# Worked Example — ThoughtSpot Model → Databricks Metric Views

End-to-end conversion of the `TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY` Model
(GUID `dc1847dc-72a7-4f13-adaf-3ace7c8e0d95`) to two Databricks Metric Views:
one for sales analysis, one for inventory analysis. Covers multi-fact split,
flattened view generation, v1.1 features (display_name, comment, synonyms),
LOD dimension via window function, cross-measure ratio via MEASURE()/ANY_VALUE(),
semi-additive via window/semiadditive, and safe_divide translation.

Verified against live Databricks instance (`dbc-3472b2da-8a4e.cloud.databricks.com`,
warehouse `AGENT_SKILLS_TESTING` Preview channel) on 2026-05-25.

---

## Input — ThoughtSpot Model TML (key sections)

```yaml
guid: dc1847dc-72a7-4f13-adaf-3ace7c8e0d95
model:
  name: TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY
  description: "The Dunder Mifflin Sales & Inventory worksheet provides a comprehensive
    overview of sales transactions..."
  model_tables:
  - name: DM_ORDER
    joins:
    - with: DM_CUSTOMER
      referencing_join: DM_ORDER_to_DM_CUSTOMER
    - with: DM_DATE_DIM
      referencing_join: DM_ORDER_to_DM_DATE_DIM
    - with: DM_EMPLOYEE
      referencing_join: DM_ORDER_to_DM_EMPLOYEE
  - name: DM_ORDER_DETAIL
    joins:
    - with: DM_ORDER
      referencing_join: DM_ORDER_DETAIL_to_DM_ORDER
    - with: DM_PRODUCT
      referencing_join: DM_ORDER_DETAIL_to_DM_PRODUCT
  - name: DM_EMPLOYEE
  - name: DM_PRODUCT
    joins:
    - with: DM_CATEGORY
      referencing_join: DM_PRODUCT_to_DM_CATEGORY
  - name: DM_INVENTORY
    joins:
    - with: DM_DATE_DIM
      referencing_join: DM_INVENTORY_to_DM_DATE_DIM
    - with: DM_PRODUCT
      referencing_join: DM_INVENTORY_to_DM_PRODUCT
  - name: DM_CATEGORY
  - name: DM_CUSTOMER
  - name: DM_DATE_DIM
  columns:
  - name: Order Id
    column_id: DM_ORDER::ORDER_ID
    properties:
      column_type: ATTRIBUTE
      description: "Identifier for one order header. Each order can have multiple lines."
  - name: Sales Order Customer ID
    column_id: DM_ORDER::CUSTOMER_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Order Client ID']
  - name: Sales Order Employee ID
    column_id: DM_ORDER::EMPLOYEE_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Order Staff ID']
  - name: Order Date
    column_id: DM_ORDER::ORDER_DATE
    properties:
      column_type: ATTRIBUTE
      description: "Date the order was placed. The primary time anchor for sales activity."
      synonyms: ['order placed', 'purchase date']
  - name: Transaction ID
    column_id: DM_ORDER_DETAIL::ORDER_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Purchase Reference']
  - name: Sales Order Product ID
    column_id: DM_ORDER_DETAIL::PRODUCT_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Order Line Product ID']
  - name: Discount
    column_id: DM_ORDER_DETAIL::DISCOUNT
    properties:
      column_type: ATTRIBUTE
      description: "Per-line discount recorded on the order detail."
      synonyms: ['promo', 'discount amount']
  - name: Product ID
    column_id: DM_PRODUCT::PRODUCT_ID
    properties:
      column_type: ATTRIBUTE
  - name: Sales Product Category ID
    column_id: DM_PRODUCT::CATEGORY_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Product Group ID']
  - name: Product Name
    column_id: DM_PRODUCT::PRODUCT_NAME
    properties:
      column_type: ATTRIBUTE
      description: "Display name of the product."
      synonyms: ['product', 'item']
  - name: Product Description
    column_id: DM_PRODUCT::PRODUCT_DESCRIPTION
    properties:
      column_type: ATTRIBUTE
      description: "Long-form product description."
  - name: Product Identifier
    column_id: DM_INVENTORY::PRODUCT_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Inventory Code']
  - name: Balance Date
    column_id: DM_INVENTORY::BALANCE_DATE
    properties:
      column_type: ATTRIBUTE
      description: "Date the inventory balance was snapshotted."
  - name: Group ID
    column_id: DM_CATEGORY::CATEGORY_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Category Code']
  - name: Product Category
    column_id: DM_CATEGORY::CATEGORY_NAME
    properties:
      column_type: ATTRIBUTE
      description: "Category name the product belongs to."
      synonyms: ['category', 'product line']
  - name: Client ID
    column_id: DM_CUSTOMER::CUSTOMER_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Buyer ID']
  - name: Customer Code
    column_id: DM_CUSTOMER::CUSTOMER_CODE
    properties:
      column_type: ATTRIBUTE
      description: "Short business code for the customer."
  - name: Customer Name
    column_id: DM_CUSTOMER::COMPANY_NAME
    properties:
      column_type: ATTRIBUTE
      description: "The customer display name."
      synonyms: ['customer', 'client', 'buyer']
  - name: Customer State
    column_id: DM_CUSTOMER::STATE
    properties:
      column_type: ATTRIBUTE
      description: "The customer state of residence."
      synonyms: ['state']
  - name: Customer Zipcode
    column_id: DM_CUSTOMER::ZIPCODE
    properties:
      column_type: ATTRIBUTE
      description: "Postal code on the customer billing address."
      synonyms: ['zip', 'zip code', 'postal code']
  - name: Transaction Date
    column_id: DM_DATE_DIM::DATE_VALUE
    properties:
      column_type: ATTRIBUTE
      description: "Date dimension key."
      synonyms: ['date']
  - name: Staff ID
    column_id: DM_EMPLOYEE::EMPLOYEE_ID
    properties:
      column_type: ATTRIBUTE
      synonyms: ['Worker ID']
  - name: Unit Price
    column_id: DM_ORDER_DETAIL::UNIT_PRICE
    properties:
      column_type: MEASURE
      aggregation: AVERAGE
      description: "Unit price recorded on the order-line item."
      synonyms: ['price', 'list price']
  - name: Quantity
    column_id: DM_ORDER_DETAIL::QUANTITY
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Number of units sold on one order line."
      synonyms: ['units', 'units sold']
  - name: Amount
    column_id: DM_ORDER_DETAIL::LINE_TOTAL
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Dollar value of an order-line item."
      synonyms: ['revenue', 'sales', 'sales revenue']
  - name: "# Employees"
    formula_id: "formula_# Employees"
    properties:
      column_type: MEASURE
      aggregation: SUM
      synonyms: ['employee count', 'rep count']
  - name: Employee
    formula_id: formula_Employee
    properties:
      column_type: ATTRIBUTE
      synonyms: ['sales rep', 'rep', 'salesperson']
  - name: Answer Formula
    formula_id: formula_Answer Formula
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Average revenue per unit."
  - name: Category Quantity
    formula_id: formula_Category Quantity
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Total units sold for a product category."
  - name: Product to Category Contribution Ratio
    formula_id: formula_Product to Category Contribution Ratio
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Product share of category total units."
  - name: Inventory Balance
    formula_id: formula_Inventory Balance
    properties:
      column_type: MEASURE
      aggregation: SUM
      description: "Semi-additive inventory snapshot."
      synonyms: ['stock', 'stock on hand', 'current inventory']
  formulas:
  - id: "formula_# Employees"
    name: "# Employees"
    expr: "count ( [DM_ORDER::EMPLOYEE_ID] )"
  - id: formula_Employee
    name: Employee
    expr: "concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )"
  - id: formula_Answer Formula
    name: Answer Formula
    expr: "safe_divide ( [DM_ORDER_DETAIL::LINE_TOTAL] , [DM_ORDER_DETAIL::QUANTITY] )"
  - id: formula_Inventory Balance
    name: Inventory Balance
    expr: "last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )"
  - id: formula_Category Quantity
    name: Category Quantity
    expr: "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) ) )"
  - id: formula_Product to Category Contribution Ratio
    name: Product to Category Contribution Ratio
    expr: "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_INVENTORY::PRODUCT_ID] } , query_filters ( ) ) ) / [formula_Category Quantity]"
```

All 8 associated Table TMLs resolve to `db: agent_skills, schema: dunder_mifflin`.

---

## Step 1 — Identify Fact Tables and Split Decision

**Why split?** Databricks Metric Views have a single `source:` table/view. This model
has two independent fact tables (`DM_ORDER_DETAIL` for sales, `DM_INVENTORY` for stock
levels). Each must become its own Metric View.

**Additionally:** Metric View v1.1 joins do not support transitive references. The `on`
clause can only reference `source` and the current join entity — not previously-joined
entities. Even if the model were single-fact, the transitive dimension chain
(ORDER_DETAIL → ORDER → CUSTOMER) cannot be expressed as MV joins.

**Workaround:** Create a flattened SQL VIEW per fact table that pre-joins all dimension
tables, then point each Metric View at its flattened view using v1.1 single-source mode.

**Fact table assignment:**

| Fact Table | Dimension Tables Joined | Metric View |
|---|---|---|
| DM_ORDER_DETAIL | DM_ORDER, DM_PRODUCT, DM_CATEGORY, DM_CUSTOMER, DM_DATE_DIM, DM_EMPLOYEE | Sales MV |
| DM_INVENTORY | DM_PRODUCT, DM_CATEGORY | Inventory MV |

**Column assignment:**

| Column | Source Table | → Metric View |
|---|---|---|
| Order Id, Order Date, Customer ID, Employee ID | DM_ORDER | Sales |
| Transaction ID, Product ID, Discount, Unit Price, Quantity, Amount | DM_ORDER_DETAIL | Sales |
| Product Name, Product Description, Category ID | DM_PRODUCT | Sales + Inventory |
| Product Category | DM_CATEGORY | Sales + Inventory |
| Customer Code/Name/State/Zipcode | DM_CUSTOMER | Sales |
| Transaction Date | DM_DATE_DIM | Sales |
| Employee, Staff ID, # Employees | DM_EMPLOYEE / formula | Sales |
| Answer Formula, Category Quantity, Contribution Ratio | formulas | Sales |
| Balance Date, Inventory Product ID, Inventory Balance | DM_INVENTORY / formula | Inventory |

---

## Step 2 — Create Flattened Views

### Sales flattened view

Joins ORDER_DETAIL → ORDER → CUSTOMER, DATE_DIM, EMPLOYEE; ORDER_DETAIL → PRODUCT → CATEGORY.

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dm_sales_flat AS
SELECT
  od.DM_ORDER_DETAIL_ORDER_ID,
  od.DM_ORDER_DETAIL_PRODUCT_ID,
  od.UNIT_PRICE,
  od.QUANTITY,
  od.DISCOUNT,
  od.LINE_TOTAL,
  o.ORDER_ID,
  o.DM_ORDER_CUSTOMER_ID,
  o.DM_ORDER_EMPLOYEE_ID,
  o.DM_ORDER_ORDER_DATE,
  p.PRODUCT_ID,
  p.PRODUCT_NAME,
  p.PRODUCT_DESCRIPTION,
  p.DM_PRODUCT_CATEGORY_ID,
  c.CATEGORY_ID,
  c.CATEGORY_NAME AS PRODUCT_CATEGORY,
  cu.CUSTOMER_ID,
  cu.CUSTOMER_CODE,
  cu.COMPANY_NAME,
  cu.STATE AS CUSTOMER_STATE,
  cu.ZIPCODE,
  d.DATE_VALUE AS TRANSACTION_DATE,
  e.EMPLOYEE_ID,
  e.FIRST_NAME,
  e.LAST_NAME
FROM agent_skills.dunder_mifflin.DM_ORDER_DETAIL od
JOIN agent_skills.dunder_mifflin.DM_ORDER o
  ON od.DM_ORDER_DETAIL_ORDER_ID = o.ORDER_ID
JOIN agent_skills.dunder_mifflin.DM_PRODUCT p
  ON od.DM_ORDER_DETAIL_PRODUCT_ID = p.PRODUCT_ID
JOIN agent_skills.dunder_mifflin.DM_CATEGORY c
  ON p.DM_PRODUCT_CATEGORY_ID = c.CATEGORY_ID
JOIN agent_skills.dunder_mifflin.DM_CUSTOMER cu
  ON o.DM_ORDER_CUSTOMER_ID = cu.CUSTOMER_ID
JOIN agent_skills.dunder_mifflin.DM_DATE_DIM d
  ON o.DM_ORDER_ORDER_DATE = d.DATE_VALUE
JOIN agent_skills.dunder_mifflin.DM_EMPLOYEE e
  ON o.DM_ORDER_EMPLOYEE_ID = e.EMPLOYEE_ID
```

### Inventory flattened view

Joins INVENTORY → PRODUCT → CATEGORY.

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dm_inventory_flat AS
SELECT
  inv.DM_INVENTORY_BALANCE_DATE,
  inv.DM_INVENTORY_PRODUCT_ID,
  inv.FILLED_INVENTORY,
  inv.OFFSET_BALANCE_DATE,
  p.PRODUCT_ID,
  p.PRODUCT_NAME,
  p.DM_PRODUCT_CATEGORY_ID,
  c.CATEGORY_ID,
  c.CATEGORY_NAME AS PRODUCT_CATEGORY
FROM agent_skills.dunder_mifflin.DM_INVENTORY inv
JOIN agent_skills.dunder_mifflin.DM_PRODUCT p
  ON inv.DM_INVENTORY_PRODUCT_ID = p.PRODUCT_ID
JOIN agent_skills.dunder_mifflin.DM_CATEGORY c
  ON p.DM_PRODUCT_CATEGORY_ID = c.CATEGORY_ID
```

---

## Step 3 — Translate Formulas

### Formula 1: `Employee` (ATTRIBUTE)

```
concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )
```

→ Dimension with computed `expr`:
```yaml
- name: employee_name
  expr: CONCAT(LAST_NAME, ', ', FIRST_NAME)
```

In the flattened view, `LAST_NAME` and `FIRST_NAME` are direct columns (no entity prefix
needed in v0.1/single-source mode).

### Formula 2: `# Employees` (MEASURE)

```
count ( [DM_ORDER::EMPLOYEE_ID] )
```

→ Measure:
```yaml
- name: employee_count
  expr: COUNT(DM_ORDER_EMPLOYEE_ID)
```

### Formula 3: `Answer Formula` (safe_divide)

```
safe_divide ( [DM_ORDER_DETAIL::LINE_TOTAL] , [DM_ORDER_DETAIL::QUANTITY] )
```

→ Databricks has no `SAFE_DIVIDE`. Use `COALESCE(x / NULLIF(y, 0), 0)`:
```yaml
- name: answer_formula
  expr: COALESCE(SUM(LINE_TOTAL) / NULLIF(SUM(QUANTITY), 0), 0)
```

### Formula 4: `Category Quantity` (LOD / group_aggregate) — **DIMENSION, not measure**

```
sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) ) )
```

**Key insight:** In Databricks Metric Views, LOD expressions are expressed as
**dimensions** using SQL window functions, not as measures with `AGGREGATE OVER`.

→ Dimension with window function:
```yaml
dimensions:
  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)
    display_name: 'Category Quantity'
    comment: 'Total units sold at the category grain, independent of query GROUP BY.'
```

The `SUM() OVER (PARTITION BY)` computes the total at the category grain for every row,
regardless of what dimensions the query groups by. This is the Databricks equivalent of
ThoughtSpot's `group_aggregate`.

### Formula 5: `Product to Category Contribution Ratio` (cross-measure ratio)

```
sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_INVENTORY::PRODUCT_ID] } , query_filters ( ) ) ) / [formula_Category Quantity]
```

**Key insight:** Use `MEASURE()` to reference a measure and `ANY_VALUE()` to reference a
dimension inside a measure expression.

→ Measure referencing both `quantity` (measure) and `category_quantity` (dimension):
```yaml
measures:
  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
    display_name: 'Product to Category Contribution Ratio'
    comment: 'Product share of category total units.'
```

`MEASURE(quantity)` references the `quantity` measure defined in the same MV.
`ANY_VALUE(category_quantity)` wraps the LOD dimension — `ANY_VALUE()` is required
because dimensions cannot be directly referenced in a measure expression without
an aggregate wrapper.

### Formula 6: `Inventory Balance` (semi-additive)

```
last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
```

→ Measure with `window` and `semiadditive`:
```yaml
- name: inventory_balance
  expr: SUM(FILLED_INVENTORY)
  window:
    - order: balance_date
      range: current
      semiadditive: last
```

The `semiadditive: last` tells Databricks to take the last value along the `balance_date`
dimension when aggregating across time periods — equivalent to ThoughtSpot's `last_value`
pattern. The `range: current` scopes to the current time grain.

**Important:** The `window` field REQUIRES `semiadditive` to be present. Using `window`
without `semiadditive` (e.g. for LOD with `range: all`) fails with
`Missing required creator property 'semiadditive'`. Use dimension window functions
for LOD instead.

---

## Step 4 — Classify Columns

### Sales MV — Column classification

**Dimensions (21):**

| Display Name | Source | `expr` | v1.1 features |
|---|---|---|---|
| Order Id | DM_ORDER | `ORDER_ID` | comment |
| Sales Order Customer ID | DM_ORDER | `DM_ORDER_CUSTOMER_ID` | synonyms: [Order Client ID] |
| Sales Order Employee ID | DM_ORDER | `DM_ORDER_EMPLOYEE_ID` | synonyms: [Order Staff ID] |
| Order Date | DM_ORDER | `DM_ORDER_ORDER_DATE` | comment, synonyms: [order placed, purchase date] |
| Transaction ID | DM_ORDER_DETAIL | `DM_ORDER_DETAIL_ORDER_ID` | synonyms: [Purchase Reference] |
| Sales Order Product ID | DM_ORDER_DETAIL | `DM_ORDER_DETAIL_PRODUCT_ID` | synonyms: [Order Line Product ID] |
| Discount | DM_ORDER_DETAIL | `DISCOUNT` | comment, synonyms: [promo, discount amount] |
| Product ID | DM_PRODUCT | `PRODUCT_ID` | — |
| Sales Product Category ID | DM_PRODUCT | `DM_PRODUCT_CATEGORY_ID` | synonyms: [Product Group ID] |
| Product Name | DM_PRODUCT | `PRODUCT_NAME` | comment, synonyms: [product, item] |
| Product Description | DM_PRODUCT | `PRODUCT_DESCRIPTION` | comment |
| Group ID | DM_CATEGORY | `CATEGORY_ID` | synonyms: [Category Code] |
| Product Category | DM_CATEGORY | `PRODUCT_CATEGORY` | comment, synonyms: [category, product line] |
| Client ID | DM_CUSTOMER | `CUSTOMER_ID` | synonyms: [Buyer ID] |
| Customer Code | DM_CUSTOMER | `CUSTOMER_CODE` | comment |
| Customer Name | DM_CUSTOMER | `COMPANY_NAME` | comment, synonyms: [customer, client, buyer] |
| Customer State | DM_CUSTOMER | `CUSTOMER_STATE` | comment, synonyms: [state] |
| Customer Zipcode | DM_CUSTOMER | `ZIPCODE` | comment, synonyms: [zip, zip code, postal code] |
| Transaction Date | DM_DATE_DIM | `TRANSACTION_DATE` | comment, synonyms: [date] |
| Staff ID | DM_EMPLOYEE | `EMPLOYEE_ID` | synonyms: [Worker ID] |
| Employee | formula (CONCAT) | `CONCAT(LAST_NAME, ', ', FIRST_NAME)` | comment, synonyms: [sales rep, rep, salesperson] |
| Category Quantity | formula (LOD) | `SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)` | comment |

**Measures (7):**

| Display Name | `expr` | v1.1 features |
|---|---|---|
| Unit Price | `AVG(UNIT_PRICE)` | comment, synonyms: [price, list price] |
| Quantity | `SUM(QUANTITY)` | comment, synonyms: [units, units sold] |
| Amount | `SUM(LINE_TOTAL)` | comment, synonyms: [revenue, sales, sales revenue] |
| # Employees | `COUNT(DM_ORDER_EMPLOYEE_ID)` | comment, synonyms: [employee count, rep count] |
| Answer Formula | `COALESCE(SUM(LINE_TOTAL) / NULLIF(SUM(QUANTITY), 0), 0)` | comment |
| Category Contribution Ratio | `MEASURE(quantity) / ANY_VALUE(category_quantity)` | comment |

### Inventory MV — Column classification

**Dimensions (7):**

| Display Name | Source | `expr` |
|---|---|---|
| Product Identifier | DM_INVENTORY | `DM_INVENTORY_PRODUCT_ID` |
| Balance Date | DM_INVENTORY | `DM_INVENTORY_BALANCE_DATE` |
| Product ID | DM_PRODUCT | `PRODUCT_ID` |
| Product Name | DM_PRODUCT | `PRODUCT_NAME` |
| Product Category ID | DM_PRODUCT | `DM_PRODUCT_CATEGORY_ID` |
| Category ID | DM_CATEGORY | `CATEGORY_ID` |
| Product Category | DM_CATEGORY | `PRODUCT_CATEGORY` |

**Measures (1):**

| Display Name | `expr` | Semi-additive |
|---|---|---|
| Inventory Balance | `SUM(FILLED_INVENTORY)` | `window: [{order: balance_date, range: current, semiadditive: last}]` |

---

## Step 5 — Version Decision

Use **v1.1** for both MVs. Even though neither uses `joins:` (flattened view handles
that), v1.1 is required for `display_name`, `comment`, and `synonyms`. v0.1 only
supports `name`, `expr`, and `window`.

---

## Step 6 — DDL Syntax

The DDL uses `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$`.

**The `LANGUAGE YAML` clause is required.** Omitting it fails with:
```
[MISSING_CLAUSES_FOR_OPERATION] Missing clause LANGUAGE for operation CREATE METRIC VIEW
```

---

## Output — Sales Metric View DDL

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: >-
  Dunder Mifflin Sales analysis — order revenue (Amount, Quantity, Unit Price),
  employee activity, product categorization, and customer demographics.
  Converted from ThoughtSpot model TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY.
source: agent_skills.dunder_mifflin.dm_sales_flat

dimensions:
  - name: order_id
    expr: ORDER_ID
    display_name: 'Order Id'
    comment: 'Identifier for one order header. Each order can have multiple lines.'

  - name: order_customer_id
    expr: DM_ORDER_CUSTOMER_ID
    display_name: 'Sales Order Customer ID'
    synonyms: ['Order Client ID']

  - name: order_employee_id
    expr: DM_ORDER_EMPLOYEE_ID
    display_name: 'Sales Order Employee ID'
    synonyms: ['Order Staff ID']

  - name: order_date
    expr: DM_ORDER_ORDER_DATE
    display_name: 'Order Date'
    comment: 'Date the order was placed. The primary time anchor for sales activity.'
    synonyms: ['order placed', 'purchase date']

  - name: transaction_id
    expr: DM_ORDER_DETAIL_ORDER_ID
    display_name: 'Transaction ID'
    synonyms: ['Purchase Reference']

  - name: order_product_id
    expr: DM_ORDER_DETAIL_PRODUCT_ID
    display_name: 'Sales Order Product ID'
    synonyms: ['Order Line Product ID']

  - name: discount
    expr: DISCOUNT
    display_name: 'Discount'
    comment: 'Per-line discount recorded on the order detail.'
    synonyms: ['promo', 'discount amount']

  - name: product_id
    expr: PRODUCT_ID
    display_name: 'Product ID'

  - name: product_category_id
    expr: DM_PRODUCT_CATEGORY_ID
    display_name: 'Sales Product Category ID'
    synonyms: ['Product Group ID']

  - name: product_name
    expr: PRODUCT_NAME
    display_name: 'Product Name'
    comment: 'Display name of the product. Primary human-readable identifier for product-level breakdowns.'
    synonyms: ['product', 'item']

  - name: product_description
    expr: PRODUCT_DESCRIPTION
    display_name: 'Product Description'
    comment: 'Long-form product description. Free-text, not suitable for filtering or grouping.'

  - name: category_id
    expr: CATEGORY_ID
    display_name: 'Group ID'
    synonyms: ['Category Code']

  - name: product_category
    expr: PRODUCT_CATEGORY
    display_name: 'Product Category'
    comment: 'Category name the product belongs to. Mid-level grouping.'
    synonyms: ['category', 'product line']

  - name: client_id
    expr: CUSTOMER_ID
    display_name: 'Client ID'
    synonyms: ['Buyer ID']

  - name: customer_code
    expr: CUSTOMER_CODE
    display_name: 'Customer Code'
    comment: 'Short business code for the customer (account number).'

  - name: customer_name
    expr: COMPANY_NAME
    display_name: 'Customer Name'
    comment: 'The customer display name.'
    synonyms: ['customer', 'client', 'buyer']

  - name: customer_state
    expr: CUSTOMER_STATE
    display_name: 'Customer State'
    comment: 'The customer state of residence.'
    synonyms: ['state']

  - name: customer_zipcode
    expr: ZIPCODE
    display_name: 'Customer Zipcode'
    comment: 'Postal code on the customer billing address.'
    synonyms: ['zip', 'zip code', 'postal code']

  - name: transaction_date
    expr: TRANSACTION_DATE
    display_name: 'Transaction Date'
    comment: 'Date dimension key.'
    synonyms: ['date']

  - name: staff_id
    expr: EMPLOYEE_ID
    display_name: 'Staff ID'
    synonyms: ['Worker ID']

  - name: employee_name
    expr: CONCAT(LAST_NAME, ', ', FIRST_NAME)
    display_name: 'Employee'
    comment: 'Employee name as Last, First.'
    synonyms: ['sales rep', 'rep', 'salesperson']

  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)
    display_name: 'Category Quantity'
    comment: 'Total units sold at the category grain, independent of query GROUP BY.'

measures:
  - name: unit_price
    expr: AVG(UNIT_PRICE)
    display_name: 'Unit Price'
    comment: 'Unit price recorded on the order-line item.'
    synonyms: ['price', 'list price']

  - name: quantity
    expr: SUM(QUANTITY)
    display_name: 'Quantity'
    comment: 'Number of units sold on one order line.'
    synonyms: ['units', 'units sold']

  - name: amount
    expr: SUM(LINE_TOTAL)
    display_name: 'Amount'
    comment: 'Dollar value of an order-line item. The primary revenue measure.'
    synonyms: ['revenue', 'sales', 'sales revenue']

  - name: employee_count
    expr: COUNT(DM_ORDER_EMPLOYEE_ID)
    display_name: '# Employees'
    comment: 'Count of employees referenced on order records.'
    synonyms: ['employee count', 'rep count']

  - name: answer_formula
    expr: COALESCE(SUM(LINE_TOTAL) / NULLIF(SUM(QUANTITY), 0), 0)
    display_name: 'Answer Formula'
    comment: 'Average revenue per unit: Amount divided by Quantity.'

  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
    display_name: 'Product to Category Contribution Ratio'
    comment: 'Product share of category total units.'
$$
```

---

## Output — Inventory Metric View DDL

```sql
CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: >-
  Dunder Mifflin Inventory analysis — semi-additive stock levels by product
  and category over time. Converted from ThoughtSpot model
  TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY.
source: agent_skills.dunder_mifflin.dm_inventory_flat

dimensions:
  - name: inventory_product_id
    expr: DM_INVENTORY_PRODUCT_ID
    display_name: 'Product Identifier'
    synonyms: ['Inventory Code']

  - name: balance_date
    expr: DM_INVENTORY_BALANCE_DATE
    display_name: 'Balance Date'
    comment: 'Date the inventory balance was snapshotted.'

  - name: product_id
    expr: PRODUCT_ID
    display_name: 'Product ID'

  - name: product_name
    expr: PRODUCT_NAME
    display_name: 'Product Name'
    comment: 'Display name of the product.'
    synonyms: ['product', 'item']

  - name: product_category_id
    expr: DM_PRODUCT_CATEGORY_ID
    display_name: 'Product Category ID'

  - name: category_id
    expr: CATEGORY_ID
    display_name: 'Category ID'

  - name: product_category
    expr: PRODUCT_CATEGORY
    display_name: 'Product Category'
    comment: 'Category name the product belongs to.'
    synonyms: ['category', 'product line']

measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Quantity of stock held at each balance date. Semi-additive snapshot measure.'
    synonyms: ['stock', 'stock on hand', 'current inventory']
    window:
      - order: balance_date
        range: current
        semiadditive: last
$$
```

---

## Verification Queries

Metric View measures must be wrapped in `MEASURE()` when queried:

```sql
-- Sales: top categories by revenue
SELECT product_category,
  MEASURE(amount) AS revenue,
  MEASURE(quantity) AS units,
  MEASURE(answer_formula) AS avg_revenue_per_unit
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

-- Inventory: semi-additive balance by category
SELECT product_category, balance_date,
  MEASURE(inventory_balance) AS stock
FROM agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv
GROUP BY product_category, balance_date
ORDER BY balance_date DESC
```

---

## Key patterns from this example

1. **Multi-fact models must split into independent MVs.** Databricks Metric Views have a
   single `source:`. Models with multiple fact tables (sales + inventory) require one MV
   per fact table, each with its own flattened view as the source.

2. **Transitive joins are not supported.** The `on` clause in v1.1 `joins:` can only
   reference `source` and the current join entity. `entity1.col = entity2.col` fails
   with `UNRESOLVED_COLUMN`. Workaround: pre-join in a flattened SQL VIEW.

3. **Always use v1.1.** Even for single-source MVs without joins, v1.1 is needed for
   `display_name`, `comment`, and `synonyms`. v0.1 only supports `name`, `expr`, `window`.

4. **`LANGUAGE YAML` is required in the DDL.** `WITH METRICS AS $$` fails. Must be
   `WITH METRICS LANGUAGE YAML AS $$ ... $$`.

5. **LOD = dimension with window function.** ThoughtSpot `group_aggregate(sum(x), {dim}, query_filters())`
   becomes a **dimension** (not a measure) using `SUM(x) OVER (PARTITION BY dim)`. This
   computes the value at the partition grain for every row, independent of query GROUP BY.

6. **Cross-measure ratios use `MEASURE()` and `ANY_VALUE()`.** To reference a measure
   inside another measure: `MEASURE(measure_name)`. To reference a dimension inside a
   measure: `ANY_VALUE(dimension_name)`. The contribution ratio pattern is
   `MEASURE(quantity) / ANY_VALUE(category_quantity)`.

7. **Semi-additive uses `window` with required `semiadditive`.** The `window` field on a
   measure always requires `semiadditive`. `{order: dim, range: current, semiadditive: last}`
   is the Databricks equivalent of ThoughtSpot's `last_value(sum(x), query_groups(), {date})`.
   Using `window` without `semiadditive` fails.

8. **`safe_divide` → `COALESCE(x / NULLIF(y, 0), 0)`.** Databricks has no `SAFE_DIVIDE`
   function. Use `COALESCE(SUM(a) / NULLIF(SUM(b), 0), 0)` for divide-by-zero safety.

9. **Querying MVs requires `MEASURE()`.** Measure columns cannot be referenced directly
   in SELECT — they must be wrapped in `MEASURE(measure_name)`. Dimension columns
   referenced inside measure expressions use `ANY_VALUE(dim_name)`.

10. **Column references use physical names directly in v0.1 / single-source v1.1.** No
    entity alias prefix needed when the MV has a single `source:` (no `joins:`). Column
    names come from the flattened view's SELECT aliases.

11. **Shared dimension tables appear in both flattened views.** DM_PRODUCT and DM_CATEGORY
    are joined into both the sales and inventory flat views. This is expected — each MV
    needs its own complete column set.
