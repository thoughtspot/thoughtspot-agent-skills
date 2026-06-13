"""Unit tests for check_tml allowlists VALID_AGGREGATIONS / TS_DATA_TYPES (audit F4).

These value sets were defined but never referenced, so an invalid aggregation
(AVG instead of AVERAGE) or a SQL-only data_type slipped through unflagged.
Imports check_tml the same way test_check_tml.py does."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_tml  # noqa: E402


def _model(**inner):
    return {"model": inner}


# ── VALID_AGGREGATIONS: aggregation values must be a known enum ─────────────

def test_invalid_aggregation_avg_is_flagged():
    # TS uses AVERAGE, not AVG — AVG must be rejected.
    data = _model(
        model_tables=[{"name": "ORDERS"}],
        formulas=[],
        columns=[{
            "name": "Avg Price",
            "column_id": "ORDERS::price",
            "properties": {"column_type": "MEASURE", "aggregation": "AVG"},
        }],
    )
    errors = check_tml.validate_model_tml(data)
    assert any("AVG" in e and "aggregation" in e.lower() for e in errors), errors


def test_valid_aggregation_average_passes():
    data = _model(
        model_tables=[{"name": "ORDERS"}],
        formulas=[],
        columns=[{
            "name": "Avg Price",
            "column_id": "ORDERS::price",
            "properties": {"column_type": "MEASURE", "aggregation": "AVERAGE"},
        }],
    )
    errors = check_tml.validate_model_tml(data)
    assert not any("aggregation" in e.lower() and "invalid" in e.lower()
                   for e in errors), errors


def test_count_distinct_stays_a_valid_enum():
    # COUNT_DISTINCT is a valid aggregation enum value. Its forbidden-on-physical-column
    # placement (I5) is a separate check; the enum check must not also reject it as unknown.
    assert "COUNT_DISTINCT" in check_tml.VALID_AGGREGATIONS
    data = _model(
        model_tables=[{"name": "ORDERS"}],
        formulas=[],
        columns=[{
            "name": "Unique Customers",
            "formula_id": "f1",
            "properties": {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT"},
        }],
    )
    errors = check_tml.validate_model_tml(data)
    assert not any("invalid" in e.lower() and "aggregation" in e.lower()
                   for e in errors), errors


# ── TS_DATA_TYPES: db_column_properties.data_type must be a known TS type ────

def test_unknown_data_type_varchar2_is_flagged():
    data = {"table": {
        "name": "T", "db": "DB", "schema": "S", "db_table": "T",
        "connection": {"name": "conn"},
        "columns": [{
            "name": "c", "db_column_name": "c",
            "properties": {"column_type": "ATTRIBUTE"},
            "db_column_properties": {"data_type": "VARCHAR2"},
        }],
    }}
    errors = check_tml.validate_table_tml(data)
    assert any("VARCHAR2" in e for e in errors), errors


def test_sql_only_type_keeps_existing_message():
    data = {"table": {
        "name": "T", "db": "DB", "schema": "S", "db_table": "T",
        "connection": {"name": "conn"},
        "columns": [{
            "name": "c", "db_column_name": "c",
            "properties": {"column_type": "ATTRIBUTE"},
            "db_column_properties": {"data_type": "TEXT"},
        }],
    }}
    errors = check_tml.validate_table_tml(data)
    assert any("TEXT" in e and "SQL type" in e for e in errors), errors


def test_valid_data_type_varchar_passes():
    data = {"table": {
        "name": "T", "db": "DB", "schema": "S", "db_table": "T",
        "connection": {"name": "conn"},
        "columns": [{
            "name": "c", "db_column_name": "c",
            "properties": {"column_type": "ATTRIBUTE"},
            "db_column_properties": {"data_type": "VARCHAR"},
        }],
    }}
    errors = check_tml.validate_table_tml(data)
    assert not any("data_type" in e for e in errors), errors
