# Synthetic Domo Sample Set — for Domo → ThoughtSpot TML Conversion Testing

These 7 files simulate a small, self-consistent Domo environment: two datasets, a
shared calculated-field layer, three cards, and one page (Liveboard) that ties them
together. IDs are cross-referenced across files exactly as they would be in a real
Domo instance, so you can test end-to-end conversion logic, not just isolated objects.

## Files and what they represent

| File | Domo concept | ThoughtSpot TML target |
|---|---|---|
| `domo_table_sales_transactions.json` | Dataset (table) | Worksheet source table |
| `domo_table_customer_master.json` | Dataset (table) | Worksheet source table (for join testing) |
| `domo_model_beastmodes.json` | Beast Modes (calculated fields) | Worksheet formulas |
| `domo_card_500000001_kpi_net_revenue.json` | KPI Card | Answer (single metric / headline) |
| `domo_card_500000002_bar_revenue_by_region.json` | Bar Chart Card | Answer (bar viz) |
| `domo_card_500000003_table_sales_rep_performance.json` | Table Card | Answer (tabular viz) |
| `domo_liveboard_page_sales_overview.json` | Page | Liveboard |

## How the IDs connect (for your parser to follow)

- Both cards and the page reference `dataSetId` / dataset id `00000001-0000-4000-8000-000000000001` (Sales Transactions).
- All three Beast Modes in `domo_model_beastmodes.json` also reference that same `dataSourceId`.
- The three card `urn` values (`500000001`, `500000002`, `500000003`) are exactly the `cardIds` listed in the page file — this is how Domo links a Page to its Cards, and it's the relationship your Skill needs to resolve first before it can build a Liveboard's layout.
- `calculatedFields` inside each card duplicate the Beast Mode formulas by name — in real Domo, a card can either reference a global Beast Mode or redefine the formula locally; both patterns are represented here so your Skill can handle either.

## Suggested conversion logic to test against these files

1. **Datasets → Worksheets**: map each `schema.columns` entry to a Worksheet column, preserving `type` (STRING/DATETIME/DOUBLE/LONG → TML equivalent types).
2. **Beast Modes → Worksheet formulas**: convert each `formula` string (Domo's SQL-like syntax) into a TML formula block; the two use similar aggregate-function syntax (`SUM()`, `COUNT(DISTINCT ...)`), so this is mostly a syntax pass-through with light rewriting.
3. **Cards → Answers**: map `chartType` to a ThoughtSpot viz type (`kpi`→headline, `bar`→bar chart, `table`→table), and translate `chartBody.groupBy`/`filters`/`orderBy` into the Answer's query definition.
4. **Page → Liveboard**: iterate `cardIds`, resolve each to its Answer, and assemble them onto one Liveboard in the order listed.

## Extending this set

If you want more coverage, the easy next additions (ask and I'll generate them) are:
- A card with `conditionalFormats` driving TML conditional formatting rules
- A card with a `dateRangeFilter` for relative date handling
- A second page with `collectionIds` populated, to test Domo's card-grouping/tab structure
