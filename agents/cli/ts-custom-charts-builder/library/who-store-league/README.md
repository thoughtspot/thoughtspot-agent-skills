# Store league: position, movement and form

Which stores lead this year, which are climbing, and which are in form?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [region] [date].monthly [date].'this year' [date].'last year'` |
| Library | Plain HTML table (no CDN) |
| Tile | 12x7 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Region chips filter (rows glide, FLIP); click a header to sort by position, movement, store, region, YTD sales, change or form (rows glide); hover a row for YTD, same months last year, change, position change and form count, plus a line explaining the hovered column; hover a form square for that month against the same month a year earlier; click a row (or Enter) to open its monthly bars, this year in ink against last year in slate, bars grow in; hover a month for both values; click again or Escape closes

## Notes
Position is by sales over the year-to-date window: the first month of the latest year in the result through the latest complete month; last year uses the same months. Movement is last year's position over that window minus this year's. Form is the last 5 complete months, each against the same month a year earlier: filled good above, filled bad below, hollow level (within 0.05%), dashed when the month a year earlier is missing. A latest month whose total is under 60% of the median of the three before it is treated as partial and left out of YTD and form, with a footnote. With no last-year months (a this-year-only filter), change, movement and form show - and the footnote says why. Chips filter the view; positions stay the league positions of the whole result. A single store opens its monthly detail. In this data Jan to May 2026 equal 2025 exactly, so May shows level for every store. Region is slate text, never a hue. Bar column hidden under 560px, YTD sales under 400px, movement under 330px. Preview only: built on real search output and checked in the preview, but not yet on a Liveboard or seen in a real cluster tile.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
