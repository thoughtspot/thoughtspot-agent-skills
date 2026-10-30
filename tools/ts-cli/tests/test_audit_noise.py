"""Roadmap PR 2.3 — the noise fixes, held directly (the alias, H2 and S1 changes also
in test_audit_engine.py, test_audit_rules_human.py and test_checks_data_trip.py).

- D3 rolls a Model's LEFT/RIGHT outer joins into one INFO finding; FULL OUTER stays HIGH
  per join.
- A1 and A2 count visible columns only.
- S5 matches a spaced "API Key" / "Secret Key".
"""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule
from ts_cli.audit.context import make_context


def _joined_model(*types):
    """FACT joined to D0, D1, … with the given join types."""
    tables = [{"name": "FACT", "fqn": "t-f", "joins": [
        {"with": f"D{i}", "on": f"[FACT::K{i}] = [D{i}::K]", "type": t,
         "cardinality": "MANY_TO_ONE"} for i, t in enumerate(types)]}]
    tables += [{"name": f"D{i}", "fqn": f"t-d{i}"} for i in range(len(types))]
    return make_context(models=[fx.build_data_model(name="Sales", guid="m-1",
                                                    model_tables=tables)])


def test_d3_rolls_one_sided_outer_joins_into_one_info_per_model():
    findings = run_rule(_joined_model("LEFT_OUTER", "INNER", "RIGHT_OUTER", "left_outer"),
                        "D3")
    [f] = findings
    assert (f.severity, f.object_type, f.object_name, f.metric) == ("INFO", "model", "Sales", 3)
    assert f.detail == ("3 LEFT/RIGHT outer join(s), which may drop or add rows in results: "
                        "FACT -> D0 (LEFT_OUTER), FACT -> D2 (RIGHT_OUTER), "
                        "FACT -> D3 (LEFT_OUTER)")


def test_d3_keeps_a_high_finding_per_full_outer_join_before_the_roll_up():
    findings = run_rule(_joined_model("OUTER", "LEFT_OUTER", "OUTER"), "D3")
    assert [(f.severity, f.object_type, f.object_name) for f in findings] == [
        ("HIGH", "join", "FACT -> D0"), ("HIGH", "join", "FACT -> D2"),
        ("INFO", "model", "Sales")]


def test_d3_is_silent_on_inner_joins():
    assert run_rule(_joined_model("INNER", "INNER"), "D3") == []


def _ai_model(cols):
    return make_context(models=[fx.build_ai_model(columns=cols)])


def test_a1_and_a2_leave_hidden_columns_out():
    """Two visible columns, both described and with synonyms; ten hidden ones with
    neither. Counted over all columns this is 2/12 (17%, HIGH); visible only, 2/2."""
    visible = [dict(fx.build_ai_col(n, description="good"),
                    properties={"synonyms": ["x"]}) for n in ("A", "B")]
    hidden = [dict(fx.build_ai_col(f"H{i}"), properties={"is_hidden": True})
              for i in range(10)]
    ctx = _ai_model(visible + hidden)
    assert run_rule(ctx, "A1", "spotter") == []
    assert run_rule(ctx, "A2", "spotter") == []


def test_a1_reports_against_visible_columns():
    cols = [fx.build_ai_col("A", description="good"), fx.build_ai_col("B"),
            dict(fx.build_ai_col("H", description="good"), properties={"is_hidden": True})]
    [f] = run_rule(_ai_model(cols), "A1", "spotter")
    assert f.detail == "1/2 visible columns have descriptions (50%)"


def test_s5_matches_spaced_credential_names():
    cols = [{"name": n, "properties": {}} for n in ("API Key", "Secret Key", "Monkey")]
    ctx = make_context(models=[fx.build_data_model(columns=cols)])
    assert sorted((f.object_name, f.severity) for f in run_rule(ctx, "S5")) == [
        ("API Key", "CRITICAL"), ("Secret Key", "CRITICAL")]
