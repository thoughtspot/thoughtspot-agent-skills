---
name: ts-profile-tableau
description: Set up and manage Tableau Server/Cloud connection profiles. Use when configuring a new Tableau instance for workbook migration, updating credentials, or testing whether an existing profile is working. Supports password and Personal Access Token (PAT) auth. Credentials are stored securely in the OS keychain.
---

# Tableau Profile Setup

Manage Tableau Server/Cloud connection profiles stored in `~/.claude/tableau-profiles.json`.

Ask one question at a time for **dependent** decisions (credential flows are mostly
sequential). Batch **independent** questions when possible — e.g. profile name + server
URL can be collected together.

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

### Step 2 — Save profile and derive credentials

Build the `--field` arguments from the collected details.

For **password** auth:

```bash
ts profiles add \
  --platform tableau \
  --name "{PROFILE_NAME}" \
  --auth-type password \
  --field server_url={SERVER_URL} \
  --field site_content_url={SITE_CONTENT_URL} \
  --field username={USERNAME} \
  --field api_version=3.22
```

For **PAT** auth:

```bash
ts profiles add \
  --platform tableau \
  --name "{PROFILE_NAME}" \
  --auth-type pat \
  --field server_url={SERVER_URL} \
  --field site_content_url={SITE_CONTENT_URL} \
  --field pat_name={PAT_NAME} \
  --field api_version=3.22
```

Parse the JSON output. It contains `keychain_store_commands`, `keychain_verify_commands`,
`zshenv_line`, and `windows_env_commands`.

### Step 3 — Store credential

**Never accept the credential in this conversation.**

Show the user the keychain store command for their platform from the
`keychain_store_commands` in the Step 2 output, replacing `VALUE` with
`PASTE_CREDENTIAL_HERE`. Tell them to run it in their own terminal.

After the user confirms the credential is stored, show the verify command
from `keychain_verify_commands` to confirm it worked.

### Step 4 — Update shell profile

**macOS / Linux:** Read `~/.zshenv`, upsert the `zshenv_line` from Step 2
(replace an existing line for the same env var, or append if not present),
write back. Then tell the user to run `source ~/.zshenv`.

**Windows:** Show the `windows_env_commands` from Step 2 for the user to
run in PowerShell.

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

Ask which profile to remove, then run:

```bash
ts profiles remove --platform tableau --name "{PROFILE_NAME}"
```

Parse the JSON output for `keychain_service` and `env_var_to_remove`.

Show the user the command to remove the keychain entry for their platform:

**macOS:**
```bash
security delete-generic-password -s "{keychain_service}" -a "{account}"
```

**Windows:**
```powershell
python -c "import keyring; keyring.delete_password('{keychain_service}', '{account}')"
```

**Linux:**
```bash
python3 -c "import keyring; keyring.delete_password('{keychain_service}', '{account}')"
```

Then remove the export line for `env_var_to_remove` from `~/.zshenv` (read,
filter out the line starting with `export {env_var_to_remove}=`, write back).

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.1 | 2026-07-22 | Relax prompt-batching: credential flows are mostly sequential, but independent inputs can now be batched (BL-074) |
| 1.1.0 | 2026-07-13 | Adopt `ts profiles add/remove` CLI commands — replaces hand-coded slug derivation, keychain commands, and profile JSON I/O; fixes append-only zshenv bug |
| 1.0.0 | 2026-06-26 | Initial release — password and PAT auth |
