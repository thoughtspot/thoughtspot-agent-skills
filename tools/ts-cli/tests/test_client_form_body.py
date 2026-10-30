"""ThoughtSpotClient.request() must not label a form body as JSON.

The v1 /dependency family (`ts dependency cascade-*`) takes a form-encoded body and
answers 415 to `Content-Type: application/json` (live-verified 2026-10-30). The client
forced that header on every non-multipart call, so a `data={...}` form could not be
sent through it at all.

No live connection: client._session is a MagicMock.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ts_cli.client import ThoughtSpotClient


def _client(tmp_path: Path) -> ThoughtSpotClient:
    profile = {"name": "P", "base_url": "https://test.thoughtspot.cloud",
               "username": "u", "token_env": "THOUGHTSPOT_TOKEN_P"}
    with patch("ts_cli.client.load_profiles", return_value={"P": profile}):
        client = ThoughtSpotClient("P")
    client._token_path = lambda: tmp_path / "token.txt"
    client._expiry_path = lambda: tmp_path / "expiry.txt"
    client._token = "tok"
    ok = MagicMock(status_code=200, ok=True, text="{}")
    client._session = MagicMock()
    client._session.request.return_value = ok
    return client


def _sent_headers(client: ThoughtSpotClient) -> dict:
    return client._session.request.call_args.kwargs["headers"]


def test_form_body_does_not_get_json_content_type(tmp_path):
    client = _client(tmp_path)
    client.request("POST", "/callosum/v1/dependency/x", data={"type": "LOGICAL_TABLE"})
    headers = _sent_headers(client)
    assert "Content-Type" not in headers
    assert headers["Authorization"] == "Bearer tok"
    assert client._session.request.call_args.kwargs["data"] == {"type": "LOGICAL_TABLE"}


def test_json_body_still_gets_json_content_type(tmp_path):
    client = _client(tmp_path)
    client.request("POST", "/api/rest/2.0/metadata/search", json={"metadata": []})
    assert _sent_headers(client)["Content-Type"] == "application/json"


def test_bodyless_call_still_gets_json_content_type(tmp_path):
    client = _client(tmp_path)
    client.request("GET", "/api/rest/2.0/system")
    assert _sent_headers(client)["Content-Type"] == "application/json"


def test_string_data_keeps_json_content_type(tmp_path):
    # A pre-serialised JSON string is not a form; leave its behaviour unchanged.
    client = _client(tmp_path)
    client.request("POST", "/api/rest/2.0/x", data='{"a": 1}')
    assert _sent_headers(client)["Content-Type"] == "application/json"
