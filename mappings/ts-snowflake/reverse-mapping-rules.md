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

**Critical:** Semantic view dimensions reference columns in the Snowflake view layer
(e.g., `BIRD.FINANCIAL_SV.TRANS`), which renames physical columns from the underlying
table (e.g., `BIRD.financial.trans`). ThoughtSpot table objects are connected to the
**physical tables**, so `column_id` values must use the **physical column names**.

Example:
```
Semantic view:       TRANS.TRANS_ACCOUNT_ID (column in BIRD.FINANCIAL_SV.TRANS view)
Physical table:      BIRD.financial.trans.account_id
ThoughtSpot column:  account_id
Correct column_id:   trans::account_id   ← NOT trans::TRANS_ACCOUNT_ID
```

**How to get the correct physical column names:**

1. **Always run `GET_DDL` on each view** before assuming column names match the
   semantic view references. The semantic view DDL frequently uses aliases that
   differ from the view's actual column names:
   ```sql
   SELECT GET_DDL('VIEW', 'DB.SCHEMA.VIEW_NAME');
   ```
   The view DDL shows the exact column names that ThoughtSpot will see.
   Cross-check: if `information_schema.columns` shows `A2` but the semantic view
   says `CLIENT_DISTRICT_NAME`, the physical column is `A2`.

2. For Scenario A (existing ThoughtSpot table objects), export Table TMLs instead:
   ```bash
   ts tml export {guid1} {guid2} ... --profile {profile}
   ```
   The TML `table.columns[].name` (or `db_column_name`) values are authoritative.

3. Build a mapping per table: `semantic_view_col_name → physical_col_name`
   - Try an exact case-insensitive match first
   - If no match, strip the table alias prefix and retry
     (e.g., `TRANS_ACCOUNT_ID` → strip `TRANS_` → `ACCOUNT_ID`)
   - If still no match, the view DDL from step 1 is the final answer

4. Use the physical column name as `column_id` in the model TML.

**NEVER use semantic view alias names directly as column_id values.**

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
- `time_dimensions` → `ATTRIBUTE` (ThoughtSpot handles date type from the physical column)
- `metrics` → `MEASURE` (use `default_aggregation` as the aggregation type)

The CA extension `name` values are **lowercase aliases** of the semantic view dimension names.
They confirm which columns are metrics vs attributes, but do NOT give you the physical column names.

---

## Column Type Classification

Apply this decision tree:

```
Is the column listed in the CA extension metrics block (or has an AGG(…) expression)?
  YES → Is the expr a simple AGG(view.col) pattern?
          YES → MEASURE column with aggregation from AGG function
          NO  → formula column (translate SQL → ThoughtSpot formula)
  NO  → Is it in time_dimensions (or data type DATE/TIMESTAMP)?
          YES → ATTRIBUTE column (ThoughtSpot infers date type from physical column)
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

When the aggregation is COUNT_DISTINCT, prefer a formula column:
```
unique count ( [TABLE_ID::physical_col] )
```
over a MEASURE with `COUNT_DISTINCT`, as the formula syntax is more reliable.

---

## SQL → ThoughtSpot Formula Translation

> See **[formula-translation.md](formula-translation.md)** for the full bidirectional
> translation reference (Snowflake SQL ↔ ThoughtSpot formulas), including window functions,
> LOD expressions, and semi-additive patterns.

Apply these rules when a metric EXPR is **not** a simple `AGG(view.col)`.
The quick-reference tables below cover the most common cases; consult formula-translation.md
for edge cases and complex expressions.

**Column reference conversion:**
```
SQL:            TABLE_ALIAS.VIEW_COLUMN_NAME
ThoughtSpot:    [TABLE_ID::physical_column_name]
```
`TABLE_ID` is the `id` value from the model_tables entry.
`physical_column_name` is the column name from the ThoughtSpot table TML (not the view alias).

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

## Untranslatable SQL Patterns

**Omit and log — do not include these as formula columns.**

| Pattern | Example | Reason |
|---|---|---|
| Window functions | `AVG(x) OVER (PARTITION BY ...)` | No ThoughtSpot equivalent |
| CTEs / subqueries | `(SELECT ... FROM ...)` | Cannot be embedded in a formula |
| JSON/variant access | `col:key::type`, `GET_PATH(col, 'k')` | Snowflake-specific |
| `TRY_CAST`, `PARSE_JSON` | — | Snowflake-specific |
| `LISTAGG`, `ARRAY_AGG` | — | No ThoughtSpot equivalent |
| Unknown functions | `HAVERSINE(...)` | Not in ThoughtSpot |

---

## Display Name Resolution

For each dimension/metric in the semantic view DDL:

The `comment='...'` value on the right-hand side is the intended display name.
If no comment is present, convert the DIM_NAME to title case (e.g., `trans_id` → `Trans Id`).

ThoughtSpot model column format:
```yaml
- name: "{display_name}"              # From comment or title-cased DIM_NAME
  column_id: {TABLE_ID}::{physical_col}  # TABLE_ID = id in model_tables, physical_col from TS table TML
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
| `DATETIME`, `TIMESTAMP_NTZ`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ` | `DATETIME` |
| `VARIANT`, `OBJECT`, `ARRAY` | `VARCHAR` *(flag for review)* |

**Important:** Use `INT64` not `BIGINT` — ThoughtSpot will return
`DataType BIGINT does not match CDW DataType` if you use SQL type names.
When in doubt about NUMBER scale, use `INT64`; ThoughtSpot validates against
the actual CDW column type and will report a mismatch if wrong.

---

## Model TML Templates

### Table TML creation notes (Scenario B)

**Use connection `fqn` (GUID), not `name`:**
```yaml
connection:
  fqn: "f0bc76d5-077d-432b-8000-87a046c06bef"   # preferred — more reliable
  # name: "apj"                                   # avoid — can cause JDBC errors
```
Get the connection GUID first with `ts connections list --profile {profile}`.

**Transient JDBC errors:** ThoughtSpot occasionally returns
`CONNECTION_METADATA_FETCH_ERROR / JDBC driver encountered a communication error`
during table TML import. This is transient — retry up to 3 times with a 5-second
delay before treating it as a real failure.

**GUID after import:** The `ts tml import` response often returns an empty `object`
list even on success. Always follow up with a metadata search to confirm the GUID:
```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --name '%{table_name}%' --profile {profile}
```

---

### Core rules that apply to ALL scenarios

1. **`id` values must be lowercase** and must be unique across all `model_tables` entries.
   The `id` is the alias you assign; it does not need to match anything in ThoughtSpot,
   but it must be consistent — `with` and `on` clause references both use `id`.

2. **`name` values must be unique** across all `model_tables` entries. `name` must match
   the ThoughtSpot table object's name exactly (case-sensitive, usually lowercase).

3. **`column_id` must use the ThoughtSpot physical column name**, not the semantic view
   alias. Format: `{TABLE_ID}::{physical_column_name}`.

4. **`with` in an inline join** must equal the `id` of the target table entry.

5. **`on` clause references** use `id` values: `[{from_id}::{physical_col}] = [{to_id}::{physical_col}]`.

---

### Scenario A — On underlying tables (pre-defined joins exist)

Use when the ThoughtSpot Table objects already have `joins_with` entries linking them together.

```yaml
model:
  name: "{model_name}"
  model_tables:
  - id: fact_table          # lowercase, matches ThoughtSpot table name
    name: fact_table        # exact ThoughtSpot table object name
    fqn: "{fact_guid}"
  - id: dim_table           # lowercase, unique alias
    name: dim_table         # exact ThoughtSpot table object name
    fqn: "{dim_guid}"
    referencing_join: "{join_name_from_table_tml}"  # from Step 7
  columns:
  - name: "{display_name}"
    column_id: fact_table::{physical_col}  # physical col from ThoughtSpot table TML
    properties:
      column_type: ATTRIBUTE
  - name: "{display_name}"
    column_id: fact_table::{physical_col}
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - name: "{display_name}"
    expr: "{thoughtspot_formula}"
    properties:
      column_type: MEASURE
```

To find `referencing_join`: export TML for the FROM table → parse `joins_with[]` →
find entry where `destination.name` matches the TO table → use `name` from that entry.

---

### Scenario B — Inline joins (no pre-defined table joins, or new table objects)

Use when ThoughtSpot Table objects have no `joins_with` entries, OR when creating new
Table objects (views/tables not yet in ThoughtSpot). The `joins` array lives on the
**source (FROM) table** entry — never on the target.

```yaml
model:
  name: "{model_name}"
  model_tables:
  - id: from_table          # lowercase, unique
    name: from_table        # ThoughtSpot table object name
    fqn: "{from_guid}"
    joins:
    - name: join_name
      with: to_table        # MUST match the `id` of the target entry below
      on: "[from_table::{fk_col}] = [to_table::{pk_col}]"   # uses id values, physical cols
      type: INNER
      cardinality: MANY_TO_ONE
  - id: to_table            # the id referenced in `with` and `on` above
    name: to_table          # ThoughtSpot table object name
    fqn: "{to_guid}"
  columns:
  # ... same as Scenario A ...
  formulas:
  # ... same as Scenario A ...
```

**Inline join checklist:**
- `with: to_table` — target `id`, lowercase, not the physical table name
- `on: "[from_table::fk] = [to_table::pk]"` — both references are `id` values
- Target table entry has its own `model_tables` row with matching `id`
- No `referencing_join` field when using inline joins

---

### Dual-Role Tables

When a **single physical ThoughtSpot table** serves as multiple logical entities in the
semantic view (e.g., `colour` is EYE_COLOUR, HAIR_COLOUR, and SKIN_COLOUR), include it
**only once** in `model_tables`.

Pattern:
```yaml
model_tables:
- id: superhero
  name: superhero
  fqn: "{guid}"
  joins:
  - name: sh_to_eye_colour
    with: colour            # the ONE colour entry
    on: "[superhero::eye_colour_id] = [colour::id]"
    type: INNER
    cardinality: MANY_TO_ONE
  - name: sh_to_hair_colour
    with: colour            # same target
    on: "[superhero::hair_colour_id] = [colour::id]"
    type: INNER
    cardinality: MANY_TO_ONE
  - name: sh_to_skin_colour
    with: colour            # same target
    on: "[superhero::skin_colour_id] = [colour::id]"
    type: INNER
    cardinality: MANY_TO_ONE
- id: colour                # ONE entry, not three
  name: colour
  fqn: "{guid}"
```

**What this means for columns:** You can only include columns from one of the three
roles (typically the most important). Log the omission in the summary report:
`colour.HAIR_COLOUR and colour.SKIN_COLOUR omitted — same physical table as EYE_COLOUR`.

**Detecting dual-role tables:** When two semantic view table aliases resolve to the
same ThoughtSpot GUID, you have a dual-role table. The `name` field would collide —
ThoughtSpot rejects models with duplicate `name` values with:
`"Multiple tables have same alias {name}"`.

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

The `column_id` format is: `{TABLE_ID}::{physical_column_name}`

- `TABLE_ID` = the `id` from the corresponding `model_tables` entry (lowercase)
- `physical_column_name` = the column name from the **ThoughtSpot table TML** (Step 6A/7)

The ThoughtSpot table TML column `name` (or `db_column_name`) is the authoritative source.
**Do not use** the semantic view dimension aliases (left side of `TABLE_REF.VIEW_COL`).

Example:
```
Semantic view dimension:    TRANS.TRANS_ACCOUNT_ID as trans.TRANS_ACCOUNT_ID
Semantic view left side:    TRANS.TRANS_ACCOUNT_ID   ← column in FINANCIAL_SV.TRANS view
ThoughtSpot table TML col:  account_id               ← column in financial.trans table
Correct column_id:          trans::account_id
```
