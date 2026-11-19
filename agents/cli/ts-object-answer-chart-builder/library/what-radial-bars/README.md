# Item types as radial bars

How do the 15 item types rank by sales, and what leads inside each?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [product]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 6x6 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover or arrow-key to a bar for its item type and sales; the other bars dim. Click a bar (or Enter) to select it, and click a family in the legend to select that family's item types; Escape clears.

## Notes
Built on MayaCharts 0.18.1 as a `radial` bar chart with `x` item type, `sort: 'desc'` and `series` family, so colours come from the literal `COL` map (`colors: COL`; Family is an editorial grouping derived from a literal `FAM` map in chart.js). The product rows of the search roll up into one bar per item type; the centre shows total sales. The headline (the top three item types and their share of sales) is computed in the body. Dropped against the D3 chart: the click that swapped a bar for that item type's top 12 products, because `radial` took no `path` or `drill` in 0.16.0, the version this chart was first built on (`path` without `x` failed with `missing-field`). The tooltip lists every family with a value only on the hovered bar's family. On narrow tiles long item type names shorten with an ellipsis. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
