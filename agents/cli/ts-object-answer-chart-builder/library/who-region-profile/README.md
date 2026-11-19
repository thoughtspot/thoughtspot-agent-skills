# Region profiles: family mix against average

Does any region sell a different family mix from the all-region average?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 6x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Switch between Gap from average and Share of region sales with the toggle. Hover a bar for the region, the family and the value. Click a family in the key to hide or show it. Click bars to select; Escape clears. Arrow keys step through regions and families.

## Notes
Built on MayaCharts 0.18.1 as a grouped horizontal `bar`: one group per region (region by position, never by colour), one bar per family in its family hue, with `y: ['Gap', 'Share']` as the measure toggle. Gap is the region's family share minus the all-region share, in points; the headline names the largest gap and says when every gap is under 1 point (true in this data). The body derives families from item type through a literal `FAM` map in chart.js (hues from the literal `COL` map) and computes both measures. Dropped against the old chart: the small-multiple panels with the all-region average tick on each bar (the Gap view replaces it) and click-to-enlarge a region. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
