---
name: ts-convert-to-dbt
description: Generate a dbt project (models + schema.yml) from a ThoughtSpot Table/Model TML. Use when ThoughtSpot is the source and the goal is dbt project files — a new dbt project scaffolded from a Model's tables, joins, and column properties, tagged with ThoughtSpot's own ts_* metadata so a later sync back into ThoughtSpot preserves them. Direction is always ThoughtSpot → dbt. Not for dbt → ThoughtSpot (see ts-convert-from-dbt). Reads the Model via `ts tml export`, then generates or updates the dbt project files offline (Case A new project; Case B diff + sync into an existing project, optionally updating ts_* tags and descriptions on existing models); optionally commits/pushes and triggers a dbt Cloud job. It does not import anything into ThoughtSpot — that return leg is ts-convert-from-dbt.
---

# ThoughtSpot → dbt

Generate a new dbt project from a ThoughtSpot Model TML: one staging `.sql`
model per physical table (plus a thin passthrough model for each role-play
alias), a `sources.yml`, and two complementary YAML artifacts that carry the
Model's column properties and joins forward using ThoughtSpot's own dbt
integration mechanisms — `models/schema.yml` (ThoughtSpot's `ts_*` metadata
tags under `meta:`, the primary artifact) and, behind `--semantic-models`,
`models/semantic_models.yml` (the legacy MetricFlow spec — opt-in because it
breaks `dbt parse` under dbt-core without a time spine model).

This is an **offline file transform** — the underlying `ts dbt-export build`
command reads locally exported TML JSON and writes files; it uses no
ThoughtSpot connection, dbt connection, or warehouse credentials, and it does
not run `dbt`. It is the reverse of `ts-convert-from-dbt`, which drives
ThoughtSpot's *native* server-side dbt integration — that skill is where the
generated project actually goes back into ThoughtSpot once you have run it
through dbt (see Step 9).

**Two modes.** Case A scaffolds a brand-new dbt project (Steps 4-6 below).
Case B updates a dbt project that already exists for this Model (e.g. it was
originally synced in via `ts-convert-from-dbt`, or you already ran this skill
once before). By default it only adds new tables and reports everything
else for manual review; with `--update-metadata` it also writes `ts_*` tag,
description and relationship changes onto tables that already exist (never
deletes a table, never removes a column that carries non-`ts_*` content). See
[references/open-items.md](references/open-items.md) #4 and Step 4b/6b below.
Live-verified end-to-end 2026-09-09 (open-items #14).
Case B's diffing covers `models/schema.yml` only, not
`models/semantic_models.yml` — see the same open item.

**Formula (calculated) columns are emitted as `ts_formula` in `schema.yml`.**
Each formula column is placed under the first `[TABLE::COL]` reference found in
its expression (using `_first_table_ref`). Formula columns whose expression
contains no `[TABLE::COL]` reference are skipped and reported. On resync via
`ts-convert-from-dbt` Path Y (`ts dbt-export build-model --schema-yml`), the
`ts_formula` value is restored verbatim to the assembled Model TML.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single multi-question prompt to cut round-trips — e.g. project name + source name
+ output directory. Case A vs Case B is dependent: it decides which questions follow,
so ask it alone.

---

## References

| File | Purpose |
|---|---|
| [references/concept-mapping.md](references/concept-mapping.md) | ThoughtSpot construct → dbt construct mapping |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Per-construct support status |
| [references/open-items.md](references/open-items.md) | Unverified behaviour — dbt-core compatibility gap, live-import verification gaps |
| [../ts-convert-from-dbt/SKILL.md](../ts-convert-from-dbt/SKILL.md) | The reverse direction — use it to actually sync this project's compiled output back into ThoughtSpot |
| [../ts-convert-from-dbt/references/open-items.md](../ts-convert-from-dbt/references/open-items.md) | #9 — the same `ts_*` tag YAML-syntax-vs-dbt-core-version gap, from the reading side |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| `tools/ts-cli/README.md` "`ts dbt-export`" section | Full command reference — `build` (Case A), `diff`/`sync` (Case B), `build-model` (`schema.yml` → a unified Model TML) |
| `tools/ts-cli/README.md` "`ts columns impact`" section | The pre-deletion dependency gate used in Step 6b |

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- Read access to the target Model (`DEVELOPER` privilege or equivalent)
- Authentication configured — run `/ts-profile-thoughtspot` if you haven't already
- The `ts` CLI installed (`pip install -e /path/to/tools/ts-cli`), **v0.133.0+** —
  the release that introduced `ts dbt-export` and the `ts columns impact`
  pre-deletion gate used in Step 6b

### dbt — not needed to run this skill

Generating the project needs no dbt install, no warehouse credentials, and no
dbt Cloud token — it's a pure file transform from already-exported TML JSON.
You only need dbt once you want to actually *use* the generated project:

- A working dbt installation (dbt Core or dbt Fusion) pointed at the same
  warehouse/schema the Model's tables live in — to compile and run it, **or**
- A dbt Cloud project you can commit the generated files into

Which one you need depends on how (or whether) you plan to sync the result
back into ThoughtSpot — see Step 9.

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-to-dbt** — generate a dbt project from a ThoughtSpot Model
(new project, or add new tables to one that already exists).

Steps:
  1.   Authenticate ThoughtSpot ............................ auto
  2.   Find and select the Model ........................... you choose
  3.   Export Model + Table TML ............................ auto
  3b.  New project or update existing? ..................... you choose
  4.   Choose dbt project parameters (Case A) .............. you choose
  4b.  Point at the existing project (Case B) .............. you choose
  5.   Checkpoint — confirm before generating (Case A) ...... you confirm
  6.   Generate the dbt project (`ts dbt-export build`) ..... auto (Case A)
  6b.  Diff + sync into the existing project (Case B) ....... auto, you review
  7.   Review diagnostics .................................... auto
  8a.  Commit + push generated files ......................... you choose
  8b.  Trigger dbt Cloud job (DBT_CLOUD only) ................ you choose
  9.   Hand-off guidance (getting it back into ThoughtSpot) .. auto

Confirmation required: Steps 3b, 4, 4b, 5, 6b, 8a, 8b
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Workflow

### Step 1: Authenticate

Run `ts profiles list` to show configured ThoughtSpot profiles.
- Multiple profiles: display a numbered list and ask the user to select one.
- Exactly one profile: display it and confirm before proceeding.

Verify: `ts auth whoami --profile {profile}` — print `display_name` and base URL.

---

### Step 2: Find and select the Model

```
How would you like to find your Model?
  G — I have a GUID
  S — Search (by name, author, tags, or a combination)
  B — Browse all
```

**G:** store the GUID as `{model_guid}` directly; confirm the name after export.

**S:**
```bash
ts metadata search --profile {profile} --subtype WORKSHEET --name "%{keyword}%" --all
```
Omit `--name` if no keyword was given. `--subtype WORKSHEET` covers both
Worksheets and Models — there is no separate `MODEL` subtype (see the
Terminology note in [../ts-convert-from-dbt/SKILL.md](../ts-convert-from-dbt/SKILL.md)).
If zero results, retry without `--name` and filter client-side.

**B:**
```bash
ts metadata search --profile {profile} --subtype WORKSHEET --all
```

Display results as a numbered list; store the selection's `metadata_id` as
`{model_guid}`.

---

### Step 3: Export Model + Table TML

`ts dbt-export build`/`diff`/`sync` read pre-split files from a directory
(`--model model.json` + `--tables-dir`), so export straight into that layout:

```bash
ts tml export {model_guid} --profile {profile} --associated --split-dir {export_dir}
```

`--associated` pulls in every Table TML the Model's `model_tables[]`
reference in the same call. `--split-dir` writes `model.json` and one
`table_<NAME>.json` per Table, and prints only a manifest —
`{split_dir, written[]}` — rather than passing the whole export array through
context to be re-emitted as files.

Check the `written` list against the Model's `model_tables[]`. If it holds
fewer `table_*.json` files than the Model lists tables, some were inaccessible
or invalid (the command names each on stderr and exits 1). **Report which are
missing before continuing** — they will be silently absent from the generated
project, and `ts dbt-export build` cannot flag it because it only sees what is
on disk.

---

### Step 3b: New project or update existing?

```
Is this Model already synced to a dbt project on disk?
  N — No, generate a new project (Case A)
  U — Yes, update that existing project (Case B)
```

**N** → continue to Step 4. **U** → skip to Step 4b.

---

### Step 4: Choose dbt project parameters (Case A)

Ask the user for:

```
dbt project name (dbt_project.yml `name:`):
dbt source name (for the generated sources.yml):
Output directory (this IS the project root — files land directly here,
not in a subdirectory). Suggest: ~/dbt-projects/{project_name}/
```

`--output-dir` is the project root, not a parent directory — `dbt_project.yml`
and `models/` are written directly inside it. If the user gives a parent
directory (e.g. `~/dbt-projects/`), clarify and append `/{project_name}/`
before running the command.

Suggest defaults derived from the Model name (`to_snake(model_name)` for the
project name; the Model's connection name, snake-cased, for the source name)
but let the user override either.

Continue to Step 5.

---

### Step 4b: Point at the existing project (Case B)

Ask the user for:

```
Path to the existing dbt project directory:
dbt project name (must match this project's dbt_project.yml `name:`):
dbt source name (must match this project's existing sources.yml):
```

The project/source names must match what's already in the project — `ts
dbt-export diff`/`sync` use them to name any BRAND-NEW source block, not to
rename anything that already exists. Skip to Step 6b.

---

### Step 5: Checkpoint (Case A)

```
About to generate a dbt project from Model "{model_name}":
  Project name:  {project_name}
  Source name:   {source_name}
  Output dir:    {output_dir}
  Tables:        {n} (from model_tables[])
  Formula columns: {n} — emitted as ts_formula in schema.yml (any without a [TABLE::COL] reference are reported as skipped)

Proceed? [Y / N]
```

Wait for confirmation before Step 6.

---

### Step 6: Generate the dbt project (Case A)

```bash
ts dbt-export build \
  --model {export_dir}/model.json --tables-dir {export_dir}/ \
  --project-name {project_name} --source-name {source_name} \
  --output-dir {output_dir}
```

This writes, per distinct physical table in the Model: one staging model
(`select * from {{ source(...) }}`), a thin passthrough model for each
role-play alias, plus `dbt_project.yml`, `models/staging/sources.yml`, and —
when the Model has any classified columns or joins — `models/schema.yml`
(primary; `ts_*` tags). `models/semantic_models.yml` (secondary; legacy
MetricFlow spec) is written only with `--semantic-models`. See
[references/concept-mapping.md](references/concept-mapping.md) for exactly
what each TML property becomes.

Print the file count from stdout (the `files_written` JSON summary field).
Continue to Step 7.

---

### Step 6b: Diff + sync into the existing project (Case B)

First, run the read-only diff so the user sees what would change before
anything is written. Ask for markdown and **show the output verbatim** —
do not re-summarise it:

```bash
ts dbt-export diff --format md \
  --model {export_dir}/model.json --tables-dir {export_dir}/ \
  --project-name {project_name} --source-name {source_name} \
  --project-dir {project_dir}
```

The report leads with a **"Needs a decision"** section — the removals that are
never applied automatically — then new tables, new source tables, and the
per-column changes on existing tables. Restating it in your own words is how a
removal gets softened or dropped; paste it.

Add `--format json` (the default) instead when you need the structured
change-set — `adopted_names`, `scoped_to`, `dbt_output_tables`, `new_tables`,
`removed_tables`, `changed_tables`, `new_source_tables`,
`removed_source_tables`. `modified_meta` lists only the tags this skill
generates — a hand-authored `ts_*` tag it cannot produce is neither reported
there nor touched by `sync` (see the `--update-metadata` note below).

**Existing model names are adopted, not renamed.** Case A names staging models
`stg_<table>`, but an existing project may use other names. `diff`/`sync` pair
each Model table with the on-disk model that either *selects from* its warehouse
table (`{{ source() }}` matched by database/schema/table) or *produces* it — when
the ThoughtSpot Tables were created by `ts-convert-from-dbt` they point at the
dbt models' output relations, so the Table's `db_table` is the model name
(`DBT_DLEE_PROD.BARBERS` ← `barbers`; reported under `dbt_output_tables`). The
adopted names drive the regenerated `.sql`/`schema.yml`/`ref()` targets, and
`removed_tables` is scoped to those models' directories (`scoped_to`). If
`adopted_names` is empty for a project you know already contains these tables,
stop and check the naming before trusting `new_tables`. **`changed_tables` covers `models/schema.yml` only — a change to
`models/semantic_models.yml` on an already-existing table is not reported at
all** (open-items.md #4).

Each `changed_tables` entry carries `new_columns`, `removed_columns`,
`modified_meta` (`ts_*` tag differences), `modified_description` (a column
description edited in ThoughtSpot — non-empty new text only; a description
cleared in ThoughtSpot is neither reported nor applied, dbt keeps its text),
`new_relationship`, `removed_relationship` and `modified_relationship`. The
markdown report renders all seven per column, so a description-only edit — a
legitimate change `--update-metadata` will write — is visible without you
having to unpack the JSON.

```
{new_tables} new table(s), {removed_tables} table(s) no longer in the Model,
{changed_tables} existing table(s) with changed ts_* tags/descriptions/relationships,
{new_source_tables} new source table(s).

Add the new table(s) to the project now? [Y / N]
Also apply the changed_tables metadata (ts_* tags, descriptions,
relationships) to existing models with --update-metadata? [Y / N]
(removed tables / removed source tables are never applied automatically —
 you'll still see them below either way, for manual review; without
 --update-metadata, changed tables are only reported too)
```

If confirmed, run the same command with `sync`:

```bash
ts dbt-export sync --format md \
  --model {export_dir}/model.json --tables-dir {export_dir}/ \
  --project-name {project_name} --source-name {source_name} \
  --project-dir {project_dir}
```

> Adding `--dry-run` to that exact command makes it return **before any write**
> — including under `--update-metadata` — and print exactly what `diff`
> printed. Both go through one renderer over one change-set, so a reviewed
> plan and an applied plan cannot differ. Use it when you have amended the
> flags since the diff and want to confirm the plan still matches, rather than
> reconstructing the equivalent `diff` invocation and hoping it agrees.

This writes ONLY the new tables' `.sql` files, appends their `schema.yml`
model blocks, and merges their `sources.yml` table entries — nothing for a
table that already existed is touched. Appending is a full YAML round-trip
that reformats the whole file and drops comments (a real, disclosed
limitation, not a bug) — tell the user to review `git diff models/schema.yml
models/staging/sources.yml` before committing. Surface `changed_tables`/
`removed_tables`/`removed_source_tables` from the output as an explicit
manual-review checklist; do not imply `sync` applied them.

To also apply `ts_*` metadata changes to existing tables (updated
descriptions, synonyms, ai_context, RLS rules, new/changed relationships),
add `--update-metadata`. This flag also auto-deletes column entries whose
content is entirely `ts_*`-originated when the column was removed from the
ThoughtSpot Model (non-`ts_*` meta keys, custom descriptions, and custom
data tests prevent auto-deletion — those are left for manual review).
Columns tagged `ts_column_exclude: yes` in `schema.yml` are deliberately absent
from the Model, so `diff` never reports them as removed/changed and `sync`
never deletes them.

**`--update-metadata` only touches the tags `ts dbt-export build` can write.**
It clears and rewrites all 13 documented column tags, the three join tags, the
ts-cli extensions (`ts_ai_context`, `ts_display_name`, `ts_formula`) and
model-level `ts_rls_rules` — the set declared as `GENERATED_COLUMN_META_KEYS` /
`GENERATED_MODEL_META_KEYS`. Every other `ts_*` key is preserved untouched,
because this generator cannot produce it and so a human must have: today that
is `ts_column_exclude` and any tag a ThoughtSpot release newer than this build
adds. Preserved tags are listed in the `preserved_meta` field of the output and
on stderr; read them out to the user so it's clear they were kept deliberately
rather than missed. (An earlier revision of this work deleted them silently — see
[references/open-items.md](references/open-items.md) #17. The four tags that
originally triggered that bug — `ts_hidden`, `ts_calendar_type`,
`ts_currency_type`, `ts_geo_config` — are themselves generated now,
so the boundary now serves forward-compatibility rather than those four.)

**Before committing auto-deleted columns:** if `--update-metadata` removed
any columns, run `ts columns impact` first to confirm nothing in ThoughtSpot
depends on them:

```bash
ts columns impact \
  --column "<display name>" --physical-col "<db col name>" \
  --model {model_guid} --table {table_guid} \
  --profile {profile}
```

A non-empty `objects` list in the JSON output means Answers, Liveboards, or
other objects still reference that column — do not delete it from the Model
until those dependents are resolved. The column was removed from `schema.yml`
because it had no non-`ts_*` content, but ThoughtSpot-side dependents are not
visible from the dbt project alone.

Skip Step 7 (that step is Case A's `build` diagnostics) and continue to
Step 8a.

---

### Step 7: Review diagnostics (Case A)

`ts dbt-export build` prints diagnostics to stderr and a JSON summary to
stdout — surface both to the user, don't just report success:

```
Generated {files_written} files in {output_dir}:
  Tables:          {tables}
  Dimensions:      {dimensions}
  Time dimensions: {time_dimensions}
  Metrics:         {metrics}

Formula columns emitted as ts_formula:
  {n} formula column(s) placed under their first [TABLE::COL] reference

Skipped (reported not dropped):
  {n} formula column(s) with no [TABLE::COL] reference — {list names}
  {n} composite-key join(s) — {list relationship names + reasons}

Unmapped properties (present on the Model, no ts_* tag emitted):
  {list property + column/join + reason}
```

If `skipped_formulas` (no table ref) or `unmapped_properties` is non-empty,
tell the user these were intentional omissions (not bugs) and point to
[references/open-items.md](references/open-items.md) #9 for unmapped properties.

---

### Step 8a: Commit and push

Ask the user whether to commit and push the generated/updated files now:

```
Would you like to commit and push the updated dbt project files now?
  Y — Yes, commit and push
  N — No, I'll do it manually

Enter Y / N:
```

**If Y:**

Stage only the generated files — do not `git add .` (could pick up secrets or unrelated changes):

```bash
git -C {output_dir} add models/schema.yml \
  models/staging/sources.yml models/staging/
# `models/semantic_models.yml` is not generated unless you passed
# --semantic-models; add it too only if it is actually there.
git -C {output_dir} status
```

Show the user the staged files. Suggest a default commit message, then ask for confirmation or a custom message:

```
Suggested commit message: "sync: update ThoughtSpot ts_* tags from Model export"
Press Enter to accept, or type a custom message:
```

Then commit and push:

```bash
git -C {output_dir} commit -m "{commit_message}"
git -C {output_dir} push
```

**If N:** Tell the user which files were written (from Step 6/6b output) and that they'll need to commit and push manually before continuing.

Continue to Step 8b.

---

### Step 8b: Trigger dbt Cloud job (DBT_CLOUD only)

This skill never asked for a connection type, so establish it here (it also
decides which branch of Step 9 applies):

```
How does ThoughtSpot read this dbt project?
  C — dbt Cloud (DBT_CLOUD) — ThoughtSpot calls the dbt Cloud API
  Z — dbt Core, manifest + catalog ZIP (ZIP_FILE) — you compile locally
  ? — Not synced to ThoughtSpot yet / don't know

Enter C / Z / ?:
```

If the project already has a ThoughtSpot dbt connection, `ts dbt list --profile
{profile}` shows its `import_type` — offer to check rather than making the user
guess. **Z** or **?** → skip to Step 9.

For **DBT_CLOUD**, ask:

```
Would you like to trigger a dbt Cloud job run now?
  Y — Yes, list jobs and trigger one
  N — No, I'll trigger it manually (or wait for the scheduled run)

Enter Y / N:
```

**If Y:**

List the project's jobs (with each job's last successful run) so the user can pick:

```bash
ts dbt trigger-job --dbt-cloud-profile {dbt_cloud_profile}
```

`{dbt_cloud_profile}` is the `ts profiles --platform dbt-cloud` profile for this
project (created in ts-convert-from-dbt Step 2 — it holds the account/project/
environment IDs and reads the token from the OS credential store; never pass a
token value). Show the returned jobs as a numbered list (`id`, `name`,
`last_successful_run`) and ask the user to select one — suggest the job that
produced the artifacts ThoughtSpot last imported.

Then trigger it and wait:

```bash
ts dbt trigger-job --dbt-cloud-profile {dbt_cloud_profile} --job-id {job_id}
```

The command polls every 15 s (progress on stderr) and prints
`{run_id, job_id, status, finished_at}` on success. On `Error`/`Cancelled` it
exits non-zero and prints the failed step's log tail on stderr — report those
lines to the user and stop; do not attempt the resync until the job is fixed.
Do not call the dbt Cloud REST API with `curl` here — the CLI owns auth and
token handling (`.claude/rules/ts-cli.md`).

**If N:** continue to Step 9.

---

### Step 9: Hand-off guidance

**Getting the result back into ThoughtSpot** branches by connection type (see
[references/open-items.md](references/open-items.md) #7):

**ZIP_FILE** (dbt Core, or a dbt-Cloud-managed repo you compile locally
— e.g. via the dbt Cloud CLI's Fusion engine):

```
Next steps:
  1. Copy/merge the generated files into your real dbt project
     (or run dbt directly against this scaffold if it's new).
  2. Run `dbt run` (or `dbt compile`) + `dbt docs generate` — this
     produces target/manifest.json + target/catalog.json.
  3. Zip those two files together.
  4. Use /ts-convert-from-dbt (Step 4, create/update) with
     --import-type ZIP_FILE --file {the zip}, then Step 8
     (generate-tml) or Step 10 (resync) to bring it into ThoughtSpot.
```

**DBT_CLOUD** (if the job run in Step 8b succeeded):

```
Next step:
  Use /ts-convert-from-dbt (Step 10, resync). For a Model built with
  `ts dbt build-model` (Path Y), that is a `--model-guid {model_guid}`
  re-run against the new job's manifest — same GUID, dependents intact;
  a zero-delta re-export confirms the round trip closed. No local
  artifact file is needed.
```

**Which return path is lossless.** Three of the tags this skill writes —
`ts_formula`, `ts_display_name`, and (pending verification) `ts_ai_context` —
are read only by `ts dbt build-model`, not by ThoughtSpot's server-side
`generate-tml`. Say so plainly when handing off:

- **`ts-convert-from-dbt` Path Y** (`--import-worksheets NONE` +
  `ts dbt build-model`) round-trips everything this skill emitted, including
  formulas, display names and `ts_rls_rules`.
- **Path N** (server-side Model generation) carries the documented `ts_*`
  column tags, `ts_join_*` and descriptions, but drops formulas and display
  names **silently** — no error, no diagnostic.

If the user's Model has formula columns, tell them Path Y is required, not
optional. See [references/open-items.md](references/open-items.md) #15.

**Note — `semantic_models.yml` is no longer emitted by default.** It made the
generated project fail `dbt parse` with "The semantic layer requires a time
spine model" whenever it carried a time dimension, and no MetricFlow time spine
model is generated (confirmed against dbt-core 1.12.4, 2026-09-10). This used to
be a caution the user had to remember when copying files; `ts dbt-export build`
now withholds the file and says so on stderr.

`--semantic-models` puts it back for anyone testing ThoughtSpot's separate
MetricFlow import (open-items #2) — the command then warns if the project would
need a time spine. The `schema.yml` (with `ts_*` tags) is all ThoughtSpot's dbt
integration needs.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-09-10 | Initial release — ThoughtSpot Model TML → dbt project. Case A scaffolds a new project (staging models aliased to their ThoughtSpot Table names so the return leg preserves identity); Case B diffs and syncs into an existing project. `ts dbt-export build-model` assembles a unified Model TML back from a project's `schema.yml`. |
