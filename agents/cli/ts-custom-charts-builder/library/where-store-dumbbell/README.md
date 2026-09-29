# Store sales, this year vs last

Which stores are ahead or behind the same quarters last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | none (inline SVG) |
| Tile | 6x6 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sort toggle (rows glide to their new place); hover a row for both years and rank; click a row to expand it in place into its quarterly line (this year solid, last year dashed slate) with the readout below; click again, Collapse or Escape closes; list scrolls

## Notes
Latest quarter in the data sets the window. Axis does not start at zero, stated under the chart and in the expanded panel. The quarterly panel shows Q1 to Q4 for last year and the quarters so far for this year, all from the rows already returned.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
