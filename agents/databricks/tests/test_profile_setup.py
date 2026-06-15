"""
test_profile_setup.py — Unit tests for ts_profile_setup CRUD operations.

Tests cover:
  - create_profile: scope created, secrets stored, widgets cleared
  - update_profile: metadata updated, credential skipped when blank
  - list_profiles: scans scopes, handles edge cases
  - delete_profile: removes scope, idempotent
  - setup_update_widgets: pre-populates from existing profile
  - test_profile: instantiates ThoughtSpotClient and calls whoami()

All tests are offline — no live Databricks or ThoughtSpot instance required.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_setup():
    """Import all public functions from the notebooks directory."""
    notebooks_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "notebooks")
    )
    if notebooks_dir not in sys.path:
        sys.path.insert(0, notebooks_dir)
    from ts_profile_setup import (
        create_profile,
        update_profile,
        test_profile,
        list_profiles,
        delete_profile,
        setup_update_widgets,
    )
    return create_profile, update_profile, test_profile, list_profiles, delete_profile, setup_update_widgets


def _patch_secrets_api(mock_dbutils):
    """Patch _create_scope and _put_secret to delegate to the mock dbutils."""
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
        create_profile, *_ = _import_setup()
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
        assert secrets["base_url"] == "https://staging.thoughtspot.cloud"
        assert secrets["auth_method"] == "bearer_token"
        assert secrets["username"] == "user@example.com"
        assert secrets["token"] == "my-bearer-token"

    def test_password_auth_stores_password_key(self, mock_dbutils):
        """password auth: credential stored under key 'password'."""
        create_profile, *_ = _import_setup()
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
        create_profile, *_ = _import_setup()
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
        create_profile, *_ = _import_setup()
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
        create_profile, *_ = _import_setup()
        p1, p2 = _patch_secrets_api(mock_dbutils)

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
# TestUpdateProfile
# ===========================================================================

class TestUpdateProfile:
    """Tests for update_profile()."""

    def _setup_existing_profile(self, mock_dbutils, name="default"):
        """Pre-populate a profile so update has something to modify."""
        scope = f"thoughtspot-{name}"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://old.thoughtspot.cloud")
        mock_dbutils.secrets.put(scope, "auth_method", "bearer_token")
        mock_dbutils.secrets.put(scope, "username", "old@example.com")
        mock_dbutils.secrets.put(scope, "token", "old-token")
        return scope

    def test_updates_metadata(self, mock_dbutils):
        """Metadata fields (base_url, auth_method, username) are overwritten."""
        _, update_profile, *_ = _import_setup()
        _, p2 = _patch_secrets_api(mock_dbutils)
        self._setup_existing_profile(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://new.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "password")
        mock_dbutils.widgets._set("username", "new@example.com")
        mock_dbutils.widgets._set("credential", "")

        with p2:
            scope = update_profile(mock_dbutils)

        assert scope == "thoughtspot-default"
        secrets = mock_dbutils.secrets._scopes["thoughtspot-default"]
        assert secrets["base_url"] == "https://new.thoughtspot.cloud"
        assert secrets["auth_method"] == "password"
        assert secrets["username"] == "new@example.com"

    def test_skips_credential_when_blank(self, mock_dbutils):
        """Blank credential widget preserves the existing credential."""
        _, update_profile, *_ = _import_setup()
        _, p2 = _patch_secrets_api(mock_dbutils)
        self._setup_existing_profile(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://old.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "old@example.com")
        mock_dbutils.widgets._set("credential", "")

        with p2:
            update_profile(mock_dbutils)

        assert mock_dbutils.secrets._scopes["thoughtspot-default"]["token"] == "old-token"

    def test_updates_credential_when_provided(self, mock_dbutils):
        """Non-blank credential widget overwrites the stored credential."""
        _, update_profile, *_ = _import_setup()
        _, p2 = _patch_secrets_api(mock_dbutils)
        self._setup_existing_profile(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://old.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "old@example.com")
        mock_dbutils.widgets._set("credential", "brand-new-token")

        with p2:
            update_profile(mock_dbutils)

        assert mock_dbutils.secrets._scopes["thoughtspot-default"]["token"] == "brand-new-token"

    def test_widgets_cleared_after_update(self, mock_dbutils):
        """Widgets are removed after update_profile returns."""
        _, update_profile, *_ = _import_setup()
        _, p2 = _patch_secrets_api(mock_dbutils)
        self._setup_existing_profile(mock_dbutils)

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://old.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "old@example.com")
        mock_dbutils.widgets._set("credential", "")

        with p2:
            update_profile(mock_dbutils)

        assert mock_dbutils.widgets._values == {}


# ===========================================================================
# TestSetupUpdateWidgets
# ===========================================================================

class TestSetupUpdateWidgets:
    """Tests for setup_update_widgets()."""

    def test_prepopulates_from_existing_profile(self, mock_dbutils):
        """Widgets get defaults from the existing scope."""
        *_, setup_update_widgets = _import_setup()

        scope = "thoughtspot-staging"
        mock_dbutils.secrets.createScope(scope)
        mock_dbutils.secrets.put(scope, "base_url", "https://staging.ts.cloud")
        mock_dbutils.secrets.put(scope, "auth_method", "password")
        mock_dbutils.secrets.put(scope, "username", "admin@staging.com")

        setup_update_widgets("staging", mock_dbutils)

        assert mock_dbutils.widgets.get("profile_name") == "staging"
        assert mock_dbutils.widgets.get("base_url") == "https://staging.ts.cloud"
        assert mock_dbutils.widgets.get("auth_method") == "password"
        assert mock_dbutils.widgets.get("username") == "admin@staging.com"
        assert mock_dbutils.widgets.get("credential") == ""

    def test_falls_back_to_blanks_on_missing_profile(self, mock_dbutils):
        """Non-existent profile gets blank widget defaults."""
        *_, setup_update_widgets = _import_setup()

        setup_update_widgets("nonexistent", mock_dbutils)

        assert mock_dbutils.widgets.get("profile_name") == "nonexistent"
        assert mock_dbutils.widgets.get("base_url") == ""
        assert mock_dbutils.widgets.get("auth_method") == "bearer_token"
        assert mock_dbutils.widgets.get("username") == ""
        assert mock_dbutils.widgets.get("credential") == ""


# ===========================================================================
# TestListProfiles
# ===========================================================================

class TestListProfiles:
    """Tests for list_profiles()."""

    def test_returns_empty_when_no_profiles(self, mock_dbutils):
        """No thoughtspot-* scopes → empty list."""
        *_, list_profiles, _, _ = _import_setup()
        assert list_profiles(mock_dbutils) == []

    def test_lists_single_profile(self, profile_secrets):
        """Pre-populated profile appears with correct metadata."""
        *_, list_profiles, _, _ = _import_setup()
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
        *_, list_profiles, _, _ = _import_setup()

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
        *_, list_profiles, _, _ = _import_setup()

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
        *_, list_profiles, _, _ = _import_setup()

        mock_dbutils.secrets.createScope("thoughtspot-broken")
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
        *_, delete_profile, _ = _import_setup()
        mock_dbutils, _ = profile_secrets

        with _patch_delete_scope(mock_dbutils):
            result = delete_profile("default", mock_dbutils)

        assert result == "thoughtspot-default"
        assert "thoughtspot-default" not in mock_dbutils.secrets._scopes

    def test_delete_nonexistent_profile_does_not_raise(self, mock_dbutils):
        """Deleting a profile that doesn't exist is a no-op."""
        *_, delete_profile, _ = _import_setup()

        with _patch_delete_scope(mock_dbutils):
            result = delete_profile("nonexistent", mock_dbutils)

        assert result == "thoughtspot-nonexistent"

    def test_delete_does_not_affect_other_profiles(self, mock_dbutils):
        """Deleting one profile leaves other profiles intact."""
        *_, delete_profile, _ = _import_setup()

        for name in ("keep-me", "delete-me"):
            scope = f"thoughtspot-{name}"
            mock_dbutils.secrets.createScope(scope)
            mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")

        with _patch_delete_scope(mock_dbutils):
            delete_profile("delete-me", mock_dbutils)

        assert "thoughtspot-keep-me" in mock_dbutils.secrets._scopes
        assert "thoughtspot-delete-me" not in mock_dbutils.secrets._scopes


# ===========================================================================
# TestTestProfile
# ===========================================================================

class TestTestProfile:
    """Tests for test_profile()."""

    def test_whoami_called(self, profile_secrets):
        """test_profile calls whoami() and returns the user dict."""
        _, _, test_profile_fn, *_ = _import_setup()
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
        _, _, test_profile_fn, *_ = _import_setup()
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
