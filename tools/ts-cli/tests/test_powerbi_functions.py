"""Unit tests for ts_cli.powerbi.functions — DAX -> ThoughtSpot translation.

Pure functions, no live cluster (per .claude/rules/ts-cli.md). Covers the safe subset
plus the cluster-verified extensions (sum_if, group_aggregate, [formula_<name>] id-refs,
ROUND-increment, 2-arg CEILING, diff_days) and the NEEDS-REVIEW gate.
"""
import pytest

from ts_cli.powerbi.functions import translate_dax


def test_simple_sum():
    expr, status, _ = translate_dax("SUM(Employee[Amount])")
    assert status == "Migrated"
    assert expr == "sum([Employee::Amount])"


def test_distinctcount_maps_to_unique_count():
    # BL-171: the ThoughtSpot function is `unique count` — with a SPACE.
    # `unique_count(` is rejected with error_code 14516 (live-verified
    # 2026-07-30, se-thoughtspot). Only the *_if variants use an underscore.
    # BL-540: DISTINCTCOUNT also counts BLANK, so it carries a has-blank term; the
    # plain `unique count` is DISTINCTCOUNTNOBLANK (tests below).
    expr, status, _ = translate_dax("DISTINCTCOUNT('BU'[BU])")
    assert status == "Approximated"
    assert expr.startswith("(unique count([BU::BU]) + ")
    assert "unique_count" not in expr


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


def test_marker_inside_a_string_literal_is_data_not_a_call():
    """A DAX string literal containing `trim(` is text, not a call. Rewriting it
    corrupted the formula into nested quotes and still reported Migrated — a
    silent wrong answer, which is the one outcome the pass-through mechanism
    exists to avoid."""
    expr, status, _ = translate_dax('CONCATENATE(Employee[Name], "trim(x)")')
    assert status == "Migrated"
    assert expr == "concat([Employee::Name], 'trim(x)')"


def test_trim_of_a_literal_containing_a_marker():
    expr, status, _ = translate_dax('TRIM("upper(x)")')
    assert status == "Migrated"
    assert expr == 'sql_string_op("TRIM({0})", \'upper(x)\')'


def test_no_disproved_name_ever_emitted():
    for dax in ("TRIM(Employee[Name])", "UPPER(Employee[Name])",
                "LOWER(Employee[Name])", "UPPER(TRIM(Employee[Name]))",
                "DISTINCTCOUNT(Employee[Name])", "HOUR(Employee[Start])",
                "MONTH(Employee[Start])", "TRIM(Employee[a]) & 'x'"):
        expr, _status, _note = translate_dax(dax)
        if expr is not None:
            _assert_clean(expr)


# BL-369: DAX escapes an apostrophe in a quoted table name by doubling it.
def test_quoted_table_name_with_doubled_apostrophe():
    expr, status, _ = translate_dax("SUM('Bob''s Sales'[x])")
    assert expr == "sum([Bob's Sales::x])"
    assert status == "Migrated"


def test_doubled_apostrophe_table_beside_a_plain_one():
    expr, _, _ = translate_dax("SUM('Sales'[x]) + SUM('Bob''s Sales'[y])")
    assert expr == "sum([Sales::x]) + sum([Bob's Sales::y])"


def test_doubled_apostrophe_table_qualifying_a_measure_ref():
    expr, _, _ = translate_dax("'Bob''s Sales'[M] * 2", measure_dax={"M": "SUM(T[x])"})
    assert expr == "[formula_M] * 2"


def test_long_apostrophe_run_is_linear():
    """#583 review: a regex quoted-name branch was quadratic on a run of apostrophes.
    Generous bound: a quadratic scan of 20k characters takes far longer than this."""
    import time
    from ts_cli.powerbi.functions import dax_col_refs
    for src in ("SUM(" + "'" * 20001 + "[x])", "SUM(" + "'" * 20000 + ")"):
        t0 = time.monotonic()
        dax_col_refs(src)
        translate_dax(src)
        assert time.monotonic() - t0 < 5


def test_dax_col_refs_shapes():
    from ts_cli.powerbi.functions import dax_col_refs
    refs = [(t, c) for _s, _e, t, c in dax_col_refs(
        "SUM(T[x]) + 'A B'[y] + 'Bob''s'[z] + [m] + IF(1, \"T[no]\", 0)")]
    assert refs == [("T", "x"), ("A B", "y"), ("Bob's", "z")]


def test_string_literal_apostrophe_does_not_steal_a_table():
    expr, _, _ = translate_dax("IF(x, \"it's\", 'T'[c])")
    assert expr.endswith("else [T::c])")


# BL-375: DAX keywords are never table names.
def test_not_before_a_measure_keeps_the_not():
    expr, _, _ = translate_dax("NOT [Flag]", measure_dax={"Flag": "MAX(T[f])"})
    assert expr == "not [formula_Flag]"


def test_and_not_before_a_measure():
    expr, _, _ = translate_dax("x && NOT [Flag]", measure_dax={"Flag": "MAX(T[f])"})
    assert expr == "x and not [formula_Flag]"


def test_var_return_stays_needs_review():
    expr, status, _ = translate_dax("VAR a = 1 RETURN [M]", measure_dax={"M": "SUM(T[x])"})
    assert expr is None and status == "NEEDS REVIEW"


def test_keywords_are_not_table_refs():
    from ts_cli.powerbi.functions import dax_col_refs
    assert [(t, c) for _s, _e, t, c in dax_col_refs("NOT [c] && TRUE [d] || T[e]")] == [("T", "e")]


# --- BL-540: DAX DISTINCTCOUNT counts BLANK as a value; unique count does not ------
# Live probe 2026-11-08 (keys a,a,b,NULL,NULL,c): `unique count` compiled to
# count(DISTINCT k) = 3, DAX DISTINCTCOUNT = 4. The exact form below returned 4, and 1
# for a group holding only the blank key.

def test_distinctcount_counts_blank_as_one_value():
    expr, status, note = translate_dax("DISTINCTCOUNT('BU'[BU])")
    assert expr == ("(unique count([BU::BU]) + max((if (isnull([BU::BU])) then 1 else 0)))")
    # Approximated, not exact: a dimension row with no matching facts is BLANK in DAX
    # and 1 here, and the form is unprobed inside group_aggregate (review, BL-540).
    assert status == "Approximated", note
    assert "no matching" in note and "group_aggregate" in note


def test_distinctcountnoblank_is_plain_unique_count():
    expr, status, _ = translate_dax("DISTINCTCOUNTNOBLANK('BU'[BU])")
    assert status == "Migrated"
    assert expr == "unique count([BU::BU])"


def test_distinctcount_inside_divide():
    expr, status, _ = translate_dax("DIVIDE(SUM(Sales[Amount]), DISTINCTCOUNT(Sales[Customer]))")
    assert status == "Approximated"
    assert "unique count([Sales::Customer])" in expr and "isnull([Sales::Customer])" in expr


def test_split_args_tracks_braces():
    """DAX writes a value set as `T[Status] IN {"a","b"}`. Without brace tracking the
    commas inside the set split it into arguments that are not arguments, so every
    CALCULATE carrying an IN-set was read wrongly."""
    from ts_cli.powerbi.functions import _split_args
    assert _split_args('DISTINCTCOUNT(T[k]), T[Status] IN {"x","y"}') == [
        "DISTINCTCOUNT(T[k])", 'T[Status] IN {"x","y"}']


# --- Round-4 review of the gated-measures PR: _split_args reaches every DAX path -------

@pytest.mark.parametrize("dax,expected", [
    # main gave this; brace tracking without string skipping mis-split it into
    # "then '{', 'b' else 0", labelled Migrated
    ('IF(T[c] = 1, "{", "b")', "(if ([T::c] = 1) then '{' else 'b')"),
    ('IF(T[c] = 1, "}", "b")', "(if ([T::c] = 1) then '}' else 'b')"),
    ('IF(T[s] = "a,b", 1, 0)', "(if ([T::s] = 'a,b') then 1 else 0)"),
    ('IF(T[s] = "a)b", 1, 0)', "(if ([T::s] = 'a)b') then 1 else 0)"),
])
def test_quoted_text_is_not_argument_structure(dax, expected):
    expr, status, _ = translate_dax(dax)
    assert (expr, status) == (expected, "Migrated")


def test_split_args_skips_strings_quoted_names_and_brackets():
    from ts_cli.powerbi.functions import _split_args
    assert _split_args('T[c] = 1, "{", "b"') == ["T[c] = 1", '"{"', '"b"']
    assert _split_args('"a,b", \'Bob\'\'s, (x)\'[c], T[a,b]') == [
        '"a,b"', "'Bob''s, (x)'[c]", "T[a,b]"]
    assert _split_args('"say ""a,b"""') == ['"say ""a,b"""']


def test_in_set_inside_if_translates():
    """An IN-set inside a call was NEEDS REVIEW before _split_args tracked braces (its
    commas split the call). It now translates; `in { }` is ThoughtSpot syntax."""
    expr, status, _ = translate_dax('IF(T[s] IN {"a","b"}, 1, 0)')
    assert (expr, status) == ("(if ([T::s] IN {'a','b'}) then 1 else 0)", "Migrated")


# --- Round-5 review: the splitter must not open new inputs to _calc_approx ---------

_CALC_SHAPES = {
    "ratio": "CALCULATE(SUM(Sales[Profit]) / SUM(Sales[Revenue]), {f})",
    "times 100": "CALCULATE(SUM(Sales[Profit]) * 100, {f})",
    "countrows distinct": "CALCULATE(COUNTROWS(DISTINCT(Sales[Cust])), {f})",
    "count": "CALCULATE(COUNT(Sales[Cust]), {f})",
    "filter all": "CALCULATE(SUM(Sales[Profit]), FILTER(ALL(Sales), {f}))",
}
_NEW_FILTERS = {
    "in set": 'Sales[Region] IN {"East","West"}',
    "comma in string": 'Sales[Region] = "East,West"',
    "paren in string": 'Sales[Region] = "East)"',
}


@pytest.mark.parametrize("shape", sorted(_CALC_SHAPES))
@pytest.mark.parametrize("filt", sorted(_NEW_FILTERS))
def test_calculate_the_quote_aware_split_newly_reads_stays_needs_review(shape, filt):
    """_calc_approx keeps only the first aggregate's argument (a ratio became its
    numerator, `* 100` vanished, ALL was dropped). Before the quote-aware splitter these
    inputs failed to split and were NEEDS REVIEW; they still are (BL-590)."""
    expr, status, _ = translate_dax(_CALC_SHAPES[shape].format(f=_NEW_FILTERS[filt]))
    assert (expr, status) == (None, "NEEDS REVIEW")


@pytest.mark.xfail(strict=True, reason="BL-590: _calc_approx drops parts of the expression "
                   "on an `=` filter, as on main; flips to a pass when BL-590 lands")
@pytest.mark.parametrize("shape", sorted(_CALC_SHAPES))
def test_calculate_with_an_equals_filter_should_need_review(shape):
    expr, status, _ = translate_dax(_CALC_SHAPES[shape].format(f='Sales[Region] = "East"'))
    assert (expr, status) == (None, "NEEDS REVIEW")


def test_in_set_inside_calculate_sum_needs_review():
    expr, status, _ = translate_dax('CALCULATE(SUM(T[x]), T[s] IN {"a","b"})')
    assert (expr, status) == (None, "NEEDS REVIEW")


def test_plain_equals_calculate_still_approximates_as_on_main():
    expr, status, _ = translate_dax('CALCULATE(SUM(T[x]), T[s] = "a")')
    assert (expr, status) == ("sum_if([T::s] = 'a', [T::x])", "Approximated")


@pytest.mark.parametrize("dax", [
    'IF(NOT Fact[s] IN {"a","b"}, 1, 0)',
    'IF(NOT(Fact[s] IN {"a"}), 1, 0)',
    'NOT(T[s] IN {"a"})',
    'IF(NOT [s] IN {"a"}, 1, 0)',
    "IF(NOT 'My T'[s] IN {\"a\"}, 1, 0)",
    'IF(not Fact[s] in {"a"}, 1, 0)',
])
def test_not_before_an_in_set_needs_review(dax):
    """A blank s is not in the set: TRUE in DAX, but ThoughtSpot's not ( NULL in {…} )
    is NULL and falls to else. Inferred, not probed (BL-591). The gated parser refuses
    the same shape."""
    expr, status, note = translate_dax(dax)
    assert (expr, status) == (None, "NEEDS REVIEW")
    assert "BL-591" in note


@pytest.mark.parametrize("dax", [
    'IF(Fact[s] IN {"a", 1.50}, 1, 0)', 'IF(Fact[s] IN {"a", 1.0}, 1, 0)',
    'IF(Fact[s] IN {"a", 01}, 1, 0)', 'IF(Fact[s] IN {"a", 1}, 1, 0)',
    'T[s] IN {2.5, "a"}', 'IF(Fact[s] IN {"a", 99999999999999999999}, 1, 0)',
    'IF(Fact[s] IN {"a", TRUE}, 1, 0)', 'IF(Fact[s] IN {"a", BLANK()}, 1, 0)',
    'IF(Fact[s] IN {"a", Fact[t]}, 1, 0)',
])
def test_mixed_in_set_on_the_main_path_needs_review(dax):
    """DAX compares a mixed set as text, each number in its own form (1.50 as "1.5").
    This path rewrites no literal, so even a plain integer would be emitted bare against
    a text column; every mixed set is refused (the gated parser writes plain ones as text)."""
    expr, status, _ = translate_dax(dax)
    assert (expr, status) == (None, "NEEDS REVIEW")


@pytest.mark.parametrize("dax,expected", [
    ('IF(Fact[s] IN {1, 2.5}, 1, 0)', "(if ([Fact::s] IN {1, 2.5}) then 1 else 0)"),
    ('IF(NOT ISBLANK(T[a]) && T[s] IN {"a"}, 1, 0)',
     "(if (not isnull([T::a]) and [T::s] IN {'a'}) then 1 else 0)"),
    ('IF(T[s] IN {"NOT x"}, 1, 0)', None),     # NOT inside a string is not a NOT
    ('IF(NOTE[s] IN {"a"}, 1, 0)', "(if ([NOTE::s] IN {'a'}) then 1 else 0)"),
    ('IF(T[s] IN {"1", "2"}, 1, 0)', "(if ([T::s] IN {'1', '2'}) then 1 else 0)"),
])
def test_in_sets_that_still_translate(dax, expected):
    expr, status, _ = translate_dax(dax)
    assert status == "Migrated"
    if expected:
        assert expr == expected


def test_plain_int64():
    from ts_cli.powerbi.functions import plain_int64
    assert all(plain_int64(v) for v in ("0", "-1", "10", "9223372036854775807",
                                        "-9223372036854775808"))
    assert not any(plain_int64(v) for v in ("01", "-0", "1.0", "+1", "9223372036854775808",
                                            "-9223372036854775809", "9" * 5000))


# --- Round-6 review: a [ or ] the two splitters read differently --------------------

_BRACKET_CALCS = [
    # a "[" or "]" inside a string: the earlier splitter counted it as depth, failed to
    # split and left the measure NEEDS REVIEW; read correctly, _calc_approx drops parts
    # (the first counts every open row, not just those with "[" in the title)
    'CALCULATE(COUNTROWS(FILTER(Fact, CONTAINSSTRING(Fact[Title], "["))), Fact[Status] = "Open")',
    'CALCULATE(SUM(Fact[Amount]) * IF(Fact[Tag] = "[", 2, 1), Fact[Status] = "East")',
    'CALCULATE(SUM(Fact[Amount]) * IF(Fact[Tag] = "]", 2, 1), Fact[Status] = "East")',
    # a [column] whose parens close before they open: equal counts, not nested
    'CALCULATE(SUM(Fact[x]) + Fact[a),(b], Fact[s] = "x")',
    # a ] outside any [column]
    'CALCULATE(SUM(Fact[x]) * 2 ], Fact[s] = "x")',
    'CALCULATE(SUM(Fact[x]) * 2 ], ALL(Fact[r]))',
]


@pytest.mark.parametrize("dax", _BRACKET_CALCS)
def test_calculate_with_a_bracket_the_splitters_read_differently_needs_review(dax):
    expr, status, _ = translate_dax(dax)
    assert (expr, status) == (None, "NEEDS REVIEW")


@pytest.mark.parametrize("dax", _BRACKET_CALCS[:2])
def test_formula_translate_refuses_a_bracket_in_a_string_inside_calculate(dax):
    """`ts formula translate --from dax` shares translate_dax, and returned both of these
    APPROXIMATED with part of the expression dropped."""
    from ts_cli.formula_translate.engine import translate as ft_translate
    r = ft_translate(dax, "dax")
    assert (r["status"], r["formula"]) == ("NEEDS_REVIEW", None)


@pytest.mark.parametrize("dax", [
    'CALCULATE(SUM(T[x]) * IF(MAX(T[s]) IN {"a","b"}, 2, 1), ALL(T[r]))',
    'CALCULATE(SUM(T[x]) * IF(MAX(T[s]) = "a,b", 2, 1), ALL(T[r]))',
])
def test_calculate_all_the_quote_aware_split_newly_reads_stays_needs_review(dax):
    """The group_aggregate rewrite has the same gate as _approx_calculate: a body the
    earlier splitter could not read stays NEEDS REVIEW, as on main, rather than being
    rewritten by code written against that splitter."""
    expr, status, _ = translate_dax(dax)
    assert (expr, status) == (None, "NEEDS REVIEW")


# --- Round-6 review: refuse the NOT ... IN class, not its spellings -------------------

@pytest.mark.parametrize("dax", [
    # NOT over an operand holding the set, however the operand is spelled
    'IF(NOT ((T[s])) IN {"a","b"}, 1, 0)',
    'IF(NOT UPPER(T[s]) IN {"A","B"}, 1, 0)',
    'IF(NOT T[n] + 0 IN {1, 2}, 1, 0)',
    'IF(NOT (T[n] > 1 && T[s] IN {"a","b"}), 1, 0)',
    'IF(NOT OR(T[n] > 1, T[s] IN {"a","b"}), 1, 0)',
    'IF(T[n] > 1 && NOT T[s] IN {"a","b"}, 1, 0)',
    # the set's result compared, which negates it as surely as NOT does
    'IF(T[s] IN {"a","b"} = FALSE, 1, 0)',
    'IF(T[s] IN {"a","b"} <> TRUE, 1, 0)',
    'IF(T[s] IN {"a","b"} == FALSE(), 1, 0)',
    'IF(FALSE = (T[s] IN {"a","b"}), 1, 0)',
    'IF((T[s] IN {"a","b"} && T[n] > 1) = FALSE, 1, 0)',
    'IF(AND(T[s] IN {"a","b"}, T[n] > 1) <> TRUE, 1, 0)',
])
def test_a_negated_or_compared_in_set_needs_review(dax):
    """A blank s is not in the set: FALSE in DAX, NULL in ThoughtSpot. As a condition the
    two agree (both take else); negated or compared they do not (BL-591). The last four
    were Migrated on main too, because their set's commas sat inside parens."""
    expr, status, note = translate_dax(dax)
    assert (expr, status) == (None, "NEEDS REVIEW")
    assert "BL-591" in note


@pytest.mark.parametrize("dax", [
    'IF((T[a], T[b]) IN {("x", 1), ("y", 2)}, 1, 0)',
    '(T[a], T[b]) IN {("x", 1), ("y", 2)}',
    'IF(T[n] IN {T[m], 2}, 1, 0)',
    'IF(T[n] IN {1 + 1, 3}, 1, 0)',
])
def test_an_in_set_member_that_is_not_a_literal_needs_review(dax):
    """ThoughtSpot's `in` takes a list of literals: a row constructor, a column or an
    expression in the set is refused (the second was Migrated on main)."""
    expr, status, note = translate_dax(dax)
    assert (expr, status) == (None, "NEEDS REVIEW")
    assert "literal" in note


@pytest.mark.parametrize("dax,expected", [
    # a comparison or NOT beside the set, not over it, leaves it a plain condition
    ('IF(T[n] > 1 && T[s] IN {"a","b"}, 1, 0)',
     "(if ([T::n] > 1 and [T::s] IN {'a','b'}) then 1 else 0)"),
    ('IF(T[s] IN {"a","b"} && T[n] > 1, 1, 0)',
     "(if ([T::s] IN {'a','b'} and [T::n] > 1) then 1 else 0)"),
    ('IF(NOT ISBLANK(T[a]) || T[s] IN {"a","b"}, 1, 0)',
     "(if (not isnull([T::a]) or [T::s] IN {'a','b'}) then 1 else 0)"),
    # IF turns the set back into a value both sides agree on, so comparing that is exact
    ('IF(IF(T[s] IN {"a","b"}, 1, 0) = 1, 1, 0)',
     "(if ((if ([T::s] IN {'a','b'}) then 1 else 0) = 1) then 1 else 0)"),
])
def test_a_set_beside_a_negation_it_is_not_under_still_translates(dax, expected):
    expr, status, _ = translate_dax(dax)
    assert (expr, status) == (expected, "Migrated")
