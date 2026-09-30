# Region by item type heatmap

Which item types drive each region's sales?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | none (HTML grid) |
| Tile | 6x6 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales / Share of region toggle; hover a cell for sales, shares and rank; click a row or column header to isolate it

## Notes
Family swatches use the editorial family grouping (not a model column). Column labels are rotated; values print inside cells only when they fit (about 34px per column).

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
