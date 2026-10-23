"""Alias blindness, and joins reported with no name (BL-305).

A `model_tables[]` entry with an `alias` prefixes its columns' `column_id` with
the **alias**, not the table name (model schema: `column_id` is
`TABLE_NAME::col`, where TABLE_NAME is "the `name:` (or `alias:`) from
model_tables"). Several checks keyed on `name`, so a role-playing dimension
resolved to no columns at all: D10 reported a fully-populated table as a
zero-column leaf, D6 and D11 silently saw "unknown".

Separately, every join finding was anonymous. `model_tables[].joins[]` carries
no `name` key — none of the 493 joins in the 2026-07-30 census has one — so
`j.get("name", "")` was always `""` and the report could not identify which join
a finding was about.
"""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule
from ts_cli.audit.engine import tml


def _aliased_model():
    """One physical table joined twice, the second under an alias (the model document
    of the named builder audit_rule_fixtures.data_model_aliased_role_playing, whose legacy D
    answers test_audit_pinned_findings.py pins)."""
    return fx.data_model_aliased_role_playing().models[0]


# ── the shared key ─────────────────────────────────────────────────────────

def test_table_key_prefers_the_alias():
    assert tml.table_key({"name": "CUSTOMERS", "alias": "SHIP_TO"}) == "SHIP_TO"
    assert tml.table_key({"name": "ORDERS"}) == "ORDERS"
    assert tml.table_key({}) == ""


def test_table_role_resolves_an_aliased_table():
    m = _aliased_model()["model"]
    cols, mts = m["columns"], m["model_tables"]
    assert tml.table_role(cols, tml.table_key(mts[1])) == "dimension"
    # Keying on the physical name is what made it invisible.
    assert tml.table_role(cols, mts[1]["name"]) == "unknown"


# ── D10 must not call a populated aliased table a zero-column leaf ─────────

def test_d10_does_not_call_an_aliased_table_a_zero_column_leaf():
    findings = run_rule(fx.data_model_aliased_role_playing(), "D10")
    leaf = [f for f in findings if "leaf" in f.detail.lower() and "SHIP_TO" in f.detail]
    assert leaf == [], f"SHIP_TO has three columns: {[f.detail for f in findings]}"


def test_d6_sees_the_columns_of_an_aliased_table():
    """Not asserting a finding — asserting the table is no longer 'unknown'."""
    m = _aliased_model()["model"]
    assert tml.table_role(m["columns"], "SHIP_TO") != "unknown"
    run_rule(fx.data_model_aliased_role_playing(), "D6")  # must not raise


# ── a join finding must identify its join ──────────────────────────────────

def test_join_label_names_both_sides():
    mt = {"name": "ORDERS"}
    assert tml.join_label(mt, {"with": "CUSTOMERS"}) == "ORDERS -> CUSTOMERS"


def test_join_label_prefers_a_declared_name_when_one_exists():
    mt = {"name": "ORDERS"}
    assert tml.join_label(mt, {"name": "orders_to_cust", "with": "CUSTOMERS"}) == "orders_to_cust"


def test_join_label_uses_the_alias_side():
    mt = {"name": "CUSTOMERS", "alias": "SHIP_TO"}
    assert tml.join_label(mt, {"with": "ORDERS"}) == "SHIP_TO -> ORDERS"


def test_a_join_finding_is_not_anonymous():
    """D3 flags an OUTER join; the report must say which one."""
    findings = run_rule(fx.data_model_anonymous_outer_join(), "D3")
    assert findings
    assert all(f.object_name for f in findings), "a join finding must name its join"
    assert "ORDERS" in findings[0].object_name and "RETURNS" in findings[0].object_name


# ── S2 must find the RLS on an aliased table ───────────────────────────────

def test_s2_sees_table_rls_through_an_alias():
    """A role-playing dimension with RLS must not be reported as unprotected."""
    import audit_rule_fixtures as fx
    findings = run_rule(fx.sec_alias_table_with_rls(), "S2")
    assert len(findings) == 1
    assert findings[0].severity == "INFO", "RLS is present — this is not a HIGH"


def test_s2_still_reports_a_table_with_no_rls():
    import audit_rule_fixtures as fx
    findings = run_rule(fx.sec_alias_table_without_rls(), "S2")
    assert len(findings) == 1 and findings[0].severity == "HIGH"
