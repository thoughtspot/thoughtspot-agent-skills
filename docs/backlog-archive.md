# Backlog Archive — Completed Items
Done backlog items moved out of `backlog.md` to keep the active backlog lean.
Shipped history also lives in `CHANGELOG.md` and each skill's `## Changelog`.

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
**Status:** Done — BL-003, BL-003b, BL-003c, BL-004, GAP-13 implemented (2026-06-13); GAP-04/05/08/10 mapped + SKILL.md parsing (2026-06-14); live-verified via BL018_TEST_SV (2026-06-14); remaining LOW gaps (GAP-06/07/09/11) tracked in `references/open-items.md`
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
> Implemented in CLI SKILL.md Step 9a (identifier resolution pre-pass), shared rules (ts-from-snowflake-rules.md), and formula translation (ts-snowflake-formula-translation.md). Option B (group_aggregate, no schema changes) chosen as default. Mirrored to CoCo.

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
> Facts parsed as `{table_alias, fact_name, expression, comment, synonyms, access_modifier}`. Public facts emitted as `formulas[]` entries with `column_type: ATTRIBUTE`. Private facts emitted but noted in report. Mirrored to CoCo.
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
> Three-step resolution in Step 9a: physical column → `[TABLE::col]`; fact → `[Fact Display Name]` formula reference; metric → double aggregation. Mirrored to CoCo.
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
> If no `relationships` block exists, Steps 7 (join mapping) and related sections are skipped. Model TML produced with `model_tables[]` entries and no `joins_with` entries. Mirrored to CoCo.

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

## BL-017 — Cursor mirror sync: close version gaps or retire runtime

**Source:** 2026-06-13 mirror parity audit (Plan 3)
**Affects:** All 7 behind-version Cursor `.mdc` mirrors (see `agents/SYNC-DEBT.md`)
**Status:** Done (2026-06-14) — Cursor runtime retired
> Retired: `agents/cursor/` deleted, all validators/rules/docs updated to remove Cursor references. No one was using Cursor with these skills and there was no way to test it. See PR for full change list.

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
**Status:** Done (2026-06-14) — documentation, SKILL.md parsing, and live verification complete
> Live-verified on se-thoughtspot via BL018_TEST_SV (GUID: 93b6ff6b). All 4 sub-items confirmed: range join (EMP_TO_PERIOD), filter label (IS_SENIOR → boolean formula), composite equi-join (discovered via column overlap on EMPLOYEE_SUMMARY_VW), verified queries (3 entries → NLS Feedback TML). Also verified: I8 duplicate column_id detection, metric-on-fact resolution, view-backed table source. Coverage matrix added to `references/coverage-matrix.md`.
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
---

