# Sales by product family, by quarter

Does the product-family mix change over time?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [date].quarterly` |
| Library | d3@7.9.0 (cdn.jsdelivr.net, fallback unpkg; injected by chart.js) |
| Tile | 12x6 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js, https://unpkg.com/d3@7.9.0/dist/d3.min.js |

## Interactions
Toggle Stream / Stacked / 100% (the bands morph); hover a quarter for every series; click a family band or label to drill into its item types (tinted family hue, animated), Back, crumb or Escape returns; swatch beside a label isolates a series

## Notes
Families are an editorial grouping of item types (AZ.familyOf). Drill uses only the item type column already returned. Header recomputes per level. First quarter flagged partial.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
