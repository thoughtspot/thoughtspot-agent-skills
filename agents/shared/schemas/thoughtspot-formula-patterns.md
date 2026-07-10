<!-- currency: thoughtspot — 2026-07 (variable endpoints: per-identifier update-values; rename + bulk delete added in 26.4.0.cl; formula composition + TML import behaviours validated on SE cluster 2026-07-10 — function composition rules, if() parens mandatory) -->

# ThoughtSpot Formula Patterns — Reference

Platform-agnostic reference for ThoughtSpot formula syntax, functions, and model TML
integration. For platform-specific translation rules (Snowflake, BigQuery, etc.),
see the corresponding file in `mappings/`.

For parsing TML that was **exported** from ThoughtSpot (PyYAML pitfalls,
non-printable characters, object type detection), see
[thoughtspot-tml.md](thoughtspot-tml.md).
For Model TML construction, see [thoughtspot-model-tml.md](thoughtspot-model-tml.md).

---

## Column Reference Syntax

ThoughtSpot formulas reference columns using bracket notation:

```
[TABLE_NAME::column_display_name]   # physical column from a table
[formula_name]                       # another formula in the same model (no TABLE:: prefix)
[Parameter Name]                     # runtime parameter (no TABLE:: prefix)
```

**Distinguishing the three types:**
- `TABLE::` separator present → physical column
- No `::`, matches a `formulas[].name` → formula reference (resolved at compile time)
- No `::`, matches a `parameters[].name` → runtime parameter (resolved at query time — untranslatable to static SQL)
- No `::`, no match → likely stale or broken reference

**Column name in reference:** Use the `name` field from the Table TML `columns[]` entry
(the ThoughtSpot display name), not the physical warehouse column name.

---

## YAML Encoding

Formula expressions live in `formulas[].expr`. Two encoding rules:

**Use `>-` folded block scalar when the expression contains `{ }` curly braces:**

```yaml
formulas:
- id: formula_Inventory Balance
  name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
```

**Use inline string for all other expressions:**

```yaml
formulas:
- id: formula_Revenue
  name: "Revenue"
  expr: "sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )"
```

Inline strings with `{ }` cause a YAML mapping error — ThoughtSpot interprets `{` as
the start of an inline map. Always use `>-` when curly braces appear in the expression.

**Single quotes inside formulas do NOT need escaping in YAML double-quoted strings:**

```yaml
# CORRECT — single quotes are valid inside double-quoted YAML:
  expr: "concat ( [T::LAST_NAME] , ', ' , [T::FIRST_NAME] )"
```

```text
# WRONG — backslash-quote is not a valid YAML escape (causes parse error):
  expr: "concat ( [T::LAST_NAME] , \', \' , [T::FIRST_NAME] )"
```

Only `\\`, `\"`, `\n`, `\t`, and Unicode escapes (`\uXXXX`) are valid inside YAML
double-quoted strings. If a formula contains both single quotes and curly braces, use
`>-` (which needs no escaping at all).

---

## Aggregate Functions

| Function | Syntax | Notes |
|---|---|---|
| `sum` | `sum ( [TABLE::col] )` | Sum of all values |
| `count` | `count ( [TABLE::col] )` | Count of non-null values |
| `unique count` | `unique count ( [TABLE::col] )` | **Distinct count — use this form.** Note the space, not an underscore. `count_distinct` is **not a valid TS formula function** — it is rejected by the formula parser ("Search did not find count_distinct(...)"). Use `unique count` exclusively. |
| `average` | `average ( [TABLE::col] )` | Mean |
| `min` | `min ( [TABLE::col] )` | Minimum |
| `max` | `max ( [TABLE::col] )` | Maximum |
| `median` | `median ( [TABLE::col] )` | Median |
| `stddev` | `stddev ( [TABLE::col] )` | Standard deviation |
| `variance` | `variance ( [TABLE::col] )` | Variance |
| `greatest` | `greatest ( [a] , [b] , ... )` | Returns the largest value across N arguments |

### Conditional Aggregates

All standard aggregates have a `*_if` variant that filters rows by a condition.
Signature: `agg_if ( condition , measure_expression )`

| Function | Syntax | Notes |
|---|---|---|
| `sum_if` | `sum_if ( condition , [TABLE::col] )` | Sum where condition is true |
| `count_if` | `count_if ( condition , [TABLE::col] )` | Count where condition is true |
| `unique_count_if` | `unique_count_if ( condition , [TABLE::col] )` | Distinct count where condition is true |
| `average_if` | `average_if ( condition , [TABLE::col] )` | Average where condition is true |
| `min_if` | `min_if ( condition , [TABLE::col] )` | Min where condition is true |
| `max_if` | `max_if ( condition , [TABLE::col] )` | Max where condition is true |
| `stddev_if` | `stddev_if ( condition , [TABLE::col] )` | Std deviation where condition is true |
| `variance_if` | `variance_if ( condition , [TABLE::col] )` | Variance where condition is true |

```
# Examples
sum_if ( [formula_Opportunity Qualified Flag] , [SFDC_OPP::ACV] )
unique_count_if ( not ( isnull ( [SFDC_OPP::M0 Date] ) ) , [SFDC_OPP::Opportunity ID] )
average_if ( [TABLE::city] = 'San Francisco' , [TABLE::revenue] )
count_if ( [TABLE::region] = 'west' , [TABLE::region] )
```

---

## Conditional Functions

| Function | Syntax |
|---|---|
| `if / then / else` | `if ( [cond] ) then [a] else [b]` |
| Multi-branch | `if ( [c1] ) then [a] else if ( [c2] ) then [b] else [c]` |
| `isnull` | `isnull ( [TABLE::col] )` |
| `isnotnull` | `isnotnull ( [TABLE::col] )` |
| `ifnull` | `ifnull ( [TABLE::col] , [default] )` |
| `nullif` | `nullif ( [a] , [b] )` |
| `not` | `not ( [expr] )` |
| `and` / `or` | `[a] and [b]` / `[a] or [b]` |
| `in` | `[col] in ( 'a' , 'b' )` |
| `between` | `[col] between [a] and [b]` |

**TML import requirement:** The parentheses around the condition in
`if ( condition ) then ... else ...` are **mandatory** for TML import via
`ts tml import`. Without them, the formula parser rejects the expression with
"Search did not find ... in your data or metadata. Expecting keyword '('."

This applies to all condition types — BOOL columns, string comparisons, compound
AND/OR, and NULL checks. Verified 2026-07-10, SE cluster.

Conditions in `if` can include `and` / `or` and function calls:

```
if ( year ( [OPP::Close Date] , fiscal ) = year ( today () , fiscal ) and [OPP::Type] != 'renewal' )
then [OPP::ACV]
else 0
```

---

## Math Functions

| Function | Syntax |
|---|---|
| `safe_divide` | `safe_divide ( [a] , [b] )` — returns 0 (not NULL) when `b` is 0 |
| `round` | `round ( [x] , [n] )` |
| `floor` | `floor ( [x] )` |
| `ceil` | `ceil ( [x] )` |
| `abs` | `abs ( [x] )` |
| `pow` | `pow ( [x] , [n] )` | Verified 2026-06-13. **Not** `power` — that name is rejected. |
| `mod` | `mod ( [x] , [n] )` |
| `sqrt` | `sqrt ( [x] )` |
| `ln` | `ln ( [x] )` |
| `log2` | `log2 ( [x] )` |
| `log10` | `log10 ( [x] )` |

---

## String Functions

| Function | Syntax | Notes |
|---|---|---|
| `concat` | `concat ( [a] , [b] , ... )` | N arguments supported. **`+` does NOT concatenate strings** in TS formulas — it is numeric-only. The TS parser rejects `[a] + ', ' + [b]` with "Search did not find + ', ' +". Always use `concat()` for string joining, including for SQL `CONCAT(a, ', ', b)` translations. |
| `substr` | `substr ( [x] , [start] , [len] )` | Zero-indexed start |
| `left` | `left ( [x] , [n] )` | First N characters |
| `right` | `right ( [x] , [n] )` | Last N characters |
| `strlen` | `strlen ( [x] )` | String length |
| `strpos` | `strpos ( [x] , 'val' )` | Position of first occurrence — 1-indexed, returns 0 when not found (live-verified 2026-06-13, se-thoughtspot; official docs claim 0-based/−1 — live behavior wins). |
| ~~`upper`~~ | — | **Does not exist** in ThoughtSpot (verified 2026-06-13). Use `sql_string_op ( "UPPER({0})" , [x] )` pass-through. |
| ~~`lower`~~ | — | **Does not exist** in ThoughtSpot (verified 2026-06-13). Use `sql_string_op ( "LOWER({0})" , [x] )` pass-through. |
| `trim` | `trim ( [x] )` | Strip leading/trailing whitespace |
| `replace` | `replace ( [x] , [old] , [new] )` | Replace all occurrences |
| `contains` | `contains ( [x] , 'val' )` | Returns boolean |
| `starts_with` | `starts_with ( [x] , 'val' )` | Returns boolean |
| `ends_with` | `ends_with ( [x] , 'val' )` | Returns boolean |

### Hyperlink Markup

`concat()` supports a ThoughtSpot-specific display pattern for clickable hyperlinks:

```
concat ( "{caption}" , "display text" , "{/caption}" , [TABLE::url_col] )
concat ( "{caption}" , "view in SFDC" , "{/caption}" , concat ( 'https://force.com/' , [OPP::ID] ) )
```

The `{caption}` / `{/caption}` tags are rendered as hyperlink text in ThoughtSpot search
results. They are ThoughtSpot-only — **not translatable** to any warehouse SQL.

---

## Type Conversion Functions

| Function | Syntax |
|---|---|
| `to_integer` | `to_integer ( [x] )` |
| `to_double` | `to_double ( [x] )` |
| `to_string` | `to_string ( [x] )` |

---

## Date Functions

*Source: ThoughtSpot official formula reference (verified 2026-06-13). Most date-part
functions accept an optional `fiscal` second parameter for fiscal calendar support.*

| Function | Syntax | Notes |
|---|---|---|
| `today` | `today ()` | Current date |
| `now` | `now ()` | Current date and time |
| `date` | `date ( [datetime] )` | Date portion of a datetime |
| `time` | `time ( [datetime] )` | Time portion of a datetime |
| `year` | `year ( [date] )` | Calendar year (integer). Optional `fiscal` param. |
| `year_name` | `year_name ( [date] )` | Year as string. With fiscal: `"FY_2014"` |
| `quarter_number` | `quarter_number ( [date] )` | Quarter (1–4). Optional `fiscal` param. |
| `month` | `month ( [date] )` | Month name (e.g. "January"). Optional `fiscal` param. |
| `month_number` | `month_number ( [date] )` | Month number (1–12). Optional `fiscal` param. |
| `month_number_of_quarter` | `month_number_of_quarter ( [date] )` | Month within quarter (1–3). Optional `fiscal` param. |
| `day` | `day ( [date] )` | Day of month (1–31). Verified 2026-06-13. Optional `fiscal` param. |
| `day_of_week` | `day_of_week ( [date] )` | Day name (e.g. "Friday"). Optional `fiscal` param. |
| `day_number_of_week` | `day_number_of_week ( [date] )` | Day number (1=Mon, 7=Sun). Optional `fiscal` param. |
| `day_number_of_quarter` | `day_number_of_quarter ( [date] )` | Day within quarter. Optional `fiscal` param. |
| `day_number_of_year` | `day_number_of_year ( [date] )` | Day within year (1–366). Optional `fiscal` param. |
| `hour_of_day` | `hour_of_day ( [date] )` | Hour of the day |
| `week_number_of_month` | `week_number_of_month ( [date] )` | Week within month. Optional `fiscal` param. |
| `week_number_of_quarter` | `week_number_of_quarter ( [date] )` | Week within quarter. Optional `fiscal` param. |
| `week_number_of_year` | `week_number_of_year ( [date] )` | Week within year. Optional `fiscal` param. |
| `is_weekend` | `is_weekend ( [date] )` | Returns true for Saturday/Sunday. Optional `fiscal` param. |
| `start_of_month` | `start_of_month ( [date] )` | First day of the month. Optional `fiscal` param. |
| `start_of_quarter` | `start_of_quarter ( [date] )` | First day of the quarter. Optional `fiscal` param. |
| `start_of_week` | `start_of_week ( [date] )` | First day of the week. Optional `fiscal` param. |
| `start_of_year` | `start_of_year ( [date] )` | First day of the year. Optional `fiscal` param. |
| `start_of_hour` | `start_of_hour ( [time] )` | Time truncated to the hour |
| `start_of_min` | `start_of_min ( [time] )` | Time truncated to the minute |
| `diff_days` | `diff_days ( [end] , [start] )` | Days between — note arg order (end first) |
| `diff_weeks` | `diff_weeks ( [end] , [start] )` | Weeks between. Optional `fiscal` third param. |
| `diff_months` | `diff_months ( [end] , [start] )` | Months between. Optional `fiscal` third param. |
| `diff_quarters` | `diff_quarters ( [end] , [start] )` | Quarters between. Optional `fiscal` third param. |
| `diff_years` | `diff_years ( [end] , [start] )` | Years between. Optional `fiscal` third param. |
| `diff_time` | `diff_time ( [end] , [start] )` | Difference in seconds |
| `diff_hours` | `diff_hours ( [end] , [start] )` | Difference in hours |
| `diff_minutes` | `diff_minutes ( [end] , [start] )` | Difference in minutes |
| `add_days` | `add_days ( [date] , [n] )` | Add N days |
| `add_weeks` | `add_weeks ( [date] , [n] )` | Add N weeks |
| `add_months` | `add_months ( [date] , [n] )` | Add N months |
| `add_years` | `add_years ( [date] , [n] )` | Add N years |
| `add_minutes` | `add_minutes ( [datetime] , [n] )` | Add N minutes |
| `add_seconds` | `add_seconds ( [datetime] , [n] )` | Add N seconds |
| ~~`date_trunc`~~ | — | **Does not exist** as a formula function (verified 2026-06-13). Use `start_of_month()` / `start_of_quarter()` / `start_of_week()` / `start_of_year()` instead. ThoughtSpot also has search keywords (`Weekly`, `Monthly`, `Quarterly`, `Yearly`) for time bucketing. |
| ~~`day_number_of_month`~~ | — | **Does not exist** (verified 2026-06-13). Use `day()` instead. |

**Argument order note:** `diff_*` functions take `(end, start)` — end date first. This is
the opposite of most SQL `DATEDIFF` functions which take `(unit, start, end)`.

**Date literal warning:** A bare `'2024-05-01'` is parsed as subtraction
(`'2024' - 05 - 01`). Wrap in `to_date ( '2024-05-01' , 'yyyy-MM-dd' )` —
hyphens are fine inside `to_date()` since the parser treats the argument as
a string. No reformatting needed; just provide a matching format pattern.

---

## Window Functions

### Cumulative Functions

`cumulative_{func}(measure, attr1 [, attr2, ...])`

ThoughtSpot dynamically adds any dimensions in the query to the partition, excluding the
`attr` arguments (which become the ORDER BY). This means cumulative functions respond to
whatever dimensions the user has in their search.

| Function | Behavior |
|---|---|
| `cumulative_sum` | Running sum ordered by `attr` |
| `cumulative_average` | Running average ordered by `attr` |
| `cumulative_max` | Running max ordered by `attr` |
| `cumulative_min` | Running min ordered by `attr` |

```
cumulative_sum ( [FACT::AMOUNT] , [DATE_DIM::ORDER_DATE] )
```

### Moving Functions

`moving_{func}(measure, start, end, attr1 [, attr2, ...])`

- `start`: positive = N rows preceding (backward), negative = N rows following (forward)
- `end`: positive = N rows following (forward), negative = N rows preceding (backward)
- `attr`: ORDER BY columns
- **Opposite-sign convention:** `start` and `end` use opposite sign conventions.
  `start=2, end=0` means "from 2 preceding to current." `start=1, end=-1` means
  "exactly the row 1 position back" (single-row window). This is how ThoughtSpot
  stores the offsets internally — verified via TML round-trip export (2026-06-15).

| Function |
|---|
| `moving_sum` |
| `moving_average` |
| `moving_max` |
| `moving_min` |

**Common patterns:**

```
# Trailing window (2-period trailing sum)
moving_sum ( [FACT::AMOUNT] , 2 , 0 , [DATE_DIM::ORDER_DATE] )

# LAG(1) — single row 1 position back
moving_sum ( [FACT::AMOUNT] , 1 , -1 , [DATE_DIM::ORDER_DATE] )

# LAG(3) — single row 3 positions back
moving_sum ( [FACT::AMOUNT] , 3 , -3 , [DATE_DIM::ORDER_DATE] )

# LEAD(1) — single row 1 position forward
moving_sum ( [FACT::AMOUNT] , -1 , 1 , [DATE_DIM::ORDER_DATE] )

# LEAD(2) — single row 2 positions forward
moving_sum ( [FACT::AMOUNT] , -2 , 2 , [DATE_DIM::ORDER_DATE] )
```

**Offset summary (verified 2026-06-15, se-thoughtspot):**

| Intent | start | end | Window |
|---|---|---|---|
| Trailing N rows + current | N | 0 | N preceding → current |
| LAG(N) — single row N back | N | -N | exactly row N back |
| LEAD(N) — single row N forward | -N | N | exactly row N forward |
| Full window (N back to M forward) | N | M | N preceding → M following |

Sort column (4th arg) must be a physical `[TABLE::column]` reference. Formula column
names fail with "Search did not find" errors. Verified 2026-05-28.

**Row-positional, not date-interval (platform-native fact, live-verified 2026-07-09
on gapped data).** `moving_sum`'s window is a count of *rows* in sort order, not a
span of calendar time. Re-run on a fixture with date gaps (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, E1), `moving_sum([m], N, -1, [d])`
counted the N preceding *surviving rows* regardless of the calendar distance between
them — diverging from a date-interval reading whenever the sort column has gaps at
its nominal grain. Matches the row-count description above exactly; this is a
ThoughtSpot-side fact independent of any specific cross-platform mapping — see the
claim matrix (E1) for the cross-platform consequences.

### Function Composition Rules

ThoughtSpot formulas have strict rules about which functions can contain which:

**1. Group functions are shorthand for `group_aggregate`:**

| Shorthand | Expands to |
|---|---|
| `group_sum(col, dim)` | `group_aggregate(sum(col), {dim}, query_filters())` |
| `group_average(col, dim)` | `group_aggregate(average(col), {dim}, query_filters())` |
| `group_count(col, dim)` | `group_aggregate(count(col), {dim}, query_filters())` |
| `group_max(col, dim)` | `group_aggregate(max(col), {dim}, query_filters())` |
| `group_min(col, dim)` | `group_aggregate(min(col), {dim}, query_filters())` |
| `group_unique_count(col, dim)` | `group_aggregate(unique count(col), {dim}, query_filters())` |

All group functions return a **row-level scalar** value.

**2. Group functions CANNOT nest inside each other:**

```
# INVALID — group inside group
group_sum ( group_count ( [T::ID] , [T::CATEGORY] ) , [T::REGION] )

# VALID — use separate formulas and reference by name
# Formula 1: "Count by Category" = group_count([T::ID], [T::CATEGORY])
# Formula 2: group_sum([Count by Category], [T::REGION])
```

**3. Window functions accept group function output:**

Window functions (`cumulative_*`, `moving_*`) take either:
- A column reference: `cumulative_sum([T::AMOUNT], [T::ORDER_DATE])`
- A group function result: `moving_sum(group_aggregate(sum([T::COL]), {[T::PK]}, query_filters()), -1, 0, [T::ORDER])`

**4. Raw aggregates CANNOT go directly into window functions:**

```
# INVALID — raw aggregate inside moving_sum
moving_sum ( sum ( [T::AMOUNT] ) , -1 , 0 , [T::ORDER_DATE] )

# VALID — wrap in group_aggregate first
moving_sum ( group_aggregate ( sum ( [T::AMOUNT] ) , { [T::PK] } , query_filters ( ) ) , -1 , 0 , [T::ORDER_DATE] )

# VALID — use a column reference (ThoughtSpot handles aggregation implicitly)
cumulative_sum ( [T::AMOUNT] , [T::ORDER_DATE] )
```

**Summary:**

| Input to... | Column ref | group_aggregate / group_* | Raw aggregate (sum, count...) |
|---|---|---|---|
| **group functions** | ✓ | ✗ (cannot nest) | ✓ (inside group_aggregate only) |
| **window functions** | ✓ | ✓ | ✗ (wrap in group_aggregate first) |
| **aggregates** (sum, count...) | ✓ | — | — |

### Rank Functions

`rank(agg(measure), 'asc'|'desc')`
`rank_percentile(agg(measure), 'asc'|'desc')`

Rank is always **global** — no partition attributes. ORDER BY is derived from the measure aggregation.

```
rank ( sum ( [FACT::QUANTITY] ) , 'desc' )
rank_percentile ( sum ( [FACT::REVENUE] ) , 'asc' )
```

---

## Level of Detail (LOD) Functions

LOD functions compute sub-aggregations at a fixed or dynamic granularity, independent of
the query grain.

### `group_aggregate`

Full syntax: `group_aggregate ( agg(measure) , grouping , filters )`

**Grouping argument:**

| Grouping | Behavior |
|---|---|
| `{}` | Grand total — no partition |
| `{ [TABLE::attr1] , [TABLE::attr2] }` | Fixed partition — always these dimensions |
| `query_groups()` | All dimensions in the query (equivalent to a regular aggregate) |
| `query_groups() + {}` | Same as `query_groups()` — prevents TS SQL simplification |
| `query_groups() - { [TABLE::attr] }` | All query dimensions except attr |
| `query_groups() + { [TABLE::attr] }` | All query dimensions plus always include attr — **untranslatable** |
| `query_groups( [TABLE::attr1] )` | Include only attr1 if it's in the query — **untranslatable** |

**Filter argument:**

| Filter | Behavior |
|---|---|
| `query_filters()` | All filters from the query — translatable |
| `{}` | No filters — **untranslatable** to Snowflake SV; **translatable to a Databricks MV** as the query-time-blind LOD paired with a model filter → MV global `filter:` (live-verified 2026-07-09 — see the A3 note below) |
| `{ [TABLE::col] = 'value' }` | Hardcoded filter — **untranslatable** |
| `query_filters() + { [TABLE::col] = 'value' }` | All query filters + hardcoded — **untranslatable** |
| `query_filters() - { [TABLE::col] }` | Query filters minus one column — **untranslatable** |

**`{}` is scoped to query-level filters only — live-verified 2026-07-09** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A3). "No filters" means no
*query-level* filters: `{}` blinds the `group_aggregate` LOD to a search-level pin
(the LOD value is unchanged whether or not the pin is applied) but it does **not**
blind the LOD to a model-level `filters:` block — the LOD value still narrows to
whatever the model-level filter has already restricted the underlying data to. In
other words, `{}` disables incorporation of ad hoc query-time filters; it does not
bypass filtering baked into the model itself. Import-accepted with no error on this
build. The subtraction form (`query_filters() - { [TABLE::col] }`) was also
import-accepted, but subtracting a raw physical column does not exclude a filter
pinned on a *derived* boolean formula built from that column — the query-filter
provenance tracks the column the filter predicate was actually applied to, not that
column's underlying physical dependency.

### `group_*` Shorthand Functions

Sugar for `group_aggregate` with `query_filters()` as the filter argument:

| Shorthand | Equivalent |
|---|---|
| `group_sum(m, attr)` | `group_aggregate(sum(m), {attr}, query_filters())` |
| `group_average(m, attr)` | `group_aggregate(average(m), {attr}, query_filters())` |
| `group_count(m, attr)` | `group_aggregate(count(m), {attr}, query_filters())` |
| `group_max(m, attr)` | `group_aggregate(max(m), {attr}, query_filters())` |
| `group_min(m, attr)` | `group_aggregate(min(m), {attr}, query_filters())` |
| `group_unique_count(m, attr)` | `group_aggregate(unique count(m), {attr}, query_filters())` |
| `group_stddev(m, attr)` | `group_aggregate(stddev(m), {attr}, query_filters())` |
| `group_variance(m, attr)` | `group_aggregate(variance(m), {attr}, query_filters())` |

### Percentage Contribution Pattern

A very common use of LOD: product sales as % of category total.

```
safe_divide ( sum ( [FACT::QUANTITY] ) , group_sum ( [FACT::QUANTITY] , [CATEGORY::NAME] ) )
```

---

## Semi-Additive Functions

Used for snapshot metrics — values that should not be summed across time (e.g. inventory
balance, account balance, headcount at period end).

`last_value ( agg(measure) , grouping , { [DATE_TABLE::date_col] } )`
`first_value ( agg(measure) , grouping , { [DATE_TABLE::date_col] } )`

- The `grouping` argument uses the same `query_groups()` / `{}` syntax as `group_aggregate`
- The `{ date_col }` argument (curly braces) specifies the time axis — **requires `>-` YAML encoding**

```yaml
expr: >-
  last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
```

**Semi-additive variants:**

| Function | Behavior | Translatable? |
|---|---|---|
| `last_value(..., query_groups(), {date})` | Last snapshot value, query-grain partition | Yes — via `non_additive_dimensions` in Snowflake SV |
| `first_value(..., query_groups(), {date})` | First snapshot value | No — `NON ADDITIVE BY` only supports last-value semantics |
| `last_value_in_period(...)` | Last value only if the period's last date is complete | Yes — treat same as `last_value(...)` |
| `first_value_in_period(...)` | First value only if the period's first date is complete | Yes — treat same as `first_value(...)` |
| `agg(last_value(...))` e.g. `max(last_value(...))` | Re-aggregation of a snapshot metric | No |

---

## SQL Pass-Through Functions

Embed raw SQL templates with `{0}`, `{1}`, ... positional placeholders for column arguments.
Used when ThoughtSpot's native functions don't cover the required expression.

| Function | Return type | Use case |
|---|---|---|
| `sql_string_op(template, args...)` | VARCHAR | String dimension |
| `sql_int_op(template, args...)` | INTEGER | Integer dimension |
| `sql_double_op(template, args...)` | DOUBLE | Double dimension |
| `sql_bool_op(template, args...)` | BOOLEAN | Boolean dimension |
| `sql_date_op(template, args...)` | DATE | Date dimension |
| `sql_date_time_op(template, args...)` | DATETIME | Datetime dimension (verified 2026-06-15) |
| `sql_string_aggregate_op(template, args...)` | VARCHAR | String aggregate/metric |
| `sql_int_aggregate_op(template, args...)` | INTEGER | Integer aggregate/metric |
| `sql_number_aggregate_op(template, args...)` | NUMBER | Numeric aggregate/metric |
| `sql_date_time_aggregate_op(template, args...)` | DATETIME | Datetime aggregate/metric |

```
# Initcap with replace
sql_string_op ( " initcap ( replace ( {0} , '_' , ' ' ) ) " , [TASK::Status] )

# Regex replace
sql_string_op ( " regexp_replace( {0} , '\\[partner\\] ' , '' , 1 , 0 , 'i' ) " , [OPP::Account Name] )

# Conditional integer using Snowflake IFF
sql_int_op ( "iff ( lower({0}) = 'yes' , 1 , 0 )" , [SURVEY::Answer] )

# Date function using GREATEST
sql_date_op ( " greatest ( {0} , {1} ) " , [PROJECT::Start Date] , [PROJECT::Baseline Date] )

# Aggregate: LISTAGG
sql_string_aggregate_op ( "listagg({0}, ' | ') within group (order by {0})" , [PRODUCTS::Name] )
```

**If any argument is a parameter reference (`[Param Name]`), the formula is untranslatable.**

### Window functions inside `sql_*_aggregate_op`

`sql_*_aggregate_op` can embed SQL window functions (`LAG`, `LEAD`, `ROW_NUMBER`,
`RANK`, `DENSE_RANK`, etc.). Two rules apply when the query is aggregated
(i.e., the search includes both dimension and measure columns):

1. **ORDER BY expression must match GROUP BY.** ThoughtSpot generates GROUP BY from
   the search query's columns. The window function's `ORDER BY` must resolve to the
   same expression. For date columns with bucketing (e.g., `[date].monthly` in the
   search query), use the matching ThoughtSpot date function in ORDER BY:

   | Search date aggregate | Matching ORDER BY expression |
   |---|---|
   | `[date].monthly` | `start_of_month ( [date] )` |
   | `[date].quarterly` | `start_of_quarter ( [date] )` |
   | `[date].yearly` | `start_of_year ( [date] )` |
   | `[date].weekly` | `start_of_week ( [date] )` |
   | `[date]` (no bucketing) | `[date]` |

   A raw `[date]` in ORDER BY when the search uses `.monthly` produces
   `"column is not a valid group by expression"` — the raw column doesn't match
   the `DATE_TRUNC` in GROUP BY.

2. **All search dimensions must appear in PARTITION BY.** Every non-measure column
   in the `search_query` generates a GROUP BY clause. The window function must
   include all of them in `PARTITION BY`, or Snowflake rejects the unmatched
   GROUP BY column.

Verified 2026-06-15 on se-thoughtspot (Snowflake). Example:
```
# LEAD with monthly date bucketing and region partition
sql_int_aggregate_op ( "LEAD(SUM({0}), 1) OVER (PARTITION BY {1} ORDER BY {2})" , [Sales] , [Region] , start_of_month ( [Order Date] ) )
# search_query must include: [Order Date].monthly [Region] [Sales] [formula]
```

### `group_aggregate` wrapping for pass-through window functions

Wrapping a `sql_*_aggregate_op` window function in `group_aggregate` resolves
multiple limitations at once:

1. **Mandatory partition columns** — the PARTITION BY column is guaranteed to be in
   the GROUP BY via `query_groups() + {col}`, even if the user's search doesn't
   include it. Without wrapping, the formula breaks when the partition column is
   absent from the search.
2. **Aggregate function conflicts** — ThoughtSpot's SQL generator can misplace
   aggregate expressions inside window functions. `group_aggregate` isolates the
   aggregation context.
3. **HAVING clause compatibility** — bare pass-through window functions can conflict
   with ThoughtSpot-generated HAVING clauses. The wrapper prevents this.
4. **Drill-down support** — wrapped formulas remain valid when the user drills into
   additional dimensions, because `query_groups()` dynamically includes them.

**Pattern — partitioned rank:**
```
# Without wrapping — breaks if [Account Region] is not in the search
sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [Account Region] , [Account Revenue] )

# With group_aggregate wrapping — always works
group_aggregate ( sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [Account Region] , [Account Revenue] ) , query_groups ( ) + { [Account Region] } , query_filters ( ) )
```

The `query_groups() + {col}` grouping ensures the partition column is always
present in the GROUP BY. `query_filters()` passes through all user-applied filters.

**When to wrap:** wrap any `sql_*_aggregate_op` window function that has a
`PARTITION BY` clause referencing a column that may not be in the user's search.
Unwrapped formulas are valid only when the partition column is guaranteed to be in
every search that uses the formula.

**Prefer native functions** (`moving_sum` for LAG/LEAD, `first_value`/`last_value`,
`rank`) when they cover the use case — they handle all column types without
GROUP BY matching concerns. Use `sql_*_aggregate_op` window functions (with
`group_aggregate` wrapping) when native functions can't express the required
semantics (e.g., `DENSE_RANK`, partitioned rank, `ROW_NUMBER`).

---

## Weighted average

A weighted average is `Σ(value × weight) / Σ(weight)`. In ThoughtSpot the hard part is
never the arithmetic — it is **(1) deciding whether the weight is already applied at the
source, and (2) choosing the grain the weighted sum is computed at.** Get either wrong and
the formula is syntactically valid but numerically wrong.

### Step 0 — the fork: is the weight already baked in?

Before writing anything, determine which situation you are in:

| Situation | Recognize it by | What to do |
|---|---|---|
| **Pre-weighted at source** | A physical column already holds the weighted quantity (a name like `WEIGHTED_USAGE`, `WEIGHTED_COST`); upstream SQL/ETL applied the weight | Just **sum it** — `sum ( [col] )`, optionally inside `group_aggregate(...)` for a fixed grain. **Do not** apply a weighted-average formula on top — that re-applies the weight and double-counts. |
| **Computed in-tool** | You have a raw `value` and a separate `weight`, and need to combine them | Use the computed pattern below. |

This fork is the single most common mistake: wrapping a `Σ(v×w)/Σ(w)` template around a
column that was *already* weighted.

### Step 1 — the computed pattern

For a weighted average computed at a grouping grain (e.g. weighted unit cost across the
lines of each product, then rolled up):

```
# Weighted average — Σ(value × weight) over {grain}, divided by Σ(weight)
sum ( group_aggregate ( sum ( [value] ) * sum ( [weight] ) , { [grain] } , query_filters ( ) ) )
/ sum ( [weight] )
```

The unweighted companion (a plain average across the same grain), useful as a comparison
column:

```
average ( group_aggregate ( sum ( [value] ) , { [grain] } , query_filters ( ) ) )
```

### Step 2 — grain and re-aggregation

- **`{ [grain] }`** is the level the per-group weighted sum is computed at. It is the one
  decision a column-injection template cannot make for you — pick the grain at which the
  weight is meaningful (per product, per account, per SKU…), not the viz's display grain.
- The **outer `sum ( group_aggregate ( … ) )`** is what lets the measure re-aggregate when
  shown at a coarser grain. A **bare** `group_aggregate(...)` stays pinned at `{ [grain] }`
  (matches a Tableau `FIXED` value that repeats per row); the **wrapped** form is the
  portable measure you can drop on any viz. For a model MEASURE column you almost always
  want the wrapped form — and recall ThoughtSpot ignores the column's `aggregation` field,
  so the explicit outer `sum` is what actually re-aggregates. See "`group_aggregate`
  wrapping" above.
- Use `query_filters()` in the filter argument when the weighted average should respect the
  user's filters (the usual case). Use a hard `{ … }` only to pin a scope that must ignore
  viz filters (Tableau `FIXED` semantics — see the Tableau mapping's "boolean predicate
  inside a FIXED partition" rule).

These computed forms are generalized from production formulas (weighted cost across
product lines, with a parameter-driven window). They are not yet captured as a
live-verified worked example — verify the grain against the source before shipping.

---

## Runtime Parameters

Defined in `model.parameters[]` and referenced in formula expressions with bracket notation
(no `TABLE::` prefix):

```yaml
parameters:
- id: "4aa0677f-b1e6-40c2-a33e-7da656820710"
  name: FTE Hourly Rate
  data_type: INT64          # INT64 | DOUBLE | DATE | VARCHAR
  default_value: "40"       # always a string in TML regardless of data_type
  description: ""
```

Reference in formula: `[FTE Hourly Rate]`

Parameters are set by users at query time via the ThoughtSpot UI. They cannot be resolved
to static SQL — formulas referencing parameters are **untranslatable** to Snowflake
Semantic Views or other static SQL targets.

---

## System Variables and Formula Variables

ThoughtSpot provides two categories of runtime variables — **system variables**
(built-in, always available) and **formula variables** (admin-created via API).
Both are available in model/answer formulas and in RLS rules, but the syntax
differs between these two contexts.

### System Variables (built-in)

| Variable | Resolves to | Data type |
|---|---|---|
| `ts_username` | Signed-in user's username | VARCHAR |
| `ts_groups` | List of group names the user belongs to | VARCHAR list |
| `ts_groups_int` | List of group IDs the user belongs to | INT list |
| `ts_org` | Current org context | VARCHAR |
| `ts_email_domain` | Email domain of the signed-in user | VARCHAR |

### Formula Variables (admin-created)

Created via `POST /api/rest/2.0/template/variables/create` with `type: FORMULA_VARIABLE`.
Referenced using `ts_var()`. Supported data types: `VARCHAR`, `INT32`, `INT64`,
`DOUBLE`, `DATE`, `DATE_TIME`. `BOOLEAN` and `TIME` are not supported.

Values can be set at three levels (most specific wins):
- **Org level** — default for all users in the org
- **User level** — overrides org default for a specific user
- **Model level** — overrides org default for a specific Model

Values are assigned via the per-identifier endpoint
`POST /api/rest/2.0/template/variables/{identifier}/update-values` (the batch
`/template/variables/update-values` form is deprecated as of 26.4.0.cl) or passed as
security entitlements in JWT tokens (ABAC pattern). 26.4.0.cl also added variable
rename (`POST /template/variables/{identifier}/update`) and bulk delete
(`POST /template/variables/delete`).

Common formula variables: `region_var`, `department_var`, `country_var`.
Manage `ts_user_timezone` via `/ts-variable-timezone`.

### Syntax: Model / Answer Formulas

In formula expressions (`formulas[].expr`), use ThoughtSpot formula syntax with
bracket notation for column references.

**`ts_var()` in the formula editor currently only supports `ts_user_timezone`** —
arbitrary formula variables (e.g. `region_var`) are not yet supported in
model/answer formulas. Use RLS rules for those.

```yaml
formulas:
- id: formula_Timezone Filter
  name: Timezone Filter
  expr: "[DATE_TZ_BRIDGE::TIMEZONE] = ts_var ( ts_user_timezone )"
```

System variables are available directly (no `ts_var()` wrapper):

```
if ( 'Admin Group' in ts_groups ) then true else false
```

Use a boolean formula as a model-level filter by adding it as a hidden
column and referencing it in `model.filters[]`:

```yaml
columns:
- name: Timezone Filter
  formula_id: formula_Timezone Filter
  properties:
    column_type: ATTRIBUTE

filters:
- column:
  - Timezone Filter
  oper: in
  values:
  - "true"
```

### Syntax: RLS Rules (Table objects)

RLS rules use **bare column names** (no bracket notation, no `TABLE::` prefix).

**`ts_var()` in RLS can reference formula variables but currently NOT
`ts_user_timezone`** — the timezone attribute is only available via the formula
editor, not RLS.

```
region = ts_var(region_var)
```

```
'data developers' in ts_groups OR Department = ts_var(department_var)
```

RLS rules are defined on Table objects, not Models. They are **not exported in
TML** — they must be managed via the ThoughtSpot UI or REST API.

### Key Differences: Formula Context vs RLS Context

| Aspect | Formula (Model/Answer) | RLS (Table) |
|---|---|---|
| Column references | `[TABLE::COL]` bracket notation | Bare column name |
| `ts_var()` scope | `ts_user_timezone` only | Formula variables only (not timezone) |
| `ts_var()` syntax | `ts_var ( name )` (spaces around parens) | `ts_var(name)` (compact) |
| System variables | `ts_username`, `ts_groups`, `ts_groups_int`, `ts_org`, `ts_email_domain` | Same |
| Defined on | Model or Answer `formulas[]` | Table → Row Security |
| Exported in TML | Yes (in `formulas[].expr`) | No |
| Multi-value `=` | Standard equality | Expands to `IN (...)` clause |

### Translatability

Formulas referencing `ts_var()` or system variables are **untranslatable** to
Snowflake Semantic Views, Databricks Metric Views, or other static SQL targets —
these are ThoughtSpot runtime constructs with no SQL equivalent. When converting
from ThoughtSpot, flag them as `UNTRANSLATABLE` with a note explaining the
variable's purpose.

---

## Formula in Model TML

### `formula_id` format

```
formula_id = "formula_" + formula name (spaces preserved, original case)
```

Examples:
- Formula named `"Revenue"` → `formula_id: formula_Revenue`
- Formula named `"Inventory Balance"` → `formula_id: formula_Inventory Balance`

### Every formula must appear in `columns[]`

Formulas defined in `formulas[]` are invisible unless referenced by a `columns[]` entry:

```yaml
formulas:
- id: formula_Revenue
  name: "Revenue"
  expr: "sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )"

columns:
- name: "Revenue"
  formula_id: formula_Revenue    # connects the formula to the visible column
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX
```

### `aggregation` on formulas vs columns

- **Never** add `aggregation:` to a `formulas[]` entry — causes `FORMULA is not a valid aggregation type`
- Add `aggregation:` to the `columns[]` entry that references the formula

### Formula inter-references

A formula can reference another formula by display name:

```yaml
formulas:
- id: formula_Gross Margin
  name: "Gross Margin"
  expr: "sum ( [FACT::REVENUE] ) - sum ( [FACT::COST] )"

- id: formula_Gross Margin %
  name: "Gross Margin %"
  expr: "safe_divide ( [Gross Margin] , sum ( [FACT::REVENUE] ) )"
  #                    ^^^^^^^^^^^^^ references the formula above by name
```

Resolve inter-references by name lookup in `formulas[]`. Apply recursively up to 3 levels.
Circular or depth > 3 references should be flagged as untranslatable.
