<!-- currency: qlik — 2026-07 (Qlik Sense SaaS / ThoughtSpot Cloud 26.x) -->

# Qlik Sense → ThoughtSpot Formula Translation

The canonical Qlik→ThoughtSpot formula mapping — **199 rows** across 17 categories. This is the human-readable rendering; the machine-readable source that `ts qlik build-model` loads is `tools/ts-cli/ts_cli/qlik/data/qlik_ts_formula_map.json`.

The `ts-convert-from-qlik` skill consults this reference before declaring any Qlik expression untranslatable.

**Status legend:** `ok` = verified 1:1 mapping · `corrected` = mapping fixed against the ThoughtSpot formula reference · `verify` = could not be confirmed against docs, treat as NEEDS REVIEW.

| Status | Count |
|---|---|
| `ok` | 186 |
| `corrected` | 10 |
| `verify` | 3 |

---

## Aggregation

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| A01 | `Sum(expr)` | `sum(col)` | ok | Direct equivalent. Sums all values of a measure column. |
| A02 | `Avg(expr)` | `average(col)` | ok | ThoughtSpot uses the full word 'average'; Qlik uses the abbreviation 'Avg'. |
| A03 | `Count(expr)` | `count(col)` | ok | Counts total rows. Both include NULLs in count unless DISTINCT is used. |
| A04 | `Count(DISTINCT expr)` | `unique count(col)` | ok | ThoughtSpot uses 'unique count' as a single keyword instead of a DISTINCT modifier. |
| A05 | `Min(expr)` | `min(col)` | ok | Direct equivalent. Returns the smallest value in the aggregated set. |
| A06 | `Max(expr)` | `max(col)` | ok | Direct equivalent. Returns the largest value in the aggregated set. |
| A07 | `Stdev(expr)` | `stddev(col)` | ok | Standard deviation. ThoughtSpot spells it 'stddev'; Qlik uses 'Stdev'. |
| A08 | `Median(expr)` | `median(col)` | ok | Direct equivalent. Both return the statistical middle value. |
| A09 | `Mode(expr)` | `No direct equivalent` | ok | Qlik returns the most frequent value. ThoughtSpot has no built-in mode() function. |
| A10 | `Only(expr)` | `No direct equivalent` | ok | Qlik returns a value only if all rows in the group share one value, else NULL. ThoughtSpot has no direct equivalent. |
| A11 | `Sum(TOTAL expr)` | `group_aggregate(sum(col), {}, {})` | ok | TOTAL in Qlik ignores all chart dimensions to give a grand total. ThoughtSpot achieves this with group_aggregate using empty groupings and filters. |
| A12 | `Sum(TOTAL <dim> expr)` | `group_aggregate(sum(col), {dim}, {})` | ok | Qlik TOTAL <dim> ignores all dims except the specified one. ThoughtSpot uses group_aggregate with that dim in the groupings list. |
| A13 | `Variance(expr)` | `variance(col)` | ok | Direct equivalent. Returns the statistical variance of a measure column. |

## Conditional Aggregation

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| CA01 | `Sum(If(cond, expr))` | `sum_if(condition, col)` | ok | ThoughtSpot has a dedicated sum_if(). Qlik nests If() inside Sum() to achieve conditional summing. |
| CA02 | `Avg(If(cond, expr))` | `average_if(condition, col)` | ok | ThoughtSpot provides average_if() natively. In Qlik, nest If() inside Avg(). |
| CA03 | `Count(If(cond, expr))` | `count_if(condition, col)` | ok | ThoughtSpot has a built-in count_if(). Qlik achieves this by nesting If() inside Count(). |
| CA04 | `Count(DISTINCT If(cond,expr))` | `unique_count_if(condition, col)` | ok | ThoughtSpot has unique_count_if(). Qlik uses Count(DISTINCT If(...)). |
| CA05 | `Stdev(If(cond, expr))` | `stddev_if(condition, col)` | ok | ThoughtSpot has stddev_if() for conditional standard deviation. Qlik nests If() inside Stdev(). |
| CA06 | `Variance(If(cond, expr))` | `variance_if(condition, col)` | ok | ThoughtSpot has variance_if() natively. Qlik nests If() inside Variance(). |

## Conditional / Logical

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| CL01 | `If(cond, then, else)` | `if condition then val1 else val2` | ok | ThoughtSpot uses keyword syntax (if/then/else). Qlik uses a function call If(). Both support chained else-if. |
| CL02 | `If(c1,v1, If(c2,v2, v3))` | `if c1 then v1 else if c2 then v2 else v3` | ok | Nested conditionals. ThoughtSpot uses chained else-if keywords; Qlik nests If() calls. |
| CL03 | `If(IsNull(expr), fallback, expr)` | `ifnull(col, fallback)` | ok | ThoughtSpot has a dedicated ifnull() for null replacement in one call. Qlik requires wrapping IsNull() inside If(). |
| CL04 | `IsNull(expr)` | `isnull(col)` | ok | Direct equivalent. Both return true/1 when the value is null. |
| CL05 | `Not IsNull(expr)` | `not isnull(col)` | ok | Direct equivalent. Both check for non-null values using a not prefix. |
| CL06 | `Match(expr, val1, val2, ...)` | `col in (val1, val2, ...)` | ok | Qlik Match() returns position of match (1-based). ThoughtSpot uses the 'in' operator for membership testing — simpler and more readable. |
| CL07 | `Not Match(expr, val1, val2)` | `col not in (val1, val2, ...)` | ok | ThoughtSpot uses 'not in' operator directly. Qlik uses Not around Match(). |
| CL08 | `Mixmatch(expr, val1, val2)` | `lower(col) in (lower(val1), ...)` | ok | Qlik Mixmatch is case-insensitive Match. ThoughtSpot uses lower() on both sides to simulate. |
| CL09 | `WildMatch(expr, pattern)` | `contains(col, substr)` | ok | Qlik supports wildcard patterns with *. ThoughtSpot uses contains() for substring checks — no wildcard syntax in formulas. |
| CL10 | `Pick(n, val1, val2, ...)` | `if n=1 then val1 else if n=2 then val2 ...` | ok | Qlik Pick() selects the nth value from a list. ThoughtSpot has no Pick() — replicate with chained if/then/else. |
| CL11 | `and` | `and` | ok | Direct equivalent. Boolean AND operator — both conditions must be true. |
| CL12 | `or` | `or` | ok | Direct equivalent. Boolean OR operator — at least one condition must be true. |
| CL13 | `not` | `not` | ok | Direct equivalent. Negates a boolean condition. |

## Set Analysis

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| SA01 | `Sum({1} expr)` | `group_aggregate(sum(col), {}, {})` | ok | Qlik {1} ignores ALL user selections (grand total). ThoughtSpot group_aggregate with empty groupings/filters achieves the same result. |
| SA02 | `Sum({$} expr)` | `sum(col)` | ok | Qlik {$} is the current selection — the default. ThoughtSpot always uses the current filter context by default. |
| SA03 | `Sum({<Field={'Val'}>} expr)` | `group_aggregate(sum(col), {dim}, {col='val'})` | ok | Both allow hardcoded filter overrides. Qlik uses Set Expression {}. ThoughtSpot uses group_aggregate's third filter argument. |
| SA04 | `Sum({<Field -= {'Val'}>} expr)` | `group_aggregate(sum(col), query_groups(), query_filters() - {filter})` | ok | Qlik -= removes a value from the current selection set. ThoughtSpot has no exact -= syntax but query_filters() can be combined to control filter scope. |
| SA05 | `Sum({<Field += {'Val'}>} expr)` | `group_aggregate(sum(col), query_groups() + {dim}, query_filters())` | ok | Qlik += adds a value to the current selection. ThoughtSpot uses query_groups() + {attr} to extend grouping scope. |
| SA06 | `Sum({$<Field={'Val'}>} expr)` | `group_aggregate(sum(col), query_groups(), {col = val})` | ok | Qlik {$<>} applies an override on top of current selections. ThoughtSpot uses group_aggregate with query_groups() to inherit dims and a custom filter. |
| SA07 | `group_aggregate with query_groups()` | `group_aggregate(agg, query_groups(), query_filters())` | ok | ThoughtSpot-specific. query_groups() and query_filters() inherit the current search's dimensions and filters. No direct Qlik equivalent. |

## Cross-Level Aggregation

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| GA01 | `Aggr(Sum(measure), attr)` | `group_sum(measure, attr)` | ok | Both compute aggregation at a different grain. Qlik creates a virtual table with Aggr(); ThoughtSpot uses group_sum() directly. |
| GA02 | `Aggr(Avg(measure), attr)` | `group_average(measure, attr)` | ok | Qlik uses Aggr() wrapper around Avg(). ThoughtSpot has a dedicated group_average() function. |
| GA03 | `Aggr(Count(measure), attr)` | `group_count(measure, attr)` | ok | Qlik uses Aggr() wrapper around Count(). ThoughtSpot has a dedicated group_count() function. |
| GA04 | `Aggr(Max(measure), attr)` | `group_max(measure, attr)` | ok | Qlik uses Aggr() wrapper around Max(). ThoughtSpot has a dedicated group_max() function. |
| GA05 | `Aggr(Min(measure), attr)` | `group_min(measure, attr)` | ok | Qlik uses Aggr() wrapper around Min(). ThoughtSpot has a dedicated group_min() function. |
| GA06 | `Aggr(Stdev(measure), attr)` | `group_stddev(measure, attr)` | ok | Qlik uses Aggr() around Stdev(). ThoughtSpot has group_stddev() as a direct function. |
| GA07 | `Aggr(Count(DISTINCT m), attr)` | `group_unique_count(measure, attr)` | ok | ThoughtSpot has group_unique_count() natively. Qlik wraps Count(DISTINCT ...) inside Aggr(). |
| GA08 | `Max(Aggr(Sum(m), attr))` | `max(group_sum(measure, attr))` | ok | Nested aggregation — find max across customer totals. ThoughtSpot supports direct nesting; Qlik wraps Aggr() inside outer aggregation. |
| GA09 | `Avg(Aggr(Count(m), attr))` | `average(group_count(measure, attr))` | ok | Average orders per customer. ThoughtSpot nests group_count() inside average(); Qlik wraps Aggr() inside Avg(). |

## Cumulative

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| CU01 | `RangeSum(Above(Sum(expr),0,RowNo()))` | `cumulative_sum(measure, attr)` | ok | Running total. ThoughtSpot has dedicated cumulative_sum(). Qlik combines RangeSum() + Above(). |
| CU02 | `RangeAvg(Above(Avg(expr),0,RowNo()))` | `cumulative_average(measure, attr)` | ok | Running average. ThoughtSpot provides cumulative_average() natively. Qlik builds it with RangeAvg() + Above(). |
| CU03 | `RangeMax(Above(Max(expr),0,RowNo()))` | `cumulative_max(measure, attr)` | ok | Running maximum. ThoughtSpot has cumulative_max() natively. Qlik uses RangeMax() + Above(). |
| CU04 | `RangeMin(Above(Min(expr),0,RowNo()))` | `cumulative_min(measure, attr)` | ok | Running minimum. ThoughtSpot has cumulative_min() natively. Qlik uses RangeMin() + Above(). |

## Inter-Record (Qlik-specific)

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| IR01 | `Above(expr, offset)` | `No direct equivalent` | ok | Qlik returns value from N rows above current row. ThoughtSpot has no row-reference function — use date-based period comparisons. |
| IR02 | `Below(expr, offset)` | `No direct equivalent` | ok | Qlik returns value from N rows below current row. ThoughtSpot has no row-level reference function. |
| IR03 | `Top(expr, offset)` | `No direct equivalent` | ok | Qlik returns value from the top (first) row of the current column segment. No direct ThoughtSpot equivalent. |
| IR04 | `Bottom(expr, offset)` | `No direct equivalent` | ok | Qlik returns value from the bottom (last) row. No direct ThoughtSpot equivalent. |
| IR05 | `Before(expr)` | `No direct equivalent` | ok | Qlik pivot-only — returns value from previous column in pivot table. ThoughtSpot has no column-reference inter-record function. |
| IR06 | `After(expr)` | `No direct equivalent` | ok | Qlik pivot-only — returns value from next column. No ThoughtSpot equivalent. |
| IR07 | `First(expr)` | `No direct equivalent` | ok | Qlik returns value from the first column of current pivot row segment. No ThoughtSpot equivalent. |
| IR08 | `Last(expr)` | `No direct equivalent` | ok | Qlik returns value from last column of current pivot row. No ThoughtSpot equivalent. |
| IR09 | `Column(n)` | `No direct equivalent` | ok | Qlik returns value of the nth measure column in a straight table. ThoughtSpot has no column-index reference — use named columns. |
| IR10 | `RowNo()` | `No direct equivalent` | ok | Qlik returns current row number in chart table. ThoughtSpot has no RowNo() concept in formula context. |
| IR11 | `NoOfRows()` | `count(col)` | ok | Qlik returns total row count of current chart segment. ThoughtSpot's count() on a key column approximates total row count. |

## Script / Load (Qlik-specific)

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| SC01 | `Peek(field, row, table)` | `No direct equivalent` | ok | Qlik script function that looks up a previously loaded row's value. ThoughtSpot formulas operate on already-loaded data — handle row-lookups in ETL. |
| SC02 | `Lookup(ret_fld, match_fld, match_val, table)` | `No direct equivalent` | ok | Qlik script VLOOKUP across tables. ThoughtSpot handles multi-table lookups through data model/worksheet joins — not in formula syntax. |
| SC03 | `Previous(expr)` | `No direct equivalent` | ok | Qlik script function returning previous row's value during data load. ThoughtSpot has no sequential row reference in formula context. |
| SC04 | `Exists(field, expr)` | `No direct equivalent` | ok | Qlik script checks if a value exists in a previously loaded field. In ThoughtSpot, use data model joins or worksheet-level filters. |
| SC05 | `ApplyMap(mapname, expr, default)` | `if col = 'val1' then 'mapped1' else if ...` | ok | Qlik script maps values using a mapping table. ThoughtSpot replicates with if/then/else chains or pre-maps in the data pipeline. |
| SC06 | `MapSubString(mapname, expr)` | `replace(col, old, new)` | ok | Qlik replaces substrings using a mapping table. ThoughtSpot's replace() substitutes fixed values; for complex mappings use ETL. |
| SC07 | `FieldValue(field, n)` | `No direct equivalent` | ok | Qlik returns the nth distinct value of a field. ThoughtSpot has no field-enumeration function in formula context. |
| SC08 | `FieldIndex(field, value)` | `No direct equivalent` | ok | Qlik returns the position of a value in a field's value list. No ThoughtSpot equivalent. |

## Date

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| D01 | `Year(date)` | `year(date_col)` | ok | Direct equivalent. Both extract the 4-digit year from a date column. |
| D02 | `Month(date)` | `month(date_col)` | ok | Qlik returns month name (e.g. 'Jan'). ThoughtSpot returns numeric month (1-12) by default. |
| D03 | `Day(date)` | `day(date_col)` | ok | Direct equivalent. Both extract the day of month (1-31). |
| D04 | `Quarter(date)` | `quarter(date_col)` | ok | Direct equivalent. Both return quarter number (1-4). |
| D05 | `Week(date)` | `week_number_of_year(date_col)` | ok | Both return ISO week number. Naming differs: Qlik uses Week(); ThoughtSpot uses week_number_of_year(). |
| D06 | `Weekday(date)` | `day_of_week(date_col)` | ok | Qlik returns a number (0=Mon, 6=Sun). ThoughtSpot returns the day name (e.g. 'Monday'). |
| D07 | `WeekYear(date)` | `year(date_col)` | ok | Qlik returns the year the ISO week belongs to (can differ near year boundaries). ThoughtSpot year() returns calendar year — may differ for week 53. |
| D08 | `Hour(time)` | `hour(date_col)` | ok | Direct equivalent. Both extract the hour (0-23) from a datetime column. |
| D09 | `Minute(time)` | `minute(date_col)` | ok | Direct equivalent. Both extract the minute (0-59). |
| D10 | `Second(time)` | `second(date_col)` | ok | Direct equivalent. Both extract seconds (0-59). |
| D11 | `Today()` | `today()` | ok | Direct equivalent. Both return today's date with no time component. |
| D12 | `Now()` | `now()` | ok | Direct equivalent. Both return the current date and time as a timestamp. |
| D13 | `MonthStart(date)` | `start_of_month(date_col)` | ok | Both return the first day of the month. Different naming but identical behavior. |
| D14 | `MonthEnd(date)` | `No direct equivalent` | ok | Qlik has built-in MonthEnd(). ThoughtSpot has no end-of-month function — workaround: start of next month minus 1 day. |
| D15 | `QuarterStart(date)` | `start_of_quarter(date_col)` | ok | Direct equivalent behavior. Naming convention differs. |
| D16 | `QuarterEnd(date)` | `No direct equivalent` | ok | Qlik has QuarterEnd(). ThoughtSpot has no equivalent — workaround: start of next quarter minus 1 day. |
| D17 | `YearStart(date)` | `start_of_year(date_col)` | ok | Direct equivalent behavior. Different naming convention only. |
| D18 | `YearEnd(date)` | `No direct equivalent` | ok | Qlik has YearEnd(). ThoughtSpot has no equivalent — workaround: start of next year minus 1 day. |
| D19 | `WeekStart(date)` | `start_of_week(date_col)` | ok | Both return the start of the week. Naming differs; behavior is equivalent. |
| D20 | `WeekEnd(date)` | `No direct equivalent` | ok | Qlik has WeekEnd(). ThoughtSpot workaround: add 6 days to start_of_week(). |
| D21 | `AddMonths(date, n)` | `add_months(date_col, n)` | ok | Direct equivalent. Both add or subtract months. Use negative n to go backward. |
| D22 | `AddYears(date, n)` | `add_years(date_col, n)` | corrected | ThoughtSpot has a native add_years(). No add_months(date,12) workaround needed. |
| D23 | `Age(date, ref_date)` | `(today() - date_col) / 365` | ok | Qlik Age() returns exact age in years. ThoughtSpot approximates age via date subtraction divided by 365. |
| D24 | `NetworkDays(start, end)` | `diff_days(date1, date2)` | corrected | Qlik NetworkDays() excludes weekends and optionally holidays. ThoughtSpot date_diff() returns total calendar days only — no business day logic. |
| D25 | `Date(expr, format)` | `to_date(col, format)` | ok | Both convert a value to a date. Format strings differ: Qlik uses 'YYYY-MM-DD'; ThoughtSpot uses strftime '%Y-%m-%d'. |
| D26 | `Timestamp(expr, format)` | `to_date(col, format)` | ok | Qlik Timestamp() formats a datetime as a string. ThoughtSpot uses to_date() for parsing strings into dates. |
| D27 | `DayStart(date)` | `date_trunc(date_col, 'day')` | verify | Qlik DayStart() returns midnight of the given date. ThoughtSpot date_trunc to 'day' is the equivalent. |
| D28 | `MakeDate(year, month, day)` | `to_date(concat(to_string(y),'-',to_string(m),'-',to_string(d)), '%Y-%m-%d')` | ok | Qlik has dedicated MakeDate() to construct a date from parts. ThoughtSpot workaround uses concat + to_date. |
| D29 | `InYear(date, base_date, year_offset)` | `year(date_col) = year(today())` | ok | Qlik InYear() checks if a date falls in a relative year. ThoughtSpot replicates by comparing year() extractions. |
| D30 | `InMonth(date, base_date, month_offset)` | `year(date_col) = year(today()) and month(date_col) = month(today())` | ok | Qlik InMonth() checks if a date is in the same month as the base. ThoughtSpot matches both year and month components. |
| D31 | `InWeek(date, base_date, week_offset)` | `start_of_week(date_col) = start_of_week(today())` | ok | Qlik InWeek() checks if a date is in the same week as the base. ThoughtSpot compares start_of_week() values. |
| D32 | `InQuarter(date, base_date, qtr_offset)` | `start_of_quarter(date_col) = start_of_quarter(today())` | ok | Qlik InQuarter() checks if a date falls in the same quarter. ThoughtSpot compares start_of_quarter() values. |
| D33 | `InYearToDate(date, base_date, year_offset)` | `date_col >= start_of_year(today()) and date_col <= today()` | ok | Qlik InYearToDate() checks if a date falls within the YTD window. ThoughtSpot uses a range comparison from start_of_year to today. |
| D34 | `date_diff (subtraction)` | `diff_days(date1, date2)` | corrected | Qlik computes date difference by simple subtraction. ThoughtSpot uses the explicit date_diff() function. Both return days. |
| D35 | `MakeTime(h, m, s)` | `No direct equivalent` | ok | Qlik constructs a time value from hours/minutes/seconds. ThoughtSpot has no MakeTime() — build a string and parse with to_date(). |
| D36 | `AddDays (via arithmetic)` | `add_days(date_col, n)` | ok | Qlik adds days via arithmetic (date + n). ThoughtSpot uses the explicit add_days() function. |

## String

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| S01 | `Len(str)` | `len(col)` | ok | Direct equivalent. Both return the character length of the string. |
| S02 | `Upper(str)` | `sql_string_op('UPPER({0})', col)` | corrected | ThoughtSpot has no native `upper()` in formula context — use the SQL passthrough, same as the Tableau converter's UPPER handling. |
| S03 | `Lower(str)` | `sql_string_op('LOWER({0})', col)` | corrected | ThoughtSpot has no native `lower()` in formula context — use the SQL passthrough, same as the Tableau converter's LOWER handling. |
| S04 | `Capitalize(str)` | `No direct equivalent` | ok | Qlik Capitalize() converts to title case. ThoughtSpot has no built-in capitalize — combine upper() on first char and lower() on the rest. |
| S05 | `Trim(str)` | `trim(col)` | ok | Direct equivalent. Removes leading and trailing whitespace. |
| S06 | `LTrim(str)` | `No direct equivalent` | ok | Qlik LTrim() removes only leading spaces. ThoughtSpot trim() removes both sides — no left-only trim available. |
| S07 | `RTrim(str)` | `No direct equivalent` | ok | Qlik RTrim() removes only trailing spaces. ThoughtSpot trim() removes both sides — no right-only trim available. |
| S08 | `Left(str, n)` | `substr(col, 1, n)` | ok | Qlik has dedicated Left(). ThoughtSpot uses substr() starting at position 1 to replicate Left(). |
| S09 | `Right(str, n)` | `substr(col, len(col)-n+1, n)` | ok | Qlik has dedicated Right(). ThoughtSpot combines substr() and len() to extract trailing characters. |
| S10 | `Mid(str, start, n)` | `substr(col, start, n)` | ok | Direct equivalent (different name). Qlik Mid() maps exactly to ThoughtSpot substr(). Both are 1-indexed. |
| S11 | `Replace(str, old, new)` | `replace(col, old, new)` | ok | Direct equivalent. Both replace all occurrences of a substring. |
| S12 | `Index(str, substr, n)` | `No direct equivalent` | verify | Qlik returns position of nth occurrence of a substring. ThoughtSpot has no substring-position function. |
| S13 | `SubField(str, delim, n)` | `No direct equivalent` | ok | Qlik splits a string on a delimiter and returns the nth token. ThoughtSpot has no token-split function. |
| S14 | `Concat(expr, delimiter) [aggregating]` | `concat(str1, str2, ...) [row-level]` | ok | DIFFERENT behavior: Qlik Concat() aggregates many row values into one string (like GROUP_CONCAT). ThoughtSpot concat() joins values within the same row — different use case. |
| S15 | `PurgeChar(str, chars)` | `replace(replace(replace(col,'(',''),')',''),'-','')` | ok | Qlik PurgeChar() removes a set of specified characters in one call. ThoughtSpot requires chained replace() calls — one per character. |
| S16 | `KeepChar(str, chars)` | `No direct equivalent` | ok | Qlik KeepChar() retains only specified characters. ThoughtSpot has no equivalent — handle in ETL. |
| S17 | `Repeat(str, n)` | `No direct equivalent` | ok | Qlik repeats a string n times. ThoughtSpot has no Repeat() function. |
| S18 | `Ord(str)` | `No direct equivalent` | ok | Qlik returns the ASCII code of the first character. ThoughtSpot has no Ord()/ASCII() function. |
| S19 | `Chr(n)` | `No direct equivalent` | ok | Qlik converts an ASCII code to a character. ThoughtSpot has no Chr() function. |
| S20 | `Hash128(expr)` | `No direct equivalent` | ok | Qlik generates a 128-bit hash of a value. ThoughtSpot has no hash function in formula context. |
| S21 | `Hash256(expr)` | `No direct equivalent` | ok | Qlik generates a 256-bit hash (SHA-256). ThoughtSpot has no hash function in formulas. |
| S22 | `TextBetween(str, start_delim, end_delim)` | `No direct equivalent` | ok | Qlik extracts text between two delimiter strings. ThoughtSpot requires complex substr logic. |
| S23 | `N/A — use WildMatch(str, 'prefix*')` | `starts_with(col, prefix)` | ok | ThoughtSpot has dedicated starts_with(). Qlik uses WildMatch with * at end: WildMatch(str, 'prefix*'). |
| S24 | `N/A — use WildMatch(str, '*.suffix')` | `ends_with(col, suffix)` | ok | ThoughtSpot has dedicated ends_with(). Qlik uses WildMatch with * at start: WildMatch(str, '*.suffix'). |
| S25 | `WildMatch(str, '*substr*')` | `contains(col, substr)` | ok | ThoughtSpot has dedicated contains(). Qlik uses WildMatch with * on both sides for substring checking. |
| S26 | `Evaluate(expr_string)` | `No direct equivalent` | ok | Qlik Evaluate() parses and executes a string as an expression at runtime. ThoughtSpot has no dynamic expression evaluation. |
| S27 | `Num(expr, format) [display]` | `to_string(col)` | ok | Qlik Num() formats a number as a display string. ThoughtSpot to_string() converts to string — control display formatting in visualization settings. |

## Numeric / Math

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| N01 | `Abs(x)` | `abs(col)` | ok | Direct equivalent. Returns the absolute (non-negative) value. |
| N02 | `Round(x, n)` | `round(col, n)` | ok | Qlik second arg is rounding interval (0.01 = 2 decimals). ThoughtSpot uses the number of decimal places directly. |
| N03 | `Floor(x)` | `floor(col)` | ok | Direct equivalent. Rounds down to the nearest integer. |
| N04 | `Ceil(x)` | `ceil(col)` | ok | Direct equivalent. Rounds up to the nearest integer. |
| N05 | `Pow(base, exp)` | `pow(base, exp)` | ok | Direct equivalent. Raises base to the power of exponent. |
| N06 | `Sqrt(x)` | `sqrt(col)` | ok | Direct equivalent. Returns the square root. |
| N07 | `Log(x)` | `ln(col)` | ok | Qlik Log() is natural log (base e). ThoughtSpot names it ln(). ThoughtSpot also has log10() for base-10. |
| N08 | `Log10(x)` | `log10(col)` | ok | Direct equivalent. Both return the base-10 logarithm. |
| N09 | `Exp(x)` | `No direct equivalent` | verify | Qlik Exp() returns e raised to the power of x. ThoughtSpot has no Exp() — approximate with pow(2.71828, x). |
| N10 | `Mod(x, y)` | `mod(col, divisor)` | ok | Direct equivalent. Returns remainder after division — useful for alternating row logic. |
| N11 | `Div(x, y)` | `floor(col / divisor)` | ok | Qlik Div() returns integer quotient. ThoughtSpot uses floor(x/y) to replicate integer division. |
| N12 | `Frac(x)` | `col - floor(col)` | ok | Qlik Frac() returns fractional part (3.75 → 0.75). ThoughtSpot workaround: subtract floor() from the value. |
| N13 | `Sign(x)` | `if col > 0 then 1 else if col < 0 then -1 else 0` | ok | Qlik Sign() returns -1, 0, or 1. ThoughtSpot has no Sign() — replicate with if/then/else. |
| N14 | `Odd(x)` | `mod(col, 2) != 0` | ok | Qlik Odd() returns true if integer is odd. ThoughtSpot replicates with mod(x,2) != 0. |
| N15 | `Even(x)` | `mod(col, 2) = 0` | ok | Qlik Even() returns true if integer is even. ThoughtSpot replicates with mod(x,2) = 0. |
| N16 | `RangeSum(v1, v2, ...)` | `col1 + col2 + col3 + col4` | ok | Qlik RangeSum() sums arguments (NULLs treated as 0). ThoughtSpot uses direct arithmetic — wrap with ifnull(col,0) to handle NULLs. |
| N17 | `RangeMax(v1, v2, ...)` | `if Q1>=Q2 and Q1>=Q3 ... then Q1 ...` | ok | Qlik RangeMax() finds max across a list of arguments (row-level). ThoughtSpot max() is an aggregate — use nested if/then/else for row-level multi-column max. |
| N18 | `RangeMin(v1, v2, ...)` | `if Q1<=Q2 and Q1<=Q3 then Q1 ...` | ok | Qlik RangeMin() finds min across a list of arguments (row-level). ThoughtSpot min() is an aggregate — use if/then/else for row-level minimum. |
| N19 | `RangeAvg(v1, v2, ...)` | `(col1 + col2 + col3 + col4) / 4` | ok | Qlik RangeAvg() averages a list. ThoughtSpot: sum divided by count — wrap each with ifnull(col,0). |
| N20 | `Combination(n, k)` | `No direct equivalent` | ok | Qlik computes combinations (n choose k). ThoughtSpot has no combinatorial math functions. |
| N21 | `Permutation(n, k)` | `No direct equivalent` | ok | Qlik computes permutations. ThoughtSpot has no permutation function. |
| N22 | `Fabs(x)` | `abs(col)` | ok | Qlik Fabs() is float absolute value. ThoughtSpot abs() works on both integers and floats — direct equivalent. |

## Statistical

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| ST01 | `Fractile(expr, fraction)` | `No direct equivalent` | ok | Qlik Fractile() returns a percentile (0.9 = 90th percentile). ThoughtSpot has no built-in percentile in formula context — use SQL passthrough or ETL. |
| ST02 | `Correl(x, y)` | `No direct equivalent` | ok | Qlik Correl() returns the Pearson correlation coefficient. ThoughtSpot has no built-in correlation in formulas. |
| ST03 | `Kurtosis(expr)` | `No direct equivalent` | ok | Qlik returns statistical kurtosis. ThoughtSpot has no kurtosis function in formula context. |
| ST04 | `Skew(expr)` | `No direct equivalent` | ok | Qlik returns statistical skewness. ThoughtSpot has no skewness formula function. |
| ST05 | `NormDist(x, mean, stdev, cumulative)` | `No direct equivalent` | ok | Qlik calculates normal distribution CDF/PDF. ThoughtSpot has no statistical distribution functions in formulas. |
| ST06 | `NormInv(p, mean, stdev)` | `No direct equivalent` | ok | Qlik returns the inverse normal distribution. ThoughtSpot has no equivalent. |
| ST07 | `ChiDist(x, df)` | `No direct equivalent` | ok | Qlik chi-square distribution function. ThoughtSpot has no statistical distribution functions. |
| ST08 | `TDist(x, df, tails)` | `No direct equivalent` | ok | Qlik Student's t-distribution function. ThoughtSpot has no equivalent. |
| ST09 | `FDist(x, df1, df2)` | `No direct equivalent` | ok | Qlik F-distribution function. ThoughtSpot has no statistical distribution functions. |
| ST10 | `Rank(expr)` | `rank(col)` | ok | Both rank current value relative to peers in the chart. Minor syntax difference — functionally equivalent. |
| ST11 | `HRank(expr)` | `No direct equivalent` | ok | Qlik HRank() ranks values horizontally in pivot tables. ThoughtSpot has no horizontal rank concept. |

## Type Conversion

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| TC01 | `Num#(str, format)` | `to_double(col)` | ok | Qlik Num#() parses a formatted string into a number. ThoughtSpot uses to_double() or to_integer() to cast string to numeric. |
| TC02 | `Text(expr)` | `to_string(col)` | ok | Both convert a value to its string representation. Useful for concatenation with date or numeric fields. |
| TC03 | `Date(expr, format)` | `to_date(col, format)` | ok | Both convert/format values as dates. Format strings differ: Qlik 'YYYY-MM-DD' vs ThoughtSpot strftime '%Y-%m-%d'. |
| TC04 | `Date#(str, format)` | `to_date(col, format)` | ok | Qlik Date#() interprets a string as a date. ThoughtSpot uses to_date() for the same purpose. |
| TC05 | `Int(x)` | `to_integer(col)` | ok | Qlik Int() truncates to integer. ThoughtSpot to_integer() converts to integer type — behavior may differ for negative numbers. |
| TC06 | `Money(expr, format)` | `to_string(col)` | ok | Qlik Money() formats as currency string. ThoughtSpot has no currency formatter — use to_string() and control display in visualization settings. |
| TC07 | `Bool(x)` | `to_bool(col)` | ok | Both convert a value to boolean. Qlik Bool() and ThoughtSpot to_bool() are functionally equivalent. |
| TC08 | `Dual(str, num)` | `No direct equivalent` | ok | Qlik Dual() creates a value with both text and numeric representations. ThoughtSpot has no dual-type concept — store as separate columns. |
| TC09 | `Num(expr, format) [to_double path]` | `to_double(col)` | ok | Qlik Num() formats a number as display string. ThoughtSpot to_double() converts string to numeric for calculations — different primary purpose. |

## Color (Qlik-specific)

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| CO01 | `RGB(r, g, b)` | `No equivalent` | ok | Qlik RGB() returns a color value for conditional coloring in charts. ThoughtSpot does not expose color functions in formula context — colors are set via chart config. |
| CO02 | `ARGB(a, r, g, b)` | `No equivalent` | ok | Qlik ARGB() creates a color with transparency (alpha channel). No ThoughtSpot formula equivalent. |
| CO03 | `HSL(h, s, l)` | `No equivalent` | ok | Qlik HSL() creates a color from hue/saturation/lightness. No ThoughtSpot formula equivalent. |
| CO04 | `ColorMix1(weight, col1, col2)` | `No equivalent` | ok | Qlik blends two colors based on a weight (0-1). ThoughtSpot achieves conditional coloring through visualization-level settings only. |
| CO05 | `ColorMix2(weight, col1, col2, col3)` | `No equivalent` | ok | Qlik blends three colors. No ThoughtSpot formula equivalent. |
| CO06 | `Red(color)` | `No equivalent` | ok | Qlik extracts the red component of a color value. No ThoughtSpot equivalent. |
| CO07 | `Green(color)` | `No equivalent` | ok | Qlik extracts the green component of a color value. No ThoughtSpot equivalent. |
| CO08 | `Blue(color)` | `No equivalent` | ok | Qlik extracts the blue component of a color value. No ThoughtSpot equivalent. |

## Financial (Qlik-specific)

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| FI01 | `BlackAndScholes(s, x, r, t, sigma, type)` | `No equivalent` | ok | Qlik provides a built-in Black-Scholes option pricing formula. ThoughtSpot has no financial modeling functions — use sql_float() passthrough or pre-compute in ETL. |
| FI02 | `FV(rate, nper, pmt, pv, type)` | `No equivalent` | ok | Qlik FV() calculates Future Value of an investment. ThoughtSpot has no financial calculation functions in formulas. |
| FI03 | `PV(rate, nper, pmt, fv, type)` | `No equivalent` | ok | Qlik PV() calculates Present Value. ThoughtSpot has no financial functions in formula context. |
| FI04 | `NPV(discount, val1, val2, ...)` | `No equivalent` | ok | Qlik NPV() calculates Net Present Value. ThoughtSpot has no NPV function — pre-compute or use passthrough SQL. |
| FI05 | `IRR(values)` | `No equivalent` | ok | Qlik IRR() calculates Internal Rate of Return. ThoughtSpot has no financial functions. |
| FI06 | `Rate(nper, pmt, pv, fv, type, guess)` | `No equivalent` | ok | Qlik Rate() calculates the interest rate per period. ThoughtSpot has no financial formula functions. |

## Passthrough SQL (ThoughtSpot-specific)

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| PT01 | `No equivalent (Qlik uses native script)` | `sql_string_op('expression')` | corrected | ThoughtSpot sql_string() passes raw SQL to the underlying database and returns a string. Qlik handles this via data load script. Use when ThoughtSpot native functions are insufficient. |
| PT02 | `No equivalent` | `sql_int_op('expression')` | corrected | ThoughtSpot sql_int() passes a SQL expression to the database and returns an integer. Useful for database-specific functions not available natively. |
| PT03 | `No equivalent` | `sql_double_op('expression')` | corrected | ThoughtSpot sql_float() passes a SQL expression returning a float. Useful for percentiles and complex math not available in native ThoughtSpot formulas. |
| PT04 | `No equivalent` | `sql_date_op('expression')` | corrected | ThoughtSpot sql_date() passes a SQL expression returning a date. Use when ThoughtSpot date functions do not cover a specific database function. |
| PT05 | `No equivalent` | `sql_bool_op('expression')` | corrected | ThoughtSpot sql_bool() passes a SQL expression returning a boolean. Use for complex conditions not expressible in native ThoughtSpot formula syntax. |

## ThoughtSpot-Specific

| # | Qlik Sense | ThoughtSpot | Status | Notes |
|---|---|---|---|---|
| TS01 | `No equivalent` | `query_groups()` | ok | ThoughtSpot-only. query_groups() inherits the current search's dimension groupings dynamically inside group_aggregate(). Adapts as users change their search. |
| TS02 | `No equivalent` | `query_filters()` | ok | ThoughtSpot-only. query_filters() inherits the current search's applied filters inside group_aggregate(). No Qlik formula equivalent. |
| TS03 | `No equivalent` | `query_groups() + {attr}` | ok | ThoughtSpot-only. Extends current search groupings by adding an extra dimension to scope. No direct Qlik equivalent. |
| TS04 | `No equivalent` | `query_groups() - {attr}` | ok | ThoughtSpot-only. Removes a specific dimension from inherited search groupings inside group_aggregate(). Allows finer control of aggregation scope. |
