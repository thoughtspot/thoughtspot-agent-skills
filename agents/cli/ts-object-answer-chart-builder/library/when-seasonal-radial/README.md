# Monthly sales around the year

Which months are strong every year, and how does the latest year compare with earlier ones?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 6x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover a segment (or arrow-key to it) for that month's sales in every year; the month is outlined and the rest dims. Click a segment or a year in the legend to select that year, Escape clears. The centre shows total sales.

## Notes
Built on MayaCharts 0.18.1 as one `radial` spec: `x: 'Month'` (Jan to Dec around the circle), `y: 'Sales'`, `series: 'Year'`. MayaCharts radial bars stack their series, so each month is one wedge with a segment per year, oldest inside and the latest outermost in ink (slate ramp by `colors` keyed by year); bar length reads the months that are strong across all years. The body fills Jan to Dec per year with nulls for missing months. This changes the chart's form: the old tile drew one closed line per year (a radar), so a year's shape could be compared with another's directly; here the latest year is compared through its outer segment, the tooltip and selection. Dropped: the per-year closed lines, dashed partial-year line, the 6-month minimum per year and the peak / low headline. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
