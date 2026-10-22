"""Equivalence comparator: the gate that proves the rule engine reproduces the
legacy checks. Its one job is never to call two different finding lists identical."""
from __future__ import annotations

import copy

import pytest

from ts_cli.audit import ANGLE_MODULES
from ts_cli.audit.context import AuditContext
from ts_cli.audit.equivalence import (
    collect_both, compare_findings, legacy_rule_ids, main, per_rule_rows, run_both)
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


# ── catalog rules vs legacy checks, over the legacy checks' own test inputs ─

A_RULES = ["A1", "A2", "A3", "A4", "A5", "A6"]


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_a_rules_equivalent_on_the_check_tests_inputs(profile):
    """The A catalog rules (rules/ai.yaml, the default engine runner) reproduce
    checks_ai.py exactly over every input its tests use (audit_rule_fixtures.AI_INPUTS:
    test_checks_ai*.py's contexts, the profile-bar families swept end to end, the A6
    example fixtures and the demo corpus models)."""
    import audit_rule_fixtures as fx

    differing, fired = {}, dict.fromkeys(A_RULES, 0)
    for name, build in fx.AI_INPUTS.items():
        old, new = collect_both(build(), profile, A_RULES, categories=["A"])
        res = compare_findings(old, new)
        if not res["identical"]:
            differing[name] = res
        for f in old:
            fired[f["check_id"]] += 1
    assert differing == {}
    # Not vacuous: every rule fires somewhere in these inputs.
    assert all(fired.values()), fired


@pytest.mark.parametrize("profile", ["spotter", "general"])
@pytest.mark.parametrize("fixture,probe", [
    # a nameless measure: legacy A6 lists it as "?"
    ("tml_unnamed_measure", lambda f: f["check_id"] == "A6" and f["detail"].endswith(": ?")),
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("ai_model_name_none", lambda f: f["object_name"] is None),
    ("ai_document_guid_none", lambda f: f["object_guid"] is None),
])
def test_a_rules_keep_legacy_names_and_guids(profile, fixture, probe):
    import audit_rule_fixtures as fx

    old, new = collect_both(getattr(fx, fixture)(), profile, A_RULES, categories=["A"])
    assert any(probe(f) for f in old), "the input must exercise the case"
    assert compare_findings(old, new)["identical"] is True


P_RULES = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P11", "P13", "P14",
           "P15", "P16", "P17", "P18"]


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_p_rules_equivalent_on_the_check_tests_inputs(profile):
    """The P catalog rules (rules/perf.yaml, the default engine runner) reproduce
    checks_perf.py exactly over every input its tests use (audit_rule_fixtures.P_INPUTS:
    test_checks_perf*.py's contexts and the P halves of the shared-check tests, the
    threshold families swept across their boundaries, raw None/absent names and guids,
    duplicate formula names, and the demo corpus models)."""
    import audit_rule_fixtures as fx

    differing, fired = {}, dict.fromkeys(P_RULES, 0)
    for name, build in fx.P_INPUTS.items():
        old, new = collect_both(build(), profile, P_RULES, categories=["P"])
        res = compare_findings(old, new)
        if not res["identical"]:
            differing[name] = res
        for f in old:
            fired[f["check_id"]] += 1
    assert differing == {}
    # Not vacuous: every rule fires somewhere in these inputs.
    assert all(fired.values()), fired


@pytest.mark.parametrize("profile", ["spotter", "general"])
@pytest.mark.parametrize("fixture,probe", [
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("perf_names_none", lambda f: f["object_name"] is None and f["object_guid"] is None),
    ("perf_names_none", lambda f: f["check_id"] == "P1" and f["object_guid"] is None),
    # absent keys reach it as ""
    ("perf_names_absent", lambda f: f["object_name"] == "" and f["object_guid"] == ""),
    # legacy P17 keys its graph by name: one finding per name, later definition wins
    ("perf_duplicate_formula_names",
     lambda f: f["check_id"] == "P17" and f["object_name"] == "Z" and f["metric"] == 4),
    ("perf_unnamed_formulas_with_references",
     lambda f: f["check_id"] == "P17" and f["object_name"] == ""),
])
def test_p_rules_keep_legacy_names_and_guids(profile, fixture, probe):
    import audit_rule_fixtures as fx

    old, new = collect_both(getattr(fx, fixture)(), profile, P_RULES, categories=["P"])
    assert any(probe(f) for f in old), "the input must exercise the case"
    assert compare_findings(old, new)["identical"] is True


S_RULES = ["S1", "S2", "S3", "S4", "S5", "S8", "S9", "S10"]


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_s_rules_equivalent_on_the_check_tests_inputs(profile):
    """The S catalog rules (rules/security.yaml, the default engine runner) reproduce
    checks_security.py exactly over every input its tests use (audit_rule_fixtures.
    S_INPUTS: test_checks_security*.py's contexts and the S halves of the alias,
    index-type and registry tests, the name heuristics swept across their patterns,
    the owning-table and masking edges, raw None/absent names and guids, None where
    lists are expected, and the demo corpus models)."""
    import audit_rule_fixtures as fx

    differing, fired = {}, dict.fromkeys(S_RULES, 0)
    for name, build in fx.S_INPUTS.items():
        old, new = collect_both(build(), profile, S_RULES, categories=["S"])
        res = compare_findings(old, new)
        if not res["identical"]:
            differing[name] = res
        for f in old:
            fired[f["check_id"]] += 1
    assert differing == {}
    # Not vacuous: every rule fires somewhere in these inputs.
    assert all(fired.values()), fired


def _legacy_s_raises(ctx) -> bool:
    from ts_cli.audit import checks_security
    try:
        for check in checks_security.ALL_CHECKS:
            check(copy.deepcopy(ctx))
    except Exception:  # noqa: BLE001 - any legacy failure makes the input incomparable
        return True
    return False


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_s_rules_equivalent_wherever_legacy_s_runs(profile):
    """Every other committed audit input (AI_INPUTS, P_INPUTS) on which the legacy S
    checks run cleanly: the engine must neither raise nor differ there. Inputs the
    legacy checks raise on cannot be compared and are counted, not judged."""
    import audit_rule_fixtures as fx

    differing, compared, legacy_raised = {}, 0, []
    for name, build in {**fx.AI_INPUTS, **fx.P_INPUTS}.items():
        ctx = build()
        if _legacy_s_raises(ctx):
            legacy_raised.append(name)
            continue
        compared += 1
        res = run_both(ctx, profile, S_RULES, categories=["S"])
        if not res["identical"]:
            differing[name] = res
    assert differing == {}
    assert compared > 300, (compared, legacy_raised)
    # Only the inputs built to carry `name: None` columns make the legacy regexes raise.
    assert legacy_raised == ["perf_names_none"]


def test_every_s_input_runs_cleanly_on_the_legacy_checks():
    """An S_INPUTS entry the legacy checks raise on would compare nothing."""
    import audit_rule_fixtures as fx

    assert [n for n, build in fx.S_INPUTS.items() if _legacy_s_raises(build())] == []


@pytest.mark.parametrize("profile", ["spotter", "general"])
@pytest.mark.parametrize("fixture,probe", [
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("sec_names_none", lambda f: f["check_id"] == "S4" and f["object_name"] is None
     and f["object_guid"] is None),
    ("sec_names_none", lambda f: f["check_id"] == "S9" and f["object_name"] is None
     and f["object_guid"] is None),
    ("sec_names_none", lambda f: f["check_id"] == "S8" and f["object_guid"] is None),
    # absent keys reach it as ""
    ("sec_names_absent", lambda f: f["check_id"] == "S10" and f["object_name"] == ""
     and f["object_guid"] == ""),
    ("sec_names_absent", lambda f: f["check_id"] == "S9" and f["object_name"] == ""),
    # S2: the owning table's RLS through "" keys, overriding aliases and absent tables
    ("sec_owning_table_edges", lambda f: f["check_id"] == "S2"
     and f["object_name"] == "email_no_id" and f["severity"] == "INFO"),
    ("sec_owning_table_edges", lambda f: f["check_id"] == "S2"
     and f["object_name"] == "email_x" and f["severity"] == "HIGH"),
    ("sec_owning_table_edges", lambda f: f["check_id"] == "S2"
     and f["object_name"] == "email_y" and f["severity"] == "INFO"),
    # S3: the masking blob is case-insensitive on both sides
    ("sec_masking_edges", lambda f: f["check_id"] == "S3" and f["object_name"] == "home_phone"),
    # S5: `token` is HIGH, the other words CRITICAL, matched in any case
    ("credential_names", lambda f: f["check_id"] == "S5" and f["object_name"] == "TOKEN"
     and f["severity"] == "HIGH"),
    # S9: the detail quotes the first 80 characters
    ("sec_long_rls_expression", lambda f: f["check_id"] == "S9"
     and len(f["detail"]) == len("Function in RLS expression prevents filter pushdown: ") + 80),
])
def test_s_rules_keep_legacy_names_guids_and_edges(profile, fixture, probe):
    import audit_rule_fixtures as fx

    build = getattr(fx, fixture, None) or fx.S_INPUTS[fixture]
    old, new = collect_both(build(), profile, S_RULES, categories=["S"])
    assert any(probe(f) for f in old), "the input must exercise the case"
    assert compare_findings(old, new)["identical"] is True


D_RULES = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12"]


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_d_rules_equivalent_on_the_check_tests_inputs(profile):
    """The D catalog rules (rules/data.yaml, the default engine runner) reproduce
    checks_data.py exactly over every input its tests use (audit_rule_fixtures.
    D_INPUTS: test_checks_data*.py's contexts and the D halves of the alias, join-key,
    referencing-join and registry tests, the D1 lines and D3/D11 vocabularies swept
    across their boundaries, the grain and pass-through shares, raw None/absent names
    and guids, None where lists are expected, multi-Model overlap and divergence edges,
    and the demo corpus models)."""
    import audit_rule_fixtures as fx

    differing, fired = {}, dict.fromkeys(D_RULES, 0)
    for name, build in fx.D_INPUTS.items():
        old, new = collect_both(build(), profile, D_RULES, categories=["D"])
        res = compare_findings(old, new)
        if not res["identical"]:
            differing[name] = res
        for f in old:
            fired[f["check_id"]] += 1
    assert differing == {}
    # Not vacuous: every rule fires somewhere in these inputs.
    assert all(fired.values()), fired


def _legacy_d_raises(ctx) -> bool:
    from ts_cli.audit import checks_data
    try:
        for check in checks_data.ALL_CHECKS:
            check(copy.deepcopy(ctx))
    except Exception:  # noqa: BLE001 - any legacy failure makes the input incomparable
        return True
    return False


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_d_rules_equivalent_wherever_legacy_d_runs(profile):
    """Every other committed audit input (AI_INPUTS, P_INPUTS, S_INPUTS) on which the
    legacy D checks run cleanly: the engine must neither raise nor differ there."""
    import audit_rule_fixtures as fx

    differing, compared, legacy_raised = {}, 0, []
    for name, build in {**fx.AI_INPUTS, **fx.P_INPUTS, **fx.S_INPUTS}.items():
        ctx = build()
        if _legacy_d_raises(ctx):
            legacy_raised.append(name)
            continue
        compared += 1
        res = run_both(ctx, profile, D_RULES, categories=["D"])
        if not res["identical"]:
            differing[name] = res
    assert differing == {}
    assert compared > 450, (compared, legacy_raised)
    assert legacy_raised == []


def test_every_d_input_runs_cleanly_on_the_legacy_checks():
    """A D_INPUTS entry the legacy checks raise on would compare nothing."""
    import audit_rule_fixtures as fx

    assert [n for n, build in fx.D_INPUTS.items() if _legacy_d_raises(build())] == []


@pytest.mark.parametrize("profile", ["spotter", "general"])
@pytest.mark.parametrize("fixture,probe", [
    # `name: None` / `guid: None` reach the finding as None, not ""
    ("data_names_none", lambda f: f["check_id"] == "D1" and f["object_name"] is None
     and f["object_guid"] is None),
    ("data_names_none", lambda f: f["check_id"] == "D10" and f["object_name"] is None
     and f["detail"] == "Zero-column bridge table 'None'"),
    ("data_names_none", lambda f: f["check_id"] == "D7" and f["object_name"] == "None / Twin"
     and f["object_guid"] is None),
    ("data_names_none", lambda f: f["check_id"] == "D8" and f["object_name"] == "...None"
     and f["object_guid"] is None),
    ("data_names_none", lambda f: f["check_id"] == "D12" and f["object_name"] is None
     and f["object_guid"] == ""),
    # absent keys reach it as ""
    ("data_names_absent", lambda f: f["check_id"] == "D9" and f["object_name"] == ""
     and f["object_guid"] == ""),
    ("data_names_absent", lambda f: f["check_id"] == "D8" and f["object_name"] == "..."),
    # D1: one finding per measure, each with its own legacy threshold
    ("data_names_absent", lambda f: f["check_id"] == "D1"
     and f["threshold"] == {"green": 10, "yellow": 15} and f["metric"] == 16),
    # D7: the MEDIUM finding carries a threshold, the HIGH one none
    ("models_overlapping_tables", lambda f: f["check_id"] == "D7" and f["severity"] == "MEDIUM"
     and f["threshold"] == {"high_overlap": 0.5}),
    ("data_models_identical_tables", lambda f: f["check_id"] == "D7" and f["threshold"] is None),
    # D7: an explicit `fqn: None` is an element; an absent fqn falls back to the name
    ("data_models_overlap_edges", lambda f: f["check_id"] == "D7"
     and f["object_name"] == "NoneFqn / NoneToo"),
    ("data_models_overlap_edges", lambda f: f["check_id"] == "D7"
     and f["object_name"] == "ByName / ByFqn"),
    # D8: an absent stripe groups with an explicit "", never with None
    ("data_metadata_edges", lambda f: f["check_id"] == "D8" and f["object_name"] == "...LINES"),
    # D10 / D11 look a table up by name, not alias (BL-305, kept)
    ("data_model_aliased_fact", lambda f: f["check_id"] == "D10" and f["object_name"] == "ORDERS"),
    ("data_model_aliased_fact", lambda f: f["check_id"] == "D11" and f["severity"] == "INFO"
     and f["detail"] == "ONE_TO_MANY join 'SHIPMENTS' -> 'O'"),
    # D11 words a MANY_TO_MANY INFO finding "ONE_TO_MANY" (kept)
    ("data_fanout_many_to_many_dimension", lambda f: f["check_id"] == "D11"
     and f["detail"].startswith("ONE_TO_MANY join")),
    # D12: a later column overwrites an earlier one's type within a Model
    ("data_models_column_type_edges", lambda f: f["check_id"] == "D12"
     and f["detail"].endswith("A=MEASURE, B=ATTRIBUTE")),
    # D7 / D8 compare as Python does: 1 and True are one table, 0 and False one schema
    ("overlap_scalars_1_True", lambda f: f["check_id"] == "D7" and f["severity"] == "HIGH"),
    ("duplicate_schemaStripe_0_False", lambda f: f["check_id"] == "D8" and f["metric"] == 2),
])
def test_d_rules_keep_legacy_names_guids_and_edges(profile, fixture, probe):
    import audit_rule_fixtures as fx

    build = getattr(fx, fixture, None) or fx.D_INPUTS[fixture]
    old, new = collect_both(build(), profile, D_RULES, categories=["D"])
    assert any(probe(f) for f in old), "the input must exercise the case"
    assert compare_findings(old, new)["identical"] is True


H_RULES = ["H1", "H2", "H3", "H4", "H5", "H7", "H8", "H9", "H10"]


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_h_rules_equivalent_on_the_check_tests_inputs(profile):
    """The H catalog rules (rules/human.yaml, the default engine runner) reproduce
    checks_human.py exactly over every input its tests use (audit_rule_fixtures.
    H_INPUTS: test_checks_human*.py's contexts, the H halves of the dead-guard,
    unreachable-check, context and snapshot tests — contexts `build_context`
    assembles with Set lookups failing, empty, partial and clean among them — the H1
    name shapes and H2 lengths swept across their lines, join/formula/dependents/
    answer edges, raw None/absent names, None where lists are expected, the registry
    contexts and the demo corpus)."""
    import audit_rule_fixtures as fx

    differing, fired = {}, dict.fromkeys(H_RULES, 0)
    for name, build in fx.H_INPUTS.items():
        old, new = collect_both(build(), profile, H_RULES, categories=["H"])
        res = compare_findings(old, new)
        if not res["identical"]:
            differing[name] = res
        for f in old:
            fired[f["check_id"]] += 1
    assert differing == {}
    # Not vacuous: every rule fires somewhere in these inputs.
    assert all(fired.values()), fired


def _legacy_h_raises(ctx) -> bool:
    from ts_cli.audit import checks_human
    try:
        for check in checks_human.ALL_CHECKS:
            check(copy.deepcopy(ctx))
    except Exception:  # noqa: BLE001 - any legacy failure makes the input incomparable
        return True
    return False


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_h_rules_equivalent_wherever_legacy_h_runs(profile):
    """Every other committed audit input (AI_INPUTS, P_INPUTS, S_INPUTS, D_INPUTS) on
    which the legacy H checks run cleanly: the engine must neither raise nor differ."""
    import audit_rule_fixtures as fx

    differing, compared, legacy_raised = {}, 0, []
    for name, build in {**fx.AI_INPUTS, **fx.P_INPUTS, **fx.S_INPUTS,
                        **fx.D_INPUTS}.items():
        ctx = build()
        if _legacy_h_raises(ctx):
            legacy_raised.append(name)
            continue
        compared += 1
        res = run_both(ctx, profile, H_RULES, categories=["H"])
        if not res["identical"]:
            differing[name] = res
    assert differing == {}
    assert compared > 550, (compared, legacy_raised)
    # A None column or Model name (H1/H10 regexes) and a list-valued column
    # `properties` (H3) abort legacy H; the rule-by-rule test below covers them.
    assert sorted(legacy_raised) == sorted(H_LEGACY_RAISES), legacy_raised


#: Inputs on which some legacy H check raises, and which ones.
H_LEGACY_RAISES = {
    "ai_model_name_none": {"H10"}, "tml_value_shapes": {"H3"},
    "perf_names_none": {"H1", "H10"}, "sec_names_none": {"H10"},
    "data_names_none": {"H1", "H10"}, "data_single_model_malformed_column": {"H3"},
}


@pytest.mark.parametrize("profile", ["spotter", "general"])
@pytest.mark.parametrize("name", sorted(H_LEGACY_RAISES))
def test_h_rules_equivalent_rule_by_rule_where_a_legacy_h_check_raises(profile, name):
    """Where one legacy H check raises (aborting the category), every OTHER H rule
    still matches its own legacy check exactly, and the engine raises on none."""
    import audit_rule_fixtures as fx
    from ts_cli.audit import checks_human
    from ts_cli.audit.catalog_model import load_catalog
    from ts_cli.audit.engine.run import run_rule

    ctx = {**fx.AI_INPUTS, **fx.P_INPUTS, **fx.S_INPUTS, **fx.D_INPUTS}[name]()
    raised, catalog = set(), load_catalog()
    for check in checks_human.ALL_CHECKS:
        rule_id = check.__name__.replace("check_", "").upper()
        try:
            old = [f.to_dict() for f in check(copy.deepcopy(ctx))]
        except Exception:  # noqa: BLE001 - the legacy check aborts on this input
            raised.add(rule_id)
            run_rule(copy.deepcopy(ctx), catalog, rule_id, profile)  # must not raise
            continue
        new = [f.to_dict() for f in run_rule(copy.deepcopy(ctx), catalog, rule_id, profile)]
        assert compare_findings(old, new)["identical"] is True, (rule_id, old, new)
    assert raised == H_LEGACY_RAISES[name]


def test_every_h_input_runs_cleanly_on_the_legacy_checks():
    """An H_INPUTS entry the legacy checks raise on would compare nothing."""
    import audit_rule_fixtures as fx

    assert [n for n, build in fx.H_INPUTS.items() if _legacy_h_raises(build())] == []


@pytest.mark.parametrize("profile", ["spotter", "general"])
@pytest.mark.parametrize("fixture,probe", [
    # H1: one finding per Model, the first five names, the legacy threshold dict
    ("human_h1_all_anti_patterns", lambda f: f["check_id"] == "H1"
     and f["detail"] == "7/7 columns have anti-pattern names (100%): col1, col2, val, "
     "tmp_a, 9b" and f["threshold"] == {"max_pct": 10} and f["metric"] == 100.0),
    # H2: one finding per Model, three issues listed, "; "-joined
    ("human_h2_many_issues", lambda f: f["check_id"] == "H2" and f["metric"] == 4
     and f["detail"] == "4 description quality issues: 'C0' too short (5 chars); "
     "'C1' too short (4 chars); '' uses boilerplate pattern"),
    # H3 looks a table up by NAME: a hidden column of an aliased table is reported
    ("human_h3_join_edges", lambda f: f["check_id"] == "H3" and f["object_name"] == "K1"),
    # H4: a Model whose only dependents are Sets is an orphan
    ("human_h4_dependent_shapes", lambda f: f["check_id"] == "H4"
     and f["object_guid"] == "m-sets"),
    # H5: a Set consumed by a Set is not an orphan; that consumer, looked up, is
    ("human_h5_set_shapes", lambda f: f["check_id"] == "H5" and f["object_guid"] == "s2"),
    # H5: a failed consumer lookup is silent; a clean empty one reports
    ("built_set_without_consumers", lambda f: f["check_id"] == "H5"
     and f["object_type"] == "set" and f["object_guid"] == "s1"),
    # H7: one finding per table reference, the same reference twice included
    ("human_h7_reference_shapes", lambda f: f["check_id"] == "H7"
     and f["object_name"] == "Twice"),
    # H8: object named by a count, no guid, metric the size, three answers listed
    ("human_h8_group_shapes", lambda f: f["check_id"] == "H8"
     and f["object_name"] == "shared in 4 answers" and f["object_guid"] == ""
     and f["metric"] == 4 and f["detail"].endswith(": Q1, Q2, Q3")),
    ("human_h8_group_shapes", lambda f: f["check_id"] == "H8" and f["detail"]
     == "Formula duplicated in 2 answers but not in model: Q0, Q0"),
    # H9: a blank Answer expression matches a blank Model one; the later Model wins
    ("human_h9_match_shapes", lambda f: f["check_id"] == "H9"
     and f["detail"] == "Answer formula 'NoExpr' duplicates model formula 'Empty'"),
    ("human_h9_match_shapes", lambda f: f["check_id"] == "H9"
     and f["detail"] == "Answer formula '' duplicates model formula 'Second'"),
    # H10: Model and column findings; a description cut at 60 characters
    ("human_h10_name_shapes", lambda f: f["check_id"] == "H10" and f["object_type"] == "model"
     and f["detail"] == "Model name matches stale pattern: 'Sales (Backup)'"),
    ("human_h10_name_shapes", lambda f: f["check_id"] == "H10" and f["object_name"] == "Plain"
     and f["detail"] == "Column description matches stale pattern: 'Deprecated: this "
     "column will be removed once the new ledger '"),
    # raw None names and guids reach the finding as None
    ("human_names_none", lambda f: f["check_id"] == "H4" and f["object_guid"] is None),
    ("human_names_none", lambda f: f["check_id"] == "H5" and f["object_name"] is None
     and f["object_guid"] is None),
    ("human_names_none", lambda f: f["check_id"] == "H7" and f["object_name"] is None),
    ("human_names_none", lambda f: f["check_id"] == "H9" and f["object_name"] is None
     and f["detail"] == "Answer formula 'None' duplicates model formula 'None'"),
])
def test_h_rules_keep_legacy_names_guids_and_edges(profile, fixture, probe):
    import audit_rule_fixtures as fx

    build = getattr(fx, fixture, None) or fx.H_INPUTS[fixture]
    old, new = collect_both(build(), profile, H_RULES, categories=["H"])
    assert any(probe(f) for f in old), "the input must exercise the case"
    assert compare_findings(old, new)["identical"] is True
