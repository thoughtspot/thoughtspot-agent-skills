# Worked Example — Databricks Metric View → ThoughtSpot Model

End-to-end conversion of `analytics.ecommerce.ecommerce_transactions_mv` to a
ThoughtSpot Table (`TRANSACTIONS`) and Model (`Transactions_MV_Model`). Covers
direct column dimensions, computed date dimension, rich v1.1 metadata
(display_name, comment, synonyms), simple and complex measures (SUM, COUNT
DISTINCT, ratio with inlined aggregates, FILTER WHERE conditional, rolling
window, CASE/CAST ratio), and a global filter translated to a boolean formula
column with model-level filter enforcement.

Verified against live ThoughtSpot and Databricks instances on 2026-05-28.

> **Corrected 2026-07-09** — `revenue_7d_rolling`'s formula below was updated. The
> original `moving_sum([m], 7, 0, [date])` reproduced Databricks' `trailing 8 day
> inclusive` semantics, not the `trailing 7 day` (default/exclusive) the source MV
> actually declares. See "Measure 5" below and
> `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1/C2) for the corrected
> mapping and the old/new formula text.

> **Live-verified 2026-07-09** — this MV combines a global `filter: status !=
> 'cancelled'` (line 34 below) with the `revenue_7d_rolling` window measure in the
> same view, a combination never queried together before this pass. See
> `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` (C1): filter ordering is
> **CONFIRMED cross-platform** — the filter removes rows *before* `moving_sum`
> computes over them, on both Databricks and ThoughtSpot, so the mapping below
> requires no formula change. **Density note (E1):** this MV's `transaction_date`
> is daily-dense (one row per day, no gaps) for the categories exercised in this
> example, so the row-positional/date-interval divergence documented at E1 does
> not surface here — the numbers below stand as verified. On a source with date
> gaps, re-check the density caveat in the Rolling Window section of
> `ts-from-databricks-rules.md` before trusting this formula shape.

---

## Source — Metric View YAML (v1.1)

Retrieved via `DESCRIBE TABLE EXTENDED analytics.ecommerce.ecommerce_transactions_mv`.

```yaml
version: 1.1
comment: >-
  E-commerce transaction metrics — revenue, customer counts, order value,
  and return analysis on the transactions table.

source: analytics.ecommerce.transactions

filter: status != 'cancelled'

dimensions:
  - name: transaction_id
    expr: transaction_id

  - name: product_category
    expr: product_category
    display_name: 'Product Category'
    synonyms: ['category', 'product type']

  - name: transaction_month
    expr: DATE_TRUNC('MONTH', transaction_date)

  - name: customer_region
    expr: customer_region
    display_name: 'Region'
    synonyms: ['area', 'territory']

  - name: transaction_date
    expr: transaction_date

measures:
  - name: total_revenue
    expr: SUM(unit_price * quantity * (1 - discount))
    display_name: 'Total Revenue'
    comment: 'Net revenue after discount.'
    synonyms: ['revenue', 'sales']

  - name: unique_customers
    expr: COUNT(DISTINCT customer_id)
    display_name: 'Unique Customers'
    comment: 'Distinct customer count.'

  - name: avg_order_value
    expr: SUM(unit_price * quantity) / COUNT(DISTINCT transaction_id)
    display_name: 'Avg Order Value'
    comment: 'Average revenue per transaction.'
    synonyms: ['AOV']

  - name: high_value_revenue
    expr: SUM(unit_price * quantity) FILTER (WHERE unit_price > 100)
    display_name: 'High Value Revenue'
    comment: 'Revenue from items priced above 100.'

  - name: revenue_7d_rolling
    expr: SUM(unit_price * quantity)
    display_name: '7-Day Rolling Revenue'
    comment: 'Trailing 7-day rolling sum of gross revenue.'
    window:
      - order: transaction_date
        range: trailing 7 day
        semiadditive: last

  - name: return_rate
    expr: CAST(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*)
    display_name: 'Return Rate'
    comment: 'Fraction of transactions that were returned.'
```

---

## ThoughtSpot Connection

The Databricks connection in ThoughtSpot is named `Databricks Analytics`.
The source table `analytics.ecommerce.transactions` maps to:
- `db: analytics`
- `schema: ecommerce`
- `db_table: transactions`

---

## Step 1 — Parse and Classify Dimensions

| Name | `expr` | Classification | Reason |
|---|---|---|---|
| `transaction_id` | `transaction_id` | Direct ATTRIBUTE | Single column reference, no functions |
| `product_category` | `product_category` | Direct ATTRIBUTE | Single column reference; has `display_name`, `synonyms` |
| `transaction_month` | `DATE_TRUNC('MONTH', transaction_date)` | Formula ATTRIBUTE | `date_trunc` function — translates to `start_of_month` |
| `customer_region` | `customer_region` | Direct ATTRIBUTE | Single column reference; has `display_name`, `synonyms` |
| `transaction_date` | `transaction_date` | Direct ATTRIBUTE | Single column reference |

### Dimension 1: `transaction_id` — Direct column

```
expr: transaction_id  →  direct column reference
```

No `display_name`, no `comment`, no `synonyms` — title-case the `name`: `Transaction Id`.

| Property | Value |
|---|---|
| Column name | `Transaction Id` |
| `column_id` | `TRANSACTIONS::transaction_id` |
| `column_type` | `ATTRIBUTE` |

### Dimension 2: `product_category` — Direct column with metadata

```
expr: product_category  →  direct column reference
display_name: 'Product Category'
synonyms: ['category', 'product type']
```

| Property | Value |
|---|---|
| Column name | `Product Category` (from `display_name`) |
| `column_id` | `TRANSACTIONS::product_category` |
| `column_type` | `ATTRIBUTE` |
| `synonyms` | `['category', 'product type']` |
| `synonym_type` | `USER_DEFINED` |

### Dimension 3: `transaction_month` — Computed (DATE_TRUNC)

```
expr: DATE_TRUNC('MONTH', transaction_date)  →  computed expression
```

`DATE_TRUNC('MONTH', col)` translates to `start_of_month ( [TRANSACTIONS::transaction_date] )`.
This is a formula ATTRIBUTE. No `display_name` — title-case `name`: `Transaction Month`.

| Property | Value |
|---|---|
| Column name | `Transaction Month` |
| Formula id | `formula_Transaction Month` |
| Formula expr | `start_of_month ( [TRANSACTIONS::transaction_date] )` |
| `column_type` | `ATTRIBUTE` |

### Dimension 4: `customer_region` — Direct column with metadata

```
expr: customer_region  →  direct column reference
display_name: 'Region'
synonyms: ['area', 'territory']
```

| Property | Value |
|---|---|
| Column name | `Region` (from `display_name`) |
| `column_id` | `TRANSACTIONS::customer_region` |
| `column_type` | `ATTRIBUTE` |
| `synonyms` | `['area', 'territory']` |
| `synonym_type` | `USER_DEFINED` |

### Dimension 5: `transaction_date` — Direct column

```
expr: transaction_date  →  direct column reference
```

No metadata — title-case `name`: `Transaction Date`.

| Property | Value |
|---|---|
| Column name | `Transaction Date` |
| `column_id` | `TRANSACTIONS::transaction_date` |
| `column_type` | `ATTRIBUTE` |

---

## Step 2 — Parse and Classify Measures

| Name | `expr` | `window:` | Classification | Reason |
|---|---|---|---|---|
| `total_revenue` | `SUM(unit_price * quantity * (1 - discount))` | — | Formula MEASURE | Arithmetic inside aggregate |
| `unique_customers` | `COUNT(DISTINCT customer_id)` | — | Formula MEASURE | `COUNT(DISTINCT)` must always be a formula |
| `avg_order_value` | `SUM(unit_price * quantity) / COUNT(DISTINCT transaction_id)` | — | Formula MEASURE | Ratio of two aggregates — inline both |
| `high_value_revenue` | `SUM(unit_price * quantity) FILTER (WHERE unit_price > 100)` | — | Formula MEASURE | `FILTER (WHERE)` → `sum_if` |
| `revenue_7d_rolling` | `SUM(unit_price * quantity)` | `trailing 7 day` | Formula MEASURE | Window measure → `moving_sum` |
| `return_rate` | `CAST(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*)` | — | Formula MEASURE | Ratio with CASE inside aggregate + `COUNT(*)` |

**Note:** All six measures are formulas. None qualifies as a simple MEASURE column
(single `AGG(column)` on one physical column). This is common in real MVs where
measures involve arithmetic, ratios, conditional aggregates, or window functions.

### Measure 1: `total_revenue` — Formula MEASURE (arithmetic inside aggregate)

Databricks:
```
SUM(unit_price * quantity * (1 - discount))
```

ThoughtSpot formula:
```
sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] ) )
```

Multi-column arithmetic inside `SUM` translates directly. Each column reference
uses `[TABLE::col]` notation.

| Property | Value |
|---|---|
| Column name | `Total Revenue` (from `display_name`) |
| Formula id | `formula_Total Revenue` |
| Formula expr | `sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] ) )` |
| `column_type` | `MEASURE` |
| `aggregation` | `SUM` |
| `description` | `Net revenue after discount.` |
| `synonyms` | `['revenue', 'sales']` |
| `synonym_type` | `USER_DEFINED` |

### Measure 2: `unique_customers` — Formula MEASURE (COUNT DISTINCT)

Databricks:
```
COUNT(DISTINCT customer_id)
```

ThoughtSpot formula:
```
unique count ( [TRANSACTIONS::customer_id] )
```

`COUNT(DISTINCT col)` must always be a formula using `unique count` (two words,
space — NOT `unique_count` with underscore). Never use `aggregation: COUNT_DISTINCT`
on a `column_id` — ThoughtSpot silently overrides `column_type` to ATTRIBUTE.

| Property | Value |
|---|---|
| Column name | `Unique Customers` (from `display_name`) |
| Formula id | `formula_Unique Customers` |
| Formula expr | `unique count ( [TRANSACTIONS::customer_id] )` |
| `column_type` | `MEASURE` |
| `aggregation` | `SUM` |
| `description` | `Distinct customer count.` |

### Measure 3: `avg_order_value` — Formula MEASURE (ratio with inlined aggregates)

Databricks:
```
SUM(unit_price * quantity) / COUNT(DISTINCT transaction_id)
```

ThoughtSpot formula:
```
sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) / unique count ( [TRANSACTIONS::transaction_id] )
```

Ratio of two aggregates — both must be inlined in a single formula expression.
Cross-formula references fail during TML import, so each aggregate is written
out directly rather than referencing the Total Revenue or Unique Customers formulas.

**Live-verified 2026-07-09 across query grain** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — inlined ratio-of-aggregate
measures like this one are **CONFIRMED** to compute true ratio-of-sums, cross-platform,
at every grain tested — no formula change needed.

| Property | Value |
|---|---|
| Column name | `Avg Order Value` (from `display_name`) |
| Formula id | `formula_Avg Order Value` |
| Formula expr | `sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) / unique count ( [TRANSACTIONS::transaction_id] )` |
| `column_type` | `MEASURE` |
| `aggregation` | `SUM` |
| `description` | `Average revenue per transaction.` |
| `synonyms` | `['AOV']` |
| `synonym_type` | `USER_DEFINED` |

### Measure 4: `high_value_revenue` — Formula MEASURE (FILTER WHERE conditional)

Databricks:
```
SUM(unit_price * quantity) FILTER (WHERE unit_price > 100)
```

ThoughtSpot formula:
```
sum_if ( [TRANSACTIONS::unit_price] > 100 , [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] )
```

`AGG(...) FILTER (WHERE cond)` translates to the native `*_if` conditional
aggregate. `sum_if` signature: condition FIRST, measure expression SECOND.

| Property | Value |
|---|---|
| Column name | `High Value Revenue` (from `display_name`) |
| Formula id | `formula_High Value Revenue` |
| Formula expr | `sum_if ( [TRANSACTIONS::unit_price] > 100 , [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] )` |
| `column_type` | `MEASURE` |
| `aggregation` | `SUM` |
| `description` | `Revenue from items priced above 100.` |

### Measure 5: `revenue_7d_rolling` — Formula MEASURE (rolling window)

Databricks:
```yaml
expr: SUM(unit_price * quantity)
window:
  - order: transaction_date
    range: trailing 7 day
    semiadditive: last
```

ThoughtSpot formula (**corrected 2026-07-09** — see below):
```
moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , -1 , [TRANSACTIONS::transaction_date] )
```

> **Corrected 2026-07-09.** The original translation recorded here (verified
> 2026-05-28) was
> `moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , 0 , [TRANSACTIONS::transaction_date] )`.
> Live testing on 2026-07-09
> (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`, C1/C2) established that
> `moving_sum([m], N, 0, [date])` always includes the anchor row — it spans N+1
> rows — so the old formula actually reproduces `trailing 8 day inclusive`, not
> the source MV's `trailing 7 day` (default/exclusive, per Databricks' confirmed
> `exclusive` default). The corrected form above (`start=7, end=-1`) spans exactly
> 7 rows ending one row before the anchor, matching `trailing 7 day` exactly —
> including boundary behavior (partial sums near the start of the series, `NULL`
> only when zero preceding rows exist).

Key translation rules:
- The outer `SUM` is stripped — `moving_sum` applies its own aggregation internally.
  The inner expression `unit_price * quantity` is passed as the first argument.
- The sort column must be a physical `[TABLE::col]` reference (`[TRANSACTIONS::transaction_date]`),
  not the formula dimension name. Formula references in `moving_sum` sort position
  fail with "Search did not find" errors.
- The `order:` dimension `transaction_date` has `expr: transaction_date` — a direct
  column reference — so the physical column is `transaction_date`.
- Arguments: `moving_sum(measure_expr, start, end, sort_column)` — see
  [thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md#moving-functions)
  for the `start`/`end` opposite-sign convention. `start` = 7, `end` = -1: 7 rows
  ending one row before the anchor (the `trailing 7 day` default/exclusive form).

| Property | Value |
|---|---|
| Column name | `7-Day Rolling Revenue` (from `display_name`) |
| Formula id | `formula_7-Day Rolling Revenue` |
| Formula expr | `moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , -1 , [TRANSACTIONS::transaction_date] )` |
| `column_type` | `MEASURE` |
| `aggregation` | `SUM` |
| `description` | `Trailing 7-day rolling sum of gross revenue.` |

### Measure 6: `return_rate` — Formula MEASURE (CASE/CAST ratio)

Databricks:
```
CAST(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*)
```

Break this into parts:

- `CASE WHEN status = 'returned' THEN 1 ELSE 0 END` →
  `if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 )`
- `SUM(CASE ...)` → `sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) )`
  (ThoughtSpot's `sum()` accepts inline `if` expressions without needing CAST)
- `COUNT(*)` → `count ( 1 )` (ThoughtSpot has no `COUNT(*)` — use `count ( 1 )`)
- The CAST is implicit in ThoughtSpot — division of two numeric aggregates
  returns a double naturally.

**Live-verified 2026-07-09 across query grain** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — this ratio-of-aggregates
pattern is **CONFIRMED** to compute true ratio-of-sums, cross-platform, at every
grain tested — no formula change needed.

ThoughtSpot formula:
```
sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) ) / count ( 1 )
```

| Property | Value |
|---|---|
| Column name | `Return Rate` (from `display_name`) |
| Formula id | `formula_Return Rate` |
| Formula expr | `sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) ) / count ( 1 )` |
| `column_type` | `MEASURE` |
| `aggregation` | `SUM` |
| `description` | `Fraction of transactions that were returned.` |

---

## Step 3 — Handle Filter

The MV `filter:` field:
```
filter: status != 'cancelled'
```

Create a boolean formula column and apply it as a model-level filter:

- Formula: `[TRANSACTIONS::status] != 'cancelled'`
- Column name: `MV Filter`
- `column_type`: ATTRIBUTE
- Model-level `filters:` section enforces the filter automatically on every query.

---

## Output — Table TML

```yaml
table:
  name: TRANSACTIONS
  db: analytics
  schema: ecommerce
  db_table: transactions
  connection:
    name: "Databricks Analytics"
  columns:
  - name: transaction_id
    db_column_name: transaction_id
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: product_category
    db_column_name: product_category
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: transaction_date
    db_column_name: transaction_date
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: DATE
  - name: customer_region
    db_column_name: customer_region
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: customer_id
    db_column_name: customer_id
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
  - name: unit_price
    db_column_name: unit_price
    properties:
      column_type: MEASURE
      aggregation: SUM
    db_column_properties:
      data_type: DOUBLE
  - name: quantity
    db_column_name: quantity
    properties:
      column_type: MEASURE
      aggregation: SUM
    db_column_properties:
      data_type: INT64
  - name: discount
    db_column_name: discount
    properties:
      column_type: MEASURE
      aggregation: SUM
    db_column_properties:
      data_type: DOUBLE
  - name: status
    db_column_name: status
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: VARCHAR
```

---

## Output — Model TML

```yaml
model:
  name: Transactions_MV_Model
  description: >-
    E-commerce transaction metrics — revenue, customer counts, order value,
    and return analysis on the transactions table.
    Converted from Databricks Metric View analytics.ecommerce.ecommerce_transactions_mv.
    MV Filter applied automatically via model filter.
  model_tables:
  - name: TRANSACTIONS
    fqn: "{table_guid}"
  formulas:
  - id: formula_Transaction Month
    name: "Transaction Month"
    expr: "start_of_month ( [TRANSACTIONS::transaction_date] )"
    properties:
      column_type: ATTRIBUTE
  - id: formula_Total Revenue
    name: "Total Revenue"
    expr: "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] * ( 1 - [TRANSACTIONS::discount] ) )"
  - id: formula_Unique Customers
    name: "Unique Customers"
    expr: "unique count ( [TRANSACTIONS::customer_id] )"
  - id: formula_Avg Order Value
    name: "Avg Order Value"
    expr: "sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] ) / unique count ( [TRANSACTIONS::transaction_id] )"
  - id: formula_High Value Revenue
    name: "High Value Revenue"
    expr: "sum_if ( [TRANSACTIONS::unit_price] > 100 , [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] )"
  - id: "formula_7-Day Rolling Revenue"
    name: "7-Day Rolling Revenue"
    expr: "moving_sum ( [TRANSACTIONS::unit_price] * [TRANSACTIONS::quantity] , 7 , -1 , [TRANSACTIONS::transaction_date] )"
  - id: formula_Return Rate
    name: "Return Rate"
    expr: "sum ( if ( [TRANSACTIONS::status] = 'returned' , 1 , 0 ) ) / count ( 1 )"
  - id: "formula_MV Filter"
    name: "MV Filter"
    expr: "[TRANSACTIONS::status] != 'cancelled'"
    properties:
      column_type: ATTRIBUTE
  columns:
  - name: "Transaction Id"
    column_id: TRANSACTIONS::transaction_id
    properties:
      column_type: ATTRIBUTE
  - name: "Product Category"
    column_id: TRANSACTIONS::product_category
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - "category"
      - "product type"
      synonym_type: USER_DEFINED
  - name: "Transaction Month"
    formula_id: formula_Transaction Month
    properties:
      column_type: ATTRIBUTE
  - name: "Region"
    column_id: TRANSACTIONS::customer_region
    properties:
      column_type: ATTRIBUTE
      synonyms:
      - "area"
      - "territory"
      synonym_type: USER_DEFINED
  - name: "Transaction Date"
    column_id: TRANSACTIONS::transaction_date
    properties:
      column_type: ATTRIBUTE
  - name: "Total Revenue"
    formula_id: formula_Total Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Net revenue after discount."
      synonyms:
      - "revenue"
      - "sales"
      synonym_type: USER_DEFINED
  - name: "Unique Customers"
    formula_id: formula_Unique Customers
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Distinct customer count."
  - name: "Avg Order Value"
    formula_id: formula_Avg Order Value
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Average revenue per transaction."
      synonyms:
      - "AOV"
      synonym_type: USER_DEFINED
  - name: "High Value Revenue"
    formula_id: formula_High Value Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Revenue from items priced above 100."
  - name: "7-Day Rolling Revenue"
    formula_id: "formula_7-Day Rolling Revenue"
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Trailing 7-day rolling sum of gross revenue."
  - name: "Return Rate"
    formula_id: formula_Return Rate
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      description: "Fraction of transactions that were returned."
  - name: "MV Filter"
    formula_id: "formula_MV Filter"
    properties:
      column_type: ATTRIBUTE
  filters:
  - column:
    - "MV Filter"
    oper: in
    values:
    - "true"
  properties:
    is_bypass_rls: false
    join_progressive: true
```

---

## Key Patterns

1. **Direct column dimensions map to `column_id` ATTRIBUTEs.** When the MV dimension
   `expr` is a bare column reference (e.g., `expr: product_category`), use a physical
   `column_id` in the model — no formula needed.

2. **Computed dimensions become formula ATTRIBUTEs.** `DATE_TRUNC('MONTH', transaction_date)`
   translates to `start_of_month ( [TRANSACTIONS::transaction_date] )`. Create a
   `formulas[]` entry and a `columns[]` entry with `formula_id`.

3. **`display_name` becomes the ThoughtSpot column name; `name` is the identifier.**
   When the MV has a `display_name`, use it as the column `name` in the model TML.
   When absent, title-case the `name` field.

4. **`synonyms` live under `properties:`, not at the column root.** ThoughtSpot silently
   drops top-level `synonyms:` on import. Always nest under `properties:` with
   `synonym_type: USER_DEFINED`.

5. **Arithmetic inside aggregates requires a formula.** `SUM(unit_price * quantity * (1 - discount))`
   is not a simple `SUM(col)` and cannot be expressed with `column_id` + `aggregation`.
   Translate the full expression into a ThoughtSpot formula.

6. **`COUNT(DISTINCT col)` must always be a formula using `unique count`.** Two words,
   space — NOT `unique_count` with underscore. Never use `aggregation: COUNT_DISTINCT`
   on a physical `column_id` — ThoughtSpot silently overrides `column_type` to ATTRIBUTE.

7. **Ratio measures inline all aggregates — no cross-formula references.**
   `SUM(a) / COUNT(DISTINCT b)` translates to `sum ( [a] ) / unique count ( [b] )` in
   a single formula. Cross-formula references fail during TML import, so always inline
   the aggregate expressions.

8. **`FILTER (WHERE cond)` uses native `*_if` functions.** `SUM(expr) FILTER (WHERE cond)`
   becomes `sum_if ( cond , expr )`. The condition is the first argument, the measure
   expression is the second.

9. **Rolling windows strip the outer aggregate.** `SUM(a * b)` with
   `window: [{range: trailing 7 day}]` becomes `moving_sum ( [a] * [b] , 7 , -1 , [date] )`.
   The outer `SUM` is removed because `moving_sum` aggregates internally. The sort
   argument must be the physical date column (`[TABLE::col]`), not a formula reference.
   **Corrected 2026-07-09** — the original write-up of this pattern used
   `moving_sum([a] * [b], 7, 0, [date])`, which live testing showed reproduces
   `trailing 8 day inclusive`, not `trailing 7 day` (default/exclusive). `end=-1`
   (not `end=0`) is required to exclude the anchor row for the default/exclusive
   form — see
   `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1/C2) and "Measure 5" above.

   Row-positional: matches Databricks' date-interval trailing/leading windows only when the order column is dense at the window's unit grain (one row per unit, no gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

   This example's `transaction_date` is daily-dense, so the formula above is
   exact — verify density before reusing this pattern on a gapped source.

10. **`CASE WHEN ... END` translates to `if (..., val, val)`; `COUNT(*)` becomes
    `count ( 1 )`.** ThoughtSpot has no `COUNT(*)` syntax. `CAST(... AS DOUBLE)` is
    implicit — division of two numeric aggregates returns a double naturally.

11. **MV `filter:` always becomes a boolean formula column with model-level enforcement.**
    Create a formula `[TABLE::col] != 'value'`, add it as an ATTRIBUTE column, then add
    a `filters:` section with `oper: in, values: ['true']`. This enforces the filter on
    all queries. Do NOT rely on description-only documentation — users will not apply
    column filters manually.

12. **MV top-level `comment:` maps to model `description`.** The view-level comment becomes
    the model description, with a note about the MV filter and source MV name appended.
