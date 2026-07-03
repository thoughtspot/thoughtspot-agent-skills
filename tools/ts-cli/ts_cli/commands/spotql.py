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

classify-columns (BL-087) is a third, unrelated capability bolted onto this group
because it feeds the same SUM-vs-AGG decision Step 3 of ts-object-model-spotql-query
makes before writing SpotQL: it wraps `ts_cli.spotql_ops` (the pure aggregate-function
classifier) with two I/O modes — Model TML export, or a bare list of expressions.
"""
from __future__ import annotations

import json as _json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.spotql_ops import classify_expr, classify_model_columns

app = typer.Typer(help="SpotQL (Semantic SQL) query commands.")

_profile_option = typer.Option(
    None, "--profile", "-p", envvar="TS_PROFILE",
    help="Profile name (default: first profile or TS_PROFILE env var)",
)
_model_option = typer.Option(
    ..., "--model", "-m",
    help="Model identifier — the Model's GUID (from `ts metadata search --subtype WORKSHEET`)",
)

_TML_EXPORT_PATH = "/api/rest/2.0/metadata/tml/export"

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


def _classify_by_model(model: str, profile: Optional[str]) -> list[dict]:
    """--model mode: export the Model's TML and classify every model.columns[] entry."""
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post(
        _TML_EXPORT_PATH,
        json={
            "metadata": [{"identifier": model}],
            "export_fqn": False,
            "export_associated": False,
            "formattype": "YAML",
        },
    )
    data = resp.json()
    if not data:
        raise SystemExit(f"No TML returned for model identifier: {model}")

    # Local import — avoids a module-load-order cycle with ts_cli.commands.tml
    # (both modules are registered as sibling command groups in cli.py).
    from ts_cli.commands.tml import parse_edoc

    edoc = data[0].get("edoc", "")
    try:
        parsed = parse_edoc(edoc, "YAML")
    except Exception as exc:
        raise SystemExit(f"Failed to parse Model TML for {model}: {exc}") from exc

    results = classify_model_columns(parsed)
    n_attr = sum(1 for r in results if r["kind"] == "attribute")
    n_raw = sum(1 for r in results if r["kind"] == "raw_measure")
    n_agg = sum(1 for r in results if r["kind"] == "aggregate_measure")
    print(
        f"  {len(results)} column(s): {n_attr} attribute, {n_raw} raw measure, "
        f"{n_agg} aggregate-formula measure",
        file=sys.stderr,
    )
    return results


def _read_exprs_input(exprs_file: Optional[str]) -> list:
    """--exprs-file / stdin mode: read and validate the {name, expr}[] JSON payload."""
    if exprs_file:
        p = Path(exprs_file)
        if not p.is_file():
            raise SystemExit(f"--exprs-file path does not exist or is not a file: {exprs_file}")
        raw = p.read_text()
    else:
        raw = sys.stdin.read()

    try:
        exprs = _json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid JSON input: {exc}")
    if not isinstance(exprs, list):
        raise SystemExit(
            "Input must be a JSON array of {\"name\": ..., \"expr\": ...} objects."
        )
    return exprs


def _classify_by_exprs(exprs_file: Optional[str]) -> list[dict]:
    """--exprs-file / stdin mode: classify a bare list of {name, expr} objects."""
    exprs = _read_exprs_input(exprs_file)

    results = []
    for item in exprs:
        name = item.get("name", "") if isinstance(item, dict) else ""
        expr = item.get("expr", "") if isinstance(item, dict) else ""
        results.append({"name": name, **classify_expr(expr)})

    n_agg = sum(1 for r in results if r["is_aggregate"])
    print(f"  {len(results)} expression(s) classified ({n_agg} aggregate)", file=sys.stderr)
    return results


@app.command("classify-columns")
def classify_columns_cmd(
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help=(
            "Model GUID — classify every model.columns[] entry via a TML export. "
            "Mutually exclusive with --exprs-file / stdin."
        ),
    ),
    exprs_file: Optional[str] = typer.Option(
        None, "--exprs-file",
        help=(
            "Path to a JSON array of {\"name\": ..., \"expr\": ...} objects to classify "
            "(answer-formula mode — expressions not yet attached to a Model column). "
            "Reads the same shape from stdin if neither --model nor --exprs-file is given. "
            "Mutually exclusive with --model."
        ),
    ),
    profile: Optional[str] = _profile_option,
) -> None:
    """Classify ThoughtSpot columns/formula expressions as attribute vs. measure vs.
    aggregate-formula-measure — the decision that drives SUM-vs-AGG in SpotQL and
    MEASURE/ATTRIBUTE + aggregation inference when promoting Answer formulas to a Model.

    Exactly one input mode:

    \b
    1. --model <guid>: exports the Model's TML and classifies every model.columns[]
       entry. Output: JSON array of
       {"name", "column_type", "kind": "attribute"|"raw_measure"|"aggregate_measure",
        "needs_agg": bool, "aggregation": "SUM"|None}.
       `kind == "aggregate_measure"` (equivalently `needs_agg: true`) means SpotQL
       must wrap the column in `AGG(...)` — never a real aggregate, or ThoughtSpot
       rejects the query with NESTED_AGGREGATE_NOT_SUPPORTED. `"raw_measure"` means
       a real aggregate (`SUM`/`AVG`/...). `"attribute"` means group by it.

    2. --exprs-file <path> (or stdin): classifies a bare JSON array of
       {"name": ..., "expr": ...} objects — formula expressions not yet attached to
       any Model column (e.g. Answer formulas being promoted). Output: JSON array of
       {"name", "column_type": "MEASURE"|"ATTRIBUTE", "aggregation": "SUM"|None,
        "is_aggregate": bool}. No ThoughtSpot connection is used in this mode.

    Diagnostic counts go to stderr; the JSON array goes to stdout.

    Examples:

    \\b
      ts spotql classify-columns --model 4da3a07f-fe29-4d20-8758-260eb1315071 --profile prod
      ts spotql classify-columns --exprs-file formulas_to_add.json
      echo '[{"name": "Profit Margin", "expr": "[Revenue] - [Cost]"}]' \\
        | ts spotql classify-columns
    """
    if model and exprs_file:
        raise SystemExit(
            "--model and --exprs-file are mutually exclusive — pick one input mode."
        )

    results = _classify_by_model(model, profile) if model else _classify_by_exprs(exprs_file)
    print(_json.dumps(results))
