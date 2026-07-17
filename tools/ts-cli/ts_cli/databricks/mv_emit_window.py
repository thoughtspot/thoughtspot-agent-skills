"""Window-measure emission (Task 9's rolling/cumulative/semi-additive/
period-offset measures), split out of mv_emit.py under the file-size gate
(tools/validate/check_file_size.py, CAP 1000 lines) when Task 10's assembly
code pushed mv_emit.py past the cap. Mirrors the mv_translate.py /
mv_window_translate.py split for the reverse (from-databricks) direction:
mv_emit.py does a normal top-level import of this module's public API
(re-exported for callers/tests); this module late-imports mv_emit's
resolve_refs/to_snake/_formula_expr/_finalize_column/_raise_unresolved_ref/
_IF_FAMILY_FNS inside the function that needs each, to avoid a circular
top-level import.

Pure: stdlib only. No I/O here.
"""
from __future__ import annotations
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql, AGG_MAP, COND_AGG

# moving_sum/moving_average (4-arg trailing/leading shapes), cumulative_sum/
# cumulative_average, last_value/first_value (true semi-additive), and
# *_if(diff_months|diff_quarters(...) = N, [m]) (period-offset) all become a
# MEASURE carrying a `window: [...]` block. `semiadditive` is always present
# (Metric View requirement -- omitting it fails with "Missing required
# creator property 'semiadditive'", per the mapping doc's Key rules).

_MOVING_FNS = {"moving_sum": "SUM", "moving_average": "AVG"}
_CUMULATIVE_FNS = {"cumulative_sum": "SUM", "cumulative_average": "AVG"}
# diff_months(...)=N -> N month-units of offset; diff_quarters(...)=N -> N
# quarter-units, each worth 3 offset-months (ts-databricks-formula-translation.md
# Semi-Additive/Period Filter section; Task 9 brief embeds this verbatim).
# diff_years is not in the brief's mapping table -- left unmapped (raises
# UntranslatableError below) rather than guessed at.
_PERIOD_OFFSET_GRAIN = {"diff_months": ("month", 1), "diff_quarters": ("month", 3)}


def _extract_int(node: dict) -> int:
    """Read an integer literal, allowing a unary-minus-wrapped literal (how the
    parser represents e.g. `-1` -- see mv_emit_expr._parse_unary)."""
    if node.get("node") == "lit" and node.get("kind") == "number":
        return int(node["value"])
    if node.get("node") == "unop" and node.get("op") == "-":
        return -_extract_int(node["operand"])
    raise UntranslatableError("expected an integer literal in a window function argument")


def _moving_range(start_val: int, end_val: int) -> str:
    """Classify a moving_sum/moving_average (start, end) row-offset pair into
    one of the four live-verified range shapes (ts-databricks-formula-translation.md
    "Rolling Window Functions" / "Leading Window"). Any other pair -- including a
    pair that matches a shape's anchor but derives a non-positive day count N
    (e.g. (-1, -1), (-2, -1), (-5, 0), (-1, -5), (0, -5)) -- is a manual-review
    case -- raise rather than emit a guessed range that would fail cryptically
    as invalid MV YAML at DDL time.
    """
    if end_val == -1:
        n, label = start_val, f"trailing {start_val} day"
    elif end_val == 0:
        n, label = start_val + 1, f"trailing {start_val + 1} day inclusive"
    elif start_val == -1:
        n, label = end_val, f"leading {end_val} day"
    elif start_val == 0:
        n, label = end_val + 1, f"leading {end_val + 1} day inclusive"
    else:
        raise UntranslatableError(
            f"moving_sum/moving_average start={start_val} end={end_val} does not match "
            "a known trailing/leading shape (manual review)")
    if n < 1:
        raise UntranslatableError(
            f"moving_sum/moving_average start={start_val} end={end_val} derives a "
            f"non-positive day count (N={n}) -- not a valid trailing/leading window "
            "shape (manual review)")
    return label


def _match_dim(expr: str, existing_dims: list[dict]) -> str | None:
    for d in existing_dims:
        if d.get("expr") == expr:
            return d["name"]
    return None


def _find_join_predicate_alias(model: dict | None, target_table: str, target_column: str):
    """If `model.model_tables[].joins[]` has an INLINE `on:` join naming
    target_table as its `with`, and that `on` equates target_table::target_column
    to a column on the other side of the join, return (other_table, other_column).

    Only inline `on:` is resolvable here -- a `referencing_join`-only join's
    condition lives in Table TML `joins_with[]`, which isn't part of this
    function's inputs (documented limitation -- see Task 9 report).
    """
    if model is None:
        return None
    for mt in model.get("model_tables", []):
        for join in mt.get("joins", []):
            if join.get("with") != target_table:
                continue
            on_str = join.get("on")
            if not on_str:
                continue
            try:
                ast = parse_formula(on_str)
            except UntranslatableError:
                continue
            if ast.get("node") != "binop" or ast.get("op") != "=":
                continue
            left, right = ast["left"], ast["right"]
            if left.get("node") != "col" or right.get("node") != "col":
                continue
            for a, b in ((left, right), (right, left)):
                if a["table"] == target_table and a["column"] == target_column:
                    return b["table"], b["column"]
    return None


def _raw_date_dim(date_node: dict, col_resolver: Callable[[dict], str], existing_dims: list[dict],
                   model: dict | None = None) -> tuple[str, list[dict]]:
    """Resolve a raw (non-truncated) date column reference used as a window
    `order:` to a dimension NAME -- reusing an existing dimension with a
    matching `expr`, else falling back through the column's join-predicate
    alias (see `_find_join_predicate_alias`), else synthesizing a brand-new
    plain dot-path dimension (returned as the sole entry of `extra_dims`).
    """
    from ts_cli.databricks.mv_emit import to_snake

    if date_node.get("node") != "col":
        raise UntranslatableError("window order column must be a direct [TABLE::COL] reference")
    dot_path = col_resolver(date_node)
    match = _match_dim(dot_path, existing_dims)
    if match is not None:
        return match, []

    alias = _find_join_predicate_alias(model, date_node["table"], date_node["column"])
    if alias is not None:
        alias_dot = col_resolver({"node": "col", "table": alias[0], "column": alias[1]})
        alias_match = _match_dim(alias_dot, existing_dims)
        if alias_match is not None:
            return alias_match, []

    name = to_snake(f"{date_node['table']}_{date_node['column']}")
    display = date_node["column"].replace("_", " ").title()
    new_dim = {"name": name, "expr": dot_path, "display_name": display}
    return name, [new_dim]


def synthesize_period_dim(date_col_node: dict, grain: str,
                           col_resolver: Callable[[dict], str]) -> dict:
    """Build a truncated-period dimension (e.g. `DATE_TRUNC('MONTH', ...)`) for
    a period-offset window measure's `order:`. Returned as a plain dict -- the
    caller (`_period_dim` here, or build_metric_view in Task 10) is responsible
    for adding it to the MV's dimensions[] only if an equivalent one doesn't
    already exist.
    """
    from ts_cli.databricks.mv_emit import to_snake

    dot_path = col_resolver(date_col_node)
    name = to_snake(f"{grain}_{date_col_node['column']}")
    display = f"{grain.title()} ({date_col_node['column'].replace('_', ' ').title()})"
    return {"name": name, "expr": f"DATE_TRUNC('{grain.upper()}', {dot_path})", "display_name": display}


def _period_dim(date_node: dict, grain: str, col_resolver: Callable[[dict], str],
                 existing_dims: list[dict]) -> tuple[str, list[dict]]:
    synthesized = synthesize_period_dim(date_node, grain, col_resolver)
    match = _match_dim(synthesized["expr"], existing_dims)
    if match is not None:
        return match, []
    return synthesized["name"], [synthesized]


def _emit_moving_window(fn: str, args: list[dict], col_resolver, ref_resolver,
                         existing_dims: list[dict], model: dict | None) -> tuple[str, dict, list[dict]]:
    from ts_cli.databricks.mv_emit import resolve_refs

    if len(args) != 4:
        raise UntranslatableError(
            f"{fn} expects 4 arguments (measure, start, end, sort_col), got {len(args)}")
    measure_node, start_node, end_node, sort_node = args
    range_str = _moving_range(_extract_int(start_node), _extract_int(end_node))
    inner = emit_sql(resolve_refs(measure_node, ref_resolver), col_resolver)
    measure_expr = f"{_MOVING_FNS[fn]}({inner})"
    order_name, extra = _raw_date_dim(sort_node, col_resolver, existing_dims, model)
    window = {"order": order_name, "range": range_str, "semiadditive": "last"}
    return measure_expr, window, extra


def _emit_cumulative_window(fn: str, args: list[dict], col_resolver, ref_resolver,
                             existing_dims: list[dict], model: dict | None) -> tuple[str, dict, list[dict]]:
    from ts_cli.databricks.mv_emit import resolve_refs

    if len(args) != 2:
        raise UntranslatableError(
            f"{fn} expects 2 arguments (measure, sort_col), got {len(args)}")
    measure_node, sort_node = args
    inner = emit_sql(resolve_refs(measure_node, ref_resolver), col_resolver)
    measure_expr = f"{_CUMULATIVE_FNS[fn]}({inner})"
    order_name, extra = _raw_date_dim(sort_node, col_resolver, existing_dims, model)
    window = {"order": order_name, "range": "cumulative", "semiadditive": "last"}
    return measure_expr, window, extra


def _emit_semiadditive_window(fn: str, args: list[dict], col_resolver, ref_resolver,
                               existing_dims: list[dict],
                               model: dict | None) -> tuple[str, dict, list[dict]]:
    from ts_cli.databricks.mv_emit import resolve_refs

    if len(args) != 3:
        raise UntranslatableError(
            f"{fn} expects 3 arguments (agg, query_groups(), {{date}}), got {len(args)}")
    inner_agg, groups_node, dateset_node = args
    if not (groups_node.get("node") == "call" and groups_node.get("fn") == "query_groups"):
        raise UntranslatableError(f"{fn}'s second argument must be query_groups()")
    if dateset_node.get("node") != "lodset" or len(dateset_node.get("cols") or []) != 1:
        raise UntranslatableError(f"{fn}'s third argument must be a single-column {{[date]}} set")
    date_node = dateset_node["cols"][0]
    measure_expr = emit_sql(resolve_refs(inner_agg, ref_resolver), col_resolver)
    order_name, extra = _raw_date_dim(date_node, col_resolver, existing_dims, model)
    semi = "last" if fn == "last_value" else "first"
    window = {"order": order_name, "semiadditive": semi, "range": "current"}
    return measure_expr, window, extra


def _period_offset_condition_parts(cond_node: dict) -> tuple[dict, dict, int]:
    """Validate + unpack a period-offset condition: `diff_months|diff_quarters
    ([date], today()) = N`. Returns (diff_call_node, date_node, N)."""
    if cond_node.get("node") != "binop" or cond_node.get("op") != "=":
        raise UntranslatableError(
            "period-offset condition must be diff_months/diff_quarters(...) = N")
    diff_call, n_node = cond_node["left"], cond_node["right"]
    if diff_call.get("node") != "call" or diff_call.get("fn") not in _PERIOD_OFFSET_GRAIN:
        raise UntranslatableError(
            "period-offset condition's left side must be diff_months(...)/diff_quarters(...)")
    diff_args = diff_call.get("args") or []
    if len(diff_args) != 2:
        raise UntranslatableError(f"{diff_call['fn']} expects 2 arguments (date, today())")
    date_node, today_node = diff_args
    if today_node.get("node") != "call" or today_node.get("fn") != "today":
        raise UntranslatableError(f"{diff_call['fn']}'s second argument must be today()")
    return diff_call, date_node, _extract_int(n_node)


def _period_offset_value(n_val: int, month_units_per_period: int) -> str | None:
    if n_val == 0:
        return None
    offset_months = n_val * month_units_per_period
    if offset_months != 0 and offset_months % 12 == 0:
        return f"{offset_months // 12} year"
    return f"{offset_months} month"


def _emit_period_offset_window(fn: str, args: list[dict], col_resolver, ref_resolver,
                                existing_dims: list[dict]) -> tuple[str, dict, list[dict]]:
    from ts_cli.databricks.mv_emit import resolve_refs

    if len(args) != 2:
        raise UntranslatableError(f"{fn} expects 2 arguments (condition, measure), got {len(args)}")
    cond_node, measure_node = args
    diff_call, date_node, n_val = _period_offset_condition_parts(cond_node)
    grain, month_units_per_period = _PERIOD_OFFSET_GRAIN[diff_call["fn"]]

    order_name, extra = _period_dim(date_node, grain, col_resolver, existing_dims)

    agg, distinct = COND_AGG[fn]
    inner = emit_sql(resolve_refs(measure_node, ref_resolver), col_resolver)
    measure_expr = f"{agg}(DISTINCT {inner})" if distinct else f"{agg}({inner})"

    window = {"order": order_name, "range": "current", "semiadditive": "last"}
    offset = _period_offset_value(n_val, month_units_per_period)
    if offset is not None:
        window["offset"] = offset
    return measure_expr, window, extra


def emit_window_measure(col: dict, col_resolver: Callable[[dict], str],
                         ref_resolver: Callable[[dict], str] | None = None,
                         model: dict | None = None,
                         existing_dims: list[dict] | None = None) -> tuple[dict, list[dict]]:
    """Emit a window-measure formula (moving_sum/moving_average, cumulative_sum/
    cumulative_average, last_value/first_value, or a period-offset *_if) as a
    measure dict carrying a `window: [...]` block, plus any newly-synthesized
    dimension(s) the window's `order:` needed (empty when reused/not needed).
    """
    from ts_cli.databricks.mv_emit import (
        _formula_expr, _finalize_column, _raise_unresolved_ref, _IF_FAMILY_FNS)

    ref_resolver = ref_resolver or _raise_unresolved_ref
    existing_dims = existing_dims if existing_dims is not None else []
    ast = parse_formula(_formula_expr(col, model))
    fn = ast.get("fn")
    args = ast.get("args") or []

    if fn in _MOVING_FNS:
        measure_expr, window, extra_dims = _emit_moving_window(
            fn, args, col_resolver, ref_resolver, existing_dims, model)
    elif fn in _CUMULATIVE_FNS:
        measure_expr, window, extra_dims = _emit_cumulative_window(
            fn, args, col_resolver, ref_resolver, existing_dims, model)
    elif fn in ("last_value", "first_value"):
        measure_expr, window, extra_dims = _emit_semiadditive_window(
            fn, args, col_resolver, ref_resolver, existing_dims, model)
    elif fn in _IF_FAMILY_FNS:
        measure_expr, window, extra_dims = _emit_period_offset_window(
            fn, args, col_resolver, ref_resolver, existing_dims)
    else:
        raise UntranslatableError(f"{fn!r} is not a supported window measure function")

    measure = _finalize_column(col, measure_expr)
    measure["window"] = [window]
    return measure, extra_dims


# --- detect_fact_tables helper (Task 13 fix) -------------------------------
# Not window-measure logic -- placed here (rather than mv_emit.py) purely to
# stay under mv_emit.py's file-size cap; mv_emit.py imports it alongside this
# module's other re-exports.

def _join_target_tables(model: dict) -> set:
    """Every table named as a `with` value across every `model_tables[].joins[]`
    entry -- i.e. every table that is a JOIN TARGET (a dimension joined TO),
    never a join root. Used by `mv_emit.detect_fact_tables` to exclude
    dimensions from the fact-table result: a real fact table is never itself
    the target of another table's join.
    """
    targets: set = set()
    for mt in model.get("model_tables", []):
        for join in mt.get("joins", []):
            target = join.get("with")
            if target:
                targets.add(target)
    return targets
