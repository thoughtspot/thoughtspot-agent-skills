"""Unit tests for ts_cli.link_build — the pure builder behind `ts link build`."""
import pytest

from ts_cli.link_build import (
    LinkSpecError, build_link_tml, diff_column_roles, humanize, infer_aggregation,
    map_data_type, normalize_aggregation,
)


def _spec(columns, **extra):
    base = {"connection": "TS-DBX", "db": "cat", "schema": "sch", "db_table": "sales_mv",
            "columns": columns}
    base.update(extra)
    return base


DIM = {"name": "region", "data_type": "string", "kind": "dimension", "description": "Sales region"}
REV = {"name": "revenue_gbp", "data_type": "decimal(28,2)", "kind": "measure",
       "expr": "SUM(revenue)", "description": "Revenue", "synonyms": ["sales", " "]}


class TestMapDataType:
    @pytest.mark.parametrize("raw,expected", [
        ("string", "VARCHAR"), ("VARCHAR(255)", "VARCHAR"), ("bigint", "INT64"),
        ("decimal(28,2)", "DOUBLE"), ("NUMBER(38,0)", "INT64"), ("number", "INT64"),
        ("decimal", "INT64"), ("number(38)", "INT64"), ("NUMERIC(10,00)", "INT64"),
        ("decimal(10, 2)", "DOUBLE"),
        ("timestamp_ltz", "DATE_TIME"), ("TIMESTAMP_NTZ(9)", "DATE_TIME"), ("date", "DATE"),
        ("boolean", "BOOL"), ("INT64", "INT64"), ("DATE_TIME", "DATE_TIME"),
    ])
    def test_known(self, raw, expected):
        assert map_data_type(raw) == expected

    @pytest.mark.parametrize("raw", ["array<string>", "struct<a:int>", "variant", "", None])
    def test_unsupported(self, raw):
        assert map_data_type(raw) is None


class TestInferAggregation:
    @pytest.mark.parametrize("expr,expected", [
        ("SUM(x)", "SUM"), ("  sum ( line_total ) ", "SUM"),
        ("COUNT(DISTINCT customer_id)", "COUNT_DISTINCT"), ("count(x)", "COUNT"),
        ("AVG(price)", "AVERAGE"), ("MAX(dt)", "MAX"), ("STDDEV(x)", "STD_DEVIATION"),
        ("SUM(CASE WHEN a = 'x' THEN b ELSE 0 END)", "SUM"),
        ("SUM(x) FILTER (WHERE y = 1)", "SUM"),
        ("COUNT(DISTINCT(x))", "COUNT_DISTINCT"),
        ("SUM(CASE WHEN a = ')' THEN b END)", "SUM"),
        ("SUM(x) FILTER (WHERE y = ')')", "SUM"),
        ("SUM(x) FILTER (WHERE y = 1) / SUM(z)", None),
    ])
    def test_outer(self, expr, expected):
        assert infer_aggregation(expr) == expected

    @pytest.mark.parametrize("expr", [
        "SUM(a) / SUM(b)", "SUM(a) * 100.0", "ROUND(SUM(a), 2)", "a + b", "", None,
        "SUM(SUM(a)) OVER ()", "SUM(DISTINCT x)", "AVG(DISTINCT x)",
    ])
    def test_compound_is_none(self, expr):
        assert infer_aggregation(expr) is None


def test_normalize_aggregation_aliases():
    assert normalize_aggregation("unique count") == "COUNT_DISTINCT"
    assert normalize_aggregation("avg") == "AVERAGE"
    assert normalize_aggregation("sum") == "SUM"
    assert normalize_aggregation("median-ish") is None


def test_humanize():
    assert humanize("revenue_gbp") == "Revenue GBP"
    assert humanize("dm_order.employee_count") == "Employee Count"
    assert humanize("order_id") == "Order ID"


class TestBuildAggregateMode:
    def test_roles_and_aggregation(self):
        t, m, r = build_link_tml(_spec([DIM, REV]), aggregation_mode="aggregate", model_name="Sales")
        tcols = {c["name"]: c for c in t["table"]["columns"]}
        assert tcols["region"]["properties"] == {"column_type": "ATTRIBUTE"}
        assert tcols["revenue_gbp"]["properties"] == {
            "column_type": "MEASURE", "aggregation": "AGGREGATE", "index_type": "DONT_INDEX"}
        # db_column_name always present (TML invariant)
        assert all(c["db_column_name"] == c["name"] for c in t["table"]["columns"])
        assert t["table"]["connection"] == {"name": "TS-DBX"}
        assert r["measures"] == 1 and r["attributes"] == 1

    def test_thin_model_no_formulas_no_joins(self):
        _, m, _ = build_link_tml(_spec([DIM, REV]), aggregation_mode="aggregate", model_name="Sales")
        model = m["model"]
        assert "formulas" not in model
        assert model["model_tables"] == [{"name": "sales_mv"}]
        assert {c["column_id"] for c in model["columns"]} == {"sales_mv::region", "sales_mv::revenue_gbp"}
        assert model["properties"]["spotter_config"] == {"is_spotter_enabled": True}

    def test_metadata_carried_to_model(self):
        rev = dict(REV, ai_context="Primary revenue measure")
        _, m, r = build_link_tml(_spec([DIM, rev], description="Obj desc"),
                                 aggregation_mode="aggregate", model_name="Sales")
        mc = {c["column_id"]: c for c in m["model"]["columns"]}["sales_mv::revenue_gbp"]
        assert mc["name"] == "Revenue GBP"
        assert mc["description"] == "Revenue"
        assert mc["properties"]["synonyms"] == ["sales"]  # blank synonym dropped
        assert mc["properties"]["synonym_type"] == "USER_DEFINED"
        assert mc["properties"]["ai_context"] == "Primary revenue measure"
        assert m["model"]["description"] == "Obj desc"
        assert r["with_synonyms"] == 1 and r["with_ai_context"] == 1

    def test_non_numeric_measure_skipped(self):
        last = {"name": "last_available_date", "data_type": "date", "kind": "measure",
                "expr": "MAX(dt)"}
        t, m, r = build_link_tml(_spec([DIM, REV, last]), aggregation_mode="aggregate", model_name="S")
        assert "last_available_date" not in {c["name"] for c in t["table"]["columns"]}
        assert [s["name"] for s in r["skipped"]] == ["last_available_date"]

    def test_instructions_go_to_report_not_tml(self):
        _, m, r = build_link_tml(_spec([DIM, REV], instructions="Use geo dims for sessions."),
                                 aggregation_mode="aggregate", model_name="S")
        assert "model_instructions" not in m["model"]
        assert r["instructions"] == ["Use geo dims for sessions."]

    def test_table_name_override(self):
        t, m, _ = build_link_tml(_spec([DIM, REV]), aggregation_mode="aggregate",
                                 model_name="S", table_name="Sales MV")
        assert t["table"]["name"] == "Sales MV" and t["table"]["db_table"] == "sales_mv"
        assert m["model"]["columns"][0]["column_id"].startswith("Sales MV::")


class TestBuildStandardMode:
    def test_inferred_and_explicit(self):
        cnt = {"name": "employee_count", "data_type": "bigint", "kind": "measure",
               "expr": "COUNT(DISTINCT emp_id)"}
        avg = {"name": "avg_price", "data_type": "double", "kind": "measure", "aggregation": "avg"}
        t, _, r = build_link_tml(_spec([DIM, REV, cnt, avg]), aggregation_mode="standard", model_name="S")
        aggs = {c["name"]: c["properties"].get("aggregation") for c in t["table"]["columns"]}
        assert aggs == {"region": None, "revenue_gbp": "SUM", "employee_count": "COUNT_DISTINCT",
                        "avg_price": "AVERAGE"}
        assert r["aggregation_source"] == {"explicit": 1, "inferred": 2}

    def test_uninferable_fails_without_default(self):
        ratio = {"name": "cvr", "data_type": "double", "kind": "measure", "expr": "SUM(a) / SUM(b)"}
        with pytest.raises(LinkSpecError, match="cvr: no aggregation"):
            build_link_tml(_spec([DIM, ratio]), aggregation_mode="standard", model_name="S")

    def test_default_aggregation_fallback(self):
        ratio = {"name": "cvr", "data_type": "double", "kind": "measure", "expr": "SUM(a) / SUM(b)"}
        t, _, r = build_link_tml(_spec([DIM, ratio]), aggregation_mode="standard", model_name="S",
                                 default_aggregation="AVERAGE")
        assert t["table"]["columns"][1]["properties"]["aggregation"] == "AVERAGE"
        assert r["aggregation_source"] == {"default": 1}

    def test_explicit_wins_over_expr(self):
        m = dict(REV, aggregation="max")
        t, _, _ = build_link_tml(_spec([m]), aggregation_mode="standard", model_name="S")
        assert t["table"]["columns"][0]["properties"]["aggregation"] == "MAX"


class TestValidation:
    def test_missing_object_fields(self):
        with pytest.raises(LinkSpecError, match="connection"):
            build_link_tml({"db": "a", "schema": "b", "db_table": "c", "columns": [DIM]},
                           aggregation_mode="aggregate", model_name="S")

    def test_duplicate_names(self):
        with pytest.raises(LinkSpecError, match="duplicate"):
            build_link_tml(_spec([DIM, DIM]), aggregation_mode="aggregate", model_name="S")

    def test_bad_kind_and_type_collected_together(self):
        bad = [{"name": "a", "data_type": "array<int>", "kind": "measure"},
               {"name": "b", "data_type": "string", "kind": "metric"}]
        with pytest.raises(LinkSpecError) as exc:
            build_link_tml(_spec(bad), aggregation_mode="aggregate", model_name="S")
        assert "a: unsupported" in str(exc.value) and "b: kind" in str(exc.value)

    def test_bad_mode(self):
        with pytest.raises(LinkSpecError, match="aggregation mode"):
            build_link_tml(_spec([DIM]), aggregation_mode="sum", model_name="S")


class TestDisplayNames:
    def test_collision_falls_back_to_full_name(self):
        a = {"name": "dm_order.id", "data_type": "bigint", "kind": "attribute"}
        b = {"name": "dm_customer.id", "data_type": "bigint", "kind": "attribute"}
        _, m, _ = build_link_tml(_spec([a, b]), aggregation_mode="aggregate", model_name="S")
        names = [c["name"] for c in m["model"]["columns"]]
        assert names == ["ID", "Dm Customer ID"]

    def test_raw_and_explicit(self):
        a = dict(DIM, display_name="Sales Region")
        _, m, _ = build_link_tml(_spec([a, REV]), aggregation_mode="aggregate", model_name="S",
                                 naming="raw")
        assert [c["name"] for c in m["model"]["columns"]] == ["Sales Region", "revenue_gbp"]


def test_diff_column_roles_reports_coercion():
    expected = {"model": {"columns": [
        {"column_id": "t::a", "properties": {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT"}},
        {"column_id": "t::b", "properties": {"column_type": "ATTRIBUTE"}},
        {"column_id": "t::c", "properties": {"column_type": "ATTRIBUTE"}},
    ]}}
    exported = {"model": {"columns": [
        {"column_id": "t::a", "properties": {"column_type": "ATTRIBUTE"}},
        {"column_id": "t::b", "properties": {"column_type": "ATTRIBUTE", "index_type": "DONT_INDEX"}},
    ]}}
    diffs = diff_column_roles(expected, exported)
    assert {"column_id": "t::c", "issue": "missing after import"} in diffs
    assert {"column_id": "t::a", "field": "column_type", "expected": "MEASURE", "actual": "ATTRIBUTE"} in diffs
    assert {"column_id": "t::a", "field": "aggregation", "expected": "COUNT_DISTINCT", "actual": None} in diffs
    assert not any(d["column_id"] == "t::b" for d in diffs)


def test_existing_table_guid_parsed_from_refusal():
    from ts_cli.commands.link import _existing_table_guid
    msg = ("[0] Cannot create a new table as the table in the TML file already exists. "
           "Existing Table GUID: 39570acf-7364-4860-a1c4-599c4a9d75b3. Switch to Update existing")
    assert _existing_table_guid(msg) == "39570acf-7364-4860-a1c4-599c4a9d75b3"
    assert _existing_table_guid("some other failure") is None


def _names(cols, naming="humanize"):
    spec = _spec([dict({"data_type": "string", "kind": "attribute"}, **c) for c in cols])
    _, m, _ = build_link_tml(spec, aggregation_mode="aggregate", model_name="S", naming=naming)
    return [c["name"] for c in m["model"]["columns"]]


class TestDisplayNameUniqueness:
    @pytest.mark.parametrize("cols,naming", [
        ([{"name": "revenue"}, {"name": "x", "display_name": "Revenue"}], "humanize"),
        ([{"name": "revenue_id"}, {"name": "Revenue ID"}], "humanize"),
        ([{"name": "Revenue"}, {"name": "revenue"}], "humanize"),
        ([{"name": "x", "display_name": "y"}, {"name": "y"}], "humanize"),
        ([{"name": "a.revenue"}, {"name": "b.revenue"}, {"name": "A Revenue"}], "humanize"),
        ([{"name": "a"}, {"name": "b", "display_name": "a"}], "raw"),
    ])
    def test_always_unique_case_insensitive(self, cols, naming):
        names = _names(cols, naming)
        assert len({n.lower() for n in names}) == len(names), names

    def test_explicit_display_name_wins(self):
        names = _names([{"name": "revenue"}, {"name": "x", "display_name": "Revenue"}])
        assert names[1] == "Revenue" and names[0] != "Revenue"

    def test_explicit_clash_is_an_error(self):
        with pytest.raises(LinkSpecError, match="display_name"):
            _names([{"name": "a", "display_name": "Same"}, {"name": "b", "display_name": "same"}])


class TestMalformedSpec:
    @pytest.mark.parametrize("spec", [
        [],
        {"connection": "c", "db": "d", "schema": "s", "db_table": "t", "columns": ["x"]},
        {"connection": "c", "db": "d", "schema": "s", "db_table": "t", "columns": [{"name": ["x"]}]},
        _spec([dict(DIM, ai_context=5)]),
        _spec([dict(DIM, description=["a"])]),
        _spec([DIM], instructions=5),
        _spec([dict(DIM, synonyms={"a": 1})]),
    ])
    def test_raises_link_spec_error_not_traceback(self, spec):
        with pytest.raises(LinkSpecError):
            build_link_tml(spec, aggregation_mode="aggregate", model_name="S")


def test_synonyms_normalized():
    _, m, _ = build_link_tml(_spec([dict(DIM, synonyms="area"), dict(REV, name="r2", synonyms=[1, None, " x "])]),
                             aggregation_mode="aggregate", model_name="S")
    props = [c["properties"] for c in m["model"]["columns"]]
    assert props[0]["synonyms"] == ["area"]
    assert props[1]["synonyms"] == ["1", "x"]


def test_default_aggregation_ignored_in_aggregate_mode():
    t, _, _ = build_link_tml(_spec([REV]), aggregation_mode="aggregate", model_name="S",
                             default_aggregation="bogus")
    assert t["table"]["columns"][0]["properties"]["aggregation"] == "AGGREGATE"


def test_count_distinct_warns():
    cnt = {"name": "n", "data_type": "bigint", "kind": "measure", "expr": "COUNT(DISTINCT x)"}
    _, _, r = build_link_tml(_spec([cnt]), aggregation_mode="standard", model_name="S")
    assert r["warnings"] and "COUNT_DISTINCT" in r["warnings"][0]


def test_diff_treats_omitted_sum_as_default():
    expected = {"model": {"columns": [
        {"column_id": "t::a", "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}]}}
    exported = {"model": {"columns": [{"column_id": "t::a", "properties": {"column_type": "MEASURE"}}]}}
    assert diff_column_roles(expected, exported) == []
