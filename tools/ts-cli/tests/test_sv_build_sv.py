"""Tests for ts_cli.sv_build_sv — Model TML → SV DDL assembly.

Dialect-agnostic parsing (column index, classification, join graph, metric
ordering) is tested separately in test_tml_model_parse.py. This file covers
only Snowflake-DDL-specific emission logic.
"""
from __future__ import annotations

import json

from ts_cli.sv_build_sv import (
    aggregation_expr,
    build_ca_json,
    build_sv_ddl,
    build_synonym_clause,
    escape_comment,
    _dedupe_aliases,
)


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

    def test_column_root_description_reaches_comment(self):
        """BL-232 site 4 — a column's `description` is a SIBLING of `name`.

        `sv_build_sv.py` read `properties.description`, which real ThoughtSpot never
        emits, so no genuine Model's descriptions ever reached an SV `comment=`. It
        went unnoticed because `sv_build_model.py` wrote to that same wrong place, so
        the two cancelled on a round-trip through our own tools. No fixture carried a
        description at all, so nothing failed when one side was fixed.
        """
        model = _model_tml()
        for col in model["model"]["columns"]:
            if col["name"] == "Customer Name":
                col["description"] = "The customer display name."
        ddl, _ = build_sv_ddl(
            model_tml=model, table_tmls=_table_tmls(), sv_name="DB.S.SV")
        assert "The customer display name." in ddl

    def test_properties_description_still_read_as_fallback(self):
        """Locally generated TML predating the fix keeps working."""
        model = _model_tml()
        for col in model["model"]["columns"]:
            if col["name"] == "Customer Name":
                col["properties"]["description"] = "Legacy placement."
        ddl, _ = build_sv_ddl(
            model_tml=model, table_tmls=_table_tmls(), sv_name="DB.S.SV")
        assert "Legacy placement." in ddl

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


# ---------------------------------------------------------------------------
# Role-playing (aliased) dimensions — reverse direction (TS Model -> SV)
# ---------------------------------------------------------------------------

def _roleplay_model_tml():
    """ORDERS joins CUSTOMERS twice: the base CUSTOMERS and a BILL_TO role-play."""
    return {"model": {
        "name": "RP Model",
        "model_tables": [
            {"id": "ORDERS", "name": "ORDERS", "joins": [
                {"name": "j1", "with": "CUSTOMERS",
                 "on": "[ORDERS::Customer Id] = [CUSTOMERS::Customer Id]",
                 "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"},
                {"name": "j2", "with": "BILL_TO",
                 "on": "[ORDERS::Bill To Id] = [CUSTOMERS::Customer Id]",
                 "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"},
            ]},
            {"name": "CUSTOMERS"},
            {"name": "CUSTOMERS", "alias": "BILL_TO"},
        ],
        "columns": [
            {"name": "Customer Name", "column_id": "CUSTOMERS::Customer Name",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Bill To Name", "column_id": "BILL_TO::Customer Name",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
        "formulas": [],
    }}


def _roleplay_table_tmls():
    return {"ORDERS": {"table": {"name": "ORDERS", "db": "DB", "schema": "S",
                                 "db_table": "ORDERS", "columns": [
        {"name": "Customer Id", "db_column_name": "CUSTOMER_ID",
         "db_column_properties": {"data_type": "INT64"}},
        {"name": "Bill To Id", "db_column_name": "BILL_TO_ID",
         "db_column_properties": {"data_type": "INT64"}}]}},
        "CUSTOMERS": {"table": {"name": "CUSTOMERS", "db": "DB", "schema": "S",
                                "db_table": "CUSTOMERS", "columns": [
        {"name": "Customer Id", "db_column_name": "CUSTOMER_ID",
         "db_column_properties": {"data_type": "INT64"}},
        {"name": "Customer Name", "db_column_name": "CUSTOMER_NAME",
         "db_column_properties": {"data_type": "VARCHAR"}}]}}}


class TestBuildSvRolePlay:
    def _ddl(self):
        ddl, info = build_sv_ddl(
            model_tml=_roleplay_model_tml(),
            table_tmls=_roleplay_table_tmls(), sv_name="DB.S.RP_SV")
        return ddl, info

    def test_aliased_table_declared_with_as(self):
        ddl, _ = self._ddl()
        # role-play instance declared as `<alias> as <FQN>`
        assert "BILL_TO as DB.S.CUSTOMERS" in ddl
        # base CUSTOMERS declared bare (no alias)
        assert any(line.strip().startswith("DB.S.CUSTOMERS")
                   for line in ddl.splitlines())

    def test_primary_key_has_no_square_brackets(self):
        ddl, _ = self._ddl()
        assert "primary key (" in ddl
        assert "[primary key" not in ddl  # brackets are invalid CREATE syntax

    def test_relationships_use_logical_names_not_fqn(self):
        ddl, _ = self._ddl()
        # right side references the alias / logical name, never the FQN
        assert "references BILL_TO(" in ddl
        assert "references CUSTOMERS(" in ddl
        assert "references DB.S.CUSTOMERS(" not in ddl
        # left side is the logical table too
        assert "as ORDERS(" in ddl

    def test_roleplay_dimension_resolves_via_physical(self):
        ddl, info = self._ddl()
        # both the base and the role-play NAME column survive (not collapsed)
        assert info["dimensions"] == 2
        # role-play dimension owned by BILL_TO, physical column resolved
        assert "BILL_TO.bill_to_name as bill_to.CUSTOMER_NAME" in ddl
