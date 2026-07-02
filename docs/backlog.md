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
**Affects:** `tools/ts-cli/ts_cli/tableau_translate.py` (`validate_pre_import()`)
**Status:** Open — deferred from the build-model pipeline work (PR on `feat/build-model-pipeline`)

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

## BL-061 — Tableau: integrate `tml_lint()` into `build-model` command

**Source:** Build-model pipeline design (2026-06-27)
**Affects:** `tools/ts-cli/ts_cli/commands/tableau.py` (`build_model` command)
**Status:** Open — deferred as belt-and-suspenders with `validate_pre_import()`

### Problem

`tml_lint()` (in `tml_lint.py`) validates structural TML invariants (I1 duplicate
`aggregation:` on formulas, I2 missing `formula_id`, I4 `COUNTD` on physical columns,
I5 `aggregation:` inside `formulas[]`, I8 duplicate `column_id`). It runs via
`ts tml lint` at the CLI level but is never called from within the `build-model`
command pipeline. This means structural issues are only caught at ThoughtSpot import
time, not during the build step.

### Why deferred

`validate_pre_import()` is now wired into `build-model` (as of v0.19.0) and catches
the most common formula-level issues. The structural invariants `tml_lint()` checks
are less likely to be violated by the builder (which generates TML programmatically)
than by hand-edited TML. Adding it is incremental safety, not a gap fix.

### Proposed approach

After `build_model_tml()` generates the model dict, serialize to YAML and run
`tml_lint()` on the result. Surface warnings to stderr + include in the JSON output.
Do not block the import — let the retry loop handle actual failures.

**Target:** No date set — add when build-model is next touched.

---

## BL-062 — Tableau: detect misplaced-else-in-aggregate formula pattern

**Source:** Ads Commercial Dashboard migration (2026-06-27) — 1 formula hit this pattern
**Affects:** `tools/ts-cli/ts_cli/tableau_translate.py` (`validate_pre_import()`)
**Status:** Open — deferred from the build-model pipeline work

### Problem

A formula like `sum(if X then Y else) + sum(if A then B else)` uses Tableau's
implicit-else syntax (bare `else` with no value = NULL). ThoughtSpot requires an
explicit value after `else`: `sum(if X then Y else 0) + ...`. The translator
sometimes produces the bare `else)` pattern when the source formula has no else
clause and the translation inserts a synthetic one without a value.

### Why deferred

Detecting bare `else)` reliably (vs. `else <expr>)`) requires context-aware parsing
to distinguish the aggregate-boundary `)` from a sub-expression `)`. Low frequency
(1 occurrence across 2 full migrations). The import retry loop catches it and the
fix is mechanical (`else)` → `else 0)`).

### Proposed approach

Add a regex check to `validate_pre_import()` for `else\s*\)` — warn that the else
clause may be missing a default value. False positives possible if a legitimate
expression ends with `)` after `else`, but rare enough to be acceptable as a warning.

**Target:** No date set — revisit if the pattern recurs in future migrations.

---

## BL-063 — Extract CLI-based formula translation for Snowflake and Databricks converters

**Source:** Architectural comparison of conversion skill implementations (2026-06-28)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv, tools/ts-cli
**Status:** Open — assess feasibility before scheduling
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
| 2a | `ts databricks parse-mv` — parse MV YAML into structured JSON | ~1 week |
| 2b | `ts databricks translate-formulas` — Databricks SQL → ThoughtSpot formulas | ~2 weeks |
| 2c | `ts databricks build-model` — assemble Model TML from parsed/translated data | ~1 week |
| 3 | Reverse direction (`ts snowflake translate-formulas --reverse`) for to-SV | ~1 week |
| 4 | Update SKILL.md files to use CLI commands instead of inline LLM translation | ~1 week |

### Decision to make first

Assess whether the translation rules are stable enough to codify. If the mapping docs
are still actively evolving (new constructs being added frequently), the LLM-driven
approach has an advantage: updating a markdown file is faster than updating code + tests.
Once the mapping surface stabilises, extraction becomes higher-value.

**Target:** Assess feasibility by 2026-09-30. Schedule extraction only if mapping churn
has slowed and the quality gap is confirmed via smoke-test comparison.

---

## BL-064 — External audit 2026-06-28: Databricks + Snowflake product-currency fixes

**Source:** External audit sweep 2026-06-28 (angle 13 — product currency)
**Affects:** agents/shared/schemas/databricks-metric-view.md, agents/shared/schemas/snowflake-schema.md, agents/shared/mappings/ts-databricks/, agents/shared/mappings/ts-snowflake/
**Status:** Open
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

5. `sample_values` listed as both supported and unsupported in snowflake-schema.md
6. `verified_queries` now YAML-supported; schema marks it DDL-only
7. `custom_instructions`/`module_custom_instructions` YAML fields not documented
8. `unique_keys` shown with wrong YAML structure in properties file
9. Complete Schema block missing ~15 now-supported YAML fields
10. Three new Databricks window range types undocumented (`leading`, `all`, inclusive/exclusive)
11. Phantom `entities:`/`db_connection:` syntax in ts-to-databricks-rules.md
12. `safe_divide` "No DIV0" comment is wrong; comparison table still says "Preview required"
13. `materialization:` block not documented

### ThoughtSpot medium-severity (separate, lower urgency)

14. RLS rules ARE in table TML — schemas say they are not
15. New TML export options (`export_column_security_rules`, `export_with_column_aliases`)
16. `PARTIAL_OBJECT` import policy + async TML import endpoint undocumented

### Approach

Fix items 1-4 immediately (high severity). Items 5-13 fix as part of the next
schema/mapping update cycle. Items 14-16 document opportunistically.

For Databricks items that overlap BL-032: merge into BL-032's scope rather than
duplicating work. BL-032's target (2026-09-30) applies.

**Target:** High-severity items by 2026-07-15. Medium-severity items by 2026-09-30.

---

## BL-066 — Codify formula promotion as `ts model promote-formula`

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

## BL-067 — Codify Tableau set/cohort detection and TML generation

**Source:** codification sweep 2026-06-29 (angle #11b), priority #5.
**Affects:** `agents/cli/ts-convert-from-tableau/`, `tools/ts-cli/`.
**Status:** OPEN.

### Problem

ts-convert-from-tableau Step 5b (set/cohort detection + TML generation, ~400 lines of prompt)
is fully mechanical. Every set type (fixed, dynamic, combined) has a fully specified mapping
to ThoughtSpot filter/parameter TML. The LLM re-derives this mapping on each invocation.

### Approach

Extend `model_builder.py` with `extract_sets()` and `build_cohort_tml()`:
- `extract_sets()`: identify Tableau sets in the parsed workbook, classify by type
- `build_cohort_tml()`: emit the corresponding ThoughtSpot filter/parameter TML
- Wire into `ts tableau build-model` or as a standalone `ts tableau build-sets` command

**Target:** 2026-10-31.

---

## BL-068 — Codify Tableau dashboard-to-liveboard conversion

**Source:** codification sweep 2026-06-29 (angle #11b), priority #7.
**Affects:** `agents/cli/ts-convert-from-tableau/`, `tools/ts-cli/`.
**Status:** OPEN.

### Problem

ts-convert-from-tableau Steps 9a–9c + 10c (dashboard zone parsing + liveboard TML assembly)
are mechanical: parse Tableau dashboard zones from the TWB XML, map each zone to a ThoughtSpot
liveboard visualization tile, emit Liveboard TML with layout. The LLM re-derives the
zone→tile mapping on every invocation.

### Approach

Build `ts tableau build-liveboard` in ts-cli:
- Input: parsed TWB (from `parse_twb()`) + answer GUIDs (from prior import)
- Parse dashboard zones, map to liveboard tiles with layout coordinates
- Emit Liveboard TML ready for import
- Extends the existing Tableau codification pattern (`parse_twb` → `translate-formulas` →
  `build-model` → **`build-liveboard`**)

**Target:** 2026-12-31.

---

## BL-069 — Refactor tableau_translate.py into module-per-concern structure

**Source:** codification sweep 2026-06-29 (angle #11b), architectural observation.
**Affects:** `tools/ts-cli/ts_cli/tableau_translate.py`, `tools/ts-cli/ts_cli/model_builder.py`.
**Status:** OPEN — **HIGH PRIORITY** (flagged 2026-07-02).
**Priority rationale:** `check_module_health` (radon) confirms this file holds the repo's
worst complexity — `ensure_else_clause` **F (47)**, `validate_pre_import` **E (32)**,
`normalize_operator_spacing` **D (27)**, `translate_formulas` **D (25)**, `build_dependency_dag`
**D (21)** — 5 of the repo's highest-complexity functions in one 2,543-line module. It is the
single largest maintainability risk as contributor count grows, and the complexity ratchet now
prevents it from getting *worse* but does not pay down the existing debt. Prioritise ahead of
the 2026-12-31 target.

### Problem

`tableau_translate.py` is 2543 lines in a single module covering: dependency DAG building,
parameter conflict detection, name clash resolution, pre-transforms (5), main translation
pipeline, post-transforms (2), and YAML serialization. `model_builder.py` is 1025 lines
covering TWB parsing, ref resolution, TML assembly, and phased import splitting.

Both files work well but are hard to navigate and test in isolation. The `ts audit run`
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

---

## BL-070 — Add file-size validator for ts-cli modules

**Source:** architectural review 2026-07-01, repo-audit angle #4 (tools quality).
**Affects:** `tools/validate/`, `tools/ts-cli/ts_cli/`.
**Status:** PARTIALLY DONE (2026-07-02) — the *complexity* dimension is now gated by
`check_module_health.py` (radon cyclomatic-complexity ratchet, wired into pre-commit + CI),
and repo-audit angle #4 has been updated to reference it. **Remaining scope:** the *file-size*
(line-count) dimension — a soft-warn at 500 lines / hard-fail at 1000 on new-or-modified
`ts_cli` modules with a baseline allowlist. Complexity and size are complementary signals
(a file can be long-but-simple or short-but-gnarly), so the line-count gate is still worth
adding.

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
