# Latest month, dot strip

Where does the latest month rank among all months in view?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales, Units, Price toggle. Dots fade in left to right. Hover a dot for the month and its rank. Click a dot to pin it against the latest month; click again to unpin.

## Notes
One dot per month in the filter, oldest to newest, height is the value; a dashed line at the latest level shows how many months sit above it.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
