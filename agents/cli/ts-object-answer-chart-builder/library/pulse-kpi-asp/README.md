# Average selling price

Is the price per unit rising or sliding?

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
Built on MayaCharts 0.18.1 as a `kpi` tile with `aggregate: { ratio: ['Sales', 'Units'] }`, so each year's price is its total sales over its total units for the same months (never an average of monthly prices). The body keeps the months from January to the latest month of every year that has all of them and labels each row with its year; the change line reads this year against the same months last year. The sparkline is now one point per year, not the last 24 months. Dropped against the old tile: the YTD and All toggle, the month-level sparkline with its year-earlier tooltip, and the span caption. The tile is no longer shared with the other Pulse KPIs through data-kpi. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 7 code lines (comments aside), the loader included: it still derives the same-months-per-year rows; the ratio and the price format are spec options.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
