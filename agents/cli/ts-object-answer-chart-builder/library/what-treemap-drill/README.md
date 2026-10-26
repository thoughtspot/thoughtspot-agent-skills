# Sales treemap with drill-down

Where do sales sit across families, item types and products, and how concentrated is each?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [product]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 8x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
The root shows each family with its item types nested inside under a name strip. Click anywhere in a family to zoom into it (its item types with their products nested inside), then click an item type to zoom into its products; the breadcrumb reads Back > Family > Item type, and Back, Escape or a click on empty space goes up one level. Hover or arrow-key to a rectangle for its sales (others dim). The product level is the last: a click there does nothing.

## Notes
Built on MayaCharts 0.18.1 as a single treemap spec with `drill` and `depth: 2` on the path Family > Item type > Product, so two levels are drawn at once below the current branch. Family is an editorial grouping derived from Item type (a literal `FAM` map in chart.js). Colours come from `colors: COL`, a literal map keyed by family, so each family keeps its hue at the root and through every drill without sorting rows or ordering a colour array; inside a family the rectangles step through tints of that hue by size (a drilled branch now shows five or more distinct tints, where 0.15.0 showed two or three). Rows with zero or negative sales are dropped (a treemap sizes by value). Render-complete fires on `maya-settled`, after the last animation. Labels shorten with an ellipsis when a rectangle is narrow. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
