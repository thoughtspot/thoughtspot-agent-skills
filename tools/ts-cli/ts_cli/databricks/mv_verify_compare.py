"""The comparison behind `ts databricks verify` (BL-639): no I/O.

Reads a Databricks Statement Execution result, normalises grouping keys so both sides
agree on them, compares each measure cell by its Databricks type, and judges each shape
and the run. Split from `mv_verify.py` (the plan) under the file-size line.

How a cell is compared, by the Databricks type of its column:

- **Integers** (`BYTE`, `SHORT`, `INT`, `LONG`; a `COUNT` is `LONG`): exactly.
- **DECIMAL**: rounded to its scale (half up, as Databricks rounds); relative 1e-12 when
  the scale is unknown.
- **DOUBLE** and **FLOAT**: within a relative or absolute 1e-9, for summation order.
- **DATE**, **TIMESTAMP**, **BOOLEAN**: after normalising, as keys are.
- **Anything else** (STRING among them): as exact text.

A cell accepted within a tolerance but not equal is counted per shape
(`tolerance_accepted`). NULL matches only NULL.

Keys: a DATE arrives from AgentQL as epoch seconds (or milliseconds) at midnight in the
ThoughtSpot cluster's time zone, so it needs that zone to decode (live-checked on the run
BL-639 records). TIMESTAMP keys are decoded in the same zone to the microsecond, the
Databricks value converted to that zone; that is not live-verified. A wrong reading
shows as rows on one side only or as values compared against the wrong group, never as
a silent match.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Optional

FLOAT_REL_TOL = 1e-9
FLOAT_ABS_TOL = 1e-9
DECIMAL_REL_TOL = 1e-12
#: AgentQL caps an ordinary SELECT at 100,000 rows and says nothing when it does.
AGENTQL_ROW_CAP = 100_000
#: Mismatch entries kept per shape in the report; the count is always the full one.
MAX_MISMATCHES_KEPT = 50

_KIND_BY_TYPE = {
    "DATE": "date", "TIMESTAMP": "timestamp", "TIMESTAMP_NTZ": "timestamp",
    "BOOLEAN": "boolean",
    "BYTE": "integer", "TINYINT": "integer", "SHORT": "integer", "SMALLINT": "integer",
    "INT": "integer", "INTEGER": "integer", "LONG": "integer", "BIGINT": "integer",
    "DECIMAL": "decimal", "FLOAT": "float", "DOUBLE": "float",
}
NUMBER_KINDS = ("integer", "decimal", "float")

EQUAL, CLOSE, DIFFERENT = "equal", "close", "different"


# ---------------------------------------------------------------------------
# Databricks result
# ---------------------------------------------------------------------------

def _scale(col: dict) -> Optional[int]:
    if col.get("type_scale") is not None:
        return int(col["type_scale"])
    m = re.search(r"DECIMAL\(\s*\d+\s*,\s*(\d+)\s*\)", str(col.get("type_text") or ""), re.I)
    return int(m.group(1)) if m else None


def column_spec(col: dict) -> dict:
    """{"kind", "scale"} for one Statement Execution manifest column."""
    kind = _KIND_BY_TYPE.get(str(col.get("type_name") or "").upper(), "string")
    return {"kind": kind, "scale": _scale(col) if kind == "decimal" else None}


def databricks_result(response: dict, n_columns: int) -> tuple[list[dict], list[list]]:
    """(column specs, rows) from a Statement Execution response.

    Refuses a result split into chunks or truncated (comparing part of it would report
    the missing rows as mismatches), and one whose schema or rows do not have
    `n_columns` columns."""
    manifest = response.get("manifest") or {}
    result = response.get("result") or {}
    chunks = manifest.get("total_chunk_count") or 1
    if chunks > 1 or result.get("next_chunk_index") is not None:
        raise ValueError(f"the Databricks result arrived in {chunks} chunks; narrow the "
                         f"shape (fewer or coarser dimensions)")
    if manifest.get("truncated"):
        raise ValueError("the Databricks result was truncated; narrow the shape")
    cols = (manifest.get("schema") or {}).get("columns") or []
    if len(cols) != n_columns:
        raise ValueError(f"the Databricks result schema has {len(cols)} columns, "
                         f"expected {n_columns}")
    rows = result.get("data_array") or []
    check_row_widths(rows, n_columns, "Databricks")
    return [column_spec(c) for c in cols], rows


def check_row_widths(rows: list, width: int, side: str) -> None:
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            got = len(row) if isinstance(row, list) else type(row).__name__
            raise ValueError(f"a {side} row has {got} values, expected {width}")


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def _epoch_datetime(value: Any, tz: _dt.tzinfo) -> Optional[_dt.datetime]:
    """An AgentQL epoch (seconds, or milliseconds past ~year 5138 in seconds) as a
    datetime in `tz`, exact to the microsecond for integer input."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        value = int(value)
    if isinstance(value, int):
        ms = abs(value) >= 10 ** 11
        secs, frac = divmod(value, 1000) if ms else (value, 0)
        base = _dt.datetime.fromtimestamp(secs, tz)
        return base + _dt.timedelta(microseconds=frac * 1000)
    if isinstance(value, float):
        return _dt.datetime.fromtimestamp(value / 1000 if abs(value) >= 1e11 else value, tz)
    return None


def _date_text(value: Any, tz: _dt.tzinfo) -> str:
    when = _epoch_datetime(value, tz)
    return when.date().isoformat() if when else str(value)[:10]


def _timestamp_text(value: Any, tz: _dt.tzinfo) -> str:
    when = _epoch_datetime(value, tz)
    if when is None:
        text = str(value).strip()
        try:
            when = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if when.tzinfo is not None:
            when = when.astimezone(tz)
    return when.strftime("%Y-%m-%d %H:%M:%S.%f")


def _decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _number_text(value: Any) -> str:
    d = _decimal(value)
    if d is None or not d.is_finite():
        return str(value) if d is None else str(d)
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def norm_key(value: Any, kind: str, tz: _dt.tzinfo) -> Optional[str]:
    """One grouping value as text both sides agree on; None stays None (a NULL group)."""
    if value is None:
        return None
    if isinstance(value, bool) or kind == "boolean":
        return str(value).lower()
    if kind == "date":
        return _date_text(value, tz)
    if kind == "timestamp":
        return _timestamp_text(value, tz)
    if kind in NUMBER_KINDS:
        return _number_text(value)
    return str(value)


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------

def _at_scale(d: Decimal, scale: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 100
        return d.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)


def _compare_numbers(a: Any, b: Any, spec: dict) -> str:
    da, db = _decimal(a), _decimal(b)
    if da is None or db is None:
        return EQUAL if str(a) == str(b) else DIFFERENT
    if da.is_nan() or db.is_nan():
        return EQUAL if da.is_nan() and db.is_nan() else DIFFERENT
    if da == db:
        return EQUAL
    if spec["kind"] == "integer" or not (da.is_finite() and db.is_finite()):
        return DIFFERENT
    if spec["kind"] == "decimal":
        if spec.get("scale") is not None:
            same = _at_scale(da, spec["scale"]) == _at_scale(db, spec["scale"])
        else:
            same = abs(da - db) <= Decimal(DECIMAL_REL_TOL) * max(abs(da), abs(db))
    else:
        same = math.isclose(float(da), float(db), rel_tol=FLOAT_REL_TOL,
                            abs_tol=FLOAT_ABS_TOL)
    return CLOSE if same else DIFFERENT


def compare_cells(a: Any, b: Any, spec: dict, tz: _dt.tzinfo) -> str:
    """EQUAL, CLOSE (accepted within the column type's tolerance) or DIFFERENT, by the
    Databricks type in `spec` (see the module docstring)."""
    if a is None or b is None:
        return EQUAL if a is None and b is None else DIFFERENT
    kind = spec["kind"]
    if kind in ("date", "timestamp", "boolean"):
        return EQUAL if norm_key(a, kind, tz) == norm_key(b, kind, tz) else DIFFERENT
    if kind in NUMBER_KINDS:
        return _compare_numbers(a, b, spec)
    return EQUAL if str(a) == str(b) else DIFFERENT


# ---------------------------------------------------------------------------
# Shapes and the run
# ---------------------------------------------------------------------------

def _index_rows(rows: list, n_dims: int, specs: list, tz) -> tuple[dict, list]:
    """key tuple -> measure values, plus the keys seen more than once."""
    out: dict = {}
    dupes: list = []
    for row in rows:
        key = tuple(norm_key(v, specs[i]["kind"], tz) for i, v in enumerate(row[:n_dims]))
        if key in out:
            dupes.append(key)
        out[key] = list(row[n_dims:])
    return out, dupes


def _sort_key(key: tuple) -> tuple:
    return tuple((v is None, "" if v is None else v) for v in key)


def _compare_block(dbx: dict, block: dict, n_dims: int, specs: list,
                   measures: list, tz) -> tuple[list, dict]:
    """Mismatches between Databricks and one AgentQL result covering some measures, and
    the counts of cells holding a value and cells accepted within tolerance."""
    idx = block["measures"]
    ts, dupes = _index_rows(block["rows"], n_dims, specs, tz)
    out = [{"key": list(k), "issue": "duplicate key in the ThoughtSpot result"} for k in dupes]
    counts = {"non_null_cells": 0, "tolerance_accepted": 0}
    names = [measures[i]["title"] for i in idx]
    for key in sorted(set(dbx) | set(ts), key=_sort_key):
        if key not in dbx or key not in ts:
            side = "ThoughtSpot" if key in ts else "Databricks"
            out.append({"key": list(key), "issue": f"row only in {side}", "measures": names})
            continue
        for j, i in enumerate(idx):
            a, b = dbx[key][i], ts[key][j]
            counts["non_null_cells"] += a is not None or b is not None
            verdict = compare_cells(a, b, specs[n_dims + i], tz)
            counts["tolerance_accepted"] += verdict == CLOSE
            if verdict == DIFFERENT:
                out.append({"key": list(key), "measure": measures[i]["title"],
                            "databricks": a, "thoughtspot": b})
    return out, counts


def compare_shape(n_dims: int, specs: list, dbx_rows: list, ts_blocks: list,
                  measures: list, tz) -> dict:
    """Compare one shape. `ts_blocks` is a list of `{"measures": [measure indices],
    "rows": [...]}`, one per AgentQL query (all measures in one query, or one each).
    Raises ValueError when an AgentQL row is not as wide as its query."""
    for block in ts_blocks:
        check_row_widths(block["rows"], n_dims + len(block["measures"]), "ThoughtSpot")
    dbx, dupes = _index_rows(dbx_rows, n_dims, specs, tz)
    found = [{"key": list(k), "issue": "duplicate key in the Databricks result"} for k in dupes]
    totals = {"non_null_cells": 0, "tolerance_accepted": 0}
    ts_rows = 0
    for block in ts_blocks:
        mismatches, counts = _compare_block(dbx, block, n_dims, specs, measures, tz)
        found.extend(mismatches)
        for k in totals:
            totals[k] += counts[k]
        ts_rows = max(ts_rows, len(block["rows"]))
    compared = sum(len(b["measures"]) for b in ts_blocks)
    return {"rows_databricks": len(dbx_rows), "rows_thoughtspot": ts_rows,
            "cells": len(dbx_rows) * compared, **totals, "mismatch_count": len(found),
            "mismatches": found[:MAX_MISMATCHES_KEPT]}


def shape_status(result: dict) -> str:
    """error, skipped, mismatch, `no_data` (no row on either side, or every compared cell
    NULL on both), or match."""
    if result.get("errors"):
        return "error"
    if result.get("skipped"):
        return "skipped"
    if result.get("mismatch_count"):
        return "mismatch"
    return "match" if result.get("non_null_cells") else "no_data"


_STATUSES = ("match", "mismatch", "error", "skipped", "no_data")


def summarise(shapes: list[dict], problems: list[str], filter_required: bool) -> dict:
    """Totals over the shape results, and the run status, the first that applies:

    - `error`: a shape could not be run;
    - `mismatch`: a cell disagrees, or a plan problem (`problems`);
    - `no_data`: no shape compared a cell holding a value;
    - `incomplete`: `filter_required` (the default shapes) and no filtered shape
      compared a cell holding a value, so no search filter stood beside the measures;
    - `match`."""
    counts = {s: sum(1 for r in shapes if r["status"] == s) for s in _STATUSES}
    summary = {"shapes": len(shapes), **counts,
               **{k: sum(r.get(k, 0) for r in shapes)
                  for k in ("cells", "non_null_cells", "tolerance_accepted")},
               "mismatches": sum(r.get("mismatch_count", 0) for r in shapes),
               "problems": len(problems)}
    filtered = any(r.get("filter") and r.get("non_null_cells") for r in shapes)
    if counts["error"]:
        status = "error"
    elif counts["mismatch"] or problems:
        status = "mismatch"
    elif not summary["non_null_cells"]:
        status = "no_data"
    elif filter_required and not filtered:
        status = "incomplete"
    else:
        status = "match"
    return {"status": status, "summary": summary}
