"""S17: a Table carrying RLS rules at the root of a Model's joins, beside another root.

Live-verified 2026-11-12 (internal dev cluster, a non-admin user under a table RLS rule):
an access-control table joined many-to-one to a dimension — or the dimension joined to it
one-to-many, which is byte-identical — is planned as a second fact, two CTEs stitched by
an outer join; the dimension joined many-to-one to it makes it a leaf and one flat query.
"""
from __future__ import annotations

import audit_rule_fixtures as fx
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context
from ts_cli.audit.engine import fields, scopes
from ts_cli.audit.engine.fields_data import RLS_ROOT_FIXES


def _s17(ctx):
    out = run_audit(None, [], ctx=ctx, angles=["S"])
    return [(f["object_name"], f["severity"]) for f in out["findings"]
            if f["check_id"] == "S17"]


def _tables(ctx):
    return {i["name"]: i for i in scopes.iterate(ctx, "model.table")}


def test_fires_on_the_acl_table_as_a_second_root():
    assert _s17(fx.sec_rls_acl_table_as_root()) == [("ACL_USER_SITE", "HIGH")]


def test_one_to_many_from_the_dimension_is_the_same_plan():
    """Direction is decided by cardinality, not by which table declares the join: D_SITE
    declaring ONE_TO_MANY to the ACL table leaves the ACL table a root (variant 2)."""
    ctx = fx.sec_rls_acl_table_one_to_many()
    assert _s17(ctx) == [("ACL_USER_SITE", "HIGH")]
    assert list(fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_beside", ctx)) == [
        "F_ORDER"]


def test_silent_when_the_dimension_joins_the_acl_table_many_to_one():
    ctx = fx.sec_rls_acl_table_as_leaf()
    assert _s17(ctx) == []
    assert list(fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_beside", ctx)) == []


def test_silent_when_the_rls_is_on_the_only_root():
    """RLS on the fact itself, with the ACL table a leaf: the fact is the only root."""
    assert _s17(fx.build_acl_ctx("dim_to_acl", rule_expr="[F_ORDER_1::ORDER_ID] = ts_username",
                                 rls_on="F_ORDER")) == []


def test_silent_when_the_acl_table_has_no_rls():
    """Two roots and no RLS anywhere: a multi-root plan, not this rule's concern."""
    assert _s17(fx.build_acl_ctx("acl_to_dim", rls_on="NONE")) == []


def test_missing_cardinality_reads_as_many_to_one():
    ctx = fx.sec_rls_acl_table_as_root()
    acl = ctx.models[0]["model"]["model_tables"][2]
    del acl["joins"][0]["cardinality"]
    assert _s17(ctx) == [("ACL_USER_SITE", "HIGH")]


def test_undirected_and_unjoined_acl_tables_are_not_roots():
    """ONE_TO_ONE gives no direction (the shared role classifier), and an unjoined table
    is D5's: neither is a root here."""
    ctx = fx.sec_rls_acl_table_as_root()
    acl = ctx.models[0]["model"]["model_tables"][2]
    acl["joins"][0]["cardinality"] = "ONE_TO_ONE"
    assert _s17(ctx) == []
    del acl["joins"]
    assert _s17(ctx) == []


def test_rls_root_beside_absent_data_reads_as_none():
    """No Table TML in scope, no fqn, malformed rules: unknown, never raises."""
    ctx = fx.sec_rls_acl_table_as_root()
    del ctx.tables["t-acl_user_site"]
    assert list(fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_beside", ctx)) == []

    ctx = fx.sec_rls_acl_table_as_root()
    del ctx.models[0]["model"]["model_tables"][2]["fqn"]
    assert list(fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_beside", ctx)) == []

    ctx = fx.sec_rls_acl_table_as_root()
    ctx.tables["t-acl_user_site"]["table"]["rls_rules"]["rules"] = "junk"
    assert list(fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_beside", ctx)) == []

    ctx = fx.sec_rls_acl_table_as_root()
    ctx.models[0]["model"]["model_tables"][2]["alias"] = ["odd"]     # a non-string key
    odd = [i for i in scopes.iterate(ctx, "model.table") if not isinstance(i["name"], str)]
    assert [list(fields.get(i, "@rls_root_beside", ctx)) for i in odd] == [[]]

    bare = make_context(models=[{"guid": "g", "model": {"name": "M", "model_tables": [
        {"name": "A", "fqn": "t-a"}]}}], tables={"t-a": {"table": {"rls_rules": {
            "rules": [{"expr": "[A_1::K] = ts_username"}]}}}})
    (only,) = scopes.iterate(bare, "model.table")
    assert list(fields.get(only, "@rls_root_beside", bare)) == []


def test_unjoined_fact_is_not_a_second_root():
    """Only the ACL table is a joined root; F_ORDER, holding a measure, is unjoined (D5's).
    Without the `unjoined` exclusion F_ORDER would read as a root and S17 would fire."""
    ctx = fx.sec_rls_acl_table_as_root()
    del ctx.models[0]["model"]["model_tables"][0]["joins"]
    assert _s17(ctx) == []
    assert list(fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_beside", ctx)) == []


def test_silent_on_a_genuine_fact_with_rls():
    """An RLS table holding a measure is a fact of a multi-fact Model, not an access
    table: silent, whatever its rules key on."""
    for expr in ("ts_username = [ACL_USER_SITE_1::USER_KEY]",
                 "[ACL_USER_SITE_1::USER_KEY] = ts_groups"):
        ctx = fx.build_acl_ctx("acl_to_dim", rule_expr=expr)
        ctx.models[0]["model"]["columns"].append({
            "name": "ACL_USER_SITE QTY", "column_id": "ACL_USER_SITE::QTY",
            "properties": {"column_type": "MEASURE"}})
        assert _s17(ctx) == [], expr


def test_silent_on_a_fact_whose_measures_are_formulas():
    """No MEASURE column of its own, but a formula measure reads it: a fact, not an
    access table (the role classifier reads `column_id` columns only), directly or
    through another formula."""
    for exprs in (["unique count ( [ACL_USER_SITE::USER_KEY] )"],
                  ["[formula_inner] * 2", "count ( [ACL_USER_SITE::SITE_ID] )"]):
        ctx = fx.build_acl_ctx("acl_to_dim")
        m = ctx.models[0]["model"]
        m["formulas"] = [{"id": "formula_outer" if k == 0 else "formula_inner",
                          "name": "Outer" if k == 0 else "Inner", "expr": e}
                         for k, e in enumerate(exprs)]
        m["columns"].append({"name": "Outer", "formula_id": "formula_outer",
                             "properties": {"column_type": "MEASURE"}})
        assert _s17(ctx) == [], exprs
    # an ATTRIBUTE formula reading it is not a measure: still fires
    ctx = fx.build_acl_ctx("acl_to_dim")
    m = ctx.models[0]["model"]
    m["formulas"] = [{"id": "formula_a", "name": "A", "expr": "[ACL_USER_SITE::USER_KEY]"}]
    m["columns"].append({"name": "A", "formula_id": "formula_a",
                         "properties": {"column_type": "ATTRIBUTE"}})
    assert _s17(ctx) == [("ACL_USER_SITE", "HIGH")]


def test_rls_root_fix_reverses_only_for_one_user_equals_key_rule():
    for expr, safe in [
        ("ts_username = [ACL_USER_SITE_1::USER_KEY]", True),
        ("[ACL_USER_SITE_1::USER_KEY]  =  TS_USERNAME", True),
        ("[ACL_USER_SITE_1::TS_GROUPS_KEY] = ts_username", True),       # a column name
        ("ts_username = [ACL_USER_SITE_1::USER_KEY] and 'ts_groups' = 'x'", False),
        ("[ACL_USER_SITE_1::USER_KEY] = ts_groups", False),
        ("'site admins' in ts_groups or ts_username = [ACL_USER_SITE_1::USER_KEY]", False),
        ("[ACL_USER_SITE_1::USER_KEY] = ts_groups_int", False),
        ("[ACL_USER_SITE_1::USER_KEY] = ts_var ( site_regions )", False),
        ("ts_username = [ACL_USER_SITE_1::USER_KEY] or [ACL_USER_SITE_1::IS_PUBLIC] = 'Y'",
         False),
        ("ts_username != 'guest'", False),
        ("ts_username = 'alice'", False),
        ("ts_username != [ACL_USER_SITE_1::USER_KEY]", False),
        ("contains ( [ACL_USER_SITE_1::USERS], ts_username )", False),
        ("[ACL_USER_SITE_1::USER_KEY] in ( ts_username , 'public' )", False),
        ("if ( ts_username = 'admin' ) then true else ts_username = [ACL_USER_SITE_1::USER_KEY]",
         False),
        ("not ( ts_username = [ACL_USER_SITE_1::USER_KEY] )", False),
    ]:
        ctx = fx.build_acl_ctx("acl_to_dim", rule_expr=expr)
        got = fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_fix", ctx)
        assert got == RLS_ROOT_FIXES[1 if safe else 0], expr


def test_rls_root_fix_keeps_the_join_for_two_rules():
    """A Table's rules combine with OR: owner on one row and delegate on another gives a
    user two rows per key, though each rule alone is `ts_username = [column]`."""
    ctx = fx.build_acl_ctx("acl_to_dim")
    ctx.tables["t-acl_user_site"]["table"]["rls_rules"]["rules"].append(
        {"name": "Delegate", "expr": "ts_username = [ACL_USER_SITE_1::DELEGATE]"})
    assert fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_fix", ctx) == RLS_ROOT_FIXES[0]


def test_rls_root_fix_detail_for_ts_groups():
    ctx = fx.build_acl_ctx("acl_to_dim", rule_expr="[ACL_USER_SITE_1::USER_KEY] = ts_groups")
    out = run_audit(None, [], ctx=ctx, angles=["S"])
    (detail,) = [f["detail"] for f in out["findings"] if f["check_id"] == "S17"]
    assert "review its rules" in detail and "ts_username = [column]" in detail


def test_rls_root_fix_without_table_tml_keeps_the_join():
    """No rules to read: never advise the reversal."""
    ctx = fx.sec_rls_acl_table_as_root()
    del ctx.tables["t-acl_user_site"]
    assert fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_fix", ctx) == RLS_ROOT_FIXES[0]
