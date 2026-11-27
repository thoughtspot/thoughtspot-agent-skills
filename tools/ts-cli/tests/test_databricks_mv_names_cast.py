"""BL-631 (display titles keep a name written for people) and BL-633 (a cast to text
is emitted, not dropped)."""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import translate_sql_expr
from ts_cli.databricks.mv_translate import display_title, make_resolver


@pytest.mark.parametrize("name,title", [
    ("order_month", "Order Month"),
    ("ORDER_DATE", "Order Date"),
    ("revenue", "Revenue"),
    ("SKU Type", "SKU Type"),
    ("Is eBook", "Is eBook"),
    ("API Channel", "API Channel"),
    ("CustomerName", "CustomerName"),
])
def test_display_title(name, title):
    assert display_title({"name": name}) == title


def test_display_name_wins():
    assert display_title({"name": "x_y", "display_name": "My X"}) == "My X"


R = make_resolver({"source": "FACT"})


@pytest.mark.parametrize("sql,ts", [
    ("CAST(source.K AS STRING)", 'sql_string_op ( "CAST({0} AS STRING)" , [FACT::K] )'),
    ("CAST(source.K AS VARCHAR(8))", 'sql_string_op ( "CAST({0} AS VARCHAR(8))" , [FACT::K] )'),
    ("CAST(SUM(source.K) AS STRING)", "to_string ( sum ( [FACT::K] ) )"),
])
def test_cast_to_text_is_kept(sql, ts):
    assert translate_sql_expr(sql, R) == ts


def test_cast_inside_a_pass_through_reaches_the_warehouse():
    out = translate_sql_expr("TO_DATE(CAST(source.K AS STRING), 'yyyyMMdd')", R)
    assert 'CAST({0} AS STRING)' in out and out.startswith("sql_date_op (")


def test_numeric_widening_is_still_a_no_op():
    assert translate_sql_expr("CAST(source.K AS DOUBLE)", R) == "[FACT::K]"


@pytest.mark.parametrize("sql,ts", [
    ("CAST(DATE_TRUNC('MONTH', source.D) AS DATE)", "start_of_month ( [FACT::D] )"),
    ("CAST(source.TS AS DATE)", "to_date ( [FACT::TS] )"),
])
def test_cast_to_date(sql, ts):
    assert translate_sql_expr(sql, R) == ts


# --- review round 1 (PR #771) ----------------------------------------------------
@pytest.mark.parametrize("name,title", [
    ("order month", "Order Month"),
    ("REVENUE", "Revenue"),
    ("net sales", "Net Sales"),
])
def test_lower_and_upper_names_are_title_cased(name, title):
    assert display_title({"name": name}) == title


@pytest.mark.parametrize("sql", [
    "CAST(DATE_TRUNC('MONTH', source.D) AS STRING)",   # TS start_of_month may be a TIMESTAMP
    "CAST(TRUNC(source.D, 'MM') AS STRING)",
    "CAST(MIN(source.S) AS STRING)",                   # text or date aggregate
    "CAST(MAX(source.D) AS STRING)",
    "CAST(CONCAT('max(', source.S) AS STRING)",
])
def test_cast_to_text_over_an_expression_is_refused(sql):
    from ts_cli.databricks.mv_sql import UntranslatableError
    with pytest.raises(UntranslatableError, match="warehouse type"):
        translate_sql_expr(sql, R)


@pytest.mark.parametrize("sql,ts", [
    ("CAST(NULL AS STRING)", "null"),
    ("CAST('abc' AS STRING)", "'abc'"),
    ("CAST(COUNT(source.K) AS STRING)", "to_string ( count ( [FACT::K] ) )"),
    ("CAST((DATE_TRUNC('MONTH', source.D)) AS DATE)", "( start_of_month ( [FACT::D] ) )"),
])
def test_cast_forms_left_alone_or_exact(sql, ts):
    assert translate_sql_expr(sql, R) == ts


def test_measure_ref_cast_to_text_is_refused():
    from ts_cli.databricks.mv_parse import parse_metric_view
    from ts_cli.databricks.mv_translate import translate_metric_view
    mv = """
version: 1.1
source: cat.sch.fact
dimensions:
  - name: k
    expr: source.K
measures:
  - name: revenue
    expr: SUM(source.AMOUNT)
  - name: revenue_text
    expr: CAST(MEASURE(revenue) AS STRING)
"""
    out = translate_metric_view(parse_metric_view(mv), {"source": "FACT"})
    assert "revenue_text" in {s["name"] for s in out["skipped"]}


def test_titles_differing_only_by_case_fail_loud():
    from ts_cli.databricks.mv_build_model import _check_no_duplicate_display_names
    with pytest.raises(ValueError, match="duplicate display title"):
        _check_no_duplicate_display_names([{"name": "SKU Type"}, {"name": "Sku Type"}])


# --- review round 2 (PR #771) ----------------------------------------------------
@pytest.mark.parametrize("sql", [
    "CONCAT(CAST(CAST(source.QTY AS DOUBLE) AS STRING), ' units')",  # '5.0' vs '5'
    "CAST(SUM(CAST(source.QTY AS DOUBLE)) AS STRING)",
    "CAST(SUM(source.A + source.B) AS STRING)",
    "CAST('x' = source.S AS STRING)",
])
def test_cast_to_text_decided_from_the_source(sql):
    from ts_cli.databricks.mv_sql import UntranslatableError
    with pytest.raises(UntranslatableError, match="warehouse type"):
        translate_sql_expr(sql, R)


@pytest.mark.parametrize("sql,ts", [
    ("CAST(COUNT(DISTINCT source.K) AS STRING)", "to_string ( unique count ( [FACT::K] ) )"),
    ("CAST(COUNT(*) AS STRING)", "to_string ( count ( 1 ) )"),
    ("CAST(AVG(source.K) AS STRING)", "to_string ( average ( [FACT::K] ) )"),
])
def test_cast_to_text_of_one_column_aggregate(sql, ts):
    assert translate_sql_expr(sql, R) == ts


def test_date_no_op_needs_one_whole_call():
    out = translate_sql_expr("CAST(TRUNC(source.D, 'MM') + 1 AS DATE)", R)
    assert out.startswith("to_date (")
