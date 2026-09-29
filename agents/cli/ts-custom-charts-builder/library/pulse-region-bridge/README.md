# YTD sales by region

Which regions and states moved year-to-date sales against the same quarters last year?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [region] [state] [date].quarterly` |
| Library | none (inline SVG) |
| Tile | 4x6 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a row for both years and the change; click a region step (or Enter) to split it into its states with the bridge re-scaled to that region (crumbs All regions / West, Back or Escape return); click a total or a state to isolate it, Show all clears

## Notes
SEARCH CHANGED from [sales] [region] [date].monthly to [sales] [region] [state] [date].quarterly (418 rows: 19 states x 22 quarters). YTD is now whole quarters; the latest quarter (Q3 2026) is complete so the region bridge matches the monthly one (-0.5 percent, -$686.5K). If the latest quarter were part-complete the window would over-state the current year. Axis starts at a non-zero value, stated under the chart.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
