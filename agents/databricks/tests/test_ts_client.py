"""
test_ts_client.py — Unit tests for ThoughtSpotClient (Task 2).

Tests cover:
  - ThoughtSpotAPIError: construction, str, configuration scrubbing
  - ThoughtSpotClient.__init__: reads from Databricks Secrets, dbutils fallback
  - Auth — bearer_token: token used directly, cached in memory
  - Auth — password: exchange endpoint called, token+expiry cached
  - Auth — secret_key: same exchange pattern
  - Token refresh on 401: one retry with fresh token
  - HTTP helpers: get(), post() delegate to _request_with_retry
  - whoami(): calls correct endpoint

All tests are offline — no live Databricks or ThoughtSpot instance required.
requests.request and dbutils.secrets.get are mocked throughout.
"""

import importlib
import os
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_ts_client():
    """Import ts_client from the notebooks directory, ensuring it's on sys.path."""
    notebooks_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "notebooks")
    )
    if notebooks_dir not in sys.path:
        sys.path.insert(0, notebooks_dir)
    # Force reload in case a previous test modified the module state
    if "ts_client" in sys.modules:
        return sys.modules["ts_client"]
    return importlib.import_module("ts_client")


def _make_client(mock_dbutils, profile="default"):
    """Instantiate ThoughtSpotClient with mocked dbutils.

    Returns (client, ThoughtSpotAPIError) so tests can reference the error class
    without a separate import.
    """
    mod = _import_ts_client()
    client = mod.ThoughtSpotClient(profile=profile, dbutils=mock_dbutils)
    return client, mod.ThoughtSpotAPIError


# ===========================================================================
# ThoughtSpotAPIError
# ===========================================================================

class TestThoughtSpotAPIError:
    def test_stores_status_code_and_endpoint(self):
        mod = _import_ts_client()
        err = mod.ThoughtSpotAPIError(404, "not found", "/api/rest/2.0/metadata/search")
        assert err.status_code == 404
        assert err.endpoint == "/api/rest/2.0/metadata/search"

    def test_str_includes_status_and_endpoint(self):
        mod = _import_ts_client()
        err = mod.ThoughtSpotAPIError(500, "server error", "/api/rest/2.0/foo")
        assert "500" in str(err)
        assert "/api/rest/2.0/foo" in str(err)

    def test_configuration_scrubbed_from_message(self):
        mod = _import_ts_client()
        body = '{"error": "bad creds", "configuration": {"password": "s3cret", "host": "db"}}'
        err = mod.ThoughtSpotAPIError(401, body, "/api/rest/2.0/auth/token/full")
        assert "s3cret" not in str(err)
        assert "[REDACTED]" in str(err)

    def test_message_without_configuration_unchanged(self):
        mod = _import_ts_client()
        body = '{"error": "not found"}'
        err = mod.ThoughtSpotAPIError(404, body, "/api/rest/2.0/metadata/search")
        assert "not found" in str(err)


# ===========================================================================
# __init__ — profile reading and dbutils fallback
# ===========================================================================

class TestClientInit:
    def test_reads_base_url_from_secrets(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        assert client.base_url == "https://ts.example.com"

    def test_dbutils_none_falls_back_to_builtins(self, profile_secrets):
        """If dbutils=None is passed, the client should look in builtins."""
        import builtins
        mock_dbutils, _ = profile_secrets
        builtins.dbutils = mock_dbutils  # type: ignore[attr-defined]
        try:
            mod = _import_ts_client()
            client = mod.ThoughtSpotClient(profile="default", dbutils=None)
            assert client.base_url == "https://ts.example.com"
        finally:
            del builtins.dbutils

    def test_no_dbutils_raises_runtime_error(self):
        """If dbutils is not provided and not in builtins, raise RuntimeError."""
        import builtins
        # Make sure dbutils is NOT in builtins
        if hasattr(builtins, "dbutils"):
            del builtins.dbutils
        mod = _import_ts_client()
        with pytest.raises(RuntimeError, match="dbutils"):
            mod.ThoughtSpotClient(profile="default", dbutils=None)

    def test_token_not_fetched_at_init(self, profile_secrets):
        """Constructor must not call the auth endpoint eagerly."""
        mock_dbutils, _ = profile_secrets
        with patch("requests.request") as mock_req:
            client, _ = _make_client(mock_dbutils)
            mock_req.assert_not_called()


# ===========================================================================
# Auth — bearer_token
# ===========================================================================

class TestBearerTokenAuth:
    def test_bearer_token_used_directly(self, profile_secrets):
        """bearer_token auth returns the stored token without an HTTP exchange."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request") as mock_req:
            token = client.get_token()
        mock_req.assert_not_called()
        assert token == "test-bearer-token-abc123"

    def test_bearer_token_cached_in_memory(self, profile_secrets):
        """Calling get_token() twice for bearer_token returns same value, no extra calls."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        t1 = client.get_token()
        t2 = client.get_token()
        assert t1 == t2 == "test-bearer-token-abc123"

    def test_bearer_token_no_expiry(self, profile_secrets):
        """Bearer tokens have no expiry — _token_expiry should be None."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        client.get_token()
        assert client._token_expiry is None


# ===========================================================================
# Auth — password
# ===========================================================================

class TestPasswordAuth:
    @pytest.fixture
    def password_dbutils(self, mock_dbutils):
        scope = "thoughtspot-default"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "password")
        mock_dbutils.secrets.put(scope, "username", "admin@example.com")
        mock_dbutils.secrets.put(scope, "password", "super-secret-pw")
        return mock_dbutils

    def _mock_token_response(self, bearer_value="fake-exchanged-token-xyz", validity_ms=3_600_000):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"token": bearer_value, "token_expiry_duration": validity_ms}
        resp.raise_for_status = MagicMock()
        return resp

    def test_password_exchange_called(self, password_dbutils):
        """password auth POSTs to /api/rest/2.0/auth/token/full."""
        client, _ = _make_client(password_dbutils)
        with patch("requests.request", return_value=self._mock_token_response()) as mock_req:
            token = client.get_token()
        assert token == "fake-exchanged-token-xyz"
        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args
        assert call_kwargs[0][0].upper() == "POST"
        assert "/api/rest/2.0/auth/token/full" in call_kwargs[0][1]

    def test_password_request_body(self, password_dbutils):
        """password exchange body includes username and password, not secret_key."""
        client, _ = _make_client(password_dbutils)
        with patch("requests.request", return_value=self._mock_token_response()) as mock_req:
            client.get_token()
        body = mock_req.call_args[1].get("json") or mock_req.call_args[1].get("data")
        assert body is not None
        assert body.get("username") == "admin@example.com"
        assert "password" in body
        assert "secret_key" not in body

    def test_password_token_cached(self, password_dbutils):
        """Second call to get_token() returns cached token without another exchange."""
        client, _ = _make_client(password_dbutils)
        with patch("requests.request", return_value=self._mock_token_response()) as mock_req:
            t1 = client.get_token()
            t2 = client.get_token()
        assert mock_req.call_count == 1
        assert t1 == t2

    def test_password_expiry_stored(self, password_dbutils):
        """Token expiry is stored so re-auth can trigger near expiry."""
        client, _ = _make_client(password_dbutils)
        with patch("requests.request", return_value=self._mock_token_response(validity_ms=3_600_000)):
            client.get_token()
        assert client._token_expiry is not None
        assert client._token_expiry > time.time()

    def test_password_exchange_500_raises_api_error(self, password_dbutils):
        """A 500 from the token exchange endpoint raises ThoughtSpotAPIError, not JSONDecodeError."""
        client, _ = _make_client(password_dbutils)
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.ok = False
        resp_500.text = "<html><body>Internal Server Error</body></html>"
        # json() should never be called — if it were, it would raise JSONDecodeError
        resp_500.json.side_effect = Exception("json() must not be called on a 500 HTML body")

        mod = _import_ts_client()
        with patch("requests.request", return_value=resp_500):
            with pytest.raises(mod.ThoughtSpotAPIError) as exc_info:
                client.get_token()
        assert exc_info.value.status_code == 500
        assert "/api/rest/2.0/auth/token/full" in exc_info.value.endpoint


# ===========================================================================
# Auth — secret_key
# ===========================================================================

class TestSecretKeyAuth:
    @pytest.fixture
    def secret_key_dbutils(self, mock_dbutils):
        scope = "thoughtspot-default"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "secret_key")
        mock_dbutils.secrets.put(scope, "username", "admin@example.com")
        mock_dbutils.secrets.put(scope, "secret_key", "my-secret-key-999")
        return mock_dbutils

    def _mock_token_response(self, bearer_value="fake-sk-exchanged-token"):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"token": bearer_value, "token_expiry_duration": 3_600_000}
        resp.raise_for_status = MagicMock()
        return resp

    def test_secret_key_exchange_called(self, secret_key_dbutils):
        """secret_key auth POSTs to /api/rest/2.0/auth/token/full."""
        client, _ = _make_client(secret_key_dbutils)
        with patch("requests.request", return_value=self._mock_token_response()) as mock_req:
            token = client.get_token()
        assert token == "fake-sk-exchanged-token"
        mock_req.assert_called_once()

    def test_secret_key_request_body(self, secret_key_dbutils):
        """secret_key exchange body includes secret_key, not password."""
        client, _ = _make_client(secret_key_dbutils)
        with patch("requests.request", return_value=self._mock_token_response()) as mock_req:
            client.get_token()
        body = mock_req.call_args[1].get("json") or mock_req.call_args[1].get("data")
        assert body is not None
        assert body.get("username") == "admin@example.com"
        assert "secret_key" in body
        assert "password" not in body

    def test_secret_key_token_cached(self, secret_key_dbutils):
        """Second call returns cached token without a second exchange."""
        client, _ = _make_client(secret_key_dbutils)
        with patch("requests.request", return_value=self._mock_token_response()) as mock_req:
            client.get_token()
            client.get_token()
        assert mock_req.call_count == 1


# ===========================================================================
# Token refresh on 401
# ===========================================================================

class TestTokenRefreshOn401:
    def _resp(self, status, body=None):
        """Build a minimal mock response."""
        r = MagicMock()
        r.status_code = status
        r.json.return_value = body or {}
        r.text = str(body or {})
        r.ok = status < 400
        return r

    def test_401_triggers_single_retry(self, profile_secrets):
        """A 401 from the first request triggers one token-refresh + retry."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)

        resp_401 = self._resp(401, {"error": "token expired"})
        resp_ok = self._resp(200, {"username": "admin@example.com"})

        with patch("requests.request", side_effect=[resp_401, resp_ok]) as mock_req:
            response = client.get("/api/rest/2.0/auth/session/user")

        assert response.status_code == 200
        assert mock_req.call_count == 2

    def test_second_401_raises_error(self, profile_secrets):
        """If the retry also returns 401, raise ThoughtSpotAPIError."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)

        resp_401a = self._resp(401, {"error": "still expired"})
        resp_401b = self._resp(401, {"error": "still expired"})

        with patch("requests.request", side_effect=[resp_401a, resp_401b]):
            _, ThoughtSpotAPIError = _make_client(mock_dbutils)  # get error class
            mod = _import_ts_client()
            with pytest.raises(mod.ThoughtSpotAPIError) as exc_info:
                client.get("/api/rest/2.0/auth/session/user")
        assert exc_info.value.status_code == 401

    def test_401_clears_cached_token(self, profile_secrets):
        """On 401, the stale token is cleared before re-auth."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        # Pre-populate cache
        client._token = "stale-token"

        resp_401 = self._resp(401)
        resp_ok = self._resp(200, {"username": "admin"})

        with patch("requests.request", side_effect=[resp_401, resp_ok]):
            client.get("/api/rest/2.0/auth/session/user")

        # After retry the client should hold the fresh token (bearer = re-read from secrets)
        assert client._token == "test-bearer-token-abc123"

    def test_5xx_raises_error(self, profile_secrets):
        """A 500 response raises ThoughtSpotAPIError immediately (no retry)."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        resp_500 = self._resp(500, {"error": "internal server error"})

        mod = _import_ts_client()
        with patch("requests.request", return_value=resp_500):
            with pytest.raises(mod.ThoughtSpotAPIError) as exc_info:
                client.get("/api/rest/2.0/some/endpoint")
        assert exc_info.value.status_code == 500


# ===========================================================================
# HTTP helpers — get() and post()
# ===========================================================================

class TestHttpHelpers:
    def _ok_resp(self, body=None):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body or {}
        r.text = ""
        r.ok = True
        return r

    def test_get_sends_get_request(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.get("/api/rest/2.0/some/endpoint")
        assert mock_req.call_args[0][0].upper() == "GET"

    def test_post_sends_post_request(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.post("/api/rest/2.0/some/endpoint", json={"key": "val"})
        assert mock_req.call_args[0][0].upper() == "POST"

    def test_auth_header_sent(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.get("/api/rest/2.0/auth/session/user")
        headers = mock_req.call_args[1].get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_url_constructed_from_base_url(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.get("/api/rest/2.0/auth/session/user")
        url = mock_req.call_args[0][1]
        assert url.startswith("https://ts.example.com")
        assert "/api/rest/2.0/auth/session/user" in url


# ===========================================================================
# whoami()
# ===========================================================================

class TestWhoami:
    def test_whoami_calls_correct_endpoint(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        user_resp = MagicMock()
        user_resp.status_code = 200
        user_resp.json.return_value = {"username": "admin@example.com", "id": "abc-123"}
        user_resp.ok = True

        with patch("requests.request", return_value=user_resp) as mock_req:
            result = client.whoami()

        url = mock_req.call_args[0][1]
        assert "/api/rest/2.0/auth/session/user" in url
        assert result["username"] == "admin@example.com"

    def test_whoami_returns_json(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"username": "admin@example.com"}
        resp.ok = True

        with patch("requests.request", return_value=resp):
            result = client.whoami()

        assert isinstance(result, dict)


# ===========================================================================
# logout()
# ===========================================================================

class TestLogout:
    def test_logout_clears_token(self, profile_secrets):
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        # Populate token
        client._token = "some-token"
        client._token_expiry = time.time() + 3600
        client.logout()
        assert client._token is None
        assert client._token_expiry is None

    def test_get_token_after_logout_re_auths(self, profile_secrets):
        """After logout, get_token() re-reads from secrets."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        client._token = "old-token"
        client.logout()
        token = client.get_token()
        assert token == "test-bearer-token-abc123"


# ===========================================================================
# metadata_search()
# ===========================================================================

class TestMetadataSearch:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_basic_search_returns_results(self, profile_secrets):
        """metadata_search returns a list of objects from the API response."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        items = [{"id": "abc-1", "name": "Sales Table", "type": "LOGICAL_TABLE"}]
        with patch("requests.request", return_value=self._ok_resp(items)):
            result = client.metadata_search(
                type="LOGICAL_TABLE",
                subtypes=None,
                name=None,
                guid=None,
                tags=None,
                include_hidden=False,
                fetch_all=False,
            )
        assert result == items

    def test_fetch_all_paginates(self, profile_secrets):
        """fetch_all=True paginates until a page smaller than page_size is returned."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        page1 = [{"id": f"id-{i}"} for i in range(500)]
        page2 = [{"id": "id-last"}]
        with patch("requests.request", side_effect=[
            self._ok_resp(page1),
            self._ok_resp(page2),
        ]) as mock_req:
            result = client.metadata_search(
                type="LOGICAL_TABLE",
                subtypes=None,
                name=None,
                guid=None,
                tags=None,
                include_hidden=False,
                fetch_all=True,
            )
        # page1=500 (full) → request page2; page2=1 (partial) → stop
        assert mock_req.call_count == 2
        assert len(result) == 501

    def test_name_filter_sets_name_pattern(self, profile_secrets):
        """Passing name= sets name_pattern in the request body."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.metadata_search(
                type="LOGICAL_TABLE",
                subtypes=None,
                name="Sales%",
                guid=None,
                tags=None,
                include_hidden=False,
                fetch_all=False,
            )
        body = mock_req.call_args[1]["json"]
        assert body.get("metadata", [{}])[0].get("name_pattern") == "Sales%"

    def test_guid_filter_sets_identifier(self, profile_secrets):
        """Passing guid= sets identifier in the request body."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.metadata_search(
                type="LOGICAL_TABLE",
                subtypes=None,
                name=None,
                guid="abc-123",
                tags=None,
                include_hidden=False,
                fetch_all=False,
            )
        body = mock_req.call_args[1]["json"]
        assert body.get("metadata", [{}])[0].get("identifier") == "abc-123"


# ===========================================================================
# metadata_get()
# ===========================================================================

class TestMetadataGet:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_returns_single_object(self, profile_secrets):
        """metadata_get returns the first matching result."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        obj = {"id": "abc-1", "name": "MyTable"}
        with patch("requests.request", return_value=self._ok_resp([obj])):
            result = client.metadata_get("abc-1", type="LOGICAL_TABLE")
        assert result == obj

    def test_raises_on_not_found(self, profile_secrets):
        """metadata_get raises ThoughtSpotAPIError(404) if no results returned."""
        mock_dbutils, _ = profile_secrets
        client, ThoughtSpotAPIError = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])):
            with pytest.raises(ThoughtSpotAPIError) as exc_info:
                client.metadata_get("nonexistent-guid", type="LOGICAL_TABLE")
        assert exc_info.value.status_code == 404


# ===========================================================================
# metadata_dependents()
# ===========================================================================

class TestMetadataDependents:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_flat_normalization(self, profile_secrets):
        """Dependents response is flattened with normalized types."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        api_response = {
            "source-guid-1": {
                "ANSWER": [
                    {"id": "ans-1", "name": "My Answer"},
                ],
                "PINBOARD": [
                    {"id": "lb-1", "name": "My Liveboard"},
                ],
            }
        }
        with patch("requests.request", return_value=self._ok_resp(api_response)):
            result = client.metadata_dependents(
                ["source-guid-1"],
                type="LOGICAL_TABLE",
            )
        assert len(result) == 2
        types = {item["type"] for item in result}
        assert "ANSWER" in types
        assert "LIVEBOARD" in types  # PINBOARD → LIVEBOARD
        source_guids = {item["source_guid"] for item in result}
        assert source_guids == {"source-guid-1"}
        ids = {item["id"] for item in result}
        assert ids == {"ans-1", "lb-1"}


# ===========================================================================
# metadata_delete()
# ===========================================================================

class TestMetadataDelete:
    def _ok_resp(self, body=None):
        r = MagicMock()
        r.status_code = 204
        r.json.return_value = body or {}
        r.text = ""
        r.ok = True
        return r

    def test_correct_payload_shape(self, profile_secrets):
        """metadata_delete sends correct payload with GUID list and type."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        guids = ["guid-1", "guid-2"]
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            result = client.metadata_delete(guids, type="LOGICAL_TABLE")
        body = mock_req.call_args[1]["json"]
        assert "metadata" in body
        assert len(body["metadata"]) == 2
        identifiers = {item["identifier"] for item in body["metadata"]}
        assert identifiers == {"guid-1", "guid-2"}
        types = {item["type"] for item in body["metadata"]}
        assert types == {"LOGICAL_TABLE"}
        assert isinstance(result, dict)


# ===========================================================================
# tml_export()
# ===========================================================================

class TestTmlExport:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_basic_export(self, profile_secrets):
        """tml_export returns raw list of edoc/info dicts when parse=False."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        api_response = [
            {"edoc": "guid: abc-123\nworksheet:\n  name: Sales\n", "info": {"id": "abc-123", "name": "Sales"}},
        ]
        with patch("requests.request", return_value=self._ok_resp(api_response)):
            result = client.tml_export(["abc-123"])
        assert result == api_response

    def test_export_with_parse(self, profile_secrets):
        """tml_export with parse=True returns list of dicts with type, guid, tml, info."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        edoc = "worksheet:\n  name: Sales\n"
        api_response = [
            {"edoc": edoc, "info": {"id": "abc-123", "name": "Sales"}},
        ]
        with patch("requests.request", return_value=self._ok_resp(api_response)):
            result = client.tml_export(["abc-123"], parse=True)
        assert len(result) == 1
        item = result[0]
        assert item["type"] == "worksheet"
        assert item["guid"] == "abc-123"
        assert isinstance(item["tml"], dict)
        assert item["tml"]["worksheet"]["name"] == "Sales"
        assert item["info"] == {"id": "abc-123", "name": "Sales"}

    def test_export_fqn_and_associated_flags(self, profile_secrets):
        """tml_export with fqn=True and associated=True sets export_fqn and export_associated in body."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.tml_export(["abc-123"], fqn=True, associated=True)
        body = mock_req.call_args[1]["json"]
        assert body.get("export_fqn") is True
        assert body.get("export_associated") is True

    def test_export_obj_id_flags(self, profile_secrets):
        """tml_export with include_obj_id and include_obj_id_ref sends export_options with those flags."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.tml_export(
                ["abc-123"],
                include_obj_id=True,
                include_obj_id_ref=True,
                include_guid=False,
            )
        body = mock_req.call_args[1]["json"]
        opts = body.get("export_options", {})
        assert opts.get("include_obj_id") is True
        assert opts.get("include_obj_id_ref") is True
        assert opts.get("include_guid") is False

    def test_export_no_export_options_when_defaults(self, profile_secrets):
        """tml_export with all default options does NOT include export_options in the body."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.tml_export(["abc-123"])
        body = mock_req.call_args[1]["json"]
        assert "export_options" not in body

    def test_feedback_type_raises(self, profile_secrets):
        """tml_export with type='FEEDBACK' raises ValueError mentioning FEEDBACK."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with pytest.raises(ValueError, match="FEEDBACK"):
            client.tml_export(["abc-123"], type="FEEDBACK")

    def test_feedback_type_case_insensitive(self, profile_secrets):
        """tml_export with type='feedback' (lowercase) also raises ValueError."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with pytest.raises(ValueError, match="FEEDBACK"):
            client.tml_export(["abc-123"], type="feedback")


# ===========================================================================
# tml_import()
# ===========================================================================

class TestTmlImport:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_basic_import(self, profile_secrets):
        """tml_import returns a list from the API response."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        api_response = [{"response": {"status": {"status_code": "OK"}}}]
        with patch("requests.request", return_value=self._ok_resp(api_response)):
            result = client.tml_import(["worksheet:\n  name: Sales\n"])
        assert isinstance(result, list)
        assert result == api_response

    def test_import_create_new_default_false(self, profile_secrets):
        """tml_import sends create_new=False by default."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.tml_import(["worksheet:\n  name: Sales\n"])
        body = mock_req.call_args[1]["json"]
        assert body.get("create_new") is False

    def test_import_policy_flag(self, profile_secrets):
        """tml_import passes import_policy=ALL_OR_NONE when specified."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.tml_import(["worksheet:\n  name: Sales\n"], policy="ALL_OR_NONE")
        body = mock_req.call_args[1]["json"]
        assert body.get("import_policy") == "ALL_OR_NONE"

    def test_import_wraps_dict_response_in_list(self, profile_secrets):
        """tml_import wraps a dict response in a list for consistent return type."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        api_response = {"response": {"status": {"status_code": "OK"}}}
        with patch("requests.request", return_value=self._ok_resp(api_response)):
            result = client.tml_import(["worksheet:\n  name: Sales\n"])
        assert isinstance(result, list)
        assert result == [api_response]


# ===========================================================================
# connections_list()
# ===========================================================================

class TestConnectionsList:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_auto_pagination_two_pages(self, profile_secrets):
        """connections_list paginates when first page is full (500 items)."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        page1 = [{"id": f"conn-{i}"} for i in range(500)]
        page2 = [{"id": "conn-last"}]
        with patch("requests.request", side_effect=[
            self._ok_resp(page1),
            self._ok_resp(page2),
        ]) as mock_req:
            result = client.connections_list(type="SNOWFLAKE")
        assert mock_req.call_count == 2
        assert len(result) == 501

    def test_stops_on_partial_page(self, profile_secrets):
        """connections_list stops when page is smaller than page_size."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        page = [{"id": "conn-1"}, {"id": "conn-2"}]
        with patch("requests.request", return_value=self._ok_resp(page)) as mock_req:
            result = client.connections_list()
        assert mock_req.call_count == 1
        assert len(result) == 2

    def test_type_sent_in_body(self, profile_secrets):
        """connections_list sends the type filter in the request body."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.connections_list(type="DATABRICKS")
        body = mock_req.call_args[1]["json"]
        assert body.get("data_warehouse_types") == ["DATABRICKS"]


# ===========================================================================
# connections_get()
# ===========================================================================

class TestConnectionsGet:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_uses_v1_endpoint(self, profile_secrets):
        """connections_get POSTs to the v1 fetchConnection endpoint."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp({"id": "conn-1"})) as mock_req:
            result = client.connections_get("conn-1")
        url = mock_req.call_args[0][1]
        assert "/tspublic/v1/connection/fetchConnection" in url

    def test_sends_connection_id(self, profile_secrets):
        """connections_get sends connection_id and includeColumns in the body."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp({})) as mock_req:
            client.connections_get("my-conn-guid")
        body = mock_req.call_args[1]["json"]
        assert body["connection_id"] == "my-conn-guid"
        assert body["includeColumns"] is True

    def test_returns_json(self, profile_secrets):
        """connections_get returns the parsed JSON response."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        conn_data = {"id": "conn-1", "name": "My Snowflake"}
        with patch("requests.request", return_value=self._ok_resp(conn_data)):
            result = client.connections_get("conn-1")
        assert result == conn_data


# ===========================================================================
# _merge_tables() (static method)
# ===========================================================================

class TestMergeTables:
    def _get_merge_tables(self):
        mod = _import_ts_client()
        return mod.ThoughtSpotClient._merge_tables

    def test_preserves_existing_tables(self):
        """_merge_tables keeps existing tables when no new tables overlap."""
        _merge_tables = self._get_merge_tables()
        fetch_response = {
            "dataWarehouseInfo": {
                "databases": [
                    {
                        "name": "MYDB",
                        "schemas": [
                            {
                                "name": "PUBLIC",
                                "tables": [
                                    {"name": "EXISTING_TABLE", "columns": [{"name": "id", "type": "INT"}]},
                                ],
                            }
                        ],
                    }
                ]
            }
        }
        new_tables = [
            {"db": "MYDB", "schema": "PUBLIC", "name": "NEW_TABLE",
             "columns": [{"name": "col1", "type": "VARCHAR"}]},
        ]
        result = _merge_tables(fetch_response, new_tables)
        # Find the db
        db = next(d for d in result if d["name"] == "MYDB")
        schema = next(s for s in db["schemas"] if s["name"] == "PUBLIC")
        table_names = {t["name"] for t in schema["tables"]}
        assert "EXISTING_TABLE" in table_names
        assert "NEW_TABLE" in table_names

    def test_appends_missing_columns_to_existing_table(self):
        """_merge_tables appends only missing columns to an existing table."""
        _merge_tables = self._get_merge_tables()
        fetch_response = {
            "dataWarehouseInfo": {
                "databases": [
                    {
                        "name": "MYDB",
                        "schemas": [
                            {
                                "name": "PUBLIC",
                                "tables": [
                                    {
                                        "name": "MY_TABLE",
                                        "columns": [{"name": "col_a", "type": "INT"}],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }
        new_tables = [
            {
                "db": "MYDB",
                "schema": "PUBLIC",
                "name": "MY_TABLE",
                "columns": [
                    {"name": "col_a", "type": "INT"},   # already exists — should not duplicate
                    {"name": "col_b", "type": "VARCHAR"},  # new column
                ],
            }
        ]
        result = _merge_tables(fetch_response, new_tables)
        db = next(d for d in result if d["name"] == "MYDB")
        schema = next(s for s in db["schemas"] if s["name"] == "PUBLIC")
        table = next(t for t in schema["tables"] if t["name"] == "MY_TABLE")
        col_names = [c["name"] for c in table["columns"]]
        assert col_names.count("col_a") == 1  # not duplicated
        assert "col_b" in col_names

    def test_new_table_has_required_fields(self):
        """New tables added via _merge_tables have selected, linked, and column flags."""
        _merge_tables = self._get_merge_tables()
        result = _merge_tables({}, [
            {"db": "DB1", "schema": "S1", "name": "TBL",
             "columns": [{"name": "x", "type": "INT"}]},
        ])
        db = next(d for d in result if d["name"] == "DB1")
        schema = next(s for s in db["schemas"] if s["name"] == "S1")
        table = next(t for t in schema["tables"] if t["name"] == "TBL")
        assert table["selected"] is True
        assert table["linked"] is True
        col = table["columns"][0]
        assert col["selected"] is True
        assert col["isLinkedActive"] is True


# ===========================================================================
# connections_add_tables()
# ===========================================================================

class TestConnectionsAddTables:
    def _ok_resp(self, body=None):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body or {}
        r.text = ""
        r.ok = True
        return r

    def test_calls_update_endpoint(self, profile_secrets):
        """connections_add_tables POSTs to the v2 connections update endpoint."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        # connections_get response + update response
        fetch_resp = self._ok_resp({"dataWarehouseInfo": {"databases": []}})
        update_resp = self._ok_resp({"status": "ok"})
        with patch("requests.request", side_effect=[fetch_resp, update_resp]) as mock_req:
            client.connections_add_tables("conn-1", [
                {"db": "DB", "schema": "S", "name": "T",
                 "columns": [{"name": "col1", "type": "INT"}]},
            ])
        # Second call should be the update
        urls = [c[0][1] for c in mock_req.call_args_list]
        assert any("/api/rest/2.0/connections/conn-1/update" in u for u in urls)

    def test_graceful_on_fetch_failure(self, profile_secrets):
        """connections_add_tables falls back to empty state if connections_get fails."""
        mock_dbutils, _ = profile_secrets
        client, ThoughtSpotAPIError = _make_client(mock_dbutils)
        fetch_err_resp = MagicMock()
        fetch_err_resp.status_code = 500
        fetch_err_resp.text = "server error"
        fetch_err_resp.ok = False
        update_resp = self._ok_resp({})
        with patch("requests.request", side_effect=[fetch_err_resp, update_resp]):
            # Should not raise even if connections_get returns an error
            client.connections_add_tables("conn-1", [
                {"db": "DB", "schema": "S", "name": "T",
                 "columns": [{"name": "col1", "type": "INT"}]},
            ])


# ===========================================================================
# _build_table_tml() (static method)
# ===========================================================================

class TestBuildTableTml:
    def _get_build_table_tml(self):
        mod = _import_ts_client()
        return mod.ThoughtSpotClient._build_table_tml

    def test_produces_valid_yaml(self):
        """_build_table_tml returns a parseable YAML string with a 'table' root."""
        import yaml
        _build_table_tml = self._get_build_table_tml()
        spec = {
            "name": "ORDERS",
            "db": "MYDB",
            "schema": "PUBLIC",
            "connection_name": "My Snowflake",
            "columns": [
                {"name": "ORDER_ID", "type": "INT64", "kind": "ATTRIBUTE"},
                {"name": "REVENUE", "type": "DOUBLE", "kind": "MEASURE"},
            ],
        }
        tml_str = _build_table_tml(spec)
        parsed = yaml.safe_load(tml_str)
        assert "table" in parsed
        assert parsed["table"]["name"] == "ORDERS"
        assert parsed["table"]["db"] == "MYDB"
        assert parsed["table"]["schema"] == "PUBLIC"

    def test_measure_columns_get_aggregation_sum(self):
        """_build_table_tml adds aggregation: SUM for MEASURE columns."""
        import yaml
        _build_table_tml = self._get_build_table_tml()
        spec = {
            "name": "SALES",
            "db": "DB",
            "schema": "S",
            "connection_name": "Conn",
            "columns": [
                {"name": "AMOUNT", "type": "DOUBLE", "kind": "MEASURE"},
                {"name": "CATEGORY", "type": "VARCHAR", "kind": "ATTRIBUTE"},
            ],
        }
        tml_str = _build_table_tml(spec)
        parsed = yaml.safe_load(tml_str)
        cols = {c["name"]: c for c in parsed["table"]["columns"]}
        assert cols["AMOUNT"]["properties"].get("aggregation") == "SUM"
        assert "aggregation" not in cols["CATEGORY"].get("properties", {})

    def test_db_column_name_always_present(self):
        """_build_table_tml always includes db_column_name on every column."""
        import yaml
        _build_table_tml = self._get_build_table_tml()
        spec = {
            "name": "T",
            "db": "D",
            "schema": "S",
            "connection_name": "C",
            "columns": [
                {"name": "MY_COL", "type": "INT"},  # no explicit db_column_name
            ],
        }
        tml_str = _build_table_tml(spec)
        parsed = yaml.safe_load(tml_str)
        col = parsed["table"]["columns"][0]
        assert "db_column_name" in col
        assert col["db_column_name"] == "MY_COL"


# ===========================================================================
# tables_create()
# ===========================================================================

class TestTablesCreate:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_creates_tml_and_returns_guid(self, profile_secrets):
        """tables_create imports TML and returns {table_name: guid}."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        import_response = [
            {"response": {"header": {"id_guid": "new-table-guid-123"}}}
        ]
        with patch("requests.request", return_value=self._ok_resp(import_response)):
            result = client.tables_create([
                {
                    "name": "ORDERS",
                    "db": "MYDB",
                    "schema": "PUBLIC",
                    "connection_name": "My Snowflake",
                    "columns": [{"name": "ID", "type": "INT64", "kind": "ATTRIBUTE"}],
                }
            ])
        assert "ORDERS" in result
        assert result["ORDERS"] == "new-table-guid-123"

    def test_returns_none_on_unrecoverable_error(self, profile_secrets):
        """tables_create returns None for a table that fails with a non-JDBC error."""
        mock_dbutils, ThoughtSpotAPIError = _make_client(
            profile_secrets[0]
        )
        mock_dbutils, _ = profile_secrets
        client, ThoughtSpotAPIError = _make_client(mock_dbutils)
        err_resp = MagicMock()
        err_resp.status_code = 400
        err_resp.text = "Invalid TML"
        err_resp.ok = False
        with patch("requests.request", return_value=err_resp):
            result = client.tables_create([
                {
                    "name": "BAD_TABLE",
                    "db": "DB",
                    "schema": "S",
                    "connection_name": "C",
                    "columns": [],
                }
            ], retries=1, retry_delay=0)
        assert result["BAD_TABLE"] is None


# ===========================================================================
# users_search()
# ===========================================================================

class TestUsersSearch:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_basic_search_returns_list(self, profile_secrets):
        """users_search returns the API response as a list."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        users = [{"id": "user-1", "name": "alice"}]
        with patch("requests.request", return_value=self._ok_resp(users)):
            result = client.users_search()
        assert result == users

    def test_name_filter_sent(self, profile_secrets):
        """users_search sends name_pattern when name is provided."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.users_search(name="alice")
        body = mock_req.call_args[1]["json"]
        assert body.get("name_pattern") == "alice"


# ===========================================================================
# orgs_search()
# ===========================================================================

class TestOrgsSearch:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_basic_search_returns_list(self, profile_secrets):
        """orgs_search returns the API response as a list."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        orgs = [{"id": "org-1", "name": "Acme"}]
        with patch("requests.request", return_value=self._ok_resp(orgs)):
            result = client.orgs_search()
        assert result == orgs

    def test_status_filter_sent(self, profile_secrets):
        """orgs_search sends status in the body when provided."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.orgs_search(status="ACTIVE")
        body = mock_req.call_args[1]["json"]
        assert body.get("status") == "ACTIVE"


# ===========================================================================
# variables_search()
# ===========================================================================

class TestVariablesSearch:
    def _ok_resp(self, body):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body
        r.text = ""
        r.ok = True
        return r

    def test_basic_search_returns_list(self, profile_secrets):
        """variables_search returns the API response as a list."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        variables = [{"id": "var-1", "name": "timezone"}]
        with patch("requests.request", return_value=self._ok_resp(variables)):
            result = client.variables_search()
        assert result == variables

    def test_response_content_always_sent(self, profile_secrets):
        """variables_search always sends response_content=METADATA_AND_VALUES."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp([])) as mock_req:
            client.variables_search(identifier="timezone")
        body = mock_req.call_args[1]["json"]
        assert body.get("response_content") == "METADATA_AND_VALUES"
        assert body.get("variable_identifiers") == ["timezone"]


# ===========================================================================
# variables_set() and variables_remove()
# ===========================================================================

class TestVariablesSetRemove:
    def _ok_resp(self, body=None):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = body or {}
        r.text = ""
        r.ok = True
        return r

    def test_variables_set_sends_replace_operation(self, profile_secrets):
        """variables_set sends operation=REPLACE."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.variables_set("timezone", "America/Chicago", orgs=["org-1"])
        body = mock_req.call_args[1]["json"]
        assert body["operation"] == "REPLACE"
        assert body["variable_identifier"] == "timezone"

    def test_variables_remove_sends_remove_operation(self, profile_secrets):
        """variables_remove sends operation=REMOVE."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.variables_remove("timezone", "America/Chicago", orgs=["org-1"])
        body = mock_req.call_args[1]["json"]
        assert body["operation"] == "REMOVE"

    def test_org_level_scope_when_no_users(self, profile_secrets):
        """variables_set builds org-level scopes when users is not provided."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.variables_set("timezone", "UTC", orgs=["org-1", "org-2"])
        body = mock_req.call_args[1]["json"]
        scopes = body["variable_values"][0]["scopes"]
        assert len(scopes) == 2
        assert all("org_identifier" in s for s in scopes)
        assert all("user_identifier" not in s for s in scopes)

    def test_per_user_scopes_when_users_provided(self, profile_secrets):
        """variables_set builds per-user scopes when users list is provided."""
        mock_dbutils, _ = profile_secrets
        client, _ = _make_client(mock_dbutils)
        with patch("requests.request", return_value=self._ok_resp()) as mock_req:
            client.variables_set(
                "timezone", "UTC",
                orgs=["org-1"],
                users=["user-a", "user-b"],
            )
        body = mock_req.call_args[1]["json"]
        scopes = body["variable_values"][0]["scopes"]
        assert len(scopes) == 2  # 1 org × 2 users
        user_ids = {s["user_identifier"] for s in scopes}
        assert user_ids == {"user-a", "user-b"}


# ===========================================================================
# token_refresh — refresh_all_profiles()
# ===========================================================================

import sys as _sys

_notebooks_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "notebooks")
)
if _notebooks_dir not in _sys.path:
    _sys.path.insert(0, _notebooks_dir)

from token_refresh import refresh_all_profiles  # noqa: E402


class TestTokenRefresh:
    """Tests for refresh_all_profiles() in notebooks/token_refresh.py."""

    def _mock_token_post(self, token_value="fresh-token-xyz"):
        """Build a mock requests.post response returning a fresh token."""
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.json.return_value = {"token": token_value}
        return resp

    def test_refreshes_password_profile(self, mock_dbutils):
        """A password profile gets a fresh token fetched and stored back."""
        scope = "thoughtspot-staging"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "password")
        mock_dbutils.secrets.put(scope, "username", "admin@example.com")
        mock_dbutils.secrets.put(scope, "password", "super-secret-pw")

        with patch("requests.post", return_value=self._mock_token_post("fresh-token-xyz")) as mock_post:
            results = refresh_all_profiles(mock_dbutils)

        assert results["staging"] == "OK"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        # Endpoint URL
        assert "/api/rest/2.0/auth/token/full" in call_kwargs[0][0]
        # Request body contains username and password
        body = call_kwargs[1]["json"]
        assert body["username"] == "admin@example.com"
        assert body["password"] == "super-secret-pw"
        assert "secret_key" not in body
        # Token stored back
        stored_token = mock_dbutils.secrets.get(scope, "token")
        assert stored_token == "fresh-token-xyz"

    def test_skips_bearer_token_profiles(self, mock_dbutils):
        """A bearer_token profile is skipped — no HTTP call made."""
        scope = "thoughtspot-prod"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "bearer_token")
        mock_dbutils.secrets.put(scope, "username", "admin@example.com")
        mock_dbutils.secrets.put(scope, "token", "static-bearer-token")

        with patch("requests.post") as mock_post:
            results = refresh_all_profiles(mock_dbutils)

        assert results["prod"] == "SKIPPED"
        mock_post.assert_not_called()

    def test_refreshes_secret_key_profile(self, mock_dbutils):
        """A secret_key profile gets a fresh token fetched using secret_key in the body."""
        scope = "thoughtspot-dev"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "secret_key")
        mock_dbutils.secrets.put(scope, "username", "admin@example.com")
        mock_dbutils.secrets.put(scope, "secret_key", "my-secret-key-999")

        with patch("requests.post", return_value=self._mock_token_post("sk-fresh-token")) as mock_post:
            results = refresh_all_profiles(mock_dbutils)

        assert results["dev"] == "OK"
        body = mock_post.call_args[1]["json"]
        assert body["secret_key"] == "my-secret-key-999"
        assert "password" not in body
        assert mock_dbutils.secrets.get(scope, "token") == "sk-fresh-token"

    def test_ignores_non_thoughtspot_scopes(self, mock_dbutils):
        """Scopes not starting with 'thoughtspot-' are not processed."""
        mock_dbutils.secrets.createScope("databricks-config")
        mock_dbutils.secrets.put("databricks-config", "token", "db-token")

        with patch("requests.post") as mock_post:
            results = refresh_all_profiles(mock_dbutils)

        assert results == {}
        mock_post.assert_not_called()

    def test_handles_missing_auth_method(self, mock_dbutils):
        """A scope missing auth_method key returns an ERROR result."""
        scope = "thoughtspot-broken"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        # auth_method intentionally omitted

        results = refresh_all_profiles(mock_dbutils)

        assert results["broken"].startswith("ERROR:")

    def test_handles_http_error(self, mock_dbutils):
        """An HTTP error from the token endpoint is caught and returned as ERROR."""
        scope = "thoughtspot-flaky"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "password")
        mock_dbutils.secrets.put(scope, "username", "admin@example.com")
        mock_dbutils.secrets.put(scope, "password", "pw")

        bad_resp = MagicMock()
        bad_resp.status_code = 500
        bad_resp.ok = False

        with patch("requests.post", return_value=bad_resp):
            results = refresh_all_profiles(mock_dbutils)

        assert results["flaky"].startswith("ERROR:")

    def test_mixed_profiles(self, mock_dbutils):
        """Multiple profiles of different types are handled independently."""
        # bearer_token profile
        scope_bearer = "thoughtspot-p1"
        mock_dbutils.secrets.createScope(scope_bearer)
        mock_dbutils.secrets.put(scope_bearer, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope_bearer, "auth_method", "bearer_token")
        mock_dbutils.secrets.put(scope_bearer, "token", "static-token")

        # password profile
        scope_pw = "thoughtspot-p2"
        mock_dbutils.secrets.createScope(scope_pw)
        mock_dbutils.secrets.put(scope_pw, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope_pw, "auth_method", "password")
        mock_dbutils.secrets.put(scope_pw, "username", "user@example.com")
        mock_dbutils.secrets.put(scope_pw, "password", "pw123")

        with patch("requests.post", return_value=self._mock_token_post("fresh-p2-token")):
            results = refresh_all_profiles(mock_dbutils)

        assert results["p1"] == "SKIPPED"
        assert results["p2"] == "OK"
