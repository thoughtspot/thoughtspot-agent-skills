"""The Excel translator fixes from formula fidelity M1 (BL-346..355), one block per BL item.

Every formula is written for these tests — none is copied from the M1 corpus (which lives
outside the repo, see tools/formula-fidelity/README.md). Each block pins the emitted form; the
type checker (test_excel_typecheck.py) pins that none of it can fail ThoughtSpot's import.
"""
from __future__ import annotations

import json

import pytest

from ts_cli.excel.helpers import from_text
from ts_cli.excel.translate import translate_excel
from ts_cli.excel.typecheck import check, type_of_data_type
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json

TYPES = {"amt": "DOUBLE", "qty": "INT64", "name": "VARCHAR", "day": "DATE",
         "flag": "BOOLEAN", "stamp": "DATE_TIME"}
COLUMNS = json.dumps({c: {"table": "T", "column": c, "data_type": t} for c, t in TYPES.items()})
EPOCH = "to_date ( '1899-12-30' , '%Y-%m-%d' )"


def tx(src):
    return translate_excel(src, ColumnContext(parse_columns_json(COLUMNS), level=1))


def ok(src):
    r = tx(src)
    assert r.expr is not None, r.notes
    errs = check(from_text(r.expr), lambda n: type_of_data_type(TYPES.get(n.get("column"))))[0]
    assert errs == [], (r.expr, errs)
    return r


def f(src):
    return ok(src).expr


def review(src):
    r = tx(src)
    assert r.status == "NEEDS_REVIEW" and r.expr is None, r.expr
    return r.notes[-1]


# ---------------------------------------------------------------------------
# BL-352: a date written as text, in a date function
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ('=YEAR("2015-02-11")', "year ( to_date ( '2015-02-11' , '%Y-%m-%d' ) )"),
    ('=EDATE("1999-06-30",2)', "add_months ( to_date ( '1999-06-30' , '%Y-%m-%d' ) , 2 )"),
    ('=DAY("2004/02/29")', "day ( to_date ( '2004/02/29' , '%Y/%m/%d' ) )"),
    ('=MONTH("25/12/2020")', "month_number ( to_date ( '25/12/2020' , '%d/%m/%Y' ) )"),
    ('=MONTH("12/25/2020")', "month_number ( to_date ( '12/25/2020' , '%m/%d/%Y' ) )"),
    ('=MONTH("07/07/2020")', "month_number ( to_date ( '07/07/2020' , '%m/%d/%Y' ) )"),
    ('=DAY("2010-05-06T07:08:09")',
     "day ( to_date ( '2010-05-06T07:08:09' , '%Y-%m-%dT%H:%M:%S' ) )"),
    ('=DAYS("2000-01-10",[@day])',
     "diff_days ( to_date ( '2000-01-10' , '%Y-%m-%d' ) , [T::day] )"),
])
def test_text_date_becomes_to_date(src, expected):
    assert f(src) == expected


def test_text_date_in_weekday_and_eomonth():
    assert "day_number_of_week ( to_date ( '2012-12-12' , '%Y-%m-%d' ) )" in f(
        '=WEEKDAY("2012-12-12",2)')
    assert "start_of_month ( to_date ( '2010-01-15' , '%Y-%m-%d' ) )" in f(
        '=EOMONTH("2010-01-15",0)')


@pytest.mark.parametrize("src,why", [
    ('=MONTH("03/04/2026")', "day/month or month/day"),
    ('=YEAR("someday")', "#VALUE!"),
    ('=YEAR("2021-02-30")', "not a real date"),
    ('=DAY("1850-01-01")', "before 1900"),
])
def test_text_date_that_cannot_be_read_is_needs_review(src, why):
    assert why in review(src)


# ---------------------------------------------------------------------------
# BL-353 (dates): a serial number in a date function
# ---------------------------------------------------------------------------

def test_serial_literal_is_its_date():
    assert f("=YEAR(45000)") == "year ( to_date ( '2023-03-15' , '%Y-%m-%d' ) )"
    assert f("=MONTH(3)") == "month_number ( to_date ( '1900-01-03' , '%Y-%m-%d' ) )"


@pytest.mark.parametrize("src", ["=MONTH(0)", "=DAY(60)", "=YEAR(-5)"])
def test_serial_with_no_real_date_is_needs_review(src):
    assert "1900" in review(src)


def test_numeric_column_in_a_date_function_counts_days_from_the_excel_epoch():
    r = ok("=YEAR([@amt])")
    assert r.expr == f"year ( add_days ( {EPOCH} , floor ( [T::amt] ) ) )"
    assert any("1899-12-30" in t for t in r.traps)
    assert f("=MONTH([@qty])") == f"month_number ( add_days ( {EPOCH} , [T::qty] ) )"


def test_text_column_in_a_date_function_is_needs_review():
    assert "locale" in review("=YEAR([@name])")


# ---------------------------------------------------------------------------
# BL-353: Excel's implicit coercion between number, text and boolean
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    # a number into a text function: its digits
    ("=LEN([@qty])", "strlen ( to_string ( [T::qty] ) )"),
    ("=LEFT([@amt],2)", "left ( to_string ( [T::amt] ) , 2 )"),
    ("=SEARCH(7,1234567)", "strpos ( to_string ( 1234567 ) , to_string ( 7 ) )"),
    # numeric text literal in arithmetic: folded to the number
    ('="4"*[@qty]', "4 * [T::qty]"),
    ('=ABS("-2.5")', "abs ( - 2.5 )"),
    # VALUE of a number is the number (to_double rejects a DOUBLE); of a date, its serial
    ("=VALUE([@amt])", "[T::amt]"),
    ("=VALUE([@day])", "diff_days ( [T::day] , to_date ( '1899-12-30' , '%Y-%m-%d' ) )"),
    ("=VALUE([@name])", "to_double ( [T::name] )"),
    # a boolean in arithmetic: if … then 1 else 0 (unchanged)
    ("=[@flag]+1", "( if ( [T::flag] ) then 1 else 0 ) + 1"),
])
def test_coercion_emitted_form(src, expected):
    assert f(src) == expected


@pytest.mark.parametrize("src,expected", [
    ("=ABS([@name])", "abs ( to_double ( [T::name] ) )"),
    ("=[@name]/[@qty]", "to_double ( [T::name] ) / [T::qty]"),
    ("=POWER([@name],2)", "pow ( to_double ( [T::name] ) , 2 )"),
    ("=CEILING([@name],1)", "ceil ( to_double ( [T::name] ) / 1 ) * 1"),
])
def test_text_column_in_arithmetic_is_to_double_with_a_trap(src, expected):
    r = ok(src)
    assert r.expr == expected and r.status == "APPROXIMATED"
    assert any("#VALUE!" in t for t in r.traps)


def test_non_numeric_text_literal_in_arithmetic_is_needs_review():
    assert "#VALUE!" in review('="abc"+1')


@pytest.mark.parametrize("src,expected", [
    ('="yes"<>[@flag]', "true"), ('="yes"=[@flag]', "false"),
    ('=[@qty]="5"', "false"),          # a number never equals text in Excel
    ('=[@qty]<"a"', "true"),           # numbers sort before text
    ('=[@flag]>"zzz"', "true"),        # booleans sort after text
])
def test_comparison_across_types_follows_excel_type_order(src, expected):
    r = ok(src)
    assert r.expr == expected and any("by type" in n for n in r.notes)


def test_date_compared_with_text_stays_needs_review():
    assert review('=[@day]="soon"').startswith("type check:")


# ---------------------------------------------------------------------------
# BL-355: a DOUBLE in an integer slot
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("=MID([@name],[@amt],[@amt])",
     "substr ( [T::name] , floor ( [T::amt] ) - 1 , floor ( [T::amt] ) )"),
    ("=MID([@name],[@qty],2)", "substr ( [T::name] , [T::qty] - 1 , 2 )"),
    ("=MID([@name],2.9,1.5)", "substr ( [T::name] , 1 , 1 )"),   # Excel truncates
    ("=RIGHT([@name],[@amt])", "right ( [T::name] , floor ( [T::amt] ) )"),
    ("=LEFT([@name],[@qty])", "left ( [T::name] , [T::qty] )"),
    ("=LEFT([@name],2.7)", "left ( [T::name] , 2 )"),
    # a month offset can be negative: truncate toward zero both ways
    ("=EDATE([@day],[@amt])", "add_months ( [T::day] , if ( [T::amt] < 0 ) then ceil ( "
                              "[T::amt] ) else floor ( [T::amt] ) )"),
    ("=EDATE([@day],-1.5)", "add_months ( [T::day] , - 1 )"),
])
def test_integer_slot(src, expected):
    assert f(src) == expected


# ---------------------------------------------------------------------------
# BL-354: IF / IFERROR branches of different types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ('=IFERROR([@qty]/[@amt],"n/a")',
     "if ( [T::amt] = 0 ) then 'n/a' else to_string ( [T::qty] / [T::amt] )"),
    ('=IFERROR(1/0,"none")', "if ( 0 = 0 ) then 'none' else to_string ( 1 / 0 )"),
    ('=IFERROR(VALUE([@name]),"bad")', "ifnull ( to_string ( to_double ( [T::name] ) ) , 'bad' )"),
    ('=IF([@qty]>1,[@qty],"small")',
     "if ( [T::qty] > 1 ) then to_string ( [T::qty] ) else 'small'"),
    ('=IF([@qty]>1,[@flag],"none")',
     "if ( [T::qty] > 1 ) then ( if ( [T::flag] ) then 'TRUE' else 'FALSE' ) else 'none'"),
    ('=IF([@qty]>1,TRUE,0)', "if ( [T::qty] > 1 ) then 1 else 0"),
    ('=IF([@qty]>1,"many",FALSE)', "if ( [T::qty] > 1 ) then 'many' else 'FALSE'"),
])
def test_branches_share_one_type(src, expected):
    r = ok(src)
    assert r.expr == expected and r.status == "APPROXIMATED"
    assert any("branches of different types" in t for t in r.traps)


def test_date_beside_text_branch_is_needs_review():
    assert review('=IF([@qty]>1,[@day],"none")').startswith("type check:")


def test_same_type_branches_are_untouched():
    r = ok('=IFERROR([@qty]/[@amt],-1)')
    assert r.expr == "if ( [T::amt] = 0 ) then - 1 else [T::qty] / [T::amt]"
    assert not any("branches of different types" in t for t in r.traps)
