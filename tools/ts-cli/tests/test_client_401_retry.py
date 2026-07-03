# tools/ts-cli/tests/test_client_401_retry.py
"""Unit tests for ThoughtSpotClient.request() 401 handling (2026-07 audit finding 4.2).

Before this fix, request() exited on a 401 without ever clearing the cached token.
token_env tokens cache with no server-verified expiry and are treated valid for ~23h
(see _read_cached_token), so a rotated/revoked token bricked every `ts` command until
a manual `ts auth logout` or the 23h window lapsed.

Fix under test: on 401, clear the cached token, force one fresh authentication, and
retry the request exactly once. A second 401 fails with the original error (no
infinite retry loop). The auth token-exchange endpoint itself must never enter this
retry path (it doesn't reach request() today, but the guard is defense in depth).

No live ThoughtSpot connection: client._session is replaced with a MagicMock, and
the token cache is redirected into pytest's tmp_path fixture for full isolation from
any real ts_token_<slug>.txt files on disk.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ts_cli.client import ThoughtSpotClient, _AUTH_TOKEN_PATH


def _make_client(tmp_path: Path, profile_name: str = "Production", **profile_kwargs) -> ThoughtSpotClient:
    """Build a ThoughtSpotClient with a synthetic profile and an isolated token cache."""
    profile = {
        "name": profile_name,
        "base_url": "https://test.thoughtspot.cloud",
        "username": "user@test.com",
        "token_env": "THOUGHTSPOT_TOKEN_PRODUCTION",
        **profile_kwargs,
    }
    with patch("ts_cli.client.load_profiles", return_value={profile_name: profile}):
        client = ThoughtSpotClient(profile_name)
    # Redirect the token cache into tmp_path so tests never touch (or race with)
    # real ts_token_<slug>.txt files in the OS temp directory.
    client._token_path = lambda: tmp_path / "token.txt"
    client._expiry_path = lambda: tmp_path / "expiry.txt"
    return client


def _resp(status_code: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.ok = 200 <= status_code < 300
    r.text = ""
    r.json.side_effect = ValueError("no json")
    return r


class TestSingleRetryOn401:
    def test_401_then_200_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "fresh-token")
        client = _make_client(tmp_path)
        client._write_cached_token("stale-token", None)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(401), _resp(200)]

        resp = client.request("GET", "/api/rest/2.0/whoami")

        assert resp.status_code == 200
        assert client._session.request.call_count == 2

    def test_401_then_200_rewrites_token_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "fresh-token")
        client = _make_client(tmp_path)
        client._write_cached_token("stale-token", None)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(401), _resp(200)]

        client.request("GET", "/api/rest/2.0/whoami")

        assert client._token_path().read_text() == "fresh-token"

    def test_401_clears_in_memory_token_before_retry(self, tmp_path, monkeypatch):
        """Both the on-disk cache AND the in-memory self._token must be dropped —
        otherwise _auth_headers() would keep resending the stale in-memory value
        on the retry instead of forcing a fresh authenticate()."""
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "fresh-token")
        client = _make_client(tmp_path)
        client._token = "stale-in-memory-token"

        client._session = MagicMock()
        seen_auth_headers = []

        def _capture(method, url, headers=None, **kwargs):
            seen_auth_headers.append(headers["Authorization"])
            return _resp(401) if len(seen_auth_headers) == 1 else _resp(200)

        client._session.request.side_effect = _capture

        client.request("GET", "/api/rest/2.0/whoami")

        assert seen_auth_headers == ["Bearer stale-in-memory-token", "Bearer fresh-token"]

    def test_401_twice_fails_cleanly(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "still-bad-token")
        client = _make_client(tmp_path)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(401), _resp(401)]

        with pytest.raises(SystemExit):
            client.request("GET", "/api/rest/2.0/whoami")

        # Exactly one retry attempt — not an infinite loop.
        assert client._session.request.call_count == 2

    def test_401_twice_reports_the_final_401_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "still-bad-token")
        client = _make_client(tmp_path)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(401), _resp(401)]

        with pytest.raises(SystemExit):
            client.request("GET", "/api/rest/2.0/whoami")

        err = capsys.readouterr().err
        assert "401" in err

    def test_non_401_error_does_not_retry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "token")
        client = _make_client(tmp_path)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(500)]

        with pytest.raises(SystemExit):
            client.request("GET", "/api/rest/2.0/whoami")

        assert client._session.request.call_count == 1

    def test_success_on_first_try_does_not_retry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "token")
        client = _make_client(tmp_path)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(200)]

        resp = client.request("GET", "/api/rest/2.0/whoami")

        assert resp.status_code == 200
        assert client._session.request.call_count == 1


class TestAuthEndpointNeverRetries:
    def test_auth_token_path_401_does_not_enter_retry_path(self, tmp_path, monkeypatch):
        """Defense in depth: a 401 from the token-exchange endpoint itself must
        never trigger clear-cache-and-retry (that endpoint IS the authentication
        call — retrying it the same way would be a wasted round-trip at best and
        a recursive loop at worst)."""
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "token")
        client = _make_client(tmp_path)

        client._session = MagicMock()
        client._session.request.side_effect = [_resp(401)]

        with pytest.raises(SystemExit):
            client.request("POST", _AUTH_TOKEN_PATH)

        assert client._session.request.call_count == 1
