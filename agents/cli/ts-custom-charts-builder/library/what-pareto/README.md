# Products that make 80% of sales

How few products make 80% of sales, overall and inside each item type?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[product] [item type] [sales] [quantity purchased]` |
| Library | echarts@5 via cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js (fallback unpkg.com/echarts@5/dist/echarts.min.js) |
| Tile | 6x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js, https://unpkg.com/echarts@5/dist/echarts.min.js |

## Interactions
Item type chips (top 6 plus All) re-rank and re-animate the Pareto; hover for rank, product, sales and cumulative share; click a bar to open a detail card (sales, units, price against the item type average, rank in the item type) with an animated highlight along the cumulative line; Top 50 / All toggle; Escape or Close dismisses

## Notes
SEARCH CHANGED from [sales] [product] to [product] [item type] [sales] [quantity purchased] (345 rows, same as who-product-table). Item type, units and price cannot come from the old search. Header recomputes per scope.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
