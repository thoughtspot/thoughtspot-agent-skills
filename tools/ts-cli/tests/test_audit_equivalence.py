"""compare_findings: the strict comparator the equivalence gate was built on, and that
test_audit_pinned_findings.py now holds the catalog to the pinned legacy answers with.
Its one job is never to call two different finding lists identical."""
from __future__ import annotations

import copy

import pytest

from ts_cli.audit.equivalence import compare_findings


def _f(check_id="A1", guid="g1", name="Sales", detail="3/10 columns", **kw) -> dict:
    out = {
        "check_id": check_id, "angle": "ai", "severity": "HIGH",
        "object_type": "model", "object_name": name, "object_guid": guid,
        "detail": detail, "metric": 30.0, "threshold": {"pass": 50},
    }
    out.update(kw)
    return out


# ── compare_findings ────────────────────────────────────────────────────────

def test_identical_lists():
    old = [_f(), _f("D2", detail="x")]
    res = compare_findings(old, copy.deepcopy(old))
    assert res == {"identical": True, "only_old": [], "only_new": [], "changed": []}


def test_empty_lists_are_identical():
    assert compare_findings([], [])["identical"] is True


def test_reports_only_old_only_new_and_changed():
    old = [_f(), _f("A2", detail="gone")]
    new = [_f(severity="MEDIUM", metric=31.0), _f("A3", detail="added")]
    res = compare_findings(old, new)
    assert res["identical"] is False
    assert res["only_old"] == [_f("A2", detail="gone")]
    assert res["only_new"] == [_f("A3", detail="added")]
    key = ("A1", "model", "g1", "Sales", "3/10 columns")
    assert sorted(res["changed"], key=lambda c: c["field"]) == [
        {"key": key, "field": "metric", "old": 30.0, "new": 31.0},
        {"key": key, "field": "severity", "old": "HIGH", "new": "MEDIUM"},
    ]


def test_order_independent():
    old = [_f("A1"), _f("A2"), _f("D1", detail="d")]
    assert compare_findings(old, list(reversed(old)))["identical"] is True


def test_duplicate_findings_are_counted():
    res = compare_findings([_f(), _f()], [_f()])
    assert res["identical"] is False
    assert res["only_old"] == [_f()] and res["only_new"] == [] and res["changed"] == []
    res = compare_findings([_f()], [_f(), _f()])
    assert res["identical"] is False and res["only_new"] == [_f()]


def test_duplicate_keys_with_one_changed_member():
    old = [_f(metric=1.0), _f(metric=2.0)]
    new = [_f(metric=2.0), _f(metric=3.0)]
    res = compare_findings(old, new)
    assert res["identical"] is False
    assert res["changed"] == [{"key": ("A1", "model", "g1", "Sales", "3/10 columns"),
                               "field": "metric", "old": 1.0, "new": 3.0}]


@pytest.mark.parametrize("old_val,new_val", [
    (30, 30.0), (1, True), (0, None), ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
    ({"pass": 50}, {"pass": 50.0}), ([1, 2], [2, 1]),
    ({1: "x"}, {1.0: "x"}), ({1: "x"}, {True: "x"}), ({1.0: "x"}, {True: "x"}),
    (0.0, -0.0), ({"pass": 0.0}, {"pass": -0.0}),
])
def test_values_compared_exactly(old_val, new_val):
    """1 == 1.0 == True in Python but they serialise differently, so they differ."""
    res = compare_findings([_f(metric=old_val)], [_f(metric=new_val)])
    assert res["identical"] is False
    assert res["changed"][0]["field"] == "metric"


def test_compared_field_missing_on_one_side_is_a_difference():
    new = _f()
    del new["threshold"]
    no_threshold = _f(threshold=None)
    assert compare_findings([no_threshold], [new])["identical"] is False


def test_key_field_missing_is_not_none():
    new = _f(object_guid=None)
    old = _f()
    del old["object_guid"]
    res = compare_findings([old], [new])
    assert res["identical"] is False
    assert len(res["only_old"]) == 1 and len(res["only_new"]) == 1


def test_angle_only_difference_is_reported():
    """Legacy angles are long keys ("data_modeling"); an engine emitting the
    category letter instead must not pass."""
    res = compare_findings([_f(angle="data_modeling")], [_f(angle="D")])
    assert res["identical"] is False
    assert [(c["field"], c["old"], c["new"]) for c in res["changed"]] == [
        ("angle", "data_modeling", "D")]


def test_equal_counts_one_duplicated_one_missing():
    a, b = _f(detail="a"), _f(detail="b")
    res = compare_findings([a, b], [a, a])
    assert res["identical"] is False
    assert res["only_old"] == [b] and res["only_new"] == [a]


def test_extra_fields_on_new_side_are_ignored():
    """New fields (e.g. ``categories``) are additive and not compared."""
    assert compare_findings([_f()], [_f(categories=["A"])])["identical"] is True


def test_key_includes_detail_and_name():
    res = compare_findings([_f(detail="a")], [_f(detail="b")])
    assert res["only_old"] and res["only_new"] and not res["changed"]
    res = compare_findings([_f(name="x")], [_f(name="y")])
    assert res["only_old"] and res["only_new"]


def test_nan_metrics_on_both_sides_are_identical():
    nan = float("nan")
    assert compare_findings([_f(metric=nan)], [_f(metric=nan)])["identical"] is True
