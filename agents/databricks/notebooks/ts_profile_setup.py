# Databricks notebook source
# DBTITLE 1,Load ThoughtSpotClient
# MAGIC %run ./ts_client

# COMMAND ----------

# DBTITLE 1,Interactive Profile Manager (ipywidgets)
import ipywidgets as widgets
from IPython.display import display, clear_output
import requests as _requests

# ---------------------------------------------------------------------------
# Secrets helpers
# ---------------------------------------------------------------------------
_CRED_KEYS = {"bearer_token": "token", "password": "password", "secret_key": "secret_key"}

def _auth():
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    return ctx.apiUrl().get().rstrip("/"), {"Authorization": f"Bearer {ctx.apiToken().get()}"}

def _put(scope, key, val):
    h, hdr = _auth()
    _requests.post(f"{h}/api/2.0/secrets/put", json={"scope": scope, "key": key, "string_value": val}, headers=hdr, timeout=30).raise_for_status()

def _mk_scope(scope):
    h, hdr = _auth()
    r = _requests.post(f"{h}/api/2.0/secrets/scopes/create", json={"scope": scope}, headers=hdr, timeout=30)
    if r.status_code != 409: r.raise_for_status()

def _rm_scope(scope):
    h, hdr = _auth()
    r = _requests.post(f"{h}/api/2.0/secrets/scopes/delete", json={"scope": scope}, headers=hdr, timeout=30)
    if r.status_code != 404: r.raise_for_status()

def _profiles():
    out = []
    for s in dbutils.secrets.listScopes():
        name = s.name if hasattr(s, "name") else s
        if not name.startswith("thoughtspot-"): continue
        try:
            out.append({"name": name[12:], "url": dbutils.secrets.get(name, "base_url"), "auth": dbutils.secrets.get(name, "auth_method"), "user": dbutils.secrets.get(name, "username")})
        except Exception:
            out.append({"name": name[12:], "url": "?", "auth": "?", "user": "?"})
    return out

def _profile_names():
    return [p["name"] for p in _profiles()]

# ---------------------------------------------------------------------------
# UI widgets
# ---------------------------------------------------------------------------
_out = widgets.Output(layout=widgets.Layout(border="1px solid #ccc", padding="10px", min_height="120px"))

# Profile selector dropdown (for Update/Delete/Test)
_select = widgets.Dropdown(description="Select:", options=[], layout=widgets.Layout(width="420px"))

# Form fields (for Create/Update)
_name = widgets.Text(description="Profile:", placeholder="new-profile-name", layout=widgets.Layout(width="420px"))
_url = widgets.Text(description="URL:", placeholder="https://myorg.thoughtspot.cloud", layout=widgets.Layout(width="420px"))
_user = widgets.Text(description="Username:", layout=widgets.Layout(width="420px"))
_auth_w = widgets.Dropdown(description="Auth:", options=["bearer_token", "password", "secret_key"], layout=widgets.Layout(width="420px"))
_cred = widgets.Password(description="Credential:", layout=widgets.Layout(width="420px"))

# Rename field (for Update)
_new_name = widgets.Text(description="New Name:", placeholder="(leave blank to keep current name)", layout=widgets.Layout(width="420px"))

# Group widgets
_create_fields = widgets.VBox([_name, _url, _user, _auth_w, _cred])
_select_fields = widgets.VBox([_select, _new_name, _url, _user, _auth_w, _cred])
_form_area = widgets.VBox([])

def _refresh_selector():
    """Refresh the profile dropdown with current profiles."""
    names = _profile_names()
    _select.options = names if names else ["(no profiles)"]

def _load_selected_profile(change=None):
    """Load selected profile data into form fields."""
    n = _select.value
    if not n or n == "(no profiles)": return
    scope = f"thoughtspot-{n}"
    try:
        _url.value = dbutils.secrets.get(scope, "base_url")
        _auth_w.value = dbutils.secrets.get(scope, "auth_method")
        _user.value = dbutils.secrets.get(scope, "username")
        _cred.value = ""
    except Exception:
        pass

_select.observe(lambda c: _load_selected_profile() if c["name"] == "value" else None)

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _on_list(_):
    _form_area.children = []
    with _out:
        clear_output()
        ps = _profiles()
        if not ps: print("No profiles found."); return
        from IPython.display import HTML as _HTML
        style = "border-collapse:collapse;width:100%"
        td = "border:1px solid #ddd;padding:6px 10px;text-align:left"
        html = f"<table style='{style}'><tr>" + "".join(f"<th style='{td};background:#f5f5f5;font-weight:600'>{h}</th>" for h in ['Name','Auth','URL','Username']) + "</tr>"
        for p in ps:
            html += f"<tr><td style='{td}'>{p['name']}</td><td style='{td}'>{p['auth']}</td><td style='{td}'>{p['url']}</td><td style='{td}'>{p['user']}</td></tr>"
        html += "</table>"
        display(_HTML(html))

def _on_show_create(_):
    """Show the create form."""
    _name.value = ""; _url.value = ""; _user.value = ""; _cred.value = ""
    _form_area.children = [widgets.HTML("<b>Create new profile:</b>"), _create_fields, _btn_save_create]
    with _out:
        clear_output()
        print("Fill in the fields and click Save.")

def _on_save_create(_):
    with _out:
        clear_output()
        n, u, usr, a, c = _name.value.strip(), _url.value.strip(), _user.value.strip(), _auth_w.value, _cred.value
        if not all([n, u, usr, c]): print("All fields required."); return
        scope = f"thoughtspot-{n}"
        _mk_scope(scope)
        _put(scope, "base_url", u.rstrip("/")); _put(scope, "auth_method", a)
        _put(scope, "username", usr); _put(scope, _CRED_KEYS[a], c)
        print(f"✓ Created '{n}'")
        _form_area.children = []

def _on_show_update(_):
    """Show the update form with profile selector."""
    _refresh_selector()
    if _select.options == ["(no profiles)"]:
        with _out: clear_output(); print("No profiles to update.")
        return
    _new_name.value = ""
    _load_selected_profile()
    _form_area.children = [widgets.HTML("<b>Select profile to update:</b>"), _select_fields, _btn_save_update]
    with _out:
        clear_output()
        print("Select a profile, edit fields, then click Save.\nTo rename: fill in 'New Name'.")

def _on_save_update(_):
    with _out:
        clear_output()
        n = _select.value
        if not n or n == "(no profiles)": print("No profile selected."); return
        new_n = _new_name.value.strip()
        old_scope = f"thoughtspot-{n}"

        if new_n and new_n != n:
            # Rename: create new scope, copy values, delete old
            new_scope = f"thoughtspot-{new_n}"
            _mk_scope(new_scope)
            _put(new_scope, "base_url", (_url.value.strip().rstrip("/") or dbutils.secrets.get(old_scope, "base_url")))
            _put(new_scope, "auth_method", _auth_w.value)
            _put(new_scope, "username", (_user.value.strip() or dbutils.secrets.get(old_scope, "username")))
            cred_key = _CRED_KEYS[_auth_w.value]
            if _cred.value:
                _put(new_scope, cred_key, _cred.value)
            else:
                _put(new_scope, cred_key, dbutils.secrets.get(old_scope, cred_key))
            _rm_scope(old_scope)
            print(f"✓ Renamed '{n}' → '{new_n}' and updated.")
        else:
            # Update in place
            if _url.value.strip(): _put(old_scope, "base_url", _url.value.strip().rstrip("/"))
            if _user.value.strip(): _put(old_scope, "username", _user.value.strip())
            _put(old_scope, "auth_method", _auth_w.value)
            if _cred.value: _put(old_scope, _CRED_KEYS[_auth_w.value], _cred.value)
            print(f"✓ Updated '{n}'")
        _form_area.children = []

def _on_show_delete(_):
    """Show delete confirmation with profile selector."""
    _refresh_selector()
    if _select.options == ["(no profiles)"]:
        with _out: clear_output(); print("No profiles to delete.")
        return
    _form_area.children = [widgets.HTML("<b>Select profile to delete:</b>"), _select, _btn_confirm_delete]
    with _out:
        clear_output()
        ps = _profiles()
        from IPython.display import HTML as _HTML
        style = "border-collapse:collapse;width:100%"
        td = "border:1px solid #ddd;padding:6px 10px;text-align:left"
        html = f"<table style='{style}'><tr>" + "".join(f"<th style='{td};background:#f5f5f5;font-weight:600'>{h}</th>" for h in ['Name','Auth','URL','Username']) + "</tr>"
        for p in ps:
            html += f"<tr><td style='{td}'>{p['name']}</td><td style='{td}'>{p['auth']}</td><td style='{td}'>{p['url']}</td><td style='{td}'>{p['user']}</td></tr>"
        html += "</table>"
        display(_HTML(html))
        print("\nSelect a profile above and click Confirm Delete.")

def _on_confirm_delete(_):
    with _out:
        clear_output()
        n = _select.value
        if not n or n == "(no profiles)": print("No profile selected."); return
        _rm_scope(f"thoughtspot-{n}")
        print(f"✓ Deleted '{n}'")
        _form_area.children = []

def _on_show_test(_):
    """Show test with profile selector."""
    _refresh_selector()
    if _select.options == ["(no profiles)"]:
        with _out: clear_output(); print("No profiles to test.")
        return
    _form_area.children = [widgets.HTML("<b>Select profile to test:</b>"), _select, _btn_run_test]
    with _out:
        clear_output()

def _on_run_test(_):
    with _out:
        clear_output()
        n = _select.value
        if not n or n == "(no profiles)": print("No profile selected."); return
        print(f"Testing '{n}'...")
        try:
            r = ThoughtSpotClient(profile=n, dbutils=dbutils).whoami()
            print(f"✓ Connected as {r.get('display_name', r.get('name', '?'))}")
        except Exception as e:
            print(f"✗ Failed: {e}")

# ---------------------------------------------------------------------------
# Secondary action buttons (shown in form area)
# ---------------------------------------------------------------------------
_btn_save_create = widgets.Button(description="Save", button_style="success", icon="check")
_btn_save_create.on_click(_on_save_create)

_btn_save_update = widgets.Button(description="Save", button_style="success", icon="check")
_btn_save_update.on_click(_on_save_update)

_btn_confirm_delete = widgets.Button(description="Confirm Delete", button_style="danger", icon="trash")
_btn_confirm_delete.on_click(_on_confirm_delete)

_btn_run_test = widgets.Button(description="Run Test", button_style="info", icon="plug")
_btn_run_test.on_click(_on_run_test)

# ---------------------------------------------------------------------------
# Main action buttons
# ---------------------------------------------------------------------------
_btn_list = widgets.Button(description="List", button_style="info", icon="list")
_btn_create = widgets.Button(description="Create", button_style="success", icon="plus")
_btn_update = widgets.Button(description="Update", button_style="warning", icon="pencil")
_btn_delete = widgets.Button(description="Delete", button_style="danger", icon="trash")
_btn_test = widgets.Button(description="Test", button_style="", icon="plug")

_btn_list.on_click(_on_list)
_btn_create.on_click(_on_show_create)
_btn_update.on_click(_on_show_update)
_btn_delete.on_click(_on_show_delete)
_btn_test.on_click(_on_show_test)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
display(widgets.VBox([
    widgets.HTML("<h3>\U0001f511 ThoughtSpot Profile Manager</h3>"),
    widgets.HBox([_btn_list, _btn_create, _btn_update, _btn_delete, _btn_test]),
    _form_area,
    _out,
]))
