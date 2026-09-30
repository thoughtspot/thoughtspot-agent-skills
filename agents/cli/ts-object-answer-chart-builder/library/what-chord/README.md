# Region to family chord

Which regions buy which product families?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | d3@7 (d3-hierarchy, d3-shape, d3-chord) from https://cdn.jsdelivr.net/npm/d3@7 (fallback https://unpkg.com/d3@7) |
| Tile | 6x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/d3@7, https://unpkg.com/d3@7 |

## Interactions
Hover a ribbon or arc to highlight it and dim the rest; click a family arc to open its item types (animated morph); crumbs, Back, Escape.

## Notes
Family is an editorial grouping. Region arcs slate, family arcs family hues; item-type view uses tints of the family hue.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
