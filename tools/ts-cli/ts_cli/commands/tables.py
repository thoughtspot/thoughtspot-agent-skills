"""ts tables — create ThoughtSpot logical table objects from a JSON spec."""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import typer
import yaml

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.tml_common import extract_imported_guid

app = typer.Typer(help="ThoughtSpot logical table object commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

_JDBC_ERRORS = ("CONNECTION_METADATA_FETCH_ERROR", "JDBC driver encountered a communication error")


def _is_jdbc_error(status: Dict[str, Any]) -> bool:
    msg = status.get("error_message", "")
    return any(e in msg for e in _JDBC_ERRORS)


def _err(msg: str) -> None:
    """print(..., file=sys.stderr) plus an explicit flush.

    Duplicated locally rather than imported from `commands.aggregate` (same
    helper, same reasoning as that module's own docstring — see rls.py's
    convention of keeping each module's diagnostics self-contained): Click's
    `CliRunner(mix_stderr=False)` only flushes `sys.stdout` in its `invoke()`
    finally block, not `sys.stderr` — an unflushed stderr diagnostic here
    would otherwise vanish from `result.stderr` in tests.
    """
    print(msg, file=sys.stderr)
    sys.stderr.flush()


# Live-verified BL-063 PR4 (2026-07-10, se-thoughtspot): the import API rejects
# "BOOLEAN" ("Data type BOOLEAN is not valid for column ...") — it wants "BOOL".
# Normalize the common spelling so existing specs authored against the old
# help text keep working without every caller needing to change.
_DATA_TYPE_NORMALIZE = {"BOOLEAN": "BOOL"}


def _build_table_tml(spec: Dict[str, Any], guid: Optional[str] = None) -> str:
    """Build a ThoughtSpot table TML YAML string from a spec dict.

    An optional `rls_rules` key on `spec` (Task 23 — `ts aggregate generate`
    attaches the block `ts_cli.aggregate.rls.propagate_rls` returns) is
    passed straight through onto `table.rls_rules`. Absent for every other
    spec-building caller (Tableau/Databricks conversions, hand-authored
    specs), so this is purely additive — no behavior change when the key
    isn't present.

    An optional `guid` (Bug B, Task 25 — two-pass RLS registration) is placed
    at the document root, a sibling of `table:` — never nested inside it, per
    the "guid: goes at the document root" TML invariant
    (`agents/shared/schemas/thoughtspot-table-tml.md`). `create_tables` uses
    this for pass 2's update-in-place (`--no-create-new`) import that attaches
    a propagated `rls_rules` block once the table (and its GUID) already
    exist. Omitted by default — every other caller creates a brand-new table
    with no GUID yet.
    """
    columns = []
    for col in spec.get("columns", []):
        data_type = col["data_type"]
        data_type = _DATA_TYPE_NORMALIZE.get(data_type, data_type)
        col_entry: Dict[str, Any] = {
            "name": col["name"],
            "db_column_name": col["name"],
            "properties": {"column_type": col.get("column_type", "ATTRIBUTE")},
            "db_column_properties": {"data_type": data_type},
        }
        if col.get("column_type") == "MEASURE":
            col_entry["properties"]["aggregation"] = col.get("aggregation", "SUM")
        columns.append(col_entry)

    tbl: Dict[str, Any] = {
        "table": {
            "name": spec["name"],
            "db": spec["db"],
            "schema": spec["schema"],
            "db_table": spec["db_table"],
            "connection": {"name": spec["connection_name"]},
            "columns": columns,
        }
    }
    if spec.get("rls_rules"):
        tbl["table"]["rls_rules"] = spec["rls_rules"]

    doc: Dict[str, Any] = {}
    if guid:
        doc["guid"] = guid
    doc.update(tbl)
    return yaml.dump(doc, default_flow_style=False, allow_unicode=True)


def _strip_rls_rules(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of `spec` with `rls_rules` removed — the RLS-less spec
    variant `create_tables` uses for pass 1 (create).

    Bug B (Task 25, live import failure): a table TML that carries a
    self-referencing `rls_rules` block (`[<agg_table>_1::COL]` pointing at
    the table being imported) in the SAME `create_new` import call fails —
    the self-reference can't resolve to a `LOGICAL_TABLE` that doesn't exist
    yet. Pass 1 must create the table without it; pass 2 re-imports WITH
    `rls_rules` once the table (and its GUID) exist (see `create_tables`).
    A no-op (returns an equal, distinct dict) when `rls_rules` isn't present.
    """
    return {k: v for k, v in spec.items() if k != "rls_rules"}


def _find_guid_by_name(
    client: ThoughtSpotClient, name: str, connection_name: str,
) -> Optional[str]:
    """Search for a ONE_TO_ONE_LOGICAL table by exact name AND connection, return its GUID.

    Connection-scoped: a name-only search can return the wrong table when two
    connections both have a table with the same name (live finding, BL-063
    PR4, 2026-07-10, se-thoughtspot — same-named DM_ORDER tables existed on
    both the "Power" and "APJ_BIRD" connections; a name-only lookup resolved
    to the wrong connection's GUID, and the resulting model referenced
    foreign tables, failing import with "Could not find column"/"different
    connections"). Filters candidates to those whose
    ``metadata_header.dataSourceName`` matches ``connection_name`` (the
    verified field — see .claude/rules/ts-cli.md and
    agents/cli/ts-audit/SKILL.md for the same pattern). Returns None if no
    candidate matches both name and connection.
    """
    try:
        resp = client.post(
            "/api/rest/2.0/metadata/search",
            json={
                "metadata": [{"type": "LOGICAL_TABLE", "subtypes": ["ONE_TO_ONE_LOGICAL"],
                               "name_pattern": name}],
                "record_size": 10,
                "record_offset": 0,
                "include_headers": True,
            },
        )
        results = resp.json()
        if isinstance(results, list):
            for r in results:
                if r.get("metadata_name") != name:
                    continue
                header = r.get("metadata_header") or r
                if header.get("dataSourceName") == connection_name:
                    return r.get("metadata_id")
    except Exception:
        pass
    return None


def _import_one(client: ThoughtSpotClient, tml_str: str, create_new: bool,
                retries: int, retry_delay: float, name: str,
                connection_name: str) -> Tuple[Optional[str], bool]:
    """One create-or-update import attempt for a single table TML string,
    with the existing transient-JDBC-error retry loop. Shared by
    `create_tables`'s pass 1 (create, `create_new=True`) and pass 2 (update
    in place with `create_new=False`, Bug B / Task 25 — attaches a
    propagated `rls_rules` block onto the table pass 1 just created) — same
    retry semantics either way. Returns `(guid, success)`; `guid` is
    resolved from the response first, falling back to a connection-scoped
    name search (`_find_guid_by_name`) when the import response omits it.
    """
    guid: Optional[str] = None
    for attempt in range(1, retries + 1):
        if attempt > 1:
            time.sleep(retry_delay)

        result = client.post(
            "/api/rest/2.0/metadata/tml/import",
            json={"metadata_tmls": [tml_str], "import_policy": "PARTIAL", "create_new": create_new},
        )
        resp_data = result.json()
        # Handle both list and dict response shapes
        items = resp_data if isinstance(resp_data, list) else resp_data.get("object", [resp_data])
        item = items[0] if items else {}
        status = item.get("response", item).get("status", {})
        status_code = status.get("status_code", "ERROR")

        if status_code == "OK":
            # Try to get GUID from response first (nested or flat shape)
            guid = extract_imported_guid([item])
            # If not in response, search for it (connection-scoped — see
            # _find_guid_by_name docstring for why name-only isn't enough)
            if not guid:
                guid = _find_guid_by_name(client, name, connection_name)
            return guid, True
        elif _is_jdbc_error(status):
            _err(f"  RETRY {name} (attempt {attempt}/{retries}): transient JDBC error")
            continue
        else:
            err = status.get("error_message", "")[:200]
            _err(f"  ERROR {name}: {err}")
            return None, False
    return None, False


@app.command("create")
def create_tables(
    profile: Optional[str] = _profile_option,
    retries: int = typer.Option(3, "--retries", "-r",
                                help="Max retries per table on transient JDBC errors"),
    retry_delay: float = typer.Option(5.0, "--retry-delay",
                                      help="Seconds to wait between retries"),
) -> None:
    """Create ThoughtSpot logical table objects from a JSON spec.

    Reads a JSON array from stdin where each element describes one table:

    \b
    [
      {
        "name": "trans",
        "db": "BIRD",
        "schema": "FINANCIAL_SV",
        "db_table": "TRANS",
        "connection_name": "APJ_BIRD",
        "columns": [
          {"name": "TRANS_ID",     "data_type": "INT64",   "column_type": "ATTRIBUTE"},
          {"name": "TRANS_AMOUNT", "data_type": "INT64",   "column_type": "MEASURE"},
          {"name": "TRANS_DATE",   "data_type": "DATE",    "column_type": "ATTRIBUTE"},
          {"name": "TRANS_TYPE",   "data_type": "VARCHAR", "column_type": "ATTRIBUTE"}
        ]
      }
    ]

    Data types: INT64, DOUBLE, VARCHAR, DATE, DATE_TIME, BOOL. ("BOOLEAN" is
    accepted too and normalized to BOOL — the live import API rejects BOOLEAN
    with "Data type BOOLEAN is not valid for column ...", verified 2026-07-10.)
    Column types: ATTRIBUTE (default) or MEASURE (adds aggregation: SUM).

    Auto-retries on transient JDBC errors. After each successful import,
    resolves the GUID via metadata search if not returned in the import response.

    Row-level security (Bug B, Task 25 — two-pass import): a spec whose
    `rls_rules` key is set (Task 23 — `ts aggregate generate` attaches the
    block `ts_cli.aggregate.rls.propagate_rls` returns) is registered in TWO
    passes automatically, transparent to the caller. Pass 1 creates the
    table WITHOUT `rls_rules`; pass 2 re-imports the SAME table WITH
    `rls_rules` plus the just-created GUID at the document root and
    `--no-create-new`, attaching the rules. This is required — live-verified
    — because `rls_rules`' `table_paths` entry self-references the table
    being created (`[<name>_1::COL]`); resolving that reference in the SAME
    `create_new` call the table itself is created in fails with
    `OBJECT_NOT_FOUND ... LOGICAL_TABLE`, since the table doesn't exist yet
    at the moment ThoughtSpot tries to resolve the self-reference. A spec
    with no `rls_rules` is completely unaffected — one pass, as before.

    Output: JSON object mapping table name → GUID for all successfully created tables.
    Tables that failed after all retries are included with null as the GUID. A table
    whose pass 1 (create) succeeded but pass 2 (RLS attach) failed still reports its
    GUID here (the table exists) — check stderr for an RLS-attach error in that case.

    Examples:

    \b
      cat tables.json | ts tables create --profile my-profile
      cat tables.json | ts tables create --retries 5 --retry-delay 10
    """
    try:
        specs: List[Dict[str, Any]] = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON on stdin: {e}")

    if not isinstance(specs, list):
        raise SystemExit("stdin must be a JSON array of table spec objects.")

    client = ThoughtSpotClient(resolve_profile(profile))
    results: Dict[str, Optional[str]] = {}

    for spec in specs:
        name = spec["name"]
        connection_name = spec["connection_name"]
        has_rls = bool(spec.get("rls_rules"))

        # Pass 1: create. Strip rls_rules first when present — a
        # self-referencing rule can't resolve before the table exists (Bug B).
        create_spec = _strip_rls_rules(spec) if has_rls else spec
        tml_str = _build_table_tml(create_spec)
        guid, success = _import_one(client, tml_str, True, retries, retry_delay,
                                    name, connection_name)

        if not success:
            results[name] = None
            continue

        # Pass 2: attach RLS now that the table (and its GUID) exist.
        if has_rls:
            if guid:
                rls_tml_str = _build_table_tml(spec, guid=guid)
                _, rls_success = _import_one(client, rls_tml_str, False, retries,
                                             retry_delay, name, connection_name)
                if not rls_success:
                    # NOT "re-run ts tables create" — a second create_new pass
                    # would create a DUPLICATE same-named table, not update this
                    # one. The table already exists (guid known); only the
                    # attach needs retrying, directly against that guid.
                    _err(f"  ERROR {name}: table created ({guid}) but attaching "
                        "row-level security failed after retries — the table is "
                        "UNSECURED. Do not re-run `ts tables create` (creates a "
                        f"duplicate); instead set `guid: {guid}` at the document "
                        "root of the table's TML (with rls_rules) and run "
                        "`ts tml import --file <that TML> --no-create-new`.")
            else:
                _err(f"  WARNING {name}: table created but its GUID could not be "
                    "resolved — cannot attach row-level security automatically. "
                    "Find the GUID, set it at the document root of the table's "
                    "TML (with rls_rules), and run `ts tml import --file <that "
                    "TML> --no-create-new`.")

        results[name] = guid
        _err(f"  OK  {name}: {guid}")

    print(json.dumps(results))
