"""Unit tests for the Excel / Google Sheets ⇄ ThoughtSpot translator (ts_cli/excel/)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.excel_support import normalise
from ts_cli.excel import nodes as X
from ts_cli.excel.functions import HANDLERS, SHEETS_HANDLERS
from ts_cli.excel.helpers import from_text
from ts_cli.excel.map_index import EXCEL_ROWS, SHEETS_ROWS, cite
from ts_cli.excel.parser import ExcelSyntaxError, parse
from ts_cli.excel.rules import FUNCTION_RULES, SHEETS_RULES
from ts_cli.excel.to_excel import to_excel
from ts_cli.excel.translate import translate_excel
from ts_cli.excel.tsast import to_text, walk
from ts_cli.formula_translate.catalog import is_known
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
from ts_cli.formula_translate.engine import translate

_REPO = Path(__file__).resolve().parents[3]


def tx(src, role=None, dialect="excel", columns=None):
    ctx = ColumnContext(parse_columns_json(columns), level=1) if columns else ColumnContext()
    return translate_excel(src, ctx, dialect=dialect, role=role)


def f(src, **kw):
    r = tx(src, **kw)
    assert r.expr is not None, r.notes
    return r.expr


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TestParser:
    def test_structured_references(self):
        assert parse("[@Col]") == X.Ref("Col", "row", None, "structured", "[@Col]")
        assert parse("[@[Col Name]]").column == "Col Name"
        assert parse("[@[Col Name]]").grain == "row"
        r = parse("Sales[@Amount]")
        assert (r.table, r.column, r.grain) == ("Sales", "Amount", "row")
        r = parse("Sales[Amount]")
        assert (r.table, r.column, r.grain) == ("Sales", "Amount", "column")
        assert parse("[Amount]").grain == "column"
        r = parse("Sales[[#This Row],[Unit Price]]")
        assert (r.column, r.grain) == ("Unit Price", "row")
        assert parse("Sales[[#Data],[Amount]]").grain == "column"

    def test_structured_escape(self):
        assert parse("T[@[a'[1']]]").column == "a[1]"

    def test_a1_references(self):
        r = parse("B2")
        assert (r.kind, r.column, r.grain, r.absolute) == ("a1", "B", "row", False)
        assert parse("$B$2").absolute is True
        r = parse("B2:B100")
        assert (r.column, r.grain) == ("B", "column")
        assert parse("A:A").grain == "column"
        r = parse("Sheet1!C3")
        assert (r.sheet, r.column) == ("Sheet1", "C")
        assert parse("'My Sheet'!A:A").sheet == "My Sheet"

    def test_two_dimensional_range_rejected(self):
        assert parse("A1:C9").grain == "block" and parse("A:C").grain == "block"
        assert tx("=SUM(A1:C9)").status == "NEEDS_REVIEW"
        with pytest.raises(ExcelSyntaxError):
            parse("Sales[[Col1]:[Col2]]")

    def test_sheets_open_range(self):
        r = parse("A2:A")
        assert (r.column, r.grain) == ("A", "column")

    def test_literals_and_operators(self):
        node = parse('="a""b"&TRUE')
        assert node == X.Binary("&", X.Str('a"b'), X.Bool(True))
        assert parse("#N/A") == X.Err("#N/A")
        assert parse("-2^2") == X.Binary("^", X.Unary("-", X.Num("2")), X.Num("2"))
        assert parse("50%") == X.Percent(X.Num("50"))
        assert parse("1<>2").op == "<>"
        assert parse("1E3").text == "1E3"

    def test_precedence(self):
        node = parse("1+2*3&\"x\"=\"7x\"")
        assert node.op == "=" and node.left.op == "&" and node.left.left.op == "+"

    def test_functions_dotted_and_prefixed(self):
        assert parse("STDEV.S(A:A)").name == "STDEV.S"
        assert parse("_xlfn.CONCAT(A1,B1)").name == "CONCAT"
        assert parse("NETWORKDAYS.INTL(A1,B1,11)").name == "NETWORKDAYS.INTL"

    def test_array_constant_and_missing_argument(self):
        node = parse("{1,2;3,4}")
        assert node.rows == [[X.Num("1"), X.Num("2")], [X.Num("3"), X.Num("4")]]
        assert isinstance(parse("IF(A1,,1)").args[1], X.Missing)

    def test_errors(self):
        for bad in ("", "=", "SUM(1", "1 +", '"open', "1:1"):
            with pytest.raises(ExcelSyntaxError):
                parse(bad)


# ---------------------------------------------------------------------------
# Forward rules
# ---------------------------------------------------------------------------

FORWARD = [
    # arithmetic, references
    ("=[@a]+[@b]*2", "[TABLE::a] + [TABLE::b] * 2"),
    ("=([@a]+[@b])*2", "( [TABLE::a] + [TABLE::b] ) * 2"),
    ("=[@a]^2", "pow ( [TABLE::a] , 2 )"),
    ("=-[@a]", "- [TABLE::a]"),
    ("=[@a]*10%", "[TABLE::a] * ( 10 / 100 )"),
    ("=Sales[@Amount]", "[Sales::Amount]"),
    # aggregates (E5) and row-wise reducers (E7)
    ("=SUM(Sales[Amount])", "sum ( [Sales::Amount] )"),
    ("=SUM([@a],[@b],[@c])", "[TABLE::a] + [TABLE::b] + [TABLE::c]"),
    ("=MAX(0,[@a]-[@b])", "greatest ( 0 , [TABLE::a] - [TABLE::b] )"),
    ("=MIN([@a],[@b])", "least ( [TABLE::a] , [TABLE::b] )"),
    ("=MAX(B:B)", "max ( [TABLE::B] )"),
    ("=AVERAGE(Sales[x])", "average ( [Sales::x] )"),
    ("=AVERAGE([@a],[@b])", "( [TABLE::a] + [TABLE::b] ) / 2"),
    ("=COUNTA(Sales[x])", "count ( [Sales::x] )"),
    ("=STDEV.S(Sales[x])", "stddev ( [Sales::x] )"),
    ("=MEDIAN(Sales[x])", "median ( [Sales::x] )"),
    # criteria (E11)
    ('=SUMIFS(Sales[Amount],Sales[Region],"West")',
     "sum_if ( [Sales::Region] = 'West' , [Sales::Amount] )"),
    ('=SUMIF(Sales[x],">5")', "sum_if ( [Sales::x] > 5 , [Sales::x] )"),
    ('=COUNTIF(Sales[r],"<>West")',
     "count_if ( [Sales::r] != 'West' or isnull ( [Sales::r] ) , [Sales::r] )"),
    ('=COUNTIF(Sales[r],"*es*")', "count_if ( contains ( [Sales::r] , 'es' ) , [Sales::r] )"),
    ('=COUNTIF(Sales[r],"We*")', "count_if ( strpos ( [Sales::r] , 'We' ) = 1 , [Sales::r] )"),
    ('=AVERAGEIFS(T[v],T[a],">="&10)', "average_if ( [T::a] >= 10 , [T::v] )"),
    ('=MAXIFS(T[v],T[a],5)', "max_if ( [T::a] = 5 , [T::v] )"),
    # rounding (E12)
    ("=ROUND([@x],2)", "round ( [TABLE::x] , 0.01 )"),
    ("=ROUND([@x],0)", "round ( [TABLE::x] , 1 )"),
    ("=ROUND([@x],-2)", "round ( [TABLE::x] , 100 )"),
    ("=ROUNDUP([@x],2)",
     # an untyped column may be a DOUBLE: the scaled value is snapped (review fix 1)
     "if ( [TABLE::x] >= 0 ) then ceil ( round ( [TABLE::x] * 100 , 0.000000001 ) ) * 0.01 "
     "else floor ( round ( [TABLE::x] * 100 , 0.000000001 ) ) * 0.01"),
    ("=ROUNDDOWN([@x],0)", "if ( [TABLE::x] >= 0 ) then floor ( round ( [TABLE::x] , 0.000000001 ) ) "
     "else ceil ( round ( [TABLE::x] , 0.000000001 ) )"),
    ("=ROUNDUP(MONTH([@d])/3,0)", "quarter_number ( [TABLE::d] )"),
    ("=MROUND([@x],5)", "round ( [TABLE::x] , 5 )"),
    ("=INT([@x])", "floor ( [TABLE::x] )"),
    ("=MOD([@x],3)", "[TABLE::x] - 3 * floor ( [TABLE::x] / 3 )"),
    ("=CEILING([@x],5)", "ceil ( round ( [TABLE::x] / 5 , 0.000000001 ) ) * 5"),
    ("=CEILING.MATH([@x])", "ceil ( round ( [TABLE::x] , 0.000000001 ) )"),
    ("=POWER([@x],2)", "pow ( [TABLE::x] , 2 )"),
    # logic
    ('=IF([@a]>1,"x","y")', "if ( [TABLE::a] > 1 ) then 'x' else 'y'"),
    ('=IF([@a]>1,"x",IF([@a]>0,"y","z"))',
     "if ( [TABLE::a] > 1 ) then 'x' else if ( [TABLE::a] > 0 ) then 'y' else 'z'"),
    ('=IFS([@a]>1,"x",TRUE,"z")', "if ( [TABLE::a] > 1 ) then 'x' else 'z'"),
    ('=SWITCH([@r],"N","North","S","South","?")',
     "if ( [TABLE::r] = 'N' ) then 'North' else if ( [TABLE::r] = 'S' ) then 'South' else '?'"),
    ("=AND([@a]>1,[@b]<2,[@c]=3)", "[TABLE::a] > 1 and [TABLE::b] < 2 and [TABLE::c] = 3"),
    ("=OR([@a]>1,NOT([@b]))", "[TABLE::a] > 1 or not ( [TABLE::b] )"),
    ("=IF([@a]<>1,1,0)", "if ( [TABLE::a] != 1 ) then 1 else 0"),
    ("=ISBLANK([@a])", "isnull ( [TABLE::a] )"),
    ('=ISNUMBER(SEARCH("x",[@s]))', "contains ( [TABLE::s] , 'x' )"),
    ("=ISNUMBER(VALUE([@s]))", "not ( isnull ( to_double ( [TABLE::s] ) ) )"),
    ("=IFERROR([@a]/[@b],0)", "safe_divide ( [TABLE::a] , [TABLE::b] )"),
    ("=IFERROR([@a]/[@b],-1)", "if ( [TABLE::b] = 0 ) then -1 else [TABLE::a] / [TABLE::b]"),
    ("=IFERROR(VALUE([@s]),0)", "ifnull ( to_double ( [TABLE::s] ) , 0 )"),
    ("=IF([@b]=0,0,[@a]/[@b])", "safe_divide ( [TABLE::a] , [TABLE::b] )"),
    # text
    ('=[@a]&" "&[@b]', "concat ( [TABLE::a] , ' ' , [TABLE::b] )"),  # types unknown: bare
    ('=CONCAT("a",[@b])', "concat ( 'a' , [TABLE::b] )"),
    ('=TEXTJOIN("-",FALSE,"a","b")', "concat ( 'a' , '-' , 'b' )"),
    ('="FY"&2026', "concat ( 'FY' , '2026' )"),
    ("=LEFT([@s],3)", "left ( [TABLE::s] , 3 )"),
    ("=LEFT([@s])", "left ( [TABLE::s] , 1 )"),
    ("=MID([@s],2,3)", "substr ( [TABLE::s] , 1 , 3 )"),
    ("=LEN([@s])", "strlen ( [TABLE::s] )"),
    ('=SEARCH("x",[@s])', "strpos ( [TABLE::s] , 'x' )"),
    ('=FIND("x",[@s])', "sql_int_op ( \"POSITION({0} IN {1})\" , 'x' , [TABLE::s] )"),
    ('=EXACT([@a],"X")', "sql_bool_op ( \"{0} = {1}\" , [TABLE::a] , 'X' )"),
    ("=UPPER([@s])", "sql_string_op ( \"UPPER({0})\" , [TABLE::s] )"),
    ("=VALUE([@s])", "to_double ( [TABLE::s] )"),
    # dates
    ("=TODAY()", "today ( )"),
    ("=YEAR([@d])", "year ( [TABLE::d] )"),
    ("=MONTH([@d])", "month_number ( [TABLE::d] )"),
    ("=DAY([@d])", "day ( [TABLE::d] )"),
    ('=DATEDIF([@s],[@e],"D")', "diff_days ( [TABLE::e] , [TABLE::s] )"),
    ('=DATEDIF([@s],[@e],"M")',
     "diff_months ( [TABLE::e] , [TABLE::s] ) - ( if ( day ( [TABLE::e] ) < day ( [TABLE::s] ) ) "
     "then 1 else 0 )"),
    ("=EOMONTH([@d],0)", "add_days ( add_months ( start_of_month ( [TABLE::d] ) , 1 ) , -1 )"),
    ("=EDATE([@d],3)", "add_months ( [TABLE::d] , 3 )"),
    ("=DAYS([@e],[@s])", "diff_days ( [TABLE::e] , [TABLE::s] )"),
    ("=WEEKDAY([@d])", "( mod ( day_number_of_week ( [TABLE::d] ) , 7 ) + 1 )"),
    ("=WEEKDAY([@d],2)", "day_number_of_week ( [TABLE::d] )"),
    ("=WEEKDAY([@d],3)", "( day_number_of_week ( [TABLE::d] ) - 1 )"),
]


@pytest.mark.parametrize("src,expected", FORWARD, ids=[s for s, _ in FORWARD])
def test_forward(src, expected):
    assert normalise(f(src)) == normalise(expected)


def test_networkdays_is_the_live_verified_counting_form():
    out = f("=NETWORKDAYS([@s],[@e])")
    n = "( diff_days ( [TABLE::e] , [TABLE::s] ) + 1 )"
    w = "day_number_of_week ( [TABLE::s] )"
    expected = (f"{n} - ( floor ( {n} / 7 ) + if ( mod ( 6 + 7 - {w} , 7 ) < mod ( {n} , 7 ) ) "
                f"then 1 else 0 ) - ( floor ( {n} / 7 ) + if ( mod ( 7 + 7 - {w} , 7 ) < "
                f"mod ( {n} , 7 ) ) then 1 else 0 )")
    assert normalise(out) == normalise(expected)
    intl = f('=NETWORKDAYS.INTL([@s],[@e],"1000001")')
    assert "mod ( 1 + 7 -" in intl and "mod ( 7 + 7 -" in intl
    assert "mod ( 7 + 7 -" in f("=NETWORKDAYS.INTL([@s],[@e],11)")


def test_dates_by_type():
    cols = json.dumps({"d": {"table": "T", "column": "d", "data_type": "DATE"},
                       "e": {"table": "T", "column": "e", "data_type": "DATE"},
                       "n": {"table": "T", "column": "n", "data_type": "INT64"}})
    assert f("=[@e]-[@d]", columns=cols) == "diff_days ( [T::e] , [T::d] )"
    assert f("=[@d]+30", columns=cols) == "add_days ( [T::d] , 30 )"
    assert f("=[@d]-[@n]", columns=cols) == "add_days ( [T::d] , - [T::n] )"


def test_concat_wraps_only_non_text():
    cols = json.dumps({"s": {"table": "T", "column": "s", "data_type": "VARCHAR"},
                       "n": {"table": "T", "column": "n", "data_type": "DOUBLE"}})
    assert f('=[@s]&"-"&[@n]', columns=cols) == "concat ( [T::s] , '-' , to_string ( [T::n] ) )"
    r = tx('=[@x]&"!"')
    assert r.expr == "concat ( [TABLE::x] , '!' )" and r.status == "APPROXIMATED"
    assert any("column types unknown" in t for t in r.traps)


class TestStatusesAndTraps:
    def test_iferror_blank_fallback_is_approximated(self):
        r = tx('=IFERROR([@a]/[@b],"")')
        assert r.expr == "safe_divide ( [TABLE::a] , [TABLE::b] )"
        assert r.status == "APPROXIMATED"
        assert any("fallback \"\"" in t for t in r.traps)

    def test_iferror_zero_fallback_is_translated(self):
        r = tx("=IFERROR([@a]/[@b],0)")
        assert r.status == "TRANSLATED" and any("NULL) divisor" in t for t in r.traps)

    def test_iferror_several_divisions_is_approximated(self):
        r = tx("=IFERROR([@a]/[@b]-[@c]/[@d],0)")
        assert r.status == "APPROXIMATED" and any("2 divisions" in t for t in r.traps)

    def test_non_division_iferror_needs_review(self):
        r = tx("=IFERROR(VLOOKUP([@a],T[[k]],2,FALSE),0)")
        assert r.status == "NEEDS_REVIEW"
        r = tx("=IFERROR([@a]+1,0)")
        assert r.status == "NEEDS_REVIEW"

    def test_bare_division_trap(self):
        r = tx("=[@a]/[@b]")
        assert r.expr == "[TABLE::a] / [TABLE::b]" and any("#DIV/0!" in t for t in r.traps)

    def test_blank_branch_beside_number_becomes_null(self):
        r = tx('=IF([@a]>0,[@a]*2,"")')
        assert r.expr == "if ( [TABLE::a] > 0 ) then [TABLE::a] * 2 else null"
        assert r.status == "APPROXIMATED"

    def test_if_without_else(self):
        r = tx("=IF([@a]>0,1)")
        assert r.expr.endswith("else null") and r.status == "APPROXIMATED"


class TestNeedsReview:
    @pytest.mark.parametrize("src", [
        "=VLOOKUP([@a],Lookup[[k]],2,FALSE)", "=XLOOKUP([@a],L[k],L[v])", "=OFFSET(A1,1,0)",
        "=NORM.DIST([@x],0,1,TRUE)", '=TEXT([@d],"yyyy")', "=#N/A", "={1,2}",
        '=DATEDIF([@s],[@e],"MD")', "=NETWORKDAYS([@s],[@e],Holidays[d])",
        "=SUM(Sales[a],[@b])", "=WEEKDAY([@d],21)", '=SEARCH("a*",[@s])',
    ])
    def test_never_guessed(self, src):
        r = tx(src)
        assert r.expr is None and r.status == "NEEDS_REVIEW" and r.notes

    def test_no_rule_cites_the_map_row(self):
        r = tx("=VLOOKUP([@a],L[[k]],2,FALSE)")
        assert "Excel map" in r.notes[-1] and "VLOOKUP" in r.notes[-1] and "structural" in r.notes[-1]

    def test_a1_without_mapping_is_flagged(self):
        r = tx("=B2*C2")
        assert r.expr == "[TABLE::B] * [TABLE::C]"
        assert sum("NEEDS_REVIEW: A1 reference" in n for n in r.notes) == 2

    def test_a1_with_column_map(self):
        r = tx("=B2*C2", columns="B=ORDERS.QTY, C=ORDERS.PRICE")
        assert r.expr == "[ORDERS::QTY] * [ORDERS::PRICE]" and not r.notes

    def test_parse_error(self):
        r = tx("=SUM(")
        assert r.status == "NEEDS_REVIEW" and "cannot parse" in r.notes[0]


# ---------------------------------------------------------------------------
# Intended role
# ---------------------------------------------------------------------------

class TestRole:
    def test_ratio_of_totals(self):
        r = tx("=IFERROR([@a]/[@b],0)", role="measure")
        assert r.expr == "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) )"
        assert r.role == "MEASURE" and any("ratio of totals" in t for t in r.traps)

    def test_bare_ratio_measure_uses_safe_divide(self):
        r = tx("=[@a]/[@b]", role="measure")
        assert r.expr == "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) )"

    def test_additive(self):
        assert f("=[@a]-[@b]+[@c]", role="measure") == \
            "sum ( [TABLE::a] ) - sum ( [TABLE::b] ) + sum ( [TABLE::c] )"
        assert f("=[@a]*12", role="measure") == "sum ( [TABLE::a] ) * 12"
        assert f("=-[@a]", role="measure") == "- sum ( [TABLE::a] )"

    def test_product_of_columns_sums_per_row(self):
        assert f("=[@q]*[@p]", role="measure") == "sum ( [TABLE::q] * [TABLE::p] )"

    def test_explicit_aggregate_maps_directly(self):
        r = tx("=SUM(T[a])/SUM(T[b])", role="measure")
        assert r.expr == "sum ( [T::a] ) / sum ( [T::b] )" and r.role == "MEASURE"

    def test_flag_stays_row_level(self):
        r = tx('=IF([@r]="EMEA",1,0)', role="measure")
        assert r.expr == "if ( [TABLE::r] = 'EMEA' ) then 1 else 0" and r.role == "MEASURE"
        full = translate('=IF([@r]="EMEA",1,0)', "excel", role="measure")
        assert full["role"] == "MEASURE" and full["agentql_wrapper"] == "SUM"
        assert "aggregation: SUM" in full["tml"]

    def test_text_over_measure_intent_stays_attribute_with_trap(self):
        r = tx('=IF([@a]/[@b]>0.5,"High","Low")', role="measure")
        assert r.role == "ATTRIBUTE" and r.expr.startswith("if ( [TABLE::a] / [TABLE::b]")
        assert any("group_aggregate" in t for t in r.traps)

    def test_attribute_keeps_row_level(self):
        r = tx("=IFERROR([@a]/[@b],0)", role="attribute")
        assert r.expr == "safe_divide ( [TABLE::a] , [TABLE::b] )" and r.role == "ATTRIBUTE"

    def test_bad_role(self):
        with pytest.raises(ValueError):
            tx("=1", role="dimension")


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

class TestSheets:
    def sheets(self, src, **kw):
        return tx(src, dialect="google_sheets", **kw)

    def test_one_argument_iferror_is_plain_division(self):
        r = self.sheets("=IFERROR(A2/B2)")
        assert r.expr == "[TABLE::A] / [TABLE::B]" and r.status == "TRANSLATED"
        assert "nullif" not in r.expr and "safe_divide" not in r.expr

    def test_two_argument_iferror_as_excel(self):
        assert self.sheets("=IFERROR([@a]/[@b],0)").expr == "safe_divide ( [TABLE::a] , [TABLE::b] )"

    def test_query_is_structural(self):
        r = self.sheets('=QUERY(A1:D9,"select A")')
        assert r.status == "NEEDS_REVIEW" and "structural" in r.notes[-1]

    def test_arrayformula(self):
        assert self.sheets("=ARRAYFORMULA(A2:A*B2:B)").expr == "[TABLE::A] * [TABLE::B]"
        r = self.sheets("=ARRAYFORMULA(COUNTIF(A2:A,A2:A))")
        assert r.status == "NEEDS_REVIEW" and "element-wise" in r.notes[-1]

    def test_regex_and_countunique(self):
        assert self.sheets('=REGEXMATCH([@s],"a.c")').expr == \
            "sql_bool_op ( \"REGEXP_INSTR({0}, {1}) > 0\" , [TABLE::s] , 'a.c' )"
        assert "'e', 1" in self.sheets('=REGEXEXTRACT([@s],"(\\d+)")').expr
        assert self.sheets("=COUNTUNIQUE(A:A)").expr == "unique count ( [TABLE::A] )"

    def test_operator_functions(self):
        assert self.sheets("=ADD([@a],[@b])").expr == "[TABLE::a] + [TABLE::b]"
        assert self.sheets("=GTE([@a],1)").expr == "[TABLE::a] >= 1"
        assert self.sheets("=UNARY_PERCENT(5)").expr == "5 / 100"

    def test_excel_rule_applies_to_unrowed_names(self):
        assert self.sheets("=ROUND([@x],2)").expr == "round ( [TABLE::x] , 0.01 )"


# ---------------------------------------------------------------------------
# Reverse direction
# ---------------------------------------------------------------------------

REVERSE = [
    ("safe_divide ( [T::a] , [T::b] )", "=IF([@b]=0,0,[@a]/[@b])"),
    ("safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )",
     "=IF(SUM(Table1[b])=0,0,SUM(Table1[a])/SUM(Table1[b]))"),
    ("unique count ( [T::c] )", "=COUNTA(UNIQUE(Table1[c]))"),
    ("count ( [T::c] )", "=COUNTA(Table1[c])"),
    ("average ( [T::Order Value] )", "=AVERAGE(Table1[Order Value])"),
    ("[T::Order Value] * 2", "=[@[Order Value]]*2"),
    ("round ( [T::x] , 0.01 )", "=ROUND([@x],2)"),
    ("round ( [T::x] , 1 )", "=ROUND([@x],0)"),
    ("round ( [T::x] , 0.5 )", "=ROUND([@x]/0.5,0)*0.5"),
    ("concat ( [T::s] , ' ' , to_string ( [T::n] ) )", '=[@s]&" "&[@n]'),
    ("to_string ( [T::n] )", '=[@n]&""'),
    ("contains ( [T::s] , 'x' )", '=ISNUMBER(SEARCH("x",[@s]))'),
    ("diff_days ( [T::e] , [T::s] )", "=[@e]-[@s]"),
    ("diff_months ( [T::e] , [T::s] )", "=(YEAR([@e])-YEAR([@s]))*12+MONTH([@e])-MONTH([@s])"),
    ("day_number_of_week ( [T::d] )", "=WEEKDAY([@d],2)"),
    ("start_of_month ( [T::d] )", "=EOMONTH([@d],-1)+1"),
    ("today ( )", "=TODAY()"),
    ("if ( [T::a] > 1 ) then 'x' else if ( [T::a] > 0 ) then 'y' else 'z'",
     '=IF([@a]>1,"x",IF([@a]>0,"y","z"))'),
    ("greatest ( [T::a] , [T::b] )", "=MAX([@a],[@b])"),
    ("least ( [T::a] , 0 )", "=MIN([@a],0)"),
    ("isnull ( [T::a] )", "=ISBLANK([@a])"),
    ("not ( isnull ( [T::a] ) )", "=NOT(ISBLANK([@a]))"),
    ("count_if ( not ( isnull ( [T::a] ) ) , [T::a] )", '=COUNTIFS(Table1[a],"<>")'),
    ("ifnull ( [T::a] , 0 )", "=IF(ISBLANK([@a]),0,[@a])"),
    ("[T::a] != 'x' and not ( [T::b] )", '=AND([@a]<>"x",NOT([@b]))'),
    ("sum_if ( [T::r] = 'West' and [T::q] > 5 , [T::a] )",
     '=SUMIFS(Table1[a],Table1[r],"=West",Table1[q],">5")'),
    ("group_aggregate ( sum ( [T::a] ) , { [T::acct] } , query_filters ( ) )",
     "=SUMIFS(Table1[a],Table1[acct],[@acct])"),
    ("substr ( [T::s] , 0 , 3 )", "=MID([@s],1,3)"),
    ("[T::a] in { 'x' , 'y' }", '=OR([@a]="x",[@a]="y")'),
]


@pytest.mark.parametrize("ts,excel", REVERSE, ids=[t for t, _ in REVERSE])
def test_reverse(ts, excel):
    out = to_excel(ts)
    assert out.formula == excel, out.notes


def test_reverse_table_option_and_references():
    out = to_excel("sum ( [T::a] )", table="Sales")
    assert out.formula == "=SUM(Sales[a])"
    assert out.references == [{"source": "[T::a]", "target": "Sales[a]"}]


@pytest.mark.parametrize("ts", [
    "cumulative_sum ( [T::a] , [T::d] )", "moving_average ( [T::a] , 2 , 0 , [T::d] )",
    "rank ( sum ( [T::a] ) , 'desc' )", 'sql_int_op ( "LENGTH({0})" , [T::s] )',
    "group_aggregate ( sum ( [T::a] ) , query_groups ( ) , query_filters ( ) )",
    "round ( [T::x] , 0 )", "unique_count_if ( [T::a] > 1 , [T::b] )", "[T::a] +",
    "isnotnull ( [T::a] )", "nullif ( [T::a] , 0 )",
])
def test_reverse_needs_review(ts):
    out = to_excel(ts)
    assert out.formula is None and out.status == "NEEDS_REVIEW" and out.notes


def test_reverse_caveats():
    out = to_excel("if ( [T::a] = 'x' ) then null else [T::b] / [T::c]")
    assert out.status == "APPROXIMATED"
    assert any("blank cell" in t for t in out.traps) and any("#DIV/0!" in t for t in out.traps)
    assert any("case-insensitive" in n for n in out.notes)


def test_reverse_cli(tmp_path):
    from typer.testing import CliRunner
    from ts_cli.cli import app

    res = CliRunner().invoke(app, ["formula", "translate", "safe_divide ( [T::a] , [T::b] )",
                                   "--from", "thoughtspot", "--to", "excel", "--table", "S"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.stdout)
    assert data["formula"] == "=IF([@b]=0,0,[@a]/[@b])" and data["table"] == "S"
    bad = CliRunner().invoke(app, ["formula", "translate", "x", "--from", "excel", "--to", "excel"])
    assert bad.exit_code == 2


def test_forward_cli_role():
    from typer.testing import CliRunner
    from ts_cli.cli import app

    res = CliRunner().invoke(app, ["formula", "translate", "=IFERROR([@a]/[@b],0)",
                                   "--from", "excel", "--role", "measure"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.stdout)
    assert data["formula"] == "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) )"
    assert data["role"] == "MEASURE" and data["verification"]["translator"].startswith("ts_cli.excel")


# ---------------------------------------------------------------------------
# Rules, catalog and map inventory
# ---------------------------------------------------------------------------

def test_handlers_match_rule_table():
    assert set(HANDLERS) == set(FUNCTION_RULES)
    assert set(SHEETS_HANDLERS) == set(SHEETS_RULES)


def test_every_forward_output_is_inside_the_catalog():
    srcs = [s for s, _ in FORWARD] + ["=NETWORKDAYS([@s],[@e])", "=WEEKDAY([@d],13)"]
    for src in srcs:
        calls = {n["fn"] for n in walk(from_text(f(src))) if n.get("node") == "call"}
        assert all(is_known(c) for c in calls if c not in ("in", "between")), (src, calls)


def test_rule_emits_cover_handler_output():
    """A handler emits only names its rule declares (the names the validator checks against
    the map row)."""
    for src, _ in FORWARD:
        name = re.match(r"=([A-Z][A-Z0-9.]*)\(", src)
        if not name or name.group(1) not in FUNCTION_RULES:
            continue
        calls = {n["fn"] for n in walk(from_text(f(src))) if n.get("node") == "call"}
        nested = {"to_string", "safe_divide", "contains", "strpos", "isnull",
                  "month_number", "day", "to_double", "if"}
        allowed = set(FUNCTION_RULES[name.group(1)]["emits"]) | nested
        for rule in FUNCTION_RULES.values():
            if name.group(1) in ("SUMIF", "SUMIFS", "COUNTIF", "AVERAGEIFS", "MAXIFS"):
                allowed |= set(rule["emits"])
        assert calls <= allowed | {"mod", "floor", "diff_days", "day_number_of_week"}, (src, calls)


def _doc_rows(path: Path) -> dict:
    out, sec = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            sec = line[3:].strip()
        m = re.match(r"^\| `([A-Z][A-Z0-9_.]*)\([^|]*\| *([^|]+?) *\|", line)
        if m:
            out[m.group(1)] = (sec, m.group(2).replace("*", "").strip())
    return out


class TestMapIndex:
    def test_excel_index_matches_map(self):
        assert EXCEL_ROWS == _doc_rows(_REPO / "docs/function-maps/ts-excel-function-mapping.md")

    def test_sheets_index_matches_map(self):
        assert SHEETS_ROWS == _doc_rows(_REPO / "docs/function-maps/ts-sheets-function-mapping.md")

    def test_cite(self):
        assert cite("vlookup").endswith("`VLOOKUP` — structural")
        assert "via Sheets E1" in cite("VLOOKUP", "google_sheets")
        assert cite("NOPE").startswith("no map row")


def test_printer_round_trips_through_the_one_parser():
    for _src, expected in FORWARD:
        assert to_text(from_text(expected)) == expected or \
            normalise(to_text(from_text(expected))) == normalise(expected)
