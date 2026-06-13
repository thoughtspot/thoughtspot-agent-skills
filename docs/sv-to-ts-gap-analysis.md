# Semantic View → ThoughtSpot Model: Gap Analysis

Exhaustive review of Snowflake Semantic View constructs vs what `ts-convert-from-snowflake-sv`
currently handles. Each gap includes severity, examples, and proposed ThoughtSpot mapping.

Reference SV for testing: `DEMO.SEMANTIC_TESTING.SHIFTS7_PAYROLL1`

---

## Currently Mapped (working)

| SV Construct | TS Mapping | Status |
|---|---|---|
| `tables (...)` block | `model_tables[]` | Done |
| Table aliases (explicit + default) | `model_tables[].id` / `name` | Done |
| `primary key (col)` | Join target identification | Done |
| Table-level `comment='...'` | TS Table TML `table.description` | Done |
| `relationships (REL as FROM(FK) references TO(PK))` | `joins[]` inline or `referencing_join` | Done |
| `dimensions (TABLE.COL as NAME)` | `columns[]` with `column_type: ATTRIBUTE` | Done |
| `metrics (TABLE.COL as AGG(NAME))` — simple | `columns[]` with `column_type: MEASURE` + aggregation | Done |
| `metrics` — complex SQL expressions | `formulas[]` with translated formula | Done |
| `metrics` — `NON ADDITIVE BY` (semi-additive) | `last_value`/`first_value` formula | Done |
| `metrics` — window functions (`OVER (PARTITION BY ...)`) | `group_sum`/`group_aggregate` | Done |
| `metrics` — `PARTITION BY EXCLUDING` | `group_aggregate(... query_groups()-{dim})` | Done |
| `metrics` — cumulative (`ROWS BETWEEN UNBOUNDED...`) | `cumulative_sum` etc. | Done |
| `with synonyms=(...)` on dim/metric | column `name` (1st) + `properties.synonyms` (rest) | Done |
| `comment='...'` on dim/metric | column `description` | Done |
| Top-level `comment='...'` | `model.description` | Done |
| `with extension (CA='...')` | Parsed for type confirmation only | Done |
| Computed dimensions (`DATEDIFF(...)`, `CONCAT(...)`) | `formulas[]` with `column_type: ATTRIBUTE` | Done |
| `COUNT(DISTINCT col)` | `unique count(...)` formula | Done |

---

## Gaps

### GAP-01: `facts (...)` section — HIGH

**What it is:** The DDL `facts` block defines row-level computed expressions (not
aggregates). Facts are intermediate calculations used by metrics.

**Example from `SHIFTS7_PAYROLL1`:**

```sql
facts (
    PAYROLL_COMPANIES.COMPANY_AGE_MONTHS as DATEDIFF(month, PAYROLL_COMPANY_CREATED_AT, CURRENT_DATE())
        comment='The number of months this company has been on the platform',
    PAYROLL_COMPANIES.INACTIVE_LOCATIONS_SINCE_ACTIVATION as NUMBER_LOCATIONS_AT_ACTIVATION - NUMBER_ACTIVE_PAYROLL_LOCATIONS
        comment='Number of locations that were active at activation but are no longer active'
)
```

**Current state:** Step 4 parser extracts `tables`, `relationships`, `dimensions`, and
`metrics`. No mention of parsing a `facts` block.

**Proposed mapping:**

Facts are row-level expressions. In ThoughtSpot, they map to either:
- A `formulas[]` entry with `column_type: MEASURE` (if the fact is numeric and intended
  for aggregation by downstream metrics)
- A pre-computed column in the physical table (if it already exists there)

If the fact references other columns from the same table, the formula translates the
SQL expression using standard rules from `ts-snowflake-formula-translation.md`.

**Example translation:**
```yaml
formulas:
- name: "Company Age Months"
  expr: "diff_months ( today () , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )"
  properties:
    column_type: MEASURE
```

**Files to update:**
- `ts-from-snowflake-rules.md` — add Facts section to DDL Format
- SKILL.md Step 4 — add extraction of `facts` block
- SKILL.md Step 9 — translate fact expressions using existing formula rules

---

### GAP-02: Double aggregation (metric-referencing-metric) — HIGH

**What it is:** A metric whose expression references another metric by
`table_alias.metric_name`. The engine resolves the inner metric first (grouped by
the join key), then applies the outer aggregate.

**Example from `SHIFTS7_PAYROLL1`:**

```sql
-- Inner metric (PAYROLL_LOCATIONS):
PAYROLL_LOCATIONS.NUMBER_OF_LOCATIONS as COUNT(PAYROLL_LOCATION_ID)

-- Outer metric (PAYROLL_COMPANIES, referencing inner):
PAYROLL_COMPANIES.AVERAGE_LOCATIONS_PER_COMPANY as AVG(payroll_locations.number_of_locations)
```

**Current state:** Step 9 translates metric expressions assuming column references
resolve to physical columns. It does not detect when a reference targets another metric.

**Proposed mapping:** See `docs/double-aggregation-guide.md` and backlog `BL-003`.

Two options:
- **Option A (recommended):** Pre-aggregated column + simple `average([TABLE::col])`
- **Option B:** `average(group_aggregate(count([PAYROLL_LOCATIONS::PAYROLL_LOCATION_ID]), {[PAYROLL_COMPANIES::PAYROLL_COMPANY_ID]}, {}))`

**Detection rule:** When parsing a metric expression like `AVG(table_alias.name)`,
check whether `name` matches a defined metric (from the metrics block) rather than
a physical column or fact.

**Files to update:**
- `ts-snowflake-formula-translation.md` — add Double Aggregation section
- SKILL.md Step 9 — add detection + resolution logic
- `ts-from-snowflake-rules.md` — document the pattern

---

### GAP-03: No relationships defined (joinless SVs) — MEDIUM

**What it is:** A semantic view may have no `relationships (...)` section at all.
All dimensions and metrics operate within a single table or across tables with no
declared joins.

**Current state:** Step 7 ("Find join names") assumes relationships exist. If the
relationships block is empty or absent, the skill should produce a model with:
- A single `model_tables` entry (or multiple entries with no `joins[]`)
- No `referencing_join` on any table

**Proposed mapping:** No-op — just skip Step 7 and produce `model_tables[]` entries
without `joins[]`. The model is valid without joins.

**Files to update:**
- SKILL.md Step 7 — add "if no relationships, skip this step" clause
- SKILL.md Step 8 — handle the single-table / no-join case in TML skeleton

---

### GAP-04: Derived metrics / view-backed sources — MEDIUM — CLARIFIED (2026-06-13)

**What it is:** Two related patterns:

1. **Derived metrics:** `DESCRIBE SEMANTIC VIEW` shows `DERIVED_METRIC` as a distinct
   object kind. These are metrics defined at the view level that can reference metrics
   from multiple tables. In GET_DDL output they appear as regular metric entries
   referencing multiple table aliases.

2. **View-backed table sources:** Snowflake views referenced in the `tables()` block
   instead of physical tables. Confirmed: `tables()` accepts fully-qualified view names
   (verified 2026-06-13 with EMPLOYEE_SUMMARY_VW). Subqueries are NOT supported — the
   source must be a named database object.

**ThoughtSpot equivalent:**
- Cross-table derived metrics → formulas referencing columns from multiple `model_tables`
- View-backed sources → ThoughtSpot Table objects can point to views (connection table
  browser shows both tables and views)

**Mapping:** View-backed sources are handled identically to physical tables — no special
logic needed. Flag in report: "Source: Snowflake view (no primary key declared)".
See `ts-from-snowflake-rules.md` "View-Backed Sources".

---

### GAP-05: Verified queries / AI verified queries — MEDIUM — MAPPED (2026-06-13)

**What it is:** SVs can include question + SQL pairs that train Cortex Analyst.
`DESCRIBE SEMANTIC VIEW` shows these as `AI_VERIFIED_QUERY`. Full DDL format:

```sql
ai_verified_queries (
    QUERY_NAME AS (
        QUESTION 'natural language question'
        VERIFIED_AT unix_epoch_seconds
        SQL 'SELECT ... using SV logical names'
    )
)
```

**ThoughtSpot equivalent:** NLS Feedback TML (`nls_feedback.feedback[]` entries).
Each verified query maps to a `REFERENCE_QUESTION` entry with `feedback_phrase` (from
QUESTION) and `search_tokens` (translated from SQL using the column mapping).

**Mapping:** Parse verified queries in Step 4. After Model import (Step 12), translate
SQL to search tokens using the column name mapping, generate NLS Feedback TML, and
import as a separate payload. See `ts-from-snowflake-rules.md` "Verified Queries →
NLS Feedback TML" and `agents/shared/schemas/thoughtspot-feedback-tml.md`.

---

### GAP-06: Custom instructions — LOW

**What it is:** SVs support `CUSTOM_INSTRUCTIONS` with `AI_QUESTION_CATEGORIZATION`
and `AI_SQL_GENERATION` properties that guide Cortex Analyst behaviour.

**ThoughtSpot equivalent:** `data_model_instructions` in the model TML (guides Spotter).

**Proposed mapping:**
1. Extract custom instruction text from the DDL or DESCRIBE output
2. Present to user at review checkpoint (Step 10)
3. If user approves, add as `data_model_instructions` in the model TML

**Files to update:**
- SKILL.md Step 4 — parse custom instructions if present in DDL
- SKILL.md Step 10 — present as optional Spotter instructions

---

### GAP-07: Table synonyms — LOW

**What it is:** SVs support `with synonyms=(...)` on table entries in the `tables`
block. Example from Snowflake docs: `ORDERS with synonyms=('sales orders')`.

**ThoughtSpot equivalent:** ThoughtSpot models have no table-level synonym concept.

**Proposed mapping:** Log in report. Could optionally:
- Add table synonyms to `model.description` for context
- Use in `data_model_instructions` for Spotter

---

### GAP-08: Range joins / ASOF joins — MEDIUM — MAPPED (2026-06-13)

**What it is:** Snowflake SVs support:
- `constraint ... distinct range between START and END exclusive` on table entries
- `references TABLE(between START and END exclusive)` in relationships (range join)
- `references TABLE(COL, ASOF COL)` in relationships (ASOF/temporal join)

**ThoughtSpot equivalent:** Model TML `joins[].on` supports arbitrary expressions
including `<`, `>`, `>=`, `AND`. Verified via live TML export showing range predicates
in the `on` field.

**Mapping:**
- Range join → `'on': '[FROM::COL] >= [TO::START] and [FROM::COL] < [TO::END]'`
  (half-open interval from `exclusive` keyword)
- ASOF join → `'on': '[FROM::COL1] = [TO::COL1] and [FROM::COL2] >= [TO::ASOF_COL]'`
- Both use `type: LEFT_OUTER`, `cardinality: MANY_TO_ONE`

See `ts-from-snowflake-rules.md` "Range Joins → ThoughtSpot".

---

### GAP-09: Private facts and metrics (`ACCESS_MODIFIER: PRIVATE`) — LOW

**What it is:** SVs support marking facts and metrics as private — helper columns
not exposed to end users querying the semantic view.

**ThoughtSpot equivalent:** No "private" concept in models. All columns are visible.

**Proposed mapping:** Options:
- **Skip** private facts/metrics (they're implementation helpers, not user-facing)
- **Include** with `index_type: DONT_INDEX` so Spotter ignores them

Recommend: Skip by default, present as option at review checkpoint if any exist.

---

### GAP-10: Filter labels on facts/dimensions — MEDIUM — MAPPED (2026-06-13)

**What it is:** SVs support `LABELS = (FILTER)` on facts and dimensions. These are
boolean expressions that Cortex Analyst can use as optional WHERE clauses. They are
NOT permanently auto-applied — they are available for use in queries.

DDL syntax: `TABLE.NAME labels = (filter) as BOOLEAN_EXPR`

**ThoughtSpot equivalent:** Two options depending on intent:
- **Boolean formula column (default)** — matches SV semantics (available, not auto-applied)
- **Model filter** — `model.filters[]` with optional `apply_on_tables` scoping.
  Without `apply_on_tables` = always applied. With `apply_on_tables` = only when
  listed tables are in the search.

**Mapping:** Create as boolean formula column by default. Offer model filter as opt-in
at the Step 10 review checkpoint. See `ts-from-snowflake-rules.md` "Filter Labels →
ThoughtSpot".

---

### GAP-11: `unique_keys` on tables — LOW

**What it is:** SVs support `unique_keys` declarations beyond primary key.

**ThoughtSpot equivalent:** None — ThoughtSpot doesn't use key declarations.

**Proposed mapping:** Not mapped. Log if present but no action needed.

---

### GAP-12: Metric references to facts — HIGH

**What it is:** Metrics that reference a fact by name (not a physical column). Since
facts are computed expressions, the skill must resolve the fact expression when
translating the metric.

**Example from `SHIFTS7_PAYROLL1`:**
```sql
-- Fact:
PAYROLL_COMPANIES.INACTIVE_LOCATIONS_SINCE_ACTIVATION as
    NUMBER_LOCATIONS_AT_ACTIVATION - NUMBER_ACTIVE_PAYROLL_LOCATIONS

-- Metric referencing the fact:
PAYROLL_COMPANIES.TOTAL_INACTIVE_LOCATIONS_SINCE_ACTIVATION as
    SUM(payroll_companies.inactive_locations_since_activation)
```

**Current state:** If `inactive_locations_since_activation` is a physical column on
the table, the skill maps it fine. But if it only exists as a SV fact (computed), the
skill needs to either:
- Resolve the fact expression and inline it: `sum([TABLE::NUMBER_LOCATIONS_AT_ACTIVATION] - [TABLE::NUMBER_ACTIVE_PAYROLL_LOCATIONS])`
- Or reference the fact's ThoughtSpot formula (if created from GAP-01)

**Proposed mapping:** Two approaches depending on whether the fact maps to a physical column:
1. Check if the fact's expression column exists in the TS Table TML → use `column_id`
2. If not → inline the translated fact expression inside the metric formula

**Files to update:**
- SKILL.md Step 9 — add fact-reference resolution before formula translation

---

### GAP-13: Window metrics referencing other metrics — MEDIUM

**What it is:** Window function metrics where the windowed expression references
another metric rather than a physical column.

**Example from `SHIFTS7_PAYROLL1`:**
```sql
PAYROLL_COMPANIES.CUMULATIVE_COMPANIES as SUM(payroll_companies.number_of_companies) OVER (
    ORDER BY payroll_companies.payroll_company_created_at
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
```

Here `payroll_companies.number_of_companies` is itself `COUNT(PAYROLL_COMPANY_ID)`.

**Current state:** The skill handles window functions but assumes the inner reference
resolves to a physical column or pre-defined metric alias.

**Proposed mapping:** Same resolution pattern as GAP-02 — detect that
`number_of_companies` is a metric, and translate as:
```
cumulative_sum ( count ( [PAYROLL_COMPANIES::PAYROLL_COMPANY_ID] ) , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )
```

Or if using pre-aggregation (Option A from GAP-02):
```
cumulative_sum ( [PAYROLL_COMPANIES::NUMBER_OF_COMPANIES] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )
```

---

## Priority Summary

| Priority | Gaps | Impact |
|---|---|---|
| **HIGH — DONE** | GAP-01, GAP-02, GAP-12 | Implemented 2026-06-13 (identifier resolution engine) |
| **MEDIUM — DONE** | GAP-03, GAP-04, GAP-05, GAP-08, GAP-10, GAP-13 | GAP-03/13 done 2026-06-13; GAP-04/05/08/10 mapped 2026-06-13 + SKILL.md parsing 2026-06-14 (BL-018) |
| **LOW** | GAP-06, GAP-07, GAP-09, GAP-11 | Nice-to-have; no direct TS equivalent for most |

---

## Files Requiring Changes

| File | Gaps Addressed |
|---|---|
| `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` | All gaps (parser + translation steps) |
| `agents/shared/mappings/ts-snowflake/ts-from-snowflake-rules.md` | GAP-01, GAP-02, GAP-03, GAP-08, GAP-12 |
| `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` | GAP-02, GAP-12, GAP-13 |
| `agents/cli/ts-convert-from-snowflake-sv/references/open-items.md` | GAP-04, GAP-08, GAP-10 |
| `docs/double-aggregation-guide.md` | GAP-02 (reference document) |
| `docs/backlog.md` | BL-003 already covers GAP-02; add entries for GAP-01, GAP-12 |

---

## Relationship to `ts-convert-to-snowflake-sv` (reverse direction)

The reverse skill emits `metrics[]` wrappers (not `facts[]`) — `facts[]` emission
is a Future Improvement (see `ts-snowflake-properties.md:448`). The reverse skill
maps ThoughtSpot synonyms/descriptions into the SV DDL. Any changes to fact/metric
resolution in the forward direction should be cross-referenced to ensure bidirectional
consistency.
