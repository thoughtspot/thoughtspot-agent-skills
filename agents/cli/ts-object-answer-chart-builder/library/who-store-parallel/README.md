# Stores across five measures

Which stores are alike across sales, units, price, year-to-date change and size, and which stand apart?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [store] [date].quarterly` |
| Library | Plain SVG and HTML (no CDN) |
| Tile | 12x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
lines draw in with a stagger; drag on any axis to brush and filter (matches stay ink, the rest fade), click an axis to clear its brush; hover a line for the store (nearest-line hit test); click a line to pin it and list its values and ranks; Reset and Escape

## Notes
YTD change compares the latest year's quarters up to the latest quarter with the same quarters last year; the axis is dropped when the view has no comparable quarters. Share of largest store is a rescaling of total sales, so those two axes are perfectly correlated. Stores are not placed by latitude/longitude.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
