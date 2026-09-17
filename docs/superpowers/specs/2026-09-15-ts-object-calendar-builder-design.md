# ts-object-calendar-builder — Custom Calendar Builder (Design)

**Status:** implemented, reviewed and live-verified on `feat/ts-object-calendar-builder` (2026-09-16). Open items 1, 4 and 6 are now closed. Item 6's registration half was verified live; its filter-widget half was answered at PR review on 2026-09-16 from ThoughtSpot product knowledge (there is no REST surface that could probe it), and the answer generalises beyond `13x4`: a non-month `month` label is not selectable in a filter widget and a prefixed `year` (`FY2024`) is not typeable into the year filter, while a prefixed `quarter` (`Q1`) works — with date-range and dynamic filters, and all querying/grouping/display, unaffected. The live run also found three defects, all fixed in the same branch: `ts load snowflake` upper-cases columns so the documented load path could not produce a registrable table (Step 6 now re-aliases via `references/fix-column-case.sql`); `createCalendar` rejects the 10-column shape outright; and `--ddl` was specified but never implemented. See the skill's `references/open-items.md`.
**Skill:** `agents/cli/ts-object-calendar-builder/`
**CLI surface:** `ts calendar`
**Date:** 2026-09-15

---

## Problem

ThoughtSpot custom calendars (`/api/rest/2.0/calendars/*`, 10.12.0.cl / 26.3.0.sw or
later) can be created two ways: `FROM_INPUT_PARAMS`, where ThoughtSpot generates the
calendar itself, or `FROM_EXISTING_TABLE`, where a warehouse table matching a required
schema is registered as-is.

The native `FROM_INPUT_PARAMS` path is insufficient for real retail and fiscal
calendars. Verified live against `semantic-sql`
(`nebula-ts-semview.thoughtspotdev.cloud`) on 2026-09-15:

1. **It never inserts a leap week.** Every generated fiscal year is exactly 364 days.
   A 4-4-5 / 4-5-4 / 5-4-4 year is 52 weeks, so the calendar drifts against the
   Gregorian year at ~1.25 days/year and cannot re-anchor. Generating 4-5-4 /
   February / Monday across 2015–2026 and diffing against the known-good `LULULEMON`
   calendar in `CUSTOM_CALENDAR.PUBLIC`:

   | Label | API start | Days | LULULEMON start | |
   |---|---|---|---|---|
   | FY2015 | 2015-02-02 | 364 | 2015-02-02 | match |
   | FY2016 | 2016-02-01 | 364 | 2016-02-01 | match |
   | FY2017 | 2017-01-30 | 364 | 2017-01-30 | match |
   | FY2018 | 2018-01-29 | 364 | 2018-01-29 | match |
   | FY2019 | 2019-01-28 | 364 | 2019-02-04 | **diverges** |
   | FY2022 | 2022-01-24 | 364 | 2022-01-31 | drift 7d |
   | FY2025 | 2025-01-20 | 364 | 2025-02-03 | drift 14d |

   The divergence at FY2019 is exactly the 53rd week LULULEMON inserted in 2018.

   **Testing trap, recorded deliberately:** FY2015–FY2018 match exactly. Any test
   range shorter than ~4 years makes the native API look correct. This is why the
   oracle test below spans 11 years, and why this paragraph exists.

2. **`monthly` carries the fiscal year, not the calendar year.** For a December
   offset starting 2024-12-01, ThoughtSpot emits `monthly = "January 2024"` for rows
   dated 2025-01-01..2025-01-31, and `"November 2024"` for rows dated
   2025-11-01..2025-11-30. Any month falling in the fiscal year's second calendar
   year is mislabelled.

What the native API *does* do correctly, and which this design must preserve rather
than reimplement badly:

- It snaps `start_date` forward to the next `start_day_of_week`. Requested
  `01/01/2027` (Friday) with `Monday` returned `01/04/2027`; requested `02/01/2028`
  (Tuesday) returned `2028-02-07`, the first Monday of February.
- It numbers the fiscal year by the calendar year it **starts** in (verified for both
  July and December offsets).
- It emits the 30-column extended schema with `MM/DD/YYYY` dates and `"true"`/`"false"`
  for `is_weekend`.

So the native API is exactly equivalent to one of the three anchor rules below
(`fixed52`), and is a legitimate fast path for that rule only.

---

## Scope

Generate a custom calendar table, load it to Snowflake, and register it with
ThoughtSpot — with the native API used as a fast path when, and only when, the
requested calendar is natively expressible.

Primary output is a **warehouse-neutral CSV**. Snowflake is the supported load and
registration path. Databricks is out of scope for v1.

---

## Architecture

Pure core, thin wrappers. Three entry points over one implementation:

- **Python:** `from ts_cli.custom_calendar import ...` — importable and scriptable
  directly, no CLI required.
- **CLI:** `ts calendar <cmd>` — a thin Typer wrapper.
- **Skill:** `agents/cli/ts-object-calendar-builder/SKILL.md` orchestrates the CLI.

The pure core is what makes the oracle tests runnable with no live cluster.

### Package layout — `tools/ts-cli/ts_cli/custom_calendar/`

Named `custom_calendar`, **not** `calendar` — `calendar` shadows the stdlib module.

| Module | Responsibility |
|---|---|
| `spec.py` | `CalendarSpec`, `LabelSpec`, `CalendarSet` dataclasses + validation |
| `anchors.py` | The three anchor rules, each `(year) -> date` |
| `grid.py` | Spec → year/quarter/period/week skeleton. Derives 52 vs 53 weeks, distributes the pattern, places the leap week |
| `labels.py` | Skeleton → display labels (month/day names, year basis, prefixes, formats) |
| `rows.py` | Skeleton + labels → the 10- or 30-column rows |
| `emit.py` | Rows → CSV, Snowflake DDL, or a union view/table for the RLS case |

Split this way because `check_file_size.py` warns past 500 lines and fails past 1000,
and because the anchor/grid arithmetic is where the bugs live — it must be testable
without the row expansion.

### CLI subcommands — `tools/ts-cli/ts_cli/commands/calendars.py`, registered as `ts calendar`

| Command | Network | Purpose |
|---|---|---|
| `preview` | no | Print the year/period boundary table — which years are 53 weeks and which period is long — so the shape is confirmed before generating thousands of rows |
| `compare` | no | Show what a given option choice actually changes, before committing to it — see below |
| `generate` | no | Write the CSV; `--ddl` also emits the Snowflake `CREATE TABLE` for the same shape (needs `--database`/`--schema`, optional `--table`). **`--set` was never built** — an RLS union is composed by the skill's Step 6c as a `UNION ALL` view over the per-variant tables, which is the corpus `rlscalendar` shape; `emit.union_sql()` remains the tested reference for that statement |
| `validate` | no | Check a CSV or live table against the column contract and the internal invariants below |
| `register` | yes | `createCalendar` via `FROM_EXISTING_TABLE`; `--native` uses `FROM_INPUT_PARAMS` |
| `search` | yes | `POST /calendars/search` to verify what actually landed |

Loading reuses the existing `ts load snowflake`. No new loader.

`--native` **must refuse** any spec whose anchor rule is not `fixed52`, rather than
silently emitting a drifting calendar. This is the single most important safety rail
in the design.

### `compare` — showing the implications of a choice

Several options in this design are consequential and hard to reason about in the
abstract: fiscal vs gregorian year basis, and the three anchor rules. A user choosing
between them should see what changes *before* generating a calendar, not discover it
afterwards in a Liveboard.

`ts calendar compare --vary <dimension>` renders the same specification under every
value of one dimension and reports **only where they disagree**:

| `--vary` | Compares | Reports |
|---|---|---|
| `year-basis`, `monthly-basis`, `quarterly-basis`, `fiscal-year-number` | fiscal vs gregorian (or start vs end) | Count of differing rows, and sample rows with both labels side by side |
| `anchor` | `nearest` vs `first` vs `fixed52` | Per-year start dates under each rule, plus `first_divergence` — the first year where any two disagree |

Two properties make this worth a command rather than "run `preview` twice":

- **A null result is informative.** When a fiscal year sits entirely inside one
  Gregorian year, *no* rows differ, and reporting "0 of 364 rows differ" tells the user
  the choice is irrelevant for their calendar — which running two previews and
  eyeballing them does not.

  **This is rarer than it looks, and that is the point.** An earlier draft of this spec
  claimed a January-start calendar simply has no differing rows. That is false for
  week-aligned calendars, because the anchor is seldom 1 January. Verified for
  January/Monday/`first`: FY2023 runs 2023-01-02 → 2023-12-31 and differs nowhere, but
  FY2022, FY2024, FY2025 and FY2026 all spill into the following Gregorian year, and
  FY2024 — a 53-week year ending 2025-01-05 — differs on 5 rows. So even a January
  start usually *does* make the basis choice matter. A user cannot be expected to work
  that out; the command exists to tell them.
- **`--vary anchor` surfaces the testing trap directly.** `first_divergence` is
  exactly the year where a short test range stops telling the truth (2019 for the
  motivating retail case). Making it a reported number is cheaper than hoping someone
  reads the warning.

`compare` is pure and network-free, like `preview`.

---

## Anchor rules

A fiscal year runs `anchor(y) .. anchor(y+1) - 1`. Because every anchor falls on the
same weekday, that span is always a whole number of weeks, so **52-vs-53 is derived,
never configured**. Only the leap week's *placement* is an option.

| Rule | Definition | Implemented by |
|---|---|---|
| `nearest` | Chosen weekday nearest the 1st of the start month. NRF/retail standard | Us — reproduces LULULEMON |
| `first` | First chosen weekday on or after the 1st of the start month | Us |
| `fixed52` | Anchor once, then +364 days forever | Us, and **identical to the native API** |

`nearest` verified by hand against all twelve LULULEMON year boundaries including both
371-day years (2018, 2024). `fixed52` verified against the live API output above.

### Period patterns

`pattern` selects both the period count and the weeks each period holds. Quarter
layout is derived from the period count, not configured.

| Pattern | Periods | Weeks per period in a quarter | Quarter layout | Corpus reference |
|---|---|---|---|---|
| `4-4-5` | 12 | 4, 4, 5 | 3/3/3/3 | `PERIOD_CALENDAR` (labelled `Period N`) |
| `4-5-4` | 12 | 4, 5, 4 | 3/3/3/3 | `LULULEMON` |
| `5-4-4` | 12 | 5, 4, 4 | 3/3/3/3 | — |
| `13x4` | 13 | 4 throughout | **3/3/3/4** | `FISCAL_CALENDAR_13_PERIOD` |

All four are 52 weeks in a normal year. The `13x4` quarter layout is 3/3/3/4 —
verified from `FISCAL_CALENDAR_13_PERIOD` FY2020, where Q1–Q3 hold three periods and
Q4 holds four (`Period 10`–`Period 13`).

`13x4` is a genuine structure, not a relabelling. An earlier draft of this spec put
13-period out of scope on the grounds that it was "4-4-5 with `Period N` labels";
that is true of `PERIOD_CALENDAR` (12 periods) but false of
`FISCAL_CALENDAR_13_PERIOD` (13 periods × 28 days, 364-day years, and a 371-day
FY2023). Both tables exist in the corpus and they are different things.

#### 13x4 carries a consumption constraint that the other patterns do not

Query generation is fine — the numeric columns carry all the ordering. The constraint
is in the **filter widget**, via two distinct mechanisms, both now settled:

1. **Lexical sort scrambles period order.** Confirmed against
   `FISCAL_CALENDAR_13_PERIOD` on 2026-09-15: sorting its `month` values as strings
   gives `Period 1, Period 10, Period 11, Period 12, Period 13, Period 2, …` —
   numeric order is not preserved. Any consumer that sorts the label rather than
   `month_number_of_year` lists periods wrongly.
2. **A non-month label cannot be selected in the filter widget** — confirmed at PR
   review on 2026-09-16 from ThoughtSpot product knowledge, not an automated probe.
   This is **not specific to `13x4`**: it applies to any custom `--month-names` value
   that is not a real month name. A second limitation of the same family hits the
   **year** filter, and a third case is explicitly fine:

| Label column | Custom / prefixed value | Filter widget |
|---|---|---|
| `month` | non-month names (e.g. `Period 01`) | **not selectable** |
| `year` | prefixed (e.g. `FY2024`) | **not typeable** — accepts `YYYY` only |
| `quarter` | prefixed (e.g. `Q1`) | **works** |

   So `--year-prefix FY` — an extremely common requirement, presented as an ordinary
   option — costs typed year filtering, while `--quarter-prefix Q` costs nothing. The
   design must not present this as a blanket "prefixes break filters".

**Registration is not at risk** — live 2026-09-16, a `13x4` calendar with
`Period 01`…`Period 13` labels registered successfully (200).

**Mitigation, applied by default for `13x4`:** zero-pad the generated labels
(`Period 01` … `Period 13`) so lexical and numeric order coincide. This costs nothing,
needs no product change, and removes mechanism 1 entirely.

**Mechanism 2 has no fix, only a mitigation — and the mitigation is the half that
matters.** Filter by **date range** or by a **dynamic/relative filter** ("this year"),
or on `month_number_of_year`; querying, grouping, aggregation and display are
unaffected. So `13x4` ships **documented as query-safe with a constrained filter
widget**, not as broken. The skill must say so when a user selects `13x4`, or sets
`--month-names` or `--year-prefix`, rather than presenting any of them as
unconstrained — and must say the mitigation in the same breath. `ts calendar validate`
warns on both shapes (`month-label-not-filter-selectable`,
`year-label-not-filter-typeable`) at warning severity, exit 0.

### Leap-week placement

`--leap-week-period`, default `last`:

| Value | Effect |
|---|---|
| `last` (default) | Final period of the fiscal year absorbs the extra week. 4-5-4 → Q4 becomes 4-5-5; 4-4-5 → Q4 becomes 4-4-6 |
| `1`–`12` | That period ordinal absorbs it (`1`–`13` under 13-period labelling) |

`last` is not a guess: in both LULULEMON 53-week years (2018, 2024) the extra week
lands on JAN, the final period, turning Q4 from 4-5-4 into 4-5-5. No other period
moves.

The named period gains a week, its quarter goes to 14 weeks, `week_number_of_year`
runs 1..53, and every dependent column (`week_number_of_quarter`, the
`absolute_*_number`s, the `*_epoch` boundaries) shifts accordingly. An ordinal outside
the period count is rejected.

---

## Label layer

The date grid and the labels are independent. Almost all client-specific variation
lives in the labels.

```
month_names         list[str]   # 12 or 13 — default English full names
day_names           list[str]   # 7, absolute Sunday..Saturday
year_prefix                     # e.g. "FY"
quarter_prefix                  # e.g. "Q"
year_basis          fiscal | gregorian     (default fiscal)
monthly_basis       fiscal | gregorian     (default fiscal)
quarterly_basis     fiscal | gregorian     (default fiscal)
fiscal_year_number  start | end            (default start — verified)
monthly_format      "{month} {year}"
quarterly_format    "{quarter} {year}"
```

**`month_names` collapses three features into one mechanism.** Localization,
abbreviations (`FEB`), and 13-period labelling (`Period 1..13`) are all "supply a list
of names". There is no separate label-style option.

**The three `*_basis` knobs are independent because real client requirements make them
independent.** The motivating case sets `year` and `monthly` to gregorian while
deliberately leaving `quarterly` fiscal — a single uniform switch cannot express that.
With `gregorian`, the `year` column varies *within* a fiscal year; that is intended.

`day_number_of_week` is relative to `start_day_of_week` while `day_of_week` is the
absolute day name (verified: `start_day_of_week: Monday` gives Thursday
`day_number_of_week = 4`, `day_of_week = "Thursday"`). Ordering lives in the numeric
columns, so labels are opaque strings.

### Label scope: set-level by default

`LabelSpec` attaches to the **`CalendarSet`**, shared by every variant. A per-variant
override exists but requires an explicit opt-in.

This is a structural decision, not a stylistic one. ThoughtSpot indexes a column's
values across all rows of the registered object, but RLS resolves a given user to a
single variant. If one variant labels a month `AUGUST` and another `AUG`, the UI
offers **both** as search suggestions while only one can ever return rows for any
given user — the other silently yields nothing. The same applies to `day_of_week`,
to `quarter` prefixes, and to `year` prefix drift (`FY2024` vs `2024`).

Variants legitimately differ in *grid* — start day, pattern, anchor rule, range; that
is the entire point of an RLS calendar. There is no corresponding reason for them to
differ in *vocabulary*. Defaulting the label spec to set level makes the common case
correct by construction rather than merely checkable.

Detection is still required because unions can be assembled from pre-existing tables
that never went through this generator — `rlscalendar` unions `saturdaycalendar` and
`mondaycalendar`, both built independently. Those two happen to agree (identical
month, day and quarter vocabularies, checked 2026-09-15), but nothing enforced it.
See validation invariant 9.

### Relabelling calendars that already exist

`references/relabel-calendar.sql`, parameterised and run via
`ts snowflake exec -f … --var`, the same pattern
`ts-recipe-formula-business-days-snowflake` uses. This supports
"API-generate → relabel → register" without regenerating, which is worth having
because the native `fixed52` output is correct as far as it goes.

Not a CLI command in v1. Cheap to promote later if it earns it.

---

## Row-level security — union calendars

Verified from `CUSTOM_CALENDAR.PUBLIC.rlscalendar`:

```sql
create or replace view "rlscalendar"( …30 standard columns…, TS_CALENDAR_GROUP ) as (
   select *, 'tsCalendar1' as ts_calendar_group from custom_calendar.public."saturdaycalendar"
   union all
   select *, 'tsCalendar2' as ts_calendar_group from custom_calendar.public."mondaycalendar"
);
```

RLS is **composition over N independent calendars**: generate each variant as its own
table, `UNION ALL` with a literal discriminator appended as column 31, register the
union. `damianmultitest` is the materialised-table flavour of the same idea (3
variants, 52,230 rows, discriminator column `TSGROUP`).

```
CalendarSet:
  labels:                LabelSpec          # set-level — shared by all variants
  variants:              list[(discriminator_value, CalendarSpec)]
  discriminator_column:  str = "TS_CALENDAR_GROUP"
  materialisation:       view | table
```

`labels` sits on the set, not the variant — see "Label scope" above. Variants differ
in grid; they share a vocabulary.

The discriminator column name is caller-chosen — the corpus uses both
`TS_CALENDAR_GROUP` and `TSGROUP`.

Two facts from the corpus that contradict the obvious assumptions:

- **Variants need not share a date range.** `testcal2` covers 1980-02-01..2023-01-31
  while its siblings cover 1980-07-01..2030-06-30. The union is ragged; `validate`
  checks coverage per variant, never against one global range.
- **Within a variant each date appears exactly once** (rows = distinct dates for all
  three variants). The uniqueness invariant is on `(date, discriminator)`.

### Boundary

This skill produces the correctly-shaped union and emits what an RLS rule needs. It
does **not** create the RLS rule — that means fetching, editing and reimporting the
ThoughtSpot table's TML, and `.claude/rules/skill-naming.md` already reserves
`ts-security-rls` for that work.

---

## Column contract

Two shapes, first 10 columns identical in name and order. Written from the live API's
own CSV output, corroborated across 42 corpus tables — not inferred.

| Shape | Columns |
|---|---|
| Minimum (10) | `date, day_of_week, month, quarter, year, day_number_of_week, week_number_of_month, week_number_of_quarter, week_number_of_year, is_weekend` |
| Extended (30) | the above + `monthly`, `quarterly`, `day_number_of_{month,quarter,year}`, `month_number_of_{quarter,year}`, `quarter_number_of_year`, and `absolute_*_number` / `start_of_*_epoch` / `end_of_*_epoch` for week/month/quarter/year |

`--columns 10|30`, default **30** — the corpus majority, and what period-over-period
comparisons need.

`end_of_*_epoch` is exclusive (start of the next period): the API emits
`start_of_week_epoch = 07/01/2027`, `end_of_week_epoch = 07/05/2027` for a Monday-start
week. Documented in `references/calendar-table-contract.md`.

---

## Validation invariants

`ts calendar validate` checks:

1. Column names, order and types match the 10- or 30-column contract
2. Periods tile — no gaps, no overlaps, no missing dates in range
3. Week numbering monotonic; `week_number_of_year` ∈ 1..53
4. Period lengths are whole weeks and match the declared pattern
5. Exactly one period per year is long in a 53-week year, at the declared ordinal
6. `(date, discriminator)` unique — plain `date` unique when not a set
7. Per-variant range coverage for a `CalendarSet`
8. **Warn** (not fail) when `year_basis` and `quarterly_basis` disagree: filtering
   `year = 2025` then returns dates spanning two fiscal years and `quarterly` will
   disagree with `year` on boundary rows. A legitimate choice, but it must be visible.
9. **Cross-variant label consistency** for a `CalendarSet` — see "Label scope" above
   for why. Two tiers, because the columns differ in kind:

   | Columns | Rule | Severity |
   |---|---|---|
   | `day_of_week`, `month`, `quarter` | Closed vocabularies — distinct value sets must be **identical** across every variant | **Fail**, `--allow-label-drift` downgrades to warn |
   | `year`, `monthly`, `quarterly` | Derived and open-ended; values legitimately differ by range. Compare the *format signature* — prefix presence, separator, component order | Warn |

   The failure message names the mismatching values explicitly (`month: AUGUST` vs
   `AUG`), not just the column.

   **Known legitimate conflict:** a set mixing a 12-month variant with a 13-period
   variant cannot have identical `month` vocabularies. This fails by design — it is a
   real modelling smell that produces exactly the broken-suggestion behaviour above —
   and `--allow-label-drift` is the deliberate escape hatch rather than a special case
   in the rule.

---

## Testing

Two independent ground truths — a stronger position than most converters in this repo.

| Oracle | Asserts |
|---|---|
| **LULULEMON** (`CUSTOM_CALENDAR.PUBLIC`) | `nearest` / 4-5-4 / February / Monday reproduces all 12 year boundaries *and* the full period grid for 2018 and 2024, pinning leap-week placement — not just year length |
| **Live API CSV** | `fixed52` output matches the native API row-for-row |

The LULULEMON fixture is extracted to a checked-in file so the test stays Pure tier
(no credentials, runs in CI). The API oracle is a Live-tier check.

- Unit tests: `tools/ts-cli/tests/test_custom_calendar.py` — anchors, tiling, 52/53
  derivation, pattern distribution, leap-week placement, label bases.
- Smoke test: `tools/smoke-tests/smoke_ts_object_calendar_builder.py`, **Pure** tier,
  plus its row in `tools/smoke-tests/README.md`.

Test range must span ≥ 4 years wherever native-vs-generated behaviour is compared —
see the testing trap under Problem.

---

## Skill flow

Step 0 plan block with confirmation gate → authenticate → gather spec (batched
independent questions) → `preview` + **confirm gate** → `generate` → `validate` →
load to Snowflake *or* hand over the CSV → `register` (native fast path only when the
rule is `fixed52`) → `search` to verify → Error Handling table → Changelog at 1.0.0.

### Reference files

| File | Purpose |
|---|---|
| `references/calendar-table-contract.md` | The 10/30 column contract, value formats, epoch exclusivity |
| `references/anchor-rules.md` | The three rules with worked year tables and the nearest-vs-first divergence |
| `references/relabel-calendar.sql` | Parameterised relabel CTAS for existing calendars |
| `references/open-items.md` | See below |

---

## Open items (verify live before/during implementation)

1. **Non-English labels — VERIFIED 2026-09-16.** A 30-column calendar with Japanese
   month (`2月`…`1月`) and day (`日曜日`…`土曜日`) labels registered successfully
   (200, calendar `643ff2ed`, deleted afterwards). Non-Latin labels are accepted; the
   API does not parse the label strings and ordering lives in the numeric columns, as
   the design assumed. The corpus had no such example — none of the 42 tables in
   `CUSTOM_CALENDAR.PUBLIC` uses one, `rlscalendarjapan` included — so this replaces
   an inference with direct evidence. Status: **VERIFIED**.
2. **`generate-csv` is unavailable on `se-thoughtspot`.** Every request shape returns
   504 or times out, including the documented happy path (`MONTH_OFFSET` July,
   month-boundary start). The control failing is what makes this a cluster/endpoint
   problem, not a request-shape problem. All native-API findings in this design come
   from `semantic-sql`. Re-verify on a second cluster before relying on `--native`.
3. **`fiscal_year_number` default.** Verified `start` on `semantic-sql` for July and
   December offsets. May be version- or config-dependent; re-check on another build
   before documenting it as invariant.
4. **`FROM_EXISTING_TABLE` schema validation — VERIFIED 2026-09-16, and the answer is
   that the API never says what is wrong.** Every contract violation returns the
   identical response: HTTP 400, code `10002`, `INVALID_EXTERNAL_CALENDAR` wrapping
   `CONNECTION_METADATA_FETCH_ERROR` ("Unable to fetch column metadata for external
   table : `<db>.<schema>.<table>`"), with the reason as a JSON-escaped string inside
   `error.message.debug.debug`. Identical for a missing column, a correct 10-column
   table, a wrong type (`date` as TEXT), an extra column, and a table that does not
   exist at all; control — a valid 30-column table — returns 200. **It never names the
   offending column.** So `validate` cannot mirror the API's message and must catch
   problems locally instead, which is what it does. Status: **VERIFIED**.
5. **`--native`'s `start_date` / `end_date` convention — RESOLVED, and the original
   reading was WRONG.** The design shipped with `build_register_payload` constructing
   the range as the nominal start of `first_year` through the nominal start of
   `last_year + 1`. The published `createCalendar` example could not adjudicate it — it
   pairs `start_date: "04/01/2025"` with `end_date: "04/31/2025"`, which is not a valid
   date — so this was flagged as the highest-value live check before trusting
   `--native`. That check was run, and it failed:

   | Source | Rows | Range |
   |---|---|---|
   | Our generator (`build_rows`) | 1092 | 2027-02-01 .. 2030-01-27 |
   | ThoughtSpot `generate-csv`, old payload | 1097 | 2027-02-01 .. 2030-02-01 |

   The five extra days form a partial fiscal period — a stub 13th month past the true
   year-end — and the overshoot **grows** with the requested range (2 days for one year,
   5 for three), which is what identifies `end_date` rather than a fixed per-request pad
   as the cause. `end_date` must be the last day the calendar actually covers, the day
   before the next fiscal year's anchor: `resolve_anchor(spec, last_year + 1) - 1 day`,
   which equals `build_rows(spec, ...)[-1]["date"]`. `build_register_payload` now
   computes it that way and the corrected payload was re-verified live as byte-identical
   to our generator's output for the same spec.

   `start_date` was separately checked rather than assumed, and is correct as-is: the
   API snaps a submitted `start_date` forward to the next `start_day_of_week`, the same
   rule `anchor_first` implements, so the `MM/01/{first_year}` literal is an input to
   that snap and not the first row's date. This closes the silent-day-drift risk the
   item existed to catch; the convention is pinned by exact-value unit tests against the
   live-confirmed values. Status: **VERIFIED 2026-09-16** (see the skill's
   `references/open-items.md` item 5).
6. **Filter-widget behaviour for custom labels — VERIFIED 2026-09-16.** Wider than the
   `13x4` question this item was opened for.
   - *Provenance, and it bounds how this may be cited:* the filter-widget half was
     answered by the repository owner, a ThoughtSpot solutions engineer, from direct
     product knowledge, confirmed during PR review on 2026-09-16. **Expert product
     knowledge, not a test result.** No REST surface could have produced it:
     `POST /calendars/search` returns metadata only (name, connection, author, ids) —
     no column values, no ordering — so this needed a person or a browser, not a probe.
   - *Closed — lexical sort:* `Period 1..13` does not sort numerically as strings.
     Mitigated by zero-padding the default labels. Custom unpadded `--month-names`
     reintroduce it; `ts calendar validate` warns on any non-month label, covering it.
   - *Closed — registration, by live API:* a `13x4` calendar with `Period 01`…`Period 13`
     labels registers successfully (200, calendar `d2309815`, deleted afterwards). The
     API accepts non-month `month` labels; `--native`'s `13x4` refusal is about
     `FROM_INPUT_PARAMS` having no 13-period calendar type, not about the shape.
   - *Closed — the filter widget:* the limitation is confined to the **typed-value**
     filter components, and it is an asymmetry, not a blanket rule:

| Label column | Custom / prefixed value | Filter widget |
|---|---|---|
| `month` | non-month names (e.g. `Period 01`) | **not selectable** |
| `year` | prefixed (e.g. `FY2024`) | **not typeable** — accepts `YYYY` only |
| `quarter` | prefixed (e.g. `Q1`) | **works** |

     **L1** — a month/period label that is not a month name cannot be selected; this
     generalises to *any* custom `--month-names`, not just `13x4`. **L2** — the year
     filter accepts `YYYY` only, so a `--year-prefix` value cannot be typed into it;
     this matters disproportionately because the prefix is a very common requirement.
     **`--quarter-prefix` works** and must not be warned against.
   - *The qualification, and it carries equal weight:* the calendar remains fully
     usable. Date-range filters and dynamic/relative filters ("this year") work; query
     generation, grouping, aggregation and display are unaffected, because the numeric
     columns carry all the true ordering. Custom labels do not break calendars — they
     narrow which filter components accept typed input.
   - *Not established, and not to be implied:* whether a localized real month name
     (`2月`, `février`) reads to the widget as a month name (it registers fine — item 1),
     and whether a `MONTH_YEAR` filter submitted through the REST API accepts a period
     label. Neither changes the guidance; the mitigation is the same either way.
   - Status: **VERIFIED 2026-09-16** — filter behaviour from expert product knowledge at
     PR review, registration from a live API call. See the skill's
     `references/open-items.md` item 6.

---

## Out of scope (v1)

- Databricks loading — `ts load databricks` exists, but doubles the DDL and
  type-mapping surface for no demonstrated demand.
- Calendar `update` / `delete` lifecycle — `search` is included only to verify
  registration.
- Creating RLS rules — see the boundary note above; belongs to `ts-security-rls`.
- ~~13-period as a separate structure~~ — **corrected and brought into scope.** See
  "Period patterns": `FISCAL_CALENDAR_13_PERIOD` is a real 13×28 grid, not a
  relabelled 4-4-5. Shipping it as `pattern: 13x4` costs less than the false
  justification did.
- `relabel` as a CLI command — ships as a parameterised `.sql` recipe.

---

## Repo wiring checklist

- `agents/cli/ts-object-calendar-builder/SKILL.md` — family `ts-object-*`, no naming
  rule change needed
- README skills-table row
- Both `ln -s` blocks in `agents/cli/SETUP.md` (Cortex + Claude Code)
- `EXPECTED_DIVERGENCES` entry in `tools/validate/check_runtime_coverage.py`
- Same-day `CHANGELOG.md` entry (hard-gated)
- Regenerate `agents/PARITY.md`
- `ts_cli` version bump in both `__init__.py` and `pyproject.toml`
- `tools/ts-cli/README.md` command docs
- Smoke test + `tools/smoke-tests/README.md` row
