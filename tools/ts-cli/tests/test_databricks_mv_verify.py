"""Tests for `ts databricks verify` (BL-639): the plan in `ts_cli/databricks/mv_verify.py`,
the comparison in `mv_verify_compare.py`, and the command in
`commands/databricks_verify.py` with its three executors replaced by fakes that answer
from one synthetic fact table.

No live calls. Every name here is synthetic.
"""
import copy
import datetime as dt
import json
import re
from zoneinfo import ZoneInfo

import pytest
import yaml

from ts_cli.cli import app
from ts_cli.commands import databricks_verify as verify_mod
from ts_cli.commands import load_databricks as load_mod
from ts_cli.databricks import mv_verify as mv
from ts_cli.databricks import mv_verify_compare as mvc

from runners import msg_runner, runner  # noqa: E402  (BL-139)

UTC = ZoneInfo("UTC")
TOKYO = ZoneInfo("Asia/Tokyo")
INTEGER = {"kind": "integer", "scale": None}
FLOAT = {"kind": "float", "scale": None}
STRING = {"kind": "string", "scale": None}


def _dec(scale):
    return {"kind": "decimal", "scale": scale}


# ---------------------------------------------------------------------------
# Plan fixture: one of each kind of measure and dimension
# ---------------------------------------------------------------------------

PLAN_PARSED = {
    "dimensions": [
        {"name": "order_date", "display_name": "Order Date"},
        {"name": "region"},
        {"name": "is_returned"},
        {"name": "Has Coupon"},
        {"name": "priority_order"},
        {"name": "warehouse_code"},          # skipped by the converter
        {"name": "ship_mode"},               # missing: not skipped, not in the Model
        {"name": "units"},                   # a MEASURE column in the Model
    ],
    "measures": [
        {"name": "revenue"},
        {"name": "avg_price"},
        {"name": "order_count"},
        {"name": "closing_balance", "window": {"order": "order_date"}},
        {"name": "price_sd"},
        {"name": "margin"},                  # skipped by the converter
        {"name": "discount"},                # missing
        {"name": "unique_buyers"},
        {"name": "tax_total", "display_name": "Tax total"},   # Model spells it "Tax Total"
        {"name": "segment_label"},           # an ATTRIBUTE column in the Model
    ],
}

PLAN_TRANSLATED = {"skipped": [
    {"name": "margin", "role": "measure", "reason": "unsupported"},
    {"name": "warehouse_code", "role": "dimension", "reason": "unsupported"},
    {"name": "MV Filter", "role": "filter", "reason": "unsupported"},
]}


def _col(name, ctype, agg=None, formula_id=None):
    col = {"name": name, "properties": {"column_type": ctype}}
    if agg:
        col["properties"]["aggregation"] = agg
    if formula_id:
        col["formula_id"] = formula_id
    else:
        col["column_id"] = f"F::{name.upper().replace(' ', '_')}"
    return col


PLAN_MODEL = {"model": {
    "name": "Sales MV",
    "formulas": [
        {"id": "f_oc", "name": "Order Count", "expr": "count ( 1 )"},
        {"id": "f_cb", "name": "Closing Balance",
         "expr": "last_value ( sum ( [F::BAL] ) , query_groups ( ) , { [F::D] } )"},
        {"id": "f_po", "name": "Priority Order",
         "expr": "sql_bool_op ( \"{0} > 3\" , [F::PRI] )"},
        {"id": "f_ub", "name": "Unique Buyers", "expr": "unique count ( [F::BUYER] )"},
    ],
    "columns": [
        _col("Order Date", "ATTRIBUTE"), _col("Region", "ATTRIBUTE"),
        _col("Is Returned", "ATTRIBUTE"), _col("Has Coupon", "ATTRIBUTE"),
        _col("Priority Order", "ATTRIBUTE", formula_id="f_po"),
        _col("Units", "MEASURE", "SUM"),
        _col("Revenue", "MEASURE", "SUM"), _col("Avg Price", "MEASURE", "AVERAGE"),
        _col("Order Count", "MEASURE", "SUM", formula_id="f_oc"),
        _col("Closing Balance", "MEASURE", "SUM", formula_id="f_cb"),
        _col("Price Sd", "MEASURE", "STD_DEVIATION"),
        _col("Unique Buyers", "MEASURE", "SUM", formula_id="f_ub"),
        _col("Tax Total", "MEASURE", "SUM"),
        _col("Segment Label", "ATTRIBUTE"),
    ],
}}


@pytest.fixture
def plan():
    return mv.build_plan(PLAN_PARSED, PLAN_MODEL, PLAN_TRANSLATED)


class TestPlan:
    def test_measures_and_their_agentql_wrappers(self, plan):
        got = {m["mv_name"]: (m["title"], m["agentql"]) for m in plan["measures"]}
        assert got == {
            "revenue": ("Revenue", "SUM"),
            "avg_price": ("Avg Price", "AVG"),          # a raw AVERAGE column, not SUM
            "order_count": ("Order Count", "AGG"),
            "closing_balance": ("Closing Balance", "SUM"),   # semi-additive last_value
            "unique_buyers": ("Unique Buyers", "AGG"),
            "tax_total": ("Tax Total", "SUM"),     # matched ignoring case, Model's spelling
        }

    def test_skipped_by_converter_and_missing(self, plan):
        assert plan["skipped_by_converter"] == {"measures": ["margin"],
                                                "dimensions": ["warehouse_code"]}
        assert plan["missing"] == {"measures": ["discount"], "dimensions": ["ship_mode"]}

    def test_without_translated_every_absent_entry_is_missing(self):
        p = mv.build_plan(PLAN_PARSED, PLAN_MODEL)
        assert p["missing"]["measures"] == ["margin", "discount"]
        assert p["skipped_by_converter"] == {"measures": [], "dimensions": []}

    def test_wrong_column_type(self, plan):
        assert plan["wrong_column_type"] == [
            {"mv_name": "segment_label", "title": "Segment Label", "role": "measure",
             "column_type": "ATTRIBUTE"},
            {"mv_name": "units", "title": "Units", "role": "dimension",
             "column_type": "MEASURE"}]

    def test_problems_fail_on_missing_and_wrong_type_not_on_skips(self, plan):
        problems = mv.plan_problems(plan)
        assert len(problems) == 4
        assert any("discount" in p for p in problems)
        assert any("ship_mode" in p for p in problems)
        assert not any("margin" in p or "warehouse_code" in p for p in problems)

    def test_stddev_column_is_not_verifiable(self, plan):
        assert [(u["mv_name"], "STD_DEVIATION" in u["reason"])
                for u in plan["not_verifiable"]] == [("price_sd", True)]

    def test_flags_by_name_and_by_sql_bool_op(self, plan):
        flags = {d["mv_name"]: d["flag"] for d in plan["dimensions"]}
        assert flags == {"order_date": False, "region": False, "is_returned": True,
                         "Has Coupon": True, "priority_order": True}

    def test_window_order_dimension_reported(self, plan):
        assert plan["order_dimensions"] == [{"mv_name": "order_date", "in_model": True}]

    @pytest.mark.parametrize("name,title,expr,want", [
        ("is_active", "Is Active", "", True),
        ("IS_ACTIVE", "Is Active", "", True),
        ("x", "Is Active", "", True),
        ("has_coupon", "Has Coupon", "", True),
        ("island", "Island", "", False),
        ("isolation_level", "Isolation Level", "", False),
        ("hash_key", "Hash Key", "", False),
        ("late", "Late", "  SQL_BOOL_OP ( \"{0}\" , [T::c] )", True),
        ("late", "Late", "if ( [T::c] > 1 ) then true else false", False),
    ])
    def test_is_flag_dimension(self, name, title, expr, want):
        assert mv.is_flag_dimension(name, title, expr) is want

    @pytest.mark.parametrize("agg,want", [
        ("SUM", "SUM"), ("AVERAGE", "AVG"), ("MIN", "MIN"), ("MAX", "MAX"),
        ("COUNT", "COUNT"), ("COUNT_DISTINCT", "COUNT(DISTINCT)"), ("VARIANCE", None),
    ])
    def test_raw_measure_wrapper(self, agg, want):
        fn, reason = mv.agentql_function({"kind": "raw_measure", "aggregation": agg})
        assert fn == want and (reason is None) == (want is not None)

    def test_model_differences(self):
        imported = copy.deepcopy(PLAN_MODEL)
        cols = imported["model"]["columns"]
        cols[:] = [c for c in cols if c["name"] != "Region"]
        next(c for c in cols if c["name"] == "Revenue")["properties"]["aggregation"] = "MAX"
        cols.append(_col("Extra", "ATTRIBUTE"))
        assert mv.model_differences(PLAN_MODEL, imported) == [
            "column 'Region' is in --model-tml but not in the imported Model",
            "column 'Extra' is in the imported Model but not in --model-tml",
            "column 'Revenue': --model-tml has ('MEASURE', 'SUM'), the imported Model "
            "('MEASURE', 'MAX')"]

    def test_model_differences_none_when_defaults_only_differ(self):
        imported = copy.deepcopy(PLAN_MODEL)
        for c in imported["model"]["columns"]:
            if c["properties"].get("aggregation") == "SUM":
                del c["properties"]["aggregation"]          # SUM is the default
        assert mv.model_differences(PLAN_MODEL, imported) == []


class TestShapes:
    def test_default_shapes(self, plan):
        shapes = mv.default_shapes(plan)
        assert [s["label"] for s in shapes] == [
            "total", "by Order Date", "by Region", "by Is Returned", "by Has Coupon",
            "by Priority Order",
            "Is Returned = true", "Is Returned = false",
            "Has Coupon = true", "Has Coupon = false",
            "Priority Order = true", "Priority Order = false",
        ]
        assert shapes[6] == {"label": "Is Returned = true", "dims": [],
                             "filter": ["is_returned", "true"], "flag": "is_returned"}

    @pytest.mark.parametrize("values,kind,want", [
        (["West", "East", None, "East"], "string", "'East'"),
        (["East"], "string", None),                 # the only value: equals the total
        ([None, None], "string", None),
        (["O'Brien", "Smith"], "string", "'Smith'"),   # quotes escape differently per side
        (["a\\b", "c"], "string", "'c'"),
        (["east", "East", "West"], "string", "'West'"),   # AgentQL would match both cases
        (["east", "East"], "string", None),
        (["", "B", "A"], "string", "'A'"),           # never the empty string
        ([" East", "West"], "string", "'West'"),     # never a value with outer spaces
        (["7", "12", "7"], "integer", "7"),
        (["7"], "integer", None),
        (["2024-02-29", "2024-01-31"], "date", "TO_DATE('2024-01-31')"),
        (["1.5", "2.5"], "float", None),
    ])
    def test_pick_filter_literal(self, values, kind, want):
        assert mv.pick_filter_literal(values, kind) == want

    def test_search_filter_prefers_strings_then_integers_then_dates(self):
        dims = [{"mv_name": "d", "title": "D"}, {"mv_name": "n", "title": "N"},
                {"mv_name": "s", "title": "S"}]
        values = {"d": ("date", ["2024-01-31", "2024-02-29"]), "n": ("integer", ["2", "1"]),
                  "s": ("string", ["x", "y"])}
        assert mv.search_filter_shape(dims, values)[0]["filter"] == ["s", "'x'"]
        values["s"] = ("string", ["only"])
        assert mv.search_filter_shape(dims, values)[0]["filter"] == ["n", "1"]
        values["n"] = ("integer", ["1"])
        assert mv.search_filter_shape(dims, values)[0]["filter"] == [
            "d", "TO_DATE('2024-01-31')"]

    def test_search_filter_reason_when_nothing_qualifies(self):
        shape, reason = mv.search_filter_shape(
            [{"mv_name": "s", "title": "S"}], {"s": ("string", ["only"])})
        assert shape is None and "two usable values" in reason

    def test_parse_shapes_valid(self, plan):
        raw = [{"label": "r x d", "dims": ["region", "order_date"], "filter": None},
               {"label": "east", "dims": [], "filter": ["region", "'East'"]}]
        assert mv.parse_shapes(raw, plan) == raw

    @pytest.mark.parametrize("raw,needle", [
        ([], "non-empty"),
        ({"label": "x"}, "non-empty"),
        ([{"dims": []}], "label"),
        ([{"label": "x", "dims": "region"}], "dims"),
        ([{"label": "x", "dims": ["warehouse_code"]}], "warehouse_code"),
        ([{"label": "x", "dims": [], "filter": ["region"]}], "filter"),
        ([{"label": "x", "dims": [], "filter": ["nope", "1"]}], "nope"),
    ])
    def test_parse_shapes_rejects(self, plan, raw, needle):
        with pytest.raises(ValueError, match=needle):
            mv.parse_shapes(raw, plan)


class TestSql:
    MEASURES = [{"mv_name": "revenue", "title": "Revenue", "agentql": "SUM"},
                {"mv_name": "odd`name", "title": 'Odd "Name"', "agentql": "AGG"},
                {"mv_name": "buyers", "title": "Buyers", "agentql": "COUNT(DISTINCT)"}]
    TITLES = {"region": "Region", "is_returned": "Is Returned", "odd`dim": 'Odd "Dim"'}

    def test_databricks_total(self):
        sql = mv.databricks_sql("cat.sch.sales_mv", {"dims": [], "filter": None},
                                self.MEASURES[:1])
        assert sql == "SELECT MEASURE(`revenue`) AS `m0` FROM `cat`.`sch`.`sales_mv`"

    def test_databricks_grouped_filtered_and_escaped(self):
        shape = {"dims": ["region", "odd`dim"], "filter": ["is_returned", "false"]}
        sql = mv.databricks_sql("cat.sch.sales_mv", shape, self.MEASURES[:2])
        assert sql == ("SELECT `region`, `odd``dim`, MEASURE(`revenue`) AS `m0`, "
                       "MEASURE(`odd``name`) AS `m1` FROM `cat`.`sch`.`sales_mv` "
                       "WHERE `is_returned` = false GROUP BY ALL")

    def test_databricks_fqn_already_quoted_is_kept(self):
        sql = mv.databricks_sql("`cat`.`my sch`.`mv`", {"dims": [], "filter": None},
                                self.MEASURES[:1])
        assert sql.endswith("FROM `cat`.`my sch`.`mv`")

    def test_agentql_total(self):
        q = mv.agentql_sql("Sales MV", {"dims": [], "filter": None}, self.MEASURES, {})
        assert q == ('SELECT SUM("t1"."Revenue") AS "M0", AGG("t1"."Odd ""Name""") AS "M1", '
                     'COUNT(DISTINCT "t1"."Buyers") AS "M2" FROM "Sales MV" AS "t1"')

    def test_agentql_grouped_and_filtered(self):
        shape = {"dims": ["region", "odd`dim"], "filter": ["is_returned", "true"]}
        q = mv.agentql_sql('My "MV"', shape, self.MEASURES[:1], self.TITLES)
        assert q == ('SELECT "t1"."Region", "t1"."Odd ""Dim""", SUM("t1"."Revenue") AS "M0" '
                     'FROM "My ""MV""" AS "t1" WHERE "t1"."Is Returned" = true '
                     'GROUP BY "t1"."Region", "t1"."Odd ""Dim"""')

    def test_filter_literal_is_used_as_written_on_both_sides(self):
        shape = {"dims": [], "filter": ["region", "'East'"]}
        assert mv.databricks_sql("a.b.c", shape, self.MEASURES[:1]).endswith(
            "WHERE `region` = 'East'")
        assert mv.agentql_sql("M", shape, self.MEASURES[:1], self.TITLES).endswith(
            "WHERE \"t1\".\"Region\" = 'East'")


def _midnight(y, m, d, tz):
    return int(dt.datetime(y, m, d, tzinfo=tz).timestamp())


class TestNormalise:
    def test_date_epoch_seconds_decoded_in_cluster_zone(self):
        epoch = _midnight(2024, 3, 1, TOKYO)          # 2024-02-29 15:00 UTC
        assert mvc.norm_key(epoch, "date", TOKYO) == "2024-03-01"
        assert mvc.norm_key(epoch, "date", UTC) == "2024-02-29"   # wrong zone, wrong day

    def test_date_epoch_milliseconds(self):
        assert mvc.norm_key(_midnight(2024, 3, 1, TOKYO) * 1000, "date", TOKYO) == "2024-03-01"

    def test_date_before_1970(self):
        assert mvc.norm_key(_midnight(1965, 7, 4, UTC), "date", UTC) == "1965-07-04"

    def test_date_string_from_databricks(self):
        assert mvc.norm_key("2024-03-01", "date", TOKYO) == "2024-03-01"
        assert mvc.norm_key("2024-03-01T00:00:00.000Z", "date", TOKYO) == "2024-03-01"

    def test_timestamp_to_the_microsecond(self):
        when = dt.datetime(2024, 3, 1, 9, 30, 0, 123000, tzinfo=TOKYO)
        epoch_ms = int(when.timestamp() * 1000)
        assert mvc.norm_key(epoch_ms, "timestamp", TOKYO) == "2024-03-01 09:30:00.123000"
        assert mvc.norm_key("2024-03-01T00:30:00.123Z", "timestamp", TOKYO) == \
            "2024-03-01 09:30:00.123000"
        assert mvc.norm_key("2024-03-01T00:30:00.124Z", "timestamp", TOKYO) != \
            mvc.norm_key(epoch_ms, "timestamp", TOKYO)
        assert mvc.norm_key("2024-03-01 09:30:00", "timestamp", TOKYO) == \
            "2024-03-01 09:30:00.000000"

    def test_boolean_case_insensitive(self):
        assert mvc.norm_key(True, "boolean", UTC) == mvc.norm_key("true", "boolean", UTC)

    @pytest.mark.parametrize("a,b", [("1", 1), ("1.50", 1.5), ("1E+3", 1000),
                                     ("-0.0000001", -1e-7),
                                     ("12345678901234567", 12345678901234567)])
    def test_number_keys_agree(self, a, b):
        for kind in mvc.NUMBER_KINDS:
            assert mvc.norm_key(a, kind, UTC) == mvc.norm_key(b, kind, UTC)

    def test_null_and_strings(self):
        assert mvc.norm_key(None, "string", UTC) is None
        assert mvc.norm_key("East ", "string", UTC) == "East "


class TestCompareCells:
    def test_count_is_exact(self):
        assert mvc.compare_cells("1000000000", 999999999, INTEGER, UTC) == mvc.DIFFERENT
        assert mvc.compare_cells("1000000000", 1e9, INTEGER, UTC) == mvc.EQUAL

    def test_decimal_cent_at_a_trillion_differs(self):
        assert mvc.compare_cells("1000000000000.01", 1e12, _dec(2), UTC) == mvc.DIFFERENT

    def test_decimal_equal_at_its_scale_is_close(self):
        assert mvc.compare_cells("1234.50", 1234.5000000001, _dec(2), UTC) == mvc.CLOSE
        assert mvc.compare_cells("0.123457", 0.1234565, _dec(6), UTC) == mvc.CLOSE  # half up

    def test_decimal_without_scale_uses_1e_12(self):
        assert mvc.compare_cells("100", 100 + 1e-11, _dec(None), UTC) == mvc.CLOSE
        assert mvc.compare_cells("100", 100 + 1e-8, _dec(None), UTC) == mvc.DIFFERENT

    def test_double_summation_order_still_matches(self):
        assert mvc.compare_cells("0.3", 0.1 + 0.2, FLOAT, UTC) == mvc.CLOSE
        assert mvc.compare_cells("10.5", 10.6, FLOAT, UTC) == mvc.DIFFERENT

    @pytest.mark.parametrize("a,b", [("0042", "42"), ("1234.50", "1234.5"),
                                     ("TRUE", "true")])
    def test_string_measures_compare_as_exact_text(self, a, b):
        assert mvc.compare_cells(a, b, STRING, UTC) == mvc.DIFFERENT

    @pytest.mark.parametrize("a,b,want", [
        (None, None, mvc.EQUAL), (None, 0, mvc.DIFFERENT), ("0", None, mvc.DIFFERENT),
        ("NaN", float("nan"), mvc.EQUAL), ("Infinity", float("inf"), mvc.EQUAL),
        ("Infinity", 1e308, mvc.DIFFERENT),
    ])
    def test_nulls_and_specials(self, a, b, want):
        assert mvc.compare_cells(a, b, FLOAT, UTC) == want

    def test_date_measure(self):
        epoch = _midnight(2024, 3, 1, TOKYO)
        spec = {"kind": "date", "scale": None}
        assert mvc.compare_cells("2024-03-01", epoch, spec, TOKYO) == mvc.EQUAL
        assert mvc.compare_cells("2024-03-01", epoch, spec, UTC) == mvc.DIFFERENT


class TestDatabricksResult:
    def _resp(self, manifest_extra=None, **result_extra):
        manifest = {"schema": {"columns": [
            {"name": "d", "type_name": "DATE"}, {"name": "b", "type_name": "BOOLEAN"},
            {"name": "s", "type_name": "STRING"}, {"name": "n", "type_name": "LONG"},
            {"name": "m0", "type_name": "DECIMAL", "type_text": "DECIMAL(20,2)"},
            {"name": "m1", "type_name": "DECIMAL", "type_scale": 4},
            {"name": "m2", "type_name": "DOUBLE"}]}, **(manifest_extra or {})}
        return {"manifest": manifest,
                "result": {"data_array": [["2024-01-01", "true", "x", "3", "1.50", "2", "3"]],
                           **result_extra}}

    def test_specs_and_rows(self):
        specs, rows = mvc.databricks_result(self._resp(), 7)
        assert [s["kind"] for s in specs] == ["date", "boolean", "string", "integer",
                                              "decimal", "decimal", "float"]
        assert [s["scale"] for s in specs][4:6] == [2, 4]
        assert rows == [["2024-01-01", "true", "x", "3", "1.50", "2", "3"]]

    def test_chunked_result_refused(self):
        with pytest.raises(ValueError, match="3 chunks"):
            mvc.databricks_result(self._resp({"total_chunk_count": 3}), 7)

    def test_next_chunk_index_refused(self):
        with pytest.raises(ValueError, match="chunks"):
            mvc.databricks_result(self._resp(next_chunk_index=1), 7)

    def test_truncated_result_refused(self):
        with pytest.raises(ValueError, match="truncated"):
            mvc.databricks_result(self._resp({"truncated": True}), 7)

    def test_missing_schema_refused(self):
        with pytest.raises(ValueError, match="schema has 0 columns, expected 2"):
            mvc.databricks_result({"result": {"data_array": [["a", "1"]]}}, 2)

    def test_short_row_refused(self):
        resp = self._resp()
        resp["result"]["data_array"].append(["2024-01-01"])
        with pytest.raises(ValueError, match="a Databricks row has 1 values, expected 7"):
            mvc.databricks_result(resp, 7)


class TestCompareShape:
    MEASURES = [{"title": "Revenue"}, {"title": "Orders"}]
    SPECS = [STRING, {"kind": "date", "scale": None}, FLOAT, INTEGER]

    def _ts(self, rows, measures=(0, 1)):
        return [{"measures": list(measures), "rows": rows}]

    def test_match_with_null_key_and_date_key(self):
        epoch = _midnight(2024, 3, 1, TOKYO)
        dbx = [["East", "2024-03-01", "10.5", "2"], [None, "2024-03-01", "1", "1"]]
        ts = [[None, epoch, 1.0, 1], ["East", epoch, 10.5, 2]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, TOKYO)
        assert r == {"rows_databricks": 2, "rows_thoughtspot": 2, "cells": 4,
                     "non_null_cells": 4, "tolerance_accepted": 0, "mismatch_count": 0,
                     "mismatches": []}

    def test_tolerance_accepted_is_counted(self):
        dbx = [["East", "2024-03-01", "0.3", "2"]]
        ts = [["East", "2024-03-01", 0.1 + 0.2, 2]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert (r["mismatch_count"], r["tolerance_accepted"]) == (0, 1)

    def test_count_off_by_one_at_a_billion(self):
        dbx = [["East", "2024-03-01", "1", "1000000000"]]
        ts = [["East", "2024-03-01", 1.0, 999999999]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert r["mismatches"] == [{"key": ["East", "2024-03-01"], "measure": "Orders",
                                    "databricks": "1000000000", "thoughtspot": 999999999}]

    def test_null_measure_is_not_zero(self):
        dbx = [["East", "2024-03-01", None, "2"]]
        ts = [["East", "2024-03-01", 0, 2]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert r["mismatch_count"] == 1

    def test_all_null_cells_count_as_no_data(self):
        dbx = [["East", "2024-03-01", None, None]]
        ts = [["East", "2024-03-01", None, None]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert (r["non_null_cells"], r["mismatch_count"]) == (0, 0)
        assert mvc.shape_status(r) == "no_data"

    def test_rows_on_one_side_only(self):
        dbx = [["East", "2024-03-01", "1", "1"], ["West", "2024-03-01", "1", "1"]]
        ts = [["East", "2024-03-01", 1, 1], ["North", "2024-03-01", 1, 1]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert [(m["key"][0], m["issue"]) for m in r["mismatches"]] == [
            ("North", "row only in ThoughtSpot"), ("West", "row only in Databricks")]

    def test_duplicate_key_reported(self):
        dbx = [["East", "2024-03-01", "1", "1"]]
        ts = [["east", "2024-03-01", 1, 1], ["east", "2024-03-01", 1, 1]]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert "duplicate key in the ThoughtSpot result" in [m.get("issue")
                                                              for m in r["mismatches"]]

    def test_short_thoughtspot_row_raises(self):
        with pytest.raises(ValueError, match="a ThoughtSpot row has 3 values, expected 4"):
            mvc.compare_shape(2, self.SPECS, [["East", "2024-03-01", "1", "1"]],
                              self._ts([["East", "2024-03-01", 1]]), self.MEASURES, UTC)

    def test_per_measure_blocks(self):
        dbx = [["East", "2024-03-01", "5", "2"]]
        blocks = [{"measures": [0], "rows": [["East", "2024-03-01", 5]]},
                  {"measures": [1], "rows": [["East", "2024-03-01", 3]]}]
        r = mvc.compare_shape(2, self.SPECS, dbx, blocks, self.MEASURES, UTC)
        assert r["cells"] == 2
        assert [m["measure"] for m in r["mismatches"]] == ["Orders"]

    def test_mismatch_list_is_capped_but_counted(self):
        dbx = [[f"k{i}", "2024-03-01", "1", "1"] for i in range(80)]
        r = mvc.compare_shape(2, self.SPECS, dbx, self._ts([]), self.MEASURES, UTC)
        assert r["mismatch_count"] == 80
        assert len(r["mismatches"]) == mvc.MAX_MISMATCHES_KEPT


class TestSummarise:
    MATCH = {"status": "match", "cells": 4, "non_null_cells": 4, "filter": None}
    FILTERED = {"status": "match", "cells": 1, "non_null_cells": 1, "filter": ["r", "'E'"]}

    def test_match(self):
        assert mvc.summarise([self.MATCH, self.FILTERED], [], True)["status"] == "match"

    def test_precedence(self):
        bad = {"status": "mismatch", "cells": 1, "non_null_cells": 1, "mismatch_count": 1}
        err = {"status": "error"}
        assert mvc.summarise([self.MATCH, bad, err], [], True)["status"] == "error"
        assert mvc.summarise([self.MATCH, bad], [], True)["status"] == "mismatch"
        assert mvc.summarise([self.MATCH, self.FILTERED], ["x"], True)["status"] == "mismatch"

    def test_no_data(self):
        empty = {"status": "no_data", "cells": 0, "non_null_cells": 0, "filter": None}
        assert mvc.summarise([empty], [], False)["status"] == "no_data"

    def test_incomplete_without_a_filtered_shape(self):
        assert mvc.summarise([self.MATCH], [], True)["status"] == "incomplete"
        assert mvc.summarise([self.MATCH], [], False)["status"] == "match"

    def test_summary_counts(self):
        out = mvc.summarise([self.MATCH, {"status": "skipped"}], [], False)["summary"]
        assert out == {"shapes": 2, "match": 1, "mismatch": 0, "error": 0, "skipped": 1,
                       "no_data": 0, "cells": 4, "non_null_cells": 4,
                       "tolerance_accepted": 0, "mismatches": 0, "problems": 0}


# ---------------------------------------------------------------------------
# Command: the executors answer from one synthetic fact table
# ---------------------------------------------------------------------------

FACT = [
    {"region": "East", "order_date": dt.date(2024, 1, 31), "returned": True, "is_gift": "Y",
     "store_no": 7, "revenue": 10.5},
    {"region": "East", "order_date": dt.date(2024, 2, 29), "returned": False, "is_gift": "N",
     "store_no": 7, "revenue": 4.0},
    {"region": "West", "order_date": dt.date(2024, 2, 29), "returned": False, "is_gift": "N",
     "store_no": 9, "revenue": 7.25},
    {"region": None, "order_date": dt.date(2024, 1, 31), "returned": False, "is_gift": "Y",
     "store_no": 9, "revenue": 1.0},
]
DBX_TYPES = {"region": "STRING", "order_date": "DATE", "returned": "BOOLEAN",
             "is_gift": "STRING", "store_no": "INT", "revenue": "DOUBLE",
             "order_count": "LONG"}
TITLE_TO_FIELD = {"Region": "region", "Order Date": "order_date", "Returned": "returned",
                  "Is Gift": "is_gift", "Store No": "store_no", "Revenue": "revenue",
                  "Order Count": "order_count"}

CMD_PARSED = {
    "dimensions": [{"name": "region"}, {"name": "order_date"}, {"name": "returned"},
                   {"name": "is_gift"}, {"name": "store_no"}],
    "measures": [{"name": "revenue"}, {"name": "order_count"}],
}
CMD_MODEL = {"model": {
    "name": "Sales MV",
    "formulas": [{"id": "f_oc", "name": "Order Count", "expr": "count ( 1 )"}],
    "columns": [
        _col("Region", "ATTRIBUTE"), _col("Order Date", "ATTRIBUTE"),
        _col("Returned", "ATTRIBUTE"), _col("Is Gift", "ATTRIBUTE"),
        _col("Store No", "ATTRIBUTE"),
        _col("Revenue", "MEASURE", "SUM"),
        _col("Order Count", "MEASURE", "SUM", formula_id="f_oc"),
    ],
}}


def _literal(text):
    if text in ("true", "false"):
        return text == "true"
    if text.startswith("'"):
        return text[1:-1]
    if text.startswith("TO_DATE("):
        return dt.date.fromisoformat(text[len("TO_DATE('"):-2])
    return int(text)


def _aggregate(fact, dims, measures, flt):
    groups: dict = {}
    for row in fact:
        if flt and row[flt[0]] != flt[1]:
            continue
        acc = groups.setdefault(tuple(row[d] for d in dims), {"revenue": 0.0, "order_count": 0})
        acc["revenue"] += row["revenue"]
        acc["order_count"] += 1
    if not dims and not groups:
        return [[None for _ in measures]]       # an aggregate over no rows: one NULL row
    return [list(k) + [acc[m] for m in measures] for k, acc in groups.items()]


class FakeDatabricks:
    """Answers `SELECT <dims>, MEASURE(m) ... FROM mv [WHERE d = lit] [GROUP BY ALL]`."""

    def __init__(self, fact=None, fail_on=None, drop_schema=False):
        self.fact = FACT if fact is None else fact
        self.calls = []
        self.fail_on = fail_on
        self.drop_schema = drop_schema

    def __call__(self, cli_profile, warehouse_id, sql):
        self.calls.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise SystemExit("Databricks SQL failed (FAILED): [UNRESOLVED_COLUMN] synthetic")
        select = sql.split(" FROM ")[0][len("SELECT "):]
        dims = [i.strip("`") for i in select.split(", ") if not i.startswith("MEASURE(")]
        measures = re.findall(r"MEASURE\(`([^`]+)`\)", sql)
        m = re.search(r"WHERE `([^`]+)` = (.+?)(?: GROUP BY ALL)?$", sql)
        flt = (m.group(1), _literal(m.group(2))) if m else None
        cols = [{"name": c, "type_name": DBX_TYPES[c]} for c in dims + measures]
        data = [[_dbx_text(v) for v in row]
                for row in _aggregate(self.fact, dims, measures, flt)]
        manifest = {} if self.drop_schema else {"schema": {"columns": cols}}
        return {"status": {"state": "SUCCEEDED"},
                "manifest": {**manifest, "total_chunk_count": 1},
                "result": {"data_array": data}}


def _dbx_text(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


class FakeAgentQL:
    """Answers AgentQL over the Model the way fetch-data does: DATEs as epoch seconds
    at midnight in the cluster zone, booleans as booleans."""

    def __init__(self, fact=None, tz="Asia/Tokyo", revenue_factor=1.0, revenue_noise=0.0,
                 combined_error=False, transport_error=False, rows=None, short_rows=False):
        self.fact = FACT if fact is None else fact
        self.tz = ZoneInfo(tz)
        self.calls = []
        self.revenue_factor = revenue_factor
        self.revenue_noise = revenue_noise
        self.combined_error = combined_error
        self.transport_error = transport_error
        self.fixed_rows = rows
        self.short_rows = short_rows

    def __call__(self, sql, model_guid, profile):
        self.calls.append(sql)
        if self.transport_error:
            raise RuntimeError("401 Unauthorized")
        if self.fixed_rows is not None:
            return {"status": "SUCCESS", "rows": self.fixed_rows, "columns": [], "errors": []}
        select = sql.split(" FROM ")[0][len("SELECT "):]
        items = select.split(", ")
        dims = [TITLE_TO_FIELD[re.match(r'"t1"\."([^"]+)"$', i).group(1)]
                for i in items if i.startswith('"t1"')]
        measures = [TITLE_TO_FIELD[t] for t in re.findall(r'\("t1"\."([^"]+)"\)', select)]
        if self.combined_error and len(measures) > 1 and dims:
            return {"status": "QUERY_GEN_ERROR", "rows": [], "columns": [],
                    "errors": [{"code": "QUERY_GEN_ERROR", "message": "synthetic"}]}
        m = re.search(r'WHERE "t1"\."([^"]+)" = (.+?)(?: GROUP BY .*)?$', sql)
        flt = (TITLE_TO_FIELD[m.group(1)], _literal(m.group(2))) if m else None
        rows = [self._row(row, dims, measures)
                for row in _aggregate(self.fact, dims, measures, flt)]
        if self.short_rows:
            rows = [r[:-1] for r in rows]
        return {"status": "SUCCESS", "rows": rows, "columns": [], "errors": []}

    def _row(self, row, dims, measures):
        out = [self._value(v) for v in row]
        for j, name in enumerate(measures):
            if name == "revenue" and out[len(dims) + j] is not None:
                out[len(dims) + j] *= self.revenue_factor * (1 + self.revenue_noise)
        return out

    def _value(self, v):
        if isinstance(v, dt.date):
            return int(dt.datetime(v.year, v.month, v.day, tzinfo=self.tz).timestamp())
        return v


@pytest.fixture
def files(tmp_path):
    def write(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data))
        return str(path)
    model = tmp_path / "Sales MV.model.tml"
    model.write_text(yaml.safe_dump(CMD_MODEL))
    return {"parsed": write("parsed.json", CMD_PARSED), "model": str(model),
            "dir": tmp_path, "write": write}


@pytest.fixture
def fakes(monkeypatch):
    def install(dbx=None, agentql=None, exported=None):
        dbx = dbx or FakeDatabricks()
        agentql = agentql or FakeAgentQL()
        exports = []

        def export(guid, profile):
            exports.append(guid)
            return copy.deepcopy(exported or CMD_MODEL)
        monkeypatch.setattr(verify_mod, "_run_databricks", dbx)
        monkeypatch.setattr(verify_mod, "_run_agentql", agentql)
        monkeypatch.setattr(verify_mod, "_export_model", export)
        monkeypatch.setattr(load_mod, "_load_dbx_profile", lambda name: {
            "name": name, "dbx_profile": "stub",
            "sql_warehouse_http_path": "/sql/1.0/warehouses/wh123"})
        return dbx, agentql, exports
    return install


def _args(files, *extra, tz="Asia/Tokyo", parsed=None):
    return ["databricks", "verify", "--parsed", parsed or files["parsed"],
            "--model-tml", files["model"], "--mv-fqn", "cat.sch.sales_mv",
            "--model-guid", "00000000-0000-0000-0000-000000000001",
            "--dbx-profile", "synthetic", "--cluster-tz", tz, *extra]


def _shape(report, label):
    return next(s for s in report["shapes"] if s["label"] == label)


class TestCommand:
    def test_all_shapes_match(self, files, fakes):
        _, _, exports = fakes()
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert report["status"] == "match"
        assert exports == ["00000000-0000-0000-0000-000000000001"]
        assert {s["label"]: s["status"] for s in report["shapes"]} == {
            "total": "match", "by Region": "match", "by Order Date": "match",
            "by Returned": "match", "by Is Gift": "match", "by Store No": "match",
            # named like a flag but STRING on Databricks: the filtered shapes are skipped
            "Is Gift = true": "skipped", "Is Gift = false": "skipped",
            # BOOLEAN on Databricks, missed by the name heuristic: added at run time
            "Returned = true": "match", "Returned = false": "match",
            "Region = 'East'": "match",       # the search filter
        }
        assert report["search_filter"] == {"label": "Region = 'East'", "status": "match"}
        assert report["summary"]["non_null_cells"] > 0
        assert report["problems"] == [] and report["model_differences"] == []
        assert _shape(report, "by Region")["rows_databricks"] == 3   # NULL group too
        assert _shape(report, "Region = 'East'")["databricks_sql"].endswith(
            "WHERE `region` = 'East'")

    def test_progress_line_per_shape_on_stderr(self, files, fakes):
        fakes()
        result = msg_runner.invoke(app, _args(files))
        assert result.exit_code == 0
        assert "[1] total: MATCH (rows 1/1, 0 mismatch(es))" in result.output
        assert "Is Gift = true: SKIPPED (is_gift is string on Databricks, not BOOLEAN)" \
            in result.output

    def test_wrong_number_exits_1_and_names_the_cell(self, files, fakes):
        fakes(agentql=FakeAgentQL(revenue_factor=2.0))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["status"] == "mismatch"
        assert report["shapes"][0]["mismatches"] == [
            {"key": [], "measure": "Revenue", "databricks": "22.75", "thoughtspot": 45.5}]

    def test_double_noise_is_accepted_and_counted(self, files, fakes):
        fakes(agentql=FakeAgentQL(revenue_noise=1e-13))
        result = msg_runner.invoke(app, _args(files))
        assert result.exit_code == 0
        assert "[1] total: MATCH (rows 1/1, 0 mismatch(es), 1 within tolerance)" \
            in result.output

    def test_wrong_cluster_zone_shows_as_rows_on_one_side(self, files, fakes):
        fakes(agentql=FakeAgentQL(tz="Asia/Tokyo"))
        result = runner.invoke(app, _args(files, tz="UTC"))
        assert result.exit_code == 1
        by_date = _shape(json.loads(result.stdout), "by Order Date")
        assert by_date["status"] == "mismatch"
        assert {m["issue"] for m in by_date["mismatches"]} == {
            "row only in Databricks", "row only in ThoughtSpot"}

    def test_databricks_error_is_reported_and_the_run_continues(self, files, fakes):
        fakes(dbx=FakeDatabricks(fail_on="SELECT `region`"))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["status"] == "error"
        assert "UNRESOLVED_COLUMN" in _shape(report, "by Region")["errors"][0]["error"]
        assert _shape(report, "total")["status"] == "match"

    def test_missing_schema_is_a_shape_error_not_a_traceback(self, files, fakes):
        fakes(dbx=FakeDatabricks(drop_schema=True))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert "schema has 0 columns" in report["shapes"][0]["errors"][0]["error"]

    def test_short_agentql_row_is_a_shape_error(self, files, fakes):
        fakes(agentql=FakeAgentQL(short_rows=True))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        total = json.loads(result.stdout)["shapes"][0]
        assert total["status"] == "error"
        assert "a ThoughtSpot row has 1 values, expected 2" in total["errors"][0]["error"]

    def test_agentql_row_cap_is_an_error(self, files, fakes):
        fakes(agentql=FakeAgentQL(rows=[[1, 1]] * mvc.AGENTQL_ROW_CAP))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        assert "row cap" in json.loads(result.stdout)["shapes"][0]["errors"][0]["error"]

    def test_agentql_query_error_falls_back_to_one_measure_at_a_time(self, files, fakes):
        fakes(agentql=FakeAgentQL(combined_error=True))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 0, result.output
        region = _shape(json.loads(result.stdout), "by Region")
        assert region["status"] == "match"
        assert len(region["agentql"]) == 3            # combined + one per measure
        assert "each measure ran alone" in region["notes"][0]

    def test_transport_error_is_not_retried_per_measure(self, files, fakes):
        _, agentql, _ = fakes(agentql=FakeAgentQL(transport_error=True))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["shapes"][0]["errors"] == [
            {"side": "thoughtspot", "error": "401 Unauthorized"}]
        ran = [s for s in report["shapes"] if s["status"] != "skipped"]
        assert len(agentql.calls) == len(ran)

    def test_search_filter_falls_back_to_an_integer(self, files, fakes):
        fact = [dict(r, region="East", is_gift="Y") for r in FACT]
        fakes(dbx=FakeDatabricks(fact=fact), agentql=FakeAgentQL(fact=fact))
        report = json.loads(runner.invoke(app, _args(files)).stdout)
        assert report["search_filter"] == {"label": "Store No = 7", "status": "match"}

    def test_search_filter_not_run_makes_the_run_incomplete(self, files, fakes):
        fact = [{"region": "East", "order_date": dt.date(2024, 1, 31), "revenue": 2.0}] * 2
        parsed = files["write"]("parsed2.json", {
            "dimensions": [{"name": "region"}, {"name": "order_date"}],
            "measures": [{"name": "revenue"}, {"name": "order_count"}]})
        fakes(dbx=FakeDatabricks(fact=fact), agentql=FakeAgentQL(fact=fact))
        result = msg_runner.invoke(app, _args(files, parsed=parsed))
        assert result.exit_code == 1
        assert "search filter: SKIPPED (not run: no string, integer or date dimension" \
            in result.output
        report = json.loads(runner.invoke(app, _args(files, parsed=parsed)).stdout)
        assert report["status"] == "incomplete"
        assert report["search_filter"]["status"] == "skipped"

    def test_no_data_anywhere_exits_1(self, files, fakes):
        fakes(dbx=FakeDatabricks(fact=[]), agentql=FakeAgentQL(fact=[]))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["status"] == "no_data"
        assert report["summary"]["non_null_cells"] == 0

    def test_custom_shape_matching_nothing_is_no_data(self, files, fakes):
        dbx, _, _ = fakes()
        shapes = files["write"]("shapes.json", [
            {"label": "region x date", "dims": ["region", "order_date"], "filter": None},
            {"label": "nowhere", "dims": ["region"], "filter": ["is_gift", "'Z'"]}])
        result = runner.invoke(app, _args(files, "--shapes", shapes))
        assert result.exit_code == 0, result.output       # the other shape compared data
        report = json.loads(result.stdout)
        assert [s["label"] for s in report["shapes"]] == ["region x date", "nowhere"]
        assert _shape(report, "nowhere")["status"] == "no_data"
        assert report["search_filter"] is None
        assert dbx.calls[1].endswith("WHERE `is_gift` = 'Z' GROUP BY ALL")

    def test_missing_measure_fails_unless_the_converter_skipped_it(self, files, fakes):
        fakes()
        parsed = files["write"]("parsed3.json", {
            **CMD_PARSED, "measures": CMD_PARSED["measures"] + [{"name": "margin"}]})
        result = runner.invoke(app, _args(files, parsed=parsed))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["status"] == "mismatch" and report["missing"]["measures"] == ["margin"]
        translated = files["write"]("translated.json", {"skipped": [
            {"name": "margin", "role": "measure", "reason": "unsupported"}]})
        result = runner.invoke(app, _args(files, "--translated", translated, parsed=parsed))
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["skipped_by_converter"]["measures"] == ["margin"]

    def test_measure_on_an_attribute_column_fails(self, files, fakes):
        fakes()
        parsed = files["write"]("parsed4.json", {
            **CMD_PARSED, "measures": CMD_PARSED["measures"] + [{"name": "region"}]})
        result = runner.invoke(app, _args(files, parsed=parsed))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["wrong_column_type"][0]["mv_name"] == "region"
        assert any("ATTRIBUTE column" in p for p in report["problems"])

    def test_imported_model_differing_from_the_file_fails(self, files, fakes):
        imported = copy.deepcopy(CMD_MODEL)
        imported["model"]["columns"][5]["properties"]["aggregation"] = "MAX"
        fakes(exported=imported)
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["model_differences"] == [
            "column 'Revenue': --model-tml has ('MEASURE', 'SUM'), the imported Model "
            "('MEASURE', 'MAX')"]
        assert report["measures"][0]["agentql"] == "MAX"     # the plan follows the import

    def test_output_file(self, files, fakes):
        fakes()
        out = files["dir"] / "reports" / "verify.json"
        result = runner.invoke(app, _args(files, "--output", str(out)))
        assert result.exit_code == 0
        written = json.loads(out.read_text())
        assert json.loads(result.stdout) == {"status": written["status"],
                                             "summary": written["summary"],
                                             "report": str(out)}

    def test_bad_shapes_file_exits_1(self, files, fakes):
        fakes()
        shapes = files["write"]("shapes.json", [{"label": "x", "dims": ["no_such_dim"]}])
        result = msg_runner.invoke(app, _args(files, "--shapes", shapes))
        assert result.exit_code == 1
        assert "no_such_dim" in result.output

    def test_dry_run_runs_nothing(self, files, monkeypatch):
        def boom(*a):
            raise AssertionError("dry run must not execute")
        for name in ("_run_databricks", "_run_agentql", "_export_model"):
            monkeypatch.setattr(verify_mod, name, boom)
        result = runner.invoke(app, ["databricks", "verify", "--parsed", files["parsed"],
                                     "--model-tml", files["model"], "--mv-fqn", "c.s.v",
                                     "--dry-run"])
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert report["dry_run"] is True
        total = report["shapes"][0]
        assert total["databricks_sql"] == ("SELECT MEASURE(`revenue`) AS `m0`, "
                                           "MEASURE(`order_count`) AS `m1` FROM `c`.`s`.`v`")
        assert total["agentql"] == ('SELECT SUM("t1"."Revenue") AS "M0", '
                                    'AGG("t1"."Order Count") AS "M1" FROM "Sales MV" AS "t1"')

    def test_guid_and_dbx_profile_required_without_dry_run(self, files, fakes):
        fakes()
        result = msg_runner.invoke(app, ["databricks", "verify", "--parsed", files["parsed"],
                                         "--model-tml", files["model"], "--mv-fqn", "c.s.v"])
        assert result.exit_code == 1
        assert "--model-guid and --dbx-profile are required" in result.output

    def test_export_failure_exits_1(self, files, fakes, monkeypatch):
        fakes()

        def fail(guid, profile):
            raise RuntimeError("404 not found")
        monkeypatch.setattr(verify_mod, "_export_model", fail)
        result = msg_runner.invoke(app, _args(files))
        assert result.exit_code == 1
        assert "cannot export the imported Model" in result.output

    def test_unknown_zone_exits_1(self, files, fakes):
        fakes()
        result = msg_runner.invoke(app, _args(files, tz="Mars/Olympus_Mons"))
        assert result.exit_code == 1
        assert "unknown time zone" in result.output

    def test_nothing_to_compare_exits_1(self, files, fakes):
        fakes(exported={"model": {"name": "Other", "columns": []}})
        result = msg_runner.invoke(app, _args(files))
        assert result.exit_code == 1
        assert "nothing to compare" in result.output
