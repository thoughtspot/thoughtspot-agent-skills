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
        ...
    )
    relationships (
        REL_NAME as FROM_TABLE(FROM_COL) references TO_TABLE(TO_COL),
        ...
    )
    dimensions (
        -- All dimensions at view level (NOT nested per-table)
        TABLE_REF.VIEW_COL as view_alias.DIM_NAME [comment='...'],
        ...
    )
    metrics (
        -- Simple: TABLE_REF.VIEW_COL as AGG(view_alias.METRIC_NAME)
        TABLE_REF.VIEW_COL as SUM(view_alias.METRIC_NAME) [comment='...'],
        -- Complex expressions appear as the right-hand side
        ...
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
| `CASE WHEN c THEN a ELSE b END` | `if [c] then [a] else [b]` |
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

## Untranslatable SQL Patterns

**Omit and log — do not include these as formula columns.**

| Pattern | Example | Reason |
|---|---|---|
| Complex window functions | `RANK() OVER (...)`, `ROW_NUMBER() OVER (...)`, `LAG(x, n)`, `LEAD(x, n)` | No ThoughtSpot equivalent |
| Running/moving window | `SUM(x) OVER (... ROWS BETWEEN ...)` | Use `cumulative_*` / `moving_*` only if exact match — otherwise omit |
| CTEs / subqueries | `(SELECT ... FROM ...)` | Cannot be embedded in a formula |
| JSON/variant access | `col:key::type`, `GET_PATH(col, 'k')` | Snowflake-specific |
| `TRY_CAST`, `PARSE_JSON` | — | Snowflake-specific |
| `LISTAGG`, `ARRAY_AGG` | — | No ThoughtSpot equivalent |
| Unknown functions | `HAVERSINE(...)` | Not in ThoughtSpot |

**Note:** `SUM/COUNT/AVG(x) OVER (PARTITION BY dims)` is NOT in this table — it IS
translatable. See the "Translatable Window Function Patterns" section above.

---

## Display Name Resolution

For each dimension/metric in the semantic view DDL:

The `comment='...'` value on the right-hand side is the intended display name.
If no comment is present, convert the DIM_NAME to title case (e.g., `trans_id` → `Trans Id`).

ThoughtSpot model column format:
```yaml
- name: "{display_name}"              # From comment or title-cased DIM_NAME
  column_id: {TABLE_ID}::{col_name}  # TABLE_ID = id in model_tables, col_name from ThoughtSpot Table TML
  properties:
    column_type: ATTRIBUTE
```

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
| `BOOLEAN` | `BOOLEAN` |
| `DATE` | `DATE` |
| `DATETIME`, `TIMESTAMP_NTZ`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ` | `DATE_TIME` |
| `VARIANT`, `OBJECT`, `ARRAY` | `VARCHAR` *(flag for review)* |

**Important:** Use `INT64` not `BIGINT` — ThoughtSpot will return
`DataType BIGINT does not match CDW DataType` if you use SQL type names.
When in doubt about NUMBER scale, use `INT64`; ThoughtSpot validates against
the actual CDW column type and will report a mismatch if wrong.

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
- `referencing_join` on a dim table entry names the join defined in the FROM table's
  ThoughtSpot Table TML (`joins_with[].name` where `destination.name` = TO table name).

For Scenario B / inline joins:
- The `joins[]` array lives on the FROM table's `model_tables` entry.
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
