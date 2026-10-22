"""The S rules (rules/security.yaml), as the legacy S-check tests (checks_security.py,
deleted when the rule catalog replaced them) exercised them. The contexts are named builders in
audit_rule_fixtures (security.py), whose legacy answers test_audit_pinned_findings.py
pins."""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule
from ts_cli.audit.context import make_context


def test_s1_flags_email():
    findings = run_rule(fx.sec_model_email_column(), "S1")
    assert any(f.check_id == "S1" and "email" in f.detail.lower() for f in findings)


def test_s1_passes_non_pii():
    assert run_rule(fx.sec_model_without_pii(), "S1") == []


def test_s5_flags_password_column():
    findings = run_rule(fx.sec_password_column(), "S5")
    assert any(f.check_id == "S5" and f.severity == "CRITICAL" for f in findings)


def test_s5_token_is_high():
    """S5's one non-CRITICAL branch: a column named for a `token` (a whole word, any
    case) is HIGH, beside a password column that stays CRITICAL."""
    ctx = make_context(models=[fx.build_sec_model(columns=[
        fx.build_sec_col("Access Token"), fx.build_sec_col("password"),
        fx.build_sec_col("token_id")])])   # `token_id` is not the whole word
    by_name = {f.object_name: f.severity for f in run_rule(ctx, "S5")}
    assert by_name == {"Access Token": "HIGH", "password": "CRITICAL"}


def test_s5_passes_no_credentials():
    assert run_rule(fx.sec_model_without_pii(), "S5") == []


def test_s4_flags_bypass_with_pii():
    findings = run_rule(fx.sec_bypass_with_pii(), "S4")
    assert any(f.check_id == "S4" and f.severity == "HIGH" for f in findings)


def test_s10_flags_bypass():
    findings = run_rule(fx.sec_bypass_without_pii(), "S10")
    assert any(f.check_id == "S10" for f in findings)


def test_s10_passes_no_bypass():
    assert run_rule(fx.sec_model_without_bypass(), "S10") == []
