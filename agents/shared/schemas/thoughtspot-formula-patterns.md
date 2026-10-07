<!-- currency: thoughtspot — 2026-10 (2026-10-07 week probes on se-thoughtspot: week_number_of_year is the ISO week, ThoughtSpot's APJ_TAB session runs WEEK_START 0, a column-bound custom calendar does not change start_of_week/day_number_of_week/week_number_of_year, the calendar argument is a bare keyword, exact non-Monday week forms built on day_number_of_week — BL-373/BL-380/BL-334; 2026-10-06 compiled-SQL probes on se-thoughtspot: day_number_of_week fixed Mon=1, start_of_week compiled to DATE_TRUNC(week) (Monday only under WEEK_START 0/1); domain review: Model calendar defaults to Gregorian/Monday, start_of_* take an optional 'Calendar Name' arg that translations must not emit, diff_months/diff_years count boundaries, contains/strpos/= case-insensitive; variable endpoints: per-identifier update-values; rename + bulk delete added in 26.4.0.cl; formula composition + TML import behaviours validated on SE cluster 2026-07-10 — function composition rules, if() parens mandatory; string-function nativeness re-verified on se-thoughtspot 2026-07-29 per BL-170 — trim/ltrim/rtrim/replace/starts_with/ends_with confirmed ABSENT, `in` confirmed curly-brace-only; window/semi-additive signatures verified on se-thoughtspot 2026-07-30 — no PARTITION BY slot on moving_*/cumulative_*, rank/rank_percentile arity fixed at 2, first_value/last_value partition + axis explicit, lag/dense_rank/row_number/nth_value/moving_count/moving_stddev/cumulative_count confirmed ABSENT); 2026-08-26 finding 13.8: first_value(..., query_groups(), {date}) reclassified TRANSLATABLE via NON ADDITIVE BY desc / sort_direction: descending -- the old "last-value only" reason contradicted a sibling file and the row two lines below it -->

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
| `least` | `least ( [a] , [b] , ... )` | Returns the smallest value across N arguments — row-wise, like `greatest` (`min` / `max` are aggregate-only). Accepted VALIDATE_ONLY on se-thoughtspot 2026-10-06 ([probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)) |

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
| ~~`null_if_zero`~~ | — **Does not exist** (VALIDATE_ONLY, se-thoughtspot, 2026-10-06 — *Search did not find "null_if_zero ("*; BL-344). Write `if ( [x] = 0 ) then null else [x]` |
| NULL branch | `if ( [c] ) then null else [x]` — `null` is accepted as a branch value (VALIDATE_ONLY 2026-10-06, probe record §7); it is the native replacement for SQL `NULLIF` |
| `isnull` | `isnull ( [TABLE::col] )` |
| ~~`isnotnull`~~ | — **Does not exist** (VALIDATE_ONLY, se-thoughtspot, 2026-10-06 — `isnotnull ( [x] )` is rejected: *Search did not find "isnotnull ("*; [probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)). Write `not ( isnull ( [x] ) )`, which the repo's translators already emit. BL-339 |
| `ifnull` | `ifnull ( [TABLE::col] , [default] )` |
| ~~`nullif`~~ | — **Does not exist** (VALIDATE_ONLY, se-thoughtspot, 2026-10-06 — both `nullif ( x , 0 )` and `null_if` are rejected: *Search did not find "nullif ("*; [probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)). For a guarded ratio use `safe_divide ( [a] , [b] )` (0 on a zero divisor) or plain `[a] / [b]` (NULL on a zero divisor); for an explicit NULL use `if ( [b] = 0 ) then null else [a] / [b]` — `then null` is accepted. BL-339 |
| `not` | `not ( [expr] )` |
| `and` / `or` | `[a] and [b]` / `[a] or [b]` |
| `in` | `[col] in { 'a' , 'b' }` — **curly braces, not parentheses** (see below) |
| `between` | `[col] between [a] and [b]` |

**`in` takes a curly-brace literal list.** Live-verified 2026-07-29, se-thoughtspot
(BL-170). The round-parenthesis form `[col] in ( 'a' , 'b' )` is **rejected**:

```text
Search did not find "( 'cancelled' , 'active' )" in your data or metadata.
Expecting one of the valid keywords, such as, "ts_var", "{".
```

Because the expression contains `{ }`, it **must** use the `>-` folded block scalar in
YAML — see [YAML Encoding](#yaml-encoding) above. There is no `not in` keyword; negate
with `not ( [col] in { ... } )`.

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
| `safe_divide` | `safe_divide ( [a] , [b] )` — compiles to `CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END` (live-probed se-thoughtspot 2026-10-06, [probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)): a **zero** divisor returns **0**; a **NULL** divisor or numerator returns NULL. Plain `[a] / [b]` returns **NULL** on a zero divisor (no query error). **Zero only when the source asks for zero** (BL-357, 2026-10-07): a SQL `x / NULLIF(y, 0)` is plain `[x] / [y]`; `COALESCE(x / NULLIF(y, 0), 0)` is `ifnull ( safe_divide ( [x] , [y] ) , 0 )`. Over a **Databricks** connection ThoughtSpot's queries run non-ANSI (BL-358): BIGINT overflow wraps and an out-of-range cast clamps rather than raising — see `ts-databricks-formula-translation.md` |
| `round` | `round ( [x] , [inc] )` — **`inc` is a rounding INCREMENT, not a decimal-place count** (BL-331, live-probed se-thoughtspot 2026-10-06). Compiles to `inc * round(x / NULLIF(inc, 0))`. On `1234.5678`: `round(x)` = 1235, `round(x, 1)` = 1235, `round(x, 0.01)` = 1234.57, `round(x, 0.5)` = 1234.5, `round(x, 10)` = 1230, `round(x, 2)` = **1234** (nearest multiple of 2), `round(x, -2)` = 1234, `round(x, 0)` = **NULL**. Result type: an integer `inc` (`1`, `10`) returns **INT64**, a fractional one (`0.01`, `0.5`) **DOUBLE** — and the `sql_double_op` pass-throughs the translators fall back to (non-literal SQL digit count; Snowflake `TRUNC`) always return **DOUBLE**, whatever the warehouse's own ROUND/TRUNC type. So SQL `ROUND(x, d)` ↔ `round ( x , 10^-d )` — never copy `d` across (`formula_common.ts_round_from_sql_digits` / `ts_increment_to_sql_digits`) |
| `floor` | `floor ( [x] )` |
| `ceil` | `ceil ( [x] )` |
| `abs` | `abs ( [x] )` |
| `pow` | `pow ( [x] , [n] )` — **not `power`**, which the parser rejects (verified 2026-06-13) |
| `mod` | `mod ( [x] , [n] )` |
| `sqrt` | `sqrt ( [x] )` |
| `ln` | `ln ( [x] )` |
| `log2` | `log2 ( [x] )` |
| `log10` | `log10 ( [x] )` |
| `sin` | `sin ( [x] )` — **radians**, like SQL, Excel and Tableau: `sin ( 30 )` compiles to `SIN(30)` = −0.988 ([probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat), live 2026-10-07; BL-364). Never convert by `180 / π` |
| `cos` | `cos ( [x] )` — radians (`cos ( 60 )` = −0.952, live 2026-10-07; BL-364) |
| `tan` | `tan ( [x] )` — radians (`tan ( 45 )` = 1.620, live 2026-10-07). No native `cot`: `1 / tan ( [x] )` |
| `asin` | `asin ( [x] )` — returns radians (`asin ( 0.5 )` = 0.5236, live 2026-10-07; BL-364) |
| `acos` | `acos ( [x] )` — returns radians (`acos ( 0.5 )` = 1.0472, live 2026-10-07) |
| `atan` | `atan ( [x] )` — returns radians (`atan ( 1 )` = 0.7854, live 2026-10-07). No catalogued `atan2`: `sql_double_op ( "ATAN2({0}, {1})" , [y] , [x] )` |
| π | `sql_double_op ( "PI()" )` — the warehouse's own double (a zero-argument template is accepted, live 2026-10-07). A 15-digit literal loses precision, and a literal-over-literal division of it is fixed-point (below) |

**Operator grouping — `a * b / c` is `a * ( b / c )`** (live, se-thoughtspot 2026-10-07; probe
record §7; BL-365). `[n] * 4 / 3` compiles to `n * (4 / NULLIF(3, 0))`, and Snowflake divides two
integers (or literals) at **scale 6**, so it returns 3.999999 for n = 3; `[n] * 2 * 5 / 3` is
`n * 2 * (5 / 3)`. `a / b / c`, `a / b * c`, `a - b + c` and `a - b - c` stay left to right.
**Bracket a product that is the left operand of a division**: `( [n] * 4 ) / 3` returns 4.
Every translator does it in its last step (`formula_text.ts_finalize_formula`).

---

## String Literals

How ThoughtSpot reads a literal (live, se-thoughtspot 2026-10-07, each compared with the Snowflake
value over the same rows; [probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat); BL-365):

| Literal | Reads as | Use it? |
|---|---|---|
| `'plain'` | `plain` | yes, for text with no quote and no backslash |
| `'it''s'` | **`it''s`** — a doubled quote is TWO quotes | **never** for a quote |
| `'it\'s'` | `it's` — but rejected at import when a space follows the escape (`'it\'s here'`, `'x\'s '`) | no |
| `"it's"` (double-quoted) | `it's` — exact as a filter value (`=`, `!=`), in `in { }`, `contains`, `concat` after another literal, an `if` branch and a `sql_*_op` argument | **yes**, for text with a quote |
| `'a\\b'`, `"a\\b"` | `a\b`; a lone `\` is dropped (`'a\b'` is `ab`) | double every backslash |
| `sql_string_op ( "'it''s'" )` | `it's` | works; the double-quoted literal is shorter |

Text holding both `'` and `"` is a `concat` of the two forms split at each `"`:
`concat ( 'say ' , '"' , 'hi' , '"' , " it's" )`. `formula_text.ts_string_literal` prints these
forms for every translator. A `sql_*_op` template is a different thing: double-quoted, no escape at
all, and its inner literals are the warehouse's own (`'it''s'` is right inside a Snowflake template).

---

## String Functions

| Function | Syntax | Notes |
|---|---|---|
| `concat` | `concat ( [a] , [b] , ... )` | N arguments supported — `concat ( 'a' , 'b' , 'c' , 'd' )` imports (VALIDATE_ONLY 2026-10-06). **Every argument must be Text**: a number is rejected with *"Function concat expects 2nd argument to be Text"* — wrap it in `to_string ( … )`; and `to_string` itself **rejects a Text argument** (*"expects 1st argument to be Boolean or Date or DateTime or Numeric or Time"*), so wrap only the non-text operands ([probe record §7](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)). **`+` does NOT concatenate strings** in TS formulas — it is numeric-only. The TS parser rejects `[a] + ', ' + [b]` with "Search did not find + ', ' +". Always use `concat()` for string joining, including for SQL `CONCAT(a, ', ', b)` translations. |
| `substr` | `substr ( [x] , [start] , [len] )` | **Zero-indexed start**, three arguments — compiles to `SUBSTRING(x, (start + 1), len)` (Snowflake, live 2026-10-06). A 1-based SQL `SUBSTR(x, s, n)` is `substr ( x , s - 1 , n )`; a negative SQL start (counted from the end) has no `substr` form — `sql_string_op` (BL-340) |
| `left` | `left ( [x] , [n] )` | First N characters |
| `right` | `right ( [x] , [n] )` | Last N characters |
| `strlen` | `strlen ( [x] )` | String length |
| `strpos` | `strpos ( [x] , 'val' )` | Position of first occurrence — 1-indexed, returns 0 when not found (live-verified 2026-06-13, se-thoughtspot; official docs claim 0-based/−1 — live behavior wins). **Case-insensitive**: compiles to `POSITION('val' IN LOWER(x))` with the literal lowercased at compile time (live-verified 2026-10-06, se-thoughtspot — see "String comparison is case-insensitive" below). |
| ~~`upper`~~ | — | **Does not exist** in ThoughtSpot (verified 2026-06-13). Use `sql_string_op ( "UPPER({0})" , [x] )` pass-through. |
| ~~`lower`~~ | — | **Does not exist** in ThoughtSpot (verified 2026-06-13). Use `sql_string_op ( "LOWER({0})" , [x] )` pass-through. |
| ~~`trim`~~ | — | **Does not exist** in ThoughtSpot (live-verified 2026-07-29, se-thoughtspot — BL-170). Use `sql_string_op ( "TRIM({0})" , [x] )` pass-through. |
| ~~`ltrim`~~ | — | **Does not exist** (live-verified 2026-07-29, se-thoughtspot — BL-170). Use `sql_string_op ( "LTRIM({0})" , [x] )` pass-through. |
| ~~`rtrim`~~ | — | **Does not exist** (live-verified 2026-07-29, se-thoughtspot — BL-170). Use `sql_string_op ( "RTRIM({0})" , [x] )` pass-through. |
| ~~`replace`~~ | — | **Does not exist** (live-verified 2026-07-29, se-thoughtspot — BL-170). Use `sql_string_op ( "REPLACE({0}, {1}, {2})" , [x] , [old] , [new] )` pass-through. |
| `contains` | `contains ( [x] , 'val' )` | Returns boolean. **Case-insensitive**: compiles to `LOWER(x) LIKE '%val%' ESCAPE '!'`, literal lowercased at compile time (live-verified 2026-10-06, se-thoughtspot — see below). For case-sensitive semantics use `sql_bool_op ( "CONTAINS({0}, {1})" , [x] , 'val' )`. |
| ~~`starts_with`~~ | — | **Does not exist** (live-verified 2026-07-29, se-thoughtspot — BL-170; also 2026-06-13). Compose from `strpos`: `strpos ( [x] , 'val' ) = 1`. |
| ~~`ends_with`~~ | — | **Does not exist** (live-verified 2026-07-29, se-thoughtspot — BL-170). Compose from `substr`/`strlen`: `substr ( [x] , strlen ( [x] ) - strlen ( 'val' ) , strlen ( 'val' ) ) = 'val'`. |

**Whitespace/replacement/prefix note (BL-170, live-verified 2026-07-29 on se-thoughtspot).**
`trim`, `ltrim`, `rtrim`, `replace`, `starts_with` and `ends_with` are **all absent** from
the formula parser — each is rejected with `Search did not find "<fn> (" in your data or
metadata`, the same signature `upper`/`lower` produce. The pass-throughs and compositions
above were verified to import in the same pass. Only `concat`, `substr`, `left`, `right`,
`strlen`, `strpos` and `contains` are native string functions.

### String comparison is case-insensitive

*Live-verified 2026-10-06 on se-thoughtspot (Snowflake), via scratch Models and
`ts agentql generate-sql` / `fetch-data`; the Models were deleted afterwards.* ThoughtSpot
lowercases both sides of a string comparison when it compiles a formula:

| Formula | Compiled Snowflake SQL | Observed |
|---|---|---|
| `contains ( [DEPARTMENT] , 'eng' )` | `LOWER(DEPARTMENT) LIKE '%eng%' ESCAPE '!'` | matches `Engineering` |
| `contains ( 'Hello World' , 'WORLD' )` | `'hello world' LIKE '%world%'` | `true` — **literals are lowercased at compile time** |
| `strpos ( [DEPARTMENT] , 'eng' )` | `POSITION('eng' IN LOWER(DEPARTMENT))` | 1 for `Engineering` |
| `[DEPARTMENT] = 'engineering'` | `LOWER(DEPARTMENT) = 'engineering'` | matches `Engineering` |

Consequence: a source comparison that is case-sensitive (Snowflake's default collation,
Excel `FIND`/`EXACT`, Sigma `Contains`) is **not** reproduced by native `=` / `contains` /
`strpos`. Where exact case semantics matter, pass the comparison through:
`sql_bool_op ( "CONTAINS({0}, {1})" , [s] , 'x' )` or `sql_bool_op ( "{0} = {1}" , [s] , 'x' )`
(Snowflake compares case-sensitively under its default collation). Converter impact is
tracked as BL-333.

Probed again 2026-10-07 (same method). These are lowercased the same way:

| Formula | Compiled Snowflake SQL | Observed |
|---|---|---|
| `[DEPARTMENT] != 'engineering'` | `LOWER(DEPARTMENT) <> 'engineering'` | FALSE for `Engineering` |
| `[DEPARTMENT] in { 'engineering' , 'sales' }` | `LOWER(DEPARTMENT) IN ( 'engineering', 'sales' )` | TRUE for `Engineering`, `Sales` |
| `strpos ( [DEPARTMENT] , 'eng' ) = 1` | `POSITION('eng' IN LOWER(DEPARTMENT)) = 1` | TRUE for `Engineering` (prefix test) |
| `[DEPARTMENT] < 'f'` | `LOWER(DEPARTMENT) < 'f'` | FALSE for `HR`: **ordering changes too**. Case-sensitively `'HR' < 'f'` is TRUE, because uppercase sorts first |

**Still not tested:** whether join conditions on string keys are lowercased.

**Decision (2026-10-07, BL-333): accepted and documented.** Converters keep emitting native `=` / `!=` / `in` / `contains` / `strpos` / ordering comparisons. They do not pass every comparison through, because in typical BI data a case-only difference is noise, and pass-throughs are opaque to ThoughtSpot. Each affected converter documents the change. Where exact case semantics matter for a specific formula, hand-edit it to the `sql_bool_op` form above. `ts-object-formula-translate` still flags these comparisons as APPROXIMATED.

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
| `to_string` | `to_string ( [x] )` — Boolean, Date, DateTime, Numeric or Time only; a **Text** argument is rejected (VALIDATE_ONLY 2026-10-06, probe record §7). **On a DATE column the one-argument form is rejected too** (*Function to_string expects 2 arguments, found 1*, error_code 14516, VALIDATE_ONLY 2026-10-06, formula fidelity M0 `sf-date-011`); the second argument's meaning is unverified, so a SQL `TO_CHAR(d, fmt)` translates to a `sql_string_op` pass-through (BL-343) |

---

## Date Functions

*Source: ThoughtSpot official formula reference (verified 2026-06-13). Most date-part
functions accept an optional second parameter for non-Gregorian calendars. Rows below call
it the "`fiscal` param" — the bare keyword `fiscal` (e.g. `year ( [d] , fiscal )`, see the
fiscal-year example above) selects the cluster's fiscal calendar. The domain review below
describes the `start_of_*` argument as a **custom calendar** name. `fiscal` and `'fiscal'` were
both **rejected** in the `start_of_week` slot on se-thoughtspot (VALIDATE_ONLY, 2026-10-07).*

**Calendar argument and the Model's default calendar (ThoughtSpot domain review 2026-10-06;
corrected by live probe 2026-10-07, [probe record §8](../../../docs/reviews/2026-10-06-formula-semantics-probes.md#8-week-truncation-week-numbering-week_start-and-custom-calendars-bl-373-bl-380-bl-334-items-34)).**
`start_of_week`, `start_of_month`, `start_of_quarter` and `start_of_year` take an optional
**custom calendar** argument. So do `day_number_of_week`, `week_number_of_year` and
`diff_weeks` (all accepted). The argument is the calendar name as a **bare keyword**, not a
string literal: `start_of_week ( [date] , RetailCal )` is accepted, while `'RetailCal'` and
`"RetailCal"` are rejected (error 14516). It resolves per connection; a calendar registered
on another connection is rejected. With it, the function reads the calendar table:
`start_of_week` became `"cal"."start_of_week_epoch"` over an **INNER** join on the date, so a
date outside the calendar's range drops the row. **Formula translations must not emit it.**

**A custom calendar bound to the column does NOT reach these functions.** With
`properties.calendar` set to a Sunday-start custom calendar, `start_of_week`,
`day_number_of_week` and `week_number_of_year` compiled to exactly the same SQL as on a
plain column: Gregorian, Monday weeks. So the effective calendar for a formula without the
argument is **Gregorian with a Monday week start**, whatever the column says. (For the Model/column side, `properties.calendar` takes the name of
a Connection-scoped custom calendar — see [thoughtspot-sql-view-tml.md](thoughtspot-sql-view-tml.md);
`ts-object-calendar-builder` builds those calendars.)

**What to flag instead: any translated formula that assumes Monday is the first day of the
week** — weekday numbering (`day_number_of_week`), week-start alignment (`start_of_week`),
week-number and ISO-week compositions, and NETWORKDAYS/WORKDAY-style arithmetic built on
`day_number_of_week`. Each such translation is Gregorian with Monday weeks even on a column
bound to another calendar (probed 2026-10-07, above); say so on the row. A source with an
explicit fiscal or custom week setting (Excel `WEEKNUM` return types, Sigma/Omni fiscal
settings, `fiscal_month_offset`) is a note, not a formula change.

**Where the source's week start is KNOWN and is not Monday, emit the exact form (BL-373,
live-verified for all seven start days on 120 dates, 2026-10-07).** Rebuild it from
`day_number_of_week`, which is fixed arithmetic. **Do not shift `start_of_week`.**
- Week start: `add_days ( date ( d ) , 0 - mod ( day_number_of_week ( d ) + (6 - i) , 7 ) )`,
  where `i` is the start day Monday-based (Monday = 0 … Sunday = 6). Sunday is
  `add_days ( date ( d ) , 0 - mod ( day_number_of_week ( d ) , 7 ) )`.
- Why not the shift: `add_days ( start_of_week ( add_days ( d , k ) ) , -k )` was exact on
  se-thoughtspot, but `start_of_week` compiles to `DATE_TRUNC(week, d)`. Under Snowflake
  `WEEK_START = 7` the shift returns Saturday for a Sunday week.
- "Week 1 contains January 1" numbering (Tableau `DATEPART('week')`):
  `( floor ( ( day_number_of_year ( d ) - 1 + mod ( day_number_of_week ( start_of_year ( d ) ) + (6 - i) , 7 ) ) / 7 ) + 1 )`.
- Code: `ts_cli/formula_week.py` (`ts_week_start`, `ts_week_of_year_jan1`).

| Function | Syntax | Notes |
|---|---|---|
| `today` | `today ()` | Current date |
| `now` | `now ()` | Current date and time |
| `date` | `date ( [datetime] )` | Date portion of a datetime. On a genuine DATETIME it compiles to `CAST(… AS date)` (`date ( now ( ) )`, live 2026-10-07). On an expression ThoughtSpot already types as DATE it compiles to nothing. That includes `add_seconds ( [a DATE] , n )`, whose warehouse value keeps its time of day (probe record §8) |
| `time` | `time ( [datetime] )` | Time portion of a datetime |
| `year` | `year ( [date] )` | Calendar year (integer). Optional `fiscal` param. |
| `year_name` | `year_name ( [date] )` | Year as string. With fiscal: `"FY_2014"` |
| `quarter_number` | `quarter_number ( [date] )` | Quarter (1–4). Optional `fiscal` param. |
| `month` | `month ( [date] )` | Month name (e.g. "January"). Optional `fiscal` param. |
| `month_number` | `month_number ( [date] )` | Month number (1–12). Optional `fiscal` param. |
| `month_number_of_quarter` | `month_number_of_quarter ( [date] )` | Month within quarter (1–3). Optional `fiscal` param. |
| `day` | `day ( [date] )` | Day of month (1–31). Verified 2026-06-13. Optional `fiscal` param. |
| `day_of_week` | `day_of_week ( [date] )` | Day name (e.g. "Friday"). Optional `fiscal` param. |
| `day_number_of_week` | `day_number_of_week ( [date] )` | Day number, **1=Monday … 7=Sunday** — agrees with the Model's default calendar (Gregorian, Monday week start). **Translations built on it assume a Monday week start** and diverge on a Model whose calendar starts elsewhere. Compiles to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)`, a fixed arithmetic independent of the warehouse's `WEEK_START` (live-verified 2026-10-06, se-thoughtspot: 2026-10-04 Sun=7, 2026-10-05 Mon=1, 2026-10-10 Sat=6, 2020-01-01 Wed=3). A custom calendar bound to the column does **not** change it (same SQL with a Sunday-start calendar on the column, live 2026-10-07, BL-334 item 4); only an explicit calendar argument does. Because it is fixed arithmetic, it is the building block for exact non-Monday week starts (see "Where the source's week start is KNOWN" above). |
| `day_number_of_quarter` | `day_number_of_quarter ( [date] )` | Day within quarter. Optional `fiscal` param. |
| `day_number_of_year` | `day_number_of_year ( [date] )` | Day within year (1–366). Optional `fiscal` param. |
| `hour_of_day` | `hour_of_day ( [date] )` | Hour of the day |
| `week_number_of_month` | `week_number_of_month ( [date] )` | Week within month. Optional `fiscal` param. |
| `week_number_of_quarter` | `week_number_of_quarter ( [date] )` | Week within quarter. Optional `fiscal` param. |
| `week_number_of_year` | `week_number_of_year ( [date] )` | **The ISO-8601 week** (Thursday rule): it equalled Python `isocalendar()` on all 120 dates probed around six year boundaries (live 2026-10-07, BL-380). So early-January days can be week 52/53 (2021-01-01 = 53) and late-December days week 1 (2019-12-30 = 1). It is **not** a "week 1 contains January 1" numbering. Under a Monday start it was one lower than Tableau `DATEPART('week')` for the whole of 2021, 2022, 2023 and 2027; use the Jan-1 composition above for those sources. A column-bound custom calendar does not change it. |
| `is_weekend` | `is_weekend ( [date] )` | Returns true for Saturday/Sunday. Optional `fiscal` param. |
| `start_of_month` | `start_of_month ( [date] )` / `start_of_month ( [date] , CalendarName )` | First day of the month. Default: the Model's calendar, Gregorian when nothing else is set (ThoughtSpot domain review, 2026-10-06). Translations omit the calendar argument — see "Calendar argument" above. |
| `start_of_quarter` | `start_of_quarter ( [date] )` / `start_of_quarter ( [date] , CalendarName )` | First day of the quarter. Default: the Model's calendar, Gregorian when nothing else is set (ThoughtSpot domain review, 2026-10-06). Translations omit the calendar argument — see "Calendar argument" above. |
| `start_of_week` | `start_of_week ( [date] )` / `start_of_week ( [date] , CalendarName )` | First day of the week, **Monday**. A custom calendar bound to the column does not change it (live 2026-10-07); only the explicit calendar argument does. Translations omit the argument — see "Calendar argument" above. **SQL caveat:** it compiles to Snowflake `DATE_TRUNC(week, d)`, which follows the `WEEK_START` of ThoughtSpot's connection session. That was **0** on se-thoughtspot / `APJ_TAB`: a ThoughtSpot-issued `DAYOFWEEK` returned 0 for every Sunday (2026-10-07, BL-334 item 3). A connection whose Snowflake user or account sets 2–7 truncates to that day instead; whether ThoughtSpot would override it is unprobed (needs `ALTER USER` on the connection user). For a known non-Monday source start, do **not** shift this function — see "Where the source's week start is KNOWN" above (BL-373). |
| `start_of_year` | `start_of_year ( [date] )` / `start_of_year ( [date] , CalendarName )` | First day of the year. Default: the Model's calendar, Gregorian when nothing else is set (ThoughtSpot domain review, 2026-10-06). Translations omit the calendar argument — see "Calendar argument" above. |
| `start_of_hour` | `start_of_hour ( [time] )` | Time truncated to the hour |
| `start_of_min` | `start_of_min ( [time] )` | Time truncated to the minute |
| `diff_days` | `diff_days ( [end] , [start] )` | Days between — note arg order (end first) |
| `diff_weeks` | `diff_weeks ( [end] , [start] )` | **Week boundaries crossed, with a FIXED Monday week start** — compiles to epoch day arithmetic, `(CEIL((days(end) + 1 + 7 - 4) / 7) - 1) - (… start …)` (live-verified 2026-10-06, se-thoughtspot: Sun 2026-10-04 → Sat 2026-10-10 = 1). A SQL `DATEDIFF(week)` follows the warehouse's week start (Snowflake `WEEK_START`), so the two agree only under a Monday start; the SQL translators emit a `sql_int_op` pass-through instead (#572 review). Optional `fiscal` third param. |
| `diff_months` | `diff_months ( [end] , [start] )` | **Month boundaries crossed, not complete months** — compiles to `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)` (live-verified 2026-10-06, se-thoughtspot: Jan31→Feb1 = 1, Jan31→Feb28 = 1, Jan20→Mar15 = 2, reversed = −1). A complete-months source (Excel `DATEDIF "M"`) needs a day-of-month correction. Optional `fiscal` third param. |
| `diff_quarters` | `diff_quarters ( [end] , [start] )` | **Quarter boundaries crossed** — compiles to `CEIL((((YEAR(end) - 1970) * 12) + MONTH(end)) / 3) - CEIL(… start …)` (live-verified 2026-10-06, se-thoughtspot, formula fidelity M0 `sf-date-012`: equal to Snowflake `DATEDIFF(quarter)` on all 10 rows). Optional `fiscal` third param. |
| `diff_years` | `diff_years ( [end] , [start] )` | **Calendar-year difference, not complete years** — compiles to `EXTRACT(YEAR FROM end) - EXTRACT(YEAR FROM start)` (live-verified 2026-10-06, se-thoughtspot: Dec31→Jan1 = 1, 2025-07-01→2026-06-30 = 1). A complete-years source (Excel `DATEDIF "Y"`) needs a month/day correction. Optional `fiscal` third param. |
| `diff_time` | `diff_time ( [end] , [start] )` | Difference in seconds — compiles to `TIMESTAMPDIFF(second, start, end)`, i.e. second **boundaries** on Snowflake (17:59:59.900 → 18:00:00.100 = 1; live-verified 2026-10-06, M0 `sf-ts-003`, and on TIMESTAMP_TZ) |
| `diff_hours` | `diff_hours ( [end] , [start] )` | **Hour boundaries, counted in UTC** — compiles to `DATEDIFF('HOUR', DATE '1970-01-01', end) - DATEDIFF('HOUR', DATE '1970-01-01', start)`. On DATE and TIMESTAMP_NTZ it equals Snowflake `DATEDIFF(hour)` (10:59 → 11:01 = 1, 10:00:30 → 10:59:59 = 0; M0 `sf-ts-001`, 2026-10-06). On a **TIMESTAMP_TZ with a non-whole-hour offset it does not**: at +05:30, 10:59 → 11:01 local is 1 in Snowflake and 0 here (4 of 10 rows wrong, M0 `sf-ts-005`), so the SQL translators emit a `sql_int_op` pass-through for `DATEDIFF(hour)` |
| `diff_minutes` | `diff_minutes ( [end] , [start] )` | **Minute boundaries** — compiles to the same epoch-anchored `DATEDIFF('MINUTE', …)` difference as `diff_hours`. Equal to Snowflake `DATEDIFF(minute)` on DATE, TIMESTAMP_NTZ (23:59:59 → 00:00:01 = 1) and TIMESTAMP_TZ at +05:30 (M0 `sf-date-015`, `sf-ts-002`, `sf-ts-006`, 2026-10-06) — every real UTC offset is whole minutes |
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

> **The window shape is completed from the search context — a window formula cannot declare its
> own PARTITION BY.** *Per ThoughtSpot domain review, 2026-07-30, live-confirmed the same day on
> `se-thoughtspot` by rejection.* `moving_*` and `cumulative_*` take a measure, frame offsets and
> **order** columns only; there is no partition argument and one cannot be added:
>
> ```
> # REJECTED — Search did not find "{"
> moving_sum ( [T::AMOUNT] , 1 , -1 , [T::ORDER_DATE] , { [T::REGION] } )
> cumulative_sum ( [T::AMOUNT] , [T::ORDER_DATE] , { [T::REGION] } )
>
> # REJECTED — Search did not find "query_groups ( ) )"
> moving_sum ( [T::AMOUNT] , 1 , -1 , [T::ORDER_DATE] , query_groups ( ) )
> ```
>
> The partition is whatever dimensions the user's search or Answer carries, minus the order
> columns. `rank` / `rank_percentile` are stricter still — arity is fixed at exactly two, so they
> are always global (see Rank Functions below). **The one exception is the semi-additive pair**
> `first_value` / `last_value`, whose partition *is* an explicit argument — see Semi-Additive
> Functions.
>
> Consequence for any conversion: a source window expression with an explicit `PARTITION BY`
> (SQL `OVER`, Tableau `WINDOW_*`, DAX, LookML) has **no** native ThoughtSpot target. Use a
> `sql_*_aggregate_op` pass-through carrying the whole `OVER` clause, wrapped in
> `group_aggregate ( ... , query_groups ( ) + { [partition_col] } , query_filters ( ) )` so the
> partition column reaches the GROUP BY — see *`group_aggregate` wrapping for pass-through window
> functions* below.
>
> The order columns are optional too: `cumulative_sum ( [T::AMOUNT] )` — a single argument, no
> order attribute — was **accepted** (2026-07-30), which leaves *both* halves of the window to the
> query context. `moving_*` is stricter: its frame offsets are positional and required
> (`moving_sum ( [m] , [ord] )` → `Function moving_sum expects 2nd argument to be Numeric`).
>
> **Functions that do NOT exist** (all rejected 2026-07-30 with
> `Search did not find "<name> ("`): `lag`, `dense_rank`, `row_number`, `nth_value`,
> `moving_count`, `moving_stddev`, `cumulative_count`. The ordered-window family is
> `sum` / `average` / `max` / `min` only; a windowed `COUNT` / `STDDEV` / `VARIANCE` has a
> *partitioned* form (`group_count`, `group_stddev`, `group_variance`) and no ordered or framed
> form of any kind.

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

**Signature live-verified 2026-07-30, se-thoughtspot** (`VALIDATE_ONLY`). Both forms above
import clean. Four hard constraints, each proven by rejection:

| Attempt | Verbatim rejection |
|---|---|
| `rank ( sum ( [m] ) )` — direction omitted | `Function rank expects 2 arguments, found 1.` |
| `rank ( [m] , 'desc' )` — bare column | `Function rank expects 1st argument to be aggregated.` |
| `rank ( sum ( [m] ) , 'desc' , [attr] )` — and the `{ [attr] }` and `query_groups ( )` spellings | `Function rank expects only 2 arguments.` |
| `rank ( group_aggregate ( sum ( [m] ) , { [a] } , query_filters ( ) ) , 'desc' )` | `Search did not find "group_aggregate ( sum ("` |

`rank_percentile` behaves identically (`Function rank_percentile expects only 2 arguments.`).
So a **partitioned rank has no native form at all** — not via an extra argument, and not by
wrapping the measure in a `group_aggregate`. Use the `sql_int_aggregate_op` pass-through with
`group_aggregate` wrapping (see below).

**Caveat — the direction string is not validated at import.** `rank ( sum ( [m] ) , 'descending' )`
was **accepted**. Acceptance proves the call shape, never the ordering; only `'asc'` and `'desc'`
are documented, so emit only those.

For dense ranking and row numbering, note that `dense_rank ( )` and `row_number ( )` **do not
exist** — both rejected 2026-07-30. Use a pass-through.

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

**This family is the exception to the no-explicit-PARTITION-BY rule above** — its partition and
its axis are *both* explicit formula arguments. Live-verified 2026-07-30, se-thoughtspot
(`VALIDATE_ONLY`); every grouping form below imports clean:

| Grouping argument | Accepted? | Meaning |
|---|:-:|---|
| `query_groups ( )` | ✓ | Partition by the query grain (the common snapshot case) |
| `{ [T::attr] }` | ✓ | **Fixed single-column partition** — declared in the formula |
| `{ [T::a] , [T::b] }` | ✓ | **Fixed multi-column partition** |
| `{ }` | ✓ | Grand total — no partition |
| `query_groups ( ) - { [T::attr] }` | ✓ | Query grain minus one dimension |

Two enforced constraints:

- **The axis argument must be a List** — the braces are mandatory:
  `last_value ( sum ( [m] ) , query_groups ( ) , [T::DATE] )` is rejected with
  `Function last_value expects 3rd argument to be List.`
- All four spellings (`last_value`, `first_value`, `last_value_in_period`,
  `first_value_in_period`) share this identical three-argument shape, and a two-column axis
  (`{ [d1] , [d2] }`) is also accepted.

**Caveat — the axis column's type is not validated at import.** A `VARCHAR` axis was accepted.
Acceptance proves the call shape, not that the axis is temporal; supply a DATE / DATE_TIME column.

```yaml
expr: >-
  last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
```

**Semi-additive variants:**

| Function | Behavior | Translatable? |
|---|---|---|
| `last_value(..., query_groups(), {date})` | Last snapshot value, query-grain partition | Yes — via `non_additive_dimensions` in Snowflake SV |
| `first_value(..., query_groups(), {date})` | First snapshot value | **Yes** — `NON ADDITIVE BY (dim **desc** nulls last)`, i.e. `sort_direction: descending` (corrected 2026-08-26, finding 13.8). `NON ADDITIVE BY` takes `{ASC\|DESC}`; DESC selects the earliest value. The previous "only supports last-value semantics" reason was false, contradicted the row two lines below (`first_value_in_period` → "treat same as `first_value`", which was marked No), and contradicted `ts-snowflake-formula-translation.md:1036`, which had already mapped this correctly. |
| `last_value_in_period(...)` | Last value only if the period's last date is complete | Yes — treat same as `last_value(...)` |
| `first_value_in_period(...)` | First value only if the period's first date is complete | Yes — treat same as `first_value(...)` |
| `agg(last_value(...))` e.g. `max(last_value(...))` | Re-aggregation of a snapshot metric | No |
| `agg(first_value(...))` e.g. `max(first_value(...))` | Re-aggregation of a snapshot metric | No — same as the row above. Added 2026-08-26 with finding 13.8: promoting `first_value` to translatable without this row would leave a reader seeing Yes with no re-aggregation caveat, where the sibling mapping carries both. |

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
| `sql_double_aggregate_op(template, args...)` | DOUBLE | Numeric (non-integer) aggregate/metric |
| `sql_date_aggregate_op(template, args...)` | DATE | Date aggregate/metric |
| `sql_date_time_aggregate_op(template, args...)` | DATETIME | Datetime aggregate/metric |
| `sql_bool_aggregate_op(template, args...)` | BOOLEAN | Boolean aggregate/metric |

**There is no `sql_number_aggregate_op`** (nor `sql_number_op`) — the formula parser rejects both ("Formula addition failed"). Verified 2026-10-06 on se-thoughtspot by `VALIDATE_ONLY` import of each name over `MAX({0})`: `sql_double_aggregate_op`, `sql_int_aggregate_op`, `sql_string_aggregate_op`, `sql_date_aggregate_op`, `sql_date_time_aggregate_op` and `sql_bool_aggregate_op` were accepted. Earlier revisions of this file and the mapping docs named `sql_number_aggregate_op`; it was never probed (BL-335).

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

### JSON / VARIANT path access — bracket notation only

ThoughtSpot's `sql_*_op` template parser **rejects colon-and-dot path syntax** for
navigating semi-structured (JSON / VARIANT) columns, even though that syntax is valid
SQL in the source warehouse. The template imports/validates only when every path
segment is written in `['segment']` **bracket notation**.

| Warehouse SQL — valid, but REJECTED inside a TS template | ThoughtSpot pass-through — bracket notation |
|---|---|
| `PARSE_JSON({0}):address` | `sql_string_op ( "PARSE_JSON({0})['address']" , [T::JSON_STRING] )` |
| `PARSE_JSON({0}):address.city::STRING` | `sql_string_op ( "PARSE_JSON({0})['address']['city']" , [T::JSON_STRING] )` |

**Conversion rule:** replace the leading `:` and every `.` separator in the path with
its own bracketed key — `:a.b.c` → `['a']['b']['c']`. Bracket notation is also valid
SQL in the source warehouse, so the emitted template both passes the TS parser and
executes correctly. The `sql_string_op` return type supplies STRING typing, so a
trailing `::STRING` cast is optional — keep it only if the warehouse needs the explicit
VARIANT→scalar cast.

This is a **ThoughtSpot formula-parser constraint, not a warehouse constraint** — it
applies to any pass-through carrying a JSON path regardless of source platform. The
colon-free *replacement*, however, is platform-specific — the bracket form above is
valid on **Snowflake** (verified 2026-07-15) but **not on Databricks**, where
`parse_json(col)['key']` errors (`VARIANT` is not a bracket-extractable type) and the
correct colon-free form is `get_json_object(col, '$.key')`. Use the per-platform
mapping for the right replacement:
[Snowflake](../mappings/ts-snowflake/ts-snowflake-formula-translation.md),
[Databricks](../mappings/ts-databricks/ts-databricks-formula-translation.md).

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

**"Cover the use case" has one specific meaning for `moving_*` / `cumulative_*`:** the source's
partition must be the dimensions the user's search will actually carry. If the source declares an
explicit `PARTITION BY`, the native form does **not** cover it — there is no partition slot (see
the note at the head of *Window Functions*) — so a `sql_*_aggregate_op` carrying the whole `OVER`
clause is the faithful translation, and the native `moving_sum` is a **documented downgrade** the
user should be asked to accept rather than a silent substitution. `first_value` / `last_value` are
the exception: their partition is explicit, so they cover an explicit `PARTITION BY` exactly.

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
