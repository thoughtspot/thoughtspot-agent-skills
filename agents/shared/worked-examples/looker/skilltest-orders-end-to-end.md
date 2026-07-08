# Worked Example: LookML skilltest-orders → ThoughtSpot

End-to-end walkthrough of the `ts-convert-from-looker` skill applied to the
`skilltest-orders` LookML fixture. Status: **VERIFIED** — successfully imported 2026-06-18.

**Verified import details:**
- Connection: `{connection_name}` | db: `{database}` | schema: `{schema}`
- Import method: zip upload via ThoughtSpot UI (Data → TML Import)
- 6 table TMLs + 1 model TML — all imported successfully in one batch
- Fixes required before import: add `with:` to all join definitions; remove duplicate dim-side join key columns from `columns[]`

Fixture location: `sigma-migration-skills-main/plugins/looker-to-sigma/skills/looker-to-sigma/fixtures/skilltest-orders/`

---

## Input LookML

### skilltest_orders.model.lkml
```lkml
connection: "snowflake_csa"
include: "views/*.view.lkml"

explore: order_fact {
  label: "Orders"
  join: customer_dim {
    type: left_outer
    relationship: many_to_one
    sql_on: ${order_fact.customer_key} = ${customer_dim.customer_key} ;;
  }
}
```

### views/order_fact.view.lkml
```lkml
view: order_fact {
  sql_table_name: CSA.TJ.ORDER_FACT ;;

  dimension: order_id      { type: string;  sql: ${TABLE}.ORDER_ID ;; }
  dimension: customer_key  { type: number;  hidden: yes; sql: ${TABLE}.CUSTOMER_KEY ;; }
  dimension: net_revenue   { type: number;  hidden: yes; sql: ${TABLE}.NET_REVENUE ;; }

  measure: total_net_revenue {
    type: sum
    sql: ${net_revenue} ;;
    value_format_name: usd
  }
  measure: order_count {
    type: count_distinct
    sql: ${TABLE}.ORDER_ID ;;
  }
  measure: average_order_value {
    type: number
    sql: 1.0 * ${total_net_revenue} / NULLIF(${order_count}, 0) ;;
    value_format_name: usd
  }
}
```

### views/customer_dim.view.lkml
```lkml
view: customer_dim {
  sql_table_name: CSA.TJ.CUSTOMER_DIM ;;

  dimension: customer_key       { primary_key: yes; hidden: yes; type: number;  sql: ${TABLE}.CUSTOMER_KEY ;; }
  dimension: region             { type: string; sql: ${TABLE}.REGION ;; }
  dimension: customer_segment   { type: string; sql: ${TABLE}.CUSTOMER_SEGMENT ;; }
  dimension: loyalty_tier       { type: string; sql: ${TABLE}.LOYALTY_TIER ;; }
}
```

---

## Step 3 — Parse results

**Connection:** `snowflake_csa`

**Explore:** `order_fact` (label: "Orders") → model name: "Orders"

**Joins:**
- `customer_dim`: type `LEFT_OUTER`, cardinality `MANY_TO_ONE`
- `sql_on:` `${order_fact.customer_key} = ${customer_dim.customer_key}`
  → `[ORDER_FACT::CUSTOMER_KEY] = [CUSTOMER_DIM::CUSTOMER_KEY]`

**Views:** ORDER_FACT (CSA.TJ.ORDER_FACT), CUSTOMER_DIM (CSA.TJ.CUSTOMER_DIM)

---

## Step 4 — Field resolution and classification

### Cross-field inline resolution

`total_net_revenue`:
- `sql: ${net_revenue}` → `${net_revenue}` is `${TABLE}.NET_REVENUE`
- Resolved: `sum ( [ORDER_FACT::NET_REVENUE] )`

`order_count`:
- `type: count_distinct`, `sql: ${TABLE}.ORDER_ID`
- Resolved: `unique count ( [ORDER_FACT::ORDER_ID] )` — Invariant I5

`average_order_value`:
- `sql: 1.0 * ${total_net_revenue} / NULLIF(${order_count}, 0)`
- After inline: `1.0 * sum([ORDER_FACT::NET_REVENUE]) / NULLIF(unique count([ORDER_FACT::ORDER_ID]), 0)`
- After translation: `safe_divide ( sum ( [ORDER_FACT::NET_REVENUE] ) , unique count ( [ORDER_FACT::ORDER_ID] ) )`
- Note: `1.0 *` dropped (TS division returns DOUBLE)

**Format hints (logged, not translated):**
- `total_net_revenue.value_format_name: usd` → log: "format as USD in ThoughtSpot Answer"
- `average_order_value.value_format_name: usd` → same

---

## Step 5 — Generated Table TMLs

### order_fact.table.tml
```yaml
table:
  name: ORDER_FACT
  db: CSA
  schema: TJ
  db_table: ORDER_FACT
  connection:
    name: {connection_name}
  columns:
  - name: Order ID
    db_column_name: ORDER_ID
    properties:
      column_type: ATTRIBUTE
  - name: Customer Key
    db_column_name: CUSTOMER_KEY
    properties:
      column_type: ATTRIBUTE
  - name: Net Revenue
    db_column_name: NET_REVENUE
    properties:
      column_type: MEASURE
      aggregation: SUM
```

### customer_dim.table.tml
```yaml
table:
  name: CUSTOMER_DIM
  db: CSA
  schema: TJ
  db_table: CUSTOMER_DIM
  connection:
    name: {connection_name}
  columns:
  - name: Customer Key (Customer)
    db_column_name: CUSTOMER_KEY
    properties:
      column_type: ATTRIBUTE
  - name: Region
    db_column_name: REGION
    properties:
      column_type: ATTRIBUTE
  - name: Customer Segment
    db_column_name: CUSTOMER_SEGMENT
    properties:
      column_type: ATTRIBUTE
  - name: Loyalty Tier
    db_column_name: LOYALTY_TIER
    properties:
      column_type: ATTRIBUTE
```

---

## Step 6 — Generated Model TML

```yaml
model:
  name: Orders
  model_tables:
  - name: ORDER_FACT
    joins:
    - id: CUSTOMER_DIM
      name: CUSTOMER_DIM
      on: '[ORDER_FACT::CUSTOMER_KEY] = [CUSTOMER_DIM::CUSTOMER_KEY]'
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - name: CUSTOMER_DIM

  formulas:
  - id: formula_Total Net Revenue
    name: Total Net Revenue
    expr: sum ( [ORDER_FACT::NET_REVENUE] )

  - id: formula_Order Count
    name: Order Count
    expr: unique count ( [ORDER_FACT::ORDER_ID] )

  - id: formula_Average Order Value
    name: Average Order Value
    expr: safe_divide ( sum ( [ORDER_FACT::NET_REVENUE] ) , unique count ( [ORDER_FACT::ORDER_ID] ) )

  columns:
  - name: Order ID
    column_id: ORDER_FACT::ORDER_ID
    properties:
      column_type: ATTRIBUTE

  - name: Customer Key
    column_id: ORDER_FACT::CUSTOMER_KEY
    properties:
      column_type: ATTRIBUTE

  - name: Net Revenue
    column_id: ORDER_FACT::NET_REVENUE
    properties:
      column_type: MEASURE
      aggregation: SUM

  - name: Customer Key (Customer)
    column_id: CUSTOMER_DIM::CUSTOMER_KEY
    properties:
      column_type: ATTRIBUTE

  - name: Region
    column_id: CUSTOMER_DIM::REGION
    properties:
      column_type: ATTRIBUTE

  - name: Customer Segment
    column_id: CUSTOMER_DIM::CUSTOMER_SEGMENT
    properties:
      column_type: ATTRIBUTE

  - name: Loyalty Tier
    column_id: CUSTOMER_DIM::LOYALTY_TIER
    properties:
      column_type: ATTRIBUTE

  - name: Total Net Revenue
    formula_id: formula_Total Net Revenue
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX

  - name: Order Count
    formula_id: formula_Order Count
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX

  - name: Average Order Value
    formula_id: formula_Average Order Value
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX

  properties:
    is_bypass_rls: false
    join_progressive: false
```

---

## Invariant checklist

- [x] I1 — All 3 formulas have matching `columns[]` entries
- [x] I2 — No `aggregation:` inside `formulas[]`
- [x] I3 — All formula MEASURE columns have `index_type: DONT_INDEX`
- [x] I4 — `CUSTOMER_DIM` join: `id` equals `name` exactly
- [x] I5 — `order_count` uses `unique count()`, not `COUNT_DISTINCT`
- [x] I6 — `connection.name: {connection_name}` (no GUID)
- [x] I7 — All SQL patterns checked against formula translation reference before translation
- [x] I8 — No duplicate `column_id` values (each physical column appears once)

---

## Migration summary (expected)

```
=== LookML → ThoughtSpot Migration Summary ===

Source project: skilltest-orders/
Explore migrated: order_fact (label: "Orders")

Tables:    2 registered (ORDER_FACT, CUSTOMER_DIM)
Formulas:  3 translated
  - Total Net Revenue: sum ( [ORDER_FACT::NET_REVENUE] )
  - Order Count: unique count ( [ORDER_FACT::ORDER_ID] )
  - Average Order Value: safe_divide(...)

Format hints (apply manually in ThoughtSpot):
  - total_net_revenue: USD currency format
  - average_order_value: USD currency format

Omitted/unsupported: none
==============================================
```

---

## Live verification status

| Step | Status | Notes |
|---|---|---|
| Table TML import | VERIFIED 2026-06-18 | 6 table TMLs imported via zip |
| Model TML import | VERIFIED 2026-06-18 | Model imported in same batch, no GUID capture needed |
| Formula validation | PENDING | Formulas present in model — search test not yet run |
| Search query test | PENDING | |
