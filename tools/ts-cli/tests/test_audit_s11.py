"""S11 — an RLS rule's join closes a cycle with the Model's joins (synthetic tables)."""
from __future__ import annotations

import audit_rule_fixtures as fx
from audit_run_rule import run_rule


def test_s11_fires_on_case_shape():
    found = run_rule(fx.sec_rls_join_cycle(), "S11")
    assert [(f.severity, f.object_type, f.object_name) for f in found] == [
        ("HIGH", "model", "Activity")]
    for word in ("users", "bridge", "users_to_bridge", "bridge_users"):
        assert word in found[0].detail


def test_s11_silent_same_direction():
    assert run_rule(fx.sec_rls_same_direction(), "S11") == []


def test_s11_maps_tables_by_fqn():
    """The users Table TML is found through model_tables[].fqn, not by its name: filed
    under another guid, the same body is not this Model's users table."""
    ctx = fx.build_rls_cycle_ctx(fx.sec_rls_join_cycle().tables["g-users"],
                                 users_fqn="g-someone-else")
    assert run_rule(ctx, "S11") == []


def test_s11_message_has_no_engine_ids():
    for f in run_rule(fx.sec_rls_join_cycle(), "S11"):
        assert "@" not in f.detail and "code:" not in f.detail
