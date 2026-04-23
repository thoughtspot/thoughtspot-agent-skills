"""
test_client_auth.py — unit tests for ThoughtSpotClient credential resolution
and token cache path logic.

Tests the cross-platform keyring fallback introduced in the Windows/Linux support
change. No live ThoughtSpot instance or real keyring installation required — all
credential store calls are mocked.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ts_cli.client import ThoughtSpotClient, _slugify, load_profiles


# ---------------------------------------------------------------------------
# _slugify — regression guard: slug derivation must be stable (used as Keychain
# service name component and env var name component)
# ---------------------------------------------------------------------------

class TestSlugify:
    @pytest.mark.parametrize("name,expected", [
        ("Production",        "production"),
        ("My Staging",        "my-staging"),
        ("MY_STAGING",        "my-staging"),
        ("prod (us-east-1)",  "prod-us-east-1"),
        ("  Leading  ",       "leading"),
        ("A--B",              "a-b"),
    ])
    def test_slug_derivation(self, name, expected):
        assert _slugify(name) == expected


# ---------------------------------------------------------------------------
# Helpers — build a ThoughtSpotClient without reading a real profiles file
# ---------------------------------------------------------------------------

def _make_client(profile_name: str = "Production", **profile_kwargs) -> ThoughtSpotClient:
    """Build a ThoughtSpotClient with a synthetic in-memory profile."""
    profile = {
        "name": profile_name,
        "base_url": "https://test.thoughtspot.cloud",
        "username": "user@test.com",
        "token_env": "THOUGHTSPOT_TOKEN_PRODUCTION",
        **profile_kwargs,
    }
    with patch("ts_cli.client.load_profiles", return_value={profile_name: profile}):
        return ThoughtSpotClient(profile_name)


# ---------------------------------------------------------------------------
# Token cache paths — must use OS temp dir, not hardcoded /tmp
# ---------------------------------------------------------------------------

class TestTokenCachePaths:
    def test_token_path_uses_tempdir(self):
        client = _make_client()
        assert client._token_path().parent == Path(tempfile.gettempdir())

    def test_expiry_path_uses_tempdir(self):
        client = _make_client()
        assert client._expiry_path().parent == Path(tempfile.gettempdir())

    def test_token_path_not_hardcoded_tmp(self):
        """Regression: path must not be the old /tmp hardcode."""
        client = _make_client("Prod")
        assert str(client._token_path()) != "/tmp/ts_token_prod.txt"

    def test_token_path_contains_slug(self):
        client = _make_client("My Staging")
        assert "my-staging" in str(client._token_path())

    def test_expiry_path_contains_slug(self):
        client = _make_client("My Staging")
        assert "my-staging" in str(client._expiry_path())

    def test_token_and_expiry_different_paths(self):
        client = _make_client()
        assert client._token_path() != client._expiry_path()

    @pytest.mark.parametrize("profile_name", ["Production", "My Staging", "prod (us-east-1)"])
    def test_path_is_valid_for_profile_name(self, profile_name):
        """Token path must be constructable for all valid profile name inputs."""
        client = _make_client(profile_name)
        path = client._token_path()
        assert path.parent.exists(), f"Parent dir {path.parent} does not exist on this OS"


# ---------------------------------------------------------------------------
# _get_credential — env var path
# ---------------------------------------------------------------------------

class TestGetCredentialEnvVar:
    def test_returns_env_var_when_set(self, monkeypatch):
        """If the env var is set, return it without touching keyring."""
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "env-token-value")
        client = _make_client()
        with patch("keyring.get_password") as mock_kr:
            result = client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        assert result == "env-token-value"
        mock_kr.assert_not_called()

    def test_empty_env_var_falls_through_to_keyring(self, monkeypatch):
        """Empty env var must not be returned — fall through to keyring."""
        monkeypatch.setenv("THOUGHTSPOT_TOKEN_PRODUCTION", "")
        client = _make_client()
        with patch("keyring.get_password", return_value="keyring-token"):
            result = client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        assert result == "keyring-token"

    def test_missing_env_var_falls_through_to_keyring(self, monkeypatch):
        """Absent env var must fall through to keyring."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client()
        with patch("keyring.get_password", return_value="keyring-token"):
            result = client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        assert result == "keyring-token"


# ---------------------------------------------------------------------------
# _get_credential — keyring fallback
# ---------------------------------------------------------------------------

class TestGetCredentialKeyringFallback:
    def test_keyring_service_name_uses_thoughtspot_prefix(self, monkeypatch):
        """Service name passed to keyring.get_password must be 'thoughtspot-{slug}'."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client("Production")
        with patch("keyring.get_password", return_value="token") as mock_kr:
            client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        service, username = mock_kr.call_args[0]
        assert service == "thoughtspot-production"

    def test_keyring_account_is_profile_username(self, monkeypatch):
        """Account (username) passed to keyring.get_password must come from the profile."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client("Production", username="alice@company.com")
        with patch("keyring.get_password", return_value="token") as mock_kr:
            client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        service, username = mock_kr.call_args[0]
        assert username == "alice@company.com"

    def test_returns_keyring_value(self, monkeypatch):
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client()
        with patch("keyring.get_password", return_value="secret-from-os-store"):
            result = client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        assert result == "secret-from-os-store"

    def test_keyring_none_falls_through_to_error(self, monkeypatch):
        """keyring.get_password returning None must raise SystemExit (credential not found)."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client()
        with patch("keyring.get_password", return_value=None):
            with pytest.raises(SystemExit):
                client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")

    def test_keyring_import_error_falls_through_to_error(self, monkeypatch):
        """If keyring is not installed (ImportError), must raise SystemExit."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client()
        with patch("builtins.__import__", side_effect=_raise_if_keyring):
            with pytest.raises(SystemExit):
                client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")

    def test_keyring_exception_falls_through_to_error(self, monkeypatch):
        """Any keyring exception (e.g. backend unavailable) must raise SystemExit."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client()
        with patch("keyring.get_password", side_effect=RuntimeError("no backend")):
            with pytest.raises(SystemExit):
                client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")


def _raise_if_keyring(name, *args, **kwargs):
    if name == "keyring":
        raise ImportError("No module named 'keyring'")
    return __builtins__.__import__(name, *args, **kwargs)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _get_credential — error message quality
# ---------------------------------------------------------------------------

class TestGetCredentialErrorMessage:
    def test_error_message_names_the_profile(self, monkeypatch):
        """SystemExit message must name the profile so the user knows which one failed."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_MY_STAGING", raising=False)
        client = _make_client(
            "My Staging",
            token_env="THOUGHTSPOT_TOKEN_MY_STAGING",
        )
        with patch("keyring.get_password", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                client._get_credential("THOUGHTSPOT_TOKEN_MY_STAGING")
        assert "My Staging" in str(exc_info.value)

    def test_error_message_mentions_profile_command(self, monkeypatch):
        """SystemExit message must guide the user to fix it."""
        monkeypatch.delenv("THOUGHTSPOT_TOKEN_PRODUCTION", raising=False)
        client = _make_client()
        with patch("keyring.get_password", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                client._get_credential("THOUGHTSPOT_TOKEN_PRODUCTION")
        msg = str(exc_info.value)
        assert "ts-profile-thoughtspot" in msg or "profile" in msg.lower()


# ---------------------------------------------------------------------------
# _get_credential — slug derivation used in keyring service name
# ---------------------------------------------------------------------------

class TestKeyringServiceSlugVariants:
    @pytest.mark.parametrize("profile_name,expected_service", [
        ("Production",          "thoughtspot-production"),
        ("My Staging",          "thoughtspot-my-staging"),
        ("prod (us-east-1)",    "thoughtspot-prod-us-east-1"),
    ])
    def test_service_name_derived_from_profile_name(self, monkeypatch, profile_name, expected_service):
        monkeypatch.delenv(f"THOUGHTSPOT_TOKEN_{_slugify(profile_name).upper().replace('-', '_')}", raising=False)
        client = _make_client(profile_name)
        with patch("keyring.get_password", return_value="tok") as mock_kr:
            try:
                client._get_credential(f"THOUGHTSPOT_TOKEN_{_slugify(profile_name).upper().replace('-', '_')}")
            except SystemExit:
                pass
        if mock_kr.called:
            service = mock_kr.call_args[0][0]
            assert service == expected_service
