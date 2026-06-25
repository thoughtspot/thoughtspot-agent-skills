---
name: ts-object-model-spotql-query
description: Ask a question of a ThoughtSpot Model and get the answer as data — write SpotQL (Semantic SQL), validate it to warehouse SQL, execute it, and review the results. Use this whenever someone wants to query a ThoughtSpot Model with SpotQL, turn a natural-language question into SpotQL, see the SQL ThoughtSpot generates for a question, pull rows from a Model programmatically, learn how the SpotQL APIs behave, or build a question set to accuracy-test / regression-test / feature-test SpotQL. Triggers on "query this model", "ask the model", "run SpotQL", "what SQL does ThoughtSpot generate", "get the data for…", even when SpotQL isn't named explicitly.
---

# ThoughtSpot: Query a Model with SpotQL

Turn a question about a ThoughtSpot **Model** into an answer. You (the agent) write a
SpotQL statement grounded in the rules in `references/`, then run it through two `ts`
commands: `generate-sql` (compiles it to warehouse SQL and validates) and `fetch-data`
(executes it and returns rows). The result is a **review** the user can inspect at the
level they care about — the data table, the SpotQL, the warehouse SQL, or the raw JSON.

This skill is the **primitive**. It is the foundation other things build on: an
onboarding tutorial, a drop-in for your own agent, or the per-question engine of an
accuracy / regression / feature test suite. See `references/use-cases.md` for those
compositions — they are *uses* of this skill, not built into it.

> **SpotQL requires an external cloud data warehouse.** The SpotQL endpoints only work on
> Models backed by Snowflake / Databricks / BigQuery / etc. A Model over Falcon, imported
> data, or system data (`DEFAULT` datasource) is rejected with *"This API only supports
> external cloud data warehouses"*. If you hit that, the Model isn't queryable via SpotQL —
> say so plainly.

---

## References

| File | When to read it |
|---|---|
| [references/spotql-rules.md](references/spotql-rules.md) | **Always, before writing SpotQL.** The hard constraints + dialect rules that make a statement valid (single-Model `FROM`, mandatory aliases, the literal-arithmetic trap, etc.). |
| [references/udf-reference.md](references/udf-reference.md) | Any question involving dates/time, ranking, or statistics — the SpotQL UDF catalogue (use these instead of `DATE_TRUNC`/`NOW()`/etc.). |
| [references/patterns.md](references/patterns.md) | Complex shapes: last-N-periods, year-over-year, top-N / top-N-per-group, period-over-period, anomaly detection. |
| [references/limitations.md](references/limitations.md) | **What SpotQL can't do** — hard-unsupported constructs, silent wrong-answer traps (e.g. `UNION` drops a branch), and what's been *fixed* on current builds. Read before telling a user something can't be done, and for the known-limitation-retest use case. |
| [references/use-cases.md](references/use-cases.md) | When the user wants to *build on* this skill — tutorial, agent building-block, accuracy/regression/feature/limitation testing. |
| [references/integration.md](references/integration.md) | When the user wants to call SpotQL directly from their own product/agent — auth options, the callosum endpoints, request bodies, the raw columnar response format and a parser. |
| [references/open-items.md](references/open-items.md) | Verification status of the API behaviour this skill relies on. |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | If no ThoughtSpot profile is configured yet. |

---

## Prerequisites

- A ThoughtSpot profile — run `/ts-profile-thoughtspot` if none exists.
- The `ts` CLI (`pip install -e tools/ts-cli`), version **0.13.0+** (provides `ts spotql`).
- The target Model is backed by an **external cloud data warehouse** (see the note above).

All ThoughtSpot calls go through the `ts` CLI, which handles auth, token caching, and the
keychain — never construct API requests directly. Prefix `ts` calls with
`source ~/.zshenv &&` so environment variables resolve.

---

## Flow

Pick the depth from how the user framed the request:

- **Business question** ("what were sales by region last quarter?") → run the flow, then
  show **the answer table**. Keep SpotQL and warehouse SQL out of the way unless asked.
- **Developer / learning** ("show me the SpotQL", "what SQL does this generate?", "I'm
  integrating this") → show every artifact: the SpotQL you wrote, the warehouse SQL, the
  rows, and the raw JSON the commands emit.

### Step 1 — Pick the profile and the Model

If multiple profiles exist in `~/.claude/thoughtspot-profiles.json`, ask which to use, then
confirm it authenticates:

```bash
source ~/.zshenv && ts auth whoami --profile "{profile}"
```

**Always ask the user which Model to query.** Accept any of these — you do not need a name
to search for if you already have an identifier:

- **A GUID** — use it directly as `{model_guid}`.
- **A ThoughtSpot URL** — extract the GUID from the path. Users often have the Model open in
  a browser, e.g. `…/#/data/tables/4da3a07f-…` or `…/#/data/embrace/4da3a07f-…` — the GUID
  is the path segment after `tables/` / `embrace/`.
- **A name, or nothing** — fall back to search and let the user pick:

  ```bash
  source ~/.zshenv && ts metadata search --subtype WORKSHEET --name "%{search}%" --profile "{profile}"
  ```

  Present matches with **name + GUID + owner + modified date** so the user can disambiguate.

Models are `LOGICAL_TABLE` with header `type: WORKSHEET`. Whichever path you took, **confirm
the resolved Model display name** back to the user — you need it verbatim for the `FROM`
clause in Step 3.

### Step 2 — Learn the schema

Export the Model's TML to see its columns:

```bash
source ~/.zshenv && ts tml export {model_guid} --profile "{profile}"
```

The TML body is in the `edoc` field. It is a structured document — JSON or YAML depending on
build (`yaml.safe_load` parses both; `ts tml export … --parse` returns it already parsed).
For a Model it is rooted at `model:` with these parts:

- **`model.columns[]`** — each entry's `name` is the **exact** identifier you must use in
  SpotQL (case-sensitive). The column kind is at **`properties.column_type`** (ATTRIBUTE or
  MEASURE) — note it is **nested under `properties`**, not a direct child of the column.
- **`model.formulas[]`** — formula definitions. A formula column references one by carrying a
  **`formula_id`** that matches a `formulas[].id`; that formula's **`expr`** is where the
  aggregation logic lives.

**Classify every column** — this drives the `SUM`-vs-`AGG` decision in Step 3:

| Column | How to tell | In SpotQL |
|---|---|---|
| **Attribute** | `properties.column_type: ATTRIBUTE` | group by it |
| **Raw measure** | `properties.column_type: MEASURE`, **no** aggregating formula (a plain `column_id`, or a `formula_id` whose `expr` has no aggregate) | `SUM`/`AVG`/`MIN`/`MAX` |
| **Aggregate-formula measure** | `properties.column_type: MEASURE` **and** its `formulas[].expr` contains an aggregate — `sum`, `count`, `group_aggregate`, `last_value`, `first_value`, … | **`AGG(...)`** — never `SUM` (errors `NESTED_AGGREGATE_NOT_SUPPORTED`) |

See `spotql-rules.md` § Aggregation for the full rule and the "compile-it-to-check" probe if
a column is ambiguous. If TML export is FORBIDDEN, you lack access to that Model — pick
another or ask the user.

### Step 3 — Write the SpotQL

**Read `references/spotql-rules.md` first.** Then write one SpotQL statement for the
question. The essentials (full list in the rules file):

- `FROM "Model Display Name" AS "t1"` — the one Model only, always aliased.
- Every column reference alias-prefixed and double-quoted: `"t1"."Product Category"`.
- **Raw measures** get a real aggregate (`SUM` is the default): `SUM("t1"."Amount")`.
  **Aggregate-formula columns** (formula already contains `sum`/`count`/`group_aggregate`/
  `last_value(...)`) get **`AGG("t1"."# Employees")`** — never `SUM` (that errors
  `NESTED_AGGREGATE_NOT_SUPPORTED`). Attributes go in `GROUP BY`. See `spotql-rules.md`.
  Alias only computed/aggregate expressions, in Title Case. Never alias a plain model column.
- **Never** `SELECT *`, `COUNT(*)`, subqueries, set operations, or arithmetic between an
  aggregate and a numeric literal (it silently returns zeros — see the rules).
- Dates: use the SpotQL UDFs (`YEAR_NUMBER`, `DIFF_MONTH`, `START_OF_CURRENT_MONTH()`, …),
  never `DATE_TRUNC`/`NOW()`/`CURRENT_DATE`.

### Step 4 — Validate and get the warehouse SQL

```bash
source ~/.zshenv && ts spotql generate-sql '{spotql}' --model {model_guid} --profile "{profile}"
```

Returns JSON `{status, executable_sql, errors}`. If `status` is `SUCCESS`, `executable_sql`
is the warehouse SQL ThoughtSpot compiled — this is the "database SQL". If `status` is
anything else, read `errors[]` (e.g. `COLUMN_NOT_FOUND`, `QUERY_GEN_ERROR`), fix the SpotQL
against the rules, and retry. Do not execute a statement that failed validation.

### Step 5 — Execute

```bash
source ~/.zshenv && ts spotql fetch-data '{spotql}' --model {model_guid} --profile "{profile}"
```

Returns JSON `{status, columns, rows, errors}`. `columns` are `{index, type}` — SpotQL
returns per-query column GUIDs, not names, so columns are identified by SELECT ordinal.
You wrote the SELECT, so you know what each ordinal means: label them from your own column
list when you present results.

### Step 6 — Review

Present the result at the depth from the top of this section:

- **Answer (always):** render `rows` as a table, with headers from your SELECT list (not
  `col0`/`col1`). This rendered table is *your* presentation of the JSON — the commands
  emit JSON; you make it readable.
- **🧠 Generated SpotQL** (developer): the statement you wrote.
- **🗄️ Warehouse SQL** (developer): `executable_sql` from Step 4.
- **📋 Request bodies** (developer): the ready-to-paste API bodies for the session's query,
  pre-filled with the SpotQL you wrote and the Model GUID — so the user can run it from the
  REST playground or their own code. (See `references/integration.md` for auth and response
  parsing.)

  ```text
  POST /callosum/v1/v2/data/spotql/generate-sql
  { "spotql_query": "<the SpotQL from Step 3>", "model_identifier": "<model_guid>" }

  POST /callosum/v1/v2/data/spotql/fetch-data
  { "spotql_query": "<the SpotQL from Step 3>", "model_identifier": "<model_guid>" }
  ```
- **❌ Errors:** if any `status` was not `SUCCESS`, show the code + message and what you
  changed (or why it can't be answered).

If the user wants the machine-readable form (for piping or their own code), give them the
raw JSON from Steps 4–5 — that is the building-block interface.

---

## Building on this skill

The six common uses — interactive tutorial, agent building-block, accuracy benchmarking,
functional regression testing, new-feature testing, and known-limitation retesting — are
all *compositions* over Steps 3–5 (write SpotQL → run → compare). They are documented in
[references/use-cases.md](references/use-cases.md), not implemented here: this skill stays
the single-question primitive so consumers can build suites on top of its JSON output
without re-deriving the query mechanics.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-25 | Initial release — query a Model with SpotQL via `ts spotql`; generate-sql + fetch-data + review. |
