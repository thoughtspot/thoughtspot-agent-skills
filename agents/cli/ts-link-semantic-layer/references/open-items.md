# Open Items

Findings from building this skill against the `nebula-ts-semview` cluster (DBX, SF and HD
Orgs), 2026-09-28. Status vocabulary: `OPEN | VERIFIED | DEFERRED | WONT-FIX`.

## 1 — Databricks Metric View, `aggregate` mode, end to end — VERIFIED 2026-09-28

`agent_skills.business_forecast.business_reporting_mv` (22 dimensions, 136 measures) was
linked in the DBX Org: Table `39570acf-7364-4860-a1c4-599c4a9d75b3`, Model
`3fee09f8-35a8-49cd-8a84-777b83d694a6`. AgentQL compiled measures to `MEASURE(col)`, and
`py_monthly_revenue_gbp` (a window measure with a subquery, which `ts databricks parse-mv`
rejects) returned the correct prior-year values. `ts link build` itself was then run end to
end against `dunder_mifflin_inventory_mv`: Table and Model created, `coerced: []`, a grouped
query matched Databricks exactly, and `ai/instructions/set` then `get` round-tripped. Those
test objects were deleted.

Also verified the same day:

- A DATE measure cannot be a MEASURE: import coerces it to ATTRIBUTE, and every query
  shape then fails with `METRIC_VIEW_MISSING_MEASURE_FUNCTION`. The builder skips it.
- A second Table over the same `connection/db/schema/db_table` is refused, with the
  existing GUID in the message. The command reports it as `existing_table_guid`.
- TML `model_instructions` is not persisted by import and not returned by export; the API is
  the only path (BL-030).

**Status: VERIFIED 2026-09-28.**

## 2 — Honeydew, Cube and Kyvos spec extraction — DEFERRED

The skill does not say how to read these platforms' metadata; it asks the user for the
metric and attribute list. The Snowflake SV spec path was verified against the hand-built
SF Org Table (31 of 31 columns identical in role, aggregation and data type). The HD Org's
hand-built Table shows Honeydew exposes `entity.field` column names and that its
descriptions carry `Expression: SUM(...)`, but not every metric's description does
(`quantity`, `unit_price` have none), so `standard` mode needs explicit aggregations from
Honeydew itself.

Resolve by reading the metadata from each platform's API once a connection is available,
then add a row to SKILL.md Step 4.

**Status: DEFERRED — until live access to each platform.**

## 3 — Aggregation mode for Cube and Kyvos — DEFERRED

Whether Cube and Kyvos accept `AGGREGATE` (platform measure function) or need `standard`
is being tested by the user. Until then Step 3 tells the agent to ask.

**Status: DEFERRED — user testing in progress (2026-09-28).**

## 4 — `COUNT_DISTINCT` on a physical column — DEFERRED

`thoughtspot-model-tml.md` documents that `aggregation: COUNT_DISTINCT` on a `column_id`
silently turns the column into an ATTRIBUTE. The hand-built HD Org Model carries exactly
that (`Employee Count`, MEASURE / COUNT_DISTINCT) without being coerced. The command's
post-import re-export (`coerced`) detects the coercion either way, so a wrong answer cannot
go unreported; what is unknown is whether it happens. Resolve on the first `standard`-mode
link with a distinct-count metric.

**Status: DEFERRED — detected at run time by the `coerced` check.**

## 5 — Does `ai/instructions/set` replace or append? — DEFERRED

Only a set on a Model with no prior instructions was tested. Irrelevant while the skill only
creates new Models; it matters for re-linking (BL-318), which must `get` and merge first.

**Status: DEFERRED — with BL-318.**

## 6 — Snowflake Semantic View facts — VERIFIED 2026-10-05

A Semantic View `FACT` (`GROSS_PROFIT AS gross - costs`) has no aggregation of its own, and
`DESCRIBE` returns only its table, expression, data type and access modifier. Verified on a
scratch view in `AGENT_SKILLS.PUBLIC` (4 rows; truth East 90 / West 20 / total 110) with three
Models in the SF Org of `nebula-ts-semview`, one per marking of the fact:

| Fact marked | UI search | Why |
|---|---|---|
| `MEASURE` + `AGGREGATE` | **Every search failed** — *Unsupported feature 'AGG'* | Snowflake rejects `AGG()` on a fact; ThoughtSpot rewrites even an explicit `SUM`/`AVG` to `AGG()` |
| `MEASURE` + `SUM` | All correct, including fact + metric in one search (90/300, 20/130) | |
| `ATTRIBUTE` | Row-level values; `[Gross Profit]` alone returns distinct values, not a total | |

`default_aggregation` on a fact is accepted in YAML (`SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`)
and survives in `GET_DDL` / `SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW`, but only inside the Cortex
Analyst extension (`with extension (CA='…')`). It is not in `DESCRIBE` or `SHOW SEMANTIC FACTS`,
and it changes no SQL: with `default_aggregation: avg`, `SUM(fact)` still sums and `AGG(fact)`
still fails. A Model marking that fact `SUM` answered 90/20 for `[Gross Profit]` and 45/10 for
`average [Gross Profit]` — so ThoughtSpot runs what it sends, and copying the declared default
is what keeps its default answer equal to Cortex Analyst's.

`ts link build` (ts-cli 0.154.0) takes `kind: fact`: never `AGGREGATE`, declared aggregation
else `SUM`. All scratch objects were deleted. Regression coverage: querygen
`tests/SIMBA/snowflake/facts/` (21 cases).

**Status: VERIFIED 2026-10-05.**

## 7 — SpotQL cannot mix `AGG()` with a standard aggregate — DEFERRED (product)

On a linked model, any SpotQL query combining `AGG(metric)` with `SUM`/`AVG`/`COUNT` of
another column is planned as two levels: the inner query selects the `AGGREGATE` column raw
and **groups by it**, and the outer re-aggregates. Grouping by a metric is never valid —
Snowflake rejects it (*Requested semantic expression … in DIMENSIONS clause must be one of
the following types: (DIMENSION, FACT)*), and the same plan appears on Databricks
(`COUNT(attr) + AGG(measure)` groups by the raw measure column). Isolated 2026-10-06:

| SpotQL | Plan |
|---|---|
| `AGG(metric)` alone; `SUM(fact)` alone; fact as a group key + `AGG(metric)` | single level, valid |
| `SUM(fact) + AGG(metric)` (either order, with or without `GROUP BY`); `COUNT(attr) + AGG(metric)` | two levels, invalid |
| `AVG(fact) + AGG(metric)` | two levels, **and the outer function is `sum`** — the requested average is lost |

UI search is not affected: it plans from each column's own aggregation at one grain, and a
fact + metric search returns the right numbers. This is a query-gen bug, not something the
skill can work around beyond telling the user not to mix the two in one SpotQL query (Step 7).
Pinned as `known-product-bug` in querygen `tests/SIMBA/snowflake/facts/` (PR #150).

**Status: DEFERRED — fix belongs to the semantic-SQL query-gen change.**

## 8 — AgentQL reads a measure's aggregation from the Table, search from the Model — VERIFIED 2026-10-07

Two hand-built Models in the DBX Org of `nebula-ts-semview` — "Semantic SQL - Sale (Metric
Views)" (one Table over a composed Metric View) and "DM Sales & Inventory (Metric Views
Joined)" (six Metric Views and two tables joined in ThoughtSpot) — had every Metric View
measure `MEASURE`/`SUM` on the **Table** and `MEASURE`/`AGGREGATE` on the **Model**.

| Path | Result before the fix |
|---|---|
| UI search (`searchdata`) | Correct — total revenue 594,188,083.19, matching the native star-schema Model |
| AgentQL `AGG("Total Revenue")` | `QUERY_GEN_ERROR` — `AGG()` on a column the query spec carried as non-`AGGREGATE` |
| AgentQL `SUM("Total Revenue")` | Sent as plain `SUM(total_revenue)`; Databricks `METRIC_VIEW_MISSING_MEASURE_FUNCTION` |

A third Model, "Semantic SQL - Sales " (built by `ts link build`, `AGGREGATE` at both levels),
worked on every path. Fix applied: the seven Metric View Tables' measures — exactly the
columns `DESCRIBE TABLE EXTENDED … AS JSON` flags `is_measure` — set to `AGGREGATE` in place
(GUIDs kept). Afterwards all AgentQL baseline queries matched across the four Models, and the
60-case AgentQL corpus matched the native Model on every comparable case. The reverse (Table
`AGGREGATE`, Model `ATTRIBUTE`, on "Line Count") searched correctly, so only the
Model-`AGGREGATE`-over-non-`AGGREGATE`-Table direction is a defect.

`ts link build` is unaffected (it writes both levels). Enforced for hand-built/edited Models
by `ts tml lint` I16 when the Tables are linted with the Model (ts-cli 0.166.0). The product
inconsistency itself — AgentQL and search reading different levels — belongs to the
semantic-SQL query-gen change, like #7.

**Status: VERIFIED 2026-10-07.**
