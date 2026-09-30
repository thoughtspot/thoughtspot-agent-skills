# Premium or volume, by item type

Which item types earn more than their share of units (premium) and which sell on volume?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [product]` |
| Library | Muze |
| Tile | 8x7 grid units (04 What tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Hover a row for share of sales, share of units, the gap, and price per unit against the average; the hovered bar stays, others dim, and a ruler reads the scale. Click a bar (or arrow keys and Enter) to see that item type's products, measured the same way inside the item type (top 12 by gap); the crumb or Escape goes back. Toggle between gap in pts and price index; the bars morph between the two.

## Notes
Muze draws the bars (colour per point in encodingTransform, order via axes.y.ordering custom). Names, values, zero line, grid and axis labels are SVG/HTML overlays drawn from the geometry captured in encodingTransform. Two Muze workarounds: (1) Muze floors each category band at the measured tick-label height even with the y axis hidden, so the canvas sets useExternalCSS and chart.css shrinks the element Muze measures (body > .muze-ticks); a band still needs about 18 px, so a short tile keeps the rows with the largest gaps, says so, and drops one more row if Muze still draws a scrollbar. (2) Updating the data of a mounted canvas throws in this Muze build, so every toggle or drill remounts; the toggle remounts without Muze's transition and tweens the rects from their old positions. Muze's x axis and grid are hidden (its label row made the plot scroll). Colour is the family (editorial grouping via AZ.familyColor, not a model column). With one item type in the filter the top level has no gap and offers the product drill. probe --sweep at 520x420 counts 2 of 5 middle-line points: all five sit on one bar, and the moving ruler keeps the same markup length, which the probe reads as no change; 8 of 13 overall, 13 of 13 at 280 wide. Preview only: built on real search output and checked in the preview, but not yet on a Liveboard or seen in a real cluster tile.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
