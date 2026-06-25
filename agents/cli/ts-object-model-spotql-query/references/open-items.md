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

## #3 — `AGG(template_col)` wrapper — DEFERRED (not used by this skill)

The SpotQL reference documents an `AGG(aggregate_template_col)` wrapper for formula columns
with embedded aggregation. This skill writes **real aggregates** (`SUM`, etc.) directly,
which is verified working, so `AGG()` is not on the skill's path. If a future need arises
(a formula column whose aggregation must be preserved and differs from SUM), verify the
`AGG()` form live before relying on it. Not a blocker — the skill's guidance (SUM for
additive measure formulas) is verified and matches ThoughtSpot's behaviour of ignoring a
formula's own aggregation setting.
