"""ts security column-rules -- Column Security Rules (CSR).

The second of the two column-security mechanisms. `ts share` carries the first
(column-level sharing, CLS); this carries CSR, and they are not interchangeable:

| | CLS (`ts share`) | CSR (here) |
|---|---|---|
| Works on published objects | yes | NO |
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


def _published_orgs(client: ThoughtSpotClient, guid: str) -> List[int]:
    """The Org ids a table is published into, read from ``metadata_header.orgIds``.

    CSR cannot be defined on a published object, and this is the same field
    `ts publish status` reads, so no per-Org auth is needed to answer the question.
    """
    resp = client.post("/api/rest/2.0/metadata/search",
                       json={"metadata": [{"identifier": guid, "type": "LOGICAL_TABLE"}],
                             "include_headers": True},
                       raise_for_status=False)
    if not getattr(resp, "ok", False):
        return []
    data = resp.json()
    hits = data if isinstance(data, list) else (data.get("metadata") or [])
    if not hits:
        return []
    header = hits[0].get("metadata_header") or {}
    return [int(o) for o in (header.get("orgIds") or []) if str(o).lstrip("-").isdigit()]


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

    Only the columns named are touched. A column already secured and not mentioned here
    is left exactly as it was; use `clear --column` to unsecure one, or
    `resolve --prune` to unsecure everything absent from a manifest.

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
