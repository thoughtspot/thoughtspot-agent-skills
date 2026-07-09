# Worked Example — ThoughtSpot Model → Databricks Metric Views

End-to-end conversion of the `Dunder Mifflin Sales & Inventory` Model to two
Databricks Metric Views — `dunder_mifflin_sales_mv` (sales) and
`dunder_mifflin_inventory_mv` (inventory). Covers multi-fact splitting, nested
v1.1 joins (not flattened views), LOD dimension window functions, semi-additive
snapshot measures, MEASURE()/ANY_VALUE() cross-references, period-over-period
windows with offset, conditional aggregates via FILTER (WHERE), v1.1 rich
metadata, and flattened views as a fallback.

Verified against live Databricks instance (`dbc-3472b2da-8a4e.cloud.databricks.com`,
warehouse `AGENT_SKILLS_TESTING` Preview channel) on 2026-05-25.

---

## Source — ThoughtSpot Model TML (key sections)

```yaml
guid: dc1847dc-72a7-4f13-adaf-3ace7c8e0d95
model:
  name: Dunder Mifflin Sales & Inventory
  description: "The Dunder Mifflin Sales & Inventory worksheet provides a comprehensive
    overview of sales transactions, inventory snapshots, and product categorization."
  model_tables:
  - name: DM_ORDER_DETAIL
    joins:
    - with: DM_ORDER
      referencing_join: DM_ORDER_DETAIL_to_DM_ORDER
    - with: DM_PRODUCT
      referencing_join: DM_ORDER_DETAIL_to_DM_PRODUCT
  - name: DM_ORDER
    joins:
    - with: DM_CUSTOMER
      referencing_join: DM_ORDER_to_DM_CUSTOMER
    - with: DM_DATE_DIM
      referencing_join: DM_ORDER_to_DM_DATE_DIM
    - with: DM_EMPLOYEE
      referencing_join: DM_ORDER_to_DM_EMPLOYEE
  - name: DM_INVENTORY
    joins:
    - with: DM_DATE_DIM
      referencing_join: DM_INVENTORY_to_DM_DATE_DIM
    - with: DM_PRODUCT
      referencing_join: DM_INVENTORY_to_DM_PRODUCT
  - name: DM_PRODUCT
    joins:
    - with: DM_CATEGORY
      referencing_join: DM_PRODUCT_to_DM_CATEGORY
  - name: DM_CUSTOMER
  - name: DM_EMPLOYEE
  - name: DM_DATE_DIM
  - name: DM_CATEGORY
  columns:
  - name: Order Id
    column_id: DM_ORDER::ORDER_ID
    properties:
      column_type: ATTRIBUTE
      description: "Identifier for one order header. Each order can have multiple lines."
  - name: Order Date
    column_id: DM_ORDER::ORDER_DATE
    properties:
      column_type: ATTRIBUTE
      description: "Date the order was placed."
      synonyms:
      - order placed
      - purchase date
  - name: Product Name
    column_id: DM_PRODUCT::PRODUCT_NAME
    properties:
      column_type: ATTRIBUTE
      description: "Display name of the product."
      synonyms:
      - product
      - item
  - name: Product Category
    column_id: DM_CATEGORY::CATEGORY_NAME
    properties:
      column_type: ATTRIBUTE
      description: "Category name the product belongs to."
      synonyms:
      - category
      - product line
  - name: Customer Name
    column_id: DM_CUSTOMER::COMPANY_NAME
    properties:
      column_type: ATTRIBUTE
      description: "The customer display name."
      synonyms:
      - customer
      - client
      - buyer
  - name: Customer State
    column_id: DM_CUSTOMER::STATE
    properties:
      column_type: ATTRIBUTE
      description: "The customer state of residence."
  - name: Customer Zipcode
    column_id: DM_CUSTOMER::ZIPCODE
    properties:
      column_type: ATTRIBUTE
      description: "Postal code on the customer billing address."
      synonyms:
      - zip code
      - postal code
  - name: Discount
    column_id: DM_ORDER_DETAIL::DISCOUNT
    properties:
      column_type: ATTRIBUTE
      description: "Per-line discount recorded on the order detail."
      synonyms:
      - promo
      - discount amount
  - name: Employee
    formula_id: formula_Employee
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - sales rep
      - rep
      - salesperson
  - name: Transaction Date
    column_id: DM_DATE_DIM::DATE_VALUE
    properties:
      column_type: ATTRIBUTE
      description: "Date dimension key."
      synonyms:
      - date
  - name: Balance Date
    column_id: DM_INVENTORY::BALANCE_DATE
    properties:
      column_type: ATTRIBUTE
      description: "Date the inventory balance was snapshotted."
  - name: Revenue
    column_id: DM_ORDER_DETAIL::LINE_TOTAL
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Dollar value of an order-line item."
      synonyms:
      - sales
      - total sales
      - amount
      ai_context: Total line-item revenue for financial analysis.
  - name: Quantity
    column_id: DM_ORDER_DETAIL::QUANTITY
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Number of units sold on one order line."
      synonyms:
      - units
      - units sold
  - name: Unit Price
    column_id: DM_ORDER_DETAIL::UNIT_PRICE
    properties:
      column_type: MEASURE
      aggregation: AVERAGE
      description: "Unit price recorded on the order-line item."
      synonyms:
      - price
      - list price
  - name: "# Employees"
    formula_id: "formula_# Employees"
    properties:
      column_type: MEASURE
      aggregation: SUM
      synonyms:
      - employee count
      - rep count
  - name: Category Quantity
    formula_id: formula_Category Quantity
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Total units sold for a product category."
  - name: Category Contribution Ratio
    formula_id: formula_Category Contribution Ratio
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Product share of category total units."
  - name: Monthly Revenue
    formula_id: formula_Monthly Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Prior Month Revenue
    formula_id: formula_Prior Month Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Inventory Balance
    formula_id: formula_Inventory Balance
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Semi-additive inventory snapshot."
      synonyms:
      - stock
      - stock on hand
      - current inventory
  - name: Active Customers
    formula_id: formula_Active Customers
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - id: formula_Employee
    name: Employee
    expr: "concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )"
  - id: "formula_# Employees"
    name: "# Employees"
    expr: "count ( [DM_ORDER::EMPLOYEE_ID] )"
  - id: formula_Category Quantity
    name: Category Quantity
    expr: "group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) )"
  - id: formula_Category Contribution Ratio
    name: Category Contribution Ratio
    expr: "safe_divide ( [Quantity] , [Category Quantity] )"
  - id: formula_Monthly Revenue
    name: Monthly Revenue
    expr: "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = 0 , [DM_ORDER_DETAIL::LINE_TOTAL] )"
  - id: formula_Prior Month Revenue
    name: Prior Month Revenue
    expr: "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = -1 , [DM_ORDER_DETAIL::LINE_TOTAL] )"
  - id: formula_Inventory Balance
    name: Inventory Balance
    expr: "last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )"
  - id: formula_Active Customers
    name: Active Customers
    expr: "unique_count_if ( [DM_ORDER_DETAIL::LINE_TOTAL] > 0 , [DM_CUSTOMER::CUSTOMER_ID] )"
```

All 8 associated Table TMLs resolve to `db: agent_skills, schema: dunder_mifflin`.

---

## Resolve Physical Table Names and Joins

**Physical table map** (from Table TML exports):

| Table | db (catalog) | schema | db_table |
|---|---|---|---|
| DM_ORDER_DETAIL | agent_skills | dunder_mifflin | DM_ORDER_DETAIL |
| DM_ORDER | agent_skills | dunder_mifflin | DM_ORDER |
| DM_INVENTORY | agent_skills | dunder_mifflin | DM_INVENTORY |
| DM_PRODUCT | agent_skills | dunder_mifflin | DM_PRODUCT |
| DM_CATEGORY | agent_skills | dunder_mifflin | DM_CATEGORY |
| DM_CUSTOMER | agent_skills | dunder_mifflin | DM_CUSTOMER |
| DM_EMPLOYEE | agent_skills | dunder_mifflin | DM_EMPLOYEE |
| DM_DATE_DIM | agent_skills | dunder_mifflin | DM_DATE_DIM |

**Resolve `referencing_join` conditions** from Table TML `joins_with[]`:

| Join Name | On Condition | Left Table | Right Table |
|---|---|---|---|
| DM_ORDER_DETAIL_to_DM_ORDER | `[DM_ORDER_DETAIL::ORDER_ID] = [DM_ORDER::ORDER_ID]` | DM_ORDER_DETAIL | DM_ORDER |
| DM_ORDER_DETAIL_to_DM_PRODUCT | `[DM_ORDER_DETAIL::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]` | DM_ORDER_DETAIL | DM_PRODUCT |
| DM_ORDER_to_DM_CUSTOMER | `[DM_ORDER::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]` | DM_ORDER | DM_CUSTOMER |
| DM_ORDER_to_DM_DATE_DIM | `[DM_ORDER::ORDER_DATE] = [DM_DATE_DIM::DATE_VALUE]` | DM_ORDER | DM_DATE_DIM |
| DM_ORDER_to_DM_EMPLOYEE | `[DM_ORDER::EMPLOYEE_ID] = [DM_EMPLOYEE::EMPLOYEE_ID]` | DM_ORDER | DM_EMPLOYEE |
| DM_PRODUCT_to_DM_CATEGORY | `[DM_PRODUCT::CATEGORY_ID] = [DM_CATEGORY::CATEGORY_ID]` | DM_PRODUCT | DM_CATEGORY |
| DM_INVENTORY_to_DM_DATE_DIM | `[DM_INVENTORY::BALANCE_DATE] = [DM_DATE_DIM::DATE_VALUE]` | DM_INVENTORY | DM_DATE_DIM |
| DM_INVENTORY_to_DM_PRODUCT | `[DM_INVENTORY::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]` | DM_INVENTORY | DM_PRODUCT |

All 8 joins are in scope — both sides appear in `model_tables`.

---

## Split Decision — Multi-Fact → Two Metric Views

The model has two fact tables with MEASURE columns:

| Fact Table | Measure Columns |
|---|---|
| DM_ORDER_DETAIL | Revenue (SUM), Quantity (SUM), Unit Price (AVG) + formula measures |
| DM_INVENTORY | Inventory Balance (semi-additive formula measure) |

Databricks Metric Views have a single `source:` — one fact table per MV. This model
must be split into two independent Metric Views:

1. **`dunder_mifflin_sales_mv`** — `source: DM_ORDER_DETAIL`, with nested joins to
   DM_ORDER (and under it: DM_CUSTOMER, DM_EMPLOYEE, DM_DATE_DIM) and DM_PRODUCT
   (and under it: DM_CATEGORY)
2. **`dunder_mifflin_inventory_mv`** — `source: DM_INVENTORY`, with nested joins to
   DM_DATE_DIM and DM_PRODUCT (and under it: DM_CATEGORY)

Shared dimension tables (DM_PRODUCT, DM_CATEGORY, DM_DATE_DIM) appear in both MVs
with the same join structure.

---

## Build Join Hierarchies

### MV 1 — Sales: Join tree from DM_ORDER_DETAIL

```
DM_ORDER_DETAIL (source)
  |-- orders: DM_ORDER (source.ORDER_ID = orders.ORDER_ID)
  |     |-- customers: DM_CUSTOMER (orders.CUSTOMER_ID = customers.CUSTOMER_ID)
  |     |-- employees: DM_EMPLOYEE (orders.EMPLOYEE_ID = employees.EMPLOYEE_ID)
  |     |-- dates: DM_DATE_DIM (orders.ORDER_DATE = dates.DATE_VALUE)
  |-- products: DM_PRODUCT (source.PRODUCT_ID = products.PRODUCT_ID)
        |-- category: DM_CATEGORY (products.CATEGORY_ID = category.CATEGORY_ID)
```

DM_ORDER joins directly from `source` (DM_ORDER_DETAIL). DM_CUSTOMER, DM_EMPLOYEE,
and DM_DATE_DIM are **nested under** the `orders` join — not at sibling level with
`source`. This is critical: placing them at the top level with
`"on": source.CUSTOMER_ID = customers.CUSTOMER_ID` fails with `UNRESOLVED_COLUMN`
because the FK columns (`CUSTOMER_ID`, `EMPLOYEE_ID`, `ORDER_DATE`) live on DM_ORDER,
not on DM_ORDER_DETAIL.

### MV 2 — Inventory: Join tree from DM_INVENTORY

```
DM_INVENTORY (source)
  |-- dates: DM_DATE_DIM (source.BALANCE_DATE = dates.DATE_VALUE)
  |-- products: DM_PRODUCT (source.PRODUCT_ID = products.PRODUCT_ID)
        |-- category: DM_CATEGORY (products.CATEGORY_ID = category.CATEGORY_ID)
```

Simpler tree — DM_DATE_DIM and DM_PRODUCT both join directly from `source`.

**Column reference dot-paths (Sales MV):**
- Fact table columns: `source.LINE_TOTAL`, `source.QUANTITY`
- First-level join: `orders.ORDER_ID`, `products.PRODUCT_NAME`
- Nested join: `orders.customers.COMPANY_NAME`, `orders.employees.LAST_NAME`
- Double-nested: `products.category.CATEGORY_NAME`

---

## Translate Formulas

### Formula 1: `Employee` (ATTRIBUTE — computed dimension)

```
concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )
```

Translation:
- `concat(a, b, c)` → `CONCAT(a, b, c)`
- `[DM_EMPLOYEE::LAST_NAME]` → `orders.employees.LAST_NAME` (dot-path through nested joins)
- `[DM_EMPLOYEE::FIRST_NAME]` → `orders.employees.FIRST_NAME`
- Result: `CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)`

Translatable — add as `dimensions[]` entry (ATTRIBUTE formula).

---

### Formula 2: `# Employees` (MEASURE)

```
count ( [DM_ORDER::EMPLOYEE_ID] )
```

Translation:
- `count(x)` → `COUNT(x)`
- `[DM_ORDER::EMPLOYEE_ID]` → `orders.EMPLOYEE_ID`
- Result: `COUNT(orders.EMPLOYEE_ID)`

Translatable — add as `measures[]` entry.

---

### Formula 3: `Category Quantity` (LOD — group_aggregate)

```
group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) )
```

Translation:
- `group_aggregate(sum(x), {dim}, query_filters())` → `SUM(x) OVER (PARTITION BY dim)`
- `[DM_ORDER_DETAIL::QUANTITY]` → `source.QUANTITY` (fact table column)
- `[DM_CATEGORY::CATEGORY_NAME]` → `products.category.CATEGORY_NAME` (dot-path through nested join)
- Result: `SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)`

Translatable — add as `dimensions[]` entry. LOD results go to **dimensions**, not
measures. Do NOT use `AGGREGATE OVER` — it causes `PARSE_SYNTAX_ERROR`. Do NOT use
`window:` for LOD — `window` requires `semiadditive`.

**Live-verified 2026-07-09 — first time this construct has been queried under any
filter** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A1/A2). On the
ThoughtSpot side, the source `group_aggregate(..., query_filters())` this dimension
was translated from is **CONFIRMED** filter-aware under both a query-level pin and
a model-level `filters:` block. On the emitted Databricks side, the
`SUM(source.QUANTITY) OVER (PARTITION BY ...)` dimension above reproduces that
filter-awareness **only** for a Databricks consumer whose filter is baked into this
MV's own global `filter:` block — a consumer who instead applies an ad hoc
query-time `WHERE` on the MV gets a filter-**blind** `Category Quantity` (the
`WHERE` prunes output rows, not the window's computed value). This is a
Databricks-side asymmetry to flag for the consuming team, not a defect in this
translation.

**A3 follow-up, live-verified 2026-07-09** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A3) — if the source
ThoughtSpot formula had instead used `group_aggregate(sum(x), {dim}, {})` (the
empty-set filter argument) with a model-level `filters:` block mirroring this MV's
`filter:`, the emitted `SUM(x) OVER (PARTITION BY ...)` dimension would reproduce
**both** DBX conditions above — filter-aware for the MV's own global `filter:` AND
filter-blind for an ad hoc query-time `WHERE`. `query_filters()` remains the right
default here (simpler formula, matches the common case); `{}` is the refinement to
reach for only when a consumer specifically needs the query-time-`WHERE`-blind
behavior reproduced.

---

### Formula 4: `Category Contribution Ratio` (MEASURE — cross-references)

```
safe_divide ( [Quantity] , [Category Quantity] )
```

Translation:
- `[Quantity]` is a measure → `MEASURE(quantity)`
- `[Category Quantity]` is an LOD dimension → `ANY_VALUE(category_quantity)`
- `safe_divide(a, b)` → `COALESCE(a / NULLIF(b, 0), 0)` (no `DIV0` in Databricks)
- Result: `COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)`

Translatable — add as `measures[]` entry. Uses `MEASURE()` for measure-to-measure
references and `ANY_VALUE()` for dimension-from-measure references.

**Live-verified 2026-07-09 across query grain** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — this is the exact
`MEASURE(a) / ANY_VALUE(b)` cross-measure ratio pattern Battery B tested: **CONFIRMED**
to compute true ratio-of-sums, cross-platform, at every grain (fine/coarse/total) —
no formula change or grain caveat needed.

---

### Formula 5: `Monthly Revenue` (period filter — current month)

```
sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = 0 , [DM_ORDER_DETAIL::LINE_TOTAL] )
```

> **Corrected 2026-07-09 — approximation caveat (matrix C6, `docs/audit/2026-07-08-dbx-window-claim-matrix.md`).**
> Live testing established that Databricks `window: [{range: current, offset: ...}]`
> is **row-relative** (a `LAG`-style shift relative to each output row's own period),
> not anchored to wall-clock `today()` like the source TS formula above. The
> translation below is the closest available Databricks construct, but it is a
> **lossy approximation**: it is exact only when the query returns a single row for
> the current period (the single-snapshot pattern this example was verified
> against on 2026-05-25); querying `monthly_revenue`/`prior_month_revenue` across a
> multi-month trend would diverge from the wall-clock source formula's intent. Flag
> this caveat when converting a wall-clock `sum_if(diff_months(...), today())`
> formula for a model that will be queried as a trend, not a single KPI snapshot.

Translation:
- Pattern: `sum_if(diff_months([date], today()) = 0, [m])` → period-filter window
- The `order:` dimension must reference a **truncated month** dimension (not raw date)
- Create a computed dimension `order_month` with
  `expr: DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)`
- Inner measure: `SUM(source.LINE_TOTAL)`
- Result:
  ```yaml
  window:
    - order: order_month
      semiadditive: last
      range: current
  ```

Translatable — add as `measures[]` with `window: [{range: current}]`.
The `order:` references a truncated period dimension, distinguishing this from the
semi-additive pattern (which uses a raw date).

---

### Formula 6: `Prior Month Revenue` (period filter — previous month)

```
sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = -1 , [DM_ORDER_DETAIL::LINE_TOTAL] )
```

Translation:
- Pattern: `sum_if(diff_months([date], today()) = -1, [m])` → period-filter with offset
- Same `order: order_month` dimension as Monthly Revenue
- Result:
  ```yaml
  window:
    - order: order_month
      semiadditive: last
      range: current
      offset: -1 month
  ```

Translatable — add as `measures[]` with `window: [{range: current, offset: -1 month}]`.
**Caveat (2026-07-09):** this DBX construct is row-relative, not wall-clock — see
the note under Formula 5 above.

---

### Formula 7: `Inventory Balance` (semi-additive — snapshot metric)

```
last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
```

Translation:
- Pattern: `last_value(sum(m), query_groups(), {date})` → true semi-additive
- The `order:` dimension must reference a **raw date** dimension (not truncated)
- `[DM_INVENTORY::FILLED_INVENTORY]` → `source.FILLED_INVENTORY`
- `[DM_DATE_DIM::DATE_VALUE]` identifies the ordering date → `balance_date` dimension
- Result:
  ```yaml
  window:
    - order: balance_date
      semiadditive: last
      range: current
  ```

Translatable — add as `measures[]` in the Inventory MV. The `order:` references a
raw date dimension, distinguishing this from the period-filter pattern (which uses a
truncated period).

**Live-verified 2026-07-09 under a query-time date-range filter** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — **CONFIRMED
cross-platform**: `last_value` and the equivalent Databricks `window:` measure both
collapse to the last observation *within the filtered range* under a query-level
date-range pin (e.g. "this quarter"), identical values on both platforms including
the single-surviving-row edge case. No formula change needed.

---

### Formula 8: `Active Customers` (conditional aggregate)

```
unique_count_if ( [DM_ORDER_DETAIL::LINE_TOTAL] > 0 , [DM_CUSTOMER::CUSTOMER_ID] )
```

Translation:
- `unique_count_if(cond, x)` → `COUNT(DISTINCT x) FILTER (WHERE cond)`
- `[DM_ORDER_DETAIL::LINE_TOTAL] > 0` → `source.LINE_TOTAL > 0`
- `[DM_CUSTOMER::CUSTOMER_ID]` → `orders.customers.CUSTOMER_ID`
- Result: `COUNT(DISTINCT orders.customers.CUSTOMER_ID) FILTER (WHERE source.LINE_TOTAL > 0)`

Translatable — add as `measures[]` using Databricks `FILTER (WHERE ...)` syntax.

---

## MV 1 — Dunder Mifflin Sales

**Source:** `agent_skills.dunder_mifflin.dm_order_detail`

### Dimensions

| Name | Source | expr | display_name | Notes |
|---|---|---|---|---|
| `order_id` | DM_ORDER::ORDER_ID | `orders.ORDER_ID` | Order Id | Via nested join |
| `order_date` | DM_ORDER::ORDER_DATE | `orders.ORDER_DATE` | Order Date | |
| `order_month` | (computed) | `DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)` | Order Month | Required by period-filter window measures |
| `transaction_date` | DM_DATE_DIM::DATE_VALUE | `orders.dates.DATE_VALUE` | Transaction Date | Dot-path through two joins |
| `product_name` | DM_PRODUCT::PRODUCT_NAME | `products.PRODUCT_NAME` | Product Name | |
| `product_category` | DM_CATEGORY::CATEGORY_NAME | `products.category.CATEGORY_NAME` | Product Category | Nested join dot-path |
| `customer_name` | DM_CUSTOMER::COMPANY_NAME | `orders.customers.COMPANY_NAME` | Customer Name | |
| `customer_state` | DM_CUSTOMER::STATE | `orders.customers.STATE` | Customer State | |
| `customer_zipcode` | DM_CUSTOMER::ZIPCODE | `orders.customers.ZIPCODE` | Customer Zipcode | |
| `employee_name` | formula_Employee | `CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)` | Employee | Computed ATTRIBUTE formula |
| `discount` | DM_ORDER_DETAIL::DISCOUNT | `source.DISCOUNT` | Discount | Fact table ATTRIBUTE |
| `category_quantity` | formula_Category Quantity (LOD) | `SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)` | Category Quantity | LOD → dimension with window function |

### Measures

| Name | Source | expr | display_name | Notes |
|---|---|---|---|---|
| `revenue` | DM_ORDER_DETAIL::LINE_TOTAL | `SUM(source.LINE_TOTAL)` | Revenue | SUM aggregation |
| `quantity` | DM_ORDER_DETAIL::QUANTITY | `SUM(source.QUANTITY)` | Quantity | |
| `unit_price` | DM_ORDER_DETAIL::UNIT_PRICE | `AVG(source.UNIT_PRICE)` | Unit Price | AVERAGE → AVG |
| `employee_count` | formula_# Employees | `COUNT(orders.EMPLOYEE_ID)` | # Employees | |
| `category_contribution_ratio` | formula | `COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)` | Category Contribution Ratio | Cross-refs via MEASURE() and ANY_VALUE() |
| `monthly_revenue` | formula_Monthly Revenue | `SUM(source.LINE_TOTAL)` | Monthly Revenue | Window: `range: current`, `order: order_month` |
| `prior_month_revenue` | formula_Prior Month Revenue | `SUM(source.LINE_TOTAL)` | Prior Month Revenue | Window: `range: current`, `offset: -1 month` |
| `mom_growth_pct` | (derived) | `(MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100` | MoM Growth % | Derived from two period-filter measures. `MEASURE()` cross-references in this ratio are **CONFIRMED** grain-safe (B1, live-verified 2026-07-09, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`); the underlying `monthly_revenue`/`prior_month_revenue` measures still carry the row-relative-vs-wall-clock caveat from C6/C6a (see Formula 5/6 above) |
| `active_customers` | formula_Active Customers | `COUNT(DISTINCT orders.customers.CUSTOMER_ID) FILTER (WHERE source.LINE_TOTAL > 0)` | Active Customers | Conditional aggregate |

### Full YAML Output — Sales MV

```yaml
version: 1.1
comment: >-
  Dunder Mifflin Sales metrics built on normalized star schema — revenue,
  quantity, pricing, period-over-period analysis, and category contribution.
  Converted from ThoughtSpot Model: Dunder Mifflin Sales & Inventory.
source: agent_skills.dunder_mifflin.dm_order_detail

joins:
  - name: orders
    source: agent_skills.dunder_mifflin.dm_order
    "on": source.ORDER_ID = orders.ORDER_ID
    rely: { at_most_one_match: true }
    joins:
      - name: customers
        source: agent_skills.dunder_mifflin.dm_customer
        "on": orders.CUSTOMER_ID = customers.CUSTOMER_ID
        rely: { at_most_one_match: true }
      - name: employees
        source: agent_skills.dunder_mifflin.dm_employee
        "on": orders.EMPLOYEE_ID = employees.EMPLOYEE_ID
        rely: { at_most_one_match: true }
      - name: dates
        source: agent_skills.dunder_mifflin.dm_date_dim
        "on": orders.ORDER_DATE = dates.DATE_VALUE
        rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.PRODUCT_ID = products.PRODUCT_ID
    rely: { at_most_one_match: true }
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }

dimensions:
  - name: order_id
    expr: orders.ORDER_ID
    display_name: 'Order Id'
    comment: 'Identifier for one order header. Each order can have multiple lines.'

  - name: order_date
    expr: orders.ORDER_DATE
    display_name: 'Order Date'
    comment: 'Date the order was placed.'
    synonyms: ['order placed', 'purchase date']

  - name: order_month
    expr: "DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)"
    display_name: 'Order Month'
    comment: 'Truncated month for period-over-period analysis.'

  - name: transaction_date
    expr: orders.dates.DATE_VALUE
    display_name: 'Transaction Date'
    comment: 'Date dimension key.'
    synonyms: ['date']

  - name: product_name
    expr: products.PRODUCT_NAME
    display_name: 'Product Name'
    comment: 'Display name of the product.'
    synonyms: ['product', 'item']

  - name: product_category
    expr: products.category.CATEGORY_NAME
    display_name: 'Product Category'
    comment: 'Category name the product belongs to.'
    synonyms: ['category', 'product line']

  - name: customer_name
    expr: orders.customers.COMPANY_NAME
    display_name: 'Customer Name'
    comment: 'The customer display name.'
    synonyms: ['customer', 'client', 'buyer']

  - name: customer_state
    expr: orders.customers.STATE
    display_name: 'Customer State'
    comment: 'The customer state of residence.'

  - name: customer_zipcode
    expr: orders.customers.ZIPCODE
    display_name: 'Customer Zipcode'
    comment: 'Postal code on the customer billing address.'
    synonyms: ['zip code', 'postal code']

  - name: employee_name
    expr: "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)"
    display_name: 'Employee'
    comment: 'Employee name as Last, First.'
    synonyms: ['sales rep', 'rep', 'salesperson']

  - name: discount
    expr: source.DISCOUNT
    display_name: 'Discount'
    comment: 'Per-line discount recorded on the order detail.'
    synonyms: ['promo', 'discount amount']

  - name: category_quantity
    expr: SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)
    display_name: 'Category Quantity'
    comment: 'Total units sold at category grain, independent of query GROUP BY.'

measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Revenue'
    comment: 'Dollar value of an order-line item.'
    synonyms: ['sales', 'total sales', 'amount']
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }

  - name: quantity
    expr: SUM(source.QUANTITY)
    display_name: 'Quantity'
    comment: 'Number of units sold on one order line.'
    synonyms: ['units', 'units sold']

  - name: unit_price
    expr: AVG(source.UNIT_PRICE)
    display_name: 'Unit Price'
    comment: 'Unit price recorded on the order-line item.'
    synonyms: ['price', 'list price']

  - name: employee_count
    expr: COUNT(orders.EMPLOYEE_ID)
    display_name: '# Employees'
    comment: 'Count of employees referenced on order records.'
    synonyms: ['employee count', 'rep count']

  - name: category_contribution_ratio
    expr: COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)
    display_name: 'Category Contribution Ratio'
    comment: 'Product share of category total units.'

  - name: monthly_revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Monthly Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current

  - name: prior_month_revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Prior Month Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 month

  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
    display_name: 'MoM Growth %'
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }

  - name: active_customers
    expr: COUNT(DISTINCT orders.customers.CUSTOMER_ID) FILTER (WHERE source.LINE_TOTAL > 0)
    display_name: 'Active Customers'
    comment: 'Customers with at least one positive-value line item.'
```

---

## MV 2 — Dunder Mifflin Inventory

**Source:** `agent_skills.dunder_mifflin.dm_inventory`

### Dimensions

| Name | Source | expr | display_name | Notes |
|---|---|---|---|---|
| `balance_date` | DM_INVENTORY::BALANCE_DATE | `source.BALANCE_DATE` | Balance Date | Raw date — used as semi-additive order dimension |
| `product_name` | DM_PRODUCT::PRODUCT_NAME | `products.PRODUCT_NAME` | Product Name | |
| `product_category` | DM_CATEGORY::CATEGORY_NAME | `products.category.CATEGORY_NAME` | Product Category | Nested join dot-path |

### Measures

| Name | Source | expr | display_name | Notes |
|---|---|---|---|---|
| `inventory_balance` | formula_Inventory Balance | `SUM(source.FILLED_INVENTORY)` | Inventory Balance | Semi-additive: `window: [{order: balance_date, semiadditive: last, range: current}]` |

### Full YAML Output — Inventory MV

```yaml
version: 1.1
comment: >-
  Dunder Mifflin Inventory analysis — semi-additive stock levels by product
  and date. Converted from ThoughtSpot Model: Dunder Mifflin Sales & Inventory.
source: agent_skills.dunder_mifflin.dm_inventory

joins:
  - name: dates
    source: agent_skills.dunder_mifflin.dm_date_dim
    "on": source.BALANCE_DATE = dates.DATE_VALUE
    rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.PRODUCT_ID = products.PRODUCT_ID
    rely: { at_most_one_match: true }
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }

dimensions:
  - name: balance_date
    expr: source.BALANCE_DATE
    display_name: 'Balance Date'
    comment: 'Date the inventory balance was snapshotted.'

  - name: product_name
    expr: products.PRODUCT_NAME
    display_name: 'Product Name'
    comment: 'Display name of the product.'
    synonyms: ['product', 'item']

  - name: product_category
    expr: products.category.CATEGORY_NAME
    display_name: 'Product Category'
    comment: 'Category name the product belongs to.'
    synonyms: ['category', 'product line']

measures:
  - name: inventory_balance
    expr: SUM(source.FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Quantity of stock held at each balance date. Semi-additive snapshot measure.'
    synonyms: ['stock', 'stock on hand', 'current inventory']
    window:
      - order: balance_date
        semiadditive: last
        range: current
```

---

## DDL — CREATE OR REPLACE VIEW ... WITH METRICS

### MV 1 — Sales

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: >-
  Dunder Mifflin Sales metrics built on normalized star schema — revenue,
  quantity, pricing, period-over-period analysis, and category contribution.
  Converted from ThoughtSpot Model: Dunder Mifflin Sales & Inventory.
source: agent_skills.dunder_mifflin.dm_order_detail

joins:
  - name: orders
    source: agent_skills.dunder_mifflin.dm_order
    "on": source.ORDER_ID = orders.ORDER_ID
    rely: { at_most_one_match: true }
    joins:
      - name: customers
        source: agent_skills.dunder_mifflin.dm_customer
        "on": orders.CUSTOMER_ID = customers.CUSTOMER_ID
        rely: { at_most_one_match: true }
      - name: employees
        source: agent_skills.dunder_mifflin.dm_employee
        "on": orders.EMPLOYEE_ID = employees.EMPLOYEE_ID
        rely: { at_most_one_match: true }
      - name: dates
        source: agent_skills.dunder_mifflin.dm_date_dim
        "on": orders.ORDER_DATE = dates.DATE_VALUE
        rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.PRODUCT_ID = products.PRODUCT_ID
    rely: { at_most_one_match: true }
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }

dimensions:
  - name: order_id
    expr: orders.ORDER_ID
    display_name: 'Order Id'
    comment: 'Identifier for one order header. Each order can have multiple lines.'

  - name: order_date
    expr: orders.ORDER_DATE
    display_name: 'Order Date'
    comment: 'Date the order was placed.'
    synonyms: ['order placed', 'purchase date']

  - name: order_month
    expr: "DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)"
    display_name: 'Order Month'
    comment: 'Truncated month for period-over-period analysis.'

  - name: transaction_date
    expr: orders.dates.DATE_VALUE
    display_name: 'Transaction Date'
    comment: 'Date dimension key.'
    synonyms: ['date']

  - name: product_name
    expr: products.PRODUCT_NAME
    display_name: 'Product Name'
    comment: 'Display name of the product.'
    synonyms: ['product', 'item']

  - name: product_category
    expr: products.category.CATEGORY_NAME
    display_name: 'Product Category'
    comment: 'Category name the product belongs to.'
    synonyms: ['category', 'product line']

  - name: customer_name
    expr: orders.customers.COMPANY_NAME
    display_name: 'Customer Name'
    comment: 'The customer display name.'
    synonyms: ['customer', 'client', 'buyer']

  - name: customer_state
    expr: orders.customers.STATE
    display_name: 'Customer State'
    comment: 'The customer state of residence.'

  - name: customer_zipcode
    expr: orders.customers.ZIPCODE
    display_name: 'Customer Zipcode'
    comment: 'Postal code on the customer billing address.'
    synonyms: ['zip code', 'postal code']

  - name: employee_name
    expr: "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)"
    display_name: 'Employee'
    comment: 'Employee name as Last, First.'
    synonyms: ['sales rep', 'rep', 'salesperson']

  - name: discount
    expr: source.DISCOUNT
    display_name: 'Discount'
    comment: 'Per-line discount recorded on the order detail.'
    synonyms: ['promo', 'discount amount']

  - name: category_quantity
    expr: SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)
    display_name: 'Category Quantity'
    comment: 'Total units sold at category grain, independent of query GROUP BY.'

measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Revenue'
    comment: 'Dollar value of an order-line item.'
    synonyms: ['sales', 'total sales', 'amount']
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }

  - name: quantity
    expr: SUM(source.QUANTITY)
    display_name: 'Quantity'
    comment: 'Number of units sold on one order line.'
    synonyms: ['units', 'units sold']

  - name: unit_price
    expr: AVG(source.UNIT_PRICE)
    display_name: 'Unit Price'
    comment: 'Unit price recorded on the order-line item.'
    synonyms: ['price', 'list price']

  - name: employee_count
    expr: COUNT(orders.EMPLOYEE_ID)
    display_name: '# Employees'
    comment: 'Count of employees referenced on order records.'
    synonyms: ['employee count', 'rep count']

  - name: category_contribution_ratio
    expr: COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)
    display_name: 'Category Contribution Ratio'
    comment: 'Product share of category total units.'

  - name: monthly_revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Monthly Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current

  - name: prior_month_revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Prior Month Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 month

  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
    display_name: 'MoM Growth %'
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }

  - name: active_customers
    expr: COUNT(DISTINCT orders.customers.CUSTOMER_ID) FILTER (WHERE source.LINE_TOTAL > 0)
    display_name: 'Active Customers'
    comment: 'Customers with at least one positive-value line item.'
$$
```

### MV 2 — Inventory

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: >-
  Dunder Mifflin Inventory analysis — semi-additive stock levels by product
  and date. Converted from ThoughtSpot Model: Dunder Mifflin Sales & Inventory.
source: agent_skills.dunder_mifflin.dm_inventory

joins:
  - name: dates
    source: agent_skills.dunder_mifflin.dm_date_dim
    "on": source.BALANCE_DATE = dates.DATE_VALUE
    rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.PRODUCT_ID = products.PRODUCT_ID
    rely: { at_most_one_match: true }
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }

dimensions:
  - name: balance_date
    expr: source.BALANCE_DATE
    display_name: 'Balance Date'
    comment: 'Date the inventory balance was snapshotted.'

  - name: product_name
    expr: products.PRODUCT_NAME
    display_name: 'Product Name'
    comment: 'Display name of the product.'
    synonyms: ['product', 'item']

  - name: product_category
    expr: products.category.CATEGORY_NAME
    display_name: 'Product Category'
    comment: 'Category name the product belongs to.'
    synonyms: ['category', 'product line']

measures:
  - name: inventory_balance
    expr: SUM(source.FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Quantity of stock held at each balance date. Semi-additive snapshot measure.'
    synonyms: ['stock', 'stock on hand', 'current inventory']
    window:
      - order: balance_date
        semiadditive: last
        range: current
$$
```

---

## Unmapped Properties Report

| Property | Column/Field | Value | Reason |
|---|---|---|---|
| `ai_context` | Revenue | "Total line-item revenue for financial analysis." | No MV equivalent — included in `comment:` instead |

No formulas were omitted — all 8 were translatable.

---

## Verification Queries

Metric View measures must be wrapped in `MEASURE()` when queried:

```sql
-- Sales: top categories by revenue
SELECT product_category,
  MEASURE(revenue) AS revenue,
  MEASURE(quantity) AS units,
  MEASURE(unit_price) AS avg_price
FROM agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
GROUP BY product_category
ORDER BY revenue DESC

-- Sales: LOD dimension and contribution ratio
SELECT product_category, product_name,
  MEASURE(quantity) AS product_qty,
  ANY_VALUE(category_quantity) AS cat_qty,
  MEASURE(category_contribution_ratio) AS contribution
FROM agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
GROUP BY product_category, product_name
ORDER BY contribution DESC

-- Sales: period-over-period (MoM)
-- Caveat (2026-07-09): this multi-month query returns ROW-RELATIVE values
-- (each row's prior_month is its own previous period), which diverges from
-- the wall-clock intent of the source TS formula — see the Formula 5 caveat.
SELECT order_month,
  MEASURE(monthly_revenue) AS current_month,
  MEASURE(prior_month_revenue) AS prior_month,
  MEASURE(mom_growth_pct) AS growth_pct
FROM agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
GROUP BY order_month
ORDER BY order_month DESC

-- Sales: conditional aggregate — active customers by state
SELECT customer_state,
  MEASURE(active_customers) AS active
FROM agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
GROUP BY customer_state
ORDER BY active DESC

-- Inventory: semi-additive balance by category
SELECT product_category, balance_date,
  MEASURE(inventory_balance) AS stock
FROM agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv
GROUP BY product_category, balance_date
ORDER BY balance_date DESC
```

---

## Flattened Views as Fallback

The primary approach above uses v1.1 nested `joins:` to express the star schema
directly. Flattened SQL VIEWs are a fallback for cases where the join structure
cannot be expressed as nested joins (e.g., many-to-many relationships, cross-fact
joins, or self-joins).

If the nested join approach fails for a specific model, create a flattened view
that pre-joins all dimension tables and point the MV at it using single-source mode:

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dm_sales_flat AS
SELECT
  od.ORDER_ID AS DM_ORDER_DETAIL_ORDER_ID,
  od.PRODUCT_ID AS DM_ORDER_DETAIL_PRODUCT_ID,
  od.UNIT_PRICE, od.QUANTITY, od.DISCOUNT, od.LINE_TOTAL,
  o.ORDER_ID, o.CUSTOMER_ID, o.EMPLOYEE_ID, o.ORDER_DATE,
  p.PRODUCT_ID, p.PRODUCT_NAME, p.PRODUCT_DESCRIPTION,
  c.CATEGORY_ID, c.CATEGORY_NAME AS PRODUCT_CATEGORY,
  cu.CUSTOMER_ID AS DM_CUSTOMER_ID, cu.CUSTOMER_CODE,
  cu.COMPANY_NAME, cu.STATE AS CUSTOMER_STATE, cu.ZIPCODE,
  d.DATE_VALUE AS TRANSACTION_DATE,
  e.EMPLOYEE_ID AS DM_EMPLOYEE_ID, e.FIRST_NAME, e.LAST_NAME
FROM agent_skills.dunder_mifflin.DM_ORDER_DETAIL od
JOIN agent_skills.dunder_mifflin.DM_ORDER o
  ON od.ORDER_ID = o.ORDER_ID
JOIN agent_skills.dunder_mifflin.DM_PRODUCT p
  ON od.PRODUCT_ID = p.PRODUCT_ID
JOIN agent_skills.dunder_mifflin.DM_CATEGORY c
  ON p.CATEGORY_ID = c.CATEGORY_ID
JOIN agent_skills.dunder_mifflin.DM_CUSTOMER cu
  ON o.CUSTOMER_ID = cu.CUSTOMER_ID
JOIN agent_skills.dunder_mifflin.DM_DATE_DIM d
  ON o.ORDER_DATE = d.DATE_VALUE
JOIN agent_skills.dunder_mifflin.DM_EMPLOYEE e
  ON o.EMPLOYEE_ID = e.EMPLOYEE_ID
```

With a flattened view, the MV uses `source:` without `joins:` and column references
use physical column names directly (no dot-path prefixes):

```yaml
version: 1.1
source: agent_skills.dunder_mifflin.dm_sales_flat
dimensions:
  - name: product_category
    expr: PRODUCT_CATEGORY          # no prefix — single-source mode
measures:
  - name: revenue
    expr: SUM(LINE_TOTAL)           # no prefix
```

The user must confirm the fallback approach at the Step 10 checkpoint before the
flattened view is created.

---

## Key Patterns from This Example

1. **Multi-fact split: one MV per fact table.** Databricks MV has a single `source:`.
   A model with two fact tables (DM_ORDER_DETAIL, DM_INVENTORY) must be split into
   independent MVs, each with its own dimension joins. Shared dimensions (DM_PRODUCT,
   DM_CATEGORY) are duplicated across both MVs.

2. **Nested joins, not sibling-level.** DM_CUSTOMER, DM_EMPLOYEE, and DM_DATE_DIM
   join to DM_ORDER, not directly to the source (DM_ORDER_DETAIL). They must appear
   nested under `orders:` in the `joins:` hierarchy. Placing them at the top level
   with `"on": source.CUSTOMER_ID = customers.CUSTOMER_ID` fails with
   `UNRESOLVED_COLUMN` because the FK columns live on DM_ORDER, not DM_ORDER_DETAIL.

3. **LOD formulas → dimension window functions.** `group_aggregate(sum([QUANTITY]),
   {[CATEGORY_NAME]}, query_filters())` becomes a `dimensions[]` entry with
   `expr: SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)`.
   Do NOT use `AGGREGATE OVER` (causes `PARSE_SYNTAX_ERROR`) and do NOT put LOD
   results in `measures[]`.

4. **Semi-additive snapshot: `last_value` → `window: [{semiadditive: last}]`.**
   `last_value(sum([FILLED_INVENTORY]), query_groups(), {[DATE_VALUE]})` maps to
   a measure with `window: [{order: balance_date, semiadditive: last, range: current}]`.
   The `order:` references a **raw date** dimension, distinguishing this from
   period-filter patterns that use a truncated period dimension.

5. **MEASURE() / ANY_VALUE() for cross-references.** `safe_divide([Quantity],
   [Category Quantity])` references a measure and an LOD dimension. In the MV,
   the measure reference becomes `MEASURE(quantity)` and the LOD dimension reference
   becomes `ANY_VALUE(category_quantity)`. The ratio uses
   `COALESCE(... / NULLIF(..., 0), 0)` because Databricks has no `DIV0`.

6. **v1.1 metadata: `display_name`, `comment`, `synonyms`.** Every column carries
   its ThoughtSpot display name in `display_name:`, description in `comment:`, and
   synonyms in `synonyms:`. The machine-readable `name:` uses snake_case. Always
   use v1.1 — v0.1 only supports `name`, `expr`, `window`.

7. **Period-over-period: `sum_if(diff_months(...))` → window with truncated order
   dimension.** The pattern `sum_if(diff_months([date], today()) = 0, [m])` maps
   to `window: [{order: order_month, semiadditive: last, range: current}]` where
   `order_month` is a computed dimension with `DATE_TRUNC('MONTH', ...)`. The prior
   month adds `offset: -1 month`. Growth % is derived via `MEASURE()` references
   to both period measures. **Caveat added 2026-07-09** (matrix C6,
   `docs/audit/2026-07-08-dbx-window-claim-matrix.md`): Databricks' `range:
   current`/`offset` is row-relative, not wall-clock like the source TS formula —
   this translation is exact only for a single-current-period snapshot query, not
   a multi-period trend. See Formula 5 above for the full caveat.

8. **Conditional aggregates: `*_if` → `FILTER (WHERE ...)`.** ThoughtSpot's
   `unique_count_if(cond, x)` maps to `COUNT(DISTINCT x) FILTER (WHERE cond)`.
   All native `*_if` functions (`sum_if`, `count_if`, `average_if`, etc.) use this
   same pattern.

9. **`semiadditive` is required when `window` is present.** Omitting `semiadditive`
   fails with `Missing required creator property 'semiadditive'`. Valid values:
   `last`, `first`.

10. **Dot-path column references through nested joins.** Fact table columns use
    `source.COL`. First-level join columns use `alias.COL`. Nested join columns
    use `parent_alias.child_alias.COL` — e.g., `products.category.CATEGORY_NAME`
    reaches DM_CATEGORY through the DM_PRODUCT join.

11. **`ai_context` has no MV equivalent.** ThoughtSpot's `ai_context` property
    cannot be mapped to any Databricks MV field. When meaningful, fold it into the
    column's `comment:` field instead. Log the unmapped property in the report.

12. **Flattened views are the fallback, not the default.** Use v1.1 nested `joins:`
    as the primary approach. Fall back to a flattened SQL VIEW only when joins cannot
    be expressed as nested hierarchy (many-to-many, self-joins, cross-fact). The user
    must confirm fallback at the Step 10 checkpoint.
