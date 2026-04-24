---
name: ts-profile-thoughtspot
description: Manage ThoughtSpot connection profiles — add, list, update, delete, and test profiles. Stores credentials securely in the OS credential store (macOS Keychain, Windows Credential Manager, or Linux Secret Service). Run with no arguments to add your first profile or manage existing ones.
---

# ThoughtSpot Setup

Manage ThoughtSpot connection profiles stored in `~/.claude/thoughtspot-profiles.json`.

Ask one question at a time. Wait for each answer before moving on.

---

## Entry Point

Manage ThoughtSpot connection profiles — add, list, update, delete, or test a profile.

Read `~/.claude/thoughtspot-profiles.json`.

**If no profiles file or empty profiles array:** go directly to [Add](#add).

**If profiles exist:** show the menu.

```
ThoughtSpot Profiles

  1. {name}  —  {auth_method}  —  {base_url}
  2. {name}  —  {auth_method}  —  {base_url}
  ...

  L  List profiles       (full details of all profiles)
  A  Add a new profile
  U  Update a profile
  D  Delete a profile
  T  Test a profile
  Q  Quit

Enter L / A / U / D / T / Q:
```

For `auth_method` display: `token_env` → `token`, `password_env` → `password`, `secret_key_env` → `secret key`.

---

## L — List

Show each profile with full details. For each profile:

```
Profile: {name}
  URL:      {base_url}
  Username: {username}
  Auth:     {auth_method_label}
  Env var:  {env_var_name}
  Status:   {SET — credential loaded | NOT SET — run 'source ~/.zshenv' (macOS/Linux) or restart terminal (Windows), or re-add credential}
```

To check status: read `os.environ.get("{env_var_name}", "")` — non-empty = SET.

After displaying all profiles, return to the menu.

---

## A — Add

Collect connection details one at a time:

```
ThoughtSpot URL (e.g. https://myorg.thoughtspot.cloud):
```
Strip trailing slash. Store as `{base_url}`.

```
Username (email):
```
Store as `{username}`.

```
Profile name: [Production]
```
Default to `Production`. Store as `{profile_name}`.

```
Auth method:

  1  Token      — log into ThoughtSpot in a browser (includes SSO) — recommended
  2  Password   — username + password for direct API access
  3  Secret key — secret key from your ThoughtSpot admin

Enter 1, 2, or 3:
```

### Obtain the credential

**Token (1):**
```
To get your token:
  1. Log into ThoughtSpot in your browser
  2. Click Develop in the top navigation
  3. Select REST Playground 2.0
  4. Expand the Authentication section
  5. Click Get Current User Token → Try it out → Execute
  6. Copy the token value from the response body

Tokens are valid for ~24 hours. When yours expires, run /ts-profile-thoughtspot,
choose U (Update), then Refresh credential.

Paste your token (will not be displayed):
```

**Password (2):**
```
Password (will not be displayed):
```

**Secret key (3):**
```
Secret key (will not be displayed):
```

Store input as `{credential_value}`. Never echo it back.

### Derive names

From `{profile_name}`:
- `{slug}` — lowercase, non-alphanumeric → hyphens, collapse multiples, strip ends
  e.g. `"My Staging"` → `"my-staging"`
- `{keychain_service}` — `"thoughtspot-{slug}"`
- `{SLUG}` — slug uppercased, hyphens → underscores  e.g. `"MY_STAGING"`
- `{env_var}`:
  - token      → `THOUGHTSPOT_TOKEN_{SLUG}`
  - password   → `THOUGHTSPOT_PASSWORD_{SLUG}`
  - secret key → `THOUGHTSPOT_SECRET_KEY_{SLUG}`
- `{credential_field}`:
  - token      → `token_env`
  - password   → `password_env`
  - secret key → `secret_key_env`

### Store credential

First detect the platform:
```python
import platform
print(platform.system())  # Darwin = macOS, Windows, Linux
```

Ask the user to run this command **in their own terminal** (not here — credentials
must not enter the Claude Code conversation or its history file):

**macOS** (`Darwin`):
```
Run this in your terminal to store the credential securely:

  security add-generic-password \
    -s "{keychain_service}" \
    -a "{username}" \
    -w "YOUR_{CREDENTIAL_TYPE}_HERE"

Replace YOUR_{CREDENTIAL_TYPE}_HERE with your actual value, then let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell to store the credential securely:

  python -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_{CREDENTIAL_TYPE}_HERE')"

Replace YOUR_{CREDENTIAL_TYPE}_HERE with your actual value, then let me know when done.
```

**Linux**:
```
Run this in your terminal to store the credential securely:

  python3 -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_{CREDENTIAL_TYPE}_HERE')"

Replace YOUR_{CREDENTIAL_TYPE}_HERE with your actual value, then let me know when done.
```

Where `{CREDENTIAL_TYPE}` is `TOKEN`, `PASSWORD`, or `SECRET_KEY` depending on the
auth method chosen. The value will not appear in this conversation.

After the user confirms, verify the entry was written:

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

### Update shell profile

**macOS** (`Darwin`) — export line for `~/.zshenv`:
```
export {env_var}=$(security find-generic-password -s "{keychain_service}" -a "{username}" -w 2>/dev/null)
```
Read `~/.zshenv` (empty string if missing). If the line already exports `{env_var}`, replace it. Otherwise append (preceded by a blank line if file is non-empty).

Tell the user:
```
~/.zshenv updated. Run this in your terminal:

  source ~/.zshenv

Let me know when done.
```
Wait for confirmation.

**Linux** — export line for `~/.zshenv` (or `~/.bashrc` if that is the user's shell profile):
```
export {env_var}=$(python3 -c "import keyring; v=keyring.get_password('{keychain_service}', '{username}'); print(v or '', end='')" 2>/dev/null)
```
Apply the same read/replace/append logic as macOS. Tell the user to run `source ~/.zshenv` (or the appropriate profile file).

**Windows** — set a permanent user environment variable via PowerShell:
```
Run this in PowerShell to persist the credential as an env var:

  $val = python -c "import keyring; v=keyring.get_password('{keychain_service}', '{username}'); print(v or '', end='')"
  [System.Environment]::SetEnvironmentVariable('{env_var}', $val, 'User')

Let me know when done, then restart your terminal for the change to take effect.
```
Note: on Windows the env var step is **optional** — the `ts` CLI reads credentials
directly from Windows Credential Manager at runtime. Skip this step if the user only
needs `ts` commands; advise it only if they need `{env_var}` available in other tools.

### Save profile

Read `~/.claude/thoughtspot-profiles.json`.
- Profile with same name exists → replace it.
- Other profiles exist → append.
- File missing → create with this profile as the only entry.

Profile entry:
```json
{
  "name": "{profile_name}",
  "base_url": "{base_url}",
  "username": "{username}",
  "{credential_field}": "{env_var}"
}
```

### Test and confirm

Run the [Test](#test-a-profile) flow for this profile.

On success:
```
ThoughtSpot profile '{profile_name}' configured and verified.
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

  1  URL
  2  Username
  3  Refresh credential  (update stored value — same auth method)
  4  Change auth method  (switch between token / password / secret key)

Enter 1–4:
```

### U1 — Update URL

```
New URL: [{current_base_url}]
```

Update `base_url` in the profile JSON. No Keychain or env var changes needed.

Confirm: `URL updated.`

### U2 — Update Username

```
New username: [{current_username}]
```

If username changes:
- The credential store entry is keyed by username — migrate it to the new username:

**macOS:**
```python
import subprocess
# Read existing credential
r = subprocess.run(["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{old_username}", "-w"], capture_output=True, text=True)
credential = r.stdout.strip()
# Delete old, add new
subprocess.run(["security", "delete-generic-password", "-s", "{keychain_service}", "-a", "{old_username}"], capture_output=True)
subprocess.run(["security", "add-generic-password", "-s", "{keychain_service}", "-a", "{new_username}", "-w", credential], capture_output=True)
print("Keychain entry updated.")
```

**Windows / Linux:**
```python
import keyring
credential = keyring.get_password("{keychain_service}", "{old_username}")
if credential:
    keyring.delete_password("{keychain_service}", "{old_username}")
    keyring.set_password("{keychain_service}", "{new_username}", credential)
    print("Credential store updated.")
else:
    print("No stored credential found for old username — re-add manually.")
```

Update `username` in profile JSON. Return to menu.

### U3 — Refresh Credential

Show the auth method for the selected profile, then prompt for the new credential value (same prompt as Add step for that method).

Detect platform (`platform.system()`), then ask the user to run **in their own terminal**:

**macOS** (`Darwin`):
```
Run this in your terminal to update the credential:

  security delete-generic-password -s "{keychain_service}" -a "{username}"
  security add-generic-password \
    -s "{keychain_service}" \
    -a "{username}" \
    -w "YOUR_NEW_CREDENTIAL_HERE"

Let me know when done.
```

**Windows** (PowerShell):
```
Run this in PowerShell to update the credential:

  python -c "import keyring; keyring.delete_password('{keychain_service}', '{username}')"
  python -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_NEW_CREDENTIAL_HERE')"

Let me know when done.
```

**Linux**:
```
Run this in your terminal to update the credential:

  python3 -c "import keyring; keyring.delete_password('{keychain_service}', '{username}')"
  python3 -c "import keyring; keyring.set_password('{keychain_service}', '{username}', 'YOUR_NEW_CREDENTIAL_HERE')"

Let me know when done.
```

After confirmation, verify (re-use the platform-specific verification block from the Add flow).

No profile JSON changes needed (env var name stays the same).

**macOS / Linux:** Tell the user:
```
Credential updated. Run this in your terminal to apply:

  source ~/.zshenv
```

**Windows:** Tell the user: `Credential updated in Windows Credential Manager. Restart your terminal for the change to take effect (or it will be read directly from the credential store at next use).`

### U4 — Change Auth Method

Run the full credential setup section of [Add](#add) for this profile (auth method selection → credential prompt → Keychain store → ~/.zshenv update → profile JSON update).

The old Keychain entry and env var are cleaned up as part of the new setup:
- Delete old Keychain entry.
- Replace old export line in `~/.zshenv` with new one.
- Update profile JSON with new `{credential_field}` and `{env_var}`.

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

1. **Remove from profile JSON** — filter out the entry with matching `name`. Write the updated file (or delete the file if no profiles remain).

2. **Remove credential store entry:**

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

3. **Remove export line from ~/.zshenv** — read the file, filter out any line that exports `{env_var}`, write back.

4. Tell the user:
```
Profile '{name}' deleted.
```
**macOS / Linux:** also tell the user:
```
Run this in your terminal to apply the ~/.zshenv change:

  source ~/.zshenv
```
**Windows:** no shell profile reload needed.

---

## T — Test

Show numbered profile list (if more than one) and ask which to test. If only one, confirm and test it directly.

**macOS / Linux:**
```bash
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

**Windows:**
```bash
ts auth whoami --profile {profile_name}
```
(No source step needed — credentials are read from Windows Credential Manager directly.)

On success: `Profile '{name}' — connection verified.` Return to menu.

---

## Error Handling

| Symptom | Action |
|---|---|
| Credential write fails | macOS: check the login keychain is unlocked. Windows: ensure `keyring` is installed (`pip install keyring`). Linux: ensure a Secret Service backend is running (`pip install keyring secretstorage`). |
| Env var empty after source | macOS/Linux: remind user to run `source ~/.zshenv` in a real terminal (not with `!`). Windows: the env var is optional — `ts` reads from Credential Manager directly. |
| 401 / 403 on `ts auth whoami` | Wrong or expired credential. Token: get a fresh one (U → Refresh credential). Run `ts auth logout --profile {name}` to clear the stale cache first. |
| DNS / connection refused | URL is wrong or instance unreachable. Check with U → Update URL. |
| `SSLCertVerificationError: certificate verify failed: self signed certificate` | Internal/dev cluster with a self-signed cert. Manually add `"verify_ssl": false` to the profile entry in `~/.claude/thoughtspot-profiles.json`. The CLI will skip certificate verification for that profile. Do not use on production instances. |

---

## Technical Reference — For Use by Other Skills

Other skills should use the `ts` CLI for all ThoughtSpot API calls. The CLI handles
token caching, Keychain access, and expiry automatically — no manual auth scripts,
temp files, or `source ~/.zshenv` wrangling needed in skill logic.

### Authentication

Verify a profile is working:

```bash
# macOS / Linux
source ~/.zshenv && ts auth whoami --profile {profile_name}

# Windows (no source step — credentials read from Credential Manager directly)
ts auth whoami --profile {profile_name}
```

If this returns 401, the token is expired. Ask the user to refresh it (U → Refresh
credential in this skill), then clear the stale cache:

```bash
ts auth logout --profile {profile_name}
```

### Common API Calls

```bash
# Search for models/worksheets
ts metadata search --profile {profile_name} --subtype WORKSHEET --name "%keyword%"

# Export TML with FQN and associated table objects
ts tml export {guid} --profile {profile_name} --fqn --associated

# Import TML
echo '["{tml_string}"]' | ts tml import --profile {profile_name} --policy ALL_OR_NONE

# List Snowflake connections
ts connections list --profile {profile_name}
```

### Token Cache

The CLI stores tokens per profile in the OS temp directory (`tempfile.gettempdir()/ts_token_{slug}.txt`,
permissions 600 on POSIX) and refreshes them automatically on expiry. Skills do not
need to manage this file.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.1 | 2026-04-24 | Add one-line context before menu |
| 1.0.0 | 2026-04-24 | Initial versioned release |
