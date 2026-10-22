"""The join checks were blind to the dominant real-world join shape (BL-306).

A model's `model_tables[].joins[]` entry is one of two shapes:

  inline       {with, on, type, cardinality}          — condition in the model
  referencing  {with, referencing_join[, type]}       — condition in the TABLE

For a referencing join the real definition lives in the source Table TML's
`joins_with[]`, keyed by the name `referencing_join` holds:

  {name, destination: {name, fqn}, on, type}

D2/D3/D11/P6 read only `joins[].on`, so they saw nothing on a referencing join.

Live-verified 2026-09-23 on se-thoughtspot: **0 of 6** joins in "Retail Sales -
RLS" carry an inline `on`, and one of them — `FK_BASKETFACT_TO_PROMOTIONDIM`,
`PROMOTION_KEY` VARCHAR on both sides — is exactly the VARCHAR join key P6/D2
exist to report. The audit reported zero.

Fixtures below use the real shapes from that export.
"""
import audit_rule_fixtures as fx
from ts_cli.audit import rules
from ts_cli.audit.checks_data import check_d2, check_d3
from ts_cli.audit.checks_perf import check_p6

# The contexts are named builders in audit_rule_fixtures.py (the shapes from that
# export), so the P6 catalog rule's equivalence test runs over exactly these inputs.


# ── the resolver ───────────────────────────────────────────────────────────

def test_resolver_finds_a_referencing_join_definition():
    ctx = fx.referencing_join_varchar()
    joins = list(rules.model_joins(ctx.models[0]["model"], ctx.tables))
    assert len(joins) == 1
    j = joins[0]
    assert j["name"] == "FK_BASKETFACT_TO_PROMOTIONDIM"
    assert "PROMOTION_KEY" in j["on"]
    assert j["type"] == "INNER"
    assert j["with"] == "PROMOTION_DIMENSION"


def test_the_models_inline_type_overrides_the_tables():
    """Observed live: the model said LEFT_OUTER over a table that says INNER."""
    ctx = fx.referencing_join_model_type_override()
    j = list(rules.model_joins(ctx.models[0]["model"], ctx.tables))[0]
    assert j["type"] == "LEFT_OUTER"


def test_an_inline_join_still_resolves():
    model = {"guid": "m-1", "model": {"name": "M", "columns": [], "model_tables": [
        {"name": "A", "joins": [{"with": "B", "on": "[A::K] = [B::K]",
                                 "type": "INNER", "cardinality": "MANY_TO_ONE"}]}]}}
    j = list(rules.model_joins(model["model"], {}))[0]
    assert j["on"] == "[A::K] = [B::K]" and j["type"] == "INNER"


def test_a_referencing_join_with_no_matching_table_yields_no_condition():
    """Unknown is not the same as 'no keys' — callers must not read it as clean."""
    ctx = fx.referencing_join_table_missing()
    j = list(rules.model_joins(ctx.models[0]["model"], ctx.tables))[0]
    assert j["on"] == ""


# ── the checks that were blind ─────────────────────────────────────────────

def test_p6_reports_the_varchar_key_of_a_referencing_join():
    """The exact finding the live audit missed."""
    findings = check_p6(fx.referencing_join_varchar())
    assert len(findings) == 1, "a VARCHAR join key must be reported"
    assert "PROMOTION_KEY" in findings[0].detail


def test_d2_reports_it_too():
    assert len(check_d2(fx.referencing_join_varchar())) == 1


def test_an_integer_referencing_join_is_not_reported():
    assert check_p6(fx.referencing_join_integer()) == []
    assert check_d2(fx.referencing_join_integer()) == []


def test_d3_sees_a_referencing_joins_type():
    findings = check_d3(fx.referencing_join_outer())
    assert findings, "an OUTER join defined in the table must be seen"


def test_join_findings_use_the_declared_name():
    """`joins_with[]` carries a real name — better than a synthesised one."""
    f = check_p6(fx.referencing_join_varchar())[0]
    assert f.object_name == "FK_BASKETFACT_TO_PROMOTIONDIM"
