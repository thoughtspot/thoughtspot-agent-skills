"""The retest cases: one per documented construct in
`agents/cli/ts-object-model-agentql-query/references/limitations.md`.

Each case states what the doc says TODAY. When a run reports CHANGED, update the doc row
(and the rules it feeds), then update the case here so the next run is quiet again.

Written against the Dunder Mifflin demo Models (synthetic data):
  single — "DunderMifflin Sales": one table, has a date column
  multi  — "Dunder Mifflin": multi-table, carries `group_aggregate` formulas
Value checks are relative to control cases wherever possible, so a data reload does not
read as a behaviour change. Literal values appear only for constant expressions.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

from .classify import FETCH_ERROR, GEN_ERROR, OK, SQL_OK, Case

F = 'FROM "DunderMifflin Sales" AS "t1"'
FX = 'FROM "Dunder Mifflin" AS "t1"'
SP, Q, D, CN, PN, UP, OID = ('"t1"."Salesperson"', '"t1"."Quantity"', '"t1"."Order Date"',
                             '"t1"."Customer Name"', '"t1"."Product Name"', '"t1"."Unit Price"',
                             '"t1"."Order ID"')
CTE_SP = f'WITH a AS (SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY {SP})'

NO = "❌ "
SILENT = "⚠️ "
FIXED = "✅ "


def _totals(results) -> dict:
    """Control: per-salesperson SUM(Quantity)."""
    return {r[0]: r[1] for r in results["ctl_totals_by_sp"]["fetch"]["rows"]}


def _check_round(rows, results):
    true = results["ctl_avg_unrounded"]["fetch"]["rows"][0][0]
    want = round(true, 2)
    return None if math.isclose(rows[0][0], want) else f"ROUND gave {rows[0][0]}, want {want} (true {true})"


def _check_times(factor, col):
    def check(rows, results):
        tot = _totals(results)
        bad = [r for r in rows if not math.isclose(r[col], tot[r[0]] * factor)]
        return f"{len(bad)} rows are not control x {factor}: {bad[:2]}" if bad else None
    return check


def _check_offset(rows, results):
    want = sorted(_totals(results).items(), key=lambda kv: -kv[1])[1:3]
    got = [tuple(r) for r in rows]
    return None if got == want else f"OFFSET 1 LIMIT 2 gave {got}, want ranks 2-3 {want}"


def _check_lag(rows, results):
    tot = sorted(_totals(results).items())
    want = {sp: (tot[i - 2][1] if i >= 2 else 0) for i, (sp, _) in enumerate(tot)}
    bad = [r for r in rows if r[1] != want[r[0]]]
    return f"LAG(x, 2, 0) wrong for {bad[:2]}" if bad else None


def _check_stddev(rows, results):
    want = statistics.stdev(_totals(results).values())
    got = rows[0][-1]
    return None if math.isclose(got, want, rel_tol=1e-9) else f"STDDEV gave {got}, hand-computed {want}"


def _check_having(rows, results):
    want = sorted((k, v) for k, v in _totals(results).items() if v > 1500)
    got = sorted(tuple(r) for r in rows)
    return None if got == want else f"rows {got} are not the control filtered > 1500 {want}"


def _check_union(rows, _results):
    got = sorted(r[0] for r in rows)
    return None if got == ["Andy Bernard", "Jim Halpert"] else f"union returned {got} — a branch was dropped?"


def _check_setop_order(rows, _results):
    qs = [r[1] for r in rows]
    if len(rows) != 3:
        return f"LIMIT 3 on a set op returned {len(rows)} rows"
    return None if qs == sorted(qs, reverse=True) else f"ORDER BY dropped: {qs}"


def _check_day_of_year(rows, _results):
    bad = []
    for epoch, doy, dom in rows:
        d = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).date()
        if (doy, dom) != (d.timetuple().tm_yday, d.day):
            bad.append((d.isoformat(), doy, dom))
    return f"DAY_IN_YEAR_NUMBER / DAY_NUMBER wrong for {bad}" if bad else None


CASES = [
    # ---- controls -------------------------------------------------------------------------
    Case("ctl_totals_by_sp", f'SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY {SP}', OK,
         "control", control=True),
    Case("ctl_avg_unrounded", f'SELECT AVG({UP}) AS r {F}', OK, "control", control=True),
    Case("ctl_sum_jim", f"SELECT SUM(CASE WHEN {SP} = 'Jim Halpert' THEN {Q} ELSE 0 END) AS q {F}",
         OK, "control", control=True),
    Case("ctl_year_ge_2025", f"SELECT SUM(CASE WHEN YEAR({D}) >= 2025 THEN {Q} ELSE 0 END) AS q {F}",
         OK, "control", control=True),
    Case("ctl_like_upper_a", f"SELECT SUM({Q}) AS q {F} WHERE {CN} LIKE 'A%'", OK, "control",
         control=True),
    Case("ctl_top1_per_sp",
         f'WITH r AS (SELECT {SP} AS sp, {CN} AS cn, SUM({Q}) AS q, ROW_NUMBER() OVER '
         f'(PARTITION BY {SP} ORDER BY SUM({Q}) DESC) AS rn {F} GROUP BY {SP}, {CN}) '
         'SELECT r.sp, r.cn, r.q FROM r WHERE r.rn = 1', OK, "control", control=True),
    Case("ctl_filter_eq", f"SELECT SUM({Q}) AS q {F} WHERE {SP} = 'Jim Halpert'", OK, "control",
         control=True),

    # ---- ❌ rejected at generate-sql ----------------------------------------------------------
    Case("self_join_cte", f'{CTE_SP} SELECT x.sp, y.q FROM a x JOIN a y ON x.sp = y.sp', GEN_ERROR,
         NO + "Self-join of a CTE", code="SELF_JOIN"),
    Case("non_equi_model_cte",
         f'{CTE_SP} SELECT {SP} AS sp, SUM({Q}) AS q {F} JOIN a ON {SP} = a.sp AND a.q > 1500 GROUP BY {SP}',
         GEN_ERROR, NO + "Non-equi JOIN (Model ⋈ CTE)", code="NON_EQUI_JOIN"),
    Case("non_equi_two_ctes",
         f'WITH a AS (SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY {SP}), b AS (SELECT {PN} AS pn, '
         f'SUM({Q}) AS q2 {F} GROUP BY {PN}) SELECT a.sp, b.pn FROM a JOIN b ON a.q > b.q2',
         GEN_ERROR, NO + "Non-equi JOIN (between two CTEs; misleading alias error)", code="QUERY_GEN_ERROR"),
    Case("from_subquery", f'SELECT s.sp, s.q FROM (SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY {SP}) AS s',
         GEN_ERROR, NO + "Subquery in FROM", code="TABLE_NOT_FOUND"),
    Case("stddev_grouped", f'SELECT {SP} AS sp, STDDEV_SAMP({Q}) AS s {F} GROUP BY {SP}', GEN_ERROR,
         NO + "STDDEV_* / VAR_* on a Model column", code="UNSUPPORTED_AGGREGATE"),
    Case("stddev_scalar", f'SELECT STDDEV_SAMP({Q}) AS s {F}', GEN_ERROR,
         NO + "STDDEV_* / VAR_* on a Model column", code="UNSUPPORTED_AGGREGATE"),
    Case("var_scalar", f'SELECT VAR_SAMP({Q}) AS v {F}', GEN_ERROR,
         NO + "STDDEV_* / VAR_* on a Model column", code="UNSUPPORTED_AGGREGATE"),
    Case("percentile_cont", f'SELECT PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY {Q}) AS p {F}', GEN_ERROR,
         NO + "Percentiles other than MEDIAN", code="UNSUPPORTED_AGGREGATE"),
    Case("approx_percentile", f'SELECT APPROX_PERCENTILE({Q}, 0.9) AS p {F}', GEN_ERROR,
         NO + "Percentiles other than MEDIAN", code="UNSUPPORTED_AGGREGATE"),
    Case("select_star", f'SELECT * {F}', GEN_ERROR, NO + "SELECT * · COUNT(*)", code="SELECT_STAR"),
    Case("count_star", f'SELECT COUNT(*) AS n {F}', GEN_ERROR, NO + "SELECT * · COUNT(*)", code="COUNT_STAR"),
    Case("sum_on_agg_formula",
         f'SELECT "t1"."Ship Country" AS c, SUM("t1"."Sales - Comparative") AS s {FX} GROUP BY "t1"."Ship Country"',
         GEN_ERROR, NO + "SUM() on an aggregate-formula column", model="multi",
         code="NESTED_AGGREGATE_NOT_SUPPORTED"),
    Case("rollup", f'SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY ROLLUP({SP})', GEN_ERROR,
         NO + "ROLLUP / CUBE / GROUPING SETS", code="QUERY_GEN_ERROR"),
    Case("initcap", f'SELECT INITCAP({CN}) AS x {F} GROUP BY INITCAP({CN})', GEN_ERROR,
         NO + "Unknown scalar functions", code="QUERY_GEN_ERROR"),
    Case("regexp_substr", f"SELECT REGEXP_SUBSTR({CN}, '[A-Z]+') AS x {F} GROUP BY REGEXP_SUBSTR({CN}, '[A-Z]+')",
         GEN_ERROR, NO + "Unknown scalar functions", code="QUERY_GEN_ERROR"),
    Case("to_varchar", f'SELECT TO_VARCHAR({Q}) AS x {F}', GEN_ERROR, NO + "Unknown scalar functions",
         code="QUERY_GEN_ERROR"),
    Case("regexp_replace", f"SELECT REGEXP_REPLACE({CN}, 'a', 'b') AS x {F} GROUP BY REGEXP_REPLACE({CN}, 'a', 'b')",
         GEN_ERROR, NO + "REGEXP_REPLACE", code="NO_BASE_TABLES_IN_QUERY_NOT_SUPPORTED"),
    Case("current_date", f'SELECT CURRENT_DATE AS x, SUM({Q}) AS q {F}', GEN_ERROR,
         NO + "CURRENT_DATE, NOW()", code="SQL_DATE_FUNCTION"),
    Case("log_two_arg", f'SELECT LOG(10, 100) AS l, SUM({Q}) AS q {F}', GEN_ERROR,
         NO + "LOG(base, x)", code="QUERY_GEN_ERROR"),
    Case("extract_dow", f'SELECT EXTRACT(DOW FROM {D}) AS x, SUM({Q}) AS q {F} GROUP BY EXTRACT(DOW FROM {D})',
         GEN_ERROR, NO + "EXTRACT(DOW …)", code="QUERY_GEN_ERROR"),
    Case("date_trunc_over_cte",
         f"WITH a AS (SELECT {D} AS od, SUM({Q}) AS q {F} GROUP BY {D}) SELECT DATE_TRUNC('month', a.od) AS m, "
         "SUM(a.q) AS q FROM a GROUP BY DATE_TRUNC('month', a.od)",
         GEN_ERROR, NO + "DATE_TRUNC · TRUNC (over a CTE column)", code="QUERY_GEN_ERROR"),
    Case("cast_fn_join_cte",
         f'{CTE_SP} SELECT CAST(LOWER({SP}) AS VARCHAR) AS l, SUM({Q}) AS q {F} JOIN a ON {SP} = a.sp '
         f'GROUP BY CAST(LOWER({SP}) AS VARCHAR)',
         GEN_ERROR, NO + "CAST(<function call>) in a block that joins a CTE", code="UNSUPPORTED_EXPRESSION"),
    Case("cast_extract_join_cte",
         f'{CTE_SP} SELECT CAST(EXTRACT(YEAR FROM {D}) AS INTEGER) AS y, SUM({Q}) AS q {F} JOIN a ON {SP} = a.sp '
         f'GROUP BY CAST(EXTRACT(YEAR FROM {D}) AS INTEGER)',
         GEN_ERROR, NO + "CAST(<function call>) in a block that joins a CTE", code="UNSUPPORTED_EXPRESSION"),
    Case("outer_agg_over_setop_cte",
         f"WITH u AS (SELECT {SP} AS sp, {Q} AS q {F} WHERE {SP} = 'Jim Halpert' UNION ALL SELECT {SP} AS sp, "
         f"{Q} AS q {F} WHERE {SP} = 'Andy Bernard') SELECT u.sp, SUM(u.q) AS q FROM u GROUP BY u.sp",
         GEN_ERROR, NO + "Outer aggregation over a set-operation CTE", code="10000"),

    # ---- ❌ compiles, then fails in the warehouse ----------------------------------------------
    Case("in_subquery",
         f'SELECT {SP} AS sp, SUM({Q}) AS q {F} WHERE {SP} IN (SELECT "t2"."Salesperson" FROM '
         f'"DunderMifflin Sales" AS "t2" WHERE "t2"."Quantity" > 40) GROUP BY {SP}',
         FETCH_ERROR, NO + "IN (SELECT …)", code="QUERY_EXECUTION_FAILED"),
    Case("day_of_year", f'SELECT DAY_OF_YEAR({D}) AS x, SUM({Q}) AS q {F} GROUP BY DAY_OF_YEAR({D})',
         FETCH_ERROR, NO + "DAY_OF_YEAR(x), EXTRACT(DOY …)", code="QUERY_EXECUTION_FAILED"),
    Case("extract_doy", f'SELECT EXTRACT(DOY FROM {D}) AS x, SUM({Q}) AS q {F} GROUP BY EXTRACT(DOY FROM {D})',
         FETCH_ERROR, NO + "DAY_OF_YEAR(x), EXTRACT(DOY …)", code="QUERY_EXECUTION_FAILED"),
    Case("trunc_date", f"SELECT TRUNC({D}, 'MONTH') AS x, SUM({Q}) AS q {F} GROUP BY TRUNC({D}, 'MONTH')",
         FETCH_ERROR, NO + "DATE_TRUNC · TRUNC", code="QUERY_EXECUTION_FAILED"),
    Case("date_trunc", f"SELECT DATE_TRUNC('month', {D}) AS m, SUM({Q}) AS q {F} GROUP BY DATE_TRUNC('month', {D})",
         FETCH_ERROR, NO + "DATE_TRUNC · TRUNC", code="QUERY_EXECUTION_FAILED"),
    Case("bitand", f'SELECT BITAND({Q}, 1) AS x {F}', FETCH_ERROR, NO + "Bitwise (BITAND, BIT_*)",
         code="QUERY_EXECUTION_FAILED"),
    Case("overlay", f"SELECT OVERLAY({SP} PLACING 'X' FROM 1 FOR 1) AS o {F} GROUP BY OVERLAY({SP} PLACING 'X' FROM 1 FOR 1)",
         FETCH_ERROR, NO + "OVERLAY(… PLACING …)", code="QUERY_EXECUTION_FAILED"),
    Case("ltrim_two_arg", f"SELECT LTRIM({SP}, 'D') AS x {F} GROUP BY LTRIM({SP}, 'D')", FETCH_ERROR,
         NO + "LTRIM(x, chars) / RTRIM(x, chars)", code="QUERY_EXECUTION_FAILED"),
    Case("regex_tilde", f"SELECT {SP} AS s {F} WHERE {SP} ~ '^J' GROUP BY {SP}", FETCH_ERROR,
         NO + "REGEXP_LIKE / ~ / !~", code="QUERY_EXECUTION_FAILED", sql_has=("like_regex",)),
    Case("regex_not_tilde", f"SELECT {SP} AS s {F} WHERE {SP} !~ '^J' GROUP BY {SP}", FETCH_ERROR,
         NO + "REGEXP_LIKE / ~ / !~", code="QUERY_EXECUTION_FAILED", sql_has=("like_regex",)),
    Case("regexp_like", f"SELECT {SP} AS s {F} WHERE REGEXP_LIKE({SP}, '^J.*') GROUP BY {SP}", FETCH_ERROR,
         NO + "REGEXP_LIKE / ~ / !~", code="QUERY_EXECUTION_FAILED", sql_has=("like_regex",)),
    Case("setop_type_mismatch", f'SELECT {SP} AS x {F} GROUP BY {SP} UNION ALL SELECT SUM({Q}) AS x {F}',
         FETCH_ERROR, SILENT + "Set-operation branches with mismatched column types",
         code="QUERY_EXECUTION_FAILED"),

    # ---- ⚠️ SUCCESS with the wrong answer -------------------------------------------------------
    Case("where_aggregate", f'SELECT {SP} AS sp, SUM({Q}) AS q {F} WHERE SUM({Q}) > 1500 GROUP BY {SP}', OK,
         SILENT + "Aggregate condition in WHERE (reinterpreted as HAVING)", sql_has=("having",),
         check=_check_having),
    Case("qualify",
         f'SELECT {SP} AS sp, {CN} AS cn, SUM({Q}) AS q {F} GROUP BY {SP}, {CN} QUALIFY ROW_NUMBER() OVER '
         f'(PARTITION BY {SP} ORDER BY SUM({Q}) DESC) = 1',
         OK, SILENT + "QUALIFY …", sql_lacks=("row_number",), differs_from="ctl_top1_per_sp"),
    Case("filter_where", f"SELECT SUM({Q}) FILTER (WHERE {SP} = 'Jim Halpert') AS q {F}", OK,
         SILENT + "FILTER (WHERE …) on an aggregate", differs_from="ctl_sum_jim"),
    Case("sum_case_date_literal", f"SELECT SUM(CASE WHEN {D} >= '2025-01-01' THEN {Q} ELSE 0 END) AS q {F}", OK,
         SILENT + "SUM(CASE WHEN <raw-date >= literal> …)", differs_from="ctl_year_ge_2025"),
    Case("limit_default_cap", f'SELECT {OID} AS o {F}', SQL_OK, SILENT + "LIMIT n with n > 100,000",
         sql_has=("limit 100000",)),
    Case("limit_over_cap", f'SELECT {OID} AS o {F} LIMIT 200000', SQL_OK, SILENT + "LIMIT n with n > 100,000",
         sql_has=("limit 100000",), sql_lacks=("limit 200000",)),
    Case("log_one_arg", f'SELECT LOG(100) AS l, SUM({Q}) AS q {F}', OK,
         SILENT + "LOG(x) (one-argument) is the natural log", values=((0, 0, math.log(100)),)),

    # ---- ✅ fixed — guard against regression ------------------------------------------------------
    Case("union_both_branches",
         f"SELECT {SP} AS sp {F} WHERE {SP} = 'Jim Halpert' GROUP BY {SP} UNION ALL SELECT {SP} AS sp {F} "
         f"WHERE {SP} = 'Andy Bernard' GROUP BY {SP}", OK, FIXED + "UNION ALL / UNION / … at top level",
         check=_check_union),
    Case("setop_order_limit",
         f"SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY {SP} UNION SELECT {CN} AS sp, SUM({Q}) AS q {F} "
         f"GROUP BY {CN} ORDER BY q DESC LIMIT 3", OK, FIXED + "ORDER BY / LIMIT on a set-operator result",
         check=_check_setop_order),
    Case("round", f'SELECT ROUND(AVG({UP}), 2) AS r {F}', OK, FIXED + "ROUND(x, N)", check=_check_round),
    # TO_NUMBER is typed by its input: a string is CAST to double, a number is not cast at all
    Case("to_number_int_col", f'SELECT TO_NUMBER({Q}) AS x {F} LIMIT 2', OK, FIXED + "TO_NUMBER(x)",
         sql_has=("round(",), sql_lacks=("as double",)),
    Case("to_number_decimal_col", f'SELECT TO_NUMBER({UP}) AS x {F} LIMIT 2', OK, FIXED + "TO_NUMBER(x)",
         sql_lacks=("as double", "round(")),
    Case("to_number_string_literal", f"SELECT TO_NUMBER('12.75') AS x, SUM({Q}) AS q {F}", OK,
         FIXED + "TO_NUMBER(x)", sql_has=("as double",), values=((0, 0, 12.75),)),
    Case("to_number_string_col", f'SELECT TO_NUMBER({SP}) AS x {F} LIMIT 2', FETCH_ERROR,
         FIXED + "TO_NUMBER(x) (hard error on non-numeric data)", code="QUERY_EXECUTION_FAILED",
         sql_has=("as double",)),
    Case("concat_ws",
         f"SELECT CONCAT_WS('-', {SP}, {PN}) AS x {F} GROUP BY CONCAT_WS('-', {SP}, {PN}) LIMIT 2", OK,
         FIXED + "CONCAT_WS · LENGTH()"),
    Case("length", f'SELECT LENGTH({SP}) AS l, SUM({Q}) AS q {F} GROUP BY LENGTH({SP})', OK,
         FIXED + "CONCAT_WS · LENGTH()"),
    Case("median_grouped", f'SELECT {SP} AS sp, MEDIAN({Q}) AS m {F} GROUP BY {SP}', OK,
         FIXED + "MEDIAN in a GROUP BY query"),
    Case("median_scalar", f'SELECT MEDIAN({Q}) AS m {F}', OK, FIXED + "MEDIAN in a GROUP BY query"),
    Case("stddev_over_cte", f'{CTE_SP} SELECT STDDEV_SAMP(a.q) AS s FROM a', OK,
         FIXED + "STDDEV over a CTE column (the documented workaround)", check=_check_stddev),
    Case("stddev_window",
         f'SELECT {SP} AS sp, SUM({Q}) AS q, STDDEV_SAMP(SUM({Q})) OVER () AS s {F} GROUP BY {SP}', OK,
         FIXED + "STDDEV window form (the documented workaround)", check=_check_stddev),
    Case("framed_window_only",
         f'SELECT {D} AS d, SUM({Q}) OVER (ORDER BY {D} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS w {F}', OK,
         FIXED + "A query whose only window function is framed"),
    Case("offset", f'SELECT {SP} AS sp, SUM({Q}) AS q {F} GROUP BY {SP} ORDER BY q DESC LIMIT 2 OFFSET 1', OK,
         FIXED + "LIMIT n OFFSET m", check=_check_offset),
    Case("decimal_literal", f'SELECT {SP} AS sp, SUM({Q}) * 1.25 AS q {F} GROUP BY {SP}', OK,
         FIXED + "Decimal literals in arithmetic", check=_check_times(1.25, 1)),
    Case("greatest_varargs", f'SELECT GREATEST({Q}, {UP}, 5) AS g {F} LIMIT 3', OK,
         FIXED + "GREATEST / LEAST with 3+ arguments", sql_has=("greatest(",)),
    Case("constant_label", f"SELECT 'x' AS lbl, SUM({Q}) AS q {F}", OK,
         FIXED + "Selecting a constant as a label", values=((0, 0, "x"),)),
    Case("ntile", f'SELECT {SP} AS sp, NTILE(2) OVER (ORDER BY SUM({Q})) AS t {F} GROUP BY {SP}', OK,
         FIXED + "NTILE(n)", sql_lacks=("$tiles",)),
    Case("lag_optional_args",
         f'SELECT {SP} AS sp, LAG(SUM({Q}), 2, 0) OVER (ORDER BY {SP}) AS l {F} GROUP BY {SP}', OK,
         FIXED + "LAG(x, N, default) / LEAD(x, N)", check=_check_lag),
    Case("multi_cte_join",
         f'{CTE_SP}, b AS (SELECT {SP} AS sp, COUNT({OID}) AS n {F} GROUP BY {SP}) SELECT a.sp, a.q, b.n '
         'FROM a JOIN b ON a.sp = b.sp', OK, FIXED + "Joining two or more model-derived CTEs",
         check=_check_times(1, 1)),
    Case("cte_from_cte", f'{CTE_SP}, b AS (SELECT a.sp, a.q * 2 AS q2 FROM a) SELECT b.sp, b.q2 FROM b', OK,
         FIXED + "CTE selecting FROM an earlier CTE", check=_check_times(2, 1)),
    Case("case_in_group_by",
         f"SELECT CASE WHEN {Q} > 20 THEN 'big' ELSE 'small' END AS b, SUM({Q}) AS q {F} "
         f"GROUP BY CASE WHEN {Q} > 20 THEN 'big' ELSE 'small' END", OK, FIXED + "CASE expression in GROUP BY"),
    Case("mixed_quote_literal", f"SELECT SUM({Q}) AS q {F} WHERE {CN} <> 'O''Brien \"x\"'", OK,
         FIXED + "String literal containing both ' and \""),
    Case("cast_literal", f"SELECT CAST('1' AS INTEGER) AS x, SUM({Q}) AS q {F}", OK,
         FIXED + "CAST(<literal> AS <type>)", values=((0, 0, 1),)),
    Case("const_exp", f'SELECT EXP(1) AS x, SUM({Q}) AS q {F}', OK, FIXED + "Constant-only scalar functions",
         values=((0, 0, math.e),)),
    Case("const_acos", f'SELECT ACOS(1) AS a, SUM({Q}) AS q {F}', OK, FIXED + "Constant-only scalar functions",
         values=((0, 0, 0.0),)),
    Case("const_chr_space", f"SELECT CHR(65) AS c, SPACE(2) AS s, SUM({Q}) AS q {F}", OK,
         FIXED + "Constant-only scalar functions", values=((0, 0, "A"), (0, 1, "  "))),
    Case("to_date_literal", f"SELECT SUM({Q}) AS q {F} WHERE {D} >= TO_DATE('2025-01-01')", OK,
         FIXED + "TO_DATE('<literal>') in a filter", same_as="ctl_year_ge_2025"),
    Case("cte_agg_unreferenced_col",
         f'WITH a AS (SELECT {SP} AS sp {F} GROUP BY {SP} HAVING COUNT({CN}) > 0) SELECT a.sp FROM a', OK,
         FIXED + "Aggregate over a column a CTE does not otherwise reference"),
    Case("cast_col_fn_join_cte",
         f'{CTE_SP} SELECT CAST(ABS({Q}) AS INTEGER) AS l, SUM({Q}) AS q {F} JOIN a ON {SP} = a.sp '
         f'GROUP BY CAST(ABS({Q}) AS INTEGER)', OK,
         FIXED + "CAST of a numeric function joined to a CTE (the ❌ CAST row's boundary)"),
    Case("agg_on_agg_formula",
         f'SELECT "t1"."Ship Country" AS c, AGG("t1"."Sales - Comparative") AS s {FX} GROUP BY "t1"."Ship Country"',
         OK, FIXED + "AGG() on an aggregate-formula column (the documented form)", model="multi"),
    Case("count_distinct_plus_measure",
         f'SELECT {SP} AS sp, COUNT(DISTINCT {CN}) AS c, SUM({Q}) AS q {F} GROUP BY {SP}', OK,
         FIXED + "Raw COUNT(DISTINCT x) alongside SUM(y)", check=_check_times(1, 2)),
    Case("day_in_year_number",
         f'SELECT {D} AS d, DAY_IN_YEAR_NUMBER({D}) AS doy, DAY_NUMBER({D}) AS dn {F} '
         f'GROUP BY {D}, DAY_IN_YEAR_NUMBER({D}), DAY_NUMBER({D}) ORDER BY {D} LIMIT 3', OK,
         FIXED + "DAY_IN_YEAR_NUMBER (the DAY_OF_YEAR workaround)", check=_check_day_of_year),
    Case("ilike", f"SELECT SUM({Q}) AS q {F} WHERE {CN} ILIKE 'a%'", OK, FIXED + "ILIKE",
         same_as="ctl_like_upper_a"),

    # ---- string comparisons are case-insensitive (agentql-rules.md § Filters) ---------------------
    Case("filter_eq_lower", f"SELECT SUM({Q}) AS q {F} WHERE {SP} = 'jim halpert'", OK,
         FIXED + "String = / IN are case-insensitive", sql_has=("lower(",), same_as="ctl_filter_eq"),
    Case("filter_in_upper", f"SELECT SUM({Q}) AS q {F} WHERE {SP} IN ('JIM HALPERT')", OK,
         FIXED + "String = / IN are case-insensitive", same_as="ctl_filter_eq"),
]
