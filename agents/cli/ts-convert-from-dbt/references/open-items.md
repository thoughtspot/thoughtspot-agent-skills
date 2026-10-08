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
| 3 | dbt constructs beyond "models" | VERIFIED live 2026-10-06 — models only |
| 4 | No ThoughtSpot API to enumerate a connection's dbt models | RESOLVED via the Admin API; one residual |
| 5 | Certified-warehouse enforcement point | DEFERRED — no uncertified warehouse on either test cluster |
| 6 | `model_path` / relation-name extraction | VERIFIED 2026-09-01, corrected 2026-09-09 |
| 7 | `generate-sync-tml` has no diff/dry-run | DEFERRED — ThoughtSpot API gap, re-checked 2026-10-06 |
| 8 | `ts metadata report` coverage was narrower than documented | FIXED 2026-08-27 |
| 9 | `ts_*` tag YAML syntax | VERIFIED 2026-09-10 (incl. dbt-core 1.12.4) |
| 10 | `ts dbt delete` crashed on the real 204 | FIXED 2026-08-30 |
| 11 | `model_tables` grouping; what Path N's split actually is | VERIFIED 2026-09-04, **split rule corrected 2026-09-10** |
| 12 | `generate-sync-tml` 500s on resync after structural edits | RESOLVED 2026-10-06 — no 500; TS-only physical columns are removed |
| 13 | dbt Cloud token required a shell env var | RESOLVED 2026-10-06 — both halves (ThoughtSpot half by code review) |
| 14 | MetricFlow metrics → Model formulas | VERIFIED live 2026-09-08; ThoughtSpot side re-tested 2026-10-06 — cluster-dependent |
| 15 | `list-models` emitted `name`, not `alias` | VERIFIED live 2026-10-06 |
| 16 | `ts_ai_context` is a ts-cli extension | RESOLVED 2026-09-09 |
| 17 | The two `build-model` readers disagreed on custom tags | FIXED (never shipped) |
| 18 | Manifest readers missed joins in a parent-dir schema.yml | FIXED 2026-09-10 (never shipped) |
| 19 | Server and client name metric formulas differently | RESOLVED 2026-10-06 — keep label names; `build-model` refuses to mix |
| 20 | dbt `foreign_key` constraints as joins (composite keys) | VERIFIED live 2026-10-06 — `build-model` reads them; native import ignores them |

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

## #3 — dbt construct coverage beyond "models" — VERIFIED live 2026-10-06 (models only)

ThoughtSpot documents the integration only as "provide your existing dbt models".
Undocumented, and untested here:

- **sources** — imported as Tables too, or models only?
- **tests** — surfaced anywhere?
- **exposures** — surfaced anywhere?
- **metrics / Semantic Layer** — see #14: the client-side translator works; the
  server-side importer produced nothing on embed-1 but translates metrics where its
  MetricFlow import is enabled (2026-10-06)
- **snapshots / seeds** — treated as models, or excluded?

Needs a live test against a manifest containing one of each. Do not mark any
coverage-matrix row SUPPORTED without it.

**Scoped 2026-09-10 — the test project cannot settle this, so don't retry it
there.** Inventory of the test dbt Cloud project's compiled manifest (one
job run):

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

**Retested 2026-10-06 on two clusters — ThoughtSpot imports dbt `model` nodes only.**
A purpose-built dbt Core project (2 seeds, 1 source, 1 snapshot, an aliased model,
a time spine) was uploaded as a ZIP to embed-1 Dev and to a MetricFlow-enabled test cluster (Primary org, a Snowflake connection, ZIP_FILE import). Same result on both:

| Requested in `model_tables` | Result |
|---|---|
| seeds, under `model_path: seeds` | 400 `passed models don't have match with the job artifacts` |
| snapshot, under `model_path: snapshots` | same 400 |
| seed / snapshot / raw source table listed under `models` (control) | 400 `<TABLE> table(s) not found for model models` |
| models (incl. one built `from {{ source() }}`) | imported |

So a seed, a snapshot or a bare source cannot become a ThoughtSpot Table through this
integration; a model selecting from it can. A `relationships` test surfaced as a
Model join. **Not tested:** exposures.

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

## #5 — Certified-warehouse enforcement point — DEFERRED

The integration is certified only for Redshift, Databricks, BigQuery and
Snowflake. **Where** an uncertified warehouse fails is unverified — at `ts dbt
create`, at `generate-tml`, or silently with degraded support. Needs a live test
against e.g. Postgres.

Until then, treat "certified" as a prerequisite stated to the user up front, not
something the skill defends against programmatically.

**Deferred 2026-10-06.** Neither test cluster (embed-1, the MetricFlow cluster) has a
connection to an uncertified warehouse — both list Snowflake only. The skill keeps
stating "certified warehouse" as a prerequisite up front.

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

## #7 — `generate-sync-tml` has no diff/dry-run — DEFERRED (ThoughtSpot API gap)

Confirmed via MCP: the response schema is an undocumented **empty object**. There
is no way to ask ThoughtSpot what a resync would change before running it —
unlike `ts snowflake diff` for the Snowflake SV skills.

SKILL.md Steps 10.1–10.5 build a preflight/post-hoc check around the gap
(snapshot → predict → dependency check → resync → re-diff to verify). That is
mitigation, not a fix: the API gap is real, and the empty response is also why
Step 10.5's post-hoc verify is the only evidence a resync did anything at all.

**Re-checked 2026-10-06** on a MetricFlow-enabled test cluster (Primary org, a Snowflake connection, ZIP_FILE import): `dbtGenerateSyncTml` still takes only
`dbt_connection_identifier`, `file_content` and `include_semantic_report` (MCP spec) —
no dry-run. One change from the empty object recorded above: the 200 now lists the
Models and Tables the resync touched (`worksheet_tmls`, `table_tmls`, GUIDs
unchanged). That says *which* objects were rewritten, not *what* changed, so the
skill's snapshot → resync → re-diff mitigation is still the only evidence. Deferred:
nothing on our side can add a preview.

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

## #12 — `generate-sync-tml` 500s on resync after structural edits — RESOLVED 2026-10-06

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
tested directly, as the only changed variable, on a dbt connection in the Prod org:

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

**Retested 2026-10-06 on a MetricFlow-enabled test cluster (Primary org, a Snowflake connection, ZIP_FILE import) — the untested variant, an extra physical column.**
Added `EXTRA_WAREHOUSE_COL` to the warehouse table with DDL, added it to the
ThoughtSpot Table TML (import `OK`), then `generate-sync-tml` with the unchanged dbt
artifacts:

| ThoughtSpot-only addition | Resync | Afterwards |
|---|---|---|
| physical column on the Table | 200, no 500 | **column silently removed** — the Table is reset to dbt's definition |
| formula column on the Model (`TS Only Probe`) | 200, no 500 | **kept**, alongside the 6 metric formulas |

No variant produced the 500 on this cluster, so the original Dev-org failure is not
reproducible. The real hazard is the opposite one: a physical column added in
ThoughtSpot but not in dbt disappears on the next resync without any message. SKILL.md
Step 10 now warns about it; add such columns in dbt instead.

**Column names re-checked 2026-10-06 on the MetricFlow-enabled cluster** (metric import
confirmed active — Model returned as `_METRIC_MODEL`). Background: ThoughtSpot's native
integration supports 16 tags (13 column, 3 join — docs.thoughtspot.com/cloud/26.10.0.cl/
dbt-integration-metadata-tags, unchanged from 26.9.0.cl) and **none of them sets a display
name**; `ts_display_name` is this repo's extension, read by `build-model` only, so its
row below is the expected result, not a defect. The test checked whether any *other*
field the manifest carries is read. Every one was confirmed present in the compiled
manifest; **none was read**:

| Column | Field carrying a friendly name | Model column name |
|---|---|---|
| `AMOUNT` | `config.meta.ts_display_name` | `Amount` |
| `DISCOUNT` | bare `meta.ts_display_name` (legacy syntax) | `Discount` |
| `CUSTOMER_ID` | `config.meta.display_name` | `Customer Id` |
| `IS_FLAGGED` | MetricFlow dimension `label` | `Is Flagged` |
| `ORDER_DATE` | MetricFlow time-dimension `label` | `Order Date` |
| `ORDER_ID` | none (control) | `Order Id` |

Model columns are always the physical name prettified; Table columns keep the raw name.
This matches the 2026-09-10 embed-1 result above, on a second cluster. A Model-column
rename made in ThoughtSpot survives a resync (#19).

**Where the native name does come from — the column itself (2026-10-06).** The display name
is the dbt model's **physical column name**, prettified, and schema.yml `name:` only matters
by matching that column:

| dbt change | Model column | schema.yml `description` carried? |
|---|---|---|
| schema.yml `name: Order Id`, SQL unchanged (column stays `ORDER_ID`) | `Order Id` — just `ORDER_ID` prettified | **no** — the entry matched no column |
| SQL `amount as "Customer Amount"` + schema.yml `name: Customer Amount` | **`Customer Amount`** | yes |

So to get a friendly native name, name the column in the dbt model's SQL. A plain
snake_case alias is enough — `amount as customer_amount` arrives as "Customer Amount" —
which avoids quoted identifiers with spaces in the warehouse. A schema.yml `name:` that
differs from the real column is silently unmatched, and its description and tags with it.

---

## #13 — dbt Cloud token required a shell env var — RESOLVED 2026-10-06

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
(the test dbt Cloud account and project) with no keychain prompt and no per-command
token flag. The artifact cache landed at
`$TMPDIR/ts_dbt_artifact_my-test-proj_<run_id>_manifest.json`, mode `0600`,
and served **one download across four commands** (1.20s uncached → 0.47s
cached); `build-model` reused the same run key for `catalog.json`. This is the
"3–5 fetches become 1" claim, measured.

**ThoughtSpot half — resolved by code review, 2026-10-06.** Every ThoughtSpot API
credential is read in one place, `ThoughtSpotClient._get_credential` (`client.py`):
the profile's env var first, then `keyring` on `thoughtspot-<slug>` / the profile's
username — the same deliberate order as the dbt Cloud half above, for the same
Keychain-prompt reason. A sweep of `ts_cli` for other credential env reads found only
the dbt Cloud token (this item's first half), the password for a *new* user in
`users`/`tenancy`, and a warehouse password in `load` — none a ThoughtSpot login. So
the "some paths" this line used to name do not exist in the current code. Not
exercised keyring-only live: with no env var, a Python-side Keychain read prompts
for the keychain password on every call, which is exactly why env-first is kept.

---

## #14 — MetricFlow metrics → Model formulas — VERIFIED live 2026-09-08; server side cluster-dependent (2026-10-06)

`ts dbt build-model` translates in-scope MetricFlow `metrics:` into Model
formulas — `simple`, `ratio` and `derived`. Verified live: **6/6 barbershop
metrics translated, 0 unmapped**. Handles both manifest dialects (dbt Cloud lists
only `metric.*` nodes under a ratio/derived metric's `depends_on`; Fusion lists
the semantic model directly — resolved transitively).

MetricFlow `entities` also become joins, but **as a fallback only**: emitted for
a table pair no `ts_join_*` test covers, so explicit tags keep authority.

> **Superseded in part, 2026-10-06** — see the end of this item. The server-side result
> below is embed-1's; on a cluster with MetricFlow import enabled the server *does*
> translate metrics (6 of 7, derived skipped). The client-side path is no longer the
> *only* working one, but it is still the more complete one.

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
resolved to `safe_divide([formula_Total Tips], [formula_Total Service Revenue])` *(plain division since 2026-10-06 — NULL, not 0, on a zero denominator, matching MetricFlow)*
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
bare column, and `percentile` aggregations (`median` and `sum_boolean` translated since 2026-10-06).

**2026-10-06 — the server-side result depends on the cluster.** On a MetricFlow-enabled test cluster (Primary org, a Snowflake connection, ZIP_FILE import),
ThoughtSpot's own importer **does** translate metrics (Models come back named
`<TABLE>_METRIC_MODEL`). Same 7-metric project, both paths:

| Metric | ThoughtSpot `generate-tml` | `build-model` (client) |
|---|---|---|
| simple sum ×2, count_distinct | bare column formula + column aggregation | `sum ( … )` / `unique count ( … )` |
| `median` | `median ( [T::C] )` | **now** `median ( [T::C] )` (was unmapped; fixed 2026-10-06) |
| `sum_boolean` | reported IMPORTED, but the formula is the bare boolean column typed ATTRIBUTE — **not** a count | **now** `sum ( if ( [T::C] ) then 1 else 0 )` — imported and returned the right count (fixed 2026-10-06) |
| ratio | `( sum (a) ) / ( sum (b) )` | `safe_divide ( [formula_a] , [formula_b] )` — plain `/` since 2026-10-06 |
| derived | **skipped** | translated |

Four ZIP layouts (CLI's flat 2-file archive; + `semantic_manifest.json`; nested under
`target/`; the user's own archive) gave identical results, so the archive format is
not the variable — embed-1's 0 formulas is the cluster. The client path stays the
default: it covers derived metrics and names formulas by metric label. Naming differs
between the two paths — see #19.

`build-model` also gained `--manifest` (2026-10-06): before it, a dbt Core (ZIP_FILE)
user had no client-side translation at all.

**Caution for anyone re-running this:** on the same cluster, the same project gave 6
formulas at 16:51 and none from 17:58 on 2026-10-06 (Model `_MODEL` rather than
`_METRIC_MODEL`, empty `semantic_report`), after an unrelated cluster setting changed.
A `_METRIC_MODEL` name in the response is the quick tell that the server-side metric
import ran. See #19.

**Semi-additive and timespine settings (PR #506 review, 2026-10-07).** A metric whose measure
carries `non_additive_dimension`, `fill_nulls_with` or `join_to_timespine` used to be
translated as if the setting were absent — a balance measure became `sum ( … )` with
`unmapped: []`, the construct the 2026-09-08 study measured at 25,400 against a true
5,300. All three now route the metric to `unmapped` with the reason (v2 and
legacy-measure shapes; a ratio/derived metric over one is reported too). Never
approximated: a wrong number is worse than a missing one.

---

## #15 — `ts dbt list-models` emitted the model `name`, not its `alias` — VERIFIED live 2026-10-06

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
A full round trip against the test dbt Cloud project ran `list-models --alias` and
`--no-alias` over all 7 model directories: **0 of 7 differ**, because no model
in that project sets `alias:` either. So the live run proves the alias path does
not *regress* an unaliased project, and nothing more; the fix itself rests on
the two unit tests. Confirming it end-to-end needs a dbt project that actually
sets `alias:` — none is available today.

**Verified live 2026-10-06** with a project whose model sets `alias:`, on embed-1
Dev and on a MetricFlow-enabled test cluster (Primary org, a Snowflake connection, ZIP_FILE import): `list-models` emitted the alias (`CLOI_ORDERS_ALIASED`, not
`CLOI_STG_ORDERS`), `generate-tml` created the Table under it, and metric formulas
referencing `[CLOI_ORDERS_ALIASED::…]` imported.

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

---

## #19 — ThoughtSpot's importer and `build-model` name metric formulas differently — RESOLVED 2026-10-06

Found 2026-10-06 on a MetricFlow-enabled test cluster (Primary org, a Snowflake connection, ZIP_FILE import). For the same metric ThoughtSpot's server-side importer writes
`Formula_<metric_name>` (`Formula_tips_total`); `build-model` writes the metric's label
(`Tips Total`), id `formula_<label>`. A Model built one way and later rebuilt the
other way gets a second copy of every metric column rather than an update, and any
Answer built on the first set keeps pointing at it.

Not a bug in either path on its own. **Needs a decision:** whether `build-model` should
adopt ThoughtSpot's naming (renames formulas in Models already built with it) or the
skill should pin one path per Model and say so.

**What controls the server-side name — partly tested 2026-10-06.**

- **`label:` does not.** Every metric in the 16:51 run carried a label (`label: Total Amount`);
  the server still wrote `Formula_total_amount`. MetricFlow `name:` must be an identifier
  (lowercase, underscores), so the friendliest name reachable through it is
  `Formula_total_amount`.
- **Metric-level and measure-level `config.meta` tags (`ts_display_name`, `display_name`),
  and metric name vs. measure name — not yet answerable.** A project built to separate
  them (each metric named differently from its measure; one candidate tag per metric;
  the tags confirmed present in the compiled manifest) imported with **no** metric
  translation at all. A control re-import of the unchanged project that had produced 6
  formulas at 16:51 also produced none (empty `semantic_report`, Model named `_MODEL`
  not `_METRIC_MODEL`), as had a fresh import at 17:58 — so the cluster's MetricFlow
  import was off by then, not the project. Rerun when it is back on.
- **A rename made in ThoughtSpot survives a resync.** Renamed a Model column
  (`Amount` → `Order Amount`) and added a formula with a custom name, then ran
  `generate-sync-tml`: both unchanged. (Tables are reset to dbt on resync — #12 — but Model
  column names are not.) So renaming server-created `Formula_…` columns after import is
  a working fallback; checked on an ordinary column, not yet on a server-created one.

**Answered 2026-10-06 (MetricFlow import re-enabled, 18:17).** Same naming-test project:

| Question | Result |
|---|---|
| Does any dbt field set the server-side formula name? | **No.** The native integration documents no tag for metrics or measures. Beyond that, metric `label`, measure `label`, and `config.meta` `ts_display_name` (this repo's extension) / `display_name` on a metric or a measure were all in the compiled manifest; none appears anywhere in the imported Model. The name is always `Formula_` + a technical name. |
| Which technical name? | **Both, when they differ.** A metric named differently from its measure produces two formulas — `Formula_m_amount` (the measure, `[TABLE::AMOUNT]`) and `Formula_total_amount` (the metric, `[formula_Formula_m_amount]`): 9 formula columns for 5 metrics. With metric name = measure name (the 16:51 run) there is one per metric. |
| Rename the **column** of a server-created formula (`Formula_total_amount` → `Total Amount`), then resync | **Kept**, no duplicate; search on `[Total Amount]` returned the right value (725.5). |
| Rename the column **and the formula's own `name`** (`Formula_m_discount` → `Total Discount`), then resync | Kept, **but the resync re-created `Formula_m_discount`** — a duplicate. |

**Practical rule for a friendly name on the server-side path:** name each metric the same
as its measure in dbt (avoids the doubled formulas), then rename only the Model
**column** in ThoughtSpot — never the formula's `name`. The column rename survives
resyncs. The decision this item asks for is unchanged.

**Same for ordinary columns (2026-10-06):** the native integration has no display-name
tag at all (its 16 supported tags are listed in #12), and it does not fall back to
other manifest fields either — `display_name` meta and MetricFlow dimension `label`
were ignored too; it prettifies the raw name (#12). So "dbt cannot set the name" holds
for `generate-tml` as a whole, not just metrics; only the `Formula_` prefix is
metric-specific. `ts_display_name` (columns) and metric `label` work through
`build-model`, where this repo reads them.

**Metric names are capped by dbt, not ThoughtSpot (2026-10-06).** dbt-core 1.12.5 rejects a
metric `name: Total Amount` ("cannot contain spaces") and `name: Total_Amount` ("names may
only contain lower case letters, numbers, and underscores… must start with a lower case
letter"); measure names likewise. So on the native path the friendliest metric formula
name possible is `Formula_total_amount`; renaming the Model column afterwards (above) is
the only way past it. Ordinary columns are different — see #12: name them in the model
SQL.

**Decision and fix, 2026-10-06.** Keep `build-model`'s label-based names: dbt cannot
make the native names friendlier (above), so matching them would trade readable names
for nothing. Instead `build-model --model-guid` now **refuses** to update a Model that
already holds native `Formula_…` metric formulas (other than names it is itself about
to write), before any import, and says why; `--allow-native-metric-formulas` overrides.
An unreadable Model is warned about, not refused. Pinned by
`TestBuildModelRefusesNativeMetricFormulas` (the refusal and warn tests fail without
the guard) and checked live against a Model the native import had just created: it
found all 6 `Formula_…` metrics and stopped with exit 1. New Models are not checked.

---

## #20 — dbt `foreign_key` constraints as joins, incl. composite keys — VERIFIED live 2026-10-06

dbt's `relationships` test is single-column, so a composite-key join had no dbt form
(ts-convert-to-dbt #5). dbt model constraints do: `type: foreign_key` with `columns`,
`to`, `to_columns` (dbt 1.9+; dbt-core 1.12.5 keeps all three in the manifest).

| Path | Reads constraints? | Evidence (MetricFlow cluster, 2026-10-06) |
|---|---|---|
| Native `generate-tml` | **No** — composite *or* single-column | a project joined only by constraints imported as 3 separate Models with no joins |
| `build-model` | **Yes** | composite + single-column round trip identical, same query results (to-dbt #5) |

**Reader** (`ts_cli/dbt/constraint_joins.py`): model- and column-level foreign keys on
in-scope models; precedence `ts_join_*` relationships tests → constraints → MetricFlow
entities, per table pair; type/cardinality from the `ts_join_options` model meta tag,
else LEFT_OUTER / MANY_TO_ONE. **Two forms of `to`:** `ref('model')` in a parse-only
manifest, but the **resolved relation** (`ANALYTICS_DB.SCHEMA.TABLE`) after `dbt build` /
`docs generate` — i.e. every dbt Cloud artifact. The first cut read only `ref()`; the
live round trip caught it (every constraint join would have vanished silently), and the
reader now resolves both. `ts dbt inspect` uses the same reader, reports
`constraint_joins[]`, and recommends Path Y when any exist.

