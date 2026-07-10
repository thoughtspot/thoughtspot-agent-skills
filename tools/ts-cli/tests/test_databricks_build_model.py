"""Tests for ts_cli/databricks/mv_tml.py and mv_build_model.py.

One class per transform, mirroring test_model_builder.py. Golden classes pin
the shared worked examples (see TestGoldenEcommerce/TestGoldenSqlView, Task 6).
"""
import pytest

from ts_cli.databricks.mv_build_model import (
    build_columns_and_formulas,
    build_description,
    build_model_tables,
    build_model_tml_dbx,
    display_title,
    flatten_join_aliases,
)
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
        # loud rather than silently emit two formulas[] entries with the same
        # `name` (which ThoughtSpot import would reject or silently mangle).
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
        with pytest.raises(ValueError, match=r"(?i)duplicate formula display title.*Revenue"):
            build_model_tml_dbx(model_name="M", parsed=parsed,
                                translated_doc=translated,
                                tables={"source": "T"})
