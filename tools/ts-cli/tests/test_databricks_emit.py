import pytest
from ts_cli.databricks.mv_emit import build_column_index, make_col_resolver
from ts_cli.databricks.mv_emit_expr import parse_formula
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
        with pytest.raises(Exception):
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
