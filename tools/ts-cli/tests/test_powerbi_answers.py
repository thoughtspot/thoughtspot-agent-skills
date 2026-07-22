"""Unit tests for ts_cli.powerbi.answers — PBI report -> build_from_spec spec.

Pure functions, no live cluster. Covers chart-type mapping, leaf resolution, PBIR field
resolution (incl. month -> date bucket), spec assembly (tooltip drop, non-visual skip), and
the end-to-end handoff to the shared build_from_spec (including the ts_chart passthrough).
"""
import json

from ts_cli.powerbi.answers import chart_type_for, _leaf, spec_from_parse
from ts_cli.tableau import liveboard as lb


def test_chart_type_mapping():
    assert chart_type_for("columnChart")[0] == "STACKED_COLUMN"   # PBI columnChart IS stacked
    assert chart_type_for("clusteredColumnChart")[0] == "COLUMN"
    assert chart_type_for("matrix")[0] == "PIVOT_TABLE"
    assert chart_type_for("lineClusteredColumnComboChart")[0] == "LINE_COLUMN"
    assert chart_type_for("slicer")[0] is None                    # non-visual -> skip
    assert chart_type_for("card")[0] == "KPI"


def test_leaf():
    assert _leaf("Region") == "Region"
    assert _leaf("Table.Amount") == "Amount"       # dotted ref -> leaf
    assert _leaf("Average Age") == "Age"           # single-word agg prefix stripped


def _inv():
    return {
        "tables": [
            {"name": "Date", "columns": [{"name": "Date", "dataType": "date"},
                                         {"name": "Month"}], "measures": []},
            {"name": "Fact", "columns": [{"name": "Region"},
                                         {"name": "Amount", "dataType": "double", "summarizeBy": "sum"}],
             "measures": [{"name": "Total", "expression": "SUM(Fact[Amount])"}]},
        ],
        "relationships": [],
        "pages": [
            {"name": "P1", "tooltip": False, "visuals": [
                {"type": "clusteredColumnChart", "title": "Amt by Region",
                 "fields": [{"role": "Category", "field": "Region", "kind": "column"},
                            {"role": "Y", "field": "Total", "kind": "measure"}]},
                {"type": "lineChart",
                 "fields": [{"role": "Category", "field": "Month", "kind": "column"},
                            {"role": "Y", "field": "Total", "kind": "measure"}]},
                {"type": "slicer", "fields": [{"role": "Category", "field": "Region"}]},
            ]},
            {"name": "TT", "tooltip": True, "visuals": []},
        ],
    }


COLS = ["Date", "Month", "Region", "Amount", "Total"]
MEAS = {"Total", "Amount"}


def test_spec_shape():
    spec = spec_from_parse(_inv(), "Sales Model", None, COLS, MEAS, {})
    assert [d["name"] for d in spec["dashboards"]] == ["P1", "TT"]
    p1 = spec["dashboards"][0]
    assert len(p1["visuals"]) == 2                       # slicer skipped
    assert spec["dashboards"][1]["tooltip"] is True      # tooltip page flagged, no visuals
    # first visual: clustered column -> COLUMN, mark carries a non-skip sentinel
    v0 = p1["visuals"][0]
    assert v0["ts_chart"] == "COLUMN" and v0["mark"] == "automatic"
    # month column resolves to the RAW base date column + monthly token — NOT the pre-resolved
    # "Month(Date)"; the shared emitter applies the bucket label once (see _date_bucket_map).
    v1 = p1["visuals"][1]
    names = [f["name"] for f in v1["fields"]]
    assert "Date" in names and "Month(Date)" not in names
    assert v1.get("bucket_tokens", {}).get("Date") == "[Date].MONTHLY"


def test_end_to_end_build_from_spec():
    spec = spec_from_parse(_inv(), "Sales Model", None, COLS, MEAS, {})
    res = lb.build_from_spec(spec)
    assert len(res["answers"]) == 2                       # two real charts (slicer skipped)
    charts = {a["answer"]["chart"]["type"] for a in res["answers"]}
    assert charts == {"COLUMN", "LINE"}                   # ts_chart passthrough honored
    # tooltip page is not a migrated tab
    tt = next(p for p in res["page_rows"] if p["name"] == "TT")
    assert tt["status"] == "NEEDS REVIEW"
    line = next(a for a in res["answers"] if a["answer"]["chart"]["type"] == "LINE")
    assert "[Date].MONTHLY" in line["answer"]["search_query"]
    # regression: a bucketed date emits output column Month(Date) exactly once — never the
    # double-wrapped Month(Month(Date)) the engine rejects (live-verified on ps-internal).
    ccols = [c["column_id"] for c in line["answer"]["chart"]["chart_columns"]]
    assert "Month(Date)" in ccols and "Month(Month(Date))" not in ccols
    assert "Month(Month(Date))" not in json.dumps(line["answer"])
