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
from ts_cli.audit import rules
from ts_cli.audit.checks_data import check_d6, check_d10
from ts_cli.audit.context import make_context


def _aliased_model():
    """One physical table joined twice, the second under an alias."""
    return {"guid": "m-1", "model": {
        "name": "Sales",
        "columns": (
            [{"name": f"M{i}", "column_id": f"ORDERS::M{i}",
              "properties": {"column_type": "MEASURE"}} for i in range(4)]
            + [{"name": f"A{i}", "column_id": f"SHIP_TO::A{i}",
                "properties": {"column_type": "ATTRIBUTE"}} for i in range(3)]
        ),
        "model_tables": [
            {"name": "ORDERS", "joins": [{"with": "SHIP_TO", "on": "[ORDERS::M0] = [SHIP_TO::A0]",
                                          "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
            {"name": "CUSTOMERS", "alias": "SHIP_TO"},
        ],
    }}


# ── the shared key ─────────────────────────────────────────────────────────

def test_table_key_prefers_the_alias():
    assert rules.table_key({"name": "CUSTOMERS", "alias": "SHIP_TO"}) == "SHIP_TO"
    assert rules.table_key({"name": "ORDERS"}) == "ORDERS"
    assert rules.table_key({}) == ""


def test_table_role_resolves_an_aliased_table():
    m = _aliased_model()["model"]
    cols, mts = m["columns"], m["model_tables"]
    assert rules.table_role(cols, rules.table_key(mts[1])) == "dimension"
    # Keying on the physical name is what made it invisible.
    assert rules.table_role(cols, mts[1]["name"]) == "unknown"


# ── D10 must not call a populated aliased table a zero-column leaf ─────────

def test_d10_does_not_call_an_aliased_table_a_zero_column_leaf():
    findings = check_d10(make_context(models=[_aliased_model()]))
    leaf = [f for f in findings if "leaf" in f.detail.lower() and "SHIP_TO" in f.detail]
    assert leaf == [], f"SHIP_TO has three columns: {[f.detail for f in findings]}"


def test_d6_sees_the_columns_of_an_aliased_table():
    """Not asserting a finding — asserting the table is no longer 'unknown'."""
    m = _aliased_model()["model"]
    assert rules.table_role(m["columns"], "SHIP_TO") != "unknown"
    check_d6(make_context(models=[_aliased_model()]))  # must not raise


# ── a join finding must identify its join ──────────────────────────────────

def test_join_label_names_both_sides():
    mt = {"name": "ORDERS"}
    assert rules.join_label(mt, {"with": "CUSTOMERS"}) == "ORDERS -> CUSTOMERS"


def test_join_label_prefers_a_declared_name_when_one_exists():
    mt = {"name": "ORDERS"}
    assert rules.join_label(mt, {"name": "orders_to_cust", "with": "CUSTOMERS"}) == "orders_to_cust"


def test_join_label_uses_the_alias_side():
    mt = {"name": "CUSTOMERS", "alias": "SHIP_TO"}
    assert rules.join_label(mt, {"with": "ORDERS"}) == "SHIP_TO -> ORDERS"


def test_a_join_finding_is_not_anonymous():
    """D3 flags an OUTER join; the report must say which one."""
    model = {"guid": "m-1", "model": {"name": "S", "columns": [], "model_tables": [
        {"name": "ORDERS", "joins": [{"with": "RETURNS", "type": "OUTER"}]}]}}
    from ts_cli.audit.checks_data import check_d3
    findings = check_d3(make_context(models=[model]))
    assert findings
    assert all(f.object_name for f in findings), "a join finding must name its join"
    assert "ORDERS" in findings[0].object_name and "RETURNS" in findings[0].object_name


# ── S2 must find the RLS on an aliased table ───────────────────────────────

def test_s2_sees_table_rls_through_an_alias():
    """A role-playing dimension with RLS must not be reported as unprotected."""
    from ts_cli.audit.checks_security import check_s2
    tbl = {"guid": "t-1", "table": {"name": "CUSTOMERS", "columns": [],
                                    "rls_rules": {"rules": [{"expr": "x = ts_groups"}]}}}
    model = {"guid": "m-1", "model": {"name": "S", "columns": [
        {"name": "customer_email", "column_id": "SHIP_TO::customer_email"}],
        "model_tables": [{"name": "CUSTOMERS", "alias": "SHIP_TO", "fqn": "t-1"}]}}
    findings = check_s2(make_context(models=[model], tables={"t-1": tbl}))
    assert len(findings) == 1
    assert findings[0].severity == "INFO", "RLS is present — this is not a HIGH"


def test_s2_still_reports_a_table_with_no_rls():
    from ts_cli.audit.checks_security import check_s2
    tbl = {"guid": "t-1", "table": {"name": "CUSTOMERS", "columns": []}}
    model = {"guid": "m-1", "model": {"name": "S", "columns": [
        {"name": "customer_email", "column_id": "SHIP_TO::customer_email"}],
        "model_tables": [{"name": "CUSTOMERS", "alias": "SHIP_TO", "fqn": "t-1"}]}}
    findings = check_s2(make_context(models=[model], tables={"t-1": tbl}))
    assert len(findings) == 1 and findings[0].severity == "HIGH"
