"""ts security column-rules -- Column Security Rules (CSR).

The second of the two column-security mechanisms. `ts share` carries the first
(column-level sharing, CLS); this carries CSR, and they are not interchangeable:

| | CLS (`ts share`) | CSR (here) |
|---|---|---|
| Works on published objects | yes | refused BY DEFAULT (the platform itself accepts an owning-Org CSR update on a published table, live-verified 2026-07-27; whether a tenant Org can see or use it is unverified, so this CLI blocks unless `--allow-published`) |
| Declares | every VISIBLE column per group | only the RESTRICTED columns |
| Liveboard filter on a secured column | locks | stays interactive |
| Availability | GA | Beta 10.12+, feature-flagged OFF by default |

The group is named for the mechanism, not the goal: "column security" is equally true
of `ts share`'s column grants, and conflating them is how a published object ends up
with rules that silently do not apply.

Two chains over one plan, so each route has exactly one executor:

    get | export                         read (API state, TML document)
    resolve -> apply                     the API route
    resolve -> build -> import           the TML route
    set | clear                          one-shot imperatives, no manifest

Pure logic lives in `ts_cli/csr_plan.py`; this module is the I/O wrapper. The manifest
layer lives in `security_planning.py`, split under the file-size gate the way
`share_planning.py` splits from `share.py`.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient
from ts_cli.commands.share import (  # noqa: F401 -- re-exported for security_planning
    _client_for_org,
    _profile_option,
    _read_json_envelope,
    _resolve_object,
    assert_org_context,
)
from ts_cli.csr_plan import (
    build_update_payload,
    explain_csr_error,
    normalise_fetch_response,
)
from ts_cli.publish_plan import published_org_ids

app = typer.Typer(help="Security configuration (column security rules).")
column_rules_app = typer.Typer(
    help="Column Security Rules: restrict columns to named groups (Beta, 10.12+).")
app.add_typer(column_rules_app, name="column-rules")

_FETCH_PATH = "/api/rest/2.0/security/column/rules/fetch"
_UPDATE_PATH = "/api/rest/2.0/security/column/rules/update"


def _fail(resp: Any, context: str) -> None:
    """Turn a failed CSR call into an actionable message, then exit.

    The feature-flag 403 is the one that matters most: a bare "403 Forbidden" sends an
    operator hunting for a permissions problem that is not there.
    """
    body = getattr(resp, "text", "") or ""
    status = getattr(resp, "status_code", None)
    explanation = explain_csr_error(body, status)
    if not explanation:
        explanation = f"HTTP {status} {' '.join(body.split())[:400]}"
    print(f"{context}: {explanation}", file=sys.stderr)
    raise typer.Exit(1)


def _fetch_rules(client: ThoughtSpotClient,
                 identifiers: List[str]) -> List[Dict[str, Any]]:
    """Current CSR for a set of tables, flattened to one row per (table, column).

    ``fetch`` takes many tables in one call, unlike ``update``, so this is one request
    however many tables were named.
    """
    body = {"tables": [{"identifier": i} for i in dict.fromkeys(identifiers)]}
    resp = client.post(_FETCH_PATH, json=body, raise_for_status=False)
    if not resp.ok:
        _fail(resp, "Could not read column security rules")
    return normalise_fetch_response(resp.json())


def _post_update(client: ThoughtSpotClient, payload: Dict[str, Any],
                 label: str) -> None:
    """POST one `rules/update` body.

    Success is documented as 204 with no body; live probing has seen 200. Any 2xx is
    treated as success and no body is parsed.
    """
    resp = client.post(_UPDATE_PATH, json=payload, raise_for_status=False)
    if not resp.ok:
        _fail(resp, f"Failed on {label}")
    print(f"applied {label}", file=sys.stderr)


def _published_orgs(client: ThoughtSpotClient, guid: str) -> Optional[List[Any]]:
    """The Org ids a table is published into, or None when that could not be read.

    The `metadata_header` reading is `publish_plan.published_org_ids`, shared with
    `ts publish status` rather than restated here: `orgIds` includes the OWNING Org, and
    reading it as "published into" made every table on an Orgs-enabled cluster look
    published.

    Feeds the CSR_BLOCKED refusal, which is conservative rather than a platform
    restriction: live-verified 2026-07-27, an owning-Org CSR update against a genuinely
    published table returned HTTP 204 and took effect. What is still unverified is
    whether a TENANT Org can see or use a rule set applied that way, so the CLI blocks
    by default here and `--allow-published` is the override.

    None is distinct from an empty list, and the difference is the whole point. ``[]``
    means the read succeeded and the table is published nowhere; None means the read
    failed -- a 403 on a cluster where the CSR flag is off, a 500, or no hit for the guid
    -- so publication state is UNKNOWN and the caller blocks the step rather than
    treating it as unpublished. `resolve` writes nothing, so a false block costs a
    re-run while a false pass applies CSR to a published object.
    """
    resp = client.post("/api/rest/2.0/metadata/search",
                       json={"metadata": [{"identifier": guid, "type": "LOGICAL_TABLE"}],
                             "include_headers": True},
                       raise_for_status=False)
    if not getattr(resp, "ok", False):
        print(f"Warning: could not read publication state for '{guid}': "
              f"HTTP {getattr(resp, 'status_code', '?')}. Treating it as unknown, which "
              f"blocks the step.", file=sys.stderr)
        return None
    data = resp.json()
    hits = data if isinstance(data, list) else (data.get("metadata") or [])
    if not hits:
        print(f"Warning: '{guid}' returned no metadata/search hit, so its publication "
              f"state is unknown. Treating it as unknown, which blocks the step.",
              file=sys.stderr)
        return None
    return published_org_ids(hits[0].get("metadata_header") or {})


# ---------------------------------------------------------------------------
# ts security column-rules get
# ---------------------------------------------------------------------------

@column_rules_app.command("get")
def get_cmd(
    tables: List[str] = typer.Argument(..., help="Table GUIDs or names to read"),
    org: List[str] = typer.Option([], "--org",
                                  help="Read in this Org (repeatable). Omit for the "
                                       "current Org."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Report which columns are restricted, and which groups can see each one.

    The read side of the API route, and the way to check an apply landed. Capture it
    before and after a change and diff the two: a single reading in isolation cannot
    tell you what your change did.

    Output (JSON to stdout):
      [{"org", "table_guid", "obj_id", "column_id", "column_name", "group_names",
        "source_table_name"}]

    Examples:

    \b
      ts security column-rules get T2_PUBLISH -p prod
      ts security column-rules get T1 T2 T3 --org ORG1 --org ORG2 -p prod
    """
    rows: List[Dict[str, Any]] = []
    for org_name in list(dict.fromkeys(org)) or [""]:
        client = _client_for_org(profile, org_name or None)
        for row in _fetch_rules(client, list(tables)):
            rows.append({"org": org_name, **row})
    print(json.dumps(rows))


# ---------------------------------------------------------------------------
# ts security column-rules set / clear -- one-shot imperatives, no manifest
# ---------------------------------------------------------------------------

def _one_shot(profile: Optional[str], org: Optional[str], payload: Dict[str, Any],
              label: str, dry_run: bool) -> None:
    """Apply one `rules/update` body to one table, or print it under --dry-run.

    The Org context is asserted before writing. Org scoping fails SILENTLY when the
    platform does not honour the field it was given, and a silent failure here writes
    one tenant's column security into another tenant's Org.
    """
    if dry_run:
        print(json.dumps(payload))
        return
    client = _client_for_org(profile, org)
    if org:
        assert_org_context(client, org, profile)
    _post_update(client, payload, label)


def _refuse_empty_groups_for_increment(rules: Dict[str, List[str]],
                                       operation: str) -> None:
    """Refuse ``--rule "COL="`` under --add or --remove.

    An empty group list is meaningful only under REPLACE, where it declares the column
    secured with nobody able to see it. ADDING or REMOVING nothing is not a state, it is
    a no-op: the call would return success having changed nothing, which reads as
    "secured" to whoever ran it. Refusing costs nothing -- REPLACE expresses the only
    thing the empty form can mean.
    """
    if operation == "REPLACE":
        return
    empty = sorted(column for column, groups in rules.items() if not groups)
    if not empty:
        return
    raise typer.BadParameter(
        f"--rule \"{empty[0]}=\" names no groups, and {operation} has nothing to act on: "
        f"it would report success having changed nothing. \"COL=\" is meaningful only "
        f"under the default REPLACE, where it means secured with no group able to see "
        f"it. Columns affected: {', '.join(empty)}.")


@column_rules_app.command("set")
def set_cmd(
    table: str = typer.Option(..., "--table", help="Table GUID or name"),
    rule: List[str] = typer.Option(..., "--rule",
                                   help='Restricted column and its groups: '
                                        '"COL=GROUP[,GROUP...]" (repeatable). '
                                        'Use "COL=" to secure a column for nobody.'),
    add: bool = typer.Option(False, "--add",
                             help="Add these groups to each column's access list "
                                  "instead of replacing it"),
    remove: bool = typer.Option(False, "--remove",
                                help="Remove these groups from each column's access list"),
    org: Optional[str] = typer.Option(None, "--org", help="Apply in this Org"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Print the payload without sending it"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Restrict columns on one table to named groups.

    Declarative by default: the groups you pass are what the column ends up with
    (REPLACE), so running the same command twice converges and `get` before and after
    diffs cleanly. --add and --remove reach the incremental operations when a
    read-modify-write is not what you want.

    Only the columns named are touched: a column already secured and not mentioned here
    is left exactly as it was. Live-verified (2026-07-27, cluster
    `nebula-damian-alias`): securing `PROD_NM` for one group, then `UNIT_PRICE_AMT` for
    a different group in a SEPARATE `set` call, left both rules in place side by side --
    a per-column `REPLACE` is genuinely scoped, not a whole-table replace. Verified for
    REPLACE on a single table; `set` itself is otherwise unchanged. Use `clear --column`
    to unsecure one column, or `resolve --prune` to unsecure everything absent from a
    manifest.

    Output (JSON to stdout, --dry-run only): the request payload.

    Examples:

    \b
      ts security column-rules set --table T2_PUBLISH --rule "PROD_NM=Analyst" -p prod
      ts security column-rules set --table T2 --rule "COST=Finance,Audit" \\
        --rule "SALARY=" --org ORG1 -p prod
      ts security column-rules set --table T2 --rule "COST=Audit" --add -p prod
    """
    from ts_cli.csr_plan import parse_rule_flags

    if add and remove:
        raise typer.BadParameter(
            "--add and --remove are mutually exclusive: one call carries one operation.")
    operation = "ADD" if add else "REMOVE" if remove else "REPLACE"

    try:
        rules = parse_rule_flags(list(rule))
        _refuse_empty_groups_for_increment(rules, operation)
        payload = build_update_payload(table, rules, operation=operation)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    _one_shot(profile, org, payload,
              f"{table}: {operation} {', '.join(sorted(rules))}", dry_run)


@column_rules_app.command("clear")
def clear_cmd(
    table: str = typer.Option(..., "--table", help="Table GUID or name"),
    column: Optional[str] = typer.Option(None, "--column",
                                         help="Unsecure only this column. Omit to "
                                              "unsecure every column on the table."),
    org: Optional[str] = typer.Option(None, "--org", help="Apply in this Org"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Print the payload without sending it"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Unsecure one column, or every column on a table.

    With --column this sends `is_unsecured: true` for that column alone. Without it,
    `clear_csr: true` unsecures the whole table -- accompanied by the empty
    `column_security_rules: []` the request schema requires, which is why the flag
    appears not to work when sent on its own.

    This removes protection. Capture `get` first if you may need to put it back.

    Output (JSON to stdout, --dry-run only): the request payload.

    Examples:

    \b
      ts security column-rules clear --table T2_PUBLISH --column COST -p prod
      ts security column-rules clear --table T2_PUBLISH --org ORG1 -p prod
    """
    try:
        if column is not None:
            payload = build_update_payload(table, {}, unsecure=[column])
            label = f"{table}: unsecure {column}"
        else:
            payload = build_update_payload(table, {}, clear=True)
            label = f"{table}: clear all column security rules"
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    _one_shot(profile, org, payload, label, dry_run)


# ---------------------------------------------------------------------------
# ts security column-rules export -- the TML route's read stage
# ---------------------------------------------------------------------------

@column_rules_app.command("export")
def export_cmd(
    tables: List[str] = typer.Argument(..., help="Table GUIDs or names to export"),
    org: Optional[str] = typer.Option(None, "--org", help="Export from this Org"),
    out: Optional[str] = typer.Option(None, "--out",
                                      help="Directory to write the .tml files into. "
                                           "Omit to print them only."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Export each table's `column_security_rules` TML document.

    CSR round-trips through TML as a sibling document, exactly the `column_alias`
    pattern, so the export needs BOTH `export_associated: true` and
    `export_options.export_column_security_rules: true`. The option is Beta (10.12+);
    without it the CSR document simply is not in the response.

    Preserving this document is what makes a tenant's CSR configuration restorable
    later, published or not -- an owning-Org CSR update on a published table already
    succeeds (live-verified 2026-07-27; tenant-Org visibility of the result is the
    still-open question, not whether the owning Org can set it). Once that path is used
    instead of `CSR_BLOCKED`, restoring is a single import rather than a reconstruction
    from CLS grants.

    An empty result is a legitimate answer: a table with no secured columns has no
    document to return.

    Output (JSON to stdout):
      {"documents": [{"table_name", "rules", "guid", "yaml"}], "written": [paths]}

    Examples:

    \b
      ts security column-rules export T2_PUBLISH -p prod
      ts security column-rules export T1 T2 --out ./plan/csr --org ORG1 -p prod
    """
    from pathlib import Path

    from ts_cli.csr_plan import csr_tml_filename, parse_csr_tml_export

    client = _client_for_org(profile, org)
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": t, "type": "LOGICAL_TABLE"}
                     for t in dict.fromkeys(tables)],
        "export_associated": True,
        "export_fqn": True,
        "edoc_format": "YAML",
        "export_options": {"export_column_security_rules": True},
    }, raise_for_status=False)
    if not resp.ok:
        _fail(resp, "Could not export column security rules")

    documents = parse_csr_tml_export(resp.json())
    if not documents:
        print("No column security rules found on: "
              f"{', '.join(dict.fromkeys(tables))}. Either nothing is secured, or the "
              f"export option is unavailable on this build (Beta, 10.12+).",
              file=sys.stderr)

    written: List[str] = []
    if out and documents:
        directory = Path(out)
        directory.mkdir(parents=True, exist_ok=True)
        for document in documents:
            path = directory / csr_tml_filename(document["table_name"])
            path.write_text(document["yaml"])
            written.append(str(path))
            print(f"wrote {path}", file=sys.stderr)

    print(json.dumps({"documents": documents, "written": written}))
