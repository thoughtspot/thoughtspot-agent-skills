"""Unit tests for render_check — the Liveboard render-verify classifier.

The error body shape below is the real one observed live: an imported-but-broken
liveboard returns 500 with the message nested at error.message.debug.debug.
"""
from ts_cli.render_check import classify_render, extract_error, render_summary

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
