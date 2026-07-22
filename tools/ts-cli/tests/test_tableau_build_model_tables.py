# tools/ts-cli/tests/test_tableau_build_model_tables.py
"""Task A2 — wiring ts_cli.tableau.tables.build_table_tml (Task A1) into
`ts tableau build-model` so it actually WRITES `.table.tml` files.

Four scenarios (see A2 brief):
  1. Single-table emission — one .table.tml, correct columns/data_types.
  2. End-to-end lint-clean — a real (small) TWB fixture through the full
     GENERATE flow, then `ts tml lint --dir` on the output directory must be
     clean. This is the model<->table name-alignment arbiter.
  3. No-reparse guardrail — parse_twb is called at most once per build-model run.
  4. Multi-table best-effort — owned columns land on the right table; columns
     with unresolvable ownership are collected, not silently dumped onto a table.
"""
from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

import ts_cli.commands.tableau as tableau_cmd
from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr is separated by default)
    runner = CliRunner()


def _ds(tables, columns=(), joins=(), col_table_map=None):
    return {
        "name": "DS",
        "tables": list(tables),
        "joins": list(joins),
        "columns": list(columns),
        "calculated_fields": [],
        "calc_map": {},
        "col_table_map": col_table_map or {},
    }


def _run_generate_flow(ds, out_path, **overrides):
    parsed = {"parameters": []}
    kwargs = dict(
        ds=ds, name="Test", slug="test", connection_name="CONN", parsed=parsed,
        cleaned_cols=list(ds["columns"]), cleaned_formulas=[], translated=[], skipped=[],
        rename_map={}, raw_levels={}, validation_issues=[], out_path=out_path,
        dry_run=False,
    )
    kwargs.update(overrides)
    return tableau_cmd._generate_flow(**kwargs)


# ---------------------------------------------------------------------------
# 1. Single-table emission
# ---------------------------------------------------------------------------

def test_single_table_emits_one_table_tml_with_correct_columns(tmp_path):
    ds = _ds(
        tables=[{"name": "Orders", "db_table": "ORDERS"}],
        columns=[
            {"name": "Order ID", "db_column_name": "Order ID", "column_type": "ATTRIBUTE", "data_type": "INT64"},
            {"name": "Sales", "db_column_name": "Sales", "column_type": "MEASURE", "data_type": "DOUBLE"},
            {"name": "Order Date", "db_column_name": "Order Date", "column_type": "ATTRIBUTE", "data_type": "DATE_TIME"},
        ],
    )

    result = _run_generate_flow(ds, tmp_path, database="DB", schema="PUBLIC")

    assert result["tables_written"] == 1
    assert len(result["table_files"]) == 1

    table_files = sorted(tmp_path.glob("*.table.tml"))
    assert len(table_files) == 1

    doc = yaml.safe_load(table_files[0].read_text())
    table = doc["table"]
    assert table["name"] == "Orders"
    assert table["db"] == "DB"
    assert table["schema"] == "PUBLIC"
    assert table["connection"] == {"name": "CONN"}

    cols = {c["name"]: c for c in table["columns"]}
    assert set(cols) == {"Order ID", "Sales", "Order Date"}
    assert cols["Order Date"]["db_column_properties"]["data_type"] == "DATE_TIME"
    assert cols["Sales"]["properties"]["column_type"] == "MEASURE"
    assert all("db_column_name" in c for c in table["columns"])


def test_dry_run_writes_no_table_tml(tmp_path):
    ds = _ds(
        tables=[{"name": "Orders", "db_table": "ORDERS"}],
        columns=[{"name": "Order ID", "db_column_name": "Order ID", "column_type": "ATTRIBUTE", "data_type": "INT64"}],
    )
    result = _run_generate_flow(ds, tmp_path, dry_run=True)
    assert list(tmp_path.glob("*.table.tml")) == []
    assert "table_files" not in result


# ---------------------------------------------------------------------------
# 2. End-to-end lint-clean (the model<->table name-alignment arbiter)
# ---------------------------------------------------------------------------

# A caption that differs from the underlying internal column name (CUST_NM vs.
# "Customer Name") is common in real Tableau workbooks and is exactly the case
# that breaks alignment if the Table TML re-derives db_column_name from the
# display name instead of reusing the same db_column_name the model's
# column_id was built from.
LINT_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='Orders' type='table' table='[db].[s].[Orders]'/>
    <column name='[Order ID]' datatype='integer' role='dimension' caption='Order ID'/>
    <column name='[Sales]' datatype='real' role='measure' caption='Sales'/>
    <column name='[Order Date]' datatype='datetime' role='dimension' caption='Order Date'/>
    <column name='[CUST_NM]' datatype='string' role='dimension' caption='Customer Name'/>
  </datasource>
</workbook>
"""


def test_end_to_end_build_model_is_lint_clean(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(LINT_TWB)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(out_dir), "--database", "DB", "--schema", "PUBLIC"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    assert list(out_dir.glob("*.table.tml")), "no .table.tml written"

    lint_result = runner.invoke(app, ["tml", "lint", "--dir", str(out_dir)])
    payload = json.loads(lint_result.stdout)
    assert payload["clean"] is True, payload
    assert lint_result.exit_code == 0


# ---------------------------------------------------------------------------
# 3. No-reparse guardrail
# ---------------------------------------------------------------------------

def test_build_model_parses_twb_at_most_once(tmp_path, monkeypatch):
    twb = tmp_path / "wb.twb"
    twb.write_text(LINT_TWB)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    from ts_cli import model_builder as mb

    real_parse_twb = mb.parse_twb
    calls = []

    def counting_parse_twb(path):
        calls.append(path)
        return real_parse_twb(path)

    monkeypatch.setattr(mb, "parse_twb", counting_parse_twb)

    result = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(out_dir), "--database", "DB", "--schema", "PUBLIC"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(calls) <= 1


# ---------------------------------------------------------------------------
# 4. Multi-table best-effort
# ---------------------------------------------------------------------------

def test_multi_table_assigns_owned_columns_and_collects_unowned(tmp_path):
    ds = _ds(
        tables=[{"name": "Orders", "db_table": "ORDERS"}, {"name": "Customers", "db_table": "CUSTOMERS"}],
        columns=[
            {"name": "Order ID", "db_column_name": "ORDER_ID", "column_type": "ATTRIBUTE", "data_type": "INT64"},
            {"name": "Sales", "db_column_name": "SALES", "column_type": "MEASURE", "data_type": "DOUBLE"},
            {"name": "Customer Name", "db_column_name": "CUST_NAME", "column_type": "ATTRIBUTE", "data_type": "VARCHAR"},
            {"name": "Mystery Column", "db_column_name": "MYSTERY", "column_type": "ATTRIBUTE", "data_type": "VARCHAR"},
        ],
        col_table_map={
            "ORDER_ID": "Orders",
            "SALES": "Orders",
            "CUST_NAME": "Customers",
            # MYSTERY intentionally absent -> unresolvable ownership
        },
    )

    result = _run_generate_flow(ds, tmp_path)

    table_files = sorted(tmp_path.glob("*.table.tml"))
    assert len(table_files) == 2
    assert result["tables_written"] == 2
    assert result["table_columns_unassigned"] == ["Mystery Column"]

    docs = {}
    for f in table_files:
        doc = yaml.safe_load(f.read_text())
        docs[doc["table"]["name"]] = doc["table"]

    orders_cols = {c["name"] for c in docs["Orders"]["columns"]}
    customers_cols = {c["name"] for c in docs["Customers"]["columns"]}
    assert orders_cols == {"Order ID", "Sales"}
    assert customers_cols == {"Customer Name"}
    assert "Mystery Column" not in orders_cols
    assert "Mystery Column" not in customers_cols
