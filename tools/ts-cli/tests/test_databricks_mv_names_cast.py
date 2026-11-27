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
