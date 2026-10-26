# Year to date, odometer

What is the year-to-date figure, and which way is it moving?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover the sparkline for each year's figure over the same months; arrow keys step through the years. The headline counts up on first draw.

## Notes
Built on MayaCharts 0.18.1 as a `kpi` tile over one row per year, each summing the same months as the latest year (January to the latest month); years missing any of those months are left out. The headline is year to date, the change line reads against the same months a year earlier, and the sparkline shows the same-months figure across the years in view. Dropped from the old chart: the rolling digit columns (MayaCharts counts the number up instead) and the click to cycle Sales, Units and Price (a `kpi` `y` array shows all three at once, with no sparkline and so no hover, on a 3x4 tile). Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 7 code lines, the loader included. It sums January to the latest month for each year (Units are no longer carried, since only Sales is drawn); the column names are plain.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
