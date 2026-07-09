# tools/ts-cli/tests/test_databricks_parse.py
"""Unit tests for ts_cli/databricks/mv_parse.py (BL-063 PR2 — ts databricks parse-mv).

One class per transform, mirroring test_tableau_translate.py. Pure functions
only until the CLI-command class at the bottom — no live connection anywhere.
"""
from __future__ import annotations

from ts_cli.databricks.mv_parse import (
    classify_dimension_expr,
    classify_measure_expr,
    classify_source,
    extract_cross_refs,
    parse_offset,
    parse_range,
    parse_window,
    strip_sql_comments,
)


class TestStripSqlComments:
    def test_line_comment_stripped(self):
        assert strip_sql_comments("SUM(x) -- total") == "SUM(x)"

    def test_block_comment_stripped(self):
        assert strip_sql_comments("SUM(/* the amount */ x)") == "SUM(  x)"

    def test_multiline_block_comment(self):
        assert strip_sql_comments("SUM(x)\n/* a\nb */\n+ 1") == "SUM(x)\n \n+ 1"

    def test_no_comment_untouched(self):
        assert strip_sql_comments("a - b") == "a - b"


class TestClassifySource:
    def test_table_fqn(self):
        src = classify_source("catalog.schema.fact_table")
        assert src == {
            "kind": "table_fqn",
            "raw": "catalog.schema.fact_table",
            "parts": ["catalog", "schema", "fact_table"],
            "needs_live_check": True,
        }

    def test_backtick_fqn_parts_unquoted(self):
        src = classify_source("`my-cat`.`my sch`.`fact`")
        assert src["kind"] == "table_fqn"
        assert src["parts"] == ["my-cat", "my sch", "fact"]

    def test_backtick_fqn_with_dot_inside_segment(self):
        src = classify_source("`c.dev`.sch.fact")
        assert src["parts"] == ["c.dev", "sch", "fact"]

    def test_two_part_fqn_has_null_parts(self):
        src = classify_source("schema.table_only")
        assert src["kind"] == "table_fqn"
        assert src["parts"] is None
        assert src["needs_live_check"] is True

    def test_parenthesized_sql(self):
        src = classify_source("(SELECT a, b FROM t)")
        assert src == {"kind": "sql_query", "raw": "(SELECT a, b FROM t)",
                       "parenthesized": True}

    def test_bare_sql(self):
        src = classify_source("SELECT a, b FROM t")
        assert src["kind"] == "sql_query"
        assert src["parenthesized"] is False

    def test_bare_with_cte(self):
        assert classify_source("WITH c AS (SELECT 1) SELECT * FROM c")["kind"] == "sql_query"

    def test_parenthesized_cte_case_insensitive(self):
        assert classify_source("(with c as (select 1) select * from c)")["kind"] == "sql_query"

    def test_leading_whitespace_stripped(self):
        assert classify_source("  select 1 ")["kind"] == "sql_query"

    def test_unrecognized_returns_none(self):
        assert classify_source("???not a source") is None

    def test_empty_returns_none(self):
        assert classify_source("") is None


class TestParseRange:
    def test_current(self):
        assert parse_range("current") == {"type": "current", "n": None,
                                          "unit": None, "anchor": None}

    def test_cumulative(self):
        assert parse_range("cumulative")["type"] == "cumulative"

    def test_all(self):
        assert parse_range("all")["type"] == "all"

    def test_trailing_default_anchor_is_exclusive(self):
        assert parse_range("trailing 7 day") == {"type": "trailing", "n": 7,
                                                 "unit": "day", "anchor": "exclusive"}

    def test_trailing_inclusive(self):
        assert parse_range("trailing 30 day inclusive")["anchor"] == "inclusive"

    def test_leading_exclusive_explicit(self):
        assert parse_range("leading 7 day exclusive") == {"type": "leading", "n": 7,
                                                          "unit": "day", "anchor": "exclusive"}

    def test_case_and_whitespace_insensitive(self):
        assert parse_range("  Trailing 7 DAY  ")["type"] == "trailing"

    def test_month_unit(self):
        assert parse_range("trailing 3 month")["unit"] == "month"

    def test_modifier_on_current_rejected(self):
        assert parse_range("current inclusive") is None

    def test_modifier_on_all_rejected(self):
        assert parse_range("all exclusive") is None

    def test_garbage_rejected(self):
        assert parse_range("trailing seven day") is None

    def test_missing_unit_rejected(self):
        assert parse_range("trailing 7") is None


class TestParseOffset:
    def test_negative_month(self):
        assert parse_offset("-1 month") == {"n": -1, "unit": "month"}

    def test_negative_year(self):
        assert parse_offset("-1 year") == {"n": -1, "unit": "year"}

    def test_positive_rejected(self):
        assert parse_offset("1 month") is None

    def test_garbage_rejected(self):
        assert parse_offset("last month") is None


class TestParseWindow:
    def _win(self, **overrides):
        w = {"order": "order_month", "range": "current", "semiadditive": "last"}
        w.update(overrides)
        return [w]

    def test_valid_current_window(self):
        win, problems = parse_window(self._win(), "m")
        assert problems == []
        assert win["order"] == "order_month"
        assert win["range"]["type"] == "current"
        assert win["semiadditive"] == "last"
        assert win["offset"] is None
        assert win["density_check_required"] is False

    def test_offset_parsed(self):
        win, problems = parse_window(self._win(offset="-1 month"), "m")
        assert problems == []
        assert win["offset"] == {"n": -1, "unit": "month"}
        assert win["raw_offset"] == "-1 month"

    def test_trailing_sets_density_flag(self):
        win, problems = parse_window(self._win(range="trailing 7 day"), "m")
        assert problems == []
        assert win["density_check_required"] is True

    def test_leading_sets_density_flag(self):
        win, _ = parse_window(self._win(range="leading 7 day inclusive"), "m")
        assert win["density_check_required"] is True

    def test_cumulative_no_density_flag(self):
        win, _ = parse_window(self._win(range="cumulative"), "m")
        assert win["density_check_required"] is False

    def test_missing_semiadditive_fails(self):
        w = [{"order": "d", "range": "current"}]
        win, problems = parse_window(w, "m")
        assert win is None
        assert any("semiadditive" in p for p in problems)

    def test_bad_semiadditive_value_fails(self):
        win, problems = parse_window(self._win(semiadditive="sum"), "m")
        assert win is None and problems

    def test_missing_order_fails(self):
        w = [{"range": "current", "semiadditive": "last"}]
        win, problems = parse_window(w, "m")
        assert win is None
        assert any("order" in p for p in problems)

    def test_bad_range_fails_with_measure_name(self):
        win, problems = parse_window(self._win(range="sideways 3 day"), "m1")
        assert win is None
        assert any("m1" in p for p in problems)

    def test_bad_offset_fails(self):
        win, problems = parse_window(self._win(offset="next month"), "m")
        assert win is None and problems

    def test_multi_entry_window_fails(self):
        win, problems = parse_window(self._win() + self._win(), "m")
        assert win is None
        assert any("single-entry" in p for p in problems)

    def test_non_list_window_fails(self):
        win, problems = parse_window({"order": "d"}, "m")
        assert win is None and problems

    def test_unknown_window_key_fails(self):
        win, problems = parse_window(self._win(frame="rows"), "m")
        assert win is None
        assert any("frame" in p for p in problems)


class TestExtractCrossRefs:
    def test_measure_and_any_value(self):
        expr = "MEASURE(quantity) / ANY_VALUE(category_quantity)"
        refs, lod = extract_cross_refs(expr)
        assert refs == ["quantity"]
        assert lod == ["category_quantity"]

    def test_multiple_measure_refs(self):
        expr = ("(MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) "
                "/ MEASURE(prior_month_revenue) * 100")
        refs, lod = extract_cross_refs(expr)
        assert refs == ["monthly_revenue", "prior_month_revenue", "prior_month_revenue"]
        assert lod == []

    def test_backtick_ref_unquoted(self):
        refs, _ = extract_cross_refs("MEASURE(`total sales`)")
        assert refs == ["total sales"]

    def test_no_refs(self):
        assert extract_cross_refs("SUM(x)") == ([], [])

    def test_case_insensitive(self):
        refs, lod = extract_cross_refs("measure(a) + any_value(b)")
        assert refs == ["a"] and lod == ["b"]


class TestClassifyDimension:
    def test_bare_column_is_direct(self):
        assert classify_dimension_expr("product_category")["kind"] == "direct"

    def test_dot_path_is_direct(self):
        assert classify_dimension_expr("orders.customers.COMPANY_NAME")["kind"] == "direct"

    def test_backtick_identifier_is_direct(self):
        assert classify_dimension_expr("`Order Date`")["kind"] == "direct"

    def test_function_is_computed(self):
        assert classify_dimension_expr(
            "date_trunc('day', transaction_date)")["kind"] == "computed"

    def test_case_when_is_computed(self):
        assert classify_dimension_expr(
            "CASE WHEN tenure < 12 THEN '0-1' ELSE '1+' END")["kind"] == "computed"

    def test_concat_is_computed(self):
        assert classify_dimension_expr(
            "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)"
        )["kind"] == "computed"

    def test_lod_window(self):
        cls = classify_dimension_expr(
            "SUM(source.LINE_TOTAL) OVER (PARTITION BY products.category.CATEGORY_NAME)")
        assert cls["kind"] == "lod_window"
        assert cls["inner_agg"] == "SUM"
        assert cls["inner_expr"] == "source.LINE_TOTAL"
        assert cls["partition_by"] == ["products.category.CATEGORY_NAME"]

    def test_lod_multi_partition_dims(self):
        cls = classify_dimension_expr("SUM(x) OVER (PARTITION BY a, b)")
        assert cls["partition_by"] == ["a", "b"]

    def test_lod_partition_with_function_call(self):
        cls = classify_dimension_expr(
            "SUM(x) OVER (PARTITION BY date_trunc('month', d), region)")
        assert cls["partition_by"] == ["date_trunc('month', d)", "region"]

    def test_over_without_partition_is_unsupported(self):
        cls = classify_dimension_expr("ROW_NUMBER() OVER (ORDER BY d)")
        assert cls["kind"] == "unsupported"

    def test_subquery_is_unsupported(self):
        cls = classify_dimension_expr("(SELECT MAX(d) FROM t)")
        assert cls["kind"] == "unsupported"
        assert "subquery" in cls["reason"]

    def test_comment_stripped_before_classifying(self):
        assert classify_dimension_expr("region -- the sales region")["kind"] == "direct"


class TestClassifyMeasure:
    def test_simple_sum(self):
        cls = classify_measure_expr("SUM(sales)")
        assert cls["expr_kind"] == "simple"
        assert cls["agg_function"] == "SUM"
        assert cls["physical_ref"] == "sales"
        assert cls["distinct"] is False

    def test_simple_dot_path(self):
        cls = classify_measure_expr("SUM(source.LINE_TOTAL)")
        assert cls["expr_kind"] == "simple"
        assert cls["physical_ref"] == "source.LINE_TOTAL"

    def test_avg_case_normalized(self):
        assert classify_measure_expr("avg(tenure)")["agg_function"] == "AVG"

    def test_count_distinct(self):
        cls = classify_measure_expr("COUNT(DISTINCT customer_id)")
        assert cls["expr_kind"] == "count_distinct"
        assert cls["physical_ref"] == "customer_id"

    def test_count_star(self):
        assert classify_measure_expr("COUNT(*)")["expr_kind"] == "count_star"

    def test_conditional_filter_where(self):
        cls = classify_measure_expr("SUM(x) FILTER (WHERE region = 'EMEA')")
        assert cls["expr_kind"] == "conditional"

    def test_cross_measure(self):
        cls = classify_measure_expr("MEASURE(quantity) / ANY_VALUE(category_quantity)")
        assert cls["expr_kind"] == "complex_cross_measure"
        assert cls["cross_refs"] == ["quantity"]
        assert cls["lod_refs"] == ["category_quantity"]

    def test_arithmetic_in_agg_is_complex(self):
        cls = classify_measure_expr("SUM(product_price * quantity * (1 - discount_percent))")
        assert cls["expr_kind"] == "complex"

    def test_ratio_of_aggs_is_complex(self):
        cls = classify_measure_expr("SUM(x) / COUNT(DISTINCT y)")
        assert cls["expr_kind"] == "complex"

    def test_subquery_is_unsupported(self):
        cls = classify_measure_expr(
            "COUNT(DISTINCT x) / (SELECT COUNT(DISTINCT x) FROM t)")
        assert cls["expr_kind"] == "unsupported"
        assert "subquery" in cls["reason"]

    def test_conditional_still_records_cross_refs(self):
        cls = classify_measure_expr("MEASURE(a) FILTER (WHERE b = 1)")
        assert cls["expr_kind"] == "conditional"
        assert cls["cross_refs"] == ["a"]

    def test_sum_distinct_keeps_simple_with_flag(self):
        cls = classify_measure_expr("SUM(DISTINCT amount)")
        assert cls["expr_kind"] == "simple"
        assert cls["distinct"] is True
