"""Tests for ts_cli/databricks/mv_tml.py and mv_build_model.py.

One class per transform, mirroring test_model_builder.py. Golden classes pin
the shared worked examples (see TestGoldenEcommerce/TestGoldenSqlView, Task 6).
"""
import pytest

from ts_cli.databricks.mv_build_model import build_columns_and_formulas, display_title
from ts_cli.databricks.mv_tml import (
    build_table_tml,
    map_dbx_type,
    validate_tml_invariants,
)


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
