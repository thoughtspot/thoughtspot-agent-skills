# Backlog

Improvement ideas identified but not yet scheduled. Each item includes context on
why it matters and what the approach would be.

> **Tableau converter parked 2026-07-23.** All done items archived; remaining open items
> (BL-020, BL-024, BL-069-residual, BL-071/072 remainders, BL-076, BL-091, BL-094) are
> deferred with per-item park notes below.

---

## Archived (completed)

Done items have moved to [`backlog-archive.md`](backlog-archive.md):
- BL-001 — Pre-import TML lint for all conversion skills — Done (2026-06-12)
- BL-002 — NULL fall-through in Tableau IF/ELSE formula translation — Done (2026-06-12) — resolved as "no auto-guard"
- BL-003-UMBRELLA — Complete Semantic View → ThoughtSpot mapping coverage — Done — BL-003, BL-003b, BL-003c, BL-004, GAP-13 implemented (2026-06-13); GAP-04/05/08/10 mapped + SKILL.md parsing (2026-06-14); live-verified via BL018_TEST_SV (2026-06-14); remaining LOW gaps (GAP-06/07/09/11) tracked in `references/open-items.md`
- BL-003 — Double aggregation translation (metric-referencing-metric) — Done (2026-06-13) — identifier resolution engine adds group_aggregate wrapping with group_* shorthand
- BL-003b — Parse and map `facts (...)` section from Semantic View DDL — Done (2026-06-13) — Step 4 extracts facts block; facts become standalone formulas in Step 8
- BL-003c — Metric-references-fact resolution in formula translation — Done (2026-06-13) — identifier resolution pre-pass resolves fact references to formula names
- BL-004 — Handle semantic views with no joins defined — Done (2026-06-13) — joinless SV guard skips Step 7 and produces model with no joins
- BL-006 — BOOL vs BOOLEAN mapping inconsistency for Snowflake connections — Done (2026-06-12)
- BL-012 — Cross-skill conversion consistency: parity + auditor (extends BL-001) — Done (2026-06-12)
- BL-017 — Cursor mirror sync: close version gaps or retire runtime — Done (2026-06-14) — Cursor runtime retired
- BL-018 — Close remaining SV→TS mapping gaps (range joins, model filters, SQL View for subquery SVs) — Done (2026-06-14) — documentation, SKILL.md parsing, and live verification complete
- BL-009 — Tableau conversion mapping gaps (functions, dynamic sets, geospatial, sources) — Complete (2026-06-14) — all 5 phases shipped
- BL-010 — ts-load-source-data skill (generic Snowflake/Databricks loader) — v1 shipped (2026-06-26) — Snowflake loading complete
- BL-013 — Metadata-only sync mode for converters — Superseded by BL-021
- BL-042 — Tableau REST API integration — Complete (2026-06-26) — PR #121/#122
- BL-044 — Tableau: detect orphan inherited calcs — Complete (2026-06-27)
- BL-045 — Tableau: blend post-aggregation semantics warning — Complete (2026-06-27)
- BL-046 — Tableau: formula translation determinism — Complete (2026-06-27) — ts-cli v0.17.0
- BL-047 — Tableau: audit formula complexity reporting — Complete (2026-06-27)
- BL-048 — Tableau: user review checkpoint — Complete (2026-06-27)
- BL-049 — Tableau: Phase 2 pipeline performance — Complete (2026-06-27) — ts-cli v0.17.0
- BL-050 — Tableau: systematic pre-transforms — Complete (2026-06-27) — ts-cli v0.17.0
- BL-051 — Tableau: eliminate unnecessary metadata fetching — Complete (2026-06-27)
- BL-052 — Tableau: no-keyword LOD expressions — Complete (2026-06-27) — ts-cli v0.17.0
- BL-053 — Tableau: migration report excluded formulas — Complete (2026-06-27)
- BL-054 — Tableau: date arithmetic rewrite — Complete (2026-06-27) — ts-cli v0.17.0
- BL-055 — Tableau: scalar MAX/MIN detection — Complete (2026-06-27) — ts-cli v0.17.0
- BL-056 — Tableau: strip line comments — Complete (2026-06-27) — ts-cli v0.17.0
- BL-057 — Tableau: CSQ alias resolution — Complete (2026-06-27) — ts-cli v0.17.0
- BL-065 — Codify ts-audit engine as `ts audit run` — Complete (2026-07-01) — 51 deterministic checks across 5 modules, `ts audit run` + `ts audit report` CLI commands, 32 unit tests
- BL-027 — Explicit table→ThoughtSpot binding — Done (archived 2026-07-23) — `.tds` parsing + `--reconcile-table`/`--column-name-map`/`--table-name-map`, live-verified on the cited Catalog Health Workbook
- BL-061 — Integrate `tml_lint()` into build-model — Done (archived 2026-07-23) — mandatory `ts tml lint --dir` + `ts tableau verify --dir` in skill Step 6, plus an XREF preflight inside build-model itself
- BL-062 — Misplaced-else-in-aggregate detection — Done (archived 2026-07-23) — regex live at `validate.py:212`
- BL-068 — Codify Tableau dashboard-to-liveboard conversion — Done (archived 2026-07-23) — `ts tableau build-liveboard` + `extract_dashboards()` shipped, live-verified against FedEx VEDR
- BL-085 — build-model generate mode + TWB-parse codification — Done (archived 2026-07-23) — both parts shipped; the stale "Part 2 OPEN" status line was corrected
- BL-089 — Multi-table build-model generate-mode support — Done (archived 2026-07-23) — M1–M11 confirmed, including live-verified `.tds` parsing and a clean complexity gate
- BL-090 — Document multi-table/multi-query Tableau migration — Done (archived 2026-07-23) — M12–M16 documented in SKILL.md + `references/step-5-tml-generation.md`
- BL-092 — Drop extract table when Custom SQL→SQL View — Done (archived 2026-07-23) — live-verified 0 extract-schema Table TML; adjacent column-ownership bug fixed separately (PR #324)
- BL-125 — Retire vestigial phased-formula emission — Done (archived 2026-07-23) — PR #291, live-verified a single `.phase0.model.tml`

---

## Priority index

Open items classified by tier. Work top-down within each tier; items within a tier
are roughly ordered by value÷effort.

### Tier 1 — Tackle next

| Item | Summary | Target |
|---|---|---|
| BL-100 | Bring remaining converters to DBX-from standard (Snowflake pipeline first) | post-audit |
| ~~BL-064~~ | ~~External audit product-currency fixes (medium-severity residuals)~~ | DONE |
| ~~BL-118~~ | ~~Codify SpotQL SV/MV backing behaviour~~ | DONE (PR #301) |
| ~~BL-063~~ | ~~Extract CLI formula translation~~ | DONE |
| ~~BL-029~~ | ~~Coverage matrix for ts-convert-to-databricks-mv~~ | DONE |

### Tier 2 — Schedule soon

| Item | Summary | Target |
|---|---|---|
| BL-123 | Product currency gaps (2026-07-22 audit) | weekly sweep |
| BL-122 | Cross-skill prompt/discovery extraction | next converter edit |
| BL-127 | Roll out context-budget rule to all conversion skills | next converter edit |
| BL-129 | One-pass CLI guidance + batch ops across converters | next converter edit |
| BL-130 | Canonical data-type audit across converters (DATE_TIME) | 2026-09-30 |
| BL-095 | connections add-tables missing authenticationType | 2026-08-31 |
| BL-120 | Live e2e verification for ts-convert-from-qlik | first live pass |
| BL-115 | Smoke test for ts-convert-from-looker | first live pass |
| BL-126 | Migrate SpotQL smoke test from champ-staging to se-thoughtspot | blocked on instance |
| BL-076 | Smoke test backfills: answer-promote + from-tableau | 2026-09-30 |
| BL-084 | Codify profile substrate as `ts profiles add/update/remove` | 2026-10-31 |
| BL-071 | Tableau user-function → ThoughtSpot RLS variables | 2026-09-30 |
| BL-073 | ~~ts-audit / ts-cli round-trip batching (perf)~~ | DONE |
| BL-030 | Model-coach: migrate to `ai/instructions` API | 2026-09-30 |
| BL-032 | Databricks MV: parser for GA constructs (`materialization:`, `fields:`) | 2026-09-30 |
| BL-031 | Snowflake to-SV: emit `facts[]` / `sample_values` / filter-labels | 2026-09-30 |
| BL-005 | Databricks runtime: ThoughtSpot client + conversion skills | — |
| BL-011 | ts-object-connection-create skill + `ts connections create` CLI | — |
| BL-014 | Databricks MV → ThoughtSpot mapping coverage review | — |
| BL-015 | Pre-conversion audit/feasibility mode for SF SV and DBX MV | — |
| BL-019 | Databricks MV: audit mapping gaps (SV parity) | — |
| BL-020 | Tableau: audit mapping gaps (SV parity) | — |
| BL-021 | Delta sync mode for SV and MV converters | — |
| ~~BL-023~~ | ~~Coverage matrices for DBX MV and Tableau converters~~ | DONE |
| BL-024 | Close row-offset table-calc gap with window functions | — |
| BL-026 | ts-object-liveboard-builder skill | — |
| BL-028 | Audit mode: assess visualization layer | — |
| BL-094 | Joins between SQL Views (multi-query Custom SQL) | — |

### Tier 3 — Opportunistic

| Item | Summary | Target |
|---|---|---|
| BL-034 | tools/ & ts-cli quality polish | 2026-10-31 |
| BL-128 | Skill-size audit: extract detail from heavy converter skills | opportunistic |
| BL-036 | Databricks-native connection creation | 2026-10-31 |
| BL-066 | Codify formula promotion as `ts model promote-formula` | 2026-10-31 |
| BL-080 | `ts metadata permissions` + answer-promote pre-flight | 2026-09-30 |
| BL-081 | `ts data search` for ts-audit Phase 2 | 2026-10-31 |
| BL-086 | Model-coach: codify deterministic substrate | 2026-11-30 |
| BL-007 | Array/VARIANT column handling pattern | — |
| BL-008 | Soft/overridable exclusion rules in model-instructions-schema | — |
| BL-022 | Unjoined table suggestion pattern (cross-converter) | — |
| BL-043 | Evaluate two-phase import for other converters | — |
| BL-059 | ts-audit: set (cohort) usage analysis checks | — |
| BL-072 | Tableau hierarchies and value aliases (+ inverse-trig) | 2026-12-31 |
| BL-101 | Chart-axis-role in `ts metadata report` | — |
| BL-102 | Databricks MV `parameters:` parse + emit | — |
| BL-111 | `--connection` filter: converter rewiring (remaining) | — |
| BL-112 | Rewire smoke_ts_audit.py onto `ts audit run/report` | — |
| BL-116 | Live destructive dependency-manager smoke | — |
| ~~BL-132~~ | ~~from-Databricks build-model: duplicate `column_id` → formula promotion (I8/I5 parity with from-Snowflake)~~ | DONE (PR #332) |
| ~~BL-133~~ | ~~`ts metadata delete`: partial-success handling (batch fails atomically if one GUID is missing)~~ | DONE (PR #333, #335) |

### Tier 4 — Deferred

| Item | Summary | Trigger |
|---|---|---|
| BL-016 | Conversion mapping-file naming consistency | cosmetic, low priority |
| BL-025 | DBX Genie connection-selection parity | next Genie skill touch |
| BL-037 | Recipe skills for investigation patterns | demand-driven |
| BL-038 | ts-recipe-formula-weighted-average | demand-driven |
| BL-039 | ts-object-answer-promote: embedded Answers + sets | demand-driven |
| BL-041 | ts-recipe-model-timezone-bridge-snowflake | demand-driven |
| BL-091 | Multi-table model grain semantics verification | when data access available |
| BL-096 | se-thoughtspot SpotQL endpoints 500 | next build re-verify |
| BL-098 | DBX trailing/leading sparse data (item 3 only) | next DBX live-verify |
| BL-103 | searchConnection with OAuth hierarchy | next OAuth connection |
| BL-104 | Evaluate DBX BI compatibility mode | evaluation item |
| BL-106 | Python 3.11 floor bump (remaining) | after 2026-10 |
| BL-113 | Live provisioning step for load smoke | next SF live session |
| BL-114 | Document export_with_column_aliases | GA or skill need |
| BL-119 | Smoke test for ts-convert-from-sisense | first Sisense bundle |

---

## BL-118 — Codify SpotQL semantic-view / metric-view backing behaviour into `ts-object-model-spotql-query` — DONE `Tier 1`

**Status:** DONE — PR #301 (2026-07-22). `references/snowflake-sv-backing.md` (R1–R7 + Databricks MV comparison)
committed; `limitations.md` updated with the measure-statistics silent-wrong-answer trap; SKILL.md references
table cross-linked; skill bumped to v1.5.0.

**Why it matters.** SpotQL/Semantic-SQL behaviour differs materially when a Model is backed by a
Snowflake Semantic View (SV) or a Databricks Metric View (MV) rather than regular tables. These
behaviours were characterised live (2026-07-21) across three Models holding identical Dunder Mifflin
data.

**What to codify (all live-verified):**
- **Null-key `100072`** on an SV: a raw PK-backed dimension key materialised in a CTE then transformed
  throws `100072 NULL result in a non-nullable column`. Fix: CASE-wrap the key
  (`CASE WHEN k IS NOT NULL THEN k END`; also `IFF`/`NVL2`; not a plain cast or `+0`), in SELECT/GROUP BY
  only, never WHERE. The MV tolerates NULL grouping keys, so this is SV-only.
- **No inline window on an SV**: a window function in a query that references an SV errors
  `Unsupported feature 'WINDOW FUNCTIONS'`; author as aggregate-in-CTE then window-in-outer. The MV runs
  windows inline.
- **Measure-statistics trap (all backings)**: a secondary aggregate on an already-aggregated measure is
  invalid everywhere. The regular Model hard-errors (`NESTED_AGGREGATE_NOT_SUPPORTED`); the SV/MV
  **silently drop** the outer aggregate and return the measure's native aggregation (`AVG` returns the
  SUM); `MEDIAN`/`STDDEV` fail as nested aggregates. Fix on all backings: the CTE statistics pattern
  (materialise the measure at a grain, apply the statistic in the outer SELECT).
- **`AGG()` (Snowflake) ≡ `MEASURE()` (Databricks)** for pre-aggregated measures; ThoughtSpot emits these
  automatically for SV/MV-backed Models.

**Approach.**
1. Recreate + extend `agents/cli/ts-object-model-spotql-query/references/snowflake-sv-backing.md`
   (rules R1–R7 from the prior draft + the measure-statistics trap + a Databricks MV sibling note).
2. Add a `references/limitations.md` ⚠️ silent-wrong-answer row: `AVG`/`MIN`/`MAX` on a measure over an
   SV/MV backing is silently dropped and returns the native aggregation (regular Model hard-errors);
   cross-link to the CTE statistics pattern in `patterns.md`.
3. Cross-link from the `SKILL.md` references table and `limitations.md`; bump skill version + changelog (MINOR).
4. Consider an xModel cross-model stitching section once the fan-out analysis lands (see reference docs).

**Reference docs (merged / available):**
- `djwaldo/spotql-testing` `main`: `docs/spotql-backing-comparison.md` (three-way matrix + actual SQL +
  both SV fixes), `docs/spotql-snowflake-sv-findings.md`, `docs/spotql-sv-backing-rules-PLAN.md`,
  `docs/search-data-probe-findings.md`, `docs/spotql-limitations.md`.
- Shareable artifact: https://claude.ai/code/artifact/b0d02cee-19d3-4967-ae0c-59001a668f44
- In flight: `docs/cross-model-stitching-analysis.md` (xModel fan-out avoidance in author-written SpotQL;
  no engine-level chasm protection) — feeds the xModel stitching guidance in step 4.

**Branch.** A worktree branch `feat/spotql-measure-statistics-trap` (off `main`) was staged for this work
but only used to raise this backlog item; it can be reused for the codification or discarded and the work
redone from the reference docs above.

**Date raised:** 2026-07-21.

---

## BL-005 — Databricks runtime: ThoughtSpot client + conversion skills `Tier 2`

**Source:** Design spec `docs/superpowers/specs/2026-06-11-databricks-ts-client-design.md`
**Affects:** All Databricks-related skills; future Genie Code skill runtime
**Status:** Spec complete — ready for implementation planning

### Problem

The repo's Databricks skills (`ts-convert-to-databricks-mv`, `ts-convert-from-databricks-mv`)
currently run only from CLI (Claude Code / Cortex Code CLI). Databricks users working
inside the platform (notebooks, Genie Code) cannot use them because there is no
ThoughtSpot API client for the Databricks runtime — the `ts` CLI requires shell access
and OS keychain, neither of which exist in Databricks.

Beyond the Databricks conversion skills, platform-agnostic skills (`ts-object-model-coach`,
`ts-object-answer-promote`, `ts-dependency-manager`) could also run from Databricks if
a client layer existed.

### Proposed approach

Build `agents/databricks/` as a third runtime alongside CLI and CoCo:

1. **`ts_client.py` notebook** — single-file `ThoughtSpotClient` class with full ts-cli
   parity (auth, metadata, TML, connections, tables, users, orgs, variables) plus
   `ReportEngine` for metadata report. Uses Databricks Secrets for credentials,
   in-memory token caching.

2. **`ts_profile_setup.py` notebook** — interactive setup wizard using `dbutils.widgets`
   to create Secrets scopes, store credentials, and test connections. Supports three
   auth methods: bearer token, password→token exchange, secret_key→token exchange.

3. **`token_refresh.py`** — lightweight script for a scheduled Databricks Job that
   rotates tokens every 12 hours (password and secret_key auth only).

4. **Two Genie Code skills** — `ts-convert-to-databricks-mv` and
   `ts-convert-from-databricks-mv` adapted as SKILL.md files for Genie Code Agent
   mode. These reference the client notebook and shared reference files.

5. **Shared reference files** — `agents/shared/mappings/ts-databricks/`,
   `agents/shared/schemas/`, and `agents/shared/worked-examples/databricks/` deployed
   to the workspace alongside notebooks and skills.

6. **SETUP.md** — end-to-end deployment guide: upload notebooks + skills + shared
   files, create profile, optional token refresh job, Genie Code usage.

7. **Unit tests** — pytest-based, mocked `dbutils.secrets` and `requests`, covering
   all auth flows + all client methods.

### Phases

| Phase | Deliverable | Depends on |
|---|---|---|
| **Phase 1** (this item) | `ts_client.py` + setup/refresh notebooks + 2 conversion skills + shared files + tests + SETUP.md | — |
| **Phase 2** | Genie Code skills for 4 platform-agnostic skills (model-coach, answer-promote, dependency-manager, profile-thoughtspot) | Phase 1 |
| **Phase 3** | `databricks aitools install` packaging for distribution | Phase 1 |

### Design spec

Full architecture, auth design, command mapping, test cases, and SETUP.md outline:
[`docs/superpowers/specs/2026-06-11-databricks-ts-client-design.md`](superpowers/specs/2026-06-11-databricks-ts-client-design.md)

---

## BL-007 — Array/VARIANT column handling pattern for model coaching `Tier 3`

**Source:** Live coaching of AGENT_SKILLS.BOOKINGS.BOOKINGS_WITH_ARRAY (2026-06-11)
**Affects:** ts-object-model-coach (Step 6.1), ts-from-snowflake-rules.md
**Status:** Not started

### Problem

`ts-from-snowflake-rules.md` maps `VARIANT, OBJECT, ARRAY → VARCHAR *(flag for review)*`
but provides no guidance on what "flag for review" means in practice. The model coach
skill has no pattern for handling VARCHAR columns that store serialised arrays (a common
Snowflake pattern), leaving skills to treat them as plain strings.

The correct handling requires two surfaces:
1. A companion `VARIANT` column in Snowflake for efficient native array querying
2. Specific `description`, `ai_context`, and `column_metadata` coaching to guide agents
   toward `ARRAY_CONTAINS` rather than `LIKE`/`CONTAINS`

### Proposed approach

Add a new **Array column pattern** section to `ts-from-snowflake-rules.md` covering:

**Detection signals** (any one is sufficient):
- Column name contains `_array`, `_list`, `_tags`, `_ids`
- Sample values match `[ "...", "..." ]` or `["...","..."]` JSON array pattern
- `APPROX_COUNT_DISTINCT` is high relative to low cardinality of individual values (i.e. many combinations of a small value set)

**Recommended handling when detected:**

1. Register the VARCHAR column in ThoughtSpot as-is (`data_type: VARCHAR`) — ThoughtSpot cannot use VARIANT natively
2. Create a companion `{col}_ARRAY VARIANT` column in Snowflake:
   ```sql
   ALTER TABLE {db}.{schema}.{table} ADD COLUMN {col}_ARRAY VARIANT;
   UPDATE {db}.{schema}.{table} SET {col}_ARRAY = PARSE_JSON({col});
   ```
3. Register the VARIANT column in ThoughtSpot as `VARCHAR` with the following `description` template:
   > `Snowflake VARIANT form of {col}. Use ARRAY_CONTAINS(value::VARIANT, {col}_ARRAY) for filtering — not LIKE or CONTAINS. NULL = no filters selected.`
4. In `ai_context` on the VARIANT model column: add `source: {SCHEMA}.{TABLE}.{COL}_ARRAY` to override the column_id resolution and point agents to the physical VARIANT path
5. In `column_metadata` (model instructions): add both columns — VARCHAR with `value_format: JSON array of {value type} strings`, VARIANT column with note to prefer `ARRAY_CONTAINS`
6. Add a sync note: the VARIANT column requires a Snowflake Task to stay current if the table receives ongoing inserts

**`column_metadata` template for instructions:**

```
| {Col} | {cardinality} | {samples} | filter | JSON array of {value type} strings (VARCHAR — use CONTAINS or LIKE) |
| {Col} Array | {cardinality} | {samples} | filter | Snowflake VARIANT — use ARRAY_CONTAINS(value::VARIANT, {col}_ARRAY); preferred for exact matching |
```

### Files affected

- `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md` — new "Array column pattern" section
- `agents/cli/ts-object-model-coach/SKILL.md` — Step 6.1 column detection, Step 6.5 column_metadata generation

---

## BL-008 — Soft/overridable exclusion rules in model-instructions-schema `Tier 3`

**Source:** Live coaching of AGENT_SKILLS.BOOKINGS.BOOKINGS_WITH_ARRAY (2026-06-11)
**Affects:** ts-object-model-coach (Step 6.5)
**Status:** Not started

### Problem

`model-instructions-schema.md` describes `exclusion_rules` only as "always-applied
filters" — appropriate for hard business rules (e.g. never include refund line items
in revenue) but not for quality filters that represent sensible defaults yet should
remain user-overridable (e.g. exclude bot traffic by default, but allow "show me bot
traffic" to work).

The current schema gives no mechanism to express this distinction, so skill-generated
instructions either over-restrict (hard exclude of user-queryable data) or under-specify
(no default filter at all).

### Proposed fix

Add a **Soft exclusion** subsection to the `exclusion_rules` category in
`model-instructions-schema.md`:

> **Hard vs soft exclusions:**
>
> | Type | When to use | Override clause |
> |---|---|---|
> | Hard | Business rule — rows are never valid for the measure (refunds, test accounts) | None — no override |
> | Soft | Quality default — rows are queryable but excluded unless explicitly requested (bot traffic, internal sessions) | Required — see below |
>
> **Soft exclusion pattern:**
> ```
> Exclude rows where {condition} by default.
> Override: if the user explicitly asks for {bot traffic / internal sessions / all traffic},
> remove this exclusion for that query only.
> ```
>
> The override clause is scoped to a single query — it does not permanently change the default.

### Files affected

- `agents/cli/ts-object-model-coach/references/model-instructions-schema.md` — new Hard vs Soft subsection under `exclusion_rules`
- `agents/cli/ts-object-model-coach/SKILL.md` — Step 6.5 `exclusion_rules` bootstrapping logic (detect soft candidates: IS_BOT, IS_INTERNAL, IS_TEST etc.)

## BL-011 — `ts-object-connection-create` skill + `ts connections create` CLI `Tier 2`

**Source:** Smoke test of `connection/create` on se-thoughtspot (2026-06-11)
**Affects:** NEW skill `agents/cli/ts-object-connection-create`; `tools/ts-cli` (`connections create`)
**Status:** Not started
**Full plan:** no separate plan doc was ever written — see Problem / Verified facts /
Proposed approach below for the full design.

### Problem

All three convert-from skills require a ThoughtSpot connection but none can create one, and the
`ts` CLI has no `connections create`. Connection creation is the missing prerequisite, and the
credential handling must be done in exactly one audited place.

### Verified facts (smoke test)

- `POST /api/rest/2.0/connection/create` works; auth + `DATAMANAGEMENT`/RBAC + payload shape OK.
- **`validate:false` does NOT skip the live warehouse handshake** — real reachable creds are
  mandatory; no shell/credential-less connection is possible.
- Snowflake `KEY_PAIR` is a valid `authenticationType` but its **private-key field name is
  UNDOCUMENTED** (research item — the user's profile is key-pair only).

### Proposed approach

Standalone skill + `ts connections create` subcommand. **Security baseline (`.claude/rules/
security.md`):** secrets read in-process from keychain/PEM, NEVER as CLI flags, never printed,
never in agent context; scrub `configuration` from error bodies; enforce `verify_ssl`; recommend
a dedicated least-privilege service account. KEY_PAIR field discovery is a gated phase needing a
least-privilege SF service account. Hands off to/from BL-010 (loader emits a tables.json for
create-with-tables) and the convert-from skills (cross-link as the "create one first" path).

## BL-014 — Databricks MV → ThoughtSpot mapping coverage review (parallel to SV gap analysis + Tableau audit) `Tier 2`

**Source:** Coverage-review gap identified 2026-06-12 (SF has one, DBX does not)
**Affects:** ts-convert-from-databricks-mv
**Status:** Not started

### Problem

There is a systematic mapping-coverage review for **Snowflake SV** (BL-003 umbrella,
now tracked in the skill's `references/coverage-matrix.md`) and for **Tableau** (127-workbook audit, BL-009), but **none for
Databricks Metric Views**. The DBX converter is the youngest (1.0.0 — 2026-05-22, single mode) and
has never been audited against real MVs, so the true unmapped surface is unknown.

### Proposed approach

Run a gap analysis against one or more production Databricks Metric Views (MV YAML/DDL):

1. Enumerate every MV construct — dimensions, measures, joins, filters, window/derived metrics,
   double-aggregation (metric-referencing-metric), comments, synonyms, custom instructions,
   `version` differences — and classify each **mapped / partial / unmapped** to TS Model TML.
2. Produce `docs/mv-to-ts-gap-analysis.md` mirroring the SV gap-analysis structure, and file the
   findings as `references/open-items.md` entries + (where multi-step) backlog sub-items.
3. Identify a representative test MV (the DBX analogue of the SV `SHIFTS7_PAYROLL1` test object).

### Files affected

- NEW `docs/mv-to-ts-gap-analysis.md`
- `agents/cli/ts-convert-from-databricks-mv/references/open-items.md`

---

## BL-015 — Pre-conversion Audit/feasibility mode for SF SV and DBX MV (parity with Tableau Audit mode) `Tier 2`

**Source:** Feature request (2026-06-12) — "assess how much the routine can map; is it worth attempting"
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv
**Status:** Not started

### Problem

`ts-convert-from-tableau` has an **Audit mode** (Steps A1–A4: no auth, no TML) that classifies
every source construct into translation tiers and prints a **Migration Coverage Report** with
per-tier counts/% — "use this to assess feasibility" *before* committing to a conversion. The SF
and DBX converters have **no equivalent**: SV has nothing; DBX has only a static reference
(`ts-databricks-properties.md`), not a runtime per-object assessment. So a user can't ask "how
much of *this* Semantic View / Metric View will actually map, and is it worth attempting?"

### Proposed approach

Add an **Audit mode** to both converters, mirroring the Tableau pattern:

1. **Mode select up front** — offer "Audit (assess only)" vs "Convert", like Tableau's Step 0.
   Audit needs **source/DDL access only** — no ThoughtSpot auth, no TML generated.
2. **Parse** the SV/MV (reuse the converter's existing parse step) and **classify every construct**
   — dimensions, measures, joins, filters, window/derived metrics, double-aggregation, comments,
   synonyms, instructions — into tiers: **Native / Translatable-with-pattern / Pass-through /
   Partial / Unmapped** (define the SF and MV tier taxonomies; SF can seed from its
   formula-translation "untranslatable" section, DBX from `ts-databricks-properties.md` + BL-014).
3. **Coverage report** — per-tier counts + %, the specific unmapped/partial constructs by name,
   and a **go / caution / no-go recommendation** with the reasons (e.g. "82% native, 2 window
   metrics need manual rework, 1 unmapped ASOF join → proceed with review").
4. Reuse the Tableau Audit-mode report layout (Step A4) for a consistent UX across all three.

### Dependencies / relationships

- **BL-014** (DBX MV coverage review) defines the tier taxonomy the DBX audit classifies against —
  do BL-014 first, or develop them together.
- Complements **BL-013** (metadata-only sync): audit tells you *whether* to convert; BL-013 is one
  of the *outcomes* (if only metadata changed).

### Files affected

- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — Audit mode steps + coverage report
- `agents/cli/ts-convert-from-databricks-mv/SKILL.md` — Audit mode steps + coverage report
- `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` + `ts-databricks/ts-databricks-properties.md` — tier definitions feeding the classifier

---

## BL-016 — Conversion mapping-file naming/structure consistency `Tier 4`

**Source:** Observed during BL-009 Phase 1 (2026-06-12)
**Affects:** agents/shared/mappings/tableau/, ts-snowflake/, ts-databricks/
**Status:** Not started

### Problem

The three convert-from skills name their shared mapping files inconsistently:

| Role | Tableau | Snowflake | Databricks |
|---|---|---|---|
| Formula translation | `tableau-formula-translation.md` | `ts-snowflake-formula-translation.md` | `ts-databricks-formula-translation.md` |
| TML-generation rules | **`tableau-tml-rules.md`** | `ts-from-snowflake-rules.md` | `ts-from-databricks-rules.md` |
| Properties | *(none — folded into tml-rules)* | `ts-snowflake-properties.md` | `ts-databricks-properties.md` |

`tableau-tml-rules.md` is the functional equivalent of the SV/MV `*-from-rules.md` files
(Table/Model/SQL-View TML rules, date rules, join + type mapping, validation reference) — just
named differently. Tableau correctly has no `*-to-rules.md` (it is convert-*from* only, one-directional).

### Proposed approach

Low-priority cosmetic alignment (no capability gap): consider renaming
`tableau-tml-rules.md` → `tableau-from-rules.md` (update all SKILL.md + coco mirror
references), and optionally splitting Tableau property/type content into a
`tableau-properties.md` to mirror SV/MV. Fits the BL-012 cross-skill-consistency theme; the
conversion-consistency-auditor could then assert the naming convention.

---

## BL-019 — Databricks MV: audit mapping gaps equivalent to BL-018 (SV parity) `Tier 2`

**Source:** BL-018 parity review (2026-06-13)
**Affects:** ts-convert-from-databricks-mv, ts-from-databricks-rules.md
**Status:** Not started
**Related:** BL-014 (general DBX MV coverage review), BL-018 (SV equivalent)

### Problem

BL-018 identified and mapped four SV constructs to ThoughtSpot (range joins, filter
labels, view-backed sources, verified queries). The Databricks MV converter needs a
parallel assessment: which of these concepts exist in Databricks Metric Views, and
does the converter handle them?

### Feature parity matrix

| SV Feature (BL-018) | Databricks MV Equivalent | Current Mapping Status |
|---|---|---|
| Range joins (BETWEEN, ASOF) | **None** — MV YAML `joins` are equi-only (`primary_key`/`foreign_key`) | N/A — no equivalent construct |
| Filter labels (`LABELS=(FILTER)`) | MV `filter:` on dimensions/measures — boolean expressions for conditional availability | **Not mapped** — `ts-from-databricks-rules.md` does not document filter handling |
| View-backed sources | MV `source.table` accepts views and subqueries (`source.sql_select`) | **Partially mapped** — `sql_select` sources → SQL View TML exists in worked example |
| Verified queries | **None** — Databricks uses Genie Spaces with separate instruction files, not inline verified queries | N/A — no equivalent construct |

### Proposed approach

1. **MV filters** — Audit the `filter:` property on MV dimensions and measures.
   Determine whether these are row-level boolean expressions (like SV filter labels)
   or pre-applied aggregation filters. Map to boolean formula columns or model filters
   per the same decision logic as BL-018 sub-item 2.

2. **View/subquery sources** — Verify the existing `sql_select` → SQL View TML path
   is documented in `ts-from-databricks-rules.md` and the SKILL.md. Confirm the
   worked example (`ts-from-databricks-sql-view.md`) is still current.

3. **No-action items** — Document in `ts-from-databricks-rules.md` that range/non-equi
   joins and verified queries have no Databricks MV equivalent (so the converter
   correctly has no mapping for these).

### Files affected

- `agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md` — filter mapping, view/subquery docs, no-equivalent notes
- `agents/cli/ts-convert-from-databricks-mv/SKILL.md` — filter parsing if applicable
- `docs/mv-to-ts-gap-analysis.md` (new, also tracked in BL-014)

---

## BL-020 — Tableau: audit mapping gaps equivalent to BL-018 (SV parity) `Tier 2`

**Source:** BL-018 parity review (2026-06-13)
**Affects:** ts-convert-from-tableau, tableau-tml-rules.md
**Status:** Not started. Per the 2026-07-23 triage, only sub-item 2 (data-source `<filter>` →
`model.filters[]`) is real and unimplemented; sub-item 1 (range-predicate parsing) is
deprioritized by this item's own text and sub-item 4 (verified queries) is moot (no Tableau
equivalent); sub-item 3 (Custom SQL → SQL View) shipped separately (PR #188).
**Park note (2026-07-23):** deferred as feature-sized — sub-item 2 needs new XML parsing for
categorical/quantitative/relative-date/context filter shapes, boolean-formula generation, and
`model.filters[]` wiring with `apply_on_tables` scoping. Decision owed: whether to scope it
down to categorical-only first or build all filter shapes in one pass.
**Related:** BL-009 (general Tableau mapping gaps), BL-018 (SV equivalent)

### Problem

BL-018 mapped four SV constructs to ThoughtSpot. The Tableau converter needs a
parallel assessment for equivalent concepts in Tableau workbooks.

### Feature parity matrix

| SV Feature (BL-018) | Tableau Equivalent | Current Mapping Status |
|---|---|---|
| Range joins (BETWEEN, ASOF) | Custom SQL data sources with range predicates in JOIN ON clauses | **Not mapped** — Tableau custom SQL is extracted but JOIN clauses within it are passed through, not parsed for range predicates |
| Filter labels | Data source filters, context filters, fixed dimension filters — boolean conditions on data sources | **Partially mapped** — data source filters are logged but not translated to model filters or boolean formulas |
| View-backed sources | Custom SQL data sources (arbitrary SELECT statements) | **Partially mapped** — custom SQL logged in report (BL-009 Phase 4), not yet translated to SQL View TML |
| Verified queries | **None** — Tableau has "Ask Data" lenses but these are not exported in .twb/.twbx files | N/A — no equivalent construct |

### Proposed approach

1. **Custom SQL range predicates** — When Tableau's custom SQL contains JOIN ... ON
   with range predicates (`<`, `>`, `BETWEEN`), the converter currently passes the
   entire custom SQL through as a SQL View. Consider parsing the JOIN structure to
   produce Model TML joins with range expressions (same as BL-018 sub-item 1). This
   is complex and may not be worth the effort vs. the SQL View pass-through.

2. **Data source filters** — Tableau data source filters are boolean conditions
   applied at the data source level. Map to model filters (`model.filters[]`) with
   appropriate `apply_on_tables` scoping. This is a direct equivalent of the SV
   filter label → model filter mapping.

3. **Custom SQL → SQL View TML** — This is already identified as BL-009 Phase 4.
   Confirm alignment with the SQL View TML generation path used by BL-018 sub-item 3
   and the Databricks `sql_select` path.

4. **No-action items** — Document that verified queries have no Tableau equivalent.

### Dependencies

- **BL-009 Phase 4** (source coverage) overlaps with custom SQL handling — coordinate.
- Tableau data source filter mapping should use the same model filter generation
  logic as BL-018 sub-item 2 (shared pattern).

### Files affected

- `agents/shared/mappings/tableau/tableau-tml-rules.md` — filter mapping, custom SQL→SQL View docs
- `agents/cli/ts-convert-from-tableau/SKILL.md` — data source filter translation step
- `agents/cli/ts-convert-from-tableau/references/open-items.md` — new items for filter + custom SQL gaps

---

## BL-021 — Delta sync mode for SV and MV converters (selective, additive, TS-side-preserving) `Tier 2`

**Source:** Feature request (2026-06-14)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv
**Status:** Not started
**Supersedes:** BL-013 (metadata-only sync is a subset of this)

### Problem

Mode C (SV) performs a full structural diff — every column, formula, join, and metadata
field is compared and the user decides per-item. This is appropriate for a wholesale
refresh, but too heavy for the common case: the source SV/MV changed incrementally and
the user wants to **selectively pull in specific changes** while **preserving everything
they've added on the ThoughtSpot side**.

Typical delta scenarios:

| What changed in SV/MV | What user wants | What must be preserved in TS |
|---|---|---|
| New columns added | Pull in new columns only | All existing columns, formulas, ai_context, instructions |
| Column descriptions/synonyms updated | Sync metadata selectively | User-authored ai_context, coached synonyms |
| Metric expression changed | Update specific formulas | Unrelated formulas, column settings |
| New relationship added | Add the join | Existing joins, column order |
| Nothing — user added formulas in TS | No source sync | Everything — this is a TS-only edit |

Today's options don't cover this well:

- **Mode A** (create new) — overwrites everything; user loses all TS-side additions
- **Mode C** (full diff) — presents every difference, even unchanged items; user must
  review the full change set even when only one column changed
- **BL-013** (metadata-only) — limited to names/comments/synonyms; can't pull in new
  columns or updated expressions

### Proposed approach

A **delta sync** mode (Mode D or an enhancement to Mode C) with these principles:

#### 1. Selective change categories

Present changes grouped by category, let the user opt in/out per category:

```
Delta sync — changes detected:

  ✚ New columns (3)          [APPLY / SKIP]    ← default: APPLY
  ✏ Modified metadata (5)    [REVIEW / SKIP]   ← default: REVIEW (per-column MERGE/UPDATE/KEEP)
  ~ Modified expressions (2) [REVIEW / SKIP]   ← default: REVIEW (per-formula YES/SKIP)
  ✚ New joins (1)            [APPLY / SKIP]    ← default: APPLY
  ✖ Removed in source (2)   [FLAG ONLY]        ← never auto-removed

  = Unchanged (42)           — no action
```

User can APPLY an entire category without per-item review, or REVIEW to get the
Mode C per-column table for that category only.

#### 2. TS-side preservation rules

These fields are **never overwritten** by a delta sync, regardless of category:

| TS-side field | Why preserved |
|---|---|
| `ai_context` | User-authored coaching — no source equivalent |
| `data_model_instructions` | User-authored Spotter guidance |
| User-added formulas (no source match) | Custom TS-side analytics |
| User-added joins (no source match) | Manual relationship additions |
| `index_type` overrides | User tuning for Spotter |
| Column order | User curation |

#### 3. Conflict resolution for metadata

When both source and TS have changed the same field (e.g. source updated a synonym
AND the user added a coached synonym):

- **Synonyms** — default MERGE (union of both sets; never remove user-added synonyms)
- **Descriptions** — default KEEP TS (user's description is likely more refined)
- **Expressions** — always REVIEW (show side-by-side, require explicit YES)

#### 4. New-column enrichment

New columns pulled from the source get:
- Display name, description, synonyms from the source (as in Mode A)
- No `ai_context` (flagged for coaching handoff)
- Automatic `column_type` classification per existing rules

Post-sync handoff to `/ts-object-model-coach` for the new columns.

#### 5. Dry-run option

```
Run as:  DRY RUN (show what would change, don't import)  /  APPLY
```

Dry run produces the categorised change report without importing — useful for
assessing scope before committing.

### Relationship to existing modes

| Mode | When to use |
|---|---|
| A — Create new | First conversion; no existing model |
| B — Merge | Combine multiple SVs/MVs into one model |
| C — Full diff | Wholesale refresh; review everything |
| D — Delta sync (this item) | Incremental sync; preserve TS-side work |
| BL-013 — Metadata only | Subset of D: only names/comments/synonyms |

BL-013 becomes a convenience shortcut within Mode D (select only the "Modified metadata"
category and skip all others).

### Files affected

- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — Mode D workflow steps
- `agents/cli/ts-convert-from-databricks-mv/SKILL.md` — Mode D workflow steps (first update mode for DBX)
- `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md` — delta sync rules
- `agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md` — delta sync rules

---

## BL-022 — Unjoined table suggestion pattern (cross-converter) `Tier 3`

**Source:** BL-018 live testing — EMPLOYEE_SUMMARY_VW had no declared relationship in the SV (2026-06-13)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv, ts-convert-from-tableau
**Status:** In progress — SV converter join discovery workflow implemented (2026-06-14); Databricks MV and Tableau pending
**Priority:** Medium — prevents orphan tables silently entering models without joins

### Problem

When a source (SV, MV, or Tableau datasource) includes a table with no declared
foreign-key or relationship to other tables, the current converters silently add
it to `model_tables[]` with no `joins[]`. The resulting model has an unjoined island
that ThoughtSpot accepts but cannot query across — the user gets "no path between
tables" errors at search time with no clue why.

### Proposed approach

When a table has no declared relationship in the source, the converter should:

1. **Scan column name overlap** — compare the unjoined table's columns against all
   other tables in the model. Columns with identical names (exact match, case-insensitive)
   are candidate join keys.

2. **Check composite key uniqueness** — for each candidate set of join columns on the
   unjoined table, verify uniqueness:
   ```sql
   SELECT COUNT(*) AS total,
          COUNT(DISTINCT (col1, col2, ...)) AS distinct_keys
   FROM schema.table;
   ```
   If `total == distinct_keys`, the column set is a valid key.

3. **Validate cardinality** — run a live query to confirm the relationship direction
   (MANY_TO_ONE, ONE_TO_ONE, or MANY_TO_MANY):
   ```sql
   SELECT MAX(cnt) FROM (
     SELECT col1, col2, COUNT(*) AS cnt
     FROM left_table GROUP BY col1, col2
   );
   ```
   `max(cnt) == 1` → ONE_TO_ONE; `max(cnt) > 1` → MANY_TO_ONE from the left table.

4. **Present to user with evidence** — show the suggested join, the overlapping
   columns, the uniqueness result, and the cardinality. Require explicit confirmation
   before adding the join to the model.

5. **User actions:**
   - **Accept** — add the join as suggested
   - **Modify** — user corrects columns, cardinality, or join type
   - **Skip** — exclude the table from the model entirely (with a warning)
   - **Add anyway (no join)** — include the table as an unjoined island (explicit choice)

### Cross-converter applicability

| Converter | Table source | Join source | Suggestion triggers when |
|---|---|---|---|
| from-snowflake-sv | `tables(...)` block | `relationships(...)` block | Table listed in `tables()` but absent from `relationships()` |
| from-databricks-mv | `tables:` section | `primary_keys:` / `foreign_keys:` | Table has no foreign key declared in MV YAML |
| from-tableau | Data source tables | Tableau join clauses | Table in datasource with no join to other tables |

### Files affected

- `agents/shared/schemas/ts-model-conversion-invariants.md` — document as a recommended pattern (not a hard invariant)
- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — add unjoined-table check after Step 6
- `agents/cli/ts-convert-from-databricks-mv/SKILL.md` — add unjoined-table check after table discovery
- `agents/cli/ts-convert-from-tableau/SKILL.md` — add unjoined-table check after datasource parsing

---

## BL-023 — Coverage matrix reference docs for Databricks MV and Tableau converters — DONE `Tier 2`

**Source:** BL-018 completion — SV converter now has `references/coverage-matrix.md` (2026-06-14)
**Affects:** ts-convert-from-databricks-mv, ts-convert-from-tableau
**Status:** DONE — both converters have coverage matrices. from-databricks-mv shipped in PR #232;
from-tableau has had one since the skill shipped. The `check_coverage_matrix.py` BACKLOG set is
empty — all 9 conversion skills have coverage matrices. Closed 2026-07-23.
**Related:** BL-014 (DBX MV coverage review), BL-009 (Tableau mapping gaps)

### Problem

The SV converter now has a `references/coverage-matrix.md` that clearly lists every
mapped construct, every limitation, and the test objects used for verification. This
serves as user-facing limitations documentation.

The Databricks MV and Tableau converters have no equivalent — their coverage is
scattered across gap-analysis docs, backlog items, and open-items files. Users cannot
easily determine what a converter handles vs what it does not.

### Proposed approach

Create `references/coverage-matrix.md` for each converter, following the same structure
as the SV coverage matrix:

1. **Mapped constructs** — table of every source construct handled, the ThoughtSpot
   equivalent, and which test object verified it
2. **Unmapped constructs (limitations)** — table with severity and workaround
3. **Test objects** — list of verified test sources

| Converter | Source for coverage data | Test objects |
|---|---|---|
| `ts-convert-from-databricks-mv` | `ts-from-databricks-rules.md`, `ts-databricks-properties.md`, BL-014 findings | `ts-from-databricks.md` + `ts-from-databricks-sql-view.md` worked examples |
| `ts-convert-from-tableau` | `tableau-tml-rules.md`, `tableau-formula-translation.md`, BL-009 findings | `tableau-migration-testing` corpus |

### Dependencies

- **BL-014** (DBX MV coverage review) should run first for the Databricks matrix — it
  identifies the full unmapped surface
- **BL-009** (Tableau mapping gaps, Phases 2c/3/4) should be referenced for known
  Tableau limitations

### Files affected

- NEW `agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md`
- NEW `agents/cli/ts-convert-from-tableau/references/coverage-matrix.md`

---

## BL-024 — Close the row-offset table-calc gap with window functions (INDEX/LOOKUP/FIRST/LAST/SIZE) `Tier 2`

**Source:** Sigma-vs-ThoughtSpot Tableau-migration comparison over a 140-workbook corpus (2026-06-14)
**Affects:** ts-convert-from-tableau (primarily); pattern applies to any converter that translates table calcs
**Status:** PARTIAL. Only the safety-net tier shipped (v0.78.0): omit + log for
INDEX/LOOKUP/FIRST/LAST/PREVIOUS_VALUE (`row_offset_ambiguous`/`window_ambiguous`,
`classify.py:34-71` & `validate.py:73`), plus a native `SIZE()` → `COUNT(*) OVER()`
translation. **Tiers 1 (route `INDEX()<=N` to the Top-N/query-set machinery) and 2
(gated `sql_*_aggregate_op` pass-through via recovered worksheet shelf-sort) are NOT
implemented anywhere.** This is the single largest remaining gap in the Tableau
backlog (source data: `INDEX()` blocks 39 of 140 real workbooks).
**Park note (2026-07-23):** deferred as feature-sized; tiers 1-2 need design work
(Top-N-filter detection tied to table calcs, and shelf-sort-driven pass-through
emission for `sql_*_aggregate_op`) before implementation can start.
**Related:** BL-009 (Tableau mapping gaps), BL-020/BL-023 (coverage matrix)

### Problem

`ts-convert-from-tableau` currently classifies the row-offset table calculations
`INDEX()`, `LOOKUP()`, `FIRST()`, `LAST()`, `SIZE()`, and `PREVIOUS_VALUE()` as
**Untranslatable** (omit + log). In a scan of 140 real Tableau workbooks these were the
single largest ThoughtSpot blocker: `INDEX()` in **39** workbooks, `LOOKUP()` in **21**,
`FIRST/LAST/PREVIOUS_VALUE/SIZE` in **18**. The comparison's competitor (Sigma) handles the
same constructs — it maps them to native window math placed on the chart axis — which is
most of its measured migration-completeness advantage on this corpus.

The reason these are listed untranslatable is **not** that SQL can't express them: warehouse
SQL has `ROW_NUMBER`/`LAG`/`LEAD`/`FIRST_VALUE`/`LAST_VALUE`/`COUNT(*) OVER`. The blocker is the
**addressing context** — Tableau derives the `ORDER BY`/`PARTITION BY` from the viz's
compute-using direction, which a model-level TML formula doesn't carry. The skill already
solves the identical problem for `WINDOW_*`/`RUNNING_*` by extracting the worksheet shelf sort
and emitting `moving_*`/`cumulative_*`; the same extraction applies here.

> **Why this is NOT "just always emit a pass-through":** ThoughtSpot does not validate
> pass-through SQL at import, and it folds referenced columns into `GROUP BY`. A pass-through
> with a *guessed* `ORDER BY` imports clean and returns plausible-but-wrong numbers at query
> time — worse than an honest omission. Coverage must never come at the cost of silent wrong
> results. (See also the SQL-passthrough constraints in
> `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`.)

### Proposed approach — tiered, never a blanket pass-through

1. **Native first (no SQL).** Translate the *intent*, not the function:
   - `INDEX() <= N` (and `RANK`/`INDEX`-based Top-N) used as a **filter** → route to the
     existing Top-N / query-set machinery (the skill already builds `ADVANCED` query sets for
     Top-N sets). This is the most common `INDEX()` use and needs no SQL.
   - `LOOKUP(agg, ±n)`, `FIRST()`/`LAST()` used as window **bounds/offsets** → native
     `moving_*`/`cumulative_*` with the recovered shelf sort.
2. **Gated pass-through fallback** — only when the worksheet yields an **unambiguous** sort +
   partition. Emit an **answer-level** (viz-scoped) `sql_*_aggregate_op` with an explicit
   `OVER (PARTITION BY … ORDER BY …)`, wrapped in `group_aggregate()` to satisfy the GROUP BY
   engine — mirrors how Sigma places these on the chart.

   | Tableau | Answer-level pass-through (Snowflake-flavored) |
   |---|---|
   | `INDEX()` (display row number) | `sql_int_aggregate_op ( "ROW_NUMBER() OVER (ORDER BY {0})" , [sort] )` |
   | `LOOKUP(SUM([m]), -1)` | `LAG(...) OVER (PARTITION BY … ORDER BY …)` |
   | `FIRST()` / `LAST()` (standalone) | `FIRST_VALUE/LAST_VALUE(...) OVER (...)` |
   | `SIZE()` | `COUNT(*) OVER (PARTITION BY …)` |
3. **Omit-and-log only when addressing is ambiguous** — pane-relative / restart-every /
   compute-along a non-axis dim, or genuinely recursive `PREVIOUS_VALUE` (a recursive CTE, not
   a scalar). Keep current behavior; do not guess an order.
4. **Always flag + report.** List every emitted pass-through in the migration report with its
   SQL and the standing caveats: must be **admin-enabled**, is **dialect-specific** (loses
   warehouse portability), and is **unvalidated** (verify values post-import).

### Decision tree (per detected table calc)

```
Intent is a Top-N / filter?               → native Top-N / query set            (best)
Intent is a running/offset/window-bound?  → native moving_*/cumulative_*        (portable)
Else, worksheet sort+partition
  unambiguously recoverable?              → answer-level sql_*_aggregate_op + flag
Else                                      → omit + log (current behavior)
```

### Longer-term (separate, platform-level — out of skill scope)

The portable end-state is **native context-following window functions**
(`row_number`/`lag`/`lead`/`first`/`last`/`percentile` that adapt `PARTITION BY`/`ORDER BY` to
the search query), extending the family ThoughtSpot already started with
`cumulative_*`/`moving_*`/`rank()`. That closes the gap without dialect-locked, unvalidated
pass-through. Note as a product input; not implementable in the skill.

### Files affected

- `agents/shared/mappings/tableau/tableau-formula-translation.md` — move
  `INDEX`/`LOOKUP`/`FIRST`/`LAST`/`SIZE` out of "Untranslatable"; add the tiered decision tree
  and answer-level pass-through forms
- `agents/cli/ts-convert-from-tableau/SKILL.md` — apply the decision tree in the table-calc
  translation step (reuse the existing shelf-sort extraction used for `moving_*`/`cumulative_*`)
- `agents/cli/ts-convert-from-tableau/references/coverage-matrix.md` (from BL-023) —
  reclassify these constructs once implemented
- Verification: re-run against the `tableau-migration-testing` corpus; expect the
  `INDEX`/`LOOKUP`/`FIRST`/`LAST` blocker count to fall from ~60 workbooks toward the
  ambiguous-addressing residue only

---

## BL-025 — Review connection-selection parity for the Databricks Genie agent skill `Tier 4`

**Source:** Live Tableau migration session (2026-06-16) — connection-identification feature (PR #88)
**Affects:** agents/databricks/skills/ts-convert-from-databricks-mv (Genie Code runtime)
**Status:** Open
**Related:** PR #88 (connection-identification prompt in the three CLI from-* skills)

### Problem

PR #88 added a how-to-identify-the-connection prompt (N name it / F filter by partial
string / L list all) to the connection-selection step of the three **CLI** from-* conversion
skills (`agents/cli/ts-convert-from-tableau`, `-from-snowflake-sv`, `-from-databricks-mv`).

The **Databricks Genie agent** skill (`agents/databricks/skills/ts-convert-from-databricks-mv`)
is a separate runtime (runs inside Databricks via `ThoughtSpotClient` / `%run ts_client`,
deployed by `databricks bundle deploy`). It is currently a thin ~63-line mirror with **no
explicit connection-selection step** — its steps are read MV → map to TML → import. So the
new prompt was not (and could not be 1:1) applied there.

### Question to resolve

Should the Genie skill gain an explicit connection-selection step for parity? The Genie
runtime already has `ThoughtSpotClient.connections_list()` (in `notebooks/ts_client.py`), so
the same N/F/L prompt is feasible using that instead of the `ts` CLI. Decide whether:
1. The Genie skill should surface connection selection at all (today it relies on the
   connection name being baked into the generated table TML), and if so
2. Mirror the N/F/L prompt against `client.connections_list()`, keeping wording consistent
   with the CLI skills.

Also review the sibling `agents/databricks/skills/ts-convert-to-databricks-mv` for any
analogous list-pick UX that should match.

### Notes

- `agents/databricks/` is not part of the root CLAUDE.md change-impact mirror set (cli /
  claude / coco-snowsight); it is its own deployable runtime, so parity is a deliberate
  review, not an automatic validator requirement.

---

## BL-028 — Audit mode: assess the visualization layer (chart types + dashboard→liveboard), not just the data layer `Tier 2`

**Source:** Live Catalog Health Workbook migration session (2026-06-17)
**Affects:** ts-convert-from-tableau (Audit mode, Steps A1–A4 / Migration Coverage Report)
**Status:** Open
**Related:** BL-023 (Tableau coverage matrix), BL-026 (liveboard builder + verified chart-types reference), BL-015 (audit-mode parity), BL-009 (Tableau mapping gaps)

### Problem

The Tableau Audit mode (Steps A1–A4) classifies **data-layer** constructs only —
formulas, sets, joins, sources — and the Migration Coverage Report reflects that.
It says nothing about the **visualization layer**: which chart/mark types each
worksheet uses, whether they map to a ThoughtSpot chart type, and how migratable
the dashboard→liveboard layout is. So a user assessing feasibility sees data-layer
coverage but no signal on whether the *visuals* will come across — even though the
skill already migrates dashboards to liveboards "with layout approximation", and a
verified ThoughtSpot chart-type enum now exists
(`agents/shared/schemas/thoughtspot-chart-types.md`, PR #92).

### Proposed approach

Extend Audit mode to classify the viz layer alongside the data layer:

1. **Parse each worksheet's chart/mark type** — `<pane>`/`<mark class=...>`,
   dual-axis, combo marks, table/text, maps, etc. — plus dashboard layout
   (`<dashboard>`/`<zone>` structure).
2. **Classify each against the verified chart-type enum** into tiers:
   **Native** (direct ThoughtSpot equivalent) / **Approximate** (maps with layout
   or encoding loss) / **Unsupported** (no equivalent — e.g. certain map/custom
   marks).
3. **Add a "Visualization coverage" section to the Migration Coverage Report (A4)**:
   per-chart-type counts + %, which sheets map cleanly vs approximate vs have no
   equivalent, and dashboard→liveboard layout-fidelity notes.
4. **Fold viz coverage into the go / caution / no-go recommendation** (e.g. "data
   layer 90% native, but 4 of 12 sheets use unsupported map marks → caution").
5. Reuse the chart-type intent mapping shared with BL-026 so the auditor and the
   liveboard builder classify consistently.

### Files affected

- `agents/cli/ts-convert-from-tableau/SKILL.md` — Audit steps (classify worksheet chart types + dashboard layout); coverage report (A4) viz-coverage section + recommendation
- `agents/shared/schemas/thoughtspot-chart-types.md` — reuse/extend the chart-type + intent mapping for the classifier
- `agents/cli/ts-convert-from-tableau/references/coverage-matrix.md` (from BL-023) — add visualization-layer rows

## BL-026 — `ts-object-liveboard-builder` skill: build the best liveboard for a domain + suggest KPIs `Tier 2`

**Source:** Live chart-type testing + design session (2026-06-16)
**Affects:** new skill `agents/cli/ts-object-liveboard-builder`; shared analytics references; `ts-convert-from-tableau` (optional hand-off)
**Status:** Open — design complete, not yet scheduled
**Design:** [`docs/designs/ts-object-liveboard-builder.md`](designs/ts-object-liveboard-builder.md)
**Reference:** [`agents/shared/schemas/thoughtspot-chart-types.md`](../agents/shared/schemas/thoughtspot-chart-types.md) (verified chart-type enum + intent mapping)
**Related:** PR #92 (this design + chart-type reference); complements `ts-convert-from-tableau`, distinct from `ts-object-model-coach`

### Problem

`ts-convert-from-tableau` is deliberately *faithful* — it inherits the source dashboard's
gaps (missing KPIs, dated chart choices, no exec summary). A user with a good ThoughtSpot
**Model but no dashboard** has nothing to migrate at all. There is no skill that asks *given
this data, what is the best analytical product we could build?* — answered as a senior BI +
domain analyst — nor one that **reviews a model and proposes the KPIs/measures it's missing**.

### Proposed approach

A standalone, model-first skill **`ts-object-liveboard-builder`** (family `ts-object-*`,
parallel to `ts-object-model-builder`). Core is a **7-stage recommendation engine**: profile
the model → classify column roles → detect domain → build an analytical agenda → match a
domain **KPI library** → propose **new measures the model lacks** → select chart types (from
the verified 24) → compose an opinionated board (exec summary + themed tabs). Plan-first
approval; grounded only in real columns; reversible model changes. Reuses the model picker
(G/N/F/L) and the obj_id read-back rule from `ts-convert-from-tableau`. Liveboard emission +
chart selection extracted to shared references consumed by both skills.

Modes: **Build** (full), **Enrich-only** (review model → suggest/create measures, no
liveboard — directly satisfies the "suggest KPIs to improve analytics" ask), **Plan-only**
(write a board spec, no writes).

### Phasing

See the design doc §11. Phase 0 (this PR): verified chart-types reference + design. Phase 1:
shared `chart-selection.md` + `kpi-library.md`. Phase 2 (min useful release): builder skill in
Plan-only/Enrich mode. Phase 3: Build mode (emission). Phase 4: measure creation. Phase 5:
Tableau "enhance instead of mirror" hand-off. Phase 6: domain-library growth + evals.

### Open questions (from the design)

1. New measures on the existing model (reversible) vs a copy?
2. Which domains to seed in the KPI library first (beyond banking/retail/generic)?
3. Tableau hand-off: replace the faithful board, or add a "Recommended" one alongside?
4. Plan delivery: in-chat table and/or a written `*.plan.md` artifact?
5. Keep enrichment inside the builder, or commit now to a future `ts-object-model-enrich`?

---

## BL-029 — Coverage matrices for the remaining three conversion skills — DONE `Tier 1`

**Related:** `tools/validate/check_coverage_matrix.py` BACKLOG set; repo quality audit (codification follow-up)
**Status:** DONE — all 9 conversion skills now have coverage matrices. The last one
(`ts-convert-to-databricks-mv`) shipped in PR #257; the `BACKLOG` set in
`check_coverage_matrix.py` is empty. Closed 2026-07-22.

### Problem

~~Three~~ ~~Two~~ ~~One~~ Zero `ts-convert-*` skills lack a `references/coverage-matrix.md`.
`ts-convert-from-databricks-mv` shipped its coverage matrix in PR #232 (74 mapped
constructs, 10 limitations). `ts-convert-to-snowflake-sv` shipped its coverage matrix
(24 mapped constructs, 13 limitations) as part of BL-100 Phase 0 doc reconciliation.
`ts-convert-to-databricks-mv` shipped its coverage matrix (65 mapped constructs, 11
limitations) in PR #257.

**Target:** ~~2026-08-31~~ Completed 2026-07-22.

---

## BL-030 — ThoughtSpot model-level NL instructions: migrate model-coach off manual paste to the `ai/instructions` API `Tier 2`

**Source:** first full audit sweep, 2026-06-17 (angle 13). See `docs/audit/2026-06-17-full.md` findings #1–#3.

### Problem

`ts-object-model-coach` writes `instructions.md` for the user to **manually paste** into
Settings → Coach Spotter → Instructions, because open-item #4 (probed 2026-04-25) found no
working API — it tried `sage/spotter/metadata` route prefixes and got 500s. The product has
since shipped a programmatic surface the open-item missed: **`POST /api/rest/2.0/ai/instructions/set`**
and **`/ai/instructions/get`** (Beta since 10.15.0.cl), payload
`{data_source_identifier, nl_instructions_info:[{instructions:[...], scope:'GLOBAL'}]}`,
requiring `CAN_USE_SPOTTER` + `SPOTTER_COACHING_PRIVILEGE`.

### Approach

1. Re-probe `ai/instructions/set|get` against a live instance (the route the open-item missed).
2. Add a `ts` command wrapping set/get; replace the manual-paste fallback in model-coach Step 6.5/8b/9a.
3. Re-frame `model-instructions-schema.md` "Where it lives in TML" around the API (scope `GLOBAL` only today), not a TML round-trip — re-validate the round-trip assumption before any v1.1 TML work.
4. Add a model-level instructions note to `thoughtspot-model-tml.md` once the API-vs-TML question is settled (`tml_probes.py:129` already reads `model.model_instructions.data_model_instructions`).

**Target:** 2026-09-30.

---

## BL-031 — Snowflake to-SV converter: emit `facts[]` / `sample_values` / filter-labels in YAML mode `Tier 2`

**Source:** full audit sweep 2026-06-17 (angle 13), findings #4–#6. Referenced from `agents/shared/schemas/snowflake-schema.md`.

### Problem

The published semantic-view YAML spec now accepts constructs the converter still treats as
DDL-only or unsupported: per-table `facts:`, dimension `sample_values:` (Snowflake-recommended
for Cortex Analyst accuracy), `labels: [filter]`, `unique:`, `cortex_search_service:`,
`access_modifier:`, and `base_table.definition:` (SQL-query logical tables, GA 2026-06-26 —
audit 13.4). The schema doc has been corrected (2026-06-17); the **converter emit
behaviour has deliberately not changed** pending verification.

### Approach

1. Verify each construct against a live `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` round-trip
   (the agent verified against published docs, not a live warehouse).
2. Update `to-snowflake-sv` to emit `facts[]` natively (instead of down-converting to metrics)
   and populate `sample_values` for dimensions; stop stripping the now-valid fields.
3. Bump the `snowflake-schema.md` currency anchor to a live-verified date.

**Target:** 2026-09-30.

---

## BL-032 — Databricks Metric Views: parser support for GA constructs (`materialization:`, `fields:`), retire v0.1 framing `Tier 2`

**Source:** full audit sweep 2026-06-17 (angle 13), findings #8–#10. Referenced from `agents/shared/schemas/databricks-metric-view.md`.

### Problem

Metric Views went GA 2026-04-02 (schema doc corrected). Remaining work: the `from-databricks`
parser keys only on `dimensions:` (misses the GA `fields:` alias) and ignores the top-level
`materialization:` block (could be silently dropped or error); the v0.1 section is framed as a
co-equal current option (docs now document 1.1 only, default 1.1); the measure `window:` field
underpins a large translation block but is marked **Experimental** in current docs.

### Approach

1. Extend the `from-databricks` parser for `materialization:` and the `fields:`/`dimensions:` alias.
2. Condense the v0.1 section to "legacy — may be encountered"; confirm the parser still reads it.
3. Re-verify the `window:` `range`/`offset`/`semiadditive` shape against the current build before relying on the rolling/semi-additive translations.
   **Update 2026-07-03 (external sweep, finding 13.7):** scope extended — the current
   YAML reference documents `range` with five values (`current | cumulative | trailing |
   leading | all`) plus an `inclusive|exclusive` anchor-row modifier (default `exclusive`).
   `leading`/`all` are now recognised in the schema and mapping docs but their ThoughtSpot
   translations are marked PENDING LIVE VERIFICATION (candidates: `moving_sum([m], 0, N, [date])`
   for `leading`, partition-wide `group_aggregate(...)` for `all` — neither shipped). The
   live re-verify in this step must also confirm/refute the `trailing N day` ↔
   `moving_sum([m], N, 0, [date])` equivalence against the documented `exclusive` anchor
   default, which postdates when that equivalence was first recorded.

   **Update 2026-07-09 (PR1 live verification):** `trailing N day` (default/exclusive) —
   CORRECTED (was `moving_sum([m], N, 0, [date])`, which actually reproduces `trailing
   (N+1) day inclusive`; now `moving_sum([m], N, -1, [date])`). `inclusive|exclusive`
   anchor default — CONFIRMED `exclusive`. `leading N day` (default/exclusive) —
   CORRECTED (was PENDING candidate `moving_sum([m], 0, N, [date])`, which matches
   neither DBX form; now `moving_sum([m], -1, N, [date])`). `range: all` (partition-wide
   `group_aggregate(...)`) — CONFIRMED. `range: cumulative` (`cumulative_sum(...)`) —
   CONFIRMED. `semiadditive: last`/`first` (`last_value`/`first_value`) — CONFIRMED.
   `range: current` + `offset: -N <unit>` — CORRECTED (was wall-clock
   `sum_if(diff_months/quarters/years([date], today())=N, [m])`; live testing showed
   the mechanism is row-relative, not wall-clock — now `moving_sum([m], N, -N, [date])`,
   a LAG(N) idiom valid only with exactly one row per period; quarter/year grains and
   N>1 are Deferred (C8), extrapolated from the verified month-grain N=1 case, not
   separately live-tested). Full evidence:
   `docs/audit/2026-07-08-dbx-window-claim-matrix.md`. Remaining BL-032 scope:
   `materialization:`/`fields:` **parser** support (PR2, not a docs gap) and C8's
   quarter/year grain re-verification if ever needed. Window `range`/`offset`/
   `semiadditive`/anchor-modifier semantics are now fully resolved — the parser can
   implement all 5 range values directly in PR2, no `pending_verification` skip path
   needed for `leading`/`all`.

   **Update 2026-07-09 (PR1.5 semantic deep-dive):** LOD dimension × filter
   interaction — CONFIRMED filter-aware on ThoughtSpot under both filter kinds
   (query-level pin and model-level `filters:`), with a cross-platform DIVERGENCE
   caveat: the equivalence holds for a Databricks MV's own global `filter:` block
   only, not for a consumer's ad hoc query-time `WHERE` on an unfiltered MV (A1/A2).
   Cross-measure ratio × grain — CONFIRMED ratio-of-sums cross-platform at every
   grain tested (fine/coarse/total), no sum-of-ratios or average-of-ratios
   divergence (B1). Global filter × window ordering — CONFIRMED filter-before-window
   cross-platform; split verdict, frame semantics DIVERGENCE (C1, same root cause as
   E1 below). Semi-additive × date-range filter — CONFIRMED last/first-in-filtered-
   range cross-platform, including the single-surviving-row edge case (D1).
   Trailing-frame rows-vs-dates (E1, gapped-data probe of PR1's C1/C3) — DIVERGENCE:
   Databricks `trailing`/`leading N day` frames are date-interval framed; ThoughtSpot
   `moving_sum` is row-positional; the two produce different numbers on sparse/gapped
   data. PR1's C1/C3 CONFIRMED verdicts were density-conditional (dense daily fixture
   only) — this is now caveated in every trailing/leading mapping site. Filed
   BL-098 for the E1/C1-frame divergence's follow-up action items (PR2 density-check
   warning flag, PR3 sparse-data-risk annotation). Full evidence:
   `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`. This closes the remaining
   discriminating-experiment gap the spec's PR 1.5 paragraph flagged — all four
   dimension/metric semantic constructs now carry a live-verified verdict before
   PR 3 (`translate-formulas`) encodes them in code.

   **Update 2026-07-09 (A3, user-suggested follow-up to A1/A2):** the A1/A2 "DBX's
   filter-kind sensitivity has no TS analogue" conclusion is CORRECTED. Live-tested
   `group_aggregate`'s documented empty-set filter argument, `group_aggregate(sum(x),
   {dim}, {})`: it is blind to a search-level/query-time filter (matches DBX's ad hoc
   query-time `WHERE`-blind reading) but still respects a model-level `filters:`
   block (matches DBX's own MV-global-`filter:`-aware reading) — exactly DBX's
   composite. `group_aggregate(sum(x), {dim}, {})` + a model-level `filters:` block
   mirroring the MV's `filter:` therefore reproduces BOTH halves of the DBX
   composite in one ThoughtSpot construct. `query_filters()` remains the default LOD
   mapping (simpler formula, matches the common MV-global-`filter:` case); `{}` +
   a mirrored model filter is the refinement for reproducing a DBX consumer's ad hoc
   query-time-`WHERE`-blind LOD specifically. A candidate subtraction form,
   `query_filters() - { [TABLE::col] }` (also documented in
   `thoughtspot-formula-patterns.md`), was import-accepted but did not exclude a
   filter pinned on a *derived* boolean formula built from the subtracted column —
   recorded as a live finding, not a working alternative. No new backlog item filed
   — this is a resolved refinement, not an open divergence or blocker. Full evidence:
   `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` (A3).

**Target:** 2026-09-30.

---

## BL-033 — Dependency & CI supply-chain hygiene

**Source:** full audit sweep 2026-06-17 (angle 16), findings #16–#19.
**Status:** DONE — all three items completed across later PRs.

1. `pip-audit` in CI — done (validate.yml `pip-audit` step, PR #173).
2. Python floor raised to `>=3.10`, cap lifted to `<3.15`, 3.14 in CI matrix — done (BL-106, BL-107).
3. `requests` floor bumped to `>=2.33.0` — done (BL-105). Lock file decision deferred (BL-075).

### Problem

No dependency-vulnerability gate (no `pip-audit`/`safety` step, no `.github/dependabot.yml`);
`requires-python` floor is `>=3.9` (EOL Oct 2025, never exercised — CI tests only 3.12); runtime
deps are floor-only with no lockfile (`requests>=2.28` permits CVE-affected <2.32.0); CI installs
unpinned tooling (`pip install pytest pyyaml`).

### Approach

1. Add a `pip-audit` job to `validate.yml` + a `.github/dependabot.yml` (pip + github-actions).
2. Raise the Python floor to `>=3.10` (or add 3.10/3.11 to a CI matrix if the floor is kept).
3. Add a constraints/lockfile; bump the `requests` floor to `>=2.32.0`; pin or extras-ify CI tooling deps.

---

## BL-034 — tools/ & ts-cli quality polish `Tier 3`

**Source:** full audit sweep 2026-06-17 (angles 4, 5, 14), findings across tools-quality / ts-cli-gaps / performance.

### Problem

A cluster of low/medium tool-quality issues: `model-coach` exports feedback TML one GUID per
round-trip (`ts tml export` takes multiple GUIDs — pure batch win, no attribution trade-off);
`databricks_sql` polls only on `PENDING` and ignores `RUNNING`; `import_tml` GUID back-fill uses a
brittle first-name regex; `report` deep-probe swallows all errors as "alias not supported"; `report`
walker re-queries leaf ANSWER/LIVEBOARD dependents; `report` resolver multi-part name lookup likely
never matches 2-/3-part names; the `model-coach` changelog claims a FEEDBACK export flag the CLI
rejects; `.gitignore` has ~4 stale entries pointing to non-existent paths.

### Additional scope (codification sweep 2026-06-29)

Three new ts-cli commands identified by the angle #11b codification sweep that belong here:

- **`ts tml strip-columns`** — remove unused columns from Table/View TML before repoint
  (ts-dependency-manager Steps 9b–9c, ~250 lines of mechanical logic today)
- **`ts tml repoint`** — repoint a TML object's table/connection references
  (ts-dependency-manager Steps 9b–9c, paired with strip-columns)
- **`ts tml export-corpus`** — parallel cached TML export with local cache directory
  (ts-audit Step 2, ts-object-model-coach Step 4.5; shared infrastructure pattern)

These are reusable TML manipulation primitives. See `docs/audit/2026-06-29-codification-sweep.md`
priorities #6 and #8.

### Approach

Fix opportunistically, each with a focused test. The batch-export and `databricks_sql` `RUNNING`
poll are the highest-value. The three codification-sweep commands (`strip-columns`, `repoint`,
`export-corpus`) are medium priority — implement when the consuming skills are next touched.

**Target:** 2026-10-31.

---

## BL-035 — Test-suite integrity gaps

**Source:** full audit sweep 2026-06-17 (angle 6).
**Status:** DONE (final items PR #292).

### Problem

Two assertions can't actually fail: `ts-dependency-manager`'s round-trip step treats an **ERROR
import as success** (the round-trip assertion is vacuous), and the `to-databricks` DDL "validation"
asserts substrings on a string the test itself just built (tautological). Plus
`smoke_ts-metadata-report.py` is orphaned (never run by any harness, leaving `ts metadata report`
unexercised — **RESOLVED 2026-07-03:** deleted in PR #172, which also added a reverse orphan
check to `check_smoke_tests.py`), the `smoke-tests/README.md` Scripts table is stale (lists 3
of 11), and the business-days recipe smoke header references an old skill name. Also
(2026-07-03 audit 1.6): `smoke_sv_minimal.yaml` / `smoke_sv_test.yaml` are referenced by
nothing and pin "as of 2026-04" environment facts — document them in smoke-tests/README.md
or delete them as part of this item.

### Approach

1. Make the dependency-manager round-trip step fail on a non-OK import status.
2. Replace the tautological to-databricks assertion with a real parse/round-trip check.
3. Wire or remove the orphaned report smoke test; refresh the smoke README table; fix the stale header.

**Target:** 2026-10-31.

---

## BL-036 — Databricks-native connection creation `Tier 3`

**Source:** create-connection feature work 2026-06-17 (`ts connections create` + convert-from connection step).
**Affects:** ts-cli (`connections create`), ts-convert-from-databricks-mv

### Problem

`ts connections create` supports **Snowflake key-pair** auth only, so `ts-convert-from-snowflake-sv`
(and `ts-convert-from-tableau` for Snowflake sources) can create a connection in-flow. Databricks
connections authenticate with a **Personal Access Token or OAuth (M2M)**, not key-pair — so
`ts-convert-from-databricks-mv` has no create path and falls back to "stop & instruct" (create in the
ThoughtSpot UI, then resume). This is path A, chosen deliberately for the initial feature.

### Approach

1. Extend `ts connections create` with a Databricks mode: `--host`, `--http-path`, and a PAT
   (read from a file path or the keychain via `/ts-profile-databricks`, never pasted into chat),
   `data_warehouse_type=DATABRICKS`, `authenticationType` per the connection API.
2. Verify the create payload shape against `get-rest-api-reference(apiName: "createConnection")`
   and a live Databricks-backed instance before shipping.
3. Replace the databricks-mv "stop & instruct" fallback with the create branch (mirror the
   Snowflake skill's E/C prompt). Add a unit test for the Databricks payload builder.

**Target:** 2026-10-31.

---

## BL-037 — Recipe skills for common data investigation patterns (cohort, funnel, segmentation, time-series, A/B, RCA) `Tier 4`

**Source:** Review of `nimrodfisher/data-analytics-skills` repo, `03-data-analysis-investigation/` (2026-06-18)
**Affects:** New `ts-recipe-*` skills under `agents/cli/`
**Status:** Open
**Related:** Skill family 7 (`ts-recipe-*`) in `.claude/rules/skill-naming.md`

### Problem

Common analytical investigation patterns — cohort analysis, funnel analysis, segmentation,
time-series decomposition, A/B test analysis, root-cause investigation, and business metrics
calculation — are well-understood frameworks that users repeatedly build from scratch in
ThoughtSpot. The `nimrodfisher/data-analytics-skills` repo packages these as generic
Claude Code skills (markdown instructions + pandas scripts), but they are not
ThoughtSpot-aware: they operate on raw data, not on ThoughtSpot models/answers/liveboards.

ThoughtSpot-native recipe skills could produce real artifacts — formulas, answers, and
liveboards — that implement these patterns against the user's existing models, using
ThoughtSpot's native constructs (group_aggregate for cohort buckets, cumulative_sum for
funnel drop-off, parameters for A/B date ranges, etc.).

### Candidate skills (assess feasibility per pattern)

| Pattern | Candidate skill name | Primary TS artifact | Key constructs |
|---|---|---|---|
| Cohort analysis | `ts-recipe-answer-cohort-analysis` | Answer + formulas | group_aggregate for cohort bucketing, date-diff for retention, pivot via search |
| Funnel analysis | `ts-recipe-answer-funnel-analysis` | Answer + formulas | Cumulative filters, conversion rate formulas, step-over-step % |
| Segmentation | `ts-recipe-formula-segmentation` | Model formulas | IF/CASE bucketing, group_aggregate for segment metrics |
| Time-series | `ts-recipe-answer-time-series` | Answer + formulas | moving_average, cumulative_sum, period-over-period, seasonality via date buckets |
| A/B testing | `ts-recipe-answer-ab-test` | Answer + formulas | Parameter-driven date ranges, group comparison formulas, statistical significance (pass-through SQL) |
| Root-cause investigation | `ts-recipe-answer-root-cause` | Answer | Drill-down search patterns, contribution analysis via group_aggregate |
| Business metrics | `ts-recipe-formula-business-metrics` | Model formulas | Common KPIs (CAC, LTV, churn rate, NRR) as formula templates |

### Approach

1. Review each `nimrodfisher` skill's process steps and determine which translate to
   ThoughtSpot-native constructs vs which require raw SQL/pandas (and therefore don't fit).
2. For each viable pattern, build a `ts-recipe-*` skill that takes a model as input,
   asks the user to identify the relevant columns (e.g. "which column is the user ID?
   which is the signup date?"), and emits formulas + an answer/liveboard.
3. Reuse the `nimrodfisher` analytical frameworks as the domain logic reference (attribution:
   analytical patterns inspired by `nimrodfisher/data-analytics-skills`), but all code and
   ThoughtSpot-specific logic is original.

### Notes

- Each recipe is independent — no need to ship all at once. Start with the highest-value
  pattern (likely cohort or time-series, as these are the most-requested in ThoughtSpot).
- The `nimrodfisher` repo is MIT-licensed generic markdown — patterns are common analytical
  knowledge, not proprietary. The value-add is the ThoughtSpot-native implementation.

**Target:** Assess feasibility by 2026-09-30; ship first recipe by 2026-12-31.

---

## BL-039 — `ts-object-answer-promote`: support embedded Answers and set/cohort promotion `Tier 4`

**Source:** Resolving `ts-object-answer-promote` open items 4 & 5 (2026-06-19). Both were `UNTESTED`; on inspection neither is a shipped-unverified path — the skill handles **standalone Answers, formulas + parameters only** — so they were re-dispositioned as deferred scope and the open items closed.
**Affects:** `agents/cli/ts-object-answer-promote/` (Steps 2, 3, 4); `references/open-items.md` Items 4 & 5
**Status:** Open — enhancement, not a defect

### Scope

Two independent capability gaps the current skill intentionally does not cover:

1. **Embedded Answers (Item 4).** Step 2 searches `ts metadata search --type ANSWER`, which
   returns only standalone saved Answers. A formula living in a Liveboard-embedded Answer
   can't be found or promoted today. Enhancement: detect/resolve embedded Answers out of a
   Liveboard TML, then run the existing promotion path. Open questions: does Answer search
   ever surface embedded Answers (expected no); the Liveboard TML structure for embedded
   Answers; whether their formulas reuse the same `formulas[]` / `expr` shape.

2. **Set/cohort promotion (Item 5).** Sets appear as `cohorts[]` in Answer TML (BIN_BASED and
   COLUMN_BASED — structure verified). The skill detects them and tells the user they need
   separate promotion. Enhancement: build a standalone set object from the answer-level
   cohort entry and import it, then verify the reusable set works as a column in new Answers
   on the same Model.

### Approach

Each is independent and can ship separately. Both require live-instance verification
(`se-thoughtspot` smoke profile) before shipping — build the test objects (an embedded
Answer in a Liveboard; a BIN_BASED and a COLUMN_BASED set), run the procedures recorded in
the old open-items entries, and record findings. When built, re-open concrete open items for
the specific API behaviours rather than carrying the broad gaps here.

**Target:** No date — schedule when embedded-Answer or set-promotion demand is confirmed.
## BL-038 — `ts-recipe-formula-weighted-average` skill `Tier 4`

**Source:** Tableau migration sessions (`tableau-migration-testing/twb/test/Weighted Usage.twb`) + production weighted-cost formulas (Albertsons / JD Power). Spun out of the weighted-average mapping work (`feat/weighted-average-mapping`, 2026-06-19).
**Affects:** New `ts-recipe-formula-weighted-average` skill under `agents/cli/` (pure-ThoughtSpot — no platform suffix); family 7 (`ts-recipe-*`)
**Status:** Open — deferred deliberately. The mapping/coverage knowledge that makes the **converters** weighted-average-aware shipped first (see Related); this standalone interactive recipe is the second, larger deliverable.
**Related:** BL-037 (recipe skills for investigation patterns); `thoughtspot-formula-patterns.md` → "Weighted average"; `tableau-formula-translation.md` LOD section ("boolean predicate inside a FIXED partition"); coverage-matrix rows 110–112.

### Problem

Users repeatedly hand-build weighted-average measures in ThoughtSpot, and get them wrong in
predictable ways. The arithmetic (`Σ(v×w)/Σ(w)`) is trivial; the judgement is not.

### Why it must NOT be a dumb template

A "inject your numerator and weight columns" builder is a footgun. The two decisions that
actually determine correctness are exactly the ones a template skips:

1. **The pre-weighted vs computed fork.** A large share of real "weighted" fields are
   *already weighted at source* (e.g. a `WEIGHTED_USAGE` column). Wrapping a `Σ(v×w)/Σ(w)`
   template around such a column double-counts the weight. The skill must detect/ask which
   situation it is in **before** emitting anything.
2. **Grain.** The `{ grain }` of the inner `group_aggregate` is the level the weight is
   meaningful at (per product, per account…), not the viz display grain. Plus the
   bare-vs-`sum(group_aggregate(...))` re-aggregation choice.

### Approach

1. Reuse the now-shipped `thoughtspot-formula-patterns.md` "Weighted average" section as the
   domain logic — the skill is the interactive front end, not a second source of truth.
2. Step 1: ask whether a pre-weighted column exists (fork). Step 2: if computed, collect
   value + weight columns and the grain. Step 3: emit the formula(s) and optionally insert
   into a Model TML (mirror the `formulas[]` + `columns[]` pattern from
   `ts-recipe-formula-business-days-snowflake`).
3. Decide whether unweighted-companion + a verified worked example are in v1 scope.

**Target:** Assess demand before scheduling — only build once standalone (non-migration)
weighted-average asks are recurring. No date set.

---

## BL-040 — Databricks `shared/` should copy from canonical `agents/shared/` at deploy time

**Source:** 2026-06-19 — discovered `agents/databricks/shared/schemas/` is a stale snapshot of `agents/shared/schemas/`, gitignored and drifting (missing range join docs, currency anchors, I11 invariant).
**Affects:** `agents/databricks/deploy.sh`, `agents/databricks/shared/schemas/`
**Status:** DONE — `deploy.sh` already copies fresh from `agents/shared/` on every deploy
(`rm -rf` + `cp`); the gitignored local `agents/databricks/shared/` is a deploy artifact,
not a source of truth.

### Problem

`agents/databricks/shared/schemas/` duplicates files from `agents/shared/schemas/` but is gitignored — no validator catches drift. The Databricks Genie Code skills read stale guidance when the canonical files are updated.

### Approach

Make `agents/databricks/deploy.sh` copy the relevant files from `agents/shared/` at deploy time (same pattern as CoCo's `stage-sync.sh`), eliminating the local copy as a source of truth. Remove `agents/databricks/shared/schemas/` from the repo and add the copy step to the deploy script.

**Target:** Next time Databricks skills are actively worked on. No date set.

---

## BL-041 — `ts-recipe-model-timezone-bridge-snowflake` skill `Tier 4`

**Source:** 2026-06-19 — built and verified a timezone-aware model on champ-staging (model `f9ce44d9`). Pattern documented in [Google Doc](https://docs.google.com/document/d/1ouU8TW2EU18DUk1gScGHna1IAK4CzVHKj429YQjPXpo/edit).
**Affects:** New skill under `agents/cli/ts-recipe-model-timezone-bridge-snowflake/`; family 7 (`ts-recipe-*`)
**Status:** Open

### Problem

Customers with UTC-stored timestamps need timezone-aware reporting without materialising date keys per timezone on every fact row. The pattern — a lightweight bridge table with range joins and a `ts_var(ts_user_timezone)` formula filter — is non-obvious and easy to get wrong (range join syntax, boolean filter pattern, DST handling, fan-out prevention).

### Approach

Interactive recipe that collects inputs and generates all artifacts:

1. **Collect inputs:** ThoughtSpot connection name, Snowflake database/schema, fact tables + their timestamp columns, list of IANA timezones to support (e.g. `America/New_York`, `Australia/Sydney`), date range for the bridge table
2. **Generate + execute Snowflake DDL:** `DATE_TZ_BRIDGE` table using `CONVERT_TIMEZONE` + `GENERATOR` date spine, crossed with the user's timezone list
3. **Register tables in ThoughtSpot:** table TMLs for bridge + fact tables (if not already registered)
4. **Generate model TML:** range joins from each fact table to bridge, `ts_var(ts_user_timezone)` boolean formula filter, `unique count` measures
5. **Import + verify:** import all TML, confirm model loads

### Key design decisions

- User must specify which timezones to include — the bridge table is sized per timezone (~365 rows/tz/year), and the timezone list determines which `ts_user_timezone` values are valid
- No DIM_DATE required — ThoughtSpot auto-generates date-part hierarchies from `local_date`
- Bridge table handles DST transitions via pre-computed UTC boundaries
- Platform suffix `-snowflake` because bridge DDL uses Snowflake-specific functions (`CONVERT_TIMEZONE`, `GENERATOR`)

### Verified patterns (from champ-staging session)

- Range join syntax: `[FACT::ts] >= [BRIDGE::utc_start_ts] and [FACT::ts] < [BRIDGE::utc_end_ts]`
- `ts_var(ts_user_timezone)` works in model formulas (formula context)
- Boolean formula filter: `oper: in, values: ["true"]` on a hidden formula column
- ThoughtSpot normalises `on` with parens and uppercase `AND` on export

**Target:** No date set. Build when timezone-aware modelling requests recur.

---

## BL-043 — Evaluate two-phase import and formula translation pipeline for other conversion skills `Tier 3`

**Source:** `ts-convert-from-tableau` v1.16.0 (feat/tableau-translate-formulas)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv, ts-convert-to-snowflake-sv, ts-convert-to-databricks-mv
**Status:** Not started

### Problem

The Tableau conversion skill now has three patterns that significantly improved migration
reliability and accuracy:

1. **Two-phase model import** — Phase 1 imports the base model (tables, columns, joins,
   parameters, no formulas) for guaranteed success; Phase 2 adds formulas via GUID-pinned
   update with iterative error recovery. One bad formula no longer blocks the entire model.
2. **Deterministic formula translation pipeline** — a CLI command (`ts tableau translate-formulas`)
   applies all transforms in a strict order instead of relying on ad-hoc LLM reasoning.
   Closed a 47%→90%+ migration gap on real workbooks.
3. **Cross-reference depth reporting** — audit mode reports formula dependency depth
   (Level 0/1/2+/circular) alongside syntax-level tier classification, giving an honest
   "effective migration coverage" number.

The other conversion skills (`from-snowflake-sv`, `from-databricks-mv`, and the `to-*`
directions) may benefit from the same patterns — particularly the two-phase import, which
is platform-agnostic. The formula pipeline is Tableau-specific, but the concept of a
deterministic transform sequence (vs LLM reasoning) may apply to Snowflake Semantic View
and Databricks Metric View formula translation.

### Proposed approach

1. **Two-phase import** — evaluate for `from-snowflake-sv` and `from-databricks-mv`. Both
   skills currently import the full model in one pass. The two-phase pattern is most
   valuable when formula counts are high and cross-references are common. Snowflake SVs
   have `metrics` (which can reference other metrics) and Databricks MVs have `measures`
   (which can reference dimensions). Check whether these create the same failure mode.
2. **Formula translation pipeline** — assess whether the Snowflake and Databricks formula
   mappings (in `agents/shared/mappings/`) are complex enough to warrant a deterministic
   CLI pipeline vs the current inline mapping approach. The Tableau pipeline was justified
   by 14 ordered transforms with cross-reference resolution; Snowflake/Databricks may have
   fewer transforms and simpler dependency graphs.
3. **Cross-reference depth reporting** — add to both `from-*` audit modes if the formula
   dependency analysis applies. Snowflake SVs have metric-references-metric chains;
   Databricks MVs have measure-references-dimension chains.
4. **Join confirmation** — less applicable since SVs and MVs define joins explicitly in
   their source format (unlike Tableau published datasources where joins are server-side).

Start with a review of recent migration failures in the other skills to determine
whether the same gap (audit overpromises vs actual migration rate) exists.

## BL-058 — ts-object-model-erd: interactive ERD renderer for ThoughtSpot Models

**Source:** Design spec `docs/superpowers/specs/2026-06-27-ts-object-model-erd-design.md`;
  implementation plan `docs/superpowers/plans/2026-06-27-ts-object-model-erd.md` (local, gitignored);
  validated mockup `docs/superpowers/specs/2026-06-27-ts-object-model-erd-mockup.html`
**Affects:** New skill `agents/cli/ts-object-model-erd/`; new shared module `agents/shared/erd/`;
  future `ts-audit` integration (per-model ERD in `audit_report.html`)
**Status:** DONE — shipped as `ts-object-model-erd` v1.0.0 (PR #142, 2026-07-01) and iterated
  through v1.7.0 (subject-area grouping, PR #160). The Python core (`parser.py`/`erd_data.py`/
  `render.py`) and the shared vanilla-SVG renderer (`agents/shared/erd/renderer.{css,js}`) both
  landed as specced. Remaining follow-on (`ts-audit` findings-overlay integration) is tracked
  separately, not under this item.
**Priority:** MEDIUM

### Problem

ThoughtSpot's in-product model/join viewer is hard to use, requires a login plus object
permissions, and can't overlay analysis. There is no way to hand someone a shareable,
self-contained picture of a Model's structure — tables, joins, columns, RLS — for review
or migration QA.

### Proposed approach (approach C — validated by mockup)

A new skill that renders an existing Model (Model TML + its Table TMLs) into a single
self-contained, interactive HTML ERD that opens in any browser with no TS login.

- **Python (stdlib + pyyaml)** owns the testable core: `parser.py` parses the Model TML and
  stitches its Table TMLs (RLS, join cardinality, join type, and join origin all live in the
  **table** TMLs, not the model); `erd_data.py` assembles a multi-model bundle (index +
  switcher + model cap with logging + `--redact-rls`); `render.py` inlines the renderer and
  injects the model JSON.
- **Renderer is a static vanilla-SVG asset** (`agents/shared/erd/renderer.{css,js}`, ported
  from the validated mockup) so `ts-audit` can reuse it. No JS build step, no external libs.
- **Inputs:** local TML files, or live export via `ts tml export "{guid}" --fqn --associated`.
- **Features (all proven in the mockup):** layouts (organic / star / layered →↓) with
  orthogonal routing; focus/ghosting + shift-click compare with shortest join path; column
  modes (collapsed / keys / flagged / all); findings overlay (populated later by ts-audit);
  RLS overlay + secured-subgraph isolate; Arrow vs Crow's-foot notation; table-vs-model join
  origin badges; localStorage saved layouts + bake-on-export.

### Scope notes

- Render-from-TML only. **Image → TML ingestion** (`ts-convert-from-image` /
  `ts-object-model-from-sketch`) is a separate, opposite-direction skill that would reuse this
  renderer behind a human-review loop — not part of this item.
- 8-task TDD plan already written; follow it task-by-task.
- Verify the real `rls_rules` field shape against a live `ts tml export` of a secured table
  (read defensively in the plan; repo schema docs don't document it).

---

## BL-059 — ts-audit: set (cohort) usage analysis checks `Tier 3`

**Source:** Live testing on champ-staging (2026-06-26) — Dunder Mifflin Sales model (`0e4406c7-d978-4be7-abd7-c34e8f7da835`, 44 reusable cohorts)
**Affects:** `tools/ts-cli/ts_cli/audit/checks_data.py` (new checks), `tools/ts-cli/ts_cli/audit/report.py` / `report_template.html` (report sections) — the audit engine was codified into `ts_cli/audit/*`; the former skill-dir `analyzer.py`/`report.py` were removed as dead code (2026-07-02)
**Status:** Open — research complete, implementation deferred
**Related:** `agents/shared/schemas/thoughtspot-sets-tml.md` (set TML structure reference)

### Problem

ThoughtSpot sets (cohorts) count as columns on a model — a model with 100 columns and 200 sets exposes 300 accessible columns to users, causing UX overload. Sets can also drift (identical definitions across multiple sets) and cluster on a small number of base columns. The `ts-audit` health report has no visibility into set usage patterns.

### Verified discovery mechanism

Sets are **not** returned via `ts metadata dependents` COHORT bucket on a model. They **are** returned via `ts tml export <model-guid> --fqn --associated` as `type=cohort` items alongside tables. The audit pipeline already does `--associated` exports, so the cohort data is available — it just needs to be extracted from the export response and populated into the `Corpus.sets` field (which exists but is never populated).

Consumer counting for individual sets: `ts metadata dependents <set-guid> --type LOGICAL_COLUMN` returns answers/liveboards that use the set.

### Proposed checks

| Check ID | Name | What it detects | Severity |
|---|---|---|---|
| D12 | Set count check | Models where `columns + sets > threshold` (e.g. 150). Too many accessible columns degrades UX (search suggestions, column picker overload). | WARNING at 150, CRITICAL at 300 |
| D13 | Unused set detection | Reusable sets with 0 consumers (`ts metadata dependents` returns empty). Unused reusable sets add noise — suggest deleting or converting to answer-level. | WARNING |
| D14 | Duplicate set definition | Sets with identical `config` blocks (same `cohort_type`, `cohort_grouping_type`, `anchor_column_id`, and filter/bin config). Definition drift — multiple sets doing the same thing. | WARNING |
| D15 | Base column concentration | Anchor column usage analysis — which base columns (`config.anchor_column_id`) are used across sets, and how often. High concentration on one column may indicate over-segmentation. | INFO |

### Key technical details

- **Set TML structure:** `cohort.config.cohort_type` (SIMPLE = column set, ADVANCED = query set), `cohort.config.cohort_grouping_type` (BIN_BASED / GROUP_BASED / COLUMN_BASED), `cohort.config.anchor_column_id` (base column the set operates on), `cohort.worksheet` (model binding)
- **Corpus integration:** `Corpus.sets: list[dict]` field exists at `analyzer.py:83` but is never populated. Populate from `--associated` export filtering for `type=cohort`
- **Test model:** Dunder Mifflin Sales on champ-staging — 44 reusable cohorts, mix of SIMPLE and ADVANCED, consumer counts ranging from 0 to multiple

### Implementation notes

1. **Extract sets from `--associated` export** — filter the export response for items with `type=cohort`, parse each cohort TML, populate `Corpus.sets`
2. **D12 (set count)** — count columns from model TML + count sets from corpus, compare against threshold
3. **D13 (unused sets)** — for each set GUID, run `ts metadata dependents <guid> --type LOGICAL_COLUMN`; flag those with 0 dependents
4. **D14 (duplicate definitions)** — hash the relevant `config` fields across all sets; group by hash; flag groups with >1 member
5. **D15 (base column concentration)** — extract `anchor_column_id` from each set; count frequency; report distribution

### Dependencies

- The audit pipeline's `--associated` export already retrieves cohort TMLs — no additional API calls needed for discovery
- D13 (unused sets) requires one `ts metadata dependents` call per set — could be batched or rate-limited for models with many sets

**Target:** No date set — implement when ts-audit is next actively worked on.

---

## BL-060 — Tableau: detect nested-if-in-comparison formula pattern

**Source:** Ads Commercial Dashboard migration (2026-06-27) — 1 formula hit this pattern
**Affects:** `tools/ts-cli/ts_cli/tableau/validate.py` (`validate_pre_import()`)
**Status:** DONE (ts-cli v0.85.0, `fix/tableau-quick-closeout` commit 50603af) — `[<>=!]=?\s*if\b`
regex check added to `validate_pre_import()`, mirroring the shipped BL-062 bare-else check.
Live-confirmed on Ads Commercial Dashboard's `Dimensions: TrafficLight` formula.

### Problem

A formula like `sum(X) < if(Y) then Z else W` is valid Tableau syntax but fails
ThoughtSpot import because the comparison operator binds before the `if` keyword.
ThoughtSpot requires parentheses: `sum(X) < (if(Y) then Z else W)`. This pattern
was hit once in the Ads migration and manually fixed during the import retry loop.

### Why deferred

Detecting this reliably requires understanding operator precedence in formula
expressions — a regex can't distinguish `< if(` in a comparison context from `< if(`
inside a string literal or a different syntactic position. Low frequency (1 occurrence
across 2 full migrations) doesn't justify the AST-level parsing needed.

### Proposed approach

Add a check to `validate_pre_import()` that looks for `<comparison_op> if(` patterns
outside of string literals. False positives are acceptable as warnings (the user
confirms or ignores). Alternatively, wrap all `if/then/else` blocks on the right side
of comparisons in parentheses during the translation step.

**Target:** No date set — revisit if the pattern recurs in future migrations.

---

## BL-063 — Extract CLI-based formula translation for Snowflake and Databricks converters `Tier 1`

**Source:** Architectural comparison of conversion skill implementations (2026-06-28)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv, tools/ts-cli
**Status:** DONE — all phases complete. Databricks track (2a/2b/2c + Phase 4 Databricks
half) shipped earlier. Snowflake SKILL.md rewiring: `ts-convert-from-snowflake-sv` rewired
onto `parse-sv` / `translate-formulas` / `build-model` (PR #286, 2026-07-22);
`ts-convert-to-snowflake-sv` rewired onto `build-sv` (PR #287, 2026-07-22). Phase 1c
(shared import error table + post-import verification extracted to `ts-tml-import-gate.md`
§4/§5, replacing ~100 lines of near-verbatim duplication across from-snowflake-sv and
from-databricks-mv) completed PR #288, 2026-07-22.
**Related:** BL-032 (Databricks parser support), BL-014 (Databricks coverage review)

### Problem

The Tableau converter delegates formula translation and model building to deterministic
CLI commands (`ts tableau translate-formulas` — 14-step pipeline in `tableau_translate.py`,
85KB; `ts tableau build-model` — 8 transforms in `model_builder.py`, 35KB). The LLM
orchestrates the workflow and makes judgment calls but does not do the translation itself.

The Snowflake and Databricks converters follow a fundamentally different pattern: the LLM
reads the mapping docs (`ts-snowflake-formula-translation.md`, `ts-databricks-formula-translation.md`)
and performs the translation inline — parsing DDL/YAML, translating formulas, and assembling
TML directly. There are 7-11 inline Python blocks in each SKILL.md for parsing/validation
helpers, but no CLI commands for formula translation or model building.

This means:
1. **Translation quality depends on the LLM correctly applying mapping docs every time** —
   the Tableau CLI pipeline is deterministic and produces identical output for identical input.
2. **Mapping-doc errors propagate to output** — the 2026-06-28 audit found contradictions
   within mapping files (wrong field names, stale "untranslatable" entries). The CLI pipeline
   is immune to these because the logic is in code, not docs the LLM interprets.
3. **No unit-testable translation path** — the Tableau pipeline has `pytest` coverage for
   pure functions; the Snowflake/Databricks translation is only testable via end-to-end
   smoke tests with a live instance.

### Proposed approach

Extract `ts snowflake translate-formulas` and `ts databricks translate-formulas` CLI
commands, mirroring the Tableau pattern:

1. **Input:** parsed source structure (DDL parse result / YAML parse result) + column map
2. **Output:** JSON with translated ThoughtSpot formula expressions + dependency DAG +
   cross-reference depth (same shape as `ts tableau translate-formulas`)
3. **Logic:** encode the mapping rules from the formula-translation.md files as code —
   identifier resolution, double-aggregation detection, cross-reference inlining, pass-through
   gating (PT1 policy)
4. **Unit tests:** pure-function tests for each translation rule, no live instance needed

### Phasing (expanded per codification sweep 2026-06-29)

| Phase | Scope | Estimate |
|---|---|---|
| 1a | `ts snowflake parse-sv` — parse SV DDL into structured JSON | ~1 week |
| 1b | `ts snowflake translate-formulas` — Snowflake SQL → ThoughtSpot formulas | ~2 weeks |
| 1c | `ts snowflake build-model` — assemble Model TML from parsed/translated data (adapter for existing `model_builder.py`) | ~1 week |
| 2a | `ts databricks parse-mv` — parse MV YAML into structured JSON | **DONE** (PR #200, ts-cli v0.42.0) |
| 2b | `ts databricks translate-formulas` — Databricks SQL → ThoughtSpot formulas | **DONE** (PR #202, ts-cli v0.43.0) |
| 2c | `ts databricks build-model` — assemble Model TML from parsed/translated data | **DONE** (PR4, ts-cli v0.44.0, 2026-07-10) |
| 3 | Reverse direction (`ts snowflake translate-formulas --reverse`) for to-SV | ~1 week |
| 4 | Update SKILL.md files to use CLI commands instead of inline LLM translation | **Databricks DONE** (PR4, `ts-convert-from-databricks-mv` v1.8.0); Snowflake OPEN |

### Decision to make first

Assess whether the translation rules are stable enough to codify. If the mapping docs
are still actively evolving (new constructs being added frequently), the LLM-driven
approach has an advantage: updating a markdown file is faster than updating code + tests.

### Scope extension — 2026-07-03 (full audit 11.3 + codification review)

Folded into this item rather than opened separately:

- **Quick wins that can ship ahead of the phases** (codification review 2026-07-03 rows
  3–4): extract the Mode-C diff helpers (`_normalise_expr`/`_exprs_differ` — currently
  copy-pasted as literal Python in BOTH Snowflake SKILL.mds, to:~1018 / from:~242) as
  `ts snowflake diff`, and codify the to-direction's 17-item manual DDL checklist as
  `ts snowflake lint-ddl` (the from-direction already gates on `ts tml lint`; the
  to-direction self-checks its own just-written DDL).
  **DONE 2026-07-03 (ts-cli v0.30.0):** both shipped as `ts snowflake diff` and
  `ts snowflake lint-ddl` (`tools/ts-cli/ts_cli/snowflake_ops.py` + `commands/snowflake.py`).
  `lint-ddl` covers 6 deterministic checklist items (identifier format, duplicate
  alias, undeclared table, metric-forward-reference, untranslatable placeholder,
  unescaped comment quote); the remaining items need aggregation/join-cardinality
  judgment or a reserved-word list broad enough to risk false positives, and stay
  manual — see Step 11 in `agents/cli/ts-convert-to-snowflake-sv/SKILL.md`. Both
  Snowflake SKILL.mds wired up (to: v1.3.0, from: v1.13.0). The remaining phases
  (1a-4, `build-sv`, shared lint+import procedure) are still open.
- **`ts snowflake build-sv`** (TS → SV DDL emission — PK clauses, alias-collision wrapper
  views, metric ordering) as the mirror of phase 1c.
- **Shared lint+import procedure** (audit 11.3): the ~200-line pre-import lint gate +
  Step 11 import procedure is near-verbatim across from-snowflake-sv (:1579-1660) and
  from-databricks-mv (:1117-1200). Phase 4 must extract this to a shared reference (or
  absorb it into the build-model commands) rather than leaving the duplication.
Once the mapping surface stabilises, extraction becomes higher-value.

**Target:** Assess feasibility by 2026-09-30. Schedule extraction only if mapping churn
has slowed and the quality gap is confirmed via smoke-test comparison.

**Update 2026-07-09 (PR1 feasibility-gate check):** per the design spec's Risks table
("if PR1 finds more high-severity drift than BL-064 already catalogued, stop and
re-raise feasibility before PR 2"), PR1's live window-semantics deep-analysis
(`docs/audit/2026-07-08-dbx-window-claim-matrix.md`) found 2 corrected mappings beyond
BL-064's catalogue — C1 (`trailing N day` anchor args) and C6 (`range: current` +
`offset` mechanism, wall-clock → row-relative). This is real drift, but both are now
resolved and locked with live citations against a Databricks fixture + ThoughtSpot
number-match; nothing is left PENDING or unresolved. **Stop-condition NOT triggered** —
this is in line with (not beyond) the churn BL-064 already catalogued. PR2
(`ts databricks parse-mv`/`translate-formulas`) may proceed.

**Update 2026-07-10 (PR4 — build-model + Phase-4 Databricks rewiring):** the Databricks
track completes phases 2a-2c and its half of Phase 4. `ts databricks build-model`
(ts-cli v0.44.0) assembles Model (+ Table) TML from `parse-mv`/`translate-formulas`
JSON with a TML invariant/lint gate and an optional `ts tml import`; `ts-convert-from-databricks-mv`
Steps 5/6/9/9.5/10/11 (v1.8.0) now call the deterministic 3-command pipeline instead of
inline LLM parsing/translation/assembly. Live e2e-verified against se-thoughtspot +
DBX_DAMIAN (Task 10), which surfaced and fixed 3 ts-cli defects along the way: the flat
import-response GUID shape in `extract_imported_guid`, connection-scoped GUID resolution
+ `BOOLEAN`→`BOOL` normalization in `ts tables create`, and in-band `ERROR`-status import
errors now surfaced via `build-model`'s `import_error` (previously swallowed as an empty
string). BL-098 items 1 and 2 (density-check warning, sparse-data-risk annotation) are
DONE as part of PR2/PR3 — see BL-098. **Remaining for the Databricks track:** PR 5 —
extract the shared lint+import procedure (the ~200-line duplication flagged in the
2026-07-03 scope extension, now also present a third time in the Databricks build-model
contract) and widen the pure-function vendorable surface (`ts_cli/databricks/`) for a
future Genie Code adoption. The Snowflake phases (1a-1c, `build-sv`, Snowflake's Phase 4)
remain OPEN and unscheduled.

---

## BL-064 — External audit 2026-06-28: Databricks + Snowflake product-currency fixes `Tier 1`

**Source:** External audit sweep 2026-06-28 (angle 13 — product currency)
**Affects:** agents/shared/schemas/databricks-metric-view.md, agents/shared/schemas/snowflake-schema.md, agents/shared/mappings/ts-databricks/, agents/shared/mappings/ts-snowflake/
**Status:** DONE — all 16 items fixed. Item 9 residual (cross-entity-type fields on time_dimensions/facts/filters) deferred to next Snowflake spec sweep; items 14-16 closed 2026-07-23.
**Related:** BL-032 (Databricks parser support — overlapping scope)

### Problem

The 2026-06-28 external audit found 4 high-severity and 9 medium-severity product-currency
findings across Databricks and Snowflake. These represent drift between our mapping/schema
docs and the current product state.

### High-severity (parse errors or silent data loss on current builds)

1. **`nulls_position` → `null_order`** — **FIXED** (PR #136). Renamed in all 9 occurrences.
2. **`fields:` is canonical; `dimensions:` is backward-compat** — **FIXED** (PR #137).
   Parser now checks `fields:` first, falls back to `dimensions:`. Schema doc updated.
   Overlaps BL-032 (broader v0.1 retirement remains open).
3. **Window `offset` requires Runtime 18.1** — **FIXED** (PR #137). Runtime gate
   documented in schema, SKILL.md, and mapping rules. Warning emitted in to-databricks.
4. **`cardinality:` join field undocumented** — **FIXED** (PR #137). Schema documents
   `cardinality:` as Runtime 18.1+ alternative to `rely:`. Parser extended to handle both.

### Medium-severity (stale claims, schema gaps)

5. `sample_values` listed as both supported and unsupported in snowflake-schema.md — **FIXED** (2026-07-23). Removed residual blockquote from "NOT supported" section; `sample_values` is correctly shown in the Complete Schema.
6. `verified_queries` now YAML-supported; schema marks it DDL-only — **FIXED** (2026-07-23). Added `verified_queries[]` to Complete Schema with sub-fields (name, question, sql, verified_at, verified_by, onboarding_question).
7. `custom_instructions`/`module_custom_instructions` YAML fields not documented — **FIXED** (prior to this audit — already in Complete Schema at 2026-07 currency correction).
8. `unique_keys` shown with wrong YAML structure in properties file — **FIXED** (2026-07-23). Added `unique_keys[]` to Complete Schema under `tables[]`; properties file structure was correct (list-of-objects with `columns[]`).
9. Complete Schema block missing ~15 now-supported YAML fields — **PARTIALLY FIXED** (2026-07-23). Added `verified_queries`, `unique_keys`, `relationship_columns[].type`, `relationship_columns[].right_range`. Remaining gaps: cross-entity-type fields (e.g. `tags`/`is_enum`/`cortex_search_service` on `time_dimensions`/`facts`/`filters`) need Snowflake YAML spec verification before adding — deferred to next currency sweep.
10. Three new Databricks window range types undocumented (`leading`, `all`, inclusive/exclusive) — **FIXED** (PR1, 2026-07-09). leading/all/inclusive-exclusive now documented in databricks-metric-view.md + both mapping files with live-verification citations — see the PR1 window-claim matrix.
11. Phantom `entities:`/`db_connection:` syntax in ts-to-databricks-rules.md — **RESOLVED — verified absent 2026-07-09.** No entities:/db_connection: syntax found in ts-to-databricks-rules.md or ts-databricks-properties.md as of this check; likely fixed silently in an earlier PR (#136/#137 touched adjacent Databricks fixes). No action taken.
12. `safe_divide` "No DIV0" comment is wrong; comparison table still says "Preview required" — **FIXED** (2026-07-23). Quick-reference in `ts-from-snowflake-rules.md` updated: `(a) / NULLIF(b, 0)` → `DIV0(a, b)` to match authoritative formula-translation.md; "no null guard" comment corrected to "no divide-by-zero guard".
13. `materialization:` block not documented — **FIXED** (PR1, 2026-07-09). Materialization block documented in databricks-metric-view.md (new section) and ts-databricks-properties.md — see Task 1 docs-research findings.

### ThoughtSpot medium-severity (separate, lower urgency)

14. ~~RLS rules ARE in table TML — schemas say they are not~~ **FIXED** (2026-07-23). Added `rls_rules` to `thoughtspot-table-tml.md` (structure + field reference).
15. ~~New TML export options (`export_column_security_rules`, `export_with_column_aliases`)~~ **FIXED** (2026-07-23). Added export_options table to `thoughtspot-tml.md`.
16. ~~`PARTIAL_OBJECT` import policy~~ **FIXED** (2026-07-23, via BL-123 item 13.1). Added to `ts-tml-import-gate.md` §3.

### Approach

Fix items 1-4 immediately (high severity). Items 5-13 fix as part of the next
schema/mapping update cycle. Items 14-16 document opportunistically.

For Databricks items that overlap BL-032: merge into BL-032's scope rather than
duplicating work. BL-032's target (2026-09-30) applies.

**Target:** High-severity items by 2026-07-15. Medium-severity items by 2026-09-30.

---

## BL-066 — Codify formula promotion as `ts model promote-formula` `Tier 3`

**Source:** codification sweep 2026-06-29 (angle #11b), priority #4.
**Affects:** `agents/cli/ts-object-answer-promote/`, `tools/ts-cli/`.
**Status:** OPEN.

### Problem

ts-object-answer-promote Steps 8–10 (duplicate detection, reference mapping,
column_type inference, TML merge) are entirely mechanical — the LLM reads answer formulas,
maps them to model columns, infers ATTRIBUTE/MEASURE from aggregation patterns, and emits
a merged Model TML. No judgment is needed; the operation is a deterministic merge.

### Approach

Build `ts model promote-formula` in ts-cli:
- Input: answer GUID + model GUID (+ profile)
- Export both TMLs, extract answer formulas, detect duplicates against model formulas,
  infer column_type from aggregation, emit merged Model TML
- Output: JSON with added formulas, skipped duplicates, and the updated TML

**Target:** 2026-10-31.

---

## BL-067 — Codify Tableau set/cohort detection and TML generation `Tier 3`

**Source:** codification sweep 2026-06-29 (angle #11b), priority #5.
**Affects:** `agents/cli/ts-convert-from-tableau/`, `tools/ts-cli/`.
**Status:** DONE (ts-cli v0.87.0, `feat/tableau-set-codify`) — the detection rules and target
TML shapes were already fully documented (`references/step-5-tml-generation.md` "Tableau Sets
→ ThoughtSpot column sets (Phase 2a/2b/2c)", `agents/shared/schemas/thoughtspot-sets-tml.md`);
this shipped the CLI implementation, not new design.

### What shipped

- `ts_cli/tableau/twb.py::extract_sets()` — extracts every top-level `<group>` Set from a
  datasource and classifies it (`static`/`except_members`/`intersect_members`/`topn`/
  `except_topn`/`condition`/`mixed`/`set_control`/`unclassified`), capturing the fields each
  emission rule needs (member lists, anchor column + datatype, Top-N count/order, condition
  expression). Wired into `ts tableau parse`'s per-datasource output as `sets[]`.
- New `ts_cli/tableau/sets.py::build_cohort_tml()` (pure, mirrors `tables.py`/`liveboard.py`'s
  style) — per-type builders producing the exact documented `*.cohort.tml` shape for each
  set type, including the `%null%`→`{Null}` grouping value, `except`→`NE` conditions, the
  Top-N static (`top N` keyword) vs. dynamic (rank + parameter-filter formula) forms, the
  inverted-rank all-except-Top-N form, and a (one-level-deep) multi-formula mixed
  intersect/except composer. Untranslatable forms (dynamic Set Controls, unclassifiable
  shapes) return `None` + the documented log line, never mis-converted.
- Wired into `ts tableau build-model`: emits one `*.cohort.tml` per translatable Set
  alongside the model files, reporting `cohorts_emitted`/`cohorts_deferred`/`cohort_files`
  in the result JSON and echoing the documented per-set log line to stderr.
- BL-131's `sets_detected` warning reworded to point at the new automatic emission instead
  of telling the agent to hand-convert.

### Arbiter

`TableauSetControlUseCases.twbx` (10 native Sets, the arbiter fixture) → 9 cohorts emitted
(8 static + 1 except-of-member-list, all `GROUP_BASED`), 1 deferred (dynamic Set Control, no
fixed members) — `ts tml lint --dir` clean. Non-Set workbook (Ads Commercial Dashboard) → 0
cohorts, output otherwise byte-identical to pre-change (regression-checked). Live
`VALIDATE_ONLY` (se-thoughtspot/APJ_TAB) confirmed a freshly generated cohort's `worksheet:`
binding (no `obj_id` yet — the model doesn't exist until its own first import) fails with
"Worksheet not found" (14500) in a same-batch import, consistent with the pre-existing
obj_id-read-back rule (BL-067 doesn't change this — it's documented in
`ts-convert-from-tableau` SKILL.md Step 5b/6 as an existing post-import patch step).

**Deferred within scope:** deeply-nested set operations (a side of a mixed intersect/except
that is itself another set-op) are flagged for manual review rather than recursively
decomposed — matches the docs' own "flag deeply nested cases prominently" framing, not a
mandatory-recurse rule. Set *actions* (`<action>` elements — a different XML construct from
`<group>` Sets) are unaffected; no workbook in the test corpus exercises one.

---

## BL-069 — Refactor tableau_translate.py into module-per-concern structure

**Source:** codification sweep 2026-06-29 (angle #11b), architectural observation.
**Affects:** `tools/ts-cli/ts_cli/tableau_translate.py`, `tools/ts-cli/ts_cli/model_builder.py`.
**Status:** OPEN (residual only). The module-per-concern split is DONE (shipped 2026-07-02
on feat/tableau-module-split) — see History below. Per the 2026-07-23 triage ("BL-069 (1
residual bug)"), this item now tracks solely one live-reproduced defect: the
**string-concat operand-grammar bug** in `convert_string_concat` (full detail under
Follow-ups > "String-concat operand grammar"). The dead-locals cleanup and quote-blindness
follow-ups remain noted below as pre-existing, non-blocking items — not part of this item's
active scope.
**Park note (2026-07-23):** the Tableau converter is parked; this residual is a known small
open bug, fix on the next Tableau touch.

### History (module split — DONE)

`tableau_translate.py` was 2543 lines in a single module covering: dependency DAG building,
parameter conflict detection, name clash resolution, pre-transforms (5), main translation
pipeline, post-transforms (2), and YAML serialization. `model_builder.py` was 1025 lines
covering TWB parsing, ref resolution, TML assembly, and phased import splitting.

Both files worked well but were hard to navigate and test in isolation. The `ts audit run`
design (BL-065) uses a module-per-angle pattern that keeps each file 200-500 lines — the
same structure would benefit the Tableau pipeline.

### Approach

Split into focused modules without changing external interfaces:
- `tableau_dag.py` — dependency DAG building, topological sort, cycle detection
- `tableau_transforms.py` — pre-transforms and post-transforms
- `tableau_translate.py` — core `translate_single()` + `translate_formulas()` orchestrator (kept as entry point)
- `tableau_parse.py` — TWB/TWBX XML parsing (from `model_builder.py`)
- `model_builder.py` — TML assembly + phased import (remains, but slimmer)

No functional changes — pure structural refactor. Existing tests continue to pass by
importing from the same entry points.

**Target:** 2026-12-31.

### Follow-ups (from the finalization PR)

- Confirmed-dead code candidates left in place per pure-move discipline:
  `parsing._split_on_plus`, `cleanup._BINARY_OPS` (both zero callers repo-wide), plus
  dead locals inside `conditionals.ensure_else_clause` — clean these when that function
  is next touched. — **DONE 2026-07-03** (v0.26.2): both symbols and their
  tableau_translate.py re-exports removed. The dead locals inside
  conditionals.ensure_else_clause remain (function not yet touched).
- Pre-existing `module_health` baseline drift `agents/shared/erd/parser.py::parse_model`
  57→56 (radon recomputation) deliberately NOT committed in this PR — re-baseline
  separately. — **DONE 2026-07-03**: baseline re-keyed; the entry was removed entirely
  (the ERD notes/zoom refactors brought parse_model to cc=15).
- Loop-unification candidate: `tableau/dag.py` holds two deliberately-separate fixpoint
  loops (`build_dependency_dag` matches only `[Calculation_\d+]`; `build_formula_levels`
  matches ALL bracketed refs — see the `# NOTE:` at the top of `build_formula_levels`).
  Unifying them is a behaviour-affecting change; evaluate alongside the
  `build_model_cmd` decomposition follow-up. — **EVALUATED 2026-07-03, won't do**: the
  loops differ in ref universe ([Calculation_\d+] vs all bracketed refs), unresolvable
  handling (level -1 vs default 0), and return shape (per-formula dict vs flat levels
  map). A shared fixpoint helper would need flags for all three — indirection cost
  exceeds the ~20 shared lines. dag.py NOTE updated with the disposition.
- Pre-existing annotation bug carried verbatim: `model_builder.py::filter_unresolvable_formulas`
  return annotation says `tuple[list[str], list[dict]]` but the function returns
  `(kept: list[dict], dropped: list[str])` — docstring is correct, annotation reversed.
  Fix on next touch (PR 2 of the plan touches this area). — **DONE 2026-07-03** (v0.26.2):
  annotation now tuple[list[dict], list[str]].
- Quote-blindness (dated 2026-07-03): the whole map_functions driver — blanket regexes,
  _apply_arg_handler, and validate_output's unmapped-function scan — matches function
  tokens inside string literals. Pre-existing class, probe-proven vs pre-split code; rare
  in real formulas. Fix would need a quote-aware scanner in ts_cli/tableau/parsing.py.
- String-concat operand grammar (dated 2026-07-03, final-review finding):
  convert_string_concat's operand pattern doesn't accept function calls, so e.g.
  LEFT([a],2) + '-' + [b] on a dimension emerges half-converted with a surviving string +
  and zero validation errors — the mapping doc's own worked example STR(ROUND(x,2)) + '%'
  reproduces it. Pre-existing (identical exposure pre-v0.26.0). Candidate fixes: extend
  the operand grammar to function calls, or a validate_output rule flagging + adjacent to
  a quoted string literal.
- Module size (added 2026-07-03, from PR #162's allowlist): `commands/tableau.py`
  remains 1069 lines (TableauClient ~437 lines + six commands) and is carried by the
  one seeded `check_file_size.py` ALLOWLIST entry. Split candidate: move
  `TableauClient` to `ts_cli/tableau/client.py`; remove the allowlist entry when done.
  — **DONE 2026-07-03** (v0.26.4): TableauClient moved to ts_cli/tableau/client.py;
  allowlist entry removed.

---

## BL-070 — Add file-size validator for ts-cli modules

**Source:** architectural review 2026-07-01, repo-audit angle #4 (tools quality).
**Affects:** `tools/validate/`, `tools/ts-cli/ts_cli/`.
**Status:** DONE (2026-07-03) — complexity dimension shipped 2026-07-02 as
`check_module_health.py`; file-size dimension shipped as `check_file_size.py`
(soft-warn 500 / hard-fail 1000; one seeded allowlist entry —
`commands/tableau.py`, whose complexity the BL-069 decomposition already
gated (entry since retired by the TableauClient split, v0.26.4)), wired into
pre-commit + CI.

### Problem

`tableau_translate.py` (2543 lines) and `model_builder.py` (1025 lines) are both
monolithic modules that are hard to navigate, test in isolation, and review. There is
no automated gate preventing new modules from growing to similar sizes. Angle #4 (tools
quality) catches this manually but should be a validator per the two-bucket rule.

### Approach

Add `tools/validate/check_file_size.py`:
- Scan `tools/ts-cli/ts_cli/**/*.py` for files exceeding a line threshold
- Soft-warn at 500 lines, hard-fail at 1000 lines on new/modified files
- Existing files above the threshold get a one-time allowlist entry with a
  cross-reference to BL-069 (the refactor backlog item)
- Wire into `scripts/pre-commit.sh` and `.github/workflows/validate.yml`

Also expand repo-audit angle #4 description in `.claude/rules/repo-audit.md` to
explicitly include module size / modularity as a check dimension.

**Target:** 2026-09-30.

---

## BL-071 — Tableau user-function + user-attribute family → ThoughtSpot RLS variables `Tier 2`

**Source:** task-21 gap documentation, 2026-07-03 (following ts-cli v0.26.0 / #158's
fail-loud validation for this function family). Extended 2026-07-03 (audit finding 13.9,
v0.28.1) to add `USERATTRIBUTE()`/`USERATTRIBUTEINCLUDES()` — the same class of gap,
folded into this item rather than a duplicate backlog entry.
**Affects:** `agents/cli/ts-convert-from-tableau/`, `agents/shared/mappings/tableau/tableau-formula-translation.md`,
`tools/ts-cli/`.
**Status:** PARTIAL.

**Update 2026-07-23 (ts-cli v0.88.0):** shipped the three unambiguous, documented
mappings — `USERNAME()` → `ts_username`, `ISUSERNAME(s)` → `( ts_username = s )`, and
`ISMEMBEROF("group")` → `( ts_groups = 'group' )` (this last one wired into the CLI for
the first time; it previously passed through untranslated and un-rejected). All three
removed from `_UNMAPPED_FUNCTIONS` / documented in `tableau-formula-translation.md` +
`coverage-matrix.md`. **Remaining (deferred, unchanged target):** `FULLNAME()`/`ISFULLNAME(s)`
— no confirmed ThoughtSpot display-name variable; `USERDOMAIN()` — `ts_email_domain` is a
candidate but the domain-only-vs-full-email value shape is unverified; `USERATTRIBUTE(attr)`/
`USERATTRIBUTEINCLUDES(attr, val)` — `ts_var(...)` is only accepted in RLS RULES, not in
Model/Answer formulas today, so no faithful in-formula translation exists. All four stay
rejected at translate time pending the live verification / product research described below.

**Park note (2026-07-23):** deferred pending product confirmation on the remaining four —
no confirmed display-name variable for `FULLNAME`/`ISFULLNAME`; domain-vs-full-email value
shape unverified for `USERDOMAIN`; `ts_var()` is only valid in RLS rules, not Model/Answer
formulas, for `USERATTRIBUTE`/`USERATTRIBUTEINCLUDES`. Decision owed: confirm ThoughtSpot's
display-name variable and formula-editor `ts_var()` support before resuming.

### Problem

Tableau's user-context function family — `USERNAME()`, `FULLNAME()`, `ISUSERNAME(s)`,
`ISFULLNAME(s)`, `USERDOMAIN()` — has no CLI translation. As of ts-cli v0.26.0 (#158)
these are rejected loud at translate time (coverage-matrix.md U7) instead of silently
passing through broken syntax — a real improvement — but the underlying capability gap
remains: workbooks using Tableau's built-in user identity for RLS or personalization have
no automated migration path. This is the direct sibling of `ISMEMBEROF("group")` →
`ts_groups = 'group'` (`tableau-formula-translation.md:1041`, coverage-matrix.md #108,
reclassified 2026-06-28) for group membership — shipped as a **documented skill-level
mapping only**: no CLI translation exists yet, and the CLI passes `ISMEMBEROF(...)`
through untranslated and un-rejected (it is not in `_UNMAPPED_FUNCTIONS`); implementing
one is part of this item's scope. This item is about implementing the translations, not
about the fail-loud behavior (already shipped for the U7 functions).

`USERATTRIBUTE(attr)` / `USERATTRIBUTEINCLUDES(attr, val)` — Tableau's embedded-RLS
custom-attribute functions (read a named attribute passed in from the row-level-security
system, distinct from the built-in identity functions above) — were undocumented and
unhandled entirely until v0.28.1, which added both to `_UNMAPPED_FUNCTIONS`
(coverage-matrix.md U9) for fail-loud rejection. Same underlying gap as U7: no CLI
translation exists yet.

### Approach

- `USERNAME()` → `ts_username` — direct system-variable reference (see the system
  variable table in `thoughtspot-formula-patterns.md:627`)
- `USERDOMAIN()` → likely `ts_email_domain` (`thoughtspot-formula-patterns.md:716`) —
  needs live verification that its value shape matches Tableau's `USERDOMAIN()` semantics
  (domain-only vs. full email address)
- `FULLNAME()` → no direct ThoughtSpot system variable found in `thoughtspot-formula-patterns.md`
  today; needs product research to confirm whether a display-name variable exists or
  whether this stays untranslatable
- `ISUSERNAME(s)` / `ISFULLNAME(s)` → composite comparisons once `USERNAME`/`FULLNAME`
  are resolved (e.g. `ts_username = s`)
- `USERATTRIBUTE(attr)` → **ABAC `ts_var(attr_var)`** referencing an admin-created formula
  variable is the plausible native translation — same JWT user-attribute mechanism as
  `ISMEMBEROF`→`ts_groups`. **Caveat not present for the U7 functions:** per
  `thoughtspot-formula-patterns.md` ("Syntax: Model / Answer Formulas"), `ts_var()` in the
  **formula editor today only supports `ts_user_timezone`** — arbitrary formula variables
  are not yet accepted in Model/Answer formulas, only in **RLS rules** on Table objects
  (`thoughtspot-formula-patterns.md` "Syntax: RLS Rules"). So a Tableau calc using
  `USERATTRIBUTE()` inside a *formula* may have no faithful Model-level translation until
  that formula-editor gap closes; the translation is more likely to land as guidance to
  move the logic into an RLS rule (`attr = ts_var(attr_var)`) than as an inline formula
  rewrite. Confirm current formula-editor support before committing to either path.
- `USERATTRIBUTEINCLUDES(attr, val)` → composite once `USERATTRIBUTE` is resolved (e.g.
  `val in ts_var(attr_var)` for a list-valued attribute, RLS context)
- **Requires live verification** against a ThoughtSpot instance that `ts_username` (and
  any `FULLNAME` candidate) resolves correctly inside a **Model formula context**, not
  just answer-level search — follow the `references/open-items.md` pattern
  (`.claude/rules/api-research.md`) before wiring a translation into `tableau_translate.py`.
  For `USERATTRIBUTE`/`USERATTRIBUTEINCLUDES`, also verify whether `ts_var()` formula-editor
  support has expanded beyond `ts_user_timezone` before assuming a Model-formula path exists.
- Once verified: remove the resolved functions from `_UNMAPPED_FUNCTIONS`, add the mapping
  to `tableau-formula-translation.md`, and move the rows in coverage-matrix.md from
  "Rejected at Translate Time" (U7 / U9) into "Mapped Constructs"

**Target:** 2026-09-30.

---

## BL-072 — Tableau hierarchies and value aliases (+ inverse-trig disposition) `Tier 3`

**Source:** task-21 gap documentation, 2026-07-03.
**Affects:** `agents/cli/ts-convert-from-tableau/`, `agents/shared/mappings/tableau/`,
`tools/ts-cli/`.
**Status:** PARTIAL.

**Update 2026-07-23 (ts-cli v0.88.0):** the inverse-trig sub-item is DONE — `ACOS`/`ASIN`/
`ATAN(x)` → `( acos/asin/atan ( x ) * 3.14159265358979 / 180 )` and `COT(x)` →
`( 1 / tan ( x * 180 / 3.14159265358979 ) )`, all four removed from `_UNMAPPED_FUNCTIONS`
and documented in `tableau-formula-translation.md` + `coverage-matrix.md` (#132/#133).
**Remaining (deferred, unchanged target):** hierarchies (`<drill-paths>`) and value aliases
(`<aliases>`) — the other two sub-items, untouched by this change.

**Park note (2026-07-23):** deferred; needs a design fork decision before implementation —
Model column-ordering vs. AI-context emission for hierarchies, and CASE-formula vs.
column-level display mapping for value aliases (see Approach below for both options).

### Problem

Two TWB XML constructs are near-universal in production Tableau workbooks and have no
ThoughtSpot TML equivalent today: `<drill-paths>` (hierarchies — a curated dimension
drill order, e.g. Region → State → City) and `<aliases>` (dimension value display
remapping, e.g. source value `"US"` displayed as `"United States"`). Both are currently
omitted and logged (coverage-matrix.md L24/L25) with no automated workaround.

Folded into this item as a smaller, related sub-item: `ACOS`/`ASIN`/`ATAN`/`COT`
(coverage-matrix.md #32) are silent pass-throughs today — neither translated nor caught
by the fail-loud validator. `ACOS`/`ASIN`/`ATAN` share the same radian/degree composite
family as the already-shipped `SIN`/`COS`/`TAN` translation, so it is a small, largely
independent fix worth bundling here rather than opening a third backlog item for it.

### Approach

- **Hierarchies:** parse `<drill-paths>` from the TWB. ThoughtSpot has no declared-hierarchy
  TML construct, so investigate two non-exclusive directions: (a) **Model column ordering**
  — arrange the referenced dimensions in the Model's `columns[]` in the hierarchy's order
  as a soft signal for ThoughtSpot's own ad-hoc drill-down; (b) **AI-context emission** —
  surface the hierarchy as a business-term / data-model-instruction hint (via
  `ts-object-model-coach`'s schema) so Spotter understands the intended drill relationship
  even without a hard TML construct
- **Value aliases:** parse `<aliases>` from the TWB; translate to a `CASE`-style
  `if/else if` formula mapping each source value to its display value, added as a derived
  `ATTRIBUTE` column. Also investigate whether a lighter-weight column-level display-value
  mapping exists in TML as an alternative to a formula
- **Inverse trig (sub-item):** implement `ACOS`/`ASIN`/`ATAN` as a `* pi/180` composite —
  same shape as the shipped `SIN`/`COS`/`TAN` handling. Give `COT` an explicit disposition:
  either reject it at translate time (add to `_UNMAPPED_FUNCTIONS`, joining U1–U7) or emit
  a `1/tan(...)` composite. Independent of the hierarchy/alias work and can ship first.
  **Update 2026-07-03:** fail-loud shipped in ts-cli v0.26.5 (all four in
  `_UNMAPPED_FUNCTIONS`, coverage-matrix U8). **Update 2026-07-23 (ts-cli v0.88.0):
  DONE** — `* pi/180` composites shipped for `ACOS`/`ASIN`/`ATAN` (derived from the
  already-shipped SIN/COS/TAN radians-to-degrees convention rather than a fresh live
  check, per the brief for this change), and `COT` ships as a `1/tan(...)` composite.
  All four removed from `_UNMAPPED_FUNCTIONS`.
- All three sub-items are parser/codegen work in the Tableau translation pipeline (module
  home per BL-069's refactor), not skill-prompt changes — follow the codification pattern
  (repo-audit angle #11) rather than adding LLM judgment steps

**Target:** 2026-12-31.

---

## BL-073 — ts-audit / ts-cli round-trip batching (perf angle 14) `Tier 2`

**Source:** 2026-07-03 full audit, findings 14.1 / 14.3 / 14.4.
**Affects:** `tools/ts-cli/ts_cli/audit/context.py`, `commands/tables.py`.
**Status:** DONE (14.1/14.3/14.4 all closed).

### Problem

1. ~~**14.1:** `build_context` exports ALL model TMLs in ONE unbatched call.~~ **DONE** —
   model TML export now batched at 50 with `raise_for_status=False` and per-batch error
   tolerance, matching the answer export pattern. (ts-cli v0.76.0)
2. ~~**14.3:** `ts tables create` costs up to 2N round-trips (per-table singleton import +
   per-table GUID search)~~ **DONE** — tables now imported in batches of 50 with `PARTIAL`
   policy; JDBC failures retried individually; pass 2 (RLS) also batched. (ts-cli v0.79.0)
3. ~~**14.4:** the audit AI-instructions fetch records failed fetches as `{}`, so errors read
   as "missing AI instructions" in A-angle findings.~~ **DONE** — failed fetches now
   recorded in `AuditContext.warnings` (not as `{}`); A3 skips models whose fetch failed
   instead of flagging false positives; A5 scoring unaffected (falls back to TML-embedded
   instructions). (ts-cli v0.76.0)

### Approach

All three findings closed: model export batched (v0.76.0), AI-instructions
false positives fixed (v0.76.0), tables create batched (v0.78.0).

---

## BL-074 — Propagate prompt-batching relaxation to remaining interactive skills

**Source:** 2026-07-03 full audit, finding 14.5.
**Affects:** ts-audit, ts-dependency-manager, ts-object-answer-promote, ts-object-model-coach,
ts-object-model-erd, ts-profile-tableau, both ts-recipe-* skills, `ts-profile-thoughtspot:10`,
`ts-profile-databricks:10`, `ts-variable-timezone:11` (strict serial-prompt wording; per-skill
judgment needed for the partly-sequential credential flows).
**Status:** DONE (PR #293, 2026-07-22).

All 13 remaining skills updated: 9 non-credential skills received the concise
dependent/independent wording; 4 credential-flow skills (`ts-profile-*`) received a
tailored version acknowledging their mostly-sequential nature while allowing independent
inputs (name + URL + auth method) to be batched. Each skill received a PATCH bump.

---

## BL-075 — Dependency currency residuals: lock file + Python 3.14 cap

**Source:** 2026-07-03 full audit, findings 16.2 (residual) / 16.3. The `typer<1` cap and
`dev` extra shipped in PR #173.
**Affects:** `tools/ts-cli/pyproject.toml`, install docs.
**Status:** DONE — Python 3.14 cap lifted (BL-106, ts-cli v0.46.0); lock file deferred.

The Python 3.14 cap was lifted to `<3.15` and 3.14 added to the CI pytest matrix (BL-106).
The lock file question (whether to check in `uv.lock` for reproducible installs) is
deliberately deferred — `uv tool install --force` re-resolves fresh, but `pip-audit` in CI
(BL-033) catches CVE-affected resolutions, which was the motivating risk.

---

## BL-076 — Smoke-test backfills: ts-object-answer-promote + ts-convert-from-tableau `Tier 2`

**Source:** 2026-07-03 full audit, finding 6.3 — both `check_smoke_tests.py` ALLOWLIST
exemptions were undated two-bucket violations (comments now reference this item).
**Affects:** `tools/smoke-tests/`, `tools/validate/check_smoke_tests.py` ALLOWLIST.
**Status:** OPEN.

ts-convert-from-tableau is the largest conversion skill (1,709 lines of translation unit
tests) with zero end-to-end TWB→TML→import smoke and no .twb fixture tracked — add a small
fixture workbook + end-to-end smoke. ts-object-answer-promote needs its deferred smoke
backfilled. Remove both ALLOWLIST entries when the smokes land.

**Park note (2026-07-23):** deferred; the Tableau half needs a committed `.twb` fixture plus
an E2E import test written against it before this can close.

**Target:** 2026-09-30.

---

## BL-077 — Known-bad fixture self-tests for the remaining validators

**Source:** 2026-07-03 full audit, finding 6.5.
**Affects:** `tools/validate/tests/`.
**Status:** DONE (PR #296 wave 1, PR #297 wave 2 — 2026-07-22).

All 18 validators now have known-bad fixture self-tests in
`test_known_bad_fixtures.py`. Wave 1 (PR #296): `check_skill_naming`,
`check_runtime_coverage`, `check_skill_versions`. Wave 2 (PR #297):
`check_coverage_matrix`, `check_file_size`, `check_sv_yaml`,
`check_version_sync`, `check_yaml`, `check_formula_catalog`,
`check_consistency` (git-initialised tmp repo), `check_secrets`
(staged PEM header). Git-dependent validators use `_init_git()` helper to
create a real repo in `tmp_path`.

---

## BL-078 — check_open_items: scoped hard mode in CI

**Source:** 2026-07-03 full audit, finding 7.2.
**Affects:** `tools/validate/check_open_items.py`, `.github/workflows/validate.yml`.
**Status:** DONE (PR #294, 2026-07-22).

Added `--base` flag to `check_open_items.py`: when provided, only open-items.md files
changed in the PR diff (`git diff <base>...HEAD`) are checked in hard mode (exit nonzero).
Pre-existing unresolved items in unchanged files are WARN-only. CI wired as a new
"Open-items gate (PR only)" step in `validate.yml`, analogous to the changelog gate.
Pre-commit still uses `--warn` (unchanged).

---

## BL-079 — Recipe codification: UDF SQL as files + `ts snowflake exec`

**Source:** 2026-07-03 full audit finding 11.2 + codification review rows 14/22.
**Affects:** both ts-recipe-formula-* skills, `tools/ts-cli/`.
**Status:** ✅ DONE in PR #229 (ts-cli v0.48.0) — flip on merge. Delivered: `ts snowflake
exec -f/-q --sf-profile --var` (reuses `load.py`'s `_connect_python`, both python/cli
methods); UDF DDL moved to `references/business-day-udfs.sql` /
`references/duration-udfs.sql`; both SKILL.md Steps 1/3/4 rewired (no inline
`snowflake.connector` connect block, no retyped SQL); both smoke tests deploy via the
real command against the single-source templates; **11.3 two-bucket exit satisfied** —
`check_patterns` rule 7 flags a cloned `snowflake.connector.connect(` in any SKILL.md
(`ts-profile-snowflake` allowlisted, references/ carved out). Pure helpers
(`parse_var_assignment`/`substitute_sql_vars`/`json_safe_value`) unit-tested; CoCo
mirrors won't-sync (CLI-only) — acknowledged in SYNC-DEBT.md. **Live-verified on
se-thoughtspot (`AGENT_SKILLS.PUBLIC`)**: both smoke tests green end-to-end — business-days
via the **python/key_pair** profile, hms-display via the **cli** profile (both methods).
The live run found+fixed a serialization bug: `_exec_python` returned `datetime`/`Decimal`
that crashed `json.dumps` (`SELECT CURRENT_TIMESTAMP()` etc.) → added `json_safe_value`
coercer. **Blocks:** should land before the next ts-recipe-* skill (BL-037 plans six).

The recipes' UDF SQL — the entire point of the skills — exists only as markdown fences the
LLM transcribes into Python strings each run (a `-1` vs `-2` DATEDIFF slip is syntactically
valid and silently wrong), and the ~40-line Snowflake connect/execute block is cloned
between both skills and has already drifted from `load.py:_connect_python()` (key-path
handling). Move the SQL to `references/*.sql` templates and add `ts snowflake exec -f
<file.sql> --sf-profile <name> [--var k=v]` reusing the load.py connector; point both
recipes (and their smoke tests, deduped in PR #174) at it.

**Note (2026-07-11 full audit finding 11.3, two-bucket exit):** when `ts snowflake
exec` lands, add a `check_patterns` rule for the cloned `snowflake.connector` connect
block (in SKILL.md; references/ carve-out) in the same PR — the permanent check that
keeps the ~30-line clone from re-drifting.

**Target:** 2026-08-31.

---

## BL-080 — `ts metadata permissions` + answer-promote permission pre-flight `Tier 3`

**Source:** 2026-07-03 full audit, finding 5.3.
**Affects:** `tools/ts-cli/`, ts-object-answer-promote.
**Status:** OPEN.

answer-promote's deferred permission pre-flight (open-item #2 recorded a 500 on
`/security/metadata/fetch`) is closable: dependency-manager's references row 12 already
verified `/security/metadata/fetch-permissions` works — the knowledge never crossed skills.
Confirm the spec via `get-rest-api-reference(apiName:"fetchPermissionsOnMetadata")`, add
`ts metadata permissions`, wire the pre-flight, and update open-item #2.

**Target:** 2026-09-30.

---

## BL-081 — `ts data search` for ts-audit Phase 2 (usage-based checks) `Tier 3`

**Source:** 2026-07-03 full audit, finding 5.4 (the capability gap had no dated item —
two-bucket violation; the stale OI numbering was fixed in PR #168).
**Affects:** `tools/ts-cli/`, ts-audit.
**Status:** OPEN.

ts-audit Phase 2 (dead-column detection, unused-object identification, low-usage flagging)
requires querying the TS: BI Server system model — a `ts data search` command (open items
#9–#12 in ts-audit's references). Spec via MCP first, then live-verify.

**Target:** 2026-10-31.

---

## BL-082 — Drop the `source ~/.zshenv &&` prefix repo-wide (after Linux keyring verify)

**Source:** 2026-07-03 full audit, finding 11.5.
**Affects:** 18 SKILL.md / shared files (~134 occurrences), `agents/cli/CLAUDE.md`.
**Status:** DONE (PR #298, 2026-07-22).

Dropped `source ~/.zshenv && ` prefix from 134 bash command examples across 18 files.
`client.py` falls back to the OS credential store via `keyring`, making the prefix
redundant — the `ts` CLI resolves credentials from Keychain/Credential Manager/Secret
Service without needing env vars sourced. Standalone `source ~/.zshenv` instructions
(after credential setup) and changelog entries preserved. Linux degradation:
`_get_credential()` catches `keyring` import/call failures and raises a clear
`SystemExit` with remediation instructions — no silent failure path.

---

## BL-083 — Codify ts-dependency-manager backup / mutation / verify / rollback

**Source:** 2026-07-03 codification review rows 11–13 (angle 11).
**Affects:** ts-dependency-manager, `tools/ts-cli/ts_cli/dependency/` module.
**Status:** ✅ DONE — PR1 (#192, 2026-07-08, ts-cli v0.39.0) + PR2 (#194, 2026-07-08,
ts-cli v0.41.0, skill v1.4.0) both merged to main. PR2 was live-verified on
se-thoughtspot (open-item #23): green end-to-end (dependent-fix → source-remove →
one-pass rollback), and the live run found+fixed two bugs (open-items #24 aliased-column
strip via column_id/expr, #25 root-first rollback order). Only follow-up left is
open-item #22 (surface chart-axis-role in `ts metadata report` for Step 6).

~900 of the SKILL.md's lines are inline pseudocode for the skill's headline safety
promises: TML backup manifest (Step 7), the remove/repoint mutation engine across 5 object
types (Step 9, with known gaps in open-items #2/#13), import/verify/drift orchestration
(including the live-tested "TS misreports import status" edge case, currently prose-only),
and full rollback (Step 11) — all re-derived by the LLM each run. The walk +
impact report (Steps 4–5) are already deterministic via `ts metadata report`.

**PR1 (shipped, non-destructive substrate):** new `ts_cli/dependency/` module —
`mutate.py` (pure REMOVE/REPOINT TML transforms, extracted from Step 9, 2 latent bugs
fixed), `backup.py` (manifest/ordering helpers), `commands/dependency.py` exposing
`ts dependency mutate | backup | rollback`. 127 unit tests; the old
`tests/test_dependency_helpers.py` (which duplicated the inline functions) is replaced by
the real module. SKILL.md Step 7 → `ts dependency backup`, Step 11 → `ts dependency
rollback`.

**PR2 (SHIPPED — #194, live-verified on se-thoughtspot):**
`ts dependency apply-change` — the Step 9 drift-check → delete → dependent-fix →
source → set-delete loop, wiring `apply_remove`/`apply_repoint` (mutate.py) and the new
deterministic decision helpers in `ts_cli/dependency/apply.py` (drift, obj_id derivation,
the import/verify outcome matrix, post-import verification, 9c ordering, the set-delete
consumer guard). SKILL.md Step 9 dropped from ~1,060 lines of inline pseudocode to a
plan-JSON build + one command call. **Latent-bug fix:** corrected the execution order to
**source LAST** (deletes → dependents → source → sets) — the old section bodies ran
source-first, which error 14544 rejects while a dependent still references the column.
**Chart-axis-role decision** (`dep["action"]/REMOVE_CHART`) codified as a self-contained
pure function (`apply.chart_role_for_answer`/`classify_liveboard_viz_roles`) consumed by
apply-change (default CONVERT_TO_TABLE, plan-overridable) — surfacing it in `ts metadata
report` for Step 6 is deferred to **open-item #22** (build_report doesn't wire
per-dependent chart classification today, so it's a larger schema-contract change).
Open-items #2/#13/#15/#16 still bite here. Live verification of the corrected ordering +
drift/obj_id/set-guard paths — **done, open-item #23 VERIFIED**.

**Target:** ✅ Delivered 2026-07-08 (both PRs merged, live-verified).

---

## BL-084 — `ts profiles add/update/remove`: codify the profile substrate `Tier 2`

**Source:** 2026-07-03 codification review row 18.
**Affects:** all four ts-profile-* skills, `tools/ts-cli/ts_cli/commands/profiles.py`.
**Status:** OPEN.

Slug/env-var derivation, keychain command templating, profile-JSON CRUD, and `~/.zshenv`
upsert are freehand LLM work duplicated across the four profile skills, with one
demonstrated drift bug (ts-profile-tableau's slug rule lost "collapse multiples, strip
ends" vs its three siblings). The interactive credential flow stays agentic per
security.md — the credential VALUE never passes through the CLI conversation; the substrate
(everything except the secret) becomes `ts profiles add/update/remove` + `ts profiles
sync-env`. Also adopt `ts profiles list --json` in the 4 skills that hand-parse
`~/.claude/*-profiles.json`.

**Note (2026-07-11 full audit finding 11.2):** the adoption pass should also fold in a
shared select-and-verify authenticate reference in `agents/shared/` — from-looker's
Step 1 dropped profile discovery entirely (bare `ts auth whoami`, no multi-profile
menu) and from-databricks-mv inlines ~15 lines of profile-JSON Python duplicated from
ts-profile-databricks. Cross-reference BL-079/11.3 above.

**Target:** 2026-10-31.

---

## BL-086 — model-coach: codify the deterministic substrate under the judgment layer `Tier 3`

**Source:** 2026-07-03 codification review rows 16/17/19/20.
**Affects:** ts-object-model-coach, `tools/ts-cli/`.
**Status:** OPEN.

The coaching judgment (what synonym/instruction to write) stays agentic; the arithmetic
feeding it should not be re-executed as inline Python each run: prose mining (regex NP
extraction + Jaccard-stem scoring with hard thresholds — prose-mining-rules.md:43-116),
the cross-model corpus scan (TTL cache + parallel export, documented to scale to 1,000
models), synonym-conflict validation (complete working Python at SKILL.md ~:788-834),
candidate scoring, and the Step 8b/8c TML patch/merge + enum/char-limit validation (the
step the Critical TML invariants exist to protect). Candidates: `ts model mine-language`,
`ts model validate-synonyms`, `ts model patch-model` (or `ts tml patch-model`),
`ts model cross-consistency-scan`.

**Target:** 2026-11-30.

---

## BL-087 — Shared `ts spotql classify-columns` (dedupe divergent keyword lists)

**Source:** 2026-07-03 codification review row 24.
**Affects:** ts-object-model-spotql-query, ts-object-answer-promote, `tools/ts-cli/`.
**Status:** DONE 2026-07-03 (ts-cli v0.31.0) — `ts spotql classify-columns` shipped
(`ts_cli/spotql_ops.py` + `commands/spotql.py`); both skills adopt it (spotql-query
v1.3.0, answer-promote v1.3.0).

Column classification is duplicated between the two skills with DIFFERENT keyword lists
(spotql SKILL.md ~:137-146 vs promote ~:700-722) — live drift, and exactly the ts-cli.md
"two skills duplicate the same logic" trigger. One `ts spotql classify-columns --model
{guid}` command; both skills adopt it.

**Target:** 2026-09-30.

---

## BL-088 — Audit mode doesn't classify Tableau Sets `Tier 3`

**Source:** 2026-07-04 live audit of `CPG+Merch Promotion Performance.twbx`.
**Affects:** ts-convert-from-tableau (Audit mode, Steps A2–A4), `tools/ts-cli/` (`ts tableau parse` / `classify-formulas`).
**Status:** DONE (ts-cli v0.87.0, `feat/tableau-set-codify`) — shipped alongside BL-067
(same "two paths, one detector" reuse this item asked for: no set-detection logic was
duplicated).

The audit-mode coverage report (Step A4) has a **Tableau Sets** section, and migrate mode
(Step 5b) has extensive set→cohort translation (static/Top-N/condition/computed sets). But
`ts tableau parse` and `ts tableau classify-formulas` only extract and classify **calculated
fields and parameters** — they do **not** emit top-level `<group>` set data. So an audit of a
workbook that uses sets silently omits them: the A4 "Tableau Sets" row can't be populated from
the CLI, and the coverage % reflects only calc fields. This is the audit analogue of the
audit/migrate divergence BL-fixed for formulas (#181) — the audit under-reports scope for
set-heavy workbooks.

### What shipped

- `ts tableau parse` now extracts `sets[]` per datasource (BL-067's `extract_sets()` — the
  SAME classification migrate mode's `build_cohort_tml()` consumes).
- `ts_cli/tableau/sets.py::classify_sets()` labels each parsed Set with the audit tier
  Step A4's "Tableau Sets" table needs: `column_set` (static + member-intersect →
  `GROUP_BASED`), `query_set` (Top-N/condition/all-except-Top-N/mixed → `ADVANCED`), or
  `deferred` (dynamic Set Control, or an intersect that computes zero common members —
  structurally can't emit a cohort either).
- `classify_workbook()` (`ts tableau classify-formulas`) now returns `sets[]` +
  `sets_tier_counts` per datasource, plus a summed top-level `sets_tier_counts` — the exact
  numbers `references/audit-mode-report.md`'s "Tableau Sets" table needs, sourced from JSON
  like every other tier count (never hand-tallied). SKILL.md Step A3/A4 updated to cite it.

**Arbiter:** `TableauSetControlUseCases.twbx` → `sets_tier_counts: {column_set: 9,
query_set: 0, deferred: 1}` (matches the BL-067 arbiter's emitted/deferred split exactly,
since it's the same classification).

## BL-091 — Tableau: verify multi-table model grain semantics against data `Tier 4`

**Source:** 2026-07-05 live CPG migration (schema-only build; no data verification).
**Affects:** ts-convert-from-tableau, generated multi-table models.
**Status:** OPEN.

A hand-built multi-table model joins fact tables at different grains (chasm/fan-out). Formulas
imported structurally but may not return Tableau-equivalent **numbers**. Concrete open case:
the CPG **tentpole** category pre/LY formulas (`CPG Category Sales Pre/LY`) reference a
`PERIOD_TYPE` that `tentpole_promotion_master` does not have — they were qualified cross-table
to `tentpole_product_metrics.PERIOD_TYPE`, changing the grain. Needs a data-level check
(compare a few aggregates against Tableau) once warehouse access is available. This is the
migrate-mode analogue of audit angle #15 (conversion fidelity, parked).

**Park note (2026-07-23):** DATA-BLOCKED, not a code gap — needs Tableau's own numbers for
the cited CPG tentpole case before this can be verified either way.

**Target:** when data access is available.

---

## BL-093 — Tableau: substitute or flag Tableau parameters embedded in Custom SQL

**Source:** 2026-07-06 PR #188, seussrecs.twb (`WHERE rec_date >= <[Parameters].[Parameter 1]>`).
**Affects:** ts-convert-from-tableau, `build-model` (`_generate_flow` / SQL View emission).
**Status:** DONE (ts-cli v0.85.0, `fix/tableau-quick-closeout` commit b036302) — new
`substitute_sql_view_parameters()` (`ts_cli/tableau/params.py`) scans each SQL View's
`sql_query` for `<[Parameters].[Name]>` tokens: a token naming a parsed parameter gets that
parameter's default value substituted in (+ a `validation_warnings` note the value is now
static); an unresolved token gets a `NEEDS-REVIEW` warning instead and is left in place —
never silently passed through to import. `references/coverage-matrix.md` #131 added.

Tableau lets a Custom SQL body reference a workbook parameter inline as `<[Parameters].[Name]>`.
That token is not valid warehouse SQL, so the emitted `sql_view.sql_query` will fail at import
until it is resolved. Options: substitute the parameter's default value into the SQL, or emit a
NEEDS-REVIEW flag pointing at the token. Currently the SQL is passed through verbatim.

**Target:** next `build-model` iteration.

---

## BL-094 — Tableau: capture joins BETWEEN SQL Views (multi-query Custom SQL datasources) `Tier 2`

**Source:** 2026-07-06 PR #188, validated against `tableau/community-tableau-server-insights` ts_users.twb (6 joined Custom SQL Queries).
**Affects:** ts-convert-from-tableau, `build-model` (`_extract_joins` / model join wiring).
**Status:** OPEN.

`_extract_joins` reads only `relation[@type='table']` children, so a datasource that JOINS
several Custom SQL Queries (each now a SQL View) loses the joins between them — the model gets
the SQL Views as unconnected `model_tables[]` with no `joins`. Needs join extraction over
`type='text'` relation children plus cardinality inference (deterministic only via a data probe;
CTE-grain heuristic otherwise). This is the multi-query analogue of the single-view case shipped
in #188 and overlaps the deferred "logical-relationship → join cardinality" gap.

**Park note (2026-07-23):** deferred; needs a cardinality-inference design decision (data-probe
vs. CTE-grain heuristic, per this item's own text) before implementation can start.

**Target:** next multi-query build-model work; needed for FedEx VEDR (2 joined Custom SQL sources).

---

## BL-095 — ts-cli: `connections add-tables` omits required `authenticationType`; instance `updateConnectionV2` 500s `Tier 2`

**Source:** 2026-07-08 BL-063 PR1 Task 5 live run against se-thoughtspot (diagnostics recorded in `docs/audit/2026-07-08-dbx-window-claim-matrix.md`, Task-5 BLOCKED subsections, incl. incident GUIDs for a support ticket).
**Affects:** `tools/ts-cli/ts_cli/commands/connections.py::add_tables()`; any skill relying on `ts connections add-tables`.
**Status:** (1) DONE (ts-cli v0.75.0); (2) OPEN — re-verify on a newer build.

Two distinct findings:

1. ~~**ts-cli bug (fix in ts-cli):** `add_tables()` never sends `authenticationType` on
   `POST /api/rest/2.0/connections/{id}/update`.~~ **DONE** — `add_tables()` now auto-detects
   `authenticationType` from the `connection/search` response and includes it in the update
   payload. A `--auth-type` CLI option provides an explicit override when auto-detection
   fails. 22 unit tests cover extraction and payload shape. (ts-cli v0.75.0)
2. **Probable build defect (verify on a newer build / support ticket):** even with a
   corrected payload, `updateConnectionV2` returned a uniform generic 500
   (`code: 10000`, `debug: "[null]"`) across 4 payload variants and 2 independently
   healthy connections (PAT and SERVICE_ACCOUNT) on the se-thoughtspot build of
   2026-07-08. Re-verify after the fix in (1) lands and on a newer cloud build before
   assuming the CLI fix alone resolves it; incident GUIDs are in the claim matrix.

**Target:** (2) re-check on next se-thoughtspot build update.

---

## BL-096 — se-thoughtspot build: SpotQL `generate-sql`/`fetch-data` endpoints return an empty-body 500 `Tier 4`

**Source:** 2026-07-09 BL-063 PR1 Task 5 live TS-side number-match run against se-thoughtspot (diagnostics recorded in `docs/audit/2026-07-08-dbx-window-claim-matrix.md`, "TS-side number-match results (Task 5, live 2026-07-09)" execution-path note).
**Affects:** `ts-object-model-spotql-query` skill; `ts spotql fetch-data` (and any command depending on it).
**Status:** OPEN.

The SpotQL endpoints (`/callosum/v1/v2/data/spotql/generate-sql` / `fetch-data`) return
a bare, empty-body HTTP 500 for any payload on this se-thoughtspot build — including an
empty request body, which a live handler would reject as a structured 400 — so `ts
spotql fetch-data` was unusable (its output normalises to `status: UNKNOWN`). Task 5
worked around this by fetching data via the stable v2 `POST /api/rest/2.0/searchdata`
endpoint instead (spec confirmed via `get-rest-api-reference(apiName: "searchData")`),
through a scratch script reusing `ts_cli.client.ThoughtSpotClient` for auth — the
documented open-items-style exception in `.claude/rules/ts-cli.md`, since ts-cli has no
`searchdata` command yet. `ts spotql classify-columns --model` is unaffected (it
classifies from exported TML, with no server-side SpotQL dependency).

**Target:** re-verify on the next se-thoughtspot build; if the 500 persists, add a
`searchdata`-based fallback to ts-cli's SpotQL commands. No date set — revisit next
time SpotQL commands are exercised live.

---

## BL-097 — ts-cli: `_stdin_has_piped_content()` hangs forever on an open non-TTY stdin

**Source:** 2026-07-09 BL-063 PR1 Task 5 live run against se-thoughtspot — `ts tml import --file` invoked from a script context (diagnostics recorded in `docs/audit/2026-07-08-dbx-window-claim-matrix.md`, "TS-side number-match results (Task 5, live 2026-07-09)" import-iterations note).
**Affects:** `tools/ts-cli/ts_cli/commands/tml.py` (`_stdin_has_piped_content()`); any skill or script invoking `ts tml import`/`ts tml lint` from a non-interactive shell with an open stdin.
**Status:** DONE — ts-cli v0.47.1 (2026-07-12).

`_stdin_has_piped_content()` blocked on `sys.stdin.read()` whenever stdin was open but
not a TTY and nothing had actually been piped in (e.g. a background shell context) — it
hung forever instead of falling through to the `--file`/`--dir` path. The workaround
used during Task 5 was `< /dev/null`.

**Fix (v0.47.1):** the read is now `select()`-guarded with a zero timeout — it reads only
when the fd reports readable (data → content, EOF / `< /dev/null` → empty, regular-file
redirect → readable) and returns False without reading on an idle open pipe. Falls back
to the prior blocking read where `select` can't poll the handle (e.g. a Windows
non-socket handle), preserving prior behaviour there. Covered by
`TestStdinHasPipedContentNoHang` in `tests/test_tml_file_dir_input.py`, including a
real-pipe hang guard that fails against the pre-fix code.

---

## BL-098 — Databricks trailing/leading window translation: date-interval vs row-positional frame semantics diverge on sparse data (E1/C1) `Tier 4`

**Source:** 2026-07-09 BL-063 PR1.5 semantic deep-dive, claim IDs E1 (Trailing-window frame
semantics) and the frame-semantics half of C1's split verdict (Global `filter:` × window
ordering). Full evidence: `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`.
**Affects:** `ts-convert-from-databricks-mv` and `ts-convert-to-databricks-mv` skills (both
directions' `trailing`/`leading` `range:` mapping); the planned BL-063 PR2
(`ts databricks parse-mv`) and PR3 (`ts databricks translate-formulas`) substrate.
**Status:** OPEN — items 1 and 2 are DONE (shipped in BL-063 PR2 and PR3
respectively, 2026-07-09/10); item 3 (a live probe on a DENSE non-day-grain fixture)
is the entry's sole remaining scope.

Databricks `trailing N day`/`leading N day` window frames are date-interval framed — the
frame boundary is a calendar-date interval intersected with surviving rows. ThoughtSpot's
`moving_sum`/`moving_average` (the documented translation target) is row-positional — it
counts N preceding/following surviving *rows*, not calendar days. On dense, gapless daily
data the two framings are indistinguishable, which is why PR 1's C1/C3 CONFIRMED verdicts
(obtained on a dense fixture) did not catch this. On sparse/gapped data — a category with
missing days, or any filter that removes rows unevenly — the two platforms compute
different trailing/leading sums: live-verified on cat Z's gapped fixture, days 5/8, DBX
20/50 vs. TS 30/80. No `moving_sum` argument shape reconciles the two; this is a genuine
platform divergence, not a formula bug, and it is now caveated at every trailing/leading
mapping site (both directions, both SKILL.md files, the schema doc, all three mapping
files, and `ts-databricks-properties.md`).

### Approach

1. **DONE — PR #200** (`ts-cli` v0.42.0, BL-063 PR2). `ts databricks parse-mv`
   (`ts_cli/databricks/mv_window.py`) sets `density_check_required: true` on every
   `trailing`/`leading`/`window` `range:` measure and emits a stderr WARNING; the
   flag is surfaced by `ts-convert-from-databricks-mv` SKILL.md Step 5.
2. **DONE — PR #202** (`ts-cli` v0.43.0, BL-063 PR3). `ts databricks translate-formulas`
   (`ts_cli/databricks/mv_window_translate.py`) attaches a `sparse_data_risk` annotation
   to every trailing/leading translation plus a stderr WARNING, rather than asserting
   equivalence unconditionally. Carried through into `ts databricks build-model`'s
   `window_measures[]` summary field (BL-063 PR4, ts-cli v0.44.0, 2026-07-10).
3. **OPEN — remaining scope.** A future live probe should test DENSE non-day units
   (e.g. month grain) to confirm the date-interval/row-positional distinction — and its
   practical impact — generalizes beyond daily grain.

**2026-07-11 status:** BL-063 Phase 2 (PR4 `ts databricks build-model` #204, PR5
naming/import-guard follow-ups #206) shipped and closed without touching item 3.
`_window_moving` in `ts_cli/databricks/mv_window_translate.py` (:159-163) still hard-fails
non-day `rng["unit"]` trailing/leading windows with `"only day grain trailing/leading
windows are live-verified (BL-098 item 3 / C8); non-day units need a live probe first"` —
confirming no month/quarter/year-grain live probe has been run. Item 3 remains OPEN;
unblocking it needs a live Databricks fixture at a dense non-day grain, opportunistic
alongside the next Databricks live-verification pass.

**Target:** item 3 — no fixed calendar date; opportunistic, alongside the next Databricks
live-verification pass.

---

## BL-099 — Databricks/TML import-response parsing + naming guards — PR4 final-review follow-ups

**Source:** 2026-07-10 BL-063 PR4 final whole-branch review.
**Affects:** `ts_cli/commands/tml.py:478`, `ts_cli/commands/dependency.py:468`,
`ts_cli/commands/tables.py:187` (flat-GUID sites); `ts_cli/databricks/mv_build_model.py`
(`_check_no_duplicate_display_names`); `ts_cli/databricks/mv_parse.py`
(`duplicate_name` guard).
**Status:** SHIPPED (BL-063 PR5, ts-cli v0.45.0, 2026-07-10).

1. **SHIPPED** — the flat import-response shape (`resp[0].response.header.id_guid`,
   live-verified 2026-07-10) was parsed only by `extract_imported_guid`
   (`ts_cli/tableau/build_model.py`). The nested-only sites `commands/tml.py:478`,
   `commands/dependency.py:468`, and `commands/tables.py:187` still read only
   `response.object[0].header.id_guid` and silently fell back to slower/degraded
   paths (name search, "no GUID" branches) when a caller hit the flat shape.
   Fixed by relocating the helper to `ts_cli/tml_common.py` and importing
   `extract_imported_guid` from there at all three sites — `tml.py`, `dependency.py`,
   and `tables.py` now share the one flat-shape-aware parser.
2. **SHIPPED** — `_check_no_duplicate_formula_names` (`mv_build_model.py`) covered
   `formulas[]` only — it did not extend to all `columns[]` display names. Two
   dimensions with identical `display_name` emit duplicate column names that
   `ts tml lint`'s I8 (unique `column_id`) can't catch, because `column_id` and
   display `name` are different fields. Fixed by `_check_no_duplicate_display_names`
   in `ts_cli/databricks/mv_build_model.py`, which checks display-title collisions
   across every `columns[]` entry (dimensions and measures alike).
3. **SHIPPED** — `parse-mv` had no name-uniqueness guard: duplicate MV identifiers
   across `dimensions` + `measures` would double-emit via the `mv_name`-keyed lookups
   in `build_columns_and_formulas` (`physical_by_mv`/`formula_by_mv`, last-write-wins).
   Theoretical only — Databricks rejects duplicate dimension/measure names at
   `CREATE VIEW ... WITH METRICS` time — but defensive against hand-edited or
   partially-applied YAML. Fixed by a `duplicate_name` entry appended to
   `unsupported[]` in `ts_cli/databricks/mv_parse.py` when a dimension/measure
   name repeats.

**Target:** fold into BL-063 PR 5, or take as a standalone ts-cli fix — no fixed
calendar date. **Closed** — all three items shipped in BL-063 PR5 (ts-cli v0.45.0).

## BL-100 — Bring the remaining converters up to the Databricks-from standard `Tier 1`

**Filed:** 2026-07-11 (post BL-063 Phase 2 close-out).
**Source:** user-raised after reviewing what `agents/shared/mappings/` is for now that
`ts databricks parse-mv / translate-formulas / build-model` codified the from-Databricks
direction.
**Status:** OPEN — deliberately sequenced AFTER the next full repo audit, whose angle 11
(agentic → deterministic) and external sweep will inventory/scope the exact mechanical
steps per converter and refresh the currency baseline this work builds on.

The from-Databricks direction now sets the bar: (a) **deterministic codification** — the
mechanical parse → translate → assemble-TML pipeline runs as pure ts-cli code with golden
fixtures, the LLM handling only the judgment residue (`unsupported[]`/`skipped[]`, review
steps); (b) **empirical semantic verification** — claim-matrix deep-dives with live
fixture number-matching on both platforms (BL-063 PR1/PR1.5 pattern), findings recorded
in the mapping docs with citation-rich currency anchors; (c) **runtime vendoring** where
a runtime can't call ts-cli (Genie `build_mv_lib` concatenation pattern).

Per-converter gap against that bar:

| Converter | Codification | Empirical verification | Notes |
|---|---|---|---|
| ts-convert-from-snowflake-sv | **None** (only `ts snowflake diff`/`lint-ddl`) | Partial — 2026-07-10 SE-cluster formula-composition/TML-import batch, but no per-construct claim matrix | Biggest gap; BL-063's original title named Snowflake too. Mirror the Databricks 3-command pipeline (`parse-sv` / `translate-formulas` / `build-model`). CoCo mirror keeps the doc-driven path (no shell) — docs stay authoritative for it. |
| ts-convert-to-snowflake-sv | None | Inaugural anchor only (2026-06, never swept) | DDL emission is highly mechanical — strong codification candidate. |
| ts-convert-to-databricks-mv | None | Window emission tables live-verified (PR1) | MV YAML emission is mechanical; reuse `mv_*` module vocabulary in reverse. |
| ts-convert-from-tableau | **Done** (full `ts tableau` pipeline) | Doc-driven sweeps only — no fixture number-match has ever run | Only the fidelity leg is missing; needs live Tableau Server access (often unavailable — see feedback memory). Scope as opportunistic. |
| ts-convert-from-looker | **None** | Not yet swept | (audit finding 5.2) 1,845 lines run lkml parsing, field resolution, measure translation, and TML emission agentically — the same mechanical shape codified for Tableau/Databricks. Cheapest parse leg of all converters (mature `lkml` parser on PyPI); build-model can reuse existing machinery. Model on the BL-063 phases (`ts looker parse` / `translate-formulas` / `build-model`). Shipped 6 days after the codification review, so it was absent from the original table. |

Also in scope: normalize currency-anchor style (the Databricks anchors have outgrown
"context" into changelog territory; the anchor format is `platform — YYYY-MM (context)` —
long-form evidence belongs in `docs/audit/` claim matrices, referenced from the anchor).

**Relationship to angle 15 (conversion fidelity, PARKED):** the empirical-verification
leg of this item is a per-converter unparking of angle 15 — coordinate rather than
duplicate.

**Target:** scope after the next full repo audit (angle 11 output feeds the plan);
Snowflake-from pipeline is the natural first program (BL-063-style phased PRs).

**Two axes of "the standard" (2026-07-24 clarification).** "Databricks-from standard" here
means the **codification / empirical-verification** axis only (a → c above). It is NOT the
whole bar. A second, orthogonal axis — **token/runtime efficiency** — was pioneered on the
*Tableau* converter, not Databricks: the context-budget rule (BL-127), one-pass CLI guidance
+ batch `--dir` operations (BL-129), and shared prompt/discovery extraction (BL-122). So no
single converter is uniformly "highest": Databricks-from leads on codification, Tableau leads
on efficiency. When bringing a converter "up to standard," treat it as the **union** — codify
the mechanical pipeline (this item) AND apply BL-122/127/129 — and cross-check both axes per
converter rather than assuming DBX-from alone is the target.

---

## BL-101 — Surface chart-axis-role classification in `ts metadata report` (schema 1.0 contract change) `Tier 3`

**Filed:** 2026-07-11.
**Source:** BL-083 PR2 scope decision + `agents/cli/ts-dependency-manager/references/open-items.md`
open-item #22.
**Affects:** `tools/ts-cli/ts_cli/report/__init__.py` (`build_report`, `DependentSignals`),
`ts-dependency-manager` Step 6.
**Status:** OPEN — no fixed target date.

`ts dependency apply-change` already classifies per-viz chart-axis roles itself
(`ts_cli.dependency.apply.chart_role_for_answer` / `classify_liveboard_viz_roles`),
defaulting every x/y-axis-affected visualization to the always-safe `CONVERT_TO_TABLE`
with a per-viz plan override — so the destructive mutation path is deterministic and
safe today. What is missing is surfacing that same classification in `ts metadata
report`'s output so Step 6 can present the `CONVERT_TO_TABLE`-vs-`REMOVE` decision
interactively from the report itself, rather than requiring a separate TML read.

This was deferred out of BL-083 PR2 rather than folded in because `build_report` does
not wire per-dependent chart classification at all today — `DependentSignals.chart_axis_use`
exists as a field but is never populated (`build_report` feeds only the aggregate from the
RLS/join/AI-surface probes). Emitting a per-viz `action` touches the report's
`schema_version` 1.0 contract, which is a larger, deliberate change rather than something
to bundle into the apply-change orchestrator.

**Scope:** extend `build_report`'s per-dependent output to populate
`DependentSignals.chart_axis_use` per liveboard visualization (reusing the same
`chart_role_for_answer` / `classify_liveboard_viz_roles` pure functions
`apply.py` already computes), emit a per-viz role in the report JSON, and have
Step 6 consume it directly instead of a separate TML read. Consider bumping the report
schema version if the new field changes the existing contract's shape expectations.

**Target:** no fixed date — natural next step whenever `ts_cli/report/__init__.py` is
next touched, or as part of a future ts-dependency-manager UX pass.

---

## BL-102 — Databricks MV `parameters:` parse + emit support (live-verify on Runtime 18.2) `Tier 3`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 13.2.
**Affects:** `tools/ts-cli/ts_cli/databricks/mv_parse.py` (known-key set, line 190),
`tools/ts-cli/ts_cli/databricks/mv_build_model.py` (line 66 comment); `ts-convert-from-databricks-mv`.
**Status:** OPEN.

`ts databricks parse-mv` (mv_parse.py:190 known-key set) rejects the GA `parameters:`
block as `unknown_key`; mv_build_model.py:66's comment "MVs have no parameters" is now
wrong. Decide TS Parameter ↔ MV parameter translation both directions and live-verify
on an 18.2 SQL warehouse. Doc corrections already shipped in the 2026-07-11 mapping
batch (PR #213); this is the parser/emitter half. Companion to finding 13.1.

**Target:** no fixed date — next Databricks-from touch, paired with the 13.1 companion work.

---

## BL-103 — Retest `searchConnection` with explicit `authentication_type` for OAuth hierarchy `Tier 4`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 13.3.
**Affects:** `tools/ts-cli/ts_cli/commands/connections.py` (`_fetch_connection_v2`); `.claude/rules/ts-cli.md`.
**Status:** OPEN.

`.claude/rules/ts-cli.md` claims OAuth/PKCE connections return an empty warehouse
hierarchy as a product limitation, but the `searchConnection` spec exposes an
`authentication_type` field (defaults to `SERVICE_ACCOUNT`), and `_fetch_connection_v2`
never passes it. Live-test passing the matching type; if the hierarchy is retrievable,
fix `_fetch_connection_v2` and soften the "do not rely on connection introspection" rule.

**Target:** no fixed date — next live-instance session with an OAuth/PKCE connection available.

---

## BL-104 — Evaluate Databricks BI compatibility mode (GA 18.0+) as an alt MV architecture `Tier 4`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 13.9.
**Affects:** `agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md:106`; `ts-convert-from-databricks-mv`.
**Status:** OPEN.

BI compatibility mode lets BI tools query MV measures without `MEASURE()`, opening up
registering the MV itself over an Embrace connection instead of building over source
tables. Evaluate connector support and semi-additive/window behaviour. Nothing is
broken today — the mode is opt-in and the repo builds over source tables. Also add a
one-line caveat at ts-from-databricks-rules.md:106.

**Target:** no fixed date — evaluation item, not a defect.

---

## BL-105 — Bump `requests` floor to `>=2.33.0` on the next ts-cli version bump

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 16.1.
**Affects:** `tools/ts-cli/pyproject.toml`.
**Status:** DONE (2026-07-11) — requests floor bumped to >=2.33.0 + ts-cli 0.45.2 (feat/audit-backlog-quickwins)

The current `requests>=2.32.4` floor permits requests 2.32.5 (GHSA-gc5v-m9x4-r6x2,
fixed in 2.33.0) and transitive urllib3 2.6.3 (PYSEC-2026-141/-142, fixed in 2.7.0).
Real environments resolve clean today; a floor-constrained resolution would silently
reintroduce the CVEs. urllib3 is covered transitively — no separate pin needed.

**Target:** bundle with the next ts-cli version bump.

---

## BL-106 — Lift the CPython 3.14 cap; plan the 3.11 floor bump `Tier 4`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 16.2.
**Affects:** `tools/ts-cli/pyproject.toml` (`requires-python`).
**Status:** PARTIAL — (a) DONE (2026-07-11): cap lifted to `>=3.10,<3.15` (ts-cli v0.46.0);
3.14 added to the CI `pytest-matrix` job so the suite is exercised on it every PR (couples with
BL-107 — `pip install -e` refuses interpreters outside `requires-python`, so the cap had to lift
for 3.14 to be testable). **Remaining:** (b) the `>=3.11` floor bump after 3.10 EOL (2026-10) — still OPEN.

`requires-python = ">=3.10,<3.14"` blocked CPython 3.14 (GA Oct 2025). The cap is now lifted and
3.14 is CI-verified; the floor bump to `>=3.11` remains deferred.

**Target:** ✅ cap lifted; revisit the 3.11 floor bump after 2026-10.

---

## BL-107 — Add a small CI Python matrix (3.10, 3.13) on the pytest step

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 16.4.
**Affects:** `.github/workflows/validate.yml` (pytest step).
**Status:** DONE (2026-07-11) — added a dedicated `pytest-matrix` job running the unit/validator
tests on `["3.10", "3.11", "3.13", "3.14"]` (3.12 already covered by `validate`). Validators/linters
stay single-version in `validate`, per the item's scope.

CI tested a single Python version (3.12) while `pyproject.toml` claimed support for a wider range.
The new matrix job fills in the rest of `requires-python` without duplicating the validator suite.

**Target:** ✅ done.

---

## BL-108 — SHA-pin GitHub Actions (`checkout@v4`, `setup-python@v5`)

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 16.5.
**Affects:** `.github/workflows/validate.yml`.
**Status:** DONE (2026-07-11) — checkout@v4→v4.3.1 SHA + setup-python@v5→v5.6.0 SHA pinned in validate.yml (feat/audit-backlog-quickwins)

Actions are pinned by mutable tags — the tj-actions incident class. Only two
first-party actions are in use, so risk is modest. SHA-pin both with a version-tag
comment; batch with the next workflow edit rather than open a standalone PR.

**Target:** bundle with the next workflow edit (e.g. alongside BL-107).

---

## BL-109 — Retire `agents/claude/references/direct-api-auth.md` + remove its two dead reference rows

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 1.2.
**Affects:** `agents/claude/references/direct-api-auth.md`; `agents/cli/ts-convert-from-snowflake-sv/SKILL.md:33`;
`agents/cli/ts-convert-to-snowflake-sv/SKILL.md:28`.
**Status:** DONE (2026-07-11) — `direct-api-auth.md` deleted (its only consumers were the two
dead reference rows); both rows removed; ts-convert-from-snowflake-sv → 1.16.1, ts-convert-to-snowflake-sv
→ 1.3.2 (PATCH). Also removed the now-stale "NOT in scope" paragraph in `check_orphan_references.py`
that tracked this item. No CoCo references existed, so no mirror bump / stage-sync.

The doc described a curl + `/tmp/ts_token.txt` fallback that `ts-cli.md` and `security.md` prohibit;
its only consumers were two dead reference-table rows with no corresponding step logic.

**Target:** ✅ done.

---

## BL-110 — Consolidate the hardcoded runtime skill-dir list into a shared `tools/validate/_dirs.py`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 4.4.
**Affects:** files under `tools/validate/`.
**Status:** DONE — 2026-07-12.

18 validators independently hardcoded `('agents/cli', 'agents/claude',
'agents/coco-snowsight')`; a directory rename meant ~18 edits, and a missed one
silently reported PASS. The three dirs are stable today — this is drift insurance,
the same pattern as the existing ALLOWLIST/NAME_ALIASES consolidation.

**Resolution (2026-07-12):** new `tools/validate/_dirs.py` is the single source of
truth — `ALL_RUNTIMES` / `CLI_RUNTIMES` (short names), `ALL_RUNTIME_PATHS` /
`CLI_RUNTIME_PATHS` (agents-prefixed), the `CLI`/`CLAUDE`/`COCO` scalars, and a
`runtime_globs()` helper. Three semantic groupings were preserved: all-three-runtime
enumerations, the CLI family (CoCo deliberately excluded — no `ts` CLI in Snowsight),
and CoCo-alone. 14 validators now import from it; every runtime *enumeration* is
consolidated (single-runtime literals for runtime-specific checks left in place, as
they are not the drift surface). A `test_dirs.py` guard asserts every listed runtime
dir exists on disk, so a rename fails loudly here instead of no-opping a downstream
validator. Verified output-neutral by diffing all ~28 validators before/after: the
only diffs are `check_runtime_coverage --verbose` column order (claude-first →
canonical cli-first) and `check_smoke_tests`' self-referential ALLOWLIST line numbers
(shifted by the added import) — both cosmetic, no logic change. Sibling import
resolves in pre-commit, CI, and the test conftest.

---

## BL-111 — `--connection <name>` filter on `ts metadata search` (optionally `ts tables discover`) `Tier 3`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 11.1.
**Affects:** `tools/ts-cli/ts_cli/commands/metadata.py`; `ts-convert-from-snowflake-sv` Step 6A,
`ts-convert-from-databricks-mv` Step 8A, `ts-convert-from-tableau`, `ts-audit`.
**Status:** PARTIAL — (a) DONE (2026-07-11, ts-cli v0.47.0): `ts metadata search --connection <name>`
(alias `-c`) added, a client-side case-insensitive filter on `metadata_header.dataSourceName` via the
pure, unit-tested `filter_by_connection` helper (11 tests). Available for converters to adopt.
**Remaining:** (b) the optional `ts tables discover` command returning the found/missing/column-gap
map directly, and rewiring the converter Step-6A/8A prose to call `--connection` instead of describing
the manual filter — both deferred to the next converter that needs them.

Connection-scoped table discovery is duplicated near-verbatim across 3+ converters
(from-snowflake-sv Step 6A, from-databricks-mv Step 8A, from-tableau, ts-audit prose):
metadata search → client-side `dataSourceName` filter → stripe disambiguation →
column-gap map. Meets ts-cli.md's "2+ skills duplicate the same raw API call" trigger.

**Target:** ✅ (a) shipped; (b) + converter rewiring scope alongside the next converter that needs it.

---

## BL-112 — Rewire `smoke_ts_audit.py` onto `ts audit run`/`report` + dedup the PII pattern list `Tier 3`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 6.2.
**Affects:** `tools/smoke-tests/smoke_ts_audit.py`; `tools/ts-cli/ts_cli/audit/checks_security.py` (`_PII_PATTERNS`).
**Status:** OPEN.

The smoke test predates the ts_cli audit engine: it never invokes `ts audit
run`/`report`, and its Step 8 duplicates a local `PII_PATTERNS` list ("mirrors the
skill logic") that can silently diverge from `_PII_PATTERNS` in checks_security.py.
Point the smoke test at `ts audit run` live; import or delete the duplicated list.
Parallels the 6.1 dependency-manager smoke-test rewire shipped in PR #212.

**Target:** no fixed date — natural next touch of the audit smoke test.

---

## BL-113 — Add a live provisioning step to `smoke_ts_load_source_data.py` `Tier 4`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 6.4.
**Affects:** `tools/smoke-tests/smoke_ts_load_source_data.py`.
**Status:** OPEN.

The smoke test covers only the offline half — `ts load snowflake` provisioning
(CREATE TABLE + PUT + COPY) has mocked unit coverage but no live smoke test. The
runner already has `--sf-profile` plumbing in place to support one.

**Target:** no fixed date — next live-instance session with a Snowflake profile available.

---

## BL-114 — Document `export_with_column_aliases` when it stabilises or a skill needs it `Tier 4`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 13.11.
**Affects:** `agents/shared/schemas/thoughtspot-model-tml.md`; ts-convert-* mappings.
**Status:** OPEN.

`export_with_column_aliases` (Beta, 10.13.0.cl) confirms Models carry a column-alias
feature distinct from `properties.synonyms`; `thoughtspot-model-tml.md` has no
coverage today and ts-convert-* mappings only target synonyms. This is a newly
possible mapping target once the flag reaches GA — document it then, or sooner if a
skill needs it before GA.

**Target:** no fixed date — triggered by GA or by a skill requirement, whichever comes first.

---

## BL-115 — Write a smoke test for `ts-convert-from-looker` `Tier 2`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 6.3.
**Affects:** `tools/smoke-tests/smoke_ts_convert_from_looker.py` (new);
`tools/validate/check_smoke_tests.py:50` (ALLOWLIST entry).
**Status:** OPEN.

from-looker (shipped 2026-07-09) has an undated `ALLOWLIST` exemption in
check_smoke_tests.py; this backlog item is the dated exit that exemption's comment
should reference. Author `tools/smoke-tests/smoke_ts_convert_from_looker.py` on the
first live LookML verification (needs a LookML fixture project).

**Target:** first live-verification pass against a real or fixture Looker project.

---

## BL-116 — Live destructive run of the rewired `smoke_ts_dependency_manager.py` `Tier 3`

**Filed:** 2026-07-11.
**Source:** 2026-07-11 full audit finding 6.1; rewrite shipped in PR #212 — this item
is the deferred live-verification follow-up.
**Affects:** `tools/smoke-tests/smoke_ts_dependency_manager.py`.
**Status:** OPEN.

The smoke test was rewired onto `ts dependency backup/apply-change/rollback` with the
destructive `apply-change` leg gated behind `--run-apply-change`. The safe legs
(backup + `rollback --only updates`) and the destructive leg under the flag both need
a live-instance run against a disposable model — reserved for a user-authorized
destructive gate.

**Target:** next live-instance session with an expendable ThoughtSpot model and explicit user authorization for the destructive leg.

---

## BL-117 — Migrate the shared `ts-tml-import-gate.md` off the stdin-import wrapper

**Filed:** 2026-07-11
**Source:** 2026-07-11 full audit finding 5.1 (remainder; surfaced during the PR-batch-3 migration).
**Status:** DONE (2026-07-11) — (a) `ts-tml-import-gate.md` §1 lint wrapper rewritten to `ts tml lint
--file`/`--dir`, and §3 now shows the canonical `ts tml import --file`/`--dir --policy PARTIAL` form;
(b) `check_patterns` Check 6 extended to scan tracked `agents/shared/**/*.md` (2 new regression tests —
shared doc IS flagged, generated `agents/databricks/shared/` copy is NOT, being outside the glob);
(c) post-merge `./scripts/stage-sync.sh` REQUIRED (shared file → CoCo stage); the `agents/databricks/shared/`
copy regenerates from source on `deploy.sh`. Referencing SKILL.md files are byte-unchanged (they link,
not inline) so no skill version bumps.

The audit-5.1 fix migrated `ts-convert-from-looker` and `ts-object-model-coach` off the superseded
`python3 -c "…json.dumps([…])" | ts tml import/lint` stdin wrapper to `--file`/`--dir`, and added
`check_patterns` Check 6 to block re-entry — but Check 6 scans only `SKILL.md` files (mirroring
Check 5's carve-out). The shared reference `agents/shared/schemas/ts-tml-import-gate.md` (line ~27)
and its generated copy under `agents/databricks/shared/` **still teach the old wrapper** as the
canonical import-gate procedure, and two CLI-runtime converters (`ts-convert-from-databricks-mv`,
`ts-convert-from-snowflake-sv`) defer to it — both run ts-cli ≥ v0.27.0 and would execute the taught
wrapper literally. So 5.1 is only partially closed repo-wide.

**Work:** (a) rewrite the `ts-tml-import-gate.md` procedure to use `ts tml lint --file`/`--dir` /
`ts tml import --file`/`--dir`; (b) extend Check 6 (or a sibling) to also scan
`agents/shared/schemas/*.md` so the shared doc can't regress; (c) run `./scripts/stage-sync.sh` (shared
file changed → CoCo stage) and confirm the `agents/databricks/shared/` copy regenerates on deploy.
This carries the CLAUDE.md change-impact fan-out, which is why it was scoped out of the batch-3
validators PR rather than bundled.

**Target:** next converter/codification pass (fold into BL-100 sequencing if convenient).

---

## BL-119 — Write a smoke test for `ts-convert-from-sisense` `Tier 4`

**Filed:** 2026-07-17.
**Source:** new wip skill `ts-convert-from-sisense` (Sisense offline-bundle → ThoughtSpot).
**Affects:** `tools/smoke-tests/smoke_ts_convert_from_sisense.py` (new);
`tools/validate/check_smoke_tests.py` (ALLOWLIST entry).
**Status:** OPEN.

`ts-convert-from-sisense` (wip) has an `ALLOWLIST` exemption in check_smoke_tests.py; this
backlog item is the dated exit that exemption's comment references. Author
`tools/smoke-tests/smoke_ts_convert_from_sisense.py` once a captured Sisense bundle fixture
(`{dashboard, widgets, datamodel}`) exists and the shared liveboard emitter
(`ts_cli.tableau.liveboard.build_from_spec`, open-item #2) has landed so the full
`parse → build-model → build-liveboard` chain can be exercised end-to-end.

**Target:** first live end-to-end verification against a captured Sisense bundle (open-item #1).
## BL-120 — Live end-to-end verification for `ts-convert-from-qlik` `Tier 2`

**Filed:** 2026-07-21.
**Source:** initial `ts-convert-from-qlik` release (PR #254).
**Affects:** `agents/cli/ts-convert-from-qlik/references/open-items.md` (#1, #2, #6).
**Status:** OPEN.

ts-convert-from-qlik shipped code-backed (`ts qlik`, 58 unit tests + an **offline smoke test**
`tools/smoke-tests/smoke_ts_convert_from_qlik.py` — no longer on the ALLOWLIST). Still needs
verification against real infrastructure: (a) live import on a ThoughtSpot cluster —
parse→build-model→import→build-liveboard→import + a numbers/double-count check (open-items #1);
(b) chart-type enum validity on the target build (open-items #2); (c) the live Qlik Cloud/Engine
extraction paths against a real tenant/engine (open-items #6) — currently mocked-only. Also
recover table joins/associations from engine-artifacts mode (open-items #3).

**Target:** first live-verification pass against a real Qlik app + ThoughtSpot instance.

## BL-121 — ts-cli code dedup: profile loading, JSON helpers, bare-except, stdin import

**Filed:** 2026-07-22.
**Source:** 2026-07-22 full audit, findings 4.1–4.5.
**Status:** DONE (PR #290).

Five ts-cli code-quality items from the audit — all resolved:
- **4.1** Profile loading → delegates to `profile_ops.get_profile` (with `path` override
  for testability) across `load.py` and `_common.py`
- **4.2** JSON file-load → extracted to `io_helpers.load_json_file`; thin wrappers in
  snowflake.py, databricks.py, tableau.py, sisense.py
- **4.3** Bare `except Exception` → narrowed to `except (json.JSONDecodeError, ValueError)`
  in snowflake.py and databricks.py
- **4.4** Smoke tests `_common.py` → delegates to `profile_ops.get_profile`; dead
  `sf_connect_python` removed (42 lines)
- **4.5** stdin import → extracted to `io_helpers.run_tml_import`; databricks.py and
  snowflake.py use thin wrappers

## BL-122 — Cross-skill prompt/discovery extraction (connection, tables, import errors) `Tier 2`

**Filed:** 2026-07-22.
**Source:** 2026-07-22 full audit, findings 11.3–11.5.
**Status:** 11.3 PARTIAL, 11.4 OPEN, 11.5 DONE.

Three near-identical prose blocks duplicated across 4+ conversion skills:
- **11.3** Connection selection prompt (N/F/L + E/C) — extracted to
  `agents/shared/references/connection-select.md`; from-snowflake-sv and
  from-databricks-mv updated to link. from-tableau not yet updated (Tableau
  changes tracked separately). model-aggregates doesn't use this prompt
  (confirmed — no connection selection in that skill)
- **11.4** Table discovery pattern (C/I scope + metadata search + column verification +
  Table Plan summary) — duplicated with identical logic, already patched skill-by-skill
  once (2026-06-16). See also BL-111 (`--connection` filter on `ts metadata search`)
- **11.5** ~~Post-import verification + import error table~~ — DONE (BL-063 phase 1c,
  PR #288: extracted to `ts-tml-import-gate.md` §4/§5)
- **11.6 (added 2026-07-23)** Embed exact CLI command+flag examples in each step. In the 2026-07-23
  Tableau benchmark, agents made **5–7 `ts … --help` discovery calls per run** (both ours AND #252)
  because steps described commands in prose without exact flags. PR #319 embedded a canonical
  copy-pasteable invocation per step in `ts-convert-from-tableau` → **0 `--help` probes**, ~25% fewer
  tokens on the Ads run. Apply to every conversion skill — highest-ROI slice of this item.

**Target:** extract shared references when next editing the conversion skills.

## BL-123 — Product currency gaps from 2026-07-22 audit `Tier 2`

**Filed:** 2026-07-22.
**Source:** 2026-07-22 full audit, findings 13.1, 13.5, 13.7–13.10.
**Status:** Non-Tableau items DONE (13.1, 13.5, 13.7, 13.8 — PRs #304/#305, 2026-07-23). Remaining: 13.9 + 13.10 (Tableau — tracked separately).

Platform-specific documentation gaps identified by the product-currency specialists:
- **13.1** ~~`PARTIAL_OBJECT` import policy undocumented in authoritative schema docs~~ DONE (added to ts-tml-import-gate.md §3, 2026-07-23)
- **13.5** ~~`cortex_search_service` is an object, not a string in `snowflake-schema.md`~~ DONE (fixed type + sub-fields, 2026-07-23)
- **13.7** ~~Missing `median()` mapping for Databricks formula translation~~ DONE (ts-cli v0.74.0, 2026-07-23)
- **13.8** ~~Wildcard field expressions (`source.*`, `EXCEPT`) undocumented in MV schema~~ DONE (added to databricks-metric-view.md v1.1, 2026-07-23)
- **13.9** 6 Tableau date functions missing from mapping (ISOYEAR/ISOQUARTER/ISOWEEK/
  ISOWEEKDAY → reject; standalone QUARTER/WEEK → map)
- **13.10** 7 Tableau window/rank variants missing (WINDOW_CORR/COVAR/COVARP/STDEVP/
  VAR/VARP + RANK_PERCENTILE → reject list)

**Target:** address per-platform as part of the weekly external sweep.

## BL-124 — Orphaned proposal doc and quality gates enforcement

**Filed:** 2026-07-22.
**Source:** 2026-07-22 full audit, findings 1.5, 7.3.
**Status:** DONE (PR #289, 2026-07-22).

- **1.5** Proposal doc now has a status header; remaining code action tracked as BL-125
- **7.3** Enforcement model section added to `docs/quality-gates.md` (via generator)

---

## BL-126 — Migrate SpotQL smoke test from `champ-staging` to `se-thoughtspot` profile `Tier 2`

**Filed:** 2026-07-22.
**Source:** Pre-push smoke failure — `champ-staging` token expired; SE profile uses
username/password (more resilient).
**Affects:** `tools/smoke-tests/smoke_ts_object_model_spotql_query.py`,
`tools/smoke-tests/smoke-config.local.json`
**Status:** OPEN — blocked until `se-thoughtspot` instance is reachable.

### Problem

The SpotQL smoke test (`smoke_ts_object_model_spotql_query.py`) hard-references
`champ-staging` in its docstring and `smoke-config.local.json` overrides the default
profile to `champ-staging` for this skill. That profile uses token auth which expires
and requires manual refresh. The `se-thoughtspot` profile uses username/password auth
which is more resilient to expiry.

### Proposed fix

1. Find or create a SpotQL-capable Model on `se-thoughtspot` (must be backed by
   Snowflake, not Falcon — SpotQL requires an external warehouse).
2. Write a simple SpotQL query for it.
3. Update `smoke-config.local.json` to remove the `champ-staging` override (the
   `default_ts_profile` is already `se-thoughtspot`).
4. Update the docstring in `smoke_ts_object_model_spotql_query.py`.

**Blocked on:** `se-thoughtspot` instance being reachable (returning 404 as of
2026-07-22).

---

## BL-127 — Roll out the "context-budget" rule to all conversion skills `Tier 2`

**Filed:** 2026-07-23.
**Source:** 2026-07-23 ours-vs-#252 Tableau benchmark (generalizable finding).
**Affects:** `ts-convert-from-looker`, `ts-convert-from-snowflake-sv`, `ts-convert-from-databricks-mv`,
`ts-convert-from-sisense` SKILL.md.
**Status:** OPEN.

Reading large tool `--out` JSON (a real `parse` output is tens of thousands of tokens) into agent context
is a recurring, avoidable token sink. `ts-convert-from-tableau` (and powerbi/qlik) carry an explicit
"**Context budget — never Read the big `--out` files; use the stdout summary / `json.load()` from disk /
targeted `offset`+`limit`**" rule; **looker (1,834-line skill), snowflake-sv (1,341), databricks-mv (997),
and sisense lack it**. In benchmark runs the rule kept generated-JSON Read calls at 0.

**Approach:** port the tableau/powerbi wording (name each skill's real `--out` artifacts) into a prominent
section near the top of each missing skill. Verify by an agent run keeping `read_calls_on_generated_json` at 0.
**Target:** next converter edit.

---

## BL-128 — Skill-size audit: extract reference-heavy detail from the heavy converter skills `Tier 3`

**Filed:** 2026-07-23.
**Source:** 2026-07-23 benchmark; PR #314 (tableau 4,436 → ~2,900 lines).
**Affects:** `ts-convert-from-looker` (1,834), `ts-convert-from-snowflake-sv` (1,341),
`ts-convert-from-databricks-mv` (997) SKILL.md.
**Status:** OPEN.

SKILL.md size is a per-run token tax (the file is read every run, sometimes in multiple slices). PR #314
cut tableau ~34% by moving reference-heavy detail (templates, rule tables, report formats) into
`references/*.md` while keeping the procedural spine + links inline — **no logic change**. powerbi/qlik/sisense
(~100 lines each, defer to shared mappings) are the lean model. Apply the same extraction to the three heavy
skills above.

**Approach:** per skill, move bulk templates/tables/examples to `references/`, keep every step heading +
procedural instructions inline, leave a link; verify all step headings survive + link checker clean.
**Target:** opportunistic, per skill.

---

## BL-129 — One-pass CLI guidance + batch operations across converters `Tier 2`

**Filed:** 2026-07-23.
**Source:** 2026-07-23 benchmark; PR #319 (`verify --dir` + one-pass build-model guidance).
**Affects:** all `ts-convert-*` SKILL.md + their `ts <src> verify`/build CLIs.
**Status:** OPEN (tableau done in #319).

Two generalizable token/latency wins found on Tableau, likely present in the other converters:
1. **No unnecessary per-object loops in skill prose.** `ts tableau build-model` already emits ALL datasources'
   models+tables in one call, but the SKILL.md prose ("one model per datasource") led agents to loop it per
   datasource (3× build + 3× lint + 3× verify on a 3-datasource workbook). Fixed by guiding a single pass.
   Audit looker/snowflake-sv/databricks-mv/qlik/sisense/powerbi skill prose for the same per-object looping.
2. **Batch verify.** Added `ts tableau verify --dir` (verify every model in a dir in one call) so verify isn't
   looped per model. Check whether sibling converters' `verify`/validate commands need the same `--dir`.
3. **Embed exact CLI command+flags per step** (see BL-122) — removed 5–7 `--help` probes/run.

**Verify:** an agent run on a multi-object workbook uses ~1 build + 1 lint + 1 verify (not N+N+N), same output.
**Target:** next converter edit.

---

## BL-130 — Canonical data-type audit across all converters (DATE_TIME vs DATETIME etc.) `Tier 2`

**Filed:** 2026-07-23.
**Source:** 2026-07-23 benchmark; PR #315 (databricks-mv emitted invalid `DATETIME`).
**Affects:** every converter that emits Table TML `db_column_properties.data_type`.
**Status:** databricks-mv fixed (#315); OTHERS UNAUDITED.

`databricks/mv_tml.py` mapped `timestamp`→`DATETIME`, which ThoughtSpot **rejects** at import
(live-confirmed error: "Data type DATETIME is not valid"); the canonical value is `DATE_TIME`
(`agents/shared/schemas/thoughtspot-table-tml.md`). Snowflake's map was already correct. Audit every
converter's type map against the schema's canonical values — a wrong type is a silent import-breaker that
local lint does NOT catch.

**Approach:** grep each converter's type-map module against the Table-TML schema type table; add a unit test
per converter asserting each source type → a schema-valid TS type. Consider a shared validator.
**Target:** 2026-09-30.

---

## BL-131 — Tableau Sets: warn when an automated/Stage-1 run skips the Phase-2 set→cohort step

**Filed:** 2026-07-23. **Corrected:** 2026-07-23 (original framing was wrong — see below).
**Source:** 2026-07-23 benchmark (Set Control workbook), Stage-1 non-interactive run.
**Affects:** `ts-convert-from-tableau` SKILL.md (Step 3/5b) — surfacing only.
**Status:** DONE (ts-cli v0.85.0, `fix/tableau-quick-closeout` commit 45db8e9) — new
`count_native_sets()` (`ts_cli/tableau/twb.py`) counts datasource-scoped `<group>` Set elements
(excluding Tableau's internal `crossjoin` combined-field mechanism used for multi-field dashboard
Actions/Tooltips, and the Pivot-field `<group>` shape — neither is a user Set). `build-model` now
prints a stderr WARNING and adds `sets_detected` to each datasource's result JSON when count > 0.
Live-confirmed: `TableauSetControlUseCases.twbx` → `sets_detected: 10` + warning; a no-Set
workbook → 0, no warning; Ads Commercial Dashboard (14 crossjoin groups, 0 real Sets) → 0,
correctly not warned.

**Correction:** Tableau Sets → ThoughtSpot cohorts **is already supported** (shipped under BL-009) — static
sets → `GROUP_BASED` column-set cohort (incl. `%null%`, `except` member-lists, formula-anchored); Top-N/Bottom-N
→ query sets; condition-based/intersect/all-except-Top-N → query sets; one `*.cohort.tml` per set. See
coverage-matrix rows 73–79 and SKILL.md "Tableau Sets → ThoughtSpot column sets (Phase 2a/2b/2c)". The only
deferred forms are dynamic *set controls* with no fixed members (→ Liveboard filter) and *set actions* (no TS
equivalent) — already documented. The benchmark's "Sets not converted" observation was a **scope artifact**:
Set→cohort is an agent-guided Phase-2a/2b/2c hand-assembly flow, NOT part of `build-model`'s GENERATE pass, so a
non-interactive Stage-1 (Tables+Models-only) run legitimately skips it.

**Real (small) residual:** in an automated / Stage-1 / non-interactive run, a workbook's `<group>` Set elements
are skipped **silently** — no warning that the Phase-2 set step is still owed. Nudge only:
1. `ts tableau parse` already surfaces enough to detect `<group>` Sets — have `build-model` (or the skill's
   Step 3 summary) **emit a WARNING** listing detected Sets and pointing to the Phase-2a/2b/2c step, so they're
   not silently dropped in a pipeline run.
2. Optionally add the Set count to the migration report's coverage summary.
**Target:** opportunistic. (Distinct from BL-024 row-offset table-calcs.)

---

## BL-132 — from-Databricks build-model: promote duplicate `column_id` to a formula (I8/I5 parity) — DONE `Tier 3`

**Status:** DONE — PR #332 (2026-07-24). Shared helper `formula_common.promote_duplicate_column_ids`
keeps the first occurrence of a `column_id` and re-expresses later duplicates as `fn ( [TABLE::col] )`
aggregation formulas (SUM/AVERAGE/MIN/MAX/COUNT/MEDIAN/STDDEV/VARIANCE + I5's COUNT_DISTINCT →
`unique count`); wired into **both** `mv_build_model` and `sv_build_model`. Investigation found the
premise below was inaccurate — the from-Snowflake path had the identical bug (nothing to "mirror"),
so the fix was written new and applied to both directions. A duplicate that is not a re-expressible
aggregate is left in place so `ts tml lint` I8 still surfaces it. ts-cli v0.92.0.

**Filed:** 2026-07-24.
**Source:** surfaced during the Databricks role-play round-trip verification (PR #330) — a
TS→MV→TS round-trip of the SUPPORT_CASE model, where the model has both a raw fact/measure
column and an aggregate metric over the *same* physical column.
**Affects:** `ts databricks build-model` (`mv_build_model.build_columns_and_formulas`).

**Symptom:** `ts tml lint` I8 — `column_id 'SFCASE::TIMETORESOLVE__C' appears 2 times in
columns[]` — so the emitted Model TML is rejected on import. Two `columns[]` entries resolve
to the same `TABLE::col` because the source referenced the physical column twice (e.g. a raw
`MEASURE` column `F_TIME_TO_RESOLVE` **and** `AVG(TIMETORESOLVE__C)`).

**Why it matters:** the from-**Snowflake** build-model (`sv_build_model`) already handles this
— it detects a duplicate `column_id` and promotes the extra occurrence(s) to `formulas[]`
(I8, and the related I5 `COUNT(DISTINCT)` → `unique count(...)` rule). The from-Databricks
build-model lacks that promotion, so the two converters diverge on the same input shape. This
is a converter-parity gap, orthogonal to role-play.

**Approach:** port the duplicate-`column_id` detection + formula-promotion from `sv_build_model`
into `mv_build_model` (ideally via a shared helper so the rule has one home), keeping one
`column_id` entry and expressing the other aggregation(s) as `formulas[]`. Add a unit test with
a fact-column + aggregate-metric-on-same-column fixture; re-run the SUPPORT_CASE round-trip to
confirm a clean `ts tml lint`.

**Target:** next Databricks converter edit (fold into BL-100's Databricks parity pass).

---

## BL-133 — `ts metadata delete`: partial-success handling for batch deletes — DONE `Tier 3`

**Status:** DONE — PR #333 (2026-07-24), refined by PR #335. `ts metadata delete` tries the batch
first and, on failure, falls back to per-GUID deletes, reporting a `{deleted, not_found, errors,
outcomes}` map to stdout (`deleted` key preserved for back-compat). The delete API is the source of
truth for each object's fate (approach (b)+(c); the search pre-filter (a) was dropped to avoid a
pre-filter under-count skipping a real object). New `--ignore-missing` flag treats already-gone
GUIDs as success; genuine errors always exit non-zero. PR #335 (from an angle-17-style `/code-review`
of #333) tightened `not_found` detection to key off the structured error code `13003` rather than a
bare "not found" substring, closing a false-positive that `--ignore-missing` could have silently
swallowed. ts-cli v0.93.0 → v0.94.0.

**Filed:** 2026-07-24.
**Source:** fixture teardown after the role-play PRs — deleting a model + its tables in one
call failed the whole batch when one GUID was already gone.
**Affects:** `ts metadata delete` (`commands/metadata.py`) + the `metadata/delete` API call.

**Symptom:** `ts metadata delete <g1> <g2> ... <gN>` returns a single 400 (`13003 Metadata
object not found corresponding to the metadata_identifier: ...`) and deletes **nothing** if
*any* one GUID in the batch is missing — the call is all-or-nothing. Deleting each GUID
individually succeeds, so the objects were deletable; only the batch atomicity bit.

**Why it matters:** teardown/cleanup scripts (and the dependency-manager rollback path) often
pass a set of GUIDs where some may already be gone; today that aborts the entire cleanup and
forces a per-GUID retry loop.

**Approach:** options — (a) pre-filter the batch against `metadata search` and drop GUIDs that
don't resolve before calling delete; (b) on a 400, fall back to per-GUID deletes and report a
per-object outcome map (`{guid: deleted|not_found|error}`) to stdout; (c) surface a
`--ignore-missing` flag. Keep the JSON-to-stdout contract. Add a unit test for the fallback
outcome map. Low effort; mostly a resilience/UX improvement.

**Target:** opportunistic.
