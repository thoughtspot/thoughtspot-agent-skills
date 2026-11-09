# Year-end outlook

Where does the year end if the rest follows last year's months, or the last three months?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a month for the actual value or both projected values. Click a legend key to hide or show a scenario, which replaces the old scenario toggle. Wider tiles also name each line at its right end. Drag to zoom into a span of months; double-click or Escape resets. Arrow keys step through months and lines.

## Notes
Built on MayaCharts 0.18.1: a `line` on a time axis with three series (actual in ink, and the two projections dashed in slate through `dash`), plus a `rules` x line at the last actual month labelled Projected. The body still builds the projections: the same months a year earlier, and the last three months' average carried on, both starting from the last actual month. If December is already in the data, it projects the next year. The title gives both year-end totals and the subtitle compares them with last year. Dropped against the old chart: the two total cards (now in the title), the shaded projection band and the 'apart by' caption. A projection, not a forecast. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 20 code lines, the loader included: it builds the projection rows and the subtitle by hand (MayaCharts has no native projection); the series colours are a literal map in the spec.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
