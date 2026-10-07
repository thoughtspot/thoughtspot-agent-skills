# tools/ts-cli/tests/test_databricks_translate.py
"""Unit tests for ts_cli/databricks/mv_translate.py (BL-063 PR3).

One class per transform. The golden classes at the bottom pin the two
post-PR-1 corrected worked examples byte-for-byte."""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import UntranslatableError, translate_sql_expr
from ts_cli.databricks.mv_translate import (
    make_resolver,
    resolve_parts,
    translate_dimension,
    translate_filter,
    translate_measure,
    translate_metric_view,
    translate_window_measure,
)

TABLES = {"source": "TRANSACTIONS", "orders": "DM_ORDER",
          "orders.customers": "DM_CUSTOMER"}


def _dim(name, expr, kind, **kw):
    base = {"name": name, "expr": expr, "kind": kind, "display_name": None,
            "comment": None, "synonyms": [], "inner_agg": None,
            "inner_expr": None, "partition_by": []}
    base.update(kw)
    return base


def _measure(name, expr, expr_kind, **kw):
    base = {"name": name, "expr": expr, "kind": kw.pop("kind", expr_kind),
            "expr_kind": expr_kind, "agg_function": None, "physical_ref": None,
            "distinct": False, "cross_refs": [], "lod_refs": [],
            "display_name": None, "comment": None, "synonyms": [],
            "format": None, "window": None}
    base.update(kw)
    return base


class TestResolver:
    def test_bare_column_resolves_via_source(self):
        assert resolve_parts(TABLES, "unit_price") == ("TRANSACTIONS", "unit_price")

    def test_alias_path(self):
        assert resolve_parts(TABLES, "orders.ORDER_DATE") == ("DM_ORDER", "ORDER_DATE")

    def test_nested_alias_path(self):
        assert resolve_parts(TABLES, "orders.customers.NAME") == ("DM_CUSTOMER", "NAME")

    def test_backticked_column(self):
        assert resolve_parts(TABLES, "`unit price`") == ("TRANSACTIONS", "unit price")

    def test_unmapped_alias_raises_with_hint(self):
        with pytest.raises(UntranslatableError, match="products.*--tables"):
            resolve_parts(TABLES, "products.SKU")

    def test_bracketed_form(self):
        assert make_resolver(TABLES)("orders.ORDER_DATE") == "[DM_ORDER::ORDER_DATE]"


class TestTranslateDimension:
    def test_direct_is_column_output(self):
        out = translate_dimension(
            _dim("product_category", "product_category", "direct",
                 display_name="Product Category",
                 synonyms=["category", "product type"]), TABLES)
        assert out["output_kind"] == "column"
        assert (out["table"], out["column"]) == ("TRANSACTIONS", "product_category")
        assert out["column_type"] == "ATTRIBUTE"
        assert out["ts_expr"] is None
        assert out["synonyms"] == ["category", "product type"]

    def test_computed_is_formula(self):
        out = translate_dimension(
            _dim("transaction_month", "DATE_TRUNC('MONTH', transaction_date)",
                 "computed"), TABLES)
        assert out["output_kind"] == "formula"
        assert out["ts_expr"] == "start_of_month ( [TRANSACTIONS::transaction_date] )"
        assert out["column_type"] == "ATTRIBUTE"
        assert out["aggregation"] is None

    def test_lod_window_group_aggregate(self):
        out = translate_dimension(
            _dim("category_quantity", "SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)",
                 "lod_window", inner_agg="SUM", inner_expr="QUANTITY",
                 partition_by=["PRODUCT_CATEGORY"]), TABLES)
        assert out["ts_expr"] == ("group_aggregate ( sum ( [TRANSACTIONS::QUANTITY] ) , "
                                  "{ [TRANSACTIONS::PRODUCT_CATEGORY] } , query_filters ( ) )")
        assert out["column_type"] == "ATTRIBUTE"
        assert [a["kind"] for a in out["annotations"]] == ["lod_filter_asymmetry"]

    def test_lod_multi_partition_and_cross_table(self):
        out = translate_dimension(
            _dim("x", "AVG(amt) OVER (PARTITION BY cat, orders.REGION)",
                 "lod_window", inner_agg="AVG", inner_expr="amt",
                 partition_by=["cat", "orders.REGION"]), TABLES)
        assert out["ts_expr"] == ("group_aggregate ( average ( [TRANSACTIONS::amt] ) , "
                                  "{ [TRANSACTIONS::cat] , [DM_ORDER::REGION] } , query_filters ( ) )")

    def test_lod_median_agg(self):
        out = translate_dimension(
            _dim("x", "MEDIAN(amt) OVER (PARTITION BY cat)", "lod_window",
                 inner_agg="MEDIAN", inner_expr="amt",
                 partition_by=["cat"]), TABLES)
        assert out["ts_expr"] == ("group_aggregate ( median ( [TRANSACTIONS::amt] ) , "
                                  "{ [TRANSACTIONS::cat] } , query_filters ( ) )")

    def test_lod_unknown_agg_raises(self):
        with pytest.raises(UntranslatableError, match="PERCENTILE_CONT"):
            translate_dimension(
                _dim("x", "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY amt) OVER (PARTITION BY cat)",
                     "lod_window",
                     inner_agg="PERCENTILE_CONT", inner_expr="amt",
                     partition_by=["cat"]), TABLES)


class TestTranslateFilter:
    def test_filter_golden_ecommerce(self):
        out = translate_filter("status != 'cancelled'", TABLES)
        assert out == {"name": "MV Filter", "column_type": "ATTRIBUTE",
                       "ts_expr": "[TRANSACTIONS::status] != 'cancelled'",
                       "annotations": []}

    def test_filter_not_and_in(self):
        out = translate_filter(
            "NOT is_return AND transaction_status IN ('Completed', 'Shipped')", TABLES)
        assert out["ts_expr"] == (
            "[TRANSACTIONS::is_return] = false and "
            "( [TRANSACTIONS::transaction_status] = 'Completed' or "
            "[TRANSACTIONS::transaction_status] = 'Shipped' )")


class TestTranslateMeasure:
    def test_simple_sum_is_column(self):
        out = translate_measure(
            _measure("revenue", "SUM(LINE_TOTAL)", "simple",
                     agg_function="SUM", physical_ref="LINE_TOTAL"), TABLES)
        assert out["output_kind"] == "column"
        assert (out["table"], out["column"]) == ("TRANSACTIONS", "LINE_TOTAL")
        assert out["aggregation"] == "SUM"
        assert out["column_type"] == "MEASURE"

    def test_simple_avg_maps_average(self):
        out = translate_measure(
            _measure("t", "AVG(tenure)", "simple", agg_function="AVG",
                     physical_ref="tenure"), TABLES)
        assert out["aggregation"] == "AVERAGE"

    def test_simple_stddev_maps_std_deviation(self):
        out = translate_measure(
            _measure("s", "STDDEV(x)", "simple", agg_function="STDDEV",
                     physical_ref="x"), TABLES)
        assert out["aggregation"] == "STD_DEVIATION"

    def test_simple_median_uses_formula_path(self):
        out = translate_measure(
            _measure("m", "MEDIAN(x)", "simple", agg_function="MEDIAN",
                     physical_ref="x"), TABLES)
        assert out["output_kind"] == "formula"
        assert out["ts_expr"] == "median ( [TRANSACTIONS::x] )"

    def test_simple_unknown_agg_falls_back_to_formula_path(self):
        with pytest.raises(UntranslatableError, match="PERCENTILE_CONT"):
            translate_measure(
                _measure("m", "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY x)",
                         "simple", agg_function="PERCENTILE_CONT",
                         physical_ref="x"), TABLES)

    def test_simple_distinct_raises(self):
        with pytest.raises(UntranslatableError, match="DISTINCT"):
            translate_measure(
                _measure("m", "SUM(DISTINCT x)", "simple", agg_function="SUM",
                         physical_ref="x", distinct=True), TABLES)

    def test_count_distinct_formula(self):
        out = translate_measure(
            _measure("unique_customers", "COUNT(DISTINCT customer_id)",
                     "count_distinct", physical_ref="customer_id"), TABLES)
        assert out["output_kind"] == "formula"
        assert out["ts_expr"] == "unique count ( [TRANSACTIONS::customer_id] )"
        assert out["aggregation"] == "SUM"

    def test_count_star_formula(self):
        out = translate_measure(
            _measure("total_orders", "COUNT(*)", "count_star"), TABLES)
        assert out["ts_expr"] == "count ( 1 )"
        assert out["aggregation"] == "SUM"

    def test_conditional_sum_if_golden(self):
        # ts-from-databricks.md Measure 4
        out = translate_measure(
            _measure("high_value_revenue",
                     "SUM(unit_price * quantity) FILTER (WHERE unit_price > 100)",
                     "conditional"), TABLES)
        assert out["ts_expr"] == ("sum_if ( [TRANSACTIONS::unit_price] > 100 , "
                                  "[TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] )")

    def test_conditional_count_distinct(self):
        out = translate_measure(
            _measure("m", "COUNT(DISTINCT customer_id) FILTER (WHERE NOT is_return)",
                     "conditional"), TABLES)
        assert out["ts_expr"] == ("unique_count_if ( [TRANSACTIONS::is_return] = false , "
                                  "[TRANSACTIONS::customer_id] )")

    def test_conditional_unmapped_agg_fails_loud(self):
        # All eight doc-mapped aggregates have native *_if forms, so an
        # unmapped aggregate under FILTER (WHERE …) fails loud (no dead
        # fallback branch — see _translate_conditional comment):
        with pytest.raises(UntranslatableError, match="FILTER"):
            translate_measure(
                _measure("m", "MEDIAN(x) FILTER (WHERE y > 1)", "conditional"),
                TABLES)

    def test_conditional_nested_parens_inner(self):
        out = translate_measure(
            _measure("m", "SUM(COALESCE(a, b)) FILTER (WHERE c > 1)",
                     "conditional"), TABLES)
        assert out["ts_expr"] == (
            "sum_if ( [TRANSACTIONS::c] > 1 , "
            "if ( [TRANSACTIONS::a] != null ) then [TRANSACTIONS::a] else [TRANSACTIONS::b] )")

    def test_complex_ratio_golden(self):
        # ts-from-databricks.md Measure 3
        out = translate_measure(
            _measure("avg_order_value",
                     "SUM(unit_price * quantity) / COUNT(DISTINCT transaction_id)",
                     "complex"), TABLES)
        assert out["ts_expr"] == ("sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) "
                                  "/ unique count ( [TRANSACTIONS::transaction_id] )")

    def test_complex_case_cast_golden(self):
        # ts-from-databricks.md Measure 6
        out = translate_measure(
            _measure("return_rate",
                     "CAST(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*)",
                     "complex"), TABLES)
        assert out["ts_expr"] == ("sum ( if ( [TRANSACTIONS::status] = 'returned' ) then 1 else 0 ) "
                                  "/ count ( 1 )")

    def test_windowed_measure_guard_routes_away(self):
        # kind=="windowed" measures must go through translate_window_measure;
        # translate_measure raises rather than silently mistranslating.
        with pytest.raises(UntranslatableError, match="translate_window_measure"):
            translate_measure(
                _measure("m", "SUM(x)", "simple", agg_function="SUM",
                         physical_ref="x",
                         window={"order": "d", "range": {"type": "cumulative"}}),
                TABLES)

    def test_cross_measure_placeholders_prepared(self):
        out = translate_measure(
            _measure("ratio", "MEASURE(quantity) / ANY_VALUE(category_quantity)",
                     "complex_cross_measure",
                     cross_refs=["quantity"], lod_refs=["category_quantity"]),
            TABLES)
        assert out["ts_expr"] == "__MVREF_0__ / __MVREF_1__"
        assert out["inlined_refs"] == ["quantity", "category_quantity"]


class TestPrepareCrossMeasureSurfaces:
    def test_ref_text_inside_literal_not_substituted(self):
        from ts_cli.databricks.mv_translate import _prepare_cross_measure
        sql, refs = _prepare_cross_measure("MEASURE(a) + 'MEASURE(fake)'")
        assert refs == ["a"]
        assert sql == "__MVREF_0__ + 'MEASURE(fake)'"

    def test_ref_inside_comment_not_substituted(self):
        from ts_cli.databricks.mv_translate import _prepare_cross_measure
        sql, refs = _prepare_cross_measure("MEASURE(a) /* MEASURE(dead) */ + 1")
        assert refs == ["a"]
        assert "__MVREF_1__" not in sql

    def test_conditional_with_trailing_comment(self):
        out = translate_measure(
            _measure("m", "SUM(x) FILTER (WHERE y > 1) -- note",
                     "conditional"), TABLES)
        assert out["ts_expr"] == ("sum_if ( [TRANSACTIONS::y] > 1 , "
                                  "[TRANSACTIONS::x] )")


def _win_measure(name, expr, expr_kind, window, **kw):
    m = _measure(name, expr, expr_kind, **kw)
    m["kind"] = "windowed"
    m["window"] = window
    return m


def _window(order, rtype, n=None, unit=None, anchor=None, semi="last",
            offset=None, raw_range=None):
    return {"order": order,
            "range": {"type": rtype, "n": n, "unit": unit, "anchor": anchor},
            "raw_range": raw_range or rtype, "semiadditive": semi,
            "offset": offset, "raw_offset": None,
            "density_check_required": rtype in ("trailing", "leading")}


DIMS = [
    _dim("transaction_date", "transaction_date", "direct"),
    _dim("order_month", "DATE_TRUNC('MONTH', order_date)", "computed"),
    _dim("order_quarter", "DATE_TRUNC('QUARTER', order_date)", "computed"),
    _dim("balance_date", "balance_date", "direct"),
]


class TestWindowMeasures:
    def test_trailing_exclusive_golden(self):
        # ts-from-databricks.md Measure 5 (post-PR-1 corrected form)
        out = translate_window_measure(
            _win_measure("revenue_7d_rolling", "SUM(unit_price * quantity)",
                         "complex", _window("transaction_date", "trailing", 7,
                                           "day", "exclusive",
                                           raw_range="trailing 7 day")),
            DIMS, TABLES)
        assert out["ts_expr"] == ("moving_sum ( [TRANSACTIONS::unit_price] * "
                                  "[TRANSACTIONS::quantity] , 7 , -1 , "
                                  "[TRANSACTIONS::transaction_date] )")
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["sparse_data_risk"]
        assert "BL-098" in out["annotations"][0]["detail"]

    def test_trailing_inclusive(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("transaction_date", "trailing", 7, "day",
                                 "inclusive"), physical_ref="x",
                         agg_function="SUM"),
            DIMS, TABLES)
        assert " , 6 , 0 , " in out["ts_expr"]

    def test_leading_exclusive(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("transaction_date", "leading", 7, "day",
                                 "exclusive"), physical_ref="x",
                         agg_function="SUM"),
            DIMS, TABLES)
        assert " , -1 , 7 , " in out["ts_expr"]

    def test_avg_uses_moving_average(self):
        out = translate_window_measure(
            _win_measure("m", "AVG(x)", "simple",
                         _window("transaction_date", "trailing", 30, "day",
                                 "exclusive"), physical_ref="x",
                         agg_function="AVG"),
            DIMS, TABLES)
        assert out["ts_expr"].startswith("moving_average ( [TRANSACTIONS::x] , 30 , -1")

    def test_max_pending_verification(self):
        out = translate_window_measure(
            _win_measure("m", "MAX(x)", "simple",
                         _window("transaction_date", "trailing", 7, "day",
                                 "exclusive"), physical_ref="x",
                         agg_function="MAX"),
            DIMS, TABLES)
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["sparse_data_risk", "pending_verification"]

    def test_trailing_non_day_unit_skipped(self):
        with pytest.raises(UntranslatableError, match="month.*day grain"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("order_month", "trailing", 2, "month",
                                     "exclusive"), physical_ref="x",
                             agg_function="SUM"),
                DIMS, TABLES)

    def test_cumulative_sum(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("transaction_date", "cumulative"),
                         physical_ref="x", agg_function="SUM"),
            DIMS, TABLES)
        assert out["ts_expr"] == ("cumulative_sum ( [TRANSACTIONS::x] , "
                                  "[TRANSACTIONS::transaction_date] )")
        assert out["annotations"] == []

    def test_semiadditive_last_raw_date(self):
        out = translate_window_measure(
            _win_measure("inventory_balance", "SUM(FILLED_INVENTORY)", "simple",
                         _window("balance_date", "current"),
                         physical_ref="FILLED_INVENTORY", agg_function="SUM"),
            DIMS, TABLES)
        assert out["ts_expr"] == ("last_value ( sum ( [TRANSACTIONS::FILLED_INVENTORY] ) , "
                                  "query_groups ( ) , { [TRANSACTIONS::balance_date] } )")

    def test_semiadditive_first_raw_date(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("balance_date", "current", semi="first"),
                         physical_ref="x", agg_function="SUM"),
            DIMS, TABLES)
        assert out["ts_expr"].startswith("first_value (")

    def test_current_truncated_no_offset_plain_sum(self):
        out = translate_window_measure(
            _win_measure("monthly_revenue", "SUM(LINE_TOTAL)", "simple",
                         _window("order_month", "current"),
                         physical_ref="LINE_TOTAL", agg_function="SUM"),
            DIMS, TABLES)
        assert out["ts_expr"] == "sum ( [TRANSACTIONS::LINE_TOTAL] )"

    def test_current_offset_month_lag_verified(self):
        out = translate_window_measure(
            _win_measure("prior_month_revenue", "SUM(LINE_TOTAL)", "simple",
                         _window("order_month", "current",
                                 offset={"n": -1, "unit": "month"}),
                         physical_ref="LINE_TOTAL", agg_function="SUM"),
            DIMS, TABLES, allow_row_lag=True)
        assert out["ts_expr"] == ("moving_sum ( [TRANSACTIONS::LINE_TOTAL] , 1 , -1 , "
                                  "[TRANSACTIONS::order_date] )")
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["row_lag_approximation", "one_row_per_period"]  # the C6-verified combo — no pending

    def test_current_offset_year_at_month_grain_pending_c8(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("order_month", "current",
                                 offset={"n": -1, "unit": "year"}),
                         physical_ref="x", agg_function="SUM"),
            DIMS, TABLES, allow_row_lag=True)
        assert " , 12 , -12 , " in out["ts_expr"]
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["row_lag_approximation", "one_row_per_period", "pending_verification"]
        assert "C8" in out["annotations"][2]["detail"]

    def test_current_offset_quarter_grain_pending_c8(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("order_quarter", "current",
                                 offset={"n": -3, "unit": "month"}),
                         physical_ref="x", agg_function="SUM"),
            DIMS, TABLES, allow_row_lag=True)
        assert " , 1 , -1 , " in out["ts_expr"]
        assert "pending_verification" in [a["kind"] for a in out["annotations"]]

    def test_offset_day_unit_skipped(self):
        with pytest.raises(UntranslatableError, match="offset unit 'day'"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("order_month", "current",
                                     offset={"n": -30, "unit": "day"}),
                             physical_ref="x", agg_function="SUM"),
                DIMS, TABLES, allow_row_lag=True)

    def test_offset_not_divisible_skipped(self):
        with pytest.raises(UntranslatableError, match="divide"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("order_quarter", "current",
                                     offset={"n": -1, "unit": "month"}),
                             physical_ref="x", agg_function="SUM"),
                DIMS, TABLES, allow_row_lag=True)

    def test_range_all_skipped_judgment(self):
        with pytest.raises(UntranslatableError, match="partition-dimension"):
            translate_window_measure(
                _win_measure("all_amount", "SUM(x)", "simple",
                             _window("transaction_date", "all"),
                             physical_ref="x", agg_function="SUM"),
                DIMS, TABLES)

    def test_order_dimension_missing_skipped(self):
        with pytest.raises(UntranslatableError, match="order.*not found"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("nope", "cumulative"),
                             physical_ref="x", agg_function="SUM"),
                DIMS, TABLES)

    def test_order_dimension_truncates_non_column_raises(self):
        # DATE_TRUNC('MONTH', CAST(x AS DATE)) — the inner isn't a plain
        # column, so the sort ref must not leak "CAST(x AS DATE)" verbatim
        # into the resolver; fail loud instead.
        dims = DIMS + [_dim("bad_month", "DATE_TRUNC('MONTH', CAST(x AS DATE))",
                            "computed")]
        with pytest.raises(UntranslatableError, match="non-column"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("bad_month", "cumulative"),
                             physical_ref="x", agg_function="SUM"),
                dims, TABLES)

    def test_complex_inner_expr_stripped_of_outer_agg(self):
        # golden Measure 5 uses SUM(a * b) — inner is a * b (rule 9)
        out = translate_window_measure(
            _win_measure("m", "SUM(unit_price * quantity)", "complex",
                         _window("transaction_date", "trailing", 7, "day",
                                 "exclusive")),
            DIMS, TABLES)
        assert out["ts_expr"].startswith(
            "moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ,")

    def test_current_window_unmapped_agg_raises(self):
        # MEDIAN has no ThoughtSpot aggregate-function mapping for a range:
        # current window — must fail loud, not silently emit `median ( … )`.
        with pytest.raises(UntranslatableError, match="MEDIAN"):
            translate_window_measure(
                _win_measure("m", "MEDIAN(x)", "complex",
                             _window("order_month", "current")),
                DIMS, TABLES)

    def test_windowed_cross_measure_skipped(self):
        with pytest.raises(UntranslatableError, match="MEASURE"):
            translate_window_measure(
                _win_measure("m", "MEASURE(a) - MEASURE(b)",
                             "complex_cross_measure",
                             _window("order_month", "current"),
                             cross_refs=["a", "b"]),
                DIMS, TABLES)


# --- BL-315 / BL-316 (2026-09-28): budget/forecast Metric View constructs ----

FWK = "DATE_ADD(DATE_TRUNC('WEEK', DATE_ADD(dt, 3)), -3)"
BF_DIMS = [
    _dim("date", "dt", "direct"),
    _dim("month", "DATE_TRUNC('MONTH', dt)", "computed"),
    _dim("week", FWK, "computed"),
    _dim("week_mond", "DATE_TRUNC('WEEK', dt)", "computed"),
]
LAST_ACTUAL = {"agg": "MAX", "arg": "dt", "where": "observation = 'current'",
               "sql": "(SELECT MAX(dt) FROM c.s.t WHERE observation = 'current')"}
GA = ("group_aggregate ( max ( if ( [TRANSACTIONS::observation] = 'current' ) "
      "then [TRANSACTIONS::dt] else null ) , { } , { } )")


def _offset(n, unit):
    return {"n": n, "unit": unit}


class TestBL322RowLagRefusedByDefault:
    """A period comparison (range: current + offset) has no safe ThoughtSpot
    formula: moving_sum counts query rows, the MV counts calendar periods, and
    the two diverge silently at any other grain (live-measured 2026-09-28)."""

    W = _window("month", "current", offset={"n": -12, "unit": "month"})

    def test_refused_by_default_with_the_reason(self):
        with pytest.raises(UntranslatableError, match="no safe ThoughtSpot formula") as e:
            translate_window_measure(_win_measure("py_monthly", "SUM(x)", "simple", self.W,
                                                  physical_ref="x", agg_function="SUM"),
                                     BF_DIMS, TABLES)
        msg = str(e.value)
        assert "calendar PERIODS" in msg and "--allow-row-lag" in msg and "BL-322" in msg

    def test_opt_in_emits_and_annotates(self):
        out = translate_window_measure(
            _win_measure("py_monthly", "SUM(x)", "simple", self.W, physical_ref="x",
                         agg_function="SUM"), BF_DIMS, TABLES, allow_row_lag=True)
        assert out["ts_expr"].startswith("moving_sum (")
        assert out["annotations"][0]["kind"] == "row_lag_approximation"

    def test_orchestrator_skips_and_threads_flag(self):
        m = _win_measure("py_monthly", "SUM(x)", "simple", self.W, physical_ref="x",
                         agg_function="SUM")
        out = translate_metric_view(_parsed(dimensions=BF_DIMS, measures=[m]), TABLES)
        assert [s["name"] for s in out["skipped"]] == ["py_monthly"]
        assert "no safe ThoughtSpot formula" in out["skipped"][0]["reason"]
        out2 = translate_metric_view(_parsed(dimensions=BF_DIMS, measures=[m]), TABLES,
                                     allow_row_lag=True)
        assert out2["skipped"] == []

    def test_no_offset_windows_unaffected(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple", _window("date", "current"),
                         physical_ref="x", agg_function="SUM"), BF_DIMS, TABLES)
        assert out["ts_expr"].startswith("last_value (")


class TestBL315DayGrainOffset:
    """A day-grain `range: current` + `offset:` used to return last_value with
    the offset silently dropped — a prior-year measure gave this year's value."""

    def test_day_offset_is_a_lag_never_last_value(self):
        out = translate_window_measure(
            _win_measure("py_daily", "SUM(x) FILTER (WHERE observation = 'current')",
                         "conditional", _window("date", "current",
                                                offset=_offset(-364, "day"))),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert "last_value" not in out["ts_expr"]
        assert out["ts_expr"] == (
            "moving_sum ( if ( [TRANSACTIONS::observation] = 'current' ) then "
            "[TRANSACTIONS::x] else null , 364 , -364 , [TRANSACTIONS::dt] )")
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["row_lag_approximation", "one_row_per_period"]  # day/day is live-verified

    def test_week_offset_at_day_grain_counts_days(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("date", "current", offset=_offset(-2, "week")),
                         physical_ref="x", agg_function="SUM"),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert " , 14 , -14 , " in out["ts_expr"]

    def test_month_offset_at_day_grain_raises(self):
        with pytest.raises(UntranslatableError, match="not a fixed number"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("date", "current", offset=_offset(-1, "month")),
                             physical_ref="x", agg_function="SUM"),
                BF_DIMS, TABLES, allow_row_lag=True)

    def test_no_offset_day_grain_still_semiadditive(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple", _window("date", "current"),
                         physical_ref="x", agg_function="SUM"),
            BF_DIMS, TABLES)
        assert out["ts_expr"].startswith("last_value ( sum ( [TRANSACTIONS::x] )")


class TestFormulaOrderedWeek:
    """BL-316 item 6 — a non-bucket (date-shifted) order dimension."""

    def test_friday_week_lag_orders_by_formula(self):
        out = translate_window_measure(
            _win_measure("py_weekly", "SUM(x)", "simple",
                         _window("week", "current", offset=_offset(-364, "day")),
                         physical_ref="x", agg_function="SUM"),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert out["ts_expr"] == "moving_sum ( [TRANSACTIONS::x] , 52 , -52 , [formula_Week] )"
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["row_lag_approximation", "one_row_per_period", "order_by_formula"]

    def test_plain_week_trunc_also_formula_ordered(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("week_mond", "current", offset=_offset(-1, "week")),
                         physical_ref="x", agg_function="SUM"),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert out["ts_expr"].endswith(", 1 , -1 , [formula_Week Mond] )")
        assert "pending_verification" in [a["kind"] for a in out["annotations"]]

    def test_week_offset_not_multiple_of_7_raises(self):
        with pytest.raises(UntranslatableError, match="divide evenly"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("week", "current", offset=_offset(-10, "day")),
                             physical_ref="x", agg_function="SUM"),
                BF_DIMS, TABLES, allow_row_lag=True)

    def test_trailing_over_formula_order_raises(self):
        with pytest.raises(UntranslatableError, match="derived order"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("week", "cumulative"),
                             physical_ref="x", agg_function="SUM"),
                BF_DIMS, TABLES)

    def test_two_columns_is_not_a_shifted_trunc(self):
        dims = BF_DIMS + [_dim("odd", "DATE_ADD(DATE_TRUNC('WEEK', a), b)", "computed")]
        with pytest.raises(UntranslatableError, match="cannot determine"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("odd", "current", offset=_offset(-7, "day")),
                             physical_ref="x", agg_function="SUM"),
                dims, TABLES)


class TestWindowReviewGuards:
    """Adversarial review 2026-09-28."""

    def test_nested_aggregate_in_window_raises(self):
        with pytest.raises(UntranslatableError, match="nested aggregate"):
            translate_window_measure(
                _win_measure("m", "SUM(SUM(a))", "complex", _window("date", "cumulative")),
                BF_DIMS, TABLES)

    def test_untranslatable_order_dim_raises(self):
        # passes the shifted-trunc shape check, but its column's alias is unmapped
        dims = BF_DIMS + [_dim("odd_week", "DATE_ADD(DATE_TRUNC('WEEK', nope.dt), -3)",
                               "computed")]
        with pytest.raises(UntranslatableError, match="does not translate"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("odd_week", "current", offset=_offset(-1, "week")),
                             physical_ref="x", agg_function="SUM"),
                dims, TABLES)

    def test_date_sub_order_dim_not_formula_ordered(self):
        dims = BF_DIMS + [_dim("sub_week", "DATE_SUB(DATE_TRUNC('WEEK', DATE_ADD(dt, 3)), 3)",
                               "computed")]
        with pytest.raises(UntranslatableError, match="cannot determine"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("sub_week", "current", offset=_offset(-1, "week")),
                             physical_ref="x", agg_function="SUM"),
                dims, TABLES)

    def test_arithmetic_is_not_a_date_shift(self):
        dims = BF_DIMS + [_dim("minus", "DATE_TRUNC('MONTH', dt) - 3", "computed")]
        with pytest.raises(UntranslatableError, match="cannot determine"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("minus", "current", offset=_offset(-1, "month")),
                             physical_ref="x", agg_function="SUM"),
                dims, TABLES)

    def test_order_by_formula_only_when_used(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple", _window("week", "current"),
                         physical_ref="x", agg_function="SUM"),
            BF_DIMS, TABLES)
        assert out["ts_expr"] == "sum ( [TRANSACTIONS::x] )"
        assert "order_by_formula" not in [a["kind"] for a in out["annotations"]]

    def test_unverified_n_keeps_pending(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("date", "current", offset=_offset(-7, "day")),
                         physical_ref="x", agg_function="SUM"),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert "pending_verification" in [a["kind"] for a in out["annotations"]]


class TestRatioWindow:
    """BL-316 item 7 — the window applies to each aggregate of a ratio."""

    def test_ratio_monthly_lag(self):
        out = translate_window_measure(
            _win_measure("py_ecpc", "SUM(r) / NULLIF(SUM(c), 0)", "complex",
                         _window("month", "current", offset=_offset(-12, "month"))),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert out["ts_expr"] == (
            "moving_sum ( [TRANSACTIONS::r] , 12 , -12 , [TRANSACTIONS::dt] ) / "
            "moving_sum ( [TRANSACTIONS::c] , 12 , -12 , [TRANSACTIONS::dt] )")
        # month/month is verified at N=12: no C8 annotation
        assert [a["kind"] for a in out["annotations"]] == ["row_lag_approximation",
                                                           "one_row_per_period"]

    def test_ratio_semiadditive_last(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(r) / NULLIF(SUM(c), 0)", "complex",
                         _window("date", "current")),
            BF_DIMS, TABLES)
        assert out["ts_expr"].count("last_value") == 2

    def test_no_aggregate_raises(self):
        with pytest.raises(UntranslatableError, match="no aggregate"):
            translate_window_measure(
                _win_measure("m", "x + 1", "complex",
                             _window("month", "current", offset=_offset(-1, "month"))),
                BF_DIMS, TABLES, allow_row_lag=True)


class TestScalarSubquery:
    """BL-316 item 1 — a whole-table scalar subquery over the MV's own source."""

    def test_budget_cap_is_whole_table_lod(self):
        out = translate_measure(_measure(
            "budget_capped",
            "SUM(x) FILTER (WHERE observation = 'budget' AND dt <= __MVSCALAR_0__)",
            "conditional", scalar_subqueries=[LAST_ACTUAL]), TABLES)
        assert out["ts_expr"] == (
            "sum_if ( [TRANSACTIONS::observation] = 'budget' and "
            f"[TRANSACTIONS::dt] <= {GA} , [TRANSACTIONS::x] )")
        assert [a["kind"] for a in out["annotations"]] == ["scalar_subquery"]

    def test_no_where_clause(self):
        sc = dict(LAST_ACTUAL, where=None, agg="SUM", arg="x")
        out = translate_measure(_measure(
            "share", "SUM(x) / NULLIF(__MVSCALAR_0__, 0)", "complex",
            scalar_subqueries=[sc]), TABLES)
        assert "group_aggregate ( sum ( [TRANSACTIONS::x] ) , { } , { } )" in out["ts_expr"]

    def test_inside_window_uses_yesterday_option_a(self):
        out = translate_window_measure(
            _win_measure("py_monthly",
                         "SUM(x) FILTER (WHERE dt <= DATE_ADD(__MVSCALAR_0__, -364))",
                         "conditional",
                         _window("month", "current", offset=_offset(-12, "month")),
                         scalar_subqueries=[LAST_ACTUAL]),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert "group_aggregate" not in out["ts_expr"]  # cannot nest in moving_sum
        assert ("add_days ( add_days ( today ( ) , -1 ) , - 364 )"
                in out["ts_expr"])
        assert "cap_assumption" in [a["kind"] for a in out["annotations"]]

    def test_scalar_on_formula_ordered_week_uses_underlying_date(self):
        out = translate_window_measure(
            _win_measure("py_weekly",
                         "SUM(x) FILTER (WHERE dt <= DATE_ADD(__MVSCALAR_0__, -364))",
                         "conditional",
                         _window("week", "current", offset=_offset(-364, "day")),
                         scalar_subqueries=[LAST_ACTUAL]),
            BF_DIMS, TABLES, allow_row_lag=True)
        assert "add_days ( add_days ( today ( ) , -1 ) , - 364 )" in out["ts_expr"]
        cap = next(a for a in out["annotations"] if a["kind"] == "cap_assumption")
        assert "where observation = 'current'" in cap["detail"]  # WHERE not hidden

    def test_max_of_non_date_inside_window_raises(self):
        # review finding B: MAX(amount) is not "the latest date"
        with pytest.raises(UntranslatableError, match="order date column"):
            translate_window_measure(
                _win_measure("m", "SUM(x) FILTER (WHERE x <= __MVSCALAR_0__)",
                             "conditional",
                             _window("month", "current", offset=_offset(-1, "month")),
                             scalar_subqueries=[dict(LAST_ACTUAL, arg="amount")]),
                BF_DIMS, TABLES, allow_row_lag=True)

    def test_max_of_other_date_inside_window_raises(self):
        with pytest.raises(UntranslatableError, match="order date column"):
            translate_window_measure(
                _win_measure("m", "SUM(x) FILTER (WHERE dt <= __MVSCALAR_0__)",
                             "conditional",
                             _window("month", "current", offset=_offset(-1, "month")),
                             scalar_subqueries=[dict(LAST_ACTUAL, arg="ship_dt")]),
                BF_DIMS, TABLES, allow_row_lag=True)

    def test_scalar_under_mv_filter_is_refused(self):
        # review: {} LODs still apply the mirrored model filter; the subquery doesn't
        m = _measure(
            "capped", "SUM(x) FILTER (WHERE dt <= __MVSCALAR_0__)", "conditional",
            scalar_subqueries=[LAST_ACTUAL])
        out = translate_metric_view(_parsed(dimensions=[], measures=[m],
                                            filter_sql="region = 'EU'"), TABLES)
        assert out["translated"] == []
        assert "unfiltered source" in out["skipped"][0]["reason"]
        out2 = translate_metric_view(_parsed(dimensions=[], measures=[m]), TABLES)
        assert out2["skipped"] == [] and len(out2["translated"]) == 1

    def test_count_star_scalar_is_count_1(self):
        sc = dict(LAST_ACTUAL, agg="COUNT", arg="*", where=None)
        out = translate_measure(_measure(
            "m", "SUM(x) / NULLIF(__MVSCALAR_0__, 0)", "complex",
            scalar_subqueries=[sc]), TABLES)
        assert "group_aggregate ( count ( 1 ) , { } , { } )" in out["ts_expr"]

    def test_non_max_scalar_inside_window_raises(self):
        with pytest.raises(UntranslatableError, match=r"only\s+MAX"):
            translate_window_measure(
                _win_measure("m", "SUM(x) / NULLIF(__MVSCALAR_0__, 0)", "complex",
                             _window("month", "current", offset=_offset(-1, "month")),
                             scalar_subqueries=[dict(LAST_ACTUAL, agg="SUM", arg="x")]),
                BF_DIMS, TABLES, allow_row_lag=True)


class TestConditionalFallback:
    """BL-316 item 4 — `FILTER (…) / NULLIF (…)` used to reach the tokenizer
    as a half-expression ("unexpected trailing token ')'")."""

    def test_filter_then_ratio(self):
        out = translate_measure(_measure(
            "rps", "SUM(r) FILTER (WHERE o = 'current') / NULLIF(SUM(s), 0)",
            "conditional"), TABLES)
        assert out["ts_expr"] == (
            "sum_if ( [TRANSACTIONS::o] = 'current' , "
            "[TRANSACTIONS::r] ) / sum ( [TRANSACTIONS::s] )")

    def test_whole_expression_filter_unchanged(self):
        out = translate_measure(_measure(
            "m", "SUM(r) FILTER (WHERE o = 'current')", "conditional"), TABLES)
        assert out["ts_expr"] == "sum_if ( [TRANSACTIONS::o] = 'current' , [TRANSACTIONS::r] )"


def _parsed(dimensions=(), measures=(), filter_sql=None):
    return {"version": "1.1", "comment": None,
            "source": {"kind": "table_fqn", "raw": "c.s.t", "parts": ["c", "s", "t"],
                       "needs_live_check": True},
            "joins": [], "dimensions": list(dimensions),
            "measures": list(measures), "filter": filter_sql,
            "materialization": None, "warnings": [], "unsupported": []}


class TestOrchestrator:
    def test_cross_measure_inlines_column_ref(self):
        measures = [
            _measure("quantity", "SUM(QUANTITY)", "simple",
                     agg_function="SUM", physical_ref="QUANTITY"),
            _measure("ratio", "MEASURE(quantity) / ANY_VALUE(category_quantity)",
                     "complex_cross_measure", cross_refs=["quantity"],
                     lod_refs=["category_quantity"]),
        ]
        dims = [_dim("category_quantity",
                     "SUM(QUANTITY) OVER (PARTITION BY CAT)", "lod_window",
                     inner_agg="SUM", inner_expr="QUANTITY",
                     partition_by=["CAT"])]
        out = translate_metric_view(_parsed(dims, measures), TABLES)
        ratio = next(e for e in out["translated"] if e["name"] == "ratio")
        assert ratio["ts_expr"] == (
            "( sum ( [TRANSACTIONS::QUANTITY] ) ) / "
            "( group_aggregate ( sum ( [TRANSACTIONS::QUANTITY] ) , "
            "{ [TRANSACTIONS::CAT] } , query_filters ( ) ) )")
        assert out["dependency_dag"] == {"ratio": ["quantity", "category_quantity"]}

    def test_chained_refs_inline_transitively(self):
        measures = [
            _measure("a", "SUM(x)", "simple", agg_function="SUM",
                     physical_ref="x"),
            _measure("b", "MEASURE(a) * 2", "complex_cross_measure",
                     cross_refs=["a"]),
            _measure("c", "MEASURE(b) + 1", "complex_cross_measure",
                     cross_refs=["b"]),
        ]
        out = translate_metric_view(_parsed((), measures), TABLES)
        c = next(e for e in out["translated"] if e["name"] == "c")
        assert c["ts_expr"] == "( ( sum ( [TRANSACTIONS::x] ) ) * 2 ) + 1"

    def test_cycle_skips_all_members(self):
        measures = [
            _measure("a", "MEASURE(b) + 1", "complex_cross_measure",
                     cross_refs=["b"]),
            _measure("b", "MEASURE(a) + 1", "complex_cross_measure",
                     cross_refs=["a"]),
        ]
        out = translate_metric_view(_parsed((), measures), TABLES)
        assert {s["name"] for s in out["skipped"]} == {"a", "b"}
        assert all("circular" in s["reason"] for s in out["skipped"])

    def test_ref_to_skipped_measure_skips_referrer(self):
        measures = [
            _measure("bad", "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY x)",
                     "simple", agg_function="PERCENTILE_CONT",
                     physical_ref="x"),
            _measure("dep", "MEASURE(bad) * 2", "complex_cross_measure",
                     cross_refs=["bad"]),
        ]
        out = translate_metric_view(_parsed((), measures), TABLES)
        dep = next(s for s in out["skipped"] if s["name"] == "dep")
        assert "bad" in dep["reason"]

    def test_unknown_ref_skips(self):
        measures = [_measure("dep", "MEASURE(ghost) * 2",
                             "complex_cross_measure", cross_refs=["ghost"])]
        out = translate_metric_view(_parsed((), measures), TABLES)
        assert "ghost" in out["skipped"][0]["reason"]

    def test_filter_translated_and_counted(self):
        out = translate_metric_view(
            _parsed((), (), filter_sql="status != 'cancelled'"), TABLES)
        assert out["filter"]["ts_expr"] == "[TRANSACTIONS::status] != 'cancelled'"
        assert out["stats"] == {"total": 1, "translated": 1, "skipped": 0}

    def test_untranslatable_filter_is_skipped_role_filter(self):
        out = translate_metric_view(
            _parsed((), (), filter_sql="s LIKE 'a!%' ESCAPE '!'"), TABLES)
        assert out["filter"] is None
        assert out["skipped"][0]["role"] == "filter"

    def test_window_measures_listed_even_when_skipped(self):
        measures = [
            _win_measure("all_amount", "SUM(x)", "simple",
                         _window("transaction_date", "all"),
                         physical_ref="x", agg_function="SUM"),
        ]
        out = translate_metric_view(_parsed(DIMS, measures), TABLES)
        assert out["window_measures"] == ["all_amount"]
        assert out["skipped"][0]["name"] == "all_amount"

    def test_stats_and_shapes(self):
        out = translate_metric_view(
            _parsed([_dim("d", "d", "direct")],
                    [_measure("m", "SUM(x)", "simple", agg_function="SUM",
                              physical_ref="x")],
                    filter_sql="x > 0"), TABLES)
        assert out["stats"] == {"total": 3, "translated": 3, "skipped": 0}
        assert set(out) == {"translated", "skipped", "filter",
                            "dependency_dag", "window_measures", "stats"}

    def test_tables_map_validated(self):
        with pytest.raises(ValueError, match="source"):
            translate_metric_view(_parsed(), {"orders": "DM_ORDER"})

    def test_duplicate_refs_to_deferred_measure_not_circular(self):
        measures = [
            _measure("a", "SUM(x)", "simple", agg_function="SUM",
                     physical_ref="x"),
            _measure("b", "MEASURE(a) * 2", "complex_cross_measure",
                     cross_refs=["a"]),
            _measure("c", "MEASURE(b) + MEASURE(b)", "complex_cross_measure",
                     cross_refs=["b", "b"]),
        ]
        out = translate_metric_view(_parsed((), measures), TABLES)
        assert out["skipped"] == []
        c = next(e for e in out["translated"] if e["name"] == "c")
        assert c["ts_expr"] == ("( ( sum ( [TRANSACTIONS::x] ) ) * 2 ) + "
                                "( ( sum ( [TRANSACTIONS::x] ) ) * 2 )")

    def test_any_value_of_direct_dimension_inlines_column_ref(self):
        dims = [_dim("region", "region", "direct")]
        measures = [_measure("m", "SUM(x) * ANY_VALUE(region)",
                             "complex_cross_measure", lod_refs=["region"])]
        out = translate_metric_view(_parsed(dims, measures), TABLES)
        m = next(e for e in out["translated"] if e["name"] == "m")
        assert m["ts_expr"] == "sum ( [TRANSACTIONS::x] ) * ( [TRANSACTIONS::region] )"

    def test_truncated_expr_skipped_not_crashed(self):
        # A truncated SQL expression (dangling IS with no NULL/NOT NULL that
        # follows) must land in skipped[] with a reason, never raise an
        # unguarded IndexError out of translate_metric_view.
        measures = [_measure("bad", "x IS", "complex")]
        out = translate_metric_view(_parsed((), measures), TABLES)
        assert out["skipped"] == [
            {"name": "bad", "role": "measure",
             "reason": "unexpected end of expression"}]

    def test_windowed_cycle_member_listed_in_window_measures(self):
        measures = [
            _win_measure("m1", "SUM(x)", "simple",
                         _window("transaction_date", "cumulative"),
                         physical_ref="x", agg_function="SUM",
                         cross_refs=["m2"]),
            _measure("m2", "MEASURE(m1) * 2", "complex_cross_measure",
                     cross_refs=["m1"]),
        ]
        out = translate_metric_view(_parsed(DIMS, measures), TABLES)
        assert "m1" in out["window_measures"]
        assert {s["name"] for s in out["skipped"]} == {"m1", "m2"}


class TestNormalizeTables:
    def test_string_values_pass_through(self):
        from ts_cli.databricks.mv_translate import normalize_tables
        assert normalize_tables({"source": "FACT", "orders": "DM_ORDER"}) == {
            "source": "FACT", "orders": "DM_ORDER"}

    def test_object_values_extract_name(self):
        from ts_cli.databricks.mv_translate import normalize_tables
        tables = {"source": {"name": "FACT", "fqn": "guid-1", "create": True},
                  "orders": "DM_ORDER"}
        assert normalize_tables(tables) == {"source": "FACT", "orders": "DM_ORDER"}

    def test_object_without_name_raises(self):
        from ts_cli.databricks.mv_translate import normalize_tables
        with pytest.raises(ValueError, match="orders"):
            normalize_tables({"source": "FACT", "orders": {"fqn": "guid-2"}})

    def test_non_str_non_dict_value_raises(self):
        from ts_cli.databricks.mv_translate import normalize_tables
        with pytest.raises(ValueError, match="orders"):
            normalize_tables({"source": "FACT", "orders": 7})

    def test_missing_source_raises(self):
        from ts_cli.databricks.mv_translate import normalize_tables
        with pytest.raises(ValueError, match="source"):
            normalize_tables({"orders": "DM_ORDER"})

    def test_translate_accepts_object_form(self):
        parsed = {"version": "1.1", "comment": None,
                  "source": {"kind": "table_fqn", "raw": "c.s.t", "parts": ["c", "s", "t"],
                             "needs_live_check": True},
                  "joins": [], "filter": None, "materialization": None,
                  "warnings": [], "unsupported": [],
                  "dimensions": [{"name": "region", "expr": "region", "kind": "direct",
                                  "display_name": None, "comment": None, "synonyms": [],
                                  "inner_agg": None, "inner_expr": None, "partition_by": []}],
                  "measures": []}
        out = translate_metric_view(parsed, {"source": {"name": "FACT", "fqn": "g"}})
        assert out["translated"][0]["table"] == "FACT"


# --- ts databricks translate-formulas CLI (BL-063 PR3) -----------------

import json


from ts_cli.cli import app
from ts_cli.databricks.mv_parse import parse_metric_view

from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)


def _stderr(result):
    try:
        return result.stderr
    except ValueError:
        return ""


def _write_inputs(tmp_path, parsed, tables):
    inp = tmp_path / "parsed.json"
    inp.write_text(json.dumps(parsed))
    tab = tmp_path / "tables.json"
    tab.write_text(json.dumps(tables))
    return inp, tab, tmp_path / "translated.json"


class TestTranslateFormulasCli:
    def test_happy_path_exit_0_and_stats_on_stderr(self, tmp_path):
        parsed = _parsed([_dim("d", "d", "direct")],
                         [_measure("m", "SUM(x)", "simple",
                                   agg_function="SUM", physical_ref="x")])
        inp, tab, out = _write_inputs(tmp_path, parsed, TABLES)
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(inp), "--output", str(out),
                                     "--tables", str(tab)])
        assert result.exit_code == 0, result.stdout + _stderr(result)
        assert result.stdout == ""  # stdout purity (DEFER m)
        err = _stderr(result)
        assert "translated" in err and "2" in err
        data = json.loads(out.read_text())
        assert data["stats"]["translated"] == 2

    def test_skips_reported_on_stderr_exit_0(self, tmp_path):
        parsed = _parsed((), [_win_measure(
            "all_amount", "SUM(x)", "simple",
            _window("transaction_date", "all"),
            physical_ref="x", agg_function="SUM")])
        parsed["dimensions"] = DIMS
        inp, tab, out = _write_inputs(tmp_path, parsed, TABLES)
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(inp), "--output", str(out),
                                     "--tables", str(tab)])
        assert result.exit_code == 0
        err = _stderr(result)
        assert "SKIPPED" in err and "all_amount" in err

    def test_bl098_warning_on_stderr(self, tmp_path):
        parsed = _parsed(DIMS, [_win_measure(
            "roll", "SUM(x)", "simple",
            _window("transaction_date", "trailing", 7, "day", "exclusive",
                    raw_range="trailing 7 day"),
            physical_ref="x", agg_function="SUM")])
        inp, tab, out = _write_inputs(tmp_path, parsed, TABLES)
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(inp), "--output", str(out),
                                     "--tables", str(tab)])
        err = _stderr(result)
        assert "WARNING" in err and "BL-098" in err

    def test_missing_input_exit_1(self, tmp_path):
        tab = tmp_path / "tables.json"
        tab.write_text(json.dumps(TABLES))
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(tmp_path / "nope.json"),
                                     "--output", str(tmp_path / "o.json"),
                                     "--tables", str(tab)])
        assert result.exit_code == 1

    def test_bad_tables_map_exit_1(self, tmp_path):
        parsed = _parsed()
        inp, tab, out = _write_inputs(tmp_path, parsed, {"orders": "X"})
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(inp), "--output", str(out),
                                     "--tables", str(tab)])
        assert result.exit_code == 1
        assert "source" in _stderr(result)

    def test_tables_file_non_dict_json_exit_1_no_traceback(self, tmp_path):
        # A syntactically-valid JSON array (not an object) for --tables must
        # exit cleanly with a message on stderr, not an unguarded traceback.
        # (translate_metric_view's own _validate_tables already catches this
        # shape, but _load_json must guard it too — see the --input variant
        # below, which crashes with an unguarded IndexError/TypeError today.)
        parsed = _parsed()
        inp = tmp_path / "parsed.json"
        inp.write_text(json.dumps(parsed))
        tab = tmp_path / "tables.json"
        tab.write_text(json.dumps([1, 2]))
        out = tmp_path / "translated.json"
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(inp), "--output", str(out),
                                     "--tables", str(tab)])
        assert result.exit_code == 1
        err = _stderr(result)
        assert "must be a JSON object" in err
        assert "Traceback" not in err

    def test_input_file_non_dict_json_exit_1_no_traceback(self, tmp_path):
        # A syntactically-valid JSON array for --input has no downstream
        # dict-shape validation before translate_metric_view indexes into
        # it (parsed["dimensions"]) — today this escapes as a raw
        # TypeError traceback instead of a clean exit 1.
        inp = tmp_path / "parsed.json"
        inp.write_text(json.dumps([1, 2]))
        tab = tmp_path / "tables.json"
        tab.write_text(json.dumps(TABLES))
        out = tmp_path / "translated.json"
        result = runner.invoke(app, ["databricks", "translate-formulas",
                                     "--input", str(inp), "--output", str(out),
                                     "--tables", str(tab)])
        assert result.exit_code == 1
        err = _stderr(result)
        assert "must be a JSON object" in err
        assert "Traceback" not in err


# --- Golden worked-example fixtures (BL-063 PR3 acceptance gate) -------
#
# Copied verbatim from the source-of-truth worked examples:
#   agents/shared/worked-examples/databricks/ts-from-databricks.md
#   agents/shared/worked-examples/databricks/ts-from-databricks-sql-view.md
# The expected ts_expr strings are the POST-2026-07-09-correction texts
# recorded in those docs (revenue_7d_rolling uses moving_sum(..., 7, -1, ...)).

ECOMMERCE_MV_YAML = """\
version: 1.1
comment: >-
  E-commerce transaction metrics — revenue, customer counts, order value,
  and return analysis on the transactions table.
source: analytics.ecommerce.transactions
filter: status != 'cancelled'
dimensions:
  - name: transaction_id
    expr: transaction_id
  - name: product_category
    expr: product_category
    display_name: 'Product Category'
    synonyms: ['category', 'product type']
  - name: transaction_month
    expr: DATE_TRUNC('MONTH', transaction_date)
  - name: customer_region
    expr: customer_region
    display_name: 'Region'
    synonyms: ['area', 'territory']
  - name: transaction_date
    expr: transaction_date
measures:
  - name: total_revenue
    expr: SUM(unit_price * quantity * (1 - discount))
    display_name: 'Total Revenue'
    comment: 'Net revenue after discount.'
    synonyms: ['revenue', 'sales']
  - name: unique_customers
    expr: COUNT(DISTINCT customer_id)
    display_name: 'Unique Customers'
    comment: 'Distinct customer count.'
  - name: avg_order_value
    expr: SUM(unit_price * quantity) / COUNT(DISTINCT transaction_id)
    display_name: 'Avg Order Value'
    comment: 'Average revenue per transaction.'
    synonyms: ['AOV']
  - name: high_value_revenue
    expr: SUM(unit_price * quantity) FILTER (WHERE unit_price > 100)
    display_name: 'High Value Revenue'
    comment: 'Revenue from items priced above 100.'
  - name: revenue_7d_rolling
    expr: SUM(unit_price * quantity)
    display_name: '7-Day Rolling Revenue'
    comment: 'Trailing 7-day rolling sum of gross revenue.'
    window:
      - order: transaction_date
        range: trailing 7 day
        semiadditive: last
  - name: return_rate
    expr: CAST(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*)
    display_name: 'Return Rate'
    comment: 'Fraction of transactions that were returned.'
"""

# Expected TS text, byte-exact from ts-from-databricks.md (corrected 2026-07-09)
ECOMMERCE_EXPECTED = {
    "transaction_month": "start_of_month ( [TRANSACTIONS::transaction_date] )",
    "total_revenue": "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] ) )",
    "unique_customers": "unique count ( [TRANSACTIONS::customer_id] )",
    "avg_order_value": "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) / unique count ( [TRANSACTIONS::transaction_id] )",
    "high_value_revenue": "sum_if ( [TRANSACTIONS::unit_price] > 100 , [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] )",
    "revenue_7d_rolling": "moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , -1 , [TRANSACTIONS::transaction_date] )",
    "return_rate": "sum ( if ( [TRANSACTIONS::status] = 'returned' ) then 1 else 0 ) / count ( 1 )",
}


class TestGoldenEcommerce:
    """ts-from-databricks.md — the post-PR-1 corrected worked example."""

    def _translate(self):
        parsed = parse_metric_view(ECOMMERCE_MV_YAML)
        assert parsed["unsupported"] == []
        return translate_metric_view(parsed, {"source": "TRANSACTIONS"})

    def test_every_formula_matches_recorded_text(self):
        out = self._translate()
        by_name = {e["name"]: e for e in out["translated"]}
        for name, expected in ECOMMERCE_EXPECTED.items():
            assert by_name[name]["ts_expr"] == expected, name

    def test_direct_dimensions_are_columns(self):
        out = self._translate()
        by_name = {e["name"]: e for e in out["translated"]}
        for name in ("transaction_id", "product_category", "customer_region",
                     "transaction_date"):
            assert by_name[name]["output_kind"] == "column", name

    def test_filter_golden(self):
        out = self._translate()
        assert out["filter"]["ts_expr"] == "[TRANSACTIONS::status] != 'cancelled'"

    def test_nothing_skipped_and_window_flagged(self):
        out = self._translate()
        assert out["skipped"] == []
        assert out["window_measures"] == ["revenue_7d_rolling"]
        risk = next(e for e in out["translated"]
                    if e["name"] == "revenue_7d_rolling")["annotations"]
        assert risk[0]["kind"] == "sparse_data_risk"  # BL-098 item 2


SQL_VIEW_MV_YAML = """\
version: "1.1"
source: "select * from analytics.sales.orders"
filter: "order_status = 'completed'"
dimensions:
  - name: order_id
    expr: order_id
  - name: order_date
    expr: order_date
    display_name: "Order Date"
  - name: order_status
    expr: order_status
    display_name: "Order Status"
  - name: customer_segment
    expr: "CASE WHEN total_amount > 1000 THEN 'Premium' WHEN total_amount > 100 THEN 'Standard' ELSE 'Basic' END"
    display_name: "Customer Segment"
measures:
  - name: total_orders
    expr: "COUNT(*)"
    display_name: "Total Orders"
  - name: total_amount
    expr: "SUM(total_amount)"
    display_name: "Total Amount"
  - name: avg_order_amount
    expr: "SUM(total_amount) / COUNT(DISTINCT order_id)"
    display_name: "Avg Order Amount"
"""


class TestGoldenSqlView:
    """ts-from-databricks-sql-view.md — SQL-source MV over Orders_MV_View."""

    def _translate(self):
        parsed = parse_metric_view(SQL_VIEW_MV_YAML)
        assert parsed["source"]["kind"] == "sql_query"
        assert parsed["unsupported"] == []
        return translate_metric_view(parsed, {"source": "Orders_MV_View"})

    def test_filter_translates_for_pr4_to_bake_or_formula(self):
        # The worked example bakes this filter into the SQL View's sql_query
        # (a build-model/skill decision, PR 4); translate-formulas just
        # translates it faithfully.
        out = self._translate()
        assert out["filter"]["ts_expr"] == "[Orders_MV_View::order_status] = 'completed'"

    def test_case_nested_if_golden(self):
        out = self._translate()
        seg = next(e for e in out["translated"] if e["name"] == "customer_segment")
        assert seg["ts_expr"] == (
            "if ( [Orders_MV_View::total_amount] > 1000 ) then 'Premium' "
            "else if ( [Orders_MV_View::total_amount] > 100 ) then 'Standard' else 'Basic'")

    def test_count_star_golden(self):
        out = self._translate()
        assert next(e for e in out["translated"]
                    if e["name"] == "total_orders")["ts_expr"] == "count ( 1 )"

    def test_ratio_golden(self):
        out = self._translate()
        assert next(e for e in out["translated"]
                    if e["name"] == "avg_order_amount")["ts_expr"] == (
            "sum ( [Orders_MV_View::total_amount] ) / "
            "unique count ( [Orders_MV_View::order_id] )")

    def test_simple_sum_is_column_bind(self):
        # ts-from-databricks-sql-view.md: total_amount binds directly with
        # aggregation: SUM — no formula
        out = self._translate()
        ta = next(e for e in out["translated"] if e["name"] == "total_amount")
        assert ta["output_kind"] == "column"
        assert ta["aggregation"] == "SUM"


class TestJsonPathAccess:
    """Databricks colon-path JSON access -> get_json_object pass-through.

    ThoughtSpot's sql_*_op parser rejects the colon-and-dot syntax; bracket
    notation on parse_json fails on Databricks (VARIANT is not a complex
    type), so get_json_object is the colon-free form. Verified live
    2026-07-15 (ts-databricks-formula-translation.md)."""

    def _t(self, expr):
        return translate_sql_expr(expr, make_resolver(TABLES))

    def test_nested_path(self):
        assert self._t("json_string:address.city") == (
            "sql_string_op ( \"get_json_object({0}, '$.address.city')\" , "
            "[TRANSACTIONS::json_string] )")

    def test_single_key(self):
        assert self._t("json_string:city") == (
            "sql_string_op ( \"get_json_object({0}, '$.city')\" , "
            "[TRANSACTIONS::json_string] )")

    def test_parse_json_wrapper_is_stripped(self):
        # parse_json(col):a.b and col:a.b translate identically —
        # get_json_object takes the raw string column either way.
        assert self._t("parse_json(json_string):address.city") == (
            "sql_string_op ( \"get_json_object({0}, '$.address.city')\" , "
            "[TRANSACTIONS::json_string] )")

    def test_alias_path_column(self):
        assert self._t("orders.raw_json:a.b") == (
            "sql_string_op ( \"get_json_object({0}, '$.a.b')\" , "
            "[DM_ORDER::raw_json] )")

    def test_redundant_string_cast_stripped(self):
        assert self._t("json_string:address.city::string") == (
            "sql_string_op ( \"get_json_object({0}, '$.address.city')\" , "
            "[TRANSACTIONS::json_string] )")

    def test_non_string_cast_raises(self):
        with pytest.raises(UntranslatableError, match="cast"):
            self._t("json_string:amount::int")

    def test_array_index_raises(self):
        with pytest.raises(UntranslatableError):
            self._t("json_string:items[0].sku")

    def test_computed_dimension_uses_get_json_object(self):
        dim = _dim("City", "json_string:address.city", "computed")
        out = translate_dimension(dim, TABLES)
        assert out["ts_expr"] == (
            "sql_string_op ( \"get_json_object({0}, '$.address.city')\" , "
            "[TRANSACTIONS::json_string] )")
