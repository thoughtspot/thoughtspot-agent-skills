"""Tests for ts_cli/databricks/mv_tml.py and mv_build_model.py.

One class per transform, mirroring test_model_builder.py. Golden classes pin
the shared worked examples (see TestGoldenEcommerce/TestGoldenSqlView, Task 6).
"""
import json

import pytest
import yaml
from typer.testing import CliRunner

from ts_cli.cli import app

from ts_cli.databricks.mv_build_model import (
    _check_no_duplicate_display_names,
    build_columns_and_formulas,
    build_description,
    build_model_tables,
    build_model_tml_dbx,
    display_title,
    flatten_join_aliases,
)
from ts_cli.databricks.mv_parse import parse_metric_view
from ts_cli.databricks.mv_tml import (
    build_table_tml,
    map_dbx_type,
    validate_tml_invariants,
)
from ts_cli.databricks.mv_translate import translate_metric_view


class TestMapDbxType:
    def test_string_family(self):
        assert map_dbx_type("string") == "VARCHAR"
        assert map_dbx_type("varchar(255)") == "VARCHAR"
        assert map_dbx_type("char(4)") == "VARCHAR"

    def test_int_family(self):
        assert map_dbx_type("bigint") == "INT64"
        assert map_dbx_type("int") == "INT64"
        assert map_dbx_type("smallint") == "INT64"
        assert map_dbx_type("tinyint") == "INT64"

    def test_float_family(self):
        assert map_dbx_type("double") == "DOUBLE"
        assert map_dbx_type("float") == "DOUBLE"
        assert map_dbx_type("decimal(10,2)") == "DOUBLE"

    def test_bool_date_time(self):
        assert map_dbx_type("boolean") == "BOOL"
        assert map_dbx_type("date") == "DATE"
        assert map_dbx_type("timestamp") == "DATETIME"
        assert map_dbx_type("timestamp_ntz") == "DATETIME"

    def test_case_and_whitespace_insensitive(self):
        assert map_dbx_type("  STRING ") == "VARCHAR"
        assert map_dbx_type("DECIMAL(38, 6)") == "DOUBLE"

    def test_unsupported_types_return_none(self):
        for t in ("binary", "array<string>", "map<string,int>", "struct<a:int>"):
            assert map_dbx_type(t) is None

    def test_unknown_type_raises_naming_type_and_doc(self):
        with pytest.raises(ValueError) as exc:
            map_dbx_type("interval")
        assert "interval" in str(exc.value)
        assert "ts-from-databricks-rules.md" in str(exc.value)


class TestBuildTableTml:
    INFO = {"name": "TRANSACTIONS", "create": True,
            "db": "analytics", "schema": "ecommerce", "db_table": "transactions",
            "columns": [
                {"name": "transaction_id", "dbx_type": "string"},
                {"name": "unit_price", "dbx_type": "double"},
                {"name": "raw_payload", "dbx_type": "binary"},
            ]}

    def test_shape_matches_worked_example(self):
        doc, notes = build_table_tml(self.INFO, "Databricks Analytics")
        t = doc["table"]
        assert t["name"] == "TRANSACTIONS"
        assert t["db"] == "analytics"
        assert t["schema"] == "ecommerce"
        assert t["db_table"] == "transactions"
        assert t["connection"] == {"name": "Databricks Analytics"}

    def test_every_column_has_db_column_name(self):
        doc, _ = build_table_tml(self.INFO, "C")
        for col in doc["table"]["columns"]:
            assert col["db_column_name"] == col["name"]

    def test_numeric_defaults_to_measure_sum(self):
        doc, _ = build_table_tml(self.INFO, "C")
        by_name = {c["name"]: c for c in doc["table"]["columns"]}
        assert by_name["unit_price"]["properties"] == {
            "column_type": "MEASURE", "aggregation": "SUM"}
        assert by_name["unit_price"]["db_column_properties"] == {"data_type": "DOUBLE"}
        assert by_name["transaction_id"]["properties"] == {"column_type": "ATTRIBUTE"}

    def test_explicit_column_type_overrides_heuristic(self):
        info = dict(self.INFO, columns=[
            {"name": "order_num", "dbx_type": "bigint", "column_type": "ATTRIBUTE"}])
        doc, _ = build_table_tml(info, "C")
        col = doc["table"]["columns"][0]
        assert col["properties"] == {"column_type": "ATTRIBUTE"}

    def test_unsupported_type_omitted_with_note(self):
        doc, notes = build_table_tml(self.INFO, "C")
        names = [c["name"] for c in doc["table"]["columns"]]
        assert "raw_payload" not in names
        assert any("raw_payload" in n for n in notes)

    def test_missing_required_field_raises(self):
        info = {k: v for k, v in self.INFO.items() if k != "db"}
        with pytest.raises(ValueError, match="db"):
            build_table_tml(info, "C")

    def test_missing_dbx_type_raises_clean_error(self):
        info = dict(self.INFO, columns=[{"name": "mystery_col"}])
        with pytest.raises(ValueError, match="mystery_col"):
            build_table_tml(info, "C")


class TestValidateTmlInvariants:
    def test_clean_table_tml(self):
        doc = {"table": {"name": "T", "db": "d", "schema": "s", "db_table": "t",
                         "connection": {"name": "C"},
                         "columns": [{"name": "a", "db_column_name": "a",
                                      "properties": {"column_type": "ATTRIBUTE"},
                                      "db_column_properties": {"data_type": "VARCHAR"}}]}}
        assert validate_tml_invariants(doc) == []

    def test_missing_db_column_name_flagged(self):
        doc = {"table": {"name": "T", "connection": {"name": "C"},
                         "columns": [{"name": "a",
                                      "properties": {"column_type": "ATTRIBUTE"}}]}}
        findings = validate_tml_invariants(doc)
        assert any("db_column_name" in f and "'a'" in f for f in findings)

    def test_fqn_in_connection_flagged(self):
        doc = {"table": {"name": "T",
                         "connection": {"name": "C", "fqn": "guid-x"}, "columns": []}}
        findings = validate_tml_invariants(doc)
        assert any("fqn" in f and "connection" in f for f in findings)

    def test_model_tml_passes_through(self):
        # model docs have no table columns/connection — nothing for THIS validator;
        # lint_tml owns the model-side invariants.
        assert validate_tml_invariants({"model": {"name": "M"}}) == []


def _t(name, output_kind, column_type, *, table=None, column=None, ts_expr=None,
       aggregation=None, display_name=None, comment=None, synonyms=None, fmt=None,
       annotations=None):
    return {"name": name, "role": "measure" if column_type == "MEASURE" else "dimension",
            "output_kind": output_kind, "column_type": column_type,
            "table": table, "column": column, "ts_expr": ts_expr,
            "aggregation": aggregation, "inlined_refs": [],
            "display_name": display_name, "comment": comment,
            "synonyms": synonyms or [], "format": fmt,
            "annotations": annotations or []}


class TestDisplayTitle:
    def test_display_name_wins(self):
        assert display_title({"name": "customer_region", "display_name": "Region"}) == "Region"

    def test_title_case_fallback(self):
        assert display_title({"name": "transaction_id", "display_name": None}) == "Transaction Id"


class TestBuildColumnsAndFormulas:
    def test_physical_attribute_column(self):
        cols, formulas, renames = build_columns_and_formulas(
            [_t("product_category", "column", "ATTRIBUTE", table="TRANSACTIONS",
                column="product_category", display_name="Product Category",
                synonyms=["category", "product type"])], None)
        assert formulas == [] and renames == {}
        assert cols == [{"name": "Product Category",
                         "column_id": "TRANSACTIONS::product_category",
                         "properties": {"column_type": "ATTRIBUTE",
                                        "synonyms": ["category", "product type"],
                                        "synonym_type": "USER_DEFINED"}}]

    def test_formula_measure_pairing(self):
        cols, formulas, _ = build_columns_and_formulas(
            [_t("total_revenue", "formula", "MEASURE",
                ts_expr="sum ( [T::a] )", aggregation="SUM",
                display_name="Total Revenue", comment="Net revenue.")], None)
        assert formulas == [{"id": "formula_Total Revenue", "name": "Total Revenue",
                             "expr": "sum ( [T::a] )"}]
        assert cols == [{"name": "Total Revenue",
                         "formula_id": "formula_Total Revenue",
                         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                                        "index_type": "DONT_INDEX",
                                        "description": "Net revenue."}}]

    def test_attribute_formula_gets_column_type_in_formulas(self):
        _, formulas, _ = build_columns_and_formulas(
            [_t("transaction_month", "formula", "ATTRIBUTE",
                ts_expr="start_of_month ( [T::d] )")], None)
        assert formulas == [{"id": "formula_Transaction Month",
                             "name": "Transaction Month",
                             "expr": "start_of_month ( [T::d] )",
                             "properties": {"column_type": "ATTRIBUTE"}}]

    def test_physical_measure_column_keeps_mapped_aggregation(self):
        cols, _, _ = build_columns_and_formulas(
            [_t("avg_price", "column", "MEASURE", table="T", column="price",
                aggregation="AVERAGE")], None)
        assert cols[0]["properties"] == {"column_type": "MEASURE",
                                         "aggregation": "AVERAGE"}

    def test_filter_entry_appended_last(self):
        cols, formulas, _ = build_columns_and_formulas(
            [_t("region", "column", "ATTRIBUTE", table="T", column="region")],
            {"name": "MV Filter", "column_type": "ATTRIBUTE",
             "ts_expr": "[T::status] != 'cancelled'"})
        assert formulas[-1] == {"id": "formula_MV Filter", "name": "MV Filter",
                                "expr": "[T::status] != 'cancelled'",
                                "properties": {"column_type": "ATTRIBUTE"}}
        assert cols[-1] == {"name": "MV Filter", "formula_id": "formula_MV Filter",
                            "properties": {"column_type": "ATTRIBUTE"}}

    def test_column_formula_name_clash_drops_physical_column(self):
        # a direct dim titled "Status" AND a formula titled "Status":
        # resolve_name_collisions keeps the formula, drops the physical column.
        cols, formulas, _ = build_columns_and_formulas(
            [_t("status", "column", "ATTRIBUTE", table="T", column="status"),
             _t("status_flag", "formula", "ATTRIBUTE", ts_expr="[T::x] = 1",
                display_name="Status")], None)
        assert [f["name"] for f in formulas] == ["Status"]
        assert [c["name"] for c in cols] == ["Status"]           # the paired entry only
        assert "formula_id" in cols[0] and "column_id" not in cols[0]
        # BL-099 #2 — the shadowed physical column never reaches columns[], so
        # the duplicate-title guard must NOT fire on this already-resolved case.
        _check_no_duplicate_display_names(cols)

    def test_paired_columns_survive_collision_pass(self):
        # regression for the sequencing trap: N formulas in, N paired columns out.
        entries = [_t(f"m{i}", "formula", "MEASURE", ts_expr=f"sum ( [T::c{i}] )",
                      aggregation="SUM") for i in range(3)]
        cols, formulas, _ = build_columns_and_formulas(entries, None)
        assert len(formulas) == 3 and len(cols) == 3

    def test_double_aggregation_fixed_via_shared_helper(self):
        # a formula referencing another already-aggregated formula gets unwrapped
        entries = [
            _t("base", "formula", "MEASURE", ts_expr="sum ( [T::a] )",
               aggregation="SUM", display_name="Base"),
            _t("wrapped", "formula", "MEASURE", ts_expr="sum ( [Base] )",
               aggregation="SUM", display_name="Wrapped"),
        ]
        _, formulas, _ = build_columns_and_formulas(entries, None)
        by_name = {f["name"]: f for f in formulas}
        assert by_name["Wrapped"]["expr"] == "[formula_Base]"

    def test_duplicate_dimension_display_titles_fail_loud(self):
        # BL-099 #2 — two physical dimensions with the same display_name must
        # not silently emit duplicate columns[] names. `ts tml lint` I8 (unique
        # column_id) can't catch this: column_id ("T1::REGION_A" vs.
        # "T1::REGION_B") differs even though the display name collides.
        columns, _, _ = build_columns_and_formulas(
            [_t("region_a", "column", "ATTRIBUTE", table="T1", column="REGION_A",
                display_name="Region"),
             _t("region_b", "column", "ATTRIBUTE", table="T1", column="REGION_B",
                display_name="Region")], None)
        with pytest.raises(ValueError, match=r"(?i)duplicate.*Region"):
            _check_no_duplicate_display_names(columns)


def _join(alias, source_raw, *, on=None, using=None, cardinality="many_to_one", joins=None):
    return {"alias": alias, "source": {"kind": "table_fqn", "raw": source_raw,
                                       "parts": source_raw.split("."),
                                       "needs_live_check": True},
            "on": on, "using": using, "parent": "source",
            "cardinality": cardinality, "cardinality_source": "default",
            "joins": joins or []}


NESTED = [_join("orders", "c.s.dm_order", on="source.ORDER_ID = orders.ORDER_ID",
                joins=[_join("customers", "c.s.dm_customer",
                             on="orders.CUSTOMER_ID = customers.CUSTOMER_ID")])]
TABLES3 = {"source": {"name": "FACT_SALES", "fqn": "g-fact"},
           "orders": {"name": "DM_ORDER", "fqn": "g-ord"},
           "orders.customers": {"name": "DM_CUSTOMER", "fqn": "g-cust"}}


class TestFlattenJoinAliases:
    def test_nested_paths(self):
        triples = flatten_join_aliases(NESTED)
        assert [(a, p) for a, p, _ in triples] == [
            ("orders", "source"), ("orders.customers", "orders")]


class TestBuildModelTables:
    def test_single_table_no_id_no_joins(self):
        parsed = {"source": {"kind": "table_fqn", "raw": "a.e.t"}, "joins": []}
        out = build_model_tables(parsed, {"source": {"name": "TRANSACTIONS",
                                                     "fqn": "{table_guid}"}})
        assert out == [{"name": "TRANSACTIONS", "fqn": "{table_guid}"}]

    def test_multi_table_ids_joins_cardinality(self):
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": NESTED}
        out = build_model_tables(parsed, TABLES3)
        assert [t["name"] for t in out] == ["FACT_SALES", "DM_ORDER", "DM_CUSTOMER"]
        assert all(t["id"] == t["name"] for t in out)
        assert out[0]["joins"] == [{
            "name": "fact_to_orders", "with": "DM_ORDER",
            "on": "[FACT_SALES::ORDER_ID] = [DM_ORDER::ORDER_ID]",
            "type": "INNER", "cardinality": "MANY_TO_ONE"}]
        assert out[1]["joins"][0]["name"] == "orders_to_customers"
        assert out[1]["joins"][0]["on"] == (
            "[DM_ORDER::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]")
        assert "joins" not in out[2]

    def test_using_join_and_one_to_many(self):
        joins = [_join("orders", "c.s.dm_order", using=["ORDER_ID", "REGION_ID"],
                       cardinality="one_to_many")]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        out = build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})
        j = out[0]["joins"][0]
        assert j["on"] == ("[FACT::ORDER_ID] = [DM_ORDER::ORDER_ID] AND "
                           "[FACT::REGION_ID] = [DM_ORDER::REGION_ID]")
        assert j["cardinality"] == "ONE_TO_MANY"

    def test_unknown_alias_in_on_raises(self):
        joins = [_join("orders", "c.s.dm_order", on="source.ID = warehouse.ID")]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        with pytest.raises(ValueError, match="warehouse"):
            build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})

    def test_on_with_ge_operator_raises(self):
        # `>=` contains `=` — split("=") would silently produce a malformed
        # ref like `[FACT::QTY >]` if not guarded against.
        joins = [_join("orders", "c.s.dm_order", on="source.QTY >= orders.QTY")]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        with pytest.raises(ValueError, match="not a simple equality"):
            build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})

    def test_on_with_ne_operator_raises(self):
        joins = [_join("orders", "c.s.dm_order", on="source.STATUS != orders.STATUS")]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        with pytest.raises(ValueError, match="not a simple equality"):
            build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})

    def test_on_with_null_safe_eq_operator_raises(self):
        joins = [_join("orders", "c.s.dm_order", on="source.ID <=> orders.ID")]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        with pytest.raises(ValueError, match="not a simple equality"):
            build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})

    def test_missing_on_and_using_raises(self):
        joins = [_join("orders", "c.s.dm_order", on=None, using=None)]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        with pytest.raises(ValueError, match="neither"):
            build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})

    def test_empty_using_list_raises(self):
        joins = [_join("orders", "c.s.dm_order", using=[])]
        parsed = {"source": {"kind": "table_fqn", "raw": "c.s.fact"}, "joins": joins}
        with pytest.raises(ValueError, match="neither"):
            build_model_tables(parsed, {"source": "FACT", "orders": "DM_ORDER"})


class TestBuildDescription:
    def test_comment_fqn_filter(self):
        assert build_description("Metrics.", "a.e.mv", True) == (
            "Metrics. Converted from Databricks Metric View a.e.mv. "
            "MV Filter applied automatically via model filter.")

    def test_no_comment_falls_back(self):
        assert build_description(None, "a.e.mv", False) == (
            "Converted from Databricks Metric View a.e.mv.")

    def test_nothing_known(self):
        assert build_description(None, None, False) == (
            "Converted from a Databricks Metric View.")


class TestBuildModelTmlDbx:
    PARSED = {"version": "1.1", "comment": "Metrics.",
              "source": {"kind": "table_fqn", "raw": "a.e.t"},
              "joins": [], "filter": "status != 'cancelled'",
              "materialization": None, "warnings": [], "unsupported": []}
    TRANSLATED = {
        "translated": [
            {"name": "region", "role": "dimension", "output_kind": "column",
             "column_type": "ATTRIBUTE", "table": "T", "column": "region",
             "ts_expr": None, "aggregation": None, "inlined_refs": [],
             "display_name": None, "comment": None, "synonyms": [], "format": None,
             "annotations": []},
            {"name": "rev_7d", "role": "measure", "output_kind": "formula",
             "column_type": "MEASURE", "table": None, "column": None,
             "ts_expr": "moving_sum ( [T::a] , 7 , -1 , [T::d] )",
             "aggregation": "SUM", "inlined_refs": [], "display_name": "Rev 7d",
             "comment": None, "synonyms": [], "format": None,
             "annotations": [{"kind": "sparse_data_risk", "detail": "E1"}]}],
        "skipped": [], "filter": {"name": "MV Filter", "column_type": "ATTRIBUTE",
                                  "ts_expr": "[T::status] != 'cancelled'"},
        "dependency_dag": {}, "window_measures": ["rev_7d"],
        "stats": {"total": 3, "translated": 3, "skipped": 0}}

    def test_document_shape_and_filters_block(self):
        doc, info = build_model_tml_dbx(
            model_name="M", parsed=self.PARSED, translated_doc=self.TRANSLATED,
            tables={"source": {"name": "T", "fqn": "g"}}, mv_fqn="a.e.mv")
        model = doc["model"]
        assert set(doc) == {"model"}
        assert model["name"] == "M"
        assert model["filters"] == [{"column": ["MV Filter"], "oper": "in",
                                     "values": ["true"]}]
        assert model["properties"] == {"is_bypass_rls": False,
                                       "join_progressive": True}
        assert info["filter_applied"] is True
        assert info["window_measures"] == [{
            "name": "Rev 7d", "mv_name": "rev_7d",
            "ts_expr": "moving_sum ( [T::a] , 7 , -1 , [T::d] )",
            "annotations": [{"kind": "sparse_data_risk", "detail": "E1"}]}]

    def test_existing_guid_stamped_at_root(self):
        doc, _ = build_model_tml_dbx(
            model_name="M", parsed=self.PARSED, translated_doc=self.TRANSLATED,
            tables={"source": "T"}, existing_guid="g-123")
        assert doc["guid"] == "g-123" and "guid" not in doc["model"]

    def test_spotter_config(self):
        doc, _ = build_model_tml_dbx(
            model_name="M", parsed=self.PARSED, translated_doc=self.TRANSLATED,
            tables={"source": "T"}, spotter_enabled=True)
        assert doc["model"]["properties"]["spotter_config"] == {
            "is_spotter_enabled": True}
        doc2, _ = build_model_tml_dbx(
            model_name="M", parsed=self.PARSED, translated_doc=self.TRANSLATED,
            tables={"source": "T"}, spotter_enabled=None)
        assert "spotter_config" not in doc2["model"]["properties"]

    def test_no_filter_no_filters_block(self):
        translated = dict(self.TRANSLATED, filter=None)
        parsed = dict(self.PARSED, filter=None)
        doc, info = build_model_tml_dbx(
            model_name="M", parsed=parsed, translated_doc=translated,
            tables={"source": "T"})
        assert "filters" not in doc["model"]
        assert info["filter_applied"] is False

    def test_alias_missing_from_tables_raises(self):
        parsed = dict(self.PARSED, joins=NESTED)
        with pytest.raises(ValueError, match="orders"):
            build_model_tml_dbx(model_name="M", parsed=parsed,
                                translated_doc=self.TRANSLATED,
                                tables={"source": "T"})

    def test_duplicate_formula_display_title_raises(self):
        # two measures whose display_name collides once titled — resolve_name_
        # collisions only covers formula-vs-parameter and column-vs-formula
        # clashes, not formula-vs-formula, so build_model_tml_dbx must fail
        # loud (via _check_no_duplicate_display_names, BL-099 #2) rather than
        # silently emit two formulas[]/columns[] entries with the same `name`
        # (which ThoughtSpot import would reject or silently mangle).
        translated = dict(self.TRANSLATED, translated=[
            {"name": "rev_7d", "role": "measure", "output_kind": "formula",
             "column_type": "MEASURE", "table": None, "column": None,
             "ts_expr": "moving_sum ( [T::a] , 7 , -1 , [T::d] )",
             "aggregation": "SUM", "inlined_refs": [], "display_name": "Revenue",
             "comment": None, "synonyms": [], "format": None, "annotations": []},
            {"name": "rev_30d", "role": "measure", "output_kind": "formula",
             "column_type": "MEASURE", "table": None, "column": None,
             "ts_expr": "moving_sum ( [T::a] , 30 , -1 , [T::d] )",
             "aggregation": "SUM", "inlined_refs": [], "display_name": "Revenue",
             "comment": None, "synonyms": [], "format": None, "annotations": []},
        ], window_measures=[])
        parsed = dict(self.PARSED, filter=None)
        translated = dict(translated, filter=None)
        with pytest.raises(ValueError, match=r"(?i)duplicate display title.*Revenue"):
            build_model_tml_dbx(model_name="M", parsed=parsed,
                                translated_doc=translated,
                                tables={"source": "T"})


# --- ts databricks build-model CLI (BL-063 PR4 Task 5) --------------------

PARSED_MIN = {"version": "1.1", "comment": "Metrics.",
              "source": {"kind": "table_fqn", "raw": "a.e.t", "parts": ["a", "e", "t"],
                         "needs_live_check": True},
              "joins": [], "filter": None, "materialization": None,
              "warnings": [], "unsupported": []}
TRANSLATED_MIN = {"translated": [
    {"name": "region", "role": "dimension", "output_kind": "column",
     "column_type": "ATTRIBUTE", "table": "T", "column": "region", "ts_expr": None,
     "aggregation": None, "inlined_refs": [], "display_name": None, "comment": None,
     "synonyms": [], "format": None, "annotations": []}],
    "skipped": [], "filter": None, "dependency_dag": {}, "window_measures": [],
    "stats": {"total": 1, "translated": 1, "skipped": 0}}


def _write_build_inputs(tmp_path, parsed=None, translated=None, tables=None):
    (tmp_path / "parsed.json").write_text(json.dumps(parsed or PARSED_MIN))
    (tmp_path / "translated.json").write_text(json.dumps(translated or TRANSLATED_MIN))
    (tmp_path / "tables.json").write_text(json.dumps(tables or {"source": "T"}))
    return tmp_path


class TestBuildModelCommand:
    def _run(self, tmp_path, *extra):
        runner = CliRunner()
        args = ["databricks", "build-model",
                "--parsed", str(tmp_path / "parsed.json"),
                "--translated", str(tmp_path / "translated.json"),
                "--tables", str(tmp_path / "tables.json"),
                "--connection", "Databricks Analytics",
                "--model-name", "M",
                "--output-dir", str(tmp_path / "out"), *extra]
        return runner.invoke(app, args)

    def test_writes_model_tml_and_summary(self, tmp_path):
        result = self._run(_write_build_inputs(tmp_path))
        assert result.exit_code == 0, result.output
        summary = json.loads(result.stdout)
        assert summary["model_name"] == "M"
        assert summary["import_status"] == "not_requested"
        assert summary["lint_findings"] == [] and summary["invariant_findings"] == []
        model_file = tmp_path / "out" / "M.model.tml"
        assert model_file.exists()
        import yaml
        doc = yaml.safe_load(model_file.read_text())
        assert doc["model"]["name"] == "M"

    def test_stdout_is_pure_json(self, tmp_path):
        result = self._run(_write_build_inputs(tmp_path))
        json.loads(result.stdout)  # raises if any diagnostic leaked to stdout

    def test_table_tml_written_for_create_true(self, tmp_path):
        tables = {"source": {"name": "T", "create": True, "db": "a", "schema": "e",
                             "db_table": "t",
                             "columns": [{"name": "region", "dbx_type": "string"}]}}
        result = self._run(_write_build_inputs(tmp_path, tables=tables))
        assert result.exit_code == 0, result.output
        assert (tmp_path / "out" / "T.table.tml").exists()
        summary = json.loads(result.stdout)
        assert summary["table_files"] == [str(tmp_path / "out" / "T.table.tml")]

    def test_existing_guid_at_document_root(self, tmp_path):
        result = self._run(_write_build_inputs(tmp_path), "--existing-guid", "g-1")
        assert result.exit_code == 0, result.output
        import yaml
        doc = yaml.safe_load((tmp_path / "out" / "M.model.tml").read_text())
        assert doc["guid"] == "g-1" and "guid" not in doc["model"]

    def test_lint_finding_exits_1_but_writes_files(self, tmp_path):
        # duplicate column_id triggers lint I8
        bad = dict(TRANSLATED_MIN)
        bad["translated"] = TRANSLATED_MIN["translated"] + [dict(
            TRANSLATED_MIN["translated"][0], name="region2", display_name="Region 2")]
        result = self._run(_write_build_inputs(tmp_path, translated=bad))
        assert result.exit_code == 1
        summary = json.loads(result.stdout)
        assert summary["lint_findings"]
        assert (tmp_path / "out" / "M.model.tml").exists()

    def test_missing_input_exits_1(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(app, ["databricks", "build-model",
                                     "--parsed", str(tmp_path / "nope.json"),
                                     "--translated", str(tmp_path / "nope.json"),
                                     "--tables", str(tmp_path / "nope.json"),
                                     "--connection", "C", "--model-name", "M",
                                     "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1

    def test_dry_run_with_profile_skips_import(self, tmp_path, monkeypatch):
        import subprocess as sp
        def boom(*a, **k):
            raise AssertionError("subprocess must not run under --dry-run")
        monkeypatch.setattr(sp, "run", boom)
        result = self._run(_write_build_inputs(tmp_path),
                           "--profile", "p", "--dry-run")
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["import_status"] == "dry_run"

    def test_import_invokes_tml_import_with_stdin(self, tmp_path, monkeypatch):
        import subprocess as sp
        calls = {}
        class FakeCompleted:
            returncode = 0
            # Real extract_imported_guid shape (ts_cli/tableau/build_model.py:274):
            # import_result[0]["response"]["object"][0]["header"]["id_guid"].
            stdout = json.dumps([{"response": {"object": [
                {"header": {"id_guid": "new-guid"}}]}}])
            stderr = ""
        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["input"] = kwargs.get("input")
            return FakeCompleted()
        monkeypatch.setattr(sp, "run", fake_run)
        result = self._run(_write_build_inputs(tmp_path), "--profile", "p")
        assert result.exit_code == 0, result.output
        assert "ts tml import" in " ".join(calls["cmd"])
        assert calls["input"] is not None            # BL-097: stdin always provided
        summary = json.loads(result.stdout)
        assert summary["import_status"] == "imported"
        assert summary["model_guid"] == "new-guid"

    def test_import_failure_exits_1_with_error_detail(self, tmp_path, monkeypatch):
        import subprocess as sp
        class FakeCompleted:
            returncode = 1
            stdout = ""
            stderr = "Error: connection refused"
        monkeypatch.setattr(sp, "run", lambda cmd, **kwargs: FakeCompleted())
        result = self._run(_write_build_inputs(tmp_path), "--profile", "p")
        assert result.exit_code == 1
        summary = json.loads(result.stdout)
        assert summary["import_status"] == "failed"
        assert "connection refused" in summary["import_error"]

    def test_in_band_error_status_surfaced_even_when_returncode_zero(self, tmp_path, monkeypatch):
        # Live finding, BL-063 PR4 (2026-07-10, se-thoughtspot): `ts tml
        # import` exited 0, but the response body carried
        # status.status_code == "ERROR" with a rich, HTML-laden
        # error_message — previously swallowed as import_error: "".
        import subprocess as sp
        class FakeCompleted:
            returncode = 0
            stdout = json.dumps([{"response": {
                "status": {"status_code": "ERROR",
                           "error_message": "<p>Could not find column <b>REGION</b> "
                                             "— tables belong to different "
                                             "connections</p>"},
                "object": []}}])
            stderr = ""
        monkeypatch.setattr(sp, "run", lambda cmd, **kwargs: FakeCompleted())
        result = self._run(_write_build_inputs(tmp_path), "--profile", "p")
        assert result.exit_code == 1
        summary = json.loads(result.stdout)
        assert summary["import_status"] == "failed"
        assert summary["model_guid"] is None
        assert summary["import_error"]  # non-empty — the original live bug
        assert "<" not in summary["import_error"] and ">" not in summary["import_error"]
        assert "Could not find column REGION" in summary["import_error"]
        assert "different connections" in summary["import_error"]

    def test_ok_status_but_no_guid_gets_synthesized_error(self, tmp_path, monkeypatch):
        # Live finding, BL-063 PR4 (2026-07-10, se-thoughtspot): import
        # succeeded (rc 0, status OK) but GUID extraction failed (the
        # Defect-1 flat-response-shape bug) — previously swallowed as
        # import_status: "failed", import_error: "".
        import subprocess as sp
        class FakeCompleted:
            returncode = 0
            stdout = json.dumps([{"response": {
                "status": {"status_code": "OK"}, "object": []}}])
            stderr = ""
        monkeypatch.setattr(sp, "run", lambda cmd, **kwargs: FakeCompleted())
        result = self._run(_write_build_inputs(tmp_path), "--profile", "p")
        assert result.exit_code == 1
        summary = json.loads(result.stdout)
        assert summary["import_status"] == "failed"
        assert summary["model_guid"] is None
        assert summary["import_error"]  # non-empty — the original live bug
        assert "no GUID found" in summary["import_error"]

    def test_zero_column_table_guard_exits_1_before_writing(self, tmp_path):
        # Every column in this create:true table maps to an unsupported
        # Databricks type — build_table_tml omits all of them, leaving an
        # empty columns[] list. That must be a hard error, not a table.tml
        # with no columns, and must fail before any file is written.
        tables = {"source": {"name": "T", "create": True, "db": "a", "schema": "e",
                             "db_table": "t",
                             "columns": [{"name": "raw_payload", "dbx_type": "binary"},
                                         {"name": "tags", "dbx_type": "array<string>"}]}}
        result = self._run(_write_build_inputs(tmp_path, tables=tables))
        assert result.exit_code == 1
        assert "T" in result.output and "zero columns" in result.output
        assert "raw_payload" in result.output and "tags" in result.output
        assert not (tmp_path / "out" / "T.table.tml").exists()
        assert not (tmp_path / "out" / "M.model.tml").exists()


# --- Golden acceptance tests — both shared worked examples (BL-063 PR4 Task 6) ---
#
# Fixtures below are copied VERBATIM from the two worked-example docs at
# implementation time (repo convention: no on-disk fixture directories):
#   agents/shared/worked-examples/databricks/ts-from-databricks.md
#   agents/shared/worked-examples/databricks/ts-from-databricks-sql-view.md
#
# Semantic equality only (yaml.safe_load), never byte equality or hand-
# normalization of folded scalars — the worked examples are ground truth
# (agents/shared/CLAUDE.md). On mismatch, fix the builder, never the doc.


class TestGoldenEcommerce:
    """Pins agents/shared/worked-examples/databricks/ts-from-databricks.md.

    Semantic equality (yaml.safe_load), not byte equality — TML meaning,
    not YAML style. The worked example is ground truth; on mismatch fix
    the builder, never the doc (agents/shared/CLAUDE.md).
    """

    MV_YAML = """\
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

    EXPECTED_TABLE_TML = """\
table:
  name: TRANSACTIONS
  db: analytics
  schema: ecommerce
  db_table: transactions
  connection:
    name: "Databricks Analytics"
  columns:
  - name: transaction_id
    db_column_name: transaction_id
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: product_category
    db_column_name: product_category
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: transaction_date
    db_column_name: transaction_date
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: DATE
  - name: customer_region
    db_column_name: customer_region
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: customer_id
    db_column_name: customer_id
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: unit_price
    db_column_name: unit_price
    properties:
      column_type: MEASURE
      aggregation: SUM
    db_column_properties:
      data_type: DOUBLE
  - name: quantity
    db_column_name: quantity
    properties:
      column_type: MEASURE
      aggregation: SUM
    db_column_properties:
      data_type: INT64
  - name: discount
    db_column_name: discount
    properties:
      column_type: MEASURE
      aggregation: SUM
    db_column_properties:
      data_type: DOUBLE
  - name: status
    db_column_name: status
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
"""

    EXPECTED_MODEL_TML = """\
model:
  name: Transactions_MV_Model
  description: >-
    E-commerce transaction metrics — revenue, customer counts, order value,
    and return analysis on the transactions table.
    Converted from Databricks Metric View analytics.ecommerce.ecommerce_transactions_mv.
    MV Filter applied automatically via model filter.
  model_tables:
  - name: TRANSACTIONS
    fqn: "{table_guid}"
  formulas:
  - id: formula_Transaction Month
    name: "Transaction Month"
    expr: "start_of_month ( [TRANSACTIONS::transaction_date] )"
    properties:
      column_type: ATTRIBUTE
  - id: formula_Total Revenue
    name: "Total Revenue"
    expr: "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] ) )"
  - id: formula_Unique Customers
    name: "Unique Customers"
    expr: "unique count ( [TRANSACTIONS::customer_id] )"
  - id: formula_Avg Order Value
    name: "Avg Order Value"
    expr: "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) / unique count ( [TRANSACTIONS::transaction_id] )"
  - id: formula_High Value Revenue
    name: "High Value Revenue"
    expr: "sum_if ( [TRANSACTIONS::unit_price] > 100 , [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] )"
  - id: "formula_7-Day Rolling Revenue"
    name: "7-Day Rolling Revenue"
    expr: "moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , -1 , [TRANSACTIONS::transaction_date] )"
  - id: formula_Return Rate
    name: "Return Rate"
    expr: "sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) ) / count ( 1 )"
  - id: "formula_MV Filter"
    name: "MV Filter"
    expr: "[TRANSACTIONS::status] != 'cancelled'"
    properties:
      column_type: ATTRIBUTE
  columns:
  - name: "Transaction Id"
    column_id: TRANSACTIONS::transaction_id
    properties:
      column_type: ATTRIBUTE
  - name: "Product Category"
    column_id: TRANSACTIONS::product_category
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - "category"
      - "product type"
      synonym_type: USER_DEFINED
  - name: "Transaction Month"
    formula_id: formula_Transaction Month
    properties:
      column_type: ATTRIBUTE
  - name: "Region"
    column_id: TRANSACTIONS::customer_region
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - "area"
      - "territory"
      synonym_type: USER_DEFINED
  - name: "Transaction Date"
    column_id: TRANSACTIONS::transaction_date
    properties:
      column_type: ATTRIBUTE
  - name: "Total Revenue"
    formula_id: formula_Total Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Net revenue after discount."
      synonyms:
      - "revenue"
      - "sales"
      synonym_type: USER_DEFINED
  - name: "Unique Customers"
    formula_id: formula_Unique Customers
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Distinct customer count."
  - name: "Avg Order Value"
    formula_id: formula_Avg Order Value
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Average revenue per transaction."
      synonyms:
      - "AOV"
      synonym_type: USER_DEFINED
  - name: "High Value Revenue"
    formula_id: formula_High Value Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Revenue from items priced above 100."
  - name: "7-Day Rolling Revenue"
    formula_id: "formula_7-Day Rolling Revenue"
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Trailing 7-day rolling sum of gross revenue."
  - name: "Return Rate"
    formula_id: formula_Return Rate
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Fraction of transactions that were returned."
  - name: "MV Filter"
    formula_id: "formula_MV Filter"
    properties:
      column_type: ATTRIBUTE
  filters:
  - column:
    - "MV Filter"
    oper: in
    values:
    - "true"
  properties:
    is_bypass_rls: false
    join_progressive: true
"""

    TABLES = {"source": {
        "name": "TRANSACTIONS", "fqn": "{table_guid}", "create": True,
        "db": "analytics", "schema": "ecommerce", "db_table": "transactions",
        "columns": [
            {"name": "transaction_id", "dbx_type": "string"},
            {"name": "product_category", "dbx_type": "string"},
            {"name": "transaction_date", "dbx_type": "date"},
            {"name": "customer_region", "dbx_type": "string"},
            {"name": "customer_id", "dbx_type": "string"},
            {"name": "unit_price", "dbx_type": "double"},
            {"name": "quantity", "dbx_type": "bigint"},
            {"name": "discount", "dbx_type": "double"},
            {"name": "status", "dbx_type": "string"},
        ]}}

    def _build(self):
        parsed = parse_metric_view(self.MV_YAML)
        assert parsed["unsupported"] == []
        translated = translate_metric_view(parsed, self.TABLES)
        assert translated["skipped"] == []
        doc, info = build_model_tml_dbx(
            model_name="Transactions_MV_Model", parsed=parsed,
            translated_doc=translated, tables=self.TABLES,
            mv_fqn="analytics.ecommerce.ecommerce_transactions_mv")
        return doc, info

    def test_model_tml_matches_worked_example(self):
        doc, _ = self._build()
        assert doc == yaml.safe_load(self.EXPECTED_MODEL_TML)

    def test_table_tml_matches_worked_example(self):
        doc, notes = build_table_tml(self.TABLES["source"], "Databricks Analytics")
        assert notes == []
        assert doc == yaml.safe_load(self.EXPECTED_TABLE_TML)

    def test_window_measures_surfaced(self):
        _, info = self._build()
        assert [w["mv_name"] for w in info["window_measures"]] == ["revenue_7d_rolling"]
        assert any(a["kind"] == "sparse_data_risk"
                   for a in info["window_measures"][0]["annotations"])


class TestGoldenSqlView:
    """Pins agents/shared/worked-examples/databricks/ts-from-databricks-sql-view.md.

    The MV's `source:` is a SELECT subquery, so the user-chosen option (T)
    builds a ThoughtSpot SQL View from that subquery and the MV's own
    `filter:` gets baked into the SQL View's `sql_query` WHERE clause at
    Step 5T of the doc — it never survives as a Model-level filter. That
    means the inputs fed to translate/build here are NOT a literal re-parse
    of the MV YAML: `filter` is nulled before translation (mirroring the
    Step 5T consumption) and `comment` is set to the doc's own bespoke
    Model-description prose (this MV has no top-level `comment:`, and the
    description text describing the SQL-View path is composed by the skill
    step that builds the SQL View — see doc Step 6 "Key points"). Passed
    through build_description's comment-only branch (mv_fqn=None,
    has_filter=False), `comment.strip()` alone reproduces the doc's
    description verbatim — no generator change needed for this path.

    RESOLVED (BL-063 PR4 Task 6 fix round 1, 2026-07-10): the doc originally
    diverged from the already-shipped, already-tested conventions the
    ecommerce golden pins on two stylistic (not semantic) points — a
    controller decision aligned the doc to the canonical style rather than
    changing the generator:

    1. Title-case fallback. `order_id` has no `display_name`. The doc's
       "Key points" now says the bare `name:` is title-cased -> `Order Id`,
       matching ts-from-databricks.md's Key Pattern #3 ("When absent,
       title-case the `name` field") and the pre-existing
       TestDisplayTitle.test_title_case_fallback (Task 3) / TestGoldenEcommerce
       above. ts-from-databricks-rules.md line 139 ("name: use display_name
       (or name if no display_name)") does not specify a case transform
       either way, so this was a style choice, not a rule conflict.
    2. `formulas[]` `properties.column_type` for an ATTRIBUTE-kind formula.
       `formula_Customer Segment` now carries `properties: {column_type:
       ATTRIBUTE}`, matching the ecommerce doc's `formula_Transaction Month`
       / `formula_MV Filter` (also ATTRIBUTE-kind).
       agents/shared/schemas/thoughtspot-model-tml.md:193 documents this
       field as OPTIONAL on formulas[] — both renderings were valid TML;
       the doc was updated to the canonical (explicit) form for consistency
       across worked examples.

    Neither change affects import semantics or numbers — the doc's
    "verified 2026-05-28" live-verification claim stands; see the doc's own
    "Style aligned 2026-07-10" note.
    """

    MV_YAML = """\
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

    EXPECTED_MODEL_TML = """\
model:
  name: Orders_MV_Model
  description: "Converted from Databricks Metric View. Source: select * from analytics.sales.orders. Filter baked into SQL View WHERE clause."
  model_tables:
  - name: Orders_MV_View
    fqn: "11111111-2222-3333-4444-555555555555"
  formulas:
  - id: formula_Customer Segment
    name: Customer Segment
    expr: "if ( [Orders_MV_View::total_amount] > 1000 , 'Premium' , if ( [Orders_MV_View::total_amount] > 100 , 'Standard' , 'Basic' ) )"
    properties:
      column_type: ATTRIBUTE
  - id: formula_Total Orders
    name: Total Orders
    expr: "count ( 1 )"
  - id: formula_Avg Order Amount
    name: Avg Order Amount
    expr: "sum ( [Orders_MV_View::total_amount] ) / unique count ( [Orders_MV_View::order_id] )"
  columns:
  - name: Order Id
    column_id: Orders_MV_View::order_id
    properties:
      column_type: ATTRIBUTE
  - name: Order Date
    column_id: Orders_MV_View::order_date
    properties:
      column_type: ATTRIBUTE
  - name: Order Status
    column_id: Orders_MV_View::order_status
    properties:
      column_type: ATTRIBUTE
  - name: Customer Segment
    formula_id: formula_Customer Segment
    properties:
      column_type: ATTRIBUTE
  - name: Total Orders
    formula_id: formula_Total Orders
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  - name: Total Amount
    column_id: Orders_MV_View::total_amount
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Avg Order Amount
    formula_id: formula_Avg Order Amount
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  properties:
    is_bypass_rls: false
    join_progressive: true
"""

    TABLES = {"source": {"name": "Orders_MV_View",
                         "fqn": "11111111-2222-3333-4444-555555555555"}}

    DESCRIPTION = ("Converted from Databricks Metric View. Source: select * "
                   "from analytics.sales.orders. Filter baked into SQL View "
                   "WHERE clause.")

    def _build(self):
        parsed = parse_metric_view(self.MV_YAML)
        assert parsed["unsupported"] == []
        # Step 5T: filter consumed into the SQL View's sql_query — does not
        # survive to translate/build as a Model-level filter.
        parsed_for_pipeline = dict(parsed, filter=None)
        translated = translate_metric_view(parsed_for_pipeline, self.TABLES)
        assert translated["skipped"] == []
        parsed_for_model = dict(parsed_for_pipeline, comment=self.DESCRIPTION)
        doc, info = build_model_tml_dbx(
            model_name="Orders_MV_Model", parsed=parsed_for_model,
            translated_doc=translated, tables=self.TABLES)
        return doc, info

    def test_model_tml_matches_worked_example(self):
        doc, _ = self._build()
        assert doc == yaml.safe_load(self.EXPECTED_MODEL_TML)

    def test_no_filter_block(self):
        doc, info = self._build()
        assert "filters" not in doc["model"]
        assert info["filter_applied"] is False
