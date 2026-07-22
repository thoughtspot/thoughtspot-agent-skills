# Profile Select and Authenticate — Shared Reference

Canonical flow for conversion skills (and any other skill) that need to
select a profile and verify connectivity before proceeding. Use this instead
of hand-coding profile JSON reads or bare `ts auth whoami` calls.

## ThoughtSpot profile

1. Run `ts profiles list --json` and parse the output.
2. If zero profiles: tell the user to run `/ts-profile-thoughtspot` first and stop.
3. If one profile: display it and confirm before proceeding.
4. If multiple profiles: display a numbered list and ask the user to select one.
5. Verify: `ts auth whoami --profile {name}` — print the display_name and base URL.
6. If verification fails: suggest the user run `/ts-profile-thoughtspot` to
   refresh their credential.

## Snowflake profile

1. Run `ts profiles list --snowflake --json` and parse the output.
2. Same selection logic as ThoughtSpot (zero/one/multiple).
3. Verify connectivity using the method from the profile:
   - `method: python` → test with `ts snowflake exec --sf-profile {name} -q "SELECT 1"`
   - `method: cli` → test with `snow sql -q "SELECT 1" -c {cli_connection}`

## Databricks profile

1. Run `ts profiles list --databricks --json` and parse the output.
2. Same selection logic as ThoughtSpot (zero/one/multiple).
3. Extract `dbx_profile` from the selected profile.
4. Verify: `databricks auth describe --profile {dbx_profile}`

## Tableau profile

1. Run `ts profiles list --tableau --json` and parse the output.
2. Same selection logic as ThoughtSpot (zero/one/multiple).
3. Verify: `ts tableau signin --profile {name}` — check for success.

## When both platforms are needed

Some skills (conversion skills) need both a ThoughtSpot profile and a
source-platform profile. Run both selection flows above, in order. Store
both profile names for use in subsequent steps. If the user has already
selected profiles earlier in the session (e.g. for a previous conversion),
skip this step and reuse them — ask the user to confirm.
