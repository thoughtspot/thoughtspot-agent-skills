import pytest

from ts_cli.aggregate.measures import classify_measure
from ts_cli.aggregate.sqlgen import UnsupportedModelError
from ts_cli.aggregate.spotql_aggregate import (
    UnsupportedMeasureError, build_spotql, wrap_as_ddl,
)

PLANS = {"Sales": classify_measure("Sales", aggregation="SUM")}


def test_build_spotql_two_dims_bucketed_date_sum_measure():
    cand = {"id": "cand_1", "dimensions": ["Category", "Region"],
            "date_column": "Order Date", "bucket": "MONTHLY",
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, PLANS, "Sales Model")
    assert 'FROM "Sales Model" AS "t1"' in spotql
    assert '"t1"."Category"' in spotql
    assert '"t1"."Region"' in spotql
    # Task 19: raw date column by display name, NO bucket function — SpotQL
    # has none (start_of_month(...) -> QUERY_GEN_ERROR, live-proven).
    assert '"t1"."Order Date"' in spotql
    assert "start_of_month" not in spotql
    assert "DATE_TRUNC" not in spotql
    # Task 19: measure referenced by its OWN display name, never wrapped in a
    # real aggregate function over a physical column (SUM(col) -> also
    # QUERY_GEN_ERROR, live-proven) — selecting "Sales" bare yields the
    # already-aggregated value because the model carries its aggregation.
    assert '"t1"."Sales" AS "sales_sum"' in spotql
    assert "SUM(" not in spotql
    group_line = next(l for l in spotql.splitlines() if l.startswith("GROUP BY"))
    assert '"t1"."Category"' in group_line
    assert '"t1"."Region"' in group_line
    assert '"t1"."Order Date"' in group_line
    # Measures never appear in GROUP BY.
    assert "sales_sum" not in group_line
    assert descriptors == [
        {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
        {"alias": "Region", "kind": "dim", "bucket": None, "reagg": None},
        {"alias": "Order Date", "kind": "date", "bucket": "MONTHLY", "reagg": None},
        {"alias": "sales_sum", "kind": "measure", "bucket": None, "reagg": "SUM"},
    ]


def test_build_spotql_never_aliases_plain_columns_or_dates():
    # spotql-rules.md: "Never alias a plain Model column" — dims and date
    # columns (bucketed or raw — Task 19 never emits a bucket function, so
    # every date is now a plain column reference) must be selected bare, no AS.
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": "Order Date",
            "bucket": "MONTHLY", "measure_columns": [], "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, {}, "Sales Model")
    assert '"t1"."Category"' in spotql
    assert '"t1"."Category" AS' not in spotql
    assert '"t1"."Order Date"' in spotql
    assert '"t1"."Order Date" AS' not in spotql
    assert descriptors == [
        {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
        {"alias": "Order Date", "kind": "date", "bucket": "MONTHLY", "reagg": None},
    ]


def test_build_spotql_min_max_count_measures_by_display_name():
    plans = {
        "Highest Sale": classify_measure("Highest Sale", aggregation="MAX"),
        "Lowest Sale": classify_measure("Lowest Sale", aggregation="MIN"),
        "Order Count": classify_measure("Order Count", aggregation="COUNT"),
    }
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Highest Sale", "Lowest Sale",
                                                "Order Count"],
            "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, plans, "Sales Model")
    assert '"t1"."Highest Sale" AS "highest_sale_max"' in spotql
    assert '"t1"."Lowest Sale" AS "lowest_sale_min"' in spotql
    assert '"t1"."Order Count" AS "order_count_cnt"' in spotql
    assert "MAX(" not in spotql and "MIN(" not in spotql and "COUNT(" not in spotql
    assert descriptors == [
        {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
        {"alias": "highest_sale_max", "kind": "measure", "bucket": None, "reagg": "MAX"},
        {"alias": "lowest_sale_min", "kind": "measure", "bucket": None, "reagg": "MIN"},
        # COUNT's reagg is SUM (re-summing partial counts across the grain).
        {"alias": "order_count_cnt", "kind": "measure", "bucket": None, "reagg": "SUM"},
    ]


def test_build_spotql_avg_measure_raises_unsupported():
    # AVG decomposes to two stored components (sum + count) — SpotQL can only
    # reference the whole "Avg Sale" formula by name (yields the ratio, not
    # the parts), so there's no valid single-expression SpotQL for either
    # component. Must raise cleanly, never emit a guess at invalid SpotQL.
    plans = {"Avg Sale": classify_measure("Avg Sale", expr="average ( [Sales] )")}
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Avg Sale"], "covered": [0],
            "flags": []}
    with pytest.raises(UnsupportedMeasureError, match="Avg Sale.*2 stored components"):
        build_spotql(cand, plans, "Sales Model")


def test_build_spotql_ratio_measure_raises_unsupported():
    plans = {"Margin": classify_measure("Margin", expr="sum ( [Profit] ) / sum ( [Sales] )")}
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Margin"], "covered": [0],
            "flags": []}
    with pytest.raises(UnsupportedMeasureError, match="Margin"):
        build_spotql(cand, plans, "Sales Model")


def test_build_spotql_multi_date_grain_both_dates_present():
    cand = {"id": "cand_1", "dimensions": ["Category"],
            "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"},
                            {"column": "Shipped Date", "bucket": None}],
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, PLANS, "Sales Model")
    assert '"t1"."Order Date"' in spotql
    assert '"t1"."Shipped Date"' in spotql
    assert "start_of_month" not in spotql
    group_line = next(l for l in spotql.splitlines() if l.startswith("GROUP BY"))
    assert '"t1"."Order Date"' in group_line
    assert '"t1"."Shipped Date"' in group_line
    assert descriptors == [
        {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
        {"alias": "Order Date", "kind": "date", "bucket": "MONTHLY", "reagg": None},
        {"alias": "Shipped Date", "kind": "date", "bucket": None, "reagg": None},
        {"alias": "sales_sum", "kind": "measure", "bucket": None, "reagg": "SUM"},
    ]


def test_build_spotql_emits_one_item_per_component_no_dedup():
    # Two measures whose plans decompose to the identical (source_column,
    # func) pair — a RAW SUM measure `Sales` and a summing formula
    # `Total Revenue = sum([Sales])`, both -> ("Sales", "SUM"). build_spotql
    # must NOT dedup them: generate.build_aggregate_table_spec declares one
    # physical column per component (sales_sum AND total_revenue_sum), so a
    # deduped SELECT would leave total_revenue_sum with no backing column
    # (Table TML schema mismatch). One SELECT item + one descriptor per
    # measure, in order — each referencing its OWN display name.
    plans = {
        "Sales": classify_measure("Sales", aggregation="SUM"),
        "Total Revenue": classify_measure("Total Revenue", expr="sum ( [Sales] )"),
    }
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales", "Total Revenue"],
            "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, plans, "Sales Model")
    assert '"t1"."Sales" AS "sales_sum"' in spotql
    assert '"t1"."Total Revenue" AS "total_revenue_sum"' in spotql
    assert [d["alias"] for d in descriptors] == ["Category", "sales_sum", "total_revenue_sum"]


def test_build_spotql_aliases_match_table_spec_component_order():
    # Cross-check against generate.build_aggregate_table_spec: the measure-
    # component tail of build_spotql's descriptor aliases must equal the
    # aggregate Table's MEASURE column names, in the SAME order, so ca_N <->
    # descriptor alias <-> table-spec column are 1:1. Uses the raw-measure +
    # summing-formula model that reaches the (previously dedup-divergent) case.
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

    _spotql, descriptors = build_spotql(cand, plans, "Sales Model")
    spec = build_aggregate_table_spec(cand, plans, model, db="DB", schema="S",
                                      table_name="AGG", connection_name="C")
    measure_cols = [c["name"] for c in spec["columns"] if c["column_type"] == "MEASURE"]
    aliases = [d["alias"] for d in descriptors]
    # Tail of aliases (after the "Category" dim) is the component list.
    assert aliases[1:] == measure_cols == ["sales_sum", "total_revenue_sum"]


def test_build_spotql_no_group_by_when_no_dims_or_dates():
    cand = {"id": "cand_1", "dimensions": [], "date_column": None, "bucket": None,
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, PLANS, "Sales Model")
    assert "GROUP BY" not in spotql
    assert descriptors == [
        {"alias": "sales_sum", "kind": "measure", "bucket": None, "reagg": "SUM"},
    ]


def test_build_spotql_skips_non_decomposable_measures():
    plans = {"Distinct Customers": classify_measure(
        "Distinct Customers", aggregation="COUNT_DISTINCT")}
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Distinct Customers"],
            "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, plans, "Sales Model")
    assert descriptors == [{"alias": "Category", "kind": "dim", "bucket": None, "reagg": None}]
    assert "GROUP BY" in spotql


def test_build_spotql_quotes_identifiers_with_embedded_quotes():
    cand = {"id": "cand_1", "dimensions": ['Net "Adj" Category'],
            "date_column": None, "bucket": None, "measure_columns": [],
            "covered": [0], "flags": []}
    spotql, descriptors = build_spotql(cand, {}, "Sales Model")
    assert '"t1"."Net ""Adj"" Category"' in spotql
    assert descriptors == [
        {"alias": 'Net "Adj" Category', "kind": "dim", "bucket": None, "reagg": None},
    ]


# --- wrap_as_ddl -------------------------------------------------------------

# Dateless / no-bucket fixture: the pre-Task-19 pass-through shape is
# unaffected by this task's changes (no bucketed date -> no outer GROUP BY).
TS_SQL_NO_BUCKET = (
    'SELECT "ta_1"."CATEGORY_NAME" AS "ca_1", "ta_1"."ORDER_DT" AS "ca_2", '
    'SUM("ta_1"."AMOUNT") AS "ca_3" '
    'FROM "SALESDB"."PUBLIC"."FACT_SALES" "ta_1" '
    'GROUP BY "ca_1", "ca_2" LIMIT 100000'
)
DESCRIPTORS_NO_BUCKET = [
    {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
    {"alias": "Order Date", "kind": "date", "bucket": None, "reagg": None},
    {"alias": "sales_sum", "kind": "measure", "bucket": None, "reagg": "SUM"},
]

# Bucketed fixture: build_spotql groups at the RAW date grain (Task 19), so
# ThoughtSpot's compiled SQL is grouped on the raw date column, not a bucket.
# wrap_as_ddl's outer aggregating SELECT does the bucketing + re-aggregation.
TS_SQL_BUCKETED = (
    'SELECT "ta_1"."CATEGORY_NAME" AS "ca_1", "ta_1"."ORDER_DT" AS "ca_2", '
    'SUM("ta_1"."AMOUNT") AS "ca_3" '
    'FROM "SALESDB"."PUBLIC"."FACT_SALES" "ta_1" '
    'GROUP BY "ca_1", "ca_2" LIMIT 100000'
)
DESCRIPTORS_BUCKETED = [
    {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
    {"alias": "Order Date", "kind": "date", "bucket": "MONTHLY", "reagg": None},
    {"alias": "sales_sum", "kind": "measure", "bucket": None, "reagg": "SUM"},
]


def test_wrap_as_ddl_strips_limit_and_maps_positional_aliases():
    ddl = wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                      "SALESDB.PUBLIC.FACT_AGG_M", "snowflake", materialization="ctas")
    assert "LIMIT" not in ddl
    # ThoughtSpot emits the inner derived columns as quoted-lowercase "ca_N"
    # (case-sensitive). The outer SELECT must reference them quoted too, or
    # Snowflake folds an unquoted ca_1 to CA_1 and fails to bind ("invalid
    # identifier") at execution time.
    assert '"ca_1" AS "Category"' in ddl
    assert '"ca_2" AS "Order Date"' in ddl
    assert '"ca_3" AS "sales_sum"' in ddl
    assert 'ca_1 AS' not in ddl  # never the unquoted, case-folding form
    # Pass-through (no bucketed date): only ONE GROUP BY in the whole DDL —
    # the inner (preserved) one; the outer wrapper never adds its own.
    assert ddl.count("GROUP BY") == 1
    assert "GROUP BY \"ca_1\", \"ca_2\"" in ddl  # inner content otherwise intact
    assert ddl.startswith("CREATE OR REPLACE TABLE SALESDB.PUBLIC.FACT_AGG_M AS")
    assert 'FROM (\n' in ddl and ') "src"' in ddl


def test_wrap_as_ddl_leaves_sql_without_a_limit_intact():
    no_limit_sql = TS_SQL_NO_BUCKET.rsplit(" LIMIT 100000", 1)[0]
    ddl = wrap_as_ddl(no_limit_sql, DESCRIPTORS_NO_BUCKET,
                      "SALESDB.PUBLIC.FACT_AGG_M", "snowflake", materialization="ctas")
    assert 'GROUP BY "ca_1", "ca_2"' in ddl


def test_wrap_as_ddl_snowflake_dynamic_table_shape():
    ddl = wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                      "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                      materialization="dynamic", warehouse="WH")
    assert ddl.startswith("CREATE OR REPLACE DYNAMIC TABLE SALESDB.PUBLIC.FACT_AGG_M")
    assert "TARGET_LAG = '1 hour'" in ddl and "WAREHOUSE = WH" in ddl


def test_wrap_as_ddl_databricks_mview_shape_and_quoting():
    ddl = wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                      "cat.sch.agg", "databricks", materialization="mview")
    assert ddl.startswith("CREATE OR REPLACE MATERIALIZED VIEW cat.sch.agg AS")
    assert "`ca_1` AS `Category`" in ddl
    assert '`src`' in ddl


def test_wrap_as_ddl_bigquery_ctas_shape():
    ddl = wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                      "proj.ds.agg", "bigquery", materialization="ctas")
    assert ddl.startswith("CREATE OR REPLACE TABLE proj.ds.agg AS")
    assert "`ca_1` AS `Category`" in ddl


def test_wrap_as_ddl_snowflake_materialized_view_guard_still_fires():
    with pytest.raises(UnsupportedModelError, match="002212"):
        wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                   "SALESDB.PUBLIC.FACT_AGG_M", "snowflake", materialization="mview")


def test_wrap_as_ddl_auto_resolves_per_dialect_default():
    sf = wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                     "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                     materialization="auto", warehouse="WH")
    assert "DYNAMIC TABLE" in sf
    bq = wrap_as_ddl(TS_SQL_NO_BUCKET, DESCRIPTORS_NO_BUCKET,
                     "proj.ds.agg", "bigquery", materialization="auto")
    assert bq.startswith("CREATE MATERIALIZED VIEW proj.ds.agg")


def test_wrap_as_ddl_bucketed_date_emits_outer_aggregating_select():
    # The live-proven shape: CREATE TABLE AS SELECT dims,
    # DATE_TRUNC('MONTH', ca_date), SUM(ca_measure) FROM (spotql_sql) src
    # GROUP BY dims, DATE_TRUNC(...).
    ddl = wrap_as_ddl(TS_SQL_BUCKETED, DESCRIPTORS_BUCKETED,
                      "SALESDB.PUBLIC.FACT_AGG_M", "snowflake", materialization="ctas")
    assert '"ca_1" AS "Category"' in ddl
    assert "DATE_TRUNC('MONTH', \"ca_2\") AS \"Order Date\"" in ddl
    assert 'SUM("ca_3") AS "sales_sum"' in ddl
    group_line = next(l for l in ddl.splitlines() if l.startswith("GROUP BY"))
    assert '"ca_1"' in group_line
    assert "DATE_TRUNC('MONTH', \"ca_2\")" in group_line
    assert "sales_sum" not in group_line  # measures never in the outer GROUP BY


def test_wrap_as_ddl_bigquery_bucketed_date_trunc_argument_order():
    ddl = wrap_as_ddl(TS_SQL_BUCKETED, DESCRIPTORS_BUCKETED,
                      "proj.ds.agg", "bigquery", materialization="ctas")
    assert "DATE_TRUNC(`ca_2`, MONTH) AS `Order Date`" in ddl


def test_wrap_as_ddl_bucketed_multi_date_mixes_raw_and_bucketed_grains():
    descriptors = [
        {"alias": "Category", "kind": "dim", "bucket": None, "reagg": None},
        {"alias": "Order Date", "kind": "date", "bucket": "MONTHLY", "reagg": None},
        {"alias": "Shipped Date", "kind": "date", "bucket": None, "reagg": None},
        {"alias": "sales_sum", "kind": "measure", "bucket": None, "reagg": "SUM"},
    ]
    ts_sql = (
        'SELECT "ta_1"."CATEGORY_NAME" AS "ca_1", "ta_1"."ORDER_DT" AS "ca_2", '
        '"ta_1"."SHIPPED_DT" AS "ca_3", SUM("ta_1"."AMOUNT") AS "ca_4" '
        'FROM "SALESDB"."PUBLIC"."FACT_SALES" "ta_1" '
        'GROUP BY "ca_1", "ca_2", "ca_3"'
    )
    ddl = wrap_as_ddl(ts_sql, descriptors, "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                      materialization="ctas")
    assert "DATE_TRUNC('MONTH', \"ca_2\") AS \"Order Date\"" in ddl
    assert '"ca_3" AS "Shipped Date"' in ddl  # raw grain: positional rename, still grouped
    group_line = next(l for l in ddl.splitlines() if l.startswith("GROUP BY"))
    assert '"ca_1"' in group_line and '"ca_3"' in group_line
    assert "DATE_TRUNC('MONTH', \"ca_2\")" in group_line


def test_wrap_as_ddl_bucketed_snowflake_materialized_view_guard_still_fires():
    with pytest.raises(UnsupportedModelError, match="002212"):
        wrap_as_ddl(TS_SQL_BUCKETED, DESCRIPTORS_BUCKETED,
                   "SALESDB.PUBLIC.FACT_AGG_M", "snowflake", materialization="mview")
