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

## 6 — Filter-widget behaviour for `13x4` period labels — SPLIT

Three mechanisms, two now closed and one still open — see
[anchor-rules.md](anchor-rules.md) for the full discussion.

- *Closed (lexical sort):* a lexical sort of `Period 1..13` does not preserve
  numeric order (`Period 1, Period 10, Period 11, …, Period 2, …`). Mitigated
  by zero-padding the default generated labels (`Period 01`…`Period 13`); no
  further action needed unless a user supplies custom, unpadded
  `--month-names`, which `validate` should warn about.
- *Closed (registration) — VERIFIED 2026-09-16:* a `13x4` calendar with
  zero-padded `Period 01`…`Period 13` labels **registers successfully** via
  `FROM_EXISTING_TABLE` on `se-thoughtspot` (HTTP 200, calendar id
  `d2309815`; deleted afterwards, 204). A 13-period calendar with non-month
  `month` labels is therefore accepted by the API — the refusal `--native`
  carries for `13x4` is about `FROM_INPUT_PARAMS` having no 13-period
  calendar *type*, not about the shape being unacceptable.
- *Open (filter widget and `MONTH_YEAR` filters):* whether a Liveboard filter
  widget and the `MONTH_YEAR` date-filter type accept a non-month string as
  `month_name`, and whether the widget orders choices by
  `month_number_of_year` or by the label text. The REST spec documents
  `month_name` as "Name of the month in uppercase" and lists `PERIOD_ONLY` as
  an unsupported filter type, so the concern is real, but its enforcement in
  the product is untested.

*Why the open half stayed open on 2026-09-16:* `POST /calendars/search`
returns metadata only — name, connection, author, ids — with no column values
and no ordering information, so it cannot answer a question about what a
widget displays. There is no REST surface for it.

*What would resolve it (needs a browser session against a cluster with the
`d2309815`-style calendar registered):* build a Liveboard filter on the
calendar's month column and record (a) the order the periods are listed in,
(b) whether selecting `Period 13` filters correctly, (c) whether a
`MONTH_YEAR` filter submitted via the REST API accepts a period label.

*If it fails:* `13x4` remains useful for query generation and aggregation —
document the fallback (filter on `month_number_of_year` or a date range)
rather than withdrawing the pattern.

**Status: registration VERIFIED 2026-09-16; the filter-widget half remains
UNVERIFIED.**
