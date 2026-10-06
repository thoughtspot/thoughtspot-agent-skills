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
        with pytest.raises(ValueError):
            normalise_dialect("excel")  # map-backed in v1: the skill, not the CLI

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
        r2 = translate("IF(Sales[Status] = \"Open\", 1, 0)", "dax")  # DAX is case-insensitive
        assert not any("case-INSENSITIVE" in t for t in (r2["traps"] or []))

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
    ("IFF(status = 'X', amount, 0)", "snowflake"),
    ("DATEADD(day, 7, order_date)", "snowflake"),
    ("amount::FLOAT / qty", "snowflake"),
    ("SUM(`amount`)", "databricks"),
    ("date_add(order_date, 7)", "databricks"),
]

DETECT_TIES = [
    ("=SUMIFS(C:C, A:A, \"East\")", {"excel", "google_sheets", "omni_table_calc"}),
    ("SUM(B2:B10)", {"excel", "google_sheets", "omni_table_calc"}),
    ("${orders.amount} * 2", {"lookml", "omni"}),
    ("CASE WHEN a > 1 THEN 1 ELSE 0 END", {"snowflake", "databricks"}),
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
        v = Validator(c)
        with pytest.raises(RuntimeError):
            v.run("execute", MODEL, "Probe", "sum ( [ORDERS::AMOUNT] )", "MEASURE", "AGG", name="ZZ_T")
        assert not c.objects


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
