"""Tests for ts_cli.formula_translate — `ts formula translate` / `ts formula detect`.

Spec: docs/superpowers/specs/2026-10-06-ts-object-formula-translate-design.md §8.
No live calls: validation runs against a fake client.
"""
from __future__ import annotations

import json

import pytest

from ts_cli.formula_translate.adapters import (
    APPROXIMATED, NEEDS_REVIEW, TRANSLATED, make_recording_resolver, normalise_dialect,
    synthesise_sisense_context,
)
from ts_cli.formula_translate.context import (
    ColumnContext, ColumnSpec, parse_columns_json, specs_from_model_tml,
)
from ts_cli.formula_translate.detect import detect
from ts_cli.formula_translate.engine import formula_tml_entries, infer_role, translate, tml_snippet
from ts_cli.formula_translate.refs import bracket_refs, qualify_refs
from ts_cli.formula_translate.traps import detect_traps, leftover_sql
from ts_cli.formula_translate.validate import (
    SCRATCH_PREFIX, SCRATCH_SUFFIX, ValidationError, Validator, agentql_statement,
    build_scratch_model, pick_group_attribute, scratch_name,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MODEL = {
    "guid": "11111111-2222-3333-4444-555555555555",
    "model": {
        "name": "Orders Model",
        "model_tables": [{"name": "ORDERS"}, {"name": "CUSTOMERS"}],
        "formulas": [{"id": "formula_Total Sales", "name": "Total Sales",
                      "expr": "sum ( [ORDERS::AMOUNT] )"},
                     {"id": "formula_Is Big", "name": "Is Big",
                      "expr": "[ORDERS::AMOUNT] > 100"}],
        "columns": [
            {"name": "Region", "column_id": "CUSTOMERS::REGION",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Order Date", "column_id": "ORDERS::ORDER_DATE",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Ship Date", "column_id": "ORDERS::SHIP_DATE",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Amount", "column_id": "ORDERS::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Order Id", "column_id": "ORDERS::ORDER_ID",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Total Sales", "formula_id": "formula_Total Sales",
             "properties": {"column_type": "MEASURE"}},
            {"name": "Is Big", "formula_id": "formula_Is Big",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
    },
}
TABLES = [{"table": {"name": "ORDERS", "columns": [
    {"name": "ORDER_DATE", "db_column_properties": {"data_type": "DATE"}},
    {"name": "SHIP_DATE", "db_column_properties": {"data_type": "DATE"}},
    {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]


def model_ctx() -> ColumnContext:
    return ColumnContext(specs_from_model_tml(MODEL, TABLES), level=2, model_name="Orders Model")


# ---------------------------------------------------------------------------
# Context + recording resolver
# ---------------------------------------------------------------------------

class TestContext:
    def test_level0_placeholder(self):
        ctx = ColumnContext()
        assert ctx.resolve("Sales") == "[TABLE::Sales]"
        assert ctx.references[0].as_dict() == {"source": "Sales", "target": "[TABLE::Sales]",
                                               "placeholder": True}

    def test_level0_keeps_source_table(self):
        ctx = ColumnContext()
        assert ctx.resolve("Amount", table_hint="Sales") == "[Sales::Amount]"

    def test_records_each_reference_once(self):
        ctx = ColumnContext()
        ctx.resolve("A"); ctx.resolve("A"); ctx.resolve("B")
        assert [r.source for r in ctx.references] == ["A", "B"]

    def test_columns_json_shapes(self):
        a = parse_columns_json('{"Sales": "ORDERS.SALES_AMT", "Cust": "ORDERS::CUST_ID"}')
        assert [s.target for s in a] == ["[ORDERS::SALES_AMT]", "[ORDERS::CUST_ID]"]
        b = parse_columns_json('["ORDERS.SALES_AMT"]')
        assert b[0].names == ["SALES_AMT"]
        c = parse_columns_json('[{"source": "Sales", "table": "O", "column": "S", '
                               '"data_type": "DATE", "key": true}]')
        assert c[0].target == "[O::S]" and c[0].is_date and c[0].key
        with pytest.raises(ValueError):
            parse_columns_json("[1]")
        with pytest.raises(ValueError):
            parse_columns_json("not json")

    def test_level1_exact_then_case_insensitive(self):
        ctx = ColumnContext(parse_columns_json('{"Sales Amount": "ORDERS.SALES_AMT"}'), level=1)
        assert ctx.resolve("Sales Amount") == "[ORDERS::SALES_AMT]"
        assert ctx.resolve("sales_amount") == "[ORDERS::SALES_AMT]"  # case + space/underscore

    def test_level1_miss_is_unresolved_with_candidates_never_fuzzy(self):
        ctx = ColumnContext(parse_columns_json('{"Customer": "ORDERS.CUST"}'), level=1)
        out = ctx.resolve("Custmer")
        assert out == "[TABLE::Custmer]"  # NOT silently matched to Customer
        ref = ctx.unresolved[0]
        assert ref.placeholder and ref.candidates == ["Customer"]

    def test_model_specs(self):
        ctx = model_ctx()
        assert ctx.resolve("Amount") == "[ORDERS::AMOUNT]"
        assert ctx.resolve("ORDER_DATE") == "[ORDERS::ORDER_DATE]"   # column_id part
        assert ctx.resolve("Total Sales") == "[formula_Total Sales]"  # formula by id
        assert "[formula_Total Sales]" in ctx.aggregate_formula_targets()
        assert "[formula_Is Big]" not in ctx.aggregate_formula_targets()
        assert {"Order Date", "ORDER_DATE", "Ship Date", "SHIP_DATE"} <= ctx.date_names()
        assert not ctx.unresolved

    def test_ambiguous_name_is_unresolved(self):
        specs = [ColumnSpec(names=["Region"], target="[A::REGION]", table="A"),
                 ColumnSpec(names=["Region"], target="[B::REGION]", table="B")]
        ctx = ColumnContext(specs, level=1)
        ctx.resolve("Region")
        assert ctx.unresolved and len(ctx.unresolved[0].candidates) == 2
        ctx2 = ColumnContext(specs, level=1)
        assert ctx2.resolve("Region", table_hint="B") == "[B::REGION]"

    def test_recording_resolver_sql_idents(self):
        ctx = ColumnContext(parse_columns_json('{"amount": "ORDERS.AMOUNT"}'), level=1)
        r = make_recording_resolver(ctx)
        assert r("o.amount") == "[ORDERS::AMOUNT]"
        assert r('"amount"') == "[ORDERS::AMOUNT]"
        assert r("`amount`") == "[ORDERS::AMOUNT]"
        assert hasattr(r, "metric_refs")

    def test_key_reference(self):
        ctx = ColumnContext(parse_columns_json('[{"column": "ID", "table": "O", "key": true}]'), level=1)
        assert ctx.key_reference() == "[O::ID]"
        assert ColumnContext().key_reference() == "[TABLE::<primary key>]"


class TestRefs:
    def test_bracket_refs_skip_literals(self):
        assert bracket_refs("[a] + '[not]' + [b]") == ["a", "b"]

    def test_qualify_bare_idents_skips_keywords_and_calls(self):
        ctx = ColumnContext()
        out = qualify_refs("if (Year = '2024') then sum(Sales) else 0", ctx, bare_idents=True)
        assert out == "if ([TABLE::Year] = '2024') then sum([TABLE::Sales]) else 0"

    def test_qualify_leaves_formula_ids_and_params(self):
        ctx = ColumnContext()
        out = qualify_refs("[formula_X] + [P] + [c]", ctx, parameters={"P"})
        assert out == "[formula_X] + [P] + [TABLE::c]"
        kinds = {r.kind for r in ctx.references}
        assert kinds == {"parameter", "column"}


# ---------------------------------------------------------------------------
# Adapters — each normalises its translator's own return shape
# ---------------------------------------------------------------------------

class TestAdapters:
    def test_dialect_names(self):
        assert normalise_dialect("PowerBI") == "dax"
        assert normalise_dialect("excel") == "excel"  # translator-backed since v0.158.0
        assert normalise_dialect("Sheets") == "google_sheets"
        with pytest.raises(ValueError):
            normalise_dialect("sigma")  # still map-backed: the skill, not the CLI

    def test_tableau(self):
        r = translate("ROUND(SUM([Sales]) / COUNTD([Customer]), 2)", "tableau")
        assert r["status"] == TRANSLATED and r["role"] == "MEASURE"
        assert r["formula"] == "round ( sum ( [TABLE::Sales]) / unique count ( [TABLE::Customer]) , 0.01 )"
        assert [x["source"] for x in r["references"]] == ["Sales", "Customer"]

    def test_tableau_errors_are_needs_review(self):
        r = translate("WINDOW_SUM(SUM([Sales]))", "tableau")
        assert r["status"] == NEEDS_REVIEW and r["formula"] is None
        assert r["original_kept"] == "WINDOW_SUM(SUM([Sales]))"
        assert any("WINDOW_SUM" in n for n in r["notes"])

    def test_tableau_parameter_not_a_column(self):
        r = translate("[Sales] * [Parameters].[Rate]", "tableau")
        kinds = {x["source"]: x.get("kind", "column") for x in r["references"]}
        assert kinds["[Rate]"] == "parameter" and kinds["Sales"] == "column"

    def test_tableau_level2_date_arithmetic(self):
        r = translate("DATEDIFF('day', [Order Date], [Ship Date])", "tableau", model_ctx())
        assert r["formula"] == "diff_days ( [ORDERS::SHIP_DATE] , [ORDERS::ORDER_DATE] )"
        assert not r["unresolved"]

    def test_dax(self):
        r = translate("DIVIDE(SUM(Sales[Amount]), DISTINCTCOUNT(Sales[Customer]))", "dax")
        assert r["status"] == TRANSLATED
        assert r["formula"] == "safe_divide(sum([Sales::Amount]), unique count([Sales::Customer]))"

    def test_dax_approximated(self):
        r = translate("CALCULATE(SUM(Sales[Amount]), ALL(Sales[Region]))", "dax")
        assert r["status"] == APPROXIMATED and r["classification"] == "direct (downgrade)"
        assert r["notes"]

    def test_dax_needs_review(self):
        r = translate("SUMX(Sales, Sales[Qty] * Sales[Price])", "dax")
        assert r["status"] == NEEDS_REVIEW and r["classification"] == "unmappable"

    def test_dax_home_columns_and_date_subtraction(self):
        ctx = ColumnContext(parse_columns_json(
            '[{"source": "Ship", "table": "T", "column": "SHIP", "data_type": "DATE"},'
            ' {"source": "Order", "table": "T", "column": "ORD", "data_type": "DATE"}]'), level=1)
        r = translate("[Ship] - [Order]", "dax", ctx)
        assert r["formula"] == "diff_days([T::SHIP], [T::ORD])"

    def test_qlik(self):
        r = translate("Round(Sum(Sales), 0.01)", "qlik")
        assert r["formula"] == "round(sum([TABLE::Sales]), 0.01)"
        assert any("already a step" in t for t in r["traps"])

    def test_qlik_review(self):
        r = translate("Concat(Name, ',')", "qlik")
        assert r["status"] == NEEDS_REVIEW

    def test_qlik_leftover_distinct_is_review_not_emitted(self):
        # qlik.translate only handles Count(DISTINCT x) as the WHOLE expression; inside a
        # larger one it leaves `count(DISTINCT Customer)`, which no TS function accepts.
        r = translate("Sum(Sales) / Count(DISTINCT Customer)", "qlik")
        assert r["status"] == NEEDS_REVIEW and r["formula"] is None
        assert "DISTINCT" in r["partial"]

    def test_sisense_synthesised_context(self):
        assert synthesise_sisense_context("[rev] / [cust]") == {
            "[rev]": {"dim": "[TABLE.rev]"}, "[cust]": {"dim": "[TABLE.cust]"}}
        r = translate("ROUND(SUM([rev]), 2)", "sisense")
        assert r["formula"] == "round(sum([TABLE::rev]), 0.01)"
        assert any("no JAQL context" in n for n in r["notes"])

    def test_sisense_real_context(self):
        ctx = {"[rev]": {"dim": "[Orders.Revenue]", "agg": "sum"}}
        r = translate("[rev] * 2", "sisense", sisense_context=ctx)
        assert r["formula"] == "sum([TABLE::Revenue]) * 2"

    def test_snowflake(self):
        r = translate("ROUND(SUM(sales)/COUNT(DISTINCT cust), 2)", "snowflake")
        assert r["formula"] == "round ( sum ( [TABLE::sales] ) / unique count ( [TABLE::cust] ) , 0.01 )"

    def test_snowflake_untranslatable(self):
        r = translate("ROW_NUMBER() OVER (ORDER BY x)", "snowflake")
        assert r["status"] == NEEDS_REVIEW and "ROW_NUMBER" in r["notes"][0]

    def test_snowflake_parser_error_is_review_not_crash(self):
        r = translate("ROUND(sales, ", "snowflake")
        assert r["status"] == NEEDS_REVIEW

    def test_databricks(self):
        r = translate("date_add(`order_date`, 3)", "databricks")
        assert r["formula"] == "add_days ( [TABLE::order_date] , 3 )"

    def test_metric_ref_round_is_aggregated(self):
        # ROUND over an aggregate Model formula: the resolver's metric_refs tell sv_sql
        # the operand is aggregated even though [formula_X] hides it (BL-331).
        r = translate('ROUND("Total Sales", 2)', "snowflake", model_ctx())
        assert r["formula"] == "round ( [formula_Total Sales] , 0.01 )"
        assert r["role"] == "MEASURE"


# ---------------------------------------------------------------------------
# Golden trap cases (spec §8)
# ---------------------------------------------------------------------------

class TestGoldenTraps:
    @pytest.mark.parametrize("dialect,src,expected", [
        ("tableau", "ROUND([x], 2)", "round ( [TABLE::x] , 0.01 )"),
        ("tableau", "ROUND([x], 0)", "round ( [TABLE::x] , 1 )"),
        ("snowflake", "ROUND(x, -2)", "round ( [TABLE::x] , 100 )"),
        ("dax", "ROUND(SUM(T[x]), 2)", "round(sum([T::x]), 0.01)"),
        ("sisense", "ROUND([x], 0)", "round([TABLE::x], 1)"),
    ])
    def test_round_increment(self, dialect, src, expected):
        r = translate(src, dialect)
        assert r["formula"] == expected
        assert any("increment" in t for t in r["traps"])

    @pytest.mark.parametrize("dialect,src", [
        ("tableau", "COUNTD([c])"), ("dax", "DISTINCTCOUNT(T[c])"),
        ("snowflake", "COUNT(DISTINCT c)"), ("qlik", "Count(DISTINCT c)"),
    ])
    def test_unique_count(self, dialect, src):
        r = translate(src, dialect)
        assert "unique count" in r["formula"] and "unique_count" not in r["formula"]
        assert any("unique count" in t for t in r["traps"])

    @pytest.mark.parametrize("dialect,src", [
        ("tableau", "DATEDIFF('day', [start], [end])"),
        ("snowflake", "DATEDIFF('day', start_d, end_d)"),
    ])
    def test_diff_days_end_first(self, dialect, src):
        r = translate(src, dialect)
        f = r["formula"]
        assert f.startswith("diff_days")
        assert f.index("end") < f.index("start")
        assert any("LATER date first" in t for t in r["traps"])

    def test_count_star_counts_a_key(self):
        r = translate("COUNT(*)", "snowflake")
        assert r["formula"] == "count ( [TABLE::<primary key>] )"
        assert any(x.get("kind") == "primary_key" for x in r["references"])
        assert any("COUNT(*)" in t for t in r["traps"])
        ctx = ColumnContext(parse_columns_json('[{"column": "ID", "table": "O", "key": true}]'), level=1)
        assert translate("COUNT(*)", "snowflake", ctx)["formula"] == "count ( [O::ID] )"

    def test_count_star_at_level2_without_key_is_unresolved(self):
        r = translate("COUNT(*)", "snowflake", model_ctx())
        assert r["unresolved"] == ["COUNT(*)"]

    def test_week_diff_over_seven(self):
        r = translate("DATEDIFF('week', [a], [b])", "tableau")
        assert any("week boundaries" in t for t in r["traps"])
        # the output does not compute what the source does: never a clean "direct"
        assert r["status"] == APPROXIMATED and r["classification"] == "direct (downgrade)"

    def test_case_insensitive_compare_flagged_for_case_sensitive_dialects(self):
        r = translate("CASE WHEN status = 'Open' THEN 1 ELSE 0 END", "snowflake")
        assert any("case-INSENSITIVE" in t for t in r["traps"])
        assert r["status"] == APPROXIMATED  # differs for values differing only in case
        r2 = translate("IF(Sales[Status] = \"Open\", 1, 0)", "dax")  # DAX is case-insensitive
        assert not any("case-INSENSITIVE" in t for t in (r2["traps"] or []))
        assert r2["status"] == TRANSLATED

    def test_monday_week_start_flag(self):
        traps = detect_traps("snowflake", "DATE_TRUNC('week', d)", "start_of_week ( [T::d] )")
        assert any("Monday week start" in t for t in traps)

    def test_diff_months_boundaries(self):
        traps = detect_traps("tableau", "DATEDIFF('month',[a],[b])", "diff_months ( [T::b] , [T::a] )")
        assert any("boundaries" in t for t in traps)

    def test_passthrough_classified(self):
        r = translate("UPPER(Sales[Name])", "dax")
        assert r["classification"] == "passthrough"
        assert any("passthrough" in t for t in r["traps"])

    def test_leftover_sql_ignores_literals(self):
        assert leftover_sql("sql_int_aggregate_op ( \"COUNT(*) OVER ()\" )") is None
        assert leftover_sql("count(DISTINCT [x])")


# ---------------------------------------------------------------------------
# Role + TML
# ---------------------------------------------------------------------------

class TestRoleAndTml:
    def test_role_from_text(self):
        ctx = ColumnContext()
        assert infer_role("sum ( [T::a] )", ctx)["role"] == "MEASURE"
        assert infer_role("[T::a] * 2", ctx)["role"] == "ATTRIBUTE"

    def test_role_from_aggregate_formula_reference(self):
        assert infer_role("[formula_Total Sales] * 2", model_ctx())["role"] == "MEASURE"

    def test_semi_additive_wrapper(self):
        assert infer_role("last_value ( sum ( [T::a] ) , query_groups ( ) , { [T::d] } )",
                          ColumnContext())["agentql_wrapper"] == "SUM"

    def test_tml_entries(self):
        f, c = formula_tml_entries("My Calc", "sum ( [T::a] )", "MEASURE")
        assert f == {"id": "formula_My Calc", "name": "My Calc", "expr": "sum ( [T::a] )"}
        # user-supplied names keep their spaces in the id (repo convention)
        assert "aggregation" not in f
        assert c["formula_id"] == "formula_My Calc" and c["properties"]["aggregation"] == "SUM"
        _, ca = formula_tml_entries("Flag", "[T::a] > 1", "ATTRIBUTE")
        assert "aggregation" not in ca["properties"]

    def test_tml_snippet_is_yaml(self):
        import yaml
        snip = tml_snippet("My Calc", "sum ( [T::a] )", "MEASURE")
        assert snip.startswith("formulas:")
        data = yaml.safe_load(snip)
        assert data["formulas"][0]["expr"] == "sum ( [T::a] )"


# ---------------------------------------------------------------------------
# Detection corpus — including the must-ask ties (spec §4, §8)
# ---------------------------------------------------------------------------

DETECT_CORPUS = [
    ("{FIXED [Region] : SUM([Sales])}", "tableau"),
    ("IF [Profit] > 0 THEN 'Gain' ELSE 'Loss' END", "tableau"),
    ("ZN(SUM([Sales])) / COUNTD([Customer])", "tableau"),
    ("DATEDIFF('day', [Order Date], [Ship Date])", "tableau"),
    ("CALCULATE(SUM(Sales[Amount]), ALL(Sales[Region]))", "dax"),
    ("DIVIDE(SUM('Sales Table'[Amount]), DISTINCTCOUNT('Sales Table'[Customer]))", "dax"),
    ("VAR x = SUM(Sales[Amount]) RETURN x * 2", "dax"),
    ("Sum({<Year={2024}>} Sales)", "qlik"),
    ("Aggr(Sum(Sales), Region)", "qlik"),
    ("RangeSum(Above(Sum(Sales), 0, 3))", "qlik"),
    ("YTDSUM([rev])", "sisense"),
    ("DateDiff(\"day\", [Orders/Order Date], [Orders/Ship Date])", "sigma"),
    ("DIV0(SUM(amount), COUNT(*))", "snowflake"),
    ("TO_VARCHAR(order_date)", "snowflake"),
    ("DATEDIFF(\"day\", [Order Date], [Ship Date])", "tableau"),
    ("datediff(ship_date, order_date)", "databricks"),
    ("SUM(`amount`)", "databricks"),
    ("date_add(order_date, 7)", "databricks"),
]

DETECT_TIES = [
    ("=SUMIFS(C:C, A:A, \"East\")", {"excel", "google_sheets", "omni_table_calc"}),
    ("SUM(B2:B10)", {"excel", "google_sheets", "omni_table_calc"}),
    ("${orders.amount} * 2", {"lookml", "omni"}),
    ("CASE WHEN a > 1 THEN 1 ELSE 0 END", {"snowflake", "databricks"}),
    # Databricks has IFF, :: and DATEDIFF(unit, …) too: shared signals never settle the pair
    ("IFF(status = 'X', amount, 0)", {"snowflake", "databricks"}),
    ("DATEADD(day, 7, order_date)", {"snowflake", "databricks"}),
    ("amount::FLOAT / qty", {"snowflake", "databricks"}),
    # [A/B] alone is weak evidence: asked, not confirmed
    ("[Orders/Revenue] * 2", {"sigma"}),
    ("SUM([Sales])", {"tableau", "dax", "qlik", "sisense", "sigma"}),
    ("sum(amount)", {"snowflake", "databricks", "qlik"}),
]


class TestDetect:
    @pytest.mark.parametrize("expr,expected", DETECT_CORPUS)
    def test_corpus(self, expr, expected):
        r = detect(expr)
        assert r["best"] == expected, r
        assert r["ambiguous"] is False

    @pytest.mark.parametrize("expr,tied", DETECT_TIES)
    def test_ties_are_returned_not_picked(self, expr, tied):
        r = detect(expr)
        assert r["ambiguous"] is True and r["best"] is None
        assert set(r["ask"]) == tied

    def test_no_signal(self):
        r = detect("1 + 1")
        assert r["ambiguous"] is True and r["ask"] == [] and r["candidates"] == []

    def test_backing(self):
        c = {x["dialect"]: x for x in detect("${orders.amount}")["candidates"]}
        assert c["omni"]["backing"] == "map" and c["lookml"]["backing"] == "none"


# ---------------------------------------------------------------------------
# Google Sheets — signals, collisions and the delta-map routing (BL-338)
# ---------------------------------------------------------------------------

_REPO = __import__("pathlib").Path(__file__).resolve().parents[3]

SHEETS_STRONG = [
    '=QUERY(A1:D100, "select A, sum(D) group by A")',
    "=ARRAYFORMULA(A2:A * B2:B)",
    'IMPORTRANGE("https://docs.google.com/x", "Sheet1!A1:C10")',
    'IMPORTDATA("https://example.com/x.csv")',
    'IMPORTHTML("https://example.com", "table", 1)',
    'IMPORTXML("https://example.com", "//a")',
    'GOOGLEFINANCE("NASDAQ:GOOG")',
    'GOOGLETRANSLATE(name, "en", "fr")',
    "SPARKLINE(B2:B20)",
    'REGEXMATCH(name, "^A")',
    "COUNTUNIQUE(customer)",
    'COUNTUNIQUEIFS(customer, region, "East")',
    "EPOCHTODATE(ts, 2)",
    "TO_PERCENT(ratio)", "TO_DOLLARS(amount)", "TO_TEXT(amount)", "TO_PURE_NUMBER(amount)",
    "ISEMAIL(contact)", "ISURL(site)",
    "SORTN(data, 5)",
    *[f"{op}(a, b)" for op in ("ADD", "MULTIPLY", "EQ", "NE", "GT", "GTE", "LT", "LTE")],
    "UMINUS(a)", "UPLUS(a)",
    # colliding names, settled by spreadsheet context
    "=TO_DATE(A2)", '=SPLIT(A2, ",")', '=JOIN(",", A2:A10)', "=FLATTEN(A2:B10)",
    "=DIVIDE(A2, B2)", "=MINUS(A2, B2)",
]

# Must NOT route to Sheets: these names belong to another supported dialect too.
SHEETS_COLLISIONS = [
    ("TO_DATE(order_date)", {"snowflake", "databricks", "qlik"}),
    ("SPLIT(s, ',')", {"snowflake", "databricks", "qlik"}),
    ("split(tags, ',')", {"snowflake", "databricks", "qlik"}),
    ("FLATTEN(input => arr)", None),
    ("DIVIDE(SUM(Sales[Amount]), SUM(Sales[Qty]))", "dax"),
    ("DIVIDE([Profit], [Revenue])", None),
    ("ISDATE([Order Date])", None),
]


class TestSheets:
    def test_sheets_only_matches_the_map(self):
        """SHEETS_ONLY is the map's rowed names minus the shared names it reconciles."""
        import re as _re
        from ts_cli.formula_translate.detect import SHEETS_ONLY
        text = (_REPO / "docs/function-maps/ts-sheets-function-mapping.md").read_text()
        rowed = set(_re.findall(r"^\| `([A-Z][A-Z0-9_.]*)\(", text, _re.M))
        recon = text.split("## Same as the Excel map (reconciliation)", 1)[1]
        shared_line = next(ln for ln in recon.splitlines() if ln.startswith("(`"))
        shared = set(_re.findall(r"`([A-Z][A-Z0-9_.]*)`", shared_line))
        assert len(shared) == 17, shared
        assert rowed - shared == SHEETS_ONLY
        assert len(SHEETS_ONLY) == 46

    @pytest.mark.parametrize("expr", SHEETS_STRONG)
    def test_strong_signal_routes_to_sheets(self, expr):
        r = detect(expr)
        assert r["best"] == "google_sheets" and r["ambiguous"] is False, r

    @pytest.mark.parametrize("expr,expected", SHEETS_COLLISIONS)
    def test_collisions_do_not_route_to_sheets(self, expr, expected):
        r = detect(expr)
        assert r["best"] != "google_sheets" and r["guess"] != "google_sheets", r
        assert "google_sheets" not in r["ask"], r
        if isinstance(expected, str):
            assert r["best"] == expected
        elif expected:
            assert r["ambiguous"] and set(r["ask"]) == expected

    def test_shared_names_are_not_sheets_evidence(self):
        # REGEXEXTRACT / REGEXREPLACE are Excel 365 functions too: still the must-ask family
        r = detect('=REGEXEXTRACT(A2, "[0-9]+")')
        assert r["ambiguous"] and set(r["ask"]) == {"excel", "google_sheets", "omni_table_calc"}

    def test_routing_reads_sheets_map_first_then_excel(self):
        c = {x["dialect"]: x for x in detect('=QUERY(A1:D9, "select A")')["candidates"]}
        assert c["google_sheets"]["map"] == "docs/function-maps/ts-sheets-function-mapping.md"
        assert c["google_sheets"]["fallback_map"] == "docs/function-maps/ts-excel-function-mapping.md"
        assert c["excel"]["map"] == "docs/function-maps/ts-excel-function-mapping.md"
        assert "fallback_map" not in c["excel"]
        for x in ("google_sheets", "excel"):
            assert (_REPO / c[x]["map"]).is_file()
            assert c[x]["backing"] == "translator"  # the map is the NEEDS_REVIEW fallback

    def test_fallback_map_rows_a_name_the_delta_does_not(self):
        """E1: VLOOKUP has no Sheets row, so it is read from the Excel row."""
        sheets = (_REPO / "docs/function-maps/ts-sheets-function-mapping.md").read_text()
        excel = (_REPO / "docs/function-maps/ts-excel-function-mapping.md").read_text()
        assert "| `VLOOKUP(" not in sheets and "`VLOOKUP`" in sheets
        assert "| `VLOOKUP(" in excel


# ---------------------------------------------------------------------------
# Validation — scratch TML + cleanup under simulated failures
# ---------------------------------------------------------------------------

class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status
        self.ok = 200 <= status < 300
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeClient:
    """Simulates the endpoints validate.py calls. Knobs make each step fail."""

    def __init__(self, *, validate_error=None, import_error=None, gen_error=None,
                 fetch_error=None, delete_fails=False, import_omits_guid=False):
        self.validate_error, self.import_error = validate_error, import_error
        self.gen_error, self.fetch_error = gen_error, fetch_error
        self.delete_fails, self.import_omits_guid = delete_fails, import_omits_guid
        self.objects: dict[str, str] = {}  # guid -> name
        self.calls: list[tuple[str, dict]] = []
        self.policies: list[str] = []

    def post(self, path, json=None, raise_for_status=True):
        self.calls.append((path, json))
        if path.endswith("/tml/export"):
            return FakeResp([{"edoc": __import__("json").dumps(MODEL)},
                             {"edoc": __import__("json").dumps(TABLES[0])}])
        if path.endswith("/tml/import"):
            policy = json["import_policy"]
            self.policies.append(policy)
            if policy == "VALIDATE_ONLY":
                if self.validate_error:
                    return FakeResp([{"response": {"status": {"status_code": "ERROR",
                                     "error_code": 14516, "error_message": self.validate_error}}}])
                return FakeResp([{"response": {"status": {"status_code": "OK"},
                                 "header": {"id_guid": "phantom"}}}])
            if self.import_error:
                return FakeResp([{"response": {"status": {"status_code": "ERROR",
                                 "error_code": 1, "error_message": self.import_error}}}])
            doc = __import__("json").loads(json["metadata_tmls"][0])
            guid = f"scratch-{len(self.objects) + 1}"
            self.objects[guid] = doc["model"]["name"]
            header = {} if self.import_omits_guid else {"id_guid": guid}
            return FakeResp([{"response": {"status": {"status_code": "OK"}, "header": header}}])
        if path.endswith("/metadata/search"):
            f = json["metadata"][0]
            if "identifier" in f:
                g = f["identifier"]
                return FakeResp([{"metadata_id": g, "metadata_name": self.objects[g]}]
                                if g in self.objects else [])
            return FakeResp([{"metadata_id": g, "metadata_name": n}
                             for g, n in self.objects.items() if n == f["name_pattern"]])
        if path.endswith("/metadata/delete"):
            if self.delete_fails:
                return FakeResp({"error": "boom"}, status=500)
            for m in json["metadata"]:
                self.objects.pop(m["identifier"], None)
            return FakeResp({}, status=204)
        if path.endswith("generate-sql"):
            if self.gen_error:
                return FakeResp({"error": {"message": {"debug": f"[BAD] {self.gen_error}"}}}, 400)
            return FakeResp({"executable_sql": "SELECT 1"})
        if path.endswith("fetch-data"):
            if self.fetch_error:
                return FakeResp({"error": {"message": {"debug": f"[BAD] {self.fetch_error}"}}}, 400)
            return FakeResp({"query_result": {"results": []}})
        raise AssertionError(f"unexpected path {path}")


class TestScratchTml:
    def test_scratch_name(self):
        n = scratch_name(0)
        assert n.startswith(SCRATCH_PREFIX) and n.endswith(SCRATCH_SUFFIX)
        assert n == "ZZ_FORMULA_PROBE_19700101T000000_DELETE_ME"

    def test_build_drops_guid_renames_and_appends(self):
        doc = build_scratch_model(MODEL, "Probe", "sum ( [ORDERS::AMOUNT] )", "MEASURE", "ZZ_X")
        assert "guid" not in doc and doc["model"]["name"] == "ZZ_X"
        assert doc["model"]["formulas"][-1] == {"id": "formula_Probe", "name": "Probe",
                                                "expr": "sum ( [ORDERS::AMOUNT] )"}
        assert doc["model"]["columns"][-1]["formula_id"] == "formula_Probe"
        # the source fixture is untouched
        assert MODEL["guid"] and MODEL["model"]["name"] == "Orders Model"
        assert len(MODEL["model"]["formulas"]) == 2

    def test_name_clash_refused(self):
        with pytest.raises(ValidationError):
            build_scratch_model(MODEL, "Amount", "1", "ATTRIBUTE", "ZZ_X")

    def test_not_a_model(self):
        with pytest.raises(ValidationError):
            build_scratch_model({"worksheet": {}}, "P", "1", "ATTRIBUTE", "ZZ_X")

    def test_group_attribute_and_statement(self):
        assert pick_group_attribute(MODEL, "Probe") == "Region"
        s = agentql_statement("ZZ_X", "Probe", "MEASURE", "AGG", "Region", limit=5)
        assert s == ('SELECT "t1"."Region" AS "g", AGG("t1"."Probe") AS "v" FROM "ZZ_X" AS "t1" '
                     'GROUP BY "t1"."Region" LIMIT 5')
        # ONE formula per query: no other measure is selected
        assert s.count("AGG(") == 1 and "SUM(" not in s
        a = agentql_statement("ZZ_X", "Flag", "ATTRIBUTE", None, None)
        assert a == 'SELECT "t1"."Flag" AS "v" FROM "ZZ_X" AS "t1" GROUP BY "t1"."Flag"'

    def test_measure_without_group_column(self):
        with pytest.raises(ValidationError):
            agentql_statement("ZZ_X", "P", "MEASURE", "AGG", None)


class TestValidator:
    def _run(self, client, level="execute", expr="sum ( [ORDERS::AMOUNT] )", role="MEASURE"):
        return Validator(client).run(level, MODEL, "Probe", expr, role, "AGG", name="ZZ_T")

    def test_export_model(self):
        model, tables = Validator(FakeClient()).export_model(MODEL["guid"])
        assert model["model"]["name"] == "Orders Model" and tables[0]["table"]["name"] == "ORDERS"

    def test_compile_uses_validate_only_and_creates_nothing(self):
        c = FakeClient()
        out = self._run(c, level="compile")
        assert out["result"] == "OK" and c.policies == ["VALIDATE_ONLY"] and not c.objects
        assert "scratch" not in out

    def test_compile_failure_verbatim(self):
        c = FakeClient(validate_error="Formula addition failed. Formula: Probe, Error: Unknown data type.")
        out = self._run(c, level="compile")
        assert out["result"] == "FAILED" and "Unknown data type" in out["error"]

    def test_execute_ok_and_cleaned(self):
        c = FakeClient()
        out = self._run(c)
        assert out["result"] == "OK" and out["sql"] == "SELECT 1"
        assert c.policies == ["VALIDATE_ONLY", "ALL_OR_NONE"]
        assert out["scratch"]["confirmed_absent"] is True and not c.objects
        fetch = [j for p, j in c.calls if p.endswith("fetch-data")][0]
        assert fetch["spotql_query"].endswith("LIMIT 5")

    def test_execute_stops_before_import_on_validate_failure(self):
        c = FakeClient(validate_error="bad")
        out = self._run(c)
        assert out["result"] == "FAILED" and c.policies == ["VALIDATE_ONLY"] and not c.objects

    def test_import_failure_still_sweeps_by_name(self):
        c = FakeClient(import_error="nope")
        c.objects["leaked"] = "ZZ_T"  # an object the failed import left behind
        out = self._run(c)
        assert out["result"] == "FAILED" and "nope" in out["error"]
        assert out["scratch"]["confirmed_absent"] is True and not c.objects

    def test_query_failure_cleans_up(self):
        c = FakeClient(gen_error="[ca_3] is not a valid group by expression")
        out = self._run(c)
        assert out["result"] == "FAILED" and "group by" in out["error"]
        assert not c.objects and out["scratch"]["confirmed_absent"]

    def test_fetch_failure_cleans_up(self):
        c = FakeClient(fetch_error="warehouse down")
        out = self._run(c)
        assert out["result"] == "FAILED" and not c.objects

    def test_delete_failure_reports_guid(self):
        c = FakeClient(delete_fails=True)
        out = self._run(c)
        sc = out["scratch"]
        assert sc["confirmed_absent"] is False and sc["remaining"] == ["scratch-1"]
        assert "scratch-1" in c.objects

    def test_import_without_guid_found_by_name(self):
        c = FakeClient(import_omits_guid=True)
        out = self._run(c)
        assert out["result"] == "OK" and out["scratch"]["guid"] == "scratch-1" and not c.objects

    def test_exception_mid_run_still_cleans(self):
        c = FakeClient()
        orig = c.post

        def boom(path, json=None, raise_for_status=True):
            if path.endswith("generate-sql"):
                raise RuntimeError("network")
            return orig(path, json=json, raise_for_status=raise_for_status)
        c.post = boom
        out = Validator(c).run("execute", MODEL, "Probe", "sum ( [ORDERS::AMOUNT] )",
                               "MEASURE", "AGG", name="ZZ_T")
        assert out["result"] == "ERROR" and "network" in out["error"]
        assert not c.objects and out["scratch"]["confirmed_absent"]

    def test_delete_failure_logs_guid(self):
        logged = []
        c = FakeClient(delete_fails=True)
        Validator(c, log=logged.append).run("execute", MODEL, "Probe", "sum ( [ORDERS::AMOUNT] )",
                                            "MEASURE", "AGG", name="ZZ_T")
        assert any("scratch-1" in m and "ts metadata delete" in m for m in logged)

    def test_search_failure_during_cleanup_is_not_absent(self):
        logged = []
        c = FakeClient()
        orig = c.post
        state = {"imported": False}

        def flaky(path, json=None, raise_for_status=True):
            if path.endswith("/tml/import") and json["import_policy"] == "ALL_OR_NONE":
                state["imported"] = True
            if path.endswith("/metadata/search") and state["imported"]:
                raise RuntimeError("search down")
            return orig(path, json=json, raise_for_status=raise_for_status)
        c.post = flaky
        out = Validator(c, log=logged.append).run("execute", MODEL, "Probe", "1", "ATTRIBUTE",
                                                  None, name="ZZ_T")
        assert out["scratch"]["confirmed_absent"] is False
        assert out["scratch"]["remaining"] == ["scratch-1"] and logged

    def test_ctrl_c_during_cleanup_logs_and_reraises(self):
        logged = []
        c = FakeClient()
        orig = c.post

        def interrupt(path, json=None, raise_for_status=True):
            if path.endswith("/metadata/delete"):
                raise KeyboardInterrupt
            return orig(path, json=json, raise_for_status=raise_for_status)
        c.post = interrupt
        with pytest.raises(KeyboardInterrupt):
            Validator(c, log=logged.append).run("execute", MODEL, "Probe", "1", "ATTRIBUTE",
                                                None, name="ZZ_T")
        assert any("scratch-1" in m for m in logged)


# ---------------------------------------------------------------------------
# CLI wiring (no network)
# ---------------------------------------------------------------------------

class TestCli:
    def test_translate_and_detect_commands(self):
        from typer.testing import CliRunner
        from ts_cli.cli import app

        runner = CliRunner()
        r = runner.invoke(app, ["formula", "translate", "COUNTD([c])", "--from", "tableau"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.stdout)["formula"] == "unique count ( [TABLE::c])"
        assert json.loads(r.stdout)["formula_editor"] == "unique count ( c)"
        r = runner.invoke(app, ["formula", "translate", "--from", "snowflake"], input="SUM(x)\n")
        assert json.loads(r.stdout)["formula"] == "sum ( [TABLE::x] )"
        r = runner.invoke(app, ["formula", "detect", "{FIXED [a] : SUM([b])}"])
        assert json.loads(r.stdout)["best"] == "tableau"

    def test_validate_needs_model(self):
        from typer.testing import CliRunner
        from ts_cli.cli import app

        r = CliRunner().invoke(app, ["formula", "translate", "SUM(x)", "--from", "snowflake",
                                     "--validate", "compile"])
        assert r.exit_code == 2

    def test_bad_columns_json(self):
        from typer.testing import CliRunner
        from ts_cli.cli import app

        r = CliRunner().invoke(app, ["formula", "translate", "SUM(x)", "--from", "snowflake",
                                     "--columns", "[1]"])
        assert r.exit_code == 2


class TestThoughtSpotIdentity:
    def test_resolves_refs_translates_nothing(self):
        r = translate("round ( sum ( [Amount] ) , 0.01 )", "thoughtspot", model_ctx())
        assert r["formula"] == "round ( sum ( [ORDERS::AMOUNT] ) , 0.01 )"
        assert not any("increment" in t for t in r["traps"])  # no false round trap
        assert r["verification"]["translator"] is None

    def test_placeholder_table_resolves_at_level2(self):
        r = translate("sum ( [TABLE::Amount] )", "thoughtspot", model_ctx())
        assert r["formula"] == "sum ( [ORDERS::AMOUNT] )" and not r["unresolved"]


# ---------------------------------------------------------------------------
# Review round 2 (2026-10-06): known defects, output guard, dialect fixes
# ---------------------------------------------------------------------------

class TestKnownDefects:
    def test_databricks_datediff_fixed_by_bl336(self):
        r = translate("datediff(ship_date, order_date)", "databricks")
        assert r["status"] == TRANSLATED
        assert r["formula"] == "diff_days ( [TABLE::ship_date] , [TABLE::order_date] )"

    def test_qlik_weekday_needs_first_week_day(self):
        assert translate("WeekDay(OrderDate)", "qlik")["status"] == NEEDS_REVIEW
        r = translate("WeekDay(OrderDate)", "qlik", first_week_day=6)
        assert r["status"] == TRANSLATED and "day_number_of_week" in r["formula"]

    @pytest.mark.parametrize("dialect,src", [
        ("snowflake", "DAYOFWEEK(order_date)"),
        ("databricks", "dayofweek(order_date)"),
        ("tableau", "DATEPART('weekday', [Order Date])"),
    ])
    def test_weekday_fixed_by_bl334_now_translates_with_week_trap(self, dialect, src):
        # #565 fixed the translators, so the defect entries are gone; the Monday-week
        # assumption still shows as a trap.
        r = translate(src, dialect)
        assert r["status"] == TRANSLATED and "mod" in r["formula"]
        assert any("Monday week start" in t for t in r["traps"])

    def test_zeroifnull_is_ifnull(self):
        # BL-226: ZEROIFNULL was a rename to the uncatalogued `zeroifnull`
        r = translate("ZEROIFNULL(SUM(amount))", "snowflake")
        assert r["status"] == TRANSLATED and "ifnull ( sum (" in r["formula"]

    @pytest.mark.parametrize("dialect,src", [
        ("snowflake", "name ILIKE '%abc%'"), ("snowflake", "name NOT ILIKE 'a%'"),
        ("snowflake", "name RLIKE 'a.*'"), ("databricks", "name ilike 'a%'"),
        ("databricks", "name LIKE 'a%'"),
    ])
    def test_like_family_is_a_passthrough(self, dialect, src):
        # BL-362: the warehouse's own operator, exact (case-sensitive LIKE stays so)
        r = translate(src, dialect)
        assert r["status"] == TRANSLATED and r["formula"].startswith("sql_bool_op ("), r

    def test_zn_stripped_is_approximated(self):
        r = translate("ZN(SUM([Profit])) / SUM([Sales])", "tableau")
        assert r["status"] == APPROXIMATED and any("ZN()" in t for t in r["traps"])


class TestOutputGuard:
    @pytest.mark.parametrize("dialect,src,why", [
        # an unknown keyword operator is refused, never read as a column (BL-360)
        ("snowflake", "name SIMILAR TO 'a%'", "SIMILAR"),
        ("databricks", "name REGEXP 'a.*'", "REGEXP"),
        ("databricks", "I1 DIV2 3", "DIV2"),
        ("qlik", "Sum(Sales)/Sum(TOTAL Sales)", "TOTAL"),
        ("dax", 'IF(Sales[Name] == "Bob", 1, 0)', "=="),
        ("tableau", "LEFT([Customer Name], 3) + '...'", "concat"),
        ("tableau", "RUNNING_SUM(SUM([Sales]))", "RUNNING_SUM"),
    ])
    def test_invalid_output_is_needs_review(self, dialect, src, why):
        r = translate(src, dialect)
        assert r["status"] == NEEDS_REVIEW and r["formula"] is None
        assert any(why in n for n in r["notes"]), r["notes"]

    def test_unknown_and_rejected_functions(self):
        from ts_cli.formula_translate.traps import output_guard
        assert output_guard("zeroifnull ( [T::a] )")
        assert output_guard("Sum ( [T::a] )")  # case matters: untranslated source
        assert output_guard('sql_number_aggregate_op ( "SUM({0})" , [T::a] )')  # OI-5
        assert output_guard("zeroifnull ( [T::a] )", allow=frozenset({"zeroifnull"})) is None
        assert output_guard("unique count ( [T::a] ) / count ( [T::b] )") is None
        assert output_guard('if ( sql_bool_op ( "{0} = {1}" , [T::a] , \'x\' ) ) then 1 else 0') is None

    def test_keyword_named_column_is_fine(self):
        # a bracketed column called End / Over Budget is a column, not an operator
        assert translate("DATEDIFF('day', [start], [end])", "tableau")["status"] == TRANSLATED
        for src in ("SUM([Over Budget])", "SUM([Distinct Users])", "[Partition By Region]"):
            assert translate(src, "tableau")["status"] == TRANSLATED, src

    @pytest.mark.parametrize("dialect,src", [
        ("snowflake", "-- total\nSUM(amount)"),
        ("snowflake", "SUM(amount) /* x */"),
        ("tableau", "// c\nSUM([Sales])"),
        ("dax", "SUM(Sales[Amount]) // c"),
    ])
    def test_comments_stripped(self, dialect, src):
        r = translate(src, dialect)
        assert r["status"] == TRANSLATED and "--" not in r["formula"]
        assert any("comments were removed" in n for n in r["notes"])

    def test_comment_marker_inside_literal_kept(self):
        r = translate("CASE WHEN a = '--x' THEN 1 ELSE 0 END", "snowflake")
        assert "'--x'" in r["formula"]


class TestDialectFixes:
    def test_qlik_double_quoted_field(self):
        r = translate('Sum("Sales Amount")', "qlik")
        assert r["formula"] == "sum([TABLE::Sales Amount])"
        assert translate("If(Region = 'East', 1, 0)", "qlik")["formula"].count("'East'") == 1

    def test_tableau_if_without_else_is_null(self):
        r = translate("IF [City] = 'Zürich' THEN 1 END", "tableau")
        assert r["formula"] == "if ( [TABLE::City] = 'Zürich' ) then 1 else null"
        r2 = translate("IF [a] > 1 THEN 'x' ELSEIF [a] > 0 THEN 'y' END", "tableau")
        assert r2["formula"].endswith("else null")
        r3 = translate("IF [a] > 1 THEN 1 ELSE 0 END", "tableau")
        assert "null" not in r3["formula"]

    def test_round_trap_needs_two_args(self):
        assert not any("increment" in t for t in translate("ROUND([Sales])", "tableau")["traps"])
        assert not any("increment" in t for t in translate("ROUND(amount)", "snowflake")["traps"])

    def test_case_trap_on_column_comparison(self):
        r = translate("[First Name] = [Nick Name]", "tableau")
        assert any("text columns" in t for t in r["traps"])


class TestCatalog:
    def test_vendored_catalog_matches_formula_patterns(self):
        import sys
        from pathlib import Path
        from ts_cli.formula_translate.catalog import CATALOG, NONEXISTENT
        root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(root / "tools" / "validate"))
        from check_formula_catalog import parse_catalog
        text = (root / "agents/shared/schemas/thoughtspot-formula-patterns.md").read_text()
        valid, nonexistent = parse_catalog(text)
        assert CATALOG == frozenset(valid), "regenerate formula_translate/catalog.py CATALOG"
        assert NONEXISTENT == frozenset(nonexistent)


class TestEditorForm:
    """Two forms per formula: TML (bracketed, required in formulas[]) and editor (bare)."""

    def test_bare_names_in_editor_brackets_in_tml(self):
        r = translate("ROUND(SUM(amount), 2)", "snowflake")
        assert r["formula"] == "round ( sum ( [TABLE::amount] ) , 0.01 )"
        assert r["formula_editor"] == "round ( sum ( amount ) , 0.01 )"
        assert any("domain guidance" in n for n in r["formula_editor_notes"])

    def test_name_with_spaces_stays_bracketed_with_rename_note(self):
        r = translate("DATEDIFF('day', [Order Date], [Ship Date])", "tableau")
        assert r["formula_editor"] == "diff_days ( [Ship Date] , [Order Date] )"
        assert any("underscores" in n and "'Ship Date'" in n for n in r["formula_editor_notes"])

    def test_level2_uses_model_display_names_and_formula_names(self):
        r = translate('ROUND("Total Sales", 2) + amount', "snowflake", model_ctx())
        assert r["formula"] == "round ( [formula_Total Sales] , 0.01 ) + [ORDERS::AMOUNT]"
        assert r["formula_editor"] == "round ( [Total Sales] , 0.01 ) + Amount"

    def test_coined_default_name_uses_underscores(self):
        r = translate("SUM(x)", "snowflake")
        assert r["name"] == "Translated_Formula"
        assert "id: formula_Translated_Formula" in r["tml"]

    def test_literals_untouched(self):
        r = translate("CASE WHEN a = '[x]' THEN 1 ELSE 0 END", "snowflake")
        assert "'[x]'" in r["formula_editor"] and "'[x]'" in r["formula"]

    def test_placeholder_key_not_listed_as_a_rename(self):
        r = translate("COUNT(*)", "snowflake")
        assert r["formula_editor"] == "count ( [<primary key>] )"
        assert len(r["formula_editor_notes"]) == 1


class TestNullifRefused:
    """BL-339: `nullif` is not a ThoughtSpot function (VALIDATE_ONLY 2026-10-06, probe §7)."""

    def test_catalog_does_not_know_nullif(self):
        from ts_cli.formula_translate.catalog import is_known
        assert not is_known("nullif")
        assert not is_known("null_if")
        assert is_known("least") and is_known("safe_divide")

    def test_output_guard_rejects_nullif(self):
        from ts_cli.formula_translate.traps import output_guard
        assert "nullif" in output_guard("[T::a] / nullif ( [T::b] , 0 )")

    def test_thoughtspot_input_using_nullif_is_needs_review(self):
        r = translate("[a] / nullif ( [b] , 0 )", "thoughtspot")
        assert r["status"] == "NEEDS_REVIEW" and r["formula"] is None

    def test_snowflake_nullif_non_zero_is_case_form(self):
        r = translate("NULLIF(a, b)", "snowflake")
        assert r["formula"] == "( if ( [TABLE::a] = [TABLE::b] ) then null else [TABLE::a] )"


class TestFidelityM0SnowflakeFixes:
    """BL-340..343 through the engine: status, classification and traps."""

    def test_substr_folded_is_translated(self):
        r = translate("SUBSTR(s, 2, 3)", "snowflake")
        assert r["formula"] == "substr ( [TABLE::s] , 1 , 3 )"
        assert r["status"] == TRANSLATED

    def test_datediff_year_is_diff_years(self):
        r = translate("DATEDIFF(year, a, b)", "snowflake")
        assert r["formula"] == "diff_years ( [TABLE::b] , [TABLE::a] )"
        assert r["status"] == TRANSLATED

    def test_datediff_week_is_a_pass_through(self):
        r = translate("DATEDIFF(week, a, b)", "snowflake")
        assert r["formula"] == 'sql_int_op ( "DATEDIFF(week, {0}, {1})" , [TABLE::a] , [TABLE::b] )'
        assert r["classification"] == "passthrough"

    def test_diff_weeks_output_still_carries_the_week_start_trap(self):
        from ts_cli.formula_translate.traps import detect_traps
        traps = detect_traps("tableau", "DATEDIFF('week', [a], [b])",
                             "diff_weeks ( [T::b] , [T::a] )")
        # One coherent trap: the shared week note's diff_weeks clause (BL-334 review),
        # not a second, separately worded diff_weeks line.
        week = [t for t in traps if "diff_weeks" in t and "Monday" in t]
        assert len(week) == 1 and "FIXED Monday" in week[0]

    @pytest.mark.parametrize("src", ["MONTHS_BETWEEN(b, a)", "TO_CHAR(d, 'YYYY-MM')",
                                     "SUBSTR(s, -2, 1)"])
    def test_pass_throughs_are_classified_passthrough(self, src):
        r = translate(src, "snowflake")
        assert r["status"] == TRANSLATED and r["classification"] == "passthrough"
        assert r["formula"].startswith("sql_") and "diff_months" not in r["formula"]


class TestQlikFieldQuotesShared:
    """BL-368: the field-quote rewrite moved into ``qlik.functions.translate``; the adapter
    must not re-apply it (a second pass would be a no-op, but one owner keeps the two paths
    from drifting)."""

    def test_adapter_and_translator_agree(self):
        from ts_cli.qlik.functions import translate as qlik_translate
        assert qlik_translate('Sum("Sales Amount")')[0] == "sum([Sales Amount])"
        assert translate('Sum("Sales Amount")', "qlik")["formula"] == \
            "sum([TABLE::Sales Amount])"

    def test_adapter_no_longer_carries_its_own_rewrite(self):
        from ts_cli.formula_translate import adapters
        assert not hasattr(adapters, "qlik_field_quotes")

    def test_double_quote_in_single_quoted_literal_untouched(self):
        r = translate("If(Region = 'say \"hi\"', 1, 0)", "qlik")
        assert "'say \"hi\"'" in r["formula"]


class TestQuoteInsideBracketRef:
    """BL-369: a bracketed reference whose name holds an apostrophe is code, not the
    start of a string literal, so its reference is still recorded."""

    def test_dax_doubled_apostrophe_table(self):
        r = translate("SUM('Bob''s Sales'[x])", "dax")
        assert r["formula"] == "sum([Bob's Sales::x])"
        assert [x["source"] for x in r["references"]] == ["Bob's Sales.x"]

    def test_apostrophe_ref_before_a_literal(self):
        r = translate("IF('Bob''s Sales'[x] > 1, \"a\", \"b\")", "dax")
        assert [x["source"] for x in r["references"]] == ["Bob's Sales.x"]
        assert "'a'" in r["formula"] and "'b'" in r["formula"]

    def test_split_literals_keeps_bracket_in_code(self):
        from ts_cli.formula_translate.refs import split_literals
        assert split_literals("[Bob's x] = 'it''s'") == [
            (False, "[Bob's x] = "), (True, "'it''s'")]
        assert split_literals("'a[b' + [c]") == [(True, "'a[b'"), (False, " + [c]")]


class TestCotZeroTrap:
    """BL-370: COT(x) -> 1 / tan ( x ) is NULL at x = 0 in ThoughtSpot (NULL-safe
    division) where the source errors or returns infinity. Informational, not a
    downgrade: the status stays TRANSLATED."""

    @pytest.mark.parametrize("dialect,src", [
        ("tableau", "COT([x])"), ("snowflake", "COT(x)"), ("databricks", "COT(x)"),
    ])
    def test_cot_carries_zero_trap_without_downgrade(self, dialect, src):
        r = translate(src, dialect)
        assert r["status"] == TRANSLATED
        assert "tan" in r["formula"]
        assert any("BL-370" in t for t in r["traps"])

    def test_no_trap_without_cot_in_source(self):
        assert not any("BL-370" in t for t in translate("TAN([x])", "tableau")["traps"])
        assert not any("BL-370" in t for t in translate("ACOS([x])", "tableau")["traps"])

    def test_cot_inside_a_literal_does_not_fire(self):
        r = translate("IF [s] = 'cot(' THEN TAN([x]) END", "tableau")
        assert not any("BL-370" in t for t in r["traps"])


class TestPr583ReviewFixes:
    """Independent review of #583: the adapter-side and scanner-side halves of BL-368/369,
    plus the pre-existing silent wrong answers it found next to them."""

    def test_dax_adapter_reads_doubled_apostrophe_dates(self):
        ctx = ColumnContext(parse_columns_json(
            '[{"source": "Ship", "table": "T", "column": "SHIP", "data_type": "DATE"},'
            ' {"source": "Order", "table": "T", "column": "ORD", "data_type": "DATE"}]'), level=1)
        r = translate("'Bob''s Sales'[Ship] - 'Bob''s Sales'[Order]", "dax", ctx)
        assert r["formula"] == "diff_days([T::SHIP], [T::ORD])"
        assert r["status"] == TRANSLATED

    def test_qlik_apostrophe_field_concat(self):
        r = translate('"Bob\'s" & \' - \' & "Region"', "qlik")
        assert r["formula"] == "concat ( [TABLE::Bob's] , ' - ' , [TABLE::Region] )"
        assert r["status"] == TRANSLATED

    def test_sql_comment_stripping_reads_literals_inside_brackets(self):
        from ts_cli.formula_translate.engine import strip_comments
        assert strip_comments("v['a--b'] + 1", "snowflake") == ("v['a--b'] + 1", False)
        assert strip_comments("v['a--b'] + 1 -- c", "databricks")[0].rstrip() == "v['a--b'] + 1"

    @pytest.mark.parametrize("src", ['Sum("a]b")', 'Sum("")', 'Sum("x'])
    def test_qlik_unreadable_double_quoted_name_needs_review(self, src):
        assert translate(src, "qlik")["status"] == NEEDS_REVIEW

    @pytest.mark.parametrize("src", [
        'Sum({<Year={2023}, Region={"A"}>} Sales)',
        'Sum({<Year={2023}>}"Sales") / Sum({1} "Sales")',
        "Sum({1} Sales) / Sum(Sales)",
    ])
    def test_qlik_set_analysis_shapes_it_cannot_read_need_review(self, src):
        assert translate(src, "qlik")["status"] == NEEDS_REVIEW

    def test_qlik_one_field_several_values_still_translates(self):
        r = translate('Sum({<Region={"A","B"}>} Sales)', "qlik")
        assert r["status"] == TRANSLATED
        assert "'A'" in r["formula"] and "'B'" in r["formula"]

    def test_tableau_apostrophe_in_field_name_is_not_a_string(self):
        r = translate("[Bob's Sales] + [Tax]", "tableau")
        assert r["formula"] == "[TABLE::Bob's Sales] + [TABLE::Tax]"
        assert "concat" not in translate("[Bob's Sales] + [Tax]", "tableau")["formula"]
        assert translate("[Name] + 'x'", "tableau")["formula"].startswith("concat")


class TestStripCommentsPerDialect:
    """#583 re-review: only SQL reads ``[…]`` as a subscript holding a real literal; in
    Tableau, Qlik and DAX a ``[…]`` is a field whose name may hold a quote."""

    @pytest.mark.parametrize("dialect,src,kept", [
        ("tableau", "[Bob's] + 'x' // note", "[Bob's] + 'x'"),
        ("qlik", "Sum([Bob's]) // it's", "Sum([Bob's])"),
        ("dax", "SUM([Bob's]) // it's", "SUM([Bob's])"),
    ])
    def test_bracket_names_with_quotes(self, dialect, src, kept):
        from ts_cli.formula_translate.engine import strip_comments
        out, removed = strip_comments(src, dialect)
        assert removed and out.rstrip() == kept

    @pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
    def test_sql_subscript_literal(self, dialect):
        from ts_cli.formula_translate.engine import strip_comments
        assert strip_comments("v['a--b'] + 1", dialect) == ("v['a--b'] + 1", False)

    def test_end_to_end(self):
        r = translate("[Bob's] + 'x' // note", "tableau")
        assert r["status"] != NEEDS_REVIEW and "concat" in r["formula"]
        r = translate("Sum([Bob's]) // it's", "qlik")
        assert r["formula"] == "sum([TABLE::Bob's])"


class TestBl375To379:
    def test_dax_not_is_an_operator_not_a_table(self):  # BL-375
        r = translate("NOT [Flag]", "dax")
        assert r["formula"] == "not [TABLE::Flag]"
        assert "[not::" not in translate("x && NOT [Flag]", "dax")["formula"]

    def test_dax_var_return_needs_review(self):
        assert translate("VAR a = 1 RETURN [M]", "dax")["status"] == NEEDS_REVIEW

    def test_qlik_search_string_needs_review(self):  # BL-377
        assert translate('Sum({<Year={">=2020<=2023"}>} Sales)', "qlik")["status"] == NEEDS_REVIEW

    def test_qlik_bracketed_modifier_field(self):  # BL-378
        r = translate('Sum({<[Field Name]={"x"}>} Sales)', "qlik")
        assert r["formula"] == "sum(if ([TABLE::Field Name] = 'x') then [TABLE::Sales] else 0)"

    def test_tableau_if_without_else_on_an_apostrophe_field(self):  # BL-379
        r = translate("IF [Bob's] = 'a' THEN 1 END", "tableau")
        assert r["formula"] == "if ( [TABLE::Bob's] = 'a' ) then 1 else null"
        assert r["formula"].count("else") == 1


class TestQlikSetAnalysisNote:
    def test_case_note_reaches_notes_without_downgrading(self):
        r = translate("Sum({<Region={'A'}>} Sales)", "qlik")
        assert r["status"] == TRANSLATED
        assert any("BL-333" in n for n in r["notes"])
