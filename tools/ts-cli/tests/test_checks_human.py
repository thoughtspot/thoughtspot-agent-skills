import audit_rule_fixtures as fx
from audit_run_rule import active_rule_ids, run_rule


# The H rules (rules/human.yaml), as the legacy H-check tests (checks_human.py, deleted
# in Task 12b) exercised them. The contexts are named builders in audit_rule_fixtures
# (human.py), whose legacy answers test_audit_pinned_findings.py pins.


def test_h1_flags_generic_names():
    findings = run_rule(fx.human_generic_names(), "H1")
    assert any(f.check_id == "H1" for f in findings)


def test_h1_passes_good_names():
    assert run_rule(fx.human_good_names(), "H1") == []


def test_h3_flags_hidden_not_referenced():
    findings = run_rule(fx.human_hidden_unreferenced(), "H3")
    assert any(f.check_id == "H3" and "Amount" in f.detail for f in findings)


def test_h3_passes_hidden_referenced_by_formula():
    assert run_rule(fx.human_hidden_referenced(), "H3") == []


def test_h4_flags_zero_dependents():
    findings = run_rule(fx.human_model_no_dependents(), "H4")
    assert any(f.check_id == "H4" for f in findings)


def test_h4_passes_with_dependents():
    assert run_rule(fx.human_model_with_dependents(), "H4") == []


def test_h10_flags_stale_column():
    findings = run_rule(fx.human_stale_column(), "H10")
    assert any(f.check_id == "H10" for f in findings)


def test_h10_passes_clean_names():
    assert run_rule(fx.human_clean_names(), "H10") == []


def test_all_checks_has_nine_entries():
    assert len(active_rule_ids("H")) == 9
