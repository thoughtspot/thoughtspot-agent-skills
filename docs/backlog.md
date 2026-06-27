# Backlog

Improvement ideas identified but not yet scheduled. Each item includes context on
why it matters and what the approach would be.

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

---

## BL-005 — Databricks runtime: ThoughtSpot client + conversion skills

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
[`docs/superpowers/specs/2026-06-11-databricks-ts-client-design.md`](../superpowers/specs/2026-06-11-databricks-ts-client-design.md)

---

## BL-007 — Array/VARIANT column handling pattern for model coaching

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

## BL-008 — Soft/overridable exclusion rules in model-instructions-schema

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

---

## BL-009 — Tableau conversion mapping gaps (functions, dynamic sets, geospatial, sources)

**Source:** Audit of 127 workbooks in `tableau-migration-testing/twb/inactive/` (2026-06-10)
**Affects:** ts-convert-from-tableau, `agents/shared/mappings/tableau/tableau-formula-translation.md`
**Status:** Complete — all 5 phases shipped. Phase 1 (PR #48), Phase 2a (PR #49), Phase 2b (2026-06-12), Phase 2c/3/4 (PR #66), Phase 5 data blending (2026-06-14)
**Full plan:** [`superpowers/plans/2026-06-11-tableau-mapping-gaps.md`](superpowers/plans/2026-06-11-tableau-mapping-gaps.md)

> **Phase 1 (function table) — DONE (PR #48):** added DATEPARSE, EXP, trig (radians→degrees fix),
> STARTSWITH/ENDSWITH, PI/RADIANS/DEGREES composites, PROPER/ASCII/CHAR/REGEXP_*/FINDNTH
> scalar pass-through, WINDOW_*/RUNNING_COUNT/DATETIME notes; fixed the UPPER/LOWER bug; all
> grounded against the 26.6.0 formula reference + live-validated. Introduced the PT1 pass-through
> policy. Open-items #12/#13/#14 closed.
> **Phase 2a (static sets → column sets) — DONE (PR #49, 2026-06-12, live/UI-verified on se-thoughtspot):**
> bind via `worksheet:` (not `model:`); `%null%` via the `{Null}` grouping value; `except` member-list
> via `operator: NE`; formula-column anchors (resolve calc id → display name + emit formula column);
> set controls → interactive filter + migrate anchor calc + drop IF-[Set] scaffolding; EVERY set
> conversion flagged for user review (Step 7 + Step 12). Worked example added.
> **Phase 2b (Top-N/Bottom-N sets → query sets) — DONE (2026-06-12, live-verified on se-thoughtspot):**
> `cohort_type: ADVANCED`, `cohort_grouping_type: COLUMN_BASED`, embedded answer with rank formula
> (`rank(sum(measure),'desc'/'asc')`) + parameter-filter formula (`[formula_rank] <= [alias::param]`).
> Stepped range params → `list_config`. Detection: `function='end'`, `end='top'/'bottom'`, `count`
> param/literal, ordering measure. Full emission template + worked example
> (`topn-set-to-query-set.md`) added. The Dynamic-Sets gap (previously noted at line ~500) is now
> addressed for Top-N/Bottom-N. Open-items #10 Phase 2b closed.
> **Phase 2c/3/4 (PR #66):** All set operations now translatable (condition-based, member-list
> intersect, all-except-Top-N, mixed computed); geospatial detect+log policy; unsupported
> source policy (google-sheets, OGR, webdata); Redshift/Postgres dialect notes; INDEX()
> prevalence note. Open-items #10–#17 closed.
> **Phase 5 — Data blending (2026-06-14):** blend-connected datasources merge into single
> model, linking fields → LEFT_OUTER inline joins, cross-datasource formulas resolve within
> merged model. Affects 90/140 audited workbooks (64%). Star and transitive topologies
> supported. Open-item #8 closed.
> **Phase 2c (set operations + condition sets) — DONE (2026-06-14):** member-list intersect →
> GROUP_BASED cohort of common members; all-except-Top-N → query set with inverted rank filter
> (`[rank] > N`); condition-based sets (`function='filter'`) → query set with boolean condition
> formula; mixed computed set operations (member ∩ Top-N, condition ∩ condition, nested set-ops)
> → multi-formula query set with combined filters in `search_query`. All Tableau set types now
> translatable except set controls (→ interactive filter) and set actions (no equivalent).
> **Phase 3 (geospatial) — DONE (2026-06-14):** explicit detect+log policy for MAKEPOINT/MAKELINE/
> DISTANCE/BUFFER/AREA. MAKEPOINT decomposes lat/lon to individual attribute columns. Added to
> classifier regex, untranslatable table, and dedicated audit report row.
> **Phase 4 (source coverage) — DONE (2026-06-14):** unsupported-source policy (google-sheets,
> ogrdirect, webdata-direct, CustomMapbox → skip + log); Redshift/Postgres dialect notes for
> pass-through SQL; INDEX() prevalence note (recommend rank() / top-N substitute).

### Problem

Corpus audit (53,126 calc fields, 411 dashboards) surfaced patterns the skill does not map.
Confirmed absent from the mapping file as of 2026-06-11 (manual-groups→cohort is already
shipped via changelog 1.5.5 and is NOT part of this):

- **Dynamic Sets** (Top-N sets, `<groupfilter>`) — 86 files, zero mapping. Largest gap.
  Target TML already exists: `agents/shared/schemas/thoughtspot-sets-tml.md`.
- **Missing function-table entries** — `DATEPARSE` (93×, highest-value), `REGEXP_*`/`FINDNTH`,
  `MAKEPOINT`(362×)/`MAKELINE` geospatial (no policy → silent drop), `WINDOW_STDEV/PERCENTILE/
  COUNT/MEDIAN` + `RUNNING_COUNT` (~80× mis-flagged), `EXP/PI/trig/PROPER/ASCII/CHAR/
  STARTSWITH/ENDSWITH`. (`QUARTER`/`WEEK` already partially present — verify, don't duplicate.)
- **Source coverage** — Redshift(15)/Postgres(1) RDBMS examples are Snowflake-dialect only;
  no "unsupported source" policy for google-sheets/drive, ogr/spatial, webdata, mapbox.

### Proposed approach

Phased per the plan: (1) fill the function table, (2) add dynamic-Sets translation wired to
`thoughtspot-sets-tml.md`, (3) explicit geospatial policy, (4) broaden source coverage + INDEX
prevalence note. Validate with the tiered test workbooks listed in the plan via the
`tableau-migration-testing` harness. Open-items #10–#17 (drafted in the plan) append to
`agents/cli/ts-convert-from-tableau/references/open-items.md`.

---

## BL-010 — `ts-load-source-data` skill (generic Snowflake/Databricks loader)

**Source:** Generalising the Snowflake-only `tableau-migration-testing` loader (2026-06-11)
**Affects:** NEW skill `agents/cli/ts-load-source-data`; `tableau-migration-testing` harness
**Status:** Not started
**Full plan:** [`superpowers/plans/2026-06-11-ts-load-source-data.md`](superpowers/plans/2026-06-11-ts-load-source-data.md)

### Problem

The convert-from skills assume source tables already exist in a warehouse, but there's no
warehouse-agnostic way to create + load them. The existing harness is Snowflake-only
(PUT/stage/COPY INTO, `snowflake.connector`).

### Proposed approach

New skill with a generic loader core behind a `WarehouseAdapter` (Snowflake + Databricks).
Pluggable manifest producers (TWB primary, CSV-dir, manifest JSON). **Decisions:** Databricks
load = `INSERT … VALUES` batches (no volume); **DB layer only — no connection creation** (hands
off to BL-011); Snowflake supports `method:python` AND `method:cli`; warehouse chosen by profile
auto-detect → ask. Prove in the harness first, then promote into the skill. Reuses
`ts-profile-snowflake` / `ts-profile-databricks`. **Open question:** non-prod Databricks
workspace + catalog for the live load test.

**Status (2026-06-26):** v1 shipped — Snowflake loading (both `method:python` and
`method:cli`), schema inference, synthetic data generation, four input modes.
Databricks loading deferred to v2.

---

## BL-011 — `ts-object-connection-create` skill + `ts connections create` CLI

**Source:** Smoke test of `connection/create` on se-thoughtspot (2026-06-11)
**Affects:** NEW skill `agents/cli/ts-object-connection-create`; `tools/ts-cli` (`connections create`)
**Status:** Not started
**Full plan:** [`superpowers/plans/2026-06-11-ts-object-connection-create.md`](superpowers/plans/2026-06-11-ts-object-connection-create.md)

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

---

## BL-013 — Metadata-only sync mode for converters (names, comments, synonyms → matched columns)

**Source:** Feature request (2026-06-12)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv (mode option at start); possibly ts-convert-from-tableau later
**Status:** Superseded by BL-021 (metadata-only sync is the "Modified metadata" subset of BL-021's Mode D — implement there)

### Problem

When a ThoughtSpot model already exists from a prior conversion, the user may want to refresh
**only the metadata** — column display names, descriptions/comments, and synonyms — onto
**matched columns**, without touching structure, formulas, joins, `column_type`, aggregation, or
recreating any object. Today there's no lightweight path:

- **Snowflake SV** has Mode C (Step 1.5 → C1–C6), but it's a **full** structural + metadata diff —
  heavier than "just sync the labels/comments/synonyms".
- **Databricks MV** has **no** update/mode selection at all (single Mode A) — so there's no way to
  re-sync metadata onto an existing model.

### Proposed approach

Add a **metadata-only sync** mode, surfaced as a choice at the start of each converter
(SV: a new option at Step 1.5 alongside Modes A/B/C; DBX: introduce mode selection — this is also
DBX's first update path, related to its update open-item):

1. **Match** source columns to existing TS model columns by name (case-insensitive last segment).
2. **Update matched columns only:** `display_name` ← source caption/alias/title; `description` ←
   source comment; `properties.synonyms` ← source synonyms. Nothing else.
3. **Never touch:** formulas, joins, `column_type`, aggregation, `index_type`, table structure.
   **Preserve** user-added `ai_context` and Data Model Instructions (offer merge, don't overwrite —
   per the Mode C principle).
4. **Report** unmatched columns in both directions (in source but not model; in model but not
   source) without changing them — flag, don't delete.
5. Reuse SV Mode C's `_normalise_expr`/diff helpers and the per-column MERGE/UPDATE/KEEP prompt
   pattern where applicable; hand off to `/ts-object-model-coach` after.

### Files affected

- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — Step 1.5 mode option + metadata-sync sub-workflow
- `agents/cli/ts-convert-from-databricks-mv/SKILL.md` — add mode selection + metadata-sync sub-workflow
- `agents/cli/ts-convert-from-snowflake-sv/references/update-mode-spec.md` — document the metadata-only variant
- Source→TS metadata mapping: comment→`description`, synonyms→`properties.synonyms`, caption/alias→`display_name`

---

## BL-014 — Databricks MV → ThoughtSpot mapping coverage review (parallel to SV gap analysis + Tableau audit)

**Source:** Coverage-review gap identified 2026-06-12 (SF has one, DBX does not)
**Affects:** ts-convert-from-databricks-mv
**Status:** Not started

### Problem

There is a systematic mapping-coverage review for **Snowflake SV** (`docs/sv-to-ts-gap-analysis.md`,
13 gaps, BL-003 umbrella) and for **Tableau** (127-workbook audit, BL-009), but **none for
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

## BL-015 — Pre-conversion Audit/feasibility mode for SF SV and DBX MV (parity with Tableau Audit mode)

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

## BL-016 — Conversion mapping-file naming/structure consistency

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

## BL-019 — Databricks MV: audit mapping gaps equivalent to BL-018 (SV parity)

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

## BL-020 — Tableau: audit mapping gaps equivalent to BL-018 (SV parity)

**Source:** BL-018 parity review (2026-06-13)
**Affects:** ts-convert-from-tableau, tableau-tml-rules.md
**Status:** Not started
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

## BL-021 — Delta sync mode for SV and MV converters (selective, additive, TS-side-preserving)

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

## BL-022 — Unjoined table suggestion pattern (cross-converter)

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

## BL-023 — Coverage matrix reference docs for Databricks MV and Tableau converters

**Source:** BL-018 completion — SV converter now has `references/coverage-matrix.md` (2026-06-14)
**Affects:** ts-convert-from-databricks-mv, ts-convert-from-tableau
**Status:** Not started
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

## BL-024 — Close the row-offset table-calc gap with window functions (INDEX/LOOKUP/FIRST/LAST/SIZE)

**Source:** Sigma-vs-ThoughtSpot Tableau-migration comparison over a 140-workbook corpus (2026-06-14)
**Affects:** ts-convert-from-tableau (primarily); pattern applies to any converter that translates table calcs
**Status:** Implemented (2026-06-14) — tiered decision tree in SKILL.md + formula translation reference. Needs live verification against workbooks with INDEX/LOOKUP calcs.
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

## BL-025 — Review connection-selection parity for the Databricks Genie agent skill

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

## BL-027 — Explicit table→ThoughtSpot binding (user-supplied GUID / db.schema.table) instead of search-and-guess

**Source:** Live Catalog Health Workbook migration session (2026-06-17)
**Affects:** ts-convert-from-tableau (Step 4 / 4.5 — physical table resolution)
**Status:** Open
**Related:** BL-025 (connection-selection N/F/L prompt, PR #88), BL-022 (unjoined-table suggestion)

### Problem

The skill resolves each Tableau table to a warehouse table by parsing the TWB
relation name (`[DB].[SCHEMA].[TABLE]`, `[sqlproxy]`, etc.) and then matching it
against the chosen connection — effectively a search-and-guess. When the parsed
name is wrong, the generated table/SQL-View TML binds to a non-existent object and
fails at `VALIDATE_ONLY`/import with "table does not exist", with no easy way for
the user to correct the binding.

This was hit live on the **Catalog Health Workbook**: the two **sqlproxy
(Published Datasource)** sources resolved from `connection.get('dbname')`, which
was a mangled concatenation
(`CATALOG_HEALTH_PRODUCT_COMPLETENESSPRD_DATALAKEHOUSE_..._DATA_CATALOG`). The
real object is `PRD_DATALAKEHOUSE.DATA_CATALOG.CATALOG_HEALTH_PRODUCT_COMPLETENESS`
and it existed in Snowflake (as `AGENT_SKILLS.DATA_CATALOG.<table>`), but the
skill reported it missing because it bound to the garbage name. The same class of
failure occurs whenever the TWB's `[DB]` differs from the target connection's
database, or a Published Datasource hides the real schema/table.

### Proposed approach

Add an explicit **table-binding step** so the user can pin each Tableau table to a
real ThoughtSpot/warehouse object rather than relying on inference:

1. **Show the resolved binding per table** — after Step 4/4.5, print a table:
   `Tableau ref → resolved db.schema.table (+ connection)` with a confidence flag.
2. **Allow per-table override**, accepting either:
   - an existing **ThoughtSpot table GUID** (look it up, confirm its
     db/schema/db_table, and bind to it), or
   - an explicit **`db` / `schema` / `db_table`** triple.
3. **Force confirmation for low-confidence bindings** rather than silently emitting
   a guess: sqlproxy `dbname` that isn't a clean identifier; `[DB].[SCHEMA].[TABLE]`
   where `DB` ≠ the selected connection's database; any name not found on the
   connection during a (optional) live existence check.
4. **Persist the mapping** (a `table_mapping` override, mirroring the
   tableau-migration-testing harness's `table_mapping.csv`) so re-runs and audit
   mode don't re-prompt.
5. **sqlproxy resolution fix** — for Published Datasources, prefer the real
   `schema.table` parsed from the datasource caption
   (`... (DB.SCHEMA.TABLE) (SCHEMA)`) / metadata-records over the opaque `dbname`,
   and surface it as the default in the binding table.

### Files affected

- `agents/cli/ts-convert-from-tableau/SKILL.md` — new per-table binding/override step (Step 4/4.5); low-confidence confirmation gate
- `agents/shared/mappings/tableau/tableau-tml-rules.md` — sqlproxy `dbname` resolution rule; explicit-binding + cross-database notes
- `agents/cli/ts-convert-from-tableau/references/open-items.md` — sqlproxy mis-binding + cross-DB binding items

---

## BL-028 — Audit mode: assess the visualization layer (chart types + dashboard→liveboard), not just the data layer

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

## BL-026 — `ts-object-liveboard-builder` skill: build the best liveboard for a domain + suggest KPIs

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

## BL-029 — Coverage matrices for the remaining three conversion skills

**Related:** `tools/validate/check_coverage_matrix.py` BACKLOG set; repo quality audit (codification follow-up)

### Problem

Three `ts-convert-*` skills still lack a `references/coverage-matrix.md` and are exempted in
the validator's `BACKLOG` set: `ts-convert-from-databricks-mv`, `ts-convert-to-snowflake-sv`,
`ts-convert-to-databricks-mv`. The original justification ("add after Tableau matrix ships")
went stale once the Tableau matrix shipped, and was dateless — so the exemption never
expired. The validator now requires every BACKLOG justification to carry a target date or a
`#NNN`/`BL-NNN` reference; these three point here with a target of **2026-08-31**.

### Proposed approach

Author a coverage matrix for each, mirroring the structure of the shipped
`ts-convert-from-snowflake-sv` and `ts-convert-from-tableau` matrices (Mapped Constructs +
Unmapped Constructs/Limitations, `Notes` as the last column, no `Last verified:` line). Then
remove each skill from the `BACKLOG` set in `check_coverage_matrix.py` as its matrix lands.

**Target:** 2026-08-31.

---

## BL-030 — ThoughtSpot model-level NL instructions: migrate model-coach off manual paste to the `ai/instructions` API

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

## BL-031 — Snowflake to-SV converter: emit `facts[]` / `sample_values` / filter-labels in YAML mode

**Source:** full audit sweep 2026-06-17 (angle 13), findings #4–#6. Referenced from `agents/shared/schemas/snowflake-schema.md`.

### Problem

The published semantic-view YAML spec now accepts constructs the converter still treats as
DDL-only or unsupported: per-table `facts:`, dimension `sample_values:` (Snowflake-recommended
for Cortex Analyst accuracy), `labels: [filter]`, `unique:`, `cortex_search_service:`,
`access_modifier:`. The schema doc has been corrected (2026-06-17); the **converter emit
behaviour has deliberately not changed** pending verification.

### Approach

1. Verify each construct against a live `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` round-trip
   (the agent verified against published docs, not a live warehouse).
2. Update `to-snowflake-sv` to emit `facts[]` natively (instead of down-converting to metrics)
   and populate `sample_values` for dimensions; stop stripping the now-valid fields.
3. Bump the `snowflake-schema.md` currency anchor to a live-verified date.

**Target:** 2026-09-30.

---

## BL-032 — Databricks Metric Views: parser support for GA constructs (`materialization:`, `fields:`), retire v0.1 framing

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

**Target:** 2026-09-30.

---

## BL-033 — Dependency & CI supply-chain hygiene

**Source:** full audit sweep 2026-06-17 (angle 16), findings #16–#19.

### Problem

No dependency-vulnerability gate (no `pip-audit`/`safety` step, no `.github/dependabot.yml`);
`requires-python` floor is `>=3.9` (EOL Oct 2025, never exercised — CI tests only 3.12); runtime
deps are floor-only with no lockfile (`requests>=2.28` permits CVE-affected <2.32.0); CI installs
unpinned tooling (`pip install pytest pyyaml`).

### Approach

1. Add a `pip-audit` job to `validate.yml` + a `.github/dependabot.yml` (pip + github-actions).
2. Raise the Python floor to `>=3.10` (or add 3.10/3.11 to a CI matrix if the floor is kept).
3. Add a constraints/lockfile; bump the `requests` floor to `>=2.32.0`; pin or extras-ify CI tooling deps.

**Target:** 2026-08-31.

---

## BL-034 — tools/ & ts-cli quality polish

**Source:** full audit sweep 2026-06-17 (angles 4, 5, 14), findings across tools-quality / ts-cli-gaps / performance.

### Problem

A cluster of low/medium tool-quality issues: `model-coach` exports feedback TML one GUID per
round-trip (`ts tml export` takes multiple GUIDs — pure batch win, no attribution trade-off);
`databricks_sql` polls only on `PENDING` and ignores `RUNNING`; `import_tml` GUID back-fill uses a
brittle first-name regex; `report` deep-probe swallows all errors as "alias not supported"; `report`
walker re-queries leaf ANSWER/LIVEBOARD dependents; `report` resolver multi-part name lookup likely
never matches 2-/3-part names; the `model-coach` changelog claims a FEEDBACK export flag the CLI
rejects; `.gitignore` has ~4 stale entries pointing to non-existent paths.

### Approach

Fix opportunistically, each with a focused test. The batch-export and `databricks_sql` `RUNNING`
poll are the highest-value. None are urgent.

**Target:** 2026-10-31.

---

## BL-035 — Test-suite integrity gaps

**Source:** full audit sweep 2026-06-17 (angle 6).

### Problem

Two assertions can't actually fail: `ts-dependency-manager`'s round-trip step treats an **ERROR
import as success** (the round-trip assertion is vacuous), and the `to-databricks` DDL "validation"
asserts substrings on a string the test itself just built (tautological). Plus
`smoke_ts-metadata-report.py` is orphaned (never run by any harness, leaving `ts metadata report`
unexercised), the `smoke-tests/README.md` Scripts table is stale (lists 3 of 11), and the
business-days recipe smoke header references an old skill name.

### Approach

1. Make the dependency-manager round-trip step fail on a non-OK import status.
2. Replace the tautological to-databricks assertion with a real parse/round-trip check.
3. Wire or remove the orphaned report smoke test; refresh the smoke README table; fix the stale header.

**Target:** 2026-10-31.

---

## BL-036 — Databricks-native connection creation

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

## BL-037 — Recipe skills for common data investigation patterns (cohort, funnel, segmentation, time-series, A/B, RCA)

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

## BL-039 — `ts-object-answer-promote`: support embedded Answers and set/cohort promotion

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
## BL-038 — `ts-recipe-formula-weighted-average` skill

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
**Status:** Open

### Problem

`agents/databricks/shared/schemas/` duplicates files from `agents/shared/schemas/` but is gitignored — no validator catches drift. The Databricks Genie Code skills read stale guidance when the canonical files are updated.

### Approach

Make `agents/databricks/deploy.sh` copy the relevant files from `agents/shared/` at deploy time (same pattern as CoCo's `stage-sync.sh`), eliminating the local copy as a source of truth. Remove `agents/databricks/shared/schemas/` from the repo and add the copy step to the deploy script.

**Target:** Next time Databricks skills are actively worked on. No date set.

---

## BL-041 — `ts-recipe-model-timezone-bridge-snowflake` skill

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

## BL-043 — Evaluate two-phase import and formula translation pipeline for other conversion skills

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

---

## BL-042 — Tableau REST API integration: live-instance testing

**Source:** Design spec `docs/superpowers/specs/2026-06-26-tableau-api-integration-design.md`
**Affects:** ts-profile-tableau, `ts tableau` CLI commands, ts-convert-from-tableau Step 3.5
**Status:** Complete — API connectivity verified on live Tableau Cloud instance (PR #121 signin/datasources, PR #122 download with CSV validation); Step 3.5 sqlproxy resolution shipped (PR #121)

### Problem

The Tableau REST API integration (profile skill, CLI commands, Step 3.5) was built from
API documentation and the sigma-migration-skills reference implementation. Core API
operations (signin, datasource search, VizQL read-metadata, workbook download) have been
verified against a live Tableau Cloud instance, but the full end-to-end Step 3.5 flow
(sqlproxy detection → API resolution → field merge → table creation) has not been tested
as part of a complete migration.

### Proposed approach

1. Complete a full `ts-convert-from-tableau` migration of the DunderMifflin workbook
   (confirmed sqlproxy with published datasource)
2. Verify field metadata merge produces correct table TML column types
3. Test PAT auth path when PATs are enabled on the developer site
4. Document any API response shape surprises in `references/open-items.md`

---

## BL-044 — Tableau: detect orphan inherited calcs in copied datasources

**Source:** CPG Merch Promotion Performance migration (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 3, A2, A4, 5b, 12
**Status:** Implemented — Step 3g orphan detection, A4 orphan section, 5b exclusion guard, Step 12 root cause category, migrate-mode E/A prompt

### Problem

When a Tableau published datasource is a **copy** of another (TWB name contains `(copy)`,
or the datasource is a subset clone), it inherits **all calculated fields** from the
original — including ones that reference tables no longer present in the copy. Tableau
silently ignores these orphan calcs; they are non-functional dead weight.

In the CPG Merch migration, the tentpole datasource was a copy of the main datasource
with only 3 of the original 9 tables. It inherited 116 of 117 formulas from the main
datasource, but 41 of them referenced tables (PRODUCT_METRICS, CATEGORY_SHARE,
DAILY_METRICS, CUSTOMER_ORDERS) that don't exist in the copy. These orphan calcs were
translated, carried through to Phase 2 import, and failed — wasting ~30 minutes of
migration time.

The sigma-migration-skills repo handles this indirectly via Jaccard similarity clustering
on field overlap (detecting duplicate datasources) and scoped calc extraction per
dashboard. Neither approach explicitly detects orphan calcs.

### Proposed approach

1. **Step 3 (parse) — orphan calc detection.** After extracting tables and calcs from
   each datasource, cross-reference every calc's `[TABLE::COL]` references against the
   datasource's actual table set. If a calc references a table not in the datasource,
   mark it as an orphan. Transitively mark any calc that depends on an orphan.

2. **Step A4 (audit report) — orphan section.** Add an "Orphan inherited calcs" section
   to the audit report showing: count, the referenced missing tables, and a note that
   these calcs are non-functional in Tableau and will be excluded from migration.

3. **Step 5b / Phase 2 — automatic exclusion.** Exclude orphan calcs from the formula
   translation pipeline. Currently these get translated, fail at import, and consume
   retry cycles. Excluding them up front saves time and tokens.

4. **Step 12 (migration report) — orphan tally.** Report orphan calcs separately from
   "excluded due to translation failure" — they are a different category (never
   functional, not a translation gap).

5. **User confirmation.** During migrate mode, surface the orphan count and list of
   missing tables. Ask the user to confirm exclusion — in rare cases they may want to
   add the missing tables to the model instead.

### Detection heuristic

```python
# After Step 3b extraction, for each datasource:
ds_tables = {mt['name'].upper() for mt in datasource['model_tables']}
orphan_calcs = set()
for calc in datasource['calculated_fields']:
    for ref in re.findall(r'\[([^\]]+)::', calc['expr']):
        if ref.upper() not in ds_tables:
            orphan_calcs.add(calc['name'])
            break
# Transitively mark dependents of orphans
```

---

## BL-045 — Tableau: blend post-aggregation semantics warning + audit flag

**Source:** CPG Merch Promotion Performance migration (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 3e, 5b, A4, 7, 12; data-blend-to-model worked example
**Status:** Implemented — A4 blend risk table (HIGH/MED/LOW classification), Step 7 HIGH-risk R/S/M prompt, Step 12 blend-context review category. Remaining: worked example caveat section (#3), coverage matrix note (#4)

### Problem

Tableau blending is a **post-aggregation LEFT JOIN**: the secondary datasource is
aggregated independently to the linking-field grain, then joined to the primary's
aggregated results. This is fundamentally different from a ThoughtSpot model join, which
joins at the **row level** and lets the query engine aggregate afterward.

The current skill (Step 5b) merges blended datasources into a single model with
`LEFT_OUTER` joins. For simple cases (one fact + one dimension/reference table), the
result is equivalent. But when **both sides are fact tables at different grains**, a
row-level join produces fan-out and **wrong aggregation results** — exactly the scenario
blending was designed to avoid.

The worked example (`data-blend-to-model.md`) mentions "ThoughtSpot's chasm trap
protection aggregates each fact independently" but does not explicitly flag the semantic
difference or warn that results may diverge.

The sigma-migration-skills repo explicitly documents this: "Tableau aggregates the
secondary to the linking-field grain before joining" and recommends grouped helper
elements to reproduce the aggregation level.

### Proposed approach

1. **Step A4 (audit report) — blend semantics flag.** When blending is detected, add a
   warning section:
   ```
   ⚠ Data Blending — post-aggregation semantics
     Tableau blends aggregate the secondary datasource independently before
     joining. ThoughtSpot model joins operate at row level. If both sides are
     fact tables at different grains, aggregation results may differ.
     Blends detected: {N}
     ┌─────────────────────────────────────────────────────────────┐
     │ Primary DS        Secondary DS       Link Cols   Risk      │
     ├─────────────────────────────────────────────────────────────┤
     │ {name}            {name}             {cols}      {H/M/L}   │
     └─────────────────────────────────────────────────────────────┘
     Risk: HIGH = both sides have measures (fact×fact blend)
           MEDIUM = secondary has measures but is likely a reference table
           LOW = secondary is dimension-only
   ```

2. **Step 7 (review checkpoint) — user confirmation.** For HIGH-risk blends, explicitly
   ask the user: "This blend joins two fact tables. ThoughtSpot's row-level join may
   produce different aggregation results than Tableau's post-aggregation blend. Options:
   (a) proceed with row-level join (ThoughtSpot chasm trap may handle it),
   (b) create a SQL View that pre-aggregates the secondary to the linking grain,
   (c) keep as separate models (no blend merge)."

3. **Worked example update.** Update `data-blend-to-model.md` to add a "Semantic
   Caveat" section documenting the post-aggregation difference and when it matters.

4. **Coverage matrix.** Update row #4 (Data blending) notes to add: "Post-aggregation
   semantics: secondary is aggregated to linking grain in Tableau; ThoughtSpot joins at
   row level — verify results when both sides are fact tables."

### Risk classification heuristic

```python
# For each blend edge in blend_graph:
secondary_ds = datasources[target_ds]
secondary_has_measures = any(
    col['role'] == 'measure' for col in secondary_ds['columns']
)
primary_has_measures = any(
    col['role'] == 'measure' for col in datasources[source_ds]['columns']
)
if primary_has_measures and secondary_has_measures:
    risk = 'HIGH'  # fact × fact — aggregation may diverge
elif secondary_has_measures:
    risk = 'MEDIUM'
else:
    risk = 'LOW'
```

---

## BL-046 — Tableau: formula translation determinism improvements

**Source:** CPG Merch Promotion Performance migration observations (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 5b, 7, A3, A4; ts-cli `ts tableau translate-formulas`
**Status:** Implemented (ts-cli v0.17.0) — all 7 items complete. #1 ifnull(X,0) stripping (default-on for measures), #2 sum_if/count_if/average_if conversion (default-on), #3 rank() completion, #4 operator spacing, #5 if/then/else structural validation (balanced parens/brackets, orphaned else detection), #6 physical ref qualification, #7 name clash detection

### Problem

The CPG Merch migration (161 + 117 formulas) revealed several patterns where the formula
translation pipeline produces errors that require manual intervention, adding ~30–60
minutes and significant token cost. These are not translation gaps (the functions exist
in ThoughtSpot) but determinism gaps — known patterns that should produce correct output
on the first pass.

Observations from the migration:

1. **`ifnull(measure, 0)` is unnecessary.** ThoughtSpot query generation handles NULL
   automatically. The pattern `ifnull(if(PERIOD_TYPE='promo') then SALES else null, 0)`
   should simplify to `if(PERIOD_TYPE='promo') then SALES else null`. Prompt the user
   whether to keep or strip `ifnull` wrapping on measures.

2. **`sum_if` / `unique_count_if` / `average_if` alternatives.** Tableau's
   `IF condition THEN measure END` (no ELSE) translates to
   `if(condition) then measure else null` in ThoughtSpot. For aggregated measures, the
   native `sum_if(condition, measure)` is simpler and avoids the missing-ELSE error
   class entirely. The pipeline should offer this as an alternative.

3. **`rank()` requires 2 arguments.** ThoughtSpot `rank(expr, 'asc'|'desc')` needs the
   sort direction. The pipeline should always emit both arguments. This is documented in
   `thoughtspot-formula-patterns.md` but the Tableau translation step doesn't enforce it.

4. **Missing spaces around operators.** Expressions like `[A]-[B]` fail; ThoughtSpot
   requires `[A] - [B]`. The pipeline's operator-spacing step should catch all binary
   operators (`+`, `-`, `*`, `/`, `=`, `!=`, `>`, `<`, `>=`, `<=`).

5. **`if/then/else` structure validation.** ThoughtSpot `if` is self-terminating (no
   `end` keyword) and every `if` MUST have an `else`. The pipeline should validate this
   structurally before import, not rely on import errors to surface it.

6. **Physical column refs must be table-qualified in model formulas.** `[SALES]` fails;
   `[TABLE::SALES]` works. The qualifier step should enforce this for ALL physical column
   references, not just ambiguous ones.

7. **Formula/column name clash detection.** Physical column `SALES` and formula `Sales`
   collide case-insensitively. The pipeline should detect these at translation time and
   auto-rename the formula (e.g., `Promo Sales`) before import.

### Proposed approach

Add or fix these transforms in `ts tableau translate-formulas` (ts-cli):

| # | Transform | Current state | Fix |
|---|---|---|---|
| 1 | Strip `ifnull(measure, 0)` | Not implemented | Add as optional transform; prompt user |
| 2 | `IF/THEN/END` → `sum_if` etc. | Not implemented | Detect `SUM(IF...THEN...ELSE NULL)` → `sum_if(condition, expr)` |
| 3 | `rank()` second arg | Missing | Always emit `'desc'` (or infer from Tableau sort) |
| 4 | Operator spacing | Partial | Regex all binary operators |
| 5 | `if/else` validation | Not pre-validated | Structural check before import |
| 6 | Physical ref qualification | Partial (ambiguous only) | Qualify ALL physical column refs |
| 7 | Name clash detection | Not implemented | Case-insensitive check; auto-rename formula |

**See also:** BL-049 (pipeline performance) for the architectural efficiency improvements
that reduce cost even when individual transforms are correct. BL-050 (systematic
pre-transforms) for the ordered transform pipeline that codifies reactive Phase 2 fixes.

---

## BL-047 — Tableau: audit should report formula complexity and effective migration rate

**Source:** CPG Merch Promotion Performance migration observations (2026-06-27)
**Affects:** ts-convert-from-tableau Steps A3, A4
**Status:** Implemented — complexity distribution (Simple/Medium/Complex), realistic coverage estimate (subtracts orphans + circular + unresolvable), per-datasource breakdown

### Problem

The audit mode (Step A3/A4) classifies formulas by translation tier (Native, LOD,
Pass-through, etc.) and reports cross-reference depth. But it does not capture:

1. **Formula complexity** — a formula with 5 nested `if/then/else` and 3 cross-references
   is much harder to migrate than a simple `SUM([col])`. The audit should report a
   complexity distribution so users can estimate migration effort.

2. **Effective migration rate vs audit promise** — the CPG Merch audit would have shown
   high syntax-level coverage, but the actual migration rate was 73% (Model 1) and 54%
   (Model 2) after accounting for orphan calcs, cross-reference inlining failures,
   structural errors, and missing tables. The gap between "audit says migratable" and
   "actually migrates" needs to be visible in the audit.

3. **Blend + orphan impact on coverage** — the audit shows formula tiers per-datasource
   but doesn't account for orphan calcs (BL-044) or blend post-aggregation risk (BL-045).
   These should reduce the reported coverage number.

### Proposed approach

1. **Complexity scoring per formula.** Score based on: nesting depth, cross-reference
   count, function count, operator count, string length. Report distribution:
   `Simple (1-2) / Medium (3-5) / Complex (6+)`.

2. **Effective coverage estimate.** After tier classification, subtract: orphan calcs
   (BL-044), formulas with unresolvable circular deps, formulas requiring manual
   structural fixes (broken if/else, missing args). Report both "syntax coverage" and
   "effective coverage" with the gap explained.

3. **Per-model breakdown.** When multiple datasources exist, report coverage per
   datasource/model — not just workbook-wide. The CPG Merch tentpole datasource had 54%
   effective coverage vs 73% for the main datasource; a combined number would hide this.

---

## BL-048 — Tableau: user review checkpoint before formula import (Step 7.5 enhancement)

**Source:** CPG Merch Promotion Performance migration observations (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 7, 7.5
**Status:** Implemented — Phase 1.5 checkpoint added between base model import and formula import (yes/search/no prompt)

### Problem

The current flow imports the base model (Phase 1), then immediately proceeds to formula
import (Phase 2). The user has no opportunity to review the base model in ThoughtSpot
(check table bindings, column types, join correctness) before formulas are added.

The user observed that reviewing the base model in ThoughtSpot Search/Spotter before
adding formulas would catch issues earlier and reduce costly Phase 2 retry cycles.

### Proposed approach

After Phase 1 import succeeds, add an explicit checkpoint:

1. Provide the ThoughtSpot URL to the imported model
2. Ask the user to verify: tables bound correctly, columns visible, joins working,
   parameters present
3. Only proceed to Phase 2 after user confirms

This is already partially described in Step 7.5 ("Confirm the model is correct") but
the current implementation doesn't pause between Phase 1 and Phase 2 in practice.

---

## BL-049 — Tableau: Phase 2 pipeline performance and token cost

**Source:** CPG Merch Promotion Performance migration observations (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 5b, 7; ts-cli `ts tableau translate-formulas`
**Status:** Implemented (ts-cli v0.17.0) — all 5 items complete. #1 deterministic CLI pipeline, #2 `validate_pre_import()`, #3 targeted retry (only re-import failing formulas), #4 context cache (preserve column registry/DAG between retries), #5 migration effort estimate in audit report
**Priority:** HIGH

### Problem

The CPG Merch migration took over 1.5 hours and consumed significant tokens. Most of the
wall-clock time was in Phase 2 (formula import): translating 161 formulas per model,
retrying import errors, fixing structural issues, and re-importing. The retry cycle
(translate → import → fail → diagnose → fix → re-import) is the dominant cost.

This is distinct from BL-046 (determinism of individual transforms). Even with perfect
transforms, the pipeline architecture itself has inefficiencies:

1. **Per-formula LLM round-trips.** Each formula is translated individually with a separate
   LLM call. Batching formulas (e.g., groups of 10-20 with shared context) would reduce
   round-trips and allow the model to see cross-formula patterns.

2. **Import-error-driven debugging.** The pipeline imports, waits for ThoughtSpot to report
   errors, then fixes. A pre-validation step that catches syntax errors, missing refs, and
   structural issues *before* import would eliminate most retry cycles.

3. **Retry scope is too broad.** When one formula fails, the entire batch is often
   re-evaluated. Isolating failures and only re-translating the broken formula would save
   time.

4. **Context re-computation.** Each retry rebuilds the full model context. Caching the model
   state and column registry between retries would reduce per-cycle overhead.

### Proposed approach

| # | Change | Expected impact |
|---|---|---|
| 1 | Batch formula translation (10-20 per LLM call) | ~5-10x fewer round-trips |
| 2 | Pre-import structural validation (syntax, refs, name clashes) | Eliminate ~60% of retry cycles |
| 3 | Targeted retry (only failed formulas, not full batch) | ~3x faster error recovery |
| 4 | Column/formula registry cache across retries | ~2x faster per-cycle |
| 5 | Token budget estimation in audit report | User can decide scope before committing |

### Relationship to other items

- BL-046 (determinism) reduces the *number* of errors to fix
- BL-047 (audit complexity) sets *expectations* about effort
- BL-048 (user checkpoint) prevents wasted Phase 2 work on a bad base model
- BL-049 (this) reduces the *cost of the pipeline itself* even when errors remain

---

## BL-050 — Tableau: codify Phase 2 reactive fixes as systematic pre-transforms

**Source:** CPG Merch Promotion Performance Phase 2 summary (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 5b, 7; ts-cli `ts tableau translate-formulas`;
  agents/shared/mappings/tableau/tableau-formula-translation.md
**Status:** Implemented (ts-cli v0.17.0) — all 9 transforms complete. Cross-ref inlining, END stripping, if/then/else validation, ifnull stripping (default-on), sum_if conversion (default-on), operator spacing, rank() completion, physical ref resolution, name clash detection + auto-rename.
**Priority:** HIGH

### Problem

During the CPG Merch Phase 2 import, several fixes were applied **reactively** after import
failures — fixes that should be **systematic pre-transforms** applied before the first
import attempt. These are not hypothetical: they were discovered and manually applied
during a real migration, and they will recur on every Tableau workbook with similar
patterns.

The reactive fixes from the migration summary:

1. **Cross-formula reference inlining.** ThoughtSpot TML import does NOT resolve
   formula-to-formula references — even when the target formula exists in the same model.
   All `[Other Formula]` references must be inlined (expanded to the target formula's
   expression) before import. The `ts tableau translate-formulas` command performs
   topological-sort inlining, but in this migration it was invoked late (after initial
   import failures). It must be the **first** transform, not a retry fix.

2. **Tableau `end` keyword stripping.** Tableau `IF...THEN...END` uses `END` as a
   terminator. ThoughtSpot formulas are self-terminating (no `end`). The pipeline should
   strip trailing `end` keywords after translating `if/then/else` structure. This was
   a recurring fix in Phase 2.

3. **Dangling `else` at wrong nesting level.** Complex nested `if/then/else` expressions
   sometimes have an `else` that belongs to an outer `if` but is positioned at an inner
   nesting level. The pipeline needs a structural validation pass that matches each
   `if/then/else` triad and flags orphaned `else` clauses before import.

4. **Table-qualified refs use display name, not column_id.** In model formulas,
   `[TABLE::COLUMN]` uses the **display name** of both the table and the column — not the
   `column_id` or `db_column_name`. When a physical column has been renamed in the model
   (e.g., `SALES` → `PM SALES`), refs must use the new display name. The pipeline must
   resolve refs against the model's column registry, not the raw datasource column names.

5. **Duplicate column name detection at model construction.** Physical column `SALES` and
   formula column `Sales` collide case-insensitively in ThoughtSpot. This was detected
   at import time and fixed by renaming the formula column. Detection should happen at
   model construction (Step 5) with auto-rename, not at import (Step 7).

6. **Parameter name sanitisation.** ThoughtSpot parameter names cannot contain `/`, `\`,
   or other special characters. Tableau parameter `Platform/Placement` → rename to
   `Platform Placement` (or similar). Apply during Step 5 parameter creation; update all
   formula references to use the sanitised name. In the CPG Merch migration, 1 formula
   was excluded solely because its parameter name contained `/`.

### Key finding (invariant)

**ThoughtSpot TML import does not resolve formula cross-references.** This is an import
engine limitation, not a skill bug. Document in:
- `agents/shared/schemas/thoughtspot-model-tml.md` — add to the invariants list
- `agents/shared/mappings/tableau/tableau-tml-rules.md` — add as a TML generation rule
- `agents/cli/ts-convert-from-tableau/SKILL.md` Step 5b — confirm inlining is mandatory

### Proposed transform order

These pre-transforms should run in this sequence (each depends on prior):

```
1. Cross-formula inlining (topological sort + expand)
2. Tableau `end` keyword stripping
3. if/then/else structural validation (match triads, flag orphans)
4. ifnull stripping (optional, per user pref — see BL-046 #1)
5. IF/THEN/END → sum_if conversion (optional — see BL-046 #2)
6. Operator spacing normalization
7. rank() argument completion
8. Physical ref → table-qualified display name resolution
9. Column/formula name clash detection + auto-rename
```

Steps 1–3 are structural (must happen). Steps 4–5 are optional (prompt user). Steps 6–9
are deterministic cleanup (always apply).

---

## BL-051 — Tableau: eliminate unnecessary metadata fetching when connection is known

**Source:** CPG Merch Promotion Performance migration observations (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 3.5, 4, 4.5
**Status:** Implemented — #1 Tableau API progress label, #2 T (trust) connection option, #3+#4 compound prompt (connection + db + schema in one question)
**Priority:** MEDIUM

### Problem

During the CPG Merch migration, the user provided the connection name early in the
process, yet the skill still performed metadata searches or connection schema fetches
that added wall-clock time. The SKILL.md has guardrails (Step 4 "ask before searching",
Step 4.5 N/F/L prompt, `ts connections get` as last-resort fallback), but there are gaps
in the fast path:

1. **sqlproxy resolution (Step 3.5) is opaque.** When the TWB has published datasources,
   the skill queries the Tableau API to resolve columns. This is necessary, but the user
   doesn't know whether it's searching *Tableau* or *ThoughtSpot*. The progress feedback
   doesn't distinguish between the two, so it feels like unnecessary ThoughtSpot searching.

2. **Connection validation requires `ts connections list`.** Even when the user types the
   exact connection name (N path), the skill runs `ts connections list` to validate it
   exists. On an instance with many connections, this adds latency. When the user is
   *certain* of the name, an option to skip validation and use it directly would be faster
   (the import will fail cleanly if the name is wrong).

3. **db/schema confirmation could be earlier.** The TWB parse (Step 3) already extracts
   `{db}.{schema}.{table}` paths. If the user could confirm these paths *at the same time*
   as answering E/N/? (Step 4a), the skill could skip the entire Step 4.5 db/schema
   confirmation loop when paths are confirmed.

4. **No "I'll provide everything" fast path.** A power user who knows the connection name,
   db, schema, and that tables don't exist should be able to provide all four in one prompt
   and skip Steps 4a–4.5 entirely. The current flow asks 3–4 sequential questions when one
   compound prompt would suffice.

### Proposed approach

| # | Change | Impact |
|---|---|---|
| 1 | Add progress labels: "Querying Tableau API (not ThoughtSpot)…" in Step 3.5 | Clarity — user knows what's happening |
| 2 | Add a "T — trust the name" option alongside N/F/L for connection selection | Skip `ts connections list` when user is certain |
| 3 | Merge Step 4a + db/schema confirmation into one compound prompt | Eliminate one round-trip for the N (create) path |
| 4 | Add a "power user" compound prompt for N path: connection + db + schema in one question | Skip 3 sequential prompts for users who know their setup |

### Compound prompt example (N path)

```
Source tables ({N} total): TABLE_A, TABLE_B, TABLE_C

These tables don't exist yet — I'll create Table TMLs for them.

Connection: ____________  (exact ThoughtSpot connection name)
Database:   ____________  (or press Enter to use '{twb_extracted_db}')
Schema:     ____________  (or press Enter to use '{twb_extracted_schema}')
```

This replaces: Step 4a (E/N/?) → Step 4.5 (E/C?) → Step 4.5 N/F/L → Step 4.5 db/schema
confirmation — four prompts collapsed to one.

---

## BL-052 — Tableau: translate no-keyword LOD expressions ({AGG([col])})

**Source:** CPG Merch Promotion Performance excluded formulas review (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 3, 5b, A3, A4, 12;
  ts-cli `ts tableau translate-formulas`;
  agents/shared/mappings/tableau/tableau-formula-translation.md
**Status:** Implemented (ts-cli v0.17.0) — `convert_no_keyword_lod()` pre-transform P2
**Priority:** HIGH

### Problem

No-keyword LOD expressions like `{COUNTD([PROMOTION_ID])}` and `{MAX([COL])}` are
currently classified as untranslatable ("raw LOD braces") and excluded from the
formula translation pipeline. In the CPG Merch migration this excluded 5 formulas
directly plus 2 dependents — all of which are translatable.

The mapping reference (`tableau-formula-translation.md`) already documents the
no-keyword LOD → `group_aggregate(..., {}, query_filters())` pattern (updated
2026-06-27), but the `ts tableau translate-formulas` command and the Step A3 classifier
do not recognise the pattern.

### Semantic caveat

No-keyword LODs are translatable but **not semantically identical**. Tableau computes
them after dimension filters but before table-calc filters — a specific point in
Tableau's order of operations with no exact ThoughtSpot equivalent. The translation
uses `query_filters()` as the closest match, but results may differ in edge cases.

Every no-keyword LOD formula must be flagged for user review in both the audit (Step A4)
and migration report (Step 12). This is already documented in the mapping reference and
the SKILL.md — the implementation just needs to follow through.

### What to implement

1. **Step A3 classifier** — recognise `{AGG([col])}` (where AGG is any of COUNTD, COUNT,
   SUM, AVG, MAX, MIN, MEDIAN, ATTR) as the "LOD → group_agg" tier, not untranslatable.
   Detection regex: `\{(COUNTD|COUNT|SUM|AVG|MAX|MIN|MEDIAN|ATTR)\s*\(` (no FIXED/
   INCLUDE/EXCLUDE keyword before the aggregate).

2. **`ts tableau translate-formulas`** — add a transform step that converts `{AGG([col])}`
   to `group_aggregate(ts_agg([table::col]), {}, query_filters())`, mapping Tableau
   aggregate names to ThoughtSpot equivalents (COUNTD → unique_count, AVG → average,
   etc.).

3. **Step A4 audit report** — the "Needs Review" section (added 2026-06-27) lists these.
   Implementation must populate it from the classifier output.

4. **Step 12 migration report** — the "Needs review — no-keyword LOD formulas" section
   (added 2026-06-27) lists each with original/translated expression and what to verify.

### Aggregate mapping

| Tableau | ThoughtSpot |
|---|---|
| `COUNTD` | `unique_count` |
| `COUNT` | `count` |
| `SUM` | `sum` |
| `AVG` | `average` |
| `MAX` | `max` |
| `MIN` | `min` |
| `MEDIAN` | `median` |
| `ATTR` | `max` (ATTR returns the value if all rows agree — `max` is the closest) |

---

## BL-053 — Tableau: migration report must include excluded formulas and review flags

**Source:** CPG Merch Promotion Performance migration (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 12, A4
**Status:** Implemented — Step 12 and Step A4 report templates updated with Excluded Formulas (grouped by root cause) and Formulas Needing Review (5 categories) sections
**Priority:** HIGH

### Problem

The Step 12 migration report has a formula mapping table (every calc field with status
✅/◑/⊘), but it lacks two dedicated sections that a user needs for post-migration work:

1. **Excluded formulas with reasons.** During the CPG Merch migration an `excluded_formulas.md`
   was created ad-hoc. This should be a standard part of every migration report — grouped
   by root cause, with the Tableau expression and a potential resolution for each category.

2. **Formulas that need review.** No-keyword LODs, blend-context formulas, formulas where
   `query_filters()` vs `{}` was a judgement call, pass-through SQL formulas — these are
   migrated but the user must verify they produce correct results. Currently they appear
   in the formula mapping table as ✅ with no flag. They need a separate "Needs Review"
   section with the specific question the user should answer for each one.

### Proposed report structure

```markdown
## Excluded Formulas

{N} formulas were not migrated. Grouped by root cause:

### {Root cause category} ({N} formulas)

| # | Formula Name | Tableau Expression | Potential Resolution |
|---|---|---|---|
| 1 | {name} | {expr} | {what the user can do} |

Root cause summary:
| Root Cause | Count | Potential Resolution |
|---|---|---|
| Missing table in model | {N} | Add tables or restructure model |
| Complex date arithmetic | {N} | Rewrite with TS date functions or pre-compute |
| ... | ... | ... |

## Formulas Needing Review

{N} formulas were migrated but require user verification:

| # | Formula Name | Reason for Review | What to Verify |
|---|---|---|---|
| 1 | Level CPG Category | No-keyword LOD — filter context may differ | Test with/without filters applied |
| 2 | {name} | Pass-through SQL | Confirm SQL passthrough is enabled |
```

### What counts as "needs review"

| Category | Flag text |
|---|---|
| No-keyword LOD (`{AGG([col])}`) | Filter context may differ from Tableau — test with/without search filters |
| Blend-context formula (BL-045) | Row-level join may produce different aggregation than Tableau's post-agg blend |
| Pass-through SQL (`sql_*_aggregate_op`) | Requires SQL Passthrough Functions enabled on the cluster |
| `ifnull` stripping (if applied) | NULL handling now deferred to ThoughtSpot query engine — verify nulls display correctly |
| `sum_if` rewrite (if applied) | Simplified from if/then/else — verify aggregation matches |

---

## BL-054 — Tableau: date arithmetic operator rewrite (DATE()+N → add_days)

**Source:** CPG Merch Promotion Performance excluded formulas review (2026-06-27)
**Affects:** ts-convert-from-tableau Step 5b; ts-cli `ts tableau translate-formulas`;
  agents/shared/mappings/tableau/tableau-formula-translation.md
**Status:** Implemented (ts-cli v0.17.0) — `rewrite_date_arithmetic()` pre-transform P4 + `--date-columns` CLI option
**Priority:** HIGH

### Problem

Tableau allows arithmetic operators on dates: `DATE([col]) + 1` adds one day,
`[date_col] - 7` subtracts seven days. ThoughtSpot does not support `+` or `-` on date
types — these must be rewritten to `add_days()`.

In the CPG Merch migration, the "Start Date" formula used `DATE([START_DATE_CAMPAIGN])+1`
inside a `datediff('hour', ...)` conditional. This was classified as "complex date
arithmetic" and excluded, but the only untranslatable element was the `+1` on a date — the
rest (`datediff`, `dateadd`, `IF/THEN/ELSE`) all have direct mappings.

This pattern is common in Tableau workbooks. It blocked 1 formula directly and 13 more
transitively (the entire Promo Period filter chain depended on it).

### Scope

The transform must handle:

| Tableau pattern | ThoughtSpot |
|---|---|
| `DATE([col]) + N` | `add_days ( date ( [t::col] ) , N )` |
| `DATE([col]) - N` | `add_days ( date ( [t::col] ) , -N )` |
| `[date_col] + N` | `add_days ( [t::date_col] , N )` |
| `[date_col] - N` | `add_days ( [t::date_col] , -N )` |

Detection: a `+` or `-` operator where one side is a date-typed column or `DATE()` call
and the other is a numeric literal. Do not rewrite `+`/`-` between two numbers — only
date±integer patterns.

### Where it fits in BL-050 transform order

This should run as part of step 6 (operator normalisation) in the BL-050 pre-transform
pipeline, after structural validation but before column reference qualification:

```
...
5. IF/THEN/END → sum_if conversion (optional)
6. Operator normalisation — spacing + date arithmetic rewrite   ← here
7. rank() argument completion
...
```

### Relationship to other items

- BL-050 item #6 (operator spacing) — this extends that step with date-specific rewrites
- BL-052 (no-keyword LOD) — 2 of the 14 "date arithmetic" formulas were actually blocked
  by no-keyword LODs, not date functions
- The 4 "date range comparison" formulas were blocked by Custom SQL Query alias resolution
  (a Step 3 parsing issue, not a formula translation issue)

---

## BL-055 — Tableau: detect and translate scalar MAX(a,b) / MIN(a,b)

**Source:** CPG Merch Promotion Performance excluded formulas review (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 5b, A3;
  ts-cli `ts tableau translate-formulas`;
  agents/shared/mappings/tableau/tableau-formula-translation.md
**Status:** Implemented (ts-cli v0.17.0) — `convert_scalar_max_min()` pre-transform P3
**Priority:** HIGH

### Problem

Tableau's `MAX()` and `MIN()` are overloaded — one-arg is aggregate, two-arg is scalar
(returns the greater/lesser of two values). ThoughtSpot only has aggregate `max()` /
`min()`. The pipeline does not distinguish the two forms, so scalar `MAX(expr, 0)` is
either passed through as aggregate `max()` (wrong) or flagged as untranslatable.

In the CPG Merch migration, 4 formulas were excluded as "Scalar MAX(expr, 0)". On
review, only 1 (Forecasted Sales) actually used scalar `MAX(a, 0)`. The other 3 used
aggregate `MAX()` inside FIXED LOD expressions and were misclassified — their real
blocker was no-keyword LOD recognition (BL-052).

### What to implement

1. **Argument-count detection in `ts tableau translate-formulas`.** Count top-level
   arguments (commas not inside nested parens/brackets). 2 args → scalar rewrite;
   1 arg → aggregate `max()` / `min()`.

2. **`MAX(expr, 0)` / `MIN(expr, 0)` special case.** When the second arg is `0`, add
   `else 0` to the inner expression instead of wrapping in `if (expr > 0) then expr
   else 0` — avoids duplicating the expression tree. Already documented in the mapping
   reference ("Scalar MAX/MIN detection" section, added 2026-06-27).

3. **General case `MAX(a, b)`.** Rewrite to `if (a > b) then a else b`. For `MIN(a, b)`
   → `if (a < b) then a else b`.

4. **Step A3 classifier.** Stop classifying two-arg `MAX`/`MIN` as untranslatable. Route
   to the "Native" tier.

### Mapping (already in tableau-formula-translation.md)

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `MAX(a, b)` (2-arg) | `if ( a > b ) then a else b` | General case |
| `MIN(a, b)` (2-arg) | `if ( a < b ) then a else b` | General case |
| `MAX(expr, 0)` | Add `else 0` to inner expr | Preferred simplification |
| `MAX([col])` (1-arg) | `max ( [t::col] )` | Aggregate — unchanged |

---

## BL-056 — Tableau: strip // line comments and handle // inside string literals

**Source:** CPG Merch Promotion Performance excluded formulas review (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 3, 5b, A3;
  ts-cli `ts tableau translate-formulas`
**Status:** Implemented (ts-cli v0.17.0) — `strip_comments()` pre-transform P0
**Priority:** MEDIUM

### Problem

Tableau formulas support `//` as a line comment. The pipeline treated `//` as an
unsupported operator and excluded 3 formulas:

- **ISR 30D / ISR 60D** — `[Lift] / [Cost] //SUM([Redemption Cost])`. The `//` is a
  commented-out alternative denominator. The actual formula is a simple division.
- **Link** — `'https://coda.io/...'`. The `//` is inside a string literal (URL), not a
  comment or operator.

All 3 are translatable once `//` is handled correctly.

### What to implement

Add a comment-stripping pre-parse step in `ts tableau translate-formulas`:

1. **Strip `//` line comments** — remove `//` and everything after it to end of line,
   but only when `//` is NOT inside a string literal (single or double quotes).
2. **Preserve `//` inside string literals** — URLs and other string constants must not
   be modified.

Detection: scan left-to-right tracking quote state. When `//` is encountered outside
quotes, truncate the line there. Inside quotes, leave as-is.

```python
def strip_tableau_comments(formula):
    result = []
    in_single = False
    in_double = False
    i = 0
    while i < len(formula):
        c = formula[i]
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        elif c == '/' and i + 1 < len(formula) and formula[i+1] == '/' \
                and not in_single and not in_double:
            # Skip to end of line
            newline = formula.find('\n', i)
            if newline == -1:
                break
            i = newline
            continue
        result.append(c)
        i += 1
    return ''.join(result)
```

### Where it fits in BL-050 transform order

This should be step 0 — before any other transform, including cross-formula inlining:

```
0. Strip Tableau // line comments              ← here (new)
1. Cross-formula inlining (topological sort)
2. Tableau `end` keyword stripping
...
```

---

## BL-057 — Tableau: resolve Custom SQL Query aliases to model table names

**Source:** CPG Merch Promotion Performance excluded formulas review (2026-06-27)
**Affects:** ts-convert-from-tableau Steps 3, 3.5, 5b;
  ts-cli `ts tableau translate-formulas`
**Status:** Implemented (ts-cli v0.17.0) — `rewrite_csq_aliases()` + `build_csq_column_map()` + `--csq-map` CLI option
**Priority:** HIGH

### Problem

When a Tableau datasource uses Custom SQL Queries as its relations (common with published
datasources), calculated fields reference columns with the query alias suffix:
`[DATE (Custom SQL Query8)]`, `[CATEGORY (Custom SQL Query8)]`. During migration,
Step 3/3.5 resolves the sqlproxy datasource to physical tables (e.g. FORECAST,
DAILY_METRICS), but the **formula column references retain the Custom SQL Query alias**.
The formula pipeline can't match `[DATE (Custom SQL Query8)]` to any model column and
excludes the formula as untranslatable.

In the CPG Merch migration, this excluded 6 formulas directly — all of which are
translatable once the alias is resolved. Custom SQL Query8 maps 100% to the FORECAST
table (all 5 columns: CATEGORY, DATE, LEVEL, PERIOD_TYPE, PROMOTION_ID). Custom SQL
Query6 maps to DAILY_METRICS (DATE, PROMOTION_ID).

### What to implement

1. **Step 3 — build Custom SQL Query → table mapping.** During TWB parsing, for each
   datasource, extract the `<relation>` elements that define Custom SQL Queries and match
   their columns against the resolved table set. Use column-overlap scoring (as verified
   above: 100% match = definitive, 60%+ = likely, <50% = ambiguous → prompt user).

2. **Step 5b / translate-formulas — alias rewriting.** Before formula translation, rewrite
   `[COL (Custom SQL Query N)]` → `[TABLE::COL]` using the mapping from Step 3. This runs
   before cross-reference resolution (step 1 in BL-050) since inlined formulas may also
   contain these aliases.

3. **Step A3/A4 — stop classifying as untranslatable.** Formulas with Custom SQL Query
   aliases should be reclassified based on their *resolved* expression, not the raw alias.

### Detection and mapping heuristic

```python
# For each Custom SQL Query, find all columns it contains
# (from <metadata-record> elements with local-name containing "Custom SQL Query")
csq_columns = extract_csq_columns(datasource)

# Match against model tables by column overlap
for csq_name, csq_cols in csq_columns.items():
    best_match = None
    best_score = 0
    for table_name, table_cols in model_tables.items():
        overlap = set(csq_cols) & set(table_cols)
        score = len(overlap) / len(csq_cols)
        if score > best_score:
            best_match = table_name
            best_score = score
    if best_score >= 0.8:
        csq_to_table[csq_name] = best_match  # definitive
    elif best_score >= 0.5:
        # prompt user to confirm
        pass
```

### CPG Merch mappings (verified)

| Custom SQL Query | Model Table | Match | Key Columns |
|---|---|---|---|
| Custom SQL Query8 | FORECAST | 5/5 (100%) | CATEGORY, DATE, LEVEL, PERIOD_TYPE, PROMOTION_ID |
| Custom SQL Query6 | DAILY_METRICS | 2/2 (100%) | DATE, PROMOTION_ID |
| Custom SQL Query1 | PROMOTION_METRICS | 3/3 (100%) | LEVEL, PROMOTION_ID, UPDATED_AT |
| Custom SQL Query3 | CATEGORY_SHARE | 3/3 (100%) | CPG_NAME, LEVEL, PERIOD_TYPE |

---

## BL-058 — ts-object-model-erd: interactive ERD renderer for ThoughtSpot Models

**Source:** Design spec `docs/superpowers/specs/2026-06-27-ts-object-model-erd-design.md`;
  implementation plan `docs/superpowers/plans/2026-06-27-ts-object-model-erd.md` (local, gitignored);
  validated mockup `docs/superpowers/specs/2026-06-27-ts-object-model-erd-mockup.html`
**Affects:** New skill `agents/cli/ts-object-model-erd/`; new shared module `agents/shared/erd/`;
  future `ts-audit` integration (per-model ERD in `audit_report.html`)
**Status:** Spec approved + plan written + mockup validated — ready for implementation
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

## BL-059 — ts-audit: set (cohort) usage analysis checks

**Source:** Live testing on champ-staging (2026-06-26) — Dunder Mifflin Sales model (`0e4406c7-d978-4be7-abd7-c34e8f7da835`, 44 reusable cohorts)
**Affects:** `agents/cli/ts-audit/analyzer.py` (new checks), `agents/cli/ts-audit/report.py` (report sections)
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
