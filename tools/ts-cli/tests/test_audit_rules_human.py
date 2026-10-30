"""The H (Human Readiness) rules' engine parts: the derived fields (engine/
fields_human.py), the code rules (engine/code_rules_human.py) and H6, the retired rule
with no logic. The H rules' legacy answers are pinned in test_audit_pinned_findings.py;
the rules' catalog examples in test_audit_rule_examples.py."""
from __future__ import annotations

import copy

import pytest

import audit_rule_fixtures as fx
from ts_cli.audit.catalog_model import build_catalog, load_catalog, load_raw
from ts_cli.audit.catalog_validate import validate_catalog
from ts_cli.audit.context import make_context
from ts_cli.audit.engine import code_rules, code_rules_human, fields, scopes
from ts_cli.audit.engine.run import run_rule, run_rules


def _children_of(ctx, scope):
    return list(scopes.iterate(ctx, scope))


def _by_name(ctx, scope, field):
    return {i["name"]: fields.get(i, field, ctx) for i in _children_of(ctx, scope)}


# ── derived fields ──────────────────────────────────────────────────────────

def test_sole_join_carrier_looks_tables_up_by_alias():
    """K1 sits on DIM aliased D1, which declares its own join: joined by its alias, so
    exempt (by name, before 2026-10, it was reported)."""
    got = _by_name(fx.human_h3_join_edges(), "model.column", "@is_sole_join_carrier")
    assert got == {"K": True, "X": False, "Y": True, "K1": True, "KA": True,
                   "NOID": False, "LK": False}


def test_sole_join_carrier_skips_the_column_itself_by_identity():
    got = [fields.get(i, "@is_sole_join_carrier", ctx) for ctx in
           [fx.human_h3_shared_column_object()] for i in _children_of(ctx, "model.column")]
    assert got == [True, True]


def test_referenced_by_formula_reads_ids_and_display_names():
    """ById's formula is referenced only as `[formula_ById]`, how TML writes it: seen
    since 2026-10."""
    got = _by_name(fx.human_h3_formula_edges(), "model.column", "@referenced_by_formula")
    assert got == {"Amount": True, "Calc": True, "ById": True, "Str": False,
                   "Zero": False, "NoProps": False}


def test_referenced_by_formula_ignores_a_non_string_expression():
    ctx = make_context(models=[fx.build_human_model(
        columns=[{"name": "A"}], formulas=[{"expr": None}, {"expr": "[A]"}])])
    assert _by_name(ctx, "model.column", "@referenced_by_formula") == {"A": True}


def test_dependent_count_excludes_set_rows():
    got = _by_name(fx.human_h4_dependent_shapes(), "model", "@dependent_count")
    assert got == {"OnlySets": 0, "SetAndBoard": 1, "NoGuid": 1, "Unlisted": 0}


def test_set_consumers_is_the_looked_up_list():
    ctx = fx.human_h5_set_shapes()
    got = {i["guid"]: fields.get(i, "@set_consumers", ctx) for i in _children_of(ctx, "set")}
    assert got == {"": [], "s1": [{"guid": "s2", "type": "SET", "name": "Child"}],
                   "s9": None, "s2": []}


def test_is_table_reference_knows_model_tables_and_context_tables():
    ctx = fx.human_h7_reference_shapes()
    got = [(i["name"], i["obj"].get("fqn"), fields.get(i, "@is_table_reference", ctx))
           for i in _children_of(ctx, "answer.table_ref")]
    assert got == [("Two", "tbl-orders", True), ("Two", "tbl-only-ctx", True),
                   ("Twice", "tbl-orders", True), ("Twice", "tbl-orders", True),
                   ("Blank", "", False), ("Blank", None, False),
                   ("", "tbl-only-ctx", True), ("Model", "mdl-1", False)]


@pytest.mark.parametrize("expr,normalized", [
    ("  SUM( [X] )\t", "sum( [x] )"), ("a\n\n b", "a b"), ("", ""), ("   ", ""),
    (None, None), (5, None)])
def test_normalized_expr(expr, normalized):
    item = {"obj": {"expr": expr}, "parent": None}
    assert fields.get(item, "@normalized_expr", make_context()) == normalized


def test_absent_expr_normalizes_to_empty():
    assert fields.get({"obj": {}, "parent": None}, "@normalized_expr", make_context()) == ""


def test_model_formula_match_and_name_last_wins():
    ctx = fx.human_h9_match_shapes()
    got = [(fields.get(i, "@matches_model_formula", ctx),
            fields.get(i, "@matched_model_formula_name", ctx),
            fields.get(i, "@answer_name", ctx)) for i in _children_of(ctx, "answer.formula")]
    assert got == [(True, "Empty", "Q0"), (False, None, "Q0"), (True, "Second", "Q1")]


# ── code rules ──────────────────────────────────────────────────────────────

def test_h_code_rules_declare_what_they_read():
    assert code_rules.SEVERITY_SOURCES["description_quality"] == "severity"
    assert code_rules.SEVERITY_SOURCES["stale_names"] == "severity"
    assert code_rules.CODE_USES["stale_names"] == frozenset()  # @orphan_model declares them
    assert code_rules.PLACEHOLDERS["description_quality"] == {"count", "issues"}
    assert code_rules.PLACEHOLDERS["stale_names"] == {"what", "value"}
    assert not {"description_quality", "stale_names"} & code_rules.OWN_THRESHOLD


@pytest.mark.parametrize("desc,issue", [
    ("x" * 19, "'C' too short (19 chars)"), ("x" * 20, None), ("x" * 400, None),
    ("x" * 401, "'C' too long (401 chars)"), ("  " + "x" * 19 + "  ", "'C' too short (19 chars)"),
    ("The opening is ordinary prose here.", None),  # "The "/"A " dropped 2026-10
    ("A plain sentence that is long enough.", None),
    ("Column for the net amount of the order.", "'C' uses boilerplate pattern"),
    ("this is a column with enough characters.", "'C' uses boilerplate pattern"),
    ("Them apples are counted in this one.", None), ("   ", None), (None, None), (5, None)])
def test_description_issue(desc, issue):
    assert code_rules_human.description_issue(
        {"name": "C", "description": desc}, min_chars=20, max_chars=400) == issue


@pytest.mark.parametrize("name,stale", [
    ("Sales_old", True), ("test_results", False), ("test_results old", False),
    ("Contest", False), ("Test 2", True), ("Template", False), ("Region (2)", True),
    (None, False), (5, False)])
def test_is_stale_name(name, stale):
    assert code_rules_human.is_stale_name(name) is stale


def _stale_model_ctx(dependents):
    return make_context(models=[fx.build_human_model(name="Sales_old", columns=[
        {"name": "tmp_a", "description": "Temporary"}, {"name": "B", "description": 7}])],
        dependents=dependents)


def test_stale_names_reports_model_then_columns_in_order():
    ctx = _stale_model_ctx({"m-1": [{"id": "a-1", "type": "ANSWER", "name": "A"}]})
    got = [(f.object_type, f.object_name, f.detail, f.severity)
           for f in run_rule(ctx, load_catalog(), "H10", "general")]
    assert got == [
        ("model", "Sales_old", "Model name matches stale pattern: 'Sales_old'", "LOW"),
        ("column", "tmp_a", "Column name matches stale pattern: 'tmp_a'", "LOW"),
        ("column", "tmp_a", "Column description matches stale pattern: 'Temporary'", "LOW")]


@pytest.mark.parametrize("dependents", [{}, {"m-1": [{"id": "s-1", "type": "SET",
                                                      "name": "S"}]}])
def test_a_stale_model_name_on_an_orphan_model_is_medium(dependents):
    """H10 MEDIUM "if also orphan" (BL-406 item 2, 2026-10): H4's test — no dependents
    but Sets. Only the Model-name finding moves; column findings stay LOW."""
    got = [(f.object_type, f.severity, f.detail)
           for f in run_rule(_stale_model_ctx(dependents), load_catalog(), "H10", "general")]
    assert got[0] == ("model", "MEDIUM", "Model name matches stale pattern: 'Sales_old', "
                      "and nothing uses the Model")
    assert [s for t, s, _ in got[1:]] == ["LOW", "LOW"]


# ── H6: retired with no logic ───────────────────────────────────────────────

def test_h6_is_retired_with_no_logic_and_never_runs():
    cat = load_catalog()
    h6 = cat.rules["H6"]
    assert (h6.status, h6.implementation, h6.aggregate, h6.examples) == (
        "retired", "declarative", {}, {})
    assert run_rule(fx.human_rich_context(), cat, "H6", "general") == []
    assert not [f for f in run_rules(fx.human_rich_context(), cat, ["H"], "spotter")
                if f.check_id == "H6"]


def test_reviving_a_rule_with_no_logic_raises_at_run_time():
    with pytest.raises(ValueError, match="H6: has no logic"):
        run_rule(fx.human_rich_context(), load_catalog(), "H6", "general",
                 layers=[{"H6": {"status": "active"}}])


def _shipped_with(rule_id, edit):
    raw = copy.deepcopy(load_raw())
    [rule] = [r for f, rules in raw.items() if f.startswith("rules/") for r in rules
              if r["id"] == rule_id]
    edit(rule)
    return validate_catalog(build_catalog(raw), raw)


def test_a_profile_cannot_revive_a_rule_with_no_logic():
    problems = _shipped_with("H6", lambda r: r.update(profiles={"spotter": {"status": "active"}}))
    assert any("H6: profiles.spotter.status: a retired rule with no logic" in p
               for p in problems), problems


def test_an_active_rule_still_needs_its_logic():
    problems = _shipped_with("H6", lambda r: r.update(status="active"))
    assert any("H6: aggregate.mode is required for a declarative rule" in p
               for p in problems), problems


def test_h2_reads_its_parameters_and_an_override_replaces_them():
    """`parameters` reach the code rule, and a later layer replaces the map whole."""
    ctx = make_context(models=[fx.build_human_model(columns=[
        {"name": "A", "description": "x" * 15}, {"name": "B", "description": "y" * 15}])])
    cat = load_catalog()
    [base] = run_rule(ctx, cat, "H2", "general")
    assert base.metric == 2
    looser = {"H2": {"parameters": {"min_chars": 10, "max_chars": 400, "issues_shown": 1}}}
    assert run_rule(ctx, cat, "H2", "general", layers=[looser]) == []
    shown = {"H2": {"parameters": {"min_chars": 20, "max_chars": 400, "issues_shown": 1}}}
    [one] = run_rule(ctx, cat, "H2", "general", layers=[shown])
    assert one.metric == 2 and one.detail.count("too short") == 1
