# Products by sales

Which products carry the sales, and how does one compare with its item type?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[product] [item type] [sales] [quantity purchased]` |
| Library | Plain HTML table (no CDN) |
| Tile | 12x7 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Click a header to sort (rows glide); search by name; family chips filter; Show 25 more; hover row tooltip; click a row to open a detail row with sales, units and price against the item type average, its rank in the item type and animated bars (one row open at a time, click again or Escape closes)

## Notes
Rank and share are computed against the whole search result. Item type averages and ranks are computed from the same 345 rows. Bar column hidden below 560px wide. Family is an editorial grouping.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
