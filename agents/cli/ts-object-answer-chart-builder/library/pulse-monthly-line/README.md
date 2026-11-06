# Monthly sales against last year

How have sales moved month to month, and where did the level change?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 8x6 grid units (Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover for the crosshair and a tooltip with the month, sales and the same month last year. Click a legend key (shown on narrow tiles; wider tiles name each line at its right end) to hide or show a line. Drag across the plot to zoom into a span of months; double-click or Escape resets. The chart is keyboard navigable: arrow keys step through months and between the two lines.

## Notes
Built on MayaCharts 0.18.1. The headline is back: the title compares the same months of the latest year with the year before (so it stays right under a date filter), and the subtitle names the latest month through the `{last.x}` data token. Last year runs as a second, dashed slate line (`dash`) under the ink sales line; the body still pairs each month with the same month a year earlier to build it. The peak month is labelled with `annotate` and the latest month carries its value in the end label. The old step-up and step-down markers stay dropped. Colour is deliberately monochrome: hues are reserved for product families. Below about 160 px tall the title and subtitle wrap and crowd the plot, since MayaCharts keeps them in its compact frame. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 8 code lines, the loader included: it still pairs each month with the same month a year earlier (drawn through `was`); the colours are a literal map in the spec and the Month format is the 'month' preset.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
