"""`ts model dictionary` — one row per Model column, typed from the Table TMLs."""
import csv
import io
import json

import pytest
import yaml

from ts_cli.model_dictionary import FIELDS, build_rows, sheet_titles, to_csv, write_xlsx

TABLES = {
    "DM_ORDER": {"name": "DM_ORDER", "columns": [
        {"name": "Order Date", "db_column_name": "ORDER_DATE",
         "db_column_properties": {"data_type": "DATE"}},
        {"name": "FREIGHT", "db_column_name": "FREIGHT",
         "db_column_properties": {"data_type": "DOUBLE"}}]},
    "DM_DATE": {"name": "DM_DATE", "columns": [
        {"name": "YEAR", "db_column_name": "YEAR",
         "db_column_properties": {"data_type": "INT64"}}]},
}

MODEL = {"model": {
    "name": "Sales",
    "model_tables": [{"name": "DM_ORDER"}, {"name": "DM_DATE"},
                     {"name": "DM_DATE", "alias": "SHIP_DATE"}],
    "formulas": [{"id": "formula_Avg Freight", "name": "Avg Freight",
                  "expr": "average ( [DM_ORDER::FREIGHT] )"}],
    "columns": [
        {"name": "Order Date", "column_id": "DM_ORDER::Order Date",
         "description": "When the order was placed",
         "properties": {"column_type": "ATTRIBUTE", "synonyms": ["placed", "booked"]}},
        {"name": "Freight", "column_id": "DM_ORDER::FREIGHT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "ai_context": "additivity: additive", "index_type": "DONT_INDEX"}},
        {"name": "Ship Year", "column_id": "SHIP_DATE::YEAR",
         "properties": {"column_type": "ATTRIBUTE", "is_hidden": True}},
        {"name": "Avg Freight", "formula_id": "formula_Avg Freight",
         "properties": {"column_type": "MEASURE"}},
    ]}}


def _by_name(rows):
    return {r["Column"]: r for r in rows}


class TestBuildRows:
    def test_one_row_per_column_with_every_field(self):
        rows = build_rows(MODEL, TABLES)
        assert len(rows) == 4 and all(set(r) == set(FIELDS) for r in rows)

    def test_data_type_and_warehouse_column_come_from_the_table(self):
        r = _by_name(build_rows(MODEL, TABLES))["Order Date"]
        assert (r["Source table"], r["Source column"], r["Data type"]) == (
            "DM_ORDER", "ORDER_DATE", "DATE")

    def test_alias_resolves_to_its_physical_table(self):
        r = _by_name(build_rows(MODEL, TABLES))["Ship Year"]
        assert (r["Source table"], r["Data type"], r["Hidden"]) == ("DM_DATE", "INT64", "yes")

    def test_properties_fields_and_root_description(self):
        rows = _by_name(build_rows(MODEL, TABLES))
        assert rows["Order Date"]["Synonyms"] == "placed; booked"
        assert rows["Order Date"]["Description"] == "When the order was placed"
        assert rows["Freight"]["AI context"] == "additivity: additive"
        assert rows["Freight"]["Indexed"] == "no" and rows["Order Date"]["Indexed"] == "yes"
        assert rows["Freight"]["Aggregation"] == "SUM"

    def test_formula_column_carries_its_expression(self):
        r = _by_name(build_rows(MODEL, TABLES))["Avg Freight"]
        assert r["Formula"] == "average ( [DM_ORDER::FREIGHT] )" and r["Source table"] == ""

    def test_sql_view_column_is_sourced_but_untyped(self):
        """A SQL View exports `sql_view_columns` with `sql_output_column` and no data
        type (the live Dunder Mifflin Model's `dm_date_view`)."""
        m = {"model": {"name": "M", "model_tables": [{"name": "dm_date_view"}],
                       "columns": [{"name": "viewDate", "column_id": "dm_date_view::date",
                                    "properties": {"column_type": "ATTRIBUTE"}}]}}
        views = {"dm_date_view": {"name": "dm_date_view", "sql_view_columns": [
            {"name": "date", "sql_output_column": "DATE_COL"}]}}
        r = build_rows(m, views)[0]
        assert (r["Source table"], r["Source column"], r["Data type"]) == (
            "dm_date_view", "DATE_COL", "")

    def test_without_tables_the_type_is_blank_but_every_row_is_there(self):
        rows = _by_name(build_rows(MODEL, None))
        assert len(rows) == 4
        assert rows["Order Date"]["Data type"] == ""
        assert rows["Order Date"]["Source column"] == "Order Date"


class TestCsv:
    def test_header_and_rows_round_trip(self):
        text = to_csv(build_rows(MODEL, TABLES))
        rows = list(csv.DictReader(io.StringIO(text)))
        assert list(rows[0]) == FIELDS and len(rows) == 4
        assert rows[0]["Model"] == "Sales"


class TestSheetTitles:
    def test_invalid_characters_and_length(self):
        t = sheet_titles(["Sales: EU/UK [draft]?", "x" * 40])
        assert t[0] == "Sales_ EU_UK _draft__" and len(t[1]) == 31

    def test_duplicates_are_made_unique_case_insensitively(self):
        t = sheet_titles(["Sales", "sales", "Sales"])
        assert t == ["Sales", "sales (2)", "Sales (3)"]

    def test_long_duplicates_stay_within_31(self):
        t = sheet_titles(["y" * 40, "y" * 40])
        assert all(len(x) <= 31 for x in t) and t[0] != t[1]


def test_xlsx_one_sheet_per_model(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "d.xlsx"
    rows = build_rows(MODEL, TABLES)
    write_xlsx([("Sales", rows), ("Sales", rows[:1])], str(out))
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Sales", "Sales (2)"]
    ws = wb["Sales"]
    assert [c.value for c in ws[1]] == [f for f in FIELDS if f != "Model"]
    assert ws.max_row == 5 and ws.freeze_panes == "A2"


class TestCommand:
    @staticmethod
    def _run(tmp_path, *args):
        from typer.testing import CliRunner
        from ts_cli.cli import app
        (tmp_path / "sales.model.tml").write_text(yaml.safe_dump(MODEL))
        for name, t in TABLES.items():
            (tmp_path / f"{name}.table.tml").write_text(yaml.safe_dump({"table": t}))
        return CliRunner().invoke(app, ["model", "dictionary", "--dir", str(tmp_path), *args])

    def test_json_to_stdout_by_default(self, tmp_path):
        res = self._run(tmp_path)
        assert res.exit_code == 0, res.output
        rows = json.loads(res.stdout)
        assert len(rows) == 4 and _by_name(rows)["Order Date"]["Data type"] == "DATE"

    def test_csv_to_a_file(self, tmp_path):
        out = tmp_path / "d.csv"
        res = self._run(tmp_path, "--format", "csv", "--out", str(out))
        assert res.exit_code == 0 and out.read_text().startswith("Model,Column,")

    def test_xlsx_needs_out(self, tmp_path):
        assert self._run(tmp_path, "--format", "xlsx").exit_code != 0

    def test_unknown_format_is_refused(self, tmp_path):
        assert self._run(tmp_path, "--format", "pdf").exit_code != 0

    def test_input_without_a_model_is_refused(self, tmp_path):
        from typer.testing import CliRunner
        from ts_cli.cli import app
        (tmp_path / "t.table.tml").write_text(yaml.safe_dump({"table": TABLES["DM_DATE"]}))
        res = CliRunner().invoke(app, ["model", "dictionary", "--dir", str(tmp_path)])
        assert res.exit_code != 0
