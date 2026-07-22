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

_BATCH_SIZE = 50


def _is_jdbc_error(status: Dict[str, Any]) -> bool:
    msg = status.get("error_message", "")
    return any(e in msg for e in _JDBC_ERRORS)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.stderr.flush()


_DATA_TYPE_NORMALIZE = {"BOOLEAN": "BOOL"}


def _build_table_tml(spec: Dict[str, Any], guid: Optional[str] = None) -> str:
    """Build a ThoughtSpot table TML YAML string from a spec dict.

    An optional `rls_rules` key on `spec` is passed straight through onto
    `table.rls_rules`. An optional `guid` is placed at the document root
    (a sibling of `table:`, per the TML invariant).
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
    """Return a copy of `spec` with `rls_rules` removed."""
    return {k: v for k, v in spec.items() if k != "rls_rules"}


def _find_guid_by_name(
    client: ThoughtSpotClient, name: str, connection_name: str,
) -> Optional[str]:
    """Search for a ONE_TO_ONE_LOGICAL table by exact name AND connection."""
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


def _parse_import_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Extract status, GUID, and error info from one import response item."""
    status = item.get("response", item).get("status", {})
    return {
        "status_code": status.get("status_code", "ERROR"),
        "guid": extract_imported_guid([item]),
        "is_jdbc_error": _is_jdbc_error(status),
        "error_message": status.get("error_message", ""),
    }


def _import_batch(
    client: ThoughtSpotClient, tml_strings: List[str], create_new: bool,
) -> List[Dict[str, Any]]:
    """Import a batch of TMLs in one call with PARTIAL policy.

    Returns a list of parsed per-item result dicts (same length as
    tml_strings).
    """
    result = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={"metadata_tmls": tml_strings, "import_policy": "PARTIAL",
              "create_new": create_new},
    )
    resp_data = result.json()
    items = resp_data if isinstance(resp_data, list) else resp_data.get("object", [resp_data])
    parsed = [_parse_import_item(item) for item in items]
    while len(parsed) < len(tml_strings):
        parsed.append({"status_code": "ERROR", "guid": None,
                       "is_jdbc_error": False, "error_message": "missing from response"})
    return parsed


def _import_one(client: ThoughtSpotClient, tml_str: str, create_new: bool,
                retries: int, retry_delay: float, name: str,
                connection_name: str) -> Tuple[Optional[str], bool]:
    """Single-table import with transient-JDBC-error retry loop."""
    guid: Optional[str] = None
    for attempt in range(1, retries + 1):
        if attempt > 1:
            time.sleep(retry_delay)

        result = client.post(
            "/api/rest/2.0/metadata/tml/import",
            json={"metadata_tmls": [tml_str], "import_policy": "PARTIAL", "create_new": create_new},
        )
        resp_data = result.json()
        items = resp_data if isinstance(resp_data, list) else resp_data.get("object", [resp_data])
        item = items[0] if items else {}
        status = item.get("response", item).get("status", {})
        status_code = status.get("status_code", "ERROR")

        if status_code == "OK":
            guid = extract_imported_guid([item])
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


def _run_pass1(
    client: ThoughtSpotClient,
    entries: List[Tuple[Dict[str, Any], str, bool]],
    retries: int,
    retry_delay: float,
    results: Dict[str, Optional[str]],
) -> List[Tuple[Dict[str, Any], Optional[str]]]:
    """Pass 1: create tables (without rls_rules) in batches.

    Returns a list of (spec, guid) pairs for tables that need pass 2 (RLS
    attach).
    """
    rls_pending: List[Tuple[Dict[str, Any], Optional[str]]] = []

    for chunk_start in range(0, len(entries), _BATCH_SIZE):
        chunk = entries[chunk_start:chunk_start + _BATCH_SIZE]
        tml_strings = [tml for _, tml, _ in chunk]
        batch_results = _import_batch(client, tml_strings, create_new=True)

        for i, (spec, tml_str, has_rls) in enumerate(chunk):
            name = spec["name"]
            connection_name = spec["connection_name"]
            br = batch_results[i]

            if br["status_code"] == "OK":
                guid = br["guid"] or _find_guid_by_name(client, name, connection_name)
                results[name] = guid
                _err(f"  OK  {name}: {guid}")
                if has_rls:
                    rls_pending.append((spec, guid))
            elif br["is_jdbc_error"]:
                guid, success = _import_one(
                    client, tml_str, True, retries, retry_delay, name, connection_name)
                if success:
                    results[name] = guid
                    _err(f"  OK  {name}: {guid}")
                    if has_rls:
                        rls_pending.append((spec, guid))
                else:
                    results[name] = None
            else:
                _err(f"  ERROR {name}: {br['error_message'][:200]}")
                results[name] = None

    return rls_pending


def _run_pass2(
    client: ThoughtSpotClient,
    rls_pending: List[Tuple[Dict[str, Any], Optional[str]]],
    retries: int,
    retry_delay: float,
) -> List[str]:
    """Pass 2: attach RLS rules in batches. Returns names of tables that failed."""
    rls_attach_failed: List[str] = []

    rls_entries: List[Tuple[Dict[str, Any], str, Optional[str]]] = []
    for spec, guid in rls_pending:
        if guid:
            rls_entries.append((spec, _build_table_tml(spec, guid=guid), guid))
        else:
            _err(f"  WARNING {spec['name']}: table created but its GUID could "
                "not be resolved — cannot attach row-level security "
                "automatically. Find the GUID, set it at the document root "
                "of the table's TML (with rls_rules), and run "
                "`ts tml import --file <that TML> --no-create-new`.")

    for chunk_start in range(0, len(rls_entries), _BATCH_SIZE):
        chunk = rls_entries[chunk_start:chunk_start + _BATCH_SIZE]
        tml_strings = [tml for _, tml, _ in chunk]
        batch_results = _import_batch(client, tml_strings, create_new=False)

        for i, (spec, tml_str, guid) in enumerate(chunk):
            name = spec["name"]
            br = batch_results[i]

            if br["status_code"] == "OK":
                continue

            if br["is_jdbc_error"]:
                _, rls_ok = _import_one(
                    client, tml_str, False, retries, retry_delay,
                    name, spec["connection_name"])
                if rls_ok:
                    continue

            rls_attach_failed.append(name)
            _err(f"  ERROR {name}: table created ({guid}) but attaching "
                "row-level security failed — the table is UNSECURED. Do not "
                f"re-run `ts tables create` (creates a duplicate); instead "
                f"set `guid: {guid}` at the document root of the table's TML "
                "(with rls_rules) and run "
                "`ts tml import --file <that TML> --no-create-new`.")

    return rls_attach_failed


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

    Tables are imported in batches of up to 50 per API call with PARTIAL
    policy. Tables that fail with transient JDBC errors are retried
    individually. After each successful import, resolves the GUID from the
    response or via metadata search.

    Row-level security (Bug B, Task 25 — two-pass import): a spec whose
    `rls_rules` key is set is registered in TWO passes automatically. Pass 1
    creates the table WITHOUT `rls_rules`; pass 2 re-imports WITH `rls_rules`
    plus the just-created GUID and `--no-create-new`. A spec with no
    `rls_rules` is completely unaffected — one pass, as before.

    Output: JSON object mapping table name → GUID. Tables that failed are
    included with null. A table whose pass 2 (RLS attach) failed still
    reports its GUID but the command exits non-zero (fail-closed).

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

    entries: List[Tuple[Dict[str, Any], str, bool]] = []
    for spec in specs:
        has_rls = bool(spec.get("rls_rules"))
        create_spec = _strip_rls_rules(spec) if has_rls else spec
        entries.append((spec, _build_table_tml(create_spec), has_rls))

    rls_pending = _run_pass1(client, entries, retries, retry_delay, results)
    rls_attach_failed = _run_pass2(client, rls_pending, retries, retry_delay) if rls_pending else []

    print(json.dumps(results))

    if rls_attach_failed:
        _err(f"ERROR: row-level security failed to attach for: "
            f"{', '.join(rls_attach_failed)} — see the per-table ERROR "
            "line(s) above for manual recovery instructions.")
        raise typer.Exit(1)
