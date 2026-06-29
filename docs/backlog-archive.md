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
