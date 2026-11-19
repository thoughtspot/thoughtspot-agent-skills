# Sales bubble map by state

Which states carry the sales, and how many stores sit behind them?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [state] [region]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 7x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Click Sales or Stores to switch what the fill shows (summed sales, or the number of stores in the state). Hover or arrow-key to a state for its value; click states to select several, Escape clears.

## Notes
Built on MayaCharts 0.18.1 as a `hexmap` with `y: [sales, Stores]` as the measure toggle and `select: 'multi'`. The body adds Stores = 1 per store row, so the default sum is the store count per state, and computes the subtitle (top state, its sales and store count, and how many states have more than one store). Dropped against the old chart: the Albers map with sized bubbles (MayaCharts has no geographic projection or bubble map) and the click-to-zoom into a state with one bubble per store; stores are no longer shown individually, only counted. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
