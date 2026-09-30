# Item types as radial bars

How do the 15 item types rank by sales, and what leads inside each?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [product]` |
| Library | d3@7 (d3-hierarchy, d3-shape, d3-chord) from https://cdn.jsdelivr.net/npm/d3@7 (fallback https://unpkg.com/d3@7) |
| Tile | 6x6 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/d3@7, https://unpkg.com/d3@7 |

## Interactions
Hover a bar; click a bar to swap to that item type's top 12 products (bars retract then grow); crumbs, Back, Escape.

## Notes
Bar length is proportional to sales (linear radius). Family is an editorial grouping. Top 12 products shown per item type.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
