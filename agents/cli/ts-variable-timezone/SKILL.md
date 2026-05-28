---
name: ts-variable-timezone
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
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |

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
[ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) for
the token refresh procedure.

Save `{base_url}` (strip trailing slash) and `{profile_name}` for display in confirmation
and result summaries. The `ts` CLI handles auth and SSL internally — no need to track
`{verify_ssl}` or manage bearer tokens.

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
- 2 → `{operation}` = `"set"` (API operation: `REPLACE`)
- 3 → `{operation}` = `"remove"` (API operation: `REMOVE` — skill will look up current value)

Save `{operation}`. If `{operation}` is `"search"`, skip to [Search Flow](#search-flow).
Otherwise continue with Step 3.

---

## Search Flow

```bash
source ~/.zshenv && ts variables search ts_user_timezone --profile "{profile_name}"
```

Parse the JSON response. The response is an array; the first element's `values` array
holds the assignments. Display in a readable table:

```
ts_user_timezone — current assignments on {base_url}

  Org               Level   Principal          Timezone
  ────────────────  ──────  ─────────────────  ──────────────────
  Primary           org     —                  Asia/Kolkata
  Primary           user    guest1             America/New_York
  ...

Total: {n} assignment(s)
```

Level is `"user"` when `principal_type == "USER"`, otherwise `"org"`.
Principal shows `principal_identifier` for user-level rows, `—` for org-level.

If the response's `values` array is empty, show:

```
No values are currently set for ts_user_timezone on {base_url}.
```

On API error, show the raw error message from the response.

After displaying results, stop — do not continue to Step 3.

---

## Step 3 — Collect Timezone (skip for Remove)

If `{operation}` is `"remove"`, skip this step — the current value will be looked up
automatically in Step 7 before the API call.

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

## Step 4 — Collect Org(s)

Fetch all active orgs:

```bash
source ~/.zshenv && ts orgs search --status ACTIVE --profile "{profile_name}"
```

Parse the JSON array. Each element has an `orgName` field. Save all names as
`{available_orgs}`.

**If 20 or fewer orgs** — show a numbered checklist:

```
Which org(s) should this apply to? Enter numbers separated by commas (e.g. 1, 3):

  1  Primary
  2  Sales
  3  Engineering
  ...
```

Parse input as comma-separated numbers. Save selected names as `{org_identifiers}`.

**If more than 20 orgs** — ask by name instead:

```
{n} orgs found. Enter org name(s), comma-separated (exact match required):
e.g. Primary, Sales, Engineering
```

Validate each name against `{available_orgs}`. For any name not found, show:
```
Org "{name}" not found. Available orgs containing "{name}":
  - {close match 1}
  - {close match 2}
```
Re-ask until all names are valid. Save as `{org_identifiers}`.

---

## Step 5 — Collect User (optional)

Ask:

```
Apply to:

  1  Org level          — applies to all users in the org(s)
  2  Specific user(s)   — search by name or email
  3  Users in a group   — find users via group membership

Enter 1, 2, or 3:
```

If 1: set `{level}` to `"org"`, leave `{principal_identifiers}` empty.

### If 2 — Specific user(s)

Ask: `Search for user (name or email pattern):` Save as `{user_search_term}`.

```bash
source ~/.zshenv && ts users search \
  --name "{user_search_term}" \
  $(printf -- '--org "%s" ' {org_identifiers}) \
  --account-status ACTIVE \
  --profile "{profile_name}"
```

Display results as a numbered list: `# | Display Name | Username (email)`.

- If 0 results: report "No users found matching '{user_search_term}'" and re-ask.
- If results: user picks by number(s), comma-separated. Save selected `name` values as
  `{principal_identifiers}`. Set `{level}` = `"user"`.

### If 3 — Users in a group

Ask: `Search for group (name pattern):` Save as `{group_search_term}`.

```bash
source ~/.zshenv && ts users groups \
  --name "{group_search_term}" \
  $(printf -- '--org "%s" ' {org_identifiers}) \
  --include-users \
  --profile "{profile_name}"
```

Show matching groups as a numbered list: `# | Group Name | User count`. User picks one group.

Then show the users in that group (from the `users` array in the response):

```
Users in "{group_name}":

  1  user@example.com
  2  another@example.com
  ...

Apply to all {n} users? (Y) or enter numbers to pick specific ones:
```

Save selected `name` values as `{principal_identifiers}`. Set `{level}` = `"user"`.

---

## Step 6 — Confirm

Show a summary before making any changes:

```
Ready to update ts_user_timezone:

  Operation:  {operation}
  Timezone:   {timezone_value}   ← omitted if operation is remove
  Orgs:       {org_identifiers joined with ", "}
  Level:      {level} level{" — users: " + ", ".join(principal_identifiers) if level == "user" else ""}

  Cluster:    {base_url}

Proceed? (Y / N):
```

If N, ask what to change and return to the relevant step.

---

## Step 7 — Call the API

### For Set

Build the `ts variables set` command with one `--org` flag per org, and one `--user` flag
per user (if user-level). The CLI builds the cross-product internally:

```bash
source ~/.zshenv && ts variables set ts_user_timezone "{timezone_value}" \
  --org "{org1}" [--org "{org2}" ...] \
  [--user "{user1}" [--user "{user2}" ...]] \
  --profile "{profile_name}"
```

### For Remove: look up current value first

```python
import subprocess, json

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts variables search ts_user_timezone --profile '{profile_name}'"],
    capture_output=True, text=True,
)
data = json.loads(result.stdout)
all_values = data[0].get("values", []) if data else []

current_value = None
for v in all_values:
    if "{level}" == "user":
        if v.get("principal_type") == "USER" and v.get("org_identifier") in {org_identifiers}:
            current_value = v["value"]
            break
    else:
        if v.get("principal_type") is None and v.get("org_identifier") in {org_identifiers}:
            current_value = v["value"]
            break
```

If `current_value` is `None`, report that no assignment exists for any selected org and stop.

Then remove:

```bash
source ~/.zshenv && ts variables remove ts_user_timezone "{current_value}" \
  --org "{org1}" [--org "{org2}" ...] \
  [--user "{user1}" [--user "{user2}" ...]] \
  --profile "{profile_name}"
```

### Interpreting the response

- No output → success (HTTP 204)
- JSON with `error` key → extract and display the error message

---

## Step 8 — Report Result

**On success (no output):**

```
ts_user_timezone updated.

  Operation:  {operation}
  Timezone:   {timezone_value}   ← omitted if operation is remove
  Orgs:       {org_identifiers joined with ", "}
  Applied at: {level} level{" — users: " + ", ".join(principal_identifiers) if level == "user" else ""}

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
| API returns 400 with `variable_assignment` error | Request body is malformed — check that `operation` (REPLACE/REMOVE) and `variable_values` are set correctly |
| Timezone not applied after update | Token may be stale in the ThoughtSpot session — ask the user to log out and back in |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 2.0.0 | 2026-05-11 | Refactor to use `ts` CLI commands: `ts variables search/set/remove`, `ts orgs search`, `ts users search`, `ts users groups` — removes all curl boilerplate |
| 1.5.0 | 2026-05-11 | Step 5: user search (by name/email) and group-based user selection; multi-user scope support |
| 1.4.0 | 2026-05-11 | Step 4: adaptive UX — numbered checklist for ≤20 orgs, name entry with validation for >20 |
| 1.3.0 | 2026-05-11 | Step 4: fetch org list from API and present numbered checklist; support multiple orgs in one call |
| 1.2.0 | 2026-05-11 | Step 5: replace "press Enter for org level" with explicit 1/2 menu (Enter doesn't work in Claude Code chat) |
| 1.1.0 | 2026-05-11 | Fix API endpoint and schema: use global `/update-values` with `variable_values`/`operation` fields; fix Remove to look up current value before calling REMOVE |
| 1.0.0 | 2026-04-27 | Initial release — search, set, and remove timezone values for `ts_user_timezone` |
