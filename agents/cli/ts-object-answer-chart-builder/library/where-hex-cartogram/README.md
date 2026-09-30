# US state hex map of sales

Which states have sales, and how do they rank?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [state]` |
| Library | none (inline SVG) |
| Tile | 5x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales / Share of total toggle (header line, tooltip, readout, hex figures when wide); hover a hex; click a hex to pin it with a readout; Unpin clears

## Notes
Fill is by sales rank because Nevada and Montana dominate. Hex layout adapted from examples/State-hex-cartogram. Values print inside hexes only when the tile is wide enough (about 46px per hex); the toggle still changes header, tooltip and readout on narrow tiles.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
