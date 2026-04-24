---
name: ts-profile-snowflake
description: Manage Snowflake connection profiles — add, list, update, delete, and test profiles. Supports Python connector (key pair or password) and Snowflake CLI. Passwords stored securely in the OS credential store (macOS Keychain, Windows Credential Manager, or Linux Secret Service). Run with no arguments to add your first profile or manage existing ones.
---

# Snowflake Setup

Manage Snowflake connection profiles stored in `~/.claude/snowflake-profiles.json`.

Ask one question at a time. Wait for each answer before moving on.

---

## Entry Point

Manage Snowflake connection profiles — add, list, update, delete, or test a profile.

Read `~/.claude/snowflake-profiles.json`.

**If no profiles file or empty profiles array:** go directly to [Add](#add).

**If profiles exist:** show the menu.

```
Snowflake Profiles

  1. {name}  —  {method_label}  —  {account_or_connection}
  2. {name}  —  {method_label}  —  {account_or_connection}
  ...

  L  List profiles       (full details of all profiles)
  A  Add a new profile
  U  Update a profile
  D  Delete a profile
  T  Test a profile
  Q  Quit

Enter L / A / U / D / T / Q:
```

For `method_label` display: `method: python` + `auth: key_pair` → `python / key pair`, `method: python` + `auth: password` → `python / password`, `method: cli` → `Snowflake CLI`.

For `account_or_connection`: show `account` for python profiles, `cli_connection` for cli profiles.

---

## L — List

Show each profile with full details. For each profile:

**Python connector:**
```
Profile: {name}
  Method:    Python connector
  Account:   {account}
  Username:  {username}
  Auth:      {key pair | password}
  Warehouse: {default_warehouse}
  Role:      {default_role}
  {if password: Env var:  {password_env}  |  Status: {SET | NOT SET}}
  {if key_pair: Key file: ~/.ssh/snowflake_key.p8  |  Exists: {yes | no}}
```

**Snowflake CLI:**
```
Profile: {name}
  Method:     Snowflake CLI
  Connection: {cli_connection}
  Warehouse:  {default_warehouse}
  Role:       {default_role}
```

To check password env var status: read `os.environ.get("{password_env}", "")` — non-empty = SET.
To check key file: test whether `~/.ssh/snowflake_key.p8` exists.

After displaying all profiles, return to the menu.

---

## A — Add

```
How should Claude connect to Snowflake?

  1  Python connector  — no extra tools needed; works with key pair or password
  2  Snowflake CLI     — uses your existing `snow` CLI and its config file

Not sure? Choose 1 — fewest dependencies.

Enter 1 or 2:
```

---

### Path A — Python Connector

#### A1 — Collect Account Details

Ask one at a time:

```
Your Snowflake account identifier
(from your URL: https://<account-identifier>.snowflakecomputing.com):
```
Store as `{account}`.

```
Your Snowflake username:
```
Store as `{username}`.

```
Default warehouse (e.g. MY_WAREHOUSE):
```
Store as `{warehouse}`.

```
Default role (e.g. MY_ROLE):
```
Store as `{role}`.

```
Profile name for this connection: [Production]
```
Store as `{profile_name}`. Default to `Production`.

#### A2 — Choose Auth Method

```
Auth method:

  1  Key pair  — generates a key file; more secure (recommended)
  2  Password  — simpler setup

Enter 1 or 2:
```

---

#### A3a — Key Pair Auth

Check whether `~/.ssh/snowflake_key.p8` already exists.

**If it exists:**
```
Found an existing key at ~/.ssh/snowflake_key.p8.
Use it for this profile? (Y/n):
```
If yes: use it and skip key generation.

**If it doesn't exist (or user declines):**

Write to `/tmp/sf_keygen.py`:

```python
import subprocess, os, sys

key_path = os.path.expanduser("~/.ssh/snowflake_key.p8")
pub_path = os.path.expanduser("~/.ssh/snowflake_key.pub")

os.makedirs(os.path.expanduser("~/.ssh"), exist_ok=True)

r1 = subprocess.run(["openssl", "genrsa", "2048"], capture_output=True)
if r1.returncode != 0:
    print(f"Key generation failed: {r1.stderr.decode()}")
    sys.exit(1)

r2 = subprocess.run(
    ["openssl", "pkcs8", "-topk8", "-inform", "PEM", "-out", key_path, "-nocrypt"],
    input=r1.stdout, capture_output=True
)
if r2.returncode != 0:
    print(f"PKCS8 conversion failed: {r2.stderr.decode()}")
    sys.exit(1)

os.chmod(key_path, 0o600)

r3 = subprocess.run(["openssl", "rsa", "-in", key_path, "-pubout", "-out", pub_path], capture_output=True)
if r3.returncode != 0:
    print(f"Public key extraction failed: {r3.stderr.decode()}")
    sys.exit(1)

with open(pub_path) as f:
    print(f.read())
```

Run: `python3 /tmp/sf_keygen.py`
Remove: `rm -f /tmp/sf_keygen.py`

Then show the user:
```
Key pair generated at ~/.ssh/snowflake_key.p8

Run this SQL in Snowsight to assign the public key to your user
(paste the lines between the -----BEGIN and -----END----- markers):

  ALTER USER {username} SET RSA_PUBLIC_KEY='<public key contents here>';

Let me know when you've done that.
```

Wait for confirmation.

**Write the profile:**
```json
{
  "name": "{profile_name}",
  "method": "python",
  "account": "{account}",
  "username": "{username}",
  "auth": "key_pair",
  "private_key_path": "~/.ssh/snowflake_key.p8",
  "private_key_passphrase_env": "",
  "default_warehouse": "{warehouse}",
  "default_role": "{role}"
}
```

---

#### A3b — Password Auth

Derive names from `{profile_name}`:
- `{slug}` — lowercase, non-alphanumeric → hyphens, collapse multiples, strip ends
  e.g. `"My Staging"` → `"my-staging"`
- `{keychain_service}` — `"snowflake-{slug}"`
- `{SLUG}` — slug uppercased, hyphens → underscores
- `{env_var}` — `SNOWFLAKE_PASSWORD_{SLUG}`

**Store credential** — detect platform first (`python -c "import platform; print(platform.system())"`), then ask the user to run **in their own terminal** so the password is never written into the conversation or history file:

**macOS** (`Darwin`):
```
Run this in your terminal:

  security add-generic-password \
    -s "{keychain_service}" \
    -a "{username}" \
    -w "YOUR_PASSWORD_HERE"

Let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell:

  python -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_PASSWORD_HERE')"

Let me know when done.
```

**Linux**:
```
Run this in your terminal:

  python3 -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_PASSWORD_HERE')"

Let me know when done.
```

After confirmation, verify:

**macOS:**
```python
import subprocess
r = subprocess.run(
    ["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{username}"],
    capture_output=True
)
print("Stored." if r.returncode == 0 else "Not found — check the command ran without errors.")
```

**Windows / Linux:**
```python
import keyring
stored = keyring.get_password("{keychain_service}", "{username}")
print("Stored." if stored else "Not found — check the command ran without errors.")
```

Stop if verification fails — do not proceed without a confirmed credential write.

**Update shell profile**

**macOS** — export line for `~/.zshenv`:
```
export {env_var}=$(security find-generic-password -s "{keychain_service}" -a "{username}" -w 2>/dev/null)
```

**Linux** — export line for `~/.zshenv` (or `~/.bashrc`):
```
export {env_var}=$(python3 -c "import keyring; v=keyring.get_password('{keychain_service}', '{username}'); print(v or '', end='')" 2>/dev/null)
```

For both: read the shell profile (empty string if missing). If the line already exports `{env_var}`, replace it. Otherwise append (preceded by a blank line if file is non-empty). Tell the user to run `source ~/.zshenv` and wait for confirmation.

**Windows** — set a permanent user environment variable:
```
Run this in PowerShell:

  $val = python -c "import keyring; v=keyring.get_password('{keychain_service}', '{username}'); print(v or '', end='')"
  [System.Environment]::SetEnvironmentVariable('{env_var}', $val, 'User')

Restart your terminal after, then let me know when done.
```
Note: on Windows this step is optional — the connector reads from Windows Credential Manager via `keyring` at runtime.

**Write the profile:**
```json
{
  "name": "{profile_name}",
  "method": "python",
  "account": "{account}",
  "username": "{username}",
  "auth": "password",
  "password_env": "{env_var}",
  "default_warehouse": "{warehouse}",
  "default_role": "{role}"
}
```

---

#### A4 — Test Python Connector

Write to `/tmp/sf_verify.py`:

```python
import os, sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import snowflake.connector

auth      = "{auth}"
account   = "{account}"
username  = "{username}"
warehouse = "{warehouse}"
role      = "{role}"

try:
    if auth == "key_pair":
        key_path = os.path.expanduser("~/.ssh/snowflake_key.p8")
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
        private_key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        conn = snowflake.connector.connect(account=account, user=username, private_key=private_key_bytes, role=role, warehouse=warehouse)
    else:
        env_var = "{env_var}"
        password = os.environ.get(env_var, "")
        if not password:
            print(f"ERROR: {env_var} is empty — run 'source ~/.zshenv' first.")
            sys.exit(1)
        conn = snowflake.connector.connect(account=account, user=username, password=password, role=role, warehouse=warehouse)

    cur = conn.cursor()
    cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
    row = cur.fetchone()
    print(f"User:      {row[0]}")
    print(f"Role:      {row[1]}")
    print(f"Warehouse: {row[2]}")
    conn.close()
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
```

**macOS / Linux:** `source ~/.zshenv && python3 /tmp/sf_verify.py 2>/dev/null`
**Windows:** `python /tmp/sf_verify.py 2>/dev/null`
Remove: `rm -f /tmp/sf_verify.py` (macOS/Linux) or `del /tmp/sf_verify.py` (Windows)

---

### Path B — Snowflake CLI

#### B1 — Check CLI is Installed

Run: `snow --version 2>&1`

If not found (exit code 127), search for the binary:
```bash
find /usr/local/bin /opt/homebrew/bin /usr/bin ~/.local/bin ~/Library/Python -name "snow" 2>/dev/null | head -5
```

If found at an alternate path, store it as `{snow_cmd}` (e.g. `~/Library/Python/3.9/bin/snow`) and use that path in all subsequent `snow` commands. Confirm to the user:
```
Found snow at {snow_cmd} (version X.Y.Z).
```

If not found anywhere:
```
Snowflake CLI (snow) is not installed.

Install it from:
https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation

Once installed, run `snow --version` to verify, then re-run /ts-profile-snowflake.
```
Stop here.

#### B2 — Choose or Create a Connection

Run: `{snow_cmd} connection list 2>&1`

Parse the connection names from the output and display them numbered:
```
Available connections:

  1  {connection_name_1}
  2  {connection_name_2}
  ...
  N  Create a new connection

Enter a number:
```

**If existing connection selected (1…N-1):** store the corresponding name as `{cli_connection}`. Skip to B3.

**If N (new):** ask for connection name — that becomes `{cli_connection}`. Skip to new-connection flow below.

**If 'new':** ask for connection name, account identifier, username, default role, default warehouse, and auth method (key pair path or browser SSO). Write the config block to `~/.snowflake/config.toml`, show it to the user, and confirm before appending.

#### B3 — Collect Profile Details

```
Profile name for this connection: [Production]
```

Then ask:
```
Override the CLI connection's warehouse and role? (y/N):
```

**If no (default):** set `{warehouse}` and `{role}` to `""` (empty — CLI connection defaults apply).

**If yes:** ask:
```
Default warehouse:
```
```
Default role:
```

Store as `{profile_name}`, `{warehouse}`, `{role}`.

#### B4 — Test CLI Connection

Run: `{snow_cmd} connection test -c {cli_connection} 2>&1`

**If the test fails with `No such file or directory` on a key path:**

Snow CLI 2.8.2 stores connections in `~/.snowflake/connections.toml` (separate from `config.toml`) and does NOT expand `~` in `private_key_path` — it joins the path literally with the CWD. Fix by replacing `~` with the absolute home path in `connections.toml`:

```toml
private_key_path = "/Users/username/.ssh/snowflake_private_key.p8"
```

Read `~/.snowflake/connections.toml`, update the `private_key_path` for the relevant connection, write it back, then re-run the test.

Show output. If it still fails, stop and ask the user to fix the CLI config before continuing.

#### B5 — Write Profile

```json
{
  "name": "{profile_name}",
  "method": "cli",
  "cli_connection": "{cli_connection}",
  "snow_cmd": "{snow_cmd}",
  "default_warehouse": "{warehouse}",
  "default_role": "{role}"
}
```

`snow_cmd` is the resolved path to the `snow` binary (e.g. `~/Library/Python/3.9/bin/snow`). If `snow` was found on PATH, store `"snow"` as the value.

---

### Save Profile

Read `~/.claude/snowflake-profiles.json`.
- Profile with same name exists → replace it.
- Other profiles exist → append.
- File missing → create with this profile as the only entry.

On success:
```
Snowflake profile '{profile_name}' configured and verified.
```

Return to menu (or exit if this was the first-run flow).

---

## U — Update

Show numbered profile list and ask:
```
Which profile would you like to update? (enter number):
```

Then show what can be changed. Options vary by profile type:

**Python connector (key pair):**
```
What would you like to update?

  1  Account identifier
  2  Username
  3  Warehouse
  4  Role
  5  Change auth method  (switch to password)

Enter 1–5:
```

**Python connector (password):**
```
What would you like to update?

  1  Account identifier
  2  Username
  3  Warehouse
  4  Role
  5  Refresh password    (update stored value)
  6  Change auth method  (switch to key pair)

Enter 1–6:
```

**Snowflake CLI:**
```
What would you like to update?

  1  CLI connection name
  2  Warehouse
  3  Role

Enter 1–3:
```

### U — Simple Field Updates (Account, Username, Warehouse, Role, CLI Connection)

```
New {field}: [{current_value}]
```

Update the field in profile JSON. For username changes on password profiles, migrate the stored credential:

**macOS:**
```python
import subprocess
r = subprocess.run(["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{old_username}", "-w"], capture_output=True, text=True)
credential = r.stdout.strip()
subprocess.run(["security", "delete-generic-password", "-s", "{keychain_service}", "-a", "{old_username}"], capture_output=True)
subprocess.run(["security", "add-generic-password", "-s", "{keychain_service}", "-a", "{new_username}", "-w", credential], capture_output=True)
```

**Windows / Linux:**
```python
import keyring
credential = keyring.get_password("{keychain_service}", "{old_username}")
if credential:
    keyring.delete_password("{keychain_service}", "{old_username}")
    keyring.set_password("{keychain_service}", "{new_username}", credential)
```

Update `username` in profile JSON.

Confirm: `{Field} updated.`

### U — Refresh Password

Show the profile's auth details, then detect platform (`platform.system()`) and ask the user to run **in their own terminal**:

**macOS** (`Darwin`):
```
Run this in your terminal to update the password:

  security delete-generic-password -s "{keychain_service}" -a "{username}"
  security add-generic-password \
    -s "{keychain_service}" \
    -a "{username}" \
    -w "YOUR_NEW_PASSWORD_HERE"

Let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell to update the password:

  python -c "import keyring; keyring.delete_password('{keychain_service}', '{username}')"
  python -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_NEW_PASSWORD_HERE')"

Let me know when done.
```

**Linux**:
```
Run this in your terminal to update the password:

  python3 -c "import keyring; keyring.delete_password('{keychain_service}', '{username}')"
  python3 -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_NEW_PASSWORD_HERE')"

Let me know when done.
```

After confirmation, verify using the platform-specific check from the Add flow.

No profile JSON or shell profile changes needed (env var name stays the same).

**macOS / Linux:** Tell the user:
```
Password updated. Run this in your terminal to apply:

  source ~/.zshenv
```

**Windows:** `Password updated in Windows Credential Manager. Restart your terminal for the change to take effect (or it will be read directly from the credential store at next use).`

### U — Change Auth Method

Run the full auth setup section of [Add](#add) for the chosen method:
- **Key pair:** generate or reuse key → assign public key in Snowsight → update profile JSON (`auth: key_pair`, remove `password_env`)
- **Password:** prompt → Keychain → ~/.zshenv → update profile JSON (`auth: password`, add `password_env`, remove `private_key_path`)

Clean up the old auth:
- Switching to key pair: delete Keychain entry, remove export line from `~/.zshenv`
- Switching to password: no key file cleanup (key may be shared across profiles)

---

## D — Delete

Show numbered profile list and ask:
```
Which profile would you like to delete? (enter number):
```

Confirm:
```
Delete profile '{name}'?
This will remove it from the profile file{, the macOS Keychain, and ~/.zshenv | (no Keychain or env var — key pair auth)}.

Y / N:
```

If confirmed:

1. **Remove from profile JSON** — filter out the entry with matching `name`. Write the updated file (or delete the file if no profiles remain).

2. **If password auth — remove credential store entry:**

   **macOS:**
   ```bash
   security delete-generic-password -s "{keychain_service}" -a "{username}"
   ```

   **Windows / Linux:**
   ```python
   import keyring
   try:
       keyring.delete_password("{keychain_service}", "{username}")
   except Exception:
       pass
   ```

   If not found, continue silently.

3. **If password auth — remove export line from shell profile** (macOS/Linux only) — read `~/.zshenv` (or `~/.bashrc`), filter out any line that exports `{password_env}`, write back. Skip on Windows.

4. Tell the user:
```
Profile '{name}' deleted.
```
If password auth on **macOS / Linux**, add:
```
Run this in your terminal to apply the shell profile change:

  source ~/.zshenv
```
If password auth on **Windows**: no shell profile reload needed.
If key pair auth, add:
```
Note: the key file ~/.ssh/snowflake_key.p8 was not removed — it may be used by
other profiles or tools. Delete it manually if no longer needed.
```

---

## T — Test

Show numbered profile list (if more than one) and ask which to test. If only one, confirm and test it directly.

**Python connector:**

Write to `/tmp/sf_verify.py` (same script as A4, with values filled in for the selected profile).

**macOS / Linux:** `source ~/.zshenv && python3 /tmp/sf_verify.py 2>/dev/null`
**Windows:** `python /tmp/sf_verify.py 2>/dev/null`
Remove: `rm -f /tmp/sf_verify.py` (macOS/Linux) or `del /tmp/sf_verify.py` (Windows)

Show the result as a table (User / Role / Warehouse).

On success: `Profile '{name}' — connection verified.` Return to menu.

**Snowflake CLI:**

Run: `{snow_cmd} connection test -c {cli_connection} 2>&1`

If that succeeds, run a live SQL query to confirm real query execution:

`{snow_cmd} sql -c {cli_connection} -q "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE()" 2>&1`

Show the result as a table.

On success: `Profile '{name}' — connection verified.` Return to menu.

---

## Error Handling

| Symptom | Action |
|---|---|
| `snow` not found | Direct user to install CLI; stop |
| Key generation fails | Show openssl error; check openssl is installed (`openssl version`) |
| `ALTER USER` not confirmed | Wait; remind user the key pair won't work until this step is done |
| Credential write fails | macOS: check the login keychain is unlocked. Windows: ensure `keyring` is installed (`pip install keyring`). Linux: ensure a Secret Service backend is running (`pip install keyring secretstorage`). |
| Password env var empty after source | macOS/Linux: remind user to run `source ~/.zshenv` in a real terminal (not with `!`). Windows: env var is optional — connector reads from Credential Manager via `keyring`. |
| Snowflake 250001 / auth error | Check account identifier, username, role, warehouse are all correct |
| `snowflake.connector` not found | `pip install snowflake-connector-python cryptography` |

---

## Technical Reference — For Use by Other Skills

### Python Connector — Connection Code

**Key pair:**
```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os, snowflake.connector

key_path = os.path.expanduser(profile['private_key_path'])
passphrase_env = profile.get('private_key_passphrase_env', '')
passphrase_bytes = os.environ.get(passphrase_env).encode() if passphrase_env else None

with open(key_path, 'rb') as f:
    private_key = serialization.load_pem_private_key(
        f.read(), password=passphrase_bytes, backend=default_backend()
    )
private_key_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

conn = snowflake.connector.connect(
    account=profile['account'], user=profile['username'],
    private_key=private_key_bytes, role=role, warehouse=warehouse,
)
```

**Password:**
```python
conn = snowflake.connector.connect(
    account=profile['account'], user=profile['username'],
    password=os.environ.get(profile['password_env']),
    role=role, warehouse=warehouse,
)
```

### SQL Execution

**Python connector:**
```python
cur = conn.cursor()
cur.execute(f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{db}.{schema}', $${yaml}$$, TRUE)")
print(cur.fetchone())
conn.close()
```

**Snowflake CLI — use a temp SQL file** to avoid shell-escaping issues with dollar-quotes:

```python
import subprocess

sql = f"""USE ROLE {role};
USE DATABASE {db};
USE SCHEMA {schema};
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{db}.{schema}', $${yaml}$$, TRUE);
"""
with open('/tmp/sf_query.sql', 'w') as f:
    f.write(sql)

result = subprocess.run(
    [profile['snow_cmd'], 'sql', '-c', cli_connection, '--format', 'json', '-f', '/tmp/sf_query.sql'],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
```

Remove `TRUE` for the actual CREATE (not dry-run). Cleanup: `rm -f /tmp/sf_query.sql`

### SHOW Commands — Case-Sensitivity Detection

**Python connector:**
```python
cur.execute(f"SHOW SCHEMAS IN DATABASE {db}")
cs_schemas = {r[1] for r in cur.fetchall() if r[1] != r[1].upper()}

schema_ref = f'"{schema}"' if schema in cs_schemas else schema
cur.execute(f'SHOW COLUMNS IN TABLE {db}.{schema_ref}."{phys_table}"')
cs_columns = {r[2] for r in cur.fetchall() if r[2] != r[2].upper()}
```

**Snowflake CLI:**
```python
import subprocess, json

def snow_json(cli_connection, query, snow_cmd='snow'):
    r = subprocess.run(
        [snow_cmd, 'sql', '-c', cli_connection, '--format', 'json', '-q', query],
        capture_output=True, text=True
    )
    return json.loads(r.stdout)

rows = snow_json(cli_connection, f"SHOW SCHEMAS IN DATABASE {db}")
cs_schemas = {r['name'] for r in rows if r['name'] != r['name'].upper()}

schema_ref = f'"{schema}"' if schema in cs_schemas else schema
rows = snow_json(cli_connection, f'SHOW COLUMNS IN TABLE {db}.{schema_ref}."{phys_table}"')
cs_columns = {r['column_name'] for r in rows if r['column_name'] != r['column_name'].upper()}
```

Lowercase in `SHOW` output = case-sensitive identifier = must be quoted in SQL.

### Notes on `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`

- Use `CALL`, not `SELECT`
- First argument: fully-qualified target schema as a string: `'DATABASE.SCHEMA'`
- Second argument: YAML in `$$` dollar-quotes
- Third argument `TRUE`: dry-run (validates without creating) — always run first
- Remove the third argument (or pass `FALSE`) for the actual CREATE

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.1 | 2026-04-24 | Add one-line context before menu |
| 1.0.0 | 2026-04-24 | Initial versioned release |
