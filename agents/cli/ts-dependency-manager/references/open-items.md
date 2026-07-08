# Open Items — ts-dependency-manager

Items that need verification against a live ThoughtSpot instance before the skill
is considered fully verified. Update each item with findings after testing.

Status legend: **CONFIRMED** (direction known, needs live verification) | **VERIFIED** (tested) | **OPEN** (unknown)

---

## #2 — Column reference format in chart configs (mutate.py `remove_columns_from_answer`) — OPEN

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
helpers in `ts_cli/dependency/mutate.py` (`sanitize_search_query`, applied by `apply-change`) include `search_query` sanitization.

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #4 — Join conditions with removed columns must be updated — CONFIRMED (user-verified)

**Confirmed behavior:** A Model TML cannot be saved if `joins_with[].on` (or equivalent
join expression in `model_tables[]`) references a column that no longer exists in
`columns[]`. The import fails. The join must be removed or the `on` expression corrected.

**Resolution:** Implemented in `ts_cli/dependency/mutate.py` (`remove_columns_from_model_section`, run by `apply-change`) — scan all join expressions for references
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

## #22 — Surface chart-axis-role (REMOVE_CHART) in `ts metadata report` for Step 6 — OPEN

**Context (BL-083 PR2):** `ts dependency apply-change` classifies per-viz chart roles
itself (`ts_cli.dependency.apply.chart_role_for_answer` /
`classify_liveboard_viz_roles`) and defaults every x/y-axis-affected viz to the
always-safe CONVERT_TO_TABLE, with a per-viz plan override. This is self-contained in
the command, so the destructive path is deterministic. What is NOT yet done: surfacing
those roles in `ts metadata report` output so Step 6 can present the CONVERT_TO_TABLE
-vs-REMOVE decision interactively from the report rather than from a separate TML read.

**Why deferred:** `ts_cli/report/__init__.py:build_report` does not wire per-dependent
chart classification at all today (`classify_dependent` / `DependentSignals.chart_axis_use`
exist but are never populated — build_report feeds only the aggregate from RLS/join/AI
probes). Emitting a per-viz `action` would touch the `schema_version` 1.0 report
contract, a larger change than the orchestrator needs.

**Action:** populate `DependentSignals.chart_axis_use` per liveboard viz in
`build_report`, emit a per-viz role in the report JSON, and have Step 6 consume it.

**Related fidelity follow-up:** `mutate._apply_remove_liveboard` currently converts EVERY source-referencing viz to TABLE_MODE on the CONVERT_TO_TABLE default (safe, but over-flattens a viz that used the removed column only as a color/size/shape binding). A strip-in-place path for REMOVE_COLUMN vizzes (using `classify_liveboard_viz_roles`) would preserve those charts — pair it with the report surfacing above.

---

## #23 — `apply-change` execution order (source LAST) — VERIFIED LIVE 2026-07-08

**Corrected in BL-083 PR2.** The SKILL's old Step 9 *section bodies* imported the
source BEFORE dependents, but the overview + the error-14544 rationale ("Deleted
columns have dependents" — TS rejects the source column removal while any dependent
still references it) require dependents to be fixed FIRST and the source LAST.
`ts dependency apply-change` therefore runs deletes → dependents → source → sets.

**Live-test gate (MANDATORY before this ships):** on se-thoughtspot (AGENT_SKILLS),
run a REMOVE against a Model whose column is referenced by ≥1 dependent Answer and
confirm (a) the dependent fix imports before the source, and (b) the source removal
succeeds (no 14544) because the dependents were fixed first. Also exercise: a REPOINT
with obj_id present, a dependent-drift skip, a set with a failed consumer fix (must be
skipped), and the source-drift hard stop. This is a destructive command — do not merge
BL-083 PR2 until this passes.

**Live results (se-thoughtspot, DM_CATEGORY.CATEGORY_NAME, 2026-07-08) — VERIFIED:**
- **Ordering:** dependent fixes ran before the source; when a dependent fix failed,
  the source column removal was correctly rejected with real error 14544 ("Deleted
  columns have dependents"). Confirms dependents-first is required and sequenced right.
- **Outcome matrix / verify:** the post-import re-export correctly distinguished
  SUCCESS from FAIL_SILENT (import OK but column still present) and FAIL_VERIFIED
  (real 14544). No silent success; nothing was deleted or half-applied.
- **Rollback:** `ts dependency rollback` restored source + all fixed dependents
  cleanly (verified column/refs back to original) after every run.
- **Bug found + fixed (open-item #24):** the model-fix mutation missed aliased
  columns; after the fix, 3 of 4 models stripped CATEGORY_NAME successfully.
- **Green end-to-end CONFIRMED** on a clean column (DM_PRODUCT.PRODUCT_DESCRIPTION,
  4 model fixes + source, no cohort/set): all 4 dependent fixes SUCCESS, then the
  source table column removal SUCCESS (no 14544), column verified gone from table and
  models; `ts dependency rollback` then restored all 5 objects. (CATEGORY_NAME's own
  removal needs a non-cleanly-reversible set delete — a cohort is anchored on it — so
  the green demo used the fix-only PRODUCT_DESCRIPTION graph instead.)

---

## #24 — Model-fix missed aliased base columns (column_id / formula-expr) — FIXED 2026-07-08

**Found live on se-thoughtspot** during the open-item #23 apply-change test. When a
dependent Model exposes a base-table column under a friendly alias, the column entry
has `name: "Product Category"` but `column_id: "DM_CATEGORY::CATEGORY_NAME"`, and the
model's measure formulas reference `[DM_CATEGORY::CATEGORY_NAME]` in their `expr`.
`remove_columns_from_model_section` matched columns by `name` only, so removing base
column `CATEGORY_NAME` stripped nothing from the model — the import returned OK but the
re-export still referenced the column (caught as FAIL_SILENT by post-import verify),
and the source removal was then blocked by 14544.

**Fix (ts-cli v0.41.0):** `remove_columns_from_model_section` now also matches columns
by `column_id` (whole-token, via `_references_column`), removes formulas whose `expr`
references the removed column, and cascades to any column backed by a removed formula.
Whole-token matching avoids false-positives (`SUB_CATEGORY_NAME`, `CATEGORY_ID` survive).
Verified live: 3 of 4 models then stripped the aliased column successfully. Unit tests
added in `test_dependency_mutate.py`.

**Status:** FIXED + unit-tested + live-verified.

---

## #25 — Rollback restored dependents before source (one-pass failure) — FIXED 2026-07-08

**Found live on se-thoughtspot** during the #23 green-path test. `rollback_order`
restored dependents BEFORE the source (tables last), but a REMOVE rollback must restore
the source's removed column FIRST — re-importing a Model whose `column_id` is
`DM_PRODUCT::PRODUCT_DESCRIPTION` fails ("Unable to create model column(s) …
DM_PRODUCT::PRODUCT_DESCRIPTION") while the source table has not yet been restored. On
the live run the 4 model restores failed on pass 1 (table restored last); a SECOND
rollback run completed them (table then present). Silent-ish: exit 0 with per-object
failures in the results JSON.

**Fix (ts-cli v0.41.0):** `rollback_order` now restores ROOT-first — sorted by
`DELETE_ORDER` rank DESCENDING (Table → Model/Worksheet → View → Set → Answer →
Liveboard), the reverse of the leaf-first delete/apply order, stable within a tier.
Re-verified live: the same cycle now rolls back all 5 objects in ONE pass (source table
first, then the 4 models), 0 failures. Tests updated in `test_dependency_backup.py`.

**Status:** FIXED + unit-tested + live-verified.
