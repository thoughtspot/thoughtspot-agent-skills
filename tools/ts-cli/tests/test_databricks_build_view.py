"""Tests for ts_cli/databricks/mv_build_view.py (Task 11).

build_view_ddl: MV YAML doc -> CREATE OR REPLACE VIEW ... WITH METRICS DDL,
with a `$$` dollar-quote-termination guard. default_view_name: snake_case
view-name generation. build_summary: aggregate per-MV build_metric_view
results into the stdout JSON contract / Unmapped-Report source.
"""
import pytest

from ts_cli.databricks.mv_build_view import (
    build_summary,
    build_view_ddl,
    default_view_name,
)


class TestBuildViewDdl:
    def test_wrapper_and_yaml(self):
        doc = {"version": "1.1", "source": "c.s.fact",
               "dimensions": [{"name": "region", "expr": "source.REGION"}],
               "measures": [{"name": "amount", "expr": "SUM(source.AMOUNT)"}]}
        ddl = build_view_ddl(doc, catalog="c", schema="s", view_name="fact_mv")
        assert ddl.startswith("CREATE OR REPLACE VIEW c.s.fact_mv\nWITH METRICS LANGUAGE YAML AS $$\n")
        assert ddl.rstrip().endswith("$$")
        assert "version: '1.1'" in ddl or 'version: "1.1"' in ddl or "version: 1.1" in ddl

    def test_key_order_preserved_sort_keys_false(self):
        # version, then source, then dimensions, then measures -- the emit
        # order build_metric_view establishes (schema key order). If
        # sort_keys were not False, "dimensions"/"measures"/"source"/"version"
        # would be alphabetized instead.
        doc = {"version": "1.1", "source": "c.s.fact",
               "dimensions": [{"name": "region", "expr": "source.REGION"}],
               "measures": [{"name": "amount", "expr": "SUM(source.AMOUNT)"}]}
        ddl = build_view_ddl(doc, catalog="c", schema="s", view_name="fact_mv")
        i_version = ddl.index("version")
        i_source = ddl.index("source")
        i_dimensions = ddl.index("dimensions")
        i_measures = ddl.index("measures")
        assert i_version < i_source < i_dimensions < i_measures

    def test_dollar_dollar_guard(self):
        doc = {"version": "1.1", "source": "c.s.f",
               "dimensions": [{"name": "x", "expr": "concat(a, '$$')"}], "measures": []}
        with pytest.raises(ValueError, match=r"\$\$"):
            build_view_ddl(doc, catalog="c", schema="s", view_name="f_mv")

    def test_no_joins_or_filter_omitted_cleanly(self):
        doc = {"version": "1.1", "source": "c.s.fact", "dimensions": [], "measures": []}
        ddl = build_view_ddl(doc, catalog="cat1", schema="sch1", view_name="v_mv")
        assert ddl.startswith("CREATE OR REPLACE VIEW cat1.sch1.v_mv\n")
        assert "joins" not in ddl
        assert "filter" not in ddl


class TestViewName:
    def test_default(self):
        assert default_view_name("Dunder Mifflin Sales", "DM_ORDER_DETAIL") == \
            "dunder_mifflin_sales_dm_order_detail_mv"

    def test_lowercases_and_snakes_mixed_punctuation(self):
        assert default_view_name("Q1 Sales!!", "fact-table") == "q1_sales_fact_table_mv"


class TestBuildSummary:
    def test_aggregates_across_multiple_mvs(self):
        mvs = [
            {"view_name": "fact_a_mv", "file": "fact_a_mv.sql",
             "yaml_doc": {"version": "1.1", "source": "c.s.fact_a",
                          "dimensions": [{"name": "d1", "expr": "x"}],
                          "measures": [{"name": "m1", "expr": "SUM(x)"},
                                       {"name": "m2", "expr": "SUM(y)"}],
                          "filter": "x > 0"},
             "skipped": [{"name": "Bad Col", "role": "measure", "reason": "nope"}],
             "warnings": ["warn 1"]},
            {"view_name": "fact_b_mv", "file": "fact_b_mv.sql",
             "yaml_doc": {"version": "1.1", "source": "c.s.fact_b",
                          "dimensions": [], "measures": [{"name": "m3", "expr": "SUM(z)"}]},
             "skipped": [], "warnings": ["warn 2"]},
        ]
        summary = build_summary("Dunder Mifflin", mvs)
        assert summary["model_name"] == "Dunder Mifflin"
        assert summary["metric_views"] == [
            {"view_name": "fact_a_mv", "source": "c.s.fact_a", "dimensions": 1,
             "measures": 2, "filter_applied": True, "file": "fact_a_mv.sql"},
            {"view_name": "fact_b_mv", "source": "c.s.fact_b", "dimensions": 0,
             "measures": 1, "filter_applied": False, "file": "fact_b_mv.sql"},
        ]
        assert summary["skipped"] == [{"name": "Bad Col", "role": "measure", "reason": "nope"}]
        assert summary["warnings"] == ["warn 1", "warn 2"]

    def test_single_mv_no_skips_or_warnings(self):
        mvs = [{"view_name": "x_mv", "file": "x_mv.sql",
                "yaml_doc": {"version": "1.1", "source": "c.s.x",
                             "dimensions": [{"name": "d", "expr": "x"}], "measures": []}}]
        summary = build_summary("M", mvs)
        assert summary["model_name"] == "M"
        assert summary["metric_views"][0] == {
            "view_name": "x_mv", "source": "c.s.x", "dimensions": 1,
            "measures": 0, "filter_applied": False, "file": "x_mv.sql"}
        assert summary["skipped"] == []
        assert summary["warnings"] == []

    def test_empty_mvs_list(self):
        summary = build_summary("Empty Model", [])
        assert summary == {"model_name": "Empty Model", "metric_views": [],
                           "skipped": [], "warnings": []}
