# Sales by family, item type and product

How do sales split from family to item type to product?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [product]` |
| Library | MayaCharts 0.18.1 (maya.global.js from jsDelivr) |
| Tile | 6x7 grid units (What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js` |

## Interactions
Hover a wedge for its sales and share of the parent (other wedges dim). Click a wedge to zoom into it (animated), with a breadcrumb of the path; Back, Escape or a click on empty space goes up a level. The centre shows the total of the current level.

## Notes
Built on MayaCharts 0.18.1 as a single sunburst spec with `path: [Family, Item type, Product]` and `drill: true`. Family is an editorial grouping (a literal `FAM` map in chart.js), not a model column. Colours are `colors: COL`, a literal map keyed by family, so the rows need no sorting and each family keeps its hue through every drill (checked by drilling into Accessories and into Swim and basics, which hold their pink and amber with no other family present). The hand-made top 6 plus Other (n) per item type is gone: `minAngle: 5` folds product wedges under 5 degrees into MayaCharts' grey Other (n) per parent instead, so there is one fold mechanism and no Other next to another Other. The fold is redone at the zoom shown, so drilling into a family or item type shows every product (the old roll-up hid them at every level); the largest sibling never folds, so a few thin wedges can remain. Render-complete fires on `maya-settled`. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
