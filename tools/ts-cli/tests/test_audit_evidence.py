"""The severity rubric (audit v2 roadmap PR 4.2): every rule declares its evidence class,
and a heuristic rule cannot grade above MEDIUM unless it carries an approved exception."""
from __future__ import annotations

import copy
import dataclasses

import pytest

from audit_catalog_helpers import PKG_CATALOG
from ts_cli.audit.catalog_model import Band, Bands, load_catalog
from ts_cli.audit.catalog_validate import evidence_problems

CAT = load_catalog(PKG_CATALOG)
PROFILES = list(CAT.profiles)


def _rule(rid="A6", **changes):
    return dataclasses.replace(copy.deepcopy(CAT.rules[rid]), **changes)


def _bands(*sevs):
    return Bands(direction="higher_is_better", unit="percent",
                 levels=[Band(op="lt", value=10.0 * (i + 1), severity=s)
                         for i, s in enumerate(sevs)])


def _medium_bands():
    return _bands("MEDIUM", "LOW")


@pytest.mark.parametrize("how", ["band", "severity map", "fixed", "profile override",
                                 "code rule"])
def test_heuristic_above_medium_fails(how):
    if how == "band":
        rule = _rule(evidence="heuristic", bands=_bands("HIGH", "MEDIUM"), profiles={})
    elif how == "severity map":
        rule = _rule("D10", evidence="heuristic", profiles={},
                     severity={"field": "@zero_column_role", "map": {"bridge": "INFO"},
                               "default": "HIGH"})
    elif how == "fixed":
        rule = _rule("A4", evidence="heuristic", severity="HIGH", profiles={})
    elif how == "profile override":
        rule = _rule(evidence="heuristic", bands=_medium_bands(), profiles={
            "spotter": {"bands": {"direction": "higher_is_better", "unit": "percent",
                                  "levels": [{"op": "lt", "value": 40, "severity": "HIGH"}]}}})
    else:  # D3 is a code rule registered to grade HIGH or INFO
        rule = _rule("D3", evidence="heuristic")
    problems = evidence_problems(rule, PROFILES)
    assert any("heuristic" in p and "HIGH" in p for p in problems), problems


def test_heuristic_at_medium_passes():
    rule = _rule(evidence="heuristic", bands=_medium_bands(), profiles={})
    assert evidence_problems(rule, PROFILES) == []


def test_exception_allows_and_needs_reason_and_date():
    high = dict(evidence="heuristic", bands=_bands("HIGH", "MEDIUM"), profiles={})
    ok = {"reason": "Severe enough that a name match alone warrants it.",
          "approved": "2026-11-02"}
    assert evidence_problems(_rule(severity_exception=ok, **high), PROFILES) == []
    for bad in ({"reason": "", "approved": "2026-11-02"}, {"reason": "x"},
                {"reason": "x", "approved": "02/11/2026"}, {"approved": "2026-11-02"},
                {"reason": "x", "approved": "2026-11-02", "by": "me"}, "yes"):
        assert evidence_problems(_rule(severity_exception=bad, **high), PROFILES), bad


def test_exception_on_non_heuristic_fails():
    rule = _rule(evidence="measure", severity_exception={"reason": "x",
                                                          "approved": "2026-11-02"})
    assert any("severity_exception" in p for p in evidence_problems(rule, PROFILES))


def test_missing_or_unknown_evidence_fails():
    assert any("evidence" in p for p in evidence_problems(_rule(evidence=""), PROFILES))
    assert any("evidence" in p
               for p in evidence_problems(_rule(evidence="hunch"), PROFILES))
    assert evidence_problems(_rule(evidence="", status="retired"), PROFILES) == []


HEURISTIC = {"S1", "S2", "S4", "S5", "H1", "H2", "H10", "D12"}
MEASURE = {"A1", "A2", "A6", "D1", "D9", "P2", "P4", "P7", "P8", "P11", "P13", "P16",
           "P17", "D7", "A7", "H11"}


def test_shipped_catalog_classes():
    active = {r.id: r for r in CAT.rules.values() if r.status == "active"}
    assert {i for i, r in active.items() if r.evidence == "heuristic"} == HEURISTIC
    assert {i for i, r in active.items() if r.evidence == "measure"} == MEASURE
    assert {i for i, r in active.items() if r.evidence == "fact"} == \
        set(active) - HEURISTIC - MEASURE
    assert [r.id for r in active.values() if r.severity_exception] == ["S5"]
    assert all(evidence_problems(r, PROFILES) == [] for r in active.values())


# ── findings carry their rule's evidence ────────────────────────────────────

def test_findings_carry_their_rules_evidence():
    import audit_rule_fixtures as fx
    from audit_run_rule import run_rule
    (s1, *_) = run_rule(fx.sec_pii_indexed_without_rls(), "S1")
    assert s1.evidence == "heuristic" and s1.to_dict()["evidence"] == "heuristic"
    (a4, *_) = run_rule(fx.ai_model_without_description(), "A4")
    assert a4.evidence == "fact" and a4.to_dict()["evidence"] == "fact"


def test_repin_does_not_copy_evidence():
    import audit_pinned
    pinned = audit_pinned._as_pinned({"check_id": "S1", "severity": "INFO", "evidence": "heuristic"})
    assert "evidence" not in pinned


def test_compacted_finding_marks_a_heuristic():
    from ts_cli.audit.report import _compact_finding
    base = {"check_id": "S1", "angle": "security", "severity": "INFO", "object_type": "column",
            "object_name": "x", "object_guid": "m-1", "detail": "d"}
    idx = {("x", "m-1"): 0}
    assert _compact_finding({**base, "evidence": "heuristic"}, idx, {}).get("h") == 1
    assert "h" not in _compact_finding({**base, "evidence": "fact"}, idx, {})
    assert "h" not in _compact_finding(base, idx, {})  # JSON from before 4.2


import report_browser  # noqa: E402

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None, reason="no headless Chrome")


def _audit():
    import audit_rule_fixtures as fx
    from ts_cli.audit import run_audit
    ctx = fx.sec_pii_indexed_without_rls()
    return run_audit(None, [m["guid"] for m in ctx.models], ["S", "A"], ctx=ctx)


@needs_chrome
def test_heuristic_findings_show_name_match(tmp_path):
    from ts_cli.audit.report import render_report
    data = _audit()
    heuristic = sum(1 for f in data["findings"] if f["evidence"] == "heuristic")
    assert heuristic and any(f["evidence"] != "heuristic" for f in data["findings"])
    page = render_report(data)
    guid = data["findings"][0]["object_guid"]
    for route in ("crossmodel", f"model/{guid}"):
        shown = report_browser.render(page, tmp_path, route, actions=(
            'window.__extra = document.querySelectorAll(".view.active .evidence-tag").length;'))
        assert shown["errors"] == [] and shown["extra"] == heuristic, (route, shown["extra"])
        # the scorecard opens with its angle sections collapsed, so its text, not its
        # visible text; the cross-model table shows every finding
        text = shown["visible"] if route == "crossmodel" else shown["active_text"]
        assert "name match" in text


@needs_chrome
def test_old_json_without_evidence_renders(tmp_path):
    from ts_cli.audit.report import render_report
    data = _audit()
    for f in data["findings"]:
        f.pop("evidence")
    shown = report_browser.render(render_report(data), tmp_path, "crossmodel")
    assert shown["errors"] == [] and "name match" not in shown["visible"]


@needs_chrome
def test_the_name_match_tooltip_states_no_cap_and_details_are_escaped(tmp_path):
    from ts_cli.audit.report import render_report
    data = _audit()
    for f in data["findings"]:
        if f["evidence"] == "heuristic":
            f["severity"], f["detail"] = "CRITICAL", '<img src=x onerror="window.__pwned=1">'
    page = render_report(data)
    guid = data["findings"][0]["object_guid"]
    for route in ("crossmodel", f"model/{guid}"):
        shown = report_browser.render(page, tmp_path, route, actions=(
            'var t = document.querySelector(".view.active .evidence-tag");'
            'window.__extra = {title: t && t.title, img: document.querySelectorAll('
            '".view.active img").length, pwned: !!window.__pwned};'))
        assert shown["errors"] == [] and shown["extra"]["img"] == 0, route
        assert shown["extra"]["pwned"] is False
        assert "capped" not in (shown["extra"]["title"] or "")
        assert '<img src=x onerror="window.__pwned=1">' in shown["active_text"]
