import pytest
from ts_cli.aggregate.sqlgen import (build_select, build_profile_sql,
                                     build_base_count_sql, build_ddl,
                                     UnsupportedModelError)
from ts_cli.aggregate.measures import classify_measure, build_rewrite_plans

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


def test_star_join_pruned_to_needed_tables():
    # Fix 1 (CRITICAL, original intent): star FACT->{DIM, DIM2} with a
    # candidate needing only DIM must not emit an unnecessary DIM2 join.
    #
    # Post open-item #11 fix (see test_inner_joined_unreferenced_table_is_
    # retained below): an INNER-joined table reachable from root is now
    # ALWAYS retained even when unreferenced, because dropping a mandatory
    # INNER join can silently keep fact rows the primary Model's canonical
    # query would exclude (nullable/orphan FK) — wrong totals. That
    # deterministic safe rule means an unreferenced DIM2 joined via INNER
    # would now correctly be *kept*, not pruned, so this test's DIM2 join is
    # changed to LEFT_OUTER to preserve its original intent (pruning a
    # genuinely optional/unreferenced dimension) — a LEFT_OUTER join to an
    # unreferenced table never changes the root row set, so pruning it
    # remains correct and desirable.
    model = {"model": {
        "model_tables": [
            {"name": "FACT", "joins": [
                {"with": "DIM", "on": "[FACT::CAT_ID] = [DIM::CAT_ID]",
                 "type": "INNER", "cardinality": "MANY_TO_ONE"},
                {"with": "DIM2", "on": "[FACT::D2_ID] = [DIM2::D2_ID]",
                 "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]},
            {"name": "DIM"}, {"name": "DIM2"},
        ],
        "columns": MODEL["model"]["columns"] + [
            {"name": "Region", "column_id": "DIM2::REGION",
             "properties": {"column_type": "ATTRIBUTE"}}],
    }}
    tables = dict(TABLES)
    tables["DIM2"] = {"table": {"db": "SALESDB", "schema": "PUBLIC",
                                "db_table": "DIM_REGION",
                                "columns": [{"name": "REGION", "db_column_name": "REGION"},
                                            {"name": "D2_ID", "db_column_name": "D2_ID"}]}}
    sql = build_select(model, tables, CAND, PLANS, dialect="snowflake")
    assert 'JOIN "SALESDB"."PUBLIC"."DIM_CATEGORY" "DIM"' in sql
    assert "DIM_REGION" not in sql
    assert "DIM2" not in sql


def test_inner_joined_unreferenced_table_is_retained():
    # Fix 3 (IMPORTANT, open-item #11): FACT INNER JOIN DIM must be retained
    # even when the candidate selects no DIM column — dropping a mandatory
    # INNER join would silently keep FACT rows the primary Model's canonical
    # query excludes (nullable/orphan FK), producing wrong totals.
    cand = {"id": "cand_1", "dimensions": [], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0],
            "flags": []}
    sql = build_select(MODEL, TABLES, cand, PLANS, dialect="snowflake")
    assert 'JOIN "SALESDB"."PUBLIC"."DIM_CATEGORY" "DIM"' in sql


def test_left_outer_joined_unreferenced_table_is_pruned():
    # Fix 3 counterpart: a LEFT_OUTER join to an unreferenced table never
    # changes the root row set (it preserves all root rows regardless of
    # match), so pruning it when unreferenced remains correct.
    model = {"model": {
        "model_tables": [
            {"name": "FACT", "joins": [
                {"with": "DIM", "on": "[FACT::CAT_ID] = [DIM::CAT_ID]",
                 "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]},
            {"name": "DIM"},
        ],
        "columns": MODEL["model"]["columns"],
    }}
    cand = {"id": "cand_1", "dimensions": [], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0],
            "flags": []}
    sql = build_select(model, TABLES, cand, PLANS, dialect="snowflake")
    assert "DIM_CATEGORY" not in sql
    assert "JOIN" not in sql


def test_reversed_outer_join_traversal_swaps_type():
    # Fix 2 (IMPORTANT): FACT LEFT_OUTER DIM traversed from root DIM must emit
    # RIGHT JOIN FACT (keep all FACT rows), not LEFT JOIN FACT.
    model = {"model": {
        "model_tables": [
            {"name": "DIM"},
            {"name": "FACT", "joins": [
                {"with": "DIM", "on": "[FACT::CAT_ID] = [DIM::CAT_ID]",
                 "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}]},
        ],
        "columns": MODEL["model"]["columns"],
    }}
    sql = build_select(model, TABLES, CAND, PLANS, dialect="snowflake")
    assert 'FROM "SALESDB"."PUBLIC"."DIM_CATEGORY" "DIM"' in sql
    assert ('RIGHT JOIN "SALESDB"."PUBLIC"."FACT_SALES" "FACT" '
            'ON "FACT"."CAT_ID" = "DIM"."CAT_ID"') in sql
    assert "LEFT JOIN" not in sql


def test_quote_char_in_identifier_is_escaped():
    # Fix 3 (IMPORTANT): quote chars inside display names must be escaped.
    model = {"model": {
        "model_tables": MODEL["model"]["model_tables"],
        "columns": [
            {"name": "Sales", "column_id": "FACT::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": 'Net "Adj" Category', "column_id": "DIM::CATEGORY",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
    }}
    cand = {"id": "cand_1", "dimensions": ['Net "Adj" Category'],
            "date_column": None, "bucket": None,
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, TABLES, cand, PLANS, dialect="snowflake")
    assert 'AS "Net ""Adj"" Category"' in sql
    sql_bq = build_select(model, TABLES, cand, PLANS, dialect="bigquery")
    assert 'AS `Net "Adj" Category`' in sql_bq  # double quotes fine in backticks


def test_backtick_in_identifier_escaped_per_dialect():
    model = {"model": {
        "model_tables": MODEL["model"]["model_tables"],
        "columns": [
            {"name": "Sales", "column_id": "FACT::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Cat `X`", "column_id": "DIM::CATEGORY",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
    }}
    cand = {"id": "cand_1", "dimensions": ["Cat `X`"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0],
            "flags": []}
    dbx = build_select(model, TABLES, cand, PLANS, dialect="databricks")
    assert "AS `Cat ``X```" in dbx  # databricks doubles the backtick
    bq = build_select(model, TABLES, cand, PLANS, dialect="bigquery")
    assert "AS `Cat \\`X\\``" in bq  # bigquery backslash-escapes it


def test_unknown_table_prefix_raises_unsupported():
    # Fix 4 (IMPORTANT): aliased/unknown model_tables prefixes must raise
    # UnsupportedModelError (downstream fallback keys on it), not KeyError.
    model = {"model": {
        "model_tables": MODEL["model"]["model_tables"],
        "columns": MODEL["model"]["columns"] + [
            {"name": "Alias Dim", "column_id": "FACT_A::CATEGORY",
             "properties": {"column_type": "ATTRIBUTE"}}],
    }}
    cand = {"id": "cand_1", "dimensions": ["Alias Dim"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0],
            "flags": []}
    with pytest.raises(UnsupportedModelError, match="FACT_A.*not resolvable"):
        build_select(model, TABLES, cand, PLANS, dialect="snowflake")


def test_formula_backed_measure_column_does_not_crash_col_map():
    # Fix 1 (CRITICAL): every ThoughtSpot formula appears in model.columns[]
    # with a formula_id and NO column_id (the physical-vs-formula column
    # rule). _col_map previously did `c["column_id"].split("::", 1)` for
    # every column unconditionally, so a formula-backed MEASURE (formula_id,
    # no column_id — e.g. an AVG measure) raised a bare KeyError here before
    # this fix, crashing `ts aggregate profile`/`generate` (both call
    # build_select). After the fix, the measure's stored components resolve
    # via their source_column physical columns ("Sales"), not via the
    # formula entry itself.
    model = {"model": {
        "model_tables": MODEL["model"]["model_tables"],
        "formulas": [{"id": "formula_Avg Sale", "name": "Avg Sale",
                      "expr": "average ( [Sales] )"}],
        "columns": MODEL["model"]["columns"] + [
            {"name": "Avg Sale", "formula_id": "formula_Avg Sale",
             "properties": {"column_type": "MEASURE"}}],
    }}
    plans = build_rewrite_plans(model)
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Avg Sale"], "covered": [0],
            "flags": []}
    sql = build_select(model, TABLES, cand, plans, dialect="snowflake")
    assert 'SUM("FACT"."AMOUNT") AS "avg_sale_sum"' in sql
    assert 'COUNT("FACT"."AMOUNT") AS "avg_sale_cnt"' in sql


def test_nested_formula_source_column_raises_unsupported_not_keyerror():
    # Fix 2 (IMPORTANT): a measure that decomposes to a source_column that is
    # itself a formula (not a physical display name resolvable via
    # column_id) must raise UnsupportedModelError, not a bare KeyError, so
    # callers (`profile`/`generate`) fall back to the documented "skip
    # candidate / manual SQL" path instead of crashing.
    model = {"model": {
        "model_tables": MODEL["model"]["model_tables"],
        "formulas": [
            {"id": "formula_Net Sale", "name": "Net Sale",
             "expr": "[Sales] - [Discount]"},
            {"id": "formula_Avg Net Sale", "name": "Avg Net Sale",
             "expr": "average ( [Net Sale] )"},
        ],
        "columns": MODEL["model"]["columns"] + [
            {"name": "Net Sale", "formula_id": "formula_Net Sale",
             "properties": {"column_type": "MEASURE"}},
            {"name": "Avg Net Sale", "formula_id": "formula_Avg Net Sale",
             "properties": {"column_type": "MEASURE"}},
        ],
    }}
    plans = build_rewrite_plans(model)
    cand = {"id": "cand_1", "dimensions": ["Category"], "date_column": None,
            "bucket": None, "measure_columns": ["Avg Net Sale"],
            "covered": [0], "flags": []}
    with pytest.raises(UnsupportedModelError):
        build_select(model, TABLES, cand, plans, dialect="snowflake")


def test_ddl_dialects():
    sf = build_ddl("SELECT 1", "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                   warehouse="WH")
    assert sf.startswith("CREATE OR REPLACE DYNAMIC TABLE SALESDB.PUBLIC.FACT_AGG_M")
    assert "TARGET_LAG = '1 hour'" in sf and "WAREHOUSE = WH" in sf
    dbx = build_ddl("SELECT 1", "cat.sch.agg", "databricks")
    assert dbx.startswith("CREATE OR REPLACE MATERIALIZED VIEW cat.sch.agg")
    bq = build_ddl("SELECT 1", "proj.ds.agg", "bigquery", materialization="ctas")
    assert bq.startswith("CREATE OR REPLACE TABLE proj.ds.agg AS")
