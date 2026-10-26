# Stores against last year

Which stores are furthest below last year on the same quarters, against a threshold you set?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Hover a store for its change on last year (with an above or below the line tone), sales this year and sales last year. Click stores to select them (Escape clears). Arrow keys step through stores. The threshold is the `THRESHOLD` constant at the top of the body (default -5%), not a slider.

## Notes
Built on MayaCharts 0.18.1: a horizontal `bar` sorted lowest first, with `colorBy: { target: LOW }` (stores below it turn red, the rest are slate), a `rules` line at the threshold and `aggregate: { ratio }`. The ratio keeps the change right in the Other bucket that MayaCharts makes on small tiles. The body still sums the year-to-date quarters per store against the same quarters a year earlier. The title counts the flagged stores, or names the lowest store when none is flagged. Dropped against the old chart: the threshold slider, which MayaCharts has no input control for, so the threshold is now a constant in the code; the pinned detail box (selection replaces it); and the units change. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 14 code lines, the loader included: it still derives per-store year-to-date rows, the subtitle and the axis steps; the ratio, tooltip rows and number formats are spec options.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
