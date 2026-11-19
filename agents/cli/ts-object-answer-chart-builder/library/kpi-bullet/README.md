# Latest month, bullet

Where does the latest month sit against the best and the average month?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover the sparkline for each month's sales and whether it sits below the average, above it, or at the best month; arrow keys step through the months. The headline counts up on first draw.

## Notes
Built on MayaCharts as a `kpi` tile (7 code lines on 0.18.1, plain column names, the adapter reads the search): the headline is the latest month, `yDomain` sets the bullet scale a little past the best month, and `colorBy: { target: best month, warn: average month }` draws the two bands, the target tick at the best month and the bar toned below average, above average or best (status words and tooltip words renamed through `text`). The change lines read against the previous month and against the best month; the subtitle names the average and the best month. The body only reads the best and average month, because `yDomain` and `colorBy` need numbers. Dropped from the old chart: the Sales, Units, Price toggle (a MayaCharts `kpi` has no measure toggle; a `y` array draws every measure at once and leaves no room for the bullet on a 3x4 tile), the year-to-date change in the header and the marker legend. With no rows the title still shows above the empty state. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
