# Anchor Rules, Patterns, and Leap-Week Placement

A fiscal year runs `anchor(y) .. anchor(y+1) - 1`. Because every anchor falls
on the same weekday, that span is always a whole number of weeks — **52 vs
53 weeks is derived, never configured.** Only the leap week's *placement*
(which period absorbs it) is an option.

## The three anchor rules

| Rule | Definition | Implemented by |
|---|---|---|
| `nearest` | The chosen weekday **nearest** the 1st of the start month — go backward or forward, whichever is fewer days. NRF/retail standard | This skill — reproduces the `LULULEMON` corpus table |
| `first` | The **first** chosen weekday **on or after** the 1st of the start month — never goes backward | This skill |
| `fixed52` | Anchor once, then `+364 days` forever — a pure arithmetic progression with no re-anchoring | This skill, and **identical to the native ThoughtSpot API** (`FROM_INPUT_PARAMS`) |

`--native` (`ts calendar register --native`) is refused for any anchor rule
other than `fixed52`, because the native API has no way to express
`nearest` or `first` — it does not re-anchor, so requesting it for those
rules would silently ship a drifting calendar instead of failing loudly.

## Worked example: `LULULEMON` (February start, Monday, `nearest`)

`nearest`/4-5-4/February/Monday reproduces every year boundary in the
`CUSTOM_CALENDAR.PUBLIC.LULULEMON` corpus table. Fiscal-year start dates,
derived from the rule and cross-checked against every value confirmed live
against that table:

| Fiscal Year | Start date | Length |
|---|---|---|
| FY2015 | 2015-02-02 | 364 days (52 weeks) |
| FY2016 | 2016-02-01 | 364 days (52 weeks) |
| FY2017 | 2017-01-30 | 364 days (52 weeks) |
| FY2018 | 2018-01-29 | **371 days (53 weeks)** |
| FY2019 | 2019-02-04 | 364 days (52 weeks) |
| FY2020 | 2020-02-03 | 364 days (52 weeks) |
| FY2021 | 2021-02-01 | 364 days (52 weeks) |
| FY2022 | 2022-01-31 | 364 days (52 weeks) |
| FY2023 | 2023-01-30 | 364 days (52 weeks) |
| FY2024 | 2024-01-29 | **371 days (53 weeks)** |
| FY2025 | 2025-02-03 | 364 days (52 weeks) |
| FY2026 | 2026-02-02 | 364 days (52 weeks) |

FY2015, FY2016, FY2017, FY2018, FY2019, FY2022 and FY2025's start dates —
and both 53-week years, FY2018 and FY2024 — are corroborated directly
against the live corpus table. The remaining rows follow deterministically
from the same rule applied to the same twelve-year cycle and are shown so
the full run is visible in one table.

**This is the table the Problem section's "testing trap" is about.**
FY2015–FY2018 are exactly where `fixed52` (what the native API generates)
still agrees with `nearest` (what a real retail calendar needs) — the
native API's `FY2019` start (`2019-01-28`, `+364` from `2018-01-29`) is the
first year it diverges from `LULULEMON`'s `2019-02-04`, and the gap only
widens: 7 days by FY2022, 14 by FY2025. Any comparison spanning less than
~4 years never reaches that divergence and reports the native API as
correct.

## `nearest` vs `first`: the two rules disagree too

`nearest` and `first` are not interchangeable even though both are
week-aligned and re-anchor every year — they only coincide when the 1st of
the start month falls exactly on, or up to 3 days before, the chosen
weekday. Same February/Monday example, both rules applied independently:

| Fiscal Year | `nearest` start | `first` start | Agree? |
|---|---|---|---|
| FY2015 | 2015-02-02 | 2015-02-02 | yes |
| FY2016 | 2016-02-01 | 2016-02-01 | yes |
| FY2017 | 2017-01-30 | 2017-02-06 | **no** |
| FY2018 | 2018-01-29 | 2018-02-05 | **no** |
| FY2019 | 2019-02-04 | 2019-02-04 | yes |
| FY2020 | 2020-02-03 | 2020-02-03 | yes |
| FY2021 | 2021-02-01 | 2021-02-01 | yes |
| FY2022 | 2022-01-31 | 2022-02-07 | **no** |
| FY2023 | 2023-01-30 | 2023-02-06 | **no** |
| FY2024 | 2024-01-29 | 2024-02-05 | **no** |
| FY2025 | 2025-02-03 | 2025-02-03 | yes |
| FY2026 | 2026-02-02 | 2026-02-02 | yes |

**`first_divergence` = 2017.** This is exactly the number
`ts calendar compare --vary anchor` reports: the first fiscal year where
`nearest`, `first` and `fixed52` stop agreeing with each other. Two things
worth noting when reading this table:

- The divergence is **not monotonic** — FY2019–FY2021 and FY2025–FY2026
  agree again after FY2017/FY2018 diverge. Do not assume that because two
  anchor rules agree for a stretch of years, they will keep agreeing; run
  `compare` for the actual range in question rather than extrapolating from
  a few sample years.
- Whenever `--vary anchor` is run for a spec still under discussion, treat
  its reported `first_divergence` — not "do the first couple of years
  match" — as the number that answers "does this choice matter for my
  range."

## Leap-week placement

`--leap-week-period`, default `last`:

| Value | Effect |
|---|---|
| `last` (default) | The final period of the fiscal year absorbs the extra week. `4-5-4` → Q4 becomes `4-5-5`; `4-4-5` → Q4 becomes `4-4-6` |
| `1`–`12` (or `1`–`13` under `13x4`) | That period ordinal absorbs it instead |

`last` is not a guess: in **both** `LULULEMON` 53-week years — 2018 and
2024 — the extra week lands on `JAN`, the final period of the fiscal year,
turning Q4 from `4-5-4` into `4-5-5`. No other period moves in either year.
The named period gains a week, its quarter goes to 14 weeks,
`week_number_of_year` runs 1..53, and every dependent column
(`week_number_of_quarter`, the `absolute_*_number`s, the `*_epoch`
boundaries) shifts accordingly for every later row in that fiscal year. A
`--leap-week-period` ordinal outside the pattern's period count is
rejected.

## Period patterns

`--pattern` selects both the period count and the weeks each period holds
in a normal (52-week) year. The quarter layout is **derived from the period
count**, not separately configured:

| Pattern | Periods | Weeks per period in a quarter | Quarter layout | Corpus reference |
|---|---|---|---|---|
| `4-4-5` | 12 | 4, 4, 5 | 3 / 3 / 3 / 3 | `PERIOD_CALENDAR` (labelled `Period N`) |
| `4-5-4` (default) | 12 | 4, 5, 4 | 3 / 3 / 3 / 3 | `LULULEMON` |
| `5-4-4` | 12 | 5, 4, 4 | 3 / 3 / 3 / 3 | — |
| `13x4` | 13 | 4 throughout | **3 / 3 / 3 / 4** | `FISCAL_CALENDAR_13_PERIOD` |

All four are 52 weeks in a normal year — only `13x4` changes the quarter
layout, because 13 periods of 4 weeks each cannot split evenly across four
3-period quarters. Verified from `FISCAL_CALENDAR_13_PERIOD` FY2020: Q1–Q3
each hold three periods, Q4 holds four (`Period 10`–`Period 13`).

`13x4` is a genuine 13×28-day structure, not a relabelled `4-4-5` — it
differs in period *count*, not just in label text.

### `13x4` labels cannot be selected in a filter widget

Query generation and aggregation are unaffected — the numeric columns
(`month_number_of_year`, `absolute_week_number`, etc.) carry all the true
ordering regardless of pattern. Two separate things touch the **labels**, and
both are now settled:

1. **Lexical sort scrambles period order.** Confirmed against
   `FISCAL_CALENDAR_13_PERIOD`: sorting `month` values as strings gives
   `Period 1, Period 10, Period 11, Period 12, Period 13, Period 2, …` — not
   numeric order. **Mitigated by default**: `13x4`'s generated labels are
   zero-padded (`Period 01` … `Period 13`) so lexical and numeric order
   coincide. Automatic; needs no user action unless custom, unpadded
   `--month-names` are supplied, which `ts calendar validate` warns about.
2. **A non-month label cannot be selected in the filter widget.** This is a
   product limitation, confirmed at PR review on 2026-09-16 from ThoughtSpot
   product knowledge (not an automated probe — there is no REST surface that
   could be one). It is **not specific to `13x4`**: it applies to any custom
   `--month-names` value that is not a real month name. A second, related
   limitation affects the year filter, and a third case does *not*:

| Label column | Custom / prefixed value | Filter widget |
|---|---|---|
| `month` | non-month names (e.g. `Period 01`) | **not selectable** |
| `year` | prefixed (e.g. `FY2024`) | **not typeable** — accepts `YYYY` only |
| `quarter` | prefixed (e.g. `Q1`) | **works** |

**The pattern remains fully usable, and this is the half to say out loud.**
Only the typed-value filter components are affected. A `13x4` calendar
filters normally by **date range** and by **dynamic / relative filters**
("this year"), or on `month_number_of_year`; registration, querying,
grouping, aggregation and display are all unaffected. A `13x4` calendar with
`Period 01`…`Period 13` labels registered live on 2026-09-16 (HTTP 200).

**State this to the user whenever `13x4` is selected**, rather than
presenting it as equivalent to the 12-period patterns — but state the
mitigation with it, because "this still works, here is how" is the
actionable half. See open item 6 in [open-items.md](open-items.md).
