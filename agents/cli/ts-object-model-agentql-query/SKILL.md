---
name: ts-object-model-agentql-query
description: Ask a question of a ThoughtSpot Model and get the answer as data — write AgentQL (Semantic SQL), validate it to warehouse SQL, execute it, and review the results. Use this whenever someone wants to query a ThoughtSpot Model with AgentQL, turn a natural-language question into AgentQL, see the SQL ThoughtSpot generates for a question, pull rows from a Model programmatically, learn how the AgentQL APIs behave, take a guided hands-on course in AgentQL, or build a question set to accuracy-test / regression-test / feature-test AgentQL. Triggers on "query this model", "ask the model", "run AgentQL", "what SQL does ThoughtSpot generate", "get the data for…", "teach me AgentQL", even when AgentQL isn't named explicitly.
---

# ThoughtSpot: Query a Model with AgentQL

> **AgentQL** is a SQL dialect an AI agent writes against a ThoughtSpot **Model**, not against
> warehouse tables. ThoughtSpot never runs AgentQL itself — it **compiles it deterministically**
> into warehouse SQL (Snowflake, Databricks, BigQuery, …), and the warehouse runs that SQL.
> Because the Model supplies the joins, formulas, security and null-handling, the **same
> question always compiles to the same governed SQL and returns the same answer**.

Turn a question about a ThoughtSpot **Model** into an answer. You (the agent) write an
AgentQL statement grounded in the rules in `references/`, then run it through two `ts`
commands: `generate-sql` (**ThoughtSpot** compiles it to warehouse SQL and validates it)
and `fetch-data` (**ThoughtSpot** executes it and returns rows). You never compile or
translate AgentQL yourself — ThoughtSpot does the AgentQL→SQL compilation, deterministically,
so the warehouse SQL and the results are exactly what the platform would run. The result is
a **review** the user can inspect at the level they care about — the data table, the
AgentQL, the warehouse SQL, or the raw JSON.

This skill is the **primitive**. It is the foundation other things build on: an
onboarding tutorial, a drop-in for your own agent, or the per-question engine of an
accuracy / regression / feature test suite. See `references/use-cases.md` for those
compositions — they are *uses* of this skill, not built into it.

## What this skill does

If asked "what can you do?", this is the answer. Given a question about a ThoughtSpot Model
I can:

- **Answer it** — write the AgentQL and hand it to ThoughtSpot, which compiles it to the
  warehouse SQL and executes it; I return the rows as a table.
- **Show the work** — the AgentQL, the generated warehouse SQL, the raw JSON, or just the
  data table, at whatever depth you want.
- **Help you integrate** — hand you ready-to-paste API request bodies and point you at
  `references/integration.md` (auth, endpoints, response parsing) to call AgentQL from your
  own product or agent.
- **Explain the rules** — what AgentQL can and can't express: aggregation (`SUM` vs `AGG`),
  the date/time UDFs, query patterns (top-N, year-over-year, semi-additive measures), and
  the known limitations.
- **Teach you AgentQL** — a guided, hands-on course run live on a sample Model every cluster
  has. See [Learn AgentQL](#learn-agentql--a-guided-course) below.
- **Explain *why* AgentQL exists** — the architecture and its trust/correctness guarantees
  versus raw warehouse SQL (the LLM's SQL is never executed; RLS/CLS, Model joins/filters,
  governed metrics, custom calendars and multi-fact trap resolution are all applied
  deterministically). See `references/architecture.md`.

The one requirement is below: the Model must be backed by an external cloud data warehouse.

> **AgentQL requires an external cloud data warehouse.** The AgentQL endpoints only work on
> Models backed by Snowflake / Databricks / BigQuery / etc. A Model over Falcon, imported
> data, or system data (`DEFAULT` datasource) is rejected with *"This API only supports
> external cloud data warehouses"*. If you hit that, the Model isn't queryable via AgentQL —
> say so plainly.

## Learn AgentQL — a guided course

**New to AgentQL, or need to explain and demo it?** This skill includes a hands-on course.
It shows how to write AgentQL, what the two APIs do, and the exact SQL ThoughtSpot sends to
the warehouse. Built first for SEs and other technical field staff. Anyone who reads SQL
can take it.

**Start it** by asking, in Claude Code or Cortex Code:

> teach me AgentQL

You can also run `/ts-object-model-agentql-query teach me AgentQL`, or be specific: *"teach
me AgentQL, just modules 1 and 2"*, *"start at module 5"*.

**You need** a ThoughtSpot profile (set one up with `/ts-profile-thoughtspot`). There is no
Model to prepare: the course runs on **`(Sample) Retail - Apparel`**, the sample Model
every cluster ships with, and finds it by name.

**How a lesson runs.** The agent states a question and **shows you the AgentQL**, ready to
run, so you never get stuck on syntax. It asks one quick prediction, such as "which tables
will this touch?". Answer it, or just say **"run it"**. It runs `generate-sql` and
`fetch-data` live, walks through the SQL ThoughtSpot generated, then breaks the query on
purpose to show a rule. If you want practice, write your own version first and it will run
that instead.

**Live or offline.** At the start the agent asks which mode you want:
- **Live** (default) — real `ts agentql` calls on a cluster: fresh SQL and rows. Needs a
  profile and the sample Model. Best for a demo or to check current behaviour.
- **Offline** — everything is read from **[references/agentql-offline.md](references/agentql-offline.md)**,
  a single generated bundle of the whole reference library (every rule, pattern, limitation
  and lesson, with the captured SQL). **No cluster, no live calls, far lower token spend.**
  Result *numbers* aren't live, so offline teaches the SQL and the behaviour, not a fresh
  figure. Best for reading and review, when there's no cluster, or to keep token spend down.

| Module | What you learn | Questions |
|---|---|---|
| 0. Why AgentQL | ThoughtSpot compiles AgentQL to warehouse SQL and never runs it itself; the Model supplies joins, formulas and security | concept |
| 1. The two APIs | `generate-sql` vs `fetch-data`, structured errors, a query that compiles but fails, reading result types, why it can only read (writes, DDL and injection are refused) | 5 |
| 2. First queries | reading the SQL ThoughtSpot writes: joins written for you, null handling, the row cap, formulas inlined, the lenient parser, the bare-measure trap | 8 |
| 3. The semantic layer | ratios and safe division, what `AVG` averages, which tables a query reads, formula measures (`AGG`, not `SUM`) on a Model you choose, security you never write, every member via an outer join and the business rules in the generated SQL | 6 |
| 4. Dates and functions | date parts, relative dates without `CURRENT_DATE`, date literals, string functions, `CASE` buckets | 5 |
| 5. Advanced shapes | CTEs, ranking and share of total, top N per group, year over year, set operations | 6 |
| 6. Trust, but verify | queries that return `SUCCESS` with the wrong number, and the control queries that catch them | 4 |
| 7. Building on it | consuming results in code, testing an agent that writes AgentQL | 3 |

37 questions in all; each module stands alone after Module 2. The course itself is
[references/learning-path.md](references/learning-path.md).

**Is the course still accurate on your cluster?** Every lesson claim is a retest case:
`python3 tools/agentql-retest/run.py --profile <profile> --suite lessons` runs them all and
lists any lesson whose behaviour has changed.

---

## References

| File | When to read it |
|---|---|
| [references/architecture.md](references/architecture.md) | **The "why".** What actually executes (ThoughtSpot compiles AgentQL → deterministic warehouse SQL; the LLM's SQL is never run) and the value prop vs raw DB SQL — RLS/CLS, Model joins/filters, governed metrics/LOD/semi-additive, custom calendars, multi-fact chasm/fan-trap resolution. Read when asked "what's the point of AgentQL?" or "is this safe to trust?". |
| [references/agentql-rules.md](references/agentql-rules.md) | **Always, before writing AgentQL.** The hard constraints + dialect rules that make a statement valid (single-Model `FROM`, mandatory aliases, the literal-arithmetic trap, etc.). |
| [references/udf-reference.md](references/udf-reference.md) | Any question involving dates/time, ranking, or statistics — the AgentQL UDF catalogue (use these instead of `DATE_TRUNC`/`NOW()`/etc.). |
| [references/patterns.md](references/patterns.md) | Complex shapes: last-N-periods, year-over-year, top-N / top-N-per-group, period-over-period, anomaly detection. |
| [references/limitations.md](references/limitations.md) | **What AgentQL can't do** — hard-unsupported constructs, silent wrong-answer traps (e.g. `QUALIFY` and `FILTER (WHERE …)` are dropped), and what's been *fixed* on current builds. Read before telling a user something can't be done, and for the known-limitation-retest use case. |
| [references/snowflake-sv-backing.md](references/snowflake-sv-backing.md) | **Snowflake Semantic View backing** (EXPERIMENTAL) — rules R1–R7 for SV-backed Models: the `100072` NULL-key bug, window-via-CTE, no `FROM`-subqueries, the measure-statistics trap, and Databricks MV comparison. Read when the Model's warehouse object is an SV. |
| [references/learning-path.md](references/learning-path.md) | **The user wants to *learn* AgentQL** ("teach me AgentQL", "how does this work", "I need to demo it"). A guided, live course on `(Sample) Retail - Apparel`, the sample Model on every cluster: each lesson writes AgentQL, predicts the SQL, runs both APIs and breaks the query on purpose. Run it lesson by lesson instead of the normal flow. |
| [references/beyond-keywords.md](references/beyond-keywords.md) | **Worked examples of questions that need AgentQL — and ones it still can't answer.** Four live-verified cases (rank within a partition, a preceding-N-days window, a cohort semi-join, an unsupported percentile), each shown in the six-section output block. Read for "why not just use search?", for a demo, or before telling a user a question can or can't be done. |
| [references/use-cases.md](references/use-cases.md) | When the user wants to *build on* this skill — tutorial, agent building-block, accuracy/regression/feature/limitation testing. |
| [references/integration.md](references/integration.md) | When the user wants to call AgentQL directly from their own product/agent — auth options, the callosum endpoints, request bodies, the raw columnar response format and a parser. |
| [references/open-items.md](references/open-items.md) | Verification status of the API behaviour this skill relies on. |
| [references/agentql-offline.md](references/agentql-offline.md) | **The whole reference library as one offline document** — every file above, bundled. Read this (or hand it to an agent) to review everything in one place, or to run the skill/course **offline** with no live `ts agentql` calls and lower token spend. Generated from the sources by `tools/validate/generate_agentql_offline.py`; do not edit by hand. |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | If no ThoughtSpot profile is configured yet. |

---

## Prerequisites

- A ThoughtSpot profile — run `/ts-profile-thoughtspot` if none exists.
- The `ts` CLI (`pip install -e tools/ts-cli`), version **0.31.0+** (provides `ts agentql`,
  including `ts agentql classify-columns` for Step 2).
- The target Model is backed by an **external cloud data warehouse** (see the note above).

All ThoughtSpot calls go through the `ts` CLI, which handles auth, token caching, and the
keychain — never construct API requests directly.

---

## Flow

Pick the depth from how the user framed the request:

- **Business question** ("what were sales by region last quarter?") → run the flow, then
  show **the answer table**. Keep AgentQL and warehouse SQL out of the way unless asked.
- **Developer / learning** ("show me the AgentQL", "what SQL does this generate?", "I'm
  integrating this") → show every artifact: the AgentQL you wrote, the warehouse SQL, the
  rows, and the raw JSON the commands emit.
- **Learning the capability** ("teach me AgentQL", "walk me through how it works") → follow
  [references/learning-path.md](references/learning-path.md) instead of this flow. It sets
  the Model, the lesson order and the predict-then-run loop.

### Step 1 — Pick the profile and the Model

If multiple profiles exist in `~/.claude/thoughtspot-profiles.json`, ask which to use, then
confirm it authenticates:

```bash
ts auth whoami --profile "{profile}"
```

**Always ask the user which Model to query.** Accept any of these — you do not need a name
to search for if you already have an identifier:

- **A GUID** — use it directly as `{model_guid}`.
- **A ThoughtSpot URL** — extract the GUID from the path. Users often have the Model open in
  a browser, e.g. `…/#/data/tables/4da3a07f-…` or `…/#/data/embrace/4da3a07f-…` — the GUID
  is the path segment after `tables/` / `embrace/`.
- **A name, or nothing** — fall back to search and let the user pick:

  ```bash
  ts metadata search --subtype WORKSHEET --name "%{search}%" --profile "{profile}"
  ```

  Present matches with **name + GUID + owner + modified date** so the user can disambiguate.

Models are `LOGICAL_TABLE` with header `type: WORKSHEET`. Whichever path you took, **confirm
the resolved Model display name** back to the user — you need it verbatim for the `FROM`
clause in Step 3.

### Step 2 — Learn the schema

Export the Model's TML to see its columns:

```bash
ts tml export {model_guid} --profile "{profile}"
```

The TML body is in the `edoc` field. It is a structured document — JSON or YAML depending on
build (`yaml.safe_load` parses both; `ts tml export … --parse` returns it already parsed).
For a Model it is rooted at `model:` with these parts:

- **`model.columns[]`** — each entry's `name` is the identifier to use in AgentQL. Matching
  is case-insensitive, but copy the spelling. The column kind is at **`properties.column_type`** (ATTRIBUTE or
  MEASURE) — note it is **nested under `properties`**, not a direct child of the column.
- **`model.formulas[]`** — formula definitions. A formula column references one by carrying a
  **`formula_id`** that matches a `formulas[].id`; that formula's **`expr`** is where the
  aggregation logic lives.

**Classify every column** — this drives the `SUM`-vs-`AGG` decision in Step 3. Don't
eyeball the TML for this: run

```bash
ts agentql classify-columns --model {model_guid} --profile "{profile}"
```

This calls the same aggregate-function detector `ts-object-answer-promote` uses (BL-087 —
one canonical keyword list, not two drifted copies), applied to every `model.columns[]`
entry. It returns a JSON array of `{name, column_type, kind, needs_agg, aggregation, wrapper}`.
The `wrapper` field is the directly-actionable output — the AgentQL function to wrap a
reference to that column in (or `None` for attributes):

| `kind` | Meaning | How it was detected | In AgentQL (`wrapper`) |
|---|---|---|---|
| `attribute` | `properties.column_type: ATTRIBUTE` | — | group by it (`None`) |
| `raw_measure` | `properties.column_type: MEASURE`, **no** aggregating formula (a plain `column_id`, or a `formula_id` whose `expr` has no aggregate) | `needs_agg: false` | `SUM`/`AVG`/`MIN`/`MAX` (`aggregation` field names which) |
| `aggregate_measure` | `properties.column_type: MEASURE` **and** its `formulas[].expr` contains an aggregate | `needs_agg: true` | **`AGG(...)`** — never `SUM` (errors `NESTED_AGGREGATE_NOT_SUPPORTED`) |
| `semiadditive_measure` | aggregate-formula whose **outermost** call is `last_value`/`first_value` (the `last_value(sum(col), query_groups(), {date})` snapshot form) | `needs_agg: false`, `wrapper: SUM` | **`SUM(...)`** — `AGG(...)` errors `NON_CONVERTIBLE_FUNCTION` (see below) |

**Semi-additive is the one inversion of the aggregate-formula rule.** A measure whose
outermost op is `last_value`/`first_value` cannot use `AGG(...)` — the AgentQL→SQL
serializer can't emit its `query_groups()` and fails with `NON_CONVERTIBLE_FUNCTION`
("Non standard sql function QueryGroups"). Wrap it in `SUM(...)` instead: that forces a
per-group materialisation that resolves `query_groups()` and passes the already-collapsed
snapshot value through unchanged (verified at grand-total, grouped, and time-series
grain). The trigger is the **outermost** op only — `sum(last_value(...))` is a normal
`aggregate_measure` (use `AGG`; an extra `SUM` double-aggregates → `NESTED_AGGREGATE`).

Match each column you plan to use in Step 3 against its `wrapper`/`kind` in this output —
do not re-derive the classification by reading the TML expr yourself. See
`agentql-rules.md` § Aggregation for the full rule and the "compile-it-to-check" probe if
a column is still ambiguous after classification. If TML export is FORBIDDEN, you lack
access to that Model — pick another or ask the user.

### Step 3 — Write the AgentQL

**Read `references/agentql-rules.md` first.** Then write one AgentQL statement for the
question. The essentials (full list in the rules file):

- `FROM "Model Display Name" AS "t1"` — the one Model only, always aliased.
- Every column reference alias-prefixed and double-quoted: `"t1"."Product Category"`.
- **Raw measures** get a real aggregate (`SUM` is the default): `SUM("t1"."Amount")`.
  **Aggregate-formula columns** (formula already contains `sum`/`count`/`group_aggregate`/
  `cumulative_*`/…) get **`AGG("t1"."# Employees")`** — never `SUM` (that errors
  `NESTED_AGGREGATE_NOT_SUPPORTED`). **Semi-additive columns** (`semiadditive_measure` —
  outermost op `last_value`/`first_value`) are the exception: wrap in **`SUM(...)`**, not
  `AGG` (which errors `NON_CONVERTIBLE_FUNCTION`). Just follow each column's `wrapper` from
  Step 2. Attributes go in `GROUP BY`. See `agentql-rules.md`.
  Alias only computed/aggregate expressions, in Title Case. Never alias a plain model column.
- **Never** `SELECT *`, `COUNT(*)`, or subqueries (`IN (SELECT …)` compiles but fails at
  execution — use the semi-join rewrite in `patterns.md`). Set operations and
  aggregate×literal arithmetic **work** on current builds — see the rules and
  `limitations.md` for the caveats.
- **Never** `QUALIFY` or `FILTER (WHERE …)` — both are silently dropped and return
  unfiltered numbers. Use `ROW_NUMBER()` in a CTE, and `SUM(CASE WHEN … THEN x ELSE 0 END)`.
- Results are **capped at 100,000 rows** (a larger `LIMIT` is silently lowered). Say so if
  the user wants a full extract; page with `LIMIT … OFFSET`.
- String `=` / `IN` are case-insensitive — spelling must match, case need not.
- Dates: use the AgentQL UDFs (`YEAR_NUMBER`, `DIFF_MONTH`, `START_OF_CURRENT_MONTH()`, …),
  never `DATE_TRUNC`/`NOW()`/`CURRENT_DATE`.

### Step 4 — Validate and get the warehouse SQL

```bash
ts agentql generate-sql '{spotql}' --model {model_guid} --profile "{profile}"
```

Returns JSON `{status, executable_sql, errors}`. If `status` is `SUCCESS`, `executable_sql`
is the warehouse SQL ThoughtSpot compiled — this is the "database SQL". If `status` is
anything else, read `errors[]` (e.g. `COLUMN_NOT_FOUND`, `QUERY_GEN_ERROR`), fix the AgentQL
against the rules, and retry. Do not execute a statement that failed validation.

### Step 5 — Execute

```bash
ts agentql fetch-data '{spotql}' --model {model_guid} --profile "{profile}"
```

Returns JSON `{status, columns, rows, errors}`. `columns` are `{index, type}` — AgentQL
returns per-query column GUIDs, not names, so columns are identified by SELECT ordinal.
You wrote the SELECT, so you know what each ordinal means: label them from your own column
list when you present results.

### Step 6 — Review

Present **every** question in the same six-section block, in this fixed order, so repeated
questions read consistently. This is the canonical output structure — the course
(`references/learning-path.md`) reports the same shape:

| Section | What goes here |
|---|---|
| **1. Question** | The business question in plain English. |
| **2. AgentQL Sent** | The exact AgentQL statement you wrote (Step 3). |
| **3. DB SQL Generated** | `executable_sql` from Step 4 — the warehouse SQL ThoughtSpot compiled. If `generate-sql` did not return `SUCCESS`, say so here and show nothing else in this section. |
| **4. Error & Explanation** | *Only if a `status` was not `SUCCESS`.* The code + `errors[].message`, the rule it maps to, and what you changed (or why it can't be answered). Omit the section entirely when both calls succeeded. |
| **5. Key Findings** | The one or two things this question teaches: a join the Model added, a type surprise (dates as numbers), a cap applied, a silent reparse. Keep it to what the SQL or rows actually show. |
| **6. Results** | `rows` from Step 5 rendered as a table, headers from your SELECT list (not `col0`/`col1`). This rendered table is *your* presentation of the JSON — the commands emit JSON; you make it readable. |

Depth still scales to the audience (top of this section): a non-technical asker may only
want **1**, **5** and **6**, while a developer wants all six. The order never changes — omit
a section, don't reorder.

**Request bodies (developer, optional add-on).** When the user wants to run the query
themselves, append the ready-to-paste API bodies after section 6, pre-filled with the
AgentQL and Model GUID. (See `references/integration.md` for auth and response parsing.)

```text
POST /callosum/v1/v2/data/spotql/generate-sql
{ "spotql_query": "<the AgentQL from Step 3>", "model_identifier": "<model_guid>" }

POST /callosum/v1/v2/data/spotql/fetch-data
{ "spotql_query": "<the AgentQL from Step 3>", "model_identifier": "<model_guid>" }
```

If the user wants the machine-readable form (for piping or their own code), give them the
raw JSON from Steps 4–5 — that is the building-block interface.

---

## Building on this skill

The six common uses — interactive tutorial, agent building-block, accuracy benchmarking,
functional regression testing, new-feature testing, and known-limitation retesting — are
all *compositions* over Steps 3–5 (write AgentQL → run → compare). They are documented in
[references/use-cases.md](references/use-cases.md), not implemented here: this skill stays
the single-question primitive so consumers can build suites on top of its JSON output
without re-deriving the query mechanics.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 2.12.0 | 2026-10-19 | **Consistent course messaging + determinism throughline.** Every course module now opens with three pinned lines shown verbatim — **Key takeaway**, **How determinism holds**, **Covers** — so the messaging is identical on every run instead of improvised; a new **Key takeaways** table at the top of `learning-path.md` collects them for review, with *how deterministic SQL is maintained* as the throughline (Model-defined join types in Module 2; AgentQL overriding the default join for all-members expressibility in Module 3; Gregorian/fiscal/custom-4-4-5 calendars resolved deterministically in Module 4; determinism ≠ correct intent in Module 6). SKILL.md intro replaced the SpotQL-rename banner with a clean determinism-forward definition (the `spotql` API identifiers remain in the integration reference). |
| 2.11.1 | 2026-10-19 | **Terminology: "Keyword Search" replaces "Token Search".** The positioning (Module 0, `architecture.md`, `beyond-keywords.md`) now calls ThoughtSpot's classic search experience **Keyword Search** and its query chips **keywords**, so the word *token* is reserved for AI token spend (and bearer-token auth) and no longer overloaded. Reference file `beyond-tokens.md` renamed to [`beyond-keywords.md`](references/beyond-keywords.md). No behaviour change; offline bundle regenerated. |
| 2.11.0 | 2026-10-16 | **Offline mode + a single-document bundle.** New generated reference [`agentql-offline.md`](references/agentql-offline.md) assembles the whole library (SKILL.md + every `references/*.md`) into one document — for reading/reviewing everything in one place, or handing to an agent as grounding. The course (and the normal flow) now offer **live vs offline**: offline works entirely from the bundle, with no live `ts agentql` calls and far lower token spend (result numbers aren't live). Built by `tools/validate/generate_agentql_offline.py` and gated against drift (`--check`) in pre-commit and CI. |
| 2.10.0 | 2026-10-14 | **Learn AgentQL positioning + business-rules showcase.** Module 0 rewritten as the Keyword-Search-vs-AgentQL positioning (keywords validate, AgentQL expresses; the expressibility↔determinism trade-off; valid SQL ≠ correct business logic), with an optional **three-query taster** — a governed base, expressibility with governance still applied, and a hard limit — so the point lands without working through every module. New lesson **3.6** — *every product including those with no sales* (a `LEFT OUTER JOIN` keywords can't express) — dissects the generated SQL to show the business rules the Model applies for you: `join_progressive` table pruning, Model-supplied inner joins + keys, null-guarded aggregates, a case-insensitive filter, the row cap, and where RLS is injected. Live-verified on `(Sample) Retail - Apparel`; guarded by `l3_all_products_left_join`. Course now 37 questions. |
| 2.9.0 | 2026-10-14 | **New reference: [`beyond-keywords.md`](references/beyond-keywords.md)** — four live-verified worked examples (26.9.0.cl) of questions that need AgentQL and ones it still can't answer: rank within a partition (window `RANK()` in a CTE, since `QUALIFY` is dropped), a preceding-7-days window (AgentQL frames count **rows**, not calendar days — no `RANGE … INTERVAL`), a cohort semi-join (`IN (SELECT …)` compiles then fails; CTE equi-join is the fix), and percentiles (`PERCENTILE_CONT` unsupported; `STDDEV` needs the CTE pattern, where **both** `STDDEV_POP` and `STDDEV_SAMP` work — not sample-only). Each rendered in the six-section block. Linked from the References table and as the course capstone. |
| 2.8.2 | 2026-10-14 | **Consistent per-question output.** Every question — in the main run flow (Step 6) and in every course lesson — now reports in the same fixed six-section block, in the same order: **1. Question · 2. AgentQL Sent · 3. DB SQL Generated · 4. Error & Explanation (if any) · 5. Key Findings · 6. Results**. Section 4 is omitted when the query succeeds; depth still scales to the audience, but the order never changes. |
| 2.8.1 | 2026-10-14 | Learn AgentQL: dropped the audience **tracks** in favour of a plain module list — each module with a one-line summary and its **number of questions** (36 in all). Module headings now show the count. |
| 2.8.0 | 2026-10-14 | **Read-only guards.** A new `guards` suite in `tools/agentql-retest` (26 cases + a positive control) covers statements AgentQL must always refuse: writes, DDL, admin (incl. `PUT`/`GET`/`UNDROP`/`EXECUTE IMMEDIATE`/`SHOW`), a second statement, and a physical table in `FROM`. It also checks that comments, `SELECT … INTO` and a `'; DROP` inside a literal compile to one regenerated `SELECT`. A guard that ever compiles to anything else is a new **BREACH** verdict (exit 3); guards never call `fetch-data`. The read-only check handles backslash and `$$` quoting. The suite's claim is scoped to *no writes or DDL*, not that a `SELECT` reads only the Model. New `limitations.md` § Read-only by design and Learn AgentQL lesson 1.5, "It can only read". |
| 2.7.1 | 2026-10-14 | Learn AgentQL: the agent now **shows each lesson's AgentQL ready to run** rather than asking the learner to write it ("Learner writes" → "Question"). This avoids syntax errors and keeps lessons quick. The SQL prediction is one quick optional question; "run it" skips it. Writing your own query stays available as practice. |
| 2.7.0 | 2026-10-14 | Learn AgentQL lesson 3.4 restored, now generic: **formula measures, `AGG` not `SUM`, on a Model the learner chooses**. The agent runs `ts agentql classify-columns`, picks an aggregate-formula measure, an attribute and (where one exists) a raw-measure control, and writes the question from their names. If the Model has no formula measures, it says so. The Break it step shows `SUM(formula)` → `NESTED_AGGREGATE_NOT_SUPPORTED`, `AGG(raw)` → `QUERY_GEN_ERROR`, and a bare formula measure compiling exactly like `AGG()`. Security moves back to 3.5. New retest cases: `AGG()` equals the raw SUM it wraps, a bare formula measure matches `AGG()`, and `AGG()` on a raw measure is rejected. |
| 2.6.1 | 2026-10-14 | Learn AgentQL: the `SUM` vs `AGG` lesson (3.4) is parked, because `AGG()` is not a released product feature. Former lesson 3.5 (security) is now 3.4. The skill's query rules are unchanged. |
| 2.6.0 | 2026-10-14 | **Learn AgentQL: modules 3–7 written** (the semantic layer, dates and functions, advanced shapes, trust but verify, building on it). The course now covers all eight modules, with tracks, and every claim is checked by the `lessons` suite (57 cases, up from 18). New **Learn AgentQL** section near the top of this file: what the course is, how to start it, the modules and tracks. Rules: `GROUP BY` accepts an output alias (`GROUP BY u`), and ordinals stay rejected. |
| 2.5.0 | 2026-10-14 | **Learn AgentQL pathway** (`references/learning-path.md`): a guided live course on `(Sample) Retail - Apparel`, the sample Model shipped on every cluster and found by exact name plus `system` author rather than a GUID. Modules 0–2 are written (why AgentQL, the two APIs, reading the SQL ThoughtSpot writes); 3–7 are outlined. Every lesson claim is checked by a new `lessons` suite in `tools/agentql-retest` (`--suite lessons`, needs no GUID). Rules corrected from the same probes: identifiers are **case-insensitive** (both the rules file and Step 2 said case-sensitive), a missing `GROUP BY` is filled in implicitly, and a bare raw measure returns row-level values, not the Model's default aggregation. |
| 2.4.0 | 2026-10-14 | Known-limitation retest suite (`tools/agentql-retest/`): one case per `limitations.md` row with controls and value checks, reporting only rows whose behaviour moved. `use-cases.md` #6 and the open-items refresh procedure now run it. Its first run corrected the ✅ `TO_NUMBER` row (typed by input: strings are cast, numeric columns are not). Also new: one-argument `LOG(x)` is the natural log (⚠️), and `ACOS(1)` works in isolation. |
| 2.3.1 | 2026-10-14 | Regex limitation (SCAL-338545) marked build- or cluster-dependent: it fails on Snowflake on 26.9.0.cl PROD for `~`, `!~` and `REGEXP_LIKE`, but the ticket records Snowflake compiling it correctly on a dev cluster, so re-probe before dropping the row. |
| 2.3.0 | 2026-10-14 | Limitation re-probe on **26.9.0.cl (PROD)** — the second build after jul.26.mt, ~80 live probes plus a Jira refresh of both epics. **Now working** (→ ✅, rules relaxed): framed-window-only queries, `LIMIT … OFFSET`, decimal literal arithmetic, `GREATEST`/`LEAST` varargs, constant labels, `NTILE`, `LAG`/`LEAD` offsets and defaults, multi-CTE and chained-CTE joins, `CASE` in `GROUP BY`, `CAST(<literal>)`, constant-only `EXP`/`CHR`/`SPACE`, `TO_DATE('<literal>')` filters, aggregates over CTE-unreferenced columns. **Still broken** on both builds: direct `STDDEV`/`VAR` (despite SCAL-314019 closed as fixed), `QUALIFY`/`FILTER` silently dropped, `IN (SELECT …)`, self/non-equi joins, `ROLLUP`, date-literal `SUM(CASE …)` (now characterised as a result-typing bug — the SQL is right). **Newly documented:** `REGEXP_LIKE`/`~` fails at fetch on Snowflake (SCAL-338545), outer aggregation over a set-op CTE fails (SCAL-330561), an explicit `LIMIT` over 100,000 is silently lowered, `DATE_TRUNC` fails at fetch rather than running silently, string `=`/`IN` are case-insensitive (the rule demanding exact case was wrong), dates return as epoch seconds. Stale claims removed from `udf-reference.md` (MEDIAN "scalar only", `LENGTH()` and literal arithmetic "forbidden", "no form for N rows back"). |
| 2.2.1 | 2026-08-08 | `snowflake-sv-backing.md`: add a do-not-adopt warning on the Snowflake **`SEMANTIC_VIEW` clause**. Snowflake advised 2026-08-08 that it is a **deprecated** solution, so it is no longer a capability upgrade to pursue and the previously-recommended "emit the clause" product ask is withdrawn. The clause description is retained only to explain why the `100072` bug occurs (column nullability). **R2 (`CASE`-wrap) is the recommended remediation** and is portable to Databricks. Open question on what replaces the clause for dimension-anchored aggregation is tracked in [SCAL-331033](https://thoughtspot.atlassian.net/browse/SCAL-331033). No rule or behaviour change. |
| 2.2.0 | 2026-07-29 | Full limitation re-probe on jul.26.mt (dev-cluster, 38 probes): set-op ORDER BY/LIMIT on the combined result, aggregated-branch CTE set-ops, `ROUND(x,N)`, `TO_NUMBER`, `CONCAT_WS`, `LENGTH()` and grouped `MEDIAN` all fixed → moved to ✅ in `limitations.md` and rules relaxed. Two new bugs filed and documented: scalar `STDDEV`/`VAR` regression ([SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935)) and `IN (SELECT …)` compiles-but-fails-at-fetch ([SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936)). New `patterns.md` § Semi-join via CTE (membership filters; dedupe-the-key fan-out guard). Fix stale Step 3 "no set operations / literal arithmetic zeros" line. |
| 2.1.0 | 2026-07-24 | Rename the CLI command **`ts spotql` → `ts agentql`** (and all skill/doc references to it). `ts spotql` still works as a deprecated hidden alias, so existing scripts don't break. The server contract is unchanged: the callosum `/data/spotql/*` endpoints and the `spotql_query` request field keep the `spotql` spelling. (ts-cli v0.95.0.) |
| 2.0.0 | 2026-07-24 | Rename the external product name **SpotQL → AgentQL** across the skill and every reference. Breaking: the skill directory and slash command are renamed `ts-object-model-spotql-query` → `ts-object-model-agentql-query` (re-point the `~/.claude/skills/` and `~/.snowflake/cortex/skills/` symlinks), and `references/spotql-rules.md` → `references/agentql-rules.md`. **No behaviour change:** the `ts spotql` CLI, the callosum endpoints, and the `spotql_query` request field are unchanged stable identifiers, so existing integrations and scripts keep working. |
| 1.5.0 | 2026-07-22 | Add `references/snowflake-sv-backing.md` — rules R1–R7 for Snowflake Semantic View-backed Models (NULL-key `100072` fix, window-via-CTE, no FROM-subqueries, measure-statistics trap) with Databricks MV comparison; new silent-wrong-answer row in `limitations.md` for secondary aggregates on SV/MV measures. Live-verified 2026-07-21 on `direct-query-cluster` + native Snowflake + Databricks. |
| 1.4.0 | 2026-07-13 | Semi-additive measures use `SUM(...)`, not `AGG(...)`: a measure whose outermost formula op is `last_value`/`first_value` errors `NON_CONVERTIBLE_FUNCTION` under `AGG()` and must be wrapped in `SUM()` (identity pass-through over the per-group snapshot). `ts spotql classify-columns` now returns this as `kind: semiadditive_measure` + a directly-actionable `wrapper` field (ts-cli v0.52.0). Corrects earlier docs that wrongly showed `AGG("Inventory Balance")` as verified. `sum(last_value(...))` (additive outer op) stays `AGG`. Live-verified at grand-total/grouped/monthly grain on nebula-aggregate-aware. |
| 1.3.2 | 2026-07-10 | Live-verified on nebula-spotQL (Supplier Model): `LEFT`/`RIGHT`/`FULL OUTER JOIN` between CTEs compile verbatim and execute correctly; an attribute-only CTE compiles to a dimension-only scan (no fact join). Together these bypass a Model's inner join without changing it — new `patterns.md` § Dimension-anchored anti-join ("customers without sales"). Fix stale patterns.md set-op-in-CTE notes to match the 1.3.1 finding. |
| 1.3.1 | 2026-07-08 | Fold in 2026-07 set-operator bug-hunt findings (live-verified on nebula-spotQL): correct CTE set-operation limitation — works when no branch contains an aggregate measure, only aggregated branches fail (engineering-confirmed); note `10000: Failed to transform QuerySpec: null` on outer re-aggregation (likely SCAL-318834); document aggregate-in-WHERE silently reparsed as HAVING; document set-op branch type mismatch compiling but failing at fetch-data. |
| 1.3.0 | 2026-07-03 | Column classification now delegates to `ts spotql classify-columns` (BL-087); single canonical aggregate-function list. Prereq ts-cli v0.31.0. |
| 1.2.0 | 2026-06-25 | Add `references/architecture.md` — the "why AgentQL" value proposition and architecture vs raw DB SQL (LLM SQL never executed; RLS/CLS, Model joins/filters, governed metrics/LOD/semi-additive, custom calendars, multi-fact chasm/fan-trap resolution; hybrid keyword/AgentQL NL flow with a unified verification layer across both transformers — co-existence + parity, not replacement). New capability bullet + References row linking it. |
| 1.1.1 | 2026-06-25 | Correct compilation attribution: ThoughtSpot (not the skill/agent) compiles AgentQL to warehouse SQL, deterministically; clarify in the intro and capability summary. |
| 1.1.0 | 2026-06-25 | Add `references/integration.md` (raw AgentQL API for non-CLI consumers); Step 6 emits paste-ready request bodies; fix Step 2 TML parsing (`properties.column_type`, `formulas[]` via `formula_id`) with deterministic raw-vs-aggregate-formula classification; add capability summary; Step 1 accepts Model GUID/URL with search as fallback. |
| 1.0.0 | 2026-06-25 | Initial release — query a Model with AgentQL via `ts spotql`; generate-sql + fetch-data + review. |
