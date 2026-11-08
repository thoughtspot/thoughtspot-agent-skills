"""Unit tests for the pure SQL-builders behind `ts load databricks` (no live connection)."""
from ts_cli.commands.load_databricks import (
    dbx_type, build_dbx_create_sql, build_dbx_insert_sql, build_dbx_insert_batches, _sql_literal,
)


def test_dbx_type_mapping():
    assert dbx_type("VARCHAR(64)") == "STRING"
    assert dbx_type("CHAR") == "STRING"
    assert dbx_type("DATE") == "DATE"
    assert dbx_type("TIMESTAMP") == "TIMESTAMP"
    assert dbx_type("FLOAT") == "DOUBLE"
    assert dbx_type("NUMBER(38,2)") == "DOUBLE"   # has scale → DOUBLE
    assert dbx_type("NUMBER(38,0)") == "BIGINT"   # no scale → BIGINT
    assert dbx_type("INT") == "BIGINT"
    assert dbx_type("BOOLEAN") == "BOOLEAN"
    assert dbx_type("") == "STRING"


def test_create_sql_backticks_and_column_mapping():
    cols = [{"name": "Order Date", "type": "DATE"}, {"name": "Sales", "type": "NUMBER(38,2)"}]
    sql = build_dbx_create_sql("`c`.`s`.`orders_demo`", cols)
    assert "`Order Date` DATE" in sql          # space-containing name preserved 1:1
    assert "`Sales` DOUBLE" in sql
    assert "delta.columnMapping.mode" in sql   # column mapping enabled (else Delta rejects spaces)
    assert sql.startswith("CREATE TABLE IF NOT EXISTS `c`.`s`.`orders_demo`")


def test_sql_literal_quoting_by_type():
    assert _sql_literal("2024-01-02", "DATE") == "DATE'2024-01-02'"
    assert _sql_literal("123.45", "DOUBLE") == "123.45"
    assert _sql_literal("42", "BIGINT") == "42"
    # Backslash-escaped: on Databricks `'O''Brien'` is two adjacent literals that
    # concatenate to `OBrien` (live-verified 2026-11-08, BL-550).
    assert _sql_literal("O'Brien", "STRING") == "'O\\'Brien'"
    assert _sql_literal("a\\b", "STRING") == "'a\\\\b'"
    assert _sql_literal("", "STRING") == "NULL"
    assert _sql_literal(None, "DOUBLE") == "NULL"
    assert _sql_literal("true", "BOOLEAN") == "true"
    assert _sql_literal("no", "BOOLEAN") == "false"


def test_insert_sql_builds_value_tuples():
    cols = [{"name": "Region", "type": "VARCHAR"}, {"name": "Sales", "type": "NUMBER(38,2)"}]
    rows = [["West", "10.5"], ["East", "20"]]
    sql = build_dbx_insert_sql("`c`.`s`.`t`", cols, rows)
    assert sql.startswith("INSERT INTO `c`.`s`.`t` (`Region`, `Sales`) VALUES ")
    assert "('West', 10.5)" in sql
    assert "('East', 20)" in sql


# ---------------------------------------------------------------------------
# Numeric-type detection for synthetic data (bug: NUMBER/DECIMAL/INT/BIGINT
# fell through to the val_00001 string generator) — added 2026-07-16
# ---------------------------------------------------------------------------
from ts_cli.commands.load import _is_int_type, _is_float_type, _pick_generator
import random


def test_is_int_type():
    for t in ("INTEGER", "INT", "BIGINT", "NUMBER(38,0)", "NUMERIC(10)", "DECIMAL(5,0)"):
        assert _is_int_type(t), t
    for t in ("NUMBER(38,2)", "DOUBLE", "VARCHAR(64)", "DATE"):
        assert not _is_int_type(t), t


def test_is_float_type():
    for t in ("FLOAT", "DOUBLE", "REAL", "NUMBER(38,2)", "DECIMAL(10,4)"):
        assert _is_float_type(t), t
    for t in ("NUMBER(38,0)", "BIGINT", "VARCHAR", "DATE"):
        assert not _is_float_type(t), t


def test_id_column_number_type_generates_integers_not_val_strings():
    # regression: order_id NUMBER(38,0) previously produced "val_00001" (string)
    gen = _pick_generator("order_id", "NUMBER(38,0)", random.Random(1))
    vals = [gen() for _ in range(5)]
    assert all(v.isdigit() for v in vals), vals   # integers, not val_0000N


def test_plain_number_column_generates_numeric():
    gen = _pick_generator("some_measure", "NUMBER(38,2)", random.Random(1))
    v = gen()
    assert float(v)  # parses as a number, not a val_ string


# ---------------------------------------------------------------------------
# BL-550: `ts load databricks` must INSERT a CSV source's own rows, not synthetic
# ones. The command is driven end to end with `_dbx_exec` stubbed, so these
# assert on the exact SQL that would reach the warehouse.
# ---------------------------------------------------------------------------
import json as _json

import pytest
from typer.testing import CliRunner

from ts_cli.commands import load_databricks as load_mod

_ORDERS_CSV = (
    "Order Id,Customer,Amount,Order Date,Note\n"
    "1,O'Brien,10.50,2024-01-02,plain\n"
    "2,Smith,,2024-02-03,\n"
    "3,Ng,7.25,2024-03-04,back\\slash\n"
)


@pytest.fixture
def dbx(monkeypatch):
    """Stub the profile and the SQL executor; return the list of executed statements."""
    executed: list = []
    monkeypatch.setattr(load_mod, "_load_dbx_profile", lambda name: {
        "name": name, "dbx_profile": "stub",
        "sql_warehouse_http_path": "/sql/1.0/warehouses/wh123"})
    monkeypatch.setattr(load_mod, "_dbx_exec",
                        lambda cli_profile, warehouse_id, statement: executed.append(statement) or {})
    return executed


def _run(args):
    return CliRunner().invoke(load_mod.app, ["databricks", "--profile", "p",
                                             "--catalog", "c", "--schema", "s", *args])


def _inserts(executed):
    return [s for s in executed if s.startswith("INSERT INTO")]


def test_csv_source_inserts_its_own_rows(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code == 0, result.output
    sql = " ".join(_inserts(dbx))
    assert "(1, 'O\\'Brien', 10.50, DATE'2024-01-02', 'plain')" in sql
    assert "(3, 'Ng', 7.25, DATE'2024-03-04', 'back\\\\slash')" in sql
    assert "val_0" not in sql            # no synthetic placeholder strings

    assert "(2, 'Smith', NULL, DATE'2024-02-03', NULL)" in sql   # empty cells → NULL


def test_csv_quote_in_value_is_backslash_escaped(tmp_path, dbx):
    (tmp_path / "people.csv").write_text(
        'Name,Quote\n"O\'Brien","she said ""hi"", it\'s fine"\n', encoding="utf-8")
    assert _run(["--source", str(tmp_path)]).exit_code == 0
    sql = _inserts(dbx)[0]
    assert "('O\\'Brien', 'she said \"hi\", it\\'s fine')" in sql
    assert "''" not in sql   # the doubled form Databricks reads as concatenation


def test_empty_cell_becomes_null(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("A,B,C\n1,,x\n2,3,\n", encoding="utf-8")
    assert _run(["--source", str(tmp_path)]).exit_code == 0
    sql = _inserts(dbx)[0]
    assert "(1, NULL, 'x')" in sql
    assert "(2, 3, NULL)" in sql


def test_reported_rows_equal_rows_inserted(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), "--batch", "2"])
    assert result.exit_code == 0, result.output
    inserts = _inserts(dbx)
    assert len(inserts) == 2                                  # 3 rows at --batch 2
    inserted = sum(s.count("), (") + 1 for s in inserts)
    out = _json.loads(result.stdout)["loaded"][0]
    assert out["rows"] == inserted == 3
    assert out["data"] == "source"
    assert "(3 source rows)" in result.stderr
    assert "SYNTHETIC" not in result.stderr


def test_schema_only_source_gets_synthetic_rows_with_notice(tmp_path, dbx):
    manifest = tmp_path / "schema.json"
    manifest.write_text(_json.dumps({"tables": [{"table_name": "T", "columns": [
        {"name": "id", "type": "INTEGER"}, {"name": "region", "type": "VARCHAR(20)"}]}]}))
    result = _run(["--source", str(manifest), "--rows", "5"])
    assert result.exit_code == 0, result.output
    assert "NOTICE" in result.stderr and "SYNTHETIC" in result.stderr
    assert "schema-only" in result.stderr
    out = _json.loads(result.stdout)["loaded"][0]
    assert out["rows"] == 5 and out["data"] == "synthetic"
    assert _inserts(dbx)[0].count("), (") + 1 == 5


def test_generate_sample_forces_synthetic_rows(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), "--generate-sample", "--rows", "4"])
    assert result.exit_code == 0, result.output
    sql = " ".join(_inserts(dbx))
    assert "O\\'Brien" not in sql and "'Ng'" not in sql      # the file's rows are not used
    assert "--generate-sample" in result.stderr and "SYNTHETIC" in result.stderr
    out = _json.loads(result.stdout)["loaded"][0]
    assert out["rows"] == 4 and out["data"] == "synthetic"


def test_manifest_columns_matched_to_csv_header_by_name(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("B,A\nb1,1\n", encoding="utf-8")
    manifest = tmp_path / "m.json"
    manifest.write_text(_json.dumps({"tables": [{"table_name": "T", "data_file": str(tmp_path / "t.csv"),
        "columns": [{"name": "A", "type": "INTEGER"}, {"name": "B", "type": "VARCHAR(10)"}]}]}))
    assert _run(["--source", str(manifest)]).exit_code == 0
    assert "(1, 'b1')" in _inserts(dbx)[0]


def test_invalid_numeric_value_refused_before_anything_runs(tmp_path, dbx):
    # Inference samples the first 1000 rows; a later non-numeric value must not be
    # spliced raw into a BIGINT column (a date would evaluate as arithmetic).
    rows = "".join(f"{i}\n" for i in range(1, 1002)) + "2024-01-02\n"
    (tmp_path / "t.csv").write_text("N\n" + rows, encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0
    assert "data row 1002" in result.output and "BIGINT" in result.output
    assert dbx == []            # no schema, table or row was created


def test_insert_batches_respect_byte_ceiling():
    cols = [{"name": "S", "type": "VARCHAR(5000)"}]
    rows = [["x" * 400] for _ in range(10)]
    stmts = build_dbx_insert_batches("`c`.`s`.`t`", cols, rows, batch=200, max_bytes=1000)
    assert len(stmts) > 1
    assert all(len(s.encode()) <= 1000 for s in stmts)
    assert sum(s.count("), (") + 1 for s in stmts) == 10


def test_sql_literal_rejects_non_literals():
    for val, t in (("1); DROP TABLE x; --", "BIGINT"), ("nan", "DOUBLE"),
                   ("2024-01-02", "BIGINT"), ("maybe", "BOOLEAN")):
        with pytest.raises(ValueError):
            _sql_literal(val, t)
    assert _sql_literal(" 1e3 ", "DOUBLE") == "1e3"
    assert _sql_literal("2024-01-02'x", "DATE") == "DATE'2024-01-02\\'x'"
