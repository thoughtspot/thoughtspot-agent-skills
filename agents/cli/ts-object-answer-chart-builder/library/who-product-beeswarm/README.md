# Every product by price per unit

Where does each of the 345 products sit on price per unit, and how does one compare with its item type?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[product] [item type] [sales] [quantity purchased]` |
| Library | d3@7 force simulation and scales (cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js, fallback unpkg.com) |
| Tile | 6x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js, https://unpkg.com/d3@7/dist/d3.min.js |

## Interactions
dots settle from the price line into a force-simulation swarm; family chips filter (others dim); hover a dot; click a dot (Enter/Space on the 12 largest) to open its card (sales, units, price vs item type average, rank) with item type peers highlighted and the average marked; Back, crumbs and Escape close

## Notes
Log price axis because prices bunch between 15 and 60 dollars. Price is sales / units per product, so it is an average selling price. Family grouping is editorial.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
