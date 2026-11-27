<!-- currency: powerbi — 2026-11 (gated shapes: emitted form live-probed on ps-internal 2026-10-08) / 2026-07 (DAX subset verified on ps-internal 26.x; ThoughtSpot target names re-verified on se-thoughtspot 2026-07-30 per BL-171 — `unique_count` (underscore), `trim`, `upper`, `lower`, `hour`, `minute`, `second` confirmed ABSENT; `MONTH` retargeted to `month_number` because `month` returns the month NAME) -->
# Power BI DAX → ThoughtSpot formula translation

The translation map behind `ts powerbi build-model`. Verified against a live cluster, not
just docs. Anything outside this subset is returned untranslated and flagged NEEDS REVIEW —
never faked.

## String literals and `a * b / c` (BL-365, ts-cli 0.165.0)

ThoughtSpot reads a doubled quote in a single-quoted literal as **two** quotes (`'it''s'` is
`it''s`), its backslash escape fails before a space, and it reads `a * b / c` as
`a * ( b / c )` — with a division of two integers fixed-point at scale 6 (live, se-thoughtspot
2026-10-07; [formula reference](../../schemas/thoughtspot-formula-patterns.md#string-literals)).
So a DAX literal is decoded (`""` is one double quote), a literal holding a quote is emitted **double-quoted** (`"O'Brien"`), a
backslash doubled, and every product under a division bracketed (`( a * b ) / c`) — the
translator's last step, `formula_text.ts_finalize_formula`. Copying a quote-bearing literal across was a silent
wrong answer.

## Direct

| DAX | ThoughtSpot | Notes |
|---|---|---|
| `SUM(t[c])` / `AVERAGE` / `MIN` / `MAX` | `sum([t::c])` / `average` / `min` / `max` | |
| `COUNT` / `COUNTA` | `count([t::c])` | |
| `DISTINCTCOUNT(t[c])` | `(unique count([t::c]) + max(if (isnull([t::c])) then 1 else 0))` — **Approximated** | DAX counts BLANK as one more value; `unique count` compiles to SQL `count(DISTINCT …)`, which ignores NULL, so it alone is **one lower** whenever the column has a blank. The bracketed `max(if (isnull …))` term adds that one back, per group (bracketed so it composes, e.g. as a divisor). Live-probed 2026-11-08 on an internal cluster (keys a, a, b, NULL, NULL, c): `unique count` = 3, this form = 4 (DAX's answer), and 1 for a group holding only the blank key (BL-540). Approximated, not exact: a dimension row with no matching facts is BLANK in DAX and 1 here (the outer join's NULL counts as the blank), Power BI's blank row for unmatched relationship keys is not modelled, and the form is unprobed inside `group_aggregate`. The mapping row carries that note. Before ts-cli 0.212.0 the plain form shipped as Mapped. The name has a **SPACE**: `unique_count(` does not exist and is rejected with `Search did not find "unique_count ("` (error_code 14516, live-verified 2026-07-30 on se-thoughtspot, BL-171). Only the conditional variants carry an underscore (`unique_count_if`) |
| `DISTINCTCOUNTNOBLANK(t[c])` | `unique count([t::c])` | Skips BLANK, exactly as `unique count` skips NULL (live-probed 2026-11-08, BL-540) |
| `DIVIDE(a, b)` | `safe_divide(a, b)` | avoids /0 |
| `IF(c, x, y)` / nested | `if (c) then x else y` | |
| `ROUND(x, n)` | `round(x, 10^-n)` | TS 2nd arg is an **increment**, not digit count; `round(x,0)`=null (trap) |
| `CEILING(x)` / `FLOOR(x)` | `ceil(x)` / `floor(x)` | |
| `CEILING(x, sig)` / `FLOOR(x, sig)` | `ceil(x/sig)*sig` / `floor(x/sig)*sig` | 2-arg significance |
| `a & b` / `CONCATENATE` | `concat(a, b)` | a lone `&` is flagged (verify) |
| `TRIM` / `UPPER` / `LOWER` | `sql_string_op("TRIM({0})", x)` etc. | **None of the three exists** as a ThoughtSpot function (live-verified: `upper`/`lower` 2026-06-13, `trim` 2026-07-29/30 — BL-170/BL-171). Pass-through; emitted forms live-verified 2026-07-30 |
| `YEAR` / `MONTH` / `DAY` / `HOUR` / `QUARTER` | `year` / `month_number` / `day` / `hour_of_day` / `quarter_number` | `MONTH` → `month_number`, **not** `month`, which returns the month NAME. A bare `hour` does not exist (BL-171) |
| `MINUTE` / `SECOND` | *flagged NEEDS REVIEW* | ThoughtSpot has no minute or second extractor (live-verified 2026-07-30), and the warehouse dialect is not known at this layer, so no `sql_int_op` template can be assumed. Hand-write `sql_int_op("MINUTE({0})", [t::c])` once the warehouse is known |
| `AND(a,b)` / `OR(a,b)` (function form) | `a and b` / `a or b` | also `&&`/`\|\|` operators |

## Pattern rewrites

| DAX | ThoughtSpot | Reference |
|---|---|---|
| `CALCULATE(<agg>, <filter/cond>)` | `sum_if(<cond>, <agg-arg>)` | |
| `CALCULATE(DISTINCTCOUNT(t[k]), <filters>)` — **Approximated** | `unique_count_if ( <conditions ANDed> , [t::k] )` | Measures only (a calculated column is evaluated per row in DAX, so it stays NEEDS REVIEW). Accepted only when the whole measure is the CALCULATE, every column is on the home table, and every filter argument is exactly one of: `t[c] = <literal>` → `[t::c] = <literal>`; `t[c] IN {<literals>}` → ORed `=`; `NOT ISBLANK(t[c])` or `NOT(ISBLANK(t[c]))` → `[t::c] != null`; `USERELATIONSHIP(t[a], u[b])` → no condition, plus a note that a page slicing on the role-playing date needs a union fact. Anything else in an argument refuses the measure: another comparison (`>=`, `==`, `<>`), a NOT before the column, a function or arithmetic around it, `&&`, `\|\|`, `&`, a non-column inside `ISBLANK`, a DAX comment, a filter on `0` or `""` (`= 0` and `= ""` also match BLANK in DAX, which ThoughtSpot's `=` drops; DAX `IN` compares strictly, but a set holding either is refused too). Literals go through the shared DAX decoder. A mixed set `IN {"a", 1}` compares as text, as DAX coerces it, and is accepted only when every number in it is a plain integer (`1.50` would compare as `"1.5"` in DAX). A nested `CALCULATE(CALCULATE(…), …)` ANDs filters on different columns and refuses filters on the same column, compared case-insensitively, because the inner one wins in DAX. Approximated for two reasons: the filter-replacement difference below, which arises whenever the query filters the filtered column (grouping, a slicer, a page or Liveboard filter), and `DISTINCTCOUNT` counting a blank key as one value where `unique_count_if` ignores NULL. With USERELATIONSHIP as its only argument it is a plain `DISTINCTCOUNT` and takes that row's form and note (BL-540) |
| `VAR a = CALCULATE(DISTINCTCOUNT(t[k]), …) VAR b = CALCULATE(DISTINCTCOUNT(t[k]), …) RETURN a/b` — **Approximated** | the two terms above, divided | Each VAR follows the CALCULATE row. Both must count the same key; VAR names are case-insensitive and a name defined twice refuses; the definitions must run back to back up to RETURN; a `RETURN` other than one VAR divided by another (`DIVIDE(a,b)`, `1 - a/b`, `a/b*2`) refuses |
| `t[c] IN {<literals>}` (`T[s] IN {"a","b"}` on its own, or a one-member `IF(t[s] IN {"a"}, 1, 0)`) | `[t::c] IN {'a','b'}` in place (`if (…) then 1 else 0`) | ThoughtSpot's `in` takes the curly-brace list ([patterns](../../schemas/thoughtspot-formula-patterns.md), BL-170), and string comparison there is case-insensitive like DAX's. **Refused (NEEDS REVIEW):** a set whose result is negated or compared, under a NOT, a comparison (`= FALSE`, `<> TRUE`, `FALSE = (…)`) or a blank test (`ISBLANK`), directly or through a bare paren, `AND`/`OR`, or the value arguments of `IF` (then and else, not the condition), `SWITCH`, `IFERROR` or `COALESCE`: `NOT t[s] IN {…}`, `NOT UPPER(t[s]) IN {…}`, `NOT (x && t[s] IN {…})`, `NOT OR(x, t[s] IN {…})`, `t[s] IN {…} = FALSE`, `<> TRUE`, `FALSE = (t[s] IN {…})`, `IF(IF(c, t[s] IN {…}, TRUE) = FALSE, …)`, `ISBLANK(t[s] IN {…})` (a blank is not in the set: FALSE in DAX, NULL in ThoughtSpot; as a plain condition both take `else`, negated or compared they differ, BL-610). A NOT or comparison beside the set rather than over it (`NOT ISBLANK(t[a]) && t[s] IN {…}`, `t[n] > 1 && t[s] IN {…}`) still translates, as does a comparison on an `IF` around the set. Also refused: **text the earlier splitter read differently at a call the translator splits (`IF`, `AND`, `OR`, `DIVIDE`, `ROUND`, `CEILING`, `FLOOR`, `CALCULATE`)** — a multi-member set as such a call's argument (`IF(t[s] IN {"a","b"}, 1, 0)`), or a string or name whose comma, paren or bracket throws the earlier splitter off there (`IF(t[s] = "a,b", 1, 0)`), or a `[column]` holding `]]` or `[` inside `CALCULATE` — because the rewrites after the split still reach inside quoted text (BL-611), so these stay NEEDS REVIEW as on main. Text the earlier splitter read the same way (`IF(t[s] = "(x)", 1, 0)`) translates as on main, in-string rewrites included (BL-611); an `IN` not followed directly by `{` (`IN ({…})`, a comment between, `IN VALUES(…)`); an IN set in a measure carrying a comment; a set mixing strings and numbers (DAX compares it as text, `1.50` as `"1.5"`); a member that is not a string or number literal, such as the row constructor `(t[a], t[b]) IN {("x", 1)}`, since ThoughtSpot's `in` takes a list of literals; and an IN set inside a `CALCULATE` other than the gated distinct count, because the `sum_if` rewrite keeps only the first aggregate's argument (BL-609). The same goes for any `CALCULATE` whose text the earlier argument splitter could not read: a `,` `(` `)` `[` `]` inside a string, a `[column]` whose parens do not nest, or a stray `]` |
| `CALCULATE(m, ALL(t[c]))` / `REMOVEFILTERS(t[c])` / `ALLSELECTED(t[c])` | `group_aggregate(m, query_groups()-{[t::c]}, query_filters()-{[t::c]})` | [worked-examples/powerbi/calculate-all-to-group-aggregate.md](../../worked-examples/powerbi/calculate-all-to-group-aggregate.md) |
| measure / calc-column reference | `[formula_<name>]` id-reference (topo-sorted) | resolves on first import; name-refs do not |
| `a - b` (two DATE columns) | `diff_days(a, b)` | day grain only; TS `diff_days(end, start)` = end − start, so the order is kept (BL-336) |

### Why the gated shapes are Approximated, never Migrated

`CALCULATE`'s column filter **replaces** any filter already on that column;
`unique_count_if` **ANDs** its condition with the query filters. A synthetic illustration,
for `CALCULATE(DISTINCTCOUNT(t[k]), t[s] = "b")` on a visual grouped by `t[s]`, where N is
the number of distinct keys with `s = "b"`:

| `t[s]` | emitted `unique_count_if` | Power BI `CALCULATE` |
|---|--:|--:|
| a | 0 | N |
| b | N | N |
| c | 0 | N |

The emitted column is what a live probe on ps-internal (2026-10-08) observed: row-local.
The Power BI column follows from CALCULATE's filter replacement and was not measured. The
same difference arises whenever the query itself filters the filtered column, whether by
grouping, a slicer, a page filter or a Liveboard filter: under a filter `s = "c"`, Power BI
still returns N and `unique_count_if` returns 0. The two agree only when nothing in the
query filters that column, so the label has to say Approximated. The same probe confirmed `unique_count_if` compiles and returns what
`unique count ( if … else null )` returns, which is why the shorter form is emitted.

## Rebuilt via a parameter (no 1:1 formula path)

| DAX | ThoughtSpot | Reference |
|---|---|---|
| `SAMEPERIODLASTYEAR` / SPLY | `sum_if(year([date]) = year([Reference Date]) - 1, <base>)` | [worked-examples/powerbi/sply-parameter.md](../../worked-examples/powerbi/sply-parameter.md) |
| YoY / YoY % / `DATEADD(-1 year)` | current (`= year([Reference Date])`) vs SPLY, then Var / % Change | same |
| `TOTALYTD` | parameter + cumulative; flag if not expressible | same |

## Flagged (genuine manual rebuild — never faked)

| DAX | Why |
|---|---|
| Point-in-time `CALCULATE(MAX(period)) + ALL` (headcount-as-of-date) | needs a correlated as-of filter TS formulas can't express |
| Iterators `SUMX` / `RANKX` / `EARLIER`, row context, `VAR`/`RETURN`, `SWITCH` | no safe deterministic port |
