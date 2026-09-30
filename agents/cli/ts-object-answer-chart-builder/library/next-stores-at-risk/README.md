# Stores against last year

Which stores are furthest below last year on the same quarters, against a threshold you set?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [date].quarterly` |
| Library | HTML and CSS (no CDN) |
| Tile | 6x6 grid units (07 Next tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
threshold slider (default -5%) flags stores below it; hover a row for numbers; click a row to pin its detail

## Notes
At the default -5% no store is flagged (range is -2.9% to +4.5%); the chart says so and the slider explores. Units change comes from quantity purchased when the search includes it.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
