<!-- currency: databricks — 2026-09 (2026-09-28 BL-315/BL-316, budget/forecast MV number-matched on nebula-ts-semview: whole-table scalar subquery -> group_aggregate(…,{},{}); NOT IN; FILTER on any aggregate; SUM(SUM(x)) OVER (); day-grain offset LAG (was dropped); week grain + formula-ordered LAG; ratio windows; group_aggregate cannot nest in moving_sum; a lag reads only filter-surviving rows; PR1 window deep-analysis 2026-07-09: all 5 range values + inclusive|exclusive anchor modifier live-verified against a Databricks fixture + ThoughtSpot number-match — trailing/leading moving_sum args corrected (C1/C3), exclusive default confirmed (C2), all/cumulative/semi-additive confirmed (C4/C5/C7), period-filter offset corrected to row-relative (C6/C6a); quarter/year offset grains Deferred (C8); see BL-032; PR1.5 semantic deep-dive 2026-07-09: LOD dimension × filter (A1) CONFIRMED filter-aware on TS under both filter kinds, cross-platform DIVERGENCE for a DBX consumer's ad hoc query-time WHERE (A2, DBX-internal asymmetry); cross-measure ratio × grain (B1) CONFIRMED ratio-of-sums cross-platform at every grain; global filter: × window ordering (C1) CONFIRMED filter-before-window cross-platform, frame semantics DIVERGENCE (date-interval vs row-positional); semi-additive × date-range filter (D1) CONFIRMED last/first-in-filtered-range cross-platform; trailing-window frame (E1) DIVERGENCE — DBX date-interval vs TS row-positional on gapped data, density caveat added; A3 follow-up (user-suggested) 2026-07-09: group_aggregate's `{}` filter argument CORRECTS the A1/A2 "no TS analogue" conclusion — `{}` is search-filter-blind but model-filter-aware, reproducing DBX's MV-filter-aware + query-WHERE-blind composite when paired with a mirrored model-level filters: block; subtraction form query_filters() - {col} import-accepted but does not exclude a derived-formula filter — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md; see BL-032; 2026-07-11 audit: corrected the "Parameter References (untranslatable)" flowchart node and Untranslatable Patterns table row — MV `parameters:` IS a GA construct (18.2+); auto-translation is deferred, not "doesn't exist" (findings 13.1/13.10, deferred to 13.2)) -->

# Formula Translation Reference — Databricks

Bidirectional translation rules between ThoughtSpot formulas and **Databricks SQL**
Metric View expressions. Use **TS → Databricks** when converting ThoughtSpot models
to Metric Views (Step 9) and **Databricks → TS** when converting Metric Views to
ThoughtSpot models.

> **Platform-specific:** This reference targets Databricks SQL syntax. For Snowflake,
> see `../ts-snowflake/ts-snowflake-formula-translation.md`.

> **ThoughtSpot formula syntax:** For complete ThoughtSpot formula syntax reference,
> see **[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md)**.

---

## Translation Decision Flowchart

```
Formula / Expression contains...
├── [word] with no ::           → Parameter References (see note below — not yet auto-translated)
├── (SELECT AGG(x) FROM <MV source> [WHERE c]) → Scalar Subquery → group_aggregate ( … , { } , { } )
├── (SELECT ... FROM ...) other → Subquery (untranslatable — log in Unmapped Report)
├── -- or /* ... */             → SQL Comments (strip before translating)
├── *_if(cond, x)               → Conditional Aggregates (native *_if functions)
├── AGG(...) FILTER (WHERE ...) → Conditional Aggregates (FILTER WHERE clause)
├── sql_*_op(...)               → SQL Pass-Through Functions
├── cumulative_*                → Window: Cumulative Functions
├── moving_*                    → Window: Moving / Rolling Functions
├── rank( or rank_percentile(   → Window: Rank Functions
├── group_* or group_aggregate  → Level of Detail (LOD) Functions
├── last_value( or first_value(  → Semi-Additive: True Semi-Additive (snapshot metrics — order: raw date)
├── sum_if(diff_months/...      → Semi-Additive: Period Filter (flow metrics — order: truncated period)
├── cumulative_sum(             → Semi-Additive: Cumulative (range: cumulative)
├── COUNT(*)                    → count(1) — no direct COUNT(*) in TS
├── [TABLE::COL] references     → Resolve via Column Reference Syntax
├── [other_formula_name]        → Resolve via Nested Column References
└── standard function(args)     → Scalar Functions
```

**Corrected 2026-07-11 (audit findings 13.1/13.10) — Parameter References.** A bare
`[word]` with no `::` is only untranslatable when the target Metric View has no
matching entry in its `parameters:` block. Databricks MV runtime parameters ARE a
GA construct (Runtime 18.2+, see
[databricks-metric-view.md](../../schemas/databricks-metric-view.md#parameters-block-ga--runtime-182) —
"parameters don't exist in MVs" was wrong. The gap is on the *conversion* side, not
the platform side: this repo's converters do not yet auto-emit a ThoughtSpot Parameter
as an MV `parameters:` entry (or parse one back), pending live verification against an
18.2+ warehouse (audit finding 13.2, deferred). Until that lands, treat bare-word
Parameter References as **not yet auto-translated** and log them in the Unmapped
Report rather than treating them as inherently impossible.

---

## Column Reference Syntax

**ThoughtSpot Model TML** references:
```
[DM_ORDER::FREIGHT]
```
Resolution:
1. `DM_ORDER` is the table name
2. `FREIGHT` is the column name
3. In v0.1 MV (single source): output `FREIGHT` (no prefix)
4. In v1.1 MV (multi-source): output `dm_order.FREIGHT`

---

## Scalar Functions

### String Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `concat(a, b)` | `CONCAT(a, b)` | |
| `strlen(s)` | `LENGTH(s)` | |
| `strpos(s, sub)` | `LOCATE(sub, s)` | Argument order reversed. **Case semantics differ (BL-333):** ThoughtSpot's native form is case-insensitive — it lowercases both sides at compile time (live-verified 2026-10-06, se-thoughtspot; [formula reference](../../schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive)) — while Databricks' default `UTF8_BINARY` collation is case-sensitive. Exact only on data of consistent case; the translator is unchanged. |
| `substr(s, start, len)` | `SUBSTRING(s, start, len)` | |
| `sql_string_op("LOWER({0})", s)` | `LOWER(s)` | Auto-translated pass-through (ts-cli v0.50.0) |
| `sql_string_op("UPPER({0})", s)` | `UPPER(s)` | Auto-translated pass-through (ts-cli v0.50.0) |
| `sql_string_op("TRIM({0})", s)` | `TRIM(s)` | **No native `trim` in ThoughtSpot** — pass-through (live-verified 2026-07-29, se-thoughtspot — BL-170) |
| `sql_string_op("LTRIM({0})", s)` | `LTRIM(s)` | **No native `ltrim`** — pass-through (live-verified 2026-07-29, se-thoughtspot — BL-170) |
| `sql_string_op("RTRIM({0})", s)` | `RTRIM(s)` | **No native `rtrim`** — pass-through (live-verified 2026-07-29, se-thoughtspot — BL-170) |
| `sql_string_op("REPLACE({0}, {1}, {2})", s, old, new)` | `REPLACE(s, old, new)` | **No native `replace`** — pass-through (live-verified 2026-07-29, se-thoughtspot — BL-170) |
| `contains(s, sub)` | `CONTAINS(s, sub)` | **Case semantics differ (BL-333):** ThoughtSpot's native form is case-insensitive — it lowercases both sides at compile time (live-verified 2026-10-06, se-thoughtspot; [formula reference](../../schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive)) — while Databricks' default `UTF8_BINARY` collation is case-sensitive. Exact only on data of consistent case; the translator is unchanged. |
| `strpos(s, prefix) = 1` | `STARTSWITH(s, prefix)` | **No native `starts_with`** — compose from `strpos`, which is 1-based (live-verified 2026-07-29, se-thoughtspot — BL-170). **Case semantics differ (BL-333):** ThoughtSpot's native form is case-insensitive — it lowercases both sides at compile time (live-verified 2026-10-06, se-thoughtspot; [formula reference](../../schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive)) — while Databricks' default `UTF8_BINARY` collation is case-sensitive. Exact only on data of consistent case; the translator is unchanged. |
| `substr(s, strlen(s) - strlen(sfx), strlen(sfx)) = sfx` | `ENDSWITH(s, sfx)` | **No native `ends_with`** — compose from `substr`/`strlen` (live-verified 2026-07-29, se-thoughtspot — BL-170) |
| `left(s, n)` | `LEFT(s, n)` | |
| `right(s, n)` | `RIGHT(s, n)` | |
| `lpad(s, n, pad)` | `LPAD(s, n, pad)` | |
| `rpad(s, n, pad)` | `RPAD(s, n, pad)` | |
| `reverse(s)` | `REVERSE(s)` | |
| `repeat(s, n)` | `REPEAT(s, n)` | |

### Numeric Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `abs(x)` | `ABS(x)` | |
| `ceil(x)` | `CEIL(x)` | |
| `floor(x)` | `FLOOR(x)` | |
| `round(x, inc)` | `ROUND(x, d)` / `(inc * ROUND(x / inc))` | ThoughtSpot's 2nd arg is a rounding **increment** (BL-331, live-probed 2026-10-06). A literal power-of-ten `inc` → `ROUND(x, d)` with `d = -log10(inc)` (`0.01` → `2`, `1` → `0`, `100` → `-2`); any other literal → `(inc * ROUND(x / inc))`; non-literal → `(inc * ROUND(x / NULLIF(inc, 0)))`. `round(x, 0)` is NULL in ThoughtSpot — refused as untranslatable |
| `mod(x, y)` | `MOD(x, y)` | |
| `pow(x, y)` | `POWER(x, y)` | TS function is `pow`, not `power` (verified 2026-06-13) |
| `sqrt(x)` | `SQRT(x)` | |
| `ln(x)` | `LN(x)` | |
| `log2(x)` | `LOG2(x)` | |
| `log10(x)` | `LOG10(x)` | |
| `safe_divide(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` | No `DIV0` in Databricks |
| `if_null(x, default)` | `COALESCE(x, default)` | |
| `zero_if_null(x)` | `COALESCE(x, 0)` | No `ZEROIFNULL` in Databricks |
| `null_if_zero(x)` | `NULLIF(x, 0)` | |

### Date / Time Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `today()` | `CURRENT_DATE()` | |
| `now()` | `CURRENT_TIMESTAMP()` | |
| `date(ts)` | `DATE(ts)` or `date_trunc('day', ts)` | |
| `year(d)` | `YEAR(d)` | |
| `month_number(d)` | `MONTH(d)` | `month()` also exists but returns the name (e.g. "January"), not the number |
| `day(d)` | `DAY(d)` | Extracts day of month (1–31). `day_of_month` does not exist in TS. |
| `day_number_of_week(d)` | `DAYOFWEEK(d)` | TS `day_number_of_week` returns number (1=Mon, 7=Sun); Databricks `DAYOFWEEK` returns number (1=Sun). `day_of_week(d)` also exists but returns the name (e.g. "Friday"). Confirmed 2026-10-06: TS is fixed 1 = Monday (compiles to day-count arithmetic). So the exact pair is `day_number_of_week(d)` ↔ `mod(DAYOFWEEK(d) + 5, 7) + 1`; **`mv_sql.py` still renames `DAYOFWEEK` → `day_number_of_week`** (wrong on every day) — BL-334 |
| `day_number_of_year(d)` | `DAYOFYEAR(d)` | TS function is `day_number_of_year`, not `day_of_year` |
| `hour_of_day(ts)` | `HOUR(ts)` | TS function is `hour_of_day`, not `hour` |
| `sql_int_op("MINUTE({0})", ts)` | `MINUTE(ts)` | Auto-translated pass-through (ts-cli v0.50.0) |
| `sql_int_op("SECOND({0})", ts)` | `SECOND(ts)` | Auto-translated pass-through (ts-cli v0.50.0) |
| `quarter_number(d)` | `QUARTER(d)` | TS function is `quarter_number`, not `quarter` |
| `week_number_of_year(d)` | `WEEKOFYEAR(d)` | TS function is `week_number_of_year`, not `week_of_year` |
| `start_of_month(d)` | `date_trunc('month', d)` | |
| `start_of_quarter(d)` | `date_trunc('quarter', d)` | |
| `start_of_year(d)` | `date_trunc('year', d)` | |
| `start_of_week(d)` | `date_trunc('week', d)` | Week start day may differ. TS week start comes from the Model's calendar, Monday when nothing else is set (ThoughtSpot domain review, 2026-10-06); Databricks `date_trunc('week')` is Monday-start, so they agree under the default calendar (BL-334) |
| `diff_days(start, end)` | `DATEDIFF(end, start)` | Arg order reversed; Databricks `DATEDIFF` returns days only |
| `diff_days(start, end)` | `DATEDIFF(DAY, start, end)` | 3-arg form: unit first; reverse args for TS |
| `diff_months(start, end)` | `DATEDIFF(MONTH, start, end)` | 3-arg form: unit first; reverse args for TS. TS `diff_months` counts month boundaries (live-verified 2026-10-06); Databricks `DATEDIFF(MONTH, …)` / `timestampdiff` counts **complete** months (Databricks docs — `timestampdiff` semantics; not probed here), so the two differ by one when the end's day-of-month is before the start's |
| `diff_months(start, end)` | `MONTHS_BETWEEN(end, start)` | Returns fractional months |
| `year(d)` | `EXTRACT(YEAR FROM d)` | `EXTRACT` form — same as `YEAR(d)` |
| `month_number(d)` | `EXTRACT(MONTH FROM d)` | `EXTRACT` form — same as `MONTH(d)` |
| `day(d)` | `EXTRACT(DAY FROM d)` | `EXTRACT` form — same as `DAY(d)` |
| `hour_of_day(ts)` | `EXTRACT(HOUR FROM ts)` | `EXTRACT` form — same as `HOUR(ts)` |
| `add_days(d, n)` | `DATE_ADD(d, n)` | |
| `add_months(d, n)` | `ADD_MONTHS(d, n)` | |
| `sql_string_op("DATE_FORMAT({0}, 'fmt')", d)` | `DATE_FORMAT(d, fmt)` | Auto-translated pass-through — format literal baked into SQL template (ts-cli v0.50.0) |

### Conditional / Logic Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `if (cond) then val else val` | `CASE WHEN cond THEN val ELSE val END` | Or `IF(cond, val, val)` |
| `ifnull(x, default)` | `COALESCE(x, default)` | |
| `isnull(x)` | `x IS NULL` | |
| `not(x)` | `NOT x` | |
| `in(x, a, b, c)` | `x IN (a, b, c)` | |
| `between(x, lo, hi)` | `x BETWEEN lo AND hi` | |
| `greatest(a, b, ...)` | `GREATEST(a, b, ...)` | |
| `least(a, b, ...)` | `LEAST(a, b, ...)` | |

---

## Aggregate Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `sum(x)` | `SUM(x)` | |
| `average(x)` | `AVG(x)` | |
| `count(x)` | `COUNT(x)` | |
| `count(1)` | `COUNT(*)` | TS has no `COUNT(*)` — use `count(1)` |
| `unique count(x)` | `COUNT(DISTINCT x)` | |
| `min(x)` | `MIN(x)` | |
| `max(x)` | `MAX(x)` | |
| `stddev(x)` | `STDDEV(x)` | |
| `variance(x)` | `VARIANCE(x)` | |
| `median(x)` | `MEDIAN(x)` | |
| `sum_if(cond, x)` | `SUM(x) FILTER (WHERE cond)` | Conditional aggregate |
| `count_if(cond, x)` | `COUNT(x) FILTER (WHERE cond)` | Conditional aggregate |
| `unique_count_if(cond, x)` | `COUNT(DISTINCT x) FILTER (WHERE cond)` | Conditional aggregate |
| `average_if(cond, x)` | `AVG(x) FILTER (WHERE cond)` | Conditional aggregate |
| `min_if(cond, x)` | `MIN(x) FILTER (WHERE cond)` | Conditional aggregate |
| `max_if(cond, x)` | `MAX(x) FILTER (WHERE cond)` | Conditional aggregate |
| `stddev_if(cond, x)` | `STDDEV(x) FILTER (WHERE cond)` | Conditional aggregate |
| `variance_if(cond, x)` | `VARIANCE(x) FILTER (WHERE cond)` | Conditional aggregate |

### Conditional Aggregates — `FILTER (WHERE ...)` Clause

Databricks SQL supports the `FILTER (WHERE ...)` clause on aggregate functions.
ThoughtSpot has native `*_if` conditional aggregate functions — use these as the
**primary** translation. Fall back to `agg(if (cond) then x else null)` only when no
native `*_if` function exists for the aggregate type.

#### Databricks → TS (primary: native `*_if` functions)

| Databricks SQL | ThoughtSpot formula | Notes |
|---|---|---|
| `SUM(x) FILTER (WHERE cond)` | `sum_if ( cond , [x] )` | Native |
| `COUNT(x) FILTER (WHERE cond)` | `count_if ( cond , [x] )` | Native |
| `COUNT(DISTINCT x) FILTER (WHERE cond)` | `unique_count_if ( cond , [x] )` | Native |
| `AVG(x) FILTER (WHERE cond)` | `average_if ( cond , [x] )` | Native |
| `MIN(x) FILTER (WHERE cond)` | `min_if ( cond , [x] )` | Native |
| `MAX(x) FILTER (WHERE cond)` | `max_if ( cond , [x] )` | Native |
| `STDDEV(x) FILTER (WHERE cond)` | `stddev_if ( cond , [x] )` | Native |
| `VARIANCE(x) FILTER (WHERE cond)` | `variance_if ( cond , [x] )` | Native |

**`*_if` function signature:** `agg_if ( condition , measure_expression )`
- First argument is the boolean condition
- Second argument is the measure column or expression

**Fallback pattern** (if a `*_if` function doesn't exist for the aggregate type):
Wrap the column in `if()` inside the aggregate:
- `agg ( if ( cond , [x] , null ) )` — for COUNT, AVG, MIN, MAX (skip nulls)
- `agg ( if ( cond , [x] , 0 ) )` — for SUM only (`0` is additive-neutral)

Translate the `cond` expression using the standard SQL → TS rules from this file.

**Example:**
```sql
-- Databricks MV
COUNT(DISTINCT customer_id) FILTER (WHERE NOT is_return AND transaction_status = 'Completed')
```
```
-- ThoughtSpot formula (primary)
unique_count_if ( [TABLE::is_return] = false and [TABLE::transaction_status] = 'Completed' , [TABLE::customer_id] )
```

#### TS → Databricks

| ThoughtSpot formula | Databricks SQL |
|---|---|
| `sum_if ( cond , [x] )` | `SUM(x) FILTER (WHERE cond)` |
| `count_if ( cond , [x] )` | `COUNT(x) FILTER (WHERE cond)` |
| `unique_count_if ( cond , [x] )` | `COUNT(DISTINCT x) FILTER (WHERE cond)` |
| `average_if ( cond , [x] )` | `AVG(x) FILTER (WHERE cond)` |
| `min_if ( cond , [x] )` | `MIN(x) FILTER (WHERE cond)` |
| `max_if ( cond , [x] )` | `MAX(x) FILTER (WHERE cond)` |
| `stddev_if ( cond , [x] )` | `STDDEV(x) FILTER (WHERE cond)` |
| `variance_if ( cond , [x] )` | `VARIANCE(x) FILTER (WHERE cond)` |

Also detect the fallback pattern: an aggregate wrapping `if()` where the else
branch is `null` (or `0` for SUM) → extract the condition into `FILTER (WHERE ...)`.

---

## SQL Pass-Through Functions

Pass-through policy: scalar reliable, aggregate flag for review — see PT1 in ../../schemas/ts-model-conversion-invariants.md

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `sql_int_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_bool_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_str_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_number_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_date_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |
| `sql_datetime_op(expr)` | `expr` | Unwrap — emit the inner SQL directly |

The inner expression is already valid SQL. Strip the wrapper function and emit
the contents. If the SQL uses Snowflake-specific syntax, translate it to
Databricks SQL equivalents.

### JSON path access — use `get_json_object`, NOT bracket notation

Databricks colon-path access for semi-structured columns (`col:field.subfield`) is
valid Databricks SQL but **fails ThoughtSpot's `sql_*_op` template parser**. The
Snowflake fix — bracket notation on the parsed value — **does not work on Databricks**:
`parse_json(col)['field']` errors with `INVALID_EXTRACT_BASE_FIELD_TYPE` because `[...]`
extraction requires a complex type (`STRUCT`/`ARRAY`/`MAP`), and `parse_json` returns
`VARIANT`. Use one of these colon-free forms instead:

| Databricks JSON access | ThoughtSpot pass-through | Notes |
|---|---|---|
| `col:field.subfield` (rejected by TS) | `sql_string_op ( "get_json_object({0}, '$.field.subfield')" , [T::COL] )` | **Preferred.** No colon, no schema needed. The `'$.path'` is a quoted string literal, so the TS parser accepts it. |
| — | `sql_string_op ( "from_json({0}, 'field struct<subfield:string>')['field']['subfield']" , [T::COL] )` | Bracket extraction is valid here because `from_json` returns `STRUCT`. Requires declaring the JSON schema in the template — more verbose; use when you need typed nested extraction. |

Verified live on Databricks 2026-07-15 (`get_json_object` and the `from_json`+bracket
form both return the value; `parse_json(...)['...']` fails; colon-path executes on
Databricks but is rejected by ThoughtSpot). Canonical constraint:
[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md#json--variant-path-access--bracket-notation-only).

**Codified (ts-cli ≥ v0.54.0):** `ts databricks translate-formulas` rewrites a
whole-expression colon path (`col:a.b`, `parse_json(col):a.b`, optional trailing
`::string` cast) to `get_json_object({0}, '$.a.b')` automatically. Non-string casts
(`::int`, …) and array indices (`items[0]`) are not codified — they route to
`skipped[]` with a reason rather than emitting a wrong translation.

---

## Window Functions

### Cumulative Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `cumulative_sum(measure)` | `SUM(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` | Requires a sort column |
| `cumulative_average(measure)` | `AVG(measure) OVER (ORDER BY {sort_col} ROWS UNBOUNDED PRECEDING)` | |
| `cumulative_max(measure)` | `MAX(measure) OVER (ORDER BY {sort_col} ROWS UNBOUNDED PRECEDING)` | |
| `cumulative_min(measure)` | `MIN(measure) OVER (ORDER BY {sort_col} ROWS UNBOUNDED PRECEDING)` | |

### Moving Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `moving_sum(measure, s, e, sort_col)` | `SUM(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {s} PRECEDING AND {e < 0 ? ABS(e) PRECEDING : e FOLLOWING})` | 4-arg signature, not 2-arg — window spans `[-s, +e]` rows around the current row (opposite-sign convention on `e`; see Rolling Window Functions below). Live-verified 2026-07-09 — `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1/C3) |
| `moving_average(measure, s, e, sort_col)` | `AVG(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {s} PRECEDING AND {e < 0 ? ABS(e) PRECEDING : e FOLLOWING})` | Same signature and frame rule as `moving_sum` above |
| `moving_max(measure, s, e, sort_col)` | `MAX(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {s} PRECEDING AND {e < 0 ? ABS(e) PRECEDING : e FOLLOWING})` | Same 4-arg signature and frame rule as `moving_sum` above; not separately live-tested |
| `moving_min(measure, s, e, sort_col)` | `MIN(measure) OVER (ORDER BY {sort_col} ROWS BETWEEN {s} PRECEDING AND {e < 0 ? ABS(e) PRECEDING : e FOLLOWING})` | Same 4-arg signature and frame rule as `moving_sum` above; not separately live-tested |

### Rolling Window Functions

Databricks MV `window: [{range: trailing N day}]` is a date-based rolling window.
ThoughtSpot's `moving_sum`/`moving_average` operate on row counts, not calendar days,
so the mapping assumes one row per day (daily grain). If the source data has multiple
rows per day or gaps, the results may differ. `moving_sum`'s argument order is
`moving_sum(measure, start, end, sort_column)` — see
[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md#moving-functions)
for the `start`/`end` opposite-sign convention this section relies on.

**Corrected 2026-07-09 (matrix C1/C2, `docs/audit/2026-07-08-dbx-window-claim-matrix.md`).**
`moving_sum([m], N, 0, [date])` always includes the anchor row (`end=0` means "up to
and including the current row"), so it spans **N+1 rows** and reproduces `trailing
(N+1) day inclusive` — **not** `trailing N day` (Databricks' default/exclusive form).
The tables below are the corrected mappings, live-verified at every row of a 24-row
fixture including boundary partial-window/`NULL` rows.

#### Databricks → TS

| Databricks MV YAML | ThoughtSpot formula | Notes |
|---|---|---|
| `window: [{order: date_dim, range: trailing 7 day, semiadditive: last}]` (default/exclusive) | `moving_sum ( [m] , 7 , -1 , [date] )` | 7-day rolling sum, anchor excluded |
| `window: [{order: date_dim, range: trailing 7 day exclusive, semiadditive: last}]` | `moving_sum ( [m] , 7 , -1 , [date] )` | Explicit exclusive — same as default |
| `window: [{order: date_dim, range: trailing 7 day inclusive, semiadditive: last}]` | `moving_sum ( [m] , 6 , 0 , [date] )` | Anchor included — 7 rows total |
| `window: [{order: date_dim, range: trailing N day, semiadditive: last}]` (default/exclusive) | `moving_sum ( [m] , N , -1 , [date] )` | General pattern |
| `window: [{order: date_dim, range: trailing N day inclusive, semiadditive: last}]` | `moving_sum ( [m] , N-1 , 0 , [date] )` | General pattern |
| `window: [{order: date_dim, range: trailing 7 day, semiadditive: last}]` (avg) | `moving_average ( [m] , 7 , -1 , [date] )` | Rolling average variant |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1, C2). Boundary behavior
matches on both platforms: a partial sum when 1..N-1 rows are available, `NULL`
only when zero rows are available.

**Density caveat (E1, live-verified 2026-07-09 on gapped data — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** The tables above and below
were re-verified against a fixture with date gaps and found to **diverge**:
Databricks' `trailing N day` is a genuine date-interval window; `moving_sum` counts
rows. On dense daily data the two framings are identical, which is why the C1/C2
verification above didn't surface this.

Row-positional: matches Databricks' date-interval trailing/leading windows only when the order column is dense at the window's unit grain (one row per unit, no gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

#### TS → Databricks

| ThoughtSpot | Databricks MV YAML |
|---|---|
| `moving_sum([m], N, -1, [d])` | `expr: SUM(m)` + `window: [{order: date_dim, range: trailing N day, semiadditive: last}]` (default/exclusive) |
| `moving_sum([m], N-1, 0, [d])` | `expr: SUM(m)` + `window: [{order: date_dim, range: trailing N day inclusive, semiadditive: last}]` |
| `moving_average([m], 30, -1, [d])` | `expr: AVG(m)` + `window: [{order: date_dim, range: trailing 30 day, semiadditive: last}]` |

**Note:** `moving_sum([m], N, 0, [d])` (anchor-inclusive, the form previously
mismapped to plain `trailing N day`) translates to `range: trailing (N+1) day
inclusive`, not `trailing N day` — adjust N accordingly when translating this
direction.

#### Leading Window (`range: leading N unit`)

`range` has **five** values — `current | cumulative | trailing <N> <unit> |
leading <N> <unit> | all` — plus an `inclusive|exclusive` anchor-row modifier
(default `exclusive`, applying only to `trailing`/`leading`). `leading` is the
look-ahead counterpart to `trailing`.

**Corrected 2026-07-09 (matrix C3).** The candidate previously listed here
(`moving_sum([m], 0, 7, [date])`) is **wrong** — it always includes the anchor row
(spans N+1 rows: anchor + N following) and matches neither the `exclusive` nor
`inclusive` DBX form.

| Databricks MV YAML | ThoughtSpot formula |
|---|---|
| `window: [{order: date_dim, range: leading 7 day, semiadditive: last}]` (default/exclusive) | `moving_sum ( [m] , -1 , 7 , [date] )` |
| `window: [{order: date_dim, range: leading 7 day inclusive, semiadditive: last}]` | `moving_sum ( [m] , 0 , 6 , [date] )` |
| `window: [{order: date_dim, range: leading N day, semiadditive: last}]` (default/exclusive) | `moving_sum ( [m] , -1 , N , [date] )` |
| `window: [{order: date_dim, range: leading N day inclusive, semiadditive: last}]` | `moving_sum ( [m] , 0 , N-1 , [date] )` |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C3).

**Density caveat (E1)** — same as the Rolling Window section above: row-positional:
matches Databricks' date-interval trailing/leading windows only when the order
column is dense at the window's unit grain (one row per unit, no gaps) — see
docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

#### All-Partition Window (`range: all`)

`range: all` spans the entire partition, unbounded in both directions — not a
bounded rolling window like `trailing`/`leading`. Confirmed **scoped per query
partition** (e.g. per category), not table-wide.

| Databricks MV YAML | ThoughtSpot formula | Column type |
|---|---|---|
| `window: [{order: date_dim, range: all}]`, partitioned by `cat` | `group_aggregate ( sum ( [m] ) , { [cat] } , query_filters ( ) )` | **ATTRIBUTE** — see LOD section below |

The partition-wide `group_aggregate(...)` is the same LOD mechanism as
`AGG() OVER (PARTITION BY ...)` — see the LOD section below.

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C4): matched DBX exactly at
both row grain and category grain.

**Filter asymmetry caveat (A1/A2)** — because this mapping shares the LOD
mechanism above, it inherits the same DBX-side asymmetry: filter-aware for a
Databricks MV's own global `filter:`, filter-blind for an ad hoc query-time
`WHERE` on an MV with no global `filter:` — see the LOD Functions section above
and `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` (A1/A2).

#### Anchor-Row Modifier (`inclusive` | `exclusive`)

`trailing`/`leading` ranges accept an `inclusive|exclusive` modifier controlling
whether the anchor (current) row is included in the window. The modifier applies
**only** to `trailing`/`leading` — `current`, `cumulative`, and `all` do not
accept it. **Confirmed default: `exclusive`** (Runtime 18.1 + YAML 1.1; DBSQL
2026.10 preview, release note 2026-03-26) — confirmed live 2026-07-08:
`trailing N day` == `trailing N day exclusive` at all 24 fixture rows.

The `trailing N day` ↔ `moving_sum([m], N, 0, [date])` equivalence recorded in
the tables above before 2026-07-09 was **wrong** for the reason given at the top
of this section — the corrected forms are in the Rolling Window and Leading
Window tables above.

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1, C2, C3).

### Rank Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `rank(expr)` | `RANK() OVER (ORDER BY expr)` | |
| `rank(expr, 'asc')` | `RANK() OVER (ORDER BY expr ASC)` | |
| `rank(expr, 'desc')` | `RANK() OVER (ORDER BY expr DESC)` | |

---

## Level of Detail (LOD) Functions (verified 2026-05-25)

LOD functions map to **dimension window functions** in Metric Views. The LOD
column becomes a `dimensions[]` entry (not a measure), using
`AGG() OVER (PARTITION BY ...)` in the `expr`.

### TS → Databricks (to-direction)

| ThoughtSpot | Databricks MV YAML | Column type |
|---|---|---|
| `group_aggregate(sum(x), {dim}, query_filters())` | `expr: SUM(x) OVER (PARTITION BY dim)` | **dimension** |
| `group_aggregate(count(x), {dim}, query_filters())` | `expr: COUNT(x) OVER (PARTITION BY dim)` | **dimension** |
| `group_aggregate(average(x), {d1, d2}, query_filters())` | `expr: AVG(x) OVER (PARTITION BY d1, d2)` | **dimension** |
| `group_sum(x, dim)` | `expr: SUM(x) OVER (PARTITION BY dim)` | **dimension** |
| `group_count(x, dim)` | `expr: COUNT(x) OVER (PARTITION BY dim)` | **dimension** |
| `group_average(x, dim)` | `expr: AVG(x) OVER (PARTITION BY dim)` | **dimension** |

**Key rules:**
- LOD results are **dimensions**, not measures
- Do NOT use `AGGREGATE OVER` — it causes `PARSE_SYNTAX_ERROR`
- Do NOT use `window:` for LOD — `window` requires `semiadditive`
- Complex `group_aggregate` with `query_groups()` or multiple aggregation levels
  may still be untranslatable — log in Unmapped Report

### Databricks → TS (from-direction)

| Databricks MV (dimension) | ThoughtSpot formula |
|---|---|
| `expr: SUM(x) OVER (PARTITION BY dim)` | `group_aggregate(sum([x]), {[dim]}, query_filters())` |
| `expr: COUNT(x) OVER (PARTITION BY dim)` | `group_aggregate(count([x]), {[dim]}, query_filters())` |
| `expr: AVG(x) OVER (PARTITION BY d1, d2)` | `group_aggregate(average([x]), {[d1], [d2]}, query_filters())` |

**Live-verified 2026-07-09** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`,
A1/A2) — the ThoughtSpot side is **CONFIRMED**: `query_filters()` makes this LOD
respect user-applied filters under both a query-level pin and a model-level
`filters:` block. **Cross-platform asymmetry:** this equivalence with the Databricks
`OVER (PARTITION BY ...)` form holds only when the filter is applied as the MV's own
global `filter:` block. A Databricks consumer applying an ad hoc query-time `WHERE`
on an MV with no global `filter:` gets a filter-**blind** LOD dimension (the `WHERE`
prunes output rows only, never the window's computed value) — no `query_filters()`
form on the ThoughtSpot side reproduces that DBX-side behavior. Document this as a
DBX-side asymmetry when converting either direction, not as a translation defect.

**A3 follow-up, live-verified 2026-07-09** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A3) — that asymmetry **is
reproducible** after all, using a different third argument. `group_aggregate`'s
filter argument also accepts the documented empty-set literal `{}`
(`thoughtspot-formula-patterns.md`): `group_aggregate(sum(x), {dim}, {})` is
**blind to a search-level/query-time filter** (matches DBX's ad hoc query-time
`WHERE`-blind reading) but **still respects a model-level `filters:` block**
(matches DBX's own MV-global-`filter:`-aware reading). So the refined mapping is:

| ThoughtSpot construct | Reproduces (DBX-side) |
|---|---|
| `group_aggregate(sum(x), {dim}, query_filters())`, no model-level filter | An MV's global `filter:` (default mapping, simpler formula) |
| `group_aggregate(sum(x), {dim}, {})` + a model-level `filters:` block mirroring the MV's `filter:` | Both halves of the DBX composite: MV-`filter:`-aware AND ad hoc query-time-`WHERE`-blind |

A candidate subtraction form, `query_filters() - { [TABLE::col] }`, was
import-accepted on the TS side but did not exclude a filter pinned on a *derived*
boolean formula built from that column (the query-filter provenance tracks the
filtered column, not its underlying physical dependency) — recorded as a live
finding, not a working alternative to `{}`.

---

## Scalar Subqueries over the MV Source (verified 2026-09-28)

A budget/forecast MV caps budget to the latest actuals date with an uncorrelated
scalar subquery over **its own source table**:

```sql
SUM(revenue_gbp) FILTER (WHERE observation = 'budget'
  AND dt <= (SELECT MAX(dt) FROM <source> WHERE observation = 'current'))
```

The subquery ignores the outer query's grouping and filters. `group_aggregate` with
empty groupings **and** empty filters has that meaning for the query's grouping and
**search** filters:

| Databricks | ThoughtSpot |
|---|---|
| `(SELECT MAX(dt) FROM <source> WHERE c)` | `group_aggregate ( max ( if ( c ) then [dt] else null ) , { } , { } )` |
| `(SELECT SUM(x) FROM <source>)` | `group_aggregate ( sum ( [x] ) , { } , { } )` |

It is valid inside a row-level condition, e.g. `sum_if ( … and [dt] <= group_aggregate ( … ) , [x] )`
(number-matched against Databricks 2026-09-28, BL-316).

**Caveat — an MV with a global `filter:`.** `{ }` is search-filter-blind but
**model-filter-aware** (A3, above), and build-model mirrors the MV's `filter:` into the
model's `filters:` block. The Databricks subquery reads the *unfiltered* source, so on a
filtered MV the ThoughtSpot value is computed over fewer rows. The translator therefore
**refuses** a scalar subquery on an MV that has a global `filter:` (it lands in
`skipped[]` with the reason); move the filter into the subquery's `WHERE` so both sides
agree, then build the formula manually.

**Recognised shape only:** `( SELECT <SUM|COUNT|AVG|MIN|MAX>(<expr>) FROM <the MV's
source FQN> [WHERE <cond>] )` — no alias, join, `GROUP BY`, nested `SELECT`, comma, or
**qualified column reference** (`source.region` may correlate with the outer row, and
lifting it would turn the correlation into a tautology). `COUNT(*)` emits `count ( 1 )`.
`parse-mv` lifts it to a `__MVSCALAR_n__` placeholder and records it under the
measure's `scalar_subqueries`. Every other subquery stays untranslatable.

**Inside a windowed measure** (`window:`), the LOD cannot be used — see limit 2 in
"Databricks → TS: offsets at day and week grain, ratios" (Semi-Additive / Period-Filter
section, below). A scalar `MAX(<col>)` is emitted as `add_days ( today ( ) , -1 )` —
"the latest actuals are yesterday" — **only when `<col>` is the date column the window
is ordered by** (the one column proven to be a date; for a formula-ordered week, the
column it truncates). The `cap_assumption` annotation names the subquery's `WHERE`,
because the stand-in cannot honour it. That equals the subquery only while that data is
loaded through yesterday; on a stale load the cap drifts one day per day. Any other
aggregate, or `MAX` of any other column, inside a window is refused.

## Cross-Measure References (verified 2026-05-25)

Metric Views support referencing other measures and dimensions from within measure
expressions using `MEASURE()` and `ANY_VALUE()`.

### TS → Databricks (to-direction)

| ThoughtSpot pattern | Databricks MV `expr` |
|---|---|
| `[measure_name]` (ref to another measure) | `MEASURE(measure_name)` |
| `[lod_dimension]` (ref to LOD dim from a measure) | `ANY_VALUE(lod_dimension)` |
| `safe_divide([quantity], [category_quantity])` | `MEASURE(quantity) / ANY_VALUE(category_quantity)` |

### Databricks → TS (from-direction)

| Databricks MV `expr` | ThoughtSpot formula |
|---|---|
| `MEASURE(measure_name)` | `[measure_name]` |
| `ANY_VALUE(dimension_name)` | `[dimension_name]` |
| `MEASURE(a) / ANY_VALUE(b)` | `[a] / [b]` |

**Live-verified 2026-07-09 across query grain** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — **CONFIRMED**: this
inlining computes true ratio-of-sums, cross-platform, at every grain tested
(fine/coarse/total). No sum-of-ratios or average-of-ratios divergence found — no
formula change or grain caveat is needed.

---

## Semi-Additive / Period-Filter Functions

Databricks MV measures with a `window` field use the `semiadditive` property.
The ThoughtSpot translation depends on the `order:` dimension type:

- **`order:` is a raw date** (snapshot metric — inventory, account balance) →
  **`last_value`/`first_value`** — takes the last/first observation in each period.
  **Live-verified 2026-07-09** — see `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C7).
- **`order:` is a truncated period dimension** (flow metric — revenue, quantity) →
  **row-relative `moving_sum` LAG idiom** (see "Corrected 2026-07-09" below) — a true
  window function, not a conditional aggregate.
- **`range: cumulative`** → **`cumulative_sum`** — a true window function.
  **Live-verified 2026-07-09** — matrix C5.

**How to classify:** Look up the `order:` dimension's `expr` in the MV YAML.
If the expr is a direct column reference or `date_trunc('day', ...)`, it's a raw
date → `last_value`/`first_value`. If it uses `date_trunc('month'/'quarter'/'year', ...)`,
it's a truncated period → the row-relative `moving_sum` idiom below.

### True Semi-Additive (snapshot metrics)

#### TS → Databricks

| ThoughtSpot | Databricks MV YAML | Notes |
|---|---|---|
| `last_value(sum(m), query_groups(), {date})` | `expr: SUM(m)` + `window: [{order: raw_date_dim, semiadditive: last, range: current}]` | End-of-period snapshot |
| `first_value(sum(m), query_groups(), {date})` | `expr: SUM(m)` + `window: [{order: raw_date_dim, semiadditive: first, range: current}]` | Start-of-period snapshot |

#### Databricks → TS

| Databricks MV YAML | ThoughtSpot formula | Notes |
|---|---|---|
| `window: [{order: raw_date, semiadditive: last, range: current}]` | `last_value(sum([m]), query_groups(), {[date]})` | `order:` is a raw date dimension |
| `window: [{order: raw_date, semiadditive: first, range: current}]` | `first_value(sum([m]), query_groups(), {[date]})` | `order:` is a raw date dimension |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C7). `last` was reconfirmed
and `first` was exercised live for the first time in this repo; both matched DBX
exactly at category grain.

**Live-verified 2026-07-09 under a query-time date-range filter** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — **CONFIRMED
cross-platform**: `last_value`/`first_value` and the equivalent Databricks
`window:` measure both collapse to the last/first observation *within the
filtered range* under a query-level date-range pin, identical values at every row
including the single-surviving-row edge case. No formula change needed.

### Period Filter (flow/additive metrics)

**Corrected 2026-07-09 — row-relative, not wall-clock (matrix C6/C6a,
`docs/audit/2026-07-08-dbx-window-claim-matrix.md`).** The mapping previously
documented here (`sum_if(diff_months/quarters/years([date], today())=N, [m])`) is
**wrong**: live testing (Query B1, a 3-hypothesis discriminator) proved
`range: current` + `offset` is evaluated **relative to each output row's own
period**, not anchored to wall-clock `today()`. Querying a "prior month" measure
across a multi-month trend returns a `LAG`-style shift for every row, not a
fixed-calendar-month filter — the old mapping only coincidentally matched a
single current-period snapshot query and fails for any query spanning more than
one period. `range: current` with **no** offset is simply the per-period
aggregate (`sum([m])` at the query grain) under either reading.

**Caveat:** the `moving_sum` LAG idiom below is exact only when the query returns
exactly **one row per period** in the `order:` dimension. General use (gaps or
multiple rows per period) needs a period-grain pre-aggregation first.

#### TS → Databricks

| ThoughtSpot | Databricks MV YAML | Notes |
|---|---|---|
| `sum(m)` at month/quarter/year grain | `expr: SUM(m)` + `window: [{order: month_dim, range: current, semiadditive: last}]` | Current period, no offset |
| `moving_sum([m], 1, -1, [date])` | `expr: SUM(m)` + `window: [{order: month_dim, semiadditive: last, range: current, offset: -1 month}]` | Previous month (LAG(1)) — Live-verified 2026-07-09 |
| `moving_sum([m], 1, -1, [date])` | `expr: SUM(m)` + `window: [{order: quarter_dim, semiadditive: last, range: current, offset: -3 month}]` | Previous quarter (LAG(1) at quarter grain) — Deferred (C8), not separately live-tested |
| `moving_sum([m], 12, -12, [date])` | `expr: SUM(m)` + `window: [{order: month_dim, semiadditive: last, range: current, offset: -1 year}]` | Same month last year (LAG(12)). The `-12 month` spelling was number-matched 2026-09-28 (BL-316); the `-1 year` spelling is the same N and is not separately tested |
| `moving_sum([m], 1, -1, [date])` | `expr: SUM(m)` + `window: [{order: year_dim, semiadditive: last, range: current, offset: -1 year}]` | Previous year (LAG(1) at year grain) — Deferred (C8), not separately live-tested |

#### ⚠ Period comparisons are NOT translated by default (BL-322, 2026-09-28)

**`range: current` + `offset:` has no safe ThoughtSpot formula.** The Metric View counts
calendar **periods** of its `order:` dimension; `moving_sum ( m , N , -N , order )` counts
**rows of the query result**, and a formula cannot see the grain it is queried at. Measured
against Databricks on a 136-measure budget/forecast MV (ts-model-parity metric matrix, 2,161
outcomes):

| Query | Metric View | row-lag formula |
|---|---|---|
| grouped by the window's own order dimension, every period present | prior-period value | **same** (exact) |
| + extra non-time dimensions (month × vertical) | prior-period value per group | **same** |
| coarser grain (`py_daily` by month) | prior-year value of each month's last day (`semiadditive: last`) | **NULL** |
| finer grain (`py_monthly` by date) | the month's value on every day | **the value N DAYS back — a plausible wrong number** |
| a period missing in a group | still the correct prior period | **silently shifted to the wrong period** |

So `ts databricks translate-formulas` now puts every such measure in `skipped[]` with the
reason. The correct translation is a **date-shifted join** — the fact role-played on
`date + offset` against a shared date dimension — which is additive and right at every grain
(design pending, BL-322). `--allow-row-lag` restores the approximation below for a user who
will only query at the window's own grain; every emitted measure then carries a
`row_lag_approximation` annotation. The `trailing` / `leading` mappings share the same
rows-vs-periods root cause (BL-098 density); BL-322 tracks treating them the same way.

#### Databricks → TS: offsets at day and week grain, ratios (2026-09-28, BL-315/BL-316) — opt-in only, `--allow-row-lag`

All rows below were number-matched against a Databricks Metric View on dense data
(`agent_skills.business_forecast.business_reporting_mv`, nebula-ts-semview):

| Databricks MV YAML | ThoughtSpot formula | Notes |
|---|---|---|
| `order: <raw date>`, `range: current`, `offset: -364 day` | `moving_sum ( [m] , 364 , -364 , [date] )` | **BL-315:** `ts-cli` before 0.149.0 emitted `last_value(…)` here with the offset dropped — the "prior year" measure returned this year's number. An `offset:` always means LAG; `last_value` is only for an offset-less raw-date window. `-N week` at day grain lags 7N rows; a month/quarter/year offset at day grain is not a fixed row count and is refused |
| `order: week` where `week` is a date-shifted truncation (`DATE_ADD(DATE_TRUNC('WEEK', DATE_ADD(dt, 3)), -3)`), `offset: -364 day` | `moving_sum ( [m] , 52 , -52 , [formula_Week] )` | Order by the **dimension's own formula**. Ordering by `[dt]` forces the query to daily grain and returns NULL — `start_of_month(dt)` is a recognised bucket of `dt`, a shifted week is not. Every week-grain order is formula-ordered (a plain `DATE_TRUNC('WEEK', dt)` is untested and carries a pending-verification note) |
| `expr: SUM(a) / NULLIF(SUM(b), 0)` + any `window:` | `safe_divide ( moving_sum ( [a] , … ) , moving_sum ( [b] , … ) )` | The window applies to **every** aggregate. Same for `last_value`/`cumulative_sum`/trailing ranges. A **nested** aggregate (`SUM(SUM(a))`) is refused — it would be windowed twice |
| `expr: SUM(x) FILTER (WHERE c)` + `window:` | `moving_sum ( if ( c ) then [x] else null , … )` | FILTER-equivalent: non-matching rows contribute NULL |

**Two ThoughtSpot limits (live-probed 2026-09-28):**

1. **A lag reads only rows that survive the query's filters.** Filter a query to
   May–Sep 2026 and a prior-year `moving_sum` LAG returns NULL; the Databricks
   window reaches outside the filter and returns a value. The prior period must be
   inside the query's date range. Every LAG translation carries this in its
   `one_row_per_period` annotation.
2. **`group_aggregate` cannot sit inside a `moving_sum`.** Every variant fails at query
   compile with `Failed to transform QuerySpec`. So a scalar subquery used *inside a
   windowed measure* is emitted as `add_days ( today ( ) , -1 )` — see "Scalar
   Subqueries over the MV Source" (above).

**Growth % formulas (MoM, YoY)** inline both period expressions directly — no
cross-formula references needed:

```
// MoM growth %
safe_divide(
  sum([m]) - moving_sum([m], 1, -1, [date]),
  moving_sum([m], 1, -1, [date])
) * 100

// YoY growth % (month grain)
safe_divide(
  sum([m]) - moving_sum([m], 12, -12, [date]),
  moving_sum([m], 12, -12, [date])
) * 100
```

#### Databricks → TS

| Databricks MV YAML | ThoughtSpot formula | Notes |
|---|---|---|
| `window: [{range: current}]`, `order:` is truncated month/quarter/year | `sum([m])` at the query grain | Current period, no offset |
| `window: [{range: current, offset: -1 month}]` | `moving_sum([m], 1, -1, [date])` | Previous month (LAG(1)) — **Live-verified 2026-07-09** |
| `window: [{range: current, offset: -3 month}]`, quarter grain | `moving_sum([m], 1, -1, [date])` | Previous quarter — Deferred (C8), not separately live-tested at quarter grain |
| `window: [{range: current, offset: -1 year}]`, month grain | `moving_sum([m], 12, -12, [date])` | Same month last year — Deferred (C8), not separately live-tested |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C6, C6a). Verified for N=1:
`moving_sum([m], 1, -1, [date])` matched DBX's prior-period value exactly at
every row, including the out-of-range `NULL` at the earliest row (no "prior"
period exists yet). N=12 (`-1 year` at month grain) and the quarter/year-grain
rows are the documented extrapolation of the same verified idiom — flagged as
deferred (C8) rather than separately live-tested.

### Cumulative

| Direction | From | To |
|---|---|---|
| TS → Databricks | `cumulative_sum(m, d)` | `expr: SUM(m)` + `window: [{order: d, semiadditive: last, range: cumulative}]` |
| Databricks → TS | `window: [{range: cumulative}]` | `cumulative_sum([m], [d])` |

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C5): matched DBX's running
total at every row of the fixture.

### Key rules

- `semiadditive` is REQUIRED when `window` is present. Using `window`
  without `semiadditive` fails with `Missing required creator property 'semiadditive'`.
- **Classify by `order:` dimension type**: raw date → `last_value`/`first_value`;
  truncated period → the row-relative `moving_sum` LAG idiom. The `order:`
  dimension's `expr` in the MV YAML tells you which.
- The `offset` shifts the period anchor by a row count N (offset value ÷ the
  `order:` dimension's own period size — `-1 month` at month grain = N=1;
  `-1 year` at month grain = N=12): `moving_sum([m], N, -N, [date])`. This is
  **row-relative**, not wall-clock — see "Corrected 2026-07-09" above.
- `range: cumulative` remains a true window function (`cumulative_sum`).

---

## safe_divide Pattern (verified 2026-05-25)

ThoughtSpot `safe_divide` has no direct Databricks equivalent. Use `COALESCE/NULLIF`:

| Direction | From | To |
|---|---|---|
| TS → Databricks | `safe_divide(sum(a), sum(b))` | `COALESCE(SUM(a) / NULLIF(SUM(b), 0), 0)` |
| Databricks → TS | `COALESCE(x / NULLIF(y, 0), 0)` | `safe_divide(x, y)` |
| Databricks → TS | `x / NULLIF(y, 0)` | `safe_divide(x, y)` |

---

## Untranslatable Patterns

These ThoughtSpot formula patterns cannot be translated to Databricks MV expressions:

| Pattern | Reason |
|---|---|
| Parameter references: `[Param]` (no `::`) | **Not yet auto-translated** (deferred — audit finding 13.2). MV `parameters:` DOES exist as a GA construct (Runtime 18.2+) — this is a conversion-tooling gap, not a platform limitation; see [databricks-metric-view.md](../../schemas/databricks-metric-view.md#parameters-block-ga--runtime-182) |
| `last_value(...)` / `first_value(...)` — when NOT a semi-additive pattern | Only translatable when the formula matches the semi-additive pattern `last_value(sum([m]), query_groups(), {[d]})` → `window: [{semiadditive: last}]`. Other uses are untranslatable. |
| Complex `group_aggregate(...)` with `query_groups()` modifier | Cannot express the query-group-aware variant |
| `AGGREGATE OVER` in YAML `expr` | Causes `PARSE_SYNTAX_ERROR` — use dimension window function instead |
| Nested formula references beyond 3 levels | Complexity limit |
| Circular formula references | Cannot resolve |

These Databricks MV expression patterns cannot be translated to ThoughtSpot formulas:

| Pattern | Reason |
|---|---|
| Subquery in `expr`: `(SELECT ... FROM ...)` — any shape **other than** the whole-table scalar over the MV's own source (see "Scalar Subqueries over the MV Source") | ThoughtSpot formulas cannot contain SQL subqueries |
| `source:` as SELECT statement: `source: (SELECT ... FROM ...)` | Not a table reference — requires creating a Databricks VIEW first |
| Correlated window with non-standard frame | No direct TS equivalent for arbitrary window frames |

When encountering untranslatable patterns:
1. Omit the column from the output (MV YAML or TS Model TML)
2. Log in the Unmapped Report with the original expression and reason

### SQL Comment Stripping

Databricks MV `expr` fields may contain SQL comments:
- `-- line comment` at end of expression
- `/* block comment */` inline

Strip all SQL comments before translating. They are not meaningful to ThoughtSpot
formulas and will cause parse errors if included.

---

## Databricks → ThoughtSpot (Reverse Direction)

Common Databricks SQL patterns found in MV `expr` fields and their ThoughtSpot
formula equivalents:

| Databricks SQL (in MV expr) | ThoughtSpot formula |
|---|---|
| `date_trunc('day', col)` | `date(col)` |
| `date_trunc('week', col)` | `start_of_week(col)` |
| `date_trunc('month', col)` | `start_of_month(col)` |
| `date_trunc('quarter', col)` | `start_of_quarter(col)` |
| `date_trunc('year', col)` | `start_of_year(col)` |
| `date_trunc('hour', col)` | `sql_date_time_op("DATE_TRUNC('HOUR', {0})", col)` — no native TS function returns DATETIME truncated to the hour; `start_of_hour` returns TIME only |
| `date_trunc('minute', col)` | `sql_date_time_op("DATE_TRUNC('MINUTE', {0})", col)` — same as hour; `start_of_min` returns TIME only |
| `date_trunc('second', col)` | `sql_date_time_op("DATE_TRUNC('SECOND', {0})", col)` — no native TS equivalent |
| `CASE WHEN x THEN y WHEN z THEN w ELSE v END` | `if (x) then y else if (z) then w else v` |
| `COALESCE(a, b)` | `if (a != null) then a else b` |
| `CONCAT(a, ' ', b)` | `concat(a, ' ', b)` |
| `DATEDIFF(end, start)` | `diff_days(start, end)` — arg order reversed |
| `DATEDIFF(MONTH, start, end)` | `diff_months(start, end)` — 3-arg form; swap start/end for TS — **semantic gap:** Databricks counts complete months, `diff_months` counts month boundaries (live-verified 2026-10-06), so Jan 31 → Feb 1 is 0 in Databricks and 1 in ThoughtSpot |
| `DATEDIFF(DAY, start, end)` | `diff_days(start, end)` — 3-arg form; swap start/end for TS |
| `MONTHS_BETWEEN(end, start)` | `diff_months(start, end)` — arg order reversed |
| `EXTRACT(YEAR FROM d)` | `year(d)` |
| `EXTRACT(MONTH FROM d)` | `month_number(d)` |
| `EXTRACT(DAY FROM d)` | `day(d)` |
| `EXTRACT(HOUR FROM ts)` | `hour_of_day(ts)` |
| `YEAR(d)` | `year(d)` |
| `MONTH(d)` | `month_number(d)` |
| `DAYOFWEEK(d)` | `day_number_of_week(d)` — Databricks 1=Sun, TS 1=Mon; `day_of_week(d)` also exists but returns the name — **a rename is wrong on every day** (BL-334): the exact form is `mod ( day_number_of_week ( d ) , 7 ) + 1` (TS fixed 1 = Monday, live-verified 2026-10-06) |
| `ROUND(x, d)` | `round(x, 10^-d)` — `2` → `0.01`, `0` → `1`, `-2` → `100`; non-literal `d` → `sql_double_op ( "ROUND({0}, {1})" , x , d )` (row-level only). Never `round(x, d)` (BL-331) |
| `CAST(x AS type)` | Depends on target type; often implicit in TS |
| `x / NULLIF(y, 0)` | `safe_divide(x, y)` |
| `COALESCE(x / NULLIF(y, 0), 0)` | `safe_divide(x, y)` |
| `x IS NULL` | `isnull(x)` |
| `NOT expr` | `not(expr)` |
| `x IN (a, b, c)` | `( [x] = a or [x] = b or [x] = c )` — the form the translator emits; `in(x, a, b, c)` is rejected at import (`thoughtspot-formula-patterns.md`). The to-direction row near the top of this file still shows `in(…)` — BL-317 |
| `x NOT IN (a, b)` | `( [x] != a and [x] != b )` — Live-verified 2026-09-28 (BL-316). A `NULL` in the list is refused: SQL makes that `NOT IN` never true, which the `!=` chain would not reproduce |
| `COUNT(*)` | `count ( 1 )` — TS has no `COUNT(*)` syntax |
| `AGG(x) FILTER (WHERE cond)` | `agg_if ( cond , [x] )` — native `*_if` function; see Conditional Aggregates section. Applies to **every** aggregate call in an expression, e.g. `SUM(a) FILTER (WHERE c) / NULLIF(SUM(b), 0)` → `safe_divide ( sum_if ( c , [a] ) , sum ( [b] ) )` (BL-316, 2026-09-28) |
| `SUM(SUM(x)) OVER ()` | `group_aggregate ( sum ( [x] ) , { } , query_filters ( ) )` — grand total of the result rows, filters kept (share-of-total denominators). Only an empty `OVER ()`, and only SUM of SUM/COUNT, MIN of MIN, MAX of MAX. The argument must be exactly one aggregate call — `SUM(SUM(a)/SUM(b)) OVER ()` is refused. Live-verified 2026-09-28 (BL-316) |
| `SUM(x) OVER (PARTITION BY dim)` | `group_aggregate(sum([x]), {[dim]}, query_filters())` — LOD dimension |
| `MEASURE(name)` | `[name]` — cross-measure reference |
| `ANY_VALUE(name)` | `[name]` — dimension reference from measure |
| `MEASURE(a) / ANY_VALUE(b)` | `[a] / [b]` — cross-measure ratio |
| `(SELECT MAX(dt) FROM <MV source> WHERE c)` | `group_aggregate ( max ( if ( c ) then [dt] else null ) , { } , { } )` — see "Scalar Subqueries over the MV Source" |
| `(SELECT ... FROM ...)` (any other shape) | **Untranslatable** — subquery; log in Unmapped Report |

**LOD row above (A1/A2) and cross-measure/ratio rows (B1)** — see the fuller LOD
Functions and Cross-Measure References sections earlier in this file for the
live-verified 2026-07-09 caveat/citation (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`):
the LOD row's filter-awareness holds for a Databricks MV's own global `filter:`
only, not for a consumer's ad hoc query-time `WHERE`; the cross-measure/ratio rows
are CONFIRMED cross-platform at every grain, no caveat needed.

### Implementation Notes

**Date literals with hyphens:** A bare `'2024-05-01'` in a ThoughtSpot formula is parsed
as `'2024' - 05 - 01` (subtraction). Wrap in `to_date('2024-05-01', 'yyyy-MM-dd')` —
hyphens are fine inside `to_date()` because the parser treats the first argument as a
string, not arithmetic. No reformatting needed — keep the original date string as-is
and provide a matching format pattern.

**Operator regex ordering:** When tokenising SQL operators for translation, match multi-character
operators before single-character ones: `<=|>=|!=|<>|<|>|=`. If `<` is matched before `<=`,
the `=` is left orphaned and the formula breaks.

**`moving_sum` / `moving_average` — no nested aggregates:** ThoughtSpot window functions
(`moving_sum`, `moving_average`, `cumulative_sum`) already aggregate internally. Do NOT
wrap `sum()` or `average()` inside them. Strip the outer aggregate and pass the raw
column expression: `moving_sum([col], N, -1, [date])`, not `moving_sum(sum([col]), N, -1, [date])`.

**`count(distinct col)` — use `unique count`:** ThoughtSpot does not support `count(distinct ...)`.
Always express a distinct count as a **`formulas[]` entry** with `unique count ( [col] )` (with a
space, not underscore) plus its paired `columns[]` entry. **Never** set
`aggregation: COUNT_DISTINCT` on a physical-column `columns[]` entry — that silently flips the
column's `column_type` from MEASURE to ATTRIBUTE (invariant **I5**). This matches the Snowflake
mapping (`ts-snowflake-formula-translation.md`): distinct counts are formulas, not an aggregation.
