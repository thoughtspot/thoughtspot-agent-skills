# Reverse Mapping Rules Reference

Snowflake Semantic View DDL → ThoughtSpot Model TML. Consult during Steps 4–9.

---

## Semantic View DDL Format

`GET_DDL('SEMANTIC_VIEW', 'db.schema.view')` returns a SQL DDL string. The
real format (from Snowflake) is:

```sql
create or replace semantic view DB.SCHEMA.VIEW_NAME
    tables (
        -- Default alias = last segment of the table name
        DB.SCHEMA.TABLE_NAME [primary key (COL)],
        -- Explicit alias (reserved words, name conflicts)
        ALIAS as DB.SCHEMA."TABLE_NAME" [primary key (COL)],
        -- Table-level comment + synonyms
        DB.SCHEMA.TABLE comment='...' with synonyms=('Alt Name','...'),
        ...
    )
    relationships (
        REL_NAME as FROM_TABLE(FROM_COL) references TO_TABLE(TO_COL),
        ...
    )
    -- FACTS: row-level named expressions referenced by metrics (not all SVs have this)
    facts (
        -- Format 1: Physical column reference (aliases a table column)
        TABLE.COL as view_alias.FACT_NAME [comment='...'] [with synonyms=(...)],
        -- Format 2: Expression-based fact (computed from table columns)
        EXPR as view_alias.FACT_NAME [comment='...'] [with synonyms=(...)],
        -- Format 3: Private fact (hidden from Cortex Analyst, may be referenced by metrics)
        PRIVATE TABLE.COL as view_alias.FACT_NAME,
        PRIVATE EXPR as view_alias.FACT_NAME,
        ...
    )
    dimensions (
        -- All dimensions at view level (NOT nested per-table)
        TABLE_REF.VIEW_COL as view_alias.DIM_NAME [comment='...'] [with synonyms=(...)],
        -- Visibility modifier: PRIVATE dims are hidden from Cortex Analyst
        PRIVATE TABLE_REF.VIEW_COL as view_alias.DIM_NAME,
        -- Cortex Search Service on a dimension
        TABLE_REF.VIEW_COL as view_alias.DIM_NAME with cortex search service SVC_NAME,
        ...
    )
    -- Uniqueness constraints (optional; inform cardinality)
    unique (TABLE.COL_A, TABLE.COL_B) distinct TABLE.COL_C range between X and Y,
    metrics (
        -- Simple: TABLE_REF.VIEW_COL as AGG(view_alias.METRIC_NAME)
        TABLE_REF.VIEW_COL as SUM(view_alias.METRIC_NAME) [comment='...'],
        -- Semi-additive: non additive by (DATE_TABLE.COL asc|desc nulls last)
        TABLE_REF.VIEW_COL non additive by (DATE.COL desc nulls last) as SUM(view_alias.NAME),
        -- Metric referencing another metric alias (USING <relationship>)
        TABLE_REF.metric_alias USING REL_NAME as AGG(view_alias.NAME),
        -- Complex expressions appear as the right-hand side
        ...
    )
    comment='top-level view description'
    -- Cortex Analyst clauses (optional; may appear after comment)
    ai_sql_generation = 'ON'|'OFF'
    ai_question_categorization = 'ON'|'OFF'
    ai_verified_queries (
        'query text' verified_by = 'username' ...
    )
    with extension (CA='{...cortex_analyst_context_json...}');
```

**BIRD Financial example (abbreviated):**

```sql
create or replace semantic view BIRD_FINANCIAL_SV
    tables (
        BIRD.FINANCIAL_SV.TRANS,
        ORDER_TBL as BIRD.FINANCIAL_SV."ORDER",
        BIRD.FINANCIAL_SV.ACCOUNT primary key (ACCOUNT_ID),
        BIRD.FINANCIAL_SV.CLIENT_DISTRICT primary key (CLIENT_DISTRICT_PK_ID)
    )
    relationships (
        TRANS_TO_ACCOUNT as TRANS(TRANS_ACCOUNT_ID) references ACCOUNT(ACCOUNT_ID),
        ORDER_TO_ACCOUNT as ORDER_TBL(ORDER_ACCOUNT_ID) references ACCOUNT(ACCOUNT_ID)
    )
    dimensions (
        TRANS.TRANS_ID as trans.TRANS_ID comment='transaction id',
        TRANS.TRANS_ACCOUNT_ID as trans.TRANS_ACCOUNT_ID,
        TRANS.TRANS_DATE as trans.TRANS_DATE comment='date of transaction'
    )
    metrics (
        TRANS.TRANS_AMOUNT as SUM(trans.TRANS_AMOUNT) comment='amount in USD'
    )
    with extension (CA='...');
```

**Key differences from hypothetical "nested" DDL:**
- No `base table` keyword — table references are fully-qualified directly
- Dimensions and metrics are **flat at view level**, not nested under tables
- Table alias: `ALIAS as DB.SCHEMA.TABLE` (not `TABLE_NAME as ALIAS`)
- Relationship: `REL_NAME as FROM(COL) references TO(COL)` (not `from ... key ... to ... key ...`)
- Extension: `with extension (CA='...')` (not `extension = '...'`)

**DDL parsing notes:**
- The table alias defaults to the last part of the table name (e.g., `BIRD.FINANCIAL_SV.TRANS` → alias `TRANS`).
  When an explicit alias is given (`ORDER_TBL as BIRD.FINANCIAL_SV."ORDER"`), use that alias.
- Each dimension entry format: `TABLE_ALIAS.VIEW_COLUMN as view_alias.DIM_NAME`
  - Left side: column name IN THE VIEW/TABLE referenced by TABLE_ALIAS
  - Right side: how it appears inside the semantic view
- Each metric entry format: `TABLE_ALIAS.VIEW_COLUMN as AGG(view_alias.METRIC_NAME)`
  - The `AGG(...)` expression defines the aggregation
- `comment='...'` is optional metadata — use as a ThoughtSpot column description

---

## Column Name Resolution

The `column_id` in the model TML must use the column name as it appears in the
**ThoughtSpot Table object's TML** — not the left-hand side of the semantic view
dimension entry.

**The correct approach:** Build ThoughtSpot Table objects that point directly to the
same Snowflake objects (tables or views) that the semantic view references. When the
ThoughtSpot table and the semantic view reference the same object, column names match
and no translation is needed.

Example (straightforward case):
```
Semantic view tables block:  BIRD.SUPERHERO_SV.SUPERHERO
ThoughtSpot table points to: BIRD.SUPERHERO_SV.SUPERHERO  ← same object
Semantic view dimension:     SUPERHERO.SUPERHERO_NAME as superhero.SUPERHERO_NAME
ThoughtSpot column name:     SUPERHERO_NAME
Correct column_id:           superhero::SUPERHERO_NAME
```

**Always export ThoughtSpot Table TMLs and use their column names** — do not assume
they match the semantic view left-hand side. Some Snowflake views rename columns
internally (e.g., a view may expose `EYE_COLOUR` as `COLOUR`), so the ThoughtSpot
TML is the authoritative source:

```bash
ts tml export {guid1} {guid2} ... --profile {profile}
```

Use `table.columns[].name` from each returned TML as the `column_id` value.

---

## CA Extension JSON

The `with extension (CA='...')` block contains a JSON object with Cortex Analyst
configuration. Parse it to quickly determine column types per table.

Structure:
```json
{
  "tables": [
    {
      "name": "trans",
      "dimensions": [{"name": "trans_id"}, {"name": "trans_account_id"}, ...],
      "metrics": [{"name": "trans_amount", "default_aggregation": "sum"}, ...],
      "time_dimensions": [{"name": "trans_date"}]
    },
    ...
  ],
  "relationships": [{"name": "trans_to_account"}, ...]
}
```

Use this for column type classification:
- `dimensions` → `ATTRIBUTE`
- `time_dimensions` → `ATTRIBUTE` (ThoughtSpot infers date type from the Snowflake column)
- `metrics` → `MEASURE` (use `default_aggregation` as the aggregation type)

The CA extension `name` values are **lowercase aliases** of the semantic view dimension names.
They confirm which columns are metrics vs attributes, but do NOT give you the authoritative `column_id` names.

---

## Column Type Classification

Apply this decision tree:

```
Is the column listed in the CA extension metrics block (or has an AGG(…) expression)?
  YES → Is the expr a simple AGG(view.col) pattern?
          YES → MEASURE column with aggregation from AGG function
          NO  → formula column (translate SQL → ThoughtSpot formula)
  NO  → Is it in time_dimensions (or data type DATE/TIMESTAMP)?
          YES → ATTRIBUTE column (ThoughtSpot infers date type from the Snowflake column)
          NO  → ATTRIBUTE column
```

---

## Aggregation Mapping

For simple metric EXPR patterns (`AGG(view_alias.col)`):

| Snowflake SQL aggregate | ThoughtSpot `aggregation` | Column type |
|---|---|---|
| `SUM(view.col)` | `SUM` | MEASURE |
| `COUNT(view.col)` | `COUNT` | MEASURE |
| `COUNT(DISTINCT view.col)` | `COUNT_DISTINCT` | MEASURE |
| `AVG(view.col)` | `AVERAGE` | MEASURE |
| `MIN(view.col)` | `MIN` | MEASURE |
| `MAX(view.col)` | `MAX` | MEASURE |

When the aggregation is COUNT_DISTINCT, **always use a formula column** rather than a
MEASURE with `COUNT_DISTINCT`:
```
unique count ( [TABLE_ID::col_name] )
```
This is required (not just preferred) when the same column is also used as an
ATTRIBUTE dimension in `columns[]`. ThoughtSpot rejects models where the same
`column_id` appears more than once — the duplicate `column_id` error fires even when
the two entries have different `column_type` values. Moving COUNT_DISTINCT to
`formulas[]` avoids this entirely.

---

## Computed Dimensions (ATTRIBUTE-type Formulas)

Some semantic view dimensions are derived from SQL expressions rather than a single
physical column. These are identified by a non-`view_alias.NAME` right-hand side:

```sql
-- Simple dimension (physical column):
DM_ORDER.ORDER_DATE as dm_order.ORDER_DATE

-- Computed dimension (SQL expression):
DM_ORDER.DAYS_TO_SHIP as DATEDIFF('day', dm_order.ORDER_DATE, dm_order.SHIPPED_DATE)
DM_EMPLOYEE.EMPLOYEE_NAME as CONCAT(dm_employee.FIRST_NAME, ' ', dm_employee.LAST_NAME)
```

Computed dimensions translate to `formulas[]` entries with `column_type: ATTRIBUTE`:

```yaml
formulas:
- name: "Days To Ship"
  expr: "diff_days ( [dm_order::SHIPPED_DATE] , [dm_order::ORDER_DATE] )"
  properties:
    column_type: ATTRIBUTE
- name: "Employee Name"
  expr: "concat ( [dm_employee::FIRST_NAME] , ' ' , [dm_employee::LAST_NAME] )"
  properties:
    column_type: ATTRIBUTE
```

Like MEASURE formulas, computed ATTRIBUTE dimensions **do appear in `columns[]`** — add a
`columns[]` entry with `formula_id:` for each one (no `aggregation` needed for ATTRIBUTE
entries). The formula translation rules (column references, function names) are identical
to MEASURE formulas.

```yaml
columns:
- name: "Employee Name"
  formula_id: formula_Employee Name
  properties:
    column_type: ATTRIBUTE
formulas:
- id: formula_Employee Name
  name: "Employee Name"
  expr: "concat ( [dm_employee::FIRST_NAME] , ' ' , [dm_employee::LAST_NAME] )"
  properties:
    column_type: ATTRIBUTE
```

**`diff_days` argument order:** ThoughtSpot uses `(end, start)` — the opposite of
Snowflake's `DATEDIFF('day', start, end)`. Always check the arg order:
```
DATEDIFF('day', ORDER_DATE, SHIPPED_DATE)  →  diff_days ( [SHIPPED_DATE] , [ORDER_DATE] )
```

---

## SQL → ThoughtSpot Formula Translation

> See **[ts-snowflake-formula-translation.md](ts-snowflake-formula-translation.md)** for the full bidirectional
> translation reference (Snowflake SQL ↔ ThoughtSpot formulas), including window functions,
> LOD expressions, and semi-additive patterns.

Apply these rules when a metric EXPR is **not** a simple `AGG(view.col)`.
The quick-reference tables below cover the most common cases; consult ts-snowflake-formula-translation.md
for edge cases and complex expressions.

**Column reference conversion:**
```
SQL:            TABLE_ALIAS.VIEW_COLUMN_NAME
ThoughtSpot:    [TABLE_ID::col_name]
```
`TABLE_ID` is the `id` value from the model_tables entry.
`col_name` is the column name from the ThoughtSpot Table TML.

**Aggregate functions:**

| Snowflake SQL | ThoughtSpot formula |
|---|---|
| `SUM(x)` | `sum ( [x] )` |
| `COUNT(x)` | `count ( [x] )` |
| `COUNT(DISTINCT x)` | `unique count ( [x] )` |
| `AVG(x)` | `average ( [x] )` |
| `MIN(x)` | `min ( [x] )` |
| `MAX(x)` | `max ( [x] )` |

**Arithmetic and conditional:**

| Snowflake SQL | ThoughtSpot formula |
|---|---|
| `a * b` | `[a] * [b]` |
| `a + b` | `[a] + [b]` |
| `a - b` | `[a] - [b]` |
| `(a) / NULLIF(b, 0)` | `safe_divide ( [a] , [b] )` |
| `a / b` | `[a] / [b]` *(warn: no null guard)* |
| `CASE WHEN c THEN a ELSE b END` | `if ( [c] ) then [a] else [b]` |
| `x IS NULL` | `isnull ( [x] )` |
| `x IS NOT NULL` | `isnotnull ( [x] )` |

**Date functions:**

| Snowflake SQL | ThoughtSpot formula | Note |
|---|---|---|
| `DATEDIFF('day', a, b)` | `diff_days ( [b] , [a] )` | **Args reversed** — ThoughtSpot (end, start) |
| `DATEDIFF('month', a, b)` | `diff_months ( [b] , [a] )` | Args reversed |
| `DATEDIFF('year', a, b)` | `diff_years ( [b] , [a] )` | Args reversed |
| `YEAR(col)` | `year ( [col] )` | |
| `MONTH(col)` | `month ( [col] )` | |
| `DAY(col)` | `day ( [col] )` | |
| `CURRENT_DATE()` | `today ()` | |
| `CURRENT_TIMESTAMP()` | `now ()` | |

**String functions:**

| Snowflake SQL | ThoughtSpot formula |
|---|---|
| `CONCAT(a, b)` | `concat ( [a] , [b] )` |
| `SUBSTR(x, start, len)` | `substr ( [x] , start , len )` |
| `LENGTH(x)` | `strlen ( [x] )` |
| `UPPER(x)` | `upper ( [x] )` |
| `LOWER(x)` | `lower ( [x] )` |

**Numeric functions:**

| Snowflake SQL | ThoughtSpot formula |
|---|---|
| `CAST(x AS INTEGER)` | `to_integer ( [x] )` |
| `CAST(x AS DOUBLE)` | `to_double ( [x] )` |
| `CAST(x AS VARCHAR)` | `to_string ( [x] )` |
| `ROUND(x, n)` | `round ( [x] , n )` |
| `FLOOR(x)` | `floor ( [x] )` |
| `CEIL(x)` | `ceil ( [x] )` |
| `ABS(x)` | `abs ( [x] )` |

---

## Translatable Window Function Patterns

`SUM/COUNT/AVG(x) OVER (PARTITION BY dims)` is **translatable** to ThoughtSpot LOD
functions. Do NOT omit these as untranslatable.

| Snowflake SQL pattern | ThoughtSpot formula | Notes |
|---|---|---|
| `SUM(x) OVER (PARTITION BY dim)` | `group_sum([table::x], [dim_table::dim])` | Use `[table::col]` references |
| `SUM(x) OVER (PARTITION BY dim1, dim2)` | `group_sum([table::x], [t1::dim1], [t2::dim2])` | Multiple partition dims |
| `DIV0(x, SUM(y) OVER (PARTITION BY dim))` | `safe_divide([table::x], group_sum([table::y], [dim_table::dim]))` | Contribution ratio |
| `COUNT(DISTINCT x) OVER (PARTITION BY dim)` | `group_aggregate(unique count([table::x]), {[dim_table::dim]}, query_filters())` | No group_count_distinct shorthand |

See [ts-snowflake-formula-translation.md](ts-snowflake-formula-translation.md) (LOD section) for full `group_aggregate` rules, `query_filters()` vs `{}` grouping, and the `sum(group_aggregate(...))` simplification.

---

## NON ADDITIVE BY → ThoughtSpot

The Snowflake semantic view `NON ADDITIVE BY (date_col ASC NULLS LAST) SUM(table.col)`
syntax translates to a ThoughtSpot formula using `last_value`:

```
last_value ( sum ( [fact_table::col] ) , query_groups ( ) , { [date_dim_table::date_col] } )
```

- `fact_table::col` = the measure column in the fact table
- `date_dim_table::date_col` = the date column from the **joined date dimension table**
  (NOT the fact table FK — look up which dimension table is in the `NON ADDITIVE BY` clause)
- The sort argument uses `{ [col] }` syntax — square brackets **inside** curly braces

Example — `NON ADDITIVE BY (DM_DATE_DIM.DATE_VALUE ASC NULLS LAST) SUM(DM_INVENTORY.FILLED_INVENTORY)`:
```
last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
```

Add this as a `formulas[]` entry with `column_type: MEASURE`.

**YAML representation — block scalar required:**

The `{ [col] }` syntax contains a `{` character which YAML interprets as a flow mapping
start. In ThoughtSpot TML YAML, use a `>-` block scalar for the `expr` value to avoid
this parsing issue:

```yaml
formulas:
- name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
  properties:
    column_type: MEASURE
```

`>-` strips the trailing newline (folded block scalar, chomping strip). The formula is
passed as a single-line string to ThoughtSpot. Do NOT quote the `expr:` value inline
(e.g. `expr: "last_value(...)"`) when it contains curly braces — YAML may still
misparse the `{` as a flow sequence start even inside double quotes in some parsers.

**Note for Snowflake/CoCo context:** `>-` block scalars are NOT allowed in Snowflake
Semantic View YAML (`CREATE SEMANTIC VIEW` DDL), but ARE valid in ThoughtSpot TML YAML.
Do not confuse the two contexts.

---

## Untranslatable vs pass-through (PT1)

**AUTHORITY:** `ts-snowflake-formula-translation.md` is the single mapping authority.
This file does not maintain a separate untranslatable list. Under PT1
(`ts-model-conversion-invariants.md`):

- Scalar SQL with no native TS mapping → `sql_*_op` pass-through (reliable)
- Aggregate/window SQL with no native mapping → `sql_*_aggregate_op` pass-through, ALWAYS flagged for review
- `TRY_CAST` has a native mapping (see formula translation reference)
- `RANK() OVER` has a native mapping via `rank()` (see formula translation reference)
- Omit-and-log is reserved for constructs PT1 explicitly excludes: CTEs/subqueries and
  genuinely un-representable structures (not just unfamiliar functions)

**Truly untranslatable (omit and log):**

| Pattern | Example | Reason |
|---|---|---|
| CTEs / subqueries | `(SELECT ... FROM ...)` | Cannot be embedded in a ThoughtSpot formula |
| Self-referential metrics | Metric A → Metric B → Metric A | Circular dependency; no formula representation |

---

## Facts Block → ThoughtSpot

Facts are **row-level computed expressions** — NOT aggregates. They define named
calculations at the grain of the underlying table, which metrics then aggregate.
A fact never contains `SUM`, `COUNT`, `AVG`, or any aggregate function; if it did,
the semantic view DDL would reject it.

**Parsing format:** identical to dimensions —
```
TABLE.FACT_NAME as EXPR [comment='...'] [with synonyms=(...)]
```

Where `EXPR` is either a physical column reference (`view_alias.COL`) or a SQL
expression over one or more columns (`DATEDIFF(month, view_alias.COL_A, CURRENT_DATE())`).

**ThoughtSpot mapping:** each public (non-PRIVATE) fact translates to a `formulas[]`
entry with a paired `columns[]` entry, following the same pattern as computed
dimensions:

- Numeric expressions (arithmetic, date-diff, cast-to-number) → `column_type: MEASURE`
- String expressions (concat, substr, upper) → `column_type: ATTRIBUTE`
- Date expressions (dateadd, date_trunc) → `column_type: ATTRIBUTE`

**Worked example:**

Semantic view fact:
```sql
PAYROLL_COMPANIES.COMPANY_AGE_MONTHS as DATEDIFF(month, payroll.PAYROLL_COMPANY_CREATED_AT, CURRENT_DATE())
```

ThoughtSpot TML:
```yaml
formulas:
- id: formula_Company Age Months
  name: "Company Age Months"
  expr: "diff_months ( today () , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )"
  properties:
    column_type: MEASURE

columns:
- name: "Company Age Months"
  formula_id: formula_Company Age Months
  properties:
    column_type: MEASURE
```

**Private facts:** a `PRIVATE` fact is hidden from Cortex Analyst but may be
referenced by a metric expression. Apply this rule:
- If the private fact is referenced by any metric → create with `index_type: DONT_INDEX`
- If the private fact is unreferenced by any metric → skip entirely (do not emit)

**Synonyms and description:** map identically to dimensions — first synonym becomes
the display `name`, remaining synonyms → `properties.synonyms`, and `comment='...'` →
`description`. See "Display Name, Synonyms, and Description Resolution" below.

---

## Identifier Resolution Algorithm

When translating metric expressions from Snowflake SQL to ThoughtSpot formulas,
every `table_alias.name` reference in the expression must be resolved to the
correct ThoughtSpot construct. This decision tree defines the resolution order.

**Resolution inputs:**

| Input | Source |
|---|---|
| Table columns | Physical columns from the ThoughtSpot Table TML exports |
| Facts map | `{FACT_NAME: {expr, table_alias, visibility}}` parsed from the `facts()` block |
| Metrics map | `{METRIC_NAME: {expr, agg, table_alias}}` parsed from the `metrics()` block |
| Relationships | `{REL_NAME: {from_table, from_col, to_table, to_col}}` parsed from `relationships()` |

**Decision tree — resolve `table_alias.name` in this order:**

```
1. Is `name` a physical column on the table identified by `table_alias`?
   YES → emit [TABLE_ID::col_name]  (standard column reference)
   NO  → step 2

2. Is `name` a FACT_NAME in the facts map where the fact's table_alias matches?
   YES → emit [formula_<id>]  (formula reference using the fact's `id` field)
         The reference uses the formula's `id` value (e.g. `formula_Tenure Months`),
         NOT the display name. `[Tenure Months]` fails during TML import;
         `[formula_Tenure Months]` succeeds. The `formula_` prefix + name is the
         `id:` value from the fact's `formulas[]` entry. No TABLE:: prefix.
         Example: fact id `formula_Tenure Months`
                  metric `AVG(employees.tenure_months)`
                  → `average ( [formula_Tenure Months] )`
   NO  → step 3

3. Is `name` a METRIC_NAME in the metrics map?
   YES → Double aggregation — see "Double Aggregation (Metric-on-Metric)" below.
         The referenced metric becomes an inner formula; the current metric wraps it.
   NO  → step 4

4. FAIL — the identifier cannot be resolved. Log it as an unresolved reference
   in the Formula Translation Log and emit a placeholder comment in the formula:
   /* UNRESOLVED: table_alias.name */
```

**Cross-table resolution:** when `table_alias` in the metric expression differs
from the metric's own table, the reference crosses a relationship. The column
reference still uses the standard `[TABLE_ID::col_name]` format — ThoughtSpot
resolves cross-table references through the model's join graph. No special syntax
is needed, but the join between the two tables must exist in `model_tables[].joins[]`.

---

## Double Aggregation (Metric-on-Metric)

When a metric's expression references another metric (resolved at step 3 of the
Identifier Resolution Algorithm), the outer metric aggregates an already-aggregated
value. ThoughtSpot requires the inner metric to be wrapped in `group_aggregate`
(or a `group_*` shorthand) to produce a per-group value that the outer metric
can then aggregate.

**Step 1 — Find the relationship:** identify the relationship connecting the inner
metric's table to the outer metric's table. The grouping key is the primary key
column on the parent (TO) side of that relationship.

**Step 2 — Build the formula:** use a `group_*` shorthand function when one exists
for the inner metric's aggregation:

| Inner metric aggregation | Shorthand function |
|---|---|
| `COUNT(col)` | `group_count` |
| `SUM(col)` | `group_sum` |
| `AVG(col)` | `group_average` |
| `COUNT(DISTINCT col)` | `group_unique_count` |
| `MIN(col)` | `group_min` |
| `MAX(col)` | `group_max` |

Shorthand syntax: `group_<agg>([inner_table::measure_col], [outer_table::group_key])`

When no shorthand exists (complex inner expression), use the full form:
```
group_aggregate(<inner_agg_formula>, {[outer_table::group_key]}, query_filters())
```

The filter argument is always `query_filters()` — this ensures user-applied runtime
filters propagate into the inner aggregation. Do NOT use `{}` (empty filter).

**Worked example:**

Semantic view metrics:
```sql
-- Inner: count of locations per company
PAYROLL_LOCATIONS.PAYROLL_LOCATION_ID as COUNT(payroll.NUMBER_OF_LOCATIONS)
-- Outer: average locations across companies (references inner metric)
PAYROLL_LOCATIONS.NUMBER_OF_LOCATIONS USING LOCATIONS_TO_COMPANIES as AVG(payroll.AVERAGE_LOCATIONS_PER_COMPANY)
```

Relationship: `LOCATIONS_TO_COMPANIES as PAYROLL_LOCATIONS(PAYROLL_COMPANY_ID) references PAYROLL_COMPANIES(PAYROLL_COMPANY_ID)`

Resolution:
- Outer metric `AVERAGE_LOCATIONS_PER_COMPANY` references `NUMBER_OF_LOCATIONS`
- `NUMBER_OF_LOCATIONS` resolves to a metric (step 3) → double aggregation
- Inner aggregation is `COUNT` → use `group_count` shorthand
- Grouping key = `PAYROLL_COMPANIES.PAYROLL_COMPANY_ID` (PK on the TO side)

ThoughtSpot formula:
```yaml
formulas:
- id: formula_Average Locations Per Company
  name: "Average Locations Per Company"
  expr: "average ( group_count ( [PAYROLL_LOCATIONS::PAYROLL_LOCATION_ID] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_ID] ) )"
  properties:
    column_type: MEASURE
```

**Window metrics referencing metrics (GAP-13):** when a cumulative or moving-window
metric references another metric, the same resolution applies — resolve the inner
metric reference, wrap it in the appropriate `group_*` function, then apply the
window function (`cumulative_sum`, `moving_average`, etc.) on top. The inner
`group_*` call is inlined as the argument to the window function rather than
being split into a separate formula.

**Report line requirement:** every double-aggregation formula must appear in the
Formula Translation Log with a 🔄 marker prefix to flag it for review. Double
aggregations are semantically fragile — the grouping key and relationship
direction must be verified against the semantic view's intent.

---

## Display Name, Synonyms, and Description Resolution

The Snowflake Semantic View DDL has three optional metadata clauses on each dimension
and metric. Map them to ThoughtSpot as follows:

| SV DDL | ThoughtSpot field |
|---|---|
| `with synonyms=('Display Name','Alt 1','Alt 2',...)` | First value → column `name`. Remaining values → `properties.synonyms` (with `properties.synonym_type: USER_DEFINED`). |
| `comment='...'` (on a dimension or metric) | column `description` |
| `comment='...'` (on a table in the `tables (...)` block) | TS Table TML `table.description` |
| Top-level `comment='...'` (after the metrics block) | Model TML `model.description` |

**Display-name precedence:**
1. **First synonym** in `with synonyms=(...)` if present
2. Else: title-cased DIM_NAME / METRIC_NAME (e.g., `STOCK_ON_HAND` → `Stock On Hand`)

**Synonyms placement — CRITICAL:** synonyms in TS Model and Table TML go under
**`properties.synonyms`**, NOT at the column root. Top-level `synonyms:` is silently
dropped on import. Always emit `properties.synonym_type: USER_DEFINED` alongside.

```yaml
# CORRECT
- name: "Customer Name"
  column_id: "DM_CUSTOMER::COMPANY_NAME"
  description: "Full company name of the customer"
  properties:
    column_type: ATTRIBUTE
    synonyms:
    - "Client"
    - "Account"
    - "Company Name"
    synonym_type: USER_DEFINED

# WRONG — synonyms at root are silently dropped
- name: "Customer Name"
  column_id: "DM_CUSTOMER::COMPANY_NAME"
  synonyms: ["Client", "Account"]   # ← lost on import
  properties:
    column_type: ATTRIBUTE
```

**Table-level `comment='...'` mapping:** when the SV `tables (...)` block has a comment
on a base table, push it onto the corresponding ThoughtSpot Table TML as
`table.description`. This is a separate import (Table TML, with `--no-create-new` to
update in place) — do this before importing the model.

**Per-column `comment='...'`** maps to model column `description`. ThoughtSpot model
TML allows `description` at column root.

---

## Snowflake Type → ThoughtSpot Type

Used in Scenario B when creating Table TML objects.

The `data_type` field in ThoughtSpot TML `db_column_properties` uses these values
(**not** SQL type names — the API rejects `BIGINT`, `INTEGER`, etc.):

| Snowflake type | ThoughtSpot `data_type` in TML |
|---|---|
| `TEXT`, `VARCHAR`, `CHAR`, `STRING` | `VARCHAR` |
| `NUMBER`, `DECIMAL`, `INT`, `INTEGER`, `BIGINT` (scale=0) | `INT64` |
| `FLOAT`, `DOUBLE`, `REAL`, `NUMBER` (scale>0) | `DOUBLE` |
| `BOOLEAN` | `BOOL`  *(Snowflake connections — `ts tables create` rejects `BOOLEAN`)* |
| `DATE` | `DATE` |
| `DATETIME`, `TIMESTAMP_NTZ`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ` | `DATE_TIME` |
| `VARIANT`, `OBJECT`, `ARRAY` | `VARCHAR` *(flag for review)* |

**Important:** Use `INT64` not `BIGINT` — ThoughtSpot will return
`DataType BIGINT does not match CDW DataType` if you use SQL type names.
When in doubt about NUMBER scale, use `INT64`; ThoughtSpot validates against
the actual CDW column type and will report a mismatch if wrong.

> **Snowflake connection note:** `ts tables create` validates `data_type` against the
> live CDW column type. For Snowflake `BOOLEAN` columns, use `BOOL` — not `BOOLEAN`,
> `INT64`, or `VARCHAR`. Any other value returns:
> `Data type BOOLEAN is not valid for column having name {col} and db_column_name {col}.`

---

## ThoughtSpot TML Construction

For Table TML and Model TML field references, templates, self-validation checklists,
and common import errors, see the platform-agnostic schema references:

- **[../../schemas/thoughtspot-table-tml.md](../../schemas/thoughtspot-table-tml.md)** — Table TML structure, connection reference, data types, GUID patterns, import errors
- **[../../schemas/thoughtspot-model-tml.md](../../schemas/thoughtspot-model-tml.md)** — Model TML structure, join scenarios, formula visibility, self-validation checklist
- **[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md)** — ThoughtSpot formula syntax, function categories, LOD/window/semi-additive patterns, YAML encoding

**Snowflake / CoCo-specific notes:**

- Do NOT search for a connection GUID — `TS_SEARCH_MODELS` only finds data objects, not connections. Use the connection name provided by the user directly.
- **GUID after import (CoCo workflow):** Do NOT search by name after import. `TS_SEARCH_MODELS` returns tables from ALL connections, making it impossible to identify newly-created tables by name. Use the `OBJECT_AGG` extraction pattern from `RESULT_SCAN` — see the CoCo SKILL.md Step 4B.

---

## Fact Table Identification

The fact table is the table that never appears on the `TO` side of any relationship.

Algorithm:
1. Collect all `TO_TABLE` values from the relationships block.
2. The table alias(es) not in that set are the fact-side tables.
3. If multiple fact-side tables exist (bridge/junction pattern), include each without
   a `referencing_join` and note that cross-table joins must be defined manually.

---

## Join Direction

Joins flow FROM the table with the foreign key TO the table with the primary key.
This matches the semantic view relationship direction:
`REL_NAME as FROM_TABLE(FK) references TO_TABLE(PK)`.

For Scenario A:
- `referencing_join` is a field inside a `joins[]` entry on the FROM/FK table's
  `model_tables` entry. It names the join defined in the FROM table's ThoughtSpot
  Table TML (`joins_with[].name` where `destination.name` = TO table name).

For Scenario B / inline joins:
- The `joins[]` array lives on the FROM table's `model_tables` entry.
- Each entry has `with`, `on`, `type`, `cardinality` (no `referencing_join`).
- `with` points to the TO table's `id`.

---

## Column ID Construction

The `column_id` format is: `{TABLE_NAME}::{col_name}`

- `TABLE_NAME` = the `name:` from the corresponding `model_tables[]` entry (exact case — copy verbatim)
- `col_name` = the column name from the **ThoughtSpot Table TML** — export and read the Table TML; do not assume it matches the semantic view left-hand side

**Do not use** the semantic view dimension aliases (left side of `TABLE_REF.VIEW_COL`) as the `col_name`. Some Snowflake views rename columns internally.

Example:
```
Semantic view dimension:    SUPERHERO.SUPERHERO_NAME as superhero.SUPERHERO_NAME
ThoughtSpot Table TML col:  SUPERHERO_NAME
model_tables name:          SUPERHERO
Correct column_id:          SUPERHERO::SUPERHERO_NAME
```
