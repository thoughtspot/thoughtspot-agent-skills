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

import report_browser

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

def test_pre_cutover_payload_derives_categories_and_reads_the_catalog():
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    payload = compact_payload(copy.deepcopy(data))
    labels = [c["label"] for c in payload["G"]["categories"]]
    assert labels == LABELS
    # categories derived from the legacy angle when the finding has none
    assert [f["c"] for f in payload["F"]] == [["A"], ["P"], ["D"], ["H"]]
    # the run's own check text is kept; remediation and views come from the catalog
    assert payload["K"]["A1"]["t"] == "Spotter-ready >= 95% / General >= 50%; HIGH below half"
    assert payload["K"]["D8"]["r"].startswith("Run /ts-dependency-manager")
    assert payload["G"]["views"]["cleanup"] == ["H4", "H5", "H10"]
    assert "fn" not in payload["C"]  # no fetched_needs record in old JSON


LABELS = ["AI Readiness", "Data Modeling", "Human Readiness", "Performance", "Security"]
_MODEL_1 = "model/00000000-0000-4000-8000-000000000001"
needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")


def _render_problems(html_text: str, tmp_path) -> list:
    """What is wrong with the rendered report: JS errors, or a category label missing
    from the rendered page (the dashboard heatmap and a Model's sections — the text
    the template builds, never the embedded JSON)."""
    problems = []
    for route in ("", _MODEL_1):
        out = report_browser.render(html_text, tmp_path, route)
        problems += [f"#{route}: JS error: {e}" for e in out["errors"]]
        problems += [f"#{route}: label '{lab}' not rendered" for lab in LABELS
                     if lab not in out["text"]]
    return problems


@needs_chrome
def test_report_renders_pre_cutover_json(tmp_path):
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html
    assert _render_problems(html, tmp_path) == []


@needs_chrome
def test_render_check_fails_on_a_throwing_template(tmp_path, monkeypatch):
    """The render check bites: a template that throws while building its category
    maps leaves no label on the page, and the error is reported."""
    import ts_cli.audit.report as report_mod
    template = report_mod.TEMPLATE_PATH.read_text(encoding="utf-8")
    anchor = "CATEGORIES.forEach(function(c){"
    assert template.count(anchor) == 1
    broken = tmp_path / "broken_template.html"
    broken.write_text(template.replace(anchor, anchor + ' throw new Error("probe");'),
                      encoding="utf-8")
    monkeypatch.setattr(report_mod, "TEMPLATE_PATH", broken)
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    problems = _render_problems(render_report(data), tmp_path)
    assert any("JS error" in p and "probe" in p for p in problems), problems
    assert any("not rendered" in p for p in problems), problems


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


def _p_only_client(model):
    from unittest.mock import MagicMock

    import yaml

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
    return client


def test_a_run_fetches_only_what_its_rules_need_and_records_it():
    """A P-only run: no P rule reads AI instructions or Sets, so neither is fetched
    for the report's sake (ruling, fix round 1) — and the corpus says so."""
    from unittest.mock import patch

    from ts_cli.audit import data_needs, run_audit
    assert not {"ai_instructions", "sets"} & data_needs(["P"])
    model = {"guid": "m1", "model": {"name": "Sales", "model_tables": [
        {"name": "ORDERS", "fqn": "t1"}], "columns": [], "formulas": []}}
    client = _p_only_client(model)
    with patch("ts_cli.audit.context.discover_sets") as disc:
        out = run_audit(client, ["m1"], ["P"])
    disc.assert_not_called()
    assert not any(c.args[0].endswith("/ai/instructions/get")
                   for c in client.post.call_args_list)
    assert out["corpus"]["fetched_needs"] == ["dependents", "metadata", "model_tml",
                                              "table_tml"]
    assert out["corpus"]["models"][0]["ai_analysis"]["questions"] == []
    with patch("ts_cli.audit.context.discover_sets",
               return_value={"sets": {}, "incomplete": [], "notes": []}):
        out_a = run_audit(_p_only_client(model), ["m1"], ["A", "H"])
    assert {"ai_instructions", "answers", "sets"} <= set(out_a["corpus"]["fetched_needs"])
    assert out_a["corpus"]["models"][0]["ai_analysis"]["questions"] == [
        "Revenue means net revenue"]


def _with_fetched(needs):
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    if needs is not None:
        data["corpus"]["fetched_needs"] = sorted(needs)
    return render_report(data)


_ALWAYS = {"dependents", "metadata", "model_tml", "table_tml"}


@needs_chrome
def test_report_says_not_collected_for_data_the_run_did_not_fetch(tmp_path):
    out = report_browser.render(_with_fetched(_ALWAYS), tmp_path, _MODEL_1)
    assert out["errors"] == []
    assert "Business Questions" in out["text"]
    assert out["text"].count("Not collected for this selection") == 2  # questions, Sets
    assert "None — no AI instructions on this Model." not in out["text"]


@needs_chrome
def test_report_says_none_for_data_collected_and_empty(tmp_path):
    out = report_browser.render(_with_fetched(_ALWAYS | {"ai_instructions", "sets"}),
                                tmp_path, _MODEL_1)
    assert out["errors"] == []
    assert "None — no AI instructions on this Model." in out["text"]
    assert "Not collected for this selection" not in out["text"]


@needs_chrome
def test_report_without_a_fetched_record_renders_as_before(tmp_path):
    out = report_browser.render(_with_fetched(None), tmp_path, _MODEL_1)
    assert out["errors"] == []
    assert "Not collected" not in out["text"]
    assert "Business Questions" not in out["text"]  # empty questions: no section, as before


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


def test_replay_records_what_the_snapshot_captured(tmp_path):
    from ts_cli.commands.audit import _replay
    snap = _snap(tmp_path, ["D"], needs=set())
    assert _replay(snap, ["D"], None)["corpus"]["fetched_needs"] == sorted(_ALWAYS)
    legacy = tmp_path / "legacy"
    from ts_cli.audit.snapshot import write_snapshot
    write_snapshot(fx.registry_populated_context(), legacy, ["A", "D"])
    assert _replay(legacy, ["D"], None)["corpus"]["fetched_needs"] == \
        sorted(_ALWAYS | {"ai_instructions"})


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


# ── review fix round 1: degenerate --angles ─────────────────────────────────

def test_cli_empty_angle_selection_is_a_usage_error(tmp_path):
    from typer.testing import CliRunner

    from ts_cli.cli import app
    snap = _snap(tmp_path, ["A", "D"], needs={"ai_instructions"})
    for value in (",", " , ,"):
        res = CliRunner().invoke(app, ["audit", "run", "--snapshot-in", str(snap),
                                       "--angles", value])
        assert res.exit_code == 2 and "no category given" in res.output, res.output


def test_duplicate_angles_run_once_and_are_listed_once(tmp_path):
    from typer.testing import CliRunner

    from ts_cli.audit import run_audit
    from ts_cli.cli import app
    snap = _snap(tmp_path, ["A", "D"], needs={"ai_instructions"})
    out = tmp_path / "o.json"
    res = CliRunner().invoke(app, ["audit", "run", "--snapshot-in", str(snap),
                                   "--angles", "A,a,A", "-o", str(out)])
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text())
    assert data["corpus"]["angles_run"] == ["A"] and data["summary"]["checks_run"] == 6
    direct = run_audit(None, [], ["D", "A", "D"], ctx=fx.registry_populated_context())
    assert direct["corpus"]["angles_run"] == ["D", "A"]
