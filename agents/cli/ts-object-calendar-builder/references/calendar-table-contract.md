# Custom Calendar Table Contract

Two shapes, written from the live ThoughtSpot API's own CSV output and
corroborated across 42 tables in the `CUSTOM_CALENDAR.PUBLIC` corpus — not
inferred. The first 10 columns are identical, in name and order, in both
shapes. `ts calendar generate --columns 10|30` (default **30**) emits one of
these; `ts calendar validate` checks a CSV or a live table against them.

## Minimum shape (10 columns)

**Not registrable.** These ten columns are the minimum the corpus documents,
and every 30-column table starts with them, but ThoughtSpot's `createCalendar`
**rejects a table that has only these ten** — verified live 2026-09-16 against
a 10.12+ build, for a pre-existing table and a freshly created one, with
correct types in both cases. The API requires all **30** columns. Treat
`ts calendar generate --columns 10` as an intermediate artifact only;
`ts calendar validate` raises a `ten-column-not-registrable` warning when it
sees one.

In order:

| # | Column | Meaning |
|---|---|---|
| 1 | `date` | The calendar day |
| 2 | `day_of_week` | Absolute day name (`Monday`, `Tuesday`, …) — see "day_of_week vs day_number_of_week" below |
| 3 | `month` | Period label for this row (e.g. `February`, `Period 01`) — a non-month label is **not selectable in a filter widget**, see below |
| 4 | `quarter` | Quarter label for this row (e.g. `Q1`) |
| 5 | `year` | Fiscal year label for this row — a prefixed value (`FY2024`) **cannot be typed into the year filter**, see below |
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

## Label values and the ThoughtSpot filter widget

The label columns are free text as far as *registration* goes — the API does
not parse them, and non-Latin labels register fine (open item 1, live-verified
2026-09-16). **Consumption is where the constraint is**, and only in the
filter components that take a *typed value*:

| Label column | Custom / prefixed value | Filter widget |
|---|---|---|
| `month` | non-month names (e.g. `Period 01`) | **not selectable** |
| `year` | prefixed (e.g. `FY2024`) | **not typeable** — accepts `YYYY` only |
| `quarter` | prefixed (e.g. `Q1`) | **works** |

- A `month` label that is not a month name — `Period 01`, or any custom
  `--month-names` value — cannot be selected in a filter widget.
- The year filter accepts a four-digit `YYYY` only, so a `--year-prefix`
  value (`FY2024`) cannot be typed into it.
- A prefixed `quarter` (`Q1`) **is** selectable; the `YYYY`-only rule is
  specific to the year filter.

**The calendar is still fully usable.** Date-range filters and dynamic /
relative filters ("this year") work regardless, and query generation,
grouping, aggregation and display are unaffected — the numeric columns
(`month_number_of_year`, `quarter_number_of_year`, `absolute_week_number`, …)
carry all the real ordering. `ts calendar validate` warns (exit 0) on both
shapes: `month-label-not-filter-selectable` and
`year-label-not-filter-typeable`.

Provenance: ThoughtSpot product knowledge, confirmed at PR review on
2026-09-16 — not an automated probe. Full detail, and what was *not*
established, is in [open-items.md](open-items.md) item 6.

## Snowflake column naming

Every column name in the table registered with ThoughtSpot **must stay
quoted and lower-case** — `"date"`, `"day_of_week"`, `"is_weekend"`, and so
on, exactly as written above. Snowflake folds unquoted identifiers to
upper-case by default; if the DDL or load path lets that happen, the
resulting table has columns named `DATE`, `DAY_OF_WEEK`, etc., and the
ThoughtSpot API rejects the table as not matching the required schema (HTTP
400, `INVALID_EXTERNAL_CALENDAR` — a message that never names a column).

**`ts load snowflake` does NOT preserve the case** — it derives each column
name from the CSV header with `sanitise_name()`, which upper-cases it, and
emits the DDL unquoted. It has no case-preserving flag. That is why the
skill's Step 6 runs
[`references/fix-column-case.sql`](fix-column-case.sql) after the load: a
CTAS that re-aliases all 30 columns back to their quoted lower-case contract
names and casts each to its contract type. Verified live 2026-09-16 — the
same rows that were rejected as `DATE`/`DAY_OF_WEEK`/… registered 200 once
re-aliased.

`ts calendar generate --ddl` emits this shape directly, correctly quoted, for
the case where the table is created by hand rather than loaded. The note
above also exists so that a hand-edited DDL statement (for example, a variant
of `relabel-calendar.sql`) doesn't reintroduce the problem.

## The row-level-security discriminator (column 31)

A calendar built for row-level security appends one more column beyond the
30 above: a literal discriminator identifying which variant a row came from.
It is **column 31**, and its name is caller-chosen — the existing corpus
uses both `TS_CALENDAR_GROUP` and `TSGROUP` for the same purpose on
different tables, so there is no single canonical name to match. Pick one
name and use it consistently across every variant in the same set;
`ts calendar generate --discriminator-column` / `--discriminator-value` set
it per variant.

**How `validate` treats the discriminator: it doesn't.** `read_calendar_csv`
accepts exactly one trailing discriminator column and then drops it, so
`validate` never sees its value. Date uniqueness and date continuity are
checked **per file** — each `--csv` path is validated on its own — and there
is no cross-file `(date, discriminator)` uniqueness key. That is sufficient
for the way these sets are built (one file per variant, each covering every
date once), but it means `validate` cannot catch two variants that were
given the *same* discriminator value, or a single already-unioned file
holding every variant's rows: the latter reads as a duplicate-date error.
What `validate` does check across a set of two or more `--csv` paths is
label consistency, which is a different failure and the reason multi-`--csv`
mode exists.
