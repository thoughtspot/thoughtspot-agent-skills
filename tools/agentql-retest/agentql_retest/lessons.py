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
import math
import statistics

from .classify import FETCH_ERROR, GEN_ERROR, OK, Case

SAMPLE_MODEL = "(Sample) Retail - Apparel"
F = f'FROM "{SAMPLE_MODEL}" AS "t1"'
REGION, ITEM, SALES, QTY, DATE, STORE = ('"t1"."region"', '"t1"."item type"', '"t1"."sales"',
                                         '"t1"."quantity purchased"', '"t1"."date"', '"t1"."store"')
STATE = '"t1"."state"'
THIS_YEAR = dt.date.today().year  # the `date` formula rolls the data to end today
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


def _close(a, b, rel=1e-9):
    return a is not None and b is not None and math.isclose(a, b, rel_tol=rel, abs_tol=1e-6)


def _sums_to_total_col(col):
    def check(rows, results):
        total = _ctl(results, "ctl_ap_total")[0][0]
        got = sum(r[col] for r in rows)
        return None if _close(got, total, 1e-6) else f"column {col} sums to {got}, grand total is {total}"
    return check


def _this_year_row(results):
    return {r[0]: r[1] for r in _ctl(results, "ctl_ap_by_year")}.get(THIS_YEAR)


def _equals_this_year(rows, results):
    want = _this_year_row(results)
    return None if _close(rows[0][0], want, 1e-6) else f"gave {rows[0][0]}, the {THIS_YEAR} row of the control is {want}"


def _ratio_matches_parts(rows, results):
    parts = {r[0]: (r[1], r[2]) for r in _ctl(results, "ctl_ap_item_parts")}
    bad = [r for r in rows if not _close(r[1], parts[r[0]][0] / parts[r[0]][1], 1e-6)]
    return f"ratio is not SUM(sales) / SUM(qty) for {bad[:2]}" if bad else None


def _avg_is_sum_over_count(rows, _results):
    bad = [r for r in rows if not _close(r[1], r[2] / r[3], 1e-6)]
    return f"AVG is not SUM / COUNT for {bad[:2]}" if bad else None


def _strings_consistent(rows, _results):
    for u, n, c, sub in rows:
        region, state = c.split("-", 1)
        if (u, n, sub) != (region.upper(), len(region), state[:3]):
            return f"string functions disagree for {c!r}: UPPER={u!r} LENGTH={n} SUBSTR={sub!r}"
    return None


def _week_days(rows, _results):
    days = sorted(r[0] for r in rows)
    return None if days == list(range(1, 8)) else f"DAY_IN_WEEK_NUMBER values {days}, documented 1..7"


def _store_mean(rows, results):
    stores = [r[1] for r in _ctl(results, "ctl_ap_by_store")]
    avg, n = rows[0]
    return None if (n == len(stores) and _close(avg, statistics.mean(stores), 1e-6)) else \
        f"CTE gave avg {avg} over {n} stores; control has {len(stores)} stores, mean {statistics.mean(stores)}"


def _store_stdev(rows, results):
    want = statistics.stdev(r[1] for r in _ctl(results, "ctl_ap_by_store"))
    return None if _close(rows[0][0], want, 1e-6) else f"STDDEV over the CTE gave {rows[0][0]}, hand-computed {want}"


def _rank_one_is_max(rows, _results):
    best = {}
    for r, _store, s, rk in rows:
        best[r] = max(best.get(r, s), s)
    bad = [x for x in rows if x[3] == 1 and not _close(x[2], best[x[0]])]
    return f"rank 1 is not the regional max: {bad[:2]}" if bad else None


def _shares_sum_to_one(rows, _results):
    total = sum(r[2] for r in rows)
    return None if _close(total, 1.0, 1e-9) else f"shares sum to {total}"


def _two_per_region(rows, results):
    regions = {r[0] for r in _ctl(results, "ctl_ap_by_region")}
    counts = {g: sum(1 for r in rows if r[0] == g) for g in regions}
    return None if set(counts.values()) == {2} else f"rows per region {counts}, documented 2"


def _lag_is_previous_year(rows, _results):
    by_year = {r[0]: r[1] for r in rows}
    bad = [r for r in rows if r[2] is not None and not _close(r[2], by_year.get(r[0] - 1))]
    first = min(by_year)
    if [r[2] for r in rows if r[0] == first] != [None]:
        return f"the first year's LAG should be NULL: {[r for r in rows if r[0] == first]}"
    return f"LAG is not the previous year's total for {bad[:2]}" if bad else None


def _running_ends_at_total(rows, results):
    total = _ctl(results, "ctl_ap_total")[0][0]
    last = max(rows, key=lambda r: r[0])
    return None if _close(last[2], total, 1e-6) else f"running total ends at {last[2]}, grand total is {total}"


def _union_matches_regions(rows, results):
    reg = {r[0]: r[1] for r in _ctl(results, "ctl_ap_by_region")}
    got = {r[0]: r[1] for r in rows}
    ok = set(got) == {"West", "East"} and all(_close(v, reg[k], 1e-6) for k, v in got.items())
    return None if ok else f"UNION ALL gave {got}"


def _per_store(rows, _results):
    bad = [r for r in rows if not _close(r[3], r[1] / r[2], 1e-6)]
    return f"per_store is not s / n for {bad[:2]}" if bad else None


def _all_over(threshold, col):
    def check(rows, _results):
        bad = [r for r in rows if not r[col] > threshold]
        return f"rows at or below {threshold}: {bad[:2]}" if bad else None
    return check


def _columns_match_rows(rows, _results):
    return None if rows and all(len(r) == 3 for r in rows) else "row width is not the 3 selected columns"


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

    # ---- module 3: what the semantic layer does for you ---------------------------------------
    Case("ctl_ap_item_parts", f'SELECT {ITEM} AS it, SUM({SALES}) AS s, SUM({QTY}) AS q {F} GROUP BY {ITEM}', OK,
         "control", model="apparel", control=True),
    Case("l3_ratio_safe_division", f'SELECT {ITEM} AS it, SUM({SALES}) / SUM({QTY}) AS avg_price {F} GROUP BY {ITEM}',
         OK, L + "3.1 a ratio of two measures, divided safely", model="apparel", sql_has=("nullif(",),
         check=_ratio_matches_parts),
    Case("l3_avg_is_row_level", f'SELECT {REGION} AS r, AVG({SALES}) AS a, SUM({SALES}) AS s, COUNT({SALES}) AS n '
         f'{F} GROUP BY {REGION}', OK, L + "3.2 AVG averages fact rows, not anything larger", model="apparel",
         check=_avg_is_sum_over_count),
    Case("l3_agg_on_raw_measure_rejected", f'SELECT {REGION} AS r, AGG({SALES}) AS s {F} GROUP BY {REGION}',
         GEN_ERROR, L + "3.4 formula measures: AGG, not SUM (break it)", model="apparel", code="QUERY_GEN_ERROR"),
    Case("l3_dim_only_one_table", f'SELECT {ITEM} AS it {F} GROUP BY {ITEM}', OK,
         L + "3.3 a dimension-only query reads only its own table", model="apparel",
         sql_has=("dim_retapp_products",), sql_lacks=("join", "fact_retapp_sales")),
    Case("l3_two_dims_via_fact", f'SELECT {ITEM} AS it, {REGION} AS r {F} GROUP BY {ITEM}, {REGION}', OK,
         L + "3.3 two dimensions are joined through the fact table", model="apparel",
         sql_has=("fact_retapp_sales", "dim_retapp_products", "dim_retapp_stores")),

    # ---- module 4: dates and functions ----------------------------------------------------------
    Case("ctl_ap_by_year", f'SELECT YEAR_NUMBER({DATE}) AS y, SUM({SALES}) AS s {F} GROUP BY YEAR_NUMBER({DATE})',
         OK, "control", model="apparel", control=True),
    Case("l4_date_parts", f'SELECT YEAR_NUMBER({DATE}) AS y, QUARTER_NUMBER({DATE}) AS qn, MONTH_NUMBER({DATE}) AS m, '
         f'SUM({SALES}) AS s {F} GROUP BY YEAR_NUMBER({DATE}), QUARTER_NUMBER({DATE}), MONTH_NUMBER({DATE})', OK,
         L + "4.1 date parts with the extraction functions", model="apparel", check=_sums_to_total_col(3)),
    Case("l4_day_name", f'SELECT DAY_NAME({DATE}) AS dn, SUM({SALES}) AS s {F} GROUP BY DAY_NAME({DATE})', OK,
         L + "4.1 date parts with the extraction functions", model="apparel", check=_sums_to_total_col(1)),
    Case("l4_day_in_week", f'SELECT DAY_IN_WEEK_NUMBER({DATE}) AS dw, SUM({SALES}) AS s {F} '
         f'GROUP BY DAY_IN_WEEK_NUMBER({DATE})', OK, L + "4.1 date parts with the extraction functions",
         model="apparel", check=_week_days),
    Case("l4_this_year_relative", f'SELECT SUM({SALES}) AS s {F} WHERE DIFF_YEAR(START_OF_CURRENT_YEAR(), {DATE}) = 0',
         OK, L + "4.2 relative dates: the period functions", model="apparel", sql_has=("current_date()",),
         check=_equals_this_year),
    Case("l4_last_30_days", f'SELECT SUM({SALES}) AS s {F} WHERE DIFF_DAY(START_OF_CURRENT_DAY(), {DATE}) '
         'BETWEEN 1 AND 30', OK, L + "4.2 relative dates: the period functions", model="apparel",
         sql_has=("current_date()", ">= 1", "<= 30")),
    Case("l4_date_literal_filter", f"SELECT SUM({SALES}) AS s {F} WHERE {DATE} >= '{THIS_YEAR}-01-01'", OK,
         L + "4.3 a date literal in WHERE", model="apparel", check=_equals_this_year),
    Case("l4_date_trunc_fails", f"SELECT DATE_TRUNC('month', {DATE}) AS m, SUM({SALES}) AS s {F} "
         f"GROUP BY DATE_TRUNC('month', {DATE})", FETCH_ERROR, L + "4.3 a date literal in WHERE (break it)",
         model="apparel", code="QUERY_EXECUTION_FAILED"),
    Case("l4_string_functions", f"SELECT UPPER({REGION}) AS u, LENGTH({REGION}) AS l, CONCAT({REGION}, '-', {STATE}) "
         f"AS c, SUBSTR({STATE}, 1, 3) AS sub {F} GROUP BY UPPER({REGION}), LENGTH({REGION}), "
         f"CONCAT({REGION}, '-', {STATE}), SUBSTR({STATE}, 1, 3)", OK, L + "4.4 string functions",
         model="apparel", check=_strings_consistent),
    Case("l4_group_by_alias", f'SELECT UPPER({REGION}) AS u, SUM({SALES}) AS s {F} GROUP BY u', OK,
         L + "4.4 string functions", model="apparel", check=_sums_to_total_col(1)),
    Case("l4_group_by_ordinal_rejected", f'SELECT UPPER({REGION}) AS u, SUM({SALES}) AS s {F} GROUP BY 1', GEN_ERROR,
         L + "4.4 string functions", model="apparel", code="QUERY_GEN_ERROR"),
    Case("l4_case_buckets", f"SELECT CASE WHEN {SALES} >= 1000 THEN 'large' WHEN {SALES} >= 100 THEN 'medium' "
         f"ELSE 'small' END AS b, COUNT({SALES}) AS n, SUM({SALES}) AS s {F} GROUP BY CASE WHEN {SALES} >= 1000 "
         f"THEN 'large' WHEN {SALES} >= 100 THEN 'medium' ELSE 'small' END", OK,
         L + "4.5 CASE to bucket values", model="apparel", check=_sums_to_total_col(2)),

    # ---- module 5: advanced shapes ---------------------------------------------------------------
    Case("ctl_ap_by_store", f'SELECT {STORE} AS st, SUM({SALES}) AS s {F} GROUP BY {STORE}', OK, "control",
         model="apparel", control=True),
    Case("l5_cte_two_step", f'WITH st AS (SELECT {STORE} AS store, SUM({SALES}) AS s {F} GROUP BY {STORE}) '
         'SELECT AVG(st.s) AS avg_store_sales, COUNT(st.store) AS n FROM st', OK,
         L + "5.1 a CTE for two-step aggregation", model="apparel", check=_store_mean),
    Case("l5_rank", f'SELECT {REGION} AS r, {STORE} AS store, SUM({SALES}) AS s, RANK() OVER (PARTITION BY {REGION} '
         f'ORDER BY SUM({SALES}) DESC) AS rk {F} GROUP BY {REGION}, {STORE}', OK,
         L + "5.2 window functions: rank and share of total", model="apparel", check=_rank_one_is_max),
    Case("l5_share_of_total", f'SELECT {REGION} AS r, SUM({SALES}) AS s, SUM({SALES}) / SUM(SUM({SALES})) OVER () '
         f'AS share {F} GROUP BY {REGION}', OK, L + "5.2 window functions: rank and share of total",
         model="apparel", sql_has=("over ()",), check=_shares_sum_to_one),
    Case("l5_top_n_per_group", f'WITH x AS (SELECT {REGION} AS r, {ITEM} AS it, SUM({SALES}) AS s, ROW_NUMBER() OVER '
         f'(PARTITION BY {REGION} ORDER BY SUM({SALES}) DESC) AS rn {F} GROUP BY {REGION}, {ITEM}) '
         'SELECT x.r, x.it, x.s FROM x WHERE x.rn <= 2', OK, L + "5.3 top N per group", model="apparel",
         check=_two_per_region),
    Case("l5_year_over_year", f'SELECT YEAR_NUMBER({DATE}) AS y, SUM({SALES}) AS s, LAG(SUM({SALES})) OVER '
         f'(ORDER BY YEAR_NUMBER({DATE})) AS prev {F} GROUP BY YEAR_NUMBER({DATE})', OK,
         L + "5.4 period over period and running totals", model="apparel", check=_lag_is_previous_year),
    Case("l5_running_total", f'SELECT YEAR_NUMBER({DATE}) AS y, SUM({SALES}) AS s, SUM(SUM({SALES})) OVER '
         f'(ORDER BY YEAR_NUMBER({DATE})) AS running {F} GROUP BY YEAR_NUMBER({DATE})', OK,
         L + "5.4 period over period and running totals", model="apparel", check=_running_ends_at_total),
    Case("l5_union_all", f"SELECT {REGION} AS r, SUM({SALES}) AS s {F} WHERE {REGION} = 'West' GROUP BY {REGION} "
         f"UNION ALL SELECT {REGION} AS r, SUM({SALES}) AS s {F} WHERE {REGION} = 'East' GROUP BY {REGION}", OK,
         L + "5.5 combining results: set operations and CTE joins", model="apparel", check=_union_matches_regions),
    Case("l5_join_ctes", f'WITH a AS (SELECT {REGION} AS r, SUM({SALES}) AS s {F} GROUP BY {REGION}), b AS (SELECT '
         f'{REGION} AS r, COUNT(DISTINCT {STORE}) AS n {F} GROUP BY {REGION}) SELECT a.r, a.s, b.n, a.s / b.n AS '
         'per_store FROM a JOIN b ON a.r = b.r', OK, L + "5.5 combining results: set operations and CTE joins",
         model="apparel", check=_per_store),
    Case("l5_having", f'SELECT {STORE} AS store, SUM({SALES}) AS s {F} GROUP BY {STORE} HAVING SUM({SALES}) > 40000000',
         OK, L + "5.6 HAVING, and the shapes that are not allowed", model="apparel", sql_has=("having",),
         check=_all_over(40000000, 1)),
    Case("l5_from_subquery_rejected", f'SELECT x.r FROM (SELECT {REGION} AS r, SUM({SALES}) AS s {F} '
         f'GROUP BY {REGION}) AS x', GEN_ERROR, L + "5.6 HAVING, and the shapes that are not allowed",
         model="apparel", code="TABLE_NOT_FOUND"),

    # ---- module 6: trust, but verify ---------------------------------------------------------------
    Case("ctl_ap_top1_per_region", f'WITH x AS (SELECT {REGION} AS r, {ITEM} AS it, SUM({SALES}) AS s, ROW_NUMBER() '
         f'OVER (PARTITION BY {REGION} ORDER BY SUM({SALES}) DESC) AS rn {F} GROUP BY {REGION}, {ITEM}) '
         'SELECT x.r, x.it, x.s FROM x WHERE x.rn = 1', OK, "control", model="apparel", control=True),
    Case("ctl_ap_west_case", f"SELECT SUM(CASE WHEN {REGION} = 'West' THEN {SALES} ELSE 0 END) AS s {F}", OK,
         "control", model="apparel", control=True),
    Case("l6_qualify_dropped", f'SELECT {REGION} AS r, {ITEM} AS it, SUM({SALES}) AS s {F} GROUP BY {REGION}, {ITEM} '
         f'QUALIFY ROW_NUMBER() OVER (PARTITION BY {REGION} ORDER BY SUM({SALES}) DESC) = 1', OK,
         L + "6.1 QUALIFY is silently dropped", model="apparel", sql_lacks=("row_number",),
         differs_from="ctl_ap_top1_per_region"),
    Case("l6_filter_dropped", f"SELECT SUM({SALES}) FILTER (WHERE {REGION} = 'West') AS s {F}", OK,
         L + "6.2 FILTER (WHERE …) is silently dropped", model="apparel", sql_lacks=("west",),
         differs_from="ctl_ap_west_case"),
    Case("l6_where_aggregate_is_having", f'SELECT {STORE} AS store, SUM({SALES}) AS s {F} '
         f'WHERE SUM({SALES}) > 40000000 GROUP BY {STORE}', OK, L + "6.3 lenient rewrites you should not rely on",
         model="apparel", sql_has=("having",), same_as="l5_having"),
    Case("l6_stddev_rejected", f'SELECT STDDEV_SAMP({SALES}) AS sd {F}', GEN_ERROR,
         L + "6.4 loud failures, and their workarounds", model="apparel", code="UNSUPPORTED_AGGREGATE"),
    Case("l6_stddev_over_cte", f'WITH st AS (SELECT {STORE} AS store, SUM({SALES}) AS s {F} GROUP BY {STORE}) '
         'SELECT STDDEV_SAMP(st.s) AS sd FROM st', OK, L + "6.4 loud failures, and their workarounds",
         model="apparel", check=_store_stdev),
    Case("l6_in_subquery_fails", f'SELECT {REGION} AS r, SUM({SALES}) AS s {F} WHERE {REGION} IN (SELECT '
         f'"t2"."region" FROM "{SAMPLE_MODEL}" AS "t2" WHERE "t2"."state" = \'california\') GROUP BY {REGION}',
         FETCH_ERROR, L + "6.4 loud failures, and their workarounds", model="apparel",
         code="QUERY_EXECUTION_FAILED"),
    Case("l6_sum_case_date_literal", f"SELECT SUM(CASE WHEN {DATE} >= '{THIS_YEAR}-01-01' THEN {SALES} ELSE 0 END) "
         f"AS s {F}", OK, L + "6.1 QUALIFY is silently dropped (and one more silent case)", model="apparel",
         differs_from="ctl_ap_this_year_case"),
    Case("ctl_ap_this_year_case", f"SELECT SUM(CASE WHEN YEAR_NUMBER({DATE}) >= {THIS_YEAR} THEN {SALES} ELSE 0 END) "
         f"AS s {F}", OK, "control", model="apparel", control=True),

    # ---- module 7: building on it -------------------------------------------------------------------
    Case("l7_columns_match_rows", f'SELECT {REGION} AS r, {DATE} AS d, SUM({SALES}) AS s {F} GROUP BY {REGION}, {DATE} '
         f'ORDER BY {DATE} DESC LIMIT 5', OK, L + "7.1 consuming fetch-data in code", model="apparel",
         check=_columns_match_rows),
]
