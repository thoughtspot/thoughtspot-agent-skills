# Backlog

Improvement ideas identified but not yet scheduled. Each item includes context on
why it matters and what the approach would be.

---

## BL-001 — Pre-import TML lint for all conversion skills

**Source:** Analysis of twells89/sigma-migration-skills (2026-06-11)
**Affects:** ts-convert-from-tableau, ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv
**Status:** Done (2026-06-12)
> Done: check_tml.py enforces I1/I2/I4/I5; inline pre-import gate added to all three convert-from skills. (I3 remains advisory via conversion-consistency-auditor.)

### Problem

The I1–I7 invariants in `ts-model-conversion-invariants.md` include rules that
ThoughtSpot accepts silently but produces wrong results:

| Invariant | Silent failure |
|---|---|
| I1 — missing `columns[]` entry for a formula | Formula silently dropped on import |
| I4 — join `id` ≠ `name` (case mismatch) | Joins silently fail at query time |
| I5 — `aggregation: COUNT_DISTINCT` | `column_type` silently overridden to ATTRIBUTE |

`--policy VALIDATE_ONLY` does not catch these — the API accepts the TML without error.

### Current state

- Tableau skill has `VALIDATE_ONLY` fix cycles (Step 6) but only checks API responses
- Snowflake SV and Databricks MV skills have no pre-import validation
- `tools/validate/check_tml.py` implements the self-validation checklist but no skill calls it

### Proposed approach

Add a validation step between TML generation and import in each conversion skill.
Either call `check_tml.py` inline or embed the I1–I5 checks directly in the skill
step that writes TML. Fail loudly before attempting import.

---

## BL-002 — NULL fall-through in Tableau IF/ELSE formula translation

**Source:** Analysis of twells89/sigma-migration-skills (2026-06-11)
**Affects:** ts-convert-from-tableau (primarily); applies to all converters
**Status:** Done (2026-06-12) — resolved as "no auto-guard"
> Live test on se-thoughtspot: `if ([x] >= 5000) then 'High' else 'Low'` returns **'Low'**
> for NULL rows. ThoughtSpot compiles if/then/else → SQL `CASE WHEN ... THEN ... ELSE ... END`
> (captured: `CASE WHEN NULL >= 5E3 THEN 'High' ELSE 'Low' END`), so NULL→ELSE is standard
> warehouse `CASE` semantics — **identical to Tableau's own behavior**. A literal translation is
> therefore **faithful**; auto-adding an `isnull()` guard would *change* the source behavior.
> Resolution: documented in `tableau-formula-translation.md` ("NULL in IF/THEN/ELSE") as
> matching-Tableau + opt-in correction only. No mandatory rule added.

### Problem (original framing — now disproven)

The concern was that ThoughtSpot might *differ* from Tableau on `IF [x] >= 5000 THEN 'Platinum'
ELSE 'Bronze'` when `[x]` is NULL, silently mis-classifying NULLs. The live test showed
ThoughtSpot behaves **the same as Tableau** (NULL → ELSE), so there is no divergence to fix and
a faithful migration must NOT guard by default. The Sigma repo's `Coalesce` wrap is an
intentional *correction*, not a fidelity requirement — offered as opt-in, not applied
automatically.

---

## BL-003-UMBRELLA — Complete Semantic View → ThoughtSpot mapping coverage

**Source:** Full gap analysis against production SV `DEMO.SEMANTIC_TESTING.SHIFTS7_PAYROLL1` (2026-06-11)
**Affects:** ts-convert-from-snowflake-sv (all steps)
**Status:** Not started
**Full spec:** [`sv-to-ts-gap-analysis.md`](sv-to-ts-gap-analysis.md)

### Summary

The `ts-convert-from-snowflake-sv` skill has 13 identified gaps where Snowflake Semantic
View constructs are not parsed or translated to ThoughtSpot. The full gap analysis is in
`sv-to-ts-gap-analysis.md`. This umbrella item tracks the initiative as a whole.

### Sub-items (in dependency order)

| Item | Gap | Priority | Dependency |
|---|---|---|---|
| BL-003b | Parse `facts (...)` section from DDL | HIGH | None |
| BL-003c | Metric-references-fact resolution | HIGH | BL-003b |
| BL-003 | Double aggregation (metric-referencing-metric) | HIGH | BL-003b |
| BL-004 | Semantic views with no joins | MEDIUM | None |
| GAP-04 | Derived metrics (cross-table, view-level) | MEDIUM | BL-003 |
| GAP-08 | Range joins / ASOF joins | MEDIUM | None |
| GAP-10 | Filters on logical tables | MEDIUM | None |
| GAP-13 | Window metrics referencing other metrics | MEDIUM | BL-003 |
| GAP-05 | Verified queries → Spotter instructions | LOW | None |
| GAP-06 | Custom instructions → `data_model_instructions` | LOW | None |
| GAP-07 | Table synonyms | LOW | None |
| GAP-09 | Private facts/metrics | LOW | None |
| GAP-11 | `unique_keys` | LOW | None |

### Recommended execution order

1. BL-003b (facts parsing) — unblocks everything else
2. BL-003c (fact resolution) + BL-003 (double aggregation) — the core reference resolution engine
3. BL-004 (no joins) — quick win, independent
4. GAP-13 (window + metric refs) — extends the resolution engine to window functions
5. Remaining MEDIUM/LOW gaps as encountered

### Files affected

- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md`
- `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md`
- `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`
- `agents/cli/ts-convert-from-snowflake-sv/references/open-items.md`

### Test SV

Use `DEMO.SEMANTIC_TESTING.SHIFTS7_PAYROLL1` — it exercises facts, double aggregation,
metric-references-fact, cumulative window metrics with metric references, and joinless
metric patterns (all metrics on a single table).

---

## BL-003 — Double aggregation translation (metric-referencing-metric)

**Source:** Analysis of Snowflake Semantic View `DEMO.SEMANTIC_TESTING.SHIFTS7_PAYROLL1` (2026-06-11)
**Affects:** ts-convert-from-snowflake-sv (Step 9 — formula translation)
**Status:** Not started

### Problem

Snowflake Semantic Views support **double aggregation** — a metric whose expression
references another metric by name. The engine resolves the inner metric first (grouped
by the join key), then applies the outer aggregate. The `ts-convert-from-snowflake-sv`
skill does not detect or translate this pattern.

**Reference document:** [`double-aggregation-guide.md`](double-aggregation-guide.md)

### Example (production SV)

```sql
-- Relationship (many-to-one):
LOCATIONS_TO_COMPANIES as PAYROLL_LOCATIONS(PAYROLL_COMPANY_ID)
    references PAYROLL_COMPANIES(PAYROLL_COMPANY_ID)

-- Inner metric (child table — PAYROLL_LOCATIONS):
PAYROLL_LOCATIONS.NUMBER_OF_LOCATIONS as COUNT(PAYROLL_LOCATION_ID)

-- Outer metric (parent table — PAYROLL_COMPANIES, referencing inner):
PAYROLL_COMPANIES.AVERAGE_LOCATIONS_PER_COMPANY as AVG(payroll_locations.number_of_locations)
```

The engine computes: `AVG( COUNT(locations) per company )`.

### Proposed approach

1. **Detection** — In Step 9, when parsing a metric expression like `AVG(table_alias.metric_name)`, check whether `metric_name` resolves to another metric definition (not a physical column).
2. **Resolution** — Look up the inner metric's aggregate expression and identify the grouping boundary from the declared relationship.
3. **Translation** — Two options, presented as a decision point to the user:

| Option | ThoughtSpot formula | Trade-off |
|---|---|---|
| A (recommended) | `average ( [COMPANIES::NUMBER_OF_LOCATIONS] )` | Requires pre-aggregated column in a view/dynamic table; best for Spotter UX |
| B | `average ( group_aggregate ( count ( [PAYROLL_LOCATIONS::PAYROLL_LOCATION_ID] ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_ID] } , {} ) )` | No schema changes; complex formula confuses Spotter |

4. **Shared references** — Create missing files:
   - `shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` — "Double Aggregation" section
   - `shared/schemas/thoughtspot-formula-patterns.md` — `group_aggregate` syntax and nesting rules

### Key context

- The relationship declaration tells the engine how to group the inner metric — without it, the grouping boundary is ambiguous.
- Other double-aggregation metrics in the same SV: `AVG(payroll_locations.number_of_active_locations)`.
- Metrics referencing **facts** (e.g. `AVG(payroll_companies.company_age_months)`) are NOT double aggregation — facts are row-level expressions, so only one aggregation step occurs.

---

## BL-003b — Parse and map `facts (...)` section from Semantic View DDL

**Source:** Gap analysis of `DEMO.SEMANTIC_TESTING.SHIFTS7_PAYROLL1` (2026-06-11)
**Affects:** ts-convert-from-snowflake-sv (Step 4 parser + Step 9 translation)
**Status:** Not started
**Full analysis:** [`sv-to-ts-gap-analysis.md`](sv-to-ts-gap-analysis.md) — GAP-01

### Problem

The DDL `facts` block defines row-level computed expressions (not aggregates). The
skill's Step 4 parser does not extract this section. Facts are intermediate calculations
referenced by metrics — without parsing them, metrics like `SUM(table.fact_name)` cannot
be resolved.

### Example

```sql
facts (
    PAYROLL_COMPANIES.COMPANY_AGE_MONTHS as DATEDIFF(month, PAYROLL_COMPANY_CREATED_AT, CURRENT_DATE()),
    PAYROLL_COMPANIES.INACTIVE_LOCATIONS_SINCE_ACTIVATION as NUMBER_LOCATIONS_AT_ACTIVATION - NUMBER_ACTIVE_PAYROLL_LOCATIONS
)
```

### Proposed approach

1. **Parser** — Extract `facts` entries in Step 4 alongside dimensions and metrics.
   Store as `{table_alias, fact_name, expression, comment}`.
2. **Mapping** — Facts → `formulas[]` with `column_type: MEASURE` and the translated
   expression (e.g. `diff_months(today(), [TABLE::COL])`).
3. **Metric resolution** — When a metric references a fact by `table.fact_name`, check
   whether the fact name corresponds to a physical column (use `column_id` directly) or
   a computed fact (inline the translated expression or reference the formula).

Closely related to BL-003 (double aggregation) — resolving fact references is a
prerequisite for correct metric-on-fact translation.

---

## BL-003c — Metric-references-fact resolution in formula translation

**Source:** Gap analysis of `DEMO.SEMANTIC_TESTING.SHIFTS7_PAYROLL1` (2026-06-11)
**Affects:** ts-convert-from-snowflake-sv (Step 9)
**Status:** Not started
**Full analysis:** [`sv-to-ts-gap-analysis.md`](sv-to-ts-gap-analysis.md) — GAP-12

### Problem

Metrics that reference a fact by name (e.g. `SUM(payroll_companies.inactive_locations_since_activation)`)
need the skill to resolve whether `inactive_locations_since_activation` is a physical
column or a computed fact. If it's a computed fact, the skill must either:
- Inline the translated fact expression inside the metric formula
- Reference the fact's ThoughtSpot formula (if created from BL-003b)

### Proposed approach

Add a resolution step before formula translation:
1. For each metric expression argument, check against: physical columns → facts → other metrics
2. If it's a physical column → use `[TABLE::col]` reference
3. If it's a fact → inline the translated fact expression (or reference the formula name)
4. If it's a metric → apply double-aggregation logic (BL-003)

---

## BL-004 — Handle semantic views with no joins defined

**Source:** Field observations (2026-06-11)
**Affects:** ts-convert-from-snowflake-sv
**Status:** Not started

### Problem

The `ts-convert-from-snowflake-sv` skill assumes the semantic view defines
relationships (joins) between tables. Some semantic views define multiple tables
with no `relationships` block, or define a single table only. The skill's current
join-mapping logic does not account for this — it may error or produce an incomplete
model.

### Proposed approach

1. **Detection** — After parsing the semantic view DDL, check whether a `relationships`
   block exists and whether it contains any entries.
2. **Single-table SV** — Generate a ThoughtSpot model with one `model_table` and no
   joins. This is a valid and common model shape.
3. **Multi-table, no joins** — Flag to the user that the SV defines multiple tables
   without declared relationships. Options:
   - Import each table as an independent model table (no joins — user wires them manually in ThoughtSpot)
   - Prompt the user for join definitions before proceeding
   - Attempt to infer joins from matching column names / foreign key naming conventions (risky — flag confidence level)

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

Build `agents/databricks/` as a fourth runtime alongside CLI, Cursor, and CoCo:

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

## BL-006 — BOOL vs BOOLEAN mapping inconsistency for Snowflake connections

**Source:** Live testing against SpotterAccuracy (thoughtspot_partner.ap-southeast-2) (2026-06-11)
**Affects:** ts-convert-from-snowflake-sv, ts-object-model-coach (table creation step)
**Status:** Done (2026-06-12)
> Done: ts-from-snowflake-rules.md maps BOOLEAN→BOOL with a ts-tables-create callout.

### Problem

`ts-from-snowflake-rules.md` type mapping table (line 468) documents `BOOLEAN → BOOLEAN`
for the ThoughtSpot `data_type` field. However, when creating tables via `ts tables create`
against a Snowflake connection, the API rejects `BOOLEAN` with:

```
Data type BOOLEAN is not valid for column having name {col} and db_column_name {col}.
```

The correct value is `BOOL`. This inconsistency between the two reference files causes
skill-generated TML to fail on import when the source table contains boolean columns.

`thoughtspot-table-tml.md` (line 107) already documents the correct value:

| Boolean (Snowflake) | `BOOL` |
| Boolean (general / may vary) | `BOOLEAN` |

### Proposed fix

1. Update `ts-from-snowflake-rules.md` type mapping table to:

   ```
   | BOOLEAN | BOOL  *(Snowflake connections — ts tables create rejects BOOLEAN)* |
   ```

2. Add a callout box after the type mapping table:
   > **Snowflake connection note:** `ts tables create` validates `data_type` against the
   > live CDW column type. For Snowflake BOOLEAN columns, use `BOOL` — not `BOOLEAN`,
   > `INT64`, or `VARCHAR`. Using any other type returns a CDW mismatch error.

### Files affected

- `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md` — type mapping table

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
**Status:** In progress — **Phase 1 DONE (PR #48)**, **Phase 2a DONE (PR #49)**, **Phase 2b DONE (2026-06-12)**; Phase 2c + 3 + 4 open
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
> **Remaining:** Phase 2c (`intersect`/computed `except`), Phase 3 (geospatial MAKEPOINT/MAKELINE),
> Phase 4 (source coverage + INDEX note). See the full plan.

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

## BL-012 — Cross-skill conversion consistency: parity + auditor (extends BL-001)

**Source:** Cross-skill audit of the five `ts-convert-*` skills (2026-06-10/11)
**Affects:** ts-convert-from-tableau/snowflake-sv/databricks-mv; `.claude/agents/`
**Status:** Done (2026-06-12)
> Done in commit a624dfa + 2026-06-12 follow-up (tableau/dbx cursor mirrors, auditor smoke-test). Implementation plan removed on completion.
**Overlaps:** BL-001 (pre-import TML lint) + existing `agents/shared/schemas/ts-model-conversion-invariants.md` — EXTEND, do not duplicate.

### Problem

The three Model-producing "from" skills drifted: Tableau lacks invariants I1–I5 + the I7
mandatory-reference gate that SV/MV state; Databricks-MV has no update-in-place (Mode C); the
`TEST_*` model-name prefix is inconsistent. (The `cumulative_*`/`moving_*` difference is
INTENTIONAL — Tableau table-calcs are row-level, not model formulas — captured as EXC1, do not
"harmonize".)

### Proposed approach

Verify/extend the existing invariants doc (BL-001 owns the lint enforcement), bring Tableau to
parity (Step 5b), port SV's Mode C to Databricks-MV, unify the name-prefix policy, and add a NEW
`.claude/agents/conversion-consistency-auditor.md` subagent (semantic checks, distinct from the
stale structural `consistency-checker`, whose `agents/claude`→`agents/cli` paths also need fixing).
The auditor + Tableau parity + Mode C are the genuinely-new parts; the invariants doc and lint
already exist via BL-001.

---

## BL-013 — Metadata-only sync mode for converters (names, comments, synonyms → matched columns)

**Source:** Feature request (2026-06-12)
**Affects:** ts-convert-from-snowflake-sv, ts-convert-from-databricks-mv (mode option at start); possibly ts-convert-from-tableau later
**Status:** Not started

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
`tableau-tml-rules.md` → `tableau-from-rules.md` (update all SKILL.md + cursor/coco mirror
references), and optionally splitting Tableau property/type content into a
`tableau-properties.md` to mirror SV/MV. Fits the BL-012 cross-skill-consistency theme; the
conversion-consistency-auditor could then assert the naming convention.
