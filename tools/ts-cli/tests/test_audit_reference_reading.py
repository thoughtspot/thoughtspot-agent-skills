"""BL-504: every audit reader of `[...]` references reads them one way.

The report's formula tree skipped string literals, kept a reference whole when its name
holds a quote (BL-369), stripped whitespace, dropped self-references and resolved a
formula by its surfacing column's display name. P17 and P2 (`_reference_graph`) and H3
(`@referenced_by_formula`) read bracket text inside a literal as a reference and did not
strip names; H3 counted a formula's reference to itself; P17 did not resolve a display
name; the RLS and join on-clause readers did not skip literals either. Now all of them
read through `tml.expr_refs` and the tree's index, `tml.formula_reference_index`.
"""
from __future__ import annotations

from ts_cli.audit.context import join_key_ids, make_context
from ts_cli.audit.engine import fields, scopes, tml
from ts_cli.audit.formula_tree import formula_tree


def test_expr_refs_skips_literals_strips_and_keeps_a_quoted_name_whole():
    assert tml.expr_refs("concat ( '[A::x]' , [B::y] )") == ["B::y"]
    assert tml.expr_refs('if ( [A::x] = "[C::z]" ) then 1 else 0') == ["A::x"]
    assert tml.expr_refs("[Bob's Sales::x] + [ T::y ]") == ["Bob's Sales::x", "T::y"]
    assert tml.expr_refs("[ ] + 1") == []
    assert tml.expr_refs(None) == [] and tml.expr_refs(3) == []


def _model(formulas, columns=()):
    return {"guid": "m-1", "model": {"name": "M", "formulas": list(formulas),
                                    "columns": list(columns), "model_tables": []}}


def _formula_items(model):
    ctx = make_context(models=[model])
    return ctx, {i["obj"]["name"]: i for i in scopes.iterate(ctx, "model.formula")}


def test_p17_ignores_a_reference_inside_a_literal_and_resolves_a_display_name():
    f = [{"id": "formula_A", "name": "A", "expr": "concat ( '[formula_B]' , [B Shown] )"},
         {"id": "formula_B", "name": "B", "expr": "[formula_C] + 1"},
         {"id": "formula_C", "name": "C", "expr": "[T::x]"}]
    cols = [{"name": "B Shown", "formula_id": "formula_B"}]
    ctx, items = _formula_items(_model(f, cols))
    # A -> B through the display name only (the literal's [formula_B] is text), B -> C
    assert fields.get(items["A"], "@reference_chain_depth", ctx) == 2
    f[0]["expr"] = "concat ( '[formula_B]' , 'x' )"
    ctx, items = _formula_items(_model(f, cols))
    assert fields.get(items["A"], "@reference_chain_depth", ctx) is None


def test_p2_does_not_inherit_an_aggregate_named_inside_a_literal():
    f = [{"id": "formula_Agg", "name": "Agg", "expr": "sum ( [T::x] )"},
         {"id": "formula_Row", "name": "Row", "expr": "concat ( '[formula_Agg]' , [T::y] )"},
         {"id": "formula_Uses", "name": "Uses", "expr": "[ formula_Agg ] * 2"}]
    ctx, items = _formula_items(_model(f))
    assert fields.get(items["Row"], "@is_row_level_formula", ctx) is True
    assert fields.get(items["Uses"], "@is_row_level_formula", ctx) is False  # stripped


def _columns(model):
    ctx = make_context(models=[model])
    return ctx, {i["obj"]["name"]: i for i in scopes.iterate(ctx, "model.column")}


def test_h3_reads_references_as_the_tree_does():
    f = [{"id": "formula_Self", "name": "Self", "expr": "[formula_Self] + [ T::SPACED ]"},
         {"id": "formula_Lit", "name": "Lit", "expr": "concat ( '[T::QUOTED]' , 'x' )"},
         {"id": "formula_Used", "name": "Used", "expr": "[T::X]"},
         {"id": "formula_User", "name": "User", "expr": "[Used Shown] + 1"}]
    cols = [{"name": "Self", "formula_id": "formula_Self"},
            {"name": "Lit", "formula_id": "formula_Lit"},
            {"name": "Used Shown", "formula_id": "formula_Used"},
            {"name": "User", "formula_id": "formula_User"},
            {"name": "Quoted", "column_id": "T::QUOTED"},
            {"name": "Spaced", "column_id": "T::SPACED"},
            {"name": "X", "column_id": "T::X"}]
    ctx, items = _columns(_model(f, cols))
    got = {n: fields.get(items[n], "@referenced_by_formula", ctx) for n in items}
    assert got == {"Self": False,          # only its own formula names it
                   "Lit": False, "User": False,
                   "Used Shown": True,     # by its display name
                   "Quoted": False,        # only inside a literal
                   "Spaced": True,         # `[ T::SPACED ]`, stripped
                   "X": True}


def test_the_tree_and_the_rules_share_one_index():
    f = [{"id": "formula_A", "name": "A", "expr": "[B Shown] + '[formula_C]'"},
         {"id": "formula_B", "name": "B", "expr": "1"},
         {"id": "formula_C", "name": "C", "expr": "2"}]
    cols = [{"name": "B Shown", "formula_id": "formula_B"}]
    tree = formula_tree(_model(f, cols)["model"])
    (a,) = [n for n in tree["nodes"] if n["name"] == "A"]
    assert a["uses"] == [{"formula": "B"}]
    index = tml.formula_reference_index(f, cols)
    assert index["B Shown"] == "B" and index["formula_C"] == "C"


def test_rls_and_join_readers_skip_literals():
    table = {"table": {"name": "T", "columns": [
        {"name": "C", "db_column_properties": {"data_type": "VARCHAR"}},
        {"name": "D", "db_column_properties": {"data_type": "VARCHAR"}}],
        "rls_rules": {"rules": [{"name": "r", "expr": "[T::C] = '[T::D]'"}]}}}
    assert [col for _, col, _, _ in tml.rls_column_refs(table)] == ["C"]
    assert join_key_ids("[A::x] = [ B::y ]") == ["A::x", "B::y"]
    assert join_key_ids("[A::x] = '[B::y]'") == ["A::x"]


# ── BL-507: a referencing join's keys on an aliased table ───────────────────

def _aliased_join_ctx(date_key_type="VARCHAR", alias="Order Date"):
    """FACT joins the DATE Table under an alias; the join is referencing, so its `on`
    lives in FACT's Table TML and names the physical Tables."""
    date_mt = {"name": "DATE", "fqn": "t-date"}
    if alias:
        date_mt["alias"] = alias
    model = {"guid": "m-1", "model": {"name": "M", "columns": [], "model_tables": [
        {"name": "FACT", "fqn": "t-fact", "joins": [
            {"with": alias or "DATE", "referencing_join": "fact_date"}]},
        date_mt]}}
    tables = {
        "t-fact": {"guid": "t-fact", "table": {"name": "FACT", "columns": [
            {"name": "DATE_KEY", "db_column_properties": {"data_type": "VARCHAR"}}],
            "joins_with": [{"name": "fact_date", "destination": {"name": "DATE"},
                            "on": "[FACT::DATE_KEY] = [DATE::KEY]"}]}},
        "t-date": {"guid": "t-date", "table": {"name": "DATE", "columns": [
            {"name": "KEY", "db_column_properties": {"data_type": date_key_type}}]}}}
    ctx = make_context(models=[model], tables=tables)
    (join,) = scopes.iterate(ctx, "join")
    return ctx, join


def test_p6_types_the_key_of_an_aliased_table():
    ctx, join = _aliased_join_ctx()
    assert list(fields.get(join, "@varchar_join_keys", ctx)) == ["FACT::DATE_KEY", "DATE::KEY"]
    ctx, join = _aliased_join_ctx(alias=None)          # unaliased: as before
    assert list(fields.get(join, "@varchar_join_keys", ctx)) == ["FACT::DATE_KEY", "DATE::KEY"]


def test_d16_compares_the_key_of_an_aliased_table():
    ctx, join = _aliased_join_ctx(date_key_type="INT64")
    assert list(fields.get(join, "@join_key_type_mismatches", ctx)) == [
        "FACT::DATE_KEY (VARCHAR) = DATE::KEY (INT64)"]


def test_a_physical_name_is_read_for_this_join_only():
    """Two aliases of one Table: each join reads its own end, not the other alias."""
    model = {"guid": "m-1", "model": {"name": "M", "columns": [], "model_tables": [
        {"name": "FACT", "fqn": "t-fact", "joins": [
            {"with": "Order Date", "on": "[FACT::OD] = [Order Date::KEY]",
             "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "DATE", "alias": "Order Date", "fqn": "t-date"},
        {"name": "DATE", "alias": "Ship Date", "fqn": "t-date"}]}}
    tables = {"t-fact": {"table": {"name": "FACT", "columns": [
                  {"name": "OD", "db_column_properties": {"data_type": "INT64"}}]}},
              "t-date": {"table": {"name": "DATE", "columns": [
                  {"name": "KEY", "db_column_properties": {"data_type": "INT64"}}]}}}
    ctx = make_context(models=[model], tables=tables)
    (join,) = scopes.iterate(ctx, "join")
    assert list(fields.get(join, "@join_key_type_mismatches", ctx)) == []
    assert list(fields.get(join, "@varchar_join_keys", ctx)) == []
