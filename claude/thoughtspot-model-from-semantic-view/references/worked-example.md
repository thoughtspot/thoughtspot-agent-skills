# Worked Example — Snowflake Semantic View → ThoughtSpot Model

End-to-end conversion of `DUNDERMIFFLIN.PUBLIC.DUNDER_MIFFLIN_SALES` to a
ThoughtSpot Model named `TEST_SV_Dunder Mifflin Sales`. This is a Scenario A
conversion (model built on the underlying physical tables, not views).

---

## Input — Semantic View DDL (abbreviated)

```sql
create or replace semantic view DUNDERMIFFLIN.PUBLIC.DUNDER_MIFFLIN_SALES
  tables (
    DM_CUSTOMER base table DUNDERMIFFLIN.PUBLIC.DM_CUSTOMER
      primary key ( CUSTOMER_ID )
      dimensions (
        CUSTOMER_ID data_type = NUMBER expr = DM_CUSTOMER.CUSTOMER_ID,
        CUSTOMER_NAME aliases = ( "Customer Name", customer ) data_type = TEXT
          expr = DM_CUSTOMER.CUSTOMER_NAME,
        LOCALE data_type = TEXT expr = DM_CUSTOMER.LOCALE,
        COUNTRY_NAME aliases = ( "Country" ) data_type = TEXT
          expr = DM_LOCALE_COUNTRY.COUNTRY_NAME
      ),
    DM_LOCALE_COUNTRY base table DUNDERMIFFLIN.PUBLIC.DM_LOCALE_COUNTRY
      primary key ( LOCALE )
      dimensions (
        LOCALE data_type = TEXT expr = DM_LOCALE_COUNTRY.LOCALE,
        COUNTRY_NAME aliases = ( "Country Name" ) data_type = TEXT
          expr = DM_LOCALE_COUNTRY.COUNTRY_NAME
      ),
    DM_ORDERS base table DUNDERMIFFLIN.PUBLIC.DM_ORDERS
      dimensions (
        ORDER_ID data_type = NUMBER expr = DM_ORDERS.ORDER_ID,
        ORDER_DATE aliases = ( "Order Date" ) data_type = DATE
          expr = DM_ORDERS.ORDER_DATE,
        SHIP_DATE aliases = ( "Ship Date" ) data_type = DATE
          expr = DM_ORDERS.SHIP_DATE,
        CUSTOMER_ID data_type = NUMBER expr = DM_ORDERS.CUSTOMER_ID
      )
      metrics (
        order_duration_days aliases = ( "Order Duration (Days)" )
          expr = DATEDIFF( 'day', DM_ORDERS.ORDER_DATE, DM_ORDERS.SHIP_DATE )
      ),
    DM_ORDERDETAILS base table DUNDERMIFFLIN.PUBLIC.DM_ORDERDETAILS
      dimensions (
        ORDER_DETAIL_ID data_type = NUMBER expr = DM_ORDERDETAILS.ORDER_DETAIL_ID,
        ORDER_ID data_type = NUMBER expr = DM_ORDERDETAILS.ORDER_ID,
        PRODUCT_ID data_type = NUMBER expr = DM_ORDERDETAILS.PRODUCT_ID,
        UNIT_PRICE aliases = ( "Unit Price" ) data_type = NUMBER
          expr = DM_ORDERDETAILS.UNIT_PRICE,
        QUANTITY aliases = ( "Quantity" ) data_type = NUMBER
          expr = DM_ORDERDETAILS.QUANTITY
      )
      metrics (
        total_revenue aliases = ( "Total Revenue" )
          expr = SUM( DM_ORDERDETAILS.UNIT_PRICE * DM_ORDERDETAILS.QUANTITY )
      ),
    DM_PRODUCTS base table DUNDERMIFFLIN.PUBLIC.DM_PRODUCTS
      primary key ( PRODUCT_ID )
      dimensions (
        PRODUCT_ID data_type = NUMBER expr = DM_PRODUCTS.PRODUCT_ID,
        PRODUCT_NAME aliases = ( "Product Name" ) data_type = TEXT
          expr = DM_PRODUCTS.PRODUCT_NAME,
        CATEGORY aliases = ( "Category" ) data_type = TEXT
          expr = DM_PRODUCTS.CATEGORY
      )
  )
  relationships (
    dm_orders_to_dm_customer
      from DM_ORDERS key ( CUSTOMER_ID )
      to   DM_CUSTOMER key ( CUSTOMER_ID ),
    dm_customer_to_dm_locale_country
      from DM_CUSTOMER key ( LOCALE )
      to   DM_LOCALE_COUNTRY key ( LOCALE ),
    dm_orderdetails_to_dm_orders
      from DM_ORDERDETAILS key ( ORDER_ID )
      to   DM_ORDERS key ( ORDER_ID ),
    dm_orderdetails_to_dm_products
      from DM_ORDERDETAILS key ( PRODUCT_ID )
      to   DM_PRODUCTS key ( PRODUCT_ID )
  );
```

---

## Step 4: DDL Parse Results

**Tables:**

| Alias | Base Table | Primary Key | Is Join Target? |
|---|---|---|---|
| DM_CUSTOMER | DUNDERMIFFLIN.PUBLIC.DM_CUSTOMER | CUSTOMER_ID | YES |
| DM_LOCALE_COUNTRY | DUNDERMIFFLIN.PUBLIC.DM_LOCALE_COUNTRY | LOCALE | YES |
| DM_ORDERS | DUNDERMIFFLIN.PUBLIC.DM_ORDERS | — | YES (from DM_ORDERDETAILS) |
| DM_ORDERDETAILS | DUNDERMIFFLIN.PUBLIC.DM_ORDERDETAILS | — | NO (fact table) |
| DM_PRODUCTS | DUNDERMIFFLIN.PUBLIC.DM_PRODUCTS | PRODUCT_ID | YES |

**Fact table:** `DM_ORDERDETAILS` (not a `TO` target in any relationship).

**Relationships:**

| Name | From | From Key | To | To Key |
|---|---|---|---|---|
| dm_orders_to_dm_customer | DM_ORDERS | CUSTOMER_ID | DM_CUSTOMER | CUSTOMER_ID |
| dm_customer_to_dm_locale_country | DM_CUSTOMER | LOCALE | DM_LOCALE_COUNTRY | LOCALE |
| dm_orderdetails_to_dm_orders | DM_ORDERDETAILS | ORDER_ID | DM_ORDERS | ORDER_ID |
| dm_orderdetails_to_dm_products | DM_ORDERDETAILS | PRODUCT_ID | DM_PRODUCTS | PRODUCT_ID |

---

## Step 6A: ThoughtSpot Table Objects Found

Query: `ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile champ-staging`

| Physical Table | ThoughtSpot GUID |
|---|---|
| DM_CUSTOMER | `aaa-111` *(placeholder)* |
| DM_LOCALE_COUNTRY | `aaa-222` *(placeholder)* |
| DM_ORDERS | `aaa-333` *(placeholder)* |
| DM_ORDERDETAILS | `aaa-444` *(placeholder)* |
| DM_PRODUCTS | `aaa-555` *(placeholder)* |

---

## Step 7: Join Names from Table TML

For each relationship, export TML of the FROM table and find the matching join:

| Relationship | FROM table TML exported | Join name found |
|---|---|---|
| dm_orderdetails_to_dm_orders | DM_ORDERDETAILS | `dm_orderdetails_to_dm_orders` |
| dm_orderdetails_to_dm_products | DM_ORDERDETAILS | `dm_orderdetails_to_dm_products` |
| dm_orders_to_dm_customer | DM_ORDERS | `dm_orders_to_dm_customer` |
| dm_customer_to_dm_locale_country | DM_CUSTOMER | `dm_customer_to_dm_locale_country` |

---

## Step 9: Formula Translations

| Column | Semantic View EXPR | Type | Result |
|---|---|---|---|
| Order Duration (Days) | `DATEDIFF('day', DM_ORDERS.ORDER_DATE, DM_ORDERS.SHIP_DATE)` | formula | `diff_days ( [DM_ORDERS::SHIP_DATE] , [DM_ORDERS::ORDER_DATE] )` |
| Total Revenue | `SUM(DM_ORDERDETAILS.UNIT_PRICE * DM_ORDERDETAILS.QUANTITY)` | formula | `sum ( [DM_ORDERDETAILS::UNIT_PRICE] * [DM_ORDERDETAILS::QUANTITY] )` |

Note: `DATEDIFF` args are **reversed** — ThoughtSpot `diff_days(end, start)` maps to
`DATEDIFF('day', start, end)`.

---

## Output — ThoughtSpot Model TML

```yaml
model:
  name: "TEST_SV_Dunder Mifflin Sales"
  model_tables:
  - id: DM_ORDERDETAILS
    name: DM_ORDERDETAILS
    fqn: "aaa-444"
  - id: DM_ORDERS
    name: DM_ORDERS
    fqn: "aaa-333"
    referencing_join: dm_orderdetails_to_dm_orders
  - id: DM_CUSTOMER
    name: DM_CUSTOMER
    fqn: "aaa-111"
    referencing_join: dm_orders_to_dm_customer
  - id: DM_LOCALE_COUNTRY
    name: DM_LOCALE_COUNTRY
    fqn: "aaa-222"
    referencing_join: dm_customer_to_dm_locale_country
  - id: DM_PRODUCTS
    name: DM_PRODUCTS
    fqn: "aaa-555"
    referencing_join: dm_orderdetails_to_dm_products
  columns:
  - name: "Customer Name"
    column_id: DM_CUSTOMER::CUSTOMER_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "Locale"
    column_id: DM_CUSTOMER::LOCALE
    properties:
      column_type: ATTRIBUTE
  - name: "Country Name"
    column_id: DM_LOCALE_COUNTRY::COUNTRY_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "Order Date"
    column_id: DM_ORDERS::ORDER_DATE
    properties:
      column_type: ATTRIBUTE
  - name: "Ship Date"
    column_id: DM_ORDERS::SHIP_DATE
    properties:
      column_type: ATTRIBUTE
  - name: "Unit Price"
    column_id: DM_ORDERDETAILS::UNIT_PRICE
    properties:
      column_type: ATTRIBUTE
  - name: "Quantity"
    column_id: DM_ORDERDETAILS::QUANTITY
    properties:
      column_type: ATTRIBUTE
  - name: "Product Name"
    column_id: DM_PRODUCTS::PRODUCT_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "Category"
    column_id: DM_PRODUCTS::CATEGORY
    properties:
      column_type: ATTRIBUTE
  formulas:
  - name: "Order Duration (Days)"
    expr: "diff_days ( [DM_ORDERS::SHIP_DATE] , [DM_ORDERS::ORDER_DATE] )"
    properties:
      column_type: MEASURE
  - name: "Total Revenue"
    expr: "sum ( [DM_ORDERDETAILS::UNIT_PRICE] * [DM_ORDERDETAILS::QUANTITY] )"
    properties:
      column_type: MEASURE
```

**Import command:**
```bash
cat model_tml.json | ts tml import --policy ALL_OR_NONE --profile champ-staging
```

Where `model_tml.json` contains: `["{yaml_string_with_escaped_newlines}"]`

**Result:** Model `TEST_SV_Dunder Mifflin Sales` created with GUID `e516d156-3275-4bf3-b335-d269a0f67c1f`.

---

## Key patterns from this example

1. **`referencing_join` direction:** Each dimension table's entry in `model_tables`
   has `referencing_join` pointing to the join defined in the fact side's Table TML.

2. **DATEDIFF arg reversal:** `DATEDIFF('day', ORDER_DATE, SHIP_DATE)` → `diff_days([SHIP_DATE], [ORDER_DATE])`.
   The order is always (end, start) in ThoughtSpot, opposite of Snowflake.

3. **Multi-column formula metrics:** `SUM(UNIT_PRICE * QUANTITY)` → formula column,
   not a simple MEASURE column, because it involves two columns.

4. **Column IDs for aliased columns:** `COUNTRY_NAME` aliased as "Country" on the
   DM_CUSTOMER table entry maps to `column_id: DM_LOCALE_COUNTRY::COUNTRY_NAME`
   because the EXPR reveals it comes from `DM_LOCALE_COUNTRY.COUNTRY_NAME`.

5. **Omit primary key dimensions from columns list:** `CUSTOMER_ID`, `ORDER_ID`,
   `PRODUCT_ID` etc. are typically FK/PK columns not surfaced to end users — omit
   them from the model columns unless the user explicitly wants them.
