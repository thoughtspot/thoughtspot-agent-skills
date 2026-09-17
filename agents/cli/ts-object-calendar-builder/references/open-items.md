# Open Items

Tracked findings from building this skill against the live corpus and the
`semantic-sql` cluster. Each entry records what is known, what would resolve
it, and its current status. See
`docs/superpowers/specs/2026-09-15-ts-object-calendar-builder-design.md` for
the full design context these were verified against.

## 1 — Non-English labels — VERIFIED 2026-09-16

**Non-Latin month and day labels are accepted.** A 30-column calendar whose
`month` values were `2月`…`1月` and whose `day_of_week` values were
`日曜日`…`土曜日` registered successfully via `FROM_EXISTING_TABLE` on
`se-thoughtspot` (HTTP 200, calendar id `643ff2ed`). The probe calendar was
deleted afterwards (204).

This is now direct evidence rather than inference. The corpus contained no
such example — none of the 42 tables in `CUSTOM_CALENDAR.PUBLIC` uses a
non-English label, `rlscalendarjapan` included, which is English despite its
name — so the earlier reading rested on the fact that three mutually
incompatible label styles already ship in production (`April`, `FEB`,
`Period 1`) and no month-name parser would accept `Period 1` either. That
inference held: the API does not parse the label strings, and ordering lives
in the numeric columns, exactly as the design assumed.

**Status: VERIFIED 2026-09-16.**

## 2 — `generate-csv` unavailable on `se-thoughtspot`

Every request shape to the native ThoughtSpot `generate-csv` endpoint
returns 504 or times out on `se-thoughtspot`, including the documented happy
path (`MONTH_OFFSET`, July, month-boundary start). Because the *control*
case also fails, this reads as a cluster/endpoint problem, not a
request-shape problem. All native-API findings in this design — including
the leap-week and `monthly`-mislabelling findings the whole skill exists to
work around — come from a different cluster, `semantic-sql`. Re-verify on a
second cluster before relying further on `--native`.

**Status: VERIFIED on one cluster only (`semantic-sql`).**

## 3 — `fiscal_year_number` default

Verified `start` (the fiscal year is numbered by the calendar year it
*starts* in) on `semantic-sql`, for both July and December start-month
offsets. This may be version- or configuration-dependent rather than a fixed
platform default — re-check on another ThoughtSpot build before documenting
it as an invariant that never varies.

**Status: VERIFIED, re-check on another build.**

## 4 — `FROM_EXISTING_TABLE` schema-validation error shape — VERIFIED 2026-09-16

**Captured live, and the answer is that the API never tells you what is
wrong.** Every contract violation returns the *identical* response:

```
HTTP 400
{"error":{"message":{"debug":{"code":10002, ...
  "Error Code: INVALID_EXTERNAL_CALENDAR
   Error Message: Table <db>.<schema>.<table> cannot be imported as calendar because:
   Error Code: CONNECTION_METADATA_FETCH_ERROR
   Error Message: Unable to fetch column metadata for external table : <db>.<schema>.<table>"
```

Status 400, top-level code `10002`, calendar-specific code
`INVALID_EXTERNAL_CALENDAR`, and the human-readable reason nested as a
JSON-escaped string inside `error.message.debug.debug` — not a structured
field list.

**The same response came back for every one of these**, on `se-thoughtspot`,
2026-09-16:

| Probe | Response |
|---|---|
| Table does not exist | 400, identical body |
| 30-column table missing one contract column | 400, identical body |
| Correct 10-column table, correct types | 400, identical body |
| 30-column table with `date` typed as TEXT | 400, identical body |
| 30-column table with one extra column | 400, identical body |
| **Control:** valid 30-column table | **200** |

**It never names the offending column**, and it does not distinguish "table
missing" from "table wrong" — the earlier partial finding read the
`CONNECTION_METADATA_FETCH_ERROR` as a metadata-fetch failure specific to a
non-existent table, and that reading was too generous: it is simply the only
message this endpoint emits.

**Consequence, and it is the useful half.** `ts calendar validate` cannot
mirror the API's message, because the API has no message to mirror. It has to
catch the problem locally instead — which is what it does: an exact header
match against the 10- or 30-column contract plus at most one trailing
discriminator, per-row contract shape, duplicate/missing dates, week-number
range, and a `ten-column-not-registrable` warning for the shape this probe
proved is rejected. Two of the five failing probes above (missing column,
extra column) are caught by `validate` before a `register` call is made.

**Status: VERIFIED 2026-09-16.**

## 5 — `--native`'s `start_date` / `end_date` convention — VERIFIED 2026-09-16

`register --native` used to construct the registration range as the nominal
start of `first_year` through the nominal start of `last_year + 1`. The
published `createCalendar` spec worked example could not settle whether
this was right: it pairs `start_date: "04/01/2025"` with
`end_date: "04/31/2025"`, which is not a valid date (April has 30 days), so
the documentation is internally broken and adjudicates nothing.

**Live comparison, `start_month=February, start_day_of_week=Monday,
pattern=4-5-4, anchor_rule=fixed52, first_year=2027, last_year=2029`:**

| Source | Row count | Range |
|---|---|---|
| Our generator (`build_rows`) | 1092 | 2027-02-01 .. 2030-01-27 |
| ThoughtSpot `generate-csv`, given our old payload | 1097 | 2027-02-01 .. 2030-02-01 |

The API's five extra days are not noise — they form a partial fiscal
period, a stub 13th month past the true year-end. The overshoot **grows**
with the range: 2 days for a 1-year request, 5 days for this 3-year one,
confirming it is `end_date` itself (the nominal "start of `last_year + 1`"
form) that is wrong, not a fixed per-request pad.

**Confirmed rule:** `end_date` must be the last day the calendar actually
covers — the day before the next fiscal year's anchor:
`resolve_anchor(spec, last_year + 1) - 1 day`, which equals
`build_rows(spec, ...)[-1]["date"]`. `build_register_payload` now computes
it via `resolve_anchor` (imported from `ts_cli.custom_calendar.anchors`)
rather than the old string arithmetic.

**`start_date` was separately checked, not just assumed, and found correct
as-is.** For `fixed52`, `resolve_anchor(spec, first_year)` reduces to
`anchor_first(first_year, start_month, start_dow)` — the first chosen
weekday on or after the 1st of `start_month` — and the live API's first row
(2027-02-01) matched it exactly. The existing `MM/01/first_year` literal
works because the API snaps a submitted `start_date` forward to the next
`start_day_of_week`, which is the same rule `anchor_first` implements; the
literal is just an input to that snap, not the row's actual date (e.g. for
`first_year=2015` the literal `02/01/2015` snaps to the API's actual first
row 2015-02-02, a Monday, since Feb 1 2015 was a Sunday — verified against
the generator's own first row for the same spec). No change was needed.

This closes the risk this item existed to catch: `fixed52`'s entire risk
profile is *silent* day-drift, where a wrong boundary produces a calendar
that imports cleanly, validates cleanly, and is quietly short or long by
some number of days. The convention is now pinned by exact-value unit tests
in `tools/ts-cli/tests/test_custom_calendar_cli.py`
(`test_native_payload_carries_generation_parameters`,
`test_native_payload_date_range_spans_multiple_fiscal_years`) against the
live-confirmed values, not the old placeholder ones.

**Status: VERIFIED 2026-09-16.**

## 6 — Filter-widget behaviour for custom labels — VERIFIED 2026-09-16

**Provenance, and it decides how much weight this carries.** The
filter-widget half of this item was answered by the repository owner — a
ThoughtSpot solutions engineer — from direct product knowledge, confirmed
during PR review on 2026-09-16. It is **expert product knowledge, not an
automated probe result**, and nothing in this repo tested it. There is no
REST surface that could: `POST /calendars/search` returns metadata only —
name, connection, author, ids — with no column values and no ordering
information, so the question needs a browser session or a person who knows
the product. The *registration* half further down **is** a live API result.

### What the filter widget does with custom labels

The limitation is confined to the **typed-value** filter components, and it
is an asymmetry rather than a blanket rule about custom labels:

| Label column | Custom / prefixed value | Filter widget |
|---|---|---|
| `month` | non-month names (e.g. `Period 01`) | **not selectable** |
| `year` | prefixed (e.g. `FY2024`) | **not typeable** — accepts `YYYY` only |
| `quarter` | prefixed (e.g. `Q1`) | **works** |

- **L1 — a period/month label that is not a month name cannot be selected in
  the filter widget.** This is a known product limitation, and it is why a
  `13x4` calendar's `Period 01`…`Period 13` labels cannot be picked from the
  filter. **It generalises past `13x4`:** it applies to *any* custom
  `--month-names` that are not real month names, whatever the pattern.
- **L2 — the year filter accepts only `YYYY`.** A calendar whose `year`
  column reads `FY2024` cannot be filtered by typing `FY2024` — the widget
  takes a four-digit year and nothing else. This one matters out of
  proportion to its size, because `--year-prefix FY` is an extremely common
  requirement and the option is presented as ordinary.
- **`--quarter-prefix` works** — `Q1` is selectable. The `YYYY`-only
  constraint is specific to the **year** filter and does not extend to
  quarters. Do not warn users off `--quarter-prefix`: a caveat on an option
  that works costs them a capability for nothing.

### The qualification — carries the same weight as the limitations

**The calendar remains fully usable.** Only the *typed-value* filter
components are affected. Everything else behaves normally:

- **Date-range filters work.**
- **Dynamic / relative filters work** — "this year", "last quarter", and so on.
- **Query generation, grouping, aggregation and display are unaffected.** The
  numeric columns (`month_number_of_year`, `quarter_number_of_year`,
  `absolute_week_number`, …) carry all the true ordering regardless of what
  the labels say, and the labels display exactly as written.

So this is **not** "custom labels break calendars". Custom labels narrow
*which filter components accept typed input*. A `13x4` calendar, or an
`FY`-prefixed one, is a legitimate calendar to build — filter it with a date
range or a dynamic filter, or on the numeric period/quarter columns.

### Closed — registration, VERIFIED by API 2026-09-16

A `13x4` calendar with zero-padded `Period 01`…`Period 13` labels
**registers successfully** via `FROM_EXISTING_TABLE` on `se-thoughtspot`
(HTTP 200, calendar id `d2309815`; deleted afterwards, 204). This half *was*
verified by API. A 13-period calendar with non-month `month` labels is
therefore accepted by the create endpoint — the refusal `--native` carries
for `13x4` is about `FROM_INPUT_PARAMS` having no 13-period calendar *type*,
not about the shape being unacceptable.

### Closed — lexical sort

A lexical sort of `Period 1..13` does not preserve numeric order (`Period 1,
Period 10, Period 11, …, Period 2, …`). Mitigated by zero-padding the default
generated labels (`Period 01`…`Period 13`), which makes lexical and numeric
order coincide at no cost. Custom, unpadded `--month-names` reintroduce it —
`ts calendar validate` now warns on any non-month `month` label, which covers
that case as well as L1.

### What was NOT established, and must not be implied

- **Localized month names.** Whether a real month name in another language
  (`2月`, `février`) reads to the widget as a month name or as a non-month
  label was not part of what was confirmed. Such a calendar *registers* fine
  (item 1, live-verified) and `validate` warns on it under L1 out of caution;
  treat the filter behaviour as not established either way.
- **`MONTH_YEAR` filters submitted through the REST API.** The spec documents
  `month_name` as "Name of the month in uppercase" and lists `PERIOD_ONLY` as
  an unsupported filter type, which is consistent with L1, but the REST path
  specifically was not probed.

Neither gap changes the guidance, because the mitigation for both is the same
one already documented above: date-range or dynamic filters, or the numeric
columns.

**Status: VERIFIED 2026-09-16** — filter behaviour from expert product
knowledge confirmed at PR review; registration from a live API call.
