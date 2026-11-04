"""BL-509: formula `aggregation:` under the product owner's ruling (2026-11-02).

The column `aggregation` of a formula is applied when the formula is per-row, and when
it is a bare group_aggregate / last_value / first_value (their group_* shorthands and
*_in_period spellings included); it is ignored for any other aggregate formula, which
must still declare one. `spotql_ops.formula_aggregation` is the one reading of what a
generator declares on a MEASURE formula column the source gave no aggregation for, and
every Model emitter declares one.
"""
from __future__ import annotations

import pytest

from ts_cli.spotql_ops import (
    classify_expr, classify_model_columns, declare_formula_aggregations, formula_aggregation,
    is_aggregate_expr, is_bare_window,
)

GROUPS = "query_groups ( ) , query_filters ( )"
SNAP = "query_groups ( ) , { [D::d] }"


@pytest.mark.parametrize("expr,expected", [
    ("[A::x] * 2", "SUM"),                                              # per-row: applied
    ("sum ( [A::x] )", "SUM"),                                          # aggregate: ignored
    (f"sum ( group_aggregate ( average ( [A::x] ) , {GROUPS} ) )", "SUM"),
    (f"group_aggregate ( average ( [A::x] ) , {GROUPS} )", "AVERAGE"),  # bare: applied
    (f"group_aggregate ( sum ( [A::x] ) , {GROUPS} )", "SUM"),
    (f"group_aggregate ( count ( [A::x] ) , {GROUPS} )", "SUM"),        # counts add
    (f"group_aggregate ( min ( [A::x] ) , {GROUPS} )", "MIN"),
    (f"group_aggregate ( max ( [A::x] ) , {GROUPS} )", "MAX"),
    (f"last_value ( sum ( [A::b] ) , {SNAP} )", "SUM"),                 # a balance
    (f"last_value ( average ( [A::rate] ) , {SNAP} )", "AVERAGE"),
    (f"first_value ( max ( [A::x] ) , {SNAP} )", "MAX"),
    (f"last_value_in_period ( average ( [A::rate] ) , {SNAP} )", "AVERAGE"),
    (f"first_value_in_period ( min ( [A::x] ) , {SNAP} )", "MIN"),
    ("group_average ( [A::x] , [A::r] )", "AVERAGE"),                    # shorthands
    ("group_sum ( [A::x] , [A::r] )", "SUM"),
    ("group_min ( [A::x] , [A::r] )", "MIN"),
    ("group_max ( [A::x] , [A::r] )", "MAX"),
    ("group_count ( [A::x] , [A::r] )", "SUM"),
    ("group_unique_count ( [A::x] , [A::r] )", "AVERAGE"),              # not additive
    (f"group_aggregate ( sum ( [A::a] ) / sum ( [A::b] ) , {GROUPS} )", "AVERAGE"),  # a ratio
    (f"group_aggregate ( average_if ( [A::f] , [A::x] ) , {GROUPS} )", "AVERAGE"),
    (f"group_aggregate ( max_if ( [A::f] , [A::x] ) , {GROUPS} )", "MAX"),
    (f"group_aggregate ( count_if ( [A::f] , [A::x] ) , {GROUPS} )", "SUM"),
    (f"group_aggregate ( [formula_Unknown] , {GROUPS} )", "SUM"),       # opaque: convention
    (f"GROUP_AGGREGATE ( AVERAGE ( [A::x] ) , {GROUPS} )", "AVERAGE"),  # any case
    (f"last_value ( [A::b] , {SNAP} )", "SUM"),                         # no inner aggregate
])
def test_formula_aggregation(expr, expected):
    assert formula_aggregation(expr) == expected


def test_formula_aggregation_sees_through_a_formula_reference():
    """Power BI and promote write the inner aggregate as `[formula_X]` (review of PR 2)."""
    index = {"formula_Avg Sales": "average ( [F::amount] )", "Avg Sales": "average ( [F::amount] )",
             "formula_Total": "sum ( [F::amount] )"}
    assert formula_aggregation(f"group_aggregate ( [formula_Avg Sales] , {GROUPS} )", index) == "AVERAGE"
    assert formula_aggregation(f"group_aggregate ( [Avg Sales] , {GROUPS} )", index) == "AVERAGE"
    assert formula_aggregation(f"last_value ( [formula_Total] , {SNAP} )", index) == "SUM"
    # a chain of references and a cycle both end
    chain = {"formula_A": "[formula_B]", "formula_B": "min ( [F::x] )"}
    assert formula_aggregation(f"group_aggregate ( [formula_A] , {GROUPS} )", chain) == "MIN"
    loop = {"formula_A": "[formula_A]"}
    assert formula_aggregation(f"group_aggregate ( [formula_A] , {GROUPS} )", loop) == "SUM"


def test_declare_fills_only_undeclared_measure_formula_columns():
    columns = [
        {"name": "Avg", "formula_id": "f_avg", "properties": {"column_type": "MEASURE"}},
        {"name": "Kept", "formula_id": "f_avg", "properties": {"column_type": "MEASURE",
                                                            "aggregation": "MAX"}},
        {"name": "Attr", "formula_id": "f_attr", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Untyped", "formula_id": "f_avg", "properties": {}},
        {"name": "Phys", "column_id": "F::x", "properties": {"column_type": "MEASURE"}},
    ]
    formulas = [{"id": "f_inner", "name": "Inner", "expr": "average ( [F::x] )"},
                {"id": "f_avg", "name": "Avg", "expr": f"group_aggregate ( [f_inner] , {GROUPS} )"},
                {"id": "f_attr", "name": "Attr", "expr": "upper ( [F::r] )"}]
    declare_formula_aggregations(columns, formulas)
    props = {c["name"]: c["properties"] for c in columns}
    assert props["Avg"]["aggregation"] == "AVERAGE"
    assert props["Kept"]["aggregation"] == "MAX"
    assert "aggregation" not in props["Attr"]
    assert props["Untyped"] == {"aggregation": "AVERAGE"}       # untyped reads as MEASURE
    assert "aggregation" not in props["Phys"]                    # formula columns only


@pytest.mark.parametrize("expr,bare", [
    (f"group_aggregate ( sum ( [A::x] ) , {GROUPS} )", True),
    ("group_average ( [A::x] , [A::r] )", True),
    (f"last_value_in_period ( sum ( [A::x] ) , {SNAP} )", True),
    (f"sum ( last_value ( sum ( [A::x] ) , {SNAP} ) )", False),
    (f"last_value ( sum ( [A::x] ) , {SNAP} ) + 1", False),
    ("sum ( [A::x] )", False),
    (None, False),
])
def test_is_bare_window(expr, bare):
    assert is_bare_window(expr) is bare


def test_the_in_period_spellings_are_aggregate():
    assert is_aggregate_expr(f"last_value_in_period ( [A::x] , {SNAP} )")
    assert is_aggregate_expr(f"first_value_in_period ( sum ( [A::x] ) , {SNAP} )")


def test_classify_expr_declares_the_applied_aggregation_on_a_bare_window():
    """`ts model promote-formula` writes this: a per-group average must not be summed."""
    out = classify_expr(f"group_aggregate ( average ( [A::x] ) , {GROUPS} )")
    assert out == {"column_type": "MEASURE", "aggregation": "AVERAGE", "is_aggregate": True}
    assert classify_expr("[A::x] + 1")["aggregation"] is None
    ref = f"group_aggregate ( [formula_Avg] , {GROUPS} )"
    assert classify_expr(ref, {"formula_Avg": "average ( [A::x] )"})["aggregation"] == "AVERAGE"


def test_an_in_period_snapshot_is_semi_additive_for_agentql():
    model = {"columns": [{"name": "Bal", "formula_id": "f1",
                          "properties": {"column_type": "MEASURE"}}],
             "formulas": [{"id": "f1", "name": "Bal",
                           "expr": f"last_value_in_period ( sum ( [A::b] ) , {SNAP} )"}]}
    (col,) = classify_model_columns(model)
    assert col["kind"] == "semiadditive_measure" and col["wrapper"] == "SUM"


# ── every Model emitter declares an aggregation on a MEASURE formula column ──

def _undeclared(model: dict) -> list:
    return [c["name"] for c in model.get("columns", [])
            if c.get("formula_id") and c.get("properties", {}).get("column_type") == "MEASURE"
            and not c["properties"].get("aggregation")]


def _powerbi():
    from test_powerbi_build_model import _build
    return _build()[2]


def test_powerbi_group_aggregate_over_a_measure_reference_is_averaged():
    from ts_cli.powerbi.build_model import assemble
    from test_powerbi_build_model import _inv
    inv = _inv()
    inv["tables"][0]["measures"] += [
        {"name": "Avg Sales", "expression": "AVERAGE(Fact[Amount])"},
        {"name": "Avg Sales All Names", "expression": "CALCULATE([Avg Sales], ALL(Dim[Name]))"}]
    files, _ = assemble(inv, {}, "MyConn", "db1", "sch1", "LEFT_OUTER", False)
    model = next(t for fn, t in files if fn.endswith(".model.tml"))["model"]
    exprs = {f["name"]: f["expr"] for f in model["formulas"]}
    assert exprs["Avg Sales All Names"].startswith("group_aggregate ( [formula_Avg Sales]") or \
        "[formula_Avg Sales]" in exprs["Avg Sales All Names"]
    cols = {c["name"]: c["properties"] for c in model["columns"]}
    assert cols["Avg Sales All Names"]["aggregation"] == "AVERAGE"


def _sisense():
    from test_sisense_build_model import _build
    return _build()[2]


def _timeintel():
    from ts_cli.powerbi.timeintel import build_time_intelligence
    return build_time_intelligence(
        [{"base_name": "New Hires", "base_expr": "[formula_isNewHire]"}], date_column="Date")


_SCHEMA_YML = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: AMOUNT
        config: {meta: {ts_column_type: measure, ts_aggregation: sum}}
      - name: Avg Amount
        config:
          meta:
            ts_formula: 'group_aggregate ( average ( [STG_ORDERS::AMOUNT] ) , query_groups ( ) , query_filters ( ) )'
            ts_column_type: measure
      - name: Total
        config:
          meta:
            ts_formula: 'sum ( [STG_ORDERS::AMOUNT] )'
            ts_column_type: measure
"""


def _dbt_schema_yml():
    from ts_cli.dbt.model_from_schema_yml import build_model_tml_from_schema_yml
    return build_model_tml_from_schema_yml(_SCHEMA_YML, "M")["model"]


def _dbt_manifest():
    from ts_cli.dbt.manifest import build_model_tml_from_manifest
    nodes = {"model.p.orders": {
        "resource_type": "model", "name": "orders",
        "original_file_path": "models/x/orders.sql",
        "columns": {
            "AMOUNT": {"config": {"meta": {"ts_column_type": "measure",
                                            "ts_aggregation": "sum"}}},
            "AVG_AMOUNT": {"config": {"meta": {
                "ts_column_type": "measure",
                "ts_formula": f"group_aggregate ( average ( [ORDERS::AMOUNT] ) , {GROUPS} )"}}},
        }}}
    return build_model_tml_from_manifest({"nodes": nodes}, {}, "models/x", "M",
                                         metrics=False)["model"]


def _aggregates():
    """`ts aggregate generate` passes formulas with no column_type (review of PR 2)."""
    from ts_cli.model_builder import build_model_tml
    return build_model_tml(
        model_name="M", connection_name="C", tables=[{"name": "T"}], columns=[], joins=[],
        translated_formulas=[{"name": "Avg Sale", "expr": "sum ( [T::x] ) / count ( [T::x] )"},
                             {"name": "Sales", "expr": "sum ( [T::x] )"}],
        parameters=[])["model"]


def _tableau_merge():
    """`ts tableau build-model --existing-guid` strips column_type before the merge."""
    from ts_cli.model_builder import merge_formulas_into_model
    existing = {"model": {"name": "M", "formulas": [], "columns": [
        {"name": "x", "column_id": "T::x", "properties": {"column_type": "MEASURE"}}]}}
    out = merge_formulas_into_model(existing, [
        {"id": "formula_Total", "name": "Total", "expr": "sum ( [T::x] )"},
        {"id": "formula_Per Customer", "name": "Per Customer",
         "expr": f"group_aggregate ( average ( [T::x] ) , {GROUPS} )"}])
    return out["model"]


@pytest.mark.parametrize("build", [_powerbi, _sisense, _timeintel, _dbt_schema_yml,
                                   _dbt_manifest, _aggregates, _tableau_merge],
                         ids=["powerbi", "sisense", "powerbi-timeintel", "dbt-schema-yml",
                              "dbt-manifest", "aggregates-untyped", "tableau-merge"])
def test_every_measure_formula_column_declares_an_aggregation(build):
    model = build()
    assert any(c.get("formula_id") and c["properties"].get("column_type") == "MEASURE"
               for c in model["columns"]), "the input must emit a MEASURE formula column"
    assert _undeclared(model) == []


def test_dbt_declares_the_applied_aggregation_for_a_bare_window():
    cols = {c["name"]: c["properties"] for c in _dbt_schema_yml()["columns"]}
    assert cols["Avg Amount"]["aggregation"] == "AVERAGE"
    assert cols["Total"]["aggregation"] == "SUM"


def test_a_declared_aggregation_is_kept():
    yml = _SCHEMA_YML.replace("ts_column_type: measure\n      - name: Total",
                              "ts_column_type: measure\n            ts_aggregation: max\n"
                              "      - name: Total")
    from ts_cli.dbt.model_from_schema_yml import build_model_tml_from_schema_yml
    cols = {c["name"]: c["properties"]
            for c in build_model_tml_from_schema_yml(yml, "M")["model"]["columns"]}
    assert cols["Avg Amount"]["aggregation"] == "MAX"


def test_the_aggregates_generator_declares_by_the_formula_not_the_name():
    """An aggregate formula's column aggregation is ignored: SUM, not the name heuristic's
    AVERAGE for "Avg Sale"."""
    cols = {c["name"]: c["properties"] for c in _aggregates()["columns"]}
    assert cols["Avg Sale"]["aggregation"] == "SUM" and cols["Sales"]["aggregation"] == "SUM"


def test_the_tableau_merge_declares_the_applied_aggregation():
    cols = {c["name"]: c["properties"] for c in _tableau_merge()["columns"]}
    assert cols["Per Customer"]["aggregation"] == "AVERAGE"
    assert cols["Total"]["aggregation"] == "SUM"
    assert "aggregation" not in cols["x"]          # an existing column is left as it was


def test_formula_translate_snippet_and_manifest_keep_their_aggregations():
    from ts_cli.formula_translate.engine import formula_tml_entries
    _, col = formula_tml_entries("Per Group", f"group_aggregate ( max ( [A::x] ) , {GROUPS} )",
                                 "MEASURE")
    assert col["properties"]["aggregation"] == "MAX"
    from ts_cli.dbt.manifest import build_model_tml_from_manifest
    nodes = {"model.p.orders": {
        "resource_type": "model", "name": "orders", "original_file_path": "models/x/orders.sql",
        "columns": {"AVG_AMOUNT": {"config": {"meta": {
            "ts_column_type": "measure", "ts_aggregation": "min",
            "ts_formula": f"group_aggregate ( average ( [ORDERS::AMOUNT] ) , {GROUPS} )"}}}}}}
    model = build_model_tml_from_manifest({"nodes": nodes}, {}, "models/x", "M", metrics=False)
    (col,) = [c for c in model["model"]["columns"] if c.get("formula_id")]
    assert col["properties"]["aggregation"] == "MIN"


def test_promote_resolves_an_inner_reference_to_a_model_formula():
    """`ts model promote-formula` rewrites Answer refs to `[formula_X]` (review of PR 2)."""
    from ts_cli.promote import build_merged_model
    model = {"model": {"name": "M", "columns": [], "formulas": [
        {"id": "formula_Avg Sales", "name": "Avg Sales", "expr": "average ( [F::amount] )"}]}}
    to_add = [{"name": "Per Region Avg",
               "expr": f"group_aggregate ( [formula_Avg Sales] , {GROUPS} )"}]
    result = build_merged_model(model, to_add, [], [])
    (added,) = result["added"]
    assert added["aggregation"] == "AVERAGE"
