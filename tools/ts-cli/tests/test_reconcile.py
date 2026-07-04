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
