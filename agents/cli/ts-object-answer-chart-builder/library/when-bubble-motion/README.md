# Item types in motion by quarter

How did each item type move between volume and price, quarter by quarter?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].quarterly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Press Play (above the legend) to step through the quarters every 0.9 s; it stops on the last quarter, which is the one shown at first, and the title names the quarter on screen. The axes span every quarter, so the bubbles move against a still frame. Hover a bubble (or arrow-key to it) for the item type, family, units, price per unit and sales, with crosshair guides to both axes; the other bubbles dim. Click a bubble or a family in the legend to select it, Escape clears.

## Notes
Built on MayaCharts 0.18.1 as one `scatter` spec with `frame: 'Quarter'` (playback), `size: 'Sales'` (area, with a size key), `series: 'Family'` coloured by a literal `colors` map in the spec, `name: 'Item type'` and `select`. The body only derives what the search does not return: the family from Item type (a literal `FAM` map), price per unit as sales over units, and a 'Q3 2026' quarter label, rows sorted by date so the frames play in time order. Dropped against the old chart: the scrub slider (the Play button only steps forward from the first quarter; `el.view = { frame }` is not exposed in the tile), the 4-quarter trails, the follow-one-bubble path across all quarters, the in-plot quarter watermark, direct labels on the largest bubbles and the headline naming the leader. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
