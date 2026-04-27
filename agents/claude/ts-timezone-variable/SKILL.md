---
name: ts-timezone-variable
description: Manage the ts_user_timezone variable in ThoughtSpot — search current values, or set/remove timezone values at org or user level.
---

# ThoughtSpot: Manage Timezone Variable

Manage values for the `ts_user_timezone` template variable, which controls the timezone
applied to date/time calculations per org or per user.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [~/.claude/skills/ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- The `ts_user_timezone` variable must already exist on the cluster

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If the file is missing or empty, prompt the
user to run `/ts-profile-thoughtspot` first.

If multiple profiles exist, ask:

```
Which ThoughtSpot profile would you like to use?

  1. {name}  —  {base_url}
  2. {name}  —  {base_url}

Enter number:
```

If exactly one profile exists, show it and ask the user to confirm.

Authenticate:

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

If the command fails, refer to
[ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) for
the token refresh procedure.

Save `{base_url}` (strip trailing slash), `{profile_name}`, and `{verify_ssl}` (from
the profile JSON, default `true`) for all subsequent steps.

---

## Step 2 — Select Operation

Ask:

```
What would you like to do with ts_user_timezone?

  1  Search — view current timezone values set for ts_user_timezone
  2  Set    — set (or overwrite) a timezone value for an org or user
  3  Remove — remove the timezone value for an org or user

Enter 1, 2, or 3:
```

Map selections:
- 1 → `{operation}` = `"search"` → go to [Search Flow](#search-flow)
- 2 → `{operation}` = `"set"` (POST with `assigned_values` populated)
- 3 → `{operation}` = `"remove"` (POST with `assigned_values` as empty list `[]`)

Note: the update endpoint (`update-values`) is a POST that upserts — there is no separate
`operation` field in the request body. "Set" always adds or replaces; "remove" clears
the value by sending an empty `assigned_values` list.

Save `{operation}`. If `{operation}` is `"search"`, skip to [Search Flow](#search-flow).
Otherwise continue with Step 3.

---

## Search Flow

Call the variables search API and display all current assignments for `ts_user_timezone`:

```bash
source ~/.zshenv && curl -sk -X POST \
  "{base_url}/api/rest/2.0/template/variables/search" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(ts auth token --profile {profile_name})" \
  --data-raw '{
    "record_offset": 0,
    "record_size": 10,
    "response_content": "METADATA_AND_VALUES",
    "variable_details": [
      { "identifier": "ts_user_timezone" }
    ]
  }'
```

Parse the JSON response and display it in a readable table. For each entry in the
`variable_values` array, show:

```
ts_user_timezone — current assignments on {base_url}

  Org               Level   Principal          Timezone
  ────────────────  ──────  ─────────────────  ──────────────────
  Primary           org     —                  Asia/Kolkata
  Primary           user    guest1             America/New_York
  ...

Total: {n} assignment(s)
```

If the response contains no `variable_values` entries, show:

```
No values are currently set for ts_user_timezone on {base_url}.
```

On API error, show the raw error message from the response.

After displaying results, stop — do not continue to Step 3.

---

## Step 3 — Collect Timezone (skip for Remove)

If `{operation}` is `"remove"`, skip this step — no timezone value needed.

Ask:

```
Timezone value (IANA format, e.g. Asia/Kolkata, America/New_York, Europe/London):
```

Validate the format: must contain exactly one `/` and match the pattern
`Continent/City` or `Region/City` (e.g. `Asia/Kolkata`, `America/New_York`,
`Pacific/Auckland`). Common valid prefixes: `Africa`, `America`, `Antarctica`,
`Arctic`, `Asia`, `Atlantic`, `Australia`, `Europe`, `Indian`, `Pacific`, `UTC`, `Etc`.

If the format looks invalid, warn the user:

```
"{value}" does not look like a valid IANA timezone (expected format: Region/City).
Common examples: Asia/Kolkata, America/New_York, Europe/London, Australia/Sydney.

Continue anyway? (Y / N):
```

Save `{timezone_value}`.

---

## Step 4 — Collect Org

Ask:

```
Org name (e.g. Primary, or the name of another org):
```

Save as `{org_identifier}`.

---

## Step 5 — Collect User (optional)

Ask:

```
Apply to a specific user? Enter username, or press Enter to apply at org level:
```

If the user enters a value, save as `{principal_identifier}` and set `{level}` to `"user"`.
If the user presses Enter (empty), leave `{principal_identifier}` unset and set `{level}` to `"org"`.

---

## Step 6 — Confirm

Show a summary before making any changes:

```
Ready to update ts_user_timezone:

  Operation:  {operation}
  Timezone:   {timezone_value}   ← omitted if operation is remove
  Org:        {org_identifier}
  Level:      {level} level{" — user: " + principal_identifier if level == "user" else ""}

  Cluster:    {base_url}

Proceed? (Y / N):
```

If N, ask what to change and return to the relevant step.

---

## Step 7 — Call the API

Build the request body:

```python
import json, subprocess

# Build variable_assignment entry
assignment = {
    "operation": "{operation}",
    "org_identifier": "{org_identifier}",
    "principal_type": "USER",
}

# Set: populate assigned_values; Remove: send empty list to clear
if "{operation}" == "set":
    assignment["assigned_values"] = ["{timezone_value}"]
else:
    assignment["assigned_values"] = []

# Only include principal_identifier for user-level assignments
if "{level}" == "user":
    assignment["principal_identifier"] = "{principal_identifier}"

body = json.dumps({"variable_assignment": [assignment]})
```

Get the bearer token:

```bash
source ~/.zshenv && ts auth token --profile "{profile_name}"
```

Save the token as `{bearer_token}`.

Make the API call:

```python
import subprocess, json

verify_flag = "" if {verify_ssl} else "-k"

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && curl -s {verify_flag} -X POST "
     f"'{base_url}/api/rest/2.0/template/variables/ts_user_timezone/update-values' "
     f"-H 'Content-Type: application/json' "
     f"-H 'Authorization: Bearer $(ts auth token --profile {profile_name})' "
     f"--data-raw '{body}'"],
    capture_output=True, text=True
)

raw = result.stdout.strip()
```

Parse the response:
- Empty response body → success (the API returns HTTP 204 on success with no body)
- JSON with `error` key → extract and display the error message
- Any other response → show raw output

---

## Step 8 — Report Result

**On success (empty body):**

```
ts_user_timezone updated.

  Operation:  {operation}
  Timezone:   {timezone_value}   ← omitted if operation is remove
  Org:        {org_identifier}
  Applied at: {level} level{" — user: " + principal_identifier if level == "user" else ""}

  Cluster:    {base_url}
```

**On error:**

```
API call failed.

  Error: {error_message}

Common causes:
  - Timezone value is not recognised by ThoughtSpot (check IANA spelling)
  - Username does not exist in the specified org
  - Org name is incorrect (check exact capitalisation)
  - ts_user_timezone variable does not exist on this cluster
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts auth whoami` returns 401 | Token expired — follow refresh steps in `/ts-profile-thoughtspot` |
| `SSLCertVerificationError` | Set `"verify_ssl": false` in `~/.claude/thoughtspot-profiles.json` for this profile |
| API returns 404 on the variable endpoint | `ts_user_timezone` variable may not exist on this cluster — ask admin to create it |
| API returns 400 with `variable_assignment` error | Request body is malformed — check that `operation` and `assigned_values` are set correctly |
| Timezone not applied after update | Token may be stale in the ThoughtSpot session — ask the user to log out and back in |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-04-27 | Initial release — search, set, and remove timezone values for `ts_user_timezone` |
