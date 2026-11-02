# Open Items — ts-object-answer-chart-builder

Tracks behaviour not yet verified on a live cluster, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

Everything here is covered offline by the mock-`ts` scenarios in thoughtspot-agent-skills
(`tools/smoke-tests/_answer_patch_mock.mjs`); "live" means a real import on a cluster.

---

## #1 — An answer update keeps the column order and the chart's own state, live — OPEN

**What changed:** an update keeps the table's `ordered_column_ids` (new columns last) and the custom chart's
`client_state`, and the round trip compares both (`client_state` and `client_state_v2` parsed, since
ThoughtSpot re-serialises them).

**Action:** Update a saved custom-chart answer whose table columns were reordered in ThoughtSpot, with a fresh
backup; expect `roundTripOk: true` and the order unchanged in the table view.

---

## #2 — The intake blocks' field names — OPEN

**Question:** `helpers/mcp/model-columns.js` reads `metadata_detail.columns[].header.name` (falling back to
`.name`), `.type` and `.dataType` (falling back to `.data_type`). The intake that SKILL.md held inline before
read the same response, but the block's exact field reads have not been run on a cluster.

**Action:** Run `mcp-block.mjs model-columns --model <guid>` on a cluster and check every column has a name,
a type of `ATTRIBUTE` or `MEASURE` and a data type.

---

## #3 — The answer backup's fingerprint matches the sandbox's export — OPEN

As Liveboard open item #3: the backup comes from `ts tml export --format JSON`, the sandbox exports with
`export_fqn: true` through the MCP. The fingerprint leaves out tables (where the fqn shows), but the two have not
been compared on a cluster. A mismatch refuses the update; it never writes.
