# Direct API Authentication (Fallback)

> **Snowsight Workspace limitation:** This fallback path uses `python3` and `curl`
> via the Bash tool, which are **not available** in Snowsight Workspaces (only `ls`,
> `dbt`, and `snow` commands are supported). If the stored procedures are missing and
> you are in a Snowsight Workspace, inform the user they must run `/thoughtspot-setup`
> first to create the stored procedures. Do not attempt direct API calls.

This file documents the direct API authentication flow used when the
`TS_SEARCH_MODELS` and `TS_EXPORT_TML` stored procedures do not exist in
`SKILLS.PUBLIC`. This is the fallback path — the preferred path uses stored procedures.

---

## Session continuity — skip if already authenticated this session

If ThoughtSpot and Snowflake profiles were already selected earlier in this
conversation (e.g. for a previous model in a batch), skip profile selection entirely
and reuse the same profiles. If `/tmp/ts_token.txt` is missing (e.g. it was cleaned
up after the last model) but the profile's env var is set, re-authenticate silently:

```python
import os, stat
token = os.environ.get("{token_env}", "")
if token:
    with open("/tmp/ts_token.txt", "w") as f: f.write(token)
    os.chmod("/tmp/ts_token.txt", stat.S_IRUSR | stat.S_IWUSR)
    # proceed — no user prompt needed
```

Only show profile-selection prompts on the very first model of the session.

## Stale token check — always run before writing a new token

```python
import os, time
token_path = "/tmp/ts_token.txt"
if os.path.exists(token_path) and time.time() - os.path.getmtime(token_path) > 23 * 3600:
    os.remove(token_path)  # expired — re-authenticate
```

## Profile selection (first model only)

1. Read `~/.claude/thoughtspot-profiles.json` if it exists.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and ask the user to confirm before proceeding.
4. If no profiles file: fall back to `THOUGHTSPOT_BASE_URL` / `THOUGHTSPOT_USERNAME` / `THOUGHTSPOT_SECRET_KEY` env vars.

```
Available ThoughtSpot profiles:
  1. Production — analyst@company.com @ myorg.thoughtspot.cloud
  2. Staging    — analyst@company.com @ myorg-staging.thoughtspot.cloud

Select a profile (or press Enter to use #1):
```

After profile is confirmed, resolve credentials in priority order:
`token_env` → `password_env` → `secret_key_env` (use the first field present).

- Read the env var value at runtime via `os.environ.get(env_var_name)`
- **Never print, echo, or log any credential value or bearer token.**
- If the env var is unset or empty, prompt the user to set it before proceeding:
  ```
  Credential for {profile_name} is not set ({env_var_name} is empty).
  Store it in the macOS Keychain, then wire up ~/.zshenv and reload:

    # Store (run in your terminal, not in Claude Code)
    security add-generic-password -s "thoughtspot-{profile}" -a "{username}" -w "your-value"

    # Add to ~/.zshenv
    export {env_var_name}=$(security find-generic-password -s "thoughtspot-{profile}" -a "{username}" -w 2>/dev/null)

    # Reload
    source ~/.zshenv
  ```
  For `token_env`: also remind the user to get a fresh token from the ThoughtSpot
  Developer Playground: Develop → REST Playground 2.0 → Authentication →
  Get Current User Token → Try it out → Execute → copy the `token` value.
  If the user cannot use the Keychain and insists on pasting, warn that the value
  will be visible in the conversation, use it for this session only, and do not
  write it to any file.
- If no credential field is present in the profile, ask which auth method they want
  to use and which env var name to read it from.

Strip any trailing slash from `base_url` before constructing URLs.

## Obtain the bearer token

Use Python so credentials never appear in command text
(see [~/.claude/skills/thoughtspot-setup/SKILL.md](~/.claude/skills/thoughtspot-setup/SKILL.md) — Pattern A):
- `token_env`: use the value directly as the token — no API call needed
- `password_env` / `secret_key_env`: call `POST /api/rest/2.0/auth/token/full` with
  `validity_time_in_sec: 3600`
- Write the token to `/tmp/ts_token.txt` with `600` permissions
- Print only `"Authenticated."` — never print the token value

On 401/403 for password auth — stop and inform the user that API password login may
be disabled (MFA or SSO enforcement). Suggest using `token_env` from the Developer
Playground, or asking their admin for the trusted auth secret key.

## Token persistence across Bash calls

Bash tool calls do not share shell state between separate invocations. Never store
the token in a shell variable across calls — it will be empty in the next call.
Instead, use one of these strategies for every subsequent API call:

- **Temp file (preferred for multi-call scripts):** Authenticate using Pattern A in
  [~/.claude/skills/thoughtspot-setup/SKILL.md](~/.claude/skills/thoughtspot-setup/SKILL.md) — writes the token
  to `/tmp/ts_token.txt` with `600` permissions. Read it back in subsequent calls:
  ```python
  with open("/tmp/ts_token.txt") as f:
      token = f.read().strip()
  ```
- **Single pipeline:** Combine all API calls into one `python3` script within a single
  Bash invocation. Authenticate at the top, reuse the token variable throughout.
- **Never** pass the secret key or token as a shell argument or in a curl `-d` string —
  the full command text is visible to the user.

The temp file approach is most reliable for the multi-step workflow in this skill.
The token file is cleaned up automatically at the end of the workflow (Step 12).
