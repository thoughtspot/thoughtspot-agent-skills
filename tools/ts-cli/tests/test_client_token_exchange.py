"""A 2xx from `auth/token/full` that carries no token exits cleanly.

`_authenticate` read `data["token"]`, so a 200 without one (a proxy's or SSO page's
JSON, an empty object, a non-JSON body) raised a bare KeyError/ValueError traceback,
where a 401/403 on the same call gives a one-paragraph SystemExit naming the profile.
Both password and secret-key auth take the same path.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ts_cli.client import ThoughtSpotClient

_BASE = {"base_url": "https://example.thoughtspot.cloud", "username": "u"}


def _client(monkeypatch, kind):
    monkeypatch.setenv("TS_CRED", "fake-credential")
    profile = {**_BASE, f"{kind}_env": "TS_CRED"}
    with patch("ts_cli.client.load_profiles", return_value={"p": profile}):
        return ThoughtSpotClient("p")


def _answer(status, body=None, json_error=False):
    resp = MagicMock(status_code=status)
    if json_error:
        resp.json.side_effect = ValueError("Expecting value")
    else:
        resp.json.return_value = body
    return resp


@pytest.mark.parametrize("kind", ["password", "secret_key"])
@pytest.mark.parametrize("answer", [
    _answer(200, {}),
    _answer(200, {"token": ""}),
    _answer(200, ["not", "an", "object"]),
    _answer(200, json_error=True),
])
def test_a_2xx_without_a_token_exits_with_a_message(monkeypatch, kind, answer):
    client = _client(monkeypatch, kind)
    client._session = MagicMock()
    client._session.post.return_value = answer
    with pytest.raises(SystemExit) as exc:
        client._authenticate()
    message = str(exc.value)
    assert "Authentication failed for profile 'p'" in message
    assert "answered 200 without a token" in message
    assert "fake-credential" not in message


@pytest.mark.parametrize("kind", ["password", "secret_key"])
def test_a_token_is_returned_with_its_expiry(monkeypatch, kind):
    client = _client(monkeypatch, kind)
    client._session = MagicMock()
    client._session.post.return_value = _answer(
        200, {"token": "tok", "expiration_time_in_millis": 5})
    assert client._authenticate() == ("tok", 5)
