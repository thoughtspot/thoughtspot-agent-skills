"""The type checker over emitted ThoughtSpot ASTs (``ts_cli/excel/typecheck.py``).

Its job: a translation ThoughtSpot would reject at import (*Function X expects …*, error_code
14516) is never reported TRANSLATED — fidelity M1 found 36 such cases (BL-352..355). The
formulas here are written for these tests; none is copied from the M1 corpus.
"""
from __future__ import annotations

import json

import pytest

from ts_cli.excel.helpers import from_text
from ts_cli.excel.translate import translate_excel
from ts_cli.excel.typecheck import check, infer, type_of_data_type
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json

TYPES = {"amt": "DOUBLE", "qty": "INT64", "name": "VARCHAR", "day": "DATE",
         "flag": "BOOLEAN", "dec": "DECIMAL", "ts": "DATE_TIME"}
COLUMNS = json.dumps({c: {"table": "T", "column": c, "data_type": t} for c, t in TYPES.items()})


def _col_type(node):
    name = node.get("column") or node.get("name")
    return type_of_data_type(TYPES.get(name)) if name in TYPES else None


def errors(text):
    return check(from_text(text), _col_type)[0]


def unknown(text):
    return [need for _node, need in check(from_text(text), _col_type)[1]]


def tx(src, typed=True):
    ctx = ColumnContext(parse_columns_json(COLUMNS), level=1) if typed else ColumnContext()
    return translate_excel(src, ctx)


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("3", "int"), ("3.5", "double"), ("'x'", "text"), ("true", "bool"),
    ("[T::qty]", "int"), ("[T::amt]", "double"), ("[T::dec]", "number"),
    ("[T::qty] + 1", "int"), ("[T::qty] * [T::amt]", "double"), ("[T::qty] / 2", "double"),
    ("floor ( [T::amt] )", "int"), ("ceil ( [T::amt] )", "int"), ("abs ( [T::amt] )", "double"),
    ("strlen ( [T::name] )", "int"), ("to_date ( '2020-01-02' , '%Y-%m-%d' )", "date"),
    ("add_days ( [T::day] , 1 )", "date"), ("diff_days ( [T::day] , [T::day] )", "int"),
    ("if ( [T::flag] ) then 1 else 2.5", "double"), ("if ( [T::flag] ) then 'a' else null", "text"),
    ("[T::qty] > 1", "bool"), ("to_string ( [T::qty] )", "text"),
])
def test_infer(text, expected):
    assert infer(from_text(text), _col_type) == expected


# ---------------------------------------------------------------------------
# Provable errors — each one a live VALIDATE_ONLY rejection (probe record §7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,fragment", [
    ("concat ( 'a' , [T::qty] )", "concat argument 2 expects Text"),
    ("to_string ( [T::name] )", "to_string argument 1"),
    ("to_string ( [T::day] )", "to_string argument 1"),
    ("to_double ( [T::amt] )", "to_double argument 1"),
    ("substr ( [T::name] , [T::amt] , 2 )", "substr argument 2 expects an integer"),
    ("substr ( [T::name] , 1 , 1.5 )", "substr argument 3 expects an integer"),
    ("left ( [T::name] , [T::amt] )", "left argument 2 expects an integer"),
    ("right ( [T::name] , [T::amt] - 1 )", "right argument 2 expects an integer"),
    ("add_months ( [T::day] , [T::amt] )", "add_months argument 2"),
    ("mod ( [T::amt] , 2 )", "mod argument 1"),
    ("strlen ( [T::amt] )", "strlen argument 1 expects Text"),
    ("strpos ( 'abc' , 5 )", "strpos argument 2 expects Text"),
    ("year ( [T::amt] )", "year argument 1 expects a Date"),
    ("month_number ( 0 )", "month_number argument 1"),
    ("start_of_month ( 'not a date' )", "start_of_month argument 1"),
    ("diff_days ( '2020-01-02' , [T::day] )", "diff_days argument 1"),
    ("abs ( [T::name] )", "abs argument 1 expects a number"),
    ("floor ( [T::day] )", "floor argument 1"),
    ("round ( [T::flag] , 1 )", "round argument 1"),
    ("[T::name] * 2", "operator * expects a number"),
    ("[T::flag] + 1", "operator + expects a number"),
    ("- [T::name]", "unary -"),
    ("[T::qty] = 'a'", "compares an integer with Text"),
    ("'yes' != [T::flag]", "compares Text with a Boolean"),
    ("[T::day] = 'a'", "compares a Date with Text"),
    ("[T::qty] and true", "and"),
    ("not ( [T::qty] )", "not"),
    ("if ( [T::qty] ) then 1 else 0", "an if condition"),
    ("if ( [T::flag] ) then 'x' else [T::amt] / 2", "if branches have different types"),
    ("if ( [T::flag] ) then true else 1", "if branches have different types"),
    ("if ( [T::flag] ) then [T::day] else 'x'", "if branches have different types"),
    ("ifnull ( [T::qty] , 'x' )", "ifnull needs both arguments of one type"),
])
def test_error(text, fragment):
    found = errors(text)
    assert any(fragment in e for e in found), found


@pytest.mark.parametrize("text", [
    "concat ( 'a' , to_string ( [T::qty] ) )", "to_string ( [T::amt] )",
    "to_double ( [T::qty] )", "to_double ( [T::name] )", "to_integer ( [T::amt] )",
    "substr ( [T::name] , floor ( [T::amt] ) - 1 , floor ( [T::amt] ) )",
    "substr ( [T::name] , [T::qty] - 1 , 2 )", "right ( 'abc' , [T::qty] )",
    "add_days ( to_date ( '1899-12-30' , '%Y-%m-%d' ) , floor ( [T::amt] ) )",
    "if ( [T::flag] ) then 1 else 2.5", "if ( [T::flag] ) then [T::qty] else [T::amt]",
    "if ( [T::flag] ) then 'a' else null", "[T::qty] = [T::amt]", "greatest ( [T::amt] , 1 )",
    "abs ( [T::amt] )", "pow ( [T::amt] , [T::amt] )", "safe_divide ( [T::amt] , [T::qty] )",
    "sql_string_op ( \"UPPER({0})\" , [T::day] )", "isnull ( [T::day] )",
    "diff_days ( now ( ) , [T::day] )", "day_number_of_week ( now ( ) )",
    "ifnull ( [T::amt] , 0 )", "sum ( [T::amt] )", "sum_if ( [T::qty] > 1 , [T::amt] )",
    # a DECIMAL column in an integer slot cannot be decided: not an error
    "left ( [T::name] , [T::dec] )",
])
def test_accepted(text):
    assert errors(text) == []


def test_unknown_column_in_an_integer_slot_is_asked_not_guessed():
    assert unknown("left ( 'abc' , [T::other] )") == [
        "left argument 2 needs an integer (ThoughtSpot's Numeric; a DOUBLE is rejected)"]
    # arithmetic and text slots: the common type is the right one, so no question
    assert unknown("[T::other] * 2") == [] and unknown("strlen ( [T::other] )") == []


# ---------------------------------------------------------------------------
# Through the translator: the gate
# ---------------------------------------------------------------------------

def test_a_provable_type_error_is_needs_review_with_the_reason():
    # comparing a date with a text that is not a date: no rule converts it
    r = tx('=[@day]="soon"')
    assert r.status == "NEEDS_REVIEW" and r.expr is None
    assert any(n.startswith("type check:") and "error_code 14516" in n for n in r.notes)


def test_unknown_type_in_an_integer_slot_uses_needs_types():
    r = tx("=LEFT([@code],[@width])", typed=False)
    assert r.status != "NEEDS_REVIEW"
    assert [t[1] for t in r.type_needs] == ["typed argument"]
    assert r.type_needs[0][0].endswith("width]")


# Look-alikes of the M1 import-failure shapes, in our own words: a text date, a serial number
# or text in a date function, numbers into text functions, numeric text into arithmetic, a
# DOUBLE in an integer slot, IFERROR with a text fallback, text compared with a boolean.
LOOKALIKES = [
    '=YEAR("2015-02-11")', '=MONTH(45000)', '=DAY([@amt])', '=EDATE("1999-06-30",2)',
    '=EOMONTH("2010-01-15",0)', '=WEEKDAY("2012-12-12",2)', '=DAYS("2000-01-10","1999-12-25")',
    '=EOMONTH("not a date",1)', '=DAY(-0)', '=LEN([@amt])', '=MID([@amt],2,1)',
    '=SEARCH(7,1234567)', '=VALUE([@amt])', '=VALUE([@day])', '=ABS([@name])',
    '=[@name]/[@qty]', '=ROUNDUP([@name],1)', '=POWER([@name],2)', '=MOD([@name],3)',
    '=MID([@name],[@amt],[@amt])', '=RIGHT("abcdef",[@amt])', '=LEFT([@name],[@amt])',
    '=IFERROR(1/0,"none")', '="yes"<>[@flag]', '=UPPER([@day])', '="a"&[@day]',
    '=CEILING([@name],1)',
]


@pytest.mark.parametrize("src", LOOKALIKES)
def test_never_translated_but_ill_typed(src):
    r = tx(src)
    if r.status != "NEEDS_REVIEW":
        ast = from_text(r.expr)
        assert check(ast, _col_type)[0] == [], r.expr
