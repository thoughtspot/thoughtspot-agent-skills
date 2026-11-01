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
           "P17", "D7"}


def test_shipped_catalog_classes():
    active = {r.id: r for r in CAT.rules.values() if r.status == "active"}
    assert {i for i, r in active.items() if r.evidence == "heuristic"} == HEURISTIC
    assert {i for i, r in active.items() if r.evidence == "measure"} == MEASURE
    assert {i for i, r in active.items() if r.evidence == "fact"} == \
        set(active) - HEURISTIC - MEASURE
    assert [r.id for r in active.values() if r.severity_exception] == ["S5"]
    assert all(evidence_problems(r, PROFILES) == [] for r in active.values())
