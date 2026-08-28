"""Tests for the `ts domo` converter, run against tests/fixtures/domo/."""
import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr
    runner = CliRunner()

FIXTURES = str(Path(__file__).parent / "fixtures" / "domo")


def test_parse_writes_inventory(tmp_path):
    out = tmp_path / "inv.json"
    result = runner.invoke(app, ["domo", "parse", FIXTURES, "--output", str(out)])
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    inv = json.loads(out.read_text())
    assert inv["counts"] == {"datasets": 2, "beast_modes": 3, "cards": 3, "pages": 1}
    assert inv["app_name"] == "Sales Overview"


def test_parse_missing_dir_is_graceful(tmp_path):
    out = tmp_path / "inv.json"
    result = runner.invoke(app, ["domo", "parse", str(tmp_path / "nope"), "--output", str(out)])
    # never crashes; emits an empty-but-valid inventory with a warning note
    assert result.exit_code == 0
    inv = json.loads(out.read_text())
    assert inv["counts"]["datasets"] == 0
    assert any(n["area"] == "parse" for n in inv["notes"])


def _build_model(tmp_path):
    result = runner.invoke(app, [
        "domo", "build-model", FIXTURES, "--connection", "Conn",
        "--database", "DB", "--schema", "SCH", "--model-name", "Sales Model",
        "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    return json.loads((tmp_path / "mapping.json").read_text())


def test_build_model_translates_beast_modes(tmp_path):
    mapping = _build_model(tmp_path)
    by_name = {f["name"]: f for f in mapping["beast_modes"]}
    assert by_name["Net Revenue"]["ts_formula"] == "sum([Revenue]) - sum([Discount])"
    assert by_name["Avg Order Value"]["ts_formula"] == \
        "sum([Revenue]) / unique count([Transaction ID])"
    assert all(f["status"] == "Migrated" for f in mapping["beast_modes"])


def test_build_model_flags_inferred_join(tmp_path):
    mapping = _build_model(tmp_path)
    assert len(mapping["joins"]) == 1
    j = mapping["joins"][0]
    assert j["on"] == "Customer ID" and j["inferred"] and j["status"] == "NEEDS REVIEW"


def test_build_model_tml_invariants(tmp_path):
    _build_model(tmp_path)
    # every table column carries db_column_name; connection uses name: only
    for tbl_file in tmp_path.glob("*.table.tml"):
        doc = yaml.safe_load(tbl_file.read_text())["table"]
        assert "fqn" not in doc["connection"]
        for col in doc["columns"]:
            assert col["db_column_name"], f"missing db_column_name in {tbl_file.name}"
    # model: formula columns pair to formulas[] by id
    model_doc = yaml.safe_load((tmp_path / "Sales_Model.model.tml").read_text())["model"]
    formula_ids = {f["id"] for f in model_doc["formulas"]}
    for col in model_doc["columns"]:
        if "formula_id" in col:
            assert col["formula_id"] in formula_ids


def test_build_liveboard_chart_types(tmp_path):
    result = runner.invoke(app, [
        "domo", "build-liveboard", FIXTURES, "--model-name", "Sales Model",
        "--report-name", "Sales Overview", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    lb = yaml.safe_load((tmp_path / "Sales_Overview.liveboard.tml").read_text())["liveboard"]
    vizzes = {v["answer"]["name"]: v["answer"] for v in lb["visualizations"]}
    assert vizzes["Net Revenue"]["chart"]["type"] == "KPI"
    assert vizzes["Revenue by Region"]["chart"]["type"] == "BAR"
    # table card -> TABLE_MODE (no chart block)
    assert vizzes["Sales Rep Performance"]["display_mode"] == "TABLE_MODE"
    assert "chart" not in vizzes["Sales Rep Performance"]
    # page card order preserved, all three resolved
    assert len(lb["visualizations"]) == 3


# ---------------------------------------------------------------------------
# Dropped-construct reporting (open-items #11)
#
# The converter does not emit card sort / filters / quick filters / conditional
# formatting / number formats. That is a documented gap — but it must never be a
# SILENT one, or the migration report tells the user a card migrated cleanly when
# half its query was left behind.
# ---------------------------------------------------------------------------

def test_cards_with_dropped_constructs_are_not_reported_migrated(tmp_path):
    """A fixture card carries a sort, a LAST_90_DAYS filter and a quick filter."""
    from ts_cli.domo.answers import build_liveboard_artifacts
    from ts_cli.domo.parsing import parse_app

    arts = build_liveboard_artifacts(parse_app(FIXTURES), model_name="M")
    cards = {c["title"]: c for c in arts["mapping"]["cards"]}

    bar = cards["Revenue by Region"]
    assert bar["status"] == "Approximated", "dropped constructs must downgrade the card"
    assert "Total Revenue DESCENDING" in bar["note"]
    assert "LAST_90_DAYS" in bar["note"]
    assert "Product Category" in bar["note"]
    assert set(bar["dropped_constructs"]) and all(
        isinstance(d, str) for d in bar["dropped_constructs"])

    # No card in this bundle should claim a clean migration.
    assert not [c for c in arts["mapping"]["cards"] if c["status"] == "Migrated"]


def test_dropped_constructs_reach_the_migration_report():
    from ts_cli.domo.answers import build_liveboard_artifacts
    from ts_cli.domo.build_model import build_model_artifacts
    from ts_cli.domo.parsing import parse_app
    from ts_cli.domo.report import render_report

    app = parse_app(FIXTURES)
    model = build_model_artifacts(app, connection_name="C", db="D", schema="S")
    lb = build_liveboard_artifacts(app, model_name="M")
    md = render_report(model["mapping"], lb["mapping"])

    review = md.split("## Manual review")[1].split("## Verification")[0]
    assert "Revenue by Region" in review
    assert "LAST_90_DAYS" in review
    # Automation % must not claim the cards came across cleanly.
    assert "**Automation %:** 89%" not in md


def test_card_with_no_extra_constructs_stays_migrated():
    """Guard the other direction — the downgrade must be construct-driven, not blanket.

    The app needs a dataset: a card whose columns belong to no dataset is genuinely
    unbindable and is (correctly) flagged for that instead.
    """
    from ts_cli.domo.answers import build_liveboard_artifacts
    from ts_cli.domo.ir import (
        Card, CardQuery, Dataset, DomoApp, DomoColumn, Page, QueryColumn,
    )

    app = DomoApp(app_name="Clean", source="-", extraction_mode="offline")
    app.datasets = [Dataset(id="d", name="T", rows=10, columns=[
        DomoColumn("Region", "STRING"), DomoColumn("Revenue", "DOUBLE")])]
    app.cards = [Card(urn="1", title="Plain", chart_type="table", data_set_id="d",
                      query=CardQuery(group_by=["Region"],
                                      columns=[QueryColumn(column="Revenue",
                                                           aggregation="SUM")]))]
    app.pages = [Page(id="p", name="P", card_ids=["1"])]
    card = build_liveboard_artifacts(app, model_name="M")["mapping"]["cards"][0]
    assert card["status"] == "Migrated"
    assert card["dropped_constructs"] == []
