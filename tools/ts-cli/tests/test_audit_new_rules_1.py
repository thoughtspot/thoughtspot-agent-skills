"""New audit rules, set 1 (audit v2 roadmap PR 4.3): A7, A8, H11, H12, D14, D15, D16."""
from __future__ import annotations

from audit_rule_fixtures.ai import build_tml_col, build_tml_ctx
from audit_run_rule import run_rule


def _sev(ctx, rid):
    return sorted(f.severity for f in run_rule(ctx, rid))


def _measures(blank, total):
    return [build_tml_col(f"M{i}", "MEASURE", desc=None if i < blank else "described")
            for i in range(total)]


# ── A7: visible measures without a description ──────────────────────────────

def test_a7_bands():
    assert _sev(build_tml_ctx(*_measures(1, 4)), "A7") == ["LOW"]
    assert _sev(build_tml_ctx(*_measures(4, 4)), "A7") == ["MEDIUM"]
    assert _sev(build_tml_ctx(*_measures(3, 4)), "A7") == ["LOW"]        # 75%: not above
    assert _sev(build_tml_ctx(*_measures(0, 4)), "A7") == []
    hidden = [build_tml_col("H", "MEASURE", hidden=True)]
    assert _sev(build_tml_ctx(*hidden, build_tml_col("A", desc="d")), "A7") == []  # none visible


# ── H11: many hidden ordinary columns ───────────────────────────────────────

def _h11_ctx(hidden, visible, referenced=0):
    cols = [build_tml_col(f"H{i}", hidden=True) for i in range(hidden)]
    cols += [build_tml_col(f"V{i}") for i in range(visible)]
    ctx = build_tml_ctx(*cols)
    model = ctx.models[0]["model"]
    model["formulas"] = [{"id": f"f{i}", "name": f"F{i}", "expr": f"[H{i}] * 2"}
                         for i in range(referenced)]
    return ctx


def test_h11_bands_and_what_h3_excuses():
    assert _sev(_h11_ctx(3, 1), "H11") == ["MEDIUM"]       # 75% hidden
    assert _sev(_h11_ctx(1, 2), "H11") == ["LOW"]          # 33%
    assert _sev(_h11_ctx(1, 3), "H11") == []               # 25%: not above
    assert _sev(_h11_ctx(3, 1, referenced=3), "H11") == [] # all three feed formulas
    assert _sev(_h11_ctx(0, 0), "H11") == []


def test_h11_counts_physical_columns_only():
    ctx = _h11_ctx(1, 2)
    formula = build_tml_col("F", hidden=True)
    formula.pop("column_id")
    formula["formula_id"] = "f_x"
    ctx.models[0]["model"]["columns"].append(formula)
    assert _sev(ctx, "H11") == ["LOW"]                     # still 1 of 3


def test_h11_excuses_join_keys():
    """Hiding a join key is good modelling (review 2026-11-02: 44 of the 47 hidden
    columns behind the sample's H11 findings were join keys)."""
    ctx = _h11_ctx(4, 1)
    model = ctx.models[0]["model"]
    model["model_tables"] = [{"name": "T", "joins": [
        {"name": "j", "with": "U", "on": "[T::H0] = [U::ID] and [T::H1] = [U::ID2]"}]}]
    assert _sev(ctx, "H11") == ["LOW"]                     # H2, H3 unexplained: 2 of 5
    (f,) = run_rule(ctx, "H11")
    assert "H2" in f.detail and "H0" not in f.detail and "join key" in f.detail


def test_h11_excuses_table_level_join_keys():
    from ts_cli.audit.context import make_context
    cols = [build_tml_col(f"H{i}", hidden=True) for i in range(3)] + [build_tml_col("V")]
    model = {"guid": "g-1", "model": {"name": "M", "columns": cols, "model_tables": [
        {"name": "T", "fqn": "t-t", "joins": [{"name": "j", "referencing_join": "t_u"}]}]}}
    table = {"table": {"name": "T", "joins_with": [
        {"name": "t_u", "destination": {"name": "U"}, "on": "[T::H0] = [U::ID]"}]}}
    ctx = make_context(models=[model], tables={"t-t": table})
    assert _sev(ctx, "H11") == ["LOW"]                     # H1, H2: 2 of 4, not above 50%


# ── D14: rate-like columns summed ───────────────────────────────────────────

def _measure(name, agg=None, formula=False):
    col = build_tml_col(name, "MEASURE", desc="d")
    if agg:
        col["properties"]["aggregation"] = agg
    if formula:
        col.pop("column_id")
        col["formula_id"] = f"formula_{name}"
    return col


def test_d14_whole_words():
    assert _sev(build_tml_ctx(_measure("UNIT_PRICE")), "D14") == ["MEDIUM"]
    assert _sev(build_tml_ctx(_measure("DISCOUNT_RATE", "SUM")), "D14") == ["MEDIUM"]
    assert _sev(build_tml_ctx(_measure("Margin Pct")), "D14") == ["MEDIUM"]
    assert _sev(build_tml_ctx(_measure("SEPARATE_AMOUNT")), "D14") == []
    assert _sev(build_tml_ctx(_measure("DISCOUNT_RATE", "AVERAGE")), "D14") == []
    assert _sev(build_tml_ctx(_measure("UNIT_PRICE", formula=True)), "D14") == []
    assert _sev(build_tml_ctx(_measure("RATE_CARD_ID")), "D14") == []
    attribute = build_tml_col("PRICE_BAND")
    assert _sev(build_tml_ctx(attribute), "D14") == []
    assert _sev(build_tml_ctx(_measure("Rated Capacity")), "D14") == []


def _measure_on(name, column_id):
    col = _measure(name)
    col["column_id"] = column_id
    return col


def test_d14_reads_the_column_part_only():
    """The table part of column_id is not the column's name (review 2026-11-02)."""
    assert _sev(build_tml_ctx(_measure_on("Quantity", "PRICE_HISTORY::QUANTITY")), "D14") == []
    assert _sev(build_tml_ctx(_measure_on("Amount", "AVG_DAILY::AMOUNT")), "D14") == []
    assert _sev(build_tml_ctx(_measure_on("Unit Amount", "T::UNIT_PRICE")), "D14") == ["MEDIUM"]
    assert _sev(build_tml_ctx(_measure_on("Rate Card", "T::RATE_CARD_ID")), "D14") == []


def test_h12_business_names_silent():
    """Words that also name business data are not plumbing (review 2026-11-02: all 25
    sample matches of the first word list were business columns)."""
    for physical in ("AUDIT_DATE", "AUDIT_STATUS", "BATCH_NUMBER", "LOAD_FACTOR",
                     "MAX_LOAD_AMOUNT", "CREATED_DATE", "ACCOUNT_CREATED_AT", "UPDATED_AT"):
        assert _sev(build_tml_ctx(_col_with_id("C", physical)), "H12") == [], physical
    assert _sev(build_tml_ctx(_col_with_id("Amount", "AMOUNT")), "H12") == []
    staged = build_tml_col("Amount")
    staged["column_id"] = "STG_ORDERS::AMOUNT"
    assert _sev(build_tml_ctx(staged), "H12") == []


# ── H12: technical columns visible ──────────────────────────────────────────

def _col_with_id(name, physical, hidden=False):
    col = build_tml_col(name, hidden=hidden)
    col["column_id"] = f"T::{physical}"
    return col


def test_h12_physical_name_only():
    assert _sev(build_tml_ctx(_col_with_id("Load", "ETL_LOAD_TS")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Hash", "_ROW_HASH")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Loaded", "LOADED_AT")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Synced", "_FIVETRAN_SYNCED")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Row hash", "ROW_HASH")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Load", "ETL_LOAD_TS", hidden=True)), "H12") == []
    assert _sev(build_tml_ctx(_col_with_id("Load date", "ORDER_DATE")), "H12") == []
    assert _sev(build_tml_ctx(_col_with_id("Download count", "DOWNLOADS")), "H12") == []


# ── A8: one search term naming two columns ──────────────────────────────────

def test_a8_name_vs_synonym():
    name_clash = build_tml_ctx(build_tml_col("Revenue"),
                               build_tml_col("Sales", synonyms=["revenue "]))
    assert _sev(name_clash, "A8") == ["MEDIUM"]
    synonym_only = build_tml_ctx(build_tml_col("Gross", synonyms=["sales"]),
                                 build_tml_col("Net", synonyms=["Sales"]))
    assert _sev(synonym_only, "A8") == ["LOW"]
    own = build_tml_ctx(build_tml_col("Revenue", synonyms=["revenue", "Revenue", "rev"]),
                        build_tml_col("Cost", synonyms=["spend"]))
    assert _sev(own, "A8") == []
    hidden = build_tml_ctx(build_tml_col("Revenue"),
                           build_tml_col("Sales", synonyms=["revenue"], hidden=True))
    assert _sev(hidden, "A8") == []


def test_a8_lists_the_terms():
    from audit_run_rule import run_rule
    ctx = build_tml_ctx(build_tml_col("Revenue"), build_tml_col("Sales", synonyms=["revenue"]),
                        build_tml_col("A", synonyms=["x"]), build_tml_col("B", synonyms=["X"]))
    (f,) = run_rule(ctx, "A8")
    assert "revenue" in f.detail and "x" in f.detail and "2" in f.detail


def test_a8_lists_name_collisions_first():
    """A MEDIUM finding's list must show the column name that made it MEDIUM."""
    syn = [build_tml_col(f"S{i}", synonyms=[f"a{i}"]) for i in range(6)]
    syn += [build_tml_col(f"R{i}", synonyms=[f"A{i}"]) for i in range(6)]
    ctx = build_tml_ctx(*syn, build_tml_col("Zeta"), build_tml_col("Z2", synonyms=["zeta"]))
    (f,) = run_rule(ctx, "A8")
    assert f.severity == "MEDIUM" and "zeta" in f.detail


def test_a7_reads_measures_only():
    cols = [build_tml_col(f"A{i}") for i in range(4)] + _measures(0, 2)
    assert _sev(build_tml_ctx(*cols), "A7") == []


# ── D15: duplicate Table-level joins ────────────────────────────────────────

def _table_ctx(*joins):
    from ts_cli.audit.context import make_context
    table = {"name": "ORDERS", "columns": [{"name": "ID", "db_column_name": "ID"}],
             "joins_with": list(joins)}
    return make_context(tables={"t-orders": {"guid": "t-orders", "table": table}})


def _jw(name, dest="CUSTOMER", on="[ORDERS::CUST_ID] = [CUSTOMER::ID]", type_="INNER",
        card="MANY_TO_ONE"):
    return {"name": name, "destination": {"name": dest, "fqn": f"t-{dest.lower()}"},
            "on": on, "type": type_, "cardinality": card}


def test_d15():
    assert _sev(_table_ctx(_jw("a"), _jw("b")), "D15") == ["LOW"]
    assert _sev(_table_ctx(_jw("a"), _jw("b", on="[ORDERS::CUST_ID]=[CUSTOMER::ID]",
                                         type_="LEFT_OUTER")), "D15") == ["MEDIUM"]
    role_play = _jw("b", on="[ORDERS::SHIP_CUST_ID] = [CUSTOMER::ID]")
    assert _sev(_table_ctx(_jw("a"), role_play), "D15") == []
    assert _sev(_table_ctx(_jw("a"), _jw("b", dest="REGION")), "D15") == []
    assert _sev(_table_ctx(_jw("a"), {"name": "x"}, "junk", {"destination": "CUSTOMER"}), "D15") == []
    assert _sev(_table_ctx(_jw("a"), _jw("b", card="ONE_TO_ONE")), "D15") == ["MEDIUM"]


def test_d15_odd_destinations_do_not_crash_the_run():
    """A non-string fqn or name is skipped, never a TypeError that loses every rule."""
    odd = [{"destination": {"fqn": ["t-customer"]}, "on": "[A::x] = [B::y]"},
           {"destination": {"name": {"x": 1}}, "on": "[A::x] = [B::y]"},
           {"destination": {"fqn": ["t-customer"]}, "on": "[A::x] = [B::y]"}]
    assert _sev(_table_ctx(_jw("a"), *odd), "D15") == []


# ── D16: join keys of different types ───────────────────────────────────────

def _typed_join_ctx(left_type, right_type, on="[ORDERS::CUST_ID] = [CUST::ID]",
                    cust_tml=True):
    from ts_cli.audit.context import make_context
    tables = {"t-o": {"table": {"name": "ORDERS", "columns": [
        {"name": "CUST_ID", "db_column_properties": {"data_type": left_type}},
        {"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}}
    if cust_tml:
        tables["t-c"] = {"table": {"name": "CUST", "columns": [
            {"name": "ID", "db_column_properties": {"data_type": right_type}},
            {"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}
    model = {"guid": "m-1", "model": {"name": "Sales", "columns": [], "model_tables": [
        {"name": "ORDERS", "fqn": "t-o", "joins": [{"name": "j1", "with": "CUST", "on": on,
                                                   "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "CUST", "fqn": "t-c"}]}}
    return make_context(models=[model], tables=tables)


def test_d16():
    assert _sev(_typed_join_ctx("VARCHAR", "INT64"), "D16") == ["MEDIUM"]
    assert _sev(_typed_join_ctx("INT32", "INT64"), "D16") == []
    assert _sev(_typed_join_ctx("VARCHAR", "CHAR"), "D16") == []
    assert _sev(_typed_join_ctx("DATE", "DATE_TIME"), "D16") == []
    assert _sev(_typed_join_ctx("VARCHAR", "INT64", cust_tml=False), "D16") == []
    assert _sev(_typed_join_ctx("VARCHAR", "INT64", on="[ORDERS::CUST_ID] = 1"), "D16") == []
    two = "[ORDERS::REGION] = [CUST::REGION] and [ORDERS::CUST_ID] = [CUST::ID]"
    assert _sev(_typed_join_ctx("INT64", "VARCHAR", on=two), "D16") == ["MEDIUM"]


def test_d16_reads_on_as_the_join_graph_does():
    """Escaped names are unescaped; a side with arithmetic is not a column pair."""
    assert _sev(_typed_join_ctx("VARCHAR", "INT64", on="[ORDERS::CUST_ID] = [CUST::ID] + 1"),
                "D16") == []
    assert _sev(_typed_join_ctx("VARCHAR", "INT64", on="[ORDERS::CUST\\_ID] = [CUST::ID]"),
                "D16") == ["MEDIUM"]


def test_d16_names_both_keys():
    from audit_run_rule import run_rule
    (f,) = run_rule(_typed_join_ctx("VARCHAR", "INT64"), "D16")
    assert "ORDERS::CUST_ID (VARCHAR)" in f.detail and "CUST::ID (INT64)" in f.detail
