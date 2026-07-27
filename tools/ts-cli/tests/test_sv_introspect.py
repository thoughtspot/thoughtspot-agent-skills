"""Tests for ts_cli.sv_introspect — INFORMATION_SCHEMA → tables-spec."""
from __future__ import annotations

import pytest

from ts_cli.sv_introspect import (
    build_info_schema_query,
    build_tables_map,
    build_tables_spec,
    detect_column_gaps,
    extract_table_locations,
    map_snowflake_type,
    _split_fqn,
    _sv_referenced_columns,
)


# ---------------------------------------------------------------------------
# map_snowflake_type
# ---------------------------------------------------------------------------

class TestMapSnowflakeType:
    def test_varchar(self):
        assert map_snowflake_type("VARCHAR") == ("VARCHAR", [])

    def test_text(self):
        assert map_snowflake_type("TEXT") == ("VARCHAR", [])

    def test_char(self):
        assert map_snowflake_type("CHAR") == ("VARCHAR", [])

    def test_string(self):
        assert map_snowflake_type("STRING") == ("VARCHAR", [])

    def test_int(self):
        assert map_snowflake_type("INT") == ("INT64", [])

    def test_integer(self):
        assert map_snowflake_type("INTEGER") == ("INT64", [])

    def test_bigint(self):
        assert map_snowflake_type("BIGINT") == ("INT64", [])

    def test_float(self):
        assert map_snowflake_type("FLOAT") == ("DOUBLE", [])

    def test_double(self):
        assert map_snowflake_type("DOUBLE") == ("DOUBLE", [])

    def test_boolean(self):
        assert map_snowflake_type("BOOLEAN") == ("BOOL", [])

    def test_date(self):
        assert map_snowflake_type("DATE") == ("DATE", [])

    def test_timestamp_ntz(self):
        assert map_snowflake_type("TIMESTAMP_NTZ") == ("DATE_TIME", [])

    def test_timestamp_ltz(self):
        assert map_snowflake_type("TIMESTAMP_LTZ") == ("DATE_TIME", [])

    def test_timestamp_tz(self):
        assert map_snowflake_type("TIMESTAMP_TZ") == ("DATE_TIME", [])

    def test_datetime(self):
        assert map_snowflake_type("DATETIME") == ("DATE_TIME", [])

    def test_number_scale_zero(self):
        assert map_snowflake_type("NUMBER", 0) == ("INT64", [])

    def test_number_scale_positive(self):
        assert map_snowflake_type("NUMBER", 2) == ("DOUBLE", [])

    def test_number_scale_none(self):
        assert map_snowflake_type("NUMBER", None) == ("INT64", [])

    def test_decimal(self):
        assert map_snowflake_type("DECIMAL", 4) == ("DOUBLE", [])

    def test_variant_warns(self):
        ts_type, warns = map_snowflake_type("VARIANT")
        assert ts_type == "VARCHAR"
        assert len(warns) == 1
        assert "VARIANT" in warns[0]

    def test_array_warns(self):
        ts_type, warns = map_snowflake_type("ARRAY")
        assert ts_type == "VARCHAR"
        assert len(warns) == 1

    def test_object_warns(self):
        ts_type, warns = map_snowflake_type("OBJECT")
        assert ts_type == "VARCHAR"
        assert len(warns) == 1

    def test_binary_warns(self):
        ts_type, warns = map_snowflake_type("BINARY")
        assert ts_type == "VARCHAR"
        assert "binary" in warns[0].lower()

    def test_unknown_type_warns(self):
        ts_type, warns = map_snowflake_type("GEOMETRY")
        assert ts_type == "VARCHAR"
        assert "unknown" in warns[0].lower()

    def test_case_insensitive(self):
        assert map_snowflake_type("varchar") == ("VARCHAR", [])

    def test_whitespace_stripped(self):
        assert map_snowflake_type("  INT  ") == ("INT64", [])


# ---------------------------------------------------------------------------
# _split_fqn
# ---------------------------------------------------------------------------

class TestSplitFqn:
    def test_simple(self):
        assert _split_fqn("DB.SCHEMA.TABLE") == ("DB", "SCHEMA", "TABLE")

    def test_quoted(self):
        assert _split_fqn('DB."My Schema"."My Table"') == (
            "DB", "My Schema", "My Table")

    def test_four_parts(self):
        assert _split_fqn("CAT.DB.SCHEMA.TABLE") == ("DB", "SCHEMA", "TABLE")

    def test_too_few_parts(self):
        with pytest.raises(ValueError, match="3 parts"):
            _split_fqn("TABLE_ONLY")


# ---------------------------------------------------------------------------
# extract_table_locations
# ---------------------------------------------------------------------------

class TestExtractTableLocations:
    def test_basic(self):
        parsed = {
            "tables": [
                {"fqn": "DB.S.ORDERS", "name": "ORDERS", "alias": "ORDERS"},
                {"fqn": "DB.S.CUSTOMERS", "name": "CUSTOMERS",
                 "alias": "CUSTOMERS"},
            ],
        }
        locs = extract_table_locations(parsed)
        assert len(locs) == 2
        assert locs[0]["database"] == "DB"
        assert locs[0]["schema"] == "S"
        assert locs[0]["table_name"] == "ORDERS"
        assert locs[0]["alias"] == "ORDERS"

    def test_skips_subquery(self):
        parsed = {
            "tables": [
                {"fqn": "DB.S.T", "name": "T", "alias": "T"},
                {"fqn": "", "name": "SUB", "alias": "SUB",
                 "is_subquery": True},
            ],
        }
        locs = extract_table_locations(parsed)
        assert len(locs) == 1
        assert locs[0]["alias"] == "T"

    def test_empty_tables(self):
        assert extract_table_locations({"tables": []}) == []
        assert extract_table_locations({}) == []


# ---------------------------------------------------------------------------
# build_info_schema_query
# ---------------------------------------------------------------------------

class TestBuildInfoSchemaQuery:
    def test_single_schema(self):
        locations = [
            {"database": "DB", "schema": "S", "table_name": "T1",
             "alias": "T1"},
            {"database": "DB", "schema": "S", "table_name": "T2",
             "alias": "T2"},
        ]
        q = build_info_schema_query(locations)
        assert "DB.INFORMATION_SCHEMA.COLUMNS" in q
        assert "'T1'" in q
        assert "'T2'" in q
        assert "UNION" not in q

    def test_cross_schema(self):
        locations = [
            {"database": "DB", "schema": "S1", "table_name": "T1",
             "alias": "T1"},
            {"database": "DB", "schema": "S2", "table_name": "T2",
             "alias": "T2"},
        ]
        q = build_info_schema_query(locations)
        assert "UNION ALL" in q
        assert "TABLE_SCHEMA = 'S1'" in q
        assert "TABLE_SCHEMA = 'S2'" in q


# ---------------------------------------------------------------------------
# build_tables_spec
# ---------------------------------------------------------------------------

class TestBuildTablesSpec:
    def test_basic(self):
        rows = [
            {"TABLE_CATALOG": "DB", "TABLE_SCHEMA": "S",
             "TABLE_NAME": "ORDERS", "COLUMN_NAME": "ORDER_ID",
             "DATA_TYPE": "NUMBER", "NUMERIC_SCALE": 0,
             "ORDINAL_POSITION": 1},
            {"TABLE_CATALOG": "DB", "TABLE_SCHEMA": "S",
             "TABLE_NAME": "ORDERS", "COLUMN_NAME": "AMOUNT",
             "DATA_TYPE": "FLOAT", "NUMERIC_SCALE": None,
             "ORDINAL_POSITION": 2},
            {"TABLE_CATALOG": "DB", "TABLE_SCHEMA": "S",
             "TABLE_NAME": "ORDERS", "COLUMN_NAME": "STATUS",
             "DATA_TYPE": "VARCHAR", "NUMERIC_SCALE": None,
             "ORDINAL_POSITION": 3},
        ]
        locations = [
            {"database": "DB", "schema": "S", "table_name": "ORDERS",
             "alias": "ORDERS"},
        ]
        specs, warns = build_tables_spec(rows, locations, "My Conn")
        assert len(specs) == 1
        spec = specs[0]
        assert spec["name"] == "ORDERS"
        assert spec["db"] == "DB"
        assert spec["schema"] == "S"
        assert spec["db_table"] == "ORDERS"
        assert spec["connection_name"] == "My Conn"
        assert len(spec["columns"]) == 3
        assert spec["columns"][0]["data_type"] == "INT64"
        assert spec["columns"][1]["data_type"] == "DOUBLE"
        assert spec["columns"][2]["data_type"] == "VARCHAR"
        assert warns == []

    def test_variant_warning(self):
        rows = [
            {"TABLE_CATALOG": "DB", "TABLE_SCHEMA": "S",
             "TABLE_NAME": "T", "COLUMN_NAME": "DATA",
             "DATA_TYPE": "VARIANT", "NUMERIC_SCALE": None,
             "ORDINAL_POSITION": 1},
        ]
        locations = [
            {"database": "DB", "schema": "S", "table_name": "T",
             "alias": "T"},
        ]
        specs, warns = build_tables_spec(rows, locations, "C")
        assert specs[0]["columns"][0]["data_type"] == "VARCHAR"
        assert len(warns) == 1
        assert "VARIANT" in warns[0]

    def test_multi_table(self):
        rows = [
            {"TABLE_CATALOG": "DB", "TABLE_SCHEMA": "S",
             "TABLE_NAME": "A", "COLUMN_NAME": "ID",
             "DATA_TYPE": "INT", "NUMERIC_SCALE": None,
             "ORDINAL_POSITION": 1},
            {"TABLE_CATALOG": "DB", "TABLE_SCHEMA": "S",
             "TABLE_NAME": "B", "COLUMN_NAME": "ID",
             "DATA_TYPE": "INT", "NUMERIC_SCALE": None,
             "ORDINAL_POSITION": 1},
        ]
        locations = [
            {"database": "DB", "schema": "S", "table_name": "A",
             "alias": "A"},
            {"database": "DB", "schema": "S", "table_name": "B",
             "alias": "B"},
        ]
        specs, _ = build_tables_spec(rows, locations, "C")
        assert len(specs) == 2


# ---------------------------------------------------------------------------
# build_tables_map
# ---------------------------------------------------------------------------

class TestBuildTablesMap:
    def test_basic(self):
        locations = [
            {"database": "DB", "schema": "S", "table_name": "ORDERS",
             "alias": "O"},
            {"database": "DB", "schema": "S", "table_name": "CUSTOMERS",
             "alias": "C"},
        ]
        m = build_tables_map(locations)
        assert m == {
            "O": {"name": "ORDERS"},
            "C": {"name": "CUSTOMERS"},
        }


# ---------------------------------------------------------------------------
# _sv_referenced_columns
# ---------------------------------------------------------------------------

class TestSvReferencedColumns:
    def test_extracts_from_all_sections(self):
        parsed = {
            "dimensions": [
                {"name": "D1", "table": "T1", "column": "COL_A"},
            ],
            "metrics": [
                {"name": "M1", "table": "T1", "column": "COL_B"},
                {"name": "M2", "table": "T2", "column": "COL_C"},
            ],
            "facts": [
                {"name": "F1", "table": "T1", "column": "COL_D"},
            ],
        }
        cols = _sv_referenced_columns(parsed)
        assert cols["T1"] == {"COL_A", "COL_B", "COL_D"}
        assert cols["T2"] == {"COL_C"}

    def test_formula_entries_skipped(self):
        parsed = {
            "dimensions": [
                {"name": "D1", "table": None, "column": None,
                 "expr": "DATEDIFF(...)"},
            ],
            "metrics": [], "facts": [],
        }
        cols = _sv_referenced_columns(parsed)
        assert cols == {}


# ---------------------------------------------------------------------------
# detect_column_gaps
# ---------------------------------------------------------------------------

class TestDetectColumnGaps:
    def test_no_gaps(self):
        parsed = {
            "dimensions": [
                {"name": "D1", "table": "T", "column": "A"},
                {"name": "D2", "table": "T", "column": "B"},
            ],
            "metrics": [], "facts": [],
        }
        ts_cols = {"T": ["A", "B", "C"]}
        report = detect_column_gaps(parsed, ts_cols)
        assert report["T"]["status"] == "ok"
        assert report["T"]["missing"] == []
        assert report["T"]["extra"] == ["C"]

    def test_gaps(self):
        parsed = {
            "dimensions": [
                {"name": "D1", "table": "T", "column": "A"},
                {"name": "D2", "table": "T", "column": "MISSING"},
            ],
            "metrics": [], "facts": [],
        }
        ts_cols = {"T": ["A", "B"]}
        report = detect_column_gaps(parsed, ts_cols)
        assert report["T"]["status"] == "gaps"
        assert report["T"]["missing"] == ["MISSING"]

    def test_not_found(self):
        parsed = {
            "dimensions": [
                {"name": "D1", "table": "T", "column": "A"},
            ],
            "metrics": [], "facts": [],
        }
        report = detect_column_gaps(parsed, {})
        assert report["T"]["status"] == "not_found"
        assert report["T"]["missing"] == ["A"]

    def test_empty(self):
        report = detect_column_gaps(
            {"dimensions": [], "metrics": [], "facts": []}, {})
        assert report == {}
