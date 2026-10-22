import audit_rule_fixtures as fx
from ts_cli.audit.checks_data import (
    check_d1, check_d2, check_d3, check_d4, check_d5, check_d6,
    check_d7, check_d8, check_d9, check_d10, check_d11, check_d12,
    ALL_CHECKS,
)

# The contexts are named builders in audit_rule_fixtures (data.py), so the D catalog
# rules' equivalence test runs over exactly these inputs.


def test_d1_flags_excess_tables():
    findings = check_d1(fx.data_model_sixteen_tables())
    assert any(f.check_id == "D1" and f.severity == "HIGH" and "table" in f.detail.lower()
               for f in findings)


def test_d1_passes_small_model():
    findings = check_d1(fx.data_model_small())
    assert not any("table" in f.detail.lower() for f in findings)


def test_d4_flags_non_progressive():
    findings = check_d4(fx.data_model_six_tables_not_progressive())
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_d4_passes_progressive():
    assert check_d4(fx.data_model_six_tables_progressive()) == []


def test_d4_passes_small_model():
    assert check_d4(fx.data_model_three_tables_not_progressive()) == []


def test_d5_flags_unjoined_table():
    findings = check_d5(fx.data_model_unjoined_table())
    assert any(f.check_id == "D5" and "T3" in f.detail for f in findings)


def test_d5_passes_all_joined():
    assert check_d5(fx.data_model_all_joined()) == []


def test_d7_flags_identical_table_sets():
    findings = check_d7(fx.data_models_identical_tables())
    assert any(f.check_id == "D7" and f.severity == "HIGH" for f in findings)


def test_d7_passes_disjoint_models():
    assert check_d7(fx.data_models_disjoint_tables()) == []


def test_d9_flags_high_sql_ratio():
    findings = check_d9(fx.data_model_half_sql_passthrough())
    assert any(f.check_id == "D9" for f in findings)


def test_all_checks_has_twelve_entries():
    assert len(ALL_CHECKS) == 12
