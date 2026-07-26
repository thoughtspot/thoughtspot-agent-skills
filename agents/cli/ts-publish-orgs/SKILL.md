---
name: ts-publish-orgs
description: Publish ThoughtSpot Tables, Models, Answers and Liveboards from the Primary Org to target Orgs without copying them — defining the template variables and metadata parameterization that publishing requires — via the `ts publish export/resolve/apply/verify/rollback` CLI pipeline.
---

# ThoughtSpot: Publish Objects to Orgs

Orgs Publishing keeps **one** object in the Primary Org and makes it visible in target
Orgs. There is no copy, no new GUID, and no GUID mapping. Per-tenant variation comes
entirely from **template variables** substituted at runtime.

This skill drives the `ts publish` pipeline (`export` → `resolve` → `apply` → `verify`,
with `rollback` to undo) and the variable work publishing depends on.

**The thing to understand before starting:** variable definition is not a preliminary to
publishing, it *is* the work. An object with no variable in its dependency tree cannot be
published at all.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [tools/ts-cli/README.md](../../../tools/ts-cli/README.md) (`ts publish` + `ts variables` sections) | Full flag reference for every command used here |
| [references/open-items.md](references/open-items.md) | Unverified behaviour and its status |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |
| [ts-profile-snowflake (Claude Code)](../../claude/ts-profile-snowflake/SKILL.md) | Snowflake profile — needed only for `--source db` |

---

## Prerequisites

- `ts` CLI installed and on PATH, version **0.107.0+**
- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- **Orgs enabled** on the instance, and you are signed in to the **Primary Org**
- Your account holds `ADMINISTRATION` with access to all Orgs. Publishing is refused otherwise
- Orgs Publishing is **Early Access**. Confirm with a ThoughtSpot admin that it is enabled
  before starting
- Optional: Snowflake profile (`/ts-profile-snowflake`) — only for `--source db`

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-publish-orgs** — publish Tables, Models, Answers and Liveboards from the Primary Org
to target Orgs, wiring the variables that per-tenant values need.

Steps:
  1.  Authenticate ..................................... auto
  2.  Select objects to publish ........................ you choose
  3.  Discover the closure ............................. auto
  4.  Review the variables to create ................... you confirm (may edit)
  5.  Select target Orgs ............................... you choose
  6.  Choose the value source .......................... you choose
  7.  Resolve the per-Org value matrix ................. auto
  8.  Review the matrix + coverage ..................... you confirm (may edit)
  9.  Dry-run the plan ................................. auto
 10.  Apply and publish ................................ you confirm (checkpoint)
 11.  Verify ........................................... auto

Confirmation required: Steps 2, 4, 5, 6, 8, and the checkpoint in Step 10
Auto-executed: Steps 1, 3, 7, 9, 11
Reversible: a rollback record is written before anything changes

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If missing or empty, prompt the user to run
`/ts-profile-thoughtspot` first.

If multiple profiles exist, ask which to use. If exactly one exists, show it and confirm.

```bash
ts auth whoami --profile "{profile_name}"
```

Confirm from the response that `current_org` is the **Primary Org** and that `privileges`
includes `ADMINISTRATION`. If either is wrong, stop and explain: publishing runs only from
the Primary Org, by an administrator with all-Orgs access.

Save `{profile_name}` for all subsequent steps.

---

## Step 2 — Select Objects

Ask how the user wants to choose what to publish:

```
What would you like to publish?

  1  Search by name/pattern
  2  I already have the GUID(s)
  3  A manifest (CSV file or Snowflake table)

Enter 1, 2, or 3:
```

**By name/pattern** — search each relevant type and show a numbered list with
`{name}` — `{guid}` — `{owner}` — `{modified}`:

```bash
ts metadata search --subtype WORKSHEET --name "%{pattern}%" --profile "{profile_name}"
ts metadata search --type LIVEBOARD --name "%{pattern}%" --profile "{profile_name}"
ts metadata search --type ANSWER --name "%{pattern}%" --profile "{profile_name}"
```

**By manifest** — confirm the CSV path or the fully-qualified Snowflake table. Columns are
`identifier, type, with_dependents`. If the user does not have the table yet, offer the DDL:

```bash
ts publish resolve --init-table
```

Then ask about the upward walk:

```
Publishing cascades DOWN to dependencies automatically, but never UP to siblings.
An Answer sitting beside a Liveboard on the same Model needs publishing in its own right.

Include everything riding on your selection? (Y / N):
```

Save the selection as `{guids}` (or `{manifest}`) and the answer as `{with_dependents}`.

---

## Step 3 — Discover the Closure

```bash
ts publish export {guids} [--with-dependents] --profile "{profile_name}"
# or, from a manifest:
ts publish export --objects-file "{csv_path}" --profile "{profile_name}"
ts publish export --objects-table "{table}" --sf-profile "{sf_profile}" --profile "{profile_name}"
```

Write the output to `/tmp/ts_publish_closure.json`.

This walks each object down to the Tables that need variables and groups their
`db` / `schema` / `db_table` values by **distinct value**. Each cluster is one variable,
because a variable holds one value per scope: twenty tables sharing a schema need one
variable, not twenty.

**Two blockers to check before going further.**

If `cohort_columns` is non-empty, stop:

```
"{model_name}" has cohort column(s) {names}.

Cohort publishing is not supported, and the block is Model-wide: it stops the Model
and every Answer or Liveboard built on it, whether or not they use the column.
Delete the cohort column from the Model to publish. Tables below it are unaffected.
```

If `unparameterizable_tables` is non-empty, those are Falcon-backed and cannot be
parameterized or published. Report them and confirm whether to continue with the rest.

---

## Step 4 — Review the Variables

Present the clusters for review:

| Field | Current value | Tables | Variable | Recommended |
|---|---|---|---|---|

Show `already_parameterized` clusters separately — they are already wired and need no new
variable. This is what makes the skill safe to re-run when adding a tenant.

`recommended` covers `databaseName` and `schemaName`, the conventional per-tenant
discriminators. `tableName` is offered but not recommended, because tenant tables normally
share a name.

Ask:

```
Create these variables? (Y / N / choose different fields):
```

To widen or narrow, re-run Step 7 with `--field`.

---

## Step 5 — Select Target Orgs

```bash
ts orgs search --profile "{profile_name}"
```

Show the Orgs and let the user pick. Save as `{orgs}`.

Note for the user, so the behaviour is not a surprise: the **owner Org (Primary) is always
included automatically**, pinned to each field's current value. Parameterizing swaps the
static database and schema for tokens, so without a value there the source object breaks.
Publishing must never change what Primary reads.

---

## Step 6 — Choose the Value Source

```
Where do the per-Org values come from?

  1  Uniform   — the current value, in every org (all tenants share one table)
  2  Pattern   — a template per field, e.g. schemaName={ORG_UPPER}
  3  File      — a CSV of org_name,variable_name,value
  4  DB table  — a Snowflake governance table with those columns
  5  Existing  — values already assigned on this instance

Enter 1-5:
```

Save as `{source}` plus its argument. For **Pattern**, collect `field=template` pairs;
placeholders are `{ORG}`, `{ORG_UPPER}`, `{ORG_LOWER}`, `{ORG_ID}`, `{VALUE}`. For **DB
table**, confirm the Snowflake profile and fully-qualified table.

**Never accept a secret here.** If any variable is a credential (`user`, `password`), it is
created with `is_sensitive: true` and the user assigns its value from their own terminal.
Do not read secrets from the config file and do not echo them. See
`.claude/rules/security.md`.

---

## Step 7 — Resolve the Value Matrix

```bash
ts publish export ... \
  | ts publish resolve --org {org} [--org {org}] --source {source} \
      [--pattern "field=template"] [--csv "{path}"] \
      [--table "{table}" --sf-profile "{sf_profile}"] \
      [--field {field}] --profile "{profile_name}"
```

Write the output to `/tmp/ts_publish_matrix.json`.

---

## Step 8 — Review the Matrix

Present the assignments:

| Variable | Org | Value |
|---|---|---|

Mask the value of any variable marked sensitive.

If `coverage.complete` is false, list the gaps and stop. Publishing would be refused anyway,
and a partial apply is worse than none:

```
Coverage gap: variable '{variable}' has no value for org '{org}'.
```

Ask:

```
Do these values look correct? (Y / N / edit):
```

To edit, change `/tmp/ts_publish_matrix.json` directly and continue.

---

## Step 9 — Dry-Run the Plan

```bash
ts publish apply -c /tmp/ts_publish_closure.json -m /tmp/ts_publish_matrix.json \
  --publish-to {org} [--publish-to {org}] --dry-run --profile "{profile_name}"
```

Show the ordered plan: variables to create, values to assign, fields to parameterize, and
which objects publish to which Orgs. Nothing has changed at this point.

---

## Step 10 — Apply and Publish

**Checkpoint** — confirm before the first mutation:

```
Ready to publish:

  Objects:    {n} ({types})
  Target orgs: {orgs}
  Variables:   {n} to create, {n} reused
  Fields:      {n} to parameterize
  Rollback:    /tmp/ts_publish_rollback.json

Proceed? (Y / N):
```

If Y:

```bash
ts publish apply -c /tmp/ts_publish_closure.json -m /tmp/ts_publish_matrix.json \
  --publish-to {org} [--publish-to {org}] \
  --rollback-out /tmp/ts_publish_rollback.json --profile "{profile_name}"
```

Always pass `--rollback-out`. `unparameterize` substitutes a static value rather than
clearing the field, so the original values must be recorded or there is no way back.

Relay the progress lines (`created variable ...`, `assigned n value(s)`,
`parameterized n field(s)`, `published n {TYPE} to {orgs}`) as they arrive.

Never pass `--skip-validation`. It disables every check, not just the variable one, and lets
an unparameterized object publish so the target Org silently reads the Primary Org's
database. When every Org shares one table, use `--source uniform` instead.

---

## Step 11 — Verify

```bash
ts publish status {guids} --profile "{profile_name}"
```

Confirm each object's `published_to` contains every target Org. This reads
`metadata_header.orgIds` from the Primary Org, so it needs no per-Org authentication.

Then confirm the **source** Org is still healthy, which is the regression the owner-Org
protection exists to prevent:

```bash
ts tml export {table_guid} --profile "{profile_name}"
```

The `db` and `schema` should show `${variable}` tokens, and the variables should hold a
Primary value.

```
Publication summary:

  {n} of {n} objects published to {orgs}.
  Primary Org unchanged and still resolving.
```

---

## Rollback

To undo a publication:

```bash
ts publish rollback -i /tmp/ts_publish_rollback.json --profile "{profile_name}"
```

This unpublishes (retracting the Connection grant too), restores each field's static value,
and deletes only the variables that run created.

**Retraction order matters when siblings share a Model.** An Answer and a Liveboard on one
Model each block the other, so `include_dependencies: true` fails with `code 13152`. Retract
the siblings first with `--keep-dependencies`, then the Model, which cascades:

```bash
ts publish unpush {liveboard} --type LIVEBOARD --org {org} --keep-dependencies --profile "{profile_name}"
ts publish unpush {answer} --type ANSWER --org {org} --keep-dependencies --profile "{profile_name}"
ts publish unpush {model} --org {org} --profile "{profile_name}"
```

---

## Unattended runs

The same pipeline runs headless for a scheduled deployment:

```bash
ts publish run --org {org} \
  --objects-table DB.SCH.TS_PUBLISH_OBJECTS \
  --values-table  DB.SCH.TS_PUBLISH_VARIABLES \
  --sf-profile {sf_profile} --rollback-out rb.json --profile "{profile_name}"
```

Same engine, no prompts, exit `1` on any refusal. It stops before touching the instance on a
coverage gap or a cohort column. Use it for cron; use the steps above when a human is
reviewing.

---

## Cleanup

```bash
rm -f /tmp/ts_publish_closure.json /tmp/ts_publish_matrix.json
```

Keep `/tmp/ts_publish_rollback.json` until the publication is confirmed good. It is the only
record of the original static values.

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts publish export` reports `cohort_columns` | Stop. A cohort column on a Model blocks the Model and everything on it, used or not. Delete the column from the Model, or publish only Tables below it |
| `ts publish export` reports `unparameterizable_tables` | Falcon-backed tables cannot be parameterized or published. Exclude them; publish the CDW-backed objects |
| `resolve` reports a coverage gap | Assign the missing value (`ts variables set {var} {value} --org {org}`) and re-run, or pick a source that supplies it. Do not proceed |
| `apply` refuses with "coverage gaps" | Same cause; the matrix was stale. Re-run Step 7 |
| Publish: `Variable ... has no value for org(s) ...` | The CLI names the variable and Org and prints the `ts variables set` command to run |
| Publish: `Object ... is not parameterized` | Bind a variable first. Even when every Org shares one table, use a variable with the same value in each rather than `--skip-validation` |
| Publish: `cohort column ... is defined on the Model` | As above. This is a platform limitation, not a configuration problem |
| Publish: `Org '...' does not exist` | The CLI lists the known Orgs. Re-run Step 5 |
| Unpublish: `code 13152 ... dependents present` | Siblings share the Model. Retract them with `--keep-dependencies` first, then the Model (see Rollback) |
| `ts variables create` fails with `Duplicate template variable name` | Names are unique **instance-wide**, not per Org. `ts variables search` to find the existing one, then reuse it via `--source existing` |
| `ts variables delete` fails with "dependent objects" | The variable is still bound. `ts metadata unparameterize` the fields first |
| Source Org queries fail with `Object '...' does not exist` after publishing | The owner Org has no value for a variable. Assign one; the skill includes Primary automatically, so this indicates a hand-edited matrix |
| `parameterize-fields` returns 500 `NullPointerException` | The target is a Falcon-backed table. See `references/open-items.md` #2 |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-26 | Initial release |
