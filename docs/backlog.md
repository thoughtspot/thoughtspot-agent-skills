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
| BL-178 | from-Snowflake identifier resolution: 3-defect regression, every metric formula dangles | immediate |
| BL-183 | Validator: dangling `[formula_X]` refs in `ts tml lint` + CA-JSON table refs | with BL-178 |
| BL-174 | from-Databricks forward leg: `INNER` join type, dropped `format:`, stamped `cardinality:` | next DBX pass |
| BL-180 | from-Snowflake translator ignores `\|\|`→`concat` and NULL-preserving division | next formula pass |
| BL-172 | `check_formula_catalog.py` skips most data rows | next validator pass |
| BL-171 | Five ts-cli emitters still emit the six non-existent string functions | next formula pass |
| BL-100 | Bring remaining converters to DBX-from standard (Snowflake pipeline first) | post-audit |
| ~~BL-064~~ | ~~External audit product-currency fixes (medium-severity residuals)~~ | DONE |
| ~~BL-118~~ | ~~Codify AgentQL SV/MV backing behaviour~~ | DONE (PR #301) |
| ~~BL-063~~ | ~~Extract CLI formula translation~~ | DONE |
| ~~BL-029~~ | ~~Coverage matrix for ts-convert-to-databricks-mv~~ | DONE |

### Tier 2 — Schedule soon

| Item | Summary | Target |
|---|---|---|
| BL-184 | Worked-example reproducibility test (ground truth is never re-run) | after BL-178 |
| BL-179 | from-Snowflake promotes the first synonym over the logical identifier | with BL-166 |
| BL-181 | from-Snowflake classifies every fact `ATTRIBUTE` (no MEASURE branch) | after BL-178 |
| BL-182 | from-Snowflake reverse leg: date-suffix override + fabricated CA table `field` | next SF pass |
| BL-176 | File-only path Table TML gaps in both from-directions | next converter pass |
| BL-175 | Provenance text written into the round-tripping description field | with BL-166 |
| BL-166 | `custom_extensions`-style loss stash for the ts-convert-* pairs | next SF converter edit |
| BL-168 | Property-based tests for the ts-cli converter builders (dual-driver) | next builder change |
| BL-123 | Product currency gaps (2026-07-22 audit) | weekly sweep |
| BL-122 | Cross-skill prompt/discovery extraction | next converter edit |
| BL-127 | Roll out context-budget rule to all conversion skills | next converter edit |
| BL-129 | One-pass CLI guidance + batch ops across converters | next converter edit |
| BL-130 | Canonical data-type audit across converters (DATE_TIME) | 2026-09-30 |
| BL-095 | connections add-tables missing authenticationType | 2026-08-31 |
| BL-120 | Live e2e verification for ts-convert-from-qlik | first live pass |
| BL-115 | Smoke test for ts-convert-from-looker | first live pass |
| BL-126 | Migrate AgentQL smoke test from champ-staging to se-thoughtspot | blocked on instance |
| BL-135 | Live e2e verification for ts-object-model-alias | first live pass |
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
| BL-177 | Reverse legs synthesise names that were already available | opportunistic |
| BL-173 | Bound `ts tml verify-render` per-tile probing on large liveboards | opportunistic |
| BL-167 | Record (or change) the to-direction's never-hard-error-on-loss posture | opportunistic |
| BL-169 | Vendor-neutral TPC-DS fixture corpus (Phase-3-coupled) | Phase-3 test PR |
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
| BL-096 | se-thoughtspot AgentQL endpoints 500 | next build re-verify |
| BL-098 | DBX trailing/leading sparse data (item 3 only) | next DBX live-verify |
| BL-103 | searchConnection with OAuth hierarchy | next OAuth connection |
| BL-104 | Evaluate DBX BI compatibility mode | evaluation item |
| BL-106 | Python 3.11 floor bump (remaining) | after 2026-10 |
| BL-113 | Live provisioning step for load smoke | next SF live session |
| BL-114 | Document export_with_column_aliases | GA or skill need |
| BL-119 | Smoke test for ts-convert-from-sisense | first Sisense bundle |
| ~~BL-134~~ | ~~Smoke test for ts-object-model-alias~~ | DONE (feat/ts-object-model-alias) |

---

## BL-118 — Codify AgentQL semantic-view / metric-view backing behaviour into `ts-object-model-agentql-query` — DONE `Tier 1`

**Status:** DONE — PR #301 (2026-07-22). `references/snowflake-sv-backing.md` (R1–R7 + Databricks MV comparison)
committed; `limitations.md` updated with the measure-statistics silent-wrong-answer trap; SKILL.md references
table cross-linked; skill bumped to v1.5.0.

**Why it matters.** AgentQL/Semantic-SQL behaviour differs materially when a Model is backed by a
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
1. Recreate + extend `agents/cli/ts-object-model-agentql-query/references/snowflake-sv-backing.md`
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
- In flight: `docs/cross-model-stitching-analysis.md` (xModel fan-out avoidance in author-written AgentQL;
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
| Verified queries | **None** — Databricks uses Genie Agents with separate instruction files, not inline verified queries | N/A — no equivalent construct |

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
`access_modifier:`, `using_relationships:` on metrics (scope widened 2026-07-29 — see below),
and `base_table.definition:` (SQL-query logical tables, GA 2026-06-26 —
audit 13.4). The schema doc has been corrected (2026-06-17); the **converter emit
behaviour has deliberately not changed** pending verification.

**`using_relationships` (added 2026-07-29, TPC-DS fidelity review F21).** Every metric
`build-sv` emits lands at the root of `metrics()` with an unqualified name — which in Semantic
View terms is the **derived-metric** form, reserved for expressions spanning multiple logical
tables and required to declare its relationship path (`snowflake-schema.md:275-276`, Key
Structural Rule #1 at `:233-239`). On the TPC-DS fixture two of the five metrics genuinely do
span two tables and reach Snowflake with no declared path. Whether Snowflake resolves such a
metric by inference or rejects it is **unverified** — settle it in step 1's live round trip
alongside the other constructs, then either emit `using_relationships` or table-scope the
metric. See `docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` §3.6 F21; the referee could not
adjudicate it because OSI metrics are model-level by spec, so neither converter had the
information to scope them.

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

**Note (2026-07-29 full audit finding 11.3):** the shared reference this note
anticipated now exists —
`agents/shared/references/profile-select-and-authenticate.md` (this item's PR1) — but has
**zero adopters**: 15 `agents/cli/*/SKILL.md` files still inline a divergent "read
`~/.claude/thoughtspot-profiles.json`" block (`ts-convert-from-looker`, `ts-audit`,
`ts-dependency-manager`, `ts-object-model-aggregates`, `ts-object-answer-promote`,
`ts-object-model-agentql-query`, `ts-object-model-alias`, `ts-object-model-coach`,
both `ts-recipe-formula-*-snowflake` skills, `ts-object-model-erd`,
`ts-profile-thoughtspot`, `ts-variable-timezone`, `ts-publish-orgs`,
`ts-security-columns`) — a Claude-only path that quietly assumes the Claude Code
runtime, though `agents/cli/` also serves Cortex Code CLI. This is the confirmed
baseline for this item's adoption-pass phase: link each of the 15 to the shared
reference and swap the inline JSON-parse for `ts profiles list --json`. (BL-122's own
11.3 note is corrected separately — see that entry — and cross-references this one
rather than duplicating the adopter list.)

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

## BL-087 — Shared `ts agentql classify-columns` (dedupe divergent keyword lists)

**Source:** 2026-07-03 codification review row 24.
**Affects:** ts-object-model-agentql-query, ts-object-answer-promote, `tools/ts-cli/`.
**Status:** DONE 2026-07-03 (ts-cli v0.31.0) — `ts agentql classify-columns` shipped
(`ts_cli/spotql_ops.py` + `commands/spotql.py`); both skills adopt it (spotql-query
v1.3.0, answer-promote v1.3.0).

Column classification is duplicated between the two skills with DIFFERENT keyword lists
(spotql SKILL.md ~:137-146 vs promote ~:700-722) — live drift, and exactly the ts-cli.md
"two skills duplicate the same logic" trigger. One `ts agentql classify-columns --model
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

## BL-096 — se-thoughtspot build: AgentQL `generate-sql`/`fetch-data` endpoints return an empty-body 500 `Tier 4`

**Source:** 2026-07-09 BL-063 PR1 Task 5 live TS-side number-match run against se-thoughtspot (diagnostics recorded in `docs/audit/2026-07-08-dbx-window-claim-matrix.md`, "TS-side number-match results (Task 5, live 2026-07-09)" execution-path note).
**Affects:** `ts-object-model-agentql-query` skill; `ts agentql fetch-data` (and any command depending on it).
**Status:** OPEN.

The AgentQL endpoints (`/callosum/v1/v2/data/spotql/generate-sql` / `fetch-data`) return
a bare, empty-body HTTP 500 for any payload on this se-thoughtspot build — including an
empty request body, which a live handler would reject as a structured 400 — so `ts
spotql fetch-data` was unusable (its output normalises to `status: UNKNOWN`). Task 5
worked around this by fetching data via the stable v2 `POST /api/rest/2.0/searchdata`
endpoint instead (spec confirmed via `get-rest-api-reference(apiName: "searchData")`),
through a scratch script reusing `ts_cli.client.ThoughtSpotClient` for auth — the
documented open-items-style exception in `.claude/rules/ts-cli.md`, since ts-cli has no
`searchdata` command yet. `ts agentql classify-columns --model` is unaffected (it
classifies from exported TML, with no server-side AgentQL dependency).

**Target:** re-verify on the next se-thoughtspot build; if the 500 persists, add a
`searchdata`-based fallback to ts-cli's AgentQL commands. No date set — revisit next
time AgentQL commands are exercised live.

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
| ts-convert-from-snowflake-sv | **Shipped** — `ts snowflake parse-sv` / `translate-formulas` / `build-model` (+ `introspect`) | Partial — 2026-07-10 SE-cluster formula-composition/TML-import batch, but no per-construct claim matrix | Skill rewired onto the pipeline. CoCo mirror keeps the doc-driven path (no shell) — docs stay authoritative for it. |
| ts-convert-to-snowflake-sv | **Shipped** — `ts snowflake introspect` / `build-sv` | Inaugural anchor only (2026-06, never swept) | DDL emission codified; skill rewired. |
| ts-convert-to-databricks-mv | **Shipped** — `ts databricks build-mv` | Window emission tables live-verified (PR1) | MV YAML emission codified; skill rewired. |
| ts-convert-from-tableau | **Done** (full `ts tableau` pipeline) | Doc-driven sweeps only — no fixture number-match has ever run | Only the fidelity leg is missing; needs live Tableau Server access (often unavailable — see feedback memory). Scope as opportunistic. |
| ts-convert-from-looker | **None** | Not yet swept | (audit finding 5.2) 1,845 lines run lkml parsing, field resolution, measure translation, and TML emission agentically — the same mechanical shape codified for Tableau/Databricks/Snowflake. Cheapest parse leg of all converters (mature `lkml` parser on PyPI); build-model can reuse existing machinery. Model on the BL-063 phases (`ts looker parse` / `translate-formulas` / `build-model`). **The only converter left with zero deterministic pipeline** (2026-07-29 audit finding 11.4) — the natural next codification program. |

**Correction (2026-07-29 full audit finding 11.4):** the table above previously listed
Snowflake from/to and Databricks-to as "None (only diff/lint-ddl)" — stale. All three
shipped (`parse-sv`/`translate-formulas`/`build-model`/`introspect`/`build-sv` for
Snowflake; `build-mv` for Databricks-to) and their skills are rewired onto the pipeline.
ts-convert-from-looker is now the only converter with zero deterministic codification.

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

**Note (2026-07-29 full audit finding 16.1):** re-confirms the floor bump is already
tracked here (not a new item) and narrows the plan now that 3.10 EOL (2026-10) is ~2
months out: bump `requires-python` to `>=3.11` with a **MINOR** ts-cli version bump,
drop `3.10` from the `pytest-matrix` CI job (BL-107) at the same time, and check
install-docs / README for any `>=3.10` wording. Batchable with BL-164's
`snowflake-connector-python` 4.x floor bump — both are Oct-2026-adjacent dependency-floor
changes — but neither blocks the other.

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
  `agents/shared/references/connection-select.md`; ~~from-snowflake-sv and~~
  from-databricks-mv updated to link. **Correction (2026-07-29 full audit, its own
  finding 11.6 — "BL-122 item 11.3 status inaccurate"):** this status line was wrong —
  only from-databricks-mv actually links `connection-select.md`; from-snowflake-sv
  still carries its own inline N/F/L prompt and has NOT been updated. from-tableau also
  not yet updated (Tableau changes tracked separately). model-aggregates doesn't use
  this prompt (confirmed — no connection selection in that skill).
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

**Note (2026-07-29 full audit finding 11.3, profile-select-and-authenticate scope):**
a sibling adoption gap of the same shape — `agents/shared/references/profile-select-and-authenticate.md`
has zero `agents/cli/*/SKILL.md` adopters (15 skills still inline divergent profile-JSON
reads) — is tracked under **BL-084** rather than duplicated here, since that reference
was filed as BL-084's own PR1 and BL-084 already anticipated this exact adoption pass
(its 2026-07-11 note). See BL-084 for the adopter list and target date.

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

## BL-126 — Migrate AgentQL smoke test from `champ-staging` to `se-thoughtspot` profile `Tier 2`

**Filed:** 2026-07-22.
**Source:** Pre-push smoke failure — `champ-staging` token expired; SE profile uses
username/password (more resilient).
**Affects:** `tools/smoke-tests/smoke_ts_object_model_agentql_query.py`,
`tools/smoke-tests/smoke-config.local.json`
**Status:** OPEN — blocked until `se-thoughtspot` instance is reachable.

### Problem

The AgentQL smoke test (`smoke_ts_object_model_agentql_query.py`) hard-references
`champ-staging` in its docstring and `smoke-config.local.json` overrides the default
profile to `champ-staging` for this skill. That profile uses token auth which expires
and requires manual refresh. The `se-thoughtspot` profile uses username/password auth
which is more resilient to expiry.

### Proposed fix

1. Find or create an AgentQL-capable Model on `se-thoughtspot` (must be backed by
   Snowflake, not Falcon — AgentQL requires an external warehouse).
2. Write a simple AgentQL query for it.
3. Update `smoke-config.local.json` to remove the `champ-staging` override (the
   `default_ts_profile` is already `se-thoughtspot`).
4. Update the docstring in `smoke_ts_object_model_agentql_query.py`.

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
**Status:** DONE 2026-07-28 for the three filed skills — looker #390 (~21.0k → ~11.9k
est. tokens), databricks-mv #392 (~13.7k → ~11.4k), snowflake-sv #393 (~15.0k → ~11.5k);
all `check_skill_context_cost` warnings cleared, no logic changes. **Tableau round 2**
landed the same day: ~57.2k → ~34.4k (−40%, changelog history archived to
references/changelog-archive.md + step-file appends), but the file remains over the 25k
hard-fail line and keeps its allowlist entry — the residue is genuine procedural spine
(~29KB of protected commands/prompts/invariants). A round 3 would have to extract
prompt-and-command sequences from Steps 4.5/5b/6/7 into step files, trading inline
flow for size; deferred until the WARN pressure justifies it. The gate introduced
2026-07-28 (PR #385) now enforces the ceiling this entry was filed for.

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
**Affects:** all `ts-convert-*` SKILL.md + their `ts <src> verify`/build CLIs;
**+ `agents/cli/ts-audit/SKILL.md` line ~214** (2026-07-29 audit finding 14.3 — see below).
**Status:** OPEN (tableau done in #319).

Two generalizable token/latency wins found on Tableau, likely present in the other converters:
1. **No unnecessary per-object loops in skill prose.** `ts tableau build-model` already emits ALL datasources'
   models+tables in one call, but the SKILL.md prose ("one model per datasource") led agents to loop it per
   datasource (3× build + 3× lint + 3× verify on a 3-datasource workbook). Fixed by guiding a single pass.
   Audit looker/snowflake-sv/databricks-mv/qlik/sisense/powerbi skill prose for the same per-object looping.
2. **Batch verify.** Added `ts tableau verify --dir` (verify every model in a dir in one call) so verify isn't
   looped per model. Check whether sibling converters' `verify`/validate commands need the same `--dir`.
3. **Embed exact CLI command+flags per step** (see BL-122) — removed 5–7 `--help` probes/run.

**Extension (2026-07-29 full audit finding 14.3):** the same per-object-loop class exists
outside the converters — `ts-audit/SKILL.md:214` loops `ts metadata dependents "{model_guid}"`
once per Model even though the command accepts multiple GUIDs and batches natively (proven
by `ts audit run`'s own `build_context`, which already calls it batched). Prose-only fix:
change the step to pass all Model GUIDs to one call. Filed against this item's affected
list rather than a new BL, since it's the same shape this item already tracks — just found
outside the `ts-convert-*` family this item was originally scoped to.

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

---

## BL-134 — Write a smoke test for `ts-object-model-alias` — DONE `Tier 4`

**Filed:** 2026-07-24.
**Source:** new skill `ts-object-model-alias` (Task 5/6 of the column-alias feature).
**Affects:** `tools/smoke-tests/smoke_ts_object_model_alias.py` (new);
`tools/validate/check_smoke_tests.py` (ALLOWLIST entry).
**Status:** DONE — landed on `feat/ts-object-model-alias` (Task 6/6). `smoke_ts_object_model_alias.py`
covers the pure-function pipeline (`parse_csv_aliases` → `translations_to_columns`/`merge_aliases` →
`build_alias_tml` → structure/size assertions, plus the AI prompt/response round-trip via
`build_translation_prompt`/`parse_translation_response`) with no live ThoughtSpot or Snowflake
connection needed — mirrors the offline-smoke pattern used by `ts-convert-from-qlik`,
`ts-load-source-data`, and `ts-object-model-erd`. `ts-object-model-alias` removed from the
`check_smoke_tests.py` ALLOWLIST.

`ts alias export/translate/build/import` was already unit-tested (`tools/ts-cli/tests/test_alias.py`,
`test_alias_translate.py`) and code-backed; this closes the "no smoke test exists" gap the
ALLOWLIST exemption was covering. A genuine gap remains — no *live* round-trip has been run
against a real ThoughtSpot instance with the column-alias feature flag enabled — tracked
separately as **BL-135** (mirrors how BL-120 was split out once BL-119/the Qlik offline smoke
test landed).

**Target:** first live verification once a column-alias-enabled test instance is available.

---

## BL-135 — Live end-to-end verification for `ts-object-model-alias` `Tier 2`

**Filed:** 2026-07-24.
**Source:** Task 6/6 of the `ts-object-model-alias` feature, split out of BL-134 once its
offline smoke test landed (mirrors BL-120, split out of BL-119 for `ts-convert-from-qlik`).
**Affects:** `agents/cli/ts-object-model-alias/SKILL.md`; `ts alias export/translate/build/import`.
**Status:** OPEN.

`ts-object-model-alias` shipped code-backed (`ts alias`, unit tests in `test_alias.py`/
`test_alias_translate.py`, and an offline smoke test — `smoke_ts_object_model_alias.py` —
covering the pure-function pipeline). Still needs a live round-trip against a real
ThoughtSpot instance with the column-alias feature flag enabled (Beta, 10.13.0.cl+ — see
BL-114): `export` an existing Model's columns + any existing aliases, `translate` (AI and/or
CSV/table source), `build --merge`, `import` (exercising both the <5 MB sync and 5–25 MB
async-with-polling paths), then a re-`export` to confirm the aliases actually took effect.
No such instance was available during Tasks 1–6.

**Target:** first live-verification pass once a column-alias-enabled ThoughtSpot instance is available.

---

## BL-136 — Generic warehouse row-source for governance tables (Snowflake + Databricks) `Tier 2`

**Affects:** `ts alias translate --source db`; `ts publish export --objects-table`,
`ts publish resolve --source db --init-table`, `ts publish run --objects-table/--values-table`;
`get_sf_cursor` in `tools/ts-cli/ts_cli/commands/load.py`.
**Status:** OPEN (raised 2026-07-26).

**Why it matters.** Every `--source db` path in the repo is Snowflake-only. A customer on
Databricks can use the CSV path but not the governed-table path, even though Databricks is
otherwise a first-class platform here (`ts-profile-databricks`, `ts load databricks`, two
conversion skills, a whole `agents/databricks/` runtime). The asymmetry is an accident of
which platform each feature was built against first, not a deliberate scoping decision.

It matters more for `ts publish` than for `ts alias`, because a publication manifest is
operational state a customer will want governed, reviewed and scheduled, and the natural
home for it is the warehouse they already run.

**Why it is not a small change.** The two platforms do not currently share a shape:

| | Snowflake | Databricks |
|---|---|---|
| Path | Python connector, DB-API cursor (`get_sf_cursor`) | `databricks` CLI, Statement Execution API (`_run_dbx_sql` in `load.py`) |
| Credentials | profile + keyring | `~/.databrickscfg`, token never in-repo |
| Result | cursor + `cursor.description` | JSON payload |

So there is no cursor to abstract over. The abstraction has to sit one level up, at "give me
rows".

**Approach.** Introduce a row-source function in `commands/load.py`, beside the two existing
connection paths:

```python
def fetch_table_rows(platform: str, profile: str, table: str) -> list[dict]:
    """Read every row of a governance table as a list of dicts, lower-cased keys."""
```

with a Snowflake backend wrapping `get_sf_cursor` and zipping `cursor.description`, and a
Databricks backend wrapping the existing statement-execution helper and mapping its JSON
result. Callers then drop their private `_fetch_table_rows` and select the backend from
whichever profile flag was given (`--sf-profile` / `--dbx-profile`), or an explicit
`--warehouse snowflake|databricks`.

The normalisation contract already exists: `parse_object_rows` and `parse_value_rows` in
`ts_cli/publish_plan.py` lower-case headers precisely because a DB cursor returns them
upper-case and a hand-written CSV does not. A Databricks backend inherits that for free.

**Also needed.** The `--init-table` DDL is Snowflake-flavoured (`TIMESTAMP_NTZ`,
`CURRENT_TIMESTAMP()`, `VARCHAR`). A Databricks variant needs `TIMESTAMP`,
`current_timestamp()`, `STRING`, and no `PRIMARY KEY` clause on older runtimes. Emit per
platform rather than hoping one dialect parses on both.

**Target:** alongside the first customer engagement that governs a publication manifest in
Databricks. Not blocking `ts-publish-orgs`, whose file path covers the same ground.

---

## BL-137 -- End-to-end test-environment fixture for the multi-tenancy platform `Tier 2` -- **DONE 2026-07-27**

**Filed:** 2026-07-27.
**Source:** the repo owner's request, raised while verifying `ts security column-rules`
(`feat/ts-security-column-rules`) end to end.
**Affects:** the multi-tenancy platform programme as a whole -- `ts load`, `ts publish`,
`ts share`, `ts security column-rules`, and whichever `ts-security-columns` skill and
migration additions land later. No single ts-cli module owns this.
**Status:** **DONE 2026-07-27** — shipped as `ts tenancy` (ts-cli v0.111.0), with the
primitives it needed (`ts orgs create`, `ts users create`, `ts groups create` /
`search` / `add-member`). Pulled forward ahead of the migration additions at the repo
owner's request.

The per-Org group topology this item called out as the subtle part is enforced by
`tenancy_spec.validate_spec`, which refuses a spec where a user joins a group that is not
declared for that Org — the failure that otherwise surfaces as `Invalid group identifiers`
mid-apply. The shipped reference topology at `tools/fixtures/tenancy-reference.yaml` is
**captured** by `ts tenancy export` from a working cluster rather than hand-written, so it
cannot drift from the environment it describes.

Warehouse tables remain `ts load`'s job, as this item anticipated; `ts tenancy` owns the
Org/user/group topology only.

**The guided path is `/ts-setup-tenancy`** (second PR). The CLI alone did not satisfy this
item's own wording -- "a cluster state a newcomer can stand up from scratch and immediately
use to run the whole pattern" -- because the end-to-end sequence spans five command groups
and carries real judgement. The skill builds one of four scenarios: `topology`, `per-org`
(the PRE-migration state, which is `ts migrate audit`'s input), `published` (the
post-migration target) and `mixed` (the half-migrated state a real cluster occupies for the
whole duration of a migration, and where the untested interactions live).

Production tenant onboarding is BL-143.

**Why it mattered.** Today, exercising publication, sharing, aliasing and column security
end to end requires a cluster someone has hand-built, and reproducing it is undocumented
tribal knowledge. Verifying this branch alone needed warehouse tables, several Orgs, users
assigned to those Orgs, and users assigned to per-Org groups -- and there is no repeatable
way to stand that up other than remembering how it was done last time.

**Why it is subtle, not merely tedious.** Groups are per-Org: a group name that exists in
the Primary Org does not exist in a tenant Org, and a CSR manifest or `ts share` manifest
naming it fails there (`_check_groups_exist` in `share_planning.py` refuses exactly this).
Getting the per-Org group topology right -- which groups exist in which Org, and which
users are members of which per-Org group -- is the part of a hand-built environment most
likely to be got wrong, not the tedious-but-mechanical parts like warehouse tables.

**Approach.** A reproducible fixture that provisions, in order: warehouse tables (`ts load`
already does this and is the natural starting point -- see `ts-load-source-data`); the
Orgs themselves; users created and assigned to those Orgs; and per-Org groups created with
the right members in each Org. The deliverable is a cluster state a newcomer can stand up
from scratch and immediately use to run the whole pattern -- publish, alias, share, secure
-- without hand-authoring any of the topology first.

**Target:** after the platform's development work is complete end to end -- i.e., once the
`ts-security-columns` skill and the migration additions (parent spec §4/§5 of
`2026-07-26-ts-security-sharing-design.md`) have landed -- so the fixture covers the
finished shape of the platform rather than chasing a moving one.

---

## BL-138 -- `ts alias import` and `ts tml import` do not detect embedded per-item TML failures `Tier 2` -- **DONE 2026-07-27**

**Filed:** 2026-07-27.
**Source:** `ts security column-rules import`, fixed on `feat/ts-security-column-rules`
after a live-observed failure: an import that failed with error code 14502 exited 0.
**Affects:** `ts alias import` (`commands/alias.py`); `ts tml import` (`commands/tml.py`);
the shared pure helper `tml_import_failures` in `tools/ts-cli/ts_cli/tml_common.py`.
**Status:** **DONE 2026-07-27.** `ts alias import` and `ts tml import` now both call the shared `tml_import_failures` helper and exit non-zero, naming each failed item. `ts tml import` collects failures BEFORE its GUID back-fill loop, which deliberately skips non-OK items and would otherwise have been the only thing that noticed. A new shared `format_import_failures` keeps all three callers reporting the same shape, and `test_import_failure_detection.py` asserts all three are wired -- so the next reader does not have to grep three modules.


**Why it matters.** `POST /api/rest/2.0/metadata/tml/import` returns HTTP 200 even when
individual items in the batch failed -- the per-item outcome is buried in the response
body (`response.status.status_code == "ERROR"`, with an accompanying `error_code`), not
the HTTP status. A caller that checks only `resp.ok` reports success on an import that did
nothing. Live-verified on this branch: before the fix, an import that failed with error
code 14502 exited 0 and reported success.

This branch fixed it for `ts security column-rules import` only: it now calls the shared
pure helper `tml_import_failures(result)` and exits non-zero, naming each failed item, when
the platform's own per-item status disagrees with the HTTP status. `ts alias import` and
`ts tml import` have the identical shape and the identical gap, but were deliberately left
alone to keep this branch's blast radius small -- both still trust `resp.ok` alone.

**Approach.** Wire both callers to the existing `tml_import_failures` helper the same way
`security_planning.py`'s `import_cmd` already does: call it on the parsed response and
route to the same style of per-item failure reporting before exiting non-zero, translating
via each command's own error-translator where one exists. No new parsing logic is needed --
the helper already exists and is pure.

**Target:** next time either `ts alias import` or `ts tml import` is touched, since the
helper already exists and the fix is now mechanical.

---

## BL-139 -- The `CliRunner(mix_stderr=False)` fallback is a Click 8.2 landmine `Tier 3` -- **DONE 2026-07-27**

**Filed:** 2026-07-27.
**Source:** noticed while adding tests to `tools/ts-cli/tests/test_share_commands.py` on
`feat/ts-security-column-rules`, following the convention already used by
`tests/test_security_planning.py` and others.
**Affects:** every test module using the `try: CliRunner(mix_stderr=False) except
TypeError: CliRunner()` pattern; `tools/ts-cli/tests/conftest.py`; the Click pin in
`pyproject.toml` (currently 8.1.8).
**Status:** **DONE 2026-07-27.** Both runners now live in `tools/ts-cli/tests/runners.py`; 22 modules import them and no test constructs `CliRunner(mix_stderr=False)` any more. Note the approach below proposed `conftest.py`, which is WRONG for this repo: pre-commit and CI run `tools/ts-cli/tests/` and `tools/validate/tests/` as one pytest invocation and both have a conftest, so a bare `from conftest import ...` binds to whichever is cached first. A uniquely named module has no such collision, exactly as `ansi.py` does.


**Why it matters.** Several test modules construct their `runner` with `try:
CliRunner(mix_stderr=False) except TypeError: CliRunner()`, because Click 8.2 removed the
`mix_stderr` parameter entirely (it raises `TypeError` at construction, not at call time).
Click is pinned at 8.1.8 today, so the `try` branch always succeeds. The moment Click is
upgraded past 8.1.x, every one of those `runner`s silently becomes a *mixing* runner
instead of a stream-separated one -- no test fails at the moment of upgrade. What breaks
instead is every `json.loads(result.stdout)` assertion across those modules, each failing
with a confusing JSON-decode error that gives no hint the real cause is an unrelated Click
version bump.

**Approach.** `feat/ts-security-column-rules` created `tools/ts-cli/tests/conftest.py`
for an unrelated reason (see its docstring), which makes it the obvious single home for a
shared `runner`/`msg_runner` pair: define both there once, and have every test module
import them instead of repeating the try/except. That turns the eventual fix --
reconstructing `msg_runner`'s mixing behaviour some other way once `mix_stderr` is gone,
and pointing every module at the shared fixtures -- from a repo-wide sweep into a
one-file change plus per-module import edits.

**Target:** whenever Click is upgraded past 8.1.x, or opportunistically before then to
pre-position the shared fixtures.

---

## BL-140 -- `ts security column-rules export --out` writes a flat layout while `build --out` namespaces by Org `Tier 3` -- **DONE 2026-07-27**

**Filed:** 2026-07-27.
**Source:** noticed while implementing `build --out`'s Org-namespaced layout on
`feat/ts-security-column-rules` (`security_planning.py`'s `_document_paths`).
**Affects:** `ts security column-rules export` (`commands/security.py`); `ts security
column-rules build --out` (`commands/security_planning.py`, already fixed).
**Status:** **DONE 2026-07-27.** `export --out` now writes `<out>/<org>/<TABLE>_CSR...tml`, matching `build --out`, and refuses an Org name containing a path separator. An un-scoped export (no `--org`) stays flat: there is no Org name to use and inventing one would make the path unpredictable.


**Why it matters.** `build --out` was changed on this branch to write
`<out>/<org>/<TABLE>_CSR.column_security_rules.tml` -- one subdirectory per Org --
because a plan step is per (Org, table) but the platform's own filename is derived from
the table alone. A flat layout collapsed a multi-Org plan into one file per table,
silently keeping only the last Org's rules and losing every other Org's (see
`_document_paths`'s docstring).

`ts security column-rules export --out` still writes the flat layout,
`<out>/<TABLE>_CSR...tml`, with no Org subdirectory. Exporting the same table from two
different Orgs into the same output directory, across two separate `export` invocations,
silently overwrites the first Org's export with the second's. Same collision class as the
one `build` already guards against, but lower severity: it needs two deliberate
invocations against the same `--out` directory rather than a single multi-Org plan
producing the collision on its own.

**Approach.** Apply the same Org-subdirectory fix to `export --out` that `build --out`
already has, reusing the same collision-refusal logic rather than re-deriving it.

**Target:** alongside the `ts-security-columns` skill, which is the first thing likely to
script repeated per-Org exports into a shared directory.

---

## BL-141 -- The parent spec and the platform plan still carry a disproven CSR-on-published claim `Tier 3` -- **DONE 2026-07-27**

**Filed:** 2026-07-27.
**Source:** live verification of `ts security column-rules` on `feat/ts-security-column-rules`,
third round (data-plane, real non-admin users). See
`docs/superpowers/verification/2026-07-26-ts-security-column-rules-live-verification.md`
§15 for the evidence.
**Affects:** `docs/superpowers/specs/2026-07-26-ts-security-sharing-design.md` (§1's
CSR-vs-CLS comparison table, row "Works on published objects"); `docs/multi-tenancy-platform-plan.md`
§4.3 ("Publication constrains the column-security mechanism").
**Status:** **DONE 2026-07-27.** The parent spec's §5.1 is corrected. `docs/multi-tenancy-platform-plan.md` §4.3 had already been corrected in an earlier PR, so only one document needed the edit; the stale 'both still carry the claim' notes in the CLI design doc are updated too.

comparison table row now reads "Accepted and enforced, but Org-scoped" with a pointer to a
new §2.7; §2.7 records the corrected behaviour and supersedes the old flat "No"; §6's open
items #2 and #3 are answered and a new open item #5 records the still-unresolved question of
whether a tenant Org can be given usable CSR at all. `docs/multi-tenancy-platform-plan.md`
§4.3's opening claim is rewritten to the corrected mechanism (accepted, but Org-scoped),
keeping the existing table and sequencing conclusion, plus a note that this makes the
per-Org (`org_name`-keyed) shape of the `TS_COLUMN_SECURITY_RULES` manifest load-bearing.

**Why it matters.** Both documents state that CSR cannot be defined on published objects.
Live testing disproved the mechanism, not the conclusion: the platform accepts a CSR
update against a genuinely published object from the owning Org, returns HTTP 204, and
enforces it there -- but the rule does not travel with publication, so a tenant Org the
object is published to keeps seeing the restricted column in full, with no error and no
warning either way. The two documents' bottom-line advice ("do not rely on CSR here") is
still right, but the reason they give is wrong: it is not an API refusal, it is a silent
scoping trap, and an operator reading only the current wording would expect a hard failure
rather than a working-but-misleading result. `ts security column-rules`
(`commands/security_planning.py`, §3.3 of `2026-07-26-ts-security-column-rules-cli-design.md`)
already codifies the corrected understanding; these two programme documents have not
caught up.

**Approach.** Correct the mechanism in both places, keeping the same "do not do this"
conclusion: CSR from the owning Org succeeds and is enforced in that Org, but does not
propagate to any tenant Org the object is published to. Cite the live-verification
document above as the evidence. Both documents are outside this branch's scope (see the
top of `2026-07-26-ts-security-column-rules-cli-design.md`), so the correction is deferred
rather than made here.

**Target:** next edit to either document.

---

## BL-142 -- PLATFORM: an object-level `NO_ACCESS` removes discovery but not the column-grant entitlement `Tier 2`

**Filed:** 2026-07-27.
**Source:** data-plane verification for `ts-security-columns`, as real non-admin users on
`nebula-damian-alias`. See
`docs/superpowers/verification/2026-07-27-ts-security-columns-live-verification.md` §11.

This is a **platform defect to raise with ThoughtSpot**, not a repo bug. Recorded here so
the skill's guidance has something to point at and so it is not rediscovered.

**What happens.** With a group holding column-level grants (CLS) and no object grant,
applying an object-level `NO_ACCESS` to that group:

- removes the object from **search** (a Model disappears; a Table stays reachable via the
  Data page), and
- leaves the **entitlement fully intact** -- the object still opens by **direct link**,
  still showing exactly the granted columns.

Verified on both `T2_PUBLISH` (Table) and `T2_PUBLISH_MODEL` (Model) in Primary, with
Strict Object Mode ON. The Table/Model difference is only which discovery surface each
uses; the entitlement is identical on both.

**Why it matters.** A partial deny is worse than either a real deny or none at all. It
looks effective to the administrator who applied it while remaining live for anyone with a
direct link, a bookmark, or an Answer or Liveboard built on the object. The intuitive
operator action -- "remove their access to this table" -- does not do what it appears to,
and nothing warns. Same failure class as CSR-on-published: the write succeeds, and a false
belief is created.

**What we do in the meantime.**

1. `ts-security-columns` states the rule plainly: to revoke CLS, revoke at **column**
   level; an object-level deny is not a revoke.
2. Consider having `ts share status` flag surviving column grants when the object grant is
   absent, rather than listing them as unremarkable rows -- that combination is now known
   to be the shape of a failed revoke.
3. `ts share`'s existing refusal to mix revoke-and-grant in one manifest is retro-justified
   by this and should stay.

**Target:** (1) ships with the skill. (2) is a `ts share` follow-up, unscheduled. Raising
it with the platform team is the real fix.

---

## BL-143 -- Production tenant onboarding over `ts tenancy` `Tier 2`

**Filed:** 2026-07-27.
**Source:** the repo owner, while `ts tenancy` was being built for BL-137 — "can this be
used for production setup as well, i.e. a client can use this to build a tenant in an Org".
**Status:** OPEN.

**The engine is already production-capable.** Creating a tenant's Org, its per-Org groups
and its users is the same operation as building a fixture, and `ts tenancy` was
deliberately designed for both rather than fixture-only: `account_type` is per user so a
federated tenant gets `SAML_USER`/`OIDC_USER` and is never offered a password; `--tenant`
substitutes `{TENANT}` through a template so one spec onboards N tenants without a
copy-pasted file each; and `teardown` requires the marker AND every Org named on the
command line AND `--yes`, so no single mistake can lose a real tenant.

**What is missing is selectivity.** A fixture means "make all of this exist". Production
onboarding is usually **partial** — create the Org and its groups, but let users arrive via
SSO/SCIM; or add a group to an Org that already exists. `apply` already tolerates this
(it is idempotent, and any spec section may be omitted), but there is no way to say
"apply the orgs and groups, skip the users" from one shared spec.

**Scope.**

1. `--only orgs,groups,users,members` / `--skip ...` on `apply`, so one spec serves both a
   full fixture and a partial onboarding.
2. A `ts-tenant-*` skill wrapping the whole pipeline with confirmation gates:
   `ts tenancy apply` -> `ts connections create` -> `ts load` -> `ts publish` ->
   `ts alias` -> `ts share` / `ts security column-rules`. Every one of those already
   exists; the skill is orchestration and judgement, not new API surface.
3. Decide whether the marker belongs on production objects. It reads as provenance
   ("this Org was provisioned from spec X"), which is probably worth keeping, but it also
   makes `teardown` willing to consider them — that interaction needs a deliberate answer.

**Why not now.** BL-137 wanted a test fixture, and shipping the onboarding skill against
an unmerged engine would make both harder to review. The engine is the part that would
have been expensive to retrofit, so it was done first.

**Target:** after the migration additions (parent spec §5 of
`2026-07-26-ts-security-sharing-design.md`), so the skill covers the finished platform.

---

## BL-144 -- PLATFORM: a column-less RLS expression imports `OK` and silently WIPES existing rules `Tier 1`

**Filed:** 2026-07-27.
**Source:** RLS-on-published verification for `ts-org-migrate`, on `nebula-damian-alias`.
See `docs/superpowers/verification/2026-07-27-ts-migrate-binding-resolution.md`.

An RLS `expr` that references no column is accepted by TML import with `status_code: OK`,
but the `rules` array is **discarded** -- and if the table already carried a valid rule,
**that rule is destroyed too**. Verified in sequence on one table:

| # | `expr` | Import | Rule afterwards |
|---|---|---|---|
| 1 | `[T_1::PROD_NM] = ts_username` | `OK` | present, correct |
| 2 | `[T_1::PROD_NM] = ts_orgid` | `ERROR` -- unknown keyword | unchanged (rule 1 intact) |
| 3 | `ts_orgid = 0` | **`OK`** | **GONE** -- rule 1 destroyed |

Row 2 is the control that makes this a defect rather than a syntax complaint: the *same*
unknown keyword errors loudly when a column reference is present, and passes silently when
it is not. The rule is discarded before keyword validation, so the caller is told the
import succeeded.

**Why Tier 1.** The failure is silent in the direction that removes security. An operator
who applies a malformed rule believes RLS is in force; the table is in fact unfiltered, and
any rule that *was* protecting it is gone. Nothing in the response distinguishes this from
a successful application.

**Ask:** reject a rule whose expression references no column, rather than dropping it; and
never let a rejected rule delete the rule it was meant to replace.

**Mitigation until fixed** -- any code path writing `rls_rules` must **read back and assert
the rule survived**, never trusting `status_code: OK`.

**Update 2026-07-28: `ts migrate apply` is NOT exposed to this.** It writes no Table TML at
all -- the architecture changed to export/rewrite/import and nothing is lifted. A guard was
added and then removed as dead code: it looked for `doc["table"]["rls_rules"]` while only
ever running on a Model document, which has no `table` key, so it could never fire.
Recorded because dead safety code reads as protection. BL-144 remains live for anyone
writing Table TML directly.

---

## BL-145 -- `ts_orgid` is not a valid RLS keyword; Org-aware RLS needs ABAC formula variables `Tier 2`

**Filed:** 2026-07-27.
**Source:** as BL-144.

The natural predicate for a published single-model tenancy -- filter rows by the querying
user's Org -- has no system variable on this build. `ts_orgid` is rejected:
`Search did not find "ts_orgid" in your data or metadata`. The documented system variables
are only `ts_username` and `ts_groups`.

The documented Org-aware route is `ts_var(varName)` against an **ABAC formula variable**,
whose values can be set per Org. On `nebula-damian-alias` that is also unavailable:
`ts_var(apj_schema)` is rejected at parse time, and the `VariableType` enum on
`template/variables/create` accepts neither `FORMULA`, `RLS` nor `USER_PARAMETER`. The
only variable observed is `TABLE_MAPPING` -- the *publishing* parameterization class, which
is a different mechanism from ABAC formula variables despite the shared endpoint.

So on this cluster the two Org-aware options are: a `ts_groups` predicate against a
per-Org group whose name matches a tenant-key column value, or enabling ABAC via RLS.

**Blocks:** open question 4 in the org-migrate design cannot be fully answered until an
Org-aware predicate is available; only the *does RLS carry at all* half is testable today
(via `ts_username`).

**Next:** confirm with the platform team whether ABAC via RLS is a flag that can be enabled
on this cluster, and whether an Org-scoped system variable is planned.

---

## BL-146 -- `ts publish apply` creates state before its cohort gate, then cannot be re-run `Tier 2` -- **DONE 2026-07-28**

**Filed:** 2026-07-27.
**Source:** staging the end-to-end migration fixture on `nebula-damian-alias`. See
`docs/superpowers/verification/2026-07-27-ts-migrate-e2e-runbook.md`.

`apply` creates the template variable and parameterizes the field **before** checking the
cohort-column gate. Publishing a Set-blocked Model therefore:

1. creates the variable,
2. parameterizes the table's `schemaName`,
3. *then* refuses on the cohort column.

The variable and the parameterization are left behind. The re-run fails at step 1 with
`HTTP 409 Duplicate template variable name` -- pointing at the wrong problem entirely, and
sending the operator looking for a variable conflict rather than the Set that actually
blocked them. Recovery needs a manual `unparameterize` first, because the variable cannot
be deleted while still bound.

**Ask:** run the cohort gate (and any other refusal that is knowable up front) **before**
creating anything. Failing that, roll back what was created when a later gate refuses.

**FIXED (ts-cli v0.113.1).** `apply` now reads `cohort_columns` off the closure -- which
`export` already computed, so the check is free -- and refuses beside the existing
coverage-gap check, before any client is even constructed. Verified live against
T1_PUBLISH_MODEL: the same command on the same cluster state that previously reported
`HTTP 409 Duplicate template variable name` now names the actual cohort column, and the
message states that nothing needs cleaning up so nobody goes looking.

**Also observed:** the refusal was invisible at the surface being watched. `created
variable` and `parameterized` printed, while the cohort message went elsewhere -- so the
run read as partial success rather than a refusal.

---

## BL-147 -- `ts migrate audit` reads the WRONG ORG when given an Org name `Tier 2` -- **DONE 2026-07-28**

**Filed:** 2026-07-27.
**Source:** as BL-146.

`ts migrate audit --source-org ORG1` fails with `Specified identifier doesn't exist
<guid>`; `--source-org 12750490` works. `auth/token/full` silently ignores a non-numeric
`org_identifier` and falls back to the caller's default Org (memory
`feedback_ts_org_scoped_auth_silent`), so the audit reads Primary while believing it is
reading ORG1.

The inline comment in `commands/migrate.py::audit` asserting that `_org_auth_fields`
resolves a name **is wrong**, which makes this worse than an undocumented limitation -- it
tells the next reader the opposite of the truth.

A missing GUID is the lucky case. The dangerous one is an audit that *succeeds* against
the wrong Org and emits a plausible `column-mapping.csv` for objects that are not the
tenant's.

**Ask:** resolve the name to a numeric id and assert the session, exactly as `apply` does;
or refuse a non-numeric value outright. Correct the comment either way.

**FIXED (ts-cli v0.113.1).** `_assert_write_org` is now `_org_client` and **every** command
in the group goes through it, reads included -- the read/write distinction was the mistake,
since the audit produces the file a human approves. The false comment is replaced with the
reason. Verified live: `--source-org ORG1` now returns the correct ORG1 mapping where it
previously failed outright.

---

## BL-148 -- lift-and-shift collides by NAME with the published objects it is migrating onto `Tier 1` -- **RESOLVED BY DESIGN CHANGE 2026-07-28**

> **No longer reachable.** Lift-and-shift was removed: `ts migrate apply` now rewrites
> content (data-source reference + column names) instead of lifting scaffolding, so nothing
> is ever imported that could collide. The finding below stands as a fact about the
> platform and is why the architecture changed -- see
> `docs/superpowers/specs/2026-07-28-ts-migrate-orgs-rewrite-design.md`. The third
> candidate option recorded below ("do not lift the scaffolding at all") is what was
> built.

**Filed:** 2026-07-28.
**Source:** the first live `ts migrate apply` run against the end-to-end fixture. See
`docs/superpowers/verification/2026-07-27-ts-migrate-e2e-runbook.md`.

**This blocks Phase 2 end to end.** `ts migrate apply` fails at `lift_scaffolding`:

```
scaffolding import failed:
  Error: Found multiple data sources with same name.
  - T2_PUBLISH
    * T2_PUBLISH[d2c12c11-...]   <- the PUBLISHED table
    * T2_PUBLISH[0d111529-...]   <- the scaffolding being lifted
```

### Why it is structural, not a fixture artefact

The collision is **guaranteed by the design**, not incidental:

1. `ts migrate audit` pairs a tenant Model to its published counterpart **by name**. So by
   construction they share one.
2. `apply` then lifts the tenant's Table and Model into the target Org -- which already
   holds the published objects of those exact names.
3. Reference resolution is **fqn-then-name** (spike finding 4). The lifted Model's `fqn`
   points at a source-Org GUID that is dead in the target, so resolution falls back to the
   name -- and now finds two.

Spike finding 4 already stated "names must be unique within the target Org" as a
precondition. What was missed is that **the architecture itself violates it**: pairing by
name and lifting into the same Org cannot both hold.

### What was ruled out

`ALL_OR_NONE` behaves correctly -- the failed batch created nothing, and the target Org was
left clean. This is a hard failure, not a partial write.

Three variants were probed live; none is a fix on its own:

| Variant | Result |
|---|---|
| Keep the document `guid`, same names | `Object with GUID ... already exists. New GUID will be used` -- the source GUID is not usable as an intra-batch key |
| Strip `guid`, rename scaffolding unique | Table created, but the Model then fails: `No table with fqn ... found for table_id MIG_T2_PUBLISH` |
| Keep `guid`, rename scaffolding unique | same as above |

Renaming the scaffolding **Table** is not sufficient because the scaffolding **Model** also
collides with the published Model -- and renaming the Model breaks the *content* lift,
which is a later batch whose Answers resolve the Model by name.

### Candidate designs, none yet chosen

| Option | Note |
|---|---|
| Lift scaffolding **and content in ONE batch**, with scaffolding renamed unique | All references remap intra-batch, so no name fallback is needed. Fewest calls. Needs verification that intra-batch fqn remapping actually works across object types |
| Rename scaffolding unique, then rewrite each content object's Model reference from the ledger's source→target GUID map | Deterministic, but it is O(objects) reference rewriting -- the exact thing the architecture exists to avoid |
| Do not lift the scaffolding at all; bind lifted content directly to the **published** Model | Removes the collision entirely and would simplify the design, but the rename step exists precisely because the names do not match yet, so the ordering would have to change |

The third is the most interesting and was already flagged as "the strongest option" in the
original spike, deferred for its own verification. It is now worth taking seriously.

**Do not attempt a quick fix.** This is reference-resolution behaviour that has already
produced one wrong assumption (a guard that could never fire, BL-144's mitigation), and
each candidate needs its own live verification before being built.

---

## BL-149 -- `search_query` propagates ASYNCHRONOUSLY after a column rename `Tier 1` -- **NO LONGER ON THE MIGRATION PATH 2026-07-28**

> **The migration no longer depends on the cascade.** `ts migrate apply` rewrites
> `search_query` deterministically rather than renaming a Model column and waiting, so the
> lag cannot bite it. The finding below stands as a live platform fact and still applies to
> anyone relying on rename propagation -- it is simply not a migration blocker any more.
> The "rewrite deterministically" option recorded below is what was built.

**Filed:** 2026-07-28.
**Source:** live on `nebula-damian-alias`, testing the rename cascade the whole migration
architecture rests on. Raised by the repo owner from field experience, then reproduced.

Renaming a Model column updates a dependent Answer's fields at **different times**:

| Field | Immediately after the rename | Next read |
|---|---|---|
| `answer_columns[].name` | new name | new name |
| `table.table_columns[].column_id` | new name | new name |
| `search_query` | **OLD name (stale)** | new name |

Reproduced in both directions (rename, then revert). It does converge -- this is a lag,
not a permanent failure.

### Why Tier 1

The migration's `rename` step is immediately followed by steps that **export** content. An
export taken in that window produces a TML that is **internally inconsistent**: the column
lists carry the new name while `search_query` still carries the old one.

That TML then fails on import, or worse mis-binds -- and `search_query` correctness before
import is already a hard constraint (memory `feedback_ts_tml_import_constraints`). The
failure mode is a half-correct document that looks plausible in review.

### What this corrects

The 2026-07-15 verification concluded that a rename "auto-propagates to dependent
Answers/Liveboards", and the design's O(columns)-not-O(objects) claim rests on it. That
test only inspected a **formula** field, which updates synchronously. It saw the half that
works.

The claim survives, narrowed: propagation is real, but it is not atomic, and nothing in the
API response signals when it has completed. `diff: {columns_updated: 1}` is returned before
`search_query` has caught up.

### Also established: content TML has NO physical anchor

A Liveboard references columns purely by display name -- `search_query` tokens,
`answer_columns[].name`, and `table_columns[].column_id`, where `column_id` is the **display
name**, not a `TBL::COL` binding. Only `tables[].fqn` (the data-source GUID) is stable.

This is why the rename has to be relied on at all: there is no id-based path.

### Options

| Option | Note |
|---|---|
| Rewrite `search_query` deterministically after the rename, rather than trusting the cascade | Deterministic and testable, and the repo already prefers codified transforms over waiting. Costs a per-object edit, but only to one field |
| Poll each content object until its export is self-consistent (`search_query` tokens all present in `answer_columns`) | No rewriting, but unbounded wait and a fuzzy stop condition |
| Re-export content in a later pass, well after the rename | Simplest, but "well after" is not a specification |

The first looks strongest, and it composes with **BL-148**: content has to be rewritten for
the data-source reference anyway, so `search_query` becomes one more field in the same pass
rather than a separate mechanism.

---

## BL-151 -- Skill to migrate tables from column-level sharing to column security rules `Tier 2`

**Filed:** 2026-07-28. **Renumbered from BL-150 on 2026-07-28:** two items were filed as
BL-150 the same day. The other one is cross-referenced from `CHANGELOG.md`, `apply_exec.py`,
`apply_plan.py`, a test docstring and `ts-migrate-orgs/SKILL.md`, so it kept the number and
this one moved.
**Source:** user request.
**Family:** `ts-security-columns` (see `.claude/rules/skill-naming.md` family #11).

ThoughtSpot has two mechanisms for restricting column visibility: **column-level sharing**
(the legacy approach — share individual columns per group/user) and **column security rules**
(the newer, policy-based approach — define rules that control which columns are visible to
which groups). The newer mechanism is more maintainable at scale, but migrating from one to
the other is manual and error-prone.

### What the skill would do

1. **Audit** — for a given table (or set of tables), read the current column-level sharing
   configuration and produce a report of which columns are shared with which groups/users.
2. **Generate rules** — translate the sharing configuration into equivalent column security
   rules that produce the same effective visibility.
3. **Apply** — import the generated column security rules (with user confirmation).
4. **Verify** — compare effective column visibility before and after to confirm equivalence.
5. **Cleanup** — optionally remove the legacy column-level sharing entries once the rules are
   verified.

### Approach

- Research the column-sharing and column-security-rules APIs via SpotterCode MCP before
  writing any code.
- The `ts-security-columns` family already exists in the naming convention — this skill fits
  there.
- The `ts security column-rules` CLI group (if it exists) or new ts-cli commands would handle
  the API calls; the skill orchestrates the migration workflow.

---

## BL-150 -- a new-Org migration DROPS ALL SHARING, so tenant users lose every object `Tier 1`

**Filed:** 2026-07-28.
**Source:** raised by the repo owner asking whether the fixture was visible only to
`tsadmin`. It was -- and checking why exposed the general case.

**TML carries no sharing information at all.** An exported Answer contains no `share`,
`permission`, `principal`, `group` or `acl` key; its top-level keys are only
`answer_columns`, `chart`, `display_mode`, `name`, `search_query`, `table`, `tables`.

So in a **new-Org** run, `ts migrate apply` creates content authored by the migrating
admin and **shared with nobody**. The migration completes, every object is present and
correct, every check passes -- and not one tenant user can see anything.

### Why this is Tier 1

It affects **every tenant** in production, it is **silent** (nothing fails), and it is
invisible to an admin verifying the migration, because an admin sees objects regardless of
sharing. The failure surfaces only when a real tenant user logs in and finds an empty
Org -- which is exactly the point at which the source Org may already have been retired.

A **same-Org** run is unaffected: content is updated in place and keeps its existing
grants.

### What a fix has to handle

Reading and re-applying is straightforward -- `security/metadata/fetch-permissions` on the
source, `ts share` on the target. Two things make it more than a copy:

1. **Groups are per-Org principals.** A group named `ACME_VIEWERS` in the source Org is a
   *different object* from a same-named group in the target, so the target must already
   have the group (a `ts tenancy` precondition) and the grant must be resolved against the
   target's principal, not the source's.
2. **Users may not exist in the target Org yet**, since cutover is deliberately the last
   step. A per-user grant therefore cannot always be applied at migration time, and may
   have to be deferred to cutover.

### RESOLVED 2026-07-28 -- it was OUR bug: the whole object stack must be granted

`nebula-damian-alias` runs **Strict Object Mode**, so a user needs an explicit grant on the
entire chain -- Table, then Model, then content. And **publication makes an object *present*,
not *visible***, so the published Model carries no tenant grants of its own (that half is
independent of the mode).

> **Strict Object Mode is a per-cluster SETTING and can be toggled.** Confirm it before
> assuming this explanation applies elsewhere -- on a non-strict cluster the same symptom
> will have a different cause. The fix below is **safe either way**: with the mode off the
> extra grants are redundant rather than wrong, so no mode detection is needed.

`share_grants` shared only the content. With the Model ungranted, **the Answer share was
accepted and not recorded**:

```
BEFORE  published Model grants: [Administrator, tsadmin]
        Answer grants         : [Administrator, tsadmin]

share published TABLE  -> 204
share published MODEL  -> 204   ->  MIGTEST_VIEWERS/READ_ONLY APPEARS
re-share the ANSWER    -> 204   ->  MIGTEST_VIEWERS/READ_ONLY APPEARS
```

Granting the Model made the identical Answer share register immediately.

**Why ORG1 appeared to work:** the fixture script happened to share `LOGICAL_TABLE` before
`ANSWER`, granting the stack bottom-up by accident. Nothing about ORG1 was different.

### Three wrong conclusions, and what they have in common

1. "grants do not register when the content sits on a published Model" -- wrong cause,
   right neighbourhood.
2. "it tracks with object TYPE in that Org" -- a real correlation with the wrong
   explanation: Answers failed because Answers sit on top of a stack, Models did not
   because theirs was already granted or owned.
3. "`fetch-permissions` under-reports group grants" -- **wrong.** The read was accurate
   every time; there was nothing to report.

All three came from treating an API response as the thing to explain, instead of asking
what the product requires. The repo owner supplied the missing premise (Strict Object Mode)
in one sentence.

### The fix

`share_grants` now grants **bottom-up over the whole stack**: the published Tables, then
the published Model, then the migrated content. Ordering is load-bearing -- a content grant
applied before its Model is silently dropped.

---

## BL-152 -- a same-Org migration pairs the tenant's Model with ITSELF and reports READY `Tier 1` -- **FIXED 2026-07-28**

**Filed:** 2026-07-28.
**Source:** found while running the first same-Org (source Org == target Org) test end to
end -- the last of the three supported topologies to be exercised.

`ts migrate audit --source-org ORG1 --target-org ORG1` returned:

```
source_guid  : 9917a017-443c-4cf7-be81-2958d83997c8
target_guid  : 9917a017-443c-4cf7-be81-2958d83997c8   <- the SAME object
readiness    : READY
column_counts: {'MATCHED': 6, 'GAP': 0, 'GAP_BLOCKER': 0, 'BINDING_MISMATCH': 0}
```

### Cause

`discover.find_model_by_name` returned the **first** name match. In the same-Org topology
the Org legitimately holds **two** Models of that name -- its own, and the master published
in from Primary -- and which one came back first was whatever `metadata/search` happened to
list. It returned the tenant's own Model, so the audit compared the source with itself.

Every downstream number then follows: each column matches itself, the rename map is empty,
`validate_apply` has nothing to object to, and the verdict is `READY`.

### Why Tier 1

It is a **silent no-op that passes every gate.** `apply` would run green, write a state
ledger, and move nothing. Verification does not catch it either: the content still works,
because it is still pointed at the Model it always used. It surfaces only when someone
retires the "old" Model at teardown -- the point at which every Answer and Liveboard in the
tenant Org breaks at once, and the backup is the only way back.

Three narrower instances of the same defect were found alongside it, all from the same
name-only assumption:

| Where | What went wrong |
|---|---|
| `audit --all-models` | Swept the published master in as a *source* Model, auditing it against itself. **Measured on ORG1: 12 Models visible, 5 owned** -- the other seven were the master and **six ThoughtSpot system worksheets** (`TS: BI Server`, `Falcon_Monitor_Data_Load_360`, `Credit Usage Worksheet`, ...), all of which landed in the `column-mapping.csv` a human is asked to approve |
| `_classify_scope` (`apply`) | The **source** lookup could equally return the master, so `apply` would migrate the master's own dependents and rename its columns |
| `scan-sets --model <name>` | Could report the master as the tenant's Set blocker, overstating the one number that command exists to produce |

### The fix

**Ownership is the discriminator.** `metadata_header.ownerOrgId` distinguishes the two: the
published master is owned by Primary, the tenant's copy by the tenant. The same field
`list_models` already used for the fleet scan, applied to the one place it was missing.

- `discover.name_matches` returns **all** exact name matches with their `ownerOrgId`,
  because the count is the point.
- `select_source` requires the Org to **own** the Model; `select_target` requires that it
  does **not**, and additionally excludes the source object by GUID.
- Either one **refuses** on genuine ambiguity (`AmbiguousModelName`) rather than picking.
  Both wrong answers here are silent, so guessing is the one thing not to do.
- `exclude_owner_org_id` is passed as `None` when the two profiles differ, because Org ids
  mean nothing across clusters and `Primary` is `0` on both -- excluding by id would refuse
  a legitimate Primary-to-Primary cross-cluster target.
- `apply_plan.find_self_repoint` re-asserts the invariant at plan time. The lookup now makes
  it unreachable; it is kept because the **previous architecture had this guard, the rewrite
  dropped it, and the case came straight back.**
- `find_model_by_name`, `scaffolding_objects` and `bespoke_content` are removed --
  name-only lookup and two dead helpers from the retired lift-and-shift design.

Regression tests were confirmed to fail against the old behaviour with the bug's exact
signature (`target_guid == '9917a017'`, the source) before being taken as passing.

**Verified live** on `nebula-damian-alias`: the same audit now targets the master
(`2a743be3`) and returns `NEEDS_MAPPING` with `Segment` a blocker, where it had returned
`READY` with 6 columns matched. Full record, including the prepared plan and what was
deliberately not run:
`docs/superpowers/verification/2026-07-28-ts-migrate-same-org-topology.md`.

### What this does not fix

The audit now reports `NO_TARGET` in a same-Org run where the master has not been published
into the Org yet. That is correct and actionable, but it means **the same-Org topology
requires the master to be published into the source Org first** -- worth stating in the
runbook, because the Org already contains a same-named Model and an operator may reasonably
assume there is nothing to publish.

---

## BL-153 -- `ts share status --org X` cannot resolve an object NATIVE to Org X `Tier 2` -- **FIXED 2026-07-28**

**Filed:** 2026-07-28.
**Source:** found reaching for `ts share status <liveboard-guid> --org ORG1` to read a
migration's grants back -- the exact use the command exists for.

```
$ ts share status 083fbd06-... --org ORG1 -p nebula-damian-alias
ThoughtSpot API 400 ... {"metadata":"Specify the metadata_type for identifier 083fbd06-..."}
Error: Invalid value: Could not resolve '083fbd06-...'.
       Expected a GUID, or the exact name of one of: LOGICAL_TABLE, LIVEBOARD, ANSWER.
```

The GUID was valid, the object existed, and the Org was named on the command line.

### Cause

`status_cmd` resolved its targets with an **Org-less** client and scoped only the
*permissions read* per Org:

```python
targets = _status_targets(_client_for_org(profile), list(guids), columns)   # no org
for org_name in orgs:
    client = _client_for_org(profile, org_name)                            # org, too late
```

`metadata/search` is Org-scoped, so an object **native to a tenant Org is invisible to the
default-Org client** -- it cannot be resolved at all. This is the **same bug already fixed in
`ts share export` on 2026-07-27**, which is why `_resolve_object_in_orgs` exists. `status` was
simply missed at the time.

It matters because it breaks the read-back half of the pipeline exactly where a migration
needs it: confirming that migrated content in a tenant Org carries the grants it should. And
the error blames the identifier, so it reads as "you typed the GUID wrong" rather than "I
looked in the wrong Org" -- the same misdirection as BL-147.

**Blast radius beyond migration.** `ts-security-columns/SKILL.md` calls
`ts share status {guid} --columns --org "{org}"` at two steps, and
`references/mechanism-decision.md` names it as the check for "does the audience hold object
access?". Those worked for a Primary-owned published table (visible to the default Org) and
failed for a **tenant-owned** one -- so the mechanism-decision check was unavailable for
exactly the objects a tenant defines CLS on.

### Second defect found alongside: the probe cried wolf

`_find_object` probes untyped first, which the platform rejects with a 400 whenever the
identifier is not in the client's Org -- i.e. **on every tenant-Org lookup**. `_try_search`
correctly swallows it, but `client.py` had already printed
`ThoughtSpot API 400 ... Specify the metadata_type` to stderr. So a *successful* report came
with a red API error in front of it. A probe whose failure IS the answer must not announce a
fault. `_search` gained a `quiet` flag that passes `raise_for_status=False`; only probes use
it, and a genuine search failure is still loud and fatal.

### A trap worth recording

Adding a kwarg to the `client.post` call broke five test doubles whose signature was
`post(self, _path, json=None)`. Because `_try_search` catches **everything**, the resulting
`TypeError` did not surface as an error -- every lookup silently "found nothing". Reading
`resp.ok` had the same shape: `AttributeError` on any non-`requests.Response`, swallowed the
same way. `ok` is now read via `getattr(resp, "ok", True)` and the doubles take `**_kw`.

**The blanket `except (Exception, SystemExit)` in `_try_search` converts programming errors
into empty result sets.** Its docstring rightly warns against narrowing it to
`except Exception` (that reintroduces a crash), but the cost is that nothing in this path
fails loudly. Any future change to what `_search` calls or reads must be exercised against a
real response object.

### Verified

Live on `nebula-damian-alias`: `ts share status 083fbd06-... --org ORG1` now exits 0, prints
no stderr diagnostic, and returns 5 rows showing `MIGTEST_VIEWERS` with `READ_ONLY` plus
`guest1`/`guest4` inheriting it. The three regression tests were confirmed to **fail against
the old behaviour** (with `__pycache__` cleared, after a stale `.pyc` briefly made a restored
file look broken).

---

## BL-154 -- Phase D's four residual verification gaps `Tier 2`

**Filed:** 2026-07-28.
**Source:** written up at the repo owner's request when pausing the migration work, so the
gaps are tracked rather than living in a conversation.
**Status:** OPEN. **The code is built and Phase D is functionally complete** -- these are
paths that have not been *exercised*, which is a different and lesser thing than unbuilt.

Filed as one item rather than four because they share a cause: each needs cluster or fixture
state that does not exist yet, and they would be scheduled together in one session with the
right environment.

| Gap | What is verified today | What it needs | Risk if wrong |
|---|---|---|---|
| **Same-Org `apply` (the WRITE)** | `audit` and the full `--dry-run` plan, live (BL-152 record) | The repo owner's go-ahead -- it rewrites ORG1 in place, and ORG1 is the source side of the fixture that has caught six real bugs | An in-place `--no-create-new` import of rewritten content behaving unlike the create-fresh path |
| **Published Model WITH RLS** | Only the **refusal** path of the tenant-isolation check | An RLS rule on the master -- which runs straight into **BL-144**, where a column-less RLS expression imports `OK` and silently WIPES existing rules | The happy path is the one every real tenant takes, and it is the security-shaped one |
| **`client_state_v2` rewriting** | The parse-rewrite-reserialise transform, by unit test over a hand-built blob | A chart **customised in the UI** -- a TML-created chart carries no such blob at all, so the path cannot be reached from fixtures the tooling builds | A substring pass over that blob corrupts unrelated chart state; the rewrite parses it precisely to avoid that, and the precision is what is untested |
| **Cross-cluster topology** | `import_mode` derives it, and the Org-id exclusion is deliberately skipped there (BL-152) | A second cluster with the master published on it | Org ids are meaningless across clusters and `Primary` is `0` on both, so the fallback is GUID exclusion alone |

Also unverified, and much smaller: **that ORG2's pre-existing aliases still RENDER** after a
later wave's merge. Their presence in the stored document is proven by round-trip export
(`2026-07-28-ts-migrate-wave-aliases.md` §4); nobody has looked in an ORG2 session. ORG1's
render **is** confirmed, so the mechanism works -- this is the preservation half's last inch.

### Why this is Tier 2 rather than Tier 1

Nothing here is known-broken. But note what the session that produced Phase D actually shows:
**every real bug in it was found by running something, and none by reasoning or unit tests** --
two Tier 1 defects (BL-150, BL-152) that unit tests passed straight through, both silent
successes. So "built and unit-tested" has a measured track record here, and it is not good.
These four are where the next one would be.

---

## BL-155 -- the security spec's Phase D additions are still unbuilt `Tier 2`

**Filed:** 2026-07-28.
**Source:** carried forward from `docs/superpowers/specs/2026-07-26-ts-security-sharing-design.md`
§5, which lists migration-side work that Phase D did not include.
**Status:** OPEN, and genuinely unbuilt -- distinct from BL-154, which is untested-but-built.

Three pieces:

1. **A `CSR_BLOCKER` audit status.** A tenant table carrying Column Security Rules cannot be
   migrated blindly: **CSR is scoped to the Org it was defined in and does NOT travel with
   publication** (live-verified 2026-07-27 -- the owning Org's update succeeds and is enforced
   there, while a tenant Org the table is published to keeps the restricted column fully
   visible). So a migration that moves content onto a published master silently *widens* column
   access. `audit` should classify and refuse it the way it refuses `SET_BLOCKER`.
2. **`--csr map-to-cls`.** The mechanism is chosen by AUDIENCE per (Org, object), so migrating
   onto a published master can require translating CSR to column-level sharing. `ts security
   column-rules` and `ts share` both exist; what is missing is the migration-time translation.
3. **CSR TML preservation.** CSR exports as a sibling TML document (`column_security_rules`),
   exactly like `column_alias`. The rewrite does not carry it, so a migrated table would lose
   its rules -- the same class of silent loss as BL-150's sharing, reached from a different
   direction.

**Why it matters:** every failure mode here is a column becoming *more* visible, silently.
That is the one direction a security change must never drift in by accident.

---

## BL-156 -- two command modules crossed the file-size warn line `Tier 3`

**Filed:** 2026-07-28.
**Status:** OPEN. Advisory only -- the gate warns at 500 and fails at 1000, and 30 modules
already warn.

| Module | Lines | Was |
|---|---|---|
| `commands/migrate.py` | 654 | 487 before BL-152 |
| `commands/share.py` | 516 | 484 before BL-153 |

Both crossed while fixing Tier 1/2 bugs, and in both cases the added lines are mostly the
"why" comments that record what the bug was -- trimming them to get under the line would
delete the thing worth keeping.

**The established pattern is a module-per-concern split, not shorter comments.**
`share_planning.py` was already split out of `share.py` under this same gate, and
`publish_planning.py` out of `publish.py`. `commands/migrate.py` has the same natural seam:
read-only `audit` / `scan-sets` / `aliases` in one module, destructive `apply` / `rollback` in
the other. Doing it needs care rather than effort -- the last two renderer patches in this
family landed in dead code paths because a refactor had moved the live one.

---

## BL-157 -- Aggregates CLI gap: `preview-names`, `widen-rls`, force-add-aware `recommend`, drop the private imports `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, findings 5.1 + 5.4.
**Affects:** `agents/cli/ts-object-model-aggregates/SKILL.md` (Steps 5d/5e/6d),
`tools/ts-cli/ts_cli/commands/aggregate.py`, `tools/ts-cli/ts_cli/aggregate/rls.py`,
`tools/validate/check_patterns.py`.
**Status:** OPEN.

`ts-object-model-aggregates` has the executor import PRIVATE ts-cli internals directly --
exactly the anti-pattern `.claude/rules/ts-cli.md` exists to prevent, and it landed
unnoticed because check_patterns.py only ever looked for `requests.*`:

- Step 5d (SKILL.md:388) imports `ts_cli.commands.aggregate._aggregate_name` to compute
  the deterministic proposed aggregate name for the curve display.
- Step 5e (SKILL.md:445) imports `ts_cli.aggregate.rls.add_rls_columns_to_candidate` to
  force-add a missing RLS column to a candidate's grain.

The leading underscore means no contract protects either call -- a ts-cli refactor can
pass every unit test and still silently break the shipped skill the moment either
function's signature or module path changes.

**Companion hazard (from finding 11 -- codification):** SKILL.md ~460-467 already warns in
prose that re-running `ts aggregate recommend` after a force-add silently discards the
widened grain, because `recommend` regenerates `candidates.json` wholesale from
`signatures.jsonl` and never reads the existing force-added dimensions back in. Today
that is a warning to the reader, not a guard in the code.

**Fix, four parts:**
1. Add `ts aggregate preview-names` -- wraps `_aggregate_name` as a public command so
   Step 5d calls the CLI instead of importing the private function.
2. Add `ts aggregate widen-rls --candidate <id>` -- wraps `add_rls_columns_to_candidate`
   as a public command for Step 5e's force-add path.
3. Make `recommend` force-add-aware: read back any already-force-added dimensions from
   the existing `candidates.json` (the same way `_merge_prior_agg_rows` already reads
   back profiled row counts) so a re-run doesn't discard a widened grain.
4. Let `ts tables create` accept a single spec object (not only a JSON array) or add
   `--file`, removing the `python3 -c` array-wrap shim in SKILL.md Step 6d (line ~659).

**Note:** `check_patterns.py` carries a dated allowlist entry for this SKILL.md's two
`ts_cli` imports (PR #405, extending rule 8 / finding 5.2) -- remove that entry when this
item ships and the imports are replaced.

**Target:** next `ts-object-model-aggregates` touch -- the audit's own Follow-ups section
names this as the next scoped unit of work once the migrate-engine/harness/mapping wave closed.

---

## BL-158 -- Extract the cascade-drop retry loop into shared import machinery `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, finding 11.2.
**Affects:** `tools/ts-cli/ts_cli/commands/tableau.py` (`_collect_cascade_victims`, line
~436, and its retry loop around line ~537); `ts-convert-from-qlik`, `ts-convert-from-powerbi`,
`ts-convert-from-sisense` SKILL.md; the shared import/build-model machinery.
**Status:** OPEN.

Tableau's build-model import path is the only converter where a rejected-formula cascade
(a formula referencing another formula that gets dropped for validation reasons) is
walked deterministically: `_collect_cascade_victims` computes the transitive closure of
what else breaks when a formula is excluded, then the import retries without those
victims. `qlik.py`, `powerbi.py`, and `sisense.py` have no equivalent machinery -- their
SKILL.md files instead instruct the LLM to walk the cascade by hand on import failure.
An LLM re-deriving the closure from rejection error text will miss a victim that isn't
directly named in the message (a formula whose only reference to the dropped one is
transitive) -- exactly what the codified version gets right.

**Approach:** extract the collect-victims + retry loop into shared import machinery
reusable across converters -- e.g. a `--prune-rejected` flag on the generic
`ts tml import` / build-model import path, or a shared helper in `io_helpers.py` any
converter's build-model command can call. Wire qlik/powerbi/sisense's build-model
commands to it and delete the manual-loop prose from their SKILL.md files.

**Target:** next touch of qlik/powerbi/sisense build-model, or a standalone
shared-import-machinery pass.

---

## BL-159 -- Canonical migration-report status vocabulary `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, finding 11.5.
**Affects:** qlik/sisense/powerbi (`Migrated`/`Approximated`/`NEEDS REVIEW`/`Skipped`),
looker (`translated`/`approximate`/`omitted`/`Untranslatable`), tableau
(`Migrated`/`Partial`/`Parked`/`Not migrated`) migration-report generation + each
skill's `mapping.json`.
**Status:** OPEN.

Three incompatible status vocabularies exist across the five converters for the same
underlying concept -- whether a construct migrated cleanly, migrated approximately,
needs manual review, or was dropped entirely. The vocabulary is the cross-converter
contract written into each skill's `mapping.json` / migration-report template, so a
reader (or a future cross-converter tool) has to learn three synonym sets for the same
four ideas.

**Approach:** extract a canonical status-vocabulary reference to
`agents/shared/references/` (four canonical states, one line each defining what
qualifies for it). Adopt the qlik/sisense/powerbi four-state set
(`Migrated`/`Approximated`/`NEEDS REVIEW`/`Skipped`) as canonical, since it is already
shared by three of the five converters, and converge looker and tableau onto it the
next time either skill's migration-report section is touched -- not a standalone
rename-only PR.

**Target:** next edit of looker's or tableau's migration-report section.

---

## BL-160 -- migrate/ts-cli pagination and per-dependent batching gaps `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, findings 14.1 + 14.2.
**Affects:** `tools/ts-cli/ts_cli/migrate/discover.py` (`dependents_through_views`, line
347), `tools/ts-cli/ts_cli/migrate/__init__.py:30`, `tools/ts-cli/ts_cli/commands/migrate.py:457`,
`tools/ts-cli/ts_cli/commands/orgs.py:62`, `tools/ts-cli/ts_cli/commands/users.py:67,130`.
**Status:** OPEN.

Two related performance gaps in the post-2026-07-22 migrate delta:

1. `discover.py:347`'s `dependents_through_views` calls the batched `subtypes_by_guid`
   helper ONE GUID AT A TIME inside the frontier walk, violating the module's own stated
   API budget -- and both callers (`migrate/__init__.py`'s `run_audit`,
   `commands/migrate.py`'s audit command) immediately re-fetch the same subtypes
   afterward in one batched call anyway, so the per-dependent calls are pure waste. A
   tenant with 200 dependents costs ~201 `metadata/search` calls per Model instead of
   ~5 on a fleet-wide scan. **Fix:** batch `subtypes_by_guid` once per frontier LEVEL
   (collect every `dep_guid` discovered at that depth, one batched call, then decide
   which are `VIEW_BASED` for the next frontier) instead of once per dependent.
2. The 2026-07-22 audit's finding 14.1 was recorded as closed by PR #283, but that PR
   only bumped `metadata/search`'s default page size to 500 -- `orgs.py:62` and
   `users.py:67` (users) / `:130` (groups) still paginate at `page_size=50`, and
   `ts-setup-tenancy` / `ts-publish-orgs` both enumerate orgs/users/groups through these
   paths. Same one-line fix (bump to 500, matching the metadata-search precedent);
   filing as its own tracked entry since the prior routing record incorrectly reads this
   as fully closed.

**Target:** next migrate/ts-cli performance pass, or bundled with the BL-157 aggregates
CLI work if convenient.

---

## BL-161 -- Tools quality cluster: SQL-tokenizer dedup, subprocess import path, validator-helper dedup, dead `--all` flag `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, findings 4.3, 4.4, 4.6, 1.3.
**Affects:** `tools/ts-cli/ts_cli/commands/sv_sql.py`, `tools/ts-cli/ts_cli/databricks/mv_sql.py`,
`tools/ts-cli/ts_cli/io_helpers.py` (`run_tml_import`), `tools/ts-cli/ts_cli/commands/snowflake.py:591`,
`tools/ts-cli/ts_cli/commands/databricks.py:436`, `tools/validate/check_secrets.py`,
`check_tml.py`, `check_sv_yaml.py`, `tools/smoke-tests/`, `tools/ts-cli/ts_cli/commands/model.py`
(`_select_formulas` / `promote-formula --all`).
**Status:** OPEN.

Four independent cleanups bundled because each is small and touches the same "tools
quality" surface:

1. `sv_sql.py` and `databricks/mv_sql.py` duplicate ~150 lines of SQL tokenizer/parser
   machinery (`tokenize()`, `_Cursor`, date-literal constants, shared construct
   handlers) -- a tokenizer bug fixed in one silently persists in the other. Extract to
   a shared `sql_common.py`. **Must stay stdlib-only** (no third-party deps) to preserve
   Genie-vendorability -- `agents/databricks/` concatenates modules for Genie Code,
   which can't `pip install`.
2. `io_helpers.py:76`'s `run_tml_import` shells out via
   `bash -c "source ~/.zshenv && ts tml import ..."` -- hard-requires `~/.zshenv` and
   `ts` on the subprocess PATH, so it fails outright on fresh Linux installs and on
   Windows (both declared-supported platforms). An in-process alternative already
   exists (`commands/tml.py` calling through `ThoughtSpotClient` directly; keyring-backed
   auth makes the zshenv sourcing unnecessary). Callers: `snowflake.py:591`,
   `databricks.py:436`. Switch both to the in-process path.
3. `_extract_yaml_blocks` / `_get_staged_files` are cloned across 3+ validators
   (`check_secrets.py`, `check_tml.py`, `check_sv_yaml.py`); a ~26-line
   model-GUID-resolution block is cloned across 2+ smoke tests. Move into a shared
   `tools/validate/_dirs.py`-style module and `tools/smoke-tests/_common.py`'s
   `resolve_model()`, respectively.
4. `ts model promote-formula --all` is a dead no-op: `model.py`'s `_select_formulas`
   takes an `all_flag` parameter but never reads it, and with neither `--formula` names
   nor `--all` given, every formula is silently promoted anyway. Either honor the flag
   (require one of names/`--all`) or remove it and document the promote-all default
   explicitly.

**Target:** opportunistic, next touch of any of the files above.

---

## BL-162 -- Repoint or retire the `tableau.py` file-size ALLOWLIST justification `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, finding 4.5.
**Affects:** `tools/validate/check_file_size.py` (ALLOWLIST entry for `commands/tableau.py`),
`tools/ts-cli/ts_cli/commands/tableau.py` (1,675 lines).
**Status:** OPEN.

`check_file_size.py`'s ALLOWLIST entry for `commands/tableau.py` cites BL-089 as its
justification, but BL-089 is archived Done (`backlog-archive.md` -- "Multi-table
build-model generate-mode support"), and the file has since grown to 1,675 lines with no
live backlog item tracking a split. The ALLOWLIST's own rule -- every entry needs a
backlog cross-reference that is still open -- is silently unsatisfied.

Two paths, either closes it:
- **(a)** This item becomes the live cross-reference and schedules the per-flow split
  the same way `share_planning.py` was split out of `share.py` and `publish_planning.py`
  out of `publish.py` under the same file-size gate (BL-156 documents that pattern for
  `migrate.py`/`share.py`) -- the natural seam here is parse/classify vs.
  build-model/build-liveboard vs. the cascade-retry import machinery (BL-158).
- **(b)** If a split isn't planned, amend the ALLOWLIST comment to an honest permanent
  exemption instead of a stale backlog pointer.

Optionally extend `check_file_size.py` to assert ALLOWLIST BL references resolve to an
OPEN backlog item -- would have caught this drift automatically.

**Target:** opportunistic -- next time `tableau.py` is touched for unrelated work, or a
standalone split PR.

---

## BL-163 -- Validator test coverage + qlik smoke fixture-fail-hard `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, findings 6.1 + 6.2.
**Affects:** `tools/validate/` (`check_consistency.py`, `check_runtime_coverage.py`,
`check_coverage_matrix.py`, `check_skill_naming.py`, `check_no_inline_requests.py`,
`check_file_size.py`, `check_sv_yaml.py`, `check_version_sync.py`, `check_yaml.py`,
`generate_parity.py`), `tools/validate/tests/`, `tools/smoke-tests/smoke_ts_convert_from_qlik.py`.
**Status:** OPEN.

Ten `tools/validate/` gates have zero tests of their own -- including five non-trivial
ones (`check_consistency.py` at 295 lines, `check_runtime_coverage.py`,
`check_coverage_matrix.py` including its date-enforcement logic,
`check_skill_naming.py`'s `FAMILY_PATTERNS` table, `check_no_inline_requests.py`).
BL-077 (done, PRs #296/#297) added known-bad-fixture self-tests for 18 OTHER
validators -- this is the same treatment for the stragglers it didn't reach. A
regression that silently stops one of these ten from flagging still exits 0, exactly
the failure mode BL-077's own motivating finding (F2, `check_skill_versions`) described.

Separately: `smoke_ts_convert_from_qlik.py` SKIPs (prints "SKIP -- fixture not found"
and returns 0) when its repo-bundled `.qvf` fixture is missing, applying the
live-instance-dependency convention (skip when no live instance) to a fixture that
should always be present in a checkout -- a regression that deletes or corrupts the
fixture goes unnoticed. The liveboard step also tolerates an empty sheet result
silently. **Fix:** fail (nonzero) on a missing fixture, and assert the fixture's known
sheet count rather than accepting whatever comes back.

**Approach:** test the straggler validators highest-line-count first
(`check_consistency.py`, then `check_runtime_coverage.py` / `check_coverage_matrix.py`),
following the `test_known_bad_fixtures.py` pattern BL-077 established (git-initialised
`tmp_path` repos via the existing `_init_git()` helper).

**Target:** opportunistic, highest-line-count validator first.

---

## BL-164 -- `snowflake-connector-python` 4.x compat check and floor bump `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, finding 16.3.
**Affects:** `tools/ts-cli/pyproject.toml`.
**Status:** OPEN.

`snowflake-connector-python>=3.13.1` (the current floor) now resolves to 4.7.1 on a
fresh install -- a silent major-version crossing nothing in the repo has deliberately
tested against. Fresh-resolve is defensible day to day given the per-PR CVE gate, but a
major version bump crossing unnoticed deserves a deliberate compatibility check rather
than passive trust in "tests still pass": review the 3.x -> 4.x changelog for breaking
changes relevant to `load.py`'s `_connect_python` (key-pair auth path) and
ts-profile-snowflake's connection test, run the Snowflake-profile smoke tests against
4.x explicitly, then set an explicit floor (`>=4,<5`) once verified rather than leaving
the range open-ended.

**Related but separate:** BL-106 tracks the Python 3.11 floor bump (also
October-adjacent, since Python 3.10 EOLs 2026-10) -- the two are batchable in the same
PR if convenient (both are dependency-floor bumps with a similar Oct-2026 trigger) but
are independent changes; this item does not require BL-106 to land first.

**Target:** no fixed date -- before Python 3.10 EOL (2026-10) is a reasonable anchor,
since a floor-bump PR is already scheduled for BL-106 around then.

---

## BL-165 -- Small residuals: dependency-types sync check, check_secrets scope, Tableau 2026.2 investigation `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 full audit, findings 7.2, 18.4 (residual), 13.14.
**Affects:** `scripts/pre-commit.sh` (dependency-types.md sync nudge), root `CLAUDE.md`
(change-impact map wording), `tools/validate/check_secrets.py`,
`.claude/rules/security.md`, `agents/shared/mappings/tableau/tableau-tml-rules.md`.
**Status:** OPEN.

Three independent small items:

1. dependency-types.md sync is a TTY-only soft nudge in `pre-commit.sh` (line ~269) with
   no CI counterpart, while root `CLAUDE.md`'s change-impact map words the rule as "must
   stay in sync" -- agent-driven (non-TTY) commits, the dominant mode for this repo, get
   zero signal either way. Promote the mechanically-checkable component (does
   dependency-types.md's status table/hierarchy still mention every status
   ts-dependency-manager's Step 4/5 emit) to a `check_*.py` validator, or soften
   CLAUDE.md's wording to describe what's actually enforced.
2. `check_secrets.py` only scans tracked/staged files; the permission-capture
   inline-credential class documented in `security.md` (Claude Code's
   `permissions.allow` captures the full command text -- including any inlined bearer
   token or Snowflake keypair JWT -- into the gitignored `.claude/settings.local.json`)
   is invisible to it by construction. The two live stale entries found by the
   2026-07-29 audit were already deleted and the rule is now documented in
   `security.md` (PR #402); optionally extend `check_secrets.py` to also scan
   `.claude/settings.local.json` when present, so a longer-lived captured token
   wouldn't sit unnoticed.
3. Tableau 2026.2 Composable Data Sources let a workbook relate multiple *published*
   data sources into one model; `tableau-tml-rules.md`'s one-model-per-datasource rule
   is silent on composed/PDS-backed datasources and the parser targets federated
   physical relations only. TWB serialization for this feature is unverified --
   investigate with a real 2026.2 workbook before changing any mapping or parser logic
   (park note: DATA-BLOCKED, same shape as BL-091 -- not a known code gap yet).

**Target:** opportunistic -- (1)/(2) are validator/doc touches; (3) needs a 2026.2
workbook to become actionable.

---

## BL-166 -- `custom_extensions`-style loss stash for the ts-convert-* pairs `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 Apache Ossie converter review
(`docs/reviews/2026-07-29-ossie-converter-learnings.md`), finding F11.
**Affects:** `agents/cli/ts-convert-to-snowflake-sv/` (SKILL.md +
`references/coverage-matrix.md`), `agents/cli/ts-convert-from-snowflake-sv/`,
`agents/cli/ts-convert-to-databricks-mv/`, `agents/cli/ts-convert-from-databricks-mv/`,
`tools/ts-cli/ts_cli/` (`build-sv`/`parse-sv`, `build-mv`/`parse-mv`), `tools/ts-cli/tests/`.
**Status:** OPEN.

41 limitation rows across the four coverage matrices (13 to-SF, 8 from-SF, 10 to-DBX,
10 from-DBX) resolve to "documented in the Unmapped Properties Report, then gone" --
`format_pattern`, `geo_config`, `column_groups`, `default_date_bucket`, `custom_order`,
locale aliases and partial `ai_context` on the way out; `ACCESS_MODIFIER: PRIVATE`,
table-level synonyms, `is_enum` and sample values on the way in. A TS->SV->TS round trip
cannot recover any of them and nothing in the repo measures how much is lost. Upstream's
databricks converter solves the identical problem with a `write_stash`/`read_stash` pair
over `custom_extensions`, and asserts the result as parsed-dict equality with zero
normalization.

The sharpest part of the finding: **we already ship the plumbing and don't use it for
preservation.** `ts-convert-to-snowflake-sv` emits `with extension (CA='{ca_json}')` and
`ts-convert-from-snowflake-sv` parses that same clause -- but the from-side coverage matrix
row 31 records the handling as "Parsed only ... Type confirmation; not mapped to TML". A
versioned, ThoughtSpot-keyed JSON payload written on export and read on import is a small
change to two CLI commands that would make the pair lossy-by-declaration rather than
lossy-by-default.

**Approach** -- the five details below are all load-bearing, not polish (each verified in
the review; section refs are to the report):

1. The payload is a **serialised JSON string**, never a nested object (report section 1 #1:
   `osi-schema.json` constrains the equivalent field to a string with
   `additionalProperties: false`; our own DDL clause is a quoted scalar).
2. Version it with a `_v` marker and **merge into an existing entry** rather than appending
   a second one.
3. Restore as **stash-if-present-else-derive** (report section 2.3). A stash-only design
   breaks on any input the converter did not itself produce -- i.e. every hand-written SV
   or MV, which is most real inputs.
4. Golden and round-trip comparisons must `json.loads` both sides before comparing
   (upstream's `canon()` helper): serialised key order is not stable.
5. Give the round trip two explicit equality bars -- a *documented-lossy* one that
   normalizes known drops through a named helper (upstream's `strip_dropped`), and a
   *lossless* one asserting parsed equality with no normalization at all.

**Scope:** start with the Snowflake pair, where the extension clause already exists on both
sides. Databricks MV has no equivalent carrier identified yet, so that half needs a
placement decision first. Then update each coverage-matrix limitation row to state
*preserved-via-stash* vs *dropped*.

**Validator promotion this unlocks (file once the mechanism exists):** extend
`check_coverage_matrix.py` so every limitation row must declare preserved-vs-dropped --
per the two-bucket rule, the promotion is the point, but it cannot precede the mechanism.

**Target:** next converter edit on the Snowflake pipeline, or bundled with BL-100 (bring
remaining converters to the DBX-from standard, Snowflake pipeline first).

---

## BL-167 -- Record (or change) the to-direction's never-hard-error-on-loss posture `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 Apache Ossie converter review
(`docs/reviews/2026-07-29-ossie-converter-learnings.md`), finding F14.
**Affects:** `agents/shared/schemas/ts-model-conversion-invariants.md`, the four
`references/coverage-matrix.md` files, `agents/cli/ts-convert-to-snowflake-sv/SKILL.md`,
`agents/cli/ts-convert-to-databricks-mv/SKILL.md`.
**Status:** OPEN.

Our from-direction hard-errors on constructs it cannot represent (MV-on-MV fail-loud,
`unsupported[]` + exit 1, the joinless-SV decision prompt), but our **to-direction never
hard-errors over information loss**: every unmapped construct is a warn-and-drop into the
Unmapped Properties Report, and the only exit-1 gates there are structural
(`ts snowflake lint-ddl` errors). Upstream's databricks import direction takes the opposite
line deliberately -- a condition-less/cross join, a non-equi `on`, a reserved/duplicate join
name or an unsupported input version all raise `ConversionError`, on the explicit grounds
that losslessness is that direction's purpose; the single drop-with-warning exception is a
wildcard column, which has no field identity to preserve.

There is a defensible reason for our asymmetry -- the to-direction ends at a mandatory
Step 10 human checkpoint that shows the report before anything is written -- but it is
currently an accident of how the two directions grew rather than a decision on record.

**Approach:** state the posture explicitly as a short subsection in
`ts-model-conversion-invariants.md` (where the cross-converter rules already live, alongside
I1-I12/N1/PT1), naming which loss classes are warn-and-drop **by design** and which, if any,
should become hard errors. Cheaper and sharper after BL-166, because a stash changes the
answer: a construct that can be preserved should never have been a drop in the first place.

**Target:** opportunistic -- with BL-166, or the next edit to the invariants file.

---

## BL-168 -- Property-based tests for the ts-cli converter builders (dual-driver) `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 Apache Ossie converter review
(`docs/reviews/2026-07-29-ossie-converter-learnings.md`), finding F15.
**Affects:** `tools/ts-cli/tests/`, `tools/ts-cli/pyproject.toml` (`dev` extra),
`.github/workflows/validate.yml`.
**Status:** OPEN.

All 3,808 cases collected from `tools/ts-cli/tests/` are example-based. There is no
`hypothesis` dependency or import anywhere in the repo and it is absent from
`tools/ts-cli/pyproject.toml`'s `dev` extra (`pytest`, `PyYAML`, `radon`, `vulture`,
`pip-audit`). Upstream's databricks converter runs Hypothesis at 300 examples per property.

The gap matters more than the raw absence suggests because **the properties are already
written**: `agents/shared/schemas/ts-model-conversion-invariants.md` states I1-I12, N1 and
PT1 -- 14 rules -- as universally-quantified statements over generated Model TML ("for every
entry in `formulas[]` there must be a corresponding entry in `columns[]`..."). What is only
partly built is the checker: `tools/ts-cli/ts_cli/tml_lint.py` implements **6 of the 14** --
I1, I2, I4, I5, I8 and I12, plus a guid-placement rule. So today six invariants are checked,
and only against the handful of documents a fixture or a live run happens to produce; the
other eight are enforced by author discipline alone.

**Approach** -- two components, sequenced, not one:

1. **The generator.** A strategy producing arbitrary in-subset `parsed.json` documents,
   asserting `lint_tml(build_model(parsed, translated, tables)) == []`. Even confined to the
   6 invariants lint already covers, this tests the **builder** rather than the documents our
   fixtures happen to contain -- a materially stronger claim, and the duplicate-`column_id`
   class (I8, ts-cli v0.92.0, shipped in `from-snowflake-sv` 1.19.0 / `from-databricks-mv`
   1.10.0) is exactly the kind of bug it would have caught by construction instead of the
   hard way. This half is worth doing on its own.
2. **Checkers for the assertable remainder.** I3, I6, I9, I10, I11 and N1 are mechanically
   assertable over emitted TML but have no `tml_lint.py` check today, so a property test
   cannot exercise them until one exists -- each is a small addition to the same module, and
   each also strengthens the existing pre-import `ts tml lint` gate independently of any
   property test. I7 (a MANDATORY consult gate on the author) and PT1 (a flag-for-review
   rule) are **not** assertions over output and stay outside both lint and any property test;
   they are deliberately out of scope here.
3. Restrict generation to the **round-trippable subset** rather than generating everything
   and excepting the failures -- upstream's decision, and what stops a property test
   degenerating into a list of known-bad shapes.
4. **The dual driver is load-bearing here, not optional polish.** `validate.yml` installs
   `pytest pyyaml radon pip-audit` on its 3.12 job and only `pytest pyyaml` on the
   3.10/3.11/3.13/3.14 matrix legs, so a Hypothesis-only test would be silently skipped on
   every leg as configured today, and adding the dependency to the 3.12 job alone still
   leaves four legs uncovered. Mirror upstream: `pytest.importorskip("hypothesis")` plus a
   hand-rolled seeded `Rnd` implementing the same interface, so the same properties run
   either way.

**Validator promotion this unlocks (file once the first property test exists):** assert that
any test importing `hypothesis` has a seeded counterpart, or that `hypothesis` is installed
on every CI leg.

**Target:** next ts-cli converter-builder change. Splittable: the generator over the 6
already-checked invariants (item 1) plus the seeded driver (item 4) is the smaller first
increment and delivers value alone; the six new lint checks (item 2) can land incrementally
after it, or opportunistically whenever `tml_lint.py` is next touched.

---

## BL-169 -- Vendor-neutral TPC-DS fixture corpus (Phase-3-coupled) `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 Apache Ossie converter review
(`docs/reviews/2026-07-29-ossie-converter-learnings.md`), finding F24.
**Affects:** upstream `converters/thoughtspot/tests/fixtures/` (Phase 3); in this repo,
`tools/ts-cli/tests/fixtures/` and `agents/shared/worked-examples/` only if the corpus is
mirrored inward at Phase 5.
**Status:** OPEN.

Our fixtures are richer and better grounded than upstream's -- `agents/shared/worked-examples/`
holds 4 Snowflake and 3 Databricks end-to-end conversions that `agents/shared/CLAUDE.md`
makes normative because each was verified against a live instance -- and they do recur across
converters: the Dunder Mifflin Sales & Inventory schema is the shared spine of three worked
examples (to-snowflake-sv, from-snowflake-sv, to-databricks-mv), with the same model object
reused again as the target of two Tableau set examples. What is missing is a
**vendor-neutral, ecosystem-shared** corpus. Dunder Mifflin is ThoughtSpot-shaped and
repo-local, so however many of our converters it exercises it can never make one of them
comparable against an upstream converter -- and there is no TPC-DS anywhere in the repo.
Upstream's `tpcds_ossie.yaml` / `tpcds_metric_view.yaml` pair (and
`examples/tpcds_semantic_model.yaml`) is the schema the whole ecosystem is compared on.

**Why this is Phase-3-coupled rather than a general repo improvement:** TPC-DS only buys
comparability once there is something to compare against, i.e. the Phase-3
`converters/thoughtspot/` package -- whose spec already calls for a `tpcds_*` fixture pair.
Adopting it here first would add a fixture none of our converters is measured against.

**Approach:** take `tpcds_ossie.yaml` verbatim as the Phase-3 from-Ossie input fixture and
assert the emitted Model TML against a golden -- our first fixture shared with anything
outside this repo, and so our first cross-ecosystem comparability. Note that upstream CI is
offline and cannot depend on our CLI, so the `ts tml lint` pass over the emitted TML belongs
in local development and at Phase-5 back-port time, not in the upstream workflow (the report
states the `ts tml lint` assertion without drawing that boundary). Then decide at Phase 5
whether the TPC-DS Model TML also belongs in `agents/shared/worked-examples/`.

**Target:** with the Phase-3 converter's first test PR -- see
`docs/superpowers/specs/2026-07-29-ossie-thoughtspot-converter-design.md`, Phase 3.

---

## BL-170 -- Live-verify four internal ground-truth conflicts in the ThoughtSpot formula references `Tier 2`

**Filed:** 2026-07-29.
**Source:** the `docs/ossie/ts-osi-function-mapping.md` review on the
`feat/ossie-converter-design` branch -- writing one row per Ossie function forced a
side-by-side read of every ThoughtSpot formula reference we ship, which is what surfaced
these. Cross-referenced from that document's *Rows live-confirmed — 2026-07-29* section
(named *Rows pending live confirmation* until this entry was resolved).
**Affects:** `agents/shared/schemas/thoughtspot-formula-patterns.md`,
`agents/shared/mappings/tableau/tableau-formula-translation.md`,
`agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md`,
`agents/shared/mappings/qlik/qlik-thoughtspot-formula-translation.md`, and any converter
whose emitter branches on these functions.
**Status:** RESOLVED 2026-07-29 (live-verified on se-thoughtspot; docs corrected in
`fix(shared): BL-170 — live-verified function nativeness corrections`).

**Result — all four settled, and every "native" claim lost:**

| # | Function(s) | Verdict | Which side was wrong |
|---|---|---|---|
| a | `replace` | **NOT native** — `Search did not find "replace ("` | `thoughtspot-formula-patterns.md` + the Databricks/Snowflake/Qlik/Looker mappings. The Tableau mapping was right. |
| b | `starts_with` / `ends_with` | **NOT native** — both rejected | `thoughtspot-formula-patterns.md` + the Databricks/Snowflake/Qlik mappings. The Tableau mapping was right. |
| c | `ltrim` / `rtrim` | **NOT native** — and neither is `trim` | The Databricks/Snowflake/Qlik mappings claimed all three. The Qlik file's *conclusion* (no one-sided trim) was right but its premise (`trim` is two-sided) was also wrong. |
| d | `in` delimiter | **Curly braces required** — `in ( ... )` is rejected with `Expecting one of the valid keywords, such as, "ts_var", "{"` | `thoughtspot-formula-patterns.md` + the Snowflake/Qlik mappings. The Tableau mapping was right. |

**Bonus finding (outside the four questions):** `trim` is **not** a native ThoughtSpot
function either. It surfaced because `trim` was used as a known-good *control* and failed;
`concat`, `substr`, `strlen`, `strpos` and `contains` passed as controls, and `upper`
failed as expected, so the method was sound. Every reference mapping a source `TRIM()` to
a bare `trim ( )` was corrected in the same pass.

Net effect: `thoughtspot-formula-patterns.md` — the file CLAUDE.md treats as formula ground
truth — was the defect in all four rows, exactly as this entry predicted. The corrected
native string-function set is **`concat`, `substr`, `left`, `right`, `strlen`, `strpos`,
`contains`** and nothing else.

**Follow-on:** the *documentation* is now correct but **five CLI emitters still emit the
invalid bare calls** — filed as **BL-171**. And the validator that was supposed to gate this
class, `check_formula_catalog.py`, **silently skips most of its input** (82% of the qlik
file's rows) — filed as **BL-172** after the PR review found a wrong row the validator had
passed. See *Validator promotion* below: this class of drift is **not** yet unable to recur.

### What the conflict was (for the record)

Four function-level claims about ThoughtSpot's *own* formula language **were** stated
incompatibly across our shared references. In each case one of the files was wrong, so at
least one converter was emitting either an invalid native call or an unnecessary
pass-through -- and the two failure modes are asymmetric: a wrong "native" claim produces a
formula that fails at import, while a wrong "no native" claim only costs fidelity. As it
turned out, **every "native" claim was the wrong one**, so the realised failure mode was the
import-breaking kind on all four rows.

| # | Function(s) | Claim A | Claim B |
|---|---|---|---|
| a | `replace` | native: `replace ( [x] , [old] , [new] )` (`thoughtspot-formula-patterns.md:186`), and the Databricks mapping's ThoughtSpot column agrees (`ts-databricks-formula-translation.md:84`) | "Bare `replace(...)` is **NOT** a valid ThoughtSpot formula function (live-confirmed)" -- re-mapped to `sql_string_op` and CLI-translated in ts-cli v0.81.0 (`tableau-formula-translation.md:117`, `:172`, `:1032`, `:1125`) |
| b | `starts_with` / `ends_with` | native, returning boolean (`thoughtspot-formula-patterns.md:188-189`); `starts_with` again in `ts-databricks-formula-translation.md:86` | "No native `starts_with`" / "No native `ends_with`", composed from `strpos` / `substr` instead (`tableau-formula-translation.md:227-228`, live-verified 2026-06-13 on se-thoughtspot) |
| c | `ltrim` / `rtrim` | exist as ThoughtSpot functions (`ts-databricks-formula-translation.md:82-83`, whose left-hand column is the ThoughtSpot side) | "ThoughtSpot `trim()` removes both sides -- no left-only / right-only trim available" (`qlik-thoughtspot-formula-translation.md:180-181`). `thoughtspot-formula-patterns.md` lists `trim` only and names neither, so it corroborates neither side |
| d | `in` literal-list delimiter | `[col] in ( 'a' , 'b' )` -- round parentheses (`thoughtspot-formula-patterns.md:134`) | `in { a , b , c }` -- curly braces required; the round form raises the parser error "Search did not find 'in ( ...'" (`tableau-formula-translation.md:41`) |

The prediction recorded here at filing time was that rows (a), (b) and (d) each had a
live-confirmed side (the Tableau mapping, dated and attributed to se-thoughtspot), making
`thoughtspot-formula-patterns.md` the probable defect in all three, with row (c) having no
live evidence either way. **That prediction was correct, and row (c) resolved against the
mappings too** -- `ltrim`/`rtrim` *and* `trim` are all absent.

### How it was settled

22 probes on **se-thoughtspot** (`https://se-thoughtspot-cloud.thoughtspot.cloud`) on
2026-07-29 via `ts tml import --policy VALIDATE_ONLY` -- one throwaway Model formula per
probe, so every result is individually attributable, and nothing is persisted (the probe
Model re-exported byte-identical afterwards; no objects were created).

The method was validated by controls in the same pass, which is what makes the surprising
`trim` result trustworthy: `concat`, `substr`, `left`, `right`, `strlen`, `strpos` and
`contains` all **passed**; `upper` (known absent since 2026-06-13) **failed** as expected.
Every replacement pass-through and composition was also verified to import, so the
corrections are evidence-backed rather than inferred.

One correction to the filing-time plan is worth recording: the entry anticipated that a
`passthrough` -> `direct` flip on `LTRIM`/`RTRIM` might move the Ossie document's counts.
**The flip went the other way.** `LTRIM`/`RTRIM` stayed `passthrough` (with a stronger
justification -- there is no `trim` to substitute at all), and `TRIM` and `REPLACE` moved
`direct` -> `passthrough`, so the split went `114/31/1` -> `112/33/1` and 78% -> 77%. The
"two spellings may coexist by build" allowance was not needed either: the `in` delimiter is
unambiguously `{ }`, and the parser error names `"{"` as an expected token explicitly.

### Validator promotion -- partly already in place, and weaker than it looked

The extension proposed at filing time (`check_formula_catalog.py` cross-checking each
mapping's ThoughtSpot column against the catalog) **already existed** and now has a correct
baseline. But it should **not** be read as making this class of drift unable to recur, for
two reasons:

1. **The scanner is broken.** `scan_mapping` skips any table row containing the word
   "ThoughtSpot" -- 82% of the qlik file's rows. That is why the PR review still found a
   wrong row (`qlik` CL08: round-paren `in (...)` plus a struck-through `lower()`) *after*
   the validator reported green. Filed as **BL-172**, which should land before any
   extension.
2. **It only covers `agents/shared/mappings/*.md`.** The five converter emitters in
   `tools/ts-cli/` are ungated and still emit the invalid bare names -- filed as **BL-171**.

So the honest status is: the references are correct and there is a *partial* gate on them;
the code is still wrong and ungated. BL-172 then BL-171, in that order, is what would
actually close the loop.

**Outcome:** four conflicts settled, one bonus defect found, six shared references and
three coverage matrices corrected, seven skills PATCH-bumped, two follow-on entries filed
(BL-171, BL-172).

---

## BL-171 -- Five ts-cli emitters still emit the six non-existent string functions `Tier 1`

**Filed:** 2026-07-29.
**Source:** fallout from BL-170's live verification. BL-170 corrected the *reference docs*;
this entry is the *code*.
**Affects:** `tools/ts-cli/ts_cli/sv_sql.py`, `tools/ts-cli/ts_cli/databricks/mv_sql.py`,
`tools/ts-cli/ts_cli/tableau/functions.py`, `tools/ts-cli/ts_cli/qlik/functions.py`,
`tools/ts-cli/ts_cli/powerbi/functions.py`, plus the vendored
`agents/databricks/notebooks/databricks_mv_lib.py` (regenerated, not hand-edited).
**Status:** OPEN.

BL-170 live-proved that `trim`, `ltrim`, `rtrim`, `replace`, `starts_with` and `ends_with`
are **not** ThoughtSpot formula functions. Five converter emitters still translate a source
function to those bare names, so every affected formula **fails at TML import** with
`Search did not find "<fn> ("` (error 14516). This is a correctness bug, not a fidelity
one — the import is rejected outright.

| Module | Direction | Offending map | Names emitted |
|---|---|---|---|
| `sv_sql.py:206-208` | Snowflake SQL → TS | `_RENAME` | `trim`, `ltrim`, `rtrim`, `replace`, `starts_with`, `ends_with` |
| `databricks/mv_sql.py:251-252` | Databricks SQL → TS | `_RENAME` | `trim`, `ltrim`, `rtrim`, `replace`, `starts_with` |
| `tableau/functions.py:47` | Tableau → TS | regex rewrite list | `trim` only (the rest of this module is already correct) |
| `qlik/functions.py:40-43` | Qlik → TS | `FUNCTION_MAP` | `trim`, `ltrim`, `rtrim`, `replace` — **plus `upper`/`lower`** (wrong since 2026-06-13) **and `len`/`mid`** (line 40, identity-mapped `"len": "len"` / `"mid": "mid"`; both live-disproved 2026-07-29 — the real names are `strlen` and `substr`, and neither `len` nor `mid` appears in the catalog at all) |
| `powerbi/functions.py:39` | DAX → TS | `_DAX_FUNC` | `trim` — **plus `upper`/`lower`**, same pre-existing defect |

`databricks/mv_emit_sql.py:22` (`"trim": "TRIM"`) is the reverse direction and is a
**harmless dead entry** — no valid TS model can contain `trim`, and the `sql_string_op`
unwrap already handles the real path. Leave it or delete it; it is not a bug.

**Reference implementation already in the repo:** `tableau/functions.py` `_ARG_HANDLERS`
(L157-205) already does exactly the right thing for `REPLACE`, `STARTSWITH`, `ENDSWITH`,
`UPPER` and `LOWER`. The other four modules need the same shape. `sv_sql.py` and
`mv_sql.py` each already have a `_PASS_THROUGH_HINT` dict (holding `LOWER`/`UPPER`/
`INITCAP`) which is the natural home; `qlik` and `powerbi` have only `None`-means-flag and
need a template mechanism added.

**Approach:**

1. Move the six names out of each rename map into that module's pass-through/handler path,
   emitting `sql_string_op ( "TRIM({0})" , ... )` etc., and the `strpos ( ) = 1` /
   `substr` compositions for `STARTSWITH`/`ENDSWITH`.
2. Fold in `upper`/`lower` for qlik and powerbi — same defect class, already disproved — and
   qlik's `len`/`mid`, which are identity-mapped to names that do not exist (→ `strlen`,
   `substr`). The qlik map should be audited end-to-end rather than patched name-by-name:
   four separate defect classes have now been found in it, which suggests it was written
   against assumed rather than verified ThoughtSpot function names.
3. Unit tests per module: `tools/ts-cli/tests/` has **no** test asserting any of these six
   mappings today, which is why the bug survived. `test_sv_sql.py:90-92` asserts the *wrong*
   expectation (`starts_with ( [A::NAME] , 'A' )`) and must be updated.
4. Re-run `agents/databricks/build_mv_lib.py` to regenerate the vendored lib
   (`test_vendor_mv_lib.py` enforces the sync).
5. Update each affected `references/coverage-matrix.md` to drop the "documentation
   corrected, CLI still wrong — see BL-171" caveats BL-170 added.
6. Bump ts-cli version + the affected skills' versions.

**Validator promotion this should unlock:** extend `check_formula_catalog.py` (which today
scans only `agents/shared/mappings/*.md`) to also parse the emitter rename maps in
`tools/ts-cli/ts_cli/**` and fail when a map's *value* is a function the catalog marks
non-existent. That closes the loop BL-170 opened — the catalog is now correct, and the code
is the only remaining place the claim can drift.

**Target:** next converter-formula pass. Tier 1 because it produces failed imports today on
five of the six conversion paths.

---

## BL-172 -- `check_formula_catalog.py` silently skips most data rows (header detection is too loose) `Tier 1`

**Filed:** 2026-07-30.
**Source:** PR review of the BL-170 corrections. The reviewer found a wrong row
(`qlik` CL08) that the validator should have caught, which led to this root cause.
**Affects:** `tools/validate/check_formula_catalog.py` (+ `tools/validate/tests/test_formula_catalog.py`).
**Status:** OPEN.

`scan_mapping` treats **any** table row containing one of `_TS_COLUMN_KEYWORDS`
(`"thoughtspot"`, `"ts syntax"`, `"ts formula"`) as a **column header**, resets `ts_col`
from it, and `continue`s -- skipping the row entirely:

```python
# check_formula_catalog.py:136-141
if line.strip().startswith("|") and any(
    kw in line.lower() for kw in _TS_COLUMN_KEYWORDS
):
    ts_col = _find_ts_column(line)
    continue
```

Mapping files mention "ThoughtSpot" **in their Notes column constantly**, so this silently
excludes most of the corpus the validator exists to gate:

| File | Table rows | Skipped as "header" |
|---|--:|--:|
| `qlik-thoughtspot-formula-translation.md` | 220 | **182 (82%)** |
| `tableau-formula-translation.md` | 241 | 67 (27%) |

Worse, `_find_ts_column` returns `None` for a data row (no cell *is* a header), which
**resets `ts_col` to `None`**, so subsequent genuine rows get scanned against cell 0 instead
of the real ThoughtSpot column -- a second, quieter failure mode.

**Confirmed reproduction** (2026-07-30). The shipped CL08 row is skipped; the *same* row with
the word "ThoughtSpot" removed from its Notes is flagged correctly:

```
AS SHIPPED (Notes says 'ThoughtSpot')   -> errors: []            <-- silently skipped
SAME ROW, 'ThoughtSpot' removed         -> errors: ['ERROR: ... `lower` is not a valid TS function']
```

`lower` is marked non-existent in the catalog, so this row was always an error -- the
validator just never looked at it. **This is why the BL-170 pass missed CL08** (round-paren
`in (...)` *and* a struck-through `lower()`), and it means `check_formula_catalog.py`'s
green result across the BL-170 corrections was substantially weaker evidence than it
appeared.

**Approach:**

1. Identify header rows structurally, not by keyword: a header is the row **immediately
   preceding a separator row** (`|---|---|`). Detect the separator first, then treat the
   previous line as that table's header.
2. Never reset `ts_col` from a non-header line.
3. Regression tests that would have caught this: a data row whose Notes contain
   "ThoughtSpot" *and* an invalid function must ERROR; and a table whose header is followed
   by many "ThoughtSpot"-mentioning rows must keep `ts_col` stable throughout.
4. Re-run over all of `agents/shared/mappings/` afterwards and triage the backlog of rows
   that were never gated -- expect real findings, including the two open conflicts BL-170
   flagged but did not settle (`substr` 0- vs 1-indexing in the qlik file; qlik S12's
   "no substring-position function" claim vs the verified `strpos`).

**Deliberately not fixed in the BL-170 PR** -- that PR is a content correction, and this is a
tooling change whose blast radius is "every mapping row that was never scanned". Fixing it
first would have mixed an unbounded triage into a scoped fix.

**Relationship to BL-171:** BL-171 proposes *extending* this validator to cover
`tools/ts-cli/` emitter maps. **BL-172 should land first** -- extending a scanner that
skips 82% of its current input would inherit the same blind spot.

**Target:** next validator pass; before BL-171's validator extension.

---

## BL-173 — Bound `ts tml verify-render` per-tile probing on large liveboards `Tier 3`

Raised by djwaldo reviewing #356 (the Power BI render-robustness PR). When a board fails the
whole-board `metadata/liveboard/data` call, `verify-render` re-probes **each tile sequentially**
with a 180s timeout to name the offending visualization. On a board with 20+ tiles this is
sequential and unbounded.

**Why it is low priority (reviewer's call, agreed):** it is the error path only — a board that
already failed the whole-board render — and the per-tile 500s return fast in practice, so the
realistic wall time is small. The current behaviour is correct, just not bounded.

**Approach when picked up:** cap the work — either probe tiles concurrently (a small pool) or
early-bail after N failing tiles (the board is already known broken; naming the first few is
enough to act), keeping the full per-tile list only under the cap. Pure change in
`ts_cli/render_check.py` + the loop in `commands/tml.py verify_render_cmd`; add a test asserting
the cap. Target: opportunistic — next time a real liveboard with 20+ tiles goes through the gate.

---

## BL-174 -- from-Databricks forward leg: three source-fidelity defects in `mv_build_model.py` `Tier 1`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), findings F1, F3, F5.
**Affects:** `tools/ts-cli/ts_cli/databricks/mv_build_model.py`,
`tools/ts-cli/tests/` (no test asserts any of the three today),
`agents/cli/ts-convert-from-databricks-mv/references/coverage-matrix.md` (rows #13, #77, #79 —
added/corrected in the fidelity PR, to be flipped when this lands).
**Status:** OPEN -- **ready to fix**. All three are localised, source-derived-value-vs-constant
defects in one module; one PR, one ts-cli bump.

Round-tripping apache/ossie's TPC-DS Metric View fixture (MV -> Model TML -> MV, fully offline)
scored 9 of 15 constructs `matched`. Three of the six deviations are forward-leg assembly
defects in the same module, and every gate -- `parse-mv`, `translate-formulas`, `build-model`'s
own `invariant_findings`/`lint_findings`, `ts tml lint`, `check_tml.py` -- reported clean on all
three.

| # | Defect | Line | Correct behaviour |
|---|---|---|---|
| 1 | **`"type": "INNER"` emitted unconditionally** for every join | `mv_build_model.py:236` | `LEFT_OUTER`. The MV schema has no join-type field because Databricks fixes it: "In a star schema, the `source` is the fact table and joins with one or more dimension tables using a `LEFT OUTER JOIN`" ([Joins in metric views](https://docs.databricks.com/aws/en/business-semantics/metric-views/joins)). `LEFT_OUTER` is a valid Model TML join type (`thoughtspot-model-tml.md:123`), so nothing about the target format forces `INNER`. |
| 2 | **Measure `format:` never read** | `mv_build_model.py` / `mv_tml.py` (absence) | Write `properties.currency_type.iso_code`. `mv_translate.py:98` already carries `"format": meta.get("format")` into `translated.json`; the data survives parse and translate and is discarded at assembly. The **reverse** leg already implements the pair (`mv_emit_classify.py:228-231`), and `ts-databricks-properties.md:109`/`:122` document it as mapped. `grep -rn currency_type tools/ts-cli/ts_cli/` returns only the two reverse-direction lines. |
| 3 | **`cardinality: MANY_TO_ONE` stamped on every join** | `mv_build_model.py:237` | Stamp it only when the source declared `cardinality:` explicitly. `rely: {at_most_one_match: true}` works on all runtimes; `cardinality:` is **18.1+ only** and `many_to_one` is the schema default anyway (`databricks-metric-view.md:20`, `:430-437`). Promoting the `rely:` hint means the to-direction then emits `cardinality:`, silently moving the round-tripped MV's runtime floor from 17.3+ to 18.1+ -- the to-mv skill's own prerequisites table says 18.1+ is "Required only if the model has an explicit `MANY_TO_ONE` join" (`ts-convert-to-databricks-mv/SKILL.md:197`). |

**Why Tier 1 is defect 1 alone.** It **changes numbers, silently**. Every fact row whose FK is
NULL or matches no dimension row is retained by the Metric View and dropped by the ThoughtSpot
Model, so measures read **lower** in ThoughtSpot than in Databricks on the same data. TPC-DS's
`store_sales` surrogate-key columns carry no NOT NULL constraint, so the divergence is reachable
on the fixture's own schema. The magnitude was **not measured** (no live workspace or instance --
see the report's §2.7); the direction of the error is not in doubt.

**Why the round-trip diff cannot see defect 1.** The Metric View schema has no `type:` field, so
the source-vs-regenerated diff is silent on it -- it is visible only by reading our intermediate
TML against the vendor spec. A property-level diff alone scored the round trip 35/38 = 92% and
missed the one finding that changes numbers. That asymmetry is why this needs a unit test, not a
round-trip assertion.

**Approach:**

1. Fix the three lines. Defect 3 needs the parsed node to distinguish "declared `cardinality:`"
   from "inferred from `rely:`" -- `parse-mv` already preserves both, so this is a read of the
   parsed dict, not a parser change.
2. Unit tests per defect against `_build_joins` / the assembly function directly (no live
   connection): a join with only `rely:` emits `LEFT_OUTER` and **no** `cardinality`; a join with
   explicit `cardinality:` emits it; a measure with `format: {type: currency, currency_code: USD}`
   emits `properties.currency_type.iso_code: USD`.
3. Flip coverage-matrix rows #13, #77 and #79 to plain Mapped rows and drop the BL-174 caveats.
4. Re-run the TPC-DS round trip from the fidelity report's workspace recipe (§1.4) and confirm the
   regenerated MV has no `cardinality:` keys and carries the `format:` block back.
5. Bump ts-cli + the from-databricks-mv skill (MINOR -- #2 is a new mapped property).

**Target:** next converter pass on the Databricks pipeline; Tier 1 because defect 1 produces
wrong numbers today with no warning anywhere in the pipeline.

---

## BL-175 -- Provenance text written into the field that round-trips as the source's own description `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), findings F4 (Databricks) and F19 (Snowflake) --
independently observed in both converter pairs, which is what makes it a class rather than a quirk.
**Affects:** `tools/ts-cli/ts_cli/databricks/mv_build_model.py`,
`tools/ts-cli/ts_cli/sv_build_model.py`, `tools/ts-cli/ts_cli/sv_build_sv.py`,
`tools/ts-cli/ts_cli/databricks/mv_emit_classify.py` -- plus a sweep of the other five
converters, which were not exercised by this review.
**Status:** OPEN.

Both from-directions append provenance sentences to `model.description`, and both reverse legs
copy the whole string back into the source's own comment field. Two distinct defects, both
present in both converters:

1. **Missing separator.** The source description and the appended sentence are concatenated with
   a single space and no terminating punctuation on the first, producing a run-on that is
   **user-visible in the ThoughtSpot model description** regardless of any round trip:
   `"...customer dimensions Converted from Databricks Metric View tpcds.public.tpcds_store_sales."`
   and `"...sales and customer analytics Converted from Snowflake Semantic View
   TPCDS.PUBLIC.TPCDS_RETAIL_MODEL."`
2. **Unbounded accretion.** Because the reverse leg round-trips the polluted string, each
   conversion cycle appends again. The Snowflake pair appends on **both** legs, so a single round
   trip already accumulates two provenance strings
   (`comment='... Converted from Snowflake Semantic View ... | Migrated from ThoughtSpot: Tpcds
   Retail Model'`) and accretes twice as fast as the Databricks pair.

The provenance itself is legitimate and useful -- the defect is the destination.

**Approach:**

1. Decide the destination once, cross-converter. Options: a dedicated non-round-tripping field;
   the model's AI-context/instructions block; or the stash BL-166 will introduce (cleanest -- a
   `_v`-versioned `converted_from` key is exactly the shape BL-166 defines, and a stash-aware
   reverse leg would strip it from the comment automatically).
2. Until then, at minimum: separator + terminating punctuation, and make the reverse leg strip a
   recognised provenance suffix before writing `comment:`/`description:` -- an idempotence
   property, not a cosmetic fix.
3. Add a round-trip test that converts twice and asserts the description is byte-identical after
   the second cycle (the property the current code violates).
4. Sweep tableau / qlik / powerbi / sisense / looker for the same pattern -- this review only
   exercised the Snowflake and Databricks pairs, so their status is unknown, not clean.

**Target:** with BL-166 (shared destination decision) or the next converter pass, whichever comes
first. Tier 2 rather than 3 because the run-on is user-visible on every single conversion, not
only on a round trip.

---

## BL-176 -- File-only path Table TML gaps in both from-direction converters `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), findings F7 (Databricks) and F16 (Snowflake).
**Affects:** `tools/ts-cli/ts_cli/databricks/mv_tml.py`,
`agents/cli/ts-convert-from-databricks-mv/SKILL.md` (the file-only `tables.json` spec, twice --
`:552-556` and the identical block at `:607-611`),
`tools/ts-cli/ts_cli/sv_build_model.py`, `agents/cli/ts-convert-from-snowflake-sv/SKILL.md`
(Step 10-FILE, Step 6D), both `references/coverage-matrix.md` files.
**Status:** OPEN.

The two from-direction converters have opposite and equally unsatisfactory offline Table TML
stories, and the contrast is the finding:

**Databricks emits Table TMLs, but classifies them badly.** `build_table_tml`
(`mv_tml.py:69-73`) defaults every numeric column to `MEASURE` with `aggregation: SUM`. On the
TPC-DS fixture the four surrogate keys **and `ss_ticket_number`** -- which the MV *explicitly
declares a dimension* -- arrive as summable measures, so the user's Tables offer "Sum of Ss Sold
Date Sk" and a summable ticket number. The Model TML overrides the classification correctly, so
this is a quality defect, not a fidelity loss. `build_table_tml` **already accepts** per-column
`column_type` and `aggregation` overrides -- but the SKILL's file-only `tables.json` spec
documents only `{name, dbx_type}`, so no documented run ever passes them. The information needed
is free: the MV's own dimension list and every join's `on` clause name exactly which numeric
columns are keys or declared dimensions.

**Snowflake emits no Table TML at all**, so a documented mapping row is unreachable. Coverage
row 5 maps table-level `comment=` to `table.description` via "Separate Table TML update"
(Step 6D) -- but Step 6D needs Table TMLs fetched from a live instance, and Step 10-FILE writes
`{model_name}.model.tml` only (`SKILL.md:753-754`). `parse-sv` captures all five table comments
correctly (`"comment": "Fact table containing all store sales transactions"` in the parsed JSON);
they are then silently dropped. Five of five table descriptions lost on the documented offline
path.

**Approach:**

1. **Databricks:** derive `column_type`/`aggregation` from the MV itself inside `build-model` --
   any column named in `dimensions:`/`fields:` or in a join `on` clause is an `ATTRIBUTE` with no
   aggregation; everything else keeps today's default. Then document the two extra `tables.json`
   keys in **both** copies of the SKILL.md spec block so a hand-built map can override.
2. **Snowflake:** emit Table TML on the file-only path too, carrying at least the SV's table-level
   `comment=` and the physical columns the SV references. The SV DDL does not enumerate every
   physical column, so these are necessarily partial Table TMLs -- decide explicitly whether that
   is acceptable (import-then-refresh) or whether the comment should instead be surfaced as a
   post-import manual step the skill names. Either way the current silent drop is not the answer.
3. Update coverage rows: from-DBX **L11** and from-SF row **#5** were added/amended in the
   fidelity PR to declare today's behaviour; flip both when this lands.
4. Tests: assert the emitted Table TML classifies a join key and an MV-declared dimension as
   `ATTRIBUTE`; assert the SF file-only path emits one Table TML per referenced table with the
   parsed `comment` on it.

**Target:** next converter pass; bundle with BL-100 (bring remaining converters to the DBX-from
standard) if that lands first -- this is exactly the kind of asymmetry BL-100 exists to close.

---

## BL-177 -- Reverse legs synthesise names that were already available `Tier 3`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), findings F8 (Databricks) and F18 (Snowflake).
**Affects:** `tools/ts-cli/ts_cli/databricks/mv_emit.py` (`default_view_name`),
`tools/ts-cli/ts_cli/sv_build_sv.py` (relationship naming),
`agents/cli/ts-convert-to-databricks-mv/SKILL.md` (Step 5.2 prompts).
**Status:** OPEN.

Two independent instances of the same small defect class: the reverse leg generates a name from a
template when the real name was sitting in the input.

1. **Doubled fact-table token in the default MV name.** `default_view_name(model_name, fact)`
   concatenates the model name with the fact table, so a model named after its fact produces
   `tpcds_store_sales_store_sales_mv`. `--view-name` overrides it and **no skill step prompts for
   it**, so the default is what most runs get. Fix: skip the fact token when the snake-cased model
   name already ends with it, and add the prompt.
2. **Relationship names regenerated rather than reused.** The forward leg preserves the SV
   relationship name correctly onto the join (`name: store_sales_to_date` in the Model TML) and
   `build-sv` discards it in favour of a `{left}_to_{right}` template, emitting
   `store_sales_to_date_dim`. The other three names on the TPC-DS fixture survive only
   coincidentally, by already matching the template. Relationship names are **referenceable** in
   Snowflake -- `using_relationships` on a metric names them (`snowflake-schema.md:146-147`) -- so a
   rename breaks any metric or verified query that cites one. Fix: reuse `joins[].name` when
   present; fall back to the template only when it is absent.

Low impact on this fixture (nothing referenced either name) and both fixes are a few lines with
an obvious test, which is why they are grouped rather than filed separately: neither justifies its
own PR, and both are pure name fidelity that costs nothing to preserve.

**Target:** opportunistic -- fold into the next PR touching either emitter (BL-174 for Databricks,
BL-182 for Snowflake).

---

## BL-178 -- from-Snowflake identifier resolution: a three-defect regression that makes every metric's formula reference dangle `Tier 1`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), finding F9 -- the report's headline.
**Affects:** `tools/ts-cli/ts_cli/sv_translate.py` (`:103-137`, `:72-79`),
`tools/ts-cli/ts_cli/sv_parse.py` (`:470-492`), `tools/ts-cli/ts_cli/sv_build_model.py` (`:96`),
`tools/ts-cli/tests/test_sv_translate.py` (`:352-361` -- **asserts the defect**),
`agents/shared/worked-examples/snowflake/ts-from-snowflake-identifier-resolution.md`.
**Status:** OPEN -- **ready to fix**, with a mandatory three-part scope (below).

**The symptom.** Converting a Semantic View whose metrics aggregate a declared fact -- the normal
shape, and the shape upstream's own converter always emits -- produces a Model TML in which
**every measure is unresolvable**. On the TPC-DS fixture all 5 of 5 metric formulas reference
formula ids that are never declared:

```yaml
  formulas:
  - expr: "sum ( [formula_ss_ext_sales_price] )"   # <- no such id
    id: formula_total revenue
    name: total revenue
  - expr: "sum ( [formula_ss_ext_sales_price] ) / unique count ( [CUSTOMER::c_customer_sk] )"
    id: formula_CLV
    name: CLV
```

Declared ids are `formula_total revenue`, `formula_net profit`, `formula_CLV`,
`formula_brand sales`, `formula_sales per employee`; referenced ids are
`formula_ss_ext_sales_price`, `formula_ss_net_profit`, `formula_s_number_employees` -- none of
which exists. All three referents were emitted as plain `columns[]` entries instead. Per
CLAUDE.md's formula invariant, a bracket reference matching no `formulas[].id` is parsed as search
tokens rather than resolving, so the expected outcome is import failure or a silently broken
measure -- **which of the two is unverified** (no instance was available; verify on the fix).

`ts tml lint` and `check_tml.py` both report **clean** on this TML. So does `build-model`'s own
`lint_findings`. The defect is confined to the forward leg: `build-sv` reads the Step 8
translations, not the TML expressions (`sv_build_sv.py:518-529`), so repairing the references
produces a byte-identical DDL -- verified by diff. The **only** damaged artifact is the one the
user imports.

**This is a regression against a live-verified baseline.**
`agents/shared/worked-examples/snowflake/ts-from-snowflake-identifier-resolution.md` was "Verified
end-to-end against `se-thoughtspot` on 2026-06-13" (`:23`, with the resulting model GUID recorded)
and documents `expr: "average ( [formula_Tenure Months] )"` at `:233`. Re-running that worked
example's own DDL through today's pipeline emits `average ( [formula_tenure_months] )` and
**4 of its 8 formulas dangle**. Per `agents/shared/CLAUDE.md` ("Worked examples are ground
truth"), the worked example wins. Likely window: the Step 4/9/8 rewire onto deterministic
commands -- from-snowflake-sv SKILL.md v1.17.0, 2026-07-22 -- which postdates the verification.

### Fix scope -- all three defects, or the fix is cosmetic

Repairing only the resolver leaves the index it reads still poisoned. A fix that addresses defects
1 and 2 would look correct on the TPC-DS fixture and still be wrong on any SV containing a
computed fact.

**Defect 1 -- the documented resolution order is inverted** (`sv_translate.py:125-137`).
`ts-from-snowflake-rules.md:585-593` is explicit: step 1 is "is `name` a physical column on the
table identified by `table_alias`?", step 2 is the facts map. The code checks
`fact_idx`/`metric_idx` **first** and falls through to `alias_map` afterwards -- and the
function's own docstring (`:103-110`) restates the correct order immediately above the code that
inverts it. **This is the defect that fires on TPC-DS**: every fact there is a passthrough whose
`expr` *is* a physical column, so step 1 would have emitted `[STORE_SALES::ss_ext_sales_price]`
and resolved cleanly.

**Defect 2 -- the emitted id is not the id `build-model` mints.** Even where a fact or metric
legitimately becomes a formula, the resolver emits `[formula_<sql_token>]` while `build-model`
derives the id from the *display* name (first synonym, else title-case -- `sv_build_model.py:96`).
The rules file forecloses this at step 2: "The reference uses the formula's `id` value (e.g.
`formula_Tenure Months`), **NOT** the display name." Reordering the resolver does not fix this --
a correctly-reached step 2 still emits the wrong token.

**Defect 3 -- `sv_parse.py` assigns `alias_name` from the expression, not the declared name**
(`_resolve_rhs_alias`, `:470-492`), which poisons **both** indexes. It returns the first qualified
token of the right-hand side as `alias_name` whenever the RHS is more complex than a bare
`alias.NAME`; `_build_column_index` then keys both `fact_idx` and `metric_idx` on
`alias_table.alias_name` (`sv_translate.py:72-79`), so a computed fact or metric is indexed under
**a physical column of its own table** rather than under its declared name. Reproduced with a
minimal probe -- `STORE_SALES.net_line as STORE_SALES.ss_ext_sales_price -
STORE_SALES.ss_net_profit` parses to `alias_name: ss_ext_sales_price` with the declared name
`net_line` in `source_column`. Two corruptions follow: a spurious reference to a physical column
(`[formula_ss_ext_sales_price] - [STORE_SALES::ss_net_profit]` -- inconsistent *within one
expression*), and, for `SUM(store_sales.net_line)`, a **metric self-reference** where resolving the
metric's inner reference hits its own `metric_idx` entry. Latent on TPC-DS; not latent in general.

**Approach:**

1. Fix all three. Defect 3 first -- the index feeds the resolver.
2. **Fix the test that asserts the bug.** `test_sv_translate.py:352-361`
   (`test_fact_reference`) asserts `resolver("employees.tenure_months") ==
   "[formula_tenure_months]"` -- the wrong expectation, which is why this survived.
3. **Add the missing contract test.** The resolver and `build-model` are each tested in isolation
   and the contract *between* them -- every `[formula_X]` a metric emits matches an id
   `build-model` will declare -- is asserted nowhere. Assert it end-to-end over a parsed SV, not
   per-unit. (The structural half of this is also a validator promotion: BL-183.)
4. **Re-verify the worked example live.** Re-run
   `ts-from-snowflake-identifier-resolution.md`'s DDL through the fixed pipeline against
   `se-thoughtspot` and confirm both the documented `formulas[]` block and a successful import;
   the worked example is ground truth and must be re-earned, not assumed. Note the worked example
   **also** diverges on 6 of 18 display names and 2 formula ids for an unrelated reason (coverage
   row 14's first-synonym promotion landed 2026-06-15, after the 2026-06-13 verification), so
   expect to reconcile that in the same pass -- see BL-184, which depends on this baseline being
   trustworthy.
5. Bump ts-cli + the from-snowflake-sv skill (PATCH -- restores documented behaviour).

**Target:** immediate -- this is the highest-severity finding of the review. Every from-Snowflake
conversion done since 2026-07-22 on an SV with declared facts has produced a Model whose measures
do not resolve, with every gate green.

---

## BL-179 -- from-Snowflake promotes the first synonym over the logical identifier `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), finding F10.
**Affects:** `tools/ts-cli/ts_cli/sv_build_model.py`,
`agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md` row 14 (amended in the
fidelity PR), `agents/cli/ts-convert-from-snowflake-sv/SKILL.md`.
**Status:** OPEN.

`with synonyms=('...',...)` is read as "first synonym is the display name; the rest are
synonyms" (coverage row 14). **29 of the 36 named dimension/time_dimension/fact/metric constructs
on the TPC-DS fixture are renamed this way** -- every construct that carries a synonyms list. The
7 survivors survive only because they have no synonyms, so the title-case <-> snake-case pair is
invertible.

**The heuristic is defensible for a Semantic View our own to-direction authored** -- `build-sv`
emits the ThoughtSpot column name as the first synonym, so the pair round-trips cleanly. It is
wrong for a Semantic View authored anywhere else, where `with synonyms=(...)` means what Snowflake
says it means: alternate names for natural-language matching. The referee is unambiguous and
separates the two fields explicitly: OSI keeps `name: total_sales` and
`ai_context.synonyms: ["total revenue", ...]` in different places, and upstream's converter carried
both through correctly.

Worst on metrics, where the substitutions are not even display-name-shaped: `total_sales` ->
`total revenue`, `customer_lifetime_value` -> **`CLV`**, `store_productivity` ->
`sales per employee`, `sales_by_brand` -> `brand sales`. Any Cortex Analyst verified query, saved
question or downstream SQL referencing the real name breaks.

**It also compounds** -- the rename is what triggers the date-heuristic misfire in BL-182 item 1:
`ss_sold_date_sk` matches no `_DATE_SUFFIXES` entry, but `sale date` does.

**Approach:**

1. Default to the SV logical name as `column.name` and put **all** synonyms in
   `properties.synonyms`. That is the behaviour the source format's own semantics imply.
2. Detect our own output and keep today's behaviour for it: `build-sv` emits the ThoughtSpot
   column name as the first synonym *and* writes a `with extension (CA=...)` clause, so a
   provenance marker in that clause is the natural signal -- which is exactly the stash BL-166
   introduces. Until BL-166 lands, a `--promote-first-synonym/--no-promote-first-synonym` flag
   defaulting to *off* (identifier wins) is the honest interim.
3. Amend coverage row 14 again when this lands (it was corrected in the fidelity PR only to
   declare the current hazard).
4. Tests: a foreign-shaped SV keeps its identifiers and gains all synonyms; a `build-sv`-produced
   SV still round-trips its ThoughtSpot names.

**Target:** with BL-166 (the provenance signal makes the detection clean) or the next
from-Snowflake pass. Do **not** land before BL-178 -- renaming behaviour interacts with the id the
resolver mints.

---

## BL-180 -- from-Snowflake formula translation ignores two mappings it already documents `Tier 1`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), findings F11 and F12.
**Affects:** `tools/ts-cli/ts_cli/sv_sql.py`,
`agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` (a missing hazard
warning), `agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md` (L10, #39 --
added in the fidelity PR), plus `tools/ts-cli/ts_cli/databricks/mv_sql.py` for the second item.
**Status:** OPEN -- **ready to fix**; both are mechanical rewrites with no judgment involved.

Two independent findings, one root cause: the translator has the correct mapping documented in
the reference it cites and does not apply it.

**1. `||` is rejected and the whole construct dropped, though `CONCAT` is mapped.**
`ts snowflake translate-formulas` on the TPC-DS fixture:

```
Skipped:
  - customer_full_name (dimensions): operator '||' — use CONCAT() instead (ts-snowflake-formula-translation.md)
```

The suggested replacement is already a documented bidirectional mapping, and the second row of it
is a character-for-character match for the shape needed
(`ts-snowflake-formula-translation.md:197-198`: `CONCAT(a, ' ', b)` ->
`concat ( [a] , ' ' , [b] )`). So the translator declines a translation whose rule it names in its
own error message. `||` is **the ANSI SQL standard** concatenation operator -- the OSI source
declares this very expression under `dialect: ANSI_SQL` -- and upstream's converter passes
expressions through untouched, so every `||` in any OSI model reaches us intact. This will drop
constructs from a large share of real Semantic Views. Fix: a mechanical N-ary fold of `a || b || c`
to `concat ( a , b , c )` in the tokenizer.

**2. `x / NULLIF(y, 0)` becomes `safe_divide`, silently turning NULL into 0.**

| | |
|---|---|
| Source | `SUM(store_sales.ss_ext_sales_price) / NULLIF(SUM(store.s_number_employees), 0)` |
| Ours (forward) | `safe_divide ( sum ( [...] ) , sum ( [...] ) )` |
| Ours (regenerated) | `DIV0(SUM(store_sales.ss_ext_sales_price), SUM(store.s_number_employees))` |

`X / NULLIF(Y, 0)` yields **NULL** when `Y = 0`; `safe_divide` yields **0** --
`thoughtspot-formula-patterns.md:171` states it outright -- and the round trip completes the
substitution by emitting Snowflake's `DIV0`. A store with zero employees reports **0 sales per
employee** where the source reports "no value", and the two are not interchangeable downstream:
0 participates in `AVG`, `MIN` and ranking; NULL does not. Emitted with `"annotations": []` -- no
flag, no note, nothing in the `build-model` summary. A NULL-preserving translation was available
throughout: `nullif` is mapped in both directions at `ts-snowflake-formula-translation.md:154`.

**Cross-converter.** from-Databricks does the same collapse and documents it without the caveat
(coverage rows #23/#67 -- caveat added in the fidelity PR). The **Tableau** mapping already carries
exactly this warning (`tableau-formula-translation.md:319`: "Returns **0**, not NULL, on zero
divisor ... flag if downstream logic distinguishes 0 from NULL"); the ts-snowflake and
ts-databricks mappings carry no such warning. **Magnitude not measured** -- it depends on how many
rows have a zero divisor, which needs live data on both sides.

**Approach:**

1. `||` -> `concat` N-ary fold in `sv_sql.py`; drop the skip branch. Tests for 2-arg, 3-arg and
   literal-interleaved forms.
2. Emit the NULL-preserving form `sum ( [...] ) / nullif ( sum ( [...] ) , 0 )` by default in both
   `sv_sql.py` and `mv_sql.py`, keeping `safe_divide` behind an explicit opt-in for callers who
   want 0. If the default must stay `safe_divide` for compatibility, then at minimum emit a typed
   `annotations[]` entry so the substitution is visible in the summary JSON -- silence is the part
   that is indefensible.
3. Add the zero-divisor warning to `ts-snowflake-formula-translation.md` and
   `ts-databricks-formula-translation.md`, matching the Tableau mapping's wording. Bump the
   currency anchors and stage-sync the shared files.
4. Flip coverage rows: from-SF **L10** -> Mapped, from-SF **#39** and from-DBX **#23/#67** to
   whatever the new default is.

**Target:** next converter-formula pass, alongside BL-171 (same modules, same class of
"the emitter disagrees with the reference"). Tier 1: item 1 drops constructs and item 2 changes
numbers, both on common shapes.

---

## BL-181 -- from-Snowflake classifies every fact `ATTRIBUTE`, so `facts()` returns as `dimensions()` `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), finding F13.
**Affects:** `tools/ts-cli/ts_cli/sv_translate.py` (`_translate_fact`, `:454-468`),
`agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md` row 16 (corrected in the
fidelity PR), `tools/ts-cli/tests/`.
**Status:** OPEN.

`_translate_fact` hardcodes `ATTRIBUTE` on both branches -- there is no `MEASURE` branch anywhere
in the function -- while its own docstring describes the choice ("always formulas, classified as
ATTRIBUTE (non-aggregated) or MEASURE") and coverage row 16 promised "`formulas[]` entries
(**MEASURE or ATTRIBUTE**)". The documented decision is never actually made.

Consequence on the TPC-DS fixture: all 5 facts leave `facts()` and return inside `dimensions()`;
the regenerated Semantic View has **no `facts()` block at all**. Quantities, prices, profit and
employee counts are declared to Cortex Analyst as categorical dimensions.

**The referee draws the line cleanly and we erase it.** OSI marks a field as a fact *by omitting
the `dimension:` block* -- upstream's own `_classify_field` documents the rule as "A field with no
`dimension` block is a `fact` regardless of `datatype`" -- and all 22 true dimensions on the
fixture carry `dimension: {is_time: false}` and are correctly `ATTRIBUTE` on our side. So the
distinction survives the source format and upstream's converter, and is lost in ours.

This is **structurally the same defect as BL-174 item 1** (a hardcoded constant where the source
implies a choice) in a different converter -- worth reading the two together, though the fixes are
independent.

**Approach:**

1. Classify from the SV: a fact whose `expr` is a bare physical column or a row-level arithmetic
   expression over numeric columns is a `MEASURE` candidate; one that is categorical or produces a
   string/date is `ATTRIBUTE`. The parsed entry already carries enough to decide
   (`expr`, `source_column`, and the physical column's type where available).
2. If the classification cannot be made reliably offline, make it an explicit prompt in the
   SKILL's review step rather than a silent constant -- but do not leave the docstring describing
   a branch the code lacks.
3. Tests over `_translate_fact` directly, one per branch.
4. Flip coverage row 16 back to "MEASURE or ATTRIBUTE" only once the branch exists.

**Blocks a round-trip check in BL-031.** BL-031 wants the to-direction to emit `facts[]` natively;
until this lands, a TS <-> SV round trip has no MEASURE-classified facts for it to emit, so that
half of BL-031 cannot be exercised end-to-end.

**Target:** next from-Snowflake pass, after BL-178.

---

## BL-182 -- from-Snowflake reverse leg: date-suffix heuristic overrides a known type, and metrics are grouped under a fabricated table `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`), findings F15 and F20.
**Affects:** `tools/ts-cli/ts_cli/sv_build_sv.py` (`_is_date_column` `:94-105`,
`_classify_formula_column` `:531-538`, `_build_ca_tables` `:610-613`, `to_snake` `:24-32`),
`tools/ts-cli/ts_cli/sv_lint_ddl.py`, `tools/ts-cli/tests/`.
**Status:** OPEN. Both defects are in one module and both are a few lines.

**1. A surrogate key is re-emitted as a `time_dimension`.** `ss_sold_date_sk` -- a
`NUMBER(38,0)` foreign key the source declares under `dimensions:`, not `time_dimensions:` --
comes back in the Cortex-Analyst extension JSON as the fact table's time dimension:
`{"name":"store_sales", ... ,"time_dimensions":[{"name":"sale_date"}]}`. That invites date
filtering and date truncation of a join key. Mechanism: `_is_date_column` tests the declared type
(correctly fails, `INT64`) then falls back to a name-suffix list containing the bare string
`"date"`. **The two defects compound**: the original identifier `ss_sold_date_sk` ends in `_sk` and
matches no suffix -- it only trips the heuristic because BL-179's rename made it `sale date`.
Neither defect alone produces this. The source `data_type` was available and correct throughout
and is not consulted once the name test fires. Fix: never let the name heuristic promote a column
whose declared type is a known **non**-date type; the name test is a fallback for unknown types
only.

**2. Every formula-backed metric is grouped under a fabricated table named `field`.**
`_classify_formula_column` builds the metric entry with no `"table"` key; `_build_ca_tables` groups
by `to_snake(m.get("table", ""))`; and `to_snake` returns the placeholder `"field"` for an empty
string. The `if tname:` guard immediately above was clearly meant to skip untabled entries --
`"field"` is truthy, so it never fires. Result: the Cortex Analyst context JSON attributes all five
metrics to a table that does not exist in the view. **This is general** -- any Model with
formula-backed measures produces it, not just this fixture. Fix: carry the owning table onto the
entry (the alias is already resolved when the entry is built), and make `to_snake`'s empty-string
fallback distinguishable from a real alias so the guard works.

**A gate misses defect 2 within its own documented remit.** `ts snowflake lint-ddl` reports
`clean — no findings` on a DDL whose CA JSON references a non-existent table, although
"undeclared table references" is in its `--help` remit -- it checks the DDL clauses and not the CA
JSON payload. Extending it to the CA payload is the validator half, filed as BL-183.

**Approach:** fix both; unit-test `_is_date_column` with a `NUMBER` column named `sale_date`
(must be False) and a `DATE` column named `x` (must be True); assert the emitted CA JSON's table
names are a subset of the `tables()` block -- which is also BL-183's check, so write it once and
share.

**Target:** next from-Snowflake pass; fold BL-177 item 2 in (same module, same PR).

---

## BL-183 -- Validator promotion: dangling `[formula_X]` references and CA-JSON table references `Tier 1`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`) §3.9 -- the promotion the two-bucket rule
prefers for BL-178 (F9) and BL-182 item 2 (F20).
**Affects:** `tools/ts-cli/ts_cli/tml_lint.py` (`ts tml lint`),
`tools/ts-cli/ts_cli/sv_lint_ddl.py` (`ts snowflake lint-ddl`),
`agents/shared/schemas/ts-model-conversion-invariants.md` (a new invariant row),
`docs/quality-gates.md`.
**Status:** OPEN -- **the preferred exit** for BL-178's class per `.claude/rules/repo-audit.md`.

**Why this is validator-shaped and not a backlog fix.** BL-178 is one bug; *dangling
cross-references in emitted TML* is a recurring class. The check is purely structural over a
single TML document -- every bracket reference matching `formula_*` must match a `formulas[].id`
in the same document -- needing no live instance and no judgment. It belongs in `ts tml lint`'s
invariant set beside I5/I8, and **it would have caught BL-178 at the moment it was introduced on
2026-07-22** rather than five weeks later via a fidelity review. Today `ts tml lint`,
`check_tml.py` and `build-model`'s own `lint_findings` all report clean on a Model whose five of
five measures are unresolvable.

Two checks, same PR:

1. **`ts tml lint` — dangling formula reference.** For each `formulas[].expr` and each
   `columns[].formula_id`, resolve every `[formula_*]` bracket token against the document's
   declared `formulas[].id` set; report each miss with the referring formula's id. Note this is
   *distinct* from CLAUDE.md's existing display-name-vs-id invariant (I9): I9 says use the id
   form; this says the id you used must exist.
2. **`ts snowflake lint-ddl` — CA-JSON table references.** Assert every table name inside
   `with extension (CA='…')` appears in the DDL's `tables()` block. This is already in the
   command's documented remit ("undeclared table references") and it currently passes a DDL whose
   CA payload names a table called `field`.

**Not the same tool as BL-172, deliberately.** BL-172 fixes `check_formula_catalog.py`, a scanner
over `agents/shared/mappings/*.md` table rows that gates *function-name* claims in documentation.
This entry gates *reference integrity inside emitted TML/DDL*, in the CLI's own lint commands.
Different input, different tool, no shared code -- so this is its own entry rather than an
extension of BL-172's scope, and neither blocks the other.

**Approach:**

1. Add the two checks with unit tests, including a positive case (an id-form reference that
   resolves) so the check cannot be satisfied by rejecting everything.
2. Add the invariant to `ts-model-conversion-invariants.md` so the property is written down where
   BL-168's property tests can pick it up as a generator target.
3. Regenerate the quality-gates catalog (`generate_quality_gates --check` runs in CI).
4. Run over the repo's existing worked-example TMLs before enabling as an error -- expect real
   findings, and triage rather than weaken the check.

**Target:** with or immediately after BL-178. Tier 1: the promotion is the point, and it stops the
class recurring.

---

## BL-184 -- Worked-example reproducibility: nothing re-runs the ground truth `Tier 2`

**Filed:** 2026-07-29.
**Source:** 2026-07-29 TPC-DS conversion-fidelity cross-validation
(`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`) §3.9, second validator promotion.
**Affects:** `tools/ts-cli/tests/test_worked_examples.py`,
`tools/smoke-tests/`, `agents/shared/worked-examples/snowflake/`,
`agents/shared/worked-examples/databricks/`, `agents/shared/CLAUDE.md`.
**Status:** OPEN.

`agents/shared/CLAUDE.md` makes the worked examples **ground truth** -- each was verified
end-to-end against a live instance and dated. Nothing re-runs them. `test_worked_examples.py`
re-validates the *documented output* against `check_sv_yaml`/`check_tml`, which asserts the
document is well-formed, not that today's converter still produces it; only
`test_databricks_to_golden.py` runs a real emitter against a fixture. That gap is exactly why a
live-verified output could silently stop being reproducible: BL-178 broke
`ts-from-snowflake-identifier-resolution.md` on 2026-07-22 and it went unnoticed until this
review re-ran the example by hand and found 4 of 8 formulas dangling.

**The test that would have caught it:** re-run each Snowflake worked example's DDL through
`parse-sv -> translate-formulas -> build-model` and diff the emitted `formulas[]` block against
the block the worked example documents. Same shape for the Databricks examples via
`parse-mv -> translate-formulas -> build-model`.

**Size it for the baseline it will actually find -- this is the load-bearing caveat.** A naive
diff against the documented output will **not** come back clean once BL-178 is fixed.
`ts-from-snowflake-identifier-resolution.md` also diverges on **6 of 18 display names and 2
formula ids** for an entirely unrelated reason: coverage row 14's first-synonym-to-name promotion
landed 2026-06-15, *after* the 2026-06-13 verification, so the documented names predate current
documented behaviour. Two of those divergences are therefore *correct current behaviour* against a
*stale document*, not regressions. Decide up front which it is for each divergence:

- re-verify the worked example live and update the documented output (preferred -- it restores the
  document to ground truth, and BL-178's step 4 has to go live on this example anyway, so bundle
  them); **or**
- scope the assertion narrowly (formula ids and `expr` reference-resolution only, not display
  names) and record in the worked example *why* the names are excluded.

Do **not** land a test that silently normalises the difference away -- that reproduces the
original failure mode one level up.

**Approach:**

1. Land after BL-178, whose step 4 produces the re-verified baseline.
2. One parametrised test per worked example, driven off a small manifest so a new worked example
   is covered by adding a row (the same binding discipline as `check_formula_catalog.py`).
3. Where a divergence is accepted, name it in the manifest with a reason -- an auditable declared
   difference, not a silent normalisation (the same "documented-lossy vs lossless" two-bar pattern
   BL-166 item 5 adopts).
4. If a worked example needs a live instance to re-verify, the offline test asserts the frozen
   documented output and a `tools/smoke-tests/` entry covers the live leg -- do not skip the
   offline half because the live half is unavailable.

**Target:** immediately after BL-178. Tier 2 rather than 1 only because it depends on that fix
landing first; the gate itself is the higher-value half of the pair.
