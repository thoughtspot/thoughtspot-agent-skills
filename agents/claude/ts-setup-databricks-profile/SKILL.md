---
name: ts-setup-databricks-profile
description: Manage Databricks connection profiles — add, list, update, delete, and test profiles. Stores PAT tokens securely in macOS Keychain. Run with no arguments to add your first profile or manage existing ones.
---

# Databricks Setup

Manage Databricks connection profiles stored in `~/.claude/databricks-profiles.json`.
Profiles are used by `ts-convert-to-databricks-mv` and other skills that connect to Databricks.

Ask one question at a time. Wait for each answer before moving on.

---

## Entry Point

Read `~/.claude/databricks-profiles.json`.

**If no profiles file or empty profiles array:** go directly to [Add](#add).

**If profiles exist:** show the menu.

```
Databricks Profiles

  1. {name}  —  {hostname}  —  catalog: {catalog}
  2. {name}  —  {hostname}  —  catalog: {catalog}
  ...

  L  List profiles       (full details of all profiles)
  A  Add a new profile
  U  Update a profile
  D  Delete a profile
  T  Test a profile
  Q  Quit

Enter L / A / U / D / T / Q:
```

---

## L — List

Show each profile with full details:

```
Profile: {name}
  Hostname:   {hostname}
  HTTP Path:  {http_path}
  Catalog:    {catalog}
  Schema:     {schema}
  Token env:  {token_env}  |  Status: {SET | NOT SET}
```

To check token env status: `os.environ.get("{token_env}", "")` — non-empty = SET.

After displaying all profiles, return to the menu.

---

## A — Add

### A1 — Collect Connection Details

Ask one at a time:

```
Your Databricks workspace hostname
(from your URL: https://<hostname>.azuredatabricks.net or similar):
```
Store as `{hostname}` — strip leading `https://` if the user includes it.

```
HTTP path for your SQL warehouse or cluster
(in Databricks: SQL Warehouses → your warehouse → Connection details → HTTP Path):
```
Store as `{http_path}`. Example: `/sql/1.0/warehouses/abc1234567890def`

```
Default catalog (e.g. main, hive_metastore):
```
Store as `{catalog}`. Default to `main`.

```
Default schema (optional — leave blank to skip):
```
Store as `{schema}`. Leave empty if the user skips.

```
Profile name for this connection: [Production]
```
Store as `{profile_name}`. Default to `Production`.

---

### A2 — Derive Names

From `{profile_name}`:
- `{slug}` — lowercase, non-alphanumeric → hyphens, collapse multiples, strip ends
  e.g. `"My Staging"` → `"my-staging"`
- `{keychain_service}` — `"databricks-{slug}"`
- `{SLUG}` — slug uppercased, hyphens → underscores
- `{token_env}` — `DATABRICKS_TOKEN_{SLUG}`

---

### A3 — Store Token in Keychain

**Get the token:** Ask the user to generate a Personal Access Token (PAT) in Databricks:

```
To generate a Databricks Personal Access Token:
  1. Open your Databricks workspace in a browser
  2. Go to Settings → Developer → Access Tokens
  3. Click Generate new token, set a name and expiry, copy the token value

Then run this in your terminal (replace YOUR_TOKEN with the actual token):

  security add-generic-password \
    -s "{keychain_service}" \
    -a "{hostname}" \
    -w "YOUR_TOKEN"

Let me know when done.
```

After confirmation, verify:

```python
import subprocess
r = subprocess.run(
    ["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{hostname}"],
    capture_output=True
)
print("Stored." if r.returncode == 0 else "Not found — check the command ran without errors.")
```

Stop if verification fails — do not proceed without a confirmed Keychain write.

---

### A4 — Update ~/.zshenv

Export line:
```
export {token_env}=$(security find-generic-password -s "{keychain_service}" -a "{hostname}" -w 2>/dev/null)
```

Read `~/.zshenv` (empty string if missing).
- Line already exports `{token_env}` → replace it.
- Not present → append (preceded by a blank line if file is non-empty).

Tell the user:
```
~/.zshenv updated. Run this in your terminal:

  source ~/.zshenv

Let me know when done.
```

Wait for confirmation.

---

### A5 — Write the Profile

```json
{
  "name": "{profile_name}",
  "hostname": "{hostname}",
  "http_path": "{http_path}",
  "catalog": "{catalog}",
  "schema": "{schema}",
  "token_env": "{token_env}"
}
```

Read `~/.claude/databricks-profiles.json`.
- Profile with same name exists → replace it.
- Other profiles exist → append.
- File missing → create with this profile as the only entry.

---

### A6 — Test Connection

Write to `/tmp/dbx_verify.py`:

```python
import os, sys

try:
    from databricks import sql as dbsql
except ImportError:
    print("ERROR: databricks-sql-connector not installed.")
    print("  Run: pip install databricks-sql-connector")
    sys.exit(1)

hostname  = "{hostname}"
http_path = "{http_path}"
catalog   = "{catalog}"
token_env = "{token_env}"

token = os.environ.get(token_env, "")
if not token:
    print(f"ERROR: {token_env} is empty — run 'source ~/.zshenv' first.")
    sys.exit(1)

try:
    conn = dbsql.connect(
        server_hostname=hostname,
        http_path=http_path,
        access_token=token
    )
    cursor = conn.cursor()
    cursor.execute("SELECT current_user(), current_catalog(), current_database()")
    row = cursor.fetchone()
    print(f"User:    {row[0]}")
    print(f"Catalog: {row[1]}")
    print(f"Schema:  {row[2]}")
    conn.close()
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
```

Run: `source ~/.zshenv && python3 /tmp/dbx_verify.py`
Remove: `rm -f /tmp/dbx_verify.py`

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

  1  Hostname
  2  HTTP path (warehouse)
  3  Default catalog
  4  Default schema
  5  Refresh token    (update stored value in Keychain)
  6  Rename profile

Enter 1–6:
```

### U — Simple Field Updates (Hostname, HTTP Path, Catalog, Schema)

```
New {field}: [{current_value}]
```

Update the field in profile JSON. Confirm: `{Field} updated.`

### U — Refresh Token

Show the profile's connection details, then:

```
Run this in your terminal to update the stored token:

  security delete-generic-password -s "{keychain_service}" -a "{hostname}"
  security add-generic-password \
    -s "{keychain_service}" \
    -a "{hostname}" \
    -w "YOUR_NEW_TOKEN"

Let me know when done.
```

After confirmation, verify the Keychain entry was updated:

```python
import subprocess
r = subprocess.run(
    ["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{hostname}"],
    capture_output=True
)
print("Token updated." if r.returncode == 0 else "Not found — check the command ran without errors.")
```

No profile JSON or `~/.zshenv` changes needed — the env var expression re-reads from
Keychain on each shell start.

Tell the user:
```
Token updated. Run this in your terminal to apply:

  source ~/.zshenv
```

### U — Rename Profile

```
New profile name: [{current_name}]
```

Update `name` in profile JSON. If auth changes are needed (new slug → new token_env
name), walk through the rename:
1. Derive new slug, new keychain_service, new token_env
2. Copy token: read old keychain entry, write new keychain entry
3. Delete old keychain entry
4. Update `~/.zshenv`: replace old export line with new token_env export
5. Update profile JSON: name, token_env
6. Ask user to run `source ~/.zshenv`

---

## D — Delete

Show numbered profile list and ask:
```
Which profile would you like to delete? (enter number):
```

Confirm:
```
Delete profile '{name}'?
This will remove it from the profile file, the macOS Keychain, and ~/.zshenv.

Y / N:
```

If confirmed:

1. **Remove from profile JSON** — filter out entry with matching `name`. Write updated
   file (or delete the file if no profiles remain).

2. **Remove Keychain entry:**
```bash
security delete-generic-password -s "{keychain_service}" -a "{hostname}"
```
If not found, continue silently.

3. **Remove export line from ~/.zshenv** — read the file, filter out any line that
   exports `{token_env}`, write back.

4. Tell the user:
```
Profile '{name}' deleted.

Run this in your terminal to apply the ~/.zshenv change:

  source ~/.zshenv
```

---

## T — Test

Show numbered profile list (if more than one) and ask which to test. If only one,
confirm and test it directly.

Write to `/tmp/dbx_verify.py` (same script as A6, with values filled in for the
selected profile).

Run: `source ~/.zshenv && python3 /tmp/dbx_verify.py`
Remove: `rm -f /tmp/dbx_verify.py`

Show result as a table (User / Catalog / Schema).

On success: `Profile '{name}' — connection verified.` Return to menu.

---

## Error Handling

| Symptom | Action |
|---|---|
| `databricks-sql-connector` not installed | `pip install databricks-sql-connector` |
| Token env var empty after source | Remind user to run `source ~/.zshenv` in a real terminal |
| `PermissionError` or auth failure | Check token is valid; regenerate PAT if expired |
| `Network error` / `SSL error` | Check hostname is correct (no `https://` prefix); check VPN/firewall |
| `HTTP path not found` | Verify the SQL warehouse is running and HTTP path is correct |
| Keychain write fails | Check macOS login keychain is unlocked |
| `Invalid HTTP path` | HTTP path should start with `/sql/...`; check Databricks Connection details tab |

---

## Technical Reference — For Use by Other Skills

### Python Connector — Connection Code

```python
import os
from databricks import sql as dbsql

profile = {
    "hostname": "...",
    "http_path": "/sql/1.0/warehouses/...",
    "token_env": "DATABRICKS_TOKEN_PRODUCTION"
}

token = os.environ.get(profile['token_env'], '')
if not token:
    raise RuntimeError(f"{profile['token_env']} is empty — run 'source ~/.zshenv' first.")

conn = dbsql.connect(
    server_hostname=profile['hostname'],
    http_path=profile['http_path'],
    access_token=token
)
```

### SQL Execution

```python
cursor = conn.cursor()
cursor.execute("SELECT current_user(), current_catalog()")
row = cursor.fetchone()
conn.close()
```

### DESCRIBE TABLE — Column Metadata

```python
cursor.execute(f"DESCRIBE TABLE `{catalog}`.`{schema}`.`{table_name}`")
rows = cursor.fetchall()
# Returns list of Row objects with fields: col_name (str), data_type (str), comment (str)
# Excludes partition info rows (col_name starts with '#')
columns = [r for r in rows if not r['col_name'].startswith('#')]
```

Column data types returned by `DESCRIBE TABLE` include: `string`, `bigint`, `double`,
`boolean`, `date`, `timestamp`, `decimal(p,s)`, `array<...>`, `map<...>`, `struct<...>`.

### CREATE VIEW — Unity Catalog Metric View

```python
view_ddl = f"""CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`{view_name}`
WITH METRICS
LANGUAGE YAML
AS $$
{yaml_content}
$$"""
cursor.execute(view_ddl)
```

### Verify View Exists

```python
cursor.execute(f"SHOW CREATE TABLE `{catalog}`.`{schema}`.`{view_name}`")
row = cursor.fetchone()
# Returns the DDL string — confirms the view was created
```

### Spot-check Query

```python
# Use backtick-quoting for measure name if it contains spaces
cursor.execute(f"""
  SELECT MEASURE(`{first_measure_name}`)
  FROM `{catalog}`.`{schema}`.`{view_name}`
""")
row = cursor.fetchone()
```

### Profile Selection Pattern (for use in other skills)

```python
import json
from pathlib import Path

profiles_file = Path.home() / '.claude' / 'databricks-profiles.json'
profiles = json.loads(profiles_file.read_text()) if profiles_file.exists() else []

if not profiles:
    print("No Databricks profiles configured. Run /ts-setup-databricks-profile first.")
    exit()
elif len(profiles) == 1:
    profile = profiles[0]
    print(f"Using Databricks profile: {profile['name']} — {profile['hostname']}")
    input("Press Enter to confirm...")
else:
    for i, p in enumerate(profiles, 1):
        print(f"  {i}. {p['name']}  —  {p['hostname']}  —  catalog: {p.get('catalog', '(none)')}")
    choice = int(input("Select a profile: ")) - 1
    profile = profiles[choice]
```

### Notes on Token Expiry

Databricks PATs have a configurable expiry (default: 90 days). If the connection fails
with an authentication error, the token may have expired. Ask the user to:

```
Your Databricks token may have expired. To refresh:
  1. Open Databricks workspace → Settings → Developer → Access Tokens
  2. Revoke the old token and generate a new one
  3. Run /ts-setup-databricks-profile → T (Test) or U → Refresh token
```
