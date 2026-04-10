# Formula Translation Reference

ThoughtSpot formula → Snowflake SQL translation rules. Consult during Step 9.

This reference is intentionally kept separate so it can be reused by other skills
(e.g. ThoughtSpot → Databricks, ThoughtSpot → BigQuery) with target-specific overrides.

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

## Translatable Functions

| ThoughtSpot formula | Snowflake SQL equivalent |
|---|---|
| `sum ( [x] )` | `SUM(x)` |
| `count ( [x] )` | `COUNT(x)` |
| `count_distinct ( [x] )` | `COUNT(DISTINCT x)` |
| `unique count ( [x] )` | `COUNT(DISTINCT x)` |
| `average ( [x] )` | `AVG(x)` |
| `min ( [x] )` | `MIN(x)` |
| `max ( [x] )` | `MAX(x)` |
| `if [cond] then [a] else [b]` | `CASE WHEN cond THEN a ELSE b END` |
| `if [c1] then [a] else if [c2] then [b] else [c]` | `CASE WHEN c1 THEN a WHEN c2 THEN b ELSE c END` |
| `isnull ( [x] )` | `x IS NULL` |
| `isnotnull ( [x] )` | `x IS NOT NULL` |
| `not ( [x] )` | `NOT x` |
| `safe_divide ( [a] , [b] )` | `(a) / NULLIF(b, 0)` |
| `concat ( [a] , [b] )` | `CONCAT(a, b)` |
| `concat ( [a] , ' ' , [b] )` | `CONCAT(a, ' ', b)` *(supports N args)* |
| `substr ( [x] , [start] , [len] )` | `SUBSTR(x, start, len)` |
| `strlen ( [x] )` | `LENGTH(x)` |
| `upper ( [x] )` | `UPPER(x)` |
| `lower ( [x] )` | `LOWER(x)` |
| `to_integer ( [x] )` | `CAST(x AS INTEGER)` |
| `to_double ( [x] )` | `CAST(x AS DOUBLE)` |
| `to_string ( [x] )` | `CAST(x AS VARCHAR)` |
| `round ( [x] , [n] )` | `ROUND(x, n)` |
| `floor ( [x] )` | `FLOOR(x)` |
| `ceil ( [x] )` | `CEIL(x)` |
| `abs ( [x] )` | `ABS(x)` |
| `power ( [x] , [n] )` | `POWER(x, n)` |
| `year ( [date] )` | `YEAR(date)` |
| `month ( [date] )` | `MONTH(date)` |
| `day ( [date] )` | `DAY(date)` |
| `hour ( [date] )` | `HOUR(date)` |
| `date_diff ( [a] , [b] )` | `DATEDIFF('day', b, a)` |
| `diff_days ( [end] , [start] )` | `DATEDIFF('day', start, end)` |
| `diff_months ( [end] , [start] )` | `DATEDIFF('month', start, end)` |
| `diff_years ( [end] , [start] )` | `DATEDIFF('year', start, end)` |
| `today ()` | `CURRENT_DATE()` |
| `now ()` | `CURRENT_TIMESTAMP()` |

---

## Nested Column References

If a formula references another model column by display name (e.g. `[Revenue]`):

1. Look up that column name in the model's column list.
2. Substitute its already-translated `expr` value inline.
3. Apply recursively up to **3 levels deep**.
4. If circular or deeper than 3 levels, emit a `-- TODO` comment.

---

## Untranslatable Patterns

Replace with `-- TODO` comment and add to the Unmapped Properties Report.

### Parameter References

A `[word]` reference with no `::` that matches a model `parameter` name cannot be
resolved to a static SQL expression.

```yaml
# Example — formula using parameter "locale":
expr: '[locale]'

# Example — formula using parameter "Date" as a conditional:
expr: if ( [Date] = 'order date' ) then [DM_ORDER::ORDER_DATE] else [DM_ORDER::SHIPPED_DATE]
```

Output format:
```
-- TODO: formula uses parameter '[{param_name}]' — no Snowflake equivalent.
-- Original ThoughtSpot formula: {original_expr}
-- Suggestion: create separate concrete columns, or use a Snowflake session variable.
```

### `sql_string_op`

Embeds a raw SQL template with positional `{0}`, `{1}` substitution. ThoughtSpot-specific.

```yaml
expr: "sql_string_op ( 'get({0},{1}) :: text' , [DM_LOCALE_COUNTRY::COUNTRY_NAME] , [locale] )"
```

Common patterns and their Snowflake equivalents:
- JSON path extraction → `GET_PATH(col, 'key')` or `col:key::text`
- Type casting → `CAST(col AS type)` or `col::type`
- Other → inspect the template string and rewrite manually

Output format:
```
-- TODO: sql_string_op requires manual translation.
-- Original ThoughtSpot formula: {original_expr}
-- Template: {template_string}
-- Args: {arg1}, {arg2}
```

### Time Intelligence Functions

These have no direct SQL equivalent and require window function rewrites.

| ThoughtSpot function | Intended behaviour | Snowflake window function approach |
|---|---|---|
| `growth_rate([x], n period)` | Period-over-period % change | `(x - LAG(x) OVER (...)) / LAG(x) OVER (...)` |
| `period_ago([x], n period)` | Value from n periods ago | `LAG(x, n) OVER (ORDER BY date)` |
| `last_period([x])` | Previous period value | `LAG(x, 1) OVER (ORDER BY date)` |
| `vs_period([x])` | Difference vs prior period | `x - LAG(x, 1) OVER (ORDER BY date)` |
| `moving_average([x], n, m)` | Rolling average | `AVG(x) OVER (ROWS BETWEEN n PRECEDING AND m FOLLOWING)` |
| `moving_sum([x], n, m)` | Rolling sum | `SUM(x) OVER (ROWS BETWEEN n PRECEDING AND m FOLLOWING)` |
| `moving_max` / `moving_min` | Rolling max/min | `MAX/MIN(x) OVER (ROWS BETWEEN ...)` |
| `cumulative_sum([x])` | Running total | `SUM(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |
| `cumulative_max` / `min` | Running max/min | `MAX/MIN(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |
| `rank()` | Rank within group | `RANK() OVER (PARTITION BY ... ORDER BY ...)` |
| `rank_percentile()` | Percentile rank | `PERCENT_RANK() OVER (...)` |
| `running_count([x])` | Running count | `COUNT(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |

Output format:
```
-- TODO: ThoughtSpot time intelligence function '{function_name}' requires manual translation.
-- Suggested Snowflake approach: {approach from table above}
-- Original ThoughtSpot formula: {original_expr}
```

---

## Formula Translation Record (for Unmapped Report)

For every formula processed, include a row in the Unmapped Properties Report:

| Column Name | Original ThoughtSpot Expression | Status | Snowflake Output |
|---|---|---|---|
| Days to Ship | `diff_days([SHIPPED_DATE], [ORDER_DATE])` | Translated | `DATEDIFF('day', DM_ORDER.ORDER_DATE, DM_ORDER.SHIPPED_DATE)` |
| Employee Name | `concat([FIRST_NAME], ' ', [LAST_NAME])` | Translated | `CONCAT(DM_EMPLOYEE.FIRST_NAME, ' ', DM_EMPLOYEE.LAST_NAME)` |
| Language | `[locale]` | ⚠ Parameter reference | `-- TODO` |
| Master Date | `if ([Date] = 'order date') then ...` | ⚠ Parameter reference | `-- TODO` |
| Locale Country | `sql_string_op(...)` | ⚠ sql_string_op | `-- TODO` |
