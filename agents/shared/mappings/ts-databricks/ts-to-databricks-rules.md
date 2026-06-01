# Mapping Rules Reference

ThoughtSpot → Databricks Metric View conversion tables. Consult during Steps 4–9.

**Always use v1.1** — even for single-source MVs. v1.1 supports `source:` (same as
v0.1) but adds `display_name`, `comment`, and `synonyms` per column.

---

## Column Type Classification

Apply this decision tree to every column:

```
Is formula_id set?
  YES → Is it a LOD formula (group_aggregate with partition)?
          YES → dimensions (with window function in expr — see LOD section)
        Is it last_value/first_value (semi-additive)?
          YES → measures with window: [{semiadditive: last/first}] — see Semi-Additive section
        Is it sum_if(diff_months/quarters/years(...))?
          YES → measures with window: [{range: current, offset: ...}] — see Period-Filter section
        Is it moving_sum/moving_average?
          YES → measures with window: [{range: trailing N day}] — see Rolling Window section
        Is it cumulative_sum?
          YES → measures with window: [{range: cumulative}] — see Cumulative section
        Is it *_if(cond, x) (sum_if, count_if, unique_count_if, etc.)?
          YES → measures with FILTER (WHERE ...) — see Conditional Aggregates section
        Is it agg(if (cond) then x else null) (fallback pattern)?
          YES → measures with FILTER (WHERE ...) — see Conditional Aggregates section
          NO  → measures (if translatable) or OMIT (if untranslatable — see Step 9)
  NO  → Is column_type MEASURE?
          YES → measures
          NO  → dimensions
```

Unlike Snowflake SVs, Databricks Metric Views have no separate `time_dimensions`
category — date/timestamp columns go into `dimensions` alongside all other attributes.

---

## Aggregation Functions

Databricks MV embeds the aggregation in the measure `expr` — same pattern as
Snowflake SVs but with Databricks SQL syntax.

| ThoughtSpot `aggregation` | Databricks MV `expr` wrapper |
|---|---|
| `SUM` | `SUM(expr)` |
| `COUNT` | `COUNT(expr)` |
| `COUNT_DISTINCT` | `COUNT(DISTINCT expr)` |
| `AVG` / `AVERAGE` | `AVG(expr)` |
| `MIN` | `MIN(expr)` |
| `MAX` | `MAX(expr)` |
| `STD_DEVIATION` | `STDDEV(expr)` |
| `VARIANCE` | `VARIANCE(expr)` |
| *(not set on MEASURE)* | `SUM(expr)` *(default)* |

---

## Data Types

Databricks Metric Views do not have an explicit `data_type` field on dimensions
or measures. The data type is inferred from the source table column and the `expr`.

For reference when determining column classification from ThoughtSpot TML:

| Source field value | Databricks type | Classification |
|---|---|---|
| `VARCHAR`, `CHAR`, `TEXT`, `STRING` | `STRING` | dimension |
| `INT`, `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT`, `INT64` | `BIGINT`/`INT` | dimension or measure |
| `FLOAT`, `DOUBLE`, `DECIMAL`, `NUMERIC`, `REAL`, `NUMBER` | `DOUBLE`/`DECIMAL` | dimension or measure |
| `BOOLEAN`, `BOOL` | `BOOLEAN` | dimension |
| `DATE` | `DATE` | dimension |
| `DATETIME`, `DATE_TIME`, `TIMESTAMP`, `TIMESTAMP_NTZ` | `TIMESTAMP` | dimension |

---

## Name Generation Rules

Databricks MV dimension and measure names support spaces and mixed case —
no snake_case conversion needed. Use the ThoughtSpot display name directly:

```yaml
dimensions:
  - name: Sale Date          # Keep as-is from ThoughtSpot display name
    expr: sale_date
measures:
  - name: Total Revenue      # Keep as-is
    expr: SUM(revenue)
```

If the ThoughtSpot name contains characters that break YAML parsing (colons,
quotes, `#` at start of line), wrap the name in quotes:

```yaml
  - name: "Revenue: YoY Growth (%)"
    expr: ...
```

---

## v1.1 Column Metadata Mapping

v1.1 columns support rich metadata. Map ThoughtSpot properties as follows:

| ThoughtSpot property | v1.1 MV field | Notes |
|---|---|---|
| Column `name` (display name) | `display_name:` | Wrap in quotes for YAML safety |
| Column `description` | `comment:` | |
| `properties.synonyms[]` | `synonyms:` | Read from `properties.synonyms`, NOT column root. YAML list: `['alias1', 'alias2']` |
| Model-level `description` | Top-level `comment:` | |
| `ai_context` | **Unmapped** | No equivalent — log in Unmapped Report |
| `properties.calendar_type` | **Unmapped** | No equivalent |

The `name:` field in MV YAML is a machine-readable identifier (snake_case recommended).
The `display_name:` is the human-readable label.

---

## Expression Rules

### Single Source (v0.1 or v1.1 with `source:`)

Column references in `expr` use the source table's physical column names directly
(no table alias prefix):

```yaml
source: catalog.schema.fact_sales

dimensions:
  - name: store_id
    expr: store_id
    display_name: 'Store ID'

  - name: sale_year
    expr: YEAR(sale_date)
    display_name: 'Sale Year'

measures:
  - name: total_sales
    expr: SUM(sales_amount)
    display_name: 'Total Sales'
```

### Multi-Source (v1.1 with `entities:`)

Column references use `entity_alias.column` prefix:

```yaml
entities:
  - name: sales
    db_connection: catalog.schema.fact_sales
  - name: stores
    db_connection: catalog.schema.dim_stores

dimensions:
  - name: store_name
    expr: stores.store_name
    display_name: 'Store Name'

measures:
  - name: total_sales
    expr: SUM(sales.sales_amount)
    display_name: 'Total Sales'
```

---

## Filter Generation

ThoughtSpot models may contain boolean ATTRIBUTE formulas intended as filters
(e.g., `[MV Filter]`, `[Is Active]`). Detect these and translate to the MV
`filter:` field when possible.

### Detection

Look for formula columns that match these patterns:
- `column_type: ATTRIBUTE` with a boolean expression (comparisons, AND/OR, NOT)
- Column name contains "filter" (case-insensitive) — e.g., "MV Filter"
- Formula expr produces a boolean result (equality checks, `in()`, `between()`, etc.)

### Classification and translation

```
Is the formula a simple boolean expression?
  (Only AND-joined conditions, each being col = val, col != val, NOT col,
   col > val, col >= val, col < val, col <= val)
  YES → Translate to MV filter: field
        Each condition maps to SQL:
          [TABLE::col] = 'val'     → col = 'val'
          [TABLE::col] = false     → NOT col
          [TABLE::col] > N         → col > N
  NO  → Does it contain OR, in(), between(), or complex logic?
        YES → Still translatable — convert to SQL filter expression:
              [TABLE::col] = 'a' or [TABLE::col] = 'b'  → col IN ('a', 'b')
              [TABLE::col] >= N and [TABLE::col] <= M    → col BETWEEN N AND M
              Use parentheses for OR groups within AND
  NO  → Contains parameters, LOD, or untranslatable functions?
        YES → Omit — log in Unmapped Report
```

### ThoughtSpot → MV filter translation

| ThoughtSpot formula | MV `filter:` |
|---|---|
| `[TABLE::status] = 'Active'` | `status = 'Active'` |
| `[TABLE::is_deleted] = false` | `NOT is_deleted` |
| `[TABLE::status] = 'Active' and [TABLE::is_deleted] = false` | `status = 'Active' AND NOT is_deleted` |
| `[TABLE::status] = 'a' or [TABLE::status] = 'b'` | `status IN ('a', 'b')` |
| `[TABLE::amount] >= 100 and [TABLE::amount] <= 500` | `amount BETWEEN 100 AND 500` |

### Placement in YAML

```yaml
version: 1.1
source: catalog.schema.table
filter: status = 'Active' AND NOT is_deleted
dimensions:
  # ...
measures:
  # ...
```

The filter formula column is consumed by the `filter:` field — do **not** also
emit it as a dimension or measure. Remove it from the column list after converting.

### Non-filter boolean formulas

Not every boolean ATTRIBUTE is a filter. If the formula is used for grouping or
display (e.g., "Is High Value" used as a dimension in searches), keep it as a
dimension and do not move it to `filter:`. Only convert when the formula's
purpose is clearly row-level filtering.

---

## LOD Formulas → Dimension Window Functions

ThoughtSpot LOD formulas (`group_aggregate`, `group_sum`, etc.) map to **dimension**
entries with window functions — NOT measures with `AGGREGATE OVER`.

| ThoughtSpot formula | MV YAML (dimension) |
|---|---|
| `group_aggregate(sum(quantity), {product_category}, query_filters())` | `expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)` |
| `group_aggregate(count(order_id), {customer_id}, query_filters())` | `expr: COUNT(ORDER_ID) OVER (PARTITION BY CUSTOMER_ID)` |
| `group_aggregate(average(price), {region, year}, query_filters())` | `expr: AVG(PRICE) OVER (PARTITION BY REGION, YEAR)` |

**Key rules:**
- LOD results go in `dimensions[]`, not `measures[]`
- Use `AGG(col) OVER (PARTITION BY dim1, dim2)` in `expr`
- Do NOT use `AGGREGATE OVER` — it causes `PARSE_SYNTAX_ERROR`
- Do NOT use `window:` for LOD — `window` requires `semiadditive`

---

## Cross-Measure References

When a measure references another measure or an LOD dimension:

| Pattern | MV `expr` syntax |
|---|---|
| Reference another measure | `MEASURE(measure_name)` |
| Reference a dimension from a measure | `ANY_VALUE(dimension_name)` |
| Ratio: measure / LOD dimension | `MEASURE(quantity) / ANY_VALUE(category_quantity)` |

Example — contribution ratio:
```yaml
dimensions:
  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)

measures:
  - name: quantity
    expr: SUM(QUANTITY)
  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
```

---

## Window Measures — Classification

Two distinct ThoughtSpot patterns map to MV `window: [{range: current}]`:

```
Is the ThoughtSpot formula last_value() or first_value()?
  YES → True semi-additive (snapshot metric)
        order: raw date dimension, semiadditive: last/first
  NO  → Is it sum_if(diff_months/quarters/years(...))?
          YES → Period filter (flow/additive metric)
                order: truncated period dimension, semiadditive: last
```

---

## True Semi-Additive Measures

ThoughtSpot `last_value`/`first_value` formulas (snapshot metrics like inventory
balances, account balances) where summing across time is not meaningful:

| ThoughtSpot formula | MV `window` |
|---|---|
| `last_value(sum(m), query_groups(), {date})` | `window: [{order: raw_date_dim, semiadditive: last, range: current}]` |
| `first_value(sum(m), query_groups(), {date})` | `window: [{order: raw_date_dim, semiadditive: first, range: current}]` |

The `order:` dimension must reference a **raw date** dimension (not a truncated
period like month or quarter).

---

## Period-Filter Measures (`range: current` + truncated dimension)

ThoughtSpot `sum_if` patterns with `diff_months`/`diff_quarters`/`diff_years` map to
`window` with `range: current` and an optional `offset`. These are flow/additive
metrics (revenue, quantity) where `range: current` means "filter to the current
period."

| ThoughtSpot formula | MV `window` |
|---|---|
| `sum_if(diff_months([date], today()) = 0, [m])` | `window: [{order: month_dim, semiadditive: last, range: current}]` |
| `sum_if(diff_months([date], today()) = -1, [m])` | `window: [{order: month_dim, semiadditive: last, range: current, offset: -1 month}]` |
| `sum_if(diff_months([date], today()) = -12, [m])` | `window: [{order: month_dim, semiadditive: last, range: current, offset: -1 year}]` |
| `sum_if(diff_quarters([date], today()) = 0, [m])` | `window: [{order: quarter_dim, semiadditive: last, range: current}]` |
| `sum_if(diff_quarters([date], today()) = -1, [m])` | `window: [{order: quarter_dim, semiadditive: last, range: current, offset: -3 month}]` |
| `sum_if(diff_years([date], today()) = 0, [m])` | `window: [{order: year_dim, semiadditive: last, range: current}]` |
| `sum_if(diff_years([date], today()) = -1, [m])` | `window: [{order: year_dim, semiadditive: last, range: current, offset: -1 year}]` |
| `sum_if(diff_years([date], today()) = -2, [m])` | `window: [{order: year_dim, semiadditive: last, range: current, offset: -2 year}]` |

**`semiadditive` is required** when `window` is present. Valid values: `last`, `first`.

The `order:` dimension must reference a **truncated period** dimension (e.g., one
whose `expr` uses `DATE_TRUNC('MONTH', ...)`, `DATE_TRUNC('QUARTER', ...)`, etc.).

**Growth % formulas** inline `sum_if` for both periods — no cross-formula references:
```
( sum_if(diff_months([date], today()) = 0, [m])
- sum_if(diff_months([date], today()) = -1, [m]) )
/ sum_if(diff_months([date], today()) = -1, [m]) * 100
```

---

## Rolling Window Measures (`moving_sum` / `moving_average`)

ThoughtSpot `moving_sum(m, N, 0, d)` maps to `window` with `range: trailing N day`:

| ThoughtSpot formula | MV `window` |
|---|---|
| `moving_sum([m], 7, 0, [d])` | `window: [{order: date_dim, range: trailing 7 day, semiadditive: last}]` |
| `moving_sum([m], 30, 0, [d])` | `window: [{order: date_dim, range: trailing 30 day, semiadditive: last}]` |
| `moving_average([m], 7, 0, [d])` | `window: [{order: date_dim, range: trailing 7 day, semiadditive: last}]` (with `AVG` in `expr`) |

The `order:` dimension should be a date-granularity dimension (daily). The N value
maps directly to the trailing day count.

---

## Conditional Aggregates (TS `*_if` → Databricks `FILTER (WHERE ...)`)

ThoughtSpot native `*_if` conditional aggregate functions map to Databricks
`FILTER (WHERE ...)` syntax:

| ThoughtSpot formula | MV `expr` |
|---|---|
| `sum_if ( cond , [x] )` | `SUM(x) FILTER (WHERE cond)` |
| `count_if ( cond , [x] )` | `COUNT(x) FILTER (WHERE cond)` |
| `unique_count_if ( cond , [x] )` | `COUNT(DISTINCT x) FILTER (WHERE cond)` |
| `average_if ( cond , [x] )` | `AVG(x) FILTER (WHERE cond)` |
| `min_if ( cond , [x] )` | `MIN(x) FILTER (WHERE cond)` |
| `max_if ( cond , [x] )` | `MAX(x) FILTER (WHERE cond)` |
| `stddev_if ( cond , [x] )` | `STDDEV(x) FILTER (WHERE cond)` |
| `variance_if ( cond , [x] )` | `VARIANCE(x) FILTER (WHERE cond)` |

Also detect the fallback pattern: an aggregate wrapping `if()` where the else
branch is `null` (or `0` for SUM) → extract the condition into `FILTER (WHERE ...)`.

---

## Cumulative Measures

ThoughtSpot `cumulative_sum(m, d)` maps to `window` with `range: cumulative`:

```yaml
measures:
  - name: cumulative_revenue
    expr: SUM(LINE_TOTAL)
    display_name: 'Cumulative Revenue'
    window:
      - order: order_date
        semiadditive: last
        range: cumulative
```

---

## safe_divide → COALESCE/NULLIF

ThoughtSpot `safe_divide(a, b)` maps to `COALESCE(a / NULLIF(b, 0), 0)`:

```yaml
measures:
  - name: answer_formula
    expr: COALESCE(SUM(LINE_TOTAL) / NULLIF(SUM(QUANTITY), 0), 0)
```

---

## Multi-Table Model Mapping

### Single-fact with dimension joins (primary approach)

Use v1.1 nested `joins:` to express the star schema directly. Map ThoughtSpot
`joins[]` / `referencing_join` to nested join entries:

```yaml
source: catalog.schema.fact_table
joins:
  - name: dim_alias                           # from TS join target table name
    source: catalog.schema.dim_table
    "on": source.FK_COL = dim_alias.PK_COL    # from TS join condition
    rely: { at_most_one_match: true }          # many-to-one cardinality
    joins:                                     # nested for dimension-of-dimension
      - name: sub_dim_alias
        source: catalog.schema.sub_dim
        "on": dim_alias.FK = sub_dim_alias.PK
        rely: { at_most_one_match: true }
```

**Column references** use dot-path through the join hierarchy:
- Fact table: `source.COL`
- First-level dim: `dim_alias.COL`
- Nested dim: `dim_alias.sub_dim_alias.COL`

**Mapping from ThoughtSpot joins:**

| ThoughtSpot | Databricks MV |
|---|---|
| `model_tables[0]` (primary fact) | `source:` |
| `model_tables[].joins[].with` | Nested `joins[].name` |
| `joins[].on: "[A::fk] = [B::pk]"` | `"on": source.fk = alias.pk` or nested equivalent |
| `joins[].type: INNER` | Default join type (no explicit type field in MV) |
| `joins[].cardinality: MANY_TO_ONE` | `rely: { at_most_one_match: true }` |

### Multi-fact models (split required)

Models with multiple fact tables must be split into independent MVs because each MV
has a single `source:`. Each fact table becomes its own MV with its dimension tables
joined via nested `joins:`.

**Split pattern:**
1. Identify fact tables (tables with MEASURE columns)
2. Create one MV per fact table as `source:`, with dimension tables as nested `joins:`
3. Deduplicate shared dimension columns across MVs

### Flattened SQL VIEW (fallback only)

Only use flattened views when the join structure cannot be expressed as nested joins
(e.g., many-to-many, cross-fact). The user must confirm this approach at the Step 10
checkpoint.

See the [Dunder Mifflin worked example](../../worked-examples/databricks/ts-to-databricks.md)
for a complete multi-fact split.

---

## Metric View YAML Templates

### v1.1 — Single Source

```yaml
version: 1.1
comment: >-
  Description of what this Metric View covers.
source: catalog.schema.table_or_view
dimensions:
  - name: identifier_name
    expr: PHYSICAL_COLUMN
    display_name: 'Human Label'
    comment: 'Column description.'
    synonyms: ['alias1', 'alias2']
measures:
  - name: identifier_name
    expr: AGG(PHYSICAL_COLUMN)
    display_name: 'Human Label'
    comment: 'Measure description.'
    synonyms: ['alias1']
```

### v1.1 — Star Schema with Joins (recommended for multi-table)

```yaml
version: 1.1
comment: >-
  Description.
source: catalog.schema.fact_table
joins:
  - name: dim_alias
    source: catalog.schema.dim_table
    "on": source.FK = dim_alias.PK
    rely: { at_most_one_match: true }
    joins:
      - name: sub_dim
        source: catalog.schema.sub_dim_table
        "on": dim_alias.FK2 = sub_dim.PK2
        rely: { at_most_one_match: true }
dimensions:
  - name: dim_col
    expr: dim_alias.COLUMN_NAME
    display_name: 'Human Label'
  - name: nested_dim_col
    expr: dim_alias.sub_dim.COLUMN_NAME     # dot-path through hierarchy
    display_name: 'Nested Dim Label'
measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Revenue'
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }
```

### Untranslatable Formula — OMIT ENTIRELY

Do not include columns whose ThoughtSpot formula cannot be translated to
Databricks SQL. Instead:

1. Omit the column from the generated YAML
2. Log it in the Unmapped Properties Report

---

## Unmapped ThoughtSpot Properties

These ThoughtSpot properties have no Databricks MV equivalent:

| ThoughtSpot property | Status | Notes |
|---|---|---|
| `ai_context` | **Unmapped** | No equivalent — include in view-level `comment` if relevant |
| `properties.calendar_type` | **Unmapped** | No equivalent |
| `properties.index_type` | **Unmapped** | Databricks handles indexing internally |
| `properties.index_priority` | **Unmapped** | No equivalent |
| `properties.currency_type` | `format: { type: currency, currency_code: ... }` | v1.1 supports `format:` on measures |
| `properties.geo_config` | **Unmapped** | No geo support in MV |
| `column_type: UNKNOWN` | **Omit** | Cannot classify — log in report |
