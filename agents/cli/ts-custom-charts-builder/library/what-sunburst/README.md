# Sales by family, item type and product

How do sales split from family to item type to product?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [product]` |
| Library | Plotly sunburst (plotly.js-dist-min 2.35.2 from a CDN) |
| Tile | 6x7 grid units (What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js, https://cdn.plot.ly/plotly-2.35.2.min.js |

## Interactions
Click a wedge to zoom in (animated); click the centre or a crumb to zoom back out. Hover a wedge for its sales and shares; the line under the chart follows the pointer. Two rings show at a time, and products appear as you zoom into an item type.

## Notes
Rebuilt on Plotly because its drill is an animated zoom; the earlier ECharts version had animation switched off and re-drew on every drill. Family is an editorial grouping, not a model column. Top six products per item type, the rest as Other.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
