"""Domo converter — the awkward inputs from the PR #440 review.

Each class here pins a defect that shipped in the first revision: a formula-id
collision that produced a dangling reference, joins invented on incidental columns,
ETL joins counted but dropped, a join side decided by filename order, overlapping
tiles, and a 100%-automation report for a bundle that parsed nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.domo.answers import build_liveboard_artifacts
from ts_cli.domo.build_model import build_model_artifacts
from ts_cli.domo.ir import (
    Card,
    CardQuery,
    Dataset,
    DomoApp,
    DomoColumn,
    Page,
    QueryColumn,
)
from ts_cli.domo.magic_etl import parse_etl
from ts_cli.domo.parsing import parse_app
from ts_cli.domo.report import render_report, _pct

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()

EDGE = str(Path(__file__).parent / "fixtures" / "domo_edge")
FIXTURES = str(Path(__file__).parent / "fixtures" / "domo")


def _ds(name, rows, cols):
    return Dataset(id=name[0].lower(), name=name, rows=rows,
                   columns=[DomoColumn(c, t) for c, t in cols])


class TestFormulaIdCollisions:
    """Two datasets carrying the same Beast Mode name is ordinary in Domo."""

    def test_no_dangling_formula_reference(self):
        arts = build_model_artifacts(parse_app(EDGE), connection_name="C", db="D",
                                     schema="S", model_name="M")
        model = arts["model"]["tml"]["model"]
        ids = {f["id"] for f in model["formulas"]}
        refs = [c["formula_id"] for c in model["columns"] if c.get("formula_id")]
        assert refs, "expected formula columns"
        assert not [r for r in refs if r not in ids], "dangling formula_id — import fails"

    def test_both_formulas_survive_and_the_rename_is_reported(self):
        arts = build_model_artifacts(parse_app(EDGE), connection_name="C", db="D",
                                     schema="S", model_name="M")
        names = [f["name"] for f in arts["mapping"]["beast_modes"]]
        assert "Net Revenue" in names
        renamed = [f for f in arts["mapping"]["beast_modes"] if f["name"] != f["domo_name"]]
        assert renamed, "the colliding formula must be renamed, not dropped"
        assert "renamed from" in renamed[0]["note"]

    def test_formula_ids_are_unique(self):
        model = build_model_artifacts(parse_app(EDGE), connection_name="C", db="D",
                                      schema="S", model_name="M")["model"]["tml"]["model"]
        ids = [f["id"] for f in model["formulas"]]
        assert len(ids) == len(set(ids))


class TestJoinInference:
    def test_one_join_per_dataset_pair(self):
        """Previously one join per shared column — duplicate `with:` entries."""
        app = DomoApp(app_name="P", source="-", extraction_mode="offline")
        app.datasets = [
            _ds("Fact", 90000, [("Order ID", "STRING"), ("Region", "STRING"), ("Date", "DATETIME")]),
            _ds("Dim", 500, [("Order ID", "STRING"), ("Region", "STRING"), ("Date", "DATETIME")]),
        ]
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        assert arts["counts"]["joins"] == 1
        assert arts["mapping"]["joins"][0]["on"] == "Order ID", "must prefer the id-like key"

    def test_incidental_only_pair_is_not_joined_but_is_reported(self):
        app = DomoApp(app_name="P", source="-", extraction_mode="offline")
        app.datasets = [
            _ds("A", 100, [("Region", "STRING"), ("Date", "DATETIME")]),
            _ds("B", 9000, [("Region", "STRING"), ("Date", "DATETIME")]),
        ]
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        assert arts["counts"]["joins"] == 0, "joining on Region/Date fans measures out"
        assert any("incidental" in w for w in arts["mapping"]["join_warnings"])

    def test_join_side_is_row_count_driven_not_dataset_order(self):
        """The side used to be decided by bundle filename sort order."""
        def placement(order):
            app = DomoApp(app_name="S", source="-", extraction_mode="offline")
            app.datasets = [_ds(n, r, [("cid", "STRING")]) for n, r in order]
            model = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                          model_name="M")["model"]["tml"]["model"]
            return [(t["name"], [(j["with"], j["cardinality"]) for j in t.get("joins", [])])
                    for t in model["model_tables"] if t.get("joins")]

        dim_first = placement([("Customers", 100), ("Orders", 10000)])
        fact_first = placement([("Orders", 10000), ("Customers", 100)])
        assert dim_first == fact_first
        assert dim_first == [("Orders", [("Customers", "MANY_TO_ONE")])]


class TestEtlJoinReconciliation:
    def test_unmatched_etl_joins_are_not_counted_as_emitted(self):
        """Magic ETL uses dataflow action names, which need not match dataset names."""
        app = parse_app(FIXTURES)
        etl = parse_etl(json.loads(
            (Path(FIXTURES) / "magic_etl_olist.json").read_text()))
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M", explicit_joins=etl["joins"])
        model = arts["model"]["tml"]["model"]
        emitted = sum(len(t.get("joins", [])) for t in model["model_tables"])
        assert arts["counts"]["joins"] == emitted, "counts must describe what was emitted"
        assert arts["counts"]["joins_dropped"] == len(etl["joins"])
        assert len(arts["mapping"]["joins"]) == emitted
        assert arts["mapping"]["join_warnings"]

    def test_dropped_joins_reach_the_report(self):
        app = parse_app(FIXTURES)
        etl = parse_etl(json.loads(
            (Path(FIXTURES) / "magic_etl_olist.json").read_text()))
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M", explicit_joins=etl["joins"])
        md = render_report(arts["mapping"], None)
        review = md.split("## Manual review")[1]
        assert "Join not emitted" in review

    def test_malformed_etl_export_does_not_raise(self):
        out = parse_etl({"data": {"actions": [{"type": "LoadFromVault", "name": "X"}]}})
        assert out["tables"] == []
        assert any("no 'id'" in n for n in out["notes"])


class TestCardAggregation:
    def test_non_sum_aggregation_is_flagged(self):
        """A MIN card would otherwise render as SUM via the Model default."""
        card = [c for c in parse_app(EDGE).cards if c.urn == "500001"]
        assert card, "edge fixture card missing"
        arts = build_liveboard_artifacts(parse_app(EDGE), model_name="M")
        row = arts["mapping"]["cards"][0]
        assert row["status"] == "Approximated"
        assert "MIN" in row["note"]


class TestTileLayout:
    def test_tiles_do_not_overlap_when_a_short_tile_wraps(self):
        app = DomoApp(app_name="L", source="-", extraction_mode="offline")
        specs = [(6, 5), (6, 5), (6, 2), (6, 2)]
        app.cards = [
            Card(urn=str(i), title=f"C{i}", chart_type="table", pref_width=w,
                 pref_height=h,
                 query=CardQuery(group_by=["G"],
                                 columns=[QueryColumn(column="M", aggregation="SUM")]))
            for i, (w, h) in enumerate(specs)]
        app.pages = [Page(id="p", name="P", card_ids=[str(i) for i in range(len(specs))])]
        tiles = build_liveboard_artifacts(app, model_name="M")[
            "liveboard"]["tml"]["liveboard"]["layout"]["tiles"]

        def overlap(a, b):
            return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                        or a["y"] + a["height"] <= b["y"]
                        or b["y"] + b["height"] <= a["y"])

        clashes = [(tiles[i]["visualization_id"], tiles[j]["visualization_id"])
                   for i in range(len(tiles)) for j in range(i + 1, len(tiles))
                   if overlap(tiles[i], tiles[j])]
        assert not clashes, f"overlapping tiles: {clashes}"


class TestEmptyParse:
    def test_pct_of_nothing_is_zero_not_one_hundred(self):
        assert _pct(0, 0) == 0

    def test_empty_bundle_does_not_report_a_clean_conversion(self):
        md = render_report({}, None)
        assert "Nothing was parsed" in md
        assert "Automation %:** 100%" not in md
        assert "clean conversion" not in md


class TestModeRejection:
    def test_domo_cloud_mode_is_refused(self, tmp_path):
        """Recording an un-implemented mode put false provenance in a customer report."""
        result = runner.invoke(app, ["domo", "parse", EDGE, "--mode", "domo-cloud",
                                     "--output", str(tmp_path / "i.json")])
        assert result.exit_code == 2
        assert "Only 'offline' is implemented" in (
            result.output + getattr(result, "stderr", ""))

    def test_report_before_build_model_is_a_clean_error(self, tmp_path):
        result = runner.invoke(app, ["domo", "report", "--output-dir", str(tmp_path)])
        assert result.exit_code == 2
        assert "build-model" in (result.output + getattr(result, "stderr", ""))


class TestEdgeBundleImportsCleanly:
    def test_emitted_tml_is_valid_yaml_with_no_invariant_findings(self, tmp_path):
        common = ["--connection", "C", "--database", "DB", "--schema", "S"]
        r = runner.invoke(app, ["domo", "build-model", EDGE, *common,
                                "--model-name", "Edge", "--output-dir", str(tmp_path)])
        assert r.exit_code == 0, r.stdout + getattr(r, "stderr", "")
        mapping = json.loads((tmp_path / "mapping.json").read_text())
        assert mapping["invariant_findings"] == []
        for f in tmp_path.glob("*.tml"):
            yaml.safe_load(f.read_text())
