# Premium or volume, by item type

Which item types earn more than their share of units (premium) and which sell on volume?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [product]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 8x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows MayaCharts' empty state, worded to name the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` (loaded by chart.js) |

## Interactions
Hover or focus a bar for its tooltip: the gap in points with Premium or Volume, plus the share of sales and the share of units behind it; the other bars dim. Click a bar, or focus it and press Enter, to drill into that item type's products; the breadcrumb, Back, Escape or a click on empty space goes back up. Arrow keys move between bars. The subtitle names the leader of the level shown and follows the drill. All of this is built into MayaCharts.

## Notes
Built on MayaCharts 0.18.1: a horizontal `bar` with `path: [Item Type, Product]`, `drill: true`, `sort: 'desc'`, `labels: true` and `colorBy: 'sign'` (green premium, red volume). The body computes three fields per row: Sales and Units, each row's share of the whole search, and Gap, their difference times 100. All three add up from product to item type, so MayaCharts' default sum is right at both levels; `tooltip: {fields: [Sales, Units]}` brings back the two shares the original tooltip showed (checked at the root, Dresses 14.8% and 8.3% for +6.57 pts, and inside the Dresses drill, Sport Dress 3.2% and 1.6% for +1.64 pts). The subtitle uses the `{max.x}` and `{max.y}` data tokens. Render-complete fires on `maya-settled`.

Two things from the original still cannot be expressed. The price index toggle needs `aggregate: {ratio: [sales, units]}` (price per unit has to be summed then divided at every level), and 0.16.0, the version this chart was first built on, refused a ratio with a `y` array (`option-unsupported`), so there is no toggle between gap and price; a price row in the tooltip is not possible either, because tooltip fields are combined by the chart's aggregate, which is sum here. The gap re-measured inside an item type (a product's share of the item type's sales minus its share of the item type's units) is not a ratio of two sums: its denominators change with the drill level, so `{ratio}` cannot express it; inside a drill the products show their contribution to the item type's gap. MayaCharts hides value labels that do not fit (narrow tiles, tiny bars); the tooltip still gives the value. Preview-verified on synthetic data; not yet re-checked on a cluster.

chart.js is 12 code lines (comments aside), the loader included; everything it computes is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
