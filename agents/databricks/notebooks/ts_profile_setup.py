# Databricks notebook source
# DBTITLE 1,Install dependencies
# MAGIC %pip install -q requests ipywidgets

# COMMAND ----------

# DBTITLE 1,Load ThoughtSpotClient
# MAGIC %run ./ts_client

# COMMAND ----------

"""
ts_profile_setup.py — CRUD manager for ThoughtSpot profiles in Databricks Secrets.

Actions: Create, List, Update, Delete, Test.

Consumed interactively from a Databricks notebook (ipywidgets button UI),
or imported directly in tests (add ``agents/databricks/notebooks/`` to sys.path).

Design
------
- ipywidgets UI: button bar (List/Create/Update/Delete/Test) with dynamic
  forms — password masking, profile selector dropdown, rename support.
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

# DBTITLE 1,Profile Manager
try:
    import ipywidgets as _iw
    from IPython.display import display as _display, clear_output as _clear, HTML as _HTML

    # --- Output area ---
    _out = _iw.Output(layout=_iw.Layout(border="1px solid #ccc", padding="10px", min_height="120px"))

    # --- Profile selector (for Update/Delete/Test) ---
    _select = _iw.Dropdown(description="Select:", options=[], layout=_iw.Layout(width="420px"))

    # --- Form fields ---
    _w_name = _iw.Text(description="Profile:", placeholder="new-profile-name", layout=_iw.Layout(width="420px"))
    _w_url = _iw.Text(description="URL:", placeholder="https://myorg.thoughtspot.cloud", layout=_iw.Layout(width="420px"))
    _w_user = _iw.Text(description="Username:", layout=_iw.Layout(width="420px"))
    _w_auth = _iw.Dropdown(description="Auth:", options=["bearer_token", "password", "secret_key"], layout=_iw.Layout(width="420px"))
    _w_cred = _iw.Password(description="Credential:", layout=_iw.Layout(width="420px"))
    _w_new_name = _iw.Text(description="New Name:", placeholder="(leave blank to keep current name)", layout=_iw.Layout(width="420px"))

    _create_fields = _iw.VBox([_w_name, _w_url, _w_user, _w_auth, _w_cred])
    _update_fields = _iw.VBox([_select, _w_new_name, _w_url, _w_user, _w_auth, _w_cred])
    _form_area = _iw.VBox([])

    def _refresh_selector():
        names = [p["name"] for p in list_profiles(dbutils)]
        _select.options = names if names else ["(no profiles)"]

    def _load_selected(change=None):
        n = _select.value
        if not n or n == "(no profiles)":
            return
        scope = f"thoughtspot-{n}"
        try:
            _w_url.value = dbutils.secrets.get(scope, "base_url")
            _w_auth.value = dbutils.secrets.get(scope, "auth_method")
            _w_user.value = dbutils.secrets.get(scope, "username")
            _w_cred.value = ""
        except Exception:
            pass

    _select.observe(lambda c: _load_selected() if c["name"] == "value" else None)

    def _html_table(profiles):
        style = "border-collapse:collapse;width:100%"
        td = "border:1px solid #ddd;padding:6px 10px;text-align:left"
        html = f"<table style='{style}'><tr>"
        for h in ["Name", "Auth", "URL", "Username"]:
            html += f"<th style='{td};background:#f5f5f5;font-weight:600'>{h}</th>"
        html += "</tr>"
        for p in profiles:
            html += f"<tr><td style='{td}'>{p['name']}</td><td style='{td}'>{p['auth_method']}</td><td style='{td}'>{p['base_url']}</td><td style='{td}'>{p['username']}</td></tr>"
        return html + "</table>"

    # --- Action handlers ---
    def _on_list(_):
        _form_area.children = []
        with _out:
            _clear()
            ps = list_profiles(dbutils)
            if not ps:
                print("No profiles found.")
                return
            _display(_HTML(_html_table(ps)))

    def _on_show_create(_):
        _w_name.value = ""; _w_url.value = ""; _w_user.value = ""; _w_cred.value = ""
        _form_area.children = [_iw.HTML("<b>Create new profile:</b>"), _create_fields, _btn_save_create]
        with _out:
            _clear()
            print("Fill in the fields and click Save.")

    def _on_save_create(_):
        with _out:
            _clear()
            n = _w_name.value.strip()
            url = _w_url.value.strip().rstrip("/")
            usr = _w_user.value.strip()
            cred = _w_cred.value
            if not all([n, url, usr, cred]):
                print("All fields required.")
                return
            scope = f"thoughtspot-{n}"
            _create_scope(dbutils, scope)
            _put_secret(dbutils, scope, "base_url", url)
            _put_secret(dbutils, scope, "auth_method", _w_auth.value)
            _put_secret(dbutils, scope, "username", usr)
            _put_secret(dbutils, scope, _CREDENTIAL_KEY_MAP[_w_auth.value], cred)
            print(f"✓ Created '{n}'")
            _form_area.children = []

    def _on_show_update(_):
        _refresh_selector()
        if _select.options == ("(no profiles)",):
            with _out:
                _clear()
                print("No profiles to update.")
            return
        _w_new_name.value = ""
        _load_selected()
        _form_area.children = [_iw.HTML("<b>Select profile to update:</b>"), _update_fields, _btn_save_update]
        with _out:
            _clear()
            print("Select a profile, edit fields, then click Save.\nTo rename: fill in 'New Name'.")

    def _on_save_update(_):
        with _out:
            _clear()
            n = _select.value
            if not n or n == "(no profiles)":
                print("No profile selected.")
                return
            new_n = _w_new_name.value.strip()
            old_scope = f"thoughtspot-{n}"

            if new_n and new_n != n:
                new_scope = f"thoughtspot-{new_n}"
                _create_scope(dbutils, new_scope)
                _put_secret(dbutils, new_scope, "base_url", _w_url.value.strip().rstrip("/") or dbutils.secrets.get(old_scope, "base_url"))
                _put_secret(dbutils, new_scope, "auth_method", _w_auth.value)
                _put_secret(dbutils, new_scope, "username", _w_user.value.strip() or dbutils.secrets.get(old_scope, "username"))
                cred_key = _CREDENTIAL_KEY_MAP[_w_auth.value]
                if _w_cred.value:
                    _put_secret(dbutils, new_scope, cred_key, _w_cred.value)
                else:
                    _put_secret(dbutils, new_scope, cred_key, dbutils.secrets.get(old_scope, cred_key))
                _delete_scope(dbutils, old_scope)
                print(f"✓ Renamed '{n}' → '{new_n}' and updated.")
            else:
                if _w_url.value.strip():
                    _put_secret(dbutils, old_scope, "base_url", _w_url.value.strip().rstrip("/"))
                if _w_user.value.strip():
                    _put_secret(dbutils, old_scope, "username", _w_user.value.strip())
                _put_secret(dbutils, old_scope, "auth_method", _w_auth.value)
                if _w_cred.value:
                    _put_secret(dbutils, old_scope, _CREDENTIAL_KEY_MAP[_w_auth.value], _w_cred.value)
                print(f"✓ Updated '{n}'")
            _form_area.children = []

    def _on_show_delete(_):
        _refresh_selector()
        if _select.options == ("(no profiles)",):
            with _out:
                _clear()
                print("No profiles to delete.")
            return
        _form_area.children = [_iw.HTML("<b>Select profile to delete:</b>"), _select, _btn_confirm_delete]
        with _out:
            _clear()
            ps = list_profiles(dbutils)
            _display(_HTML(_html_table(ps)))
            print("\nSelect a profile above and click Confirm Delete.")

    def _on_confirm_delete(_):
        with _out:
            _clear()
            n = _select.value
            if not n or n == "(no profiles)":
                print("No profile selected.")
                return
            delete_profile(n, dbutils)
            print(f"✓ Deleted '{n}'")
            _form_area.children = []

    def _on_show_test(_):
        _refresh_selector()
        if _select.options == ("(no profiles)",):
            with _out:
                _clear()
                print("No profiles to test.")
            return
        _form_area.children = [_iw.HTML("<b>Select profile to test:</b>"), _select, _btn_run_test]
        with _out:
            _clear()

    def _on_run_test(_):
        with _out:
            _clear()
            n = _select.value
            if not n or n == "(no profiles)":
                print("No profile selected.")
                return
            print(f"Testing '{n}'...")
            try:
                r = test_profile(n, dbutils)
                print(f"✓ Connected as {r.get('display_name', r.get('name', '?'))}")
            except Exception as e:
                print(f"✗ Failed: {e}")

    # --- Buttons ---
    _btn_save_create = _iw.Button(description="Save", button_style="success", icon="check")
    _btn_save_create.on_click(_on_save_create)
    _btn_save_update = _iw.Button(description="Save", button_style="success", icon="check")
    _btn_save_update.on_click(_on_save_update)
    _btn_confirm_delete = _iw.Button(description="Confirm Delete", button_style="danger", icon="trash")
    _btn_confirm_delete.on_click(_on_confirm_delete)
    _btn_run_test = _iw.Button(description="Run Test", button_style="info", icon="plug")
    _btn_run_test.on_click(_on_run_test)

    _btn_list = _iw.Button(description="List", button_style="info", icon="list")
    _btn_create = _iw.Button(description="Create", button_style="success", icon="plus")
    _btn_update = _iw.Button(description="Update", button_style="warning", icon="pencil")
    _btn_delete = _iw.Button(description="Delete", button_style="danger", icon="trash")
    _btn_test = _iw.Button(description="Test", button_style="", icon="plug")

    _btn_list.on_click(_on_list)
    _btn_create.on_click(_on_show_create)
    _btn_update.on_click(_on_show_update)
    _btn_delete.on_click(_on_show_delete)
    _btn_test.on_click(_on_show_test)

    _display(_iw.VBox([
        _iw.HTML("<h3>ThoughtSpot Profile Manager</h3>"),
        _iw.HBox([_btn_list, _btn_create, _btn_update, _btn_delete, _btn_test]),
        _form_area,
        _out,
    ]))

except (NameError, ImportError):
    pass
