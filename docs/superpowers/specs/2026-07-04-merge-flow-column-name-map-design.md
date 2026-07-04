# Design — apply `--column-name-map` in the merge (`--existing-guid`) flow

_Date: 2026-07-04 · Skill: `agents/cli/ts-convert-from-tableau` · CLI: `tools/ts-cli` (`ts tableau build-model --existing-guid`)_

## Problem

The tentpole-model write-path live test (se-thoughtspot, model `857ed02b`, view
`vw_dim_promo`) imported the base model cleanly via GENERATE + reconcile, but Phase 2
(formula import via `ts tableau build-model --existing-guid`) landed only 64/119 formulas
— ~55 were filtered/dropped.

#183 added Tier-2 reconciliation (`--reconcile-table` + a human-confirmed
`--column-name-map`, e.g. `DISCOUNT_RED_DOLLAR` → `DM_DISCOUNT_RED_DOLLAR`) and wired it
into the GENERATE path (`_generate_flow`) only. The MERGE path (`_merge_flow`, which backs
the skill's Phase-2 formula import) **never receives or applies the confirmed
`--column-name-map`.**

Trace (`tools/ts-cli/ts_cli/commands/tableau.py`):

- `col_name_map` is loaded (`_load_column_name_map`) and passed into `_process_datasource`
  (param `col_name_map`), but forwarded **only** to `_generate_flow` (line 836). The
  `_merge_flow` call (lines 805–817) does not pass it.
- `_merge_flow` → `prepare_formulas_for_merge(cleaned_formulas, ctx)`
  (`ts_cli/tableau/build_model.py`) runs `strip_csq_suffixes` then `fix_bare_refs`, which
  qualifies bare column refs against the **existing model's** `col_lookup`.
- A formula that references the datasource's original name (`[DISCOUNT_RED_DOLLAR]`) cannot
  be qualified — the existing model has `DM_DISCOUNT_RED_DOLLAR`, not
  `DISCOUNT_RED_DOLLAR`, so `fix_bare_refs` leaves it bare. `filter_unresolvable_formulas`
  then drops it as a bad bare ref, and formula-to-formula dependents cascade-drop.

**Not the gap (verified, not assumed):** CSQ-suffix stripping. `prepare_formulas_for_merge`
already calls `strip_csq_suffixes` (regex `_CSQ_IN_REF`), which strips
`[col (Custom SQL Query N)]` → `[col]` inside bracketed refs — and handles the no-digit
`[Sales (Custom SQL Query)]` form that reconcile's `_SUFFIX` (requiring `\d+`) does not. So
the merge path's CSQ handling is already correct and slightly broader; no change is needed
there. The sole missing transform is the confirmed **column-name-map rewrite**.

## Goal

Apply the same human-confirmed `--column-name-map` in the MERGE path that GENERATE already
applies, so Phase-2 formula import resolves formulas whose source-column names were renamed
during reconcile. Recover the ~55 dropped formulas on the tentpole model (minus any
genuinely unmigratable — e.g. refs to columns truly absent from the target view).

Non-goals: `--reconcile-table` in merge mode (the existing model **is** the target schema,
so no fuzzy suggestion pass is needed — only the already-confirmed map is applied); any
change to CSQ stripping, formula translation semantics, or `filter_unresolvable_formulas`.

## Approach

**A (chosen): apply the confirmed `--column-name-map` to formula expressions in
`_merge_flow`, reusing a new pure helper in `reconcile.py`.** Before
`prepare_formulas_for_merge`, rewrite each formula's column refs by the confirmed map
(`[old]` → `[new]`, `[t::old]` → `[t::new]`). `fix_bare_refs` then qualifies the renamed
ref against the existing model's real columns, and `filter_unresolvable_formulas` keeps it.
Genuinely-unresolvable formulas (refs to columns not on the target) still drop, correctly.
This makes reconcile consistent across both flows, reuses #183's `reconcile.py`, and keeps
the skill's proven two-phase structure. Smallest change that fixes the root cause.

**B (rejected): have the skill's Phase 2 import the GENERATE `phase1+` files** (already
reconciled) instead of re-deriving via `--existing-guid`. Avoids a CLI change but reverses
#180's "phase1+ unused" decision and changes the shape of the two-phase flow. More
disruptive than the actual defect warrants.

## Scope

The rewrite must apply the map the **same way** GENERATE's `apply_reconciliation` does, so
both flows agree:

- Match a column ref inside brackets, both bare (`[DISCOUNT_RED_DOLLAR]`) and
  table-qualified (`[vw_dim_promo::DISCOUNT_RED_DOLLAR]`), and rewrite the **column part**
  to the mapped name, preserving any `table::` qualifier.
- Whole-token match only — `DISCOUNT_RED_DOLLAR` must not partial-match
  `DISCOUNT_RED_DOLLAR_PCT`. Match the full bracket content or the full post-`::` segment.
- Idempotent: applying an already-applied map is a no-op (no `old` refs remain).
- Applied to formula expressions only. Column definitions in the existing model are already
  reconciled (they were remapped at GENERATE time), so the merge path does not touch
  `columns[]`.

## Code shape

- **`ts_cli/tableau/reconcile.py`** — new pure `rewrite_formula_refs(formulas, name_map)
  -> None` (mutates each `f["expr"]` in place, matching the in-place convention of
  `strip_csq_suffixes`), or the non-mutating `(formulas, name_map) -> list[dict]` form —
  the plan picks one and stays consistent. Extract the ref-rewrite regex logic from
  `apply_reconciliation` so GENERATE and MERGE share exactly one implementation (refactor
  `apply_reconciliation` to call the shared helper; no behavior change to GENERATE).
- **`_merge_flow`** (`commands/tableau.py`) — add a `column_name_map: Optional[dict] = None`
  parameter; when non-empty, call `rewrite_formula_refs(cleaned_formulas, column_name_map)`
  **before** `prepare_formulas_for_merge`, and echo a one-line count of formulas rewritten
  to stderr (consistent with the existing `bare_fixed` / filter / merge echoes).
- **`_process_datasource`** (`commands/tableau.py`) — forward `col_name_map` to the
  `_merge_flow(...)` call (lines 805–817). No new loading: `col_name_map` is already loaded
  and in scope.
- **`build_model_cmd` / arg validation** — `--column-name-map` is already accepted
  independently of `--reconcile-table` (only `--reconcile-plan` requires `--reconcile-table`;
  only `--table-name-map` warns under `--existing-guid`). Confirm no path rejects
  `--column-name-map` with `--existing-guid`; if a stray guard exists, remove it. The
  "`--reconcile-table` is ignored with `--existing-guid`" notice stays (still true — merge
  needs only the confirmed map, not a fresh suggestion pass).
- **SKILL** `agents/cli/ts-convert-from-tableau/SKILL.md` (Step 7, Phase 2) — pass
  `--column-name-map {workdir}/column_name_map.json` to the `--existing-guid` call so the
  Phase-2 import applies the same confirmed map the base-model GENERATE used. Note in the
  step that the map is now honored in merge mode.

## Testing & compliance

- **Unit — `rewrite_formula_refs`:** bare ref remapped (`[DISCOUNT_RED_DOLLAR]` →
  `[DM_DISCOUNT_RED_DOLLAR]`); qualified ref remapped preserving the table
  (`[vw_dim_promo::DISCOUNT_RED_DOLLAR]` → `[vw_dim_promo::DM_DISCOUNT_RED_DOLLAR]`);
  whole-token safety (`DISCOUNT_RED_DOLLAR_PCT` untouched by a `DISCOUNT_RED_DOLLAR`
  mapping); empty map is a no-op; idempotence (double-apply == single-apply); a ref not in
  the map is left unchanged.
- **Unit — merge integration:** a `cleaned_formulas` list containing a renamed-column ref,
  run through `rewrite_formula_refs` + `prepare_formulas_for_merge` +
  `filter_unresolvable_formulas` against an `existing_cols` set that has the mapped name,
  survives the filter (kept); without the rewrite it is dropped (guards the regression).
- **Refactor guard:** existing `apply_reconciliation` tests still pass after extracting the
  shared helper (proves GENERATE behavior unchanged).
- **Live end-to-end:** re-run Phase 2 on the tentpole model (`857ed02b`, `vw_dim_promo`)
  with `--column-name-map`; confirm the recovered formula count (target ≈ 119 minus
  genuinely-absent-column formulas) and that dropped names are only true non-migratables.
  se-thoughtspot uses a browser TOKEN (OIDC/SSO — password hangs); refresh mid-session if
  authed calls return empty-body / JSONDecodeError.
- **Version/docs:** bump ts-cli (`__init__.py` + `pyproject.toml`), skill `## Changelog`,
  `tools/ts-cli/README.md` if the `--existing-guid` + `--column-name-map` combination is
  worth a note, repo `CHANGELOG.md`. Branch `feat/tableau-merge-flow-reconcile`; PR to main
  (no direct push).
- `pytest tools/ts-cli/tests/` + `python tools/validate/check_version_sync.py` before commit.

## Sequencing (phases)

1. Extract the shared ref-rewrite helper into `reconcile.py`
   (`rewrite_formula_refs`); refactor `apply_reconciliation` to use it; unit tests +
   refactor guard.
2. Thread `column_name_map` into `_merge_flow`; apply before `prepare_formulas_for_merge`;
   forward from `_process_datasource`; merge-integration unit test.
3. SKILL Step 7 Phase 2 rewire (pass `--column-name-map`); README note if warranted.
4. Version/changelog bumps; live end-to-end re-run of tentpole Phase 2.

## Risks

- **Whole-token matching** — a naive substring replace would corrupt refs that share a
  prefix. Mitigated by the whole-bracket / full-post-`::`-segment match and the explicit
  whole-token unit test.
- **Double application** (map applied in both a pre-pass and inside `prepare_...`) — the map
  is applied in exactly one place (`_merge_flow`, before `prepare_...`); `prepare_...` does
  not take the map. Idempotence test covers accidental re-runs.
- **Refactor of `apply_reconciliation`** — extracting the shared helper could regress
  GENERATE; mitigated by keeping the existing `apply_reconciliation` tests green.
