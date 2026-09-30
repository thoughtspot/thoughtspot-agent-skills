# Year to date, flip card

What is the year-to-date figure, and which months made and lost it?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Click or Enter flips the card between the year-to-date figure and the three best and three weakest months in the current view. Sales, Units, Price toggle. Hover a month for its value and change.

## Notes
The back ranks every month in the current filter, not only the current year.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
