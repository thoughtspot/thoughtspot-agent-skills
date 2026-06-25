# SpotQL UDF reference

The SpotQL date/time functions and aggregate/window support. Use these **instead of**
standard PostgreSQL date functions — `DATE_TRUNC`, `NOW()`, `CURRENT_DATE`, `AGE`, and
`INTERVAL` arithmetic are all forbidden in SpotQL. Lifted from agent-expressibility-eval's
SpotQL UDF reference (verified against build 26.7.0.cl-72; re-verified on champ-staging
2026-06-25).

## Extraction UDFs — date column → integer

Take a date column, return an integer. Safe anywhere — `SELECT`, `WHERE`, `GROUP BY`,
`ORDER BY`, and inside `CASE` predicates of aggregates.

| UDF | Returns | For 2026-05-20 |
|---|---|---|
| `YEAR_NUMBER(date_col)` | INT | 2026 |
| `QUARTER_NUMBER(date_col)` | INT (1–4) | 2 |
| `MONTH_NUMBER(date_col)` | INT (1–12) | 5 |
| `WEEK_IN_YEAR_NUMBER(date_col)` | INT (1–53) | 21 |
| `DAY_NUMBER(date_col)` | INT (1–366) | 140 |
| `DAY_IN_MONTH_NUMBER(date_col)` | INT (1–31) | 20 |
| `DAY_IN_WEEK_NUMBER(date_col)` | INT (1–7, Mon=1) | 3 |
| `DAY_NAME(date_col)` | VARCHAR | "wednesday" |

Drive conditional aggregation off these (integer date-parts), not raw-date comparisons:

```sql
SUM(CASE WHEN YEAR_NUMBER("t1"."Order Date") = 2026
              AND WEEK_IN_YEAR_NUMBER("t1"."Order Date") = 21
         THEN "t1"."Amount" END)
```

## Period-boundary UDFs — return a date, take ZERO arguments

Anchored to the server's current date. `START_OF_CURRENT_MONTH()` — **empty parens**;
`START_OF_CURRENT_MONTH("Order Date")` parse-errors.

| UDF | Returns |
|---|---|
| `START_OF_CURRENT_YEAR()` / `_QUARTER()` / `_MONTH()` / `_WEEK()` / `_DAY()` | First day of that period |
| `START_OF_LAST_YEAR()` / `_QUARTER()` / `_MONTH()` / `_WEEK()` | First day of the prior period |
| `END_OF_*()` | Last day of the corresponding period |

Don't use a boundary UDF as a `WHERE` filter value directly — pair with a `DIFF_*` UDF.

## Diff UDFs — integer distance between two periods

| UDF | Example |
|---|---|
| `DIFF_YEAR(d1, d2)` | `DIFF_YEAR(START_OF_CURRENT_YEAR(), "d") = 0` → "d" is in the current year |
| `DIFF_QUARTER(d1, d2)` | `= 1` → last complete quarter |
| `DIFF_MONTH(d1, d2)` | `BETWEEN 1 AND 12` → last 12 complete months |
| `DIFF_WEEK(d1, d2)` | `= 1` → last complete week |
| `DIFF_DAY(d1, d2)` | `BETWEEN 1 AND 15` → last 15 days |
| `DIFF_HOUR` / `DIFF_MINUTE` | hour / minute distance |

**Canonical "last N complete periods"** (works in WHERE and in CASE-in-aggregate):

```sql
WHERE DIFF_MONTH(START_OF_CURRENT_MONTH(), "t1"."Order Date") BETWEEN 1 AND 12
```

## Aggregate functions

| Function | Notes |
|---|---|
| `SUM`, `AVG`, `MIN`, `MAX` | Work everywhere. `SUM` is the default for additive measures. |
| `COUNT("t1"."col")` | **Must name a column** — `COUNT(*)` / `COUNT(1)` are rejected. |
| `STDDEV_SAMP` / `STDDEV_POP`, `VAR_SAMP` / `VAR_POP`, `MEDIAN` | **Scalar context only** (no `GROUP BY` in the same query) — see `patterns.md`. Always write the explicit `_SAMP`/`_POP` suffix; bare `STDDEV` silently means `_POP`. |
| `PERCENTILE_CONT` / `PERCENTILE_DISC` / `APPROX_PERCENTILE` | ✗ Not supported. Only `MEDIAN` works as a percentile. |

> **`AGG(col)` — for aggregate-formula columns (verified live 2026-06-25).** A formula
> column whose expression already contains an aggregate (`sum`, `count`, `group_aggregate`,
> `last_value(sum(...))`, …) must be wrapped in `AGG("col")` so it isn't re-aggregated.
> **Do not `SUM` it** — `SUM("aggregate formula")` errors with
> `NESTED_AGGREGATE_NOT_SUPPORTED`. Use real aggregates (`SUM`/`AVG`/…) only on **raw**
> measure columns. `AGG()`'s argument must be a bare column reference. See `spotql-rules.md`
> § Aggregation for how to tell the two apart.

## Window functions — `OVER (PARTITION BY … ORDER BY …)`

Working on current builds: `RANK()`, `DENSE_RANK()`, `ROW_NUMBER()`, `NTILE(n)`,
`LAG(col)`/`LEAD(col)` (and explicit offsets `LAG(col, N)`), `NTH_VALUE(col, N)`,
`SUM(col) OVER (PARTITION BY … ORDER BY …)` (cumulative and with explicit
`ROWS BETWEEN …` frames), and `STDDEV_SAMP(SUM(col)) OVER ()` (the anomaly pattern).

`NTILE`, explicit `LAG`/`LEAD` offsets > 1, `NTH_VALUE`, and `ROWS BETWEEN` frames were all
broken on older builds and are now fixed (verified champ-staging 2026-06-25 / SCAL-306544).
See `limitations.md` for the dated, ticket-linked list.

For "compare to N rows back" (N>1) or "true rolling N-period average", there is no working
SpotQL form — see `patterns.md` / say it can't be done.

## CAST

Cast only `VARCHAR`/`TEXT` → numeric/date. Already-numeric (`DOUBLE`, `INT64`, `INT32`,
`NUMERIC`, `FLOAT`) and already-date (`DATE`, `TIMESTAMP`) columns need no cast — omit it.

## Forbidden (recap)

`DATE_TRUNC`, `NOW()`, `CURRENT_DATE`, `AGE`, `INTERVAL` arithmetic · `SELECT *` ·
`COUNT(*)` / `COUNT(1)` · `WITH RECURSIVE` · subqueries (`FROM (SELECT …)`, `IN (SELECT …)`,
`EXISTS`) · `UNION`/`EXCEPT`/`INTERSECT` · non-equi `JOIN … ON` · CTE self-join ·
`LENGTH()` · `GROUP BY 1` · `col NOT IN (…)` · arithmetic between an aggregate and a
numeric literal (returns zeros).
