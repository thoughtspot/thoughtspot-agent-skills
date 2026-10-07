# ThoughtSpot formula semantics: live probe record, 2026-10-06

**Cluster:** se-thoughtspot (`se-thoughtspot-cloud.thoughtspot.cloud`), connection `APJ_TAB` (Snowflake),
table `AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.SALARY_RATES` (guid `503a5cdf-b11d-4834-b313-97ad3518dc4b`).

**Method:**
1. Import a scratch Model (`ZZ_*_PROBE_DELETE_ME`, `--create-new`) whose formulas apply the construct under test to constant dates or numbers, or to table columns.
2. Read the compiled SQL with `ts agentql generate-sql`.
3. Read the values with `ts agentql fetch-data`.
4. Delete the Model with `ts metadata delete`, and confirm it is gone with `ts metadata search`.

Parser-only checks used `ts tml import --policy VALIDATE_ONLY`, which creates nothing.

**AgentQL traps hit while probing:**
- Select an aggregate formula as `AGG("name")`.
- Probe one aggregate formula per query. Selecting a plain `SUM(col)` alongside several formula measures made AgentQL put the formulas into GROUP BY: `[ca_3] is not a valid group by expression`.

Every scratch Model was deleted and confirmed absent.

This file is the evidence that the maps and mapping docs cite as "live-verified 2026-10-06".

---

## 1. `round ( x , n )`: `n` is an increment (BL-331)

Compiled SQL: `n * round(x / NULLIF(n, 0))`.

| Formula on 1234.5678 | Result |
|---|---|
| `round ( x )` | 1235 |
| `round ( x , 0 )` | NULL |
| `round ( x , 1 )` | 1235 |
| `round ( x , 2 )` | 1234 |
| `round ( x , 0.01 )` | 1234.57 |
| `round ( x , 10 )` | 1230 |
| `round ( x , 0.5 )` | 1234.5 |
| `round ( x , -2 )` | 1234 |

The result type is INT64 for an integer increment and DOUBLE for a fractional one.

Emitted forms after the fix:
- **Row level, ±1234.5678:**
  - `round ( x , 0.01 )` → ±1234.57
  - `round ( x , 100 )` → 1200
  - `sql_double_op ( "TRUNC({0}, 2)" , x )` → ±1234.56
  - `TRUNC(…, -1)` → 1230
  - Sign-split floor/ceil at 0.1 → ±1234.5
- **Over aggregates:**
  - `round ( sum ( x ) / 7 , 0.01 )` → 34285.71
  - Sign-split truncation of `sum ( x ) / -7` → -34285.7

## 2. Weekday, week and calendar (BL-334)

- **`day_number_of_week ( d )`** compiles to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)`, so 1 = Monday … 7 = Sunday, fixed. Observed values: 2026-10-04 (Sun) = 7, 2026-10-05 (Mon) = 1, 2026-10-10 (Sat) = 6, 2020-01-01 (Wed) = 3.
- **`start_of_week ( d )`** compiles to `DATE_TRUNC(week, d)`, and returned Monday 2026-09-28 for 2026-10-04.
- **`week_number_of_year ( 2026-01-04 )`** = 1.
- **Weekday-number forms**, all 7 days 2026-10-04 … 2026-10-10:

| Form | Sun | Mon | Tue | Wed | Thu | Fri | Sat |
|---|--:|--:|--:|--:|--:|--:|--:|
| `mod ( day_number_of_week ( d ) , 7 )` | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
| `( mod ( day_number_of_week ( d ) , 7 ) + 1 )` | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| `( day_number_of_week ( d ) - 1 )` | 6 | 0 | 1 | 2 | 3 | 4 | 5 |

## 3. Date differences (BL-336)

- `diff_months ( end , start )` = `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)`, i.e. month boundaries crossed:

| Start → end | Result |
|---|--:|
| Jan 31 → Feb 1 | 1 |
| Jan 31 → Feb 28 | 1 |
| Jan 20 → Mar 15 | 2 |
| Feb 1 → Jan 31 (reversed) | -1 |

- `diff_years` = `EXTRACT(YEAR end) - EXTRACT(YEAR start)`: Dec 31 → Jan 1 = 1, and 2025-07-01 → 2026-06-30 = 1.
- **Argument order:** `diff_days ( 2026-10-10 , 2026-10-04 )` = 6 and `diff_months ( 2026-12-01 , 2026-10-04 )` = 2, so the later date goes first.

## 4. String comparison is case-insensitive (BL-333)

- `contains ( [DEPARTMENT] , 'eng' )` compiles to `LOWER(col) LIKE '%eng%' ESCAPE '!'`.
- `strpos` compiles to `POSITION('eng' IN LOWER(col))`.
- Plain `=` compiles to `LOWER(col) = 'engineering'`, which matched 'Engineering'.
- String literals are lowercased at compile time: `contains ( 'Hello World' , 'WORLD' )` is true.
- **Probed 2026-10-07** (one more scratch Model, deleted and confirmed): `!=` → `LOWER(col) <> …`, `in { }` → `LOWER(col) IN (…)`, `strpos(…) = 1` → `POSITION(… IN LOWER(col)) = 1`, and `<` → `LOWER(col) < …`, all case-insensitive. Ordering changes as well: `'HR' < 'f'` is FALSE once both sides are lowercased.
- **Still not probed:** string join keys, and a column (rather than a literal) as the needle.

## 5. Parser acceptance (VALIDATE_ONLY)

**Aggregate pass-through family (BL-335), each over `MAX({0})`:**

| Name | Parser |
|---|---|
| `sql_double_aggregate_op`, `sql_int_aggregate_op`, `sql_string_aggregate_op`, `sql_date_aggregate_op`, `sql_date_time_aggregate_op`, `sql_bool_aggregate_op` | accepted |
| `sql_number_aggregate_op`, `sql_number_op` | rejected ("Formula addition failed") |

**References in TML `expr`:**

| Reference | Parser |
|---|---|
| `[formula_Total_Days] * 2` | accepted |
| `[Total_Days] * 2` (display name) | rejected |
| `Total_Days * 2` (bare) | rejected |
| `day_number_of_week ( [EFFECTIVE_DATE] )` | accepted |
| `day_number_of_week ( [SALARY_RATES::EFFECTIVE_DATE] )` | accepted |
| `day_number_of_week ( EFFECTIVE_DATE )` (bare) | rejected |

Bare names in the interactive formula editor are a separate parser. Their use there rests on ThoughtSpot domain guidance and is not probed.

## 6. Excel NETWORKDAYS family: per-weekday counting form

**Definitions:**
- n = `( diff_days ( e , s ) + 1 )`
- w = `day_number_of_week ( s )`
- count of weekday k (1 = Mon … 7 = Sun) = `( floor ( n / 7 ) + if ( mod ( k + 7 - w , 7 ) < mod ( n , 7 ) ) then 1 else 0 )`
- workdays = n − the sum of the counts over the non-working weekdays

**Run 1: no holidays.** 7 ranges against an independent Python implementation of Excel's semantics, 35 values, 0 mismatches:
- 2026-10-04 → 10-10
- 10-05 → 10-05
- 10-01 → 10-31
- 10-10 → 10-11
- 09-27 → 12-25
- 10-11 → 10-11
- 10-06 → 10-19

Five quantities were checked per range:
- `B2 - A2`
- `(B2 - A2) + 1`
- `NETWORKDAYS`
- `NETWORKDAYS.INTL` code 11 (Sunday off)
- `NETWORKDAYS.INTL` string `"1000001"` (Monday and Sunday off)

**Run 2: inline holiday array** `{2026-12-25 (Fri), 2026-12-26 (Sat)}` with weekend code 1. Each holiday subtracts `if ( h >= s and h <= e and day_number_of_week ( h ) <= 5 ) then 1 else 0`. 6 ranges, 0 mismatches:
- 2026-12-21 → 12-31 = 8
- 12-26 → 12-27 = 0
- 12-25 → 12-25 = 0
- 12-01 → 12-24 = 18
- 2026-11-15 → 2027-01-10 = 39
- 2026-12-26 → 2027-01-04 = 6

The `<= 5` test fits weekend code 1 only. Other codes need "h's weekday is not a weekend day". Duplicate holidays were not probed. `WORKDAY` / `WORKDAY.INTL` with holidays was not probed and does not follow this form: the end date shifts rather than a count being reduced.

## 7. Division, NULL and concat: `safe_divide`, `nullif`, `concat`

Probed 2026-10-06 while reviewing a 60-formula Excel batch (BL-339). The division rows come from
that review's scratch-Model probe (`ts agentql generate-sql` / `fetch-data`; the Model was deleted).
Every parser row below was re-run for this record with `ts tml import --policy VALIDATE_ONLY`
against a one-formula Model over `SALARY_RATES`, which creates nothing.

**Division.**

| Formula | Compiled SQL / result |
|---|---|
| `safe_divide ( a , b )` | `CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END` — a zero divisor gives **0**; a NULL divisor or NULL numerator gives **NULL** |
| `a / b` | a zero divisor gives **NULL** (ThoughtSpot guards the divisor); the query does not fail |

**`nullif` is not a ThoughtSpot formula function.**

| Formula | Parser |
|---|---|
| `nullif ( [SALARY_RATES::BASE_RATE] , 0 )` | rejected: *Search did not find "nullif (" in your data or metadata* |
| `null_if ( [SALARY_RATES::BASE_RATE] , 0 )` | rejected: *Search did not find "null_if ("* |
| `nullif ( 0 , 0 )` (the Excel map's former NULL-literal idiom) | rejected |
| `if ( [SALARY_RATES::BASE_RATE] = 0 ) then null else [SALARY_RATES::BASE_RATE]` | accepted |

The formula reference listed `nullif ( [a] , [b] )` in its Conditional Functions table until
this probe, and the Excel, Sheets and Omni maps and the `ts-object-formula-translate` skill
used it; a 60-formula batch composed from them failed import 36 times on it (BL-339).
Replacements: `safe_divide ( a , b )` (0 on zero), plain `a / b` (NULL on zero), or
`if ( b = 0 ) then null else a / b`.

**`concat` and `to_string`.**

| Formula | Parser |
|---|---|
| `concat ( 'a' , 'b' , 'c' , 'd' )` | accepted — `concat` takes 2 or more arguments |
| `concat ( [SALARY_RATES::DEPARTMENT] , ' ' , to_string ( [SALARY_RATES::BASE_RATE] ) )` | accepted |
| `concat ( 'a' , [SALARY_RATES::BASE_RATE] )` | rejected: *Function concat expects 2nd argument to be Text* |
| `concat ( to_string ( [SALARY_RATES::DEPARTMENT] ) , 'x' )` | rejected: *Function to_string expects 1st argument to be Boolean or Date or DateTime or Numeric or Time* |

So every `concat` argument must be Text, and `to_string` must wrap **only** the non-text ones.

**`isnotnull` is not a ThoughtSpot formula function either.** `isnotnull ( [SALARY_RATES::DEPARTMENT] )`
and `isnotnull ( [SALARY_RATES::BASE_RATE] * 2 )` are rejected (*Search did not find "isnotnull ("*);
`not ( isnull ( to_double ( [SALARY_RATES::DEPARTMENT] ) ) )` is accepted. The formula reference listed
`isnotnull` as native; the repo's translators already emitted `not ( isnull ( … ) )`, so only
documents were wrong (BL-339).

**`null` as a branch value.** Accepted in either position and in a chain:
`if ( c ) then [x] else null`, `if ( c ) then null else [x]`, `if ( c ) then 'a' else null`,
`if ( c1 ) then 'a' else if ( c2 ) then 'b' else null`. By contrast
`if ( c ) then [SALARY_RATES::BASE_RATE] else ''` is rejected (*Expecting a Numeric token*):
the branches must share a type.

**`null_if_zero` is not a ThoughtSpot function** (BL-344). `null_if_zero ( [SALARY_RATES::BASE_RATE] )`
is rejected (*Search did not find "null_if_zero ("*), alone and as a divisor. `sv_sql` and `mv_sql`
emitted it for a standalone SQL `NULLIF(x, 0)`; they now emit
`( if ( x = 0 ) then null else x )` — the parenthesised `if` is accepted inside arithmetic
(`1 + ( if … )`) and as a function argument (`isnull ( if … )`).

**Booleans in arithmetic.** `true + 1` and `( [SALARY_RATES::BASE_RATE] > 0 ) + 1` are rejected
(*Search did not find "+ 1"*); `( if ( c ) then 1 else 0 ) + 1` and the sum of two such terms are
accepted. Excel's TRUE-is-1 coercion has to be written out. A number is not a condition either:
`if ( [x] != 0 )` is the form for Excel's `IF(x, …)`.

**Blank tests.** `[SALARY_RATES::BASE_RATE] = ''` (a number against an empty string) is rejected
(*Expecting a List token*); `isnull ( [n] )` is the numeric blank test, and
`isnull ( [s] ) or [s] = ''` the text one (accepted).

**`mod` takes the dividend's sign** (scratch-Model execute, compiled SQL `MOD(…)`, deleted and
confirmed absent): `mod ( -3 , 2 )` = −1 and `mod ( 3 , -2 )` = 1, as Snowflake `MOD`. Excel `MOD`
takes the divisor's sign (Excel's MOD of −3 by 2 is 1). So Excel `MOD(a, b)` is `a - b * floor ( a / b )`
in ThoughtSpot, and ThoughtSpot `mod ( a , b )` is `a-b*TRUNC(a/b)` in Excel.

**`diff_time ( end , start )` is in seconds, end first** (scratch-Model execute, compiled to
`TIMESTAMPDIFF(second, start, end)`, deleted and confirmed absent):
`diff_time ( add_days ( d , 1 ) , d )` = 86400, on DATE columns too. So an Excel DATETIME
difference (a day count with a time fraction) is `diff_time ( t , u ) / 86400`; `diff_days` would
drop the hours.

**`diff_*` on TIMESTAMPs, by value** (added after the #572 review; formula fidelity M0,
se-thoughtspot + Snowflake `APJ_TAB`, 2026-10-06, warehouse session `TIMEZONE = UTC`, scratch
objects deleted and confirmed absent; evidence in
`tools/formula-fidelity/runs/2026-10-06-snowflake-m0-timestamp-probe.json`, the run made with
`DATEDIFF(hour)` still native, so its `sf-ts-005` row carries the wrong values and the compiled SQL). Ten fixture rows each of
TIMESTAMP_NTZ `T1 → T2` and TIMESTAMP_TZ `Z1 → Z2` at `+05:30`, compared with the Snowflake source
`DATEDIFF(<unit>, a, b)`:

| ThoughtSpot | Compiled SQL | TIMESTAMP_NTZ | TIMESTAMP_TZ (+05:30) |
|---|---|---|---|
| `diff_hours` | `DATEDIFF('HOUR', DATE '1970-01-01', b) - DATEDIFF('HOUR', DATE '1970-01-01', a)` | 10/10 equal (10:59 → 11:01 = 1; 10:00:30 → 10:59:59 = 0; 23:59:59 → 00:00:01 = 1) | **4/10 wrong**: counts UTC hours, Snowflake counts local ones (10:59 → 11:01 local: 1 vs 0; 17:29:59 → 17:30:01 local, which crosses 12:00 UTC: 0 vs 1) |
| `diff_minutes` | `DATEDIFF('MINUTE', DATE '1970-01-01', …)` differences | 10/10 | 10/10 |
| `diff_time` | `TIMESTAMPDIFF(second, a, b)` | 10/10 (17:59:59.900 → 18:00:00.100 = 1) | — |
| `diff_days` | `DATEDIFF(day, a, b)` | 10/10 (23:00 → 01:00 next day = 1) | 10/10 |
| `diff_months` | `DATEDIFF(month, epoch, b) - DATEDIFF(month, epoch, a)` | 10/10 | 10/10 (incl. Dec 31 23:00 → Jan 1 01:00 local) |
| `diff_years` | `EXTRACT(YEAR FROM b) - EXTRACT(YEAR FROM a)` | — | 10/10 |

So `diff_hours` is a boundary count only where the value's offset is a whole number of hours (or
there is none); the SQL translators now emit `DATEDIFF(hour)` as a `sql_int_op` pass-through.

**No escape for `"` in a `sql_*_op` template.** `sql_string_op ( "TO_CHAR({0}, 'YYYY\"m\"MM')" , d )`
is rejected at import: *Search did not find ""TO_CHAR ( { 0 } , 'YYYY"m"MM' ) " ," … (error_code
14516)* — the backslash does not escape, the quote ends the template (M0 `sf-date-018`,
09:50 UTC run; its JSON is `tools/formula-fidelity/runs/2026-10-06-snowflake-m0-after-fixes.json`
as committed in `a6c0ec4`, since superseded). A Snowflake format model
with double-quoted literal text therefore has no pass-through form, and the translators refuse it.

**Other parser checks in the same pass (all accepted):** `least ( [SALARY_RATES::BASE_RATE] , 10 )`
(the formula reference listed only `greatest`), `!=` between a column and a string literal,
`ifnull ( x , 0 )`, `quarter_number ( today ( ) )`, `ceil ( month_number ( today ( ) ) / 3 )` inside
`to_string`, `add_days ( add_months ( start_of_month ( d ) , 1 ) , -1 )`, `pow ( x , 2 )`, unary
`- x`. Case behaviour of `!=` was not probed (only its parse).

**Types, conversions and integer slots (added 2026-10-07, formula fidelity M1 fixes, BL-346..355).**
Probed on se-thoughtspot with the same `SALARY_RATES` table (`RATE_ID` INT64, `DEPARTMENT`
VARCHAR, `EFFECTIVE_DATE` DATE, `BASE_RATE` DOUBLE): parser rows by one-formula
VALIDATE_ONLY imports, values by a scratch Model (`ZZ_PROBE_M1FIX_*_DELETE_ME`, three of them,
each deleted and confirmed absent with `ts metadata search`) and `ts agentql fetch-data` /
`generate-sql`. These facts are what `ts_cli/excel/typecheck.py`'s signature table rests on.

*ThoughtSpot's "Numeric" is an integer.* Every error message asking for *Numeric* rejects a
DOUBLE column and a decimal literal alike:

| Formula | Parser |
|---|---|
| `substr ( [DEPARTMENT] , [BASE_RATE] , 2 )`, `substr ( 'abc' , 1 , [BASE_RATE] )`, `substr ( [DEPARTMENT] , 1.5 , 2 )` | rejected: *Function substr expects 2nd (3rd) argument to be Numeric* |
| `left ( 'a string' , [BASE_RATE] )` | rejected (*left expects 2nd argument to be Numeric*); `right` the same (M1) |
| `add_days ( [EFFECTIVE_DATE] , [BASE_RATE] )`, `add_days ( [EFFECTIVE_DATE] , 1.5 )`, `add_months ( [EFFECTIVE_DATE] , [BASE_RATE] )` | rejected (*expects 2nd argument to be Numeric*) |
| `mod ( [BASE_RATE] , 2.5 )`, `mod ( [RATE_ID] , 2.5 )` | rejected (1st, 2nd argument); `mod ( [RATE_ID] , 2 )` accepted |
| `to_double ( [BASE_RATE] )` | rejected: *Function to_double expects 1st argument to be Boolean or Numeric or Text*; `to_double` of an INT64, a VARCHAR or a boolean is accepted |
| `substr ( [DEPARTMENT] , floor ( [BASE_RATE] ) - 1 , floor ( [BASE_RATE] ) )`, `substr ( … , to_integer ( [BASE_RATE] ) - 1 , 2 )`, `right ( 'a string' , floor ( [BASE_RATE] ) )`, `add_days ( to_date ( '1899-12-30' , '%Y-%m-%d' ) , floor ( [BASE_RATE] ) )` | accepted: `floor` / `ceil` / `to_integer` return INT64 |
| `abs`, `ceil`, `floor`, `round`, `pow`, `sqrt`, `ln`, `exp`, `log10`, `safe_divide`, `greatest`, `least`, unary `-`, `*`, `sum`, `average`, `max`, `sum_if` over `[BASE_RATE]` | accepted |

*Other type rules.*

| Formula | Parser |
|---|---|
| `to_string ( [EFFECTIVE_DATE] )`, `to_string ( now ( ) )` | rejected: *Function to_string expects 2 arguments, found 1* — no one-argument form for a DATE or DATE_TIME |
| `strlen ( 5 )`, `strpos ( [DEPARTMENT] , 5 )`, `contains ( [DEPARTMENT] , 5 )`, `concat ( 'a' , [RATE_ID] )` | rejected (*expects … argument to be Text*) |
| `year`, `day_number_of_week`, `quarter_number` of `[BASE_RATE]` or of text; `start_of_month ( 'x' )`; `diff_days ( [BASE_RATE] , [BASE_RATE] )` | rejected (*expects … Date or DateTime*); `year ( now ( ) )`, `day_number_of_week ( now ( ) )`, `diff_days ( now ( ) , [EFFECTIVE_DATE] )` accepted |
| `[RATE_ID] = 'a'`, `[RATE_ID] = true` | rejected: *Expecting a List token*; `[RATE_ID] = [BASE_RATE]` accepted |
| `[EFFECTIVE_DATE] = '2020-01-01'` | rejected (the text re-read as search tokens) |
| `[EFFECTIVE_DATE] + 1`, `[DEPARTMENT] * 2`, `- [DEPARTMENT]`, `abs ( [RATE_ID] > 1 )` | rejected |
| `[RATE_ID] and true`, `not ( [RATE_ID] )`, `if ( [RATE_ID] ) then 1 else 0` | rejected (*(If / else if) expects condition to be Boolean*) |
| `if ( c ) then 1 else 2.5`, `if ( c ) then [RATE_ID] else [BASE_RATE]` | accepted: INT64 and DOUBLE branches join |
| `if ( c ) then true else 1` | rejected: *Unknown data type* |
| `if ( c ) then [EFFECTIVE_DATE] else 'x'`, `if ( 0 = 0 ) then 'x' else 0 / 0` | rejected (*Expecting a DateTime / Text token*); `… else to_string ( 0 / 0 )` accepted |
| `ifnull ( [RATE_ID] , 'x' )` | rejected (*ifnull expects 2nd argument to be Numeric*) |
| `sql_string_op ( "UPPER({0})" , [RATE_ID] )`, `sql_string_op ( "UPPER({0})" , [EFFECTIVE_DATE] )` | accepted — a pass-through's arguments are not type-checked |

*Values (scratch Model, se-thoughtspot, 2026-10-07).*

| Formula | Result | Compiled SQL |
|---|---|---|
| `to_date ( '2001-03-31' , '%Y-%m-%d' )` | 2001-03-31 | `TO_DATE('2001-03-31','YYYY-MM-DD')` — ThoughtSpot translates the strftime pattern |
| `to_date ( '2001-03-31' , 'yyyy-MM-dd' )` | 2001-03-31 | `TO_DATE('2001-03-31','yyyy-MM-dd')` — passed through verbatim; works because Snowflake's format elements are case-insensitive, so `'%Y-%m-%d'` is the form to emit |
| `to_date ( '31/03/2001' , '%d/%m/%Y' )`, `to_date ( '03/04/2026' , '%m/%d/%Y' )` | 2001-03-31, 2026-03-04 | `'DD/MM/YYYY'`, `'MM/DD/YYYY'` |
| `to_date ( '2001-03-31 10:20:30' , '%Y-%m-%d %H:%M:%S' )`; `day ( to_date ( '…T15:26:14' , '%Y-%m-%dT%H:%M:%S' ) )` | the date; 29 | `'YYYY-MM-DD HH24:MI:SS'` — the time is dropped |
| `diff_days ( to_date ( '2000-01-01' , '%Y-%m-%d' ) , to_date ( '1899-12-30' , '%Y-%m-%d' ) )` | 36526 | Excel's serial for 2000-01-01 |
| `to_integer ( 2.7 )`, `to_integer ( - 2.7 )`, `to_integer ( '2.5' )` | 3, −3, 3 | **rounds**, so it is not Excel's truncation; `floor ( - 2.5 )` = −3 |
| `to_double ( '2.99999' )`, `to_double ( ' 7' )` | 2.99999, 7.0 | leading space accepted |
| `to_string ( 2 < 3 )` | `true` | lower case (Excel: `TRUE`, BL-349) |
| `to_string ( 534 )`, `to_string ( to_double ( '534' ) )` | `534`, `534` | |
| `to_string ( [BASE_RATE] )` (95000.0) | `95000.00` | the column's NUMBER(…, 2) scale shows — a DOUBLE column's text follows the warehouse type |
| `ceil ( 8.234567890134 * 100000000000 ) / 100000000000` | 8.234568 | **an integer quotient keeps scale 6 in Snowflake** (BL-348); `/ to_double ( 100000000000 )` and `to_double ( ceil ( … ) ) / 100000000000` give 8.234568 too |
| `ceil ( 8.234567890134 * 100000000000 ) * 0.00000000001` | 8.23456789014 | multiplying by the increment keeps all 11 digits — the form the Excel translator now emits |

*Review of #574 (2026-10-07, two more scratch Models, each deleted and confirmed absent).*

| Formula | Result |
|---|---|
| `ceil ( to_double ( '1.1' ) * 100 ) * 0.01` | **1.11** — `1.1 * 100` is `110.00000000000001` in a double |
| `ceil ( round ( to_double ( '1.1' ) * 100 , 0.000000001 ) ) * 0.01` | 1.1 — **but the snap is wrong on other values**: `round ( v , 0.000000001 )` compiles to `1.0E-9 * round ( v / 1.0E-9 )`, which lands one ulp above the integer, so `ceil` jumps a step on exact grid values (3.0 → 3.1, 0.15 → 0.16, 2.5 → 2.51; `floor` −200 → −200.1). Superseded by the nudge, ts-cli 0.162.0 — see the grid below |
| `floor ( to_double ( '0.29' ) * 100 ) * 0.01` / snapped | 0.28 / 0.29 |
| `ceil ( to_double ( '1.1' ) / 0.1 ) * 0.1` / snapped | 1.1 / 1.1 here (the raw form gives 1.2 in IEEE arithmetic in general — `1.1 / 0.1` is `11.000000000000002`; the warehouse's rounding happened to absorb it) |
| `floor ( round ( to_double ( '-0.57' ) * 100 , 0.000000001 ) ) * 0.01` | −0.5700000000000001 (within any 1e-12 tolerance) |
| `ceil ( round ( [BASE_RATE] * 100 , 0.000000001 ) ) * 0.01` | 95000.0 — accepted over a column |
| `to_double ( 'abc' )`, `to_double ( [DEPARTMENT] )` | **the query fails**: *Numeric value 'abc' is not recognized* (QUERY_EXECUTION_FAILED) — not NULL. Corrects the Excel map's E8, `VALUE` and `NUMBERVALUE` rows |
| `sql_double_op ( "TRY_TO_DOUBLE({0})" , [DEPARTMENT] )`, `ifnull ( … , 0 )` | NULL, 0.0 — the null-on-failure form |
| `sql_bool_op ( "TRY_TO_DOUBLE({0}) IS NOT NULL" , [DEPARTMENT] )` | false — the `ISNUMBER(VALUE(…))` form the translator now emits |
| `to_string ( 100000000000000000000 )`, `to_string ( to_double ( '1E+20' ) )` | `'100000000000000000000'`, `'1e+20'` (Excel writes `1E+20`) |

*Excel coverage pass (2026-10-07, five scratch Models over a one-row fidelity fixture — `ZZ_FIDELITY_PROBECOV_*_DELETE_ME` — each deleted and confirmed absent by the harness's teardown, warehouse tables dropped and confirmed with `SHOW TABLES`).* Values by `ts agentql fetch-data`; every formula also passed the VALIDATE_ONLY import first.

| Formula | Result |
|---|---|
| `sin ( 30 )`, `cos ( 60 )`, `tan ( 45 )` | −0.988, −0.952, 1.620 — compiled `SIN(30)`: **ThoughtSpot trigonometry is in radians** (BL-364). The repo's "degrees" rule was never probed and was wrong |
| `asin ( 0.5 )`, `acos ( [x] )` (0.5), `atan ( 1 )` | 0.5236, 1.0472, 0.7854 — radians out too |
| `sin ( 3.141592653589793 )` | 1.2246467991473532E-16, as a double `SIN(π)` |
| `sql_double_op ( "SINH({0})" , … )`, `COSH`, `TANH` (of 1000), `ASINH`, `ACOSH`, `ATANH`, `DEGREES`, `RADIANS`, `ATAN2` | Python `math` to the last digit; `TANH(1000)` = 1.0, `SINH(1e-10)` = 1e-10 (the `exp` compositions cancel / overflow there); `ATAN2(0, 0)` = 0 (Excel `#DIV/0!`) |
| `log2 ( 8 )`, `ln ( 27 ) / ln ( 3 )`, `log10 ( 1000 )` | 3.0, 3.0, **2.9999999999999996** (within 1e-12; Excel gives 3) |
| `sql_double_op ( "FACTORIAL(FLOOR({0}))" , 5.5 )`, `… , 25 )` | 120.0, 1.5511210043330986E+25 — the `sql_int_op` variant would overflow INT64 from 21! |
| `sql_string_op ( "CHR({0})" , … )` of 65, 233, 150, 0 | `A`, `é`, **U+0096** (Windows-1252 150 is an en dash), U+0000 (Excel `CHAR(0)` is `#VALUE!`) |
| `sql_int_op ( "ASCII({0})" , 'é…' )` / `"UNICODE({0})"` | **195** (the first UTF-8 *byte*) / 233. Excel `CODE` is 233, so the map's `ASCII` row was wrong for every non-ASCII character |
| `TO_CHAR({0}, 'FM…0.00')` of 2.675, 0.125 (FLOAT), 2.675 (literal); `'FM…0'` of −2.5 | `2.68`, `0.13`, `2.68`; `-3` — half away from zero, as Excel |
| `TO_CHAR({0}, 'FM…0.00')` of −0.001 | **`-0.00`** (Excel's output for a negative that rounds to zero was not verified: the translator refuses a literal and traps a column) |
| `TO_CHAR({0}, 'FM999,…,990')`, `'…0.0'`, 14-digit integer part | `1,234,568`, `12.3`, `12345679012654.31` |
| `TO_CHAR` of a DATE with `YYYY-MM-DD`, `DD MON YYYY`, `MMMM`, `DY`, `YY/MM/DD HH24:MI:SS`, `DD.MM.YYYY`, `HH24:MI:SS` | `2024-03-15`, `15 Mar 2024`, `March`, `Fri`, `24/03/15 00:00:00`, `15.03.2024`, `00:00:00` |
| `day_of_week ( [d] )` | **`friday`** — lower case (Excel `TEXT(d, "dddd")` is `Friday`; the translator wraps it in `INITCAP`) |
| `month ( [d] )`, `left ( month ( [d] ) , 3 )` | **`march`**, `mar` — lower case too (Excel `March`, `Mar`; the translator uses `TO_CHAR` `MMMM` / `MON`) |
| `sql_string_op ( "INITCAP({0})" , day_of_week ( [d] ) )` | `Friday` |
| `sql_string_op ( "INITCAP({0})" , … )` | `Abc1def X-Y O'neil` — Snowflake's default delimiters skip digits and the apostrophe, where Excel `PROPER` gives `Abc1Def X-Y O'Neil`. A delimiter list built with `\|\|` is rejected (*argument 1 to function INITCAP needs to be constant*), and **backslash escapes in a `sql_*_op` template do not survive** (`'\t\x22…'` became the letters `t`, `x`, `2`…): `PROPER` was left out of the coverage pass |
| `add_days ( add_months ( to_date ( concat ( to_string ( y ) , '-01-01' ) , '%Y-%m-%d' ) , 13 ) , -1 )` (y = 2024) | 2025-01-31 — the `DATE` composition, overflow-safe |
| `sql_int_op ( "POSITION({0}, {1}, {2})" , 'r' , s , 7 )`, `"POSITION(LOWER({0}), LOWER({1}), {2})"` | the 1-based position at or after the start — `FIND` / `SEARCH` with `start_num` |
| `[n] * 4 / 3` (n = 3); `( [n] * 4 ) / 3`; `12 / [n] * 2` | **3.999999** — compiled `n * (4 / NULLIF(3,0))`: ThoughtSpot groups a division under a preceding product, and the literal division is fixed-point at scale 6; bracketed, 4.0; left to right, 8.0 (BL-365). `[x] * 180 / 3.141592653589793` likewise lost seven digits — the 16 silent wrong answers of the coverage run's first fresh pass |
| `sql_double_op ( "PI()" )`; `[x] * 180 / sql_double_op ( "PI()" )` | 3.141592653589793; exact — a zero-argument template is accepted |
| `concat ( 'Bob' , 'x\'s ' , … )`, `concat ( 'x' , '\'s ' )` | **rejected at import** (*Search did not find "''s ' ,"*); `'o\'neil'` and `'\'s'` alone are accepted — the backslash escape fails after an earlier string literal |
| `if ( … ) then 'it''s' else 'no'` | **`it''s`** — a doubled quote is two quotes (BL-365) |
| `concat ( 'Bob' , sql_string_op ( "'''s '" ) , … )`; `'a\\b'` | `Bob's …`; `a\b` — the forms the Excel printer now emits |

The same run checked 39 translator outputs end to end against hand-computed Excel values (the new rounding family, `LOG`, trigonometry, `ATAN2`, `FACT`, `CHAR` / `CODE` / `UNICODE`, `REPLACE`, the `B` variants, `TEXT` number / percent / date formats, `DATE` overflow, `ISTEXT` / `ISLOGICAL`, `FIND` / `SEARCH` with a start): 39 of 39 equal after `dddd` moved to `INITCAP`.

*Review of #577 (2026-10-07, two more scratch Models, each deleted and confirmed absent).*

| Formula | Result |
|---|---|
| `floor ( 1999999 / 2000000 )` over two INT64 columns (the old `QUOTIENT` / `FLOOR` forms) | **1** — two NUMBER(38,0) values divide at scale 6 (0.9999995 → 1.000000) |
| `( [a] - mod ( [a] , [b] ) ) / [b]`; the remainder forms of `FLOOR`, `CEILING`, `FLOOR.MATH` (with and without mode), `CEILING.PRECISE` over a = ±1999999, b = 2000000 | 0, 0, 0, −2000000, 0, 2000000 — Excel's values; no division feeds `floor` / `ceil` |
| `mod ( [a] , [z] )` with z = 0 | **the query fails** (*Division by zero*), where `/` returns NULL — so the translator guards it, `if ( [z] = 0 ) then null else …` (NULL for `FLOOR` / `QUOTIENT`, 0 for `CEILING`); all three guarded forms returned NULL / 0 |
| a quote-bearing literal as `sql_string_op ( "'it''s here'" )` in `=` and `!=`, the `count_if` and `sum_if` conditions, `contains`, `left`, `substr`, `strlen`, and as an argument to `sql_string_op` (`UPPER`, `REPLACE`) and `sql_bool_op` templates | all imported and all returned Excel's values (`count_if` 1, `sum_if` 3, `IT'S`, `it-s here`, `true`); compiled e.g. `LOWER("S2") = LOWER('it''s here')` |

*The nudge replaces the snap (2026-10-07, a scratch Model over a 13-row DOUBLE fixture, deleted and confirmed absent).* `ceil ( v - 0.000000001 )` / `floor ( v + 0.000000001 )`, scaled back by `/ 10^n` (exact) up to 6 digits — the forms `formula_common.scaled_ceil_floor` now emits for every Excel `ROUNDUP` / `ROUNDDOWN` / `TRUNC` / `CEILING*` / `FLOOR*` over a DOUBLE. The grid: x = 3.0, 0.15, 0.29, 2.5, 1.1, −200, 0.57, 40.955, 3.00000001, −0.57, 1.101, −1.1 and 3.000000000001, through `ROUNDUP` and `ROUNDDOWN` at 0, 1, 2 and −1 decimals (both `ceil` and `floor`, both signs), `CEILING.MATH` at 0.1 and 1, `FLOOR.MATH` at 0.01 and 10, and `TRUNC` at 2 — 169 values, compared with Excel's result on the 15-significant-digit reading of x.

| Result | Values |
|---|---|
| equal to Excel | **164 of 169**, including every exact grid value the snap broke (3.0, 0.15, 2.5, −200 → unchanged) and the genuine near-step 3.00000001 (`ROUNDUP` to 1 place → 3.1) |
| different | 5: x = 3.000000000001 rounded up (to 0, 1, 2 places and `CEILING.MATH` 0.1 and 1) returns 3 where Excel gives 4, 3.1, 3.01 — **the documented trade-off**: a value within 1e-9 of a step (scaled) is read as on the step |

