"""Build a SpotQL SELECT for an aggregate candidate's grain, and wrap
ThoughtSpot's compiled warehouse SQL as aggregate-table DDL (pure, no I/O).

Task 18: pivots aggregate DDL generation away from the hand-rolled join
walker in sqlgen.py, which resolves joins itself and gets role-playing /
ambiguous-path dimensions wrong (live-proven: it grouped revenue by
inventory-balance month instead of order month — silently wrong aggregates).
ThoughtSpot's own SQL generation for the same grain is correct because it has
the full semantic model. `build_spotql` constructs the SpotQL statement for a
candidate's grain; the I/O layer (`commands/aggregate.py`) sends it to
`ts spotql generate-sql` against the primary Model (reusing
`ts_cli.commands.spotql`'s client path — never reimplemented here);
`wrap_as_ddl` turns the returned `executable_sql` into aggregate-table DDL.
`sqlgen.build_select` remains as a fallback for when SpotQL generation is
unavailable or errors — see `commands/aggregate.py`.

Bucket function names (`start_of_hour`/`day`/`week`/`month`/`quarter`/`year`)
mirror the ThoughtSpot formula-language date functions of the same name
(confirmed: `start_of_month ( [date] )` -> `DATE_TRUNC('MONTH', date)` in
agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md).
SpotQL is documented as "a restricted PostgreSQL dialect with ThoughtSpot
extensions" and explicitly FORBIDS `DATE_TRUNC`/`TRUNC(date, part)` (see
agents/cli/ts-object-model-spotql-query/references/spotql-rules.md and
udf-reference.md) — the documented SpotQL UDFs only extract integer date
parts or return TODAY-anchored period boundaries, neither of which can bucket
an arbitrary historical date to a period start. Reusing the formula-language
function names as SpotQL calls is the best-evidenced choice available without
a live cluster to probe; UNVERIFIED — flagged as a live-validation follow-up
(see the skill's references/open-items.md).

Measure-component expressions apply a real aggregate (SUM/COUNT/...) directly
over `comp["source_column"]` — the same base column the model's own formula
decomposes to (see `measures.classify_measure`), never over the formula name
itself, so they don't double-aggregate. This assumes `source_column` always
names a non-aggregate column; if a future measure decomposition ever pointed
`source_column` at an aggregate-formula column, wrapping it in a real
aggregate here would double-aggregate (`NESTED_AGGREGATE_NOT_SUPPORTED` per
spotql-rules.md) — that classification risk lives in measures.py, out of this
task's scope, and is also flagged as a live-validation follow-up.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ts_cli.aggregate.sqlgen import build_ddl

_ALIAS = "t1"

# Mirrors the ThoughtSpot formula-language date-bucketing functions of the
# same name (start_of_month/quarter/... take a column and return that
# column's period start) — see the module docstring for why DATE_TRUNC
# itself can't be used here (forbidden in SpotQL).
_BUCKET_FN = {
    "HOURLY": "start_of_hour",
    "DAILY": "start_of_day",
    "WEEKLY": "start_of_week",
    "MONTHLY": "start_of_month",
    "QUARTERLY": "start_of_quarter",
    "YEARLY": "start_of_year",
}

# A select-row tuple: (expr, alias_sql_or_None, output_alias, is_group_by).
_Row = Tuple[str, Optional[str], str, bool]


def _sq(ident: str) -> str:
    """Quote a SpotQL identifier. SpotQL identifiers are always double-quoted
    regardless of the target warehouse dialect — this is SpotQL syntax, not
    warehouse SQL; the warehouse dialect only matters once ThoughtSpot
    compiles this statement (see `wrap_as_ddl`, which quotes per-dialect)."""
    return '"' + ident.replace('"', '""') + '"'


def _col(name: str) -> str:
    return f"{_sq(_ALIAS)}.{_sq(name)}"


def _cand_date_grains(candidate: dict) -> list:
    """Candidate's date grains, with the single-date `date_column`/`bucket`
    shim fallback. Deliberately duplicated (not imported) to keep this
    module self-contained — the same convention sqlgen.py/lattice.py/
    generate.py each follow for their own copy of this helper."""
    grains = candidate.get("date_grains")
    if grains is not None:
        return grains
    col = candidate.get("date_column")
    return [{"column": col, "bucket": candidate.get("bucket")}] if col else []


def _dim_rows(candidate: dict) -> List[_Row]:
    return [(_col(d), None, d, True) for d in candidate.get("dimensions", []) or []]


def _date_rows(candidate: dict) -> List[_Row]:
    rows: List[_Row] = []
    for g in _cand_date_grains(candidate):
        col_name = g["column"]
        bucket = g.get("bucket")
        ref = _col(col_name)
        if bucket:
            expr = f"{_BUCKET_FN[bucket]}({ref})"
            rows.append((expr, _sq(col_name), col_name, True))
        else:
            rows.append((ref, None, col_name, True))
    return rows


def _measure_rows(candidate: dict, plans: dict) -> List[_Row]:
    rows: List[_Row] = []
    seen: set = set()
    for m in candidate.get("measure_columns", []) or []:
        plan = plans.get(m)
        if not plan or not plan.get("decomposable"):
            continue
        for comp in plan["components"]:
            key = (comp["source_column"], comp["func"])
            if key in seen:
                continue
            seen.add(key)
            expr = f"{comp['func']}({_col(comp['source_column'])})"
            rows.append((expr, _sq(comp["alias"]), comp["alias"], False))
    return rows


def build_spotql(candidate: dict, plans: dict, source_name: str) -> Tuple[str, List[str]]:
    """SpotQL SELECT over the primary's semantic columns for `candidate`'s
    grain: dimensions (quoted, unaliased), date grains at their bucket (a raw
    column, unaliased, when bucket is None), and one aggregate select item
    per rewrite-plan component covering `candidate["measure_columns"]`
    (deduped by identical `(source_column, func)`).

    Returns `(spotql, output_aliases)` — `output_aliases` is the ordered list
    (dims, then dates, then measure-component stored aliases) `wrap_as_ddl`
    position-maps against ThoughtSpot's `ca_N` columns.
    """
    rows = _dim_rows(candidate) + _date_rows(candidate) + _measure_rows(candidate, plans)

    select_items = [f"{expr} AS {alias_sql}" if alias_sql else expr
                    for expr, alias_sql, _, _ in rows]
    group_items = [expr for expr, _, _, is_group in rows if is_group]
    output_aliases = [output_alias for _, _, output_alias, _ in rows]

    lines = ["SELECT", "  " + ",\n  ".join(select_items),
             f"FROM {_sq(source_name)} AS {_sq(_ALIAS)}"]
    if group_items:
        lines.append("GROUP BY " + ", ".join(group_items))
    return "\n".join(lines), output_aliases


_TRAILING_LIMIT = re.compile(r"\s+LIMIT\s+\d+\s*;?\s*\Z", re.IGNORECASE)


def _strip_trailing_limit(sql: str) -> str:
    return _TRAILING_LIMIT.sub("", sql.rstrip())


# Dialect quoting for the wrapper's OUTER select list (the aggregate table's
# real physical column names) — deliberately duplicated from sqlgen._q
# rather than imported, matching this package's established
# self-contained-module convention (see e.g. the _cand_date_grains shim
# independently copied into sqlgen.py/lattice.py/generate.py).
_QUOTE = {"snowflake": '"', "databricks": "`", "bigquery": "`"}
_QUOTE_ESCAPE = {"snowflake": '""', "databricks": "``", "bigquery": "\\`"}


def _dq(dialect: str, ident: str) -> str:
    q = _QUOTE[dialect]
    return f"{q}{ident.replace(q, _QUOTE_ESCAPE[dialect])}{q}"


def wrap_as_ddl(ts_executable_sql: str, output_aliases: List[str], target: str,
                dialect: str, materialization: str = "auto",
                target_lag: Optional[str] = "1 hour",
                warehouse: Optional[str] = None) -> str:
    """Wrap ThoughtSpot's compiled `ts_executable_sql` — positional `ca_1`,
    `ca_2`, ... columns in `build_spotql`'s SELECT order, plus a trailing
    `LIMIT` — as aggregate-table DDL. Maps `ca_N` -> `output_aliases[N-1]` by
    position and strips the trailing LIMIT (inner content otherwise intact).
    Reuses `sqlgen.build_ddl` for the materialization shape (dynamic table /
    mview / ctas per dialect), including the Snowflake
    materialized-view-can't-join guard and the warehouse rule.
    """
    inner = _strip_trailing_limit(ts_executable_sql)
    select_items = [f"ca_{i + 1} AS {_dq(dialect, alias)}"
                    for i, alias in enumerate(output_aliases)]
    wrapper_select = ("SELECT " + ",\n       ".join(select_items) + "\n" +
                      f"FROM (\n{inner}\n) {_dq(dialect, 'src')}")
    return build_ddl(wrapper_select, target, dialect,
                     materialization=materialization,
                     target_lag=target_lag or "1 hour",
                     warehouse=warehouse)
