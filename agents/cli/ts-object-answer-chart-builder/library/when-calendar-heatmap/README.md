# Sales, units and price by month

Which months and years were high or low, and how did price per unit move?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | Plain HTML (no library, no CDN) |
| Tile | 6x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Toggle Sales / Units / Price per unit (cells re-colour with a tween); hover a cell for value and change on the same month a year earlier; click a cell or month name to highlight that calendar month; click a year label to morph the grid into that year's 12 monthly columns with the previous year as a slate outline (crumbs, Back, Escape)

## Notes
Slate ramp scaled to the min and max of the selected measure. Blank dashed cells are months with no data. Price per unit is sales divided by units per month. Year drill compares like months for part years (2021, 2026).

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
