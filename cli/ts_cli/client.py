"""ThoughtSpot HTTP client with profile-based auth and token caching."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

PROFILES_PATH = Path.home() / ".claude" / "thoughtspot-profiles.json"


def _slugify(name: str) -> str:
    """Derive the profile slug used for Keychain service names.

    Matches the slug derivation in thoughtspot-setup/SKILL.md:
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
            "Run the thoughtspot-setup skill to create a profile first."
        )
    raw = json.loads(PROFILES_PATH.read_text())
    profiles = raw if isinstance(raw, list) else list(raw.values())
    if not profiles:
        raise SystemExit(
            "No ThoughtSpot profiles configured.\n"
            "Run the thoughtspot-setup skill to add a profile."
        )
    return profiles[0]["name"]


def load_profiles() -> Dict[str, Any]:
    """Load all profiles as a name → profile dict.

    Handles three file formats produced by the thoughtspot-setup skill:
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

    Auth flow (matches Pattern A from thoughtspot-setup/SKILL.md):
      1. Check for a valid cached token in /tmp/ts_token_{slug}.txt
      2. If none, read the credential from the environment variable in the
         profile, with a fallback to reading directly from macOS Keychain.
      3. If token_env: use the credential as the bearer token directly.
         If password_env / secret_key_env: exchange for a bearer token via
         POST /api/rest/2.0/auth/token/full and cache the result.
    """

    def __init__(self, profile_name: str):
        profiles = load_profiles()
        if profile_name not in profiles:
            available = ", ".join(profiles.keys()) or "(none)"
            raise SystemExit(
                f"Profile '{profile_name}' not found.\n"
                f"Available profiles: {available}\n"
                "Run the thoughtspot-setup skill to add a profile."
            )
        self._profile = profiles[profile_name]
        self._profile_name = profile_name
        self._slug = _slugify(profile_name)
        self._base_url = self._profile["base_url"].rstrip("/")
        self._token: Optional[str] = None

    # ------------------------------------------------------------------
    # Token caching
    # ------------------------------------------------------------------

    def _token_path(self) -> Path:
        return Path(f"/tmp/ts_token_{self._slug}.txt")

    def _expiry_path(self) -> Path:
        return Path(f"/tmp/ts_token_{self._slug}_expiry.txt")

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
                pass
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
        """Read a credential from the environment, falling back to Keychain."""
        val = os.environ.get(env_var, "")
        if val:
            return val

        # Keychain fallback — service name matches thoughtspot-setup derivation
        service = f"thoughtspot-{self._slug}"
        username = self._profile.get("username", "")
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", username, "-w"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        raise SystemExit(
            f"Credential not available for profile '{self._profile_name}'.\n"
            f"  Expected env var: {env_var}\n"
            f"  Keychain service: {service}\n"
            "Try running 'source ~/.zshenv' in your terminal, or re-add the profile\n"
            "with the thoughtspot-setup skill."
        )

    def _authenticate(self) -> Tuple[str, Optional[int]]:
        """Authenticate and return (bearer_token, expiry_ms)."""
        p = self._profile

        if p.get("token_env"):
            token = self._get_credential(p["token_env"])
            return token, None  # browser tokens have no API-derived expiry

        if p.get("password_env"):
            password = self._get_credential(p["password_env"])
            resp = requests.post(
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
                    f"Authentication failed ({resp.status_code}). "
                    "Password may be wrong or expired."
                )
            resp.raise_for_status()
            data = resp.json()
            return data["token"], data.get("expiration_time_in_millis")

        if p.get("secret_key_env"):
            secret_key = self._get_credential(p["secret_key_env"])
            resp = requests.post(
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
                    f"Authentication failed ({resp.status_code}). "
                    "Secret key may be wrong or expired."
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

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())
        resp = requests.request(
            method,
            f"{self._base_url}{path}",
            headers=headers,
            timeout=kwargs.pop("timeout", 60),
            **kwargs,
        )
        resp.raise_for_status()
        return resp

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    @property
    def base_url(self) -> str:
        return self._base_url
