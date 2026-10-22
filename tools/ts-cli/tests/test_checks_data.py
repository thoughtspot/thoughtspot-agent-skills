import audit_rule_fixtures as fx
from audit_run_rule import active_rule_ids, run_rule

# The D rules (rules/data.yaml), as the legacy D-check tests (checks_data.py, deleted in
# Task 12b) exercised them. The contexts are named builders in audit_rule_fixtures
# (data.py), whose legacy answers test_audit_pinned_findings.py pins.


def test_d1_flags_excess_tables():
    findings = run_rule(fx.data_model_sixteen_tables(), "D1")
    assert any(f.check_id == "D1" and f.severity == "HIGH" and "table" in f.detail.lower()
               for f in findings)


def test_d1_passes_small_model():
    findings = run_rule(fx.data_model_small(), "D1")
    assert not any("table" in f.detail.lower() for f in findings)


def test_d4_flags_non_progressive():
    findings = run_rule(fx.data_model_six_tables_not_progressive(), "D4")
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_d4_passes_progressive():
    assert run_rule(fx.data_model_six_tables_progressive(), "D4") == []


def test_d4_passes_small_model():
    assert run_rule(fx.data_model_three_tables_not_progressive(), "D4") == []


def test_d5_flags_unjoined_table():
    findings = run_rule(fx.data_model_unjoined_table(), "D5")
    assert any(f.check_id == "D5" and "T3" in f.detail for f in findings)


def test_d5_passes_all_joined():
    assert run_rule(fx.data_model_all_joined(), "D5") == []


def test_d7_flags_identical_table_sets():
    findings = run_rule(fx.data_models_identical_tables(), "D7")
    assert any(f.check_id == "D7" and f.severity == "HIGH" for f in findings)


def test_d7_passes_disjoint_models():
    assert run_rule(fx.data_models_disjoint_tables(), "D7") == []


def test_d9_flags_high_sql_ratio():
    findings = run_rule(fx.data_model_half_sql_passthrough(), "D9")
    assert any(f.check_id == "D9" for f in findings)


def test_all_checks_has_twelve_entries():
    assert len(active_rule_ids("D")) == 12
