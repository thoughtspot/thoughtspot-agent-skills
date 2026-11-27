"""BL-634 (window ordered by a date built from an integer key) and BL-635
(whole-table AGG(expr) OVER () dimension)."""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_expr import classify_dimension_expr
from ts_cli.databricks.mv_sql import UntranslatableError
from ts_cli.databricks.mv_translate import translate_dimension, translate_window_measure

TABLES = {"source": "FACT"}
INT_DATE = "TO_DATE(CAST(source.DATE_KEY AS STRING), 'yyyyMMdd')"


def _dim(name, expr, kind, **kw):
    base = {"name": name, "expr": expr, "kind": kind, "display_name": None,
            "comment": None, "synonyms": [], "inner_agg": None,
            "inner_expr": None, "partition_by": []}
    base.update(kw)
    return base


def _win(order, rtype="current", semi="first", offset=None, n=None, unit=None):
    return {"name": "Opening", "expr": "SUM(source.BAL)", "kind": "windowed",
            "expr_kind": "simple", "agg_function": "SUM", "physical_ref": "source.BAL",
            "distinct": False, "cross_refs": [], "lod_refs": [], "display_name": None,
            "comment": None, "synonyms": [], "format": None,
            "window": {"order": order,
                       "range": {"type": rtype, "n": n, "unit": unit, "anchor": None},
                       "raw_range": rtype, "semiadditive": semi, "offset": offset,
                       "raw_offset": None, "density_check_required": False}}


class TestIntKeyOrder:
    def test_semiadditive_orders_by_the_integer_key(self):
        dims = [_dim("order_month", INT_DATE, "computed")]
        out = translate_window_measure(_win("order_month"), dims, TABLES)
        assert out["ts_expr"] == ("first_value ( sum ( [FACT::BAL] ) , query_groups ( ) , "
                                  "{ [FACT::DATE_KEY] } )")
        assert any(a["kind"] == "order_by_int_key" for a in out["annotations"])

    @pytest.mark.parametrize("fmt", ["yyyyMM"])
    def test_month_key_format_also_orders(self, fmt):
        dims = [_dim("m", f"TO_DATE(CAST(source.K AS STRING), '{fmt}')", "computed")]
        out = translate_window_measure(_win("m", semi="last"), dims, TABLES)
        assert out["ts_expr"].endswith("{ [FACT::K] } )")

    @pytest.mark.parametrize("fmt", ["yyyymmdd", "yyyy-MM-dd", "ddMMyyyy", "MMddyyyy"])
    def test_format_that_does_not_sort_as_the_key_is_refused(self, fmt):
        # mm is minutes; a separator or a day-first format does not sort as the integer
        dims = [_dim("d", f"TO_DATE(CAST(source.K AS STRING), '{fmt}')", "computed")]
        with pytest.raises(UntranslatableError, match="physical sort column"):
            translate_window_measure(_win("d"), dims, TABLES)

    def test_date_interval_on_an_int_key_is_refused(self):
        dims = [_dim("d", INT_DATE, "computed")]
        with pytest.raises(UntranslatableError, match="integer key"):
            translate_window_measure(_win("d", rtype="trailing", n=7, unit="day"),
                                     dims, TABLES)

    def test_offset_on_an_int_key_is_refused(self):
        dims = [_dim("d", INT_DATE, "computed")]
        with pytest.raises(UntranslatableError, match="integer key"):
            translate_window_measure(_win("d", offset={"n": -1, "unit": "month"}),
                                     dims, TABLES)

    def test_cast_of_an_expression_is_not_an_int_key(self):
        dims = [_dim("d", "TO_DATE(CAST(source.A + 1 AS STRING), 'yyyyMMdd')", "computed")]
        with pytest.raises(UntranslatableError):
            translate_window_measure(_win("d"), dims, TABLES)


class TestWholeTableLod:
    def test_empty_over_classifies_as_lod_with_no_partition(self):
        c = classify_dimension_expr(f"MAX({INT_DATE}) OVER ()")
        assert c["kind"] == "lod_window"
        assert c["partition_by"] == []
        assert c["inner_agg"] == "MAX"

    def test_translates_to_group_aggregate_with_empty_braces(self):
        c = classify_dimension_expr("MAX(source.DATE_KEY) OVER ( )")
        out = translate_dimension(_dim("Latest Key", "x", "lod_window", **{
            k: c[k] for k in ("inner_agg", "inner_expr", "partition_by")}), TABLES)
        assert out["ts_expr"] == "group_aggregate ( max ( [FACT::DATE_KEY] ) , { } , { } )"
        assert [a["kind"] for a in out["annotations"]] == ["whole_table_lod"]

    @pytest.mark.parametrize("expr", [
        "SUM(x) OVER (ORDER BY d)",
        "ROW_NUMBER() OVER ()",
        "SUM(x) OVER () + 1",
    ])
    def test_other_window_shapes_stay_unsupported(self, expr):
        assert classify_dimension_expr(expr)["kind"] == "unsupported"

    def test_partitioned_lod_unchanged(self):
        c = classify_dimension_expr("SUM(source.x) OVER (PARTITION BY source.r)")
        assert c["partition_by"] == ["source.r"]


# --- BL-638: a row compared to a whole-table OVER () dimension -------------------
from ts_cli.databricks.mv_parse import parse_metric_view  # noqa: E402
from ts_cli.databricks.mv_translate import translate_metric_view  # noqa: E402

MV = """
version: 1.1
source: cat.sch.fact
filter: coalesce(source.IS_DELETED, false) = false
dimensions:
  - name: record_month
    expr: "TO_DATE(CAST(source.DATE_KEY AS STRING), 'yyyyMMdd')"
    display_name: Month
  - name: latest_month
    expr: "MAX(TO_DATE(CAST(source.DATE_KEY AS STRING), 'yyyyMMdd')) OVER ()"
    display_name: Latest Data Month
  - name: is_mtd
    expr: {flag}
measures:
  - name: Opening
    expr: SUM(source.BAL)
    window: [{{order: record_month, semiadditive: first, range: current}}]
  - name: Closed MTD
    expr: SUM(source.BAL) FILTER (WHERE record_month = latest_month)
"""


def _run(flag="record_month = latest_month", mv=MV):
    parsed = parse_metric_view(mv.format(flag=flag))
    return translate_metric_view(parsed, {"source": "FACT", "d": "DIM"})


def _by(out, name):
    return next(e for e in out["translated"] if e["name"] == name)


class TestLatestPeriodFlag:
    def test_flag_becomes_a_scalar_subquery(self):
        out = _run()
        flag = _by(out, "is_mtd")
        assert flag["ts_expr"] == (
            'sql_bool_op ( "{0} = (SELECT MAX(TO_DATE(CAST(DATE_KEY AS STRING), '
            "'yyyyMMdd')) FROM cat.sch.fact WHERE coalesce(IS_DELETED, false) = false)\" , "
            "[formula_Month] )")
        assert flag["annotations"][0]["kind"] == "subquery_passthrough"

    def test_latest_dimension_itself_is_whole_table(self):
        assert _by(_run(), "latest_month")["ts_expr"].endswith(", { } , { } )")

    def test_reversed_operands_keep_the_order(self):
        flag = _by(_run("latest_month > record_month"), "is_mtd")
        assert flag["ts_expr"].startswith('sql_bool_op ( "(SELECT MAX(')
        assert ') > {0}" , [formula_Month] )' in flag["ts_expr"]

    def test_window_order_uses_the_int_key(self):
        assert _by(_run(), "Opening")["ts_expr"].endswith("{ [FACT::DATE_KEY] } )")

    def test_measure_referencing_it_is_flagged_for_verification(self):
        notes = [a["kind"] for a in _by(_run(), "Closed MTD")["annotations"]]
        assert "pending_verification" in notes

    @pytest.mark.parametrize("flag", [
        "record_month = latest_month AND source.BAL > 0",
        "DATEDIFF(record_month, latest_month)",
        "latest_month = latest_month",
    ])
    def test_other_shapes_are_skipped_not_emitted(self, flag):
        out = _run(flag)
        skip = next(s for s in out["skipped"] if s["name"] == "is_mtd")
        assert "BL-638" in skip["reason"]

    def test_joined_column_in_the_latest_dimension_is_skipped(self):
        mv = MV.replace("MAX(TO_DATE(CAST(source.DATE_KEY AS STRING), 'yyyyMMdd')) OVER ()",
                        "MAX(d.MONTH_START) OVER ()").replace(
            "filter:", "joins:\n  - name: d\n    source: cat.sch.dim\n    on: source.K = d.K\nfilter:")
        out = _run(mv=mv)
        skip = next(s for s in out["skipped"] if s["name"] == "is_mtd")
        assert "BL-638" in skip["reason"] and "source column" in skip["reason"]


# --- review round 1 (PR #770) ----------------------------------------------------
def _mv(**subs):
    mv = MV
    for old, new in subs.items():
        mv = mv.replace(old, new)
    return mv


def _flag(out):
    return next((e for e in out["translated"] if e["name"] == "is_mtd"), None)


def _skip(out, name="is_mtd"):
    return next(s for s in out["skipped"] if s["name"] == name)


class TestReviewRound1:
    @pytest.mark.parametrize("flag", [
        '"-- it\'s the month-to-date flag\\nrecord_month = latest_month"',
        '"/* month\'s flag */ record_month = latest_month"',
        '"record_month = latest_month -- current month"',
        '"(record_month = latest_month)"',
        '"record_month = (latest_month)"',
    ])
    def test_comments_and_parentheses_still_give_the_subquery(self, flag):
        assert _flag(_run(flag))["ts_expr"].startswith('sql_bool_op ( "{0} = (SELECT MAX(')

    @pytest.mark.parametrize("flag", [
        "source.IS_OPEN AND record_month = latest_month",
        "source.IS_OPEN OR record_month = latest_month",
        "NOT record_month = latest_month",
        "record_month IS NOT NULL = latest_month",
    ])
    def test_looser_operator_on_the_other_side_is_skipped(self, flag):
        assert "BL-638" in _skip(_run(flag))["reason"]

    def test_backslash_in_the_filter_is_refused(self):
        out = _run(mv=_mv(**{"coalesce(source.IS_DELETED, false) = false":
                             "source.CODE LIKE 'A\\\\_%'"}))
        assert "backslash" in _skip(out)["reason"]

    def test_backticked_columns_keep_their_backticks(self):
        out = _run(mv=_mv(**{
            "MAX(TO_DATE(CAST(source.DATE_KEY AS STRING), 'yyyyMMdd')) OVER ()":
                "MAX(source.`Month Start`) OVER ()",
            "filter: coalesce(source.IS_DELETED, false) = false":
                'filter: "`source`.`Is Deleted` = false"'}))
        assert _flag(out)["ts_expr"] == (
            'sql_bool_op ( "{0} = (SELECT MAX(`Month Start`) FROM cat.sch.fact '
            'WHERE `Is Deleted` = false)" , [formula_Month] )')

    @pytest.mark.parametrize("source", ["sch.fact", "fact"])
    def test_short_source_name_is_refused(self, source):
        out = _run(mv=_mv(**{"source: cat.sch.fact": f"source: {source}"}))
        assert "three-part" in _skip(out)["reason"]

    def test_filter_comment_and_newline_do_not_reach_the_template(self):
        out = _run(mv=_mv(**{"filter: coalesce(source.IS_DELETED, false) = false":
                             "filter: |\n  source.IS_DELETED = false -- live rows\n  AND source.BAL > 0"}))
        ts = _flag(out)["ts_expr"]
        assert "--" not in ts and "\n" not in ts
        assert "WHERE IS_DELETED = false" in ts
        assert ts.endswith('AND BAL > 0)" , [formula_Month] )')

    def test_over_argument_naming_an_earlier_dimension_is_skipped(self):
        mv = _mv(**{"MAX(TO_DATE(CAST(source.DATE_KEY AS STRING), 'yyyyMMdd')) OVER ()":
                    "MAX(record_month) OVER ()"})
        out = _run(mv=mv)
        assert "unprobed" in _skip(out, "latest_month")["reason"]
        # the flag names the skipped dimension, so it is skipped too
        assert _flag(out) is None and _skip(out)["name"] == "is_mtd"

    def test_any_value_measure_gets_the_note(self):
        mv = MV + "  - name: Months Behind\n    expr: DATEDIFF(ANY_VALUE(latest_month), MAX(record_month))\n"
        ent = _by(_run(mv=mv), "Months Behind")
        assert "pending_verification" in [a["kind"] for a in ent["annotations"]]

    def test_unbalanced_over_argument_stays_unsupported(self):
        assert classify_dimension_expr(
            "MAX(source.a) - MIN(source.b) OVER ()")["kind"] == "unsupported"


class TestReviewRound2:
    SKIPPED_EARLIER = """
version: 1.1
source: cat.sch.fact
dimensions:
  - name: order_date
    expr: MAKE_DATE(YEAR(source.order_date), MONTH(source.order_date), 1)
  - name: latest_month
    expr: MAX(order_date) OVER ()
  - name: is_latest_month
    expr: order_date = latest_month
measures:
  - name: n
    expr: COUNT(1)
"""

    def test_skipped_earlier_dimension_is_not_read_as_the_column(self):
        out = translate_metric_view(parse_metric_view(self.SKIPPED_EARLIER), {"source": "FACT"})
        names = {s["name"] for s in out["skipped"]}
        assert {"order_date", "latest_month", "is_latest_month"} <= names
        assert not any("sql_bool_op" in (e["ts_expr"] or "") for e in out["translated"])

    def test_cast_type_is_not_a_dimension_name(self):
        mv = """
version: 1.1
source: cat.sch.fact
dimensions:
  - name: date
    expr: source.D
  - name: latest
    expr: MAX(CAST(source.ORDER_TS AS DATE)) OVER ()
measures:
  - name: n
    expr: COUNT(1)
"""
        out = translate_metric_view(parse_metric_view(mv), {"source": "FACT"})
        assert "latest" not in {s["name"] for s in out["skipped"]}
