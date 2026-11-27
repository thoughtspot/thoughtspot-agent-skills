<!-- coverage-matrix last-reviewed: 2026-11-17 -->
# Coverage matrix — Power BI → ThoughtSpot

Every Power BI construct and its conversion status. Cite in the migration report. Within
Mapped: **Mapped** (deterministic) · **Approximated** (mapped with a caveat).

## Mapped Constructs

### DAX measures / calculated columns

| Construct | Status | Notes |
|---|---|---|
| `SUM/AVERAGE/MIN/MAX/COUNT` | Mapped | direct aggregation |
| `DISTINCTCOUNT` | Approximated | `(unique count(x) + max(if (isnull(x)) then 1 else 0))` — with a SPACE; `unique_count` is rejected by the parser (fixed in ts-cli v0.126.1, BL-171). DAX counts BLANK as a value and `unique count` ignores NULL, so the bracketed has-blank term adds it back (live-probed 2026-11-08, BL-540; until ts-cli 0.212.0 the plain form was one lower on a column with blanks). Approximated, not exact: a dimension row with no matching facts is BLANK in DAX and 1 here (the outer join's NULL counts as the blank), Power BI's blank row for unmatched relationship keys is not modelled, and the form is unprobed inside `group_aggregate`; the mapping row says so |
| `DISTINCTCOUNTNOBLANK` | Mapped | → `unique count(x)`: both skip blanks (BL-540) |
| `TRIM` / `UPPER` / `LOWER` | Mapped | `sql_string_op("TRIM({0})", …)` pass-through — none of the three exists as a ThoughtSpot function (BL-170/BL-171); bare names were emitted until ts-cli v0.126.1. Emitted forms live-verified on se-thoughtspot 2026-07-30 |
| `YEAR` / `MONTH` / `DAY` / `HOUR` / `QUARTER` | Mapped | `year` / `month_number` / `day` / `hour_of_day` / `quarter_number`. `MONTH` previously emitted `month` (the month **name**, not 1-12) and `HOUR` emitted a non-existent `hour` — both fixed in ts-cli v0.126.1 (BL-171) |
| `MINUTE` / `SECOND` | Flagged | ThoughtSpot has **no minute or second extractor at all** (live-verified 2026-07-30: `minute (` and `second (` are rejected with error_code 14516), and the warehouse dialect is not known at this layer, so no `sql_int_op` template can be assumed — flagged NEEDS REVIEW rather than guessed (BL-171). **Fix by hand once the warehouse is known:** `sql_int_op ( "MINUTE({0})" , [t::c] )` / `sql_int_op ( "SECOND({0})" , [t::c] )` — the same prescription the Qlik mapping's D09/D10 rows carry, and what `sv_sql.py`/`mv_sql.py` emit for SQL `MINUTE()`/`SECOND()` where the dialect IS known |
| Arithmetic, operators, `DIVIDE` | Mapped | `DIVIDE` → `safe_divide` |
| A string literal holding a quote (`O'Brien`) (`"O'Brien"` in DAX) | Mapped | `"O'Brien"` — ThoughtSpot's double-quoted literal; a backslash is doubled; both quote kinds → `concat` of the two forms. **Fixed ts-cli 0.165.0 (BL-365):** the literal was copied as `'O''Brien'`, which ThoughtSpot reads as two quotes — a silent wrong answer (live 2026-10-07, probe record §7). `formula_text.ts_string_literal`; a DAX `""` is now read as one double quote |
| `a * b / c` | Mapped | → `( a * b ) / c`. **Fixed ts-cli 0.165.0 (BL-365):** ThoughtSpot reads `a * b / c` as `a * ( b / c )`, and a division of two integers is fixed-point at scale 6 in Snowflake (`[n] * 4 / 3` = 3.999999). Every product under a division is bracketed (`formula_text.ts_finalize_formula`) |
| `IF` / nested `IF` | Mapped | → conditional expressions |
| `CALCULATE(<agg>, FILTER/cond)` | Approximated | → `sum_if`; verify vs Power BI |
| `CALCULATE(DISTINCTCOUNT(t[k]), <filters>)` | Approximated | → `unique_count_if ( <conditions> , [t::k] )`, measures only (a calculated column stays NEEDS REVIEW). Each filter argument must be exactly `t[c] = <literal>`, `t[c] IN {<literals>}`, `NOT ISBLANK(t[c])` / `NOT(ISBLANK(t[c]))`, or `USERELATIONSHIP(t[a], u[b])` (no condition; adds a role-playing-date note). Anything else refuses the measure, as do a DAX comment, a filter on `0` or `""`, a mixed set holding a non-integer number, a column off the home table, and a nested CALCULATE filtering the same column (case-insensitive; different columns AND). **Not Migrated:** CALCULATE *replaces* an existing filter on the filtered column while `unique_count_if` *ANDs* with it, so the two differ whenever the query filters that column: grouping, a slicer, a page or Liveboard filter (emitted side live-probed 2026-10-08; the Power BI side is inferred), and `DISTINCTCOUNT` counts a blank key that `unique_count_if` ignores. Full rules: the mapping doc's Pattern rewrites |
| `VAR a = CALCULATE(DISTINCTCOUNT(t[k]), …) VAR b = … RETURN a/b` | Approximated | the two gated terms divided. Both VARs must count the same key; a VAR defined twice, text between definitions, or a `RETURN` doing anything else (`DIVIDE(a,b)`, `1 - a/b`, `a/b*2`) is refused |
| `CALCULATE(DISTINCTCOUNT(t[k]), USERELATIONSHIP(…))` alone | Approximated | a plain `DISTINCTCOUNT` (the `DISTINCTCOUNT` row's form and note), plus the note that a page slicing on the role-playing date needs a union fact keyed by measure |
| `t[c] IN {…}` on its own, or a one-member set inside a call (`IF(t[s] IN {"a"}, 1, 0)`) | Mapped | → `[t::c] IN {…}` in place. A multi-member set inside a call, or a `,` `(` `)` `[` `]` inside a string or name within a call, stays NEEDS REVIEW as on main: the rewrites after the split still reach inside quoted text (BL-611) |
| `CALCULATE(m, ALL(Table[Col]))` / `REMOVEFILTERS` / `ALLSELECTED` | Approximated | → `group_aggregate(m, query_groups()-{cols}, query_filters()-{cols})` (worked example) |
| Measure / calc-column cross-references | Mapped | `[formula_<name>]` id-refs, topo-sorted (resolve on first import — open-item #2) |
| `CEILING/FLOOR(x[, significance])` | Mapped | 1-arg → `ceil/floor`; 2-arg → `ceil(x/sig)*sig` |
| `ROUND(x, n)` | Mapped | TS 2nd arg is an increment: `round(x, 10^-n)` |
| Date subtraction / `DATEDIFF` | Approximated | → `diff_days` (day grain) |
| `SAMEPERIODLASTYEAR` / YoY / SPLY / `TOTALYTD` | Approximated | rebuilt via a Reference Date **parameter** (worked example); not a 1:1 formula |

### Data model

| Construct | Status | Notes |
|---|---|---|
| Tables / columns / data types | Mapped | Table TML bound to an existing connection; `db_column_name` on every column |
| Relationships → joins | Mapped | real cardinality from `fromCardinality`/`toCardinality`; `MANY_TO_ONE` default. A **many-to-many** relationship is left out and flagged NEEDS REVIEW: a Model join cannot be `MANY_TO_MANY` (14528, lint I20), and emitting `MANY_TO_ONE` would fan out silently — model a bridge table |
| `summarizeBy` (Sum/Average/…) | Mapped | drives MEASURE aggregation (AVG vs SUM) |
| `summarizeBy: distinctCount` | Approximated | the column stays an attribute under its own name (a visual grouping by it still groups), and the Model gains a separate formula column `<column> (Distinct Count)`, which a visual summarising the column binds to, in `DISTINCTCOUNT`'s form (`( unique count ( [t::c] ) + max ( if ( isnull ( [t::c] ) ) then 1 else 0 ) )`, BL-540), Approximated for the same reasons as `DISTINCTCOUNT` above; the mapping row carries the note. Never `aggregation: COUNT_DISTINCT`, which ThoughtSpot stores as an attribute on a text or date key (invariant I5, BL-447 — the column form shipped until this release). |
| Calc column used as a join key | Mapped | materialized as a physical column (joins are physical) |

### Visuals & report

| Power BI visual | Status | ThoughtSpot target |
|---|---|---|
| Clustered/stacked column & bar | Mapped | `COLUMN`/`STACKED_COLUMN` / `BAR`/`STACKED_BAR` (PBI naming inverted) |
| Line / area | Mapped | `LINE` / `AREA` |
| Line + clustered column combo | Approximated | `LINE_COLUMN`; needs 2 measures (flagged if 1 survives) |
| Pie / donut | Mapped | `PIE` |
| Matrix | Mapped | `PIVOT_TABLE` (role-aware `axis_configs`) |
| Card / KPI | Mapped | `KPI` |
| Table | Mapped | `GRID_TABLE` |
| Month text column on an axis | Mapped | monthly date bucket (`Month(Date)`) so it sorts chronologically |
| Pages → tabs | Mapped | one Liveboard, PBI `pageOrder` preserved |

## Unmapped Constructs (Limitations)

Flagged (needs a human; never faked) or Dropped (no ThoughtSpot equivalent).

| Construct | Status | Notes |
|---|---|---|
| Point-in-time (`CALCULATE`+`ALL`+`MAX`, headcount-as-of-date) | Flagged | genuine manual rebuild |
| Iterators (`SUMX`/`RANKX`/`EARLIER`), row-context, `SWITCH`, and `VAR/RETURN` other than the gated ratio above | Flagged | no safe deterministic port |
| An IN set whose result is negated or compared (under a NOT, a comparison (`= FALSE`, `<> TRUE`, `FALSE = (…)`) or a blank test (`ISBLANK`), directly or through a bare paren, `AND`/`OR`, or the value arguments of `IF` (then and else, not the condition), `SWITCH`, `IFERROR` or `COALESCE`: `NOT t[c] IN {…}`, `NOT (x && t[c] IN {…})`, `t[c] IN {…} = FALSE`, `<> TRUE`, `ISBLANK(t[c] IN {…})`); an `IN` not followed directly by `{`; an IN set in a measure carrying a comment; an IN set mixing strings and numbers; an IN set member that is not a literal (a row constructor `(t[a], t[b]) IN {("x", 1)}`, a column, an expression); a `CALCULATE(<agg>, …)` holding an IN set, a `,` `(` `)` `[` `]` inside a string, a `[column]` whose parens do not nest, or a stray `]` | Flagged | NEEDS REVIEW. Negated or compared: a blank is not in the set, FALSE in DAX and NULL in ThoughtSpot, and only a plain condition treats the two alike (BL-610). Mixed: DAX compares as text (`1.50` as `"1.5"`). Not a literal: ThoughtSpot's `in` takes a list of literals. CALCULATE: the `sum_if` rewrite keeps only the first aggregate's argument (BL-609); the gated distinct count above is the exception |
| Map / gauge / custom AppSource visual | Flagged/Approximated | needs a geo column / no map equivalent |
| Tooltip page | Dropped | hover overlay, not a navigable tab |
| Slicer / `basicShape` / buttons / text boxes | Dropped | filters / decorations, not data visuals |
| Conditional formatting / bookmarks / drill-through | Dropped | not parsed |
