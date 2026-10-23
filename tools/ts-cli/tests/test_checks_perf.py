"""The P rules (rules/perf.yaml), as the legacy P-check tests (checks_perf.py, deleted when
the rule catalog replaced them) exercised them. Their inputs are named builders in audit_rule_fixtures
(perf.py), whose legacy answers test_audit_pinned_findings.py pins."""
import audit_rule_fixtures as fx
from audit_run_rule import run_rule


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


def test_p8_general_lines_are_500_and_1500():
    """Above 500 columns Search Data gets awkward; above 1,500 performance suffers
    (field experience; 0.57% / 0.06% of production Models, 2026-10 call-home data)."""
    sev = lambda n: [f.severity for f in run_rule(fx.perf_model_columns(n), "P8", "general")]
    assert sev(80) == [] and sev(500) == []
    assert sev(501) == ["MEDIUM"] and sev(1500) == ["MEDIUM"]
    assert sev(1501) == ["HIGH"]


def test_p8_spotter_lines_are_250_and_500():
    sev = lambda n: [f.severity for f in run_rule(fx.perf_model_columns(n), "P8", "spotter")]
    assert sev(250) == []
    assert sev(251) == ["MEDIUM"] and sev(500) == ["MEDIUM"]
    assert sev(501) == ["HIGH"]


def test_p8_wording_names_search_and_performance_not_group_by():
    detail = run_rule(fx.perf_model_1600_columns(), "P8")[0].detail
    assert "GROUP BY" not in detail and "1600 columns" in detail


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
