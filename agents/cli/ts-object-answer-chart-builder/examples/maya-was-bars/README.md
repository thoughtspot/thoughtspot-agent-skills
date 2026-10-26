# Sales by item type against last year (MayaCharts)

How did each item type do this year, against the year before?

| | |
|---|---|
| Model | (Sample) Retail - Apparel (column names as that model's search returns them) |
| Search | `[sales] [item type] [date].yearly` |
| Library | MayaCharts 0.16.0 (`maya.core.global.js` from jsDelivr), through its ThoughtSpot adapter `maya.host.thoughtspot`. Pin the release the doctor's `mayacharts:` line names when you copy this |
| Tile | 8x6 grid units (about 620x400) |
| Data mode | B, live only. With no rows it shows an empty state that names the search |
| Verified | In the preview only: render, absent / wrapped / empty data, 280x300 to 1400x500 tiles, a 400x220 tile, hover sweep. `sample-data.json` is synthetic, shaped like the search's output. Not yet seen on a cluster tile |

## What MayaCharts does here
`chart.js` is 6 lines: the comment, the pinned URL, one adapter call holding the spec (3 lines; the theme is `--maya-*` in `chart.css`), and the line that loads the
library. `maya.host.thoughtspot(viz, spec)` reads the search, unwraps cells, matches `'Item Type'`, `'Total Sales'` and
`'Year(Date)'` against the columns ThoughtSpot returns (plain names, case-insensitive), mounts `#chart`, and signals render-complete once the chart
has settled, errors included. `was: { by: 'Year(Date)' }` takes the search's one row per item type and year as it is:
the latest year is the bar, the year before is the dashed ghost. `title` quotes the data with tokens
(`{max.x} leads with {max.y}`). Bars, ghosts, legend, axis, tooltip, hover dimming, keyboard focus, selection,
the empty state, the roll-up into Other on a short tile and the resize all come from the spec.

## Interactions
Hover a bar for its value and last year's (the others dim). Click a bar, or focus it and press Enter, to select it;
Escape clears it.

## Notes
- If the HTML tab already loaded the script, the adapter runs at once; otherwise the JS injects it and runs on load.
  A CDN that fails paints a message into the tile and still reports render-complete.
- With no rows the title shows its raw tokens above the empty state (a MayaCharts 0.16.0 bug, reported upstream).

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
Before reuse, swap the pinned version for the doctor's `mayacharts:` line.
