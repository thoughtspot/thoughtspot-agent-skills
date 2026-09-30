# Sales against units by state

Is it price or volume that separates the states?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [state]` |
| Library | Muze point layer, with an SVG overlay |
| Tile | 6x6 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a dot for sales, units, sales per unit and its gap to average; click a dot to pin it (others dim); click again or the background to clear

## Notes
Dots are matched to states by rank on units. Muze point groups render at half opacity; chart.css resets it.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
