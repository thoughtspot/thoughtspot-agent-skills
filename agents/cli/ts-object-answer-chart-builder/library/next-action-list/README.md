# Moves the numbers support

What should we do next, and what number backs each move? Each move and its evidence is generated from the rows.

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].quarterly` |
| Library | HTML and CSS (no CDN) |
| Tile | 4x7 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
click a move to open or close its evidence; hover an evidence bar for the numbers

## Notes
Four moves: highest sales per unit, flat year-to-date trend, peak quarter of the latest full year, top-three concentration. Moves that need data the filter removes (no year-earlier quarters, no full year, under 4 item types) are dropped, never invented. Concentration is by item type; product-level concentration would need a product search.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
