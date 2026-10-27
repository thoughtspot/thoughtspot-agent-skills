# Products that make 80% of sales

How few products make 80% of sales, overall and inside each item type?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[product] [item type] [sales] [quantity purchased]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a bar for the product, its rank, sales, units and the running share; the crosshair marks its point on the cumulative line. Play steps the scope through the six largest item types and ends on All (the default view); each scope re-ranks its own products with its own 80% marker. Click a bar (or Enter) to select it; Escape clears.

## Notes
Built on MayaCharts 0.18.1 as a `bar` with `y2` (the cumulative share on the right axis) and `frame` playback over a Scope field. The body ranks products by sales inside each scope (All plus the six largest item types), computes the running share, and builds one frame per scope with All last, since MayaCharts opens on the last frame; the value axes span every frame, so a single item type's bars are drawn against the same sales scale as All. Each scope's 80% product carries an `annotate` label ("80% at #18 of 28"); the subtitle gives the overall count. What changed against the ECharts chart: the item type chips are replaced by Play (MayaCharts has no frame picker, only Play/Pause), the Top 50 / All toggle and the click detail card (price against the item type average, rank in the item type) are dropped, and the 80% guide is a label on the bar rather than a dashed line on the cumulative axis, because `rules` only run on the left value axis. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 14 code lines (comments aside), the loader included; everything it computes is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
