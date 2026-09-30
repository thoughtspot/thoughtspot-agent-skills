# Sales treemap with drill-down

Where do sales sit across families, item types and products, and how concentrated is each?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [product]` |
| Library | d3@7 (d3-hierarchy, d3-shape, d3-chord) from https://cdn.jsdelivr.net/npm/d3@7 (fallback https://unpkg.com/d3@7) |
| Tile | 8x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/d3@7, https://unpkg.com/d3@7 |

## Interactions
Click a rectangle to zoom in (450 ms layout tween); crumbs, Back and Escape go up; Enter or Space opens a focused rectangle; hover for sales and share of parent.

## Notes
Family is an editorial grouping. Top 8 products per item type plus Other. Labels appear only when they fit.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
