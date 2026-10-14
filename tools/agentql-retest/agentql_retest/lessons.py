"""The `lessons` suite: every behavioural claim in
`agents/cli/ts-object-model-agentql-query/references/learning-path.md`, as a case.

Each case's `row` names the lesson it backs ("📘 2.3 …"), and each lesson in the doc names its
cases, so a CHANGED here points straight at the paragraph to fix.

Runs on "(Sample) Retail - Apparel", the system-authored sample Model that ships on every
cluster. Its `date` column is a formula that rolls the 2020 sample data forward to today, so
nothing here asserts a date-bucketed number. Checks are structural (what the SQL contains)
or relative to a control on the same Model (per-region rows sum to the grand total).
"""
from __future__ import annotations

import datetime as dt

from .classify import FETCH_ERROR, GEN_ERROR, OK, Case

SAMPLE_MODEL = "(Sample) Retail - Apparel"
F = f'FROM "{SAMPLE_MODEL}" AS "t1"'
REGION, ITEM, SALES, QTY, DATE, STORE = ('"t1"."region"', '"t1"."item type"', '"t1"."sales"',
                                         '"t1"."quantity purchased"', '"t1"."date"', '"t1"."store"')
L = "📘 "


def _ctl(results, cid):
    return results[cid]["fetch"]["rows"]


def _sums_to_total(rows, results):
    total = _ctl(results, "ctl_ap_total")[0][0]
    got = sum(r[-1] for r in rows)
    return None if abs(got - total) <= 1e-6 * abs(total) else f"rows sum to {got}, grand total is {total}"


def _top3_desc(rows, _results):
    s = [r[-1] for r in rows]
    if len(rows) != 3:
        return f"LIMIT 3 returned {len(rows)} rows"
    return None if s == sorted(s, reverse=True) else f"not sorted descending: {s}"


def _latest_date_is_today(rows, _results):
    """The rolling `date` formula ends today; dates arrive as INT64 epoch seconds."""
    v = rows[0][0]
    if not isinstance(v, int):
        return f"date arrived as {type(v).__name__} {v!r}, documented INT64 epoch seconds"
    latest = dt.datetime.fromtimestamp(v, dt.timezone.utc).date()
    lag = (dt.datetime.now(dt.timezone.utc).date() - latest).days
    return None if 0 <= lag <= 2 else f"latest date {latest} is {lag} days from today; the formula should roll to today"


def _west_matches_control(rows, results):
    west = {r[0]: r[1] for r in _ctl(results, "ctl_ap_by_region")}.get("West")
    return None if west is not None and abs(rows[0][0] - west) <= 1e-6 * abs(west) else \
        f"region = 'west' gave {rows[0][0]}, the West row of the control is {west}"


def _not_aggregated(rows, results):
    regions = len(_ctl(results, "ctl_ap_by_region"))
    return None if len(rows) > 10 * regions else f"{len(rows)} rows — looks aggregated, documented row-level"


LESSON_CASES = [
    # ---- controls ---------------------------------------------------------------------------
    Case("ctl_ap_total", f'SELECT SUM({SALES}) AS s {F}', OK, "control", model="apparel", control=True),
    Case("ctl_ap_by_region", f'SELECT {REGION} AS r, SUM({SALES}) AS s {F} GROUP BY {REGION}', OK,
         "control", model="apparel", control=True),

    # ---- module 1: the two APIs ---------------------------------------------------------------
    Case("l1_select_star_rejected", f'SELECT * {F}', GEN_ERROR, L + "1.2 a rejected query is a structured error",
         model="apparel", code="SELECT_STAR"),
    Case("l1_unknown_column", f'SELECT SUM("t1"."revenue") AS s {F}', GEN_ERROR,
         L + "1.2 a rejected query is a structured error", model="apparel", code="COLUMN_NOT_FOUND"),
    Case("l1_compiles_then_fails", f'SELECT BITAND({QTY}, 1) AS x {F} LIMIT 3', FETCH_ERROR,
         L + "1.3 generate-sql SUCCESS is not proof the query runs", model="apparel",
         code="QUERY_EXECUTION_FAILED", sql_has=("&",)),
    Case("l1_dates_are_epoch_seconds",
         f'SELECT {DATE} AS d, SUM({SALES}) AS s {F} GROUP BY {DATE} ORDER BY {DATE} DESC LIMIT 1', OK,
         L + "1.4 reading fetch-data: types, and dates as epoch seconds", model="apparel",
         check=_latest_date_is_today),

    # ---- module 2: first queries --------------------------------------------------------------
    Case("l2_total_touches_fact_only", f'SELECT SUM({SALES}) AS s, SUM({QTY}) AS q {F}', OK,
         L + "2.1 a total: null handling, the row cap, one table", model="apparel",
         sql_has=("is not null then sum(", "limit 100000", "fact_retapp_sales"), sql_lacks=("join",)),
    Case("l2_group_by_joins_one_dim", f'SELECT {REGION} AS r, SUM({SALES}) AS s {F} GROUP BY {REGION}', OK,
         L + "2.2 grouping by a dimension: the join is written for you", model="apparel",
         sql_has=("join", "dim_retapp_stores", "storeid"), sql_lacks=("dim_retapp_products",),
         check=_sums_to_total),
    Case("l2_two_dims_two_joins",
         f'SELECT {ITEM} AS it, {REGION} AS r, SUM({SALES}) AS s {F} GROUP BY {ITEM}, {REGION}', OK,
         L + "2.3 two dimensions, two joins", model="apparel",
         sql_has=("dim_retapp_stores", "dim_retapp_products"), check=_sums_to_total),
    Case("l2_top_n",
         f'SELECT {ITEM} AS it, SUM({SALES}) AS s {F} GROUP BY {ITEM} ORDER BY s DESC LIMIT 3', OK,
         L + "2.4 top N: ORDER BY and LIMIT", model="apparel", sql_has=("nulls last", "limit 3"),
         check=_top3_desc),
    Case("l2_formula_compiles_inline",
         f'SELECT YEAR({DATE}) AS y, SUM({SALES}) AS s {F} GROUP BY YEAR({DATE})', OK,
         L + "2.5 a Model formula compiles into the SQL", model="apparel",
         sql_has=("dateadd(", "current_date()"), check=_sums_to_total),
    Case("l2_current_date_rejected", f'SELECT CURRENT_DATE AS d, SUM({SALES}) AS s {F}', GEN_ERROR,
         L + "2.5 a Model formula compiles into the SQL (break it)", model="apparel", code="SQL_DATE_FUNCTION"),
    Case("l2_filter_case_insensitive", f"SELECT SUM({SALES}) AS s {F} WHERE {REGION} = 'west'", OK,
         L + "2.6 filters: string equality is case-insensitive", model="apparel",
         sql_has=("lower(", "join"), check=_west_matches_control),
    Case("l2_identifiers_case_insensitive",
         f'SELECT SUM("t1"."Sales") AS s FROM "{SAMPLE_MODEL.lower()}" AS "t1"', OK,
         L + "2.7 the parser is lenient: identifier case", model="apparel", same_as="ctl_ap_total"),
    Case("l2_implicit_group_by", f'SELECT {REGION} AS r, SUM({SALES}) AS s {F}', OK,
         L + "2.7 the parser is lenient: a missing GROUP BY", model="apparel",
         sql_has=("group by",), same_as="ctl_ap_by_region"),
    Case("l2_bare_measure_row_level", f'SELECT {REGION} AS r, {SALES} AS s {F}', OK,
         L + "2.8 a bare measure is not aggregated", model="apparel", sql_lacks=("sum(",),
         check=_not_aggregated),
    Case("l2_count_distinct", f'SELECT COUNT(DISTINCT {STORE}) AS n {F}', OK,
         L + "2.6 counting: COUNT(DISTINCT col), never COUNT(*)", model="apparel",
         sql_has=("count(distinct",)),
    Case("l2_count_star_rejected", f'SELECT COUNT(*) AS n {F}', GEN_ERROR,
         L + "2.6 counting: COUNT(DISTINCT col), never COUNT(*)", model="apparel", code="COUNT_STAR"),
]
