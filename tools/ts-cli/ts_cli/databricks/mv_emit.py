"""ThoughtSpot Model TML -> Databricks Metric View YAML (reverse orchestrator).
Pure: stdlib + (PyYAML only in build_view). No I/O here.
"""
from __future__ import annotations
import re
from collections import deque
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql
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


def _resolve_referencing_join(join: dict, target: str, tbl_by_name: dict) -> str:
    """Resolve a `referencing_join` name against the target Table TML's join defs.

    Table TMLs store pre-defined joins under `joins_with[]` or `joins[]` depending on
    the export path — check both defensively. Raise UntranslatableError naming the
    join if it (or its `on` clause) cannot be found.
    """
    ref_name = join.get("referencing_join")
    target_table = tbl_by_name.get(target) or {}
    candidates = list(target_table.get("joins_with") or []) + list(target_table.get("joins") or [])
    for candidate in candidates:
        if candidate.get("name") == ref_name:
            on_str = candidate.get("on")
            if not on_str:
                raise UntranslatableError(f"referencing_join {ref_name!r} has no 'on' clause")
            return on_str
    raise UntranslatableError(f"referencing_join {ref_name!r} not found for table {target}")


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
                on_str = _resolve_referencing_join(join, target, tbl_by_name)
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
