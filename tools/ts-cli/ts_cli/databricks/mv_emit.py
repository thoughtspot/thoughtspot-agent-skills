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
# Window-measure emission (Task 9) lives in mv_emit_window.py -- split out
# under the file-size gate (tools/validate/check_file_size.py). Re-exported
# here so existing callers/tests keep importing from mv_emit; that module
# late-imports the mv_emit internals it needs to avoid a circular import
# (mirrors the mv_translate.py / mv_window_translate.py split).
from ts_cli.databricks.mv_emit_window import (
    emit_window_measure, synthesize_period_dim, _moving_range)


def to_snake(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_").lower()
    return re.sub(r"_+", "_", s) or "col"


def build_column_index(model: dict, tables: list[dict]) -> dict:
    """Index every physical column of every table in `tables` by its
    `TABLE::COLUMN` id.

    Sourced from the physical schema (`tables`), not from `model.get("columns")`
    — real ThoughtSpot Models commonly reference a physical column inside a
    formula (e.g. an LOD partition column, a semi-additive order column, a
    conditional-aggregate's filter column) WITHOUT that column also being its
    own separately-declared model column (see the Dunder Mifflin worked
    example: `DM_INVENTORY::FILLED_INVENTORY`, `DM_EMPLOYEE::LAST_NAME`, and
    `DM_ORDER::EMPLOYEE_ID` are all formula-only references, never their own
    `columns[]` entry). Indexing from `tables` makes every such reference
    resolvable; `model` is kept as a parameter for interface stability but is
    no longer consulted here.
    """
    idx: dict = {}
    for t in tables:
        tname = t["table"]["name"]
        for c in t["table"].get("columns", []):
            ts_type = (c.get("db_column_properties") or {}).get("data_type") or "VARCHAR"
            try:
                dbx_type = ts_type_to_dbx(ts_type)
            except ValueError:
                dbx_type = "string"
            idx[f"{tname}::{c['name']}"] = {
                "table": tname, "column": c["name"], "dbx_type": dbx_type, "dot_path": None}
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
        if column_type == "UNKNOWN":
            return {"role": "unknown",
                    "reason": "physical column with column_type UNKNOWN — cannot classify "
                              "(ts-to-databricks-rules.md 'Unmapped ThoughtSpot Properties')"}
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


# --- Task 10: fact-table detection + cross-reference resolver + -----------
# build_metric_view assembly. Wires Tasks 6-9 into one MV yaml_doc for a
# single fact table (the multi-fact split loops over detect_fact_tables'
# result, calling build_metric_view once per fact).

def _first_col_ref_table(node) -> str | None:
    """DFS a formula AST for the first {'node':'col'} reference's table,
    walking children in the same order as `_child_nodes` (mirrors how a
    ThoughtSpot formula reads left-to-right). Returns None if the AST has no
    direct physical column reference (e.g. it only chains through other
    formulas via [ref] nodes).
    """
    if not isinstance(node, dict):
        return None
    if node.get("node") == "col":
        return node["table"]
    for child in _child_nodes(node):
        table = _first_col_ref_table(child)
        if table is not None:
            return table
    return None


def _measure_column_table(col: dict, model: dict) -> str | None:
    """A MEASURE column's owning table: its own column_id prefix if physical,
    else the table its formula's first physical [T::col] ref resolves to
    (per the Task 10 brief's 'primary/first' rule). Returns None if neither
    is available (e.g. an untranslatable or all-cross-reference formula) --
    such a column simply contributes no table to detect_fact_tables.
    """
    cid = col.get("column_id")
    if cid:
        return cid.split("::", 1)[0]
    formula_id = col.get("formula_id")
    if not formula_id:
        return None
    formula = _find_formula(model, formula_id)
    if formula is None:
        return None
    try:
        ast = parse_formula(formula["expr"])
    except UntranslatableError:
        return None
    return _first_col_ref_table(ast)


def detect_fact_tables(model: dict) -> list[str]:
    """Tables carrying >= 1 MEASURE column, in `model_tables` order.

    A physical column's table is its `column_id` prefix; a formula column's
    table is the table its first physical `[T::col]` ref resolves to. Used by
    the multi-fact split: the command calls this once, then calls
    `build_metric_view` once per returned table as `source_table`.
    """
    table_order = [mt["name"] for mt in model.get("model_tables", [])]
    found: list[str] = []
    for col in model.get("columns", []):
        props = col.get("properties") or {}
        if props.get("column_type") != "MEASURE":
            continue
        table = _measure_column_table(col, model)
        if table and table not in found:
            found.append(table)
    ordered = [t for t in table_order if t in found]
    ordered += [t for t in found if t not in table_order]
    return ordered


# `formula_roles` (despite the name, kept for interface stability per the
# Task 10 brief) actually maps ANY emitted column's display name -> its final
# MV role, not just formula-backed ones -- a ThoughtSpot [ref] can point at a
# physical MEASURE column just as easily as a formula (see the worked
# example's `safe_divide([Quantity], [Category Quantity])`, where `Quantity`
# is a physical column). Only two target roles are supported, matching the
# brief's stated scope: "measure" -> MEASURE(x), "lod_dimension" -> ANY_VALUE(y).
# A plain (non-LOD) dimension is not yet a valid ref target here -- omitted
# from the map, so referencing one raises UntranslatableError (fail loud
# rather than silently wrong); see the Task 10 report for this scope note.
_REF_ROLE_FN = {"measure": "MEASURE", "lod_dimension": "ANY_VALUE"}


def make_ref_resolver(formula_roles: dict) -> Callable[[dict], str]:
    """Build a ref_resolver for `resolve_refs`/emit_* from this MV's own
    column classification. A ref to a name classified "measure" emits
    `MEASURE(<snake>)`; "lod_dimension" emits `ANY_VALUE(<snake>)`; any other
    (or missing) name raises UntranslatableError.
    """
    def resolver(node: dict) -> str:
        name = node["name"]
        fn = _REF_ROLE_FN.get(formula_roles.get(name))
        if fn is None:
            raise UntranslatableError(
                f"unresolved reference [{name}]: no measure or LOD dimension named "
                f"{name!r} among this Metric View's classified columns")
        return f"{fn}({to_snake(name)})"
    return resolver


def _window_kind(col: dict, model: dict) -> str:
    """"lod" (dimension window function) or "measure" (window: measure) for
    a role=="window" classified column -- classify_column routes both to the
    same "window" role (Task 9), so build_metric_view needs this finer split
    to know whether to emit_lod_dimension or emit_window_measure.
    """
    ast = parse_formula(_formula_expr(col, model))
    fn = ast.get("fn") if ast.get("node") == "call" else None
    return "lod" if fn in _LOD_FNS else "measure"


def _classify_all_columns(model: dict) -> list[tuple[dict, dict]]:
    """Classify every model column, catching classify-time UntranslatableError
    (bad/unparseable formula) as a role=="error" entry rather than aborting --
    per-formula errors must not abort the whole MV.
    """
    classified: list[tuple[dict, dict]] = []
    for col in model.get("columns", []):
        try:
            result = classify_column(col, model)
            if result["role"] == "window":
                result = dict(result)
                result["window_kind"] = _window_kind(col, model)
        except UntranslatableError as exc:
            result = {"role": "error", "reason": str(exc)}
        classified.append((col, result))
    return classified


def _build_ref_roles(classified: list[tuple[dict, dict]]) -> dict:
    """Build the name -> role map `make_ref_resolver` needs, from every
    column's FINAL routed kind (not just formula columns -- see the
    `_REF_ROLE_FN` docstring above): "measure" for a plain or window measure,
    "lod_dimension" for an LOD-formula dimension. Must be built from ALL
    classified columns before any expr is emitted, so a formula can forward-
    or back-reference any other column in this MV.
    """
    roles: dict = {}
    for col, result in classified:
        name = col.get("name")
        role = result.get("role")
        if role == "measure" or (role == "window" and result.get("window_kind") == "measure"):
            roles[name] = "measure"
        elif role == "window" and result.get("window_kind") == "lod":
            roles[name] = "lod_dimension"
    return roles


def _record_skip(skipped: list, warnings: list, name, role: str, reason: str) -> None:
    """Record a per-formula/per-column omission uniformly: every skip gets
    BOTH a structured skipped[] entry and a human-readable warning (required
    follow-up: "every skipped column" must surface in warnings for the
    SKILL's checkpoint).
    """
    skipped.append({"name": name, "role": role, "reason": reason})
    warnings.append(f"skipped {role} column {name!r}: {reason}")


def _route_filter(col: dict, model: dict, col_resolver, ref_resolver,
                   dimensions: list, filter_exprs: list, warnings: list) -> None:
    """Route a role=="filter" classified column. classify_column's filter
    detection accepts EITHER a boolean-shaped expr OR a name containing
    "filter" (ts-to-databricks-rules.md "Filter Generation" > Detection) --
    but only a genuinely boolean expr may land in the MV's `filter:` field
    (required follow-up #1). A name-only match that isn't boolean is
    rerouted to a dimension (always a dimension, never a measure -- filter
    classification only ever fires on ATTRIBUTE columns) instead of being
    silently dropped or wrongly emitted as a global filter. Either path
    surfaces a warning (required follow-up #3) so the SKILL checkpoint can
    ask the user to confirm the routing. Raises UntranslatableError on
    failure -- caller records the skip.
    """
    name = col.get("name")
    ast = parse_formula(_formula_expr(col, model))
    if _is_boolean_top(ast):
        filter_exprs.append(emit_filter(col, col_resolver, ref_resolver, model))
        warnings.append(
            f"formula {name!r} classified as a row filter (boolean) — confirm this is "
            "intended as a global MV filter rather than a dimension")
    else:
        dimensions.append(emit_dimension(col, col_resolver, ref_resolver, model))
        warnings.append(
            f"formula {name!r} name suggests a filter but is not boolean-shaped — "
            "emitted as a dimension instead; confirm this routing")


def _merge_extra_dims(dimensions: list, extra_dims: list) -> None:
    """Append a window measure's synthesized order-dim(s) to `dimensions`,
    deduped by name -- emit_window_measure already prefers reusing a matching
    existing dim over synthesizing a new one (required follow-up #4), so
    `extra_dims` here is only ever genuinely-new dims; this guards against
    re-adding the same synthesized dim twice across multiple window measures.
    """
    existing_names = {d["name"] for d in dimensions}
    for d in extra_dims:
        if d["name"] not in existing_names:
            dimensions.append(d)
            existing_names.add(d["name"])


def _combine_filters(filter_exprs: list) -> str | None:
    """AND-join multiple filter formulas into the MV's single `filter:`
    string, parenthesizing each when there's more than one (so a top-level
    OR inside any individual filter can't leak across the AND join).
    """
    if not filter_exprs:
        return None
    if len(filter_exprs) == 1:
        return filter_exprs[0]
    return " AND ".join(f"({e})" for e in filter_exprs)


def _check_duplicate_display_names(dimensions: list, measures: list) -> None:
    seen: dict = {}
    for coll_name, items in (("dimension", dimensions), ("measure", measures)):
        for item in items:
            dn = item.get("display_name")
            if dn in seen:
                raise ValueError(
                    f"duplicate display_name {dn!r} across emitted columns "
                    f"({seen[dn]} and {coll_name})")
            seen[dn] = coll_name


def _source_db_table(tables: list[dict], source_table: str) -> str:
    for t in tables:
        if t["table"]["name"] == source_table:
            return t["table"]["db_table"]
    raise ValueError(f"source_table {source_table!r} not found in tables")


def _emit_dimensions_pass(classified: list[tuple[dict, dict]], model: dict,
                           col_resolver, ref_resolver,
                           skipped: list, warnings: list) -> tuple[list[dict], list[str]]:
    """Pass 1 of 2: plain dimensions, LOD dimensions, filter routing (which
    may itself append a dimension), and unknown/error omission -- everything
    that does NOT need the full dimensions list up front. Must run to
    completion before the measures pass, since window measures need this
    pass's dims available for order-dim reuse (required follow-up #4).
    """
    dimensions: list = []
    filter_exprs: list = []
    for col, result in classified:
        role = result.get("role")
        name = col.get("name")
        try:
            if role == "dimension":
                dimensions.append(emit_dimension(col, col_resolver, ref_resolver, model))
            elif role == "unknown":
                _record_skip(skipped, warnings, name, role, result.get("reason", ""))
            elif role == "error":
                _record_skip(skipped, warnings, name, role, result.get("reason", ""))
            elif role == "filter":
                _route_filter(col, model, col_resolver, ref_resolver,
                               dimensions, filter_exprs, warnings)
            elif role == "window" and result.get("window_kind") == "lod":
                dimensions.append(emit_lod_dimension(col, col_resolver, ref_resolver, model))
        except UntranslatableError as exc:
            _record_skip(skipped, warnings, name, role, str(exc))
    return dimensions, filter_exprs


def _emit_measures_pass(classified: list[tuple[dict, dict]], model: dict,
                         col_resolver, ref_resolver, dimensions: list,
                         skipped: list, warnings: list) -> list[dict]:
    """Pass 2 of 2: plain measures and window measures, using the fully-built
    `dimensions` list (from the dimensions pass) for order-dim reuse. Grows
    `dimensions` in place as window measures synthesize new order dims, so
    later window measures in this same pass can reuse earlier ones (matches
    the worked example's Monthly/Prior Month Revenue sharing one order_month
    dim).
    """
    measures: list = []
    for col, result in classified:
        role = result.get("role")
        name = col.get("name")
        try:
            if role == "measure":
                measures.append(emit_measure(col, col_resolver, ref_resolver, model))
            elif role == "window" and result.get("window_kind") == "measure":
                measure, extra_dims = emit_window_measure(
                    col, col_resolver, ref_resolver, model, existing_dims=dimensions)
                measures.append(measure)
                _merge_extra_dims(dimensions, extra_dims)
        except UntranslatableError as exc:
            _record_skip(skipped, warnings, name, role, str(exc))
    return measures


def build_metric_view(model: dict, tables: list[dict], source_table: str, *,
                       catalog: str, schema: str) -> dict:
    """Assemble one Databricks Metric View YAML doc for `source_table`,
    orchestrating Tasks 6-9: column index + joins (Task 6/7) -> classify
    every model column (Task 8/9) -> role-aware ref resolver (this task) ->
    route each column to its emitter -> assemble the MV dict in schema key
    order. Returns `{"yaml_doc": dict, "skipped": list[dict], "warnings": list[str]}`.

    A column belonging to a different fact table's join tree (relevant only
    in a multi-fact model) has no resolvable dot-path here and naturally
    lands in `skipped` via its own UntranslatableError -- callers looping
    over `detect_fact_tables` don't need to pre-filter `model["columns"]`.
    """
    skipped: list = []
    warnings: list = []

    col_index = build_column_index(model, tables)
    mv_joins, dot_path_by_table = build_joins(model, tables, source_table)
    col_resolver = make_col_resolver(col_index, source_table, dot_path_by_table)

    classified = _classify_all_columns(model)
    ref_resolver = make_ref_resolver(_build_ref_roles(classified))

    dimensions, filter_exprs = _emit_dimensions_pass(
        classified, model, col_resolver, ref_resolver, skipped, warnings)
    measures = _emit_measures_pass(
        classified, model, col_resolver, ref_resolver, dimensions, skipped, warnings)

    _check_duplicate_display_names(dimensions, measures)

    yaml_doc: dict = {"version": "1.1"}
    comment = model.get("description")
    if comment:
        yaml_doc["comment"] = comment
    yaml_doc["source"] = f"{catalog}.{schema}.{_source_db_table(tables, source_table)}"
    if mv_joins:
        yaml_doc["joins"] = mv_joins
    yaml_doc["dimensions"] = dimensions
    yaml_doc["measures"] = measures
    combined_filter = _combine_filters(filter_exprs)
    if combined_filter:
        yaml_doc["filter"] = combined_filter

    return {"yaml_doc": yaml_doc, "skipped": skipped, "warnings": warnings}
