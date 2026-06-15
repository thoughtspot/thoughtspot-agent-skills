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

# ---------------------------------------------------------------------------
# Credential key map
# ---------------------------------------------------------------------------

_CREDENTIAL_KEY_MAP: dict[str, str] = {
    "bearer_token": "token",
    "password": "password",
    "secret_key": "secret_key",
}


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

    # Create scope — ignore error if it already exists.
    try:
        dbutils.secrets.createScope(scope)
    except Exception:
        pass

    # Store non-sensitive metadata.
    dbutils.secrets.put(scope, "base_url", base_url)
    dbutils.secrets.put(scope, "auth_method", auth_method)
    dbutils.secrets.put(scope, "username", username)

    # Store credential under the method-specific key.
    credential_key = _CREDENTIAL_KEY_MAP[auth_method]
    dbutils.secrets.put(scope, credential_key, credential)

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
