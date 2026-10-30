"""P (Performance): the inputs the legacy P-check tests use, and P_INPUTS."""
from __future__ import annotations

import copy

from ts_cli.audit.context import AuditContext, make_context

from .ai import demo_corpus_models
from .common import (model_75_columns, model_76_columns, model_id_columns,
                     model_role_playing_dimension)
from .rls import (P14_FUNCTION_EXPRS, P15_UNICODE_TYPES, TRIP_FUNC_RULE, TRIP_PLAIN_RULE,
                  TRIP_TABLE_FQN, build_index_col, build_index_model,
                  build_rls_column_type, build_rls_expr, build_trip_model, build_trip_table,
                  build_trip_varchar, perf_rls_cased_varchar,
                  perf_rls_friendly_column_name, perf_rls_function_rule,
                  perf_rls_integer_column, perf_rls_plain_rule,
                  perf_rls_type_on_model_ignored, perf_table_without_rls,
                  sec_rls_cased_varchar, sec_rls_uncased_varchar, sec_rls_upper_function)


# ── P: Performance ──────────────────────────────────────────────────────────
# The inputs the legacy P-check tests exercised checks_perf.py (deleted when the rule catalog replaced them) with: test_checks_perf.py,
# test_checks_perf_trip.py, and the P halves of test_checks_varchar_join_keys.py,
# test_referencing_joins.py, test_dead_guards.py, test_index_type_sense.py,
# test_unreachable_checks.py, test_checks_registry.py and test_checks_security_trip.py.
# Those tests build their contexts here, so the P rules' examples and the pinned-findings
# test (tests/test_audit_pinned_findings.py) run over the very same inputs.

# test_checks_perf.py's shapes

def build_perf_model(name="Sales", guid="m-1", columns=None, formulas=None,
                     model_tables=None, properties=None, filters=None,
                     constraints=None) -> dict:
    """A model document as test_checks_perf.py has always built it."""
    columns, formulas, model_tables, properties, filters, constraints = copy.deepcopy(
        (columns, formulas, model_tables, properties, filters, constraints))
    return {"guid": guid, "model": {
        "name": name, "model_tables": model_tables or [{"name": "T1"}],
        "columns": columns or [], "formulas": formulas or [],
        "properties": properties or {}, "filters": filters or [],
        "constraints": constraints or []}}


def build_perf_col(name="Amount", column_type="MEASURE", aggregation=None, index_type=None,
                   column_id=None, data_type="INT64") -> dict:
    col = {"name": name, "column_id": column_id or f"T1::{name}",
           "properties": {"column_type": column_type},
           "db_column_properties": {"data_type": data_type}}
    if aggregation:
        col["properties"]["aggregation"] = aggregation
    if index_type:
        col["properties"]["index_type"] = index_type
    return col


def build_perf_table(name="ORDERS", guid="t-1", rls_rules=None) -> dict:
    table = {"guid": guid, "table": {"name": name, "columns": []}}
    if rls_rules:
        table["table"]["rls_rules"] = rls_rules
    return table


def perf_metadata_sql_view() -> AuditContext:
    """One SQL_VIEW (P1 fires on it) beside one logical table."""
    return make_context(metadata=[
        {"metadata_header": {"type": "SQL_VIEW", "name": "V1", "id": "v-1"}},
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}},
    ])


def perf_metadata_logical_only() -> AuditContext:
    return make_context(metadata=[
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}}])


def perf_model_wide_not_progressive() -> AuditContext:
    """Six tables with join_progressive false (P4 fires)."""
    return make_context(models=[build_perf_model(
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        properties={"join_progressive": False})])


def perf_model_wide_progressive() -> AuditContext:
    """Six tables with join_progressive true (P4 silent)."""
    return make_context(models=[build_perf_model(
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        properties={"join_progressive": True})])


def perf_model_80_columns() -> AuditContext:
    return make_context(models=[build_perf_model(
        columns=[build_perf_col(f"C{i}") for i in range(80)])])


def perf_model_columns(n: int) -> AuditContext:
    """A Model with `n` columns (P8's measure)."""
    return make_context(models=[build_perf_model(
        columns=[build_perf_col(f"C{i}") for i in range(n)])])


def perf_model_1600_columns() -> AuditContext:
    """1,600 columns: P8 HIGH under both profiles (> 1,500 general, > 500 spotter)."""
    return perf_model_columns(1600)


def perf_model_50_columns() -> AuditContext:
    return make_context(models=[build_perf_model(
        columns=[build_perf_col(f"C{i}") for i in range(50)])])


def perf_table_seven_rls_rules() -> AuditContext:
    rls = {"rules": [{"expr": f"[col{i}]"} for i in range(7)]}
    return make_context(tables={"db.s.T1": build_perf_table(rls_rules=rls)})


def perf_formula_six_nested_ifs() -> AuditContext:
    expr = "if(if(if(if(if(if([x]>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)"
    return make_context(models=[build_perf_model(formulas=[{"name": "F1", "expr": expr}])])


def perf_column_count_distinct() -> AuditContext:
    return make_context(models=[build_perf_model(
        columns=[build_perf_col("Users", aggregation="COUNT_DISTINCT")])])


# test_checks_perf_trip.py's shapes (from the model and table TML schemas)

def build_trip_ctx(*models) -> AuditContext:
    return make_context(models=list(models))


def build_trip_measure(table, col) -> dict:
    return {"name": col.replace("_", " ").title(), "column_id": f"{table}::{col}",
            "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}


def build_trip_attribute(table, col, **props) -> dict:
    return {"name": col, "column_id": f"{table}::{col}",
            "properties": {"column_type": "ATTRIBUTE", **props}}


def build_trip_join(with_table) -> dict:
    """An inline join — `type` and `cardinality` are required together."""
    return {"with": with_table, "on": f"[A::{with_table}_KEY] = [{with_table}::KEY]",
            "type": "INNER", "cardinality": "MANY_TO_ONE"}


# P2 — scalar formula density

def build_formula_model(n: int, aggregated: bool) -> dict:
    """`n` row-level formulas, each surfaced by a column that does (or does not)
    declare an aggregation."""
    return build_trip_model(
        formulas=[{"id": f"formula_Margin {i}", "name": f"Margin {i}",
                   "expr": "[ORDERS::AMOUNT] - [ORDERS::COST]"} for i in range(n)],
        columns=[{"name": f"Margin {i}", "formula_id": f"formula_Margin {i}",
                  "properties": {"column_type": "MEASURE",
                                 **({"aggregation": "SUM"} if aggregated else {})}}
                 for i in range(n)],
    )


def perf_six_scalar_formulas() -> AuditContext:
    """Six unaggregated formulas: P2 MEDIUM."""
    return build_trip_ctx(build_formula_model(6, aggregated=False))


def perf_eleven_scalar_formulas() -> AuditContext:
    """Eleven unaggregated formulas: P2 HIGH."""
    return build_trip_ctx(build_formula_model(11, aggregated=False))


def perf_six_aggregated_formulas() -> AuditContext:
    return build_trip_ctx(build_formula_model(6, aggregated=True))


def perf_five_scalar_formulas() -> AuditContext:
    return build_trip_ctx(build_formula_model(5, aggregated=False))


def perf_aggregate_expr_formulas() -> AuditContext:
    """Six `sum ( ... )` formulas whose columns declare no aggregation: aggregate,
    so P2 is silent (the legacy check counted them as scalar)."""
    return build_trip_ctx(build_trip_model(
        formulas=[{"id": f"formula_Rev {i}", "name": f"Rev {i}",
                   "expr": "sum ( [ORDERS::AMOUNT] )"} for i in range(6)],
        columns=[{"name": f"Rev {i}", "formula_id": f"formula_Rev {i}",
                  "properties": {"column_type": "MEASURE"}} for i in range(6)],
    ))


# P3 — model filters with no apply_on_tables

TRIP_MANDATORY_FILTER = {"column": ["Region"], "oper": "in", "values": ["APAC"]}
TRIP_SCOPED_FILTER = {"column": ["Quantity"], "oper": ">", "values": ["100"],
                      "apply_on_tables": ["Lineorder", "Supplier"]}


def perf_filters_one_mandatory() -> AuditContext:
    return build_trip_ctx(build_trip_model(filters=[TRIP_MANDATORY_FILTER,
                                                    TRIP_SCOPED_FILTER]))


def perf_filters_all_scoped() -> AuditContext:
    return build_trip_ctx(build_trip_model(filters=[TRIP_SCOPED_FILTER]))


def perf_model_without_filters() -> AuditContext:
    return build_trip_ctx(build_trip_model())


# P5 — no date constraints on a model with fact tables

TRIP_FACT_COLUMNS = [build_trip_measure("ORDERS", c)
                     for c in ("AMOUNT", "COST", "QUANTITY", "DISCOUNT")]
# The shape a live export produces: a mapping whose single key is `constraint`.
TRIP_REAL_CONSTRAINTS = {"constraint": [
    {"table": "ORDERS",
     "condition": [{"date_range_condition": {"column": "order date",
                                             "duration": 1, "bucket": "YEAR"}}]},
]}


def build_fact_model(constraints=None) -> dict:
    body = {"model_tables": [{"name": "ORDERS", "fqn": "t-orders"}],
            "columns": TRIP_FACT_COLUMNS}
    if constraints is not None:
        body["constraints"] = constraints
    return build_trip_model(**body)


def perf_fact_model_unconstrained() -> AuditContext:
    return build_trip_ctx(build_fact_model())


def perf_fact_model_date_window() -> AuditContext:
    return build_trip_ctx(build_fact_model(TRIP_REAL_CONSTRAINTS))


def perf_fact_model_flattened_window() -> AuditContext:
    """The constraint list without its mapping (a shape no export produces)."""
    return build_trip_ctx(build_fact_model(TRIP_REAL_CONSTRAINTS["constraint"]))


def perf_thin_fact_model() -> AuditContext:
    """Three measures is not >3, so no fact table."""
    return build_trip_ctx(build_trip_model(
        model_tables=[{"name": "ORDERS", "fqn": "t-orders"}],
        columns=TRIP_FACT_COLUMNS[:3]))


def build_aliased_fact_model(prefix: str) -> AuditContext:
    """ORDERS aliased as O, its four measures' column_ids prefixed `prefix`. Legacy P5
    matches fact tables by `name`, not alias (BL-305), so only "ORDERS::" reads as one."""
    return build_trip_ctx(build_trip_model(
        model_tables=[{"name": "ORDERS", "alias": "O", "fqn": "t-orders"}],
        columns=[build_trip_measure(prefix, c)
                 for c in ("AMOUNT", "COST", "QUANTITY", "DISCOUNT")]))


def perf_fact_alias_prefixed() -> AuditContext:
    """Alias-prefixed column_ids (as exported TML writes them): no P5 finding."""
    return build_aliased_fact_model("O")


def perf_fact_name_prefixed() -> AuditContext:
    """Name-prefixed column_ids under an alias: P5 fires, naming ORDERS."""
    return build_aliased_fact_model("ORDERS")


def perf_fact_columns_without_tables() -> AuditContext:
    return build_trip_ctx(build_trip_model(columns=TRIP_FACT_COLUMNS))


# P7 — join depth

def build_join_chain(names) -> AuditContext:
    """model_tables joined in a chain names[0] -> names[1] -> ..."""
    tables = [{"name": n, "fqn": f"t-{n}", "joins": [build_trip_join(nxt)]}
              for n, nxt in zip(names, names[1:])]
    tables.append({"name": names[-1], "fqn": f"t-{names[-1]}"})
    return build_trip_ctx(build_trip_model(model_tables=tables))


def perf_join_chain_four_hops() -> AuditContext:
    """A->B->C->D->E: depth 4, P7 MEDIUM."""
    return build_join_chain(["A", "B", "C", "D", "E"])


def perf_join_chain_six_hops() -> AuditContext:
    """A->...->G: depth 6, P7 HIGH."""
    return build_join_chain(["A", "B", "C", "D", "E", "F", "G"])


def perf_star_schema() -> AuditContext:
    return build_trip_ctx(build_trip_model(model_tables=[
        {"name": "A", "fqn": "t-a", "joins": [build_trip_join("DIM1"), build_trip_join("DIM2")]},
        {"name": "DIM1", "fqn": "t-d1"},
        {"name": "DIM2", "fqn": "t-d2"},
    ]))


def perf_single_table() -> AuditContext:
    return build_trip_ctx(build_trip_model(model_tables=[{"name": "A", "fqn": "t-a"}]))


# P9 — high-cardinality ID column indexed as ATTRIBUTE

P9_ID_SUFFIXES = ["ORDER_GUID", "SESSION_UUID", "ROW_ID", "TRANSACTION_ID", "SURROGATE_KEY"]


def build_id_column(name, index_type=None) -> AuditContext:
    props = {"index_type": index_type} if index_type else {}
    return build_trip_ctx(build_trip_model(
        columns=[build_trip_attribute("ORDERS", name, **props)]))


def perf_indexed_id_attribute() -> AuditContext:
    return build_id_column("CUSTOMER_ID", "DEFAULT")


def perf_id_attribute_default_indexed() -> AuditContext:
    """No index_type: indexed by default."""
    return build_id_column("CUSTOMER_ID")


def perf_id_attribute_not_indexed() -> AuditContext:
    return build_id_column("CUSTOMER_ID", "DONT_INDEX")


def perf_non_id_attribute() -> AuditContext:
    return build_id_column("REGION_NAME", "DEFAULT")


def perf_friendly_id_name() -> AuditContext:
    return build_id_column("Customer Id", "DEFAULT")


def perf_id_measure() -> AuditContext:
    return build_trip_ctx(build_trip_model(columns=[
        {"name": "ORDER_ID", "column_id": "ORDERS::ORDER_ID",
         "properties": {"column_type": "MEASURE", "aggregation": "COUNT",
                        "index_type": "DEFAULT"}}]))


# P11 — indexed-column count on a Spotter-enabled model

def build_spotter_columns(n, index_type=None, spotter=True) -> AuditContext:
    props = {"index_type": index_type} if index_type else {}
    return build_trip_ctx(build_trip_model(
        properties={"spotter_config": {"is_spotter_enabled": spotter}},
        columns=[build_trip_attribute("ORDERS", f"COL_{i}", **props) for i in range(n)]))


def perf_spotter_31_indexed() -> AuditContext:
    return build_spotter_columns(31, "DEFAULT")


def perf_spotter_30_indexed() -> AuditContext:
    return build_spotter_columns(30, "DEFAULT")


def perf_spotter_disabled_31_indexed() -> AuditContext:
    return build_spotter_columns(31, "DEFAULT", spotter=False)


def perf_spotter_31_not_indexed() -> AuditContext:
    return build_spotter_columns(31, "DONT_INDEX")


def perf_spotter_31_default_indexed() -> AuditContext:
    return build_spotter_columns(31)


def perf_spotter_config_absent() -> AuditContext:
    return build_trip_ctx(build_trip_model(columns=[
        build_trip_attribute("ORDERS", f"COL_{i}", index_type="DEFAULT") for i in range(31)]))


# P17 — formula cross-reference chain depth

TRIP_REAL_EXPORT_FORMULAS = [
    # From agents/shared/worked-examples/snowflake/ts-to-snowflake.md (an exported
    # DunderMifflin Model): a real cross-reference, id-style.
    {"id": "formula_Product to Category Contribution Ratio",
     "name": "Product to Category Contribution Ratio",
     "expr": "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , "
             "{ [DM_INVENTORY::PRODUCT_ID] } , query_filters ( ) ) ) "
             "/ [formula_Category Quantity]"},
    {"id": "formula_Category Quantity", "name": "Category Quantity",
     "expr": "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , "
             "{ [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) ) )"},
]
CHAIN_NAMES = ["A", "B", "C", "D", "E"]


def build_ref_chain(id_refs: bool) -> list:
    """A -> B -> C -> D -> E, referenced by formula id or by display name."""
    def ref(name):
        return f"[formula_{name}]" if id_refs else f"[{name}]"
    return [{"id": f"formula_{n}", "name": n,
             "expr": (f"{ref(nxt)} * 2" if nxt else "sum ( [ORDERS::AMOUNT] )")}
            for n, nxt in zip(CHAIN_NAMES, CHAIN_NAMES[1:] + [None])]


def perf_formulas_real_export() -> AuditContext:
    return build_trip_ctx(build_trip_model(formulas=TRIP_REAL_EXPORT_FORMULAS))


def perf_formula_listed_twice() -> AuditContext:
    """One formula mapping listed twice (A -> B -> C -> D): legacy P17 reports A once."""
    a = build_formula("A", "[formula_B]")
    return build_trip_ctx(build_trip_model(formulas=[
        a, build_formula("B", "[formula_C]"), build_formula("C", "[formula_D]"),
        build_formula("D", "1"), a]))


def perf_filter_scalar_column() -> AuditContext:
    """Filters whose `column` is a scalar, not a list (hand-edited TML): P3 still
    counts them."""
    return build_trip_ctx(build_trip_model(filters=[
        {"column": 5, "oper": "in", "values": ["x"]},
        {"column": True, "oper": "in", "values": ["x"]},
        {"column": "Region", "oper": "in", "values": ["x"]}]))


def perf_display_ref_chain() -> AuditContext:
    """Depth 4 from A (P17 LOW), 3 from B (P17 INFO)."""
    return build_trip_ctx(build_trip_model(formulas=build_ref_chain(id_refs=False)))


def perf_id_ref_chain() -> AuditContext:
    return build_trip_ctx(build_trip_model(formulas=build_ref_chain(id_refs=True)))


# test_unreachable_checks.py's P17 shapes

def build_formula(name, expr) -> dict:
    return {"id": f"formula_{name}", "name": name, "expr": expr}


def build_formula_doc(formulas) -> dict:
    return {"guid": "m-1", "model": {"name": "S", "formulas": copy.deepcopy(formulas)}}


def refs_id_chain_four() -> AuditContext:
    return make_context(models=[build_formula_doc([
        build_formula("A", "[formula_B] + 1"), build_formula("B", "[formula_C] * 2"),
        build_formula("C", "[formula_D] - 3"), build_formula("D", "sum ( [T::X] )")])])


def refs_display_chain_four() -> AuditContext:
    return make_context(models=[build_formula_doc([
        {"id": "formula_A", "name": "A", "expr": "[B] + 1"},
        {"id": "formula_B", "name": "B", "expr": "[C] * 2"},
        {"id": "formula_C", "name": "C", "expr": "[D] - 3"},
        {"id": "formula_D", "name": "D", "expr": "sum ( [T::X] )"}])])


def refs_plain_columns() -> AuditContext:
    return make_context(models=[build_formula_doc([
        build_formula("A", "sum ( [ORDERS::AMOUNT] )"),
        build_formula("B", "sum ( [ORDERS::COST] )")])])


def refs_self_reference() -> AuditContext:
    return make_context(models=[build_formula_doc([build_formula("A", "[formula_A] + 1")])])


# test_checks_varchar_join_keys.py's shapes (P6 and D2)

JOIN_KEYS_TABLE_FQN = "tbl-orders"
JOIN_KEYS_VARCHAR_COLS = [
    {"name": "CUST_ID", "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "AMOUNT", "db_column_properties": {"data_type": "INT64"}},
]
JOIN_KEYS_COMPOSITE_ON = ("[ORDERS::CUST_ID] = [CUST::ID] and "
                          "[ORDERS::REGION] = [CUST::REGION]")
JOIN_KEYS_COMPOSITE_COLS = [
    {"name": "CUST_ID", "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "REGION", "db_column_properties": {"data_type": "TEXT"}},
]


def build_join_keys_table(cols) -> dict:
    return {"table": {"name": "ORDERS", "columns": copy.deepcopy(cols)}}


def build_join_keys_model(on, model_columns=None) -> dict:
    return {"guid": "m-1", "model": {
        "name": "Sales",
        "columns": copy.deepcopy(model_columns) or [
            {"name": "Cust Id", "column_id": "ORDERS::CUST_ID"},
            {"name": "Id", "column_id": "CUST::ID"},
        ],
        "model_tables": [{"name": "ORDERS", "fqn": JOIN_KEYS_TABLE_FQN,
                          "joins": [{"name": "j1", "on": on}]}],
    }}


def build_join_keys_ctx(on, table_cols) -> AuditContext:
    return make_context(models=[build_join_keys_model(on)],
                        tables={JOIN_KEYS_TABLE_FQN: build_join_keys_table(table_cols)})


def join_keys_varchar() -> AuditContext:
    """A bracketed VARCHAR join key (P6 fires)."""
    return build_join_keys_ctx("[ORDERS::CUST_ID] = [CUST::ID]", JOIN_KEYS_VARCHAR_COLS)


def join_keys_integer() -> AuditContext:
    return build_join_keys_ctx("[ORDERS::CUST_ID] = [CUST::ID]",
                               [{"name": "CUST_ID",
                                 "db_column_properties": {"data_type": "INT64"}}])


def join_keys_type_on_model_ignored() -> AuditContext:
    """A model column claims INT64; the TABLE's VARCHAR is what counts."""
    model = build_join_keys_model("[ORDERS::CUST_ID] = [CUST::ID]", model_columns=[
        {"name": "Cust Id", "column_id": "ORDERS::CUST_ID",
         "db_column_properties": {"data_type": "INT64"}}])
    return make_context(models=[model], tables={
        JOIN_KEYS_TABLE_FQN: build_join_keys_table(JOIN_KEYS_VARCHAR_COLS)})


def join_keys_composite() -> AuditContext:
    return build_join_keys_ctx(JOIN_KEYS_COMPOSITE_ON, JOIN_KEYS_COMPOSITE_COLS)


def join_keys_table_missing() -> AuditContext:
    return make_context(models=[build_join_keys_model("[ORDERS::CUST_ID] = [CUST::ID]")],
                        tables={})


# test_referencing_joins.py's shapes (P6, D2, D3)

REF_FACT_FQN, REF_DIM_FQN = "fact-guid", "dim-guid"


def build_referencing_tables(key_type="VARCHAR", join_type="INNER") -> dict:
    return {
        REF_FACT_FQN: {"guid": REF_FACT_FQN, "table": {
            "name": "BASKETS_FACT",
            "columns": [{"name": "PROMOTION_KEY",
                         "db_column_properties": {"data_type": key_type}}],
            "joins_with": [{
                "name": "FK_BASKETFACT_TO_PROMOTIONDIM",
                "destination": {"name": "PROMOTION_DIMENSION", "fqn": REF_DIM_FQN},
                "on": "[BASKETS_FACT::PROMOTION_KEY] = [PROMOTION_DIMENSION::PROMOTION_KEY]",
                "type": join_type}]}},
        REF_DIM_FQN: {"guid": REF_DIM_FQN, "table": {
            "name": "PROMOTION_DIMENSION",
            "columns": [{"name": "PROMOTION_KEY",
                         "db_column_properties": {"data_type": key_type}}]}},
    }


def build_referencing_model(inline_type=None) -> dict:
    join = {"with": "PROMOTION_DIMENSION", "referencing_join": "FK_BASKETFACT_TO_PROMOTIONDIM"}
    if inline_type:
        join["type"] = inline_type
    return {"guid": "m-1", "model": {
        "name": "Retail Sales",
        "columns": [],
        "model_tables": [
            {"name": "BASKETS_FACT", "fqn": REF_FACT_FQN, "joins": [join]},
            {"name": "PROMOTION_DIMENSION", "fqn": REF_DIM_FQN},
        ]}}


def build_referencing_ctx(inline_type=None, **table_kw) -> AuditContext:
    return make_context(models=[build_referencing_model(inline_type)],
                        tables=build_referencing_tables(**table_kw))


def referencing_join_varchar() -> AuditContext:
    """A referencing join whose (table-side) key is VARCHAR (P6 fires)."""
    return build_referencing_ctx()


def referencing_join_integer() -> AuditContext:
    return build_referencing_ctx(key_type="INT64")


def referencing_join_outer() -> AuditContext:
    return build_referencing_ctx(join_type="OUTER")


def referencing_join_model_type_override() -> AuditContext:
    return build_referencing_ctx(inline_type="LEFT_OUTER")


def referencing_join_table_missing() -> AuditContext:
    return make_context(models=[build_referencing_model()], tables={})


# test_dead_guards.py's P5 shapes

GUARD_REAL_CONSTRAINTS = {"constraint": [
    {"date_range_condition": {"column": "Order Date", "period": "LAST_N_DAYS", "n": 90}}]}


def build_guard_fact_model(constraints=None) -> dict:
    """A model with a fact table, so P5 has something to report on."""
    m = {"name": "Sales",
         "columns": [{"name": f"M{i}", "column_id": f"ORDERS::M{i}",
                      "properties": {"column_type": "MEASURE"}} for i in range(4)],
         "model_tables": [{"name": "ORDERS"}]}
    if constraints is not None:
        m["constraints"] = copy.deepcopy(constraints)
    return {"guid": "m-1", "model": m}


def guard_fact_model_unconstrained() -> AuditContext:
    return make_context(models=[build_guard_fact_model()])


def guard_fact_model_date_window() -> AuditContext:
    return make_context(models=[build_guard_fact_model(GUARD_REAL_CONSTRAINTS)])


def guard_fact_model_listed_window() -> AuditContext:
    return make_context(models=[build_guard_fact_model(
        [{"date_range_condition": {"column": "Order Date"}}])])


def guard_fact_model_other_constraint() -> AuditContext:
    return make_context(models=[build_guard_fact_model(
        {"constraint": [{"some_other_condition": {"column": "X"}}]})])


# test_index_type_sense.py's shapes (P9, P11, S2); the column and model builders
# live in rls.py, which S2 shares

def build_index_spotter_ctx(cols) -> AuditContext:
    return make_context(models=[build_index_model(
        cols, properties={"spotter_config": {"is_spotter_enabled": True}})])


def index_id_default_indexed() -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("CUSTOMER_ID", "ATTRIBUTE", None)])])


def index_id_not_indexed() -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("CUSTOMER_ID", "ATTRIBUTE", "DONT_INDEX")])])


def index_id_measure() -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("CUSTOMER_ID", "MEASURE", None)])])


def index_spotter_31_default() -> AuditContext:
    return build_index_spotter_ctx([build_index_col(f"C{i}", "ATTRIBUTE", None)
                                    for i in range(31)])


def index_spotter_31_not_indexed() -> AuditContext:
    return build_index_spotter_ctx([build_index_col(f"C{i}", "ATTRIBUTE", "DONT_INDEX")
                                    for i in range(31)])


def index_spotter_mixed() -> AuditContext:
    """31 indexed (by default) and 10 DONT_INDEX columns: 31 indexed."""
    return build_index_spotter_ctx(
        [build_index_col(f"A{i}", "ATTRIBUTE", None) for i in range(31)]
        + [build_index_col(f"B{i}", "ATTRIBUTE", "DONT_INDEX") for i in range(10)])


# test_checks_registry.py's shared-rule shape (P4 and D4)

def registry_wide_not_progressive() -> AuditContext:
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "Wide", "model_tables": [{"name": f"T{i}"} for i in range(6)],
        "properties": {"join_progressive": False}}}])


# Raw names and guids: present-and-None reaches the finding as None, absent as "".

def perf_names_none() -> AuditContext:
    """Every P scope with `name: None` / `guid: None` (or `id: None`), each firing."""
    model = build_perf_model(
        name=None, guid=None,
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        columns=[build_perf_col(None, aggregation="COUNT_DISTINCT")]
        + [build_perf_col(f"C{i}") for i in range(80)],
        formulas=[{"name": None, "expr": "if(if(if(if([x],1,0),1,0),1,0),1,0) + [formula_B]"},
                  build_formula("B", "[formula_C] + 1"), build_formula("C", "[formula_D]"),
                  build_formula("D", "1")],
        filters=[TRIP_MANDATORY_FILTER])
    table = build_trip_table([build_trip_varchar("COUNTRY")],
                             [TRIP_FUNC_RULE] + [TRIP_PLAIN_RULE] * 4)
    table["guid"] = None
    table["table"]["name"] = None
    return make_context(models=[model], tables={TRIP_TABLE_FQN: table}, metadata=[
        {"metadata_header": {"type": "SQL_VIEW", "name": None, "id": None}}])


def perf_names_absent() -> AuditContext:
    """Every P scope with no `name` / `guid` (or `id`) key, each firing."""
    model = build_perf_model(
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        columns=[{"column_id": "T1::X", "properties": {"column_type": "MEASURE",
                                                      "aggregation": "COUNT_DISTINCT"}}],
        formulas=[{"expr": "if(if(if(if([x],1,0),1,0),1,0),1,0) + [formula_B]"},
                  build_formula("B", "[formula_C] + 1"), build_formula("C", "[formula_D]"),
                  build_formula("D", "1")])
    del model["guid"], model["model"]["name"]
    table = build_trip_table([build_trip_varchar("COUNTRY")], [TRIP_FUNC_RULE] * 5)
    del table["guid"], table["table"]["name"]
    return make_context(models=[model], tables={TRIP_TABLE_FQN: table},
                        metadata=[{"type": "SQL_VIEW"}])


def perf_duplicate_formula_names() -> AuditContext:
    """Two formulas named A, both referencing the chain: legacy P17 keys its graph by
    name, so they report once (the later definition's references win)."""
    return make_context(models=[build_formula_doc([
        build_formula("A", "[formula_B]"), build_formula("B", "[formula_C]"),
        build_formula("C", "[formula_D]"), build_formula("D", "[formula_E]"),
        build_formula("E", "1"),
        {"id": "formula_A2", "name": "A", "expr": "[formula_C] + 1"},
        {"id": "formula_Z", "name": "Z", "expr": "1"},
        {"id": "formula_Z2", "name": "Z", "expr": "[formula_B] + [formula_Z]"},
    ])])


def perf_unnamed_formulas_with_references() -> AuditContext:
    """Two formulas named "" (one by an absent key) that reference a chain: legacy
    P17 merges them under the name ""."""
    return make_context(models=[build_formula_doc([
        {"id": "formula_x", "name": "", "expr": "[formula_B]"},
        {"expr": "[formula_C] * [B]"},
        build_formula("B", "[formula_C]"), build_formula("C", "[formula_D]"),
        build_formula("D", "[formula_E]"), build_formula("E", "1"),
    ])])


# Every P input, for the pinned-findings test — listed by hand (see AI_INPUTS).
P_INPUTS = {fn.__name__: fn for fn in (
    perf_model_1600_columns,
    perf_metadata_sql_view, perf_metadata_logical_only, perf_model_wide_not_progressive,
    perf_model_wide_progressive, perf_fact_alias_prefixed, perf_fact_name_prefixed,
    perf_formula_listed_twice, perf_filter_scalar_column,
    perf_model_80_columns, perf_model_50_columns, perf_table_seven_rls_rules,
    perf_formula_six_nested_ifs, perf_column_count_distinct,
    perf_six_scalar_formulas, perf_eleven_scalar_formulas, perf_six_aggregated_formulas,
    perf_five_scalar_formulas, perf_aggregate_expr_formulas,
    perf_filters_one_mandatory, perf_filters_all_scoped, perf_model_without_filters,
    perf_fact_model_unconstrained, perf_fact_model_date_window,
    perf_fact_model_flattened_window, perf_thin_fact_model, perf_fact_columns_without_tables,
    perf_join_chain_four_hops, perf_join_chain_six_hops, perf_star_schema, perf_single_table,
    perf_indexed_id_attribute, perf_id_attribute_default_indexed,
    perf_id_attribute_not_indexed, perf_non_id_attribute, perf_friendly_id_name,
    perf_id_measure,
    perf_spotter_31_indexed, perf_spotter_30_indexed, perf_spotter_disabled_31_indexed,
    perf_spotter_31_not_indexed, perf_spotter_31_default_indexed, perf_spotter_config_absent,
    perf_rls_function_rule, perf_rls_plain_rule, perf_table_without_rls,
    perf_rls_cased_varchar, perf_rls_integer_column, perf_rls_type_on_model_ignored,
    perf_rls_friendly_column_name,
    perf_formulas_real_export, perf_display_ref_chain, perf_id_ref_chain,
    refs_id_chain_four, refs_display_chain_four, refs_plain_columns, refs_self_reference,
    join_keys_varchar, join_keys_integer, join_keys_type_on_model_ignored,
    join_keys_composite, join_keys_table_missing,
    referencing_join_varchar, referencing_join_integer, referencing_join_outer,
    referencing_join_model_type_override, referencing_join_table_missing,
    guard_fact_model_unconstrained, guard_fact_model_date_window,
    guard_fact_model_listed_window, guard_fact_model_other_constraint,
    index_id_default_indexed, index_id_not_indexed, index_id_measure,
    index_spotter_31_default, index_spotter_31_not_indexed, index_spotter_mixed,
    registry_wide_not_progressive,
    sec_rls_cased_varchar, sec_rls_uncased_varchar, sec_rls_upper_function,
    perf_names_none, perf_names_absent, perf_duplicate_formula_names,
    perf_unnamed_formulas_with_references,
    demo_corpus_models, model_76_columns, model_75_columns, model_id_columns,
    model_role_playing_dimension,
)}
P_INPUTS.update({f"scalar_formulas_{n}_{'agg' if agg else 'raw'}":
                 (lambda n=n, agg=agg: build_trip_ctx(build_formula_model(n, agg)))
                 for n in (0, 5, 6, 10, 11) for agg in (False, True)})
P_INPUTS.update({f"id_suffix_{name}": (lambda name=name: build_id_column(name, "PREFIX_ONLY"))
                 for name in P9_ID_SUFFIXES})
P_INPUTS.update({f"spotter_{n}_{idx or 'omitted'}":
                 (lambda n=n, idx=idx: build_spotter_columns(n, idx))
                 for n in (30, 31) for idx in (None, "DEFAULT", "DONT_INDEX")})
P_INPUTS.update({f"rls_column_type_{i}": (lambda t=t: build_rls_column_type(t))
                 for i, t in enumerate(P15_UNICODE_TYPES + ["varchar", "Text", "INT64", ""])})
P_INPUTS.update({f"rls_function_{i}": (lambda e=e: build_rls_expr(e))
                 for i, e in enumerate(P14_FUNCTION_EXPRS)})
P_INPUTS.update({f"join_chain_{n}_tables": (lambda n=n: build_join_chain(
                 [chr(ord("A") + i) for i in range(n)])) for n in range(1, 9)})
P_INPUTS.update({f"rls_rules_{n}": (lambda n=n: make_context(tables={"db.s.T1": build_perf_table(
                 rls_rules={"rules": [{"expr": f"[col{i}]"} for i in range(n)]})}))
                 for n in range(0, 9)})
