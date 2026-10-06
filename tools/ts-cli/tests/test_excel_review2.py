"""Regression tests for the second-round review of PR #570 (items 1–13).

Items 1–3 (HIGH) are explicit and named: test_h1_*, test_h2_*, test_h3_*.
"""
from __future__ import annotations

import json

import pytest

from tests.excel_support import normalise
from ts_cli.excel.to_excel import to_excel
from ts_cli.excel.translate import translate_excel
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
from ts_cli.formula_translate.engine import translate
from ts_cli.sv_sql import translate_sql_expr

NR = "NEEDS_REVIEW"


def tx(src, role=None, columns=None):
    ctx = ColumnContext(parse_columns_json(columns), level=1) if columns else ColumnContext()
    return translate_excel(src, ctx, role=role)


def typed(**types):
    return json.dumps({c: {"table": "T", "column": c, "data_type": t} for c, t in types.items()})


# ---------------------------------------------------------------------------
# HIGH 1 — NULLIF composes: always parenthesised (sv_sql / mv_sql / constructs)
# ---------------------------------------------------------------------------

def _res(ident):
    return f"[A::{ident.split('.')[-1].upper()}]"


@pytest.mark.parametrize("sql,expected", [
    ("NULLIF(x, 1) > 2 OR y > 0", "( if ( [A::X] = 1 ) then null else [A::X] ) > 2 or [A::Y] > 0"),
    ("NULLIF(x, y) * 2", "( if ( [A::X] = [A::Y] ) then null else [A::X] ) * 2"),
    ("1 + NULLIF(x, 0)", "1 + ( if ( [A::X] = 0 ) then null else [A::X] )"),
    ("NULLIF(x, 0) > 2 OR y > 0", "( if ( [A::X] = 0 ) then null else [A::X] ) > 2 or [A::Y] > 0"),
])
def test_h1_snowflake_nullif_is_parenthesised(sql, expected):
    assert translate_sql_expr(sql, _res) == expected


@pytest.mark.parametrize("sql", ["NULLIF(x, 0) > 2 OR y > 0", "1 + NULLIF(x, 0)",
                                 "NULLIF(x, 0) * 2"])
def test_h1_databricks_nullif_is_parenthesised(sql):
    out = translate(sql, "databricks")["formula"]
    assert "( if ( [TABLE::x] = 0 ) then null else [TABLE::x] )" in out, out
    from ts_cli.databricks.mv_emit_expr import parse_formula
    node = parse_formula(out)  # parses, and the if is one operand
    assert node["node"] == "binop"


def test_h1_engine_round_trip_keeps_precedence():
    r = translate("NULLIF(x, 1) > 2 OR y > 0", "snowflake")
    assert r["formula"] == ("( if ( [TABLE::x] = 1 ) then null else [TABLE::x] ) > 2 "
                            "or [TABLE::y] > 0")


# ---------------------------------------------------------------------------
# HIGH 2 — a per-row criterion inside a conditional aggregate is mixed grain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", [
    "=COUNTIF(T[r],[@r])",
    "=SUMIF(T[r],[@r],T[v])",
    '=COUNTIFS(T[a],">"&[@s])',
    '=COUNTIFS(T[a],"x",T[b],[@b])',
    "=AVERAGEIF(T[r],[@r],T[v])",
    '=SUMIFS(T[v],T[d],"<="&[@d])',
    "=COUNTIF(A:A,A2)",
])
def test_h2_per_row_criteria_need_review(src):
    r = tx(src)
    assert r.status == NR and r.expr is None, (src, r.expr)
    assert "group_aggregate ( count ( [r] ) , { [r] } , query_filters ( ) )" in r.notes[-1]


def test_h2_literal_criteria_still_translate():
    assert tx('=COUNTIF(T[r],"x")').expr == "count_if ( [T::r] = 'x' , [T::r] )"
    assert tx('=SUMIFS(T[v],T[a],">"&10)').expr == "sum_if ( [T::a] > 10 , [T::v] )"


# ---------------------------------------------------------------------------
# HIGH 3 — DATETIME arithmetic keeps the time of day; fractional days are refused
# ---------------------------------------------------------------------------

DT = typed(t="DATE_TIME", u="DATE_TIME", d="DATE", n="DOUBLE")


@pytest.mark.parametrize("src,expected", [
    ("=([@t]-[@u])*24", "diff_time ( [T::t] , [T::u] ) / 86400 * 24"),
    ("=[@t]-[@u]", "diff_time ( [T::t] , [T::u] ) / 86400"),
    ("=[@t]-[@d]", "diff_time ( [T::t] , [T::d] ) / 86400"),
    ("=NOW()-[@t]", "diff_time ( now ( ) , [T::t] ) / 86400"),
    ("=[@d]-[@d]", "diff_days ( [T::d] , [T::d] )"),
    ("=[@t]+1", "add_days ( [T::t] , 1 )"),
    ("=[@t]-7", "add_days ( [T::t] , - 7 )"),
])
def test_h3_datetime_differences(src, expected):
    assert normalise(tx(src, columns=DT).expr) == normalise(expected)


@pytest.mark.parametrize("src", ["=[@t]+0.5", "=[@t]+1/24", "=[@d]+0.5", "=[@t]-0.25",
                                 "=0.5+[@d]"])
def test_h3_fractional_days_need_review(src):
    r = tx(src, columns=DT)
    assert r.status == NR and "whole days" in r.notes[-1], (src, r.expr)


def test_h3_datetime_difference_type_chains():
    """add_days on a DATETIME stays a DATETIME, so a later difference keeps the hours."""
    assert normalise(tx("=([@t]+1)-[@u]", columns=DT).expr) == normalise(
        "diff_time ( add_days ( [T::t] , 1 ) , [T::u] ) / 86400")


# ---------------------------------------------------------------------------
# MEDIUM 4, 9 — ratios under --role measure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", ["=[@a]/[@b]+[@c]", "=[@c]-[@a]/[@b]", "=([@a]/[@b])*[@c]+[@d]"])
def test_ratio_plus_column_needs_review(src):
    r = tx(src, role="measure")
    assert r.status == NR, (src, r.expr)


def test_ratio_minus_ratio_is_two_ratios_of_totals():
    r = tx("=[@a]/[@b]-[@c]/[@d]", role="measure")
    assert normalise(r.expr) == normalise(
        "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) ) - "
        "safe_divide ( sum ( [TABLE::c] ) , sum ( [TABLE::d] ) )")
    assert any("each ratio term" in t for t in r.traps)
    assert not any("Σ(a ± b)" in n for n in r.notes)


@pytest.mark.parametrize("src,expected", [
    ("=[@a]/100/[@b]", "safe_divide ( sum ( [TABLE::a] ) / 100 , sum ( [TABLE::b] ) )"),
    ("=[@a]/2/[@b]", "safe_divide ( sum ( [TABLE::a] ) / 2 , sum ( [TABLE::b] ) )"),
    ("=([@a]/[@b])*100+0", "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) ) * 100 + 0"),
    ("=[@a]/[@b]+1", "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) ) + 1"),
    ("=[@a]/[@b]/2", "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) ) / 2"),
    ("=[@a]/[@b]*100", "safe_divide ( sum ( [TABLE::a] ) , sum ( [TABLE::b] ) ) * 100"),
])
def test_ratio_scaled_or_shifted_by_a_constant_translates(src, expected):
    assert normalise(tx(src, role="measure").expr) == normalise(expected)


def test_true_ratio_of_ratios_still_needs_review():
    assert tx("=[@a]/[@b]/[@c]", role="measure").status == NR


# ---------------------------------------------------------------------------
# MEDIUM 5 / LOW 13 — reverse-direction typed literals
# ---------------------------------------------------------------------------

DATE_SPECS = parse_columns_json(json.dumps({"d": {"table": "T", "column": "d", "data_type": "DATE"},
                                            "n": {"table": "T", "column": "n", "data_type": "DOUBLE"}}))


@pytest.mark.parametrize("ts,excel", [
    ("[T::d] between '2024-01-01' and '2024-12-31'",
     '=AND([@d]>=DATEVALUE("2024-01-01"),[@d]<=DATEVALUE("2024-12-31"))'),
    ("[T::d] in { '2024-01-01' , '2024-02-01' }",
     '=OR([@d]=DATEVALUE("2024-01-01"),[@d]=DATEVALUE("2024-02-01"))'),
    ("[T::d] >= '2024-01-01 10:30:00'", '=[@d]>=DATEVALUE("2024-01-01")+TIMEVALUE("10:30:00")'),
    ("ifnull ( [T::d] , '2024-01-01' )", '=IF(ISBLANK([@d]),DATEVALUE("2024-01-01"),[@d])'),
    ("[T::n] > '5'", '=[@n]>VALUE("5")'),
])
def test_reverse_typed_literals(ts, excel):
    known = to_excel(ts, specs=DATE_SPECS)
    assert known.formula == excel and known.status == "TRANSLATED", known.traps
    unknown = to_excel(ts)
    assert unknown.formula == excel and unknown.status == "APPROXIMATED"
    assert any("column type unknown" in t for t in unknown.traps)


def test_reverse_negative_round_increment_reason():
    out = to_excel("round ( [T::x] , -10 )")
    assert out.status == NR and "negative increment" in out.notes[-1]
    assert "non-literal" not in out.notes[-1]


# ---------------------------------------------------------------------------
# MEDIUM 6, 7, 8 and LOW 10, 11 — forward typing
# ---------------------------------------------------------------------------

def test_unknown_type_blank_and_condition_are_approximated():
    r = tx('=IF([@x]="",1,0)')
    assert r.expr == "if ( isnull ( [TABLE::x] ) or [TABLE::x] = '' ) then 1 else 0"
    assert r.status == "APPROXIMATED" and any("column type unknown" in t for t in r.traps)
    r = tx("=IF([@x],1,0)")
    assert r.expr == "if ( [TABLE::x] ) then 1 else 0" and r.status == "APPROXIMATED"
    assert any("!= 0" in t for t in r.traps)
    assert tx('=IF([@x]="",1,0)', columns=typed(x="VARCHAR")).status == "TRANSLATED"


@pytest.mark.parametrize("src,expected", [
    ("=MAX([@Q]>1,0)", "greatest ( ( if ( [T::Q] > 1 ) then 1 else 0 ) , 0 )"),
    ("=ABS([@Q]>1)", "abs ( ( if ( [T::Q] > 1 ) then 1 else 0 ) )"),
    ("=ROUND([@Q]>1,0)", "round ( ( if ( [T::Q] > 1 ) then 1 else 0 ) , 1 )"),
])
def test_boolean_function_argument_is_coerced(src, expected):
    assert normalise(tx(src, columns=typed(Q="DOUBLE")).expr) == normalise(expected)


def test_criteria_blank_is_type_aware():
    r = tx('=COUNTIF(T[r],"")')
    assert r.expr == "count_if ( isnull ( [T::r] ) or [T::r] = '' , [TABLE::<primary key>] )"
    r = tx('=COUNTIF(T[n],"")', columns=typed(n="DOUBLE"))
    assert r.expr.startswith("count_if ( isnull ( [T::n] ) ,")
    r = tx('=COUNTIF(T[r],"<>")', columns=typed(r="VARCHAR"))
    assert r.expr == "count_if ( not ( isnull ( [T::r] ) or [T::r] = '' ) , [T::r] )"


def test_isnumber_of_a_numeric_column_is_not_blank():
    assert tx("=ISNUMBER([@Q])", columns=typed(Q="DOUBLE")).expr == "not ( isnull ( [T::Q] ) )"
    assert tx("=ISNUMBER([@s])", columns=typed(s="VARCHAR")).expr == "false"


def test_comparison_inside_comparison_is_bracketed():
    assert tx("=([@a]>1)=([@b]>2)").expr == "( [TABLE::a] > 1 ) = ( [TABLE::b] > 2 )"
    assert tx("=([@a]>1)=FALSE").expr == "( [TABLE::a] > 1 ) = false"
