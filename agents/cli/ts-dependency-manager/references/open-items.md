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
helpers in SKILL.md Step 9b include `search_query` sanitization:

```python
import re

def sanitize_search_query(query_str, columns_to_remove):
    """Strip [col_name] tokens from a ThoughtSpot search_query string."""
    for col in columns_to_remove:
        query_str = re.sub(r'\s*\[' + re.escape(col) + r'\]\s*', ' ', query_str)
    return query_str.strip()

def rename_in_search_query(query_str, old_name, new_name):
    """Rename a [col_name] token in a ThoughtSpot search_query string."""
    return re.sub(
        r'\[' + re.escape(old_name) + r'\]',
        f'[{new_name}]',
        query_str,
    )
```

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #4 — Join conditions with removed columns must be updated — CONFIRMED (user-verified)

**Confirmed behavior:** A Model TML cannot be saved if `joins_with[].on` (or equivalent
join expression in `model_tables[]`) references a column that no longer exists in
`columns[]`. The import fails. The join must be removed or the `on` expression corrected.

**Resolution (implemented in SKILL.md Step 9a):** Before removing a column from a
Model, scan all join expressions for references to the column. If found:
1. Show in the impact report (Step 5) as a separate "Join Conditions Affected" section
2. At the confirmation step (Step 8): list each join that will be removed
3. In Step 9a: remove the affected join from `model_tables[].joins_with[]`

```python
def remove_column_from_model_joins(section, columns_to_remove):
    """
    Remove join conditions that reference any of columns_to_remove.
    Returns (updated_section, list of removed joins for the change report).
    """
    removed_joins = []
    for tbl in section.get("model_tables", []):
        safe   = []
        for join in tbl.get("joins_with", []):
            on_expr = join.get("on", "")
            if any(col in on_expr for col in columns_to_remove):
                removed_joins.append({
                    "table":   tbl.get("name", "?"),
                    "join":    join.get("name", "unnamed"),
                    "on":      on_expr,
                })
            else:
                safe.append(join)
        tbl["joins_with"] = safe
    return section, removed_joins
```

**Impact on dependent Models:** If a dependent Model joins to the source Model using
the removed column, the same logic applies to that Model's `joins_with[]`.

**Status:** Implementation added to SKILL.md. Mark VERIFIED once tested end-to-end.

---

## #5 — `ts metadata dependents` CLI command — VERIFIED 2026-06-01

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

## #10 — Column alias TML — VERIFIED 2026-06-01 via export_with_column_aliases beta flag

**Verified 2026-06-01** — `export_options.export_with_column_aliases: true` confirmed working. Integrated into `ts metadata report` via `ts_cli.report.tml_probes.find_alias_column_uses`. Tested via unit tests (278/278 pass). Live test against SpotterAccuracy blocked by `TLSV1_ALERT_PROTOCOL_VERSION` on `champ-clone-spotql.thoughtspotdev.cloud`; smoke test (open-item #22) pending.

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

## #19 — Audit scope 3: Whole-object section-per-column report — CLOSED 2026-06-01 via ts metadata report multi-source mode

Generate a per-column report section when the user picks audit scope 3. Implement in
Commit B.

---

## #20 — Audit scope 4: repoint pre-flight column-gap analysis — DEFERRED

**Goal:** When the user picks audit scope 4, generate a "would this repoint work?" report:
- Source object's columns
- Target object's columns
- **Column gap** — source columns absent in target
- For each gap column, list the dependents that would lose data after the repoint
- Per-dependent simulation: which would auto-resolve, which would break, which need manual
  fix-up

**Why deferred:** Reuses Step 4 dep walk on the source, but adds:
1. Target object lookup + column listing
2. Gap computation
3. Per-dependent column-impact simulation (would the dep still render? lose what columns?)

**Implementation outline:**

```python
if audit_scope == "REPOINT_PREFLIGHT":
    target_guid = ask_for_target_object()  # Step 3-P-style search
    source_cols = export_columns(source_guid)
    target_cols = export_columns(target_guid)
    gap = source_cols - target_cols  # source columns missing in target

    deps_per_col = {}
    for col in gap:
        deps_per_col[col] = run_step4_scan(source_guid, [col])

    # Render: gap table, per-gap-column dep list, simulation summary
```

**Output files:**
- `repoint_preflight.json` — full simulation result
- `column_gap.csv` — one row per gap column with dep counts
- `dependency_<col>.txt/.mmd` per gap column

**Status:** Deferred — implement in Commit B (alongside #19).

---

## #21 — Recommendation engine after audit — PARTIAL 2026-06-01 (risk + recommended-action covered by classifier; auto-jump-into-flow still deferred)

**Goal:** After any audit, surface concrete next-action recommendations per column based
on the dep graph. The user can pick a recommendation and the skill jumps directly into
the matching R/N/P flow with source + columns pre-filled.

**Recommendation rules (initial):**

| Pattern | Recommended action |
|---|---|
| 0 deps                            | REMOVE (safe) |
| Only formula deps, no charts      | REMOVE (auto-cleanup) |
| Charts on axis                    | REMOVE w/ auto-fix to TABLE_MODE |
| RLS rule + dependents             | REMOVE — coordinate with security review first |
| Display-name issue (user request) | RENAME |
| Switching backing source          | REPOINT |
| Set as anchor + consumers         | REMOVE the Set; consumers need attention |

**Output:**

```
Recommended actions:

  ZIPCODE (9 dependents)
    Recommended:  REMOVE  (with auto-fix mode for charts on axes)
    Risk:         HIGH — 1 RLS rule + 3 Liveboard vizzes on axis + 2 feedback items
    Take action?  /ts-dependency-manager → R → DM_CUSTOMER_BIRD → ZIPCODE

  STATE (0 dependents)
    Recommended:  REMOVE  (safe)
    Take action?  /ts-dependency-manager → R → DM_CUSTOMER_BIRD → STATE

Enter the number(s) to apply, or N to exit and replan later.
```

If the user picks one, the skill **jumps directly into the matching apply flow** with
source + columns pre-filled (skip Step 2 and Step 3 search; resume at Step 4 with the
recommendation's parameters).

**Why deferred:** Requires the rule-engine + jumping logic. Best to ship after #19/#20
so the input data (per-column dep counts and patterns) is already populated.

**Status:** Deferred — implement in Commit C.

---

## #22 — Smoke test for ts metadata report — VERIFIED 2026-06-01

**Status:** VERIFIED 2026-06-01. `tools/smoke-tests/smoke_ts-metadata-report.py` passes
against SpotterAccuracy (`champ-clone-spotql.thoughtspotdev.cloud`). Fixture:
`EDUCATION_BUSINESS.EDUCATION_BUSINESS.UNIVERSITY_FACULTY` (GUID `baa451a6-02a0-42d1-8347-8cd4af13b505`).

---

## #23 — VERSION_CONFLICT (14009) on fqn-based model repoint — CONFIRMED 2026-06-09

**Context:** When repointing a model's `model_tables[].fqn` from one table to another,
some ThoughtSpot builds return VERSION_CONFLICT (error 14009) on import — even when the
TML is otherwise valid and the only change is the fqn value.

**Finding:** Using `obj_id`-based references instead of `fqn` avoids the error. The
`export_options` API flags (`include_obj_id: true`, `include_obj_id_ref: true`,
`include_guid: false`) produce TML with `obj_id` fields. The repoint then replaces
`obj_id` (format: `{NAME}-{first8chars_of_guid}`) instead of `fqn`.

**Verified against:**
- `se-thoughtspot-cloud.thoughtspot.cloud` — 4 models repointed successfully using obj_id
  approach (2026-06-09). Source table `DM_CATEGORY_SQL` (GUID `dda51113-cc80-47e5-82a1-b1a997ed5e69`),
  target table `DM_CATEGORY` (GUID `b1c94779-122f-43aa-86f6-f9a7fbcfddce`).
- `champ-clone-spotql.thoughtspotdev.cloud` (SpotterAccuracy) — ALL TML imports fail with
  VERSION_CONFLICT on this cluster, including trivial description changes. This is a
  pre-existing instance condition, not specific to the repoint operation.

**Skill impact:** Step 9 now detects obj_id support and prefers obj_id-based references
with fqn fallback. See `detect_obj_id_support` block and `repoint_model()` function.

**Status:** CONFIRMED 2026-06-09. Implemented in ts-dependency-manager v1.1.0.

---

## #24 — TML export_options API flags — CONFIRMED 2026-06-09

**Context:** The `exportMetadataTML` v2 endpoint accepts an `export_options` object in
the request body with three boolean flags:

- `include_obj_id` — includes `obj_id` field at the root of each TML object
- `include_obj_id_ref` — includes `obj_id` fields on references within the TML
  (e.g. `model_tables[].obj_id`)
- `include_guid` — when `false`, omits `guid` from the exported TML (default: `true`)

**Verified via:** SpotterCode MCP `get-rest-api-reference(apiName: "exportMetadataTML")`
and live testing on `se-thoughtspot-cloud.thoughtspot.cloud` (2026-06-09).

**obj_id format:** `{OBJECT_NAME}-{first_8_chars_of_guid}` (e.g. `DM_CATEGORY_SQL-dda51113`).
The name portion uses the object's ThoughtSpot display name (spaces replaced with
underscores in some cases).

**Skill impact:** ts-cli v0.8.0 adds `--include-obj-id`, `--include-obj-id-ref`, and
`--no-guid` flags to `ts tml export`. Step 9 uses these flags for repoint operations.

**Status:** CONFIRMED 2026-06-09. Implemented in ts-cli v0.8.0.
