# Sales bubble map by state

Which states carry the sales, and how many stores sit behind them?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [store] [state] [region]` |
| Library | none (inline SVG; pre-projected us-atlas states-albers-10m paths embedded in chart.js) |
| Tile | 7x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales / Stores toggle sets bubble size at both levels (radii tween); hover a state, bubble or store; click a state to zoom (viewBox tween) while its bubble breaks into one bubble per store labelled by zip code; crumbs, Back and Escape zoom out

## Notes
Stores are placed by state centre and arranged around it, never by lat/long. In Stores mode at the store level every bubble is one store, so all are the same size. Map paths are inline because tiles cannot fetch().

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
