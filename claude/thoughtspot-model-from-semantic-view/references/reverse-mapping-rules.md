# Reverse Mapping Rules Reference

Snowflake Semantic View DDL → ThoughtSpot Model TML. Consult during Steps 4–9.

---

## Semantic View DDL Format

`GET_DDL('SEMANTIC_VIEW', 'db.schema.view')` returns a SQL DDL string with this
general structure:

```sql
create or replace semantic view {DATABASE}.{SCHEMA}.{VIEW_NAME}
  tables (
    {TABLE_ALIAS} base table {DATABASE}.{SCHEMA}.{PHYSICAL_TABLE}
      primary key ( {PK_COL} )
      dimensions (
        {DIM_NAME} aliases = ( {alias1}, {alias2} ) data_type = {TYPE}
          expr = {TABLE_ALIAS}.{COLUMN},
        ...
      )
      time_dimensions (
        {TD_NAME} aliases = ( {alias} ) data_type = {DATE|TIMESTAMP_NTZ}
          expr = {TABLE_ALIAS}.{COLUMN},
        ...
      )
      metrics (
        {METRIC_NAME} aliases = ( {alias} )
          expr = {SQL_EXPRESSION},
        ...
      ),
    ...
  )
  relationships (
    {REL_NAME}
      from {FROM_TABLE} key ( {FROM_COL} )
      to   {TO_TABLE}   key ( {TO_COL} ),
    ...
  )
  metrics (
    {METRIC_NAME} aliases = ( {alias} )
      expr = {SQL_EXPRESSION},
    ...
  )
  extension = '{...cortex_analyst_context_json...}';
```

**Notes on DDL parsing:**
- `time_dimensions` may or may not appear as a separate block. Columns with `data_type = DATE` or `data_type = TIMESTAMP_NTZ` are time dimensions regardless of which block they appear in.
- `metrics` can appear both nested under a table AND at the top level. Collect both.
- `aliases = ()` may be empty. If empty, the dimension/metric name (snake_case) is used as the display name.
- The `extension` JSON contains Cortex Analyst configuration. Do not map it to ThoughtSpot.
- Relationship key columns may be composite: `key ( COL1, COL2 )`. Both columns are included in the join condition.

---

## Column Type Classification

Apply this decision tree to each dimension, time_dimension, and metric in the DDL:

```
Is it in the metrics block (or has an expr that is an aggregate function)?
  YES → Is the expr a simple AGG(table.col) pattern?
          YES → MEASURE column (aggregation embedded in column_type)
          NO  → formula column (translate SQL → ThoughtSpot formula)
  NO  → Is data_type DATE or TIMESTAMP*?
          YES → ATTRIBUTE column (ThoughtSpot infers date/datetime type from the physical column)
          NO  → ATTRIBUTE column
```

---

## Aggregation Mapping

For simple metric EXPR patterns (`AGG(table.col)`):

| Snowflake SQL aggregate | ThoughtSpot `aggregation` | Column type |
|---|---|---|
| `SUM(table.col)` | `SUM` | MEASURE |
| `COUNT(table.col)` | `COUNT` | MEASURE |
| `COUNT(DISTINCT table.col)` | `COUNT_DISTINCT` | MEASURE |
| `AVG(table.col)` | `AVERAGE` | MEASURE |
| `MIN(table.col)` | `MIN` | MEASURE |
| `MAX(table.col)` | `MAX` | MEASURE |

When the aggregation is COUNT_DISTINCT, prefer a formula column:
```
unique count ( [TABLE::COL] )
```
over a MEASURE with `COUNT_DISTINCT`, as the formula syntax is more reliable across
ThoughtSpot versions.

---

## SQL → ThoughtSpot Formula Translation

Apply these rules when a metric EXPR is **not** a simple `AGG(table.col)`.

**Column reference conversion:**
```
SQL:            TABLE_ALIAS.COLUMN_NAME
ThoughtSpot:    [TABLE_ALIAS::COLUMN_NAME]
```
The `TABLE_ALIAS` is the alias used in the semantic view table entry (matches the
`id` field in `model_tables`).

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
| `CASE WHEN c1 THEN a WHEN c2 THEN b ELSE c END` | `if [c1] then [a] else if [c2] then [b] else [c]` |
| `x IS NULL` | `isnull ( [x] )` |
| `x IS NOT NULL` | `isnotnull ( [x] )` |

**Date functions:**

| Snowflake SQL | ThoughtSpot formula | Note |
|---|---|---|
| `DATEDIFF('day', a, b)` | `diff_days ( [b] , [a] )` | **Args are reversed** — ThoughtSpot takes (end, start) |
| `DATEDIFF('month', a, b)` | `diff_months ( [b] , [a] )` | Args reversed |
| `DATEDIFF('year', a, b)` | `diff_years ( [b] , [a] )` | Args reversed |
| `YEAR(col)` | `year ( [col] )` | |
| `MONTH(col)` | `month ( [col] )` | |
| `DAY(col)` | `day ( [col] )` | |
| `HOUR(col)` | `hour ( [col] )` | |
| `CURRENT_DATE()` | `today ()` | |
| `CURRENT_TIMESTAMP()` | `now ()` | |

**String functions:**

| Snowflake SQL | ThoughtSpot formula |
|---|---|
| `CONCAT(a, b)` | `concat ( [a] , [b] )` |
| `CONCAT(a, ' ', b)` | `concat ( [a] , ' ' , [b] )` *(N args)* |
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
| `POWER(x, n)` | `power ( [x] , n )` |

---

## Untranslatable SQL Patterns

**Do not include these as formula columns.** Omit and log in the report.

| Pattern | Example | Reason |
|---|---|---|
| Window functions | `AVG(x) OVER (PARTITION BY ...)` | ThoughtSpot has no equivalent |
| CTEs / subqueries | `(SELECT ... FROM ...)` | Cannot be embedded in a ThoughtSpot formula |
| JSON/variant access | `col:key::type`, `GET_PATH(col, 'k')` | Snowflake-specific — no ThoughtSpot equivalent |
| `TRY_CAST`, `PARSE_JSON` | `TRY_CAST(x AS INTEGER)` | Snowflake-specific |
| `LISTAGG`, `ARRAY_AGG` | `LISTAGG(x, ',')` | No ThoughtSpot equivalent |
| Arbitrary SQL functions not in the table above | `HAVERSINE(...)`, `OBJECT_CONSTRUCT(...)` | Unknown to ThoughtSpot |

Log entry format (for report in Step 12):
```
| {column_name} | `{sql_expr}` | ⚠ {reason} | OMITTED |
```

---

## Display Name and Synonym Resolution

For each dimension/metric in the semantic view DDL:

```
ALIASES = ( {alias1}, {alias2}, ... )
```

1. **If aliases is empty or absent:** use the DDL name (snake_case) as the
   ThoughtSpot column display name.
2. **If aliases has one or more entries:** use the first alias as the display name.
   Additional aliases become ThoughtSpot `synonyms[]` if supported.
3. **If the DDL name matches a human-readable format** (e.g. `customer_name` with
   no alias): convert to title case as the display name (`Customer Name`), unless
   an alias is present that differs.

ThoughtSpot model column format:
```yaml
- name: "{display_name}"              # First alias, or title-cased DDL name
  column_id: {TABLE_ALIAS}::{COLUMN}  # Physical column extracted from expr
  properties:
    column_type: ATTRIBUTE
```

---

## Snowflake Type → ThoughtSpot Type

Used in Scenario B when creating Table TML objects for views.

| Snowflake type (from SHOW COLUMNS) | ThoughtSpot `db_column_type` |
|---|---|
| `TEXT`, `VARCHAR`, `CHAR`, `STRING` | `VARCHAR` |
| `NUMBER`, `DECIMAL`, `NUMERIC`, `INT`, `INTEGER`, `BIGINT`, `SMALLINT` | `BIGINT` or `DOUBLE` |
| `FLOAT`, `DOUBLE`, `REAL` | `DOUBLE` |
| `BOOLEAN` | `BOOLEAN` |
| `DATE` | `DATE` |
| `DATETIME`, `TIMESTAMP_NTZ`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ` | `DATETIME` |
| `VARIANT`, `OBJECT`, `ARRAY` | `VARCHAR` *(flag for review)* |

---

## Model TML Templates

### Scenario A — On underlying tables (referencing_join)

```yaml
model:
  name: "{model_name}"
  model_tables:
  - id: {FACT_TABLE_ALIAS}
    name: {FACT_PHYSICAL_TABLE}
    fqn: {fact_table_guid}
  - id: {DIM_TABLE_ALIAS}
    name: {DIM_PHYSICAL_TABLE}
    fqn: {dim_table_guid}
    referencing_join: {join_name_from_table_tml}
  columns:
  - name: "{display_name}"
    column_id: {TABLE_ALIAS}::{PHYSICAL_COLUMN}
    properties:
      column_type: ATTRIBUTE
  - name: "{display_name}"
    column_id: {TABLE_ALIAS}::{PHYSICAL_COLUMN}
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - name: "{display_name}"
    expr: "{thoughtspot_formula}"
    properties:
      column_type: MEASURE
```

### Scenario B — On views (inline joins)

```yaml
model:
  name: "{model_name}"
  model_tables:
  - id: {FACT_TABLE_ALIAS}
    name: {VIEW_OR_TABLE_NAME}
    fqn: {guid_from_import}
    joins:
    - name: {join_name}
      on: "[{FACT}::{FROM_COL}] = [{DIM}::{TO_COL}]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - id: {DIM_TABLE_ALIAS}
    name: {VIEW_OR_TABLE_NAME}
    fqn: {guid_from_import}
  columns:
  # ... same as Scenario A ...
  formulas:
  # ... same as Scenario A ...
```

---

## Fact Table Identification

The fact table is the table that never appears on the `TO` side of any relationship.

Algorithm:
1. Build a set of all `TO` table aliases from the relationships block.
2. The table(s) not in that set are fact-side tables.
3. If there are multiple fact-side tables (no relationships between them), include
   each without a `referencing_join` and note that the user may need to define
   cross-table joins manually.

---

## Join Direction

In ThoughtSpot, joins are defined FROM the table that has the foreign key TO the
table that has the primary key. This matches the semantic view relationship direction:
`FROM {fact_table} KEY {fk} TO {dim_table} KEY {pk}`.

The `referencing_join` on a model_table entry points to the join in the ThoughtSpot
Table TML of the **FROM** (fact/left) table.

To locate the join name:
1. Export TML for the FROM table: `ts tml export {from_table_guid}`
2. Parse the `joins` section in the returned `edoc`
3. Find the join where `destination` matches the TO table name
4. Use that join's `name` as `referencing_join` in the model

Example Table TML join section:
```yaml
joins:
- name: dm_orders_to_dm_customer
  destination: DM_CUSTOMER
  on: "[DM_ORDERS::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]"
  type: LEFT_OUTER
  cardinality: MANY_TO_ONE
```
→ `referencing_join: dm_orders_to_dm_customer` on the DM_CUSTOMER model_table entry.

---

## Column ID Extraction from EXPR

The physical column name is embedded in the EXPR field:
```
expr = DM_CUSTOMER.CUSTOMER_NAME
```
Strip the `{TABLE_ALIAS}.` prefix to get `CUSTOMER_NAME`. This is the column portion
of `column_id: DM_CUSTOMER::CUSTOMER_NAME`.

For complex expressions (multi-column, functions), the EXPR does not resolve to a
single column → this is a formula column (see Step 9).
