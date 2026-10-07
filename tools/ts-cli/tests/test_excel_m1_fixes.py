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


def ts_eval(text: str):
    """A tiny evaluator for the emitted arithmetic (literals only): enough to check a
    composition by value, as the warehouse would compute it."""
    import math

    fns = {"ceil": math.ceil, "floor": math.floor, "abs": abs}
    ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
           "/": lambda a, b: None if b == 0 else a / b, "<": lambda a, b: a < b,
           ">=": lambda a, b: a >= b, "=": lambda a, b: a == b, ">": lambda a, b: a > b}

    def ev(n):
        k = n["node"]
        if k == "lit":
            return float(n["value"])
        if k == "unop":
            return -ev(n["operand"])
        if k == "binop":
            return ops[n["op"]](ev(n["left"]), ev(n["right"]))
        if k == "call":
            return fns[n["fn"]](*[ev(a) for a in n["args"]])
        if k == "ifelse":
            for cond, value in n["branches"]:
                if ev(cond):
                    return ev(value)
            return ev(n["else"])
        raise ValueError(k)
    return ev(from_text(text))


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


@pytest.mark.parametrize("src", ["=DAY(-0)", "=DAY(60)", "=YEAR(-5)"])
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
    ("=SEARCH(7,1234567)", "strpos ( '1234567' , '7' )"),  # literals folded to their text
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
    ("=CEILING([@name],1)", "ceil ( round ( to_double ( [T::name] ) / 1 , 0.000000001 ) ) * 1"),
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
    # the fold assumes the cell type: APPROXIMATED, with the assumption named (review #574)
    assert r.status == "APPROXIMATED"
    assert any("folded to the constant" in t and "blank cell" in t for t in r.traps)


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
    ('=IFERROR(VALUE([@name]),"bad")',
     'ifnull ( to_string ( sql_double_op ( "TRY_TO_DOUBLE({0})" , [T::name] ) ) , \'bad\' )'),
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


# ---------------------------------------------------------------------------
# BL-346 / BL-347: CEILING, CEILING.MATH and a zero significance
# ---------------------------------------------------------------------------
# Excel's documented behaviour, restated: CEILING.MATH ignores the significance's sign; a
# positive number rounds up to the next multiple; a negative number rounds toward zero by
# default and away from zero when mode is non-zero; significance 0 gives 0.

def _ceiling_math(x, s=1, mode=0):
    import math
    step = abs(s)
    if step == 0:
        return 0
    if x < 0 and mode:
        return math.floor(x / step) * step
    return math.ceil(x / step) * step


@pytest.mark.parametrize("x", [7.3, -7.3, 6, -6, 0.5, -0.5])
@pytest.mark.parametrize("s", [2, -2, 0.5, -0.5])
@pytest.mark.parametrize("mode", [None, 0, 1, -1])
def test_ceiling_math_every_sign_and_mode(x, s, mode):
    """Evaluate the emitted form on literals and compare with the documented rule."""
    args = f"{x},{s}" + ("" if mode is None else f",{mode}")
    expr = f(f"=CEILING.MATH({args})")
    assert ts_eval(expr) == pytest.approx(_ceiling_math(x, s, mode or 0))


@pytest.mark.parametrize("args,expected", [
    # the worked examples on Microsoft's CEILING.MATH page
    ("24.3,5", 25), ("6.7", 7), ("-8.1,2", -8), ("-5.5,2,-1", -6),
])
def test_ceiling_math_documented_examples(args, expected):
    assert ts_eval(f(f"=CEILING.MATH({args})")) == expected


def test_ceiling_math_emitted_forms():
    # integer columns: no division (Snowflake divides integers at scale 6) — the remainder
    # form, checked by value in test_excel_coverage.py::TestIntegerDivision
    e = f("=CEILING.MATH([@qty],[@qty])")
    assert e.startswith("if ( [T::qty] = 0 ) then 0 else [T::qty] - mod ( [T::qty] , "
                        "abs ( [T::qty] ) )") and "/" not in e
    e = f("=CEILING.MATH([@qty],-2,1)")
    assert e.startswith("if ( [T::qty] < 0 ) then [T::qty] - ( if ( mod ( [T::qty] , 2 ) < 0 )")
    assert f("=CEILING.MATH([@qty])") == "ceil ( [T::qty] )"
    assert f("=CEILING.MATH([@qty],,1)") == (
        "if ( [T::qty] < 0 ) then floor ( [T::qty] ) else ceil ( [T::qty] )")
    assert f("=CEILING.MATH([@amt],-2,1)") == (
        "if ( [T::amt] < 0 ) then floor ( round ( [T::amt] / 2 , 0.000000001 ) ) * 2 else "
        "ceil ( round ( [T::amt] / 2 , 0.000000001 ) ) * 2")
    assert "non-literal mode" in review("=CEILING.MATH([@amt],2,[@qty])")


def test_zero_significance():
    assert f("=CEILING([@qty],[@qty])").startswith("if ( [T::qty] = 0 ) then 0 else ")
    assert f("=CEILING([@amt],0)") == "0"
    assert "/" not in f("=CEILING([@qty],2)")
    # FLOOR with 0 is #DIV/0! in Excel: NULL stands for the error — guarded, because mod by
    # zero fails the whole query in Snowflake (live 2026-10-07)
    assert f("=FLOOR([@qty],[@qty])").startswith("if ( [T::qty] = 0 ) then null else ")


# ---------------------------------------------------------------------------
# BL-348: ROUNDUP / ROUNDDOWN beyond 6 digits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("=ROUNDUP([@qty],9)", "if ( [T::qty] >= 0 ) then ceil ( [T::qty] * 1000000000 ) * "
                           "0.000000001 else floor ( [T::qty] * 1000000000 ) * 0.000000001"),
    ("=ROUNDDOWN([@qty],1)", "if ( [T::qty] >= 0 ) then floor ( [T::qty] * 10 ) * 0.1 else "
                             "ceil ( [T::qty] * 10 ) * 0.1"),
    ("=ROUNDDOWN([@qty],-2)", "if ( [T::qty] >= 0 ) then floor ( [T::qty] / 100 ) * 100 else "
                              "ceil ( [T::qty] / 100 ) * 100"),
])
def test_rounding_multiplies_by_the_increment(src, expected):
    """No integer division (Snowflake keeps a quotient at scale 6)."""
    assert f(src) == expected


@pytest.mark.parametrize("x,digits,expected", [
    (3.14159265358979, 10, 3.1415926536), (-3.14159265358979, 10, -3.1415926536),
    (2.5, 0, 3), (1234.5, -2, 1300),
])
def test_roundup_by_value(x, digits, expected):
    assert ts_eval(f(f"=ROUNDUP({x},{digits})")) == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------------------
# BL-349: a boolean joined into text reads TRUE / FALSE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ('="is "&([@qty]>2)', "concat ( 'is ' , if ( [T::qty] > 2 ) then 'TRUE' else 'FALSE' )"),
    ('=CONCAT([@flag],"!")', "concat ( if ( [T::flag] ) then 'TRUE' else 'FALSE' , '!' )"),
    ('="x"&TRUE', "concat ( 'x' , 'TRUE' )"),
    ("=LEN([@flag])", "strlen ( if ( [T::flag] ) then 'TRUE' else 'FALSE' )"),
])
def test_boolean_in_text(src, expected):
    r = ok(src)
    assert r.expr == expected and r.status == "TRANSLATED"


# ---------------------------------------------------------------------------
# BL-350: a date where text is expected is its serial number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("=UPPER([@day])", f'sql_string_op ( "UPPER({{0}})" , to_string ( diff_days ( [T::day] , '
                       f'{EPOCH} ) ) )'),
    ("=LEN([@day])", f"strlen ( to_string ( diff_days ( [T::day] , {EPOCH} ) ) )"),
    ('="on "&[@day]', f"concat ( 'on ' , to_string ( diff_days ( [T::day] , {EPOCH} ) ) )"),
])
def test_date_in_text_is_the_serial(src, expected):
    r = ok(src)
    assert r.expr == expected
    assert any("serial" in n for n in r.notes) and any("1899-12-30" in t for t in r.traps)


def test_datetime_in_text_is_needs_review():
    assert "time fraction" in review("=LEFT([@stamp],4)")


# ---------------------------------------------------------------------------
# BL-351: constant decimal arithmetic — a documented platform divergence
# ---------------------------------------------------------------------------

def test_constant_decimal_arithmetic_carries_the_divergence_trap():
    r = ok("=-1234+1233.7")
    assert r.status == "TRANSLATED"            # documented, not a translation error
    assert any(t.startswith("constant decimal arithmetic (BL-351)") for t in r.traps)
    assert not any("BL-351" in t for t in ok("=[@amt]+0.5").traps)
    assert not any("BL-351" in t for t in ok("=2+3").traps)


# ---------------------------------------------------------------------------
# Review fix 1: a DOUBLE is snapped before ceil / floor (binary representation error)
# ---------------------------------------------------------------------------

def ts_eval_with(text: str, amt: float):
    """ts_eval with [T::amt] bound to a Python float (IEEE double, as the warehouse holds a
    DOUBLE) and round ( x , inc ) as ThoughtSpot compiles it (inc * round ( x / inc ))."""
    import math
    from decimal import Decimal

    def rnd(x, inc):
        return inc * round(x / inc)
    fns = {"ceil": math.ceil, "floor": math.floor, "abs": abs, "round": rnd}
    ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
           "/": lambda a, b: None if b == 0 else a / b, "<": lambda a, b: a < b,
           ">=": lambda a, b: a >= b, "=": lambda a, b: a == b}

    def ev(n):
        k = n["node"]
        if k == "lit":
            return float(Decimal(n["value"]))
        if k == "col":
            return amt
        if k == "unop":
            return -ev(n["operand"])
        if k == "binop":
            return ops[n["op"]](ev(n["left"]), ev(n["right"]))
        if k == "call":
            return fns[n["fn"]](*[ev(a) for a in n["args"]])
        if k == "ifelse":
            for cond, value in n["branches"]:
                if ev(cond):
                    return ev(value)
            return ev(n["else"])
        raise ValueError(k)
    return ev(from_text(text))


@pytest.mark.parametrize("src,amt,expected", [
    ("=ROUNDUP([@amt],2)", 1.1, 1.1), ("=ROUNDDOWN([@amt],2)", 0.29, 0.29),
    ("=ROUNDUP([@amt],2)", 0.57, 0.57), ("=ROUNDDOWN([@amt],2)", -0.57, -0.57),
    ("=ROUNDUP([@amt],2)", -1.1, -1.1), ("=ROUNDUP([@amt],0)", 2.0000000000000004, 2),
    ("=ROUNDUP([@amt],2)", 1.101, 1.11), ("=ROUNDDOWN([@amt],2)", 0.299, 0.29),
    ("=CEILING([@amt],0.1)", 1.1, 1.1), ("=FLOOR([@amt],0.1)", 0.3, 0.3),
    ("=CEILING.MATH([@amt],0.1)", 1.1, 1.1), ("=ROUNDDOWN([@amt],-1)", 70.0, 70),
])
def test_double_is_snapped_before_ceil_floor(src, amt, expected):
    r = ok(src)
    assert "round (" in r.expr and "0.000000001" in r.expr
    assert ts_eval_with(r.expr, amt) == pytest.approx(expected, rel=1e-12)


def test_the_raw_form_was_wrong():
    """The bug the snap fixes, pinned: without it, 1.1 rounds up to 1.11."""
    import math
    assert math.ceil(1.1 * 100) * 0.01 == pytest.approx(1.11)


def test_exact_inputs_are_not_snapped():
    assert "round" not in f("=ROUNDUP([@qty],2)")
    assert "round" not in f("=ROUNDUP(1.1,2)")          # literals are exact decimals


@pytest.mark.parametrize("src", ["=ROUNDUP([@amt],16)", "=ROUNDDOWN([@amt],20)",
                                 "=ROUNDUP([@amt],-16)"])
def test_more_than_15_digits_is_needs_review(src):
    assert "15 significant digits" in review(src)


# ---------------------------------------------------------------------------
# Review fix 3: a number as text — literals in Excel's General format, DOUBLEs downgraded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ('="n"&2.50', "concat ( 'n' , '2.5' )"), ('="n"&-3', "concat ( 'n' , '-3' )"),
    ('="n"&0.0005', "concat ( 'n' , '0.0005' )"), ("=LEN(12345)", "strlen ( '12345' )"),
])
def test_number_literal_as_excel_text(src, expected):
    r = ok(src)
    assert r.expr == expected and r.status == "TRANSLATED"


@pytest.mark.parametrize("src", ['="n"&1E+20', '="n"&0.00001', '="n"&1.23456789012345678'])
def test_number_literal_outside_plain_general_format_is_needs_review(src):
    assert "General format" in review(src)


def test_double_column_as_text_is_approximated():
    r = ok('=[@name]&[@amt]')
    assert r.expr == "concat ( [T::name] , to_string ( [T::amt] ) )"
    assert r.status == "APPROXIMATED"
    assert any("General format" in t and "95000.00" in t for t in r.traps)
    assert ok("=LEN([@amt])").status == "APPROXIMATED"
    assert ok("=LEN([@qty])").status == "TRANSLATED"      # integers render exactly


# ---------------------------------------------------------------------------
# Review fix 4: to_double FAILS THE QUERY on non-numeric text (live 2026-10-07)
# ---------------------------------------------------------------------------

def test_value_of_text():
    r = ok("=VALUE([@name])")
    assert r.expr == "to_double ( [T::name] )" and r.status == "APPROXIMATED"
    assert any("FAILS THE WHOLE QUERY" in t for t in r.traps)
    assert f('=VALUE("2.5")') == "2.5"


@pytest.mark.parametrize("src", ['=VALUE("abc")', '="abc"*2'])
def test_non_numeric_text_literal_is_needs_review_on_both_paths(src):
    assert "#VALUE!" in review(src)


def test_isnumber_and_iferror_of_value_use_try_to_double():
    assert f("=ISNUMBER(VALUE([@name]))") == (
        'sql_bool_op ( "TRY_TO_DOUBLE({0}) IS NOT NULL" , [T::name] )')
    assert f("=IFERROR(VALUE([@name]),0)") == (
        'ifnull ( sql_double_op ( "TRY_TO_DOUBLE({0})" , [T::name] ) , 0 )')


# ---------------------------------------------------------------------------
# Review fix 5: a slashed text date depends on the workbook's locale
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ('=MONTH("25/12/2020")', "month_number ( to_date ( '25/12/2020' , '%d/%m/%Y' ) )"),
    ('=MONTH("12/25/2020")', "month_number ( to_date ( '12/25/2020' , '%m/%d/%Y' ) )"),
    ('=MONTH("07/07/2020")', "month_number ( to_date ( '07/07/2020' , '%m/%d/%Y' ) )"),
])
def test_slashed_date_is_approximated_with_a_locale_trap(src, expected):
    r = ok(src)
    assert r.expr == expected and r.status == "APPROXIMATED"
    assert any("locale" in t and "#VALUE!" in t for t in r.traps)


def test_iso_date_stays_translated():
    r = ok('=YEAR("2015-02-11")')
    assert r.status == "TRANSLATED" and not any("locale" in t for t in r.traps)


def test_pre_1900_check_reads_the_date_not_the_string():
    assert "before 1900" in review('=DAY("31/12/1899")')       # day-first, year last
    r = ok('=DAY("1900-02-15")')                                 # real, but Excel's serial bug
    assert any("1899-12-30" in t for t in r.traps)
    assert not any("1899-12-30" in t for t in ok('=DAY("1900-03-01")').traps)


# ---------------------------------------------------------------------------
# Review fix 8 (low)
# ---------------------------------------------------------------------------

def test_untyped_column_beside_a_text_branch_asks_its_type():
    r = translate_excel('=IF([@c]>1,[@odate],"none")', ColumnContext())
    assert [t[1] for t in r.type_needs] == ["mixed branches"]
    assert r.type_needs[0][0].endswith("odate]")


def test_date_plus_a_double_column_floors_the_days():
    r = ok("=[@day]+[@amt]")
    assert r.expr == "add_days ( [T::day] , floor ( [T::amt] ) )"
    assert r.status == "APPROXIMATED" and any("whole days" in t for t in r.traps)
    assert f("=[@day]+[@qty]") == "add_days ( [T::day] , [T::qty] )"
