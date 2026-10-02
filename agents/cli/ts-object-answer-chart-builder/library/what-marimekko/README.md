# Region by family Marimekko

How big is each region and how does its family mix differ?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | pure SVG, no library |
| Tile | 6x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a segment for sales and shares; click a column to widen it to the full tile and split families into item types; crumbs, Back, Escape.

## Notes
Family is an editorial grouping. Column width is the region's share of sales; stack height is share of the region.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
