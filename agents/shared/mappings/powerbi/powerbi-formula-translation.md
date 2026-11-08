<!-- currency: powerbi — 2026-07 (DAX subset verified on ps-internal 26.x; ThoughtSpot target names re-verified on se-thoughtspot 2026-07-30 per BL-171 — `unique_count` (underscore), `trim`, `upper`, `lower`, `hour`, `minute`, `second` confirmed ABSENT; `MONTH` retargeted to `month_number` because `month` returns the month NAME) -->
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
| `DISTINCTCOUNT(t[c])` | `unique count([t::c]) + max(if (isnull([t::c])) then 1 else 0)` | DAX counts BLANK as one more value; `unique count` compiles to SQL `count(DISTINCT …)`, which ignores NULL, so it alone is **one lower** whenever the column has a blank. The `max(if (isnull …))` term adds that one back, per group. Live-probed 2026-11-08 on an internal cluster (keys a, a, b, NULL, NULL, c): `unique count` = 3, this form = 4 (DAX's answer), and 1 for a group holding only the blank key (BL-540). Before ts-cli 0.209.0 the plain form shipped as Mapped. Not modelled: the blank row Power BI adds to a table for relationship keys with no match. The name has a **SPACE**: `unique_count(` does not exist and is rejected with `Search did not find "unique_count ("` (error_code 14516, live-verified 2026-07-30 on se-thoughtspot, BL-171). Only the conditional variants carry an underscore (`unique_count_if`) |
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
| `CALCULATE(m, ALL(t[c]))` / `REMOVEFILTERS(t[c])` / `ALLSELECTED(t[c])` | `group_aggregate(m, query_groups()-{[t::c]}, query_filters()-{[t::c]})` | [worked-examples/powerbi/calculate-all-to-group-aggregate.md](../../worked-examples/powerbi/calculate-all-to-group-aggregate.md) |
| measure / calc-column reference | `[formula_<name>]` id-reference (topo-sorted) | resolves on first import; name-refs do not |
| `a - b` (two DATE columns) | `diff_days(a, b)` | day grain only; TS `diff_days(end, start)` = end − start, so the order is kept (BL-336) |

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
