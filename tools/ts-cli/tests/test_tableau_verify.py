"""Unit tests for ts_cli.tableau.verify — the source<->output migration fidelity gate.

Fixture-based: synthetic `parsed` (ts tableau parse output shape) and `model_tml`
dicts are constructed directly, matching the flattened single-datasource shape
(top-level tables/columns/joins/calculated_fields). No live Tableau/ThoughtSpot
connection and no real .twb file is needed for the pure-function tests.

The CliRunner test at the bottom drives the real `ts tableau verify` command
end-to-end (through an actual `ts tableau parse` on a tiny synthetic .twb) to
catch a wiring regression between the command and the pure module.
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.tableau.verify import (
    _similarity,
    normalize_expr,
    verify_conversion,
    verify_conversion_dir,
)

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr is separated by default)
    runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _calc(name: str, formula: str, role: str = "measure", datatype: str = "real") -> dict:
    return {"name": name, "caption": name, "formula": formula, "role": role,
            "datatype": datatype, "internal_name": name}


def _parsed(tables=None, calcs=None, joins=None, sql_views=None) -> dict:
    """Flattened single-datasource `parsed` shape."""
    return {
        "name": "Orders",
        "tables": tables if tables is not None else [{"name": "ORDERS", "db_table": "db.s.ORDERS"}],
        "sql_views": sql_views or [],
        "columns": [],
        "joins": joins or [],
        "calculated_fields": calcs or [],
        "orphan_calcs": [],
        "calc_map": {},
    }


def _model_tml(model_tables=None, formulas=None, columns=None, name="Orders") -> dict:
    return {
        "model": {
            "name": name,
            "model_tables": model_tables if model_tables is not None else [{"name": "ORDERS"}],
            "formulas": formulas or [],
            "columns": columns or [],
        }
    }


def _formula_column(name: str, formula_id: str) -> dict:
    return {"name": name, "formula_id": formula_id,
            "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}


# ---------------------------------------------------------------------------
# _similarity unit tests
# ---------------------------------------------------------------------------

def test_similarity_identical_is_one():
    tokens = ["sum", "(", "[amount]", ")"]
    assert _similarity(tokens, list(tokens)) == 1.0


def test_similarity_disjoint_is_near_zero():
    a = ["sum", "(", "[amount]", ")"]
    b = ["alpha", "beta", "gamma", "delta"]
    assert _similarity(a, b) == 0.0


def test_similarity_partial_is_in_between():
    a = ["sum", "(", "[amount]", ")"]
    b = ["average", "(", "[amount]", ")"]
    sim = _similarity(a, b)
    assert 0.2 < sim < 1.0


def test_similarity_both_empty_is_one():
    assert _similarity([], []) == 1.0


def test_similarity_one_empty_is_zero():
    assert _similarity(["sum"], []) == 0.0


# ---------------------------------------------------------------------------
# normalize_expr — spot checks that matter for the similarity comparisons
# ---------------------------------------------------------------------------

def test_normalize_strips_table_qualifier():
    assert normalize_expr("sum ( [ORDERS::Amount] )") == ["sum", "(", "[amount]", ")"]


def test_normalize_resolves_formula_prefix():
    assert normalize_expr("[formula_Revenue Growth]") == ["[formula::revenue growth]"]


def test_normalize_maps_countd_to_two_tokens():
    assert normalize_expr("COUNTD([CustomerID])") == ["unique", "count", "(", "[customerid]", ")"]


# ---------------------------------------------------------------------------
# verify_conversion — clean conversion
# ---------------------------------------------------------------------------

def test_clean_conversion_is_ok():
    parsed = _parsed(calcs=[_calc("Total Amount", "SUM([Amount])")])
    model = _model_tml(
        formulas=[{"id": "formula_Total Amount", "name": "Total Amount",
                  "expr": "sum ( [ORDERS::Amount] )"}],
        columns=[_formula_column("Total Amount", "formula_Total Amount")],
    )
    report = verify_conversion(parsed, model)
    assert report["ok"] is True
    for check in report["checks"]:
        assert all(f["severity"] != "ERROR" for f in check["findings"])
    # A MATCH — the raw formula and its translation are token-equivalent.
    eq = next(c for c in report["checks"] if c["name"] == "formula_equivalence")
    assert eq["comparisons"][0]["status"] == "MATCH"


# ---------------------------------------------------------------------------
# The key correctness proof: a translatable drop IS flagged; an untranslatable/
# query-time formula legitimately absent from the model is NOT.
# ---------------------------------------------------------------------------

def test_translatable_drop_is_flagged_but_untranslatable_absence_is_not():
    parsed = _parsed(calcs=[
        _calc("Total Amount", "SUM([Amount])"),           # translatable — DROPPED below
        _calc("Geo", "MAKEPOINT([Lat],[Lon])", role="dimension", datatype="string"),  # untranslatable
    ])
    # model.formulas is empty: "Total Amount" is missing (a real drop); "Geo" is
    # ALSO missing, but it's untranslatable so its absence is correct, not a drop.
    model = _model_tml(formulas=[], columns=[])

    report = verify_conversion(parsed, model)

    structural = next(c for c in report["checks"] if c["name"] == "structural")
    assert structural["severity"] == "ERROR"
    error_text = " ".join(f["message"] for f in structural["findings"] if f["severity"] == "ERROR")
    assert "Total Amount" in error_text
    assert "Geo" not in error_text  # the untranslatable formula must NOT be named as a drop

    eq = next(c for c in report["checks"] if c["name"] == "formula_equivalence")
    geo_comparison = next(c for c in eq["comparisons"] if c["name"] == "Geo")
    assert geo_comparison["status"] == "SKIPPED (untranslatable)"
    total_comparison = next(c for c in eq["comparisons"] if c["name"] == "Total Amount")
    assert total_comparison["status"] == "MISSING"

    assert report["ok"] is False


# ---------------------------------------------------------------------------
# Fix #B — a calc field renamed by the column/formula name-clash safety net
# (naming.py::detect_name_clashes, "Formula <X>") must NOT be flagged as a
# silent drop. Live-reproduced on Ads Commercial Dashboard: a "Region" calc
# (parameter_ref tier) collides with a physical column's internal name
# (col_table_map key "Region", from a column whose OWN display caption is
# "Delivery Region" — the clash is on the internal name, not the caption) and
# is auto-renamed to "Formula Region" at generation time — correctly emitted,
# but verify didn't know the rename recipe and reported "Region" missing.
# ---------------------------------------------------------------------------

def test_column_formula_name_clash_rename_is_not_flagged_as_drop():
    parsed = _parsed(calcs=[
        _calc("Region", "IF [Parameters].[Parameter 2] = 'On' THEN [Region] ELSE '' END",
              role="dimension", datatype="string"),
    ])
    parsed["col_table_map"] = {"Region": "AGG_PARTNER_DELIVERY_DAILY"}
    model = _model_tml(
        formulas=[{"id": "formula_Formula Region", "name": "Formula Region",
                  "expr": "if ( [AGG_PARTNER_DELIVERY_DAILY::Region] = 'On' ) "
                          "then [AGG_PARTNER_DELIVERY_DAILY::Region] else ''"}],
        columns=[_formula_column("Formula Region", "formula_Formula Region")],
    )

    report = verify_conversion(parsed, model)

    structural = next(c for c in report["checks"] if c["name"] == "structural")
    assert structural["severity"] != "ERROR", structural["findings"]
    assert not any("Region" in f["message"] for f in structural["findings"])
    assert report["ok"] is True, report


def test_name_clash_rename_still_flags_a_genuine_drop():
    """The clash-rename allowance must not blanket-suppress real drops: if
    NEITHER the original nor the "Formula <X>" name is present, it's still a
    drop."""
    parsed = _parsed(calcs=[
        _calc("Region", "IF [Parameters].[Parameter 2] = 'On' THEN [Region] ELSE '' END",
              role="dimension", datatype="string"),
    ])
    parsed["col_table_map"] = {"Region": "AGG_PARTNER_DELIVERY_DAILY"}
    model = _model_tml(formulas=[])  # neither "Region" nor "Formula Region" present

    report = verify_conversion(parsed, model)

    structural = next(c for c in report["checks"] if c["name"] == "structural")
    assert structural["severity"] == "ERROR"
    assert any("Region" in f["message"] for f in structural["findings"])
    assert report["ok"] is False


# ---------------------------------------------------------------------------
# Formula equivalence — garbled TML translation scores LOW/PARTIAL
# ---------------------------------------------------------------------------

def test_garbled_translation_is_low_similarity():
    parsed = _parsed(calcs=[_calc("Total Amount", "SUM([Amount])")])
    model = _model_tml(
        formulas=[{"id": "formula_Total Amount", "name": "Total Amount",
                  "expr": "count ( [ORDERS::CustomerID] ) + rank ( )"}],
        columns=[_formula_column("Total Amount", "formula_Total Amount")],
    )
    report = verify_conversion(parsed, model)
    eq = next(c for c in report["checks"] if c["name"] == "formula_equivalence")
    comparison = eq["comparisons"][0]
    assert comparison["status"] in ("LOW", "PARTIAL")
    assert any("Total Amount" in f["message"] for f in eq["findings"])


# ---------------------------------------------------------------------------
# Structural — a dropped physical table
# ---------------------------------------------------------------------------

def test_dropped_physical_table_is_flagged():
    parsed = _parsed(tables=[
        {"name": "ORDERS", "db_table": "db.s.ORDERS"},
        {"name": "CUSTOMERS", "db_table": "db.s.CUSTOMERS"},
    ])
    model = _model_tml(model_tables=[{"name": "ORDERS"}])  # CUSTOMERS dropped

    report = verify_conversion(parsed, model)
    structural = next(c for c in report["checks"] if c["name"] == "structural")
    assert structural["severity"] == "ERROR"
    assert any("CUSTOMERS" in f["message"] for f in structural["findings"])
    assert report["ok"] is False


# ---------------------------------------------------------------------------
# Validity — reuses tml_lint.py; a genuine invariant violation surfaces here
# ---------------------------------------------------------------------------

def test_validity_reuses_tml_lint_i1():
    parsed = _parsed(calcs=[])
    # An orphan formula (no paired columns[] entry) — this is exactly I1 from
    # tml_lint.lint_tml; verify.py must not re-derive this itself.
    model = _model_tml(formulas=[{"id": "formula_Orphan", "name": "Orphan", "expr": "1"}],
                       columns=[])
    report = verify_conversion(parsed, model)
    validity = next(c for c in report["checks"] if c["name"] == "validity")
    assert validity["severity"] == "ERROR"
    assert any(f["message"].startswith("I1:") for f in validity["findings"])


# ---------------------------------------------------------------------------
# Limitation coverage — advisory only (no limitations-list input in our flow)
# ---------------------------------------------------------------------------

def test_limitation_coverage_is_advisory_never_error():
    parsed = _parsed(calcs=[_calc("Geo", "MAKEPOINT([Lat],[Lon])", role="dimension",
                                  datatype="string")])
    model = _model_tml(formulas=[], columns=[])
    report = verify_conversion(parsed, model)
    limitation = next(c for c in report["checks"] if c["name"] == "limitation_coverage")
    assert limitation["severity"] in ("WARNING", "OK")
    assert limitation["stats"]["untranslatable_detected"] == 1


# ---------------------------------------------------------------------------
# verify_conversion_dir — pure aggregation across N models (`verify --dir`)
# ---------------------------------------------------------------------------

def test_verify_conversion_dir_all_clean_is_ok():
    parsed = _parsed(calcs=[_calc("Total Amount", "SUM([Amount])")])
    clean_model = _model_tml(
        formulas=[{"id": "formula_Total Amount", "name": "Total Amount",
                  "expr": "sum ( [ORDERS::Amount] )"}],
        columns=[_formula_column("Total Amount", "formula_Total Amount")],
    )
    models = [("a.model.tml", clean_model), ("b.model.tml", clean_model),
              ("c.model.tml", clean_model)]

    agg = verify_conversion_dir(parsed, models)

    assert agg["ok"] is True
    assert agg["summary"]["n_models"] == 3
    assert agg["summary"]["errors"] == 0
    assert agg["summary"]["models_with_errors"] == []
    assert [m["model_file"] for m in agg["models"]] == ["a.model.tml", "b.model.tml", "c.model.tml"]
    # Each entry carries the full per-model report shape (not just a summary).
    assert all("checks" in m and "summary" in m for m in agg["models"])


def test_verify_conversion_dir_aggregates_errors_and_worst_finding_gates_ok():
    parsed = _parsed(calcs=[_calc("Total Amount", "SUM([Amount])")])
    clean_model = _model_tml(
        formulas=[{"id": "formula_Total Amount", "name": "Total Amount",
                  "expr": "sum ( [ORDERS::Amount] )"}],
        columns=[_formula_column("Total Amount", "formula_Total Amount")],
    )
    # "Total Amount" never emitted here -> structural ERROR (a genuine drop).
    broken_model = _model_tml(formulas=[], columns=[])
    models = [("clean.model.tml", clean_model), ("broken.model.tml", broken_model)]

    agg = verify_conversion_dir(parsed, models)

    assert agg["ok"] is False  # gated by the single broken model
    assert agg["summary"]["n_models"] == 2
    assert agg["summary"]["errors"] >= 1
    assert agg["summary"]["models_with_errors"] == ["broken.model.tml"]
    clean_entry = next(m for m in agg["models"] if m["model_file"] == "clean.model.tml")
    broken_entry = next(m for m in agg["models"] if m["model_file"] == "broken.model.tml")
    assert clean_entry["ok"] is True
    assert broken_entry["ok"] is False


def test_verify_conversion_dir_empty_models_is_ok_with_zero_count():
    agg = verify_conversion_dir(_parsed(), [])
    assert agg["ok"] is True
    assert agg["summary"]["n_models"] == 0
    assert agg["models"] == []


# ---------------------------------------------------------------------------
# CliRunner — the real `ts tableau verify` command, end to end
# ---------------------------------------------------------------------------

_SMOKE_TWB = """<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[Amount]' datatype='real' role='measure' caption='Amount'/>
    <column name='[Calculation_1]' caption='Total Amount' datatype='real'>
      <calculation class='tableau' formula='SUM([Amount])'/>
    </column>
  </datasource>
</workbook>
"""


def test_cli_verify_clean(tmp_path):
    twb = tmp_path / "smoke.twb"
    twb.write_text(_SMOKE_TWB)
    parsed_path = tmp_path / "parsed.json"
    r1 = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(parsed_path)])
    assert r1.exit_code == 0, r1.stdout + r1.stderr

    model_path = tmp_path / "orders.model.tml"
    model_path.write_text(json.dumps({
        "model": {
            "name": "Orders",
            "model_tables": [{"name": "ORDERS"}],
            "formulas": [{"id": "formula_Total Amount", "name": "Total Amount",
                         "expr": "sum ( [ORDERS::Amount] )"}],
            "columns": [_formula_column("Total Amount", "formula_Total Amount")],
        }
    }))

    result = runner.invoke(app, ["tableau", "verify", "--parse", str(parsed_path),
                                "--model", str(model_path)])
    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True


def test_cli_verify_flags_drop_and_exits_nonzero(tmp_path):
    twb = tmp_path / "smoke.twb"
    twb.write_text(_SMOKE_TWB)
    parsed_path = tmp_path / "parsed.json"
    r1 = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(parsed_path)])
    assert r1.exit_code == 0, r1.stdout + r1.stderr

    model_path = tmp_path / "orders.model.tml"
    # "Total Amount" is translatable but never emitted — a genuine silent drop.
    model_path.write_text(json.dumps({
        "model": {"name": "Orders", "model_tables": [{"name": "ORDERS"}],
                 "formulas": [], "columns": []}
    }))

    # --input is accepted as an alias for --parse, matching build-liveboard's convention.
    result = runner.invoke(app, ["tableau", "verify", "--input", str(parsed_path),
                                "--model", str(model_path)])
    assert result.exit_code != 0
    report = json.loads(result.stdout)
    assert report["ok"] is False
    structural = next(c for c in report["checks"] if c["name"] == "structural")
    assert any("Total Amount" in f["message"] for f in structural["findings"])


# ---------------------------------------------------------------------------
# CliRunner — `ts tableau verify --dir` (Fix C: aggregate every model in one call)
# ---------------------------------------------------------------------------

_CLEAN_MODEL_TML = {
    "model": {
        "name": "Orders",
        "model_tables": [{"name": "ORDERS"}],
        "formulas": [{"id": "formula_Total Amount", "name": "Total Amount",
                     "expr": "sum ( [ORDERS::Amount] )"}],
        "columns": [_formula_column("Total Amount", "formula_Total Amount")],
    }
}

_BROKEN_MODEL_TML = {
    # "Total Amount" is translatable but never emitted — a genuine silent drop.
    "model": {"name": "Orders", "model_tables": [{"name": "ORDERS"}],
             "formulas": [], "columns": []}
}


def _make_parsed(tmp_path) -> Path:
    twb = tmp_path / "smoke.twb"
    twb.write_text(_SMOKE_TWB)
    parsed_path = tmp_path / "parsed.json"
    r1 = runner.invoke(app, ["tableau", "parse", str(twb), "--output", str(parsed_path)])
    assert r1.exit_code == 0, r1.stdout + r1.stderr
    return Path(parsed_path)


def test_cli_verify_dir_aggregates_and_excludes_phase0(tmp_path):
    parsed_path = _make_parsed(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.model.tml").write_text(json.dumps(_CLEAN_MODEL_TML))
    (out / "b.model.tml").write_text(json.dumps(_BROKEN_MODEL_TML))
    # A phase0 base model has no formulas at all — if --dir wrongly included it,
    # it would ALSO report as broken (double-counting the same underlying drop).
    (out / "a.phase0.model.tml").write_text(json.dumps(_BROKEN_MODEL_TML))

    result = runner.invoke(app, ["tableau", "verify", "--parse", str(parsed_path),
                                "--dir", str(out)])
    assert result.exit_code != 0
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["summary"]["n_models"] == 2  # phase0 excluded
    model_files = {Path(m["model_file"]).name for m in report["models"]}
    assert model_files == {"a.model.tml", "b.model.tml"}
    assert Path(report["summary"]["models_with_errors"][0]).name == "b.model.tml"


def test_cli_verify_dir_all_clean_exits_zero(tmp_path):
    parsed_path = _make_parsed(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.model.tml").write_text(json.dumps(_CLEAN_MODEL_TML))
    (out / "b.model.tml").write_text(json.dumps(_CLEAN_MODEL_TML))

    result = runner.invoke(app, ["tableau", "verify", "--parse", str(parsed_path),
                                "--dir", str(out)])
    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["summary"]["n_models"] == 2
    assert report["summary"]["errors"] == 0


def test_cli_verify_dir_no_matching_files_errors(tmp_path):
    parsed_path = _make_parsed(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "orders.table.tml").write_text("table: {}\n")  # no *.model.tml present

    result = runner.invoke(app, ["tableau", "verify", "--parse", str(parsed_path),
                                "--dir", str(out)])
    assert result.exit_code != 0


def test_cli_verify_requires_exactly_one_of_model_or_dir(tmp_path):
    parsed_path = _make_parsed(tmp_path)

    neither = runner.invoke(app, ["tableau", "verify", "--parse", str(parsed_path)])
    assert neither.exit_code != 0

    out = tmp_path / "out"
    out.mkdir()
    (out / "a.model.tml").write_text(json.dumps(_CLEAN_MODEL_TML))
    model_path = tmp_path / "orders.model.tml"
    model_path.write_text(json.dumps(_CLEAN_MODEL_TML))

    both = runner.invoke(app, ["tableau", "verify", "--parse", str(parsed_path),
                              "--model", str(model_path), "--dir", str(out)])
    assert both.exit_code != 0
