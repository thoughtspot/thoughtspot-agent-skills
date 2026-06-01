# Open Items — ts-dependency-manager

Items that need verification against a live ThoughtSpot instance before the skill
is considered fully verified. Update each item with findings after testing.

Status legend: **CONFIRMED** (direction known, needs live verification) | **VERIFIED** (tested) | **OPEN** (unknown)

---

## #2 — Column reference format in chart configs (Step 9b) — OPEN

**Question:** Do `chart_columns[].column_id`, `table.ordered_column_ids`, and
`table.table_columns[].column_id` in Answer/Liveboard TML use:
  - (A) Display name (e.g. `"Revenue"`) — expected based on schema reference
  - (B) `TABLE::COLUMN_NAME` composite key
  - (C) Opaque internal ID

**Why it matters:** The `remove_columns_from_answer()` and `rename_column_in_answer()`
helpers compare by display name. If format (B) or (C) is used for some chart types,
those helpers silently miss chart config entries.

**Finding:** _(not yet tested)_

---

## #5 — `ts metadata dependents` CLI command — OPEN

**Status:** Not yet implemented. The v2 API contract is verified (see SKILL.md).

**Proposed command interface:**

```bash
ts metadata dependents <guid> [<guid> ...] \
  [--type LOGICAL_TABLE|LOGICAL_COLUMN|PHYSICAL_TABLE|PHYSICAL_COLUMN] \
  [--profile <name>]
```

Add to `tools/ts-cli/commands/metadata.py` following the pattern of the `search` command.
Bump ts-cli version in both `__init__.py` and `pyproject.toml`.

---

## #9 — Column security rule TML retrieval — OPEN

TML structure is documented and detection/update logic is mechanical. The **retrieval
mechanism** is the open question: on champ-staging, the v2 `--associated` export does
not return CSR files. They appear only via the ThoughtSpot UI's Download TML zip or
the `vcs/git/branches/commit` workflow.

**Action:** Confirm retrieval mechanism. Re-test on Cloud 26.4.0+.

---

## #10 — Per-locale column alias TML retrieval — OPEN

Per-locale alias TML is a separate `column_alias` file at model scope. Retrieval via
v2 API not verified — same status as #9.

Inline aliases (Model `columns[].name` vs `column_id`) are already implementable.

---

## #11 — Reusable Set (cohort) delete command — OPEN

The internal type is `COHORT` but it's not a valid `SearchMetadataType` — sets must be
queried as `LOGICAL_COLUMN`. Sets appear in v2 dependents under their own `COHORT` bucket.

**Remaining question:** Does `ts metadata delete {guid} --type LOGICAL_COLUMN` work
for cohort/Set objects?

---

## #13 — Chart `client_state_v2` stale column references — OPEN

After stripping a column from all structural locations, the import still fails if the
column name appears inside `client_state_v2`'s `columnProperties[]` or
`systemSeriesColors[]`. Must parse as JSON, strip, re-serialize.

Closely related to #2. Both must be resolved together.

**Status:** Confirmed on champ-staging.

---

## #14 — Cohort `pass_thru_filter` lost on round-trip — OPEN

When a cohort TML is exported and re-imported unchanged, `config.pass_thru_filter` is
silently dropped. Affects Step 11 rollback fidelity.

**Status:** Witnessed on champ-staging 2026-04-26.

---

## #15 — TS error message text is misleading; use error_code for branching — OPEN

TML import failures return `"Invalid YAML/JSON syntax in file."` regardless of actual
cause. On champ-staging the response does NOT include `error_code`.

Skill must use dep walk as primary discovery, not error parsing. Re-test on Cloud 26.4+.

---

## #16 — Cohort + dependent answer import ordering / TS metadata caching — OPEN

Importing a Set then immediately importing a consuming answer fails with
`Column: address set not found`. A ~2s delay resolves it. Verify-and-retry is the
recommended workaround.

---

## #18 — TML export/import for FEEDBACK objects fails — OPEN

Spotter feedback objects cannot be exported via `ts tml export <guid>` (returns
error_code 10002). Correct endpoint for fetching/updating FEEDBACK objects not yet
discovered.

---

## #19 — Audit scope 3: whole-object section-per-column report — DEFERRED

Generate a per-column report section when the user picks audit scope 3. Implement in
Commit B.

---

## #20 — Audit scope 4: repoint pre-flight column-gap analysis — DEFERRED

Compare source and target columns, identify gaps, simulate per-dependent impact.
Implement in Commit B alongside #19.

---

## #21 — Recommendation engine after audit — DEFERRED

Surface next-action recommendations per column based on the dep graph. Implement in
Commit C.
