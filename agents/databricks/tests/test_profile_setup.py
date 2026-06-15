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
    """Import create_profile and test_profile from the notebooks directory."""
    notebooks_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "notebooks")
    )
    if notebooks_dir not in sys.path:
        sys.path.insert(0, notebooks_dir)
    from ts_profile_setup import create_profile, test_profile
    return create_profile, test_profile


# ===========================================================================
# TestCreateProfile
# ===========================================================================

class TestCreateProfile:
    """Tests for create_profile()."""

    def test_creates_scope_and_stores_secrets(self, mock_dbutils):
        """bearer_token profile: scope created and all four secrets stored correctly."""
        create_profile, _ = _import_setup()

        mock_dbutils.widgets._set("profile_name", "staging")
        mock_dbutils.widgets._set("base_url", "https://staging.thoughtspot.cloud/")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "user@example.com")
        mock_dbutils.widgets._set("credential", "my-bearer-token")

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
        create_profile, _ = _import_setup()

        mock_dbutils.widgets._set("profile_name", "prod")
        mock_dbutils.widgets._set("base_url", "https://prod.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "password")
        mock_dbutils.widgets._set("username", "admin@corp.com")
        mock_dbutils.widgets._set("credential", "s3cr3t!")

        scope = create_profile(mock_dbutils)

        secrets = mock_dbutils.secrets._scopes[scope]
        assert secrets["password"] == "s3cr3t!"
        assert "token" not in secrets
        assert "secret_key" not in secrets

    def test_secret_key_auth_stores_secret_key(self, mock_dbutils):
        """secret_key auth: credential stored under key 'secret_key'."""
        create_profile, _ = _import_setup()

        mock_dbutils.widgets._set("profile_name", "dev")
        mock_dbutils.widgets._set("base_url", "https://dev.thoughtspot.cloud")
        mock_dbutils.widgets._set("auth_method", "secret_key")
        mock_dbutils.widgets._set("username", "svc@corp.com")
        mock_dbutils.widgets._set("credential", "sk-abcdef123456")

        scope = create_profile(mock_dbutils)

        secrets = mock_dbutils.secrets._scopes[scope]
        assert secrets["secret_key"] == "sk-abcdef123456"
        assert "token" not in secrets
        assert "password" not in secrets

    def test_widgets_cleared_after_setup(self, mock_dbutils):
        """Widgets are removed after create_profile returns."""
        create_profile, _ = _import_setup()

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://ts.example.com")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "admin@example.com")
        mock_dbutils.widgets._set("credential", "tok-xyz")

        create_profile(mock_dbutils)

        assert mock_dbutils.widgets._values == {}

    def test_existing_scope_does_not_raise(self, mock_dbutils):
        """create_profile does not raise when the scope already exists."""
        create_profile, _ = _import_setup()

        # Pre-create the scope to simulate an existing profile.
        mock_dbutils.secrets.createScope("thoughtspot-default")

        mock_dbutils.widgets._set("profile_name", "default")
        mock_dbutils.widgets._set("base_url", "https://ts.example.com")
        mock_dbutils.widgets._set("auth_method", "bearer_token")
        mock_dbutils.widgets._set("username", "admin@example.com")
        mock_dbutils.widgets._set("credential", "tok-new")

        # Should not raise even though the scope already exists.
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
        _, test_profile_fn = _import_setup()
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
        _, test_profile_fn = _import_setup()
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
