"""The Excel coverage pass (fidelity M1, 2026-10-07): rules for the functions that blocked the
most NEEDS_REVIEW cases, one block per family.

Every formula and value here is written for these tests — none is copied from the M1 corpus
(outside the repo, tools/formula-fidelity/README.md). Each block pins the emitted form, checks a
composition by value where it is arithmetic, and the type checker that none of it can fail
ThoughtSpot's import. The live facts each rule rests on are in the probe record §7
(docs/reviews/2026-10-06-formula-semantics-probes.md).
"""
from __future__ import annotations

import json
import math

import pytest

from ts_cli.excel.helpers import from_text
from ts_cli.excel.translate import translate_excel
from ts_cli.excel.typecheck import check, type_of_data_type
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json

TYPES = {"amt": "DOUBLE", "qty": "INT64", "name": "VARCHAR", "day": "DATE",
         "flag": "BOOLEAN", "stamp": "DATE_TIME"}
COLUMNS = json.dumps({c: {"table": "T", "column": c, "data_type": t} for c, t in TYPES.items()})


def tx(src):
    return translate_excel(src, ColumnContext(parse_columns_json(COLUMNS), level=1))


def ok(src, status=None):
    r = tx(src)
    assert r.expr is not None, r.notes
    errs = check(from_text(r.expr), lambda n: type_of_data_type(TYPES.get(n.get("column"))))[0]
    assert errs == [], (r.expr, errs)
    if status:
        assert r.status == status, (r.status, r.traps)
    return r


def f(src, status=None):
    return ok(src, status).expr


def review(src):
    r = tx(src)
    assert r.status == "NEEDS_REVIEW" and r.expr is None, r.expr
    return r.notes[-1]


def ev(text: str, row: dict = None):
    """Evaluate the emitted ThoughtSpot text over literals (and ``row`` for columns), as the
    warehouse would: enough to check a composition by value."""
    row = row or {}
    fns = {"ceil": math.ceil, "floor": math.floor, "abs": abs, "ln": math.log,
           "log10": math.log10, "log2": math.log2, "round": lambda x, inc: inc * round(x / inc),
           "concat": lambda *a: "".join(a), "left": lambda s, k: s[:max(int(k), 0)],
           "right": lambda s, k: s[len(s) - int(k):] if k else "", "strlen": len,
           "substr": lambda s, b, k: s[int(b):int(b) + int(k)],
           "mod": lambda a, b: None if b == 0 else math.fmod(a, b)}
    ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
           "/": lambda a, b: None if b == 0 else a / b, "<": lambda a, b: a < b,
           ">=": lambda a, b: a >= b, "=": lambda a, b: a == b, ">": lambda a, b: a > b,
           "and": lambda a, b: a and b, "or": lambda a, b: a or b}

    def go(n):
        k = n["node"]
        if k == "lit":
            if n["kind"] == "string":
                return n["value"][1:-1].replace("''", "'")
            return float(n["value"])
        if k in ("col", "ref"):
            return row[n.get("column") or n["name"]]
        if k == "unop":
            return -go(n["operand"])
        if k == "binop":
            return ops[n["op"]](go(n["left"]), go(n["right"]))
        if k == "call":
            return fns[n["fn"]](*[go(a) for a in n["args"]])
        if k == "ifelse":
            for cond, value in n["branches"]:
                if go(cond):
                    return go(value)
            return go(n["else"])
        raise ValueError(k)
    return go(from_text(text))


# ---------------------------------------------------------------------------
# Rounding family: FLOOR.MATH, *.PRECISE, ISO.CEILING, TRUNC, EVEN, ODD, QUOTIENT
# ---------------------------------------------------------------------------

class TestRoundingFamily:
    @pytest.mark.parametrize("src,want", [
        ("=FLOOR.MATH(-8.6,4)", -12), ("=FLOOR.MATH(-8.6,4,1)", -8), ("=FLOOR.MATH(8.6,-4)", 8),
        ("=FLOOR.MATH(8.6)", 8), ("=FLOOR.MATH(8.6,0)", 0), ("=FLOOR.MATH(-8.6,,1)", -8),
        ("=CEILING.PRECISE(-8.6,4)", -8), ("=CEILING.PRECISE(8.6,-4)", 12),
        ("=CEILING.PRECISE(8.6)", 9), ("=CEILING.PRECISE(8.6,0)", 0),
        ("=ISO.CEILING(-8.6,-4)", -8), ("=ISO.CEILING(8.2)", 9),
        ("=FLOOR.PRECISE(-8.6,4)", -12), ("=FLOOR.PRECISE(8.6,-4)", 8),
        ("=FLOOR.PRECISE(-8.6)", -9),
    ])
    def test_by_value(self, src, want):
        assert ev(f(src, "TRANSLATED")) == want

    def test_mode_and_sign_on_a_column(self):
        e = f("=FLOOR.MATH([@amt],[@qty],1)")
        assert "abs ( [T::qty] )" in e and e.startswith("if ( [T::qty] = 0 ) then 0 else")
        assert ev(e, {"amt": -8.6, "qty": -4}) == -8 and ev(e, {"amt": 8.6, "qty": -4}) == 8
        assert "round ( [T::amt] / abs ( [T::qty] ) , 0.000000001 )" in e   # DOUBLE snap

    def test_non_literal_mode_is_refused(self):
        assert "non-literal mode" in review("=FLOOR.MATH([@amt],2,[@qty])")

    @pytest.mark.parametrize("src,want", [
        ("=TRUNC(-6.87)", -6), ("=TRUNC(6.87)", 6), ("=TRUNC(-6.87,1)", -6.8),
        ("=TRUNC(687.5,-2)", 600), ("=TRUNC(6.871,)", 6),
    ])
    def test_trunc(self, src, want):
        assert ev(f(src, "TRANSLATED")) == pytest.approx(want, abs=1e-12)

    def test_trunc_is_rounddown(self):
        assert f("=TRUNC([@amt],2)") == f("=ROUNDDOWN([@amt],2)")
        assert "non-literal digit count" in review("=TRUNC([@amt],[@qty])")

    @pytest.mark.parametrize("x,even,odd", [
        (0, 0, 1), (1, 2, 1), (2, 2, 3), (2.3, 4, 3), (-2.3, -4, -3), (-1, -2, -1),
        (-4, -4, -5), (6.0001, 8, 7),
    ])
    def test_even_odd(self, x, even, odd):
        assert ev(f(f"=EVEN({x})")) == even
        assert ev(f(f"=ODD({x})")) == odd

    @pytest.mark.parametrize("a,b,want", [(23, 4, 5), (-23, 4, -5), (23, -4, -5), (3, 7, 0),
                                          (0, -7, 0)])
    def test_quotient_truncates_toward_zero(self, a, b, want):
        assert ev(f(f"=QUOTIENT({a},{b})")) == want

    def test_quotient_zero_divisor_is_null(self):
        assert any("#DIV/0!" in n for n in tx("=QUOTIENT([@amt],[@qty])").notes)


# ---------------------------------------------------------------------------
# Logarithms, trigonometry, hyperbolic, angles, factorial
# ---------------------------------------------------------------------------

class TestMath:
    def test_log_bases(self):
        assert f("=LOG([@amt])") == "log10 ( [T::amt] )"
        assert f("=LOG([@amt],10)") == "log10 ( [T::amt] )"
        assert f("=LOG([@amt],2)") == "log2 ( [T::amt] )"
        assert f("=LOG([@amt],[@qty])") == "ln ( [T::amt] ) / ln ( [T::qty] )"
        assert ev(f("=LOG(625,5)")) == pytest.approx(4, rel=1e-15)

    @pytest.mark.parametrize("name", ["SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN"])
    def test_trig_is_radians_on_both_sides(self, name):
        # probe record §7: sin ( 30 ) compiles to SIN(30); no degree conversion
        assert f(f"={name}([@amt])", "TRANSLATED") == f"{name.lower()} ( [T::amt] )"

    def test_atan2_swaps_operands(self):
        r = ok("=ATAN2([@amt],[@qty])")
        assert r.expr == 'sql_double_op ( "ATAN2({0}, {1})" , [T::qty] , [T::amt] )'
        assert any("ATAN2(0, 0)" in t for t in r.traps)

    @pytest.mark.parametrize("name", ["SINH", "COSH", "TANH", "ASINH", "ACOSH", "ATANH",
                                      "DEGREES", "RADIANS"])
    def test_hyperbolic_and_angles_pass_through(self, name):
        assert f(f"={name}([@amt])", "TRANSLATED") == \
            f'sql_double_op ( "{name}({{0}})" , [T::amt] )'

    def test_pi(self):
        assert f("=PI()") == 'sql_double_op ( "PI()" )'
        # ThoughtSpot reads a * b / c as a * ( b / c ) — the product is bracketed
        assert f("=[@amt]*180/PI()") == '( [T::amt] * 180 ) / sql_double_op ( "PI()" )'
        assert f("=DEGREES(PI()/4)").startswith('sql_double_op ( "DEGREES({0})"')

    def test_fact(self):
        assert f("=FACT(7.9)", "TRANSLATED") == \
            'sql_double_op ( "FACTORIAL(FLOOR({0}))" , 7.9 )'
        r = ok("=FACT([@qty])", "APPROXIMATED")
        assert any("FAILS THE WHOLE QUERY" in t for t in r.traps)
        assert "#NUM!" in review("=FACT(-2)")
        assert "above 33" in review("=FACT(40)")


# ---------------------------------------------------------------------------
# Character codes, REPLACE, the byte variants, FIND / SEARCH start_num
# ---------------------------------------------------------------------------

class TestText:
    def test_char(self):
        assert f("=CHAR(72)", "TRANSLATED") == 'sql_string_op ( "CHR({0})" , 72 )'
        assert ok("=CHAR(201)", "TRANSLATED")
        assert ok("=CHAR(140)", "APPROXIMATED").traps      # Windows-1252 differs at 128–159
        assert ok("=CHAR([@qty])", "APPROXIMATED")
        assert f("=CHAR([@amt])") == 'sql_string_op ( "CHR({0})" , floor ( [T::amt] ) )'
        assert "#VALUE!" in review("=CHAR(0)") and "#VALUE!" in review("=CHAR(300)")

    def test_unichar(self):
        assert f("=UNICHAR(9731)", "TRANSLATED") == 'sql_string_op ( "CHR({0})" , 9731 )'
        assert "#VALUE!" in review("=UNICHAR(0)")

    def test_code_uses_unicode_not_ascii(self):
        # Snowflake ASCII returns the first UTF-8 byte (195 for é); UNICODE the code point
        assert f('=CODE("Hz")', "TRANSLATED") == 'sql_int_op ( "UNICODE({0})" , \'Hz\' )'
        assert ok('=CODE("œuf")', "APPROXIMATED")           # Windows-1252 156
        assert ok("=CODE([@name])", "APPROXIMATED")
        assert f("=UNICODE([@name])", "TRANSLATED") == \
            'sql_int_op ( "UNICODE({0})" , [T::name] )'
        assert "#VALUE!" in review('=CODE("")')

    @pytest.mark.parametrize("s,start,k,new", [
        ("wombat", 2, 3, "XY"), ("wombat", 1, 1, ""), ("wombat", 7, 0, "!"),
        ("wombat", 4, 0, "-"), ("wombat", 30, 2, "end"), ("", 3, 1, "Z"), ("wombat", 1, 9, "q"),
    ])
    def test_replace_by_value(self, s, start, k, new):
        want = s[:start - 1] + new + s[start - 1 + k:]
        assert ev(f(f'=REPLACE("{s}",{start},{k},"{new}")', "TRANSLATED")) == want
        e = f(f'=REPLACE([@name],[@qty],{k},"{new}")')
        assert ev(e, {"name": s, "qty": start}) == want

    def test_replace_is_positional_not_sql_replace(self):
        e = f('=REPLACE([@name],2,3,"ab")')
        assert e == ("concat ( left ( [T::name] , 1 ) , 'ab' , substr ( [T::name] , 4 , "
                     "strlen ( [T::name] ) ) )")
        assert "REPLACE(" not in e
        assert "#VALUE!" in review('=REPLACE([@name],0,1,"x")')

    @pytest.mark.parametrize("b,plain", [("LEFTB([@name],3)", "LEFT([@name],3)"),
                                         ("RIGHTB([@name],3)", "RIGHT([@name],3)"),
                                         ("MIDB([@name],2,3)", "MID([@name],2,3)"),
                                         ("LENB([@name])", "LEN([@name])"),
                                         ('FINDB("q",[@name])', 'FIND("q",[@name])'),
                                         ('SEARCHB("q",[@name])', 'SEARCH("q",[@name])'),
                                         ('REPLACEB([@name],2,1,"q")', 'REPLACE([@name],2,1,"q")')])
    def test_byte_variants(self, b, plain):
        r = ok("=" + b, "APPROXIMATED")
        assert r.expr == tx("=" + plain).expr
        assert any("DBCS" in t for t in r.traps)

    def test_find_search_start(self):
        assert f('=FIND("q",[@name],4)') == \
            'sql_int_op ( "POSITION({0}, {1}, {2})" , \'q\' , [T::name] , 4 )'
        assert f('=SEARCH("q",[@name],[@amt])') == (
            'sql_int_op ( "POSITION(LOWER({0}), LOWER({1}), {2})" , \'q\' , [T::name] , '
            'floor ( [T::amt] ) )')
        assert "below 1" in review('=FIND("q",[@name],0)')
        assert "wildcards" in review('=SEARCH("q*",[@name],2)')


# ---------------------------------------------------------------------------
# TEXT format codes (the exact subset)
# ---------------------------------------------------------------------------

class TestTextFormat:
    @pytest.mark.parametrize("fmt,sf", [
        ("0", "FM" + "9" * 29 + "0"), ("0.000", "FM" + "9" * 29 + "0.000"),
        ("0000", "FM" + "9" * 26 + "0000"), ("#0.0", "FM" + "9" * 29 + "0.0"),
        ("#,##0", "FM999,999,999,999,999,999,999,999,999,990"),
        ("#,##0.0", "FM999,999,999,999,999,999,999,999,999,990.0"),
    ])
    def test_number_formats(self, fmt, sf):
        r = ok(f'=TEXT([@amt],"{fmt}")', "APPROXIMATED")      # the negative-zero trap
        assert r.expr == f'sql_string_op ( "TO_CHAR({{0}}, \'{sf}\')" , [T::amt] )'
        assert f(f'=TEXT(41.5,"{fmt}")', "TRANSLATED")

    def test_percent(self):
        assert f('=TEXT(0.4271,"0.0%")', "TRANSLATED") == (
            'sql_string_op ( "TO_CHAR({0} * 100, \'FM' + "9" * 29 + '0.0\') || \'%\'" , 0.4271 )')

    def test_text_operand(self):
        assert f('=TEXT("pear","0.00")') == "'pear'"            # not a number: unchanged
        assert f('=TEXT("12.5","0.00")', "TRANSLATED").endswith(", 12.5 )")
        assert "unknown type" in review('=TEXT(A1,"0.00")')

    @pytest.mark.parametrize("fmt", ["#.##", "$#,##0.00", "0.00E+00", "# ?/?", "[Red]0",
                                     "0;(0)", "m/d/yy", "h:mm AM/PM", "dddd d mmmm", "General"])
    def test_outside_the_subset_is_refused(self, fmt):
        review(f'=TEXT([@amt],"{fmt}")' if fmt[0] in "#$0[G" else f'=TEXT([@day],"{fmt}")')

    def test_negative_rounding_to_zero_literal_is_refused(self):
        assert "minus sign" in review('=TEXT(-0.004,"0.00")')

    @pytest.mark.parametrize("fmt,sf", [
        ("yyyy-mm-dd", "YYYY-MM-DD"), ("dd/mm/yy", "DD/MM/YY"), ("mmm yyyy", "MON YYYY"),
        ("mmmm", "MMMM"), ("ddd dd.mm.yyyy", "DY DD.MM.YYYY"),
        ("yyyy-mm-dd hh:mm:ss", "YYYY-MM-DD HH24:MI:SS"), ("hh:mm", "HH24:MI"),
        ("YYYY-MM-DD", "YYYY-MM-DD"),
    ])
    def test_date_formats(self, fmt, sf):
        assert f(f'=TEXT([@day],"{fmt}")', "TRANSLATED") == \
            f'sql_string_op ( "TO_CHAR({{0}}, \'{sf}\')" , [T::day] )'

    def test_full_day_name(self):
        # day_of_week is lower case ('friday', live) — INITCAP restores Excel's 'Friday'
        assert f('=TEXT([@day],"dddd")') == \
            'sql_string_op ( "INITCAP({0})" , day_of_week ( [T::day] ) )'

    def test_date_text_and_serial_operands(self):
        assert "to_date ( '2023-07-09'" in f('=TEXT("2023-07-09","yyyy")')
        assert "add_days" in f('=TEXT([@qty],"yyyy-mm-dd")')


# ---------------------------------------------------------------------------
# DATE
# ---------------------------------------------------------------------------

class TestDate:
    @pytest.mark.parametrize("src,iso", [
        ("=DATE(2031,7,4)", "2031-07-04"), ("=DATE(2031,15,4)", "2032-03-04"),
        ("=DATE(2031,1,0)", "2030-12-31"), ("=DATE(2032,3,0)", "2032-02-29"),
        ("=DATE(2031,-1,10)", "2030-11-10"), ("=DATE(2031,2,-3)", "2031-01-28"),
        ("=DATE(31,5,6)", "1931-05-06"), ("=DATE(2031.8,6.9,5.2)", "2031-06-05"),
        ("=DATE(2031,,8)", "2030-12-08"),
    ])
    def test_literal_parts_fold(self, src, iso):
        assert f(src, "TRANSLATED") == f"to_date ( '{iso}' , '%Y-%m-%d' )"

    @pytest.mark.parametrize("src", ["=DATE(-3,1,1)", "=DATE(10000,1,1)", "=DATE(1900,1,5)",
                                     "=DATE(0,1,1)", "=DATE(9999,12,32)"])
    def test_outside_excels_calendar_is_refused(self, src):
        review(src)

    def test_column_parts(self):
        e = f("=DATE([@qty],[@qty],1)")
        assert e == ("add_months ( to_date ( concat ( to_string ( if ( [T::qty] < 1900 ) then "
                     "[T::qty] + 1900 else [T::qty] ) , '-01-01' ) , '%Y-%m-%d' ) , "
                     "[T::qty] - 1 )")
        assert f("=DATE(2031,[@qty],[@qty])") == (
            "add_days ( add_months ( to_date ( '2031-01-01' , '%Y-%m-%d' ) , [T::qty] - 1 ) , "
            "[T::qty] - 1 )")
        assert "floor ( [T::amt] )" in f("=DATE([@amt],1,1)")


# ---------------------------------------------------------------------------
# ISTEXT / ISNONTEXT / ISLOGICAL
# ---------------------------------------------------------------------------

class TestTypeTests:
    @pytest.mark.parametrize("src,want", [
        ("=ISTEXT([@name])", "not ( isnull ( [T::name] ) )"), ("=ISTEXT([@amt])", "false"),
        ('=ISTEXT("x")', "true"), ("=ISNONTEXT([@name])", "isnull ( [T::name] )"),
        ("=ISNONTEXT([@day])", "true"), ("=ISLOGICAL([@flag])", "not ( isnull ( [T::flag] ) )"),
        ("=ISLOGICAL([@qty])", "false"), ("=ISLOGICAL(1 > 0)", "true"),
    ])
    def test_resolved_from_type(self, src, want):
        assert f(src) == want

    def test_unknown_type_is_refused(self):
        assert "unknown type" in review("=ISTEXT(K7)")


# ---------------------------------------------------------------------------
# Two printer facts found by the coverage run (probe record §7, live 2026-10-07)
# ---------------------------------------------------------------------------

class TestPrinter:
    def test_quote_is_printed_as_a_warehouse_literal(self):
        # 'it''s' is read as it''s, and 'it\'s' fails to parse after another string literal
        e = f('=CONCAT("Bob","\'s ",[@name])')
        assert e == "concat ( 'Bob' , sql_string_op ( \"'''s '\" ) , [T::name] )"
        assert f('=CONCAT("a\\b","!")') == "concat ( 'a\\\\b' , '!' )"
        assert "cannot carry" in review('=CONCAT("say ""hi"", it\'s",[@name])')
        assert "cannot carry" in review('=CONCAT("it\\\'s",[@name])')     # backslash + quote
        assert "cannot carry" in review('=CONCAT("{it\'s}",[@name])')
        from ts_cli.excel.tsast import lit_string, string_text
        for text in ("it's", "a\\b", "''", "plain"):
            assert string_text(lit_string(text)["value"]) == text
        assert string_text("'it\\'s'") == "it's"

    def test_product_is_bracketed_under_a_division(self):
        # ThoughtSpot compiled [n] * 4 / 3 as n * (4 / 3) = 3.999999 for n = 3
        assert f("=[@qty]*4/3") == "( [T::qty] * 4 ) / 3"
        assert f("=[@qty]/4*3") == "[T::qty] / 4 * 3"
        assert f("=[@qty]*(4/3)") == "[T::qty] * ( 4 / 3 )"


# ---------------------------------------------------------------------------
# Integer operands: no fixed-point division (review of #577)
# ---------------------------------------------------------------------------

class TestIntegerDivision:
    """Snowflake divides two NUMBER(38,0) values at scale 6: QUOTIENT(1999999, 2000000) gave 1.
    Integer operands use the remainder form; two literals fold."""

    @pytest.mark.parametrize("a,b", [(1999999, 2000000), (-1999999, 2000000), (1999999, -2000000),
                                     (23, 4), (-23, 4), (23, -4), (-23, -4), (0, 7), (28, 7),
                                     (-28, 7)])
    def test_by_value(self, a, b):
        cols = {"qty": a}
        trunc = (abs(a) // abs(b)) * (1 if (a < 0) == (b < 0) else -1)
        sb = abs(b)
        assert ev(f(f"=QUOTIENT([@qty],{b})"), cols) == trunc
        assert ev(f(f"=QUOTIENT({a},{b})")) == trunc            # folded
        assert ev(f(f"=FLOOR([@qty],{b})"), cols) == (a // b) * b
        assert ev(f(f"=CEILING([@qty],{b})"), cols) == -((-a) // b) * b
        assert ev(f(f"=FLOOR.MATH([@qty],{b})"), cols) == (a // sb) * sb
        assert ev(f(f"=CEILING.PRECISE([@qty],{b})"), cols) == -((-a) // sb) * sb
        assert ev(f(f"=FLOOR.MATH([@qty],{b},1)"), cols) == (
            -((-a) // sb) * sb if a < 0 else (a // sb) * sb)
        for src in ("FLOOR.MATH([@qty],{b})", "CEILING([@qty],{b})", "QUOTIENT([@qty],{b})"):
            e = f("=" + src.format(b=b))
            assert "/" not in e or e.endswith(f"/ {b}") or e.endswith(f"/ - {abs(b)}"), e

    def test_literals_fold(self):
        assert f("=QUOTIENT(1999999,2000000)") == "0"
        assert f("=FLOOR.PRECISE(-1999999,2000000)") == "- 2000000"
        assert "#DIV/0!" in review("=QUOTIENT([@qty],0)")

    def test_decimal_column_is_trapped(self):
        import json as _json
        cols = _json.dumps({"dec": {"table": "T", "column": "dec", "data_type": "DECIMAL"}})
        r = translate_excel("=QUOTIENT([@dec],3)",
                            ColumnContext(parse_columns_json(cols), level=1))
        assert r.status == "APPROXIMATED" and any("scale 6" in t for t in r.traps)
