# Open items — ts-object-model-agentql-query

Tracks API behaviour this skill relies on and its verification status. Per the repo
convention, all items must be VERIFIED (or explicitly deferred) before the skill merges to
main.

## #1 — AgentQL endpoints + bearer auth — VERIFIED (live) 2026-06-25

`POST /callosum/v1/v2/data/spotql/generate-sql` and `.../fetch-data`, body
`{"spotql_query", "model_identifier": <Model GUID>}`. Verified live on champ-staging
(`champagne-master-aws.thoughtspotstaging.cloud`, profile `champ-staging`) against the
"Dunder Mifflin Sales & Inventory" Model (`4da3a07f-fe29-4d20-8758-260eb1315071`):

- `generate-sql` → `{"executable_sql": "<warehouse SQL>"}` on success.
- `fetch-data` → `{"query_result": {"results": [{"tables": {"column": [...]}}]}}` (columnar).
- **V2 bearer token (the `ts` CLI's auth) is accepted** — no V1 session-cookie login needed.
  Note: an older spotQL-testing finding saw V2 bearer 401 on champ-clone-spotql (build
  26.7.0.cl-72). Behaviour is build/cluster-specific; bearer works on current staging.
- Query errors return HTTP 400 with `{"error": {"message": {"code", "debug": "[CODE] …"}}}`
  — surfaced (not crashed) via `ts agentql`'s `raise_for_status=False` path.

Implemented as `ts agentql generate-sql` / `fetch-data` (ts-cli v0.13.0). Pure normalisation
unit-tested in `tools/ts-cli/tests/test_spotql.py`.

## #2 — External-CDW-only constraint — VERIFIED (live) 2026-06-25

AgentQL only supports Models backed by an external cloud data warehouse. A Falcon / imported
/ system Model (`DEFAULT` datasource) returns `"This API only supports external cloud data
warehouses. The model's datasource type (DEFAULT) is not supported."` Confirmed against the
"Discover Monitoring Data" Model. Documented in SKILL.md and agentql-rules.md.

## #3 — `AGG()` on aggregate-formula columns — VERIFIED (live) 2026-06-25

Verified live on champ-staging against the Dunder Mifflin Model, which has aggregate-formula
columns (`# Employees` = `count(...)`, `Inventory Balance` = `last_value(sum(...))`,
`Category Quantity` = `sum(group_aggregate(...))`). (spotQL-testing could never confirm
this — its retail-apparel model had no aggregate-formula columns; its AGG tests are marked
UNKNOWN/exploratory in `docs/test-inventory.md`.)

Findings:
- `SELECT … AGG("t1"."# Employees") … GROUP BY …` → **SUCCESS** with correct per-category
  counts.
- `SUM("t1"."# Employees")` on the same column → **`NESTED_AGGREGATE_NOT_SUPPORTED`**.
- A bare reference to the aggregate-formula column also compiles.

Conclusion: **aggregate-formula columns must use `AGG()`, never `SUM()`; raw measures use
`SUM()`/etc.** Encoded in `agentql-rules.md` § Aggregation and `udf-reference.md`. No
translation layer needed — `AGG()` is native AgentQL the API accepts directly.

## #4 — `connection_type` + callosum endpoint surface — VERIFIED (live) 2026-06-25

The AgentQL endpoints are **callosum** (`POST /callosum/v1/v2/data/spotql/generate-sql` and
`.../fetch-data`), **not** the public `/api/rest/2.0/` REST API — the SpotterCode MCP / dev
docs do not index them. Documented for integrators in `references/integration.md`.

The playground schema for `generate-sql` lists a `connection_type` field that `fetch-data`
does not. It is **optional**: the `ts` CLI sends neither `connection_type` nor any extra
field and both calls succeed against the external-CDW "Dunder Mifflin Sales & Inventory"
Model. Treat `connection_type` as build/connection-specific — omit for standard CDW.

## #5 — 2026-07-29 full limitation re-probe (jul.26.mt dev) — VERIFIED (live) 2026-07-29

Re-probed every testable `limitations.md` row on nebula-damian-alias (jul.26.mt dev build)
against the Snowflake-backed "Supplier Model" (`8777533f`) and "T1_PUBLISH_MODEL"
(`0930baf3`) — 38 `generate-sql` probes plus `fetch-data` execution checks and value
verification (literal arithmetic ×100/÷100 matched baseline exactly; UNION dedup verified
against a UNION ALL control, 12 vs 24 rows).

**Fixed on this build** (moved to ✅ in limitations.md): set-op ORDER BY/LIMIT on the
combined result, aggregated-branch CTE set-ops, `ROUND(x,N)` (now N decimals),
`TO_NUMBER` (now a real CAST — hard error on bad data), `CONCAT_WS`, `LENGTH()`,
grouped `MEDIAN`. **Still broken:** QUALIFY + FILTER silently dropped, WHERE-aggregate →
HAVING lenient parse, set-op type mismatch caught only at fetch, self-join, non-equi join,
ROLLUP, `SELECT *`/`COUNT(*)`, non-MEDIAN percentiles, INITCAP/REGEXP_*/TO_VARCHAR.
**New bugs filed:** [SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935)
(scalar `STDDEV`/`VAR` regression — CTE workaround still works) and
[SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936) (`IN (SELECT …)`
compiles but fails at fetch — subquery Model name emitted verbatim into warehouse SQL).

**Deferred follow-up:** nebula-spotQL was unreachable that day, so the 2026-07-29 findings
are single-build. When it (or another older/newer build) is available: re-confirm the
STDDEV/VAR regression and the set-op fixes, then drop the "jul.26.mt only" hedges from
`limitations.md` / `agentql-rules.md` / `patterns.md`. Also untestable on this instance
(only CDW Model has no date or formula columns): the date-function rows (`DAY_OF_YEAR`,
`TRUNC(date)`, `SUM(CASE WHEN date >= literal)`), `NESTED_AGGREGATE`, and semi-additive
rows — they keep their earlier verification dates.

---

## #6 — Reference corrections from BI-client probing — OPEN 2026-08-04

Driving Tableau Desktop at AgentQL through a Postgres-wire bridge
(`spotql-testing`, `src/spotql_test/bridge/`) exercised the reference material far
harder than hand-written queries do, because a BI tool emits SQL nobody chose.
That surfaced **three claims in this skill's own references that do not hold** on
build 26.7.0.cl-72 against a Snowflake-backed Model, plus **five limitations not
yet recorded**.

Every item below was verified with `generate-sql` / `fetch-data` against
`T1_PUBLISH_MODEL` on `nebula-damian-alias` (physical
`AGENT_SKILLS.ALIAS_TESTS.T1_PUBLISH`), per this file's own rule that the probe,
not the ticket or the doc, is the source of truth.

### A. Three corrections — the doc is wrong

| Where | Says | Actually | Evidence |
|---|---|---|---|
| `udf-reference.md` § Extraction UDFs | `DAY_NUMBER(date_col)` returns INT **(1–366)**, i.e. day of year | Returns **day of month** | For 2024-03-15, `DAY_NUMBER` = 15 and `DAY_IN_MONTH_NUMBER` = 15. Day of year is 75. So `DAY_NUMBER` duplicates `DAY_IN_MONTH_NUMBER` and **there is no day-of-year UDF** |
| `agentql-rules.md` § Forbidden (recap) | "arithmetic between an aggregate and a numeric literal (returns zeros)" | **Works correctly** | Against a known Furniture total of 6878: `*100` → 687800, `/2` → 3439, `+1` → 6879, `-1` → 6877; also literal-first, DOUBLE, `COUNT`, `AVG`, and grouped forms. All correct |
| `agentql-rules.md` § Forbidden (recap) | `LENGTH()` forbidden | **Works** | 15 grouped rows returned. `limitations.md` L-14 already records it mapping to `char_length` server-side |

**Why these matter more than a typo.** The aggregate-times-literal claim is the
dangerous one: a deny-list entry was written against it and then removed once
probed. Had it shipped it would have blocked every percentage and unit-scaling
calculation a BI tool produces. The `DAY_NUMBER` error is the other kind — it
would have been used to translate `EXTRACT(DOY ...)`, returning a plausible wrong
number rather than an error.

### B. Five limitations to add to `limitations.md`

All found through BI-client SQL, all with SCAL tickets under
[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371):

| Construct | Behaviour | Ticket |
|---|---|---|
| `LTRIM(x, chars)` / `RTRIM(x, chars)` | Validates, then renders ANSI `trim(leading ' ' from ...)`, which Snowflake rejects. Single-argument form is correct | [SCAL-326943](https://thoughtspot.atlassian.net/browse/SCAL-326943) |
| `DATE_TRUNC(unit, col)` | Validates, then leaks the parser alias, drops the unit (`trunc(x, null)`), and **silently drops the `GROUP BY`**, wrapping the date in `min()` | [SCAL-326944](https://thoughtspot.atlassian.net/browse/SCAL-326944) |
| `CAST(<literal> AS <type>)` | Rejected as a fabricated column `Constant_<value>`. Casting a *column* is fine | [SCAL-326946](https://thoughtspot.atlassian.net/browse/SCAL-326946) |
| `EXTRACT(DOW ...)` | Rejected at parse, `DatePart expected`. `DAY_IN_WEEK_NUMBER(x) % 7` is the exact equivalent (Monday=1..Sunday=7, so mod 7 gives Sunday=0..Saturday=6) | [SCAL-327864](https://thoughtspot.atlassian.net/browse/SCAL-327864) |
| `EXTRACT(DOY ...)` | Validates, renders `extract(day_of_year from ...)`; Snowflake wants `dayofyear`. No workaround, because `DAY_NUMBER` is day-of-month (see A) | [SCAL-327864](https://thoughtspot.atlassian.net/browse/SCAL-327864) |

Diagnostics worth noting alongside them
([SCAL-326945](https://thoughtspot.atlassian.net/browse/SCAL-326945)): a derived
table in a `JOIN` reports `Table 't' not found`, where `'t'` is a hardcoded
placeholder that appears whatever the real alias is; and `GROUP BY 1` reports
`Missing formula alias: <guid>`, naming neither the construct nor anything the
caller wrote.

### C. Two behaviours to document, not tickets

- **`LIMIT 100000` is appended to every generated statement**, including
  statements with no `LIMIT` of their own. On a large Model a bulk extract would
  be silently capped. Worth a line in `limitations.md` and confirming whether it
  is configurable.
- **`IN (SELECT ...)` validates and emits the subquery untranslated**, referencing
  the Model name as though it were a physical table. It only fails because no such
  object exists; if one did, it would execute against the wrong thing. A ticket
  reportedly already exists.

### D. Suggested addition to `patterns.md`: the CTE semi-join

Subqueries are unsupported, but a **CTE joined to the Model** is, and it is the
only expressible semi-join. It works, including `ORDER BY ... LIMIT n` inside the
CTE, which is what a Top-N rewrite needs.

The guard is not optional and is stricter than it looks:

> **The CTE's grouped (or `DISTINCT`) column set must be a subset of the columns
> in the join's `ON` equality.**

A derived table filters; a `JOIN` multiplies. Measured on `T1_PUBLISH_MODEL`,
true `SUM(QTY_ON_HAND)` = 18,695:

| Shape | Result |
|---|---|
| Key CTE not deduped | **472,314** |
| Key CTE `GROUP BY <join key>` | 18,695 |
| Key CTE `GROUP BY (cat, name)`, joined on `cat` only | **472,314** |

The last row is the point: a `GROUP BY` is present and the answer is still 25×
too high. Pre-aggregating the fact side does not help — re-aggregating a
fanned-out result just adds up the duplicates.

### Proposed work

1. Apply the three corrections in A. Mechanical; the evidence is above.
2. Add the five rows in B to `limitations.md` with their SCAL refs, and bump the
   currency anchor.
3. Add C as two notes.
4. Add D to `patterns.md` with the guard stated as a rule.
5. Consider whether `udf-reference.md` should be **generated from a live probe
   suite** rather than hand-maintained. Three wrong entries in one file is a
   pattern rather than bad luck, and `use-cases.md` #6 already describes the
   executable form of exactly that check.

Not done here because it changes a shipped skill's guidance, which deserves a
review rather than being folded into a bridge branch.

## Keeping `limitations.md` current

`limitations.md` carries a currency anchor (`<!-- currency: spotql — YYYY-MM (...) -->`).
The repo's `check_mapping_currency.py` (wired into pre-commit and CI via `ANCHORED_FILES`)
**soft-nudges** when that anchor is stale (> 6 months) or missing — never blocks, because
external product behaviour can't gate a PR. This is the agreed approach: a nudge, not a
live Jira call in the commit hook.

### Refreshing limitations from the Jira epics (on demand, not per-commit)

When the nudge fires (or before a release), refresh against the two epics — but **confirm
every change with a live probe**, because a ticket can be Closed without the behaviour
changing (`PERCENTILE_CONT` is Closed as MEDIAN-only yet still errors live):

1. **Pull current ticket statuses** from the two epics via the Atlassian MCP:
   - `getJiraIssue` / `searchJiraIssuesUsingJql` with
     `parent in (SCAL-306544, SCAL-316371)` (cloudId `thoughtspot.atlassian.net`),
     fields `summary,status`.
2. **Diff against `limitations.md`** — flag rows whose SCAL ticket status changed
   (Open→Closed = candidate "now works" to remove; new Open child = candidate new row).
3. **Re-probe each flagged construct live** with `ts agentql generate-sql` / `fetch-data`
   against an external-CDW model (e.g. the Dunder Mifflin smoke model) — the probe, not the
   ticket, is the source of truth.
4. **Update the file**: remove rows that now work (and relax the matching rule in
   `agentql-rules.md` / `udf-reference.md` / `patterns.md`); add newly-confirmed limitations
   with their SCAL ref. **Bump the currency anchor** to clear the nudge.

This pairs with the skill's known-limitation-retest use case (`use-cases.md` #6) — the
suite of "expected-to-fail" questions is the executable form of this re-probe.
