"""ts spotql — run SpotQL (Semantic SQL) against a ThoughtSpot Model.

Two endpoints (V2, under /callosum/v1/v2/data/spotql/):
  generate-sql — validates a SpotQL statement and returns the warehouse SQL it
                 compiles to, without executing it.
  fetch-data   — executes the SpotQL statement and returns result rows.

Both take the same body: {"spotql_query": "<SpotQL>", "model_identifier": "<Model GUID>"}.
The caller (an agent or a person) writes the SpotQL; these commands do not do
natural-language → SpotQL. Output is JSON to stdout so skills can pipe it.

Query errors (a malformed statement, an unknown column) come back as HTTP 400 with a
structured error envelope, NOT a transport failure — so these commands ask the client
not to raise on non-2xx and surface the error in the JSON `errors` field instead.

Response-normalisation logic verified against build 26.7.0.cl-72 (spotQL-testing).
"""
from __future__ import annotations

import json as _json
import re
from typing import Any, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="SpotQL (Semantic SQL) query commands.")

_profile_option = typer.Option(
    None, "--profile", "-p", envvar="TS_PROFILE",
    help="Profile name (default: first profile or TS_PROFILE env var)",
)
_model_option = typer.Option(
    ..., "--model", "-m",
    help="Model identifier — the Model's GUID (from `ts metadata search --subtype WORKSHEET`)",
)

_GENERATE_PATH = "/callosum/v1/v2/data/spotql/generate-sql"
_FETCH_PATH = "/callosum/v1/v2/data/spotql/fetch-data"

# ──────────────────────────────────────────────────────────────────────────────
# Pure response normalisation (ported from spotQL-testing core/api.py)
# ──────────────────────────────────────────────────────────────────────────────

# Map a column's `type` to the scalar field carrying each cell's value. `nullType`
# is a fallback type marker (despite the name it is not a null flag — `nullVal` is).
_TYPE_FIELD = {
    "CHAR": "stringVal", "VARCHAR": "stringVal", "STRING": "stringVal", "TYPE_STRING": "stringVal",
    "INT32": "int32Val", "TYPE_INT32": "int32Val",
    "INT64": "int64Val", "TYPE_INT64": "int64Val",
    "DOUBLE": "doubleVal", "TYPE_DOUBLE": "doubleVal",
    "FLOAT": "floatVal", "TYPE_FLOAT": "floatVal",
    "BOOL": "boolVal", "BOOLEAN": "boolVal", "TYPE_BOOL": "boolVal",
    "BYTES": "bytesVal", "TYPE_BYTES": "bytesVal",
}


def _cell_value(cell: dict, col_type: str) -> Any:
    if cell.get("nullVal"):
        return None
    field = _TYPE_FIELD.get(col_type) or _TYPE_FIELD.get(cell.get("nullType", ""))
    if field is None:
        for f in ("stringVal", "int64Val", "int32Val", "doubleVal", "floatVal", "boolVal", "bytesVal"):
            v = cell.get(f)
            if v not in (None, "", 0, 0.0, False):
                field = f
                break
        if field is None:
            return None
    v = cell.get(field)
    if field == "int64Val" and isinstance(v, str):  # int64 arrives as a JSON string
        try:
            return int(v)
        except ValueError:
            return v
    return v


def extract_columns_and_rows(block: Any) -> tuple[list[dict], list[list]]:
    """Flip the columnar fetch-data result block to row-major.

    Columns are returned as {"index": i, "type": <type>} — the API labels columns
    with a per-query GUID that is not stable across runs, so the SELECT-ordinal index
    is the usable identifier.
    """
    if not isinstance(block, dict):
        return [], []
    results = block.get("results") or []
    if not results:
        return [], []
    tables = results[0].get("tables") or {}
    raw_cols = tables.get("column") or []
    columns = [{"index": i, "type": c.get("type", "")} for i, c in enumerate(raw_cols)]
    if not columns:
        return [], []
    col_values = [c.get("value") or [] for c in raw_cols]
    n_rows = max((len(v) for v in col_values), default=0)
    rows = []
    for i in range(n_rows):
        row = [
            _cell_value(vals[i] if i < len(vals) else {"nullVal": True}, col.get("type", ""))
            for col, vals in zip(raw_cols, col_values)
        ]
        rows.append(row)
    return columns, rows


def extract_validation_code(text: str) -> str:
    """Pull a validation code from a free-text error string.

    Two forms: a bracketed marker `[SELECT_STAR]`, or an `Error Code: QUERY_GEN_ERROR`
    prefix (26.7 generate-sql / fetch-data errors).
    """
    m = re.search(r"\[([A-Z][A-Z0-9_]+)\]", text)
    if m:
        return m.group(1)
    m = re.search(r"Error Code:\s*([A-Z][A-Z0-9_]+)", text)
    return m.group(1) if m else ""


def normalise_response(data: Any) -> dict:
    """Normalise a raw SpotQL response (2xx success or 4xx error envelope) to:

    {status, executable_sql, errors: [{code, message}], columns, rows}

      generate-sql success → {"executable_sql": "..."} (no status field)
      fetch-data success    → {"query_result": {"results": [...]}} (no status, no SQL)
      error                 → {"error": {"message": {"code", "debug": "[CODE] ..."}}}
    """
    if not isinstance(data, dict):
        return {"status": "PARSE_ERROR", "executable_sql": "", "errors":
                [{"code": "PARSE_ERROR", "message": "Unexpected response format"}],
                "columns": [], "rows": []}

    status = data.get("status", "UNKNOWN")
    executable_sql = data.get("executable_sql") or ""
    errors: list[dict] = []

    new_err = data.get("error")
    if isinstance(new_err, dict):
        msg_obj = new_err.get("message")
        debug = msg_obj.get("debug", "") if isinstance(msg_obj, dict) else str(msg_obj or "")
        code = extract_validation_code(str(debug)) or (
            str(msg_obj.get("code", "")) if isinstance(msg_obj, dict) else ""
        ) or "QUERY_GEN_ERROR"
        errors.append({"code": code, "message": str(debug)})
        if status == "UNKNOWN":
            status = code

    columns, rows = extract_columns_and_rows(data.get("query_result"))

    if status == "UNKNOWN" and not errors and (executable_sql or data.get("query_result") is not None):
        status = "SUCCESS"

    return {"status": status, "executable_sql": executable_sql,
            "errors": errors, "columns": columns, "rows": rows}


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────

def _run(path: str, spotql: str, model: str, profile: Optional[str]) -> dict:
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        path,
        json={"spotql_query": spotql, "model_identifier": model},
        raise_for_status=False,  # surface structured 400 query errors instead of crashing
    )
    try:
        data = resp.json() if resp.text else {}
    except ValueError:
        data = {}
    return normalise_response(data)


@app.command("generate-sql")
def generate_sql(
    spotql: str = typer.Argument(..., help="The SpotQL (Semantic SQL) statement"),
    model: str = _model_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """Validate a SpotQL statement and return the warehouse SQL it compiles to.

    Does NOT execute the query. Output: JSON {status, executable_sql, errors}.
    A non-SUCCESS status with a populated errors[] means the statement was rejected.

    Examples:

    \\b
      ts spotql generate-sql 'SELECT "Region", SUM("Sales") AS s FROM "ORDERS" AS "t1" GROUP BY "Region"' -m <guid>
    """
    r = _run(_GENERATE_PATH, spotql, model, profile)
    print(_json.dumps({"status": r["status"], "executable_sql": r["executable_sql"],
                       "errors": r["errors"]}))


@app.command("fetch-data")
def fetch_data(
    spotql: str = typer.Argument(..., help="The SpotQL (Semantic SQL) statement"),
    model: str = _model_option,
    profile: Optional[str] = _profile_option,
) -> None:
    """Execute a SpotQL statement and return result rows.

    Output: JSON {status, columns, rows, errors}. Columns are {index, type} — SpotQL
    returns per-query column GUIDs (not stable names), so the SELECT ordinal is the
    usable identifier. A non-SUCCESS status with errors[] means execution failed.

    Examples:

    \\b
      ts spotql fetch-data 'SELECT "Region", SUM("Sales") AS s FROM "ORDERS" AS "t1" GROUP BY "Region"' -m <guid>
    """
    r = _run(_FETCH_PATH, spotql, model, profile)
    print(_json.dumps({"status": r["status"], "columns": r["columns"],
                       "rows": r["rows"], "errors": r["errors"]}))
