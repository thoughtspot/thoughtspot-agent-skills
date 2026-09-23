"""Every performance check that was *imported* by a test but never *called* by one.

2026-09-22 audit finding 6.1: 27 of 51 checks are imported by a test and never
invoked. An import satisfies a coverage grep and exercises nothing — which is
exactly how `check_p6`/`check_d2` shipped structurally incapable of returning a
finding and went unnoticed for months (finding 14.1, fixed in PR #528). The nine
checks here are the `checks_perf` half of that list: `test_checks_perf.py` imports
`check_p2, p3, p5, p7, p9, p11, p14, p15, p17` on lines 2-4 and calls none of them.

Each check below gets a **trip** test (a realistic context that must produce a
finding) and a **clean** test (a realistic context that must produce none). Where a
check is reachable but wrong, the defect is pinned with `xfail(strict=True)` so that
fixing it turns the mark red rather than leaving a stale test: nothing here edits a
check.

Fixture shapes are taken from `agents/shared/schemas/thoughtspot-model-tml.md` and
`agents/shared/schemas/thoughtspot-table-tml.md` — in particular:

* `column_id` is `TABLE::COL`, using the `model_tables[]` `alias` when one is set;
* model columns carry **no** `data_type` (the model schema's currency anchor says so
  outright) — types live on the Table TML;
* `constraints:` is a **mapping** with a single `constraint:` list inside it, not a
  list at the top level (model schema, "## `constraints`");
* RLS lives at `table.rls_rules` as `{tables, table_paths, rules}`, and rule `expr`
  bracket refs use the **`table_paths` alias** — `[BANK_EMPLOYEES_1::COUNTRY]`
  (table schema, "### `rls_rules` fields");
* formula cross-references are written as the formula **id** — `[formula_<Name>]` —
  never the display name (model schema, "Formula cross-references: reference by id,
  not display name").
"""
from __future__ import annotations

import pytest

from ts_cli.audit.checks_perf import (
    check_p2, check_p3, check_p5, check_p7, check_p9, check_p11,
    check_p14, check_p15, check_p17,
)
from ts_cli.audit.context import make_context


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------

def _model(**model_body) -> dict:
    """A model TML document: `guid` at the root, everything else under `model:`."""
    body = {"name": "Sales"}
    body.update(model_body)
    return {"guid": "m-1", "model": body}


def _ctx(*models):
    return make_context(models=list(models))


def _measure(table, col):
    return {"name": col.replace("_", " ").title(), "column_id": f"{table}::{col}",
            "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}


def _attribute(table, col, **props):
    return {"name": col, "column_id": f"{table}::{col}",
            "properties": {"column_type": "ATTRIBUTE", **props}}


def _join(with_table):
    """An inline (Scenario B) join — `type` and `cardinality` are required together."""
    return {"with": with_table, "on": f"[A::{with_table}_KEY] = [{with_table}::KEY]",
            "type": "INNER", "cardinality": "MANY_TO_ONE"}


TABLE_FQN = "DUNDERMIFFLIN.PUBLIC.BANK_EMPLOYEES"


def _table(columns, rules=None):
    t = {"name": "BANK_EMPLOYEES", "db": "DUNDERMIFFLIN", "schema": "PUBLIC",
         "db_table": "BANK_EMPLOYEES", "columns": columns}
    if rules is not None:
        t["rls_rules"] = {
            "tables": [{"name": "BANK_EMPLOYEES"}],
            "table_paths": [{"id": "BANK_EMPLOYEES_1", "table": "BANK_EMPLOYEES",
                             "column": ["COUNTRY"]}],
            "rules": rules,
        }
    return {"guid": "t-1", "table": t}


def _table_ctx(columns, rules):
    return make_context(tables={TABLE_FQN: _table(columns, rules)})


def _varchar(name, **props):
    return {"name": name, "db_column_name": name,
            "properties": {"column_type": "ATTRIBUTE", **props},
            "db_column_properties": {"data_type": "VARCHAR"}}


# --------------------------------------------------------------------------
# P2 — scalar formula density
# --------------------------------------------------------------------------
# A formula counts as scalar when no columns[] entry surfacing it declares an
# aggregation. Six trips MEDIUM, eleven trips HIGH.

def _formula_model(n, aggregated):
    return _model(
        formulas=[{"id": f"formula_Margin {i}", "name": f"Margin {i}",
                   "expr": "[ORDERS::AMOUNT] - [ORDERS::COST]"} for i in range(n)],
        columns=[{"name": f"Margin {i}", "formula_id": f"formula_Margin {i}",
                  "properties": {"column_type": "MEASURE",
                                 **({"aggregation": "SUM"} if aggregated else {})}}
                 for i in range(n)],
    )


def test_p2_trips_on_six_unaggregated_formulas():
    findings = check_p2(_ctx(_formula_model(6, aggregated=False)))
    assert len(findings) == 1
    assert findings[0].check_id == "P2"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].metric == 6


def test_p2_escalates_past_ten():
    assert check_p2(_ctx(_formula_model(11, aggregated=False)))[0].severity == "HIGH"


def test_p2_clean_when_formulas_are_aggregated():
    """Same six formulas, each surfaced by an aggregating column: nothing to flag."""
    assert check_p2(_ctx(_formula_model(6, aggregated=True))) == []


def test_p2_clean_under_threshold():
    assert check_p2(_ctx(_formula_model(5, aggregated=False))) == []


AGGREGATE_EXPR_MODEL = _model(
    formulas=[{"id": f"formula_Rev {i}", "name": f"Rev {i}",
               "expr": "sum ( [ORDERS::AMOUNT] )"} for i in range(6)],
    columns=[{"name": f"Rev {i}", "formula_id": f"formula_Rev {i}",
              "properties": {"column_type": "MEASURE"}} for i in range(6)],
)


@pytest.mark.xfail(strict=True, reason=(
    "checks_perf.py:51-53 decides 'scalar' from whether the surfacing columns[] "
    "entry carries an `aggregation:` key, and never looks at `expr`. The model "
    "schema says that key is a no-op on an aggregate expr and APPLIES on a scalar "
    "one, so it does not discriminate -- it is wrong in both directions. Six "
    "`sum ( ... )` formulas are counted and reported as '6 scalar formulas (run at "
    "query time in TS engine)', and six genuinely row-level ones are excluded "
    "whenever their column declares an aggregation. Reported, not fixed."))
def test_p2_metric_counts_the_wrong_formulas():
    assert check_p2(_ctx(AGGREGATE_EXPR_MODEL)) == [], \
        "sum ( ... ) is not a scalar formula"
    assert len(check_p2(_ctx(_formula_model(6, aggregated=True)))) == 1, \
        "[A] - [B] is scalar whether or not the column rolls it up"


# --------------------------------------------------------------------------
# P3 — model filters with no apply_on_tables
# --------------------------------------------------------------------------
# Model schema, filters[] fields: "apply_on_tables ... Absent -> filter is always
# applied (mandatory)." That absence is what P3 reports.

MANDATORY_FILTER = {"column": ["Region"], "oper": "in", "values": ["APAC"]}
SCOPED_FILTER = {"column": ["Quantity"], "oper": ">", "values": ["100"],
                 "apply_on_tables": ["Lineorder", "Supplier"]}


def test_p3_trips_on_a_filter_without_apply_on_tables():
    findings = check_p3(_ctx(_model(filters=[MANDATORY_FILTER, SCOPED_FILTER])))
    assert len(findings) == 1
    assert findings[0].check_id == "P3"
    assert findings[0].metric == 1
    assert "1/2" in findings[0].detail


def test_p3_clean_when_every_filter_is_table_scoped():
    assert check_p3(_ctx(_model(filters=[SCOPED_FILTER]))) == []


def test_p3_clean_when_model_has_no_filters():
    assert check_p3(_ctx(_model())) == []


# --------------------------------------------------------------------------
# P5 — no date constraints on a model with fact tables
# --------------------------------------------------------------------------
# "Fact table" = a model_tables[] entry with >3 MEASURE columns whose column_id
# prefix matches its name.

FACT_COLUMNS = [_measure("ORDERS", c) for c in
                ("AMOUNT", "COST", "QUANTITY", "DISCOUNT")]

# The shape a live export actually produces (model schema, "## `constraints`"):
# a mapping whose single key is `constraint`.
REAL_CONSTRAINTS = {"constraint": [
    {"table": "ORDERS",
     "condition": [{"date_range_condition": {"column": "order date",
                                             "duration": 1, "bucket": "YEAR"}}]},
]}


def _p5_model(constraints=None):
    body = {"model_tables": [{"name": "ORDERS", "fqn": "t-orders"}],
            "columns": FACT_COLUMNS}
    if constraints is not None:
        body["constraints"] = constraints
    return _model(**body)


def test_p5_trips_on_an_unconstrained_fact_model():
    findings = check_p5(_ctx(_p5_model()))
    assert len(findings) == 1
    assert findings[0].check_id == "P5"
    assert "ORDERS" in findings[0].detail


def test_p5_clean_when_no_table_looks_like_a_fact():
    """Three measures is not >3, so no fact table, so nothing to constrain."""
    thin = _model(model_tables=[{"name": "ORDERS", "fqn": "t-orders"}],
                  columns=FACT_COLUMNS[:3])
    assert check_p5(_ctx(thin)) == []


def test_p5_clean_when_the_model_has_no_tables():
    assert check_p5(_ctx(_model(columns=FACT_COLUMNS))) == []


@pytest.mark.xfail(strict=True, reason=(
    "checks_perf.py:112-116 iterates `constraints` as if it were a list of "
    "constraint entries. The exported shape is a MAPPING -- {'constraint': [...]} "
    "-- so `for c in constraints` yields the single key string 'constraint', which "
    "never contains 'date_range_condition'. The suppression is dead: P5 reports "
    "'No date constraints' on every fact model, including ones that carry a rolling "
    "date window. Reported, not fixed."))
def test_p5_a_real_date_constraint_should_suppress_the_finding():
    assert check_p5(_ctx(_p5_model(REAL_CONSTRAINTS))) == []


def test_p5_suppression_only_works_on_a_shape_no_export_produces():
    """Pinning the above: flatten the mapping by hand and the guard starts working."""
    flattened = REAL_CONSTRAINTS["constraint"]        # a list, which TML never is
    assert check_p5(_ctx(_p5_model(flattened))) == []


# --------------------------------------------------------------------------
# P7 — join depth
# --------------------------------------------------------------------------
# `joins[]` lives on the source (FK) entry; `with` names the target model_tables
# entry. A->B->C->D->E is depth 4.

def _chain(names):
    tables = [{"name": n, "fqn": f"t-{n}", "joins": [_join(nxt)]}
              for n, nxt in zip(names, names[1:])]
    tables.append({"name": names[-1], "fqn": f"t-{names[-1]}"})
    return _model(model_tables=tables)


def test_p7_trips_on_a_four_hop_chain():
    findings = check_p7(_ctx(_chain(["A", "B", "C", "D", "E"])))
    assert len(findings) == 1
    assert findings[0].check_id == "P7"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].metric == 4


def test_p7_escalates_past_five_hops():
    findings = check_p7(_ctx(_chain(["A", "B", "C", "D", "E", "F", "G"])))
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 6


def test_p7_clean_on_a_star_schema():
    """One fact joined to two dimensions is depth 1 — the shape we want people to use."""
    star = _model(model_tables=[
        {"name": "A", "fqn": "t-a", "joins": [_join("DIM1"), _join("DIM2")]},
        {"name": "DIM1", "fqn": "t-d1"},
        {"name": "DIM2", "fqn": "t-d2"},
    ])
    assert check_p7(_ctx(star)) == []


def test_p7_clean_when_the_model_has_no_joins():
    assert check_p7(_ctx(_model(model_tables=[{"name": "A", "fqn": "t-a"}]))) == []


# --------------------------------------------------------------------------
# P9 — high-cardinality ID column indexed as ATTRIBUTE
# --------------------------------------------------------------------------
# The name pattern is snake_case-anchored (`_id|_guid|_uuid|...$`), so it only
# matches a model whose column display names are the physical names.

def _p9_model(name, index_type=None):
    props = {"index_type": index_type} if index_type else {}
    return _model(columns=[_attribute("ORDERS", name, **props)])


def test_p9_trips_on_an_indexed_id_attribute():
    findings = check_p9(_ctx(_p9_model("CUSTOMER_ID", "DEFAULT")))
    assert len(findings) == 1
    assert findings[0].check_id == "P9"
    assert findings[0].object_name == "CUSTOMER_ID"


@pytest.mark.parametrize("name", ["ORDER_GUID", "SESSION_UUID", "ROW_ID",
                                  "TRANSACTION_ID", "SURROGATE_KEY"])
def test_p9_trips_on_every_id_suffix_in_the_pattern(name):
    assert len(check_p9(_ctx(_p9_model(name, "PREFIX_ONLY")))) == 1


def test_p9_clean_on_a_measure():
    m = _model(columns=[{"name": "ORDER_ID", "column_id": "ORDERS::ORDER_ID",
                         "properties": {"column_type": "MEASURE",
                                        "aggregation": "COUNT",
                                        "index_type": "DEFAULT"}}])
    assert check_p9(_ctx(m)) == []


def test_p9_clean_on_a_non_id_attribute():
    assert check_p9(_ctx(_p9_model("REGION_NAME", "DEFAULT"))) == []


def test_p9_misses_a_friendly_display_name():
    """Not a bug so much as a blind spot worth recording.

    `_ID_PATTERN` anchors on an underscore, and `columns[].name` is the *display*
    name. A model built with friendly names -- the common case for anything a
    converter produced -- never matches, however the column is indexed.
    """
    assert check_p9(_ctx(_p9_model("Customer Id", "DEFAULT"))) == []


def test_p9_index_type_sense_is_inverted():
    """`index_type` absent means indexed; P9 used to test presence (BL-299, fixed)."""
    assert check_p9(_ctx(_p9_model("CUSTOMER_ID", "DONT_INDEX"))) == [], \
        "DONT_INDEX means NOT indexed"
    assert len(check_p9(_ctx(_p9_model("CUSTOMER_ID")))) == 1, \
        "an omitted index_type IS the indexed default"


# --------------------------------------------------------------------------
# P11 — indexed-column count on a Spotter-enabled model
# --------------------------------------------------------------------------

def _p11_model(n, index_type=None, spotter=True):
    props = {"index_type": index_type} if index_type else {}
    return _model(
        properties={"spotter_config": {"is_spotter_enabled": spotter}},
        columns=[_attribute("ORDERS", f"COL_{i}", **props) for i in range(n)],
    )


def test_p11_trips_past_thirty_indexed_columns():
    findings = check_p11(_ctx(_p11_model(31, "DEFAULT")))
    assert len(findings) == 1
    assert findings[0].check_id == "P11"
    assert findings[0].severity == "INFO"
    assert findings[0].metric == 31


def test_p11_clean_at_the_threshold():
    assert check_p11(_ctx(_p11_model(30, "DEFAULT"))) == []


def test_p11_clean_when_spotter_is_disabled():
    assert check_p11(_ctx(_p11_model(31, "DEFAULT", spotter=False))) == []


def test_p11_clean_when_spotter_config_is_absent():
    m = _model(columns=[_attribute("ORDERS", f"COL_{i}", index_type="DEFAULT")
                        for i in range(31)])
    assert check_p11(_ctx(m)) == []


def test_p11_index_type_sense_is_inverted():
    """P11 counted columns carrying the key, not indexed ones (BL-299, fixed)."""
    assert check_p11(_ctx(_p11_model(31, "DONT_INDEX"))) == [], \
        "DONT_INDEX means NOT indexed"
    assert len(check_p11(_ctx(_p11_model(31)))) == 1, \
        "an omitted index_type IS the indexed default"


# --------------------------------------------------------------------------
# P14 — RLS expression wrapped in a function
# --------------------------------------------------------------------------
# Live rule exprs look like `ts_groups = [BANK_EMPLOYEES_1::COUNTRY]` (table
# schema). Wrapping either side in upper()/trim()/cast() is what P14 reports.

PLAIN_RULE = {"name": "Country rule",
              "expr": "ts_groups = [BANK_EMPLOYEES_1::COUNTRY]"}
FUNC_RULE = {"name": "Country rule",
             "expr": "upper ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups"}


def test_p14_trips_on_a_function_wrapped_rls_expression():
    findings = check_p14(_table_ctx([_varchar("COUNTRY")], [FUNC_RULE]))
    assert len(findings) == 1
    assert findings[0].check_id == "P14"
    assert findings[0].object_name == "BANK_EMPLOYEES"
    assert "upper" in findings[0].detail


@pytest.mark.parametrize("expr", [
    "trim ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups",
    "cast ( [BANK_EMPLOYEES_1::COUNTRY] as varchar ) = ts_groups",
    "concat ( [BANK_EMPLOYEES_1::COUNTRY] , 'x' ) = ts_groups",
    "if ( ts_groups = 'admin' , true , [BANK_EMPLOYEES_1::COUNTRY] = ts_groups )",
])
def test_p14_trips_on_each_function_in_the_pattern(expr):
    ctx = _table_ctx([_varchar("COUNTRY")], [{"name": "R", "expr": expr}])
    assert len(check_p14(ctx)) == 1


def test_p14_clean_on_a_bare_column_comparison():
    assert check_p14(_table_ctx([_varchar("COUNTRY")], [PLAIN_RULE])) == []


def test_p14_clean_when_the_table_has_no_rls():
    assert check_p14(make_context(tables={TABLE_FQN: _table([_varchar("COUNTRY")])})) == []


# --------------------------------------------------------------------------
# P15 — VARCHAR RLS column with no value_casing
# --------------------------------------------------------------------------
# P15 reads db_column_properties.data_type off ctx.tables, which is where the
# type actually lives -- the opposite of the P6/D2 defect (finding 14.1), where
# the same key was read off the MODEL, whose columns carry no data type. The
# tests below pin that: a model-side data_type must not influence the result.

def test_p15_trips_on_an_uncased_varchar_rls_column():
    findings = check_p15(_table_ctx([_varchar("COUNTRY")], [PLAIN_RULE]))
    assert len(findings) == 1
    assert findings[0].check_id == "P15"
    assert findings[0].object_name == "COUNTRY"


def test_p15_clean_when_value_casing_is_set():
    ctx = _table_ctx([_varchar("COUNTRY", value_casing="UPPER")], [PLAIN_RULE])
    assert check_p15(ctx) == []


def test_p15_clean_on_an_integer_rls_column():
    int_col = {"name": "COUNTRY_ID", "db_column_name": "COUNTRY_ID",
               "properties": {"column_type": "ATTRIBUTE"},
               "db_column_properties": {"data_type": "INT64"}}
    rule = {"name": "R", "expr": "ts_groups_int = [BANK_EMPLOYEES_1::COUNTRY_ID]"}
    assert check_p15(_table_ctx([int_col], [rule])) == []


def test_p15_clean_when_the_table_has_no_rls():
    assert check_p15(make_context(tables={TABLE_FQN: _table([_varchar("COUNTRY")])})) == []


def test_p15_reads_the_type_off_the_table_not_a_model():
    """A model in the context must not be able to supply (or fake) the type.

    This is the check the audit asked about by name: P15 touches
    `db_column_properties` the way the two broken checks did, but it iterates
    `ctx.tables`, so it reads the key on the object that actually carries it.
    """
    lying_model = _model(columns=[
        {"name": "COUNTRY", "column_id": "BANK_EMPLOYEES::COUNTRY",
         "properties": {"column_type": "ATTRIBUTE"},
         "db_column_properties": {"data_type": "INT64"}},   # a lie, and ignored
    ])
    ctx = make_context(models=[lying_model],
                       tables={TABLE_FQN: _table([_varchar("COUNTRY")], [PLAIN_RULE])})
    assert len(check_p15(ctx)) == 1, "the TABLE's VARCHAR is what counts"


def test_p15_misses_a_column_whose_display_name_differs_from_the_physical_one():
    """Blind spot worth recording, not a fixture problem.

    checks_perf.py:303 keys the lookup on `columns[].name`, but an RLS expr
    references the *physical* column through the table_paths alias. The table
    schema requires `db_column_name` precisely because the two can differ; when
    they do, the lookup misses and the column is silently passed.
    """
    friendly = {"name": "Country", "db_column_name": "COUNTRY",
                "properties": {"column_type": "ATTRIBUTE"},
                "db_column_properties": {"data_type": "VARCHAR"}}
    assert check_p15(_table_ctx([friendly], [PLAIN_RULE])) == []


# --------------------------------------------------------------------------
# P17 — formula cross-reference chain depth  (CANNOT TRIP on real TML)
# --------------------------------------------------------------------------
# checks_perf.py:351  formula_names = {f.get("name", "") for f in formulas}
# checks_perf.py:357  cross_refs = [r for r in refs if r in formula_names ...]
#
# Real TML references a formula by its **id**, and the id is by construction
# "formula_" + name. So the token pulled out of the expr is "formula_Category
# Quantity" while the set holds "Category Quantity" — the two can never be equal,
# for any model, and the graph is always empty.
#
# The only shape that DOES match is a bare display-name ref, which the model
# schema records as failing on first import ("Search did not find ..."). Since
# the audit only ever sees TML exported from an instance, every model it reads
# imported successfully, so no model it reads can carry that shape.

REAL_EXPORT_FORMULAS = [
    # Verbatim from agents/shared/worked-examples/snowflake/ts-to-snowflake.md
    # (an exported DunderMifflin Model): a real cross-reference, id-style.
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
ID_REF_CHAIN = [
    {"id": f"formula_{n}", "name": n,
     "expr": (f"[formula_{nxt}] * 2" if nxt else "sum ( [ORDERS::AMOUNT] )")}
    for n, nxt in zip(CHAIN_NAMES, CHAIN_NAMES[1:] + [None])
]
DISPLAY_REF_CHAIN = [
    {"id": f"formula_{n}", "name": n,
     "expr": (f"[{nxt}] * 2" if nxt else "sum ( [ORDERS::AMOUNT] )")}
    for n, nxt in zip(CHAIN_NAMES, CHAIN_NAMES[1:] + [None])
]

def test_p17_returns_nothing_for_a_real_exported_cross_reference():
    """Minimal reproduction against TML copied out of a live export."""
    assert check_p17(_ctx(_model(formulas=REAL_EXPORT_FORMULAS))) == []


def test_p17_only_fires_on_the_shape_that_fails_import():
    """The same chain with display-name refs does trip it — and cannot be imported.

    This is what makes P17 unreachable rather than merely under-tuned: the one
    input shape it recognises is the shape ThoughtSpot rejects, so no exported
    model can ever carry it.
    """
    findings = check_p17(_ctx(_model(formulas=DISPLAY_REF_CHAIN)))
    assert [(f.object_name, f.metric) for f in findings] == [("A", 4), ("B", 3)]


def test_p17_should_see_the_chain_a_real_model_actually_carries():
    findings = check_p17(_ctx(_model(formulas=ID_REF_CHAIN)))
    assert [(f.object_name, f.metric) for f in findings] == [("A", 4), ("B", 3)]

# NOTE: the H7/P17 defect-characterization tests that lived here were removed
# when BL-300/BL-301 were fixed — they asserted the broken behaviour by design
# and their names encoded it. The corrected behaviour is covered by
# tools/ts-cli/tests/test_unreachable_checks.py.
