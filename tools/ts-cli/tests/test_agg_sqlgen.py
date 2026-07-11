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

# --- referencing_join fixtures --------------------------------------------
# Minimal shapes lifted from a real 26.9 champ-staging export (Dunder Mifflin
# Sales) — see .superpowers/sdd/task-12-brief.md and
# .superpowers/sdd/dunder_assoc_sample.json (not shipped as a fixture; these
# are the extracted-down minimal pieces needed to exercise the resolver).
DM_TABLES = {
    "DM_ORDER_DETAIL": {"table": {
        "db": "DUNDERMIFFLIN", "schema": "PUBLIC", "db_table": "DM_ORDER_DETAIL",
        "columns": [{"name": "AMOUNT", "db_column_name": "AMOUNT"},
                    {"name": "ORDER_ID", "db_column_name": "ORDER_ID"},
                    {"name": "PRODUCT_ID", "db_column_name": "PRODUCT_ID"}],
        "joins_with": [
            {"name": "DM_ORDER_DETAIL_to_DM_ORDER", "destination": {"name": "DM_ORDER"},
             "on": "[DM_ORDER_DETAIL::ORDER_ID] = [DM_ORDER::ORDER_ID]", "type": "INNER"},
            {"name": "DM_ORDER_DETAIL_to_DM_PRODUCT", "destination": {"name": "DM_PRODUCT"},
             "on": "[DM_ORDER_DETAIL::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]", "type": "INNER"},
        ],
    }},
    "DM_ORDER": {"table": {
        "db": "DUNDERMIFFLIN", "schema": "PUBLIC", "db_table": "DM_ORDER",
        "columns": [{"name": "STATUS", "db_column_name": "STATUS"},
                    {"name": "ORDER_ID", "db_column_name": "ORDER_ID"},
                    {"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID"}],
        "joins_with": [
            {"name": "DM_ORDER_to_DM_CUSTOMER", "destination": {"name": "DM_CUSTOMER"},
             "on": "[DM_ORDER::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]", "type": "INNER"},
        ],
    }},
    "DM_PRODUCT": {"table": {
        "db": "DUNDERMIFFLIN", "schema": "PUBLIC", "db_table": "DM_PRODUCT",
        "columns": [{"name": "PRODUCT_ID", "db_column_name": "PRODUCT_ID"}],
    }},
    "DM_CUSTOMER": {"table": {
        "db": "DUNDERMIFFLIN", "schema": "PUBLIC", "db_table": "DM_CUSTOMER",
        "columns": [{"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID"},
                    {"name": "COUNTRY", "db_column_name": "COUNTRY"}],
    }},
    "DM_LOCALE_COUNTRY": {"table": {
        "db": "DUNDERMIFFLIN", "schema": "PUBLIC", "db_table": "DM_LOCALE_COUNTRY",
        "columns": [{"name": "COUNTRY_KEY", "db_column_name": "COUNTRY_KEY"},
                    {"name": "COUNTRY_NAME", "db_column_name": "COUNTRY_NAME"}],
    }},
}
DM_COLUMNS = [
    {"name": "Sales", "column_id": "DM_ORDER_DETAIL::AMOUNT",
     "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
    {"name": "Order Status", "column_id": "DM_ORDER::STATUS",
     "properties": {"column_type": "ATTRIBUTE"}},
]
DM_PLANS = {"Sales": classify_measure("Sales", aggregation="SUM")}


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


def test_referencing_join_source_table_no_joins_with_raises_unsupported():
    # Requirement 3 (task 12): source table TML present but carries no
    # `joins_with` key at all — must raise UnsupportedModelError, never
    # silently drop the join.
    model = {"model": {"model_tables": [
        {"name": "FACT", "joins": [{"with": "DIM", "referencing_join": "SYS_X"}]},
        {"name": "DIM"}], "columns": MODEL["model"]["columns"]}}
    with pytest.raises(UnsupportedModelError, match="SYS_X.*FACT.*joins_with"):
        build_select(model, TABLES, CAND, PLANS, dialect="snowflake")


def test_referencing_join_source_table_tml_entirely_missing_raises_unsupported():
    # Requirement 3 counterpart: the source table isn't in table_tmls at all.
    model = {"model": {"model_tables": [
        {"name": "GHOST", "joins": [{"with": "DIM", "referencing_join": "SYS_X"}]},
        {"name": "DIM"}], "columns": MODEL["model"]["columns"]}}
    with pytest.raises(UnsupportedModelError, match="SYS_X.*GHOST.*joins_with"):
        build_select(model, TABLES, CAND, PLANS, dialect="snowflake")


def test_referencing_join_name_not_found_in_joins_with_raises_unsupported():
    # Requirement 3: joins_with exists but has no entry matching the
    # referencing_join value.
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_ORDER", "referencing_join": "SOME_UNKNOWN_JOIN_NAME"}]},
            {"name": "DM_ORDER"},
        ],
        "columns": DM_COLUMNS,
    }}
    cand = {"id": "cand_1", "dimensions": ["Order Status"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0], "flags": []}
    with pytest.raises(UnsupportedModelError,
                        match="SOME_UNKNOWN_JOIN_NAME.*DM_ORDER_DETAIL.*joins_with"):
        build_select(model, DM_TABLES, cand, DM_PLANS, dialect="snowflake")


def test_referencing_join_resolves_single_hop():
    # Requirement 1 (task 12): a model_tables join entry carrying only
    # `referencing_join` resolves against the source table's `joins_with[]`
    # entry of the same name, emitting the JOIN with the resolved `on` +
    # `type` exactly as the inline path would. Real 26.9 shape from the brief.
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_ORDER", "referencing_join": "DM_ORDER_DETAIL_to_DM_ORDER"}]},
            {"name": "DM_ORDER"},
        ],
        "columns": DM_COLUMNS,
    }}
    cand = {"id": "cand_1", "dimensions": ["Order Status"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, DM_TABLES, cand, DM_PLANS, dialect="snowflake")
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_ORDER" "DM_ORDER" '
            'ON "DM_ORDER_DETAIL"."ORDER_ID" = "DM_ORDER"."ORDER_ID"') in sql


def test_referencing_join_multi_hop_chain():
    # Requirement: DM_ORDER_DETAIL -> DM_ORDER -> DM_CUSTOMER, both hops via
    # referencing_join — all intermediate joins resolve and emit in BFS
    # dependency order.
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_ORDER", "referencing_join": "DM_ORDER_DETAIL_to_DM_ORDER"}]},
            {"name": "DM_ORDER", "joins": [
                {"with": "DM_CUSTOMER", "referencing_join": "DM_ORDER_to_DM_CUSTOMER"}]},
            {"name": "DM_CUSTOMER"},
        ],
        "columns": DM_COLUMNS[:1] + [
            {"name": "Customer Country", "column_id": "DM_CUSTOMER::COUNTRY",
             "properties": {"column_type": "ATTRIBUTE"}}],
    }}
    cand = {"id": "cand_1", "dimensions": ["Customer Country"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, DM_TABLES, cand, DM_PLANS, dialect="snowflake")
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_ORDER" "DM_ORDER" '
            'ON "DM_ORDER_DETAIL"."ORDER_ID" = "DM_ORDER"."ORDER_ID"') in sql
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_CUSTOMER" "DM_CUSTOMER" '
            'ON "DM_ORDER"."CUSTOMER_ID" = "DM_CUSTOMER"."CUSTOMER_ID"') in sql


def test_mixed_inline_and_referencing_join_both_resolve():
    # Requirement: one inline `on` join (DM_CUSTOMER -> DM_LOCALE_COUNTRY) +
    # one referencing_join (DM_ORDER_DETAIL -> DM_ORDER, and DM_ORDER ->
    # DM_CUSTOMER) in the same model — all must resolve correctly.
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_ORDER", "referencing_join": "DM_ORDER_DETAIL_to_DM_ORDER"}]},
            {"name": "DM_ORDER", "joins": [
                {"with": "DM_CUSTOMER", "referencing_join": "DM_ORDER_to_DM_CUSTOMER"}]},
            {"name": "DM_CUSTOMER", "joins": [
                {"with": "DM_LOCALE_COUNTRY",
                 "on": "[DM_CUSTOMER::COUNTRY] = [DM_LOCALE_COUNTRY::COUNTRY_KEY]",
                 "type": "INNER"}]},
            {"name": "DM_LOCALE_COUNTRY"},
        ],
        "columns": DM_COLUMNS[:1] + [
            {"name": "Country Name", "column_id": "DM_LOCALE_COUNTRY::COUNTRY_NAME",
             "properties": {"column_type": "ATTRIBUTE"}}],
    }}
    cand = {"id": "cand_1", "dimensions": ["Country Name"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, DM_TABLES, cand, DM_PLANS, dialect="snowflake")
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_ORDER" "DM_ORDER" '
            'ON "DM_ORDER_DETAIL"."ORDER_ID" = "DM_ORDER"."ORDER_ID"') in sql
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_CUSTOMER" "DM_CUSTOMER" '
            'ON "DM_ORDER"."CUSTOMER_ID" = "DM_CUSTOMER"."CUSTOMER_ID"') in sql
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_LOCALE_COUNTRY" "DM_LOCALE_COUNTRY" '
            'ON "DM_CUSTOMER"."COUNTRY" = "DM_LOCALE_COUNTRY"."COUNTRY_KEY"') in sql


def test_referencing_join_missing_on_key_raises_unsupported():
    # Task 13 minor (a): a joins_with entry matched by `name` but missing the
    # `on` key must raise UnsupportedModelError naming the join, not a bare
    # KeyError — same graceful-degradation treatment as the other
    # missing-shape cases above.
    tables = {
        "DM_ORDER_DETAIL": {"table": {
            **DM_TABLES["DM_ORDER_DETAIL"]["table"],
            "joins_with": [
                {"name": "DM_ORDER_DETAIL_to_DM_ORDER", "destination": {"name": "DM_ORDER"},
                 "type": "INNER"},  # no "on"
            ],
        }},
        "DM_ORDER": DM_TABLES["DM_ORDER"],
    }
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_ORDER", "referencing_join": "DM_ORDER_DETAIL_to_DM_ORDER"}]},
            {"name": "DM_ORDER"},
        ],
        "columns": DM_COLUMNS,
    }}
    cand = {"id": "cand_1", "dimensions": ["Order Status"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0], "flags": []}
    with pytest.raises(UnsupportedModelError,
                        match="DM_ORDER_DETAIL_to_DM_ORDER.*on"):
        build_select(model, tables, cand, DM_PLANS, dialect="snowflake")


def test_referencing_join_missing_type_key_defaults_to_inner():
    # Companion case: `type` absent on the matched joins_with entry defaults
    # to INNER (matching the existing _JOIN_TYPE fallback elsewhere), rather
    # than raising.
    tables = {
        "DM_ORDER_DETAIL": {"table": {
            **DM_TABLES["DM_ORDER_DETAIL"]["table"],
            "joins_with": [
                {"name": "DM_ORDER_DETAIL_to_DM_ORDER", "destination": {"name": "DM_ORDER"},
                 "on": "[DM_ORDER_DETAIL::ORDER_ID] = [DM_ORDER::ORDER_ID]"},  # no "type"
            ],
        }},
        "DM_ORDER": DM_TABLES["DM_ORDER"],
    }
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_ORDER", "referencing_join": "DM_ORDER_DETAIL_to_DM_ORDER"}]},
            {"name": "DM_ORDER"},
        ],
        "columns": DM_COLUMNS,
    }}
    cand = {"id": "cand_1", "dimensions": ["Order Status"], "date_column": None,
            "bucket": None, "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, tables, cand, DM_PLANS, dialect="snowflake")
    assert ('JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_ORDER" "DM_ORDER" '
            'ON "DM_ORDER_DETAIL"."ORDER_ID" = "DM_ORDER"."ORDER_ID"') in sql


def test_referencing_join_inner_unreferenced_table_is_retained():
    # open-item #11's mandatory-INNER-retention rule must see the RESOLVED
    # type: DM_ORDER_DETAIL's referencing_join to DM_PRODUCT resolves to
    # INNER via joins_with, and must be retained even though the candidate
    # selects no DM_PRODUCT column.
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_PRODUCT", "referencing_join": "DM_ORDER_DETAIL_to_DM_PRODUCT"}]},
            {"name": "DM_PRODUCT"},
        ],
        "columns": DM_COLUMNS[:1],
    }}
    cand = {"id": "cand_1", "dimensions": [], "date_column": None, "bucket": None,
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, DM_TABLES, cand, DM_PLANS, dialect="snowflake")
    assert 'JOIN "DUNDERMIFFLIN"."PUBLIC"."DM_PRODUCT" "DM_PRODUCT"' in sql


def test_referencing_join_left_outer_unreferenced_table_is_pruned():
    # Counterpart: a resolved LEFT_OUTER referencing_join to an unreferenced
    # table never changes the root row set, so pruning it remains correct.
    tables = {
        "DM_ORDER_DETAIL": {"table": {
            **DM_TABLES["DM_ORDER_DETAIL"]["table"],
            "joins_with": [
                {"name": "DM_ORDER_DETAIL_to_DM_PRODUCT", "destination": {"name": "DM_PRODUCT"},
                 "on": "[DM_ORDER_DETAIL::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]",
                 "type": "LEFT_OUTER"},
            ],
        }},
        "DM_PRODUCT": DM_TABLES["DM_PRODUCT"],
    }
    model = {"model": {
        "model_tables": [
            {"name": "DM_ORDER_DETAIL", "joins": [
                {"with": "DM_PRODUCT", "referencing_join": "DM_ORDER_DETAIL_to_DM_PRODUCT"}]},
            {"name": "DM_PRODUCT"},
        ],
        "columns": DM_COLUMNS[:1],
    }}
    cand = {"id": "cand_1", "dimensions": [], "date_column": None, "bucket": None,
            "measure_columns": ["Sales"], "covered": [0], "flags": []}
    sql = build_select(model, tables, cand, DM_PLANS, dialect="snowflake")
    assert "DM_PRODUCT" not in sql
    assert "JOIN" not in sql


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


def test_snowflake_materialized_view_guard_raises():
    # Task 13 (c): Snowflake materialized views can't contain joins (live-
    # verified error 002212 — "More than one table referenced in the view
    # definition"). A caller that explicitly requests
    # --materialization mview on Snowflake must get a clear
    # UnsupportedModelError steering to dynamic/ctas, not DDL that will fail
    # at CREATE time.
    with pytest.raises(UnsupportedModelError, match="002212"):
        build_ddl("SELECT 1", "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                  materialization="mview")


def test_snowflake_dynamic_and_ctas_unaffected_by_mview_guard():
    # The guard must not catch snowflake+dynamic or snowflake+ctas — only
    # the snowflake+mview combination.
    dynamic = build_ddl("SELECT 1", "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                        materialization="dynamic", warehouse="WH")
    assert dynamic.startswith("CREATE OR REPLACE DYNAMIC TABLE")
    ctas = build_ddl("SELECT 1", "SALESDB.PUBLIC.FACT_AGG_M", "snowflake",
                     materialization="ctas")
    assert ctas.startswith("CREATE OR REPLACE TABLE")


def test_databricks_bigquery_mview_unaffected_by_snowflake_guard():
    # The guard is snowflake-specific — databricks/bigquery mview (including
    # the "auto" resolution path) must keep working.
    dbx = build_ddl("SELECT 1", "cat.sch.agg", "databricks", materialization="mview")
    assert dbx.startswith("CREATE OR REPLACE MATERIALIZED VIEW cat.sch.agg")
    bq = build_ddl("SELECT 1", "proj.ds.agg", "bigquery", materialization="auto")
    assert bq.startswith("CREATE MATERIALIZED VIEW proj.ds.agg")
