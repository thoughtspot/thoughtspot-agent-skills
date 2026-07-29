# AgentQL patterns

Condensed recipes for the recurring shapes. Each says when to use it and gives a skeleton.
Compose them (e.g. period-over-period inside a top-N). Distilled from
agent-expressibility-eval's AgentQL pattern library. Read `agentql-rules.md` and
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

**When:** standard deviation, median, "outliers". `MEDIAN` works directly (scalar, and
grouped as of jul.26.mt). `STDDEV_*`/`VAR_*` do **not** compile directly against a Model
column on jul.26.mt in *any* context (regression — [SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935);
scalar worked on earlier builds): **materialise the aggregate in a CTE first**, then take
the statistic over the CTE column — plain (`STDDEV_SAMP("Total Sales")` in a scalar outer
SELECT) for one global number, or the window form to keep per-group rows alongside:

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

**First choice — use the Model's own formula, wrapped in `SUM()`.** If the Model already
has a semi-additive column whose **outermost** op is `last_value`/`first_value` (formula
`last_value(sum(col), query_groups(), {date})` — e.g. `Inventory Balance`), wrap it in
**`SUM(...)`**. The formula encodes the non-additivity; the outer `SUM` is an identity
pass-through over the one already-collapsed value per query group, and it is what forces
the engine to resolve `query_groups()`.

```sql
SELECT "t1"."Product Category", SUM("t1"."Inventory Balance") AS "Inventory Balance"
FROM "Model" AS "t1" GROUP BY "t1"."Product Category"
```

**Do NOT use `AGG()` here** — on a `last_value`/`first_value` semi-additive measure it
errors `NON_CONVERTIBLE_FUNCTION` ("Non standard sql function QueryGroups"). This is the
one measure kind that takes `SUM` over `AGG`; verified live at grand-total, grouped, and
monthly grain (nebula-aggregate-aware, 2026-07-13), all matching Snowflake ground truth.
Run `ts agentql classify-columns` and follow the `wrapper` field (`semiadditive_measure` →
`SUM`) rather than guessing. Note the inverse case — `sum(last_value(...))`, where the
outer op is additive — is a normal aggregate-formula and takes `AGG()`.

**Only if no such column exists:** hand-roll "latest value per entity" with
`ROW_NUMBER()` over the raw measure ordered by date desc, filtered to rank 1. If the
correct behaviour is unclear from the TML, say so rather than silently `SUM`.

## Semi-join via CTE — membership filters without IN (SELECT …)

**When:** any filter that in plain SQL would be `WHERE col IN (SELECT …)` — "quantity by
category for products that appear in <some set>". Subqueries are unsupported, and on
jul.26.mt the `IN (SELECT …)` form even passes `generate-sql` before failing at
`fetch-data` ([SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936)) — so
this rewrite is the **only** expressible semi-join.

```sql
WITH "furniture_products" AS (
  SELECT "t2"."Product Name"
  FROM "Model" AS "t2"
  WHERE "t2"."Product Category" = 'Furniture'
  GROUP BY "t2"."Product Name"          -- the guard: dedupe the key
), "qty" AS (
  SELECT "t1"."Product Category", "t1"."Product Name", SUM("t1"."Quantity") AS "Qty"
  FROM "Model" AS "t1"
  GROUP BY "t1"."Product Category", "t1"."Product Name"
)
SELECT "q"."Product Category", SUM("q"."Qty") AS "Total Quantity"
FROM "qty" AS "q"
JOIN "furniture_products" AS "f" ON "q"."Product Name" = "f"."Product Name"
GROUP BY "q"."Product Category"
```

**The `GROUP BY` in the key CTE is load-bearing, not style.** `IN` is a semi-join — each
outer row is kept or dropped exactly once. A `JOIN` is relational multiplication — an
outer row matched by *k* key rows appears *k* times, and the outer `SUM` silently
double-counts. The two are equivalent **only when the key side is unique**, which the
`GROUP BY <key>` guarantees. Never join to a raw projection; pre-aggregating the measure
side does not protect you — deduping the key side is the only guard.

For the negation ("members NOT in the set") this rewrite does not apply — use the
LEFT-OUTER-JOIN + `IS NULL` shape in § Dimension-anchored anti-join below. (Verified live
2026-07-29, nebula-damian-alias: the `IN (SELECT …)` original fails at fetch; this rewrite
returns correct rows.)

## Dimension-anchored anti-join — members with no fact rows

**When:** "which customers have **no** sales?", "products never ordered", "suppliers with
no purchase transactions". The Model's dimension↔fact join is typically INNER, so members
with no fact rows vanish from every ordinary query — this pattern surfaces them **without
changing the Model's join definition**.

**Why it works (both verified live, nebula-spotQL 2026-07-10):**
1. **An attribute-only CTE compiles to a scan of the dimension table alone** — AgentQL only
   pulls the fact table (and the Model's inner join) into the generated SQL when a measure
   demands it. So a CTE selecting just the member attribute returns the *full* member list.
2. **Outer joins between CTEs compile and execute verbatim** — `LEFT OUTER JOIN`,
   `RIGHT OUTER JOIN` and `FULL OUTER JOIN` all work (equi-`ON` only, as with all CTE joins).

```sql
WITH "all_members" AS (
  SELECT "t1"."Customer Name"
  FROM "Model" AS "t1" GROUP BY "t1"."Customer Name"
), "with_sales" AS (
  SELECT "t2"."Customer Name", SUM("t2"."Amount") AS "Total Sales"
  FROM "Model" AS "t2" GROUP BY "t2"."Customer Name"
)
SELECT "a"."Customer Name", "s"."Total Sales"
FROM "all_members" AS "a"
LEFT OUTER JOIN "with_sales" AS "s" ON "a"."Customer Name" = "s"."Customer Name"
WHERE "s"."Total Sales" IS NULL
```

- Drop the `WHERE … IS NULL` to get **all** members with their activity (NULL = none) —
  the outer-join equivalent the Model's inner join can't express.
- The `IS NULL` lands in the outer query of the generated SQL (correct anti-join
  semantics). The compiled aggregated CTE wraps the sum in `CASE … ELSE 0`, but unmatched
  members never appear in that CTE at all (inner join), so they still surface as true NULLs.
- The anchor attribute must live on the **dimension side** (check `column_id` in the TML).
  A formula column spanning other tables drags their joins into the "all members" CTE and
  narrows the list.
- No set operators needed — `EXCEPT` could express "all minus active", but this form also
  returns the measure column.

## When there's no working form

Still no reliable AgentQL form today: non-`MEDIAN` percentiles, direct `STDDEV`/`VAR` on a
Model column (the CTE form above works), subqueries (`IN (SELECT …)` — use § Semi-join via
CTE — / `FROM (SELECT …)`), `QUALIFY` and `FILTER (WHERE …)` (both silently dropped),
`ROLLUP`/`CUBE`, self-joins, and non-equi joins. Don't emit a query that looks right but
returns wrong numbers — explain the limitation instead.

Several constructs that *used* to be unsupported now work — set operations (`UNION ALL`,
`UNION`, `EXCEPT`, `INTERSECT` at the top level and in CTEs, with ORDER BY / LIMIT on the
combined result as of jul.26.mt), `NTILE`, explicit `LAG`/`LEAD` offsets, `ROWS BETWEEN`
window frames (so true rolling N-period averages are now expressible), multi-CTE joins,
aggregate×literal arithmetic, `LENGTH()`, `CONCAT_WS`, and grouped `MEDIAN`. See
`limitations.md` for the current, dated, ticket-linked list.

## Set operations

**When:** combining disjoint result sets, subtracting one set from another, or finding the
intersection of two sets. Since [SCAL-313049](https://thoughtspot.atlassian.net/browse/SCAL-313049),
set operations work at the **top level** of the query and inside a CTE — including
aggregated branches, as of jul.26.mt (hard error on older builds).

**Basic UNION ALL** — combine results from different filters:

```sql
SELECT "t1"."Country", SUM("t1"."Revenue") AS "Total Revenue"
FROM "Model" AS "t1"
WHERE "t1"."Country" = 'united states'
GROUP BY "t1"."Country"
UNION ALL
SELECT "t1"."Country", SUM("t1"."Revenue") AS "Total Revenue"
FROM "Model" AS "t1"
WHERE "t1"."Country" = 'canada'
GROUP BY "t1"."Country"
```

**EXCEPT** — subtract one set from another:

```sql
SELECT "t1"."Country"
FROM "Model" AS "t1"
GROUP BY "t1"."Country"
EXCEPT
SELECT "t1"."Country"
FROM "Model" AS "t1"
WHERE "t1"."Country" = 'united states'
GROUP BY "t1"."Country"
```

**Chained operators** — precedence follows the SQL standard (INTERSECT binds tighter than
UNION ALL / EXCEPT). Use parentheses for explicit grouping:

```sql
(SELECT "t1"."Country" FROM "Model" AS "t1" WHERE "t1"."Country" = 'united states' GROUP BY "t1"."Country"
 UNION ALL
 SELECT "t1"."Country" FROM "Model" AS "t1" WHERE "t1"."Country" = 'canada' GROUP BY "t1"."Country")
EXCEPT
SELECT "t1"."Country" FROM "Model" AS "t1" WHERE "t1"."Country" = 'canada' GROUP BY "t1"."Country"
```

**Rules:**
- Each branch must have the same number of columns with compatible types.
- Each branch independently follows all AgentQL rules (alias, aggregation, GROUP BY).
- Branches can use different aggregate functions (`SUM` in one, `AVG` in another).
- HAVING, ILIKE, window functions all work inside individual branches.
- ORDER BY and LIMIT on the combined result work as of jul.26.mt (verified 2026-07-29;
  on older builds ORDER BY was silently dropped and LIMIT misplaced into the first
  branch — check the generated SQL if the build is older). See `limitations.md`.
