"""Unit tests for ts_cli.powerbi.gated — gated distinct-count measures.

Pure functions, no live cluster (per .claude/rules/ts-cli.md). The negative cases carry
the weight here: the first version of this module searched for a CALCULATE anywhere in the
expression and discarded the rest, so a ratio came back as its own numerator labelled
Migrated. Acceptance is now whole-expression or nothing.
"""
import pytest

from ts_cli.formula_text import ts_string_literal
from ts_cli.powerbi.functions import translate_dax
from ts_cli.powerbi.gated import parse_calculate, translate

RATIO = """VAR Hit = CALCULATE(
    DISTINCTCOUNT(Fact[Order Line]),
        NOT ISBLANK(Fact[Booked]),
        Fact[Stage] IN {"Early","On Time"})
VAR Total = CALCULATE(
    DISTINCTCOUNT(Fact[Order Line]),
        NOT ISBLANK(Fact[Booked]))
RETURN Hit/Total"""


def _t(dax, home="Fact"):
    return translate_dax(dax, home_table=home)


# ---------------------------------------------------------------- what converts

def test_gated_count():
    expr, status, _ = _t("CALCULATE(DISTINCTCOUNT(Fact[Order Line]),NOT ISBLANK(Fact[Booked]))")
    assert status == "Approximated"
    assert expr == "unique_count_if ( [Fact::Booked] != null , [Fact::Order Line] )"


def test_gated_ratio_expands_the_value_set():
    expr, status, _ = _t(RATIO)
    assert status == "Approximated"
    assert "[Fact::Stage] = 'Early' or [Fact::Stage] = 'On Time'" in expr
    assert expr.count("unique_count_if") == 2


def test_never_migrated_because_calculate_replaces_and_unique_count_if_ands():
    """Live probe (ps-internal 2026-10-08): the emitted form grouped by the column it
    filters on is row-local (On Time 3812, every other stage 0). Power BI shows 3812 in
    every row (inferred from CALCULATE semantics, not measured), because CALCULATE drops the
    grouping filter on that column."""
    for dax in ("CALCULATE(DISTINCTCOUNT(Fact[Order Line]),NOT ISBLANK(Fact[Booked]))", RATIO):
        _, status, note = _t(dax)
        assert status == "Approximated"
        assert "REPLACES" in note


def test_userelationship_adds_its_own_note():
    _, status, note = _t("CALCULATE(DISTINCTCOUNT(Fact[Order Line]),"
                         "USERELATIONSHIP(Cal[Date],Fact[Booked]))")
    assert status == "Approximated"
    assert "USERELATIONSHIP" in note


def test_nested_calculate_keeps_the_inner_gate():
    spec = parse_calculate(
        "CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[Order Line]),"
        "NOT ISBLANK(Fact[Arrived])),USERELATIONSHIP(Fact[Arrived],Cal[Date]))")
    assert spec["gates"] == [("Fact", "Arrived")]
    assert spec["userelationship"] is True


def test_quoted_table_name_with_doubled_apostrophe():
    """BL-369: a hand-rolled ref regex read 'Bob''s Sales'[g] as [s Sales::g]."""
    expr, _, _ = _t("CALCULATE(DISTINCTCOUNT('Bob''s Sales'[k]), NOT ISBLANK('Bob''s Sales'[g]))",
                    home="Bob's Sales")
    assert expr == "unique_count_if ( [Bob's Sales::g] != null , [Bob's Sales::k] )"


def test_apostrophe_in_a_value_uses_the_double_quoted_literal():
    """BL-365: emitting '{v}' raw produced an unreadable literal for O'Brien."""
    expr, _, _ = _t('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "O\'Brien")')
    assert expr == 'unique_count_if ( [Fact::s] = "O\'Brien" , [Fact::k] )'


def test_mixed_value_set_compares_as_text():
    """DAX coerces the 1 in IN {"a", 1} to "1"; a bare 1 against a text column is wrong."""
    expr, _, _ = _t('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", 1})')
    assert "[Fact::s] = 'a' or [Fact::s] = '1'" in expr


def test_all_number_value_set_stays_numeric():
    expr, _, _ = _t("CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[n] IN {1, 2.5, -3})")
    assert "[Fact::n] = 1 or [Fact::n] = 2.5 or [Fact::n] = -3" in expr


@pytest.mark.parametrize("dax_value,text", [
    ('"C:\\temp"', "C:\\temp"),                # DAX has no backslash escapes
    ('"say ""hi"""', 'say "hi"'),                # "" is one embedded quote (BL-365)
])
def test_literals_use_the_shared_dax_decoder(dax_value, text):
    """The value is the text DAX means, printed the way every other translator prints it."""
    expr, status, _ = _t(f"CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = {dax_value})")
    assert status == "Approximated"
    assert expr == f"unique_count_if ( [Fact::s] = {ts_string_literal(text)} , [Fact::k] )"


def test_not_isblank_with_parentheses():
    expr, _, _ = _t("CALCULATE(DISTINCTCOUNT(Fact[k]), NOT(ISBLANK(Fact[g])))")
    assert expr == "unique_count_if ( [Fact::g] != null , [Fact::k] )"


def test_nested_calculate_on_different_columns_is_anded():
    expr, _, _ = _t('CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a"), '
                    'NOT ISBLANK(Fact[g]))')
    assert expr == "unique_count_if ( [Fact::g] != null and [Fact::s] = 'a' , [Fact::k] )"


# ---------------------------------------------------------------- what must refuse

@pytest.mark.parametrize("label,dax", [
    ("the CALCULATE is only the numerator",
     "DIVIDE(CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g])), DISTINCTCOUNT(Fact[k]))"),
    ("RETURN is DIVIDE(a,b), not a/b",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h]))\nRETURN DIVIDE(a, b)"),
    ("RETURN does arithmetic around the ratio",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h]))\nRETURN 1 - a/b"),
    ("a VAR that is not a CALCULATE",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR b = a*2\nRETURN a/b"),
    ("&& — the second predicate would be dropped",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]) && Fact[qty] > 5)"),
    ("|| — the second predicate would be dropped",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]) || NOT ISBLANK(Fact[h]))"),
    ("a filter on another table would be re-qualified to the home table",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Dim[g]))"),
    ("the key is counted off another table",
     "CALCULATE(DISTINCTCOUNT('Dim Cust'[id]), NOT ISBLANK(Fact[g]))"),
    ("subtraction around the CALCULATE",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g])) - DISTINCTCOUNT(Fact[k])"),
    ("division by a measure, not by a second CALCULATE",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g])) / [Total]"),
    ("arithmetic inside the aggregate",
     "CALCULATE(DISTINCTCOUNT(Fact[k]) * 100, NOT ISBLANK(Fact[g]))"),
    ("wrapped in IF",
     "IF(ISBLANK(Fact[x]), 0, CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g])))"),
    ("a filter shape we do not read",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), FILTER(Fact, Fact[qty] > 5))"),
    ("a value we cannot render as a literal",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = Fact[t])"),
    # Second review: every filter must be exactly `<ref> = lit`, `<ref> IN {…}` or
    # NOT ISBLANK(<ref>). Each of these used to come back as a wrong formula.
    (">= is not =", "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[qty] >= 5)"),
    ("<= is not =", "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[qty] <= 5)"),
    ("== is not =", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] == "a")'),
    ("NOT before = would be lost", 'CALCULATE(DISTINCTCOUNT(Fact[k]), NOT Fact[s] = "a")'),
    ("NOT before IN would be lost",
     'CALCULATE(DISTINCTCOUNT(Fact[k]), NOT Fact[s] IN {"a","b"})'),
    ("LEFT() around the column", 'CALCULATE(DISTINCTCOUNT(Fact[k]), LEFT(Fact[s],1) = "A")'),
    ("YEAR() around the column", "CALCULATE(DISTINCTCOUNT(Fact[k]), YEAR(Fact[d]) = 2024)"),
    ("arithmetic on the column", "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[qty] + 1 = 5)"),
    ("|| between two = predicates",
     'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "Early" || Fact[s] = "On Time")'),
    ("&& between two = predicates",
     'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a" && Fact[t] = "b")'),
    ("&& between two IN predicates",
     'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a"} && Fact[t] IN {"b"})'),
    ("& concatenation inside a value set",
     'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a" & "b"})'),
    ("& concatenation as the value", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a" & "b")'),
    ("NOT ISBLANK && NOT(measure)",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]) && NOT([Is Test]))"),
    ("NOT ISBLANK && ISBLANK(measure)",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]) && ISBLANK([M]))"),
    ("NOT ISBLANK || a constant",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]) || (1 = 1))"),
    ("NOT ISBLANK of an expression, not a column",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(IF(Fact[g] > 5, 1)))"),
    ("USERELATIONSHIP with a trailing predicate",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), USERELATIONSHIP(Cal[Date], Fact[d]) && NOT(ISBLANK(Fact[g])))"),
    ("a bare column, not a qualified one", 'CALCULATE(DISTINCTCOUNT(Fact[k]), [s] = "a")'),
    ("trailing text after the value set",
     'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a"} || TRUE)'),
    ("nested CALCULATE filtering the same column: the inner filter wins in DAX",
     'CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a"), Fact[s] = "b")'),
    ("nested CALCULATE gating the same column it filters",
     'CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[s])), Fact[s] IN {"a"})'),
])
def test_refuses_and_keeps_needs_review(label, dax):
    assert translate(dax, "Fact") == (None, None, None), label
    expr, status, _ = _t(dax)
    assert expr is None and status == "NEEDS REVIEW", label


# ---------------------------------------------------------------- third review

@pytest.mark.parametrize("label,dax", [
    ("a trailing -- comment carries a second VAR b that would overwrite the real one",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h])) "
     "-- VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]))\n"
     "RETURN a / b"),
    ("a // comment line carries a second VAR a that would overwrite the real one",
     'VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "Early")\n'
     "// VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]))\n"
     "RETURN a / b"),
    ("a /* */ comment in a single CALCULATE",
     "CALCULATE(DISTINCTCOUNT(Fact[k]), /* gate */ NOT ISBLANK(Fact[g]))"),
    ("a VAR defined twice, no comment involved",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]))\n"
     "RETURN a / b"),
    ("VAR names are case-insensitive in DAX, so A redefines a",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR A = CALCULATE(DISTINCTCOUNT(Fact[k]))\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h]))\n"
     "RETURN a / b"),
    ("text between VAR definitions would be skipped",
     "VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
     "VAR = junk\n"
     "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h]))\n"
     "RETURN a / b"),
    # BLANK() = 0 and BLANK() = "" are TRUE in DAX, so Power BI also keeps blank rows.
    ("= 0 also matches BLANK in DAX", "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[n] = 0)"),
    ("= 0.0 also matches BLANK in DAX", "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[n] = 0.0)"),
    ('= "" also matches BLANK in DAX', 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "")'),
    ("IN {…} holding 0", "CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[n] IN {1, 0})"),
    ('IN {…} holding ""', 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", ""})'),
])
def test_third_review_refusals(label, dax):
    assert translate(dax, "Fact") == (None, None, None), label
    expr, status, _ = _t(dax)
    assert expr is None and status == "NEEDS REVIEW", label


def test_comment_markers_inside_a_string_are_not_comments():
    expr, status, _ = _t('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a--b", "c//d"})')
    assert status == "Approximated"
    assert "[Fact::s] = 'a--b' or [Fact::s] = 'c//d'" in expr


def test_a_string_holding_zero_is_not_blank_equal():
    expr, status, _ = _t('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "0")')
    assert status == "Approximated"
    assert expr == "unique_count_if ( [Fact::s] = '0' , [Fact::k] )"


@pytest.mark.parametrize("dax,cond", [
    ('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[d] = "2024-01-01")', "[Fact::d] = '2024-01-01'"),
    ("CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = 1)", "[Fact::s] = 1"),
])
def test_type_mismatches_pass_through_unchanged(dax, cond):
    """Pinned, not endorsed: the column's type is unknown here, so a text literal against a
    date column (or a number against a text one) is emitted as written. A mismatch fails at
    Model import rather than giving a wrong number."""
    expr, status, _ = _t(dax)
    assert status == "Approximated"
    assert expr == f"unique_count_if ( {cond} , [Fact::k] )"


@pytest.mark.parametrize("flt", ['Fact[s] = "a,b"', 'Fact[s] = "a)b"', 'Fact[s] IN {"a)b"}'])
def test_literals_holding_split_characters_are_refused(flt):
    """Pinned coverage gap: argument splitting and paren matching do not skip strings, so
    a value holding , or ) outside a value set mis-splits and the measure is refused. Safe,
    never a wrong formula."""
    assert translate(f"CALCULATE(DISTINCTCOUNT(Fact[k]), {flt})", "Fact") == (None, None, None)


@pytest.mark.parametrize("flt,value", [
    ('Fact[s] IN {"a,b"}', "'a,b'"), ('Fact[s] IN {"a}b"}', "'a}b'"),
    ('Fact[s] = "a}b"', "'a}b'"),
])
def test_split_characters_that_do_not_mis_split_convert_whole(flt, value):
    expr, _, _ = _t(f"CALCULATE(DISTINCTCOUNT(Fact[k]), {flt})")
    assert expr == f"unique_count_if ( [Fact::s] = {value} , [Fact::k] )"


def test_formula_translate_path_does_not_reach_the_gated_shapes():
    """`ts formula translate --from dax` passes a sentinel home table, so every column is
    off the home table and the gated translator refuses. Pinned so a change to the adapter
    cannot open this path without a test noticing."""
    from ts_cli.formula_translate.engine import translate as ft_translate
    r = ft_translate("CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))", "dax")
    assert r["status"] == "NEEDS_REVIEW" and r["formula"] is None


def test_ratio_over_two_different_grains_is_refused():
    assert translate(RATIO.replace("DISTINCTCOUNT(Fact[Order Line]),\n        NOT ISBLANK(Fact[Booked]))",
                                   "DISTINCTCOUNT(Fact[Shipment]),\n        NOT ISBLANK(Fact[Booked]))"),
                     "Fact") == (None, None, None)


def test_unrelated_dax_still_needs_review():
    expr, status, _ = _t("SUMX(Sales, Sales[Qty] * Sales[Price])")
    assert expr is None and status == "NEEDS REVIEW"
