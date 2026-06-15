# Databricks notebook source
# DBTITLE 1,Install dependencies
# MAGIC %pip install -q requests

# COMMAND ----------

# DBTITLE 1,Load ThoughtSpotClient
# MAGIC %run ./ts_client

# COMMAND ----------

"""
ts_profile_setup.py — CRUD manager for ThoughtSpot profiles in Databricks Secrets.

Actions: Create, List, Update, Delete, Test.

Consumed interactively from a Databricks notebook (action dropdown + widgets),
or imported directly in tests (add ``agents/databricks/notebooks/`` to sys.path).

Design
------
- Widget-driven: action dropdown selects the operation; input widgets collect
  parameters for Create/Update/Delete/Test.
- Secrets-backed: credentials stored in Databricks Secrets under scope
  ``thoughtspot-{profile_name}``.
- Testable: all logic lives in plain functions — no side effects at import time.
"""

from __future__ import annotations

import requests as _requests

# ---------------------------------------------------------------------------
# Credential key map
# ---------------------------------------------------------------------------

_CREDENTIAL_KEY_MAP: dict[str, str] = {
    "bearer_token": "token",
    "password": "password",
    "secret_key": "secret_key",
}

_ACTIONS: list[str] = ["List", "Create", "Update", "Delete", "Test"]


# ---------------------------------------------------------------------------
# Secrets REST API helpers — dbutils.secrets is read-only in Databricks;
# writes go through the REST API.
# ---------------------------------------------------------------------------

def _workspace_auth(dbutils) -> tuple[str, dict]:
    """Extract the workspace host and auth headers from the notebook context."""
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    host = ctx.apiUrl().get().rstrip("/")
    token = ctx.apiToken().get()
    return host, {"Authorization": f"Bearer {token}"}


def _create_scope(dbutils, scope: str) -> None:
    """Create a Databricks Secrets scope via REST API (idempotent)."""
    host, headers = _workspace_auth(dbutils)
    resp = _requests.post(
        f"{host}/api/2.0/secrets/scopes/create",
        json={"scope": scope},
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 409:
        return
    resp.raise_for_status()


def _put_secret(dbutils, scope: str, key: str, value: str) -> None:
    """Write a secret value via REST API."""
    host, headers = _workspace_auth(dbutils)
    resp = _requests.post(
        f"{host}/api/2.0/secrets/put",
        json={"scope": scope, "key": key, "string_value": value},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()


def _delete_scope(dbutils, scope: str) -> None:
    """Delete a Databricks Secrets scope and all its secrets via REST API."""
    host, headers = _workspace_auth(dbutils)
    resp = _requests.post(
        f"{host}/api/2.0/secrets/scopes/delete",
        json={"scope": scope},
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 404:
        return
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Widget setup
# ---------------------------------------------------------------------------

def setup_widgets(dbutils) -> None:
    """Show input widgets for creating a new profile (blank defaults)."""
    dbutils.widgets.text("profile_name", "default", "Profile Name")
    dbutils.widgets.text("base_url", "", "ThoughtSpot Base URL")
    dbutils.widgets.text("username", "", "Username")
    dbutils.widgets.text("credential", "", "Credential (token / password / secret key)")
    dbutils.widgets.dropdown(
        "auth_method",
        "bearer_token",
        ["bearer_token", "password", "secret_key"],
        "Auth Method",
    )


def setup_update_widgets(profile_name: str, dbutils) -> None:
    """Show input widgets pre-populated with existing profile values.

    Reads ``base_url``, ``auth_method``, and ``username`` from the existing
    scope and uses them as widget defaults. The credential widget is always
    blank — leave it empty to keep the existing credential, or enter a new
    value to replace it.

    Falls back to blank defaults if the profile doesn't exist.
    """
    scope = f"thoughtspot-{profile_name}"
    try:
        base_url = dbutils.secrets.get(scope, "base_url")
        auth_method = dbutils.secrets.get(scope, "auth_method")
        username = dbutils.secrets.get(scope, "username")
    except Exception:
        base_url = ""
        auth_method = "bearer_token"
        username = ""

    dbutils.widgets.text("profile_name", profile_name, "Profile Name")
    dbutils.widgets.text("base_url", base_url, "ThoughtSpot Base URL")
    dbutils.widgets.text("username", username, "Username")
    dbutils.widgets.text("credential", "", "New credential (blank = keep existing)")
    dbutils.widgets.dropdown(
        "auth_method",
        auth_method,
        ["bearer_token", "password", "secret_key"],
        "Auth Method",
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_profile(dbutils) -> str:
    """Read widget values and store a new profile in Databricks Secrets.

    Creates the scope ``thoughtspot-{profile_name}`` if it does not already
    exist, stores all fields, then clears widgets.

    Returns the scope name.
    """
    profile_name = dbutils.widgets.get("profile_name")
    base_url = dbutils.widgets.get("base_url").rstrip("/")
    auth_method = dbutils.widgets.get("auth_method")
    username = dbutils.widgets.get("username")
    credential = dbutils.widgets.get("credential")

    scope = f"thoughtspot-{profile_name}"

    _create_scope(dbutils, scope)
    _put_secret(dbutils, scope, "base_url", base_url)
    _put_secret(dbutils, scope, "auth_method", auth_method)
    _put_secret(dbutils, scope, "username", username)

    credential_key = _CREDENTIAL_KEY_MAP[auth_method]
    _put_secret(dbutils, scope, credential_key, credential)

    dbutils.widgets.removeAll()
    return scope


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_profile(dbutils) -> str:
    """Read widget values and update an existing profile.

    Same as :func:`create_profile` except:
    - Does NOT create a new scope (the scope must already exist).
    - Skips the credential write if the credential widget is blank,
      preserving the existing credential in Secrets.

    Returns the scope name.
    """
    profile_name = dbutils.widgets.get("profile_name")
    base_url = dbutils.widgets.get("base_url").rstrip("/")
    auth_method = dbutils.widgets.get("auth_method")
    username = dbutils.widgets.get("username")
    credential = dbutils.widgets.get("credential")

    scope = f"thoughtspot-{profile_name}"

    _put_secret(dbutils, scope, "base_url", base_url)
    _put_secret(dbutils, scope, "auth_method", auth_method)
    _put_secret(dbutils, scope, "username", username)

    if credential:
        credential_key = _CREDENTIAL_KEY_MAP[auth_method]
        _put_secret(dbutils, scope, credential_key, credential)

    dbutils.widgets.removeAll()
    return scope


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def list_profiles(dbutils) -> list[dict]:
    """List all ThoughtSpot profiles stored in Databricks Secrets.

    Returns metadata only — credential values are never included.
    """
    profiles = []
    for s in dbutils.secrets.listScopes():
        scope = s.name if hasattr(s, "name") else s
        if not scope.startswith("thoughtspot-"):
            continue
        name = scope[len("thoughtspot-"):]
        try:
            base_url = dbutils.secrets.get(scope, "base_url")
            auth_method = dbutils.secrets.get(scope, "auth_method")
            username = dbutils.secrets.get(scope, "username")
        except Exception:
            base_url = auth_method = username = "?"
        profiles.append({
            "name": name,
            "scope": scope,
            "base_url": base_url,
            "auth_method": auth_method,
            "username": username,
        })
    return profiles


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_profile(profile_name: str, dbutils) -> str:
    """Delete a ThoughtSpot profile (scope + all secrets). Idempotent."""
    scope = f"thoughtspot-{profile_name}"
    _delete_scope(dbutils, scope)
    return scope


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_profile(profile_name: str, dbutils) -> dict:
    """Test a profile by calling ThoughtSpot ``whoami()``.

    Returns the parsed JSON user dict on success.
    """
    from ts_client import ThoughtSpotClient  # noqa: PLC0415

    client = ThoughtSpotClient(profile=profile_name, dbutils=dbutils)
    return client.whoami()


# COMMAND ----------

# DBTITLE 1,Pick an action
try:
    dbutils.widgets.dropdown(  # noqa: F821
        "action", "List", _ACTIONS, "Action",
    )
except NameError:
    pass

# COMMAND ----------

# DBTITLE 1,Setup — prepare widgets for the selected action
try:
    _action = dbutils.widgets.get("action")  # noqa: F821

    if _action == "Create":
        setup_widgets(dbutils)

    elif _action == "Update":
        dbutils.widgets.text("profile_name", "default", "Profile to Update")
        _pn = dbutils.widgets.get("profile_name")
        setup_update_widgets(_pn, dbutils)

    elif _action in ("Delete", "Test"):
        dbutils.widgets.text("profile_name", "default", "Profile Name")

    elif _action == "List":
        print("No setup needed — run the next cell.")

except NameError:
    pass

# COMMAND ----------

# DBTITLE 1,Execute
try:
    _action = dbutils.widgets.get("action")  # noqa: F821

    if _action == "Create":
        _scope = create_profile(dbutils)
        print(f"Created profile in scope: {_scope}")

    elif _action == "List":
        _profiles = list_profiles(dbutils)
        if _profiles:
            print(f"  {'Name':20s}  {'Auth':14s}  {'URL':40s}  Username")
            print(f"  {'─' * 20}  {'─' * 14}  {'─' * 40}  {'─' * 30}")
            for _p in _profiles:
                print(f"  {_p['name']:20s}  {_p['auth_method']:14s}  {_p['base_url']:40s}  {_p['username']}")
        else:
            print("No ThoughtSpot profiles found. Select Create to add one.")

    elif _action == "Update":
        _scope = update_profile(dbutils)
        print(f"Updated profile in scope: {_scope}")

    elif _action == "Delete":
        _pn = dbutils.widgets.get("profile_name")
        _scope = delete_profile(_pn, dbutils)
        print(f"Deleted scope: {_scope}")
        dbutils.widgets.removeAll()

    elif _action == "Test":
        _pn = dbutils.widgets.get("profile_name")
        _result = test_profile(_pn, dbutils)
        print(_result)

except NameError:
    pass
