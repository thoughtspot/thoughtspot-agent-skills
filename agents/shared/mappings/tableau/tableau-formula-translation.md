# Tableau → ThoughtSpot Formula Translation

Reference for converting Tableau calculated field expressions to ThoughtSpot TML formula expressions.

---

## Function Mapping

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `IF cond THEN a ELSE b END` | `if ( cond ) then a else b` | Parentheses required around condition |
| `ELSEIF` | `else if` | Two words in ThoughtSpot |
| `CASE [f] WHEN 'a' THEN 1 ... END` | `if ( [f] = 'a' ) then 1 else if ...` | No native CASE; expand to if/else chain |
| `IFNULL(a, b)` | `ifnull ( a , b )` | Direct mapping |
| `ISNULL(a)` | `isnull ( a )` | Maps to `isnull()` — NOT `= ''` (different semantics) |
| `ZN(a)` | `ifnull ( a , 0 )` | |
| `CONTAINS(a, b)` | `contains ( a , b )` | |
| `LEFT(s, n)` | `substr ( s , 0 , n )` | ThoughtSpot uses 0-based indexing |
| `RIGHT(s, n)` | `substr ( s , strlen ( s ) - n , n )` | |
| `MID(s, start, len)` | `substr ( s , start - 1 , len )` | Adjust for 0-based indexing |
| `LEN(s)` | `strlen ( s )` | |
| `FIND(s, sub)` | `strpos ( s , sub )` | |
| `REPLACE(s, old, new)` | `replace ( s , old , new )` | |
| `UPPER(s)` | `upper ( s )` | |
| `LOWER(s)` | `lower ( s )` | |
| `TRIM(s)` | `trim ( s )` | |
| `SPLIT(s, delim, n)` | Use `substr`/`strpos` combination | No direct equivalent; chain: Tableau `SPLIT` → Snowflake `SPLIT_PART` → ThoughtSpot `substr`/`strpos` |
| `DATEDIFF('day', a, b)` | `diff_days ( a , b )` | Unit-specific: also `diff_months` |
| `DATETRUNC('month', d)` | `start_of_month ( d )` | Also `start_of_quarter`, `start_of_week`, `start_of_year` |
| `DATETRUNC('week', TODAY()) + 1` | `add_days ( start_of_week ( today () ) , 1 )` | Do NOT use + operator on dates |
| `DATEADD('day', n, d)` | `add_days ( d , n )` | Also `add_months`, `add_years` |
| `DATEPART('month', d)` | `month_number ( d )` | Also `day_number_of_month`, `year`, `quarter_number` |
| `DATENAME('month', d)` | `month_number ( d )` | ThoughtSpot has no month-name function; use number |
| `TODAY()` | `today ()` | |
| `NOW()` | `now ()` | |
| `DATE(d)` | `date ( d )` | Does not accept string literals |
| `YEAR(d)` | `year ( d )` | |
| `MONTH(d)` | `month_number ( d )` | |
| `DAY(d)` | `day_number_of_month ( d )` | |
| `INT(x)` | `round ( x )` | No direct INT cast in ThoughtSpot |
| `FLOAT(x)` | `x * 1.0` | |
| `STR(x)` | `to_string ( x )` | |
| `ABS(x)` | `abs ( x )` | |
| `ROUND(x, n)` | `round ( x , n )` | |
| `CEILING(x)` | `ceil ( x )` | |
| `FLOOR(x)` | `floor ( x )` | |
| `LOG(x)` | `log10 ( x )` | |
| `LN(x)` | `ln ( x )` | |
| `POWER(x, n)` | `pow ( x , n )` | |
| `SQRT(x)` | `sqrt ( x )` | |
| `MIN(a, b)` (scalar) | `if ( a < b ) then a else b` | ThoughtSpot `min` is aggregate-only |
| `MAX(a, b)` (scalar) | `if ( a > b ) then a else b` | ThoughtSpot `max` is aggregate-only |
| `COUNTD(x)` | `unique count ( x )` | Aggregate only |
| `AVG(x)` | `average ( x )` | Aggregate only |
| `ATTR(x)` | `x` | No equivalent; just reference the column |
| `IIF(test, a, b)` | `if ( test ) then a else b` | Tableau's inline if; chain: Tableau `IIF` → Snowflake `IFF` → ThoughtSpot `if/then/else` |
| `SIGN(x)` | `if ( x > 0 ) then 1 else if ( x < 0 ) then -1 else 0` | No direct `sign()` in ThoughtSpot |
| `SQUARE(x)` | `pow ( x , 2 )` | |
| `STDEV(x)` | `stddev ( x )` | Aggregate only |
| `MEDIAN(x)` | `median ( x )` | Aggregate only |
| `DATEPART('dayofyear', d)` | `day_number_of_year ( d )` | |
| `DATEPART('weekday', d)` | `day_of_week ( d )` | |
| `DATEPART('hour', d)` | `hour_of_day ( d )` | |
| `DATEPART('quarter', d)` | `quarter_number ( d )` | |
| `DATEPART('week', d)` | `week_number_of_year ( d )` | |

---

## ThoughtSpot Formula Syntax Rules

1. **Spaces around operators and parentheses** — `if ( a = b ) then c else d` (not `if(a=b)`)
2. **Single quotes for string literals** — `'value'` (not `"value"`)
3. **Square brackets for column references** — `[table::column]` or `[formula_id]`
4. **Boolean literals** — lowercase `true` / `false`
5. **Boolean operators** — `and`, `or`, `not` (lowercase)
6. **No semicolons or statement terminators**
7. **`to_date()` requires exactly 2 arguments** — `to_date ( '2019-07-31' , 'yyyy-MM-dd' )`

---

## LOD Expressions → `group_aggregate()`

Tableau Level of Detail (LOD) expressions map to ThoughtSpot's `group_aggregate()`
function. Chain: Tableau LOD → Snowflake `OVER (PARTITION BY ...)` → ThoughtSpot
`group_aggregate()`. See `ts-snowflake-formula-translation.md` "Level of Detail (LOD)
Functions" for the full `group_aggregate` reference.

| Tableau LOD | ThoughtSpot | Notes |
|---|---|---|
| `{FIXED [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , { dim } , {} )` | Fixed grain — partitions by the listed dimension(s) |
| `{FIXED [d1], [d2] : AVG([col])}` | `group_aggregate ( average ( [table::col] ) , { d1 , d2 } , {} )` | Multiple dimensions in partition |
| `{INCLUDE [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , query_groups () + { dim } , query_filters () )` | Adds dimension to whatever the query already groups by |
| `{EXCLUDE [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , query_groups () - { dim } , query_filters () )` | Removes dimension from the query's grouping |
| `{SUM([col])}` (no LOD keyword) | `group_aggregate ( sum ( [table::col] ) , {} , {} )` | Grand total — no partitioning |

**Syntax rules for `group_aggregate`:**
- Dimensions use curly braces: `{ dim1 , dim2 }`
- `query_groups()` and `query_filters()` are ThoughtSpot keywords, not column references
- The inner aggregate (`sum`, `average`, `max`, `min`, `unique count`) follows standard ThoughtSpot formula syntax
- Column references inside `group_aggregate` use `[table::column]` format

---

## Running / Cumulative Functions

Tableau running table calculations map to ThoughtSpot cumulative functions. Chain:
Tableau `RUNNING_*` → Snowflake `SUM/AVG/etc OVER (... ROWS BETWEEN UNBOUNDED PRECEDING
AND CURRENT ROW)` → ThoughtSpot `cumulative_*()`.

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `RUNNING_SUM(SUM([col]))` | `cumulative_sum ( sum ( [table::col] ) )` | Optional partition/sort args: `cumulative_sum ( measure , attr1 , attr2 )` |
| `RUNNING_AVG(AVG([col]))` | `cumulative_average ( average ( [table::col] ) )` | |
| `RUNNING_MAX(MAX([col]))` | `cumulative_max ( max ( [table::col] ) )` | |
| `RUNNING_MIN(MIN([col]))` | `cumulative_min ( min ( [table::col] ) )` | |

**Limitations:**
- ThoughtSpot cumulative functions use the query's natural sort order — there is no
  explicit `ORDER BY` parameter like Snowflake window functions
- Partition dimensions are optional trailing arguments, not a separate `PARTITION BY`

---

## Window / Moving Functions

Tableau's `WINDOW_*` functions map to ThoughtSpot's `moving_*` functions. Chain:
Tableau `WINDOW_SUM` → Snowflake `SUM() OVER (... ROWS BETWEEN ...)` → ThoughtSpot
`moving_sum()`. See `ts-snowflake-formula-translation.md` "Moving / Sliding Window
Functions" for the full reference.

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `WINDOW_SUM(SUM([col]), -3, 0)` | `moving_sum ( sum ( [table::col] ) , 3 , 0 , [table::sort_attr] )` | 3-row lookback |
| `WINDOW_AVG(SUM([col]), -3, 0)` | `moving_average ( sum ( [table::col] ) , 3 , 0 , [table::sort_attr] )` | |
| `WINDOW_MAX(SUM([col]), -3, 0)` | `moving_max ( sum ( [table::col] ) , 3 , 0 , [table::sort_attr] )` | |
| `WINDOW_MIN(SUM([col]), -3, 0)` | `moving_min ( sum ( [table::col] ) , 3 , 0 , [table::sort_attr] )` | |

### Syntax

```
moving_sum ( measure , start_offset , end_offset , sort_attr1 [, sort_attr2 ...] )
```

- `start_offset` = rows before current row (positive integer; Tableau uses negative → negate)
- `end_offset` = rows after current row (0 = current row, negative in Tableau → negate)
- `sort_attr` = the attribute(s) that define the row ordering

### Offset conversion (Tableau → ThoughtSpot)

| Tableau offset pair | ThoughtSpot (start, end) | Meaning |
|---|---|---|
| `-3, 0` | `3, 0` | 3 rows before through current row |
| `-3, 3` | `3, -3` | 3 rows before through 3 rows after |
| `0, 0` | `0, 0` | Current row only |
| `FIRST(), 0` | Use `cumulative_*` instead | From first row to current |

### Key difference: sort attribute is required

Tableau's `WINDOW_*` functions inherit their sort order from the visualization context
(the dimension on the Rows/Columns shelf). ThoughtSpot's `moving_*` functions require
explicit sort attribute arguments — there is no implicit context.

When translating:
1. Identify the sort dimension from the Tableau worksheet's shelf configuration
   (typically a date column on the Columns shelf)
2. Pass it as the trailing attribute argument(s) to `moving_*`
3. If the sort dimension cannot be determined, fall back to a pass-through function
   or omit-and-log

**Limitation:** Tableau WINDOW_* functions can partition implicitly via the Tableau
Compute Using / Addressing setting. ThoughtSpot `moving_*` functions do not have
partition arguments — partitioning is determined dynamically by which attributes
appear in the search query. If explicit partitioning is required, use a pass-through
function with `PARTITION BY` in the SQL string instead.

---

## Rank Functions

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `RANK(SUM([col]))` | `rank ( sum ( [table::col] ) )` | Descending by default |
| `RANK(SUM([col]), 'asc')` | `rank ( sum ( [table::col] ) , 'asc' )` | |
| `RANK_UNIQUE(SUM([col]))` | `rank ( sum ( [table::col] ) )` | ThoughtSpot `rank` is always dense; no RANK_UNIQUE equivalent |

**Partitioned rank** — ThoughtSpot's native `rank()` has no partition support. For
partitioned rank, use a pass-through function (see "Pass-Through Fallback" below):
```
sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [table::region] , [table::revenue] )
```

**Limitations:**
- `RANK_MODIFIED`, `RANK_DENSE` have no exact native equivalents; use `rank()` as an approximation and document the difference

---

## Aggregate Formulas: Row-Level Conversion

Tableau calculated fields that use aggregation functions (`COUNTD`, `SUM`, `COUNT`) are aggregate formulas. ThoughtSpot **model formulas must be row-level**. Convert them to row-level expressions; the aggregation is applied at the search/answer level.

**Tableau (aggregate):**
```
COUNTD(if [source_table] = 'terminations' then [employee_id] end)
```

**ThoughtSpot model formula (row-level):**
```
if ( [table::source_table] = 'terminations' ) then [table::employee_id] else ''
```

---

## Pass-Through Fallback (Last Resort)

When a Tableau formula has a valid Snowflake SQL equivalent but no native ThoughtSpot
function, use a **pass-through function** to embed the raw SQL. Pass-through functions
are a last resort — always prefer native ThoughtSpot functions first.

See `ts-snowflake-formula-translation.md` "Pass-Through Functions" for the full
reference. Summary below.

### Variants

Choose by return type and whether the SQL contains aggregation/windowing:

| Non-aggregate (scalar) | Aggregate / window | Returns |
|---|---|---|
| `sql_bool_op` | `sql_bool_aggregate_op` | BOOL |
| `sql_int_op` | `sql_int_aggregate_op` | INT |
| `sql_double_op` | `sql_double_aggregate_op` | DOUBLE |
| `sql_string_op` | `sql_string_aggregate_op` | VARCHAR |
| `sql_date_op` | `sql_date_aggregate_op` | DATE |

### Syntax

```
sql_<type>_aggregate_op ( "SQL expression with {0}, {1} placeholders" , column_0 , column_1 )
```

- `{0}`, `{1}`, etc. are positional column references (zero-indexed)
- The SQL expression must be valid for the target warehouse (Snowflake, Databricks, etc.)
- Aggregation must be **inside** the SQL string — ThoughtSpot adds referenced columns to
  GROUP BY, so `sum({0})` works but bare `{0}` causes SQL errors

### Tableau patterns rescued by pass-through

| Tableau | Pass-through ThoughtSpot formula | Notes |
|---|---|---|
| `RANK(SUM([col]))` partitioned | `sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [table::dim] , [table::measure] )` | Native `rank()` has no partition support |
| `DENSE_RANK(SUM([col]))` | `sql_int_aggregate_op ( "dense_rank() over (order by sum({0}) desc)" , [table::col] )` | |

### Rules

1. **Last resort only** — use native ThoughtSpot functions (LOD → `group_aggregate`,
   running → `cumulative_*`, rank → `rank()`) before falling back to pass-through
2. **Aggregation inside the SQL string** — ThoughtSpot adds columns to GROUP BY; bare
   column references without aggregation cause errors
3. **Wrap complex window functions in `group_aggregate()`** — prevents query generation
   errors when partition columns or date parts are involved:
   ```
   group_aggregate ( sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [table::dim] , [table::measure] ) , query_groups () + { dim } , query_filters () )
   ```
4. **No validation** — ThoughtSpot does not validate the SQL string; errors surface at
   query time from the warehouse
5. **Pass-through must be enabled** — admins can disable via Admin > Search & SpotIQ >
   SQL Passthrough Functions. Document usage in `MIGRATION_LIMITATIONS.md`

### Translation priority order

When converting a Tableau formula, try in this order:

1. **Native ThoughtSpot function** — direct mapping from the Function Mapping table
2. **LOD / cumulative / rank** — sections above
3. **Pass-through function** — this section (embed valid Snowflake SQL)
4. **Omit and log** — truly untranslatable (next section)

---

## Untranslatable Patterns

These Tableau features have no ThoughtSpot equivalent. When encountered during
conversion, apply the **omit-and-log** convention:

1. **Omit** the formula from the model TML `formulas[]` section entirely
2. **Omit** the corresponding `columns[]` entry that would reference it
3. **Log** the omission as a row in `MIGRATION_LIMITATIONS.md`

Never generate a placeholder or stub formula — incorrect syntax fails the entire
model import. A missing formula produces a functional model with reduced coverage.

| Tableau Feature | Reason |
|---|---|
| `LOOKUP()` | Table calculation — references rows by offset; no SQL equivalent |
| `INDEX()` | Table calculation — row numbering without aggregation context |
| `ISMEMBEROF()` | User-specific function — no equivalent |
| `SIZE()`, `FIRST()`, `LAST()` | Table calculations — partition-aware row addressing; no SQL equivalent |
| `PREVIOUS_VALUE()` | Recursive table calculation — no SQL equivalent |
| `RAWSQL_*()` | Direct SQL passthrough — not portable across warehouses |
| References to SQL-lookup Tableau Parameters | ThoughtSpot `list_config` only supports static values; SQL-populated parameter lists need manual recreation |

**Formerly untranslatable, now mapped:**
- `{FIXED ...}`, `{INCLUDE ...}`, `{EXCLUDE ...}` → `group_aggregate()` (see LOD section)
- `RUNNING_SUM`, `RUNNING_AVG`, etc. → `cumulative_sum()`, `cumulative_average()`, etc. (see Running/Cumulative section)
- `RANK()` → `rank()` (see Rank section)
- `WINDOW_SUM`, `WINDOW_AVG`, etc. → `moving_sum()`, `moving_average()`, etc. (see Window / Moving section); fall back to pass-through when sort dimension cannot be determined
- `RANK_MODIFIED`, `RANK_DENSE` → `sql_int_aggregate_op()` pass-through
- Partitioned `RANK` → `sql_int_aggregate_op()` with `partition by`

---

## Parameter References

Tableau formulas can reference parameters via `[Parameters].[Parameter Name]`. This is
Tableau's cross-datasource parameter reference syntax — the formula evaluates to a
user-selected value at runtime.

**Detection pattern:** `[Parameters].[` in the formula text.

**Common patterns in production workbooks:**

| Pattern | Tableau | Purpose |
|---|---|---|
| Dimension selector | `CASE [Parameters].[Dimension Picker] WHEN 'Revenue' THEN [Revenue] WHEN 'Units' THEN [Units] END` | User picks which metric to display |
| Threshold filter | `IF [Metric] > [Parameters].[Threshold] THEN 'Above' ELSE 'Below' END` | User sets a numeric cutoff |
| Date granularity | `CASE [Parameters].[Date Grain] WHEN 'day' THEN DATEPART('day', [Date]) WHEN 'month' THEN DATEPART('month', [Date]) END` | User picks date roll-up |

### Auto-migratable parameters (static list or range)

ThoughtSpot supports `model.parameters[]` with `list_config` (fixed choice list) and
`range_config` (numeric range). Tableau parameters with static `<member>` values or
`<range>` bounds map directly:

| Tableau | ThoughtSpot TML |
|---|---|
| `param-domain-type="list"` + `<member>` values | `list_config.list_choice[]` |
| `param-domain-type="range"` + `<range min max>` | `range_config` (numeric types only) |
| `param-domain-type="any"` | Free-form (no config) |

**Formula translation:** `[Parameters].[Currency]` → `[Currency]` (strip prefix).
ThoughtSpot parameter references use bare `[Name]` syntax with no table qualifier.

**Value cleanup:**
- Strip wrapping double quotes from member values: `'"USD"'` → `USD`
- Strip `#` delimiters from date defaults: `#2026-05-10#` → format as `MM/DD/YYYY`
- `default_value` is always a string in ThoughtSpot TML regardless of `data_type`

### SQL-lookup parameters (query at migration time)

Tableau parameters whose list values come from a database query (no static `<member>`
elements in the TWB) can still be auto-migrated — query the warehouse at migration
time to populate `list_config.list_choice[]` with a snapshot of the current values.

**Migration-time approach:**
1. Extract the SQL query or column reference that populates the parameter in Tableau
2. Execute the query against the connected warehouse (Snowflake/Databricks) via the
   connection established in Step 4
3. Use the distinct values from the result set as `list_choice[]` values
4. Document in `MIGRATION_LIMITATIONS.md` that these values are a point-in-time snapshot
   — if the underlying data changes, the parameter list goes stale

**Ongoing sync:** ThoughtSpot's `list_config` is static — it has no live-query
capability. A future `/ts-recipe-parameter-sync` skill could periodically re-query the
warehouse and update the parameter's `list_choice[]` values via TML export/modify/import.
This is not part of the migration skill but is a natural follow-up.

**Audit mode note:** In audit mode (no auth, no connection), SQL-lookup parameters
are classified as **Parameter ref (query)** — auto-migratable at migration time but
requires a live connection. The audit report flags them separately from static params.

**Scale note:** In production workbooks, parameter references can account for 10–50%
of all calculated fields (observed up to 131 in a single datasource). With auto-migration
of both static and query-based parameters, all parameter-referencing formulas are
translatable during migration.

---

## Data Type Mapping (Tableau → ThoughtSpot)

| Tableau `datatype` | ThoughtSpot `data_type` |
|---|---|
| `string` | `VARCHAR` |
| `integer` | `INT64` — **never `INT`** (ThoughtSpot rejects `INT`) |
| `real` | `DOUBLE` |
| `boolean` | `BOOL` |
| `date` | `DATE` |
| `datetime` | `DATETIME` |

---

## HTML Entity Decoding

Tableau formulas in TWB XML are HTML-encoded. Decode before translating:

| HTML entity | Character |
|---|---|
| `&quot;` | `"` |
| `&amp;` | `&` |
| `&lt;` | `<` |
| `&gt;` | `>` |
| `&#39;` | `'` |
