<!-- currency: sigma — 2026-10 (Sigma function reference; apache/ossie @ 2491533 converters/sigma) -->
# Sigma formula language → ThoughtSpot function mapping

**Status:** research draft (2026-10-06) — not live-verified on the Sigma side, nothing
probed on a ThoughtSpot cluster for this document specifically · **Coverage:** 234/234
functions in Sigma's published function index
(`help.sigmacomputing.com/docs/function-index`, read 2026-10-06), plus 24 operators and
syntactic constructs — 258 rows · **Upstream comparison:** the apache/ossie Sigma converter
at `2491533`, `converters/sigma/` (`src/ossie_sigma/sigma_formula.py`,
`sigma_to_ossie.py`, `expression_utils.py`, `LIMITATIONS.md`, `README.md`; cited as
`file:line`) · **Classifications:** `direct` (native ThoughtSpot formula equivalent,
possibly as a documented composition of native functions; `direct (downgrade)` marks a native form that is faithful only under a stated precondition, counted as `direct`) · `passthrough` (requires a
ThoughtSpot `sql_*_op` pass-through — warehouse-dialect-specific, bypasses ThoughtSpot's
query planning) · `unmappable` (no ThoughtSpot expression; the converter raises an issue)
· `structural` (the Sigma function is a modelling construct — a join, a security rule, a
display limit, a parameter — whose ThoughtSpot home is Model or Answer TML rather than a
formula) · **TS ground truth:** `agents/shared/schemas/thoughtspot-formula-patterns.md`
(the *formula reference*), `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`
(the *Snowflake formula mapping*), and the verified findings of
[`docs/ossie/ts-ossie-function-mapping.md`](../ossie/ts-ossie-function-mapping.md) (the
*Ossie map*). Where a Sigma construct has a close Tableau or Power BI analogue, the repo's
verified decisions in `agents/shared/mappings/tableau/tableau-formula-translation.md` (the
*Tableau map*) and `agents/shared/mappings/powerbi/powerbi-formula-translation.md` (the
*Power BI map*) are reused and cited. **Reference dialect for every pass-through template:
Snowflake.** Sigma formulas are warehouse-agnostic; a pass-through is not, so the template
is written for Snowflake and must be re-derived for another connection.

The point of the **Via Ossie** column is a comparison of two paths. A Sigma model can reach
ThoughtSpot directly (Sigma formula → ThoughtSpot formula, this map) or in two hops (Sigma
→ Ossie `ANSI_SQL` via the upstream converter, then Ossie → ThoughtSpot via the Ossie map).
The column records what the first hop of the two-hop path produces, so a reader can see
where it loses fidelity. "Not translated" in that column means the upstream converter keeps
the formula as a `SIGMA`-dialect string only and raises `EXPRESSION_NOT_TRANSLATABLE`
(`sigma_to_ossie.py:247-257`, metrics `:360-378`) — nothing is lost on the way in, but an
Ossie consumer that is not a Sigma converter receives no usable expression.

---

## How to read the tables

Every ThoughtSpot cell is written in ThoughtSpot formula syntax: column references are
`[TABLE::Column]` (shortened to `[x]`, `[d]`, `[s]` where the table is immaterial), and the
spaces around parentheses and commas are the canonical form. Sigma's own reference syntax
(`[Column]`, `[Element/Column]`) is rewritten from resolved metadata, never textually.

- **E1 — one row per documented function.** The inventory is Sigma's function index as
  published on 2026-10-06. Two names appear in it twice — `Text` (Type and Geography) and
  `Json`/`JSON` (Type and Geography) — and are one overloaded function each, so each gets one
  row (under Type) whose Notes cover the geography overload. That gives 234 function rows.
  Operators and syntactic constructs are not in the index; they are rowed separately and
  counted separately. Argument vocabularies (`DateTrunc` precisions, `DatePart` parts,
  `DateFormat` tokens) are in sub-tables marked *(not counted)*.
- **E2 — `direct` may be a composition.** As in the Ossie map ([E2](../ossie/ts-ossie-function-mapping.md#how-to-read-the-tables)):
  ThoughtSpot has no `sign`, `trunc`, `pi`, `weekday-from-Sunday` or financial functions,
  but each is exactly expressible from native functions and arithmetic, and the Notes give
  the composition. The financial family is the largest beneficiary — all ten are closed-form
  arithmetic.
- **E3 — a `direct` row whose argument space is only partly covered names its fallback.**
  `DateTrunc` to `"second"`, `DatePart` for `"minute"`, `Like` with an interior wildcard,
  `Rank` inside a grouped table: each is `direct` for the common argument and names the
  `sql_*_op` fallback for the rest.
- **E4 — every `passthrough` row names its variant** (`sql_string_op`, `sql_int_op`,
  `sql_double_op`, `sql_bool_op`, `sql_date_op`, `sql_date_time_op`,
  `sql_string_aggregate_op`, `sql_int_aggregate_op`, `sql_double_aggregate_op`,
  `sql_date_time_aggregate_op`). The variant fixes type and measure/attribute role
  (Ossie map [E7](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)).
- **E5 — grouping level decides the ThoughtSpot shape, not the function name.** This is the
  hardest part of the map. A Sigma formula is evaluated *relative to the grouping level its
  column sits in*: the same `Sum([Amount])` is a per-row value in an ungrouped table, a
  per-group value at a grouping level, and a grand total in a summary. ThoughtSpot has no
  levels — a Model formula is evaluated at whatever grain the search asks for. So every
  aggregate row below is the *query-grain* translation, and the converter chooses among
  four shapes from the element's `groupings` (which the upstream converter preserves but
  does not model — `LIMITATIONS.md:26-38`, `README.md:114`):

  | Where the Sigma aggregate lives | ThoughtSpot shape |
  |---|---|
  | Data-model **metric**, or a column at the grouping level the target Answer will be built at | Plain aggregate — `sum ( [x] )` — a measure; the search supplies the grain. The clean case. |
  | Column at grouping level *L*, **referenced from a finer level** (or used in row-level arithmetic) | Fixed LOD — `group_aggregate ( sum ( [x] ) , { [k1] , [k2] } , query_filters ( ) )` where `k1…` are the grouping keys of *L* and every level above it. The Tableau `{FIXED}` decision (Tableau map, "LOD Expressions") applies verbatim. |
  | **Summary** (table-level total) | `group_aggregate ( sum ( [x] ) , { } , query_filters ( ) )` — the `GrandTotal` row. |
  | Aggregate inside an **ungrouped** table | Row grain. Sigma documents "the aggregate is calculated for each row" (SumIf reference page); the faithful target is the row-level expression with the aggregate dropped, or `group_aggregate ( … , { [T::pk] } , query_filters ( ) )` when a key exists. Raise an issue — this is usually a modelling slip on the Sigma side. |

  `Subtotal` / `PercentOfTotal` make the level explicit in the formula and map onto
  `query_groups ( ) - { … }`; see the Aggregate section.
- **E6 — Sigma window functions and ThoughtSpot's ordered windows are both context-completed,
  but from different contexts — so the native form is a downgrade, not a translation.**
  `CumulativeSum`, `MovingAvg`, `Lag`, `First`… take no order and no partition argument:
  order is the element's sort, and the partition is "each grouping above the level of the
  column" (CumulativeSum reference page). ThoughtSpot's `cumulative_*` / `moving_*` also take
  their order from trailing arguments and their partition from context — but the partition is
  **every dimension in the search, minus the order columns** (formula reference, *Window
  Functions*). The two agree only when the Answer's dimensions are the Sigma element's parent
  groupings plus the sort column, and nothing else. A reusable Model formula cannot guarantee
  that — the same reason [**E5**](#how-to-read-the-tables) gives for level-scoped aggregates
  — and the Ossie map rejects the identical reasoning for `LAG` (its `LAG` row: the
  `moving_sum` idiom "is correct exactly when the search's dimensions are the intended
  partition"). So these rows are classed **`direct (downgrade)`**: the native form is kept,
  because it is what most Answers built from the element will need and it is live-verified,
  and the Notes name its precondition and give the **faithful partitioned pass-through** as
  the alternative. The native form additionally needs (a) the sort column recovered from the
  element's `sort`/`order` and passed as the trailing order argument, and (b) that sort column
  to be a physical `[TABLE::col]` (Ossie map
  [E6](../ossie/ts-ossie-function-mapping.md#window-functions)). When (a) fails — no
  deterministic sort — the row is omitted with an issue, the Tableau map's tier-8 decision
  ("Row-Offset Table Calculations"), because no translation can be faithful to an order that
  does not exist. `Rank` / `RankPercentile` are **not** in this family: ThoughtSpot's `rank`
  has no partition at all (see the Ranking table). `direct (downgrade)` rows are counted as
  `direct` in the coverage summary and reported separately there.
- **E7 — a raw aggregate cannot be the first argument of a ThoughtSpot window function.**
  Sigma `CumulativeSum([Sum of Amount])` at a grouping level becomes
  `cumulative_sum ( [T::Amount] , [T::Order Date] )` — strip the inner `Sum`, as the Tableau
  map does for `RUNNING_SUM(SUM(x))` (live-verified EXC1). A non-`Sum` inner aggregate is
  wrapped instead: `cumulative_sum ( group_aggregate ( max ( [x] ) , query_groups ( ) , query_filters ( ) ) , [d] )`.
- **E8 — Sigma string literals are double-quoted; ThoughtSpot's are single-quoted.**
  `"closed"` → `'closed'`, and Sigma's doubled-quote escape (`""`) becomes a literal `"`
  inside the single-quoted string. Inside YAML the formula is double-quoted, so single
  quotes need no escaping (formula reference, *YAML Encoding*).
- **E9 — a missing `else` is `else null`, not `else 0`.** Sigma `If` and `Switch` return Null
  when nothing matches. ThoughtSpot requires an `else`; `else null` is live-verified (Tableau
  map, "Conditional aggregates", citing `static-set-to-column-set.md:107`) and preserves the
  semantics. This is a deliberate departure from the Ossie map's "`else 0` for a measure"
  rule, which changes a NULL into a zero.
- **E10 — Sigma `Count` and `CountDistinct` skip empty strings.** Both are documented as
  counting "non-null and non-empty values". ThoughtSpot `count` / `unique count` skip nulls
  only. On a text column the faithful form is `count_if ( [x] != '' , [x] )` /
  `unique_count_if ( [x] != '' , [x] )`; on any other type the plain form is exact.
- **E11 — an optional `timezone` argument forces a pass-through.** `DateTrunc`, `DatePart`,
  `Weekday`, `ConvertTimezone` accept an IANA zone. No ThoughtSpot date function takes one
  (`ts_var ( ts_user_timezone )` is a user setting, not an argument), so the row falls back
  to `CONVERT_TIMEZONE` inside the template.

---

## Coverage summary

| Section | Rows | `direct` | `passthrough` | `unmappable` | `structural` |
|---|--:|--:|--:|--:|--:|
| Aggregate functions | 30 | 24 | 4 | 2 | 0 |
| Array functions | 15 | 0 | 3 | 12 | 0 |
| Date functions | 30 | 20 | 10 | 0 | 0 |
| Financial functions | 10 | 10 | 0 | 0 | 0 |
| Geography functions | 11 | 0 | 7 | 4 | 0 |
| Join functions | 3 | 0 | 0 | 1 | 2 |
| Logical functions | 9 | 9 | 0 | 0 | 0 |
| Math functions | 39 | 36 | 3 | 0 | 0 |
| Passthrough functions | 12 | 0 | 7 | 5 | 0 |
| System functions | 6 | 2 | 0 | 3 | 1 |
| Text functions | 32 | 8 | 24 | 0 | 0 |
| Type functions | 6 | 3 | 1 | 2 | 0 |
| Window functions | 31 | 14 (12 downgrade) | 16 | 0 | 1 |
| **Function index subtotal** | **234** | **126** (12 downgrade) | **75** | **29** | **4** |
| Operators and constructs | 24 | 22 | 1 | 0 | 1 |
| **Total** | **258** | **148** (12 downgrade) | **76** | **29** | **5** |

57% of the inventory (148/258; 54% of the function index alone) is expressible in
ThoughtSpot's native formula language — **of which 12 are `direct (downgrade)`** window rows
(Cumulative/Moving Sum/Avg/Min/Max, `Lag`, `Lead`, `First`, `Last`), native in shape but
faithful only under [**E6**](#how-to-read-the-tables)'s precondition. Without them the
strictly faithful native share is 53% (136/258). The `passthrough` set concentrates in four places —
**case and whitespace string editing, regular expressions and case-sensitive matching** (24 of 32 Text rows: no native
`upper`/`lower`/`trim`/`replace`/regex in ThoughtSpot, and — since the 2026-10-06 probe — native `contains`/`strpos`/`=` are case-insensitive, so Sigma's case-sensitive `Contains`/`StartsWith`/`EndsWith`/`Find`/`Like` pass through; BL-333), **windowed statistics with no native
ordered form** (`Cumulative`/`Moving` `Count`/`StdDev`/`Variance`/`Corr`, dense rank, row
number, `Nth`, `FillDown`), **percentiles and string aggregation**, and **sub-day date
parts and timezone conversion**. 24 of the 29 `unmappable` rows are one cause, not
twenty-four: ThoughtSpot formulas have **no array, variant or geography type**, so every
Sigma function that *returns* one (plus the two sparkline display constructs built on arrays)
has nowhere to land; functions that take one and return a scalar are `passthrough`, over a
warehouse column. The other five are three system functions (two user-profile fields and
the organisation timezone), `AggLogical` (no
boolean aggregate pass-through variant) and `LookupMatchNulls` (no null-matching join).

**Against the two-hop path.** The upstream converter translates 44 documented Sigma
functions to SQL at all (its `_DIRECT_FUNCTIONS` table and special cases,
`sigma_formula.py:332-351, 527-590`), two of them with their arguments reversed and two more
with a wrong two-argument meaning — see [Open questions and gaps](#open-questions-and-gaps).
Every window function, every `Date*` function except the bare extractors, and Sigma's own
`Call*`/`Agg*` pass-throughs fall through to "not translated" (`sigma_formula.py:592`;
`LIMITATIONS.md:99-103`). The direct path keeps 31 window rows that the two-hop path cannot
carry at all — 14 natively (12 of them as downgrades) and 16 as pass-throughs.

---

## Aggregate functions

Source: Sigma function index, "Aggregate Functions". All rows are query-grain translations;
apply [**E5**](#how-to-read-the-tables) to choose the final shape.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `ArrayAgg(x)` | unmappable | — issue | not translated (`sigma_formula.py:592`) | Returns an array; ThoughtSpot formulas have no array type. A string-serialised downgrade is `sql_string_aggregate_op ( "ARRAY_TO_STRING(ARRAY_AGG({0}), ',')" , [x] )`, offered only on request because it changes the column's type. |
| `ArrayAggDistinct(x)` | unmappable | — issue | not translated | As `ArrayAgg`; downgrade uses `ARRAY_AGG(DISTINCT {0})`. |
| `Avg(x)` | direct | `average ( [x] )` | `AVG(x)` (`:334`) | |
| `AvgIf(x, cond)` | direct | `average_if ( cond , [x] )` | **not translated** — upstream keys the branch on `averageif` (`:553`), which is not a Sigma name; the branch also reverses the arguments | **Argument order reverses:** Sigma is value-first, ThoughtSpot condition-first. Multiple conditions are joined with `and`. |
| `Corr(x, y)` | direct | `( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / ( ( count ( [x] ) - 1 ) * stddev ( [x] ) * stddev ( [y] ) )` | not translated | The Excel map's `CORREL` composition (sample covariance over the product of sample standard deviations — the *n − 1* factors cancel to Pearson's *r*); **not import-probed**, as no row of that map is. Exact when `x` and `y` are non-null on the same rows; otherwise every aggregate takes the `*_if` form under `not ( isnull ( [x] ) ) and not ( isnull ( [y] ) )`. Fallback: `sql_double_aggregate_op ( "CORR({0}, {1})" , [x] , [y] )`. |
| `Count(x)` | direct | `count ( [x] )` | `COUNT(x)` (`:338`) | Exact for non-text columns; on text use `count_if ( [x] != '' , [x] )` ([**E10**](#how-to-read-the-tables)). The upstream translation loses the empty-string exclusion. |
| `CountDistinct(x)` | direct | `unique count ( [x] )` | `COUNT(DISTINCT x)` (`:527-528`) | **A space, not an underscore** (formula reference). Text columns: `unique_count_if ( [x] != '' , [x] )`. |
| `CountDistinctIf(x, cond1, …)` | direct | `unique_count_if ( cond1 and cond2 , [x] )` | **wrong** — `COUNT(DISTINCT CASE WHEN x THEN cond END)`: upstream treats the first argument as the condition (`:551-552`), Sigma's is the value | Sigma is value-first with variadic AND-ed conditions. |
| `CountIf(cond1, …)` | direct | `sum ( if ( cond1 and cond2 ) then 1 else 0 )` | `COUNT(CASE WHEN cond THEN 1 END)` for one condition only (`:549-550`); two or more conditions not translated | Sigma `CountIf` counts *rows*, so there is no value column; the Snowflake formula mapping's `COUNT_IF` row uses this exact `sum ( if … )` shape. `count_if ( cond , [T::pk] )` is equivalent when a non-null key exists. |
| `GrandTotal(agg)` | direct | `group_aggregate ( sum ( [x] ) , { } , query_filters ( ) )` | not translated | Shorthand for `Subtotal(agg, "grand_total")`. `{ }` grouping = grand total; `query_filters ( )` keeps the user's filters, which is the documented-but-unstated Sigma behaviour (the reference page does not say whether filters apply — flagged). |
| `ListAgg(x, sep)` | passthrough | `sql_string_aggregate_op ( "LISTAGG({0}, ', ') WITHIN GROUP (ORDER BY {0})" , [x] )` | not translated | **Variant: `sql_string_aggregate_op`.** Separator baked in (default `","`). Sigma orders the list by the *input column's sort*; the template's `WITHIN GROUP` must carry that sort explicitly or the order is unspecified. |
| `ListAggDistinct(x, sep)` | passthrough | `sql_string_aggregate_op ( "LISTAGG(DISTINCT {0}, ', ') WITHIN GROUP (ORDER BY {0})" , [x] )` | not translated | **Variant: `sql_string_aggregate_op`.** |
| `Max(x)` | direct | `max ( [x] )` | `MAX(x)` (`:337`) | ThoughtSpot `max` is aggregate-only — Sigma's row-wise maximum is `Greatest`, its own row. |
| `MaxIf(x, cond)` | direct | `max_if ( cond , [x] )` | not translated | Argument order reverses. |
| `Median(x)` | direct | `median ( [x] )` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x)` (`:529-530`) | Second hop recovers `median` only because the Ossie map tells its converter to prefer `median` at `p = 0.5`. |
| `Min(x)` | direct | `min ( [x] )` | `MIN(x)` (`:336`) | Aggregate-only, as `Max`. |
| `MinIf(x, cond)` | direct | `min_if ( cond , [x] )` | not translated | |
| `PercentileCont(x, k)` | passthrough | `sql_double_aggregate_op ( "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY {0})" , [x] )` | not translated — upstream handles `percentile` (`:531-532`), not Sigma's `PercentileCont` | **Variant: `sql_double_aggregate_op`.** `k` baked into the template. `k = 0.5` → `median ( [x] )`. |
| `PercentileDisc(x, k)` | passthrough | `sql_double_aggregate_op ( "PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY {0})" , [x] )` | not translated | **Variant: `sql_double_aggregate_op`.** |
| `PercentOfTotal(agg, mode, n)` | direct | `sum ( [x] ) / group_aggregate ( sum ( [x] ) , query_groups ( ) - { [parent dims] } , query_filters ( ) )` | not translated | Documented as `agg / Subtotal(agg, mode, n)`, so it inherits `Subtotal`'s grouping rewrite. `"grand_total"` → `{ }`. Plain `/`, not `safe_divide` — `safe_divide` returns 0 where Sigma returns Null (Ossie map, `a / b`). The formula reference's *Percentage Contribution* pattern is this shape. |
| `RegressionIntercept(y, x)` | direct | `average ( [y] ) - [formula_RegressionSlope] * average ( [x] )` | not translated | The Excel map's `INTERCEPT` composition, referencing the slope formula by id; not import-probed; pairing caveat as `Corr`. Argument order assumed `(y, x)` by analogy with `RegressionSlope`, whose page states it. Fallback `sql_double_aggregate_op ( "REGR_INTERCEPT({0}, {1})" , [y] , [x] )`. |
| `RegressionR2(y, x)` | direct | `pow ( [formula_Corr] , 2 )` | not translated | The Excel map's `RSQ` composition (square of Pearson's *r*), referencing the `Corr` composition by id; not import-probed. Same argument-order assumption. Fallback `sql_double_aggregate_op ( "REGR_R2({0}, {1})" , [y] , [x] )`. |
| `RegressionSlope(y, x)` | direct | `( ( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / ( count ( [x] ) - 1 ) ) / variance ( [x] )` | not translated | The Excel map's `SLOPE` composition — sample covariance (its `COVARIANCE.S` row) over sample variance of `x`; not import-probed; pairing caveat as `Corr`. `(y, x)` confirmed on the reference page. Fallback `sql_double_aggregate_op ( "REGR_SLOPE({0}, {1})" , [y] , [x] )`. |
| `StdDev(x)` | direct | `stddev ( [x] )` | `STDDEV_SAMP(x)` (`:535-536`) | Sample on both sides. Sigma documents no population form for standard deviation. |
| `Subtotal(agg, mode, n)` | direct | `group_aggregate ( sum ( [x] ) , query_groups ( ) - { [d1] } , query_filters ( ) )` | not translated | Per mode ([**E3**](#how-to-read-the-tables)): `"grand_total"` → `{ }`; `"parent_grouping"` with `n` → `query_groups ( ) - { … }` minus the `n` innermost grouping keys; `"x_axis"`/`"color"`/`"row"`/`"column"`/`*_parent` → `query_groups ( ) - { [that axis's dims] }`, which requires the converter to read the chart or pivot encoding. Sigma notes `Subtotal` is unavailable in datasets, so it arrives only from workbook elements. |
| `Sum(x)` | direct | `sum ( [x] )` | `SUM(x)` (`:333`) | |
| `SumIf(x, cond1, …)` | direct | `sum_if ( cond1 and cond2 , [x] )` | **wrong** — `SUM(CASE WHEN x THEN cond ELSE 0 END)` (`:547-548`): condition and value swapped, and only the two-argument form is recognised | Sigma is value-first with variadic AND-ed conditions; ThoughtSpot is condition-first. |
| `SumProduct(a, b, …)` | direct | `sum ( [a] * [b] )` | not translated | Row-wise product, then sum. |
| `Variance(x)` | direct | `variance ( [x] )` | `VAR_SAMP(x)` (`:533-534`) | Sample on both sides. |
| `VariancePop(x)` | direct | `variance ( [x] ) * ( count ( [x] ) - 1 ) / count ( [x] )` | not translated | ThoughtSpot `variance` is sample-only; population variance is sample variance times `(n − 1)/n`, an exact identity — the Excel map's `VAR.P` row (which flags the Ossie map's `VAR_POP` `passthrough` for revisiting). Not import-probed. Edge case: a single value gives NULL here where a population variance is 0. Fallback `sql_double_aggregate_op ( "VAR_POP({0})" , [x] )`. |

---

## Array functions

Source: Sigma function index, "Array Functions". ThoughtSpot formulas have no array type,
so the only reachable rows are those that consume an array **already present as a warehouse
column** (Snowflake `ARRAY`/`VARIANT`) and return a scalar. A nested array expression —
`ArrayLength(SplitToArray([s], ","))` — collapses into one template
(`sql_int_op ( "ARRAY_SIZE(SPLIT({0}, ','))" , [s] )`), which is how most real uses reach
ThoughtSpot.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Array(v1, …)` | unmappable | — issue | not translated | Returns an array. |
| `ArrayCompact(a)` | unmappable | — issue | not translated | Returns an array. |
| `ArrayConcat(a, b)` | unmappable | — issue | not translated | Returns an array. |
| `ArrayContains(a, v)` | passthrough | `sql_bool_op ( "ARRAY_CONTAINS({1}::VARIANT, {0})" , [a] , [v] )` | not translated | **Variant: `sql_bool_op`.** Snowflake's argument order is (value, array). |
| `ArrayDistinct(a)` | unmappable | — issue | not translated | Returns an array. |
| `ArrayExcept(a, b)` | unmappable | — issue | not translated | Returns an array. |
| `ArrayIntersection(a, b)` | unmappable | — issue | not translated | Returns an array. |
| `ArrayJoin(a, sep)` | passthrough | `sql_string_op ( "ARRAY_TO_STRING({0}, ', ')" , [a] )` | not translated | **Variant: `sql_string_op`.** |
| `ArrayLength(a)` | passthrough | `sql_int_op ( "ARRAY_SIZE({0})" , [a] )` | not translated | **Variant: `sql_int_op`.** |
| `ArraySlice(a, start, len)` | unmappable | — issue | not translated | Returns an array. |
| `RaggedHierarchy(c1, c2, …)` | unmappable | — issue | not translated | Builds a hierarchy value; ThoughtSpot has no ragged-hierarchy construct in formulas or Models. |
| `Sequence(start, end, step)` | unmappable | — issue | not translated | Returns an array. |
| `SplitToArray(s, delim)` | unmappable | — issue | not translated | Returns an array; see the section note for the scalar-consuming composition. |
| `Sparkline(json)` *(Beta)* | unmappable | — issue | not translated | A display construct (inline chart), not a value. |
| `SparklineAgg(v, d)` *(Beta)* | unmappable | — issue | not translated | As `Sparkline`. The nearest ThoughtSpot equivalent is an Answer visualisation, not a formula. |

---

## Date functions

Source: Sigma function index, "Date Functions". Sigma passes units as **leading** string
literals that may not reference a column (`DateAdd(unit, amount, date)`,
`DateDiff(unit, start, end)`, `DateTrunc(precision, date)` — each reference page), so the
per-unit rewrite is always static.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `BusinessDays(start, end)` | passthrough | `sql_int_op ( "{db}.{schema}.get_business_days_clamped({0}, {1}, TRUE)" , [start] , [end] )` | not translated | **Variant: `sql_int_op`.** No native weekday-only difference. The repo's `ts-recipe-formula-business-days-snowflake` skill deploys the UDF; its weekend-clamping and endpoint-inclusion rules must be checked against Sigma's ("excluding Saturdays and Sundays") before relying on equality. |
| `ConvertTimezone(d, to, from)` | passthrough | `sql_date_time_op ( "CONVERT_TIMEZONE('UTC', 'America/New_York', {0})" , [d] )` | not translated | **Variant: `sql_date_time_op`.** Zones baked in ([**E11**](#how-to-read-the-tables)). |
| `DateAdd(unit, n, d)` | direct | per-unit `add_*` — see the arithmetic table | **not translated** — upstream reads the unit from the *third* argument (`:581-587`); Sigma puts it first, so `_date_part_unit` rejects every documented call | **Argument order:** Sigma `(unit, n, d)` → ThoughtSpot `add_days ( [d] , n )`. Sigma truncates a fractional `n`; wrap a non-literal `n` in `floor ( )` for positive values (sign rule as `Trunc`). Month overflow clamps to month-end in Sigma; ThoughtSpot `add_months` clamping is not verified — flagged. |
| `DateDiff(unit, start, end)` | direct | per-unit `diff_*` — see the arithmetic table | **not translated** — same leading-unit defect (`:583-587`) | **Argument order reverses:** ThoughtSpot is `diff_days ( [end] , [start] )`. Sigma documents the result as "rounded to the nearest integer"; whether that means boundary-crossing (as Snowflake `DATEDIFF`) or rounded elapsed time is not stated on the reference page (re-read 2026-10-06). **ThoughtSpot's side is now settled** (V3): `diff_months` counts month boundaries crossed (`DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)`: Jan 31 → Feb 1 = 1) and `diff_years` is `EXTRACT(YEAR FROM end) - EXTRACT(YEAR FROM start)` (Dec 31 → Jan 1 = 1) — formula reference, live-verified 2026-10-06. If Sigma pushes down warehouse `DATEDIFF` (boundary-counting on Snowflake), these are exact; if it rounds elapsed time, month/year differences need a correction — still flagged on the Sigma side only. `"millisecond"` → `sql_int_op ( "DATEDIFF('millisecond', {0}, {1})" , [start] , [end] )`. |
| `DateFormat(d, fmt)` | passthrough | `sql_string_op ( "TO_CHAR({0}, 'YYYY-MM')" , [d] )` | not translated | **Variant: `sql_string_op`.** Sigma uses `strftime` `%`-codes; Snowflake's `TO_CHAR` uses its own model, so tokens are translated into the template (`%Y`→`YYYY`, `%m`→`MM`, `%d`→`DD`, `%B`→`MMMM`, `%a`→`DY` (abbreviated name; Snowflake's `TO_CHAR` has no full-weekday token, so `%A` uses the native below), `%H`→`HH24`, `%M`→`MI`, `%S`→`SS`, `%p`→`AM`). Single-token formats have natives and are preferred: `"%Y"` → `year_name ( [d] )`, `"%B"` → `month ( [d] )`, `"%A"` → `day_of_week ( [d] )` (Ossie map, `TO_CHAR`). |
| `DateFromUnix(n)` | passthrough | `sql_date_time_op ( "TO_TIMESTAMP({0})" , [n] )` | not translated | **Variant: `sql_date_time_op`.** A native composition `add_seconds ( to_date ( '1970-01-01' , 'yyyy-MM-dd' ) , [n] )` is plausible but `add_seconds` on a DATE operand is unverified. |
| `DateFromUnixMs(n)` | passthrough | `sql_date_time_op ( "TO_TIMESTAMP({0}, 3)" , [n] )` | not translated | **Variant: `sql_date_time_op`.** |
| `DateFromUnixUs(n)` | passthrough | `sql_date_time_op ( "TO_TIMESTAMP({0}, 6)" , [n] )` | not translated | **Variant: `sql_date_time_op`.** |
| `DateLookback(v, d, n, unit)` | passthrough | `sql_double_aggregate_op ( "SUM(SUM({0})) OVER (PARTITION BY {2} ORDER BY {1} RANGE BETWEEN INTERVAL '1 month' PRECEDING AND INTERVAL '1 month' PRECEDING)" , [v] , start_of_month ( [d] ) , [T::parent] )` | not translated | **Variant: `sql_double_aggregate_op`; wrap per the [passthrough caveat](#passthrough-caveat-applies-to-every-passthrough-row); *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** The operand is aggregated inside the window, and `ORDER BY` is the bucketed date expression matching the search's `.monthly` grouping. Sigma requires an *exact* row at the offset date and returns Null otherwise — a value-ranged frame, not a row offset. ThoughtSpot's `moving_sum ( [v] , 1 , -1 , [d] )` is row-positional (live-verified on gapped dates, formula reference *Moving Functions*), so it is a **documented downgrade** that is exact only when the date axis is dense at the search's bucket. Snowflake's support for an `INTERVAL` frame on this exact shape is **unverified** — flagged. The Power BI map rebuilds the common year-ago case with a parameter (`SAMEPERIODLASTYEAR`), which is the better target when the intent is period comparison. |
| `DatePart(part, d, tz)` | direct | per-part — see the date-part table | not translated (only the one-argument extractors are) | 8 of 12 parts native; `"minute"`, `"second"`, `"millisecond"`, `"epoch"` fall back to `sql_int_op` ([**E3**](#how-to-read-the-tables)); a `tz` argument forces a pass-through ([**E11**](#how-to-read-the-tables)). |
| `DateParse(s, fmt)` | direct | `to_date ( [s] , '%Y-%m-%d' )` | not translated | ThoughtSpot `to_date` accepts `strptime` `%`-codes (formula reference; Tableau map `DATEPARSE`), so a date-only Sigma format passes through unchanged. Sigma returns a datetime; a format carrying time components falls back to `sql_date_time_op ( "TO_TIMESTAMP({0}, 'YYYY-MM-DD HH24:MI:SS')" , [s] )` because `to_date` drops the time ([**E3**](#how-to-read-the-tables)). |
| `DateTrunc(precision, d, tz)` | direct | per-precision `start_of_*` — see the truncation table | not translated | **ThoughtSpot has no `date_trunc`.** 9 of 10 precisions native; `"second"` falls back to `sql_date_time_op`. |
| `Day(d)` | direct | `day ( [d] )` | `EXTRACT(DAY FROM d)` (`:356`) | |
| `DayOfYear(d)` | direct | `day_number_of_year ( [d] )` | not translated | |
| `EndOfMonth(d)` | direct | `add_days ( start_of_month ( add_months ( [d] , 1 ) ) , -1 )` | not translated | No native month-end; the composition is exact. |
| `Hour(d)` | direct | `hour_of_day ( [d] )` | `EXTRACT(HOUR FROM d)` (`:357`) | Not `hour`, which does not exist (Power BI map, BL-171). |
| `InDateRange(d, dir, unit, n, offset, today)` | direct | `"current"`: `start_of_month ( [d] ) = start_of_month ( today ( ) )`; `"last"`, `n`: `[d] >= add_months ( start_of_month ( today ( ) ) , - n ) and [d] < start_of_month ( today ( ) )` | not translated | Per `unit` the `start_of_*` / `add_*` pair changes; `"to_date"` is `[d] >= start_of_year ( today ( ) ) and [d] <= today ( )`. Whether Sigma's `"last"` excludes the current period is not stated on the reference page — the composition assumes it does (flagged). Sub-day units fall back to `sql_bool_op` ([**E3**](#how-to-read-the-tables)). |
| `InPriorDateRange(d, range, prior, n, today)` | direct | `("month", "year")`: `start_of_month ( [d] ) = start_of_month ( add_years ( today ( ) , - 1 ) )` | not translated | The current `range` bucket shifted back `n` `prior` periods. Sub-day `range` units fall back to `sql_bool_op` ([**E3**](#how-to-read-the-tables)). |
| `LastDay(d, precision)` | direct | `"month"`: `add_days ( start_of_month ( add_months ( [d] , 1 ) ) , -1 )`; `"quarter"`/`"year"`/`"week"` analogously from `start_of_quarter`/`start_of_year`/`start_of_week` | not translated | Sigma returns the **last instant** (23:59:59) of the period as a timestamp; the composition returns the last *date*. Equal for date-grain comparisons; for a timestamp result use `sql_date_time_op ( "DATEADD('second', -1, DATEADD('month', 1, DATE_TRUNC('month', {0})))" , [d] )`. `"week"` uses the Sunday-start composition from the truncation table. The `"week"` form assumes the Model calendar's Monday week start (Gregorian, Monday-first when nothing else is set — ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. |
| `MakeDate(y, m, d)` | passthrough | `sql_date_op ( "DATE_FROM_PARTS({0}, {1}, {2})" , [y] , [m] , [d] )` | not translated | **Variant: `sql_date_op`.** A native `to_date ( concat ( to_string ( [y] ) , '-' , to_string ( [m] ) , '-' , to_string ( [d] ) ) , '%Y-%m-%d' )` depends on `to_date` accepting un-padded month/day — unverified. |
| `Minute(d)` | passthrough | `sql_int_op ( "MINUTE({0})" , [d] )` | `EXTRACT(MINUTE FROM d)` (`:358`) | **Variant: `sql_int_op`.** No native minute extractor (Ossie map; Power BI map). |
| `Month(d)` | direct | `month_number ( [d] )` | `EXTRACT(MONTH FROM d)` (`:355`) | **Not `month ( )`**, which returns the name. |
| `MonthName(d)` | direct | `month ( [d] )` | not translated | Full month name on both sides; locale-dependent. |
| `Now()` | direct | `now ( )` | `CURRENT_TIMESTAMP` (`:574-575`) | Sigma evaluates in the **organisation's** account timezone; ThoughtSpot in the warehouse/cluster setting. Same instant, possibly a different wall-clock date near midnight — flagged per model. |
| `Quarter(d)` | direct | `quarter_number ( [d] )` | `EXTRACT(QUARTER FROM d)` (`:360`) | |
| `Second(d)` | passthrough | `sql_int_op ( "SECOND({0})" , [d] )` | `EXTRACT(SECOND FROM d)` (`:359`) | **Variant: `sql_int_op`.** |
| `Today()` | direct | `today ( )` | `CURRENT_DATE` (`:572-573`) | Timezone caveat as `Now`. |
| `Weekday(d, tz)` | direct | `mod ( day_number_of_week ( [d] ) , 7 ) + 1` | not translated; upstream's `dayofweek` key (`:362`) is not a Sigma function and would emit `EXTRACT(DOW …)`, which is 0-based | **Base shift.** Sigma numbers 1 = Sunday … 7 = Saturday; ThoughtSpot `day_number_of_week` is **fixed** 1 = Monday … 7 = Sunday — it compiles to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)`, independent of the warehouse's `WEEK_START` (formula reference, live-verified 2026-10-06). `mod ( 7 , 7 ) + 1 = 1` maps Sunday correctly. A `tz` argument forces a pass-through ([**E11**](#how-to-read-the-tables)). The composition assumes the Model calendar's Monday week start (Gregorian, Monday-first when nothing else is set — ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. |
| `WeekdayName(d)` | direct | `day_of_week ( [d] )` | not translated | Full day name; locale-dependent. |
| `Year(d)` | direct | `year ( [d] )` | `EXTRACT(YEAR FROM d)` (`:354`) | |

### `DatePart` parts *(not counted — arguments)*

| Part | ThoughtSpot | Class |
|---|---|---|
| `"year"` | `year ( [d] )` | direct |
| `"quarter"` | `quarter_number ( [d] )` | direct |
| `"month"` | `month_number ( [d] )` | direct |
| `"week"` | `week_number_of_year ( [d] )` | direct — ThoughtSpot's compiled SQL uses ISO-style Thursday logic (`week_number_of_year(2026-01-04)` = 1, live-verified 2026-10-06); Sigma's rule is not stated — flagged |
| `"day"` | `day ( [d] )` | direct |
| `"weekday"` | `mod ( day_number_of_week ( [d] ) , 7 ) + 1` | direct — Sunday-based, as `Weekday` (fixed Monday base live-verified 2026-10-06); assumes the Model calendar's Monday week start (Gregorian, Monday-first when nothing else is set — ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere |
| `"day_of_year"` | `day_number_of_year ( [d] )` | direct |
| `"hour"` | `hour_of_day ( [d] )` | direct |
| `"minute"` | `sql_int_op ( "MINUTE({0})" , [d] )` | passthrough |
| `"second"` | `sql_int_op ( "SECOND({0})" , [d] )` | passthrough |
| `"millisecond"` | `sql_int_op ( "FLOOR(DATE_PART(NANOSECOND, {0}) / 1000000)" , [d] )` | passthrough — *unverified*; `EXTRACT(MILLISECOND …)` is doubtful in Snowflake, so the nanosecond part is scaled instead |
| `"epoch"` | `sql_int_op ( "DATE_PART(EPOCH_SECOND, {0})" , [d] )` | passthrough |

### `DateTrunc` precisions *(not counted — arguments)*

| Precision | ThoughtSpot | Class |
|---|---|---|
| `"year"` | `start_of_year ( [d] )` | direct |
| `"quarter"` | `start_of_quarter ( [d] )` | direct |
| `"month"` | `start_of_month ( [d] )` | direct |
| `"week"` | `add_days ( start_of_week ( add_days ( [d] , 1 ) ) , -1 )` | direct — **Sigma defaults to Sunday-start.** The one-day shift turns the Model calendar's Monday-start truncation into a Sunday-start one; it assumes the Model calendar's Monday week start (Gregorian, Monday-first when nothing else is set — ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. Formula translations do not pass a calendar argument — the Model supplies the calendar. Residual caveat: the default form compiled to Snowflake `DATE_TRUNC(week, d)`, which is Monday only while `WEEK_START` is 0 or 1 (BL-334) |
| `"week_starting_sunday"` / `"week_starting_monday"` | Sunday: as `"week"`; Monday: `start_of_week ( [d] )` | direct — both assumes the Model calendar's Monday week start (Gregorian, Monday-first when nothing else is set — ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere (BL-334 residual caveat applies). An explicit week-start setting in the source is a note for the Model's calendar, not a formula change |
| `"day"` | `date ( [d] )` | direct |
| `"hour"` | `start_of_hour ( [d] )` | direct |
| `"minute"` | `start_of_min ( [d] )` | direct — `start_of_min`, not `start_of_minute` |
| `"second"` | `sql_date_time_op ( "DATE_TRUNC('second', {0})" , [d] )` | passthrough |

### `DateAdd` / `DateDiff` units *(not counted — arguments)*

| Unit | `DateAdd(unit, n, d)` → | `DateDiff(unit, start, end)` → |
|---|---|---|
| `"day"` | `add_days ( [d] , n )` | `diff_days ( [end] , [start] )` |
| `"week"` | `add_weeks ( [d] , n )` | `diff_weeks ( [end] , [start] )` |
| `"month"` | `add_months ( [d] , n )` | `diff_months ( [end] , [start] )` |
| `"quarter"` | `add_months ( [d] , 3 * n )` | `diff_quarters ( [end] , [start] )` |
| `"year"` | `add_years ( [d] , n )` | `diff_years ( [end] , [start] )` |
| `"hour"` | `add_minutes ( [d] , 60 * n )` | `diff_hours ( [end] , [start] )` |
| `"minute"` | `add_minutes ( [d] , n )` | `diff_minutes ( [end] , [start] )` |
| `"second"` | `add_seconds ( [d] , n )` | `diff_time ( [end] , [start] )` |
| `"millisecond"` | — (not a `DateAdd` unit) | `sql_int_op ( "DATEDIFF('millisecond', {0}, {1})" , [start] , [end] )` |

---

## Financial functions

Source: Sigma function index, "Financial Functions". **Sigma's reference pages were not
read row by row; argument orders below are assumed Excel-compatible** (`Pmt(rate, nper, pv,
[fv], [type])` etc.), which every financial row should confirm before implementation. Every
row is closed-form arithmetic over native `pow`, `ln` and `if`, so all are `direct` by
[**E2**](#how-to-read-the-tables). Each annuity formula divides by `rate`, so each carries a
`rate = 0` branch.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `CAGR(end, start, periods)` | direct | `pow ( [end] / [start] , 1 / [periods] ) - 1` | not translated | `pow`, not `power`. |
| `Effect(nominal, npery)` | direct | `pow ( 1 + [nominal] / [npery] , [npery] ) - 1` | not translated | |
| `FV(r, n, pmt, pv, type)` | direct | `if ( [r] = 0 ) then - ( [pv] + [pmt] * [n] ) else - ( [pv] * pow ( 1 + [r] , [n] ) + [pmt] * ( 1 + [r] * [type] ) * ( pow ( 1 + [r] , [n] ) - 1 ) / [r] )` | not translated | Excel sign convention (cash out negative). Omitted optionals default to `0`. |
| `IPmt(r, per, n, pv, fv, type)` | direct | `[FV at per − 1] * [r]` — i.e. the `FV` composition with `n` → `per - 1` and `pmt` → the `Pmt` composition, times `[r]` | not translated | Exact for `type = 0` (the Excel identity `IPMT = FV(r, per−1, PMT, pv) × r`); `type = 1` additionally divides by `1 + r` and is `0` at `per = 1`. Emit `Pmt` as its own formula and reference it by id. |
| `Nominal(effect, npery)` | direct | `[npery] * ( pow ( 1 + [effect] , 1 / [npery] ) - 1 )` | not translated | |
| `NPer(r, pmt, pv, fv, type)` | direct | `if ( [r] = 0 ) then - ( [pv] + [fv] ) / [pmt] else ln ( ( [pmt] * ( 1 + [r] * [type] ) - [fv] * [r] ) / ( [pmt] * ( 1 + [r] * [type] ) + [pv] * [r] ) ) / ln ( 1 + [r] )` | not translated | |
| `Pmt(r, n, pv, fv, type)` | direct | `if ( [r] = 0 ) then - ( [pv] + [fv] ) / [n] else - ( [r] * ( [pv] * pow ( 1 + [r] , [n] ) + [fv] ) ) / ( ( 1 + [r] * [type] ) * ( pow ( 1 + [r] , [n] ) - 1 ) )` | not translated | |
| `PPmt(r, per, n, pv, fv, type)` | direct | `[Pmt] - [IPmt]` | not translated | By definition; both referenced by formula id. |
| `PV(r, n, pmt, fv, type)` | direct | `if ( [r] = 0 ) then - ( [fv] + [pmt] * [n] ) else - ( [fv] + [pmt] * ( 1 + [r] * [type] ) * ( pow ( 1 + [r] , [n] ) - 1 ) / [r] ) / pow ( 1 + [r] , [n] )` | not translated | |
| `XNPV(r, values, dates)` | direct | `sum ( [v] / pow ( 1 + [r] , diff_days ( [d] , group_aggregate ( min ( [d] ) , query_groups ( ) , query_filters ( ) ) ) / 365 ) )` | not translated | An aggregate over cash-flow rows, discounted from the first date **of each result row's own cash-flow set** — hence `query_groups ( )`, as in the Excel map's `XNPV` row; `{ }` would discount every group from the single earliest date in the whole result. **Uncertain:** that a `group_aggregate` may sit inside a `sum` argument is not verified (the formula reference shows `group_*` beside aggregates, not inside them); if rejected, split the first-date LOD into its own formula and reference it. Sigma's exact argument shape (columns vs arrays) not confirmed. |

---

## Geography functions

Source: Sigma function index, "Geography Functions". ThoughtSpot formulas have **no
geography type** — the same wall as arrays. Scalar-returning functions over a warehouse
`GEOGRAPHY` column are `passthrough`; constructors are `unmappable`. ThoughtSpot's
geo-visualisation consumes latitude/longitude columns, which is why `Latitude`/`Longitude`
matter most. (`Text`/`Json` geography overloads are rowed under Type, per
[**E1**](#how-to-read-the-tables).)

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Area(g, unit)` | passthrough | `sql_double_op ( "ST_AREA({0})" , [g] )` | not translated | **Variant: `sql_double_op`.** Snowflake returns square metres; a non-metre `unit` is a factor baked into the template. |
| `Centroid(g)` | unmappable | — issue | not translated | Returns a geography. Its *coordinates* are reachable: `sql_double_op ( "ST_Y(ST_CENTROID({0}))" , [g] )`. |
| `Distance(g1, g2, unit)` | passthrough | `sql_double_op ( "ST_DISTANCE({0}, {1})" , [g1] , [g2] )` | not translated | **Variant: `sql_double_op`.** Metres; unit factor baked in. For two point *coordinates* use `DistanceGlobe`, which is `direct`. |
| `Geography(text)` | unmappable | — issue | not translated | Constructor. |
| `Intersects(g1, g2)` | passthrough | `sql_bool_op ( "ST_INTERSECTS({0}, {1})" , [g1] , [g2] )` | not translated | **Variant: `sql_bool_op`.** |
| `Latitude(p)` | passthrough | `sql_double_op ( "ST_Y({0})" , [p] )` | not translated | **Variant: `sql_double_op`.** |
| `Longitude(p)` | passthrough | `sql_double_op ( "ST_X({0})" , [p] )` | not translated | **Variant: `sql_double_op`.** |
| `MakeLine(…)` | unmappable | — issue | not translated | Constructor. |
| `MakePoint(lat, lon)` | unmappable | — issue | not translated | Constructor. In ThoughtSpot the latitude and longitude columns themselves are the geo inputs, so the usual intent is met structurally by marking those two columns with geo properties. |
| `Perimeter(g, unit)` | passthrough | `sql_double_op ( "ST_PERIMETER({0})" , [g] )` | not translated | **Variant: `sql_double_op`.** |
| `Within(g1, g2)` | passthrough | `sql_bool_op ( "ST_WITHIN({0}, {1})" , [g1] , [g2] )` | not translated | **Variant: `sql_bool_op`.** |

---

## Join functions

Source: Sigma function index, "Join Functions". These are joins written as formulas; the
ThoughtSpot home is the Model's `model_tables[].joins[]`, after which the looked-up column is
an ordinary column reference.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Lookup(f, local1, ext1, …)` | structural | Model join `on [LOCAL::k1] = [EXT::k1] and …`, then `[EXT::col]` (or the aggregate `f` over it) | not translated (parse succeeds; `lookup` has no mapping, `:592`) | One join per distinct (target element, key set). A non-aggregated `Lookup` with several matching rows is ambiguous in Sigma (the page does not say which row wins); in ThoughtSpot it fans out the join, so declare the join many-to-one only when the external key is unique. Sigma restricts one `Lookup` to one external element, which is exactly one join. |
| `LookupMatchNulls(f, local1, ext1, …)` | unmappable | — issue | not translated | Null-matching join keys. A ThoughtSpot Model join is an equi-join on columns and does not match `NULL = NULL`; the workaround is a warehouse view that coalesces both keys to a sentinel, which is a model change outside formula scope. |
| `Rollup(f, local1, ext1, …)` | structural | Cross-element: Model join + `f` aggregated over the joined table. **Self-rollup** (same element both sides): `group_aggregate ( sum ( [x] ) , { [k1] } , query_filters ( ) )` — `direct` ([**E3**](#how-to-read-the-tables)) | not translated | The self-rollup case is a fixed-grain LOD and needs no join at all — the Rollup reference page's own example (average margin per order) is this shape. Cross-element rollups are a join plus an aggregate; ThoughtSpot's join-path aggregation handles the fan-out. |

---

## Logical functions

Source: Sigma function index, "Logical Functions".

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Between(x, lo, hi)` | direct | `[x] between [lo] and [hi]` | not translated | Inclusive on both sides (assumed; the Sigma page says "within the range"). |
| `Choose(i, v1, v2, …)` | direct | `if ( [i] = 1 ) then [v1] else if ( [i] = 2 ) then [v2] else null` | not translated | 1-based; out-of-range is Null on both sides ([**E9**](#how-to-read-the-tables)). |
| `Coalesce(a, b, c)` | direct | `ifnull ( [a] , ifnull ( [b] , [c] ) )` | `COALESCE(a, b, c)` (`:350`) | `ifnull` is strictly two-argument, so N-ary nests right (Ossie map, `COALESCE`). |
| `If(c1, v1, c2, v2, …, else)` | direct | `if ( c1 ) then v1 else if ( c2 ) then v2 else d` | **three-argument form only** (`:538-539`); multi-branch `If` and two-argument `If` (no else) are not translated | **Parentheses around each condition are mandatory** (formula reference). A missing `else` becomes `else null` ([**E9**](#how-to-read-the-tables)). |
| `In(x, c1, c2, …)` | direct | `[x] in { 'a' , 'b' , 'c' }` | not translated | **Curly braces** (formula reference; live-verified BL-170) — forces `>-` YAML. Sigma also accepts **column** candidates (`In("John", [Customers], [Buyers])`); ThoughtSpot `in` takes literals only, so a column candidate list becomes `[x] = [c1] or [x] = [c2]`. |
| `IsNotNull(x)` | direct | `not ( isnull ( [x] ) )` | `NOT x IS NULL` (`:544-545`) | |
| `IsNull(x)` | direct | `isnull ( [x] )` | `x IS NULL` (`:542-543`) | |
| `Switch(v, k1, r1, k2, r2, …, else)` | direct | `if ( [v] = k1 ) then r1 else if ( [v] = k2 ) then r2 else d` | not translated | Expanded to equality per branch; missing `else` → `else null`. **A `Switch` on a parameter selecting a dimension** (the Sigma page's own example) is a dynamic-dimension pattern — it translates as written, but the parameter reference makes it non-portable (Ossie map [E9](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)). |
| `Zn(x)` | direct | `ifnull ( [x] , 0 )` | not translated | Tableau `ZN` decision. For a bare measure inside an aggregate the Tableau map strips `ifnull ( X , 0 )` (pipeline step 13b) because aggregation ignores nulls — except `average`, where zero-vs-null changes the denominator. |

---

## Math functions

Source: Sigma function index, "Math Functions". **Sigma trigonometry is in radians** (Sin
reference page), and so is ThoughtSpot's (`sin ( 30 )` compiles to `SIN(30)`, live 2026-10-07,
probe record §7), so the trig rows are the identity. **Corrected 2026-10-07 (BL-364):** they
converted by `180 / π` on an unprobed "ThoughtSpot is degrees" assumption.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Abs(x)` | direct | `abs ( [x] )` | `ABS(x)` (`:342`) | |
| `Acos(x)` | direct | `acos ( [x] )` | not translated | Radians on both sides (BL-364). |
| `Asin(x)` | direct | `asin ( [x] )` | not translated | |
| `Atan(x)` | direct | `atan ( [x] )` | not translated | |
| `Atan2(y, x)` | passthrough | `sql_double_op ( "ATAN2({0}, {1})" , [y] , [x] )` | not translated | **Variant: `sql_double_op`.** Quadrant-aware; same reasoning as the Ossie map and Tableau map. Sigma's argument order (y, x) assumed from convention — the page was not read. |
| `BinFixed(v, min, max, n)` | direct | `if ( [v] < [min] ) then 0 else if ( [v] >= [max] ) then [n] + 1 else floor ( ( [v] - [min] ) / ( ( [max] - [min] ) / [n] ) ) + 1` | not translated | Bins `1…n`, with `0` below and `n + 1` at or above `max`, exactly as documented. Tableau-bin precedent (Tableau map, "Tableau Bins"). |
| `BinRange(v, b1, b2, …)` | direct | `if ( [v] < b1 ) then 0 else if ( [v] < b2 ) then 1 else … else k` | not translated | Lower-bound bins as an `if` chain. Bin numbering at the boundaries assumed lower-inclusive — flagged. |
| `BitAnd(a, b)` | passthrough | `sql_int_op ( "BITAND({0}, {1})" , [a] , [b] )` | not translated | **Variant: `sql_int_op`.** No bitwise operators in ThoughtSpot. |
| `BitOr(a, b)` | passthrough | `sql_int_op ( "BITOR({0}, {1})" , [a] , [b] )` | not translated | **Variant: `sql_int_op`.** |
| `Ceiling(x, f)` | direct | `ceil ( [x] )`; with a factor, `ceil ( [x] / [f] ) * [f]` | `CEIL(x)` (`:344`); **two-argument form is wrong** — `CEIL(x, f)` means *scale* (decimal places) in Snowflake, not Sigma's multiple | Power BI map's two-argument `CEILING` decision. Sigma's sign-of-factor direction rule is matched for a positive factor; a negative factor is flagged. |
| `Cos(x)` | direct | `cos ( [x] )` | not translated | Radians on both sides. |
| `Cot(x)` | direct | `( 1 / tan ( [x] ) )` | not translated | Tableau map `COT`. |
| `Degrees(x)` | direct | `( ( [x] * 180 ) / sql_double_op ( "PI()" ) )` | not translated | Bracketed: ThoughtSpot reads `a * b / c` as `a * ( b / c )` (BL-365). |
| `DistanceGlobe(lat1, lon1, lat2, lon2)` | direct | `2 * 6371 * asin ( sqrt ( pow ( sin ( ( ( [lat2] - [lat1] ) * sql_double_op ( "PI()" ) ) / 360 ) , 2 ) + cos ( ( [lat1] * sql_double_op ( "PI()" ) ) / 180 ) * cos ( ( [lat2] * sql_double_op ( "PI()" ) ) / 180 ) * pow ( sin ( ( ( [lon2] - [lon1] ) * sql_double_op ( "PI()" ) ) / 360 ) , 2 ) ) )` | not translated | Haversine. Coordinates are in degrees and ThoughtSpot's trigonometry in radians, so each angle converts on the way in (`/ 2` folded into `/ 360`); `asin` returns radians, which the arc length wants. **Corrected 2026-10-07 (BL-364)** from a degrees-native form. **Uncertain:** Sigma's earth radius and formula (haversine vs spheroidal) are not documented on the index; the result agrees to <0.5% either way. |
| `DistancePlane(x1, y1, x2, y2)` | direct | `sqrt ( pow ( [x2] - [x1] , 2 ) + pow ( [y2] - [y1] , 2 ) )` | not translated | |
| `Div(a, b)` | direct | `if ( [a] / [b] >= 0 ) then floor ( [a] / [b] ) else ceil ( [a] / [b] )` | not translated | "Integer component of a division." **Uncertain:** Sigma does not say whether negative quotients truncate or floor; truncation (shown) is the "integer component" reading. The Tableau map's `DIV` uses `floor ( safe_divide ( ) )`, whose zero-divisor result is 0 not Null. |
| `Exp(x)` | direct | `exp ( [x] )` | not translated | |
| `Floor(x, f)` | direct | `floor ( [x] )`; with a factor, `floor ( [x] / [f] ) * [f]` | `FLOOR(x)` (`:345`); two-argument form wrong, as `Ceiling` | |
| `Greatest(a, b, …)` | direct | `greatest ( [a] , [b] , … )` | not translated | Never `max`. |
| `Int(x)` | direct | `floor ( [x] )` | not translated | **Sigma `Int` floors** (`Int(-3.2) = -4`, reference page) — unlike Tableau `INT`, which truncates and needs the sign-branch composite. Do not copy the Tableau row. |
| `IsEven(x)` | direct | `mod ( if ( [x] >= 0 ) then floor ( [x] ) else ceil ( [x] ) , 2 ) = 0` | not translated | "Integer part" = truncation. `mod` of a negative follows the warehouse (Snowflake: sign of dividend), which `= 0` is insensitive to. |
| `IsOdd(x)` | direct | `mod ( if ( [x] >= 0 ) then floor ( [x] ) else ceil ( [x] ) , 2 ) != 0` | not translated | `!= 0`, not `= 1`, because `mod ( -3 , 2 )` is `-1` on Snowflake. |
| `Least(a, b, …)` | direct | `least ( [a] , [b] , … )` | not translated | Never `min`. |
| `Ln(x)` | direct | `ln ( [x] )` | not translated | |
| `Log(x, base)` | direct | `log10 ( [x] )`; base 2 → `log2 ( [x] )`; other → `safe_divide ( ln ( [x] ) , ln ( [base] ) )` | not translated | **Sigma's argument order is (value, base)** with base defaulting to 10 — the reverse of SQL `LOG(base, x)`. |
| `Mod(a, b)` | direct | `mod ( [a] , [b] )` | `MOD(a, b)` (`:349`) | |
| `MRound(x, f)` | direct | `round ( [x] , abs ( [f] ) )` | not translated | ThoughtSpot `round`'s second argument **is a rounding increment** (live probe, se-thoughtspot 2026-10-06 — see `Round`), which is exactly `MRound`. **The `abs ( )` is load-bearing:** the probe gave `round ( x , -2 )` = 1234 on 1234.5678 (`-2 * ROUND(x / -2)`, i.e. nearest multiple of 2), not 1200. Sigma ignores the factor's sign; its own example (`MRound(-456, 100)` → `500`) is not explained by "nearest multiple" — flagged. |
| `Pi()` | direct | `sql_double_op ( "PI()" )` | not translated | The warehouse's double; a literal under `/` is fixed-point (BL-365). |
| `Power(x, y)` | direct | `pow ( [x] , [y] )` | `POWER(x, y)` (`:348`) | `power` is rejected by ThoughtSpot's parser. |
| `Radians(x)` | direct | `( ( [x] * sql_double_op ( "PI()" ) ) / 180 )` | not translated | |
| `Round(x, d)` | direct | `round ( [x] , 1 )` for `d` omitted/0; `round ( [x] , 0.01 )` for `d = 2`; `round ( [x] , 100 )` for `d = -2` | `ROUND(x, d)` (`:343`) | **The increment is `10^-d`, not `d` — settled by live probe on se-thoughtspot, 2026-10-06:** ThoughtSpot compiles `round ( x , n )` to `n * ROUND(x / NULLIF(n, 0))`; on 1234.5678, `round ( x , 0 )` = NULL, `round ( x , 2 )` = 1234, `round ( x , 0.01 )` = 1234.57, `round ( x , 10 )` = 1230, `round ( x , -2 )` = 1234. (Agrees with the Power BI map and `ts_cli/powerbi/functions.py:455-464`.) A non-literal `d` falls back to `sql_double_op ( "ROUND({0}, {1})" , [x] , [d] )` ([**E3**](#how-to-read-the-tables)). The Ossie and Tableau maps' digit-count rows are corrected by BL-331 (PR #558) — see V1. Second hop: an Ossie consumer following the Ossie map would emit `round ( [x] , 2 )` and round to the nearest 2. |
| `RoundDown(x, d)` | direct | `floor ( [x] * 100 ) / 100` for `d = 2` | not translated | **Toward negative infinity** — the reference page's `RoundDown(-6.25417, 3) = -6.255`. `10^d` baked in for a literal `d`. Float-representation edge values (`x * 10^d` landing a hair below an integer) are a known hazard of the composition. |
| `RoundUp(x, d)` | direct | `ceil ( [x] * 100 ) / 100` for `d = 2` | not translated | Mirror of `RoundDown`, **assumed** toward positive infinity — the page was not read; flagged. |
| `RowAvg(a, b, …)` | direct | `( ifnull ( [a] , 0 ) + ifnull ( [b] , 0 ) ) / ( ( if ( not ( isnull ( [a] ) ) ) then 1 else 0 ) + ( if ( not ( isnull ( [b] ) ) ) then 1 else 0 ) )` | not translated | Row-wise mean ignoring nulls (assumed, by analogy with aggregate `Avg`); all-null yields a divide-by-zero → Null on Snowflake. |
| `Sign(x)` | direct | `if ( [x] > 0 ) then 1 else if ( [x] < 0 ) then -1 else 0` | not translated | |
| `Sin(x)` | direct | `sin ( [x] )` | not translated | Radians on both sides (BL-364). |
| `Sqrt(x)` | direct | `sqrt ( [x] )` | `SQRT(x)` (`:346`) | |
| `Tan(x)` | direct | `tan ( [x] )` | not translated | |
| `Trunc(x, d)` | direct | `if ( [x] >= 0 ) then floor ( [x] * 100 ) / 100 else ceil ( [x] * 100 ) / 100` for `d = 2` | not translated | Toward zero, by sign branch — the same exact composite the Tableau map uses for `INT`. **This is a deliberate departure from the Ossie map**, which rows `TRUNC` as `passthrough` because neither `floor` nor `round` alone is a substitute; the sign-branched pair is. Negative `d` zeroes integer digits: `floor ( [x] / 100 ) * 100` on the positive branch. Float caveat as `RoundDown`. |

---

## Passthrough functions

Source: Sigma function index, "Passthrough Functions". These are Sigma's own
`sql_*_op`: a warehouse function **name** plus arguments, typed by return. The ThoughtSpot
template is built mechanically — `CallNumber("uniform", 1, 10, [x])` becomes
`sql_double_op ( "uniform({0}, {1}, {2})" , 1 , 10 , [x] )`, or with literals baked into the
template. The dialect is already the warehouse's, so no re-derivation is needed when the
ThoughtSpot connection points at the same warehouse — the one place in this map where the
pass-through caveat is weakest.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `AggDatetime(fn, …)` | passthrough | `sql_date_time_aggregate_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_date_time_aggregate_op`.** |
| `AggGeography(fn, …)` | unmappable | — issue | not translated | No geography type. |
| `AggLogical(fn, …)` | unmappable | — issue | not translated | **There is no boolean aggregate variant** in the `sql_*_op` family (formula reference, *SQL Pass-Through Functions*). `sql_int_aggregate_op ( "IFF(BOOLAND_AGG({0}), 1, 0)" , [x] )` is an available 0/1 downgrade that changes the type. |
| `AggNumber(fn, …)` | passthrough | `sql_double_aggregate_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_double_aggregate_op`** (`sql_int_aggregate_op` when the function is integer-valued). |
| `AggText(fn, …)` | passthrough | `sql_string_aggregate_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_string_aggregate_op`.** |
| `AggVariant(fn, …)` | unmappable | — issue | not translated | No variant type; a JSON-text downgrade is `sql_string_aggregate_op ( "TO_JSON(fn({0}))" , [x] )`. |
| `CallDatetime(fn, …)` | passthrough | `sql_date_time_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_date_time_op`** (`sql_date_op` when the function returns a DATE). |
| `CallGeography(fn, …)` | unmappable | — issue | not translated | No geography type. |
| `CallLogical(fn, …)` | passthrough | `sql_bool_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_bool_op`.** |
| `CallNumber(fn, …)` | passthrough | `sql_double_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_double_op`** (`sql_int_op` when integer-valued). |
| `CallText(fn, …)` | passthrough | `sql_string_op ( "fn({0})" , [x] )` | not translated | **Variant: `sql_string_op`.** A JSON path inside the call must be in bracket notation (formula reference, *JSON / VARIANT path access*). |
| `CallVariant(fn, …)` | unmappable | — issue | not translated | No variant type; JSON-text downgrade via `sql_string_op ( "TO_JSON(fn({0}))" , [x] )`. |

---

## System functions

Source: Sigma function index, "System Functions". These resolve the signed-in user at query
time — ThoughtSpot's system variables are the analogue (formula reference, *System Variables*).

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `CurrentTimezone()` | unmappable | — issue | not translated | The **organisation's** zone. `ts_var ( ts_user_timezone )` is the *user's* and is the only `ts_var` the formula editor supports; it is a different value, so substituting it is not a translation. |
| `CurrentUserAttributeText(attr)` | structural | RLS rule using `ts_var ( attr_var )` on the Table, with a formula variable per attribute | not translated | `ts_var ( )` in **formulas** supports only `ts_user_timezone`; arbitrary formula variables work in RLS rules (formula reference). Sigma user attributes are almost always row-security inputs, so the construct moves from the formula to the Table's row security. RLS is not exported in TML. |
| `CurrentUserEmail()` | direct | `ts_username` | not translated | Exact only where ThoughtSpot usernames are email addresses (the usual SSO configuration) — the converter must confirm, and raise an issue otherwise. `ts_email_domain` covers domain-only comparisons exactly. |
| `CurrentUserFirstName()` | unmappable | — issue | not translated | No ThoughtSpot variable carries profile names. |
| `CurrentUserFullName()` | unmappable | — issue | not translated | As above. |
| `CurrentUserInTeam(team)` | direct | `'Team Name' in ts_groups` | not translated | Sigma teams ↔ ThoughtSpot groups by name; exact when group names are mirrored. |

---

## Text functions

Source: Sigma function index, "Text Functions". Only `concat`, `substr`, `left`, `right`,
`strlen`, `strpos` and `contains` are native ThoughtSpot string functions (formula
reference, BL-170) — which is why this is the densest pass-through section. **And the
native ones compare case-insensitively** (`contains`, `strpos` and `=` compile to `LOWER(…)`,
literals lowercased; live-verified 2026-10-06 on se-thoughtspot, BL-333), so every Sigma text
test documented as case-sensitive is a `passthrough` to the warehouse function, which is
case-sensitive under Snowflake's default collation. The native forms remain correct on
case-consistent data.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Concat(a, b, …)` | direct | `concat ( [a] , [b] , … )` | `a \|\| b` (`:559-560`) | `+` never concatenates in ThoughtSpot. |
| `Contains(s, sub)` | passthrough | `sql_bool_op ( "CONTAINS({0}, {1})" , [s] , [sub] )` | `s LIKE '%' \|\| sub \|\| '%'` (`:562-564`) | **Variant: `sql_bool_op`. Reclassified from `direct` 2026-10-06.** Sigma documents Contains as case-sensitive ("Arguments are case sensitive", reference page); ThoughtSpot string comparison is case-insensitive — `contains`, `strpos` and `=` compile to `LOWER(…)` with literals lowercased at compile time (formula reference, *String comparison is case-insensitive*, live-verified 2026-10-06 on se-thoughtspot; BL-333), so native `contains ( [s] , [sub] )` matches `Engineering` for `'eng'`. Snowflake `CONTAINS` is case-sensitive under the default collation, so the pass-through is exact. The native form is acceptable only where the data's case is consistent. **Second-hop loss:** the generated pattern is a concatenation, not a literal, so the Ossie map's `LIKE` row (which recognises `'%foo%'` literals) falls back to `sql_bool_op`, and a `%` or `_` inside `sub` becomes a wildcard. |
| `EndsWith(s, suf)` | passthrough | `sql_bool_op ( "ENDSWITH({0}, {1})" , [s] , [suf] )` | `s LIKE '%' \|\| suf` (`:567-568`) | **Variant: `sql_bool_op`. Reclassified from `direct` 2026-10-06.** Sigma: "EndsWith is case-sensitive" (reference page). The native composition `( substr ( [s] , strlen ( [s] ) - strlen ( [suf] ) , strlen ( [suf] ) ) = [suf] )` ends in `=`, which ThoughtSpot lowercases (BL-333) — the composed form itself was not probed. Snowflake `ENDSWITH` is case-sensitive under the default collation. Native composition acceptable only on case-consistent data (no native `ends_with`, BL-170). Same second-hop loss as `Contains`. |
| `Find(s, sub)` | passthrough | `sql_int_op ( "POSITION({1} IN {0})" , [s] , [sub] )` | not translated | **Variant: `sql_int_op`. Reclassified from `direct` 2026-10-06.** Sigma's `Find` is case-sensitive (reference page); ThoughtSpot `strpos` compiles to `POSITION('sub' IN LOWER(s))` (BL-333, live-verified 2026-10-06), so the native `strpos ( [s] , [sub] )` — otherwise the identical contract: 1-based, 0 when absent, haystack first (Tableau map `FIND`) — is exact only on case-consistent data. Snowflake `POSITION` without `LOWER` is case-sensitive under the default collation. |
| `ILike(s, pattern)` | direct | `'%foo%'` → `contains ( [s] , 'foo' )`; `'foo%'` → `( strpos ( [s] , 'foo' ) = 1 )` | not translated | **Reclassified from `passthrough` 2026-10-06.** ThoughtSpot's native string comparison *is* case-insensitive (BL-333, live-verified 2026-10-06), so the `Like` shape analysis gives `ILike` its native form. The `'%foo'` shape relies on `=` over a `substr` expression lowercasing (observed for column = literal only, so flagged) and interior `%`/`_` fall back to `sql_bool_op ( "{0} ILIKE {1}" , [s] , [pattern] )` ([**E3**](#how-to-read-the-tables)). |
| `Left(s, n)` | direct | `left ( [s] , n )` | `SUBSTRING(s, 1, n)` (`:488-489`) | |
| `Len(s)` | direct | `strlen ( [s] )` | **not translated** — upstream maps `length` (`:347`), Sigma's function is `Len` | |
| `Like(s, pattern)` | passthrough | `sql_bool_op ( "{0} LIKE {1}" , [s] , [pattern] )` | not translated | **Variant: `sql_bool_op`. Reclassified from `direct` 2026-10-06.** Case-sensitive on the Sigma side; the native shape analysis (`'foo%'` → `strpos … = 1`, `'%foo%'` → `contains`) now lands on case-insensitive functions (BL-333), so it is exact only on case-consistent data — the same condition `ILike` now meets natively. Snowflake `LIKE` is case-sensitive under the default collation. |
| `LPad(s, n, pad)` | passthrough | `sql_string_op ( "LPAD({0}, 10, '0')" , [s] )` | not translated | **Variant: `sql_string_op`.** `lpad` is an **unverified** ThoughtSpot name (Snowflake formula mapping, BL-226) — never emit it bare. |
| `Lower(s)` | passthrough | `sql_string_op ( "LOWER({0})" , [s] )` | `LOWER(s)` (`:340`) | **Variant: `sql_string_op`.** Second hop lands on the same pass-through. |
| `LTrim(s)` | passthrough | `sql_string_op ( "LTRIM({0})" , [s] )` | not translated | **Variant: `sql_string_op`.** |
| `MD5(s)` | passthrough | `sql_string_op ( "MD5({0})" , [s] )` | not translated | **Variant: `sql_string_op`.** |
| `Mid(s, start, len)` | direct | `substr ( [s] , [start] - 1 , [len] )`; without `len`, `substr ( [s] , [start] - 1 , strlen ( [s] ) - [start] + 1 )` | `SUBSTRING(s, start, len)` (`:497-504`) | **1-based → 0-based** (Mid reference page; formula reference). The `− 1` is mandatory. |
| `Proper(s)` | passthrough | `sql_string_op ( "INITCAP({0})" , [s] )` | not translated | **Variant: `sql_string_op`.** |
| `RegexpCount(s, p)` | passthrough | `sql_int_op ( "REGEXP_COUNT({0}, {1})" , [s] , [p] )` | not translated | **Variant: `sql_int_op`.** |
| `RegexpExtract(s, p)` | passthrough | `sql_string_op ( "REGEXP_SUBSTR({0}, {1})" , [s] , [p] )` | not translated | **Variant: `sql_string_op`.** Snowflake spells it `REGEXP_SUBSTR`. |
| `RegexpMatch(s, p)` | passthrough | `sql_bool_op ( "REGEXP_LIKE({0}, {1})" , [s] , [p] )` | not translated | **Variant: `sql_bool_op`.** Note Snowflake `REGEXP_LIKE` anchors the whole string; if Sigma's `RegexpMatch` is a partial match, wrap the pattern in `.*…​.*` — flagged. |
| `RegexpReplace(s, p, r)` | passthrough | `sql_string_op ( "REGEXP_REPLACE({0}, {1}, {2})" , [s] , [p] , [r] )` | not translated | **Variant: `sql_string_op`.** |
| `Repeat(s, n)` | passthrough | `sql_string_op ( "REPEAT({0}, 3)" , [s] )` | not translated | **Variant: `sql_string_op`.** `repeat` unverified in ThoughtSpot (BL-226). |
| `Replace(s, from, to)` | passthrough | `sql_string_op ( "REPLACE({0}, {1}, {2})" , [s] , [from] , [to] )` | `REPLACE(s, from, to)` (`:569-570`) | **Variant: `sql_string_op`.** No native `replace` (BL-170). |
| `Reverse(s)` | passthrough | `sql_string_op ( "REVERSE({0})" , [s] )` | not translated | **Variant: `sql_string_op`.** |
| `Right(s, n)` | direct | `right ( [s] , n )` | `SUBSTRING(s, LENGTH(s) - n + 1, n)` (`:490-496`) | Second hop reaches `substr`, correct but no longer recognisable as `right`. |
| `RPad(s, n, pad)` | passthrough | `sql_string_op ( "RPAD({0}, 10, ' ')" , [s] )` | not translated | **Variant: `sql_string_op`.** `rpad` unverified (BL-226). |
| `RTrim(s)` | passthrough | `sql_string_op ( "RTRIM({0})" , [s] )` | not translated | **Variant: `sql_string_op`.** |
| `SHA256(s)` | passthrough | `sql_string_op ( "SHA2({0}, 256)" , [s] )` | not translated | **Variant: `sql_string_op`.** |
| `SplitPart(s, delim, n)` | passthrough | `sql_string_op ( "SPLIT_PART({0}, {1}, {2})" , [s] , [delim] , [n] )` | not translated | **Variant: `sql_string_op`.** No tokenising function in ThoughtSpot (Ossie map). |
| `StartsWith(s, pre)` | passthrough | `sql_bool_op ( "STARTSWITH({0}, {1})" , [s] , [pre] )` | `s LIKE pre \|\| '%'` (`:565-566`) | **Variant: `sql_bool_op`. Reclassified from `direct` 2026-10-06.** Sigma: "StartsWith is case-sensitive" (reference page). The native `( strpos ( [s] , [pre] ) = 1 )` inherits `strpos`'s lowercasing (BL-333; the composed form was not probed), so it is exact only on case-consistent data (no native `starts_with`, BL-170). Same second-hop loss as `Contains`. |
| `Substring(s, start, len)` | direct | as `Mid` | `SUBSTRING(s, start, len)` (`:497-504`) | Documented with the same signature as `Mid`. |
| `TextJoin(delim, a, b, …)` | direct | `concat ( ifnull ( [a] , '' ) , '-' , ifnull ( [b] , '' ) )` | not translated | Delimiter between values only; Sigma treats Null as `''` and still emits the delimiter (reference page) — the `ifnull` wrappers reproduce that exactly. |
| `Trim(s)` | passthrough | `sql_string_op ( "TRIM({0})" , [s] )` | `TRIM(s)` (`:341`) | **Variant: `sql_string_op`.** No native `trim` (BL-170). |
| `Upper(s)` | passthrough | `sql_string_op ( "UPPER({0})" , [s] )` | `UPPER(s)` (`:339`) | **Variant: `sql_string_op`.** |
| `UrlPart(url, part)` | passthrough | `sql_string_op ( "PARSE_URL({0})['host']" , [url] )` | not translated | **Variant: `sql_string_op`.** `PARSE_URL` returns an OBJECT, so the path **must be bracket notation** — `:host` is rejected by ThoughtSpot's template parser (formula reference, *JSON / VARIANT path access*). |

---

## Type functions

Source: Sigma function index, "Type Functions".

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `Date(x)` | direct | from text: `to_date ( [s] , '%Y-%m-%d' )`; from datetime: `date ( [d] )` | not translated | Sigma returns an ISO datetime; text carrying a time part falls back to `sql_date_time_op ( "TO_TIMESTAMP({0})" , [s] )` ([**E3**](#how-to-read-the-tables)) because `to_date` is date-only. A number argument (Excel serial / Unix) also falls back. |
| `JSON(x)` / `Json(g)` | unmappable | — issue | not translated | Returns a variant (or, on a geography, GeoJSON text). A path *into* the JSON that yields a scalar is reachable: `sql_string_op ( "PARSE_JSON({0})['a']['b']" , [s] )` with bracket notation, and Sigma's `.` path operator lands there (see Operators). The GeoJSON overload is `sql_string_op ( "ST_ASGEOJSON({0})::STRING" , [g] )`. |
| `Logical(x)` | passthrough | `sql_bool_op ( "CAST({0} AS BOOLEAN)" , [x] )` | not translated | **Variant: `sql_bool_op`.** No native boolean conversion (Ossie map, `CAST` target types). |
| `Number(x)` | direct | `to_double ( [x] )` | not translated | Returns NULL on failure, as Sigma does for unparseable text (assumed). |
| `Text(x)` / `Text(g)` | direct | `to_string ( [x] )` | not translated | The geography overload (WKT) is `sql_string_op ( "ST_ASWKT({0})" , [g] )` ([**E3**](#how-to-read-the-tables)). Number formatting of `to_string` vs Sigma `Text` (trailing zeros, scientific notation) not compared — flagged. |
| `Variant(x)` | unmappable | — issue | not translated | No variant type. |

---

## Window functions

Source: Sigma function index, "Window Functions" (Cumulative, Moving, Shifting, Ranking).
**Read [E6](#how-to-read-the-tables) and [E7](#how-to-read-the-tables) first** — they are
why 12 rows here are `direct (downgrade)`: native and live-verified in shape, but faithful only
under E6's precondition, with a partitioned pass-through named as the faithful alternative.
Only `Rank` and `RankPercentile` are plain `direct`, and only for an unpartitioned rank. Every
native row below assumes the sort column was recovered from the
element's `sort` and is a physical column; it is written `[T::sort]`. Every `passthrough`
row's template must declare a partition, which Sigma never states — so the converter fills
`PARTITION BY` with the element's parent grouping keys, wraps the template per the
[passthrough caveat](#passthrough-caveat-applies-to-every-passthrough-row), and the result is
faithful **only for searches whose dimensions are those groupings** (formula reference: every
search dimension must appear in `PARTITION BY`). That is the real cost of a passthrough here,
and it is larger than in the Ossie map, where the source at least named its partition.

**Via Ossie, for every row in this section:** not translated. The upstream converter has no
mapping for any window function (`sigma_formula.py:592`) and documents why — partition and
order come from UI configuration, not formula arguments (`LIMITATIONS.md:99-103`). The sort
and groupings it would need are preserved only as opaque `custom_extensions`
(`LIMITATIONS.md:26-38`). The column is therefore omitted from the tables below.

### Cumulative

| Sigma | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CumulativeAvg(x)` | direct (downgrade) | `cumulative_average ( [T::x] , [T::sort] )` | Precondition per [**E6**](#how-to-read-the-tables). Faithful alternative: `group_aggregate ( sql_double_aggregate_op ( "AVG(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [T::x] , [T::parent] , [T::sort] ) , query_groups ( ) + { [T::parent] } , query_filters ( ) )` — *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)). Note `AVG(SUM(x))` is a running mean of per-row sums, which is what Sigma computes at a grouping level. |
| `CumulativeCorr(x, y)` | passthrough | `sql_double_aggregate_op ( "CORR(SUM({0}), SUM({1})) OVER (PARTITION BY {2} ORDER BY {3} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [x] , [y] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** No windowed correlation. |
| `CumulativeCount(x)` | passthrough | `sql_int_aggregate_op ( "SUM(COUNT({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_int_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** The running count is the running *sum* of per-group counts (`COUNT(COUNT(x)) OVER` would count groups, not rows). `cumulative_count` does not exist (formula reference, live-rejected). The Tableau map suggests `cumulative_sum ( 1 , [sort] )` at answer level and the natural native candidate is `cumulative_sum` over a row-level `if ( not ( isnull ( [x] ) ) ) then 1 else 0` formula — **neither is live-verified**; the row moves to `direct (downgrade)` if one is. |
| `CumeDist(x)` | passthrough | `sql_double_aggregate_op ( "CUME_DIST() OVER (PARTITION BY {1} ORDER BY SUM({0}))" , [x] , [T::parent] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** Not `rank_percentile` (Ossie map, `CUME_DIST`). Sigma lists it under Cumulative; it is a distribution, ordered by the argument rather than the table sort. |
| `CumulativeMax(x)` | direct (downgrade) | `cumulative_max ( [T::x] , [T::sort] )` | Precondition per [**E6**](#how-to-read-the-tables). Faithful alternative: as `CumulativeAvg` with `MAX(SUM({0}))`. |
| `CumulativeMin(x)` | direct (downgrade) | `cumulative_min ( [T::x] , [T::sort] )` | Precondition per [**E6**](#how-to-read-the-tables). Faithful alternative: as `CumulativeAvg` with `MIN(SUM({0}))`. |
| `CumulativeStdDev(x)` | passthrough | `sql_double_aggregate_op ( "STDDEV(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** No ordered `stddev` window. At a grouping level this is the spread of per-group sums, which is Sigma's semantics there; at row grain the inner `SUM` is a no-op. |
| `CumulativeSum(x)` | direct (downgrade) | `cumulative_sum ( [T::x] , [T::sort] )` | Sigma resets "each grouping above the level … independently" (reference page); ThoughtSpot resets on every search dimension except the order columns. Equal only under the [**E6**](#how-to-read-the-tables) precondition. Inner `Sum` stripped per [**E7**](#how-to-read-the-tables). Faithful alternative: `group_aggregate ( sql_double_aggregate_op ( "SUM(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [T::x] , [T::parent] , [T::sort] ) , query_groups ( ) + { [T::parent] } , query_filters ( ) )` — *unverified*. |
| `CumulativeVariance(x)` | passthrough | `sql_double_aggregate_op ( "VARIANCE(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** As `CumulativeStdDev`. |

### Moving

Sigma `Moving*(x, above, below)` and ThoughtSpot `moving_*(x, start, end, sort)` use **the same
offset convention**: `above`/`start` positive = rows back, `below`/`end` positive = rows forward,
and a negative `below` (Sigma's documented `MovingSum([c], 8, -4)`) is a negative `end`
(formula reference: `end` negative = N preceding). So the offsets copy across unchanged —
unlike Tableau, whose negated offsets the Tableau map has to flip. Sigma's `below` defaults to
`0`. Both are row-positional. The partition still differs ([**E6**](#how-to-read-the-tables)),
so the native rows are downgrades. Pass-through frames below are written for
`above = 2, below = 0` and are baked in per occurrence.

| Sigma | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `MovingAvg(x, above, below)` | direct (downgrade) | `moving_average ( [T::x] , above , below , [T::sort] )` | Precondition per [**E6**](#how-to-read-the-tables). Faithful alternative: `group_aggregate ( sql_double_aggregate_op ( "AVG(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)" , [T::x] , [T::parent] , [T::sort] ) , query_groups ( ) + { [T::parent] } , query_filters ( ) )` — *unverified*. |
| `MovingCorr(x, y, above, below)` | passthrough | `sql_double_aggregate_op ( "CORR(SUM({0}), SUM({1})) OVER (PARTITION BY {2} ORDER BY {3} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)" , [x] , [y] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** |
| `MovingCount(x, above, below)` | passthrough | `sql_int_aggregate_op ( "SUM(COUNT({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_int_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** `moving_count` does not exist (live-rejected). Sum of per-group counts, as `CumulativeCount`. |
| `MovingMax(x, above, below)` | direct (downgrade) | `moving_max ( [T::x] , above , below , [T::sort] )` | Precondition per [**E6**](#how-to-read-the-tables); faithful alternative as `MovingAvg` with `MAX(SUM({0}))`. |
| `MovingMin(x, above, below)` | direct (downgrade) | `moving_min ( [T::x] , above , below , [T::sort] )` | Precondition per [**E6**](#how-to-read-the-tables); faithful alternative as `MovingAvg` with `MIN(SUM({0}))`. |
| `MovingStdDev(x, above, below)` | passthrough | `sql_double_aggregate_op ( "STDDEV(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** `moving_stddev` does not exist (live-rejected). |
| `MovingSum(x, above, below)` | direct (downgrade) | `moving_sum ( [T::x] , above , below , [T::sort] )` | `MovingSum([c], 8, -4)` → `moving_sum ( [T::c] , 8 , -4 , [T::sort] )`. Precondition per [**E6**](#how-to-read-the-tables); faithful alternative as `MovingAvg` with `SUM(SUM({0}))`. |
| `MovingVariance(x, above, below)` | passthrough | `sql_double_aggregate_op ( "VARIANCE(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** |

### Shifting

| Sigma | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `FillDown(x)` | passthrough | `sql_double_aggregate_op ( "LAST_VALUE(SUM({0}) IGNORE NULLS) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`** (string sibling with `MAX({0})` for text); ***unverified*** ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)). No null-skipping window natively. |
| `First(x)` | direct (downgrade) | `first_value ( sum ( [T::x] ) , query_groups ( ) , { [T::sort] } )` | The Tableau map's `LOOKUP(agg, FIRST())` decision (tier 5a); the signature is live-verified (formula reference, *Semi-Additive Functions*), the **equivalence is not**. `first_value`'s partition *is* explicit, but it is a semi-additive function over a date axis, and whether `query_groups ( )` reproduces Sigma's "each grouping above the level" when the sort column is itself in the search is open (V6) — so this is a downgrade until probed. A fixed partition `{ [T::parent] }` is accepted (live-confirmed, formula reference) and is the closer candidate when the parent groupings are known. Numeric `x` sorted on a date-like column only. Faithful alternative, and the target for text/date `x`: `sql_double_aggregate_op ( "FIRST_VALUE(SUM({0})) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [T::x] , [T::parent] , [T::sort] )` (`MAX({0})` and the string/date sibling for non-numeric `x`), wrapped per [E8](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row) — *unverified*. |
| `FirstNonNull(x)` | passthrough | `sql_double_aggregate_op ( "FIRST_VALUE(SUM({0}) IGNORE NULLS) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** `first_value` has no ignore-nulls form. |
| `Lag(x, n, default)` | direct (downgrade) | `moving_sum ( [T::x] , n , - n , [T::sort] )` | The single-row-window idiom (formula reference, *Moving Functions*, live-verified). **The Ossie map rejects this idiom as a faithful `LAG`** (its `LAG` row) because `moving_sum` completes its partition from the search; the same objection applies here — Sigma's partition is the parent groupings, ThoughtSpot's is every search dimension minus the order column ([**E6**](#how-to-read-the-tables)) — so it is a documented downgrade, not a translation. Faithful alternative: `group_aggregate ( sql_double_aggregate_op ( "LAG(SUM({0}), 1) OVER (PARTITION BY {1} ORDER BY {2})" , [T::x] , [T::parent] , [T::sort] ) , query_groups ( ) + { [T::parent] } , query_filters ( ) )` — *unverified*; it also carries `default` (as a third `LAG` argument) and non-numeric `x`, which the native idiom cannot: `ifnull ( moving_sum ( … ) , default )` replaces genuine nulls in `x` too. |
| `Last(x)` | direct (downgrade) | `last_value ( sum ( [T::x] ) , query_groups ( ) , { [T::sort] } )` | Mirror of `First` (Tableau tier 5b); same V6 status and the same `LAST_VALUE(SUM({0})) OVER (…)` faithful alternative. |
| `LastNonNull(x)` | passthrough | `sql_double_aggregate_op ( "LAST_VALUE(SUM({0}) IGNORE NULLS) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** |
| `Lead(x, n, default)` | direct (downgrade) | `moving_sum ( [T::x] , - n , n , [T::sort] )` | Mirror of `Lag`; opposite-sign convention. Faithful alternative with `LEAD(SUM({0}), 1)`. |
| `Nth(x, n)` | passthrough | `sql_double_aggregate_op ( "NTH_VALUE(SUM({0}), 3) OVER (PARTITION BY {1} ORDER BY {2} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [x] , [T::parent] , [T::sort] )` | **Variant: `sql_double_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** `nth_value` does not exist (live-rejected). |

### Ranking

| Sigma | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `Ntile(n)` | passthrough | `sql_int_aggregate_op ( "NTILE(4) OVER (PARTITION BY {1} ORDER BY {0})" , [T::sort] , [T::parent] )` | **Variant: `sql_int_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** Ordered by the table sort, which is a `GROUP BY` dimension, so `{0}` stays bare (or the bucketed date expression). |
| `Rank(x, dir)` | direct | `rank ( sum ( [T::x] ) , 'asc' )` | **Not an [E6](#how-to-read-the-tables) row.** ThoughtSpot `rank` is always **global** — no partition at all, arity fixed at two (formula reference, *Rank Functions*, live-proven) — so it is exact for a rank over the whole result set, i.e. a Sigma `Rank` whose table has no parent grouping, and only when the search returns the grain the rank assumed (Ossie map, `RANK`). Competition rank with gaps on both sides (Sigma: 1, 1, 1, 4; ThoughtSpot: 1, 1, 3 — Tableau map). **Sigma defaults to `"asc"`; ThoughtSpot requires the direction**, so it is always emitted. The first argument must be aggregated (live-rejected otherwise), so `x` is wrapped in its grouping-level aggregate. A `Rank` inside a grouped table, which Sigma resets per parent group, falls back to `group_aggregate ( sql_int_aggregate_op ( "rank() over (partition by {0} order by sum({1}) asc)" , [T::parent] , [T::x] ) , query_groups ( ) + { [T::parent] } , query_filters ( ) )` ([**E3**](#how-to-read-the-tables); formula reference, partitioned-rank pattern). Argument-less `Rank()` ranks by the table sort, so `x` = the sort column. |
| `RankDense(x, dir)` | passthrough | `sql_int_aggregate_op ( "DENSE_RANK() OVER (ORDER BY SUM({0}) ASC)" , [T::x] )` | **Variant: `sql_int_aggregate_op`.** `dense_rank` does not exist (live-rejected). Add `PARTITION BY` and the `group_aggregate` wrap inside a grouped table. |
| `RankPercentile(x, dir)` | direct | `1 - rank_percentile ( sum ( [T::x] ) , 'asc' ) / 100` | Sigma returns a 0–1 **percent rank** (first row 0, last 1); ThoughtSpot's `rank_percentile` is `(1 − PERCENT_RANK) × 100` (Snowflake formula mapping), so scale and inversion are both required — the Ossie map's `PERCENT_RANK` composition. Global like `rank` (same two-argument arity), with the same grouped-table fallback. |
| `RowNumber()` | passthrough | `sql_int_aggregate_op ( "ROW_NUMBER() OVER (PARTITION BY {1} ORDER BY {0})" , [T::sort] , [T::parent] )` | **Variant: `sql_int_aggregate_op`; *unverified* ([**E14**](#passthrough-caveat-applies-to-every-passthrough-row)).** `row_number` does not exist; `rank` is not a substitute when sort values tie. |
| `VisibilityLimit(rankfn, n)` | structural | Answer-level top-N: `top 10` in the search, or a filter on a `rank` formula `<= 10` | A display limit, not a value. The Tableau map routes `INDEX() <= N` to the same Top-N machinery (tier 1). |

---

## Operators and constructs

Source: Sigma "Operators overview" (`help.sigmacomputing.com/docs/operators-overview`), plus
Sigma's reference and literal syntax. Upstream tokenizer: `sigma_formula.py:108-120`.

| Sigma | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `a + b` | direct | `[a] + [b]` | `a + b` (`:367`) | Numeric only in ThoughtSpot. Sigma `+` is also numeric (text uses `&`), so there is no overload to unpick. Date + number is not documented in Sigma; use `add_days`. |
| `a - b` | direct | `[a] - [b]` | `a - b` (`:368`) | Two DATE operands → `diff_days ( [a] , [b] )` (Power BI map). |
| `a * b` | direct | `[a] * [b]` | `a * b` (`:369`) | |
| `a / b` | direct | `[a] / [b]` | `a / b` (`:370`) | Not `safe_divide` — that returns 0 where Sigma returns Null. |
| `a ^ b` | direct | `pow ( [a] , [b] )` | `POWER(a, b)` (`:372`, `:470-471`) | |
| `a % b` | direct | `mod ( [a] , [b] )` | **parse error** — `%` is not in the tokenizer's operator class (`:116`), so the whole formula is not translated | ThoughtSpot has no `%` operator. |
| `-x` (unary) | direct | `-[x]` | `-x` (`:458-459`) | |
| `a & b` | direct | `concat ( [a] , [b] )` | `a \|\| b` (`:371`) | |
| `a = b` | direct | `[a] = [b]` | `a = b` | Exact for numeric, date and boolean operands. **Text operands:** ThoughtSpot `=` compiles to `LOWER(col) = 'literal'` (live-verified 2026-10-06, BL-333), whereas Sigma's `=` is evaluated by the warehouse — case-sensitive under Snowflake's default collation (inferred; Sigma's operator page does not state it). Where case matters use `sql_bool_op ( "{0} = {1}" , [a] , [b] )`. |
| `a != b` | direct | `[a] != [b]` | **parse error** — the tokenizer has no `!` (`:108-120`); upstream accepts `<>` instead, which Sigma's operator table does not list | The one comparison operator Sigma documents for inequality.  Text `!=` was **not** probed for lowercasing (BL-333); assume it mirrors `=` only after a test. |
| `a < b` | direct | `[a] < [b]` | `a < b` | |
| `a <= b` | direct | `[a] <= [b]` | `a <= b` | |
| `a > b` | direct | `[a] > [b]` | `a > b` | |
| `a >= b` | direct | `[a] >= [b]` | `a >= b` | |
| `a AND b` | direct | `[a] and [b]` | `a AND b` | |
| `a OR b` | direct | `[a] or [b]` | `a OR b` | |
| `NOT x` | direct | `not ( [x] )` | `NOT x` (`:456-457`) | Function form with parentheses. |
| `TRUE` / `FALSE` | direct | `true` / `false` | `TRUE` / `FALSE` (`:273-275`) | |
| `NULL` (literal) | direct | `null` | **parse error** — `null` is parsed only as a zero-argument *function* `Null()` (`:576-577`), which Sigma does not document; a bare `NULL` token is an identifier not followed by `(` | `null` is live-verified in `else null` (Tableau map). |
| `( … )` grouping | direct | `( … )` | preserved via sqlglot `Paren` (`:384-418`) | Emit explicit parentheses around rewritten sub-expressions (Ossie map). |
| `v.key` (Variant/JSON path) | passthrough | `sql_string_op ( "{0}['key']['sub']" , [v] )` | parse error — `.` outside brackets is not tokenized | **Variant: `sql_string_op`** (or a typed sibling). **Bracket notation is mandatory** inside the template — colon/dot paths are rejected by ThoughtSpot's template parser (formula reference). |
| `[Column]` / `[Element/Column]` | direct | `[TABLE::Column]`, or `[formula_<Name>]` for another formula | `"Column"` / `"Element"."Column"` (`:441-445`) | Resolved from metadata. A reference to another *formula* column uses its **id** so it resolves on first import (CLAUDE.md invariant I9). A cross-element reference implies a relationship and is resolved through the Model join. |
| `"text"` (string literal) | direct | `'text'` | `'text'` (`:264-266`) | [**E8**](#how-to-read-the-tables). |
| `[control-id]` (workbook control / parameter reference) | structural | Model `parameters[]` entry, referenced as `[Parameter Name]` | not modelled — treated as an ordinary column reference by the parser | A Sigma control value used in a formula is a runtime parameter. Static-list and range controls become ThoughtSpot parameters (Tableau map, "Auto-migratable parameters"); any `sql_*_op` that would carry one is non-portable (Ossie map [E9](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)). |

---

## Passthrough caveat (applies to every `passthrough` row)

The `sql_*_op` family embeds raw warehouse SQL: correctness depends on the connection's
dialect, and the expression is opaque to ThoughtSpot's query planner (no automatic
aggregation-grain handling). The converter emits these with a converter issue of
severity=warning so users review each one. Every template above is written for
**Snowflake**; Sigma itself is warehouse-agnostic, so a Sigma model on BigQuery or
Databricks needs every template re-derived (the Databricks formula mapping is the reference
there).

The Ossie map's three operational rules apply unchanged — [E7](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)
(the variant fixes type and role), [E8](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)
(a pass-through carrying `PARTITION BY` is wrapped in
`group_aggregate ( … , query_groups ( ) + { [partition_col] } , query_filters ( ) )`) and
[E9](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)
(no pass-through may carry a runtime parameter). Three Sigma-specific additions:

- **E12 — a Sigma window pass-through invents its partition.** Sigma never states one; the
  converter fills `PARTITION BY` from the element's parent groupings. The formula is then
  correct for searches whose dimensions are those groupings and silently different for any other,
  because ThoughtSpot generates `GROUP BY` from the search and every search dimension must
  appear in `PARTITION BY` (formula reference). The issue text must say which dimensions
  were assumed. This is why a native `direct` row is preferred even with a documented
  limitation, and why `CumulativeCount` / `MovingCount` are the most valuable rows to verify
  natively.
- **E14 — inside a window pass-through, the operand is aggregated and the `ORDER BY` matches
  the `GROUP BY`.** Per the formula reference (*Window functions inside
  `sql_*_aggregate_op`*), an aggregated search generates a `GROUP BY` from the search's
  columns, so a bare `{0}` inside the window is not a valid expression there: the operand is
  aggregated inside the window function (`SUM(SUM({0})) OVER`, `SUM(COUNT({0})) OVER` for a
  running count, `STDDEV(SUM({0})) OVER`, `LAG(SUM({0}), 1) OVER` …), and the `ORDER BY`
  argument is the bucketed date expression matching the search's date bucket
  (`start_of_month ( [d] )` for `.monthly`, raw `[d]` only when unbucketed) — the reference's
  verified example is `LEAD(SUM({0}), 1) OVER (PARTITION BY {1} ORDER BY {2})` with
  `start_of_month ( [Order Date] )`. **Every window pass-through template in this map is
  unverified** on a live import; only that reference example is.
- **E13 — Sigma's own `Call*`/`Agg*` are pass-throughs already.** They translate
  mechanically and need no dialect re-derivation when ThoughtSpot queries the same warehouse;
  they still carry the warning, because a ThoughtSpot user can no longer see the
  computation.

---

## Reverse direction (ThoughtSpot → Sigma)

Brief by design — this map exists for the Sigma → ThoughtSpot direction. ThoughtSpot
functions with **no Sigma counterpart**, and what a converter would do:

| ThoughtSpot | Sigma | Disposition |
|---|---|---|
| `group_aggregate ( … , query_groups ( ) ± { [a] } , … )` | `Subtotal(agg, "parent_grouping", n)` covers `query_groups ( ) - { innermost dims }` only | **Partial.** Sigma can drop parent levels from the current grouping, not name an arbitrary dimension to exclude or add. `+ { [a] }` has no Sigma form. |
| `group_aggregate` with a non-`query_filters ( )` filter argument | — | **Issue.** Sigma formulas have no filter-scoping argument; filters live on elements. |
| `safe_divide ( [a] , [b] )` | `If([b] = 0, 0, [a] / [b])` | Composition — note the 0-not-Null result. |
| `sum_if` / `count_if` / `unique_count_if` / `average_if` / `min_if` / `max_if` | `SumIf` / `CountIf` / `CountDistinctIf` / `AvgIf` / `MinIf` / `MaxIf` | Direct — **argument order flips back** to value-first. |
| `stddev_if ( c , [x] )` / `variance_if ( c , [x] )` | `StdDev(If(c, [x]))` / `Variance(If(c, [x]))` | Composition. |
| `last_value_in_period` / `first_value_in_period` | — | **Issue.** No period-completeness concept. |
| `is_weekend ( [d] )` | `In(Weekday([d]), 1, 7)` | Composition (Sunday = 1, Saturday = 7). |
| `contains ( [s] , 'x' )` / `strpos` / text `=` | `ILike([s], "%x%")` / `Find(Lower([s]), "x")` / `Lower([a]) = Lower([b])` | ThoughtSpot compares case-insensitively (BL-333, live-verified 2026-10-06); Sigma's `Contains`/`Find`/`=` are case-sensitive, so the reverse leg must lower both sides. |
| `week_number_of_month` / `week_number_of_quarter` / `month_number_of_quarter` / `day_number_of_quarter` | `DateDiff("week", DateTrunc("month", [d]), [d]) + 1` etc. | Composition; the `week_number_*` forms assumes the Model calendar's Monday week start (Gregorian, Monday-first when nothing else is set — ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. |
| Fiscal-calendar variants (`year ( [d] , fiscal )` …) | — | **Issue.** Sigma has no fiscal-calendar argument. |
| `ts_groups` / `ts_username` / `ts_org` | `CurrentUserInTeam` / `CurrentUserEmail` / — | Partial; `ts_org` and `ts_groups_int` have no Sigma counterpart. |
| `rank` | `Rank` in an ungrouped table | Direct — both are unpartitioned ranks over the result rows. |
| `moving_*` / `cumulative_*` with search-derived partitions | `Moving*` / `Cumulative*` | **Downgrade**, mirror of [E6](#how-to-read-the-tables): Sigma resets per parent grouping, ThoughtSpot per every non-order search dimension. Faithful only when the Sigma element's groupings are the Answer's other dimensions. |
| `concat ( "{caption}" , … )` hyperlink markup | — | **Issue.** Display markup. |

---

## Open questions and gaps

### ThoughtSpot capability gaps this map exposes

| # | Gap | Rows affected | Note |
|---|---|---|---|
| **G1** | No array, variant or geography type in formulas | 24 `unmappable` rows (Array 12, `ArrayAgg`/`ArrayAggDistinct` 2, Geography 4, Type 2, `Agg`/`Call` 4) | The single largest cause of `unmappable`. Scalar-returning consumers survive as pass-throughs over warehouse columns. |
| **G2** | No native case, trim, replace, pad, regex; native comparison is case-insensitive (BL-333) | 24 Text rows (20 + `Contains`, `StartsWith`, `EndsWith`, `Find`, `Like`, less `ILike` now native) | Already tracked (BL-170, BL-226). `lpad`/`rpad`/`repeat` remain unverified names — probing them is cheap and could move three rows. |
| **G3** | No ordered `count` / `stddev` / `variance` / `corr` window; no `dense_rank`, `row_number`, `ntile`, `cume_dist`, `nth_value`, ignore-nulls `first/last_value`, fill-down | All 16 Window `passthrough` rows (incl. `CumeDist`, `Ntile`) — and, because `moving_*`/`cumulative_*` cannot declare a partition, the faithful alternative for the 12 `direct (downgrade)` rows too | Each forces a pass-through that must *invent* a partition ([E12](#passthrough-caveat-applies-to-every-passthrough-row)) — a correctness risk, not just a portability one. `CumulativeCount` via `cumulative_sum` over an indicator formula is the cheapest live probe. |
| **G4** | `rank` / `rank_percentile` cannot partition | `Rank`, `RankPercentile`, `RankDense` in grouped tables | Known (Ossie map A10 neighbourhood). Sigma ranks reset per parent group by default, so this bites more often than for SQL sources. |
| **G5** | No minute/second extractor, no `date_trunc('second')`, no timezone argument | `Minute`, `Second`, four `DatePart` parts, `ConvertTimezone`, every `tz` argument | |
| **G6** | No percentile functions; no ordered string aggregation | 4 Aggregate rows (`PercentileCont`, `PercentileDisc`, `ListAgg`, `ListAggDistinct`) | Population variance, correlation and regression moved to `direct` compositions (Excel map), none import-probed. |
| **G7** | No value-ranged (calendar-interval) window | `DateLookback` | `moving_*` is row-positional (live-verified). A period-offset native would cover `DateLookback` and the Power BI time-intelligence family at once. |
| **G8** | No null-matching join | `LookupMatchNulls` | Model-level. |

### ThoughtSpot-side verifications this map needs (internal, not upstream)

| # | Question | Why it matters |
|---|---|---|
| **V1** | **RESOLVED 2026-10-06 — `round`'s second argument is an increment.** Live probe on se-thoughtspot: ThoughtSpot compiles `round ( x , n )` to `n * ROUND(x / NULLIF(n, 0))`; on 1234.5678, `round ( x , 0 )` = NULL, `round ( x , 2 )` = 1234, `round ( x , 0.01 )` = 1234.57, `round ( x , 10 )` = 1230, `round ( x , -2 )` = 1234. This confirms the Power BI and Sisense maps and this map's `Round`/`MRound` rows. | BL-331 (PR #558) corrects every translator and mapping doc in the repo that read it as a digit count — Snowflake SV, Tableau, Databricks (both directions), Sisense, the formula reference and the Ossie map; BL-332 tracks the upstream apache/ossie converter. |
| **V2** | Is `Trunc` / `RoundDown` by sign-branched `floor`/`ceil` acceptable as `direct`? | The Ossie map rows `TRUNC` `passthrough`; the Tableau map uses the identical composite for `INT`. Pick one rule repo-wide. |
| **V3** | **RESOLVED (ThoughtSpot side) 2026-10-06 — `diff_months` counts month boundaries; `diff_years` subtracts calendar years.** Live probe on se-thoughtspot: `diff_months` = `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)` (Jan 31 → Feb 1 = 1, Jan 31 → Feb 28 = 1, Jan 20 → Mar 15 = 2, reversed = −1); `diff_years` = `EXTRACT(YEAR FROM end) - EXTRACT(YEAR FROM start)` (Dec 31 → Jan 1 = 1; 2025-07-01 → 2026-06-30 = 1). Recorded in the formula reference. **Still open on the Sigma side:** what "rounded to the nearest integer" means for months/years. | Exact if Sigma pushes down boundary-counting `DATEDIFF`; a silent off-by-one otherwise. |
| **V4** | **RESOLVED 2026-10-06 — ThoughtSpot string comparison is case-insensitive.** Live probe on se-thoughtspot: `contains ( [c] , 'eng' )` → `LOWER(c) LIKE '%eng%' ESCAPE '!'`; literals are lowercased at compile time (`contains ( 'Hello World' , 'WORLD' )` = true); `strpos` → `POSITION('eng' IN LOWER(c))`; `[c] = 'engineering'` → `LOWER(c) = 'engineering'`. Not tested: `!=`, `in { }`, `strpos`-based compositions, join keys. Formula reference *String comparison is case-insensitive*; converter impact BL-333. | `Contains`, `StartsWith`, `EndsWith`, `Find` and `Like` (all documented case-sensitive in Sigma) move to `passthrough`; `ILike` moves to `direct`. |
| **V5** | `group_aggregate` inside a `sum` argument (`XNPV`), and `cumulative_sum` over a row-level formula (`CumulativeCount`) | Both are plausible native compositions that are not in the formula reference. |
| **V6** | `first_value ( … , query_groups ( ) , { [sort] } )` vs Sigma `First` when the sort column is in the search | The Tableau decision this row reuses has the same open edge. |
| **V7** | `add_months` month-end clamping; `add_seconds` on a DATE | `DateAdd` fidelity; `DateFromUnix` native composition. |

### Upstream (apache/ossie `converters/sigma`) — candidate contributions

These are places where the upstream converter is weaker than the direct map or outright
wrong. Each is a small, self-contained fix. **The first three produce wrong SQL or never
translate a documented call** — they are bugs, not coverage gaps.

| # | Finding | Evidence | Suggested fix |
|---|---|---|---|
| **U1** | **`SumIf` and `CountDistinctIf` swap condition and value.** Sigma's signatures are `SumIf(field, condition, …)` and `CountDistinctIf(field, condition, …)` (reference pages); the converter treats argument 0 as the condition, emitting `SUM(CASE WHEN amount THEN status = 'x' ELSE 0 END)`. Only the two-argument form is recognised, so the documented variadic AND-ed conditions fall through. | `sigma_formula.py:547-548`, `:551-552` | Value-first, `AND` the remaining arguments. A test with a non-boolean value column would have caught it. |
| **U2** | **`DateAdd` / `DateDiff` read the unit from the wrong argument.** Sigma is `DateAdd(unit, amount, date)` and `DateDiff(unit, start, end)` (reference pages); the converter expects the unit **last** (`_date_part_unit(args[2])`), so every documented call raises `_NotTranslatable`. Fails safe, but the two most common date functions never translate. | `sigma_formula.py:581-587` | Read `args[0]` as the unit. |
| **U3** | **Two-argument `Ceiling` / `Floor` change meaning.** Sigma's second argument is a rounding *factor* (`Ceiling([Cost], 0.5)` → nearest 0.5 up); `exp.func("CEIL", x, f)` emits `CEIL(x, f)`, which in Snowflake (`CEIL(x, scale)`) is a *scale* (decimal places). Silent wrong numbers. | `sigma_formula.py:344-345`, `:589-590` | `CEIL(x / f) * f`, or reject two arguments. |
| **U4** | Dead or mis-named keys: `averageif` (Sigma: `AvgIf`), `length` (Sigma: `Len`), `percentile` (Sigma: `PercentileCont`), `var` / `standarddeviation` / `ifnull` / `null()` / `week` / `dayofweek` (not Sigma functions). `dayofweek` would also emit 0-based `EXTRACT(DOW)` against Sigma's 1 = Sunday `Weekday`. | `sigma_formula.py:335-363`, `:527-577` | Key on the published index names; add `Weekday` with the base shift. |
| **U5** | Tokenizer rejects documented operators: `!=`, `%`, the bare `NULL` literal, and the `.` variant path. Any formula containing one is untranslated as a whole. Conversely it accepts `<>`, which Sigma does not document. | `sigma_formula.py:108-122`, `:283-293` | Add `!=` and `%` (→ `MOD`), treat `null` as a keyword literal. |
| **U6** | Multi-branch `If(c1, v1, c2, v2, …, else)` and two-argument `If` (no else) are documented and untranslated; `Switch`, `Choose`, `Zn`, `In`, `Between` are absent. | `sigma_formula.py:538-539` | Variadic `CASE`; these are the commonest untranslated Logical functions. |
| **U7** | `Contains` / `StartsWith` / `EndsWith` become `LIKE` with a *concatenated* pattern, so a `%` or `_` in the search text becomes a wildcard, and downstream consumers (the Ossie map's `LIKE` shape analysis) can no longer recover the native form. | `sigma_formula.py:562-568` | Emit `POSITION`/`STARTSWITH`/`ENDSWITH`-style functions, or escape the operand. |
| **U8** | `Count` / `CountDistinct` lose Sigma's non-empty-string exclusion. | `sigma_formula.py:338`, `:527-528` | Document, or emit `COUNT(NULLIF(x, ''))` for text. |
| **U9** | **Grouping level is discarded.** A column's `groupings` and the element `sort` are preserved only as opaque `custom_extensions`, so an aggregate at a grouping level becomes an un-grained `SUM(x)` field expression ([E5](#how-to-read-the-tables)), and every window function is untranslatable for want of the order/partition that the same document carries. A Sigma column at level *L* is expressible in Ossie as `SUM(x) OVER (PARTITION BY <keys of L>)`; a cumulative function with a recovered sort as an `OVER (PARTITION BY <parent keys> ORDER BY <sort> ROWS …)` — exactly the shape the Ossie map then has to pass through. | `LIMITATIONS.md:26-38`, `:99-103`; `README.md:114` | The largest fidelity loss on the two-hop path — 31 window rows plus every level-scoped aggregate. Also: the docs name `RunningSum`, which is not a Sigma function (`CumulativeSum`) — `LIMITATIONS.md:99`, `README.md:127`. |
| **U10** | Sigma's own `CallNumber`/`CallText`/`AggNumber`… are untranslated, though they are the most mechanically translatable functions in the language (name + args → dialect SQL). | `sigma_formula.py:592` | Emit `fn(args)` as a dialect-tagged expression; it is already warehouse SQL. |

---

## Worked shape

One formula per classification, from a Sigma data-model element to the ThoughtSpot Model
formulas the converter emits. The element is `ORDERS`, grouped by `Region`, sorted by
`Order Date`.

Sigma:

```text
Revenue          = Sum([Amount])                               -- metric
Closed Revenue   = SumIf([Amount], [Status] = "closed")        -- value first
Ship Days        = DateDiff("day", [Order Date], [Ship Date])  -- unit first, start then end
Running Revenue  = CumulativeSum([Revenue])                    -- order = element sort; resets per Region
Prior Order Amt  = Lag([Amount])
Rounded Margin   = Round([Margin], 2)
Customer Upper   = Upper([Customer])
Order Week       = DateTrunc("week", [Order Date])             -- Sunday-start in Sigma
Region Share     = PercentOfTotal(Sum([Amount]), "grand_total")
```

ThoughtSpot (Model `formulas[]`; each needs a `columns[]` entry referencing it by
`formula_id`):

```yaml
formulas:
- id: formula_Revenue
  name: Revenue
  expr: "sum ( [ORDERS::Amount] )"

- id: formula_Closed Revenue
  name: Closed Revenue
  expr: "sum_if ( [ORDERS::Status] = 'closed' , [ORDERS::Amount] )"   # condition first; single quotes; text = is case-insensitive in TS (BL-333)

- id: formula_Ship Days
  name: Ship Days
  expr: "diff_days ( [ORDERS::Ship Date] , [ORDERS::Order Date] )"    # end first

- id: formula_Running Revenue
  name: Running Revenue
  expr: "cumulative_sum ( [ORDERS::Amount] , [ORDERS::Order Date] )"  # direct (downgrade): resets per Region only when the search is Region + Order Date

- id: formula_Prior Order Amt
  name: Prior Order Amt
  expr: "moving_sum ( [ORDERS::Amount] , 1 , -1 , [ORDERS::Order Date] )"  # direct (downgrade), as above

- id: formula_Rounded Margin
  name: Rounded Margin
  expr: "round ( [ORDERS::Margin] , 0.01 )"                           # increment, not digit count (live probe 2026-10-06)

- id: formula_Customer Upper
  name: Customer Upper
  expr: "sql_string_op ( \"UPPER({0})\" , [ORDERS::Customer] )"

- id: formula_Order Week
  name: Order Week
  expr: "add_days ( start_of_week ( add_days ( [ORDERS::Order Date] , 1 ) ) , -1 )"  # Sunday-start from the Model calendar's Monday default (BL-334 caveat)

- id: formula_Region Share
  name: Region Share
  expr: "sum ( [ORDERS::Amount] ) / group_aggregate ( sum ( [ORDERS::Amount] ) , { } , query_filters ( ) )"
```

Through the two-hop path the same element yields: `Revenue`, `Customer Upper` and `Rounded
Margin` translate — but the last becomes `round ( [Margin] , 2 )` through the Ossie map, which the 2026-10-06 probe shows rounds to the nearest 2; `Closed Revenue`
translates **wrongly** (U1); `Ship Days` and `Order Week` are not translated (U2; no
`DateTrunc` mapping); `Running Revenue`, `Prior Order Amt` and `Region Share` are not
translated (U9). Two of nine survive intact.
