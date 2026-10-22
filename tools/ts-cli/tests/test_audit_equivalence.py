"""Equivalence comparator: the gate that proves the rule engine reproduces the
legacy checks. Its one job is never to call two different finding lists identical."""
from __future__ import annotations

import copy

import pytest

from ts_cli.audit import ANGLE_MODULES
from ts_cli.audit.context import AuditContext
from ts_cli.audit.equivalence import (
    compare_findings, legacy_rule_ids, main, per_rule_rows, run_both)
from ts_cli.audit.findings import Finding


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


# ── per-rule table ──────────────────────────────────────────────────────────

def test_per_rule_rows_counts_and_diffs():
    old = [_f("A1"), _f("A1", detail="2"), _f("D1", detail="d")]
    new = [_f("A1"), _f("A1", detail="2", severity="LOW"), _f("P1", detail="p")]
    rows = per_rule_rows(old, new, compare_findings(old, new))
    assert rows == [("A1", 2, 2, 1), ("D1", 1, 0, 1), ("P1", 0, 1, 1)]


def test_per_rule_rows_lists_requested_rules_with_no_findings():
    old = [_f("A1")]
    rows = per_rule_rows(old, old, compare_findings(old, old), requested=["A1", "D1"])
    assert rows == [("A1", 1, 1, 0), ("D1", 0, 0, 0)]


def test_per_rule_rows_sort_numerically_within_category():
    old = [_f("A10", detail="a"), _f("A2", detail="b")]
    rows = per_rule_rows(old, old, compare_findings(old, old))
    assert [r[0] for r in rows] == ["A2", "A10"]


# ── run_both ────────────────────────────────────────────────────────────────

def _ctx(assessment="general") -> AuditContext:
    return AuditContext(
        models=[{"guid": "m1", "model": {"name": "Sales", "columns": [
            {"name": "Revenue", "description": ""}]}}],
        model_guids=["m1"], assessment=assessment)


def _legacy_runner(calls=None):
    def run(ctx, profile, categories):
        if calls is not None:
            calls.append((ctx.assessment, profile, list(categories)))
        legacy = copy.copy(ctx)
        legacy.assessment = profile
        out = []
        for cat in categories:
            for fn in ANGLE_MODULES[cat].ALL_CHECKS:
                out.extend(fn(legacy))
        return out
    return run


def test_run_both_identical_with_legacy_as_new_side():
    calls = []
    res = run_both(_ctx(), "general", None, new_runner=_legacy_runner(calls))
    assert res["identical"] is True
    assert calls == [("general", "general", list(ANGLE_MODULES))]


def test_run_both_sets_profile_for_legacy_and_does_not_mutate_ctx():
    ctx = _ctx("general")
    seen = []

    def new(c, profile, categories):
        seen.append(profile)
        return []

    res = run_both(ctx, "spotter", ["A4"], new_runner=new)
    assert ctx.assessment == "general"
    assert seen == ["spotter"]
    assert [f["severity"] for f in res["only_old"]] == ["HIGH"]  # spotter bar


def test_run_both_filters_both_sides_to_check_ids():
    def new(ctx, profile, categories):
        return [Finding("A4", "ai", "MEDIUM", "model", "Sales", "m1", "Model has no description"),
                Finding("Z9", "ai", "LOW", "model", "Sales", "m1", "noise")]

    res = run_both(_ctx(), "general", ["A4"], new_runner=new)
    assert res["identical"] is True


def test_run_both_detects_a_difference_from_the_new_side():
    def new(ctx, profile, categories):
        return [Finding("A4", "ai", "LOW", "model", "Sales", "m1", "Model has no description")]

    res = run_both(_ctx(), "general", ["A4"], new_runner=new)
    assert res["identical"] is False
    assert res["changed"][0]["field"] == "severity"


def test_run_both_accepts_dict_findings_from_new_side():
    def new(ctx, profile, categories):
        return [Finding("A4", "ai", "MEDIUM", "model", "Sales", "m1",
                        "Model has no description").to_dict()]

    assert run_both(_ctx(), "general", ["A4"], new_runner=new)["identical"] is True


def test_run_both_limits_categories():
    calls = []
    res = run_both(_ctx(), "general", None, new_runner=_legacy_runner(calls),
                   categories=["A"])
    assert res["identical"] is True
    assert calls[0][2] == ["A"]


def test_new_side_receives_a_copy_not_the_callers_ctx():
    ctx = _ctx()
    before = copy.deepcopy(ctx)
    seen = []

    def new(c, profile, categories):
        seen.append(c)
        c.models.clear()
        c.assessment = "spotter"
        return []

    run_both(ctx, "general", None, new_runner=new)
    assert seen[0] is not ctx and seen[0].models is not ctx.models
    assert ctx == before


@pytest.mark.parametrize("ids", [[], ["A99"], ["a4"], ["S1"]])
def test_run_both_rejects_rule_ids_it_cannot_compare(ids):
    """Empty, unknown, wrong case, or outside the selected categories: each would
    otherwise compare nothing and report identical."""
    with pytest.raises(ValueError):
        run_both(_ctx(), "general", ids, new_runner=_legacy_runner(), categories=["A", "D"])


def test_legacy_rule_ids_follow_check_function_names():
    assert legacy_rule_ids(["A"]) == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert "D1" in legacy_rule_ids(None)


def test_run_both_rejects_unknown_profile():
    with pytest.raises(ValueError):
        run_both(_ctx(), "nonsense", None, new_runner=_legacy_runner())


# ── CLI ─────────────────────────────────────────────────────────────────────

def _snapshot(tmp_path):
    from ts_cli.audit.snapshot import write_snapshot
    write_snapshot(_ctx(), tmp_path, ["A", "D"])
    return tmp_path


def test_cli_exit_0_when_identical(tmp_path, capsys):
    code = main(["--snapshot", str(_snapshot(tmp_path)), "--profile", "general"],
                new_runner=_legacy_runner())
    out = capsys.readouterr().out
    assert code == 0
    assert "rule" in out and "IDENTICAL:" in out and "NOT identical" not in out


def test_cli_exit_1_when_different(tmp_path, capsys):
    code = main(["--snapshot", str(_snapshot(tmp_path)), "--profile", "general"],
                new_runner=lambda ctx, profile, categories: [])
    out = capsys.readouterr().out
    assert code == 1
    assert "A4" in out and "NOT identical" in out


def test_cli_uses_captured_categories_and_rule_filter(tmp_path):
    calls = []
    code = main(["--snapshot", str(_snapshot(tmp_path)), "--profile", "spotter",
                 "--rules", "A4"], new_runner=_legacy_runner(calls))
    assert code == 0
    assert calls == [("general", "spotter", ["A", "D"])]


def test_cli_checks_is_an_alias_of_rules(tmp_path):
    calls = []
    code = main(["--snapshot", str(_snapshot(tmp_path)), "--checks", "A4"],
                new_runner=_legacy_runner(calls))
    assert code == 0 and len(calls) == 1


@pytest.mark.parametrize("rules", ["A99", "a4", ",", "", "S1"])
def test_cli_rule_selection_that_compares_nothing_exits_2(tmp_path, capsys, rules):
    """S1 is a real rule, but the snapshot captured only A and D."""
    code = main(["--snapshot", str(_snapshot(tmp_path)), "--rules", rules],
                new_runner=_legacy_runner())
    captured = capsys.readouterr()
    assert code == 2
    assert "IDENTICAL" not in captured.out
    assert "cannot compare" in captured.err


def test_cli_marks_requested_rule_without_findings_not_exercised(tmp_path, capsys):
    code = main(["--snapshot", str(_snapshot(tmp_path)), "--rules", "A4,D1"],
                new_runner=_legacy_runner())
    out = capsys.readouterr().out
    assert code == 0
    assert any(line.split()[:7] == ["D1", "|", "0", "|", "0", "|", "0"]
               for line in out.splitlines())
    assert "not exercised: D1" in out


def test_cli_bad_snapshot_exits_2(tmp_path, capsys):
    code = main(["--snapshot", str(tmp_path), "--profile", "general"],
                new_runner=_legacy_runner())
    assert code == 2
    assert "manifest" in capsys.readouterr().err
