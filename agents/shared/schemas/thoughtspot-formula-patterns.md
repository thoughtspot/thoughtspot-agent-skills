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

| Function | Syntax | Notes |
|---|---|---|
| `sum_if` | `sum_if ( [condition] , [TABLE::col] )` | Sum where condition is true |
| `unique_count_if` | `unique_count_if ( [condition] , [TABLE::col] )` | Distinct count where condition is true |

```
# Example
sum_if ( [formula_Opportunity Qualified Flag] , [SFDC_OPP::ACV] )
unique_count_if ( not ( isnull ( [SFDC_OPP::M0 Date] ) ) , [SFDC_OPP::Opportunity ID] )
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
| `power` | `power ( [x] , [n] )` |
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
| `strpos` | `strpos ( [x] , 'val' )` | Position of first occurrence (1-indexed) |
| `upper` | `upper ( [x] )` | Uppercase |
| `lower` | `lower ( [x] )` | Lowercase |
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

| Function | Syntax | Notes |
|---|---|---|
| `today` | `today ()` | Current date |
| `now` | `now ()` | Current timestamp |
| `date` | `date ( [datetime] )` | Cast datetime to date |
| `year` | `year ( [date] )` | Calendar year |
| `year` (fiscal) | `year ( [date] , fiscal )` | Fiscal year — ThoughtSpot-specific, not translatable to static SQL |
| `quarter_number` | `quarter_number ( [date] )` | Calendar quarter (1–4) |
| `quarter_number` (fiscal) | `quarter_number ( [date] , fiscal )` | Fiscal quarter — not translatable |
| `month` | `month ( [date] )` | Month number (1–12) |
| `day` | `day ( [date] )` | Day of month |
| `hour` | `hour ( [date] )` | Hour of day |
| `start_of_month` | `start_of_month ( [date] )` | First day of the month |
| `diff_days` | `diff_days ( [end] , [start] )` | Days between — note arg order (end first) |
| `diff_months` | `diff_months ( [end] , [start] )` | Months between |
| `diff_years` | `diff_years ( [end] , [start] )` | Years between |
| `diff_time` | `diff_time ( [end] , [start] )` | Time difference in seconds |
| `add_days` | `add_days ( [date] , [n] )` | Add N days |
| `add_weeks` | `add_weeks ( [date] , [n] )` | Add N weeks |
| `add_months` | `add_months ( [date] , [n] )` | Add N months |
| `date_trunc` | `date_trunc ( 'month' , [date] )` | Truncate to period — `'day'`, `'week'`, `'month'`, `'quarter'`, `'year'` |

**Argument order note:** `diff_*` functions take `(end, start)` — end date first. This is
the opposite of most SQL `DATEDIFF` functions which take `(unit, start, end)`.

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

- `start` / `end`: window frame bounds. Positive = preceding rows, 0 = current row, negative = following rows
- `attr`: ORDER BY columns

| Function |
|---|
| `moving_sum` |
| `moving_average` |
| `moving_max` |
| `moving_min` |

```
moving_sum ( [FACT::AMOUNT] , 2 , 0 , [DATE_DIM::ORDER_DATE] )   # 2-period trailing sum
```

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
| `{}` | No filters — **untranslatable** |
| `{ [TABLE::col] = 'value' }` | Hardcoded filter — **untranslatable** |
| `query_filters() + { [TABLE::col] = 'value' }` | All query filters + hardcoded — **untranslatable** |
| `query_filters() - { [TABLE::col] }` | Query filters minus one column — **untranslatable** |

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
| `last_value_in_period(...)` | Last value only if the period's last date is complete | No — completeness check has no SQL equivalent |
| `first_value_in_period(...)` | First value only if the period's first date is complete | No |
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
| `sql_string_aggregate_op(template, args...)` | VARCHAR | String aggregate/metric |
| `sql_int_aggregate_op(template, args...)` | INTEGER | Integer aggregate/metric |
| `sql_number_aggregate_op(template, args...)` | NUMBER | Numeric aggregate/metric |

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
