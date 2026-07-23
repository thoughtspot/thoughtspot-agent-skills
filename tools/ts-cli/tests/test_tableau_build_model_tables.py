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


# ---------------------------------------------------------------------------
# 5. Fix #2 — Tableau disambiguation suffix must not leak into db_column_name
#    (BL follow-up: regression from the Ads Commercial Dashboard workbook)
# ---------------------------------------------------------------------------

COLLISION_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Ads'>
    <connection class='federated'>
      <relation name='agg_booked_monthly' type='table' table='[db].[s].[agg_booked_monthly]'/>
      <relation name='v_lineitem_budgetline' type='table' table='[db].[s].[v_lineitem_budgetline]'/>
      <metadata-records>
        <metadata-record class='column'>
          <remote-name>LineItemId</remote-name>
          <local-name>[LineItemId (agg_booked_monthly)]</local-name>
          <parent-name>[agg_booked_monthly]</parent-name>
          <local-type>integer</local-type>
        </metadata-record>
        <metadata-record class='column'>
          <remote-name>Amount</remote-name>
          <local-name>[Amount]</local-name>
          <parent-name>[agg_booked_monthly]</parent-name>
          <local-type>real</local-type>
        </metadata-record>
        <metadata-record class='column'>
          <remote-name>LineItemId</remote-name>
          <local-name>[LineItemId (v_lineitem_budgetline)]</local-name>
          <parent-name>[v_lineitem_budgetline]</parent-name>
          <local-type>integer</local-type>
        </metadata-record>
        <metadata-record class='column'>
          <remote-name>Budget</remote-name>
          <local-name>[Budget]</local-name>
          <parent-name>[v_lineitem_budgetline]</parent-name>
          <local-type>real</local-type>
        </metadata-record>
      </metadata-records>
      <object-graph>
        <relationships>
          <relationship>
            <expression op='='>
              <expression op='[LineItemId (agg_booked_monthly)]'/>
              <expression op='[LineItemId (v_lineitem_budgetline)]'/>
            </expression>
          </relationship>
        </relationships>
      </object-graph>
    </connection>
    <column name='[LineItemId (agg_booked_monthly)]' caption='LineItemId (agg booked monthly)' datatype='integer' role='dimension'/>
    <column name='[Amount]' caption='Amount' datatype='real' role='measure'/>
    <column name='[LineItemId (v_lineitem_budgetline)]' caption='LineItemId (v lineitem budgetline)' datatype='integer' role='dimension'/>
    <column name='[Budget]' caption='Budget' datatype='real' role='measure'/>
  </datasource>
</workbook>
"""


def test_column_collision_strips_disambiguation_suffix_end_to_end(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(COLLISION_TWB)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(out_dir), "--database", "DB", "--schema", "PUBLIC"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    by_name = {
        yaml.safe_load(f.read_text())["table"]["name"]: yaml.safe_load(f.read_text())["table"]
        for f in out_dir.glob("*.table.tml")
    }
    assert set(by_name) == {"agg_booked_monthly", "v_lineitem_budgetline"}

    for name in ("agg_booked_monthly", "v_lineitem_budgetline"):
        line_item = next(c for c in by_name[name]["columns"] if c["db_column_name"] == "LineItemId")
        # the physical column is clean — no Tableau disambiguation suffix
        assert " (" not in line_item["db_column_name"]

    # the join XREF check is the arbiter: the join's `on:` clause references
    # plain `LineItemId`, which must now resolve against the Table TML.
    lint_result = runner.invoke(app, ["tml", "lint", "--dir", str(out_dir)])
    payload = json.loads(lint_result.stdout)
    assert payload["clean"] is True, payload


def test_single_table_model_column_id_is_table_qualified_not_bare(tmp_path):
    # Fix #3 (BL follow-up): live-verified (se-thoughtspot, 2026-07-23) that a
    # bare column_id fails import on a single-table model, while TABLE::col
    # validates. This pins today's GENERATE flow already produces the
    # qualified form for the common (one physical table) case — a regression
    # here would only be caught otherwise by a live import.
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

    model_files = [f for f in out_dir.glob("*.model.tml") if "phase0" not in f.name]
    assert len(model_files) == 1
    doc = yaml.safe_load(model_files[0].read_text())
    column_ids = [c["column_id"] for c in doc["model"]["columns"] if c.get("column_id")]
    assert column_ids, "expected physical column_id entries"
    assert all("::" in cid for cid in column_ids), column_ids
    assert all(cid.startswith("Orders::") for cid in column_ids), column_ids


# ---------------------------------------------------------------------------
# 6. Fix #4 — hyper Extract wrapper must not be emitted as a duplicate table
# ---------------------------------------------------------------------------

EXTRACT_WRAPPER_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.b' caption='SetCtrl'>
    <connection class='federated'>
      <relation name='Orders' type='table' table='[Orders$]'/>
      <metadata-records>
        <metadata-record class='column'>
          <remote-name>Sales</remote-name>
          <local-name>[Sales]</local-name>
          <parent-name>[Orders]</parent-name>
          <local-type>real</local-type>
        </metadata-record>
      </metadata-records>
    </connection>
    <extract enabled='true'>
      <connection class='hyper'>
        <relation name='Extract' type='table' table='[Extract].[Extract]'/>
      </connection>
    </extract>
    <column name='[Sales]' caption='Sales' datatype='real' role='measure'/>
  </datasource>
</workbook>
"""


def test_extract_wrapper_table_not_duplicated_end_to_end(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(EXTRACT_WRAPPER_TWB)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(out_dir), "--database", "DB", "--schema", "PUBLIC"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    table_files = list(out_dir.glob("*.table.tml"))
    assert len(table_files) == 1
    doc = yaml.safe_load(table_files[0].read_text())
    assert doc["table"]["name"] == "Orders"

    lint_result = runner.invoke(app, ["tml", "lint", "--dir", str(out_dir)])
    payload = json.loads(lint_result.stdout)
    assert payload["clean"] is True, payload


# ---------------------------------------------------------------------------
# 7. Fix #B — two datasources sharing a physical table name must not overwrite
#    each other's Table TML (BL follow-up: Set Control "Sub-Category" XREF).
#    Reproduces (in miniature) TableauSetControlUseCases.twbx, whose three
#    datasources (Set Control / Sets / Hex Map) all declare a single-table
#    relation named "Orders" but each references a different subset of that
#    table's columns. build-model iterates datasources independently and
#    writes one `{slug}.table.tml` per table NAME — before this fix, the last
#    datasource processed silently clobbered the file, dropping any column
#    only an earlier datasource referenced (there: Sub-Category).
# ---------------------------------------------------------------------------

TWO_DS_SHARED_TABLE_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='DS_A'>
    <relation name='Orders' type='table' table='[db].[s].[Orders]'/>
    <column name='[Sales]' datatype='real' role='measure' caption='Sales'/>
    <column name='[Sub-Category]' datatype='string' role='dimension' caption='Sub-Category'/>
  </datasource>
  <datasource name='federated.b' caption='DS_B'>
    <relation name='Orders' type='table' table='[db].[s].[Orders]'/>
    <column name='[Sales]' datatype='real' role='measure' caption='Sales'/>
    <column name='[Customer ID]' datatype='string' role='dimension' caption='Customer ID'/>
  </datasource>
</workbook>
"""


def test_shared_table_name_across_datasources_merges_columns_not_overwrites(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWO_DS_SHARED_TABLE_TWB)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(out_dir), "--database", "DB", "--schema", "PUBLIC"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    table_files = list(out_dir.glob("*.table.tml"))
    assert len(table_files) == 1, [f.name for f in table_files]
    doc = yaml.safe_load(table_files[0].read_text())
    col_names = {c["name"] for c in doc["table"]["columns"]}
    # union of both datasources' columns — DS_B's write must not drop DS_A's
    # Sub-Category (or vice versa)
    assert col_names == {"Sales", "Sub-Category", "Customer ID"}

    # the real arbiter: DS_A's model references Orders::Sub-Category, which
    # must resolve against the (merged) Table TML with no hand-editing.
    lint_result = runner.invoke(app, ["tml", "lint", "--dir", str(out_dir)])
    payload = json.loads(lint_result.stdout)
    assert payload["clean"] is True, payload

