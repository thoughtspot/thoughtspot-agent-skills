# Monthly sales against last year

How have sales moved month to month, and where did the level change?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | Muze (line), with an HTML header and legend |
| Tile | 8x6 grid units (Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover for month, sales, same month last year and the change. Click the key to hide or show the last-year line. The two largest month-on-month steps are marked from the data.

## Notes
Colour is deliberately monochrome: hues are reserved for product families. Muze ignores the colour range on line marks and can leave stroke width at 0, so the chart sets both after render. Muze's own tooltip and crosshair are hidden because they total this year and last year and snap half a step off the pointer. The year-to-date sentence compares the same months of the latest year and the year before, so it stays correct under a date filter.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
