---
name: ts-object-model-alias
description: Manage column aliases on a ThoughtSpot Model — language localization, tenant-based renaming, and combined tenant + locale matrices — via the `ts alias export/translate/build/import` CLI pipeline.
---

# ThoughtSpot: Manage Column Aliases

Column aliases let a single Model show a different display name (and description) for
the same column, keyed by locale, org, and group. This skill drives the four-command
`ts alias` pipeline (`export` → `translate` → `build` → `import`) to cover three use cases:

1. **Language localization** — translate column display names/descriptions to other languages
2. **Tenant-based renaming** — map technical column names to business names per org/group
3. **Tenant + locale** — layer language translation on top of tenant-specific names

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [tools/ts-cli/README.md](../../../tools/ts-cli/README.md) (`ts alias` section) | Full flag reference for `export`/`translate`/`build`/`import` |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |
| [ts-profile-snowflake (Claude Code)](../../claude/ts-profile-snowflake/SKILL.md) | Snowflake profile — needed for `--source db`, the Cortex translator, or a `--locale-config-table` |

---

## Prerequisites

- `ts` CLI installed and on PATH, version **0.96.0+** (provides `ts alias export/translate/build/import`)
- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- Column alias export/import (`export_with_column_aliases`) is **Beta** as of ThoughtSpot
  Cloud 10.13.0.cl. Confirm with a ThoughtSpot admin that the feature is enabled on the
  target instance before starting — see Error Handling below for what an unsupported
  instance looks like.
- Optional: Snowflake profile (`/ts-profile-snowflake`) — needed for `--source db`,
  the Cortex translator, or a `--locale-config-table`
- Optional: `ANTHROPIC_API_KEY` set in the environment — needed for the Claude translator
  (the default AI backend)

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-object-model-alias** — manage column aliases on one or more ThoughtSpot Models:
language localization, tenant-based renaming, or both combined.

Steps:
  1.  Authenticate ..................................... auto
  2.  Select Model(s) .................................. you choose
  3.  Export columns + existing aliases ................ auto
  4.  Choose use case ................................... you choose
  5.  Scope aliases (locales / orgs / groups) ........... you choose
  6.  Choose source (AI, file, DB) ...................... you choose
  7.  Generate aliases .................................. auto
  8.  Review generated aliases .......................... you confirm (may edit)
  9.  Choose mode (merge / replace) ..................... you choose
 10.  Build + import ................................... auto (checkpoint before import)
 11.  Verify (re-export + compare) ...................... auto

Confirmation required: Steps 2, 4, 5, 6, 8, 9, and the pre-import checkpoint in Step 10
Auto-executed: Steps 1, 3, 7, 11

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If the file is missing or empty, prompt the
user to run `/ts-profile-thoughtspot` first.

If multiple profiles exist, ask which to use. If exactly one exists, show it and confirm.

```bash
ts auth whoami --profile "{profile_name}"
```

If the command fails, refer to
[ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) for the token
refresh procedure.

Save `{base_url}` (strip trailing slash) and `{profile_name}` for all subsequent steps.

---

## Step 2 — Select Model(s)

Ask how the user wants to find the target Model(s):

```
Which Model(s) would you like to manage column aliases for?

  1  Search by name/pattern
  2  I already have the GUID(s)
  3  All Models on a specific connection

Enter 1, 2, or 3:
```

**By name/pattern:**

```bash
ts metadata search --subtype WORKSHEET --name "%{pattern}%" --profile "{profile_name}"
```

**By connection** (client-side filter on `metadata_header.dataSourceName`):

```bash
ts metadata search --subtype WORKSHEET --connection "{connection_name}" --profile "{profile_name}"
```

**By explicit GUID(s):** skip search — use the GUID(s) directly in Step 3.

Show search results as a numbered list (`{name}` — `{guid}`) and let the user pick one or
more. Save the selected list as `{model_guids}` (with matching `{model_names}`).

---

## Step 3 — Export

For each Model in `{model_guids}`:

```bash
ts alias export --model {guid} --profile "{profile_name}"
```

This calls the TML export API with `export_options.export_with_column_aliases: true`
and returns a JSON envelope:

```
{"model": {"guid", "name", "fqn"},
 "columns": [{"name", "description", "type"}, ...],
 "existing_aliases": {"columns": [...]} | null}
```

Write the output to a temp file per model (`/tmp/ts_alias_export_{guid}.json`) — it is
reused as the base for `translate` (Step 7) and as the merge base in `build` (Step 10).

Show the user, per Model:

```
"{model_name}" — {column_count} columns

  Existing aliases: {n} entries across {locale_count} locale(s), {org_count} org(s)
  (or: "No existing column aliases — this will be a fresh set.")
```

`existing_aliases` is `null` when the Model has no aliases yet — this is normal, not an
error (see Error Handling).

---

## Step 4 — Choose Use Case

Present the three options:

```
Which use case applies?

  1  Language localization    — translate column names/descriptions to other languages
  2  Tenant renaming           — org/group-specific business names (no translation)
  3  Tenant + locale           — combine tenant names with per-org language translation

Enter 1, 2, or 3:
```

Save as `{use_case}`. This choice drives Steps 5–7.

---

## Step 5 — Scope Aliases

**Use case 1 (language localization):** ask which locales to target. Show the 27
supported locales:

```
da-DK  de-DE  de-CH  en-AU  en-CA  en-DE  en-IN  en-NZ  en-GB  en-US
es-ES  es-US  es-MX  fr-CA  fr-FR  ja-JP  ko-KR  it-IT  nb-NO  nl-NL
pt-BR  pt-PT  ru-RU  fi-FI  sv-SE  zh-CN  zh-HANT
```

Save the comma-separated selection as `{locales}`.

**Use case 2 (tenant renaming):** confirm which orgs and/or groups should receive
aliases. These come from the source file/table (Step 6), not from ThoughtSpot itself —
ask the user to describe the org/group names as they appear in their CSV or Snowflake
table so you can build the `--orgs`/`--groups` filters in Step 7.

**Use case 3 (tenant + locale):** confirm both: the org/group scope (as in use case 2)
*and* which locale(s) apply per org — either a single locale list applied to all orgs
(`--ai-locales`), or a per-org matrix (a `--locale-config` YAML file or a
`--locale-config-table` in Snowflake, shaped `{org_name: [locale_codes]}` with `*` as
the default-org fallback).

---

## Step 6 — Choose Source

**Use case 1:** AI, file, or DB.
**Use cases 2–3:** file or DB only — AI cannot invent business-specific tenant names.

Ask:

```
Where should the alias values come from?

  1  AI — generate translations from column names/descriptions   (use case 1 only)
  2  File — a CSV of aliases you already have
  3  DB — a Snowflake table of aliases

Enter 1, 2, or 3:
```

**If AI:** ask which translator:

```
Which AI backend?

  1  Claude   — requires ANTHROPIC_API_KEY in the environment
  2  Cortex   — requires a Snowflake profile (runs SNOWFLAKE.CORTEX.COMPLETE)

Enter 1 or 2:
```

Save `{translator}` (`claude` or `cortex`). For Cortex, confirm the Snowflake profile
(`{sf_profile}`) is configured (`/ts-profile-snowflake` if not).

**If File:** confirm the CSV path. Expected columns: `column_name, locale, alias,
description, org_name, group_name, model_name` (locale/org/group/model_name/description
are optional — blank locale/org/group means "applies to all"). Save `{csv_path}`.

**If DB:** confirm the Snowflake profile (`{sf_profile}`) and the fully-qualified table
name (`{table}`), e.g. `DB.SCHEMA.TS_COLUMN_ALIASES`. Same column shape as the CSV. If
the user doesn't have this table yet, offer to emit the standard DDL:

```bash
ts alias translate --init-table --sf-profile "{sf_profile}"
```

This prints `CREATE TABLE IF NOT EXISTS` for both `TS_COLUMN_ALIASES` (the alias data)
and `TS_ALIAS_LOCALES` (per-org locale config, for use case 3). Run it through
`ts snowflake exec` (or hand it to the user to run) before continuing.

**Use case 3 additionally:** confirm the locale overlay source from Step 5 — an explicit
locale list (`{ai_locales}`), a YAML file (`{locale_config_path}`), or a Snowflake table
(`{locale_config_table}`) — plus the translator to use for the overlay (same choice as
the AI-source question above).

---

## Step 7 — Generate Aliases

Run the translate command against the export envelope from Step 3, based on the
source chosen in Step 6:

```bash
# Use case 1 — AI only
ts alias export --model {guid} -p "{profile_name}" \
  | ts alias translate --source ai --locales "{locales}" --translator {translator} \
      [--sf-profile "{sf_profile}"]     # only when translator=cortex

# Use case 2 — File
ts alias export --model {guid} -p "{profile_name}" \
  | ts alias translate --source file --csv "{csv_path}" \
      [--orgs "Org 1,Org 2"] [--groups "Group 1,Group 2"] [--locales "{locales}"]

# Use case 2 — DB
ts alias export --model {guid} -p "{profile_name}" \
  | ts alias translate --source db --sf-profile "{sf_profile}" --table "{table}" \
      [--orgs "Org 1,Org 2"] [--groups "Group 1,Group 2"] [--locales "{locales}"]

# Use case 3 — File/DB + AI locale overlay (pick one overlay source)
ts alias export --model {guid} -p "{profile_name}" \
  | ts alias translate --source {file|db} [--csv "{csv_path}" | --sf-profile "{sf_profile}" --table "{table}"] \
      --ai-locales "{locales}" --translator {translator}
      # or: --locale-config "{locale_config_path}" --translator {translator}
      # or: --locale-config-table "{locale_config_table}" --sf-profile "{sf_profile}" --translator {translator}
```

Write the resulting translations envelope to `/tmp/ts_alias_translations_{guid}.json`.

A malformed AI response is retried once automatically with a stricter prompt; a second
failure raises (see Error Handling).

Show a preview of the generated aliases (see Step 8's table format) to the user before
moving on.

---

## Step 8 — Review

Present the aliases from `/tmp/ts_alias_translations_{guid}.json` (the `translations[]`
array) in a table for review:

| Column | Locale | Org | Group | Alias | Description |
|---|---|---|---|---|---|

`locale`/`org`/`group` show as `(all)` when the entry uses the wildcard scope (applies
everywhere), rather than the internal `TS_WILDCARD_ALL` sentinel.

Ask:

```
Do these aliases look correct? (Y / N / edit specific rows):
```

If the user wants to edit entries, open `/tmp/ts_alias_translations_{guid}.json`,
correct the relevant `translations[]` entries directly (or re-run Step 7 with a
narrower `--locales`/`--orgs`/`--groups` filter and merge results), save the file, and
re-pipe it through `build` in Step 10 via `--input`.

---

## Step 9 — Choose Mode

```
How should this be applied?

  1  Merge   — preserve existing aliases, only overwrite matching (column, locale, org,
               group) entries   [recommended when the Model already has aliases]
  2  Replace — fresh import, discards all existing aliases

Enter 1 or 2:
```

Recommend **Merge** whenever Step 3 showed existing aliases on the Model.

---

## Step 10 — Build + Import

Build the TML from the (possibly edited) translations file:

```bash
# Merge mode (recommended when existing aliases are present)
ts alias build --input /tmp/ts_alias_translations_{guid}.json --merge \
  > /tmp/ts_alias_{guid}.yaml

# Replace mode
ts alias build --input /tmp/ts_alias_translations_{guid}.json \
  > /tmp/ts_alias_{guid}.yaml
```

`--merge` reads `existing_aliases` from the translations envelope (carried through from
the Step 3 export) and only overwrites entries whose `(column, locale, org, group)` key
matches a new translation — everything else is preserved.

`build` reports `tml_size_bytes` on stderr, warns above 20 MB, and errors above the
25 MB platform import limit (see Error Handling).

**Checkpoint** — show the final size and mode, then confirm before importing:

```
Ready to import column aliases for "{model_name}":

  Mode:        {Merge / Replace}
  TML size:    {n} bytes
  Model:       {model_name}  ({guid})

Proceed with import? (Y / N):
```

If N, stop or loop back to an earlier step.

If Y, import:

```bash
ts alias import --model {guid} --profile "{profile_name}" --file /tmp/ts_alias_{guid}.yaml
```

If the TML is between 5 MB and 25 MB, the import runs asynchronously and the CLI polls
`.../tml/async/status` itself (15s → 60s backoff), printing `Status: {state}
({processed}/{total})` to stderr until it reaches `COMPLETED` or `FAILED` — this can
take **~10–15 minutes** for large payloads. Relay these progress lines to the user as
they arrive rather than going silent. Above 25 MB, the CLI rejects the payload before
any API call — see Error Handling.

If the user wants to validate without committing, add `--dry-run` first (uses the
`VALIDATE_ONLY` import policy) and confirm no errors before running the real import.

---

## Step 11 — Verify

Re-export and compare against what was intended:

```bash
ts alias export --model {guid} --profile "{profile_name}"
```

Build a comparison table from the new `existing_aliases` against the translations that
were just applied:

| Column | Locale | Org | Group | Expected | Actual | Status |
|---|---|---|---|---|---|---|

Status is `OK` when Actual matches Expected, `MISMATCH` otherwise. In Merge mode, also
confirm every pre-existing entry that was **not** targeted by this run is still present
unchanged.

```
Round-trip verification for "{model_name}":

  {n} of {n} aliases confirmed.
  (or: "n mismatches found — see table above.")
```

Flag any mismatches to the user and offer to re-run the build/import for just the
affected entries.

---

## Cleanup

```bash
rm -f /tmp/ts_alias_export_*.json /tmp/ts_alias_translations_*.json /tmp/ts_alias_*.yaml
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts alias export` returns `"existing_aliases": null` | Normal — the Model has no existing aliases yet; proceed with an empty base for Merge (behaves like Replace on the first run) |
| Column alias feature not enabled / 4xx mentioning `export_with_column_aliases` | Message: "Contact ThoughtSpot to enable the column alias feature (Beta, 10.13.0.cl+) on this instance" |
| Column name in CSV/DB not found in the Model | The `translate` command does not validate column existence up front — a stray name only surfaces as a no-op alias entry at review time (Step 8); flag it to the user and drop the row before `build` |
| Invalid locale code | `ts alias translate`/`build` exits with `Invalid locale(s): ...` and lists all 27 valid codes — re-enter with a corrected list |
| `--orgs` passed with `--source ai` | Rejected: "AI translation is for language localization only. Use --source file or --source db for org/group aliases." — drop `--orgs` or switch source |
| AI returns malformed JSON | Retried once automatically with a stricter prompt; a second failure raises — re-run the step, and if it fails again, try `--translator cortex` or fall back to `--source file` |
| AI returns wrong column count | Same retry-once behavior as malformed JSON — the CLI validates the response array length against the requested columns |
| `--source db` / `--source file` returns no rows | `db`: exits with `No rows in {table} for model_name=...`; `file`: silently produces zero translations (no alias/description in any matching row) — verify the CSV/table has rows for this Model's `model_name` |
| TML > 25 MB | `build` errors with guidance: reduce locale/org coverage, split across Models, or wait for 26.10 delta-load support |
| TML 20–25 MB | Warning only — proceed, but consider reducing scope |
| TML import fails | Show the raw error from `ts alias import`; suggest re-running with `--dry-run` first to isolate the failing entries |
| Cortex translator without `--sf-profile` | `translate` exits with `--sf-profile required for cortex translator` — supply one or switch to `--translator claude` |
| Claude translator without `ANTHROPIC_API_KEY` | `translate` exits with `{env_var} not set` — set the key, or pass a different `--api-key-env` |
| Async import stuck / very slow | Expected for large payloads (~10–15 min); the CLI keeps polling and backs off to 60s between checks — do not re-submit the import while a task is in flight |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-24 | Initial release |
