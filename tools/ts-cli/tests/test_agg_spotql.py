import pytest

from ts_cli.aggregate.measures import classify_measure
from ts_cli.aggregate.sqlgen import UnsupportedModelError
from ts_cli.aggregate.spotql_aggregate import build_spotql, wrap_as_ddl

PLANS = {"Sales": classify_measure("Sales", aggregation="SUM")}


def test_build_spotql_two_dims_bucketed_date_sum_measure():
    cand = {"id": "cand_1", "dimensions": ["Category", "Region"],
            "date_column": "Order Date", "bucket": "MONTHLY",
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, PLANS, "Sales Model")
    assert 'FROM "Sales Model" AS "t1"' in spotql
    assert '"t1"."Category"' in spotql
    assert '"t1"."Region"' in spotql
    assert 'start_of_month("t1"."Order Date") AS "Order Date"' in spotql
    assert 'SUM("t1"."Sales") AS "sales_sum"' in spotql
    group_line = next(l for l in spotql.splitlines() if l.startswith("GROUP BY"))
    assert '"t1"."Category"' in group_line
    assert '"t1"."Region"' in group_line
    assert 'start_of_month("t1"."Order Date")' in group_line
    # Measures never appear in GROUP BY.
    assert "sales_sum" not in group_line
    assert aliases == ["Category", "Region", "Order Date", "sales_sum"]


def test_build_spotql_never_aliases_plain_columns():
    # spotql-rules.md: "Never alias a plain Model column" — dims and raw
    # (unbucketed) date columns must be selected bare, no AS.
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": "Order Date",
            "bucket": None, "measure_columns": [], "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, {}, "Sales Model")
    assert '"t1"."Category"' in spotql
    assert '"t1"."Category" AS' not in spotql
    assert '"t1"."Order Date"' in spotql
    assert '"t1"."Order Date" AS' not in spotql
    assert "start_of_" not in spotql  # no bucket fn for a raw grain
    assert aliases == ["Category", "Order Date"]


def test_build_spotql_avg_measure_two_component_items():
    plans = {"Avg Sale": classify_measure("Avg Sale", expr="average ( [Sales] )")}
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Avg Sale"], "covered": [0],
            "flags": []}
    spotql, aliases = build_spotql(cand, plans, "Sales Model")
    assert 'SUM("t1"."Sales") AS "avg_sale_sum"' in spotql
    assert 'COUNT("t1"."Sales") AS "avg_sale_cnt"' in spotql
    assert aliases == ["Category", "avg_sale_sum", "avg_sale_cnt"]


def test_build_spotql_multi_date_grain_both_dates_present():
    cand = {"id": "cand_1", "dimensions": ["Category"],
            "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                            {"column": "Shipped Date", "bucket": None}],
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, PLANS, "Sales Model")
    assert 'start_of_month("t1"."Order Date") AS "Order Date"' in spotql
    assert '"t1"."Shipped Date"' in spotql
    assert 'start_of_month("t1"."Shipped Date")' not in spotql
    group_line = next(l for l in spotql.splitlines() if l.startswith("GROUP BY"))
    assert 'start_of_month("t1"."Order Date")' in group_line
    assert '"t1"."Shipped Date"' in group_line
    assert aliases == ["Category", "Order Date", "Shipped Date", "sales_sum"]


def test_build_spotql_emits_one_item_per_component_no_dedup():
    # Two measures whose plans decompose to the identical (source_column,
    # func) pair — a RAW SUM measure `Sales` and a summing formula
    # `Total Revenue = sum([Sales])`, both -> ("Sales", "SUM"). build_spotql
    # must NOT dedup them: generate.build_aggregate_table_spec declares one
    # physical column per component (sales_sum AND total_revenue_sum), so a
    # deduped SELECT would leave total_revenue_sum with no backing column
    # (Table TML schema mismatch). Redundant identical sum() items are
    # harmless. One SELECT item + one output alias per component, in order.
    plans = {
        "Sales": classify_measure("Sales", aggregation="SUM"),
        "Total Revenue": classify_measure("Total Revenue", expr="sum ( [Sales] )"),
    }
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales", "Total Revenue"],
            "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, plans, "Sales Model")
    assert spotql.count('SUM("t1"."Sales")') == 2
    assert 'SUM("t1"."Sales") AS "sales_sum"' in spotql
    assert 'SUM("t1"."Sales") AS "total_revenue_sum"' in spotql
    assert aliases == ["Category", "sales_sum", "total_revenue_sum"]


def test_build_spotql_aliases_match_table_spec_component_order():
    # Cross-check against generate.build_aggregate_table_spec: the measure-
    # component tail of build_spotql's output_aliases must equal the aggregate
    # Table's MEASURE column names, in the SAME order, so ca_N <-> output
    # alias <-> table-spec column are 1:1. Uses the raw-measure + summing-
    # formula model that reaches the (previously dedup-divergent) case.
    from ts_cli.aggregate.generate import build_aggregate_table_spec
    from ts_cli.aggregate.measures import build_rewrite_plans

    model = {"model": {"name": "Sales Model", "columns": [
        {"name": "Category", "column_id": "FACT::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}],
        "formulas": [{"id": "f1", "name": "Total Revenue", "expr": "sum ( [Sales] )"}]}}
    model["model"]["columns"].append(
        {"name": "Total Revenue", "formula_id": "f1",
         "properties": {"column_type": "MEASURE"}})
    plans = build_rewrite_plans(model)
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales", "Total Revenue"],
            "covered": [0], "flags": []}

    _spotql, aliases = build_spotql(cand, plans, "Sales Model")
    spec = build_aggregate_table_spec(cand, plans, model, db="DB", schema="S",
                                      table_name="AGG", connection_name="C")
    measure_cols = [c["name"] for c in spec["columns"] if c["column_type"] == "MEASURE"]
    # Tail of aliases (after the "Category" dim) is the component list.
    assert aliases[1:] == measure_cols == ["sales_sum", "total_revenue_sum"]


def test_build_spotql_no_group_by_when_no_dims_or_dates():
    cand = {"id": "cand_1", "dimensions": [], "date_column": None, "bucket": None,
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, PLANS, "Sales Model")
    assert "GROUP BY" not in spotql
    assert aliases == ["sales_sum"]


def test_build_spotql_skips_non_decomposable_measures():
    plans = {"Distinct Customers": classify_measure(
        "Distinct Customers", aggregation="COUNT_DISTINCT")}
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Distinct Customers"],
            "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, plans, "Sales Model")
    assert aliases == ["Category"]
    assert "GROUP BY" in spotql


def test_build_spotql_quotes_identifiers_with_embedded_quotes():
    cand = {"id": "cand_1", "dimensions": ['Net "Adj" Category'],
            "date_column": None, "bucket": None, "measure_columns": [],
            "covered": [0], "flags": []}
    spotql, aliases = build_spotql(cand, {}, "Sales Model")
    assert '"t1"."Net ""Adj"" Category"' in spotql
    assert aliases == ['Net "Adj" Category']


# --- wrap_as_ddl -------------------------------------------------------------

TS_SQL = (
    'SELECT "ta_1"."CATEGORY_NAME" AS "ca_1", '
    'DATE_TRUNC(\'MONTH\', "ta_1"."ORDER_DT") AS "ca_2", '
    'SUM("ta_1"."AMOUNT") AS "ca_3" '
    'FROM "SALESDB"."PUBLIC"."FACT_SALES" "ta_1" '
    'GROUP BY "ca_1", "ca_2" LIMIT 100000'
)
ALIASES = ["Category", "Order Date", "sales_sum"]


def test_wrap_as_ddl_strips_limit_and_maps_positional_aliases():
    ddl = wrap_as_ddl(TS_SQL, ALIASES, "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                      materialization="ctas")
    assert "LIMIT" not in ddl
    # ThoughtSpot emits the inner derived columns as quoted-lowercase "ca_N"
    # (case-sensitive). The outer SELECT must reference them quoted too, or
    # Snowflake folds an unquoted ca_1 to CA_1 and fails to bind ("invalid
    # identifier") at execution time.
    assert '"ca_1" AS "Category"' in ddl
    assert '"ca_2" AS "Order Date"' in ddl
    assert '"ca_3" AS "sales_sum"' in ddl
    assert 'ca_1 AS' not in ddl  # never the unquoted, case-folding form
    assert "GROUP BY \"ca_1\", \"ca_2\"" in ddl  # inner content otherwise intact
    assert ddl.startswith("CREATE OR REPLACE TABLE SALESDB.PUBLIC.FACT_AGG_M AS")
    assert 'FROM (\n' in ddl and ') "src"' in ddl


def test_wrap_as_ddl_leaves_sql_without_a_limit_intact():
    no_limit_sql = TS_SQL.rsplit(" LIMIT 100000", 1)[0]
    ddl = wrap_as_ddl(no_limit_sql, ALIASES, "SALESDB.PUBLIC.FACT_AGG_M",
                      "snowflake", materialization="ctas")
    assert 'GROUP BY "ca_1", "ca_2"' in ddl


def test_wrap_as_ddl_snowflake_dynamic_table_shape():
    ddl = wrap_as_ddl(TS_SQL, ALIASES, "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                      materialization="dynamic", warehouse="WH")
    assert ddl.startswith("CREATE OR REPLACE DYNAMIC TABLE SALESDB.PUBLIC.FACT_AGG_M")
    assert "TARGET_LAG = '1 hour'" in ddl and "WAREHOUSE = WH" in ddl


def test_wrap_as_ddl_databricks_mview_shape_and_quoting():
    ddl = wrap_as_ddl(TS_SQL, ALIASES, "cat.sch.agg", "databricks",
                      materialization="mview")
    assert ddl.startswith("CREATE OR REPLACE MATERIALIZED VIEW cat.sch.agg AS")
    assert "`ca_1` AS `Category`" in ddl
    assert '`src`' in ddl


def test_wrap_as_ddl_bigquery_ctas_shape():
    ddl = wrap_as_ddl(TS_SQL, ALIASES, "proj.ds.agg", "bigquery",
                      materialization="ctas")
    assert ddl.startswith("CREATE OR REPLACE TABLE proj.ds.agg AS")
    assert "`ca_1` AS `Category`" in ddl


def test_wrap_as_ddl_snowflake_materialized_view_guard_still_fires():
    with pytest.raises(UnsupportedModelError, match="002212"):
        wrap_as_ddl(TS_SQL, ALIASES, "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                   materialization="mview")


def test_wrap_as_ddl_auto_resolves_per_dialect_default():
    sf = wrap_as_ddl(TS_SQL, ALIASES, "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                     materialization="auto", warehouse="WH")
    assert "DYNAMIC TABLE" in sf
    bq = wrap_as_ddl(TS_SQL, ALIASES, "proj.ds.agg", "bigquery", materialization="auto")
    assert bq.startswith("CREATE MATERIALIZED VIEW proj.ds.agg")
