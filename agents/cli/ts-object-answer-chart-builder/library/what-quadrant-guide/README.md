# How to read price against volume

Which item types fall in each price and volume quadrant?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 4x6 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a quadrant bar for its sales by family and units; the other bars dim. Click a quadrant (or Enter) to drill into its item types, each with its sales and units; the breadcrumb, Back, Escape or a click on empty space goes back up. Click a family in the legend to hide or show it.

## Notes
Built on MayaCharts 0.18.1 as a horizontal stacked `bar` with `path: [Quadrant, Item type]`, `drill: true`, `series` family and `stack: true`. The body uses the same two lines as what-price-volume (the units-weighted average price and the median units; higher means strictly above) to put each item type in a quadrant: Stars (above both), Premium (price only), Volume (units only) and Long tail (neither), names short enough to stay readable on a 4-wide tile; the subtitle defines them with the live line values. Family is an editorial grouping derived from a literal `FAM` map in chart.js; colours come from the literal `COL` map (`colors: COL`). The headline lists the Stars and their share of sales. Changed against the HTML card list: the quadrants are now bars sized by sales instead of cards, and the per-item price is gone from the expanded view, because tooltip fields are combined by sum and a price needs a ratio of sums. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
