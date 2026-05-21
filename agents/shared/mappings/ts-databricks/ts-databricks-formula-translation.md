# Formula Translation Reference — Databricks

Bidirectional translation rules between ThoughtSpot formulas and **Databricks SQL**
Metric View expressions. Use **TS → Databricks** when converting ThoughtSpot models
to Metric Views (Step 9) and **Databricks → TS** when converting Metric Views to
ThoughtSpot models.

> **Platform-specific:** This reference targets Databricks SQL syntax. For Snowflake,
> see `../ts-snowflake/ts-snowflake-formula-translation.md`.

> **ThoughtSpot formula syntax:** For complete ThoughtSpot formula syntax reference,
> see **[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md)**.

---

## Translation Decision Flowchart

```
Formula contains...
├── [word] with no ::           → Parameter References (untranslatable)
├── sql_*_op(...)               → SQL Pass-Through Functions
├── cumulative_*                → Window: Cumulative Functions
├── moving_*                    → Window: Moving Functions
├── rank( or rank_percentile(   → Window: Rank Functions
├── group_* or group_aggregate  → Level of Detail (LOD) Functions
├── last_value( or first_value( → Semi-Additive Functions (limited support)
├── [TABLE::COL] references     → Resolve via Column Reference Syntax
├── [other_formula_name]        → Resolve via Nested Column References
└── standard function(args)     → Scalar Functions
```

---

## Column Reference Syntax

**ThoughtSpot Model TML** references:
```
[DM_ORDER::FREIGHT]
```
Resolution:
1. `DM_ORDER` is the table name
2. `FREIGHT` is the column name
3. In v0.1 MV (single source): output `FREIGHT` (no prefix)
4. In v1.1 MV (multi-source): output `dm_order.FREIGHT`

---

## Scalar Functions

### String Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `concat(a, b)` | `CONCAT(a, b)` | |
| `strlen(s)` | `LENGTH(s)` | |
| `strpos(s, sub)` | `LOCATE(sub, s)` | Argument order reversed |
| `substr(s, start, len)` | `SUBSTRING(s, start, len)` | |
| `lower(s)` | `LOWER(s)` | |
| `upper(s)` | `UPPER(s)` | |
| `trim(s)` | `TRIM(s)` | |
| `ltrim(s)` | `LTRIM(s)` | |
| `rtrim(s)` | `RTRIM(s)` | |
| `replace(s, old, new)` | `REPLACE(s, old, new)` | |
| `contains(s, sub)` | `CONTAINS(s, sub)` | |
| `starts_with(s, prefix)` | `STARTSWITH(s, prefix)` | |
| `left(s, n)` | `LEFT(s, n)` | |
| `right(s, n)` | `RIGHT(s, n)` | |
| `lpad(s, n, pad)` | `LPAD(s, n, pad)` | |
| `rpad(s, n, pad)` | `RPAD(s, n, pad)` | |
| `reverse(s)` | `REVERSE(s)` | |
| `repeat(s, n)` | `REPEAT(s, n)` | |

### Numeric Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `abs(x)` | `ABS(x)` | |
| `ceil(x)` | `CEIL(x)` | |
| `floor(x)` | `FLOOR(x)` | |
| `round(x, n)` | `ROUND(x, n)` | |
| `mod(x, y)` | `MOD(x, y)` | |
| `power(x, y)` | `POWER(x, y)` | |
| `sqrt(x)` | `SQRT(x)` | |
| `ln(x)` | `LN(x)` | |
| `log2(x)` | `LOG2(x)` | |
| `log10(x)` | `LOG10(x)` | |
| `safe_divide(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` | No `DIV0` in Databricks |
| `if_null(x, default)` | `COALESCE(x, default)` | |
| `zero_if_null(x)` | `COALESCE(x, 0)` | No `ZEROIFNULL` in Databricks |
| `null_if_zero(x)` | `NULLIF(x, 0)` | |

### Date / Time Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `today()` | `CURRENT_DATE()` | |
| `now()` | `CURRENT_TIMESTAMP()` | |
| `date(ts)` | `DATE(ts)` or `date_trunc('day', ts)` | |
| `year(d)` | `YEAR(d)` | |
| `month(d)` | `MONTH(d)` | |
| `day_of_month(d)` | `DAY(d)` | |
| `day_of_week(d)` | `DAYOFWEEK(d)` | TS: 1=Mon; Databricks: 1=Sun — adjust |
| `day_of_year(d)` | `DAYOFYEAR(d)` | |
| `hour(ts)` | `HOUR(ts)` | |
| `minute(ts)` | `MINUTE(ts)` | |
| `second(ts)` | `SECOND(ts)` | |
| `quarter(d)` | `QUARTER(d)` | |
| `week_of_year(d)` | `WEEKOFYEAR(d)` | |
| `start_of_month(d)` | `date_trunc('month', d)` | |
| `start_of_quarter(d)` | `date_trunc('quarter', d)` | |
| `start_of_year(d)` | `date_trunc('year', d)` | |
| `start_of_week(d)` | `date_trunc('week', d)` | Week start day may differ |
| `diff_days(start, end)` | `DATEDIFF(end, start)` | Arg order reversed; Databricks `DATEDIFF` returns days only |
| `diff_months(start, end)` | `MONTHS_BETWEEN(end, start)` | Returns fractional months |
| `add_days(d, n)` | `DATE_ADD(d, n)` | |
| `add_months(d, n)` | `ADD_MONTHS(d, n)` | |
| `date_format(d, fmt)` | `DATE_FORMAT(d, fmt)` | Format strings may differ slightly |

### Conditional / Logic Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `if(cond, then, else)` | `CASE WHEN cond THEN then ELSE else END` | Or `IF(cond, then, else)` |
| `ifnull(x, default)` | `COALESCE(x, default)` | |
| `isnull(x)` | `x IS NULL` | |
| `not(x)` | `NOT x` | |
| `in(x, a, b, c)` | `x IN (a, b, c)` | |
| `between(x, lo, hi)` | `x BETWEEN lo AND hi` | |
| `greatest(a, b, ...)` | `GREATEST(a, b, ...)` | |
| `least(a, b, ...)` | `LEAST(a, b, ...)` | |

---

## Aggregate Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `sum(x)` | `SUM(x)` | |
| `average(x)` | `AVG(x)` | |
| `count(x)` | `COUNT(x)` | |
| `unique count(x)` | `COUNT(DISTINCT x)` | |
| `min(x)` | `MIN(x)` | |
| `max(x)` | `MAX(x)` | |
| `stddev(x)` | `STDDEV(x)` | |
| `variance(x)` | `VARIANCE(x)` | |

---

## SQL Pass-Through Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `sql_int_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_bool_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_str_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_number_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_date_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_datetime_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |

The inner expression is already valid SQL. Strip the wrapper function and emit
the contents. If the SQL uses Snowflake-specific syntax, translate it to
Databricks SQL equivalents.

---

## Window Functions

### Cumulative Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `cumulative_sum(measure)` | `SUM(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` | Requires a sort column |
| `cumulative_average(measure)` | `AVG(measure) OVER (ORDER BY {sort_col} ROWS UNBOUNDED PRECEDING)` | |
| `cumulative_max(measure)` | `MAX(measure) OVER (ORDER BY {sort_col} ROWS UNBOUNDED PRECEDING)` | |
| `cumulative_min(measure)` | `MIN(measure) OVER (ORDER BY {sort_col} ROWS UNBOUNDED PRECEDING)` | |

### Moving Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `moving_sum(measure, window)` | `SUM(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {window-1} PRECEDING AND CURRENT ROW)` | |
| `moving_average(measure, window)` | `AVG(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {window-1} PRECEDING AND CURRENT ROW)` | |
| `moving_max(measure, window)` | `MAX(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {window-1} PRECEDING AND CURRENT ROW)` | |
| `moving_min(measure, window)` | `MIN(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {window-1} PRECEDING AND CURRENT ROW)` | |

### Rank Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `rank(expr)` | `RANK() OVER (ORDER BY expr)` | |
| `rank(expr, 'asc')` | `RANK() OVER (ORDER BY expr ASC)` | |
| `rank(expr, 'desc')` | `RANK() OVER (ORDER BY expr DESC)` | |

---

## Level of Detail (LOD) Functions

LOD functions have limited support in Metric View `expr` fields because MVs
pre-aggregate at query time. Simple LOD patterns can sometimes be expressed
as nested aggregates or subqueries.

| ThoughtSpot | Databricks SQL | Translatable? |
|---|---|---|
| `group_sum(measure, group_by)` | Subquery or nested aggregate | Limited |
| `group_count(measure, group_by)` | Subquery or nested aggregate | Limited |
| `group_average(measure, group_by)` | Subquery or nested aggregate | Limited |
| `group_aggregate(...)` | Complex subquery | **Usually untranslatable** |

When untranslatable, omit the formula and log in the Unmapped Report.

---

## Semi-Additive Functions

| ThoughtSpot | Databricks SQL | Translatable? |
|---|---|---|
| `last_value(sum(m), query_groups(), {date})` | Complex window function | **Limited** |
| `first_value(sum(m), query_groups(), {date})` | Complex window function | **Limited** |
| `last_value_in_period(...)` | No equivalent | **Untranslatable** |
| `first_value_in_period(...)` | No equivalent | **Untranslatable** |

Semi-additive patterns are difficult to express in MV `expr` fields. Log in
the Unmapped Report when encountered.

---

## Untranslatable Patterns

These ThoughtSpot formula patterns cannot be translated to Databricks MV expressions:

| Pattern | Reason |
|---|---|
| Parameter references: `[Param]` (no `::`) | Runtime parameters don't exist in MVs |
| `last_value_in_period(...)` | No MV equivalent |
| `first_value_in_period(...)` | No MV equivalent |
| Complex `group_aggregate(...)` with custom `query_groups` | Cannot express in MV expr |
| Nested formula references beyond 3 levels | Complexity limit |
| Circular formula references | Cannot resolve |

When encountering untranslatable formulas:
1. Omit the column from the MV YAML
2. Log in the Unmapped Report with the original expression and reason

---

## Databricks → ThoughtSpot (Reverse Direction)

Common Databricks SQL patterns found in MV `expr` fields and their ThoughtSpot
formula equivalents:

| Databricks SQL (in MV expr) | ThoughtSpot formula |
|---|---|
| `date_trunc('day', col)` | `date(col)` |
| `date_trunc('month', col)` | `start_of_month(col)` |
| `date_trunc('quarter', col)` | `start_of_quarter(col)` |
| `date_trunc('year', col)` | `start_of_year(col)` |
| `CASE WHEN x THEN y WHEN z THEN w ELSE v END` | Nested `if(x, y, if(z, w, v))` |
| `COALESCE(a, b)` | `if(a != null, a, b)` |
| `CONCAT(a, ' ', b)` | `concat(a, ' ', b)` |
| `DATEDIFF(end, start)` | `diff_days(start, end)` — arg order reversed |
| `MONTHS_BETWEEN(end, start)` | `diff_months(start, end)` — arg order reversed |
| `YEAR(d)` | `year(d)` |
| `MONTH(d)` | `month(d)` |
| `DAYOFWEEK(d)` | `day_of_week(d)` — adjust: Databricks 1=Sun, TS 1=Mon |
| `ROUND(x, n)` | `round(x, n)` |
| `CAST(x AS type)` | Depends on target type; often implicit in TS |
| `x / NULLIF(y, 0)` | `safe_divide(x, y)` |
| `COALESCE(x / NULLIF(y, 0), 0)` | `safe_divide(x, y)` |
| `x IS NULL` | `isnull(x)` |
| `NOT expr` | `not(expr)` |
| `x IN (a, b, c)` | `in(x, a, b, c)` |
