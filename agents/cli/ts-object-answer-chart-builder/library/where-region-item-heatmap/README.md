# Region by item type heatmap

Which item types drive each region's sales?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Click Sales or Share of region to switch the measure. Hover or arrow-key to a cell for the item type, region and value; the cell is outlined. Click cells to select several; Escape clears.

## Notes
Built on MayaCharts 0.18.1 as a `heatmap`: item types across (`sort: 'desc'`, largest total first), regions down (largest region on top, from data order), `y: [sales, Share]` as the measure toggle and `select: 'multi'`. The body adds Share (a cell's share of its region's sales) and orders the rows. Dropped against the old chart: the family colour swatch above each column, the row and column isolate on header click, and the computed headline about the biggest cell. MayaCharts keeps heatmap cells square, so on the 6x6 tile they are small and value labels only appear on wide tiles; item type labels along the bottom are thinned, so hover names the column. The accent is mid slate because 0.16.0, the version this chart was first built on, did not flip value labels to white on dark cells. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
