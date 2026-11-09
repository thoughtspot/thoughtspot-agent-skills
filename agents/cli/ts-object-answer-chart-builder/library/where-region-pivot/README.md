# Region by family pivot

How does each region's sales break down by product family, and where does price per unit differ?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [region] [state] [item type]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a cell for its region (or state), family and price per unit. Click a cell, or focus it and press Enter, to drill into that region's states; the breadcrumb, Back, Escape or a click on empty space goes back up.

## Notes
Built on MayaCharts 0.18.1 as a `heatmap` with `path: [Region, State]` and `drill: true` on the rows, product families across (in the Liveboard's fixed family order) and `y: 'Price'` with `aggregate: {ratio: [Sales, Units]}`, so price per unit is sum(sales) / sum(units) in every cell at both levels. The body derives Family from item type (a literal `FAM` map in chart.js) and computes the subtitle (lowest against highest regional price per unit). Much was dropped from the old pivot table: the Sales / Units / Price per unit toggle (0.16.0, the version this chart was first built on, refused a ratio aggregate with a `y` array), sales and units in the tooltip (heatmap takes no `tooltip.fields`), the family to item type column expand, the Total row and column, share bars and Expand all. The tile now answers where price per unit differs; the sales breakdown by family is no longer on it. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
