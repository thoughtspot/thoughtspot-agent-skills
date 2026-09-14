---
name: ts-convert-from-dbt
description: Sync dbt models into ThoughtSpot as Tables and a Model, using ThoughtSpot's native dbt integration. Use when dbt (Cloud or Core) is the source and the goal is ThoughtSpot objects generated from dbt models — either a first import or a resync after the dbt project changes. Direction is always dbt → ThoughtSpot. Not for ThoughtSpot → dbt (see ts-convert-to-dbt), and not a client-side SQL/DDL parser — Table generation happens inside ThoughtSpot's servers via the dbt connection object, and the Model either does too or is assembled from dbt's own structured metadata (ts_* tags, relationships tests, MetricFlow metrics) by `ts dbt build-model` for multi-fact projects.
---

# dbt → ThoughtSpot Tables + Model

Syncs dbt models into ThoughtSpot using ThoughtSpot's **native dbt integration**
(`POST /api/rest/2.0/dbt/*`, 9.9.0.cl+) via the `ts dbt` CLI commands. It creates
a dbt connection object, tells ThoughtSpot which dbt models (and their tables) to
bring in, and ThoughtSpot's servers generate and import the resulting Tables.
`--include-semantic-report` (Snowflake and Databricks connections only) surfaces
the per-model SQL → ThoughtSpot-formula translation ThoughtSpot performed, for
review.

**`generate-tml` always runs — it is the only thing that creates the Table
objects.** The choice in Step 8 is not "N or Y" for the whole import; it is only
about **who builds the Model on top of those Tables**:

- **Path N** (`--import-worksheets ALL`) — ThoughtSpot's servers build the Model
  too. Correct and zero extra steps when the directory has **at most one
  FK-source (fact) table** and carries none of the tags below. Joins come
  through with their `ts_join_*` cardinality and type.
- **Path Y** (`--import-worksheets NONE`, then `ts dbt build-model`) — the same
  server-side call creates the Tables, then **one unified Model TML is assembled
  client-side** from the compiled `manifest.json` + `catalog.json` and imported.

Path N emits **one Model per FK-source table** (each holding that table plus its
direct targets, dimensions duplicated), so a directory with several fact tables
becomes several overlapping Models. It also ignores `ts_column_exclude`,
`ts_display_name`, `ts_rls_rules`, `ts_formula` and MetricFlow metrics — all
measured live 2026-09-10, see [references/open-items.md](references/open-items.md) #11.
`ts dbt inspect` reports `path_n_model_count` so you know the split **before**
importing rather than after.

Unlike the Snowflake Semantic View skills, neither path parses SQL — Path Y
reads dbt's *structured* metadata (`ts_*` tags, `relationships` tests, compiled
`semantic_models`/`metrics`), not model bodies. See
[references/concept-mapping.md](references/concept-mapping.md) for which
construct is translated where.

**Terminology note:** ThoughtSpot deprecated Worksheets in favor of Models
(disabled by default 10.4.0.cl, removed 10.12.0.cl+) — "even adding a dbt
connection will result in the creation of a Model," per ThoughtSpot's
deprecation notes. The underlying REST API for this integration still uses the
legacy field names `import_worksheets` / `worksheets` / `semantic_report`
(component-type language, etc.) for backward compatibility. This skill uses
those API field names verbatim in commands, but refers to the resulting object
as a **Model** everywhere else. See
[references/open-items.md](references/open-items.md) #1.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single multi-question prompt to cut round-trips — e.g. source type + project
identifiers, or model-directory scope + `--import-worksheets` mode. The Path N / Path Y
choice is dependent: it follows from what `ts dbt inspect` reports, so ask it alone.

Two source types:
- **DBT_CLOUD:** a dbt Cloud project, identified by URL + account ID + project ID
  (+ optional environment ID), authenticated with a dbt Cloud API token.
- **ZIP_FILE:** a dbt Core project's `manifest.json` + `catalog.json` (produced
  by `dbt docs generate`). Point `--file` at the `target/` directory — the
  archive is built for you.

**Certified warehouses only:** ThoughtSpot's dbt integration is certified for
Amazon Redshift, Databricks, Google BigQuery, and Snowflake connections. If the
dbt project targets a different warehouse, this integration is not expected to
work — see [references/open-items.md](references/open-items.md) #5.

---

## References

| File | Purpose |
|---|---|
| [references/concept-mapping.md](references/concept-mapping.md) | dbt construct → ThoughtSpot object mapping — what this skill controls vs. what ThoughtSpot generates server-side |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Per-dbt-construct support status |
| [references/open-items.md](references/open-items.md) | Unverified API/product behaviour — MCP findings and live-test gaps |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| `tools/ts-cli/README.md` "`ts dbt`" section | Full `ts dbt` command reference — `create` / `update` / `list` / `delete` / `generate-tml` / `generate-sync-tml` (ThoughtSpot API) plus `list-models` / `inspect` (dbt Cloud **or** a local manifest via `--manifest`) and `build-model` / `trigger-job` (dbt Cloud API, **DBT_CLOUD only**) |
| `tools/ts-cli/README.md` "`ts profiles`" section | `ts profiles add/update/remove/list --platform dbt-cloud` — persists dbt_url/account_id/project_id/dbt_env_id + the token env var name across sessions |
| dbt Cloud / dbt Core project (user-provided) | Source of the dbt Cloud API token, or the `manifest.json` + `catalog.json` pair for ZIP_FILE |

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, 9.9.0.cl or later, REST API v2 enabled
- `ADMINISTRATION` or `DATAMANAGEMENT` privilege (`CAN_CREATE_OR_EDIT_CONNECTIONS` +
  `CAN_MANAGE_WORKSHEET_VIEWS_TABLES` if RBAC is enabled)
- The dbt project's warehouse must be Redshift, Databricks, BigQuery, or Snowflake
  (ThoughtSpot's certified list for this integration)
- Authentication configured — run `/ts-profile-thoughtspot` if you haven't already
- The `ts` CLI installed (`pip install -e /path/to/tools/ts-cli`), **v0.133.0+** —
  the release that introduced every `ts dbt` command this skill uses

**There is no file-only / dry-run mode for this integration.** `ts dbt generate-tml`
and `ts dbt generate-sync-tml` create and import objects directly — always confirm
with the user before running either (Step 7).

### dbt

**DBT_CLOUD:**
- dbt Cloud URL, account ID, project ID (and environment ID if the project uses one)
  — persisted in a `ts profiles add --platform dbt-cloud` profile (Step 2) so
  you don't have to look them up again in a later session.
- A dbt Cloud API token with read access to the project — **never pass it as a literal
  flag value.** The profile flow derives the env var name and gives you keychain
  commands to run in your own shell (matches `.claude/rules/security.md`) — same
  pattern as `/ts-profile-thoughtspot`.

**ZIP_FILE:**
- A local dbt Core project you can run `dbt docs generate` against (produces
  `target/manifest.json` and `target/catalog.json`)

`dbt docs generate`, not `dbt compile` — the latter writes only
`manifest.json`, and ThoughtSpot types the generated Table columns from
`catalog.json`. You do **not** need to zip anything yourself: every `--file`
flag accepts the `target/` directory and builds the archive.

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-from-dbt** — sync dbt models into ThoughtSpot as Tables + a Model, using ThoughtSpot's native dbt integration.

Steps:
  1.    Authenticate ThoughtSpot ............................. auto
  2.    Choose source (DBT_CLOUD / ZIP_FILE) + gather inputs .. you choose
  2.5.  Trigger fresh dbt Cloud job run (DBT_CLOUD only) ...... you choose
  3.    Check for an existing connection for this project ..... auto
  4.    Create or update the dbt connection object ............ auto (may ask for clarification)
  5.    Identify dbt models + tables to import ................ you choose
  6.    Choose Model import scope (ALL/NONE/SELECTED) ......... you choose
  7.    Review checkpoint — confirm before importing .......... you confirm
  8.    Generate TML (first import) ........................... auto (ts dbt generate-tml)
  9.    Review results / semantic report (if requested) ....... auto
 10.    Resync (subsequent runs) .............................. you choose, when needed

Confirmation required: Steps 2, 2.5, 3 (if an existing connection is found), 5, 6, 7
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

Verify: `ts auth whoami --profile {name}` — print `display_name` and base URL.

---

### Step 2: Choose source and gather inputs

```
How is this dbt project sourced?
  C — dbt Cloud (DBT_CLOUD)
  Z — dbt Core, manifest + catalog ZIP (ZIP_FILE)

Enter C / Z:
```

**DBT_CLOUD path:** check for an existing dbt-cloud profile first — these
persist `dbt_url`/`account_id`/`project_id`/`dbt_env_id`/`project_name`
locally (ThoughtSpot's own `dbt/search` response never echoes these back
after connection creation, so without a profile you'd have to re-look them
up from the dbt Cloud UI every session):

```bash
ts profiles list --dbt-cloud --json
```

- **A match exists** for this project: reuse it — the profile's `token_env`
  field is `{access_token_env}` for every later step.
- **No match:** collect `dbt_url`, `account_id`, `project_id`, optional
  `dbt_env_id`, optional `project_name` from the user, then create the profile:

  ```bash
  ts profiles add --platform dbt-cloud --name "{project_name_or_label}" \
    --auth-type token \
    --field dbt_url={dbt_url} --field account_id={account_id} \
    --field project_id={project_id} \
    [--field dbt_env_id={dbt_env_id}] [--field project_name={project_name}]
  ```

  This returns `keychain_store_commands` and (on macOS/Linux) a `zshenv_line`
  — give these to the user to run **in their own terminal**, exactly like
  `/ts-profile-thoughtspot`'s Add flow. Never accept the token value here.
  The command's own `env_var` field is `{access_token_env}` for every later
  step — store it, don't ask the user to type it again.

**ZIP_FILE path:** ask for the path to the dbt Core project's **`target/`
directory** — the one `dbt docs generate` writes `manifest.json` and
`catalog.json` into. Do not ask the user to zip anything: `--file` accepts
that directory (or the project root above it, or either artifact) and packs
the two files into the archive ThoughtSpot uploads. A ready-made `.zip` is
still accepted verbatim if they already have one.

If they have not run `dbt docs generate` yet, have them run it first — the
command refuses with that instruction when `catalog.json` is absent, which is
what a `dbt compile`-only project looks like. It refuses rather than uploading
the manifest alone because ThoughtSpot types the generated Table columns from
`catalog.json`: a manifest-only archive imports *successfully*, with no column
types.

Also collect `connection_name` and `database_name`. **`connection_name` is the
display name of an EXISTING ThoughtSpot warehouse connection** (an "Embrace"
connection — e.g. `se snowflake`), not a label for the new dbt connection
object: the API binds the dbt connection to that warehouse connection and
returns its `connection_id`. `database_name` is the database on that
connection the dbt project builds into (e.g. `DL_TEST`). List the
candidates with `ts connections list --profile {profile}` if the user is
unsure of the exact name. (Live-verified 2026-09-09; the REST spec for
`dbtConnection` calls these the "embrace connection" and "embrace database".)

---

### Step 2.5: Trigger fresh dbt Cloud job run (DBT_CLOUD only)

**This step applies only to DBT_CLOUD projects.** Skip to Step 3 for ZIP_FILE.

Before importing, offer to trigger a fresh dbt Cloud job run so the manifest and
catalog reflect the latest `schema.yml` changes. This matters because `description`,
`ts_ai_context`, and `ts_join_*` relationship tests are all compiled into the manifest
only when a dbt job runs — if `schema.yml` was updated after the last successful run,
those fields will be absent from the manifest `build-model` reads.

**Always list available jobs first** so the user can see which job's artifacts are
currently on file before deciding whether to trigger:

```bash
ts dbt trigger-job --dbt-cloud-profile {dbt_cloud_profile}
```

This returns each job's `id`, `name`, `description`, and `last_successful_run` timestamp.
Present the list in a readable table:

```
Available jobs for this project:
  ID        Name            Last successful run
  -------   -------------   -----------------------
  184165    DL TEST Job     (none)
  384981    New Job         2026-09-03 20:43:22 UTC
  1042780   DL Job1         2026-04-24 19:03:43 UTC
  1121584   dbt-test        2026-09-04 15:22:28 UTC
```

Then ask:

```
Trigger a fresh job run, or use existing artifacts from one of these jobs?
  T — trigger a job run now (recommended if schema.yml was recently updated)
  U — use existing artifacts (pick the job whose last run produced them)

Enter T / U:
```

**If T:** ask which job to trigger (user picks from the table), confirm, then run:

```bash
ts dbt trigger-job --dbt-cloud-profile {dbt_cloud_profile} --job-id {job_id}
```

Progress is reported to stderr every 15 seconds. On success the command prints a JSON
result with `run_id`, `job_id`, `status: "Success"`, and `finished_at`. If the run
ends in `Error` or `Cancelled`, the command exits non-zero and prints the failed
step's log tail on stderr (the dbt error lines, ANSI/noise stripped) — read that
before proceeding; open dbt Cloud only if the excerpt isn't enough.

**If U:** ask which job's artifacts to use (user picks from the table). Note that
`description`, `ts_ai_context`, and `ts_join_*` definitions will be absent from the
manifest if `schema.yml` was updated after the selected job's last run.

In both cases, store `{selected_job_id}` — it is the source of the manifest used in
the Step 8 pre-check and by `build-model`.

---

### Step 3: Check for an existing connection

Avoid creating a duplicate connection for the same dbt project:

```bash
ts dbt list --profile {profile}
```

Filter the returned array by `project_name` / `cdw_database` / `connection_name`
against what the user gave you in Step 2. If a match is found:

```
Found an existing dbt connection for this project:
  {connection_name} ({dbt_connection_identifier}, {import_type})

  U — Update it and resync (go to Step 4 in update mode)
  N — Create a new, separate connection anyway

Enter U / N:
```

If no match, proceed to Step 4 in create mode.

---

### Step 4: Create or update the connection

**Create mode:**

```bash
ts dbt create \
  --connection-name "{connection_name}" --database-name "{database_name}" \
  --import-type DBT_CLOUD --dbt-url "{dbt_url}" \
  --account-id {account_id} --project-id {project_id} \
  [--dbt-env-id {dbt_env_id}] \
  [--project-name "{project_name}"] \
  --access-token-env {access_token_env} \
  --profile {profile}
```

`{dbt_url}`/`{account_id}`/`{project_id}`/`{dbt_env_id}`/`{project_name}`/`{access_token_env}`
all come from the dbt-cloud profile found or created in Step 2 — no re-prompting.
`--dbt-env-id` is required if the project uses dbt Cloud environments: without
it ThoughtSpot has no environment to fetch job runs from and `generate-tml`/
`generate-sync-tml` will fail with "passed models don't have match with the job
artifacts" (see [references/open-items.md](references/open-items.md) #11).

or, for ZIP_FILE:

```bash
ts dbt create \
  --connection-name "{connection_name}" --database-name "{database_name}" \
  --import-type ZIP_FILE --file {path/to/dbt_project}/target \
  --profile {profile}
```

`--file` takes the `target/` directory and zips `manifest.json` +
`catalog.json` into the archive ThoughtSpot uploads. A path to either artifact,
the project root, or an existing `.zip` all work too.

**Update mode:** same command, `ts dbt update --connection-id {dbt_connection_identifier} ...`,
passing only the fields that changed — unset fields are left unchanged server-side.

Store the returned `dbt_connection_identifier` — every later step needs it.

---

### Step 5: Identify dbt models and tables to import

`ts dbt generate-tml` requires `--model-tables`, a JSON array grouped by
**directory** — each entry covers all dbt models whose `original_file_path`
shares the same parent directory (see
[references/open-items.md](references/open-items.md) #11):

```
model_name  = last segment of the directory  (e.g. "core" for "models/marts/core")
model_path  = the directory path             (e.g. "models/marts/core")
tables      = warehouse relation names for all models in that directory —
              the node's `alias` when set, else its `name`, upper-cased
```

**Use the alias, not the file name.** A model with `alias:` (or a project-level
`+alias` / `generate_alias_name` macro) is materialised under that alias, and
that is the only name ThoughtSpot matches. Passing the file/model name instead
fails the whole call with a 400:
`"STG_APPOINTMENTS, … table(s) not found for model models/staging/barbershop"`
(live 2026-09-09 — the barbershop `stg_appointments` model builds
`APPOINTMENTS`).

There is no ThoughtSpot API to list a connection's available models first (see
[references/open-items.md](references/open-items.md) #4), so the array is built
from the dbt artifacts. **`ts dbt list-models` does this for both connection
types — do not hand-roll a manifest download or a grouping loop.**

**DBT_CLOUD** — the latest successful run's manifest, fetched for you:

```bash
ts dbt list-models --dbt-cloud-profile {dbt_cloud_profile}
```

**ZIP_FILE, or any offline project** — point it at the local artifact. No
profile, no token, no network:

```bash
ts dbt list-models --manifest {path}   # manifest.json, a target/ dir, or the project ZIP
```

Either way it applies the directory grouping above and prints ready-to-paste
`--model-tables` JSON, emitting each model's **alias** by default. The token
comes from the profile's Keychain entry or env var — never pass a token value
(see [references/open-items.md](references/open-items.md) #4, #13).

> `--no-alias` exists only for a project whose manifest aliases are wrong.
> Reach for it only after `generate-tml` has actually rejected the aliased
> names.

The manifest is cached per `(profile, run id, artifact)`, so the later
`ts dbt inspect` and `ts dbt build-model` calls in this run reuse it rather
than re-downloading. Pass `--no-cache` if a run's artifacts were re-uploaded
in place.

Two fallbacks, in order, if `list-models` can't run (no successful run in the
environment, or a ZIP-only workflow):

- **Ask the user** for the model names and directories. They can read these
  from the dbt Cloud UI's **Artifacts** tab.
- The **Discovery API** (GraphQL, `https://metadata.cloud.getdbt.com/graphql`)
  — exercised once during testing but not what the CLI calls; see
  [references/open-items.md](references/open-items.md) #4.

Present the extracted list to the user for confirmation — do not assume every
directory/model should be imported; ask if they want all or a subset.

Build the `--model-tables` JSON from the confirmed list.

**Note:** `generate-sync-tml` (no `--model-tables` parameter) is simpler — it
imports ALL models in the manifest without requiring this step. Prefer it when
the user wants to import everything. Use `generate-tml` when they need
per-directory scope control (e.g. import only `models/marts/core`, skip staging).

---

### Step 5.5: Optional — `ts_*` metadata tags for fine-grained control

The same sync this skill drives (`ts dbt generate-tml`/`generate-sync-tml`) reads
ThoughtSpot-specific `ts_*` tags under dbt's standard `meta:` key, if the user's
dbt project's schema.yml declares them. This is **not required** — without them,
ThoughtSpot auto-detects column types and joins from the dbt model structure —
but it's worth surfacing to the user before Step 8, since it's the only way to
control join cardinality/type/name and several column properties (format,
synonyms, indexing, etc.) declaratively from dbt rather than editing the
resulting Model in ThoughtSpot afterward.

Column-level (nest under each column's `config:` in current dbt syntax — dbt
Core ≤1.7-era projects may still use a bare `meta:` sibling instead, see below):

| Tag | Sets | Valid values |
|---|---|---|
| `ts_column_type` | Column type | `attribute` or `measure` |
| `ts_aggregation` | Default aggregation | `sum`, `count`, `count_distinct`, `min`, `max`, `average`, `std_deviation`, `variance`, `none` |
| `ts_synonym` | Search synonyms | Comma-separated text |
| `ts_format_pattern` | Numeric/date display format | Format pattern strings |
| `ts_hidden` | Column visibility | `yes`/`no` (default `no`) |
| `ts_currency_type` | Currency formatting | **A nested block, not a flat value** — `type:` is `from_isocode` (with `isocode:`), `from_column` (with `column:`), `from_browser`, or `none`. See the example below |
| `ts_calendar_type` | Custom calendar | `none`, `default`, or a calendar name. DATE/DATETIME columns only |
| `ts_geo_config` | Geo map role | **A nested block, not a flat value** — `type:` is `latitude`, `longitude`, `country`, `sub_nation_region` (with `country:` and `region_type:`), or `none`. See the example below |
| `ts_index_priority` | Search index priority | Integer 1–10 |
| `ts_index_type` | Indexing behavior | `default` or `dont_index` |
| `ts_attr_dim` | Attribution dimension flag | `yes`/`no` |
| `ts_additive` | Semi-additive summation flag | `yes`/`no` |
| `ts_spotiq_pref` | Exclude from SpotIQ analysis | `default` or `exclude` |
| `ts_display_name` | Model column display name (**ts-cli extension** — read by `ts dbt build-model` only, not by ThoughtSpot's server-side `generate-tml`) | Any text |
| `ts_column_exclude` | Leave the column out of the Model entirely (**ts-cli extension** — `build-model` only). The column still exists on the Table (Tables are generated server-side); it is simply never added to the Model's `columns[]`, so it can't be searched or charted from the Model. Differs from `ts_hidden`, which keeps the column in the Model and only hides it. Formula columns (`ts_formula`) can be excluded the same way. | `yes`/`no` (or `true`/`false`) |
| `ts_ai_context` | Column `properties.ai_context` — the per-column guidance Spotter reads (**treat as a ts-cli extension — `build-model` only**: absent from ThoughtSpot's own tag docs, and unverified on the server-side `generate-tml` path, see [references/open-items.md](references/open-items.md) #16) | Any text |
| `ts_formula` | A ThoughtSpot formula column, expression preserved verbatim (**ts-cli extension** — `build-model` only). Written by `ts-convert-to-dbt`; this is the return leg of that round trip. Pair with `ts_column_type`/`ts_aggregation` to type the resulting column | A ThoughtSpot formula expression |

Join/relationship-level (on a `relationships` data test, nested under that
test's `config.meta` in current dbt syntax):

| Tag | Sets | Valid values |
|---|---|---|
| `ts_join_cardinality` | Join cardinality | `one_to_one`, `many_to_one`, `one_to_many` |
| `ts_join_type` | Join type | `inner`, `left_outer`, `right_outer`, `full_outer` |
| `ts_join_name` | Join name | Any text |

Model-level (under the model's `config.meta` in schema.yml):

| Tag | Sets | Valid values |
|---|---|---|
| `ts_rls_rules` | Row-level security rules on the Table TML | List of `{name, expr, table_paths}` objects — see example |

`ts_rls_rules` is the dbt schema.yml representation of ThoughtSpot's Table TML
`rls_rules` block. Unlike the column- and join-level `ts_*` tags above (which
ThoughtSpot's server processes during `generate-tml`), `rls_rules` lives on the
**Table TML** not the Model TML — so ThoughtSpot's server-side `generate-tml` does
not apply it. Instead, `ts dbt build-model` handles it client-side: it reads
`ts_rls_rules` from the compiled manifest and patches each affected Table TML
(export → inject `rls_rules` block → re-import). A new job run is required any time
the rules change in schema.yml.

Example:
```yaml
models:
  - name: stg_barbers
    config:
      meta:
        ts_rls_rules:
          - name: rls rule
            expr: 'ts_username = [STG_BARBERS_1::FIRST_NAME] '
            table_paths:
              - id: STG_BARBERS_1
                table: STG_BARBERS
                columns:
                  - FIRST_NAME
```

**MetricFlow metrics (dbt Semantic Layer) — ts-cli extension, `build-model` only.**
If the project defines a v2 `semantic_model:` block (dbt Core 1.12+ / Fusion) on its
models, `ts dbt build-model` translates the compiled `metrics` into Model formulas:
`simple` (sum/average/min/max/count/count_distinct on a bare column), `ratio`
(`safe_divide` of the two input formulas) and `derived` (`expr` with input-metric
aliases replaced by formula refs). The metric `label` becomes the formula display
name; `description` and `config.meta.ts_synonym`/`ts_format_pattern`/`ts_index_type`/
`ts_ai_context` on the metric carry onto the column. A metric whose label matches an
existing `ts_formula` column supersedes it (case-insensitive) — the migration path
from `ts_formula` strings to real metrics. Cumulative/conversion metrics, `filter`s,
offsets and SQL-expression `expr`s are listed on stderr as not translated. Joins:
`relationships` tests + `ts_join_*` tags stay authoritative (the only place join type and
name live); only a table pair with no such test gets a join derived from a MetricFlow
foreign→primary entity pair (`LEFT_OUTER` / `MANY_TO_ONE`, reported on stderr). Columns
with no `ts_*` meta are still imported, typed from `catalog.json` (numeric → measure/sum,
else attribute; entity/dimension columns always attribute). MetricFlow needs a time spine model in the
project (`time_spine:` config); it lives outside the model directory and is never
imported. **Naming:** MetricFlow rejects the whole semantic manifest (`Semantic
Manifest validation failed` on the dbt Cloud run) if any entity, dimension or metric
name is not `lower_snake_case` — with upper-case warehouse columns, always set an
explicit lowercase `dimension.name` and point `agg_time_dimension` at that name, not
at the column. A second rule fails the same way: a (primary entity, dimension name)
pairing may exist on only one semantic model in the project (`Duplicate dimension +
primary entity pairing detected`), so two semantic models over related tables need
distinct primary-entity names. Full mapping: `tools/ts-cli/README.md` "MetricFlow metrics → formulas".

```yaml
models:
  - name: transactions
    semantic_model:
      enabled: true
    agg_time_dimension: transaction_date              # refers to the dimension *name*
    columns:
      - name: TRANSACTION_ID
        entity: {type: primary, name: transaction}
      - name: APPOINTMENT_ID
        entity: {type: foreign, name: appointment}      # mirrors the ts_join_* relationship
      - name: TRANSACTION_DATE
        granularity: day
        dimension: {type: time, name: transaction_date} # MetricFlow names must be lower_snake_case
      - name: PAYMENT_METHOD
        dimension: {type: categorical, name: payment_method}
    metrics:
      - name: total_tips
        label: Total Tips
        type: simple
        agg: sum
        expr: TIP_AMOUNT
      - name: tip_rate
        label: Tip Rate
        type: ratio
        numerator: total_tips
        denominator: total_service_revenue
      - name: net_revenue
        label: Net Revenue
        type: derived
        expr: revenue - discounts
        input_metrics:
          - {name: total_service_revenue, alias: revenue}
          - {name: total_discounts, alias: discounts}
```

Example (current dbt syntax):

```yaml
models:
  - name: dim_customers
    columns:
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
        data_tests:
          - relationships:
              arguments:
                to: ref('fact_orders')
                field: CUSTOMER_ID
              config:
                meta:
                  ts_join_cardinality: many_to_one
                  ts_join_type: left_outer
```

The two nested tags, verbatim from ThoughtSpot's docs:

```yaml
columns:
  - name: SALES
    config:
      meta:
        ts_column_type: measure
        ts_currency_type:
          type: from_isocode      # or from_column (+ column:), from_browser, none
          isocode: USD
  - name: STATE
    config:
      meta:
        ts_geo_config:
          type: sub_nation_region # or latitude, longitude, country, none
          country: United States
          region_type: State
```

Both round-trip through `ts-convert-to-dbt` — a ThoughtSpot `currency_type`/
`geo_config` becomes the nested block above and is restored on the way back.
The one exception is a **custom-map** geo role (`custom_file_guid`), which has
no `ts_geo_config` type and is instance-local, so it is reported rather than
translated.

Tag names and values verified against
docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags (2026-09-09
— 13 column tags + 3 join tags, the full documented set), and live against a
real `dbt-fusion parse`
(2026-08-27) for the current-syntax nesting — that build hard-errors on the
older bare `meta:`/`tests:`/`to:`/`field:` shape ThoughtSpot's own docs example
shows, so prefer the `config:`/`data_tests:`/`arguments:` form shown above unless
the user's dbt version is old enough to reject it (not yet verified against any
dbt-core version — see [references/open-items.md](references/open-items.md) #9).
Ask the user which shape their dbt version expects if `dbt parse` rejects one.

Full generation of these tags from an existing ThoughtSpot Model is the
`ts-convert-to-dbt` skill's job (the reverse direction) — this step is about
reading them, not writing them.

---

### Step 6: Choose Model import scope

The API's `import_worksheets` parameter controls whether the resulting Model
is generated at all (legacy field name — see the Terminology note above):

```
Import a Model for these dbt models?
  A — ALL (default) — generate the Model
  N — NONE — Tables only, no Model
  S — SELECTED — choose specific Model(s) by name

Enter A / N / S:
```

If **S**, also collect the Model names for `--worksheets`.

---

### Step 7: Review checkpoint

There is no dry-run mode — `generate-tml` creates and imports objects
immediately. Show the user exactly what will run before executing it:

```
About to generate TML for connection {dbt_connection_identifier}:
  Models: {model_names, comma-separated}
  Model import: {ALL | NONE | SELECTED: names}
  Semantic report: {yes/no}

Proceed? [Y / N]
```

Wait for confirmation before Step 8.

---

### Step 8: Generate TML (first import)

#### Step 8-pre: Manifest pre-check — detect multi-fact schema

Before choosing Path N or Path Y, inspect the target directory. This avoids an
unnecessary `generate-tml` round-trip when Path Y is clearly needed.

```bash
ts dbt inspect --dbt-cloud-profile {dbt_cloud_profile} \
  --model-path {target_directory}

# offline / ZIP_FILE — same output, no profile or token
ts dbt inspect --manifest {path} --model-path {target_directory}
```

Read-only: no ThoughtSpot API call, no ThoughtSpot profile, nothing written.
It reuses the manifest `ts dbt list-models` already cached for this run.

**Take `recommended_path` as the decision.** It is `"Y"` whenever the directory
holds something only the client-side assembly preserves, and `reasons[]` names
each signal that decided it:

| Signal in the output | Why Path N loses it |
|---|---|
| `ts_join_tests[]` non-empty | `generate-tml` produces one Model per **FK-source (fact) table**, each with its direct targets and shared dimensions duplicated — `path_n_model_count` in the report says how many. It also drops `ts_column_exclude` / `ts_display_name` / `ts_formula` |
| `rls_models[]` non-empty | ThoughtSpot's server-side sync does not read `ts_rls_rules` — row-level security is dropped with no error |
| `metricflow_metrics[]` non-empty | only `build-model` translates MetricFlow metrics into Model formulas |

- **`"Y"` → skip Path N.** Run Step 8a (Tables), then Step 8b (build-model).
- **`"N"` → Path N.** ThoughtSpot will attempt to unify the directory; if it
  produces multiple Models, fall back to Path Y.

**Where `ts_join_*` lives:** these tags are *defined in `schema.yml`* by the dbt
project author and *compiled into the manifest* by dbt when a job runs. Both
`inspect` and `build-model` read the compiled manifest, never `schema.yml`
directly — so a `schema.yml` change needs a new job run (`ts dbt trigger-job`)
before either sees it. If `inspect` reports no join tests you know the author
wrote, that missing job run is the first thing to check.

---

#### Path N — Direct generate-tml

Run `generate-tml` and inspect how many Models are returned for the target directory:

```bash
ts dbt generate-tml \
  --connection-id {dbt_connection_identifier} \
  --model-tables '{model_tables_json}' \
  --import-worksheets ALL \
  [--include-semantic-report] \
  --profile {profile}
```

`worksheet_tmls.{model_path}` should hold exactly the number of Models
`inspect` predicted in `path_n_model_count`:

- **1 model returned** (the expected case here — `inspect` said Path N): a
  unified Model with all tables and joins applied, including `ts_join_*`
  cardinality and type. Proceed to Step 9.
- **More than 1**: `inspect` and the server disagree, which should not happen —
  the directory has several FK-source tables. Delete the split Models (keep the
  Tables), use Path Y below, and record the divergence in open-items #11.

You should not reach this step and be surprised: run `ts dbt inspect` first
(Step 8-pre) and it reports the count up front. The older
"import it and count what comes back, then delete" loop is no longer necessary.

```bash
# Delete the split models (keep Table objects)
ts metadata delete {split_model_guid_1} {split_model_guid_2} ... --profile {profile}
```

If `generate-tml` fails with "passed models don't have match with the job
artifacts" (dbt-fusion/manifest v12 projects — see
[references/open-items.md](references/open-items.md) #11), fall back to
`generate-sync-tml`:

```bash
ts dbt generate-sync-tml \
  --connection-id {dbt_connection_identifier} \
  [--include-semantic-report] \
  --profile {profile}
```

`generate-sync-tml` imports ALL models in the project (no per-directory scope).
If it also returns multiple models for the target directory, delete the split
models and use Path Y.

`--include-semantic-report` is only honored for Snowflake and Databricks
connections — omit it for Redshift/BigQuery.

---

#### Path Y — Unified Model from dbt Cloud artifacts (multi-fact schema)

ThoughtSpot split the directory because its connected-component algorithm treats
FK-disconnected fact tables as separate models, even when `ts_join_*` tests define
cross-component joins via shared dimensions. This path reads those `ts_join_*`
tests directly from the dbt Cloud job artifacts (manifest + catalog) to build a
single unified Model — no local schema.yml needed.

**ZIP_FILE connections:** `ts dbt build-model` reads the artifacts from a dbt
Cloud run, so it needs a DBT_CLOUD connection. The offline equivalent is
`ts dbt-export build-model --schema-yml`, which assembles the same unified
Model from the project's **source** `schema.yml` instead of the compiled
manifest — see Step 10.4. Two differences that follow from reading source
rather than compiled output:

- no `catalog.json`, so a column carrying no `ts_*` meta cannot be typed from
  its warehouse type — declare those columns explicitly
- no MetricFlow translation (`semantic_models`/`metrics` exist only in the
  compiled manifest)

`ts dbt inspect --manifest {zip}` still works for the Step 8-pre decision —
it reads the manifest out of the ZIP directly.

**Step 8a — Ensure Table objects are imported:**

The Tables from the Path N attempt already exist and are correct (ThoughtSpot
created them before splitting into multiple models). Skip 8a and go directly to 8b.

If Tables need refreshing:
```bash
ts dbt generate-tml \
  --connection-id {dbt_connection_identifier} \
  --model-tables '{model_tables_json}' \
  --import-worksheets NONE \
  --profile {profile}
```

**Step 8b — Build and import the unified Model:**

Ask the user for the desired ThoughtSpot Model name (e.g. `BARBERSHOP_OPERATIONS`)
if it cannot be derived from the directory's `model_name`.

```bash
ts dbt build-model \
  --dbt-cloud-profile {dbt_cloud_profile} \
  --model-path {model_path} \
  --model-name {model_name} \
  [--pretty-names] \
  --profile {profile}
```

Ask the user whether they want **pretty display names** (`--pretty-names`:
`APPOINTMENT_DATETIME` → `Appointment Datetime`, acronyms like `ID` kept
upper-case) — warehouse-style upper-case names read poorly on charts. A
`ts_display_name` column meta tag in schema.yml overrides either choice per
column. To change names on a Model that already exists, re-run with
`--model-guid {model_guid}` — it updates in place (same GUID, dependents intact).

This command downloads `manifest.json` + `catalog.json` from the latest successful
dbt Cloud run, reads `ts_join_*` relationship tests to assemble `model_tables[]` +
`joins[]`, applies column-level `ts_*` metadata (column type, aggregation, synonyms,
format, index type, ai_context), and imports the Model TML in a single step.

A `WARNING` status about "misconfigured suggestion settings" in the response is
expected for columns without explicit `ts_index_type` in the manifest — the Model
is created/updated (live-verified by re-export 2026-09-09). `ts tml import` and
`build-model` treat `WARNING` as imported: the notice goes to stderr and the exit
code is 0. Any `status_code` other than `OK`/`WARNING` is a failure (exit 1).

**Same-named Tables in the Org:** `build-model` pins every `model_tables[]` ref
with an `fqn` (resolved via `metadata/search`; duplicates are disambiguated by
matching the candidates' `db`/`schema`/`db_table` to the manifest's
`database`/`schema`/`alias`) and uses the same GUID for the `ts_rls_rules` Table
export. Without this, a second Table with the same name — typically the raw
warehouse tables registered before the dbt views — fails the Model import with
error 14502 "Found multiple data sources with same name" and the RLS export with
409 `DUPLICATE_OBJECT_FOUND`. If `build-model` exits listing candidate GUIDs, none
of the same-named Tables sits at the manifest's warehouse location: check that
Step 8a imported the Tables from the same database/schema the dbt job built into,
or remove the stale duplicates (run `ts metadata report {guid}` first).

**Note on description and ts_ai_context:** these populate from the compiled
manifest. If absent in the imported Model, the dbt project needs a new job run to
compile the latest schema.yml changes — trigger a run in dbt Cloud, then re-run
`ts dbt build-model`.

Columns tagged `ts_column_exclude: yes` are skipped when the Model's `columns[]`
is assembled — `build-model` lists them on stderr (`ts_column_exclude: N column(s)
left out of the Model — TABLE::COL, …`). They remain on the Table object. On a
`--model-guid` re-run, a newly excluded column is removed from the Model; check
`ts metadata report {model_guid}` first if Answers or Liveboards might use it.

MetricFlow metrics (Step 5.5) are translated to formulas by default — `build-model`
reports on stderr `MetricFlow: N metric(s) translated to formulas — …`, any
`ts_formula` columns a same-named metric superseded, and each metric it could
**not** translate with the reason. Pass `--no-metrics` to build from `ts_*` column
meta only. Metrics need a fresh job run to appear in the manifest, like every
other schema.yml change.

`ts_rls_rules` in schema.yml are applied by `build-model` automatically — for each
model that carries the tag, `build-model` exports the ThoughtSpot Table TML, patches
the `rls_rules` block, and re-imports. This requires a fresh job run if `ts_rls_rules`
were added or changed since the last run (same requirement as `description`/`ts_ai_context`).

Skip to Step 9.

---

### Step 9: Review results

Print the raw JSON response. If `--include-semantic-report` was used, surface
the per-model `semantic_report` breakdown — component name, type
(dimension/measure/metric), import status, and the SQL → ThoughtSpot formula
translation — so the user can spot anything skipped or unexpected before
relying on the generated Model.

If any models were skipped or failed, report them clearly and ask whether to
retry. If the fallback (`generate-sync-tml`) was used and scope matters to
the user (they only wanted a subset), note that unneeded tables can be deleted
from ThoughtSpot after reviewing what landed.

---

### Step 10: Resync (subsequent runs)

**`generate-sync-tml` has no dry-run and no diff response** — its API response
schema is an undocumented empty object, and there is no way to ask ThoughtSpot
what a resync would change before running it (unlike the Snowflake SV skills'
`ts snowflake diff`). A dropped dbt column can silently orphan downstream
ThoughtSpot Models, Answers, Liveboards, Sets, or RLS rules with no warning
from this API. Steps 10.1–10.4 build a preflight check around that gap by
diffing dbt's *current* state against what ThoughtSpot last synced, for
**either** connection type — treat the dbt-Cloud path as best-effort until the
Discovery API call is verified live, per
[references/open-items.md](references/open-items.md) #4/#7.

#### Step 10.1: Snapshot current columns

Before doing anything else, export the connection's current Table/Model TML to
capture today's columns and their GUIDs, and write it to disk:

```bash
ts tml export {table_and_model_guids} --profile {profile} --fqn --associated --parse \
  > /tmp/ts_dbt_snapshot_{connection_name}_{YYYYMMDD}.json
```

Use today's date in the filename so multiple snapshots don't collide. Step 10.3
and Step 10.5 both diff against this file — keeping it on disk means the post-hoc
verification in Step 10.5 survives a session interruption between the resync and
the diff.

#### Step 10.2: Update connection coordinates if needed

If the connection's dbt Cloud fields changed (`dbt_url`, `account_id`,
`project_id`, or `dbt_env_id`) — or a new ZIP — run `ts dbt update` first with
the changed fields only — and, for DBT_CLOUD, `ts profiles update --platform
dbt-cloud --name {name} --field ...` too, so Step 10.3's own Discovery API call
(which reads the profile, not the ThoughtSpot connection object) uses the current
values.

#### Step 10.3: Predict removed columns

Diff dbt's current column set against the Step 10.1 snapshot file
(`/tmp/ts_dbt_snapshot_{connection_name}_{YYYYMMDD}.json`), using whichever
source matches this connection's `import_type` — same two sources as Step 5:

- **ZIP_FILE:** read the new `manifest.json`/`catalog.json` pair.
- **DBT_CLOUD:** read the latest successful run's `manifest.json`/`catalog.json`.

> **This step has no CLI command yet.** `ts dbt list-models` and
> `ts dbt inspect` report models and joins, not per-column sets, so the column
> comparison is still done by reading the artifacts directly. Codifying it as
> `dbt/manifest.py::column_set` is the next piece of work — until then, treat
> the predicted-removal list as best-effort and rely on Step 10.5's post-hoc
> verify as the real check. (The older wording here pointed at the Discovery
> API; that is not what shipped — see [references/open-items.md](references/open-items.md) #4.)

Any column present in the snapshot but absent from dbt's current state is a
**predicted removal**.

For each predicted removal, run the dependency impact check before proceeding:

```bash
ts metadata report {column_or_table_guid} --format json --profile {profile}
```

This is `ts-dependency-manager`'s read-only Audit capability. It now covers
13 impact-analysis passes end to end — model/table column dependents,
RLS-rule references, cohort/set dependents, monitor-alert references, column
security rules, model-level formula and filter references, formula/template
variables, business terms/AI memory, SQL-view text references, custom
actions, and scheduled reports — with a real per-dependent HIGH/MEDIUM/LOW
risk rating and a hard **STOP condition for RLS or column-security-rule
findings** (see [references/open-items.md](references/open-items.md) #8 for
the fix history). Two signals still have no backing probe — chart-axis usage
and dormancy — so a dependent that's only ever referenced on a chart's x/y
axis, or whose object simply hasn't been touched recently, won't be flagged
as HIGH/LOW on those grounds specifically; it will still surface as a
dependent via the underlying walk, just without that particular risk
upgrade. Do not proceed past a STOP finding without explicit user
confirmation.

Present every predicted removal and its impact report to the user:

```
The following columns will likely be dropped by this resync:
  {model_name}.{column_name} — {risk level}: used by {N} Answers, {N} Liveboards
    {list dependents, flag RLS rules prominently}

Proceed with resync anyway? [Y / N]
```

Do not proceed to Step 10.4 until the user confirms — or until they've resolved
the flagged dependencies themselves (e.g. via `/ts-dependency-manager` in
Repoint mode, run separately, before returning here).

If neither source is available (e.g. DBT_CLOUD Discovery API fails **and** the
user can't enumerate columns manually), say so plainly and fall through to
Step 10.5 as the only safety net for this run.

#### Step 10.4: Resync

```bash
ts dbt generate-sync-tml \
  --connection-id {dbt_connection_identifier} \
  [--file {path/to/dbt_project}/target] \
  [--include-semantic-report] \
  --profile {profile}
```

Unlike `generate-tml`, `generate-sync-tml` does **not** take `--model-tables` or
`--import-worksheets` — it resynchronizes the existing model/table/Model
selection already on the connection object.

**`generate-sync-tml` only refreshes what the connection manages server-side** —
physical table columns and table metadata. It does **not** touch the Model's
join graph, formula columns, display names, or `ts_column_exclude` choices. So
re-run Step 8b's `build-model` afterwards whenever the Model came from Path Y,
or whenever the dbt project's `schema.yml` carries `ts_join_*`, `ts_formula`,
`ts_display_name` or `ts_ai_context` from a prior `ts-convert-to-dbt` run.

Both re-run commands update the existing Model **in place** — same GUID, so
dependent Answers and Liveboards stay intact.

**DBT_CLOUD — preferred.** Reads the fresh manifest itself; no local
`schema.yml` needed, and it re-applies `ts_rls_rules` too:

```bash
ts dbt build-model \
  --dbt-cloud-profile {dbt_cloud_profile} \
  --model-path {model_path} \
  --model-name {model_name} \
  --model-guid {model_guid} \
  [--pretty-names] \
  --profile {profile}
```

Make sure a dbt Cloud job has run since the `schema.yml` change (Step 2.5) —
`build-model` reads the compiled artifacts, not the source file.

**ZIP_FILE, or when you only have the project files locally:** assemble from
`schema.yml` and import in one call. `--model-guid` puts the guid at the
document root and imports with `create_new=false`:

```bash
ts dbt-export build-model \
  --schema-yml {schema_yml_path} \
  --model-name {model_name} \
  --model-guid {model_guid} \
  --rls-out /tmp/{model_name}_rls \
  --import --profile {profile}
```

> **`--model-guid` is not optional on a resync.** Without it the import runs
> with `create_new=true` and produces a **second Model** beside the one you
> meant to update — it does not fail, and nothing downstream notices.

This path does **not** apply `ts_rls_rules` automatically — RLS lives on the
Table TML, not the Model. `--rls-out` writes one `<TABLE>_rls_rules.json` per
affected model for you to merge into that Table's TML and re-import; omit the
flag and the command warns by name rather than dropping the rules silently.
`ts dbt build-model` (the dbt Cloud path above) applies them for you.

Only `ts dbt build-model` pre-checks for duplicate Model column display names
(ThoughtSpot compares them case-insensitively and rejects the whole
`ALL_OR_NONE` import). On the `ts dbt-export build-model` path that check does
not run, so a collision surfaces as the API's less specific "Multiple columns
with the same name found" — give one of the pair a distinct `ts_display_name`
in `schema.yml` and regenerate.

`build-model` reads `ts_join_*` tests (join graph) and `ts_formula` entries
(formula columns) from schema.yml, so the re-imported Model contains both
alongside the updated physical columns from `generate-sync-tml`.

**RLS rules are preserved automatically on resync** — `generate-sync-tml` updates
column definitions but does not touch `rls_rules` on the Table TML. No patching
step is needed.

#### Step 10.5: Post-hoc verification (always run)

Re-export the same GUIDs from Step 10.1 and diff against the snapshot file
(`/tmp/ts_dbt_snapshot_{connection_name}_{YYYYMMDD}.json`) to confirm what
actually changed — this catches anything Step 10.3 couldn't
predict (Discovery API/manifest drift, or either source being unavailable). If
a column disappeared that wasn't already flagged and confirmed in Step 10.3,
report it to the user immediately and offer to run `ts metadata report` on it
now — after the fact, this can only surface already-broken dependents, not
prevent the break, so say that plainly rather than implying it's still
preventable.

---

### Cleanup

```bash
ts dbt delete --connection-id {dbt_connection_identifier} --profile {profile}
```

Deletes the connection object. Confirm with the user before running — this does
not undo previously-imported Tables/Models, it only removes the dbt connection
object itself.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-09-10 | Initial release — dbt (Cloud or Core) → ThoughtSpot Tables + Model, first import and resync. Path N (server-side `generate-tml`) and Path Y (`ts dbt build-model`, for `ts_join_*` graphs, `ts_rls_rules` and MetricFlow metrics), with `ts dbt list-models` / `ts dbt inspect` choosing between them. |
