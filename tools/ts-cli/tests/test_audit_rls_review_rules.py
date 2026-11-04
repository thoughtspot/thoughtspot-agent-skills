"""BL-512: two RLS judgement checks, LOW and worded "review" (product owner, 2026-11-04).

S14 (G5e): one Model's RLS Tables scope users through different session variables —
`ts_username` on one, `ts_groups` on another, a custom `ts_var ( … )` on a third — so the
same user can be scoped differently by different Tables of one search.
S15 (G5f): an RLS rule with a null test on its own Table's column. The docs give the null
test for outer joins (S12), but on the secured Table's own key it also shows every row
with no value there to every user under the rule.
"""
from __future__ import annotations

import audit_rule_fixtures as fx
from ts_cli.audit import run_audit
from ts_cli.audit.engine import fields, scopes


def _ids(out, rule):
    return [(f["object_name"], f["severity"]) for f in out["findings"] if f["check_id"] == rule]


def test_s14_fires_on_two_variables_and_not_on_variants_of_one():
    out = run_audit(None, [], ctx=fx.sec_rls_two_tenant_variables(), angles=["S"])
    assert _ids(out, "S14") == [("Sales", "LOW")]
    out = run_audit(None, [], ctx=fx.sec_rls_one_tenant_variable(), angles=["S"])
    assert _ids(out, "S14") == []


def test_rls_session_variables_reads_families():
    ctx = fx.sec_rls_two_tenant_variables()
    t = ctx.tables["t-cust"]["table"]["rls_rules"]["rules"][0]
    t["expr"] = "[CUST_1::REGION] = ts_var ( region_var ) or [CUST_1::REGION] = 'x ts_org'"
    (model,) = scopes.iterate(ctx, "model")
    assert list(fields.get(model, "@rls_session_variables", ctx)) == [
        "ts_username", "ts_var(region_var)"]          # a literal's text is not a variable


def test_s15_fires_on_its_own_column_only():
    out = run_audit(None, [], ctx=fx.sec_rls_null_test_on_own_column(), angles=["S"])
    assert _ids(out, "S15") == [("CUST", "LOW")]
    out = run_audit(None, [], ctx=fx.sec_rls_null_test_on_joined_column(), angles=["S"])
    assert _ids(out, "S15") == []


def test_own_column_null_tests_reads_each_spelling():
    ctx = fx.sec_rls_null_test_on_own_column()
    rule = ctx.tables["t-cust"]["table"]["rls_rules"]["rules"][0]
    for expr, want in [
        ("is_null ( [CUST_1::REGION] ) or [CUST_1::REGION] = ts_groups", ["REGION"]),
        ("[CUST_1::REGION] = null or [CUST_1::REGION] = ts_groups", ["REGION"]),
        ("isnull([ CUST_1::REGION ])", ["REGION"]),
        ("[CUST_1::REGION] = ts_groups and 'isnull ( [CUST_1::REGION] )' = 'x'", []),
        ("isnull ( [CUST::REGION] )", ["REGION"]),        # the Table's own name, no path id
    ]:
        rule["expr"] = expr
        (item,) = [i for i in scopes.iterate(ctx, "table.rls_rule") if i["guid"] == "t-cust"
                   or i["name"] == "CUST"]
        assert list(fields.get(item, "@own_column_null_tests", ctx)) == want, expr
