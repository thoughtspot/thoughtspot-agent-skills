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


# ── VALID_JOIN_TYPES: the same four values in every TML context ──────────────
# Live-verified 2026-07-30 on se-thoughtspot: FULL_OUTER is rejected with error
# 14528 in BOTH model_tables[].joins[].type and table.joins_with[].type, and
# OUTER *is* the full outer join. The table context was previously ungated
# because the reference wrongly documented FULL_OUTER as valid there.

def _table_with_join(join_type):
    return {"table": {
        "name": "ORDERS", "db": "DB", "schema": "S", "db_table": "ORDERS",
        "connection": {"name": "conn"},
        "columns": [{
            "name": "c", "db_column_name": "c",
            "properties": {"column_type": "ATTRIBUTE"},
            "db_column_properties": {"data_type": "VARCHAR"},
        }],
        "joins_with": [{
            "name": "ORDERS_to_CUSTOMERS",
            "destination": {"name": "CUSTOMERS"},
            "on": "[ORDERS::CID] = [CUSTOMERS::CID]",
            "type": join_type,
            "cardinality": "MANY_TO_ONE",
        }],
    }}


def test_table_joins_with_full_outer_is_flagged():
    errors = check_tml.validate_table_tml(_table_with_join("FULL_OUTER"))
    assert any("FULL_OUTER" in e and "ORDERS_to_CUSTOMERS" in e for e in errors), errors


def test_table_joins_with_outer_passes():
    errors = check_tml.validate_table_tml(_table_with_join("OUTER"))
    assert not any("type" in e for e in errors), errors


def test_table_joins_with_unknown_type_is_flagged():
    errors = check_tml.validate_table_tml(_table_with_join("CROSS"))
    assert any("CROSS" in e for e in errors), errors


def _model_with_join(join_type):
    return _model(
        model_tables=[
            {"name": "ORDERS", "joins": [{
                "with": "CUSTOMERS",
                "on": "[ORDERS::CID] = [CUSTOMERS::CID]",
                "type": join_type,
                "cardinality": "MANY_TO_ONE",
            }]},
            {"name": "CUSTOMERS"},
        ],
        formulas=[],
        columns=[{
            "name": "CID", "column_id": "ORDERS::CID",
            "properties": {"column_type": "ATTRIBUTE"},
        }],
    )


def test_model_inline_join_full_outer_still_flagged():
    errors = check_tml.validate_model_tml(_model_with_join("FULL_OUTER"))
    assert any("FULL_OUTER" in e for e in errors), errors


def test_model_inline_join_outer_passes():
    # Accept path: OUTER *is* ThoughtSpot's full outer join and must not be flagged.
    errors = check_tml.validate_model_tml(_model_with_join("OUTER"))
    assert not any("type" in e for e in errors), errors
