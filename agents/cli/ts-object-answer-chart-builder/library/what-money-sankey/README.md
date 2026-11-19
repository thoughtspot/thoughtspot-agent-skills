# Where the money flows: region to family to item type

Which regions feed which product families and item types?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 12x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover or arrow-key to a node or flow for its sales and to highlight the flows it touches (the rest dim). Click a region node to drill into that region: it stays as the first column with its family and item type flows. Click a family there to drill one column further into its item types. The breadcrumb shows Back > region > family, and Back, Escape or a click on empty space goes up one level.

## Notes
Built on MayaCharts 0.18.1 as a single sankey spec over the path region, family, item type. Family is an editorial grouping derived in chart.js from a literal `FAM` map, not a model column. Colours come from a literal `colors` map in the spec, keyed by node name: families and their item types (and the flows into them) take the family hues, and the region names are left out of the map so region nodes stay neutral grey. The map never moves when a family is missing from the rows, so no row sort is needed. Known gap (seen on 0.16.0, not re-checked on 0.18.1): once drilled into a region, the whole branch (region, families, item types) draws in that region's palette slot instead of the family hues, and the region is no longer grey; the root view is correct. Thin nodes are unlabelled and named in the tooltip. Render-complete fires on `maya-settled`. Columns are matched by name pattern, so casing changes in the search output do not break it. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 8 code lines, the loader included; the one thing it computes, the Family column, is data MayaCharts cannot derive itself.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
