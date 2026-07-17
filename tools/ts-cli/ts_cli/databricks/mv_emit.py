"""ThoughtSpot Model TML -> Databricks Metric View YAML (reverse orchestrator).
Pure: stdlib + (PyYAML only in build_view). No I/O here.
"""
from __future__ import annotations
import re
from collections import deque
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql, AGG_MAP
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

_LOD_FNS = {"group_aggregate", "group_sum", "group_count", "group_average"}
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
