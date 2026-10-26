# Stores across five measures

Which stores are alike across sales, units, price, year-to-date change and size, and which stand apart?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [store] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a line for the store and its five values. Click lines to select several (the rest fade); Escape clears. Arrow keys step between stores. Store names label the line ends where they fit.

## Notes
Built on MayaCharts 0.18.1 as `parallel` with `y: ['Sales', 'Units', 'Price', 'YTD', 'Share']`, `select: 'multi'` and slate lines. The body computes per store total sales and units over every quarter, price per unit, year-to-date change (the latest year's quarters up to the latest quarter against the same quarters a year earlier; the axis is dropped when there are none) and total sales as a share of the largest store (a rescaling of total sales, so those two axes are perfectly correlated). Dropped against the old chart: brushing an axis to filter, the staggered draw-in, and the pinned side panel with values and ranks. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
