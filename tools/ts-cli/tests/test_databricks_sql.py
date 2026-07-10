# tools/ts-cli/tests/test_databricks_sql.py
"""Unit tests for ts_cli/databricks/mv_sql.py (BL-063 PR3).

One class per transform, mirroring test_tableau_translate.py. resolver is a
plain fake mapping bare/dotted paths onto a TRANSACTIONS table.
"""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import UntranslatableError, translate_sql_expr


def _resolver(path: str) -> str:
    from ts_cli.databricks.mv_expr import split_dot_path
    segs = split_dot_path(path)
    return f"[TRANSACTIONS::{segs[-1]}]"


def t(sql: str) -> str:
    return translate_sql_expr(sql, _resolver)


class TestCore:
    def test_bare_column(self):
        assert t("unit_price") == "[TRANSACTIONS::unit_price]"

    def test_dotted_column(self):
        assert t("source.unit_price") == "[TRANSACTIONS::unit_price]"

    def test_arithmetic_spacing(self):
        assert t("unit_price * quantity * (1 - discount)") == \
            "[TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] )"

    def test_comparison_and_string(self):
        assert t("status != 'cancelled'") == "[TRANSACTIONS::status] != 'cancelled'"

    def test_angle_neq_normalized(self):
        assert t("status <> 'x'") == "[TRANSACTIONS::status] != 'x'"

    def test_and_or_lowercased(self):
        assert t("a = 1 AND b = 2 OR c = 3") == \
            "[TRANSACTIONS::a] = 1 and [TRANSACTIONS::b] = 2 or [TRANSACTIONS::c] = 3"

    def test_true_false_null_lowercased(self):
        assert t("flag = TRUE") == "[TRANSACTIONS::flag] = true"
        assert t("flag = FALSE") == "[TRANSACTIONS::flag] = false"

    def test_date_literal_wrapped(self):
        assert t("d >= '2024-05-01'") == \
            "[TRANSACTIONS::d] >= to_date ( '2024-05-01' , 'yyyy-MM-dd' )"

    def test_plain_string_not_wrapped(self):
        assert t("s = 'Premium'") == "[TRANSACTIONS::s] = 'Premium'"

    def test_placeholder_passthrough(self):
        assert t("__MVREF_0__ / __MVREF_1__") == "__MVREF_0__ / __MVREF_1__"

    def test_number_decimal(self):
        assert t("x * 0.5") == "[TRANSACTIONS::x] * 0.5"

    def test_unknown_operator_raises(self):
        with pytest.raises(UntranslatableError, match=r"\|\|"):
            t("a || b")

    def test_unresolvable_column_raises(self):
        def bad(_path):
            raise UntranslatableError("no table mapped")
        with pytest.raises(UntranslatableError, match="no table mapped"):
            translate_sql_expr("x + 1", bad)

    def test_comment_stripped_before_translation(self):
        assert t("unit_price -- the price") == "[TRANSACTIONS::unit_price]"

    def test_empty_expression_raises(self):
        with pytest.raises(UntranslatableError, match="empty"):
            t("   ")

    def test_current_date_bare_and_called(self):
        assert t("CURRENT_DATE") == "today ( )"
        assert t("d < CURRENT_DATE()") == "[TRANSACTIONS::d] < today ( )"


class TestFunctions:
    def test_sum_arithmetic(self):
        assert t("SUM(unit_price * quantity * (1 - discount))") == \
            "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] ) )"

    def test_count_star(self):
        assert t("COUNT(*)") == "count ( 1 )"

    def test_count_distinct(self):
        assert t("COUNT(DISTINCT customer_id)") == \
            "unique count ( [TRANSACTIONS::customer_id] )"

    def test_distinct_under_sum_raises(self):
        with pytest.raises(UntranslatableError, match="DISTINCT"):
            t("SUM(DISTINCT x)")

    def test_ratio_of_aggregates(self):
        assert t("SUM(unit_price * quantity) / COUNT(DISTINCT transaction_id)") == \
            "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) / unique count ( [TRANSACTIONS::transaction_id] )"

    def test_avg_renamed(self):
        assert t("AVG(tenure)") == "average ( [TRANSACTIONS::tenure] )"

    def test_date_trunc_month(self):
        assert t("DATE_TRUNC('MONTH', transaction_date)") == \
            "start_of_month ( [TRANSACTIONS::transaction_date] )"

    def test_date_trunc_day_is_date(self):
        assert t("date_trunc('day', ts_col)") == "date ( [TRANSACTIONS::ts_col] )"

    def test_date_trunc_unknown_unit_raises(self):
        with pytest.raises(UntranslatableError, match="hour"):
            t("DATE_TRUNC('hour', ts_col)")

    def test_extract_year(self):
        assert t("EXTRACT(YEAR FROM d)") == "year ( [TRANSACTIONS::d] )"

    def test_extract_month(self):
        assert t("EXTRACT(MONTH FROM d)") == "month_number ( [TRANSACTIONS::d] )"

    def test_datediff_2arg_swaps(self):
        assert t("DATEDIFF(end_d, start_d)") == \
            "diff_days ( [TRANSACTIONS::start_d] , [TRANSACTIONS::end_d] )"

    def test_datediff_3arg_month(self):
        assert t("DATEDIFF(MONTH, start_d, end_d)") == \
            "diff_months ( [TRANSACTIONS::start_d] , [TRANSACTIONS::end_d] )"

    def test_months_between_swaps(self):
        assert t("MONTHS_BETWEEN(end_d, start_d)") == \
            "diff_months ( [TRANSACTIONS::start_d] , [TRANSACTIONS::end_d] )"

    def test_locate_swaps(self):
        assert t("LOCATE(sub, s)") == \
            "strpos ( [TRANSACTIONS::s] , [TRANSACTIONS::sub] )"

    def test_power_is_pow(self):
        assert t("POWER(x, 2)") == "pow ( [TRANSACTIONS::x] , 2 )"

    def test_if_comma_form(self):
        assert t("IF(x > 1, 'a', 'b')") == \
            "if ( [TRANSACTIONS::x] > 1 , 'a' , 'b' )"

    def test_unknown_function_raises_with_doc_pointer(self):
        with pytest.raises(UntranslatableError,
                           match="MEDIAN.*ts-databricks-formula-translation"):
            t("MEDIAN(x)")

    def test_passthrough_hint(self):
        with pytest.raises(UntranslatableError, match="sql_string_op"):
            t("LOWER(s)")

    def test_to_date_args_not_double_wrapped(self):
        assert t("d >= TO_DATE('2024-05-01', 'yyyy-MM-dd')") == \
            "[TRANSACTIONS::d] >= to_date ( '2024-05-01' , 'yyyy-MM-dd' )"


class TestCaseWhen:
    def test_single_branch_golden(self):
        # ts-from-databricks.md Measure 6
        assert t("SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END)") == \
            "sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) )"

    def test_multi_branch_golden(self):
        # ts-from-databricks-sql-view.md Customer Segment
        assert t("CASE WHEN total_amount > 1000 THEN 'Premium' "
                 "WHEN total_amount > 100 THEN 'Standard' ELSE 'Basic' END") == \
            ("if ( [TRANSACTIONS::total_amount] > 1000 , 'Premium' , "
             "if ( [TRANSACTIONS::total_amount] > 100 , 'Standard' , 'Basic' ) )")

    def test_no_else_defaults_null(self):
        assert t("CASE WHEN x = 1 THEN 'y' END") == \
            "if ( [TRANSACTIONS::x] = 1 , 'y' , null )"


class TestPostfixConstructs:
    def test_not_column_equals_false(self):
        assert t("NOT is_return AND status = 'Completed'") == \
            "[TRANSACTIONS::is_return] = false and [TRANSACTIONS::status] = 'Completed'"

    def test_not_group(self):
        assert t("NOT (a = 1)") == "not ( ( [TRANSACTIONS::a] = 1 ) )"

    def test_in_expands_to_ors(self):
        assert t("status IN ('Completed', 'Shipped')") == \
            "( [TRANSACTIONS::status] = 'Completed' or [TRANSACTIONS::status] = 'Shipped' )"

    def test_between(self):
        assert t("churn_date BETWEEN '2024-05-01' AND '2025-04-30'") == \
            ("[TRANSACTIONS::churn_date] >= to_date ( '2024-05-01' , 'yyyy-MM-dd' ) "
             "and [TRANSACTIONS::churn_date] <= to_date ( '2025-04-30' , 'yyyy-MM-dd' )")

    def test_is_null(self):
        assert t("x IS NULL") == "isnull ( [TRANSACTIONS::x] )"

    def test_is_not_null(self):
        assert t("x IS NOT NULL") == "not ( isnull ( [TRANSACTIONS::x] ) )"

    def test_cast_unwraps_golden(self):
        # ts-from-databricks.md Measure 6 (full shape covered in golden task)
        assert t("CAST(SUM(x) AS DOUBLE) / COUNT(*)") == \
            "sum ( [TRANSACTIONS::x] ) / count ( 1 )"

    def test_like_raises(self):
        with pytest.raises(UntranslatableError, match="LIKE"):
            t("s LIKE 'a%'")

    def test_not_in_raises(self):
        with pytest.raises(UntranslatableError, match="NOT IN"):
            t("x NOT IN (1, 2)")

    def test_not_comparison_wraps(self):
        assert t("NOT status = 'Completed'") == \
            "not ( [TRANSACTIONS::status] = 'Completed' )"

    def test_not_is_null_wraps(self):
        assert t("NOT x IS NULL") == "not ( isnull ( [TRANSACTIONS::x] ) )"

    def test_nullif_marker_never_leaks_through_is(self):
        assert t("NULLIF(x, 0) IS NULL") == \
            "isnull ( null_if_zero ( [TRANSACTIONS::x] ) )"

    def test_not_ident_in_translates_via_expr(self):
        # NOT x IN (…) with the ident before IN routes through _expr:
        assert t("NOT x IN (1, 2)") == \
            "not ( ( [TRANSACTIONS::x] = 1 or [TRANSACTIONS::x] = 2 ) )"

    def test_not_flag_inside_case(self):
        assert t("CASE WHEN NOT is_return THEN 1 ELSE 0 END") == \
            "if ( [TRANSACTIONS::is_return] = false , 1 , 0 )"

    def test_not_comparison_inside_case(self):
        assert t("CASE WHEN NOT status = 'x' THEN 1 ELSE 0 END") == \
            "if ( not ( [TRANSACTIONS::status] = 'x' ) , 1 , 0 )"

    def test_between_compound_left_operand_raises(self):
        with pytest.raises(UntranslatableError, match="parenthesize"):
            t("price * qty BETWEEN 10 AND 20")

    def test_is_compound_left_operand_raises(self):
        with pytest.raises(UntranslatableError, match="parenthesize"):
            t("a + b IS NULL")

    def test_between_parenthesized_compound_translates(self):
        assert t("(price * qty) BETWEEN 10 AND 20") == (
            "( [TRANSACTIONS::price] * [TRANSACTIONS::qty] ) >= 10 and "
            "( [TRANSACTIONS::price] * [TRANSACTIONS::qty] ) <= 20")

    def test_and_in_guard_rail_still_translates(self):
        # 'and'/'or' are deliberately excluded from the compound-operand
        # guard — b IN (...) after 'a = 1 AND' must still pop b, not raise.
        assert t("a = 1 AND status IN ('x', 'y')") == (
            "[TRANSACTIONS::a] = 1 and "
            "( [TRANSACTIONS::status] = 'x' or [TRANSACTIONS::status] = 'y' )")


class TestTruncatedInput:
    def test_dangling_is_raises(self):
        with pytest.raises(UntranslatableError, match="end of expression"):
            t("x IS")

    def test_dangling_cast_raises(self):
        with pytest.raises(UntranslatableError, match="end of expression"):
            t("CAST(x AS")


class TestSafeDivide:
    def test_divide_by_nullif(self):
        assert t("SUM(a) / NULLIF(SUM(b), 0)") == \
            "safe_divide ( sum ( [TRANSACTIONS::a] ) , sum ( [TRANSACTIONS::b] ) )"

    def test_coalesce_safe_divide_zero(self):
        assert t("COALESCE(SUM(a) / NULLIF(SUM(b), 0), 0)") == \
            "safe_divide ( sum ( [TRANSACTIONS::a] ) , sum ( [TRANSACTIONS::b] ) )"

    def test_standalone_nullif_zero(self):
        assert t("NULLIF(x, 0)") == "null_if_zero ( [TRANSACTIONS::x] )"

    def test_nullif_nonzero_raises(self):
        with pytest.raises(UntranslatableError, match="NULLIF"):
            t("NULLIF(x, 5)")

    def test_coalesce_two_args(self):
        assert t("COALESCE(a, b)") == \
            "if ( [TRANSACTIONS::a] != null ) then [TRANSACTIONS::a] else [TRANSACTIONS::b]"

    def test_coalesce_three_args_raises(self):
        with pytest.raises(UntranslatableError, match="COALESCE"):
            t("COALESCE(a, b, c)")
