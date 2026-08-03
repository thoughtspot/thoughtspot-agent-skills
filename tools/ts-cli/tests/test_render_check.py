"""Unit tests for render_check — the Liveboard render-verify classifier.

The error body shape below is the real one observed live: an imported-but-broken
liveboard returns 500 with the message nested at error.message.debug.debug.
"""
from ts_cli.render_check import (
    chart_tiles_missing_axis,
    classify_render,
    extract_error,
    render_summary,
)

# The real 500 body from a hand-authored board that imports but fails to render.
BROKEN_500 = {
    "error": {
        "message": {
            "debug": {
                "code": 12325,
                "incident_id_guid": "5757e177-ad46-4ea9-b89d-c4944d442e84",
                "debug": '["Error Code: INTERNAL_ERROR Incident Id: 5757e177-ad46-4ea9-b89d-c4944d442e84'
                         '\\nError Message: No data source found for the query.",""]',
            }
        }
    }
}

OK_200 = {
    "metadata_id": "abc",
    "metadata_name": "New Hires",
    "contents": [{"visualization_id": "v1", "column_names": ["Month", "New Hires"], "data_rows": [[1, 2]]},
                 {"visualization_id": "v2", "column_names": ["Region"], "data_rows": [[1]]}],
}


def test_extract_error_pulls_error_message_from_nested_debug():
    assert extract_error(BROKEN_500) == "No data source found for the query."


def test_extract_error_none_when_no_error_key():
    assert extract_error({"contents": []}) is None
    assert extract_error(OK_200) is None


def test_extract_error_tolerates_plain_string_message():
    assert extract_error({"error": {"message": "boom"}}) == "boom"


def test_extract_error_never_raises_on_junk():
    for junk in (None, "", [], 42, {"error": {"message": {"debug": {}}}}):
        extract_error(junk)  # must not raise


def test_classify_render_200_with_contents_is_rendered():
    r = classify_render(200, OK_200)
    assert r == {"rendered": True, "tiles": 2, "error": None}


def test_classify_render_200_without_contents_is_failure():
    # A 200 whose body carries no contents array is not a successful render.
    r = classify_render(200, {"metadata_id": "x"})
    assert r["rendered"] is False


def test_classify_render_200_empty_contents_is_failure():
    # A 200 with an empty contents array rendered nothing — must not pass the gate.
    r = classify_render(200, {"metadata_id": "x", "contents": []})
    assert r == {"rendered": False, "tiles": 0, "error": "no visualization data returned"}


def test_classify_render_500_is_failure_with_message():
    r = classify_render(500, BROKEN_500)
    assert r["rendered"] is False
    assert r["tiles"] == 0
    assert r["error"] == "No data source found for the query."


def test_render_summary_ok_board():
    board = classify_render(200, OK_200)
    s = render_summary("guid-1", board)
    assert s["ok"] is True
    assert s["board"] == "guid-1"
    assert s["tiles_rendered"] == 2
    assert s["failing_tiles"] == []


def test_render_summary_failing_board_names_tiles():
    board = classify_render(500, BROKEN_500)
    per_viz = [
        {"visual": "Good tile", "rendered": True, "tiles": 1, "error": None},
        {"visual": "Bad tile", "rendered": False, "tiles": 0,
         "error": "No data source found for the query."},
    ]
    s = render_summary("guid-1", board, per_viz)
    assert s["ok"] is False
    assert s["error"] == "No data source found for the query."
    assert s["failing_tiles"] == [
        {"visual": "Bad tile", "error": "No data source found for the query."}
    ]


# --- chart_tiles_missing_axis: the blank-chart detector (Gunjan failure mode) ---

def test_missing_axis_flags_linechart_without_axis():
    doc = {"answer": {"name": "NH by Month", "chart": {"type": "LINE"}}}
    assert chart_tiles_missing_axis(doc) == [{"visual": "NH by Month", "chart_type": "LINE"}]


def test_missing_axis_ok_with_axis_configs():
    doc = {"answer": {"name": "x", "chart": {"type": "LINE", "axis_configs": [{"x": ["Month"], "y": ["NH"]}]}}}
    assert chart_tiles_missing_axis(doc) == []


def test_missing_axis_empty_axis_configs_still_flags():
    # an empty axis_configs list is no encoding at all
    doc = {"answer": {"name": "x", "chart": {"type": "COLUMN", "axis_configs": []}}}
    assert chart_tiles_missing_axis(doc) == [{"visual": "x", "chart_type": "COLUMN"}]


def test_missing_axis_advanced_type_uses_custom_chart_config():
    doc = {"answer": {"name": "x", "chart": {"type": "ADVANCED_LINE_COLUMN",
                                             "custom_chart_config": {"configuration": "..."}}}}
    assert chart_tiles_missing_axis(doc) == []


def test_missing_axis_exempts_tables_kpi_pie_geo():
    for ct in ("GRID_TABLE", "PIVOT_TABLE", "KPI", "PIE", "GEO_BUBBLE", "FUNNEL", "TREEMAP"):
        doc = {"answer": {"name": ct, "chart": {"type": ct}}}
        assert chart_tiles_missing_axis(doc) == [], ct


def test_missing_axis_liveboard_flags_only_the_blank_chart_tiles():
    doc = {"liveboard": {"visualizations": [
        {"answer": {"name": "good line", "chart": {"type": "LINE", "axis_configs": [{"x": ["m"]}]}}},
        {"answer": {"name": "blank combo", "chart": {"type": "LINE_COLUMN"}}},
        {"answer": {"name": "pivot", "chart": {"type": "PIVOT_TABLE"}}},
        {"answer": {"name": "blank bar", "chart": {"type": "BAR"}}},
    ]}}
    assert chart_tiles_missing_axis(doc) == [
        {"visual": "blank combo", "chart_type": "LINE_COLUMN"},
        {"visual": "blank bar", "chart_type": "BAR"},
    ]


def test_missing_axis_empty_for_model_and_table_tml():
    assert chart_tiles_missing_axis({"model": {"columns": []}}) == []
    assert chart_tiles_missing_axis({"table": {}}) == []
    assert chart_tiles_missing_axis({}) == []


def test_render_summary_blank_tiles_fail_gate_even_on_data_200():
    board = classify_render(200, {"contents": [{"visualization_id": "v"}]})  # data DOES load
    s = render_summary("g", board, None, [{"visual": "blank", "chart_type": "LINE"}])
    assert s["ok"] is False  # 200 but blank charts -> not ok
    assert s["blank_chart_tiles"] == [{"visual": "blank", "chart_type": "LINE"}]


def test_render_summary_ok_when_data_loads_and_no_blanks():
    board = classify_render(200, {"contents": [{"visualization_id": "v"}]})
    s = render_summary("g", board, None, [])
    assert s["ok"] is True
    assert s["blank_chart_tiles"] == []
