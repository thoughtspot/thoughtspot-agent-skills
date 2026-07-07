"""ThoughtSpot HTTP client with profile-based auth and token caching."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

PROFILES_PATH = Path.home() / ".claude" / "thoughtspot-profiles.json"

# The token-exchange endpoint itself must never trigger the 401-retry path below —
# a 401 from auth/token/full is a credential failure, not a stale-cache symptom, and
# _authenticate() already raises a clear SystemExit for that case. This constant only
# matters if some future caller ever routes that endpoint through request() instead of
# calling self._session.post() directly (as _authenticate() does today).
_AUTH_TOKEN_PATH = "/api/rest/2.0/auth/token/full"

# Transient gateway/network faults worth retrying with backoff (BL-089 1c).
# A flaky instance returning 502/503/504 (or a dropped connection) otherwise
# hard-fails every call — and a 504 HTML page reaching a caller's .json() gives
# a raw JSONDecodeError traceback. 500 is deliberately excluded: it's an
# application error, and retrying it would mask real failures.
_RETRY_STATUSES = frozenset({502, 503, 504})
_RETRY_MAX = 3          # retries after the initial attempt (4 attempts total)
_RETRY_BACKOFF_S = 0.5  # base backoff, doubled each retry: 0.5s, 1s, 2s


def format_http_error(method: str, url: str, resp: "requests.Response") -> str:
    """Build a single-line, secret-free diagnostic for a non-2xx response.

    The ThoughtSpot error body (when JSON) carries `debug`/`error`/`message` fields that
    pinpoint the failure far better than a Python traceback. We surface those and NEVER
    echo request headers (which hold the bearer token).
    """
    detail = ""
    body = (resp.text or "").strip()
    if body:
        try:
            data = resp.json()
            if isinstance(data, dict):
                detail = str(
                    data.get("debug")
                    or data.get("error")
                    or data.get("message")
                    or data.get("incident_id")
                    or body
                )
            else:
                detail = body
        except ValueError:
            detail = body
    detail = " ".join(detail.split())  # collapse whitespace/newlines to one line
    if len(detail) > 500:
        detail = detail[:500] + "…"
    suffix = f" — {detail}" if detail else ""
    return f"ThoughtSpot API {resp.status_code} on {method} {url}{suffix}"


def _slugify(name: str) -> str:
    """Derive the profile slug used for Keychain service names.

    Matches the slug derivation in ts-profile-setup/SKILL.md:
      lowercase, non-alphanumeric → hyphens, collapsed and stripped.
    """
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def resolve_profile(profile: Optional[str]) -> str:
    """Return the profile name to use, with fallback to TS_PROFILE env var
    and then the first profile in the profiles file."""
    if profile:
        return profile
    env = os.environ.get("TS_PROFILE", "")
    if env:
        return env
    if not PROFILES_PATH.exists():
        raise SystemExit(
            f"No profiles file found at {PROFILES_PATH}.\n"
            "Run /ts-profile-thoughtspot to create a profile first."
        )
    raw = json.loads(PROFILES_PATH.read_text())
    profiles = raw if isinstance(raw, list) else list(raw.values())
    if not profiles:
        raise SystemExit(
            "No ThoughtSpot profiles configured.\n"
            "Run /ts-profile-thoughtspot to add a profile."
        )
    return profiles[0]["name"]


def load_profiles() -> Dict[str, Any]:
    """Load all profiles as a name → profile dict.

    Handles three file formats produced by the ts-profile-setup skill:
      {"profiles": [{...}, ...]}   — wrapped list (current format)
      [{...}, ...]                 — bare list
      {"name": {...}, ...}         — dict keyed by profile name
    """
    if not PROFILES_PATH.exists():
        return {}
    raw = json.loads(PROFILES_PATH.read_text())
    if isinstance(raw, list):
        return {p["name"]: p for p in raw}
    if isinstance(raw, dict):
        # Unwrap {"profiles": [...]} if present
        if "profiles" in raw and isinstance(raw["profiles"], list):
            return {p["name"]: p for p in raw["profiles"]}
        return raw  # already keyed by name
    return {}


class ThoughtSpotClient:
    """Authenticated HTTP client for the ThoughtSpot REST API.

    Auth flow (matches ts-profile-thoughtspot/SKILL.md):
      1. Check for a valid cached token in the OS temp directory.
      2. If none, read the credential — first from the env var named in the
         profile, then directly from the OS credential store via keyring as
         fallback (macOS Keychain, Windows Credential Manager, Linux Secret
         Service).
      3. If token_env: use the credential as the bearer token directly.
         If password_env / secret_key_env: exchange for a bearer token via
         POST /api/rest/2.0/auth/token/full and cache the result.

    Credentials are managed exclusively through /ts-profile-thoughtspot.
    Do not set credential env vars manually — use that skill to add, update,
    or refresh credentials, which stores them in the OS credential store.
    """

    def __init__(self, profile_name: str):
        profiles = load_profiles()
        if profile_name not in profiles:
            available = ", ".join(profiles.keys()) or "(none)"
            raise SystemExit(
                f"Profile '{profile_name}' not found.\n"
                f"Available profiles: {available}\n"
                "Run /ts-profile-thoughtspot to add a profile."
            )
        self._profile = profiles[profile_name]
        self._profile_name = profile_name
        self._slug = _slugify(profile_name)
        self._base_url = self._profile["base_url"].rstrip("/")
        self._verify_ssl: bool = self._profile.get("verify_ssl", True)
        self._token: Optional[str] = None
        self._session = requests.Session()
        self._session.verify = self._verify_ssl

    # ------------------------------------------------------------------
    # Token caching
    # ------------------------------------------------------------------

    def _token_path(self) -> Path:
        return Path(tempfile.gettempdir()) / f"ts_token_{self._slug}.txt"

    def _expiry_path(self) -> Path:
        return Path(tempfile.gettempdir()) / f"ts_token_{self._slug}_expiry.txt"

    def _read_cached_token(self) -> Optional[str]:
        token_path = self._token_path()
        expiry_path = self._expiry_path()
        if not token_path.exists():
            return None

        if expiry_path.exists():
            try:
                expiry_ms = int(expiry_path.read_text().strip())
                if time.time() * 1000 > expiry_ms - 60_000:
                    return None  # expires within 60 s — refresh
            except ValueError:
                return None  # corrupt expiry file — force fresh auth
        else:
            # No expiry file: treat as stale after 23 hours
            age = time.time() - token_path.stat().st_mtime
            if age > 23 * 3600:
                return None

        return token_path.read_text().strip()

    def _write_cached_token(self, token: str, expiry_ms: Optional[int]) -> None:
        token_path = self._token_path()
        expiry_path = self._expiry_path()
        token_path.write_text(token)
        token_path.chmod(0o600)
        if expiry_ms:
            expiry_path.write_text(str(expiry_ms))
            expiry_path.chmod(0o600)

    def clear_token_cache(self) -> bool:
        """Remove cached token files. Returns True if anything was removed."""
        removed = False
        for p in (self._token_path(), self._expiry_path()):
            if p.exists():
                p.unlink()
                removed = True
        return removed

    # ------------------------------------------------------------------
    # Credential resolution
    # ------------------------------------------------------------------

    def _get_credential(self, env_var: str) -> str:
        """Read a credential — env var first, OS credential store fallback.

        The OS credential store fallback uses the `keyring` library, which
        delegates to macOS Keychain, Windows Credential Manager, or Linux
        Secret Service depending on the platform.
        """
        val = os.environ.get(env_var, "")
        if val:
            return val

        # OS credential store fallback — service name matches ts-profile-thoughtspot derivation
        service = f"thoughtspot-{self._slug}"
        username = self._profile.get("username", "")
        try:
            import keyring  # deferred import — graceful if not installed
            stored = keyring.get_password(service, username)
            if stored:
                return stored
        except Exception:
            pass

        raise SystemExit(
            f"No credential found for profile '{self._profile_name}'.\n"
            "To fix: run /ts-profile-thoughtspot → U → Refresh credential,\n"
            "then reload your shell (macOS/Linux: source ~/.zshenv | Windows: restart terminal)."
        )

    def _authenticate(self) -> Tuple[str, Optional[int]]:
        """Authenticate and return (bearer_token, expiry_ms)."""
        p = self._profile

        if p.get("token_env"):
            token = self._get_credential(p["token_env"])
            return token, None  # browser tokens have no API-derived expiry

        if p.get("password_env"):
            password = self._get_credential(p["password_env"])
            resp = self._session.post(
                f"{self._base_url}/api/rest/2.0/auth/token/full",
                json={
                    "username": p["username"],
                    "password": password,
                    "validity_time_in_sec": 3600,
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (401, 403):
                raise SystemExit(
                    f"Authentication failed ({resp.status_code}) for profile '{self._profile_name}'.\n"
                    "Password may be wrong or expired.\n"
                    "Run /ts-profile-thoughtspot → U → Refresh credential."
                )
            resp.raise_for_status()
            data = resp.json()
            return data["token"], data.get("expiration_time_in_millis")

        if p.get("secret_key_env"):
            secret_key = self._get_credential(p["secret_key_env"])
            resp = self._session.post(
                f"{self._base_url}/api/rest/2.0/auth/token/full",
                json={
                    "username": p["username"],
                    "secret_key": secret_key,
                    "validity_time_in_sec": 3600,
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (401, 403):
                raise SystemExit(
                    f"Authentication failed ({resp.status_code}) for profile '{self._profile_name}'.\n"
                    "Secret key may be wrong or expired.\n"
                    "Run /ts-profile-thoughtspot → U → Refresh credential."
                )
            resp.raise_for_status()
            data = resp.json()
            return data["token"], data.get("expiration_time_in_millis")

        raise SystemExit(
            f"Profile '{self._profile_name}' has no auth credential configured "
            "(expected one of: token_env, password_env, secret_key_env)."
        )

    # ------------------------------------------------------------------
    # Token access
    # ------------------------------------------------------------------

    def get_token(self) -> str:
        if self._token:
            return self._token
        cached = self._read_cached_token()
        if cached:
            self._token = cached
            return self._token
        token, expiry_ms = self._authenticate()
        self._write_cached_token(token, expiry_ms)
        self._token = token
        return self._token

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        extra_headers = kwargs.pop("headers", {})
        timeout = kwargs.pop("timeout", 60)
        url = f"{self._base_url}{path}"
        allow_401_retry = path != _AUTH_TOKEN_PATH

        retried_401 = False
        transient_attempts = 0
        while True:
            headers = dict(extra_headers)
            headers.update(self._auth_headers())
            try:
                resp = self._session.request(method, url, headers=headers, timeout=timeout, **kwargs)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as exc:
                # Dropped connection / read timeout — transient. Retry with
                # backoff, then fail cleanly (no traceback) if it persists.
                if transient_attempts < _RETRY_MAX:
                    transient_attempts += 1
                    print(
                        f"ThoughtSpot API network error on {method} {url} "
                        f"({type(exc).__name__}) — retry {transient_attempts}/{_RETRY_MAX}...",
                        file=sys.stderr,
                    )
                    time.sleep(_RETRY_BACKOFF_S * (2 ** (transient_attempts - 1)))
                    continue
                print(
                    f"ThoughtSpot API network error on {method} {url} after "
                    f"{_RETRY_MAX} retries: {exc}",
                    file=sys.stderr,
                )
                raise SystemExit(1)

            if resp.status_code in _RETRY_STATUSES and transient_attempts < _RETRY_MAX:
                # Transient gateway fault (502/503/504) — retry with backoff.
                # Prevents a flaky instance from hard-failing the call (and a
                # 504 HTML body from reaching a caller's .json() as a traceback).
                transient_attempts += 1
                print(
                    f"ThoughtSpot API {resp.status_code} on {method} {url} "
                    f"(transient) — retry {transient_attempts}/{_RETRY_MAX}...",
                    file=sys.stderr,
                )
                time.sleep(_RETRY_BACKOFF_S * (2 ** (transient_attempts - 1)))
                continue

            if resp.status_code == 401 and allow_401_retry and not retried_401:
                # A cached token_env token has no server-verified expiry and is
                # otherwise treated valid for ~23h (_read_cached_token) — a 401 here
                # means the token was actually rotated/revoked server-side, not
                # merely due for a routine refresh. Clear the stale cache; the next
                # loop pass's _auth_headers() -> get_token() call forces one fresh
                # authentication. retried_401 bounds this to exactly one retry — if
                # the fresh token still 401s, fall through and report that failure.
                print(
                    f"ThoughtSpot API 401 on {method} {url} — clearing cached token "
                    "and re-authenticating...",
                    file=sys.stderr,
                )
                self.clear_token_cache()
                self._token = None
                retried_401 = True
                continue
            break

        if raise_for_status and not resp.ok:
            # Central, traceback-free failure path: one diagnostic line on stderr,
            # exit 1. Callers that need the raw status in a 2xx body (e.g. tables
            # import, where JDBC errors arrive as 200) are unaffected — those never
            # reach here. Skill code piping our stdout JSON gets a clean signal.
            print(format_http_error(method, url, resp), file=sys.stderr)
            raise SystemExit(1)
        return resp

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    @property
    def base_url(self) -> str:
        return self._base_url
