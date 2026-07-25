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
from ts_cli.commands.publish import (
    _org_index,
    _profile_option,
    _variable_index,
    app,
    publication_rows,
)


def _walk_closure(client: ThoughtSpotClient, guid: str):
    """Export a Model (or Table) with its associated objects and split the result.

    Returns ``(root, tables)`` where ``root`` describes the requested object and
    ``tables`` is one ``extract_table_fields`` record per Table in the closure.
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
    for item in resp.json():
        info = item.get("info") or {}
        if (info.get("status") or {}).get("status_code") == "ERROR":
            continue
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
    return root, tables


@app.command("export")
def export_closure(
    guid: str = typer.Argument(..., help="GUID of the Model (or Table) to plan publication for"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Discover an object's dependency closure and cluster its parameterizable fields.

    Walks Model to Tables to Connection, reads each table's current db / schema /
    table values, and groups them by distinct value. Each cluster is one variable
    to create: every table in a cluster needs the same value for that field, so
    twenty tables sharing a schema need one variable, not twenty.

    Clusters already carrying a `${token}` are reported as
    `already_parameterized` with the variable they use, so the command is safe to
    re-run on a partly configured Model. That is the add-a-tenant path.

    `recommended` marks databaseName and schemaName, the conventional per-tenant
    discriminators. tableName is left unrecommended because tenant tables
    normally share a name. It is a default for review, not a restriction.

    Output (JSON to stdout):
      {"root", "tables", "connection", "clusters", "existing_variables", "published_to"}

    Examples:

    \b
      ts publish export 4be2cc25-... --profile prod
      ts publish export <model-guid> --profile prod | jq '.clusters'
    """
    from ts_cli.publish_plan import build_clusters

    client = ThoughtSpotClient(resolve_profile(profile))
    root, tables = _walk_closure(client, guid)
    existing = _variable_index(client)
    clusters = build_clusters(tables, existing_variables=set(existing.values()))

    org_index = _org_index(client)
    status_resp = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [{"identifier": guid, "type": "LOGICAL_TABLE"}], "include_headers": True})
    published = publication_rows(status_resp.json(), org_index)

    connections = sorted({t["connection"] for t in tables if t.get("connection")})
    unparameterizable = sorted({t["name"] for t in tables if not t.get("connection")})
    if unparameterizable:
        print(f"Warning: {len(unparameterizable)} table(s) have no connection and are "
              f"Falcon-backed, so they cannot be parameterized or published: "
              f"{', '.join(unparameterizable)}", file=sys.stderr)
    print(json.dumps({
        "root": root,
        "tables": tables,
        "connections": connections,
        "clusters": clusters,
        "existing_variables": sorted(existing.values()),
        "published_to": published[0]["published_to"] if published else [],
        "unparameterizable_tables": unparameterizable,
    }))


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


@app.command("resolve")
def resolve(
    org: List[str] = typer.Option(..., "--org", help="Target org name (repeatable)"),
    source: str = typer.Option("uniform", "--source",
                               help="uniform | pattern | file | existing"),
    input: Optional[str] = typer.Option(None, "--input", "-i",
                                        help="`ts publish export` JSON (default: stdin)"),
    pattern: List[str] = typer.Option([], "--pattern",
                                      help="field=template, repeatable. Placeholders: "
                                           "{ORG} {ORG_UPPER} {ORG_LOWER} {ORG_ID} {VALUE}"),
    csv: Optional[str] = typer.Option(None, "--csv",
                                      help="CSV with columns org_name,variable_name,value "
                                           "(--source file)"),
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
      existing  values already assigned on the instance (re-publish / add-a-tenant).

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

    envelope = _read_input(input)
    clusters = selectable_clusters(envelope.get("clusters") or [], fields=list(field) or None)
    if not clusters:
        raise typer.BadParameter(
            "No parameterizable fields selected. Falcon-backed tables cannot be "
            "parameterized; otherwise try --field to widen the selection.")

    client = ThoughtSpotClient(resolve_profile(profile))
    known = _org_index(client)
    by_name = {name: oid for oid, name in known.items()}
    unknown = [o for o in org if o not in by_name]
    if unknown:
        raise typer.BadParameter(
            f"Unknown org(s): {', '.join(unknown)}. Known orgs: {', '.join(sorted(by_name))}")
    orgs = [{"name": o, "id": by_name[o]} for o in org]

    rows = None
    if source == "file":
        if not csv:
            raise typer.BadParameter("--csv is required for --source file")
        import csv as csv_module
        with open(csv) as handle:
            rows = list(csv_module.DictReader(handle))

    matrix = build_value_matrix(
        clusters, orgs, source=source,
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

    if plan["publish"]:
        from ts_cli.commands.publish import _post_with_explanation, build_publish_payload
        payload = build_publish_payload(plan["publish"]["identifiers"], plan["publish"]["type"],
                                        plan["publish"]["orgs"])
        _post_with_explanation(client, "/api/rest/2.0/security/metadata/publish", payload,
                               plan["publish"]["identifiers"], plan["publish"]["type"])
        print(f"published to {', '.join(plan['publish']['orgs'])}", file=sys.stderr)


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
    for step in steps:
        action = step["action"]
        if action == "skip":
            print(f"skipped {step['metadata_identifier']}.{step['field_name']}: "
                  f"{step['reason']}", file=sys.stderr)
        elif action == "unpublish":
            client.post("/api/rest/2.0/security/metadata/unpublish",
                        json=build_unpublish_payload(step["identifiers"], step["type"],
                                                     step["orgs"], include_dependencies=True))
            print(f"unpublished from {', '.join(step['orgs'])}", file=sys.stderr)
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
    print("rollback complete", file=sys.stderr)
