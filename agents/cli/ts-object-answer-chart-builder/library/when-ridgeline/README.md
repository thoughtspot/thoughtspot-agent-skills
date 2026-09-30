# Sales ridgeline by year

How does the shape of the year compare across years, and what does one year look like month by month?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | d3@7 (cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js, fallback unpkg.com) |
| Tile | 6x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js, https://unpkg.com/d3@7/dist/d3.min.js |

## Interactions
ridges rise in with a stagger; hover a month for every year's value (vertical guide); click a ridge or year label (Enter/Space) to lift it to the front and open its monthly columns with the previous year as a dashed outline, crumbs, Back, Escape

## Notes
Latest year is ink, older years slate with decreasing opacity. 2021 is Jun-Dec and the latest year is a part year; both are labelled with their range and drawn only where months exist. Works under a filter down to one month.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
