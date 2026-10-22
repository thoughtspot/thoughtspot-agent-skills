"""`ts audit run` runs the rule catalog (Task 12a cut-over).

The legacy check modules still exist (12b deletes them); nothing on the `run_audit` /
`ts audit run` / `ts audit report` path may import them.
"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit import generate
from ts_cli.audit.catalog_model import build_catalog, load_catalog, load_raw
from ts_cli.audit.engine.run import run_rules
from ts_cli.audit.findings import Finding, build_summary
from ts_cli.audit.report import compact_payload, metric_bar, render_report

REPO = Path(__file__).resolve().parents[3]
TS_CLI = REPO / "tools" / "ts-cli"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audit"


# ── 1. run_audit runs the catalog ───────────────────────────────────────────

_PROBE = """
import json, sys
sys.path.insert(0, {tests!r})
import audit_rule_fixtures as fx
from ts_cli.audit import run_audit
import ts_cli.commands.audit  # the CLI module too
out = run_audit(None, [], ["A", "D", "H", "P", "S"], "spotter",
                ctx=fx.registry_populated_context())
legacy = sorted(m for m in sys.modules
                if m.startswith("ts_cli.audit.checks_") or m == "ts_cli.audit.assessment")
print(json.dumps({{"legacy": legacy, "ids": sorted({{f["check_id"] for f in out["findings"]}}),
                  "checks_run": out["summary"]["checks_run"],
                  "all_check_ids": out["summary"]["all_check_ids"]}}))
"""


def test_run_audit_uses_catalog():
    """No legacy module is imported, and the findings are the catalog's: the ids that
    fired are exactly those `run_rules` reports, every one an active catalog rule."""
    probe = _PROBE.format(tests=str(Path(__file__).resolve().parent))
    res = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(TS_CLI)})
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["legacy"] == []
    cat = load_catalog()
    active = {r.id for r in cat.rules.values() if r.status == "active"}
    fired = {f.check_id for f in run_rules(fx.registry_populated_context(), cat,
                                           list(cat.categories), "spotter")}
    assert fired and out["ids"] == sorted(fired) and fired <= active
    assert out["checks_run"] == len(active) == len(out["all_check_ids"])
    assert set(out["all_check_ids"]) == active


def test_run_audit_orders_findings_by_the_requested_categories():
    """As the legacy loop did: category by category, in the order asked for."""
    from ts_cli.audit import run_audit
    out = run_audit(None, [], ["S", "A"], "spotter", ctx=fx.registry_populated_context())
    letters = [f["check_id"][0] for f in out["findings"]]
    assert letters == sorted(letters, key=lambda c: {"S": 0, "A": 1}[c]) and set(letters) == {"S", "A"}


# ── 2. a multi-category finding: once in totals, once per category ──────────

def _p18_also_in_d(monkeypatch):
    raw = load_raw()
    for entry in raw["rules/perf.yaml"]:
        if entry["id"] == "P18":
            entry["categories"] = ["D", "P"]
    cat = build_catalog(raw)
    import ts_cli.audit.catalog_model as cm
    monkeypatch.setattr(cm, "load_catalog", lambda root=None: cat)
    return cat


def test_summary_counts_multi_category_once_in_totals(monkeypatch):
    from ts_cli.audit import run_audit
    _p18_also_in_d(monkeypatch)
    ctx = fx.perf_column_count_distinct()
    base = run_audit(None, [], ["D", "P"], "general", ctx=copy.deepcopy(ctx))
    p18 = [f for f in base["findings"] if f["check_id"] == "P18"]
    assert len(p18) == 1 and p18[0]["categories"] == ["D", "P"]
    assert p18[0]["angle"] == "data_modeling"  # its first category's angle_key
    s = base["summary"]
    others = [f for f in base["findings"] if f["check_id"] != "P18"]
    assert sum(s["by_severity"].values()) == len(base["findings"])
    assert s["by_category"]["D"] == 1 + sum("D" in f["categories"] for f in others)
    assert s["by_category"]["P"] == 1 + sum("P" in f["categories"] for f in others)
    assert sum(s["by_category"].values()) == len(base["findings"]) + 1
    assert s["all_check_ids"].count("P18") == 1


def test_build_summary_by_category_unit():
    f = Finding("X1", "data_modeling", "HIGH", "model", "m", "g", "d", categories=["D", "P"])
    s = build_summary([f], 1, 1, 0, categories=["A", "D", "P"])
    assert s["by_severity"]["HIGH"] == 1 and sum(s["by_severity"].values()) == 1
    assert s["by_category"] == {"A": 0, "D": 1, "P": 1}
    assert s["by_angle"]["data_modeling"] == 1


# ── 3. a pre-cut-over audit.json still renders ──────────────────────────────

def test_report_renders_pre_cutover_json():
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    payload = compact_payload(copy.deepcopy(data))
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html
    labels = [c["label"] for c in payload["G"]["categories"]]
    assert labels == ["AI Readiness", "Data Modeling", "Human Readiness", "Performance",
                      "Security"]
    for label in labels:
        assert label in html
    # categories derived from the legacy angle when the finding has none
    assert [f["c"] for f in payload["F"]] == [["A"], ["P"], ["D"], ["H"]]
    # the run's own check text is kept; remediation and views come from the catalog
    assert payload["K"]["A1"]["t"] == "Spotter-ready >= 95% / General >= 50%; HIGH below half"
    assert payload["K"]["D8"]["r"].startswith("Run /ts-dependency-manager")
    assert payload["G"]["views"]["cleanup"] == ["H4", "H5", "H10"]


# ── 4. the metric bar reads the bands ───────────────────────────────────────

def _p8(metric, bands=True):
    f = {"check_id": "P8", "angle": "performance", "severity": "MEDIUM", "metric": metric,
         "threshold": {"max": 75}}
    if bands:
        f["bands"] = {"direction": "lower_is_better", "unit": "count",
                      "levels": [{"op": "gt", "value": 75.0, "severity": "MEDIUM"}],
                      "profile": "general", "provenance": {}}
    return f


def test_metric_bar_lower_is_better():
    bar = metric_bar(_p8(90))
    assert bar["ok"] is False  # 90 columns is over the 75 line: a breach, not "ok"
    assert bar["mark"] == 75 and bar["dir"] == "lower_is_better"
    assert metric_bar(_p8(40))["ok"] is True


def test_metric_bar_higher_is_better_and_legacy_fallback():
    a1 = {"metric": 33.3, "threshold": {"green": 95, "yellow": 47.5},
          "bands": {"direction": "higher_is_better", "unit": "percent",
                    "levels": [{"op": "lt", "value": 47.5, "severity": "HIGH"},
                               {"op": "lt", "value": 95, "severity": "MEDIUM"}]}}
    bar = metric_bar(a1)
    assert (bar["ok"], bar["mark"], bar["unit"], bar["w"]) == (False, 95, "%", 35)
    legacy = metric_bar({"metric": 33.3, "threshold": {"green": 95}})  # pre-cut-over JSON
    assert (legacy["ok"], legacy["mark"], legacy["unit"]) == (False, 95, "%")
    # a legacy dict with no pass mark draws no bar (it used to fall back to 80, wrongly)
    assert metric_bar(_p8(90, bands=False)) is None
    # green below yellow is a lower-is-better dict (D1, P2, P7: HIGH above yellow,
    # MEDIUM above green) — D1 is a code rule with no bands, so this is its bar too
    d1 = metric_bar({"metric": 18, "threshold": {"green": 10, "yellow": 15}, "bands": None})
    assert (d1["ok"], d1["mark"], d1["dir"], d1["unit"]) == (False, 10, "lower_is_better", "")
    assert metric_bar({"metric": 8, "threshold": {"green": 10, "yellow": 15}})["ok"] is True
    assert metric_bar({"metric": None, "threshold": {"green": 95}}) is None


# ── 5. the generated catalog doc is current ─────────────────────────────────

def test_generated_catalog_current():
    assert generate.check(REPO) == []


# ── the report's own needs (REPORT_NEEDS) ───────────────────────────────────

def test_report_needs_cover_what_the_report_reads():
    """Statically, as the catalog gate checks rules: the corpus and ERD builders read
    only conditional data REPORT_NEEDS declares."""
    from ts_cli.audit import REPORT_NEEDS, build_corpus
    from ts_cli.audit.catalog_expr import CONDITIONAL_DATA
    from ts_cli.audit.catalog_reads import static_reads
    from ts_cli.audit.erd import build_erd_for_audit
    assert REPORT_NEEDS <= set(CONDITIONAL_DATA)
    reads = static_reads([build_corpus, build_erd_for_audit])
    assert {"ai_instructions", "dependents", "sets"} <= set(reads)
    assert set(reads) <= REPORT_NEEDS, reads


def test_report_data_is_fetched_when_no_selected_rule_needs_it():
    """A P-only run: no P rule reads AI instructions or Sets, yet the report's Model
    questions, ERD instructions and Set rows are there."""
    from unittest.mock import MagicMock, patch

    import yaml
    from ts_cli.audit import data_needs, run_audit
    assert not {"ai_instructions", "sets"} & data_needs(["P"])

    model = {"guid": "m1", "model": {"name": "Sales", "model_tables": [
        {"name": "ORDERS", "fqn": "t1"}], "columns": [], "formulas": []}}

    def post(url, json=None, **_kw):
        r = MagicMock()
        r.ok, r.status_code = True, 200
        if url.endswith("/metadata/tml/export"):
            r.json.return_value = [{"edoc": yaml.safe_dump(model)}]
        elif url.endswith("/ai/instructions/get"):
            r.json.return_value = {"nl_instructions_info": [
                {"instructions": ["Revenue means net revenue"], "scope": "GLOBAL"}]}
        else:
            r.json.return_value = []
        return r
    client = MagicMock()
    client.post.side_effect = post
    sets = {"sets": {"m1": [{"guid": "s1", "name": "Big customers"}]}, "incomplete": [],
            "notes": []}
    consumers = {"dependents": [], "liveboards": {}, "unreadable": [], "other_types": [],
                 "error": None}
    with patch("ts_cli.audit.context.discover_sets", return_value=sets), \
            patch("ts_cli.audit.context.fetch_consumers", return_value=consumers):
        out = run_audit(client, ["m1"], ["P"])
    [m] = out["corpus"]["models"]
    assert m["ai_analysis"]["questions"] == ["Revenue means net revenue"]
    assert [d["type"] for d in out["corpus"]["dependents"]["m1"]] == ["SET"]


# ── snapshots record what they fetched; replay refuses what is missing ──────

def _snap(tmp_path, angles, needs=None, ctx=None):
    from ts_cli.audit.snapshot import write_snapshot
    snap = tmp_path / "snap"
    write_snapshot(ctx or fx.registry_populated_context(), snap, angles, needs=needs)
    return snap


def test_capture_records_its_needs(tmp_path):
    from ts_cli.audit.snapshot import read_snapshot_needs
    snap = _snap(tmp_path, ["P"], needs={"ai_instructions", "sets"})
    manifest = json.loads((snap / "manifest.json").read_text())
    assert manifest["needs"] == ["ai_instructions", "dependents", "metadata", "model_tml",
                                 "sets", "table_tml"]
    assert read_snapshot_needs(snap)[2] == set(manifest["needs"])


def test_replay_refuses_a_selection_needing_more_than_was_captured(tmp_path):
    from ts_cli.commands.audit import _replay
    snap = _snap(tmp_path, ["A", "D"], needs={"ai_instructions", "dependents"})
    with pytest.raises(SystemExit) as exc:
        _replay(snap, ["D", "H"], None)
    message = str(exc.value)
    assert "H" in message and "not captured" in message and "answers" in message
    assert "H7" in message
    assert _replay(snap, ["D"], None)["summary"]["checks_run"] > 0


def test_replay_of_a_legacy_letter_keyed_manifest(tmp_path):
    """No `needs` in the manifest: read by what its angles fetched before the catalog
    (A: AI instructions; H: Answers and Sets; Model/Table TML, metadata and dependents
    always). An A-only capture replays D (always-fetched data) but refuses H."""
    from ts_cli.audit.snapshot import read_snapshot_needs
    from ts_cli.commands.audit import _replay
    snap = _snap(tmp_path, ["A"])
    assert "needs" not in json.loads((snap / "manifest.json").read_text())
    assert read_snapshot_needs(snap)[2] == {"ai_instructions", "model_tml", "table_tml",
                                            "metadata", "dependents"}
    assert _replay(snap, ["A", "D"], None)["corpus"]["angles_run"] == ["A", "D"]
    with pytest.raises(SystemExit, match="answers, sets"):
        _replay(snap, ["H"], None)
    snap_h = tmp_path / "h"
    from ts_cli.audit.snapshot import write_snapshot
    write_snapshot(fx.registry_populated_context(), snap_h, ["H"])
    assert _replay(snap_h, ["H"], None)["summary"]["checks_run"] == 9


def test_replay_warns_when_the_reports_data_was_not_captured(tmp_path, capsys):
    from ts_cli.commands.audit import _replay
    snap = _snap(tmp_path, ["D"], needs=set())
    _replay(snap, ["D"], None)
    assert "ai_instructions, sets" in capsys.readouterr().err


# ── the CLI validates against the catalog ───────────────────────────────────

def test_cli_rejects_an_unknown_category_and_assessment(tmp_path):
    from typer.testing import CliRunner

    from ts_cli.cli import app
    snap = _snap(tmp_path, ["A", "D", "H", "P", "S"],
                 needs={"ai_instructions", "answers", "sets"})
    runner = CliRunner()
    res = runner.invoke(app, ["audit", "run", "--snapshot-in", str(snap), "--angles", "A,X"])
    assert res.exit_code != 0 and "unknown category X" in res.output
    res = runner.invoke(app, ["audit", "run", "--snapshot-in", str(snap),
                              "--assessment", "strict"])
    assert res.exit_code != 0 and "unknown assessment 'strict'" in res.output
    out = tmp_path / "o.json"
    res = runner.invoke(app, ["audit", "run", "--snapshot-in", str(snap), "--angles", "a, p",
                              "--assessment", "Spotter-ready", "-o", str(out)])
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text())
    assert data["corpus"]["angles_run"] == ["A", "P"]
    assert data["corpus"]["assessment"] == "Spotter-ready"
