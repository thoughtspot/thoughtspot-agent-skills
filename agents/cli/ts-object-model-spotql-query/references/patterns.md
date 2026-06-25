# SpotQL patterns

Condensed recipes for the recurring shapes. Each says when to use it and gives a skeleton.
Compose them (e.g. period-over-period inside a top-N). Distilled from
agent-expressibility-eval's SpotQL pattern library. Read `spotql-rules.md` and
`udf-reference.md` first — these patterns assume those rules.

## Last N complete periods

**When:** "last 12 months", "last 4 weeks", "last 30 days". Use a `DIFF_*` UDF against the
period boundary — not a raw-date `>=` filter (which silently misbehaves inside aggregates).

```sql
SELECT "t1"."Product Category", SUM("t1"."Amount") AS "Total Sales"
FROM "Model" AS "t1"
WHERE DIFF_MONTH(START_OF_CURRENT_MONTH(), "t1"."Order Date") BETWEEN 1 AND 12
GROUP BY "t1"."Product Category"
```

`BETWEEN 1 AND N` = last N **complete** periods. Use `BETWEEN 0 AND N-1` to include the
current (partial) period.

## Year-over-year growth

**When:** "sales this year vs last year", "% growth". Compute each year with conditional
aggregation off `YEAR_NUMBER`, then the ratio of aggregates (never `× 100` in SQL — that
zeros out; present the ratio as a percentage in your rendering).

```sql
SELECT "t1"."Product Category",
       SUM(CASE WHEN YEAR_NUMBER("t1"."Order Date") = 2026 THEN "t1"."Amount" END) AS "This Year",
       SUM(CASE WHEN YEAR_NUMBER("t1"."Order Date") = 2025 THEN "t1"."Amount" END) AS "Last Year",
       SUM(CASE WHEN YEAR_NUMBER("t1"."Order Date") = 2026 THEN "t1"."Amount" END)
         / NULLIF(SUM(CASE WHEN YEAR_NUMBER("t1"."Order Date") = 2025 THEN "t1"."Amount" END), 0)
         AS "YoY Ratio"
FROM "Model" AS "t1"
GROUP BY "t1"."Product Category"
```

Compute the literal year numbers from "today" (current year, prior year) — don't hardcode.
If the current year is partial and the question is open-ended, compare the two most recent
**complete** years instead.

## Top-N and top-N-per-group

**When:** "top 10 customers", "top 3 products in each category". Aggregate in a CTE, rank
with a window function, filter on the rank in the main query.

```sql
WITH ranked AS (
  SELECT "t1"."Customer", "t1"."Product Category",
         SUM("t1"."Amount") AS "Total Sales",
         ROW_NUMBER() OVER (PARTITION BY "t1"."Product Category" ORDER BY SUM("t1"."Amount") DESC) AS "Rank"
  FROM "Model" AS "t1"
  GROUP BY "t1"."Customer", "t1"."Product Category"
)
SELECT "Customer", "Product Category", "Total Sales"
FROM ranked
WHERE "Rank" <= 3
```

Plain "top 10" (no per-group): drop the `PARTITION BY`, or just `ORDER BY … DESC LIMIT 10`.
Use `RANK()` (ties share a rank) vs `ROW_NUMBER()` (strict) per intent.

## Period-over-period pivot

**When:** "this month vs last month" side by side. Conditional aggregation with `DIFF_*`
buckets, one column per period.

```sql
SELECT "t1"."Product Category",
       SUM(CASE WHEN DIFF_MONTH(START_OF_CURRENT_MONTH(), "t1"."Order Date") = 1 THEN "t1"."Amount" END) AS "Last Month",
       SUM(CASE WHEN DIFF_MONTH(START_OF_CURRENT_MONTH(), "t1"."Order Date") = 2 THEN "t1"."Amount" END) AS "Prior Month"
FROM "Model" AS "t1"
GROUP BY "t1"."Product Category"
```

## Statistics / anomaly detection

**When:** standard deviation, median, "outliers". `STDDEV_*`/`VAR_*`/`MEDIAN` only work in
**scalar context** (no `GROUP BY`). For per-group sums vs the global spread, use the window
form `STDDEV_SAMP(SUM(col)) OVER ()`:

```sql
WITH per_cat AS (
  SELECT "t1"."Product Category", SUM("t1"."Amount") AS "Total Sales"
  FROM "Model" AS "t1" GROUP BY "t1"."Product Category"
)
SELECT "Product Category", "Total Sales",
       AVG("Total Sales") OVER () AS "Mean",
       STDDEV_SAMP("Total Sales") OVER () AS "Std Dev"
FROM per_cat
```

## Semi-additive measures

**When:** a measure that must not be summed across time — e.g. an inventory balance, an
account balance.

**First choice — use the Model's own formula.** If the Model already has a semi-additive
**aggregate-formula** column (its formula is `last_value(sum(...))` / `first_value(...)` —
e.g. `Inventory Balance`), just wrap it in `AGG()`. The formula encodes the
non-additivity; `AGG()` returns the right number. Do **not** `SUM` it (that double-counts
*and* errors `NESTED_AGGREGATE_NOT_SUPPORTED` on an aggregate formula).

```sql
SELECT "t1"."Product Category", AGG("t1"."Inventory Balance") AS "Inventory Balance"
FROM "Model" AS "t1" GROUP BY "t1"."Product Category"
```

**Only if no such column exists:** hand-roll "latest value per entity" with
`ROW_NUMBER()` over the raw measure ordered by date desc, filtered to rank 1. If the
correct behaviour is unclear from the TML, say so rather than silently `SUM`.

## When there's no working form

Still no reliable SpotQL form today: non-`MEDIAN` percentiles, per-group `STDDEV`/`VAR`,
subqueries (`IN (SELECT …)` / `FROM (SELECT …)`), set operations (`UNION` silently drops a
branch), `QUALIFY` and `FILTER (WHERE …)` (both silently dropped), `ROLLUP`/`CUBE`,
self-joins, and non-equi joins. Don't emit a query that looks right but returns wrong
numbers — explain the limitation instead.

Several constructs that *used* to be unsupported now work — `NTILE`, explicit `LAG`/`LEAD`
offsets, `ROWS BETWEEN` window frames (so true rolling N-period averages are now
expressible), multi-CTE joins, and aggregate×literal arithmetic. See `limitations.md` for
the current, dated, ticket-linked list.
