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
    DISTINCTCOUNT(Fact[Order Key]),
        NOT ISBLANK(Fact[Gate A]),
        Fact[Status] IN {"x","y"})
VAR Total = CALCULATE(
    DISTINCTCOUNT(Fact[Order Key]),
        NOT ISBLANK(Fact[Gate A]))
RETURN Hit/Total"""


def _t(dax, home="Fact"):
    return translate_dax(dax, home_table=home)


# ---------------------------------------------------------------- what converts

def test_gated_count():
    expr, status, _ = _t("CALCULATE(DISTINCTCOUNT(Fact[Order Key]),NOT ISBLANK(Fact[Gate A]))")
    assert status == "Approximated"
    assert expr == "unique_count_if ( [Fact::Gate A] != null , [Fact::Order Key] )"


def test_gated_ratio_expands_the_value_set():
    expr, status, _ = _t(RATIO)
    assert status == "Approximated"
    assert "[Fact::Status] = 'x' or [Fact::Status] = 'y'" in expr
    assert expr.count("unique_count_if") == 2


def test_never_migrated_because_calculate_replaces_and_unique_count_if_ands():
    """Grouped by the filtered column, the emitted form is row-local (0 in every row but the
    filtered one), while CALCULATE replaces the grouping filter and gives the full count in
    every row (gated.py's docstring has the synthetic illustration)."""
    for dax in ("CALCULATE(DISTINCTCOUNT(Fact[Order Key]),NOT ISBLANK(Fact[Gate A]))", RATIO):
        _, status, note = _t(dax)
        assert status == "Approximated"
        assert "REPLACES" in note


def test_userelationship_adds_its_own_note():
    """USERELATIONSHIP alone gates nothing, so the count is a plain DISTINCTCOUNT and gets
    main's blank-counting form and its note (BL-540), plus the role-playing-date note."""
    expr, status, note = _t("CALCULATE(DISTINCTCOUNT(Fact[Order Key]),"
                            "USERELATIONSHIP(Cal[Date],Fact[Gate A]))")
    assert status == "Approximated"
    assert expr == ("( unique count ( [Fact::Order Key] ) + max ( if ( isnull ( "
                    "[Fact::Order Key] ) ) then 1 else 0 ) )")
    assert "USERELATIONSHIP" in note and note.startswith("DISTINCTCOUNT counts a blank key")


def test_userelationship_with_a_gate_pins_the_formula():
    expr, _, note = _t("CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]), "
                       "USERELATIONSHIP(Cal[Date], Fact[d]))")
    assert expr == "unique_count_if ( [Fact::g] != null , [Fact::k] )"
    assert "REPLACES" in note and "USERELATIONSHIP" in note


def test_nested_calculate_keeps_the_inner_gate():
    spec = parse_calculate(
        "CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[Order Key]),"
        "NOT ISBLANK(Fact[Gate B])),USERELATIONSHIP(Fact[Gate B],Cal[Date]))")
    assert spec["gates"] == [("Fact", "Gate B")]
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
     'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "x" || Fact[s] = "y")'),
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
     'VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "x")\n'
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
    date column (or a number against a text one) is emitted as written. A mismatch is
    expected to fail at Model import rather than give a wrong number (not probed)."""
    expr, status, _ = _t(dax)
    assert status == "Approximated"
    assert expr == f"unique_count_if ( {cond} , [Fact::k] )"


@pytest.mark.parametrize("flt,value", [
    ('Fact[s] = "a,b"', "'a,b'"), ('Fact[s] = "a)b"', "'a)b'"),
    ('Fact[s] IN {"a)b"}', "'a)b'"), ('Fact[s] IN {"a,b"}', "'a,b'"),
    ('Fact[s] IN {"a}b"}', "'a}b'"), ('Fact[s] = "a}b"', "'a}b'"),
    ('Fact[s] = "a(b"', "'a(b'"), ('Fact[s] IN {"{", "}"}', None),
])
def test_split_characters_inside_a_literal_convert_whole(flt, value):
    """Round-4 review 5: argument splitting and paren matching skip DAX string literals,
    so a value holding , ) } ( converts as one value instead of mis-splitting."""
    expr, status, _ = _t(f"CALCULATE(DISTINCTCOUNT(Fact[k]), {flt})")
    assert status == "Approximated"
    cond = (f"[Fact::s] = {value}" if value else "( [Fact::s] = '{' or [Fact::s] = '}' )")
    assert expr == f"unique_count_if ( {cond} , [Fact::k] )"


def test_paren_inside_a_quoted_table_name_or_column_is_not_structure():
    expr, _, _ = _t("CALCULATE(DISTINCTCOUNT('T (x)'[k]), NOT ISBLANK('T (x)'[g (1)]))",
                    home="T (x)")
    assert expr == "unique_count_if ( [T (x)::g (1)] != null , [T (x)::k] )"


def test_formula_translate_path_does_not_reach_the_gated_shapes():
    """`ts formula translate --from dax` passes a sentinel home table, so every column is
    off the home table and the gated translator refuses. Pinned so a change to the adapter
    cannot open this path without a test noticing."""
    from ts_cli.formula_translate.engine import translate as ft_translate
    r = ft_translate("CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))", "dax")
    assert r["status"] == "NEEDS_REVIEW" and r["formula"] is None


# ---------------------------------------------------------------- fourth review

@pytest.mark.parametrize("label,dax", [
    ("inner and outer filter the same column in different case: the inner wins in DAX",
     'CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a"), Fact[S] = "b")'),
    ("inner gate and outer value set on the same column in different case",
     'CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[s])), Fact[S] IN {"a"})'),
    ("table name in different case is the same table",
     'CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a"), FACT[s] = "b")'),
    ("non-ASCII case variant (casefold, not lower)",
     'CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[Straße] = "a"), Fact[STRASSE] = "b")'),
    # DAX converts a number in a mixed set to its own text form, not the digits as written
    ("1.50 compares as \"1.5\" in DAX", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", 1.50})'),
    ("1.0 compares as \"1\" in DAX", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", 1.0})'),
    ("01 compares as \"1\" in DAX", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", 01})'),
    ("-01 compares as \"-1\" in DAX", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", -01})'),
    ("a decimal anywhere in a mixed set", 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {2.5, "a"})'),
])
def test_fourth_review_refusals(label, dax):
    assert translate(dax, "Fact") == (None, None, None), label
    expr, status, _ = _t(dax)
    assert expr is None and status == "NEEDS REVIEW", label


@pytest.mark.parametrize("member,ts_value", [("1", "'1'"), ("-2", "'-2'"), ("10", "'10'")])
def test_plain_integer_in_a_mixed_set_compares_as_its_text(member, ts_value):
    expr, status, _ = _t(f'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {{"a", {member}}})')
    assert status == "Approximated"
    assert f"[Fact::s] = 'a' or [Fact::s] = {ts_value}" in expr


def test_an_all_number_set_keeps_its_decimals():
    """Only a MIXED set is compared as text; a numeric set compares numerically, so 1.50
    is 1.5 on both sides and stays as written."""
    expr, _, _ = _t("CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[n] IN {1.50, 2})")
    assert "[Fact::n] = 1.50 or [Fact::n] = 2" in expr


def test_note_says_distinctcount_counts_a_blank_key():
    _, _, note = _t("CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))")
    assert "blank key as one value" in note and "ignores NULL" in note


def test_var_scan_is_linear():
    """Round-4 review 6: a leading \\s* under finditer rescanned a whitespace run from
    every start (0.5s at 16,000 spaces). Generous bound: quadratic at 200k takes minutes."""
    import time
    head = ("VAR a = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[g]))\n"
            "VAR b = CALCULATE(DISTINCTCOUNT(Fact[k]), NOT ISBLANK(Fact[h]))\nRETURN")
    for src in (head + " " * 200_000 + "a / b",
                "VAR" + " " * 200_000 + "a = 1 RETURN a / b",
                head.replace("VAR b", "VAR" + " " * 200_000 + "b") + " a / b"):
        t0 = time.monotonic()
        translate(src, "Fact")
        assert time.monotonic() - t0 < 5


# ---------------------------------------------------------------- fifth review

def test_a_mixed_set_integer_must_fit_64_bits():
    assert translate('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", 99999999999999999999})',
                     "Fact") == (None, None, None)
    expr, _, _ = _t('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {"a", 9223372036854775807})')
    assert "[Fact::s] = '9223372036854775807'" in expr


def test_calculated_column_keeps_needs_review():
    """DAX evaluates a calculated column per row; the emitted aggregate would not."""
    dax = 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a")'
    assert translate_dax(dax, home_table="Fact", is_measure=False)[:2] == (None, "NEEDS REVIEW")
    assert translate_dax(dax, home_table="Fact")[1] == "Approximated"


def test_build_model_refuses_a_gated_calculated_column():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from test_powerbi_build_model import _inv
    from ts_cli.powerbi.build_model import assemble
    inv = _inv()
    fact = inv["tables"][0]
    dax = 'CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a")'
    fact["columns"] += [{"name": "s", "dataType": "string"}, {"name": "k", "dataType": "string"},
                        {"name": "Gated Col", "dataType": "int64", "calculated": True,
                         "expression": dax}]
    fact["measures"].append({"name": "Gated Measure", "expression": dax})
    _, mapping = assemble(inv, {}, "C", "d", "s", "LEFT_OUTER", False)
    status = {r["name"]: r["status"] for r in mapping["measures"]}
    assert status["Gated Col"] == "NEEDS REVIEW"
    assert status["Gated Measure"] == "Approximated"


def test_deep_nesting_refuses_instead_of_raising():
    """1,200 levels pass Python's default recursion limit of 1,000 (BL-611 item 4: 3,000 took 13s)."""
    src = "CALCULATE(" * 1200 + "DISTINCTCOUNT(Fact[k])" + ", NOT ISBLANK(Fact[g]))" * 1200
    assert translate(src, "Fact") == (None, None, None)
    assert _t(src)[1] == "NEEDS REVIEW"


def test_value_set_is_linear():
    """Round-5 review: slicing per member made 64k members take 3s. Compares n members
    with 2n rather than a fixed bound, which a slow runner fails on correct code and a
    fast one passes with the quadratic code back (BL-611 item 4). Linear doubles the
    time; quadratic quadruples it. Best of three, to ride out a busy machine."""
    import time

    def secs(n):
        src = ('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] IN {' + ", ".join(['"a"'] * n)
               + "})")
        best = float("inf")
        for _ in range(3):
            t0 = time.monotonic()
            translate(src, "Fact")
            best = min(best, time.monotonic() - t0)
        return best

    small, big = secs(20_000), secs(40_000)
    assert big / small < 3.2, f"{big:.2f}s for 40k vs {small:.2f}s for 20k"


def test_note_says_when_the_two_forms_differ():
    _, _, note = _t('CALCULATE(DISTINCTCOUNT(Fact[k]), Fact[s] = "a")')
    assert "slicer" in note and "page" in note and "emitted side live-probed" in note


def test_ratio_over_two_different_grains_is_refused():
    assert translate(RATIO.replace("DISTINCTCOUNT(Fact[Order Key]),\n        NOT ISBLANK(Fact[Gate A]))",
                                   "DISTINCTCOUNT(Fact[Other Key]),\n        NOT ISBLANK(Fact[Gate A]))"),
                     "Fact") == (None, None, None)


def test_unrelated_dax_still_needs_review():
    expr, status, _ = _t("SUMX(Sales, Sales[Qty] * Sales[Price])")
    assert expr is None and status == "NEEDS REVIEW"
