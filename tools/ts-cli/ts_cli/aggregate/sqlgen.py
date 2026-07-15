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
    """display name -> (table, physical column name).

    Every ThoughtSpot formula appears in model.columns[] with a formula_id
    and NO column_id (the physical-vs-formula column rule — a column has
    either column_id XOR formula_id, never both). Formula-backed columns
    have no physical TABLE::COL shape to map, so they're skipped here; their
    rewrite-plan components resolve via their own source_column physical
    columns instead (see measures.build_rewrite_plans).
    """
    out = {}
    for c in model_tml["model"].get("columns", []) or []:
        if not c.get("column_id"):
            continue
        table, col = c["column_id"].split("::", 1)
        out[c["name"]] = (table, col)
    return out


def _resolve(model_tml, table_tmls, dialect, display_name):
    try:
        table, col = _col_map(model_tml)[display_name]
    except KeyError:
        raise UnsupportedModelError(
            f"'{display_name}' is not a resolvable physical column — likely a "
            "formula referencing another formula/nested measure; supply SQL "
            "manually") from None
    return f"{_q(dialect, table)}.{_q(dialect, _db_col(table_tmls, table, col))}", table


def _date_trunc(dialect: str, bucket: str, col_sql: str) -> str:
    part = {"HOURLY": "HOUR", "DAILY": "DAY", "WEEKLY": "WEEK", "MONTHLY": "MONTH",
            "QUARTERLY": "QUARTER", "YEARLY": "YEAR"}[bucket]
    fn = DATE_TRUNC_FN[dialect]
    if dialect == "bigquery":
        return f"{fn}({col_sql}, {part})"
    return f"{fn}('{part}', {col_sql})"


def _resolve_referencing_join(source_table: str, ref_name: str, table_tmls: dict) -> dict:
    """Resolve a `referencing_join` pointer to its real `on` + `type`.

    Real ThoughtSpot models (26.9) express most joins this way: the model's
    model_tables[].joins[] entry carries only a `referencing_join` name; the
    actual condition lives on the SOURCE table's own TML, in
    `table.joins_with[]`, keyed by that same name (`destination.name` there
    is just confirmation of the target — `with` on the model side remains
    the trusted key for the joined-table). The `on` string uses the
    identical `[T::col] = [T::col]` format as an inline join, and `type`
    uses the same INNER/LEFT_OUTER/RIGHT_OUTER/OUTER vocabulary — both are
    consumed as-is by the existing inline-join machinery once resolved here.

    Never silently drops a join: source table TML missing, no `joins_with`
    at all, no `joins_with` entry matching `ref_name`, or a matching entry
    missing its `on` condition all raise UnsupportedModelError rather than
    proceeding without a condition, which would risk an unintended cartesian
    join / wrong aggregate totals. `type` is optional and defaults to INNER,
    matching the `_JOIN_TYPE` fallback used elsewhere for inline joins.
    """
    joins_with = (table_tmls.get(source_table) or {}).get("table", {}).get("joins_with") or []
    for jw in joins_with:
        if jw.get("name") == ref_name:
            on = jw.get("on")
            if not on:
                raise UnsupportedModelError(
                    f"joins_with entry '{ref_name}' on table '{source_table}' "
                    "has no 'on' condition")
            return {"on": on, "type": jw.get("type", "INNER")}
    raise UnsupportedModelError(
        f"referencing_join '{ref_name}' not found in table '{source_table}' joins_with")


def _collect_edges(entries, table_tmls):
    """(src, tgt, join_dict) edges from model_tables joins.

    Inline `on` joins pass through unchanged; `referencing_join` entries are
    resolved against the source table's `joins_with[]` (see
    `_resolve_referencing_join`) so downstream code — condition rewriting,
    join-type mapping, and the open-item #11 mandatory-INNER-retention rule —
    all see a uniform join_dict shape regardless of which form the model used.
    """
    edges = []
    for e in entries:
        for j in e.get("joins", []) or []:
            if "referencing_join" in j:
                resolved = _resolve_referencing_join(
                    e["name"], j["referencing_join"], table_tmls)
                j = {**j, "on": resolved["on"], "type": resolved["type"]}
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


def _mandatory_inner_tables(order, parent):
    """Tables whose direct join to the BFS spanning tree is an unconditional
    INNER join — these must always be retained, even when no column from
    them is selected (open-item #11).

    An INNER join can only ever reduce the row set relative to whatever has
    been joined so far; retaining one is always correct — at worst it's an
    over-inclusive join, never a source of wrong numbers. Dropping a
    mandatory INNER join because its columns aren't in the grain is the
    dangerous case: it silently keeps rows the primary Model's canonical
    query would have excluded (a nullable/orphan FK with no match), inflating
    aggregate totals. LEFT_OUTER/RIGHT_OUTER/OUTER joins to unreferenced
    tables carry no such risk (they don't change the row set if dropped), so
    they're still eligible for pruning.

    INNER's effective type is direction-invariant — only LEFT_OUTER/
    RIGHT_OUTER flip on a reversed (target->source) traversal (see
    _SWAPPED_JOIN); INNER/OUTER are unaffected, so the raw declared type is
    checked directly rather than the reversal-adjusted one.
    """
    keep = set()
    for node in order:
        info = parent.get(node)
        if info is None:
            continue  # root
        _, join, _reverse = info
        if join.get("type", "INNER") == "INNER":
            keep.add(node)
    return keep


def _join_condition_sql(join, table_tmls, dialect):
    return _JOIN_COND.sub(
        lambda m: f"{_q(dialect, m.group(1))}."
                  f"{_q(dialect, _db_col(table_tmls, m.group(1), m.group(2)))}",
        join["on"])


def _join_clauses(model_tml, table_tmls, dialect, needed_tables):
    entries = model_tml["model"]["model_tables"]
    root = entries[0]["name"]
    parent, order = _bfs_parents(root, _collect_edges(entries, table_tmls))
    missing = sorted(needed_tables - set(parent))
    if missing:
        raise UnsupportedModelError(
            f"tables {missing} not reachable from root via model joins")
    mandatory = _mandatory_inner_tables(order, parent)
    keep = _path_tables(needed_tables | mandatory, parent, root)
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


def _cand_date_grains(candidate: dict) -> list:
    """Candidate's date grains (Task 15). Falls back to a 1-item list derived
    from the date_column/bucket compat shim (Task 14) when date_grains is
    absent, so hand-built single-date candidate dicts (existing callers/tests)
    keep working unchanged — a 1-grain candidate must produce byte-identical
    SQL to the pre-Task-15 single-date code path."""
    grains = candidate.get("date_grains")
    if grains is not None:
        return grains
    col = candidate.get("date_column")
    return [{"column": col, "bucket": candidate.get("bucket")}] if col else []


def _select_date_items(model_tml, table_tmls, dialect, candidate, needed):
    select_items, group_items = [], []
    for grain in _cand_date_grains(candidate):
        col_sql, table = _resolve(model_tml, table_tmls, dialect, grain["column"])
        needed.add(table)
        # bucket is None for a raw/unbucketed date grain — select the plain
        # column (no DATE_TRUNC) rather than truncating it.
        expr = (_date_trunc(dialect, grain["bucket"], col_sql)
                if grain.get("bucket") else col_sql)
        select_items.append(f"{expr} AS {_q(dialect, grain['column'])}")
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


_MEASURE_REF = re.compile(r"\[([^\]:]+)::")


def base_table_name(model_tml: dict) -> str:
    """The fact table to count for `base_rows` — the physical table owning the
    model's MEASURE columns.

    The base row count is the compression denominator (detail rows scanned).
    In a star schema that's the fact table; dimension joins are many-to-one and
    do not multiply fact rows, so a bare `COUNT(*)` of the fact is the right
    detail-grain count. The previous implementation used `model_tables[0]`,
    which is arbitrary ordering — when a dimension happened to be listed first
    (e.g. an 8-row category table) `base_rows` came back as that dimension's
    tiny count, making every compression ratio meaningless.

    Resolves the fact from measure columns: a plain measure column's
    `column_id` (`TABLE::col`) names its table directly; a formula measure's
    table comes from the `[TABLE::col]` refs in its expr. The table owning the
    most measures wins (the fact in a single-fact model). Falls back to
    `model_tables[0]` only when no measure resolves to a known table.
    """
    from collections import Counter
    m = model_tml["model"]
    valid = {t["name"] for t in m.get("model_tables", []) or []}
    formulas = {f.get("id"): f.get("expr", "") for f in m.get("formulas", []) or []}
    counts: Counter = Counter()
    for c in m.get("columns", []) or []:
        if (c.get("properties") or {}).get("column_type") != "MEASURE":
            continue
        cid = c.get("column_id")
        if cid and "::" in cid:
            counts[cid.split("::", 1)[0]] += 1
        else:
            for tbl in _MEASURE_REF.findall(formulas.get(c.get("formula_id"), "")):
                counts[tbl] += 1
    for tbl, _n in counts.most_common():
        if tbl in valid:
            return tbl
    return m["model_tables"][0]["name"]


def build_base_count_sql(model_tml: dict, table_tmls: dict,
                         dialect: str = "snowflake") -> str:
    root = base_table_name(model_tml)
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
    if dialect == "snowflake" and materialization == "mview":
        raise UnsupportedModelError(
            "Snowflake materialized views cannot contain joins (Snowflake "
            "error 002212 — 'More than one table referenced in the view "
            "definition'); use a dynamic table (--materialization dynamic, "
            "auto-refreshing, needs a warehouse) or a plain table "
            "(--materialization ctas, CREATE TABLE AS, manual refresh) instead.")
    if materialization == "ctas":
        return f"CREATE OR REPLACE TABLE {target} AS\n{select_sql}"
    if dialect == "snowflake" and materialization == "dynamic":
        wh = f"\n  WAREHOUSE = {warehouse}" if warehouse else ""
        return (f"CREATE OR REPLACE DYNAMIC TABLE {target}\n"
                f"  TARGET_LAG = '{target_lag}'{wh}\nAS\n{select_sql}")
    if dialect == "bigquery":
        return f"CREATE MATERIALIZED VIEW {target} AS\n{select_sql}"
    return f"CREATE OR REPLACE MATERIALIZED VIEW {target} AS\n{select_sql}"
