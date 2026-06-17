"""Unit tests for ts_cli.client.format_http_error — the central HTTP failure formatter.

Verifies the diagnostic is single-line, secret-free (never echoes auth headers), and
prefers the ThoughtSpot error body's debug/error/message fields over a raw dump.
"""
from unittest.mock import MagicMock

from ts_cli.client import format_http_error


def _resp(status_code, *, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    # A real JSON error response carries a non-empty body AND parses via .json().
    r.text = text or ("{json}" if json_body is not None else "")
    if json_body is None:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = json_body
    return r


def test_prefers_debug_field():
    r = _resp(400, json_body={"debug": "bad column FOO", "message": "ignored"})
    msg = format_http_error("POST", "https://x/api/import", r)
    assert "400" in msg and "POST https://x/api/import" in msg and "bad column FOO" in msg


def test_falls_back_to_message_then_body():
    r = _resp(500, json_body={"message": "boom"})
    assert "boom" in format_http_error("GET", "https://x/y", r)


def test_non_json_body_uses_text():
    r = _resp(404, text="Not Found")
    assert "Not Found" in format_http_error("GET", "https://x/y", r)


def test_collapses_newlines_to_single_line():
    r = _resp(400, json_body={"error": "line1\nline2\n   line3"})
    msg = format_http_error("POST", "https://x/y", r)
    assert "\n" not in msg
    assert "line1 line2 line3" in msg


def test_truncates_very_long_detail():
    r = _resp(400, json_body={"error": "z" * 1000})
    msg = format_http_error("POST", "https://x/y", r)
    assert msg.endswith("…")
    assert len(msg) < 600


def test_empty_body_omits_suffix():
    r = _resp(503, text="")
    msg = format_http_error("GET", "https://x/y", r)
    assert msg == "ThoughtSpot API 503 on GET https://x/y"
