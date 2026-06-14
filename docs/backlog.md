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
**Status:** In progress — BL-003, BL-003b, BL-003c, BL-004, GAP-13 implemented (2026-06-13); GAP-04/05/08/10 mapped + SKILL.md parsing complete (2026-06-14); remaining LOW gaps tracked below
**Full spec:** [`sv-to-ts-gap-analysis.md`](sv-to-ts-gap-analysis.md)

### Summary

The `ts-convert-from-snowflake-sv` skill has 13 identified gaps where Snowflake Semantic
View constructs are not parsed or translated to ThoughtSpot. The full gap analysis is in
`sv-to-ts-gap-analysis.md`. This umbrella item tracks the initiative as a whole.

### Sub-items (in dependency order)

| Item | Gap | Priority | Dependency |
|---|---|---|---|
| BL-003b | Parse `facts (...)` section from DDL | HIGH | None | **Done** (2026-06-13) |
| BL-003c | Metric-references-fact resolution | HIGH | BL-003b | **Done** (2026-06-13) |
| BL-003 | Double aggregation (metric-referencing-metric) | HIGH | BL-003b | **Done** (2026-06-13) |
| BL-004 | Semantic views with no joins | MEDIUM | None | **Done** (2026-06-13) |
| GAP-04 | Derived metrics (cross-table, view-level) | MEDIUM | BL-003 | → BL-018 sub-item 3 (SQL View path) |
| GAP-08 | Range joins / ASOF joins | MEDIUM | None | → BL-018 sub-item 1 (TS supports range joins) |
| GAP-10 | Filters on logical tables | MEDIUM | None | → BL-018 sub-item 2 (model filters) |
| GAP-13 | Window metrics referencing other metrics | MEDIUM | BL-003 | **Done** (2026-06-13) |
| GAP-05 | Verified queries → NLS Feedback TML | MEDIUM | None | → BL-018 sub-item 4 (direct mapping exists) |
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
**Status:** Done (2026-06-13) — identifier resolution engine adds group_aggregate wrapping with group_* shorthand
> Implemented in CLI SKILL.md Step 9a (identifier resolution pre-pass), shared rules (ts-from-snowflake-rules.md), and formula translation (ts-snowflake-formula-translation.md). Option B (group_aggregate, no schema changes) chosen as default. Mirrored to CoCo and Cursor.

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
**Status:** Done (2026-06-13) — Step 4 extracts facts block; facts become standalone formulas in Step 8
> Facts parsed as `{table_alias, fact_name, expression, comment, synonyms, access_modifier}`. Public facts emitted as `formulas[]` entries with `column_type: ATTRIBUTE`. Private facts emitted but noted in report. Mirrored to CoCo and Cursor.
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
**Status:** Done (2026-06-13) — identifier resolution pre-pass resolves fact references to formula names
> Three-step resolution in Step 9a: physical column → `[TABLE::col]`; fact → `[Fact Display Name]` formula reference; metric → double aggregation. Mirrored to CoCo and Cursor.
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
**Status:** Done (2026-06-13) — joinless SV guard skips Step 7 and produces model with no joins
> If no `relationships` block exists, Steps 7 (join mapping) and related sections are skipped. Model TML produced with `model_tables[]` entries and no `joins_with` entries. Mirrored to CoCo and Cursor.

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

---

## BL-017 — Cursor mirror sync: close version gaps or retire runtime

**Source:** 2026-06-13 mirror parity audit (Plan 3)
**Affects:** All 7 behind-version Cursor `.mdc` mirrors (see `agents/SYNC-DEBT.md`)
**Status:** Open

### Problem

The Cursor runtime received zero updates through four CLI release cycles. Seven
mirrors are behind — the worst (`ts-object-model-coach.mdc`) is at v1.2.0 vs
CLI v2.3.0 (a full major version behind, meaning the Cursor mirror guides users
through a workflow that no longer matches the canonical skill).

### Version gap table

| Mirror | Cursor at | CLI at | Gap size |
|---|---|---|---|
| ts-convert-from-tableau | v1.1.2 | v1.9.1 | 8 minor versions |
| ts-object-model-coach | v1.2.0 | v2.3.0 | 1 major + 1 minor |
| ts-convert-from-snowflake-sv | v1.3.1 | v1.7.1 | 4 minor versions |
| ts-convert-from-databricks-mv | v1.0.1 | v1.3.0 | 2 minor versions |
| ts-convert-to-snowflake-sv | v1.2.0 | v1.2.2 | 2 patch versions |
| ts-object-answer-promote | v1.1.0 | v1.2.0 | 1 minor version |
| ts-profile-snowflake | v1.0.0 | v1.0.1 | 1 patch version |

### Decision needed

1. **Sync**: update all 7 mirrors to current CLI versions. Estimated effort: medium
   (the `.mdc` format is condensed — a full content sync requires reading each CLI
   skill diff since the marker version and condensing the new content).
2. **Retire**: remove the Cursor runtime entirely and update `EXPECTED_DIVERGENCES`
   + PARITY.md. This is legitimate if no one uses Cursor with these skills.
3. **Selective sync**: sync the most-used mirrors (convert-from-*, profile-*), retire
   or freeze the rest.

### Tracking

`agents/SYNC-DEBT.md` tracks all gaps. `check_mirror_sync.py` fails on any
unacknowledged gap. Closing a SYNC-DEBT row = syncing the mirror and bumping
its `synced-from` marker.

---

## BL-018 — Close remaining SV→TS mapping gaps (range joins, model filters, SQL View for subquery SVs)

**Source:** Post-identifier-resolution review of unmapped SV features (2026-06-13)
**Affects:** ts-convert-from-snowflake-sv, sv-to-ts-gap-analysis.md
**Status:** In progress — documentation and mapping rules complete (2026-06-13); SKILL.md parsing complete (2026-06-14); live verification pending
**Corrects:** GAP-08 (range joins), GAP-10 (filter labels), GAP-04 (view-backed sources), GAP-05 (verified queries)

### Problem

Three SV DDL constructs were classified as "no ThoughtSpot equivalent" in the gap
analysis, but ThoughtSpot **does** have the necessary mechanisms:

1. **Range joins (GAP-08):** The gap analysis says "ThoughtSpot only supports equi-joins."
   This is wrong — ThoughtSpot Model TML `joins[].on` accepts arbitrary expressions
   including `<`, `>`, `AND`, range predicates. Verified via live TML export showing:
   ```yaml
   - name: range join
     destination:
       name: SCD Invoice
     'on': "((([FACT_RETAIL_VIEW::invoice date] < [SCD Invoice::date]) AND
             ([FACT_RETAIL_VIEW::invoice_id] = [SCD Invoice::invoice_id])) AND
             ([FACT_RETAIL_VIEW::due date] > [SCD Invoice::date]))"
     type: INNER
   ```
   Snowflake `DISTINCT_RANGE(start_col, end_col)` constraints and constant-value joins
   can be translated to this `on` expression format.

2. **Table filters (GAP-10):** The gap analysis says "No table-level filter in model TML."
   While there's no *table*-level filter, `model.filters[]` provides model-level pre-filters
   with operators (`=`, `!=`, `>`, `>=`, `<`, `<=`, `between`, `in`, `not_in`),
   `is_mandatory` for non-removable filters, and `apply_on_tables` to scope a filter to
   specific tables in a multi-fact model. This covers the SV "filters on logical tables"
   use case.

3. **Subquery-backed SVs (GAP-04):** When an SV's source is a SQL subquery rather than a
   physical table, the skill currently has no path. ThoughtSpot's SQL View TML
   (`sql_view:` with `sql_query:`) is the direct equivalent — create a SQL View TML
   containing the subquery, import it, then reference it in the Model as a `model_tables[]`
   entry. The SQL View TML schema is already documented in
   `agents/shared/schemas/thoughtspot-sql-view-tml.md`.

### Proposed approach

#### Sub-item 1: Range joins (corrects GAP-08)

1. **Detection** — In Step 4, parse `CONSTRAINT ... DISTINCT_RANGE(start_col, end_col)`
   from the SV DDL relationships block.
2. **Translation** — Convert to a Model TML join `on` expression:
   ```
   [FROM_TABLE::key] = [TO_TABLE::key] AND [FROM_TABLE::start_col] <= [TO_TABLE::date] AND [FROM_TABLE::end_col] > [TO_TABLE::date]
   ```
   The exact expression depends on whether it's an inclusive or exclusive range.
3. **ASOF joins** — Research whether these can also be expressed as range predicates
   in the `on` clause, or whether they require a different approach.
4. **Update** `sv-to-ts-gap-analysis.md` GAP-08 to reflect that TS supports range joins.

#### Sub-item 2: SV filter labels → model filters or boolean formula columns (corrects GAP-10)

Snowflake SV filters are dimensions or facts with `LABELS = (FILTER)` — boolean
expressions that Cortex Analyst *can* use as WHERE clauses. They are not
permanently auto-applied; they're available for optional use in queries.

ThoughtSpot `model.filters[]` scoping:
- Without `apply_on_tables` → filter is always applied (mandatory on every search)
- With `apply_on_tables` → filter only applies when one of those tables is in the search

**Translation depends on intent:**

| SV filter intent | TS mapping |
|---|---|
| Always-applied business rule (e.g. `is_active = TRUE`) | `model.filters[]` without `apply_on_tables` |
| Table-scoped rule (e.g. only for orders table) | `model.filters[]` with `apply_on_tables: [table_name]` |
| Available for ad-hoc filtering (the default SV LABELS=FILTER meaning) | Boolean formula column — no model filter; users apply it in the search bar |

1. **Detection** — Parse dimensions/facts with `LABELS = (FILTER)` from DDL.
   These are boolean expressions.
2. **Translation** — Create the boolean expression as a formula column. At the
   Step 10 review checkpoint, ask the user whether each filter should be:
   - A model-level filter (always applied or table-scoped via `apply_on_tables`)
   - A boolean column available for ad-hoc filtering (default — matches SV semantics)
3. **Update** `sv-to-ts-gap-analysis.md` GAP-10 to reflect the corrected mapping.

#### Sub-item 3: SQL View for subquery SVs (implements GAP-04)

1. **Detection** — In Step 4, identify when an SV's `tables` block references a subquery
   or inline SQL rather than a physical `DB.SCHEMA.TABLE`.
2. **Generation** — Create a SQL View TML with:
   - `sql_query:` ← the subquery text
   - `connection:` ← the ThoughtSpot connection name
   - `sql_view_columns:` ← columns inferred from the subquery's SELECT list
3. **Import** — Import the SQL View first, capture its GUID, then reference it in the
   Model TML as a `model_tables[]` entry (same as a regular table).
4. **Worked example** — Add a worked example showing a subquery SV → SQL View + Model.

#### Sub-item 4: Verified queries → NLS Feedback TML (implements GAP-05)

The gap analysis says "no direct TS equivalent" for `ai_verified_queries`. This is wrong —
ThoughtSpot's NLS Feedback TML (`nls_feedback:` with `feedback[]` entries) is the direct
equivalent. Both are question→search mappings that train the AI layer.

**Snowflake `ai_verified_queries`:**
```sql
ai_verified_queries (
  'What is total revenue?' : 'SELECT SUM(amount) FROM sales',
  'Revenue by region'      : 'SELECT region, SUM(amount) FROM sales GROUP BY region'
)
```

**ThoughtSpot NLS Feedback TML equivalent:**
```yaml
guid: "{model_guid}"
nls_feedback:
  feedback:
  - id: "1"
    type: REFERENCE_QUESTION
    access: GLOBAL
    feedback_phrase: "What is total revenue?"
    search_tokens: "sum [Amount]"
    rating: UPVOTE
    display_mode: UNDEFINED
    chart_type: KPI
  - id: "2"
    type: REFERENCE_QUESTION
    access: GLOBAL
    feedback_phrase: "Revenue by region"
    search_tokens: "sum [Amount] [Region]"
    rating: UPVOTE
    display_mode: CHART_MODE
    chart_type: COLUMN
```

**Translation steps:**
1. Parse each verified query's question text → `feedback_phrase`
2. Parse the SQL query's SELECT columns and map to ThoughtSpot column names using
   the column mapping already built during conversion → `search_tokens`
3. Infer `chart_type` from query shape: single aggregate → `KPI`; aggregate + group by → `COLUMN`/`BAR`;
   date group by → `LINE`; two measures → `SCATTER`
4. Emit as `REFERENCE_QUESTION` entries with `rating: UPVOTE`, `access: GLOBAL`
5. Import as a separate TML payload after the Model import succeeds (feedback entries
   reference Model columns — columns must exist first)

**Constraint:** Every column in `search_tokens` must exist on the Model at import time
(verified — silently dropped otherwise). The column mapping from Step 8/9 provides
the name resolution.

Schema reference: `agents/shared/schemas/thoughtspot-feedback-tml.md`

### Files affected

- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — Step 4 (parse), Step 7 (joins), new filter step, Step 6 (SQL View generation for subquery SVs), new post-import step for feedback TML
- `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md` — range join rules, filter mapping rules, verified query translation rules
- `docs/sv-to-ts-gap-analysis.md` — correct GAP-05, GAP-08, and GAP-10 assessments
- `agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md` — mirror changes
- `agents/cursor/rules/ts-convert-from-snowflake-sv.mdc` — mirror changes

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
- `agents/cursor/rules/ts-convert-from-snowflake-sv.mdc` — mirror
- `agents/cursor/rules/ts-convert-from-databricks-mv.mdc` — mirror
- `agents/cursor/rules/ts-convert-from-tableau.mdc` — mirror
