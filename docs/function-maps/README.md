# BI-tool function maps → ThoughtSpot

Function-level maps from three formula languages to ThoughtSpot formulas. There is no
converter for any of them in this repo. They are built the same way as the
[Ossie expression-language map](../ossie/ts-ossie-function-mapping.md): one row per
documented function, the same classifications and rules, and a gaps section.

| Map | Source inventory | Rows | `direct` | `passthrough` | `structural` | `unmappable` |
|---|---|--:|--:|--:|--:|--:|
| [Excel](ts-excel-function-mapping.md) | Microsoft 365 "Excel functions (by category)"; 109 Engineering / Cube / Web / Compatibility / Add-in functions counted, not rowed | 415 | 232 | 49 | 15 | 119 |
| [Sigma](ts-sigma-function-mapping.md) | Sigma function index (help.sigmacomputing.com), plus the upstream `apache/ossie` Sigma converter as a **Via Ossie** column | 258 | 152 ¹ | 72 | 5 | 29 |
| [Omni](ts-omni-function-mapping.md) | Omni docs, covering table calcs, the modelling layer (with a **Via Ossie** column) and filter syntax | 216 | 134 | 55 | 12 | 15 |

¹ This includes 12 `direct (downgrade)` window rows. The native form gives the same answer only when an Answer's columns are exactly Sigma's parent groupings plus the sort column. Each row names that condition and gives an exact passthrough as the alternative.

**Classifications** are those of the Ossie map:
- `direct`: native ThoughtSpot, possibly as a composition of native functions.
- `passthrough`: a typed `sql_*_op`, with Snowflake as the reference dialect.
- `unmappable`: no ThoughtSpot expression.
- `structural` (added here): the function is a modelling construct rather than a formula, such as a lookup that becomes a Model join.

## Where the evidence comes from

The ThoughtSpot side of every row comes from this repo's verified references, never
from memory:
- [`thoughtspot-formula-patterns.md`](../../agents/shared/schemas/thoughtspot-formula-patterns.md)
- the [Snowflake formula mapping](../../agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
- the Ossie map's live-confirmed rows
- the decisions this repo's converters already made:
  - Power BI/DAX for Excel-named functions
  - Tableau for Sigma
  - LookML for Omni's modelling layer

Where these sources disagreed, the maps say so. The `round` dispute is the one that was settled live (below).

For functions found in more than one tool (MOD, WEEKNUM, DATEDIF, NETWORKDAYS, CORREL, population STDEV/VAR), the Excel row holds the composition and the Sigma and Omni rows cite it. Omni's grid calcs over a column of sums are the exception. There, CORREL and population STDEV/VAR stay passthrough, because of the base-row weighting described in that map's rule E5.

**One live probe; nothing else is live-verified.**
- **The probe:** `round`'s second argument was tested on se-thoughtspot on 2026-10-06. It is a rounding *increment*, not a number of decimal places: `round(x, 2)` returns the nearest multiple of 2, and `round(x, 0)` returns NULL.
- **Everything else:** no other composition or passthrough template here has been import-tested. Each map has an "Unverified" or open-questions section listing what needs a live test before a converter relies on it.
- **The repo's own errors:** the probe also showed that several shipped translators and mapping docs read `round` the wrong way. That is tracked and fixed separately on branch `fix/round-increment`.

## Gaps that recur across all three

These are the ThoughtSpot capability gaps behind most of the `passthrough` and
`unmappable` rows. Each map's gaps section has the per-tool detail and row counts.

| Gap | Excel | Sigma | Omni | Impact |
|---|:-:|:-:|:-:|---|
| No native `trim` / `upper` / `lower` / `replace` / pad / regex | G2, G7 | G2 | ✓ | Text cleaning, which is common in sheets, becomes warehouse passthrough that ThoughtSpot can't plan around |
| A window function cannot declare its own partition, and `rank` is always global | G14 | G3, G4, E6 | E5 | Grouped running totals and ranks only come out right when the search has exactly the right dimensions; otherwise an exact passthrough is needed |
| Passthrough window templates have to match ThoughtSpot's generated GROUP BY: the operand aggregated inside the window, ORDER BY bucketed (formula reference, verified 2026-06-15) | ✓ | E14 | H1 / E5 | Every ordered passthrough is a template that may be rejected until it is tested live; Omni's 26 grid aggregates are marked *contradicted* until then |
| No aggregate over the query's own result rows (an average or median over a column of sums) | — | — | E5 | 26 of Omni's 27 math table-calc passthroughs; only MAX/MIN (and COUNT on a single-dimension grid) have untested native fast paths |
| No percentile function beyond `median`, and no ordered string aggregation | G6, G8 | G6 | ✓ | Percentile, quartile and list-of-values cells are aggregate passthroughs |
| No minute/second extraction, timezone argument, TIME type or calendar-interval window | G10 | G5, G7 | ✓ | Sub-day and look-back date logic is passthrough |
| Unconfirmed semantics: does `day_number_of_week` follow the instance's week start? Does `diff_months` count boundaries crossed or complete months? Is `contains` case-sensitive? | G11, G12 | V3, V4 | ✓ | Every WEEKDAY / WEEKNUM / NETWORKDAYS / DATEDIF composition rests on these; three cheap live tests would settle them |
| No array, variant or geography type | — | G1 | — | 24 of Sigma's 29 unmappables |
| No special-function or root-finding maths (erf, gamma, IRR) | G3, G4 | — | — | 38 statistical and 21 financial Excel functions are unmappable without a UDF |

## Upstream (apache/ossie) converter findings

The Sigma and Omni maps record **verified** defects in the upstream converters. These
are candidates to contribute upstream; they have not been filed.

- **Sigma.**
  - `SumIf` and `CountDistinctIf` swap the value and the condition (U1).
  - `DateAdd` and `DateDiff` never translate, because the converter reads the unit from the wrong argument (U2).
  - Two-argument `Ceiling` and `Floor` change meaning (U3).
  - Groupings and sort are discarded, which loses every grouping-level aggregate and window on the Sigma → Ossie → ThoughtSpot route (U9).
- **Omni.**
  - With no warning: `level_of_detail`, bins, groups, `duration` and `dynamic_top_n` produce wrong numbers.
  - With a warning, still wrong: measure `filters` come out unfiltered, and `*_distinct_on` drops its de-duplication key.
