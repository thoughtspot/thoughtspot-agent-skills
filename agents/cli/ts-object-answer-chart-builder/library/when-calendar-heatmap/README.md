# Sales, units and price by month

Which months and years were high or low, and how did price per unit move?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Toggle Sales / Units / Price per unit above the grid; the cells re-colour and the ramp key rescales to the selected measure. Hover a cell (or arrow-key to it) for the month, year and value. Click a cell to select it, Escape clears.

## Notes
Built on MayaCharts 0.18.1 as one `heatmap` spec: `x: 'Month'` (Jan to Dec), `series: 'Year'` (one row per year) and `y: ['Sales', 'Units', 'Price']`, a measure toggle. The body fills the grid Jan to Dec for every year with nulls for missing months, which keeps calendar order in the columns and rows and leaves part years (2021, 2026) blank where they have no data. Price per unit is `aggregate: { Price: { ratio: ['Sales', 'Units'] } }`, that month's sales over its units; the body adds no price column. The ramp is a slate accent; there is no hue. Dropped against the old chart: the same-month-last-year change in the tooltip (heatmap takes no `tooltip.fields`), the highlight of one calendar month across years, the year drill into 12 monthly columns with last year outlined, and the peak / low headline. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
