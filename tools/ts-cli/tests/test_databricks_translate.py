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

    def test_cross_measure_placeholders_prepared(self):
        out = translate_measure(
            _measure("ratio", "MEASURE(quantity) / ANY_VALUE(category_quantity)",
                     "complex_cross_measure",
                     cross_refs=["quantity"], lod_refs=["category_quantity"]),
            TABLES)
        assert out["ts_expr"] == "__MVREF_0__ / __MVREF_1__"
        assert out["inlined_refs"] == ["quantity", "category_quantity"]
