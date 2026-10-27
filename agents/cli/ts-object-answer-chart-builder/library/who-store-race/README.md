# Store race: cumulative sales by quarter

Which stores lead on cumulative sales, and how does the ranking change quarter by quarter?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x7 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Press Play to step through the quarters (every 900 ms); bars re-rank and the title follows the leader of the quarter shown. Hover a bar for the store, its cumulative sales and that quarter's sales. Click stores to select them; Escape clears. Arrow keys step between bars.

## Notes
Built on MayaCharts 0.18.1 as a horizontal `bar` with `frame: 'Quarter'` (playback), `sort: 'desc'`, value labels and `select: 'multi'`; the value axis holds still across quarters. The body computes cumulative sales per store at each quarter end and leaves the top 10 to MayaCharts (`limit: 10, other: false`, so each quarter keeps its own top 10), so stores enter and leave the race. Starts on the last quarter. Bars are slate (not ink) because MayaCharts 0.16.0, the version this chart was first built on, drew in-bar value labels in dark ink whatever the bar colour. Dropped against the old chart: the quarter scrub slider (MayaCharts has Play only), Play restarting from the first quarter, follow-a-store with a pinned row once it leaves the top 10, and the state under each store code. In this data Nevada (89145) leads at every quarter. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
