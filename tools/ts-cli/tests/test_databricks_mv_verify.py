"""Tests for `ts databricks verify` (BL-639): the pure planning and comparison in
`ts_cli/databricks/mv_verify.py`, and the command in `commands/databricks_verify.py`
with both executors replaced by fakes that answer from one synthetic fact table.

No live calls. Every name here is synthetic.
"""
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

from runners import msg_runner, runner  # noqa: E402  (BL-139)

UTC = ZoneInfo("UTC")
TOKYO = ZoneInfo("Asia/Tokyo")


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
        {"name": "warehouse_code"},          # not in the Model
    ],
    "measures": [
        {"name": "revenue"},
        {"name": "avg_price"},
        {"name": "order_count"},
        {"name": "closing_balance", "window": {"order": "order_date"}},
        {"name": "price_sd"},
        {"name": "margin"},                  # not in the Model
        {"name": "unique_buyers"},
    ],
}

PLAN_MODEL = {"model": {
    "name": "Sales MV",
    "formulas": [
        {"id": "formula_Order Count", "name": "Order Count", "expr": "count ( 1 )"},
        {"id": "formula_Closing Balance", "name": "Closing Balance",
         "expr": "last_value ( sum ( [F::BAL] ) , query_groups ( ) , { [F::D] } )"},
        {"id": "formula_Priority Order", "name": "Priority Order",
         "expr": "sql_bool_op ( \"{0} > 3\" , [F::PRI] )"},
        {"id": "formula_Unique Buyers", "name": "Unique Buyers",
         "expr": "unique count ( [F::BUYER] )"},
    ],
    "columns": [
        {"name": "Order Date", "column_id": "F::D", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Region", "column_id": "F::R", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Is Returned", "column_id": "F::RET",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Has Coupon", "column_id": "F::CPN", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Priority Order", "formula_id": "formula_Priority Order",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Revenue", "column_id": "F::REV",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Avg Price", "column_id": "F::PRICE",
         "properties": {"column_type": "MEASURE", "aggregation": "AVERAGE"}},
        {"name": "Order Count", "formula_id": "formula_Order Count",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Closing Balance", "formula_id": "formula_Closing Balance",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Price Sd", "column_id": "F::PRICE2",
         "properties": {"column_type": "MEASURE", "aggregation": "STD_DEVIATION"}},
        {"name": "Unique Buyers", "formula_id": "formula_Unique Buyers",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
    ],
}}


@pytest.fixture
def plan():
    return mv.build_plan(PLAN_PARSED, PLAN_MODEL)


class TestPlan:
    def test_measures_and_their_agentql_wrappers(self, plan):
        got = {m["mv_name"]: (m["title"], m["agentql"]) for m in plan["measures"]}
        assert got == {
            "revenue": ("Revenue", "SUM"),
            "avg_price": ("Avg Price", "AVG"),          # a raw AVERAGE column, not SUM
            "order_count": ("Order Count", "AGG"),
            "closing_balance": ("Closing Balance", "SUM"),   # semi-additive last_value
            "unique_buyers": ("Unique Buyers", "AGG"),
        }

    def test_not_in_model_is_listed_not_compared(self, plan):
        assert plan["not_in_model"] == {"measures": ["margin"],
                                        "dimensions": ["warehouse_code"]}

    def test_stddev_column_is_not_verifiable(self, plan):
        assert [(u["mv_name"], "STD_DEVIATION" in u["reason"])
                for u in plan["not_verifiable"]] == [("price_sd", True)]

    def test_flags_by_name_and_by_sql_bool_op(self, plan):
        flags = {d["mv_name"]: d["flag"] for d in plan["dimensions"]}
        assert flags == {"order_date": False, "region": False, "is_returned": True,
                         "Has Coupon": True, "priority_order": True}

    def test_window_order_dimension_reported(self, plan):
        assert plan["order_dimensions"] == [{"mv_name": "order_date", "in_model": True}]

    def test_model_name(self, plan):
        assert plan["model_name"] == "Sales MV"

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
        ("COUNT", "COUNT"), ("COUNT_DISTINCT", "COUNT_DISTINCT"), ("VARIANCE", None),
    ])
    def test_raw_measure_wrapper(self, agg, want):
        fn, reason = mv.agentql_function({"kind": "raw_measure", "aggregation": agg})
        assert fn == want and (reason is None) == (want is not None)

    def test_aggregate_and_semiadditive_use_classify_wrapper(self):
        assert mv.agentql_function({"kind": "aggregate_measure", "wrapper": "AGG"}) == ("AGG", None)
        assert mv.agentql_function({"kind": "semiadditive_measure", "wrapper": "SUM"}) == ("SUM", None)


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
        assert shapes[0] == {"label": "total", "dims": [], "filter": None}
        assert shapes[6] == {"label": "Is Returned = true", "dims": [],
                             "filter": ["is_returned", "true"], "flag": "is_returned"}

    def test_order_dimension_has_its_own_shape(self, plan):
        assert {"label": "by Order Date", "dims": ["order_date"], "filter": None} \
            in mv.default_shapes(plan)

    @pytest.mark.parametrize("values,want", [
        (["West", "East", None, "East"], "East"),
        (["East"], None),                          # the only value: equals the total
        ([None, None], None),
        (["O'Brien", "Smith"], "Smith"),           # quotes escape differently per side
        (["a\\b", "c"], "c"),
        (["east", "East", "West"], "West"),        # AgentQL would match both cases
        (["east", "East"], None),
        ([1, 2], None),                            # strings only
    ])
    def test_pick_filter_value(self, values, want):
        assert mv.pick_filter_value(values) == want

    def test_value_filter_shape(self):
        shape = mv.value_filter_shape({"mv_name": "region", "title": "Region"}, "East")
        assert shape == {"label": "Region = 'East'", "dims": [],
                         "filter": ["region", "'East'"]}

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
                {"mv_name": "buyers", "title": "Buyers", "agentql": "COUNT_DISTINCT"}]
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
        assert mv.norm_key(epoch, "date", TOKYO) == "2024-03-01"
        assert mv.norm_key(epoch, "date", UTC) == "2024-02-29"   # wrong zone, wrong day

    def test_date_epoch_milliseconds(self):
        epoch_ms = _midnight(2024, 3, 1, TOKYO) * 1000
        assert mv.norm_key(epoch_ms, "date", TOKYO) == "2024-03-01"

    def test_date_before_1970(self):
        assert mv.norm_key(_midnight(1965, 7, 4, UTC), "date", UTC) == "1965-07-04"

    def test_date_string_from_databricks(self):
        assert mv.norm_key("2024-03-01", "date", TOKYO) == "2024-03-01"
        assert mv.norm_key("2024-03-01T00:00:00.000Z", "date", TOKYO) == "2024-03-01"

    def test_timestamp_both_sides(self):
        epoch = int(dt.datetime(2024, 3, 1, 9, 30, tzinfo=TOKYO).timestamp())
        assert mv.norm_key(epoch, "timestamp", TOKYO) == "2024-03-01 09:30:00"
        assert mv.norm_key("2024-03-01T00:30:00.000Z", "timestamp", TOKYO) == \
            "2024-03-01 09:30:00"
        assert mv.norm_key("2024-03-01 09:30:00", "timestamp", TOKYO) == "2024-03-01 09:30:00"

    def test_boolean_case_insensitive(self):
        assert mv.norm_key(True, "boolean", UTC) == mv.norm_key("true", "boolean", UTC) == "true"
        assert mv.norm_key("FALSE", "boolean", UTC) == "false"

    @pytest.mark.parametrize("a,b", [("1", 1), ("1.50", 1.5), ("1E+3", 1000),
                                     ("-0.0000001", -1e-7), ("12345678901234567", 12345678901234567)])
    def test_number_keys_agree(self, a, b):
        assert mv.norm_key(a, "number", UTC) == mv.norm_key(b, "number", UTC)

    def test_null_stays_null(self):
        assert mv.norm_key(None, "string", UTC) is None
        assert mv.norm_key(None, "date", UTC) is None

    def test_string_is_not_touched(self):
        assert mv.norm_key("East ", "string", UTC) == "East "


class TestCellsMatch:
    @pytest.mark.parametrize("a,b,want", [
        ("10.5", 10.5, True),
        ("100", 100.00000000001, True),
        ("0", 1e-12, True),
        ("10.5", 10.6, False),
        (None, None, True),
        (None, 0, False),
        ("0", None, False),
        ("NaN", float("nan"), True),
        ("abc", "abc", True),
        ("abc", "ABC", False),
        ("true", True, True),
    ])
    def test_numbers_and_text(self, a, b, want):
        assert mv.cells_match(a, b, "number", UTC) is want

    def test_date_measure(self):
        epoch = _midnight(2024, 3, 1, TOKYO)
        assert mv.cells_match("2024-03-01", epoch, "date", TOKYO)
        assert not mv.cells_match("2024-03-01", epoch, "date", UTC)


class TestDatabricksResult:
    def _resp(self, **manifest_extra):
        return {"manifest": {"schema": {"columns": [
                    {"name": "d", "type_name": "DATE"}, {"name": "b", "type_name": "BOOLEAN"},
                    {"name": "s", "type_name": "STRING"}, {"name": "m0", "type_name": "DECIMAL"}]},
                    **manifest_extra},
                "result": {"data_array": [["2024-01-01", "true", "x", "1.5"]]}}

    def test_kinds_and_rows(self):
        kinds, rows = mv.databricks_result(self._resp())
        assert kinds == ["date", "boolean", "string", "number"]
        assert rows == [["2024-01-01", "true", "x", "1.5"]]

    def test_empty_result(self):
        assert mv.databricks_result({"manifest": {"schema": {"columns": []}}}) == ([], [])

    def test_chunked_result_refused(self):
        with pytest.raises(ValueError, match="3 chunks"):
            mv.databricks_result(self._resp(total_chunk_count=3))

    def test_truncated_result_refused(self):
        with pytest.raises(ValueError, match="truncated"):
            mv.databricks_result(self._resp(truncated=True))


class TestCompare:
    MEASURES = [{"title": "Revenue"}, {"title": "Orders"}]
    KINDS = ["string", "date", "number", "number"]

    def _ts(self, rows, measures=(0, 1)):
        return [{"measures": list(measures), "rows": rows}]

    def test_match_with_null_key_and_date_key(self):
        epoch = _midnight(2024, 3, 1, TOKYO)
        dbx = [["East", "2024-03-01", "10.5", "2"], [None, "2024-03-01", "1", "1"]]
        ts = [[None, epoch, 1.0, 1], ["East", epoch, 10.5, 2]]
        r = mv.compare_shape(2, self.KINDS, dbx, self._ts(ts), self.MEASURES, TOKYO)
        assert r == {"rows_databricks": 2, "rows_thoughtspot": 2, "cells": 4,
                     "mismatch_count": 0, "mismatches": []}

    def test_numeric_mismatch(self):
        dbx = [["East", "2024-03-01", "10.5", "2"]]
        ts = [["East", "2024-03-01", 21.0, 2]]
        r = mv.compare_shape(2, self.KINDS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert r["mismatches"] == [{"key": ["East", "2024-03-01"], "measure": "Revenue",
                                    "databricks": "10.5", "thoughtspot": 21.0}]

    def test_null_measure_is_not_zero(self):
        dbx = [["East", "2024-03-01", None, "2"]]
        ts = [["East", "2024-03-01", 0, 2]]
        r = mv.compare_shape(2, self.KINDS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert r["mismatch_count"] == 1

    def test_rows_on_one_side_only(self):
        dbx = [["East", "2024-03-01", "1", "1"], ["West", "2024-03-01", "1", "1"]]
        ts = [["East", "2024-03-01", 1, 1], ["North", "2024-03-01", 1, 1]]
        r = mv.compare_shape(2, self.KINDS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert [(m["key"][0], m["issue"]) for m in r["mismatches"]] == [
            ("North", "row only in ThoughtSpot"), ("West", "row only in Databricks")]

    def test_duplicate_key_reported(self):
        dbx = [["East", "2024-03-01", "1", "1"]]
        ts = [["east", "2024-03-01", 1, 1], ["east", "2024-03-01", 1, 1]]
        r = mv.compare_shape(2, self.KINDS, dbx, self._ts(ts), self.MEASURES, UTC)
        assert "duplicate key in the ThoughtSpot result" in [m.get("issue")
                                                              for m in r["mismatches"]]

    def test_per_measure_blocks(self):
        dbx = [["East", "2024-03-01", "5", "2"]]
        blocks = [{"measures": [0], "rows": [["East", "2024-03-01", 5]]},
                  {"measures": [1], "rows": [["East", "2024-03-01", 3]]}]
        r = mv.compare_shape(2, self.KINDS, dbx, blocks, self.MEASURES, UTC)
        assert r["cells"] == 2
        assert [m["measure"] for m in r["mismatches"]] == ["Orders"]

    def test_mismatch_list_is_capped_but_counted(self):
        dbx = [[f"k{i}", "2024-03-01", "1", "1"] for i in range(80)]
        r = mv.compare_shape(2, self.KINDS, dbx, self._ts([]), self.MEASURES, UTC)
        assert r["mismatch_count"] == 80
        assert len(r["mismatches"]) == mv.MAX_MISMATCHES_KEPT

    def test_summarise(self):
        shapes = [{"status": "match", "cells": 4}, {"status": "skipped"},
                  {"status": "mismatch", "cells": 2, "mismatch_count": 1}]
        assert mv.summarise(shapes)["status"] == "mismatch"
        assert mv.summarise(shapes + [{"status": "error"}])["status"] == "error"
        assert mv.summarise(shapes[:2])["summary"] == {
            "shapes": 2, "match": 1, "mismatch": 0, "error": 0, "skipped": 1,
            "cells": 4, "mismatches": 0}


# ---------------------------------------------------------------------------
# Command: both executors answer from one synthetic fact table
# ---------------------------------------------------------------------------

FACT = [
    {"region": "East", "order_date": dt.date(2024, 1, 31), "returned": True, "is_gift": "Y",
     "revenue": 10.5},
    {"region": "East", "order_date": dt.date(2024, 2, 29), "returned": False, "is_gift": "N",
     "revenue": 4.0},
    {"region": "West", "order_date": dt.date(2024, 2, 29), "returned": False, "is_gift": "N",
     "revenue": 7.25},
    {"region": None, "order_date": dt.date(2024, 1, 31), "returned": False, "is_gift": "Y",
     "revenue": 1.0},
]
DBX_TYPES = {"region": "STRING", "order_date": "DATE", "returned": "BOOLEAN",
             "is_gift": "STRING", "revenue": "DOUBLE", "order_count": "LONG"}
TITLE_TO_FIELD = {"Region": "region", "Order Date": "order_date", "Returned": "returned",
                  "Is Gift": "is_gift", "Revenue": "revenue", "Order Count": "order_count"}

CMD_PARSED = {
    "dimensions": [{"name": "region"}, {"name": "order_date"}, {"name": "returned"},
                   {"name": "is_gift"}],
    "measures": [{"name": "revenue"},
                 {"name": "order_count", "window": None}],
}
CMD_MODEL = {"model": {
    "name": "Sales MV",
    "formulas": [{"id": "formula_Order Count", "name": "Order Count", "expr": "count ( 1 )"}],
    "columns": [
        {"name": "Region", "column_id": "F::R", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Order Date", "column_id": "F::D", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Returned", "column_id": "F::RET", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Is Gift", "column_id": "F::G", "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Revenue", "column_id": "F::REV",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Order Count", "formula_id": "formula_Order Count",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
    ],
}}


def _aggregate(dims, measures, flt):
    groups: dict = {}
    for row in FACT:
        if flt and row[flt[0]] != flt[1]:
            continue
        acc = groups.setdefault(tuple(row[d] for d in dims), {"revenue": 0.0, "order_count": 0})
        acc["revenue"] += row["revenue"]
        acc["order_count"] += 1
    return [list(k) + [acc[m] for m in measures] for k, acc in groups.items()]


def _literal(text):
    if text.startswith("'"):
        return text[1:-1]
    return {"true": True, "false": False}[text]


class FakeDatabricks:
    """Answers `SELECT <dims>, MEASURE(m) ... FROM mv [WHERE d = lit] [GROUP BY ALL]`."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, cli_profile, warehouse_id, sql):
        self.calls.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise SystemExit("Databricks SQL failed (FAILED): [UNRESOLVED_COLUMN] synthetic")
        select = sql.split(" FROM ")[0][len("SELECT "):]
        dims = [i.strip("`") for i in select.split(", ") if not i.startswith("MEASURE(")]
        measures = re.findall(r"MEASURE\(`([^`]+)`\)", sql)
        m = re.search(r"WHERE `([^`]+)` = (\w+|'[^']*')", sql)
        flt = (m.group(1), _literal(m.group(2))) if m else None
        cols = [{"name": c, "type_name": DBX_TYPES[c]} for c in dims + measures]
        data = [[_dbx_text(v) for v in row] for row in _aggregate(dims, measures, flt)]
        return {"status": {"state": "SUCCEEDED"},
                "manifest": {"schema": {"columns": cols}, "total_chunk_count": 1},
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

    def __init__(self, tz="Asia/Tokyo", revenue_factor=1.0, combined_error=False,
                 transport_error=False):
        self.tz = ZoneInfo(tz)
        self.calls = []
        self.revenue_factor = revenue_factor
        self.combined_error = combined_error
        self.transport_error = transport_error

    def __call__(self, sql, model_guid, profile):
        self.calls.append(sql)
        if self.transport_error:
            raise RuntimeError("401 Unauthorized")
        select = sql.split(" FROM ")[0][len("SELECT "):]
        items = select.split(", ")
        dims = [TITLE_TO_FIELD[re.match(r'"t1"\."([^"]+)"$', i).group(1)]
                for i in items if i.startswith('"t1"')]
        measures = [TITLE_TO_FIELD[t] for t in re.findall(r'\("t1"\."([^"]+)"\)', select)]
        if self.combined_error and len(measures) > 1 and dims:
            return {"status": "QUERY_GEN_ERROR", "rows": [], "columns": [],
                    "errors": [{"code": "QUERY_GEN_ERROR", "message": "synthetic"}]}
        m = re.search(r'WHERE "t1"\."([^"]+)" = (\w+|\'[^\']*\')', sql)
        flt = (TITLE_TO_FIELD[m.group(1)], _literal(m.group(2))) if m else None
        rows = []
        for row in _aggregate(dims, measures, flt):
            out = [self._value(v) for v in row]
            for j, name in enumerate(measures):
                if name == "revenue":
                    out[len(dims) + j] *= self.revenue_factor
            rows.append(out)
        return {"status": "SUCCESS", "rows": rows, "columns": [], "errors": []}

    def _value(self, v):
        if isinstance(v, dt.date):
            return int(dt.datetime(v.year, v.month, v.day, tzinfo=self.tz).timestamp())
        return v


@pytest.fixture
def files(tmp_path):
    parsed = tmp_path / "parsed.json"
    parsed.write_text(json.dumps(CMD_PARSED))
    model = tmp_path / "Sales MV.model.tml"
    model.write_text(yaml.safe_dump(CMD_MODEL))
    return {"parsed": str(parsed), "model": str(model), "dir": tmp_path}


@pytest.fixture
def fakes(monkeypatch):
    def install(dbx=None, agentql=None):
        dbx = dbx or FakeDatabricks()
        agentql = agentql or FakeAgentQL()
        monkeypatch.setattr(verify_mod, "_run_databricks", dbx)
        monkeypatch.setattr(verify_mod, "_run_agentql", agentql)
        monkeypatch.setattr(load_mod, "_load_dbx_profile", lambda name: {
            "name": name, "dbx_profile": "stub",
            "sql_warehouse_http_path": "/sql/1.0/warehouses/wh123"})
        return dbx, agentql
    return install


def _args(files, *extra, tz="Asia/Tokyo"):
    return ["databricks", "verify", "--parsed", files["parsed"], "--model-tml", files["model"],
            "--mv-fqn", "cat.sch.sales_mv", "--model-guid", "00000000-0000-0000-0000-000000000001",
            "--dbx-profile", "synthetic", "--cluster-tz", tz, *extra]


class TestCommand:
    def test_all_shapes_match(self, files, fakes):
        fakes()
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert report["status"] == "match"
        labels = {s["label"]: s["status"] for s in report["shapes"]}
        assert labels == {
            "total": "match", "by Region": "match", "by Order Date": "match",
            "by Returned": "match", "by Is Gift": "match",
            # named like a flag but STRING on Databricks: the filtered shapes are skipped
            "Is Gift = true": "skipped", "Is Gift = false": "skipped",
            # BOOLEAN on Databricks, missed by the name heuristic: added at run time
            "Returned = true": "match", "Returned = false": "match",
            # a search filter beside every measure, on the first string dimension's
            # first value
            "Region = 'East'": "match",
        }
        assert report["summary"]["mismatches"] == 0
        assert report["summary"]["cells"] > 0
        region = next(s for s in report["shapes"] if s["label"] == "by Region")
        assert region["rows_databricks"] == region["rows_thoughtspot"] == 3   # NULL group too
        east = report["shapes"][-1]
        assert east["databricks_sql"].endswith("FROM `cat`.`sch`.`sales_mv` WHERE `region` = 'East'")
        assert east["agentql"] == ['SELECT SUM("t1"."Revenue") AS "M0", AGG("t1"."Order Count") '
                                   'AS "M1" FROM "Sales MV" AS "t1" WHERE "t1"."Region" = \'East\'']

    def test_custom_shapes_get_no_run_time_additions(self, files, fakes):
        fakes()
        shapes = files["dir"] / "shapes.json"
        shapes.write_text(json.dumps([{"label": "by region", "dims": ["region"],
                                       "filter": None},
                                      {"label": "by returned", "dims": ["returned"],
                                       "filter": None}]))
        result = runner.invoke(app, _args(files, "--shapes", str(shapes)))
        assert [s["label"] for s in json.loads(result.stdout)["shapes"]] == [
            "by region", "by returned"]

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
        total = report["shapes"][0]
        assert total["mismatches"] == [{"key": [], "measure": "Revenue",
                                        "databricks": "22.75", "thoughtspot": 45.5}]

    def test_wrong_cluster_zone_shows_as_rows_on_one_side(self, files, fakes):
        fakes(agentql=FakeAgentQL(tz="Asia/Tokyo"))
        result = runner.invoke(app, _args(files, tz="UTC"))
        assert result.exit_code == 1
        by_date = next(s for s in json.loads(result.stdout)["shapes"]
                       if s["label"] == "by Order Date")
        assert by_date["status"] == "mismatch"
        assert {m["issue"] for m in by_date["mismatches"]} == {
            "row only in Databricks", "row only in ThoughtSpot"}

    def test_databricks_error_is_reported_and_the_run_continues(self, files, fakes):
        fakes(dbx=FakeDatabricks(fail_on="SELECT `region`"))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["status"] == "error"
        region = next(s for s in report["shapes"] if s["label"] == "by Region")
        assert region["status"] == "error"
        assert "UNRESOLVED_COLUMN" in region["errors"][0]["error"]
        assert next(s for s in report["shapes"] if s["label"] == "total")["status"] == "match"

    def test_agentql_query_error_falls_back_to_one_measure_at_a_time(self, files, fakes):
        _, agentql = fakes(agentql=FakeAgentQL(combined_error=True))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 0, result.output
        region = next(s for s in json.loads(result.stdout)["shapes"]
                      if s["label"] == "by Region")
        assert region["status"] == "match"
        assert len(region["agentql"]) == 3            # combined + one per measure
        assert "each measure ran alone" in region["notes"][0]

    def test_transport_error_is_not_retried_per_measure(self, files, fakes):
        _, agentql = fakes(agentql=FakeAgentQL(transport_error=True))
        result = runner.invoke(app, _args(files))
        assert result.exit_code == 1
        report = json.loads(result.stdout)
        assert report["shapes"][0]["errors"] == [
            {"side": "thoughtspot", "error": "401 Unauthorized"}]
        # one AgentQL call per shape that ran, no per-measure retries
        ran = [s for s in report["shapes"] if s["status"] != "skipped"]
        assert len(agentql.calls) == len(ran)

    def test_output_file(self, files, fakes):
        fakes()
        out = files["dir"] / "reports" / "verify.json"
        result = runner.invoke(app, _args(files, "--output", str(out)))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {**{k: json.loads(out.read_text())[k]
                                                for k in ("status", "summary")},
                                             "report": str(out)}

    def test_custom_shapes(self, files, fakes):
        dbx, _ = fakes()
        shapes = files["dir"] / "shapes.json"
        shapes.write_text(json.dumps([
            {"label": "region x date", "dims": ["region", "order_date"], "filter": None},
            {"label": "kept rows", "dims": ["region"], "filter": ["returned", "false"]}]))
        result = runner.invoke(app, _args(files, "--shapes", str(shapes)))
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert [s["label"] for s in report["shapes"]] == ["region x date", "kept rows"]
        assert dbx.calls[1] == ("SELECT `region`, MEASURE(`revenue`) AS `m0`, "
                                "MEASURE(`order_count`) AS `m1` FROM `cat`.`sch`.`sales_mv` "
                                "WHERE `returned` = false GROUP BY ALL")

    def test_bad_shapes_file_exits_1(self, files, fakes):
        fakes()
        shapes = files["dir"] / "shapes.json"
        shapes.write_text(json.dumps([{"label": "x", "dims": ["no_such_dim"]}]))
        result = msg_runner.invoke(app, _args(files, "--shapes", str(shapes)))
        assert result.exit_code == 1
        assert "no_such_dim" in result.output

    def test_dry_run_runs_nothing(self, files, monkeypatch):
        def boom(*a):
            raise AssertionError("dry run must not execute")
        monkeypatch.setattr(verify_mod, "_run_databricks", boom)
        monkeypatch.setattr(verify_mod, "_run_agentql", boom)
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

    def test_unknown_zone_exits_1(self, files, fakes):
        fakes()
        result = msg_runner.invoke(app, _args(files, tz="Mars/Olympus_Mons"))
        assert result.exit_code == 1
        assert "unknown time zone" in result.output

    def test_nothing_to_compare_exits_1(self, files, fakes):
        fakes()
        other = files["dir"] / "other.model.tml"
        other.write_text(yaml.safe_dump({"model": {"name": "Other", "columns": []}}))
        args = _args(files)
        args[args.index(files["model"])] = str(other)
        result = msg_runner.invoke(app, args)
        assert result.exit_code == 1
        assert "nothing to compare" in result.output
