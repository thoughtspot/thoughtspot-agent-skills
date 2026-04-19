"""Unit tests for connection and column validation rules.

Tests that _build_table_tml() never produces known bad patterns:
  - fqn: inside a connection block
  - aggregation: in a formulas context (not applicable to _build_table_tml but
    validates the YAML output structure to ensure no unexpected fields)
  - connection name round-trips correctly

These tests act as a regression guard: if _build_table_tml() is modified in a way
that introduces a TML anti-pattern, these tests will catch it.
"""
import yaml
import pytest

from ts_cli.commands.tables import _build_table_tml


def parse(spec: dict) -> dict:
    return yaml.safe_load(_build_table_tml(spec))


def base_spec(**kwargs) -> dict:
    s = {
        "name": "TEST_TABLE",
        "db": "DB",
        "schema": "SCH",
        "db_table": "TEST_TABLE",
        "connection_name": "My Connection",
        "columns": [{"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"}],
    }
    s.update(kwargs)
    return s


# ---------------------------------------------------------------------------
# Anti-pattern: fqn: must never appear in connection block
# ---------------------------------------------------------------------------

class TestNoFqnInConnection:
    def test_connection_block_has_no_fqn(self):
        tml = parse(base_spec())
        conn = tml["table"]["connection"]
        assert "fqn" not in conn, (
            "fqn: must never appear in a connection block — "
            "ThoughtSpot only accepts name: here"
        )

    def test_connection_block_has_name(self):
        tml = parse(base_spec(connection_name="Prod Snowflake"))
        conn = tml["table"]["connection"]
        assert conn.get("name") == "Prod Snowflake"

    def test_connection_block_is_dict_not_string(self):
        """Connection must be a mapping, not a bare string."""
        tml = parse(base_spec())
        assert isinstance(tml["table"]["connection"], dict)


# ---------------------------------------------------------------------------
# Anti-pattern: aggregation: must not appear at the wrong level
# ---------------------------------------------------------------------------

class TestAggregationPlacement:
    def test_aggregation_on_measure_is_in_properties(self):
        """aggregation: must live in col['properties'], not at column root."""
        spec = base_spec(columns=[
            {"name": "AMOUNT", "data_type": "INT64", "column_type": "MEASURE"},
        ])
        tml = parse(spec)
        col = tml["table"]["columns"][0]
        # aggregation must be under properties, not at the column root
        assert "aggregation" not in col, "aggregation: must be inside properties, not at column root"
        assert "aggregation" in col["properties"]

    def test_no_formulas_in_table_tml(self):
        """_build_table_tml never produces a formulas: key — that belongs in model TML."""
        tml_str = _build_table_tml(base_spec())
        assert "formulas:" not in tml_str


# ---------------------------------------------------------------------------
# Connection name variations
# ---------------------------------------------------------------------------

class TestConnectionNameVariations:
    @pytest.mark.parametrize("conn_name", [
        "My Connection",
        "SNOWFLAKE_PROD",
        "APJ_BIRD (prod)",
        "connection with spaces and (parens)",
        "123-numeric-start",
    ])
    def test_connection_name_preserved_exactly(self, conn_name):
        tml = parse(base_spec(connection_name=conn_name))
        assert tml["table"]["connection"]["name"] == conn_name

    def test_connection_name_not_empty(self):
        """An empty connection name would produce invalid TML."""
        spec = base_spec(connection_name="Valid Name")
        tml = parse(spec)
        name = tml["table"]["connection"].get("name", "")
        assert name, "connection name must not be empty"


# ---------------------------------------------------------------------------
# db_column_name invariant as regression test
# ---------------------------------------------------------------------------

class TestDbColumnNameRegression:
    def test_db_column_name_always_present_regression(self):
        """
        Regression: If _build_table_tml is ever changed to omit db_column_name
        for columns where name == db_column_name (as an 'optimization'), this test
        will catch it. ThoughtSpot requires db_column_name in all cases.
        """
        spec = base_spec(columns=[
            {"name": "ORDER_ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
            {"name": "ORDER_DATE", "data_type": "DATE", "column_type": "ATTRIBUTE"},
            {"name": "TOTAL", "data_type": "DOUBLE", "column_type": "MEASURE"},
        ])
        tml = parse(spec)
        for col in tml["table"]["columns"]:
            assert "db_column_name" in col, (
                f"db_column_name missing from '{col['name']}' — "
                "this field is required by ThoughtSpot even when it equals name"
            )
