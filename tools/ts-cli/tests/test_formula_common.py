"""Relocation tests — ts_cli.formula_common is the canonical home; old paths are shims."""


def test_new_home_exports_all_four():
    from ts_cli.formula_common import (
        add_formula_prefix, expr_is_aggregated, fix_double_aggregation,
        resolve_name_collisions,
    )
    assert add_formula_prefix("[Profit]", {"Profit"}, set()) == "[formula_Profit]"
    assert expr_is_aggregated("sum([T::A])")
    assert fix_double_aggregation(
        "sum([formula_X])", {"X": "sum([T::A])"}) == "[formula_X]"
    cols, formulas, renames = resolve_name_collisions(
        [{"name": "Profit"}], [{"name": "Profit"}], [])
    assert cols == [] and renames == {}


def test_old_paths_are_same_objects():
    import ts_cli.formula_common as fc
    import ts_cli.model_builder as mb
    from ts_cli.tableau import naming
    assert mb.add_formula_prefix is fc.add_formula_prefix
    assert mb.expr_is_aggregated is fc.expr_is_aggregated
    assert mb.fix_double_aggregation is fc.fix_double_aggregation
    assert mb.resolve_name_collisions is fc.resolve_name_collisions
    assert naming.resolve_name_collisions is fc.resolve_name_collisions
