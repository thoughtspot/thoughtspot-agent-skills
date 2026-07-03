"""Unit tests for ts_cli.tableau.build_model — pure helpers behind ts tableau build-model.

These are characterization tests: they pin the behavior of logic extracted
verbatim from build_model_cmd (commands/tableau.py) during the BL-069
follow-up decomposition. If one fails, the extraction changed behavior —
fix the extraction, not the test.
"""
from ts_cli.tableau.build_model import (
    apply_prefix_and_double_agg,
    collect_existing_model_context,
    extract_imported_guid,
    fix_sqlproxy_scoping,
    parse_import_error,
    prepare_formulas_for_merge,
    remove_formula,
    strip_csq_suffixes,
)


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


# --- apply_prefix_and_double_agg ---

def test_apply_prefix_and_double_agg_mutates_in_place():
    formulas = [
        {"name": "Total", "expr": "sum([Sales])"},
        {"name": "UsesTotal", "expr": "sum([Total])"},
    ]
    apply_prefix_and_double_agg(formulas, {"Total", "UsesTotal"}, set())
    assert formulas[0]["expr"] == "sum([Sales])"
    assert formulas[1]["expr"] == "[formula_Total]"
