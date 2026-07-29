# Ossie expression language → ThoughtSpot function mapping

**Status:** draft for review on apache/ossie#285 · **Coverage:** 146/146 functions,
operators and constructs from `core-spec/expression_language.md` (spec version `0.2.0.dev`,
`core-spec/expression_language.md:767`; all Ossie citations are `path:line` against
apache/ossie @ `c26b61c`) · **Classifications:** `direct` (native ThoughtSpot formula
equivalent, possibly as a documented composition of native functions) · `passthrough`
(requires a ThoughtSpot `sql_*_op` pass-through — warehouse-dialect-specific, bypasses
ThoughtSpot's query planning) · `unmappable` (converter raises an issue; construct
preserved in `custom_extensions` for roundtrip) · **TS ground truth:**
`agents/shared/schemas/thoughtspot-formula-patterns.md` and
`agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` — internal paths
in the ThoughtSpot skills repo, cited below by section name as the *formula reference* and
the *Snowflake formula mapping*. They record ThoughtSpot's formula language as verified
against live instances and override any other description of it.

This is the companion to the construct-mapping document, which stops at the boundary where
an expression string begins. That document owns identifier rewriting, dialect selection,
the `custom_extensions` payload and the structural asks **A1**–**A8**; this one owns
everything inside `expression`. Rules introduced here are numbered **E1**–**E12** and new
upstream asks **A9**–**A12**, continuing that document's sequence.

---

## How to read the tables

Every row's ThoughtSpot cell is written in ThoughtSpot formula syntax: column references
are `[TABLE::Column]`, and the spaces around parentheses and commas are the canonical form
(`concat ( [a] , [b] )`). Reference rewriting is not shown per row — it is uniform and
lives in the construct-mapping document (**ID3**).

- **E1 — one row per construct.** Every named function, operator and syntactic construct
  the specification declares supported appears in exactly one row. Two categories are
  deliberately outside the 146. **Argument vocabularies** (`EXTRACT` date parts,
  `DATE_TRUNC` precisions, `CAST` target types, `TO_CHAR` format tokens) are arguments, not
  constructs; they are given in the sub-tables marked *(not counted)*. And the
  **informative tables** — the per-engine dialect variations (`:663-670`) and the
  Tableau / Looker Studio / DAX cross-reference (`:679-743`) — describe *other* products'
  spellings, so names appearing only there (`APPROX_QUANTILES`, `DATE_ADD`, `RUNNING_SUM`)
  are not Ossie functions and get no row. Everything the compliance levels bind as
  REQUIRED, RECOMMENDED or EXPERIMENTAL does.
- **E2 — `direct` may be a composition.** ThoughtSpot's formula language has no `SIGN`,
  `PI` or `PERCENT_RANK`, but each is exactly expressible in native functions and
  arithmetic. Those rows are `direct`, and the Notes give the composition. Reserving
  `direct` for one-to-one name matches would push a dozen exactly-expressible functions
  into `passthrough` and misrepresent the fidelity of the mapping.
- **E3 — a `direct` row whose argument space is only partly covered names its fallback.**
  Several constructs are `direct` for the arguments a BI model actually uses and
  `passthrough` beyond that (`EXTRACT` for `MILLISECOND`, `LIKE` for interior wildcards,
  `RANK` with an explicit `PARTITION BY`). The row is classified on the covered case and
  the Notes name the fallback and its `sql_*_op` variant. A converter implementing this
  mapping branches on the argument, so the fallback is not hypothetical.
- **E4 — every `passthrough` row names its variant.** The `sql_*_op` family is typed
  (`sql_string_op`, `sql_int_op`, `sql_double_op`, `sql_bool_op`, `sql_date_op`,
  `sql_date_time_op`, and the `sql_string_aggregate_op` / `sql_int_aggregate_op` /
  `sql_number_aggregate_op` / `sql_date_time_aggregate_op` aggregate forms). Choosing the
  wrong variant produces a column of the wrong type, so the variant is part of the mapping,
  not an implementation detail.

---

## Coverage summary

| Section | Rows | `direct` | `passthrough` | `unmappable` |
|---|--:|--:|--:|--:|
| Aggregate functions | 18 | 12 | 6 | 0 |
| Date/time functions | 24 | 17 | 7 | 0 |
| String functions | 21 | 12 | 9 | 0 |
| Mathematical functions | 25 | 23 | 2 | 0 |
| Conditional functions | 9 | 9 | 0 | 0 |
| Window functions | 14 | 9 | 5 | 0 |
| Type conversion | 2 | 2 | 0 | 0 |
| Operators and constructs | 33 | 30 | 2 | 1 |
| **Total** | **146** | **114** | **31** | **1** |

78% of the specification is expressible in ThoughtSpot's native formula language. The
`passthrough` set concentrates in three places — population statistics and percentiles,
regular expressions, and case-insensitive string handling — and there is exactly one
`unmappable` construct, `EXISTS_IN()`, which is unmappable because the specification does
not define it (see ask **A9**).

---

## Aggregate functions

Source tables: `core-spec/expression_language.md:157-163` (core), `:169-174` (statistical),
`:180-182` (percentile), `:192-193` (approximate).

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `SUM(expr)` | direct | `sum ( [x] )` | |
| `COUNT(expr)` | direct | `count ( [x] )` | Counts non-null values on both sides. |
| `COUNT(*)` | direct | `count ( [T::key] )` | ThoughtSpot has no `count(*)`; the row count is `count()` over a column known to be non-null. The converter uses the dataset's `primary_key` when the model declares one, and raises an issue rather than guessing a column when it does not. |
| `COUNT(DISTINCT expr)` | direct | `unique count ( [x] )` | **A space, not an underscore.** `count_distinct(...)` is rejected by the formula parser. See ask **A9** on `DISTINCT` as a general modifier. |
| `AVG(expr)` | direct | `average ( [x] )` | |
| `MIN(expr)` | direct | `min ( [x] )` | ThoughtSpot `min` is **aggregate-only** — it never compares two columns row-wise. Scalar two-argument minima are `LEAST`, a separate row. |
| `MAX(expr)` | direct | `max ( [x] )` | Aggregate-only, as `MIN`. |
| `STDDEV(expr)` | direct | `stddev ( [x] )` | Sample standard deviation on both sides. |
| `STDDEV_POP(expr)` | passthrough | `sql_number_aggregate_op ( "STDDEV_POP({0})" , [x] )` | **Variant: `sql_number_aggregate_op`.** ThoughtSpot `stddev` is sample-only; there is no population form, and substituting it would change the divisor from *n−1* to *n*. |
| `STDDEV_SAMP(expr)` | direct | `stddev ( [x] )` | Specification alias for `STDDEV` (`:171`). |
| `VARIANCE(expr)` | direct | `variance ( [x] )` | Sample variance on both sides. |
| `VAR_POP(expr)` | passthrough | `sql_number_aggregate_op ( "VAR_POP({0})" , [x] )` | **Variant: `sql_number_aggregate_op`.** Same divisor reason as `STDDEV_POP`. |
| `VAR_SAMP(expr)` | direct | `variance ( [x] )` | Specification alias for `VARIANCE` (`:174`). |
| `MEDIAN(expr)` | direct | `median ( [x] )` | |
| `PERCENTILE_CONT(p) WITHIN GROUP (ORDER BY expr)` | passthrough | `sql_number_aggregate_op ( "PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {0})" , [x] )` | **Variant: `sql_number_aggregate_op`.** No native percentile function. `p` is a literal in the specification's syntax, so it is baked into the template rather than passed as a placeholder. `p = 0.5` is the one case with a native equivalent — `median ( [x] )` — and the converter should prefer it. |
| `PERCENTILE_DISC(p) WITHIN GROUP (ORDER BY expr)` | passthrough | `sql_number_aggregate_op ( "PERCENTILE_DISC(0.75) WITHIN GROUP (ORDER BY {0})" , [x] )` | **Variant: `sql_number_aggregate_op`.** As `PERCENTILE_CONT`; the discrete/interpolated distinction is preserved only because the template is emitted verbatim. |
| `APPROX_COUNT_DISTINCT(expr)` | passthrough | `sql_int_aggregate_op ( "APPROX_COUNT_DISTINCT({0})" , [x] )` | **Variant: `sql_int_aggregate_op`.** ThoughtSpot's `unique count ( [x] )` is the exact-semantics alternative: same answer to within the sketch's ~2% error (`:192`), at exact-count cost. The converter emits the pass-through by default — the specification chose approximate deliberately — and offers the exact form as a documented downgrade. |
| `APPROX_PERCENTILE(expr, p)` | passthrough | `sql_number_aggregate_op ( "APPROX_PERCENTILE({0}, 0.5)" , [x] )` | **Variant: `sql_number_aggregate_op`.** `p` baked into the template as for the exact percentiles. |

**Conditional aggregation** (`:217-230`) needs no rows of its own — it is `CASE` inside an
aggregate, and both parts already have rows. It is worth recording that the round trip is
better than pass-through in this direction: ThoughtSpot has a native `*_if` family
(`sum_if`, `count_if`, `unique_count_if`, `average_if`, `min_if`, `max_if`, `stddev_if`,
`variance_if`), so `SUM(CASE WHEN cond THEN amount ELSE 0 END)` becomes
`sum_if ( cond , [T::amount] )` rather than a nested `if`. The `DISTINCT` *modifier* on
`SUM` is a different matter and has its own row under Operators.

**Decomposability** (`:236-241`) has no ThoughtSpot analogue to map. ThoughtSpot decides
re-aggregation from the formula shape and the query grain rather than from a declared
category, so the classification is informative here — but it is exactly the information a
multi-stage aggregation would need, and it is worth preserving. See ask **A12**.

---

## Date/time functions

Source tables: `core-spec/expression_language.md:251-253` (current), `:259-266`
(extraction), `:272-279` (alternative extraction), `:292` (truncation), `:307-308`
(arithmetic), `:330-337` (construction), `:353-354` (format construction, EXPERIMENTAL),
`:360` (formatting, EXPERIMENTAL).

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CURRENT_DATE` / `CURRENT_DATE()` | direct | `today ( )` | Both specification spellings map to the same function. |
| `CURRENT_TIMESTAMP` / `CURRENT_TIMESTAMP()` | direct | `now ( )` | |
| `CURRENT_TIME` / `CURRENT_TIME()` | direct | `time ( now ( ) )` | ThoughtSpot has no current-time function but `time ( )` extracts the time part of a datetime, so the composition is exact. |
| `YEAR(date_expr)` | direct | `year ( [d] )` | |
| `QUARTER(date_expr)` | direct | `quarter_number ( [d] )` | The function is `quarter_number`, not `quarter`. |
| `MONTH(date_expr)` | direct | `month_number ( [d] )` | **Not `month ( )`.** ThoughtSpot's `month` returns the month *name* ("January"); `month_number` returns 1–12, which is what `:261` specifies. Mapping to `month` silently changes the column's type from integer to string. |
| `DAY(date_expr)` | direct | `day ( [d] )` | Day of month, 1–31 on both sides. |
| `DAYOFYEAR(date_expr)` | direct | `day_number_of_year ( [d] )` | The function is `day_number_of_year`, not `day_of_year`. |
| `HOUR(timestamp_expr)` | direct | `hour_of_day ( [t] )` | The function is `hour_of_day`, not `hour`. |
| `MINUTE(timestamp_expr)` | passthrough | `sql_int_op ( "MINUTE({0})" , [t] )` | **Variant: `sql_int_op`.** No native minute-of-hour extractor; `add_minutes` and `diff_minutes` exist but neither extracts. |
| `SECOND(timestamp_expr)` | passthrough | `sql_int_op ( "SECOND({0})" , [t] )` | **Variant: `sql_int_op`.** As `MINUTE`. |
| `EXTRACT(part FROM date_expr)` | direct | per-part — see the date-part table below | Rewritten to the part's own ThoughtSpot function; there is no generic extractor. 8 of the 11 specified parts are `direct`; `MINUTE`, `SECOND` and `MILLISECOND` fall back to `sql_int_op` (**E3**). |
| `DATE_PART('part', date_expr)` | direct | per-part — see the date-part table below | Identical treatment to `EXTRACT`; the two spellings collapse onto one rewrite (`:276-279`). |
| `DATE_TRUNC(part, date_expr)` | direct | per-precision — see the truncation table below | **ThoughtSpot has no `date_trunc`.** The `start_of_*` family covers 7 of the 8 specified precisions; `'second'` falls back to `sql_date_time_op` (**E3**). |
| `DATEADD(part, amount, date_expr)` | direct | per-part `add_*` — see the arithmetic table below | **Argument order differs:** ThoughtSpot is `add_days ( [d] , n )`, the specification is `DATEADD(day, n, d)`. Every specified part is reachable, two by arithmetic on a coarser unit. |
| `DATEDIFF(part, start_date, end_date)` | direct | per-part `diff_*` — see the arithmetic table below | **Argument order is reversed:** ThoughtSpot is `diff_days ( [end] , [start] )` — end first. Getting this wrong silently negates every duration in the model. |
| `DATE '2024-01-15'` (typed literal) | direct | `to_date ( '2024-01-15' , 'yyyy-MM-dd' )` | A bare `'2024-01-15'` in a ThoughtSpot formula is parsed as *arithmetic* (`2024 − 1 − 15`), so the literal must always be wrapped. `to_date` takes exactly two arguments, so the converter supplies the ISO format model. |
| `TIMESTAMP_NTZ '2024-01-15 10:30:00'` (typed literal) | passthrough | `sql_date_time_op ( "CAST('2024-01-15 10:30:00' AS TIMESTAMP)" )` | **Variant: `sql_date_time_op`.** `to_date` returns a DATE and drops the time part, so there is no native way to construct a wall-clock timestamp. A zero-placeholder template is a documented form of the pass-through. |
| `TIME '10:30:00'` (typed literal) | passthrough | `sql_date_time_op ( "CAST('10:30:00' AS TIME)" )` | **Variant: `sql_date_time_op`.** ThoughtSpot has no TIME column type — `time ( )` extracts a time *from a datetime*, it does not construct one — so the pass-through returns DATETIME and the date part is whatever the warehouse defaults to. Flagged with an issue for that reason, not only for the dialect. |
| `TO_DATE(string)` | direct | `to_date ( [s] , 'yyyy-MM-dd' )` | The single-argument ISO form (`:336`). ThoughtSpot's `to_date` is strictly two-argument, so the converter supplies `'yyyy-MM-dd'`. |
| `TO_TIMESTAMP(string)` | passthrough | `sql_date_time_op ( "TO_TIMESTAMP({0})" , [s] )` | **Variant: `sql_date_time_op`.** `to_date` is date-only; parsing to a timestamp would drop the time silently. |
| `TO_DATE(string, format)` *(EXPERIMENTAL)* | direct | `to_date ( [s] , <translated format> )` | Format tokens are translated, not passed through — see the format-token table. ThoughtSpot accepts Java/LDML tokens (`yyyy-MM-dd`) and `strptime` `%`-codes, which between them cover the specification's entire portable core. |
| `TO_TIMESTAMP(string, format)` *(EXPERIMENTAL)* | passthrough | `sql_date_time_op ( "TO_TIMESTAMP({0}, 'YYYY-MM-DD HH24:MI:SS')" , [s] )` | **Variant: `sql_date_time_op`.** Date-only `to_date` again. The format model inside the template is the *warehouse's*, not Ossie's, so the token translation below does not apply — this is the sharpest case of the pass-through caveat. |
| `TO_CHAR(date_expr, format)` *(EXPERIMENTAL)* | passthrough | `sql_string_op ( "TO_CHAR({0}, 'YYYY-MM')" , [d] )` | **Variant: `sql_string_op`.** ThoughtSpot has no general date formatter. Single-token formats do have native equivalents and the converter prefers them: `'YYYY'` → `year_name ( [d] )`, `'MONTH'` → `month ( [d] )`, `'DAY'` → `day_of_week ( [d] )`. Those three return locale-dependent text on both sides (`:385-387`). |

### `EXTRACT` / `DATE_PART` parts *(not counted — arguments)*

Specified vocabulary: `core-spec/expression_language.md:284-286`.

| Part | ThoughtSpot | Class |
|---|---|---|
| `YEAR` | `year ( [d] )` | direct |
| `QUARTER` | `quarter_number ( [d] )` | direct |
| `MONTH` | `month_number ( [d] )` | direct |
| `WEEK` | `week_number_of_year ( [d] )` | direct |
| `DAY` | `day ( [d] )` | direct |
| `DAYOFWEEK` | `day_number_of_week ( [d] )` | direct — ThoughtSpot numbers 1 = Monday … 7 = Sunday. The specification does not fix a base, and engines disagree (Snowflake and BigQuery start at Sunday), so the converter records the base in the issue log rather than assuming parity. See ask **A11**. |
| `DAYOFYEAR` | `day_number_of_year ( [d] )` | direct |
| `HOUR` | `hour_of_day ( [d] )` | direct |
| `MINUTE` | `sql_int_op ( "MINUTE({0})" , [d] )` | passthrough |
| `SECOND` | `sql_int_op ( "SECOND({0})" , [d] )` | passthrough |
| `MILLISECOND` | `sql_int_op ( "EXTRACT(MILLISECOND FROM {0})" , [d] )` | passthrough |

Note the asymmetry in the specification's own function tables: `DAYOFYEAR` has a
first-class function (`:263`) but `DAYOFWEEK` and `WEEK` exist only as `EXTRACT`/`DATE_PART`
parts (`:284-285`). ThoughtSpot has functions for all three. See ask **A11**.

### `DATE_TRUNC` precisions *(not counted — arguments)*

Specified vocabulary: `core-spec/expression_language.md:294`.

| Precision | ThoughtSpot | Class |
|---|---|---|
| `'year'` | `start_of_year ( [d] )` | direct |
| `'quarter'` | `start_of_quarter ( [d] )` | direct |
| `'month'` | `start_of_month ( [d] )` | direct |
| `'week'` | `start_of_week ( [d] )` | direct — the specification says Monday-start (`:300`); ThoughtSpot's week start is an instance setting, so the converter verifies alignment and raises an issue when it cannot. |
| `'day'` | `date ( [d] )` | direct |
| `'hour'` | `start_of_hour ( [d] )` | direct |
| `'minute'` | `start_of_min ( [d] )` | direct — the function is `start_of_min`, not `start_of_minute`. |
| `'second'` | `sql_date_time_op ( "DATE_TRUNC('second', {0})" , [d] )` | passthrough |

### `DATEADD` / `DATEDIFF` parts *(not counted — arguments)*

| Part | `DATEADD(part, n, d)` → | `DATEDIFF(part, start, end)` → |
|---|---|---|
| `day` | `add_days ( [d] , n )` | `diff_days ( [end] , [start] )` |
| `week` | `add_weeks ( [d] , n )` | `diff_weeks ( [end] , [start] )` |
| `month` | `add_months ( [d] , n )` | `diff_months ( [end] , [start] )` |
| `quarter` | `add_months ( [d] , 3 * n )` | `diff_quarters ( [end] , [start] )` |
| `year` | `add_years ( [d] , n )` | `diff_years ( [end] , [start] )` |
| `hour` | `add_minutes ( [d] , 60 * n )` | `diff_hours ( [end] , [start] )` |
| `minute` | `add_minutes ( [d] , n )` | `diff_minutes ( [end] , [start] )` |
| `second` | `add_seconds ( [d] , n )` | `diff_time ( [end] , [start] )` |

There is no `add_quarters` or `add_hours`; both are exact multiples of a unit that does
exist, so the rewrite is arithmetic rather than a pass-through. `diff_time` returns
seconds.

### `TO_DATE` / `TO_CHAR` format tokens *(not counted — arguments)*

The specification defines a portable core of tokens with informative `strftime` and
Java/LDML columns (`core-spec/expression_language.md:369-383`). ThoughtSpot's `to_date`
accepts both vocabularies, so the specification's own informative columns *are* the
translation:

| Ossie token | ThoughtSpot (Java/LDML form) | ThoughtSpot (`strptime` form) |
|---|---|---|
| `YYYY` | `yyyy` | `%Y` |
| `YY` | `yy` | `%y` |
| `MM` | `MM` | `%m` |
| `MON` | `MMM` | `%b` |
| `MONTH` | `MMMM` | `%B` |
| `DD` | `dd` | `%d` |
| `DY` | `EEE` | `%a` |
| `DAY` | `EEEE` | `%A` |
| `HH24` | `HH` | `%H` |
| `HH12` / `HH` | `hh` | `%I` |
| `MI` | `mm` | `%M` |
| `SS` | `ss` | `%S` |
| `AM` / `PM` | `a` | `%p` |

Two constraints on using it. The two vocabularies must not be mixed within one format
string. And because `to_date` returns a DATE, tokens below day grain affect *parsing* only
— they let a timestamp string be consumed, but the time is dropped from the result, so a
format string containing them raises an issue. Sub-second tokens are outside the portable
core on the Ossie side too (`:389-391`).

---

## String functions

Source tables: `core-spec/expression_language.md:400-412` (manipulation), `:418-422`
(search), `:430` (regexp pattern match), `:441-443` (regular expressions). The `||`
operator, `LIKE` and `ILIKE` are specified in this section of the document but are
operators, so they are rowed under Operators and constructs.

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CONCAT(str1, str2, ...)` | direct | `concat ( [a] , [b] , ... )` | N-ary on both sides. **`+` does not concatenate in ThoughtSpot** — it is numeric-only and the parser rejects string operands, so `||` and `CONCAT` both land here. |
| `LENGTH(str)` | direct | `strlen ( [s] )` | Characters, not bytes, on both sides. |
| `LOWER(str)` | passthrough | `sql_string_op ( "LOWER({0})" , [s] )` | **Variant: `sql_string_op`.** There is no native `lower` in ThoughtSpot. |
| `UPPER(str)` | passthrough | `sql_string_op ( "UPPER({0})" , [s] )` | **Variant: `sql_string_op`.** There is no native `upper` in ThoughtSpot. `LOWER`/`UPPER` are the most-used functions in the whole `passthrough` set, and their absence is also what forces `ILIKE` and case-insensitive comparison into pass-throughs. |
| `TRIM(str)` | direct | `trim ( [s] )` | Both remove leading *and* trailing whitespace. |
| `LTRIM(str)` | passthrough | `sql_string_op ( "LTRIM({0})" , [s] )` | **Variant: `sql_string_op`.** ThoughtSpot's `trim` is two-sided with no one-sided form, so substituting it would strip trailing whitespace the source preserved. |
| `RTRIM(str)` | passthrough | `sql_string_op ( "RTRIM({0})" , [s] )` | **Variant: `sql_string_op`.** As `LTRIM`. |
| `LEFT(str, n)` | direct | `left ( [s] , n )` | |
| `RIGHT(str, n)` | direct | `right ( [s] , n )` | |
| `SUBSTRING(str, start, length)` | direct | `substr ( [s] , start - 1 , length )` | **Index base differs.** ANSI `SUBSTRING` is 1-based; ThoughtSpot's `substr` is 0-based. The `− 1` is mandatory and is the single most likely off-by-one in the whole mapping. When `start` is an expression rather than a literal, the arithmetic is emitted rather than folded. |
| `REPLACE(str, from, to)` | direct | `replace ( [s] , [from] , [to] )` | Replaces all occurrences on both sides. Pending live confirmation — see *Rows pending live confirmation*; the fallback is `sql_string_op ( "REPLACE({0},{1},{2})" , [s] , [from] , [to] )`. |
| `SPLIT_PART(str, delimiter, part)` | passthrough | `sql_string_op ( "SPLIT_PART({0}, {1}, {2})" , [s] , [delim] , [n] )` | **Variant: `sql_string_op`.** ThoughtSpot has no tokenising function at all — not `split`, `split_part` or an nth-occurrence search — so there is no composition to fall back on. |
| `POSITION(substr IN str)` | direct | `strpos ( [s] , [substr] )` | **Operand order is reversed** (haystack first in ThoughtSpot) and the specification's infix `IN` form becomes a comma. 1-based, returning 0 when absent, on both sides. |
| `CHARINDEX(substr, str)` | direct | `strpos ( [s] , [substr] )` | Specification alias for `POSITION` (`:419`) with the operands already in prefix order; the reversal is the same. |
| `CONTAINS(str, substr)` | direct | `contains ( [s] , [substr] )` | Returns boolean on both sides. |
| `STARTSWITH(str, prefix)` | direct | `starts_with ( [s] , [prefix] )` | Pending live confirmation — see *Rows pending live confirmation*; the composition fallback is `strpos ( [s] , [prefix] ) = 1`. |
| `ENDSWITH(str, suffix)` | direct | `ends_with ( [s] , [suffix] )` | Pending live confirmation; the composition fallback is `substr ( [s] , strlen ( [s] ) - strlen ( [suffix] ) , strlen ( [suffix] ) ) = [suffix]`. |
| `REGEXP_LIKE(str, pattern)` | passthrough | `sql_bool_op ( "REGEXP_LIKE({0}, {1})" , [s] , [pattern] )` | **Variant: `sql_bool_op`** — boolean return, so not `sql_string_op`. ThoughtSpot has no regular-expression support of any kind. |
| `REGEXP_EXTRACT(str, pattern)` | passthrough | `sql_string_op ( "REGEXP_SUBSTR({0}, {1})" , [s] , [pattern] )` | **Variant: `sql_string_op`.** The function *name* inside the template is dialect-specific — Snowflake spells it `REGEXP_SUBSTR`, others `REGEXP_EXTRACT` — so the converter selects it from the connection's dialect and raises an issue when the dialect is unknown. |
| `REGEXP_REPLACE(str, pattern, replacement)` | passthrough | `sql_string_op ( "REGEXP_REPLACE({0},{1},{2})" , [s] , [pattern] , [repl] )` | **Variant: `sql_string_op`.** Name is portable; the *pattern dialect* (POSIX vs PCRE, backreference syntax) is not. |
| `REGEXP_COUNT(str, pattern)` | passthrough | `sql_int_op ( "REGEXP_COUNT({0}, {1})" , [s] , [pattern] )` | **Variant: `sql_int_op`** — integer return. |

---

## Mathematical functions

Source tables: `core-spec/expression_language.md:453-459` (basic), `:465-470` (advanced),
`:476-485` (trigonometric), `:491-492` (comparison).

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ABS(x)` | direct | `abs ( [x] )` | |
| `ROUND(x, d)` | direct | `round ( [x] , d )` | |
| `FLOOR(x)` | direct | `floor ( [x] )` | |
| `CEIL(x)` / `CEILING(x)` | direct | `ceil ( [x] )` | Both specification spellings map to `ceil`. |
| `TRUNC(x, d)` / `TRUNCATE(x, d)` | passthrough | `sql_double_op ( "TRUNC({0}, {1})" , [x] , d )` | **Variant: `sql_double_op`.** ThoughtSpot has no truncation. `floor` agrees with `TRUNC` only for `x ≥ 0` and `d = 0`, and `round` disagrees at every half-value, so neither is a safe substitute. |
| `MOD(x, y)` | direct | `mod ( [x] , [y] )` | Sign-of-result for negative operands follows the warehouse in both cases. |
| `SIGN(x)` | direct | `if ( [x] > 0 ) then 1 else if ( [x] < 0 ) then -1 else 0` | No native `sign`, but the three-way result is exactly expressible. The `else 0` is required — ThoughtSpot rejects an `if` chain with no `else`. |
| `POWER(x, y)` | direct | `pow ( [x] , [y] )` | **The function is `pow`. `power` is rejected by the parser.** |
| `SQRT(x)` | direct | `sqrt ( [x] )` | |
| `EXP(x)` | direct | `exp ( [x] )` | |
| `LN(x)` | direct | `ln ( [x] )` | |
| `LOG(base, x)` | direct | `log2 ( [x] )` / `log10 ( [x] )` / `safe_divide ( ln ( [x] ) , ln ( base ) )` | ThoughtSpot has fixed-base `log2` and `log10` only. Arbitrary bases go through change-of-base, which is exact. `safe_divide` rather than `/` guards `base = 1`. |
| `LOG10(x)` | direct | `log10 ( [x] )` | |
| `SIN(x)` | direct | `sin ( [x] * 180 / 3.14159265358979 )` | **ThoughtSpot trigonometry is in degrees; the specification is in radians (`:476`).** The conversion is mandatory — a bare `sin ( [x] )` returns the sine of *x degrees* and is wrong for every non-zero input. |
| `COS(x)` | direct | `cos ( [x] * 180 / 3.14159265358979 )` | Degrees, as `SIN`. |
| `TAN(x)` | direct | `tan ( [x] * 180 / 3.14159265358979 )` | Degrees, as `SIN`. |
| `ASIN(x)` | direct | `( asin ( [x] ) * 3.14159265358979 / 180 )` | Inverse functions convert the other way: ThoughtSpot returns degrees, the specification expects radians. |
| `ACOS(x)` | direct | `( acos ( [x] ) * 3.14159265358979 / 180 )` | Degrees → radians, as `ASIN`. |
| `ATAN(x)` | direct | `( atan ( [x] ) * 3.14159265358979 / 180 )` | Degrees → radians, as `ASIN`. |
| `ATAN2(y, x)` | passthrough | `sql_double_op ( "ATAN2({0}, {1})" , [y] , [x] )` | **Variant: `sql_double_op`.** `atan2` is not a two-argument `atan` — it is quadrant-aware and defined where `x = 0`. Composing it from `atan` plus sign tests is possible but the branch table is easy to get wrong at the axes, so the pass-through is the honest mapping. |
| `RADIANS(degrees)` | direct | `[x] * 3.14159265358979 / 180` | No native `radians`; the arithmetic is exact and dialect-free. |
| `DEGREES(radians)` | direct | `[x] * 180 / 3.14159265358979` | No native `degrees`; as above. |
| `PI()` | direct | `3.14159265358979` | No native `pi`. The literal is emitted at the precision ThoughtSpot's own documented composites use; `sql_double_op ( "pi()" )` is available where full warehouse precision matters. |
| `GREATEST(x, y, ...)` | direct | `greatest ( [x] , [y] , ... )` | **Not `max`.** ThoughtSpot's `max` is an aggregate; `greatest` is the row-wise N-ary function. Mapping `GREATEST` to `max` collapses the column to one value and also flips it from attribute to measure. |
| `LEAST(x, y, ...)` | direct | `least ( [x] , [y] , ... )` | **Not `min`**, for the same reason. |

---

## Conditional functions

Source table: `core-spec/expression_language.md:520-528`. `CASE` (both forms) and the
boolean literals and operators from `:534-537` are rowed under Operators and constructs.

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `IF(condition, true_result, false_result)` | direct | `if ( cond ) then a else b` | **The parentheses around the condition are mandatory** for TML import — without them the parser reports `Expecting keyword '('`. This applies to every condition shape, including a bare BOOL column reference. |
| `IFF(condition, true_result, false_result)` | direct | `if ( cond ) then a else b` | Specification alias for `IF` (`:521`). |
| `NULLIF(expr1, expr2)` | direct | `nullif ( [a] , [b] )` | |
| `COALESCE(expr1, expr2, ...)` | direct | `ifnull ( [a] , ifnull ( [b] , [c] ) )` | ThoughtSpot's `ifnull` is strictly two-argument, so an N-ary `COALESCE` becomes a right-nested chain. Two arguments is the common case and needs no nesting. |
| `IFNULL(expr, default)` | direct | `ifnull ( [x] , [default] )` | |
| `NVL(expr, default)` | direct | `ifnull ( [x] , [default] )` | Specification alias for two-argument `COALESCE` (`:525`). |
| `NVL2(expr, not_null_result, null_result)` | direct | `if ( isnotnull ( [x] ) ) then [a] else [b]` | No native three-way null function; the composition is exact. |
| `ZEROIFNULL(expr)` | direct | `ifnull ( [x] , 0 )` | |
| `NULLIFZERO(expr)` | direct | `nullif ( [x] , 0 )` | |

---

## Window functions

Source tables: `core-spec/expression_language.md:566-571` (ranking), `:577-581` (offset),
`:585` (window aggregations), plus the `OVER` syntax and frame clauses at `:548-560`.

Window functions are where the two models diverge most, so the three structural rows at the
end of this table carry as much weight as the named functions above them. ThoughtSpot has no
`OVER` clause: window behaviour is expressed by *which function* is used, with the partition
and order derived from the function's trailing arguments and from the query's own grouping.
Two consequences run through every row:

- **E5 — a raw aggregate cannot be nested inside a ThoughtSpot window function.** The
  argument must be a column reference or a `group_aggregate ( ... )`. `moving_sum ( sum ( [x] ) , ... )`
  is rejected; `moving_sum ( group_aggregate ( sum ( [x] ) , { [T::pk] } , query_filters ( ) ) , ... )`
  is the valid form. A converter that translates `SUM(x) OVER (...)` naively produces a
  formula that fails at import.
- **E6 — ThoughtSpot's `ORDER BY` column must be a physical column reference.** A formula
  column in the sort position fails to resolve. When the specification's `ORDER BY`
  expression is computed, the converter raises an issue rather than emitting a formula that
  will not compile.

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ROW_NUMBER() OVER (...)` | passthrough | `sql_int_aggregate_op ( "ROW_NUMBER() OVER (PARTITION BY {0} ORDER BY {1})" , [dim] , [ord] )` | **Variant: `sql_int_aggregate_op`.** ThoughtSpot's `rank` is competition rank, not a row number, so it is not a substitute. Wrap the result in `group_aggregate ( ... , query_groups ( ) + { [dim] } , query_filters ( ) )` so the partition column is guaranteed into the GROUP BY. |
| `RANK() OVER (...)` | direct | `rank ( sum ( [m] ) , 'desc' )` | Exact for the global, `ORDER BY`-only form the specification's own tool-mapping table shows (`:740`). ThoughtSpot's `rank` is always global and takes its order from the aggregate, so **an explicit `PARTITION BY` is not expressible** and falls back to `sql_int_aggregate_op ( "RANK() OVER (PARTITION BY {0} ORDER BY SUM({1}) DESC)" , ... )` (**E3**). |
| `DENSE_RANK() OVER (...)` | passthrough | `sql_int_aggregate_op ( "dense_rank() over (order by sum({0}) desc)" , [m] )` | **Variant: `sql_int_aggregate_op`.** ThoughtSpot's `rank` skips ranks after a tie; dense ranking has no native form. |
| `NTILE(n) OVER (...)` | passthrough | `sql_int_aggregate_op ( "NTILE(4) OVER (ORDER BY SUM({0}))" , [m] )` | **Variant: `sql_int_aggregate_op`.** `n` is a literal, baked into the template. |
| `PERCENT_RANK() OVER (...)` | direct | `1 - rank_percentile ( sum ( [m] ) , 'asc' ) / 100` | ThoughtSpot's `rank_percentile` is documented as `(1.0 - PERCENT_RANK() OVER (ORDER BY ...)) * 100`, so the inverse is exact. **Two adjustments are both required:** the scale (ThoughtSpot 0–100, specification 0–1) and the inversion. Dropping either produces a plausible-looking column that is wrong everywhere. |
| `CUME_DIST() OVER (...)` | passthrough | `sql_number_aggregate_op ( "CUME_DIST() OVER (ORDER BY SUM({0}))" , [m] )` | **Variant: `sql_number_aggregate_op`.** `rank_percentile` is *not* a substitute: `PERCENT_RANK` divides by *n − 1* and starts at 0, `CUME_DIST` divides by *n* and ends at 1. They agree on no row of a tie-free window except the last. |
| `LAG(expr, offset, default) OVER (...)` | direct | `moving_sum ( [m] , n , -n , [ord] )` | The verified single-row-back idiom: a frame of `n PRECEDING` to `n PRECEDING`. **The `default` argument has no equivalent** — ThoughtSpot yields null outside the frame — so a `LAG` with a non-null `default` raises an issue. Subject to **E5** and **E6**. |
| `LEAD(expr, offset, default) OVER (...)` | direct | `moving_sum ( [m] , -n , n , [ord] )` | Mirror of `LAG` — ThoughtSpot's start/end arguments use opposite sign conventions, so a forward offset is a negative start. Same `default` limitation. |
| `FIRST_VALUE(expr) OVER (...)` | direct | `first_value ( sum ( [m] ) , query_groups ( ) , { [T::date] } )` | Exact when the `ORDER BY` is a date column and the partition is the query grain — the semi-additive snapshot case this specification's users write it for. ThoughtSpot's `first_value` is a semi-additive function over a date axis, **not** a general window function, so any other `OVER` shape falls back to `sql_number_aggregate_op ( "FIRST_VALUE({0}) OVER (...)" , ... )` (**E3**). The `{ }` argument forces `>-` block-scalar YAML. |
| `LAST_VALUE(expr) OVER (...)` | direct | `last_value ( sum ( [m] ) , query_groups ( ) , { [T::date] } )` | Same conditions and same fallback as `FIRST_VALUE`. |
| `NTH_VALUE(expr, n) OVER (...)` | passthrough | `sql_number_aggregate_op ( "NTH_VALUE({0}, 2) OVER (ORDER BY {1})" , [m] , [ord] )` | **Variant: `sql_number_aggregate_op`.** ThoughtSpot's semi-additive functions reach only the first and last values of the axis. |
| `OVER (PARTITION BY ... ORDER BY ...)` clause | direct | structural rewrite — no `OVER` keyword | `PARTITION BY attrs` becomes the `group_aggregate` grouping argument `{ [T::a] , [T::b] }`; `ORDER BY` becomes the window function's trailing attribute arguments. An empty `OVER ()` is grouping `{ }`. **The reverse direction is where this gets lossy** — ThoughtSpot's window functions add the query's own dimensions to the partition dynamically, which the specification has no way to express (ask **A10**). |
| Frame clause — `ROWS BETWEEN ...` / `RANGE BETWEEN ...` | direct | `moving_*` start/end arguments, or `cumulative_*` | `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` → `cumulative_*`. Bounded `ROWS` frames → `moving_*` with `n PRECEDING` → positive `n`, `CURRENT ROW` → `0`, `n FOLLOWING` → negative `-n`. **`RANGE` frames fall back to a pass-through:** ThoughtSpot's frames are row-positional, not value-ranged — live-verified on gapped dates, `moving_*` counts surviving rows regardless of the calendar distance between them — so a `RANGE` frame over a gapped sort column would silently return different numbers (**E3**). |
| Window aggregation — `AGG(expr) OVER (...)` | direct | `cumulative_*` / `moving_*` / `group_*` by frame shape | The specification allows every aggregate as a window function (`:585`). ThoughtSpot's window family covers `SUM`, `AVG`, `MIN` and `MAX` (as `*_sum`, `*_average`, `*_max`, `*_min`); a windowed `COUNT`, `MEDIAN`, `STDDEV` or `VARIANCE` has a partitioned form via `group_count` / `group_stddev` / `group_variance` but no ordered/framed form, and falls back to `sql_number_aggregate_op`. Subject to **E5**. |

---

## Type conversion

Source: `core-spec/expression_language.md:608-620` (`CAST`), `:625` (`TRY_CAST`).

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CAST(expression AS target_type)` | direct | per-type — see the target-type table below | 6 of the 8 specified target types are `direct`; `BOOLEAN` and `TIMESTAMP`/`TIME` fall back to a pass-through (**E3**). |
| `TRY_CAST(expression AS target_type)` | direct | the same functions as `CAST` | ThoughtSpot's `to_integer` / `to_double` / `to_string` **already return NULL on failure**, which is exactly `TRY_CAST` semantics — so the two rows share a mapping and it is `CAST`, not `TRY_CAST`, that is the imprecise one. A strict `CAST` that must *error* rather than null is not expressible; the converter records that in the issue log when the source distinguishes them. |

### `CAST` target types *(not counted — arguments)*

| Target type | ThoughtSpot | Class |
|---|---|---|
| `VARCHAR` / `STRING` | `to_string ( [x] )` | direct |
| `INTEGER` / `INT` / `BIGINT` | `to_integer ( [x] )` | direct — ThoughtSpot has one integer conversion; a `BIGINT`-vs-`INTEGER` width distinction is not carried. |
| `DECIMAL` / `NUMERIC` | `to_double ( [x] )` | direct — **precision and scale are lost.** Fixed-point becomes floating-point, so a `DECIMAL(18,2)` currency column stops being exact. The converter raises an issue when precision was declared. |
| `FLOAT` / `DOUBLE` | `to_double ( [x] )` | direct |
| `BOOLEAN` | `sql_bool_op ( "CAST({0} AS BOOLEAN)" , [x] )` | passthrough — no native boolean conversion. |
| `DATE` | `to_date ( [s] , 'yyyy-MM-dd' )` from a string; `date ( [dt] )` from a datetime | direct — which of the two depends on the source type, so the converter needs the operand's `datatype`. |
| `TIMESTAMP` | `sql_date_time_op ( "CAST({0} AS TIMESTAMP)" , [x] )` | passthrough — `to_date` is date-only. |
| `TIME` | `sql_date_time_op ( "CAST({0} AS TIME)" , [x] )` | passthrough — ThoughtSpot has no TIME type. |

---

## Operators and constructs

Sources: `core-spec/expression_language.md:109-120` (supported constructs), `:131`
(`EXISTS_IN`), `:139-147` (precedence, including unary operators), `:219-225` (`DISTINCT`
modifier), `:401` (`||`), `:428-429` (`LIKE`/`ILIKE`), `:500-513` (`CASE`), `:534-537`
(boolean literals and operators), `:636-637` (null-safe comparison).

| Ossie | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `a + b` | direct | `[a] + [b]` | **Numeric only.** ThoughtSpot's `+` rejects string operands, so a `+` that concatenates on the source side must become `concat ( )`. The specification does not overload `+`, so this only bites when translating a dialect expression. |
| `a - b` | direct | `[a] - [b]` | |
| `a * b` | direct | `[a] * [b]` | |
| `a / b` | direct | `[a] / [b]` | Both yield NULL (or a warehouse error) on divide-by-zero. ThoughtSpot's `safe_divide` returns **0**, not NULL, so it is *not* a faithful substitute and is used only where the source itself guards the denominator. |
| `a % b` | direct | `mod ( [a] , [b] )` | ThoughtSpot has no `%` operator — the modulo is the function. |
| `-x` / `+x` (unary) | direct | `-[x]` | Unary minus is where the bare-date-literal trap originates: `'2024-05-01'` unquoted is parsed as `2024 − 5 − 1`. Date literals are always wrapped in `to_date ( )`. |
| `a = b` | direct | `[a] = [b]` | |
| `a <> b` | direct | `[a] <> [b]` | |
| `a != b` | direct | `[a] != [b]` | ThoughtSpot accepts both inequality spellings, so the two rows are independent and both `direct`. |
| `a < b` | direct | `[a] < [b]` | |
| `a > b` | direct | `[a] > [b]` | |
| `a <= b` | direct | `[a] <= [b]` | |
| `a >= b` | direct | `[a] >= [b]` | |
| `a AND b` | direct | `[a] and [b]` | Lower-case, infix. |
| `a OR b` | direct | `[a] or [b]` | Lower-case, infix. |
| `NOT expr` | direct | `not ( [x] )` | **Function form with parentheses**, not a prefix operator — `not [x]` does not parse. |
| `x BETWEEN a AND b` | direct | `[x] between [a] and [b]` | Inclusive on both sides. |
| `x IN (a, b, c)` | direct | `[x] in { 'a' , 'b' , 'c' }` | Literal lists only on both sides (`:113`) — no subqueries. The list **delimiter** is the one thing to confirm per build: the curly-brace form is what the formula parser accepts in the paths verified most recently, and it forces `>-` block-scalar YAML. See *Rows pending live confirmation*. |
| `x NOT IN (a, b, c)` | direct | `not ( [x] in { 'a' , 'b' , 'c' } )` | Emitted as a negated `in` rather than a `not in` keyword — the bare keyword form is not reliably accepted. |
| `str LIKE pattern` | direct | `starts_with` / `ends_with` / `contains` by pattern shape | `'foo%'` → `starts_with ( [s] , 'foo' )`; `'%foo'` → `ends_with ( [s] , 'foo' )`; `'%foo%'` → `contains ( [s] , 'foo' )`. These three shapes are the overwhelming majority of `LIKE` use. Interior wildcards and any `_` single-character wildcard have no native form and fall back to `sql_bool_op ( "{0} LIKE {1}" , [s] , [pattern] )` (**E3**). |
| `str ILIKE pattern` | passthrough | `sql_bool_op ( "{0} ILIKE {1}" , [s] , [pattern] )` | **Variant: `sql_bool_op`.** Case-insensitive matching has no native form, and the usual workaround — fold both sides with `lower` — is itself a pass-through, so there is nothing to compose from. |
| `expr IS NULL` | direct | `isnull ( [x] )` | |
| `expr IS NOT NULL` | direct | `isnotnull ( [x] )` | Native, so not composed as `not ( isnull ( ) )`. |
| `a IS DISTINCT FROM b` | direct | `if ( isnull ( [a] ) and isnull ( [b] ) ) then false else if ( isnull ( [a] ) or isnull ( [b] ) ) then true else [a] != [b]` | No native null-safe comparison, but the three-case truth table is exactly expressible. The nesting order matters: both-null must be tested before either-null. |
| `a IS NOT DISTINCT FROM b` | direct | `if ( isnull ( [a] ) and isnull ( [b] ) ) then true else if ( isnull ( [a] ) or isnull ( [b] ) ) then false else [a] = [b]` | The negation of the row above, written directly rather than wrapped in `not ( )` — one fewer nesting level for the parser. |
| `CASE WHEN c1 THEN r1 ... ELSE d END` (searched) | direct | `if ( c1 ) then r1 else if ( c2 ) then r2 else d` | No native `CASE`; the chain is `else if`, two words. **The final `else` is mandatory and must be type-matched** — `else 0` for a measure, `else ''` for an attribute. Omitting it raises `Unknown data type`, and a `CASE` with no `ELSE` (legal in the specification, yielding NULL) therefore needs one synthesised. |
| `CASE expr WHEN v1 THEN r1 ... END` (simple) | direct | `if ( [expr] = v1 ) then r1 else if ( [expr] = v2 ) then r2 else d` | Expanded to the searched form with an explicit equality per branch. `expr` is repeated per branch, so a converter should hoist an expensive `expr` into its own formula first. |
| `str1 \|\| str2` | direct | `concat ( [a] , [b] )` | ThoughtSpot has no concatenation operator at all — `+` is numeric-only — so `\|\|` and `CONCAT` share one target. |
| Parentheses — expression grouping | direct | `( ... )` | Precedence is the standard SQL ordering on the Ossie side (`:139-147`). The converter emits explicit parentheses around every rewritten sub-expression rather than relying on the two languages agreeing about precedence — cheap, and it removes a whole class of silent arithmetic errors. |
| `TRUE` / `FALSE` (boolean literals) | direct | `true` / `false` | A bare BOOL *column* reference used as a condition still needs its parentheses: `if ( [T::flag] ) then ...` parses, `if [T::flag] then ...` does not. |
| `DISTINCT` aggregate modifier | passthrough | `sql_number_aggregate_op ( "SUM(DISTINCT {0})" , [x] )` | **Variant: `sql_number_aggregate_op`.** The specification allows `DISTINCT` on `SUM` as well as `COUNT` (`:219-225`). ThoughtSpot has exactly one distinct-aware aggregate — `unique count` — which is `COUNT(DISTINCT)` and has its own row. Every other `DISTINCT` aggregate is a pass-through. |
| Column / metric reference — `field`, `dataset.field` | direct | `[TABLE::Column]`, or `[Formula Name]` for a metric | Always rewritten from resolved metadata, never passed through textually. The rewrite, the case-sensitivity rules and the display-name-versus-identifier problem are the construct-mapping document's **ID1**–**ID4**. |
| `EXISTS_IN()` | **unmappable** | — issue; construct preserved in `custom_extensions` | Named at `:131` as the sanctioned way to filter on a subquery, but **defined nowhere in the specification** — no signature, no argument order, no semantics, and absent from every function table. Even given a signature, ThoughtSpot's nearest capability is a `sql_bool_op` subquery template that requires a fully-qualified warehouse table name, which is not derivable from an Ossie expression. See ask **A9**. |

---

## Passthrough caveat (applies to every `passthrough` row)

The sql_*_op family embeds raw warehouse SQL: correctness depends on the connection's
dialect, and the expression is opaque to ThoughtSpot's query planner (no automatic
aggregation-grain handling). The converter emits these with a converter issue of
severity=warning so users review each one.

Three additional rules make the caveat operational:

- **E7 — the variant fixes the column's type and its measure/attribute role.** The scalar
  variants produce attributes, the `*_aggregate_op` variants produce measures. Emitting
  `sql_int_op` where `sql_int_aggregate_op` was needed produces a column that imports
  cleanly and then aggregates wrongly, which is worse than a rejected import.
- **E8 — a pass-through carrying `PARTITION BY` is wrapped in `group_aggregate`.** The
  wrapper (`query_groups ( ) + { [partition_col] } , query_filters ( )`) guarantees the
  partition column reaches the GROUP BY even when the user's search omits it, isolates the
  aggregation context, and keeps the formula valid under drill-down. An unwrapped
  partitioned pass-through is valid only in searches that happen to include the partition
  column.
- **E9 — no pass-through may carry a runtime parameter.** A `sql_*_op` template whose
  arguments include a ThoughtSpot parameter cannot be resolved to static SQL, so the
  expression is not portable in either direction; the converter emits it with a
  `THOUGHTSPOT` dialect entry only and raises an issue. This is the expression-level
  counterpart of the construct-mapping document's parameter rule.

---

## Reverse direction (ThoughtSpot → Ossie)

The 146 rows above are the specification's inventory, so they are the count that matters.
This section is the other half of a bidirectional converter: the ThoughtSpot functions with
**no counterpart in the specification**. Per the two-bucket rule each one either (a) is
expressible by composing constructs the specification does have, or (b) is exported to
`custom_extensions` with a converter issue. Nothing is dropped silently, and nothing is
declared untranslatable without checking the composition first.

- **E10 — prefer composition over the stash.** Most of ThoughtSpot's apparently-proprietary
  functions are sugar. `sum_if` is `SUM(CASE WHEN ...)`, which the specification blesses
  explicitly (`:227-229`); `safe_divide` is `COALESCE(a / NULLIF(b, 0), 0)`; `group_sum`
  over a fixed grain is `SUM(x) OVER (PARTITION BY attr)`. The stash is for what genuinely
  has no expression, which turns out to be a short list dominated by *runtime* concepts.

### Conditional aggregates and arithmetic helpers

| ThoughtSpot | Ossie expression | Disposition |
|---|---|---|
| `sum_if ( cond , [x] )` | `SUM(CASE WHEN cond THEN x END)` | via Ossie composition |
| `count_if ( cond , [x] )` | `COUNT(CASE WHEN cond THEN x END)` | via Ossie composition |
| `unique_count_if ( cond , [x] )` | `COUNT(DISTINCT CASE WHEN cond THEN x END)` | via Ossie composition |
| `average_if` / `min_if` / `max_if` / `stddev_if` / `variance_if` | `AVG` / `MIN` / `MAX` / `STDDEV` / `VARIANCE` `(CASE WHEN cond THEN x END)` | via Ossie composition |
| `unique count ( [x] )` | `COUNT(DISTINCT x)` | via Ossie composition |
| `safe_divide ( [a] , [b] )` | `COALESCE(a / NULLIF(b, 0), 0)` | via Ossie composition — the zero-not-null result is preserved by the explicit `COALESCE`. |
| `pow` / `log2` / `strlen` / `strpos` / `substr` / `left` / `right` | `POWER` / `LOG(2, x)` / `LENGTH` / `POSITION(sub IN s)` / `SUBSTRING(s, start + 1, len)` | via Ossie composition — note `substr`'s 0-based start needs `+ 1` going this way. |
| `sin` / `cos` / `tan` / `asin` / `acos` / `atan` | `SIN(RADIANS(x))` … / `DEGREES(ASIN(x))` … | via Ossie composition — the degree/radian conversion reverses. |
| `to_integer` / `to_double` / `to_string` / `to_date ( s , fmt )` | `CAST(x AS INTEGER)` / `CAST(x AS DOUBLE)` / `CAST(x AS VARCHAR)` / `TO_DATE(s, format)` | via Ossie composition — the format model is translated back through the token table; `TO_DATE(s, format)` is EXPERIMENTAL on the Ossie side (`:353`). |
| `if ( c ) then a else b` | `CASE WHEN c THEN a ELSE b END` or `IF(c, a, b)` | via Ossie composition |

### Window, LOD and semi-additive functions

| ThoughtSpot | Ossie expression | Disposition |
|---|---|---|
| `rank ( agg ( [m] ) , 'desc' )` | `RANK() OVER (ORDER BY AGG(m) DESC)` | via Ossie composition |
| `rank_percentile ( agg ( [m] ) , 'asc' )` | `(1.0 - PERCENT_RANK() OVER (ORDER BY AGG(m) ASC)) * 100` | via Ossie composition — the scale and inversion both reverse. |
| `moving_sum` / `_average` / `_max` / `_min` `( [m] , s , e , [attr] )` | `AGG(m) OVER (ORDER BY attr ROWS BETWEEN s PRECEDING AND e FOLLOWING)` | via Ossie composition — sign conventions convert per the frame-clause row above. ANSI `ROWS` frames are row-positional, which matches ThoughtSpot's live-verified behaviour exactly, so this direction is clean. |
| `cumulative_sum` / `_average` / `_max` / `_min` `( [m] , [attr] )` | `AGG(m) OVER (ORDER BY attr ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` | via Ossie composition **for the frame** — but see the dynamic-partition row below. |
| `group_aggregate ( agg ( [m] ) , { [a] , [b] } , query_filters ( ) )` and the `group_*` shorthands | `AGG(m) OVER (PARTITION BY a, b)` | via Ossie composition — fixed-grain grouping is an ordinary `PARTITION BY`. `{ }` is `OVER ()`; `query_groups()` needs no window at all and becomes a plain `AGG(m)`. |
| `group_aggregate ( ... , query_groups ( ) - { [a] } , ... )`, and the dynamic partition every `cumulative_*` / `moving_*` carries implicitly | — | **`custom_extensions` + issue.** "All the query's dimensions except *a*" has no expression in the specification. Snowflake's `PARTITION BY EXCLUDING` exists precisely for this, and without an equivalent the same model returns different numbers depending on which dimensions a user adds. This is the largest single fidelity gap in this direction — see ask **A10**. |
| `group_aggregate` with a non-`query_filters()` filter argument — `{ }`, `{ [c] = 'v' }`, `query_filters ( ) - { [c] }` | — | **`custom_extensions` + issue.** Filter scoping inside an expression, which the specification excludes from expressions and redirects to a filter property it does not define (`:130`) — the construct-mapping document's ask **A3**. |
| `last_value` / `first_value` / `last_value_in_period` / `first_value_in_period` | `LAST_VALUE(m) OVER (PARTITION BY ... ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)` gets the snapshot; the re-aggregation at query grain does not | **`custom_extensions` + issue.** The window expression is only half of it: semi-additivity is a declaration about *how the measure may be rolled up*, not an expression. Snowflake carries it as `non_additive_dimensions` and Databricks has its own form; the specification has neither. See ask **A12**. |
| `sql_string_op` / `sql_int_op` / `sql_double_op` / `sql_bool_op` / `sql_date_op` / `sql_date_time_op` and the four `*_aggregate_op` variants | a `dialects[]` entry for the connection's dialect, with `{0}`, `{1}` … substituted for the resolved column references | via Ossie composition — **the dialect mechanism is the right home for these** (`:648-659`). A pass-through *is* dialect-specific raw SQL, which is what a non-Ossie dialect entry is for. Two caveats: no `ANSI_SQL` entry is emitted alongside, because the template's portability is exactly what is unknown; and the connection's dialect is not always derivable from TML, in which case the converter raises an issue rather than guessing a dialect label. |

### Runtime, display and calendar concepts

| ThoughtSpot | Ossie expression | Disposition |
|---|---|---|
| Runtime parameter reference — `[Parameter Name]` | — | **`custom_extensions` + issue.** Resolved per-query from user input; the definitions are stashed at model level. The construct-mapping document owns this rule; it is repeated here because the *expression* is the thing that stops being portable. |
| `ts_username`, `ts_groups`, `ts_groups_int`, `ts_org`, `ts_email_domain`, `ts_var ( ... )` | — | **`custom_extensions` + issue.** Signed-in-user identity resolved at query time. An interchange document that carried them would be describing an access-control decision, not semantics — the same reasoning as the construct-mapping document's **NM2**. |
| `concat ( "{caption}" , "text" , "{/caption}" , [url] )` | — | **`custom_extensions` + issue.** Hyperlink display markup, not computation. `concat` itself maps; the markup tokens inside the string literals do not, and a consumer that rendered them literally would show the tags to users. |
| Fiscal-calendar variants — `year ( [d] , fiscal )`, `quarter_number ( [d] , fiscal )`, `diff_months ( [e] , [s] , fiscal )` and the rest of the `fiscal` family | — | **`custom_extensions` + issue.** The specification has no fiscal-calendar concept, and the fiscal year's start month is a *model-level* fact that no per-expression rewrite can recover. Emitting the calendar-year function instead would be silently wrong for every organisation whose year does not start in January. See ask **A11**. |
| `month ( [d] )`, `year_name ( [d] )`, `day_of_week ( [d] )` (name-returning) | `TO_CHAR(d, 'MONTH')`, `TO_CHAR(d, 'YYYY')`, `TO_CHAR(d, 'DAY')` | via Ossie composition — but `TO_CHAR` is EXPERIMENTAL (`:356`) and the name tokens are locale-dependent by the specification's own admission (`:385-387`), so an issue records the locale exposure. |
| `month_number_of_quarter ( [d] )` | `MOD(MONTH(d) - 1, 3) + 1` | via Ossie composition |
| `day_number_of_quarter ( [d] )` | `DATEDIFF(day, DATE_TRUNC('quarter', d), d) + 1` | via Ossie composition |
| `week_number_of_month` / `week_number_of_quarter` | `DATEDIFF(week, DATE_TRUNC('month'/'quarter', d), d) + 1` | via Ossie composition — correct only if both sides agree on the week start day, which the specification fixes as Monday (`:300`) while ThoughtSpot's is an instance setting. Issue raised when they cannot be shown to agree. |
| `is_weekend ( [d] )` | `DATE_PART('dayofweek', d) IN (...)` | via Ossie composition — the member list depends on the `DAYOFWEEK` base, which the specification does not fix (see ask **A11**), so the converter emits the list for the connection's engine and records the base in the issue. |
| `start_of_hour` / `start_of_min` / `date` / `time` | `DATE_TRUNC('hour', d)` / `DATE_TRUNC('minute', d)` / `DATE_TRUNC('day', d)` / `CAST(d AS TIME)` | via Ossie composition |
| `greatest` / `least` | `GREATEST` / `LEAST` | via Ossie composition — **never `MAX`/`MIN`**, which would turn a row-wise attribute into an aggregate measure. |

- **E11 — a stashed expression still emits a `THOUGHTSPOT` dialect entry.** For every row
  above whose disposition is `custom_extensions + issue`, the expression is not simply
  discarded: the verbatim ThoughtSpot formula goes into a `THOUGHTSPOT` dialect entry so the
  round trip is lossless, and no `ANSI_SQL` sibling is emitted because there is none. This
  depends entirely on the construct-mapping document's blocking ask **A1** — until
  `THOUGHTSPOT` is in the `Dialect` enum and in `SKIP_SQL_VALIDATION`, such a document fails
  schema validation, so **every row in this table is blocked on A1**, not just the
  parameter row.
- **E12 — an issue names the function, the object and the reason.** Not "untranslatable
  expression". The reason strings above are the intended text: a reader should be able to
  tell from the issue alone whether the loss is a specification gap (raise it upstream), a
  ThoughtSpot limitation (accept it), or a missing piece of model metadata (supply it and
  re-run).

---

## Rows pending live confirmation

Four `direct` classifications rest on documentation rather than on a recent live import.
They are marked in their Notes and collected here so a reviewer can see the whole set at
once, and so the Phase-3 implementation has an explicit verification list. In each case a
documented fallback exists, so a wrong call costs fidelity, not correctness.

| Row | Claim | Fallback if it fails |
|---|---|---|
| `REPLACE(str, from, to)` | `replace ( )` is a native function | `sql_string_op ( "REPLACE({0},{1},{2})" , ... )` |
| `STARTSWITH(str, prefix)` | `starts_with ( )` is native | `strpos ( [s] , [prefix] ) = 1` |
| `ENDSWITH(str, suffix)` | `ends_with ( )` is native | `substr ( [s] , strlen ( [s] ) - strlen ( [suffix] ) , strlen ( [suffix] ) ) = [suffix]` |
| `x IN (a, b, c)` | the accepted literal-list delimiter is `{ }` | the `( )` form, per the build's parser |

`LTRIM` / `RTRIM` are the mirror case — classified `passthrough` on the conservative
reading that ThoughtSpot's `trim` is two-sided only. If a one-sided form turns out to
exist, those two rows move to `direct` and the pass-through count drops to 29.

---

## Open questions and upstream asks

Continuing the construct-mapping document's sequence, which ends at **A8**.

| # | Ask | Why |
|---|---|---|
| **A9** | Define `EXISTS_IN()`, or remove the reference to it. | It is named at `core-spec/expression_language.md:131` as the sanctioned alternative to a subquery, but has no signature, no semantics and no entry in any function table — it is the one construct in the specification that cannot be mapped, and only because it cannot be read. Relatedly: `:219` says "SUM / COUNT aggregation functions support `DISTINCT`" while the syntax table gives `COUNT(DISTINCT expr)` its own row (`:160`) and `SUM(DISTINCT …)` appears only in an example (`:224`). Is `DISTINCT` a modifier available on every aggregate, or only on those two? The answer changes how many rows a converter must generate. |
| **A10** | A way to express a *dynamic* window partition — the equivalent of Snowflake's `PARTITION BY EXCLUDING`. | ThoughtSpot's `cumulative_*`, `moving_*` and `group_aggregate ( … , query_groups ( ) - { attr } , … )` all add the query's own dimensions to the partition at query time. A static `PARTITION BY` list cannot express it, so today the construct is stashed and invisible to every other consumer — meaning the same model returns different numbers in two tools as soon as a user adds a dimension. Snowflake solved this with an explicit `EXCLUDING` clause; is a core spelling in scope for 0.2.x? |
| **A11** | Fix the date-part vocabulary's edges: (a) the `DAYOFWEEK` base, (b) the asymmetry between the function list and the part list, (c) a fiscal-calendar declaration. | (a) `:284-285` lists `DAYOFWEEK` as a valid part but never says whether 1 is Monday or Sunday, and the engines in the specification's own support table disagree — so a portable expression using it is not actually portable. (b) `DAYOFYEAR` has a first-class function (`:263`) while `DAYOFWEEK` and `WEEK` exist only as parts; ThoughtSpot has functions for all three, so the gap shows up immediately as an inconsistency in the mapping. (c) Fiscal calendars are a model-level fact with no expression-level fix; ThoughtSpot has a `fiscal` argument on most date functions and there is nowhere to put it. |
| **A12** | A declaration for non-additive / semi-additive measures, and a home for the `Decomposability` classification. | These are the two pieces of aggregation *metadata* the expression language surfaces but cannot carry. `:236-241` already classifies every aggregate as distributive / algebraic / holistic / sketch-based for multi-stage aggregation, but the classification lives only in this prose table — a consumer cannot read it off a model. And a snapshot measure (inventory balance, headcount) needs a "do not sum across time" declaration: ThoughtSpot has `last_value`/`first_value`, Snowflake has `non_additive_dimensions`, Databricks has its own. All three are stashed today, and the failure mode is the worst kind — a silently summed balance sheet, with no error anywhere. |

---

## Worked shape

One metric per classification, showing the whole path from an Ossie expression to the
ThoughtSpot formula the converter emits.

Ossie:

```yaml
metrics:
  - name: revenue
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: SUM(orders.amount)
  - name: distinct_customers
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: COUNT(DISTINCT orders.customer_id)
  - name: order_month
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: DATE_TRUNC('month', orders.order_date)
  - name: days_to_ship
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: DATEDIFF(day, orders.order_date, orders.shipped_date)
  - name: margin_band
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: >-
            CASE WHEN orders.margin > 0.3 THEN 'high'
                 WHEN orders.margin > 0.1 THEN 'medium' END
  - name: p95_response
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY orders.response_time)
```

ThoughtSpot (Model `formulas[]`; each needs a `columns[]` entry referencing it by
`formula_id`, per the construct-mapping document's **R3**):

```yaml
formulas:
- id: formula_Revenue
  name: Revenue
  expr: "sum ( [ORDERS::Amount] )"

- id: formula_Distinct Customers
  name: Distinct Customers
  expr: "unique count ( [ORDERS::Customer Id] )"          # a space, not an underscore

- id: formula_Order Month
  name: Order Month
  expr: "start_of_month ( [ORDERS::Order Date] )"          # no date_trunc in ThoughtSpot

- id: formula_Days To Ship
  name: Days To Ship
  expr: "diff_days ( [ORDERS::Shipped Date] , [ORDERS::Order Date] )"   # end first

- id: formula_Margin Band
  name: Margin Band
  expr: "if ( [ORDERS::Margin] > 0.3 ) then 'high' else if ( [ORDERS::Margin] > 0.1 ) then 'medium' else ''"

- id: formula_P95 Response
  name: P95 Response
  expr: "sql_number_aggregate_op ( \"PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY {0})\" , [ORDERS::Response Time] )"
```

Five of the six differences visible here are the ones a naive translator gets wrong: the
distinct-count spelling, the absent `date_trunc`, the reversed `diff_days` arguments, the
`else ''` synthesised for a `CASE` that had no `ELSE`, and the pass-through's aggregate
variant. Only `sum` is a plain rename.
