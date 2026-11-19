# Share of sales against price per unit

Which item types carry the sales, and what do they earn per unit? Year-to-date change is flat for every type, so the default vertical measure is price per unit.

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 8x7 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a bubble for the item type, its family, share of sales, sales per unit and sales. The measure toggle above the plot switches the vertical axis between sales per unit and change on the same quarters last year. Click bubbles to select several (the others dim; Escape clears); click a family in the legend to hide or show it. Drag to zoom; double-click or Escape resets. Arrow keys step through the bubbles.

## Notes
Built on MayaCharts 0.18.1: a `scatter` with `size` (sales), `series` (family, coloured by the literal `COL` map in chart.js), a `y` array as the measure toggle, `select: 'multi'`, `zoom` and an `annotate` label on the largest type. The body still derives the year-to-date quarters, share, price and change per item type from the rows. The title and subtitle name the largest type, the overall price per unit and the spread of the change. Dropped against the old chart: the dashed all-types average line (a rule would also show on the change measure), the quadrant bands, and the families-are-editorial caption, which is now part of the subtitle. chart.css sets no series tokens, so the `colors` map alone colours the families. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 20 code lines, the loader included. Share, price, change on last year and the subtitle are still derived per item type from the year-to-date quarters; Family is a literal `FAM` map in chart.js, the column names are plain and the format presets are inlined.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
