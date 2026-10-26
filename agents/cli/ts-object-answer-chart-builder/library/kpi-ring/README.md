# Sales year to date, ring

How close is this year to the same months last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover the dial for the share of last year and its status. The arc sweeps in on first draw.

## Notes
Built on MayaCharts 0.18.1 as a `gauge` (module type, so the tile loads maya.global.js): the value is year to date as a share of the same months last year, `yDomain: [0, 1.3]` keeps the old 130% full scale, and `colorBy: { target: 1, warn: 0.95 }` puts the tick at 100% and tones the arc ahead, close or behind. Both money figures moved to the subtitle, since a gauge tooltip shows only its one value. Under a filter with no prior year the tile falls back to a `kpi` of the year-to-date figure with a plain subtitle. Dropped from the old chart: the full ring (a gauge is a half dial), the Sales, Units, Price toggle and the hover card with both years. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 9 code lines, the loader included. The share of last year is still derived from the year-to-date read (with no prior year it returns no rows); the column names are plain.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
