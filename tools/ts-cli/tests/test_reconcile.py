# tools/ts-cli/tests/test_reconcile.py
from __future__ import annotations
from ts_cli.tableau.reconcile import clean_column_name, strip_suffix_in_expr, clean_columns


def test_clean_column_name_strips_suffix():
    assert clean_column_name("CUSTOMERS_RED_PERCENT (Custom SQL Query2)") == "CUSTOMERS_RED_PERCENT"
    assert clean_column_name("CAMPAIGN_ID") == "CAMPAIGN_ID"

def test_clean_column_name_drops_junk_and_empty():
    assert clean_column_name("__tableau_internal_object_id__].[_12CAA8") is None
    assert clean_column_name("") is None
    assert clean_column_name(None) is None

def test_strip_suffix_in_expr():
    expr = "sum ( [vw::CUSTOMERS_RED_PERCENT (Custom SQL Query2)] ) / [vw::ORDERS (Custom SQL Query5)]"
    assert strip_suffix_in_expr(expr) == "sum ( [vw::CUSTOMERS_RED_PERCENT] ) / [vw::ORDERS]"

def test_clean_columns_qualifies_dedupes_drops():
    cols = [
        {"name": "CUSTOMER_ID (Custom SQL Query2)", "db_column_name": "CUSTOMER_ID (Custom SQL Query2)", "column_type": "ATTRIBUTE", "data_type": "INT64"},
        {"name": "CUSTOMER_ID", "db_column_name": "CUSTOMER_ID", "column_type": "ATTRIBUTE", "data_type": "INT64"},
        {"name": "__tableau_internal_object_id__].[_9D99", "db_column_name": "__tableau_internal_object_id__].[_9D99", "column_type": "ATTRIBUTE", "data_type": "VARCHAR"},
        {"name": "SALES (Custom SQL Query2)", "db_column_name": "SALES (Custom SQL Query2)", "column_type": "MEASURE", "data_type": "DOUBLE"},
    ]
    out = clean_columns(cols, "vw_dim_promo")
    names = [c["db_column_name"] for c in out]
    assert names == ["CUSTOMER_ID", "SALES"]          # junk dropped, dup collapsed, suffix stripped
    assert all(c["table"] == "vw_dim_promo" for c in out)  # now qualifies
    assert out[0]["name"] == "CUSTOMER_ID"


from ts_cli.tableau.reconcile import suggest_column_mappings, apply_reconciliation

def test_suggest_mappings_dm_prefix_and_no_match():
    target = {"DM_DISCOUNT_RED_DOLLAR", "ORDER_NUM", "SALES", "CAMPAIGN_ID"}
    s = suggest_column_mappings(["DISCOUNT_RED_DOLLAR", "ORDER_ID"], target)
    by = {m["from"]: m["to"] for m in s}
    assert by.get("DISCOUNT_RED_DOLLAR") == "DM_DISCOUNT_RED_DOLLAR"   # DM_ prefix suggested
    assert "ORDER_ID" not in by                                        # ORDER_NUM too weak → no suggestion (drop)

def test_apply_reconciliation_maps_keeps_drops_and_cascades():
    cols = [
        {"name": "CAMPAIGN_ID", "db_column_name": "CAMPAIGN_ID", "table": "vw", "column_type": "ATTRIBUTE"},
        {"name": "DISCOUNT_RED_DOLLAR", "db_column_name": "DISCOUNT_RED_DOLLAR", "table": "vw", "column_type": "MEASURE"},
        {"name": "ORDER_ID", "db_column_name": "ORDER_ID", "table": "vw", "column_type": "ATTRIBUTE"},
    ]
    formulas = [
        {"name": "F_ok", "expr": "sum ( [vw::CAMPAIGN_ID] )", "column_type": "MEASURE"},
        {"name": "F_dropme", "expr": "count ( [vw::ORDER_ID] )", "column_type": "MEASURE"},
    ]
    target = {"CAMPAIGN_ID", "DM_DISCOUNT_RED_DOLLAR"}   # ORDER_ID absent; DISCOUNT_RED_DOLLAR only via map
    kept_cols, kept_formulas, report = apply_reconciliation(
        cols, formulas, target, {"DISCOUNT_RED_DOLLAR": "DM_DISCOUNT_RED_DOLLAR"})
    kept_names = {c["db_column_name"] for c in kept_cols}
    assert kept_names == {"CAMPAIGN_ID", "DM_DISCOUNT_RED_DOLLAR"}     # mapped kept, ORDER_ID dropped
    assert {f["name"] for f in kept_formulas} == {"F_ok"}             # F_dropme cascaded out
    assert "ORDER_ID" in report["columns"]
    assert "F_dropme" in report["formulas"]


def test_apply_reconciliation_rewrites_renamed_refs():
    cols = [
        {"name": "DISCOUNT_RED_DOLLAR", "db_column_name": "DISCOUNT_RED_DOLLAR", "table": "vw", "column_type": "MEASURE"},
    ]
    formulas = [
        {"name": "F_discount", "expr": "sum ( [vw::DISCOUNT_RED_DOLLAR] )", "column_type": "MEASURE"},
    ]
    target = {"DM_DISCOUNT_RED_DOLLAR"}
    kept_cols, kept_formulas, report = apply_reconciliation(
        cols, formulas, target, {"DISCOUNT_RED_DOLLAR": "DM_DISCOUNT_RED_DOLLAR"})
    assert {c["db_column_name"] for c in kept_cols} == {"DM_DISCOUNT_RED_DOLLAR"}
    assert kept_formulas[0]["name"] == "F_discount"
    assert kept_formulas[0]["expr"] == "sum ( [vw::DM_DISCOUNT_RED_DOLLAR] )"   # rewritten, not dropped
    assert report["formulas"] == []


def test_suggest_rejects_exact_half_jaccard():
    assert suggest_column_mappings(["TOTAL_TAX_AMOUNT"], {"TOTAL_FEE_AMOUNT"}) == []


def test_suggest_tie_is_deterministic():
    first = suggest_column_mappings(["AMOUNT"], {"DM_AMOUNT", "ZZ_AMOUNT"})
    second = suggest_column_mappings(["AMOUNT"], {"DM_AMOUNT", "ZZ_AMOUNT"})
    assert first == second


def test_apply_reconciliation_dedupes_convergent_target():
    # col A maps to X (via name_map), col B is already named X (unmapped) —
    # both converge on the same final db_column_name. Without a post-condition
    # dedupe this would emit two columns sharing one column_id ("vw::X"),
    # which ThoughtSpot's import rejects.
    cols = [
        {"name": "A", "db_column_name": "A", "table": "vw", "column_type": "MEASURE"},
        {"name": "X", "db_column_name": "X", "table": "vw", "column_type": "MEASURE"},
    ]
    formulas = [
        {"name": "F_uses_A", "expr": "sum ( [vw::A] )", "column_type": "MEASURE"},
        {"name": "F_uses_X", "expr": "sum ( [vw::X] )", "column_type": "MEASURE"},
    ]
    target = {"X"}
    kept_cols, kept_formulas, report = apply_reconciliation(
        cols, formulas, target, {"A": "X"})

    assert [c["db_column_name"] for c in kept_cols] == ["X"]   # only ONE X kept
    assert report["columns"] == ["X"]                          # the duplicate (orig "X" column) dropped
    assert {f["name"] for f in kept_formulas} == {"F_uses_A"}  # rewritten A->X ref survives
    assert kept_formulas[0]["expr"] == "sum ( [vw::X] )"
    assert "F_uses_X" in report["formulas"]                    # cascaded out: referenced the dropped duplicate


from ts_cli.tableau.reconcile import drop_junk_formulas

def test_drop_junk_formulas():
    formulas = [
        {"name": "F_junk", "expr": "sum ( [vw::__tableau_internal_object_id__].[_12CAA8] )", "column_type": "MEASURE"},
        {"name": "F_clean", "expr": "sum ( [vw::CAMPAIGN_ID] )", "column_type": "MEASURE"},
    ]
    kept, dropped = drop_junk_formulas(formulas)
    assert [f["name"] for f in kept] == ["F_clean"]
    assert dropped == ["F_junk"]
