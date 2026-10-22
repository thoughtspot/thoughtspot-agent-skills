import audit_rule_fixtures as fx
from ts_cli.audit.checks_human import (
    check_h1, check_h2, check_h3, check_h4, check_h5, check_h6,
    check_h7, check_h8, check_h9, check_h10, ALL_CHECKS,
)


# The contexts are named builders in audit_rule_fixtures (human.py), so the H catalog
# rules' equivalence test runs over exactly these inputs.


def test_h1_flags_generic_names():
    findings = check_h1(fx.human_generic_names())
    assert any(f.check_id == "H1" for f in findings)


def test_h1_passes_good_names():
    assert check_h1(fx.human_good_names()) == []


def test_h3_flags_hidden_not_referenced():
    findings = check_h3(fx.human_hidden_unreferenced())
    assert any(f.check_id == "H3" and "Amount" in f.detail for f in findings)


def test_h3_passes_hidden_referenced_by_formula():
    assert check_h3(fx.human_hidden_referenced()) == []


def test_h4_flags_zero_dependents():
    findings = check_h4(fx.human_model_no_dependents())
    assert any(f.check_id == "H4" for f in findings)


def test_h4_passes_with_dependents():
    assert check_h4(fx.human_model_with_dependents()) == []


def test_h10_flags_stale_column():
    findings = check_h10(fx.human_stale_column())
    assert any(f.check_id == "H10" for f in findings)


def test_h10_passes_clean_names():
    assert check_h10(fx.human_clean_names()) == []


def test_all_checks_has_nine_entries():
    assert len(ALL_CHECKS) == 9
