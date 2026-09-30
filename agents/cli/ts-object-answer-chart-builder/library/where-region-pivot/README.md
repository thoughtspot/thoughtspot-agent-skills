# Region by family pivot

How does each region's sales break down by product family, and where does price per unit differ?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [region] [state] [item type]` |
| Library | Plain HTML table (no CDN) |
| Tile | 12x7 grid units (03 Where tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Sales / Units / Price per unit toggle (share bars tween); click a region row to show its states and a family header to show its item types (height and column-width tweens); Expand all / Collapse all (one Expand/Collapse button below 360px); hover a cell to highlight its row and column with a tooltip giving sales, units, share of row, share of column and price per unit against the region

## Notes
Price per unit is sum(sales) / sum(units) at every level (cells, family subtotals, region and state rows, grand total), never an average of ratios, so every total matches ThoughtSpot. Families are an editorial grouping of the 15 item types (AZ.familyOf), not a model column; family hue appears only as a swatch on the family headers, share bars are slate. Bars show share of row sales (units in Units mode), scaled to the longest share in view. The largest region opens by default when its states fit. Expand state and measure survive redraw and are re-resolved against the rows, so a filtered-out region or family simply drops. Header, first column and Total row are sticky; narrow tiles scroll sideways. Preview only: built on real search output and checked in the preview, but not yet on a Liveboard or seen in a real cluster tile.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
