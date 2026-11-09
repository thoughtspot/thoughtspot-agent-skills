# Item type rank by year

Which item types climb or fall in the sales ranking from year to year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [date].yearly` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 12x6 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover a dot (or arrow-key to it) to light that item type's thread and dim the others; the tooltip lists that year's whole order with each rank and sales. Click a dot or thread to select it, Escape clears. Where two threads cross, the one that climbs passes over the one that falls.

## Notes
Built on MayaCharts 0.18.1 as one `weave` spec (a woven bump chart): `x: 'Year'`, `y: 'Sales'`, `series: 'Item type'`; MayaCharts ranks within each year itself. A weave holds at most 8 threads, so the body keeps the 8 item types with the most sales across the years shown (the subtitle says 'Top 8 of 15'); ranks are among those 8. Each thread takes its family hue through a `colors` map keyed by item type, built from the literal `FAM` and `HUE` maps in chart.js. Item types are named on the left in first-year order and at the right end with their latest sales. Dropped against the old chart: the other 7 item types, the Rank / Sales axis toggle, the partial-year dashes and shading on 2021 and 2026, the click-to-pin, and the headline naming the biggest climber and faller. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
