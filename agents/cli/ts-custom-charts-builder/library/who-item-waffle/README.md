# Family waffle: share of sales or units

How does each product family's share of sales compare with its share of units?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type]` |
| Library | Plain HTML/CSS grid (no CDN) |
| Tile | 6x6 grid units (06 Who tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales/Units toggle; hover a family (squares or key) to highlight it with a tooltip; click to isolate and list item types with shares; All families button to release

## Notes
100 squares assigned by largest remainder. Families are an editorial grouping. Hit-testing is by position so the gaps between squares still register.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
