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
