# Mapping Rules Reference

ThoughtSpot → Snowflake Semantic View conversion tables. Consult during Steps 7–9.

---

## Column Type Classification

Apply this decision tree to every column:

```
Is formula_id set?
  YES → metrics (if translatable) or OMIT (if untranslatable — see Step 9)
  NO  → Is column_type MEASURE?
          YES → metrics
          NO  → Is db_column_type or column name a date/timestamp? (see Data Types below)
                  YES → time_dimensions
                  NO  → dimensions
```

---

## Aggregation Functions

Used in `expr` for `metrics` entries only. There is no `default_aggregation` field
in the Snowflake Semantic View schema — the aggregation is embedded in the `expr`.

| ThoughtSpot `aggregation` | Snowflake `expr` wrapper |
|---|---|
| `SUM` | `SUM(expr)` |
| `COUNT` | `COUNT(expr)` |
| `COUNT_DISTINCT` | `COUNT(DISTINCT expr)` |
| `AVG` / `AVERAGE` | `AVG(expr)` |
| `MIN` | `MIN(expr)` |
| `MAX` | `MAX(expr)` |
| `STD_DEVIATION` | `STDDEV(expr)` *(flag for review — no direct match)* |
| `VARIANCE` | `VARIANCE(expr)` *(flag for review — no direct match)* |
| *(not set on MEASURE)* | `SUM(expr)` *(default)* |

---

## Data Types

Check `db_column_properties.data_type` first (Table TML — most reliable), then fall back
to `db_column_type` (Worksheet TML).

| Source field value | Snowflake `data_type` | date/time? |
|---|---|---|
| `VARCHAR`, `CHAR`, `TEXT`, `STRING`, `NVARCHAR`, `CLOB` | `TEXT` | no |
| `INT`, `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT`, `INT64` | `NUMBER` | no |
| `FLOAT`, `DOUBLE`, `DECIMAL`, `NUMERIC`, `REAL`, `NUMBER` | `NUMBER` | no |
| `BOOLEAN`, `BOOL` | `BOOLEAN` | no |
| `DATE` | `DATE` | **yes → time_dimension** |
| `DATETIME`, `DATE_TIME` | `TIMESTAMP` | **yes → time_dimension** |
| `TIMESTAMP`, `TIMESTAMP_NTZ`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ` | `TIMESTAMP` | **yes → time_dimension** |
| *(unknown or absent)* | `TEXT` *(default — flag for review)* | no |

**Name-based date heuristics** (use only when `db_column_type` is unavailable):

Column name ends with or equals: `_date`, `_at`, `_time`, `_ts`, `_datetime`,
`date`, `time`, `timestamp` → treat as `time_dimension`.

---

## Name Generation Rules

When generating Snowflake field names from ThoughtSpot display names:

1. Convert to lowercase.
2. Replace any sequence of non-alphanumeric characters (`spaces`, `/`, `-`, `(`, `)`,
   `#`, `%`, `@`, etc.) with a single underscore `_`.
3. Strip leading and trailing underscores.
4. If the result is empty or starts with a digit, prepend `field_`.
5. Truncate to 255 characters if needed.
6. **Check for semantic loss:** if the original name started with `#` or a symbol
   that carried meaning (e.g. `# of Products` → `of_products`), flag at the checkpoint
   and suggest a more meaningful name (e.g. `product_count`).

| ThoughtSpot display name | Generated Snowflake name | Flag? |
|---|---|---|
| `Revenue` | `revenue` | no |
| `Sale Date` | `sale_date` | no |
| `# of Products` | `of_products` | **yes** — suggest `product_count` |
| `YoY Growth (%)` | `yoy_growth` | no |
| `Customer ID (CRM)` | `customer_id_crm` | no |
| `2024 Sales` | `field_2024_sales` | no *(digit prefix fixed)* |

---

## Snowflake Field Entry Templates

Fields are **nested under their owning table** in the output YAML, not at the top level.
Do not include `sample_values` or `default_aggregation` — these are not supported.

**Table entry (with primary_key — required when table is the right side of a relationship):**
```yaml
- name: {TABLE_ALIAS}
  base_table:
    database: {DATABASE}
    schema: {SCHEMA_OR_QUOTED}          # e.g. PUBLIC  or  '"superhero"'
    table: {PHYSICAL_TABLE_OR_QUOTED}   # e.g. FACT_SALES  or  '"colour"'
  primary_key:
    columns:
    - {PK_COLUMN_BARE}                  # e.g. ORDER_ID  or  id  — NEVER '"id"'
  dimensions:
  - ...
  time_dimensions:
  - ...
  metrics:
  - ...
```

**`primary_key.columns` must always be bare unquoted identifiers.** Cortex Analyst
rejects the `'"col"'` quoting format with a 400 error, even when the physical column
is case-sensitive lowercase. Use the plain column name (e.g. `id`, `alignment_id`)
or its uppercase equivalent. The Snowflake Semantic View framework resolves these
case-insensitively, so `id` and `ID` both match a physical `"id"` column.

**Table entry (no primary_key — for the "left" / fact table that is never a join target):**
```yaml
- name: {TABLE_ALIAS}
  base_table:
    database: {DATABASE}
    schema: {SCHEMA_OR_QUOTED}
    table: {PHYSICAL_TABLE_OR_QUOTED}
  dimensions:
  - ...
  time_dimensions:
  - ...
  metrics:
  - ...
```

**Case-sensitive identifier quoting:**
- `SHOW SCHEMAS` / `SHOW TABLES` / `SHOW COLUMNS` returning lowercase → identifier is case-sensitive
- Encode as `'"value"'` in YAML (single-quoted YAML string containing Snowflake double-quoted identifier)
- Case-insensitive (UPPERCASE in SHOW output) → no quoting needed

**Dimension (nested under its table):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  - "{...additional ThoughtSpot synonyms}"
  description: "{description or [TS AI Context] {ai_context} or empty string}"
  expr: {table_alias}.{DB_COLUMN_NAME}    # or {table_alias}."{db_column_name}" if case-sensitive
  data_type: {TEXT|NUMBER|BOOLEAN}
```

**Time dimension (nested under its table):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  description: "{description or empty string}"
  expr: {table_alias}.{DB_COLUMN_NAME}    # or {table_alias}."{db_column_name}" if case-sensitive
  data_type: {DATE|TIMESTAMP}
```

**Column quoting in `expr`:** Double-quote the column name portion in the SQL expression when:
- The column is a SQL reserved word (`date`, `time`, `id`, `name`, `schema`, `table`, `value`, etc.)
- The column was created case-sensitively (appears lowercase in `SHOW COLUMNS`)
```yaml
  expr: {table_alias}."column_name"    # inline in the expression string (no YAML outer quotes needed)
```

**Metric — physical column (nested under its table):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  - "{...additional synonyms}"
  description: "{description or empty string}"
  expr: {AGG}({table_alias}.{DB_COLUMN_NAME})
  data_type: NUMBER
```

**Metric — translated formula (nested under its table):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  description: "{description or empty string}"
  expr: {translated SQL expression}
  data_type: NUMBER
```

**Untranslatable formula — OMIT ENTIRELY:**

Do **not** include columns whose ThoughtSpot formula cannot be translated to SQL.
Using placeholder `expr` values (e.g. `CAST(NULL AS TEXT)`, `-- TODO`, `NULL`)
causes Snowflake parse errors or silent incorrect results.

Instead:
1. **Omit the column** from the generated YAML
2. **Log it** in the Formula Translation Log section of the Unmapped Properties Report

The Formula Translation Log entry should capture:
- Column display name
- Original ThoughtSpot formula expression
- Reason it could not be translated (e.g. uses parameter, `sql_string_op`, time intelligence)

---

## Relationship Entry Template

```yaml
- name: {LEFT_TABLE}_to_{RIGHT_TABLE}
  left_table: {LEFT_TABLE_ALIAS}
  right_table: {RIGHT_TABLE_ALIAS}
  relationship_columns:
  - left_column: {LEFT_PHYSICAL_COLUMN}      # bare identifier — never '"col"'
    right_column: {RIGHT_PHYSICAL_COLUMN}    # bare identifier — never '"col"'
```

**Do not include** `relationship_type` or `join_type` — these fields are not supported
and will cause a parse error.

**`relationship_columns` must always use bare unquoted identifiers.** Cortex Analyst
rejects the `'"col"'` format with a 400 error. Even for case-sensitive lowercase
columns, emit the plain name without any quoting:
```yaml
  # CORRECT
  - left_column: alignment_id
    right_column: id

  # WRONG — causes 400 error from Cortex Analyst
  - left_column: '"alignment_id"'
    right_column: '"id"'
```
The Snowflake Semantic View framework resolves these case-insensitively, so `id`
matches a physical `"id"` column. Reserve `'"col"'` quoting for `base_table` fields
only; use inline `"col"` quoting inside `expr` SQL strings.
