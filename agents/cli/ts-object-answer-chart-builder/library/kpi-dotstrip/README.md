# Latest month, dot strip

Where does the latest month rank among all months in view?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 3x4 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a dot for its month and sales. Click a dot to select it and dim the rest (Escape clears). Click a legend key to select that whole group (below, above or the latest month). The chart is keyboard navigable.

## Notes
Built on MayaCharts 0.18.1 as a `scatter` of every month in the filter, oldest to newest, height the sales. The body ranks the latest month and groups each dot as the latest month (ink), above it (dark slate) or below it (light slate) through `series` and a `colors` map; a dashed `rules` line runs at the latest level and the title names the rank (for example 36th of 64). `theme.series1` is left out because it would override the colours map. Dropped from the old chart: the Sales, Units, Price toggle (the latest-level rule and the rank are in sales, so a `y` array toggle would not move them), the left-to-right fade-in and the pin-against-latest comparison (select now dims the other months instead). Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 13 code lines, the loader included. It reads the search for the months, finds the latest one, tags each dot with a group and label and sets the subtitle and the Latest rule; the colours are a literal map in the spec and the column names are plain.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
