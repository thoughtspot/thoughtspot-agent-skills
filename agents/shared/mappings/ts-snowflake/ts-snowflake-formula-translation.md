# Formula Translation Reference — Snowflake

Bidirectional translation rules between ThoughtSpot formulas and **Snowflake** Semantic
View expressions. Use **TS → Snowflake** when converting ThoughtSpot models to semantic
views (Step 9) and **Snowflake → TS** when converting semantic views to ThoughtSpot
models.

> **Platform-specific:** This reference targets Snowflake SQL syntax and Snowflake
> Semantic View constructs (`PARTITION BY EXCLUDING`, `NON ADDITIVE BY`, etc.).
> For other platforms (e.g. Databricks, BigQuery), create a separate translation
> reference with platform-specific overrides.

---

## YAML Expression Formatting

**CRITICAL:** Snowflake Semantic View YAML does not support YAML block scalars.
Every `expr` value must be a **single-line double-quoted string**, regardless of length.

```yaml
# CORRECT
expr: "SUM(tbl.col) OVER (PARTITION BY EXCLUDING dim.attr ORDER BY dim.attr ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"

# WRONG — Snowflake rejects block scalars
expr: >-
  SUM(tbl.col) OVER (
    PARTITION BY EXCLUDING dim.attr
    ORDER BY dim.attr
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  )
```

This applies to all `expr` fields in `dimensions`, `time_dimensions`, and `metrics`.
All examples in this document use the correct single-line format.

---

## Translation Decision Flowchart

Use this to quickly determine which section to consult for a given formula:

```
Formula contains...
├── [word] with no ::           → Parameter References (untranslatable)
├── sql_*_op(...)               → SQL Pass-Through Functions
├── cumulative_*                → Window: Cumulative Functions
├── moving_*                    → Window: Moving Functions
├── rank( or rank_percentile(   → Window: Rank Functions
├── group_* or group_aggregate  → Level of Detail (LOD) Functions
├── last_value( or first_value( → Semi-Additive Functions
├── last_value_in_period(       → Semi-Additive (untranslatable)
├── first_value_in_period(      → Semi-Additive (untranslatable)
├── [TABLE::COL] references     → Resolve via Column Reference Syntax
├── [other_formula_name]        → Resolve via Nested Column References
└── standard function(args)     → Scalar Functions
```

---

## Column Reference Syntax

ThoughtSpot formulas reference columns differently depending on TML format.

**Worksheet TML** — uses `table_path` IDs:
```
[fact_sales_1::sales_amount]
```
Resolution:
1. Look up `fact_sales_1` in the path → table map (built in Step 6)
2. Result: table alias = `fact_sales`
3. Look up `sales_amount` in Table TML columns → `db_column_name` = `SALES_AMOUNT`
4. Output: `fact_sales.SALES_AMOUNT`

**Model TML** — uses direct table names:
```
[DM_ORDER::FREIGHT]
```
Resolution:
1. `DM_ORDER` is the table alias directly
2. Look up `FREIGHT` in Table TML columns → `db_column_name` = `FREIGHT`
3. Output: `DM_ORDER.FREIGHT`

**Important:** A reference like `[Date]` in a Model TML formula is likely a **parameter**
reference (single word, no `::` separator), not a column. See Untranslatable Patterns.

---

## Nested Column References

If a formula references another model column by display name (e.g. `[Revenue]`):

1. Look up that column name in the model's column list.
2. Substitute its already-translated `expr` value inline.
3. Apply recursively up to **3 levels deep**.
4. If circular or deeper than 3 levels, **omit the column entirely** and log it in the Formula Translation Log.

---

## Scalar Functions

These functions translate 1:1 in both directions.

### Aggregate Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `sum ( [x] )` → `SUM(x)` | `SUM(x)` → `sum ( [x] )` |
| `count ( [x] )` → `COUNT(x)` | `COUNT(x)` → `count ( [x] )` |
| `count_distinct ( [x] )` → `COUNT(DISTINCT x)` | `COUNT(DISTINCT x)` → `count_distinct ( [x] )` |
| `unique count ( [x] )` → `COUNT(DISTINCT x)` | *(same as above)* |
| `average ( [x] )` → `AVG(x)` | `AVG(x)` → `average ( [x] )` |
| `min ( [x] )` → `MIN(x)` | `MIN(x)` → `min ( [x] )` |
| `max ( [x] )` → `MAX(x)` | `MAX(x)` → `max ( [x] )` |
| `median ( [x] )` → `MEDIAN(x)` | `MEDIAN(x)` → `median ( [x] )` |
| `stddev ( [x] )` → `STDDEV(x)` | `STDDEV(x)` → `stddev ( [x] )` |
| `variance ( [x] )` → `VARIANCE(x)` | `VARIANCE(x)` → `variance ( [x] )` |

### Conditional Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `if [cond] then [a] else [b]` → `CASE WHEN cond THEN a ELSE b END` | `CASE WHEN cond THEN a ELSE b END` → `if [cond] then [a] else [b]` |
| `if [c1] then [a] else if [c2] then [b] else [c]` → `CASE WHEN c1 THEN a WHEN c2 THEN b ELSE c END` | `CASE WHEN c1 THEN a WHEN c2 THEN b ELSE c END` → `if [c1] then [a] else if [c2] then [b] else [c]` |
| `isnull ( [x] )` → `x IS NULL` | `x IS NULL` → `isnull ( [x] )` |
| `isnotnull ( [x] )` → `x IS NOT NULL` | `x IS NOT NULL` → `isnotnull ( [x] )` |
| `ifnull ( [x] , [default] )` → `COALESCE(x, default)` | `COALESCE(x, default)` → `ifnull ( [x] , [default] )` |
| `nullif ( [a] , [b] )` → `NULLIF(a, b)` | `NULLIF(a, b)` → `nullif ( [a] , [b] )` |
| `not ( [x] )` → `NOT x` | `NOT x` → `not ( [x] )` |

### Logical and Comparison Operators

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `[a] and [b]` → `a AND b` | `a AND b` → `[a] and [b]` |
| `[a] or [b]` → `a OR b` | `a OR b` → `[a] or [b]` |
| `[x] in ( 'a' , 'b' )` → `x IN ('a', 'b')` | `x IN ('a', 'b')` → `[x] in ( 'a' , 'b' )` |
| `[x] not in ( 'a' , 'b' )` → `x NOT IN ('a', 'b')` | `x NOT IN ('a', 'b')` → `[x] not in ( 'a' , 'b' )` |
| `[x] between [a] and [b]` → `x BETWEEN a AND b` | `x BETWEEN a AND b` → `[x] between [a] and [b]` |
| `=`, `!=`, `<>`, `>`, `<`, `>=`, `<=` | Pass through directly in both directions |

### Math Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `safe_divide ( [a] , [b] )` → `(a) / NULLIF(b, 0)` | `(a) / NULLIF(b, 0)` → `safe_divide ( [a] , [b] )` |
| `round ( [x] , [n] )` → `ROUND(x, n)` | `ROUND(x, n)` → `round ( [x] , [n] )` |
| `floor ( [x] )` → `FLOOR(x)` | `FLOOR(x)` → `floor ( [x] )` |
| `ceil ( [x] )` → `CEIL(x)` | `CEIL(x)` → `ceil ( [x] )` |
| `abs ( [x] )` → `ABS(x)` | `ABS(x)` → `abs ( [x] )` |
| `power ( [x] , [n] )` → `POWER(x, n)` | `POWER(x, n)` → `power ( [x] , [n] )` |
| `mod ( [x] , [n] )` → `MOD(x, n)` | `MOD(x, n)` → `mod ( [x] , [n] )` |
| `sqrt ( [x] )` → `SQRT(x)` | `SQRT(x)` → `sqrt ( [x] )` |
| `ln ( [x] )` → `LN(x)` | `LN(x)` → `ln ( [x] )` |
| `log2 ( [x] )` → `LOG(2, x)` | `LOG(2, x)` → `log2 ( [x] )` |
| `log10 ( [x] )` → `LOG(10, x)` | `LOG(10, x)` → `log10 ( [x] )` |

### String Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `concat ( [a] , [b] )` → `CONCAT(a, b)` | `CONCAT(a, b)` → `concat ( [a] , [b] )` |
| `concat ( [a] , ' ' , [b] )` → `CONCAT(a, ' ', b)` *(supports N args)* | `CONCAT(a, ' ', b)` → `concat ( [a] , ' ' , [b] )` |
| `substr ( [x] , [start] , [len] )` → `SUBSTR(x, start, len)` | `SUBSTR(x, start, len)` → `substr ( [x] , [start] , [len] )` |
| `strlen ( [x] )` → `LENGTH(x)` | `LENGTH(x)` → `strlen ( [x] )` |
| `upper ( [x] )` → `UPPER(x)` | `UPPER(x)` → `upper ( [x] )` |
| `lower ( [x] )` → `LOWER(x)` | `LOWER(x)` → `lower ( [x] )` |
| `trim ( [x] )` → `TRIM(x)` | `TRIM(x)` → `trim ( [x] )` |
| `replace ( [x] , [old] , [new] )` → `REPLACE(x, old, new)` | `REPLACE(x, old, new)` → `replace ( [x] , [old] , [new] )` |
| `contains ( [x] , 'val' )` → `CONTAINS(x, 'val')` | `CONTAINS(x, 'val')` → `contains ( [x] , 'val' )` |
| `starts_with ( [x] , 'val' )` → `STARTSWITH(x, 'val')` | `STARTSWITH(x, 'val')` → `starts_with ( [x] , 'val' )` |
| `ends_with ( [x] , 'val' )` → `ENDSWITH(x, 'val')` | `ENDSWITH(x, 'val')` → `ends_with ( [x] , 'val' )` |

### Type Conversion Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `to_integer ( [x] )` → `CAST(x AS INTEGER)` | `CAST(x AS INTEGER)` → `to_integer ( [x] )` |
| `to_double ( [x] )` → `CAST(x AS DOUBLE)` | `CAST(x AS DOUBLE)` → `to_double ( [x] )` |
| `to_string ( [x] )` → `CAST(x AS VARCHAR)` | `CAST(x AS VARCHAR)` → `to_string ( [x] )` |

### Date Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `year ( [date] )` → `YEAR(date)` | `YEAR(date)` → `year ( [date] )` |
| `month ( [date] )` → `MONTH(date)` | `MONTH(date)` → `month ( [date] )` |
| `day ( [date] )` → `DAY(date)` | `DAY(date)` → `day ( [date] )` |
| `hour ( [date] )` → `HOUR(date)` | `HOUR(date)` → `hour ( [date] )` |
| `diff_days ( [end] , [start] )` → `DATEDIFF('day', start, end)` | `DATEDIFF('day', start, end)` → `diff_days ( [end] , [start] )` |
| `diff_months ( [end] , [start] )` → `DATEDIFF('month', start, end)` | `DATEDIFF('month', start, end)` → `diff_months ( [end] , [start] )` |
| `diff_years ( [end] , [start] )` → `DATEDIFF('year', start, end)` | `DATEDIFF('year', start, end)` → `diff_years ( [end] , [start] )` |
| `today ()` → `CURRENT_DATE()` | `CURRENT_DATE()` → `today ()` |
| `now ()` → `CURRENT_TIMESTAMP()` | `CURRENT_TIMESTAMP()` → `now ()` |
| `add_days ( [date] , [n] )` → `DATEADD('day', n, date)` | `DATEADD('day', n, date)` → `add_days ( [date] , [n] )` |
| `add_weeks ( [date] , [n] )` → `DATEADD('week', n, date)` | `DATEADD('week', n, date)` → `add_weeks ( [date] , [n] )` |
| `add_months ( [date] , [n] )` → `DATEADD('month', n, date)` | `DATEADD('month', n, date)` → `add_months ( [date] , [n] )` |
| `date_trunc ( 'month' , [date] )` → `DATE_TRUNC('MONTH', date)` | `DATE_TRUNC('MONTH', date)` → `date_trunc ( 'month' , [date] )` |

Note: `DATEDIFF` argument order is reversed — ThoughtSpot uses `(end, start)`,
Snowflake uses `(part, start, end)`. `DATEADD` argument order also differs —
ThoughtSpot uses `(date, n)`, Snowflake uses `(part, n, date)`.

---

## SQL Pass-Through Functions

ThoughtSpot's `sql_*` pass-through functions embed raw SQL templates with positional
`{0}`, `{1}` placeholders for column references. Since the templates contain valid
Snowflake SQL, they can be translated directly by substituting column references.

**Function variants:**

| ThoughtSpot function | Return type | Semantic view field |
|---|---|---|
| `sql_string_op(template, args...)` | VARCHAR | Dimension |
| `sql_int_op(template, args...)` | INTEGER | Dimension |
| `sql_bool_op(template, args...)` | BOOLEAN | Dimension |
| `sql_double_op(template, args...)` | DOUBLE | Dimension |
| `sql_string_aggregate_op(template, args...)` | VARCHAR | Metric |
| `sql_int_aggregate_op(template, args...)` | INTEGER | Metric |
| `sql_number_aggregate_op(template, args...)` | NUMBER | Metric |

**Translation rule:**

1. Extract the template string (first argument, in quotes)
2. Replace `{0}`, `{1}`, `{2}`, ... with the resolved column references
   (same `table.COLUMN` format as other expressions)
3. Use the resulting SQL as the `expr` value
4. Non-aggregate variants (`sql_string_op`, `sql_int_op`, etc.) → dimension
5. Aggregate variants (`sql_*_aggregate_op`) → metric
6. If the template contains `OVER (...)` → window function metric

**Example — `sql_string_aggregate_op("listagg({0}, ' - ') within group (order by {0} desc)", Product Name)`:**

```yaml
metrics:
  - name: product_list
    expr: "LISTAGG(products.PRODUCT_NAME, ' - ') WITHIN GROUP (ORDER BY products.PRODUCT_NAME DESC)"
```

**Example — `sql_int_aggregate_op("rank() over (partition by {0} order by sum({1}) desc)", Category Name, Quantity)`:**

```yaml
metrics:
  - name: category_quantity_rank
    expr: "RANK() OVER (PARTITION BY categories.CATEGORY_NAME ORDER BY SUM(order_detail.QUANTITY) DESC)"
```

**Example — `sql_string_op("get({0},{1})::text", json_col, locale)`:**

```yaml
dimensions:
  - name: locale_value
    expr: "GET(table.JSON_COL, table.LOCALE)::TEXT"
    data_type: TEXT
```

**Reverse translation (semantic view → ThoughtSpot):**

Any `expr` that uses Snowflake-specific syntax not covered by ThoughtSpot's native
functions can be wrapped in the appropriate `sql_*` pass-through:

- Scalar text expression → `sql_string_op("template", col1, col2)`
- Scalar numeric expression → `sql_int_op(...)` or `sql_double_op(...)`
- Aggregate expression → `sql_string_aggregate_op(...)` or `sql_number_aggregate_op(...)`

Replace each column reference with `{0}`, `{1}`, ... positional placeholders.

**Edge case — template references a parameter:** If any argument to the `sql_*`
function is a ThoughtSpot parameter (e.g. `[locale]`), the formula is
**untranslatable** because the parameter cannot be resolved to a static column.

---

## Window and Analytical Functions

Snowflake Semantic Views support **window function metrics** natively. These are
translatable — they produce a metric with `OVER (...)` syntax. Window function metrics
have two restrictions: they cannot be referenced by dimensions/facts, and they cannot
be used in the definition of other metrics.

### Cumulative Functions

ThoughtSpot syntax: `cumulative_{func}(measure, attr1 [, attr2, ...])`

- The **measure** argument is the column to aggregate
- The **attribute arguments** define the `ORDER BY` columns in the window
- Any additional dimensions the user adds at query time are **dynamically** added
  to `PARTITION BY` — this is achieved using `PARTITION BY EXCLUDING`

**Translation requires two metrics:**

1. A **base metric** that aggregates the measure column
2. A **window function metric** that applies the cumulative function over the base metric

**Translation rules:**

| ThoughtSpot function | Base metric | Window function metric |
|---|---|---|
| `cumulative_sum(measure, attr1, attr2)` | `SUM(measure)` | `SUM(base_metric) OVER (PARTITION BY EXCLUDING attr1, attr2 ORDER BY attr1, attr2 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` |
| `cumulative_average(measure, attr1, attr2)` | `SUM(measure)` | `AVG(base_metric) OVER (PARTITION BY EXCLUDING attr1, attr2 ORDER BY attr1, attr2 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` |
| `cumulative_max(measure, attr1, attr2)` | `MAX(measure)` | `MAX(base_metric) OVER (PARTITION BY EXCLUDING attr1, attr2 ORDER BY attr1, attr2 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` |
| `cumulative_min(measure, attr1, attr2)` | `MIN(measure)` | `MIN(base_metric) OVER (PARTITION BY EXCLUDING attr1, attr2 ORDER BY attr1, attr2 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` |

**Note on inner aggregates:**
- `cumulative_sum` and `cumulative_average` use `SUM` as the inner (base) aggregate
- `cumulative_max` and `cumulative_min` use `MAX` / `MIN` as the inner aggregate

**Example — `cumulative_sum(Amount, Customer Code, Product)`:**

```yaml
metrics:
  - name: line_total
    expr: SUM(order_detail.LINE_TOTAL)
  - name: cumulative_line_total
    expr: "SUM(order_detail.line_total) OVER (PARTITION BY EXCLUDING customers.customer_code, products.product_name ORDER BY customers.customer_code, products.product_name ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"
```

**How `PARTITION BY EXCLUDING` mimics ThoughtSpot's dynamic behavior:**

| Dimensions in query | Effective PARTITION BY | Effective ORDER BY |
|---|---|---|
| `customer_code` | *(empty)* | `customer_code` |
| `country`, `customer_code` | `country` | `customer_code` |
| `country`, `customer_code`, `product_name` | `country` | `customer_code, product_name` |

**Reverse translation (semantic view → ThoughtSpot):**

```
SUM(metric) OVER (
  PARTITION BY EXCLUDING dim1, dim2
  ORDER BY dim1, dim2
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
→ cumulative_sum(measure_column, dim1, dim2)
```

Match the outer window function to determine the ThoughtSpot function name:
`SUM` → `cumulative_sum`, `AVG` → `cumulative_average`,
`MAX` → `cumulative_max`, `MIN` → `cumulative_min`.

### Moving Functions

ThoughtSpot syntax: `moving_{func}(measure, start, end, attr1 [, attr2, ...])`

- The **measure** argument is the column to aggregate
- The **start** and **end** arguments define the window frame bounds
- The **attribute arguments** define the `ORDER BY` columns in the window
- Additional dimensions added at query time dynamically enter `PARTITION BY`
  — achieved using `PARTITION BY EXCLUDING`

**Frame bound conversion — negate the sign:**

| TS value | SQL frame bound |
|---|---|
| Positive `n` | `n PRECEDING` |
| `0` | `CURRENT ROW` |
| Negative `-n` | `n FOLLOWING` |

Both args use the same rule independently.

**Verified examples:**

| TS args (start, end) | SQL frame |
|---|---|
| `1, -1` | `ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING` |
| `2, 0` | `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` |
| `3, -3` | `ROWS BETWEEN 3 PRECEDING AND 3 PRECEDING` |
| `-3, 3` | `ROWS BETWEEN 3 FOLLOWING AND 3 FOLLOWING` |

**Translation requires two metrics:**

1. A **base metric** that aggregates the measure column
2. A **window function metric** that applies the moving function over the base metric

**Translation rules:**

| ThoughtSpot function | Base metric | Window function |
|---|---|---|
| `moving_sum(measure, s, e, attrs...)` | `SUM(measure)` | `SUM(base_metric) OVER (...)` |
| `moving_average(measure, s, e, attrs...)` | `SUM(measure)` | `AVG(base_metric) OVER (...)` |
| `moving_max(measure, s, e, attrs...)` | `MAX(measure)` | `MAX(base_metric) OVER (...)` |
| `moving_min(measure, s, e, attrs...)` | `MIN(measure)` | `MIN(base_metric) OVER (...)` |

**Example — `moving_sum(Amount, 2, 0, order date)`:**

```yaml
metrics:
  - name: line_total
    expr: SUM(order_detail.LINE_TOTAL)
  - name: moving_sum_line_total
    expr: "SUM(order_detail.line_total) OVER (PARTITION BY EXCLUDING date_dim.order_date ORDER BY date_dim.order_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)"
```

**Example — `moving_sum(Amount, 1, -1, order date, Customer Code)`:**

```yaml
metrics:
  - name: line_total
    expr: SUM(order_detail.LINE_TOTAL)
  - name: moving_sum_line_total
    expr: "SUM(order_detail.line_total) OVER (PARTITION BY EXCLUDING date_dim.order_date, customers.customer_code ORDER BY date_dim.order_date, customers.customer_code ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING)"
```

**Dynamic PARTITION BY behavior (same as cumulative functions):**

| Dimensions in query | Effective PARTITION BY | Effective ORDER BY |
|---|---|---|
| `order_date` | *(empty)* | `order_date` |
| `country`, `order_date` | `country` | `order_date` |
| `country`, `month`, `order_date` | `country` | `month, order_date` |

Note: when the user changes date grain (e.g. monthly), ThoughtSpot wraps the date
with `DATE_TRUNC('MONTH', ...)`. This is a query-time behavior — the semantic view
translation uses the base date dimension and Cortex Analyst handles grain selection.

**Reverse translation (semantic view → ThoughtSpot):**

```
SUM(metric) OVER (
  PARTITION BY EXCLUDING dim1
  ORDER BY dim1
  ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
)
→ moving_sum(measure_column, 2, 0, dim1)
```

Convert SQL frame bounds back to TS args: `PRECEDING n` → positive `n`,
`CURRENT ROW` → `0`, `FOLLOWING n` → negative `-n`.

### Rank Functions

ThoughtSpot syntax:
- `rank(agg(measure), 'asc'|'desc')`
- `rank_percentile(agg(measure), 'asc'|'desc')`

Key behavior:
- **No PARTITION BY** — rank is always global across all rows in the result
- **No attribute arguments** — the ORDER BY is derived from the measure aggregation
- **Direction** — `'desc'` adds `DESC` to the ORDER BY; `'asc'` uses default ascending
- ThoughtSpot does not support adding partition attributes for rank functions

**Translation rules:**

| ThoughtSpot function | Semantic view metric |
|---|---|
| `rank(agg(measure), 'desc')` | `RANK() OVER (ORDER BY base_metric DESC)` |
| `rank(agg(measure), 'asc')` | `RANK() OVER (ORDER BY base_metric ASC)` |
| `rank_percentile(agg(measure), 'asc')` | `(1.0 - PERCENT_RANK() OVER (ORDER BY base_metric ASC)) * 100` |
| `rank_percentile(agg(measure), 'desc')` | `(1.0 - PERCENT_RANK() OVER (ORDER BY base_metric DESC)) * 100` |

**Example — `rank(sum(Quantity), 'desc')`:**

```yaml
metrics:
  - name: total_quantity
    expr: SUM(order_detail.QUANTITY)
  - name: quantity_rank
    expr: RANK() OVER (ORDER BY order_detail.total_quantity DESC)
```

**Example — `rank_percentile(sum(Quantity), 'asc')`:**

```yaml
metrics:
  - name: total_quantity
    expr: SUM(order_detail.QUANTITY)
  - name: quantity_rank_pct
    expr: (1.0 - PERCENT_RANK() OVER (ORDER BY order_detail.total_quantity ASC)) * 100
```

**Reverse translation (semantic view → ThoughtSpot):**

- `RANK() OVER (ORDER BY metric DESC)` → `rank(agg(measure), 'desc')`
- `(1.0 - PERCENT_RANK() OVER (...)) * 100` → `rank_percentile(agg(measure), ...)`

---

## Level of Detail (LOD) Functions

ThoughtSpot LOD functions (`group_aggregate` and the `group_*` shorthand family) compute
sub-aggregations at a fixed or dynamic granularity. In ThoughtSpot these generate SQL CTEs.

The `group_{func}` shorthands are syntactic sugar for `group_aggregate`:

| Shorthand | Equivalent |
|---|---|
| `group_sum(quantity, product)` | `group_aggregate(sum(quantity), {product}, query_filters())` |
| `group_max(quantity, category)` | `group_aggregate(max(quantity), {category}, query_filters())` |

### `group_aggregate` Grouping Syntax

The grouping argument controls the `PARTITION BY` behavior:

| ThoughtSpot grouping | Behavior | Semantic view equivalent | Status |
|---|---|---|---|
| `{}` | No dimensions — grand total | `OVER ()` | Translatable |
| `{attr1, attr2}` | Always these dimensions, ignores query | `OVER (PARTITION BY attr1, attr2)` | Translatable |
| `query_groups() - {attr1, attr2}` | All query dimensions minus attr1/attr2 | `OVER (PARTITION BY EXCLUDING attr1, attr2)` | Translatable |
| `query_groups()` | All query dimensions | Regular metric (no window function needed) | Translatable |
| `query_groups() + {}` | Same as `query_groups()` (prevents TS SQL simplification) | Regular metric (no window function needed) | Translatable |
| `query_groups() + {attr}` | All query dimensions + always include attr | No direct equivalent | **Untranslatable** |
| `query_groups(attr1, attr2)` | Only include attr1/attr2 if they are in the query | No direct equivalent | **Untranslatable** |

### Filter Argument

The third argument to `group_aggregate` controls how filters are applied:

| ThoughtSpot filter | Behavior | Status |
|---|---|---|
| `query_filters()` | Accepts all filters from the query | Translatable — no filter needed in semantic view (Cortex applies query filters) |
| `{}` | No filters — ignores all query filters | **Untranslatable** — semantic view metrics cannot suppress query filters |
| `{region='east'}` | Hardcoded always-applied filter | **Untranslatable** — semantic view metrics cannot contain filter clauses |
| `query_filters() + {region='east'}` | All query filters + always apply region='east' | **Untranslatable** — no hardcoded filter support |
| `query_filters() - {region, country}` | All query filters minus filters on region/country | **Untranslatable** — cannot selectively ignore filters |
| `{region}` | Only accept filters for region, ignore others | **Untranslatable** — cannot selectively accept filters |

Only `query_filters()` (pass-through all filters) is translatable. All other filter
patterns require filter logic that semantic view metrics do not support.

### Translatable LOD Patterns

**Translation rules for standalone `group_{func}`:**

| ThoughtSpot function | Semantic view metric |
|---|---|
| `group_sum(measure, attr1, attr2)` | `SUM(base_metric) OVER (PARTITION BY attr1, attr2)` |
| `group_average(measure, attr1)` | `AVG(base_metric) OVER (PARTITION BY attr1)` |
| `group_count(measure, attr1)` | `COUNT(base_metric) OVER (PARTITION BY attr1)` |
| `group_max(measure, attr1)` | `MAX(base_metric) OVER (PARTITION BY attr1)` |
| `group_min(measure, attr1)` | `MIN(base_metric) OVER (PARTITION BY attr1)` |
| `group_stddev(measure, attr1)` | `STDDEV(base_metric) OVER (PARTITION BY attr1)` |
| `group_variance(measure, attr1)` | `VARIANCE(base_metric) OVER (PARTITION BY attr1)` |
| `group_unique_count(measure, attr1)` | `COUNT(DISTINCT base_metric) OVER (PARTITION BY attr1)` |

**Translation rules for `group_aggregate` with translatable grouping:**

| Grouping | Semantic view metric |
|---|---|
| `group_aggregate(sum(m), {}, ...)` | `SUM(base_metric) OVER ()` |
| `group_aggregate(sum(m), {attr1, attr2}, ...)` | `SUM(base_metric) OVER (PARTITION BY attr1, attr2)` |
| `group_aggregate(sum(m), query_groups()-{attr1}, ...)` | `SUM(base_metric) OVER (PARTITION BY EXCLUDING attr1)` |
| `group_aggregate(sum(m), query_groups(), ...)` | No window function — just `SUM(base_metric)` as a regular metric |

**Example — `group_sum(Quantity, Category Name)`:**

```yaml
metrics:
  - name: total_quantity
    expr: SUM(order_detail.QUANTITY)
  - name: category_total_quantity
    expr: "SUM(order_detail.total_quantity) OVER (PARTITION BY categories.category_name)"
```

**Example — `group_aggregate(sum(Quantity), {}, query_filters())` (grand total):**

```yaml
metrics:
  - name: total_quantity
    expr: SUM(order_detail.QUANTITY)
  - name: grand_total_quantity
    expr: SUM(order_detail.total_quantity) OVER ()
```

**Reverse translation (semantic view → ThoughtSpot):**

| Semantic view pattern | ThoughtSpot |
|---|---|
| `SUM(metric) OVER ()` | `group_sum(measure)` with `{}` grouping |
| `SUM(metric) OVER (PARTITION BY dim1, dim2)` | `group_sum(measure, dim1, dim2)` |
| `SUM(metric) OVER (PARTITION BY EXCLUDING dim1)` | `group_aggregate(sum(measure), query_groups()-{dim1})` |

### Common LOD Pattern: Percentage Contribution

A frequent use case is computing a ratio where the denominator is at a coarser grain
(e.g. product sales as a % of category sales).

**ThoughtSpot formula:**
```
safe_divide(sum(Quantity), group_sum(Quantity, Category Name))
```

**Semantic view translation:**

```yaml
metrics:
  - name: total_quantity
    expr: SUM(order_detail.QUANTITY)
  - name: category_total_quantity
    expr: "SUM(order_detail.total_quantity) OVER (PARTITION BY categories.category_name)"
  - name: pct_of_category
    expr: "DIV0(order_detail.total_quantity, SUM(order_detail.total_quantity) OVER (PARTITION BY categories.category_name))"
```

**For dynamic exclusion (% of total excluding the current dimension):**

ThoughtSpot: `safe_divide(sum(Quantity), group_aggregate(sum(Quantity), query_groups()-{Product Name}))`

```yaml
metrics:
  - name: pct_contribution
    expr: "DIV0(order_detail.total_quantity, SUM(order_detail.total_quantity) OVER (PARTITION BY EXCLUDING products.product_name))"
```

### Outer `sum()` wrapping `group_aggregate(..., query_filters())`

When `sum()` wraps a `group_aggregate` that uses `query_filters()` as its filter
argument, the entire expression simplifies to a plain `SUM(m)` metric.

**Why this works:** In ThoughtSpot, `group_aggregate` requires explicit grain
instructions because ThoughtSpot must know at what level to compute the sub-aggregation.
In a semantic view, **grain is always determined at query time by Cortex Analyst** —
the grouping is implicit in whatever dimensions are in the query. `query_filters()` is
also redundant — Cortex Analyst applies all active query filters automatically.

The outer `sum()` of the category-level total collapses to `SUM(m)` because Cortex
Analyst computes the metric at the correct grain for the current query context.

| ThoughtSpot | Semantic view | Note |
|---|---|---|
| `sum(group_aggregate(sum(m), {attr}, query_filters()))` | `SUM(m)` | Grain is implicit — Cortex handles it at query time |
| `sum(group_aggregate(sum(m), query_groups(), query_filters()))` | `SUM(m)` | `query_groups()` is already a plain metric |
| `group_sum(m, attr)` used as a standalone metric (not in ratio) | `SUM(m)` | Same simplification applies |

**Example — `sum(group_aggregate(sum(Quantity), {Category Name}, query_filters()))`:**

```yaml
metrics:
  - name: category_quantity
    expr: SUM(dm_order_detail.QUANTITY)
```

**Transitive dependencies:** If a second formula referenced this one as untranslatable,
it can now also be translated. When you resolve a previously-untranslatable formula,
revisit any formula that was omitted due to a transitive dependency on it.

**Two cases — do not confuse them:**

**Case A — numerator and denominator are different metrics** (safe to inline):

ThoughtSpot: `safe_divide(sum(Sales Amount), sum(group_aggregate(sum(Quantity), {Category Name}, query_filters())))`

After resolving `[Category Quantity]` → `SUM(QUANTITY)`, inline and translate:

```yaml
metrics:
  - name: category_quantity
    expr: SUM(dm_order_detail.QUANTITY)
  - name: sales_per_category_quantity
    expr: DIV0(SUM(dm_order_detail.AMOUNT), SUM(dm_order_detail.QUANTITY))
```

**Case B — same metric at different grains (contribution ratio):**

ThoughtSpot: `safe_divide(sum(Quantity), [Category Quantity])`
where `[Category Quantity]` = `sum(group_aggregate(sum(Quantity), {Category Name}, query_filters()))`

**Do NOT inline** — `[Category Quantity]` simplifies to `SUM(QUANTITY)`, so inlining
produces `DIV0(SUM(QUANTITY), SUM(QUANTITY))` which is always 1.0. The LOD grain is
lost. Instead, treat this as a **Percentage Contribution** pattern (see above) and
use the PARTITION BY window function:

```yaml
metrics:
  - name: product_to_category_ratio
    expr: "DIV0(SUM(dm_order_detail.QUANTITY), SUM(dm_order_detail.QUANTITY) OVER (PARTITION BY categories.CATEGORY_NAME))"
```

**How to identify Case B:** The formula references `[NamedMetric]` where that metric
is `group_aggregate` of the **same underlying column** as the numerator. In that
situation, the named reference must be re-expanded as a window function, not inlined.

**This simplification applies only when the outer aggregate is `sum()`.**  
`max(group_aggregate(...))`, `count(group_aggregate(...))`, etc. are still untranslatable
— the maximum or count of category-level totals is semantically different from
`MAX(m)` or `COUNT(m)`, so the simplification does not hold.

---

### Untranslatable LOD Patterns

| Pattern | Reason |
|---|---|
| `max/min/avg/count(group_aggregate(...))` | Max/count of category totals ≠ max/count of rows — simplification does not hold (unlike `sum`) |
| `group_aggregate(...)` with explicit filter | Semantic view metrics cannot contain filter clauses |
| `group_aggregate(...)` with `query_groups() + {attr}` | No conditional include in semantic views |
| `group_aggregate(...)` with `query_groups(attr1, attr2)` | No optional include in semantic views |

Log entry for untranslatable patterns:
```
| {column_name} | `{original_expr}` | ⚠ LOD function | OMITTED — {reason} |
```

---

## Semi-Additive Functions

ThoughtSpot syntax: `last_value(agg(measure), grouping, {date_column})`
and `first_value(agg(measure), grouping, {date_column})`

These functions compute snapshot metrics — values that should not be summed across
time periods (e.g. account balances, inventory levels, headcount). The three arguments
follow the same pattern as `group_aggregate`:

1. **Aggregation** — the measure aggregate (e.g. `sum(Quantity)`)
2. **Grouping** — same syntax as `group_aggregate` (`query_groups()`, `{attr}`, etc.)
3. **Date column** — `{date_col}` — the time dimension that controls snapshot selection

**How it works in ThoughtSpot SQL:**

1. Groups by date (at query grain) + any other query dimensions
2. Applies `LAST_VALUE(agg) OVER (PARTITION BY [coarser_date, other_dims] ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)` to pick the last date's value within each partition
3. Re-aggregates at the query grain

**Snowflake Semantic View equivalent — `non_additive_dimensions`:**

Semantic views support non-additive measures via the `non_additive_dimensions` field
on a metric entry. This tells Snowflake to take the last snapshot instead of summing
across the specified time dimensions.

**Do not** write `NON ADDITIVE BY` inline in the `expr` string — the YAML parser
rejects it. Always use `non_additive_dimensions` as a separate structured field.

### `last_value` with `query_groups()` — Translatable

| ThoughtSpot | Semantic view |
|---|---|
| `last_value(sum(measure), query_groups(), {date_col})` | `expr: SUM(measure)` + `non_additive_dimensions: [date_dim.date_col]` |

The `non_additive_dimensions` list should reference the time dimension(s) derived from
the date column in the ThoughtSpot formula.

**Example — `last_value(sum(Quantity), query_groups(), {tableDate})`:**

```yaml
metrics:
  - name: quantity_last_value
    expr: SUM(order_detail.QUANTITY)
    non_additive_dimensions:
      - date_dim.date_value
```

**Reverse translation (semantic view → ThoughtSpot):**

```
expr: SUM(measure) + non_additive_dimensions: [dim]
→ last_value(sum(measure), query_groups(), {date_column})
```

Identify the date column from the dimension(s) listed in `non_additive_dimensions`.

### Untranslatable Semi-Additive Patterns

| Pattern | Reason |
|---|---|
| `first_value(agg(measure), grouping, {date_col})` | `NON ADDITIVE BY` only supports last-value semantics |
| `agg(last_value(...))` e.g. `max(last_value(...))` | Cannot nest/re-aggregate a `NON ADDITIVE BY` metric |
| `agg(first_value(...))` e.g. `max(first_value(...))` | `first_value` is untranslatable; nesting compounds it |
| `last_value(...)` with non-`query_groups()` grouping | Same grouping limitations as `group_aggregate` |
| `last_value_in_period(...)` | Period-scoped: returns the last snapshot value only if the partition's last date matches the overall period's last date; returns NULL otherwise. This date-completeness check has no semantic view equivalent. |
| `first_value_in_period(...)` | Period-scoped: same completeness check but for the first date in the period. No semantic view equivalent. |

Log entry for untranslatable patterns:
```
| {column_name} | `{original_expr}` | ⚠ Semi-additive | OMITTED — {reason} |
```

---

## Untranslatable Patterns

**Do not emit these columns in the YAML output.** Omit the field entirely and add a
row to the Formula Translation Log in the Unmapped Properties Report (see Step 10).
The formats below are for the log entry — they must never appear as the `expr` value
in the generated YAML.

### Parameter References

A `[word]` reference with no `::` that matches a model `parameter` name cannot be
resolved to a static SQL expression.

```yaml
# Example — formula using parameter "locale":
expr: '[locale]'

# Example — formula using parameter "Date" as a conditional:
expr: if ( [Date] = 'order date' ) then [DM_ORDER::ORDER_DATE] else [DM_ORDER::SHIPPED_DATE]
```

Log entry (Unmapped Properties Report row):
```
| {column_name} | `{original_expr}` | ⚠ Parameter reference | OMITTED — `[{param_name}]` is a runtime parameter with no Snowflake equivalent. Suggestion: create concrete columns or use a session variable. |
```

---

## Formula Translation Record (for Unmapped Report)

For every formula processed, include a row in the Unmapped Properties Report:

| Column Name | Original ThoughtSpot Expression | Status | Result |
|---|---|---|---|
| Days to Ship | `diff_days([SHIPPED_DATE], [ORDER_DATE])` | Translated | `DATEDIFF('day', DM_ORDER.ORDER_DATE, DM_ORDER.SHIPPED_DATE)` |
| Employee Name | `concat([FIRST_NAME], ' ', [LAST_NAME])` | Translated | `CONCAT(DM_EMPLOYEE.FIRST_NAME, ' ', DM_EMPLOYEE.LAST_NAME)` |
| Product List | `sql_string_aggregate_op("listagg({0},...)", [PRODUCT_NAME])` | Translated | `LISTAGG(products.PRODUCT_NAME, ...)` |
| Language | `[locale]` | ⚠ Parameter reference | OMITTED |
| Master Date | `if ([Date] = 'order date') then ...` | ⚠ Parameter reference | OMITTED |