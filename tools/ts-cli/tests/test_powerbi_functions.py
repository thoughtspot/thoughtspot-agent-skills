"""Unit tests for ts_cli.powerbi.functions — DAX -> ThoughtSpot translation.

Pure functions, no live cluster (per .claude/rules/ts-cli.md). Covers the safe subset
plus the cluster-verified extensions (sum_if, group_aggregate, [formula_<name>] id-refs,
ROUND-increment, 2-arg CEILING, diff_days) and the NEEDS-REVIEW gate.
"""
from ts_cli.powerbi.functions import translate_dax


def test_simple_sum():
    expr, status, _ = translate_dax("SUM(Employee[Amount])")
    assert status == "Migrated"
    assert expr == "sum([Employee::Amount])"


def test_distinctcount_maps_to_unique_count():
    expr, status, _ = translate_dax("DISTINCTCOUNT('BU'[BU])")
    assert status == "Migrated"
    assert expr == "unique_count([BU::BU])"


def test_divide_to_safe_divide():
    expr, status, _ = translate_dax("DIVIDE(Employee[a], Employee[b])")
    assert status == "Migrated"
    assert expr == "safe_divide([Employee::a], [Employee::b])"


def test_if_expansion():
    expr, status, _ = translate_dax("IF(Employee[x] > 0, 1, 0)")
    assert status == "Migrated"
    assert "if (" in expr and "then 1 else 0" in expr


def test_measure_ref_becomes_formula_id():
    # SUM of a calc column referenced by name -> [formula_<name>] id-reference
    expr, status, _ = translate_dax("SUM([isNewHire])", measure_dax={"isNewHire": "x"})
    assert status == "Migrated"
    assert expr == "sum([formula_isNewHire])"


def test_calculate_filter_approximated_to_sum_if():
    expr, status, note = translate_dax(
        "CALCULATE(SUM(Employee[x]), FILTER(Employee, Employee[y] > 0))")
    assert status == "Approximated"
    assert expr.startswith("sum_if(")
    assert "sum_if" in note


def test_calculate_all_to_group_aggregate():
    expr, status, _ = translate_dax(
        "CALCULATE([TO %], ALL(Gender[Gender]))", measure_dax={"TO %": "x"})
    assert status == "Approximated"
    assert expr.startswith("group_aggregate([formula_TO %]")
    assert "query_groups() - {" in expr and "query_filters() - {" in expr


def test_sameperiodlastyear_needs_review():
    expr, status, note = translate_dax(
        "CALCULATE([Sales], SAMEPERIODLASTYEAR('Date'[Date]))", measure_dax={"Sales": "x"})
    assert expr is None
    assert status == "NEEDS REVIEW"
    assert "sameperiodlastyear" in note


def test_round_increment_semantics():
    # DAX ROUND(x, 2) = 2 decimal places -> TS round(x, 0.01) (increment)
    expr, status, _ = translate_dax("ROUND(Employee[x], 2)")
    assert status == "Migrated"
    assert expr == "round([Employee::x], 0.01)"


def test_ceiling_with_significance():
    expr, status, _ = translate_dax("CEILING(Employee[x], 5)")
    assert status == "Migrated"
    assert expr == "(ceil(([Employee::x])/(5))*(5))"


def test_date_subtraction_to_diff_days():
    expr, status, _ = translate_dax(
        "Employee[End] - Employee[Start]",
        date_cols={"Employee::End", "Employee::Start"})
    assert status == "Migrated"
    assert expr == "diff_days([Employee::End], [Employee::Start])"


def test_unknown_function_needs_review():
    expr, status, note = translate_dax("FOOBAR(Employee[x])")
    assert expr is None
    assert status == "NEEDS REVIEW"
    assert "FOOBAR" in note
