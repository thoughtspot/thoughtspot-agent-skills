"""Join assembly for the reverse (ThoughtSpot Model TML -> Databricks Metric
View) emit direction, split out of mv_emit.py under the file-size gate
(tools/validate/check_file_size.py). Walks model_tables[].joins[]
breadth-first from the fact table, emitting nested Metric View join nodes
plus the dot-path each joined table gets -- build_joins is mv_emit.py's
join-assembly entry point, reused unchanged by build_metric_view.

Imports Foundation (to_snake, make_col_resolver) from mv_emit_base.py rather
than from mv_emit.py itself, to avoid a circular import: mv_emit.py's
assembly code imports build_joins from here, so this module cannot import
back from mv_emit.py. mv_emit.py re-exports build_joins so existing
callers/tests keep importing from `ts_cli.databricks.mv_emit` unchanged.

Pure: stdlib only. No I/O here.
"""
from __future__ import annotations
from collections import deque

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql
from ts_cli.databricks.mv_emit_base import to_snake, make_col_resolver


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

    # Index model_tables by node identity (alias for a role-play, else id/name) so a
    # join `with: <alias>` resolves, and track each node's physical table for the
    # table-definition/column lookups (which are keyed by physical name). A reused
    # physical table (role-play) has several node ids sharing one physical name.
    # A join's `with:` may reference the target by its alias (role-play models) or by
    # its physical name (single-alias renames), so index by both — the alias key wins,
    # the physical name is a setdefault fallback (ambiguous across role-plays, but only
    # consulted when `with` names the physical table, which a role-play never does).
    def _node_id(mt: dict) -> str:
        return mt.get("alias") or mt.get("id") or mt.get("name", "")

    mt_by_id: dict[str, dict] = {}
    phys_by_id: dict[str, str] = {}
    for mt in model.get("model_tables", []):
        nid = _node_id(mt)
        phys = mt.get("name", nid)
        mt_by_id[nid] = mt
        phys_by_id[nid] = phys
        mt_by_id.setdefault(phys, mt)
        phys_by_id.setdefault(phys, phys)

    dot_path_by_table: dict[str, str] = {source_table: "source"}
    alias_by_table: dict[str, str] = {source_table: "source"}
    node_by_table: dict[str, dict] = {}
    mv_joins: list[dict] = []

    queue: deque = deque([source_table])
    seen = {source_table}
    while queue:
        current = queue.popleft()
        mt = mt_by_id.get(current, {})
        for join in mt.get("joins", []):
            target = join.get("with")
            if not target or target in seen:
                continue
            seen.add(target)

            phys = phys_by_id.get(target, target)
            target_table = tbl_by_name.get(phys)
            if target_table is None:
                raise UntranslatableError(f"no table definition found for joined table {target}")

            target_mt = mt_by_id.get(target, {})
            alias = target_mt.get("alias") or to_snake(target)
            alias_by_table[target] = alias
            parent_path = dot_path_by_table[current]
            dot_path_by_table[target] = alias if parent_path == "source" else f"{parent_path}.{alias}"

            on_str = join.get("on")
            if on_str is None:
                if "referencing_join" not in join:
                    raise UntranslatableError(
                        f"join with {target!r} has neither 'on' nor 'referencing_join'")
                on_str = _resolve_referencing_join(
                    join, phys_by_id.get(current, current), target, tbl_by_name)
            # The TS model on-clause references PHYSICAL table names; scope them to the
            # local MV path keyed by physical name. The FROM side (`current`) maps to
            # its own bare alias/`source`; the target's physical maps to THIS join's
            # alias — so a role-play's on-clause (which names the shared physical table)
            # resolves to this instance, not a sibling role-play's.
            on_scope = {
                source_table: "source",
                phys_by_id.get(current, current): alias_by_table.get(current, "source"),
                phys: alias,
            }
            on_sql = _translate_join_on(on_str, source_table, on_scope)

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
