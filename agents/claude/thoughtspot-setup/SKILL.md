---
name: thoughtspot-setup
description: Manage ThoughtSpot connection profiles — add, list, update, delete, and test profiles. Stores credentials securely in macOS Keychain. Run with no arguments to add your first profile or manage existing ones.
---

# ThoughtSpot Setup

Manage ThoughtSpot connection profiles stored in `~/.claude/thoughtspot-profiles.json`.

Ask one question at a time. Wait for each answer before moving on.

---

## Entry Point

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
  Status:   {SET — credential loaded | NOT SET — run 'source ~/.zshenv' or re-add credential}
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

Tokens are valid for ~24 hours. When yours expires, run /thoughtspot-setup,
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

### Store in Keychain

Ask the user to run this command **in their own terminal** (not here — credentials
must not enter the Claude Code conversation or its history file):

```
Run this in your terminal to store the credential securely:

  security add-generic-password \
    -s "{keychain_service}" \
    -a "{username}" \
    -w "YOUR_{CREDENTIAL_TYPE}_HERE"

Replace YOUR_{CREDENTIAL_TYPE}_HERE with your actual value, then let me know when done.
```

Where `{CREDENTIAL_TYPE}` is `TOKEN`, `PASSWORD`, or `SECRET_KEY` depending on the
auth method chosen. The value will not appear in this conversation.

After the user confirms, verify the entry was written:

```python
import subprocess
r = subprocess.run(
    ["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{username}"],
    capture_output=True
)
print("Stored." if r.returncode == 0 else "Not found — check the command ran without errors.")
```

Stop if verification fails — do not proceed without a confirmed Keychain write.

### Update ~/.zshenv

Export line:
```
export {env_var}=$(security find-generic-password -s "{keychain_service}" -a "{username}" -w 2>/dev/null)
```

Read `~/.zshenv` (empty string if missing).
- Line already exports `{env_var}` → replace it.
- Not present → append (preceded by a blank line if file is non-empty).

Tell the user:
```
~/.zshenv updated. Run this in your terminal:

  source ~/.zshenv

Let me know when done.
```

Wait for confirmation.

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
- The Keychain entry is keyed by username — delete the old entry, add a new one with the same credential value:

```python
import subprocess
# Read existing credential
r = subprocess.run(["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{old_username}", "-w"], capture_output=True, text=True)
credential = r.stdout.strip()
# Delete old
subprocess.run(["security", "delete-generic-password", "-s", "{keychain_service}", "-a", "{old_username}"], capture_output=True)
# Add new
subprocess.run(["security", "add-generic-password", "-s", "{keychain_service}", "-a", "{new_username}", "-w", credential], capture_output=True)
print("Keychain entry updated.")
```

Update `username` in profile JSON. Return to menu.

### U3 — Refresh Credential

Show the auth method for the selected profile, then prompt for the new credential value (same prompt as Add step for that method).

Ask the user to run this command **in their own terminal**:

```
Run this in your terminal to update the credential:

  security delete-generic-password -s "{keychain_service}" -a "{username}"
  security add-generic-password \
    -s "{keychain_service}" \
    -a "{username}" \
    -w "YOUR_NEW_CREDENTIAL_HERE"

Let me know when done.
```

After confirmation, verify:

```python
import subprocess
r = subprocess.run(
    ["security", "find-generic-password", "-s", "{keychain_service}", "-a", "{username}"],
    capture_output=True
)
print("Updated." if r.returncode == 0 else "Not found — check the commands ran without errors.")
```

No profile JSON or `~/.zshenv` changes needed (env var name stays the same).

Tell the user:
```
Credential updated. Run this in your terminal to apply:

  source ~/.zshenv
```

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

2. **Remove Keychain entry:**
```bash
security delete-generic-password -s "{keychain_service}" -a "{username}"
```
If not found, continue silently.

3. **Remove export line from ~/.zshenv** — read the file, filter out any line that exports `{env_var}`, write back.

4. Tell the user:
```
Profile '{name}' deleted.

Run this in your terminal to apply the ~/.zshenv change:

  source ~/.zshenv
```

---

## T — Test

Show numbered profile list (if more than one) and ask which to test. If only one, confirm and test it directly.

Run:

```bash
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

On success: `Profile '{name}' — connection verified.` Return to menu.

---

## Error Handling

| Symptom | Action |
|---|---|
| Keychain write fails | Show error. Ask user to check macOS login keychain is unlocked. |
| Env var empty after source | Remind user to run `source ~/.zshenv` in a real terminal (not with `!`). |
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
source ~/.zshenv && ts auth whoami --profile {profile_name}
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

The CLI stores tokens per profile in `/tmp/ts_token_{slug}.txt` (permissions 600)
and refreshes them automatically on expiry. Skills do not need to manage this file.
