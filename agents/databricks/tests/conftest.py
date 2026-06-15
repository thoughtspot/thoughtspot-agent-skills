"""
conftest.py — shared pytest fixtures for agents/databricks tests.

Provides offline replacements for the Databricks dbutils object so tests
can run without a live Databricks cluster.
"""

import builtins

import pytest


class MockSecrets:
    """In-memory replacement for dbutils.secrets."""

    def __init__(self):
        # Internal store: {scope: {key: value}}
        self._scopes: dict[str, dict[str, str]] = {}

    def createScope(self, scope: str) -> None:
        """Create a new secrets scope (idempotent)."""
        if scope not in self._scopes:
            self._scopes[scope] = {}

    def put(self, scope: str, key: str, string_value: str) -> None:
        """Store a secret value under the given scope and key."""
        if scope not in self._scopes:
            raise KeyError(f"Scope '{scope}' does not exist. Call createScope first.")
        self._scopes[scope][key] = string_value

    def get(self, scope: str, key: str) -> str:
        """Retrieve a secret value by scope and key."""
        if scope not in self._scopes:
            raise KeyError(f"Scope '{scope}' not found.")
        if key not in self._scopes[scope]:
            raise KeyError(f"Key '{key}' not found in scope '{scope}'.")
        return self._scopes[scope][key]

    def list(self, scope: str) -> "list[str]":
        """List all keys in a scope (returns key names, not values)."""
        if scope not in self._scopes:
            raise KeyError(f"Scope '{scope}' not found.")
        return builtins.list(self._scopes[scope].keys())

    def listScopes(self) -> "list[str]":
        """List all scope names."""
        return builtins.list(self._scopes.keys())


class MockWidgets:
    """In-memory replacement for dbutils.widgets."""

    def __init__(self):
        self._values: dict[str, str] = {}

    def text(self, name: str, default_value: str, label: str = "") -> None:
        """Register a text widget with a default value."""
        # Only set if not already set (allows overriding in tests via _set)
        if name not in self._values:
            self._values[name] = default_value

    def dropdown(self, name: str, default_value: str, choices: list[str], label: str = "") -> None:
        """Register a dropdown widget with a default value."""
        if name not in self._values:
            self._values[name] = default_value

    def get(self, name: str) -> str:
        """Retrieve the current value of a widget."""
        if name not in self._values:
            raise KeyError(f"Widget '{name}' not found. Register it with text() or dropdown() first.")
        return self._values[name]

    def removeAll(self) -> None:
        """Remove all registered widgets."""
        self._values.clear()

    def _set(self, name: str, value: str) -> None:
        """Test-only helper: set a widget value directly without registering it as text/dropdown."""
        self._values[name] = value


class MockDbutils:
    """Top-level mock combining MockSecrets and MockWidgets.

    Mirrors the shape of the real Databricks dbutils object so code that
    does ``dbutils.secrets.get(...)`` or ``dbutils.widgets.get(...)`` works
    unchanged in tests.
    """

    def __init__(self):
        self.secrets = MockSecrets()
        self.widgets = MockWidgets()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_dbutils() -> MockDbutils:
    """Return a fresh MockDbutils instance for each test."""
    return MockDbutils()


@pytest.fixture
def profile_secrets(mock_dbutils: MockDbutils) -> tuple[MockDbutils, str]:
    """Pre-populate a 'default' ThoughtSpot profile with bearer_token auth.

    Scope: thoughtspot-default
    Keys stored:
        base_url        https://ts.example.com
        auth_method     bearer_token
        username        admin@example.com
        token           test-bearer-token-abc123

    Returns:
        (mock_dbutils, scope_name) so tests can both inspect the dbutils
        object and know the scope name without hard-coding it.
    """
    scope = "thoughtspot-default"
    mock_dbutils.secrets.createScope(scope)
    mock_dbutils.secrets.put(scope, "base_url", "https://ts.example.com")
    mock_dbutils.secrets.put(scope, "auth_method", "bearer_token")
    mock_dbutils.secrets.put(scope, "username", "admin@example.com")
    mock_dbutils.secrets.put(scope, "token", "test-bearer-token-abc123")
    return mock_dbutils, scope
