"""BL-629, BL-630, BL-637: MV converter emission defects found converting three Metric
Views and validating the Models live (2026-11-26). Synthetic fixtures only."""
import pytest

from ts_cli.databricks.mv_build_model import build_model_tml_dbx
from ts_cli.databricks.mv_parse import parse_metric_view
from ts_cli.databricks.mv_translate import translate_metric_view
from ts_cli.sql_forms import sqlf_aggregate_window_values

TABLES = {"source": "FACT_ORDERS", "chan": "DIM_CHANNEL"}
JOINS = """
joins:
  - name: chan
    source: cat.sch.dim_channel
    "on": source.CHANNEL_KEY = chan.CHANNEL_KEY
"""


def _mv(body: str) -> dict:
    return parse_metric_view("version: 1.1\nsource: cat.sch.fact_orders\n" + JOINS + body)


def _exprs(parsed: dict) -> dict:
    out = translate_metric_view(parsed, TABLES)
    assert not out["skipped"], out["skipped"]
    return {e["name"]: e.get("ts_expr") for e in out["translated"]}


# --- BL-629 ---------------------------------------------------------------------------

DIMS = """
dimensions:
  - name: order_month
    expr: source.ORDER_DATE
    display_name: Order Month
  - name: order_day
    expr: "DATE_TRUNC('DAY', source.ORDER_DATE)"
    display_name: Order Day
  - name: Day Quarter
    expr: QUARTER(order_day)
  - name: Channel Description
    expr: chan.DESCRIPTION
  - name: Channel Group
    expr: "CASE WHEN `Channel Description` ILIKE '%web%' THEN 'Online' ELSE 'Other' END"
  - name: Is Web
    expr: "`channel group` = 'Online'"
measures:
  - name: Web Revenue
    expr: "SUM(CASE WHEN `Channel Group` = 'Online' THEN source.REVENUE ELSE 0 END)"
"""


def test_a_computed_dimension_is_referenced_by_its_formula_id():
    ex = _exprs(_mv(DIMS))
    assert ex["Day Quarter"] == "quarter_number ( [formula_Order Day] )"


def test_a_direct_dimension_is_referenced_by_its_column():
    assert "[DIM_CHANNEL::DESCRIPTION]" in _exprs(_mv(DIMS))["Channel Group"]


def test_dimension_names_match_case_insensitively():
    assert _exprs(_mv(DIMS))["Is Web"] == "[formula_Channel Group] = 'Online'"


def test_a_measure_can_reference_a_dimension():
    assert "[formula_Channel Group]" in _exprs(_mv(DIMS))["Web Revenue"]


def test_no_fake_fact_table_columns_are_emitted():
    for expr in _exprs(_mv(DIMS)).values():
        if expr:
            for bad in ("order_day]", "Channel Description]", "Channel Group]"):
                assert f"[FACT_ORDERS::{bad}" not in expr, expr


def test_a_qualified_name_is_always_a_column():
    ex = _exprs(_mv("""
dimensions:
  - name: Region
    expr: source.REGION
  - name: Region Upper
    expr: UPPER(source.Region)
"""))
    assert "[FACT_ORDERS::Region]" in ex["Region Upper"] and "formula_" not in ex["Region Upper"]


# Databricks scope, live-probed 2026-11-27 (DBSQL 2026.35): only `name` is an
# identifier; a dimension sees only the ones defined before it (and one of those
# shadows a same-named source column); a measure sees all; `filter:` sees columns.

SCOPE = """
dimensions:
  - name: early_ref
    expr: CONCAT('e:', region)
  - name: region
    expr: COALESCE(source.region, 'Unknown')
    display_name: Sales Region
  - name: late_ref
    expr: CONCAT('l:', region)
measures:
  - name: uk
    expr: COUNT(1) FILTER (WHERE region = 'UK')
  - name: by_label
    expr: COUNT(1) FILTER (WHERE sales_region = 'UK')
filter: region <> 'X'
"""


def test_a_dimension_sees_only_dimensions_defined_before_it():
    ex = _exprs(_mv(SCOPE))
    assert ex["early_ref"].endswith("[FACT_ORDERS::region] )"), ex["early_ref"]
    assert "[formula_Sales Region]" in ex["late_ref"]


def test_a_measure_sees_every_dimension():
    assert "[formula_Sales Region]" in _exprs(_mv(SCOPE))["uk"]


def test_a_display_name_is_a_label_not_an_identifier():
    assert "[FACT_ORDERS::sales_region]" in _exprs(_mv(SCOPE))["by_label"]


def test_the_global_filter_reads_source_columns():
    out = translate_metric_view(_mv(SCOPE), TABLES)
    assert out["filter"]["ts_expr"] == "[FACT_ORDERS::region] != 'X'"


def test_a_numeric_display_name_does_not_crash():
    ex = _exprs(_mv("""
dimensions:
  - name: yr
    expr: YEAR(source.ORDER_DATE)
    display_name: 2024
  - name: next_yr
    expr: yr + 1
"""))
    assert ex["next_yr"] == "[formula_2024] + 1"


# --- BL-630 ---------------------------------------------------------------------------

def test_a_column_and_a_formula_with_one_title_fail_loud():
    parsed = _mv("""
dimensions:
  - name: order_month
    expr: "DATE_TRUNC('MONTH', source.ORDER_DATE)"
    display_name: Month
  - name: Month
    expr: source.MONTH
measures:
  - name: Orders
    expr: COUNT(1)
""")
    translated = translate_metric_view(parsed, TABLES)
    with pytest.raises(ValueError, match=r"duplicate display title\(s\): \['Month'\]"):
        build_model_tml_dbx(model_name="m", parsed=parsed, translated_doc=translated,
                            tables=TABLES)


# --- BL-637 ---------------------------------------------------------------------------

FV = "first_value ( sum ( [T::a] ) , query_groups ( ) , { [T::d] } )"
LV = "last_value ( sum ( [T::b] ) , query_groups ( ) , { [T::d] } )"


@pytest.mark.parametrize("expr, want", [
    (FV, FV),
    (f"( {FV} )", f"( {FV} )"),
    (f"( ( {FV} ) + ( {LV} ) ) / 2", f"( ( sum ( {FV} ) ) + ( sum ( {LV} ) ) ) / 2"),
    (f"sum ( {FV} ) + 1", f"sum ( {FV} ) + 1"),
])
def test_window_values_in_arithmetic_are_aggregated(expr, want):
    assert sqlf_aggregate_window_values(expr) == want


def test_cross_measure_over_semi_additive_measures_is_aggregated():
    ex = _exprs(_mv("""
dimensions:
  - name: Order Date
    expr: source.ORDER_DATE
measures:
  - name: Opening
    expr: SUM(source.OPENING)
    window:
      - order: Order Date
        semiadditive: first
        range: current
  - name: Closing
    expr: SUM(source.CLOSING)
    window:
      - order: Order Date
        semiadditive: last
        range: current
  - name: Average Base
    expr: (MEASURE(`Opening`) + MEASURE(`Closing`)) / 2
"""))
    assert ex["Opening"].startswith("first_value (")
    assert ex["Average Base"].count("sum ( first_value") == 1
    assert ex["Average Base"].count("sum ( last_value") == 1


def test_a_windowed_measure_over_two_aggregates_is_aggregated():
    ex = _exprs(_mv("""
dimensions:
  - name: Order Date
    expr: source.ORDER_DATE
measures:
  - name: Net Balance
    expr: SUM(source.BAL) - SUM(source.OVERDRAFT)
    window:
      - order: Order Date
        semiadditive: last
        range: current
"""))
    assert ex["Net Balance"].count("sum ( last_value") == 2, ex["Net Balance"]


# --- review round 2: paths that keep the source-column reading -------------------------

LEAK = """
dimensions:
  - name: status
    expr: "CASE WHEN status = 'X' THEN 'Cancelled' ELSE 'Open' END"
  - name: region
    expr: "COALESCE(source.region, 'Unknown')"
  - name: region_total
    expr: SUM(source.net) OVER (PARTITION BY region)
measures:
  - name: share_cancelled
    expr: "SUM(source.amount) / (SELECT SUM(amount) FROM cat.sch.fact_orders WHERE status = 'X')"
"""


def test_a_scalar_subquery_reads_physical_columns_not_dimensions():
    ex = _exprs(_mv(LEAK))
    assert "[formula_Status]" not in ex["share_cancelled"], ex["share_cancelled"]
    assert "[FACT_ORDERS::status] = 'X'" in ex["share_cancelled"]


def test_an_lod_partition_reads_source_columns():
    ex = _exprs(_mv(LEAK))
    assert "{ [FACT_ORDERS::region] }" in ex["region_total"], ex["region_total"]
