# Sales pace by year

Is this year ahead of or behind the same point in earlier years?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | none (plain SVG) |
| Tile | 8x6 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Lines draw on left to right; hover a month for every year's cumulative sales; click a line or its label (or Enter) to open that year as monthly columns against the previous year outline; crumbs, Back and Escape return

## Notes
Years with fewer than 3 months are dropped. Partial years (2021 starts in Jun) are named in the subtitle. Header compares the latest year with the previous year through the same month and says when the month counts differ.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
