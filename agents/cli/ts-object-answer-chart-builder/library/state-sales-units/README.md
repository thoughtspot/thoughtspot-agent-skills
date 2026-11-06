# Sales against units by state

Is it price or volume that separates the states?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [state]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a dot for its state, sales, units and sales per unit (other dots dim); click dots to select several, Escape clears; drag to zoom, double-click or Escape resets. The dashed diagonal is the average price: states above it sell at more per unit.

## Notes
Built on MayaCharts 0.18.1 as a single scatter spec (units on x, sales on y, state as the point name). Both axes are log, since state volumes span two orders of magnitude and a linear axis piles half the states into the corner. The average-price diagonal through the origin is a `rules` slope of "mean" (total sales over total units). The body adds a per-row sales-per-unit field for the tooltip, labels the largest states by sales with `annotate` (labels that collide are dropped, so narrow tiles show California alone), and computes the subtitle: the range of sales per unit and the average. Columns are matched by name pattern, so casing changes in the search output do not break it. Below about 160 px tall the title and subtitle crowd the plot. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 9 code lines, the loader included; everything it computes is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
