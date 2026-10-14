# AgentQL rules — what makes a statement valid

AgentQL is a **restricted PostgreSQL dialect** with ThoughtSpot extensions. It runs against
a single ThoughtSpot **Model** (which maps to one or more warehouse tables behind the
scenes). Read this before writing any AgentQL. Distilled from the agent-expressibility-eval
AgentQL rules (system_prompt_v8) and verified live on champ-staging 2026-06-25.

> Source-of-truth note: these are constraints of the AgentQL engine, not of this skill.
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

## Aggregation — two kinds of measure (this distinction matters)

A Model has two kinds of numeric column, and they are aggregated **differently**. Tell them
apart from the TML (`ts tml export`): look at each MEASURE column's `formula_id` / formula
expression.

- **Raw measure** — maps to a plain numeric warehouse fact, no aggregating formula (e.g.
  `Amount`, `Quantity`). **Apply a real aggregate yourself:** `SUM` (the default for
  additive facts), `AVG`, `MIN`, `MAX`. `COUNT` must name a column — **`COUNT(*)` /
  `COUNT(1)` are rejected**; use `COUNT("t1"."Order Id")`.

  ```sql
  SUM("t1"."Amount") AS "Total Sales"
  ```

- **Aggregate-formula column** — a formula column whose expression **already contains an
  aggregate** (`sum(...)`, `count(...)`, `group_aggregate(...)`, `safe_divide(sum(...),
  sum(...))`, `cumulative_sum(...)`, `sum(last_value(...))`, etc.). **Wrap it in `AGG()`**
  so it is not re-aggregated. **Never `SUM` it** — `SUM("aggregate formula")` fails with
  `NESTED_AGGREGATE_NOT_SUPPORTED`. `AGG()`'s argument must be a bare column reference, not
  an expression.

  ```sql
  AGG("t1"."# Employees")          -- formula is count(...); AGG, never SUM
  AGG("t1"."Avg Revenue Per Unit") -- formula is safe_divide(sum,sum); AGG, never SUM
  ```

  Verified live (nebula-aggregate-aware, 2026-07-13): `AGG()` returns correct results;
  `SUM()` on the same column errors `NESTED_AGGREGATE`. This holds even when an additive
  aggregate *wraps* a window — `sum(last_value(...))`, `sum(group_sum(...))` — because the
  **outermost** op is additive.

- **Semi-additive measure** — an aggregate-formula whose **outermost** call is
  `last_value`/`first_value` (the snapshot form `last_value(sum(col), query_groups(),
  {date})`). This one **inverts** the rule above: **wrap it in `SUM(...)`, never `AGG()`**.
  `AGG()` fails with `NON_CONVERTIBLE_FUNCTION` ("Non standard sql function QueryGroups") —
  the serializer can't emit `query_groups()` natively. `SUM(...)` forces a per-group
  materialisation that resolves `query_groups()` and passes the already-collapsed snapshot
  value through unchanged (it is an identity over one value per query group).

  ```sql
  SUM("t1"."Inventory Balance")    -- formula is last_value(sum(...)); SUM, never AGG
  ```

  Verified live (nebula-aggregate-aware, 2026-07-13) at grand-total, grouped-by-dimension,
  and monthly grain — every result matched Snowflake ground truth (`sum(filled_inventory)`
  at the latest balance date). The trigger is the **outermost** op only: `sum(last_value(...))`
  is a normal aggregate-formula (`AGG`, previous bullet), not this case. `ts agentql
  classify-columns` detects this and returns `kind: semiadditive_measure`, `wrapper: SUM`
  — follow the `wrapper` field; don't re-derive it by eye. (Earlier docs wrongly showed
  `AGG("Inventory Balance")` as correct — that was never verified against a live semi-additive
  measure and is wrong; corrected here.)

  > Quick test if unsure which kind a column is: run `ts agentql classify-columns` (it parses
  > the outer op for you). Or compile a probe: `ts agentql generate-sql 'SELECT
  > AGG("t1"."<col>") FROM "<Model>" AS "t1"'` — `NESTED_AGGREGATE` means raw (use `SUM`),
  > `NON_CONVERTIBLE_FUNCTION` means semi-additive (use `SUM`), success means aggregate-formula
  > (use `AGG`).

- **Attributes go in `GROUP BY`.** Every non-aggregate column in the SELECT must appear in
  `GROUP BY`. Every CTE that contains an aggregate must have its own `GROUP BY` (the main
  SELECT is the only exception — it may aggregate to a single global row without one).
- Statistical aggregates: `MEDIAN` works directly — scalar and grouped. `STDDEV_SAMP`/
  `STDDEV_POP` and `VAR_SAMP`/`VAR_POP` **do not compile against a Model column in either
  context** (`UNSUPPORTED_AGGREGATE` — regression since jul.26.mt, still present on
  26.9.0.cl, [SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935)). Two
  forms work: materialise the aggregate in a CTE and take the statistic over the CTE
  column in the outer SELECT, or the window form `STDDEV_SAMP(SUM(x)) OVER ()`
  (`patterns.md` § Statistics). Always write the explicit `_SAMP`/`_POP` suffix.

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

- **Arithmetic between an aggregate and a numeric literal** (`SUM("x") * 100`, `/ 100.0`)
  works on current builds — verified champ-staging 2026-06-25. (It silently returned zeros
  on older builds — see `limitations.md`; if you ever see all-zero results, that's the tell.)
  For division still wrap the denominator in `NULLIF(…, 0)` to avoid divide-by-zero.
- **No `SELECT *`** — enumerate columns. Inside a CTE it is hard-rejected.
- **No subqueries anywhere** — no `FROM (SELECT …)`, no `WHERE col IN (SELECT …)`, no
  `WHERE EXISTS (…)`, no scalar subselects. Use named CTEs and JOINs instead. **Beware:**
  `IN (SELECT …)` passes `generate-sql` and only fails at `fetch-data`
  ([SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936)) — a compile
  SUCCESS is not evidence it works. For a membership filter use the rewrite in
  `patterns.md` § Semi-join via CTE — and dedupe the key CTE with `GROUP BY <key>`,
  or the join fans out and aggregates silently double-count.
- **Set operations** — `UNION ALL`, `UNION`, `EXCEPT`, `EXCEPT ALL`, `INTERSECT`,
  `INTERSECT ALL` **work at the top level** of the query ([SCAL-313049](https://thoughtspot.atlassian.net/browse/SCAL-313049),
  verified 2026-07-07) and **inside a user-defined CTE** — including branches with
  aggregate measures (fixed by jul.26.mt; on older builds an aggregated branch errors
  `QUERY_GEN_ERROR`). **`ORDER BY` and `LIMIT` on the combined result also work**
  (verified on jul.26.mt and 26.9.0.cl; on older builds ORDER BY was silently dropped and
  LIMIT misplaced into the first branch — check the generated SQL if the build is older).
  **Aggregating *over* a set-operation CTE fails** (`10000 Failed to transform QuerySpec:
  null`) — put the aggregate inside each branch instead. Each branch must have the same number of columns with compatible
  types — but type compatibility is **not checked at compile time**: a mismatch (e.g.
  VARCHAR vs DOUBLE at the same position) passes `generate-sql` and fails at `fetch-data`.
  Operator precedence follows the SQL standard (INTERSECT binds tighter than UNION/EXCEPT).
  Parentheses for explicit grouping are supported. See `limitations.md` for details.
- **No self-join of a CTE** (`[SELF_JOIN]`) and **no non-equi `JOIN … ON`** (only `=`
  allowed; use `CROSS JOIN` + `WHERE` for ranges). Between two CTEs a non-equi join
  reports the misleading `CTE table alias not found` instead of `NON_EQUI_JOIN`.
- **No recursive CTEs** (`WITH RECURSIVE`), **no table functions** (`FLATTEN`, `UNNEST`,
  `GENERATOR`), **no `GROUP BY 1` ordinals**, **no `col NOT IN (...)`**
  (rewrite as `!=` chained with `AND` — re-verified 2026-10-14, it fails `Unsupported
  type`). `LENGTH()` works (verified 2026-07-29 — earlier rules wrongly forbade it).
- **No forbidden date functions**: `DATE_TRUNC`, `TRUNC(date, part)`, `NOW()`,
  `CURRENT_DATE`, `AGE`, `INTERVAL` arithmetic. Use the AgentQL UDFs in `udf-reference.md`.
  A date literal in a filter is fine (`d >= '2025-01-01'`, or `TO_DATE('2025-01-01')`).
- **No regex** — `REGEXP_LIKE`, `~`, `REGEXP_SUBSTR`, `REGEXP_REPLACE` all fail (some only
  at `fetch-data`). Use `LIKE` / `ILIKE`.
- **Never rely on more than 100,000 rows.** Every statement is capped: `LIMIT 100000` is
  appended, and a larger explicit `LIMIT` is silently rewritten down to 100,000. For a bulk
  extract, page with `ORDER BY … LIMIT n OFFSET m` (works on 26.9.0.cl) or filter into
  slices.
- **Every CTE must reference a real column** — a CTE selecting only literals errors with
  `QueryTable has no owner tables`.

## CTEs

- Allowed and useful for multi-step logic. Each CTE sources from the one Model. Joining
  two or more model-derived CTEs in the main SELECT, and a CTE selecting `FROM` an earlier
  CTE (chained CTEs), **both work on current builds** (were broken on older ones — see
  `limitations.md`).
- **Outer joins between CTEs work** — `LEFT OUTER JOIN`, `RIGHT OUTER JOIN` and
  `FULL OUTER JOIN` (equi-`ON` only) compile verbatim into the warehouse SQL and execute
  correctly (verified live, nebula-spotQL 2026-07-10). The Model's own join types don't
  constrain this: a query can outer-join CTE results even where the Model defines an
  inner join.
- **An attribute-only CTE compiles to a dimension-only scan** — the fact table (and the
  Model's inner join to it) enters the generated SQL only when a measure requires it. So
  `SELECT "t1"."Customer Name" … GROUP BY` returns *all* members, including those with no
  fact rows. Combined with the outer-join rule above, this expresses "members with no
  activity" without any Model change — see `patterns.md` § Dimension-anchored anti-join.
- **Set operations inside a CTE work**, including branches with `SUM(col) … GROUP BY`
  (fixed by jul.26.mt). An outer aggregation *over* that CTE does not — see the
  set-operations caveats above.
- `SELECT` may appear only at the start of a CTE definition or the main query.
- Still rejected: **self-joining** a CTE (`SELF_JOIN`) and **non-equi** `JOIN … ON`
  (only `=` allowed) — see `limitations.md`.

## CAST

Only `CAST` a `VARCHAR`/`TEXT` column to numeric/date. Columns already `DOUBLE`, `INT64`,
`INT32`, `NUMERIC`, `FLOAT`, `DATE`, `TIMESTAMP` need no cast — omit it.

## Filters

- **String `=`, `<>` and `IN` are case-insensitive.** ThoughtSpot compiles them to
  `LOWER(col) = 'lowercased literal'` (✓ live 2026-10-14: `'Jim Halpert'`, `'jim halpert'`
  and `'JIM HALPERT'` return the same rows), matching ThoughtSpot's own formula semantics.
  Spelling still has to match; case does not. There is no case-sensitive equality. If the
  TML gives `sample_values`, copy a literal from it; for partial matches use `LIKE`/`ILIKE`.
- Null checks: `IS NULL` / `IS NOT NULL`, never `= NULL`.
- Filter early — put `WHERE` inside CTEs rather than wrapping the final SELECT.
- **Aggregate conditions go in `HAVING`, never `WHERE`.** An aggregate in `WHERE`
  (e.g. `WHERE SUM(x) > 0`) does not error — it is silently reinterpreted as `HAVING`
  (verified live 2026-07-07). Write the intended clause explicitly.

## When you can't answer it

If the question needs something AgentQL can't express (non-`MEDIAN` percentiles, direct
`STDDEV`/`VAR` on a Model column — the CTE and window statistics forms work — subqueries,
`QUALIFY`, `FILTER (WHERE …)`, `ROLLUP`/`CUBE`, regex, a column the Model doesn't have, or a
non-CDW Model), don't force a wrong query. State plainly what's not supported and why.
The full, current list (with what's been *fixed* — e.g. set operations incl. ORDER
BY/LIMIT on the combined result, `NTILE`, `LAG`/`LEAD` offsets, `ROWS BETWEEN` frames,
`OFFSET`, multi-CTE joins and literal arithmetic now work) is in `limitations.md`.
