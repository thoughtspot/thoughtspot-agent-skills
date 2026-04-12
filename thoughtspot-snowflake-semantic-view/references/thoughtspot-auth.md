# ThoughtSpot Authentication and API Reference

Profile configuration, token persistence patterns, and API call examples.
Reusable across any skill that connects to ThoughtSpot.

---

## Credential Safety Rules

These rules apply everywhere in this skill:

- **Never embed a secret key, password, or token value in a shell command.** When Claude
  runs a Bash command, the full command text — including interpolated values — is visible
  to the user. Always read secrets from env vars inside a Python script where the value
  is never part of the command string.
- **Never print or echo a secret key, password, or bearer token to the terminal.**
  Confirm success with a neutral message (e.g. `"Authenticated."`) instead.
- **Set `600` permissions on any temp file containing a token** so it is only readable
  by the current user.
- **The bearer token is a credential.** Treat it the same as the secret key — do not
  log it, print it, or include it in error messages.

---

## Profile Configuration

Named profiles are stored in `~/.claude/thoughtspot-profiles.json`. Non-sensitive
values (URL, username) live in the file; secret keys are referenced by env var name
and must be exported in `~/.zshrc` (or equivalent shell profile).

**Profile file format:**
```json
{
  "profiles": [
    {
      "name": "Production",
      "base_url": "https://myorg.thoughtspot.cloud",
      "username": "analyst@company.com",
      "secret_key_env": "THOUGHTSPOT_SECRET_KEY_PROD"
    },
    {
      "name": "Staging",
      "base_url": "https://myorg-staging.thoughtspot.cloud",
      "username": "analyst@company.com",
      "secret_key_env": "THOUGHTSPOT_SECRET_KEY_STAGING"
    }
  ]
}
```

**Shell profile (`~/.zshrc`):**
```bash
export THOUGHTSPOT_SECRET_KEY_PROD=your-production-secret-key
export THOUGHTSPOT_SECRET_KEY_STAGING=your-staging-secret-key
```

**Profile selection flow:**
1. Read `~/.claude/thoughtspot-profiles.json` if it exists
2. If multiple profiles: display numbered list and ask user to select
3. If one profile: show it and confirm before proceeding
4. If no profiles file: fall back to `THOUGHTSPOT_BASE_URL` / `THOUGHTSPOT_USERNAME` / `THOUGHTSPOT_SECRET_KEY` env vars

**Resolving the secret key:**
- Read the `secret_key_env` field from the profile (e.g. `THOUGHTSPOT_SECRET_KEY_PROD`)
- Read that env var at runtime: `os.environ.get('THOUGHTSPOT_SECRET_KEY_PROD')`
- If the env var is unset or empty, ask the user to paste the key directly for this session only — do not write it to any file

---

## Token Persistence

Tokens obtained from `/api/rest/2.0/auth/token/full` are session-scoped. In Claude
Code's Bash tool, **shell variables do not persist between separate tool invocations**.
Use one of these patterns:

**Pattern A — Temp file (recommended for multi-step skills):**

Use Python so the secret key is read from the environment and never appears in the
command string. The token is written with `600` permissions so only the current user
can read it.

```python
import os, stat, requests

base_url   = "{base_url}".rstrip('/')          # from profile — not secret
username   = "{username}"                       # from profile — not secret
secret_key = os.environ.get("{secret_key_env}") # value never in command text

resp = requests.post(
    f"{base_url}/api/rest/2.0/auth/token/full",
    json={"username": username, "secret_key": secret_key, "validity_time_in_sec": 3600},
    headers={"Content-Type": "application/json"},
)
resp.raise_for_status()
token = resp.json()["token"]

with open("/tmp/ts_token.txt", "w") as f:
    f.write(token)
os.chmod("/tmp/ts_token.txt", stat.S_IRUSR | stat.S_IWUSR)  # 600

print("Authenticated.")  # confirm success — never print the token value
```

Subsequent calls read the token from the file:
```python
with open("/tmp/ts_token.txt") as f:
    token = f.read().strip()
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
```

Cleanup — run at end of workflow regardless of outcome:
```bash
rm -f /tmp/ts_token.txt
```

**Pattern B — Single pipeline script:**
Combine all API calls into one `python3` script within a single Bash invocation.
Fetch the token once at the top, store it in a local variable, and reuse it throughout.
The secret key is read via `os.environ.get()` — same rule applies.

**Pattern C — Inline fetch per call (one-off calls only):**
```python
import os, requests
secret_key = os.environ.get("{secret_key_env}")
token = requests.post(
    f"{base_url}/api/rest/2.0/auth/token/full",
    json={"username": "{username}", "secret_key": secret_key, "validity_time_in_sec": 3600},
).json()["token"]
# use token immediately in the same script — do not print it
```

**Do not** set a variable in one Bash call and read it in the next — it will be empty.

---

## API Call Patterns

All environments use the same ThoughtSpot REST API v2 endpoints.

**Python `requests`:**
```python
import requests

base_url = "https://myorg.thoughtspot.cloud"  # from profile
token = "..."  # obtained from auth/token/full

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
}

response = requests.post(
    f"{base_url}/api/rest/2.0/metadata/search",
    json={"metadata": [{"type": "LOGICAL_TABLE"}]},
    headers=headers,
)
response.raise_for_status()
data = response.json()
```

**curl (Claude Code / terminal):**
```bash
curl -s -X POST "{base_url}/api/rest/2.0/metadata/search" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"metadata": [{"type": "LOGICAL_TABLE"}]}'
```
