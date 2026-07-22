"""Unit tests for ts_cli.sisense.answers.

Pure functions, no live cluster. Synthetic inventories via `_inv()`. Covers widget->chart-type
mapping, build_liveboard_result (Answers emitted with the Sisense-resolved ts_chart + status,
carried into visual_rows), and the Sisense-local filter-chip extraction (member IN, exclude
NOT_IN, numeric-range presets incl. the mixed inclusive/exclusive two-sided range).
"""
from ts_cli.sisense.answers import (chart_type_for, build_liveboard_result,
                                     extract_liveboard_filters)


def test_chart_type_mapping():
    assert chart_type_for("chart/column")[0] == "COLUMN"
    assert chart_type_for("chart/bar", "stacked")[0] == "STACKED_BAR"   # stacked subtype
    assert chart_type_for("chart/column", "stacked")[0] == "STACKED_COLUMN"
    assert chart_type_for("indicator")[0] == "KPI"
    assert chart_type_for("pivot2")[0] == "PIVOT_TABLE"
    assert chart_type_for("tablewidget")[0] == "GRID_TABLE"            # not legacy TABLE
    assert chart_type_for("chart/bubble")[0] == "SCATTER"              # bubble -> scatter
    assert chart_type_for("richtexteditor")[0] is None                # text widget -> skip
    assert chart_type_for("chart/gizmo")[0] == "GRID_TABLE"           # unknown -> default


def _field(dim, panel, kind="dimension", level=None):
    return {"kind": kind, "dim": dim, "agg": None, "title": "",
            "formula": None, "level": level, "panel": panel}


def _inv():
    return {
        "source": "Shop",
        "tables": [],
        "relations": [],
        "widgets": [
            {"oid": "w1", "title": "Revenue by Category", "wtype": "chart/column",
             "subtype": "", "filters": [],
             "fields": [_field("[Commerce.Category]", "categories"),
                        _field("[Commerce.Revenue]", "values", kind="measure")]},
            {"oid": "w2", "title": "Revenue over time", "wtype": "chart/line",
             "subtype": "", "fields": [
                 _field("[Commerce.Date (Calendar)]", "x-axis", level="months"),
                 _field("[Commerce.Revenue]", "values", kind="measure")],
             "filters": [{"kind": "top_n", "dim": "[Commerce.Category]",
                          "operator": "top", "values": [5], "raw": {"top": 5}}]},
            {"oid": "w3", "title": "notes", "wtype": "richtexteditor",
             "subtype": "", "fields": [], "filters": []},
        ],
        "dashboard": {"title": "Sales", "filters": []},
        "counts": {}, "warnings": [],
    }


COLS = ["Category", "Revenue", "Date"]
MEAS = {"Revenue"}


def test_build_liveboard_result_uses_resolved_chart_and_status():
    res = build_liveboard_result(_inv(), "Sample ECommerce", None, COLS, MEAS, {})
    assert res["report_name"] == "Sales"                       # dashboard title
    assert len(res["answers"]) == 2                            # richtext widget skipped
    assert res["liveboard"] is not None
    # Our resolved ts_chart wins (COLUMN / LINE), NOT re-inferred by the emitter's mark path.
    types = [a["answer"]["chart"]["type"] for a in res["answers"]]
    assert types == ["COLUMN", "LINE"]
    rows = res["visual_rows"]
    assert [r["ts_chart"] for r in rows] == ["COLUMN", "LINE", "(skipped)"]
    assert [r["status"] for r in rows] == ["Migrated", "Migrated", "Skipped"]


def test_chart_missing_measure_flagged_needs_review():
    inv = _dash([])
    inv["widgets"] = [{"oid": "w", "title": "Cats only", "wtype": "chart/column",
                       "subtype": "", "filters": [],
                       "fields": [_field("[Commerce.Category]", "categories")]}]
    inv["dashboard"]["title"] = "D"
    res = build_liveboard_result(inv, "M", None, ["Category"], set(), {})
    row = res["visual_rows"][0]
    assert row["status"] == "NEEDS REVIEW" and "measure" in row["note"]


def test_default_report_name_from_model():
    inv = _inv()
    inv["dashboard"]["title"] = ""
    res = build_liveboard_result(inv, "Fallback Model", None, COLS, MEAS, {})
    assert res["report_name"] == "Fallback Model"


def _dash(filters):
    return {"source": "S", "tables": [], "relations": [], "widgets": [],
            "dashboard": {"title": "D", "filters": filters}, "counts": {}, "warnings": []}


def test_filter_member_in():
    inv = _dash([{"kind": "member", "dim": "[country.Country]", "operator": "members",
                  "values": ["US", "CA"], "raw": {"members": ["US", "CA"]}}])
    chips = extract_liveboard_filters(inv)
    assert len(chips) == 1
    c = chips[0]
    assert c["column"] == ["Country"]
    assert c["generic_filter"] == {"oper": "IN", "values": ["US", "CA"]}


def test_filter_exclude_not_in():
    inv = _dash([{"kind": "exclude", "dim": "[country.Country]", "operator": "exclude",
                  "values": ["XX"], "raw": {"exclude": {"members": ["XX"]}}}])
    chips = extract_liveboard_filters(inv)
    assert chips[0]["generic_filter"] == {"oper": "NOT_IN", "values": ["XX"]}


def test_filter_range_presets():
    inv = _dash([
        {"kind": "range", "dim": "[Commerce.Revenue]", "operator": "range",
         "values": [10, 100], "raw": {"from": 10, "to": 100}},          # -> BW_INC
        {"kind": "range", "dim": "[Commerce.Cost]", "operator": "range",
         "values": [42], "raw": {"equals": 42}},                        # -> EQ
        {"kind": "range", "dim": "[Commerce.Qty]", "operator": "range",
         "values": [5], "raw": {"from": 5}},                            # single-sided -> GE
        {"kind": "range", "dim": "[Commerce.Disc]", "operator": "range",
         "values": [9], "raw": {"to": 9}},                              # single-sided -> LE
    ])
    chips = extract_liveboard_filters(inv)
    gfs = [c["generic_filter"] for c in chips]
    assert gfs[0] == {"oper": "BW_INC", "values": [10, 100]}
    assert gfs[1] == {"oper": "EQ", "values": [42]}
    assert gfs[2] == {"oper": "GE", "values": [5]}
    assert gfs[3] == {"oper": "LE", "values": [9]}


def test_filter_exclusive_single_sided():
    inv = _dash([{"kind": "range", "dim": "[Commerce.Revenue]", "operator": "range",
                  "values": [0], "raw": {"fromNotEqual": 0}}])           # -> GT (exclusive)
    chips = extract_liveboard_filters(inv)
    assert chips[0]["generic_filter"] == {"oper": "GT", "values": [0]}


def test_filter_mixed_two_sided_range_keeps_both_bounds():
    # [10, 100): a mixed inclusive/exclusive range must NOT collapse to an open-ended GE 10.
    inv = _dash([{"kind": "range", "dim": "[Commerce.Revenue]", "operator": "range",
                  "values": [10, 100], "raw": {"from": 10, "toNotEqual": 100}}])
    gf = extract_liveboard_filters(inv)[0]["generic_filter"]
    assert gf["values"] == [10, 100]                 # both bounds retained (no silent drop)
    assert gf["oper"] in ("BW_INC", "BW")


def test_filter_both_exclusive_two_sided():
    inv = _dash([{"kind": "range", "dim": "[Commerce.Revenue]", "operator": "range",
                  "values": [10, 100], "raw": {"fromNotEqual": 10, "toNotEqual": 100}}])
    gf = extract_liveboard_filters(inv)[0]["generic_filter"]
    assert gf == {"oper": "BW", "values": [10, 100]}


def test_filter_top_n_skipped_and_exposure_check():
    inv = _dash([
        {"kind": "top_n", "dim": "[Commerce.Category]", "operator": "top",
         "values": [3], "raw": {"top": 3}},                             # per-viz, not a chip
        {"kind": "member", "dim": "[Commerce.Ghost]", "operator": "members",
         "values": ["z"], "raw": {"members": ["z"]}},                   # column not on model
    ])
    # exposure check on: top-N skipped, ghost column dropped
    chips = extract_liveboard_filters(inv, ["Country", "Revenue"], {"Revenue"})
    assert chips == []
