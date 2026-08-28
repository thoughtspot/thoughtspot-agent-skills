# Domo → ThoughtSpot Migration Report

**App:** Sales Overview  
**Source mode:** offline  
**Provenance:** data model = **SOURCE** (Domo dataset schemas) · charts = **INFERRED** from the dashboard PDF (verify)

## Executive summary

- **Migration complexity:** Low–Medium
- **Automation %:** 56%  |  **Manual %:** 44%
- **Estimated effort:** ~0.5–1 engineer-day
- **Risk score:** Medium — **2 source file(s) could not be read in full — this conversion is incomplete**; 1 item(s) flagged NEEDS REVIEW; 3 item(s) Approximated — mapped with a caveat, each listed under Manual review.

## Inventory

- **Tables:** 2  |  **Columns:** 16
- **Relationships:** 1  |  **Measures (Beast Modes):** 3
- **Pages:** 1  |  **Visuals:** 3

## Modernization

**Dashboards eliminated:** none — the 1 Domo page(s) map to 1 Liveboard(s).

**Search opportunities:** the 1 KPI card(s) are re-askable on demand via Search; kept as tiles for the overview band.

**Spotter opportunities:** stand up Spotter on the model for conversational "explain <measure> by <dimension>" breakdowns that replace static charts.

**Semantic improvements:**
- Promoted 3 Domo Beast Mode(s) to reusable model measures.
- Disambiguated 1 display-name collision(s); join keys stay physically present on both tables so joins resolve.
- Confirm each join is MANY_TO_ONE from the fact so additive measures do not fan out across the star.

## Summary by object type

| Object type | In Domo | Migrated | Approximated | Needs review | Skipped |
|---|---|---|---|---|---|
| Datasets → Tables | 2 | 2 | 0 | 0 | 0 |
| Joins | 1 | 0 | 0 | 1 | 0 |
| Beast Modes → Formulas | 3 | 3 | 0 | 0 | 0 |
| Cards → Answers | 3 | 0 | 3 | 0 | 0 |
| Pages → Liveboards | 1 | 1 | 0 | 0 | 0 |

## Data model

### Tables

| Domo dataset | ThoughtSpot table | Columns | Status |
|---|---|---|---|
| Customer Master | Customer Master | 6 | Migrated |
| Sample Sales Transactions | Sample Sales Transactions | 10 | Migrated |

### Relationships → joins

| Relationship | On | Status | Note |
|---|---|---|---|
| Sample Sales Transactions ↔ Customer Master | `Customer ID` | NEEDS REVIEW | inferred by shared column name |

### Beast Modes → Formulas

| Name | Domo formula | ThoughtSpot formula | Status |
|---|---|---|---|
| Net Revenue | `SUM(`Revenue`) - SUM(`Discount`)` | `sum([Revenue]) - sum([Discount])` | Migrated |
| Avg Order Value | `SUM(`Revenue`) / COUNT(DISTINCT `Transaction ID`)` | `sum([Revenue]) / unique count([Transaction ID])` | Migrated |
| Discount Rate % | `(SUM(`Discount`) / SUM(`Revenue`)) * 100` | `(sum([Discount]) / sum([Revenue])) * 100` | Migrated |

## Cards → answers & liveboard

| Card | ThoughtSpot chart | Status | Note |
|---|---|---|---|
| Net Revenue | KPI | Approximated | not carried onto the Answer — rebuild by hand: card filter(s) (Transaction Date LAST_90_DAYS); quick filter(s) (Region); conditional formatting (1 rule(s)) |
| Revenue by Region | BAR | Approximated | not carried onto the Answer — rebuild by hand: sort (Total Revenue DESCENDING — Domo alias); card filter(s) (Transaction Date LAST_90_DAYS); quick filter(s) (Product Category) |
| Sales Rep Performance | TABLE | Approximated | not carried onto the Answer — rebuild by hand: sort (Net Revenue DESCENDING — Domo alias); card filter(s) (Transaction Date LAST_90_DAYS); number format on Net Revenue, Avg Order Value, Discount Rate %; non-SUM aggregation (Avg Order Value=AVG, Discount Rate %=AVG) — the Answer falls back to the Model default |

Assembled onto Liveboard **Sales Overview** (3 tiles).

### Renamed to keep Model names unique

A ThoughtSpot Model exposes one flat namespace, so a name used twice in Domo has to be disambiguated. The physical column is unchanged — only the display name.

- **Column** `Customer ID` → `Customer ID (Customer Master)` (table Customer Master) — the name is already taken in the Model

## Manual review (do these in ThoughtSpot)

- **Source not fully read** — unrecognized object in magic_etl_olist.json. Anything in that file is missing from this conversion.
- **Source not fully read** — unrecognized object in magic_etl_olist.json. Anything in that file is missing from this conversion.
- **Join** Sample Sales Transactions ↔ Customer Master on `Customer ID` (NEEDS REVIEW) — inferred by shared column name. Confirm MANY_TO_ONE from the fact.
- **Card** `Net Revenue` (kpi, Approximated) — not carried onto the Answer — rebuild by hand: card filter(s) (Transaction Date LAST_90_DAYS); quick filter(s) (Region); conditional formatting (1 rule(s))
- **Card** `Revenue by Region` (bar, Approximated) — not carried onto the Answer — rebuild by hand: sort (Total Revenue DESCENDING — Domo alias); card filter(s) (Transaction Date LAST_90_DAYS); quick filter(s) (Product Category)
- **Card** `Sales Rep Performance` (table, Approximated) — not carried onto the Answer — rebuild by hand: sort (Net Revenue DESCENDING — Domo alias); card filter(s) (Transaction Date LAST_90_DAYS); number format on Net Revenue, Avg Order Value, Discount Rate %; non-SUM aggregation (Avg Order Value=AVG, Discount Rate %=AVG) — the Answer falls back to the Model default

## Verification checklist

- Pick one known total in Domo and confirm the identical number in ThoughtSpot (via Search / searchdata).
- Slice a measure by a dimension across each join and confirm it does not fan out (validates the join cardinality).
- Rebuild each flagged card and confirm it matches the source dashboard tile — including its sort, filters and number formats, which are not carried across.
- Confirm any source filters became Liveboard filters and slice every tile.

## ThoughtSpot Modernization Scorecard

| Category | Score | Recommendation |
|---|---|---|
| Semantic Model | 80/100 | Confirm MANY_TO_ONE cardinalities to lock the grain. |
| Search Readiness | 90/100 | Friendly names + reusable measures in place. |
| Spotter Readiness | 85/100 | Stand up Spotter on the model to replace static breakdown charts. |
| Liveboards | 66/100 | 1 page(s) → 1 Liveboard(s); rebuild the flagged tile(s) to reach 100. |
| AI Readiness | 80/100 | Add a Monitor/Alert on a key measure and enable Spotter. |
