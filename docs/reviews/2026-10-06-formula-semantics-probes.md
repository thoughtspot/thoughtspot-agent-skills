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
- **Not probed:** `!=`, `in { }`, `starts_with`, and a column (rather than a literal) as the needle.

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
takes the divisor's sign (`MOD(-3, 2)` = 1). So Excel `MOD(a, b)` is `a - b * floor ( a / b )`
in ThoughtSpot, and ThoughtSpot `mod ( a , b )` is `a-b*TRUNC(a/b)` in Excel.

**Other parser checks in the same pass (all accepted):** `least ( [SALARY_RATES::BASE_RATE] , 10 )`
(the formula reference listed only `greatest`), `!=` between a column and a string literal,
`ifnull ( x , 0 )`, `quarter_number ( today ( ) )`, `ceil ( month_number ( today ( ) ) / 3 )` inside
`to_string`, `add_days ( add_months ( start_of_month ( d ) , 1 ) , -1 )`, `pow ( x , 2 )`, unary
`- x`. Case behaviour of `!=` was not probed (only its parse).
