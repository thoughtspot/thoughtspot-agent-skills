# BI-tool function maps → ThoughtSpot

Function-level maps from four formula languages to ThoughtSpot formulas. There is no
converter for any of them in this repo. They are built the same way as the
[Ossie expression-language map](../ossie/ts-ossie-function-mapping.md): one row per
documented function, the same classifications and rules, and a gaps section.

| Map | Source inventory | Rows | `direct` | `passthrough` | `structural` | `unmappable` |
|---|---|--:|--:|--:|--:|--:|
| [Excel](ts-excel-function-mapping.md) | Microsoft 365 "Excel functions (by category)"; 109 Engineering / Cube / Web / Compatibility / Add-in functions counted, not rowed | 415 | 231 | 50 | 15 | 119 |
| [Sigma](ts-sigma-function-mapping.md) | Sigma function index (help.sigmacomputing.com), plus the upstream `apache/ossie` Sigma converter as a **Via Ossie** column | 258 | 148 ¹ | 76 | 5 | 29 |
| [Omni](ts-omni-function-mapping.md) | Omni docs, covering table calcs, the modelling layer (with a **Via Ossie** column) and filter syntax | 216 | 130 | 59 | 12 | 15 |
| [Google Sheets](ts-sheets-function-mapping.md) ² | Google Sheets function list (support.google.com/docs), 515 names; 3 Sheets-only Engineering functions counted, not rowed | 63 | 35 | 10 | 5 | 13 |

² **A delta on the Excel map, not a full map.** It rows only the 46 functions Excel lacks (QUERY, ARRAYFORMULA, the operator functions, IMPORT*/GOOGLE*, REGEXMATCH, SPLIT/JOIN, COUNTUNIQUE…) and the 17 shared names whose Sheets behaviour changes the translation (REGEXEXTRACT capture groups, two-argument CONCAT, CODE/CHAR on Unicode, one-argument IFERROR returning blank, optional ROUND/FLOOR arguments, serial-only holiday arrays…). The other 451 Sheets functions take an Excel row unchanged (38 of them are compatibility aliases, which take their successor's row), and the map lists them by name. Its counts are not comparable with the other rows.

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

Google Sheets is handled differently from the other three: it shares most of Excel's function names, so its map rows only what differs and sends everything else to the Excel row.

For functions found in more than one tool (MOD, WEEKNUM, DATEDIF, NETWORKDAYS, CORREL, population STDEV/VAR), the Excel row holds the composition and the Sigma and Omni rows cite it. Omni's grid calcs over a column of sums are the exception. There, CORREL and population STDEV/VAR stay passthrough, because of the base-row weighting described in that map's rule E5.

**Three rounds of live probes; nothing else is live-verified.** Every "live-verified 2026-10-06" claim in these maps rests on the [probe record](../reviews/2026-10-06-formula-semantics-probes.md), which gives the cluster, method, inputs and results.
- **`round`:** its second argument was tested on se-thoughtspot on 2026-10-06 ([probe record §1](../reviews/2026-10-06-formula-semantics-probes.md#1-round--x--n--n-is-an-increment-bl-331)). It is a rounding *increment*, not a number of decimal places: `round(x, 2)` returns the nearest multiple of 2, and `round(x, 0)` returns NULL.
- **Week, month and string semantics** (se-thoughtspot, 2026-10-06, compiled SQL via `ts agentql generate-sql` — [probe record §2–§4](../reviews/2026-10-06-formula-semantics-probes.md#2-weekday-week-and-calendar-bl-334), [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#date-functions)):
  - `day_number_of_week` is 1 = Monday … 7 = Sunday, independent of the warehouse's `WEEK_START`. ThoughtSpot's week comes from the Model's calendar, Gregorian with a Monday start when nothing else is set (ThoughtSpot domain review, 2026-10-06), so every weekday/week translation is marked as assuming a Monday week start.
  - `diff_months` counts month boundaries crossed; `diff_years` is the calendar-year difference. Excel/Omni `DATEDIF` keep their day-of-month correction.
  - **String comparison is case-insensitive:** `=`, `contains` and `strpos` lowercase both sides. Source comparisons documented as case-sensitive (Excel `EXACT`/`FIND`, Sigma `Contains`/`StartsWith`/`EndsWith`/`Find`/`Like`, Omni `EXACT`/`FIND` and its case-sensitive filter operators) moved `direct` → `passthrough` with a `sql_bool_op`/`sql_int_op` template; case-insensitive ones (Excel `SEARCH`, Sigma `ILike`, Omni `SEARCH` and `case_insensitive: true`) moved the other way. Converter impact: BL-333.
- **`NETWORKDAYS` family** ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)), se-thoughtspot, 2026-10-06, every result matching Excel:
  - **probed:** the Excel map's per-weekday counting form for weekend codes 1, 11 and `"1000001"` without holidays (7 date ranges, including single days and weekend-only ranges), which also gives a simpler form of plain `NETWORKDAYS` (code 1); and the inline-holiday term with code 1 (6 ranges);
  - **not probed:** the original composition on the Excel `NETWORKDAYS` row, other weekend codes, holidays with any other code, duplicate holidays, Sheets' serial-number holidays, and `WORKDAY` / `WORKDAY.INTL` in any form (their holidays shift a date, so they are a calendar table or UDF, not the subtract-a-term form).
- **Everything else:** no other composition or passthrough template here has been import-tested. Each map has an "Unverified" or open-questions section listing what needs a live test before a converter relies on it.
- **The repo's own errors:** the probe also showed that several shipped translators and mapping docs read `round` the wrong way. That is tracked and fixed separately on branch `fix/round-increment`.

## Gaps that recur across the maps

These are the ThoughtSpot capability gaps behind most of the `passthrough` and
`unmappable` rows. Each map's gaps section has the per-tool detail and row counts.

| Gap | Excel | Sheets | Sigma | Omni | Impact |
|---|:-:|:-:|:-:|:-:|---|
| No native `trim` / `upper` / `lower` / `replace` / pad / regex | G2, G7 | G2 (+ Excel G2) | G2 | ✓ | Text cleaning, which is common in sheets, becomes warehouse passthrough that ThoughtSpot can't plan around |
| A window function cannot declare its own partition, and `rank` is always global | G14 | via Excel | G3, G4, E6 | E5 | Grouped running totals and ranks only come out right when the search has exactly the right dimensions; otherwise an exact passthrough is needed |
| Passthrough window templates have to match ThoughtSpot's generated GROUP BY: the operand aggregated inside the window, ORDER BY bucketed (formula reference, verified 2026-06-15) | ✓ | via Excel | E14 | H1 / E5 | Every ordered passthrough is a template that may be rejected until it is tested live; Omni's 26 grid aggregates are marked *contradicted* until then |
| No aggregate over the query's own result rows (an average or median over a column of sums) | — | — | — | E5 | 26 of Omni's 27 math table-calc passthroughs; only MAX/MIN (and COUNT on a single-dimension grid) have untested native fast paths |
| No percentile function beyond `median`, and no ordered string aggregation | G6, G8 | G4 (via Excel) | G6 | ✓ | Percentile, quartile and list-of-values cells are aggregate passthroughs |
| No minute/second extraction, timezone argument, TIME type or calendar-interval window | G10 | via Excel | G5, G7 | ✓ | Sub-day and look-back date logic is passthrough |
| ~~Unconfirmed semantics~~ **Settled 2026-10-06** (live, se-thoughtspot): `day_number_of_week` is fixed 1 = Monday; `diff_months` counts boundaries; `=` / `contains` / `strpos` are case-insensitive | G11, G12 (closed) | E4, G6, G7 | V3, V4 (closed) | ✓ | Week compositions stand but assume the Model calendar's Monday week start (BL-334 for the `start_of_week` / `WEEK_START` residual); `DATEDIF` keeps its correction; case-sensitive source comparisons are now passthrough (BL-333). Not probed: `!=`, `in { }`, composed `strpos ( … ) = 1`, join keys |
| No array, variant or geography type | — | G5 | G1 | — | 24 of Sigma's 29 unmappables |
| No special-function or root-finding maths (erf, gamma, IRR) | G3, G4 | via Excel | — | — | 38 statistical and 21 financial Excel functions are unmappable without a UDF |

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
