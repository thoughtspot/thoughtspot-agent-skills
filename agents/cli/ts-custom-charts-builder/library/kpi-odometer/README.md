# Year to date, odometer

What is the year-to-date figure, and which way is it moving?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Click or Enter cycles Sales, Units, Price per unit and the digit columns roll to the new value. Hover a digit for both years.

## Notes
Digits roll from the previous value, right aligned. The chip is year to date against the same months a year earlier.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
