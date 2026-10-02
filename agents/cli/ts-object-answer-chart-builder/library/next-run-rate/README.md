# Year-end outlook

Where does the year end if the rest follows last year's months, or the last three months?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | Inline SVG (no CDN) |
| Tile | 6x6 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
scenario toggle (both, same months last year, 3-month average); hover a month for actual or projected values

## Notes
Projection, not a forecast. Projects the next year if December is already in the data. Months missing under a filter are skipped, and totals then cover the months present. Jan to May 2026 equals Jan to May 2025 in this data.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
