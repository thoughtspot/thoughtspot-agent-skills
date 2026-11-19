# YTD sales by region

Which regions and states moved year-to-date sales against the same quarters last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [state] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 4x6 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a bar for the region's change in sales, or a YTD total. Click bars to select several; Escape clears.

## Notes
Built on MayaCharts 0.18.1 as a `waterfall`: last year's YTD total as the first bar, one step per region's change (largest gain first), this year's YTD in `totals`, and `select: 'multi'`. The body computes the window (Q1 to the latest quarter, same quarters a year earlier), the steps and the title (the overall change). `yDomain` starts near the lowest running total because the changes are under 1% of the totals; MayaCharts draws an axis break on the total bars and the subtitle says the axis does not start at zero. Increases are green and decreases red (theme series tokens), totals grey. Dropped against the old chart: the click-to-open split of a region into its states (waterfall takes no `path` or `drill`), the isolate-and-Show-all, and the per-row percent changes. On a 4x6 tile the region names under the steps are thinned; hover names them. With no rows the empty message names the search. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 14 code lines (comments aside), the loader included; everything it computes is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
