"""The contexts these tests run are named builders in audit_rule_fixtures (security.py),
so the S catalog rules' equivalence test runs over exactly these inputs."""
import audit_rule_fixtures as fx
from ts_cli.audit.checks_security import (
    check_s1, check_s2, check_s3, check_s4, check_s5,
    check_s8, check_s9, check_s10, ALL_CHECKS,
)


def test_s1_flags_email():
    findings = check_s1(fx.sec_model_email_column())
    assert any(f.check_id == "S1" and "email" in f.detail.lower() for f in findings)


def test_s1_passes_non_pii():
    assert check_s1(fx.sec_model_without_pii()) == []


def test_s5_flags_password_column():
    findings = check_s5(fx.sec_password_column())
    assert any(f.check_id == "S5" and f.severity == "CRITICAL" for f in findings)


def test_s5_passes_no_credentials():
    assert check_s5(fx.sec_model_without_pii()) == []


def test_s4_flags_bypass_with_pii():
    findings = check_s4(fx.sec_bypass_with_pii())
    assert any(f.check_id == "S4" and f.severity == "HIGH" for f in findings)


def test_s10_flags_bypass():
    findings = check_s10(fx.sec_bypass_without_pii())
    assert any(f.check_id == "S10" for f in findings)


def test_s10_passes_no_bypass():
    assert check_s10(fx.sec_model_without_bypass()) == []


def test_all_checks_has_eight_entries():
    assert len(ALL_CHECKS) == 8
