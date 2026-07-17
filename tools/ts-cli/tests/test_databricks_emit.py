import pytest
from ts_cli.databricks.mv_emit import (
    build_column_index, make_col_resolver, classify_column,
    emit_dimension, emit_measure, emit_filter,
)
from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql

MODEL = {"model": {"name": "M",
    "model_tables": [{"name": "FACT"}],
    "columns": [
        {"name": "Amount", "column_id": "FACT::AMOUNT", "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}],
    "formulas": []}}
TABLES = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
    "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]

class TestColumnIndex:
    def test_physical_column_dot_path(self):
        idx = build_column_index(MODEL["model"], TABLES)
        assert idx["FACT::AMOUNT"]["dbx_type"] == "double"
        r = make_col_resolver(idx, source_table="FACT")
        assert emit_sql(parse_formula("sum ( [FACT::AMOUNT] )"), r) == "SUM(source.AMOUNT)"

    def test_unknown_column_raises(self):
        idx = build_column_index(MODEL["model"], TABLES)
        r = make_col_resolver(idx, source_table="FACT")
        with pytest.raises(UntranslatableError):
            emit_sql(parse_formula("sum ( [FACT::MISSING] )"), r)


class TestJoins:
    def test_single_join(self):
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "on": "[FACT::DIM_ID] = [DIM::ID]", "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": []}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        joins, dot = build_joins(model, tables, source_table="FACT")
        assert joins == [{"name": "dim", "source": "c.s.dim",
                          "on": "source.DIM_ID = dim.ID",
                          "rely": {"at_most_one_match": True},
                          "cardinality": "many_to_one"}]
        assert dot == {"FACT": "source", "DIM": "dim"}

    def test_two_level_nested_join(self):
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "on": "[FACT::DIM_ID] = [DIM::ID]", "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DIM", "joins": [
                    {"with": "SUBDIM", "on": "[DIM::SUBDIM_ID] = [SUBDIM::ID]", "type": "INNER"}]},
                {"name": "SUBDIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": []}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}},
            {"table": {"name": "SUBDIM", "db": "c", "schema": "s", "db_table": "subdim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        joins, dot = build_joins(model, tables, source_table="FACT")
        assert dot == {"FACT": "source", "DIM": "dim", "SUBDIM": "dim.subdim"}
        # SUBDIM is nested UNDER the "dim" join node's own "joins" list (per the
        # Metric View spec — nested joins are a child list, not flat siblings),
        # and its "on" references the parent's bare alias ("dim"), not the full
        # dot path ("dim.subdim").
        assert joins == [
            {"name": "dim", "source": "c.s.dim",
             "on": "source.DIM_ID = dim.ID",
             "rely": {"at_most_one_match": True},
             "cardinality": "many_to_one",
             "joins": [
                 {"name": "subdim", "source": "c.s.subdim",
                  "on": "dim.SUBDIM_ID = subdim.ID",
                  "rely": {"at_most_one_match": True}}]}]

    def test_referencing_join_missing_raises(self):
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "referencing_join": "fk_dim", "type": "INNER"}]},
                {"name": "DIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": []}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        with pytest.raises(Exception):
            build_joins(model, tables, source_table="FACT")

    def test_referencing_join_resolved_from_source_table(self):
        # Scenario A happy path: the model's join only carries `with` +
        # `referencing_join` (no inline `on`). Per the schema
        # (thoughtspot-model-tml.md "Join Scenarios" Scenario A;
        # thoughtspot-table-tml.md `joins_with[]` field reference), the named
        # join is defined on the SOURCE (FK) table's own Table TML
        # `joins_with[]` — not on the target table's TML.
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "referencing_join": "FACT_to_DIM", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": [],
                "joins_with": [
                    {"name": "FACT_to_DIM", "destination": {"name": "DIM"},
                     "on": "[FACT::DIM_ID] = [DIM::ID]", "type": "INNER", "cardinality": "MANY_TO_ONE"}]}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        joins, dot = build_joins(model, tables, source_table="FACT")
        assert joins == [{"name": "dim", "source": "c.s.dim",
                          "on": "source.DIM_ID = dim.ID",
                          "rely": {"at_most_one_match": True},
                          "cardinality": "many_to_one"}]
        assert dot == {"FACT": "source", "DIM": "dim"}


class TestClassifyColumn:
    def test_physical_measure(self):
        col = {"name": "Amount", "column_id": "FACT::AMOUNT",
               "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}
        result = classify_column(col, MODEL["model"])
        assert result["role"] == "measure"
        assert isinstance(result["reason"], str) and result["reason"]

    def test_physical_dimension(self):
        col = {"name": "Region", "column_id": "FACT::REGION",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, MODEL["model"])
        assert result["role"] == "dimension"

    def test_boolean_filter_formula(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_filter", "name": "MV Filter", "expr": "[FACT::STATUS] = 'Active'"}]}
        col = {"name": "MV Filter", "formula_id": "formula_filter",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "filter"

    def test_group_aggregate_routes_to_window(self):
        # LOD formula -> window (dimension window function, emitted in Task 9).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_lod", "name": "Category Quantity",
                 "expr": "group_aggregate ( sum ( [FACT::QTY] ) , { [FACT::CATEGORY] } , query_filters ( ) )"}]}
        col = {"name": "Category Quantity", "formula_id": "formula_lod",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_moving_sum_routes_to_window(self):
        # Window measure -> window (rolling/cumulative/semi-additive, Task 9).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_ms", "name": "Trailing 7 Day Amount",
                 "expr": "moving_sum ( [FACT::AMOUNT] , 7 , -1 , [FACT::ORDER_DATE] )"}]}
        col = {"name": "Trailing 7 Day Amount", "formula_id": "formula_ms",
               "properties": {"column_type": "MEASURE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_period_offset_sum_if_routes_to_window(self):
        # sum_if(diff_months(...) = N, [m]) -> window (period-offset, Task 9),
        # even though its top node is a plain *_if conditional aggregate.
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_pf", "name": "Current Month Amount",
                 "expr": "sum_if ( diff_months ( [FACT::ORDER_DATE] , today ( ) ) = 0 , [FACT::AMOUNT] )"}]}
        col = {"name": "Current Month Amount", "formula_id": "formula_pf",
               "properties": {"column_type": "MEASURE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_plain_sum_if_without_period_offset_is_measure(self):
        # A *_if formula whose condition does NOT contain diff_months/quarters/years
        # is a plain conditional-aggregate measure (Task 8 territory), not window.
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_cond", "name": "Active Amount",
                 "expr": "sum_if ( [FACT::STATUS] = 'Active' , [FACT::AMOUNT] )"}]}
        col = {"name": "Active Amount", "formula_id": "formula_cond",
               "properties": {"column_type": "MEASURE"}}
        result = classify_column(col, model)
        assert result["role"] == "measure"

    def test_non_boolean_attribute_formula_is_dimension(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_concat", "name": "Full Name",
                 "expr": "concat ( [FACT::FIRST] , [FACT::LAST] )"}]}
        col = {"name": "Full Name", "formula_id": "formula_concat",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "dimension"


class TestEmitMeasure:
    def test_physical_measure(self):
        idx = build_column_index(MODEL["model"], TABLES)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = MODEL["model"]["columns"][0]
        assert emit_measure(col, resolver) == {
            "name": "amount", "expr": "SUM(source.AMOUNT)", "display_name": "Amount"}

    def test_physical_measure_count_distinct(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Customer Count", "column_id": "FACT::ID",
                "properties": {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT"}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "ID", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        result = emit_measure(col, resolver)
        assert result["expr"] == "COUNT(DISTINCT source.ID)"

    def test_formula_measure_with_cross_ref_and_resolver(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_contrib", "name": "Contribution", "expr": "[Quantity]"}]}
        col = {"name": "Contribution", "formula_id": "formula_contrib",
               "properties": {"column_type": "MEASURE"}}
        idx = build_column_index(model, [])
        resolver = make_col_resolver(idx, source_table="FACT")

        def ref_resolver(node):
            if node["name"] == "Quantity":
                return "MEASURE(quantity)"
            raise UntranslatableError(f"unexpected ref {node['name']!r}")

        result = emit_measure(col, resolver, ref_resolver, model=model)
        assert result == {
            "name": "contribution", "expr": "MEASURE(quantity)", "display_name": "Contribution"}

    def test_formula_measure_without_ref_resolver_raises(self):
        # No ref_resolver provided -> the default sink raises, deferring
        # ref-bearing formulas to Task 10's role-aware resolver.
        model = {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [],
            "formulas": [{"id": "formula_x", "name": "X", "expr": "[Quantity]"}]}
        col = {"name": "X", "formula_id": "formula_x", "properties": {"column_type": "MEASURE"}}
        idx = build_column_index(model, [])
        resolver = make_col_resolver(idx, source_table="FACT")
        with pytest.raises(UntranslatableError):
            emit_measure(col, resolver, model=model)

    def test_formula_measure_without_refs_still_resolves(self):
        # A formula with no [ref] at all still passes through resolve_refs
        # unchanged (exercises the no-op path, not just the substitution path).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Amount", "column_id": "FACT::AMOUNT",
                "properties": {"column_type": "MEASURE"}}],
            "formulas": [{"id": "formula_sum", "name": "Total Amount",
                "expr": "sum ( [FACT::AMOUNT] )"}]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = {"name": "Total Amount", "formula_id": "formula_sum",
               "properties": {"column_type": "MEASURE"}}
        result = emit_measure(col, resolver, model=model)
        assert result["expr"] == "SUM(source.AMOUNT)"


class TestEmitDimension:
    def test_physical_dimension(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Region", "column_id": "FACT::REGION",
                "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        assert emit_dimension(col, resolver) == {
            "name": "region", "expr": "source.REGION", "display_name": "Region"}


class TestEmitFilter:
    def test_boolean_filter_formula(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Status", "column_id": "FACT::STATUS",
                "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": [{"id": "formula_filter", "name": "MV Filter",
                "expr": "[FACT::STATUS] = 'Active'"}]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "STATUS", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = {"name": "MV Filter", "formula_id": "formula_filter",
               "properties": {"column_type": "ATTRIBUTE"}}
        # NOTE: the mapping doc's illustrative row (ts-to-databricks-rules.md
        # "Filter Generation") shows the single-source, no-prefix form
        # `status = 'Active'`. This module resolves every column through the
        # source./alias. dot-path scheme established in Tasks 6/7 (see
        # "SUM(source.AMOUNT)" and "source.REGION" above) -- there is no
        # no-prefix resolution mode anywhere in mv_emit.py, so the correct,
        # consistent output here carries the same "source." prefix.
        assert emit_filter(col, resolver, model=model) == "source.STATUS = 'Active'"


class TestColumnMetadata:
    def test_comment_and_synonyms(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Region", "column_id": "FACT::REGION",
                "properties": {"column_type": "ATTRIBUTE",
                    "description": "Sales region", "synonyms": ["area", "territory"]}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        result = emit_dimension(col, resolver)
        assert result == {
            "name": "region", "expr": "source.REGION", "display_name": "Region",
            "comment": "Sales region", "synonyms": ["area", "territory"]}
        assert list(result.keys()) == ["name", "expr", "display_name", "comment", "synonyms"]

    def test_currency_format(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Revenue", "column_id": "FACT::REVENUE",
                "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                    "currency_type": {"iso_code": "USD"}}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "REVENUE", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        result = emit_measure(col, resolver)
        assert result["format"] == {"type": "currency", "currency_code": "USD"}
        assert list(result.keys()) == ["name", "expr", "display_name", "format"]
