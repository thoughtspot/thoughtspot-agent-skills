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
