# Quarter pairs, drill to months

How does each quarter of this year compare with the same quarter last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales, Units, Price toggle. Columns grow in. Hover a pair. Click a pair or use arrow keys and Enter to see its months; Escape or Back closes.

## Notes
Only quarters with data in the latest year are drawn; a part quarter is marked with an asterisk and compared on the same months only.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
