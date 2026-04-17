# Worked Example — ThoughtSpot Worksheet → Snowflake Semantic View

End-to-end conversion of the `Retail Sales` Worksheet to a Snowflake Semantic View
named `retail_sales`. Covers column classification, formula translation, name
generation, and relationship mapping.

---

## Input — ThoughtSpot Worksheet TML

```yaml
guid: 2ea7add9-0ccb-4ac1-90bb-231794ebb377
worksheet:
  name: Retail Sales
  tables:
  - name: fact_sales
  - name: dim_product
  joins:
  - name: sales_to_product
    source: fact_sales
    destination: dim_product
    type: INNER
    is_one_to_one: false
  table_paths:
  - id: fact_sales_1
    table: fact_sales
    join_path:
    - {}
  - id: dim_product_1
    table: dim_product
    join_path:
    - join:
      - sales_to_product
  formulas:
  - name: '# of Products'
    expr: "count ( [dim_product_1::product_id] )"
  worksheet_columns:
  - name: Product
    column_id: dim_product_1::product_name
    properties:
      column_type: ATTRIBUTE
      synonyms: [Item]
  - name: Revenue
    column_id: fact_sales_1::sales_amount
    properties:
      column_type: MEASURE
      aggregation: SUM
      synonyms: [Sales]
      ai_context: Total transaction value for financial analysis.
  - name: Sale Date
    column_id: fact_sales_1::sale_date
    properties:
      column_type: ATTRIBUTE
  - name: Product Count
    formula_id: '# of Products'
    properties:
      column_type: MEASURE
      aggregation: COUNT
```

Associated Table TML for `fact_sales`: `db: ANALYTICS, schema: PUBLIC, db_table: FACT_SALES`.
Associated Table TML for `dim_product`: `db: ANALYTICS, schema: PUBLIC, db_table: DIM_PRODUCT`.
Join condition from `fact_sales` Table TML: `[fact_sales::product_id] = [dim_product::product_id]`.

---

## Parse the Worksheet TML

**Tables and table_paths:**

| table_path id | table | join_path | Role |
|---|---|---|---|
| `fact_sales_1` | `fact_sales` | (none — empty) | Fact / left side |
| `dim_product_1` | `dim_product` | via `sales_to_product` | Dimension / right side |

**Joins:**

| Name | Source | Destination | Type |
|---|---|---|---|
| `sales_to_product` | `fact_sales` | `dim_product` | INNER |

`dim_product` is the destination — it becomes the `right_table` in the relationship
and requires a `primary_key` in the semantic view.

**Columns:**

| Display Name | column_id / formula_id | column_type | aggregation | Other |
|---|---|---|---|---|
| Product | `dim_product_1::product_name` | ATTRIBUTE | — | synonyms: [Item] |
| Revenue | `fact_sales_1::sales_amount` | MEASURE | SUM | synonyms: [Sales], ai_context set |
| Sale Date | `fact_sales_1::sale_date` | ATTRIBUTE | — | — |
| Product Count | formula `# of Products` | MEASURE | COUNT | — |

---

## Fetch Table Details

Export Table TML for `fact_sales` and `dim_product` to get physical `db`, `schema`,
`db_table` values and the join condition column names.

**From `fact_sales` Table TML:**
- `db: ANALYTICS`, `schema: PUBLIC`, `db_table: FACT_SALES`
- `joins_with` entry for `dim_product`: `on: "[fact_sales::product_id] = [dim_product::product_id]"`
  → FK column: `PRODUCT_ID`, PK column: `PRODUCT_ID`

**From `dim_product` Table TML:**
- `db: ANALYTICS`, `schema: PUBLIC`, `db_table: DIM_PRODUCT`
- PK column (from join condition above): `PRODUCT_ID`

**`base_table` values (UPPERCASE = case-insensitive, no quoting needed):**

| Table | database | schema | table |
|---|---|---|---|
| fact_sales | ANALYTICS | PUBLIC | FACT_SALES |
| dim_product | ANALYTICS | PUBLIC | DIM_PRODUCT |

---

## Classify Columns

Apply the classification decision tree to each column:

| Display Name | formula_id? | column_type | db_column_type / name | → Semantic View section |
|---|---|---|---|---|
| Product | no | ATTRIBUTE | `product_name` — no date suffix | **dimensions** |
| Revenue | no | MEASURE | — | **metrics** |
| Sale Date | no | ATTRIBUTE | `sale_date` — name ends with `_date` → date | **time_dimensions** |
| Product Count | yes (`# of Products`) | MEASURE | — | **metrics** (if translatable) |

**Sale Date classification note:** `column_type` is ATTRIBUTE but the column name ends with
`_date`. Apply the name-based date heuristic — classify as `time_dimensions`.

---

## Translate Formulas

**Formula: `# of Products`**

ThoughtSpot expression: `count ( [dim_product_1::product_id] )`

Translation:
- `count(...)` → `COUNT(...)` (direct mapping)
- `[dim_product_1::product_id]` → resolve `dim_product_1` table_path → `dim_product` table → `dim_product.PRODUCT_ID`
- Result: `COUNT(dim_product.PRODUCT_ID)`

✓ Translatable — add as `metrics` entry on `dim_product`.

---

## Generate Snowflake Names

Apply the name generation rules (lowercase, non-alphanumeric → underscore, strip ends):

| ThoughtSpot Display Name | Generated Name | Flag? |
|---|---|---|
| Product | `product` | no |
| Revenue | `revenue` | no |
| Sale Date | `sale_date` | no |
| Product Count | `product_count` | no |
| `# of Products` (formula name used as synonym) | `of_products` | **yes** — semantic loss from `#` prefix; override with `product_count` (matches display name) |
| Retail Sales (view name) | `retail_sales` | no |

**Review checkpoint presented to user:**

```
Name to review:
  ⚠ Formula '# of Products' → 'of_products' (# stripped — semantic loss)
    Suggestion: use 'product_count' (matches the 'Product Count' display name)
    Override? [product_count]:
```
User accepts `product_count`.

---

## Build Relationship

From the join: `sales_to_product` — `fact_sales` → `dim_product`, join column `PRODUCT_ID`.

```yaml
relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

`dim_product` is the right_table → add `primary_key: columns: [PRODUCT_ID]` to its table entry.

---

## Dry-Run Validation

```sql
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('ANALYTICS.PUBLIC', $$
name: retail_sales
...
$$, TRUE);
```

Returns success — proceed to create.

---

## Output — Snowflake Semantic View YAML

```yaml
name: retail_sales
description: "Migrated from ThoughtSpot: Retail Sales"

tables:
- name: fact_sales
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: FACT_SALES
  time_dimensions:
  - name: sale_date
    synonyms:
    - "Sale Date"
    description: ""
    expr: fact_sales.SALE_DATE
    data_type: DATE
  metrics:
  - name: revenue
    synonyms:
    - "Revenue"
    - "Sales"
    description: "[TS AI Context] Total transaction value for financial analysis."
    expr: SUM(fact_sales.SALES_AMOUNT)

- name: dim_product
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: DIM_PRODUCT
  primary_key:
    columns:
    - PRODUCT_ID
  dimensions:
  - name: product
    synonyms:
    - "Product"
    - "Item"
    description: ""
    expr: dim_product.PRODUCT_NAME
    data_type: TEXT
  metrics:
  - name: product_count
    synonyms:
    - "Product Count"
    - "# of Products"
    description: ""
    expr: COUNT(dim_product.PRODUCT_ID)

relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

---

## Key patterns from this example

1. **Column classification order matters.** `Sale Date` has `column_type: ATTRIBUTE` in the
   ThoughtSpot TML, but the name-based date heuristic overrides it to `time_dimensions`.
   Always check `db_column_type` (from Table TML) first, then fall back to name heuristics.

2. **Formula columns resolve via table_path.** `[dim_product_1::product_id]` uses the
   `table_path id` (`dim_product_1`), not the table name. Look up the table_path to find
   the underlying table (`dim_product`), then emit `dim_product.PRODUCT_ID`.

3. **`primary_key` on the right-side join table.** The `destination` of a ThoughtSpot join
   becomes the `right_table` in the relationship and requires `primary_key` in the semantic
   view. Extract the PK column from the join condition in the Table TML.

4. **`primary_key.columns` must be bare unquoted identifiers.** Even for case-sensitive
   lowercase columns, do not use `'"col"'` quoting — Cortex Analyst rejects it. Use
   the plain name (`product_id`, not `'"product_id"'`).

5. **Name generation: flag semantic loss.** `# of Products` → `of_products` loses the
   count intent. Always flag these at the review checkpoint and suggest a better name.
   The original name is preserved in `synonyms` so Cortex Analyst can still find it.

6. **`ai_context` becomes `[TS AI Context]` prefix in `description`.** The `Revenue`
   column's `ai_context` value is prepended with `[TS AI Context] ` and written to
   the semantic view `description` field.

7. **`dimensions`, `time_dimensions`, `metrics` are nested under their table.** They are
   NOT top-level keys. Each table entry owns its columns.

8. **Keyword is `metrics`, not `measures`.** Using `measures` is a schema error that
   causes a parse failure at creation time.

---
---

# Worked Example 2 — ThoughtSpot Model → Snowflake Semantic View (Advanced)

End-to-end conversion of the `Dunder Mifflin Sales & Inventory` Model to a Snowflake
Semantic View named `dunder_mifflin_sales_inventory`. Covers Model format parsing,
`referencing_join` resolution, case-sensitive columns, wrapper views, FK/PK name
conflict resolution, table aliasing, semi-additive metrics (`non_additive_dimensions`),
window function metrics (`OVER PARTITION BY`), formula translation including
`group_aggregate` and `last_value`, and out-of-scope join filtering.

---

## Input — ThoughtSpot Model TML (key sections)

```yaml
guid: 4da3a07f-fe29-4d20-8758-260eb1315071
model:
  name: Dunder Mifflin Sales & Inventory
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
  - name: Employee
    formula_id: formula_Employee
    properties:
      column_type: ATTRIBUTE
  - name: Inventory Balance
    formula_id: formula_Inventory Balance
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Unit Price
    column_id: DM_ORDER_DETAIL::UNIT_PRICE
    properties:
      column_type: MEASURE
      aggregation: AVERAGE
  - name: Quantity
    column_id: DM_ORDER_DETAIL::QUANTITY
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Discount
    column_id: DM_ORDER_DETAIL::DISCOUNT
    properties:
      column_type: ATTRIBUTE
  - name: Amount
    column_id: DM_ORDER_DETAIL::LINE_TOTAL
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Product ID
    column_id: DM_PRODUCT::PRODUCT_ID
    properties:
      column_type: ATTRIBUTE
  - name: Product Name
    column_id: DM_PRODUCT::PRODUCT_NAME
    properties:
      column_type: ATTRIBUTE
  - name: Product Description
    column_id: DM_PRODUCT::PRODUCT_DESCRIPTION
    properties:
      column_type: ATTRIBUTE
  - name: Product Category
    column_id: DM_CATEGORY::CATEGORY_NAME
    properties:
      column_type: ATTRIBUTE
  - name: Customer Code
    column_id: DM_CUSTOMER::CUSTOMER_CODE
    properties:
      column_type: ATTRIBUTE
  - name: Customer Name
    column_id: DM_CUSTOMER::COMPANY_NAME
    properties:
      column_type: ATTRIBUTE
  - name: Customer State
    column_id: DM_CUSTOMER::STATE
    properties:
      column_type: ATTRIBUTE
  - name: Customer Zipcode
    column_id: DM_CUSTOMER::ZIPCODE
    properties:
      column_type: ATTRIBUTE
  - name: Transaction Date
    column_id: DM_DATE_DIM::date
    properties:
      column_type: ATTRIBUTE
  - name: "# Employees"
    formula_id: "formula_# Employees"
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Category Quantity
    formula_id: formula_Category Quantity
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Product to Category Contribution Ratio
    formula_id: formula_Product to Category Contribution Ratio
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - id: "formula_# Employees"
    name: "# Employees"
    expr: "count ( [DM_ORDER::EMPLOYEE_ID] )"
  - id: formula_Employee
    name: Employee
    expr: "concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )"
  - id: formula_Inventory Balance
    name: Inventory Balance
    expr: "last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::date] } )"
  - id: formula_Product to Category Contribution Ratio
    name: Product to Category Contribution Ratio
    expr: "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_INVENTORY::PRODUCT_ID] } , query_filters ( ) ) ) / [formula_Category Quantity]"
  - id: formula_Category Quantity
    name: Category Quantity
    expr: "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) ) )"
```

All 8 associated Table TMLs resolve to `db: DUNDERMIFFLIN, schema: PUBLIC`.

---

## Step 1 — Identify TML Format

Top-level key is `model` → **Model format**.

Key differences from Worksheet format:
- Joins use `referencing_join` (resolved from Table TML `joins_with[]`)
- No `table_paths` — column_id references use table name directly: `TABLE::COLUMN`
- `model_tables[]` is the authoritative scope — any join referencing a table not in
  this list is skipped

---

## Step 2 — Resolve Physical Table Names and Joins

**Physical table map** (from Table TML exports):

| Table | db | schema | db_table |
|---|---|---|---|
| DM_ORDER | DUNDERMIFFLIN | PUBLIC | DM_ORDER |
| DM_ORDER_DETAIL | DUNDERMIFFLIN | PUBLIC | DM_ORDER_DETAIL |
| DM_EMPLOYEE | DUNDERMIFFLIN | PUBLIC | DM_EMPLOYEE |
| DM_PRODUCT | DUNDERMIFFLIN | PUBLIC | DM_PRODUCT |
| DM_INVENTORY | DUNDERMIFFLIN | PUBLIC | DM_INVENTORY |
| DM_CATEGORY | DUNDERMIFFLIN | PUBLIC | DM_CATEGORY |
| DM_CUSTOMER | DUNDERMIFFLIN | PUBLIC | DM_CUSTOMER |
| DM_DATE_DIM | DUNDERMIFFLIN | PUBLIC | DM_DATE_DIM |

**Resolve `referencing_join` conditions** from Table TML `joins_with[]`:

| Join Name | On Condition | Left Table | Right Table |
|---|---|---|---|
| DM_ORDER_DETAIL_to_DM_ORDER | `[DM_ORDER_DETAIL::ORDER_ID] = [DM_ORDER::ORDER_ID]` | DM_ORDER_DETAIL | DM_ORDER |
| DM_ORDER_DETAIL_to_DM_PRODUCT | `[DM_ORDER_DETAIL::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]` | DM_ORDER_DETAIL | DM_PRODUCT |
| DM_ORDER_to_DM_CUSTOMER | `[DM_ORDER::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]` | DM_ORDER | DM_CUSTOMER |
| DM_ORDER_to_DM_DATE_DIM | `[DM_ORDER::ORDER_DATE] = [DM_DATE_DIM::date]` | DM_ORDER | DM_DATE_DIM |
| DM_ORDER_to_DM_EMPLOYEE | `[DM_ORDER::EMPLOYEE_ID] = [DM_EMPLOYEE::EMPLOYEE_ID]` | DM_ORDER | DM_EMPLOYEE |
| DM_PRODUCT_to_DM_CATEGORY | `[DM_PRODUCT::CATEGORY_ID] = [DM_CATEGORY::CATEGORY_ID]` | DM_PRODUCT | DM_CATEGORY |
| DM_INVENTORY_to_DM_DATE_DIM | `[DM_INVENTORY::BALANCE_DATE] = [DM_DATE_DIM::date]` | DM_INVENTORY | DM_DATE_DIM |
| DM_INVENTORY_to_DM_PRODUCT | `[DM_INVENTORY::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]` | DM_INVENTORY | DM_PRODUCT |
| DM_PRODUCT_to_DM_SUPPLIER | `[DM_PRODUCT::SUPPLIER_ID] = [DM_SUPPLIER::SUPPLIER_ID]` | DM_PRODUCT | DM_SUPPLIER |
| DM_EMPLOYEE_to_DM_EMPLOYEE_STATUS | `[DM_EMPLOYEE::STATUS_ID] = [DM_EMPLOYEE_STATUS::STATUS_ID]` | DM_EMPLOYEE | DM_EMPLOYEE_STATUS |

**Out-of-scope joins (skipped):**
- `DM_PRODUCT_to_DM_SUPPLIER` — `DM_SUPPLIER` not in `model_tables`
- `DM_EMPLOYEE_to_DM_EMPLOYEE_STATUS` — `DM_EMPLOYEE_STATUS` not in `model_tables`

→ 8 in-scope relationships remain.

---

## Step 3 — Detect Case Sensitivity and Column Issues

Query `INFORMATION_SCHEMA.COLUMNS` for all 8 tables. Key findings:

1. **Case-sensitive column:** `DM_DATE_DIM.date` — lowercase in Snowflake → requires
   quoting or wrapper view
2. **Physical column typo:** `DM_ORDER_DETAIL.RRDER_ID` — the TML references `ORDER_ID`
   but the actual Snowflake column is `RRDER_ID`
3. **FK/PK name conflicts:** Multiple tables share the same join column names:
   - `PRODUCT_ID` in DM_ORDER_DETAIL, DM_INVENTORY, and DM_PRODUCT
   - `CUSTOMER_ID` in DM_ORDER and DM_CUSTOMER
   - `EMPLOYEE_ID` in DM_ORDER and DM_EMPLOYEE
   - `ORDER_ID` in DM_ORDER_DETAIL and DM_ORDER
   - `CATEGORY_ID` in DM_PRODUCT and DM_CATEGORY
4. **Same table joined from two parents:** `DM_DATE_DIM` is joined from both `DM_ORDER`
   (on ORDER_DATE) and `DM_INVENTORY` (on BALANCE_DATE). Use a **single** shared
   wrapper view so both fact tables resolve to the same date dimension — this enables
   cross-domain queries like "sales and inventory balance last quarter"

---

## Step 4 — Create Wrapper Views

All three issues above require wrapper views in a new schema `DUNDERMIFFLIN.PUBLIC_SV`.

**Why wrapper views are needed:**
- Case-sensitive `date` column cannot be used bare in `primary_key.columns` or
  `relationship_columns` (Cortex Analyst error 392700)
- FK columns sharing names with PK columns must be renamed to be globally unique
- `DM_DATE_DIM` needs a single wrapper view with the case-sensitive column uppercased

**Wrapper view DDL** (all batched in a single SQL call):

```sql
CREATE SCHEMA IF NOT EXISTS DUNDERMIFFLIN.PUBLIC_SV;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER AS
SELECT ORDER_ID, CUSTOMER_ID AS DM_ORDER_CUSTOMER_ID,
       EMPLOYEE_ID AS DM_ORDER_EMPLOYEE_ID,
       ORDER_DATE AS DM_ORDER_ORDER_DATE,
       REQUIRED_DATE, SHIPPED_DATE, SHIPPER_ID, FREIGHT,
       SHIP_NAME, SHIP_ADDRESS, SHIP_CITY, SHIP_REGION,
       SHIP_POSTAL_CODE, SHIP_COUNTRY
FROM DUNDERMIFFLIN.PUBLIC.DM_ORDER;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL AS
SELECT RRDER_ID AS DM_ORDER_DETAIL_ORDER_ID,
       PRODUCT_ID AS DM_ORDER_DETAIL_PRODUCT_ID,
       UNIT_PRICE, QUANTITY, DISCOUNT, LINE_TOTAL
FROM DUNDERMIFFLIN.PUBLIC.DM_ORDER_DETAIL;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_CUSTOMER AS
SELECT * FROM DUNDERMIFFLIN.PUBLIC.DM_CUSTOMER;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_EMPLOYEE AS
SELECT * FROM DUNDERMIFFLIN.PUBLIC.DM_EMPLOYEE;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_PRODUCT AS
SELECT PRODUCT_ID, PRODUCT_NAME, PRODUCT_DESCRIPTION,
       SUPPLIER_ID, CATEGORY_ID AS DM_PRODUCT_CATEGORY_ID,
       QUANTITY_PER_UNIT, UNIT_PRICE AS DM_PRODUCT_UNIT_PRICE,
       UNITS_IN_STOCK, UNITS_ON_ORDER, REORDER_LEVEL,
       DISCONTINUED_FLAG
FROM DUNDERMIFFLIN.PUBLIC.DM_PRODUCT;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_CATEGORY AS
SELECT * FROM DUNDERMIFFLIN.PUBLIC.DM_CATEGORY;

-- Single shared date dim (joined from both DM_ORDER and DM_INVENTORY)
CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_DATE_DIM AS
SELECT "date" AS DATE_VALUE FROM DUNDERMIFFLIN.PUBLIC.DM_DATE_DIM;

CREATE OR REPLACE VIEW DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY AS
SELECT BALANCE_DATE AS DM_INVENTORY_BALANCE_DATE,
       PRODUCT_ID AS DM_INVENTORY_PRODUCT_ID,
       FILLED_INVENTORY, OFFSET_BALANCE_DATE
FROM DUNDERMIFFLIN.PUBLIC.DM_INVENTORY;
```

**Key decisions:**
- FK columns renamed with table prefix: `CUSTOMER_ID` → `DM_ORDER_CUSTOMER_ID`
- `DM_DATE_DIM` kept as a single shared view — case-sensitive `"date"` uppercased to `DATE_VALUE`
- Typo `RRDER_ID` renamed to `DM_ORDER_DETAIL_ORDER_ID`

---

## Step 5 — Translate Formulas

**Formula 1: `Employee`** (ATTRIBUTE formula)

```
concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )
```

Translation:
- `concat(a, b, c)` → `CONCAT(a, b, c)` (direct mapping)
- `[DM_EMPLOYEE::LAST_NAME]` → `dm_employee.LAST_NAME`
- `[DM_EMPLOYEE::FIRST_NAME]` → `dm_employee.FIRST_NAME`
- Result: `CONCAT(dm_employee.LAST_NAME, ', ', dm_employee.FIRST_NAME)`

✓ Translatable — add as `dimensions` entry on `dm_employee` (ATTRIBUTE type).

---

**Formula 2: `# Employees`**

```
count ( [DM_ORDER::EMPLOYEE_ID] )
```

Translation:
- `count(...)` → `COUNT(...)`
- `[DM_ORDER::EMPLOYEE_ID]` → `dm_order.DM_ORDER_EMPLOYEE_ID` (renamed in wrapper)
- Result: `COUNT(dm_order.DM_ORDER_EMPLOYEE_ID)`

✓ Translatable — add as `metrics` entry on `dm_order`.

---

**Formula 3: `Inventory Balance`** (semi-additive)

```
last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::date] } )
```

Translation:
- `last_value(sum(measure), query_groups(), {date_col})` matches the semi-additive
  pattern → use `non_additive_dimensions`
- The inner `sum(FILLED_INVENTORY)` becomes `SUM(dm_inventory.FILLED_INVENTORY)`
- The `{date_col}` (`DM_DATE_DIM::date`) identifies the non-additive dimension — this
  is the **joined** date dimension table, not the local FK column
- Result: metric with `non_additive_dimensions` referencing the joined date dim's
  time dimension (`dm_date_dim.date_value`)

✓ Translatable — use `non_additive_dimensions` referencing the joined date table.
No `facts` section is needed as long as the metric name does not collide with the
physical column name (case-insensitive).

```yaml
metrics:
- name: inventory_balance
  expr: SUM(dm_inventory.FILLED_INVENTORY)
  non_additive_dimensions:
  - table: dm_date_dim
    dimension: date_value
    sort_direction: ascending
    nulls_position: last
```

**Important:** The `non_additive_dimensions` should reference the **joined date
dimension table** (e.g. `dm_date_dim.date_value`), not a local FK column on the
fact table. Use a **single shared date dimension** when multiple fact tables
(e.g. orders and inventory) join to the same date table — this allows Cortex Analyst
to answer cross-domain questions like "sales and inventory balance last quarter"
through one shared time dimension. Include `nulls_position: last` to match the
ThoughtSpot `last_value` behaviour.

**Naming:** The metric name must not collide (case-insensitive) with the physical
column name. E.g. if the column is `FILLED_INVENTORY`, don't name the metric
`filled_inventory` — use a distinct name like `inventory_balance`. If a name
collision is unavoidable, use a `facts` entry as an intermediary to break the cycle.

---

**Formula 4: `Category Quantity`** (LOD / group_aggregate)

```
sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) ) )
```

Translation:
- `group_aggregate(sum(x), {dim}, query_filters())` → `SUM(x) OVER (PARTITION BY dim)`
- The outer `sum(...)` wrapping the group_aggregate is idempotent when the outer and
  inner aggregation match — the window function already computes at the partition grain
- `[DM_ORDER_DETAIL::QUANTITY]` → `dm_order_detail.quantity` (references the metric)
- `[DM_CATEGORY::CATEGORY_NAME]` → `dm_category.product_category` (references the dimension)
- Result: `SUM(dm_order_detail.quantity) OVER (PARTITION BY dm_category.product_category)`

✓ Translatable — add as `metrics` entry on `dm_order_detail` (where `quantity` is defined).

---

**Formula 5: `Product to Category Contribution Ratio`**

```
sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , { [DM_INVENTORY::PRODUCT_ID] } , query_filters ( ) ) ) / [formula_Category Quantity]
```

Translation:
- Numerator: `group_aggregate(sum(QUANTITY), {PRODUCT_ID}, query_filters())` →
  `SUM(dm_order_detail.quantity) OVER (PARTITION BY ...)` — but at the product level,
  this is the row-level quantity in the context of the query
- Denominator: `[formula_Category Quantity]` → the `category_quantity` metric above
- Combined: `DIV0(dm_order_detail.quantity, SUM(dm_order_detail.quantity) OVER (PARTITION BY dm_category.product_category))`
- Uses `DIV0` to avoid division-by-zero errors

✓ Translatable — add as `metrics` entry on `dm_order_detail`.

---

## Step 6 — Build Relationships

8 relationships from the in-scope joins. Note how renamed FK columns appear in
`left_column` while PK columns remain unchanged in `right_column`:

```yaml
relationships:
- name: dm_order_detail_to_dm_order
  left_table: dm_order_detail
  right_table: dm_order
  relationship_columns:
  - left_column: DM_ORDER_DETAIL_ORDER_ID    # renamed from RRDER_ID
    right_column: ORDER_ID
- name: dm_order_detail_to_dm_product
  left_table: dm_order_detail
  right_table: dm_product
  relationship_columns:
  - left_column: DM_ORDER_DETAIL_PRODUCT_ID  # renamed from PRODUCT_ID
    right_column: PRODUCT_ID
- name: dm_order_to_dm_customer
  left_table: dm_order
  right_table: dm_customer
  relationship_columns:
  - left_column: DM_ORDER_CUSTOMER_ID        # renamed from CUSTOMER_ID
    right_column: CUSTOMER_ID
- name: dm_order_to_dm_date_dim
  left_table: dm_order
  right_table: dm_date_dim                   # single shared date dim
  relationship_columns:
  - left_column: DM_ORDER_ORDER_DATE         # renamed from ORDER_DATE
    right_column: DATE_VALUE                 # renamed from "date"
- name: dm_order_to_dm_employee
  left_table: dm_order
  right_table: dm_employee
  relationship_columns:
  - left_column: DM_ORDER_EMPLOYEE_ID        # renamed from EMPLOYEE_ID
    right_column: EMPLOYEE_ID
- name: dm_product_to_dm_category
  left_table: dm_product
  right_table: dm_category
  relationship_columns:
  - left_column: DM_PRODUCT_CATEGORY_ID      # renamed from CATEGORY_ID
    right_column: CATEGORY_ID
- name: dm_inventory_to_dm_date_dim
  left_table: dm_inventory
  right_table: dm_date_dim                   # same shared date dim
  relationship_columns:
  - left_column: DM_INVENTORY_BALANCE_DATE   # renamed from BALANCE_DATE
    right_column: DATE_VALUE
- name: dm_inventory_to_dm_product
  left_table: dm_inventory
  right_table: dm_product
  relationship_columns:
  - left_column: DM_INVENTORY_PRODUCT_ID     # renamed from PRODUCT_ID
    right_column: PRODUCT_ID
```

Tables that appear as `right_table` need `primary_key`:
- `dm_order` → `ORDER_ID`
- `dm_product` → `PRODUCT_ID`
- `dm_customer` → `CUSTOMER_ID`
- `dm_employee` → `EMPLOYEE_ID`
- `dm_category` → `CATEGORY_ID`
- `dm_date_dim` → `DATE_VALUE`

---

## Step 7 — Output — Snowflake Semantic View YAML

```yaml
name: dunder_mifflin_sales_inventory
description: "Migrated from ThoughtSpot: Dunder Mifflin Sales & Inventory."

tables:
- name: dm_order
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_ORDER
  primary_key:
    columns:
    - ORDER_ID
  dimensions:
  - name: order_id
    expr: dm_order.ORDER_ID
    data_type: NUMBER
  - name: dm_order_customer_id
    expr: dm_order.DM_ORDER_CUSTOMER_ID
    data_type: NUMBER
  - name: dm_order_employee_id
    expr: dm_order.DM_ORDER_EMPLOYEE_ID
    data_type: NUMBER
  - name: ship_name
    expr: dm_order.SHIP_NAME
    data_type: TEXT
  - name: ship_address
    expr: dm_order.SHIP_ADDRESS
    data_type: TEXT
  - name: ship_city
    expr: dm_order.SHIP_CITY
    data_type: TEXT
  - name: ship_region
    expr: dm_order.SHIP_REGION
    data_type: TEXT
  - name: ship_postal_code
    expr: dm_order.SHIP_POSTAL_CODE
    data_type: NUMBER
  - name: ship_country
    expr: dm_order.SHIP_COUNTRY
    data_type: TEXT
  time_dimensions:
  - name: dm_order_order_date
    expr: dm_order.DM_ORDER_ORDER_DATE
    data_type: DATE
  - name: required_date
    expr: dm_order.REQUIRED_DATE
    data_type: DATE
  - name: shipped_date
    expr: dm_order.SHIPPED_DATE
    data_type: DATE
  metrics:
  - name: employees
    synonyms: ["# Employees"]
    expr: COUNT(dm_order.DM_ORDER_EMPLOYEE_ID)
  - name: freight
    expr: SUM(dm_order.FREIGHT)

- name: dm_order_detail
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_ORDER_DETAIL
  dimensions:
  - name: dm_order_detail_order_id
    expr: dm_order_detail.DM_ORDER_DETAIL_ORDER_ID
    data_type: NUMBER
  - name: dm_order_detail_product_id
    expr: dm_order_detail.DM_ORDER_DETAIL_PRODUCT_ID
    data_type: NUMBER
  - name: discount
    expr: dm_order_detail.DISCOUNT
    data_type: TEXT
  metrics:
  - name: unit_price
    synonyms: ["Unit Price"]
    expr: AVG(dm_order_detail.UNIT_PRICE)
  - name: quantity
    synonyms: ["Quantity"]
    expr: SUM(dm_order_detail.QUANTITY)
  - name: amount
    synonyms: ["Amount", "Line Total"]
    expr: SUM(dm_order_detail.LINE_TOTAL)
  - name: category_quantity
    synonyms: ["Category Quantity"]
    expr: "SUM(dm_order_detail.quantity) OVER (PARTITION BY dm_category.product_category)"
  - name: product_to_category_contribution_ratio
    synonyms: ["Product to Category Contribution Ratio"]
    expr: "DIV0(dm_order_detail.quantity, SUM(dm_order_detail.quantity) OVER (PARTITION BY dm_category.product_category))"

- name: dm_customer
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_CUSTOMER
  primary_key:
    columns:
    - CUSTOMER_ID
  dimensions:
  - name: customer_id
    expr: dm_customer.CUSTOMER_ID
    data_type: NUMBER
  - name: customer_code
    synonyms: ["Customer Code"]
    expr: dm_customer.CUSTOMER_CODE
    data_type: TEXT
  - name: customer_name
    synonyms: ["Customer Name", "Company Name"]
    expr: dm_customer.COMPANY_NAME
    data_type: TEXT
  - name: customer_state
    synonyms: ["Customer State"]
    expr: dm_customer.STATE
    data_type: TEXT
  - name: customer_zipcode
    synonyms: ["Customer Zipcode"]
    expr: dm_customer.ZIPCODE
    data_type: NUMBER

- name: dm_employee
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_EMPLOYEE
  primary_key:
    columns:
    - EMPLOYEE_ID
  dimensions:
  - name: employee_id
    expr: dm_employee.EMPLOYEE_ID
    data_type: NUMBER
  - name: employee
    synonyms: ["Employee", "Employee Name"]
    expr: "CONCAT(dm_employee.LAST_NAME, ', ', dm_employee.FIRST_NAME)"
    data_type: TEXT
  - name: last_name
    expr: dm_employee.LAST_NAME
    data_type: TEXT
  - name: first_name
    expr: dm_employee.FIRST_NAME
    data_type: TEXT
  - name: title
    expr: dm_employee.TITLE
    data_type: TEXT

- name: dm_product
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_PRODUCT
  primary_key:
    columns:
    - PRODUCT_ID
  dimensions:
  - name: product_id
    synonyms: ["Product ID"]
    expr: dm_product.PRODUCT_ID
    data_type: NUMBER
  - name: product_name
    synonyms: ["Product Name"]
    expr: dm_product.PRODUCT_NAME
    data_type: TEXT
  - name: product_description
    synonyms: ["Product Description"]
    expr: dm_product.PRODUCT_DESCRIPTION
    data_type: TEXT
  - name: dm_product_category_id
    expr: dm_product.DM_PRODUCT_CATEGORY_ID
    data_type: NUMBER

- name: dm_category
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_CATEGORY
  primary_key:
    columns:
    - CATEGORY_ID
  dimensions:
  - name: category_id
    expr: dm_category.CATEGORY_ID
    data_type: NUMBER
  - name: product_category
    synonyms: ["Product Category", "Category Name"]
    expr: dm_category.CATEGORY_NAME
    data_type: TEXT

- name: dm_date_dim
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_DATE_DIM
  primary_key:
    columns:
    - DATE_VALUE
  time_dimensions:
  - name: date_value
    synonyms: ["Transaction Date", "Order Date", "Balance Date", "Inventory Date"]
    expr: dm_date_dim.DATE_VALUE
    data_type: DATE

- name: dm_inventory
  base_table:
    database: DUNDERMIFFLIN
    schema: PUBLIC_SV
    table: DM_INVENTORY
  dimensions:
  - name: dm_inventory_balance_date
    expr: dm_inventory.DM_INVENTORY_BALANCE_DATE
    data_type: DATE
  - name: dm_inventory_product_id
    expr: dm_inventory.DM_INVENTORY_PRODUCT_ID
    data_type: NUMBER
  metrics:
  - name: total_filled_inventory
    synonyms: ["Filled Inventory"]
    expr: SUM(dm_inventory.FILLED_INVENTORY)
  - name: inventory_balance
    synonyms: ["Inventory Balance"]
    expr: SUM(dm_inventory.FILLED_INVENTORY)
    non_additive_dimensions:
    - table: dm_date_dim
      dimension: date_value
      sort_direction: ascending
      nulls_position: last

relationships:
- name: dm_order_detail_to_dm_order
  left_table: dm_order_detail
  right_table: dm_order
  relationship_columns:
  - left_column: DM_ORDER_DETAIL_ORDER_ID
    right_column: ORDER_ID
- name: dm_order_detail_to_dm_product
  left_table: dm_order_detail
  right_table: dm_product
  relationship_columns:
  - left_column: DM_ORDER_DETAIL_PRODUCT_ID
    right_column: PRODUCT_ID
- name: dm_order_to_dm_customer
  left_table: dm_order
  right_table: dm_customer
  relationship_columns:
  - left_column: DM_ORDER_CUSTOMER_ID
    right_column: CUSTOMER_ID
- name: dm_order_to_dm_date_dim
  left_table: dm_order
  right_table: dm_date_dim
  relationship_columns:
  - left_column: DM_ORDER_ORDER_DATE
    right_column: DATE_VALUE
- name: dm_order_to_dm_employee
  left_table: dm_order
  right_table: dm_employee
  relationship_columns:
  - left_column: DM_ORDER_EMPLOYEE_ID
    right_column: EMPLOYEE_ID
- name: dm_product_to_dm_category
  left_table: dm_product
  right_table: dm_category
  relationship_columns:
  - left_column: DM_PRODUCT_CATEGORY_ID
    right_column: CATEGORY_ID
- name: dm_inventory_to_dm_date_dim
  left_table: dm_inventory
  right_table: dm_date_dim
  relationship_columns:
  - left_column: DM_INVENTORY_BALANCE_DATE
    right_column: DATE_VALUE
- name: dm_inventory_to_dm_product
  left_table: dm_inventory
  right_table: dm_product
  relationship_columns:
  - left_column: DM_INVENTORY_PRODUCT_ID
    right_column: PRODUCT_ID
```

---

## Key patterns from this example

1. **Model format uses `referencing_join`.** Unlike Worksheets (which have inline `on`
   conditions), Models reference joins by name. Resolve by searching all Table TML
   `joins_with[]` entries for the matching `name` field.

2. **`model_tables` is the scope filter.** Table TML `joins_with[]` may reference tables
   not in the model (e.g. `DM_SUPPLIER`). Skip any join where either side is not in
   `model_tables`.

3. **Case-sensitive columns require wrapper views.** `DM_DATE_DIM.date` (lowercase)
   cannot be used bare in `primary_key.columns` or `relationship_columns`. Create a
   wrapper view that renames it to uppercase (`DATE_VALUE`).

4. **FK/PK name conflicts require FK renaming.** When `PRODUCT_ID` appears in both
   `DM_ORDER_DETAIL` (FK) and `DM_PRODUCT` (PK), rename the FK in the wrapper view
   to `DM_ORDER_DETAIL_PRODUCT_ID`. The PK side keeps the original name.

5. **Same table joined from multiple parents → use a single shared view.** `DM_DATE_DIM`
   is joined from both `DM_ORDER` and `DM_INVENTORY` with different FK columns. Use a
   **single** wrapper view (`DM_DATE_DIM`) so both fact tables share one time dimension.
   This enables cross-domain queries (e.g. "sales and inventory balance last quarter").
   Only split into separate aliases if the tables genuinely represent different date
   concepts that should never be queried together.

6. **Semi-additive metrics use `non_additive_dimensions`.** The `last_value`
   pattern translates to a metric with `non_additive_dimensions`. The metric can
   reference the physical column directly — no `facts` section needed. The non-additive
   dimension should reference the **joined date dimension table** (e.g.
   `dm_date_dim.date_value`), not a local FK column on the fact table.
   Include `nulls_position: last` to match ThoughtSpot's `last_value` behaviour.

7. **Metric naming must avoid cycles.** Snowflake's cycle detection is
   case-insensitive. If the physical column is `FILLED_INVENTORY`, don't name the
   metric `filled_inventory` — use a distinct name like `inventory_balance`. If a
   name collision is unavoidable, introduce a `facts` entry as an intermediary.

8. **`group_aggregate` translates to `OVER (PARTITION BY)`.** The pattern
   `group_aggregate(sum(x), {dim}, query_filters())` becomes
   `SUM(x) OVER (PARTITION BY dim)`. Cross-table references are supported — the
   PARTITION BY dimension can be on a joined table.

9. **Percentage contribution uses `DIV0`.** When translating ratio formulas that divide
   by a `group_aggregate` result, use `DIV0` to handle division-by-zero safely.

10. **Physical column typos are handled in wrapper views.** `RRDER_ID` (typo for
    `ORDER_ID`) is renamed to `DM_ORDER_DETAIL_ORDER_ID` in the wrapper view, making
    the semantic view clean regardless of the underlying data issue.

11. **Batch all wrapper view DDL into one SQL call.** Creating N views requires N+1 UI
    confirmations if done separately. Combine `CREATE SCHEMA` and all `CREATE VIEW`
    statements into a single multi-statement call.
