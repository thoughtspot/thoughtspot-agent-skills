"""What is generated from the rule catalog (ts_cli/audit/generate.py).

Mapping-valued catalog forms — `message: {by_severity: …}`, `legacy_threshold:
{by_severity: …}`, severity maps, profile overrides and code rules that grade or set
thresholds in code — must render as text, per severity and per profile, never as a
Python data structure.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ts_cli.audit import generate
from ts_cli.audit.catalog_model import load_catalog

REPO = Path(__file__).resolve().parents[3]
_REPR = re.compile(r"\{'|'\}|\{\"|by_severity|Bands\(|Band\(|frozenset|\bNone\b")


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def meta(cat):
    return generate.report_meta(cat)


@pytest.fixture(scope="module")
def doc(cat):
    return generate.catalog_markdown(cat)


def _row(doc: str, rule_id: str) -> str:
    [row] = [ln for ln in doc.splitlines() if ln.startswith(f"| {rule_id} | **")]
    return row


def test_no_data_structure_is_rendered_anywhere(meta, doc):
    for rid, check in meta["checks"].items():
        for key in ("thresholds", "message"):
            assert not _REPR.search(check[key]), (rid, key, check[key])
    assert not _REPR.search(doc), _REPR.search(doc)


def test_message_by_severity_renders_one_entry_per_severity(meta, doc):
    d3 = meta["checks"]["D3"]["message"]
    assert d3 == ("HIGH: “FULL OUTER join causes performance issues”; "
                  "INFO: “{@join_type} join — may indicate data discrepancies”")
    assert "HIGH: “VARCHAR join key(s)" in _row(doc, "D2")


def test_legacy_threshold_by_severity_and_per_profile(doc):
    rows = {ln.split(" | ")[0][2:]: ln for ln in doc.splitlines()
            if re.match(r"\| [A-Z]\d+ \| (?!\*\*)", ln)}
    assert rows["D7"] == "| D7 | MEDIUM: high_overlap=0.5 |"
    # per profile, with {profile_label} rendered as each profile's label
    assert rows["A1"] == ("| A1 | Spotter-ready: green=95, assessment=Spotter-ready, "
                          "yellow=47.5 · General: green=50, assessment=General, yellow=25 |")
    # a code rule that sets its own threshold per finding
    assert rows["D1"] == "| D1 | set per finding by code:model_complexity |"


def test_profile_overrides_render_per_profile(meta):
    assert meta["checks"]["A1"]["thresholds"] == (
        "Spotter-ready: HIGH < 47.5%, MEDIUM < 95% · General: HIGH < 25%, MEDIUM < 50%")
    assert meta["checks"]["A3"]["thresholds"] == "Spotter-ready: HIGH · General: MEDIUM"
    assert meta["checks"]["P7"]["thresholds"] == "HIGH > 5, MEDIUM > 3"


def test_severity_maps_and_code_rules_render_as_text(meta):
    assert meta["checks"]["S2"]["thresholds"] == \
        "INFO when @owning_table_has_rls is true; otherwise HIGH"
    assert meta["checks"]["S5"]["thresholds"] == \
        "HIGH when @credential_term is token; otherwise CRITICAL"
    assert meta["checks"]["D1"]["thresholds"] == "graded in code:model_complexity — HIGH, MEDIUM"
    assert meta["checks"]["A5"]["thresholds"] == "HIGH < 50, MEDIUM < 80"
    assert meta["checks"]["D10"]["thresholds"] == \
        "INFO when @zero_column_role is bridge; otherwise MEDIUM"


def test_report_meta_shape(cat, meta):
    assert [c["id"] for c in meta["categories"]] == ["A", "D", "H", "P", "S"]
    assert meta["categories"][0]["label"] == "AI Readiness"
    assert {p["id"] for p in meta["profiles"]} == set(cat.profiles)
    active = {r.id for r in cat.rules.values() if r.status == "active"}
    assert set(meta["checks"]) == active and "H6" not in meta["checks"]
    assert meta["views"] == {"duplicates": ["D8"], "cleanup": ["H4", "H5", "H10"]}
    assert meta["checks"]["S8"]["desc"] == "VARCHAR column used in an RLS rule"
    assert meta["checks"]["H8"]["remediation"].startswith("Run /ts-object-answer-promote")


def test_doc_lists_every_active_rule_under_each_category_and_retired_ones(cat, doc):
    for rule in cat.rules.values():
        rows = [ln for ln in doc.splitlines() if ln.startswith(f"| {rule.id} |")]
        if rule.status == "retired":
            assert len(rows) == 1 and "deferred" in rows[0].lower(), rule.id
        else:
            assert len([r for r in rows if r.startswith(f"| {rule.id} | **")]) == \
                len(rule.categories), rule.id


def test_pipes_in_rule_text_are_escaped():
    assert generate._cell("a | b\n c") == "a \\| b c"


def test_render_doc_needs_the_markers():
    with pytest.raises(ValueError, match="markers"):
        generate.render_doc("no markers here", load_catalog())


def _repo_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / generate.DOC_REL).parent.mkdir(parents=True)
    (root / generate.DOC_REL).write_text((REPO / generate.DOC_REL).read_text())
    import shutil
    shutil.copytree(REPO / generate.CATALOG_REL, root / generate.CATALOG_REL)
    return root


def test_check_fails_when_the_catalog_changes(tmp_path):
    root = _repo_copy(tmp_path)
    assert generate.check(root) == []
    rules = root / generate.CATALOG_REL / "rules" / "perf.yaml"
    rules.write_text(rules.read_text().replace(
        "title: Column sprawl (>75 columns)", "title: Column sprawl (wide models)"))
    assert generate.check(root) and "stale" in generate.check(root)[0]
    assert generate.write(root) is True and generate.check(root) == []


def test_cli_check_exit_codes(tmp_path):
    root = _repo_copy(tmp_path)
    cmd = [sys.executable, "-m", "ts_cli.audit.generate", "--root", str(root), "--check"]
    env = {**os.environ, "PYTHONPATH": str(REPO / "tools" / "ts-cli")}
    assert subprocess.run(cmd, capture_output=True, text=True, env=env).returncode == 0
    doc = root / generate.DOC_REL
    doc.write_text(doc.read_text().replace("| P8 | **", "| P8 | **Edited. "))
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 1 and "stale" in res.stdout


def test_check_reports_a_malformed_catalog_without_a_traceback(tmp_path):
    root = _repo_copy(tmp_path)
    (root / generate.CATALOG_REL / "rules" / "perf.yaml").write_text("- id: P1\n  title: [\n")
    problems = generate.check(root)
    assert problems and "perf.yaml" in problems[0]
    cmd = [sys.executable, "-m", "ts_cli.audit.generate", "--root", str(root), "--check"]
    env = {**os.environ, "PYTHONPATH": str(REPO / "tools" / "ts-cli")}
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 1 and "Traceback" not in res.stderr, res.stderr
    assert "FAIL" in res.stdout and "perf.yaml" in res.stdout
