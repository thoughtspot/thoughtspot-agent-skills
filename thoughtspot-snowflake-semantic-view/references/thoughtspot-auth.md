# ThoughtSpot Authentication and API Reference

Profile configuration, token persistence patterns, and API call examples.
Reusable across any skill that connects to ThoughtSpot.

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
```bash
# Step 1: Fetch and persist
TOKEN=$(curl -s -X POST "{BASE_URL}/api/rest/2.0/auth/token/full" \
  -H "Content-Type: application/json" \
  -d '{"username":"...","secret_key":"...","validity_time_in_sec":3600}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
echo "$TOKEN" > /tmp/ts_token.txt

# Subsequent calls: read from file
TOKEN=$(cat /tmp/ts_token.txt)
curl -s ... -H "Authorization: Bearer $TOKEN" ...

# Cleanup — run at end of workflow regardless of outcome
rm -f /tmp/ts_token.txt
```

**Pattern B — Single pipeline script:**
Combine all API calls into one `python3` or `bash` heredoc within a single Bash
invocation. Fetch the token once at the top and reuse the variable throughout.

**Pattern C — Inline fetch per call (for one-off calls only):**
```bash
TOKEN=$(curl -s ... | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" ...  # same invocation
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
