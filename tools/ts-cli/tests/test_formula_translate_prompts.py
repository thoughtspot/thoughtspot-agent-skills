"""The skill's two questions as CLI output fields: ``needs_types`` (column types) and
``role_ambiguous`` / ``role_options`` (per row, or a KPI that rolls up)."""
from __future__ import annotations

import json

import pytest

from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
from ts_cli.formula_translate.engine import translate
from ts_cli.formula_translate.prompts import NAME_HEURISTIC, has_ratio, suggest_type

CONCAT = '=[@CONTRACT_TERM_MONTHS]&" months"'
MARGIN = '=IFERROR(([@TOTAL_REVENUE]-[@TOTAL_COGS])/[@TOTAL_REVENUE],"")'


def _ctx(columns: dict) -> ColumnContext:
    return ColumnContext(parse_columns_json(json.dumps(columns)), level=1)


# -- needs_types ---------------------------------------------------------------------

def test_concat_with_unknown_type_needs_its_type():
    r = translate(CONCAT, "excel")
    assert r["formula"] == "concat ( [TABLE::CONTRACT_TERM_MONTHS] , ' months' )"
    assert r["needs_types"] == [{
        "column": "CONTRACT_TERM_MONTHS", "target": "[TABLE::CONTRACT_TERM_MONTHS]",
        "reason": "text join", "note": r["needs_types"][0]["note"],
        "suggested_type": "number", "suggested_data_type": "INT64", "confidence": "high"}]
    assert r["needs_types"][0]["note"] in r["traps"]  # the existing trap, reused


def test_every_text_join_column_is_listed_once():
    r = translate('=[@MONTH_NAME]&" "&[@YEAR]&" / "&[@YEAR]', "excel")
    assert [(n["column"], n["suggested_type"]) for n in r["needs_types"]] == [
        ("MONTH_NAME", "text"), ("YEAR", "number")]


@pytest.mark.parametrize("data_type, expected", [
    ("INT64", "concat ( to_string ( [ORDERS::CONTRACT_TERM_MONTHS] ) , ' months' )"),
    ("VARCHAR", "concat ( [ORDERS::CONTRACT_TERM_MONTHS] , ' months' )"),
])
def test_needs_types_empty_once_types_are_supplied(data_type, expected):
    ctx = _ctx({"CONTRACT_TERM_MONTHS": {"table": "ORDERS", "column": "CONTRACT_TERM_MONTHS",
                                         "data_type": data_type}})
    r = translate(CONCAT, "excel", ctx)
    assert r["needs_types"] == [] and r["formula"] == expected


def test_other_type_sensitive_rules_are_listed():
    cond = translate('=IF([@IS_ACTIVE],"Y","N")', "excel")["needs_types"]
    assert [(n["column"], n["reason"]) for n in cond] == [("IS_ACTIVE", "condition")]
    blank = translate('=IF([@REGION]="","none",[@REGION])', "excel")["needs_types"]
    assert [(n["column"], n["reason"]) for n in blank] == [("REGION", "blank test")]
    branch = translate('=IF([@A]>0,"",[@SCORE])', "excel")["needs_types"]
    assert ("SCORE", "blank IF branch") in [(n["column"], n["reason"]) for n in branch]


def test_date_arithmetic_listed_only_when_the_name_suggests_a_date():
    dates = translate("=[@END_DATE]-[@START_DATE]", "excel")["needs_types"]
    assert [(n["column"], n["reason"], n["suggested_type"]) for n in dates] == [
        ("END_DATE", "date arithmetic", "date"), ("START_DATE", "date arithmetic", "date")]
    # a - b is already right for numbers: no question for amounts (the trap still fires)
    amounts = translate("=[@TOTAL_REVENUE]-[@TOTAL_COGS]", "excel")
    assert amounts["needs_types"] == []
    assert any("column type unknown" in t for t in amounts["traps"])


def test_other_dialects_carry_empty_fields():
    for expr, dialect in (("SUM([Sales]) / SUM([Qty])", "tableau"),
                          ("SUM(amount) / SUM(qty)", "snowflake")):
        r = translate(expr, dialect)
        assert r["needs_types"] == [] and r["role_ambiguous"] is False
        assert r["role_options"] == []


# -- the name heuristic --------------------------------------------------------------

@pytest.mark.parametrize("token, suggested, data_type, confidence", NAME_HEURISTIC)
def test_heuristic_table(token, suggested, data_type, confidence):
    assert suggest_type(f"SOME_{token}") == {"suggested_type": suggested,
                                             "suggested_data_type": data_type,
                                             "confidence": confidence}


@pytest.mark.parametrize("name, expected", [
    ("CONTRACT_TERM_MONTHS", "number"), ("SEAT_COUNT", "number"), ("ORDER_QTY", "number"),
    ("CUSTOMER_ID", "number"), ("YEAR", "number"), ("FISCAL_YEAR", "number"),
    ("DEAL_AMOUNT", "number"), ("INFRA_COST", "number"), ("TOTAL_REVENUE", "number"),
    ("ORDER_DATE", "date"), ("CREATED_AT", "date"), ("MONTH_NAME", "text"),
    ("QUARTER_LABEL", "text"), ("ACV_BAND", "text"), ("REGION_CODE", "text"),
    ("Month Name", "text"), ("month_name", "text"),
    ("REGION", None), ("HEALTH_SCORE", None), ("ATTRIBUTE", None), ("", None),
])
def test_heuristic_suggestions(name, expected):
    s = suggest_type(name)
    assert s["suggested_type"] == expected
    if expected is None:
        assert s["confidence"] == "low" and s["suggested_data_type"] is None


def test_heuristic_agrees_with_the_regression_workbook_types():
    """Every suggestion the heuristic makes for the 60-case workbook's columns matches the
    reviewed data type (accuracy where it speaks; silence is allowed)."""
    from tests.test_excel_regression import COLUMNS

    kind = {"INT64": "number", "DOUBLE": "number", "VARCHAR": "text", "DATE": "date"}
    cols = json.loads(COLUMNS)
    suggested = {n: suggest_type(n)["suggested_type"] for n in cols}
    spoke = {n: t for n, t in suggested.items() if t}
    assert len(spoke) >= 15
    assert {n: t for n, t in spoke.items() if kind[cols[n]["data_type"]] != t} == {}


# -- role_ambiguous / role_options ---------------------------------------------------

def test_ratio_without_role_is_ambiguous_with_both_options():
    r = translate(MARGIN, "excel")
    assert r["role_ambiguous"] is True
    attr, meas = r["role_options"]
    assert attr["role"] == "attribute" and attr["flag"] == "--role attribute"
    assert attr["label"] == "per row" and attr["column_type"] == "ATTRIBUTE"
    assert attr["formula"] == ("safe_divide ( [TABLE::TOTAL_REVENUE] - [TABLE::TOTAL_COGS] , "
                               "[TABLE::TOTAL_REVENUE] )")
    assert meas["role"] == "measure" and meas["flag"] == "--role measure"
    assert meas["label"] == "KPI that rolls up" and meas["column_type"] == "MEASURE"
    assert meas["formula"] == ("safe_divide ( sum ( [TABLE::TOTAL_REVENUE] ) - sum ( "
                               "[TABLE::TOTAL_COGS] ) , sum ( [TABLE::TOTAL_REVENUE] ) )")
    assert attr["formula_editor"].startswith("safe_divide ( TOTAL_REVENUE")
    assert "per row" in attr["meaning"] and "ratio of totals" in meas["meaning"]
    # the default output is unchanged: still the row-level translation
    assert r["formula"] == attr["formula"] and r["role"] == "ATTRIBUTE"


def test_role_options_do_not_duplicate_references():
    r = translate(MARGIN, "excel")
    assert [x["source"] for x in r["references"]] == ["TOTAL_REVENUE", "TOTAL_COGS"]


@pytest.mark.parametrize("role", ["measure", "attribute"])
def test_ratio_with_role_is_not_ambiguous(role):
    r = translate(MARGIN, "excel", role=role)
    assert r["role_ambiguous"] is False and r["role_options"] == []


@pytest.mark.parametrize("expr", [
    "=[@TOTAL_REVENUE]-[@TOTAL_COGS]",        # additive: Σ per row = Σa - Σb anyway
    "=[@TOTAL_REVENUE]/100",                   # scaling by a constant is not a ratio
    "=SUM(T[a])/SUM(T[b])",                    # already aggregated: one answer
    CONCAT,
])
def test_non_ratio_is_not_ambiguous(expr):
    r = translate(expr, "excel")
    assert r["role_ambiguous"] is False and r["role_options"] == []


def test_ratio_whose_measure_form_needs_review_is_not_ambiguous():
    # 1 / x has no ratio-of-totals form: only the per-row reading exists
    r = translate("=1/[@SEATS]", "excel")
    assert r["role_ambiguous"] is False


def test_google_sheets_ratio_is_ambiguous():
    assert translate("=A2/B2", "google_sheets",
                     _ctx({"A": "T.NUM", "B": "T.DEN"}))["role_ambiguous"] is True


def test_has_ratio():
    assert has_ratio("safe_divide ( [T::a] , [T::b] )")
    assert has_ratio("[T::a] / [T::b]")
    assert not has_ratio("[T::a] / 100")
    assert not has_ratio(None)
