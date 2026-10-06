"""Regression tests for the independent review of PR #570 (items H1–H4, M1–M5, L2).

Each case was a reviewer example that came back wrong while reporting TRANSLATED or
APPROXIMATED; the assertion is the corrected output, or NEEDS_REVIEW.
"""
from __future__ import annotations

import json

import pytest

from tests.excel_support import normalise
from ts_cli.excel.to_excel import to_excel
from ts_cli.excel.translate import translate_excel
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json, specs_from_model_tml
from ts_cli.formula_translate.engine import translate

NR = "NEEDS_REVIEW"


def tx(src, role=None, columns=None, dialect="excel"):
    ctx = ColumnContext(parse_columns_json(columns), level=1) if columns else ColumnContext()
    return translate_excel(src, ctx, dialect=dialect, role=role)


def typed(**types):
    return json.dumps({c: {"table": "T", "column": c, "data_type": t} for c, t in types.items()})


# ---------------------------------------------------------------------------
# H1 — an A1 row number is a position, not a column
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,why", [
    ("=A3-A2", "rows 2, 3"),                   # previous-row arithmetic
    ("=SUM($A$2:A2)", "expanding range"),      # running total
    ("=SUM(A2:A5)", "bounded range"),          # a subset of rows, not the column
    ("=A2+$A$1", "fixed cell"),                # an input cell
    ("=A2*$B$1", "fixed cell"),
    ("=B$1*A2", "fixed cell"),
    ("=Sheet2!B2*2", "another sheet"),          # L2
    ("=SUM('Other Sheet'!A:A)", "another sheet"),
])
def test_position_dependent_a1_needs_review(src, why):
    r = tx(src, columns="A=T.QTY, B=T.PRICE")
    assert r.status == NR and r.expr is None and why in r.notes[-1], r.notes


def test_window_hint_points_at_cumulative_and_moving():
    note = tx("=SUM($A$2:A2)").notes[-1]
    assert "cumulative_sum" in note and "moving_sum" in note
    assert "parameter" in tx("=A2+$A$1").notes[-1]


def test_same_row_fill_down_and_whole_columns_still_translate():
    assert tx("=A2*B2", columns="A=T.QTY, B=T.PRICE").expr == "[T::QTY] * [T::PRICE]"
    assert tx("=SUM(A:A)", columns="A=T.QTY").expr == "sum ( [T::QTY] )"
    assert tx("=ARRAYFORMULA(A2:A*B2:B)", dialect="google_sheets").expr == "[TABLE::A] * [TABLE::B]"


# ---------------------------------------------------------------------------
# H2 — --role measure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ("=[@R]+5", "sum ( [TABLE::R] + 5 )"),
    ("=[@R]-100", "sum ( [TABLE::R] - 100 )"),
    ("=5+[@R]", "sum ( 5 + [TABLE::R] )"),
    ("=[@a]-[@b]+5", "sum ( [TABLE::a] - [TABLE::b] + 5 )"),
    ("=[@R]/100", "sum ( [TABLE::R] ) / 100"),
    ("=([@a]+[@b])/[@c]", "safe_divide ( sum ( [TABLE::a] ) + sum ( [TABLE::b] ) , sum ( [TABLE::c] ) )"),
])
def test_measure_constant_terms_sum_per_row(src, expected):
    assert normalise(tx(src, role="measure").expr) == normalise(expected)


@pytest.mark.parametrize("src,why", [
    ("=1/[@Price]", "constant divided by a column"),
    ("=ROUND([@r]/[@q],2)", "contains a ratio"),
    ("=IF([@c]>0,[@r]/[@q],0)", "contains a ratio"),
    ("=IFERROR(ROUND([@r]/[@q],2),0)", "contains a ratio"),
    ("=[@r]/[@q]/[@d]", "ratio of ratios"),
    ("=[@r]/([@q]/[@d])", "ratio of ratios"),
    ("=MAX(0,[@r]/[@q])", "contains a ratio"),
])
def test_measure_ratio_shapes_without_a_ratio_of_totals_need_review(src, why):
    r = tx(src, role="measure")
    assert r.status == NR and why in r.notes[-1], r.notes


@pytest.mark.parametrize("src", ["=SUM(T[R])/[@Qty]", "=A2/SUM(A:A)", "=[@a]-AVERAGE(T[a])"])
@pytest.mark.parametrize("role", [None, "measure", "attribute"])
def test_mixed_grain_needs_review(src, role):
    r = tx(src, role=role)
    assert r.status == NR and "mixed grain" in r.notes[-1]
    assert "group_aggregate ( sum ( [x] ) , { } , query_filters ( ) )" in r.notes[-1]


def test_additive_note_only_where_true():
    assert any("Σ(a ± b)" in n for n in tx("=[@a]-[@b]", role="measure").notes)
    assert not any("Σ(a ± b)" in n for n in tx("=[@a]+5", role="measure").notes)
    assert not any("Σ(a ± b)" in n for n in tx("=[@a]*12", role="measure").notes)


# ---------------------------------------------------------------------------
# H3 — conditional aggregates are MEASUREs by default
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", [
    '=COUNTIF(T[r],"x")', '=COUNTIFS(T[r],"x")', '=AVERAGEIF(T[r],"x",T[v])',
    '=AVERAGEIFS(T[v],T[r],"x")', '=MAXIFS(T[v],T[r],"x")', '=MINIFS(T[v],T[r],"x")',
    '=SUMIFS(T[v],T[r],"x")',
])
def test_conditional_aggregates_infer_measure(src):
    r = translate(src, "excel")
    assert r["role"] == "MEASURE" and r["agentql_wrapper"] == "AGG", (r["formula"], r["role"])


# ---------------------------------------------------------------------------
# H4 — unknown-type columns stay bare in concat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    ('=[@x]&"!"', "concat ( [TABLE::x] , '!' )"),
    ('=CONCAT([@a],[@b])', "concat ( [TABLE::a] , [TABLE::b] )"),
    ('=CONCATENATE("a",[@b])', "concat ( 'a' , [TABLE::b] )"),
    ('=TEXTJOIN("-",FALSE,[@a],[@b])', "concat ( [TABLE::a] , '-' , [TABLE::b] )"),
])
def test_unknown_columns_bare_and_approximated(src, expected):
    r = tx(src)
    assert r.expr == expected and r.status == "APPROXIMATED"
    assert any("if it is numeric" in t and "to_string" in t for t in r.traps)


@pytest.mark.parametrize("src,expected", [
    ('="FY"&2026', "concat ( 'FY' , to_string ( 2026 ) )"),
    ('="Q"&MONTH([@d])', "concat ( 'Q' , to_string ( month_number ( [TABLE::d] ) ) )"),
    ('="n="&LEN([@s])', "concat ( 'n=' , to_string ( strlen ( [TABLE::s] ) ) )"),
])
def test_known_numeric_operands_still_wrapped(src, expected):
    assert tx(src).expr == expected


def test_typed_columns_from_columns_and_from_a_model():
    assert tx('=[@s]&[@n]', columns=typed(s="VARCHAR", n="DOUBLE")).expr == \
        "concat ( [T::s] , to_string ( [T::n] ) )"
    model = {"model": {"name": "M", "model_tables": [{"name": "T"}], "columns": [
        {"name": "s", "column_id": "T::s", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "n", "column_id": "T::n", "properties": {"column_type": "MEASURE"}}]}}
    tables = [{"table": {"name": "T", "columns": [
        {"name": "s", "db_column_properties": {"data_type": "VARCHAR"}},
        {"name": "n", "db_column_properties": {"data_type": "INT64"}}]}}]
    ctx = ColumnContext(specs_from_model_tml(model, tables), level=2)
    r = translate_excel('=[@s]&[@n]', ctx)
    assert r.expr == "concat ( [T::s] , to_string ( [T::n] ) )" and r.status == "TRANSLATED"


# ---------------------------------------------------------------------------
# M1 — blank tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,columns,expected", [
    ('=IF([@s]="","blank","x")', None,
     "if ( isnull ( [TABLE::s] ) or [TABLE::s] = '' ) then 'blank' else 'x'"),
    ('=IF([@s]="","blank","x")', typed(s="VARCHAR"),
     "if ( isnull ( [T::s] ) or [T::s] = '' ) then 'blank' else 'x'"),
    ('=IF([@n]="","blank","x")', typed(n="DOUBLE"), "if ( isnull ( [T::n] ) ) then 'blank' else 'x'"),
    ('=IF([@d]="","blank","x")', typed(d="DATE"), "if ( isnull ( [T::d] ) ) then 'blank' else 'x'"),
    ('=IF(""=[@n],1,0)', typed(n="INT64"), "if ( isnull ( [T::n] ) ) then 1 else 0"),
    ('=IF([@s]<>"","x","blank")', None,
     "if ( not ( isnull ( [TABLE::s] ) or [TABLE::s] = '' ) ) then 'x' else 'blank'"),
])
def test_blank_tests(src, columns, expected):
    assert normalise(tx(src, columns=columns).expr) == normalise(expected)


# ---------------------------------------------------------------------------
# M2 — booleans in arithmetic, numbers as conditions
# ---------------------------------------------------------------------------

B1 = "( if ( [TABLE::a] > 1 ) then 1 else 0 )"


@pytest.mark.parametrize("src,columns,expected", [
    ("=TRUE+1", None, "( if ( true ) then 1 else 0 ) + 1"),
    ("=--([@a]>1)", None, f"- ( - {B1} )"),
    ("=([@a]>1)*1", None, f"{B1} * 1"),
    ("=([@a]>1)+([@b]>2)", None, f"{B1} + ( if ( [TABLE::b] > 2 ) then 1 else 0 )"),
    ("=[@Q]+TRUE", typed(Q="DOUBLE"), "[T::Q] + ( if ( true ) then 1 else 0 )"),
    ('=IF([@Q],"y","n")', typed(Q="DOUBLE"), "if ( [T::Q] != 0 ) then 'y' else 'n'"),
    ('=IF(AND([@Q],[@R]>1),"y","n")', typed(Q="INT64", R="INT64"),
     "if ( [T::Q] != 0 and [T::R] > 1 ) then 'y' else 'n'"),
    ('=NOT([@Q])', typed(Q="INT64"), "not ( [T::Q] != 0 )"),
])
def test_boolean_coercion(src, columns, expected):
    assert normalise(tx(src, columns=columns).expr) == normalise(expected)


# ---------------------------------------------------------------------------
# L2 — untyped date arithmetic, booleans in to_string
# ---------------------------------------------------------------------------

def test_untyped_column_arithmetic_is_approximated_with_a_type_note():
    for src in ("=[@D]-[@E]", "=[@D]+7"):
        r = tx(src)
        assert r.status == "APPROXIMATED" and any("diff_days" in t for t in r.traps), src
    r = tx("=TODAY()-[@D]")
    assert r.status == NR and "data_type" in r.notes[-1]
    cols = typed(D="DATE", E="DATE")
    assert tx("=[@D]-[@E]", columns=cols).expr == "diff_days ( [T::D] , [T::E] )"
    assert tx("=TODAY()-[@D]", columns=cols).expr == "diff_days ( today ( ) , [T::D] )"


def test_boolean_in_concat_reads_excel_capitals():
    # BL-349 (fidelity M1): to_string gives 'true' / 'false'; Excel's & shows TRUE / FALSE,
    # so the translation writes the capitals out instead of noting the difference
    r = tx('="x"&([@a]>1)')
    assert "if ( [TABLE::a] > 1 ) then 'TRUE' else 'FALSE'" in r.expr


# ---------------------------------------------------------------------------
# M3 — reverse direction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ts,excel", [
    ("contains ( [T::s] , 'a*b' )", '=ISNUMBER(SEARCH("a~*b",[@s]))'),
    ("contains ( [T::s] , '50%?' )", '=ISNUMBER(SEARCH("50%~?",[@s]))'),
    ("strpos ( [T::s] , '~x' )", '=IFERROR(SEARCH("~~x",[@s]),0)'),
    ("count_if ( [T::r] = 'a*' , [T::r] )", '=COUNTIFS(Table1[r],"=a~*")'),
    ("count_if ( [T::r] = '>5' , [T::r] )", '=COUNTIFS(Table1[r],"=>5")'),
    ("sum_if ( [T::r] != 'x?' , [T::v] )", '=SUMIFS(Table1[v],Table1[r],"<>x~?")'),
    ("count_if ( contains ( [T::r] , 'a*' ) , [T::r] )", '=COUNTIFS(Table1[r],"*a~**")'),
    ("round ( [T::x] , 0.25 )", "=ROUND([@x]/0.25,0)*0.25"),
    ("round ( [T::x] , 5 )", "=ROUND([@x]/5,0)*5"),
    ("mod ( [T::a] , [T::b] )", "=[@a]-[@b]*TRUNC([@a]/[@b])"),
    ("mod ( [T::a] + 1 , 7 )", "=[@a]+1-7*TRUNC(([@a]+1)/7)"),  # left-assoc: (a+1)-…
    ("if ( [T::d] >= '2024-01-01' ) then 1 else 0", '=IF([@d]>=DATEVALUE("2024-01-01"),1,0)'),
    ("'2024-12-31' > [T::d]", '=DATEVALUE("2024-12-31")>[@d]'),
])
def test_reverse_fixes(ts, excel):
    out = to_excel(ts)
    assert out.formula == excel, out.notes


def test_reverse_search_column_needle_trap():
    out = to_excel("contains ( [T::s] , [T::t] )")
    assert out.formula == "=ISNUMBER(SEARCH([@t],[@s]))"
    assert any("wildcards" in t for t in out.traps)


def test_escaped_criteria_round_trip_forward():
    assert tx('=COUNTIF(T[r],"=a~*")').expr == "count_if ( [T::r] = 'a*' , [T::r] )"
    assert tx('=COUNTIF(T[r],"=>5")').expr == "count_if ( [T::r] = '>5' , [T::r] )"


# ---------------------------------------------------------------------------
# M5 — null_if_zero does not exist (BL-344)
# ---------------------------------------------------------------------------

def test_null_if_zero_is_never_emitted():
    from ts_cli.formula_translate.catalog import is_known
    assert not is_known("null_if_zero")
    for dialect in ("snowflake", "databricks"):
        r = translate("NULLIF(x, 0)", dialect)
        assert r["formula"] == "( if ( [TABLE::x] = 0 ) then null else [TABLE::x] )", dialect
        r = translate("COALESCE(NULLIF(x, 0), 1)", dialect)
        assert "null_if_zero" not in (r["formula"] or "") and r["status"] != NR, dialect
