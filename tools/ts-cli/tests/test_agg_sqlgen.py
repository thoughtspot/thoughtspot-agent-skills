import pytest
from ts_cli.aggregate.sqlgen import (build_select, build_profile_sql,
                                     build_base_count_sql, build_ddl,
                                     UnsupportedModelError)
from ts_cli.aggregate.measures import classify_measure

MODEL = {"model": {
    "model_tables": [
        {"name": "FACT", "joins": [
            {"with": "DIM", "on": "[FACT::CAT_ID] = [DIM::CAT_ID]",
             "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "DIM"},
    ],
    "columns": [
        {"name": "Sales", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category", "column_id": "DIM::CATEGORY",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Order Date", "column_id": "FACT::ORDER_DT", "data_type": "DATE",
         "properties": {"column_type": "ATTRIBUTE"}},
    ],
}}
TABLES = {
    "FACT": {"table": {"db": "SALESDB", "schema": "PUBLIC", "db_table": "FACT_SALES",
                       "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                                   {"name": "CAT_ID", "db_column_name": "CAT_ID"},
                                   {"name": "ORDER_DT", "db_column_name": "ORDER_DT"}]}},
    "DIM": {"table": {"db": "SALESDB", "schema": "PUBLIC", "db_table": "DIM_CATEGORY",
                      "columns": [{"name": "CATEGORY", "db_column_name": "CATEGORY"},
                                  {"name": "CAT_ID", "db_column_name": "CAT_ID"}]}},
}
PLANS = {"Sales": classify_measure("Sales", aggregation="SUM")}
CAND = {"id": "cand_1", "dimensions": ["Category"], "date_column": "Order Date",
        "bucket": "MONTHLY", "measure_columns": ["Sales"], "covered": [0], "flags": []}


def test_build_select_joins_groups_and_truncates():
    sql = build_select(MODEL, TABLES, CAND, PLANS, dialect="snowflake")
    assert 'FROM "SALESDB"."PUBLIC"."FACT_SALES" "FACT"' in sql
    assert 'JOIN "SALESDB"."PUBLIC"."DIM_CATEGORY" "DIM" ON "FACT"."CAT_ID" = "DIM"."CAT_ID"' in sql
    assert 'DATE_TRUNC(\'MONTH\', "FACT"."ORDER_DT") AS "Order Date"' in sql
    assert 'SUM("FACT"."AMOUNT") AS "sales_sum"' in sql
    assert 'GROUP BY "DIM"."CATEGORY", DATE_TRUNC(\'MONTH\', "FACT"."ORDER_DT")' in sql


def test_bigquery_date_trunc_argument_order():
    sql = build_select(MODEL, TABLES, CAND, PLANS, dialect="bigquery")
    assert 'DATE_TRUNC(`FACT`.`ORDER_DT`, MONTH)' in sql


def test_referencing_join_raises_unsupported():
    model = {"model": {"model_tables": [
        {"name": "FACT", "joins": [{"with": "DIM", "referencing_join": "SYS_X"}]},
        {"name": "DIM"}], "columns": MODEL["model"]["columns"]}}
    with pytest.raises(UnsupportedModelError):
        build_select(model, TABLES, CAND, PLANS, dialect="snowflake")


def test_profile_and_base_sql():
    assert build_profile_sql("SELECT 1").startswith("SELECT COUNT(*) AS agg_rows FROM (")
    base = build_base_count_sql(MODEL, TABLES)
    assert base == 'SELECT COUNT(*) AS base_rows FROM "SALESDB"."PUBLIC"."FACT_SALES"'


def test_ddl_dialects():
    sf = build_ddl("SELECT 1", "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                   warehouse="WH")
    assert sf.startswith("CREATE OR REPLACE DYNAMIC TABLE SALESDB.PUBLIC.FACT_AGG_M")
    assert "TARGET_LAG = '1 hour'" in sf and "WAREHOUSE = WH" in sf
    dbx = build_ddl("SELECT 1", "cat.sch.agg", "databricks")
    assert dbx.startswith("CREATE OR REPLACE MATERIALIZED VIEW cat.sch.agg")
    bq = build_ddl("SELECT 1", "proj.ds.agg", "bigquery", materialization="ctas")
    assert bq.startswith("CREATE OR REPLACE TABLE proj.ds.agg AS")
