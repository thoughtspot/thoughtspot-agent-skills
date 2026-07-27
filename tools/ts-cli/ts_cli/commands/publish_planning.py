"""ts publish export / resolve — the planning half of Orgs Publishing.

Attaches to the SAME `app` Typer group defined in `ts_cli/commands/publish.py`
rather than registering its own, so the subcommands appear under `ts publish`
(the `dependency_apply.py` pattern). `cli.py` imports this module to run the
`@app.command` registration.

Split out of publish.py to keep both modules under the file-size gate: this one
holds discovery and planning, publish.py holds the publish/unpublish/status
calls and the shared payload builders.

Pure planning logic lives in `ts_cli/publish_plan.py`; this module is the I/O
wrapper around it.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.publish_plan import publish_type_for_root
from ts_cli.commands.publish import (
    _org_index,
    _profile_option,
    _variable_index,
    app,
    publication_rows,
)


def _walk_closure(client: ThoughtSpotClient, guid: str):
    """Export a Model (or Table) with its associated objects and split the result.

    Returns ``(root, tables, member_guids)``. ``root`` describes the requested
    object, ``tables`` is one ``extract_table_fields`` record per Table, and
    ``member_guids`` is every object in the closure including intermediate Models
    -- which the cohort pre-check needs, since a cohort column is owned by the
    Model rather than by the root or by any Table.

    A sibling whose TML fails to parse is warned about and skipped rather than
    sinking the whole walk.
    """
    from ts_cli.commands.tml import parse_edoc
    from ts_cli.publish_plan import extract_table_fields

    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": guid, "type": "LOGICAL_TABLE"}],
        "export_fqn": True,
        "export_associated": True,
        "formattype": "YAML",
    })

    root: Dict[str, Any] = {}
    tables: List[Dict[str, Any]] = []
    members: List[str] = []
    for item in resp.json():
        info = item.get("info") or {}
        if (info.get("status") or {}).get("status_code") == "ERROR":
            continue
        if info.get("id"):
            members.append(info["id"])
        try:
            doc = parse_edoc(item.get("edoc", ""))
        except Exception as exc:
            print(f"Warning: could not parse TML for '{info.get('name')}': {exc}", file=sys.stderr)
            continue
        doc.setdefault("guid", info.get("id"))
        if "table" in doc:
            tables.append(extract_table_fields(doc))
        elif info.get("id") == guid:
            root = {"guid": info.get("id"), "name": info.get("name"), "type": info.get("type")}

    if not root:
        root = {"guid": guid, "name": (tables[0]["name"] if tables else None), "type": "table"}
    return root, tables, members


# Mirrors the ts alias convention: one table per concern, emitted by --init-table.
# TS_PUBLISH_OBJECTS answers "what do we publish"; TS_PUBLISH_VARIABLES answers
# "what value does each variable take in each Org". Secrets never belong here --
# a variable marked sensitive is populated out of band by an admin.
_PUBLISH_TABLES_DDL = (
    "CREATE TABLE IF NOT EXISTS TS_PUBLISH_OBJECTS (\n"
    "    identifier       VARCHAR NOT NULL,\n"
    "    type             VARCHAR,\n"
    "    with_dependents  BOOLEAN DEFAULT FALSE,\n"
    "    updated_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),\n"
    "    PRIMARY KEY (identifier)\n"
    ");\n\n"
    "CREATE TABLE IF NOT EXISTS TS_PUBLISH_VARIABLES (\n"
    "    org_name         VARCHAR NOT NULL,\n"
    "    variable_name    VARCHAR NOT NULL,\n"
    "    value            VARCHAR NOT NULL,\n"
    "    updated_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),\n"
    "    PRIMARY KEY (org_name, variable_name)\n"
    ");"
)


def _get_sf_cursor(sf_profile: Optional[str]):
    """Delegates to the shared helper in commands/load.py.

    Imported lazily, as elsewhere in this module, so the Snowflake connector is
    not pulled in on every CLI invocation.
    """
    from ts_cli.commands.load import get_sf_cursor
    return get_sf_cursor(sf_profile)


def _fetch_table_rows(sf_profile: Optional[str], table: Optional[str],
                      what: str) -> List[Dict[str, Any]]:
    """Read every row of a manifest table as a list of dicts."""
    if not sf_profile or not table:
        print(f"Error: --sf-profile and --table are required to read {what} from a database",
              file=sys.stderr)
        raise SystemExit(1)
    cursor = _get_sf_cursor(sf_profile)
    cursor.execute(f"SELECT * FROM {table}")  # noqa: S608 - operator-supplied table name
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _read_object_manifest(objects_file: Optional[str], objects_table: Optional[str],
                          sf_profile: Optional[str]) -> List[Dict[str, Any]]:
    """Load the object manifest from a CSV or a Snowflake table."""
    from ts_cli.publish_plan import parse_object_rows
    if objects_file:
        import csv as csv_module
        with open(objects_file) as handle:
            return parse_object_rows(csv_module.DictReader(handle))
    if objects_table:
        return parse_object_rows(_fetch_table_rows(sf_profile, objects_table, "objects"))
    return []


def _targets_from_manifest(client: ThoughtSpotClient,
                           manifest: List[Dict[str, Any]]) -> List[str]:
    """Manifest rows to a de-duplicated target list, honouring per-row dependents."""
    expandable = [m["identifier"] for m in manifest if m["with_dependents"]]
    targets = [m["identifier"] for m in manifest]
    if expandable:
        targets = _expand_dependents(client, expandable) + targets
    return list(dict.fromkeys(targets))


def _publish_all(client: ThoughtSpotClient, plan: Dict[str, Any]) -> None:
    """Execute a plan's publish steps, one call per type."""
    from ts_cli.commands.publish import _post_with_explanation, build_publish_payload
    for entry in plan.get("publish") or []:
        payload = build_publish_payload(entry["identifiers"], entry["type"], entry["orgs"])
        _post_with_explanation(client, "/api/rest/2.0/security/metadata/publish", payload,
                               entry["identifiers"], entry["type"])
        print(f"published {len(entry['identifiers'])} {entry['type']} to "
              f"{', '.join(entry['orgs'])}", file=sys.stderr)


def build_closure(client: ThoughtSpotClient, targets: List[str]) -> Dict[str, Any]:
    """Walk every target, merge the closures, and attach publication + cohort state.

    Shared by `ts publish export` and `ts publish run` so the interactive and the
    scheduled paths plan from identical data.
    """
    from ts_cli.publish_plan import merge_closures

    existing = _variable_index(client)
    org_index = _org_index(client)

    closures: List[Dict[str, Any]] = []
    members: set = set()
    for guid in targets:
        root, tables, seen = _walk_closure(client, guid)
        members.update(seen)
        status = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"identifier": guid,
                          "type": publish_type_for_root(root.get("type"))}],
            "include_headers": True})
        rows = publication_rows(status.json(), org_index)
        closures.append({"root": root, "tables": tables,
                         "existing_variables": set(existing.values()),
                         "owner_org": rows[0]["owner_org"] if rows else None,
                         "published_to": rows[0]["published_to"] if rows else []})

    merged = merge_closures(closures)
    merged["published_to"] = sorted({o for c in closures for o in c["published_to"]})
    merged["cohort_columns"] = _cohort_columns(client, sorted(members))
    return merged


def _expand_dependents(client: ThoughtSpotClient, guids: List[str]) -> List[str]:
    """Add every Answer and Liveboard riding on the given objects.

    Cascade carries dependencies DOWNWARD on publish but never reaches siblings,
    so an Answer beside a Liveboard on the same Model must be published in its own
    right. This is the upward walk that finds them. Order is preserved and the
    originals stay first.
    """
    found = list(guids)
    for guid in guids:
        try:
            resp = client.post("/api/rest/2.0/metadata/search", json={
                "metadata": [{"identifier": guid, "type": "LOGICAL_TABLE"}],
                "include_dependent_objects": True,
                "dependent_object_version": "V2",
                "record_size": -1, "record_offset": 0})
        except Exception as exc:
            print(f"Warning: could not walk dependents of {guid}: {exc}", file=sys.stderr)
            continue
        from ts_cli.commands.metadata import _normalize_dependents_response
        for row in _normalize_dependents_response(resp.json()):
            if row["type"] in ("ANSWER", "LIVEBOARD") and row["guid"] not in found:
                found.append(row["guid"])
    return found


def _cohort_columns(client: ThoughtSpotClient, member_guids: List[str]) -> List[str]:
    """Names of cohort columns owned by any object in the closure.

    A cohort column on a Model blocks publishing that Model and every Answer and
    Liveboard on it, used or not (verified live). Catching it here turns a
    last-step refusal into something the caller sees before doing any work.
    """
    try:
        resp = client.post("/api/rest/2.0/metadata/search",
                           json={"metadata": [{"type": "LOGICAL_COLUMN"}],
                                 "include_headers": True, "record_size": -1})
    except Exception:
        return []
    owners = set(member_guids)
    return sorted({
        r.get("metadata_name") for r in resp.json()
        if str((r.get("metadata_header") or {}).get("type", "")).startswith("COHORT")
        and (r.get("metadata_header") or {}).get("owner") in owners
    } - {None})


@app.command("export")
def export_closure(
    guids: List[str] = typer.Argument(None, help="One or more GUIDs to plan publication for. "
                                                 "Any type: Table, Model, Answer or Liveboard. "
                                                 "Omit when using --objects-file/--objects-table."),
    objects_file: Optional[str] = typer.Option(None, "--objects-file",
                                               help="CSV manifest of objects to publish "
                                                    "(identifier,type,with_dependents)"),
    objects_table: Optional[str] = typer.Option(None, "--objects-table",
                                                help="Snowflake table holding the same manifest, "
                                                     "e.g. DB.SCHEMA.TS_PUBLISH_OBJECTS"),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
                                             help="Snowflake profile for --objects-table"),
    with_dependents: bool = typer.Option(False, "--with-dependents",
                                         help="Also include every Answer and Liveboard riding "
                                              "on the given objects. Publish cascades DOWN to "
                                              "dependencies but never UP to siblings, so those "
                                              "need publishing in their own right."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Discover the closure of one or more objects and cluster their parameterizable fields.

    Works from any anchor. From a Liveboard or Answer the walk goes down to the
    Model and Tables that need variables; publishing then cascades back down to
    them. From a Model or Table it finds the Tables directly, and
    --with-dependents adds the content riding on top.

    Fields are grouped by DISTINCT VALUE across every root, so two objects sharing
    a schema still need one variable rather than one each. Tables reached by more
    than one root are de-duplicated, so nothing is parameterized twice.

    Output (JSON to stdout):
      {"roots", "tables", "connections", "clusters", "existing_variables",
       "owner_org", "unparameterizable_tables", "cohort_columns"}

    Examples:

    \b
      ts publish export <model-guid> --profile prod
      ts publish export <liveboard-guid> --profile prod
      ts publish export <model-guid> --with-dependents --profile prod
      ts publish export <lb-guid> <answer-guid> --profile prod
    """
    from ts_cli.publish_plan import merge_closures

    manifest = _read_object_manifest(objects_file, objects_table, sf_profile)
    if manifest and guids:
        raise typer.BadParameter("Give either GUID arguments or a manifest, not both")
    if not manifest and not guids:
        raise typer.BadParameter("Provide GUIDs, --objects-file or --objects-table")

    client = ThoughtSpotClient(resolve_profile(profile))
    targets = (_targets_from_manifest(client, manifest) if manifest
               else list(dict.fromkeys(guids)))
    if with_dependents:
        expanded = _expand_dependents(client, targets)
        if len(expanded) > len(targets):
            print(f"--with-dependents added {len(expanded) - len(targets)} object(s) "
                  f"riding on the selection.", file=sys.stderr)
        targets = expanded

    existing = _variable_index(client)
    org_index = _org_index(client)

    closures = []
    closure_members: set = set()
    for guid in targets:
        root, tables, members = _walk_closure(client, guid)
        closure_members.update(members)
        status = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"identifier": guid,
                          "type": publish_type_for_root(root.get("type"))}],
            "include_headers": True})
        rows = publication_rows(status.json(), org_index)
        closures.append({"root": root, "tables": tables,
                         "existing_variables": set(existing.values()),
                         "owner_org": rows[0]["owner_org"] if rows else None,
                         "published_to": rows[0]["published_to"] if rows else []})

    merged = merge_closures(closures)
    merged["published_to"] = sorted({o for c in closures for o in c["published_to"]})
    # Check every object in the closure, not just the roots: a cohort column is
    # owned by the Model, so selecting only a Liveboard would otherwise miss it --
    # which is exactly the selection that fails at publish time.
    merged["cohort_columns"] = _cohort_columns(client, sorted(closure_members))

    if merged["unparameterizable_tables"]:
        print(f"Warning: {len(merged['unparameterizable_tables'])} table(s) are Falcon-backed "
              f"and cannot be parameterized or published: "
              f"{', '.join(merged['unparameterizable_tables'])}", file=sys.stderr)
    if merged["cohort_columns"]:
        print(f"Warning: cohort column(s) {', '.join(merged['cohort_columns'])} are defined on "
              f"this selection. Cohort publishing is not supported, and the block is Model-wide: "
              f"it stops the Model and every Answer or Liveboard on it, used or not.",
              file=sys.stderr)
    print(json.dumps(merged))


def _read_input(path: Optional[str]) -> Dict[str, Any]:
    """Load a `ts publish export` envelope from a file, or stdin when omitted."""
    if path:
        with open(path) as handle:
            return json.load(handle)
    if sys.stdin.isatty():
        raise typer.BadParameter("Provide --input <file> or pipe `ts publish export` output in")
    return json.load(sys.stdin)


def _existing_values(client: ThoughtSpotClient) -> Dict[str, Dict[str, str]]:
    """Current per-Org assignments, keyed {variable_name: {org_name: value}}."""
    out: Dict[str, Dict[str, str]] = {}
    page_size = 200
    offset = 0
    while True:
        resp = client.post("/api/rest/2.0/template/variables/search",
                           json={"record_offset": offset, "record_size": page_size,
                                 "response_content": "METADATA_AND_VALUES"})
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        for var in page:
            per_org = out.setdefault(var.get("name"), {})
            for entry in var.get("values") or []:
                if entry.get("org_identifier"):
                    per_org[entry["org_identifier"]] = entry.get("value")
        if len(page) < page_size:
            break
        offset += page_size
    return out


def _resolve_orgs(client: ThoughtSpotClient, names: List[str]) -> List[Dict[str, Any]]:
    """Map requested org names to {name, id}, failing on an unknown one."""
    by_name = {name: oid for oid, name in _org_index(client).items()}
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise typer.BadParameter(
            f"Unknown org(s): {', '.join(unknown)}. Known orgs: {', '.join(sorted(by_name))}")
    return [{"name": n, "id": by_name[n]} for n in names]


def _load_value_rows(source: str, path: Optional[str], table: Optional[str],
                     sf_profile: Optional[str]) -> Optional[List[Dict[str, str]]]:
    """Read the variable-value manifest for --source file or --source db.

    Both produce the same rows (org_name, variable_name, value), so the matrix
    builder does not care which was used.
    """
    from ts_cli.publish_plan import parse_value_rows
    if source == "file":
        if not path:
            raise typer.BadParameter("--csv is required for --source file")
        import csv as csv_module
        with open(path) as handle:
            return parse_value_rows(csv_module.DictReader(handle))
    if source == "db":
        return parse_value_rows(_fetch_table_rows(sf_profile, table, "variable values"))
    return None


@app.command("resolve")
def resolve(
    org: List[str] = typer.Option([], "--org", help="Target org name (repeatable)"),
    source: str = typer.Option("uniform", "--source",
                               help="uniform | pattern | file | db | existing"),
    input: Optional[str] = typer.Option(None, "--input", "-i",
                                        help="`ts publish export` JSON (default: stdin)"),
    pattern: List[str] = typer.Option([], "--pattern",
                                      help="field=template, repeatable. Placeholders: "
                                           "{ORG} {ORG_UPPER} {ORG_LOWER} {ORG_ID} {VALUE}"),
    csv: Optional[str] = typer.Option(None, "--csv",
                                      help="CSV with columns org_name,variable_name,value "
                                           "(--source file)"),
    table: Optional[str] = typer.Option(None, "--table",
                                        help="Snowflake table with the same columns "
                                             "(--source db), e.g. DB.SCHEMA.TS_PUBLISH_VARIABLES"),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
                                             help="Snowflake profile for --source db"),
    init_table: bool = typer.Option(False, "--init-table",
                                    help="Print CREATE TABLE DDL for the manifest tables "
                                         "(TS_PUBLISH_OBJECTS, TS_PUBLISH_VARIABLES) and exit"),
    field: List[str] = typer.Option([], "--field",
                                    help="Restrict to these fields (default: the recommended "
                                         "databaseName and schemaName)"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Build the per-Org value matrix for an exported closure.

    Sources:

    \b
      uniform   the current value, replicated to every org. The shared-table case:
                still a real variable, so publish validation stays on and a later
                divergence is one `ts variables set` rather than a structural change.
      pattern   a per-field template expanded per org, e.g. schemaName={ORG_UPPER}.
                A field with no pattern keeps its current value.
      file      a CSV of org_name,variable_name,value.
      db        a Snowflake table with those same columns, for a governed,
                scheduled deployment. --init-table prints the DDL.
      existing  values already assigned on the instance (re-publish / add-a-tenant).

    The owner (Primary) org is always included and always keeps its current
    value, whatever source is chosen. Parameterizing replaces the static
    db/schema with tokens, so without a value there the SOURCE object breaks, and
    ThoughtSpot's publish validation only checks target orgs. Expanding a pattern
    for the owner org would silently repoint the source data.

    Always emits a coverage check. Publishing fails closed on a gap and reports
    GUIDs and numeric ids; catching it here names the variable and org instead.

    Output (JSON to stdout):
      {"orgs", "variables", "assignments", "coverage": {"complete", "missing"}}

    Examples:

    \b
      ts publish export <guid> -p prod | ts publish resolve --org ORG1 --org ORG2 -p prod
      ts publish export <guid> -p prod | ts publish resolve --org ORG1 \\
        --source pattern --pattern "schemaName={ORG_UPPER}" -p prod
      ts publish resolve -i export.json --org ORG1 --source file --csv values.csv -p prod
    """
    from ts_cli.publish_plan import build_value_matrix, parse_pattern_args, selectable_clusters

    if init_table:
        print(_PUBLISH_TABLES_DDL)
        return
    if not org:
        raise typer.BadParameter("--org is required (repeatable) unless --init-table")

    envelope = _read_input(input)
    clusters = selectable_clusters(envelope.get("clusters") or [], fields=list(field) or None)
    if not clusters:
        raise typer.BadParameter(
            "No parameterizable fields selected. Falcon-backed tables cannot be "
            "parameterized; otherwise try --field to widen the selection.")

    client = ThoughtSpotClient(resolve_profile(profile))
    orgs = _resolve_orgs(client, list(org))
    rows = _load_value_rows(source, csv, table, sf_profile)

    owner_org = envelope.get("owner_org")
    if owner_org and owner_org not in org:
        print(f"Including owner org '{owner_org}': parameterizing replaces the static "
              f"db/schema with tokens, so without a value there the SOURCE object breaks. "
              f"It keeps its current value.", file=sys.stderr)

    matrix = build_value_matrix(
        clusters, orgs, source=source, owner_org=owner_org,
        patterns=parse_pattern_args(pattern),
        csv_rows=rows,
        existing_values=_existing_values(client) if source == "existing" else None,
    )

    if not matrix["coverage"]["complete"]:
        for gap in matrix["coverage"]["missing"]:
            print(f"Coverage gap: variable '{gap['variable']}' has no value for org "
                  f"'{gap['org']}'. Publishing will be refused until it does.", file=sys.stderr)
    print(json.dumps(matrix))


def _write_rollback(record: Dict[str, Any], path: Optional[str]) -> None:
    if not path:
        return
    with open(path, "w") as handle:
        json.dump(record, handle, indent=2)
    print(f"Rollback record written to {path}", file=sys.stderr)


def _run_apply(client: ThoughtSpotClient, plan: Dict[str, Any]) -> None:
    """Execute an apply plan in order, reporting each step on stderr.

    Order is load-bearing: create before assign, assign before publish. Variable
    creation tolerates an already-exists failure so a re-run is idempotent.
    """
    from urllib.parse import quote

    for variable in plan["create_variables"]:
        resp = client.post("/api/rest/2.0/template/variables/create", raise_for_status=False,
                           json={"type": variable["type"], "name": variable["name"],
                                 "is_sensitive": variable["sensitive"]})
        if resp.ok:
            print(f"created variable {variable['name']}", file=sys.stderr)
        elif "already exists" in (resp.text or "").lower():
            print(f"variable {variable['name']} already exists, reusing", file=sys.stderr)
        else:
            raise typer.BadParameter(
                f"Could not create variable '{variable['name']}': "
                f"HTTP {resp.status_code} {' '.join((resp.text or '').split())[:300]}")

    for assignment in plan["assign_values"]:
        client.post(
            f"/api/rest/2.0/template/variables/{quote(assignment['variable'], safe='')}/update-values",
            json={"operation": "REPLACE",
                  "variable_assignment": [{"assigned_values": [assignment["value"]],
                                           "org_identifier": assignment["org"]}]})
    print(f"assigned {len(plan['assign_values'])} value(s)", file=sys.stderr)

    for step in plan["parameterize"]:
        client.post("/api/rest/2.0/metadata/parameterize-fields", json={
            "metadata_type": step["metadata_type"],
            "metadata_identifier": step["metadata_identifier"],
            "field_type": "ATTRIBUTE",
            "field_names": step["field_names"],
            "variable_identifier": step["variable"]})
    print(f"parameterized {len(plan['parameterize'])} field(s)", file=sys.stderr)


@app.command("apply")
def apply_plan(
    closure: str = typer.Option(..., "--closure", "-c", help="`ts publish export` JSON file"),
    matrix: str = typer.Option(..., "--matrix", "-m", help="`ts publish resolve` JSON file"),
    publish_to: List[str] = typer.Option([], "--publish-to",
                                         help="Also publish to these orgs after wiring "
                                              "(repeatable). Omit to stop before publishing."),
    rollback_out: Optional[str] = typer.Option(None, "--rollback-out",
                                               help="Write the rollback record here. Strongly "
                                                    "recommended: unparameterize needs the "
                                                    "original values and nothing else records them."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the ordered plan and exit"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Create the variables, assign their values, parameterize the fields, and optionally publish.

    Runs in a fixed order because the platform requires it: a variable must exist
    before it takes a value, and must have a value in every target org before
    anything using it is published.

    Re-running is safe: an already-existing variable is reused, and a field already
    bound to a token is left alone.

    Output: the plan as JSON to stdout (always), progress on stderr.

    Examples:

    \b
      ts publish apply -c export.json -m matrix.json --dry-run
      ts publish apply -c export.json -m matrix.json --rollback-out rb.json -p prod
      ts publish apply -c export.json -m matrix.json --publish-to ORG1 --rollback-out rb.json -p prod
    """
    from ts_cli.publish_plan import build_apply_plan

    with open(closure) as handle:
        closure_doc = json.load(handle)
    with open(matrix) as handle:
        matrix_doc = json.load(handle)

    if not (matrix_doc.get("coverage") or {}).get("complete", True):
        gaps = ", ".join(f"{g['variable']}@{g['org']}"
                         for g in matrix_doc["coverage"].get("missing") or [])
        raise typer.BadParameter(
            f"The value matrix has coverage gaps ({gaps}). Publishing would be refused, "
            f"so this stops before changing anything. Re-run `ts publish resolve` with "
            f"values for every target org.")

    plan = build_apply_plan(closure_doc, matrix_doc, publish_orgs=list(publish_to) or None)
    print(json.dumps(plan))
    if dry_run:
        print("Dry run: nothing was changed.", file=sys.stderr)
        return

    client = ThoughtSpotClient(resolve_profile(profile))
    _write_rollback(plan["rollback"], rollback_out)
    _run_apply(client, plan)

    _publish_all(client, plan)


def _rollback_unpublish(client, step) -> Optional[str]:
    """Run one unpublish step. Return a problem description, or None on success.

    Two non-2xx outcomes are not real failures and must not strand the steps
    after this one -- `client.post` raises SystemExit, so the previous
    unconditional call aborted the whole rollback and left the parameterized
    fields and created variables behind. Both cases seen live 2026-07-27.
    """
    from ts_cli.commands.publish import build_unpublish_payload
    from ts_cli.publish_apply import (ALREADY_DONE, CONNECTION_IN_USE,
                                      classify_unpublish_failure)

    orgs = ", ".join(step["orgs"])

    def _call(include_dependencies: bool):
        return client.post(
            "/api/rest/2.0/security/metadata/unpublish", raise_for_status=False,
            json=build_unpublish_payload(step["identifiers"], step["type"], step["orgs"],
                                         include_dependencies=include_dependencies))

    resp = _call(True)
    if resp.status_code < 300:
        print(f"unpublished from {orgs}", file=sys.stderr)
        return None

    kind = classify_unpublish_failure(resp.text)
    if kind == ALREADY_DONE:
        print(f"already unpublished from {orgs} -- nothing to retract", file=sys.stderr)
        return None
    if kind == CONNECTION_IN_USE:
        # The object retraction is fine; only the cascade to the Connection is
        # refused, because another published object in that Org still needs it.
        # Retracting the object alone IS the correct rollback here -- the
        # Connection grant is not ours to remove while someone else depends on it.
        retry = _call(False)
        if retry.status_code < 300:
            print(f"unpublished from {orgs} (Connection grant retained -- another "
                  f"published object in that Org still uses it)", file=sys.stderr)
            return None
        return (f"unpublish from {orgs} failed even without dependencies: "
                f"HTTP {retry.status_code}")
    return f"unpublish from {orgs} failed: HTTP {resp.status_code} {resp.text[:200]}"


@app.command("rollback")
def rollback(
    input: str = typer.Option(..., "--input", "-i", help="Rollback record from `ts publish apply`"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the ordered steps and exit"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Undo an apply: unpublish, restore static values, delete the variables it created.

    Reverse order of apply. Unpublish uses include_dependencies so the Connection
    grant is retracted too; without that the target orgs keep it.

    Only variables the recorded run created are deleted, so a variable shared with
    another Model is never removed. A field with no recorded original value is
    skipped and reported, because unparameterize cannot run without one.

    Examples:

    \b
      ts publish rollback -i rb.json --dry-run
      ts publish rollback -i rb.json -p prod
    """
    from ts_cli.commands.publish import build_unpublish_payload
    from ts_cli.publish_plan import rollback_steps

    with open(input) as handle:
        record = json.load(handle)
    steps = rollback_steps(record)
    print(json.dumps(steps))
    if dry_run:
        print("Dry run: nothing was changed.", file=sys.stderr)
        return

    client = ThoughtSpotClient(resolve_profile(profile))
    failures: List[str] = []
    for step in steps:
        action = step["action"]
        if action == "skip":
            print(f"skipped {step['metadata_identifier']}.{step['field_name']}: "
                  f"{step['reason']}", file=sys.stderr)
        elif action == "unpublish":
            problem = _rollback_unpublish(client, step)
            if problem:
                failures.append(problem)
        elif action == "unparameterize":
            client.post("/api/rest/2.0/metadata/unparameterize", json={
                "metadata_type": step.get("metadata_type", "LOGICAL_TABLE"),
                "metadata_identifier": step["metadata_identifier"],
                "field_type": "ATTRIBUTE",
                "field_name": step["field_name"],
                "value": step["original_value"]})
        elif action == "delete_variables":
            client.post("/api/rest/2.0/template/variables/delete",
                        json={"identifiers": step["names"]})
            print(f"deleted variable(s) {', '.join(step['names'])}", file=sys.stderr)
    if failures:
        print("rollback INCOMPLETE:", file=sys.stderr)
        for problem in failures:
            print(f"  - {problem}", file=sys.stderr)
        raise typer.Exit(1)
    print("rollback complete", file=sys.stderr)


@app.command("run")
def run_publication(
    org: List[str] = typer.Option(..., "--org", help="Target org name (repeatable)"),
    objects_file: Optional[str] = typer.Option(None, "--objects-file",
                                               help="CSV manifest of objects to publish"),
    objects_table: Optional[str] = typer.Option(None, "--objects-table",
                                                help="Snowflake table holding the object manifest"),
    values_file: Optional[str] = typer.Option(None, "--values-file",
                                              help="CSV of org_name,variable_name,value"),
    values_table: Optional[str] = typer.Option(None, "--values-table",
                                               help="Snowflake table with the same columns"),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
                                             help="Snowflake profile for the manifest tables"),
    source: Optional[str] = typer.Option(None, "--source",
                                         help="Override the value source. Inferred from the "
                                              "flags given: db, file, else uniform."),
    pattern: List[str] = typer.Option([], "--pattern", help="field=template (--source pattern)"),
    field: List[str] = typer.Option([], "--field", help="Restrict to these fields"),
    rollback_out: Optional[str] = typer.Option(None, "--rollback-out",
                                               help="Write the rollback record here. Strongly "
                                                    "recommended for an unattended run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, change nothing"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Run a whole publication end to end, unattended.

    The scheduled counterpart to the interactive `export | resolve | apply`
    pipeline: same engine, no prompts, one exit code. Suitable for cron or any
    Python scheduler.

    Reads what to publish and what each variable should be from a CSV or a
    Snowflake table, plans the whole thing, and refuses to change anything unless
    the plan is complete. Specifically it stops before touching the instance if a
    variable has no value in a target org, or if a cohort column makes the
    selection unpublishable.

    Exits 0 on success, 1 on any refusal, with the reason on stderr.

    Output: the executed plan as JSON to stdout, progress on stderr.

    Examples:

    \b
      ts publish run --org ORG1 --org ORG2 \\
        --objects-table DB.SCH.TS_PUBLISH_OBJECTS \\
        --values-table  DB.SCH.TS_PUBLISH_VARIABLES \\
        --sf-profile sf --rollback-out rb.json -p prod

      ts publish run --org ORG1 --objects-file objects.csv \\
        --values-file values.csv --rollback-out rb.json -p prod --dry-run
    """
    from ts_cli.publish_plan import (
        build_apply_plan, build_value_matrix, parse_pattern_args, selectable_clusters,
    )

    if not (objects_file or objects_table):
        raise typer.BadParameter("Provide --objects-file or --objects-table")
    manifest = _read_object_manifest(objects_file, objects_table, sf_profile)
    if not manifest:
        raise typer.BadParameter("The object manifest is empty; nothing to publish")

    client = ThoughtSpotClient(resolve_profile(profile))
    targets = _targets_from_manifest(client, manifest)
    print(f"selected {len(targets)} object(s)", file=sys.stderr)

    closure = build_closure(client, targets)
    if closure["cohort_columns"]:
        print(f"Refusing to publish: cohort column(s) "
              f"{', '.join(closure['cohort_columns'])} are defined on this selection. "
              f"Cohort publishing is not supported and the block is Model-wide.",
              file=sys.stderr)
        raise typer.Exit(1)

    clusters = selectable_clusters(closure["clusters"], fields=list(field) or None)
    if not clusters:
        raise typer.BadParameter(
            "No parameterizable fields selected. Falcon-backed tables cannot be "
            "parameterized; otherwise use --field to widen the selection.")

    # Values
    resolved_source = source or ("db" if values_table else "file" if values_file else "uniform")
    rows = _load_value_rows(resolved_source, values_file, values_table, sf_profile)

    orgs = _resolve_orgs(client, list(org))
    matrix = build_value_matrix(
        clusters, orgs, source=resolved_source,
        patterns=parse_pattern_args(pattern), csv_rows=rows,
        existing_values=_existing_values(client) if resolved_source == "existing" else None,
        owner_org=closure.get("owner_org"),
    )
    if not matrix["coverage"]["complete"]:
        for gap in matrix["coverage"]["missing"]:
            print(f"Coverage gap: variable '{gap['variable']}' has no value for org "
                  f"'{gap['org']}'", file=sys.stderr)
        print("Refusing to publish: publishing would be rejected and a partial apply "
              "is worse than none.", file=sys.stderr)
        raise typer.Exit(1)

    plan = build_apply_plan(closure, matrix, publish_orgs=list(org))
    print(json.dumps(plan))
    if dry_run:
        print("Dry run: nothing was changed.", file=sys.stderr)
        return

    _write_rollback(plan["rollback"], rollback_out)
    _run_apply(client, plan)
    _publish_all(client, plan)
