"""Pure logic behind `ts databricks verify` (BL-639): no I/O.

Checks that a Model converted from a Databricks Metric View returns the same numbers as
the Metric View. The same query shapes run on both sides, `MEASURE()` on the Metric View
and AgentQL on the Model, and the results are compared cell by cell. Lint and import both
passed Models that returned wrong numbers (BL-638); only this comparison caught them.

This module plans the run and judges it: which MV measures and dimensions the Model
carries, the default query shapes, the SQL text for both sides, key normalisation and the
comparison. The command (`commands/databricks_verify.py`) runs the queries.

What the comparison relies on, each live-checked on the run BL-639 records (21 shapes,
6,549 cells):

- **AgentQL wrappers** come from `spotql_ops.classify_model_columns`: `AGG` for an
  aggregate formula, `SUM` for a semi-additive `first_value`/`last_value` formula. A raw
  column is wrapped in its own aggregation (`AVERAGE` -> `AVG`), which BL-639's harness
  did not need (its raw columns were all `SUM`); `STD_DEVIATION` and `VARIANCE` cannot be
  queried on a Model column in AgentQL, so those measures are listed, not compared.
- **DATE values** arrive from AgentQL as epoch seconds (or milliseconds) at midnight in
  the ThoughtSpot cluster's time zone, so a date key needs that zone to decode.
- **Booleans** compare case-insensitively (`true` from Databricks, `True` from AgentQL),
  and numbers with relative and absolute tolerance 1e-9.

TIMESTAMP keys are normalised the same way at second precision, the Databricks value
converted to the cluster zone; that conversion is not live-verified. A wrong guess shows
up as rows present on one side only, never as a silent match.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ts_cli.databricks.mv_translate import display_title
from ts_cli.spotql_ops import classify_model_columns

REL_TOL = 1e-9
ABS_TOL = 1e-9
#: AgentQL caps an ordinary SELECT at 100,000 rows and says nothing when it does.
AGENTQL_ROW_CAP = 100_000
#: Mismatch entries kept per shape in the report; the count is always the full one.
MAX_MISMATCHES_KEPT = 50

_FLAG_NAME = re.compile(r"^(is|has)[_ ]", re.IGNORECASE)

#: A raw Model column's aggregation -> the AgentQL aggregate that reproduces it.
_RAW_AGGREGATE = {"SUM": "SUM", "AVERAGE": "AVG", "MIN": "MIN", "MAX": "MAX",
                  "COUNT": "COUNT", "COUNT_DISTINCT": "COUNT_DISTINCT"}

#: Databricks Statement Execution `type_name` -> how a value of it is normalised.
_KIND_BY_TYPE = {"DATE": "date", "TIMESTAMP": "timestamp", "TIMESTAMP_NTZ": "timestamp",
                 "BOOLEAN": "boolean", "BYTE": "number", "SHORT": "number",
                 "INT": "number", "LONG": "number", "FLOAT": "number",
                 "DOUBLE": "number", "DECIMAL": "number"}


# ---------------------------------------------------------------------------
# Plan: which measures and dimensions can be compared
# ---------------------------------------------------------------------------

def _model_body(model_doc: dict) -> dict:
    inner = model_doc.get("model") if isinstance(model_doc, dict) else None
    return inner if isinstance(inner, dict) else (model_doc or {})


def _formula_exprs(model: dict) -> dict:
    """Model column name -> its formula's expression (formula columns only)."""
    by_id = {f.get("id"): f.get("expr") or "" for f in model.get("formulas") or []}
    return {c.get("name"): by_id.get(c.get("formula_id"), "")
            for c in model.get("columns") or [] if c.get("formula_id")}


def agentql_function(classified: dict) -> tuple[Optional[str], Optional[str]]:
    """(AgentQL aggregate, None) for a classified MEASURE column, or (None, reason)."""
    if classified["kind"] == "raw_measure":
        fn = _RAW_AGGREGATE.get(str(classified.get("aggregation") or "SUM").upper())
        if fn is None:
            return None, (f"aggregation {classified['aggregation']} cannot be queried on a "
                          f"Model column in AgentQL (STDDEV and VARIANCE fail there)")
        return fn, None
    return classified["wrapper"], None


def is_flag_dimension(mv_name: str, title: str, formula_expr: str = "") -> bool:
    """A boolean flag, by BL-639's heuristic: a `sql_bool_op` formula in the Model, or a
    name starting `is_`/`has_` (any case, an underscore or a space after it)."""
    if formula_expr.lstrip().lower().startswith("sql_bool_op"):
        return True
    return bool(_FLAG_NAME.match(mv_name) or _FLAG_NAME.match(title))


def _plan_measures(parsed: dict, classified: dict) -> tuple[list, list, list]:
    measures, missing, unverifiable = [], [], []
    for m in parsed.get("measures") or []:
        title = display_title(m)
        col = classified.get(title)
        if col is None or col["column_type"] != "MEASURE":
            missing.append(m["name"])
            continue
        fn, reason = agentql_function(col)
        if fn is None:
            unverifiable.append({"mv_name": m["name"], "title": title, "reason": reason})
            continue
        measures.append({"mv_name": m["name"], "title": title, "agentql": fn})
    return measures, missing, unverifiable


def _plan_dimensions(parsed: dict, classified: dict, exprs: dict) -> tuple[list, list]:
    dims, missing = [], []
    for d in parsed.get("dimensions") or []:
        title = display_title(d)
        col = classified.get(title)
        if col is None or col["column_type"] == "MEASURE":
            missing.append(d["name"])
            continue
        dims.append({"mv_name": d["name"], "title": title,
                     "flag": is_flag_dimension(d["name"], title, exprs.get(title, ""))})
    return dims, missing


def window_order_dimensions(parsed: dict) -> list[str]:
    """MV names of the `order:` dimensions of windowed measures, in first-seen order."""
    seen: list[str] = []
    for m in parsed.get("measures") or []:
        order = (m.get("window") or {}).get("order")
        if order and order not in seen:
            seen.append(order)
    return seen


def build_plan(parsed: dict, model_doc: dict) -> dict:
    """Which MV measures and dimensions the Model carries, and how to query each.

    A measure counts when its display title (`mv_translate.display_title`, the name
    `build-model` gives it) is a MEASURE column of the Model; the rest are listed under
    `not_in_model`, which is not a mismatch. A dimension counts when its title is a
    non-MEASURE column."""
    model = _model_body(model_doc)
    classified = {c["name"]: c for c in classify_model_columns({"model": model})}
    exprs = _formula_exprs(model)
    measures, missing_m, unverifiable = _plan_measures(parsed, classified)
    dims, missing_d = _plan_dimensions(parsed, classified, exprs)
    in_model = {d["mv_name"] for d in dims}
    return {
        "model_name": model.get("name") or "",
        "measures": measures,
        "dimensions": dims,
        "order_dimensions": [{"mv_name": o, "in_model": o in in_model}
                             for o in window_order_dimensions(parsed)],
        "not_in_model": {"measures": missing_m, "dimensions": missing_d},
        "not_verifiable": unverifiable,
    }


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def flag_filter_shapes(dim: dict) -> list[dict]:
    """The two filtered totals for a boolean flag: `= true` and `= false`."""
    return [{"label": f"{dim['title']} = {lit}", "dims": [], "filter": [dim["mv_name"], lit],
             "flag": dim["mv_name"]} for lit in ("true", "false")]


def default_shapes(plan: dict) -> list[dict]:
    """The total; each dimension on its own; and for each boolean flag, the total
    filtered `= true` and `= false`.

    A window's `order:` dimension is an MV dimension, so when the Model carries it, it is
    among the single-dimension shapes; the plan's `order_dimensions` says which are not.
    Grouping on a flag is its single-dimension shape. A filtered shape carries `flag`,
    the dimension it needs to be BOOLEAN on Databricks."""
    shapes = [{"label": "total", "dims": [], "filter": None}]
    for d in plan["dimensions"]:
        shapes.append({"label": f"by {d['title']}", "dims": [d["mv_name"]], "filter": None})
    for d in plan["dimensions"]:
        if d["flag"]:
            shapes.extend(flag_filter_shapes(d))
    return shapes


def _str_list(value: Any, length: Optional[int] = None) -> bool:
    return (isinstance(value, list) and all(isinstance(x, str) for x in value)
            and (length is None or len(value) == length))


def _parse_shape(s: Any, known: set) -> dict:
    """One `--shapes` entry, validated; raises ValueError without the entry number."""
    if not isinstance(s, dict) or not isinstance(s.get("label"), str):
        raise ValueError("needs a string 'label'")
    dims = s.get("dims") or []
    if not _str_list(dims):
        raise ValueError("'dims' must be a list of MV dimension names")
    flt = s.get("filter")
    if flt is not None and not _str_list(flt, 2):
        raise ValueError("'filter' must be null or [dimension, SQL literal]")
    unknown = [d for d in dims + ([flt[0]] if flt else []) if d not in known]
    if unknown:
        raise ValueError(f"not a dimension the Model carries: {', '.join(unknown)}")
    return {"label": s["label"], "dims": list(dims), "filter": list(flt) if flt else None}


def parse_shapes(raw: Any, plan: dict) -> list[dict]:
    """Validate a `--shapes` list of `{"label", "dims", "filter"}` against the plan.

    `dims` are MV dimension names; `filter` is null or `[MV dimension name, SQL
    literal]`, the literal used as written on both sides. Every name must be a dimension
    the Model carries. Raises ValueError naming the first bad entry."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("--shapes must be a non-empty JSON list")
    known = {d["mv_name"] for d in plan["dimensions"]}
    shapes = []
    for i, s in enumerate(raw):
        try:
            shapes.append(_parse_shape(s, known))
        except ValueError as exc:
            raise ValueError(f"shape {i + 1}: {exc}") from None
    return shapes


# ---------------------------------------------------------------------------
# SQL text
# ---------------------------------------------------------------------------

def _bt(name: str) -> str:
    return "`" + str(name).replace("`", "``") + "`"


def _dq(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def quote_mv_fqn(mv_fqn: str) -> str:
    """`catalog.schema.view` with each part backtick-quoted; used as given when it
    already holds a backtick."""
    if "`" in mv_fqn:
        return mv_fqn
    return ".".join(_bt(p) for p in mv_fqn.split("."))


def databricks_sql(mv_fqn: str, shape: dict, measures: list[dict]) -> str:
    """`SELECT <dims>, MEASURE(m) AS m0, ... FROM <mv> [WHERE d = lit] [GROUP BY ALL]`."""
    sel = [_bt(d) for d in shape["dims"]]
    sel += [f"MEASURE({_bt(m['mv_name'])}) AS {_bt(f'm{i}')}" for i, m in enumerate(measures)]
    sql = f"SELECT {', '.join(sel)} FROM {quote_mv_fqn(mv_fqn)}"
    if shape.get("filter"):
        sql += f" WHERE {_bt(shape['filter'][0])} = {shape['filter'][1]}"
    if shape["dims"]:
        sql += " GROUP BY ALL"
    return sql


def _agentql_measure(m: dict) -> str:
    ref = f'"t1".{_dq(m["title"])}'
    if m["agentql"] == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {ref})"
    return f"{m['agentql']}({ref})"


def agentql_sql(model_name: str, shape: dict, measures: list[dict], titles: dict) -> str:
    """The same shape in AgentQL over the Model, columns by display title.

    `titles` maps an MV dimension name to its Model column name."""
    cols = [f'"t1".{_dq(titles[d])}' for d in shape["dims"]]
    sel = cols + [f'{_agentql_measure(m)} AS "M{i}"' for i, m in enumerate(measures)]
    q = f'SELECT {", ".join(sel)} FROM {_dq(model_name)} AS "t1"'
    if shape.get("filter"):
        q += f' WHERE "t1".{_dq(titles[shape["filter"][0]])} = {shape["filter"][1]}'
    if cols:
        q += " GROUP BY " + ", ".join(cols)
    return q


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def databricks_result(response: dict) -> tuple[list[str], list[list]]:
    """(column kinds, rows) from a Statement Execution response.

    Refuses a result split into chunks or truncated: comparing part of it would report
    the missing rows as mismatches."""
    manifest = response.get("manifest") or {}
    result = response.get("result") or {}
    chunks = manifest.get("total_chunk_count") or 1
    if chunks > 1 or result.get("next_chunk_index") is not None:
        raise ValueError(f"the Databricks result arrived in {chunks} chunks; narrow the "
                         f"shape (fewer or coarser dimensions)")
    if manifest.get("truncated"):
        raise ValueError("the Databricks result was truncated; narrow the shape")
    cols = (manifest.get("schema") or {}).get("columns") or []
    kinds = [_KIND_BY_TYPE.get(str(c.get("type_name") or "").upper(), "string") for c in cols]
    return kinds, result.get("data_array") or []


def _epoch_seconds(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        v = float(value)
    else:
        return None
    return v / 1000 if abs(v) >= 1e11 else v      # milliseconds past ~year 5138 in seconds


def _date_text(value: Any, tz: _dt.tzinfo) -> str:
    epoch = _epoch_seconds(value)
    if epoch is not None:
        return _dt.datetime.fromtimestamp(epoch, tz).date().isoformat()
    return str(value)[:10]


def _timestamp_text(value: Any, tz: _dt.tzinfo) -> str:
    epoch = _epoch_seconds(value)
    if epoch is not None:
        return _dt.datetime.fromtimestamp(epoch, tz).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _number_text(value: Any) -> str:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    if not d.is_finite():
        return str(d)
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
    if kind == "number":
        return _number_text(value)
    return str(value)


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def cells_match(a: Any, b: Any, kind: str, tz: _dt.tzinfo) -> bool:
    """Do two measure values agree? NULL matches only NULL; numbers within 1e-9 (relative
    or absolute); dates and timestamps after normalising; booleans in any case."""
    if a is None or b is None:
        return a is None and b is None
    if kind in ("date", "timestamp", "boolean"):
        return norm_key(a, kind, tz) == norm_key(b, kind, tz)
    fa, fb = _as_float(a), _as_float(b)
    if fa is not None and fb is not None:
        if math.isnan(fa) or math.isnan(fb):
            return math.isnan(fa) and math.isnan(fb)
        return math.isclose(fa, fb, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    sa, sb = str(a), str(b)
    if sa.lower() in ("true", "false"):
        return sa.lower() == sb.lower()
    return sa == sb


def _index_rows(rows: list, n_dims: int, kinds: list, tz) -> tuple[dict, list]:
    """key tuple -> measure values, plus the keys seen more than once."""
    out: dict = {}
    dupes: list = []
    for row in rows:
        key = tuple(norm_key(v, kinds[i], tz) for i, v in enumerate(row[:n_dims]))
        if key in out:
            dupes.append(key)
        out[key] = list(row[n_dims:])
    return out, dupes


def _sort_key(key: tuple) -> tuple:
    return tuple((v is None, "" if v is None else v) for v in key)


def _compare_block(dbx: dict, block: dict, n_dims: int, kinds: list,
                   measures: list, tz) -> list[dict]:
    """Mismatches between Databricks and one AgentQL result covering some measures."""
    idx = block["measures"]
    ts, dupes = _index_rows(block["rows"], n_dims, kinds, tz)
    out = [{"key": list(k), "issue": "duplicate key in the ThoughtSpot result"} for k in dupes]
    names = [measures[i]["title"] for i in idx]
    for key in sorted(set(dbx) | set(ts), key=_sort_key):
        if key not in dbx or key not in ts:
            side = "ThoughtSpot" if key in ts else "Databricks"
            out.append({"key": list(key), "issue": f"row only in {side}", "measures": names})
            continue
        for j, i in enumerate(idx):
            a, b = dbx[key][i], ts[key][j]
            if not cells_match(a, b, kinds[n_dims + i], tz):
                out.append({"key": list(key), "measure": measures[i]["title"],
                            "databricks": a, "thoughtspot": b})
    return out


def compare_shape(n_dims: int, kinds: list, dbx_rows: list, ts_blocks: list,
                  measures: list, tz) -> dict:
    """Compare one shape. `ts_blocks` is a list of `{"measures": [measure indices],
    "rows": [...]}`, one per AgentQL query (all measures in one query, or one each)."""
    dbx, dupes = _index_rows(dbx_rows, n_dims, kinds, tz)
    found = [{"key": list(k), "issue": "duplicate key in the Databricks result"} for k in dupes]
    ts_rows = 0
    for block in ts_blocks:
        found.extend(_compare_block(dbx, block, n_dims, kinds, measures, tz))
        ts_rows = max(ts_rows, len(block["rows"]))
    compared = sum(len(b["measures"]) for b in ts_blocks)
    return {"rows_databricks": len(dbx_rows), "rows_thoughtspot": ts_rows,
            "cells": len(dbx_rows) * compared, "mismatch_count": len(found),
            "mismatches": found[:MAX_MISMATCHES_KEPT]}


def shape_status(result: dict) -> str:
    if result.get("errors"):
        return "error"
    if result.get("skipped"):
        return "skipped"
    return "mismatch" if result.get("mismatch_count") else "match"


def summarise(shapes: list[dict]) -> dict:
    """Totals over the shape results, and the run status: `error` when any shape could
    not be run, else `mismatch` when any cell disagrees, else `match`."""
    counts = {s: sum(1 for r in shapes if r["status"] == s)
              for s in ("match", "mismatch", "error", "skipped")}
    summary = {"shapes": len(shapes), **counts,
               "cells": sum(r.get("cells", 0) for r in shapes),
               "mismatches": sum(r.get("mismatch_count", 0) for r in shapes)}
    status = "error" if counts["error"] else ("mismatch" if counts["mismatch"] else "match")
    return {"status": status, "summary": summary}
