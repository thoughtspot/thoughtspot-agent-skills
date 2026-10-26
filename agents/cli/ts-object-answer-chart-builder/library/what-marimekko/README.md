# Region by family Marimekko

How big is each region and how does its family mix differ?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 6x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover or arrow-key to a block for its region, with every family's sales and share of that region in the tooltip; the other blocks dim. Click a block (or Enter) to select it, and click a family in the legend to select that family across every region; Escape clears.

## Notes
Built on MayaCharts 0.18.1 as a `marimekko` with `x` region, `series` family and `select: true`. Column width is the region's share of sales and each block's height is the family's share of that region, labelled on the block. Family is an editorial grouping derived from Item type through a literal `FAM` map in chart.js; colours come from the literal `COL` map (`colors: COL`), so region is never a hue. The body sorts rows by region total (widest column first) and by family in house order so the stacks line up, and computes the headline (largest region's share, and its largest family's share inside it). Dropped against the old SVG chart: the click that widened a region to the full tile and split its families into item types. MayaCharts' marimekko can drill on `path`, but the series stays fixed, so drilling into a region gives one 100% column per item type rather than the region's families split into item types; the drill was left out. The narrowest region columns lose their labels on small tiles; the tooltip still names them. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 14 code lines (comments aside), the loader included; everything it computes is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
