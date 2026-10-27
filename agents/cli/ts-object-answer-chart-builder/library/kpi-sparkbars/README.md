# Monthly columns against a year earlier

How do the last 24 months compare, and how does one month compare with a year ago?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover, or use the arrow keys, for a month's sales and the same month a year earlier. Click a column (or Enter) to select it; Escape clears. Click the legend key to hide the year-earlier ghosts.

## Notes
Built on MayaCharts 0.18.1 as a `bar` over the last 24 months with `was`: each column carries a dashed ghost at the same month a year earlier, so the old click-to-compare view is now on every column at once. The title is the year-to-date headline against the same months last year, computed in the body. The year-earlier value shows in the tooltip natively, and the value axis spans the ghosts. Dropped against the old tile: the Sales, Units and Price toggle (`was` cannot be combined with a `y` array), the ink-for-this-year and slate-for-earlier colouring (`was` cannot be combined with `stack`, which a year series would need), and the drill-in comparison panel. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 7 code lines, the loader included. `was` ghosts widen the value axis and appear in the tooltip on their own, so there is no `tooltip.fields` or hand-fitted `yDomain`. The last 24 months and the year-earlier twin are still derived, because `was: { by }` needs a period column the search does not return.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
