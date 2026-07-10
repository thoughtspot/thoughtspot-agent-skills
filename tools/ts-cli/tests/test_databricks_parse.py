# tools/ts-cli/tests/test_databricks_parse.py
"""Unit tests for ts_cli/databricks/mv_parse.py (BL-063 PR2 — ts databricks parse-mv).

One class per transform, mirroring test_tableau_translate.py. Pure functions
only until the CLI-command class at the bottom — no live connection anywhere.
"""
from __future__ import annotations

import yaml

from ts_cli.databricks.mv_parse import (
    classify_dimension_expr,
    classify_measure_expr,
    classify_source,
    extract_cross_refs,
    parse_joins,
    parse_metric_view,
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


class TestSplitDotPath:
    def test_plain_path(self):
        from ts_cli.databricks.mv_expr import split_dot_path
        assert split_dot_path("orders.customers.COL") == ["orders", "customers", "COL"]

    def test_backticked_segment(self):
        from ts_cli.databricks.mv_expr import split_dot_path
        assert split_dot_path("`my table`.COL") == ["my table", "COL"]

    def test_reexported_from_mv_parse(self):
        from ts_cli.databricks.mv_parse import split_dot_path  # noqa: F401


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

    def test_non_string_window_key_no_raise(self):
        # YAML 1.1 resolves an unquoted `no:` key to boolean False.
        w = [{"order": "d", "range": "current", "semiadditive": "last", False: "z"}]
        win, problems = parse_window(w, "m")
        assert win is None
        assert any("unknown window key" in p for p in problems)


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

    def test_partition_with_order_by_is_unsupported(self):
        cls = classify_dimension_expr("SUM(x) OVER (PARTITION BY a ORDER BY d)")
        assert cls["kind"] == "unsupported"

    def test_partition_with_frame_clause_is_unsupported(self):
        cls = classify_dimension_expr(
            "SUM(x) OVER (PARTITION BY a ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)")
        assert cls["kind"] == "unsupported"

    def test_ranking_function_with_partition_is_unsupported(self):
        cls = classify_dimension_expr("ROW_NUMBER() OVER (PARTITION BY a)")
        assert cls["kind"] == "unsupported"

    def test_multi_window_expression_is_unsupported(self):
        cls = classify_dimension_expr(
            "SUM(a) OVER (PARTITION BY b) + SUM(c) OVER (PARTITION BY d)")
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

    def test_physical_ref_backticks_normalized(self):
        out = classify_measure_expr("SUM(`source`.`LINE_TOTAL`)")
        assert out["expr_kind"] == "simple"
        assert out["physical_ref"] == "source.LINE_TOTAL"

    def test_backticked_segment_with_dot_unsupported(self):
        out = classify_measure_expr("SUM(`weird.col`)")
        assert out["expr_kind"] == "unsupported"
        assert "dot inside a backtick-quoted identifier" in out["reason"]


class TestQuoteAwareScanning:
    def test_line_marker_inside_literal_preserved(self):
        assert strip_sql_comments("col = 'a -- b'") == "col = 'a -- b'"

    def test_block_marker_inside_literal_preserved(self):
        assert strip_sql_comments("col = '/* not a comment */'") == "col = '/* not a comment */'"

    def test_line_marker_inside_block_comment(self):
        # old two-pass order stripped the -- first, corrupting the block
        assert strip_sql_comments("SUM(x) /* a -- b */ + 1") == "SUM(x)   + 1"

    def test_escaped_quote_in_literal(self):
        assert strip_sql_comments("col = 'it''s -- fine'") == "col = 'it''s -- fine'"

    def test_filter_keyword_inside_literal_not_conditional(self):
        out = classify_measure_expr("SUM(CASE WHEN note = 'FILTER (WHERE' THEN 1 ELSE 0 END)")
        assert out["expr_kind"] == "complex"

    def test_subquery_keyword_inside_literal_not_unsupported(self):
        out = classify_measure_expr("COUNT(x) FILTER (WHERE note != '(SELECT hidden')")
        assert out["expr_kind"] == "conditional"

    def test_over_inside_literal_is_computed_dimension(self):
        out = classify_dimension_expr("CONCAT(region, ' OVER (', zone)")
        assert out["kind"] == "computed"

    def test_split_top_level_quote_aware(self):
        from ts_cli.databricks.mv_expr import _split_top_level
        assert _split_top_level("a, 'x, y', b") == ["a", "'x, y'", "b"]


class TestParseJoins:
    def test_on_join_with_rely(self):
        joins = [{"name": "orders", "source": "c.s.dm_order",
                  "on": "source.ORDER_ID = orders.ORDER_ID",
                  "rely": {"at_most_one_match": True}}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert unsupported == []
        j = out[0]
        assert j["alias"] == "orders"
        assert j["source"]["kind"] == "table_fqn"
        assert j["on"] == "source.ORDER_ID = orders.ORDER_ID"
        assert j["using"] is None
        assert j["parent"] == "source"
        assert j["cardinality"] == "many_to_one"
        assert j["cardinality_source"] == "rely"
        assert j["joins"] == []

    def test_using_synthesizes_on_clause(self):
        joins = [{"name": "orders", "source": "c.s.dm_order",
                  "using": ["ORDER_ID", "REGION"]}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert out[0]["using"] == ["ORDER_ID", "REGION"]
        assert out[0]["on"] == ("source.ORDER_ID = orders.ORDER_ID"
                                " AND source.REGION = orders.REGION")

    def test_default_cardinality_many_to_one(self):
        joins = [{"name": "d", "source": "c.s.t", "on": "source.a = d.a"}]
        out = parse_joins(joins, unsupported=[])
        assert out[0]["cardinality"] == "many_to_one"
        assert out[0]["cardinality_source"] == "default"

    def test_cardinality_key_beats_rely(self):
        joins = [{"name": "d", "source": "c.s.t", "on": "source.a = d.a",
                  "cardinality": "one_to_many",
                  "rely": {"at_most_one_match": True}}]
        out = parse_joins(joins, unsupported=[])
        assert out[0]["cardinality"] == "one_to_many"
        assert out[0]["cardinality_source"] == "cardinality"

    def test_nested_joins_parent_tracks_alias(self):
        joins = [{"name": "orders", "source": "c.s.o", "on": "source.oid = orders.oid",
                  "joins": [{"name": "customers", "source": "c.s.cu",
                             "on": "orders.cid = customers.cid"}]}]
        out = parse_joins(joins, unsupported=[])
        child = out[0]["joins"][0]
        assert child["alias"] == "customers"
        assert child["parent"] == "orders"

    def test_both_on_and_using_is_unsupported(self):
        joins = [{"name": "d", "source": "c.s.t", "on": "source.a = d.a",
                  "using": ["a"]}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert out == []
        assert unsupported and "exactly one" in unsupported[0]["detail"]

    def test_neither_on_nor_using_is_unsupported(self):
        joins = [{"name": "d", "source": "c.s.t"}]
        unsupported = []
        parse_joins(joins, unsupported=unsupported)
        assert unsupported

    def test_bad_cardinality_value_is_unsupported(self):
        joins = [{"name": "d", "source": "c.s.t", "on": "source.a = d.a",
                  "cardinality": "one_to_one"}]
        unsupported = []
        parse_joins(joins, unsupported=unsupported)
        assert unsupported

    def test_rely_without_at_most_one_match_true_is_unsupported(self):
        joins = [{"name": "d", "source": "c.s.t", "on": "source.a = d.a",
                  "rely": {"at_most_one_match": False}}]
        unsupported = []
        parse_joins(joins, unsupported=unsupported)
        assert unsupported

    def test_missing_name_is_unsupported(self):
        joins = [{"source": "c.s.t", "on": "source.a = d.a"}]
        unsupported = []
        parse_joins(joins, unsupported=unsupported)
        assert unsupported

    def test_sql_query_join_source_allowed(self):
        joins = [{"name": "d", "source": "(SELECT * FROM t)", "on": "source.a = d.a"}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert unsupported == []
        assert out[0]["source"]["kind"] == "sql_query"

    def test_none_join_list_returns_empty(self):
        assert parse_joins(None, unsupported=[]) == []

    def test_unquoted_on_key_from_real_yaml(self):
        # YAML 1.1: unquoted `on:` parses as boolean True — parse_joins must accept it.
        doc = yaml.safe_load(
            "joins:\n"
            "  - name: orders\n"
            "    source: c.s.o\n"
            "    on: source.a = orders.a\n")
        assert True in doc["joins"][0]  # precondition: the trap is real
        unsupported = []
        out = parse_joins(doc["joins"], unsupported=unsupported)
        assert unsupported == []
        assert out[0]["on"] == "source.a = orders.a"

    def test_using_null_is_problem_not_crash(self):
        joins = [{"name": "d", "source": "c.s.t", "using": None}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert out == []
        assert unsupported and "'using' must be a list" in unsupported[0]["detail"]

    def test_using_scalar_is_problem_not_chars(self):
        joins = [{"name": "d", "source": "c.s.t", "using": "ORDER_ID"}]
        unsupported = []
        parse_joins(joins, unsupported=unsupported)
        assert unsupported and "'using' must be a list" in unsupported[0]["detail"]

    def test_on_null_is_problem_not_literal_none(self):
        joins = [{"name": "d", "source": "c.s.t", "on": None}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert out == []
        assert unsupported and "boolean expression" in unsupported[0]["detail"]

    def test_on_empty_string_is_problem(self):
        joins = [{"name": "d", "source": "c.s.t", "on": ""}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert out == []
        assert unsupported and "boolean expression" in unsupported[0]["detail"]

    def test_bad_nested_child_dropped_parent_survives(self):
        joins = [{"name": "orders", "source": "c.s.o", "on": "source.a = orders.a",
                  "joins": [{"name": "bad", "source": "c.s.b"}]}]
        unsupported = []
        out = parse_joins(joins, unsupported=unsupported)
        assert len(out) == 1 and out[0]["alias"] == "orders"
        assert out[0]["joins"] == []
        assert unsupported and unsupported[0]["name"] == "bad"


MV_V01_BASIC_SALES = """\
version: 0.1

source: demo_qsr.prayansh.ecommerce_transactions
filter: NOT is_return AND transaction_status = 'Completed'

dimensions:
  - name: Transaction Date
    expr: date_trunc('day', transaction_date)

  - name: Product Category
    expr: product_category

  - name: Region
    expr: region

  - name: Customer Segment
    expr: customer_segment

measures:
  - name: Total Sales
    expr: SUM(product_price * quantity * (1 - discount_percent))

  - name: Total Transactions
    expr: COUNT(DISTINCT transaction_id)

  - name: Average Order Value
    expr: SUM(product_price * quantity * (1 - discount_percent)) / COUNT(DISTINCT transaction_id)

  - name: Total Discount Amount
    expr: SUM(product_price * quantity * discount_percent)

  - name: Unique Customers
    expr: COUNT(DISTINCT customer_id)
"""

MV_DM_SALES = """\
version: 1.1
source: agent_skills.dunder_mifflin.dm_order_detail

joins:
  - name: orders
    source: agent_skills.dunder_mifflin.dm_order
    "on": source.DM_ORDER_DETAIL_ORDER_ID = orders.ORDER_ID
    joins:
      - name: customers
        source: agent_skills.dunder_mifflin.dm_customer
        "on": orders.DM_ORDER_CUSTOMER_ID = customers.CUSTOMER_ID
        rely: { at_most_one_match: true }
      - name: employees
        source: agent_skills.dunder_mifflin.dm_employee
        "on": orders.DM_ORDER_EMPLOYEE_ID = employees.EMPLOYEE_ID
        rely: { at_most_one_match: true }
      - name: dates
        source: agent_skills.dunder_mifflin.dm_date_dim
        "on": orders.DM_ORDER_ORDER_DATE = dates.DATE_VALUE
        rely: { at_most_one_match: true }
    rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.DM_ORDER_DETAIL_PRODUCT_ID = products.PRODUCT_ID
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.DM_PRODUCT_CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }
    rely: { at_most_one_match: true }

comment: >-
  Dunder Mifflin Sales metrics built on normalized star schema — revenue,
  quantity, pricing, and period-over-period analysis.

dimensions:
  - name: order_date
    expr: orders.DM_ORDER_ORDER_DATE
    display_name: Order Date
    comment: Date the order was placed.
    synonyms: ['order placed', 'purchase date']
  - name: product_category
    expr: products.category.CATEGORY_NAME
    display_name: Product Category
    synonyms: ['category', 'product line']
  - name: customer_name
    expr: orders.customers.COMPANY_NAME
    display_name: Customer Name
    synonyms: ['customer', 'client', 'buyer']
  - name: employee_name
    expr: "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)"
    display_name: Employee
    synonyms: ['sales rep', 'rep', 'salesperson']
  - name: category_total_revenue
    expr: SUM(source.LINE_TOTAL) OVER (PARTITION BY products.category.CATEGORY_NAME)
    display_name: Category Total Revenue
    comment: "Fixed LOD: total revenue at category grain."

measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: Revenue
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }
    synonyms: ['sales', 'total sales', 'amount']
  - name: order_count
    expr: COUNT(DISTINCT orders.ORDER_ID)
    display_name: Order Count
    synonyms: ['number of orders']
  - name: category_contribution_pct
    expr: MEASURE(revenue) / ANY_VALUE(category_total_revenue) * 100
    display_name: Category Contribution %
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }
  - name: monthly_revenue
    expr: SUM(source.LINE_TOTAL)
    window: [{ order: order_month, semiadditive: last, range: current }]
  - name: prior_month_revenue
    expr: SUM(source.LINE_TOTAL)
    window: [{ order: order_month, semiadditive: last, range: current, offset: -1 month }]
  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
    display_name: MoM Growth %
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }
"""

MV_DM_INVENTORY = """\
version: 1.1
comment: >-
  Dunder Mifflin Inventory analysis — semi-additive stock levels.
source: agent_skills.dunder_mifflin.dm_inventory_flat

dimensions:
  - name: balance_date
    expr: DM_INVENTORY_BALANCE_DATE
    display_name: 'Balance Date'
    comment: 'Date the inventory balance was snapshotted.'

  - name: product_name
    expr: PRODUCT_NAME
    display_name: 'Product Name'
    synonyms: ['product', 'item']

measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Semi-additive snapshot measure.'
    synonyms: ['stock', 'stock on hand', 'current inventory']
    window:
      - order: balance_date
        range: current
        semiadditive: last
"""

# v1.1 single-source composite: the schema doc's window-with-offset measures
# example + the materialization example, on a minimal fields: header. Covers
# all five range values, both anchors, offsets, fields:, materialization.
MV_V11_WINDOWS_MAT = """\
version: 1.1
comment: Single-source windows + materialization composite.
source: catalog.schema.sales_fact
filter: NOT is_return AND transaction_status = 'Completed'

fields:
  - name: order_date
    expr: order_date
  - name: order_month
    expr: date_trunc('month', order_date)

measures:
  - name: monthly_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
  - name: prior_month_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 month
  - name: prior_year_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 year
  - name: cumulative_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_date
        semiadditive: last
        range: cumulative
  - name: trailing_7d_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_date
        semiadditive: last
        range: trailing 7 day
  - name: leading_7d_incl_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_date
        semiadditive: last
        range: leading 7 day inclusive
  - name: all_time_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_date
        semiadditive: last
        range: all
  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100

materialization:
  schedule: every 6 hours
  mode: relaxed
  materialized_views:
    - name: baseline
      type: unaggregated
    - name: daily_status_metrics
      type: aggregated
      dimensions:
        - order_date
      measures:
        - monthly_revenue
"""


def _by_name(items):
    return {i["name"]: i for i in items}


class TestParseMetricViewGolden:
    def test_v01_basic_sales(self):
        r = parse_metric_view(MV_V01_BASIC_SALES)
        assert r["unsupported"] == []
        assert r["version"] == "0.1"
        assert r["source"]["kind"] == "table_fqn"
        assert r["source"]["parts"] == ["demo_qsr", "prayansh", "ecommerce_transactions"]
        assert r["filter"] == "NOT is_return AND transaction_status = 'Completed'"
        dims = _by_name(r["dimensions"])
        assert dims["Transaction Date"]["kind"] == "computed"
        assert dims["Region"]["kind"] == "direct"
        meas = _by_name(r["measures"])
        assert meas["Total Sales"]["kind"] == "complex"
        assert meas["Total Transactions"]["kind"] == "count_distinct"
        assert meas["Average Order Value"]["kind"] == "complex"
        assert meas["Unique Customers"]["physical_ref"] == "customer_id"
        assert r["joins"] == [] and r["materialization"] is None

    def test_dm_sales_star_schema(self):
        r = parse_metric_view(MV_DM_SALES)
        assert r["unsupported"] == []
        assert r["version"] == "1.1"
        assert r["comment"].startswith("Dunder Mifflin Sales metrics")
        top = {j["alias"]: j for j in r["joins"]}
        assert set(top) == {"orders", "products"}
        assert {c["alias"] for c in top["orders"]["joins"]} == {
            "customers", "employees", "dates"}
        assert top["products"]["joins"][0]["alias"] == "category"
        assert top["products"]["joins"][0]["parent"] == "products"
        assert all(j["cardinality_source"] == "rely"
                   for j in top.values())
        dims = _by_name(r["dimensions"])
        assert dims["order_date"]["kind"] == "direct"
        assert dims["order_date"]["synonyms"] == ["order placed", "purchase date"]
        assert dims["employee_name"]["kind"] == "computed"
        lod = dims["category_total_revenue"]
        assert lod["kind"] == "lod_window"
        assert lod["partition_by"] == ["products.category.CATEGORY_NAME"]
        meas = _by_name(r["measures"])
        assert meas["revenue"]["kind"] == "simple"
        assert meas["revenue"]["format"]["type"] == "currency"
        assert meas["order_count"]["kind"] == "count_distinct"
        assert meas["category_contribution_pct"]["kind"] == "complex_cross_measure"
        assert meas["category_contribution_pct"]["lod_refs"] == ["category_total_revenue"]
        assert meas["monthly_revenue"]["kind"] == "windowed"
        assert meas["monthly_revenue"]["expr_kind"] == "simple"
        # order_month is NOT a declared dimension — order: must not be
        # validated against the dimension list (live DM Sales MV proves it).
        assert meas["monthly_revenue"]["window"]["order"] == "order_month"
        assert meas["prior_month_revenue"]["window"]["offset"] == {"n": -1, "unit": "month"}
        assert meas["mom_growth_pct"]["cross_refs"] == [
            "monthly_revenue", "prior_month_revenue", "prior_month_revenue"]
        assert r["warnings"] == []  # no trailing/leading -> no density warning

    def test_dm_inventory_semiadditive(self):
        r = parse_metric_view(MV_DM_INVENTORY)
        assert r["unsupported"] == []
        meas = _by_name(r["measures"])
        w = meas["inventory_balance"]["window"]
        assert w["range"]["type"] == "current"
        assert w["semiadditive"] == "last"
        assert w["density_check_required"] is False

    def test_v11_windows_and_materialization(self):
        r = parse_metric_view(MV_V11_WINDOWS_MAT)
        assert r["unsupported"] == []
        # fields: is the dimensions key
        assert {d["name"] for d in r["dimensions"]} == {"order_date", "order_month"}
        meas = _by_name(r["measures"])
        ranges = {n: m["window"]["range"] for n, m in meas.items() if m["window"]}
        assert ranges["monthly_revenue"]["type"] == "current"
        assert ranges["cumulative_revenue"]["type"] == "cumulative"
        assert ranges["trailing_7d_revenue"] == {"type": "trailing", "n": 7,
                                                 "unit": "day", "anchor": "exclusive"}
        assert ranges["leading_7d_incl_revenue"]["anchor"] == "inclusive"
        assert ranges["all_time_revenue"]["type"] == "all"
        assert meas["prior_year_revenue"]["window"]["offset"] == {"n": -1, "unit": "year"}
        # BL-098: exactly the trailing + leading measures carry the flag
        flagged = {n for n, m in meas.items()
                   if m["window"] and m["window"]["density_check_required"]}
        assert flagged == {"trailing_7d_revenue", "leading_7d_incl_revenue"}
        assert len(r["warnings"]) == 2
        assert all("BL-098" in w or "density" in w.lower() for w in r["warnings"])
        # materialization passes through verbatim
        assert r["materialization"]["mode"] == "relaxed"
        assert r["materialization"]["materialized_views"][0]["name"] == "baseline"


class TestParseMetricViewFailLoud:
    def test_unknown_version(self):
        r = parse_metric_view("version: 2.0\nsource: c.s.t\n")
        assert r["unsupported"] == [
            {"kind": "unknown_version", "name": None, "detail": "2.0"}]

    def test_version_defaults_to_11_when_missing(self):
        r = parse_metric_view("source: c.s.t\nmeasures:\n  - name: m\n    expr: SUM(x)\n")
        assert r["version"] == "1.1"
        assert r["unsupported"] == []

    def test_yaml_float_version_normalized(self):
        r = parse_metric_view("version: 0.1\nsource: c.s.t\n")
        assert r["version"] == "0.1"

    def test_unparseable_yaml(self):
        r = parse_metric_view("version: [unclosed\n")
        assert r["unsupported"][0]["kind"] == "yaml_error"

    def test_non_mapping_top_level(self):
        r = parse_metric_view("- just\n- a list\n")
        assert r["unsupported"][0]["kind"] == "yaml_error"

    def test_missing_source(self):
        r = parse_metric_view("version: 1.1\nmeasures: []\n")
        assert any(u["kind"] == "missing_source" for u in r["unsupported"])

    def test_unknown_top_level_key(self):
        r = parse_metric_view("source: c.s.t\nfrobnicate: 1\n")
        assert any(u["kind"] == "unknown_key" and u["detail"] == "frobnicate"
                   for u in r["unsupported"])

    def test_both_fields_and_dimensions(self):
        r = parse_metric_view(
            "source: c.s.t\nfields:\n  - {name: a, expr: a}\n"
            "dimensions:\n  - {name: b, expr: b}\n")
        assert any(u["kind"] == "ambiguous_dimensions" for u in r["unsupported"])

    def test_subquery_dimension_goes_to_unsupported(self):
        r = parse_metric_view(
            "source: c.s.t\ndimensions:\n"
            "  - {name: d, expr: (SELECT MAX(x) FROM t)}\n")
        assert r["dimensions"] == []
        assert any(u["kind"] == "dimension" and u["name"] == "d"
                   for u in r["unsupported"])

    def test_subquery_measure_goes_to_unsupported(self):
        r = parse_metric_view(
            "source: c.s.t\nmeasures:\n"
            "  - {name: m, expr: COUNT(DISTINCT x) / (SELECT COUNT(1) FROM t)}\n")
        assert r["measures"] == []
        assert any(u["kind"] == "measure" and u["name"] == "m"
                   for u in r["unsupported"])

    def test_window_missing_semiadditive_goes_to_unsupported(self):
        r = parse_metric_view(
            "source: c.s.t\nmeasures:\n"
            "  - name: m\n    expr: SUM(x)\n"
            "    window:\n      - {order: d, range: current}\n")
        assert r["measures"] == []
        assert any(u["kind"] == "measure" and "semiadditive" in u["detail"]
                   for u in r["unsupported"])

    def test_entry_missing_name_or_expr(self):
        r = parse_metric_view(
            "source: c.s.t\ndimensions:\n  - {name: only_name}\n"
            "measures:\n  - {expr: SUM(x)}\n")
        assert len([u for u in r["unsupported"]
                    if u["kind"] in ("dimension", "measure")]) == 2

    def test_duplicate_identifier_across_dims_and_measures_is_unsupported(self):
        """BL-099 #3 — Databricks rejects dup names at CREATE time, but a hand-edited
        YAML must not silently last-write-wins through the mv_name-keyed lookups."""
        yaml_text = """
version: 1.1
source: cat.sch.sales
dimensions:
  - name: amount
    expr: amount_col
measures:
  - name: amount
    expr: SUM(amount_col)
"""
        r = parse_metric_view(yaml_text)
        kinds = [u["kind"] for u in r["unsupported"]]
        assert "duplicate_name" in kinds
        entry = next(u for u in r["unsupported"] if u["kind"] == "duplicate_name")
        assert "amount" in entry["detail"]

    def test_duplicate_identifier_within_dimensions_is_unsupported(self):
        r = parse_metric_view(
            "source: c.s.t\ndimensions:\n"
            "  - {name: region, expr: region_col}\n"
            "  - {name: region, expr: other_region_col}\n")
        entry = next(u for u in r["unsupported"] if u["kind"] == "duplicate_name")
        assert "region" in entry["detail"]

    def test_duplicate_identifier_within_measures_is_unsupported(self):
        r = parse_metric_view(
            "source: c.s.t\nmeasures:\n"
            "  - {name: revenue, expr: SUM(a)}\n"
            "  - {name: revenue, expr: SUM(b)}\n")
        entry = next(u for u in r["unsupported"] if u["kind"] == "duplicate_name")
        assert "revenue" in entry["detail"]

    def test_non_dict_materialization(self):
        r = parse_metric_view("source: c.s.t\nmaterialization: fast\n")
        assert any(u["kind"] == "materialization" for u in r["unsupported"])

    def test_empty_mv_warns_but_no_unsupported(self):
        r = parse_metric_view("source: c.s.t\n")
        assert r["unsupported"] == []
        assert any("no dimensions" in w for w in r["warnings"])

    def test_sql_query_source_parsed_not_unsupported(self):
        r = parse_metric_view(
            "source: SELECT a, b FROM t\nmeasures:\n  - {name: m, expr: SUM(a)}\n")
        assert r["unsupported"] == []
        assert r["source"]["kind"] == "sql_query"


class TestParseMetricViewScalarGuards:
    def test_scalar_dimensions_no_raise(self):
        r = parse_metric_view("source: c.s.t\ndimensions: 5\n")
        assert any(u["kind"] == "dimensions" for u in r["unsupported"])
        assert r["dimensions"] == []

    def test_string_measures_no_per_char_garbage(self):
        r = parse_metric_view("source: c.s.t\nmeasures: fast\n")
        assert [u["kind"] for u in r["unsupported"]].count("measures") == 1
        assert r["measures"] == []

    def test_scalar_joins_no_raise(self):
        r = parse_metric_view("source: c.s.t\njoins: 5\n")
        assert any(u["kind"] == "joins" for u in r["unsupported"])
        assert r["joins"] == []

    def test_scalar_synonyms_excludes_entry(self):
        r = parse_metric_view(
            "source: c.s.t\ndimensions:\n  - {name: d, expr: col, synonyms: fast}\n")
        assert r["dimensions"] == []
        assert any(u["kind"] == "dimension" and "synonyms" in u["detail"]
                   for u in r["unsupported"])


class TestContractGating:
    def test_source_mixed_backtick_bare_segment_validated(self):
        # bare middle segment 'bad name' must be rejected even though
        # another segment is backticked (old code skipped ALL validation
        # when any backtick was present)
        assert classify_source("`cat`.bad name.tbl") is None

    def test_source_sql_detected_with_newline(self):
        out = classify_source("select\n1 as x from t")
        assert out["kind"] == "sql_query"

    def test_source_selector_prefix_word_bound(self):
        # 'selection.schema.tbl' must NOT classify as SQL
        out = classify_source("selection.schema.tbl")
        assert out["kind"] == "table_fqn"

    def test_lod_ordered_aggregate_rejected(self):
        out = classify_dimension_expr(
            "ARRAY_AGG(x ORDER BY y) OVER (PARTITION BY cat)")
        assert out["kind"] == "unsupported"

    def test_range_unknown_unit_rejected(self):
        assert parse_range("trailing 2 fortnight") is None

    def test_range_zero_n_rejected(self):
        assert parse_range("trailing 0 day") is None

    def test_offset_zero_rejected(self):
        assert parse_offset("-0 month") is None

    def test_offset_unknown_unit_rejected(self):
        assert parse_offset("-1 sprint") is None


import json

from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr separated by default)
    runner = CliRunner()


def _stderr(result):
    try:
        return result.stderr
    except ValueError:
        return ""


class TestParseMvCli:
    def test_parses_file_to_json(self, tmp_path):
        yml = tmp_path / "mv.yaml"
        yml.write_text(MV_DM_INVENTORY)
        out = tmp_path / "parsed.json"
        result = runner.invoke(app, ["databricks", "parse-mv", str(yml),
                                     "--output", str(out)])
        assert result.exit_code == 0, result.stdout + _stderr(result)
        data = json.loads(out.read_text())
        assert data["version"] == "1.1"
        assert data["unsupported"] == []
        assert {m["name"] for m in data["measures"]} == {"inventory_balance"}

    def test_reads_stdin_dash(self, tmp_path):
        out = tmp_path / "parsed.json"
        result = runner.invoke(app, ["databricks", "parse-mv", "-",
                                     "--output", str(out)],
                               input=MV_V01_BASIC_SALES)
        assert result.exit_code == 0, result.stdout + _stderr(result)
        assert json.loads(out.read_text())["version"] == "0.1"

    def test_creates_missing_output_parent_dir(self, tmp_path):
        yml = tmp_path / "mv.yaml"
        yml.write_text(MV_DM_INVENTORY)
        out = tmp_path / "sub" / "deep" / "parsed.json"
        result = runner.invoke(app, ["databricks", "parse-mv", str(yml),
                                     "--output", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_missing_input_file_exits_nonzero(self, tmp_path):
        out = tmp_path / "parsed.json"
        result = runner.invoke(app, ["databricks", "parse-mv",
                                     str(tmp_path / "nope.yaml"),
                                     "--output", str(out)])
        assert result.exit_code == 1
        assert not out.exists()

    def test_unsupported_exits_nonzero_but_writes_json(self, tmp_path):
        yml = tmp_path / "mv.yaml"
        yml.write_text("version: 2.0\nsource: c.s.t\n")
        out = tmp_path / "parsed.json"
        result = runner.invoke(app, ["databricks", "parse-mv", str(yml),
                                     "--output", str(out)])
        assert result.exit_code == 1
        data = json.loads(out.read_text())
        assert data["unsupported"][0]["kind"] == "unknown_version"
        assert "UNSUPPORTED" in _stderr(result)

    def test_density_warning_on_stderr_exit_zero(self, tmp_path):
        yml = tmp_path / "mv.yaml"
        yml.write_text(MV_V11_WINDOWS_MAT)
        out = tmp_path / "parsed.json"
        result = runner.invoke(app, ["databricks", "parse-mv", str(yml),
                                     "--output", str(out)])
        assert result.exit_code == 0, result.stdout + _stderr(result)
        err = _stderr(result)
        assert "WARNING" in err and "BL-098" in err
