"""Tests for ts_cli.sv_sql — Snowflake SQL expression -> ThoughtSpot formula.

Tests the SQL-level translator in isolation: function mapping, identifier
resolution, construct handling. Orchestrator-level concerns (column
classification, semi-additive wrapping, window pre-splitting) are in
test_sv_translate.py.
"""
from __future__ import annotations

import pytest

from ts_cli.formula_common import UntranslatableError
from ts_cli.sv_sql import tokenize, translate_sql_expr


def _resolve(ident: str) -> str:
    """Test resolver: alias.COL -> [ALIAS::COL], bare -> [_::COL]."""
    parts = ident.split(".")
    if len(parts) == 2:
        return f"[{parts[0].upper()}::{parts[1]}]"
    return f"[_::{parts[0]}]"


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class TestTokenizer:
    def test_simple_tokens(self):
        toks = tokenize("SUM(a.COL)")
        assert toks == [("ident", "SUM"), ("op", "("),
                        ("ident", "a.COL"), ("op", ")")]

    def test_string_literal(self):
        toks = tokenize("'hello'")
        assert toks == [("string", "'hello'")]

    def test_keywords(self):
        toks = tokenize("CASE WHEN x THEN 1 ELSE 0 END")
        assert ("kw", "CASE") in toks
        assert ("kw", "WHEN") in toks

    def test_operators(self):
        toks = tokenize("a >= b AND c <> d")
        assert ("op", ">=") in toks
        assert ("op", "<>") in toks


# ---------------------------------------------------------------------------
# Simple renames (aggregates, math, string, date)
# ---------------------------------------------------------------------------

class TestSimpleRenames:
    def test_sum(self):
        assert translate_sql_expr("SUM(a.COL)", _resolve) == \
            "sum ( [A::COL] )"

    def test_count(self):
        assert translate_sql_expr("COUNT(a.COL)", _resolve) == \
            "count ( [A::COL] )"

    def test_count_star(self):
        assert translate_sql_expr("COUNT(*)", _resolve) == \
            "count ( 1 )"

    def test_count_distinct(self):
        assert translate_sql_expr("COUNT(DISTINCT a.COL)", _resolve) == \
            "unique count ( [A::COL] )"

    def test_avg(self):
        assert translate_sql_expr("AVG(a.COL)", _resolve) == \
            "average ( [A::COL] )"

    def test_min_max(self):
        assert translate_sql_expr("MIN(a.X)", _resolve) == "min ( [A::X] )"
        assert translate_sql_expr("MAX(a.X)", _resolve) == "max ( [A::X] )"

    def test_strlen(self):
        assert translate_sql_expr("LENGTH(a.NAME)", _resolve) == \
            "strlen ( [A::NAME] )"

    def test_concat(self):
        result = translate_sql_expr("CONCAT(a.FIRST, a.LAST)", _resolve)
        assert result == "concat ( [A::FIRST] , [A::LAST] )"

    def test_contains(self):
        result = translate_sql_expr("CONTAINS(a.NAME, 'test')", _resolve)
        assert result == "contains ( [A::NAME] , 'test' )"

    def test_starts_with(self):
        result = translate_sql_expr("STARTSWITH(a.NAME, 'A')", _resolve)
        assert result == "starts_with ( [A::NAME] , 'A' )"

    def test_round(self):
        result = translate_sql_expr("ROUND(a.VAL, 2)", _resolve)
        assert result == "round ( [A::VAL] , 2 )"

    def test_abs(self):
        assert translate_sql_expr("ABS(a.X)", _resolve) == "abs ( [A::X] )"

    def test_greatest_least(self):
        assert translate_sql_expr("GREATEST(a.X, a.Y)", _resolve) == \
            "greatest ( [A::X] , [A::Y] )"
        assert translate_sql_expr("LEAST(a.X, a.Y)", _resolve) == \
            "least ( [A::X] , [A::Y] )"

    def test_power(self):
        assert translate_sql_expr("POWER(a.X, 2)", _resolve) == \
            "pow ( [A::X] , 2 )"

    def test_year(self):
        assert translate_sql_expr("YEAR(a.D)", _resolve) == \
            "year ( [A::D] )"

    def test_ifnull(self):
        assert translate_sql_expr("IFNULL(a.X, 0)", _resolve) == \
            "ifnull ( [A::X] , 0 )"

    def test_nvl(self):
        assert translate_sql_expr("NVL(a.X, 0)", _resolve) == \
            "ifnull ( [A::X] , 0 )"

    def test_median(self):
        assert translate_sql_expr("MEDIAN(a.X)", _resolve) == \
            "median ( [A::X] )"


# ---------------------------------------------------------------------------
# Special function handlers
# ---------------------------------------------------------------------------

class TestSpecialFunctions:
    def test_datediff_day(self):
        result = translate_sql_expr(
            "DATEDIFF(day, a.START, a.END)", _resolve)
        assert result == "diff_days ( [A::END] , [A::START] )"

    def test_datediff_month(self):
        result = translate_sql_expr(
            "DATEDIFF(month, a.HIRE, CURRENT_DATE())", _resolve)
        assert result == "diff_months ( today ( ) , [A::HIRE] )"

    def test_datediff_year(self):
        result = translate_sql_expr(
            "DATEDIFF(year, a.START, a.END)", _resolve)
        assert result == "( diff_days ( [A::END] , [A::START] ) / 365 )"

    def test_datediff_second(self):
        result = translate_sql_expr(
            "DATEDIFF(second, a.T1, a.T2)", _resolve)
        assert result == "diff_time ( [A::T2] , [A::T1] )"

    def test_dateadd_day(self):
        result = translate_sql_expr(
            "DATEADD(day, 7, a.D)", _resolve)
        assert result == "add_days ( [A::D] , 7 )"

    def test_dateadd_month(self):
        result = translate_sql_expr(
            "DATEADD(month, 1, a.D)", _resolve)
        assert result == "add_months ( [A::D] , 1 )"

    def test_dateadd_week(self):
        result = translate_sql_expr(
            "DATEADD(week, 2, a.D)", _resolve)
        assert result == "add_days ( [A::D] , ( 2 * 7 ) )"

    def test_dateadd_year(self):
        result = translate_sql_expr(
            "DATEADD(year, 1, a.D)", _resolve)
        assert result == "add_months ( [A::D] , ( 1 * 12 ) )"

    def test_extract(self):
        result = translate_sql_expr(
            "EXTRACT(MONTH FROM a.D)", _resolve)
        assert result == "month_number ( [A::D] )"

    def test_extract_quarter(self):
        result = translate_sql_expr(
            "EXTRACT(QUARTER FROM a.D)", _resolve)
        assert result == "quarter_number ( [A::D] )"

    def test_iff(self):
        result = translate_sql_expr(
            "IFF(a.X > 0, 'positive', 'non-positive')", _resolve)
        assert result == \
            "if ( [A::X] > 0 ) then 'positive' else 'non-positive'"

    def test_div0(self):
        result = translate_sql_expr("DIV0(a.X, a.Y)", _resolve)
        assert result == "safe_divide ( [A::X] , [A::Y] )"

    def test_count_if(self):
        result = translate_sql_expr("COUNT_IF(a.FLAG)", _resolve)
        assert result == "sum ( if ( [A::FLAG] ) then 1 else 0 )"

    def test_position(self):
        result = translate_sql_expr(
            "POSITION('x' IN a.NAME)", _resolve)
        assert result == "strpos ( [A::NAME] , 'x' )"

    def test_to_char(self):
        result = translate_sql_expr("TO_CHAR(a.X)", _resolve)
        assert result == "to_string ( [A::X] )"

    def test_to_number(self):
        result = translate_sql_expr("TO_NUMBER(a.X)", _resolve)
        assert result == "to_double ( [A::X] )"

    def test_log_base2(self):
        result = translate_sql_expr("LOG(2, a.X)", _resolve)
        assert result == "log2 ( [A::X] )"

    def test_log_base10(self):
        result = translate_sql_expr("LOG(10, a.X)", _resolve)
        assert result == "log10 ( [A::X] )"

    def test_log_natural(self):
        result = translate_sql_expr("LOG(a.X)", _resolve)
        assert result == "ln ( [A::X] )"

    def test_nvl2(self):
        result = translate_sql_expr(
            "NVL2(a.X, a.Y, a.Z)", _resolve)
        assert result == \
            "if ( [A::X] != null ) then [A::Y] else [A::Z]"

    def test_trunc(self):
        result = translate_sql_expr("TRUNC(a.X, 0)", _resolve)
        assert result == "round ( [A::X] , 0 )"

    def test_date_trunc_month(self):
        result = translate_sql_expr(
            "DATE_TRUNC('month', a.D)", _resolve)
        assert result == "start_of_month ( [A::D] )"

    def test_date_trunc_year(self):
        result = translate_sql_expr(
            "DATE_TRUNC('year', a.D)", _resolve)
        assert result == "start_of_year ( [A::D] )"

    def test_months_between(self):
        result = translate_sql_expr(
            "MONTHS_BETWEEN(a.END, a.START)", _resolve)
        assert result == "diff_months ( [A::START] , [A::END] )"

    def test_current_date(self):
        assert translate_sql_expr("CURRENT_DATE()", _resolve) == "today ( )"
        assert translate_sql_expr("CURRENT_DATE", _resolve) == "today ( )"

    def test_current_timestamp(self):
        assert translate_sql_expr("CURRENT_TIMESTAMP()", _resolve) == "now ( )"
        assert translate_sql_expr("CURRENT_TIMESTAMP", _resolve) == "now ( )"


# ---------------------------------------------------------------------------
# CAST / TRY_CAST
# ---------------------------------------------------------------------------

class TestCast:
    def test_cast_integer(self):
        result = translate_sql_expr("CAST(a.X AS INTEGER)", _resolve)
        assert result == "to_integer ( [A::X] )"

    def test_cast_varchar(self):
        result = translate_sql_expr("CAST(a.X AS VARCHAR)", _resolve)
        assert result == "to_string ( [A::X] )"

    def test_cast_float(self):
        result = translate_sql_expr("CAST(a.X AS FLOAT)", _resolve)
        assert result == "to_double ( [A::X] )"

    def test_try_cast(self):
        result = translate_sql_expr("TRY_CAST(a.X AS INTEGER)", _resolve)
        assert result == "to_integer ( [A::X] )"

    def test_cast_decimal_precision(self):
        result = translate_sql_expr("CAST(a.X AS DECIMAL(10,2))", _resolve)
        assert result == "to_double ( [A::X] )"


# ---------------------------------------------------------------------------
# CASE / WHEN
# ---------------------------------------------------------------------------

class TestCase:
    def test_simple_case(self):
        result = translate_sql_expr(
            "CASE WHEN a.X > 10 THEN 'high' ELSE 'low' END", _resolve)
        assert result == "if ( [A::X] > 10 ) then 'high' else 'low'"

    def test_multi_branch(self):
        result = translate_sql_expr(
            "CASE WHEN a.X >= 90 THEN 'A' "
            "WHEN a.X >= 80 THEN 'B' "
            "ELSE 'C' END", _resolve)
        assert "if ( [A::X] >= 90 ) then 'A'" in result
        assert "if ( [A::X] >= 80 ) then 'B'" in result
        assert "else 'C'" in result

    def test_no_else(self):
        result = translate_sql_expr(
            "CASE WHEN a.X = 1 THEN 'one' END", _resolve)
        assert result == "if ( [A::X] = 1 ) then 'one' else null"


# ---------------------------------------------------------------------------
# IS NULL / IS NOT NULL / NOT / IN / BETWEEN
# ---------------------------------------------------------------------------

class TestConstructs:
    def test_is_null(self):
        result = translate_sql_expr("a.X IS NULL", _resolve)
        assert result == "isnull ( [A::X] )"

    def test_is_not_null(self):
        result = translate_sql_expr("a.X IS NOT NULL", _resolve)
        assert result == "not ( isnull ( [A::X] ) )"

    def test_in(self):
        result = translate_sql_expr("a.X IN (1, 2, 3)", _resolve)
        assert "or" in result
        assert "[A::X] = 1" in result
        assert "[A::X] = 2" in result
        assert "[A::X] = 3" in result

    def test_between(self):
        result = translate_sql_expr(
            "a.X BETWEEN 1 AND 10", _resolve)
        assert "[A::X] >= 1" in result
        assert "[A::X] <= 10" in result

    def test_and_or(self):
        result = translate_sql_expr(
            "a.X > 0 AND a.Y < 100", _resolve)
        assert result == "[A::X] > 0 and [A::Y] < 100"


# ---------------------------------------------------------------------------
# Pass-through (sql_*_op)
# ---------------------------------------------------------------------------

class TestPassThrough:
    def test_upper(self):
        result = translate_sql_expr("UPPER(a.NAME)", _resolve)
        assert result == 'sql_string_op ( "UPPER({0})" , [A::NAME] )'

    def test_lower(self):
        result = translate_sql_expr("LOWER(a.NAME)", _resolve)
        assert result == 'sql_string_op ( "LOWER({0})" , [A::NAME] )'


# ---------------------------------------------------------------------------
# NULLIF / safe_divide
# ---------------------------------------------------------------------------

class TestNullif:
    def test_nullif_zero_division(self):
        result = translate_sql_expr("a.X / NULLIF(a.Y, 0)", _resolve)
        assert result == "safe_divide ( [A::X] , [A::Y] )"

    def test_nullif_non_zero(self):
        result = translate_sql_expr("NULLIF(a.X, a.Y)", _resolve)
        assert result == "nullif ( [A::X] , [A::Y] )"


# ---------------------------------------------------------------------------
# COALESCE
# ---------------------------------------------------------------------------

class TestCoalesce:
    def test_two_args(self):
        result = translate_sql_expr("COALESCE(a.X, 0)", _resolve)
        assert result == "if ( [A::X] != null ) then [A::X] else 0"

    def test_three_args(self):
        result = translate_sql_expr("COALESCE(a.X, a.Y, 0)", _resolve)
        assert "if ( [A::X] != null )" in result
        assert "if ( [A::Y] != null )" in result


# ---------------------------------------------------------------------------
# Identifier resolution
# ---------------------------------------------------------------------------

class TestIdentResolution:
    def test_bare_ident(self):
        result = translate_sql_expr("SUM(COL)", _resolve)
        assert result == "sum ( [_::COL] )"

    def test_qualified_ident(self):
        result = translate_sql_expr("SUM(emp.SALARY)", _resolve)
        assert result == "sum ( [EMP::SALARY] )"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_over_raises(self):
        with pytest.raises(UntranslatableError, match="OVER"):
            translate_sql_expr(
                "SUM(a.X) OVER (PARTITION BY a.Y)", _resolve)

    def test_unknown_function(self):
        with pytest.raises(UntranslatableError, match="UNKNOWN_FN"):
            translate_sql_expr("UNKNOWN_FN(a.X)", _resolve)

    def test_concat_operator(self):
        with pytest.raises(UntranslatableError, match="\\|\\|"):
            translate_sql_expr("a.X || a.Y", _resolve)

    def test_empty_expression(self):
        with pytest.raises(UntranslatableError, match="empty"):
            translate_sql_expr("", _resolve)


# ---------------------------------------------------------------------------
# Complex expressions
# ---------------------------------------------------------------------------

class TestComplex:
    def test_arithmetic(self):
        result = translate_sql_expr("a.X + a.Y * 2", _resolve)
        assert result == "[A::X] + [A::Y] * 2"

    def test_nested_functions(self):
        result = translate_sql_expr(
            "ROUND(SUM(a.X) / COUNT(a.Y), 2)", _resolve)
        assert "round" in result
        assert "sum" in result
        assert "count" in result

    def test_case_with_agg(self):
        result = translate_sql_expr(
            "SUM(CASE WHEN a.STATUS = 'Active' THEN a.SALARY ELSE 0 END)",
            _resolve)
        assert "sum" in result
        assert "if ( [A::STATUS] = 'Active' )" in result

    def test_string_with_escaped_quotes(self):
        result = translate_sql_expr("a.X = 'it''s'", _resolve)
        assert "'it''s'" in result
