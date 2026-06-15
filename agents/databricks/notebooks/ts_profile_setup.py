# Databricks notebook source
"""
ts_profile_setup.py — Profile setup wizard for ThoughtSpot in Databricks notebooks.

Consumed via ``%run ./ts_profile_setup`` in Databricks notebooks, or imported
directly in tests (add ``agents/databricks/notebooks/`` to sys.path first).

Design
------
- Widget-driven: uses ``dbutils.widgets`` to collect inputs interactively.
- Secrets-backed: stores credentials in Databricks Secrets under a scope
  named ``thoughtspot-{profile_name}``.
- Testable: all logic lives in plain functions — no notebook-level side effects
  at import time.
"""

from __future__ import annotations

import os as _os
import sys as _sys

_nb_dir = _os.getcwd()
if _nb_dir not in _sys.path:
    _sys.path.insert(0, _nb_dir)

import requests as _requests

# ---------------------------------------------------------------------------
# Credential key map
# ---------------------------------------------------------------------------

_CREDENTIAL_KEY_MAP: dict[str, str] = {
    "bearer_token": "token",
    "password": "password",
    "secret_key": "secret_key",
}


# ---------------------------------------------------------------------------
# Secrets write helpers — dbutils.secrets is read-only in Databricks;
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
        return  # scope already exists
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
        return  # scope doesn't exist — nothing to delete
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Widget setup
# ---------------------------------------------------------------------------

def setup_widgets(dbutils) -> None:
    """Register input widgets for the profile setup notebook.

    Creates the following widgets (all text unless noted):
    - ``profile_name``  — profile slug used to name the Secrets scope (default "default")
    - ``base_url``      — root URL of the ThoughtSpot instance
    - ``username``      — ThoughtSpot username / e-mail
    - ``credential``    — token, password, or secret key value
    - ``auth_method``   — dropdown: bearer_token | password | secret_key

    Parameters
    ----------
    dbutils:
        The Databricks ``dbutils`` object (real or mock).
    """
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


# ---------------------------------------------------------------------------
# Profile creation
# ---------------------------------------------------------------------------

def create_profile(dbutils) -> str:
    """Read widget values and store them as Databricks Secrets.

    Reads the following widgets (register them first with :func:`setup_widgets`
    or set them via ``dbutils.widgets._set`` in tests):

    - ``profile_name``
    - ``base_url``  (trailing ``/`` stripped)
    - ``auth_method``
    - ``username``
    - ``credential``

    Creates the scope ``thoughtspot-{profile_name}`` if it does not already
    exist, then stores:

    ===============  =======================================================
    Secret key       Value
    ===============  =======================================================
    ``base_url``     Stripped base URL
    ``auth_method``  The selected auth method
    ``username``     The username
    ``token``        credential (when auth_method == "bearer_token")
    ``password``     credential (when auth_method == "password")
    ``secret_key``   credential (when auth_method == "secret_key")
    ===============  =======================================================

    Clears all widgets after successful storage.

    Parameters
    ----------
    dbutils:
        The Databricks ``dbutils`` object (real or mock).

    Returns
    -------
    str
        The name of the Secrets scope created / used.
    """
    profile_name = dbutils.widgets.get("profile_name")
    base_url = dbutils.widgets.get("base_url").rstrip("/")
    auth_method = dbutils.widgets.get("auth_method")
    username = dbutils.widgets.get("username")
    credential = dbutils.widgets.get("credential")

    scope = f"thoughtspot-{profile_name}"

    # Create scope via REST API (idempotent).
    _create_scope(dbutils, scope)

    # Store non-sensitive metadata via REST API.
    _put_secret(dbutils, scope, "base_url", base_url)
    _put_secret(dbutils, scope, "auth_method", auth_method)
    _put_secret(dbutils, scope, "username", username)

    # Store credential under the method-specific key.
    credential_key = _CREDENTIAL_KEY_MAP[auth_method]
    _put_secret(dbutils, scope, credential_key, credential)

    # Clear widgets so sensitive values are no longer displayed.
    dbutils.widgets.removeAll()

    return scope


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

def test_profile(profile_name: str, dbutils) -> dict:
    """Test a stored ThoughtSpot profile by calling ``whoami()``.

    Imports :class:`ThoughtSpotClient` from the sibling ``ts_client`` notebook,
    instantiates it for the given profile, and calls ``whoami()``.

    Parameters
    ----------
    profile_name:
        The profile name (not the scope name) to test.
    dbutils:
        The Databricks ``dbutils`` object (real or mock).

    Returns
    -------
    dict
        The parsed JSON response from ``GET /api/rest/2.0/auth/session/user``.
    """
    from ts_client import ThoughtSpotClient  # noqa: PLC0415 — sibling notebook import

    client = ThoughtSpotClient(profile=profile_name, dbutils=dbutils)
    return client.whoami()


# ---------------------------------------------------------------------------
# List profiles
# ---------------------------------------------------------------------------

def list_profiles(dbutils) -> list[dict]:
    """List all ThoughtSpot profiles stored in Databricks Secrets.

    Scans all scopes starting with ``thoughtspot-`` and returns metadata
    for each (profile name, base URL, auth method, username). Credential
    values are never included.

    Parameters
    ----------
    dbutils:
        The Databricks ``dbutils`` object (real or mock).

    Returns
    -------
    list[dict]
        Each dict contains: ``name``, ``scope``, ``base_url``,
        ``auth_method``, ``username``.
    """
    profiles = []
    for scope in dbutils.secrets.listScopes():
        if not scope.startswith("thoughtspot-"):
            continue
        name = scope[len("thoughtspot-"):]
        try:
            base_url = dbutils.secrets.get(scope, "base_url")
            auth_method = dbutils.secrets.get(scope, "auth_method")
            username = dbutils.secrets.get(scope, "username")
        except KeyError:
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
# Delete profile
# ---------------------------------------------------------------------------

def delete_profile(profile_name: str, dbutils) -> str:
    """Delete a ThoughtSpot profile from Databricks Secrets.

    Removes the entire scope ``thoughtspot-{profile_name}`` and all secrets
    within it. Idempotent — does not raise if the scope doesn't exist.

    Parameters
    ----------
    profile_name:
        The profile name (not the scope name).
    dbutils:
        The Databricks ``dbutils`` object (real or mock).

    Returns
    -------
    str
        The scope name that was deleted.
    """
    scope = f"thoughtspot-{profile_name}"
    _delete_scope(dbutils, scope)
    return scope


# COMMAND ----------

# Cell 1: List all ThoughtSpot profiles.
try:
    profiles = list_profiles(dbutils)  # noqa: F821
    if profiles:
        for p in profiles:
            print(f"  {p['name']:20s}  {p['auth_method']:14s}  {p['base_url']}  ({p['username']})")
    else:
        print("No ThoughtSpot profiles found. Run Cell 2 to create one.")
except NameError:
    pass

# COMMAND ----------

# Cell 2: Display input widgets for creating or updating a profile.
# After running this cell, fill in the widget values at the top of the notebook
# BEFORE running Cell 3.
try:
    setup_widgets(dbutils)  # noqa: F821 — injected by Databricks
except NameError:
    pass

# COMMAND ----------

# Cell 3: Store the profile in Databricks Secrets and clear widgets.
# To update an existing profile, enter the same profile name — values are overwritten.
# The credential is moved to Secrets immediately and the widgets are removed
# so the value is no longer visible in the notebook UI.
# WARNING: Do not save the notebook between Cell 2 and Cell 3 — widget values
# would persist in the saved notebook state.
try:
    scope = create_profile(dbutils)  # noqa: F821
    print(f"Profile stored in Secrets scope: {scope}")
except NameError:
    pass

# COMMAND ----------

# Cell 4: Test the connection by calling ThoughtSpot whoami().
# Edit the profile name below if you used something other than "default".
try:
    result = test_profile("default", dbutils)  # noqa: F821
    print(result)
except NameError:
    pass

# COMMAND ----------

# Cell 5: Delete a profile.
# Change the profile name below, then run this cell.
# WARNING: This permanently removes the scope and all its secrets.
try:
    # deleted_scope = delete_profile("profile-to-delete", dbutils)  # noqa: F821
    # print(f"Deleted scope: {deleted_scope}")
    print("Uncomment the lines above and set the profile name to delete.")
except NameError:
    pass
