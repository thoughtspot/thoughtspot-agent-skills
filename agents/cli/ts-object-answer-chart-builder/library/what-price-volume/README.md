# Price against volume by item type

Which item types combine high price with high volume?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 8x6 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a bubble for its item type, family, units, price and sales, with crosshair values on both axes. Click a bubble (or Enter) to select it; click a family in the legend to select (isolate) that family; Escape clears. Drag across the plot to zoom; double-click or Escape resets.

## Notes
Built on MayaCharts 0.18.1 as a `scatter` with x units, y price, `size` sales (bubble area), `series` family and `name` item type. The body adds price (sales over units) and family to each row, and works out the units-weighted average price and the median units (a scatter takes no ratio aggregate, and `rules: ["mean"]` is not units-weighted); these draw as two `rules` (`{ y }` and `{ x }`). Family is an editorial grouping derived from a literal `FAM` map in chart.js; colours come from the literal `COL` map (`colors: COL`). The four largest bubbles are named with `annotate` (`{ x, text }`; one can drop when labels collide); every other bubble is named in its tooltip. Changed against the hand-built SVG: bubble labels are on the four largest only, and a size legend now shows above the plot. On tiles under about 300 px the rule labels overlap the annotations. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
