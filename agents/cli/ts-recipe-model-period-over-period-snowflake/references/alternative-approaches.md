# Period-over-Period: the four approaches, measured

Four ways to put a prior-period value next to a current one. The recipe builds the
**role-play alias join**; this file records why, and when one of the others is the better
choice. Every number here was measured live on Snowflake
(`thoughtspot_partner.ap-southeast-2`) in August 2026, not reasoned about.

---

## The structural fact that decides everything

A measure aggregates the rows in the bucket you grouped by. When you group by an
**absolute date**, the current period's rows and the prior period's rows land in
**different buckets**. To get them onto one output row, something must *shift*: either the
grouping key, or the join. **No predicate on the aggregate can do it**, because a
row-level predicate cannot see the output bucket.

Verified, on real data, grouping by week:

| Formulation | Week 2019-06-03 |
|---|---|
| `sum_if(orderDate = add_days(orderDate, -364), amount)` | **NULL** — a row never equals itself shifted |
| `sum_if` over a correct *fixed* prior window | **NULL** — the current-period filter already removed the prior rows |
| Truth | 383,117.11 |
| Shift the **grouping key**: `DATE_TRUNC('week', orderDate + 364)` | **383,117.11** ✓ |

The shift belongs in the grouping key or the join. The alias join is precisely "shift the
key on a second copy of the fact, so both series can occupy one row" — a single query
groups by one expression, so without the second table instance you get the prior series
*or* the current series, never both.

---

## 1. Role-play alias join — what this recipe builds

A second alias of the fact joins the calendar on an offset column.

**Strengths**
- One metric definition per comparison, valid at **every** grain and with **every** attribute.
- Window-agnostic: nothing in the metric knows what the user will filter to.
- Immune to the sparsity bug in approach 4 — the date dimension *is* an outer spine, so a
  prior-period fact row always finds a home.

**Costs**
- Needs an offset column on the calendar (cheap: date arithmetic on a small dimension).
- In a hub topology, two aliases per comparison (hub + fact).
- In ThoughtSpot, alias nodes and a trimmed column set.

---

## 2. `sum_if` / conditional aggregation

**The governing rule, verified:**

> `sum_if` works **if and only if the grouping key is invariant across the two periods.**

| Grouping key | Works? | Why |
|---|---|---|
| Non-date attribute — category, employee, customer, product | **Yes, exact** | both periods' rows share the bucket |
| **Cyclic** date part — month-of-year 1-12, day-of-week, quarter number | **Yes, exact** | 2019-06 and 2018-06 both land in bucket 6 |
| Absolute date — day, week, actual month | **No** | 2019-06 ≠ 2018-06, different buckets |
| Mixed — category × actual month | **No** | the absolute-date component breaks alignment |

Measured, by category, 2019 vs 2018:

| Category | Current | Prior | vs truth |
|---|---|---|---|
| Printer Paper | 11,046,532.39 | 9,839,579.31 | exact |
| Printers | 5,366,642.08 | 5,198,382.89 | exact |

By category × **month-of-year**, month 6: `793,958.17 / 857,487.83` on one aligned row —
exact. By category × **actual month** it produced the **diagonal-NULL** shape: two
half-empty rows (2018-06 has prior only, 2019-06 has current only).

**When to prefer it:** the model only ever compares at period-invariant grains
("this year vs last year by rep", seasonality by month number). It needs **no offset
column and no extra tables at all** — genuinely simpler.

**Note the failure mode is visible**, not silently wrong: you get twice the rows, each half
NULL. That is much safer than a bad number and easy to spot on a Liveboard.

**Caveat:** the comparison window is baked into the expression, so varying it needs
parameters.

---

## 3. Window function (`LAG`)

Definable in a Snowflake Semantic View, but only in one form — windowed over the **metric
alias**, ordered by the **dimension construct**:

```sql
f.LAG52W AS LAG(f.AMOUNT, 52) OVER (ORDER BY dd.WEEK)   -- creates
LAG(SUM(f.AMT), 52) OVER (ORDER BY dd.WK)               -- invalid identifier 'DD.WK'
LAG(f.AMOUNT, 52) OVER (PARTITION BY dd.WEEK)           -- 002061 LAG requires ORDER BY
```

At its own grain it is exact. At any other grain it **hard-errors**:

```
010277: Required dimensions [DD.WEEK] must also be requested in the semantic view query.
```

Same error when grouping by month, and when grouping by a non-date attribute.

**This is the narrowest of the four.** The `52` is a row count and the `ORDER BY` names one
dimension, so the metric is welded to a single grain *and* drags a mandatory grouping
column into every query that touches it. You would need one metric per comparison **per
grain**, and "revenue vs last year by category" is unanswerable from a week-ordered LAG.

**When to prefer it:** a fixed single-grain trend where cumulative or moving aggregates are
wanted anyway.

---

## 4. Denormalised offset column on a pre-aggregated fact

Materialise the prior value as a column: a `SALES_BY_PRODUCT_DAY` table carrying both
`AMT` and `AMT_364_DAYS_AGO`.

**It is exact and fully additive** — a day-grain build rolls up correctly to week, month,
quarter and year; a product-grain build rolls up to category, supplier and any product
attribute. All verified against the alias join to the cent.

> ### The trap: the obvious construction silently under-counts
>
> Built with the natural `LEFT JOIN` from current to prior, a prior-period row whose key
> has **no current-period counterpart** has nothing to attach to and vanishes. Measured on
> (product × day) for one week: **82 orphaned product-days, 41,804.62 of revenue lost.**
> Category totals came back 121,806.64 against a true 135,094.63. No error — just low
> numbers.
>
> **Fix — `FULL OUTER JOIN` and rebuild the date from whichever side survived:**
> ```sql
> SELECT COALESCE(cur.D, DATEADD(day, 364, pri.D))  AS D,
>        COALESCE(cur.PRODUCT_ID, pri.PRODUCT_ID)   AS PRODUCT_ID,
>        COALESCE(cur.AMT, 0)                       AS AMT,
>        COALESCE(pri.AMT, 0)                       AS AMT_364_DAYS_AGO
> FROM agg cur FULL OUTER JOIN agg pri
>   ON pri.PRODUCT_ID = cur.PRODUCT_ID AND pri.D = DATEADD(day, -364, cur.D)
> ```
> Exact after the fix. The alias join cannot have this bug because the date dimension is
> already an outer spine.

**Other costs**
- **You pre-commit to a dimensional grain.** A (product × day) table cannot answer
  "vs 364 days ago by customer" *at all*. Fatal for Spotter-style ad hoc use.
- **It cannot live on an order-line fact** — order IDs do not recur, so "the same key 364
  days ago" is undefined. It is always a second object with its own ETL, not just a column.
- **Stale on restatement**: a correction to the prior period needs a rebuild across a
  364-day window. The alias join is always current.

**When to prefer it:** fixed known grain, very large fact, a target tool with no role-play
support, or a batch-refreshed warehouse where staleness is already accepted.

---

## Performance: they are equivalent — decide on semantics

Benchmarked on a purpose-built **100M-row fact, `CLUSTER BY (ORDER_DAY)` with a sorted
load, 24 micro-partitions, `average_depth 2.0`**. (A purpose-built fixture was necessary:
the production tables were 7.8 MB across 2 partitions and physically cannot show a pruning
difference.) Question: weekly revenue plus revenue 52 weeks earlier for Q1 2024. All
variants returned identical numbers; results stable over 3 repetitions.

| Variant | Fact scans | Partitions scanned | MB scanned | Avg elapsed |
|---|---|---|---|---|
| Alias join on the offset key | 2 | **4 / 24** | **15.1** | 937 ms |
| Conditional aggregation | 1 | **4 / 24** | **15.1** | 616 ms |
| Aggregate once + `LAG` | 1 | 5 / 24 | 18.3 | 612 ms |

Two assumptions people reliably get wrong, both disproven:

1. *"The alias join with a plain `SUM` is the most efficient plan."* It **ties** on I/O and
   was slower on elapsed time here — mostly compilation (366 ms vs 192 ms) from the second
   join branch.
2. *"Conditional aggregation won't prune."* It prunes to **exactly the same** 4 of 24
   partitions, because its predicate sits directly on the fact's own clustered date column.

Snowflake **does** apply runtime join pruning to the offset join. The offset branch is not
a full scan.

> ### Do not use `EXPLAIN` to compare these
> `EXPLAIN` reported the alias join as `partitionsAssigned=50, bytesAssigned=563,838,976`
> (~538 MB) — a **36× overstatement** of the 15.1 MB actually scanned, because static
> assignment ignores runtime pruning. It would lead you to reject the approach.
>
> Use runtime operator stats, and note the JSON path:
> ```sql
> SELECT OPERATOR_STATISTICS:pruning:partitions_scanned::INT,
>        OPERATOR_STATISTICS:io:bytes_scanned::INT
> FROM TABLE(GET_QUERY_OPERATOR_STATS(LAST_QUERY_ID()))
> WHERE OPERATOR_TYPE = 'TableScan';
> ```
> The plausible-looking `OPERATOR_STATISTICS:table_scan:partitions_scanned` silently
> returns NULL.

---

## Decision table

| | Alias join | `sum_if` | Window `LAG` | Denorm column |
|---|---|---|---|---|
| Absolute date grain (day/week/month) | ✅ any | ❌ | ⚠️ one grain only | ✅ |
| Period-invariant attribute | ✅ | ✅ | ❌ hard error | ⚠️ if in the key |
| Cyclic date part (month-of-year) | ✅ | ✅ | ❌ | ✅ |
| Slice by an attribute not planned for | ✅ | ✅ | ❌ | ❌ |
| Definitions needed | 1 per comparison | 1 per comparison | 1 per comparison **× grain** | 1 per comparison |
| Adapts to the user's filter | ✅ | ❌ baked in | ❌ | ✅ |
| Extra warehouse objects | offset column | **none** | none | pre-agg table + ETL |
| Correct after a restatement | ✅ | ✅ | ✅ | ❌ needs rebuild |
| I/O cost | tie | tie | tie | lowest |

**Default to the alias join.** Reach for `sum_if` when the model only ever compares at
period-invariant grains and you want zero warehouse change. Reach for the denormalised
column when the grain is fixed, the fact is huge, and staleness is acceptable. Reach for
`LAG` only for single-grain trend analysis.
