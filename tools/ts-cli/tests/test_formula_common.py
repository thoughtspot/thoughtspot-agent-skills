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


# ---------------------------------------------------------------------------
# BL-171 — the shared sql_*_op pass-through / composition scanner
# ---------------------------------------------------------------------------

_T = {"trim": ("sql_string_op", "TRIM({0})", 1),
      "upper": ("sql_string_op", "UPPER({0})", 1),
      "replace": ("sql_string_op", "REPLACE({0}, {1}, {2})", 3)}


def _wrap(text, quote="'"):
    from ts_cli.formula_common import wrap_passthrough_calls
    return wrap_passthrough_calls(text, _T, quote)


def test_wrap_single_arg():
    assert _wrap("trim(Name)") == ("sql_string_op('TRIM({0})', Name)", set())


def test_wrap_three_arg():
    out, unresolved = _wrap("replace(Name, 'a', 'b')")
    assert out == "sql_string_op('REPLACE({0}, {1}, {2})', Name, 'a', 'b')"
    assert unresolved == set()


def test_wrap_nested_resolves_inside_out():
    out, unresolved = _wrap("upper(trim(Name))")
    assert out == ("sql_string_op('UPPER({0})', "
                   "sql_string_op('TRIM({0})', Name))")
    assert unresolved == set()


def test_wrap_double_quote_style():
    assert _wrap("trim(Name)", '"')[0] == 'sql_string_op("TRIM({0})", Name)'


def test_marker_inside_single_quoted_literal_is_not_a_call():
    """The marker SEARCH must skip string literals, not just the paren walk.
    Before the fix this produced nested-quote corruption
    (`'sql_string_op('UPPER({0})', x)'`) and reported nothing unresolved, so
    the caller shipped it as a successful translation."""
    out, unresolved = _wrap("replace(Name, 'upper(x)', 'y')")
    assert out == "sql_string_op('REPLACE({0}, {1}, {2})', Name, 'upper(x)', 'y')"
    assert unresolved == set()


def test_marker_inside_double_quoted_literal_is_not_a_call():
    out, unresolved = _wrap('concat(a, "trim(x)")')
    assert out == 'concat(a, "trim(x)")'
    assert unresolved == set()


def test_emitted_template_is_not_re_read_as_a_call():
    """The emitted `'TRIM({0})'` template sits inside quotes, so a re-scan of
    the replacement must not treat it as a `trim` call."""
    out, _ = _wrap("trim(trim(Name))")
    assert out.count("sql_string_op") == 2
    assert "trim(" not in out


def test_wrong_arity_is_reported_unresolved_and_left_untouched():
    out, unresolved = _wrap("replace(Name, 'a')")
    assert out == "replace(Name, 'a')"
    assert unresolved == {"replace"}


def test_unbalanced_parens_report_unresolved():
    out, unresolved = _wrap("trim(Name")
    assert out == "trim(Name"
    assert unresolved == {"trim"}


def test_unbalanced_parens_still_report_later_markers():
    """The bail-out used to `break` after flagging only the offending marker,
    leaving any other bare marker in the text unreported — and therefore
    emitted with review=False."""
    _out, unresolved = _wrap("trim(Name , upper(x)")
    assert unresolved == {"trim", "upper"}


def test_guard_exhaustion_reports_every_surviving_marker():
    """More markers than the loop guard allows: whatever is left callable must
    still be reported, never silently emitted."""
    out, unresolved = _wrap(" + ".join(f"trim(C{i})" for i in range(300)))
    assert "trim(" in out           # some survived the guard
    assert unresolved == {"trim"}


def test_composition_handler_receives_split_args():
    from ts_cli.formula_common import rewrite_marker_calls
    out, unresolved = rewrite_marker_calls(
        "mid(Name, 2, 3)",
        {"mid": lambda a: f"substr({a[0]}, {a[1]} - 1, {a[2]})"
         if len(a) == 3 else None})
    assert out == "substr(Name, 2 - 1, 3)"
    assert unresolved == set()


def test_composition_handler_returning_none_is_unresolved():
    from ts_cli.formula_common import rewrite_marker_calls
    out, unresolved = rewrite_marker_calls(
        "mid(Name, 2)", {"mid": lambda a: None})
    assert out == "mid(Name, 2)"
    assert unresolved == {"mid"}


def test_empty_handler_map_is_a_no_op():
    from ts_cli.formula_common import rewrite_marker_calls
    assert rewrite_marker_calls("trim(x)", {}) == ("trim(x)", set())


class TestPassThroughQuotingIsUniform:
    """Finding 17.2 — every emitter must use the same outer-template quoting.

    BL-171 routed the six non-existent string functions through `sql_string_op` in five
    emitters. Four passed `quote='"'`, matching every example in
    thoughtspot-formula-patterns.md; **Qlik omitted the argument** and silently took
    formula_common's single-quote default, so one converter emitted a form no schema
    example uses and nothing compared them. This is the comparison.
    """

    @staticmethod
    def _emitted():
        """`{converter: emitted_passthrough}` for the same logical input."""
        from ts_cli.qlik.functions import translate as qlik_translate
        out = {"qlik": qlik_translate("Upper(Name)")[0]}
        from ts_cli.formula_common import wrap_passthrough_calls
        from ts_cli.powerbi import functions as pbi
        expr, _ = wrap_passthrough_calls("upper(Name)", pbi._PASSTHROUGH, quote='"')
        out["powerbi"] = expr
        return out

    def test_no_emitter_uses_a_single_quoted_outer_template(self):
        for name, emitted in self._emitted().items():
            assert "sql_string_op('" not in emitted, (
                f"{name} emits a single-quoted outer template; the authoritative schema "
                f"(thoughtspot-formula-patterns.md § SQL Pass-Through) double-quotes it, "
                f"and only the double-quoted form has a verification record"
            )

    def test_all_emitters_agree(self):
        quoting = {n: ('"' if 'sql_string_op("' in e else "'") for n, e in self._emitted().items()}
        assert len(set(quoting.values())) == 1, f"emitters disagree: {quoting}"

    def test_sv_and_mv_pass_through_double_quote_too(self):
        """D09/D10 cited these as precedent for SINGLE quotes; they use double."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "ts_cli"
        for rel in ("sv_sql.py", "databricks/mv_sql.py"):
            text = (root / rel).read_text(encoding="utf-8")
            assert 'sql_string_op ( \\"' in text or 'sql_string_op ( "' in text, rel


# --- distinct counts as formulas (invariant I5, BL-447) ---------------------------

def test_aggregate_formula_is_the_one_spelling():
    from ts_cli.formula_common import aggregate_formula, unique_count_formula
    assert aggregate_formula("COUNT_DISTINCT", "[T::c]") == "unique count ( [T::c] )"
    assert aggregate_formula("std_deviation", "[T::c]") == "stddev ( [T::c] )"
    assert aggregate_formula("NONE", "[T::c]") is None
    assert unique_count_formula("[T::a] + 1") == "unique count ( [T::a] + 1 )"


def test_distinct_count_formula_column_keeps_name_and_metadata():
    from ts_cli.formula_common import distinct_count_formula_column
    f, col = distinct_count_formula_column(
        "Customers", "SALES::CUST", "formula_Customers",
        properties={"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT",
                    "synonyms": ["buyers"]},
        description="Distinct customers")
    assert f == {"id": "formula_Customers", "name": "Customers",
                 "expr": "unique count ( [SALES::CUST] )"}
    assert col == {"name": "Customers", "formula_id": "formula_Customers",
                   "description": "Distinct customers",
                   "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                                  "synonyms": ["buyers"], "index_type": "DONT_INDEX"}}


def test_reselect_counted_columns_only_for_a_table_left_unselected():
    from ts_cli.formula_common import reselect_counted_columns
    formulas = [{"id": "f1", "expr": "unique count ( [BRIDGE::KEY] )"},
                {"id": "f2", "expr": "unique count ( [SALES::CUST] )"},
                {"id": "f3", "expr": "unique count ( [OTHER::KEY] + 1 )"}]
    columns = [{"name": "KEY", "formula_id": "f1"},
               {"name": "Customers", "formula_id": "f2"},
               {"name": "Amount", "column_id": "SALES::AMOUNT"},
               {"name": "Expr", "formula_id": "f3"}]
    added = reselect_counted_columns(columns, formulas)
    # BRIDGE had no column_id entry left; its count's display name is taken, so the
    # column is disambiguated by its table. SALES still has AMOUNT; f3 counts an
    # expression, not a column, so nothing is guessed for OTHER.
    assert added == ["KEY (BRIDGE)"]
    assert columns[-1] == {"name": "KEY (BRIDGE)", "column_id": "BRIDGE::KEY",
                           "properties": {"column_type": "ATTRIBUTE"}}
    assert reselect_counted_columns(columns, formulas) == []      # idempotent


def test_unique_count_can_count_null_as_a_value():
    # BL-540, live 2026-11-08: unique count -> count(DISTINCT k) ignores NULL (3 on
    # a,a,b,NULL,NULL,c); this form returned 4, as DAX DISTINCTCOUNT does.
    from ts_cli.formula_common import unique_count_formula
    form = unique_count_formula("[T::k]", null_is_a_value=True)
    assert form == (
        "( unique count ( [T::k] ) + max ( if ( isnull ( [T::k] ) ) then 1 else 0 ) )")
    # Bracketed, so it composes: as a divisor, `x / form` divides by the whole count,
    # never `x / unique count ( … )` plus the has-NULL term (review, BL-540).
    assert form.startswith("( ") and form.endswith(" )")


def test_reselect_matches_the_null_counting_form_too():
    from ts_cli.formula_common import distinct_count_formula_column, reselect_counted_columns
    f, col = distinct_count_formula_column("K", "BRIDGE::K", "formula_K", null_is_a_value=True)
    columns = [col]
    assert reselect_counted_columns(columns, [f]) == ["K (BRIDGE)"]
    # A formula that merely starts like one is not a count of the column.
    g = {"id": "g", "expr": "unique count ( [OTHER::K] ) + 1"}
    assert reselect_counted_columns([{"name": "G", "formula_id": "g"}], [g]) == []
