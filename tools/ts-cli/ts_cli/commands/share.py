"""ts share — object-level and column-level grants over security/metadata/share.

Sharing is a lower-level capability than publication: it is needed whether or not
anything was published, and the same endpoint carries column-level security. So it is
its own command group rather than a step inside `ts publish`.

Endpoint shape verified live on 2026-07-26 (see
docs/superpowers/specs/2026-07-26-ts-security-sharing-design.md §2), with two findings
that contradict the published examples:

- `message` is TOP-LEVEL, beside `notify_on_share` -- NOT inside `notification`. The
  nested form fails with `Variable "$message" of required type "String!" was not
  provided`, so nothing works until this is right. The request schema agrees: message
  and notify_on_share are top-level properties, and message is required.
- `LOGICAL_COLUMN` IS accepted and takes effect, despite being absent from the docs'
  "Supported metadata objects" prose list (it is in the metadata_type enum).

The pipeline mirrors `ts publish` and the `ts alias` source conventions:

    ts share export | ts share resolve | ts share apply     (+ ts share status)

Pure planning logic lives in `ts_cli/share_plan.py`; this module is the I/O wrapper.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.share_plan import GRANTABLE_TYPES, permission_rows

app = typer.Typer(help="Share objects and columns with groups (object and column security).")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

# LOGICAL_COLUMN is shareable even though the docs' supported-types prose omits it
# (verified live). It is never named in a manifest -- a column grant is a column_name on
# a LOGICAL_TABLE row -- but the payload builder must accept it.
SHAREABLE_TYPES = GRANTABLE_TYPES + ("LOGICAL_COLUMN",)

_DEFAULT_MESSAGE = "Access granted by ts share."


def build_share_payload(
    identifiers: List[str],
    metadata_type: str,
    permissions: List[Dict[str, Any]],
    *,
    message: str,
    notify_on_share: bool = False,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/security/metadata/share.

    ``message`` goes at the TOP LEVEL, beside ``notify_on_share``. Every published
    example nests it inside a ``notification`` object; that form is rejected with
    `Variable "$message" of required type "String!" was not provided`. The endpoint's
    own request schema lists both as top-level and marks ``message`` required.

    ``notify_on_share`` defaults to False, against the API's own default of True.
    Sharing tenant data across Orgs is a bulk administrative operation, and emailing
    every member of every group on every run is not what an operator wants; opting in
    is the safer default.

    Pure -- no I/O -- so it is unit-testable without a live instance.
    """
    if metadata_type not in SHAREABLE_TYPES:
        raise ValueError(
            f"'{metadata_type}' cannot be shared by this command. Expected one of: "
            f"{', '.join(SHAREABLE_TYPES)}.")
    deduped = list(dict.fromkeys(identifiers or []))
    if not deduped:
        raise ValueError("Specify at least one object to share")
    if not permissions:
        raise ValueError("Specify at least one principal to share with")
    if not (message or "").strip():
        raise ValueError("A non-empty message is required by the share API")
    return {
        "metadata_type": metadata_type,
        "metadata_identifiers": deduped,
        "permissions": list(permissions),
        "message": message,
        "notify_on_share": notify_on_share,
    }


# ---------------------------------------------------------------------------
# Shared I/O helpers
# ---------------------------------------------------------------------------

def _client_for_org(profile: Optional[str], org: Optional[str] = None) -> ThoughtSpotClient:
    """A client scoped to one Org.

    Groups are per-Org, so a grant naming a group only resolves inside that Org's
    context. Each Org gets its own client (and its own cached token) rather than the
    process switching TS_ORG between calls.
    """
    return ThoughtSpotClient(resolve_profile(profile), org=org)


def _read_json_envelope(input_file: Optional[str]) -> Dict[str, Any]:
    """Read a JSON envelope from --input, or stdin when not given."""
    if input_file:
        return json.loads(Path(input_file).read_text())
    if sys.stdin.isatty():
        raise typer.BadParameter("Provide --input <file> or pipe the previous stage's output in")
    return json.loads(sys.stdin.read())


def _search(client: ThoughtSpotClient, body: Dict[str, Any]) -> List[dict]:
    """POST metadata/search and return the result list, whichever envelope came back."""
    resp = client.post("/api/rest/2.0/metadata/search", json=body)
    data = resp.json()
    return data if isinstance(data, list) else (data.get("metadata") or [])


def _descriptor(hit: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
    """A metadata/search hit as {guid, name, type, subtype}."""
    header = hit.get("metadata_header") or {}
    return {
        "guid": hit.get("metadata_id") or header.get("id") or "",
        "name": hit.get("metadata_name") or header.get("name") or fallback_name,
        "type": hit.get("metadata_type") or "LOGICAL_TABLE",
        "subtype": header.get("type") or "",
    }


def _try_search(client: ThoughtSpotClient, metadata: Dict[str, Any],
                record_size: int) -> List[dict]:
    """One metadata/search attempt, swallowing the failure so the next can run.

    Resolution walks several candidate types; a 400 on one of them is expected, not
    an error worth surfacing.
    """
    try:
        return _search(client, {"metadata": [metadata], "include_headers": True,
                                "record_size": record_size})
    except Exception:
        return []


def _resolve_object(client: ThoughtSpotClient, identifier: str) -> Dict[str, Any]:
    """Resolve a GUID or name to {guid, name, type, subtype}, failing loudly.

    A GUID resolves untyped and identifies at most one object. A NAME needs its type
    supplied, so each grantable type is tried in turn, and an exact-name match is
    REQUIRED -- an ambiguous name is refused rather than resolved to the first hit.
    That matters more here than in most lookups: silently picking one of two
    same-named tables would grant a tenant access to the wrong data.
    """
    by_guid = _try_search(client, {"identifier": identifier}, 1)
    if by_guid:
        return _descriptor(by_guid[0], identifier)

    for obj_type in GRANTABLE_TYPES:
        # A small page, then an exact-name filter: enough to detect ambiguity without
        # turning a bounded lookup into a listing.
        hits = _try_search(client, {"identifier": identifier, "type": obj_type}, 10)
        exact = [h for h in hits if h.get("metadata_name") == identifier]
        if len(exact) > 1:
            raise typer.BadParameter(
                f"'{identifier}' matches {len(exact)} {obj_type} objects "
                f"({', '.join(h.get('metadata_id', '?') for h in exact)}). Pass the GUID "
                f"of the one you mean -- guessing which object to share would be unsafe.")
        if exact:
            return _descriptor(exact[0], identifier)

    raise typer.BadParameter(
        f"Could not resolve '{identifier}'. Expected a GUID, or the exact name of one of: "
        f"{', '.join(GRANTABLE_TYPES)}.")


def _table_columns(client: ThoughtSpotClient, table_guid: str) -> List[Dict[str, str]]:
    """[{guid, name}] for a LOGICAL_TABLE's columns, via include_details.

    Column GUIDs are what LOGICAL_COLUMN sharing needs, and they are not in the
    Table TML -- metadata/search with include_details is the one place they surface.
    """
    hits = _search(client, {"metadata": [{"identifier": table_guid, "type": "LOGICAL_TABLE"}],
                            "include_details": True, "include_headers": True,
                            "include_hidden_objects": True})
    if not hits:
        return []
    columns = (hits[0].get("metadata_detail") or {}).get("columns") or []
    resolved: List[Dict[str, str]] = []
    for column in columns:
        header = column.get("header") or {}
        if header.get("id") and header.get("name"):
            resolved.append({"guid": header["id"], "name": header["name"]})
    return resolved


def _fetch_permissions(client: ThoughtSpotClient, targets: List[Dict[str, str]],
                       groups: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Read current grants for a set of objects, normalised to flat rows.

    ``permission_type: DEFINED`` asks for access that came from SHARING rather than from
    group privileges -- which is what a before/after check on `ts share` should compare.
    """
    if not targets:
        return []
    body: Dict[str, Any] = {
        "metadata": [{"identifier": t["guid"], "type": t["type"]} for t in targets],
        "record_offset": 0, "record_size": -1,
        "permission_type": "DEFINED",
    }
    if groups:
        body["principals"] = [{"type": "USER_GROUP", "identifier": g} for g in groups]
    resp = client.post("/api/rest/2.0/security/metadata/fetch-permissions", json=body,
                       raise_for_status=False)
    if not resp.ok:
        print(f"Warning: could not read permissions "
              f"(HTTP {resp.status_code}): {' '.join((resp.text or '').split())[:300]}",
              file=sys.stderr)
        return []
    return permission_rows(resp.json())


# ---------------------------------------------------------------------------
# ts share export
# ---------------------------------------------------------------------------

@app.command("export")
def export_cmd(
    guids: List[str] = typer.Argument(..., help="One or more object GUIDs or names "
                                              "(Table, Model, Liveboard or Answer)"),
    org: List[str] = typer.Option([], "--org",
                                  help="Read current grants in this Org (repeatable). "
                                       "Omit to read only the current Org."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Describe the objects to be shared, their columns, and who can already see them.

    The first stage of the pipeline. Resolves each identifier, lists the columns of every
    LOGICAL_TABLE (column GUIDs are what LOGICAL_COLUMN sharing needs, and they are absent
    from TML), and reads the grants already in place in each named Org so a later apply
    can be compared against a real baseline.

    Groups are per-Org, so each --org is read through its own org-scoped token.

    Output (JSON to stdout):
      {"objects": [{"guid", "name", "type", "subtype", "columns": [{"guid", "name"}]}],
       "orgs": [...],
       "current_grants": {"<org>": [{"guid", "name", "type", "principal_type",
                                     "principal_id", "principal_name", "permission",
                                     "shared_permission"}]}}

    Examples:

    \b
      ts share export <table-guid> -p prod
      ts share export <table-guid> <liveboard-guid> --org ORG1 --org ORG2 -p prod
      ts share export T2_PUBLISH --org ORG1 -p prod | ts share resolve --org ORG1 \\
        --source uniform --group Analyst --share-mode READ_ONLY -p prod
    """
    base = _client_for_org(profile)
    objects: List[Dict[str, Any]] = []
    for identifier in dict.fromkeys(guids):
        resolved = _resolve_object(base, identifier)
        resolved["columns"] = (_table_columns(base, resolved["guid"])
                               if resolved["type"] == "LOGICAL_TABLE" else [])
        objects.append(resolved)
        print(f"resolved {identifier} -> {resolved['name']} ({resolved['type']}, "
              f"{len(resolved['columns'])} column(s))", file=sys.stderr)

    targets = [{"guid": o["guid"], "type": o["type"]} for o in objects]
    orgs = list(dict.fromkeys(org))
    current: Dict[str, List[Dict[str, Any]]] = {}
    for org_name in orgs:
        client = _client_for_org(profile, org_name)
        current[org_name] = _fetch_permissions(client, targets)
    if not orgs:
        current[""] = _fetch_permissions(base, targets)

    print(json.dumps({"objects": objects, "orgs": orgs, "current_grants": current}))


# ---------------------------------------------------------------------------
# ts share resolve
# ---------------------------------------------------------------------------

def _validated_share_mode(orgs: List[str], groups: List[str], share_mode: str) -> str:
    """The normalised share mode, with the audience arguments checked first.

    Groups and share mode have no defaults. Sharing decides who sees tenant data, so
    the audience is always the operator's explicit input.
    """
    from ts_cli.share_plan import SHARE_MODES

    if not orgs:
        raise ValueError("--org is required (repeatable) for --source uniform")
    if not groups:
        raise ValueError("--group is required (repeatable) for --source uniform: the "
                         "audience is never inferred")
    mode = (share_mode or "").strip().upper()
    if mode not in SHARE_MODES:
        raise ValueError(f"--share-mode '{share_mode}' is not valid. Expected one of: "
                         f"{', '.join(SHARE_MODES)}")
    return mode


def _validated_columns(objects: List[Dict[str, Any]],
                       columns: Optional[List[str]]) -> List[str]:
    """The requested column names, refusing any no exported object carries.

    A typo would otherwise silently produce an empty grant set, which reads as
    "nothing needed doing" rather than "you asked for the wrong column".
    """
    wanted = list(dict.fromkeys(columns or []))
    if not wanted:
        return []
    available = {c["name"] for o in objects for c in o.get("columns") or []}
    unknown = [c for c in wanted if c not in available]
    if unknown:
        raise ValueError(
            f"No exported object has column(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(available)) or '(none)'}")
    return wanted


def expand_uniform_grants(
    objects: List[Dict[str, Any]],
    orgs: List[str],
    groups: List[str],
    share_mode: str,
    columns: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Cross the exported objects with every Org and group at one share mode.

    The common case: the multi-tenancy pattern uses the same group names in every
    tenant Org, so per-Org variation is the exception rather than the rule. `file`
    and `db` sources express that variation when it exists, without making every
    tenant enumerate identical rows.

    With ``columns``, the grants land on those columns instead of on the object.

    Pure -- no I/O.
    """
    mode = _validated_share_mode(orgs, groups, share_mode)
    wanted = _validated_columns(objects, columns)

    def _column_names(obj: Dict[str, Any]) -> List[str]:
        if not wanted:
            return [""]  # "" means the grant is on the object itself
        return [c["name"] for c in obj.get("columns") or [] if c["name"] in wanted]

    return [
        {"org_name": org, "object_identifier": obj["name"], "object_type": obj["type"],
         "column_name": column_name, "group_name": group, "share_mode": mode}
        for org in dict.fromkeys(orgs)
        for obj in objects
        for column_name in _column_names(obj)
        for group in dict.fromkeys(groups)
    ]


def _resolve_one(grant: Dict[str, str], obj: Dict[str, Any]) -> Dict[str, Any]:
    """One grant with its GUIDs attached, and its type taken from the real object.

    ``object_type`` comes from the envelope rather than the manifest: a hand-authored
    row that guessed LOGICAL_TABLE for a Liveboard would otherwise build a payload with
    the wrong metadata_type.
    """
    row = dict(grant)
    row["object_guid"] = obj["guid"]
    row["object_type"] = obj["type"]
    row["column_guid"] = ""
    if not grant.get("column_name"):
        return row

    match = next((c for c in obj.get("columns") or []
                  if c["name"] == grant["column_name"]), None)
    if not match:
        raise ValueError(
            f"Table '{obj.get('name')}' has no column '{grant['column_name']}'. "
            f"Columns: "
            f"{', '.join(c['name'] for c in obj.get('columns') or []) or '(none)'}")
    row["column_guid"] = match["guid"]
    return row


def resolve_guids(grants: List[Dict[str, str]],
                  objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach ``object_guid`` and ``column_guid`` to each grant from the export envelope.

    Names are what an operator writes in a manifest; GUIDs are what the API needs.
    An unmatched name is an error rather than a skip: a dropped grant is either data a
    tenant cannot see or, if the drop is on a NO_ACCESS row, data they still can.

    Pure -- no I/O.
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    for obj in objects or ():
        for key in (obj.get("name"), obj.get("guid")):
            if key:
                by_key[str(key)] = obj

    resolved: List[Dict[str, Any]] = []
    for grant in grants or ():
        obj = by_key.get(str(grant["object_identifier"]))
        if not obj:
            known = ", ".join(sorted(str(o.get("name") or "") for o in objects or ()))
            raise ValueError(
                f"Object '{grant['object_identifier']}' is not in the export envelope. "
                f"Add it to `ts share export`, or correct the manifest. "
                f"Exported: {known or '(none)'}")
        resolved.append(_resolve_one(grant, obj))
    return resolved


def _get_sf_cursor(sf_profile: Optional[str]):
    """Delegates to the shared helper in commands/load.py.

    Imported lazily, as elsewhere in the CLI, so the Snowflake connector is not pulled
    in on every invocation.
    """
    from ts_cli.commands.load import get_sf_cursor
    return get_sf_cursor(sf_profile)


def _load_manifest_rows(source: str, csv_path: Optional[str], table: Optional[str],
                        sf_profile: Optional[str]) -> List[Dict[str, Any]]:
    """Read the grant manifest for --source file or --source db.

    Both produce the same rows, so the parser does not care which was used.
    """
    if source == "file":
        if not csv_path:
            raise typer.BadParameter("--csv is required for --source file")
        import csv as csv_module
        with Path(csv_path).open() as handle:
            return list(csv_module.DictReader(handle))
    if not sf_profile or not table:
        raise typer.BadParameter("--sf-profile and --table are required for --source db")
    cursor = _get_sf_cursor(sf_profile)
    cursor.execute(f"SELECT * FROM {table}")  # noqa: S608 - operator-supplied table name
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _existing_groups(client: ThoughtSpotClient) -> set:
    """Every group name visible in this client's Org, auto-paginated.

    Sharing to a group that does not exist fails loudly (code 13003), so this is not a
    safety net against silent damage -- it is what turns a mid-apply failure into a
    plan-time message naming the Org and the group.
    """
    names: set = set()
    page_size = 200
    offset = 0
    while True:
        resp = client.post("/api/rest/2.0/groups/search",
                           json={"record_offset": offset, "record_size": page_size})
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        names.update(g.get("name") for g in page if g.get("name"))
        if len(page) < page_size:
            break
        offset += page_size
    return names


def _check_groups_exist(profile: Optional[str], grants: List[Dict[str, Any]]) -> None:
    """Fail naming every (Org, group) pair that does not exist, not just the first."""
    wanted: Dict[str, set] = {}
    for grant in grants:
        wanted.setdefault(grant["org_name"], set()).add(grant["group_name"])

    missing: List[str] = []
    for org_name in sorted(wanted):
        try:
            available = _existing_groups(_client_for_org(profile, org_name))
        except Exception as exc:
            print(f"Warning: could not list groups in org '{org_name}' ({exc}); "
                  f"skipping the existence check there.", file=sys.stderr)
            continue
        for group in sorted(wanted[org_name] - available):
            missing.append(f"  org '{org_name}': group '{group}' does not exist")

    if missing:
        raise typer.BadParameter(
            "Refusing to plan: these grants name groups that do not exist.\n"
            + "\n".join(missing)
            + "\nGroups are per-Org: a group in the Primary Org is not the same "
              "principal as a same-named group in a tenant Org. Create them, or "
              "correct the manifest.")


def _raw_grants_for_source(
    source: str, objects: List[Dict[str, Any]], envelope: Dict[str, Any],
    org: List[str], group: List[str], share_mode: Optional[str], column: List[str],
    csv_path: Optional[str], table: Optional[str], sf_profile: Optional[str],
) -> List[Dict[str, Any]]:
    """The manifest rows for the chosen source, before parsing and resolution."""
    if source != "uniform":
        return _load_manifest_rows(source, csv_path, table, sf_profile)

    if not share_mode:
        raise typer.BadParameter("--share-mode is required for --source uniform")
    try:
        return list(expand_uniform_grants(
            objects, list(org) or list(envelope.get("orgs") or []),
            list(group), share_mode, columns=list(column) or None))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _parse_filter_resolve(raw_grants: List[Dict[str, Any]], objects: List[Dict[str, Any]],
                          orgs: List[str], apply_org_filter: bool) -> List[Dict[str, Any]]:
    """Manifest rows to resolved grants, turning any rule breach into a usage error.

    The --org filter applies AFTER parsing, so it matches the normalised org_name
    whatever case or header style the source used.
    """
    from ts_cli.share_plan import parse_grant_rows

    try:
        grants = parse_grant_rows(raw_grants)
        if apply_org_filter and orgs:
            wanted = set(orgs)
            grants = [g for g in grants if g["org_name"] in wanted]
        return resolve_guids(grants, objects)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _grant_summary(resolved: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts an operator can sanity-check the plan against before applying it."""
    column_grants = sum(1 for g in resolved if g["column_name"])
    return {
        "orgs": sorted({g["org_name"] for g in resolved}),
        "groups": sorted({g["group_name"] for g in resolved}),
        "object_grants": len(resolved) - column_grants,
        "column_grants": column_grants,
    }


def _refuse_conflicts(resolved: List[Dict[str, Any]]) -> None:
    """Exit 1 on any table/column exclusivity conflict, naming each one."""
    from ts_cli.share_plan import find_exclusivity_conflicts, format_conflicts

    conflicts = find_exclusivity_conflicts(resolved)
    if conflicts:
        print(format_conflicts(conflicts), file=sys.stderr)
        raise typer.Exit(1)


@app.command("resolve")
def resolve_cmd(
    org: List[str] = typer.Option([], "--org", help="Target Org name (repeatable)"),
    source: str = typer.Option("uniform", "--source",
                               help="uniform | file | db"),
    group: List[str] = typer.Option([], "--group",
                                    help="Group to grant to (repeatable, --source uniform). "
                                         "Required: the audience is never inferred."),
    share_mode: Optional[str] = typer.Option(None, "--share-mode",
                                             help="READ_ONLY | MODIFY | NO_ACCESS "
                                                  "(--source uniform)"),
    column: List[str] = typer.Option([], "--column",
                                     help="Grant at COLUMN level on these columns instead of "
                                          "at object level (repeatable, --source uniform)"),
    input_file: Optional[str] = typer.Option(None, "--input", "-i",
                                             help="`ts share export` JSON (default: stdin)"),
    csv_path: Optional[str] = typer.Option(None, "--csv",
                                           help="CSV with the TS_SHARE_GRANTS columns "
                                                "(--source file)"),
    table: Optional[str] = typer.Option(None, "--table",
                                        help="Snowflake table with the same columns "
                                             "(--source db), e.g. DB.SCHEMA.TS_SHARE_GRANTS"),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
                                             help="Snowflake profile for --source db"),
    init_table: bool = typer.Option(False, "--init-table",
                                    help="Print CREATE TABLE DDL for TS_SHARE_GRANTS and exit"),
    skip_group_check: bool = typer.Option(False, "--skip-group-check",
                                          help="Do not verify that each group exists in its "
                                               "Org. Faster on a large manifest; a missing "
                                               "group then fails at apply time (code 13003)."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Build the grant manifest, resolve it to GUIDs, and refuse an unsafe plan.

    Sources:

    \b
      uniform  the same grants in every target Org -- the common case, since the
               pattern uses the same group names per tenant. Requires --group and
               --share-mode; add --column to grant at column level instead.
      file     a CSV of org_name,object_identifier,object_type,column_name,
               group_name,share_mode.
      db       a Snowflake table with those same columns, for a governed deployment.
               --init-table prints the DDL.

    Two refusals happen here rather than mid-apply:

    \b
      1. Table and column grants for the same (org, table, group). A table share grants
         EVERY column in the table, so the table grant silently defeats the column
         grants beside it. Never both.
      2. A group that does not exist in its Org.

    Output (JSON to stdout):
      {"objects", "grants": [... + object_guid/column_guid], "summary"}

    Examples:

    \b
      ts share resolve --init-table
      ts share export <guid> -p prod | ts share resolve --org ORG1 --org ORG2 \\
        --source uniform --group Analyst --share-mode READ_ONLY -p prod
      ts share export <guid> -p prod | ts share resolve --org ORG1 --source uniform \\
        --group Analyst --share-mode READ_ONLY --column PROD_NM --column AMOUNT -p prod
      ts share resolve -i export.json --source file --csv grants.csv -p prod
    """
    from ts_cli.share_plan import SHARE_TABLE_DDL

    if init_table:
        print(SHARE_TABLE_DDL)
        return
    if source not in ("uniform", "file", "db"):
        raise typer.BadParameter(f"Unknown source {source!r}. Use uniform, file or db.")

    envelope = _read_json_envelope(input_file)
    objects = envelope.get("objects") or []
    if not objects:
        raise typer.BadParameter("The export envelope has no objects. Run `ts share export` first.")

    raw_grants = _raw_grants_for_source(source, objects, envelope, org, group, share_mode,
                                        column, csv_path, table, sf_profile)
    resolved = _parse_filter_resolve(raw_grants, objects, list(org),
                                     apply_org_filter=source != "uniform")
    if not resolved:
        raise typer.BadParameter("No grants to plan. Check the source, --org filter and manifest.")

    _refuse_conflicts(resolved)
    if not skip_group_check:
        _check_groups_exist(profile, resolved)

    summary = _grant_summary(resolved)
    print(f"planned {len(resolved)} grant(s): {summary['object_grants']} object-level, "
          f"{summary['column_grants']} column-level, across "
          f"{len(summary['orgs'])} org(s)", file=sys.stderr)
    print(json.dumps({"objects": objects, "grants": resolved, "summary": summary}))
