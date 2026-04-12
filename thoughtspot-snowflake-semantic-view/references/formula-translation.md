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
4. If circular or deeper than 3 levels, **omit the column entirely** and log it in the Formula Translation Log.

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

### `sql_string_op`

Embeds a raw SQL template with positional `{0}`, `{1}` substitution. ThoughtSpot-specific.

```yaml
expr: "sql_string_op ( 'get({0},{1}) :: text' , [DM_LOCALE_COUNTRY::COUNTRY_NAME] , [locale] )"
```

Common patterns and their Snowflake equivalents:
- JSON path extraction → `GET_PATH(col, 'key')` or `col:key::text`
- Type casting → `CAST(col AS type)` or `col::type`
- Other → inspect the template string and rewrite manually

Log entry (Unmapped Properties Report row):
```
| {column_name} | `{original_expr}` | ⚠ sql_string_op | OMITTED — requires manual translation. Template: `{template_string}`. Args: `{arg1}`, `{arg2}`. |
```

### Window and Analytical Functions

These are valid ThoughtSpot aggregate functions. They are untranslatable to a Snowflake
Semantic View `metrics` entry because the `expr` field requires a plain SQL aggregate
(`SUM`, `COUNT`, `AVG`, etc.) — window functions cannot be used there. Re-implement by
creating a Snowflake view with the window calculation pre-computed, then point the
semantic view's `base_table` at that view.

| ThoughtSpot function | Snowflake window function approach |
|---|---|
| `moving_average([x], n, m)` | `AVG(x) OVER (ROWS BETWEEN n PRECEDING AND m FOLLOWING)` |
| `moving_sum([x], n, m)` | `SUM(x) OVER (ROWS BETWEEN n PRECEDING AND m FOLLOWING)` |
| `moving_max([x], n, m)` | `MAX(x) OVER (ROWS BETWEEN n PRECEDING AND m FOLLOWING)` |
| `moving_min([x], n, m)` | `MIN(x) OVER (ROWS BETWEEN n PRECEDING AND m FOLLOWING)` |
| `cumulative_sum([x])` | `SUM(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |
| `cumulative_average([x])` | `AVG(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |
| `cumulative_max([x])` | `MAX(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |
| `cumulative_min([x])` | `MIN(x) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)` |
| `rank()` | `RANK() OVER (PARTITION BY ... ORDER BY ...)` |
| `rank_percentile()` | `PERCENT_RANK() OVER (...)` |

Log entry (Unmapped Properties Report row):
```
| {column_name} | `{original_expr}` | ⚠ Window function | OMITTED — `{function_name}` requires a window function; re-implement as a calculated column in a Snowflake view. |
```

---

### Level of Detail (LOD) Functions

ThoughtSpot LOD functions (`group_aggregate` and the `group_*` shorthand family) compute
sub-aggregations at a fixed granularity by generating a SQL CTE. There is no equivalent
in Snowflake Semantic Views — the `expr` field cannot contain a subquery or CTE.
Re-implement by creating a Snowflake view with the CTE built in, then point the semantic
view's `base_table` at that view.

| ThoughtSpot function | Notes |
|---|---|
| `group_aggregate(agg(col), grouping, filter)` | Primary LOD function — generates a SQL CTE |
| `group_sum([x], ...)` | Shorthand for `group_aggregate(sum(...), ...)` |
| `group_average([x], ...)` | Shorthand for `group_aggregate(average(...), ...)` |
| `group_count([x], ...)` | Shorthand for `group_aggregate(count(...), ...)` |
| `group_max([x], ...)` | Shorthand for `group_aggregate(max(...), ...)` |
| `group_min([x], ...)` | Shorthand for `group_aggregate(min(...), ...)` |
| `group_stddev([x], ...)` | Shorthand for `group_aggregate(stddev(...), ...)` |
| `group_variance([x], ...)` | Shorthand for `group_aggregate(variance(...), ...)` |
| `group_unique_count([x], ...)` | Shorthand for `group_aggregate(unique count(...), ...)` |

Log entry (Unmapped Properties Report row):
```
| {column_name} | `{original_expr}` | ⚠ LOD function | OMITTED — `{function_name}` generates a CTE subquery; re-implement as a Snowflake view. |
```

---

### Semi-Additive Functions

`first_value` and `last_value` are used for snapshot metrics (account balances, inventory,
headcount) — measures that aggregate across most dimensions but require special handling
for the time dimension. They use SQL window functions internally and cannot be expressed
as a plain `expr` in a Snowflake Semantic View metric. Re-implement by creating a
Snowflake view with the window function pre-computed.

| ThoughtSpot function | Snowflake window function approach |
|---|---|
| `last_value([x], {grouping}, {filter})` | `LAST_VALUE(x) IGNORE NULLS OVER (PARTITION BY ... ORDER BY date)` |
| `first_value([x], {grouping}, {filter})` | `FIRST_VALUE(x) IGNORE NULLS OVER (PARTITION BY ... ORDER BY date)` |
| `last_value_in_period([x], ...)` | `LAST_VALUE(x) IGNORE NULLS OVER (PARTITION BY ... ORDER BY date)` scoped to period |
| `first_value_in_period([x], ...)` | `FIRST_VALUE(x) IGNORE NULLS OVER (PARTITION BY ... ORDER BY date)` scoped to period |

Log entry (Unmapped Properties Report row):
```
| {column_name} | `{original_expr}` | ⚠ Semi-additive | OMITTED — `{function_name}` uses a window function; re-implement as a calculated column in a Snowflake view. |
```

---

## Formula Translation Record (for Unmapped Report)

For every formula processed, include a row in the Unmapped Properties Report:

| Column Name | Original ThoughtSpot Expression | Status | Result |
|---|---|---|---|
| Days to Ship | `diff_days([SHIPPED_DATE], [ORDER_DATE])` | Translated | `DATEDIFF('day', DM_ORDER.ORDER_DATE, DM_ORDER.SHIPPED_DATE)` |
| Employee Name | `concat([FIRST_NAME], ' ', [LAST_NAME])` | Translated | `CONCAT(DM_EMPLOYEE.FIRST_NAME, ' ', DM_EMPLOYEE.LAST_NAME)` |
| Language | `[locale]` | ⚠ Parameter reference | OMITTED |
| Master Date | `if ([Date] = 'order date') then ...` | ⚠ Parameter reference | OMITTED |
| Locale Country | `sql_string_op(...)` | ⚠ sql_string_op | OMITTED |
