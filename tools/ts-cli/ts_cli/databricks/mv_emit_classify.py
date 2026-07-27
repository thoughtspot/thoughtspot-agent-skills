"""Column classification + non-window dimension/measure/filter emitters, plus
LOD (level-of-detail) dimension-window emission, for the reverse (ThoughtSpot
Model TML -> Databricks Metric View) emit direction. Split out of mv_emit.py
under the file-size gate (tools/validate/check_file_size.py).

classify_column routes a Model TML column to dimension/measure/filter/window
(window-measure and LOD-dimension routing decisions only -- true
window-measure emission is mv_emit_window.py; LOD-dimension emission lives
here, since LOD results are always dimensions, never `window:` measures).
emit_dimension/emit_measure/emit_filter/emit_lod_dimension are mv_emit.py's
non-window emitters, reused unchanged by build_metric_view.

Imports Foundation (to_snake, resolve_refs) from mv_emit_base.py rather than
from mv_emit.py itself, to avoid a circular import: mv_emit.py's assembly
code imports classify_column/emit_*/_find_formula/_formula_expr/_child_nodes/
_is_boolean_top/_finalize_column/_raise_unresolved_ref/_IF_FAMILY_FNS/_LOD_FNS
from here, so this module cannot import back from mv_emit.py. Does NOT
depend on mv_emit_joins.py -- classification and emission never need a join
path themselves (build_metric_view supplies col_resolver/ref_resolver
already carrying that information). mv_emit.py re-exports every name
needed by external callers so existing callers/tests keep importing from
`ts_cli.databricks.mv_emit` unchanged.

Pure: stdlib only. No I/O here.
"""
from __future__ import annotations
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql, AGG_MAP, wrap_measure_if_needed
from ts_cli.databricks.mv_emit_base import to_snake, resolve_refs


# --- Column classification & routing (non-window) -----------------------------
# Decision tree per agents/shared/mappings/ts-databricks/ts-to-databricks-rules.md
# "Column Type Classification" / "Filter Generation" / window sections. LOD
# dimensions and window measures are only *classified* here — their emission
# (dimension window functions, `window:` measures) is Task 9's job.

_LOD_FNS = {"group_aggregate", "group_sum", "group_count", "group_average",
            "group_max", "group_min", "group_unique_count"}
_WINDOW_MEASURE_FNS = {
    "moving_sum", "moving_average", "cumulative_sum", "cumulative_average",
    "last_value", "first_value", "rank",
}
_IF_FAMILY_FNS = {
    "sum_if", "count_if", "unique_count_if", "average_if",
    "min_if", "max_if", "stddev_if", "variance_if",
}
_PERIOD_OFFSET_FNS = {"diff_months", "diff_quarters", "diff_years"}
_COMPARISON_OPS = {"=", "!=", "<", "<=", ">", ">="}

# ThoughtSpot properties.aggregation -> Databricks aggregate keyword, per
# ts-to-databricks-rules.md "Aggregation Functions". Values are pulled from
# mv_emit_sql.AGG_MAP (the TS-formula-fn -> DBX-fn source of truth) rather
# than re-declaring the same target strings a second time.
_PROP_AGG_TO_DBX = {
    "SUM": AGG_MAP["sum"],
    "COUNT": AGG_MAP["count"],
    "AVERAGE": AGG_MAP["average"],
    "AVG": AGG_MAP["avg"],
    "MIN": AGG_MAP["min"],
    "MAX": AGG_MAP["max"],
    "STD_DEVIATION": AGG_MAP["stddev"],
    "STDDEV": AGG_MAP["stddev"],
    "VARIANCE": AGG_MAP["variance"],
}
_DEFAULT_AGGREGATION = "SUM"


def _find_formula(model: dict, formula_id: str) -> dict | None:
    for f in model.get("formulas", []):
        if f.get("id") == formula_id:
            return f
    return None


def _formula_expr(col: dict, model: dict | None) -> str:
    """Resolve a formula-backed column's ThoughtSpot expr text.

    `model` is required here (unlike col_resolver/ref_resolver) because a
    Model TML column only ever carries a `formula_id` pointer — the `expr`
    text itself lives in the model's separate top-level `formulas[]` list
    (agents/shared/schemas/thoughtspot-model-tml.md). Physical (column_id)
    columns never reach this path, so callers emitting only physical columns
    can leave model as None.
    """
    formula_id = col.get("formula_id")
    if not formula_id:
        raise UntranslatableError(f"column {col.get('name')!r} has no formula_id")
    if model is None:
        raise UntranslatableError(
            f"formula-backed column {col.get('name')!r} needs 'model' to resolve "
            f"formula_id {formula_id!r}")
    formula = _find_formula(model, formula_id)
    if formula is None:
        raise UntranslatableError(f"formula_id {formula_id!r} not found in model formulas")
    return formula["expr"]


def _child_nodes(node: dict):
    """Yield every direct child AST node of `node` (mirrors resolve_refs's own
    walk shape) — factored out so _contains_call stays a simple recursion
    over "does any child match" rather than a flat wall of nested ifs.
    """
    for key in ("left", "right", "operand", "else"):
        if isinstance(node.get(key), dict):
            yield node[key]
    for key in ("args", "cols"):
        for item in node.get(key) or []:
            yield item
    for cond, val in node.get("branches") or []:
        yield cond
        yield val


def _contains_call(node: dict, fn_names: set) -> bool:
    """Walk a formula AST looking for any nested {'node':'call'} with fn in fn_names."""
    if not isinstance(node, dict):
        return False
    if node.get("node") == "call" and node.get("fn") in fn_names:
        return True
    return any(_contains_call(child, fn_names) for child in _child_nodes(node))


def _is_boolean_top(node: dict) -> bool:
    """True if node's own top-level shape is a boolean/comparison expression."""
    kind = node.get("node")
    if kind == "binop":
        return node["op"] in _COMPARISON_OPS or node["op"] in ("and", "or")
    if kind == "unop":
        return node.get("op") == "not"
    if kind == "call":
        return node.get("fn") in ("in", "between")
    return False


def _window_role_reason(fn: str | None, ast: dict) -> str | None:
    """Return the routing reason if `ast` is a window construct (LOD dimension,
    window measure, or period-offset conditional aggregate), else None.
    """
    if fn in _LOD_FNS:
        return f"LOD formula ({fn}) -> dimension window (Task 9)"
    if fn in _WINDOW_MEASURE_FNS:
        return f"window-measure formula ({fn}) (Task 9)"
    if fn in _IF_FAMILY_FNS and ast["args"] and _contains_call(ast["args"][0], _PERIOD_OFFSET_FNS):
        return f"period-offset conditional aggregate ({fn}) (Task 9)"
    return None


def _is_filter_formula(col: dict, column_type: str | None, ast: dict) -> bool:
    """A formula-backed ATTRIBUTE column is a row filter when its own
    top-level shape is boolean/comparison, or its name reads as a filter
    (per ts-to-databricks-rules.md "Filter Generation" > Detection).
    """
    if column_type != "ATTRIBUTE":
        return False
    name_says_filter = "filter" in (col.get("name") or "").lower()
    return _is_boolean_top(ast) or name_says_filter


def classify_column(col: dict, model: dict) -> dict:
    """Route a Model TML column to dimension/measure/filter/window.

    Returns {"role": "dimension"|"measure"|"filter"|"window", "reason": str}.
    Window routing (LOD dimensions; moving/cumulative/semi-additive/
    period-offset measures) is classified here but emitted in Task 9.
    """
    props = col.get("properties") or {}
    column_type = props.get("column_type")
    formula_id = col.get("formula_id")

    if column_type == "UNKNOWN":
        # Applies to BOTH physical and formula-backed columns -- a formula
        # whose own column_type is UNKNOWN previously fell through to the
        # final `dimension` branch below with a misleading "ATTRIBUTE" reason
        # (column_type is UNKNOWN, not ATTRIBUTE). Checked before the
        # formula_id branch so a formula-backed UNKNOWN column is omitted
        # without even attempting to parse its expr.
        kind = "formula-backed" if formula_id else "physical"
        return {"role": "unknown",
                "reason": f"{kind} column with column_type UNKNOWN — cannot classify "
                          "(ts-to-databricks-rules.md 'Unmapped ThoughtSpot Properties')"}

    if not formula_id:
        if column_type == "MEASURE":
            return {"role": "measure", "reason": "physical column with column_type MEASURE"}
        return {"role": "dimension", "reason": "physical column (non-MEASURE column_type)"}

    ast = parse_formula(_formula_expr(col, model))
    fn = ast.get("fn") if ast.get("node") == "call" else None

    window_reason = _window_role_reason(fn, ast)
    if window_reason is not None:
        return {"role": "window", "reason": window_reason}

    if _is_filter_formula(col, column_type, ast):
        return {"role": "filter", "reason": "boolean ATTRIBUTE formula classified as a row filter"}

    if column_type == "MEASURE":
        return {"role": "measure", "reason": "formula-backed MEASURE column (non-window)"}
    return {"role": "dimension", "reason": "formula-backed ATTRIBUTE column (non-window, non-filter)"}


def _physical_measure_expr(dot_path: str, aggregation: str | None) -> str:
    agg = (aggregation or _DEFAULT_AGGREGATION).upper()
    if agg == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {dot_path})"
    dbx_agg = _PROP_AGG_TO_DBX.get(agg)
    if dbx_agg is None:
        raise UntranslatableError(f"unknown aggregation {aggregation!r} on physical measure")
    return f"{dbx_agg}({dot_path})"


def _build_metadata(col: dict) -> dict:
    """Map properties.description/synonyms/currency_type to comment/synonyms/format,
    per ts-to-databricks-rules.md "v1.1 Column Metadata Mapping" /
    "Unmapped ThoughtSpot Properties". Keys are only included when present.
    """
    props = col.get("properties") or {}
    meta: dict = {}
    comment = props.get("description")
    if comment:
        meta["comment"] = comment
    synonyms = props.get("synonyms")
    if synonyms:
        meta["synonyms"] = synonyms
    currency = props.get("currency_type") or {}
    iso_code = currency.get("iso_code") if isinstance(currency, dict) else None
    if iso_code:
        meta["format"] = {"type": "currency", "currency_code": iso_code}
    return meta


def _finalize_column(col: dict, expr: str) -> dict:
    """Assemble the MV dimension/measure fragment with a stable key order:
    name, expr, display_name, comment, synonyms, format (the last three
    only when present).
    """
    display = col.get("name")
    result: dict = {"name": to_snake(display), "expr": expr, "display_name": display}
    meta = _build_metadata(col)
    for key in ("comment", "synonyms", "format"):
        if key in meta:
            result[key] = meta[key]
    return result


def _raise_unresolved_ref(node: dict) -> str:
    raise UntranslatableError(
        f"unresolved reference [{node['name']}]; no ref_resolver provided "
        "(role-aware MEASURE()/ANY_VALUE() resolution is wired in Task 10)")


def _physical_dot_path(col: dict, col_resolver: Callable[[dict], str]) -> str:
    table, column = col["column_id"].split("::", 1)
    return col_resolver({"node": "col", "table": table, "column": column})


def _formula_sql(col: dict, col_resolver: Callable[[dict], str],
                  ref_resolver: Callable[[dict], str], model: dict | None) -> str:
    ast = resolve_refs(parse_formula(_formula_expr(col, model)), ref_resolver)
    return emit_sql(ast, col_resolver)


def emit_dimension(col: dict, col_resolver: Callable[[dict], str],
                    ref_resolver: Callable[[dict], str] | None = None,
                    model: dict | None = None) -> dict:
    """Emit a non-window dimension fragment: bare dot-path for a physical
    column, translated SQL for a formula-backed (ATTRIBUTE) column.
    """
    ref_resolver = ref_resolver or _raise_unresolved_ref
    if col.get("column_id"):
        expr = _physical_dot_path(col, col_resolver)
    else:
        expr = _formula_sql(col, col_resolver, ref_resolver, model)
    return _finalize_column(col, expr)


def emit_measure(col: dict, col_resolver: Callable[[dict], str],
                  ref_resolver: Callable[[dict], str] | None = None,
                  model: dict | None = None) -> dict:
    """Emit a non-window measure fragment: AGG(dot-path) for a physical
    column (using properties.aggregation, default SUM; COUNT_DISTINCT ->
    COUNT(DISTINCT ...)); formula SQL wrapped in its own AGG if absent (Finding 1).
    """
    ref_resolver = ref_resolver or _raise_unresolved_ref
    if col.get("column_id"):
        dot_path = _physical_dot_path(col, col_resolver)
        props = col.get("properties") or {}
        expr = _physical_measure_expr(dot_path, props.get("aggregation"))
    else:
        expr = _formula_sql(col, col_resolver, ref_resolver, model)
        expr = wrap_measure_if_needed(expr, (col.get("properties") or {}).get("aggregation"))
    return _finalize_column(col, expr)


def emit_filter(col: dict, col_resolver: Callable[[dict], str],
                ref_resolver: Callable[[dict], str] | None = None,
                model: dict | None = None) -> str:
    """Emit the Databricks-SQL boolean string for the MV top-level `filter:` field."""
    ref_resolver = ref_resolver or _raise_unresolved_ref
    return _formula_sql(col, col_resolver, ref_resolver, model)


# --- LOD dimension emission (Task 9) --------------------------------------
# group_aggregate/group_sum/group_count/group_average/group_max/group_min/
# group_unique_count -> a DIMENSION whose expr is `AGG(...) OVER (PARTITION BY ...)`.
# Per ts-databricks-formula-translation.md "Level of Detail (LOD) Functions":
# LOD results are dimensions, never measures; never use `window:` for LOD (it
# requires `semiadditive`, which an LOD dimension doesn't carry).

# group_aggregate's first arg is already an aggregate call (e.g. sum(x)); the
# group_sum/group_count/group_average/group_max/group_min two-arg forms carry
# a bare column and imply the aggregate from the function name itself.
# group_unique_count needs COUNT(DISTINCT ...), handled specially below (no
# single-word AGG_MAP entry for it, mirroring emit_sql's "unique count").
_LOD_GROUP_AGG_FNS = {
    "group_sum": "sum", "group_count": "count", "group_average": "average",
    "group_max": "max", "group_min": "min",
}
_LOD_TWO_ARG_FNS = set(_LOD_GROUP_AGG_FNS) | {"group_unique_count"}


def _lod_partition_cols(cols: list[dict], col_resolver: Callable[[dict], str]) -> list[str]:
    resolved = []
    for c in cols:
        if c.get("node") != "col":
            raise UntranslatableError(
                "LOD partition column must be a direct [TABLE::COL] reference")
        resolved.append(col_resolver(c))
    return resolved


def _lod_group_aggregate_parts(args: list[dict], col_resolver, ref_resolver) -> tuple[str, list[dict]]:
    if len(args) != 3:
        raise UntranslatableError(f"group_aggregate expects 3 arguments, got {len(args)}")
    inner_agg, lodset, filt = args
    if lodset.get("node") != "lodset":
        raise UntranslatableError("group_aggregate's second argument must be a {..} LOD set")
    if filt.get("node") == "call" and filt.get("fn") == "query_groups":
        raise UntranslatableError(
            "group_aggregate with query_groups() cannot be expressed as a dimension "
            "window function (see Untranslatable Patterns)")
    agg_expr = emit_sql(resolve_refs(inner_agg, ref_resolver), col_resolver)
    return agg_expr, lodset["cols"]


def _lod_two_arg_parts(fn: str, args: list[dict], col_resolver, ref_resolver) -> tuple[str, list[dict]]:
    if len(args) != 2:
        raise UntranslatableError(f"{fn} expects 2 arguments, got {len(args)}")
    value_node, dim_node = args
    inner = emit_sql(resolve_refs(value_node, ref_resolver), col_resolver)
    if fn == "group_unique_count":
        agg_expr = f"COUNT(DISTINCT {inner})"
    else:
        agg_expr = f"{AGG_MAP[_LOD_GROUP_AGG_FNS[fn]]}({inner})"
    return agg_expr, [dim_node]


def emit_lod_dimension(col: dict, col_resolver: Callable[[dict], str],
                        ref_resolver: Callable[[dict], str] | None = None,
                        model: dict | None = None) -> dict:
    """Emit an LOD formula (group_aggregate/group_sum/group_count/group_average/
    group_max/group_min/group_unique_count) as a dimension window-function
    fragment: `AGG(...) OVER (PARTITION BY p1[, p2...])`. Metadata (name/
    display_name/comment/synonyms) handled by `_finalize_column`, same as
    `emit_dimension`/`emit_measure` (Task 8).
    """
    ref_resolver = ref_resolver or _raise_unresolved_ref
    ast = parse_formula(_formula_expr(col, model))
    fn = ast.get("fn")
    args = ast.get("args") or []

    if fn == "group_aggregate":
        agg_expr, partition_cols = _lod_group_aggregate_parts(args, col_resolver, ref_resolver)
    elif fn in _LOD_TWO_ARG_FNS:
        agg_expr, partition_cols = _lod_two_arg_parts(fn, args, col_resolver, ref_resolver)
    else:
        raise UntranslatableError(f"{fn!r} is not a supported LOD function")

    partition = _lod_partition_cols(partition_cols, col_resolver)
    expr = f"{agg_expr} OVER (PARTITION BY {', '.join(partition)})"
    return _finalize_column(col, expr)
