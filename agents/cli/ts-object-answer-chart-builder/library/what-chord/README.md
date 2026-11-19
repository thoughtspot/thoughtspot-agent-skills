# Region to family chord

Which regions buy which product families?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 6x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover or arrow-key to a region or family arc for its sales; the ribbons it touches stay lit and the rest dim. Hover a ribbon for that region-to-family flow. Click a region arc (or focus it and press Enter) to drill into it: the region stays on the left and its flows fan out to the families. The breadcrumb reads Back > region, and Back, Escape or a click on empty space goes back up.

## Notes
Built on MayaCharts 0.18.1 as a single `chord` spec over the path region > family with `drill: true`. Family is an editorial grouping derived from Item type through a literal `FAM` map in chart.js. Colours come from `colors: COL`, a literal map keyed by node name: family arcs and their ribbons take the family hues, and regions are left out of the map so their arcs stay neutral grey. The title names the largest region-to-family flow and its share of sales, computed in the body. What changed against the D3 chart: the drill now opens a region, not a family; the old click on a family arc that split it into its item types is gone, because a chord path takes exactly two levels (`invalid-option`: "spec.path needs exactly two levels for a chord"), so family arcs do not drill. The centre total and the slate ramp on the region arcs are dropped. On narrow tiles (under about 300 px) the labels of the two smallest arcs can overlap, and some thin arcs go unlabelled; the tooltip names them. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 10 code lines, the loader included; it derives the Family column and drops rows without sales, data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
