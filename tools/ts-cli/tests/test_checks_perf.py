"""The legacy P-checks (checks_perf.py). Their inputs are named builders in
audit_rule_fixtures.py, so the P catalog rules' equivalence test runs over exactly
these contexts."""
import audit_rule_fixtures as fx
from ts_cli.audit.checks_perf import (
    check_p1, check_p4, check_p8, check_p13, check_p16, check_p18, ALL_CHECKS,
)


def test_p1_flags_sql_view():
    findings = check_p1(fx.perf_metadata_sql_view())
    assert len(findings) == 1
    assert findings[0].check_id == "P1"


def test_p1_passes_no_views():
    assert check_p1(fx.perf_metadata_logical_only()) == []


def test_p4_flags_non_progressive():
    findings = check_p4(fx.perf_model_wide_not_progressive())
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_p8_flags_excess_columns():
    findings = check_p8(fx.perf_model_80_columns())
    assert any(f.check_id == "P8" for f in findings)


def test_p8_passes_under_threshold():
    assert check_p8(fx.perf_model_50_columns()) == []


def test_p13_flags_high_rls_count():
    findings = check_p13(fx.perf_table_seven_rls_rules())
    assert any(f.check_id == "P13" and f.severity == "HIGH" for f in findings)


def test_p16_flags_deep_nesting():
    findings = check_p16(fx.perf_formula_six_nested_ifs())
    assert any(f.check_id == "P16" for f in findings)


def test_p18_flags_count_distinct():
    findings = check_p18(fx.perf_column_count_distinct())
    assert any(f.check_id == "P18" for f in findings)


def test_all_checks_has_sixteen_entries():
    assert len(ALL_CHECKS) == 16
