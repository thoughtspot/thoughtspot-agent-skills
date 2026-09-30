# Sales change by family: units or price

For each product family, did sales change because we sold more units or because each unit sold for a different price?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].monthly` |
| Library | Hand-built HTML and SVG (no CDN) |
| Tile | 12x6 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | none |

## Interactions
Period toggle (Year to date against the same months a year earlier / Latest full year against the prior year) tweens values and bars in place; hover a card or a row for sales, units and price per unit in both periods plus the units and price effects, with the bar row under the pointer emphasised; click a card (or Enter) to expand it into its item types (All families expands into the families) while the others compress into a strip, click it again or press Escape to close

## Notes
Units (volume) effect = (units now - units before) x price before; price effect = (price now - price before) x units now; they sum exactly to the sales change (checked against the fixture). Family is an editorial grouping (AZ.familyOf), not a model column. Windows come from the rows: YTD uses the months of the latest year up to the latest month that the prior year also has; Latest full year needs 12 months in both years, so part years (2021, the current year) are skipped and named in the caption. Family cards share one bar scale with the zero placed by the data; All families has its own, and its price effect includes the mix shift between families. Effects under a millionth of prior sales are treated as zero (identical months in the source otherwise show float noise). With no comparison period each card shows its sales in the filter and says so; one family opens straight into its item types. Preview only: built on real search output and checked in the preview, but not yet on a Liveboard or seen in a real cluster tile.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
The block between the `amuzing core` markers is shared: change it in `library/_shared/` and run `helpers/sync-core.mjs`.
