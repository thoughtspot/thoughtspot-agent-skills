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

Write to `/tmp/ts_verify.py` and run `source ~/.zshenv && python3 /tmp/ts_verify.py 2>/dev/null`:

```python
import os, sys, requests

base_url         = "{base_url}".rstrip("/")
username         = "{username}"
env_var          = "{env_var}"
credential_field = "{credential_field}"

credential = os.environ.get(env_var, "")
if not credential:
    print(f"ERROR: {env_var} is not set — run 'source ~/.zshenv' in your terminal first.")
    sys.exit(1)

if credential_field == "token_env":
    token = credential
else:
    payload = {"username": username, "validity_time_in_sec": 60}
    if credential_field == "password_env":
        payload["password"] = credential
    else:
        payload["secret_key"] = credential
    resp = requests.post(
        f"{base_url}/api/rest/2.0/auth/token/full",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code in (401, 403):
        print(f"AUTH FAILED ({resp.status_code}) — credential may be wrong or expired.")
        sys.exit(1)
    resp.raise_for_status()
    token = resp.json()["token"]

resp = requests.get(
    f"{base_url}/api/rest/2.0/auth/session/user",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
)
if resp.status_code == 200:
    print(f"Connected as: {resp.json().get('name', username)}")
else:
    print(f"ERROR {resp.status_code}: {resp.text[:200]}")
    sys.exit(1)
```

Remove: `rm -f /tmp/ts_verify.py`

On success: `Profile '{name}' — connection verified.` Return to menu.

---

## Error Handling

| Symptom | Action |
|---|---|
| Keychain write fails | Show error. Ask user to check macOS login keychain is unlocked. |
| Env var empty after source | Remind user to run `source ~/.zshenv` in a real terminal (not with `!`). |
| 401 / 403 | Wrong or expired credential. Token: get a fresh one (U → Refresh credential). |
| DNS / connection refused | URL is wrong or instance unreachable. Check with U → Update URL. |
| `requests` not found | `pip install requests` |

---

## Technical Reference — For Use by Other Skills

### Pattern A — Auth Script (Token to Temp File)

Write to `/tmp/ts_auth.py`, run with `source ~/.zshenv && python3 /tmp/ts_auth.py`, then remove.
The token is written to `/tmp/ts_token.txt` (permissions `600`) so subsequent Bash calls
can read it without re-authenticating.

```python
import os, stat, requests, sys

base_url       = "{base_url}".rstrip('/')
username       = "{username}"
token_env      = "{token_env}"        # empty string if profile uses a different auth field
password_env   = "{password_env}"     # empty string if not used
secret_key_env = "{secret_key_env}"   # empty string if not used

token      = os.environ.get(token_env,      "") if token_env      else ""
password   = os.environ.get(password_env,   "") if password_env   else ""
secret_key = os.environ.get(secret_key_env, "") if secret_key_env else ""

if token:
    pass  # pre-obtained bearer token — use directly, no API call needed
elif password:
    resp = requests.post(
        f"{base_url}/api/rest/2.0/auth/token/full",
        json={"username": username, "password": password, "validity_time_in_sec": 3600},
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code in (401, 403):
        print("AUTH_FAILED — check password. If MFA/SSO is enforced, use token_env instead.")
        sys.exit(1)
    resp.raise_for_status()
    token = resp.json()["token"]
elif secret_key:
    resp = requests.post(
        f"{base_url}/api/rest/2.0/auth/token/full",
        json={"username": username, "secret_key": secret_key, "validity_time_in_sec": 3600},
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code in (401, 403):
        print("AUTH_FAILED — check secret key.")
        sys.exit(1)
    resp.raise_for_status()
    token = resp.json()["token"]
else:
    print("No credential available — set the required env var first.")
    sys.exit(1)

# Remove stale token file (older than 23 h) before writing
import time
token_path = "/tmp/ts_token.txt"
if os.path.exists(token_path) and time.time() - os.path.getmtime(token_path) > 23 * 3600:
    os.remove(token_path)

with open(token_path, "w") as f:
    f.write(token)
os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 600

print("Authenticated.")  # never print the token value
```

### Read Token in Subsequent Calls

```python
with open("/tmp/ts_token.txt") as f:
    token = f.read().strip()
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
```

### Cleanup

```bash
rm -f /tmp/ts_token.txt
```

### API Call Pattern

```python
import requests

response = requests.post(
    f"{base_url}/api/rest/2.0/metadata/search",
    json={"metadata": [{"type": "LOGICAL_TABLE"}]},
    headers=headers,
)
response.raise_for_status()
data = response.json()
```
