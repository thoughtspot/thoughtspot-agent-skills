"""Unit tests for the pure SQL-builders behind `ts load databricks` (no live connection)."""
from ts_cli.commands.load_databricks import (
    dbx_type, dbx_ident, build_dbx_create_sql, build_dbx_insert_sql, build_dbx_insert_batches,
    _sql_literal,
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
import subprocess as _subprocess
from pathlib import Path as _Path

import pytest
from typer.testing import CliRunner

from ts_cli.commands import load as load_core
from ts_cli.commands import load_databricks as load_mod
from ts_cli.sql_literal_shapes import is_calendar_date, is_iso_timestamp

_ORDERS_CSV = (
    "Order Id,Customer,Amount,Order Date,Note\n"
    "1,O'Brien,10.50,2024-01-02,plain\n"
    "2,Smith,,2024-02-03,\n"
    "3,Ng,7.25,2024-03-04,back\\slash\n"
)


class _Dbx:
    """Records statements. `existing` feeds SHOW TABLES; `fail_on` makes the n-th statement
    containing that text fail the way `_dbx_exec` does (SystemExit)."""
    def __init__(self):
        self.executed, self.existing, self.fail_on, self.fail_at = [], [], None, 1
        self._hits = 0

    def __call__(self, cli_profile, warehouse_id, statement):
        if self.fail_on and self.fail_on in statement:
            self._hits += 1
            if self._hits == self.fail_at:
                raise SystemExit("Databricks SQL failed (FAILED): boom")
        self.executed.append(statement)
        if statement.startswith("SHOW TABLES"):
            return {"result": {"data_array": [["s", t, "false"] for t in self.existing]}}
        if statement.startswith("DESCRIBE HISTORY"):
            return {"result": {"data_array": [["7", "2026-11-08T00:00:00.000Z"]]}}
        return {}


@pytest.fixture
def dbx(monkeypatch):
    """Stub the profile and the SQL executor; return the recorder."""
    rec = _Dbx()
    monkeypatch.setattr(load_mod, "_load_dbx_profile", lambda name: {
        "name": name, "dbx_profile": "stub",
        "sql_warehouse_http_path": "/sql/1.0/warehouses/wh123"})
    monkeypatch.setattr(load_mod, "_dbx_exec", rec)
    return rec


def _run(args):
    return CliRunner().invoke(load_mod.app, ["databricks", "--profile", "p",
                                             "--catalog", "c", "--schema", "s", *args])


def _inserts(rec):
    return [s for s in rec.executed if s.startswith("INSERT INTO")]


def _creates(rec):
    return [s for s in rec.executed if s.startswith("CREATE") and "TABLE" in s.split("(")[0]]


def _tuples(sqls):
    return sum(s.count("), (") + 1 for s in sqls)


# -- real rows, quoting, NULLs, counts ----------------------------------------

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


def test_reported_rows_equal_rows_inserted_and_source_file(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), "--batch", "2"])
    assert result.exit_code == 0, result.output
    inserts = _inserts(dbx)
    assert len(inserts) == 2                                  # 3 rows at --batch 2
    out = _json.loads(result.stdout)["loaded"][0]
    assert out["rows"] == _tuples(inserts) == 3
    assert out["data"] == "source"
    assert out["source_file"] == str(tmp_path / "orders.csv")
    assert "(3 source rows)" in result.stderr
    assert "SYNTHETIC" not in result.stderr


def test_batch_below_one_is_refused(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), "--batch", "0"])
    assert result.exit_code != 0 and "--batch must be at least 1" in result.output
    assert dbx.executed == []


def test_insert_batches_respect_byte_ceiling():
    cols = [{"name": "S", "type": "VARCHAR(5000)"}]
    rows = [["x" * 400] for _ in range(10)]
    stmts = build_dbx_insert_batches("`c`.`s`.`t`", cols, rows, batch=200, max_bytes=1000)
    assert len(stmts) > 1
    assert all(len(s.encode()) <= 1000 for s in stmts)
    assert _tuples(stmts) == 10


# -- synthetic rows: only on request ------------------------------------------

def _schema_only(tmp_path):
    manifest = tmp_path / "schema.json"
    manifest.write_text(_json.dumps({"tables": [{"table_name": "T", "columns": [
        {"name": "id", "type": "INTEGER"}, {"name": "region", "type": "VARCHAR(20)"}]}]}))
    return manifest


def test_schema_only_source_refused_without_generate_sample(tmp_path, dbx):
    result = _run(["--source", str(_schema_only(tmp_path))])
    assert result.exit_code != 0
    assert "No data file for T" in result.output and "--generate-sample" in result.output
    assert dbx.executed == []


def test_schema_only_with_generate_sample_gets_synthetic_rows_and_notice(tmp_path, dbx):
    result = _run(["--source", str(_schema_only(tmp_path)), "--generate-sample", "--rows", "5"])
    assert result.exit_code == 0, result.output
    assert "NOTICE" in result.stderr and "SYNTHETIC" in result.stderr
    out = _json.loads(result.stdout)["loaded"][0]
    assert out["rows"] == 5 and out["data"] == "synthetic" and out["source_file"] is None
    assert _tuples(_inserts(dbx)) == 5


def test_generate_sample_forces_synthetic_rows(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), "--generate-sample", "--rows", "4"])
    assert result.exit_code == 0, result.output
    sql = " ".join(_inserts(dbx))
    assert "O\\'Brien" not in sql and "'Ng'" not in sql      # the file's rows are not used
    assert "--generate-sample" in result.stderr and "SYNTHETIC" in result.stderr
    out = _json.loads(result.stdout)["loaded"][0]
    assert out["rows"] == 4 and out["data"] == "synthetic"


def test_synthetic_values_follow_the_column_type_before_its_name():
    import random as _r
    rng = _r.Random(3)
    assert {_pick_generator("has_email", "BOOLEAN", rng)() for _ in range(20)} <= {"true", "false"}
    assert _pick_generator("sales", "NUMBER(38,0)", rng)().isdigit()
    assert _pick_generator("update_count_date", "INTEGER", rng)().isdigit()
    ts = _pick_generator("created_at", "TIMESTAMP", rng)()
    assert is_iso_timestamp(ts), ts
    assert "@" in _pick_generator("email", "VARCHAR(50)", rng)()   # names still drive text


def test_synthetic_load_of_a_name_type_clash_succeeds(tmp_path, dbx):
    manifest = tmp_path / "s.json"
    manifest.write_text(_json.dumps({"tables": [{"table_name": "U", "columns": [
        {"name": "has_email", "type": "BOOLEAN"}, {"name": "created_at", "type": "TIMESTAMP"}]}]}))
    result = _run(["--source", str(manifest), "--generate-sample", "--rows", "3"])
    assert result.exit_code == 0, result.output


# -- encoding -------------------------------------------------------------------

def test_non_utf8_csv_is_refused_naming_file_line_and_byte(tmp_path, dbx):
    (tmp_path / "people.csv").write_bytes("Name,City\nAnn,Oslo\nJosé,Zürich\n".encode("cp1252"))
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0
    assert "people.csv" in result.output and "line 3" in result.output
    assert "0xE9" in result.output and "--encoding" in result.output
    assert dbx.executed == []


def test_encoding_option_loads_a_cp1252_file(tmp_path, dbx):
    (tmp_path / "people.csv").write_bytes("Name,Größe\nJosé,Zürich\n".encode("cp1252"))
    result = _run(["--source", str(tmp_path), "--encoding", "cp1252"])
    assert result.exit_code == 0, result.output
    assert "('José', 'Zürich')" in _inserts(dbx)[0]
    assert "\ufffd" not in " ".join(dbx.executed)   # header and values decoded, not replaced


def test_utf8_bom_does_not_reach_the_header(tmp_path, dbx):
    # With the BOM left on, "\ufeffCost" matched no schema name and the file was read by
    # position, so Revenue received Cost's values.
    (tmp_path / "fin.csv").write_bytes("\ufeffCost,Revenue\n1,100\n".encode("utf-8"))
    manifest = tmp_path / "m.json"
    manifest.write_text(_json.dumps({"tables": [{"table_name": "F", "data_file": str(tmp_path / "fin.csv"),
        "columns": [{"name": "Revenue", "type": "INTEGER"}, {"name": "Cost", "type": "INTEGER"}]}]}))
    assert _run(["--source", str(manifest)]).exit_code == 0
    assert "(`Revenue`, `Cost`) VALUES (100, 1)" in _inserts(dbx)[0]


# -- BIGINT / DOUBLE / DATE / TIMESTAMP literals ----------------------------------

def test_decimal_after_the_inference_sample_is_refused_for_bigint(tmp_path, dbx):
    rows = "".join(f"{i}\n" for i in range(1, 1001)) + "1.5\n"
    (tmp_path / "t.csv").write_text("N\n" + rows, encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0
    assert "data row 1001" in result.output and "BIGINT" in result.output
    assert dbx.executed == []            # no schema, table or row was created


def test_invalid_numeric_value_refused_before_anything_runs(tmp_path, dbx):
    # A later non-numeric value must not be spliced raw (a date evaluates as arithmetic).
    rows = "".join(f"{i}\n" for i in range(1, 1002)) + "2024-01-02\n"
    (tmp_path / "t.csv").write_text("N\n" + rows, encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0
    assert "data row 1002" in result.output and "BIGINT" in result.output
    assert dbx.executed == []


def test_sql_literal_rejects_non_literals():
    for val, t in (("1); DROP TABLE x; --", "BIGINT"), ("nan", "DOUBLE"),
                   ("2024-01-02", "BIGINT"), ("maybe", "BOOLEAN"),
                   ("1.5", "BIGINT"), ("1E-3", "BIGINT"), ("1e3", "BIGINT"),
                   ("\u0661\u0662", "BIGINT"), ("\u0661.5", "DOUBLE"),        # Arabic-Indic digits
                   ("2024-02-30", "DATE"), ("2024-01-02'x", "DATE"), ("02/01/2024", "DATE"),
                   ("2024-01-02 25:00:00", "TIMESTAMP"), ("2024-13-01T10:00", "TIMESTAMP"),
                   ("2024-01-02", "TIMESTAMP")):
        with pytest.raises(ValueError):
            _sql_literal(val, t)
    assert _sql_literal(" 1e3 ", "DOUBLE") == "1e3"
    assert _sql_literal("-42", "BIGINT") == "-42"
    assert _sql_literal("   ", "BIGINT") == "NULL"


def test_invalid_date_refused_at_planning(tmp_path, dbx):
    (tmp_path / "d.csv").write_text("D\n2024-02-28\n2024-02-30\n", encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0 and "data row 2" in result.output and "DATE" in result.output
    assert dbx.executed == []


@pytest.mark.parametrize("v", ["2024-01-02 10:11:12", "2024-01-02T10:11:12", "2024-01-02T10:11",
                               "2024-01-02 10:11:12.123", "2024-01-02T10:11:12Z",
                               "2024-01-02 10:11:12+05:30", "2024-01-02 10:11:12 +05:30",
                               "2024-01-02T10:11:12.5-08:00", "2024-01-02 10:11:12+0530"])
def test_timestamp_forms_databricks_accepts(v):
    # Each form was sent as TIMESTAMP'<v>' to DBSQL 2026.35 and accepted (2026-11-08).
    assert is_iso_timestamp(v)
    assert _sql_literal(v, "TIMESTAMP") == f"TIMESTAMP'{v}'"


def test_calendar_date_shape():
    assert is_calendar_date("2024-02-29") and not is_calendar_date("2023-02-29")
    assert not is_calendar_date("\u0662024-01-01")


# -- the CSV reader -------------------------------------------------------------

def _cols(*names, t="VARCHAR(10)"):
    return [{"name": n, "db_column_name": n.upper(), "inferred_type": t} for n in names]


def test_blank_lines_skipped_in_a_multi_column_csv(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("A,B\n1,2\n\n   \n3,4\n", encoding="utf-8")
    assert load_mod._read_csv_rows(p, _cols("A", "B")) == [["1", "2"], ["3", "4"]]


def test_blank_line_in_a_single_column_csv_is_null(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("A\n1\n\n3\n", encoding="utf-8")
    assert load_mod._read_csv_rows(p, _cols("A")) == [["1"], [""], ["3"]]


def test_short_row_is_padded_with_null(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("A,B,C\n1,2\n", encoding="utf-8")
    assert load_mod._read_csv_rows(p, _cols("A", "B", "C")) == [["1", "2", ""]]


def test_extra_non_empty_cells_refused_but_trailing_empties_allowed(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("A,B\n1,2,,\n", encoding="utf-8")
    assert load_mod._read_csv_rows(p, _cols("A", "B")) == [["1", "2"]]
    p.write_text("A,B\n1,2\n3,4,5\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="line 3: 3 cells, header has 2"):
        load_mod._read_csv_rows(p, _cols("A", "B"))


def test_header_width_mismatch_with_unmatched_names_refused(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("X,Y,Z\n1,2,3\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="header has 3 columns and the schema has 2"):
        load_mod._read_csv_rows(p, _cols("A", "B"))


def test_unmatched_names_same_width_fall_back_to_position(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("X,Y\n1,2\n", encoding="utf-8")
    assert load_mod._read_csv_rows(p, _cols("A", "B")) == [["1", "2"]]


def test_a_matched_name_at_the_wrong_position_is_refused_not_swapped(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Cost,Rev\n1,100\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Cost"):
        load_mod._read_csv_rows(p, _cols("Revenue", "Cost"))


def test_manifest_columns_matched_to_csv_header_by_name(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("B,A\nb1,1\n", encoding="utf-8")
    manifest = tmp_path / "m.json"
    manifest.write_text(_json.dumps({"tables": [{"table_name": "T", "data_file": str(tmp_path / "t.csv"),
        "columns": [{"name": "A", "type": "INTEGER"}, {"name": "B", "type": "VARCHAR(10)"}]}]}))
    assert _run(["--source", str(manifest)]).exit_code == 0
    assert "(1, 'b1')" in _inserts(dbx)[0]


# -- names and sources ------------------------------------------------------------

def test_two_csvs_with_one_table_name_are_refused(tmp_path, dbx):
    (tmp_path / "order-items.csv").write_text("A\n1\n", encoding="utf-8")
    (tmp_path / "order_items.csv").write_text("A\n2\n", encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0 and "ORDER_ITEMS" in result.output
    assert dbx.executed == []


def test_each_table_reads_its_own_file(tmp_path, dbx):
    (tmp_path / "a.csv").write_text("V\n10\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("V\n20\n", encoding="utf-8")
    assert _run(["--source", str(tmp_path)]).exit_code == 0
    by_table = {s.split("`")[5]: s for s in _inserts(dbx)}
    assert by_table["A"].endswith("VALUES (10)") and by_table["B"].endswith("VALUES (20)")


def test_duplicate_sanitised_column_names_are_refused(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("Order Id,order_id\n1,2\n", encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0 and "both load as ORDER_ID" in result.output
    assert dbx.executed == []


def test_infer_output_fed_back_loads_the_csv_rows(tmp_path, dbx):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    (csvs / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    elsewhere = tmp_path / "review"
    elsewhere.mkdir()
    schema = load_core.infer_schema(csvs)
    schema["tables"][0]["columns"][2]["inferred_type"] = "FLOAT"   # a Step 5 type override
    (elsewhere / "schema.json").write_text(_json.dumps(schema))
    result = _run(["--source", str(elsewhere / "schema.json")])
    assert result.exit_code == 0, result.output
    assert _json.loads(result.stdout)["loaded"][0]["data"] == "source"
    assert "'Ng'" in " ".join(_inserts(dbx))


def test_old_infer_output_without_data_file_resolves_next_to_the_json(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    schema = load_core.infer_schema(tmp_path)
    for t in schema["tables"]:
        t.pop("data_file")                     # the shape before data_file existed
    (tmp_path / "schema.json").write_text(_json.dumps(schema))
    assert load_core.detect_source(tmp_path / "schema.json")[0] == "manifest"
    result = _run(["--source", str(tmp_path / "schema.json")])
    assert result.exit_code == 0, result.output
    assert "'Ng'" in " ".join(_inserts(dbx))


def test_infer_output_naming_a_missing_file_is_refused_not_schema_only(tmp_path):
    (tmp_path / "schema.json").write_text(_json.dumps({"tables": [
        {"table_name": "T", "file": "gone.csv", "has_data": True,
         "columns": [{"name": "A", "inferred_type": "INTEGER"}]}]}))
    with pytest.raises(SystemExit, match="gone.csv not found"):
        load_core.detect_source(tmp_path / "schema.json")


# -- existing tables, partial failure ------------------------------------------------

def test_existing_table_refused_by_default_before_anything_is_created(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    dbx.existing = ["orders"]
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0 and "already exist" in result.output
    assert _creates(dbx) == [] and _inserts(dbx) == []


@pytest.mark.parametrize("args,verb", [([], "CREATE TABLE `"),
                                       (["--if-exists", "append"], "CREATE TABLE IF NOT EXISTS"),
                                       (["--if-exists", "replace"], "CREATE OR REPLACE TABLE"),
                                       (["--replace"], "CREATE OR REPLACE TABLE")])
def test_if_exists_modes(tmp_path, dbx, args, verb):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), *args])
    assert result.exit_code == 0, result.output
    assert _creates(dbx)[0].startswith(verb)


def test_replace_conflicting_with_if_exists_is_refused(tmp_path, dbx):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    result = _run(["--source", str(tmp_path), "--replace", "--if-exists", "append"])
    assert result.exit_code != 0 and "conflicts" in result.output


def test_execution_failure_reports_what_was_written(tmp_path, dbx):
    (tmp_path / "a.csv").write_text("V\n1\n2\n3\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("V\n9\n", encoding="utf-8")
    dbx.fail_on, dbx.fail_at = "INSERT INTO", 2          # A's second batch fails
    result = _run(["--source", str(tmp_path), "--batch", "2"])
    assert result.exit_code != 0
    assert "Load stopped part-way" in result.stderr
    assert "c.s.A: created by this run, 2 of 3 rows inserted" in result.stderr
    assert "--if-exists replace" in result.stderr
    assert not any("`B`" in s for s in dbx.executed)


# -- identifiers, profile, the executor ------------------------------------------------

def test_backticks_in_identifiers_are_doubled(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("a`b\n1\n", encoding="utf-8")
    result = CliRunner().invoke(load_mod.app, ["databricks", "--profile", "p", "--catalog", "c`x",
                                               "--schema", "s", "--source", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert dbx.executed[0] == "CREATE SCHEMA IF NOT EXISTS `c``x`.`s`"
    assert "`c``x`.`s`.`T`" in _creates(dbx)[0] and "`A_B`" in _creates(dbx)[0]
    assert dbx_ident("a`b") == "`a``b`"
    assert build_dbx_create_sql("`t`", [{"name": "q`r", "type": "INT"}]).count("`q``r`") == 1


def test_unknown_profile_is_a_clean_error(tmp_path, monkeypatch):
    f = tmp_path / "databricks-profiles.json"
    f.write_text(_json.dumps([{"name": "Production"}]))
    monkeypatch.setattr(load_mod, "_DBX_PROFILES_PATH", f)
    with pytest.raises(SystemExit, match="'Nope' not found. Available: Production"):
        load_mod._load_dbx_profile("Nope")


class _Proc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _capture_run(monkeypatch, result):
    seen = {}
    def fake_run(argv, **kw):
        body = argv[argv.index("--json") + 1]
        seen["argv"], seen["path"] = argv, _Path(body[1:])
        seen["body"] = _json.loads(seen["path"].read_text())
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(load_mod.subprocess, "run", fake_run)
    return seen


def test_dbx_exec_sends_the_body_as_a_file_and_unlinks_it(monkeypatch):
    seen = _capture_run(monkeypatch, _Proc(0, _json.dumps({"status": {"state": "SUCCEEDED"}})))
    load_mod._dbx_exec("prof", "wh1", "SELECT 1")
    assert seen["argv"][:4] == ["databricks", "api", "post", "/api/2.0/sql/statements"]
    assert seen["argv"][seen["argv"].index("--json") + 1].startswith("@")
    assert seen["body"] == {"warehouse_id": "wh1", "statement": "SELECT 1", "wait_timeout": "50s"}
    assert "SELECT 1" not in " ".join(seen["argv"])          # the statement is not in argv
    assert not seen["path"].exists()


@pytest.mark.parametrize("outcome", [_Proc(1, "", "denied"), FileNotFoundError("databricks")])
def test_dbx_exec_unlinks_the_body_file_on_failure(monkeypatch, outcome):
    seen = _capture_run(monkeypatch, outcome)
    with pytest.raises((SystemExit, FileNotFoundError)):
        load_mod._dbx_exec("prof", "wh1", "SELECT 1")
    assert not seen["path"].exists()



# -- re-review round: one CSV per --source, whichever loader ------------------------

def _sf_capture(monkeypatch):
    """Stub the Snowflake profile and python loader; record what the loader would read."""
    seen = {}
    monkeypatch.setattr(load_core, "load_snowflake_profile", lambda n: {"default_warehouse": "WH"})
    def fake_load(profile, tables, database, schema, wh, role, if_exists, csv_dir):
        seen["paths"] = {t["table_name"]: load_core._sf_csv_path(t, csv_dir) for t in tables}
        seen["tables"] = tables
        return [{"table_name": t["table_name"], "status": "created", "rows_loaded": 0,
                 "columns": len(t["columns"]), "source_file": t.get("file", "")} for t in tables]
    monkeypatch.setattr(load_core, "_load_via_python", fake_load)
    return seen


def _sf_run(args):
    return CliRunner().invoke(load_core.app, ["snowflake", "--profile", "p", "--database", "D",
                                              "--schema", "S", *args])


def test_infer_writes_an_absolute_data_file(tmp_path, monkeypatch):
    (tmp_path / "csvs").mkdir()
    (tmp_path / "csvs" / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    t = load_core.infer_schema(_Path("csvs"))["tables"][0]
    assert _Path(t["data_file"]).is_absolute()
    assert t["data_file"] == str((tmp_path / "csvs" / "orders.csv").resolve())


def test_infer_output_saved_next_to_its_csvs_loads_from_any_directory(tmp_path, dbx, monkeypatch):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    (csvs / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    monkeypatch.chdir(csvs)
    (csvs / "schema.json").write_text(_json.dumps(load_core.infer_schema(_Path("."))))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "orders.csv").write_text("Order Id\n99\n", encoding="utf-8")   # a decoy
    monkeypatch.chdir(elsewhere)
    assert _run(["--source", str(csvs / "schema.json")]).exit_code == 0
    assert "'Ng'" in " ".join(_inserts(dbx))
    seen = _sf_capture(monkeypatch)
    assert _sf_run(["--source", str(csvs / "schema.json")]).exit_code == 0
    assert seen["paths"]["ORDERS"] == (csvs / "orders.csv").resolve()


def test_a_relative_name_found_in_two_places_is_refused(tmp_path, monkeypatch):
    jdir, cwd = tmp_path / "j", tmp_path / "cwd"
    jdir.mkdir(), cwd.mkdir()
    (jdir / "orders.csv").write_text("A\n1\n", encoding="utf-8")
    (cwd / "orders.csv").write_text("A\n2\n", encoding="utf-8")
    (jdir / "schema.json").write_text(_json.dumps({"tables": [
        {"table_name": "ORDERS", "file": "orders.csv", "has_data": True,
         "columns": [{"name": "A", "inferred_type": "INTEGER"}]}]}))
    monkeypatch.chdir(cwd)
    with pytest.raises(SystemExit, match="ambiguous"):
        load_core.infer_schema(jdir / "schema.json")


def test_both_loaders_read_the_one_file_a_relative_name_resolves_to(tmp_path, dbx, monkeypatch):
    jdir, cwd = tmp_path / "j", tmp_path / "cwd"
    jdir.mkdir(), cwd.mkdir()
    (cwd / "orders.csv").write_text("A\n10\n", encoding="utf-8")     # only in the working dir
    (jdir / "schema.json").write_text(_json.dumps({"tables": [
        {"table_name": "ORDERS", "file": "orders.csv", "has_data": True,
         "columns": [{"name": "A", "inferred_type": "INTEGER"}]}]}))
    monkeypatch.chdir(cwd)
    assert _run(["--source", str(jdir / "schema.json")]).exit_code == 0
    assert _inserts(dbx)[0].endswith("VALUES (10)")
    seen = _sf_capture(monkeypatch)
    assert _sf_run(["--source", str(jdir / "schema.json")]).exit_code == 0
    assert seen["paths"]["ORDERS"] == (cwd / "orders.csv").resolve()


# -- header matching passes -----------------------------------------------------------

def test_header_case_only_mismatch_matches_by_name():
    # Name-only manifest columns: the old lookup missed both and read by position (swapped).
    cols = [{"name": "Revenue"}, {"name": "Cost"}]
    assert load_mod._header_index(["cost", "revenue"], cols, "f") == [1, 0]


def test_a_case_insensitive_match_beats_a_sanitised_one():
    # "a b" equals "A B" ignoring case; "A_B" equals it only once sanitised.
    assert load_mod._header_index(["a b", "A_B"], [{"name": "A B"}, {"name": "X"}], "f") == [0, 1]


def test_a_sanitised_header_never_shadows_another_headers_exact_name():
    cols = [{"name": "CUSTOMER_ID"}, {"name": "Customer ID"}, {"name": "Amount"}]
    header = ["Customer ID", "CUSTOMER_ID", "Amount"]
    assert load_mod._header_index(header, cols, "f") == [1, 0, 2]


def test_sanitised_forms_match_a_doubled_space():
    assert load_mod._header_index(["Order  Date", "Id"], [{"name": "Id"}, {"name": "Order Date"}],
                                  "f") == [1, 0]


# -- ranges ---------------------------------------------------------------------------

def test_integer_outside_bigint_loads_as_decimal_38_0(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("N\n5\n12345678901234567890123\n-9223372036854775809\n",
                                    encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "`N` DECIMAL(38,0)" in _creates(dbx)[0]
    assert "(12345678901234567890123)" in _inserts(dbx)[0]


def test_bigint_column_within_range_stays_bigint(tmp_path, dbx):
    (tmp_path / "t.csv").write_text("N\n5\n9223372036854775807\n", encoding="utf-8")
    assert _run(["--source", str(tmp_path)]).exit_code == 0
    assert "`N` BIGINT" in _creates(dbx)[0]


def test_range_limits_are_refused():
    for val, t in (("9223372036854775808", "BIGINT"), ("1" * 39, "DECIMAL(38,0)"),
                   ("1e400", "DOUBLE"), ("2024-01-02 10:00:00+18:30", "TIMESTAMP"),
                   ("2024-01-02 10:00:00-19:00", "TIMESTAMP")):
        with pytest.raises(ValueError):
            _sql_literal(val, t)
    assert is_iso_timestamp("2024-01-02 10:00:00+18:00")
    assert is_iso_timestamp("2024-01-02 10:00:00-18:00")
    assert _sql_literal("1" * 38, "DECIMAL(38,0)") == "1" * 38


# -- recovery advice after an append ---------------------------------------------------

def test_failed_append_to_an_existing_table_points_to_delta_history_not_replace(tmp_path, dbx):
    (tmp_path / "a.csv").write_text("V\n1\n2\n3\n", encoding="utf-8")
    dbx.existing = ["a"]
    dbx.fail_on, dbx.fail_at = "INSERT INTO", 2
    result = _run(["--source", str(tmp_path), "--batch", "2", "--if-exists", "append"])
    assert result.exit_code != 0
    err = result.stderr
    assert "existed before this run; 2 of 3 rows were appended" in err
    assert "RESTORE TABLE `c`.`s`.`A` TO VERSION AS OF 7" in err
    assert "Do not re-run with --if-exists replace" in err
    assert "re-run with --if-exists replace to reload" not in err


def test_failed_append_to_a_new_table_may_be_replaced(tmp_path, dbx):
    (tmp_path / "a.csv").write_text("V\n1\n2\n3\n", encoding="utf-8")
    dbx.fail_on, dbx.fail_at = "INSERT INTO", 2
    result = _run(["--source", str(tmp_path), "--batch", "2", "--if-exists", "append"])
    assert "created by this run" in result.stderr and "RESTORE" not in result.stderr


# -- --generate-sample needs no data files, and means synthetic everywhere --------------

def _manifest_with_missing_data(tmp_path):
    m = tmp_path / "m.json"
    m.write_text(_json.dumps({"tables": [{"table_name": "T", "data_file": "gone.csv", "rows": 3,
        "columns": [{"name": "id", "type": "INTEGER"}, {"name": "region", "type": "VARCHAR(20)"}]}]}))
    return m


def test_generate_needs_no_data_files(tmp_path):
    out = tmp_path / "out"
    res = load_core.generate_all(_manifest_with_missing_data(tmp_path), rows=5, output_dir=out)
    assert res[0]["rows"] == 3 and (out / "T.csv").is_file()


def test_databricks_generate_sample_needs_no_data_files(tmp_path, dbx):
    result = _run(["--source", str(_manifest_with_missing_data(tmp_path)), "--generate-sample"])
    assert result.exit_code == 0, result.output
    assert _json.loads(result.stdout)["loaded"][0]["rows"] == 3


def test_snowflake_generate_sample_needs_no_data_files(tmp_path, monkeypatch):
    seen = _sf_capture(monkeypatch)
    result = _sf_run(["--source", str(_manifest_with_missing_data(tmp_path)), "--generate-sample"])
    assert result.exit_code == 0, result.output
    assert seen["paths"]["T"].is_file()


def test_snowflake_generate_sample_replaces_source_data_and_says_so(tmp_path, monkeypatch):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    seen = _sf_capture(monkeypatch)
    result = _sf_run(["--source", str(tmp_path), "--generate-sample", "--rows", "4"])
    assert result.exit_code == 0, result.output
    assert seen["paths"]["ORDERS"] != (tmp_path / "orders.csv").resolve()
    assert len(seen["paths"]["ORDERS"].read_text().splitlines()) == 5      # header + 4
    assert "SYNTHETIC" in result.stderr
    out = _json.loads(result.stdout)["tables"][0]
    assert out["data"] == "synthetic" and out["source_file"] is None


def test_snowflake_reports_source_rows(tmp_path, monkeypatch):
    (tmp_path / "orders.csv").write_text(_ORDERS_CSV, encoding="utf-8")
    seen = _sf_capture(monkeypatch)
    result = _sf_run(["--source", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert _json.loads(result.stdout)["tables"][0]["data"] == "source"
    assert seen["paths"]["ORDERS"] == (tmp_path / "orders.csv").resolve()


def test_snowflake_generate_sample_honours_a_tables_own_row_count(tmp_path, monkeypatch):
    seen = _sf_capture(monkeypatch)
    assert _sf_run(["--source", str(_schema_only(tmp_path)), "--generate-sample",
                    "--rows", "4"]).exit_code == 0
    pinned = tmp_path / "pin.json"
    pinned.write_text(_json.dumps({"tables": [{"table_name": "P", "rows": 2,
                                               "columns": [{"name": "id", "type": "INTEGER"}]}]}))
    assert _sf_run(["--source", str(pinned), "--generate-sample", "--rows", "4"]).exit_code == 0
    assert len(seen["paths"]["P"].read_text().splitlines()) == 3            # header + 2


# -- strict decoding everywhere ------------------------------------------------------------

def _cp1252_dir(tmp_path):
    d = tmp_path / "cp"
    d.mkdir()
    (d / "sizes.csv").write_bytes("Name,Größe\nJosé,10\n".encode("cp1252"))
    return d


def test_infer_command_decodes_strictly_and_takes_an_encoding(tmp_path):
    d = _cp1252_dir(tmp_path)
    bad = CliRunner().invoke(load_core.app, ["infer", "--source", str(d)])
    assert bad.exit_code != 0 and "0xF6" in bad.output
    good = CliRunner().invoke(load_core.app, ["infer", "--source", str(d), "--encoding", "cp1252"])
    assert good.exit_code == 0, good.output
    assert [c["name"] for c in _json.loads(good.stdout)["tables"][0]["columns"]] == ["Name", "Größe"]


def test_snowflake_inference_decodes_strictly(tmp_path, monkeypatch):
    seen = _sf_capture(monkeypatch)
    result = _sf_run(["--source", str(_cp1252_dir(tmp_path))])
    assert result.exit_code != 0 and "not valid utf-8" in result.output and seen == {}


def test_cp1252_column_name_survives_direct_and_through_schema_json(tmp_path, dbx):
    d = _cp1252_dir(tmp_path)
    assert _run(["--source", str(d), "--encoding", "cp1252"]).exit_code == 0
    direct = list(dbx.executed)
    dbx.executed.clear()
    infer = CliRunner().invoke(load_core.app, ["infer", "--source", str(d), "--encoding", "cp1252"])
    schema = _json.loads(infer.stdout)
    assert schema["tables"][0]["columns"][1]["name"] == "Größe"
    (tmp_path / "schema.json").write_text(_json.dumps(schema), encoding="utf-8")
    assert _run(["--source", str(tmp_path / "schema.json"), "--encoding", "cp1252"]).exit_code == 0
    assert dbx.executed == direct                              # identical DDL and rows
    assert "('José', 10)" in _inserts(dbx)[0]
    assert "�" not in " ".join(direct)


# -- nits ---------------------------------------------------------------------------------

def test_a_bad_value_in_a_later_table_stops_everything(tmp_path, dbx):
    (tmp_path / "a.csv").write_text("V\n10\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("D\n2024-01-01\n2024-02-30\n", encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0 and "b.csv" in result.output
    assert dbx.executed == []


def test_existing_tables_ignores_temporary_views(monkeypatch):
    monkeypatch.setattr(load_mod, "_dbx_exec", lambda *a: {"result": {"data_array": [
        ["s", "orders", "true"], ["s", "items", "false"]]}})
    assert load_mod._existing_tables("p", "w", "c", "s", ["ORDERS", "ITEMS"]) == ["ITEMS"]


def test_existing_tables_refuses_a_chunked_result_with_safe_advice(monkeypatch):
    monkeypatch.setattr(load_mod, "_dbx_exec", lambda *a: {"result": {
        "data_array": [["s", "x", "false"]], "next_chunk_index": 1}})
    with pytest.raises(SystemExit, match="Check them yourself") as e:
        load_mod._existing_tables("p", "w", "c", "s", ["ORDERS"])
    assert "keeps existing rows" in str(e.value) and "drops them" in str(e.value)


def test_decode_error_offset_counts_the_bom(tmp_path):
    p = tmp_path / "t.csv"
    raw = b"\xef\xbb\xbfA\nb\xe9\n"
    p.write_bytes(raw)
    at = raw.index(b"\xe9")                          # 6: the BOM's 3 bytes count
    assert at == 6
    with pytest.raises(SystemExit, match=f"line 2, byte offset {at}: 0xE9"):
        load_core.read_csv_text(p)


def test_a_table_name_with_no_letters_or_digits_is_refused(tmp_path, dbx):
    (tmp_path / "€.csv").write_text("A\n10\n", encoding="utf-8")
    result = _run(["--source", str(tmp_path)])
    assert result.exit_code != 0 and "no letters or digits" in result.output
    assert dbx.executed == []


def test_zero_one_columns_infer_as_integer_and_true_false_as_boolean():
    assert load_core._infer_type(["0", "1", "1", "0"]) == "INTEGER"
    assert load_core._infer_type(["true", "False", "TRUE"]) == "BOOLEAN"


def test_an_exact_match_beats_a_case_insensitive_one():
    # Two headers differing only by case: each column takes its exact twin, not an ambiguity.
    assert load_mod._header_index(["Name", "NAME"], [{"name": "NAME"}, {"name": "Name"}], "f") == [1, 0]


def test_a_bom_never_reaches_the_inferred_column_name(tmp_path):
    p = tmp_path / "t.csv"
    p.write_bytes(b"\xef\xbb\xbfCost,Revenue\n1,2\n")
    assert [c["name"] for c in load_core.infer_column_types(p)] == ["Cost", "Revenue"]
