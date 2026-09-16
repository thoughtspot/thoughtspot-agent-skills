# Open Items

Tracked findings from building this skill against the live corpus and the
`semantic-sql` cluster. Each entry records what is known, what would resolve
it, and its current status. See
`docs/superpowers/specs/2026-09-15-ts-object-calendar-builder-design.md` for
the full design context these were verified against.

## 1 — Non-English labels

No table among the 42 in `CUSTOM_CALENDAR.PUBLIC` uses a non-English label —
`rlscalendarjapan` is English despite its name. The evidence that this
matters is strong but indirect: three mutually-incompatible label styles
already ship in production (`April`, `FEB`, `Period 1`), and no month-name
parser would accept `Period 1` either, so localized labels are plausible but
unconfirmed. Needs a live round-trip: register a calendar with non-Latin
month and day names and confirm it imports and is searchable. The design is
believed safe either way, because ordering lives in the numeric columns, not
the label strings.

**Status: UNVERIFIED.**

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

## 4 — `FROM_EXISTING_TABLE` schema-validation error shape

The `createCalendar` API errors when the referenced warehouse table doesn't
match the required column contract, but the exact error shape (status code,
body structure, which mismatch is named) is undocumented and has not been
captured live. Capturing it would let `ts calendar validate` pre-empt the
same problem locally with a clearer message, before a `register` call ever
reaches the API.

**Status: UNVERIFIED.**

## 5 — `--native`'s `start_date` / `end_date` convention is unconfirmed, and the published API example cannot settle it

`register --native` constructs the registration range as the nominal start
of `first_year` through the nominal start of `last_year + 1`. That is a
defensible reading of the API, but it has not been checked against a live
cluster — and the `createCalendar` spec's own worked example pairs
`start_date: "04/01/2025"` with `end_date: "04/31/2025"`, which is not a
valid date (April has 30 days), so the published documentation is
internally broken and settles nothing either way.

This matters more than a typical open item because `fixed52`'s entire risk
profile is *silent* day-drift: a wrong boundary produces a calendar that
imports cleanly, validates cleanly, and is quietly short or long by some
number of days — exactly the failure mode this skill exists to prevent for
the other two anchor rules. The convention is pinned by an exact-value unit
test, so a future change to it will be visible in CI, but "pinned" is not
the same as "correct."

*What would resolve it:* register a `fixed52` calendar via `--native` on a
live cluster and compare the resulting row range against a locally
generated `fixed52` calendar for the same years — they must match day for
day. **This is the highest-value live check before `--native` is trusted
for anything beyond the smoke test.**

**Status: UNVERIFIED.**

## 6 — Filter-widget behaviour for `13x4` period labels

Two independent mechanisms, one confirmed and mitigated, one still open —
see [anchor-rules.md](anchor-rules.md) for the full discussion.

- *Confirmed:* a lexical sort of `Period 1..13` does not preserve numeric
  order (`Period 1, Period 10, Period 11, …, Period 2, …`). Mitigated by
  zero-padding the default generated labels (`Period 01`…`Period 13`); no
  further action needed unless a user supplies custom, unpadded
  `--month-names`, which `validate` should warn about.
- *Open:* whether a Liveboard filter widget and the `MONTH_YEAR` date-filter
  type accept a non-month string as `month_name`, and whether the widget
  orders choices by `month_number_of_year` or by the label text. The REST
  spec documents `month_name` as "Name of the month in uppercase" and lists
  `PERIOD_ONLY` as an unsupported filter type, so the concern is real, but
  its actual enforcement in the product has not been tested live.

*What would resolve it:* register a `13x4` calendar on a live cluster,
build a Liveboard filter on its month column, and check (a) the order
periods are listed in, (b) whether selecting `Period 13` filters correctly,
(c) whether a `MONTH_YEAR` filter via the REST API accepts a period label.

*If it fails:* `13x4` remains useful for query generation and aggregation —
document the fallback (filter on `month_number_of_year` or a date range)
rather than withdrawing the pattern.

**Status: UNVERIFIED (the mitigated half is closed; the filter-widget half
is open).**
