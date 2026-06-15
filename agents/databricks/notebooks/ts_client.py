"""
ts_client.py — ThoughtSpotClient for Databricks notebooks.

Consumed via ``%run ./ts_client`` in Databricks notebooks, or imported
directly in tests (add ``agents/databricks/notebooks/`` to sys.path first).

Design principles
-----------------
- **Single file** — no package install needed; %run resolves it at notebook time.
- **Databricks Secrets for credentials** — one scope per ThoughtSpot profile
  (scope name: ``thoughtspot-{profile}``).
- **In-memory token caching** — no filesystem; tokens live in the notebook session.
- **No dependency on ts CLI, keyring, or OS keychain.**
- **Three auth methods**: bearer_token (direct), password (exchange), secret_key (exchange).
- **401 retry**: on the first 401 the stale token is cleared and a fresh one obtained;
  if the retry also fails, ThoughtSpotAPIError is raised.
"""

from __future__ import annotations

import builtins
import json
import re
import time
from typing import Optional

import requests
import yaml

# ---------------------------------------------------------------------------
# Module-level helpers (used by TML methods added in later tasks)
# ---------------------------------------------------------------------------

_NONPRINTABLE_RE: re.Pattern = re.compile(
    r"[^\x09\x0a\x0d\x20-\x7e\x80-\xff]"
)

_TML_TYPE_KEYS: frozenset = frozenset(
    {
        "table",
        "view",
        "sql_view",
        "worksheet",
        "answer",
        "liveboard",
        "model",
        "connection",
    }
)


def _strip_nonprintable(text: str) -> str:
    """Remove non-printable characters from *text*."""
    return _NONPRINTABLE_RE.sub("", text)


def _detect_tml_type(parsed: dict) -> Optional[str]:
    """Return the TML object type from the top-level key of a parsed TML dict."""
    for key in _TML_TYPE_KEYS:
        if key in parsed:
            return key
    return None


def _parse_edoc(edoc: str, fmt: str = "YAML") -> dict:
    """Parse a TML edoc string in YAML or JSON format.

    Parameters
    ----------
    edoc:
        Raw TML string (YAML or JSON).
    fmt:
        ``"YAML"`` (default) or ``"JSON"``.

    Returns
    -------
    dict
        Parsed TML as a Python dict.
    """
    cleaned = _strip_nonprintable(edoc)
    if fmt.upper() == "JSON":
        return json.loads(cleaned)
    return yaml.safe_load(cleaned)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

_CONFIGURATION_RE: re.Pattern = re.compile(
    r'"configuration"\s*:\s*\{[^}]*\}'
)


class ThoughtSpotAPIError(Exception):
    """Raised when a ThoughtSpot REST API call returns a non-2xx status.

    Attributes
    ----------
    status_code : int
        HTTP status code returned by the API.
    endpoint : str
        The URL path that was called, for context in error messages.
    """

    def __init__(self, status_code: int, message: str, endpoint: str) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        # Scrub any connection credential details from the message body.
        scrubbed = _CONFIGURATION_RE.sub('"configuration": "[REDACTED]"', message)
        super().__init__(f"[{status_code}] {endpoint}: {scrubbed}")


# ---------------------------------------------------------------------------
# ThoughtSpotClient
# ---------------------------------------------------------------------------

# Number of seconds before expiry at which we proactively refresh the token.
_REFRESH_BUFFER_SECS: int = 60


class ThoughtSpotClient:
    """ThoughtSpot REST API client designed for Databricks notebooks.

    Credentials are read from Databricks Secrets under the scope
    ``thoughtspot-{profile}``.  The following keys are expected:

    ===============  ==========================================================
    Key              Value
    ===============  ==========================================================
    ``base_url``     Root URL of the ThoughtSpot instance, e.g.
                     ``https://company.thoughtspot.cloud``
    ``auth_method``  One of ``bearer_token``, ``password``, ``secret_key``
    ``username``     ThoughtSpot user name / e-mail
    ``token``        *bearer_token only* — the pre-issued bearer token
    ``password``     *password only* — the user's password
    ``secret_key``   *secret_key only* — the secret key for token exchange
    ===============  ==========================================================

    Token exchange is lazy — no network call is made during ``__init__``.
    The first call to :meth:`get_token` (or any API helper) triggers the
    exchange and caches the result.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        profile: str = "default",
        *,
        dbutils=None,
    ) -> None:
        """Initialise the client for the given *profile*.

        Parameters
        ----------
        profile:
            Name of the Databricks Secrets scope to read from.
            The scope name used is ``thoughtspot-{profile}``.
        dbutils:
            The Databricks ``dbutils`` object.  If ``None`` (the default) the
            constructor checks ``builtins.dbutils`` — the name Databricks
            automatically injects into notebook scope.  Pass an explicit value
            in tests (or any non-notebook context) to avoid the builtins lookup.

        Raises
        ------
        RuntimeError
            If *dbutils* is ``None`` and ``builtins.dbutils`` is not set.
        """
        if dbutils is None:
            dbutils = getattr(builtins, "dbutils", None)
        if dbutils is None:
            raise RuntimeError(
                "dbutils is not available. Either pass it explicitly as "
                "ThoughtSpotClient(profile, dbutils=dbutils) or run this "
                "code inside a Databricks notebook where dbutils is injected."
            )

        self._dbutils = dbutils
        self._profile = profile
        self._scope = f"thoughtspot-{profile}"

        # Read non-sensitive profile metadata from Secrets.
        self._base_url: str = self._secret("base_url").rstrip("/")
        self._auth_method: str = self._secret("auth_method")
        self._username: str = self._secret("username")

        # Token cache — populated lazily on first get_token() call.
        self._token: Optional[str] = None
        self._token_expiry: Optional[float] = None  # Unix timestamp; None = no expiry

    # ------------------------------------------------------------------
    # Secret helpers
    # ------------------------------------------------------------------

    def _secret(self, key: str) -> str:
        """Read a single secret from this profile's scope."""
        return self._dbutils.secrets.get(self._scope, key)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self) -> tuple[str, Optional[float]]:
        """Perform the auth flow for this profile's auth_method.

        Returns
        -------
        (token, expiry_timestamp)
            *expiry_timestamp* is a Unix float (time.time() + TTL) for
            exchanged tokens, or ``None`` for bearer tokens (no expiry tracked).

        Raises
        ------
        ThoughtSpotAPIError
            If the token exchange endpoint returns 401 or 403.
        """
        method = self._auth_method

        if method == "bearer_token":
            token = self._secret("token")
            return token, None

        # Both password and secret_key hit the same exchange endpoint.
        url = f"{self._base_url}/api/rest/2.0/auth/token/full"
        body: dict = {
            "username": self._username,
            "validity_time_in_sec": 3600,
        }

        if method == "password":
            body["password"] = self._secret("password")
        elif method == "secret_key":
            body["secret_key"] = self._secret("secret_key")
        else:
            raise ValueError(f"Unknown auth_method: {method!r}")

        resp = requests.request(
            "POST",
            url,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        if resp.status_code in (401, 403):
            raise ThoughtSpotAPIError(resp.status_code, resp.text, url)

        data = resp.json()
        token = data["token"]
        # token_expiry_duration is in milliseconds.
        validity_ms: int = data.get("token_expiry_duration", 3_600_000)
        expiry = time.time() + (validity_ms / 1000.0)
        return token, expiry

    def get_token(self) -> str:
        """Return a valid bearer token, refreshing if necessary.

        For ``bearer_token`` profiles the stored token is returned as-is
        (no expiry tracking). For ``password`` and ``secret_key`` profiles
        the token is refreshed when it is within ``_REFRESH_BUFFER_SECS``
        seconds of expiry, or when the cache is empty.

        Returns
        -------
        str
            A valid bearer token for use in ``Authorization: Bearer`` headers.
        """
        now = time.time()
        if self._token is not None:
            # Check expiry: None means no expiry (bearer_token), so no refresh.
            if self._token_expiry is None:
                return self._token
            if self._token_expiry - now > _REFRESH_BUFFER_SECS:
                return self._token

        # Cache is empty or token is about to expire — (re-)authenticate.
        self._token, self._token_expiry = self._authenticate()
        return self._token

    def logout(self) -> None:
        """Clear the cached token, forcing re-authentication on the next request."""
        self._token = None
        self._token_expiry = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict:
        """Build authentication headers for a ThoughtSpot REST API request."""
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request_with_retry(
        self, method: str, path: str, **kwargs
    ) -> requests.Response:
        """Make an authenticated HTTP request, retrying once on 401.

        Parameters
        ----------
        method:
            HTTP method string (e.g. ``"GET"``, ``"POST"``).
        path:
            URL path relative to ``base_url`` (must start with ``/``).
        **kwargs:
            Passed directly to ``requests.request`` (e.g. ``json=``, ``params=``).

        Returns
        -------
        requests.Response
            The response object on success (2xx).

        Raises
        ------
        ThoughtSpotAPIError
            On any non-2xx status after a single 401 retry.
        """
        url = f"{self._base_url}{path}"
        headers = self._auth_headers()
        kwargs.setdefault("headers", {})
        kwargs["headers"] = {**headers, **kwargs["headers"]}

        resp = requests.request(method, url, **kwargs)

        if resp.status_code == 401:
            # Stale token — clear cache, re-auth, and retry once.
            self.logout()
            headers = self._auth_headers()
            kwargs["headers"] = {**headers}
            resp = requests.request(method, url, **kwargs)

        if not resp.ok:
            raise ThoughtSpotAPIError(resp.status_code, resp.text, path)

        return resp

    def get(self, path: str, **kwargs) -> requests.Response:
        """Make an authenticated GET request.

        Parameters
        ----------
        path:
            URL path relative to ``base_url``.
        **kwargs:
            Forwarded to ``requests.request``.
        """
        return self._request_with_retry("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """Make an authenticated POST request.

        Parameters
        ----------
        path:
            URL path relative to ``base_url``.
        **kwargs:
            Forwarded to ``requests.request``.
        """
        return self._request_with_retry("POST", path, **kwargs)

    # ------------------------------------------------------------------
    # Auth API
    # ------------------------------------------------------------------

    def whoami(self) -> dict:
        """Return the currently authenticated ThoughtSpot user.

        Calls ``GET /api/rest/2.0/auth/session/user`` and returns the
        parsed JSON response as a dict.
        """
        resp = self.get("/api/rest/2.0/auth/session/user")
        return resp.json()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """The base URL of the ThoughtSpot instance (trailing slash stripped)."""
        return self._base_url
