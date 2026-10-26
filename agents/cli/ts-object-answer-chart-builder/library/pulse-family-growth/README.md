# Sales change by family: units or price

For each product family, did sales change because we sold more units or because each unit sold for a different price?

| | |
|---|---|
| Model | (Sample) Retail - Apparel |
| Search | `[sales] [quantity purchased] [item type] [date].monthly` |
| Library | MayaCharts 0.18.1 (maya.core.global.js from jsDelivr) |
| Tile | 12x6 grid units (02 Pulse tab) |
| Data mode | B, live only. With no rows it shows an empty state that names the search. |
| CDN | `https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js` |

## Interactions
The measure toggle switches between latest full year and year to date. Hover a bar for the units effect, the price effect and their total. Click a family (or Enter) to drill into its item types; Back, Escape or a click on empty space returns. Click a legend key to hide an effect. Arrow keys step through families.

## Notes
Built on MayaCharts 0.18.1: a horizontal stacked `bar` with `path: [Family, Item type]` and `drill`. `series` is the effect (units in dark slate, price in light slate) and the `y` array is the two periods, which gives the measure toggle. Each effect is computed per item type: units effect = (units now - units before) x price before, and price effect = (price now - price before) x units now. Families and the total add up from the item types, so a family's price effect no longer includes the mix shift between its item types (the old All families card did). The title's `{total}` token gives the sales change for the period shown. Periods come from the rows as before: year to date is the latest year's months against the same months a year earlier, and the latest full year needs 12 months in both years. Dropped against the old chart: the card layout, family hues (families are now the category axis, and effects are the only colour), the All families card (now the title), the per-family percent change, and the period tween. Preview-verified on synthetic data, not yet re-checked on a cluster.

chart.js is 18 code lines (comments aside), the loader included: it still derives the units and price effect rows and the subtitle (MayaCharts has no native price-volume split); Family is a literal `FAM` map in chart.js.

## Paste
chart.html into the HTML tab, chart.css into the CSS tab, chart.js into the JS tab, then bind the search above.
