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
    # BL-171: the ThoughtSpot function is `unique count` — with a SPACE.
    # `unique_count(` is rejected with error_code 14516 (live-verified
    # 2026-07-30, se-thoughtspot). Only the *_if variants use an underscore.
    expr, status, _ = translate_dax("DISTINCTCOUNT('BU'[BU])")
    assert status == "Migrated"
    assert expr == "unique count([BU::BU])"


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


# ---------------------------------------------------------------------------
# BL-171 — DAX functions whose ThoughtSpot target does not exist
#
# `trim`, `upper`, `lower` (live-disproved 2026-06-13 / 2026-07-29, re-verified
# 2026-07-30 on se-thoughtspot) become sql_string_op pass-throughs; `hour`,
# `minute`, `second` and `unique_count` were also being emitted as bare names
# that the formula parser rejects with error_code 14516.
# ---------------------------------------------------------------------------

_DISPROVED = ("trim(", "upper(", "lower(", "hour(", "minute(", "second(",
              "unique_count(", "month(")


def _assert_clean(expr):
    for bad in _DISPROVED:
        assert bad not in expr, f"{expr!r} emits the non-existent {bad!r}"


def test_trim_pass_through():
    expr, status, _ = translate_dax("TRIM(Employee[Name])")
    assert status == "Migrated"
    assert expr == 'sql_string_op("TRIM({0})", [Employee::Name])'


def test_upper_pass_through():
    expr, status, _ = translate_dax("UPPER(Employee[Name])")
    assert status == "Migrated"
    assert expr == 'sql_string_op("UPPER({0})", [Employee::Name])'


def test_lower_pass_through():
    expr, status, _ = translate_dax("LOWER(Employee[Name])")
    assert status == "Migrated"
    assert expr == 'sql_string_op("LOWER({0})", [Employee::Name])'


def test_nested_upper_trim():
    expr, status, _ = translate_dax("UPPER(TRIM(Employee[Name]))")
    assert status == "Migrated"
    assert expr == ('sql_string_op("UPPER({0})", '
                    'sql_string_op("TRIM({0})", [Employee::Name]))')


def test_hour_maps_to_hour_of_day():
    expr, status, _ = translate_dax("HOUR(Employee[Start])")
    assert status == "Migrated"
    assert expr == "hour_of_day([Employee::Start])"


def test_month_maps_to_month_number():
    # DAX MONTH() returns 1-12; ThoughtSpot `month()` returns the month NAME —
    # `month_number()` is the numeric one.
    expr, status, _ = translate_dax("MONTH(Employee[Start])")
    assert status == "Migrated"
    assert expr == "month_number([Employee::Start])"


def test_minute_and_second_are_flagged_not_faked():
    # ThoughtSpot has no minute/second extractor at all (live-verified
    # 2026-07-30) and the warehouse dialect is unknown here, so flag rather
    # than emit a speculative pass-through.
    for dax in ("MINUTE(Employee[Start])", "SECOND(Employee[Start])"):
        expr, status, note = translate_dax(dax)
        assert expr is None, dax
        assert status == "NEEDS REVIEW"
        assert "unmapped" in note


def test_no_disproved_name_ever_emitted():
    for dax in ("TRIM(Employee[Name])", "UPPER(Employee[Name])",
                "LOWER(Employee[Name])", "UPPER(TRIM(Employee[Name]))",
                "DISTINCTCOUNT(Employee[Name])", "HOUR(Employee[Start])",
                "MONTH(Employee[Start])", "TRIM(Employee[a]) & 'x'"):
        expr, _status, _note = translate_dax(dax)
        if expr is not None:
            _assert_clean(expr)
