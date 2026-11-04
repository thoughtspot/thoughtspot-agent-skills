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
        ("isnull([ CUST_1::REGION ]) or [CUST_1::REGION] = ts_username", ["REGION"]),
        ("isnull ( [CUST_1::REGION] )", []),         # scopes no one: not the G5f shape
        ("[CUST_1::REGION] = ts_groups and 'isnull ( [CUST_1::REGION] )' = 'x'", []),
        ("isnull ( [CUST::REGION] ) or [CUST::REGION] = ts_groups", ["REGION"]),  # own name
    ]:
        rule["expr"] = expr
        (item,) = [i for i in scopes.iterate(ctx, "table.rls_rule") if i["guid"] == "t-cust"
                   or i["name"] == "CUST"]
        assert list(fields.get(item, "@own_column_null_tests", ctx)) == want, expr


# ── review of PR 5 ─────────────────────────────────────────────────────────

def _set_rules(ctx, orders, cust):
    for key, exprs in (("t-orders", orders), ("t-cust", cust)):
        rls = ctx.tables[key]["table"]["rls_rules"]
        if exprs is None:
            del ctx.tables[key]["table"]["rls_rules"]
        else:
            rls["rules"] = [{"name": f"r{i}", "expr": e} for i, e in enumerate(exprs)]


def test_s14_compares_tables_not_rules():
    """Two variables on ONE Table (an owner-or-group override) is not S14: it fires only
    when two Tables' RLS scopes differ."""
    for orders, cust in [
        (["[ORDERS_1::OWNER] = ts_username or 'admins' in ts_groups"], None),
        (["[ORDERS_1::OWNER] = ts_username", "'admins' in ts_groups"], None),
        (["[ORDERS_1::OWNER] = ts_username or 'admins' in ts_groups"],
         ["[CUST_1::REGION] = ts_username or 'admins' in ts_groups"]),
    ]:
        ctx = fx.sec_rls_two_tenant_variables()
        _set_rules(ctx, orders, cust)
        out = run_audit(None, [], ctx=ctx, angles=["S"])
        assert _ids(out, "S14") == [], (orders, cust)


def test_s14_reads_variables_outside_brackets_and_folds_case():
    ctx = fx.sec_rls_two_tenant_variables()
    _set_rules(ctx, ["[ORDERS_1::TS_ORG_ID] = ts_groups"], ["[CUST_1::REGION] = ts_groups"])
    assert _ids(run_audit(None, [], ctx=ctx, angles=["S"]), "S14") == []
    _set_rules(ctx, ["[ORDERS_1::OWNER] = ts_var ( Region_Var )"],
               ["[CUST_1::REGION] = ts_var ( region_var )"])
    assert _ids(run_audit(None, [], ctx=ctx, angles=["S"]), "S14") == []
    _set_rules(ctx, ["[ORDERS_1::OWNER] = ts_org"], ["[CUST_1::REGION] = ts_orgid"])
    (model,) = scopes.iterate(ctx, "model")
    assert "ts_orgid" not in str(fields.get(model, "@rls_session_variables", ctx))


def test_s15_spares_a_null_test_on_the_join_key():
    """`isnull ( [CUST_1::K] )` on a key that is never null keeps an outer join's
    unmatched rows without showing ownerless ones: the form S12 and S15 recommend."""
    ctx = fx.sec_rls_null_test_on_own_column()
    _set_rules(ctx, ["[ORDERS_1::OWNER] = ts_groups"],
               ["isnull ( [CUST_1::K] ) or [CUST_1::REGION] = ts_groups"])
    assert _ids(run_audit(None, [], ctx=ctx, angles=["S"]), "S15") == []


def test_a_malformed_table_path_id_ends_nothing():
    ctx = fx.sec_rls_null_test_on_own_column()
    ctx.tables["t-cust"]["table"]["rls_rules"]["table_paths"].append(
        {"id": ["CUST_1"], "table": "CUST"})
    run_audit(None, [], ctx=ctx, angles=["S"])
