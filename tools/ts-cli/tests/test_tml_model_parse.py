"""Tests for ts_cli.tml_model_parse — dialect-agnostic Model TML parsing.

Shared by sv_build_sv.py (→ Snowflake) and dbt_build_export.py (→ dbt) — no
Snowflake or dbt syntax belongs in this file. Snowflake-DDL-specific tests
(aggregation_expr, DDL assembly) stay in test_sv_build_sv.py.
"""
from __future__ import annotations

import pytest

from ts_cli.tml_model_parse import (
    build_column_index,
    build_relationship_name,
    classify_column,
    order_metrics,
    parse_join_on,
    resolve_column_id,
    to_snake,
    _is_date_column,
)


# ---------------------------------------------------------------------------
# to_snake
# ---------------------------------------------------------------------------

class TestToSnake:
    def test_basic(self):
        assert to_snake("Order Date") == "order_date"

    def test_special_chars(self):
        assert to_snake("# of Products") == "of_products"

    def test_leading_digit(self):
        assert to_snake("1st Quarter") == "field_1st_quarter"

    def test_empty(self):
        assert to_snake("!!!") == "field"

    def test_consecutive_underscores(self):
        assert to_snake("A  B") == "a_b"

    def test_long_name(self):
        result = to_snake("x" * 300)
        assert len(result) <= 255


# ---------------------------------------------------------------------------
# build_column_index
# ---------------------------------------------------------------------------

class TestBuildColumnIndex:
    def test_basic(self):
        table_tmls = {
            "ORDERS": {
                "table": {
                    "columns": [
                        {"name": "Order Id", "db_column_name": "ORDER_ID",
                         "db_column_properties": {"data_type": "INT64"}},
                        {"name": "Amount", "db_column_name": "AMOUNT",
                         "db_column_properties": {"data_type": "DOUBLE"}},
                    ]
                }
            }
        }
        idx = build_column_index(table_tmls)
        assert idx[("ORDERS", "Order Id")] == {
            "db_column_name": "ORDER_ID", "data_type": "INT64"}
        assert idx[("ORDERS", "Amount")] == {
            "db_column_name": "AMOUNT", "data_type": "DOUBLE"}


# ---------------------------------------------------------------------------
# resolve_column_id
# ---------------------------------------------------------------------------

class TestResolveColumnId:
    def test_basic(self):
        model_table_map = {"ORDERS": "ORDERS"}
        col_index = {
            ("ORDERS", "Amount"): {
                "db_column_name": "AMOUNT", "data_type": "DOUBLE"
            }
        }
        sv_table, db_col, dt = resolve_column_id(
            "ORDERS::Amount", model_table_map, col_index)
        assert sv_table == "ORDERS"
        assert db_col == "AMOUNT"
        assert dt == "DOUBLE"

    def test_missing_separator(self):
        with pytest.raises(ValueError, match="::"):
            resolve_column_id("ORDERS_Amount", {}, {})

    def test_unknown_table(self):
        with pytest.raises(ValueError, match="unknown table"):
            resolve_column_id("MISSING::Col", {}, {})

    def test_fallback_when_not_in_index(self):
        model_table_map = {"T": "T"}
        sv_table, db_col, dt = resolve_column_id(
            "T::UnknownCol", model_table_map, {})
        assert db_col == "UnknownCol"
        assert dt == ""


# ---------------------------------------------------------------------------
# classify_column
# ---------------------------------------------------------------------------

class TestClassifyColumn:
    def test_measure(self):
        col = {"properties": {"column_type": "MEASURE"}}
        assert classify_column(col, {}) == "metric"

    def test_attribute(self):
        col = {"name": "Region", "properties": {"column_type": "ATTRIBUTE"}}
        assert classify_column(col, {}) == "dimension"

    def test_date_by_type(self):
        col = {"name": "Created", "properties": {"column_type": "ATTRIBUTE"}}
        assert classify_column(col, {}, "DATE") == "time_dimension"

    def test_date_by_suffix(self):
        col = {"name": "sale_date", "properties": {"column_type": "ATTRIBUTE"}}
        assert classify_column(col, {}, "") == "time_dimension"

    def test_formula_measure(self):
        col = {"formula_id": "f1",
               "properties": {"column_type": "MEASURE"}}
        formulas = {"f1": {"id": "f1", "expr": "sum(x)"}}
        assert classify_column(col, formulas) == "metric"

    def test_formula_dimension(self):
        col = {"formula_id": "f1",
               "properties": {"column_type": "ATTRIBUTE"}}
        formulas = {"f1": {"id": "f1", "expr": "concat(a, b)"}}
        assert classify_column(col, formulas) == "dimension"

    def test_formula_missing(self):
        col = {"formula_id": "f_missing",
               "properties": {"column_type": "ATTRIBUTE"}}
        assert classify_column(col, {}) == "skip"


# ---------------------------------------------------------------------------
# _is_date_column
# ---------------------------------------------------------------------------

class TestIsDateColumn:
    def test_date_type(self):
        assert _is_date_column("anything", "DATE") is True

    def test_timestamp_type(self):
        assert _is_date_column("x", "TIMESTAMP_NTZ") is True

    def test_suffix(self):
        assert _is_date_column("order_date", "") is True

    def test_at_suffix(self):
        assert _is_date_column("created_at", "") is True

    def test_not_date(self):
        assert _is_date_column("region", "") is False
        assert _is_date_column("region", "VARCHAR") is False


# ---------------------------------------------------------------------------
# parse_join_on
# ---------------------------------------------------------------------------

class TestParseJoinOn:
    def test_simple(self):
        on = "[ORDERS::CUSTOMER_ID] = [CUSTOMERS::CUSTOMER_ID]"
        result = parse_join_on(on)
        assert result == [("ORDERS", "CUSTOMER_ID", "CUSTOMERS", "CUSTOMER_ID")]

    def test_multi(self):
        on = ("[A::C1] = [B::C1] and [A::C2] = [B::C2]")
        result = parse_join_on(on)
        assert len(result) == 2

    def test_no_match(self):
        assert parse_join_on("invalid") == []


# ---------------------------------------------------------------------------
# build_relationship_name
# ---------------------------------------------------------------------------

class TestBuildRelationshipName:
    def test_basic(self):
        used = set()
        assert build_relationship_name("orders", "customers", "cust_id", used) == "orders_to_customers"
        assert "orders_to_customers" in used

    def test_collision(self):
        used = {"orders_to_customers"}
        name = build_relationship_name("orders", "customers", "cust_id", used)
        assert name == "orders_cust_id_to_customers"

    def test_double_collision(self):
        used = {"a_to_b", "a_col_to_b"}
        name = build_relationship_name("a", "b", "col", used)
        assert name == "a_col_to_b_2"


# ---------------------------------------------------------------------------
# order_metrics
# ---------------------------------------------------------------------------

class TestOrderMetrics:
    def test_independent(self):
        metrics = [
            {"alias": "count_orders", "expr": "COUNT(t.ID)"},
            {"alias": "total_amount", "expr": "SUM(t.AMOUNT)"},
        ]
        result = order_metrics(metrics)
        assert [m["alias"] for m in result] == ["count_orders", "total_amount"]

    def test_dependent_after_base(self):
        metrics = [
            {"alias": "avg_per_order", "expr": "DIV0(total_amount, count_orders)"},
            {"alias": "count_orders", "expr": "COUNT(t.ID)"},
            {"alias": "total_amount", "expr": "SUM(t.AMOUNT)"},
        ]
        result = order_metrics(metrics)
        aliases = [m["alias"] for m in result]
        assert aliases.index("total_amount") < aliases.index("avg_per_order")
        assert aliases.index("count_orders") < aliases.index("avg_per_order")
