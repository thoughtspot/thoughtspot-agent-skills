# Item type rank by year

Which item types climb or fall in the sales ranking from year to year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [item type] [date].yearly` |
| Library | Hand-built SVG (no library, no CDN) |
| Tile | 12x6 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Toggle Rank / Sales for the vertical axis; hover a line to highlight it and dim the rest with a tooltip (year, rank, sales, rank change); click to pin, click empty space to release

## Notes
The yearly search has no month detail, so the first and last year are marked partial when their total is under 85% of the mean of the years between them (true for 2021 and 2026 here), with dashed segments and a shaded band. Labels read 'partial', not the months.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
