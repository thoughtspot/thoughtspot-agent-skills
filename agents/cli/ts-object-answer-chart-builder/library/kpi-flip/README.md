# Year to date, flip card

What is the year-to-date figure, and which months made and lost it?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a bar for the month, its sales and whether it is above or below the average month. Click a bar to select it and dim the rest (Escape clears).

## Notes
Built on MayaCharts 0.18.1 as a horizontal `bar` of the three best and three weakest months in the filter, toned against the average month with `colorBy: { target }` and labelled with their values. The title carries the year-to-date figure and its change on the same months a year earlier, so the front and the back of the old card now share one face. The body only derives the year to date, the ranking and the average. Dropped from the old chart: the flip itself (MayaCharts has no two-faced tile), the Sales, Units, Price toggle and the count-up of the front number. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 7 code lines, the loader included. It reads the months, picks the three best and three weakest and derives the average month for the `colorBy` target and the subtitle; the column names are plain.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
