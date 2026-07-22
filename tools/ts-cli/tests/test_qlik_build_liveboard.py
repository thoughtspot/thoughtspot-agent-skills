"""Unit tests for ts_cli.qlik.answers — Answer + tabbed Liveboard TML.

Pure-function tests over small in-memory IR objects (no live connection).
"""
import yaml

from ts_cli.qlik import answers
from ts_cli.qlik.ir import Chart, QlikApp, Sheet


def make_app(sheets=None, name="MyApp") -> QlikApp:
    return QlikApp(app_name=name, sheets=sheets or [])


def build(app, **kw):
    defaults = dict(model_name="Sales Model")
    defaults.update(kw)
    return answers.build_liveboard_artifacts(app, **defaults)


class TestTabsPerSheet:
    def test_one_tab_per_sheet(self):
        app = make_app(sheets=[
            Sheet(id="s1", title="Overview", charts=[Chart(id="c1", viz_type="kpi")]),
            Sheet(id="s2", title="Detail", charts=[Chart(id="c2", viz_type="table")]),
        ])
        res = build(app)
        tabs = res["liveboard"]["tml"]["liveboard"]["layout"]["tabs"]
        assert len(tabs) == 2
        assert [t["name"] for t in tabs] == ["Overview", "Detail"]
        assert res["counts"]["tabs"] == 2
        assert res["counts"]["sheets"] == 2

    def test_visualization_count_equals_total_charts(self):
        app = make_app(sheets=[
            Sheet(id="s1", title="A", charts=[Chart(id="c1", viz_type="barchart"),
                                              Chart(id="c2", viz_type="kpi")]),
            Sheet(id="s2", title="B", charts=[Chart(id="c3", viz_type="linechart")]),
        ])
        res = build(app)
        viz = res["liveboard"]["tml"]["liveboard"]["visualizations"]
        assert len(viz) == 3
        assert res["counts"]["visualizations"] == 3

    def test_tab_references_its_viz_ids(self):
        app = make_app(sheets=[
            Sheet(id="s1", title="A", charts=[Chart(id="c1", viz_type="barchart")]),
        ])
        res = build(app)
        tab = res["liveboard"]["tml"]["liveboard"]["layout"]["tabs"][0]
        viz_ids = {v["id"] for v in res["liveboard"]["tml"]["liveboard"]["visualizations"]}
        assert set(tab["visualization_ids"]) <= viz_ids


class TestChartTypeMapping:
    def test_known_viz_type_mapped(self):
        app = make_app(sheets=[Sheet(id="s", title="A",
                                     charts=[Chart(id="c", viz_type="barchart",
                                                   dimensions=["Region"], measures=["Sales"])])])
        res = build(app)
        viz = res["liveboard"]["tml"]["liveboard"]["visualizations"][0]
        assert viz["answer"]["chart"]["type"] == "COLUMN"
        entry = res["mapping"]["charts"][0]
        assert entry["status"] == "OK"

    def test_unknown_viz_type_defaults_to_table_and_flagged(self):
        app = make_app(sheets=[Sheet(id="s", title="A",
                                     charts=[Chart(id="c", viz_type="sankey-diagram",
                                                   dimensions=["Region"], measures=["Sales"])])])
        res = build(app)
        viz = res["liveboard"]["tml"]["liveboard"]["visualizations"][0]
        assert viz["answer"]["chart"]["type"] == "GRID_TABLE"
        entry = res["mapping"]["charts"][0]
        assert entry["status"] == "NEEDS REVIEW"
        assert "no ThoughtSpot equivalent" in entry["reason"]
        assert res["counts"]["charts_needs_review"] == 1

    def test_search_query_from_dims_and_measures(self):
        app = make_app(sheets=[Sheet(id="s", title="A",
                                     charts=[Chart(id="c", viz_type="barchart",
                                                   dimensions=["Region"], measures=["Total Sales"])])])
        res = build(app)
        q = res["liveboard"]["tml"]["liveboard"]["visualizations"][0]["answer"]["search_query"]
        assert q == "[Region] [Total Sales]"

    def test_empty_chart_flagged_needs_review(self):
        app = make_app(sheets=[Sheet(id="s", title="A",
                                     charts=[Chart(id="c", viz_type="barchart")])])
        res = build(app)
        entry = res["mapping"]["charts"][0]
        assert entry["status"] == "NEEDS REVIEW"
        assert entry["search_query"] == "[]"


class TestModelReference:
    def test_answer_references_model_by_name(self):
        app = make_app(sheets=[Sheet(id="s", title="A", charts=[Chart(id="c", viz_type="kpi")])])
        res = build(app, model_name="My Model")
        ref = res["liveboard"]["tml"]["liveboard"]["visualizations"][0]["answer"]["tables"][0]
        assert ref == {"name": "My Model"}

    def test_model_fqn_added_when_provided(self):
        app = make_app(sheets=[Sheet(id="s", title="A", charts=[Chart(id="c", viz_type="kpi")])])
        res = build(app, model_name="My Model", model_fqn="guid-123")
        ref = res["liveboard"]["tml"]["liveboard"]["visualizations"][0]["answer"]["tables"][0]
        assert ref["fqn"] == "guid-123"
        assert ref["name"] == "My Model"

    def test_report_name_defaults_to_model_name(self):
        app = make_app(sheets=[])
        res = build(app, model_name="My Model")
        assert res["liveboard"]["tml"]["liveboard"]["name"] == "My Model"

    def test_report_name_override(self):
        app = make_app(sheets=[])
        res = build(app, model_name="My Model", report_name="Exec Dashboard")
        assert res["liveboard"]["tml"]["liveboard"]["name"] == "Exec Dashboard"


class TestYamlOutput:
    def test_liveboard_serializes_to_valid_yaml(self):
        from ts_cli.tml_common import dump_tml_yaml
        app = make_app(sheets=[Sheet(id="s", title="A",
                                     charts=[Chart(id="c", viz_type="barchart",
                                                   dimensions=["R"], measures=["S"])])])
        res = build(app)
        reparsed = yaml.safe_load(dump_tml_yaml(res["liveboard"]["tml"]))
        assert "liveboard" in reparsed
