from ts_cli.audit.checks_security import (
    check_s1, check_s2, check_s3, check_s4, check_s5,
    check_s8, check_s9, check_s10, ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, formulas=None, properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": [{"name": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def _col(name="Amount", column_id=None, index_type=None):
    c = {
        "name": name,
        "column_id": column_id or f"T1::{name}",
        "properties": {},
        "db_column_properties": {"data_type": "VARCHAR"},
    }
    if index_type:
        c["properties"]["index_type"] = index_type
    return c


def _table_tml(name="ORDERS", guid="t-1", rls_rules=None):
    t = {"guid": guid, "table": {"name": name, "columns": []}}
    if rls_rules:
        t["table"]["rls_rules"] = rls_rules
    return t


def test_s1_flags_email():
    cols = [_col("customer_email"), _col("Amount")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_s1(ctx)
    assert any(f.check_id == "S1" and "email" in f.detail.lower() for f in findings)


def test_s1_passes_non_pii():
    cols = [_col("Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_s1(ctx) == []


def test_s5_flags_password_column():
    cols = [_col("password"), _col("Amount")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_s5(ctx)
    assert any(f.check_id == "S5" and f.severity == "CRITICAL" for f in findings)


def test_s5_passes_no_credentials():
    cols = [_col("Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_s5(ctx) == []


def test_s4_flags_bypass_with_pii():
    cols = [_col("customer_email")]
    ctx = make_context(models=[_model(columns=cols, properties={"is_bypass_rls": True})])
    findings = check_s4(ctx)
    assert any(f.check_id == "S4" and f.severity == "HIGH" for f in findings)


def test_s10_flags_bypass():
    ctx = make_context(models=[_model(properties={"is_bypass_rls": True})])
    findings = check_s10(ctx)
    assert any(f.check_id == "S10" for f in findings)


def test_s10_passes_no_bypass():
    ctx = make_context(models=[_model(properties={})])
    assert check_s10(ctx) == []


def test_all_checks_has_eight_entries():
    assert len(ALL_CHECKS) == 8
