# Qlik → ThoughtSpot migration report

**Source:** Sales App — *Sales Performance Dashboard* &nbsp;&nbsp; **Generated:** 2026-07-17
**Target:** ps-internal.thoughtspot.cloud / connection `QlikMig_CaseStudy_SF` / `SALES_DW.STAR_SCHEMA`
**Provenance:** data model = **SOURCE** (read from the warehouse) · charts = **INFERRED** from the dashboard PDF (verify)

## Executive summary

- **Migration complexity:** Low–Medium
- **Automation %:** 85% &nbsp;|&nbsp; **Manual %:** 15%
- **Estimated effort:** 0.5–1 engineer-day
- **Risk score:** Low — clean single-fact conformed star schema. Open items are cosmetic/semantic, not structural: one ambiguous duplicate "by Region" bar in the PDF, a title/grain mismatch on *Quarterly Sales by Category*, the point-layer map needing geo config, and the Profit Margin formula whose original Qlik expression was not recoverable from a static PDF.

## Inventory

- **Tables:** 6 &nbsp;|&nbsp; **Columns:** 53
- **Relationships:** 6 &nbsp;|&nbsp; **Measures:** 4 (3 additive aggregations + 1 ratio formula)
- **Sheets:** 1 &nbsp;|&nbsp; **Visuals:** 13 (+ 1 note tile, + filters)

## Modernization

**Dashboards eliminated:** none — the single Qlik sheet is retained as one Liveboard.

**Dashboards merged:** none.

**Search opportunities:** the three KPI single-value cards (Sales / Profit / Quantity) are re-askable on demand via Search; kept as permanent tiles for the executive overview band.

**Spotter opportunities:** "explain sales/profit variance by Region / Category / Customer Segment / Brand" → Spotter conversational breakdown on the model, replacing several static bars.

**Semantic improvements:**
- Renamed physical columns to friendly business names (`SALESAMOUNT` → *Sales Amount*, `PROFITAMOUNT` → *Profit*, `CUSTOMERSEGMENT` → *Customer Segment*, `MONTHNAME` → *Month Name*, …).
- Promoted inline Qlik `Sum()` chart expressions to reusable model measures; rebuilt **Profit Margin** as a single model formula instead of a per-chart expression.
- All joins are `MANY_TO_ONE` from the fact so grain is preserved and additive measures do not fan out.
- Carried the Qlik `date_test` narrative into a real ThoughtSpot **Date filter**, and the REGION listbox into a **Region filter** on the Liveboard.
- Added the source dashboard's descriptive **note tile** ("Sales Performance Overview") as a first-class Liveboard note.

## Summary by object type

| Object type | In Qlik | Migrated | Approximated | Needs review | Skipped |
|---|---|---|---|---|---|
| Tables | 6 | 6 | 0 | 0 | 0 |
| Relationships | 6 | 5 | 0 | 1 | 0 |
| Measures | 4 | 3 | 1 | 0 | 0 |
| Visuals | 13 | 10 | 2 | 1 | 0 |
| Sheets | 1 | 1 | 0 | 0 | 0 |

## Data model

### Tables

| Table | Status | Note |
|---|---|---|
| FACTSALES | Migrated | Fact grain; `SALES_DW.STAR_SCHEMA.FACTSALES` → `SPD_FACTSALES`. |
| DIMPRODUCT | Migrated | |
| DIMSTORE | Migrated | Geo-enable Country/Region for the map answer. |
| DIMDATE | Migrated | Year / Month / Quarter date parts native to ThoughtSpot. |
| DIMCUSTOMER | Migrated | |
| DIMSALESPERSON | Migrated | Joined to the fact on `SALESPERSONKEY`; the snowflake link to `DIMSTORE` was not carried (see Relationships). |

### Relationships → joins

| Relationship | Status | Note |
|---|---|---|
| FACTSALES[DATEKEY] → DIMDATE | Migrated | INNER, MANY_TO_ONE. |
| FACTSALES[PRODUCTKEY] → DIMPRODUCT | Migrated | INNER, MANY_TO_ONE. |
| FACTSALES[CUSTOMERKEY] → DIMCUSTOMER | Migrated | INNER, MANY_TO_ONE. |
| FACTSALES[STOREKEY] → DIMSTORE | Migrated | INNER, MANY_TO_ONE. |
| FACTSALES[SALESPERSONKEY] → DIMSALESPERSON | Migrated | INNER, MANY_TO_ONE. |
| DIMSALESPERSON[STOREKEY] → DIMSTORE | NEEDS REVIEW | Snowflake link visible in the Qlik data-model diagram but not carried into the star model (all store analysis routes through the fact). Add only if a salesperson→store path is needed; confirm it doesn't fan store-level measures. |

### Measures → formulas

| Measure | Complexity | Qlik expression | ThoughtSpot formula / column | Confidence | Status | Note |
|---|---|---|---|---|---|---|
| Sum(SALESAMOUNT) | Simple | `Sum(SALESAMOUNT)` | `sum([SPD_FACTSALES::SALESAMOUNT])` → *Total Sales Amount* | 95 | Migrated | Verified **63.34M** vs PDF. |
| Sum(PROFITAMOUNT) | Simple | `Sum(PROFITAMOUNT)` | `sum([SPD_FACTSALES::PROFITAMOUNT])` → *Total Profit* | 95 | Migrated | Verified **38.06M**. |
| Sum(QUANTITY) | Simple | `Sum(QUANTITY)` | `sum([SPD_FACTSALES::QUANTITY])` → *Total Quantity* | 95 | Migrated | Verified **236.2k**. |
| Profit Margin | Moderate | *(not recoverable from PDF)* | `sum([…PROFITAMOUNT]) / sum([…SALESAMOUNT]) * 100` | 70 | Approximated | Original Qlik expression not visible in the static export; rebuilt as margin %. Confirm the intended definition (profit ÷ sales vs profit ÷ cost) and the ×100 scaling. |

## Report / visuals → answers & liveboards

### Sheet → liveboard

| Sheet | Visual | ThoughtSpot chart | Status | Note |
|---|---|---|---|---|
| Sales Performance Dashboard | Note: Sales Performance Overview | NOTE_TILE | Migrated | Added as a Liveboard note tile with the source overview text (top-left). |
| Sales Performance Dashboard | KPI: Sum(SALESAMOUNT) | KPI | Migrated | |
| Sales Performance Dashboard | KPI: Sum(PROFITAMOUNT) | KPI | Migrated | |
| Sales Performance Dashboard | KPI: Sum(QUANTITY) | KPI | Migrated | |
| Sales Performance Dashboard | Monthly Sales and Profit Totals | LINE | Migrated | Sales + Profit over time (Year axis). |
| Sales Performance Dashboard | Quarterly Sales by Category | LINE | Approximated | The PDF chart actually plots `Sum(QUANTITY)` over date, not quarterly-by-category. Migrated as *Quantity Over Time*; confirm intended dimension/grain. |
| Sales Performance Dashboard | Sales by Country (map) | GEO_BUBBLE | Approximated | Qlik point-layer map → geo bubble; requires Country to be geo-recognized (set geo config on the column). |
| Sales Performance Dashboard | Sales and Profit by Region | COLUMN | Migrated | Grouped Sales + Profit by Region. |
| Sales Performance Dashboard | Second "by Region" bar | COLUMN | NEEDS REVIEW | Two near-equal bars per region; both axis labels truncate to `Sum(SALESAM…` in the export so the second measure is unreadable. Not reproduced — confirm whether it is a distinct measure (e.g. Sales vs Cost) or a duplicate of *Sales and Profit by Region*. |
| Sales Performance Dashboard | Sales by Brand and Category | PIVOT_TABLE | Migrated | Brand × Category matrix of Sales Amount. |
| Sales Performance Dashboard | Profit Margin by Category | COLUMN | Migrated | Uses the rebuilt Profit Margin formula (see Measures). |
| Sales Performance Dashboard | Sales by Customer Segment | PIE | Migrated | Wholesale / Retail / Corporate = 42.3 / 34.0 / 23.7% — matches PDF. |
| Sales Performance Dashboard | Percentage of Sales by Brand | BAR | Migrated | Share-of-sales by brand. |
| Sales Performance Dashboard | Filters: REGION, BRAND, CATEGORY, SUBCATEGORY | (filters) | Migrated | REGION + Date became Liveboard filters; brand/category/subcategory drive the pivot. |

### Sheet → liveboard decision

| Sheet | Decision | Liveboard | Status |
|---|---|---|---|
| Sales Performance Dashboard | Keep | Sales Performance Dashboard (Migrated) | Migrated |

## Manual review (do these in ThoughtSpot)

- **Second "by Region" bar chart (NEEDS REVIEW)** — the PDF shows a second grouped bar over Region with two near-equal, near-identically-labelled series. The second measure is unreadable in the static export. Confirm whether it is Sales vs Cost (or similar) or a duplicate of *Sales and Profit by Region*; add the tile once identified.
- **Quarterly Sales by Category (Approximated)** — title says "by Category" but the plotted content is `Sum(QUANTITY)` over date. Migrated as *Quantity Over Time*. Decide whether it should break out by Category and/or aggregate to Quarter.
- **Sales by Country map (Approximated)** — set geo config on the Country column so the point/bubble layer renders; the source data appears to carry a single generic country value.
- **Profit Margin formula (Approximated)** — the Qlik expression was not visible in the PDF; validate `sum(profit)/sum(sales)*100` against the source and confirm the ×100 scaling.
- **DIMSALESPERSON → DIMSTORE snowflake join (NEEDS REVIEW)** — present in the Qlik model diagram, not carried into the star. Add only if salesperson→store analysis is required.
- **`date_test` parameter (Approximated)** — the note text references a Qlik `date_test` parameter, which has no ThoughtSpot equivalent; time filtering is provided via the Liveboard **Date filter**.

## Verification checklist

- [x] Pick one known total in Qlik and confirm the SAME number in ThoughtSpot — **Sales 63.34M / Profit 38.06M / Quantity 236.2k** all match (via `searchdata`).
- [x] Spot-check the customer-segment split — Wholesale 42.3% / Retail 34.0% / Corporate 23.7% match the PDF pie.
- [ ] Confirm the note tile renders with the overview text (top-left of the Liveboard).
- [ ] Confirm Region + Date filters slice every tile.
- [ ] Geo-enable Country and confirm the map renders.

## ThoughtSpot Modernization Scorecard

| Category | Score | Recommendation |
|---|---|---|
| Semantic Model | 90/100 | Clean conformed single-fact star. Decide on the salesperson→store snowflake link; keep joins MANY_TO_ONE. |
| Search Readiness | 90/100 | Friendly names + reusable measures are in place; finish by geo-enabling Country/Region. |
| Spotter Readiness | 85/100 | Stand up Spotter on the model for "explain variance by Region/Category/Segment/Brand" to replace static breakdown bars. |
| Liveboards | 90/100 | Single sheet → one Liveboard with note tile + Region/Date filters; resolve the duplicate region bar to reach 100. |
| AI Readiness | 80/100 | Add a Monitor/Alert on Sales/Profit and enable Spotter to replace "open the dashboard every morning". |
