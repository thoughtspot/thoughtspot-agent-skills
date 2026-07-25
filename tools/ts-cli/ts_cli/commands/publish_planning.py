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
