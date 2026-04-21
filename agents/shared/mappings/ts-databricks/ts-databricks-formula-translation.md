# Formula Translation Reference — Unity Catalog (Databricks)

Translation rules between ThoughtSpot formulas and **Databricks SQL** expressions for
use in Unity Catalog Metric View `dimensions` and `measures`. Use **TS → Databricks**
when converting ThoughtSpot models to UC Metric Views (Step 9).

> **Platform-specific:** This reference targets Databricks SQL syntax and Unity Catalog
> Metric View constructs (`MEASURE()`, `window:`, `FILTER (WHERE ...)`). For Snowflake,
> see `mappings/ts-snowflake/ts-snowflake-formula-translation.md`.

> **ThoughtSpot formula syntax:** For complete ThoughtSpot formula syntax reference
> (column references, YAML encoding rules, LOD patterns, window functions,
> semi-additive functions, runtime parameters), see
> **[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md)**.

---

## YAML Expression Formatting

UC Metric View YAML supports multi-line YAML block scalars for `expr` values, but
**single-line strings are safest and most portable**. Use single-line format for all
translated expressions. If an expression is long, keep it on one line rather than splitting.

```yaml
# CORRECT — single-line string
expr: "try_divide(SUM(order_value), COUNT(DISTINCT customer_id))"

# ALSO VALID — multi-line block scalar (use only if single-line becomes unreadable)
expr: >-
  SUM(revenue) FILTER (WHERE channel = 'online')
```

---

## Translation Decision Flowchart

Use this to quickly determine which section to consult for a given ThoughtSpot formula:

```
Formula contains...
├── [word] with no ::           → Parameter References (untranslatable)
├── sql_*_op(...)               → SQL Pass-Through Functions
├── cumulative_*                → Semi-Additive / Window: use window: config
├── moving_*                    → Window Measures: use window: config
├── rank( or rank_percentile(   → Window Rank Functions (untranslatable in measures)
├── group_* or group_aggregate  → Level of Detail (LOD) — simplify to plain aggregate
├── last_value( or first_value( → Semi-Additive — use window: config
├── last_value_in_period(       → Untranslatable
├── first_value_in_period(      → Untranslatable
├── safe_divide(                → try_divide() or DIV0-equivalent
├── [TABLE::COL] references     → Resolve via Column Reference Syntax
├── [other_formula_name]        → Resolve via Nested Column References
└── standard function(args)     → Scalar Functions below
```

---

## Column Reference Syntax

ThoughtSpot formulas reference columns differently depending on TML format.

**Worksheet TML** — uses `table_path` IDs:
```
[fact_sales_1::sales_amount]
```
Resolution:
1. Look up `fact_sales_1` in the path → table map (Step 6)
2. Determine if `fact_sales_1` is the source table or a joined table
3. Source table: `physical_col_name` (bare) — e.g. `sales_amount`
4. Joined table: `join_alias.physical_col_name` — e.g. `customer.c_name`

**Model TML** — uses direct table names:
```
[DM_ORDER::FREIGHT]
```
Resolution:
1. `DM_ORDER` is the table reference (map to join alias using `to_snake()`)
2. Look up `FREIGHT` in Table TML columns → `db_column_name` = `FREIGHT`
3. Source table: `FREIGHT` (bare)
4. Joined table: `dm_order.FREIGHT`

**Important:** A reference like `[Date]` in a Model TML formula is likely a **parameter**
reference (single word, no `::` separator), not a column. See Untranslatable Patterns.

---

## Nested Column References

If a formula references another model column by display name (e.g. `[Revenue]`):

1. Look up that column name in the model's column list.
2. Substitute its already-translated `expr` value inline.
3. If the referenced column is a measure (aggregated), prefer `MEASURE(measure_name)` syntax
   over inlining the raw SQL to avoid double-aggregation.
4. Apply recursively up to **3 levels deep**.
5. If circular or deeper than 3 levels, **omit the column entirely** and log it.

**When to use `MEASURE()` vs inline substitution:**

| Referenced column type | Substitution method |
|---|---|
| Plain dimension (no aggregation) | Inline the `expr` directly |
| Measure defined in this view | Use `MEASURE(measure_name)` |
| Measure not yet defined | Define it first, then use `MEASURE()` |
| Untranslatable | Omit the referencing formula entirely |

---

## Aggregate Functions

These map 1:1 from ThoughtSpot to Databricks SQL.

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `sum([x])` | `SUM(x)` | |
| `count([x])` | `COUNT(x)` | |
| `count_distinct([x])` | `COUNT(DISTINCT x)` | |
| `unique count([x])` | `COUNT(DISTINCT x)` | synonym |
| `average([x])` | `AVG(x)` | |
| `min([x])` | `MIN(x)` | aggregate context only |
| `max([x])` | `MAX(x)` | aggregate context only |
| `median([x])` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x)` | verify Databricks support |
| `stddev([x])` | `STDDEV(x)` | |
| `variance([x])` | `VARIANCE(x)` | |

---

## Scalar Functions

### Math Functions

| ThoughtSpot | Databricks SQL |
|---|---|
| `abs([x])` | `ABS(x)` |
| `ceil([x])` | `CEIL(x)` |
| `floor([x])` | `FLOOR(x)` |
| `round([x], n)` | `ROUND(x, n)` |
| `power([x], n)` | `POWER(x, n)` |
| `sqrt([x])` | `SQRT(x)` |
| `log([x])` | `LOG(x)` |
| `ln([x])` | `LN(x)` |
| `exp([x])` | `EXP(x)` |
| `mod([x], n)` | `MOD(x, n)` |
| `safe_divide([a], [b])` | `try_divide(a, b)` — see Safe Division below |
| `greatest([x], [y])` | `GREATEST(x, y)` |
| `least([x], [y])` | `LEAST(x, y)` |

**Safe Division — `safe_divide`:**

ThoughtSpot `safe_divide(sum([Revenue]), sum([Quantity]))` translates to one of:

*Option 1 — inline (preferred when constituent measures are not separately exposed):*
```
try_divide(SUM(revenue_col), SUM(quantity_col))
```

*Option 2 — composed (preferred when constituent measures are already defined in the view):*
```
try_divide(MEASURE(total_revenue), MEASURE(total_quantity))
```

Use `try_divide(a, b)` — Databricks returns `NULL` when `b = 0` rather than raising
a divide-by-zero error. This is equivalent to ThoughtSpot's `safe_divide` behavior.

Fallback when `try_divide` is unavailable:
```sql
CASE WHEN b = 0 OR b IS NULL THEN NULL ELSE a / b END
```

### String Functions

| ThoughtSpot | Databricks SQL |
|---|---|
| `concat([a], [b])` | `CONCAT(a, b)` |
| `contains([s], 'sub')` | `s LIKE '%sub%'` or `CONTAINS(s, 'sub')` |
| `lower([s])` | `LOWER(s)` |
| `upper([s])` | `UPPER(s)` |
| `len([s])` | `LENGTH(s)` |
| `left([s], n)` | `LEFT(s, n)` |
| `right([s], n)` | `RIGHT(s, n)` |
| `substring([s], start, len)` | `SUBSTRING(s, start, len)` |
| `trim([s])` | `TRIM(s)` |
| `ltrim([s])` | `LTRIM(s)` |
| `rtrim([s])` | `RTRIM(s)` |
| `replace([s], 'old', 'new')` | `REPLACE(s, 'old', 'new')` |
| `str_position([s], 'sub')` | `INSTR(s, 'sub')` |
| `regexp_extract([s], 'pattern', idx)` | `REGEXP_EXTRACT(s, 'pattern', idx)` |
| `to_string([x])` | `CAST(x AS STRING)` |
| `to_integer([s])` | `CAST(s AS BIGINT)` |
| `to_double([s])` | `CAST(s AS DOUBLE)` |

### Date and Time Functions

| ThoughtSpot | Databricks SQL |
|---|---|
| `year([date])` | `YEAR(date)` |
| `month([date])` | `MONTH(date)` |
| `day([date])` | `DAY(date)` |
| `hour([ts])` | `HOUR(ts)` |
| `minute([ts])` | `MINUTE(ts)` |
| `day_of_week([date])` | `DAYOFWEEK(date)` |
| `day_of_year([date])` | `DAYOFYEAR(date)` |
| `week_of_year([date])` | `WEEKOFYEAR(date)` |
| `quarter([date])` | `QUARTER(date)` |
| `date_diff([unit], [d1], [d2])` | `DATEDIFF(d1, d2)` for days; unit support varies |
| `date_add([date], n)` | `DATEADD(DAY, n, date)` or `date + INTERVAL n DAY` |
| `now()` | `NOW()` or `CURRENT_TIMESTAMP()` |
| `today()` | `CURRENT_DATE()` |
| `date_trunc('month', [date])` | `DATE_TRUNC('MONTH', date)` |
| `to_date([s], 'fmt')` | `TO_DATE(s, 'fmt')` |

**`date_diff` — important:** ThoughtSpot signature is `date_diff('unit', start, end)`.
Databricks `DATEDIFF(end, start)` returns days only. For other units:
- Weeks: `DATEDIFF(end, start) / 7`
- Months: `MONTHS_BETWEEN(end, start)` (returns fractional months)
- Years: `DATEDIFF(end, start) / 365`

### Conditional Functions

| ThoughtSpot | Databricks SQL |
|---|---|
| `if([cond], [then], [else])` | `CASE WHEN cond THEN then ELSE else END` |
| `iferror([x], [default])` | `TRY(x)` or wrap in TRY_CAST |
| `if_null([x], [default])` | `COALESCE(x, default)` |
| `not_null([x])` | `x IS NOT NULL` |
| `is_null([x])` | `x IS NULL` |
| `in([x], val1, val2)` | `x IN (val1, val2)` |
| `not in([x], val1, val2)` | `x NOT IN (val1, val2)` |
| `between([x], lo, hi)` | `x BETWEEN lo AND hi` |
| `case(cond1, val1, cond2, val2, default)` | `CASE WHEN cond1 THEN val1 WHEN cond2 THEN val2 ELSE default END` |

---

## Level of Detail (LOD) Functions

### `group_aggregate` — simplification rule

ThoughtSpot `group_aggregate` often simplifies to a plain aggregate in UC.

**Pattern 1 — simplifies:**
```
sum(group_aggregate(sum([m]), query_groups(), query_filters()))
→ SUM(m_col)
```
Reasoning: `query_groups()` means "current GROUP BY", `query_filters()` means "current
WHERE". Combined with an outer `sum()`, this reduces to a standard aggregate.

**Pattern 2 — simplifies:**
```
sum(group_aggregate(sum([m]), {[attr]}, query_filters()))
→ SUM(m_col)
```
The inner `group_aggregate` fixes a grouping dimension, but `sum()` re-aggregates over
it. The result is the same as `SUM(m_col)`.

**Pattern 3 — contribution ratio (safe_divide variant):**
```
safe_divide(sum([m]), sum(group_aggregate(sum([m]), {[attr]}, query_filters())))
→ try_divide(MEASURE(m), SUM(m_col) OVER (PARTITION BY attr_col))
  OR use UC composed measures: try_divide(MEASURE(m_measure), MEASURE(total_m_by_attr))
```
This is a "percentage of total" pattern. Preferred UC approach: define the denominator
as a window measure or expose it as a separate measure and use `MEASURE()`.

**Pattern 4 — OMIT (untranslatable):**
```
group_aggregate(sum([m]), query_groups() + {[attr]}, query_filters())
group_aggregate(sum([m]), query_groups([attr1], [attr2]), query_filters())
max/min/avg(group_aggregate(...))  ← outer non-sum aggregate
```
These patterns require arbitrary grouping semantics that UC cannot express. Omit and log.

---

## Window / Moving Functions

UC Metric Views handle time-series aggregation via the `window:` config on measures,
not via SQL window function expressions. This is the key difference from Snowflake.

**When to use `window:` config:**
- `moving_average`, `moving_sum`, `moving_max`, `moving_min`, `moving_count`
- `cumulative_sum`, `cumulative_max`, `cumulative_min`
- `last_value`, `first_value` (semi-additive / snapshot patterns)

**The translated measure has two parts:**
1. The base aggregate `expr` (e.g. `SUM(col)` or `AVG(col)`)
2. A `window:` block specifying the time ordering and range

### Moving Functions

| ThoughtSpot | UC window config |
|---|---|
| `moving_sum([m], n, 1)` | `expr: SUM(m_col)` + `window: [{order: date_dim, range: trailing N unit}]` |
| `moving_average([m], n, 1)` | `expr: AVG(m_col)` + `window: [{order: date_dim, range: trailing N unit}]` |
| `moving_max([m], n, 1)` | `expr: MAX(m_col)` + `window: [{order: date_dim, range: trailing N unit}]` |
| `moving_min([m], n, 1)` | `expr: MIN(m_col)` + `window: [{order: date_dim, range: trailing N unit}]` |
| `moving_count([m], n, 1)` | `expr: COUNT(m_col)` + `window: [{order: date_dim, range: trailing N unit}]` |

**`range` values and ThoughtSpot window sizes:**

The ThoughtSpot `n` parameter is the number of periods. Choose the UC `range` unit to
match the granularity of the date dimension:

| Date dimension granularity | UC range unit |
|---|---|
| Daily | `trailing N day` |
| Weekly | `trailing N week` |
| Monthly | `trailing N month` |
| Quarterly | `trailing N quarter` |
| Yearly | `trailing N year` |
| Unknown / mixed | `trailing N row` — generic row-based window |

**Example:**
```
moving_average([Revenue], 3, 1)  →  3-period trailing average
```
```yaml
- name: revenue_3m_avg
  expr: AVG(revenue_col)
  window:
    - order: order_month      # the date dimension used for ordering
      range: trailing 3 month
```

### Cumulative Functions

| ThoughtSpot | UC window config |
|---|---|
| `cumulative_sum([m])` | `expr: SUM(m_col)` + `window: [{order: date_dim, range: cumulative}]` |
| `cumulative_max([m])` | `expr: MAX(m_col)` + `window: [{order: date_dim, range: cumulative}]` |
| `cumulative_min([m])` | `expr: MIN(m_col)` + `window: [{order: date_dim, range: cumulative}]` |

---

## Semi-Additive Functions

Semi-additive functions (snapshot / balance metrics) map to UC's `window:` with
`semiadditive:` config. This tells UC to take the first or last value when aggregating
across the time dimension.

### `last_value` → `semiadditive: last`

ThoughtSpot pattern:
```
last_value(sum([balance_amount]), query_groups(), {[snapshot_date]})
```

UC translation:
```yaml
- name: balance_end_of_period
  expr: SUM(balance_amount)
  window:
    - order: snapshot_date_dimension   # the date dimension name in this view
      range: current                   # 'current' for point-in-time; 'cumulative' for running last
      semiadditive: last
```

**Choosing `range` for `last_value`:**
- `current` — snapshot at the current period (most common for balance metrics)
- `cumulative` — running last value over time (useful for "balance as of")

### `first_value` — partially translatable

ThoughtSpot `first_value(agg, query_groups(), {date_col})` → `semiadditive: first`:

```yaml
window:
  - order: date_dimension
    range: current
    semiadditive: first
```

**`first_value` as a formula (not semi-additive):** If ThoughtSpot uses `first_value` to
pick the chronologically first value of a dimension (not an aggregate), this is
**untranslatable** as a UC measure. Omit and log.

### `last_value_in_period` / `first_value_in_period`

**Untranslatable.** These period-scoped variants have no equivalent in UC Metric Views.
Omit and log in Formula Translation Log.

---

## `rank` and `rank_percentile` Functions

Rank functions within measure expressions are **untranslatable** in UC Metric Views.
Rank requires row-level window semantics that aggregate measure expressions do not support.

Options for users:
- Create a dimension expression: `RANK() OVER (PARTITION BY ... ORDER BY ...)` — valid
  in a dimension `expr` if the result is deterministic per row before aggregation
- Create a Databricks view with rank pre-computed, then reference it

If the ThoughtSpot formula uses `rank()` or `rank_percentile()` in an aggregate context,
**omit and log**.

---

## Filtered Aggregates

ThoughtSpot conditional aggregation (using `if()` around a measure) maps to UC
`FILTER (WHERE ...)` syntax:

**ThoughtSpot:**
```
sum(if([status] = 'complete', [revenue], 0))
count(if([is_new_customer] = true, [customer_id], null))
```

**UC:**
```yaml
- name: complete_revenue
  expr: SUM(revenue) FILTER (WHERE status = 'complete')

- name: new_customer_count
  expr: COUNT(customer_id) FILTER (WHERE is_new_customer = true)
```

This is cleaner and more expressive than the ThoughtSpot `if()` pattern. Always prefer
`FILTER (WHERE ...)` over `CASE WHEN ... THEN value ELSE 0 END` in measures.

---

## SQL Pass-Through Functions

ThoughtSpot `sql_string_op` formulas embed raw SQL. If the embedded SQL is valid
Databricks SQL, translate directly. If it uses Snowflake-specific syntax, flag it:

| Snowflake-specific syntax | Databricks equivalent |
|---|---|
| `DATEADD(unit, n, date)` | `date + INTERVAL n unit` or `DATEADD(unit, n, date)` — supported in Databricks |
| `DATEDIFF(unit, d1, d2)` | `DATEDIFF(d2, d1)` (note: reversed arg order for day diff) |
| `IFF(cond, a, b)` | `IF(cond, a, b)` or `CASE WHEN cond THEN a ELSE b END` |
| `ZEROIFNULL(x)` | `COALESCE(x, 0)` |
| `NULLIFZERO(x)` | `NULLIF(x, 0)` |
| `DIV0(a, b)` | `try_divide(a, b)` |
| `BOOLOR_AGG(x)` | `BOOL_OR(x)` |
| `BOOLAND_AGG(x)` | `BOOL_AND(x)` |
| `LISTAGG(x, ',')` | `ARRAY_JOIN(COLLECT_LIST(x), ',')` |

For any `sql_string_op` formula, run it through these substitutions and flag for review.

---

## Untranslatable Patterns

After consulting this reference, if a formula still cannot be translated, **omit it
entirely** from the UC YAML. Do NOT use placeholder `expr` values.

**Confirmed untranslatable (omit and log):**

| Pattern | Reason |
|---|---|
| `[parameter_name]` — single word, no `::` | ThoughtSpot runtime parameter; no UC equivalent |
| `last_value_in_period(...)` | Period-scoped — no UC equivalent |
| `first_value_in_period(...)` | Period-scoped — no UC equivalent |
| `ts_first_day_of_week(...)` | ThoughtSpot time intelligence — no UC equivalent |
| `last_n_days(...)`, `last_n_months(...)` | ThoughtSpot time intelligence — no UC equivalent |
| `rank()` / `rank_percentile()` in a measure | Window rank unsupported in aggregate measures |
| `group_aggregate(...)` with `query_groups() + {attr}` | Nested grouping semantics not expressible |
| `group_aggregate(...)` with multiple fixed grouping sets | Requires cube/rollup semantics |
| `max/min/avg(group_aggregate(...))` | Outer non-sum aggregate prevents simplification |
| Hyperlink markup: `concat("{caption}", ..., "{/caption}", ...)` | ThoughtSpot display hint |
| Any formula referencing another formula that is itself untranslatable | Transitive |

**Formula Translation Log entry format:**
```
| {display_name} | OMITTED | {reason} | {original_expr} |
```

---

## Open Items — Verify Against Live Instance

The following behaviors have not been verified against a live Databricks UC instance.
See `agents/claude/ts-convert-to-databricks-mv/references/open-items.md` for test scripts.

1. **Composed measure ordering:** Can `MEASURE(m)` reference a measure defined later in the
   YAML, or must it be defined first? Test with forward-reference vs. in-order.

2. **Multi-line `expr` in YAML:** Does Databricks accept YAML block scalars (`>-`, `|`)
   in `expr` fields, or is single-line required?

3. **Backtick quoting in `expr`:** Is `` `date` `` the correct way to quote reserved
   word column names inside UC Metric View YAML `expr` strings? Or double quotes?

4. **`window:` with multiple orders:** Can `window:` contain multiple order entries
   (one per time grain)? Or is only one allowed?

5. **Nested join `expr` namespace:** Confirm that `nation.col` works in `expr` when
   `nation` is nested two levels deep — i.e., join names form a flat namespace.
