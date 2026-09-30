# Latest month, bullet

Where does the latest month sit against the best and the average month?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales, Units, Price toggle. Hover the track or a legend row for each marker; the others dim. The bar grows in.

## Notes
Bar is the latest month, tall tick the best month, thin tick the average month, bands run 0 to average and average to best. Year-to-date change is shown in the header line.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
