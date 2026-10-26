# US state hex map of sales

Which states have sales, and how do they rank?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [state]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 5x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Click Sales or Share of total to switch the measure (fill, legend, subtitle and tooltip follow). Hover or arrow-key to a hex for the state and its value; the hovered hex is outlined. Click hexes to select several; Escape clears. States without sales are drawn as empty outlines.

## Notes
Built on MayaCharts 0.18.1 as a `hexmap` (US states as equal hexagons) with `y: [sales, Share]` as the measure toggle and `select: 'multi'`. The body adds one field, each state's share of the total. Fill is a light-to-slate ramp by value (theme accent slate), not by rank as before: hexmap has no rank ramp, so the middle states sit closer together while Nevada and Montana stand out. Dropped against the old chart: rank fill, the pinned readout panel and values printed inside wide hexes. The accent is a mid slate rather than ink because 0.16.0, the version this chart was first built on, never flipped hex labels to white on dark fills, so an ink accent leaves the darkest state codes unreadable. The subtitle uses the `{max.x}` and `{max.y}` tokens, which follow the measure toggle. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
