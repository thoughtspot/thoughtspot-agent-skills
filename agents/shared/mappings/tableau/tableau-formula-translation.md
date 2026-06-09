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
| `SPLIT(s, delim, n)` | Use `substr`/`strpos` combination | No direct equivalent |
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

## Untranslatable Patterns

These Tableau features have no ThoughtSpot equivalent. Document them in `MIGRATION_LIMITATIONS.md` instead of converting.

| Tableau Feature | Reason |
|---|---|
| `WINDOW_SUM`, `WINDOW_AVG`, `WINDOW_MAX`, etc. | Table calculations — no ThoughtSpot equivalent |
| `LOOKUP()` | Table calculation |
| `INDEX()` | Table calculation |
| `RUNNING_SUM`, `RUNNING_AVG`, etc. | Table calculations |
| `{FIXED ...}`, `{INCLUDE ...}`, `{EXCLUDE ...}` | LOD expressions — no direct equivalent |
| `ISMEMBEROF()` | User-specific function |
| `SIZE()`, `FIRST()`, `LAST()` | Table calculations |
| References to Tableau Parameters | ThoughtSpot has its own parameter system |

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
