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
# The docs' own spelling (security-rls, "Respect join definitions").
_WITH_IS_NULL = [{"name": "Region",
                  "expr": "ts_groups = [CUST_1::REGION] or is_null ( [CUST_1::REGION] )"}]


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
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_NO_NULL), "S12") == ["MEDIUM"]
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_WITH_NULL), "S12") == []
    assert _sev(_outer_ctx("RIGHT_OUTER", cust_rules=_NO_NULL), "S12") == []
    assert _sev(_outer_ctx("RIGHT_OUTER", orders_rules=_NO_NULL), "S12") == ["MEDIUM"]
    assert _sev(_outer_ctx("OUTER", orders_rules=_NO_NULL), "S12") == ["MEDIUM"]
    assert _sev(_outer_ctx("OUTER", cust_rules=_NO_NULL), "S12") == ["MEDIUM"]
    assert _sev(_outer_ctx("INNER", cust_rules=_NO_NULL), "S12") == []
    assert _sev(_outer_ctx("LEFT_OUTER", cust_tml=False), "S12") == []
    assert _sev(_outer_ctx("LEFT_OUTER", orders_rules=_NO_NULL), "S12") == []   # required side
    assert _sev(_outer_ctx("LEFT_OUTER", cust_rules=_WITH_IS_NULL), "S12") == []


def test_s12_resolves_with_as_the_join_graph_does():
    """`with` naming the physical table of an aliased destination still resolves
    (tml.join_target, review 2026-11-04)."""
    ctx = _outer_ctx("LEFT_OUTER", cust_rules=_NO_NULL)
    tables = ctx.models[0]["model"]["model_tables"]
    tables[1]["alias"] = "BILL_TO"
    assert _sev(ctx, "S12") == ["MEDIUM"]
    tables[1]["alias"] = ["odd"]                                  # never raises
    assert _sev(ctx, "S12") in ([], ["MEDIUM"])


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


def test_s13_rule_without_an_expression_does_not_end_the_run():
    from audit_rule_fixtures.rls import build_trip_table_ctx, build_trip_varchar
    for rule in ({"name": "R"}, {"name": "R", "expr": None}, {"name": "R", "expr": ""},
                 {"name": "R", "expr": 7}):
        assert _sev(build_trip_table_ctx([build_trip_varchar("COUNTRY")], [rule]), "S13") == []


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


def test_d17_reads_the_last_word_only():
    """A date part or id used as a qualifier is not the column (review 2026-11-04)."""
    for name in ("Prior Year Sales", "Month To Date Sales", "Fiscal Year Revenue",
                 "Order ID Count", "Long Term Debt", "Orders Per Day", "Year Flag",
                 "Key Account Revenue"):
        assert _sev(_typed_ctx(_col(name, "AMOUNT")), "D17") == [], name
    assert _sev(_typed_ctx(_col("ZIP Code", "POSTAL")), "D17") == ["MEDIUM"]
    assert _sev(_typed_ctx(_col("Ship Day", "SHIP_DAY")), "D17") == ["MEDIUM"]
    for name in ("Order Month Num", "Fiscal Week Number", "Year Built", "Latitude Client",
                 "Longitude Siege", "Month Index", "Year Desc"):
        assert _sev(_typed_ctx(_col(name, "AMOUNT")), "D17") == ["MEDIUM"], name
    assert _sev(_typed_ctx(_col("Amount", "STORE_LAT_DEG")), "D17") == ["MEDIUM"]


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


# ── D18: copy of a table on the many side ───────────────────────────────────

def _copies_ctx(fact_copies=1, dim_copies=1, fact_alias=False):
    """A fact SALES joined many-to-one to a dimension DATES, each repeated as asked."""
    tables = []
    for i in range(fact_copies):
        alias = (fact_alias or i) and f"SALES_{i}"
        mt = {"name": "SALES", "fqn": "t-sales", "joins": [
            {"with": "DATES", "on": f"[{alias or 'SALES'}::D] = [DATES::D]",
             "type": "INNER", "cardinality": "MANY_TO_ONE"}]}
        if alias:
            mt["alias"] = alias
        tables.append(mt)
    for i in range(dim_copies):
        mt = {"name": "DATES", "fqn": "t-dates"}
        if i:
            mt["alias"] = f"DATES_{i}"
        tables.append(mt)
    cols = [{"name": "Amount", "column_id": f"{t.get('alias') or t['name']}::AMT",
             "properties": {"column_type": "MEASURE"}} for t in tables if t["name"] == "SALES"]
    cols += [{"name": "Date", "column_id": "DATES::D", "properties": {"column_type": "ATTRIBUTE"}}]
    return make_context(models=[{"guid": "m-1", "model": {"name": "M", "columns": cols,
                                                          "model_tables": tables}}])


def test_d18():
    assert _sev(_copies_ctx(fact_copies=2), "D18") == ["LOW", "LOW"]
    assert _sev(_copies_ctx(fact_copies=1, fact_alias=True), "D18") == []
    assert _sev(_copies_ctx(dim_copies=2), "D18") == []


# ── A9: parameters under Spotter ────────────────────────────────────────────

def _param_ctx(expr, spotter=True, params=("Rate",)):
    body = {"name": "M", "columns": [], "formulas": [{"id": "f1", "name": "Adjusted", "expr": expr}],
            "parameters": [{"id": f"p{i}", "name": p, "data_type": "DOUBLE"}
                           for i, p in enumerate(params)]}
    if spotter:
        body["properties"] = {"spotter_config": {"is_spotter_enabled": True}}
    return make_context(models=[{"guid": "m-1", "model": body}])


def test_a9():
    assert _sev(_param_ctx("[Rate] * [T::AMT]"), "A9") == ["LOW"]
    assert _sev(_param_ctx("[Rate] * [T::AMT]", spotter=False), "A9") == []
    assert _sev(_param_ctx("concat ( '[Rate]' , [T::NAME] )"), "A9") == []
    assert _sev(_param_ctx("[Rate] * [T::AMT]", params=()), "A9") == []
    assert _sev(_param_ctx("[T::Rate] * 2"), "A9") == []
    (f,) = run_rule(_param_ctx("[Rate] * [T::AMT]"), "A9")
    assert "Adjusted" in f.detail


# ── H14: flags shown as true/false or 0/1 ───────────────────────────────────

def test_h14():
    bool_col = _col("Active", "ACTIVE", ctype="ATTRIBUTE")
    (f,) = run_rule(_typed_ctx(bool_col, types={"ACTIVE": "BOOL"}), "H14")
    assert f.severity == "LOW" and "Active" in f.detail
    assert _sev(_typed_ctx(_col("IS_ACTIVE", ctype="ATTRIBUTE"),
                           types={"IS_ACTIVE": "INT64"}), "H14") == ["LOW"]
    assert _sev(_typed_ctx(_col("Churned", "CHURN_FLAG")), "H14") == ["LOW"]
    hidden = _col("Active", "ACTIVE", ctype="ATTRIBUTE", hidden=True)
    assert _sev(_typed_ctx(hidden, types={"ACTIVE": "BOOL"}), "H14") == []
    assert _sev(_typed_ctx(_col("Island", ctype="ATTRIBUTE"), types={"Island": "VARCHAR"}),
                "H14") == []
    assert _sev(_typed_ctx(_col("Display Name", ctype="ATTRIBUTE")), "H14") == []


# ── D13: group or semi-additive formula summed under a rate name ────────────

_LAST = "last_value ( sum ( [T::RATE] ) , query_groups ( ) , { [D::DT] } )"


def _bare_ctx(name, expr, agg="SUM"):
    col = _col(name, formula=True, agg=agg)
    ctx = _typed_ctx(col)
    ctx.models[0]["model"]["formulas"] = [{"id": f"f_{name}", "name": name, "expr": expr}]
    return ctx


def test_d13():
    assert _sev(_bare_ctx("Interest Rate", _LAST), "D13") == ["MEDIUM"]
    assert _sev(_bare_ctx("Interest Rate", _LAST, agg="AVERAGE"), "D13") == []
    assert _sev(_bare_ctx("Interest Rate", _LAST, agg=None), "D13") == []
    group = "group_aggregate ( average ( [T::PRICE] ) , query_groups ( ) , query_filters ( ) )"
    assert _sev(_bare_ctx("Avg Price", group), "D13") == ["MEDIUM"]
    assert _sev(_bare_ctx("Avg Price", f"sum ( {group} )"), "D13") == []
    # A balance summed across accounts and taken last over time is the textbook
    # semi-additive measure: SUM is right (thoughtspot-model-tml.md; review 2026-11-04).
    assert _sev(_bare_ctx("Closing Balance", _LAST), "D13") == []
    assert _sev(_bare_ctx("Revenue", _LAST), "D13") == []
    assert _sev(_bare_ctx("Avg Price", "group_sum ( [T::PRICE] , [T::REGION] )"), "D13") == []
    assert _sev(_bare_ctx("Avg Price", f"{_LAST} + 1"), "D13") == []


def test_d13_reads_d14s_rate_words():
    from ts_cli.audit.catalog_model import load_catalog
    rules = load_catalog().rules

    def name_regexes(rid):
        found = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("field") == "name" and "regex" in node:
                    found.append(node["regex"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(rules[rid].aggregate)
        return found
    import re
    words = lambda rx: set(re.search(r"\(\?i\)\(\^\|\[_\\s:\]\)\(([^)]*)\)", rx).group(1).split("|"))
    d13, d14 = words(name_regexes("D13")[0]), words(name_regexes("D14")[0])
    assert d13 and d13 <= d14 and "balance" not in d13
