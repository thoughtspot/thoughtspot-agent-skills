# Store race: cumulative sales by quarter

Which stores lead on cumulative sales, and how does the ranking change quarter by quarter?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | Plain HTML/CSS, requestAnimationFrame clock (no CDN) |
| Tile | 12x7 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Play/Pause (Play restarts from the first quarter); scrub slider over quarters; hover for store, rank, cumulative and quarter sales; click a store to follow it (heavier outline, pinned rank row if it leaves the top 10)

## Notes
Starts paused on the last quarter. Region is not shown; state is parsed from the store name. Q2 2021 holds June only. In this data one store (Nevada 89145) leads at every quarter, so the race shows the gap and the mid-table reshuffle, not lead changes.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
