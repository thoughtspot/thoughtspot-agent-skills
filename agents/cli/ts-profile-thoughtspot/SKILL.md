---
name: ts-profile-thoughtspot
description: Set up and manage ThoughtSpot connection profiles. Use when configuring a new ThoughtSpot instance, updating credentials, or testing whether an existing profile is working. Credentials are stored securely in the OS keychain.
---

# ThoughtSpot Profile Setup

Manage ThoughtSpot connection profiles stored in `~/.claude/thoughtspot-profiles.json`.

Ask one question at a time. Wait for each answer before moving on.

---

## Step 0 — Overview

On skill invocation, display this introduction before reading the profiles file:

---
**ts-profile-thoughtspot** — manage your ThoughtSpot connection profiles.

Profiles store your ThoughtSpot URL, username, and auth method. Credentials are kept securely in your OS keychain (macOS Keychain, Windows Credential Manager, or Linux Secret Service) — never in the profile file or this conversation.

**Actions:**  L List   A Add   U Update   D Delete   T Test

*Reading profiles…*
---

Then proceed to [Entry Point](#entry-point).

---

## Entry Point

Manage ThoughtSpot connection profiles — add, list, update, delete, or test a profile.

Read `~/.claude/thoughtspot-profiles.json`.

**If no profiles file or empty profiles array:** go directly to [Add](#a--add).

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

**Private IP validation:** If the URL contains a private IP (e.g. `172.x.x.x`,
`10.x.x.x`, `192.168.x.x`), warn the user:
> "Private IP addresses require network connectivity between your machine and the
> ThoughtSpot cluster (e.g. VPN, direct connect). Do you want to continue?"

If the user confirms, proceed. Otherwise ask for a public hostname.

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
```

**Password (2):**
```
Have your password ready — you'll enter it directly into a terminal command (not here).
```

**Secret key (3):**
```
Have your secret key ready — you'll enter it directly into a terminal command (not here).
```

### Save profile and derive credentials

Map the auth method to `{auth_type}`: `1` → `token`, `2` → `password`, `3` → `secret_key`.

Run:

```bash
ts profiles add \
  --platform thoughtspot \
  --name "{profile_name}" \
  --auth-type {auth_type} \
  --field base_url={base_url} \
  --field username={username}
```

Add `--field verify_ssl=false` only if the user confirmed a private/self-signed cluster.

Parse the JSON output. It contains `keychain_store_commands`, `keychain_verify_commands`,
`zshenv_line`, and `windows_env_commands`.

### Store credential

**Never accept the credential in this conversation.**

Show the user the keychain store command for their platform from the
`keychain_store_commands` in the output above, replacing `VALUE` with the
appropriate placeholder:

- Token → `PASTE_YOUR_TOKEN_HERE`
- Password → `YOUR_PASSWORD_HERE`
- Secret key → `YOUR_SECRET_KEY_HERE`

Tell them to run it in their own terminal.

After the user confirms the credential is stored, show the verify command
from `keychain_verify_commands` to confirm it worked.

Stop if verification fails — do not proceed without a confirmed credential write.

### Update shell profile

**macOS / Linux:** Read `~/.zshenv`, upsert the `zshenv_line` from the output
above (replace an existing line for the same env var, or append if not present),
write back. Then tell the user to run `source ~/.zshenv` and wait for confirmation.

**Windows:** Show the `windows_env_commands` from the output above for the user to
run in PowerShell. Note: on Windows the env var step is **optional** — the `ts` CLI
reads credentials directly from Windows Credential Manager at runtime.

### Test and confirm

Run the [Test](#t--test) flow for this profile.

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

Run:

```bash
ts profiles update --platform thoughtspot --name "{profile_name}" --field base_url={new_url}
```

Confirm: `URL updated.`

### U2 — Update Username

```
New username: [{current_username}]
```

If username changes, the credential store entry is keyed by username — migrate it:

**macOS:**
```python
import subprocess
r = subprocess.run(["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{old_username}", "-w"], capture_output=True, text=True)
credential = r.stdout.strip()
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

Where `{keychain_service}` is `thoughtspot-{slug}` (slug derived from the profile name).

Then update the profile JSON:

```bash
ts profiles update --platform thoughtspot --name "{profile_name}" --field username={new_username}
```

Also update the export line in `~/.zshenv` to reference the new username in the
keychain lookup (read, replace the line exporting the profile's env var, write back).

Return to menu.

### U3 — Refresh Credential

Show the auth method for the selected profile, then prompt for the new credential
value (same guidance as Add flow for that method).

Detect platform (`platform.system()`), then ask the user to run **in their own terminal**.

The keychain service is `thoughtspot-{slug}` and the account is the profile's `username`.

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

Also clear the stale token cache:
```bash
source ~/.zshenv && ts auth logout --profile {profile_name}
```

### U4 — Change Auth Method

Run the full Add flow for the new auth method. `ts profiles add` will replace the
existing profile entry.

Clean up the old auth:
- Delete old Keychain entry (show platform-specific delete command).
- Replace old export line in `~/.zshenv` with the new one (the Add flow handles this).

---

## D — Delete

Show numbered profile list and ask:
```
Which profile would you like to delete? (enter number):
```

Confirm:
```
Delete profile '{name}'?
This will remove it from the profile file, the OS credential store, and ~/.zshenv.

Y / N:
```

If confirmed:

1. **Remove profile:**

```bash
ts profiles remove --platform thoughtspot --name "{profile_name}"
```

Parse the JSON output for `keychain_service` and `env_var_to_remove`.

2. **Remove credential store entry** — show the user the command for their platform:

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

3. **Remove export line from ~/.zshenv** — read the file, filter out any line that exports `{env_var_to_remove}`, write back.

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

```bash
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

On success: `Profile '{name}' — connection verified.` Return to menu.

On failure (401/403): `Token expired or credential invalid. Run U → Refresh credential.`

---

## Error Handling

| Symptom | Action |
|---|---|
| Credential write fails | macOS: check the login keychain is unlocked. Windows: ensure `keyring` is installed (`pip install keyring`). Linux: ensure a Secret Service backend is running (`pip install keyring secretstorage`). |
| Env var empty after source | macOS/Linux: remind user to run `source ~/.zshenv` in a real terminal. Windows: the env var is optional — `ts` reads from Credential Manager directly. |
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
| 1.2.0 | 2026-07-13 | Adopt `ts profiles add/update/remove` CLI commands — replaces hand-coded slug derivation, keychain commands, env var naming, and profile JSON I/O |
| 1.1.0 | 2026-05-11 | Add Step 0 orientation paragraph shown before the mode-selection menu |
| 1.0.0 | 2026-05-06 | Initial CoCo CLI version (adapted from Claude Code skill) |
