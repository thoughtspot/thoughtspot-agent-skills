# Step 7 — Review Checkpoint & Import: Display Templates

The console/report display templates for **Step 7 — Review Checkpoint & Import**. The
step's procedure (what to do, in what order, and the gates between phases) stays in
`SKILL.md` — these are the literal shapes of what gets shown to the user or parsed from
CLI JSON output at each checkpoint.

## Pre-import review summary

Shown before the user is asked to confirm import (yes/no/file):

```
Ready to import to {base_url}:

Tables:
  ✓ {TABLE_NAME}   → create new on connection "{connection_name}"
  ↺ {TABLE_NAME}   → reuse existing object (GUID {guid})        # if Step 4.5 reuse
  …

Model: {datasource_name}
  Columns: {n} total — {a} attribute(s), {m} measure(s), {f} formula(s)
  Parameters: {p}  ({names or "none"})
  Spotter (AI search): enabled / disabled   # from Step 5.5

Formula translations ({F} total):
  ✓ {name}  [{tier}]:        {tableau_expr}  →  {ts_expr}
  ⚙ {name}  [pass-through]:   {tableau_expr}  →  {sql_*_op expr}
       (works only with SQL Passthrough Functions enabled in ThoughtSpot admin)
  ⚠ {name}  [untranslatable]: OMITTED — {reason}

Sets ({S}) — semantic reinterpretations, REVIEW each matches intent:   # omit section if no sets
  ✓ {name} → column set ({GROUP_BASED, N members | NE except | {Null} | formula-col anchor})  [what to verify]
  ✓ {name} → query set (rank {desc|asc} by SUM {measure}, N={param|literal})   [verify ranking + N]
  ⚙ {name} → interactive filter on {anchor} (set control; IF-[Set] calcs collapsed to measure+filter)
  ⊘ {name} → DEFERRED ({intersect/computed except 2c | set action}) — manual

Will NOT migrate ({K}):
  - {name}: {reason}
  # if none: "Nothing omitted — full coverage."

Dashboards: {N}  (liveboard migration offered after import)

Blended models: {N} model(s) merged from {M} datasources via data blending
  - {primary_ds} ← {secondary_ds} on [{col1}, {col2}]  (LEFT_OUTER, {cardinality})

  ⚠ HIGH-risk blend(s): {N}  (both sides have measures — fact×fact)
    {primary} ← {secondary}: Tableau aggregates {secondary} to {link_cols} grain
    before joining. ThoughtSpot joins at row level — aggregation may diverge.
    Options:
      R — proceed with row-level join (ThoughtSpot chasm trap may handle it)
      S — create a SQL View that pre-aggregates the secondary to the linking grain
      M — keep as separate models (no blend merge)

Proceed?
  yes   — import the table + model TMLs
  no    — cancel
  file  — write the TMLs to /tmp/ts_tableau_mig/output/{workbook_name}/ without importing
```

## Phase 1.5 — base model review checkpoint

Shown after Phase 1 (base model, no formulas) succeeds, before Phase 2 (formulas):

```
Base model imported: {model_name}
  {base_url}/#/data/tables/{model_guid}

  Tables:     {N} bound to connection "{connection_name}"
  Columns:    {N} physical columns ({a} attribute, {m} measure)
  Joins:      {N}
  Parameters: {names or "none"}

  Please verify in ThoughtSpot:
    1. Open the model link above
    2. Check that all tables show data (no "table not found" errors)
    3. Confirm column types look correct (especially date columns)
    4. If joins exist, try a search spanning two tables

  Ready to add {F} translated formulas (Phase 2)?
    yes    — proceed to formula import
    search — try some searches first (suggest test questions)
    no     — stop here; model is ready for manual formula work
```

## Phase 2 — `build-model --existing-guid` JSON output shape

```json
{
  "formulas_translated": N,
  "formulas_skipped": N,
  "formulas_filtered": N,
  "formulas_added": N,
  "formulas_skipped_existing": N,
  "formulas_dropped_on_import": [
    {
      "name": "Formula Name",
      "expr": "attempted ThoughtSpot expression",
      "error": "ThoughtSpot error message",
      "original_tableau": "raw Tableau expression"
    }
  ],
  "validation_warnings": [...],
  "updated_model_guid": "guid",
  "import_status": "OK"
}
```

## Fast mode — Phase 2 complete report

```
Phase 2 complete:
  ✅ {formulas_added} formulas imported successfully
  ⏸ {len(dropped)} formulas parked (will appear in final report)

Parked formulas:
  | # | Name | Error (summary) |
  |---|------|-----------------|
  | 1 | {name} | {error truncated to ~60 chars} |

These are recorded for the migration report. You can attempt fixes
after the migration is complete (Step 12.5).

Proceeding to model confirmation...
```

## Complete mode — fix cycle complete report

```
Fix cycle complete:
  ✅ {fixed_count}/{total_attempted} formulas fixed and imported
  ⏸ {remaining_parked} formulas remain parked

Fixed:
  - {name1}: {what was changed}

Still parked:
  - {name2}: {error after last attempt}
```
