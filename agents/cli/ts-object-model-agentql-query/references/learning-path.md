# Learn AgentQL: a guided pathway

A hands-on course in writing AgentQL, what the two APIs do, and what SQL ThoughtSpot actually
sends to the warehouse. **It runs offline:** the agent walks through each exercise from the
captured examples — the AgentQL, the exact warehouse SQL ThoughtSpot generated, and what it
teaches — so **no cluster is needed**. Read this when someone asks to *learn*
AgentQL ("teach me AgentQL", "how does AgentQL work", "I need to demo this"). Not for
answering a business question; that is the normal flow in `SKILL.md`.

**Audience.** Built first for **SEs and other technical field staff** who need to explain and
demo the capability. It works for anyone comfortable reading SQL.

**Status.** All eight modules (0–7) are written and live-verified on 26.9.0.cl PROD. Every
behavioural claim is checked by a retest case, named on the lesson's **Guarded by** line.

---

## Start here — the opening message (show verbatim)

When the course starts, show the learner this message **exactly as written**, before anything
else and before running any lesson. It is the one fixed opening, so every run begins the same
way. Do not paraphrase it, and do not introduce the language by any former name.

> **Learn AgentQL.** AgentQL is a SQL dialect an AI agent writes against a ThoughtSpot
> **Model**, not against warehouse tables. ThoughtSpot never runs AgentQL itself — it
> **compiles it deterministically** into warehouse SQL (Snowflake, Databricks, BigQuery, …),
> and the warehouse runs that SQL. Because the Model supplies the joins, formulas, security
> and null-handling, the **same question always compiles to the same governed SQL and returns
> the same answer**. This course shows you that one question at a time — as much by reading the
> *generated SQL* as by writing AgentQL.
>
> This course runs from **real captured examples** — the actual AgentQL and the exact warehouse
> SQL ThoughtSpot generated for each one — so **no cluster is needed**. Result numbers are taught
> values, not live rows. We'll start with the concept, then take it one question at a time.

---

## The key takeaways — review the whole messaging arc

Every module opens with the same three pinned lines — **Key takeaway**, **How determinism
holds** and **Covers** — shown *verbatim* so the messaging is identical on every run. This
table collects them in one place; the **determinism column is the throughline** of the course.

| Module | Key takeaway | How determinism holds |
|---|---|---|
| **0 · Why AgentQL** | AgentQL widens *what* can be asked; keywords keep a human able to *verify* it — more expressibility, same governance. | ThoughtSpot *compiles* AgentQL and never executes the AI's SQL, so a more expressive question never trades away a governed, reproducible answer. |
| **1 · The two APIs** | `generate-sql` compiles (nothing runs); `fetch-data` compiles then runs. Branch on `status`, not the exit code; AgentQL can only read. | `generate-sql` shows the exact warehouse SQL the engine emits — the same AgentQL always compiles to the same `executable_sql`, inspectable before a row is read. |
| **2 · First queries** | Read the generated SQL: the joins — their *type* and keys — plus null-guards and the row cap are written for you from the Model (e.g. `sales → inner join → products`), not by your query. | The join type and keys come from the Model definition every time, so the same question emits identical governed SQL run-to-run; the lenient parser never changes what's emitted. |
| **3 · The semantic layer** | The Model supplies joins, formulas, security and safe division by default — and AgentQL can *override* the default join for greater expressibility: *all products, including those with no sales* becomes a CTE of all products `LEFT JOIN`ed to sales, instead of the Model's inner join. | Whether you take the Model's join or override it, the governed parts — keys, `AGG`/`SUM`, null-handling and RLS — are still injected deterministically by the engine. You change the join *shape*, never the governance. |
| **4 · Dates and functions** | Date parts, relative periods and functions resolve through the Model's calendar — standard Gregorian, fiscal, or a custom 4-4-5 — so you never hand-code calendar math or use `CURRENT_DATE`. | AgentQL doesn't guess how a fiscal or 4-4-5 calendar works — the engine applies the Model's calendar definition deterministically, so "last period" always compiles to the same bounded SQL. |
| **5 · Advanced shapes** | CTEs, windows, top-N-per-group, period-over-period and set operations expand what you can express — within AgentQL's (narrower-than-SQL) envelope. | Even multi-stage shapes compile deterministically through the same governed engine; expressibility grows while compile-not-execute holds. |
| **6 · Trust, but verify** | `SUCCESS` is not proof of the right answer: deterministic SQL can be deterministically *wrong* — a silently-dropped `QUALIFY`/`FILTER`, or the wrong grain. | The executed SQL is always governed and reproducible — but determinism guarantees *consistency*, not *correct intent*. The control queries verify the agent asked what you meant. |
| **7 · Building on it** | Consume `fetch-data` in code, and test agents that write AgentQL — this course is itself a regression suite. | Because the same question compiles to the same SQL and rows, AgentQL output is testable: assert on generated SQL and results, and catch drift. |

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

The captured examples in this course were taken from this Model (it ships on every cluster).
Because the course is **offline**, you never search for or connect to it — the AgentQL and the
generated SQL are already captured in [`lesson-sql.md`](lesson-sql.md). For reference, its GUID
on the SE demo cluster is `cd252e5c-b552-49a8-821d-3eadaa049cca`.

**Because `date` rolls forward, totals bucketed by date change from day to day.** Never tell
a learner to expect a specific dated number. Totals over all time are stable.

---

## How this course runs (offline)

This course is **offline**: nothing runs on a cluster. Each lesson is presented from material
already captured — the AgentQL, and the real warehouse SQL ThoughtSpot compiled for it — so the
learner needs no profile and no Model, and there is no per-lesson tool cost.

- **Section 3 (DB SQL Generated)** shows the **real captured `executable_sql`** for the lesson,
  from [`lesson-sql.md`](lesson-sql.md), matched by the lesson's **Guarded by** id. It is the
  actual output of a live capture — never reconstruct SQL by hand.
- For a *break it* lesson, **section 4** shows the captured `status` and error.
- **Section 6 (Results)** shows taught values, not live rows. Say so once up front, so nobody
  mistakes a taught figure for a fresh one (the sample's rolling `date` moves dated totals anyway).
- A few lessons are **illustrative** (and labelled so): where the sample Model can't show a
  feature — RLS, a custom calendar, non-default join types — the lesson carries its
  representative SQL **inline**, clearly marked, instead of a live capture.

The whole reference library is also bundled as one document,
[`agentql-offline.md`](agentql-offline.md), for reading end to end. *(Want fresh numbers against
your own data? That is the skill's normal live query flow in `SKILL.md` — not the course.)*

---

## How to run a lesson

**Show the AgentQL. Don't ask the learner to write it.** The lesson's query is ready to
run, so nobody loses time to syntax errors, and the learning is in what ThoughtSpot does
with it. A learner who wants practice can write their own instead: run theirs, then compare
it with the lesson's.

Each lesson runs in two moves — a short pause to predict, then the result in a fixed block:

1. **Predict, briefly.** Show the lesson's AgentQL, then ask one short question in the same
   message, such as *"Before I run it: which tables will this touch?"*. Use the lesson's
   **Predict** line if it has one. Then wait. Any answer is fine, and so is a plain "show me":
   reveal it then, without pressing for a guess. The prediction is useful, but it is optional,
   not a quiz.
2. **Reveal and report in the six-section block below.** Present the lesson in the **same six
   sections, in the same order, every time** — the canonical structure from `SKILL.md` Step 6 —
   filling section 3 with the captured SQL (below). Consistency across lessons is the point: a
   learner should see the same shape for question 1 and question 36.

   **One lesson at a time.** Show a *single* lesson's six-section block, then **stop and wait**
   for the learner to say *next* / *continue* before the following lesson. Never present a whole
   module's questions in one message — it overwhelms. The module's pinned opener is shown once,
   at the start of the module; the lessons then come one at a time.

| Section | In a lesson |
|---|---|
| **1. Question** | The lesson's business question in plain English. |
| **2. AgentQL Sent** | The lesson's AgentQL, with any placeholders filled in. |
| **3. DB SQL Generated** | The captured `executable_sql` for this lesson from [`lesson-sql.md`](lesson-sql.md) (matched by its **Guarded by** id). Walk through the lesson's **Point out** items here, comparing them with the prediction if there was one. |
| **4. Error & Explanation** | *Only when a call is rejected* (the "Break it" variants, and any lesson whose point is a failure). The `status` code + message, and the rule in [`agentql-rules.md`](agentql-rules.md) it maps to. Omit when the query succeeds. |
| **5. Key Findings** | The one or two things this lesson teaches — the lesson's **Point out** takeaway, a `columns[].type` surprise, a join the Model added. |
| **6. Results** | The taught result as a table (illustrative, not live rows), with headers from the SELECT list. |

**The "Break it" variant is its own entry in the same six-section block**, where section 4
carries the rejection. At the end of each module, ask its **Check yourself** questions.

*(Optional, live — outside the offline course: a learner with their own Model and a profile can
run any of these through the skill's normal flow in `SKILL.md` to see fresh rows.)*

**Keeping it accurate.** The captured SQL reflects the build it was captured on (dated in
[`lesson-sql.md`](lesson-sql.md)). The **Guarded by** ids name the retest-suite cases that check
each lesson's claims (`tools/agentql-retest`, `--suite lessons`); re-run the capture to refresh
the SQL when the product moves. A failing case means the lesson needs updating, not the learner.

**Opening a module.** Start every module by showing its pinned **Key takeaway**, **How
determinism holds** and **Covers** lines *exactly as written in the module header* — don't
improvise the framing, so a learner sees the same messaging on every run (the
[key-takeaways table](#the-key-takeaways--review-the-whole-messaging-arc) collects them all).
Introduce the language only as **AgentQL** — never by its former name.

**Showing the explanation.** Present concept-explaining text *as written*, never paraphrased:
Module 0's **The concept (show verbatim)** section in full, and in every hands-on lesson the
written **Point out** and **Key Findings** text. Everything the learner reads — concept, Point out, Key Findings, and the captured SQL — is the
same on every run.

---

## Module 0 — Why AgentQL, and why keywords stay (concept, ~15 min)

**Key takeaway.** AgentQL widens *what* can be asked; keywords keep a human able to *verify* it — more expressibility, same governance.

**How determinism holds.** ThoughtSpot *compiles* AgentQL and never executes the AI's SQL, so a more expressive question never trades away a governed, reproducible answer.

**Covers.** The positioning, the expressibility↔determinism trade-off, and a three-query taster. (concept · ~15 min)

Read [`architecture.md`](architecture.md) § "The core principle" for the deeper version. The
concept below is **pinned**: present it to the learner **exactly as written**, in full, before
the taster — don't paraphrase or compress it. This is the one explanation every run shows.

### The concept (show verbatim)

ThoughtSpot has **two** ways to create a query over the **same** governed Model, and both keep a
human able to validate intent:

| | **Keyword Search** (the foundation) | **AgentQL** (greater expressibility) |
|---|---|---|
| Who writes the query | A person, in natural language → **keywords** | An **AI agent**, in AgentQL (Semantic SQL) |
| What it can express | Filtering, pivoting, drill-down, calendars, governed metrics | All of that **plus** multi-stage analysis, complex expressions, CTEs, outer joins, and (where supported) cross-model queries |
| How a human validates | Inspect the **keywords** — no SQL to read | **Still the keywords** — the agent's query is surfaced as keywords too, so a human confirms intent without reading SQL |
| Execution | Governed engine compiles to warehouse SQL | **Same** governed engine, same compile step |

**Keyword Search isn't replaced.** Today keywords do two jobs: they create the query and they
let a person check it. With AgentQL the agent takes over creating the query, and keywords keep
the checking job.

**The trade-off.** The more an agent can express, the more decisions it makes, and some of those
are about business meaning (which join, at what grain), not just syntax.

- **Keyword Search** is more *deterministic*, because an analyst defined the relationships in the
  Model in advance.
- **AgentQL** is more *flexible*, so someone has to check the logic the agent chose.

**Valid SQL is not proof of correct business logic.** A query can compile, run and return a
confident wrong number. Three ideas run through the rest of the course:

1. **ThoughtSpot never executes AgentQL.** It compiles AgentQL into warehouse SQL, and the
   warehouse runs that SQL.
2. **You query the Model, not the tables.** `FROM` names one Model, and every column is a
   business name such as `"t1"."sales"`.
3. **That's what makes answers consistent.** The joins, row-level security (RLS) and formulas
   come from the Model, so two people asking the same question get the same answer. That is why
   every lesson shows the generated SQL: it shows which parts the Model decided and which parts
   the agent decided.

### See it in three queries (optional — run these now)

Before the deep dive, here are three short queries that show the whole story at a glance. Run
them live if the learner wants proof; otherwise they stand as the gist. Each maps to a full
lesson later — this is the preview, not the detail. (Every query here is live-verified on the
sample Model and guarded by a retest case.)

**1 — The governed foundation (both languages share this).**
```sql
SELECT SUM("t1"."sales") AS "Total Sales" FROM "(Sample) Retail - Apparel" AS "t1"
```
You name the *business* column `sales`; the Model supplies the physical table and joins. A
keyword search answers this too — it's the common, governed base both approaches stand on.
*(Full: Module 1–2. Guarded by `ctl_ap_total`.)*

**2 — What AgentQL adds, and the business rules it inherits.**
```sql
WITH all_p AS (SELECT "t1"."product" AS p FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."product"),
     west AS (SELECT "t2"."product" AS p, SUM("t2"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t2"
              WHERE "t2"."region" = 'West' GROUP BY "t2"."product")
SELECT a.p, COALESCE(west.s, 0) FROM all_p a LEFT OUTER JOIN west ON a.p = west.p
```
*Every* product, including four never sold in the West (they come back `0`, not dropped) — an
outer join keywords can't express. Show the generated SQL: the `LEFT OUTER JOIN` is the agent's
contribution; the inner joins, keys, null-guards and (where present) RLS are the **Model's**,
written for you. *(Full: lesson 3.6. Guarded by `l3_all_products_left_join`.)*

**3 — The honest limit.**
```sql
SELECT PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY "t1"."sales") FROM "(Sample) Retail - Apparel" AS "t1"
```
Rejected — `UNSUPPORTED_AGGREGATE`. AgentQL is far more expressive than keywords but **narrower
than raw warehouse SQL**: when a shape has no form, it refuses rather than guessing a wrong
answer. *(Full: [`beyond-keywords.md`](beyond-keywords.md).)*

Together: a governed base (1), expressibility with the governance still applied (2), and a
clear boundary (3) — the three claims of this module, in three queries.

**Check yourself.** Who authors the query in each approach, and who validates it? Name one
thing AgentQL can ask that keywords can't. Why does "the SQL compiled and ran" *not* settle
whether the answer is right — and which parts of the answer are governed regardless?

---

## Module 1 — The two APIs (~20 min · 5 questions)

**Key takeaway.** `generate-sql` compiles (nothing runs); `fetch-data` compiles then runs. Branch on `status`, not the exit code; AgentQL can only read.

**How determinism holds.** `generate-sql` shows the exact warehouse SQL the engine emits — the same AgentQL always compiles to the same `executable_sql`, inspectable before a single row is read.

**Covers.** The two calls, structured errors, a query that compiles but fails, result types, and read-only. (5 questions · ~20 min)

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
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
WHERE "t1"."product" IN (
  SELECT "t2"."product" FROM "(Sample) Retail - Apparel" AS "t2" WHERE "t2"."item type" = 'Jackets')
```

**Predict.** Will this compile? Will it run?

**Point out.** It compiles (`SUCCESS`) — `generate-sql` returns warehouse SQL — but `fetch-data`
fails (`QUERY_EXECUTION_FAILED`, a SQL compilation error): the `IN (SELECT …)` subquery is
passed through untranslated and the warehouse rejects it
([SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936)). A green `generate-sql`
means *valid AgentQL*, not *runs successfully* — a query is not proven until `fetch-data` returns
rows. The fix is a CTE semi-join (see [`beyond-keywords.md`](beyond-keywords.md) and
`patterns.md`); `limitations.md` lists the compile-then-fail cases.

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

### 1.5 It can only read

The question every customer asks: *"could the AI change or delete my data?"* Show the answer.

```sql
DELETE FROM "(Sample) Retail - Apparel"
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"; DROP TABLE "(Sample) Retail - Apparel"
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" -- ; DROP TABLE x
```

**Run these with `generate-sql` only.** It compiles without touching the warehouse.

**Point out.**
- The `DELETE` is rejected: *"Only SELECT queries are supported"*. So are `UPDATE`,
  `INSERT`, `DROP`, `CREATE`, `GRANT` and the rest.
- The second statement after `;` is rejected too.
- The comment compiles, but the warehouse SQL is **generated from scratch** as one `SELECT`,
  and the comment is not in it. That is the core design from Module 0: ThoughtSpot compiles
  AgentQL into new SQL rather than running what it was handed, so a trailing `; DROP` or a
  `-- comment` cannot ride along.
- Scope this correctly: it means AgentQL **will not write or run DDL**. It is not a promise
  that a `SELECT` can read only the Model — the warehouse connection's grants are still what
  bound what a query can reach.
- The full list, and how it is checked on every run, is in
  [`limitations.md`](limitations.md) § "Read-only by design".

**Guarded by:** `g_delete_all`, `g_second_statement_drop`, `g_line_comment`.

**Check yourself.** Which call would you use to check a query in a loop while drafting it,
and why? A query returns `SUCCESS` from `generate-sql`: what can and can't you conclude? A
customer asks whether an agent using AgentQL could drop a table: what do you show them?

---

## Module 2 — First queries: reading the SQL ThoughtSpot writes (~40 min · 8 questions)

**Key takeaway.** Read the generated SQL: the joins — their *type* and keys — plus null-guards and the row cap are written for you from the Model (e.g. `sales → inner join → products`), not by your query.

**How determinism holds.** The join type and keys come from the Model definition every time, so the same question emits identical governed SQL run-to-run; the lenient parser never changes what's emitted.

**Covers.** Joins written for you, null handling, the row cap, inlined formulas, the lenient parser, the bare-measure trap, and how the Model's join *type* shapes the SQL. (8 questions + 1 illustrative · ~40 min)

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

### 2.9 The join type is the Model's, not yours (illustrative)

Every join so far has been an **inner** join, because that is how the sample Model defines its
fact↔dimension relationships. But the join **type** — inner, left, right, or full outer — is a
Model property, and the generated SQL uses whatever the Model defines. You write the *same*
AgentQL either way. The sample Model is inner-only, so the variants below are **illustrative**.

**Question.** Sales by product.

**AgentQL Sent** — the same grouped query, whatever the Model's join type:
```sql
SELECT "t1"."product" AS p, SUM("t1"."sales") AS s FROM "<Model>" AS "t1" GROUP BY "t1"."product"
```

**DB SQL Generated.** Against the sample (inner) it compiles in full to:
```sql
SELECT "ta_2"."PRODUCTNAME" "ca_1",
       CASE WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES") ELSE 0 END "ca_2"
FROM "…"."FACT_SALES" "ta_1"
  JOIN "…"."DIM_PRODUCTS" "ta_2" ON "ta_1"."PRODUCTID" = "ta_2"."PRODUCTID"
GROUP BY "ta_2"."PRODUCTNAME"
LIMIT 100000
```
If the Model defined the fact↔products relationship with a different join type, **only the join
line changes** — the `SELECT`, `GROUP BY`, null-guard and row cap are identical. The full
statement with each type:
```sql
-- LEFT OUTER (Model: "sales LEFT JOIN products") — every sales row kept, even if its product is missing
SELECT "ta_2"."PRODUCTNAME" "ca_1",
       CASE WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES") ELSE 0 END "ca_2"
FROM "…"."FACT_SALES" "ta_1"
  LEFT OUTER JOIN "…"."DIM_PRODUCTS" "ta_2" ON "ta_1"."PRODUCTID" = "ta_2"."PRODUCTID"
GROUP BY "ta_2"."PRODUCTNAME"
LIMIT 100000

-- RIGHT OUTER (Model: "sales RIGHT JOIN products") — every product kept, even one with no sales
SELECT "ta_2"."PRODUCTNAME" "ca_1",
       CASE WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES") ELSE 0 END "ca_2"
FROM "…"."FACT_SALES" "ta_1"
  RIGHT OUTER JOIN "…"."DIM_PRODUCTS" "ta_2" ON "ta_1"."PRODUCTID" = "ta_2"."PRODUCTID"
GROUP BY "ta_2"."PRODUCTNAME"
LIMIT 100000

-- FULL OUTER (Model: "sales FULL OUTER JOIN products") — both unmatched sides kept
SELECT "ta_2"."PRODUCTNAME" "ca_1",
       CASE WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES") ELSE 0 END "ca_2"
FROM "…"."FACT_SALES" "ta_1"
  FULL OUTER JOIN "…"."DIM_PRODUCTS" "ta_2" ON "ta_1"."PRODUCTID" = "ta_2"."PRODUCTID"
GROUP BY "ta_2"."PRODUCTNAME"
LIMIT 100000
```

**Key Findings.** The join **type** is defined once — in the Model, on the fact↔dimension
relationship. The agent never writes `JOIN`, and the generated SQL carries exactly the type the
Model set. Change the Model from inner to right outer and "sales by product" starts including
products that never sold, with **no change to the AgentQL**. (When the Model's join is inner but
you need all members for *one* question, AgentQL can override it with a CTE outer join — that is
lesson 3.6.) *(Illustrative — the sample Model is inner-only, so there is no retest case.)*

**Check yourself.** Without running anything: which tables will a query for "quantity by
state" touch? What does the query in 2.8 do, and how would you spot it from the result alone?
Why does `CURRENT_DATE` fail when the Model's own formula uses it?

**Try it on your Model.** Pick a Model the learner works with. Write one grouped query for it
(you write it, or the learner does if they want to), then
predict its joins from the Model's TML (`ts tml export … --parse`, `model_tables[].joins`)
before running `generate-sql`.

---

## Module 3 — What the semantic layer does for you (~35 min · 6 questions)

**Key takeaway.** The Model supplies joins, formulas, security and safe division by default — and AgentQL can *override* the default join for greater expressibility: *all products, including those with no sales* becomes a CTE of all products `LEFT JOIN`ed to sales, instead of the Model's inner join.

**How determinism holds.** Whether you take the Model's join or override it, the governed parts — keys, `AGG`/`SUM`, null-handling and RLS — are still injected deterministically by the engine. You change the join *shape*, never the governance.

**Covers.** Ratios and safe division, what `AVG` averages, table pruning, `AGG` vs `SUM`, RLS, and every-member outer joins (3.6). (6 questions · ~35 min)

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

No query here mentions security, and none needs to. If the Model carries **row-level security
(RLS)**, ThoughtSpot injects the user's filter into the compiled SQL automatically — so two
users running the *same* AgentQL get different rows, each correct for them. The agent never
writes the filter and cannot remove it. Read [`architecture.md`](architecture.md) § "What the
semantic layer guarantees".

The sample Model has no RLS rule, so the blocks below are **illustrative** (not live captures).
Assume the rule is on the **fact** table. The clearest test is a **dimension-only** question —
*"list all stores"* — because whether the fact is touched at all now depends on the RLS mode.

**Strict RLS (recommended).** The rule is on one table (the fact), and ThoughtSpot **always
forces the join to it in** — even for a question that only needs the stores dimension. So
*"list all stores"* still joins the fact and applies the filter, and the AgentQL **cannot remove
that join**:
```sql
SELECT "ta_2"."STORE" "ca_1"
FROM "…"."FACT_SALES" "ta_1"
  JOIN "…"."DIM_STORES" "ta_2" ON "ta_1"."STOREID" = "ta_2"."STOREID"
WHERE ("ta_1"."_TENANT_ID" IN (2200539748))
GROUP BY "ta_2"."STORE"
LIMIT 100000
```
The fact join is there **only** to carry the RLS filter — so every query is scoped, even one
that never asked for a measure.

**Non-strict RLS.** Only the tables the question needs are included, so RLS applies per table —
which makes *which tables you secure* a deliberate design choice:

- **Secure the fact only** — appropriate when only sales-level data is sensitive. Any query that
  includes sales is filtered, but *"list all stores"* touches just the stores table, so it has no
  fact join and returns **all** stores:
```sql
SELECT "ta_1"."STORE" "ca_1"
FROM "…"."DIM_STORES" "ta_1"
GROUP BY "ta_1"."STORE"
LIMIT 100000
```

- **Secure the store table too** — when store membership itself must be restricted. The same
  *"list all stores"* is then filtered on the store table directly:
```sql
SELECT "ta_1"."STORE" "ca_1"
FROM "…"."DIM_STORES" "ta_1"
WHERE ("ta_1"."_TENANT_ID" IN (2200539748))
GROUP BY "ta_1"."STORE"
LIMIT 100000
```

With rules on more than one table, a query that joins them carries the predicate on each — e.g.
*"sales by store"* with rules on both fact and stores:
```sql
… FROM "…"."FACT_SALES" "ta_1"
  JOIN "…"."DIM_STORES" "ta_2" ON "ta_1"."STOREID" = "ta_2"."STOREID"
WHERE (
  ("ta_1"."_TENANT_ID" IN (2200539748))
  AND ("ta_2"."_TENANT_ID" IN (2200539748))
)
GROUP BY "ta_2"."STORE"
LIMIT 100000
```

**Key Findings.** The `_TENANT_ID IN (…)` predicate is **injected by the RLS rule** — the agent
never wrote it and can't remove it; the tenant id comes from the user's context. The mode decides
*reach*: **strict RLS forces the secured table's join into every query**, so one rule on the fact
scopes even a dimension-only question; **non-strict** filters only the tables a query includes, so
you place rules by what must be protected — the fact for sales-level data, and any dimension (like
store) whose membership must also be restricted. Either way security lives in the Model, applied at
compile time — the strongest argument for AgentQL over hand-written SQL. (Column-level security
hides columns the same way.)

### 3.6 Every product, including the ones with no sales — and the business rules in the SQL

This is the module's showcase. It does two things at once: it shows a shape **keywords can't
express** (every member, matched or not — an outer join), and it is the clearest look at
**how much business logic the Model writes into the SQL for you**. Lesson 3.3 ended on a
warning — a query across two dimensions silently drops the combinations with no sales. Here is
the fix, and the anatomy of what ThoughtSpot generated.

**Question:** every product, with its sales **in the West region** — products not sold in the
West should still appear, with no number rather than being dropped.

```sql
WITH all_p AS (
  SELECT "t1"."product" AS p
  FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."product"
), west AS (
  SELECT "t2"."product" AS p, SUM("t2"."sales") AS s
  FROM "(Sample) Retail - Apparel" AS "t2"
  WHERE "t2"."region" = 'West' GROUP BY "t2"."product"
)
SELECT a.p AS product, COALESCE(west.s, 0) AS west_sales
FROM all_p a
LEFT OUTER JOIN west ON a.p = west.p
```

**Predict.** Two things: will products never sold in the West appear at all? And what will
their `west_sales` be?

**Read the generated SQL — this is the point of the lesson.** `generate-sql` returns (trimmed):

```sql
WITH "qt_0" AS (                                   -- the "all products" CTE
  SELECT "ta_1"."PRODUCTNAME"
  FROM "…"."DIM_RETAPP_PRODUCTS" "ta_1"            -- ① dimension table ALONE — no fact join
  GROUP BY "PRODUCTNAME"
), "qt_1" AS (                                      -- the "West sales" CTE
  SELECT "ta_2"."PRODUCTNAME",
    CASE WHEN sum("ta_3"."SALES") IS NOT NULL
         THEN sum("ta_3"."SALES") ELSE 0 END       -- ③ null-guarded aggregate
  FROM "…"."FACT_RETAPP_SALES" "ta_3"
    JOIN "…"."DIM_RETAPP_PRODUCTS" "ta_2" ON "ta_3"."PRODUCTID" = "ta_2"."PRODUCTID"   -- ② Model's
    JOIN "…"."DIM_RETAPP_STORES"   "ta_4" ON "ta_3"."STOREID"   = "ta_4"."STOREID"     --    inner joins + keys
  WHERE LOWER("ta_4"."REGION") = 'west'            -- ④ case-insensitive filter
  GROUP BY "PRODUCTNAME"
)
SELECT "ta_5"."PRODUCTNAME",
  CASE WHEN "ta_6".sales IS NOT NULL THEN "ta_6".sales ELSE 0 END
FROM "qt_0" "ta_5"
  LEFT OUTER JOIN "qt_1" "ta_6" ON …               -- ⑤ your outer join, preserved
LIMIT 100000                                        -- ⑥ the row cap
```

**Point out — every numbered item is a decision the agent did *not* make:**
- **① `join_progressive`.** The "all products" CTE reads `DIM_RETAPP_PRODUCTS` **by itself** —
  the Model knows an attribute-only query needs no fact table, so you get the *full* product
  list, not just products that sold. This is what makes the outer join meaningful (3.3).
- **② Join type and keys.** You never wrote `PRODUCTID` or `STOREID`, or that these are inner
  joins. The **Model** supplied the relationships; two people asking this get the same joins.
- **③ Null handling.** Every aggregate is wrapped `CASE WHEN … IS NOT NULL … ELSE 0`. The
  Model decides how NULLs behave — you didn't.
- **④ A governed business rule.** The region filter compiled to `LOWER(REGION) = 'west'` —
  case-insensitive by the Model's definition, not your literal.
- **⑤ Your contribution.** The `LEFT OUTER JOIN` and `COALESCE` are the *agent's* logic — the
  expressibility AgentQL adds. The Model couldn't express "all members" through its inner
  join; you did, with a CTE.
- **⑥ The row cap** (100,000) is applied for you.
- **RLS would live here too.** This sample has no row-level security, but if it did,
  the WHERE in `qt_1` would also carry the user's RLS predicate — injected at compile, not
  writable or removable by the agent (3.5). That is the un-bypassable part.

**Results.** 349 products; **4 come back with `west_sales = 0`** (Classic t-shirt, Penguin
t-shirt, Foothills t-shirt, Organic cotton under tee) — sold elsewhere, never in the West.
Without the outer join they would have silently vanished.

**This is the trade-off from Module 0, made concrete:** ⑤ is the agent's flexibility; ①–④ and
RLS are the Model's guarantees. Validate ⑤; trust the rest.

**Guarded by:** `l3_all_products_left_join`.

**Check yourself.** Why is `SUM(sales) / SUM(quantity)` the right average price, and
`AVG(sales / quantity)` not? A dimension-only query lists fewer products than the product
table holds: name two reasons. In 3.6, which parts of the generated SQL did the agent write,
and which did the Model write — and which of the Model's parts could the agent *not* remove
even if it tried?

---

## Module 4 — Dates and functions (~30 min · 5 questions)

**Key takeaway.** Date parts, relative periods and functions resolve through the Model's calendar — standard Gregorian, fiscal, or a custom 4-4-5 — so you never hand-code calendar math or use `CURRENT_DATE`.

**How determinism holds.** AgentQL doesn't guess how a fiscal or 4-4-5 calendar works — the engine applies the Model's calendar definition deterministically, so "last period" always compiles to the same bounded SQL. (The sample Model is Gregorian; the fiscal/4-4-5 guarantee is the general one.)

**Covers.** Date parts, relative dates without `CURRENT_DATE`, date literals, string functions, `CASE` buckets, and an illustrative custom-calendar example. (5 questions + 1 illustrative · ~30 min)

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

### 4.6 A custom calendar you never compute (illustrative)

Not every business runs on the Gregorian year. A Model can carry a **custom calendar** — here
**JulyOffset**, a fiscal calendar whose year starts in July — and relative-period questions then
resolve through *it*, not the Gregorian year. The sample Model has no custom calendar, so this is
**illustrative** (not a live capture).

**Question.** Sales for the **last five fiscal years**, on the JulyOffset calendar.

**AgentQL Sent** *(representative — the learner names the period; the Model's calendar supplies the
boundaries):*
```sql
SELECT SUM("t1"."sales") AS "Sales (last 5 fiscal years)"
FROM "<a Model on the JulyOffset calendar>" AS "t1"
WHERE <the last five completed fiscal years>
```

**DB SQL Generated** *(illustrative).* ThoughtSpot compiles **two** date filters, each doing a
different job:
```sql
-- 1. Coarse filter — partition pruning on the fact. A Model setting applies coarse date bounds
--    so the warehouse prunes partitions before the fine filter runs (a performance step):
AND "ta_3"."TRANSACTIONDATE" >= DATE('2020-01-01', 'YYYY-MM-DD')
AND "ta_2"."TRANSACTIONDATE" >= DATE('2020-01-01', 'YYYY-MM-DD')

-- 2. Fine-grain filter — the JulyOffset custom calendar, via its absolute_year_number
--    (ta_1 = the calendar, ta_4 = the current period): the five completed prior fiscal years.
AND ((
    "ta_1"."absolute_year_number" >= ("ta_4"."absolute_year_number" - 5)
    AND "ta_1"."absolute_year_number" <= ("ta_4"."absolute_year_number" - 1)
  ))
```

**Key Findings.** AgentQL never computed a fiscal boundary. "Last five fiscal years" is resolved
by the **custom calendar**: the engine joins the calendar table and compares its
`absolute_year_number` against the current period's — deterministically, the same way every run.
The two filters have distinct jobs: the **coarse** `TRANSACTIONDATE >= …` bounds are a *pruning*
optimisation on the fact, while the **fine-grain** `absolute_year_number` window is the actual
answer. Swap JulyOffset for a 4-4-5 or any fiscal calendar and the AgentQL is unchanged — only the
Model's calendar definition differs. That is why "last period" means the right thing to everyone,
with no hand-coded fiscal math.

**Check yourself.** Write "sales in the last complete quarter" without `CURRENT_DATE`. Why
does `DATE_TRUNC` compile but fail, and what do you use instead?

---

## Module 5 — Advanced shapes (~40 min · 6 questions)

**Key takeaway.** CTEs, windows, top-N-per-group, period-over-period and set operations expand what you can express — within AgentQL's (narrower-than-SQL) envelope.

**How determinism holds.** Even multi-stage shapes compile deterministically through the same governed engine; expressibility grows while compile-not-execute holds.

**Covers.** CTEs, ranking and share of total, top N per group, period over period, and set operations. (6 questions · ~40 min)

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

## Module 6 — Trust, but verify (~30 min · 4 questions)

**Key takeaway.** `SUCCESS` is not proof of the right answer: deterministic SQL can be deterministically *wrong* — a silently-dropped `QUALIFY`/`FILTER`, or the wrong grain.

**How determinism holds.** The executed SQL is always governed and reproducible — but determinism guarantees *consistency*, not *correct intent*. The control queries verify the agent asked what you meant.

**Covers.** Queries that return `SUCCESS` with the wrong number, and the control queries that catch them. (4 questions · ~30 min)

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

## Module 7 — Building on it (~30 min · 3 questions)

**Key takeaway.** Consume `fetch-data` in code, and test agents that write AgentQL — this course is itself a regression suite.

**How determinism holds.** Because the same question compiles to the same SQL and rows, AgentQL output is testable: assert on generated SQL and results, and catch drift.

**Covers.** Consuming results in code, testing an agent that writes AgentQL, and the course as a test suite. (3 questions · ~30 min)

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

## The modules

| Module | In short | Questions |
|---|---|---|
| 0. Why AgentQL | ThoughtSpot compiles AgentQL to warehouse SQL and never runs it; the Model supplies the joins, formulas and security | concept |
| 1. The two APIs | `generate-sql` vs `fetch-data`, structured errors, a query that compiles but fails, result types, why it can only read | 5 |
| 2. First queries | reading the generated SQL: joins written for you, null handling, the row cap, inlined formulas, the lenient parser, the bare-measure trap | 8 |
| 3. The semantic layer | ratios and safe division, what `AVG` averages, which tables a query reads, formula measures (`AGG` not `SUM`), security you never write, every member via an outer join and the business rules in the generated SQL | 6 |
| 4. Dates and functions | date parts, relative dates without `CURRENT_DATE`, date literals, string functions, `CASE` buckets | 5 |
| 5. Advanced shapes | CTEs, ranking and share of total, top N per group, period over period, set operations | 6 |
| 6. Trust, but verify | queries that return `SUCCESS` with the wrong number, and the control queries that catch them | 4 |
| 7. Building on it | consuming results in code, testing an agent that writes AgentQL | 3 |

37 questions in all. Each module stands alone after Module 2, so a learner can stop and pick
up later ("teach me AgentQL, start at module 5").

## After the course — where AgentQL earns its keep, and where it can't

[`beyond-keywords.md`](beyond-keywords.md) is the capstone: four live-verified worked examples of
questions that **keywords can't answer**, and ones where **even AgentQL hits a wall** —
rank within a partition, a preceding-7-days window, a cohort semi-join, and an unsupported
percentile. Each is written in the same six-section block the lessons use, so it reads like
four more questions. Good material for a demo, and the honest answer to "why not just use
search?".
