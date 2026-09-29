# Share of sales against price per unit

Which item types carry the sales, and what do they earn per unit? Year-to-date change is flat for every type, so the default vertical measure is price per unit.

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].quarterly` |
| Library | Inline SVG and HTML (no CDN) |
| Tile | 8x7 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
hover a bubble for a tooltip; click a bubble or family key to isolate (others dim); toggle vertical measure between price per unit and change vs last year (quadrant bands appear only if the change spread reaches 5 points)

## Notes
Year-to-date change (Q1 to Q3 2026 against 2025) is -1.1% to +0.1% for all 15 types, so a growth-versus-share matrix would have no spread; price per unit (12 to 87 dollars) does. Families are an editorial grouping. Latest quarter defines year to date; needs matching quarters a year earlier for the change view.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
