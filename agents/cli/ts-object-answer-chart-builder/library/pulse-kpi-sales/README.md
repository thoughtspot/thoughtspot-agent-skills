# Sales, year to date

How much have we sold this year, against the same months last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover the sparkline, or focus the tile and use the arrow keys, for each year's total over the same months; Space pins the tooltip. The headline counts up on the first draw.

## Notes
Built on MayaCharts 0.18.1 as a `kpi` tile. The body sums nothing itself: it keeps the months from January to the latest month of every year that has all of them (a part year, such as the first year of the data or one cut by a date filter, is left out) and labels each row with its year, so the kpi sums each year and its built-in change line reads this year against the same months last year. The sparkline is now one point per year over those months, not the last 24 months. Dropped against the old tile: the YTD and All toggle (kpi has no period toggle), the month-level sparkline with its year-earlier tooltip, and the caption naming both spans (the title names the months instead). The tile is no longer shared with the other three Pulse KPIs through data-kpi: each has its own spec. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 7 code lines (comments aside), the loader included: it still derives the same-months-per-year rows.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
