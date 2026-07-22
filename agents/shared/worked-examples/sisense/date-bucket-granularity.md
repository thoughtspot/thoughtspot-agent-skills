<!-- currency: sisense — 2026-07 (Sisense L2024.x JAQL) -->
# Worked example — Sisense date `level` → ThoughtSpot date bucket

A Sisense date dimension on a widget carries a `level` that sets its granularity (a month
axis, a yearly trend, …). ThoughtSpot expresses the same idea as a **date bucket** on the
column, written as a search token suffix `[Column].MONTHLY`. `ts sisense build-liveboard`
translates the `level` so a month axis sorts chronologically (Jan…Dec) rather than
alphabetically, and so a yearly trend rolls up correctly.

## The mapping (from `answers.py._DATE_BUCKET_MAP`)

| Sisense `level` | ThoughtSpot bucket suffix | Token |
|---|---|---|
| `hours` | `HOURLY` | `[Order Date].HOURLY` |
| `days` | `DAILY` | `[Order Date].DAILY` |
| `weeks` | `WEEKLY` | `[Order Date].WEEKLY` |
| `months` | `MONTHLY` | `[Order Date].MONTHLY` |
| `quarters` | `QUARTERLY` | `[Order Date].QUARTERLY` |
| `years` | `YEARLY` | `[Order Date].YEARLY` |

A `level` outside this set (a **cyclic** part such as day-of-week or month-of-year) returns no
suffix — there is no clean single-bucket equivalent, so the column is plotted ungrouped and the
granularity is left for a human to reconstruct.

## Example

A Sisense line widget trending revenue by month:
```json
{
  "type": "chart/line",
  "metadata": { "panels": [
    { "name": "x-axis", "items": [
      { "jaql": { "dim": "[Orders.Order Date (Calendar)]", "level": "months" } } ] },
    { "name": "values", "items": [
      { "jaql": { "dim": "[Orders.Revenue]", "agg": "sum" } } ] }
  ]}
}
```

Resolution:
- `[Orders.Order Date (Calendar)]` → model column `Order Date` (the `Orders.` qualifier and the
  `(Calendar)` hierarchy tag are stripped).
- `level: "months"` → bucket suffix `MONTHLY`; the field carries the token `[Order Date].MONTHLY`.
- The dimension is on the `x-axis` panel → role `Category` (x); the measure → role `Values` (y).

The emitted `build_from_spec` visual therefore requests the monthly bucket on the date axis, so
the line renders one point per month in calendar order.

## Gotchas (from the code)

- **Date buckets apply to dimensions only.** A measure never gets a bucket suffix
  (`date_bucket_suffix` is skipped when the field is a measure).
- **Hierarchy tag stripping.** `Date (Calendar)` → `Date` happens before the model-column match,
  so a Sisense calendar-hierarchy dim binds to the plain base column.
- **Cyclic parts are dropped, not guessed.** Day-of-week / month-of-year style levels have no
  bucket in `_DATE_BUCKET_MAP`; the field is plotted without a bucket rather than mapped to the
  wrong grain.
