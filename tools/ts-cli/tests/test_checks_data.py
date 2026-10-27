import audit_rule_fixtures as fx
from audit_run_rule import run_rule

# The D rules (rules/data.yaml), as the legacy D-check tests (checks_data.py, deleted when
# the rule catalog replaced them) exercised them. The contexts are named builders in audit_rule_fixtures
# (data.py), whose legacy answers test_audit_pinned_findings.py pins.


def test_d1_table_lines_are_30_and_50():
    """Production estates (2026-10 call-home data: p99 35 tables, 0.18% above 40)."""
    assert run_rule(fx.data_model_tables(30), "D1") == []
    assert [f.severity for f in run_rule(fx.data_model_tables(31), "D1")] == ["MEDIUM"]
    assert [f.severity for f in run_rule(fx.data_model_fifty_one_tables(), "D1")] == ["HIGH"]
    assert run_rule(fx.data_model_sixteen_tables(), "D1") == []


def test_d1_keeps_none_names_and_sets_each_measures_threshold():
    from ts_cli.audit.context import make_context
    model = fx.build_data_model(name=None, guid=None, model_tables=fx.build_data_tables(51))
    [f] = run_rule(make_context(models=[model]), "D1")
    assert (f.object_name, f.object_guid) == (None, None)
    assert f.threshold == {"green": 30, "yellow": 50} and f.metric == 51


def test_d1_no_longer_grades_columns_or_join_depth():
    assert run_rule(fx.data_model_wide_and_deep(), "D1") == []


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
