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


# ── H12: technical columns visible ──────────────────────────────────────────

def _col_with_id(name, physical, hidden=False):
    col = build_tml_col(name, hidden=hidden)
    col["column_id"] = f"T::{physical}"
    return col


def test_h12_physical_name_only():
    assert _sev(build_tml_ctx(_col_with_id("Load", "ETL_LOAD_TS")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Hash", "_ROW_HASH")), "H12") == ["LOW"]
    assert _sev(build_tml_ctx(_col_with_id("Updated", "UPDATED_AT")), "H12") == ["LOW"]
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
