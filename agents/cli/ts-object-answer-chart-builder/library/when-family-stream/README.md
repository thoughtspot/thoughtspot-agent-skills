# Sales by product family, by quarter

Does the product-family mix change over time?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x6 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Toggle Sales / Share of quarter: Sales stacks the families in dollars, Share stacks them to 100% of each quarter. Hover a quarter for every family's value; click a family in the legend (narrow tiles) to hide or show it, wide tiles name each family at its right end. Drag across the plot to zoom into a span of quarters; double-click or Escape resets.

## Notes
Built on MayaCharts 0.18.1 as one stacked `area` spec on a time axis, `series: 'Family'` coloured by a literal `colors` map in the spec, with `stack: [true, 'percent']` as the Layout toggle (sales or share of the quarter) and `zoom`. The body maps each item type to its family through a literal `FAM` map and leaves a part quarter at either end out; MayaCharts sums the families and the percent stack gives each family's share. Dropped against the old chart: the centred streamgraph layout (wiggle offset), the drill from a family band into its item types (MayaCharts drills `path` on x only, not on series), the swatch-isolate gesture (the legend hides instead), and the flag on the partial first quarter, which the subtitle now mentions. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
