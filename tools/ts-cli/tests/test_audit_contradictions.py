"""The BL-406 contradictions ruled on 2026-10-23 (roadmap PR 2.2), plus BL-461 and
BL-462: each rule's new behaviour, held directly rather than only through the pins.

- A4 is titled for what it checks (a Model description).
- D7 reports a partial overlap only when a table both Models contain is a fact
  table in either.
- D9 matches every `sql_<type>_aggregate_op` (BL-461).
- D11 words an INFO finding by the join's own cardinality, and reads a referencing
  join's cardinality from its Table when the model gives none.
- H10's MEDIUM-when-orphan is in test_audit_rules_human.py.
- P18 also reads distinct-count formulas (BL-462).
"""
import pytest

import audit_rule_fixtures as fx
from audit_run_rule import run_rule
from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.context import make_context


def test_a4_is_titled_for_what_it_checks():
    assert load_catalog().rules["A4"].title == "Model has no description"


# ── D7 ──────────────────────────────────────────────────────────────────────

def _measures(table, n):
    return [{"name": f"{table} M{i}", "column_id": f"{table}::M{i}",
             "properties": {"column_type": "MEASURE"}} for i in range(n)]


def _overlap_ctx(fact_in_both: bool):
    """M1 has tables F, D1, D2, D3; M2 has F, D1, D2: Jaccard 0.75. F is a fact table
    (4 MEASURE columns) in M1; in M2 too when `fact_in_both`, else M2 surfaces only one
    of its measures (as a Model measuring F through formulas would)."""
    tables = [{"name": n, "fqn": f"db.s.{n}"} for n in ("F", "D1", "D2", "D3")]
    return make_context(models=[
        fx.build_data_model(name="M1", guid="g1", model_tables=tables,
                            columns=_measures("F", 4)),
        fx.build_data_model(name="M2", guid="g2", model_tables=tables[:3],
                            columns=_measures("F", 4 if fact_in_both else 1)),
    ])


def test_d7_partial_overlap_with_a_shared_fact_is_medium():
    [f] = run_rule(_overlap_ctx(fact_in_both=True), "D7")
    assert (f.severity, f.object_name, f.metric) == ("MEDIUM", "M1 / M2", 0.75)
    assert f.threshold == {"high_overlap": 0.5}
    assert f.detail == "High overlap: 3/4 tables shared (Jaccard 0.75)"


def test_d7_a_shared_table_that_is_a_fact_in_either_model_counts():
    """The fact test counts physical measures only, so a Model measuring F through
    formulas reads F as a dimension; F is still the fact both Models share."""
    [f] = run_rule(_overlap_ctx(fact_in_both=False), "D7")
    assert f.severity == "MEDIUM"


def test_d7_models_sharing_only_dimensions_are_silent():
    """M1 = F, D1, D2, D3 and M2 = G, D1, D2, D3: Jaccard 0.6, but their fact tables
    differ and every shared table is a dimension."""
    dims = [{"name": n, "fqn": f"db.s.{n}"} for n in ("D1", "D2", "D3")]
    ctx = make_context(models=[
        fx.build_data_model(name="M1", guid="g1",
                            model_tables=[{"name": "F", "fqn": "db.s.F"}] + dims,
                            columns=_measures("F", 4)),
        fx.build_data_model(name="M2", guid="g2",
                            model_tables=[{"name": "G", "fqn": "db.s.G"}] + dims,
                            columns=_measures("G", 4))])
    assert run_rule(ctx, "D7") == []


def test_d7_finds_an_aliased_fact_table():
    """Columns carry the alias as their prefix; a name-only lookup saw no fact."""
    tables = [{"name": "F", "alias": "Sales", "fqn": "db.s.F"}] + \
        [{"name": n, "fqn": f"db.s.{n}"} for n in ("D1", "D2", "D3")]
    ctx = make_context(models=[
        fx.build_data_model(name="M1", guid="g1", model_tables=tables,
                            columns=_measures("Sales", 4)),
        fx.build_data_model(name="M2", guid="g2", model_tables=tables[:3],
                            columns=_measures("Sales", 4))])
    [f] = run_rule(ctx, "D7")
    assert f.severity == "MEDIUM"


def test_d7_identical_models_are_high_with_or_without_facts():
    [f] = run_rule(fx.data_models_identical_tables(), "D7")
    assert f.severity == "HIGH"


def test_d7_half_overlap_is_still_below_the_line():
    """Jaccard 0.5 exactly is not above 0.5, shared fact or not."""
    tables = [{"name": n, "fqn": f"db.s.{n}"} for n in ("F", "A", "B")]
    ctx = make_context(models=[
        fx.build_data_model(name="M1", guid="g1", model_tables=tables[:2],
                            columns=_measures("F", 4)),
        fx.build_data_model(name="M2", guid="g2", model_tables=[tables[0], tables[2]],
                            columns=_measures("F", 4))])
    assert run_rule(ctx, "D7") == []


# ── D9 (BL-461) ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", ["sql_double_aggregate_op", "sql_date_aggregate_op",
                                "SQL_DATE_TIME_AGGREGATE_OP", "sql_int_aggregate_op"])
def test_d9_matches_every_pass_through_aggregate(fn):
    formulas = [{"name": "F", "expr": f"{fn}('sum({{0}})', [T1::X])"},
                {"name": "G", "expr": "sum([T1::Y])"}]
    ctx = make_context(models=[fx.build_data_model(formulas=formulas)])
    [f] = run_rule(ctx, "D9")
    assert f.detail.startswith("1/2 formulas")


def test_d9_ignores_a_scalar_pass_through_and_a_lookalike_name():
    formulas = [{"name": "F", "expr": "sql_int_op('{0} + 1', [T1::X])"},
                {"name": "G", "expr": "[my_sql_int_aggregate_op_total]"}]
    ctx = make_context(models=[fx.build_data_model(formulas=formulas)])
    assert run_rule(ctx, "D9") == []


# ── D11 ─────────────────────────────────────────────────────────────────────

def _referencing(table_cardinality=None, model_cardinality=None):
    ctx = fx.referencing_join_varchar()
    if table_cardinality:
        for table in ctx.tables.values():
            for j in table["table"].get("joins_with") or []:
                j["cardinality"] = table_cardinality
    if model_cardinality:
        for mt in ctx.models[0]["model"]["model_tables"]:
            for j in mt.get("joins") or []:
                j["cardinality"] = model_cardinality
    return ctx


def test_d11_reads_a_referencing_joins_cardinality_from_the_table():
    [f] = run_rule(_referencing(table_cardinality="ONE_TO_MANY"), "D11")
    assert (f.severity, f.detail.split(" join ")[0]) == ("INFO", "ONE_TO_MANY")


def test_d11_the_models_cardinality_wins_over_the_tables():
    assert run_rule(_referencing(table_cardinality="ONE_TO_MANY",
                                 model_cardinality="MANY_TO_ONE"), "D11") == []


def test_d11_a_referencing_join_with_no_cardinality_anywhere_is_silent():
    """Exported Table TML usually carries none: unknown, not reported."""
    assert run_rule(_referencing(), "D11") == []


# ── P18 (BL-462) ────────────────────────────────────────────────────────────

def _formula_model(expr, aggregation=None):
    col = {"name": "Users", "formula_id": "f1", "properties": {"column_type": "MEASURE"}}
    if aggregation:
        col["properties"]["aggregation"] = aggregation
    return make_context(models=[fx.build_data_model(
        columns=[col], formulas=[{"id": "f1", "name": "Users", "expr": expr}])])


@pytest.mark.parametrize("expr", [
    "unique count ( [T1::USER_ID] )", "UNIQUE  COUNT([T1::USER_ID])",
    "unique_count_if ( [T1::ACTIVE] = true , [T1::USER_ID] )",
    "group_unique_count ( [T1::USER_ID] , [T1::REGION] )"])
def test_p18_reports_a_distinct_count_formula(expr):
    [f] = run_rule(_formula_model(expr), "P18")
    assert (f.severity, f.detail) == ("INFO",
                                      "Distinct count on 'Users' (distinct-count formula)")


@pytest.mark.parametrize("expr", ["[Unique Count of Users] / 7",
                                  "if ( [T1::K] = 'unique count' ) then 1 else 0",
                                  "sum ( [T1::group_unique_count] )"])
def test_p18_ignores_a_name_inside_a_reference_or_a_literal(expr):
    assert run_rule(_formula_model(expr), "P18") == []


def test_p18_says_which_kind_it_found():
    [f] = run_rule(_formula_model("sum([T1::U])", "COUNT_DISTINCT"), "P18")
    assert f.detail == "Distinct count on 'Users' (COUNT_DISTINCT aggregation)"


@pytest.mark.parametrize("expr", ["count ( [T1::USER_ID] )", "sum ( [T1::uniquecount] )"])
def test_p18_ignores_other_counts(expr):
    assert run_rule(_formula_model(expr), "P18") == []


def test_p18_still_reports_count_distinct_aggregation_once():
    """A column both aggregated COUNT_DISTINCT and surfacing a unique count formula is
    one finding, not two."""
    assert len(run_rule(_formula_model("unique count([T1::U])", "COUNT_DISTINCT"),
                        "P18")) == 1
