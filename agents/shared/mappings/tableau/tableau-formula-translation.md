# Tableau → ThoughtSpot Formula Translation

Reference for converting Tableau calculated field expressions to ThoughtSpot TML formula expressions.

---

## Function Mapping

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `IF cond THEN a ELSE b END` | `if ( cond ) then a else b` | Parentheses required around condition. **A final `else` clause is mandatory** — omitting it causes "Unknown data type" errors. Use `else null` or a type-appropriate default. |
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
| `FIND(s, sub)` | `strpos ( s , sub )` | 1-based, returns 0 when absent — identical contract to Tableau FIND, so `FIND(...) > 0` idioms translate unchanged (live-verified 2026-06-13: strpos('needle_haystack','needle')=1, not-found=0). NOTE: official TS docs describe strpos as 0-based/−1 — live behavior differs; trust this entry. |
| `REPLACE(s, old, new)` | `sql_string_op ( "replace({0}, old, new)" , s )` | No native `replace()`; use SQL passthrough. Verified live (VALIDATE_ONLY 2026-07-03). |
| `UPPER(s)` | `sql_string_op ( "upper({0})" , s )` | No native `upper()`; use SQL passthrough. Verified live (VALIDATE_ONLY 2026-07-03). |
| `LOWER(s)` | `sql_string_op ( "lower({0})" , s )` | No native `lower()`; use SQL passthrough. Verified live (VALIDATE_ONLY 2026-07-03). |
| `TRIM(s)` | `sql_string_op ( "trim({0})" , s )` | No native `trim()`; use SQL passthrough. Verified live (VALIDATE_ONLY 2026-07-03). |
| `SPLIT(s, delim, n)` | Use `substr`/`strpos` combination | No direct equivalent; chain: Tableau `SPLIT` → Snowflake `SPLIT_PART` → ThoughtSpot `substr`/`strpos` |
| `DATEDIFF('day', a, b)` | `diff_days ( b , a )` | **Arg order reversed vs Tableau.** TS `diff_*` takes `(end, start)` (see formula-patterns.md "Argument order note"); Tableau `DATEDIFF(unit, start, end)` returns end−start. Same flip for `diff_months`, `diff_years`, `diff_time` (seconds). `'hour'`/`'minute'` → `diff_time ( b , a ) / 3600` / `/ 60`. `'week'` → `diff_days ( b , a ) / 7` — boundary-crossing + week-start semantics differ from Tableau — verify per workbook. |
| `DATETRUNC('month', d)` | `start_of_month ( d )` | Also `start_of_quarter`, `start_of_week`, `start_of_year` |
| `DATETRUNC('week', TODAY()) + 1` | `add_days ( start_of_week ( today () ) , 1 )` | Do NOT use + operator on dates |
| `DATEADD('day', n, d)` | `add_days ( d , n )` | Also `add_months`, `add_years`, `add_weeks`, and (verified live) `add_minutes ( d , n )` / `add_seconds ( d , n )`. **`add_hours` is NOT a valid function** — it fails parsing ("Search did not find"). For hour arithmetic use `add_minutes ( d , n * 60 )`. |
| `DATEPART('month', d)` | `month_number ( d )` | Also `day()` (day of month), `year`, `quarter_number`, `day_number_of_week`, `day_number_of_quarter`, `day_number_of_year` |
| `DATENAME('month', d)` | `month ( d )` | Returns month name (e.g. "January"). Use `month_number()` if numeric value needed |
| `TODAY()` | `today ()` | |
| `NOW()` | `now ()` | |
| `DATE(d)` | `date ( d )` | Does not accept string literals |
| `YEAR(d)` | `year ( d )` | |
| `MONTH(d)` | `month_number ( d )` | |
| `DAY(d)` | `day ( d )` | **`day_number_of_month` does not exist** (verified 2026-06-13). `day()` extracts day-of-month. Related: `day_number_of_week`, `day_number_of_quarter`, `day_number_of_year` do exist. |
| `INT(x)` | `if ( x >= 0 ) then floor ( x ) else ceil ( x )` | Tableau INT truncates toward zero; `to_integer`/`round` round to nearest (live-verified 2026-06-13: to_integer(8.6)=9, to_integer(-9.7)=-10) so a composite is required. |
| `FLOAT(x)` | `to_double ( x )` | See formula-patterns.md (to_double). `x * 1.0` breaks for string inputs Tableau accepts. |
| `STR(x)` | `to_string ( x )` | Tableau's `'#'` number format is **not valid** in TS — strip it. Only strftime formats (`%m/%d/%y`) are valid for dates. |
| `[a] + [b]` (string concat) | `concat ( [a] , [b] )` | ThoughtSpot `concat()` accepts **2 or more** arguments — `concat ( a , ' - ' , b )` is valid, no nesting needed. The `+` operator is numeric-only and **fails on strings** (*"Search did not find '+ ...'"*). Tableau overloads `+` for both; rewrite every string `+` as `concat()`. E.g. `STR(ROUND(x,2)) + '%'` → `concat ( to_string ( round ( x , 2 ) ) , '%' )`. |
| `x IN ('a', 'b')` | `x in { 'a' , 'b' }` | ThoughtSpot uses **curly braces**, not parentheses. Also supports `not in { }`. |
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
| `SQUARE(x)` | `pow ( x , 2 )` | `sq ( x )` is also valid (verified live) — the native single-argument square. |
| `STDEV(x)` | `stddev ( x )` | Aggregate only |
| `MEDIAN(x)` | `median ( x )` | Aggregate only |
| `PERCENTILE(x, k)` | `percentile ( x , k , 'asc' )` | **3 arguments, verified live** — `(measure, fraction 0–1, 'asc'\|'desc')`. The first arg is the **raw measure column**, NOT a nested aggregate: `percentile ( sum ( [m] ) , ... )` fails. The 3rd arg is **required and must be text** `'asc'` or `'desc'` (a numeric 3rd arg errors "expects 3rd argument to be Text"). Use `'asc'` to match Tableau's default ascending percentile. |
| `DATEPART('dayofyear', d)` | `day_number_of_year ( d )` | |
| `DATEPART('weekday', d)` | `day_of_week ( d )` | |
| `DATEPART('hour', d)` | `hour_of_day ( d )` | |
| `DATEPART('quarter', d)` | `quarter_number ( d )` | |
| `DATEPART('week', d)` | `week_number_of_year ( d )` | |

### Year-over-year / period comparisons — make them dynamic, don't copy hardcoded years

Tableau workbooks routinely **hardcode** the comparison years because the author froze them to
the data they had — e.g. `IF YEAR([Order Date]) = 2019 THEN [Sales] END` ("previous year") and
`= 2020` ("current year"). A literal translation bakes in 2019/2020 forever. Prefer the
**dynamic, relative-to-today** form so the calc keeps working as data rolls forward:

| Intent | Hardcoded (as authored) | Dynamic ThoughtSpot |
|---|---|---|
| Current-year measure | `if ( year([d]) = 2020 ) then [m] else 0` | `sum ( if ( year ( [t::d] ) = year ( today ( ) ) ) then [t::m] else 0 )` |
| Prior-year measure | `if ( year([d]) = 2019 ) then [m] else 0` | `sum ( if ( year ( [t::d] ) = year ( add_years ( today ( ) , -1 ) ) ) then [t::m] else 0 )` |

**Surface the data-fidelity tradeoff (don't switch silently).** Dynamic-to-`today()` is correct
for a live/refreshing source, but returns **0 / N/A on a frozen demo dataset** whose latest year
is in the past (e.g. 2019–2020 data when `today()` is 2026). When the workbook's data doesn't
reach the current year, tell the user and offer: (a) keep dynamic (correct for production, empty
on this demo), or (b) anchor to the dataset's actual latest year so it demos now. Note that
`max([date])` is **not** allowed inside a formula filter, so "latest year in data" can't be
expressed as `year(max([d]))` in the conditional — anchoring means a literal year.

---

## ThoughtSpot Formula Syntax Rules

1. **Spaces around operators and parentheses** — `if ( a = b ) then c else d` (not `if(a=b)`)
2. **Single quotes for string literals** — `'value'` (not `"value"`)
3. **Square brackets for column references** — `[table::column]` or `[formula_id]`
4. **Boolean literals** — lowercase `true` / `false`
5. **Boolean operators** — `and`, `or`, `not` (lowercase)
6. **No semicolons or statement terminators**
7. **`to_date()` requires exactly 2 arguments** — `to_date ( '2019-07-31' , 'yyyy-MM-dd' )`

### Don't create redundant pass-through formulas

A Tableau workbook often has calculated fields that **just restate a physical column** —
`Total sales = SUM([Sales])`, `Monthly sales = [Sales]` (or a tautological `IF` that reduces to
`[Sales]`). In ThoughtSpot the physical `Sales` column is already a measure that aggregates as
`sum` by default, so these formulas add a duplicate that means the same thing. **Detect and
drop them:**
- A formula whose expression is exactly `SUM([col])` / `AVG([col])` / `[col]` of an existing
  physical column (no other transformation) → **don't create it; use the physical column**
  (e.g. reference `[Sales]` directly). Repoint anything that referenced the formula at the
  physical column.
- Two formulas that reduce to the **same expression** → keep **one**, drop the rest.
- **Note each collapse in the migration report** (status ⊘ "redundant — use physical `[col]`")
  so the reviewer sees the field wasn't lost, just deduplicated.

Keep the formula only when it adds something the physical column can't express (a different
aggregation surfaced as its own column, a rename the rest of the model depends on, etc.).

---

## LOD Expressions → `group_aggregate()`

Tableau Level of Detail (LOD) expressions map to ThoughtSpot's `group_aggregate()`
function. Chain: Tableau LOD → Snowflake `OVER (PARTITION BY ...)` → ThoughtSpot
`group_aggregate()`. See `ts-snowflake-formula-translation.md` "Level of Detail (LOD)
Functions" for the full `group_aggregate` reference.

| Tableau LOD | ThoughtSpot | Notes |
|---|---|---|
| `{FIXED [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , { [dim] } , {} )` | Fixed grain — dimension refs **must use brackets** `[dim]` inside `{ }` |
| `{FIXED [d1], [d2] : AVG([col])}` | `group_aggregate ( average ( [table::col] ) , { [d1] , [d2] } , {} )` | Multiple dimensions in partition |
| `{INCLUDE [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , query_groups () + { [dim] } , query_filters () )` | Adds dimension to whatever the query already groups by |
| `{EXCLUDE [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , query_groups () - { [dim] } , query_filters () )` | Removes dimension from the query's grouping |
| `{FIXED : MAX([col])}` (no dims) | `group_aggregate ( max ( [table::col] ) , { } , { } )` | Grand FIXED — single scalar across entire dataset (e.g. global max date). Same as no-keyword form below. |
| `{SUM([col])}` (no LOD keyword) | `group_aggregate ( sum ( [table::col] ) , {} , query_filters () )` | Grand total — no partitioning. **Default to `query_filters()`** so the result respects the user's search filters (see "No-keyword LOD filter context" below). Use `{}` only when the formula must ignore filters (rare). |
| `{COUNTD([col])}` (no LOD keyword) | `group_aggregate ( unique count ( [table::col] ) , {} , query_filters () )` | Grand distinct count. Same `query_filters()` default. Common pattern: `{COUNTD([ID])} = 1` to detect single-record context. |
| `{MEDIAN([col])}` (no LOD keyword) | `group_aggregate ( median ( [table::col] ) , {} , query_filters () )` | Grand median. Same `query_filters()` default. |
| `{ATTR([col])}` (no LOD keyword) | `group_aggregate ( max ( [table::col] ) , {} , query_filters () )` | ATTR approximated with `max` — verify the column is constant within the grand-total grain. |
| `TOTAL(SUM([col]))` | `group_aggregate ( sum ( [table::col] ) , {} , query_filters () )` | Table-calc grand total that **respects filters** — `{}` grouping (whole table) + `query_filters()`. Use this as the denominator for percent-of-total. |
| `SUM([x]) / TOTAL(SUM([x]))` (percent of total) | `sum ( [table::x] ) / group_aggregate ( sum ( [table::x] ) , {} , query_filters () )` | Common idiom: row/group value ÷ filtered grand total |

`TOTAL(agg)` is a Tableau table calculation, but the common `TOTAL(SUM(...))` / percent-of-total
case has a clean LOD translation (above) — same `group_aggregate` family Snowflake/Databricks
use. Other `TOTAL()` partitionings (e.g. along a specific pane direction) may still need
pass-through.

### Compound LOD patterns (from production workbooks)

These patterns appear frequently in real Tableau workbooks and must be converted
correctly. They combine FIXED with conditionals, nesting, or shorthand syntax.

**1. Table-scoped shorthand `{AGG([col])}` — passthrough, no conversion needed**

ThoughtSpot supports `{agg([col])}` natively (grand aggregate over the entire table).
Do NOT convert to `group_aggregate` — leave as-is with lowercase function name.

| Tableau | ThoughtSpot |
|---|---|
| `{MAX([SEND_DATE])}` | `{max([SEND_DATE])}` |
| `{MIN([SEND_DATE])}` | `{min([SEND_DATE])}` |
| `{MAX([RUN_DATE])}` | `{MAX([RUN_DATE])}` |

**2. Global FIXED (no dimensions) `{ FIXED : AGG(...) }` → `group_aggregate(..., {}, {})`**

When FIXED has no dimension list (just `: AGG(...)`), it computes a global aggregate
across all rows, ignoring the viz's grouping. Map to `group_aggregate` with empty
dimension and filter args.

| Tableau | ThoughtSpot |
|---|---|
| `{ FIXED : MAX([FISCAL_YEAR_NUM]) }` | `group_aggregate(max([FISCAL_YEAR_NUM]), {}, {})` |

**3. Conditional FIXED `{ FIXED : AGG(IF ... THEN ... END) }`**

FIXED with an inner IF/CASE filters which rows contribute to the aggregate.
Convert the inner IF to ThoughtSpot syntax, wrap in `group_aggregate`. The inner
`END` becomes `else null` (ThoughtSpot requires an explicit else).

| Tableau | ThoughtSpot |
|---|---|
| `{ FIXED : MAX(IF [YEAR] = [calc] THEN [MONTH] END) }` | `group_aggregate(max(if ([YEAR] = [formula_calc]) then [MONTH] else null), {}, {})` |
| `{ FIXED : MIN(IF [YEAR] = INT(LEFT([Param], 4)) AND [WEEK] = INT(RIGHT([Param], 2)) THEN [DATE] END) }` | `group_aggregate(min(if ([YEAR] = to_integer(LEFT([Param Name], 4)) and [WEEK] = to_integer(RIGHT([Param Name], 2))) then [DATE] else null), {}, {})` |

**4. Multi-branch conditional FIXED**

FIXED with a multi-branch IF inside (e.g. fiscal MTD vs YTD vs YoY). Convert
each branch, chain with `else if`, close with `else null`.

```
Tableau:
{ FIXED : MIN(
    IF [Parameters].[Time Frame] = 'Fiscal MTD'
       AND [FISCAL_YEAR] = [Max Year] AND [FISCAL_MONTH] = [Max Month]
    THEN [SEND_DATE]
    ELSEIF [Parameters].[Time Frame] = 'Fiscal YTD'
       AND [FISCAL_YEAR] = [Max Year]
    THEN [SEND_DATE]
    END
) }

ThoughtSpot:
group_aggregate(min(
    if ([Time Frame] = 'Fiscal MTD'
        and [FISCAL_YEAR] = [formula_Max Year] and [FISCAL_MONTH] = [formula_Max Month])
    then [SEND_DATE]
    else if ([Time Frame] = 'Fiscal YTD'
        and [FISCAL_YEAR] = [formula_Max Year])
    then [SEND_DATE]
    else null), {}, {})
```

**5. Nested FIXED — one FIXED inside another**

The inner FIXED becomes a nested `group_aggregate` call. Both levels convert
independently.

| Tableau | ThoughtSpot |
|---|---|
| `{ FIXED : MAX(IF [X] < { FIXED : MAX([X]) } THEN [X] END) }` | `group_aggregate(max(if ([X] < group_aggregate(max([X]), {}, {})) then [X] else null), {}, {})` |

This pattern computes "second-to-max" — the largest value below the global max.

**6. Dimensioned FIXED with conditional branches**

FIXED with explicit dimensions and an outer CASE/IF that dispatches based on
a parameter. Each branch contains its own `{ FIXED [dims] : AGG(...) }`.
Convert each FIXED independently; wrap the dispatch in `if/else if`.

```
Tableau:
CASE [Parameters].[Metric]
WHEN 'Engagement' THEN
    { FIXED [METRO], [CHANNEL] : SUM([CLICKS]) } /
    { FIXED [METRO], [CHANNEL] : SUM([DELIVERED]) }
WHEN 'Orders' THEN
    { FIXED [METRO], [CHANNEL] : SUM([ORDERS]) } /
    { FIXED [METRO], [CHANNEL] : SUM([DELIVERED]) }
END

ThoughtSpot:
if ([Metric] = 'Engagement') then
    group_aggregate(sum([CLICKS]), {[METRO], [CHANNEL]}, {}) /
    group_aggregate(sum([DELIVERED]), {[METRO], [CHANNEL]}, {})
else if ([Metric] = 'Orders') then
    group_aggregate(sum([ORDERS]), {[METRO], [CHANNEL]}, {}) /
    group_aggregate(sum([DELIVERED]), {[METRO], [CHANNEL]}, {})
else null
```

**7. Calculation ID references inside FIXED → formula references**

Tableau calculation IDs inside FIXED (e.g. `[Calculation_4007288936723431471]`)
must be resolved to the corresponding ThoughtSpot formula name using the
`[formula_<Name>]` convention, same as any other calc-field cross-reference.

| Tableau | ThoughtSpot |
|---|---|
| `[Calculation_6698611864531566593]` (= "Max Fiscal Year") | `[formula_Max Fiscal Year]` |
| `[Calculation_4007288936723316781]` (= "Reporting Max Fiscal Month") | `[formula_Reporting Max Fiscal Month]` |

### No-keyword LOD filter context — `query_filters()` vs `{}`

A no-keyword LOD like `{COUNTD([PROMOTION_ID])}` computes a grand scalar in Tableau.
Crucially, Tableau's no-keyword LODs are computed **after** dimension filters — so when
the user filters a dashboard to a single promotion, `{COUNTD([PROMOTION_ID])}` returns 1,
not the total count across all data.

In ThoughtSpot, the **filter argument** of `group_aggregate` controls this:
- `query_filters()` — respects the user's search filters (matches Tableau's no-keyword LOD behaviour)
- `{}` — ignores all filters (true grand total, always returns the same value)

**Default to `query_filters()`** for no-keyword LODs, but **the behaviour may not be
identical to Tableau**. Tableau computes no-keyword LODs after dimension filters but
before table-calc filters — a specific point in Tableau's order of operations that has
no exact ThoughtSpot equivalent. `query_filters()` respects all active search filters,
which is the closest match but not guaranteed to produce the same results in all cases.

The common pattern `IF {COUNTD([ID])} = 1 THEN ... ELSE ...` is a context-detection
formula that checks whether the user is looking at one record or many. With
`query_filters()` it responds to the user's search filters (likely correct). With `{}`
it always sees the full dataset (likely wrong for this use case). But edge cases exist —
particularly when the Tableau workbook relies on the specific filter ordering.

**Syntax rules for `group_aggregate`:**
- Dimensions use curly braces with **bracket-enclosed** column names: `{ [dim1] , [dim2] }` — bare names without brackets fail validation
- `query_groups()` and `query_filters()` are ThoughtSpot keywords, not column references
- The inner aggregate (`sum`, `average`, `max`, `min`, `unique count`) follows standard ThoughtSpot formula syntax
- Column references inside `group_aggregate` use `[table::column]` format
- The inner conditional's `END` must become `else null` — omitting it causes "Unknown data type" errors

### Platform limitation: nested `group_aggregate` not supported

Tableau supports nested LOD expressions — e.g. `{FIXED [A] : SUM({FIXED [B] : MAX([col])})}`.
ThoughtSpot does **not** support nesting `group_aggregate()` inside another `group_aggregate()`.
This is a platform limitation, not a translation gap.

**Workaround:** decompose nested LODs into separate formulas:
1. Create the inner LOD as its own formula (e.g. `inner_max = group_aggregate(max([col]), {B}, {})`)
2. Reference it in the outer LOD (e.g. `outer_sum = group_aggregate(sum([inner_max]), {A}, {})`)

This requires two-phase import (the inner formula must exist before the outer one can reference it).

**Detection:** the translation engine flags any output containing two or more `group_aggregate(`
occurrences as a validation warning. In audit mode, classify these as **Platform Limitation**,
not Untranslatable — the formula IS expressible in ThoughtSpot, just not as a single expression.

### Common pattern: relative time via grand FIXED

Tableau authors use `{FIXED : MAX([date])}` (grand FIXED, no dimensions) to get a
global scalar — typically the latest date in the dataset. This appears in relative-time
calculations like "weeks from latest date":

```
# Tableau
DATEDIFF('week', {FIXED : MAX([WEEK_ENDING])}, [WEEK_ENDING])

# ThoughtSpot — group_aggregate with empty grouping = grand scalar
diff_days ( group_aggregate ( max ( [TABLE::WEEK_ENDING] ) , { } , { } ) , [TABLE::WEEK_ENDING] ) / 7
```

**Do not substitute `today()` for `{FIXED : MAX([date])}`** — the Tableau author chose
the dataset's max date deliberately (it may lag behind today, or the data may be
historical). `today()` changes the semantics and produces different filter ranges.

### A predicate inside a FIXED partition is a filter, not a grain

**Do not translate every FIXED dimension as a grouping key.** A common Tableau idiom
puts a **boolean calc** into a `{FIXED ...}` partition *and* pins that boolean to a
single member (`=true`) on the worksheet **Filters shelf**. This is a workaround for
Tableau's order of operations — FIXED LODs are computed *before* categorical filters, so
the author bakes the scoping predicate into the partition to make it bite. The boolean is
doing the job of a **filter**, not defining a real grain: the `false`/`null` rows are
discarded, never shown as their own bucket.

**Detection** — both must be true:
1. A member of a `{FIXED ...}` partition is a calculated field that acts as a filter
   predicate — either boolean-valued (`true`/`false`) or string-valued with a small
   set of states where only one is used (e.g. `'in range'`/`'out of range'`).
2. That same field appears on the worksheet `<filter class='categorical'>` shelf with a
   `<groupfilter function='member' member='true' ...>` (or any single pinned member),
   **OR** is filtered to a single value in the dashboard's search query / filter bar.

**Translation** — move the predicate from the grouping set into the **filter argument**
(the 3rd `group_aggregate` argument), and keep only the real dimensions in the grouping:

| Tableau LOD | ThoughtSpot | Notes |
|---|---|---|
| `{FIXED [acct], [boolFlag] : SUM([col])}` where `[boolFlag]` is filtered `=true` | `group_aggregate ( sum ( [t::col] ) , { [acct] } , { [boolFlag] = true } )` | Predicate → filter arg; only `[acct]` is the grain |

The filter is a **hard literal `{ predicate = true }`, not `query_filters()`** — because
FIXED deliberately ignores the viz's other filters. (Use `query_filters() + { predicate
= true }` only when the LOD should additionally respect viz filters, which diverges from
FIXED semantics — surface the choice rather than assuming.)

Equivalent inline form when you'd rather not emit a separate flag column:
`group_aggregate ( sum ( if ( <predicate> ) then [t::col] else 0 ) , { [acct] } , {} )`.

**Worked illustration (from `Weighted Usage.twb`, live-verified 2026-06-19):**

```
# Tableau — lookback filter is a parameter-driven date-window predicate,
# filtered ='in range' on worksheets. Returns 'in range' / 'out of range' (string, not boolean).
tot_weighted_usage = {FIXED [MBX_ACCT_ID], [lookback filter] : SUM([WEIGHTED_USAGE])}

# WRONG (mechanical) — predicate as grain → emits separate in-range/out-of-range totals per account
group_aggregate ( sum ( [t::WEIGHTED_USAGE] ) , { [MBX_ACCT_ID] , [lookback filter] } , {} )

# WRONG (I9) — formula cross-ref in grouping fails during TML import
# ("Search did not find 'lookback filter'")
group_aggregate ( sum ( [t::WEIGHTED_USAGE] ) , { [MBX_ACCT_ID] , [lookback filter] } , {} )

# RIGHT — predicate as filter via query_filters() → respects the search-level
# [lookback filter].'in range' constraint. Use query_filters() when the predicate
# is already applied as a search/dashboard filter (common for FIXED + filter-shelf pattern).
group_aggregate ( sum ( [t::WEIGHTED_USAGE] ) , { [MBX_ACCT_ID] } , query_filters ( ) )

# ALSO RIGHT — hard literal filter when you want to enforce the value regardless
# of whether the user has it in their search query:
group_aggregate ( sum ( [t::WEIGHTED_USAGE] ) , { [MBX_ACCT_ID] } , { [lookback filter] = 'in range' } )
# (Note: this form requires the formula column to already exist on the model — it will fail
# during first import due to I9. Use query_filters() or the inline-if workaround instead.)
```

> Note: a column literally named `WEIGHTED_USAGE` is **pre-weighted at source** — this LOD
> just sums it. It is *not* a weighted-average computation. See "Weighted average" below
> for the fork between pre-weighted columns and weights computed in ThoughtSpot.

### Weighted average

A field or workbook named "weighted …" is **not** evidence of a weighted-average
*calculation* — read the actual expression. There are two distinct situations, and they
translate completely differently:

| Situation | How to recognize it | Translation |
|---|---|---|
| **Pre-weighted at source** | The weighting is already baked into a physical column (e.g. `WEIGHTED_USAGE`); the workbook only `SUM()`s / LOD-aggregates it | Plain `sum ( [t::col] )` or `group_aggregate ( sum ( [t::col] ) , { grain } , … )`. **Do not** wrap a weighted-average template around it — that double-counts the weight. |
| **Computed in-tool** | The workbook divides a weighted sum by a weight sum, e.g. `SUM([value]*[weight]) / SUM([weight])` (viz-level or inside an LOD) | See the computed weighted-average pattern in `thoughtspot-formula-patterns.md` → "Weighted average" |

The headline rule: **establish which situation you are in before emitting anything.** The
pre-weighted case is the more common one in the wild and needs no special handling beyond
getting the grain right.

---

## Tableau Bins → bucketing formula

A Tableau **bin** field (a `<column>` whose `<calculation class='bin'>` discretizes a
continuous field) is translatable — it floors the source field to multiples of the bin
size, anchored at `peg`. The `<calculation>` attributes give everything needed:

```
<calculation class='bin' formula='[Age]' size-parameter='[Parameters].[Age (bin) Parameter]' peg='0' .../>
```

| Attribute | Meaning |
|---|---|
| `formula` | the source field being binned (`[Age]`) |
| `size-parameter` | the bin width — a Tableau **parameter** (migrate it per the Parameters section); resolve to its ThoughtSpot parameter **caption** |
| `peg` | the bin anchor/offset (usually `0`) |

Translation (peg = 0):

```
floor ( [table::field] / [Bin Size Param] ) * [Bin Size Param]
```

General form (peg ≠ 0):

```
floor ( ( [table::field] - peg ) / [Bin Size Param] ) * [Bin Size Param] + peg
```

**Row-level by default.** A bare column reference inside a formula (`[BALANCE]`) is
**scalar / row-level** — the column's default aggregation does **not** apply unless you write
it explicitly (`sum([BALANCE])`). So `floor([BALANCE]/size)*size` bins each row correctly
**even when the source column is modelled as a `SUM` measure** — no need to add a separate
"scalar" attribute. (Aggregation in formulas is always explicit: `sum()`, `average()`, etc.)

The result is an **attribute** (it groups rows into buckets). Examples (dynamic, parameter-driven size):

| Tableau bin | ThoughtSpot formula |
|---|---|
| `Age (bin)` size = param `Age Groups`, peg 0 | `floor ( [Age] / [Age Groups] ) * [Age Groups]` |
| `Balance (bin)` size = param `Balance (bin) Parameter`, peg 0 | `floor ( [Balance] / [Balance (bin) Parameter] ) * [Balance (bin) Parameter]` |

### Two ways to translate a bin — pick by whether the size is dynamic

| Bin size | Approach | Why |
|---|---|---|
| **Dynamic** (driven by a Tableau parameter) | `floor()` **formula** referencing the parameter (above) | The bucket width must change when the user changes the parameter — only a formula can do that. |
| **Fixed** (a literal bin size, no parameter) | a **cohort (column set) TML object** — `cohort_grouping_type: BIN_BASED` | Native ThoughtSpot binning; cleaner than a formula, and shows as a proper set on the column. |

A fixed-size bin becomes a separate **`cohort:` TML object** bound to the model (worksheet)
by `obj_id`. See [../../schemas/thoughtspot-sets-tml.md](../../schemas/thoughtspot-sets-tml.md)
for the full schema. Shape:

```yaml
cohort:
  name: Age Bins
  worksheet:
    id: P1-UK-Bank-Customers
    name: P1-UK-Bank-Customers
    obj_id: P1-UK-Bank-Customers-5235898b   # the model's obj_id ({NameNoSpaces}-{guid8})
  config:
    cohort_type: SIMPLE
    anchor_column_id: Age                    # the model column being binned
    cohort_grouping_type: BIN_BASED
    bins:
      minimum_value: 0.0
      maximum_value: 90.0
      bin_size: 10.0
```

**Prompt the user** for `minimum_value`, `maximum_value`, and `bin_size` (suggest the Tableau
bin parameter's default as the `bin_size`). If the user can't supply the range, **a warehouse
lookup is an acceptable fallback** (e.g. `SELECT MIN(col), MAX(col) …` — with the user's
authorization, since it's a live read). Prefer prompting; fall back to the DB lookup. Import
the cohort **after** the model.

**The model must have a set `obj_id` for the cohort to bind.** A freshly created model has
**no** `obj_id` (export shows `obj_id: None`), and a cohort that references it by `fqn`
(GUID) alone fails with *"Worksheet not found"*. Fix: set the model's `obj_id` explicitly
(root `obj_id: {ModelNameNoSpaces-or-hyphenated}-{guid8}`, e.g. `P1-UK-Bank-Customers-5235898b`),
re-import the model in place (root `guid` + `--no-create-new`), then have the cohort's
`worksheet.obj_id` point at that same value. (This is also the `obj_id` a liveboard viz uses
to bind to the model — set it once, reuse everywhere.)

### `Number of Records` / row counts → `count([column])`

Tableau's auto-generated **`Number of Records`** field (`formula = 1`) is a row count. Don't
translate it to `sum ( 1 )` — that's opaque. Translate it to a real **`count()` of a chosen
column**, and **prompt the user for which column** (default to the table's primary key / a
non-null id):

```
Number of Records → count ( [TABLE::CUSTOMER_ID] )      # user picks the column
SUM([Number of Records]) → count ( [TABLE::CUSTOMER_ID] )
```

Carry the same choice into any formula that builds on it (e.g. percent-of-total):

```
Calculation1 → count ( [TABLE::CUSTOMER_ID] )
             / group_aggregate ( count ( [TABLE::CUSTOMER_ID] ) , {} , query_filters () )
```

If the user has no preference, count the primary-key column (counts every row, non-null).

### Manual groups → `GROUP_BASED` cohort (classify by `class`, NOT the field name)

A `<calculation class='categorical-bin'>` is a **manual group** — it assigns explicit source
values to named groups (e.g. specific `[Date Joined]` dates → "Cluster 1/2/3", with a
`default` label for the rest). **Despite a field name like "… (clusters)", this is NOT
statistical clustering — it is translatable** to a `GROUP_BASED` cohort:

```yaml
cohort:
  name: Date Joined (clusters)
  worksheet: { id: ..., name: ..., obj_id: P1-UK-Bank-Customers-5235898b }   # model obj_id, set it first
  config:
    cohort_type: SIMPLE
    anchor_column_id: Date Joined
    cohort_grouping_type: GROUP_BASED
    null_output_value: "Not Clustered"        # the categorical-bin `default`
    combine_non_group_values: true            # bucket everything else under null_output_value
    groups:
    - name: Cluster 1
      combine_type: ALL
      conditions:
      - operator: EQ
        column_name: Date Joined
        filter_value_type: STRING             # REQUIRED on each condition (STRING/DOUBLE/…)
        value: ["2015-04-01", "2015-08-01", ...]   # stored values, NOT Tableau's display format
    - name: Cluster 2
      combine_type: ALL
      conditions:
      - { operator: EQ, column_name: Date Joined, filter_value_type: STRING, value: [ ... ] }
```

Map: `categorical-bin` `<bin value='Cluster 1'>` → a `groups[]` entry; its `<value>` list →
the condition `value[]`; the calc's `default` → `null_output_value` (+ `combine_non_group_values: true`).

**Two things that bite (both confirmed against a working set):**
- Each condition needs **`filter_value_type`** matching the **anchor column's type**, and a
  `combine_type` (use **`ANY`** for set membership — `ALL` ANDs the conditions and matches
  nothing). The condition shape depends on the type:
  - **String/number column** → `filter_value_type: STRING` (or `DOUBLE`/…), `operator: EQ`,
    `value: [...]` (a multi-value list = "in this set").
  - **DATE column** → `filter_value_type: DATE_FILTER`, one condition per value with
    `date_filter_values: [{ type: EXACT_DATE, date: MM/DD/YYYY, oper: "=" }]`, combined with
    `combine_type: ANY`. Dates use **`MM/DD/YYYY`**. (So if you retype the anchor column
    VARCHAR→DATE, the cohort conditions must switch from `STRING`/`value[]` to
    `DATE_FILTER`/`date_filter_values`.)
- **Convert the values to the column's STORED format, not Tableau's display format.** A
  `categorical-bin`'s `<value>` strings are Tableau *display* values (`01.Apr.15`); the
  warehouse column holds something else (`2015-04-01`). Transform every value to match
  what's stored, or the groups match nothing. **If the stored format is unknown, ask the user;
  if they don't know, look it up** (`SELECT <col> … LIMIT 5`, with authorization). (Date
  display `DD.Mon.YY` → ISO `YYYY-MM-DD`.)
- **The group values are a snapshot of the TWB's data and may not exist in the target.** A
  `categorical-bin` enumerates the exact values present when the workbook was authored. If the
  warehouse now holds *different* data (regenerated, refreshed, or a different load), those
  values won't match and every row falls to `null_output_value` — a silently empty grouping.
  Don't just assume — **confirm membership**: prompt the user ("do these values still exist in
  the data?"), or, failing that, do a quick warehouse lookup (with authorization) before
  shipping the cohort. If they genuinely don't match, flag it as a **data-fidelity** limitation
  (not a translation error) and note the cohort is only meaningful once the data contains those
  values. (Also: if the anchor
  column is later retyped — e.g. VARCHAR→DATE — the condition `filter_value_type` and values
  must change to match the new type.)

**Cohort vs. `if/then` formula — decide by group shape.** A manual group can also be an
`if … then … else if … then … else …` formula (ThoughtSpot has **no `CASE`** — always use
the if/then/else-if chain). When each group is a **contiguous, non-overlapping range** of the
source value, that's the *cleanest* translation:

```
if      [x] >= a1 and [x] <= b1 then "Group 1"
else if [x] >= a2 and [x] <= b2 then "Group 2"
else "Other"
```

But this only works for ranges. Check the membership first: parse the `<value>` lists and
see whether each group is a contiguous block. If the groups are **arbitrary / interleaved
value sets** (e.g. dates from a clustering-by-volume that span the whole range), a range
formula misclassifies almost everything — use the **`GROUP_BASED` cohort** (or, if a formula
is required, an explicit membership chain `if [x] = v1 or [x] = v2 or … then "Group 1" …`,
which is faithful but verbose). For a range test on a date stored as a **string**, parse it
first (`to_date(...)`).

**Genuinely untranslatable:** true **statistical clustering** (Tableau's k-means "Clusters",
a different calculation produced by the analytics engine, not `categorical-bin`) — no
ThoughtSpot equivalent; omit + log. **Always classify by the calculation `class`, not the
field's display name.**

---

## Running / Cumulative Functions

Tableau running table calculations map to ThoughtSpot cumulative functions. Chain:
Tableau `RUNNING_*` → Snowflake `SUM/AVG/etc OVER (... ROWS BETWEEN UNBOUNDED PRECEDING
AND CURRENT ROW)` → ThoughtSpot `cumulative_*()`.

> ⚠️ **`cumulative_*` (and `moving_*`) are query-time functions — they CANNOT be stored as
> model/worksheet formula columns.** Adding one to `model.formulas[]` fails validation with
> *"Search did not find …"* (in any form — `cumulative_sum(sum([col]))`, `cumulative_sum([formula_measure])`,
> etc.). They are only valid **inside an answer's `search_query`** (the live query context that
> supplies the sort order). So: do **not** emit a model formula for a `RUNNING_*`/`WINDOW_*`
> field — instead realize it on the **viz that uses it** (Step 10b) via the search keyword
> (`cumulative …`, `moving average of …`) or an answer-level formula. Log it in the Migration
> Summary as "realized at the answer level, not the model."

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

> ⚠️ Like `cumulative_*`, **`moving_*` are query-time only — not valid in model formulas**
> (same *"Search did not find …"* failure). Realize them on the viz (answer `search_query`),
> not in `model.formulas[]`. A composite like `EXP(WINDOW_AVG(LOG([m]), -2, 0))` (a geometric
> moving average) therefore can't be a model column at all — build it as an answer-level
> formula on the one viz that needs it, or flag it as a placeholder if the answer-formula
> nesting (`exp`/`log10` around `moving_average`) is also rejected.

> 🔑 **Pass the worksheet's shelf attribute(s) as the trailing sort args — and reference the
> MEASURE COLUMN by name, not `sum()`.** A running/moving total is meaningless without an order.
> Take the dimension(s) the Tableau worksheet lays the calc *along* (its Rows/Columns shelf —
> e.g. `Month of order date`, `Order Date`) and append them as sort args. The first argument is
> the **measure column by display name** (`[Sales]`), **not** `sum([t::Sales])`: `cumulative_*`/
> `moving_*` reject an already-aggregated arg (*"expects 1st argument to be not aggregated"*) and
> can't resolve a `[t::col]` ref in answer context. So:
> `RUNNING_SUM(SUM([Sales]))` along `[Month]` → `cumulative_sum ( [Sales] , [Month of order date] )`;
> `EXP(WINDOW_AVG(LOG([Sales]),-2,0))` along `[Order Date]` → `exp ( moving_average ( log10 ( [Sales] ) , 2 , 0 , [Order Date] ) )`.

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
| `RANK(SUM([col]))` | `rank ( sum ( [table::col] ) , 'desc' )` | **Direction arg is required** — `rank(measure)` with one arg fails validation (*"Function rank expects 2 arguments, found 1"*). Pass `'desc'` explicitly for Tableau's default. |
| `RANK(SUM([col]), 'asc')` | `rank ( sum ( [table::col] ) , 'asc' )` | |
| `RANK_UNIQUE(SUM([col]), 'desc')` | `rank ( sum ( [table::col] ) , 'desc' )` | ThoughtSpot `rank` is always dense; no RANK_UNIQUE equivalent — document the tie-handling difference. |

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
| True **statistical clustering** (k-means; the analytics-engine "Clusters" calc — **not** `categorical-bin`) | No ThoughtSpot equivalent. NB: `categorical-bin` (manual groups, even when named "… clusters") **is** translatable → `GROUP_BASED` cohort |
| References to SQL-lookup Tableau Parameters | ThoughtSpot `list_config` only supports static values; SQL-populated parameter lists need manual recreation |

**Formerly untranslatable, now mapped:**
- `{FIXED ...}`, `{INCLUDE ...}`, `{EXCLUDE ...}` → `group_aggregate()` (see LOD section)
- `TOTAL(SUM(...))` / percent-of-total → `group_aggregate(..., {}, query_filters())` (see LOD section)
- Tableau **bins** (`class='bin'`) → `floor([x]/size)*size` bucketing formula (see Tableau Bins section)
- `Number of Records` (`= 1`) → `sum(1)`
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
