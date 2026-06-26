"""Unit tests for ts load commands — source detection, name sanitisation, schema inference."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSanitiseName:
    @pytest.mark.parametrize("raw,expected", [
        ("Row ID", "ROW_ID"),
        ("Order Date", "ORDER_DATE"),
        ("Customer Name", "CUSTOMER_NAME"),
        ("  spaces  ", "SPACES"),
        ("col--with---dashes", "COL_WITH_DASHES"),
        ("already_UPPER", "ALREADY_UPPER"),
        ("special!@#chars$%", "SPECIAL_CHARS"),
        ("123numeric_start", "123NUMERIC_START"),
    ])
    def test_sanitise(self, raw, expected):
        from ts_cli.commands.load import sanitise_name
        assert sanitise_name(raw) == expected


class TestDetectSource:
    def test_csv_directory(self, tmp_path):
        (tmp_path / "sales.csv").write_text("a,b\n1,2\n")
        (tmp_path / "orders.csv").write_text("x,y\n3,4\n")
        from ts_cli.commands.load import detect_source
        source_type, file_infos = detect_source(tmp_path)
        assert source_type == "csv_dir"
        assert len(file_infos) == 2
        names = {f["table_name"] for f in file_infos}
        assert names == {"SALES", "ORDERS"}

    def test_tableau_download_json(self, tmp_path):
        download_output = {
            "tdsx_path": "/tmp/test.tdsx",
            "extracted_dir": str(tmp_path),
            "files": ["Data/sales.csv"],
            "data_files": [
                {"name": "Data/sales.csv", "path": str(tmp_path / "Data" / "sales.csv"),
                 "type": "csv", "validation": {"total_lines": 3, "header_columns": 2, "corrupt_lines": []}}
            ],
        }
        json_path = tmp_path / "download.json"
        json_path.write_text(json.dumps(download_output))
        (tmp_path / "Data").mkdir()
        (tmp_path / "Data" / "sales.csv").write_text("a,b\n1,2\n3,4\n")

        from ts_cli.commands.load import detect_source
        source_type, file_infos = detect_source(json_path)
        assert source_type == "tableau_download"
        assert len(file_infos) == 1
        assert file_infos[0]["table_name"] == "SALES"

    def test_manifest_with_data(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("x,y\n1,2\n")
        manifest = {
            "source": "manual",
            "tables": [{"table_name": "MY_TABLE", "data_file": str(csv_file),
                         "columns": [{"name": "x", "db_column_name": "X", "type": "INTEGER"}]}],
        }
        json_path = tmp_path / "manifest.json"
        json_path.write_text(json.dumps(manifest))
        from ts_cli.commands.load import detect_source
        source_type, file_infos = detect_source(json_path)
        assert source_type == "manifest"

    def test_schema_only_manifest(self, tmp_path):
        manifest = {
            "source": "manual",
            "tables": [{"table_name": "MY_TABLE",
                         "columns": [{"name": "x", "db_column_name": "X", "type": "INTEGER"}]}],
        }
        json_path = tmp_path / "schema.json"
        json_path.write_text(json.dumps(manifest))
        from ts_cli.commands.load import detect_source
        source_type, _ = detect_source(json_path)
        assert source_type == "schema_only"


class TestInferColumnTypes:
    def test_integer_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("id\n1\n2\n3\n42\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "INTEGER"
        assert cols[0]["db_column_name"] == "ID"

    def test_float_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("price\n1.5\n2.99\n3.0\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "FLOAT"

    def test_date_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("order_date\n2024-01-15\n2024-02-20\n2024-03-10\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "DATE"

    def test_timestamp_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("created_at\n2024-01-15 09:30:00\n2024-02-20 14:00:00\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "TIMESTAMP"

    def test_boolean_column(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("active\ntrue\nfalse\ntrue\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "BOOLEAN"

    def test_varchar_column_with_length(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("name\nAlice\nBob\nCharlie Brown The Third\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"].startswith("VARCHAR")
        length = int(cols[0]["inferred_type"].replace("VARCHAR(", "").replace(")", ""))
        assert length >= 256

    def test_blank_column_defaults_varchar(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("empty\n\n\n\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "VARCHAR(256)"

    def test_mixed_int_and_blank(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("qty\n5\n\n10\n\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        assert cols[0]["inferred_type"] == "INTEGER"

    def test_multiple_columns(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("id,name,price,active\n1,Alice,9.99,true\n2,Bob,19.50,false\n")
        from ts_cli.commands.load import infer_column_types
        cols = infer_column_types(csv_path)
        types = {c["db_column_name"]: c["inferred_type"] for c in cols}
        assert types["ID"] == "INTEGER"
        assert types["PRICE"] == "FLOAT"
        assert types["ACTIVE"] == "BOOLEAN"
        assert types["NAME"].startswith("VARCHAR")


class TestInferSchema:
    def test_csv_dir_full_output(self, tmp_path):
        (tmp_path / "sales.csv").write_text("id,amount\n1,9.99\n2,19.50\n")
        from ts_cli.commands.load import infer_schema
        result = infer_schema(tmp_path)
        assert result["source_type"] == "csv_dir"
        assert len(result["tables"]) == 1
        tbl = result["tables"][0]
        assert tbl["table_name"] == "SALES"
        assert tbl["row_count"] == 2
        assert len(tbl["columns"]) == 2


class TestGenerateCsv:
    def _make_schema(self, columns):
        return {"table_name": "TEST_TABLE", "columns": columns, "row_count": 0, "has_data": False}

    def test_integer_id_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([{"name": "id", "db_column_name": "ID", "inferred_type": "INTEGER"}])
        path = generate_csv(schema, rows=5, output_dir=tmp_path)
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert lines[0] == "ID"
        assert len(lines) == 6
        assert lines[1] == "1"
        assert lines[5] == "5"

    def test_varchar_name_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "customer_name", "db_column_name": "CUSTOMER_NAME", "inferred_type": "VARCHAR(256)"},
        ])
        path = generate_csv(schema, rows=3, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        assert lines[0] == "CUSTOMER_NAME"
        assert len(lines) == 4
        for line in lines[1:]:
            assert len(line) > 0

    def test_date_column(self, tmp_path):
        import re
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "order_date", "db_column_name": "ORDER_DATE", "inferred_type": "DATE"},
        ])
        path = generate_csv(schema, rows=3, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        for line in lines[1:]:
            assert re.match(r"\d{4}-\d{2}-\d{2}", line)

    def test_float_price_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "price", "db_column_name": "PRICE", "inferred_type": "FLOAT"},
        ])
        path = generate_csv(schema, rows=3, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        for line in lines[1:]:
            val = float(line)
            assert 1.0 <= val <= 10000.0

    def test_boolean_column(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "active", "db_column_name": "ACTIVE", "inferred_type": "BOOLEAN"},
        ])
        path = generate_csv(schema, rows=10, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        for line in lines[1:]:
            assert line in ("true", "false")

    def test_multiple_columns(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "id", "db_column_name": "ID", "inferred_type": "INTEGER"},
            {"name": "email", "db_column_name": "EMAIL", "inferred_type": "VARCHAR(256)"},
            {"name": "sales", "db_column_name": "SALES", "inferred_type": "FLOAT"},
        ])
        path = generate_csv(schema, rows=5, output_dir=tmp_path)
        lines = path.read_text().strip().split("\n")
        assert lines[0] == "ID,EMAIL,SALES"
        assert len(lines) == 6

    def test_deterministic_with_seed(self, tmp_path):
        from ts_cli.commands.load import generate_csv
        schema = self._make_schema([
            {"name": "price", "db_column_name": "PRICE", "inferred_type": "FLOAT"},
        ])
        path1 = generate_csv(schema, rows=5, output_dir=tmp_path / "a", seed=42)
        path2 = generate_csv(schema, rows=5, output_dir=tmp_path / "b", seed=42)
        assert path1.read_text() == path2.read_text()


class TestGenerateAll:
    def test_generates_from_schema_file(self, tmp_path):
        schema = {
            "source": "manual",
            "tables": [
                {"table_name": "ORDERS", "columns": [
                    {"name": "id", "db_column_name": "ID", "inferred_type": "INTEGER"},
                    {"name": "amount", "db_column_name": "AMOUNT", "inferred_type": "FLOAT"},
                ]},
            ],
        }
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(schema))
        output_dir = tmp_path / "output"

        from ts_cli.commands.load import generate_all
        result = generate_all(schema_path, rows=10, output_dir=output_dir)
        assert len(result) == 1
        assert result[0]["table_name"] == "ORDERS"
        assert result[0]["rows"] == 10
        assert (output_dir / "ORDERS.csv").exists()


class TestLoadSnowflakeProfile:
    def test_load_list_format(self, tmp_path):
        profiles_file = tmp_path / "snowflake-profiles.json"
        profiles_file.write_text(json.dumps([
            {"name": "Production", "method": "cli", "cli_connection": "prod",
             "default_warehouse": "WH", "default_role": "ROLE"},
        ]))
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", profiles_file):
            p = load_snowflake_profile("Production")
        assert p["cli_connection"] == "prod"

    def test_load_wrapped_format(self, tmp_path):
        profiles_file = tmp_path / "snowflake-profiles.json"
        profiles_file.write_text(json.dumps({"profiles": [
            {"name": "Dev", "method": "python", "account": "acct",
             "username": "user", "auth": "key_pair",
             "default_warehouse": "WH", "default_role": "ROLE"},
        ]}))
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", profiles_file):
            p = load_snowflake_profile("Dev")
        assert p["method"] == "python"

    def test_profile_not_found_exits(self, tmp_path):
        profiles_file = tmp_path / "snowflake-profiles.json"
        profiles_file.write_text(json.dumps([{"name": "Other"}]))
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", profiles_file):
            with pytest.raises(SystemExit):
                load_snowflake_profile("Missing")

    def test_no_file_exits(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        from ts_cli.commands.load import load_snowflake_profile
        with patch("ts_cli.commands.load.SF_PROFILES_PATH", missing):
            with pytest.raises(SystemExit):
                load_snowflake_profile("Any")


class TestBuildCreateTableSql:
    def test_basic_ddl(self):
        from ts_cli.commands.load import _build_create_table_sql
        columns = [
            {"db_column_name": "ID", "inferred_type": "INTEGER"},
            {"db_column_name": "NAME", "inferred_type": "VARCHAR(256)"},
            {"db_column_name": "PRICE", "inferred_type": "FLOAT"},
        ]
        sql = _build_create_table_sql("MY_TABLE", columns, "DB", "SCH")
        assert "CREATE TABLE DB.SCH.MY_TABLE" in sql
        assert "ID INTEGER" in sql
        assert "NAME VARCHAR(256)" in sql
        assert "PRICE FLOAT" in sql

    def test_uses_type_field_when_present(self):
        from ts_cli.commands.load import _build_create_table_sql
        columns = [{"db_column_name": "X", "type": "DATE"}]
        sql = _build_create_table_sql("T", columns, "DB", "SCH")
        assert "X DATE" in sql


class TestLoadViaCli:
    def test_builds_correct_commands(self, tmp_path):
        csv_file = tmp_path / "SALES.csv"
        csv_file.write_text("ID,AMOUNT\n1,9.99\n")
        tables = [{
            "table_name": "SALES",
            "columns": [
                {"db_column_name": "ID", "inferred_type": "INTEGER"},
                {"db_column_name": "AMOUNT", "inferred_type": "FLOAT"},
            ],
            "has_data": True,
            "file": "SALES.csv",
        }]
        profile = {"method": "cli", "cli_connection": "myconn",
                    "default_warehouse": "WH", "default_role": "ROLE"}

        from ts_cli.commands.load import _load_via_cli

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("ts_cli.commands.load.subprocess.run", return_value=mock_result) as mock_run:
            results = _load_via_cli(profile, tables, "DB", "SCH", "WH", "ROLE",
                                     "error", tmp_path)

        assert len(results) == 1
        assert results[0]["status"] == "created"
        calls_made = [str(c) for c in mock_run.call_args_list]
        assert any("CREATE DATABASE" in c for c in calls_made)
        assert any("CREATE SCHEMA" in c for c in calls_made)
        assert any("CREATE TABLE" in c for c in calls_made)
        assert any("COPY INTO" in c for c in calls_made)


class TestLoadViaPython:
    def test_builds_correct_queries(self, tmp_path):
        csv_file = tmp_path / "ORDERS.csv"
        csv_file.write_text("ID,TOTAL\n1,50.00\n")
        tables = [{
            "table_name": "ORDERS",
            "columns": [
                {"db_column_name": "ID", "inferred_type": "INTEGER"},
                {"db_column_name": "TOTAL", "inferred_type": "FLOAT"},
            ],
            "has_data": True,
            "file": "ORDERS.csv",
        }]
        profile = {"method": "python", "account": "acct", "username": "user",
                    "auth": "key_pair", "private_key_path": "~/.ssh/key.p8",
                    "default_warehouse": "WH", "default_role": "ROLE"}

        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(0,), (2,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        from ts_cli.commands.load import _load_via_python

        with patch("ts_cli.commands.load._connect_python", return_value=mock_conn):
            results = _load_via_python(profile, tables, "DB", "SCH", "WH", "ROLE",
                                        "error", tmp_path)

        assert len(results) == 1
        assert results[0]["status"] == "created"
        executed = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("CREATE DATABASE" in q for q in executed)
        assert any("CREATE TABLE" in q for q in executed)
        assert any("PUT" in q for q in executed)
        assert any("COPY INTO" in q for q in executed)
