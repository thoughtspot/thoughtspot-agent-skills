"""New audit rules, set 2 (audit v2 roadmap PR 4.4): S12, S13, D13, D17, D18, H13, H14, A9."""
from __future__ import annotations

from audit_rule_fixtures.rls import build_rls_expr
from audit_run_rule import run_rule
from ts_cli.audit.context import make_context


def _sev(ctx, rid):
    return sorted(f.severity for f in run_rule(ctx, rid))


# ── S12: RLS table on the optional side of an outer join ────────────────────

def _rls_table(name, rules):
    return {"table": {"name": name, "columns": [{"name": "K"}, {"name": "REGION"}],
                      "rls_rules": {"tables": [{"name": name}],
                                    "table_paths": [{"id": f"{name}_1", "table": name,
                                                     "column": ["REGION"]}],
                                    "rules": rules} if rules else None}}


_NO_NULL = [{"name": "Region", "expr": "[CUST_1::REGION] = ts_groups"}]
_WITH_NULL = [{"name": "Region",
               "expr": "isnull ( [CUST_1::REGION] ) or [CUST_1::REGION] = ts_groups"}]


def _outer_ctx(join_type, cust_rules=None, orders_rules=None, cust_tml=True):
    tables = {"t-o": _rls_table("ORDERS", orders_rules)}
    if cust_tml:
        tables["t-c"] = _rls_table("CUST", cust_rules)
    model = {"guid": "m-1", "model": {"name": "Sales", "columns": [], "model_tables": [
        {"name": "ORDERS", "fqn": "t-o", "joins": [
            {"name": "j", "with": "CUST", "on": "[ORDERS::K] = [CUST::K]",
             "type": join_type, "cardinality": "MANY_TO_ONE"}]},
        {"name": "CUST", "fqn": "t-c"}]}}
    return make_context(models=[model], tables=tables)


def test_s12_optional_side():
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_WITH_NULL), "S12") == []
    assert _sev(_outer_ctx("RIGHT_OUTER", cust_rules=_NO_NULL), "S12") == []
    assert _sev(_outer_ctx("RIGHT_OUTER", orders_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("OUTER", orders_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("OUTER", cust_rules=_NO_NULL), "S12") == ["LOW"]
    assert _sev(_outer_ctx("INNER", cust_rules=_NO_NULL), "S12") == []
    assert _sev(_outer_ctx("LEFT_OUTER", cust_tml=False), "S12") == []


def test_s12_names_the_table():
    (f,) = run_rule(_outer_ctx("LEFT_OUTER", cust_rules=_NO_NULL), "S12")
    assert "CUST" in f.detail


# ── S13: RLS rule search cannot index ───────────────────────────────────────

def test_s13():
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_groups"), "S13") == []
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_groups_int"), "S13") == []
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_username"), "S13") == []
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] = ts_org"), "S13") == ["LOW"]
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] != ts_groups"), "S13") == ["LOW"]
    assert _sev(build_rls_expr("[CUSTOMERS_1::COUNTRY] <> ts_groups"), "S13") == ["LOW"]


# ── D17: identifiers, coordinates and date parts summed ─────────────────────

def _typed_ctx(*cols, types=None):
    """A Model over table T whose Table TML types its columns (`types`: name -> type)."""
    table_cols = [{"name": n, "db_column_name": n, "db_column_properties": {"data_type": t}}
                  for n, t in (types or {}).items()]
    model = {"guid": "m-1", "model": {"name": "M", "columns": list(cols),
                                       "model_tables": [{"name": "T", "fqn": "t-t"}]}}
    return make_context(models=[model], tables={"t-t": {"table": {"name": "T",
                                                                 "columns": table_cols}}})


def _col(name, physical=None, ctype="MEASURE", agg=None, hidden=False, formula=False):
    props = {"column_type": ctype}
    if agg:
        props["aggregation"] = agg
    if hidden:
        props["is_hidden"] = True
    col = {"name": name, "properties": props}
    if formula:
        col["formula_id"] = f"f_{name}"
    else:
        col["column_id"] = f"T::{physical or name}"
    return col


def test_d17_words():
    assert _sev(_typed_ctx(_col("CUSTOMER_ID", agg="SUM")), "D17") == ["MEDIUM"]
    assert _sev(_typed_ctx(_col("Latitude")), "D17") == ["MEDIUM"]
    assert _sev(_typed_ctx(_col("Order Year", "ORDER_YEAR", agg="SUM")), "D17") == ["MEDIUM"]
    assert _sev(_typed_ctx(_col("Store", "STORE_ZIP")), "D17") == ["MEDIUM"]
    assert _sev(_typed_ctx(_col("Number of Orders", "NUM_ORDERS")), "D17") == []
    assert _sev(_typed_ctx(_col("CUSTOMER_ID", agg="AVERAGE")), "D17") == []
    assert _sev(_typed_ctx(_col("CUSTOMER_ID", formula=True)), "D17") == []
    assert _sev(_typed_ctx(_col("STORE_KEY", hidden=True)), "D17") == []
    zip_table = _col("Amount")
    zip_table["column_id"] = "ZIP_LOOKUP::AMOUNT"
    assert _sev(_typed_ctx(zip_table), "D17") == []
    assert _sev(_typed_ctx(_col("Island Count")), "D17") == []
    assert _sev(_typed_ctx(_col("Yearly Revenue")), "D17") == []


# ── H13: date-part columns beside a date ────────────────────────────────────

def test_h13():
    date_col = _col("Order Date", "ORDER_DATE", ctype="ATTRIBUTE")
    month = _col("Order Month", "ORDER_MONTH", ctype="ATTRIBUTE")
    typed = {"ORDER_DATE": "DATE", "ORDER_MONTH": "VARCHAR"}
    ctx = _typed_ctx(date_col, month, types=typed)
    (f,) = run_rule(ctx, "H13")
    assert f.severity == "LOW" and "Order Month" in f.detail
    assert _sev(_typed_ctx(month, types={"ORDER_MONTH": "VARCHAR"}), "H13") == []
    assert _sev(_typed_ctx(date_col, month, types={"ORDER_DATE": "DATE",
                                                    "ORDER_MONTH": "DATE"}), "H13") == []
    year_measure = _col("Order Year", "ORDER_YEAR")
    assert _sev(_typed_ctx(date_col, year_measure, types={"ORDER_DATE": "DATE",
                                                          "ORDER_YEAR": "INT64"}), "H13") == []
    no_tml = make_context(models=[{"guid": "m", "model": {"name": "M", "columns": [date_col, month]}}])
    assert _sev(no_tml, "H13") == []
