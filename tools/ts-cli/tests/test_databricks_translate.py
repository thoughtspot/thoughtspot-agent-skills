# tools/ts-cli/tests/test_databricks_translate.py
"""Unit tests for ts_cli/databricks/mv_translate.py (BL-063 PR3).

One class per transform. The golden classes at the bottom pin the two
post-PR-1 corrected worked examples byte-for-byte."""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import UntranslatableError
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

    def test_lod_unknown_agg_raises(self):
        with pytest.raises(UntranslatableError, match="MEDIAN"):
            translate_dimension(
                _dim("x", "MEDIAN(amt) OVER (PARTITION BY cat)", "lod_window",
                     inner_agg="MEDIAN", inner_expr="amt",
                     partition_by=["cat"]), TABLES)


class TestTranslateFilter:
    def test_filter_golden_ecommerce(self):
        out = translate_filter("status != 'cancelled'", TABLES)
        assert out == {"name": "MV Filter", "column_type": "ATTRIBUTE",
                       "ts_expr": "[TRANSACTIONS::status] != 'cancelled'"}

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

    def test_simple_unknown_agg_falls_back_to_formula_path(self):
        with pytest.raises(UntranslatableError, match="MEDIAN"):
            translate_measure(
                _measure("m", "MEDIAN(x)", "simple", agg_function="MEDIAN",
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
        assert out["ts_expr"] == ("sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) ) "
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
            DIMS, TABLES)
        assert out["ts_expr"] == ("moving_sum ( [TRANSACTIONS::LINE_TOTAL] , 1 , -1 , "
                                  "[TRANSACTIONS::order_date] )")
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["one_row_per_period"]  # the C6-verified combo — no pending

    def test_current_offset_year_at_month_grain_pending_c8(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("order_month", "current",
                                 offset={"n": -1, "unit": "year"}),
                         physical_ref="x", agg_function="SUM"),
            DIMS, TABLES)
        assert " , 12 , -12 , " in out["ts_expr"]
        kinds = [a["kind"] for a in out["annotations"]]
        assert kinds == ["one_row_per_period", "pending_verification"]
        assert "C8" in out["annotations"][1]["detail"]

    def test_current_offset_quarter_grain_pending_c8(self):
        out = translate_window_measure(
            _win_measure("m", "SUM(x)", "simple",
                         _window("order_quarter", "current",
                                 offset={"n": -3, "unit": "month"}),
                         physical_ref="x", agg_function="SUM"),
            DIMS, TABLES)
        assert " , 1 , -1 , " in out["ts_expr"]
        assert "pending_verification" in [a["kind"] for a in out["annotations"]]

    def test_offset_day_unit_skipped(self):
        with pytest.raises(UntranslatableError, match="offset unit 'day'"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("order_month", "current",
                                     offset={"n": -30, "unit": "day"}),
                             physical_ref="x", agg_function="SUM"),
                DIMS, TABLES)

    def test_offset_not_divisible_skipped(self):
        with pytest.raises(UntranslatableError, match="divide"):
            translate_window_measure(
                _win_measure("m", "SUM(x)", "simple",
                             _window("order_quarter", "current",
                                     offset={"n": -1, "unit": "month"}),
                             physical_ref="x", agg_function="SUM"),
                DIMS, TABLES)

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
            _measure("bad", "MEDIAN(x)", "simple", agg_function="MEDIAN",
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
            _parsed((), (), filter_sql="s LIKE 'a%'"), TABLES)
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


# --- ts databricks translate-formulas CLI (BL-063 PR3) -----------------

import json

from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.databricks.mv_parse import parse_metric_view

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr separated by default)
    runner = CliRunner()


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
    "return_rate": "sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) ) / count ( 1 )",
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
            "if ( [Orders_MV_View::total_amount] > 1000 , 'Premium' , "
            "if ( [Orders_MV_View::total_amount] > 100 , 'Standard' , 'Basic' ) )")

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
