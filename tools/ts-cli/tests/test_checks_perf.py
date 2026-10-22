"""The P rules (rules/perf.yaml), as the legacy P-check tests (checks_perf.py, deleted in
Task 12b) exercised them. Their inputs are named builders in audit_rule_fixtures
(perf.py), whose legacy answers test_audit_pinned_findings.py pins."""
import audit_rule_fixtures as fx
from audit_run_rule import active_rule_ids, run_rule


def test_p1_flags_sql_view():
    findings = run_rule(fx.perf_metadata_sql_view(), "P1")
    assert len(findings) == 1
    assert findings[0].check_id == "P1"


def test_p1_passes_no_views():
    assert run_rule(fx.perf_metadata_logical_only(), "P1") == []


def test_p4_flags_non_progressive():
    findings = run_rule(fx.perf_model_wide_not_progressive(), "P4")
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_p8_flags_excess_columns():
    findings = run_rule(fx.perf_model_80_columns(), "P8")
    assert any(f.check_id == "P8" for f in findings)


def test_p8_passes_under_threshold():
    assert run_rule(fx.perf_model_50_columns(), "P8") == []


def test_p13_flags_high_rls_count():
    findings = run_rule(fx.perf_table_seven_rls_rules(), "P13")
    assert any(f.check_id == "P13" and f.severity == "HIGH" for f in findings)


def test_p16_flags_deep_nesting():
    findings = run_rule(fx.perf_formula_six_nested_ifs(), "P16")
    assert any(f.check_id == "P16" for f in findings)


def test_p18_flags_count_distinct():
    findings = run_rule(fx.perf_column_count_distinct(), "P18")
    assert any(f.check_id == "P18" for f in findings)


def test_all_checks_has_sixteen_entries():
    assert len(active_rule_ids("P")) == 16
