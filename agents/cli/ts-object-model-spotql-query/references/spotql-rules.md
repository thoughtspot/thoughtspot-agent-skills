# SpotQL rules — what makes a statement valid

SpotQL is a **restricted PostgreSQL dialect** with ThoughtSpot extensions. It runs against
a single ThoughtSpot **Model** (which maps to one or more warehouse tables behind the
scenes). Read this before writing any SpotQL. Distilled from the agent-expressibility-eval
SpotQL rules (system_prompt_v8) and verified live on champ-staging 2026-06-25.

> Source-of-truth note: these are constraints of the SpotQL engine, not of this skill.
> When a statement is rejected, the fix is almost always a rule below — not a retry.

## The shape of a valid query

```sql
SELECT "t1"."Product Category",
       SUM("t1"."Amount") AS "Total Sales"
FROM "Dunder Mifflin Sales & Inventory" AS "t1"
GROUP BY "t1"."Product Category"
```

- **One Model in `FROM`, always aliased**: `FROM "Model Display Name" AS "t1"`. Use the
  Model's display name (from `ts metadata search` / the TML `name:`), double-quoted. No
  schema-qualified or physical table names — the Model name is the only table reference.
- **Every column reference is alias-prefixed and double-quoted**: `"t1"."Order Date"`,
  never bare `"Order Date"`.
- **Column names must match the Model's TML exactly** (case-sensitive). Don't invent
  columns. If a column the question needs isn't in the Model, say so — don't guess.

## Aggregation

- **Measures get a real aggregate.** `SUM` is the default for additive measures; `AVG`,
  `MIN`, `MAX` as the question requires. `COUNT` must name an explicit column —
  **`COUNT(*)` and `COUNT(1)` are rejected**; use `COUNT("t1"."Order Id")`.
- **Attributes go in `GROUP BY`.** Every non-aggregate column in the SELECT must appear in
  `GROUP BY`. Every CTE that contains an aggregate must have its own `GROUP BY` (the main
  SELECT is the only exception — it may aggregate to a single global row without one).
- **MEASURE formula columns: use `SUM`.** ThoughtSpot ignores a formula column's own
  aggregation setting, so additive measure formulas are summed like any measure. For
  semi-additive measures (TML aggregation `last_value` / `first_value` — e.g. an inventory
  balance) see `patterns.md`; summing them double-counts.
- Statistical aggregates (`STDDEV_SAMP`/`STDDEV_POP`, `VAR_SAMP`/`VAR_POP`, `MEDIAN`) work
  in **scalar context only** (no `GROUP BY` in the same query) — see `udf-reference.md` and
  `patterns.md`. Always write the explicit `_SAMP`/`_POP` suffix.

## Aliasing (this one bites)

- **Never alias a plain Model column.** `SELECT "t1"."Product Category"` — not
  `... AS product_category`. The Model column name *is* the display name the analyst chose;
  aliasing it breaks downstream filters and round-trips (`WHERE "t"."alias" = …` →
  `COLUMN_NOT_FOUND`).
- **`AS` is only for aggregate/computed expressions** that have no Model name, and the
  alias must be **business-friendly Title Case**:
  - ✅ `SUM("t1"."Amount") AS "Total Sales"`
  - ✅ `"t1"."Sales" - "t1"."Cost" AS "Profit Margin"`
  - ✅ `CASE WHEN … END AS "Customer Segment"`
  - ❌ `SUM("t1"."Amount") AS total_sales` (snake_case — use `"Total Sales"`)
  - ❌ `"t1"."Product Category" AS category` (plain column — don't alias)

## Hard prohibitions (these are silent or hard failures)

- **No arithmetic between an aggregate and a numeric literal.** `SUM("x") * 100`,
  `SUM("x") / 100.0`, `SUM("x") * 30` all silently return **type=UNKNOWN, all-zero values**.
  Aggregate-to-aggregate is fine: `SUM("a") / NULLIF(SUM("b"), 0)`. For "× 100" percentages,
  compute the ratio of aggregates and present it as a rate — don't multiply by 100 in SQL.
- **No `SELECT *`** — enumerate columns. Inside a CTE it is hard-rejected.
- **No subqueries anywhere** — no `FROM (SELECT …)`, no `WHERE col IN (SELECT …)`, no
  `WHERE EXISTS (…)`, no scalar subselects. Use named CTEs and JOINs instead.
- **No set operations** — `UNION` / `UNION ALL` / `EXCEPT` / `INTERSECT` silently drop the
  second branch. If the question needs them, it can't be answered in one SpotQL statement.
- **No self-join of a CTE** (`[SELF_JOIN]`) and **no non-equi `JOIN … ON`** (only `=`
  allowed; use `CROSS JOIN` + `WHERE` for ranges).
- **No recursive CTEs** (`WITH RECURSIVE`), **no table functions** (`FLATTEN`, `UNNEST`,
  `GENERATOR`), **no `LENGTH()`**, **no `GROUP BY 1` ordinals**, **no `col NOT IN (...)`**
  (rewrite as `!=` chained with `AND`).
- **No forbidden date functions**: `DATE_TRUNC`, `NOW()`, `CURRENT_DATE`, `AGE`, `INTERVAL`
  arithmetic. Use the SpotQL UDFs in `udf-reference.md`.
- **Every CTE must reference a real column** — a CTE selecting only literals errors with
  `QueryTable has no owner tables`.

## CTEs

- Allowed and useful for multi-step logic, but each CTE sources from the one Model (or
  JOINs an earlier CTE — never `FROM another_cte`'s transformed result; inline instead).
- `SELECT` may appear only at the start of a CTE definition or the main query.

## CAST

Only `CAST` a `VARCHAR`/`TEXT` column to numeric/date. Columns already `DOUBLE`, `INT64`,
`INT32`, `NUMERIC`, `FLOAT`, `DATE`, `TIMESTAMP` need no cast — omit it.

## Filters

- String filter values must match the data exactly, case included. If the TML gives
  `sample_values`, copy a literal verbatim; if not, use `ILIKE`.
- Null checks: `IS NULL` / `IS NOT NULL`, never `= NULL`.
- Filter early — put `WHERE` inside CTEs rather than wrapping the final SELECT.

## When you can't answer it

If the question needs something SpotQL can't express (true rolling N-period frames,
`PERCENTILE_CONT`, set operations, `NTILE`, a column the Model doesn't have, or a
non-CDW Model), don't force a wrong query. State plainly what's not supported and why.
