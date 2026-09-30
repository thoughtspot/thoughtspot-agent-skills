# Sales year to date, ring

How close is this year to the same months last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales, Units, Price toggle with the arc tweening from the old share. Hover the ring for both figures. The centre number counts up.

## Notes
Arc is year to date as a share of the same months last year; full circle is 130% and a tick marks 100%. Under a filter with no prior year it shows the year-to-date value and a plain message.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
