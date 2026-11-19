# What if the rest of the year moves

If price per unit or units move from here, where does the year end?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | Inline SVG with native range sliders |
| Tile | 6x6 grid units (Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Drag or arrow-key the price and units sliders: the projected columns and the year-end totals glide to the new figure. Reset returns to the baseline. Hover a month for baseline, scenario and change.

## Notes
Baseline for the remaining months is the same months a year earlier. If the latest year is already complete in the rows, it projects the next year from it. The scenario is arithmetic on those months, not a forecast.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
