# Quarter pairs, drill to months

How does each quarter of this year compare with the same quarter last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Sales and Units sold toggle. Hover, or use the arrow keys, for a pair. Click a quarter (or Enter) to drill into its months, paired the same way; Back, Escape or a click on empty space returns. Click a legend key to hide a year.

## Notes
Built on MayaCharts 0.18.1 as a grouped `bar` with `path: ['Quarter', 'Month']`, `drill: true` and `series: 'Year'`: the latest year in ink against the year before in slate, coloured through the `--maya-series-1` and `--maya-series-2` tokens in chart.css. The body builds one row per month of the latest year plus the same month a year earlier, so only quarters with data in the latest year are drawn and a part quarter (marked *) is compared on the same months only. Dropped against the old tile: the Price toggle (`aggregate: { ratio }` cannot be combined with a `y` array, and a summed per-row price would be wrong at quarter level), the YTD headline number (the title would have to change with the measure) and the value labels over each pair. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 10 code lines, the loader included. It still builds the quarter and month rows with the prior-year twin (MayaCharts has no quarter grouping); the column names are plain.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
