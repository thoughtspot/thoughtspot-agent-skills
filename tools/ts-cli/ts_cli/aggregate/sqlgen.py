"""Aggregate SELECT / profiling SQL / DDL emission (pure, no I/O)."""
from __future__ import annotations

import re
from typing import Optional


class UnsupportedModelError(Exception):
    """Model shape sqlgen cannot handle deterministically (skill falls back to manual SQL)."""


_QUOTE = {"snowflake": '"', "databricks": "`", "bigquery": "`"}
# How the quote char is escaped when it appears inside an identifier:
# Snowflake doubles the ", Databricks doubles the `, BigQuery backslash-escapes the `.
_QUOTE_ESCAPE = {"snowflake": '""', "databricks": "``", "bigquery": "\\`"}
_JOIN_COND = re.compile(r"\[([^:\]]+)::([^\]]+)\]")
_JOIN_TYPE = {"INNER": "JOIN", "LEFT_OUTER": "LEFT JOIN",
              "RIGHT_OUTER": "RIGHT JOIN", "OUTER": "FULL JOIN"}
# Traversing a directional edge target->source flips which side is preserved.
_SWAPPED_JOIN = {"LEFT_OUTER": "RIGHT_OUTER", "RIGHT_OUTER": "LEFT_OUTER"}
DATE_TRUNC_FN = {"snowflake": "DATE_TRUNC", "databricks": "DATE_TRUNC", "bigquery": "DATE_TRUNC"}


def _q(dialect: str, ident: str) -> str:
    q = _QUOTE[dialect]
    return f"{q}{ident.replace(q, _QUOTE_ESCAPE[dialect])}{q}"


def _table_doc(table_tmls: dict, table: str) -> dict:
    try:
        return table_tmls[table]
    except KeyError:
        raise UnsupportedModelError(
            f"table '{table}' not resolvable — possibly an aliased "
            f"model_tables entry") from None


def _table_ref(table_tml: dict, dialect: str) -> str:
    t = table_tml["table"]
    return ".".join(_q(dialect, p) for p in (t["db"], t["schema"], t["db_table"]))


def _db_col(table_tmls: dict, table: str, col: str) -> str:
    for c in _table_doc(table_tmls, table)["table"].get("columns", []):
        if c["name"] == col:
            return c.get("db_column_name", col)
    return col


def _col_map(model_tml: dict) -> dict:
    """display name -> (table, physical column name)."""
    out = {}
    for c in model_tml["model"].get("columns", []) or []:
        table, col = c["column_id"].split("::", 1)
        out[c["name"]] = (table, col)
    return out


def _resolve(model_tml, table_tmls, dialect, display_name):
    table, col = _col_map(model_tml)[display_name]
    return f"{_q(dialect, table)}.{_q(dialect, _db_col(table_tmls, table, col))}", table


def _date_trunc(dialect: str, bucket: str, col_sql: str) -> str:
    part = {"HOURLY": "HOUR", "DAILY": "DAY", "WEEKLY": "WEEK", "MONTHLY": "MONTH",
            "QUARTERLY": "QUARTER", "YEARLY": "YEAR"}[bucket]
    fn = DATE_TRUNC_FN[dialect]
    if dialect == "bigquery":
        return f"{fn}({col_sql}, {part})"
    return f"{fn}('{part}', {col_sql})"


def _collect_edges(entries):
    """(src, tgt, join_dict) edges from inline model_tables joins."""
    edges = []
    for e in entries:
        for j in e.get("joins", []) or []:
            if "referencing_join" in j:
                raise UnsupportedModelError(
                    f"referencing_join to {j['with']} — supply SQL manually")
            edges.append((e["name"], j["with"], j))
    return edges


def _bfs_parents(root, edges):
    """BFS over the bidirectional edge set from root.

    Returns (parent, order): parent maps node -> (parent_node, join_dict,
    reversed) where reversed means the edge was traversed target->source;
    order is the deterministic BFS discovery order (declaration order per
    frontier node).
    """
    parent = {root: None}
    order = [root]
    frontier = [root]
    while frontier:
        nxt = []
        for node in frontier:
            for src, tgt, j in edges:
                other = tgt if src == node else (src if tgt == node else None)
                if other is None or other in parent:
                    continue
                parent[other] = (node, j, tgt == node)
                order.append(other)
                nxt.append(other)
        frontier = nxt
    return parent, order


def _path_tables(needed_tables, parent, root):
    """Tables on root->needed paths (excluding root) — the joins to keep."""
    keep = set()
    for t in needed_tables:
        cur = t
        while cur != root:
            keep.add(cur)
            cur = parent[cur][0]
    return keep


def _join_condition_sql(join, table_tmls, dialect):
    return _JOIN_COND.sub(
        lambda m: f"{_q(dialect, m.group(1))}."
                  f"{_q(dialect, _db_col(table_tmls, m.group(1), m.group(2)))}",
        join["on"])


def _join_clauses(model_tml, table_tmls, dialect, needed_tables):
    entries = model_tml["model"]["model_tables"]
    root = entries[0]["name"]
    parent, order = _bfs_parents(root, _collect_edges(entries))
    missing = sorted(needed_tables - set(parent))
    if missing:
        raise UnsupportedModelError(
            f"tables {missing} unreachable via inline joins")
    keep = _path_tables(needed_tables, parent, root)
    clauses = []
    for node in order:
        if node == root or node not in keep:
            continue
        _, join, reverse = parent[node]
        jtype = join.get("type", "INNER")
        if reverse:
            jtype = _SWAPPED_JOIN.get(jtype, jtype)
        clauses.append(
            f"{_JOIN_TYPE[jtype]} {_table_ref(_table_doc(table_tmls, node), dialect)} "
            f"{_q(dialect, node)} ON {_join_condition_sql(join, table_tmls, dialect)}")
    return (f"FROM {_table_ref(_table_doc(table_tmls, root), dialect)} "
            f"{_q(dialect, root)}", clauses)


def _select_dimension_items(model_tml, table_tmls, dialect, candidate, needed):
    select_items, group_items = [], []
    for d in candidate["dimensions"]:
        col_sql, table = _resolve(model_tml, table_tmls, dialect, d)
        needed.add(table)
        select_items.append(f"{col_sql} AS {_q(dialect, d)}")
        group_items.append(col_sql)
    return select_items, group_items


def _select_date_items(model_tml, table_tmls, dialect, candidate, needed):
    select_items, group_items = [], []
    if candidate.get("date_column"):
        col_sql, table = _resolve(model_tml, table_tmls, dialect,
                                  candidate["date_column"])
        needed.add(table)
        expr = (_date_trunc(dialect, candidate["bucket"], col_sql)
                if candidate.get("bucket") else col_sql)
        select_items.append(f"{expr} AS {_q(dialect, candidate['date_column'])}")
        group_items.append(expr)
    return select_items, group_items


def _select_measure_items(model_tml, table_tmls, dialect, candidate, plans, needed):
    select_items = []
    for m in candidate.get("measure_columns", []):
        plan = plans.get(m)
        if not plan or not plan["decomposable"]:
            continue
        for comp in plan["components"]:
            col_sql, table = _resolve(model_tml, table_tmls, dialect,
                                      comp["source_column"])
            needed.add(table)
            fn = "COUNT" if comp["func"] == "COUNT" else comp["func"]
            select_items.append(f"{fn}({col_sql}) AS {_q(dialect, comp['alias'])}")
    return select_items


def build_select(model_tml: dict, table_tmls: dict, candidate: dict,
                 plans: dict, dialect: str = "snowflake") -> str:
    needed: set = set()
    dim_select, dim_group = _select_dimension_items(
        model_tml, table_tmls, dialect, candidate, needed)
    date_select, date_group = _select_date_items(
        model_tml, table_tmls, dialect, candidate, needed)
    measure_select = _select_measure_items(
        model_tml, table_tmls, dialect, candidate, plans, needed)

    select_items = dim_select + date_select + measure_select
    group_items = dim_group + date_group

    from_clause, joins = _join_clauses(model_tml, table_tmls, dialect, needed)
    lines = ["SELECT", "  " + ",\n  ".join(select_items), from_clause]
    lines.extend(joins)
    if group_items:
        lines.append("GROUP BY " + ", ".join(group_items))
    return "\n".join(lines)


def build_profile_sql(select_sql: str) -> str:
    return f"SELECT COUNT(*) AS agg_rows FROM (\n{select_sql}\n) _agg"


def build_base_count_sql(model_tml: dict, table_tmls: dict,
                         dialect: str = "snowflake") -> str:
    root = model_tml["model"]["model_tables"][0]["name"]
    return (f"SELECT COUNT(*) AS base_rows FROM "
            f"{_table_ref(_table_doc(table_tmls, root), dialect)}")


def resolve_materialization(dialect: str, materialization: str) -> str:
    """Resolve `materialization="auto"` to the dialect's default target type.

    Extracted so callers that need to know the *actual* materialization ahead
    of DDL emission (e.g. the `generate` command's warehouse-required check for
    Snowflake dynamic tables) share this one resolution rule with `build_ddl`
    instead of re-deriving it and risking drift.
    """
    if materialization == "auto":
        return "dynamic" if dialect == "snowflake" else "mview"
    return materialization


def build_ddl(select_sql: str, target: str, dialect: str,
              materialization: str = "auto", target_lag: str = "1 hour",
              warehouse: Optional[str] = None) -> str:
    materialization = resolve_materialization(dialect, materialization)
    if materialization == "ctas":
        return f"CREATE OR REPLACE TABLE {target} AS\n{select_sql}"
    if dialect == "snowflake" and materialization == "dynamic":
        wh = f"\n  WAREHOUSE = {warehouse}" if warehouse else ""
        return (f"CREATE OR REPLACE DYNAMIC TABLE {target}\n"
                f"  TARGET_LAG = '{target_lag}'{wh}\nAS\n{select_sql}")
    if dialect == "bigquery":
        return f"CREATE MATERIALIZED VIEW {target} AS\n{select_sql}"
    return f"CREATE OR REPLACE MATERIALIZED VIEW {target} AS\n{select_sql}"
