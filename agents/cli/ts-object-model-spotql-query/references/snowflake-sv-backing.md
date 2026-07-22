# SpotQL over a Snowflake Semantic View backing (EXPERIMENTAL)

> **Status: EXPERIMENTAL / in dev.** Behaviour live-verified 2026-07-21 on the
> `ashok-direct-query` cluster (model `8ccee1a7-6fb5-4987-bfc8-dbadca9c6cab`,
> "Direct Query - Dunder Mifflin Sales & Inventory") and cross-checked natively
> on Snowflake (`thoughtspot_partner.ap-southeast-2`) against the backing SV
> `DUNDERMIFFLIN.PUBLIC_SV.TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY`. Full write-up
> and escalation: `~/Dev/spotQL-testing/docs/spotql-snowflake-sv-findings.md`.

## When this applies

The Model's backing warehouse object is a **Snowflake Semantic View** (SV), not a
plain table. Tells: the generated warehouse SQL references a `..._SV`-schema
object and wraps measures in Snowflake's `AGG(...)` function. ThoughtSpot queries
the SV by **direct name reference** (`SELECT dim, AGG(metric) FROM sv GROUP BY dim`),
not via the `SEMANTIC_VIEW(...)` clause. The rules below follow from that.

## Rules for the authoring agent

**R1 — `generate-sql` SUCCESS is not executability.** On SV-backed Models,
`generate-sql` passes queries that fail at execution (the NULL-key bug below,
inlined window functions). **Always `fetch-data` to confirm.**

**R2 — NULL grouping keys + a transform = hard failure (`100072`).** When a
derived grouping (e.g. `YEAR(date)`) is applied to a raw PK-backed dimension
column that carries NULL join keys, Snowflake throws
`100072: NULL result in a non-nullable column`. The PK dimension column is typed
`NOT NULL`; a NULL join key (a fact row whose FK is NULL) violates it once
materialised and transformed. **Fix: wrap the raw dimension column in a
nullable-typed expression before any function touches it:**

```sql
CASE WHEN sv.<col> IS NOT NULL THEN sv.<col> END   -- clearest; also IFF / NVL2
```

Do this **only in `SELECT`/`GROUP BY`, never in a `WHERE` predicate** (that would
defeat partition pruning). A plain cast (`col::TYPE`) or `col + 0` does **not**
work (Snowflake propagates `NOT NULL`); `COALESCE` on the metric does **not** fix
it (the NULL is on the key, not the metric). For date parts specifically,
computing `YEAR(...)`/`MONTH_NUMBER(...)` directly in the SV query also works
(the derived expression is nullable-typed) — but that leniency is date-specific,
so prefer the `CASE`-wrap for any non-date key. No performance/pruning impact
(verified: identical bytes-scanned and partition pruning).

**R3 — Windowed / period analytics must be authored as CTE + outer window.**
Direct name reference cannot put a window function (`RANK`/`LAG`/`SUM() OVER`)
inline (Snowflake: *Unsupported feature 'WINDOW FUNCTIONS'*). Author them as
**aggregate-in-a-CTE, window-in-the-outer-SELECT**. Verified working this way:
cumulative running total, year-over-year (`LAG`), top-N-per-group (`RANK`).

**R4 — No inline subqueries in `FROM`.** `FROM (SELECT ...)` fails
`TABLE_NOT_FOUND`. Use a `WITH` CTE instead (CTEs work).

**R5 — Time bucketing: build from parts, on a fact-resident date.** There is no
date-truncation UDF (`START_OF_*_MONTH()` are zero-arg "current period" only).
Build a monthly series from `YEAR_NUMBER(date)` + `MONTH_NUMBER(date)`. Group on
a **fact-resident** date, not a shared date-dimension key, or R2 bites.

**R6 — Non-additive metrics do not reconcile to the grand total, and that is
correct.** A `COUNT(DISTINCT ...)` metric summed across a dimension finer than
its grain exceeds the total (an order spans products → counted per product). Do
**not** flag this as a fan/error. A reconciliation-to-grand-total guard is valid
only for purely additive (`SUM`) metrics.

**R7 — A grouping dimension with no join path to the metric's fact hard-errors.**
Not a query-form issue; the dimension simply does not join that fact. Nothing to
retry — surface it.

## What is NOT a bug (do not chase)

- Direct name reference and the `SEMANTIC_VIEW` clause return **identical values**.
- Snowflake handles **multi-fact** correctly; additive metrics do not fan across
  facts.
- Small/odd time-series numbers may just be **data** (e.g. a fact with mostly
  NULL FKs to the date dimension).

## Product limitation behind R2/R3 (why this is experimental)

The `CASE`-wrap (R2) and CTE (R3) workarounds fully cover correctness today, and
they are **portable**: Databricks uses the same direct-name-reference shape with
`MEASURE()` (which likewise cannot window inline), so these workarounds carry
over. Snowflake additionally offers the **`SEMANTIC_VIEW` clause**
(`SEMANTIC_VIEW( … DIMENSIONS … METRICS … )`) — value-identical, immune to the
`100072` bug natively, supports inline window functions, and is the only method
that can use semantic-view **variables** — but ThoughtSpot cannot emit it yet,
and it is Snowflake-only (no Databricks analogue). So treat it as a Snowflake
capability upgrade (mainly for variables), not a required fix. See the
escalation doc.

## Databricks note (live-tested 2026-07-21, not yet via ThoughtSpot)

The Databricks Metric View analogue uses `MEASURE()` (same idea as `AGG()`;
DBR 18.1+ also accepts `agg`), queried by direct name reference; there is **no**
`SEMANTIC_VIEW`-clause or variables equivalent. Verified against
`dunder_mifflin_sales_mv` that Databricks is **more forgiving** than Snowflake:
- **R2 (`CASE`-wrap) is Snowflake-only** — the `100072` null-key bug does NOT
  reproduce; Databricks tolerates NULL grouping keys (returns a NULL bucket).
- **R3 (CTE-for-windows) is Snowflake-only** — cumulative / YoY / rank run
  **inline** on Databricks (`SUM(MEASURE()) OVER`, `LAG(MEASURE()) OVER`,
  `RANK() OVER (ORDER BY MEASURE())`). Only windowing the measure itself
  (`MEASURE(x) OVER`) fails.
So apply R2/R3 **Snowflake-conditionally**; do not carry them to Databricks as
correctness requirements (they're merely harmless there).
