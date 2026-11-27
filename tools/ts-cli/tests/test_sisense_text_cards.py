"""BloX banners with no data fields read as text widgets; tablewidgetagg maps to a grid."""
from ts_cli.sisense.allowlist import blox_text, widget_unsupported
from ts_cli.sisense.answers import chart_type_for, _widget_answer
from ts_cli.sisense.parsing import parse_widget


def _blox(items=None, text="Candidates at each stage <span id='d'>All time</span>"):
    return {"oid": "b1", "type": "BloX", "subtype": "BloX", "title": "",
            "metadata": {"panels": [{"name": "Items", "items": items or []},
                                    {"name": "Values", "items": []}, {"name": "filters", "items": []}]},
            "style": {"currentCard": {"body": [{"type": "Container", "items": [
                {"type": "TextBlock", "text": text}]}]}, "currentConfig": {}, "currentCardName": "default",
                "narration": {}},
            "script": "widget.on('ready', function(){ document.querySelector('#d').innerText = 'x'; });"}


def test_blox_without_data_is_a_text_card():
    w = _blox()
    assert blox_text(w) == "Candidates at each stage <span id='d'>All time</span>"
    assert "script" not in widget_unsupported(w)
    assert not any(u.startswith("panels of widget type") for u in widget_unsupported(w))
    parsed = parse_widget(w, [])
    assert parsed["text_card"] is True
    assert parsed["richtext"]["html"].startswith("Candidates at each stage")


def test_blox_text_card_is_skipped_not_flagged():
    parsed = parse_widget(_blox(), [])
    a, tile, row = _widget_answer(parsed, 0, "Main", "M", None,
                                  {"norm": {}, "measures": set(), "dash_filters": [], "lb_cols": set()},
                                  build_answer=None)
    assert a is None and tile is None
    assert row["status"] == "Skipped" and "text banner" in row["note"]


def test_blox_with_data_is_still_flagged():
    w = _blox(items=[{"jaql": {"dim": "[T.Status]", "datatype": "text", "title": "Status"}}])
    assert blox_text(w) is None
    assert "script" in widget_unsupported(w)
    assert chart_type_for("BloX")[1] == "NEEDS REVIEW"


def test_tablewidgetagg_maps_to_grid():
    assert chart_type_for("tablewidgetagg") == ("GRID_TABLE", "Migrated", "") or \
        chart_type_for("tablewidgetagg")[:2] == ("GRID_TABLE", "Migrated")
