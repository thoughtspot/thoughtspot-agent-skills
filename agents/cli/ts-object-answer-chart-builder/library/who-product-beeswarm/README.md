# Every product by price per unit

Where does each of the 345 products sit on price per unit, and how does one compare with its item type?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[product] [item type] [sales] [quantity purchased]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a dot for the product, its item type and its price per unit. Click dots to select several (the rest dim); Escape clears. Click a family in the key to hide or show its lane. Arrow keys step through the dots.

## Notes
Built on MayaCharts 0.18.1 as a `beeswarm` with one lane per family (`x` and `series` both Family, coloured by a literal `colors` map in the spec), price per unit (sales over units, so an average selling price) on a linear axis, and `select: 'multi'`. The body computes the price, passes the row through so `tooltip: { fields: [item type] }` shows the item type under the product name and orders the lanes by the house family order. Dropped against the old chart: the log price axis (beeswarm refuses `yScale`), dot area by sales (no `size` on beeswarm), the settle-in animation from a price line, the product card with item type peers highlighted and the item type average marked, and Back/crumbs. Dense ties (many products at the same price) clamp to their lane and overlap a little. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
