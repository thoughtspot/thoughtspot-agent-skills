"""Unit tests for _build_table_tml() in ts_cli/commands/tables.py.

Tests verify the TML invariants documented in agents/shared/schemas/thoughtspot-table-tml.md.
No live ThoughtSpot connection required.
"""
import pytest
import yaml

from ts_cli.commands.tables import _build_table_tml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_tml(tml_str: str) -> dict:
    """Parse TML YAML string and return the dict."""
    return yaml.safe_load(tml_str)


def make_spec(columns=None, **kwargs) -> dict:
    base = {
        "name": "MY_TABLE",
        "db": "MY_DB",
        "schema": "MY_SCHEMA",
        "db_table": "MY_TABLE",
        "connection_name": "My Connection",
    }
    base.update(kwargs)
    if columns is not None:
        base["columns"] = columns
    else:
        base["columns"] = [
            {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
        ]
    return base


# ---------------------------------------------------------------------------
# Critical invariant: db_column_name is always present
# ---------------------------------------------------------------------------

class TestDbColumnName:
    def test_db_column_name_equals_name_by_default(self):
        """db_column_name must always be included, even when identical to name."""
        spec = make_spec(columns=[
            {"name": "ORDER_ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert "db_column_name" in col, "db_column_name must always be present"
        assert col["db_column_name"] == col["name"]

    def test_db_column_name_present_for_measure(self):
        spec = make_spec(columns=[
            {"name": "AMOUNT", "data_type": "INT64", "column_type": "MEASURE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert "db_column_name" in col
        assert col["db_column_name"] == "AMOUNT"

    def test_db_column_name_present_for_all_columns(self):
        spec = make_spec(columns=[
            {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
            {"name": "NAME", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
            {"name": "AMOUNT", "data_type": "INT64", "column_type": "MEASURE"},
            {"name": "DATE", "data_type": "DATE", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        for col in tml["table"]["columns"]:
            assert "db_column_name" in col, f"db_column_name missing from column '{col.get('name')}'"


# ---------------------------------------------------------------------------
# Critical invariant: connection uses name: not fqn:
# ---------------------------------------------------------------------------

class TestConnectionBlock:
    def test_connection_has_name_not_fqn(self):
        """Connection block must use name: only, never fqn:."""
        spec = make_spec()
        tml = parse_tml(_build_table_tml(spec))
        conn = tml["table"]["connection"]
        assert "name" in conn
        assert "fqn" not in conn, "fqn: must never appear in a connection block"

    def test_connection_name_preserved(self):
        spec = make_spec(connection_name="My Snowflake Connection")
        tml = parse_tml(_build_table_tml(spec))
        assert tml["table"]["connection"]["name"] == "My Snowflake Connection"

    def test_connection_name_with_special_chars(self):
        spec = make_spec(connection_name="APJ_BIRD (prod)")
        tml = parse_tml(_build_table_tml(spec))
        assert tml["table"]["connection"]["name"] == "APJ_BIRD (prod)"


# ---------------------------------------------------------------------------
# MEASURE columns get aggregation: SUM by default
# ---------------------------------------------------------------------------

class TestMeasureAggregation:
    def test_measure_gets_default_aggregation_sum(self):
        spec = make_spec(columns=[
            {"name": "REVENUE", "data_type": "INT64", "column_type": "MEASURE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["properties"]["aggregation"] == "SUM"

    def test_measure_respects_explicit_aggregation(self):
        spec = make_spec(columns=[
            {"name": "COUNT_COL", "data_type": "INT64", "column_type": "MEASURE",
             "aggregation": "COUNT"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["properties"]["aggregation"] == "COUNT"

    def test_attribute_has_no_aggregation(self):
        spec = make_spec(columns=[
            {"name": "STATUS", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert "aggregation" not in col["properties"]


# ---------------------------------------------------------------------------
# Valid ThoughtSpot data types
# ---------------------------------------------------------------------------

VALID_DATA_TYPES = ["INT64", "DOUBLE", "VARCHAR", "DATE", "DATE_TIME", "BOOLEAN"]

class TestDataTypes:
    @pytest.mark.parametrize("data_type", VALID_DATA_TYPES)
    def test_valid_data_type_round_trips(self, data_type):
        spec = make_spec(columns=[
            {"name": "COL", "data_type": data_type, "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["db_column_properties"]["data_type"] == data_type


# ---------------------------------------------------------------------------
# Output is valid YAML
# ---------------------------------------------------------------------------

class TestYamlOutput:
    def test_output_is_valid_yaml(self):
        spec = make_spec(columns=[
            {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
            {"name": "NAME", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
            {"name": "AMOUNT", "data_type": "DOUBLE", "column_type": "MEASURE"},
        ])
        tml_str = _build_table_tml(spec)
        tml = yaml.safe_load(tml_str)
        assert "table" in tml

    def test_table_top_level_fields(self):
        spec = make_spec()
        tml = parse_tml(_build_table_tml(spec))
        t = tml["table"]
        assert t["name"] == "MY_TABLE"
        assert t["db"] == "MY_DB"
        assert t["schema"] == "MY_SCHEMA"
        assert t["db_table"] == "MY_TABLE"
