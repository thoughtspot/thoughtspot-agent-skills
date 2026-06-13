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

### GAP-04: Derived metrics (view-level, cross-table) — MEDIUM

**What it is:** The `DESCRIBE SEMANTIC VIEW` output shows `DERIVED_METRIC` as a
distinct object kind. These are metrics defined at the view level (not anchored to
any single table) that can reference metrics from multiple tables.

**Current state:** Unknown whether `GET_DDL` emits these differently from regular
metrics. Need to test with a live SV that has derived metrics.

**Proposed mapping:** If they appear as regular metric entries in the DDL but reference
multiple table aliases, treat them as cross-table formulas. ThoughtSpot formulas can
reference columns from multiple tables in the same model.

**Action required:** Test `GET_DDL` on a view with derived metrics to confirm DDL format,
then document the pattern.

---

### GAP-05: Verified queries / AI verified queries — LOW

**What it is:** SVs can include question + SQL pairs that train Cortex Analyst.
`DESCRIBE SEMANTIC VIEW` shows these as `AI_VERIFIED_QUERY`.

**ThoughtSpot equivalent:** No direct equivalent. Closest options:
- `data_model_instructions` in the model (Spotter instructions)
- Manual Liveboard creation from the verified SQL

**Proposed mapping:** Log in the conversion report. Optionally extract question text
as Spotter instruction hints (user decision at review checkpoint).

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

### GAP-08: Range joins / ASOF joins — MEDIUM

**What it is:** Snowflake SVs support:
- `CONSTRAINT` with `DISTINCT_RANGE` (start_column, end_column) for range joins
- ASOF joins (temporal pattern matching)

These appear in `DESCRIBE` output and are used for complex temporal relationships
(e.g. matching flights to weather windows).

**ThoughtSpot equivalent:** None. ThoughtSpot only supports equi-joins.

**Proposed mapping:**
- Flag as unsupported at Step 10 review checkpoint
- Recommend creating a pre-joined view that materialises the range/ASOF logic
- Columns dependent on these joins are omitted unless the pre-joined view exists

**Files to update:**
- SKILL.md Step 4 — detect range/ASOF relationships and flag
- SKILL.md Step 10 — warn user about unsupported join types

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

### GAP-10: Filters on logical tables — MEDIUM

**What it is:** SVs support defining permanent filters on logical tables (Snowflake
docs: "Defining filters for logical tables"). These restrict which rows Cortex Analyst
considers when querying that table.

**ThoughtSpot equivalent:** No table-level filter in model TML. Closest:
- Row-level security (different mechanism)
- Worksheet-level filters (not available in models)

**Proposed mapping:** Log in report. Flag for manual implementation as a ThoughtSpot
View (SQL view with WHERE clause) if the filter is business-critical.

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
| **HIGH** | GAP-01, GAP-02, GAP-12 | Cannot convert production SVs like SHIFTS7_PAYROLL1 without these |
| **MEDIUM** | GAP-03, GAP-04, GAP-08, GAP-10, GAP-13 | Will encounter in real-world SVs; workarounds exist but are manual |
| **LOW** | GAP-05, GAP-06, GAP-07, GAP-09, GAP-11 | Nice-to-have; no direct TS equivalent for most |

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
