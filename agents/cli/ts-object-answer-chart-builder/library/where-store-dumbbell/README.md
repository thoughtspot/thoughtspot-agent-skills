# Store sales, this year vs last

Which stores are ahead or behind the same quarters last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover or arrow-key to a store for last year and this year; the other stores dim. Click stores to select several; Escape clears. Click a year in the legend to hide it.

## Notes
Built on MayaCharts 0.18.1 as a horizontal `dumbbell` (store by year, last year light slate, this year ink) with `select: 'multi'`. The body keeps the window of the old chart (Q1 to the latest quarter in the latest year, against the same quarters a year earlier), drops stores without sales in both, orders stores by change (biggest gain on top, through data order, since `sort` only orders by total), sets `yDomain` to the range of the totals because the changes are a few percent, and writes the title (how many stores are up). Dropped against the old chart: the Change / Size / Name sort toggle, the change percent at the row end, and the click-to-expand quarterly line per store. A drill into quarters (`path: [Store, Quarter]`) works, but it cannot share the fitted axis, which is what makes the gaps visible, so it was left out. On a 6x6 tile every other store name is shown; hover names the rest. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
