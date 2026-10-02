# Monthly columns, drill to a month

How do the last 24 months compare, and how does one month compare with a year ago?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales, Units, Price toggle. Columns rise in staggered. Hover a column for the month. Click a column or use arrow keys and Enter to compare that month with the same month a year earlier; Escape or Back closes.

## Notes
Latest calendar year in ink, earlier months in slate. Bars start at zero.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
