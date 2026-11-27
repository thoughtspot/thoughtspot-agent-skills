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
