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
)

TABLES = {"source": "TRANSACTIONS", "orders": "DM_ORDER",
          "orders.customers": "DM_CUSTOMER"}


def _dim(name, expr, kind, **kw):
    base = {"name": name, "expr": expr, "kind": kind, "display_name": None,
            "comment": None, "synonyms": [], "inner_agg": None,
            "inner_expr": None, "partition_by": []}
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
