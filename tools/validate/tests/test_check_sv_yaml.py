"""Unit tests for check_sv_yaml's forbidden-field rule (BL-450).

`sample_values` left FORBIDDEN_FIELDS on 2026-11-08: it is a native spec key on
dimensions and time_dimensions (live, it compiles to `sample_values (...)` in GET_DDL).
The other three stay, because Snowflake does not reject them — it parks them in the
Cortex Analyst extension, where they have no effect — so this validator is the only
thing that catches them. These tests pin both directions.
"""
import copy

import pytest

import check_sv_yaml as sv

BASE = {
    "name": "sales_sv",
    "tables": [
        {
            "name": "orders",
            "base_table": {"database": "DB", "schema": "S", "table": "ORDERS"},
            "dimensions": [
                {"name": "status", "expr": "orders.STATUS", "data_type": "TEXT"},
            ],
            "time_dimensions": [
                {"name": "order_date", "expr": "orders.ORDER_DATE", "data_type": "DATE"},
            ],
            "metrics": [{"name": "revenue", "expr": "SUM(orders.AMOUNT)"}],
        },
        {
            "name": "customers",
            "base_table": {"database": "DB", "schema": "S", "table": "CUSTOMERS"},
            "primary_key": {"columns": ["CUSTOMER_ID"]},
            "dimensions": [
                {"name": "customer_name", "expr": "customers.NAME", "data_type": "TEXT"},
            ],
        },
    ],
    "relationships": [
        {
            "name": "orders_to_customers",
            "left_table": "orders",
            "right_table": "customers",
            "relationship_columns": [
                {"left_column": "CUSTOMER_ID", "right_column": "CUSTOMER_ID"},
            ],
        }
    ],
}


def _doc():
    return copy.deepcopy(BASE)


def test_base_document_is_valid():
    assert sv.validate_sv_yaml(_doc()) == []


def test_sample_values_is_not_forbidden():
    assert "sample_values" not in sv.FORBIDDEN_FIELDS


def test_sample_values_on_dimension_and_time_dimension_passes():
    d = _doc()
    d["tables"][0]["dimensions"][0]["sample_values"] = ["OPEN", "SHIPPED"]
    d["tables"][0]["dimensions"][0]["is_enum"] = True
    d["tables"][0]["time_dimensions"][0]["sample_values"] = ["2026-01-01"]
    assert sv.validate_sv_yaml(d) == []


@pytest.mark.parametrize("key", ["relationship_type", "join_type", "default_aggregation"])
def test_remaining_forbidden_fields_still_fail_on_a_table(key):
    d = _doc()
    d["tables"][0][key] = "x"
    errors = sv.validate_sv_yaml(d)
    assert any(f"forbidden field '{key}'" in e for e in errors), errors


@pytest.mark.parametrize("key", ["relationship_type", "join_type"])
def test_remaining_forbidden_fields_still_fail_on_a_relationship(key):
    d = _doc()
    d["relationships"][0][key] = "many_to_one"
    errors = sv.validate_sv_yaml(d)
    assert any(f"forbidden field '{key}'" in e for e in errors), errors
