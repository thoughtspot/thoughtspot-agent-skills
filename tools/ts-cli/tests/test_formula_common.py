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


def test_untranslatable_error_is_single_canonical_class():
    """Locks in the hoist: mv_sql.py (from-direction) and mv_emit_expr.py
    (to-direction) both re-export ts_cli.formula_common.UntranslatableError
    rather than defining their own class. Cross-direction `except
    UntranslatableError` handling only works if all three names refer to the
    same class object — this guards against that ever silently diverging
    again."""
    from ts_cli.formula_common import UntranslatableError as fc_err
    from ts_cli.databricks.mv_sql import UntranslatableError as sql_err
    from ts_cli.databricks.mv_emit_expr import UntranslatableError as expr_err
    assert fc_err is sql_err is expr_err

    # Cross-direction catchability: an error raised via one module's import
    # path must be catchable via another module's import path.
    try:
        raise expr_err("x")
    except sql_err:
        pass
    else:
        raise AssertionError("cross-direction except did not catch")
