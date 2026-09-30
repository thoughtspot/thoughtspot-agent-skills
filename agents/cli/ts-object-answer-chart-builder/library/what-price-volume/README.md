# Price against volume by item type

Which item types combine high price with high volume?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type]` |
| Library | Hand-built inline SVG, no external library |
| Tile | 8x6 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a bubble for details; click a bubble or a family in the key to isolate that family; click background to clear

## Notes
Bubble area is sales; x is units; y is sales/units. Reference lines: units-weighted average price and median units. Family is an editorial grouping.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
