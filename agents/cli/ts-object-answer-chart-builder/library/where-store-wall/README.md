# Quarterly sales by store

Which stores follow the company shape, and which have their own?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | none (plain SVG) |
| Tile | 12x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Scale toggle (same or own), sort toggle (Sales, Change vs last year, Name) tween in place; minis rise in with a stagger; hover a mini for the quarter under the pointer; click a store (or Enter) to FLIP-expand it to a full quarterly chart against the same quarters a year earlier; crumbs, Back and Escape shrink it back

## Notes
Change is the latest quarter against the same quarter a year earlier. A part first quarter is detected from the totals and named in the caption. At narrow widths the wall scrolls.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
