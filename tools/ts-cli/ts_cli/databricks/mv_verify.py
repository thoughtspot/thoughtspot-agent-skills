"""The plan behind `ts databricks verify` (BL-639): no I/O.

Checks that a Model converted from a Databricks Metric View returns the same numbers as
the Metric View. The same query shapes run on both sides, `MEASURE()` on the Metric View
and AgentQL on the Model, and the results are compared cell by cell. Lint and import both
passed Models that returned wrong numbers (BL-638); only this comparison caught them.

This module plans the run: which MV measures and dimensions the Model carries, the query
shapes, the SQL text for both sides, and how the imported Model differs from the TML
file. `mv_verify_compare.py` judges the results; `commands/databricks_verify.py` runs the
queries.

AgentQL wrappers: `spotql_ops.classify_model_columns` gives `AGG` for an aggregate
formula and `SUM` for a semi-additive `first_value`/`last_value` formula; both were
live-checked on the run BL-639 records. A raw column is wrapped in its own aggregation
(`AVERAGE` -> `AVG`, `COUNT_DISTINCT` -> `COUNT(DISTINCT …)`). Only the `SUM` form of that
was live-checked, because that run's raw columns were all `SUM`. `STD_DEVIATION` and
`VARIANCE` cannot be queried on a Model column in AgentQL, so those measures are listed,
not compared.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ts_cli.commands.load_databricks import dbx_ident
from ts_cli.databricks.mv_translate import display_title
from ts_cli.spotql_ops import classify_model_columns

_FLAG_NAME = re.compile(r"^(is|has)[_ ]", re.IGNORECASE)

#: A raw Model column's aggregation -> the AgentQL aggregate that reproduces it.
#: Read side only: the key is the Model's aggregation, the value an AgentQL label.
_RAW_AGGREGATE = {"SUM": "SUM", "AVERAGE": "AVG", "MIN": "MIN", "MAX": "MAX",
                  "COUNT": "COUNT", "COUNT_DISTINCT": "COUNT(DISTINCT)"}


# ---------------------------------------------------------------------------
# Plan: which measures and dimensions can be compared
# ---------------------------------------------------------------------------

def model_body(model_doc: dict) -> dict:
    """The `model:` mapping of a Model TML document (or the document itself)."""
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


def converter_skips(translated: Optional[dict]) -> dict:
    """{"measure": {names}, "dimension": {names}} the converter skipped, from the
    translate-formulas output; empty when it was not given."""
    out: dict = {"measure": set(), "dimension": set()}
    for s in (translated or {}).get("skipped") or []:
        if isinstance(s, dict) and s.get("role") in out:
            out[s["role"]].add(s.get("name"))
    return out


def _absent(plan: dict, role: str, name: str, skips: dict) -> None:
    key = "skipped_by_converter" if name in skips[role] else "missing"
    plan[key][role + "s"].append(name)


def _plan_measures(parsed: dict, columns: dict, plan: dict, skips: dict) -> None:
    for m in parsed.get("measures") or []:
        col = columns.get(display_title(m).lower())
        if col is None:
            _absent(plan, "measure", m["name"], skips)
        elif col["column_type"] != "MEASURE":
            plan["wrong_column_type"].append({"mv_name": m["name"], "title": col["name"],
                                              "role": "measure",
                                              "column_type": col["column_type"]})
        else:
            fn, reason = agentql_function(col)
            entry = {"mv_name": m["name"], "title": col["name"]}
            if fn is None:
                plan["not_verifiable"].append({**entry, "reason": reason})
            else:
                plan["measures"].append({**entry, "agentql": fn})


def _plan_dimensions(parsed: dict, columns: dict, exprs: dict, plan: dict,
                     skips: dict) -> None:
    for d in parsed.get("dimensions") or []:
        col = columns.get(display_title(d).lower())
        if col is None:
            _absent(plan, "dimension", d["name"], skips)
        elif col["column_type"] == "MEASURE":
            plan["wrong_column_type"].append({"mv_name": d["name"], "title": col["name"],
                                              "role": "dimension", "column_type": "MEASURE"})
        else:
            title = col["name"]
            plan["dimensions"].append({
                "mv_name": d["name"], "title": title,
                "flag": is_flag_dimension(d["name"], title, exprs.get(title, ""))})


def window_order_dimensions(parsed: dict) -> list[str]:
    """MV names of the `order:` dimensions of windowed measures, in first-seen order."""
    seen: list[str] = []
    for m in parsed.get("measures") or []:
        order = (m.get("window") or {}).get("order")
        if order and order not in seen:
            seen.append(order)
    return seen


def build_plan(parsed: dict, model_doc: dict, translated: Optional[dict] = None) -> dict:
    """Which MV measures and dimensions the Model carries, and how to query each.

    An MV entry's display title (`mv_translate.display_title`, the name `build-model`
    gives it) is looked up among the Model's columns ignoring case; the Model's own
    spelling is used in AgentQL. An entry with no column is `skipped_by_converter` when
    `translated` (the translate-formulas output) lists it as skipped, else `missing`. A
    measure on an ATTRIBUTE column, or a dimension on a MEASURE column, is
    `wrong_column_type`. `plan_problems` says which of these fail the run."""
    model = model_body(model_doc)
    columns = {c["name"].lower(): c for c in classify_model_columns({"model": model})}
    skips = converter_skips(translated)
    plan: dict = {"model_name": model.get("name") or "", "measures": [], "dimensions": [],
                  "skipped_by_converter": {"measures": [], "dimensions": []},
                  "missing": {"measures": [], "dimensions": []},
                  "wrong_column_type": [], "not_verifiable": []}
    _plan_measures(parsed, columns, plan, skips)
    _plan_dimensions(parsed, columns, _formula_exprs(model), plan, skips)
    in_model = {d["mv_name"] for d in plan["dimensions"]}
    plan["order_dimensions"] = [{"mv_name": o, "in_model": o in in_model}
                                for o in window_order_dimensions(parsed)]
    return plan


def plan_problems(plan: dict) -> list[str]:
    """What fails the run before any query: a measure or dimension the converter did not
    skip but the Model lacks, and one on a column of the wrong type."""
    out = []
    for role in ("measures", "dimensions"):
        if plan["missing"][role]:
            out.append(f"MV {role} with no Model column and not skipped by the converter: "
                       f"{', '.join(plan['missing'][role])}")
    for w in plan["wrong_column_type"]:
        out.append(f"MV {w['role']} {w['mv_name']} is a {w['column_type']} column "
                   f"({w['title']}) in the Model")
    return out


def _column_signature(model_doc: dict) -> dict:
    sig = {}
    for c in model_body(model_doc).get("columns") or []:
        props = c.get("properties") or {}
        ctype = props.get("column_type") or "ATTRIBUTE"
        agg = (props.get("aggregation") or "SUM") if ctype == "MEASURE" else None
        sig[c.get("name")] = (ctype, agg)
    return sig


def model_differences(file_doc: dict, imported_doc: dict) -> list[str]:
    """Column names, types and aggregations that differ between the Model TML file and
    the imported Model's export. The plan is built from the export, which is what
    AgentQL queries; a difference means the file is not what was imported."""
    a, b = _column_signature(file_doc), _column_signature(imported_doc)
    out = [f"column {n!r} is in --model-tml but not in the imported Model"
           for n in a if n not in b]
    out += [f"column {n!r} is in the imported Model but not in --model-tml"
            for n in b if n not in a]
    out += [f"column {n!r}: --model-tml has {a[n]}, the imported Model {b[n]}"
            for n in a if n in b and a[n] != b[n]]
    return out


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def flag_filter_shapes(dim: dict) -> list[dict]:
    """The two filtered totals for a boolean flag: `= true` and `= false`."""
    return [{"label": f"{dim['title']} = {lit}", "dims": [], "filter": [dim["mv_name"], lit],
             "flag": dim["mv_name"]} for lit in ("true", "false")]


def _usable_text(t: str, lowered: list) -> bool:
    return (t != "" and t.strip() == t and "'" not in t and "\\" not in t
            and lowered.count(t.lower()) == 1)


def _string_literal(present: list) -> Optional[str]:
    texts = sorted({v for v in present if isinstance(v, str)})
    lowered = [t.lower() for t in texts]
    usable = [t for t in texts if _usable_text(t, lowered)] if len(texts) > 1 else []
    return f"'{usable[0]}'" if usable else None


def _integer_literal(present: list) -> Optional[str]:
    nums = sorted({int(v) for v in present if re.fullmatch(r"-?\d+", str(v))})
    return str(nums[0]) if len(nums) > 1 else None


def _date_literal(present: list) -> Optional[str]:
    days = sorted({str(v)[:10] for v in present
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)[:10])})
    return f"DATE '{days[0]}'" if len(days) > 1 else None


_LITERAL_BY_KIND = {"string": _string_literal, "integer": _integer_literal,
                    "date": _date_literal}


def pick_filter_literal(values: list, kind: str) -> Optional[str]:
    """A SQL literal for one value of a dimension, used as written on both sides, or
    None. A filter on the only value would equal the total, so two distinct values are
    needed. A string value is passed over when it is empty, has spaces at either end,
    holds a quote or a backslash (the two sides escape them differently), or equals
    another value in all but case (AgentQL compares strings case-insensitively, BL-333).
    An integer is written as is; a date as `DATE 'yyyy-mm-dd'` (live-checked on both
    sides 2026-11-27; `TO_DATE('yyyy-mm-dd')` failed in AgentQL's SQL on Databricks)."""
    pick = _LITERAL_BY_KIND.get(kind)
    return pick([v for v in values if v is not None]) if pick else None


#: Kinds the search filter tries, in order: strings first, then exact numbers, then dates.
SEARCH_FILTER_KINDS = ("string", "integer", "date")


def search_filter_shape(dims: list[dict], dim_values: dict) -> tuple[Optional[dict], str]:
    """The total filtered on one value of a dimension: a search filter beside every
    measure at once, LOD columns included. `dim_values` maps an MV dimension name to
    `(kind, values)` from its single-dimension shape. Returns (shape, "") or
    (None, the reason no dimension gave a usable value)."""
    for kind in SEARCH_FILTER_KINDS:
        for d in dims:
            got = dim_values.get(d["mv_name"])
            if not got or got[0] != kind:
                continue
            literal = pick_filter_literal(got[1], kind)
            if literal is not None:
                return {"label": f"{d['title']} = {literal}", "dims": [],
                        "filter": [d["mv_name"], literal], "search_filter": True}, ""
    return None, ("no string, integer or date dimension had two usable values (a string "
                  "value must be non-empty, without spaces at either end, quotes or "
                  "backslashes, and unique ignoring case)")


def default_shapes(plan: dict) -> list[dict]:
    """The total; each dimension on its own; and for each boolean flag, the total
    filtered `= true` and `= false`.

    A window's `order:` dimension is an MV dimension, so when the Model carries it, it is
    among the single-dimension shapes; the plan's `order_dimensions` says which are not.
    Grouping on a flag is its single-dimension shape. A filtered shape carries `flag`,
    the dimension it needs to be BOOLEAN on Databricks. The command adds shapes that need
    the data first: flags found by their Databricks type, and `search_filter_shape`."""
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

def _dq(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def quote_mv_fqn(mv_fqn: str) -> str:
    """`catalog.schema.view` with each part backtick-quoted; used as given when it
    already holds a backtick."""
    if "`" in mv_fqn:
        return mv_fqn
    return ".".join(dbx_ident(p) for p in mv_fqn.split("."))


def databricks_sql(mv_fqn: str, shape: dict, measures: list[dict]) -> str:
    """`SELECT <dims>, MEASURE(m) AS m0, ... FROM <mv> [WHERE d = lit] [GROUP BY ALL]`."""
    sel = [dbx_ident(d) for d in shape["dims"]]
    sel += [f"MEASURE({dbx_ident(m['mv_name'])}) AS {dbx_ident(f'm{i}')}"
            for i, m in enumerate(measures)]
    sql = f"SELECT {', '.join(sel)} FROM {quote_mv_fqn(mv_fqn)}"
    if shape.get("filter"):
        sql += f" WHERE {dbx_ident(shape['filter'][0])} = {shape['filter'][1]}"
    if shape["dims"]:
        sql += " GROUP BY ALL"
    return sql


def _agentql_measure(m: dict) -> str:
    ref = f'"t1".{_dq(m["title"])}'
    if m["agentql"] == "COUNT(DISTINCT)":
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
