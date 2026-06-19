<!-- currency: thoughtspot — 2026-06 (inaugural anchor; verify in next external sweep) -->

# ThoughtSpot Model Conversion Invariants

Canonical hard rules for any skill that converts a source (Tableau / Snowflake SV /
Databricks MV / …) into ThoughtSpot **Model TML**. Every "convert-from" skill MUST
satisfy all invariants below. The `conversion-consistency-auditor` subagent checks
skills against this file; keep the IDs (I1–I10, N1, EXC1) stable so the auditor can cite
them without ambiguity.

> Source skills that established these rules: `ts-convert-from-snowflake-sv` (I1–I4, I6–I7),
> `ts-convert-from-databricks-mv` (I1–I7), and `ts-convert-from-tableau` (I9–I10, verified
> 2026-06-19 against se-thoughtspot). They are proven against live ThoughtSpot imports;
> violations produce the failure modes listed below.

---

## Invariants

### I1 — Every formula has a paired `columns[]` entry

**Rule:** For every entry in `formulas[]`, there must be a corresponding entry in
`columns[]` that references it via `formula_id:`. An unpaired formula is **silently
dropped** by ThoughtSpot on import — no error, no warning, no column in the model.

**Failure mode:** Formula disappears from the model after import. User sees a model with
fewer columns than expected, with no TML import error to diagnose.

**Applies to:** All source dialects (Tableau, Snowflake SV, Databricks MV, …).

**Correct pattern:**
```yaml
formulas:
- id: formula_Total Sales           # id: "formula_" + name
  name: "Total Sales"
  expr: "sum ( [ORDERS::price] * [ORDERS::qty] )"
  properties:
    column_type: MEASURE

columns:
# ... physical columns first ...
- name: "Total Sales"
  formula_id: formula_Total Sales   # must match the formula's id exactly
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX          # see I3
```

---

### I2 — No `aggregation:` inside `formulas[]` entries

**Rule:** Never add an `aggregation:` field to a `formulas[]` entry. Formulas are
self-contained via their `expr`; `aggregation:` belongs only on `columns[]` entries.

**Failure mode:** ThoughtSpot rejects the TML import with:
`FORMULA is not a valid aggregation type`

**Applies to:** All source dialects.

**Correct (formula — no aggregation:):**
```yaml
formulas:
- id: formula_Total Sales
  name: "Total Sales"
  expr: "sum ( [ORDERS::price] * [ORDERS::qty] )"
  properties:
    column_type: MEASURE
    # NO aggregation: here
```

**Wrong (do NOT do this) — `aggregation:` on a formulas entry:**
```yaml
# Single formula entry — aggregation: on it triggers "FORMULA is not a valid aggregation type"
- id: formula_Total Sales
  name: "Total Sales"
  expr: "sum ( [ORDERS::price] * [ORDERS::qty] )"
  properties:
    column_type: MEASURE
    aggregation: SUM    # WRONG — remove this; keep aggregation: only on the columns[] entry
```

`aggregation:` on a `columns[]` formula entry *is* allowed (it defines how the column
aggregates when rolled up). Only the `formulas[]` entry must not carry it.

---

### I3 — `index_type: DONT_INDEX` on computed numeric measures

**Rule:** Every `columns[]` entry that references a formula (i.e., has a `formula_id`)
and is typed as a MEASURE should carry `index_type: DONT_INDEX`.

**Failure mode:** ThoughtSpot may attempt to index the computed column, which is
unnecessary for numeric measures and can produce unexpected search behaviour.

**Applies to:** All source dialects.

**Correct pattern:**
```yaml
columns:
- name: "Total Sales"
  formula_id: formula_Total Sales
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX   # always on computed measures
```

---

### I4 — Join `id` (when present) must equal `name` (exact case)

**Rule:** `id` on a `model_tables[]` entry is optional. When present, it must be
character-for-character identical to the `name` field. Omitting `id:` and referencing tables
by `name:` alone (as the Tableau skill does) is simpler and equally correct. ThoughtSpot
resolves `with:` and `on:` join references against the table's `name` — so if `id` is present
but differs in case, joins silently fail.

**Failure mode:** TML imports without error, but joins are broken at query time:
`"{table_name} does not exist in schema"`

**Applies to:** All source dialects.

**Correct pattern:**
```yaml
model_tables:
- id: FACT_ORDERS          # MUST equal name exactly — often uppercase
  name: FACT_ORDERS        # exact ThoughtSpot table object name
  fqn: "{guid}"
  joins:
  - with: DIM_CUSTOMERS    # must match the target entry's name exactly
    referencing_join: "{join_name}"
- id: DIM_CUSTOMERS        # MUST equal name exactly
  name: DIM_CUSTOMERS
  fqn: "{guid}"
```

**Wrong (do NOT do this):**
```yaml
model_tables:
- id: fact_orders          # WRONG — lowercase id, uppercase name
  name: FACT_ORDERS
```

---

### I5 — COUNT-distinct as `unique count(...)` formula, never `COUNT_DISTINCT` aggregation

**Rule:** Any distinct-count measure must be expressed as a `formulas[]` entry with
`unique count ( [TABLE::col] )`. Never use `aggregation: COUNT_DISTINCT` on a `columns[]`
entry that references a physical column.

**Failure mode:** Using `aggregation: COUNT_DISTINCT` causes ThoughtSpot to silently
override `column_type: MEASURE` → `ATTRIBUTE` on that column, making it unsearchable as
a measure. No import error is raised.

**Applies to:** All source dialects.
- Tableau: `COUNTD(field)` → `unique count ( [TABLE::col] )` formula
- Snowflake SV: `COUNT(DISTINCT col)` metrics → `unique count ( [TABLE::col] )` formula
- Databricks MV: `COUNT(DISTINCT col)` → `unique count ( [TABLE::col] )` formula

**Correct pattern:**
```yaml
formulas:
- id: formula_Unique Customers
  name: "Unique Customers"
  expr: "unique count ( [ORDERS::customer_id] )"
  properties:
    column_type: MEASURE

columns:
- name: "Unique Customers"
  formula_id: formula_Unique Customers
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX
```

**Wrong (do NOT do this):**
```yaml
columns:
- name: "Unique Customers"
  column_id: ORDERS::customer_id
  properties:
    column_type: MEASURE
    aggregation: COUNT_DISTINCT   # WRONG — silently flips to ATTRIBUTE
```

---

### I6 — Connections referenced by name, not GUID

**Rule:** In all TML generated by conversion skills, the connection inside a `table:` or
`sql_view:` block must use the `name:` field — never a GUID.

**Failure mode:** GUIDs are environment-specific. A TML exported from one ThoughtSpot
instance and imported into another will fail with an unresolvable GUID.

**Applies to:** All source dialects.

**Correct pattern:**
```yaml
table:
  connection:
    name: "Snowflake Production"   # display name from ts connections list
```

**Wrong (do NOT do this) — GUID in the connection block:**
```yaml
# connection block — fqn: here causes import failure on any other ThoughtSpot instance
    name: "..."
    fqn: "a1b2c3d4-..."   # WRONG — remove fqn:; use only name:
```

---

### I7 — Consult the formula reference before declaring "untranslatable"

**Rule:** Before classifying any expression as untranslatable, the skill must explicitly
instruct the model to open the formula-translation reference for that source dialect and
check both the forward and reverse tables. Do not decide from syntax alone.

**Failure mode:** Expressions that appear Snowflake-specific or Databricks-specific have
documented ThoughtSpot equivalents. Skipping the reference causes valid columns to be
omitted from the converted model.

**Applies to:** All source dialects. Each skill must cite its own mapping file:
- Tableau: `../../shared/mappings/tableau/tableau-formula-translation.md`
- Snowflake SV: `../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`
- Databricks MV: `../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md`

**Required gate (appears before the untranslatable classification step in every skill):**
> MANDATORY: before classifying any expression as untranslatable, open the formula
> reference for this source dialect and check the reverse table. Do not decide from
> SQL syntax recognition alone.

---

### I8 — No duplicate `column_id` values; second metric on same column must be a formula

**Rule:** Every `column_id` value in `columns[]` must be unique. When a source defines
multiple metrics on the same physical column with different aggregations (e.g.
`SUM(SALARY)` and `AVG(SALARY)`), only ONE may use a `column_id`-based entry. All
others must be expressed as `formulas[]` entries.

**Failure mode:** ThoughtSpot rejects the TML import with:
`"columns should have unique column_id values — duplicate {TABLE::COL}"`

**Applies to:** All source dialects. Common in Snowflake SVs and Databricks MVs where
multiple aggregations on the same column are a standard pattern.

**Correct pattern — first metric as column, second as formula:**
```yaml
columns:
- name: "Total Salary"
  column_id: EMPLOYEES::SALARY
  properties:
    column_type: MEASURE
    aggregation: SUM

formulas:
- id: formula_Avg Salary
  name: "Avg Salary"
  expr: "average ( [EMPLOYEES::SALARY] )"
  properties:
    column_type: MEASURE

columns:
- name: "Avg Salary"
  formula_id: formula_Avg Salary
  properties:
    column_type: MEASURE
```

**Wrong (do NOT do this) — same column_id twice:**
```yaml
columns:
- name: "Total Salary"
  column_id: EMPLOYEES::SALARY       # first use — OK
  properties:
    column_type: MEASURE
    aggregation: SUM
- name: "Avg Salary"
  column_id: EMPLOYEES::SALARY       # WRONG — duplicate column_id
  properties:
    column_type: MEASURE
    aggregation: AVERAGE
```

**Which metric keeps the `column_id`?** Prefer keeping the SUM metric as the
`column_id`-based entry (SUM is the most common default aggregation). Express AVG,
MIN, MAX, COUNT, and other aggregations as formulas.

---

### I9 — Formula cross-references: inline the expression on first import

**Rule:** A formula that references another formula column by bracket notation
(`[Other Formula Name]`) will fail during TML import with "Search did not find
'other formula name'". ThoughtSpot resolves formula references by display name at
import time, but the referenced formula does not yet exist in the object when the
referencing formula is validated.

**Workaround:** Inline the referenced formula's expression directly into the
referencing formula. For example, if formula B uses `[Total Sales]` which is defined
as `group_aggregate(sum([TABLE::AMOUNT]), {[TABLE::REGION]}, {})`, expand formula B
to contain the full `group_aggregate(...)` expression.

**Alternative:** Import base formulas first (no cross-refs), export the model, then
add dependent formulas via a second import using the exported JSON format.

**Failure mode:** TML import returns "Search did not find '{formula_name}'" for every
formula-to-formula bracket reference.

**Applies to:** All source dialects — this is a ThoughtSpot platform constraint, not
source-specific.

---

### I10 — Parameters: `CHAR` for string lists, `list_choice` as objects

**Rule:** String-typed parameters with `list_config` must use `data_type: CHAR`.
`VARCHAR` is accepted by the schema but rejected on import for list parameters.
Each `list_choice` entry must be an object with `value:` (required) and `display_name:`
(recommended) — bare string values are rejected.

**Failure mode:** `data_type: VARCHAR` with `list_config` → "Invalid YAML/JSON syntax"
on import. Bare `list_choice` values → same error.

**Applies to:** All source dialects that generate parameters (Tableau parameters,
future parameter support in SV/MV converters).

**Correct pattern:**
```yaml
parameters:
- name: Currency
  data_type: CHAR
  default_value: "USD"
  list_config:
    list_choice:
    - value: USD
      display_name: USD
    - value: CAD
      display_name: CAD
```

**Wrong (do NOT do this):**
```yaml
parameters:
- name: Currency
  data_type: VARCHAR              # WRONG — fails for list params
  list_config:
    list_choice:
    - USD                          # WRONG — bare strings rejected
    - CAD
```

---

## Naming

### N1 — Model name: bare source name, no prefix

**Rule:** The converted model's `name:` must use the bare source object name (view name,
workbook + datasource name, etc.). Do not prepend environment markers such as `TEST_`,
`TEST_SV_`, `TEST_MV_`, or similar prefixes.

**Rationale:** Production migrations must not carry test markers. If the user needs a
prefix for local testing, they can override the name interactively — every skill should
ask the user if they want a different name before importing.

**Applies to:** All source dialects. Supersedes any prior per-skill default that used
`TEST_SV_*` or `TEST_MV_*` prefixes.

**Correct:**
```yaml
model:
  name: "DUNDER_MIFFLIN_SALES"     # bare view/datasource name
```

**Wrong (do NOT do this):**
```yaml
model:
  name: "TEST_SV_DUNDER_MIFFLIN_SALES"   # WRONG — environment marker in production TML
```

---

## Pass-through translation policy

### PT1 — Scalar pass-through is reliable; aggregate pass-through must be flagged for review
When a source function has no native ThoughtSpot equivalent but the underlying warehouse
provides an equivalent SQL function, translate it via a ThoughtSpot pass-through op
(`sql_*_op`) rather than dropping it.

- **Scalar pass-throughs** (`sql_string_op`, `sql_int_op`, `sql_double_op`, `sql_bool_op`,
  `sql_date_op`, `sql_time_op`, `sql_date_time_op`) are row-level and reliable — use freely.
- **Aggregate pass-throughs** (`sql_*_aggregate_op`) DO work but interact with ThoughtSpot's
  query-time aggregation/grouping context, so correctness is not guaranteed. ALWAYS mark any
  aggregate pass-through with a "⚑ flag for review" note and surface it in the conversion output.

**Applies to:** all convert-from skills (Tableau, Snowflake SV, Databricks MV).

---

## Intentional differences (do NOT harmonize)

### EXC1 — Cumulative/moving: model formula vs answer-level

`cumulative_*` and `moving_*` functions **are valid as model formulas** when the first
argument is an **unaggregated column reference** — verified 2026-06-13 on se-thoughtspot
(GUID `889a704f-2714-4649-9cea-23551cb68d64`, model `TEST_SV_DMSI_AI_CONTEXT`):

```
cumulative_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_ORDER::ORDER_DATE] )
```

The constraint is on the **first argument's aggregation state**, not on the source dialect:

| First arg form | Model formula? | Why |
|---|---|---|
| Unaggregated column ref: `[table::col]` | **YES** — valid in `formulas[]` | ThoughtSpot applies its own aggregation at query time |
| `group_aggregate()` wrapped: `group_aggregate(max([col]), query_groups(), query_filters())` | **YES** — valid in `formulas[]` | `group_aggregate` encapsulates the aggregation so the outer function sees a single value, not an aggregate expression |
| Aggregated expression: `sum([table::col])` | **NO** — rejected with *"expects 1st argument to be not aggregated"* | Already-aggregated args conflict with the query engine's own aggregation; use `group_aggregate()` wrapper instead |
| Measure display name: `[Sales]` | **Answer-level only** — valid in `search_query`, not in model `formulas[]` | Display-name refs resolve in the live query context, not at model definition time |

**Implications per source:**

| Source | Treatment | Reason |
|---|---|---|
| Snowflake SV / Databricks MV window functions | Translate to model formulas with unaggregated `[table::col]` refs | Source column refs are unaggregated — maps directly |
| Tableau `RUNNING_SUM(SUM([col]))` / `WINDOW_AVG(SUM([col]))` | **Model formula is valid** if converted to unaggregated form: `cumulative_sum ( [table::col] , [sort_col] )`. Fall back to answer-level if the sort dimension cannot be determined from the workbook | The Tableau `SUM()` wrapper must be stripped — the unaggregated column ref goes to the model formula |
| Tableau positional table calcs (`INDEX`, `LOOKUP`, `FIRST`, `LAST`, `SIZE`, `PREVIOUS_VALUE`) | Answer-level only or untranslatable — do **NOT** emit as model formulas | These are row-position-dependent; no ThoughtSpot model-level equivalent |
| `RANK`, `PERCENTILE` | Answer-level: use `rank()` in `search_query` | See Running / Cumulative Functions section in formula-translation.md |
