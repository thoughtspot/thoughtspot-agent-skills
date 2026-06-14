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

## #3 — search_query sanitization on column removal — CONFIRMED (user-verified)

**Confirmed behavior:** ThoughtSpot will **not** save an object (Answer, View) where
`search_query` references a column that no longer exists. The import fails with a
validation error. The `search_query` MUST be updated before import.

**Resolution:** The `remove_columns_from_answer()` and `remove_columns_from_view()`
helpers in SKILL.md Step 9b include `search_query` sanitization.

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #4 — Join conditions with removed columns must be updated — CONFIRMED (user-verified)

**Confirmed behavior:** A Model TML cannot be saved if `joins_with[].on` (or equivalent
join expression in `model_tables[]`) references a column that no longer exists in
`columns[]`. The import fails. The join must be removed or the `on` expression corrected.

**Resolution:** Implemented in SKILL.md Step 9a — scan all join expressions for references
to the column before removal; remove affected joins and report them.

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #9 — Column security rule TML retrieval — OPEN

TML structure is documented and detection/update logic is mechanical. The **retrieval
mechanism** is the open question: on champ-staging, the v2 `--associated` export does
not return CSR files. They appear only via the ThoughtSpot UI's Download TML zip or
the `vcs/git/branches/commit` workflow.

**Action:** Confirm retrieval mechanism. Re-test on Cloud 26.4.0+.

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

## #20 — Audit scope 4: repoint pre-flight column-gap analysis — DEFERRED

**Goal:** When the user picks audit scope 4, generate a "would this repoint work?" report
comparing source and target object columns, computing gaps, and simulating per-dependent
impact.

**Status:** Deferred — implement after #3 and #4 are verified end-to-end.

---

## #21 — Recommendation engine after audit — PARTIAL

**Goal:** After any audit, surface concrete next-action recommendations per column based
on the dep graph. The user can pick a recommendation and the skill jumps directly into
the matching R/N/P flow with source + columns pre-filled.

Risk classification and recommended-action are covered by the classifier. Auto-jump-into-flow
is still deferred.

**Status:** Partial — implement auto-jump in a future version.
