# Mapping Rules Reference

ThoughtSpot → Snowflake Semantic View conversion tables. Consult during Steps 7–9.

---

## Column Type Classification

Apply this decision tree to every column:

```
Is formula_id set?
  YES → measures
  NO  → Is column_type MEASURE?
          YES → measures
          NO  → Is db_column_type or column name a date/timestamp? (see Data Types below)
                  YES → time_dimensions
                  NO  → dimensions
```

---

## Aggregation Functions

| ThoughtSpot `aggregation` | Snowflake `expr` wrapper | `default_aggregation` |
|---|---|---|
| `SUM` | `SUM(expr)` | `sum` |
| `COUNT` | `COUNT(expr)` | `count` |
| `COUNT_DISTINCT` | `COUNT(DISTINCT expr)` | `count_distinct` |
| `AVG` / `AVERAGE` | `AVG(expr)` | `avg` |
| `MIN` | `MIN(expr)` | `min` |
| `MAX` | `MAX(expr)` | `max` |
| `STD_DEVIATION` | `STDDEV(expr)` | `avg` *(flag for review — no direct match)* |
| `VARIANCE` | `VARIANCE(expr)` | `avg` *(flag for review — no direct match)* |
| *(not set on MEASURE)* | `SUM(expr)` | `sum` *(default)* |

---

## Join Types

| ThoughtSpot `type` | Snowflake `join_type` |
|---|---|
| `INNER` | `inner` |
| `LEFT_OUTER` | `left` |
| `RIGHT_OUTER` | `right` |
| `FULL_OUTER` | `full` |
| *(absent)* | `inner` *(default)* |

---

## Cardinality / Relationship Types

| ThoughtSpot source | Snowflake `relationship_type` |
|---|---|
| `is_one_to_one: true` | `one_to_one` |
| `is_one_to_one: false` *(default)* | `many_to_one` |
| `cardinality: MANY_TO_ONE` | `many_to_one` |
| `cardinality: ONE_TO_ONE` | `one_to_one` |
| `cardinality: ONE_TO_MANY` | `one_to_many` |
| `cardinality: MANY_TO_MANY` | `many_to_many` |
| *(absent)* | `many_to_one` *(default)* |

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

**Dimension:**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  - "{...additional ThoughtSpot synonyms}"
  description: "{description or [TS AI Context] {ai_context} or empty string}"
  expr: {table_alias}.{DB_COLUMN_NAME}
  data_type: {TEXT|NUMBER|BOOLEAN}
  sample_values: []
```

**Time dimension:**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  description: "{description or empty string}"
  expr: {table_alias}.{DB_COLUMN_NAME}
  data_type: {DATE|TIMESTAMP}
```

**Measure (physical column):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  - "{...additional synonyms}"
  description: "{description or empty string}"
  expr: {AGG}({table_alias}.{DB_COLUMN_NAME})
  data_type: NUMBER
  default_aggregation: {sum|count|avg|min|max|count_distinct}
```

**Measure (translated formula):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  description: "{description or empty string}"
  expr: {translated SQL expression}
  data_type: NUMBER
  default_aggregation: sum
```

**Measure (untranslatable formula):**
```yaml
- name: {snake_case_name}
  synonyms:
  - "{display_name}"
  description: "{description or empty string}"
  expr: "-- TODO: {reason}. Original ThoughtSpot formula: {original_expr}"
  data_type: NUMBER
  default_aggregation: sum
```
