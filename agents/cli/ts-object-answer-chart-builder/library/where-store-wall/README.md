# Quarterly sales by store

Which stores follow the company shape, and which have their own?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Click Same scale or Own scale: Same scale colours each quarter by its sales, Own scale by its share of that store's total, so the shape of each store compares regardless of size. Hover or arrow-key to a cell for the store, quarter and value. Click cells to select several; Escape clears.

## Notes
Built on MayaCharts as a `heatmap`: one row per store (largest on top, through data order), one column per quarter, `y: [Sales, Own]` as the scale toggle and `select: 'multi'`. The body formats quarter labels and adds Own (each quarter's share of the store's own total). This replaces the wall of mini area charts: MayaCharts has no small-multiples layout, and the `ridgeline` that was tried colours 30 stores with eight cycling hues, adds a 30-entry legend and cannot scale rows separately. Dropped: the mini area shapes, the sort toggle (Sales / Change vs last year / Name), the click-to-expand full quarterly chart against last year, and the part-quarter caption. Heatmap cells stay square, so with 30 stores and 22 quarters they are small and row labels are thinned. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
