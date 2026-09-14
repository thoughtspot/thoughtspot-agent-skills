"""Tests for ts_cli.dbt_build_export — Model TML -> dbt project scaffold (Case A).

Dialect-agnostic parsing (column index, classification, join graph) is tested
separately in test_tml_model_parse.py. This file covers dbt-specific emission:
sources.yml/dbt_project.yml, staging SQL, ts_* metadata-tag schema.yml (the
primary artifact — read by the same base dbt sync `ts dbt generate-tml`
drives), and the legacy MetricFlow semantic_models.yml (secondary artifact).
"""
from __future__ import annotations

import yaml

from ts_cli.dbt_build_export import (
    _stg_name,
    build_dbt_export,
    build_dbt_project_yaml,
    build_model_tml_from_schema_yml,
    build_sources_yaml,
    extract_model_rls_from_manifest,
    extract_table_rls_from_schema_yml,
    group_tables_by_location,
    source_names_by_table,
)


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
                                "aggregation": "SUM", "format_pattern": "#,##0"}},
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


class TestBuildSourcesYaml:
    def test_basic_single_location(self):
        groups = group_tables_by_location(_table_tmls())
        doc = build_sources_yaml("warehouse", groups)
        assert doc["version"] == 2
        assert len(doc["sources"]) == 1
        src = doc["sources"][0]
        assert src["name"] == "warehouse"
        assert src["database"] == "DB"
        assert src["schema"] == "S"
        names = {t["name"] for t in src["tables"]}
        assert names == {"ORDERS", "CUSTOMERS"}
        for t in src["tables"]:
            assert set(t.keys()) == {"name"}  # no per-table database/schema key

    def test_multiple_locations_get_separate_sources(self):
        tables = _table_tmls()
        tables["OTHER"] = {"table": {"name": "OTHER", "db": "DB2", "schema": "S2",
                                      "db_table": "OTHER", "columns": []}}
        groups = group_tables_by_location(tables)
        doc = build_sources_yaml("warehouse", groups)
        assert len(doc["sources"]) == 2
        names = {s["name"] for s in doc["sources"]}
        assert names == {"warehouse_1", "warehouse_2"}

    def test_source_names_by_table_matches_sources_yaml(self):
        tables = _table_tmls()
        tables["OTHER"] = {"table": {"name": "OTHER", "db": "DB2", "schema": "S2",
                                      "db_table": "OTHER", "columns": []}}
        groups = group_tables_by_location(tables)
        by_table = source_names_by_table("warehouse", groups)
        assert by_table["ORDERS"] == by_table["CUSTOMERS"]
        assert by_table["OTHER"] != by_table["ORDERS"]


class TestBuildDbtProjectYaml:
    def test_basic(self):
        doc = build_dbt_project_yaml("sales")
        assert doc["name"] == "sales"
        assert doc["profile"] == "sales"
        assert doc["model-paths"] == ["models"]


class TestBuildDbtExport:
    def _export(self):
        # emit_semantic_models: this class asserts BOTH artifacts are written.
        return build_dbt_export(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            project_name="sales", source_name="warehouse",
            emit_semantic_models=True)

    def test_files_written(self):
        files, info = self._export()
        assert "dbt_project.yml" in files
        assert "models/staging/sources.yml" in files
        assert "models/staging/stg_orders.sql" in files
        assert "models/staging/stg_customers.sql" in files
        assert "models/schema.yml" in files
        assert "models/semantic_models.yml" in files
        assert info["files_written"] == sorted(files.keys())

    def test_staging_sql_selects_from_source(self):
        files, _ = self._export()
        assert files["models/staging/stg_orders.sql"] == (
            "select * from {{ source('warehouse', 'ORDERS') }}\n")
        assert files["models/staging/stg_customers.sql"] == (
            "select * from {{ source('warehouse', 'CUSTOMERS') }}\n")

    def test_counts(self):
        _, info = self._export()
        assert info["tables"] == 2
        # customer_id (ORDERS) + customer_name (CUSTOMERS)
        assert info["dimensions"] == 2
        assert info["time_dimensions"] == 1  # order_date
        assert info["metrics"] == 1  # total_amount
        assert info["skipped_formulas"] == []
        assert info["skipped_composite_joins"] == []
        assert info["unmapped_properties"] == []


class TestSchemaYamlTsMetaTags:
    """schema.yml — the primary artifact: plain dbt columns/tests + ts_* meta."""

    def _schema_models(self):
        files, _ = build_dbt_export(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            project_name="sales", source_name="warehouse")
        doc = yaml.safe_load(files["models/schema.yml"])
        assert doc["version"] == 2
        return {m["name"]: m for m in doc["models"]}

    def test_measure_column_gets_column_type_and_aggregation(self):
        models = self._schema_models()
        cols = {c["name"]: c for c in models["stg_orders"]["columns"]}
        meta = cols["AMOUNT"]["config"]["meta"]
        assert meta["ts_column_type"] == "measure"
        assert meta["ts_aggregation"] == "sum"
        assert meta["ts_format_pattern"] == "#,##0"

    def test_attribute_column_gets_column_type(self):
        models = self._schema_models()
        cols = {c["name"]: c for c in models["stg_orders"]["columns"]}
        assert cols["ORDER_DATE"]["config"]["meta"]["ts_column_type"] == "attribute"

    def test_synonym_becomes_ts_synonym_tag(self):
        models = self._schema_models()
        cols = {c["name"]: c for c in models["stg_customers"]["columns"]}
        assert cols["CUSTOMER_NAME"]["config"]["meta"]["ts_synonym"] == "Client"

    def test_fk_column_gets_relationships_test_with_join_meta(self):
        models = self._schema_models()
        cols = {c["name"]: c for c in models["stg_orders"]["columns"]}
        rel = cols["CUSTOMER_ID"]["data_tests"][0]["relationships"]
        assert rel["arguments"]["to"] == "ref('stg_customers')"
        assert rel["arguments"]["field"] == "CUSTOMER_ID"
        meta = rel["config"]["meta"]
        assert meta["ts_join_cardinality"] == "many_to_one"
        assert meta["ts_join_type"] == "left_outer"
        # The join's OWN ThoughtSpot name, not a derived `<left>_to_<right>`.
        # Deriving it renamed every join on each round trip; the derived form
        # is still generated for platforms with identifier rules (Snowflake
        # SV) and kept beside it as join_data["name"].
        assert meta["ts_join_name"] == "join_1"

    def test_fk_column_also_carries_its_own_meta(self):
        """Customer Id is BOTH the join's FK column AND a Model-declared
        dimension — one columns: entry must carry both data_tests: and
        config.meta:."""
        models = self._schema_models()
        cols = {c["name"]: c for c in models["stg_orders"]["columns"]}
        assert cols["CUSTOMER_ID"]["config"]["meta"]["ts_column_type"] == "attribute"
        assert "data_tests" in cols["CUSTOMER_ID"]

    def test_relationships_test_has_severity_warn(self):
        models = self._schema_models()
        cols = {c["name"]: c for c in models["stg_orders"]["columns"]}
        rel = cols["CUSTOMER_ID"]["data_tests"][0]["relationships"]
        assert rel["config"]["severity"] == "warn"

    def test_is_hidden_and_calendar_are_emitted(self):
        """Both are documented ThoughtSpot tags and are now emitted.

        Supersedes `test_is_hidden_and_calendar_never_emitted`. The earlier
        contract came from thoughtspot-model-tml.md's "do not emit when
        generating a model" guidance; that guidance is scoped to *generating* a
        model, and this exporter is the round-trip leg the same rows bless
        ("pass through on round-trips only"). See ts-convert-to-dbt
        open-items.md #9.
        """
        model = {
            "model": {"name": "M", "model_tables": [{"id": "T", "name": "T"}],
                      "columns": [
                          {"name": "Secret", "column_id": "T::Secret",
                           "properties": {"column_type": "ATTRIBUTE",
                                          "is_hidden": True, "calendar": "custom_cal"}},
                      ], "formulas": []}
        }
        tables = {"T": {"table": {"name": "T", "db": "DB", "schema": "S", "db_table": "T",
                                   "columns": [{"name": "Secret", "db_column_name": "SECRET"}]}}}
        files, info = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        col = doc["models"][0]["columns"][0]
        meta = col.get("config", {}).get("meta", {})
        assert meta["ts_hidden"] == "yes"
        assert meta["ts_calendar_type"] == "custom_cal"
        props = {u["property"] for u in info["unmapped_properties"]}
        assert "is_hidden" not in props
        assert "calendar" not in props


class TestSemanticModelsYamlLegacySpec:
    """semantic_models.yml — the secondary, legacy-spec MetricFlow artifact."""

    def _doc(self):
        # The whole class is about this artifact's shape, so it opts in.
        files, _ = build_dbt_export(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            project_name="sales", source_name="warehouse",
            emit_semantic_models=True)
        return yaml.safe_load(files["models/semantic_models.yml"])

    def test_top_level_shape_is_legacy_spec(self):
        doc = self._doc()
        assert "semantic_models" in doc
        assert "metrics" in doc
        # legacy spec: metrics is a top-level sibling list, not nested under a model
        assert isinstance(doc["metrics"], list)

    def test_entities_use_flat_top_level_list(self):
        doc = self._doc()
        by_name = {m["name"]: m for m in doc["semantic_models"]}
        orders_entities = {e["name"]: e for e in by_name["stg_orders"]["entities"]}
        assert orders_entities["customers"]["type"] == "foreign"
        assert orders_entities["customers"]["expr"] == "CUSTOMER_ID"
        customers_entities = {e["name"]: e for e in by_name["stg_customers"]["entities"]}
        assert customers_entities["customers"]["type"] == "primary"

    def test_measure_and_metric_reference_by_name(self):
        doc = self._doc()
        by_name = {m["name"]: m for m in doc["semantic_models"]}
        measure = by_name["stg_orders"]["measures"][0]
        assert measure["name"] == "total_amount"
        assert measure["agg"] == "sum"
        assert measure["expr"] == "AMOUNT"
        metric = doc["metrics"][0]
        assert metric["type"] == "simple"
        assert metric["type_params"]["measure"] == "total_amount"

    def test_time_dimension_has_granularity(self):
        doc = self._doc()
        by_name = {m["name"]: m for m in doc["semantic_models"]}
        dims = {d["name"]: d for d in by_name["stg_orders"]["dimensions"]}
        assert dims["order_date"]["type"] == "time"
        assert dims["order_date"]["type_params"]["time_granularity"] == "day"


class TestFormulaColumnsInSchemaYml:
    """Formula columns with a resolvable table reference are emitted as ts_formula
    in schema.yml under the dbt model that owns the first-referenced table.
    This is the two-way sync mechanism: ThoughtSpot → schema.yml → dbt manifest
    → ThoughtSpot (via build-model on resync).
    """

    def _model_with_formula(self, expr: str, col_type: str = "MEASURE",
                             aggregation: str = "SUM",
                             synonyms: "list[str] | None" = None) -> dict:
        props: dict = {"column_type": col_type}
        if col_type == "MEASURE":
            props["aggregation"] = aggregation
        if synonyms:
            props["synonyms"] = synonyms
        return {
            "model": {
                "name": "Sales Model",
                "model_tables": [
                    {"id": "ORDERS", "name": "ORDERS"},
                    {"id": "CUSTOMERS", "name": "CUSTOMERS",
                     "joins": [{"name": "j", "with": "ORDERS",
                                "on": "[CUSTOMERS::id] = [ORDERS::customer_id]",
                                "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]},
                ],
                "columns": [
                    {"name": "ORDER_ID", "column_id": "ORDERS::ORDER_ID"},
                    {"name": "AMOUNT", "column_id": "ORDERS::AMOUNT",
                     "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                    {"name": "Rev Formula", "formula_id": "formula_Rev_Formula",
                     "properties": props},
                ],
                "formulas": [
                    {"id": "formula_Rev_Formula", "name": "Rev Formula", "expr": expr},
                ],
            }
        }

    def _tables(self):
        return {
            "ORDERS": {"table": {"name": "ORDERS", "db": "DB", "schema": "S",
                                  "db_table": "ORDERS",
                                  "columns": [
                                      {"name": "ORDER_ID", "db_column_name": "ORDER_ID",
                                       "type": "INT64"},
                                      {"name": "AMOUNT", "db_column_name": "AMOUNT",
                                       "type": "DOUBLE"},
                                      {"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID",
                                       "type": "INT64"},
                                  ]}},
            "CUSTOMERS": {"table": {"name": "CUSTOMERS", "db": "DB", "schema": "S",
                                     "db_table": "CUSTOMERS",
                                     "columns": [
                                         {"name": "ID", "db_column_name": "ID",
                                          "type": "INT64"},
                                     ]}},
        }

    def test_formula_with_table_ref_emitted_in_schema_yml(self):
        model = self._model_with_formula("sum([ORDERS::AMOUNT])")
        files, info = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        assert info["formula_columns"] == 1
        assert info["skipped_formulas"] == []
        doc = yaml.safe_load(files["models/schema.yml"])
        models = {m["name"]: m for m in doc["models"]}
        cols = {c["name"]: c for c in models["stg_orders"]["columns"]}
        assert "Rev Formula" in cols
        meta = cols["Rev Formula"]["config"]["meta"]
        assert meta["ts_formula"] == "sum([ORDERS::AMOUNT])"
        assert meta["ts_column_type"] == "measure"
        assert meta["ts_aggregation"] == "sum"

    def test_formula_placed_under_first_referenced_table(self):
        # Formula references CUSTOMERS first — should appear under stg_customers
        model = self._model_with_formula(
            "count_distinct([CUSTOMERS::ID])", col_type="MEASURE", aggregation="COUNT_DISTINCT")
        files, info = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        assert info["formula_columns"] == 1
        doc = yaml.safe_load(files["models/schema.yml"])
        models = {m["name"]: m for m in doc["models"]}
        assert "Rev Formula" in {c["name"] for c in models["stg_customers"]["columns"]}
        assert all("Rev Formula" != c["name"]
                   for c in models.get("stg_orders", {}).get("columns", []))

    def test_formula_with_no_table_ref_goes_to_skipped(self):
        model = self._model_with_formula("sum(x) / count(y)")  # no [TABLE::COL] syntax
        _, info = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        assert info["formula_columns"] == 0
        assert len(info["skipped_formulas"]) == 1
        assert info["skipped_formulas"][0]["name"] == "Rev Formula"

    def test_formula_attribute_gets_attribute_column_type(self):
        model = self._model_with_formula(
            "concat([ORDERS::ORDER_ID], '-suffix')", col_type="ATTRIBUTE")
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c
                for m in doc["models"] for c in m["columns"]}
        assert cols["Rev Formula"]["config"]["meta"]["ts_column_type"] == "attribute"
        assert "ts_aggregation" not in cols["Rev Formula"]["config"]["meta"]

    def test_formula_synonyms_preserved(self):
        model = self._model_with_formula(
            "sum([ORDERS::AMOUNT])", synonyms=["Revenue", "Sales"])
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c
                for m in doc["models"] for c in m["columns"]}
        assert cols["Rev Formula"]["config"]["meta"]["ts_synonym"] == "Revenue, Sales"


class TestFormulaColumnsSkipped:
    def test_formula_column_reported_not_translated(self):
        model = {
            "model": {
                "name": "M", "model_tables": [{"id": "T", "name": "T"}],
                "columns": [
                    {"name": "Calc", "formula_id": "formula_Calc",
                     "properties": {"column_type": "MEASURE"}},
                ],
                "formulas": [
                    {"id": "formula_Calc", "name": "Calc", "expr": "sum(x) / count(y)"},
                ],
            }
        }
        tables = {"T": {"table": {"name": "T", "db": "DB", "schema": "S",
                                   "db_table": "T", "columns": []}}}
        files, info = build_dbt_export(
            model_tml=model, table_tmls=tables,
            project_name="p", source_name="src")
        assert len(info["skipped_formulas"]) == 1
        assert info["skipped_formulas"][0]["name"] == "Calc"
        assert "models/schema.yml" not in files
        assert "models/semantic_models.yml" not in files


class TestRolePlay:
    def _model_tml(self):
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

    def _table_tmls(self):
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

    def test_alias_gets_thin_passthrough_model(self):
        files, info = build_dbt_export(
            model_tml=self._model_tml(), table_tmls=self._table_tmls(),
            project_name="p", source_name="src")
        assert files["models/marts/dim_bill_to.sql"] == (
            "select * from {{ ref('stg_customers') }}\n")
        assert "models/staging/stg_customers.sql" in files
        assert list(files.keys()).count("models/staging/stg_customers.sql") == 1

    def test_alias_and_base_get_distinct_entries_in_both_artifacts(self):
        files, _ = build_dbt_export(
            model_tml=self._model_tml(), table_tmls=self._table_tmls(),
            project_name="p", source_name="src", emit_semantic_models=True)
        schema_doc = yaml.safe_load(files["models/schema.yml"])
        schema_names = {m["name"] for m in schema_doc["models"]}
        # stg_orders gets its own schema.yml entry too — it has two FK
        # relationships tests (to CUSTOMERS and to BILL_TO)
        assert schema_names == {"stg_orders", "stg_customers", "dim_bill_to"}

        semantic_doc = yaml.safe_load(files["models/semantic_models.yml"])
        semantic_names = {m["name"] for m in semantic_doc["semantic_models"]}
        assert semantic_names == {"stg_orders", "stg_customers", "dim_bill_to"}

    def test_alias_entity_name_distinct_from_base(self):
        files, _ = build_dbt_export(
            model_tml=self._model_tml(), table_tmls=self._table_tmls(),
            project_name="p", source_name="src", emit_semantic_models=True)
        doc = yaml.safe_load(files["models/semantic_models.yml"])
        by_name = {m["name"]: m for m in doc["semantic_models"]}
        bill_to_entities = {e["name"]: e for e in by_name["dim_bill_to"]["entities"]}
        assert "bill_to" in bill_to_entities
        customers_entities = {e["name"]: e for e in by_name["stg_customers"]["entities"]}
        assert "customers" in customers_entities

    def test_orders_relationships_tests_reference_correct_models(self):
        files, _ = build_dbt_export(
            model_tml=self._model_tml(), table_tmls=self._table_tmls(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        by_name = {m["name"]: m for m in doc["models"]}
        orders_cols = {c["name"]: c for c in by_name["stg_orders"]["columns"]}
        assert orders_cols["CUSTOMER_ID"]["data_tests"][0]["relationships"]["arguments"]["to"] == (
            "ref('stg_customers')")
        assert orders_cols["BILL_TO_ID"]["data_tests"][0]["relationships"]["arguments"]["to"] == (
            "ref('dim_bill_to')")


class TestCompositeJoin:
    def test_composite_join_skipped_in_both_artifacts(self):
        model = {"model": {
            "name": "M",
            "model_tables": [
                {"id": "A", "name": "A", "joins": [{
                    "name": "j", "with": "B",
                    "on": "[A::C1] = [B::C1] and [A::C2] = [B::C2]",
                    "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"id": "B", "name": "B"},
            ],
            "columns": [], "formulas": [],
        }}
        tables = {
            "A": {"table": {"name": "A", "db": "DB", "schema": "S", "db_table": "A",
                             "columns": [
                                 {"name": "C1", "db_column_name": "C1"},
                                 {"name": "C2", "db_column_name": "C2"}]}},
            "B": {"table": {"name": "B", "db": "DB", "schema": "S", "db_table": "B",
                             "columns": [
                                 {"name": "C1", "db_column_name": "C1"},
                                 {"name": "C2", "db_column_name": "C2"}]}},
        }
        files, info = build_dbt_export(
            model_tml=model, table_tmls=tables,
            project_name="p", source_name="src")
        assert len(info["skipped_composite_joins"]) == 1
        assert "models/schema.yml" not in files
        assert "models/semantic_models.yml" not in files


class TestUnmappedJoinValues:
    def test_unrecognized_cardinality_reported_not_mis_emitted(self):
        model = {"model": {
            "name": "M",
            "model_tables": [
                {"id": "A", "name": "A", "joins": [{
                    "name": "j", "with": "B",
                    "on": "[A::C1] = [B::C1]",
                    "type": "INNER", "cardinality": "MANY_TO_MANY"}]},
                {"id": "B", "name": "B"},
            ],
            "columns": [], "formulas": [],
        }}
        tables = {
            "A": {"table": {"name": "A", "db": "DB", "schema": "S", "db_table": "A",
                             "columns": [{"name": "C1", "db_column_name": "C1"}]}},
            "B": {"table": {"name": "B", "db": "DB", "schema": "S", "db_table": "B",
                             "columns": [{"name": "C1", "db_column_name": "C1"}]}},
        }
        files, info = build_dbt_export(
            model_tml=model, table_tmls=tables,
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        a_cols = {c["name"]: c for c in doc["models"][0]["columns"]}
        meta = a_cols["C1"]["data_tests"][0]["relationships"]["config"]["meta"]
        assert "ts_join_cardinality" not in meta
        assert meta["ts_join_type"] == "inner"
        props = {u["property"] for u in info["unmapped_properties"]}
        assert "join_cardinality" in props


# ---------------------------------------------------------------------------
# build_model_tml_from_schema_yml
# ---------------------------------------------------------------------------

_STAR_SCHEMA_YML = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: ORDER_ID
        config:
          meta:
            ts_column_type: attribute
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
        data_tests:
          - relationships:
              arguments:
                to: ref('stg_customers')
                field: CUSTOMER_ID
              config:
                meta:
                  ts_join_name: orders_to_customers
                  ts_join_cardinality: many_to_one
                  ts_join_type: left_outer
      - name: AMOUNT
        config:
          meta:
            ts_column_type: measure
            ts_aggregation: sum
            ts_synonym: "Revenue, Sales"
  - name: stg_customers
    columns:
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
      - name: CUSTOMER_NAME
        config:
          meta:
            ts_column_type: attribute
"""


class TestBuildModelTmlFromSchemaYml:
    def test_basic_structure(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        assert "model" in tml
        m = tml["model"]
        assert m["name"] == "MY_MODEL"
        assert "model_tables" in m
        assert "columns" in m

    def test_fact_table_listed_first_with_joins(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        tables = tml["model"]["model_tables"]
        names = [t["name"] for t in tables]
        assert names[0] == "STG_ORDERS"  # has joins → listed first
        assert "STG_CUSTOMERS" in names

    def test_join_assembled_correctly(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        orders_entry = next(t for t in tml["model"]["model_tables"] if t["name"] == "STG_ORDERS")
        assert "joins" in orders_entry
        j = orders_entry["joins"][0]
        assert j["name"] == "orders_to_customers"
        assert j["with"] == "STG_CUSTOMERS"
        assert j["type"] == "LEFT_OUTER"
        assert j["cardinality"] == "MANY_TO_ONE"
        assert j["on"] == "[STG_ORDERS::CUSTOMER_ID] = [STG_CUSTOMERS::CUSTOMER_ID]"

    def test_dimension_table_has_no_joins(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        customers_entry = next(t for t in tml["model"]["model_tables"] if t["name"] == "STG_CUSTOMERS")
        assert "joins" not in customers_entry

    def test_column_types_and_aggregation(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        cols = {c["column_id"]: c for c in tml["model"]["columns"]}
        assert cols["STG_ORDERS::ORDER_ID"]["properties"]["column_type"] == "ATTRIBUTE"
        amount = cols["STG_ORDERS::AMOUNT"]["properties"]
        assert amount["column_type"] == "MEASURE"
        assert amount["aggregation"] == "SUM"

    def test_synonyms_parsed_from_comma_separated_string(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        cols = {c["column_id"]: c for c in tml["model"]["columns"]}
        assert cols["STG_ORDERS::AMOUNT"]["properties"]["synonyms"] == ["Revenue", "Sales"]

    def test_column_id_format(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        for col in tml["model"]["columns"]:
            assert "::" in col["column_id"]
            table, _, col_name = col["column_id"].partition("::")
            assert table == table.upper()
            # name is either the raw col_name (unique) or TABLE_NAME_col_name (disambiguated)
            assert col["name"] == col_name or col["name"] == f"{table}_{col_name}"

    def test_multifact_both_fact_tables_get_joins(self):
        """Two independent fact tables each with a join to the same dimension."""
        yml = """
version: 2
models:
  - name: stg_appointments
    columns:
      - name: CUSTOMER_ID
        data_tests:
          - relationships:
              arguments:
                to: ref('stg_customers')
                field: CUSTOMER_ID
              config:
                meta:
                  ts_join_name: appts_to_customers
                  ts_join_cardinality: many_to_one
                  ts_join_type: left_outer
  - name: stg_sales
    columns:
      - name: CUSTOMER_ID
        data_tests:
          - relationships:
              arguments:
                to: ref('stg_customers')
                field: CUSTOMER_ID
              config:
                meta:
                  ts_join_name: sales_to_customers
                  ts_join_cardinality: many_to_one
                  ts_join_type: left_outer
  - name: stg_customers
    columns:
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
"""
        tml = build_model_tml_from_schema_yml(yml, "MULTI_FACT_MODEL")
        tables = {t["name"]: t for t in tml["model"]["model_tables"]}
        assert "STG_APPOINTMENTS" in tables
        assert "STG_SALES" in tables
        assert "STG_CUSTOMERS" in tables
        assert "joins" in tables["STG_APPOINTMENTS"]
        assert "joins" in tables["STG_SALES"]
        assert "joins" not in tables["STG_CUSTOMERS"]
        assert tables["STG_APPOINTMENTS"]["joins"][0]["name"] == "appts_to_customers"
        assert tables["STG_SALES"]["joins"][0]["name"] == "sales_to_customers"

    def test_missing_ts_join_name_generates_default(self):
        yml = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: CUST_ID
        data_tests:
          - relationships:
              arguments:
                to: ref('stg_customers')
                field: CUST_ID
              config:
                meta:
                  ts_join_cardinality: many_to_one
  - name: stg_customers
    columns: []
"""
        tml = build_model_tml_from_schema_yml(yml, "M")
        orders = next(t for t in tml["model"]["model_tables"] if t["name"] == "STG_ORDERS")
        assert orders["joins"][0]["name"]  # non-empty default name

    def test_columns_without_meta_are_excluded(self):
        yml = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: RAW_COL
"""
        tml = build_model_tml_from_schema_yml(yml, "M")
        assert tml["model"]["columns"] == []

    def test_no_guid_in_output(self):
        tml = build_model_tml_from_schema_yml(_STAR_SCHEMA_YML, "MY_MODEL")
        assert "guid" not in tml
        assert "guid" not in tml["model"]


class TestStgNameNoPrefixDoubling:
    """_stg_name must not produce stg_stg_* for tables already named STG_*."""

    def test_stg_prefix_tables_kept_as_is(self):
        assert _stg_name("STG_APPOINTMENTS") == "stg_appointments"
        assert _stg_name("STG_BARBERS") == "stg_barbers"
        assert _stg_name("stg_orders") == "stg_orders"

    def test_non_prefixed_tables_get_stg_prefix(self):
        assert _stg_name("APPOINTMENTS") == "stg_appointments"
        assert _stg_name("ORDERS") == "stg_orders"

    def test_build_dbt_export_no_double_prefix(self):
        model_tml = {"model": {
            "name": "M",
            "model_tables": [{"name": "STG_ORDERS"}],
            "columns": [{"name": "ID", "column_id": "STG_ORDERS::ID",
                         "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": [],
        }}
        table_tmls = {"STG_ORDERS": {"table": {
            "name": "STG_ORDERS", "db": "DB", "schema": "S", "db_table": "STG_ORDERS",
            "connection": {"name": "conn"},
            "columns": [{"name": "ID", "db_column_name": "ID",
                         "properties": {"column_type": "ATTRIBUTE"},
                         "db_column_properties": {"data_type": "VARCHAR"}}],
        }}}
        _, info = build_dbt_export(
            model_tml=model_tml, table_tmls=table_tmls,
            project_name="proj", source_name="src",
        )
        sql_files = [f for f in info["files_written"] if f.endswith(".sql")]
        assert sql_files == ["models/staging/stg_orders.sql"]


# ---------------------------------------------------------------------------
# Data-loss preservation tests (BL-xxx round-trip)
# ---------------------------------------------------------------------------

class TestFormulaDescriptionAndIndexTypeEmit:
    """Formula columns must emit description: and ts_index_type in schema.yml."""

    def _model_with_formula(self, *, description=None, index_type=None):
        props: dict = {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT"}
        if index_type:
            props["index_type"] = index_type
        col: dict = {"name": "Appt Count", "formula_id": "formula_Appt_Count",
                     "properties": props}
        if description:
            col["description"] = description
        return {
            "model": {
                "name": "M",
                "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
                "columns": [col],
                "formulas": [
                    {"id": "formula_Appt_Count", "name": "Appt Count",
                     "expr": "unique count ( [ORDERS::ID] ) "},
                ],
            }
        }

    def _tables(self):
        return {"ORDERS": {"table": {"name": "ORDERS", "db": "DB", "schema": "S",
                                     "db_table": "ORDERS",
                                     "columns": [{"name": "ID", "db_column_name": "ID",
                                                  "type": "INT64"}]}}}

    def test_formula_description_emitted_in_schema_yml(self):
        model = self._model_with_formula(description="appointment made by the client")
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c for m in doc["models"] for c in m["columns"]}
        assert cols["Appt Count"].get("description") == "appointment made by the client"

    def test_formula_index_type_dont_index_emitted(self):
        model = self._model_with_formula(index_type="DONT_INDEX")
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c for m in doc["models"] for c in m["columns"]}
        assert cols["Appt Count"]["config"]["meta"]["ts_index_type"] == "dont_index"

    def test_formula_index_type_default_emitted(self):
        model = self._model_with_formula(index_type="DEFAULT")
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c for m in doc["models"] for c in m["columns"]}
        assert cols["Appt Count"]["config"]["meta"]["ts_index_type"] == "default"

    def test_formula_no_index_type_not_emitted(self):
        model = self._model_with_formula()
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c for m in doc["models"] for c in m["columns"]}
        assert "ts_index_type" not in cols["Appt Count"]["config"]["meta"]


class TestDescriptionAndIndexTypeReadBack:
    """build_model_tml_from_schema_yml must restore description and index_type."""

    _WITH_DESC_AND_INDEX_YML = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: APPOINTMENT_ID
        description: appointment made by the client
        config:
          meta:
            ts_column_type: attribute
            ts_index_type: dont_index
      - name: Number of appointments
        description: count of unique appointments
        config:
          meta:
            ts_formula: 'unique count ( [STG_ORDERS::APPOINTMENT_ID] ) '
            ts_column_type: measure
            ts_aggregation: sum
            ts_index_type: dont_index
"""

    def test_regular_column_description_restored(self):
        tml = build_model_tml_from_schema_yml(self._WITH_DESC_AND_INDEX_YML, "M")
        cols = {c["column_id"]: c for c in tml["model"]["columns"]
                if "column_id" in c}
        appt = cols["STG_ORDERS::APPOINTMENT_ID"]
        assert appt.get("description") == "appointment made by the client"

    def test_regular_column_index_type_restored(self):
        tml = build_model_tml_from_schema_yml(self._WITH_DESC_AND_INDEX_YML, "M")
        cols = {c["column_id"]: c for c in tml["model"]["columns"]
                if "column_id" in c}
        assert cols["STG_ORDERS::APPOINTMENT_ID"]["properties"]["index_type"] == "DONT_INDEX"

    def test_formula_column_description_restored(self):
        tml = build_model_tml_from_schema_yml(self._WITH_DESC_AND_INDEX_YML, "M")
        formula_cols = [c for c in tml["model"]["columns"] if "formula_id" in c]
        assert len(formula_cols) == 1
        assert formula_cols[0].get("description") == "count of unique appointments"

    def test_formula_column_index_type_restored(self):
        tml = build_model_tml_from_schema_yml(self._WITH_DESC_AND_INDEX_YML, "M")
        formula_cols = [c for c in tml["model"]["columns"] if "formula_id" in c]
        assert formula_cols[0]["properties"]["index_type"] == "DONT_INDEX"

    def test_column_without_description_has_no_description_key(self):
        yml = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: AMOUNT
        config:
          meta:
            ts_column_type: measure
            ts_aggregation: sum
"""
        tml = build_model_tml_from_schema_yml(yml, "M")
        cols = {c["column_id"]: c for c in tml["model"]["columns"]
                if "column_id" in c}
        assert "description" not in cols["STG_ORDERS::AMOUNT"]


# ---------------------------------------------------------------------------
# RLS round-trip
# ---------------------------------------------------------------------------

_STG_BARBERS_RLS = {
    "tables": [{"name": "STG_BARBERS"}],
    "table_paths": [{"id": "STG_BARBERS_1", "table": "STG_BARBERS", "column": ["FIRST_NAME"]}],
    "rules": [{"name": "rls rule", "expr": "ts_username = [STG_BARBERS_1::FIRST_NAME] "}],
}


def _model_with_rls():
    return {
        "model": {
            "name": "M",
            "model_tables": [{"id": "STG_BARBERS", "name": "STG_BARBERS"}],
            "columns": [
                {"name": "FIRST_NAME", "column_id": "STG_BARBERS::FIRST_NAME",
                 "properties": {"column_type": "ATTRIBUTE"}},
            ],
            "formulas": [],
        }
    }


def _table_with_rls():
    return {
        "STG_BARBERS": {"table": {
            "name": "STG_BARBERS", "db": "DB", "schema": "S", "db_table": "STG_BARBERS",
            "columns": [{"name": "FIRST_NAME", "db_column_name": "FIRST_NAME",
                         "db_column_properties": {"data_type": "VARCHAR"}}],
            "rls_rules": _STG_BARBERS_RLS,
        }}
    }


class TestRlsEmitInSchemaYml:
    """RLS rules from Table TML must appear as ts_rls_rules in schema.yml."""

    def test_rls_emitted_at_model_level(self):
        files, _ = build_dbt_export(
            model_tml=_model_with_rls(), table_tmls=_table_with_rls(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        models = {m["name"]: m for m in doc["models"]}
        model = models["stg_stg_barbers"] if "stg_stg_barbers" in models else models["stg_barbers"]
        assert "ts_rls_rules" in model.get("config", {}).get("meta", {})

    def test_rls_rule_name_and_expr_preserved(self):
        files, _ = build_dbt_export(
            model_tml=_model_with_rls(), table_tmls=_table_with_rls(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        models = {m["name"]: m for m in doc["models"]}
        stg_name = next(k for k in models if "barbers" in k)
        rls_rules = models[stg_name]["config"]["meta"]["ts_rls_rules"]
        assert len(rls_rules) == 1
        assert rls_rules[0]["name"] == "rls rule"
        assert rls_rules[0]["expr"] == "ts_username = [STG_BARBERS_1::FIRST_NAME] "

    def test_rls_table_path_preserved(self):
        files, _ = build_dbt_export(
            model_tml=_model_with_rls(), table_tmls=_table_with_rls(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        models = {m["name"]: m for m in doc["models"]}
        stg_name = next(k for k in models if "barbers" in k)
        tp = models[stg_name]["config"]["meta"]["ts_rls_rules"][0]["table_paths"][0]
        assert tp["id"] == "STG_BARBERS_1"
        assert tp["table"] == "STG_BARBERS"
        assert tp["columns"] == ["FIRST_NAME"]

    def test_table_without_rls_has_no_ts_rls_rules(self):
        model = {
            "model": {
                "name": "M",
                "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
                "columns": [{"name": "ID", "column_id": "ORDERS::ID",
                             "properties": {"column_type": "ATTRIBUTE"}}],
                "formulas": [],
            }
        }
        tables = {"ORDERS": {"table": {
            "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
            "columns": [{"name": "ID", "db_column_name": "ID",
                         "db_column_properties": {"data_type": "INT64"}}],
        }}}
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        for m in doc["models"]:
            meta = (m.get("config") or {}).get("meta") or {}
            assert "ts_rls_rules" not in meta


class TestExtractTableRlsFromSchemaYml:
    """extract_table_rls_from_schema_yml must reconstruct a valid Table TML rls_rules block."""

    _SCHEMA_WITH_RLS = """
version: 2
models:
  - name: stg_barbers
    config:
      meta:
        ts_rls_rules:
          - name: rls rule
            expr: 'ts_username = [STG_BARBERS_1::FIRST_NAME] '
            table_paths:
              - id: STG_BARBERS_1
                table: STG_BARBERS
                columns:
                  - FIRST_NAME
    columns:
      - name: FIRST_NAME
        config:
          meta:
            ts_column_type: attribute
"""

    def test_returns_rls_block_for_table(self):
        result = extract_table_rls_from_schema_yml(self._SCHEMA_WITH_RLS)
        assert "STG_BARBERS" in result

    def test_tables_derived_from_table_paths(self):
        result = extract_table_rls_from_schema_yml(self._SCHEMA_WITH_RLS)
        assert result["STG_BARBERS"]["tables"] == [{"name": "STG_BARBERS"}]

    def test_table_paths_match_tml_shape(self):
        result = extract_table_rls_from_schema_yml(self._SCHEMA_WITH_RLS)
        tp = result["STG_BARBERS"]["table_paths"][0]
        assert tp == {"id": "STG_BARBERS_1", "table": "STG_BARBERS", "column": ["FIRST_NAME"]}

    def test_rule_name_and_expr_restored(self):
        result = extract_table_rls_from_schema_yml(self._SCHEMA_WITH_RLS)
        rule = result["STG_BARBERS"]["rules"][0]
        assert rule["name"] == "rls rule"
        assert rule["expr"] == "ts_username = [STG_BARBERS_1::FIRST_NAME] "

    def test_model_without_rls_not_in_result(self):
        yml = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: ID
        config:
          meta:
            ts_column_type: attribute
"""
        result = extract_table_rls_from_schema_yml(yml)
        assert result == {}


# ---------------------------------------------------------------------------
# extract_model_rls_from_manifest
# ---------------------------------------------------------------------------

class TestExtractModelRlsFromManifest:
    """extract_model_rls_from_manifest must return Table TML rls_rules blocks
    from dbt manifest model nodes — the manifest-reading counterpart to
    extract_table_rls_from_schema_yml."""

    _MANIFEST = {
        "nodes": {
            "model.proj.stg_barbers": {
                "resource_type": "model",
                "name": "stg_barbers",
                "original_file_path": "models/staging/barbershop/stg_barbers.sql",
                "config": {
                    "meta": {
                        "ts_rls_rules": [
                            {
                                "name": "rls rule",
                                "expr": "ts_username = [STG_BARBERS_1::FIRST_NAME] ",
                                "table_paths": [
                                    {
                                        "id": "STG_BARBERS_1",
                                        "table": "STG_BARBERS",
                                        "columns": ["FIRST_NAME"],
                                    }
                                ],
                            }
                        ]
                    }
                },
                "columns": {},
            },
            "model.proj.stg_appointments": {
                "resource_type": "model",
                "name": "stg_appointments",
                "original_file_path": "models/staging/barbershop/stg_appointments.sql",
                "config": {"meta": {}},
                "columns": {},
            },
        }
    }
    _MODEL_PATH = "models/staging/barbershop"

    def test_returns_rls_block_for_table_with_rls(self):
        result = extract_model_rls_from_manifest(self._MANIFEST, self._MODEL_PATH)
        assert "STG_BARBERS" in result

    def test_table_without_rls_not_in_result(self):
        result = extract_model_rls_from_manifest(self._MANIFEST, self._MODEL_PATH)
        assert "STG_APPOINTMENTS" not in result

    def test_tables_derived_from_table_paths(self):
        result = extract_model_rls_from_manifest(self._MANIFEST, self._MODEL_PATH)
        assert result["STG_BARBERS"]["tables"] == [{"name": "STG_BARBERS"}]

    def test_table_paths_match_tml_shape(self):
        result = extract_model_rls_from_manifest(self._MANIFEST, self._MODEL_PATH)
        tp = result["STG_BARBERS"]["table_paths"][0]
        assert tp == {"id": "STG_BARBERS_1", "table": "STG_BARBERS", "column": ["FIRST_NAME"]}

    def test_rule_name_and_expr(self):
        result = extract_model_rls_from_manifest(self._MANIFEST, self._MODEL_PATH)
        rule = result["STG_BARBERS"]["rules"][0]
        assert rule["name"] == "rls rule"
        assert rule["expr"] == "ts_username = [STG_BARBERS_1::FIRST_NAME] "

    def test_nodes_outside_model_path_excluded(self):
        manifest = {
            "nodes": {
                "model.proj.other": {
                    "resource_type": "model",
                    "name": "other",
                    "original_file_path": "models/marts/other.sql",
                    "config": {"meta": {"ts_rls_rules": [{"name": "r", "expr": "x", "table_paths": []}]}},
                    "columns": {},
                }
            }
        }
        result = extract_model_rls_from_manifest(manifest, self._MODEL_PATH)
        assert result == {}

    def test_empty_manifest(self):
        assert extract_model_rls_from_manifest({}, self._MODEL_PATH) == {}


# ---------------------------------------------------------------------------
# ai_context round-trip
# ---------------------------------------------------------------------------

class TestAiContextEmitAndReadBack:
    """ai_context in properties must round-trip through schema.yml as ts_ai_context."""

    def _model_with_ai_context(self):
        return {
            "model": {
                "name": "M",
                "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
                "columns": [
                    {"name": "APPOINTMENT_ID", "column_id": "ORDERS::APPOINTMENT_ID",
                     "properties": {"column_type": "ATTRIBUTE",
                                    "ai_context": "these are appointments made by the client"}},
                ],
                "formulas": [],
            }
        }

    def _tables(self):
        return {"ORDERS": {"table": {
            "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
            "columns": [{"name": "APPOINTMENT_ID", "db_column_name": "APPOINTMENT_ID",
                         "db_column_properties": {"data_type": "VARCHAR"}}],
        }}}

    def _formula_model_with_ai_context(self):
        return {
            "model": {
                "name": "M",
                "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
                "columns": [
                    {"name": "Appt Count", "formula_id": "formula_Appt_Count",
                     "properties": {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT",
                                    "ai_context": "count of unique appointment IDs"}},
                ],
                "formulas": [
                    {"id": "formula_Appt_Count", "name": "Appt Count",
                     "expr": "unique count ( [ORDERS::APPOINTMENT_ID] ) "},
                ],
            }
        }

    def test_regular_column_ai_context_emitted(self):
        files, _ = build_dbt_export(
            model_tml=self._model_with_ai_context(), table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c for m in doc["models"] for c in m["columns"]}
        assert cols["APPOINTMENT_ID"]["config"]["meta"]["ts_ai_context"] == \
            "these are appointments made by the client"

    def test_formula_column_ai_context_emitted(self):
        files, _ = build_dbt_export(
            model_tml=self._formula_model_with_ai_context(), table_tmls=self._tables(),
            project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        cols = {c["name"]: c for m in doc["models"] for c in m["columns"]}
        assert cols["Appt Count"]["config"]["meta"]["ts_ai_context"] == \
            "count of unique appointment IDs"

    def test_regular_column_ai_context_read_back(self):
        yml = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: APPOINTMENT_ID
        config:
          meta:
            ts_column_type: attribute
            ts_ai_context: these are appointments made by the client
"""
        tml = build_model_tml_from_schema_yml(yml, "M")
        cols = {c["column_id"]: c for c in tml["model"]["columns"] if "column_id" in c}
        assert cols["STG_ORDERS::APPOINTMENT_ID"]["properties"]["ai_context"] == \
            "these are appointments made by the client"

    def test_formula_column_ai_context_read_back(self):
        yml = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: Appt Count
        config:
          meta:
            ts_formula: 'unique count ( [STG_ORDERS::APPOINTMENT_ID] ) '
            ts_column_type: measure
            ts_aggregation: sum
            ts_ai_context: count of unique appointment IDs
"""
        tml = build_model_tml_from_schema_yml(yml, "M")
        formula_cols = [c for c in tml["model"]["columns"] if "formula_id" in c]
        assert len(formula_cols) == 1
        assert formula_cols[0]["properties"]["ai_context"] == "count of unique appointment IDs"


# ---------------------------------------------------------------------------
# manifest_table_locations / apply_table_fqns — build-model fqn pinning
# ---------------------------------------------------------------------------

class TestManifestTableLocationsAndFqns:
    _MANIFEST = {"nodes": {
        "model.p.barbers": {"resource_type": "model", "name": "barbers", "alias": "barbers_v",
                            "database": "DL_TEST", "schema": "dbt_dlee_prod",
                            "original_file_path": "models/staging/barbershop/barbers.sql"},
        "model.p.services": {"resource_type": "model", "name": "services",
                             "database": "DL_TEST", "schema": "dbt_dlee_prod",
                             "original_file_path": "models/staging/barbershop/services.sql"},
        "test.p.t1": {"resource_type": "test", "name": "not_a_model"},
    }}

    def test_locations_use_alias_then_name_and_skip_non_models(self):
        from ts_cli.dbt_build_export import manifest_table_locations
        locs = manifest_table_locations(self._MANIFEST)
        assert set(locs) == {"BARBERS", "SERVICES"}
        assert locs["BARBERS"] == {"database": "DL_TEST", "schema": "dbt_dlee_prod", "db_table": "barbers_v"}
        assert locs["SERVICES"]["db_table"] == "services"

    def test_apply_table_fqns_pins_resolved_only(self):
        from ts_cli.dbt_build_export import apply_table_fqns
        tml = {"model": {"name": "M", "model_tables": [
            {"id": "BARBERS", "name": "BARBERS", "joins": []},
            {"id": "SERVICES", "name": "SERVICES"},
        ]}}
        out = apply_table_fqns(tml, {"BARBERS": "g-new"})
        assert out is tml
        assert tml["model"]["model_tables"][0]["fqn"] == "g-new"
        assert "fqn" not in tml["model"]["model_tables"][1]


# ---------------------------------------------------------------------------
# prettify_column_name / pretty_names / ts_display_name — Model display names
# ---------------------------------------------------------------------------

class TestPrettyColumnNames:
    _MANIFEST = {"nodes": {
        "model.p.appointments": {
            "resource_type": "model", "name": "appointments",
            "original_file_path": "models/staging/barbershop/appointments.sql",
            "columns": {
                "APPOINTMENT_DATETIME": {"config": {"meta": {"ts_column_type": "attribute"}}},
                "CUSTOMER_ID": {"config": {"meta": {"ts_column_type": "attribute"}}},
                "NOTES": {"config": {"meta": {"ts_column_type": "attribute",
                                               "ts_display_name": "Stylist Notes"}}},
                "TOTAL": {"config": {"meta": {"ts_column_type": "measure", "ts_aggregation": "sum",
                                               "ts_formula": "sum([APPOINTMENTS::TOTAL])"}}},
            },
        },
    }}

    def test_prettify_examples(self):
        from ts_cli.dbt_build_export import prettify_column_name as p
        assert p("APPOINTMENT_DATETIME") == "Appointment Datetime"
        assert p("CUSTOMER_ID") == "Customer ID"
        assert p("ZIP_CODE") == "ZIP Code"
        assert p("APPOINTMENTS_CUSTOMER_ID") == "Appointments Customer ID"
        assert p("iPhone_MODEL") == "iPhone Model"
        assert p("Net Revenue") == "Net Revenue"
        assert p("__") == "__"  # nothing to split on → unchanged, never empty

    def _names(self, pretty):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        tml = build_model_tml_from_manifest(
            self._MANIFEST, {}, "models/staging/barbershop", "M", pretty_names=pretty)
        return {c.get("column_id", "formula:" + c["name"]): c["name"] for c in tml["model"]["columns"]}

    def test_default_keeps_warehouse_names_but_honours_ts_display_name(self):
        names = self._names(pretty=False)
        assert names["APPOINTMENTS::APPOINTMENT_DATETIME"] == "APPOINTMENT_DATETIME"
        assert names["APPOINTMENTS::NOTES"] == "Stylist Notes"

    def test_pretty_names_transforms_physical_columns_only(self):
        names = self._names(pretty=True)
        assert names["APPOINTMENTS::APPOINTMENT_DATETIME"] == "Appointment Datetime"
        assert names["APPOINTMENTS::CUSTOMER_ID"] == "Customer ID"
        assert names["APPOINTMENTS::NOTES"] == "Stylist Notes"      # override still wins
        assert names["formula:TOTAL"] == "TOTAL"                    # formula names untouched


class TestDisplayNameCollisions:
    def test_detects_case_insensitive_duplicates_across_physical_and_formula(self):
        from ts_cli.dbt_build_export import find_display_name_collisions
        tml = {"model": {"columns": [
            {"name": "Appointment Time", "column_id": "APPOINTMENTS::APPOINTMENT_DATETIME"},
            {"name": "appointment time", "column_id": "APPOINTMENTS::APPOINTMENT_TIME"},
            {"name": "Status", "column_id": "APPOINTMENTS::STATUS"},
            {"name": "STATUS", "formula_id": "formula_status"},
            {"name": "Unique", "column_id": "T::UNIQUE"},
        ]}}
        assert find_display_name_collisions(tml) == [
            ("appointment time", ["APPOINTMENTS::APPOINTMENT_DATETIME", "APPOINTMENTS::APPOINTMENT_TIME"]),
            ("status", ["APPOINTMENTS::STATUS", "formula:formula_status"]),
        ]

    def test_no_collisions(self):
        from ts_cli.dbt_build_export import find_display_name_collisions
        assert find_display_name_collisions({"model": {"columns": [{"name": "A"}, {"name": "B"}]}}) == []


class TestDisplayNameRoundTrip:
    def _tml(self, display):
        return {"model": {"name": "M", "model_tables": [{"id": "T", "name": "T"}],
                          "columns": [{"name": display, "column_id": "T::APPOINTMENT_DATETIME",
                                       "properties": {"column_type": "ATTRIBUTE"}}]}}
    _TABLES = {"T": {"table": {"name": "T", "db": "DB", "schema": "S", "db_table": "T",
                               "columns": [{"name": "x", "db_column_name": "APPOINTMENT_DATETIME",
                                            "db_column_properties": {"data_type": "DATE_TIME"}}]}}}

    def _meta(self, display):
        from ts_cli.dbt_build_export import build_dbt_export
        files, _ = build_dbt_export(model_tml=self._tml(display), table_tmls=self._TABLES,
                                    project_name="p", source_name="w")
        import yaml
        doc = yaml.safe_load(files["models/schema.yml"])
        return doc["models"][0]["columns"][0]["config"]["meta"]

    def test_custom_display_name_emitted(self):
        assert self._meta("Appointment Time")["ts_display_name"] == "Appointment Time"

    def test_physical_or_prettified_name_not_emitted(self):
        assert "ts_display_name" not in self._meta("APPOINTMENT_DATETIME")
        assert "ts_display_name" not in self._meta("Appointment Datetime")   # == prettify()
        assert "ts_display_name" not in self._meta("T Appointment Datetime")  # build-model's dedupe form


class TestFormulaColumnPropsFromManifest:
    def test_synonyms_format_and_description_carried_on_formula_columns(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = {"nodes": {"model.p.appointments": {
            "resource_type": "model", "name": "appointments",
            "original_file_path": "models/staging/barbershop/appointments.sql",
            "columns": {"Number of appointments": {
                "description": "Distinct appointments.",
                "config": {"meta": {"ts_formula": "unique count ( [APPOINTMENTS::APPOINTMENT_ID] )",
                                    "ts_column_type": "measure", "ts_aggregation": "sum",
                                    "ts_synonym": "appointment count, bookings",
                                    "ts_format_pattern": "#,##0"}}}}}}}
        tml = build_model_tml_from_manifest(man, {}, "models/staging/barbershop", "M")
        col = next(c for c in tml["model"]["columns"] if c.get("formula_id"))
        assert col["properties"]["synonyms"] == ["appointment count", "bookings"]
        assert col["properties"]["format_pattern"] == "#,##0"
        assert col["description"] == "Distinct appointments."


class TestTsColumnExclude:
    _MAN = {"nodes": {"model.p.appointments": {
        "resource_type": "model", "name": "appointments",
        "original_file_path": "models/staging/barbershop/appointments.sql",
        "columns": {
            "APPOINTMENT_ID": {"config": {"meta": {"ts_column_type": "attribute"}}},
            "INTERNAL_NOTES": {"config": {"meta": {"ts_column_type": "attribute", "ts_column_exclude": True}}},
            "LEGACY_FLAG": {"config": {"meta": {"ts_column_type": "attribute", "ts_column_exclude": "yes"}}},
            "KEEP_FLAG": {"config": {"meta": {"ts_column_type": "attribute", "ts_column_exclude": "no"}}},
            "Secret Metric": {"config": {"meta": {"ts_formula": "sum([APPOINTMENTS::X])",
                                                   "ts_column_type": "measure", "ts_column_exclude": True}}},
        }}}}

    def test_is_column_excluded_truthiness(self):
        from ts_cli.dbt_build_export import is_column_excluded as ex
        assert ex({"ts_column_exclude": True}) and ex({"ts_column_exclude": "yes"}) and ex({"ts_column_exclude": "TRUE"})
        assert not ex({"ts_column_exclude": False}) and not ex({"ts_column_exclude": "no"}) and not ex({}) and not ex(None)

    def test_excluded_columns_and_formulas_left_out_of_model(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        tml = build_model_tml_from_manifest(self._MAN, {}, "models/staging/barbershop", "M")
        ids = {c.get("column_id") or "formula:" + c["name"] for c in tml["model"]["columns"]}
        assert ids == {"APPOINTMENTS::APPOINTMENT_ID", "APPOINTMENTS::KEEP_FLAG"}
        assert not tml["model"].get("formulas")
        assert tml["_excluded_columns"] == ["APPOINTMENTS::INTERNAL_NOTES", "APPOINTMENTS::LEGACY_FLAG",
                                            "APPOINTMENTS::Secret Metric"]


class TestInferredColumnMeta:
    def test_infer_helper(self):
        from ts_cli.dbt_build_export import infer_column_meta
        assert infer_column_meta("NUMBER(38,2)") == {"ts_column_type": "measure", "ts_aggregation": "sum"}
        assert infer_column_meta("FLOAT") == {"ts_column_type": "measure", "ts_aggregation": "sum"}
        assert infer_column_meta("TEXT") == {"ts_column_type": "attribute"}
        assert infer_column_meta("DATE") == {"ts_column_type": "attribute"}
        assert infer_column_meta("") == {"ts_column_type": "attribute"}
        # a MetricFlow entity/dimension is an attribute even when numeric (e.g. an ID key)
        assert infer_column_meta("NUMBER(38,0)", is_mf_attribute=True) == {"ts_column_type": "attribute"}
        # identifier-like names are attributes even when numeric and not declared as entities
        for n in ("BARBER_ID", "ID", "ORDER_KEY", "ZIP_CODE", "INVOICE_NUMBER", "SEQ_NUM", "ACCT_NO"):
            assert infer_column_meta("NUMBER", column_name=n) == {"ts_column_type": "attribute"}, n
        assert infer_column_meta("NUMBER", column_name="IDLE_HOURS") == {"ts_column_type": "measure", "ts_aggregation": "sum"}
        assert infer_column_meta("NUMBER", column_name="TOTAL_UNITS") == {"ts_column_type": "measure", "ts_aggregation": "sum"}

    def test_untagged_columns_included_with_catalog_types(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = {"nodes": {"model.p.fact": {
            "resource_type": "model", "name": "fact", "unique_id": "model.p.fact",
            "original_file_path": "models/demo/fact.sql",
            "columns": {
                "TXN_ID": {"entity": {"type": "primary", "name": "txn"}},
                "TXN_DATE": {"dimension": {"type": "time", "name": "txn_date"}, "granularity": "day"},
                "AMOUNT": {"description": "Amount in USD."},
                "NOTE": {},
                "TAGGED": {"config": {"meta": {"ts_column_type": "attribute", "ts_synonym": "t"}}},
            }}}}
        cat = {"nodes": {"model.p.fact": {"columns": {
            "TXN_ID": {"type": "NUMBER(38,0)"}, "TXN_DATE": {"type": "DATE"},
            "AMOUNT": {"type": "NUMBER(38,2)"}, "NOTE": {"type": "TEXT"}, "TAGGED": {"type": "TEXT"}}}}}
        cat["nodes"]["model.p.fact"]["columns"]["UNDECLARED_QTY"] = {"type": "NUMBER(38,0)", "name": "UNDECLARED_QTY"}
        tml = build_model_tml_from_manifest(man, cat, "models/demo", "M")
        inferred = tml.pop("_inferred_columns")
        assert inferred == ["FACT::AMOUNT", "FACT::NOTE", "FACT::TXN_DATE", "FACT::TXN_ID", "FACT::UNDECLARED_QTY"]
        props = {c["column_id"]: c.get("properties", {}) for c in tml["model"]["columns"]}
        assert props["FACT::AMOUNT"] == {"column_type": "MEASURE", "aggregation": "SUM"}
        assert props["FACT::TXN_ID"] == {"column_type": "ATTRIBUTE"}        # numeric but an entity
        assert props["FACT::TXN_DATE"] == {"column_type": "ATTRIBUTE"}
        assert props["FACT::NOTE"] == {"column_type": "ATTRIBUTE"}
        assert props["FACT::UNDECLARED_QTY"] == {"column_type": "MEASURE", "aggregation": "SUM"}  # catalog-only column
        assert props["FACT::TAGGED"]["synonyms"] == ["t"]                    # declared meta untouched
        assert next(c for c in tml["model"]["columns"] if c["column_id"] == "FACT::AMOUNT")["description"] == "Amount in USD."

    def test_fully_tagged_project_reports_no_inference(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = {"nodes": {"model.p.t": {"resource_type": "model", "name": "t", "unique_id": "model.p.t",
            "original_file_path": "models/demo/t.sql",
            "columns": {"A": {"config": {"meta": {"ts_column_type": "measure", "ts_aggregation": "sum"}}}}}}}
        tml = build_model_tml_from_manifest(man, {}, "models/demo", "M")
        assert "_inferred_columns" not in tml

    def test_excluded_column_not_resurrected_from_catalog(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = {"nodes": {"model.p.t": {"resource_type": "model", "name": "t", "unique_id": "model.p.t",
            "original_file_path": "models/demo/t.sql",
            "columns": {"HIRE_DATE": {"config": {"meta": {"ts_column_exclude": True}}}}}}}
        cat = {"nodes": {"model.p.t": {"columns": {"HIRE_DATE": {"type": "DATE", "name": "HIRE_DATE"},
                                                    "RATE": {"type": "NUMBER", "name": "RATE"}}}}}
        tml = build_model_tml_from_manifest(man, cat, "models/demo", "M")
        ids = [c["column_id"] for c in tml["model"]["columns"]]
        assert ids == ["T::RATE"] and tml["_excluded_columns"] == ["T::HIRE_DATE"]


class TestGeneratedMetaKeyBoundary:
    """`GENERATED_COLUMN_META_KEYS` / `GENERATED_MODEL_META_KEYS` declare which
    `ts_*` tags this generator owns, and `sync --update-metadata` clears exactly
    those. If an emitter starts writing a key the set doesn't declare, the tag
    stops round-tripping through Case B; if the set declares a key no emitter
    writes, a hand-authored tag gets deleted. Both directions are silent, so
    both are asserted here.
    """

    def _maximal_export(self):
        """A Model exercising every column property that maps to a ts_* tag,
        plus a formula column, a role-play alias, a join and table RLS."""
        model = {"model": {
            "name": "Max Model",
            "model_tables": [
                {"id": "ORDERS", "name": "ORDERS", "joins": [{
                    "name": "orders_to_customers", "with": "CUSTOMERS",
                    "on": "[ORDERS::CUSTOMER_ID] = [CUSTOMERS::CUSTOMER_ID]",
                    "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]},
                {"id": "CUSTOMERS", "name": "CUSTOMERS"},
            ],
            "formulas": [{"id": "formula_Rev", "name": "Rev",
                          "expr": "sum([ORDERS::AMOUNT])"}],
            "columns": [
                {"name": "Amount Renamed", "column_id": "ORDERS::AMOUNT",
                 "description": "the amount",
                 "properties": {
                     "column_type": "MEASURE", "aggregation": "SUM",
                     "synonyms": ["revenue", "takings"],
                     "format_pattern": "#,##0.00",
                     "index_type": "DONT_INDEX", "index_priority": 8,
                     "is_attribution_dimension": True, "is_additive": True,
                     "spotiq_preference": "EXCLUDE",
                     "ai_context": "money taken on the order",
                     "is_hidden": True, "calendar": "fiscal",
                     # TML shapes per thoughtspot-model-tml.md (2026-07-30 census):
                     # currency_type is one of iso_code/column/is_browser;
                     # geo_config's five role shapes are latitude/longitude/
                     # country (bare bool)/region_name (dict)/custom_file_guid.
                     "currency_type": {"iso_code": "USD"},
                     "geo_config": {"latitude": True},
                 }},
                {"name": "CUSTOMER_ID", "column_id": "ORDERS::CUSTOMER_ID",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Cust Id", "column_id": "CUSTOMERS::CUSTOMER_ID",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Rev", "formula_id": "formula_Rev",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                                "synonyms": ["income"], "index_type": "DEFAULT",
                                "ai_context": "derived revenue"}},
            ],
        }}
        tables = {
            "ORDERS": {"table": {
                "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
                "columns": [
                    {"name": "AMOUNT", "db_column_name": "AMOUNT",
                     "db_column_properties": {"data_type": "DOUBLE"}},
                    {"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID",
                     "db_column_properties": {"data_type": "VARCHAR"}},
                ],
                "rls_rules": {
                    "table_paths": [{"id": "ORDERS_1", "table": "ORDERS",
                                     "column": ["CUSTOMER_ID"]}],
                    "rules": [{"name": "own rows",
                               "expr": "ts_username = [ORDERS_1::CUSTOMER_ID]"}]},
            }},
            "CUSTOMERS": {"table": {
                "name": "CUSTOMERS", "db": "DB", "schema": "S", "db_table": "CUSTOMERS",
                "columns": [{"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID",
                             "db_column_properties": {"data_type": "VARCHAR"}}],
            }},
        }
        files, info = build_dbt_export(
            model_tml=model, table_tmls=tables,
            project_name="p", source_name="src")
        return yaml.safe_load(files["models/schema.yml"]), info

    def test_every_emitted_column_key_is_declared(self):
        from ts_cli.dbt_build_export import GENERATED_COLUMN_META_KEYS
        doc, _ = self._maximal_export()
        emitted = {
            k
            for m in doc["models"]
            for c in m.get("columns") or []
            for k in ((c.get("config") or {}).get("meta") or {})
        }
        assert emitted, "fixture produced no column meta at all"
        undeclared = emitted - GENERATED_COLUMN_META_KEYS
        assert not undeclared, (
            f"emitter writes {sorted(undeclared)} but GENERATED_COLUMN_META_KEYS "
            "does not declare them — sync --update-metadata would never clear "
            "them, so a property removed in ThoughtSpot would linger in schema.yml")

    def test_every_declared_column_key_is_reachable(self):
        from ts_cli.dbt_build_export import GENERATED_COLUMN_META_KEYS
        doc, _ = self._maximal_export()
        emitted = {
            k
            for m in doc["models"]
            for c in m.get("columns") or []
            for k in ((c.get("config") or {}).get("meta") or {})
        }
        unreachable = GENERATED_COLUMN_META_KEYS - emitted
        assert not unreachable, (
            f"GENERATED_COLUMN_META_KEYS declares {sorted(unreachable)} but no "
            "emitter produces them — sync --update-metadata would DELETE a "
            "hand-authored tag of that name")

    # Every column tag on docs.thoughtspot.com/cloud/26.9.0.cl/
    # dbt-integration-metadata-tags (verified 2026-09-09).
    DOCUMENTED_COLUMN_TAGS = {
        "ts_additive", "ts_aggregation", "ts_attr_dim", "ts_calendar_type",
        "ts_column_type", "ts_currency_type", "ts_format_pattern",
        "ts_geo_config", "ts_hidden", "ts_index_priority", "ts_index_type",
        "ts_spotiq_pref", "ts_synonym",
    }

    def test_all_documented_column_tags_are_emitted(self):
        """Full coverage of ThoughtSpot's documented column tag set."""
        doc, info = self._maximal_export()
        emitted = {
            k
            for m in doc["models"]
            for c in m.get("columns") or []
            for k in ((c.get("config") or {}).get("meta") or {})
        }
        missing = self.DOCUMENTED_COLUMN_TAGS - emitted
        assert not missing, f"documented tags never emitted: {sorted(missing)}"
        # nothing that now has a tag should still be reported unmapped
        reported = {u["property"] for u in info["unmapped_properties"]}
        assert not (reported & {"is_hidden", "calendar", "currency_type", "geo_config"})

    def test_ts_column_exclude_stays_outside_the_ownership_set(self):
        """Hand-authored by definition — no Model property produces it, so it
        must never be treated as generator-owned or sync would delete it."""
        from ts_cli.dbt_build_export import GENERATED_COLUMN_META_KEYS
        assert "ts_column_exclude" not in GENERATED_COLUMN_META_KEYS

    def test_model_level_key_set_matches_emitter(self):
        from ts_cli.dbt_build_export import GENERATED_MODEL_META_KEYS
        doc, _ = self._maximal_export()
        emitted = {
            k
            for m in doc["models"]
            for k in ((m.get("config") or {}).get("meta") or {})
        }
        assert emitted == set(GENERATED_MODEL_META_KEYS) == {"ts_rls_rules"}


class TestFullPropertyRoundTrip:
    """ThoughtSpot Model -> schema.yml -> ThoughtSpot Model, property-for-property.

    The guarantee the tag work exists to provide: every column property with a
    documented `ts_*` tag survives the trip out to dbt and back. Asserted as
    equality on the whole `properties` dict, so a property that silently stops
    being emitted OR stops being read back fails here — which is how
    `ts_index_priority`, `ts_attr_dim`, `ts_additive` and `ts_spotiq_pref` were
    found to be write-only.
    """

    def _model(self, props: dict, *, formula: bool = False):
        col = ({"name": "Rev", "formula_id": "formula_Rev", "properties": props}
               if formula else
               {"name": "AMOUNT", "column_id": "ORDERS::AMOUNT", "properties": props})
        model = {"model": {
            "name": "M",
            "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
            "columns": [col],
            "formulas": ([{"id": "formula_Rev", "name": "Rev",
                           "expr": "sum([ORDERS::AMOUNT])"}] if formula else []),
        }}
        tables = {"ORDERS": {"table": {
            "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
            "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT",
                         "db_column_properties": {"data_type": "DOUBLE"}}]}}}
        return model, tables

    def _round_trip(self, props: dict, *, formula: bool = False) -> dict:
        model, tables = self._model(props, formula=formula)
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        back = build_model_tml_from_schema_yml(files["models/schema.yml"], "M")
        cols = back["model"]["columns"]
        assert len(cols) == 1, cols
        return cols[0].get("properties") or {}

    def test_measure_with_every_documented_property(self):
        props = {
            "column_type": "MEASURE",
            "aggregation": "AVERAGE",
            "synonyms": ["revenue", "takings"],
            # derived on read-back from the presence of synonyms, per
            # thoughtspot-model-tml.md — part of an exact round trip
            "synonym_type": "USER_DEFINED",
            "format_pattern": "#,##0.00",
            "index_type": "DONT_INDEX",
            "index_priority": 8,
            "is_attribution_dimension": True,
            "is_additive": True,
            "spotiq_preference": "EXCLUDE",
            "is_hidden": True,
            "calendar": "fiscal_2026",
            "currency_type": {"iso_code": "USD"},
            "ai_context": "money taken on the order",
        }
        assert self._round_trip(props) == props

    def test_attribute_with_geo_region(self):
        props = {
            "column_type": "ATTRIBUTE",
            "geo_config": {"region_name": {"country": "UNITED STATES",
                                            "region_name": "state"}},
        }
        assert self._round_trip(props) == props

    def test_each_geo_role_round_trips(self):
        for geo in ({"latitude": True}, {"longitude": True}, {"country": True},
                    {"region_name": {"country": "FRANCE", "region_name": "city"}}):
            props = {"column_type": "ATTRIBUTE", "geo_config": geo}
            assert self._round_trip(props) == props, geo

    def test_each_currency_form_round_trips(self):
        for cur in ({"iso_code": "EUR"}, {"column": "CCY_CODE"}, {"is_browser": True}):
            props = {"column_type": "MEASURE", "aggregation": "SUM",
                     "currency_type": cur}
            assert self._round_trip(props) == props, cur

    def test_formula_column_carries_the_full_set(self):
        """A formula column used to get only four tags; it now takes the same
        path as a physical one (geo_config and calendar are census-confirmed on
        formula-backed columns)."""
        props = {
            "column_type": "MEASURE",
            "aggregation": "SUM",
            "synonyms": ["income"],
            "synonym_type": "USER_DEFINED",
            "format_pattern": "#,##0",
            "index_type": "DONT_INDEX",
            "index_priority": 5,
            "is_additive": True,
            "spotiq_preference": "EXCLUDE",
            "is_hidden": True,
            "calendar": "fiscal_2026",
            "currency_type": {"is_browser": True},
            "ai_context": "derived revenue",
        }
        assert self._round_trip(props, formula=True) == props

    def test_custom_map_geo_role_is_reported_not_mangled(self):
        """The one geo shape with no ts_geo_config type. thoughtspot-model-tml.md
        calls custom_file_guid instance-local, so it must be dropped and
        reported — never guessed into another role."""
        model, tables = self._model({
            "column_type": "ATTRIBUTE",
            "geo_config": {"custom_file_guid": "f3faaa74-147f-4376-ac42-eff0c3779f6f",
                            "geometryType": "POLYGON"}})
        files, info = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        doc = yaml.safe_load(files["models/schema.yml"])
        meta = (doc["models"][0]["columns"][0].get("config") or {}).get("meta") or {}
        assert "ts_geo_config" not in meta
        geo_reports = [u for u in info["unmapped_properties"]
                       if u["property"] == "geo_config"]
        assert len(geo_reports) == 1
        assert "custom_file_guid" in geo_reports[0]["reason"]

    def test_manifest_reader_agrees_with_schema_yml_reader(self):
        """Both read paths must produce identical properties from identical
        tags — they previously each inlined their own partial version."""
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        props = {
            "column_type": "MEASURE", "aggregation": "SUM",
            "index_priority": 9, "is_additive": True,
            "spotiq_preference": "EXCLUDE", "is_hidden": True,
            "calendar": "fiscal_2026", "currency_type": {"iso_code": "GBP"},
            "geo_config": {"country": True},
        }
        model, tables = self._model(props)
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        schema_doc = yaml.safe_load(files["models/schema.yml"])
        meta = (schema_doc["models"][0]["columns"][0].get("config") or {}).get("meta") or {}

        manifest = {"nodes": {"model.p.stg_orders": {
            "resource_type": "model", "name": "stg_orders",
            "original_file_path": "models/staging/stg_orders.sql",
            "columns": {"AMOUNT": {"config": {"meta": meta}}}}}}
        via_manifest = build_model_tml_from_manifest(
            manifest, {}, "models/staging", "M")["model"]["columns"][0]["properties"]
        via_schema = build_model_tml_from_schema_yml(
            files["models/schema.yml"], "M")["model"]["columns"][0]["properties"]
        assert via_manifest == via_schema == props


class TestNoTagPropertiesAreReported:
    """Model column properties with no `ts_*` tag at all must be REPORTED, not
    dropped in silence — the module's standing contract. These four were
    previously not even collected, so they vanished with no trace."""

    def test_all_four_reported(self):
        props = {
            "column_type": "ATTRIBUTE",
            "value_casing": "UNKNOWN",
            "custom_order": ["USA", "UK", "France"],
            "default_date_bucket": "MONTHLY",
            "search_iq_preferred": True,
        }
        model = {"model": {"name": "M", "model_tables": [{"id": "T", "name": "T"}],
                            "columns": [{"name": "C", "column_id": "T::C",
                                         "properties": props}], "formulas": []}}
        tables = {"T": {"table": {"name": "T", "db": "DB", "schema": "S", "db_table": "T",
                                   "columns": [{"name": "C", "db_column_name": "C"}]}}}
        _files, info = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        reported = {u["property"] for u in info["unmapped_properties"]}
        assert {"value_casing", "custom_order", "default_date_bucket",
                "search_iq_preferred"} <= reported
        for u in info["unmapped_properties"]:
            assert u["reason"], u
            assert u["column"] == "C"

    def test_absent_properties_are_not_reported(self):
        """No false positives — a column without them stays quiet."""
        model = {"model": {"name": "M", "model_tables": [{"id": "T", "name": "T"}],
                            "columns": [{"name": "C", "column_id": "T::C",
                                         "properties": {"column_type": "ATTRIBUTE"}}],
                            "formulas": []}}
        tables = {"T": {"table": {"name": "T", "db": "DB", "schema": "S", "db_table": "T",
                                   "columns": [{"name": "C", "db_column_name": "C"}]}}}
        _files, info = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        assert info["unmapped_properties"] == []


class TestCustomTagReaderParity:
    """The five ts-cli extension tags must behave identically in both readers.

    `ts dbt build-model` (manifest) and `ts dbt-export build-model` (schema.yml)
    are the two ways dbt metadata returns to ThoughtSpot. They had drifted:
    the schema.yml reader ignored `ts_display_name` and `ts_column_exclude`, so
    a user who edited either in dbt lost the edit on that path — exactly the
    round-trip guarantee these tags exist to provide.
    """

    _META = {
        "AMOUNT": {"ts_column_type": "measure", "ts_aggregation": "sum",
                   "ts_display_name": "Order Value",
                   "ts_ai_context": "what the customer paid"},
        "INTERNAL_NOTE": {"ts_column_type": "attribute", "ts_column_exclude": "yes"},
        "Margin": {"ts_formula": "sum([ORDERS::AMOUNT]) - 10",
                   "ts_column_type": "measure", "ts_aggregation": "sum"},
        "Scratch": {"ts_formula": "1 + 1", "ts_column_type": "attribute",
                    "ts_column_exclude": True},
    }

    def _schema_yml(self) -> str:
        return yaml.safe_dump({"version": 2, "models": [{
            "name": "orders",
            "columns": [{"name": n, "config": {"meta": m}}
                        for n, m in self._META.items()],
        }]}, sort_keys=False)

    def _manifest(self) -> dict:
        return {"nodes": {"model.p.orders": {
            "resource_type": "model", "name": "orders",
            "original_file_path": "models/staging/orders.sql",
            "columns": {n: {"config": {"meta": m}} for n, m in self._META.items()},
        }}}

    def _summarise(self, tml: dict) -> dict:
        cols = tml["model"]["columns"]
        return {
            "names": sorted(c["name"] for c in cols),
            "ai_context": {c["name"]: (c.get("properties") or {}).get("ai_context")
                           for c in cols},
            "formulas": sorted(f["name"] for f in tml["model"].get("formulas") or []),
        }

    def test_both_readers_agree_on_every_custom_tag(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        via_schema = build_model_tml_from_schema_yml(self._schema_yml(), "M")
        via_manifest = build_model_tml_from_manifest(
            self._manifest(), {}, "models/staging", "M")
        assert self._summarise(via_schema) == self._summarise(via_manifest)

    def test_ts_display_name_applied_by_schema_yml_reader(self):
        tml = build_model_tml_from_schema_yml(self._schema_yml(), "M")
        names = {c["name"] for c in tml["model"]["columns"]}
        assert "Order Value" in names and "AMOUNT" not in names

    def test_ts_column_exclude_honoured_by_schema_yml_reader(self):
        tml = build_model_tml_from_schema_yml(self._schema_yml(), "M")
        names = {c["name"] for c in tml["model"]["columns"]}
        assert "INTERNAL_NOTE" not in names
        # ...including an excluded FORMULA column
        assert "Scratch" not in names
        assert "Scratch" not in {f["name"] for f in tml["model"].get("formulas") or []}
        assert tml["_excluded_columns"] == ["ORDERS::INTERNAL_NOTE", "ORDERS::Scratch"]

    def test_ts_display_name_survives_a_full_round_trip(self):
        """Renamed in ThoughtSpot -> ts_display_name in dbt -> name restored."""
        model = {"model": {
            "name": "M", "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
            "columns": [{"name": "Order Value", "column_id": "ORDERS::AMOUNT",
                         "properties": {"column_type": "MEASURE",
                                        "aggregation": "SUM",
                                        "ai_context": "what the customer paid"}}],
            "formulas": []}}
        tables = {"ORDERS": {"table": {
            "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
            "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT",
                         "db_column_properties": {"data_type": "DOUBLE"}}]}}}
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        meta = (yaml.safe_load(files["models/schema.yml"])["models"][0]["columns"][0]
                .get("config") or {}).get("meta") or {}
        assert meta["ts_display_name"] == "Order Value"
        assert meta["ts_ai_context"] == "what the customer paid"

        back = build_model_tml_from_schema_yml(files["models/schema.yml"], "M")
        col = back["model"]["columns"][0]
        assert col["name"] == "Order Value"
        assert col["properties"]["ai_context"] == "what the customer paid"

    def test_ts_rls_rules_round_trips_through_schema_yml(self):
        """RLS is emitted at model level and extractable back to Table TML shape."""
        rls = {"table_paths": [{"id": "ORDERS_1", "table": "ORDERS",
                                 "column": ["CUSTOMER_ID"]}],
               "rules": [{"name": "own rows",
                           "expr": "ts_username = [ORDERS_1::CUSTOMER_ID]"}]}
        model = {"model": {
            "name": "M", "model_tables": [{"id": "ORDERS", "name": "ORDERS"}],
            "columns": [{"name": "CUSTOMER_ID", "column_id": "ORDERS::CUSTOMER_ID",
                         "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": []}}
        tables = {"ORDERS": {"table": {
            "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
            "rls_rules": rls,
            "columns": [{"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID",
                         "db_column_properties": {"data_type": "VARCHAR"}}]}}}
        files, _ = build_dbt_export(
            model_tml=model, table_tmls=tables, project_name="p", source_name="src")
        schema_text = files["models/schema.yml"]
        assert "ts_rls_rules" in schema_text

        back = extract_table_rls_from_schema_yml(schema_text)
        # Keyed on ORDERS, not STG_ORDERS: the generated model carries
        # `alias: ORDERS` so it materialises under the Table's own name, and
        # the reader resolves through the alias. Without both halves the
        # return leg attaches RLS to a Table that does not exist.
        assert back["ORDERS"]["rules"] == rls["rules"]
        assert back["ORDERS"]["table_paths"] == rls["table_paths"]


# ---------------------------------------------------------------------------
# Identity preservation across the round trip
#
# Why: Case A used to name each staging model `stg_<table>`, which with no
# alias materialises as STG_<TABLE>. Syncing that back brought a SECOND
# ThoughtSpot Table in beside the original -- the Model silently repointed at
# the copy while the original kept every dependent it had. The same class of
# bug renamed every join. Both are silent: the output is valid, just wrong.
# ---------------------------------------------------------------------------

class TestRoundTripPreservesIdentity:
    def _model(self):
        return {"model": {
            "name": "M",
            "model_tables": [
                {"id": "APPOINTMENTS", "name": "APPOINTMENTS", "joins": [{
                    "name": "appointment_to_barber", "with": "BARBERS",
                    "on": "[APPOINTMENTS::Barber Id] = [BARBERS::Barber Id]",
                    "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]},
                {"id": "BARBERS", "name": "BARBERS"}],
            "columns": [
                {"name": "Barber Id", "column_id": "APPOINTMENTS::Barber Id",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Barber Id", "column_id": "BARBERS::Barber Id",
                 "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": []}}

    def _tables(self):
        col = [{"name": "Barber Id", "db_column_name": "BARBER_ID",
                "db_column_properties": {"data_type": "INT64"}}]
        return {n: {"table": {"name": n, "db": "DL", "schema": "S",
                              "db_table": n, "columns": list(col)}}
                for n in ("APPOINTMENTS", "BARBERS")}

    def _build(self):
        files, _ = build_dbt_export(
            model_tml=self._model(), table_tmls=self._tables(),
            project_name="p", source_name="src")
        return files

    def test_staging_model_is_aliased_to_the_table_name(self):
        import yaml as _y
        models = {m["name"]: m
                  for m in _y.safe_load(self._build()["models/schema.yml"])["models"]}
        assert models["stg_appointments"]["config"]["alias"] == "APPOINTMENTS"
        assert models["stg_barbers"]["config"]["alias"] == "BARBERS"

    def test_alias_sits_beside_meta_not_inside_it(self):
        """`alias` is a dbt config key; nesting it under meta: would make dbt
        ignore it and silently restore the STG_ rename."""
        import yaml as _y
        models = {m["name"]: m
                  for m in _y.safe_load(self._build()["models/schema.yml"])["models"]}
        cfg = models["stg_appointments"]["config"]
        assert "alias" in cfg and "alias" not in (cfg.get("meta") or {})

    def test_tables_round_trip_under_their_original_names(self):
        tml = build_model_tml_from_schema_yml(self._build()["models/schema.yml"], "M")
        names = {t["name"] for t in tml["model"]["model_tables"]}
        assert names == {"APPOINTMENTS", "BARBERS"}, \
            f"round trip renamed the tables: {names}"

    def test_join_keeps_its_thoughtspot_name(self):
        tml = build_model_tml_from_schema_yml(self._build()["models/schema.yml"], "M")
        joins = [j for t in tml["model"]["model_tables"] for j in t.get("joins") or []]
        assert [j["name"] for j in joins] == ["appointment_to_barber"]

    def test_join_on_clause_uses_the_aliased_table_names(self):
        """A `ref()` names the MODEL; resolving it to the alias is what keeps
        the join pointing at real tables."""
        tml = build_model_tml_from_schema_yml(self._build()["models/schema.yml"], "M")
        joins = [j for t in tml["model"]["model_tables"] for j in t.get("joins") or []]
        assert "[APPOINTMENTS::" in joins[0]["on"]
        assert "[BARBERS::" in joins[0]["on"]
        assert "STG_" not in joins[0]["on"]

    def test_adopted_case_b_names_are_never_aliased(self):
        """Case B adopts an existing project's model names. Those models
        already materialise somewhere real, so forcing an alias would repoint
        live warehouse relations."""
        import yaml as _y
        files, _ = build_dbt_export(
            model_tml=self._model(), table_tmls=self._tables(),
            project_name="p", source_name="src",
            model_name_overrides={"APPOINTMENTS": "appointments"})
        models = {m["name"]: m
                  for m in _y.safe_load(files["models/schema.yml"])["models"]}
        assert "alias" not in (models["appointments"].get("config") or {})
        # the non-overridden sibling still gets one
        assert models["stg_barbers"]["config"]["alias"] == "BARBERS"


class TestTargetSchemaCollision:
    _TABLES = {"APPOINTMENTS": {"table": {
        "name": "APPOINTMENTS", "db": "DL_TEST", "schema": "DBT_DLEE_PROD",
        "db_table": "APPOINTMENTS", "columns": []}}}

    def test_same_db_and_schema_is_a_collision(self):
        from ts_cli.dbt_build_export import find_target_schema_collisions
        hits = find_target_schema_collisions(self._TABLES, "DL_TEST.DBT_DLEE_PROD")
        assert hits == ["DL_TEST.DBT_DLEE_PROD.APPOINTMENTS"]

    def test_bare_schema_matches_on_schema_alone(self):
        from ts_cli.dbt_build_export import find_target_schema_collisions
        assert find_target_schema_collisions(self._TABLES, "DBT_DLEE_PROD")

    def test_case_insensitive(self):
        """A collision that differs only in case is still a collision."""
        from ts_cli.dbt_build_export import find_target_schema_collisions
        assert find_target_schema_collisions(self._TABLES, "dl_test.dbt_dlee_prod")

    def test_a_different_schema_is_clean(self):
        from ts_cli.dbt_build_export import find_target_schema_collisions
        assert find_target_schema_collisions(self._TABLES, "DL_TEST.DBT_DEV") == []

    def test_no_target_schema_reports_nothing(self):
        from ts_cli.dbt_build_export import find_target_schema_collisions
        assert find_target_schema_collisions(self._TABLES, "") == []
        assert find_target_schema_collisions(self._TABLES, None) == []


class TestSemanticModelsAreOptIn:
    """The secondary artifact is withheld by default (ts-convert-to-dbt #8).

    Emitting it makes the generated project unparseable by real dbt-core
    whenever a semantic model carries a time dimension — dbt-core wants a
    `metricflow_time_spine` model that this generator never writes. Verified
    against dbt-core 1.12.4 on 2026-09-10: deleting this one file turned a
    hard `dbt parse` error into a clean parse.
    """

    def _files(self, **kw):
        files, info = build_dbt_export(
            model_tml=_model_tml(), table_tmls=_table_tmls(),
            project_name="sales", source_name="warehouse", **kw)
        return files, info

    def test_not_written_by_default(self):
        files, info = self._files()
        assert "models/semantic_models.yml" not in files
        assert info["semantic_models_emitted"] is False

    def test_the_primary_artifact_is_unaffected(self):
        """Withholding the secondary artifact must not touch schema.yml —
        that is the one both the dbt sync and Path Y actually read."""
        files, _ = self._files()
        assert "models/schema.yml" in files

    def test_reported_as_available_so_the_command_can_say_so(self):
        """Silently omitting it would leave the user hunting for the file."""
        _, info = self._files()
        assert info["semantic_models_available"] is True

    def test_opt_in_restores_it(self):
        files, info = self._files(emit_semantic_models=True)
        assert "models/semantic_models.yml" in files
        assert info["semantic_models_emitted"] is True

    def test_files_written_matches_the_files_dict_either_way(self):
        for kw in ({}, {"emit_semantic_models": True}):
            files, info = self._files(**kw)
            assert info["files_written"] == sorted(files.keys())
