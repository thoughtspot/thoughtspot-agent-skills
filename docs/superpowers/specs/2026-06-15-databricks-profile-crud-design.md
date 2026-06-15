# Databricks Profile CRUD — Design Spec

## Goal

Replace the current multi-cell, manually-sequenced `ts_profile_setup.py` notebook
with a single action-driven notebook that fully supports Create, Read (list/show),
Update, and Delete of ThoughtSpot profiles stored in Databricks Secrets.

## Problem statement

The current notebook requires the user to know which cells to run in which order
and edit hardcoded profile names inside cells. Genie's live workaround exposed
two additional gaps:

1. **Sibling notebook imports don't work** — `from ts_client import ThoughtSpotClient`
   fails because Databricks notebooks aren't on `sys.path`. Genie solved this with
   a dynamic Workspace API loader (`exec(compile(...))`), which works but is fragile
   (hardcoded path, security surface of `exec` on remote source).
2. **No list or delete** — the user can create and test but not see what exists or
   remove stale profiles.

## Architecture

### Single notebook, widget-driven action selection

```
Cell 0: %pip install -q requests
Cell 1: Function definitions (all CRUD + helpers)
Cell 2: Action picker — dropdown widget: Create | List | Update | Delete | Test
Cell 3: Execute — reads the action widget, runs the corresponding function
```

The user runs Cell 0 once per cluster attach, then uses Cells 2–3 in a loop:
pick an action, fill in params, run Cell 3.

### Why a single notebook

- Users bookmark one path, not five
- Action dropdown is the standard Databricks pattern for multi-mode notebooks
- All functions share the REST API helpers (no duplication across notebooks)

### ts_client dependency

Two options for resolving the sibling import:

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| A. `%run ./ts_client` in its own cell | Databricks native notebook include | Simple, standard, no exec() | Pollutes the notebook namespace; must run before test action |
| B. Dynamic loader via Workspace API | Download + compile at call time | No manual cell ordering | `exec()` security surface; hardcoded path; fragile |

**Recommendation: Option A.** `%run` is the standard Databricks pattern for notebook
dependencies. It's one cell the user runs once, and it makes `ThoughtSpotClient`
available in the notebook scope. The test function can then reference it directly
instead of doing a deferred import.

Cell layout becomes:

```
Cell 0: %pip install -q requests
Cell 1: %run ./ts_client
Cell 2: Function definitions
Cell 3: Action dropdown widget
Cell 4: Execute action
```

### CRUD operations

#### Create

Same as today: widget-driven, stores to Databricks Secrets via REST API.
`_create_scope` (idempotent) + `_put_secret` for each key.

Widgets: `profile_name`, `base_url`, `auth_method` (dropdown), `username`, `credential`.

After store: `removeAll()` clears widgets immediately.

#### Read (List)

Scan `dbutils.secrets.listScopes()` for `thoughtspot-*` scopes. For each,
read `base_url`, `auth_method`, `username` (never credential values).

Display as a formatted table. No widgets needed — just run the cell.

#### Update

Identical to Create — `_create_scope` is idempotent and `_put_secret` overwrites.
The user picks "Update" from the dropdown, the same widgets appear, they enter the
existing profile name and new values.

To make this smoother: when the action is Update, pre-populate the `base_url`,
`username`, and `auth_method` widgets with the current values from Secrets. The
user only changes what they need to. The credential widget is always blank (we
never read credentials back).

Implementation: a `setup_update_widgets(profile_name, dbutils)` function that
reads the existing scope and calls `dbutils.widgets.text(name, existing_value, label)`.

#### Delete

Widget: `profile_name` (text input).

Calls `_delete_scope(dbutils, scope)` via the REST API endpoint
`/api/2.0/secrets/scopes/delete`. Idempotent (404 = already gone).

Display confirmation message after deletion.

#### Test

Widget: `profile_name` (text input, default "default").

Calls `ThoughtSpotClient(profile=name, dbutils=dbutils).whoami()`.
Prints the user info dict on success, error message on failure.

Requires `ts_client` to be loaded (via `%run ./ts_client` in Cell 1).

### Widget lifecycle

| Action | Widgets shown | Cleared after |
|---|---|---|
| Create | profile_name, base_url, auth_method, username, credential | Yes — removeAll() |
| List | none | N/A |
| Update | profile_name, base_url, auth_method, username, credential (pre-filled) | Yes — removeAll() |
| Delete | profile_name | Yes — removeAll() |
| Test | profile_name | No — non-sensitive |

### REST API helpers (unchanged)

```python
_workspace_auth(dbutils) -> (host, headers)
_create_scope(dbutils, scope)      # POST /api/2.0/secrets/scopes/create (409 = exists)
_put_secret(dbutils, scope, k, v)  # POST /api/2.0/secrets/put
_delete_scope(dbutils, scope)      # POST /api/2.0/secrets/scopes/delete (404 = gone)
```

### Execute cell logic

```python
action = dbutils.widgets.get("action")

if action == "Create":
    setup_widgets(dbutils)
    # User fills widgets, re-runs this cell
    scope = create_profile(dbutils)
    print(f"Created profile in scope: {scope}")

elif action == "List":
    profiles = list_profiles(dbutils)
    for p in profiles:
        print(f"  {p['name']:20s}  {p['auth_method']:14s}  {p['base_url']}")

elif action == "Update":
    profile_name = dbutils.widgets.get("profile_name")
    setup_update_widgets(profile_name, dbutils)
    # User modifies widgets, re-runs this cell
    scope = create_profile(dbutils)
    print(f"Updated profile in scope: {scope}")

elif action == "Delete":
    profile_name = dbutils.widgets.get("profile_name")
    scope = delete_profile(profile_name, dbutils)
    print(f"Deleted scope: {scope}")

elif action == "Test":
    profile_name = dbutils.widgets.get("profile_name")
    result = test_profile(profile_name, dbutils)
    print(result)
```

**Problem with this approach:** Create and Update need a two-step flow — show
widgets first, then store after the user fills them. A single "Execute" cell
can't do both in one run.

**Solution — two-phase execution cells:**

```
Cell 3: Action dropdown (Create | List | Update | Delete | Test)
Cell 4: Setup — shows the right widgets for the selected action
Cell 5: Execute — performs the action using widget values
```

- **List** skips Cell 4 (no widgets needed) — runs directly in Cell 5
- **Create/Update** require: run Cell 4 (widgets appear) → fill in → run Cell 5
- **Delete/Test** require: Cell 4 shows just profile_name → run Cell 5
- Cell 5 always calls `removeAll()` for Create/Update/Delete

### Security

- Credential widget is cleared immediately after store (same as today)
- `list_profiles` never reads credential keys — only metadata
- `%run ./ts_client` is safer than `exec(compile(...))` — no remote code eval
- Do not save the notebook between Cell 4 and Cell 5 (same warning as today)

### Test strategy

All existing tests continue to work. New tests needed:

| Function | Tests |
|---|---|
| `list_profiles` | empty, single, multiple, ignores non-TS scopes, handles incomplete scope |
| `delete_profile` | deletes existing, no-op on nonexistent, doesn't affect other profiles |
| `setup_update_widgets` | pre-populates from existing scope, credential widget stays blank |

These are pure-function tests against MockSecrets/MockWidgets — no live Databricks needed.

### Changes to existing files

| File | Change |
|---|---|
| `notebooks/ts_profile_setup.py` | Add `%pip` cell, `%run ./ts_client` cell, action dropdown, `list_profiles`, `delete_profile`, `setup_update_widgets`, restructure execution cells |
| `tests/conftest.py` | Already has `deleteScope` on MockSecrets |
| `tests/test_profile_setup.py` | Already has list/delete tests; add `setup_update_widgets` tests |
| `SETUP.md` | Update Step 3 cell numbers and action descriptions |

### What this does NOT change

- `ts_client.py` — no changes
- `token_refresh.py` — no changes
- `databricks.yml` — no changes
- The REST API helpers — same `_workspace_auth`, `_create_scope`, `_put_secret`, `_delete_scope`
