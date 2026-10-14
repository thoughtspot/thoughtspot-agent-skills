# Learn AgentQL: a guided pathway

A hands-on course in writing AgentQL, what the two APIs do, and what SQL ThoughtSpot actually
sends to the warehouse. You run it live: the agent sets each exercise, runs the real
`ts agentql` calls, and walks through what came back. Read this when someone asks to *learn*
AgentQL ("teach me AgentQL", "how does AgentQL work", "I need to demo this"). Not for
answering a business question; that is the normal flow in `SKILL.md`.

**Audience.** Built first for **SEs and other technical field staff** who need to explain and
demo the capability. It works for anyone comfortable reading SQL.

**Status.** Modules 0–2 are written and live-verified. Modules 3–7 are outlined at the end
and not written yet.

---

## The Model: `(Sample) Retail - Apparel`

Every lesson runs on this Model because it **ships on every cluster**. It is a three-table
star schema (`FACT_RETAPP_SALES` joined to `DIM_RETAPP_PRODUCTS` and `DIM_RETAPP_STORES`):

| Column | Kind | Notes |
|---|---|---|
| `sales`, `quantity purchased` | MEASURE (SUM) | raw measures |
| `region`, `state`, `city`, `store`, `zip code`, … | ATTRIBUTE | from the stores dimension |
| `item type`, `product`, `SKU` | ATTRIBUTE | from the products dimension |
| `date` | ATTRIBUTE, **formula** | `add_days(RECORDDATE, diff_days(today(), 04/30/2020))`: rolls the 2020 data forward so it always ends today |

**Find it by exact name and author `system`.** A cluster usually also carries user copies with
near-identical names ("(Sample) Retail - Apparel - <initials>", "Copy of …"). Do not assume a GUID.

```bash
ts metadata search --profile {profile} --subtype WORKSHEET --name "(Sample) Retail - Apparel"
# keep the hit whose metadata_header.name matches exactly AND authorName == "system"
```

On the SE demo cluster it is `cd252e5c-b552-49a8-821d-3eadaa049cca`. Other clusters may
differ, which is why the search is the method. If there is no system-authored copy, ask
which Model to use rather than picking a near-match.

**Because `date` rolls forward, totals bucketed by date change from day to day.** Never tell
a learner to expect a specific dated number. Totals over all time are stable.

---

## How to run a lesson

Every lesson follows the same six steps. Do not skip **Predict**: guessing the SQL before
seeing it is what turns "ThoughtSpot generates SQL" into a model the learner can reason with.

1. **Question.** State the business question in plain English.
2. **Write.** In early lessons, show the AgentQL. From 2.3 on, ask the learner to write it
   first, then compare it with the version below.
3. **Predict.** Ask what the warehouse SQL will contain. Which tables? Any joins? What will
   happen to the measure? Wait for the answer.
4. **`generate-sql`.** Run it and show `executable_sql`. Walk through the lesson's
   **Point out** items, comparing them with the prediction.
5. **`fetch-data`.** Run it, render the rows as a table, and note the `columns[].type` values.
6. **Break it.** Run the lesson's variant, show what changes and why, and name the rule.

```bash
ts agentql generate-sql --profile {profile} -m {model_guid} '<agentql>'
ts agentql fetch-data  --profile {profile} -m {model_guid} '<agentql>'
```

Show every artifact: the AgentQL, the warehouse SQL, the rows, and the raw JSON when it
teaches something (as in Module 1). At the end of each module, ask its **Check yourself**
questions, then offer **Try it on your Model**: one short exercise on a Model the learner
chose, so the lesson carries over to their own data.

**If a result does not match this page,** say so plainly and move on. Don't explain it away.
The product changes between releases. The **Guarded by** ids name the retest-suite cases that
check each lesson's claims (`tools/agentql-retest`, `--suite lessons`). A failing case means
the lesson needs updating, not the learner.

---

## Module 0 — Why AgentQL exists (concept, ~10 min)

Read [`architecture.md`](architecture.md) § "The core principle" first. Teach three ideas
before writing any query:

1. **ThoughtSpot never executes AgentQL.** It is a **compile** step: AgentQL in, warehouse
   SQL out, and the warehouse runs the SQL. `generate-sql` stops after compiling;
   `fetch-data` compiles, sends the SQL to the warehouse and returns the rows.
2. **You query the Model, not the tables.** `FROM` names one Model, and every column is a
   business name (`"t1"."sales"`). The Model knows the physical tables, the joins, the
   formulas and the security rules. AgentQL reaches the data only through it.
3. **That is the point.** Joins, row-level security and formula logic come from the Model,
   so two people asking the same question get the same answer. A hand-written SQL query
   gives no such guarantee. See `architecture.md` § "What the semantic layer guarantees".

**Check yourself.** Where does the query run? What does AgentQL let you leave out that raw
SQL needs, and why does leaving it out make the answer more trustworthy rather than less?

---

## Module 1 — The two APIs (~20 min)

### 1.1 Same query, both calls

**Question.** Total sales.

```sql
SELECT SUM("t1"."sales") AS "Total Sales"
FROM "(Sample) Retail - Apparel" AS "t1"
```

**Point out.**
- `generate-sql` returns `status`, `executable_sql` and `errors[]`. Nothing ran on the
  warehouse: it is cheap and safe to call repeatedly while drafting.
- `fetch-data` returns `status`, `columns[]` (with types) and `rows[]`. This call does reach
  the warehouse.
- Both return JSON and exit 0 even when the query is rejected, so callers branch on
  `status`, not on the exit code.

**Guarded by:** `ctl_ap_total`.

### 1.2 A rejected query is a structured error

**Break it.** Two common mistakes:

```sql
SELECT * FROM "(Sample) Retail - Apparel" AS "t1"
SELECT SUM("t1"."revenue") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Point out.** `status` is a specific code (`SELECT_STAR`, `COLUMN_NOT_FOUND`), and
`errors[].message` says what to change. Each code maps to a rule in
[`agentql-rules.md`](agentql-rules.md). The fix is a rule, never a blind retry.

**Guarded by:** `l1_select_star_rejected`, `l1_unknown_column`.

### 1.3 `generate-sql` SUCCESS is not proof the query runs

```sql
SELECT BITAND("t1"."quantity purchased", 1) AS x FROM "(Sample) Retail - Apparel" AS "t1" LIMIT 3
```

**Predict.** Will this compile? Will it run?

**Point out.** It compiles (`SUCCESS`, emitting `&`), then `fetch-data` fails in the
warehouse (`QUERY_EXECUTION_FAILED`, *Unknown function "&"*). Some constructs compile to SQL
the warehouse rejects, so a query is not proven until `fetch-data` returns rows.
`limitations.md` lists which ones.

**Guarded by:** `l1_compiles_then_fails`.

### 1.4 Reading `fetch-data`: types, and dates as numbers

```sql
SELECT "t1"."date" AS d, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."date" ORDER BY "t1"."date" DESC LIMIT 1
```

**Point out.** The date comes back as an `INT64` number of seconds since 1970-01-01 UTC, not
as a date string, so the caller has to convert it (see [`integration.md`](integration.md)).
The latest date is today, because the formula rolls the data forward.

**Guarded by:** `l1_dates_are_epoch_seconds`.

**Check yourself.** Which call would you use to check a query in a loop while drafting it,
and why? A query returns `SUCCESS` from `generate-sql`: what can and can't you conclude?

---

## Module 2 — First queries: reading the SQL ThoughtSpot writes (~40 min)

### 2.1 A total: null handling, the row cap, one table

```sql
SELECT SUM("t1"."sales") AS s, SUM("t1"."quantity purchased") AS q
FROM "(Sample) Retail - Apparel" AS "t1"
```

**Predict.** How many tables will the SQL touch?

**Point out.**
- **One table.** The query needs only the fact table, so ThoughtSpot leaves the dimensions
  out (the Model has `join_progressive` on).
- `CASE WHEN sum(x) IS NOT NULL THEN sum(x) ELSE 0 END`: an empty total comes back as 0,
  not NULL.
- `LIMIT 100000` is added to every statement. That is the row cap (see `limitations.md`).
- Physical names (`"RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES"."SALES"`) replace the
  business names.

**Guarded by:** `l2_total_touches_fact_only`.

### 2.2 Grouping by a dimension: the join is written for you

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."region"
```

**Point out.** A `JOIN` to `DIM_RETAPP_STORES` on `STOREID` appears, and only that one:
`DIM_RETAPP_PRODUCTS` is not needed, so it is not joined. The learner never writes a join.
The Model's join definitions do. The region totals add up to 2.1's total.

**Guarded by:** `l2_group_by_joins_one_dim`.

### 2.3 Two dimensions, two joins

**Learner writes:** sales by item type and region.

```sql
SELECT "t1"."item type" AS it, "t1"."region" AS r, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."item type", "t1"."region"
```

**Point out.** Both dimensions are now joined, from the fact table outward. That is the star
schema the Model defines. Ask the learner to sketch it from the SQL alone.

**Guarded by:** `l2_two_dims_two_joins`.

### 2.4 Top N: `ORDER BY` and `LIMIT`

**Learner writes:** the three best-selling item types.

```sql
SELECT "t1"."item type" AS it, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."item type" ORDER BY s DESC LIMIT 3
```

**Point out.** `ORDER BY` can use the output alias. ThoughtSpot adds `NULLS LAST`, and the
learner's `LIMIT 3` replaces the default cap.

**Guarded by:** `l2_top_n`.

### 2.5 A Model formula compiles into the SQL

```sql
SELECT YEAR("t1"."date") AS y, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY YEAR("t1"."date")
```

**Predict.** `date` is a formula column. What will the warehouse see?

**Point out.** The formula is **inlined**:
`DATEADD(day, DATEDIFF(day, DATE('2020-04-30', …), CURRENT_DATE()), "RECORDDATE")`. The
learner wrote `"t1"."date"`, and the Model supplied the logic.

**Break it.**

```sql
SELECT CURRENT_DATE AS d, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

The query is rejected (`SQL_DATE_FUNCTION`). The lesson: **"today" logic lives in the
Model, not in the query.** The Model's own formula used `CURRENT_DATE()` above, and AgentQL
may not. That is deliberate: a relative date defined once in the Model means the same thing
to everyone.

**Guarded by:** `l2_formula_compiles_inline`, `l2_current_date_rejected`.

### 2.6 Filters and counting

**Learner writes:** sales in the West region.

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE "t1"."region" = 'west'
```

**Point out.** It is written in lower case, yet it matches `West`, because the SQL is
`WHERE LOWER("REGION") = 'west'`. String `=` and `IN` are **case-insensitive**, and there is
no case-sensitive form. Filtering on a dimension also brings in its join.

**Counting.** Distinct stores:

```sql
SELECT COUNT(DISTINCT "t1"."store") AS n FROM "(Sample) Retail - Apparel" AS "t1"
```

**Break it.** `COUNT(*)` is rejected (`COUNT_STAR`). Always count a named column.

**Guarded by:** `l2_filter_case_insensitive`, `l2_count_distinct`, `l2_count_star_rejected`.

### 2.7 The parser is lenient. Don't rely on it

Two statements that look wrong and still work:

```sql
SELECT SUM("t1"."Sales") AS s FROM "(sample) retail - apparel" AS "t1"          -- wrong case
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"  -- no GROUP BY
```

**Point out.** Identifiers are matched case-insensitively, and a missing `GROUP BY` is
filled in from the non-aggregated columns. Both give the correct answer. Write them properly
anyway: copy the TML spelling, and always write the `GROUP BY`. A lenient parse is not a
contract, and a reader (or another engine) should not have to guess.

**Guarded by:** `l2_identifiers_case_insensitive`, `l2_implicit_group_by`.

### 2.8 A bare measure is not aggregated

```sql
SELECT "t1"."region" AS r, "t1"."sales" AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Predict.** `sales` is defined in the Model as a SUM measure. Will this return five rows?

**Point out.** No. It returns every sales row (up to the 100,000-row cap), each tagged with
its region, and the SQL has no `sum(`. The Model's default aggregation applies in Search, not
in AgentQL. **Aggregate raw measures yourself.** This is the most common beginner mistake,
and it fails silently.

**Guarded by:** `l2_bare_measure_row_level`.

**Check yourself.** Without running anything: which tables will a query for "quantity by
state" touch? What does the query in 2.8 do, and how would you spot it from the result alone?
Why does `CURRENT_DATE` fail when the Model's own formula uses it?

**Try it on your Model.** Pick a Model the learner works with. Write one grouped query, then
predict its joins from the Model's TML (`ts tml export … --parse`, `model_tables[].joins`)
before running `generate-sql`.

---

## Modules 3–7 (outlined, not yet written)

| # | Module | Will teach | Draws on |
|---|---|---|---|
| 3 | What the semantic layer does for you | raw measures vs aggregate-formula measures (`SUM` vs `AGG`), `NESTED_AGGREGATE_NOT_SUPPORTED`, `join_progressive` and its absence, row-level security applied without being written | [`agentql-rules.md`](agentql-rules.md) § Aggregation, `architecture.md` |
| 4 | Dates and functions | date literals, `TO_DATE`, `YEAR`/`MONTH_NUMBER`/`DAY_IN_YEAR_NUMBER`, and which functions compile but fail | [`udf-reference.md`](udf-reference.md), `limitations.md` |
| 5 | Advanced shapes | CTEs, window functions (`RANK`, `LAG`, framed `SUM`), set operations, top N per group with `ROW_NUMBER` in a CTE | [`patterns.md`](patterns.md) |
| 6 | Trust, but verify | queries that return `SUCCESS` with the wrong number (`QUALIFY`, `FILTER (WHERE …)`), and catching them with a control query | [`limitations.md`](limitations.md), the retest suite's controls |
| 7 | Building on it | the two calls inside an agent, accuracy benchmarking, regression testing | [`use-cases.md`](use-cases.md), [`integration.md`](integration.md) |

**Tracks.** SE / field: 0–3 and 6. Developer integrating: 0–5 and 7. QA / power user: all.

**Module 3 needs an aggregate-formula measure,** and the sample Model has none (its two
measures are raw). Either add a scratch formula to a copy, or use a learner's own Model.
Decide that before writing the module.
