# Sales pace by year

Is this year ahead of or behind the same point in earlier years?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 8x6 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a month for every year's cumulative sales. Click a point on a line to select it (Escape clears). On narrow tiles the legend names the years, and clicking a key hides or shows a year; wider tiles name each line at its right end with its total. Arrow keys step through months and years.

## Notes
Built on MayaCharts 0.18.1: a `line` with months as categories and one series per year. The latest year is in ink and earlier years run from light to dark slate through `colors`. The body still sums sales into cumulative totals and drops years with fewer than 3 months. Months before a partial year's first month go in as nulls, so months run Jan to Dec and years stay in order. The title compares the latest year with the year before through the same month, and the subtitle names any partial years. Dropped against the old chart: clicking a year to open its monthly columns against the previous year (MayaCharts has no per-series drill to another view), the thicker latest line and the draw-on animation (MayaCharts runs its own entrance). Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 12 code lines (comments aside), the loader included; everything it computes is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
