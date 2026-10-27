# Products by sales

Which products carry the sales, and how does one compare with its item type?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[product] [item type] [sales] [quantity purchased]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x7 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Click a column header (or Enter / Space on it) to sort by that column; click again to flip the order. Hover a row's bar for a tooltip with its sales, units, average price and price against its item type. Click a row to select it; Escape clears. Arrow keys move between rows.

## Notes
Built on MayaCharts 0.18.1 as a `table` with `y: ['Sales', 'Units', 'Price', 'Vs type']`, sorted by sales and `select: true`. The body computes price per unit, and price against the item type average (the item type's sales over its units), and puts the item type into the row name. Each column draws an in-cell bar; on the signed Price vs type column the bar shows the size of the gap, not its sign, so read the number. The table draws the rows that fit the tile (about 13 at the nominal size) and has no scroll or paging. The headline gives the top product's share of all sales and the subtitle the top 25's share. Narrow tiles squeeze the columns until cell text nearly touches (about 280 px), so formats are compact. Dropped against the old chart: the Share column, search by name, family chips, Show 25 more, the family colour swatch, and the detail row with rank in item type and animated bars. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
