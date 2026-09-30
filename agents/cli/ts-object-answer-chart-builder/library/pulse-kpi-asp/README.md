# Average selling price

Is the price per unit rising or sliding?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | HTML and inline SVG (no chart library) |
| Tile | 3x4 grid units (Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
YTD and All toggle. Hover the sparkline for the month, its value and the change on the same month a year earlier.

## Notes
One source file serves four KPI tiles; the tile picks its metric with data-kpi in chart.html (asp). The comparison is the same months of the latest year against the year before, so it holds under a date filter. Search returns sales and units so any of the four can share it.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
