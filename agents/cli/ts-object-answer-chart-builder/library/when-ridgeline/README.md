# Sales ridgeline by year

How does the shape of the year compare across years, and what does one year look like month by month?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a month for every year's sales in that month, with a vertical guide and a dot on each ridge. Click a year in the legend to hide or show its ridge. Arrow keys step through months and years.

## Notes
Built on MayaCharts 0.18.1 as one `ridgeline` spec: `x: 'Month'` (Jan to Dec), `y: 'Sales'`, `series: 'Year'`, one ridge per year on a shared scale from zero. The body fills Jan to Dec per year with nulls for missing months, so part years (2021 from June, the latest year to its last month) draw only where they have data. The latest year is ink and older years step back through the slate ramp (`colors` keyed by year); each ridge labels its peak. Dropped against the old chart: the click that lifts a year and opens its monthly columns with the previous year as a dashed outline (crumbs, Back), and the part-year range labels. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
