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
| `FIND(s, sub)` | `strpos ( s , sub )` | 1-based, returns 0 when absent — identical contract to Tableau FIND, so `FIND(...) > 0` idioms translate unchanged (live-verified 2026-06-13, se-thoughtspot: strpos('needle_haystack','needle')=1, not-found=0). NOTE: official TS docs describe strpos as 0-based/−1 — live behavior differs; trust this entry. |
| `REPLACE(s, old, new)` | `replace ( s , old , new )` | |
| `UPPER(s)` | `sql_string_op ( "UPPER({0})" , s )` | No native upper/lower in ThoughtSpot — scalar pass-through (PT1) |
| `LOWER(s)` | `sql_string_op ( "LOWER({0})" , s )` | No native upper/lower in ThoughtSpot — scalar pass-through (PT1) |
| `TRIM(s)` | `trim ( s )` | |
| `SPLIT(s, delim, n)` | Use `substr`/`strpos` combination | No direct equivalent; chain: Tableau `SPLIT` → Snowflake `SPLIT_PART` → ThoughtSpot `substr`/`strpos` |
| `DATEDIFF('day', a, b)` | `diff_days ( b , a )` | **Arg order reversed vs Tableau.** TS `diff_*` takes `(end, start)` (see formula-patterns.md "Argument order note"); Tableau `DATEDIFF(unit, start, end)` returns end−start. Same flip for `diff_months`, `diff_years`, `diff_time` (seconds). `'hour'`/`'minute'` → `diff_time ( b , a ) / 3600` / `/ 60`. `'week'` → `diff_days ( b , a ) / 7` ⚠ flag: boundary-crossing + week-start semantics differ from Tableau — verify per workbook. |
| `DATETRUNC('month', d)` | `start_of_month ( d )` | Also `start_of_quarter`, `start_of_week`, `start_of_year` |
| `DATETRUNC('week', TODAY()) + 1` | `add_days ( start_of_week ( today () ) , 1 )` | Do NOT use + operator on dates |
| `DATEADD('day', n, d)` | `add_days ( d , n )` | Also `add_months`, `add_years` |
| `DATEPART('month', d)` | `month_number ( d )` | Also `day()` (day of month), `year`, `quarter_number`, `day_number_of_week`, `day_number_of_quarter`, `day_number_of_year` |
| `DATENAME('month', d)` | `month_number ( d )` | ThoughtSpot has no month-name function; use number |
| `TODAY()` | `today ()` | |
| `NOW()` | `now ()` | |
| `DATE(d)` | `date ( d )` | Does not accept string literals |
| `YEAR(d)` | `year ( d )` | |
| `MONTH(d)` | `month_number ( d )` | |
| `DAY(d)` | `day ( d )` | **`day_number_of_month` does not exist** (verified 2026-06-13). `day()` extracts day-of-month. Related: `day_number_of_week`, `day_number_of_quarter`, `day_number_of_year` do exist. |
| `INT(x)` | `if ( x >= 0 ) then floor ( x ) else ceil ( x )` | Tableau INT truncates toward zero; `to_integer`/`round` round to nearest (live-verified 2026-06-13: to_integer(8.6)=9, to_integer(-9.7)=-10) so a composite is required. ⚠ floor/ceil names pending live verification (P11/P12) — flag on first use. |
| `FLOAT(x)` | `to_double ( x )` | See formula-patterns.md (to_double). `x * 1.0` breaks for string inputs Tableau accepts. |
| `STR(x)` | `to_string ( x )` | |
| `[a] + [b]` (string concat) | `concat ( [a] , [b] )` | ThoughtSpot uses `concat()` for strings — the `+` operator is numeric-only and **fails on strings** (*"Search did not find '+ ...'"*). Tableau overloads `+` for both; rewrite every string `+` as `concat()`. E.g. `STR(ROUND(x,2)) + '%'` → `concat ( to_string ( round ( x , 2 ) ) , '%' )`. |
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
| `EXP(n)` | `exp ( n )` | |
| `SIN(n)` / `COS(n)` / `TAN(n)` | `sin ( n * 180 / 3.14159265358979 )` / `cos ( n * 180 / 3.14159265358979 )` / `tan ( n * 180 / 3.14159265358979 )` | Tableau trig is in radians; ThoughtSpot trig is in degrees — convert. (Inverse trig `acos/asin/atan` also return degrees in ThoughtSpot vs radians in Tableau.) |
| `DATEPARSE(format, s)` | `to_date ( s , format )` | **Args flipped.** ThoughtSpot `to_date` accepts both `yyyy-MM-dd`-style and strptime `%Y-%m-%d` tokens (both validate live; `%`-codes are the documented canonical form). For common date patterns pass the Tableau format string through unchanged; for time components use strptime. Date-only (drops time). |
| `STARTSWITH(s, sub)` | `strpos ( s , sub ) = 1` | No native `starts_with`. strpos is 1-based so a true prefix is position 1 (live-verified 2026-06-13, se-thoughtspot). |
| `ENDSWITH(s, sub)` | `substr ( s , strlen ( s ) - strlen ( sub ) , strlen ( sub ) ) = sub` | No native `ends_with`; mirrors the `RIGHT(s, n)` idiom above |
| `PI()` | `3.14159265358979` | No native `pi()` — use the literal (dialect-free). (alternatively `sql_double_op ( "pi()" )` — documented pass-through) |
| `RADIANS(n)` | `n * 3.14159265358979 / 180` | No native `radians()` — use the literal composite. (alternatively `sql_double_op ( "radians({0})" , n )` — documented pass-through) |
| `DEGREES(n)` | `n * 180 / 3.14159265358979` | No native `degrees()` — use the literal composite. (alternatively `sql_double_op ( "degrees({0})" , n )` — documented pass-through) |

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

### NULL in IF/THEN/ELSE conditions — matches Tableau, don't auto-guard

ThoughtSpot compiles `if ( cond ) then a else b` to a SQL `CASE WHEN cond THEN a ELSE b END`
pushed down to the warehouse. When the condition references a NULL (e.g. `[x] >= 5000` where
`[x]` is NULL), the comparison is unknown — not TRUE — so the row falls into the **ELSE**
branch. This is standard SQL `CASE` semantics, consistent across warehouses (Snowflake,
BigQuery, Databricks, Redshift). *(Confirmed live 2026-06-12: the generated SQL is
`CASE WHEN NULL >= 5E3 THEN 'High' ELSE 'Low' END` → returns the ELSE value.)*

**Tableau behaves identically** — `IF [x] >= 5000 THEN a ELSE b END` also routes NULL rows to
ELSE. So a **literal translation is faithful** and preserves the workbook's original behavior.
**Do not auto-insert a NULL guard** — adding `if ( isnull([x]) ) then ... else ...` would
*change* the result relative to the source workbook.

Treat NULL-guarding as an **opt-in correction**: only add it when the user explicitly wants to
fix latent NULL mis-classification in the original (e.g. keep NULLs as NULL rather than 'Bronze').
This is warehouse-`CASE` behavior, so the same reasoning applies to the SV/MV converters.

---

## Division-by-zero (MANDATORY for every translated ratio)

Tableau returns NULL on division by zero; raw `/` pushed to the warehouse errors the whole
answer (Snowflake: "Division by zero"). Every translated division gets one of:

| Fidelity | Form | Caveat |
|---|---|---|
| Closest to Tableau | `if ( [b] = 0 ) then null else [a] / [b]` | Exact NULL semantics |
| Shorter | `safe_divide ( [a] , [b] )` | Function live-verified 2026-06-13 (se-thoughtspot). Returns **0**, not NULL, on zero divisor (formula-patterns.md) — flag if downstream logic distinguishes 0 from NULL. |

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
| `{FIXED [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , { dim } , {} )` | Fixed grain — partitions by the listed dimension(s) |
| `{FIXED [d1], [d2] : AVG([col])}` | `group_aggregate ( average ( [table::col] ) , { d1 , d2 } , {} )` | Multiple dimensions in partition |
| `{INCLUDE [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , query_groups () + { dim } , query_filters () )` | Adds dimension to whatever the query already groups by |
| `{EXCLUDE [dim] : SUM([col])}` | `group_aggregate ( sum ( [table::col] ) , query_groups () - { dim } , query_filters () )` | Removes dimension from the query's grouping |
| `{SUM([col])}` (no LOD keyword) | `group_aggregate ( sum ( [table::col] ) , {} , {} )` | Grand total — no partitioning |
| `TOTAL(SUM([col]))` | `group_aggregate ( sum ( [table::col] ) , {} , query_filters () )` | Table-calc grand total that **respects filters** — `{}` grouping (whole table) + `query_filters()`. Use this as the denominator for percent-of-total. |
| `SUM([x]) / TOTAL(SUM([x]))` (percent of total) | `sum ( [table::x] ) / group_aggregate ( sum ( [table::x] ) , {} , query_filters () )` | Common idiom: row/group value ÷ filtered grand total |

`TOTAL(agg)` is a Tableau table calculation, but the common `TOTAL(SUM(...))` / percent-of-total
case has a clean LOD translation (above) — same `group_aggregate` family Snowflake/Databricks
use. Other `TOTAL()` partitionings (e.g. along a specific pane direction) may still need
pass-through.

**Syntax rules for `group_aggregate`:**
- Dimensions use curly braces: `{ dim1 , dim2 }`
- `query_groups()` and `query_filters()` are ThoughtSpot keywords, not column references
- The inner aggregate (`sum`, `average`, `max`, `min`, `unique count`) follows standard ThoughtSpot formula syntax
- Column references inside `group_aggregate` use `[table::column]` format

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

> ⚠️ **`cumulative_*` (and `moving_*`) ARE valid as model formulas when the first arg is an
> unaggregated `[table::col]` reference** — verified 2026-06-13 on se-thoughtspot (see EXC1 in
> `ts-model-conversion-invariants.md`). They fail ONLY when the first arg is already aggregated
> (`sum([col])`) or a display-name ref (`[Sales]`). For Tableau conversion: strip the Tableau
> `SUM()`/`AVG()` wrapper and use the raw column ref → valid model formula. Fall back to
> answer-level only when the sort dimension cannot be determined from the workbook.

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `RUNNING_SUM(SUM([col]))` | `cumulative_sum ( [table::col] , [sort attr] )` | **Model formula valid** with unaggregated `[table::col]` ref (verified 2026-06-13, EXC1). Strip Tableau's `SUM()` wrapper. Fall back to answer-level (`[Measure]` display name) only when sort dimension is undetermined. |
| `RUNNING_AVG(AVG([col]))` | `cumulative_average ( [table::col] , [sort attr] )` | Same — strip `AVG()` wrapper, use unaggregated ref. |
| `RUNNING_MAX(MAX([col]))` | `cumulative_max ( [table::col] , [sort attr] )` | Same — strip `MAX()` wrapper. |
| `RUNNING_MIN(MIN([col]))` | `cumulative_min ( [table::col] , [sort attr] )` | Same — strip `MIN()` wrapper. |

**Aggregate-inside-cumulative pattern:** When the Tableau source nests an aggregate
that can't simply be stripped (e.g. `RUNNING_SUM(MAX([col]))` where you need the MAX
semantics, not a raw SUM), wrap it in `group_aggregate()`:
```
cumulative_sum ( group_aggregate ( max ( [table::col] ) , query_groups ( ) , query_filters ( ) ) )
```
Direct nesting like `cumulative_sum ( max ( [col] ) , [date] )` is rejected — the first
arg must be unaggregated OR wrapped in `group_aggregate()`.

**Limitations:**
- ThoughtSpot cumulative functions use the query's natural sort order — there is no
  explicit `ORDER BY` parameter like Snowflake window functions
- Partition dimensions are optional trailing arguments, not a separate `PARTITION BY`
- `RUNNING_COUNT(expr)` — no `cumulative_count`. Approximate with `cumulative_sum ( 1 , [sort_attr] )` at answer level, or omit + log if the sort attribute can't be determined.

---

## Window / Moving Functions

Tableau's `WINDOW_*` functions map to ThoughtSpot's `moving_*` functions. Chain:
Tableau `WINDOW_SUM` → Snowflake `SUM() OVER (... ROWS BETWEEN ...)` → ThoughtSpot
`moving_sum()`. See `ts-snowflake-formula-translation.md` "Moving / Sliding Window
Functions" for the full reference.

> ⚠️ Like `cumulative_*`, `moving_*` **are valid as model formulas when the first arg is an
> unaggregated `[table::col]` reference** (see EXC1 in `ts-model-conversion-invariants.md`).
> Strip the Tableau `SUM()`/`AVG()` wrapper and use the raw column ref. A composite like
> `EXP(WINDOW_AVG(LOG([m]), -2, 0))` (a geometric moving average) should be built as an
> answer-level formula if the nesting (`exp`/`log10` around `moving_average`) is rejected
> at model level.

> 🔑 **First arg must be unaggregated. For model formulas use `[table::col]`; for answer-level
> use the measure display name `[Sales]`.** Strip Tableau's outer `SUM()`/`AVG()` wrapper — 
> `cumulative_*`/`moving_*` reject an already-aggregated arg (*"expects 1st argument to be not
> aggregated"*). Pass the worksheet's shelf attribute(s) as trailing sort args. Verified
> 2026-06-13: `cumulative_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_ORDER::ORDER_DATE] )` imports
> as a model formula (GUID `889a704f`, model `TEST_SV_DMSI_AI_CONTEXT`). So:
> `RUNNING_SUM(SUM([Sales]))` along `[Month]` → model: `cumulative_sum ( [t::Sales] , [t::Month] )`;
> answer: `cumulative_sum ( [Sales] , [Month of order date] )`.
> `EXP(WINDOW_AVG(LOG([Sales]),-2,0))` along `[Order Date]` → `exp ( moving_average ( log10 ( [t::Sales] ) , 2 , 0 , [t::Order Date] ) )`.

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `WINDOW_SUM(SUM([col]), -3, 0)` | `moving_sum ( [table::col] , 3 , 0 , [sort attr] )` | 3-row lookback. **Model formula valid** with unaggregated `[table::col]` ref (verified 2026-06-13, EXC1). Strip Tableau's `SUM()` wrapper. |
| `WINDOW_AVG(SUM([col]), -3, 0)` | `moving_average ( [table::col] , 3 , 0 , [sort attr] )` | Same — strip `SUM()` wrapper, use unaggregated ref. |
| `WINDOW_MAX(SUM([col]), -3, 0)` | `moving_max ( [table::col] , 3 , 0 , [sort attr] )` | Same — strip `SUM()` wrapper. |
| `WINDOW_MIN(SUM([col]), -3, 0)` | `moving_min ( [table::col] , 3 , 0 , [sort attr] )` | Same — strip `SUM()` wrapper. |

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

**Extended windowed variants with no model-formula equivalent:**
- `WINDOW_STDEV`, `WINDOW_PERCENTILE`, `WINDOW_COUNT`, `WINDOW_MEDIAN` — no windowed model-formula equivalent (table calculations, answer-level per EXC1). If the viz uses them as a plain aggregate over the whole partition (not a sliding window), use `stddev()`, `percentile(measure, p)`, `count()`, `median()` respectively. Otherwise realize answer-level or omit + log.

---

## Rank Functions

| Tableau | ThoughtSpot | Notes |
|---|---|---|
| `RANK(SUM([col]))` | `rank ( sum ( [table::col] ) , 'desc' )` | **Direction arg is required** — `rank(measure)` with one arg fails validation (*"Function rank expects 2 arguments, found 1"*). Pass `'desc'` explicitly for Tableau's default. |
| `RANK(SUM([col]), 'asc')` | `rank ( sum ( [table::col] ) , 'asc' )` | |
| `RANK_UNIQUE(SUM([col]), 'desc')` | `rank ( sum ( [table::col] ) , 'desc' )` | ThoughtSpot `rank` uses **competition ranking** (ties share a rank, next rank is skipped: 1,1,3 — verified 2026-06-13, generates `RANK() OVER (ORDER BY ...)`). No RANK_UNIQUE equivalent — document the tie-handling difference. |

**Partitioned rank** — ThoughtSpot's native `rank()` has no partition support. For
partitioned rank, use a pass-through function (see "Pass-Through Fallback" below):
```
sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [table::region] , [table::revenue] )
```
⚑ flag for review — aggregate pass-through (PT1)

**Limitations:**
- `RANK_MODIFIED` has no native equivalent; `RANK_DENSE` → use `sql_int_aggregate_op ( "dense_rank() over (...)" )` pass-through (native `rank()` is competition, not dense — verified 2026-06-13)

---

## Row-Offset Table Calculations

Tableau's row-offset table calculations (`INDEX`, `LOOKUP`, `FIRST`, `LAST`, `SIZE`) were
previously classified as Untranslatable because they derive their `ORDER BY`/`PARTITION BY`
from the visualization layout. With the `<table-calc>` addressing extraction (SKILL.md
Step 3f), the sort/partition context is now recoverable for most cases.

### Decision tree (per detected table-calc formula)

Apply in order — stop at the first match:

| # | Condition | Action | Tier |
|---|---|---|---|
| 1 | `INDEX() <= N` or `INDEX() = N` used as a **filter** (inside an IF/CASE that gates row visibility, or a set filter) | Route to existing Top-N / query-set machinery (SKILL.md Step 5b). Use `rank ( [measure] , 'desc' )` + filter `[rank] <= N`. | **Native** |
| 2 | `INDEX()` used for **display row numbering** (standalone on a shelf, not filtering) AND `ordering_type` is `Rows` or `Field` with a known sort column | Emit answer-level: `rank ( sum ( [measure] ) , 'asc' )`. Note: ranks by measure value, not row position — acceptable for display numbering. | **Native** |
| 3 | `LOOKUP(agg, N)` where N > 0 (forward offset = LEAD) AND sort column is known | Emit answer-level: `moving_sum ( [measure] , -N , N , [sort_col] )` | **Native** |
| 4 | `LOOKUP(agg, N)` where N < 0 (backward offset = LAG) AND sort column is known | Emit answer-level: `moving_sum ( [measure] , abs(N) , -abs(N) , [sort_col] )` | **Native** |
| 5 | `FIRST()` (standalone, not as WINDOW_* offset) AND sort column is known | Emit answer-level: `first_value ( sum ( [measure] ) , query_groups ( ) , { [sort_col] } )` | **Native** |
| 6 | `LAST()` (standalone, not as WINDOW_* offset) AND sort column is known | Emit answer-level: `last_value ( sum ( [measure] ) , query_groups ( ) , { [sort_col] } )` | **Native** |
| 7 | `SIZE()` (unpartitioned) | Emit answer-level: `sql_int_aggregate_op ( "COUNT(*) OVER ()" )` ⚑ flag PT1 | **Pass-through (SIZE only)** |
| 8 | Any of the above but sort/partition is **not** recoverable (`ordering_type='CellInPane'`, or `ordering_type='Rows'`/`'Columns'` with no deterministic shelf sort, or `ordering_type='Table'` spanning multiple dims) | **Omit + log** (current behavior). Log message: `"[func]() — addressing context is ambiguous (ordering_type={type}); omit + log."` | **Omit** |

### Resolving the sort column from `<table-calc>` addressing

Given the `table_calc_addressing` entry (from Step 3f) and the worksheet shelf data
(from Step 9b), resolve the sort column:

| `ordering_type` | Sort column resolution |
|---|---|
| `Field` (with `ordering_field`) | The named field — resolve through the calc_id → display_name map |
| `Field` (with `<order>` children) | The first `<order field='...'>` child — resolve through the map. Additional `<order>` fields become `PARTITION BY` dimensions. |
| `Rows` | The first date/continuous dimension on the Rows shelf (from Step 9b). If no date on Rows, fall through to Tier 8 (ambiguous). |
| `Columns` | The first date/continuous dimension on the Columns shelf (from Step 9b). If none, Tier 8. |
| `Table` | Both Rows + Columns shelf dims in sequence. Only unambiguous for simple layouts (one dim on each); for complex multi-dim, Tier 8. |
| `CellInPane` | Always ambiguous → Tier 8. |

### Native ThoughtSpot formula templates

These are answer-level formulas. Use display-name column references (`[Sales]`), not
`[TABLE::col]` model references.

The `moving_sum` offset convention: positive start = preceding (backward), negative
start = following (forward). The end offset uses opposite sign to select a single row:
`(N, -N)` = exactly the row N positions back, `(-N, N)` = exactly N positions forward.

```
# INDEX() → rank (ranks by measure value — approximates row numbering)
rank ( sum ( [Sales] ) , 'asc' )

# LOOKUP(SUM([Sales]), -1) → LAG(1)
moving_sum ( [Sales] , 1 , -1 , [Order Date] )

# LOOKUP(SUM([Sales]), -3) → LAG(3)
moving_sum ( [Sales] , 3 , -3 , [Order Date] )

# LOOKUP(SUM([Sales]), 1) → LEAD(1)
moving_sum ( [Sales] , -1 , 1 , [Order Date] )

# LOOKUP(SUM([Sales]), 2) → LEAD(2)
moving_sum ( [Sales] , -2 , 2 , [Order Date] )

# FIRST() → first_value
first_value ( sum ( [Sales] ) , query_groups ( ) , { [Order Date] } )

# LAST() → last_value
last_value ( sum ( [Sales] ) , query_groups ( ) , { [Order Date] } )

# SIZE() → COUNT(*) OVER (pass-through — only row-offset that still uses sql_*_aggregate_op)
sql_int_aggregate_op ( "COUNT(*) OVER ()" )
```

### Why native functions over SQL pass-through (default)

Native ThoughtSpot functions (`moving_sum`, `first_value`, `last_value`, `rank`) handle
all column types correctly, require no admin enablement, and are validated at import
time — verified with DATE, VARCHAR, and INT64 columns (se-thoughtspot, 2026-06-15).

### SQL pass-through alternative (when exact SQL semantics are needed)

SQL pass-through (`sql_*_aggregate_op`) with `ORDER BY` **does work** for DATE columns
when two conditions are met (live-verified 2026-06-15):

1. **Date aggregate in the search must match the ORDER BY expression.** If the search
   query uses `[Order Date].monthly`, the pass-through ORDER BY must use
   `start_of_month([Order Date])` — both resolve to `DATE_TRUNC('MONTH', ...)` in
   Snowflake. A raw `[Order Date]` in ORDER BY mismatches the monthly GROUP BY and
   produces `"column is not a valid group by expression"`.

2. **All shelf GROUP BY columns must appear in PARTITION BY.** Every non-measure column
   in the `search_query` generates a GROUP BY clause. The pass-through window function
   must include all of them in its `PARTITION BY` or Snowflake rejects the query.

Example (LEAD with monthly date bucketing and region partition):
```
sql_int_aggregate_op ( "LEAD(SUM({0}), 1) OVER (PARTITION BY {1} ORDER BY {2})" , [Sales] , [Region] , start_of_month ( [Order Date] ) )
search_query: "[Sales] [formula_name] [Order Date].monthly [Region]"
```

Use SQL pass-through when you need exact SQL window function semantics (e.g.,
`ROW_NUMBER`, `DENSE_RANK`, partitioned `LEAD`/`LAG`). Default to native functions
for simpler cases.

### Caveats for row-offset formulas

1. **`rank()` is not `ROW_NUMBER()`** — ties share a rank and the next rank is skipped
   (1,1,3 not 1,2,3). Acceptable for display numbering; document the difference.
2. **Answer-level only** — these are viz-scoped formulas, not model formulas; they
   don't participate in search/Spotter discovery.
3. **SIZE() only** uses `sql_int_aggregate_op` — requires admin enablement for SQL
   pass-through functions. All other native row-offset formulas are fully native.
4. **SQL pass-through** (when used) requires admin enablement, is dialect-specific
   (Snowflake), and is not validated at import time — verify values post-import.

---

## Conditional aggregates (Tableau `AGG(IF cond THEN x END)`)

ThoughtSpot model formulas MAY be aggregate (see invariants I5 and ts-model-conversion-invariants.md:33). Do NOT convert to row-level with `else ''` — empty string becomes a countable distinct value (COUNTD off by one) and changes SUM/AVG denominators. Use the `*_if` family; the bare `IF` with no ELSE is NULL in Tableau, which aggregates ignore — `else null` preserves that exactly.

| Tableau | ThoughtSpot |
|---|---|
| `COUNTD(IF c THEN x END)` | `unique_count_if ( c , [x] )` |
| `SUM(IF c THEN x END)` | `sum_if ( c , [x] )` |
| `COUNT(IF c THEN x END)` | `count_if ( c , [x] )` |
| `AVG(IF c THEN x END)` | `average_if ( c , [x] )` |
| other agg / complex | `agg ( if ( c ) then [x] else null )` — `else null` is live-verified (static-set-to-column-set.md:107) |

---

## Pass-Through Fallback (Last Resort)

When a Tableau formula has a valid Snowflake SQL equivalent but no native ThoughtSpot
function, use a **pass-through function** to embed the raw SQL. Pass-through functions
are a last resort — always prefer native ThoughtSpot functions first.

Pass-through policy: scalar reliable, aggregate flag for review — see PT1 in ../../schemas/ts-model-conversion-invariants.md

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
| `RANK(SUM([col]))` partitioned | `sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) desc)" , [table::dim] , [table::measure] )` | Native `rank()` has no partition support. ⚑ flag for review (PT1) |
| `DENSE_RANK(SUM([col]))` | `sql_int_aggregate_op ( "dense_rank() over (order by sum({0}) desc)" , [table::col] )` | ⚑ flag for review (PT1) |

### Functions with no native ThoughtSpot equivalent — pass-through

| Tableau | Pass-through ThoughtSpot formula | Notes |
|---|---|---|
| `PROPER(s)` | `sql_string_op ( "INITCAP({0})" , s )` | No native title-case. Dialect: Snowflake/most use `INITCAP`. |
| `ASCII(s)` | `sql_int_op ( "ASCII({0})" , s )` | No native `ascii()`. Dialect-specific. |
| `CHAR(n)` | `sql_string_op ( "CHR({0})" , n )` | Snowflake uses `CHR`; SQL Server uses `CHAR`. |
| `REGEXP_EXTRACT(s, pat)` | `sql_string_op ( "REGEXP_SUBSTR({0}, {1})" , s , pat )` | No native regex. Snowflake `REGEXP_SUBSTR`. |
| `REGEXP_MATCH(s, pat)` | `sql_bool_op ( "REGEXP_LIKE ({0}, {1})" , s , pat )` | No native regex; returns boolean. |
| `REGEXP_REPLACE(s, pat, r)` | `sql_string_op ( "REGEXP_REPLACE({0},{1},{2})" , s , pat , r )` | No native regex. |
| `FINDNTH(s, sub, n)` | `sql_int_op ( "REGEXP_INSTR({0},{1},1,{2})" , s , sub , n )` | No native nth-occurrence; else omit + log. |

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
   ⚑ flag for review — aggregate pass-through (PT1)
4. **No validation** — ThoughtSpot does not validate the SQL string; errors surface at
   query time from the warehouse
5. **Pass-through must be enabled** — admins can disable via Admin > Search & SpotIQ >
   SQL Passthrough Functions. Document usage in `MIGRATION_LIMITATIONS.md`

### Translation priority order

When converting a Tableau formula, try in this order:

1. **Native ThoughtSpot function** — direct mapping from the Function Mapping table
2. **LOD / cumulative / rank** — sections above
3. **Row-offset table calcs** — tiered decision tree (native Top-N, native rank, or gated pass-through)
4. **Pass-through function** — this section (embed valid Snowflake SQL)
5. **Omit and log** — truly untranslatable (next section)

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
| `ISMEMBEROF()` | User-specific function — no equivalent |
| `PREVIOUS_VALUE()` | Recursive table calculation — no SQL equivalent (but see the string-aggregation note below, and the **Row-Offset Table Calculations** section for `FIRST()`/`LAST()` as standalone window-bound functions). |
| `RAWSQL_*()` | Direct SQL passthrough — not portable across warehouses |
| True **statistical clustering** (k-means; the analytics-engine "Clusters" calc — **not** `categorical-bin`) | No ThoughtSpot equivalent. NB: `categorical-bin` (manual groups, even when named "… clusters") **is** translatable → `GROUP_BASED` cohort |
| References to SQL-lookup Tableau Parameters | ThoughtSpot `list_config` only supports static values; SQL-populated parameter lists need manual recreation |
| `DATETIME(expr)` | No `to_datetime` cast. If the column is already a datetime type, reference it directly; if it's a string, only `to_date` (date-only) exists — omit + log the time component. |
| `MAKEPOINT(lat, lon)` | Geospatial point constructor — no ThoughtSpot formula equivalent. **Do not silently drop.** If the underlying lat/lon columns exist, migrate them as individual `ATTRIBUTE` columns (latitude + longitude are useful filter/display dimensions); omit the `MAKEPOINT` formula + log. See "Geospatial policy" below. |
| `MAKELINE(point1, point2)` | Geospatial line constructor — no ThoughtSpot equivalent. Omit + log. The endpoint lat/lon columns are migrated individually if present. |
| `DISTANCE(point1, point2, unit)` | Geospatial distance — no ThoughtSpot equivalent. Omit + log. |
| `BUFFER(geom, distance, unit)` | Geospatial buffer — no ThoughtSpot equivalent. Omit + log. |
| `AREA(geom, unit)` | Geospatial area — no ThoughtSpot equivalent. Omit + log. |

**Formerly untranslatable, now mapped:**
- `{FIXED ...}`, `{INCLUDE ...}`, `{EXCLUDE ...}` → `group_aggregate()` (see LOD section)
- `TOTAL(SUM(...))` / percent-of-total → `group_aggregate(..., {}, query_filters())` (see LOD section)
- Tableau **bins** (`class='bin'`) → `floor([x]/size)*size` bucketing formula (see Tableau Bins section)
- `Number of Records` (`= 1`) → `sum(1)`
- `RUNNING_SUM`, `RUNNING_AVG`, etc. → `cumulative_sum()`, `cumulative_average()`, etc. (see Running/Cumulative section)
- `RANK()` → `rank()` (see Rank section)
- `WINDOW_SUM`, `WINDOW_AVG`, etc. → `moving_sum()`, `moving_average()`, etc. (see Window / Moving section); fall back to pass-through when sort dimension cannot be determined (⚑ flag for review if using `sql_*_aggregate_op` — PT1)
- `RANK_MODIFIED`, `RANK_DENSE` → `sql_int_aggregate_op()` pass-through ⚑ flag for review (PT1)
- Partitioned `RANK` → `sql_int_aggregate_op()` with `partition by` ⚑ flag for review (PT1)
- **Comma-separated list of values** (Tableau's `FIRST`/`LAST`/`LOOKUP`/`PREVIOUS_VALUE` CSV technique) →
  string aggregation, see below
- `INDEX()` → `rank()` (Top-N filter intent) or `sql_int_aggregate_op("ROW_NUMBER() OVER (...)")` (display row number, answer-level, gated) — see Row-Offset Table Calculations section
- `LOOKUP(agg, ±n)` → `sql_*_aggregate_op("LAG/LEAD(...) OVER (...)")` (answer-level, gated) — see Row-Offset Table Calculations section
- `FIRST()`, `LAST()` (standalone) → `sql_*_aggregate_op("FIRST_VALUE/LAST_VALUE(...) OVER (...)")` (answer-level, gated) — see Row-Offset Table Calculations section
- `SIZE()` → `sql_int_aggregate_op("COUNT(*) OVER (PARTITION BY ...)")` (answer-level, gated) — see Row-Offset Table Calculations section

---

## String aggregation — comma-separated list of values

Tableau workbooks concatenate a column's values into one string via a row-walking **table-calc
technique** (`FIRST()`/`LAST()`/`LOOKUP()`/`PREVIOUS_VALUE()` building up a string — e.g. Jonathan
Drummey's "comma-separated list" / set-member-list dashboards). The *implementation* is untranslatable,
but the *intent* (one delimited string of the values) maps to **`LISTAGG` via a string-aggregate
pass-through** (live-verified 2026-06-12 as an answer-level formula):

```
sql_string_aggregate_op ( "LISTAGG({0}, ', ') WITHIN GROUP (ORDER BY {0})" , [Category] )
```

- It is an **aggregate pass-through** → **⚑ flag for review** (PT1).
- Make it an **answer-level** formula (`answer.formulas[]`) on the viz that needs it (it's viz-specific,
  not a reusable model column), rendered `display_mode: TABLE_MODE`. The Tableau feeder/`Last`
  scaffolding calcs collapse into this single formula — do **not** migrate them individually.
- **Scope to a set's in/out members** by applying the migrated column set / a filter on the answer
  (LISTAGG over the in-set rows = the "in list"; over the out-set rows = the "out list").
- **Often a plain table of the values is the better ThoughtSpot UX** than a pre-concatenated string —
  offer both.

---

## Geospatial Policy

Tableau geospatial functions (`MAKEPOINT`, `MAKELINE`, `DISTANCE`, `BUFFER`, `AREA`) construct
spatial objects from lat/lon columns. ThoughtSpot has no spatial data type or point/line constructors.

**Policy — detect, decompose, log (never silent):**

1. **Detect** `MAKEPOINT(`, `MAKELINE(`, `DISTANCE(`, `BUFFER(`, `AREA(` in calculated fields
   (use the same `FUNCTION\s*\(` pattern as other untranslatable functions).
2. **Decompose `MAKEPOINT(lat, lon)`:** if the two arguments resolve to physical columns (latitude
   and longitude), ensure those columns are migrated as individual `ATTRIBUTE` columns on the model.
   They are useful as filter and display dimensions even without a map visualization. Omit the
   `MAKEPOINT` wrapper formula.
3. **Omit the geospatial formula** from the model TML — do not generate a stub or placeholder.
4. **Log** each omission:
   `"Geospatial: '<calc name>' uses MAKEPOINT/MAKELINE/DISTANCE — no ThoughtSpot equivalent. Underlying lat/lon columns migrated as individual attributes. Omitted the spatial formula."`
5. **Surface in the audit report** under a dedicated "Geospatial" row (see Tier table note below).

**Calcs that ONLY wrap `MAKEPOINT`** (e.g. `MAKEPOINT([Latitude], [Longitude])`) are pure spatial
constructors — their underlying columns carry all the analytical value. Calcs that use `DISTANCE`
or `BUFFER` lose the spatial computation entirely; flag these more prominently:
`"Geospatial: '<calc name>' computes DISTANCE/BUFFER — spatial calculation lost; lat/lon columns available for filtering but distance metric needs manual recreation."`

**Classifier detection patterns** (add to the existing regex list):
```
MAKEPOINT\s*\(   MAKELINE\s*\(   DISTANCE\s*\(   BUFFER\s*\(   AREA\s*\(
```

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
