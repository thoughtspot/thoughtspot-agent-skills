# Region profiles: family mix against average

Does any region sell a different family mix from the all-region average?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [item type]` |
| Library | Plain HTML/CSS bars (no CDN) |
| Tile | 6x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a family row for the region's share, the average and the gap in points; click a region to enlarge it and dim the rest; click again to restore

## Notes
Region is shown by panel, never colour. In this data all five regions are within 1 point of the average, so bars and ticks nearly coincide; the header says so. Bars share one scale.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
