# Store league: position, movement and form

Which stores lead this year, which are climbing, and which are in form?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [region] [date].monthly [date].'this year' [date].'last year'` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x7 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
Click a column header (or Enter / Space on it) to sort by store, YTD sales, change on last year, movement or form; rows start in league order (YTD sales, highest first). Hover a row's bar for a tooltip with all four values. Click a row to select it; Escape clears. Arrow keys move between rows.

## Notes
Built on MayaCharts 0.18.1 as a `table` with `y: ['YTD', 'Change', 'Move', 'Form']` and `select`. The body keeps the old rules: YTD runs from the first month of the latest year in the result through the latest complete month (a latest month under 60% of the median of the three before it is partial and left out, and the subtitle says so), last year uses the same months, Move is places gained on last year's league over that window, and Form counts how many of the last 5 complete months beat the same month a year earlier. The headline names the leader and the biggest climber. Each column draws an in-cell bar; on the signed vs LY and Move columns the bar shows the size, not the sign, so read the number. Dropped against the old chart: the position column (rows start in position order), region column and region chips, the five coloured form squares (now a count), the monthly this-year-against-last-year bars on row click, and the per-column explanation in the tooltip. Preview-verified on synthetic data, not yet re-checked on a cluster.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
