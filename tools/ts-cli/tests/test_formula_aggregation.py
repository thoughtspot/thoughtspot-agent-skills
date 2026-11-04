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
    classify_expr, classify_model_columns, formula_aggregation, is_aggregate_expr,
    is_bare_window,
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
    ("group_unique_count ( [A::x] , [A::r] )", "SUM"),                  # no right answer: convention
    (f"GROUP_AGGREGATE ( AVERAGE ( [A::x] ) , {GROUPS} )", "AVERAGE"),  # any case
    (f"last_value ( [A::b] , {SNAP} )", "SUM"),                         # no inner aggregate
])
def test_formula_aggregation(expr, expected):
    assert formula_aggregation(expr) == expected


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


def _tableau():
    from ts_cli.model_builder import _build_model_columns
    return {"columns": _build_model_columns(
        [], [{"name": "T"}], [{"name": "Untyped", "expr": "sum ( [T::x] )"}])}


@pytest.mark.parametrize("build", [_powerbi, _sisense, _timeintel, _dbt_schema_yml,
                                   _dbt_manifest, _tableau],
                         ids=["powerbi", "sisense", "powerbi-timeintel", "dbt-schema-yml",
                              "dbt-manifest", "tableau-untyped"])
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
