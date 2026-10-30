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


# ── review of PR 2.3: join targets, P7, H3, S1, the ERD target ──────────────

from ts_cli.audit.engine import tml  # noqa: E402


def test_join_target_resolves_a_node_identity_before_a_physical_name():
    """FACT joins `with: CUSTOMER`. The entry NAMED CUSTOMER is aliased BILL_TO; the entry
    whose alias IS CUSTOMER is the join's target, as the join graph resolves it, whatever
    the list order."""
    tables = [{"name": "FACT", "joins": [{"with": "CUSTOMER"}]},
              {"name": "CUSTOMER", "alias": "BILL_TO"},
              {"name": "CUST_TBL", "alias": "CUSTOMER"}]
    assert tml.join_target(tables, "CUSTOMER")["name"] == "CUST_TBL"
    assert tml.joined_keys(tables) == {"FACT", "CUSTOMER"}
    # a `with` written as a physical name still resolves, last
    assert tml.join_target(tables[:2], "customer")["alias"] == "BILL_TO"
    assert tml.join_target(tables, "NOPE") is None


def test_d5_reports_the_unjoined_table_not_the_join_target():
    tables = [{"name": "FACT", "joins": [{"with": "CUSTOMER", "on": "[FACT::K] = [CUSTOMER::K]"}]},
              {"name": "CUSTOMER", "alias": "BILL_TO"},
              {"name": "CUST_TBL", "alias": "CUSTOMER"}]
    ctx = make_context(models=[fx.build_data_model(model_tables=tables)])
    assert [f.object_name for f in run_rule(ctx, "D5")] == ["BILL_TO"]


def _chain(n, aliased):
    """T0 -> T1 -> … -> T{n-1}, every table aliased A0… when `aliased`."""
    key = (lambda i: f"A{i}") if aliased else (lambda i: f"T{i}")
    tables = []
    for i in range(n):
        t = {"name": f"T{i}", "fqn": f"t-{i}"}
        if aliased:
            t["alias"] = key(i)
        if i + 1 < n:
            t["joins"] = [{"with": key(i + 1), "on": f"[{key(i)}::K] = [{key(i + 1)}::K]"}]
        tables.append(t)
    return tables


def test_join_depth_follows_aliased_tables():
    """Keyed by name, a chain of aliased tables read as depth 1, and P7 missed it."""
    assert tml.join_depth(_chain(6, aliased=False)) == 5
    assert tml.join_depth(_chain(6, aliased=True)) == 5
    ctx = make_context(models=[fx.build_data_model(model_tables=_chain(7, aliased=True))])
    [f] = run_rule(ctx, "P7")
    assert (f.severity, f.metric) == ("HIGH", 6)


def test_h3_credits_a_table_column_reference():
    cols = [{"name": "Amount", "column_id": "T1::AMOUNT", "properties": {"is_hidden": True}},
            {"name": "Seen", "column_id": "T1::SEEN", "properties": {}}]
    formulas = [{"id": "f1", "name": "F", "expr": "sum ( [T1::AMOUNT] )"}]
    ctx = make_context(models=[fx.build_human_model(columns=cols, formulas=formulas)])
    assert run_rule(ctx, "H3") == []


def test_erd_target_is_the_first_table_the_detail_names():
    from ts_cli.audit import _inject_findings_into_erd
    from ts_cli.audit.findings import Finding
    corpus = {"models": [{"guid": "m-1", "erd": {
        "tables": [{"id": n} for n in ("D2", "D0", "FACT", "D1")], "findings": []}}]}
    f = Finding("D3", "x", "INFO", "model", "Sales", "m-1",
                "3 LEFT/RIGHT outer join(s): FACT -> D0 (LEFT_OUTER), FACT -> D2 (LEFT_OUTER)")
    _inject_findings_into_erd(corpus, [f], {})
    assert corpus["models"][0]["erd"]["findings"][0]["target"] == "FACT"
