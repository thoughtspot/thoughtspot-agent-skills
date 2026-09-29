#!/usr/bin/env python3
"""Writes liveboard.spec.json from the tile table below. Edit the table, run this, then send the tiles
(node scripts/liveboard-pack.mjs --commit --all, or just the slugs that changed). Positions are grid units on a 12 column grid."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
M = "[sales] [quantity purchased] [date].monthly"
MODEL = {"name": "(Sample) Retail - Apparel", "guid": "cd252e5c-b552-49a8-821d-3eadaa049cca"}

def t(slug, title, search, x, y, w, h, desc="", filters=True):
    d = {"slug": slug, "title": title, "search": search, "x": x, "y": y, "w": w, "h": h}
    if desc: d["description"] = desc
    if not filters: d["filters"] = False
    return d

PROD = "[product] [item type] [sales] [quantity purchased]"
QTR_ST = "[sales] [store] [date].quarterly"
TABS = [
 ("01 About", [
   t("about-hero", "About this Liveboard", M, 0, 0, 12, 6, filters=False),
   t("about-guide", "How to read this Liveboard", "[sales] [item type]", 0, 6, 12, 4, filters=False),
 ]),
 ("02 Pulse", [
   t("banner-pulse", "About this tab", M, 0, 0, 12, 3),
   t("pulse-kpi-sales", "Sales, sparkline", M, 0, 3, 3, 4),
   t("kpi-ring", "Year to date against last year", M, 3, 3, 3, 4),
   t("kpi-odometer", "Year to date, odometer", M, 6, 3, 3, 4),
   t("kpi-flip", "Year to date, flip card", M, 9, 3, 3, 4),
   t("kpi-bullet", "Latest month, bullet", M, 0, 7, 3, 4),
   t("kpi-sparkbars", "Monthly columns, drill to a month", M, 3, 7, 3, 4),
   t("kpi-quarter-pairs", "Quarter pairs, drill to months", M, 6, 7, 3, 4),
   t("kpi-dotstrip", "Latest month, dot strip", M, 9, 7, 3, 4),
   t("pulse-monthly-line", "Monthly sales against last year", "[sales] [date].monthly", 0, 11, 8, 6, "The dashed line is the same month a year earlier. The two largest month-on-month steps are marked. Hover for the month."),
   t("pulse-region-bridge", "Year to date sales by region", "[sales] [region] [state] [date].quarterly", 8, 11, 4, 6, "Change in year-to-date sales by region. Click a region to split it into states."),
   t("pulse-pace-lines", "Sales pace by year", "[sales] [date].monthly", 0, 17, 12, 6, "Cumulative sales by month, one line per year. Click a line to open that year."),
 ]),
 ("03 Where", [
   t("banner-where", "About this tab", "[sales] [region] [state]", 0, 0, 12, 3),
   t("where-state-bubbles", "Sales by state", "[sales] [store] [state] [region]", 0, 3, 7, 7, "Bubble size is sales or stores. Click a state to zoom in and see its stores."),
   t("where-hex-cartogram", "State sales as a hex map", "[sales] [state]", 7, 3, 5, 7, "One hex per state, shaded by sales. Click a hex to pin it."),
   t("where-store-wall", "Quarterly sales by store", QTR_ST, 0, 10, 12, 7, "Thirty mini charts. Toggle scale and sort; click a store to expand it."),
   t("where-store-dumbbell", "Store sales, this year against last", QTR_ST, 0, 17, 6, 6, "Each store against the same quarters last year. Click a store for its quarters."),
   t("where-region-item-heatmap", "Region by item type", "[sales] [region] [item type]", 6, 17, 6, 6, "Sales, or share of the region, for each region and item type. Click a row or column to isolate it."),
 ]),
 ("04 What", [
   t("banner-what", "About this tab", "[sales] [item type]", 0, 0, 12, 3),
   t("what-money-sankey", "Where the money flows", "[sales] [region] [item type]", 0, 3, 12, 7, "Sales flow from region to family to item type. Hover a flow; click a node to isolate its flows."),
   t("what-sunburst", "Sales by family, item type and product", "[sales] [item type] [product]", 0, 10, 6, 7, "Click a wedge to zoom in; click the centre to zoom out."),
   t("what-chord", "Region to family chord", "[sales] [region] [item type]", 6, 10, 6, 7, "Hover a ribbon. Click a family arc to open its item types."),
   t("what-treemap-drill", "Sales treemap with drill-down", "[sales] [item type] [product]", 0, 17, 6, 7, "Click a rectangle to zoom in: family, item type, product."),
   t("what-radial-bars", "Item types as radial bars", "[sales] [item type] [product]", 6, 17, 6, 7, "Click a bar for that item type's top products."),
   t("what-marimekko", "Region by family Marimekko", "[sales] [region] [item type]", 0, 24, 6, 7, "Column width is the region's sales. Click a column to split it into item types."),
   t("what-pareto", "Products that make 80% of sales", PROD, 6, 24, 6, 7, "Ranked bars and the cumulative line. Pick an item type; click a bar for its detail."),
   t("what-price-volume", "Price against volume by item type", "[sales] [quantity purchased] [item type]", 0, 31, 8, 6, "Bubble area is sales, colour is family. The lines mark the average price and the median units."),
   t("what-quadrant-guide", "How to read price against volume", "[sales] [quantity purchased] [item type]", 8, 31, 4, 6, "The four quadrants of the chart beside it. Click one to list them."),
 ]),
 ("05 When", [
   t("banner-when", "About this tab", "[sales] [date].monthly", 0, 0, 12, 3),
   t("when-seasonal-radial", "Monthly sales around the year", "[sales] [date].monthly", 0, 3, 6, 7, "Twelve months on a clock, one line per year. Click a year in the key to isolate it."),
   t("when-ridgeline", "Sales ridgeline by year", "[sales] [date].monthly", 6, 3, 6, 7, "One ridge per year. Click a ridge to open its months."),
   t("when-calendar-heatmap", "Sales, units and price by month", M, 0, 10, 12, 6, "Year by month. Click a year to open its twelve months."),
   t("when-family-stream", "Sales by product family, by quarter", "[sales] [item type] [date].quarterly", 0, 16, 12, 6, "Stream, stacked or 100 percent. Click a family to open its item types."),
   t("when-bubble-motion", "Item types in motion by quarter", "[sales] [quantity purchased] [item type] [date].quarterly", 0, 22, 12, 7, "Press Play or scrub the quarters. Click a bubble to follow it."),
   t("when-rank-bump", "Item type rank by year", "[sales] [item type] [date].yearly", 0, 29, 12, 6, "Rank or sales by year. 2021 and the latest year are part years. Click a line to pin it."),
 ]),
 ("06 Who", [
   t("banner-who", "About this tab", "[sales] [store]", 0, 0, 12, 3),
   t("who-store-race", "Store race: cumulative sales by quarter", QTR_ST, 0, 3, 12, 7, "Press Play or scrub the quarters. Click a store to follow it."),
   t("who-product-table", "Products by sales", PROD, 0, 10, 12, 7, "All products. Sort, search, filter by family; click a row for its detail."),
   t("who-item-waffle", "Family waffle: share of sales or units", "[sales] [quantity purchased] [item type]", 0, 17, 6, 6, "One hundred squares. Toggle sales and units; click a family to list its item types."),
   t("who-region-profile", "Region profiles: family mix against average", "[sales] [region] [item type]", 6, 17, 6, 6, "Each region's family shares against the all-region average. Click a region to enlarge it."),
   t("who-store-parallel", "Stores across five measures", "[sales] [quantity purchased] [store] [date].quarterly", 0, 23, 12, 6, "Drag an axis to filter stores; click a line to pin it."),
   t("who-product-beeswarm", "Every product by price per unit", PROD, 0, 29, 12, 7, "Dot area is sales. Filter by family; click a dot for its card."),
 ]),
 ("07 Next", [
   t("banner-next", "About this tab", M, 0, 0, 12, 3),
   t("next-growth-matrix", "Share of sales against price per unit", "[sales] [quantity purchased] [item type] [date].quarterly", 0, 3, 8, 7, "Item types as bubbles. Year-to-date change is flat for every type, so share and price are what differ."),
   t("next-action-list", "Moves the numbers support", "[sales] [quantity purchased] [item type] [date].quarterly", 8, 3, 4, 7, "Generated from the rows. Click a move to see its evidence."),
   t("next-run-rate", "Year-end outlook", "[sales] [date].monthly", 0, 10, 6, 6, "Actual to date, then two labelled projections. Pick a scenario."),
   t("next-what-if", "What if the rest of the year moves", M, 6, 10, 6, 6, "Drag the sliders to reshape the remaining months."),
   t("next-stores-at-risk", "Stores below last year", QTR_ST, 0, 16, 12, 6, "Move the threshold to flag stores below it. Click a row to pin it."),
 ]),
]
spec = {
  "liveboard": {"guid": "2babcffd-23bc-4d51-9700-63083c5afe85", "name": "Amuzing chart samples",
            "description": "Custom charts on the (Sample) Retail - Apparel model, arranged as one argument: where the money is, what sells, when, and what to do next.",
            "model": MODEL},
  "filters": [{"column": "date", "label": "Date", "applyToNarrative": False},
              {"column": "region", "label": "Region", "applyToNarrative": False},
              {"column": "item type", "label": "Item type", "applyToNarrative": False}],
  "style": [{"name": "lb_border_type", "value": "CURVED"}, {"name": "hide_group_title", "value": "false"}, {"name": "hide_tile_description", "value": "false"}],
  "tabs": [{"name": n, "tiles": tl} for n, tl in TABS],
}
out = os.path.join(HERE, "liveboard.spec.json")
json.dump(spec, open(out, "w"), separators=(",", ":"))
open(out, "a").write("\n")
print(sum(len(tl) for _, tl in TABS), "tiles in", len(TABS), "tabs")
