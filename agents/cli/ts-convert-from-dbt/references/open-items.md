# Open Items — ts-convert-from-dbt

Unverified API/product behaviour and known gaps. Per `.claude/rules/api-research.md`,
each item records whether it was resolved via the SpotterCode MCP, a live test, or
is still open.

Item **numbers are permanent** — SKILL.md and coverage-matrix.md cite them by
number, so a resolved item keeps its heading rather than being deleted or
renumbered. Resolved items are condensed to their verdict and the finding worth
keeping; the full investigation narratives were compressed 2026-09-09.

## Status at a glance

| # | Item | Status |
|---|---|---|
| 1 | Worksheet vs. Model terminology | VERIFIED via MCP 2026-08-27 |
| 2 | `include_semantic_report` scope | VERIFIED via MCP 2026-08-27 |
| 3 | dbt constructs beyond "models" | **OPEN** |
| 4 | No ThoughtSpot API to enumerate a connection's dbt models | RESOLVED via the Admin API; one residual |
| 5 | Certified-warehouse enforcement point | **OPEN** |
| 6 | `model_path` / relation-name extraction | VERIFIED 2026-09-01, corrected 2026-09-09 |
| 7 | `generate-sync-tml` has no diff/dry-run | **OPEN** — real API gap, mitigated |
| 8 | `ts metadata report` coverage was narrower than documented | FIXED 2026-08-27 |
| 9 | `ts_*` tag YAML syntax | VERIFIED 2026-09-10 (incl. dbt-core 1.12.4) |
| 10 | `ts dbt delete` crashed on the real 204 | FIXED 2026-08-30 |
| 11 | `model_tables` grouping; what Path N's split actually is | VERIFIED 2026-09-04, **split rule corrected 2026-09-10** |
| 12 | `generate-sync-tml` 500s on resync after structural edits | **OPEN** — formula columns exonerated 2026-09-10 |
| 13 | dbt Cloud token required a shell env var | FIXED; ThoughtSpot half **OPEN** |
| 14 | MetricFlow metrics → Model formulas | VERIFIED live 2026-09-08 |
| 15 | `list-models` emitted `name`, not `alias` | FIXED 2026-09-09 — no aliased project to test against |
| 16 | `ts_ai_context` is a ts-cli extension | RESOLVED 2026-09-09 |
| 17 | The two `build-model` readers disagreed on custom tags | FIXED (never shipped) |
| 18 | Manifest readers missed joins in a parent-dir schema.yml | FIXED 2026-09-10 (never shipped) |

**Five genuinely open: #3, #5, #7, #12, and the ThoughtSpot half of #13.**
#3 needs a purpose-built dbt project (the test project has no exposures,
snapshots or seeds — see the item), #5 an uncertified warehouse, #12 a live
instance; #7 is a ThoughtSpot API gap this skill can only mitigate. #18 was
found and fixed the same day.

---

## #1 — Worksheet vs. Model terminology — VERIFIED via MCP 2026-08-27

Worksheets are deprecated from 10.4.0.cl and removed in 10.12.0.cl+; "even
adding a dbt connection will result in the creation of a Model". The REST API
keeps the legacy field names (`import_worksheets`, `worksheets`,
`semantic_report`) for backward compatibility.

**Decision:** prose says "Model"; commands use the literal API field names.

---

## #2 — `include_semantic_report` scope — VERIFIED via MCP 2026-08-27

Semantic-report support is "supported only for Snowflake and Databricks
connections", per `dbtGenerateTml`'s own field description. Redshift and BigQuery
get no breakdown. No CLI-side enforcement was added — the API ignores the flag
rather than erroring, though that tolerance is itself unconfirmed against a live
Redshift/BigQuery connection.

---

## #3 — dbt construct coverage beyond "models" — OPEN

ThoughtSpot documents the integration only as "provide your existing dbt models".
Undocumented, and untested here:

- **sources** — imported as Tables too, or models only?
- **tests** — surfaced anywhere?
- **exposures** — surfaced anywhere?
- **metrics / Semantic Layer** — see #14: the client-side translator works, the
  server-side importer produced nothing
- **snapshots / seeds** — treated as models, or excluded?

Needs a live test against a manifest containing one of each. Do not mark any
coverage-matrix row SUPPORTED without it.

**Scoped 2026-09-10 — the test project cannot settle this, so don't retry it
there.** Inventory of dbt Cloud project 130012's compiled manifest (run
510723216):

| Construct | Count |
|---|---|
| `model` nodes | 19 |
| `test` nodes | 18 |
| sources | 14 |
| metrics / semantic_models | 13 / 9 |
| **exposures, saved_queries, unit_tests** | **0** |
| **snapshots, seeds** (absent from `resource_type`) | **0** |

So four of the six unknowns — exposures, snapshots, seeds, and anything
`saved_queries`-shaped — have no instance in the only project available, and no
amount of re-running the import here will produce one. Settling #3 needs a
purpose-built dbt project containing one of each.

Sources are present (14) but the observation is weak: `generate-tml` takes an
explicit `--model-tables` list, and a 7-table barbershop import produced exactly
7 Tables and no source-derived extras (verified 2026-09-10). That shows sources
are not *implicitly* added alongside the models that select from them; it does
not show what happens if a source is named directly.

---

## #4 — No ThoughtSpot API to enumerate a connection's dbt models — RESOLVED (Admin API), one residual

No **ThoughtSpot** endpoint answers "which dbt models could this connection
import" ahead of `generate-tml` — `dbtSearch` lists connections, not their
models. The original plan was dbt Cloud's GraphQL **Discovery API**.

**What shipped instead (2026-09-04) — the Admin API v2.** `ts dbt list-models`
finds the latest successful run (`GET /runs/` filtered `status=10`, `limit=1`,
`order_by=-created_at`, optionally `environment_id`), downloads that run's
`manifest.json`, and groups by directory. This sidesteps all three unverified
Discovery API questions (query shape, token scope, pagination): the token is the
same PAT the connection already uses, and no GraphQL is involved. `ts dbt
inspect`, `build-model` and `trigger-job` share the resolution path via
`ts_cli/dbt/cloud_api.py`, which also caches each run's artifacts so a round trip
downloads `manifest.json` once rather than 3–5 times.

**Residual:** the DBT_CLOUD path needs a *successful* run to exist — a project
whose last run failed gets `No successful runs found …` and must fall back to
asking the user. The offline half is covered: `--manifest` reads a local
`manifest.json`, `target/` dir or project ZIP with no profile, token or network.

**Related, closed 2026-08-30:** `dbt/search` never echoes back
`dbt_url`/`account_id`/`project_id`/`dbt_env_id` after connection creation, so
every session re-typed them. `ts profiles add --platform dbt-cloud` now persists
them.

---

## #5 — Certified-warehouse enforcement point — OPEN

The integration is certified only for Redshift, Databricks, BigQuery and
Snowflake. **Where** an uncertified warehouse fails is unverified — at `ts dbt
create`, at `generate-tml`, or silently with degraded support. Needs a live test
against e.g. Postgres.

Until then, treat "certified" as a prerequisite stated to the user up front, not
something the skill defends against programmatically.

---

## #6 — `model_path` / relation-name extraction — VERIFIED 2026-09-01, corrected 2026-09-09

The `model_tables` entry format, confirmed against a real dbt-fusion manifest v12:

- `model_path` = the **directory** of `original_file_path`, not the file
- `model_name` = the last directory segment
- `tables` = upper-cased **materialised** names

**The correction that matters.** The original finding said `tables` = model
`name`, which held only because the test project set no aliases. It must be
`alias or name`: a model with `alias:` set (directly, via `+alias`, or via
`generate_alias_name`) materialises under the alias, and that is the only name
ThoughtSpot matches. Passing the file name instead fails the whole call with
HTTP 400 `"STG_APPOINTMENTS, … table(s) not found"` — live 2026-09-09, where
barbershop's `stg_appointments` builds `APPOINTMENTS`. Fixed in #15.

`relation_name` is not needed — wrong granularity (per-model, not per-directory).

---

## #7 — `generate-sync-tml` has no diff/dry-run — OPEN

Confirmed via MCP: the response schema is an undocumented **empty object**. There
is no way to ask ThoughtSpot what a resync would change before running it —
unlike `ts snowflake diff` for the Snowflake SV skills.

SKILL.md Steps 10.1–10.5 build a preflight/post-hoc check around the gap
(snapshot → predict → dependency check → resync → re-diff to verify). That is
mitigation, not a fix: the API gap is real, and the empty response is also why
Step 10.5's post-hoc verify is the only evidence a resync did anything at all.

---

## #8 — `ts metadata report`'s real coverage was narrower than documented — FIXED 2026-08-27

A prototype did column-deletion impact analysis across 13 passes. The shipped
`ts metadata report` implemented **4**, one partially, and 8 not at all. Worse,
two things were dead code: `classify_dependent` implemented a real HIGH/MEDIUM/LOW
rule engine that was **never called** (every dependent got a hardcoded `LOW`),
and the column-security half of the STOP condition could never fire because
`csr_hits` was declared but never populated.

**Fixed** in `ts_cli/report/`: added `impact_probes.py` with the 8 missing passes
(column security rules, formula/template variables, business terms + AI memory,
SQL-view scan + downstream dependents, custom actions, scheduled reports, the
formula-cascade walk); added the pure `find_*_column_uses` helpers to
`tml_probes.py`; wired `classify_dependent` in with real signals; populated
`csr_hits`. 27 new unit tests.

**Still not backed by any probe:** chart-axis usage and dormancy
(`modified_at` is always `None`). Both are edge cases — a column referenced
*only* via a chart axis, or a dormancy judgement call — and neither was in the
prototype's 13 passes either.

**Impact here:** Step 10.3's dependency check now covers all 13 passes with a real
risk rating, and STOP fires on either RLS or CSR findings.

---

## #9 — `ts_*` metadata tag YAML syntax — VERIFIED 2026-09-10

**Verified (dbt Cloud 2026-08-30, and `dbt-fusion parse` locally 2026-08-27):**
column-level `config: {meta: {...}}` and `data_tests:` + `arguments: {to, field}`
+ `config: {meta: {ts_join_*}}` both compile clean. The bare
`meta:`/`tests:`/`to:`/`field:` shape ThoughtSpot's own docs example shows
produces hard parse **errors**.

**dbt-core settled 2026-09-10.** Tested against real **dbt-core 1.12.4** +
dbt-snowflake 1.12.0: a generated project parses clean, and dbt-core's own
`target/manifest.json` carries the model `alias`, all four `ts_*` column tags
(`ts_column_type`, `ts_index_type`, `ts_ai_context`, `ts_display_name`) and all
7 `ts_join_*` relationship tests with their meta intact. Feeding that manifest
back to `ts dbt list-models` returned the aliased table names.

So the current nested syntax is **not** fusion-only, and the fallback to the
older bare shape that the "dbt 1.7 and earlier" line implied might be needed is
not needed. Older dbt-core lines remain untested, but the concern that motivated
this item — that the syntax might be unrecognised outside Fusion — is answered.

Mirrored, with the reverse direction's detail, in `ts-convert-to-dbt` #1/#8.

---

## #10 — `ts dbt delete` crashed on the real 204 response — FIXED 2026-08-30

`delete` returns **204 No Content**, unlike `create`/`update`/`generate-tml`/
`generate-sync-tml` which all return 200 with a body. `delete_connection` called
`resp.json()` unconditionally and raised `JSONDecodeError`.

**Why it shipped uncaught:** the test fixture faked a valid JSON body for every
endpoint. Added a `NO_BODY` sentinel that raises from `.json()` like a real 204,
and pointed the delete test at it.

---

## #11 — `model_tables` is directory-grouped, and what actually triggers Path Y — VERIFIED 2026-09-04

**The format.** 12+ path shapes returned HTTP 400 `"passed models don't have
match with the job artifacts"` before this was understood: `model_tables` takes
one entry per **directory**, listing every model in it — not one entry per file.
Every failed attempt had been a single-model file path. See #6 for the fields
and the alias correction.

Verified live: 5 models across 3 directories imported in one call.
`generate-sync-tml` takes no `model_tables` at all and imports everything — the
trade-off is that `generate-tml` can scope per directory (`--import-worksheets
ALL/NONE/SELECTED`).

**The split rule — CORRECTED 2026-09-10 by direct observation.**

Path N emits **one Model per FK-source table** (a table with outgoing
`ts_join_*` edges), each containing that table plus its **direct, one-hop**
targets. Shared dimensions are **duplicated** into every Model that references
them.

Measured on `models/staging/barbershop` (7 models, 7 joins):

| Model | tables |
|---|---|
| `APPOINTMENTS_MODEL` | APPOINTMENTS, BARBERS, CUSTOMERS, SERVICES |
| `PRODUCT_SALES_MODEL` | PRODUCT_SALES, BARBERS, CUSTOMERS, PRODUCTS |
| `TRANSACTIONS_MODEL` | TRANSACTIONS, APPOINTMENTS |

Note `TRANSACTIONS_MODEL` stops at `APPOINTMENTS` — it does **not** transitively
pull in that table's own targets. One hop, not closure. And BARBERS/CUSTOMERS
appear in two Models at once.

> **The earlier "FK-connected component" reading here was wrong.** These 7
> tables are a *single* connected component — APPOINTMENTS and PRODUCT_SALES
> both reach BARBERS and CUSTOMERS — yet the directory split into 3. The old
> note even said "3 fact tables sharing dimensions" and then concluded
> ThoughtSpot "splits on FK-**dis**connected fact tables", which its own data
> contradicts.
>
> The fact-table rule also **retro-explains** the observation that motivated the
> wrong theory: `models/marts/core` has exactly one FK source (`fct_orders`) and
> returned exactly one Model. Both data points fit; connectivity fits neither.

Because the rule is deterministic, the split is now **predicted rather than
discovered after the import**: `ts dbt inspect` reports `path_n_model_count`
(distinct FK-source tables) and says so in `reasons` — "Path N would split this
directory into 3 Models …". Verified live against both directories.
Tests: `TestPathNModelCount`.

**Path Y verified 2026-09-04:** `ts dbt build-model` produced a single unified
7-table Model with all 7 `ts_join_*` tests applied, including the chasm joins
(BS_CUSTOMERS and BARBERS each joined from both APPOINTMENTS and PRODUCT_SALES).

**Also verified 2026-08-30** (dbt-fusion manifest v12, server-side sync):
`ts_column_type`, `ts_aggregation`, `ts_synonym` and plain dbt `description:`
are all honoured. Not verified server-side: `ts_join_cardinality`/`ts_join_type`,
`ts_hidden`, `ts_format_pattern`, the geo tags.

**What Path N drops — measured 2026-09-10, same directory, same day as a Path Y
run, so the two are directly comparable:**

| tag / feature | Path N (`generate-tml`) | Path Y (`build-model`) |
|---|---|---|
| unified Model | **no** — 3 Models | yes — 1 Model, 7 tables |
| `ts_column_exclude` | **ignored** — `BARBERS.HIRE_DATE` present as "Hire Date" | honoured — column left out |
| `ts_display_name` | **ignored** — emits the raw name prettified | honoured |
| MetricFlow metrics | **0 of 6** | 6 of 6 (incl. ratio + derived) |
| `ts_rls_rules` | not applied (see below) | applied, `status = OK` |
| `ts_column_type`, `ts_aggregation`, `ts_synonym`, `description` | honoured | honoured |

The `ts_display_name` result needs care to read: `APPOINTMENT_DATETIME` is tagged
`'Appointment Time'` and `APPOINTMENT_TIME` is tagged `'Appointment Time of Day'`.
Path N's Model contains **both** "Appointment Datetime" and "Appointment Time",
and **no** "Appointment Time of Day" — i.e. the two raw names prettified, not
the tags. Seeing "Appointment Time" in the output is a coincidence of
prettification, not evidence the tag was read.

**One piece of good news about RLS.** `BARBERS` still carries its `rls_rules`
after a later `generate-tml` re-run over the same connection, so a Path N
regeneration does **not** clobber Table-level RLS that Path Y previously applied.
(The rules were created by Path Y's explicit "Applying ts_rls_rules to BARBERS"
step — Path N is not shown here to create them, only to leave them alone.)

---

## #12 — `generate-sync-tml` 500s on resync after structural edits — OPEN, narrowed

**Observed 2026-08-31 (Dev org):** a resync against a connection whose Model had
manual ThoughtSpot additions returned
`500 — "Error occured during TML import"`. It persisted after those additions
were removed.

**Narrowed 2026-09-01 (Prod org).** Two clean runs isolated it:

- resync immediately after a first import, no edits → **success**, identical GUIDs
- full round trip with **metadata-only** UI edits (model + column descriptions,
  a synonym) → export → `diff` → apply to dbt → dbt Cloud job → resync →
  **success**, identical GUIDs, synonym confirmed in the post-sync export

**So the trigger is ThoughtSpot-only *structural* additions** — formula columns
or extra physical columns dbt does not know about — not metadata enrichment.
Metadata enrichment is the primary round-trip use case and it works.

**Formula columns EXONERATED — controlled test, 2026-09-10.** Previously this was
inferred from a Model that merely *happened* to carry formulas. It has now been
tested directly, as the only changed variable, on connection `fe5ebaf8-…` (Prod):

1. Fresh `generate-tml --import-worksheets ALL` → 7 Tables + 3 Models.
2. Baseline `generate-sync-tml` with no edits → **success**, identical GUIDs.
3. Added a ThoughtSpot-only formula column (`TS Only Probe`, `expr: 1`,
   MEASURE/SUM) to `APPOINTMENTS_MODEL` → import returned `columns_added: 1`.
4. `generate-sync-tml` again → **success**, identical GUIDs, no 500.
5. Re-exported the Model → **the formula column survived**: 37 columns,
   `formulas: ['TS Only Probe']` still present.

So a ThoughtSpot-only formula column neither breaks the resync nor is silently
dropped by it. That is the primary enrichment use case and it is safe.

**Still unresolved:** what *did* cause the Dev-org 500. The remaining untested
variant is an **extra physical column** — one present in the warehouse table but
absent from the dbt model — which needs warehouse DDL to arrange and was not
reproducible here. The original Dev-org connection state was never isolated.

**Incidental finding (this is the observation that corrected #11).** Step 1 split
`models/staging/barbershop` — one directory, 7 models — into **3** Models:
`APPOINTMENTS_MODEL`, `TRANSACTIONS_MODEL`, `PRODUCT_SALES_MODEL`: one per
**FK-source table**, not per connected component (all 7 are one component). See
#11 for the table-by-table breakdown.

**Also learned:** Table TML rejects a formula column outright —
`Compulsory Field table->columns(Nth)->db_column_name is not populated`
(error_code 14528). Formulas are a Model-level construct; a structural addition
to a *Table* has to be a real physical column.

The skill documents that a resync may fail when the Model carries structural
additions not representable in dbt.

---

## #13 — dbt Cloud token required a shell env var — FIXED (dbt Cloud half); ThoughtSpot half OPEN

**dbt Cloud half done.** Every `ts dbt` command resolves the token from the OS
credential store: the profile's `token_env` env var → `keyring.get_password` on
the profile's recorded `keychain_service`/`keychain_account` → the
`--access-token-env` var. A user who ran `ts profiles add --platform dbt-cloud`
needs no `~/.zshenv` export. `keyring` is imported lazily and failures degrade to
the env-var path.

**Why the env var is still checked first, deliberately:** on macOS the Keychain
item's partition list trusts only `/usr/bin/security`, so a Python-side read
prompts for the keychain password on **every call**. The `~/.zshenv` line
`ts profiles add` emits shells out to `security`, so the value is already in the
environment and no prompt appears.

Resolution now lives in `ts_cli/dbt/cloud_api.py` (`resolve_dbt_profile`,
`token_from_keychain`) — one implementation shared by `list-models`, `inspect`,
`build-model` and `trigger-job`, replacing three near-identical copies. That
consolidation also fixed a real bug: the lookup passed the raw profile **name**
where a slug was required, so any profile whose name was not already slug-shaped
("My Project") silently found no credential and reported it as "none stored".

**Live 2026-09-09:** the consolidated resolver was exercised end-to-end by
`list-models`, `inspect` and `build-model` against profile `my-test-proj`
(account 43692, project 130012) with no keychain prompt and no per-command
token flag. The artifact cache landed at
`$TMPDIR/ts_dbt_artifact_my-test-proj_510723216_manifest.json`, mode `0600`,
and served **one download across four commands** (1.20s uncached → 0.47s
cached); `build-model` reused the same run key for `catalog.json`. This is the
"3–5 fetches become 1" claim, measured.

**Still open:** the ThoughtSpot-side half — `ts` itself still expects its own
token via env var on some paths.

---

## #14 — MetricFlow metrics → Model formulas — VERIFIED live 2026-09-08

`ts dbt build-model` translates in-scope MetricFlow `metrics:` into Model
formulas — `simple`, `ratio` and `derived`. Verified live: **6/6 barbershop
metrics translated, 0 unmapped**. Handles both manifest dialects (dbt Cloud lists
only `metric.*` nodes under a ratio/derived metric's `depends_on`; Fusion lists
the semantic model directly — resolved transitively).

MetricFlow `entities` also become joins, but **as a fallback only**: emitted for
a table pair no `ts_join_*` test covers, so explicit tags keep authority.

**The finding worth keeping (coverage-matrix L11).** ThoughtSpot's own
**server-side** MetricFlow importer produced **nothing** on the tested instance —
0 formulas, empty `semantic_report`, numeric columns not even typed as measures —
across three connection shapes (v2 nested, hand-converted legacy,
dbt-Cloud-compiled legacy), via both REST and the Data-workspace UI. The
client-side translator is the only working path, and this is the strongest
evidence against ts-convert-to-dbt #2's secondary artifact being read at all.

**Re-confirmed 2026-09-10 by a direct A/B on one project, one day, one Org**
(Embed-1-Prod, `models/staging/barbershop`, 6 MetricFlow metrics):

| path | metrics → Model formulas |
|---|---|
| **Y** — `ts dbt build-model` (client-side) | **6 of 6** |
| **N** — ThoughtSpot `generate-tml` (server-side) | **0**, across all 3 Models it produced |

Path N split the directory into `APPOINTMENTS_MODEL`, `TRANSACTIONS_MODEL` and
`PRODUCT_SALES_MODEL`, and every one came back with an empty `formulas: []` —
including `TRANSACTIONS_MODEL`, which is the Model that *owns* these metrics
(all six reference `TRANSACTIONS` columns). This is a cleaner result than the
2026-09-08 one, which relied on a project whose metrics were less clearly
attributable.

The Path Y output is real, not shape-only: the ratio and derived metrics
resolved to `safe_divide([formula_Total Tips], [formula_Total Service Revenue])`
and `[formula_Total Service Revenue] - [formula_Total Discounts Given]`, using
id-references per the repo's TML invariant rather than display names.

**A distinction worth stating plainly, because it is easy to blur:** dbt's
**time spine** model governs only whether *dbt itself* can parse a project
containing semantic models (ts-convert-to-dbt #8). It has no bearing on whether
ThoughtSpot consumes anything. The barbershop project has a `time_spine_daily`
model and parses fine — and ThoughtSpot's server-side importer still produced
zero formulas from it. dbt-side validity and ThoughtSpot-side consumption are
independent.

**Not translated** (reported on stderr, never dropped silently): `cumulative` and
`conversion` metrics, metric-level and input-metric filters, `offset_window`/
`offset_to_grain`, a simple metric whose `expr` is a SQL expression rather than a
bare column, and `median`/`percentile`/`sum_boolean` aggregations.

---

## #15 — `ts dbt list-models` emitted the model `name`, not its `alias` — FIXED 2026-09-09

`_group_manifest_models` built each `tables[]` entry from `node["name"].upper()`,
so a project setting `alias:` got a 400 from `generate-tml` naming tables that
"do not exist". It went unnoticed because the only project it had been run
against (jaffle_shop) sets no aliases, so `name == alias` for every node.

**Fixed:** the grouping moved to `ts_cli/dbt/inspect.py::group_manifest_models`,
which emits `(alias or name).upper()`. `--no-alias` restores the old behaviour
for a project whose manifest aliases are wrong. Pinned by a pure test and a
CLI-level test, both confirmed to fail against the pre-fix code.

See #6 for why the alias is the only name ThoughtSpot matches.

**Live 2026-09-09 — the fix is still not exercised by a real aliased project.**
A full round trip against project 130012 ran `list-models --alias` and
`--no-alias` over all 7 model directories: **0 of 7 differ**, because no model
in that project sets `alias:` either. So the live run proves the alias path does
not *regress* an unaliased project, and nothing more; the fix itself rests on
the two unit tests. Confirming it end-to-end needs a dbt project that actually
sets `alias:` — none is available today.

---

## #16 — `ts_ai_context` is a ts-cli extension — RESOLVED 2026-09-09

**Confirmed by the skill author:** `ts_ai_context` is **not native to the
product**. It is a gap filed with ThoughtSpot that has not shipped as a metadata
tag, which is why it is absent from
docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags — a page that
carries the complete set (13 column tags + 3 join tags, read 2026-09-09).

So the conservative labelling was correct: the server-side sync does not read it,
and only the client-side `build-model` commands do. A Path N import drops it
silently. This also settles ts-convert-to-dbt #15.

---

## #17 — The two `build-model` readers disagreed on the custom tags — FIXED 2026-09-09 (never shipped)

`ts dbt build-model` (manifest) and `ts dbt-export build-model` (schema.yml) are
the two return legs, and they read different subsets of the ts-cli extension
tags: the schema.yml reader ignored `ts_display_name` and `ts_column_exclude`
entirely. A dbt-side edit to either was therefore silently lost on the offline
leg but honoured on the dbt Cloud one — the same project producing two different
Models depending on which command ran.

**Fixed:** both readers go through the same shared inverse
(`tml_properties_from_ts_meta`), and `TestCustomTagReaderParity` asserts the two
paths agree tag-for-tag.

**A correction this surfaced.** An earlier revision of these notes claimed the
TML schema "explicitly warns against emitting" all four of `is_hidden`,
`calendar`, `currency_type` and `geo_config`. Verification showed only the first
two carry such a warning — `currency_type` says the opposite, and `geo_config`
says nothing at all. That over-generalisation was what kept all four unmapped.
See ts-convert-to-dbt #9 for the exact wording of each.

---

## #18 — The manifest readers missed joins declared in a parent-directory schema.yml — FIXED 2026-09-10 (never shipped)

Found while parsing a `ts dbt-export build` project with real dbt-core (#8 in
ts-convert-to-dbt). The two path predicates in `dbt/manifest.py` and
`dbt/inspect.py` disagree about where a directory's join tests live:

| | predicate | node it matches |
|---|---|---|
| models | `os.path.dirname(original_file_path) == model_path` (**exact**) | `models/staging/stg_appointments.sql` |
| `ts_join_*` tests | `model_path in original_file_path` (**substring**) | `models/schema.yml` |

A project whose `schema.yml` sits **above** its `.sql` files satisfies neither
value of `--model-path`:

```
--model-path models/staging  ->  7 models, 0 join tests
--model-path models          ->  0 models, 7 join tests
```

`ts dbt-export build` generates exactly that layout — `.sql` under
`models/staging/`, `schema.yml` at `models/`. So a project this repo *generates*
cannot be inspected correctly through the manifest path.

**Impact.** Joins are a Path Y signal. A generated project with a join graph but
no `ts_rls_rules` and no MetricFlow metrics produces **no reasons at all** and is
recommended **Path N** — which drops `ts_formula` / `ts_display_name` /
`ts_column_exclude`. Silent fidelity loss, valid output, no error. The barbershop
round trip only escaped it because `stg_barbers` carries `ts_rls_rules`, which
forced Y on its own.

**Not an `inspect` bug specifically.** `manifest.py` L45/L155 use the same
substring predicate, so `ts dbt build-model` misses the same joins — the
"inspect cannot promise a join graph build-model won't find" invariant holds.
Both manifest readers share the blind spot.

**Unaffected:** `ts dbt-export build-model --schema-yml` reads the YAML directly
and found all 7 joins in the same project — the offline return leg is fine.

**FIXED — attribute the test by `attached_node`.** Both predicates moved into a
new `ts_cli/dbt/node_paths.py` that `manifest.py` and `inspect.py` now share, so
they cannot drift again:

- a **model** is placed by its own `.sql` dirname, exact
- a **test** is placed by the model its `attached_node` names — the join's
  `from` side, which dbt populates regardless of which file declares the test

`attached_node` was chosen over `depends_on.nodes` because the latter also holds
the `to` model, which would report a cross-directory join under both directories
and hand `build-model` a join whose other table is not in the Model it is
assembling. When `attached_node` is absent (older manifests) it falls back to the
previous substring match rather than reporting zero.

Rejected: co-locating `schema.yml` with the models in `ts dbt-export build` —
Case B's project-state walk expects `models/schema.yml` (#10), so that moves the
problem rather than fixing it.

**Verified** on both real manifests: the generated project went 0 → 7 joins and
now recommends Path Y for the join reason; the co-located source project is
unchanged at 7; `inspect` and `build_model_tml_from_manifest` return the same
count on both. Mutation-checked — reverting the predicate fails 6 of the new
tests. Also fixed alongside: `extract_model_rls_from_manifest` used a substring
match on model nodes, disagreeing with `inspect.rls_models` and sweeping in a
sibling directory sharing a prefix.

Tests: `tests/test_dbt_node_paths.py`.
