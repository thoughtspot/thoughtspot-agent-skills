---
name: ts-profile-databricks
description: Set up and manage Databricks connection profiles. Use when configuring a new Databricks workspace, updating credentials, or testing whether an existing profile is working. Supports Service Principal (OAuth M2M) and Personal Access Token auth. Credentials are stored securely in the OS keychain.
---

# Databricks Profile Setup

Manage Databricks connection profiles stored in `~/.claude/databricks-profiles.json`.

Ask one question at a time. Wait for each answer before moving on.

---

## Prerequisites

Before running this skill, complete these steps in your Databricks environment.

### 1. Install the Databricks CLI

| Platform | Command |
|---|---|
| macOS (Homebrew) | `brew tap databricks/tap && brew install databricks` |
| pip (any platform) | `pip install databricks-cli` |
| Windows (winget) | `winget install Databricks.DatabricksCLI` |
| Manual install | https://docs.databricks.com/en/dev-tools/cli/install.html |

Verify: `databricks --version`

### 2. Know your workspace URL

Your workspace URL looks like `https://dbc-abc123.cloud.databricks.com` (AWS) or
`https://adb-1234567890.1.azuredatabricks.net` (Azure). Find it by logging into
your workspace and copying the URL from the browser address bar.

**Important:** This skill needs a **workspace-level** URL, not the account-level
`https://accounts.cloud.databricks.com`. Account-level profiles are for
administration only — they cannot access catalogs, run SQL, or list warehouses.

### 3. Prepare your auth credentials

Choose one of the following. If unsure, start with **Service Principal** for
automation or **PAT** for personal use.

#### Option A — Service Principal (recommended for automation)

A Service Principal is a machine identity that doesn't expire when someone leaves.
Create one before running this skill:

1. **Create the Service Principal:**
   Account Console → Settings → Service principals → Add service principal
   https://docs.databricks.com/en/admin/users-groups/service-principals.html

2. **Generate an OAuth secret:**
   Service principal → Settings → Generate secret
   Copy the **client ID** and **secret** — you'll need both.
   https://docs.databricks.com/en/dev-tools/authentication-oauth.html

3. **Add the SP to your workspace:**
   Account Console → Workspaces → {your workspace} → Permissions → Add service principal
   https://docs.databricks.com/en/admin/users-groups/service-principals.html#assign-a-service-principal-to-a-workspace

4. **Grant catalog and warehouse access** (run in a SQL editor as admin):
   ```sql
   GRANT USE CATALOG ON CATALOG {catalog_name} TO `{service_principal_application_id}`;
   GRANT USE SCHEMA ON SCHEMA {catalog_name}.{schema_name} TO `{service_principal_application_id}`;
   ```

#### Option B — Personal Access Token (PAT)

Good for personal use and quick setup. Tokens expire (default 90 days).

1. Open your Databricks workspace in a browser
2. Click your username (top-right) → Settings
3. Go to Developer → Access Tokens
4. Click Generate New Token — set a description and expiry
5. Copy the token value (you won't see it again)

https://docs.databricks.com/en/dev-tools/auth/pat.html

#### Option C — Existing Databricks CLI profile

If you've already configured a workspace-level profile via `databricks auth login`,
you can reuse it directly. Run `databricks auth profiles` to see your profiles.

**Account-level profiles** (host = `accounts.cloud.databricks.com`) won't work for
workspace operations. You'll need to create a workspace-level profile first:
```bash
databricks auth login --host https://your-workspace.cloud.databricks.com
```

### 4. Know your SQL Warehouse HTTP path (optional)

Required for skills that run SQL statements. Find it in your workspace:
Workspace → SQL Warehouses → {warehouse} → Connection Details → HTTP Path

Example: `/sql/1.0/warehouses/abc123def456`

---

## Step 0 — Overview

On skill invocation, display this introduction before reading the profiles file:

---
**ts-profile-databricks** — manage your Databricks connection profiles.

Profiles store your Databricks workspace URL, auth credentials, and default
catalog/schema/warehouse. Credentials are kept securely in your OS keychain
(macOS Keychain, Windows Credential Manager, or Linux Secret Service) — never in
the profile file or this conversation.

**Prerequisites:** Databricks CLI installed, workspace URL, and auth credentials
ready (Service Principal, PAT, or existing CLI profile). See the Prerequisites
section if you need to set these up first.

**Actions:**  L List   A Add   U Update   D Delete   T Test

*Reading profiles…*
---

Then proceed to [Entry Point](#entry-point).

---

## Entry Point

Read `~/.claude/databricks-profiles.json`.

**If no profiles file or empty profiles array:** go directly to [Add](#a--add).

**If profiles exist:** show the menu.

```
Databricks Profiles

  1. {name}  —  {auth_type_label}  —  {host}
  2. {name}  —  {auth_type_label}  —  {host}
  ...

  L  List profiles       (full details of all profiles)
  A  Add a new profile
  U  Update a profile
  D  Delete a profile
  T  Test a profile
  Q  Quit

Enter L / A / U / D / T / Q:
```

For `auth_type_label` display: `oauth-m2m` → `service principal`, `pat` → `personal access token`, `databricks-cli` → `CLI profile`.

---

## L — List

Show each profile with full details. For each profile:

**Service principal or PAT:**
```
Profile: {name}
  Host:      {host}
  Auth:      {auth_type_label}
  {if oauth-m2m: Client ID: {client_id}}
  Catalog:   {default_catalog}
  Schema:    {default_schema}
  Warehouse: {sql_warehouse_http_path}
  Env var:   {secret_env}
  Status:    {SET — credential loaded | NOT SET — run 'source ~/.zshenv' (macOS/Linux) or restart terminal (Windows), or re-add credential}
```

**CLI profile:**
```
Profile: {name}
  Host:       {host}
  Auth:       CLI profile ({dbx_cli_profile})
  Catalog:    {default_catalog}
  Schema:     {default_schema}
  Warehouse:  {sql_warehouse_http_path}
```

To check env var status: read `os.environ.get("{secret_env}", "")` — non-empty = SET.

After displaying all profiles, return to the menu.

---

## A — Add

### A1 — Check Databricks CLI

Run: `databricks --version 2>&1`

If not found:
```
Databricks CLI is not installed.

Install it from:
  macOS:   brew tap databricks/tap && brew install databricks
  pip:     pip install databricks-cli
  Other:   https://docs.databricks.com/en/dev-tools/cli/install.html

Once installed, run `databricks --version` to verify, then re-run /ts-profile-databricks.
```
Stop here.

### A2 — Choose Auth Method

```
Auth method:

  1  Service principal  — OAuth M2M; best for shared/automated use, doesn't expire with people (recommended)
  2  Personal access token (PAT)  — user-scoped token; quick to set up, expires (default 90 days)
  3  Existing CLI profile  — reuse a workspace-level profile already in ~/.databrickscfg

Enter 1, 2, or 3:
```

If the user is unsure: recommend **1 (Service Principal)** for team or production use,
**2 (PAT)** for personal exploration, **3** only if they've already run
`databricks auth login` for their workspace.

---

### Path A — Service Principal (OAuth M2M)

#### A-SP1 — Collect Workspace Details

Ask one at a time:

```
Databricks workspace URL (e.g. https://dbc-abc123.cloud.databricks.com):
```
Strip trailing slash. Store as `{host}`.

```
Service Principal client ID (Application ID from the SP settings):
```
Store as `{client_id}`.

```
Profile name: [Production]
```
Default to `Production`. Store as `{profile_name}`.

#### A-SP2 — Store Client Secret

Derive names from `{profile_name}`:
- `{slug}` — lowercase, non-alphanumeric → hyphens, collapse multiples, strip ends
  e.g. `"My Staging"` → `"my-staging"`
- `{keychain_service}` — `"databricks-{slug}"`
- `{SLUG}` — slug uppercased, hyphens → underscores  e.g. `"MY_STAGING"`
- `{secret_env}` — `DATABRICKS_SP_SECRET_{SLUG}`
- `{dbx_profile}` — `"ts-{slug}"` (the profile name in `~/.databrickscfg`)

First detect the platform:
```python
import platform
print(platform.system())  # Darwin = macOS, Windows, Linux
```

Ask the user to run this command **in their own terminal** (not here — credentials
must not enter the conversation or its history):

**macOS** (`Darwin`):
```
Run this in your terminal to store the client secret securely:

  security add-generic-password \
    -s "databricks-{slug}" \
    -a "{client_id}" \
    -w "YOUR_CLIENT_SECRET_HERE"

Replace YOUR_CLIENT_SECRET_HERE with the Service Principal's secret value, then let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell to store the client secret securely:

  python -c "import keyring; keyring.set_password('databricks-{slug}', '{client_id}', 'YOUR_CLIENT_SECRET_HERE')"

Replace YOUR_CLIENT_SECRET_HERE with the Service Principal's secret value, then let me know when done.
```

**Linux**:
```
Run this in your terminal to store the client secret securely:

  python3 -c "import keyring; keyring.set_password('databricks-{slug}', '{client_id}', 'YOUR_CLIENT_SECRET_HERE')"

Replace YOUR_CLIENT_SECRET_HERE with the Service Principal's secret value, then let me know when done.
```

After the user confirms, verify the entry was written:

**macOS:**
```python
import subprocess
r = subprocess.run(
    ["security", "find-generic-password", "-s", "databricks-{slug}", "-a", "{client_id}"],
    capture_output=True
)
print("Stored." if r.returncode == 0 else "Not found — check the command ran without errors.")
```

**Windows / Linux:**
```python
import keyring
stored = keyring.get_password("databricks-{slug}", "{client_id}")
print("Stored." if stored else "Not found — check the command ran without errors.")
```

Stop if verification fails — do not proceed without a confirmed credential write.

#### A-SP3 — Update Shell Profile

**macOS** (`Darwin`) — export line for `~/.zshenv`:
```
export {secret_env}=$(security find-generic-password -s "databricks-{slug}" -a "{client_id}" -w 2>/dev/null)
```
Read `~/.zshenv` (empty string if missing). If the line already exports `{secret_env}`, replace it. Otherwise append (preceded by a blank line if file is non-empty).

Tell the user:
```
~/.zshenv updated. Run this in your terminal:

  source ~/.zshenv

Let me know when done.
```
Wait for confirmation.

**Linux** — export line for `~/.zshenv` (or `~/.bashrc` if that is the user's shell profile):
```
export {secret_env}=$(python3 -c "import keyring; v=keyring.get_password('databricks-{slug}', '{client_id}'); print(v or '', end='')" 2>/dev/null)
```
Apply the same read/replace/append logic as macOS. Tell the user to run `source ~/.zshenv` and wait for confirmation.

**Windows** — set a permanent user environment variable via PowerShell:
```
Run this in PowerShell to persist the credential as an env var:

  $val = python -c "import keyring; v=keyring.get_password('databricks-{slug}', '{client_id}'); print(v or '', end='')"
  [System.Environment]::SetEnvironmentVariable('{secret_env}', $val, 'User')

Let me know when done, then restart your terminal for the change to take effect.
```

#### A-SP4 — Write Databricks CLI Config

Read the client secret from the env var (must be loaded after `source ~/.zshenv`):

```python
import os
secret = os.environ.get("{secret_env}", "")
if not secret:
    print("ERROR: {secret_env} is empty — run 'source ~/.zshenv' first.")
```

Write or update the `[{dbx_profile}]` section in `~/.databrickscfg`:

```ini
[{dbx_profile}]
host          = {host}
client_id     = {client_id}
client_secret = <value from env var>
auth_type     = oauth-m2m
```

Read `~/.databrickscfg` first. If a section named `[{dbx_profile}]` already exists, replace it. Otherwise append. Preserve all other sections.

After writing, set file permissions:

```python
import os
os.chmod(os.path.expanduser("~/.databrickscfg"), 0o600)
```

**Note:** `~/.databrickscfg` must contain `client_secret` in plaintext because the
Databricks CLI reads it from this file — it does not support shell expansion or
keychain lookups. The file is permission-restricted to 0600 (owner-only). The
keychain entry is the authoritative copy; the config file is a derived artifact
that this skill keeps in sync.

#### A-SP5 — Collect Workspace Defaults

```
Default catalog (e.g. main): [main]
```
Default to `main`. Store as `{default_catalog}`.

```
Default schema (e.g. default): [default]
```
Default to `default`. Store as `{default_schema}`.

```
SQL warehouse HTTP path (from Warehouse → Connection Details, e.g. /sql/1.0/warehouses/abc123):
```
Store as `{sql_warehouse_http_path}`. This is optional — if the user doesn't have one yet, store empty string.

If the user is unsure where to find this:
```
To find the HTTP path:
  1. Open your Databricks workspace in a browser
  2. Go to SQL Warehouses (in the left sidebar)
  3. Click on a warehouse
  4. Go to the Connection Details tab
  5. Copy the HTTP Path value

You can also skip this for now and add it later with U → Update.
```

---

### Path B — Personal Access Token (PAT)

#### A-PAT1 — Collect Workspace Details

Ask one at a time:

```
Databricks workspace URL (e.g. https://dbc-abc123.cloud.databricks.com):
```
Strip trailing slash. Store as `{host}`.

```
Profile name: [Production]
```
Default to `Production`. Store as `{profile_name}`.

#### A-PAT2 — Store Token

Derive names from `{profile_name}`:
- `{slug}` — lowercase, non-alphanumeric → hyphens, collapse multiples, strip ends
- `{keychain_service}` — `"databricks-{slug}"`
- `{SLUG}` — slug uppercased, hyphens → underscores
- `{secret_env}` — `DATABRICKS_TOKEN_{SLUG}`
- `{dbx_profile}` — `"ts-{slug}"`

```
To get your token:
  1. Open your Databricks workspace in a browser
  2. Click your username in the top-right → Settings
  3. Go to Developer → Access Tokens
  4. Click Generate New Token, set a description and expiry
  5. Copy the token value (you won't see it again)
```

Detect platform (`platform.system()`), then ask the user to store the token
**in their own terminal** (same pattern as Service Principal — replace
`"databricks-{slug}"` service name and use `"token"` as the account name):

**macOS** (`Darwin`):
```
Run this in your terminal to store the token securely:

  security add-generic-password \
    -s "databricks-{slug}" \
    -a "token" \
    -w "YOUR_TOKEN_HERE"

Replace YOUR_TOKEN_HERE with the token you copied, then let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell to store the token securely:

  python -c "import keyring; keyring.set_password('databricks-{slug}', 'token', 'YOUR_TOKEN_HERE')"

Replace YOUR_TOKEN_HERE with the token you copied, then let me know when done.
```

**Linux**:
```
Run this in your terminal to store the token securely:

  python3 -c "import keyring; keyring.set_password('databricks-{slug}', 'token', 'YOUR_TOKEN_HERE')"

Replace YOUR_TOKEN_HERE with the token you copied, then let me know when done.
```

Verify the entry was written (same pattern as Service Principal, account name = `"token"`).

Stop if verification fails.

#### A-PAT3 — Update Shell Profile

Same pattern as A-SP3, but using `{secret_env}` = `DATABRICKS_TOKEN_{SLUG}` and
account name `"token"` in the keychain lookup.

**macOS:**
```
export {secret_env}=$(security find-generic-password -s "databricks-{slug}" -a "token" -w 2>/dev/null)
```

**Linux:**
```
export {secret_env}=$(python3 -c "import keyring; v=keyring.get_password('databricks-{slug}', 'token'); print(v or '', end='')" 2>/dev/null)
```

Apply the same read/replace/append logic. Wait for `source ~/.zshenv` confirmation.

#### A-PAT4 — Write Databricks CLI Config

Read the token from the env var, then write or update `~/.databrickscfg`:

```ini
[{dbx_profile}]
host  = {host}
token = <value from env var>
```

Same read/replace/append logic as A-SP4. Set file permissions to 0600.

**Note:** Same plaintext trade-off as Service Principal — `~/.databrickscfg` must
contain the token value. The keychain entry is the authoritative copy.

#### A-PAT5 — Collect Workspace Defaults

Same as A-SP5 — collect default catalog, default schema, SQL warehouse HTTP path.

---

### Path C — Existing Databricks CLI Profile

#### A-CLI1 — List Available CLI Profiles

Run: `databricks auth profiles 2>&1`

Parse the profile names from the output and display them numbered:

```
Available Databricks CLI profiles:

  1  {profile_name_1}  —  {host_1}
  2  {profile_name_2}  —  {host_2}
  ...

Enter a number:
```

Store the selected profile name as `{dbx_cli_profile}`. Extract its host from the output as `{host}`.

#### A-CLI2 — Validate and Test CLI Profile

**Account-level check:** If the host is `accounts.cloud.databricks.com` (or contains
`accounts.`), warn the user:

```
⚠ This is an account-level profile — it can manage users and workspaces but
cannot access catalogs, run SQL, or list warehouses.

You need a workspace-level profile instead. Create one with:

  databricks auth login --host https://your-workspace.cloud.databricks.com

Then re-run /ts-profile-databricks and select the new profile.
```

Stop here — do not proceed with an account-level profile.

**Auth test:** Run: `databricks auth describe --profile {dbx_cli_profile} 2>&1`

If it shows `auth_type` and `host`, the profile is usable. Show the auth details.

If it shows authentication errors, warn the user:
```
This CLI profile has authentication issues. You may need to re-authenticate:

  databricks auth login --profile {dbx_cli_profile}

Try re-authenticating, then let me know when done.
```

#### A-CLI3 — Collect Details

```
Profile name for this connection: [Production]
```
Default to `Production`. Store as `{profile_name}`.

Then collect workspace defaults (same as A-SP5).

---

### Save Profile

Read `~/.claude/databricks-profiles.json`.
- Profile with same name exists → replace it.
- Other profiles exist → append.
- File missing → create with this profile as the only entry.

**Service principal profile entry:**
```json
{
  "name": "{profile_name}",
  "dbx_profile": "{dbx_profile}",
  "host": "{host}",
  "auth_type": "oauth-m2m",
  "client_id": "{client_id}",
  "secret_env": "{secret_env}",
  "default_catalog": "{default_catalog}",
  "default_schema": "{default_schema}",
  "sql_warehouse_http_path": "{sql_warehouse_http_path}"
}
```

**PAT profile entry:**
```json
{
  "name": "{profile_name}",
  "dbx_profile": "{dbx_profile}",
  "host": "{host}",
  "auth_type": "pat",
  "secret_env": "{secret_env}",
  "default_catalog": "{default_catalog}",
  "default_schema": "{default_schema}",
  "sql_warehouse_http_path": "{sql_warehouse_http_path}"
}
```

**CLI profile entry:**
```json
{
  "name": "{profile_name}",
  "dbx_profile": "{dbx_cli_profile}",
  "host": "{host}",
  "auth_type": "databricks-cli",
  "default_catalog": "{default_catalog}",
  "default_schema": "{default_schema}",
  "sql_warehouse_http_path": "{sql_warehouse_http_path}"
}
```

### Test and Confirm

Run the [Test](#t--test) flow for this profile.

On success:
```
Databricks profile '{profile_name}' configured and verified.
```

Return to menu (or exit if this was the first-run flow).

---

## U — Update

Show numbered profile list and ask:
```
Which profile would you like to update? (enter number):
```

Then show what can be changed:
```
What would you like to update?

  1  Workspace URL
  2  Refresh credential  (update stored secret or token — same auth method)
  3  Change auth method  (switch between service principal / PAT / CLI profile)
  4  Default catalog
  5  Default schema
  6  SQL warehouse HTTP path

Enter 1–6:
```

### U1 — Update Workspace URL

```
New workspace URL: [{current_host}]
```

Update `host` in the profile JSON. Also update `host` in `~/.databrickscfg` under the
`[{dbx_profile}]` section if the profile uses SP or PAT auth.

Confirm: `URL updated.`

### U2 — Refresh Credential

**Service principal:**

Detect platform, then ask the user to run **in their own terminal**:

**macOS** (`Darwin`):
```
Run this in your terminal to update the client secret:

  security delete-generic-password -s "databricks-{slug}" -a "{client_id}"
  security add-generic-password \
    -s "databricks-{slug}" \
    -a "{client_id}" \
    -w "YOUR_NEW_SECRET_HERE"

Let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell to update the client secret:

  python -c "import keyring; keyring.delete_password('databricks-{slug}', '{client_id}')"
  python -c "import keyring; keyring.set_password('databricks-{slug}', '{client_id}', 'YOUR_NEW_SECRET_HERE')"

Let me know when done.
```

**Linux**:
```
Run this in your terminal to update the client secret:

  python3 -c "import keyring; keyring.delete_password('databricks-{slug}', '{client_id}')"
  python3 -c "import keyring; keyring.set_password('databricks-{slug}', '{client_id}', 'YOUR_NEW_SECRET_HERE')"

Let me know when done.
```

After confirmation, verify (re-use the platform-specific verification block from the Add flow).

**macOS / Linux:** Tell the user to run `source ~/.zshenv`.

After sourcing, also update `client_secret` in `~/.databrickscfg` under `[{dbx_profile}]`.

**PAT:** Same pattern but with account name `"token"`, env var `DATABRICKS_TOKEN_{SLUG}`,
and updating the `token` field in `~/.databrickscfg`.

**CLI profile:** Show:
```
CLI profiles are managed by the Databricks CLI. Run:

  databricks auth login --profile {dbx_cli_profile}

to re-authenticate, then let me know when done.
```

### U3 — Change Auth Method

Run the full credential setup section of [Add](#a--add) for the chosen method.

Clean up the old auth:
- Delete old Keychain entry
- Remove old export line from `~/.zshenv` (macOS/Linux)
- Remove or replace old `~/.databrickscfg` section
- Update profile JSON with new auth fields

### U4–U6 — Simple Field Updates (Catalog, Schema, Warehouse)

```
New {field}: [{current_value}]
```

Update the field in profile JSON. No credential or config changes needed.

Confirm: `{Field} updated.`

---

## D — Delete

Show numbered profile list and ask:
```
Which profile would you like to delete? (enter number):
```

Confirm:
```
Delete profile '{name}'?
This will remove it from the profile file{, the OS credential store, ~/.zshenv, and ~/.databrickscfg}.

Y / N:
```

If confirmed:

1. **Remove from profile JSON** — filter out the entry with matching `name`. Write the updated file (or delete the file if no profiles remain).

2. **If SP or PAT auth — remove credential store entry:**

   **macOS:**
   ```bash
   security delete-generic-password -s "databricks-{slug}" -a "{account_name}"
   ```
   Where `{account_name}` is `{client_id}` for SP or `"token"` for PAT.

   **Windows / Linux:**
   ```python
   import keyring
   try:
       keyring.delete_password("databricks-{slug}", "{account_name}")
   except Exception:
       pass
   ```

   If not found, continue silently.

3. **If SP or PAT auth — remove export line from shell profile** (macOS/Linux only) — read `~/.zshenv`, filter out any line that exports `{secret_env}`, write back.

4. **If SP or PAT auth — remove `~/.databrickscfg` section** — read the file, remove the `[{dbx_profile}]` section, write back. Preserve all other sections.

5. Tell the user:
```
Profile '{name}' deleted.
```
**macOS / Linux** (if SP or PAT): also tell the user:
```
Run this in your terminal to apply the ~/.zshenv change:

  source ~/.zshenv
```
**Windows:** no shell profile reload needed.

---

## T — Test

Show numbered profile list (if more than one) and ask which to test. If only one, confirm and test it directly.

### Test Step 1 — Auth Check

```bash
source ~/.zshenv && databricks auth describe --profile {dbx_profile} 2>&1
```

Check that the output shows a valid `auth_type` and no authentication errors.

On auth failure: `Authentication failed — check credentials. Run U → Refresh credential.`

### Test Step 2 — Workspace Connectivity

```bash
databricks clusters list --profile {dbx_profile} -o json 2>&1
```

This verifies the profile can reach the workspace and authenticate. The output doesn't matter — a successful response (even empty list) confirms connectivity.

On failure: show the error and suggest checking the workspace URL or credentials.

### Test Step 3 — Catalog Access (if default_catalog is set)

```bash
databricks catalogs get {default_catalog} --profile {dbx_profile} -o json 2>&1
```

On failure: `Catalog '{default_catalog}' not accessible — check the catalog name and permissions.`

### Test Step 4 — SQL Warehouse (if sql_warehouse_http_path is set)

```bash
databricks warehouses list --profile {dbx_profile} -o json 2>&1
```

Parse the output to verify a warehouse matching `{sql_warehouse_http_path}` exists and is accessible.

On success:
```
Profile '{name}' — connection verified.

  Auth:      ✓
  Workspace: ✓
  {if tested: Catalog:   ✓ ({default_catalog})}
  {if tested: Warehouse: ✓}
```

Return to menu.

---

## Error Handling

| Symptom | Action |
|---|---|
| `databricks` not found | Direct user to install CLI; stop |
| Credential write fails | macOS: check the login keychain is unlocked. Windows: ensure `keyring` is installed (`pip install keyring`). Linux: ensure a Secret Service backend is running (`pip install keyring secretstorage`). |
| Env var empty after source | macOS/Linux: remind user to run `source ~/.zshenv` in a real terminal. Windows: restart terminal or re-run the env var setup. |
| OAuth M2M auth failure | Verify client_id and client_secret. Check the Service Principal has workspace access. The SP must be added to the workspace in Account Console → Workspaces → {workspace} → Permissions. |
| PAT auth failure | Token may be expired or revoked. Generate a new one (U → Refresh credential). |
| `PERMISSION_DENIED` on catalog/warehouse | The Service Principal or user needs grants. `GRANT USE CATALOG ON CATALOG {catalog} TO \`{sp_application_id}\`` in SQL. |
| DNS / connection refused | Workspace URL is wrong or unreachable. Check with U → Update URL. |
| `~/.databrickscfg` permissions error | Run `chmod 600 ~/.databrickscfg` to restrict access. |

---

## Technical Reference — For Use by Other Skills

### Reading a Databricks Profile

```python
import json, os

profiles_path = os.path.expanduser("~/.claude/databricks-profiles.json")
with open(profiles_path) as f:
    profiles = json.load(f)

profile = next(p for p in profiles if p["name"] == "{profile_name}")
dbx_profile = profile["dbx_profile"]
catalog = profile.get("default_catalog", "main")
schema = profile.get("default_schema", "default")
warehouse_path = profile.get("sql_warehouse_http_path", "")
```

### Running Databricks CLI Commands

```bash
databricks clusters list --profile {dbx_profile} -o json
databricks catalogs list --profile {dbx_profile} -o json
databricks schemas list {catalog} --profile {dbx_profile} -o json
databricks tables list {catalog}.{schema} --profile {dbx_profile} -o json
```

### Executing SQL via Databricks CLI

```bash
databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "SELECT 1",
    "wait_timeout": "30s"
  }'
```

The `warehouse_id` is extracted from `sql_warehouse_http_path` — it is the last
path segment (e.g. `/sql/1.0/warehouses/abc123` → `abc123`).

### Python SDK Connection

```python
import os
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(
    host=profile["host"],
    client_id=profile.get("client_id"),
    client_secret=os.environ.get(profile.get("secret_env", ""), ""),
)

for c in w.catalogs.list():
    print(c.name)
```

### Extracting Warehouse ID from HTTP Path

```python
warehouse_id = profile["sql_warehouse_http_path"].rstrip("/").split("/")[-1]
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-05-20 | Initial release — Service Principal, PAT, and CLI profile auth |
