# Open Items — ts-object-answer-chart-builder

Tracks behaviour not yet verified on a live cluster, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

Everything here is covered offline by the mock-`ts` scenarios in thoughtspot-agent-skills
(`tools/smoke-tests/_answer_patch_mock.mjs`); "live" means a real import on a cluster.

The 2026-11-05 live run used ps-internal (ThoughtSpot 26.11.0.cl, Primary org), the "(Sample) Retail -
Apparel" model and a scratch answer saved for it. Blocks were printed by `answer-pack.mjs` / `mcp-block.mjs`
and run through the ThoughtSpot MCP; the backup was exported with `ts tml export`'s exact request from a
signed-in browser session (no CLI profile on the machine) and checked on disk by `backup-check.mjs`.

---

## #1 — An answer update keeps the column order, live — VERIFIED 2026-11-05

**What changed:** an update keeps the table's `ordered_column_ids` (new columns last) and the custom chart's
`client_state`, and the round trip compares both (`client_state` and `client_state_v2` parsed, since
ThoughtSpot re-serialises them).

**Result (ps-internal 26.11.0.cl, 2026-11-05):** a new answer from `where-hex-cartogram` (`roundTripOk: true`);
its table columns reversed in TML to `["Total sales", "state"]`, as a user's edit; then
`answer-pack.mjs --answer <guid> --backup <file> --commit`: `kept` the description, table settings, tables and
custom chart settings, `replaced: []`, `recheck: unchanged`, `roundTripOk: true`, and the order read back as
`["Total sales", "state"]`. The update (14:44 UTC) ran on a block that carried the whole-answer fingerprint
without `fqn`, as committed.

**Not shown live:** that the custom chart's `client_state` is kept. The user's edit before the update changed
only the column order, so keeping `client_state` and rewriting it to the value the skill wrote first look the
same. The mock covers it (`_answer_patch_mock.mjs`: a user's `client_state` on the answer survives the update, and a round trip that loses it fails).

---

## #2 — The intake blocks' field names — VERIFIED 2026-11-05

**Question:** `helpers/mcp/model-columns.js` reads `metadata_detail.columns[].header.name` (falling back to
`.name`), `.type` and `.dataType` (falling back to `.data_type`). Do those reads hold on a cluster?

**Result (ps-internal 26.11.0.cl, 2026-11-05):** `mcp-block.mjs model-columns --model <guid>` on "(Sample)
Retail - Apparel": all 14 columns came back with a name, a type of `ATTRIBUTE` or `MEASURE` and a data type
(`VARCHAR`, `DOUBLE`, `INT64`, `DATE`).

---

## #3 — The answer backup's fingerprint matches the sandbox's export — VERIFIED 2026-11-05

**Question:** the backup comes from `ts tml export --format JSON`; the sandbox exports with `export_fqn: true`.
Is the fingerprint the same from both?

**Result (ps-internal 26.11.0.cl, 2026-11-05):** on a saved custom-chart answer the two exports differ (the
sandbox's holds `fqn`, the CLI's does not), and a whole-answer fingerprint taken as it is did not match. The
fingerprint is now the whole answer (keys sorted) without any `fqn`, and with that the two matched; the
update in #1 accepted its CLI-format backup.
