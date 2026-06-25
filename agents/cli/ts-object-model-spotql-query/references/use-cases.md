# Building on this skill

This skill is the **SpotQL query primitive**: write SpotQL → `ts spotql generate-sql`
(warehouse SQL) → `ts spotql fetch-data` (rows). Each command emits JSON, so anything that
needs to run many questions and compare results is a thin loop over this primitive — not a
separate tool. The six common uses below are *compositions*, documented here rather than
built into the skill, so the skill stays small and a consumer (a future
agent-expressibility-eval, a CI job, your own agent) builds the suite layer it needs.

The composable unit is one record per question:

```json
{"question": "...", "spotql": "...", "executable_sql": "...",
 "status": "SUCCESS", "columns": [...], "rows": [...], "errors": []}
```

— the agent supplies `question`/`spotql`; the two `ts spotql` calls supply the rest.

## 1. Introductory tutorial

Walk a learner from a question to data and show how the SpotQL APIs behave. Use the
developer depth from `SKILL.md`: for one question, show the SpotQL you wrote, the warehouse
SQL from `generate-sql`, and the rows from `fetch-data` rendered as a table. Good first
questions on a sales-style Model: "total by category", "top 10 by amount", "this year vs
last year". Deliberately show one rejected query (e.g. `SELECT *`) so the learner sees the
structured error and the rule it maps to.

## 2. Drop-in for your own agent

Reuse the primitive directly: `ts spotql generate-sql` / `fetch-data` return JSON your code
consumes. The generation rules in `spotql-rules.md` + `udf-reference.md` + `patterns.md` are
the grounding to give your own model when it writes SpotQL. Start from this skill's flow and
keep or replace the presentation layer.

## 3. Accuracy benchmarking

Author a question set with an **expected answer** per question, run each through
`fetch-data`, and compare `rows` to the expectation.

```yaml
# accuracy-set.yaml
- question: total sales by category
  spotql: 'SELECT "t1"."Product Category", SUM("t1"."Amount") AS "Total Sales" FROM "M" AS "t1" GROUP BY "t1"."Product Category"'
  expect: { row_count: 8, contains_row: ["Printer Paper", 254889363.83] }
```

Loop: run `fetch-data`, assert `status == SUCCESS`, assert the expectation. Report pass/fail
per question. (Heavier graded evaluation — LLM-as-judge, multi-agent comparison — belongs in
agent-expressibility-eval, which can call this primitive per question.)

## 4. Functional / regression testing

Same machinery, but the baseline is a **saved prior result**, not a hand-written
expectation. Capture each question's record once (the JSON above) as a baseline; on re-run,
diff the new `rows` / `executable_sql` against the baseline and flag drift. Run it after a
ThoughtSpot upgrade to catch behavioural regressions.

## 5. New-feature testing

Add questions that exercise a newly shipped SpotQL function or capability; confirm they now
return `SUCCESS` with correct data. The question set grows as features ship.

## 6. Known-limitation retesting

Keep a set of questions for things SpotQL currently can't do (set operations, `NTILE`,
`PERCENTILE_CONT`, rolling frames — see `spotql-rules.md`), each tagged with its expected
failure. Re-run periodically; when one starts returning `SUCCESS`, the limitation has been
resolved — promote it out of the known-limitations set and into the functional set.

---

**Two more that fall out of the same machinery:**

- **Golden warehouse-SQL capture** — snapshot `executable_sql` per question and diff on
  re-run to detect when ThoughtSpot's SpotQL→SQL *compiler* changes, independent of the
  data values (a different signal than row-level regression).
- **Cross-model / cross-cluster parity** — run the same question against two Models or two
  clusters (two `--model` / `--profile` values) and diff the results — useful for validating
  a migrated Model answers like its source.
