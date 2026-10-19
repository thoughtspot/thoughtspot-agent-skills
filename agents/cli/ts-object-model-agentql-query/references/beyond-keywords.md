# Questions that need AgentQL — and where it still can't go

ThoughtSpot keyword search answers most questions. This file collects the ones they **can't**,
where writing AgentQL is the point — and, just as important, the ones where **even AgentQL
hits a wall** and you need a rewrite or have to say no.

Each example uses the skill's canonical six-section output block (`SKILL.md` Step 6):
**1. Question · 2. AgentQL Sent · 3. DB SQL Generated · 4. Error & Explanation · 5. Key
Findings · 6. Results.** Every status, SQL shape and number below was live-verified on
`(Sample) Retail - Apparel` (the sample Model on every cluster), **26.9.0.cl, 2026-10-14**.
Re-probe before trusting them on another build — `tools/agentql-retest --suite limitations`
checks the failure modes.

> The SQL in section 3 is trimmed for readability (physical table/column names, `LIMIT`
> wrappers and `CASE WHEN … IS NOT NULL` null-guards removed). Run `generate-sql` for the
> exact statement.

---

## 1. Rank *within* a partition — "the #1 product in each region"

The ThoughtSpot `rank` formula ranks across the whole answer (or by `query_groups()`); it
has no arbitrary `PARTITION BY`, so "the top product **within each region**" is not a single
rank formula or keyword. AgentQL expresses it with a window `RANK()`.

**1. Question.** For each region, which product has the highest total sales?

**2. AgentQL Sent.**
```sql
WITH ranked AS (
  SELECT "t1"."region" AS r, "t1"."product" AS p, SUM("t1"."sales") AS s,
         RANK() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) AS rnk
  FROM "(Sample) Retail - Apparel" AS "t1"
  GROUP BY "t1"."region", "t1"."product"
)
SELECT r, p, s, rnk FROM ranked WHERE rnk <= 1
```

**3. DB SQL Generated** (`generate-sql` → `SUCCESS`).
```sql
WITH "qt_0" AS (
  SELECT "ta_1"."REGION", "ta_2"."PRODUCTNAME", sum("ta_3"."SALES"),
         rank() over (partition by "ta_1"."REGION" order by sum("ta_3"."SALES") desc)
  FROM "FACT_RETAPP_SALES" "ta_3"
    JOIN "DIM_RETAPP_PRODUCTS" "ta_2" ON "ta_3"."PRODUCTID" = "ta_2"."PRODUCTID"
    JOIN "DIM_RETAPP_STORES"   "ta_1" ON "ta_3"."STOREID"   = "ta_1"."STOREID"
  GROUP BY "REGION", "PRODUCTNAME"
)
SELECT * FROM "qt_0" WHERE "rank" <= 1
```

**4. Error & Explanation.** None — it compiles and runs. But note the shape: the rank is
computed in a **CTE** and filtered in the outer `WHERE`. Don't reach for `QUALIFY` — AgentQL
**silently drops the `QUALIFY` clause** (no `ROW_NUMBER` is emitted; you get *every* row, not
the filtered set — [SCAL-319330](https://thoughtspot.atlassian.net/browse/SCAL-319330)). The
CTE + `WHERE` is the only reliable form.

**5. Key Findings.** AgentQL does what the rank formula can't — ranking *within a group* —
because it has true window functions with `PARTITION BY`. The catch is `QUALIFY`: it looks
like the natural way to filter on a window result and it's a trap. Materialise the rank in a
CTE instead.

**6. Results.**

| region | product | sales | rnk |
|---|---|--:|:-:|
| East | Pathwalker vest | 3,862,371.05 | 1 |
| Midwest | Synch vest | 3,473,704.84 | 1 |
| South | Yosemite jacket | 680,392.33 | 1 |
| Southwest | Yosemite jacket | 2,020,829.85 | 1 |
| West | … | … | 1 |

---

## 2. A rolling window by *calendar days* — "sales in the preceding 7 days"

This one is **difficult-to-impossible** in AgentQL, and the reason is subtle. The TS
`moving_sum` formula (and AgentQL window frames) count **rows**, not days.

**1. Question.** For each day, the total sales over that day and the six calendar days
before it.

**2. AgentQL Sent** (the form that *works* — a 7-**row** trailing window over a daily-totals
CTE):
```sql
WITH daily AS (
  SELECT "t1"."date" AS d, SUM("t1"."sales") AS s
  FROM "(Sample) Retail - Apparel" AS "t1"
  GROUP BY "t1"."date"
)
SELECT d, s, SUM(s) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS roll7
FROM daily ORDER BY d
```
And the form you'd *want* (a true calendar range), which is **rejected**:
```sql
... SUM(s) OVER (ORDER BY d RANGE BETWEEN INTERVAL '6' DAY PRECEDING AND CURRENT ROW) ...
```

**3. DB SQL Generated.** The `ROWS` form compiles (`SUCCESS`) to a Snowflake
`sum(...) over (order by ... rows between 6 preceding and current row)`. The `RANGE INTERVAL`
form produces no SQL — it fails at compile.

**4. Error & Explanation.**
- `moving_sum(sum("t1"."sales"), 6, 0)` → **`QUERY_GEN_ERROR` — "Unknown function"**.
  `moving_sum` is a *formula* function, not AgentQL syntax; use a window frame instead.
- `RANGE BETWEEN INTERVAL '6' DAY PRECEDING` → **`QUERY_GEN_ERROR` — "CURRENT ROW,
  UNBOUNDED, or integer literal expected"**. AgentQL frames accept an **integer row count
  only**; there is no calendar-interval `RANGE`.

**5. Key Findings.** `ROWS BETWEEN 6 PRECEDING` counts **six rows back**, not six days. On a
gap-free daily series the two coincide — but the instant a date has no sales, the 7-row
window reaches back **more than 7 calendar days** and the number is silently wrong. Because
the calendar `RANGE` form is rejected, AgentQL **cannot guarantee "the preceding 7 days" on
its own**. You either feed it a densified daily spine (every date present, zero-filled) so
rows == days, or you compute the window outside AgentQL. Say this plainly rather than shipping
a `ROWS` window and calling it "last 7 days."

**6. Results** (this sample's dates happen to be consecutive, so here 7 rows == 7 days):

| date | daily sales | rolling 7 |
|---|--:|--:|
| 2021-06-17 | 344,201.86 | 344,201.86 |
| 2021-06-18 | 345,368.78 | 689,570.64 |
| 2021-06-19 | 361,488.92 | 1,051,059.56 |
| 2021-06-20 | 341,696.36 | 1,392,755.92 |

---

## 3. Cohort / sub-query analysis — "for the Jackets cohort, sales by region"

A cohort question is a semi-join: *restrict to a set defined by one query, aggregate over
another*. In SQL you'd write `WHERE product IN (SELECT …)`. In AgentQL that form **compiles
and then fails** — the rewrite is a CTE join.

**1. Question.** Across all regions, total sales of the products that are sold as item
type "Jackets".

**2. AgentQL Sent.**
```sql
WITH cohort AS (
  SELECT "t2"."product" AS p
  FROM "(Sample) Retail - Apparel" AS "t2"
  WHERE "t2"."item type" = 'Jackets'
  GROUP BY "t2"."product"                 -- load-bearing: dedupe the join key
), s AS (
  SELECT "t1"."region" AS r, "t1"."product" AS p, SUM("t1"."sales") AS sls
  FROM "(Sample) Retail - Apparel" AS "t1"
  GROUP BY "t1"."region", "t1"."product"
)
SELECT s.r, SUM(s.sls) AS total
FROM s JOIN cohort c ON s.p = c.p
GROUP BY s.r
```

**3. DB SQL Generated** (`SUCCESS`) — two CTEs and an equi-join; no subquery in the `WHERE`.

**4. Error & Explanation.** The intuitive `IN (SELECT …)` form is the trap:
```sql
... WHERE "t1"."product" IN (SELECT "t2"."product" FROM "…" WHERE "t2"."item type" = 'Jackets') ...
```
`generate-sql` returns **`SUCCESS`**, but `fetch-data` fails with
**`QUERY_EXECUTION_FAILED` — SQL compilation error**: the subquery is passed through
**untranslated** into the warehouse SQL
([SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936)). A green `generate-sql`
is *not* proof the query runs. The CTE + equi-join is the only expressible semi-join — and the
`GROUP BY` on the cohort key is mandatory: without it a product matched twice multiplies the
join and the outer `SUM` double-counts.

**5. Key Findings.** Cohort questions *are* answerable — but not the way you'd write them in
SQL. `IN (SELECT …)` is worse than "limited": it passes validation and fails at execution.
The expressible envelope is narrower than SQL — correlated subqueries, `NOT IN`, and
`EXISTS`-with-aggregate have no clean AgentQL form; a membership cohort rewrites to a CTE
join, and some cohort shapes don't rewrite at all.

**6. Results.**

| region | total sales |
|---|--:|
| East | 49,372,530.31 |
| Midwest | 43,666,115.41 |
| South | 8,213,691.54 |
| West | 64,481,244.41 |
| Southwest | … |

---

## 4. A common function AgentQL doesn't support — percentiles (and the std sample/population note)

**1. Question.** What is the median (50th-percentile) sale amount? And the standard deviation
of regional sales?

**2. AgentQL Sent.**
```sql
-- percentile, the obvious way:
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "t1"."sales") FROM "(Sample) Retail - Apparel" AS "t1"
-- standard deviation, the obvious way:
SELECT STDDEV_SAMP("t1"."sales") FROM "(Sample) Retail - Apparel" AS "t1"
-- standard deviation, the form that works (materialise in a CTE, then the statistic):
WITH per AS (
  SELECT "t1"."region" AS r, SUM("t1"."sales") AS s
  FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
)
SELECT STDDEV_POP(s) OVER () AS pop, STDDEV_SAMP(s) OVER () AS samp FROM per LIMIT 1
```

**3. DB SQL Generated.** Only the CTE form compiles. The two scalar forms produce no SQL.

**4. Error & Explanation.**
- `PERCENTILE_CONT` / `PERCENTILE_DISC` / `APPROX_PERCENTILE` → **`UNSUPPORTED_AGGREGATE`**
  ([SCAL-314707](https://thoughtspot.atlassian.net/browse/SCAL-314707)). The **only**
  percentile AgentQL exposes is `MEDIAN` (which works scalar and grouped).
- `STDDEV_SAMP`/`STDDEV_POP`/`VAR_*` applied **directly to a Model column** →
  **`UNSUPPORTED_AGGREGATE`** in every context, scalar or grouped (regression, still present
  on 26.9.0.cl — [SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935)). Fix:
  the CTE statistics pattern (`patterns.md` § Statistics) — aggregate to a grain in a CTE,
  take the statistic over the CTE column.

**5. Key Findings.** Two different lessons.
- **Percentiles beyond the median are genuinely unavailable** — there is no workaround that
  makes `PERCENTILE_CONT` compile. If a question needs a 90th percentile, AgentQL can't answer
  it; that's a hard no, not a rewrite.
- **Standard deviation is available, but you choose sample vs population explicitly.** It is
  *not* "sample only": once you use the CTE form, **both `STDDEV_POP` and `STDDEV_SAMP`
  compile and return different numbers** (below). The gotcha is the direct scalar call, which
  fails for *any* flavour — so the fix is the CTE, and in it you spell out which standard
  deviation you mean.

**6. Results** (standard deviation of total sales across regions):

| STDDEV_POP | STDDEV_SAMP |
|--:|--:|
| 103,813,058.80 | 116,066,528.22 |

---

## The pattern across all four

| Question shape | Keywords / formula | AgentQL | Where it lands |
|---|---|---|---|
| Rank within a group | `rank` formula can't `PARTITION BY` | `RANK() OVER (PARTITION BY …)` in a CTE (not `QUALIFY`) | **AgentQL wins** |
| Preceding N calendar days | `moving_sum` counts rows | `ROWS` frame counts rows; no calendar `RANGE` | **Hard — needs a dense date spine or external compute** |
| Cohort / semi-join | — | CTE + deduped equi-join; `IN (SELECT …)` compiles then fails | **AgentQL wins, but only via rewrite** |
| Percentile / scalar stddev | — | `MEDIAN` only; `STDDEV` via CTE (pop *and* sample); `PERCENTILE_CONT` unsupported | **Mixed — stddev via workaround, percentiles are a hard no** |

The honest framing for a demo: AgentQL's window functions and CTEs take you well past what
keywords can express, but the dialect is narrower than warehouse SQL. When a shape has no form
(a non-median percentile, a true calendar-range window), say so — don't ship a query that
compiles into the wrong answer.
