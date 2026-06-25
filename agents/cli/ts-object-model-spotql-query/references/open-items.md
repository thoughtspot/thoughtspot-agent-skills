# Open items — ts-object-model-spotql-query

Tracks API behaviour this skill relies on and its verification status. Per the repo
convention, all items must be VERIFIED (or explicitly deferred) before the skill merges to
main.

## #1 — SpotQL endpoints + bearer auth — VERIFIED (live) 2026-06-25

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
  — surfaced (not crashed) via `ts spotql`'s `raise_for_status=False` path.

Implemented as `ts spotql generate-sql` / `fetch-data` (ts-cli v0.13.0). Pure normalisation
unit-tested in `tools/ts-cli/tests/test_spotql.py`.

## #2 — External-CDW-only constraint — VERIFIED (live) 2026-06-25

SpotQL only supports Models backed by an external cloud data warehouse. A Falcon / imported
/ system Model (`DEFAULT` datasource) returns `"This API only supports external cloud data
warehouses. The model's datasource type (DEFAULT) is not supported."` Confirmed against the
"Discover Monitoring Data" Model. Documented in SKILL.md and spotql-rules.md.

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
`SUM()`/etc.** Encoded in `spotql-rules.md` § Aggregation and `udf-reference.md`. No
translation layer needed — `AGG()` is native SpotQL the API accepts directly.
