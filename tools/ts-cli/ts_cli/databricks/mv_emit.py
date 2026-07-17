"""ThoughtSpot Model TML -> Databricks Metric View YAML (reverse orchestrator).
Pure: stdlib + (PyYAML only in build_view). No I/O here.
"""
from __future__ import annotations
import re
from collections import deque
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql, AGG_MAP, COND_AGG
from ts_cli.databricks.mv_tml import ts_type_to_dbx


def to_snake(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_").lower()
    return re.sub(r"_+", "_", s) or "col"


def build_column_index(model: dict, tables: list[dict]) -> dict:
    type_by_ref: dict[str, str] = {}
    for t in tables:
        tname = t["table"]["name"]
        for c in t["table"].get("columns", []):
            dt = (c.get("db_column_properties") or {}).get("data_type")
            if dt:
                type_by_ref[f"{tname}::{c['name']}"] = dt
    idx: dict = {}
    for col in model.get("columns", []):
        cid = col.get("column_id")
        if not cid:
            continue
        table, column = cid.split("::", 1)
        ts_type = type_by_ref.get(cid, "VARCHAR")
        try:
            dbx_type = ts_type_to_dbx(ts_type)
        except ValueError:
            dbx_type = "string"
        idx[cid] = {"table": table, "column": column, "dbx_type": dbx_type, "dot_path": None}
    return idx


def make_col_resolver(col_index: dict, source_table: str,
                      dot_path_by_table: dict[str, str] | None = None) -> Callable[[dict], str]:
    dot_path_by_table = dot_path_by_table or {}

    def resolver(node: dict) -> str:
        cid = f"{node['table']}::{node['column']}"
        if cid not in col_index:
            raise UntranslatableError(f"unknown column {cid}")
        prefix = "source" if node["table"] == source_table else dot_path_by_table.get(node["table"])
        if prefix is None:
            raise UntranslatableError(f"no join path for table {node['table']}")
        return f"{prefix}.{node['column']}"
    return resolver


def resolve_refs(node: dict, ref_resolver: Callable[[dict], str]) -> dict:
    """Return a copy of the AST with every {'node':'ref'} replaced by a raw-SQL literal.

    ref_resolver MUST return atomic/self-delimiting SQL (e.g. `MEASURE(x)`/`ANY_VALUE(x)`),
    since the raw-literal substitution is emitted without any added parentheses.
    """
    if node["node"] == "ref":
        return {"node": "lit", "kind": "raw", "value": ref_resolver(node)}
    out = dict(node)
    for key in ("left", "right", "operand", "else"):
        if isinstance(out.get(key), dict):
            out[key] = resolve_refs(out[key], ref_resolver)
    if "args" in out:
        out["args"] = [resolve_refs(a, ref_resolver) for a in out["args"]]
    if "cols" in out:
        out["cols"] = [resolve_refs(c, ref_resolver) for c in out["cols"]]
    if "branches" in out:
        out["branches"] = [[resolve_refs(c, ref_resolver), resolve_refs(v, ref_resolver)]
                           for c, v in out["branches"]]
    return out


def _collect_col_cids(node: dict, out: set) -> None:
    """Walk a formula AST collecting every {'node':'col'} table::column reference."""
    if not isinstance(node, dict):
        return
    if node.get("node") == "col":
        out.add(f"{node['table']}::{node['column']}")
        return
    for key in ("left", "right", "operand", "else"):
        if isinstance(node.get(key), dict):
            _collect_col_cids(node[key], out)
    for key in ("args", "cols"):
        if isinstance(node.get(key), list):
            for item in node[key]:
                _collect_col_cids(item, out)
    if isinstance(node.get("branches"), list):
        for cond, val in node["branches"]:
            _collect_col_cids(cond, out)
            _collect_col_cids(val, out)


def _translate_join_on(on_str: str, source_table: str, alias_by_table: dict[str, str]) -> str:
    """Parse a model join's inline `on` string and emit it as local-scope SQL.

    `[FACT::DIM_ID] = [DIM::ID]` -> `source.DIM_ID = dim.ID`. Per the Metric View
    nested-join spec, a join's `on` clause references only `source` or the
    **immediate parent join's own (single-segment) alias** — never a fully
    dotted nested path — so this resolves against `alias_by_table` (bare
    aliases), not the full `dot_path_by_table` returned to the caller.
    """
    ast = parse_formula(on_str)
    cids: set = set()
    _collect_col_cids(ast, cids)
    join_col_index = {cid: {} for cid in cids}
    resolver = make_col_resolver(join_col_index, source_table, alias_by_table)
    return emit_sql(ast, resolver)


def _resolve_referencing_join(join: dict, source: str, target: str, tbl_by_name: dict) -> str:
    """Resolve a `referencing_join` name against the SOURCE (FK) table's join defs.

    Per the ThoughtSpot Model TML schema (agents/shared/schemas/thoughtspot-model-tml.md
    "Join Scenarios" / Scenario A, and thoughtspot-table-tml.md `joins_with[]` field
    reference), a `referencing_join` names a `joins_with[]` entry defined on the table
    that OWNS the model's `joins[]` array — the source/FK table currently being walked
    — never the join target. Real ThoughtSpot exports (Scenario A) always define the
    join there. Table TMLs store pre-defined joins under `joins_with[]`; defensively
    also check `joins[]` in case of an unusual export shape. Raise UntranslatableError
    naming the join and the source table if it (or its `on` clause) cannot be found.
    """
    ref_name = join.get("referencing_join")
    source_table = tbl_by_name.get(source) or {}
    candidates = list(source_table.get("joins_with") or []) + list(source_table.get("joins") or [])
    for candidate in candidates:
        if candidate.get("name") != ref_name:
            continue
        destination = candidate.get("destination") or {}
        dest_name = destination.get("name")
        if dest_name is not None and dest_name != target:
            continue  # name collision with a different destination — keep looking
        on_str = candidate.get("on")
        if not on_str:
            raise UntranslatableError(f"referencing_join {ref_name!r} has no 'on' clause")
        return on_str
    raise UntranslatableError(f"referencing_join {ref_name!r} not found on source table {source!r}")


def build_joins(model: dict, tables: list[dict], source_table: str) -> tuple[list[dict], dict[str, str]]:
    """Walk model_tables[].joins[] breadth-first from source_table, emitting nested
    Metric View join nodes and the dot-path each joined table gets.

    Per the Metric View spec (agents/shared/schemas/databricks-metric-view.md),
    a nested join is a child entry under its parent join node's own `joins:` list
    (not a flat sibling), and its `on` clause references the parent's bare alias
    (or `source`) — never a fully dotted path. `dot_path_by_table`, by contrast,
    carries the full nested path (e.g. "dim.subdim") for resolving column
    references elsewhere in the model (dimensions/measures).

    Returns (mv_joins, dot_path_by_table): mv_joins is the top-level ordered list
    of MV join node dicts (source-table gets no node — it's the MV's own
    `source`), each possibly carrying a nested `joins:` list of its own children.
    """
    tbl_by_name = {t["table"]["name"]: t["table"] for t in tables}
    mt_by_name = {mt["name"]: mt for mt in model.get("model_tables", [])}

    dot_path_by_table: dict[str, str] = {source_table: "source"}
    alias_by_table: dict[str, str] = {source_table: "source"}
    node_by_table: dict[str, dict] = {}
    mv_joins: list[dict] = []

    queue: deque = deque([source_table])
    seen = {source_table}
    while queue:
        current = queue.popleft()
        mt = mt_by_name.get(current, {})
        for join in mt.get("joins", []):
            target = join.get("with")
            if not target or target in seen:
                continue
            seen.add(target)

            target_table = tbl_by_name.get(target)
            if target_table is None:
                raise UntranslatableError(f"no table definition found for joined table {target}")

            target_mt = mt_by_name.get(target, {})
            alias = target_mt.get("alias") or to_snake(target)
            alias_by_table[target] = alias
            parent_path = dot_path_by_table[current]
            dot_path_by_table[target] = alias if parent_path == "source" else f"{parent_path}.{alias}"

            on_str = join.get("on")
            if on_str is None:
                if "referencing_join" not in join:
                    raise UntranslatableError(
                        f"join with {target!r} has neither 'on' nor 'referencing_join'")
                on_str = _resolve_referencing_join(join, current, target, tbl_by_name)
            on_sql = _translate_join_on(on_str, source_table, alias_by_table)

            join_node = {
                "name": alias,
                "source": f"{target_table.get('db')}.{target_table.get('schema')}.{target_table.get('db_table')}",
                "on": on_sql,
                "rely": {"at_most_one_match": True},
            }
            if join.get("cardinality") == "MANY_TO_ONE":
                join_node["cardinality"] = "many_to_one"

            node_by_table[target] = join_node
            if current == source_table:
                mv_joins.append(join_node)
            else:
                node_by_table[current].setdefault("joins", []).append(join_node)

            queue.append(target)

    return mv_joins, dot_path_by_table


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
    COUNT(DISTINCT ...)), translated SQL for a formula-backed measure.
    """
    ref_resolver = ref_resolver or _raise_unresolved_ref
    if col.get("column_id"):
        dot_path = _physical_dot_path(col, col_resolver)
        props = col.get("properties") or {}
        expr = _physical_measure_expr(dot_path, props.get("aggregation"))
    else:
        expr = _formula_sql(col, col_resolver, ref_resolver, model)
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


# --- Window measure emission (Task 9) -------------------------------------
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
