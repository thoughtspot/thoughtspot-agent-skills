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
