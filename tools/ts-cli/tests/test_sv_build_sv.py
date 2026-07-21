"""Tests for ts_cli.sv_build_sv — Model TML → SV DDL assembly."""
from __future__ import annotations

import json
import pytest

from ts_cli.sv_build_sv import (
    aggregation_expr,
    build_ca_json,
    build_column_index,
    build_relationship_name,
    build_sv_ddl,
    build_synonym_clause,
    classify_column,
    escape_comment,
    order_metrics,
    parse_join_on,
    resolve_column_id,
    to_snake,
    _dedupe_aliases,
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
# aggregation_expr
# ---------------------------------------------------------------------------

class TestAggregationExpr:
    def test_sum(self):
        assert aggregation_expr("SUM", "orders", "AMOUNT") == "SUM(orders.AMOUNT)"

    def test_count_distinct(self):
        assert aggregation_expr("COUNT_DISTINCT", "t", "ID") == "COUNT(DISTINCT t.ID)"

    def test_default(self):
        assert aggregation_expr(None, "t", "X") == "SUM(t.X)"

    def test_avg(self):
        assert aggregation_expr("AVG", "t", "X") == "AVG(t.X)"


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
# escape_comment
# ---------------------------------------------------------------------------

class TestEscapeComment:
    def test_basic(self):
        assert escape_comment("it's a test") == "it''s a test"

    def test_no_quotes(self):
        assert escape_comment("clean") == "clean"


# ---------------------------------------------------------------------------
# build_synonym_clause
# ---------------------------------------------------------------------------

class TestBuildSynonymClause:
    def test_with_synonyms(self):
        result = build_synonym_clause("Revenue", ["Sales", "Income"])
        assert result == "with synonyms=('Revenue', 'Sales', 'Income')"

    def test_no_synonyms(self):
        assert build_synonym_clause("Revenue", []) is None

    def test_display_name_deduped(self):
        result = build_synonym_clause("Revenue", ["Revenue", "Sales"])
        assert result == "with synonyms=('Revenue', 'Sales')"

    def test_escaping(self):
        result = build_synonym_clause("It's", ["Alt"])
        assert "It''s" in result


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


# ---------------------------------------------------------------------------
# build_ca_json
# ---------------------------------------------------------------------------

class TestBuildCaJson:
    def test_basic(self):
        tables_data = {
            "orders": {
                "dimensions": ["customer_id"],
                "time_dimensions": ["order_date"],
                "metrics": ["total_amount"],
            }
        }
        result = json.loads(build_ca_json(tables_data, ["orders_to_customers"]))
        assert len(result["tables"]) == 1
        assert result["tables"][0]["name"] == "orders"
        assert result["tables"][0]["dimensions"] == [{"name": "customer_id"}]
        assert result["tables"][0]["time_dimensions"] == [{"name": "order_date"}]
        assert result["relationships"] == [{"name": "orders_to_customers"}]


# ---------------------------------------------------------------------------
# _dedupe_aliases
# ---------------------------------------------------------------------------

class TestDedupeAliases:
    def test_no_dupes(self):
        entries = [{"alias": "a"}, {"alias": "b"}]
        _dedupe_aliases(entries)
        assert entries[0]["alias"] == "a"
        assert entries[1]["alias"] == "b"

    def test_dupes(self):
        entries = [{"alias": "x"}, {"alias": "x"}, {"alias": "x"}]
        _dedupe_aliases(entries)
        assert entries[0]["alias"] == "x"
        assert entries[1]["alias"] == "x_2"
        assert entries[2]["alias"] == "x_3"


# ---------------------------------------------------------------------------
# build_sv_ddl — integration
# ---------------------------------------------------------------------------

def _model_tml():
    return {
        "model": {
            "name": "Sales Model",
            "description": "Sales analytics",
            "model_tables": [
                {
                    "id": "ORDERS", "name": "ORDERS",
                    "joins": [{
                        "name": "join_1", "with": "CUSTOMERS",
                        "on": "[ORDERS::Customer Id] = [CUSTOMERS::Customer Id]",
                        "type": "LEFT_OUTER",
                        "cardinality": "MANY_TO_ONE",
                    }],
                },
                {"id": "CUSTOMERS", "name": "CUSTOMERS"},
            ],
            "columns": [
                {"name": "Customer Id", "column_id": "ORDERS::Customer Id",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Customer Name", "column_id": "CUSTOMERS::Customer Name",
                 "properties": {"column_type": "ATTRIBUTE",
                                "synonyms": ["Client"]}},
                {"name": "Order Date", "column_id": "ORDERS::Order Date",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Total Amount", "column_id": "ORDERS::Total Amount",
                 "properties": {"column_type": "MEASURE",
                                "aggregation": "SUM"}},
            ],
            "formulas": [],
        }
    }


def _table_tmls():
    return {
        "ORDERS": {
            "table": {
                "name": "ORDERS",
                "db": "DB", "schema": "S", "db_table": "ORDERS",
                "columns": [
                    {"name": "Customer Id", "db_column_name": "CUSTOMER_ID",
                     "db_column_properties": {"data_type": "INT64"}},
                    {"name": "Order Date", "db_column_name": "ORDER_DATE",
                     "db_column_properties": {"data_type": "DATE"}},
                    {"name": "Total Amount", "db_column_name": "AMOUNT",
                     "db_column_properties": {"data_type": "DOUBLE"}},
                ],
            }
        },
        "CUSTOMERS": {
            "table": {
                "name": "CUSTOMERS",
                "db": "DB", "schema": "S", "db_table": "CUSTOMERS",
                "columns": [
                    {"name": "Customer Id", "db_column_name": "CUSTOMER_ID",
                     "db_column_properties": {"data_type": "INT64"}},
                    {"name": "Customer Name", "db_column_name": "CUSTOMER_NAME",
                     "db_column_properties": {"data_type": "VARCHAR"}},
                ],
            }
        },
    }


class TestBuildSvDdl:
    def test_basic_ddl(self):
        ddl, info = build_sv_ddl(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            sv_name="DB.S.SALES_SV")

        assert "CREATE OR REPLACE SEMANTIC VIEW DB.S.SALES_SV" in ddl
        assert "tables (" in ddl
        assert "DB.S.ORDERS" in ddl
        assert "DB.S.CUSTOMERS" in ddl
        assert "primary key (CUSTOMER_ID)" in ddl
        assert "relationships (" in ddl
        assert "orders_to_customers" in ddl
        assert "dimensions (" in ddl
        assert "metrics (" in ddl
        assert "SUM(orders.AMOUNT)" in ddl
        assert "comment=" in ddl
        assert "CA=" in ddl

    def test_counts(self):
        _, info = build_sv_ddl(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            sv_name="DB.S.SV")
        assert info["dimensions"] == 2  # customer_id, customer_name
        assert info["time_dimensions"] == 1  # order_date
        assert info["metrics"] == 1  # total_amount
        assert info["relationship_count"] == 1

    def test_dropped_join_attrs(self):
        _, info = build_sv_ddl(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            sv_name="DB.S.SV")
        assert len(info["dropped_joins"]) == 1
        assert info["dropped_joins"][0]["join_type"] == "LEFT_OUTER"

    def test_synonym_in_ddl(self):
        ddl, _ = build_sv_ddl(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            sv_name="DB.S.SV")
        assert "with synonyms=('Customer Name', 'Client')" in ddl

    def test_ca_json_valid(self):
        ddl, _ = build_sv_ddl(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            sv_name="DB.S.SV")
        ca_match = ddl.split("CA='")[1].split("')")[0]
        ca = json.loads(ca_match)
        assert "tables" in ca
        assert "relationships" in ca

    def test_no_joins(self):
        model = {
            "model": {
                "name": "Simple",
                "model_tables": [{"id": "T", "name": "T"}],
                "columns": [
                    {"name": "Id", "column_id": "T::Id",
                     "properties": {"column_type": "ATTRIBUTE"}},
                ],
                "formulas": [],
            }
        }
        tables = {
            "T": {"table": {"name": "T", "db": "DB", "schema": "S",
                             "db_table": "T",
                             "columns": [
                                 {"name": "Id", "db_column_name": "ID",
                                  "db_column_properties": {"data_type": "INT64"}},
                             ]}}
        }
        ddl, info = build_sv_ddl(
            model_tml=model, table_tmls=tables, sv_name="DB.S.SV")
        assert "relationships" not in ddl
        assert info["relationship_count"] == 0

    def test_formula_skipped(self):
        model = {
            "model": {
                "name": "M", "model_tables": [{"id": "T", "name": "T"}],
                "columns": [
                    {"name": "Calc", "formula_id": "formula_Calc",
                     "properties": {"column_type": "MEASURE"}},
                ],
                "formulas": [
                    {"id": "formula_Calc", "name": "Calc",
                     "expr": "sum(x) / count(y)"},
                ],
            }
        }
        tables = {"T": {"table": {"name": "T", "db": "DB", "schema": "S",
                                   "db_table": "T", "columns": []}}}
        _, info = build_sv_ddl(
            model_tml=model, table_tmls=tables, sv_name="DB.S.SV")
        assert len(info["skipped_formulas"]) == 1
        assert info["skipped_formulas"][0]["name"] == "Calc"

    def test_translated_formula(self):
        model = {
            "model": {
                "name": "M",
                "model_tables": [{"id": "T", "name": "T"}],
                "columns": [
                    {"name": "Revenue Per Unit",
                     "formula_id": "formula_RPU",
                     "properties": {"column_type": "MEASURE"}},
                ],
                "formulas": [
                    {"id": "formula_RPU", "name": "Revenue Per Unit",
                     "expr": "sum([ORDERS::AMOUNT]) / count([ORDERS::ID])"},
                ],
            }
        }
        tables = {"T": {"table": {"name": "T", "db": "DB", "schema": "S",
                                   "db_table": "T", "columns": []}}}
        translated = {
            "formula_RPU": {
                "expr": "DIV0(SUM(t.AMOUNT), COUNT(t.ID))",
                "kind": "metric",
            }
        }
        ddl, info = build_sv_ddl(
            model_tml=model, table_tmls=tables, sv_name="DB.S.SV",
            translated_formulas=translated)
        assert "DIV0(SUM(t.AMOUNT), COUNT(t.ID))" in ddl
        assert len(info["skipped_formulas"]) == 0
