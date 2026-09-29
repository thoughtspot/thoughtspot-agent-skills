# Item types in motion by quarter

How did each item type move between volume and price, quarter by quarter?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].quarterly` |
| Library | Plain SVG and HTML, requestAnimationFrame tween (no CDN) |
| Tile | 12x7 grid units (05 When tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Play/Pause (Play restarts from the first quarter); scrub slider; bubbles glide between quarters with a 4-quarter trail; hover a bubble; click a bubble (Enter/Space) to follow it: others dim and its path across all quarters is drawn; Escape releases

## Notes
Starts paused on the last quarter. x is units, y is price per unit (sales / units), area is sales, hue is product family (editorial grouping). Q2 2021 holds June only. Axes are fixed across quarters so motion is comparable.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
