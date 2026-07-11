"""Aggregate SELECT / profiling SQL / DDL emission (pure, no I/O)."""
from __future__ import annotations

import re
from typing import Optional


class UnsupportedModelError(Exception):
    """Model shape sqlgen cannot handle deterministically (skill falls back to manual SQL)."""


_QUOTE = {"snowflake": '"', "databricks": "`", "bigquery": "`"}
_JOIN_COND = re.compile(r"\[([^:\]]+)::([^\]]+)\]")
DATE_TRUNC_FN = {"snowflake": "DATE_TRUNC", "databricks": "DATE_TRUNC", "bigquery": "DATE_TRUNC"}


def _q(dialect: str, ident: str) -> str:
    q = _QUOTE[dialect]
    return f"{q}{ident}{q}"


def _table_ref(table_tml: dict, dialect: str) -> str:
    t = table_tml["table"]
    return ".".join(_q(dialect, p) for p in (t["db"], t["schema"], t["db_table"]))


def _db_col(table_tmls: dict, table: str, col: str) -> str:
    for c in table_tmls[table]["table"].get("columns", []):
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


def _join_clauses(model_tml, table_tmls, dialect, needed_tables):
    entries = model_tml["model"]["model_tables"]
    names = [e["name"] for e in entries]
    root = names[0]
    clauses, joined = [], {root}
    # walk join edges breadth-first from the root until all needed tables joined
    frontier = True
    while frontier and not needed_tables <= joined:
        frontier = False
        for e in entries:
            for j in e.get("joins", []) or []:
                if "referencing_join" in j:
                    raise UnsupportedModelError(
                        f"referencing_join to {j['with']} — supply SQL manually")
                src, tgt = e["name"], j["with"]
                new = tgt if src in joined and tgt not in joined else (
                    src if tgt in joined and src not in joined else None)
                if new is None:
                    continue
                cond = _JOIN_COND.sub(
                    lambda m: f"{_q(dialect, m.group(1))}."
                              f"{_q(dialect, _db_col(table_tmls, m.group(1), m.group(2)))}",
                    j["on"])
                jt = {"INNER": "JOIN", "LEFT_OUTER": "LEFT JOIN",
                      "RIGHT_OUTER": "RIGHT JOIN", "OUTER": "FULL JOIN"}[j.get("type", "INNER")]
                clauses.append(f"{jt} {_table_ref(table_tmls[new], dialect)} "
                               f"{_q(dialect, new)} ON {cond}")
                joined.add(new)
                frontier = True
    if not needed_tables <= joined:
        raise UnsupportedModelError(
            f"tables {sorted(needed_tables - joined)} unreachable via inline joins")
    return f"FROM {_table_ref(table_tmls[root], dialect)} {_q(dialect, root)}", clauses


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
    return f"SELECT COUNT(*) AS base_rows FROM {_table_ref(table_tmls[root], dialect)}"


def build_ddl(select_sql: str, target: str, dialect: str,
              materialization: str = "auto", target_lag: str = "1 hour",
              warehouse: Optional[str] = None) -> str:
    if materialization == "auto":
        materialization = "dynamic" if dialect == "snowflake" else "mview"
    if materialization == "ctas":
        return f"CREATE OR REPLACE TABLE {target} AS\n{select_sql}"
    if dialect == "snowflake" and materialization == "dynamic":
        wh = f"\n  WAREHOUSE = {warehouse}" if warehouse else ""
        return (f"CREATE OR REPLACE DYNAMIC TABLE {target}\n"
                f"  TARGET_LAG = '{target_lag}'{wh}\nAS\n{select_sql}")
    if dialect == "bigquery":
        return f"CREATE MATERIALIZED VIEW {target} AS\n{select_sql}"
    return f"CREATE OR REPLACE MATERIALIZED VIEW {target} AS\n{select_sql}"
