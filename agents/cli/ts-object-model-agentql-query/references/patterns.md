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
  returns the measure column and avoids the aggregated-branch-in-CTE set-op limitation.

## When there's no working form

Still no reliable AgentQL form today: non-`MEDIAN` percentiles, per-group `STDDEV`/`VAR`,
subqueries (`IN (SELECT …)` / `FROM (SELECT …)`), `QUALIFY` and `FILTER (WHERE …)` (both
silently dropped), `ROLLUP`/`CUBE`, self-joins, non-equi joins, and ORDER BY / LIMIT on set
operator results. Don't emit a query that looks right but returns wrong numbers — explain
the limitation instead.

Several constructs that *used* to be unsupported now work — set operations (`UNION ALL`,
`UNION`, `EXCEPT`, `INTERSECT` at the top level), `NTILE`, explicit `LAG`/`LEAD` offsets,
`ROWS BETWEEN` window frames (so true rolling N-period averages are now expressible),
multi-CTE joins, and aggregate×literal arithmetic. See `limitations.md` for the current,
dated, ticket-linked list.

## Set operations

**When:** combining disjoint result sets, subtracting one set from another, or finding the
intersection of two sets. Since [SCAL-313049](https://thoughtspot.atlassian.net/browse/SCAL-313049),
set operations work at the **top level** of the query, and inside a CTE when no branch
carries an aggregate measure.

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
- **Cannot** apply ORDER BY or LIMIT to the combined result (silently mishandled).
- Inside a user-defined CTE, set operations work **only when no branch contains an
  aggregate measure** — an aggregated branch (`SUM(col) … GROUP BY`) is a hard error.
  See `limitations.md`.
