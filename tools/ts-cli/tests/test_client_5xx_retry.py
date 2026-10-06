"""Unit tests for ThoughtSpotClient.request() transient-error retry (BL-089 1c).

A flaky instance returning 502/503/504 gateway errors (or a dropped connection)
previously hard-failed every `ts` call — and, worse, a 504 HTML page reaching a
caller's `.json()` produced a raw JSONDecodeError traceback (observed live on
se-thoughtspot 2026-07-05, wedging `ts tableau build-model`/`ts tml export`).

Fix under test: request() retries transient gateway statuses (502/503/504) and
connection/timeout errors with exponential backoff, then fails cleanly (one
stderr line + SystemExit) if they persist — never a traceback.

No live connection: client._session is a MagicMock; time.sleep is patched so the
backoff doesn't actually delay the test.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ts_cli.client import ThoughtSpotClient


def _make_client(tmp_path: Path, profile_name: str = "Production") -> ThoughtSpotClient:
    profile = {
        "name": profile_name,
        "base_url": "https://test.thoughtspot.cloud",
        "username": "user@test.com",
        "token_env": "THOUGHTSPOT_TOKEN_PRODUCTION",
    }
    with patch("ts_cli.client.load_profiles", return_value={profile_name: profile}):
        client = ThoughtSpotClient(profile_name)
    client._token_path = lambda: tmp_path / "token.txt"
    client._expiry_path = lambda: tmp_path / "expiry.txt"
    client._token = "tok"  # skip authentication
    return client


def _resp(status_code: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.ok = 200 <= status_code < 300
    r.text = "" if r.ok else "<html>504 Gateway Time-out</html>"
    return r


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("ts_cli.client.time.sleep") as s:
        yield s


class TestTransientRetry:
    def test_504_then_200_succeeds(self, tmp_path):
        client = _make_client(tmp_path)
        client._session = MagicMock()
        client._session.request.side_effect = [_resp(504), _resp(200)]
        resp = client.request("POST", "/api/rest/2.0/metadata/tml/export")
        assert resp.status_code == 200
        assert client._session.request.call_count == 2

    def test_503_then_502_then_200(self, tmp_path):
        client = _make_client(tmp_path)
        client._session = MagicMock()
        client._session.request.side_effect = [_resp(503), _resp(502), _resp(200)]
        resp = client.request("GET", "/api/rest/2.0/metadata/tml/export")
        assert resp.status_code == 200
        assert client._session.request.call_count == 3

    def test_persistent_504_fails_cleanly(self, tmp_path, capsys):
        client = _make_client(tmp_path)
        client._session = MagicMock()
        client._session.request.side_effect = [_resp(504)] * 10
        with pytest.raises(SystemExit):
            client.request("GET", "/api/rest/2.0/metadata/tml/export")
        err = capsys.readouterr().err
        assert "504" in err  # clean diagnostic, not a traceback
        assert "Traceback" not in err

    def test_connection_error_then_200(self, tmp_path):
        client = _make_client(tmp_path)
        client._session = MagicMock()
        client._session.request.side_effect = [
            requests.exceptions.ConnectionError("boom"), _resp(200),
        ]
        resp = client.request("GET", "/api/rest/2.0/metadata/tml/export")
        assert resp.status_code == 200

    def test_500_not_retried(self, tmp_path, capsys):
        # 500 is an application error, not a transient gateway/network fault —
        # retrying would mask real failures. Fail on the first response.
        client = _make_client(tmp_path)
        client._session = MagicMock()
        client._session.request.side_effect = [_resp(500), _resp(200)]
        with pytest.raises(SystemExit):
            client.request("GET", "/api/rest/2.0/metadata/tml/export")
        assert client._session.request.call_count == 1


class TestNonIdempotentNotRetried:
    """A create/import must never be repeated after the server may have processed it.
    2026-09-29: a read timeout on `tml import --create-new` was retried and left four
    identical Tables. Only a failure that provably never reached the server retries."""

    IMPORT = "/api/rest/2.0/metadata/tml/import"

    @staticmethod
    def _client(tmp_path, side_effect):
        client = _make_client(tmp_path)
        client._session = MagicMock()
        client._session.request.side_effect = side_effect
        return client

    @pytest.mark.parametrize("path", [
        "/api/rest/2.0/metadata/tml/import", "/api/rest/2.0/metadata/tml/async/import",
        "/api/rest/2.0/users/create", "/api/rest/2.0/template/variables/create",
    ])
    def test_read_timeout_on_create_is_not_retried(self, tmp_path, capsys, path):
        client = self._client(tmp_path, [requests.exceptions.ReadTimeout("slow"), _resp(200)])
        with pytest.raises(SystemExit):
            client.request("POST", path)
        assert client._session.request.call_count == 1
        assert "not retried" in capsys.readouterr().err

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_gateway_fault_on_import_is_not_retried(self, tmp_path, status):
        client = self._client(tmp_path, [_resp(status), _resp(200)])
        with pytest.raises(SystemExit):
            client.request("POST", self.IMPORT)
        assert client._session.request.call_count == 1

    def test_mid_response_disconnect_on_import_is_not_retried(self, tmp_path):
        client = self._client(tmp_path, [requests.exceptions.ChunkedEncodingError("cut"), _resp(200)])
        with pytest.raises(SystemExit):
            client.request("POST", self.IMPORT)
        assert client._session.request.call_count == 1

    def test_connect_timeout_on_import_is_retried(self, tmp_path):
        # Never reached the server — repeating it cannot duplicate anything.
        client = self._client(tmp_path, [requests.exceptions.ConnectTimeout("no route"), _resp(200)])
        assert client.request("POST", self.IMPORT).status_code == 200
        assert client._session.request.call_count == 2

    def test_refused_connection_on_import_is_retried(self, tmp_path):
        from urllib3.exceptions import MaxRetryError, NewConnectionError
        refused = requests.exceptions.ConnectionError(
            MaxRetryError(None, "/x", reason=NewConnectionError(None, "refused")))
        client = self._client(tmp_path, [refused, _resp(200)])
        assert client.request("POST", self.IMPORT).status_code == 200

    def test_idempotent_calls_still_retry(self, tmp_path):
        for path in ("/api/rest/2.0/metadata/search", "/api/rest/2.0/metadata/delete",
                     "/api/rest/2.0/groups/g1/update", "/api/rest/2.0/ai/instructions/set"):
            client = self._client(tmp_path, [requests.exceptions.ReadTimeout("slow"), _resp(200)])
            assert client.request("POST", path).status_code == 200, path

    def test_explicit_override_wins(self, tmp_path):
        client = self._client(tmp_path, [requests.exceptions.ReadTimeout("slow"), _resp(200)])
        assert client.request("POST", self.IMPORT, idempotent=True).status_code == 200
        client = self._client(tmp_path, [requests.exceptions.ReadTimeout("slow"), _resp(200)])
        with pytest.raises(SystemExit):
            client.request("POST", "/api/rest/2.0/metadata/search", idempotent=False)
