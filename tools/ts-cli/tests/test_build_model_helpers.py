"""Unit tests for ts_cli.tableau.build_model — pure helpers behind ts tableau build-model.

These are characterization tests: they pin the behavior of logic extracted
verbatim from build_model_cmd (commands/tableau.py) during the BL-069
follow-up decomposition. If one fails, the extraction changed behavior —
fix the extraction, not the test.
"""
from ts_cli.model_builder import build_model_tml, filter_unresolvable_formulas
from ts_cli.tableau.build_model import (
    apply_prefix_and_double_agg,
    apply_table_name_map,
    build_generated_tables_map,
    collect_existing_model_context,
    extract_imported_guid,
    fix_sqlproxy_scoping,
    parse_import_error,
    prepare_formulas_for_merge,
    remove_formula,
    strip_csq_suffixes,
)
from ts_cli.tableau.reconcile import rewrite_formula_refs
from ts_cli.tml_lint import lint_cross_references


def _model_tml(tables=("SALES",), columns=(), formulas=(), parameters=()):
    return {
        "model": {
            "model_tables": [{"name": t} for t in tables],
            "columns": list(columns),
            "formulas": list(formulas),
            "parameters": list(parameters),
        }
    }


# --- fix_sqlproxy_scoping ---

def test_sqlproxy_scoping_passthrough_when_no_sqlproxy():
    scoped = {"Amount": "SALES"}
    fixed, msg = fix_sqlproxy_scoping(scoped, _model_tml())
    assert fixed == {"Amount": "SALES"}
    assert msg == ""


def test_sqlproxy_scoping_single_table_forces_all_columns():
    scoped = {"Revenue (Custom SQL Query)": "sqlproxy", "Qty": "sqlproxy"}
    tml = _model_tml(
        tables=("SALES",),
        columns=[{"name": "Amount", "column_id": "SALES::AMOUNT"}],
    )
    fixed, msg = fix_sqlproxy_scoping(scoped, tml)
    # every original key forced to the single table
    assert fixed["Revenue (Custom SQL Query)"] == "SALES"
    assert fixed["Qty"] == "SALES"
    # CSQ-suffixed key also gets a base-name alias
    assert fixed["Revenue"] == "SALES"
    # existing model column backfilled
    assert fixed["AMOUNT"] == "SALES"
    assert "Single-table model" in msg


def test_sqlproxy_scoping_multi_table_remaps_via_column_id():
    scoped = {"Amount": "sqlproxy", "Region": "DIM_GEO"}
    tml = _model_tml(
        tables=("SALES", "DIM_GEO"),
        columns=[
            {"name": "Amount", "column_id": "SALES::AMOUNT"},
            {"name": "Region", "column_id": "DIM_GEO::REGION"},
        ],
    )
    fixed, msg = fix_sqlproxy_scoping(scoped, tml)
    assert fixed["Amount"] == "SALES"        # sqlproxy → actual table
    assert fixed["Region"] == "DIM_GEO"      # non-sqlproxy untouched
    assert "Remapped" in msg


def test_sqlproxy_scoping_multi_table_unknown_column_keeps_sqlproxy():
    scoped = {"Mystery": "sqlproxy"}
    tml = _model_tml(
        tables=("SALES", "DIM_GEO"),
        columns=[{"name": "Amount", "column_id": "SALES::AMOUNT"}],
    )
    fixed, _ = fix_sqlproxy_scoping(scoped, tml)
    assert fixed["Mystery"] == "sqlproxy"    # no match — left as-is
    assert fixed["AMOUNT"] == "SALES"        # model columns backfilled


# --- strip_csq_suffixes ---

def test_strip_csq_suffixes_rewrites_in_place_and_counts():
    formulas = [
        {"name": "A", "expr": "[Revenue (Custom SQL Query2)] + [X]"},
        {"name": "B", "expr": "[X] * 2"},
    ]
    changed = strip_csq_suffixes(formulas)
    assert formulas[0]["expr"] == "[Revenue] + [X]"
    assert formulas[1]["expr"] == "[X] * 2"
    assert changed == 1


# --- apply_table_name_map (BL-085 part 1: --table-name-map) ---

def _ds(tables, joins=(), columns=(), col_table_map=None):
    return {
        "name": "DS",
        "tables": list(tables),
        "joins": list(joins),
        "columns": list(columns),
        "calculated_fields": [],
        "calc_map": {},
        "col_table_map": col_table_map or {},
    }


def test_table_name_map_noop_when_map_empty():
    ds = _ds(tables=[{"name": "foo", "db_table": "raw.foo"}])
    scoped = {"COL1": "foo"}
    new_ds, new_scoped = apply_table_name_map(ds, scoped, {})
    assert new_ds is ds
    assert new_scoped is scoped


def test_table_name_map_renames_table_name_and_db_table():
    ds = _ds(tables=[{"name": "foo", "db_table": "raw.foo"}])
    new_ds, _ = apply_table_name_map(ds, {}, {"foo": "FOO_TS"})
    assert new_ds["tables"][0]["name"] == "FOO_TS"
    assert new_ds["tables"][0]["db_table"] == "FOO_TS"
    # original untouched (pure function, no mutation)
    assert ds["tables"][0]["name"] == "foo"


def test_table_name_map_leaves_unmapped_table_unchanged():
    ds = _ds(tables=[
        {"name": "foo", "db_table": "raw.foo"},
        {"name": "bar", "db_table": "raw.bar"},
    ])
    new_ds, _ = apply_table_name_map(ds, {}, {"foo": "FOO_TS"})
    assert new_ds["tables"][0]["name"] == "FOO_TS"
    assert new_ds["tables"][1]["name"] == "bar"
    assert new_ds["tables"][1]["db_table"] == "raw.bar"


def test_table_name_map_renames_join_endpoints():
    ds = _ds(
        tables=[{"name": "foo", "db_table": "foo"}, {"name": "bar", "db_table": "bar"}],
        joins=[{"type": "INNER", "left_table": "foo", "right_table": "bar",
                 "keys": [{"left": "ID", "right": "FOO_ID"}]}],
    )
    new_ds, _ = apply_table_name_map(ds, {}, {"foo": "FOO_TS"})
    assert new_ds["joins"][0]["left_table"] == "FOO_TS"
    assert new_ds["joins"][0]["right_table"] == "bar"  # unmapped side untouched


def test_table_name_map_remaps_scoped_columns_values():
    ds = _ds(tables=[{"name": "foo", "db_table": "foo"}])
    scoped = {"COL1": "foo", "COL2": "bar"}
    _, new_scoped = apply_table_name_map(ds, scoped, {"foo": "FOO_TS"})
    assert new_scoped["COL1"] == "FOO_TS"
    assert new_scoped["COL2"] == "bar"  # unmapped table untouched


def test_table_name_map_remaps_column_table_key_when_present():
    ds = _ds(
        tables=[{"name": "foo", "db_table": "foo"}],
        columns=[{"name": "Sales", "db_column_name": "SALES", "table": "foo"}],
    )
    new_ds, _ = apply_table_name_map(ds, {}, {"foo": "FOO_TS"})
    assert new_ds["columns"][0]["table"] == "FOO_TS"


def test_table_name_map_column_without_table_key_untouched():
    ds = _ds(
        tables=[{"name": "foo", "db_table": "foo"}],
        columns=[{"name": "Sales", "db_column_name": "SALES"}],
    )
    new_ds, _ = apply_table_name_map(ds, {}, {"foo": "FOO_TS"})
    assert "table" not in new_ds["columns"][0]


def test_table_name_map_feeds_build_model_tml_end_to_end():
    """The mapped name must show up in model_tables, fqn, column_id, and joins."""
    ds = _ds(
        tables=[
            {"name": "foo", "db_table": "foo"},
            {"name": "bar", "db_table": "bar"},
        ],
        joins=[{"type": "INNER", "left_table": "foo", "right_table": "bar",
                 "keys": [{"left": "BAR_ID", "right": "ID"}]}],
        columns=[
            {"name": "Sales", "db_column_name": "SALES", "column_type": "MEASURE",
             "data_type": "DOUBLE", "table": "foo"},
            {"name": "Region", "db_column_name": "REGION", "column_type": "ATTRIBUTE",
             "data_type": "VARCHAR", "table": "bar"},
        ],
    )
    new_ds, _ = apply_table_name_map(ds, {}, {"foo": "FOO_TS"})

    model = build_model_tml(
        model_name="Test",
        connection_name="CONN",
        tables=new_ds["tables"],
        columns=new_ds["columns"],
        joins=new_ds["joins"],
        parameters=[],
        translated_formulas=[],
    )

    table_names = {t["name"] for t in model["model"]["tables"]}
    assert table_names == {"FOO_TS", "bar"}

    foo_table = next(t for t in model["model"]["tables"] if t["name"] == "FOO_TS")
    assert foo_table["fqn"] == "[CONN].[FOO_TS]"

    sales_col = next(c for c in model["model"]["columns"] if c["name"] == "Sales")
    assert sales_col["column_id"] == "FOO_TS::SALES"

    foo_model_table = next(t for t in model["model"]["model_tables"] if t["name"] == "FOO_TS")
    assert foo_model_table["joins"][0]["with"] == "bar"
    assert "FOO_TS::BAR_ID" in foo_model_table["joins"][0]["on"]


def test_without_table_name_map_build_model_tml_output_unchanged():
    """Golden/no-op: generate-flow output with no map matches pre-existing behavior."""
    ds = _ds(
        tables=[{"name": "foo", "db_table": "raw.foo"}],
        joins=[],
        columns=[
            {"name": "Sales", "db_column_name": "SALES", "column_type": "MEASURE",
             "data_type": "DOUBLE", "table": "foo"},
        ],
    )
    scoped = {"Sales": "foo"}

    # No map supplied — build_model_cmd never calls apply_table_name_map at all,
    # so calling it explicitly with {} must reproduce identical output.
    mapped_ds, mapped_scoped = apply_table_name_map(ds, scoped, {})
    assert mapped_ds is ds
    assert mapped_scoped is scoped

    model_from_noop = build_model_tml(
        model_name="Test",
        connection_name="CONN",
        tables=mapped_ds["tables"],
        columns=mapped_ds["columns"],
        joins=mapped_ds["joins"],
        parameters=[],
        translated_formulas=[],
    )
    model_baseline = build_model_tml(
        model_name="Test",
        connection_name="CONN",
        tables=ds["tables"],
        columns=ds["columns"],
        joins=ds["joins"],
        parameters=[],
        translated_formulas=[],
    )
    assert model_from_noop == model_baseline


# --- collect_existing_model_context ---

def test_collect_context_extracts_sets_and_primary_table():
    tml = _model_tml(
        tables=("SALES", "DIM_GEO"),
        columns=[
            {"name": "Amount", "column_id": "SALES::AMOUNT"},
            {"name": "Derived", "formula_id": "formula_Derived"},
        ],
        formulas=[{"id": "formula_Margin", "name": "Margin", "expr": "sum([X])"}],
        parameters=[{"name": "Price Param"}],
    )
    ctx = collect_existing_model_context(tml)
    assert ctx["existing_ids"] == {"formula_Margin"}
    assert ctx["existing_cols"] == {"AMOUNT"}
    assert ctx["formula_names"] == {"Margin"}
    assert ctx["param_names"] == {"Price Param"}
    assert ctx["primary_table"] == "SALES"
    assert ctx["col_lookup"]["AMOUNT"] == "AMOUNT"


def test_collect_context_no_tables_gives_none_primary():
    ctx = collect_existing_model_context(_model_tml(tables=()))
    assert ctx["primary_table"] is None


# --- prepare_formulas_for_merge ---

def test_prepare_formulas_prefixes_and_shapes_dicts():
    # tables=() → primary_table None → the fix_bare_refs pass is skipped, so
    # this test pins add_formula_prefix behavior in isolation
    tml = _model_tml(
        tables=(),
        formulas=[{"id": "formula_Margin", "name": "Margin", "expr": "sum([X])"}],
    )
    ctx = collect_existing_model_context(tml)
    cleaned = [{"name": "New Calc", "expr": "[Margin] * 2"}]
    dicts, bare_fixed = prepare_formulas_for_merge(cleaned, ctx)
    assert dicts == [
        {"expr": "[formula_Margin] * 2", "id": "formula_New Calc", "name": "New Calc"}
    ]
    assert bare_fixed == 0


def test_prepare_formulas_collapses_double_aggregation():
    ctx = collect_existing_model_context(_model_tml(tables=()))
    cleaned = [
        {"name": "Total", "expr": "sum([Sales])"},
        {"name": "UsesTotal", "expr": "sum([Total])"},
    ]
    dicts, _ = prepare_formulas_for_merge(cleaned, ctx)
    by_name = {d["name"]: d["expr"] for d in dicts}
    # sum() around an already-aggregated formula ref is stripped
    assert by_name["UsesTotal"] == "[formula_Total]"


def test_prepare_formulas_fixes_bare_refs_and_counts():
    tml = _model_tml(
        tables=("SALES",),
        columns=[{"name": "Amount", "column_id": "SALES::AMOUNT"}],
    )
    ctx = collect_existing_model_context(tml)
    cleaned = [{"name": "Calc", "expr": "[Amount] + 1"}]
    dicts, bare_fixed = prepare_formulas_for_merge(cleaned, ctx)
    assert bare_fixed == 1
    assert dicts[0]["expr"] == "[SALES::AMOUNT] + 1"


def test_prepare_formulas_strips_csq_suffixes_first():
    ctx = collect_existing_model_context(_model_tml(tables=()))
    cleaned = [{"name": "Calc", "expr": "[Revenue (Custom SQL Query)] * 1"}]
    dicts, _ = prepare_formulas_for_merge(cleaned, ctx)
    assert "(Custom SQL Query)" not in dicts[0]["expr"]


# --- parse_import_error ---

def test_parse_import_error_extracts_name_and_detail():
    msg = "Model create failed. Formula: Profit Margin, Error: Invalid token near ')'"
    assert parse_import_error(msg) == ("Profit Margin", "Invalid token near ')'")


def test_parse_import_error_unmatched_returns_none():
    assert parse_import_error("Something else went wrong") is None


def test_parse_import_error_truncates_detail_to_120():
    msg = "Formula: X, Error: " + "e" * 300
    _, detail = parse_import_error(msg)
    assert len(detail) == 120


# --- remove_formula ---

def test_remove_formula_drops_formula_and_its_columns():
    merged = _model_tml(
        columns=[
            {"name": "Bad", "formula_id": "formula_Bad"},
            {"name": "Amount", "column_id": "SALES::AMOUNT"},
        ],
        formulas=[
            {"id": "formula_Bad", "name": "Bad"},
            {"id": "formula_Good", "name": "Good"},
        ],
    )
    remove_formula(merged, "Bad")
    assert [f["id"] for f in merged["model"]["formulas"]] == ["formula_Good"]
    assert [c["name"] for c in merged["model"]["columns"]] == ["Amount"]


# --- extract_imported_guid ---

def test_extract_imported_guid_reads_header():
    ir = [{"response": {"object": [{"header": {"id_guid": "abc-123"}}]}}]
    assert extract_imported_guid(ir) == "abc-123"


def test_extract_imported_guid_missing_gives_none():
    assert extract_imported_guid([{"response": {}}]) is None
    assert extract_imported_guid([{"response": {"object": [{"header": {}}]}}]) is None


def test_extract_imported_guid_empty_string_gives_none():
    ir = [{"response": {"object": [{"header": {"id_guid": ""}}]}}]
    assert extract_imported_guid(ir) is None


def test_extract_imported_guid_flat_shape_fallback():
    # Live shape verified BL-063 PR4 (2026-07-10, se-thoughtspot): no `object`
    # wrapper — header (with id_guid) sits directly under `response`.
    ir = [{"response": {"header": {"id_guid": "flat-456", "name": "M",
                                    "metadata_type": "LOGICAL_TABLE"},
                        "status": {"status_code": "OK"}}}]
    assert extract_imported_guid(ir) == "flat-456"


def test_extract_imported_guid_prefers_nested_when_both_present():
    ir = [{"response": {"object": [{"header": {"id_guid": "nested-1"}}],
                        "header": {"id_guid": "flat-1"}}}]
    assert extract_imported_guid(ir) == "nested-1"


def test_extract_imported_guid_neither_shape_gives_none():
    ir = [{"response": {"status": {"status_code": "OK"}}}]
    assert extract_imported_guid(ir) is None


def test_extract_imported_guid_empty_list_gives_none():
    assert extract_imported_guid([]) is None


# --- apply_prefix_and_double_agg ---

def test_apply_prefix_and_double_agg_mutates_in_place():
    formulas = [
        {"name": "Total", "expr": "sum([Sales])"},
        {"name": "UsesTotal", "expr": "sum([Total])"},
    ]
    apply_prefix_and_double_agg(formulas, {"Total", "UsesTotal"}, set())
    assert formulas[0]["expr"] == "sum([Sales])"
    assert formulas[1]["expr"] == "[formula_Total]"


# --- rewrite_formula_refs + prepare_formulas_for_merge + filter_unresolvable_formulas ---

def test_renamed_ref_dropped_without_map_kept_with_map():
    # Existing model has the RENAMED column (DM_ prefix) bound to table `vw`.
    tml = _model_tml(
        tables=("vw",),
        columns=[{"name": "Disc", "column_id": "vw::DM_DISCOUNT_RED_DOLLAR"}],
    )
    ctx = collect_existing_model_context(tml)
    name_map = {"DISCOUNT_RED_DOLLAR": "DM_DISCOUNT_RED_DOLLAR"}
    # Formula re-derived from the TWB still references the SOURCE name.
    source = [{"name": "Total Disc", "expr": "sum ( [DISCOUNT_RED_DOLLAR] )"}]

    # WITHOUT the map: bare [DISCOUNT_RED_DOLLAR] is unknown to the existing
    # model's column lookup, stays bare, and the filter drops it.
    no_map = [dict(f) for f in source]
    dicts0, _ = prepare_formulas_for_merge(no_map, ctx)
    kept0, dropped0 = filter_unresolvable_formulas(
        dicts0, ctx["existing_ids"], ctx["existing_cols"],
        ctx["formula_names"], ctx["param_names"],
    )
    assert [f["name"] for f in kept0] == []
    assert "Total Disc" in dropped0

    # WITH the map: rewrite → [DM_DISCOUNT_RED_DOLLAR] → qualifies to
    # [vw::DM_DISCOUNT_RED_DOLLAR] → survives the filter.
    with_map = [dict(f) for f in source]
    assert rewrite_formula_refs(with_map, name_map) == 1
    dicts1, _ = prepare_formulas_for_merge(with_map, ctx)
    kept1, dropped1 = filter_unresolvable_formulas(
        dicts1, ctx["existing_ids"], ctx["existing_cols"],
        ctx["formula_names"], ctx["param_names"],
    )
    assert [f["name"] for f in kept1] == ["Total Disc"]
    assert dropped1 == []


# --- build_generated_tables_map + lint_cross_references wiring ---------------
# (BL-cross-ref-check: pre-flight dangling cross-reference check for
# `ts tableau build-model`'s GENERATE flow — see commands/tableau.py _generate_flow)

def test_build_generated_tables_map_single_table():
    tables = [{"name": "ORDERS"}]
    columns = [
        {"name": "Amount", "db_column_name": "AMOUNT"},
        {"name": "Order Id", "db_column_name": "ORDER_ID"},
    ]
    result = build_generated_tables_map(tables, columns)
    assert result == {"ORDERS": {"AMOUNT", "ORDER_ID"}}


def test_build_generated_tables_map_multi_table_uses_table_key():
    tables = [{"name": "ORDERS"}, {"name": "CUSTOMERS"}]
    columns = [
        {"name": "Amount", "db_column_name": "AMOUNT", "table": "ORDERS"},
        {"name": "Cust Name", "db_column_name": "NAME", "table": "CUSTOMERS"},
    ]
    result = build_generated_tables_map(tables, columns)
    assert result == {"ORDERS": {"AMOUNT"}, "CUSTOMERS": {"NAME"}}


def test_build_generated_tables_map_falls_back_to_name_without_db_column_name():
    tables = [{"name": "ORDERS"}]
    columns = [{"name": "Amount"}]
    result = build_generated_tables_map(tables, columns)
    assert result == {"ORDERS": {"Amount"}}


def test_build_generated_tables_map_includes_sql_view_columns():
    tables = [{"name": "ORDERS"}]
    columns = [{"name": "Amount", "db_column_name": "AMOUNT"}]
    sql_views = [{"name": "MyCustomSQL", "columns": [{"name": "Total"}, {"name": "Region"}]}]
    result = build_generated_tables_map(tables, columns, sql_views)
    assert result["ORDERS"] == {"AMOUNT"}
    assert result["MyCustomSQL"] == {"Total", "Region"}


def test_build_generated_tables_map_end_to_end_with_lint_cross_references_clean():
    # Mirrors _generate_flow: assemble a model_tml via build_model_tml, then
    # verify the SAME inputs, run through build_generated_tables_map, produce
    # a clean lint_cross_references result (the happy-path pre-flight check).
    tables = [{"name": "ORDERS"}, {"name": "CUSTOMERS"}]
    columns = [
        {"name": "Amount", "db_column_name": "AMOUNT", "table": "ORDERS"},
        {"name": "Order Customer Id", "db_column_name": "CUSTOMER_ID", "table": "ORDERS"},
        {"name": "Customer Id", "db_column_name": "CUSTOMER_ID", "table": "CUSTOMERS"},
        {"name": "Customer Name", "db_column_name": "NAME", "table": "CUSTOMERS"},
    ]
    joins = [{
        "left_table": "ORDERS", "right_table": "CUSTOMERS",
        "keys": [{"left": "CUSTOMER_ID", "right": "CUSTOMER_ID"}],
    }]
    model_tml = build_model_tml(
        model_name="Sales",
        connection_name="my_conn",
        tables=tables,
        columns=columns,
        joins=joins,
        parameters=[],
        translated_formulas=[],
    )
    generated_tables = build_generated_tables_map(tables, columns)
    assert lint_cross_references(model_tml, generated_tables) == []


def test_build_generated_tables_map_end_to_end_catches_dropped_column():
    # A formula-free physical column that never made it into `columns` (e.g. a
    # bug that drops a column during reconciliation) leaves a column_id in the
    # assembled model TML with no matching entry in the generated-tables map —
    # exactly the class of bug this pre-flight check exists to catch.
    tables = [{"name": "ORDERS"}]
    columns = [{"name": "Amount", "db_column_name": "AMOUNT", "column_id": "ORDERS::AMOUNT"}]
    model_tml = build_model_tml(
        model_name="Sales",
        connection_name="my_conn",
        tables=tables,
        columns=columns,
        joins=[],
        parameters=[],
        translated_formulas=[],
    )
    # Simulate the bug: the generated-tables map was built from a columns list
    # that's missing "Amount" (as if it were silently dropped before this point).
    generated_tables = build_generated_tables_map(tables, [])
    findings = lint_cross_references(model_tml, generated_tables)
    assert any("AMOUNT" in f and "ORDERS" in f for f in findings)
