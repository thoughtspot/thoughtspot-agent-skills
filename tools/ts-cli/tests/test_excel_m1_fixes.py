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
