"""Unit tests for the Tableau → ThoughtSpot formula translation engine.

Test cases derived from actual CPG Merch Promotion Performance migration failures.
"""
from __future__ import annotations

import pytest

from ts_cli.tableau_translate import (
    apply_name_clash_renames,
    build_calc_id_map,
    build_csq_column_map,
    build_dependency_dag,
    build_param_renames,
    complete_rank_args,
    convert_agg_if,
    convert_boolean_aggregate,
    convert_case_when,
    convert_if_then,
    convert_iif,
    convert_int,
    convert_lod,
    convert_no_keyword_lod,
    convert_scalar_max_min,
    convert_string_concat,
    convert_total,
    detect_name_clashes,
    detect_param_conflicts,
    dump_tml_yaml,
    ensure_else_clause,
    fix_in_parentheses,
    map_date_functions,
    map_functions,
    map_parameter_names,
    normalize_operator_spacing,
    resolve_cross_references,
    rewrite_csq_aliases,
    rewrite_date_arithmetic,
    sanitise_parameter_name,
    sanitise_parameter_refs,
    scope_columns,
    strip_comments,
    strip_ifnull_zero,
    strip_parameter_prefix,
    translate_formulas,
    translate_single,
    validate_output,
    validate_pre_import,
)


# ---------------------------------------------------------------------------
# Pre-0. Comment stripping (BL-056)
# ---------------------------------------------------------------------------

class TestStripComments:
    def test_basic_comment(self):
        result = strip_comments("[Lift] / [Cost] //SUM([Redemption Cost])")
        assert result == "[Lift] / [Cost]"

    def test_preserves_url_in_string(self):
        result = strip_comments("'https://coda.io/d/doc'")
        assert "https://coda.io/d/doc" in result

    def test_multiline_comment(self):
        formula = "[Sales]\n// This is a comment\n+ [Revenue]"
        result = strip_comments(formula)
        assert "Sales" in result
        assert "Revenue" in result
        assert "This is a comment" not in result

    def test_no_comment(self):
        assert strip_comments("[Sales] + [Revenue]") == "[Sales] + [Revenue]"

    def test_comment_after_expression(self):
        result = strip_comments("SUM([Sales]) // total sales\n+ [Tax]")
        assert "SUM([Sales])" in result
        assert "+ [Tax]" in result
        assert "total sales" not in result

    def test_double_slash_in_double_quotes(self):
        result = strip_comments('"some//path"')
        assert '"some//path"' in result


# ---------------------------------------------------------------------------
# Pre-1. Custom SQL Query alias resolution (BL-057)
# ---------------------------------------------------------------------------

class TestRewriteCsqAliases:
    def test_basic_rewrite(self):
        result = rewrite_csq_aliases(
            "[DATE (Custom SQL Query8)]",
            {"Custom SQL Query8": "FORECAST"},
        )
        assert result == "[FORECAST::DATE]"

    def test_multiple_aliases(self):
        expr = "[DATE (Custom SQL Query8)] + [SALES (Custom SQL Query6)]"
        result = rewrite_csq_aliases(
            expr,
            {"Custom SQL Query8": "FORECAST", "Custom SQL Query6": "DAILY_METRICS"},
        )
        assert "[FORECAST::DATE]" in result
        assert "[DAILY_METRICS::SALES]" in result

    def test_unknown_csq_preserved(self):
        result = rewrite_csq_aliases(
            "[DATE (Custom SQL Query99)]",
            {"Custom SQL Query8": "FORECAST"},
        )
        assert result == "[DATE (Custom SQL Query99)]"

    def test_no_csq_map(self):
        result = rewrite_csq_aliases("[DATE (Custom SQL Query8)]", {})
        assert result == "[DATE (Custom SQL Query8)]"

    def test_column_with_spaces(self):
        result = rewrite_csq_aliases(
            "[PERIOD TYPE (Custom SQL Query8)]",
            {"Custom SQL Query8": "FORECAST"},
        )
        assert result == "[FORECAST::PERIOD TYPE]"


class TestBuildCsqColumnMap:
    def test_definitive_match(self):
        csq_columns = {
            "Custom SQL Query8": {"CATEGORY", "DATE", "LEVEL", "PERIOD_TYPE", "PROMOTION_ID"},
        }
        model_tables = {
            "FORECAST": {"CATEGORY", "DATE", "LEVEL", "PERIOD_TYPE", "PROMOTION_ID", "AMOUNT"},
        }
        definitive, ambiguous = build_csq_column_map(csq_columns, model_tables)
        assert definitive["Custom SQL Query8"] == "FORECAST"
        assert len(ambiguous) == 0

    def test_ambiguous_match(self):
        csq_columns = {
            "Custom SQL Query1": {"DATE", "ID", "AMOUNT", "TAX"},
        }
        model_tables = {
            "ORDERS": {"DATE", "ID"},
            "INVOICES": {"DATE", "ID", "TOTAL"},
        }
        definitive, ambiguous = build_csq_column_map(csq_columns, model_tables)
        assert len(definitive) == 0
        assert "Custom SQL Query1" in ambiguous

    def test_no_match(self):
        csq_columns = {"Custom SQL Query1": {"A", "B", "C"}}
        model_tables = {"TABLE1": {"X", "Y", "Z"}}
        definitive, ambiguous = build_csq_column_map(csq_columns, model_tables)
        assert len(definitive) == 0
        assert len(ambiguous) == 0


# ---------------------------------------------------------------------------
# Pre-2. No-keyword LOD (BL-052)
# ---------------------------------------------------------------------------

class TestConvertNoKeywordLod:
    def test_countd(self):
        result = convert_no_keyword_lod("{COUNTD([PROMOTION_ID])}")
        assert "group_aggregate ( unique count ( [PROMOTION_ID] ) , {} , query_filters () )" in result

    def test_sum(self):
        result = convert_no_keyword_lod("{SUM([SALES])}")
        assert "group_aggregate ( sum ( [SALES] ) , {} , query_filters () )" in result

    def test_max(self):
        result = convert_no_keyword_lod("{MAX([DATE])}")
        assert "group_aggregate ( max ( [DATE] ) , {} , query_filters () )" in result

    def test_attr(self):
        result = convert_no_keyword_lod("{ATTR([CATEGORY])}")
        assert "group_aggregate ( max ( [CATEGORY] ) , {} , query_filters () )" in result

    def test_does_not_match_fixed_lod(self):
        expr = "{FIXED [Dim] : SUM([Sales])}"
        result = convert_no_keyword_lod(expr)
        assert result == expr

    def test_does_not_match_include_lod(self):
        expr = "{INCLUDE [Dim] : SUM([Sales])}"
        result = convert_no_keyword_lod(expr)
        assert result == expr

    def test_avg(self):
        result = convert_no_keyword_lod("{AVG([PRICE])}")
        assert "group_aggregate ( average ( [PRICE] ) , {} , query_filters () )" in result


# ---------------------------------------------------------------------------
# Pre-3. Scalar MAX/MIN (BL-055)
# ---------------------------------------------------------------------------

class TestConvertScalarMaxMin:
    def test_max_two_args(self):
        result = convert_scalar_max_min("MAX([Sales], [Revenue])")
        assert result == "greatest ( [Sales] , [Revenue] )"

    def test_min_two_args(self):
        result = convert_scalar_max_min("MIN([Sales], [Revenue])")
        assert result == "least ( [Sales] , [Revenue] )"

    def test_max_with_zero(self):
        result = convert_scalar_max_min("MAX([Profit], 0)")
        assert result == "greatest ( [Profit] , 0 )"

    def test_min_with_zero(self):
        result = convert_scalar_max_min("MIN([Profit], 0)")
        assert result == "least ( [Profit] , 0 )"

    def test_aggregate_max_preserved(self):
        result = convert_scalar_max_min("MAX([Sales])")
        assert result == "MAX([Sales])"

    def test_aggregate_min_preserved(self):
        result = convert_scalar_max_min("MIN([Date])")
        assert result == "MIN([Date])"

    def test_max_with_case_expr(self):
        result = convert_scalar_max_min(
            "MAX(CASE [X] WHEN 'A' THEN [Y] WHEN 'B' THEN [Z] END, 0)"
        )
        assert result.startswith("greatest ( ")
        assert result.endswith(" , 0 )")

    def test_scalar_max_after_aggregate_max(self):
        result = convert_scalar_max_min("MAX([Sales]) + MAX([a], [b])")
        assert result == "MAX([Sales]) + greatest ( [a] , [b] )"

    def test_scalar_min_after_aggregate_min(self):
        result = convert_scalar_max_min("MIN([Sales]) / MIN([Cost], 1)")
        assert result == "MIN([Sales]) / least ( [Cost] , 1 )"

    def test_nested_scalar_inside_aggregate_args(self):
        result = convert_scalar_max_min("MAX(MAX([a], [b]))")
        assert result == "MAX(greatest ( [a] , [b] ))"


# ---------------------------------------------------------------------------
# Pre-4. Date arithmetic (BL-054)
# ---------------------------------------------------------------------------

class TestRewriteDateArithmetic:
    def test_date_call_plus(self):
        result = rewrite_date_arithmetic("DATE([START_DATE]) + 1")
        assert "add_days ( DATE([START_DATE]) , 1 )" in result

    def test_date_call_minus(self):
        result = rewrite_date_arithmetic("DATE([END_DATE]) - 7")
        assert "add_days ( DATE([END_DATE]) , -7 )" in result

    def test_date_column_plus(self):
        result = rewrite_date_arithmetic(
            "[START_DATE] + 1",
            date_columns={"START_DATE"},
        )
        assert "add_days ( [START_DATE] , 1 )" in result

    def test_non_date_column_not_rewritten(self):
        result = rewrite_date_arithmetic("[SALES] + 1")
        assert result == "[SALES] + 1"

    def test_non_date_column_without_set(self):
        result = rewrite_date_arithmetic("[START_DATE] + 1")
        assert result == "[START_DATE] + 1"

    def test_scoped_date_column(self):
        result = rewrite_date_arithmetic(
            "[TABLE::START_DATE] + 1",
            date_columns={"START_DATE"},
        )
        assert "add_days ( [TABLE::START_DATE] , 1 )" in result


# ---------------------------------------------------------------------------
# Operator spacing (BL-046 #4)
# ---------------------------------------------------------------------------

class TestNormalizeOperatorSpacing:
    def test_no_spaces(self):
        result = normalize_operator_spacing("[A]+[B]")
        assert "[A] + [B]" in result

    def test_minus_no_space(self):
        result = normalize_operator_spacing("[A]-[B]")
        assert "[A] - [B]" in result

    def test_already_spaced(self):
        result = normalize_operator_spacing("[A] + [B]")
        assert result == "[A] + [B]"

    def test_preserves_string_content(self):
        result = normalize_operator_spacing("'a+b'")
        assert result == "'a+b'"

    def test_preserves_bracket_content(self):
        result = normalize_operator_spacing("[Col-Name]")
        assert result == "[Col-Name]"

    def test_multiply(self):
        result = normalize_operator_spacing("[A]*[B]")
        assert "[A] * [B]" in result

    def test_divide(self):
        result = normalize_operator_spacing("[A]/[B]")
        assert "[A] / [B]" in result


# ---------------------------------------------------------------------------
# rank() argument completion (BL-046 #3)
# ---------------------------------------------------------------------------

class TestCompleteRankArgs:
    def test_single_arg(self):
        result = complete_rank_args("rank([Sales])")
        assert "rank ( [Sales] , 'desc' )" in result

    def test_two_args_preserved(self):
        result = complete_rank_args("rank([Sales], 'asc')")
        assert result == "rank([Sales], 'asc')"

    def test_no_rank(self):
        result = complete_rank_args("sum([Sales])")
        assert result == "sum([Sales])"


# ---------------------------------------------------------------------------
# Parameter sanitisation (BL-050 #6)
# ---------------------------------------------------------------------------

class TestSanitiseParameterName:
    def test_slash(self):
        assert sanitise_parameter_name("Platform/Placement") == "Platform Placement"

    def test_backslash(self):
        assert sanitise_parameter_name("Foo\\Bar") == "Foo Bar"

    def test_clean_name(self):
        assert sanitise_parameter_name("Metric") == "Metric"

    def test_multiple_special(self):
        assert sanitise_parameter_name("A/B:C") == "A B C"


class TestSanitiseParameterRefs:
    def test_basic(self):
        result = sanitise_parameter_refs(
            "IF [Platform/Placement] = 'web' THEN 1 END",
            {"Platform/Placement": "Platform Placement"},
        )
        assert "[Platform Placement]" in result
        assert "Platform/Placement" not in result


class TestBuildParamRenames:
    def test_detects_unsafe(self):
        params = [{"caption": "Platform/Placement"}, {"caption": "Metric"}]
        renames = build_param_renames(params)
        assert "Platform/Placement" in renames
        assert renames["Platform/Placement"] == "Platform Placement"
        assert "Metric" not in renames


# ---------------------------------------------------------------------------
# Name clash detection (BL-050 #9)
# ---------------------------------------------------------------------------

class TestDetectNameClashes:
    def test_case_insensitive_clash(self):
        clashes = detect_name_clashes(
            formula_names={"Sales"},
            column_names={"SALES"},
        )
        assert "Sales" in clashes

    def test_no_clash(self):
        clashes = detect_name_clashes(
            formula_names={"Profit Margin"},
            column_names={"SALES"},
        )
        assert len(clashes) == 0

    def test_exact_match(self):
        clashes = detect_name_clashes(
            formula_names={"SALES"},
            column_names={"SALES"},
        )
        assert "SALES" in clashes

    def test_apply_renames_updates_cross_refs(self):
        clashes = {"Units": "Formula Units", "Sales": "Formula Sales"}
        expr = "sum ( [formula_Units] ) / sum ( [formula_Sales] )"
        result = apply_name_clash_renames(expr, clashes)
        assert "[formula_Formula Units]" in result
        assert "[formula_Formula Sales]" in result
        assert "[formula_Units]" not in result

    def test_apply_renames_no_match_unchanged(self):
        clashes = {"Units": "Formula Units"}
        expr = "sum ( [formula_Profit] )"
        result = apply_name_clash_renames(expr, clashes)
        assert result == expr


# ---------------------------------------------------------------------------
# Parameter handling
# ---------------------------------------------------------------------------

class TestStripParameterPrefix:
    def test_basic(self):
        assert strip_parameter_prefix("[Parameters].[Metric]") == "[Metric]"

    def test_inline(self):
        result = strip_parameter_prefix(
            "IF [Parameters].[Parameter 3 1]='Sales' THEN [X] END"
        )
        assert "[Parameters]." not in result
        assert "[Parameter 3 1]" in result

    def test_no_params(self):
        assert strip_parameter_prefix("[Sales] + [Revenue]") == "[Sales] + [Revenue]"

    def test_case_insensitive(self):
        assert strip_parameter_prefix("[parameters].[Foo]") == "[Foo]"


class TestMapParameterNames:
    def test_basic(self):
        result = map_parameter_names(
            "[Parameter 3 1]",
            {"Parameter 3 1": "Metric"},
        )
        assert result == "[Metric]"

    def test_multiple(self):
        result = map_parameter_names(
            "IF [Parameter 3 1]='Sales' THEN [Parameter 6] END",
            {"Parameter 3 1": "Metric", "Parameter 6": "Engagement Type"},
        )
        assert "[Metric]" in result
        assert "[Engagement Type]" in result


# ---------------------------------------------------------------------------
# CASE/WHEN conversion
# ---------------------------------------------------------------------------

class TestConvertCaseWhen:
    def test_basic_case(self):
        expr = "CASE [Parameters].[Metric]\nWHEN 'Sales' THEN [SALES]\nWHEN 'Revenue' THEN [REVENUE]\nEND"
        result = convert_case_when(expr)
        assert "if" in result
        assert "CASE" not in result
        assert "WHEN" not in result
        assert "[Parameters].[Metric] = 'Sales'" in result

    def test_case_with_else(self):
        expr = "CASE [X] WHEN 'a' THEN 1 WHEN 'b' THEN 2 ELSE 0 END"
        result = convert_case_when(expr)
        assert "if ( [X] = 'a' ) then 1" in result
        assert "else if ( [X] = 'b' ) then 2" in result
        assert "else 0" in result
        assert "END" not in result

    def test_case_nested_inside_if_else(self):
        expr = (
            "IF [FLAG]>1 THEN "
            "CASE [TYPE] WHEN 'a' THEN [COL_A] WHEN 'b' THEN [COL_B] END "
            "ELSE "
            "CASE [TYPE] WHEN 'a' THEN [COL_C] WHEN 'b' THEN [COL_D] END "
            "END"
        )
        result = convert_case_when(expr)
        assert "CASE" not in result
        assert result.count("if ( [TYPE]") == 4
        assert "[COL_A]" in result
        assert "[COL_D]" in result
        # Outer IF's ELSE and END preserved for convert_if_then
        assert "ELSE" in result
        # Full pipeline produces clean output
        full = convert_if_then(result)
        assert "END" not in full
        assert "CASE" not in full
        assert "[COL_A]" in full
        assert "[COL_D]" in full

    def test_case_with_end_in_column_name(self):
        expr = "CASE [X] WHEN 'a' THEN [END_DATE_PRE] WHEN 'b' THEN [END_DATE_LY] END"
        result = convert_case_when(expr)
        assert "[END_DATE_PRE]" in result
        assert "[END_DATE_LY]" in result
        assert "CASE" not in result


# ---------------------------------------------------------------------------
# IF/THEN/END conversion
# ---------------------------------------------------------------------------

class TestConvertIfThen:
    def test_basic_if(self):
        result = convert_if_then("IF [X] > 5 THEN 'High' ELSE 'Low' END")
        assert "if ( [X] > 5 ) then" in result
        assert "END" not in result
        assert "'High'" in result

    def test_nested_if(self):
        result = convert_if_then(
            "IF [X]='a' THEN 1 ELSEIF [X]='b' THEN 2 ELSE 3 END"
        )
        assert "if ( [X]='a' ) then 1" in result
        assert "else if ( [X]='b' ) then 2" in result
        assert "else 3" in result
        assert "END" not in result
        assert "ELSEIF" not in result

    def test_preserves_non_if(self):
        result = convert_if_then("[Sales] + [Revenue]")
        assert result == "[Sales] + [Revenue]"

    def test_nested_if_with_lowercase_inner_then(self):
        # Tableau is case-insensitive; a source-authored nested IF may use
        # lowercase then/else. The inner condition must still get its if(...)
        # wrapper (regression: it was silently dropped, breaking Start/End Date).
        result = convert_if_then(
            "IF [L]='campaign' THEN IF [X] < 12 then [A] else [B] END ELSE [C] END"
        )
        assert "if ( [L]='campaign' ) then" in result
        assert "if ( [X] < 12 ) then [A]" in result
        # matches the all-uppercase-authored form exactly
        upper = convert_if_then(
            "IF [L]='campaign' THEN IF [X] < 12 THEN [A] ELSE [B] END ELSE [C] END"
        )
        assert result == upper

    def test_nested_if_in_condition(self):
        """Nested IF blocks inside an outer IF condition are converted correctly."""
        expr = (
            "IF (IF [P]='M' THEN [A] ELSEIF [P]='Q' THEN [B] END "
            "= IF [P]='M' THEN [C] ELSEIF [P]='Q' THEN [D] END) "
            "THEN 'Yes' ELSE 'No' END"
        )
        result = convert_if_then(expr)
        assert "if ( [P]='M' ) then [A]" in result
        assert "else if ( [P]='Q' ) then [B]" in result
        assert "if ( [P]='M' ) then [C]" in result
        assert "else if ( [P]='Q' ) then [D]" in result
        assert "else 'No'" in result
        assert "END" not in result
        assert result.count("else null") == 2

    def test_column_with_parens_in_brackets(self):
        """Column refs like [Budget Sub Line (copy)] don't break IF conversion."""
        expr = "IF [X]=1 THEN [Col (copy)] ELSE [Y] END"
        result = convert_if_then(expr)
        assert "if ( [X]=1 ) then [Col (copy)]" in result
        assert "else [Y]" in result


# ---------------------------------------------------------------------------
# IIF conversion
# ---------------------------------------------------------------------------

class TestConvertIif:
    def test_basic(self):
        result = convert_iif("IIF([X] > 0, 'Positive', 'Negative')")
        assert "if ( [X] > 0 ) then 'Positive' else 'Negative'" in result

    def test_no_iif(self):
        assert convert_iif("[Sales]") == "[Sales]"


# ---------------------------------------------------------------------------
# Function mapping
# ---------------------------------------------------------------------------

class TestMapFunctions:
    def test_countd(self):
        result = map_functions("COUNTD([Customer])")
        assert "unique count" in result
        assert "[Customer]" in result

    def test_avg(self):
        result = map_functions("AVG([Sales])")
        assert "average ( [Sales])" in result

    def test_zn(self):
        result = map_functions("ZN([Sales])")
        assert "ifnull ( [Sales] , 0 )" in result

    def test_contains(self):
        result = map_functions("CONTAINS([Name], 'test')")
        assert "contains ( [Name], 'test')" in result

    def test_len(self):
        result = map_functions("LEN([Name])")
        assert "strlen ( [Name])" in result

    def test_sum_preserved(self):
        result = map_functions("SUM([Sales])")
        assert "sum ( [Sales])" in result

    def test_nested_zn(self):
        result = map_functions("ZN([X]) + ZN([Y])")
        assert "ifnull ( [X] , 0 )" in result
        assert "ifnull ( [Y] , 0 )" in result

    def test_left(self):
        assert map_functions("LEFT([Name], 3)") == "substr ( [Name] , 0 , 3 )"

    def test_right(self):
        assert map_functions("RIGHT([Name], 2)") == "substr ( [Name] , strlen ( [Name] ) - 2 , 2 )"

    def test_mid(self):
        assert map_functions("MID([Name], 2, 5)") == "substr ( [Name] , 2 - 1 , 5 )"

    def test_upper(self):
        assert map_functions("UPPER([Name])") == 'sql_string_op ( "UPPER({0})" , [Name] )'

    def test_startswith(self):
        assert map_functions("STARTSWITH([Name], 'A')") == "( strpos ( [Name] , 'A' ) = 1 )"

    def test_endswith(self):
        assert map_functions("ENDSWITH([Name], 'Z')") == \
            "( substr ( [Name] , strlen ( [Name] ) - strlen ( 'Z' ) , strlen ( 'Z' ) ) = 'Z' )"

    def test_square(self):
        assert map_functions("SQUARE([X])") == "pow ( [X] , 2 )"

    def test_left_nested_in_if(self):
        assert map_functions("IF LEFT([Code], 1) = 'A' THEN 1 END") == \
            "IF substr ( [Code] , 0 , 1 ) = 'A' THEN 1 END"

    def test_self_nested_left(self):
        assert map_functions("LEFT(LEFT([a], 5), 2)") == "substr ( substr ( [a] , 0 , 5 ) , 0 , 2 )"

    def test_self_nested_right(self):
        assert map_functions("RIGHT(RIGHT([x], 10), 5)") == \
            "substr ( substr ( [x] , strlen ( [x] ) - 10 , 10 ) , strlen ( substr ( [x] , strlen ( [x] ) - 10 , 10 ) ) - 5 , 5 )"

    def test_self_nested_upper(self):
        assert map_functions("UPPER(UPPER([a]))") == \
            'sql_string_op ( "UPPER({0})" , sql_string_op ( "UPPER({0})" , [a] ) )'

    def test_sign(self):
        assert map_functions("SIGN([X])") == \
            "( if ( [X] > 0 ) then 1 else if ( [X] < 0 ) then -1 else 0 )"

    def test_trig_converts_radians_to_degrees(self):
        assert map_functions("SIN([X])") == "sin ( [X] * 180 / 3.14159265358979 )"

    def test_pi(self):
        assert map_functions("PI()") == "3.14159265358979"

    def test_radians(self):
        assert map_functions("RADIANS([D])") == "( [D] * 3.14159265358979 / 180 )"

    def test_degrees(self):
        assert map_functions("DEGREES([R])") == "( [R] * 180 / 3.14159265358979 )"

    def test_dateparse_flips_args(self):
        assert map_functions("DATEPARSE('yyyy-MM-dd', [DateStr])") == \
            "to_date ( [DateStr] , 'yyyy-MM-dd' )"


# ---------------------------------------------------------------------------
# Date function mapping
# ---------------------------------------------------------------------------

class TestMapDateFunctions:
    def test_datetrunc_month(self):
        result = map_date_functions("DATETRUNC('month', [Date])")
        assert "start_of_month ( [Date] )" in result

    def test_datetrunc_quarter(self):
        result = map_date_functions("DATETRUNC('quarter', [Date])")
        assert "start_of_quarter ( [Date] )" in result

    def test_datetrunc_column_with_parens(self):
        """Parens inside bracket refs don't break DATETRUNC arg extraction."""
        result = map_date_functions(
            "DATETRUNC('month', [Budget Sub Line (copy)])"
        )
        assert "start_of_month ( [Budget Sub Line (copy)] )" in result

    def test_datediff_day(self):
        result = map_date_functions("DATEDIFF('day', [Start], [End])")
        assert "diff_days ( [End] , [Start] )" in result

    def test_datediff_reversed_args(self):
        result = map_date_functions("DATEDIFF('month', [A], [B])")
        # TS takes (end, start) — reversed from Tableau
        assert "diff_months ( [B] , [A] )" in result

    def test_dateadd_day(self):
        result = map_date_functions("DATEADD('day', 1, [Date])")
        assert "add_days ( [Date] , 1 )" in result

    def test_datepart_month(self):
        result = map_date_functions("DATEPART('month', [Date])")
        assert "month_number ( [Date] )" in result

    def test_datepart_weekday(self):
        result = map_date_functions("DATEPART('weekday', [Date])")
        assert "day_of_week ( [Date] )" in result

    def test_datediff_hour(self):
        result = map_date_functions("DATEDIFF('hour', [A], [B])")
        assert "diff_time ( [B] , [A] ) / 3600" in result

    def test_datepart_unknown_unit_left_untranslated(self):
        # 'minute' has no ThoughtSpot extractor — must NOT fabricate minute(...)
        result = map_date_functions("DATEPART('minute', [TS])")
        assert "minute (" not in result and "DATEPART" in result

    def test_datediff_unknown_unit_left_untranslated(self):
        result = map_date_functions("DATEDIFF('fortnight', [A], [B])")
        assert "diff_fortnights" not in result and "DATEDIFF" in result

    def test_dateadd_unknown_unit_left_untranslated(self):
        result = map_date_functions("DATEADD('fortnight', 2, [D])")
        assert "add_fortnights" not in result and "DATEADD" in result

    def test_datetrunc_unknown_unit_left_untranslated(self):
        result = map_date_functions("DATETRUNC('hour', [TS])")
        assert "start_of_hour" not in result and "DATETRUNC" in result


# ---------------------------------------------------------------------------
# INT conversion
# ---------------------------------------------------------------------------

class TestConvertInt:
    def test_int(self):
        result = convert_int("INT([X])")
        assert "floor" in result
        assert "ceil" in result
        assert ">= 0" in result


# ---------------------------------------------------------------------------
# String concatenation
# ---------------------------------------------------------------------------

class TestConvertStringConcat:
    def test_string_plus(self):
        result = convert_string_concat("to_string([X]) + '%'", role="dimension")
        assert "concat" in result
        assert "+" not in result

    def test_numeric_plus_preserved(self):
        result = convert_string_concat("[Sales] + [Revenue]", role="measure")
        assert "+" in result
        assert "concat" not in result

    def test_nested_plus_inside_if_else(self):
        expr = (
            "if ( [Tier] = 'Two' ) then [A] + ' : ' + [B] "
            "else if ( [Tier] = 'Three' ) then [A] + ' : ' + [B] + ' : ' + [C] "
            "else ''"
        )
        result = convert_string_concat(expr, role="dimension")
        assert "+" not in result
        assert "then concat ( [A] , ' : ' , [B] )" in result
        assert "then concat ( [A] , ' : ' , [B] , ' : ' , [C] )" in result


# ---------------------------------------------------------------------------
# IN (...) -> in {...}
# ---------------------------------------------------------------------------

class TestFixInParentheses:
    def test_basic_in(self):
        assert fix_in_parentheses("[Region] IN ('East', 'West')") == "[Region] in { 'East', 'West' }"

    def test_in_after_not_in_still_converted(self):
        result = fix_in_parentheses("NOT [A] IN ('x') AND [B] IN ('y', 'z')")
        assert "in { 'y', 'z' }" in result

    def test_in_after_postfix_not_in_still_converted(self):
        # Guard fires only on the postfix form: `[A] NOT IN (` — pre-fix this
        # aborted the scan and left the second IN unconverted.
        result = fix_in_parentheses("[A] NOT IN ('x') AND [B] IN ('y', 'z')")
        assert "in { 'y', 'z' }" in result

    def test_no_in_unchanged(self):
        assert fix_in_parentheses("[A] + [B]") == "[A] + [B]"


# ---------------------------------------------------------------------------
# Column scoping
# ---------------------------------------------------------------------------

class TestScopeColumns:
    def test_basic_scoping(self):
        result = scope_columns(
            "[SALES] + [REVENUE]",
            {"SALES": "ORDERS", "REVENUE": "ORDERS"},
        )
        assert "[ORDERS::SALES]" in result
        assert "[ORDERS::REVENUE]" in result

    def test_already_scoped(self):
        result = scope_columns(
            "[ORDERS::SALES]",
            {"SALES": "ORDERS"},
        )
        assert result == "[ORDERS::SALES]"

    def test_formula_names_excluded(self):
        result = scope_columns(
            "[My Formula] + [SALES]",
            {"SALES": "ORDERS", "My Formula": "ORDERS"},
            formula_names={"My Formula"},
        )
        assert "[My Formula]" in result  # not scoped
        assert "[ORDERS::SALES]" in result  # scoped

    def test_parameter_names_excluded(self):
        result = scope_columns(
            "[Metric] + [SALES]",
            {"SALES": "ORDERS"},
            parameter_names={"Metric"},
        )
        assert "[Metric]" in result  # not scoped
        assert "[ORDERS::SALES]" in result

    def test_table_suffix_stripped_when_scoped(self):
        result = scope_columns(
            "sum ( [booked_gbp (agg_lineitem_daily)] )",
            {"booked_gbp (agg_lineitem_daily)": "agg_lineitem_daily"},
        )
        assert "[agg_lineitem_daily::booked_gbp]" in result

    def test_table_suffix_kept_when_table_mismatch(self):
        result = scope_columns(
            "[booked_gbp (other_table)]",
            {"booked_gbp (other_table)": "agg_lineitem_daily"},
        )
        assert "[agg_lineitem_daily::booked_gbp (other_table)]" in result

    def test_no_suffix_still_works(self):
        result = scope_columns(
            "[booked_gbp]",
            {"booked_gbp": "agg_partner_delivery_daily"},
        )
        assert "[agg_partner_delivery_daily::booked_gbp]" in result

    def test_bracket_inside_string_literal_not_consumed(self):
        # A '[' inside a string literal must not let the col-ref regex swallow
        # the real [COL] ref that follows (concat-label pattern).
        result = scope_columns(
            "concat ( '[' , to_string ( [CAMPAIGN_ID] ) , '] ' , [CAMPAIGN_NAME] )",
            {"CAMPAIGN_ID": "PROMO", "CAMPAIGN_NAME": "PROMO"},
        )
        assert "[PROMO::CAMPAIGN_ID]" in result
        assert "[PROMO::CAMPAIGN_NAME]" in result
        assert "'['" in result  # literal preserved, not scoped


class TestConvertBooleanAggregate:
    def test_max_of_comparison_wrapped(self):
        out = convert_boolean_aggregate("max ( [LEVEL]='totalsales' ) = false")
        assert out == "max ( if ( [LEVEL]='totalsales' ) then 1 else 0 ) = 0"

    def test_true_maps_to_one(self):
        out = convert_boolean_aggregate("max ( [LEVEL]='brand' ) = true")
        assert out == "max ( if ( [LEVEL]='brand' ) then 1 else 0 ) = 1"

    def test_inside_group_aggregate(self):
        out = convert_boolean_aggregate(
            "group_aggregate ( max ( [X::LEVEL]='brand' ) , { [X::ID] } , {} ) = false"
        )
        assert "if ( [X::LEVEL]='brand' ) then 1 else 0" in out
        assert out.endswith("{} ) = 0")

    def test_plain_aggregate_untouched(self):
        # No bare comparison inside the aggregate → unchanged.
        expr = "max ( [X::SALES] )"
        assert convert_boolean_aggregate(expr) == expr

    def test_no_false_rewrite_without_bool_agg(self):
        # = false left alone when no boolean-aggregate conversion fired.
        expr = "[X::FLAG] = false"
        assert convert_boolean_aggregate(expr) == expr


# ---------------------------------------------------------------------------
# Mandatory else clause
# ---------------------------------------------------------------------------

class TestEnsureElseClause:
    def test_adds_else_for_measure(self):
        result = ensure_else_clause(
            "if ( [X] > 5 ) then [Sales]",
            role="measure",
        )
        assert "else 0" in result

    def test_adds_else_for_dimension(self):
        result = ensure_else_clause(
            "if ( [X] > 5 ) then 'High'",
            role="dimension",
        )
        assert "else ''" in result

    def test_preserves_existing_else(self):
        expr = "if ( [X] > 5 ) then 'High' else 'Low'"
        result = ensure_else_clause(expr, role="dimension")
        assert result == expr

    def test_nested_if_without_else(self):
        """E2: Inner if/then without else inside a then arm."""
        expr = "if ( [A] > 0 ) then if ( [B] > 0 ) then [C] else 'No'"
        result = ensure_else_clause(expr, role="measure")
        # Should add else for the inner if that has no else
        assert result.count("else") == 2

    def test_two_ifs_one_else(self):
        """E2: Two if/then blocks but only one else."""
        expr = "if ( [A] > 0 ) then if ( [B] > 0 ) then [C] else [D]"
        result = ensure_else_clause(expr, role="measure")
        assert result.count("else") == 2

    def test_all_ifs_have_else(self):
        """No insertion needed when all ifs have else clauses."""
        expr = "if ( [A] > 0 ) then if ( [B] > 0 ) then [C] else [D] else [E]"
        result = ensure_else_clause(expr, role="measure")
        assert result == expr

    def test_sum_if_not_counted(self):
        """E8: sum_if contains 'if' but should not count as a real if keyword."""
        expr = "sum_if ( [Sales] , [Region] = 'West' )"
        result = ensure_else_clause(expr, role="measure")
        assert result == expr

    def test_count_if_not_counted(self):
        """E8: count_if should not trigger else insertion."""
        expr = "count_if ( [Region] = 'West' )"
        result = ensure_else_clause(expr, role="measure")
        assert result == expr

    def test_if_inside_ifnull_inserts_before_comma(self):
        """else clause goes inside ifnull(), before the comma separator."""
        expr = "ifnull ( if ( [X] = 'a' ) then [Y] , 'default' )"
        result = ensure_else_clause(expr, role="dimension")
        assert "else ''" in result
        assert result.index("else ''") < result.index(", 'default'")

    def test_chained_else_if_inside_ifnull(self):
        """Chained else-if inside ifnull — one missing else, inserted before comma."""
        expr = ("ifnull ( if ( [T] = 'A' ) then [X] "
                "else if ( [T] = 'B' ) then [Y] "
                "else if ( [T] = 'C' ) then [Z] , 'Unknown' )")
        result = ensure_else_clause(expr, role="dimension")
        assert "else ''" in result
        assert result.index("else ''") < result.index(", 'Unknown'")

    def test_if_inside_concat_inserts_before_comma(self):
        """else clause goes inside concat(), before the comma separator."""
        expr = "concat ( if ( [X] = 1 ) then 'a' , 'b' )"
        result = ensure_else_clause(expr, role="dimension")
        assert "else ''" in result
        assert result.index("else ''") < result.index(", 'b'")


# ---------------------------------------------------------------------------
# LOD expression conversion
# ---------------------------------------------------------------------------

class TestConvertLod:
    def test_fixed_single_dim(self):
        result = convert_lod("{FIXED [Dim] : SUM([Sales])}")
        assert "group_aggregate ( SUM([Sales]) , { [Dim] } , {} )" in result

    def test_fixed_multi_dim(self):
        result = convert_lod("{FIXED [D1], [D2] : AVG([X])}")
        assert "group_aggregate" in result
        assert "{ [D1] , [D2] }" in result

    def test_include(self):
        result = convert_lod("{INCLUDE [Dim] : SUM([X])}")
        assert "query_groups () + { [Dim] }" in result

    def test_exclude(self):
        result = convert_lod("{EXCLUDE [Dim] : SUM([X])}")
        assert "query_groups () - { [Dim] }" in result

    def test_grand_fixed(self):
        result = convert_lod("{FIXED : MAX([Date])}")
        assert "group_aggregate ( MAX([Date]) , {} , {} )" in result

    def test_exclude_with_calc_ref_in_dims(self):
        """E1: EXCLUDE LOD with Calculation_* ref in dimension list."""
        result = convert_lod(
            "{EXCLUDE [Customer Type], [Redeemer Comp Customer Type] : SUM([Sales])}"
        )
        assert "group_aggregate" in result
        assert "query_groups () - {" in result
        assert "SUM([Sales])" in result

    def test_fixed_with_boolean_in_aggregate(self):
        """E1: FIXED LOD with boolean expression inside MAX."""
        result = convert_lod("{FIXED [PROMOTION_ID] : MAX([LEVEL] = 'category')}")
        assert "group_aggregate" in result
        assert "{ [PROMOTION_ID] }" in result
        assert "MAX([LEVEL] = 'category')" in result

    def test_lod_inside_if_branch(self):
        """E1: LOD expression embedded inside an IF/THEN branch."""
        expr = "IF MAX([LEVEL])='campaign' THEN MAX({FIXED [Campaign] : SUM([Cost])}) ELSE SUM([Cost]) END"
        result = convert_lod(expr)
        assert "group_aggregate ( SUM([Cost]) , { [Campaign] } , {} )" in result
        assert "IF MAX([LEVEL])='campaign'" in result

    def test_nested_lod_innermost_first(self):
        """E1: Nested LODs are resolved inside-out."""
        expr = "{FIXED [A] : MAX({FIXED [B] : SUM([C])})}"
        result = convert_lod(expr)
        # Inner LOD should be converted; outer may produce nested group_aggregate
        assert "group_aggregate" in result
        # The inner {FIXED [B] : SUM([C])} should be resolved
        assert "{FIXED [B]" not in result

    def test_fixed_with_formula_crossref(self):
        """E1: FIXED LOD wrapping a formula cross-reference."""
        result = convert_lod("{FIXED [Campaign] : [Redemption Cost]}")
        assert "group_aggregate ( [Redemption Cost] , { [Campaign] } , {} )" in result

    def test_no_braces_passthrough(self):
        """Expressions without { } pass through unchanged."""
        expr = "SUM([Sales]) / SUM([Cost])"
        assert convert_lod(expr) == expr


# ---------------------------------------------------------------------------
# TOTAL conversion
# ---------------------------------------------------------------------------

class TestConvertTotal:
    def test_basic(self):
        result = convert_total("TOTAL(SUM([Sales]))")
        assert "group_aggregate ( SUM([Sales]) , {} , query_filters () )" in result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateOutput:
    def test_clean(self):
        assert validate_output("if ( [X] > 5 ) then [Sales] else 0") == []

    def test_bare_end(self):
        errors = validate_output("if ( [X] > 5 ) then [Sales] END")
        assert any("END" in e for e in errors)

    def test_bare_case(self):
        errors = validate_output("CASE [X] WHEN 'a' THEN 1")
        assert any("CASE" in e for e in errors)

    def test_unique_count_underscore(self):
        errors = validate_output("unique_count([X])")
        assert any("unique_count" in e for e in errors)

    def test_unmapped_function_flagged(self):
        errors = validate_output("SPLIT ( [Name] , '-' , 1 )")
        assert any("SPLIT" in e for e in errors)

    def test_username_flagged(self):
        errors = validate_output("if ( USERNAME ( ) = 'x' ) then 1 else 0")
        assert any("USERNAME" in e for e in errors)

    def test_untranslated_datepart_flagged(self):
        errors = validate_output("DATEPART ( 'minute' , [TS] )")
        assert any("DATEPART" in e for e in errors)

    def test_untranslated_datediff_flagged(self):
        errors = validate_output("DATEDIFF ( 'fortnight' , [A] , [B] )")
        assert any("DATEDIFF" in e for e in errors)

    def test_untranslated_dateadd_flagged(self):
        errors = validate_output("DATEADD ( 'fortnight' , 2 , [D] )")
        assert any("DATEADD" in e for e in errors)

    def test_inverse_trig_and_cot_rejected(self):
        for fn in ("ACOS", "ASIN", "ATAN", "COT"):
            errors = validate_output(f"{fn} ( [X] )")
            assert errors, f"{fn} should be rejected as unmapped"
            assert any(fn in e for e in errors)

    def test_spatial_functions_rejected(self):
        # Full 13-function Tableau spatial set (audit 13.8) — none has a
        # ThoughtSpot equivalent; all must be rejected loud, not pass through.
        for fn in (
            "MAKEPOINT", "MAKELINE", "DISTANCE", "BUFFER", "AREA",
            "INTERSECTS", "LENGTH", "SHAPETYPE", "OUTLINE",
            "DIFFERENCE", "INTERSECTION", "SYMDIFFERENCE", "VALIDATE",
        ):
            errors = validate_output(f"{fn} ( [X] )")
            assert errors, f"{fn} should be rejected as unmapped"
            assert any(fn in e for e in errors)

    def test_userattribute_functions_rejected(self):
        # Embedded-RLS user-attribute family (audit 13.9) — sibling of
        # USERNAME/FULLNAME/etc, tracked for a future ts_var() translation in BL-071.
        for fn in ("USERATTRIBUTE", "USERATTRIBUTEINCLUDES"):
            errors = validate_output(f"{fn} ( 'region' )")
            assert errors, f"{fn} should be rejected as unmapped"
            assert any(fn in e for e in errors)

    def test_untranslated_datetrunc_flagged(self):
        errors = validate_output("DATETRUNC ( 'hour' , [TS] )")
        assert any("DATETRUNC" in e for e in errors)

    def test_not_in_flagged(self):
        errors = validate_output("if ( [A] NOT IN ('x') ) then 1 else 0")
        assert any("NOT IN" in e for e in errors)


# ---------------------------------------------------------------------------
# Parameter conflict detection
# ---------------------------------------------------------------------------

class TestDetectParamConflicts:
    def test_pass_through(self):
        formulas = [{"caption": "Metric", "formula": "[Parameters].[Metric]"}]
        params = [{"caption": "Metric"}]
        conflicts = detect_param_conflicts(formulas, params)
        assert "Metric" in conflicts
        assert "pass-through" in conflicts["Metric"]

    def test_substantive_formula(self):
        formulas = [{"caption": "Metric", "formula": "IF [Parameters].[Metric]='A' THEN 1 END"}]
        params = [{"caption": "Metric"}]
        conflicts = detect_param_conflicts(formulas, params)
        assert "Metric" in conflicts
        assert "collision" in conflicts["Metric"]

    def test_no_conflict(self):
        formulas = [{"caption": "Sales Total", "formula": "SUM([Sales])"}]
        params = [{"caption": "Metric"}]
        conflicts = detect_param_conflicts(formulas, params)
        assert conflicts == {}


# ---------------------------------------------------------------------------
# Pre-import validation (BL-049 #2)
# ---------------------------------------------------------------------------

class TestValidatePreImport:
    def test_clean(self):
        issues = validate_pre_import([
            {"name": "Sales Total", "expr": "sum ( [ORDERS::SALES] )"},
        ])
        assert len(issues) == 0

    def test_unbalanced_parens(self):
        issues = validate_pre_import([
            {"name": "Bad Formula", "expr": "if ( [X] > 5 then [Y]"},
        ])
        assert len(issues) == 1
        assert any("parentheses" in w for w in issues[0]["warnings"])

    def test_name_clash(self):
        issues = validate_pre_import(
            [{"name": "Sales", "expr": "sum ( [ORDERS::SALES] )"}],
            column_names={"SALES"},
        )
        assert len(issues) == 1
        assert any("clashes" in w for w in issues[0]["warnings"])

    def test_unresolved_csq(self):
        issues = validate_pre_import([
            {"name": "Bad Ref", "expr": "[DATE (Custom SQL Query99)]"},
        ])
        assert len(issues) == 1
        assert any("Custom SQL" in w for w in issues[0]["warnings"])

    def test_if_without_else(self):
        issues = validate_pre_import([
            {"name": "Missing Else", "expr": "if ( [X] > 5 ) then [Y]"},
        ])
        assert len(issues) == 1
        assert any("else" in w for w in issues[0]["warnings"])

    def test_if_without_then(self):
        issues = validate_pre_import([
            {"name": "Bad If", "expr": "if ( [X] > 5 ) [Y] else [Z]"},
        ])
        assert len(issues) == 1
        assert any("then" in w for w in issues[0]["warnings"])

    def test_orphaned_else(self):
        issues = validate_pre_import([
            {"name": "Bad Else", "expr": "[Sales] else [Revenue]"},
        ])
        assert len(issues) == 1
        assert any("Orphaned" in w for w in issues[0]["warnings"])

    def test_keyword_in_column_name_not_flagged(self):
        issues = validate_pre_import([
            {"name": "OK", "expr": "if ( [If Flag] = 'Y' ) then [Then Value] else [Else Value]"},
        ])
        assert len(issues) == 0

    def test_balanced_nested_if(self):
        issues = validate_pre_import([
            {"name": "Nested", "expr": "if ( [A] > 0 ) then if ( [B] > 0 ) then [C] else [D] else [E]"},
        ])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Strip ifnull(X, 0) (BL-046 #1)
# ---------------------------------------------------------------------------

class TestStripIfnullZero:
    def test_basic_strip(self):
        result = strip_ifnull_zero("ifnull ( [Sales] , 0 )")
        assert result == "[Sales]"

    def test_nested_strip(self):
        result = strip_ifnull_zero("ifnull ( sum ( [Sales] ) , 0 )")
        assert result == "sum ( [Sales] )"

    def test_non_zero_default_preserved(self):
        result = strip_ifnull_zero("ifnull ( [Sales] , -1 )")
        assert "ifnull" in result
        assert "-1" in result

    def test_string_default_preserved(self):
        result = strip_ifnull_zero("ifnull ( [Name] , 'N/A' )")
        assert "ifnull" in result

    def test_multiple_ifnull(self):
        result = strip_ifnull_zero("ifnull ( [A] , 0 ) + ifnull ( [B] , 0 )")
        assert "ifnull" not in result
        assert "[A]" in result
        assert "[B]" in result

    def test_mixed_defaults(self):
        result = strip_ifnull_zero("ifnull ( [A] , 0 ) + ifnull ( [B] , -1 )")
        assert "[A]" in result
        assert "ifnull ( [B] , -1 )" in result

    def test_no_ifnull(self):
        assert strip_ifnull_zero("[Sales] + [Revenue]") == "[Sales] + [Revenue]"

    def test_zn_converted_then_stripped(self):
        """ZN maps to ifnull(X, 0) in map_functions; strip removes it."""
        from ts_cli.tableau_translate import map_functions
        zn_result = map_functions("ZN([Sales])")
        stripped = strip_ifnull_zero(zn_result)
        assert "ifnull" not in stripped
        assert "[Sales]" in stripped


# ---------------------------------------------------------------------------
# agg(if...else 0/null) → agg_if (BL-046 #2)
# ---------------------------------------------------------------------------

class TestConvertAggIf:
    def test_sum_if(self):
        result = convert_agg_if("sum ( if ( [PERIOD] = 'promo' ) then [SALES] else 0 )")
        assert "sum_if" in result
        assert "[PERIOD] = 'promo'" in result
        assert "[SALES]" in result
        assert "else" not in result

    def test_count_if(self):
        result = convert_agg_if("count ( if ( [Active] = 1 ) then [ID] else null )")
        assert "count_if" in result
        assert "[Active] = 1" in result
        assert "[ID]" in result

    def test_average_if(self):
        result = convert_agg_if("average ( if ( [Type] = 'A' ) then [Score] else 0 )")
        assert "average_if" in result

    def test_no_conversion_without_if(self):
        result = convert_agg_if("sum ( [Sales] )")
        assert result == "sum ( [Sales] )"
        assert "sum_if" not in result

    def test_no_conversion_with_nonzero_else(self):
        result = convert_agg_if("sum ( if ( [X] > 0 ) then [Y] else -1 )")
        assert "sum_if" not in result
        assert "sum" in result

    def test_nested_if_in_then(self):
        expr = "sum ( if ( [A] > 0 ) then if ( [B] > 0 ) then [C] else [D] else 0 )"
        result = convert_agg_if(expr)
        assert "sum_if" in result
        assert "[A] > 0" in result
        assert "[C]" in result

    def test_no_else_implicit_null(self):
        result = convert_agg_if("sum ( if ( [Active] = 1 ) then [Sales] )")
        assert "sum_if" in result
        assert "[Active] = 1" in result
        assert "[Sales]" in result

    def test_max_not_converted(self):
        result = convert_agg_if("max ( if ( [X] > 0 ) then [Y] else 0 )")
        assert "max" in result
        assert "_if" not in result

    def test_unique_count_if(self):
        result = convert_agg_if("unique count ( if ( [Cohort] = 'New' ) then [ID] )")
        assert "unique_count_if" in result
        assert "unique count_if" not in result
        assert "[Cohort] = 'New'" in result
        assert "[ID]" in result


# ---------------------------------------------------------------------------
# Dependency DAG
# ---------------------------------------------------------------------------

class TestBuildDependencyDag:
    def test_level_assignment(self):
        formulas = [
            {"caption": "Base", "name": "Calculation_1", "formula": "SUM([Sales])"},
            {"caption": "Derived", "name": "Calculation_2",
             "formula": "[Calculation_1] * 2"},
        ]
        dag = build_dependency_dag(formulas)
        assert dag["Base"]["level"] == 0
        assert dag["Derived"]["level"] == 1

    def test_no_deps(self):
        formulas = [
            {"caption": "Simple", "name": "Calculation_1", "formula": "[Sales] + 1"},
        ]
        dag = build_dependency_dag(formulas)
        assert dag["Simple"]["level"] == 0


# ---------------------------------------------------------------------------
# Full translate_single pipeline
# ---------------------------------------------------------------------------

class TestTranslateSingle:
    def test_simple_if(self):
        expr, errors, _ = translate_single(
            "IF [PERIOD_TYPE]='pre' THEN [CPG_SALES] END",
            role="measure",
        )
        assert "if" in expr
        assert "END" not in expr
        assert "else 0" in expr
        assert errors == []

    def test_case_with_params(self):
        expr, errors, _ = translate_single(
            "CASE [Parameters].[Parameter 3 1]\nWHEN 'Sales' THEN [SALES]\nWHEN 'Revenue' THEN [REVENUE]\nEND",
            role="measure",
            param_map={"Parameter 3 1": "Metric"},
        )
        assert "[Parameters]" not in expr
        assert "CASE" not in expr
        assert "WHEN" not in expr
        assert "[Metric]" in expr
        assert errors == []

    def test_datetrunc_date(self):
        expr, errors, _ = translate_single(
            "DATE(DATETRUNC('month', [DATE]))",
            role="dimension",
        )
        assert "start_of_month" in expr
        assert "date" in expr
        assert errors == []

    def test_zn_expression(self):
        expr, errors, _ = translate_single(
            "ZN([Sales]) + ZN([Revenue])",
            role="measure",
        )
        # ifnull(X, 0) auto-stripped for measures (BL-046 #1)
        assert "ifnull" not in expr
        assert "ZN" not in expr
        assert "[Sales]" in expr
        assert "[Revenue]" in expr

    def test_column_scoping(self):
        expr, errors, _ = translate_single(
            "SUM([SALES])",
            role="measure",
            scoped_columns={"SALES": "ORDERS"},
        )
        assert "[ORDERS::SALES]" in expr

    def test_datediff_reorder(self):
        expr, errors, _ = translate_single(
            "DATEDIFF('day', [Start], [End])",
            role="measure",
        )
        assert "diff_days ( [End] , [Start] )" in expr


# ---------------------------------------------------------------------------
# Full pipeline: translate_formulas batch
# ---------------------------------------------------------------------------

class TestTranslateFormulas:
    def test_basic_batch(self):
        formulas = [
            {
                "caption": "Sales Pre",
                "name": "Calculation_1",
                "formula": "IF [PERIOD]='pre' THEN [SALES] END",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
            {
                "caption": "Revenue",
                "name": "Calculation_2",
                "formula": "SUM([REVENUE])",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
        ]
        result = translate_formulas(formulas)
        assert result["stats"]["total"] == 2
        assert result["stats"]["translated"] == 2
        assert result["stats"]["skipped"] == 0
        assert len(result["translated"]) == 2

    def test_cross_reference_resolution(self):
        formulas = [
            {
                "caption": "Base Sales",
                "name": "Calculation_100",
                "formula": "SUM([SALES])",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
            {
                "caption": "Percent of Sales",
                "name": "Calculation_200",
                "formula": "[Calculation_100] / 100",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
        ]
        result = translate_formulas(formulas)
        assert result["stats"]["translated"] == 2
        # The derived formula should have resolved the cross-reference
        derived = next(t for t in result["translated"] if t["name"] == "Percent of Sales")
        assert "Calculation_" not in derived["expr"]

    def test_param_conflict_passthrough_skipped(self):
        formulas = [
            {
                "caption": "Metric",
                "name": "Calculation_1",
                "formula": "[Parameters].[Metric]",
                "role": "dimension",
                "datatype": "string",
                "datasource": "test",
            },
        ]
        parameters = [{"caption": "Metric"}]
        result = translate_formulas(formulas, parameters=parameters)
        assert result["stats"]["skipped"] == 1
        assert "pass-through" in result["skipped"][0]["reason"]

    def test_stats_include_levels(self):
        formulas = [
            {
                "caption": "A",
                "name": "Calculation_1",
                "formula": "[Sales]",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
        ]
        result = translate_formulas(formulas)
        assert 0 in result["stats"]["levels"]


# ---------------------------------------------------------------------------
# Integration: pre-transforms through translate_single pipeline
# ---------------------------------------------------------------------------

class TestPreTransformIntegration:
    def test_comment_stripped_before_translation(self):
        expr, errors, _ = translate_single(
            "[Lift] / [Cost] //SUM([Redemption Cost])",
            role="measure",
        )
        assert "Redemption" not in expr
        assert errors == []

    def test_csq_alias_rewritten(self):
        expr, errors, _ = translate_single(
            "SUM([SALES (Custom SQL Query8)])",
            role="measure",
            csq_to_table={"Custom SQL Query8": "FORECAST"},
        )
        assert "[FORECAST::SALES]" in expr
        assert "Custom SQL" not in expr
        assert errors == []

    def test_no_keyword_lod_translated(self):
        expr, errors, _ = translate_single(
            "{COUNTD([PROMOTION_ID])}",
            role="measure",
        )
        assert "group_aggregate" in expr
        assert "unique count" in expr
        assert errors == []

    def test_scalar_max_rewritten(self):
        expr, errors, _ = translate_single(
            "MAX([Profit], 0)",
            role="measure",
        )
        assert "greatest ( [Profit] , 0 )" in expr
        assert errors == []

    def test_date_arithmetic_rewritten(self):
        expr, errors, _ = translate_single(
            "DATE([START_DATE]) + 1",
            role="dimension",
        )
        assert "add_days" in expr
        assert errors == []

    def test_cpg_merch_isr_formula(self):
        """Real formula from CPG Merch migration: ISR 30D with comment."""
        expr, errors, _ = translate_single(
            "[Lift] / [Cost] //SUM([Redemption Cost])",
            role="measure",
            scoped_columns={"Lift": "PROMO", "Cost": "PROMO"},
        )
        assert "[PROMO::Lift]" in expr
        assert "[PROMO::Cost]" in expr
        assert "Redemption" not in expr

    def test_cpg_merch_forecast_csq(self):
        """Real pattern from CPG Merch: Custom SQL Query8 → FORECAST."""
        expr, errors, _ = translate_single(
            "IF [PERIOD_TYPE (Custom SQL Query8)] = 'promo' THEN [SALES (Custom SQL Query8)] END",
            role="measure",
            csq_to_table={"Custom SQL Query8": "FORECAST"},
        )
        assert "[FORECAST::PERIOD_TYPE]" in expr
        assert "[FORECAST::SALES]" in expr
        assert "Custom SQL" not in expr
        assert "else 0" in expr

    def test_operator_spacing_in_pipeline(self):
        expr, errors, _ = translate_single("[A]-[B]", role="measure")
        assert "-" in expr
        assert errors == []

    def test_rank_completion_in_pipeline(self):
        expr, errors, _ = translate_single("RANK([Sales])", role="measure")
        assert "'desc'" in expr
        assert errors == []

    def test_ifnull_stripped_for_measure(self):
        """ZN wrapping on a measure is automatically stripped."""
        expr, errors, notes = translate_single(
            "ZN([Sales])",
            role="measure",
        )
        assert "ifnull" not in expr
        assert "[Sales]" in expr
        assert notes.get("ifnull_stripped") == 1
        assert errors == []

    def test_ifnull_preserved_for_dimension(self):
        """ifnull stripping only applies to measures."""
        expr, errors, notes = translate_single(
            "ZN([Name])",
            role="dimension",
        )
        assert "ifnull" in expr
        assert notes.get("ifnull_stripped") is None

    def test_sum_if_conversion(self):
        """SUM(IF cond THEN measure END) → sum_if(cond, measure)."""
        expr, errors, notes = translate_single(
            "SUM(IF [PERIOD_TYPE]='promo' THEN [SALES] END)",
            role="measure",
        )
        assert "sum_if" in expr
        assert "PERIOD_TYPE" in expr
        assert "SALES" in expr
        assert notes.get("agg_if_converted") == 1
        assert errors == []

    def test_cpg_merch_full_pattern(self):
        """Real CPG pattern: SUM(IF...THEN...END) with CSQ aliases."""
        expr, errors, notes = translate_single(
            "SUM(IF [PERIOD_TYPE (Custom SQL Query8)] = 'promo' THEN [SALES (Custom SQL Query8)] END)",
            role="measure",
            csq_to_table={"Custom SQL Query8": "FORECAST"},
        )
        assert "sum_if" in expr
        assert "[FORECAST::PERIOD_TYPE]" in expr or "PERIOD_TYPE" in expr
        assert "[FORECAST::SALES]" in expr or "SALES" in expr
        assert "Custom SQL" not in expr
        assert errors == []


class TestBatchIntegration:
    def test_param_sanitisation(self):
        """Parameter with / in name gets sanitised across all formula refs."""
        formulas = [
            {
                "caption": "Platform Filter",
                "name": "Calculation_1",
                "formula": "IF [Parameters].[Platform/Placement] = 'web' THEN [SALES] END",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
        ]
        parameters = [{"caption": "Platform/Placement"}]
        result = translate_formulas(formulas, parameters=parameters)
        assert result["stats"]["param_renames"] == 1
        if result["translated"]:
            assert "Platform/Placement" not in result["translated"][0]["expr"]

    def test_name_clash_auto_rename(self):
        """Formula named 'Sales' collides with column 'SALES'."""
        formulas = [
            {
                "caption": "Sales",
                "name": "Calculation_1",
                "formula": "SUM([REVENUE])",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
        ]
        result = translate_formulas(
            formulas,
            scoped_columns={"SALES": "ORDERS", "REVENUE": "ORDERS"},
        )
        assert result["stats"]["name_clashes"] == 1
        assert result["translated"][0]["name"] == "Formula Sales"

    def test_ifnull_and_agg_if_stats(self):
        """Batch stats report ifnull stripping and agg_if conversions."""
        formulas = [
            {
                "caption": "Promo Sales",
                "name": "Calculation_1",
                "formula": "SUM(IF [PERIOD]='promo' THEN [SALES] END)",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
            {
                "caption": "Safe Revenue",
                "name": "Calculation_2",
                "formula": "ZN([REVENUE])",
                "role": "measure",
                "datatype": "real",
                "datasource": "test",
            },
        ]
        result = translate_formulas(formulas)
        assert result["stats"]["agg_if_conversions"] >= 1
        assert result["stats"]["ifnull_stripped"] >= 1
        t1 = next(t for t in result["translated"] if t["name"] == "Promo Sales")
        assert "sum_if" in t1["expr"]
        t2 = next(t for t in result["translated"] if t["name"] == "Safe Revenue")
        assert "ifnull" not in t2["expr"]


# ---------------------------------------------------------------------------
# TML YAML serialization (E4)
# ---------------------------------------------------------------------------

class TestDumpTmlYaml:
    def test_formula_expr_quoted(self):
        tml = {"model": {"formulas": [
            {"id": "formula_Rev", "name": "Rev", "expr": "sum ( [TABLE::COL] )"}
        ]}}
        out = dump_tml_yaml(tml)
        assert '"sum ( [TABLE::COL] )"' in out

    def test_no_line_wrap(self):
        long_expr = "if ( " + " and ".join(f"[COL_{i}] > 0" for i in range(30)) + " ) then 1 else 0"
        tml = {"model": {"formulas": [{"expr": long_expr}]}}
        out = dump_tml_yaml(tml)
        expr_lines = [l for l in out.split("\n") if "if (" in l or "COL_" in l]
        assert len(expr_lines) == 1

    def test_on_key_preserved(self):
        tml = {"model": {"model_tables": [{"joins": [
            {"with": "DIM", "on": "[FACT::FK] = [DIM::PK]"}
        ]}]}}
        out = dump_tml_yaml(tml)
        assert "'on':" in out
        assert '"[FACT::FK] = [DIM::PK]"' in out

    def test_plain_strings_unquoted(self):
        tml = {"model": {"name": "My Model"}}
        out = dump_tml_yaml(tml)
        assert "name: My Model" in out
        assert '"My Model"' not in out


# ---------------------------------------------------------------------------
# validate_pre_import — new checks (B2)
# ---------------------------------------------------------------------------

class TestValidatePreImportNewChecks:

    def test_in_with_parens_flagged(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "if [T::Status] in ('A', 'B') then 1 else 0"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 1
        assert any("curly braces" in w for w in issues[0]["warnings"])

    def test_in_with_curly_braces_passes(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "if [T::Status] in {'A', 'B'} then 1 else 0"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 0

    def test_add_quarters_flagged(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "add_quarters ( [T::Date] , 1 )"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 1
        assert any("add_quarters" in w for w in issues[0]["warnings"])

    def test_add_years_flagged(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "add_years ( [T::Date] , 2 )"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 1
        assert any("add_years" in w for w in issues[0]["warnings"])

    def test_add_months_passes(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "add_months ( [T::Date] , 3 )"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 0

    def test_bare_date_literal_flagged(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "if [T::Date] > '2024-01-01' then 1 else 0"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 1
        assert any("Bare date literal" in w for w in issues[0]["warnings"])

    def test_date_in_to_date_passes(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "F1", "expr": "if [T::Date] > to_date( '2024-01-01' , 'yyyy-MM-dd' ) then 1 else 0"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 0

    def test_max_bool_false_warns(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "Active Flag", "expr": "max([T::STATUS]='ACTIVE')=false"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 1
        assert "max([col]='value')=false" in issues[0]["warnings"][0]

    def test_max_without_bool_no_warning(self):
        from ts_cli.tableau_translate import validate_pre_import
        formulas = [{"name": "Max Sales", "expr": "max([T::SALES])"}]
        issues = validate_pre_import(formulas)
        assert len(issues) == 0
