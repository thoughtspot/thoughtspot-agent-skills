# How to read price against volume

Which item types fall in each price and volume quadrant?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type]` |
| Library | Plain HTML and CSS, no external library |
| Tile | 4x6 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Click a quadrant to expand its members with units, price and sales; hovering dims the other quadrants

## Notes
Sidecar to what-price-volume, same search and same two reference lines. Higher means strictly above the line.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
