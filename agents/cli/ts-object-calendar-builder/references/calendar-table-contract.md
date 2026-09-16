# Custom Calendar Table Contract

Two shapes, written from the live ThoughtSpot API's own CSV output and
corroborated across 42 tables in the `CUSTOM_CALENDAR.PUBLIC` corpus — not
inferred. The first 10 columns are identical, in name and order, in both
shapes. `ts calendar generate --columns 10|30` (default **30**) emits one of
these; `ts calendar validate` checks a CSV or a live table against them.

## Minimum shape (10 columns)

In order:

| # | Column | Meaning |
|---|---|---|
| 1 | `date` | The calendar day |
| 2 | `day_of_week` | Absolute day name (`Monday`, `Tuesday`, …) — see "day_of_week vs day_number_of_week" below |
| 3 | `month` | Period label for this row (e.g. `February`, `Period 01`) |
| 4 | `quarter` | Quarter label for this row (e.g. `Q1`) |
| 5 | `year` | Fiscal year label for this row |
| 6 | `day_number_of_week` | Day position **relative to `start_day_of_week`** — see below |
| 7 | `week_number_of_month` | 1-based week position within the period |
| 8 | `week_number_of_quarter` | 1-based week position within the quarter |
| 9 | `week_number_of_year` | 1-based week position within the fiscal year, 1..53 |
| 10 | `is_weekend` | `true` / `false` |

## Extended shape (30 columns)

The 10 above, plus 20 more:

| # | Column | Meaning |
|---|---|---|
| 11 | `monthly` | `month` + year, e.g. `February 2024` |
| 12 | `quarterly` | `quarter` + year, e.g. `Q1 2024` |
| 13 | `day_number_of_month` | 1-based day position within the period |
| 14 | `day_number_of_quarter` | 1-based day position within the quarter |
| 15 | `day_number_of_year` | 1-based day position within the fiscal year |
| 16 | `month_number_of_quarter` | 1-based period position within the quarter (1..3, or 1..4 for the long quarter in `13x4`) |
| 17 | `month_number_of_year` | 1-based period position within the fiscal year (1..12, or 1..13) |
| 18 | `quarter_number_of_year` | 1-based quarter position within the fiscal year (1..4) |
| 19 | `absolute_week_number` | Week index counted from the start of the generated range, never resets |
| 20 | `start_of_week_epoch` | First date of the week — inclusive |
| 21 | `end_of_week_epoch` | **Exclusive** — the first date of the *next* week |
| 22 | `absolute_month_number` | Period index counted from the start of the generated range, never resets |
| 23 | `start_of_month_epoch` | First date of the period — inclusive |
| 24 | `end_of_month_epoch` | **Exclusive** |
| 25 | `absolute_quarter_number` | Quarter index counted from the start of the generated range, never resets |
| 26 | `start_of_quarter_epoch` | First date of the quarter — inclusive |
| 27 | `end_of_quarter_epoch` | **Exclusive** |
| 28 | `absolute_year_number` | Fiscal year index counted from the start of the generated range, never resets |
| 29 | `start_of_year_epoch` | First date of the fiscal year — inclusive |
| 30 | `end_of_year_epoch` | **Exclusive** |

`references/relabel-calendar.sql` selects exactly these 30 columns, in this
order, so it doubles as a second, executable statement of this contract.

## `end_of_*_epoch` is exclusive

Every `end_of_*_epoch` column is the start of the **next** period, not the
last date inside the current one. Worked example, a Monday-start week:

```
start_of_week_epoch = 07/01/2027   (Thursday — the week's first date)
end_of_week_epoch   = 07/05/2027   (the following Monday, NOT the week's last date)
```

Treat every `end_of_*_epoch` as a half-open interval boundary
(`[start, end)`), the same convention `BETWEEN start AND end - 1` or a
`< end` filter both rely on. Reading it as inclusive silently double-counts
the first day of the next period in any range query.

## Value formats

- **Dates.** The live ThoughtSpot API's own CSV output uses `MM/DD/YYYY`
  (seen in the worked example above). This skill emits **ISO 8601**
  (`YYYY-MM-DD`) in the CSVs it generates — Snowflake accepts both, but ISO
  avoids the day/month ambiguity when a human reads the file.
- **`is_weekend`.** Lower-case string `true` / `false`, not a boolean type
  and not `1`/`0`.
- **`day_of_week` vs `day_number_of_week`.** These answer different
  questions and are easy to conflate:
  - `day_of_week` is the **absolute** day name — `Monday` is always
    `Monday`, regardless of `start_day_of_week`.
  - `day_number_of_week` is **relative to `start_day_of_week`** — position
    1 is whatever day the calendar starts its week on. Verified worked
    example: with `start_day_of_week: Monday`, a Thursday row carries
    `day_number_of_week = 4` and `day_of_week = "Thursday"`.

  Ordering and filtering by week position should use `day_number_of_week`
  (or the numeric `week_number_of_*` / `absolute_*_number` columns); the two
  `day_of_week`/`month`/`quarter` label columns are opaque display strings,
  not sort keys.

## Snowflake column naming

Every column name in the table registered with ThoughtSpot **must stay
quoted and lower-case** — `"date"`, `"day_of_week"`, `"is_weekend"`, and so
on, exactly as written above. Snowflake folds unquoted identifiers to
upper-case by default; if the DDL or load path lets that happen, the
resulting table has columns named `DATE`, `DAY_OF_WEEK`, etc., and the
ThoughtSpot API rejects the table as not matching the required schema. Both
`ts calendar generate --ddl`-style output and `ts load snowflake` quote
identifiers correctly — this note exists so a hand-edited DDL statement
(for example, a variant of `relabel-calendar.sql`) doesn't reintroduce the
problem.

## The row-level-security discriminator (column 31)

A calendar built for row-level security appends one more column beyond the
30 above: a literal discriminator identifying which variant a row came from.
It is **column 31**, and its name is caller-chosen — the existing corpus
uses both `TS_CALENDAR_GROUP` and `TSGROUP` for the same purpose on
different tables, so there is no single canonical name to match. Pick one
name and use it consistently across every variant in the same set;
`ts calendar generate --discriminator-column` / `--discriminator-value` set
it per variant, and `ts calendar validate --csv ... --csv ...` treats
`(date, discriminator)` — not `date` alone — as the uniqueness key when two
or more `--csv` paths are given.
