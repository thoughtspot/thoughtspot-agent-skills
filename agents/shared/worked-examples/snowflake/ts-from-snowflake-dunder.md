# Worked Example — Dunder Mifflin Sales & Inventory SV → ThoughtSpot Model

End-to-end conversion of `DUNDERMIFFLIN.PUBLIC.DUNDER_MIFFLIN_SALES_INVENTORY` to a
ThoughtSpot Model named `TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY`.

This example complements [ts-from-snowflake.md](ts-from-snowflake.md) (BIRD example)
by exercising features that example does NOT cover:

- Multi-value `with synonyms=(...)` clauses (mapped to display name + `properties.synonyms`)
- Per-dimension/metric `comment='...'` clauses (mapped to column `description`)
- Per-table `comment='...'` clauses in the `tables(...)` block (mapped to TS Table TML `table.description`)
- Two semi-additive metrics — closing (asc → `last_value`) and opening (desc → `first_value`)
- A `COUNT(DISTINCT ...)` metric translated to a `unique count(...)` formula (NOT `count_distinct(...)`)
- A computed dimension using `CONCAT(...)` translated with `concat()` (NOT `+` for strings)
- Connection misconfiguration repair: TS Table objects pointing to the wrong Snowflake
  schema (`PUBLIC_SV` vs `PUBLIC`) — Table TML imports failed until `table.schema` was
  corrected alongside the description update

Verified end-to-end against `se-thoughtspot` on 2026-04-28. Final model GUID:
`aee6593d-abf0-4c11-b380-d265181fa9b0`.

---

## Input — Semantic View DDL (abbreviated)

```sql
create or replace semantic view DUNDER_MIFFLIN_SALES_INVENTORY
    tables (
        DUNDERMIFFLIN.PUBLIC.DM_CATEGORY primary key (CATEGORY_ID)
            comment='Product categories used to classify products in the catalog',
        DUNDERMIFFLIN.PUBLIC.DM_CUSTOMER primary key (CUSTOMER_ID)
            comment='Customer master data including company name, location, and contact information',
        DUNDERMIFFLIN.PUBLIC_SV.DM_DATE_DIM primary key (DATE)
            comment='Date dimension table used for time-based analysis of orders and inventory',
        DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY
            comment='Daily inventory balance snapshots showing stock levels by product and date',
        ...
    )
    relationships (
        DM_INVENTORY_TO_DM_DATE_DIM as DM_INVENTORY(BALANCE_DATE) references DM_DATE_DIM(DATE),
        DM_ORDER_DETAIL_TO_DM_ORDER as DM_ORDER_DETAIL(RRDER_ID) references DM_ORDER(ORDER_ID),
        ...
    )
    dimensions (
        DM_CATEGORY.CATEGORY as dm_category.CATEGORY_NAME
            with synonyms=('Product Category','Category Name','PRODUCT_CATEGORY')
            comment='Name of the product category (e.g. Paper, Pens, Furniture)',
        DM_CUSTOMER.ZIPCODE as dm_customer.ZIPCODE
            with synonyms=('Customer Zipcode','Zip Code','Postal Code','CUSTOMER_ZIPCODE')
            comment='Postal zip code of the customer address',
        DM_EMPLOYEE.EMPLOYEE as CONCAT(dm_employee.LAST_NAME, ', ', dm_employee.FIRST_NAME)
            with synonyms=('Sales Rep','Salesperson','Representative','Employee Name')
            comment='Full name of the employee in Last, First format',
        ...
    )
    metrics (
        DM_INVENTORY.CLOSING_STOCK_BALANCE non additive by (DM_INVENTORY.BALANCE_DATE asc nulls last)
            as SUM(dm_inventory.FILLED_INVENTORY)
            with synonyms=('Inventory Balance','Stock Level','On Hand','Closing Stock','Ending Inventory')
            comment='Latest (closing) inventory quantity on hand. Semi-additive — takes most recent balance date.',
        DM_INVENTORY.OPENING_STOCK_BALANCE non additive by (DM_INVENTORY.BALANCE_DATE desc nulls last)
            as SUM(dm_inventory.FILLED_INVENTORY)
            with synonyms=('Opening Inventory','Beginning Inventory','Starting Stock','Beginning Stock')
            comment='Earliest (opening) inventory quantity on hand. Semi-additive — takes earliest balance date.',
        DM_ORDER.EMPLOYEE_COUNT
            as COUNT(DISTINCT dm_order.DM_ORDER_EMPLOYEE_ID)
            with synonyms=('Number of Employees','EMPLOYEES')
            comment='Count of distinct employees who handled orders',
        DM_ORDER_DETAIL.CATEGORY_QUANTITY
            as SUM(dm_order_detail.QUANTITY) OVER (PARTITION BY dm_category.category)
            comment='Running total of units sold within each product category.',
        DM_ORDER_DETAIL.CATEGORY_CONTRIBUTION
            as DIV0(dm_order_detail.QUANTITY,
                    SUM(dm_order_detail.QUANTITY) OVER (PARTITION BY dm_category.category))
            with synonyms=('Product to Category Contribution Ratio','Product Share')
            comment='Ratio of a products quantity sold to the total quantity sold in its category.',
        ...
    )
    comment='Dunder Mifflin Sales & Inventory semantic view providing comprehensive analysis...';
```

---

## Step 6D — Apply table descriptions and fix schema mismatches

Three of the eight TS Table objects (`DM_EMPLOYEE`, `DM_CATEGORY`, `DM_CUSTOMER`) had
`table.schema: PUBLIC_SV` in their TML, but the actual Snowflake objects live in
`PUBLIC`. The first Table-TML import attempt — adding only `table.description` — failed
with `External table with name: DUNDERMIFFLIN.PUBLIC_SV.DM_EMPLOYEE does not exist in
connection APJ_BIRD`.

**Repair:** in the same Table-TML update, set `table.schema: PUBLIC` alongside the
description, then re-run `ts tml import --no-create-new`. All eight tables updated
successfully on the second attempt.

```python
for tbl in tables_to_update:
    tml = exported_tmls[tbl.name]
    tml["table"]["description"] = sv_table_comments[tbl.name]
    if tbl.name in ("DM_EMPLOYEE", "DM_CATEGORY", "DM_CUSTOMER"):
        tml["table"]["schema"] = "PUBLIC"   # was PUBLIC_SV — wrong
    payloads.append({"guid": tbl.guid, "table": tml["table"]})
```

**Lesson:** when an SV has table-level `comment='...'` clauses and the live Snowflake
schema differs from what the TS Table object claims, fix both fields together. The
schema mismatch is otherwise undetected — Model TML imports succeed despite the broken
Table TMLs because only Table imports validate against the connection.

---

## Step 8 — Model TML Highlights

### Synonyms placement (CRITICAL)

```yaml
columns:
- name: "Product Category"                          # ← first synonym from SV
  column_id: DM_CATEGORY::CATEGORY_NAME
  description: "Name of the product category (e.g. Paper, Pens, Furniture)"
  properties:
    column_type: ATTRIBUTE
    synonyms:                                       # ← under properties:, NOT root
    - "Category Name"
    - "PRODUCT_CATEGORY"
    synonym_type: USER_DEFINED                      # ← required when synonyms[] is set
```

Top-level `synonyms:` (sibling of `column_id`) imports without error but is silently
dropped — the next export will not contain it. Always nest under `properties:`.

### `count(distinct ...)` — formula, not column

`EMPLOYEE_COUNT = COUNT(DISTINCT dm_order.DM_ORDER_EMPLOYEE_ID)` cannot be a column
MEASURE because `DM_ORDER::DM_ORDER_EMPLOYEE_ID` already exists as the FK ATTRIBUTE
(duplicate `column_id` rejected). Convert to a formula:

```yaml
formulas:
- id: formula_Number of Employees
  name: "Number of Employees"
  expr: "unique count ( [DM_ORDER::DM_ORDER_EMPLOYEE_ID] )"   # NOT count_distinct(...)
  properties:
    column_type: MEASURE

columns:
- name: "Number of Employees"
  formula_id: formula_Number of Employees
  description: "Count of distinct employees who handled orders"
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX
    synonyms: ["EMPLOYEES"]
    synonym_type: USER_DEFINED
```

`count_distinct(...)` is rejected by the TS formula parser:
`Search did not find "count_distinct (" in your data or metadata`. Always use
`unique count` (with a space, not an underscore).

### `CONCAT` formula — `concat()`, not `+`

`DM_EMPLOYEE.EMPLOYEE = CONCAT(LAST_NAME, ', ', FIRST_NAME)` translates to:

```yaml
formulas:
- id: formula_Sales Rep
  name: "Sales Rep"
  expr: "concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )"
  properties:
    column_type: ATTRIBUTE
```

`+` does not concatenate strings in TS formulas (numeric only). The parser rejects
`[a] + ', ' + [b]` with `Search did not find "+ ', ' +"`.

### Semi-additive — `last_value` and `first_value`

```yaml
formulas:
- id: formula_Inventory Balance
  name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_INVENTORY::BALANCE_DATE] } )

- id: formula_Opening Inventory
  name: "Opening Inventory"
  expr: >-
    first_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_INVENTORY::BALANCE_DATE] } )
```

Direction matrix:

| SV DDL | TS formula |
|---|---|
| `non additive by (col asc nulls last)` | `last_value(...)` |
| `non additive by (col desc nulls last)` | `first_value(...)` |

The `>-` block scalar is required because the formula contains `{ ... }` (curly
braces are flow-mapping start characters in inline YAML).

### Window functions — `group_sum` and `safe_divide`

```yaml
- id: formula_Category Quantity
  expr: "group_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_CATEGORY::CATEGORY_NAME] )"

- id: formula_Product to Category Contribution Ratio
  expr: "safe_divide ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , group_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_CATEGORY::CATEGORY_NAME] ) )"
```

Translates the SV `SUM(qty) OVER (PARTITION BY category)` and
`DIV0(qty, SUM(qty) OVER (PARTITION BY category))` patterns.

---

## Step 11 — Import — gotchas

### Updating in place needs `--no-create-new`

```bash
ts tml import --policy ALL_OR_NONE --no-create-new --profile se-thoughtspot < model.tml
```

Without `--no-create-new`, ThoughtSpot ignores the supplied `guid:` at document root
and creates a new model with a fresh GUID. The first attempt during this session
created a duplicate model (`55d6d77c-...`) which was deleted before retry. Always pair
`guid:` at root with `--no-create-new` for in-place updates.

### Order: tables, then model

Update Table TMLs first (descriptions, schema fixes), then import the model. The
model import would otherwise see stale Table metadata and fail to resolve column IDs.

---

## Final Result

- **Model:** `TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY`
- **GUID:** `aee6593d-abf0-4c11-b380-d265181fa9b0`
- **Tables:** 8 (all reused from APJ_BIRD connection)
- **Columns:** 31 (23 ATTRIBUTE + 7 MEASURE + 1 attribute formula + 6 measure formulas)
- **Columns with description:** 31 / 31
- **Columns with synonyms:** 18 / 31 (those with multi-value SV synonyms)

Side effects (one-time fixes captured during the conversion):

- `DM_ORDER.DM_ORDER_ORDER_DATE` → `ORDER_DATE` (column rename to match Snowflake)
- `DM_ORDER_DETAIL.DM_ORDER_DETAIL_ORDER_ID` → `RRDER_ID` (sic — matches Snowflake)
- `DM_INVENTORY.DM_INVENTORY_BALANCE_DATE` → `BALANCE_DATE`
- `DM_DATE_DIM.DATE_VALUE` → `DATE`
- `table.schema: PUBLIC_SV` → `PUBLIC` on DM_EMPLOYEE / DM_CATEGORY / DM_CUSTOMER
