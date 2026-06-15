"""
test_profile_setup.py — Unit tests for ts_profile_setup (Task 6).

Tests cover:
  - create_profile: scope created, all secrets stored under the correct keys,
    widgets cleared after setup
  - test_profile: instantiates ThoughtSpotClient and calls whoami()

All tests are offline — no live Databricks or ThoughtSpot instance required.
requests.request is mocked for test_profile tests.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_setup():
    """Import functions from the notebooks directory."""
    notebooks_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "notebooks")
    )
    if notebooks_dir not in sys.path:
        sys.path.insert(0, notebooks_dir)
    from ts_profile_setup import (
        create_profile, test_profile, list_profiles, delete_profile,
    )
    return create_profile, test_profile, list_profiles, delete_profile


def _patch_secrets_api(mock_dbutils):
    """Patch _create_scope and _put_secret to delegate to the mock dbutils.

    In production these use the Databricks REST API; in tests we redirect
    them to the in-memory MockSecrets so assertions on _scopes still work.
    """
    def _mock_create_scope(dbutils, scope):
        mock_dbutils.secrets.createScope(scope)

    def _mock_put_secret(dbutils, scope, key, value):
        mock_dbutils.secrets.put(scope, key, value)

    return (
        patch("ts_profile_setup._create_scope", side_effect=_mock_create_scope),
        patch("ts_profile_setup._put_secret", side_effect=_mock_put_secret),
    )


def _patch_delete_scope(mock_dbutils):
    """Patch _delete_scope to delegate to mock_dbutils.secrets.deleteScope."""
    def _mock_delete(dbutils, scope):
        mock_dbutils.secrets.deleteScope(scope)
    return patch("ts_profile_setup._delete_scope", side_effect=_mock_delete)


# ===========================================================================
# TestCreateProfile
# ===========================================================================

class TestCreateProfile:
    """Tests for create_profile()."""

    def test_creates_scope_and_stores_secrets(self, mock_dbutils):
        """bearer_token profile: scope created and all four secrets stored correctly."""
        create_profile, _, _, _ = _import_setup()
        p1, p2 = _patch_secrets_api(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "staging")
        mock_dbutils.widgets._set("base_url", "https://staging.thoughtspot.cloud/")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "user@example.com")
        mock_dbutils.widgets._set("credential", "my-bearer-token")

        with p1, p2:
            scope = create_profile(mock_dbutils)

        assert scope == "thoughtspot-staging"
        assert "thoughtspot-staging" in mock_dbutils.secrets._scopes

        secrets = mock_dbutils.secrets._scopes["thoughtspot-staging"]
        # base_url trailing slash should be stripped
        assert secrets["base_url"] == "https://staging.thoughtspot.cloud"
        assert secrets["auth_method"] == "bearer_token"
        assert secrets["username"] == "user@example.com"
        # bearer_token maps to key "token"
        assert secrets["token"] == "my-bearer-token"

    def test_password_auth_stores_password_key(self, mock_dbutils):
        """password auth: credential stored under key 'password'."""
        create_profile, _, _, _ = _import_setup()
        p1, p2 = _patch_secrets_api(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "prod")
        mock_dbutils.widgets._set("base_url", "https://prod.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "password")
        mock_dbutils.widgets._set("username", "admin@corp.com")
        mock_dbutils.widgets._set("credential", "s3cr3t!")

        with p1, p2:
            scope = create_profile(mock_dbutils)

        secrets = mock_dbutils.secrets._scopes[scope]
        assert secrets["password"] == "s3cr3t!"
        assert "token" not in secrets
        assert "secret_key" not in secrets

    def test_secret_key_auth_stores_secret_key(self, mock_dbutils):
        """secret_key auth: credential stored under key 'secret_key'."""
        create_profile, _, _, _ = _import_setup()
        p1, p2 = _patch_secrets_api(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "dev")
        mock_dbutils.widgets._set("base_url", "https://dev.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "secret_key")
        mock_dbutils.widgets._set("username", "svc@corp.com")
        mock_dbutils.widgets._set("credential", "sk-abcdef123456")

        with p1, p2:
            scope = create_profile(mock_dbutils)

        secrets = mock_dbutils.secrets._scopes[scope]
        assert secrets["secret_key"] == "sk-abcdef123456"
        assert "token" not in secrets
        assert "password" not in secrets

    def test_widgets_cleared_after_setup(self, mock_dbutils):
        """Widgets are removed after create_profile returns."""
        create_profile, _, _, _ = _import_setup()
        p1, p2 = _patch_secrets_api(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://ts.example.com")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "admin@example.com")
        mock_dbutils.widgets._set("credential", "tok-xyz")

        with p1, p2:
            create_profile(mock_dbutils)

        assert mock_dbutils.widgets._values == {}

    def test_existing_scope_does_not_raise(self, mock_dbutils):
        """create_profile does not raise when the scope already exists."""
        create_profile, _, _, _ = _import_setup()
        p1, p2 = _patch_secrets_api(mock_dbutils)

        # Pre-create the scope to simulate an existing profile.
        mock_dbutils.secrets.createScope("thoughtspot-default")

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://ts.example.com")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "admin@example.com")
        mock_dbutils.widgets._set("credential", "tok-new")

        with p1, p2:
            scope = create_profile(mock_dbutils)
        assert scope == "thoughtspot-default"
        assert mock_dbutils.secrets._scopes["thoughtspot-default"]["token"] == "tok-new"


# ===========================================================================
# TestTestProfile
# ===========================================================================

class TestTestProfile:
    """Tests for test_profile()."""

    def test_whoami_called(self, profile_secrets):
        """test_profile calls whoami() and returns the user dict."""
        _, test_profile_fn, _, _ = _import_setup()
        mock_dbutils, scope = profile_secrets

        whoami_payload = {
            "id": "abc-123",
            "name": "admin@example.com",
            "displayName": "Admin User",
        }

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = whoami_payload

        with patch("requests.request", return_value=mock_response):
            result = test_profile_fn("default", mock_dbutils)

        assert result == whoami_payload

    def test_whoami_returns_user_fields(self, profile_secrets):
        """test_profile result dict contains expected user fields."""
        _, test_profile_fn, _, _ = _import_setup()
        mock_dbutils, _ = profile_secrets

        user_data = {"id": "user-guid-999", "name": "alice@corp.com"}
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = user_data

        with patch("requests.request", return_value=mock_response):
            result = test_profile_fn("default", mock_dbutils)

        assert result["id"] == "user-guid-999"
        assert result["name"] == "alice@corp.com"


# ===========================================================================
# TestListProfiles
# ===========================================================================

class TestListProfiles:
    """Tests for list_profiles()."""

    def test_returns_empty_when_no_profiles(self, mock_dbutils):
        """No thoughtspot-* scopes → empty list."""
        _, _, list_profiles, _ = _import_setup()
        assert list_profiles(mock_dbutils) == []

    def test_lists_single_profile(self, profile_secrets):
        """Pre-populated profile appears in the list with correct metadata."""
        _, _, list_profiles, _ = _import_setup()
        mock_dbutils, _ = profile_secrets

        profiles = list_profiles(mock_dbutils)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "default"
        assert profiles[0]["scope"] == "thoughtspot-default"
        assert profiles[0]["base_url"] == "https://ts.example.com"
        assert profiles[0]["auth_method"] == "bearer_token"
        assert profiles[0]["username"] == "admin@example.com"

    def test_lists_multiple_profiles(self, mock_dbutils):
        """Multiple thoughtspot-* scopes all appear."""
        _, _, list_profiles, _ = _import_setup()

        for name in ("dev", "staging", "prod"):
            scope = f"thoughtspot-{name}"
            mock_dbutils.secrets.createScope(scope)
            mock_dbutils.secrets.put(scope, "base_url", f"https://{name}.ts.cloud")
            mock_dbutils.secrets.put(scope, "auth_method", "password")
            mock_dbutils.secrets.put(scope, "username", f"{name}@example.com")

        profiles = list_profiles(mock_dbutils)
        names = {p["name"] for p in profiles}
        assert names == {"dev", "staging", "prod"}

    def test_ignores_non_thoughtspot_scopes(self, mock_dbutils):
        """Scopes not starting with thoughtspot- are excluded."""
        _, _, list_profiles, _ = _import_setup()

        mock_dbutils.secrets.createScope("databricks-config")
        mock_dbutils.secrets.put("databricks-config", "token", "abc")

        scope = "thoughtspot-myprofile"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
        mock_dbutils.secrets.put(scope, "auth_method", "bearer_token")
        mock_dbutils.secrets.put(scope, "username", "user@example.com")

        profiles = list_profiles(mock_dbutils)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "myprofile"

    def test_handles_incomplete_scope(self, mock_dbutils):
        """A scope missing keys shows '?' for those fields."""
        _, _, list_profiles, _ = _import_setup()

        mock_dbutils.secrets.createScope("thoughtspot-broken")
        # Only base_url set — auth_method and username missing
        mock_dbutils.secrets.put("thoughtspot-broken", "base_url", "https://ts.example.com")

        profiles = list_profiles(mock_dbutils)
        assert len(profiles) == 1
        assert profiles[0]["base_url"] == "?"
        assert profiles[0]["auth_method"] == "?"
        assert profiles[0]["username"] == "?"


# ===========================================================================
# TestDeleteProfile
# ===========================================================================

class TestDeleteProfile:
    """Tests for delete_profile()."""

    def test_deletes_existing_profile(self, profile_secrets):
        """Deleting an existing profile removes the scope entirely."""
        _, _, _, delete_profile = _import_setup()
        mock_dbutils, _ = profile_secrets

        with _patch_delete_scope(mock_dbutils):
            result = delete_profile("default", mock_dbutils)

        assert result == "thoughtspot-default"
        assert "thoughtspot-default" not in mock_dbutils.secrets._scopes

    def test_delete_nonexistent_profile_does_not_raise(self, mock_dbutils):
        """Deleting a profile that doesn't exist is a no-op."""
        _, _, _, delete_profile = _import_setup()

        with _patch_delete_scope(mock_dbutils):
            result = delete_profile("nonexistent", mock_dbutils)

        assert result == "thoughtspot-nonexistent"

    def test_delete_does_not_affect_other_profiles(self, mock_dbutils):
        """Deleting one profile leaves other profiles intact."""
        _, _, _, delete_profile = _import_setup()

        for name in ("keep-me", "delete-me"):
            scope = f"thoughtspot-{name}"
            mock_dbutils.secrets.createScope(scope)
            mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")

        with _patch_delete_scope(mock_dbutils):
            delete_profile("delete-me", mock_dbutils)

        assert "thoughtspot-keep-me" in mock_dbutils.secrets._scopes
        assert "thoughtspot-delete-me" not in mock_dbutils.secrets._scopes
