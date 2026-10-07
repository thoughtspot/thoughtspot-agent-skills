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
        # BL-171: `starts_with` is NOT a ThoughtSpot function (live-verified
        # 2026-07-29 + 2026-07-30, se-thoughtspot) — compose from strpos.
        result = translate_sql_expr("STARTSWITH(a.NAME, 'A')", _resolve)
        assert result == "( strpos ( [A::NAME] , 'A' ) = 1 )"

    def test_round(self):
        # BL-331: TS round()'s 2nd arg is an increment — 2 digits -> 0.01.
        result = translate_sql_expr("ROUND(a.VAL, 2)", _resolve)
        assert result == "round ( [A::VAL] , 0.01 )"

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
# BL-171 — string functions that do NOT exist in ThoughtSpot
#
# `trim`, `ltrim`, `rtrim`, `replace`, `starts_with` and `ends_with` are all
# absent from the ThoughtSpot formula parser (live-verified 2026-07-29 and
# re-verified 2026-07-30 on se-thoughtspot; each is rejected with
# `Search did not find "<fn> ("`, error_code 14516). The replacement forms
# below are the rows in ts-snowflake-formula-translation.md (String
# Functions) and were each verified to import in the same probe pass.
# ---------------------------------------------------------------------------

_NON_EXISTENT = ("trim (", "ltrim (", "rtrim (", "replace (",
                 "starts_with (", "ends_with (")


class TestNonExistentStringFunctions:
    def test_trim_pass_through(self):
        assert translate_sql_expr("TRIM(a.NAME)", _resolve) == \
            'sql_string_op ( "TRIM({0})" , [A::NAME] )'

    def test_ltrim_pass_through(self):
        assert translate_sql_expr("LTRIM(a.NAME)", _resolve) == \
            'sql_string_op ( "LTRIM({0})" , [A::NAME] )'

    def test_rtrim_pass_through(self):
        assert translate_sql_expr("RTRIM(a.NAME)", _resolve) == \
            'sql_string_op ( "RTRIM({0})" , [A::NAME] )'

    def test_replace_pass_through(self):
        assert translate_sql_expr("REPLACE(a.NAME, 'a', 'b')", _resolve) == \
            'sql_string_op ( "REPLACE({0}, {1}, {2})" , [A::NAME] , ' \
            "'a' , 'b' )"

    def test_ends_with_composition(self):
        assert translate_sql_expr("ENDSWITH(a.NAME, 'Z')", _resolve) == (
            "( substr ( [A::NAME] , strlen ( [A::NAME] ) - strlen ( 'Z' ) "
            ", strlen ( 'Z' ) ) = 'Z' )")

    def test_no_bare_non_existent_name_is_ever_emitted(self):
        """The whole point of BL-171: no source function may translate to one
        of the six bare names, which fail at import (error 14516)."""
        sources = [
            "TRIM(a.NAME)", "LTRIM(a.NAME)", "RTRIM(a.NAME)",
            "REPLACE(a.NAME, 'a', 'b')", "STARTSWITH(a.NAME, 'A')",
            "ENDSWITH(a.NAME, 'Z')",
            "UPPER(TRIM(a.NAME))", "CONCAT(TRIM(a.FIRST), a.LAST)",
        ]
        for src in sources:
            out = translate_sql_expr(src, _resolve)
            for bad in _NON_EXISTENT:
                assert bad not in out, f"{src} -> {out} emits {bad!r}"

    def test_two_arg_trim_is_flagged_not_narrowed(self):
        """Snowflake TRIM(x, chars) has no 1-slot pass-through: emitting
        TRIM({0}) would silently drop the character set. Flag, don't narrow."""
        for src in ("TRIM(a.NAME, ' ')", "LTRIM(a.NAME, 'x')",
                    "RTRIM(a.NAME, 'x')"):
            with pytest.raises(UntranslatableError, match="expects 1 argument"):
                translate_sql_expr(src, _resolve)

    def test_nested_trim_inside_upper(self):
        assert translate_sql_expr("UPPER(TRIM(a.NAME))", _resolve) == (
            'sql_string_op ( "UPPER({0})" , '
            'sql_string_op ( "TRIM({0})" , [A::NAME] ) )')


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
        # BL-341: was ( diff_days ( … ) / 365 ), a fractional day count.
        assert result == "diff_years ( [A::END] , [A::START] )"

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
        # BL-357: DIV0(NULL, 0) is NULL in Snowflake, safe_divide's 0 — so the NULL guard
        result = translate_sql_expr("DIV0(a.X, a.Y)", _resolve)
        assert result == ("( if ( isnull ( [A::X] ) ) then null else "
                          "safe_divide ( [A::X] , [A::Y] ) )")
        assert translate_sql_expr("DIV0NULL(a.X, a.Y)", _resolve) == (
            "( if ( isnull ( [A::X] ) ) then null else "
            "safe_divide ( [A::X] , ifnull ( [A::Y] , 0 ) ) )")

    def test_count_if(self):
        result = translate_sql_expr("COUNT_IF(a.FLAG)", _resolve)
        assert result == "sum ( if ( [A::FLAG] ) then 1 else 0 )"

    def test_position(self):
        result = translate_sql_expr(
            "POSITION('x' IN a.NAME)", _resolve)
        assert result == "strpos ( [A::NAME] , 'x' )"

    def test_to_char(self):
        # BL-343: one-argument to_string is rejected on a DATE and on Text.
        result = translate_sql_expr("TO_CHAR(a.X)", _resolve)
        assert result == 'sql_string_op ( "TO_CHAR({0})" , [A::X] )'

    def test_to_number(self):
        # BL-359: Snowflake's default scale is 0 and TO_NUMBER rounds (TO_NUMBER('2.5') = 3)
        result = translate_sql_expr("TO_NUMBER(a.X)", _resolve)
        assert result == "to_integer ( [A::X] )"
        assert translate_sql_expr("TO_DECIMAL(a.X, 10, 2)", _resolve) == \
            'sql_double_op ( "TO_DECIMAL({0}, 10, 2)" , [A::X] )'
        assert translate_sql_expr("TO_NUMBER(a.X, 38, 0)", _resolve) == "to_integer ( [A::X] )"
        assert translate_sql_expr("TO_NUMBER(a.X, '999.99')", _resolve) == \
            'sql_double_op ( "TO_NUMBER({0}, \'999.99\')" , [A::X] )'

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
        # BL-331: was round(x, 0) — which rounds, and is NULL in ThoughtSpot.
        result = translate_sql_expr("TRUNC(a.X, 0)", _resolve)
        assert result == 'sql_double_op ( "TRUNC({0}, 0)" , [A::X] )'

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
        # BL-336: positive when d1 is later — source order kept. BL-342: fractional,
        # so an exact pass-through, never diff_months (a boundary count).
        assert result == \
            'sql_double_op ( "MONTHS_BETWEEN({0}, {1})" , [A::END] , [A::START] )'

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
        # BL-359: a NUMBER/DECIMAL cast ROUNDS to its scale in Snowflake (2.567 -> 2.57);
        # to_double kept every digit
        result = translate_sql_expr("CAST(a.X AS DECIMAL(10,2))", _resolve)
        assert result == 'sql_double_op ( "CAST({0} AS DECIMAL(10,2))" , [A::X] )'
        assert translate_sql_expr("CAST(a.X AS NUMBER)", _resolve) == "to_integer ( [A::X] )"
        assert translate_sql_expr("CAST(SUM(a.X) AS NUMBER(18,2))", _resolve) == \
            "round ( sum ( [A::X] ) , 0.01 )"


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
        # BL-357: NULL on a zero divisor, like ThoughtSpot's own `/`
        result = translate_sql_expr("a.X / NULLIF(a.Y, 0)", _resolve)
        assert result == "[A::X] / [A::Y]"
        assert translate_sql_expr("COALESCE(a.X / NULLIF(a.Y, 0), 0)", _resolve) == \
            "ifnull ( safe_divide ( [A::X] , [A::Y] ) , 0 )"

    def test_nullif_non_zero(self):
        result = translate_sql_expr("NULLIF(a.X, a.Y)", _resolve)
        # ThoughtSpot has no nullif (BL-339): the CASE form instead.
        assert result == "( if ( [A::X] = [A::Y] ) then null else [A::X] )"


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
        # BL-362: `||` is NULL-propagating concat, like concat
        assert translate_sql_expr("a.X || a.Y", _resolve) == "concat ( [A::X] , [A::Y] )"
        with pytest.raises(UntranslatableError, match="mixed"):
            translate_sql_expr("a.X || a.Y + 1", _resolve)

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


# ---------------------------------------------------------------------------
# BL-212 — quoted date-part units and double-quoted identifiers
#
# Both shapes are idiomatic in a hand-written Semantic View and both were
# rejected, dropping the whole construct into skipped[]. Found converting a
# real SV: DATEDIFF('day', ...) cost two metrics and dm_date_dim."DATE" cost a
# dimension, 3 of 44 constructs, with no error visible in the Model.
# ---------------------------------------------------------------------------

class TestQuotedUnitArgument:
    """Snowflake accepts the DATEDIFF/DATEADD date part bare OR quoted."""

    def test_datediff_quoted_unit(self):
        assert translate_sql_expr(
            "DATEDIFF('day', o.ORDER_DATE, o.SHIPPED_DATE)", _resolve
        ) == "diff_days ( [O::SHIPPED_DATE] , [O::ORDER_DATE] )"

    def test_datediff_bare_unit_unchanged(self):
        assert translate_sql_expr(
            "DATEDIFF(day, o.ORDER_DATE, o.SHIPPED_DATE)", _resolve
        ) == "diff_days ( [O::SHIPPED_DATE] , [O::ORDER_DATE] )"

    def test_datediff_quoted_and_bare_agree(self):
        quoted = translate_sql_expr("DATEDIFF('month', a.S, a.E)", _resolve)
        bare = translate_sql_expr("DATEDIFF(month, a.S, a.E)", _resolve)
        assert quoted == bare

    def test_datediff_quoted_unit_mixed_case(self):
        assert translate_sql_expr(
            "DATEDIFF('DAY', o.S, o.E)", _resolve
        ) == "diff_days ( [O::E] , [O::S] )"

    def test_dateadd_quoted_unit(self):
        assert translate_sql_expr(
            "DATEADD('day', -364, d.DATE_VALUE)", _resolve
        ) == "add_days ( [D::DATE_VALUE] , - 364 )"

    def test_unmapped_quoted_unit_still_refused(self):
        with pytest.raises(UntranslatableError, match="not mapped"):
            translate_sql_expr("DATEDIFF('microsecond', a.S, a.E)", _resolve)

    def test_non_unit_first_arg_still_refused(self):
        with pytest.raises(UntranslatableError, match="unit identifier"):
            translate_sql_expr("DATEDIFF(42, a.S, a.E)", _resolve)


class TestDoubleQuotedIdentifiers:
    """A reserved word or an exact-case column must be double-quoted in the
    DDL; the quotes carry no meaning once tokenized."""

    def test_quoted_reserved_word_column(self):
        assert translate_sql_expr('d."DATE"', _resolve) == "[D::DATE]"

    def test_quoted_column_inside_function(self):
        assert translate_sql_expr(
            'DATE_TRUNC(\'month\', d."DATE")', _resolve
        ) == "start_of_month ( [D::DATE] )"

    def test_quoted_table_segment(self):
        assert translate_sql_expr('"MY_TABLE".col', _resolve) == "[MY_TABLE::col]"

    def test_both_segments_quoted(self):
        assert translate_sql_expr('"T"."C"', _resolve) == "[T::C]"

    def test_unquoted_is_unchanged(self):
        assert translate_sql_expr("d.DATE_VALUE", _resolve) == "[D::DATE_VALUE]"

    def test_quoted_and_unquoted_resolve_alike(self):
        assert (translate_sql_expr('d."COL"', _resolve)
                == translate_sql_expr("d.COL", _resolve))

    def test_tokenizer_keeps_quoted_segment_whole(self):
        kinds = [k for k, _ in tokenize('d."DATE"') if k != "ws"]
        assert kinds == ["ident"]


# ---------------------------------------------------------------------------
# BL-340..343 — formula fidelity M0 silent wrong answers (2026-10-06)
# ---------------------------------------------------------------------------

class TestFidelityM0Fixes:
    # BL-340 — SUBSTR is 1-based, ThoughtSpot substr zero-based.
    @pytest.mark.parametrize("src,out", [
        ("SUBSTR(a.S, 2, 3)", "substr ( [A::S] , 1 , 3 )"),
        ("SUBSTRING(a.S, 2, 3)", "substr ( [A::S] , 1 , 3 )"),
        ("SUBSTR(a.S, 1, 1)", "substr ( [A::S] , 0 , 1 )"),
        ("SUBSTR(a.S, 3)", "substr ( [A::S] , 2 , strlen ( [A::S] ) )"),
        ("SUBSTR(a.S, 2, a.N)", "substr ( [A::S] , 1 , [A::N] )"),
    ])
    def test_substr_literal_start_folds(self, src, out):
        assert translate_sql_expr(src, _resolve) == out

    @pytest.mark.parametrize("src,out", [
        # negative start counts from the end; 0 is treated as 1 — never substr
        ("SUBSTR(a.S, -3, 2)", 'sql_string_op ( "SUBSTR({0}, -3, 2)" , [A::S] )'),
        ("SUBSTR(a.S, -2)", 'sql_string_op ( "SUBSTR({0}, -2)" , [A::S] )'),
        ("SUBSTRING(a.S, 0, 2)", 'sql_string_op ( "SUBSTRING({0}, 0, 2)" , [A::S] )'),
        # a non-literal start could be negative at run time
        ("SUBSTR(a.S, a.I, 2)",
         'sql_string_op ( "SUBSTR({0}, {1}, 2)" , [A::S] , [A::I] )'),
    ])
    def test_substr_non_positive_or_dynamic_start_passes_through(self, src, out):
        assert translate_sql_expr(src, _resolve) == out

    def test_substr_pass_through_over_aggregate_refused(self):
        with pytest.raises(UntranslatableError):
            translate_sql_expr("SUBSTR(MAX(a.S), -2)", _resolve)

    def test_substr_arity(self):
        with pytest.raises(UntranslatableError):
            translate_sql_expr("SUBSTR(a.S)", _resolve)

    # BL-341 — every DATEDIFF unit is a boundary count; end date first.
    @pytest.mark.parametrize("unit,fn", [
        ("day", "diff_days"), ("month", "diff_months"),
        ("quarter", "diff_quarters"), ("year", "diff_years"),
        ("minute", "diff_minutes"), ("second", "diff_time"),
        # documented part aliases
        ("'yyyy'", "diff_years"), ("qtr", "diff_quarters"), ("mi", "diff_minutes"),
        ("sec", "diff_time"),
    ])
    def test_datediff_units(self, unit, fn):
        assert translate_sql_expr(f"DATEDIFF({unit}, a.S, a.E)", _resolve) == \
            f"{fn} ( [A::E] , [A::S] )"

    @pytest.mark.parametrize("unit,part", [
        ("week", "week"), ("wk", "week"), ("'w'", "week"),
        # diff_hours counts UTC hours on TIMESTAMP_TZ (M0 sf-ts-005)
        ("hour", "hour"), ("hh", "hour"), ("hh24", "hour"), ("'HH24'", "hour"),
    ])
    def test_datediff_week_and_hour_are_exact_pass_throughs(self, unit, part):
        # #572 review: the converter cannot show a trap, so no native-with-a-caveat.
        assert translate_sql_expr(f"DATEDIFF({unit}, a.S, a.E)", _resolve) == \
            f'sql_int_op ( "DATEDIFF({part}, {{0}}, {{1}})" , [A::S] , [A::E] )'

    def test_datediff_week_over_aggregate_refused(self):
        with pytest.raises(UntranslatableError):
            translate_sql_expr("DATEDIFF(week, MIN(a.S), MAX(a.E))", _resolve)

    def test_datediff_year_never_days_over_365(self):
        assert "365" not in translate_sql_expr("DATEDIFF(year, a.S, a.E)", _resolve)

    def test_datediff_unknown_unit(self):
        with pytest.raises(UntranslatableError):
            translate_sql_expr("DATEDIFF(nanosecond, a.S, a.E)", _resolve)

    # BL-342 — MONTHS_BETWEEN is fractional with a month-end rule: pass-through.
    @pytest.mark.parametrize("src,out", [
        ("MONTHS_BETWEEN(a.E, a.S)",
         'sql_double_op ( "MONTHS_BETWEEN({0}, {1})" , [A::E] , [A::S] )'),
        ("MONTHS_BETWEEN(a.S, a.E)",
         'sql_double_op ( "MONTHS_BETWEEN({0}, {1})" , [A::S] , [A::E] )'),
        # a date literal is already to_date ( … ) — bound as an argument, not inlined
        ("MONTHS_BETWEEN('2026-03-31', a.S)",
         'sql_double_op ( "MONTHS_BETWEEN({0}, {1})" , '
         "to_date ( '2026-03-31' , 'yyyy-MM-dd' ) , [A::S] )"),
    ])
    def test_months_between_pass_through(self, src, out):
        result = translate_sql_expr(src, _resolve)
        assert result == out
        assert "diff_months" not in result

    def test_months_between_over_aggregate_refused(self):
        with pytest.raises(UntranslatableError):
            translate_sql_expr("MONTHS_BETWEEN(MAX(a.E), MIN(a.S))", _resolve)

    # BL-343 — TO_CHAR / TO_VARCHAR keep their format.
    @pytest.mark.parametrize("src,out", [
        ("TO_CHAR(a.D, 'YYYY-MM')", 'sql_string_op ( "TO_CHAR({0}, \'YYYY-MM\')" , [A::D] )'),
        ("TO_VARCHAR(a.D, 'DD-MON-YYYY')",
         'sql_string_op ( "TO_VARCHAR({0}, \'DD-MON-YYYY\')" , [A::D] )'),
        ("TO_CHAR(a.N, '999,999.00')",
         'sql_string_op ( "TO_CHAR({0}, \'999,999.00\')" , [A::N] )'),
        ("TO_CHAR(a.D, a.F)", 'sql_string_op ( "TO_CHAR({0}, {1})" , [A::D] , [A::F] )'),
        ("TO_VARCHAR(a.S)", 'sql_string_op ( "TO_VARCHAR({0})" , [A::S] )'),
    ])
    def test_to_char_keeps_format(self, src, out):
        result = translate_sql_expr(src, _resolve)
        assert result == out
        assert "to_string" not in result

    # #572 review item 6: a `\"` escape was live-probed and rejected at import
    # (fidelity M0 sf-date-018, 2026-10-06), so a double quote stays refused.
    @pytest.mark.parametrize("fmt", ["'YYYY\"m\"MM'", "'{0}'", "'a\\\\b'"])
    def test_to_char_format_with_quote_brace_or_backslash_refused(self, fmt):
        with pytest.raises(UntranslatableError):
            translate_sql_expr(f"TO_CHAR(a.D, {fmt})", _resolve)
