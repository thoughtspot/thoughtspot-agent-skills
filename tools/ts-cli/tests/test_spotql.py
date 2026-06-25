"""Unit tests for SpotQL response normalisation in ts_cli/commands/spotql.py.

Covers the pure functions only — no live ThoughtSpot connection:
  - generate-sql success (executable_sql, no status field)
  - fetch-data success (columnar query_result -> row-major; int64-string -> int; nulls)
  - structured 400 error envelope -> code extracted from the debug string
  - validation-code extraction (bracket marker and `Error Code:` prefix)
"""
from ts_cli.commands.spotql import (
    extract_columns_and_rows,
    extract_validation_code,
    normalise_response,
)


def test_generate_sql_success():
    out = normalise_response({"executable_sql": "SELECT 1"})
    assert out["status"] == "SUCCESS"
    assert out["executable_sql"] == "SELECT 1"
    assert out["errors"] == []


def test_error_envelope_extracts_code():
    raw = {"error": {"message": {"code": 10002,
           "debug": '["Error Code: COLUMN_NOT_FOUND Incident Id: x"]'}}}
    out = normalise_response(raw)
    assert out["status"] == "COLUMN_NOT_FOUND"
    assert out["errors"][0]["code"] == "COLUMN_NOT_FOUND"


def test_fetch_data_columnar_rows():
    raw = {"query_result": {"results": [{"tables": {"column": [
        {"name": "g1", "type": "CHAR", "value": [{"stringVal": "West"}, {"stringVal": "East"}]},
        {"name": "g2", "type": "INT64", "value": [{"int64Val": "10"}, {"int64Val": "20"}]},
    ]}}]}}
    out = normalise_response(raw)
    assert out["status"] == "SUCCESS"
    assert out["columns"] == [{"index": 0, "type": "CHAR"}, {"index": 1, "type": "INT64"}]
    assert out["rows"] == [["West", 10], ["East", 20]]  # int64 string coerced to int


def test_fetch_data_null_cell():
    raw = {"query_result": {"results": [{"tables": {"column": [
        {"name": "g1", "type": "CHAR", "value": [{"nullVal": True}]},
    ]}}]}}
    assert normalise_response(raw)["rows"] == [[None]]


def test_extract_columns_and_rows_empty():
    assert extract_columns_and_rows(None) == ([], [])
    assert extract_columns_and_rows({"results": []}) == ([], [])


def test_extract_validation_code_bracket():
    assert extract_validation_code("1. [SELECT_STAR] not supported") == "SELECT_STAR"


def test_extract_validation_code_prefix():
    assert extract_validation_code("Error Code: QUERY_GEN_ERROR Incident Id: y") == "QUERY_GEN_ERROR"


def test_unparseable_payload():
    out = normalise_response("not a dict")
    assert out["status"] == "PARSE_ERROR"
    assert out["errors"][0]["code"] == "PARSE_ERROR"
