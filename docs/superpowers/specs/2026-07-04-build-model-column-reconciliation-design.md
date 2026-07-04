# Design — `build-model` column-schema reconciliation (sqlproxy/published datasources)

_Date: 2026-07-04 · Skill: `agents/cli/ts-convert-from-tableau` · CLI: `tools/ts-cli` (`ts tableau build-model`)_

## Problem

A live migration of `CPG+Merch Promotion Performance.twbx` (2 published/`sqlproxy`
datasources, 282 calcs) surfaced that `ts tableau build-model` emits column references
that do not bind to the real target table. All three failures trace to one root cause:
**`build_model_tml` is a pure, offline function that assembles columns / `column_id`s /
formula expressions straight from the Tableau parse, with no knowledge of the real target
schema.** Concretely, against the existing view `vw_dim_promo` (APJ_TAB):

1. **Custom-SQL suffixes leak into `column_id`** — e.g. `CUSTOMERS_RED_PERCENT (Custom SQL
   Query2)`; the real column is `CUSTOMERS_RED_PERCENT`. Published datasources carry these
   per-query-instance suffixes verbatim.
2. **`__tableau_internal_object_id__*` junk columns** are emitted as real columns.
3. **Bare `column_id`** — `build_model_tml` emits `column_id: CAMPAIGN_ID`; ThoughtSpot
   **rejects every column** ("column_id/formula_id values are incorrect") when the model
   references a *pre-existing* table. Table-qualified `column_id: vw_dim_promo::CAMPAIGN_ID`
   validates cleanly (confirmed live: bare → all 56 rejected; qualified → `OK`).
4. **Name divergence** — the datasource's `DISCOUNT_RED_DOLLAR` vs the view's
   `DM_DISCOUNT_RED_DOLLAR`; genuinely-absent columns (`ORDER_ID`, `UPDATED_AT`).

These were invisible offline; only a live import against the real view exposed them. The
base model was salvaged by a one-off hand reconcile — this spec codifies that so the whole
migration (both models + formulas + future sqlproxy workbooks) runs through the normal
pipeline.

## Goal

Make `ts tableau build-model` produce column references that bind to the real target
schema, splitting the work into always-correct deterministic cleanups and an opt-in,
schema-aware reconciliation whose semantic judgment (name divergences) is confirmed by a
human in the skill layer.

Non-goals: audit-mode set classification (BL-088, separate); changing the translate
pipeline's formula semantics; connection-introspection for create-new-table flows (the v2
`connection/search` schema is empty for OAuth/PKCE connections — unreliable, out of scope).

## Scope — the two tiers

### Tier 1 — Deterministic cleanups (always-on, no schema needed)

Applied to `model_tables[].columns[]`, `model.columns[]`, **and** formula expressions
consistently, for every `build-model` run:

- **Strip** `(Custom SQL Query N)` suffixes from column names and from `[table::col]`
  references inside formula expressions.
- **Drop** `__tableau_internal_object_id__*` junk columns, and any formula that references
  one.
- **Qualify** `column_id` as `table::col` (single-table model → the one `model_tables`
  name). Fixes failure (3).
- **Dedupe** columns that collapse to the same name after stripping (keep first; drop the
  rest and repoint/drop dependent formulas).

Rationale: the suffixes and junk are never valid ThoughtSpot column names regardless of
target, and qualified `column_id` is the canonical form (matches the skill's Step 5b
template). **Risk to verify (plan):** qualifying `column_id` must not regress the normal
create-table-alongside flow — a test imports a normal (non-sqlproxy) generated model and
confirms it still binds. Suffix/junk stripping only changes sqlproxy-sourced output (those
tokens don't occur otherwise), so low risk to existing migrations.

### Tier 2 — Schema-aware reconciliation (opt-in: `--reconcile-table <guid>`)

For the consultant / reuse-existing-view case (no live connection to the real source; a
pre-built view or table stands in). When the flag is omitted, behaviour is Tier-1 only and
otherwise unchanged.

1. **Fetch** the target table object's real logical column names by exporting it via the
   API (`ts tml export <guid>` equivalent, in-process).
2. **Partition** the Tier-1-cleaned columns into present-on-target (keep) vs absent.
3. **Suggest mappings** for absent columns — fuzzy-match each against the target column set
   (case-insensitive; add/strip common prefixes e.g. `DM_`; token-overlap score) → a
   ranked suggestion with a confidence.
4. **Plan mode** (`--reconcile-plan`): emit JSON and exit **without writing TML**:
   ```json
   {
     "target_columns": N,
     "matched": ["CAMPAIGN_ID", ...],
     "suggested_mappings": [{"from": "DISCOUNT_RED_DOLLAR", "to": "DM_DISCOUNT_RED_DOLLAR", "confidence": 0.86}],
     "unmatched_drop": ["ORDER_ID", "UPDATED_AT"],
     "formulas_to_drop": ["<names referencing dropped/unmapped columns>"]
   }
   ```

### Confirmation lives in the skill, not the CLI

`build-model` never prompts. The `ts-convert-from-tableau` skill (Step 3.5 / 5b):
1. Runs `build-model --reconcile-table <guid> --reconcile-plan` and reads the JSON.
2. **Presents** `suggested_mappings` (with confidence) + `unmatched_drop` +
   `formulas_to_drop` to the user, who confirms / edits / rejects each mapping.
3. Writes the confirmed map to `column_name_map.json`.
4. Re-runs `build-model --reconcile-table <guid> --column-name-map column_name_map.json`
   to **apply**: remap confirmed names, drop unmapped-absent columns + their dependent
   formulas (reported as parked), qualify `column_id`s, write phased TMLs.

This puts the deterministic mechanics (fetch, fuzzy-suggest, apply) in the CLI and the
semantic judgment (which suggestion is right) with the human — the same split the rest of
the skill uses.

## Formula consistency

The same transform applies to formula expressions: strip suffixes, apply the confirmed
`--column-name-map`, drop any formula that (after remap) still references a column absent
from the target, and qualify column refs. Dropped formulas are returned in the result
JSON's dropped/parked list and surface in the Step 12 report — no silent loss.

## Code shape

- **New pure module `ts_cli/tableau/reconcile.py`** (no I/O, unit-testable):
  - `clean_column_name(name) -> str | None` — strip suffix; return `None` for junk.
  - `qualify_column_id(table, col) -> str`.
  - `suggest_column_mappings(absent: list[str], target: set[str]) -> list[dict]` — fuzzy,
    with confidence.
  - `apply_reconciliation(columns, formulas, target_cols, name_map) -> (kept_columns,
    kept_formulas, dropped_report)` — the deterministic apply.
- **`build_model_tml`** (`model_builder.py`): emit qualified `column_id`s (Tier-1). The
  cleaned/reconciled columns + formulas are fed in from the generate flow, so the pure
  assembler stays pure.
- **`_generate_flow` / `build_model_cmd`** (`commands/tableau.py`): always apply Tier-1;
  when `--reconcile-table` is set, fetch the target columns (live) and run reconcile in
  plan or apply mode; add options `--reconcile-table`, `--reconcile-plan`,
  `--column-name-map`.
- **SKILL** `agents/cli/ts-convert-from-tableau/SKILL.md`: document the plan → confirm →
  apply flow for published/sqlproxy datasources bound to an existing table (Step 3.5 / 5b);
  note bare-vs-qualified is now handled automatically.

## Testing & compliance

- Unit tests for every `reconcile.py` function: suffix strip, junk drop, qualify, dedupe,
  fuzzy suggest (incl. the `DM_` prefix case), apply (drop-absent + dependent-formula
  cascade). Pure, no live instance.
- Regression test: a normal (non-sqlproxy) generated model still imports with qualified
  `column_id`s (guards the Tier-1 risk).
- The CPG workbook's shapes (`CUSTOMERS_RED_PERCENT (Custom SQL Query2)`,
  `DISCOUNT_RED_DOLLAR`→`DM_...`, `__tableau_internal_object_id__`, `ORDER_ID` absent) as
  fixtures.
- One live end-to-end check on se-thoughtspot: reconcile-plan → apply → import the tentpole
  model (base + formulas) against `vw_dim_promo`.
- Version bumps: ts-cli (`__init__.py` + `pyproject.toml`), skill `## Changelog`,
  `tools/ts-cli/README.md` (new flags), repo `CHANGELOG.md`. Branch
  `feat/tableau-build-model-reconcile`; PR to main.

## Sequencing (phases)

1. `reconcile.py` pure functions + unit tests (clean/qualify/suggest/apply).
2. Tier-1 always-on in the generate flow + `build_model_tml` qualified `column_id` +
   normal-flow regression test.
3. `--reconcile-table` / `--reconcile-plan` / `--column-name-map` wiring in the command
   (fetch target columns; plan vs apply).
4. SKILL Step 3.5/5b rewire (plan→confirm→apply); README.
5. Version/changelog + live end-to-end on the tentpole model.

## Risks

- **Qualified `column_id` regressing the normal flow** — mitigated by the regression test
  (Phase 2); if the normal create-alongside flow needs bare IDs, qualify only when a
  reconcile/existing-table context applies.
- **Fuzzy suggestion mis-matching** — mitigated by human confirmation in the skill; the CLI
  only *suggests*, never auto-applies an unconfirmed mapping.
- **Target-table export shape** — the export gives logical column `name`s; reconcile matches
  on those. If a model must bind to `db_column_name` instead, adjust the fetch to read both.
