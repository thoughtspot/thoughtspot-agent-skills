# Library: proven live-data charts

Every chart here runs on the model **(Sample) Retail - Apparel**, reads only what its search returns (data mode B, an empty state names the search), is interactive, and passed the loop, the edge checks, `probe.mjs` and a screenshot in a real cluster. Start from the nearest one: copy `library/<slug>/`, change the search and the copy, run the loop.

Shared pieces: `library/_shared/core.js` and `core.css` (theme, data access, tooltip, bounded CDN loader, boot), `library/_shared/us-states.js` (inline US map). The Liveboard that arranges them, and the tools that build it, are in the sibling skill `ts-object-liveboard-chart-builder`.

Charts marked *(preview only)* were built on real search output and passed the loop, the edge checks and `probe.mjs`, but have not been on a Liveboard or screenshotted in a cluster yet (a `.preview-only` file in the chart folder; delete it once the chart has been seen on a tile).

| Chart | Tab | Tile | Built with | Search |
|---|---|---|---|---|
| `about-guide` How to read this Liveboard | 01 About | 12x4 grid units | HTML (no chart library) | `[sales] [item type]` |
| `about-hero` About this Liveboard | 01 About | 12x8 grid units | HTML (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `banner-pulse` Pulse banner | 02 Pulse | 12x4 grid units | HTML (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-bullet` Latest month, bullet | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-dotstrip` Latest month, dot strip | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-flip` Year to date, flip card | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-odometer` Year to date, odometer | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-quarter-pairs` Quarter pairs, drill to months | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-ring` Sales year to date, ring | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `kpi-sparkbars` Monthly columns, drill to a month | 02 Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `pulse-family-growth` Sales change by family: units or price *(preview only)* | 02 Pulse | 12x6 grid units | Hand-built HTML and SVG (no CDN) | `[sales] [quantity purchased] [item type] [date].monthly` |
| `pulse-pace-lines` Sales pace by year | 02 Pulse | 8x6 grid units | none (plain SVG) | `[sales] [date].monthly` |
| `pulse-region-bridge` YTD sales by region | 02 Pulse | 4x6 grid units | none (inline SVG) | `[sales] [region] [state] [date].quarterly` |
| `pulse-kpi-asp` Average selling price | Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `pulse-kpi-best` Best month | Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `pulse-kpi-sales` Sales, year to date | Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `pulse-kpi-units` Units sold, year to date | Pulse | 3x4 grid units | HTML and inline SVG (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `pulse-monthly-line` Monthly sales against last year | Pulse | 8x6 grid units | Muze (line), with an HTML header and legend | `[sales] [date].monthly` |
| `banner-where` Where banner | 03 Where | 12x4 grid units | HTML (no chart library) | `[sales] [region] [state]` |
| `state-sales-units` Sales against units by state | 03 Where | 6x6 grid units | Muze point layer, with an SVG overlay | `[sales] [quantity purchased] [state]` |
| `where-hex-cartogram` US state hex map of sales | 03 Where | 5x7 grid units | none (inline SVG) | `[sales] [state]` |
| `where-region-item-heatmap` Region by item type heatmap | 03 Where | 6x6 grid units | none (HTML grid) | `[sales] [region] [item type]` |
| `where-region-pivot` Region by family pivot *(preview only)* | 03 Where | 12x7 grid units | Plain HTML table (no CDN) | `[sales] [quantity purchased] [region] [state] [item type]` |
| `where-state-bubbles` Sales bubble map by state | 03 Where | 7x7 grid units | none (inline SVG; pre-projected us-atlas states-albers-10m paths embedded in chart.js) | `[sales] [store] [state] [region]` |
| `where-store-dumbbell` Store sales, this year vs last | 03 Where | 6x6 grid units | none (inline SVG) | `[sales] [store] [date].quarterly` |
| `where-store-wall` Quarterly sales by store | 03 Where | 12x7 grid units | none (plain SVG) | `[sales] [store] [date].quarterly` |
| `banner-what` What banner | 04 What | 12x4 grid units | HTML (no chart library) | `[sales] [item type]` |
| `what-chord` Region to family chord | 04 What | 6x7 grid units | d3@7 (d3-hierarchy, d3-shape, d3-chord) from https://cdn.jsdelivr.net/npm/d3@7 (fallback https://unpkg.com/d3@7) | `[sales] [region] [item type]` |
| `what-marimekko` Region by family Marimekko | 04 What | 6x7 grid units | pure SVG, no library | `[sales] [region] [item type]` |
| `what-money-sankey` Where the money flows: region to family to item type | 04 What | 12x7 grid units | echarts@5 via cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js (fallback unpkg.com/echarts@5/dist/echarts.min.js) | `[sales] [region] [item type]` |
| `what-pareto` Products that make 80% of sales | 04 What | 6x7 grid units | echarts@5 via cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js (fallback unpkg.com/echarts@5/dist/echarts.min.js) | `[product] [item type] [sales] [quantity purchased]` |
| `what-premium-diverging` Premium or volume, by item type *(preview only)* | 04 What | 8x7 grid units | Muze | `[sales] [quantity purchased] [item type] [product]` |
| `what-price-volume` Price against volume by item type | 04 What | 8x6 grid units | Hand-built inline SVG, no external library | `[sales] [quantity purchased] [item type]` |
| `what-quadrant-guide` How to read price against volume | 04 What | 4x6 grid units | Plain HTML and CSS, no external library | `[sales] [quantity purchased] [item type]` |
| `what-radial-bars` Item types as radial bars | 04 What | 6x6 grid units | d3@7 (d3-hierarchy, d3-shape, d3-chord) from https://cdn.jsdelivr.net/npm/d3@7 (fallback https://unpkg.com/d3@7) | `[sales] [item type] [product]` |
| `what-treemap-drill` Sales treemap with drill-down | 04 What | 8x7 grid units | d3@7 (d3-hierarchy, d3-shape, d3-chord) from https://cdn.jsdelivr.net/npm/d3@7 (fallback https://unpkg.com/d3@7) | `[sales] [item type] [product]` |
| `what-sunburst` Sales by family, item type and product | What | 6x7 grid units | Plotly sunburst (plotly.js-dist-min 2.35.2 from a CDN) | `[sales] [item type] [product]` |
| `banner-when` When banner | 05 When | 12x4 grid units | HTML (no chart library) | `[sales] [date].monthly` |
| `when-bubble-motion` Item types in motion by quarter | 05 When | 12x7 grid units | Plain SVG and HTML, requestAnimationFrame tween (no CDN) | `[sales] [quantity purchased] [item type] [date].quarterly` |
| `when-calendar-heatmap` Sales, units and price by month | 05 When | 6x7 grid units | Plain HTML (no library, no CDN) | `[sales] [quantity purchased] [date].monthly` |
| `when-family-stream` Sales by product family, by quarter | 05 When | 12x6 grid units | d3@7.9.0 (cdn.jsdelivr.net, fallback unpkg; injected by chart.js) | `[sales] [item type] [date].quarterly` |
| `when-rank-bump` Item type rank by year | 05 When | 12x6 grid units | Hand-built SVG (no library, no CDN) | `[sales] [item type] [date].yearly` |
| `when-ridgeline` Sales ridgeline by year | 05 When | 6x7 grid units | d3@7 (cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js, fallback unpkg.com) | `[sales] [date].monthly` |
| `when-seasonal-radial` Monthly sales around the year | 05 When | 6x7 grid units | Hand-built SVG (no library, no CDN) | `[sales] [date].monthly` |
| `banner-who` Who banner | 06 Who | 12x4 grid units | HTML (no chart library) | `[sales] [store]` |
| `who-item-waffle` Family waffle: share of sales or units | 06 Who | 6x6 grid units | Plain HTML/CSS grid (no CDN) | `[sales] [quantity purchased] [item type]` |
| `who-product-beeswarm` Every product by price per unit | 06 Who | 6x6 grid units | d3@7 force simulation and scales (cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js, fallback unpkg.com) | `[product] [item type] [sales] [quantity purchased]` |
| `who-product-table` Products by sales | 06 Who | 12x7 grid units | Plain HTML table (no CDN) | `[product] [item type] [sales] [quantity purchased]` |
| `who-region-profile` Region profiles: family mix against average | 06 Who | 6x6 grid units | Plain HTML/CSS bars (no CDN) | `[sales] [region] [item type]` |
| `who-store-league` Store league: position, movement and form *(preview only)* | 06 Who | 12x7 grid units | Plain HTML table (no CDN) | `[sales] [store] [region] [date].monthly [date].'this year' [date].'last year'` |
| `who-store-parallel` Stores across five measures | 06 Who | 12x6 grid units | Plain SVG and HTML (no CDN) | `[sales] [quantity purchased] [store] [date].quarterly` |
| `who-store-race` Store race: cumulative sales by quarter | 06 Who | 12x7 grid units | Plain HTML/CSS, requestAnimationFrame clock (no CDN) | `[sales] [store] [date].quarterly` |
| `banner-next` Next banner | 07 Next | 12x4 grid units | HTML (no chart library) | `[sales] [quantity purchased] [date].monthly` |
| `next-action-list` Moves the numbers support | 07 Next | 4x7 grid units | HTML and CSS (no CDN) | `[sales] [quantity purchased] [item type] [date].quarterly` |
| `next-growth-matrix` Share of sales against price per unit | 07 Next | 8x7 grid units | Inline SVG and HTML (no CDN) | `[sales] [quantity purchased] [item type] [date].quarterly` |
| `next-run-rate` Year-end outlook | 07 Next | 6x6 grid units | Inline SVG (no CDN) | `[sales] [date].monthly` |
| `next-stores-at-risk` Stores against last year | 07 Next | 6x6 grid units | HTML and CSS (no CDN) | `[sales] [store] [date].quarterly` |
| `next-what-if` What if the rest of the year moves | Next | 6x6 grid units | Inline SVG with native range sliders | `[sales] [quantity purchased] [date].monthly` |

## What each one does when you touch it

- **about-guide**: Click a tab to see how to read it. Hover a family for its item types and shares; click a family to dim the rest.
- **about-hero**: Click a person or a term to expand it.
- **banner-pulse**: Hover a number for how it is calculated. Click a prompt to copy it, then paste it into Spotter.
- **kpi-bullet**: Sales, Units, Price toggle. Hover the track or a legend row for each marker; the others dim. The bar grows in.
- **kpi-dotstrip**: Sales, Units, Price toggle. Dots fade in left to right. Hover a dot for the month and its rank. Click a dot to pin it against the latest month; click again to unpin.
- **kpi-flip**: Click or Enter flips the card between the year-to-date figure and the three best and three weakest months in the current view. Sales, Units, Price toggle. Hover a month for its value and change.
- **kpi-odometer**: Click or Enter cycles Sales, Units, Price per unit and the digit columns roll to the new value. Hover a digit for both years.
- **kpi-quarter-pairs**: Sales, Units, Price toggle. Columns grow in. Hover a pair. Click a pair or use arrow keys and Enter to see its months; Escape or Back closes.
- **kpi-ring**: Sales, Units, Price toggle with the arc tweening from the old share. Hover the ring for both figures. The centre number counts up.
- **kpi-sparkbars**: Sales, Units, Price toggle. Columns rise in staggered. Hover a column for the month. Click a column or use arrow keys and Enter to compare that month with the same month a year earlier; Escape or Back closes.
- **pulse-family-growth**: Period toggle (Year to date against the same months a year earlier / Latest full year against the prior year) tweens values and bars in place; hover a card or a row for sales, units and price per unit in both periods plus the units and price effects, with the bar row under the pointer emphasised; click a card (or Enter) to expand it into its item types (All families expands into the families) while the others compress into a strip, click it again or press Escape to close
- **pulse-pace-lines**: Lines draw on left to right; hover a month for every year's cumulative sales; click a line or its label (or Enter) to open that year as monthly columns against the previous year outline; crumbs, Back and Escape return
- **pulse-region-bridge**: Hover a row for both years and the change; click a region step (or Enter) to split it into its states with the bridge re-scaled to that region (crumbs All regions / West, Back or Escape return); click a total or a state to isolate it, Show all clears
- **pulse-kpi-asp**: YTD and All toggle. Hover the sparkline for the month, its value and the change on the same month a year earlier.
- **pulse-kpi-best**: YTD and All toggle. Hover the sparkline for the month, its value and the change on the same month a year earlier.
- **pulse-kpi-sales**: YTD and All toggle. Hover the sparkline for the month, its value and the change on the same month a year earlier.
- **pulse-kpi-units**: YTD and All toggle. Hover the sparkline for the month, its value and the change on the same month a year earlier.
- **pulse-monthly-line**: Hover for month, sales, same month last year and the change. Click the key to hide or show the last-year line. The two largest month-on-month steps are marked from the data.
- **banner-where**: Hover a number for how it is calculated. Click a prompt to copy it, then paste it into Spotter.
- **state-sales-units**: Hover a dot for sales, units, sales per unit and its gap to average; click a dot to pin it (others dim); click again or the background to clear
- **where-hex-cartogram**: Sales / Share of total toggle (header line, tooltip, readout, hex figures when wide); hover a hex; click a hex to pin it with a readout; Unpin clears
- **where-region-item-heatmap**: Sales / Share of region toggle; hover a cell for sales, shares and rank; click a row or column header to isolate it
- **where-region-pivot**: Sales / Units / Price per unit toggle (share bars tween); click a region row to show its states and a family header to show its item types (height and column-width tweens); Expand all / Collapse all (one Expand/Collapse button below 360px); hover a cell to highlight its row and column with a tooltip giving sales, units, share of row, share of column and price per unit against the region
- **where-state-bubbles**: Sales / Stores toggle sets bubble size at both levels (radii tween); hover a state, bubble or store; click a state to zoom (viewBox tween) while its bubble breaks into one bubble per store labelled by zip code; crumbs, Back and Escape zoom out
- **where-store-dumbbell**: Sort toggle (rows glide to their new place); hover a row for both years and rank; click a row to expand it in place into its quarterly line (this year solid, last year dashed slate) with the readout below; click again, Collapse or Escape closes; list scrolls
- **where-store-wall**: Scale toggle (same or own), sort toggle (Sales, Change vs last year, Name) tween in place; minis rise in with a stagger; hover a mini for the quarter under the pointer; click a store (or Enter) to FLIP-expand it to a full quarterly chart against the same quarters a year earlier; crumbs, Back and Escape shrink it back
- **banner-what**: Hover a number for how it is calculated. Click a prompt to copy it, then paste it into Spotter.
- **what-chord**: Hover a ribbon or arc to highlight it and dim the rest; click a family arc to open its item types (animated morph); crumbs, Back, Escape.
- **what-marimekko**: Hover a segment for sales and shares; click a column to widen it to the full tile and split families into item types; crumbs, Back, Escape.
- **what-money-sankey**: Hover a node or flow to highlight adjacent flows; click a node to isolate its flows and dim the rest; click background or Show all to clear
- **what-pareto**: Item type chips (top 6 plus All) re-rank and re-animate the Pareto; hover for rank, product, sales and cumulative share; click a bar to open a detail card (sales, units, price against the item type average, rank in the item type) with an animated highlight along the cumulative line; Top 50 / All toggle; Escape or Close dismisses
- **what-premium-diverging**: Hover a row for share of sales, share of units, the gap, and price per unit against the average; the hovered bar stays, others dim, and a ruler reads the scale. Click a bar (or arrow keys and Enter) to see that item type's products, measured the same way inside the item type (top 12 by gap); the crumb or Escape goes back. Toggle between gap in pts and price index; the bars morph between the two.
- **what-price-volume**: Hover a bubble for details; click a bubble or a family in the key to isolate that family; click background to clear
- **what-quadrant-guide**: Click a quadrant to expand its members with units, price and sales; hovering dims the other quadrants
- **what-radial-bars**: Hover a bar; click a bar to swap to that item type's top 12 products (bars retract then grow); crumbs, Back, Escape.
- **what-treemap-drill**: Click a rectangle to zoom in (450 ms layout tween); crumbs, Back and Escape go up; Enter or Space opens a focused rectangle; hover for sales and share of parent.
- **what-sunburst**: Click a wedge to zoom in (animated); click the centre or a crumb to zoom back out. Hover a wedge for its sales and shares; the line under the chart follows the pointer. Two rings show at a time, and products appear as you zoom into an item type.
- **banner-when**: Hover a number for how it is calculated. Click a prompt to copy it, then paste it into Spotter.
- **when-bubble-motion**: Play/Pause (Play restarts from the first quarter); scrub slider; bubbles glide between quarters with a 4-quarter trail; hover a bubble; click a bubble (Enter/Space) to follow it: others dim and its path across all quarters is drawn; Escape releases
- **when-calendar-heatmap**: Toggle Sales / Units / Price per unit (cells re-colour with a tween); hover a cell for value and change on the same month a year earlier; click a cell or month name to highlight that calendar month; click a year label to morph the grid into that year's 12 monthly columns with the previous year as a slate outline (crumbs, Back, Escape)
- **when-family-stream**: Toggle Stream / Stacked / 100% (the bands morph); hover a quarter for every series; click a family band or label to drill into its item types (tinted family hue, animated), Back, crumb or Escape returns; swatch beside a label isolates a series
- **when-rank-bump**: Toggle Rank / Sales for the vertical axis; hover a line to highlight it and dim the rest with a tooltip (year, rank, sales, rank change); click to pin, click empty space to release
- **when-ridgeline**: ridges rise in with a stagger; hover a month for every year's value (vertical guide); click a ridge or year label (Enter/Space) to lift it to the front and open its monthly columns with the previous year as a dashed outline, crumbs, Back, Escape
- **when-seasonal-radial**: Hover a spoke for every year's value in that month; click a year in the key to isolate it (click again to release)
- **banner-who**: Hover a number for how it is calculated. Click a prompt to copy it, then paste it into Spotter.
- **who-item-waffle**: Sales/Units toggle; hover a family (squares or key) to highlight it with a tooltip; click to isolate and list item types with shares; All families button to release
- **who-product-beeswarm**: dots settle from the price line into a force-simulation swarm; family chips filter (others dim); hover a dot; click a dot (Enter/Space on the 12 largest) to open its card (sales, units, price vs item type average, rank) with item type peers highlighted and the average marked; Back, crumbs and Escape close
- **who-product-table**: Click a header to sort (rows glide); search by name; family chips filter; Show 25 more; hover row tooltip; click a row to open a detail row with sales, units and price against the item type average, its rank in the item type and animated bars (one row open at a time, click again or Escape closes)
- **who-region-profile**: Hover a family row for the region's share, the average and the gap in points; click a region to enlarge it and dim the rest; click again to restore
- **who-store-league**: Region chips filter (rows glide, FLIP); click a header to sort by position, movement, store, region, YTD sales, change or form (rows glide); hover a row for YTD, same months last year, change, position change and form count, plus a line explaining the hovered column; hover a form square for that month against the same month a year earlier; click a row (or Enter) to open its monthly bars, this year in ink against last year in slate, bars grow in; hover a month for both values; click again or Escape closes
- **who-store-parallel**: lines draw in with a stagger; drag on any axis to brush and filter (matches stay ink, the rest fade), click an axis to clear its brush; hover a line for the store (nearest-line hit test); click a line to pin it and list its values and ranks; Reset and Escape
- **who-store-race**: Play/Pause (Play restarts from the first quarter); scrub slider over quarters; hover for store, rank, cumulative and quarter sales; click a store to follow it (heavier outline, pinned rank row if it leaves the top 10)
- **banner-next**: Hover a number for how it is calculated. Click a prompt to copy it, then paste it into Spotter.
- **next-action-list**: click a move to open or close its evidence; hover an evidence bar for the numbers
- **next-growth-matrix**: hover a bubble for a tooltip; click a bubble or family key to isolate (others dim); toggle vertical measure between price per unit and change vs last year (quadrant bands appear only if the change spread reaches 5 points)
- **next-run-rate**: scenario toggle (both, same months last year, 3-month average); hover a month for actual or projected values
- **next-stores-at-risk**: threshold slider (default -5%) flags stores below it; hover a row for numbers; click a row to pin its detail
- **next-what-if**: Drag or arrow-key the price and units sliders: the projected columns and the year-end totals glide to the new figure. Reset returns to the baseline. Hover a month for baseline, scenario and change.
