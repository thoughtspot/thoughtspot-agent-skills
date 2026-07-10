"""ts tables — create ThoughtSpot logical table objects from a JSON spec."""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, List, Optional

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


# Live-verified BL-063 PR4 (2026-07-10, se-thoughtspot): the import API rejects
# "BOOLEAN" ("Data type BOOLEAN is not valid for column ...") — it wants "BOOL".
# Normalize the common spelling so existing specs authored against the old
# help text keep working without every caller needing to change.
_DATA_TYPE_NORMALIZE = {"BOOLEAN": "BOOL"}


def _build_table_tml(spec: Dict[str, Any]) -> str:
    """Build a ThoughtSpot table TML YAML string from a spec dict."""
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
    return yaml.dump(tbl, default_flow_style=False, allow_unicode=True)


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

    Output: JSON object mapping table name → GUID for all successfully created tables.
    Tables that failed after all retries are included with null as the GUID.

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
        tml_str = _build_table_tml(spec)
        payload = json.dumps([tml_str])
        guid: Optional[str] = None
        success = False

        for attempt in range(1, retries + 1):
            if attempt > 1:
                time.sleep(retry_delay)

            result = client.post(
                "/api/rest/2.0/metadata/tml/import",
                json={"metadata_tmls": [tml_str], "import_policy": "PARTIAL", "create_new": True},
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
                    guid = _find_guid_by_name(client, name, spec["connection_name"])
                success = True
                break
            elif _is_jdbc_error(status):
                print(f"  RETRY {name} (attempt {attempt}/{retries}): transient JDBC error",
                      file=sys.stderr)
                continue
            else:
                err = status.get("error_message", "")[:200]
                print(f"  ERROR {name}: {err}", file=sys.stderr)
                break

        if success:
            results[name] = guid
            print(f"  OK  {name}: {guid}", file=sys.stderr)
        else:
            results[name] = None

    print(json.dumps(results))
