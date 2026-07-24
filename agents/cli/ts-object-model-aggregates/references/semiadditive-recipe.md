# Semi-additive (period-end snapshot) aggregate — hand-build recipe

`recommend` lists `last_value`/`first_value` snapshot measures under
`semiadditive_measures` and does **not** auto-generate an aggregate for them. A
correct period-end snapshot needs a **windowed** DDL (`last_value() OVER
(PARTITION BY grain ORDER BY date)`) that the flat/positional generators can't
emit — flat-summing a snapshot across periods gives wrong numbers. So build it
by hand with this recipe, and **gate it on a numeric check before importing**.

Canonical example: `Inventory Balance = last_value(sum([DM_INVENTORY::FILLED_INVENTORY]),
query_groups(), {[DM_DATE_DIM::DATE]})` on the Dunder Mifflin model — a per-product
daily stock snapshot, summarised to a month-end balance.

## 1. Grain

`<date> (month) × <product/other non-date dims>`, keyed on the **conformed shared
date** the measure's formula references (`{[DM_DATE_DIM::DATE]}`), exposed on the
Model as e.g. `Transaction Date`. Snapshot measures have no customer/order
dimension — only the dims the snapshot fact carries.

## 2. Warehouse DDL — store the month-end per (month, product)

Sum across the non-date dims (products) per snapshot date, take the **last value
in the month** as the period-end, collapse to one row per (month, product):

```sql
CREATE OR REPLACE TABLE <DB>.<SCHEMA>.<AGG> AS
WITH month_end AS (
  SELECT DATE_TRUNC('MONTH', i.<BALANCE_DATE>)::DATE       AS "Transaction Date",
         i.<PRODUCT_ID>                                     AS product_id,
         last_value(i.<FILLED_INVENTORY>) OVER (
           PARTITION BY DATE_TRUNC('MONTH', i.<BALANCE_DATE>), i.<PRODUCT_ID>
           ORDER BY i.<BALANCE_DATE>
           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS bal
  FROM <DB>.<SCHEMA>.<INVENTORY> i
)
SELECT "Transaction Date", product_id,
       MIN(bal) AS "inv_balance_month_end"     -- bal is constant within the window; MIN collapses
FROM month_end GROUP BY "Transaction Date", product_id
-- join DM_PRODUCT/DM_CATEGORY for "Product Name"/"Product Category" attributes
```

For a **combined** monthly sales+inventory table, `FULL OUTER JOIN` a monthly
`SUM(amount)`/`SUM(quantity)` CTE onto this on (month, product) — both keyed to the
same shared calendar month.

## 3. Aggregate Table + Model TML

- Table columns: the dims + `inv_balance_month_end` (type from the source column).
- Model: expose the dims as ATTRIBUTE, and the measure as a **formula** re-applying
  the snapshot over the aggregate's own month column:

  ```
  Inventory Balance = last_value ( sum ( [inv_balance_month_end] ) ,
                                    query_groups ( ) , { [Transaction Date] } )
  ```

  This sums across products within the query grouping and takes the period-end
  across months — so it re-aggregates correctly to quarter/year.
- Propagate RLS (reuse `ts aggregate generate`'s RLS handling / the two-pass
  `ts tables create`) and associate via `aggregated_models` with
  `date_aggregation_info: [{column_id: "Transaction Date", bucket: MONTHLY}]`.

## 4. Numeric gate — MANDATORY before import

Never import a snapshot aggregate you haven't numerically verified. Compare the
aggregate's period-end total to the raw fact's latest-date total:

```sql
-- ground truth: current stock = sum on the latest balance date
SELECT SUM(<FILLED_INVENTORY>) FROM <INVENTORY>
WHERE <BALANCE_DATE> = (SELECT MAX(<BALANCE_DATE>) FROM <INVENTORY>);
-- aggregate: latest month's month-end, summed
SELECT SUM("inv_balance_month_end") FROM <AGG>
WHERE "Transaction Date" = (SELECT MAX("Transaction Date") FROM <AGG>);
```

They must match exactly (Dunder Mifflin: **3,828**). Also spot-check a few
individual months. Only then register/import.

## 5. Routing verification

Snapshot measures use the **`SUM(...)`** AgentQL wrapper (per `ts spotql
classify-columns`; `AGG(...)` errors `NON_CONVERTIBLE_FUNCTION`). Confirm
`SUM("Inventory Balance")` at month grain routes to the aggregate and returns the
verified numbers.
