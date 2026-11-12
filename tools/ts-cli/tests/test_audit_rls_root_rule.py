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


def test_rls_root_fix_says_keep_the_join_for_ts_groups():
    for expr, grouped in [
        ("ts_username = [ACL_USER_SITE_1::USER_KEY]", False),
        ("[ACL_USER_SITE_1::USER_KEY] = ts_groups", True),
        ("'site admins' in ts_groups or ts_username = [ACL_USER_SITE_1::USER_KEY]", True),
        ("[ACL_USER_SITE_1::USER_KEY] = ts_groups_int", True),          # any variant
        ("[ACL_USER_SITE_1::TS_GROUPS_KEY] = ts_username", False),      # a column name
        ("ts_username = [ACL_USER_SITE_1::USER_KEY] and 'ts_groups' = 'x'", False),  # literal
    ]:
        ctx = fx.build_acl_ctx("acl_to_dim", rule_expr=expr)
        got = fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_fix", ctx)
        assert got == RLS_ROOT_FIXES[0 if grouped else 1], expr
    ctx = fx.build_acl_ctx("acl_to_dim", rule_expr="[ACL_USER_SITE_1::USER_KEY] = ts_groups")
    out = run_audit(None, [], ctx=ctx, angles=["S"])
    (detail,) = [f["detail"] for f in out["findings"] if f["check_id"] == "S17"]
    assert "keep the join as it is" in detail and "ts_groups" in detail


def test_rls_root_fix_without_table_tml():
    ctx = fx.sec_rls_acl_table_as_root()
    del ctx.tables["t-acl_user_site"]
    assert fields.get(_tables(ctx)["ACL_USER_SITE"], "@rls_root_fix", ctx) == RLS_ROOT_FIXES[1]
