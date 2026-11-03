"""New audit rules, set 2 (audit v2 roadmap PR 4.4): S12, S13, D13, D17, D18, H13, H14, A9."""
from __future__ import annotations

from audit_rule_fixtures.rls import build_rls_expr
from audit_run_rule import run_rule
from ts_cli.audit.context import make_context


def _sev(ctx, rid):
    return sorted(f.severity for f in run_rule(ctx, rid))


# ── S12: RLS table on the optional side of an outer join ────────────────────

def _rls_table(name, rules):
    return {"table": {"name": name, "columns": [{"name": "K"}, {"name": "REGION"}],
                      "rls_rules": {"tables": [{"name": name}],
                                    "table_paths": [{"id": f"{name}_1", "table": name,
                                                     "column": ["REGION"]}],
                                    "rules": rules} if rules else None}}


_NO_NULL = [{"name": "Region", "expr": "[CUST_1::REGION] = ts_groups"}]
_WITH_NULL = [{"name": "Region",
               "expr": "isnull ( [CUST_1::REGION] ) or [CUST_1::REGION] = ts_groups"}]


def _outer_ctx(join_type, cust_rules=None, orders_rules=None, cust_tml=True):
    tables = {"t-o": _rls_table("ORDERS", orders_rules)}
    if cust_tml:
        tables["t-c"] = _rls_table("CUST", cust_rules)
    model = {"guid": "m-1", "model": {"name": "Sales", "columns": [], "model_tables": [
        {"name": "ORDERS", "fqn": "t-o", "joins": [
            {"name": "j", "with": "CUST", "on": "[ORDERS::K] = [CUST::K]",
             "type": join_type, "cardinality": "MANY_TO_ONE"}]},
        {"name": "CUST", "fqn": "t-c"}]}}
    return make_context(models=[model], tables=tables)


def test_s12_optional_side():
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_WITH_NULL), "S12") == []
    assert _sev(_outer_ctx("RIGHT_OUTER", cust_rules=_NO_NULL), "S12") == []
    assert _sev(_outer_ctx("RIGHT_OUTER", orders_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("OUTER", orders_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("OUTER", cust_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("INNER", cust_rules=_NO_NULL), "S12") == []
    assert _sev(_outer_ctx("LEFT_OUTER", cust_tml=False), "S12") == []


def test_s12_names_the_table():
    (f,) = run_rule(_outer_ctx("LEFT_OUTER", cust_rules=_NO_NULL), "S12")
    assert "CUST" in f.detail


# ── S13: RLS rule search cannot index ───────────────────────────────────────

def test_s13():
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_groups"), "S13") == []
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_groups_int"), "S13") == []
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_username"), "S13") == []
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_org"), "S13") == ["LOW"]
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] != ts_groups"), "S13") == ["LOW"]
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] <> ts_groups"), "S13") == ["LOW"]
