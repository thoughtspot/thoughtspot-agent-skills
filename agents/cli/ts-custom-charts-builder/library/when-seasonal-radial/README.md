# Monthly sales around the year

Which months are strong every year, and how does the latest year compare with earlier ones?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [date].monthly` |
| Library | Hand-built SVG (no library, no CDN) |
| Tile | 6x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a spoke for every year's value in that month; click a year in the key to isolate it (click again to release)

## Notes
One closed line per calendar year with at least 6 months of data; the latest year is always drawn. Partial years are open lines (2021 dashed and labelled Jun-Dec). Radius starts at zero, so level jumps dominate over seasonal shape. Header peak and trough are computed from the latest year's rows.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
