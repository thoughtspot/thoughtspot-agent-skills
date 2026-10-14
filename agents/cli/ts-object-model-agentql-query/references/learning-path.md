# Learn AgentQL: a guided pathway

A hands-on course in writing AgentQL, what the two APIs do, and what SQL ThoughtSpot actually
sends to the warehouse. You run it live: the agent sets each exercise, runs the real
`ts agentql` calls, and walks through what came back. Read this when someone asks to *learn*
AgentQL ("teach me AgentQL", "how does AgentQL work", "I need to demo this"). Not for
answering a business question; that is the normal flow in `SKILL.md`.

**Audience.** Built first for **SEs and other technical field staff** who need to explain and
demo the capability. It works for anyone comfortable reading SQL.

**Status.** All eight modules (0–7) are written and live-verified on 26.9.0.cl PROD. Every
behavioural claim is checked by a retest case, named on the lesson's **Guarded by** line.

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

The sample's tables are on `Demo Connection`, a cloud warehouse on ThoughtSpot Cloud
clusters. If `generate-sql` answers *"This API only supports external cloud data
warehouses"*, this cluster's sample is not on one (AgentQL needs one). Say so, and ask the
learner for a Model on Snowflake, Databricks or BigQuery. The lessons still apply, but the
numbers and table names will differ.

**Because `date` rolls forward, totals bucketed by date change from day to day.** Never tell
a learner to expect a specific dated number. Totals over all time are stable.

---

## How to run a lesson

Every lesson follows the same six steps. **Show the AgentQL. Don't ask the learner to
write it.** The lesson's query is ready to run, so nobody loses time to syntax errors, and
the learning is in what ThoughtSpot does with it. A learner who wants practice can write
their own instead: run theirs, then compare it with the lesson's.

1. **Question.** State the business question in plain English.
2. **Show the query.** Present the lesson's AgentQL, with any placeholders filled in.
3. **Predict, briefly.** Ask one short question in the same message as the query, such
   as *"Before I run it: which tables will this touch?"*. Use the lesson's **Predict** line
   if it has one. Then wait. Any answer is fine, and so is a plain "run it": run it then,
   without pressing for a guess. The prediction is useful, but it is optional, not a quiz.
4. **`generate-sql`.** Run it and show `executable_sql`. Walk through the lesson's
   **Point out** items, comparing them with the prediction if there was one.
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

**Question:** sales by item type and region.

```sql
SELECT "t1"."item type" AS it, "t1"."region" AS r, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."item type", "t1"."region"
```

**Point out.** Both dimensions are now joined, from the fact table outward. That is the star
schema the Model defines. Ask the learner to sketch it from the SQL alone.

**Guarded by:** `l2_two_dims_two_joins`.

### 2.4 Top N: `ORDER BY` and `LIMIT`

**Question:** the three best-selling item types.

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

**Question:** sales in the West region.

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

**Try it on your Model.** Pick a Model the learner works with. Write one grouped query for it
(you write it, or the learner does if they want to), then
predict its joins from the Model's TML (`ts tml export … --parse`, `model_tables[].joins`)
before running `generate-sql`.

---

## Module 3 — What the semantic layer does for you (~30 min)

### 3.1 A ratio of two measures, divided safely

**Question:** average selling price per item type (sales ÷ quantity).

```sql
SELECT "t1"."item type" AS it, SUM("t1"."sales") / SUM("t1"."quantity purchased") AS avg_price
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."item type"
```

**Point out.** The divisor is wrapped in `NULLIF(…, 0.0)`, so a zero quantity gives NULL
rather than a division error. Note **ratio of sums, not sum of ratios**: each ratio is
computed from the group's totals, which is the correct average price.

**Guarded by:** `l3_ratio_safe_division`.

### 3.2 `AVG` averages fact rows

```sql
SELECT "t1"."region" AS r, AVG("t1"."sales") AS a, SUM("t1"."sales") AS s, COUNT("t1"."sales") AS n
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."region"
```

**Predict.** Is `a` the average sale per *store* in the region, or per *row*?

**Point out.** Per row: `a = s / n`, where `n` counts fact rows. "Average sales per store"
needs a two-step query (5.1). This is the most common reason an `AVG` looks wrong.

**Guarded by:** `l3_avg_is_row_level`.

### 3.3 Which tables a query reads

```sql
SELECT "t1"."item type" AS it FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type"
SELECT "t1"."item type" AS it, "t1"."region" AS r FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."item type", "t1"."region"
```

**Predict.** Will either query touch the sales table?

**Point out.**
- **One dimension:** only `DIM_RETAPP_PRODUCTS` is read. The Model has `join_progressive`
  on, so tables a query does not need are left out, as in 2.1.
- **Two dimensions from different tables:** the SQL joins **through the fact table**,
  because that is the only path between products and stores. So the result shows only the
  combinations that have sales, not every possible pairing. Here all 75 exist. On sparser
  data, a "list every product and region" query silently drops pairings with no sales.
- On a Model **without** `join_progressive`, *every* query joins every table, even a
  one-column dimension list, so results are filtered by the fact table. See
  `limitations.md` ⚠️ "Any dimension-only query on a Model without `join_progressive`".

**Guarded by:** `l3_dim_only_one_table`, `l3_two_dims_via_fact`.

### 3.4 Formula measures: `AGG`, not `SUM` (on a Model the learner chooses)

The sample Model's measures are all raw, so this lesson runs on **a Model the learner
picks**: one they work with, on a cloud warehouse, that has formula measures. On the SE demo
cluster, `Dunder Mifflin` works. Everyone else names their own.

**Set it up.** Do this yourself, in front of the learner. The classification is itself part
of the lesson.

1. **Classify the Model's columns:**

   ```bash
   ts agentql classify-columns --model {guid} --profile {profile}
   ```

   Each column comes back with a `kind` and a `wrapper`. Show the learner the measures:
   `raw_measure` (wrapper `SUM`, or the aggregation it names), `aggregate_measure`
   (wrapper **`AGG`**), and `semiadditive_measure` (wrapper `SUM`, the exception below).
   This is how you tell, for any Model, which wrapper a measure takes.
2. **No `aggregate_measure`?** Say so: this Model has no formula measures. Offer another
   Model, or skip the lesson. Do not invent one.
3. **Pick the pieces:**
   - **one `aggregate_measure`.** Prefer a simple one; read its formula with
     `ts tml export {guid} --profile {profile} --parse` (`model.formulas[].expr`).
   - **one `attribute` with a handful of values** (a country, region, category or type).
     Check with `COUNT(DISTINCT …)` if unsure, and keep it to about 20 or fewer.
   - **a control, if there is one.** When the formula is a plain sum of one column that the
     Model also exposes as a `raw_measure`, that raw measure is the control.
4. **Write the question from those names.** For example: *"What is `Sales - Actual (fx)` by
   `Ship Country`?"*

**Show the query**, filled in with the picked names. **Predict:** `SUM` or `AGG`, and what
will the SQL contain?

```sql
SELECT "t1"."<attribute>" AS a, AGG("t1"."<formula measure>") AS m
FROM "<Model>" AS "t1"
GROUP BY "t1"."<attribute>"
```

**Point out.**
- **`AGG()` means "use the Model's formula as defined."** The formula already aggregates,
  so the compiled SQL carries the formula's own aggregation once, not one you add on top.
- **Read the SQL to see how much the formula does.** A formula built on `group_aggregate`
  (the Dunder Mifflin sales measures are) compiles to a CTE at the formula's own level of
  detail, joined back to the query with a `LEFT OUTER JOIN`. That logic is defined once in
  the Model, and nobody has to write it again in a query.
- **If there is a control,** run `SUM` of the raw column beside it: the two agree.

**Break it.** Three variants, run one at a time:

| Variant | Result | Why |
|---|---|---|
| `SUM("t1"."<formula measure>")` | rejected: `NESTED_AGGREGATE_NOT_SUPPORTED` | the formula already aggregates, so `SUM` would aggregate it twice |
| `AGG("t1"."<raw measure>")` | rejected: `QUERY_GEN_ERROR`, *"All non-constant columns should be grouped by or aggregated"* | a raw column has no aggregation for `AGG` to use. Try it on the sample Model: `AGG("t1"."sales")` |
| `"t1"."<formula measure>"`, bare | **same SQL and rows as `AGG()`** | the aggregation lives in the formula. Contrast 2.8, where a bare *raw* measure returned every row. Write `AGG()` anyway, so the reader can see it |

**The exception: semi-additive measures.** A formula whose outermost call is
`last_value` / `first_value` (a balance or snapshot measure) takes **`SUM`**, and `AGG`
fails on it. `classify-columns` reports these as `semiadditive_measure` with wrapper
`SUM`. Mention it, and follow `wrapper` rather than memorising the rule. Details are in
[`agentql-rules.md`](agentql-rules.md) § Aggregation.

**Guarded by:** `sum_on_agg_formula`, `agg_on_agg_formula`, `agg_formula_equals_raw_sum`, `agg_formula_bare_like_agg`, `l3_agg_on_raw_measure_rejected`.

All but the last are limitations-suite cases on Dunder Mifflin. On another Model, the
lesson's own runs are the check.

### 3.5 Security you never write

No query here mentions security, and none needs to. If the Model has **row-level security**,
the compiled SQL includes the user's filter automatically, so two users running the same
AgentQL can get different rows, each correct for them. Column-level security hides columns
the same way. Read [`architecture.md`](architecture.md) § "What the semantic layer
guarantees". This is the strongest argument for AgentQL over raw SQL, and the sample Model
has no RLS to demonstrate it.

**Check yourself.** Why is `SUM(sales) / SUM(quantity)` the right average price, and
`AVG(sales / quantity)` not? A dimension-only query lists fewer products than the product
table holds: name two reasons. Given any Model, how do you find out whether a measure takes
`SUM` or `AGG`, without reading its formula?

---

## Module 4 — Dates and functions (~30 min)

### 4.1 Date parts with the extraction functions

```sql
SELECT YEAR_NUMBER("t1"."date") AS y, QUARTER_NUMBER("t1"."date") AS qn, MONTH_NUMBER("t1"."date") AS m,
       SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY YEAR_NUMBER("t1"."date"), QUARTER_NUMBER("t1"."date"), MONTH_NUMBER("t1"."date")
```

Also try `DAY_NAME("t1"."date")` (returns `monday` … `sunday`) and
`DAY_IN_WEEK_NUMBER("t1"."date")` (1 = Monday … 7 = Sunday).

**Point out.** AgentQL has its own date functions (catalogue in
[`udf-reference.md`](udf-reference.md)). Use them instead of guessing the warehouse's
spellings. The groups add up to the grand total.

**Guarded by:** `l4_date_parts`, `l4_day_name`, `l4_day_in_week`.

### 4.2 Relative dates: the period functions

**Question:** sales this year, and sales in the last 30 days.

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE DIFF_YEAR(START_OF_CURRENT_YEAR(), "t1"."date") = 0

SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE DIFF_DAY(START_OF_CURRENT_DAY(), "t1"."date") BETWEEN 1 AND 30
```

**Point out.** These compile to `CURRENT_DATE()` in the warehouse SQL. That is the function
2.5 showed you may not write yourself: AgentQL allows "today" only through these named
period functions, which are defined once and behave the same for everyone. "This year"
matches the current-year row of a `YEAR_NUMBER` grouping. `BETWEEN 1 AND 30` means the 30
complete days before today, excluding today.

**Guarded by:** `l4_this_year_relative`, `l4_last_30_days`.

### 4.3 A date literal in `WHERE`

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE "t1"."date" >= '<this year>-01-01'
```

**Point out.** A plain `'YYYY-MM-DD'` literal works in `WHERE`, and gives the same total as
4.2's "this year". (Module 6 shows the same comparison going wrong inside `SUM(CASE …)`.)

**Break it.** `DATE_TRUNC('month', "t1"."date")` compiles, then fails in the warehouse. Use
`YEAR_NUMBER` / `MONTH_NUMBER` instead, as in 4.1.

**Guarded by:** `l4_date_literal_filter`, `l4_date_trunc_fails`.

### 4.4 String functions

```sql
SELECT UPPER("t1"."region") AS u, LENGTH("t1"."region") AS l,
       CONCAT("t1"."region", '-', "t1"."state") AS c, SUBSTR("t1"."state", 1, 3) AS sub
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY UPPER("t1"."region"), LENGTH("t1"."region"), CONCAT("t1"."region", '-', "t1"."state"),
         SUBSTR("t1"."state", 1, 3)
```

**Point out.** Familiar SQL string functions work. A computed column in `SELECT` must also
be grouped: repeat the expression, as above, or name its output alias (`GROUP BY u`). A
position (`GROUP BY 1`) is rejected. Regex functions do not work (`limitations.md`).

**Guarded by:** `l4_string_functions`, `l4_group_by_alias`, `l4_group_by_ordinal_rejected`.

### 4.5 `CASE` to bucket values

**Question:** count and total of sales rows, bucketed small / medium / large.

```sql
SELECT CASE WHEN "t1"."sales" >= 1000 THEN 'large' WHEN "t1"."sales" >= 100 THEN 'medium' ELSE 'small' END AS b,
       COUNT("t1"."sales") AS n, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY CASE WHEN "t1"."sales" >= 1000 THEN 'large' WHEN "t1"."sales" >= 100 THEN 'medium' ELSE 'small' END
```

**Point out.** `CASE` works both in `SELECT` and in `GROUP BY`, and the buckets add up to the
grand total. This is bucketing per fact row. Bucketing *customers by their total* needs a
CTE first (Module 5).

**Guarded by:** `l4_case_buckets`.

**Check yourself.** Write "sales in the last complete quarter" without `CURRENT_DATE`. Why
does `DATE_TRUNC` compile but fail, and what do you use instead?

---

## Module 5 — Advanced shapes (~40 min)

### 5.1 A CTE for two-step aggregation

**Question:** the average total sales per store (3.2's question, answered properly).

```sql
WITH st AS (
  SELECT "t1"."store" AS store, SUM("t1"."sales") AS s
  FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."store")
SELECT AVG(st.s) AS avg_store_sales, COUNT(st.store) AS n FROM st
```

**Point out.** The CTE aggregates to the store grain, then the outer query averages over the
CTE's columns. A CTE's columns are referenced through the CTE's name (`st.s`), not `t1`.
Most "aggregate of an aggregate" questions take this shape.

**Guarded by:** `l5_cte_two_step`.

### 5.2 Window functions: rank and share of total

```sql
SELECT "t1"."region" AS r, "t1"."store" AS store, SUM("t1"."sales") AS s,
       RANK() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) AS rk
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."region", "t1"."store"

SELECT "t1"."region" AS r, SUM("t1"."sales") AS s,
       SUM("t1"."sales") / SUM(SUM("t1"."sales")) OVER () AS share
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."region"
```

**Point out.** A window function can run over an aggregate (`SUM(SUM(x)) OVER ()` is the
grand total beside each group). The shares add up to 1, and the division is again made safe
with `NULLIF`.

**Guarded by:** `l5_rank`, `l5_share_of_total`.

### 5.3 Top N per group

**Question:** the two best-selling item types in each region.

```sql
WITH x AS (
  SELECT "t1"."region" AS r, "t1"."item type" AS it, SUM("t1"."sales") AS s,
         ROW_NUMBER() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) AS rn
  FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."item type")
SELECT x.r, x.it, x.s FROM x WHERE x.rn <= 2
```

**Point out.** Number the rows in a CTE, then filter in the outer query. Do **not** reach for
`QUALIFY`: it is accepted and silently ignored (6.1).

**Guarded by:** `l5_top_n_per_group`.

### 5.4 Period over period and running totals

```sql
SELECT YEAR_NUMBER("t1"."date") AS y, SUM("t1"."sales") AS s,
       LAG(SUM("t1"."sales")) OVER (ORDER BY YEAR_NUMBER("t1"."date")) AS prev
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY YEAR_NUMBER("t1"."date")
```

Swap `LAG(…)` for `SUM(SUM("t1"."sales")) OVER (ORDER BY YEAR_NUMBER("t1"."date"))` to get a
running total.

**Point out.** `prev` is the previous year's total, and NULL for the first year. The running
total for the latest year equals the grand total. The rows may not come back in year order:
add an `ORDER BY` if order matters. More shapes (last N periods, year to date) are in
[`patterns.md`](patterns.md).

**Guarded by:** `l5_year_over_year`, `l5_running_total`.

### 5.5 Combining results: set operations and CTE joins

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE "t1"."region" = 'West' GROUP BY "t1"."region"
UNION ALL
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE "t1"."region" = 'East' GROUP BY "t1"."region"
```

**Question:** sales per store for each region, from two CTEs joined on region.

```sql
WITH a AS (SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"),
     b AS (SELECT "t1"."region" AS r, COUNT(DISTINCT "t1"."store") AS n FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region")
SELECT a.r, a.s, b.n, a.s / b.n AS per_store FROM a JOIN b ON a.r = b.r
```

**Point out.** Both branches of a `UNION ALL` survive. Joining CTEs on an equality works. An
inequality join, or joining a CTE to itself, does not (`limitations.md`).

**Guarded by:** `l5_union_all`, `l5_join_ctes`.

### 5.6 `HAVING`, and the shapes that are not allowed

```sql
SELECT "t1"."store" AS store, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."store" HAVING SUM("t1"."sales") > 40000000
```

**Break it.** A subquery in `FROM` (`SELECT x.r FROM (SELECT …) AS x`) is rejected with
`TABLE_NOT_FOUND`. Rewrite it as a CTE: everything a derived table does, a CTE does here.

**Guarded by:** `l5_having`, `l5_from_subquery_rejected`.

**Check yourself.** Write "stores whose sales are above their region's average" (a CTE plus
a window, or two CTEs). Why does 5.3 use a CTE instead of `QUALIFY`?

---

## Module 6 — Trust, but verify (~30 min)

The hardest lesson in the course: **a `SUCCESS` with a plausible number can still be
wrong.** Some constructs are accepted, then partly ignored.

### 6.1 `QUALIFY` is silently dropped (and one more silent case)

```sql
SELECT "t1"."region" AS r, "t1"."item type" AS it, SUM("t1"."sales") AS s
FROM "(Sample) Retail - Apparel" AS "t1"
GROUP BY "t1"."region", "t1"."item type"
QUALIFY ROW_NUMBER() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) = 1
```

**Predict.** How many rows: one per region (5)?

**Point out.** 75 rows, every region and item type pairing. The generated SQL has no
`ROW_NUMBER` at all: the clause was dropped without an error. The **control** is 5.3's CTE
form with `rn = 1`, which returns 5 rows. Comparing the two is how you catch this.

**One more:** `SUM(CASE WHEN "t1"."date" >= '<this year>-01-01' THEN "t1"."sales" ELSE 0 END)`
generates **correct** SQL, but the result comes back typed `UNKNOWN` with an empty value. 4.3
showed the same comparison working in `WHERE`. The control is `YEAR_NUMBER(date) >= <this
year>` inside the `CASE`, which returns the number.

**Guarded by:** `l6_qualify_dropped`, `l6_sum_case_date_literal`.

### 6.2 `FILTER (WHERE …)` is silently dropped

```sql
SELECT SUM("t1"."sales") FILTER (WHERE "t1"."region" = 'West') AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Point out.** It returns the **grand total**, because the filter is not in the SQL. The
control, `SUM(CASE WHEN "t1"."region" = 'West' THEN "t1"."sales" ELSE 0 END)`, returns
West's share. A plausible-looking number is not a correct one.

**Guarded by:** `l6_filter_dropped`.

### 6.3 Lenient rewrites you should not rely on

```sql
SELECT "t1"."store" AS store, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE SUM("t1"."sales") > 40000000 GROUP BY "t1"."store"
```

**Point out.** This is invalid SQL, but it is quietly rewritten as `HAVING` and gives 5.6's
answer. Together with 2.7 (identifier case, a missing `GROUP BY`), that makes three lenient
parses. They help a beginner, and they are exactly why a successful query proves less than
it seems.

**Guarded by:** `l6_where_aggregate_is_having`.

### 6.4 Loud failures, and their workarounds

| Try | What happens | Instead |
|---|---|---|
| `STDDEV_SAMP("t1"."sales")` | rejected, `UNSUPPORTED_AGGREGATE` | apply it to a CTE column, e.g. the per-store totals from 5.1 |
| `WHERE region IN (SELECT …)` | compiles, then fails in the warehouse | join a CTE, or filter on the values directly |

Loud failures are the easy kind: the error tells you. The full list, with dates and
tickets, is [`limitations.md`](limitations.md).

**Guarded by:** `l6_stddev_rejected`, `l6_stddev_over_cte`, `l6_in_subquery_fails`.

### The verification habit

For any answer someone will act on:
1. **Read the generated SQL** and check that every clause you wrote is in it. A dropped
   `QUALIFY` or `FILTER` is visible there.
2. **For a number that matters, run a control:** the same question in a second form (a
   `CASE` instead of `FILTER`, a CTE instead of `QUALIFY`, the parts of a ratio). If the
   two agree, trust it.
3. **Check the result's types.** An `UNKNOWN` column, or an empty value where you expected a
   number, is a defect, not a zero.

**Check yourself.** A colleague's AgentQL returns `SUCCESS` and a total that "looks about
right". Name three checks you would run before putting it in front of a customer.

---

## Module 7 — Building on it (~30 min)

For developers and anyone wiring AgentQL into an agent or a test suite.

### 7.1 Consuming `fetch-data` in code

`fetch-data` returns `columns[]` (index and type) and `rows[]` (one list per row, in
`SELECT` order). Pair them by position, and convert `INT64` dates from epoch seconds:

```python
import datetime as dt, json, subprocess

def agentql(sql, model, profile):
    out = json.loads(subprocess.run(["ts", "agentql", "fetch-data", "--profile", profile, "-m", model, sql],
                                    capture_output=True, text=True, check=True).stdout)
    if out["status"] != "SUCCESS":
        raise RuntimeError(f'{out["status"]}: {out["errors"]}')
    return out["columns"], out["rows"]

cols, rows = agentql('SELECT "t1"."region" AS r, "t1"."date" AS d, SUM("t1"."sales") AS s '
                     'FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."date" '
                     'ORDER BY "t1"."date" DESC LIMIT 5', model_guid, profile)
for region, epoch, sales in rows:
    print(region, dt.datetime.fromtimestamp(epoch, dt.timezone.utc).date(), sales)
```

**Point out.** Branch on `status`, never on the exit code (1.1). The response carries no
column names, so keep your own `SELECT` order. Calling the REST endpoints directly from a
product, with auth options and the raw response format, is covered in
[`integration.md`](integration.md).

**Guarded by:** `l7_columns_match_rows`.

### 7.2 Testing an agent that writes AgentQL

The patterns are in [`use-cases.md`](use-cases.md):
- **Accuracy benchmarking:** a set of questions, each with an answer you know is right (from
  a control query, as in Module 6), run through the agent and compared.
- **Regression testing:** the same set re-run after a ThoughtSpot upgrade.
- **Known-limitation retesting:** queries that are expected to fail, re-run to find out when
  they start working.

### 7.3 This course is a test suite too

Every lesson above names the cases that check it. To see whether the course still matches
the product on your cluster, run:

```bash
python3 tools/agentql-retest/run.py --profile {profile} --suite lessons
```

It finds the sample Model by name, runs every lesson claim, and lists only the ones whose
behaviour has changed. Treat it as the worked example for 7.2: controls, value checks and
statuses that are never trusted alone. See `tools/agentql-retest/README.md`.

**Check yourself.** Design a five-question accuracy test for an agent on the sample Model.
How will you know each expected answer is right?

---

## Tracks

| Track | Modules | Time |
|---|---|---|
| **SE / field** (the default) | 0, 1, 2, 3, 6 | ~2.5 hours |
| **Developer integrating** | 0, 1, 2, 4, 5, 7 | ~3 hours |
| **QA / power user** | all | ~4 hours |

Each module stands alone after Module 2, so a learner can stop and pick up later
("teach me AgentQL, start at module 5").
