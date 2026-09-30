# Where the money flows: region to family to item type

Which regions feed which product families and item types?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | echarts@5 via cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js (fallback unpkg.com/echarts@5/dist/echarts.min.js) |
| Tile | 12x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js, https://unpkg.com/echarts@5/dist/echarts.min.js |

## Interactions
Hover a node or flow to highlight adjacent flows; click a node to isolate its flows and dim the rest; click background or Show all to clear

## Notes
Family is an editorial grouping. Region nodes use the slate ramp. Thin nodes are unlabelled and named in the tooltip.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
