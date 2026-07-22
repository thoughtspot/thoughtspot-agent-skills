<!-- currency: powerbi — 2026-07 (DAX subset verified on ps-internal 26.x) -->
# Power BI DAX → ThoughtSpot formula translation

The translation map behind `ts powerbi build-model`. Verified against a live cluster, not
just docs. Anything outside this subset is returned untranslated and flagged NEEDS REVIEW —
never faked.

## Direct

| DAX | ThoughtSpot | Notes |
|---|---|---|
| `SUM(t[c])` / `AVERAGE` / `MIN` / `MAX` | `sum([t::c])` / `average` / `min` / `max` | |
| `COUNT` / `COUNTA` | `count([t::c])` | |
| `DISTINCTCOUNT(t[c])` | `unique_count([t::c])` | |
| `DIVIDE(a, b)` | `safe_divide(a, b)` | avoids /0 |
| `IF(c, x, y)` / nested | `if (c) then x else y` | |
| `ROUND(x, n)` | `round(x, 10^-n)` | TS 2nd arg is an **increment**, not digit count; `round(x,0)`=null (trap) |
| `CEILING(x)` / `FLOOR(x)` | `ceil(x)` / `floor(x)` | |
| `CEILING(x, sig)` / `FLOOR(x, sig)` | `ceil(x/sig)*sig` / `floor(x/sig)*sig` | 2-arg significance |
| `a & b` / `CONCATENATE` | `concat(a, b)` | a lone `&` is flagged (verify) |
| `AND(a,b)` / `OR(a,b)` (function form) | `a and b` / `a or b` | also `&&`/`\|\|` operators |

## Pattern rewrites

| DAX | ThoughtSpot | Reference |
|---|---|---|
| `CALCULATE(<agg>, <filter/cond>)` | `sum_if(<cond>, <agg-arg>)` | |
| `CALCULATE(m, ALL(t[c]))` / `REMOVEFILTERS(t[c])` / `ALLSELECTED(t[c])` | `group_aggregate(m, query_groups()-{[t::c]}, query_filters()-{[t::c]})` | [worked-examples/powerbi/calculate-all-to-group-aggregate.md](../../worked-examples/powerbi/calculate-all-to-group-aggregate.md) |
| measure / calc-column reference | `[formula_<name>]` id-reference (topo-sorted) | resolves on first import; name-refs do not |
| `a - b` (two DATE columns) | `diff_days(b, a)` | day grain only |

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
