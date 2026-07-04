from __future__ import annotations
from ts_cli.tableau.build_model import (
    build_blend_components, map_ds_to_tables, derive_blend_joins, build_blend_plan,
)

STAR = {
    "Orders": [
        {"target_ds": "Targets", "column_mappings": [{"source_col": "Cat", "target_col": "Cat"}]},
        {"target_ds": "Budget", "column_mappings": [{"source_col": "Reg", "target_col": "Reg"}]},
    ],
}
DS = [
    {"name": "Orders", "tables": [{"name": "ORDERS"}]},
    {"name": "Targets", "tables": [{"name": "TARGETS"}]},
    {"name": "Budget", "tables": [{"name": "BUDGET"}]},
]

def test_components_star_single_group_primary_is_root():
    comps = build_blend_components(STAR)
    assert len(comps) == 1
    assert comps[0]["primary"] == "Orders"
    assert set(comps[0]["members"]) == {"Orders", "Targets", "Budget"}

def test_map_ds_to_tables_primary_table():
    assert map_ds_to_tables(DS) == {"Orders": "ORDERS", "Targets": "TARGETS", "Budget": "BUDGET"}

def test_derive_joins_over_all_edges():
    comp = build_blend_components(STAR)[0]
    joins = derive_blend_joins(comp, STAR, map_ds_to_tables(DS))
    ons = sorted(j["on"] for j in joins)
    assert ons == ["[ORDERS::Cat] = [TARGETS::Cat]", "[ORDERS::Reg] = [BUDGET::Reg]"]
    assert all(j["type"] == "LEFT_OUTER" for j in joins)

def test_build_blend_plan_empty_graph():
    assert build_blend_plan({}, DS) == {"components": [], "ds_table_map": {}, "joins": []}

def test_facade_reexport_resolves_to_same_callable():
    from ts_cli.model_builder import build_blend_plan as facade_build_blend_plan
    assert facade_build_blend_plan is build_blend_plan
