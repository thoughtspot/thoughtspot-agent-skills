# Best month

What is the strongest month on record in this view, and how far above normal?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover, or use the arrow keys, for each month's sales. Drag across the plot to zoom into a span of months; double-click or Escape resets.

## Notes
Built on MayaCharts 0.18.1 as a `line` over every month in the view rather than a `kpi` tile, because a kpi headline is always the latest value and this tile's headline is the record. The title names the best month and its sales through the `{max.x}` and `{max.y}` data tokens, the subtitle gives the average month through the `{mean}` token, an `Average` rule marks the normal month, and `annotate` labels the peak Best. There is no hand-fitted `yDomain`; MayaCharts sets the value axis. Dropped against the old tile: the big-number layout and the YTD and All toggle (the view is always every month in the filter). Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 4 code lines, the loader included, and derives nothing: it hands `viz` straight to `maya.host.thoughtspot`; the Average rule is `mean`, the Best label an `annotate` on `max`, and the Month format is the 'month' preset.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
