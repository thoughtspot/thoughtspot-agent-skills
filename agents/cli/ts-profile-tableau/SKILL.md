---
name: ts-profile-tableau
description: Set up and manage Tableau Server/Cloud connection profiles. Use when configuring a new Tableau instance for workbook migration, updating credentials, or testing whether an existing profile is working. Supports password and Personal Access Token (PAT) auth. Credentials are stored securely in the OS keychain.
---

# Tableau Profile Setup

Manage Tableau Server/Cloud connection profiles stored in `~/.claude/tableau-profiles.json`.

Ask one question at a time. Wait for each answer before moving on.

---

## Prerequisites

- `ts` CLI installed: `pip install -e tools/ts-cli`
- A Tableau Server or Tableau Cloud account with REST API access
- Your Tableau credentials ready:
  - **Password auth:** your Tableau username (email) and password
  - **PAT auth:** a Personal Access Token name and secret (Settings → Personal Access Tokens)

---

## On Invocation

Ask: **Add, List, Test, or Remove a Tableau profile?**

---

## Add

### Step 1 — Collect profile details

Ask in sequence (one question per message):

1. **Profile name** — a friendly label (e.g. "Tableau Cloud Prod")
2. **Server URL** — the Tableau base URL (e.g. `https://prod-apsoutheast-a.online.tableau.com`)
3. **Site content URL** — the path segment after `/site/` in the browser URL when logged in.
   For Tableau Server default site, use an empty string.
4. **Auth method** — `password` or `pat`

If **password**:
5. **Username** — Tableau login email

If **pat**:
5. **PAT name** — the token label (not a secret)

### Step 2 — Derive names

From the profile name, derive:

```
slug        = lowercase, non-alphanumeric → hyphens
              e.g. "My Tableau Cloud" → "my-tableau-cloud"
SLUG        = slug uppercased, hyphens → underscores
              e.g. "MY_TABLEAU_CLOUD"
```

Credential env var:
- Password: `TABLEAU_PASSWORD_{SLUG}`
- PAT: `TABLEAU_PAT_SECRET_{SLUG}`

Keychain service: `tableau-{slug}`
Keychain account:
- Password: the username (email)
- PAT: the PAT name

### Step 3 — Store credential

**Never accept the credential in this conversation.**

Show the user the commands to run in their own terminal. Do not ask them
to paste the credential here.

#### macOS

```bash
security add-generic-password -s "tableau-{slug}" -a "{account}" -w "PASTE_CREDENTIAL_HERE"
```

Then add the env var to `~/.zshenv`:

```bash
echo 'export {ENV_VAR}="$(security find-generic-password -s tableau-{slug} -a {account} -w)"' >> ~/.zshenv
source ~/.zshenv
```

#### Windows

```powershell
python -c "import keyring; keyring.set_password('tableau-{slug}', '{account}', input('Credential: '))"
```

Then set the env var permanently:

```powershell
[System.Environment]::SetEnvironmentVariable('{ENV_VAR}', (python -c "import keyring; print(keyring.get_password('tableau-{slug}', '{account}'))"), 'User')
```

#### Linux

```bash
python3 -c "import keyring; keyring.set_password('tableau-{slug}', '{account}', input('Credential: '))"
echo 'export {ENV_VAR}="$(python3 -c \"import keyring; print(keyring.get_password(\\\"tableau-{slug}\\\", \\\"{account}\\\"))\")"' >> ~/.zshenv
source ~/.zshenv
```

### Step 4 — Write profile JSON

Build the profile entry and write to `~/.claude/tableau-profiles.json`:

```python
import json
from pathlib import Path

profile_path = Path.home() / ".claude" / "tableau-profiles.json"
existing = json.loads(profile_path.read_text()) if profile_path.exists() else []

new_profile = {
    "name": "{PROFILE_NAME}",
    "server_url": "{SERVER_URL}",
    "site_content_url": "{SITE_CONTENT_URL}",
    "auth": "{AUTH_METHOD}",
    # password fields:
    "username": "{USERNAME}",          # omit if PAT
    "password_env": "{ENV_VAR}",       # omit if PAT
    # PAT fields:
    "pat_name": "{PAT_NAME}",          # omit if password
    "pat_secret_env": "{ENV_VAR}",     # omit if password
    "api_version": "3.22"
}

existing.append(new_profile)
profile_path.write_text(json.dumps(existing, indent=2))
```

### Step 5 — Test

Run: `ts tableau signin --profile "{PROFILE_NAME}"`

If successful, show the site ID and confirm. If it fails, troubleshoot:
- 401 → wrong password/PAT secret, or PAT disabled on the site
- Connection error → wrong server URL
- "site not found" → wrong site content URL

---

## List

Run: `ts profiles list --tableau`

Shows all Tableau profiles without credentials.

---

## Test

Ask which profile to test, then run:

```bash
ts tableau signin --profile "{PROFILE_NAME}"
```

Report success or failure with the error detail.

---

## Remove

Ask which profile to remove, then:

1. Remove the profile entry from `~/.claude/tableau-profiles.json`
2. Show the user the command to remove the keychain entry:

```bash
# macOS
security delete-generic-password -s "tableau-{slug}" -a "{account}"
```

```powershell
# Windows
python -c "import keyring; keyring.delete_password('tableau-{slug}', '{account}')"
```

```bash
# Linux
python3 -c "import keyring; keyring.delete_password('tableau-{slug}', '{account}')"
```

3. Show the user the env var line to remove from `~/.zshenv`

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-26 | Initial release — password and PAT auth |
