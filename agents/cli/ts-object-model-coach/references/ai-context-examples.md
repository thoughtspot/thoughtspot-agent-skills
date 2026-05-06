# `ai_context` Worked Examples

Concrete examples grounded in the `agent-expressibility-eval` Test 4 failure data.
Each example shows: the TML excerpt, the wrong SQL Test 4 actually emitted, the right
SQL the new schema enables, and which axis or system-prompt clause does the work.

For the schema itself, see [ai-context-schema.md](ai-context-schema.md).

---

## Example 1 — Display names + `[bracket]` refs

**Failure cluster:** Wrong physical column references. Test 4 emitted SQL referring
to TS-friendly aliases (`Total Sales`, `Total_Sales`) that don't exist.

**Question:** *"What is total sales?"*

### TML excerpt

```yaml
tables:
  - name: DM_ORDER_DETAIL
    fqn: DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL
    columns:
      - name: Amount
        column_id: DM_ORDER_DETAIL::AMOUNT
        db_column_name: AMOUNT
model:
  name: Dunder Mifflin Sales
  columns:
    - name: Total Sales
      formula_id: f_total_sales
      properties:
        column_type: MEASURE
        ai_context: |
          additivity: additive
          time_basis: DM_DATE_DIM.Date
          grain_keys: [DM_DATE_DIM.Date]
          unit: currency
formulas:
  - id: f_total_sales
    expression: sum([Amount])
```

### ❌ Wrong SQL (Test 4 actual failure pattern)

```sql
SELECT Total_Sales FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDERS
-- Object 'DUNDERMIFFLIN.PUBLIC_SV.DM_ORDERS' does not exist or not authorized.
```

The LLM treated `Total Sales` (display name) as a column and invented a table name
that fit.

### ✅ Right SQL

```sql
SELECT SUM(AMOUNT) AS TOTAL_SALES
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL
```

### What caught the issue

| Layer | Role |
|---|---|
| Clause 3 of system-prompt rule | `Total Sales` is a TS display name, never a SQL identifier |
| Clause 2 of system-prompt rule | `[Amount]` resolves via `column_id: DM_ORDER_DETAIL::AMOUNT` + `fqn` |
| Clause 1 of system-prompt rule | The formula `sum([Amount])` was re-implemented in SQL, not copy-pasted |

---

## Example 2 — TS DSL formula functions + semi-additive trap

**Failure cluster:** TS DSL formulas treated as SQL + no semi-additive guidance.
Two of Test 4's largest failure modes hit at once.

**Question:** *"What's the inventory balance for product P-100 in March?"*

### TML excerpt

```yaml
tables:
  - name: DM_INVENTORY
    fqn: DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY
    columns:
      - name: Filled Inventory
        column_id: DM_INVENTORY::FILLED_INVENTORY
        db_column_name: FILLED_INVENTORY
      - name: Balance Date
        column_id: DM_INVENTORY::BALANCE_DATE
        db_column_name: BALANCE_DATE
model:
  name: Dunder Mifflin Sales & Inventory
  columns:
    - name: Inventory Balance
      formula_id: f_inventory_balance
      description: |
        End-of-period warehouse position. Latest filled snapshot per product per
        date — never SUM across dates. Excludes in-transit stock.
      properties:
        column_type: MEASURE
        ai_context: |
          additivity: semi_additive
          non_additive_dimension: DM_DATE_DIM.Date
          time_basis: DM_DATE_DIM.Date
          grain_keys: [Product, DM_DATE_DIM.Date]
          unit: count
          null_semantics: no_snapshot
formulas:
  - id: f_inventory_balance
    expression: last_value(sum([Filled Inventory]), query_groups(), {DM_DATE_DIM.DATE})
```

### ❌ Wrong SQL — failure mode A (semi-additive trap)

```sql
SELECT SUM(FILLED_INVENTORY) AS INVENTORY_BALANCE
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY
WHERE BALANCE_DATE BETWEEN '2026-03-01' AND '2026-03-31'
  AND PRODUCT_ID = 'P-100'
-- Returns 31× the correct number — summed across daily snapshots.
```

### ❌ Wrong SQL — failure mode B (TS DSL transliteration, what Test 4 did)

```sql
SELECT last_value(SUM(FILLED_INVENTORY), query_groups(), {DM_DATE_DIM.DATE})
FROM DM_INVENTORY ...
-- Snowflake error: query_groups() does not exist; {DM_DATE_DIM.DATE} is not a SQL token.
```

### ✅ Right SQL

```sql
WITH latest AS (
  SELECT
    PRODUCT_ID,
    BALANCE_DATE,
    FILLED_INVENTORY,
    ROW_NUMBER() OVER (
      PARTITION BY PRODUCT_ID
      ORDER BY BALANCE_DATE DESC
    ) AS rn
  FROM DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY
  WHERE BALANCE_DATE BETWEEN '2026-03-01' AND '2026-03-31'
    AND PRODUCT_ID = 'P-100'
)
SELECT FILLED_INVENTORY AS INVENTORY_BALANCE
FROM latest
WHERE rn = 1
```

### What caught the issue

| Layer | Role |
|---|---|
| Clause 1 of system-prompt rule | `last_value(...)`, `query_groups(...)` are TS DSL — re-implement in SQL using a window function |
| `additivity: semi_additive` + `non_additive_dimension` | Blocks `SUM(FILLED_INVENTORY)`; tells the LLM to pick the latest snapshot per product, not sum across dates |
| Clause 2 of system-prompt rule | `{DM_DATE_DIM.DATE}` and `[Filled Inventory]` resolve to physical columns, not copy-pasted as SQL |

---

## Example 3 — Conformed date dim prevents chasm fanout

**Failure cluster:** No "Balance Date, not Order Date" signal. Cross-fact joins
fanned out catastrophically.

**Question:** *"What was monthly sales and ending inventory for March?"*

### TML excerpt

```yaml
tables:
  - name: DM_DATE_DIM
    fqn: DUNDERMIFFLIN.PUBLIC_SV.DM_DATE_DIM
    columns:
      - column_id: DM_DATE_DIM::DATE
        name: Date
        db_column_name: DATE
joins_with:
  - name: order_to_date
    on: DM_ORDER_DETAIL::ORDER_DATE = DM_DATE_DIM::DATE
  - name: inventory_to_date
    on: DM_INVENTORY::BALANCE_DATE = DM_DATE_DIM::DATE
model:
  name: Dunder Mifflin Sales & Inventory
  columns:
    - name: Total Sales
      properties:
        column_type: MEASURE
        ai_context: |
          additivity: additive
          time_basis: DM_DATE_DIM.Date
          grain_keys: [DM_ORDER_DETAIL::ORDER_DETAIL_KEY]
          unit: currency
    - name: Inventory Balance
      properties:
        column_type: MEASURE
        ai_context: |
          additivity: semi_additive
          non_additive_dimension: DM_DATE_DIM.Date
          time_basis: DM_DATE_DIM.Date
          grain_keys: [Product, DM_DATE_DIM.Date]
          unit: count
```

### ❌ Wrong SQL (Test 4 chasm fanout)

```sql
SELECT
  TO_CHAR(od.ORDER_DATE, 'YYYY-MM') AS MONTH,
  SUM(od.AMOUNT) AS TOTAL_SALES,
  SUM(inv.FILLED_INVENTORY) AS INVENTORY_BALANCE
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL od
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY inv
  ON od.ORDER_DATE = inv.BALANCE_DATE   -- joins raw fact dates → fanout
GROUP BY 1
-- TOTAL_SALES is N× too high (one row per inventory snapshot per order);
-- INVENTORY_BALANCE is wrong twice over (semi-additive trap on top of fanout).
```

### ✅ Right SQL

```sql
SELECT
  TO_CHAR(d.DATE, 'YYYY-MM') AS MONTH,
  SUM(od.AMOUNT) AS TOTAL_SALES,
  SUM(CASE WHEN inv.rn = 1 THEN inv.FILLED_INVENTORY END) AS INVENTORY_BALANCE
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_DATE_DIM d
LEFT JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL od
  ON od.ORDER_DATE = d.DATE
LEFT JOIN (
  SELECT PRODUCT_ID, BALANCE_DATE, FILLED_INVENTORY,
         ROW_NUMBER() OVER (PARTITION BY PRODUCT_ID,
                                          DATE_TRUNC('MONTH', BALANCE_DATE)
                            ORDER BY BALANCE_DATE DESC) AS rn
  FROM DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY
) inv
  ON inv.BALANCE_DATE = d.DATE
WHERE d.DATE BETWEEN '2026-03-01' AND '2026-03-31'
GROUP BY 1
```

### What caught the issue

| Layer | Role |
|---|---|
| `time_basis: DM_DATE_DIM.Date` on **both** measures | Tells the LLM to anchor both facts on the conformed dim, not on each fact's raw date |
| `joins_with` block in TML | Tells the LLM how each fact joins to `DM_DATE_DIM` |
| `additivity: semi_additive` on Inventory Balance | Triggers the per-period last-snapshot pattern (no naive SUM) |

---

## Example 4 — Phantom dimension table prevented

**Failure cluster:** Wrong physical column references. Test 4 invented eight
distinct phantom dimension tables (`DM_CATEGORY`, `DM_EMPLOYEE`, `DM_CUSTOMER`,
etc.) — accounted for ~12 of 17 FAILs.

**Question:** *"What are total sales by product category?"*

### TML excerpt

```yaml
tables:
  - name: DM_PRODUCT
    fqn: DUNDERMIFFLIN.PUBLIC_SV.DM_PRODUCT
    columns:
      - name: Product Category
        column_id: DM_PRODUCT::PRODUCT_CATEGORY    # category lives ON the product table
        db_column_name: PRODUCT_CATEGORY
model:
  name: Dunder Mifflin Sales & Inventory
  columns:
    - name: Product Category
      description: |
        Top-level product taxonomy. Stored on the product record;
        no separate category table.
      properties:
        column_type: ATTRIBUTE
        ai_context: |
          role: label
    - name: Total Sales
      properties:
        column_type: MEASURE
        ai_context: |
          additivity: additive
          time_basis: DM_DATE_DIM.Date
          grain_keys: [DM_ORDER_DETAIL::ORDER_DETAIL_KEY]
          unit: currency
```

### ❌ Wrong SQL (Test 4 actual — 8 FAILs from this pattern)

```sql
SELECT C.CATEGORY_NAME AS CATEGORY,
       SUM(OD.AMOUNT) AS TOTAL_SALES
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL OD
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_PRODUCT P
  ON OD.DM_ORDER_DETAIL_PRODUCT_ID = P.PRODUCT_ID
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_CATEGORY C   -- phantom table — invented from the column name
  ON P.DM_PRODUCT_CATEGORY_ID = C.CATEGORY_ID
GROUP BY C.CATEGORY_NAME
-- Object 'DUNDERMIFFLIN.PUBLIC_SV.DM_CATEGORY' does not exist or not authorized.
```

### ✅ Right SQL

```sql
SELECT P.PRODUCT_CATEGORY AS CATEGORY,
       SUM(OD.AMOUNT) AS TOTAL_SALES
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL OD
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_PRODUCT P
  ON OD.PRODUCT_ID = P.PRODUCT_ID
GROUP BY P.PRODUCT_CATEGORY
```

### What caught the issue

| Layer | Role |
|---|---|
| Clause 2 of system-prompt rule | `column_id: DM_PRODUCT::PRODUCT_CATEGORY` resolves to the right table — no phantom dim invented |
| `role: label` (per-column `ai_context`) | Confirms this column is for human display (not a key/code) |
| `column.description` | Reinforces in prose: *"no separate category table"* — per-column backstop |
| `model_instructions.schema_assumptions.denormalized_attributes` | **Meta-level reinforcement** — Model-level rule listing all denormalized columns, telling the LLM not to infer separate dim tables for any of them. See worked example below. |

### Meta-level reinforcement at Model scope

The phantom-table failure occurred 8 times in Test 4 across multiple columns
(`Product Category`, `Customer Region`, `Employee Manager`). A per-column
backstop catches each one individually; a Model-level rule catches the whole
class once:

```yaml
model_instructions:
  schema_assumptions:
    - assumption: denormalized_attributes
      columns: [Product Category, Customer Region, Employee Manager]
      note: do not infer separate dim tables — follow column_id
```

This is **layer 5** in the phantom-table prevention stack:

| Layer | Mechanism |
|---|---|
| 1 (truth) | `column_id` + `fqn` resolution |
| 2 (semantic role) | `ai_context.role: label` |
| 3 (instruction) | System-prompt clauses 2 & 3 |
| 4 (per-column prose) | `column.description` |
| 5 (Model-level meta) | `model_instructions.schema_assumptions` |

If layer 1 is right, layers 2-5 don't need to do anything. They exist because
LLMs are imperfect followers of structured rules — each layer catches what
prior layers missed. See
[model-instructions-schema.md § How `schema_assumptions` reinforces phantom-table prevention](model-instructions-schema.md#how-schema_assumptions-reinforces-phantom-table-prevention).

---

## Example 5 — id / label disambiguation with `role`

**Failure cluster:** Test 3 (SV) Q-010 PARTIAL: *"returns category_id instead of
category name."* The LLM picked the FK column when the user clearly meant the label.

**Question:** *"Show total sales by product category."*

### TML excerpt

```yaml
- name: Product Category
  column_id: DM_PRODUCT::PRODUCT_CATEGORY
  column_type: ATTRIBUTE
  description: |
    Top-level product taxonomy — Office Supplies, Paper, Furniture.
  properties:
    ai_context: |
      role: label

- name: Product Category ID
  column_id: DM_PRODUCT::PRODUCT_CATEGORY_ID
  column_type: ATTRIBUTE
  description: |
    Internal numeric ID for the product category. Use Product Category for display.
  properties:
    ai_context: |
      role: id
```

### ❌ Without `role` (Test 3 partial pattern on Q-010)

```sql
SELECT PRODUCT_CATEGORY_ID, SUM(OD.AMOUNT)
FROM ... GROUP BY PRODUCT_CATEGORY_ID
-- LLM grabbed the ID column; output is meaningless to a human.
```

### ✅ With `role: label` and `role: id`

```sql
SELECT P.PRODUCT_CATEGORY, SUM(OD.AMOUNT)
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL OD
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_PRODUCT P ON OD.PRODUCT_ID = P.PRODUCT_ID
GROUP BY P.PRODUCT_CATEGORY
```

### What caught the issue

| Layer | Role |
|---|---|
| `role: label` on `Product Category` | Tells the LLM this is the human-readable column |
| `role: id` on `Product Category ID` | Tells the LLM the ID is for joining/filtering, not display |

---

## Example 6 — FK on the fact, label on the dim

**Question:** *"Top 10 customers by sales."*

### TML excerpt

```yaml
# DM_ORDER_DETAIL has the FK
- name: Customer ID
  column_id: DM_ORDER_DETAIL::CUSTOMER_ID
  column_type: ATTRIBUTE
  description: |
    FK to DM_CUSTOMER. Use Customer Name for display.
  properties:
    ai_context: |
      role: key

# DM_CUSTOMER has the label
- name: Customer Name
  column_id: DM_CUSTOMER::CUSTOMER_NAME
  column_type: ATTRIBUTE
  properties:
    ai_context: |
      role: label
```

### ❌ Without `role`

LLM might `GROUP BY OD.CUSTOMER_ID` and skip the join to `DM_CUSTOMER` — output
shows opaque IDs to the user.

### ✅ With `role: key` on the FK and `role: label` on the name column

```sql
SELECT C.CUSTOMER_NAME, SUM(OD.AMOUNT) AS TOTAL_SALES
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL OD
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_CUSTOMER C ON OD.CUSTOMER_ID = C.CUSTOMER_ID
GROUP BY C.CUSTOMER_NAME
ORDER BY TOTAL_SALES DESC
LIMIT 10
```

### What caught the issue

`role: key` tells the LLM the FK isn't for display — it must follow `joins_with` to
find the label column on the dim.

---

## Example 7 — NULL semantics on a dimension

**Question:** *"Sales by region in March 2026."*

### TML excerpt

```yaml
- name: Customer Region
  column_id: DM_CUSTOMER::REGION
  column_type: ATTRIBUTE
  description: |
    Sales region the customer belongs to. NULL means the customer has not
    yet been territory-assigned — exclude from regional rollups, not "Other".
  properties:
    ai_context: |
      role: label
      null_semantics: unknown
```

### ❌ Without `null_semantics`

```sql
SELECT COALESCE(REGION, 'Other') AS REGION, SUM(AMOUNT)
FROM ... GROUP BY 1
-- Lumps unassigned customers into "Other" — distorts the regional view.
```

### ✅ With `null_semantics: unknown`

```sql
SELECT REGION, SUM(AMOUNT)
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_CUSTOMER C
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL OD ON C.CUSTOMER_ID = OD.CUSTOMER_ID
WHERE OD.ORDER_DATE BETWEEN '2026-03-01' AND '2026-03-31'
  AND C.REGION IS NOT NULL
GROUP BY REGION
```

### What caught the issue

| Layer | Role |
|---|---|
| `null_semantics: unknown` | Tells the LLM NULL has business meaning (not yet assigned), not "missing data to coalesce" |
| `column.description` | Carries the prose ("not yet been territory-assigned") that fully explains why NULL should be excluded |

---

## Example 8 — Multi-input formula (margin %)

**Failure cluster:** Multi-column formulas amplify the TS DSL transliteration risk.

**Question:** *"What's our gross margin % by month?"*

### TML excerpt

```yaml
model:
  name: Dunder Mifflin Sales & Inventory
  columns:
    - name: Gross Margin %
      formula_id: f_gross_margin_pct
      description: |
        Sales-weighted margin (Amount minus Cost) divided by Amount.
        Excludes refund line items.
      properties:
        column_type: MEASURE
        ai_context: |
          additivity: non_additive
          time_basis: DM_DATE_DIM.Date
          grain_keys: [DM_DATE_DIM.Date]
          unit: percentage
          null_semantics: unknown
formulas:
  - id: f_gross_margin_pct
    expression: (sum([Amount]) - sum([Cost])) / sum([Amount])
```

### ❌ Wrong SQL (transliteration)

```sql
SELECT (sum([Amount]) - sum([Cost])) / sum([Amount]) AS GROSS_MARGIN_PCT
FROM ...
-- Square-bracket refs are not SQL.
```

### ❌ Wrong SQL (over-summing)

```sql
SELECT TO_CHAR(ORDER_DATE,'YYYY-MM') AS MONTH,
       SUM(GROSS_MARGIN_PCT) AS GROSS_MARGIN_PCT  -- ratios don't sum
FROM ...
GROUP BY 1
```

### ✅ Right SQL

```sql
SELECT
  TO_CHAR(d.DATE, 'YYYY-MM') AS MONTH,
  (SUM(od.AMOUNT) - SUM(od.COST)) / NULLIF(SUM(od.AMOUNT), 0) AS GROSS_MARGIN_PCT
FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL od
JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_DATE_DIM d ON od.ORDER_DATE = d.DATE
GROUP BY 1
```

### What caught the issue

| Layer | Role |
|---|---|
| Clauses 1 & 2 of system-prompt rule | `[Amount]` and `[Cost]` resolve to physical columns; the formula expression is re-implemented in SQL |
| `additivity: non_additive` | Blocks `SUM(GROSS_MARGIN_PCT)` — ratios must be recomputed at each aggregation level |
| `time_basis: DM_DATE_DIM.Date` | Anchors monthly grouping on the conformed dim |
| `null_semantics: unknown` + `NULLIF` in SQL | Avoids divide-by-zero when filtered Amount is 0 |

---

## Cross-cutting patterns

| Failure cluster | Primary fix | Secondary backup |
|---|---|---|
| Wrong physical column references | Clauses 2 & 3 of system-prompt rule (`column_id` + `fqn` resolution) | `source:` override; `column.description` in prose |
| TS DSL formulas treated as SQL | Clause 1 of system-prompt rule | `formula` axis forbidden in `ai_context` |
| Semi-additive trap | `additivity: semi_additive` + `non_additive_dimension` | `column.description` describing the snapshot semantics |
| Cross-fact chasm fanout | `time_basis` on conformed dim (both measures) | `joins_with` block in TML |
| ID vs label confusion | `role:` on each member of an id/label/code/key set | `column.description` flagging which to prefer |
| NULL handling | `null_semantics:` enum | `column.description` explaining the business meaning |

Three classes of fix split the load:

1. **System-prompt rule (Clauses 1–3)** does pure resolution — turning TS-DSL artifacts back into physical paths and known patterns.
2. **Mandatory `ai_context` tier + `role`** does semantic constraint — additivity, time anchor, grain, role disambiguation.
3. **`column.description` prose** does the irreducible human nuance.

Each one alone leaves gaps; the combination closes them. This is the core insight
from Test 4 → the new schema.
