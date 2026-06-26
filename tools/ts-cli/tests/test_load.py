"""Unit tests for ts load commands — source detection, name sanitisation, schema inference."""
from __future__ import annotations

import csv
import json
from pathlib import Path

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
