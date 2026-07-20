# Design — Codify `ts-convert-to-databricks-mv` (agentic → deterministic)

**Date:** 2026-07-16
**Branch:** `wip/to-databricks-mv-codify`
**Status:** Design approved; pending spec review → implementation plan

---

## Problem

The `ts-convert-to-databricks-mv` converter emits its Databricks Metric View
(`CREATE OR REPLACE VIEW … WITH METRICS`) DDL **agentically** in both runtimes —
the LLM reads the mapping files and hand-writes the YAML, the DDL, and the
ThoughtSpot-formula → Databricks-SQL translation (CLI SKILL Step 7 "auto",
Genie SKILL "translate formulas, generate the DDL").

This is exactly the "agentic → deterministic" target of repo-audit angle #11(b):
mechanical transformation (parse, type-map, formula-rewrite, DDL emission)
currently executed by the LLM, codifiable as deterministic Python for faster,
cheaper, reproducible, testable output.

The **from**-direction is already codified this way (BL-063): pure modules in
`tools/ts-cli/ts_cli/databricks/` (`mv_parse`, `mv_sql`, `mv_translate`,
`mv_tml`, `mv_build_model`, …), used directly by `ts databricks build-model` in
the CLI and **vendored** into the Genie notebook `databricks_mv_lib.py` by
`agents/databricks/build_mv_lib.py` at deploy time. This design mirrors that
pattern in reverse to close the loop.

## Goals

- Deterministic emission of Metric View DDL from a ThoughtSpot Model, running in
  **both** runtimes (CLI + Databricks Genie agent) from **one** source of truth.
- **Full** reverse formula translation: a TS-formula-grammar → Databricks-SQL
  translator (the mirror of the from-direction's `translate_sql_expr`), covering
  aggregations, windows, LOD, conditionals — not just structural mechanics.
- Merge gated on **live numeric fidelity**: the emitted MV must produce the same
  numbers as the source ThoughtSpot Model on a live Databricks warehouse.

## Non-Goals

- Executing the DDL on Databricks from the pure core. Execution needs the
  Databricks CLI/API (not vendorable) and stays a separate SKILL step
  (file-only vs. run, Preview-channel check).
- A shared cross-platform TS-formula frontend for a future
  `ts-convert-to-snowflake-sv`. Deferred until a second consumer exists
  (anti-speculation rule). Extract then, not now.
- Any CoCo/Snowsight variant — to-databricks-mv is an existing documented
  `EXPECTED_DIVERGENCES` entry (Databricks CLI absent in Snowsight).

---

## Architecture

One source of truth, two runtimes. All conversion logic is **pure** (`stdlib` +
PyYAML only — no HTTP, no typer, no `ts_cli.client`), so it vendors into the
Genie notebook unchanged.

### New pure modules — `tools/ts-cli/ts_cli/databricks/`

| Module | Responsibility |
|---|---|
| `mv_emit_expr.py` | TS-formula **tokenizer + parser → AST**. Grammar: bracket refs `[Table::Col]`, function calls, operators, `if/then/else`, `= null` / `!= null`, string/number literals, cross-formula refs. |
| `mv_emit_sql.py` | **AST → Databricks SQL** expression string, per `ts-databricks-formula-translation.md`. Emits aggregations, `… OVER (PARTITION BY …)` windows, `CASE`, etc. Raises `UntranslatableError` for constructs with no Databricks equivalent. |
| `mv_emit.py` | Orchestration: Model-TML dict → classify columns (dimension / measure / formula) → reverse type-map → translate each formula → assemble Metric View **YAML** doc (source, joins, dimensions, measures, filter). Returns `(yaml_doc, skipped[], warnings[])`. |
| `mv_build_view.py` | YAML doc → `CREATE OR REPLACE VIEW … WITH METRICS LANGUAGE YAML AS $$…$$` **DDL** string; summary + Unmapped-Report builder. This is the pure core the command and the Genie skill call. |

Reuses existing closure members: `formula_common.py`, `tml_common.py`,
`tml_lint.py`.

**Structure decision:** parallel mirror — new single-purpose, one-directional
modules alongside the from-modules. Keeps each file easy to hold in context,
test, and vendor. (Rejected: bidirectional modules — bloats clean single-purpose
files; shared AST core — over-engineering for an unscheduled second consumer.)

### New CLI command — `ts databricks build-mv`

Thin typer wrapper in `commands/databricks.py`:

- **Input:** exported Model TML (via `ts tml export --fqn --associated` — the
  HTTP call stays in the CLI/client layer), connection/warehouse/output args.
- **Calls** the pure `mv_emit` + `mv_build_view`.
- **Output:** writes the `.sql` file and emits JSON to stdout; diagnostics to
  stderr (ts-cli output conventions).
- **Emit-only** — does not execute the DDL on Databricks.

### Vendor wiring — `agents/databricks/build_mv_lib.py`

Add the four modules to `CLOSURE` (dependency order) and update the header
docstring's function list. `assert_no_duplicate_top_level_names` guards
collisions with the from-modules (parallel-mirror uses distinct names; shared
helpers already single-owner in `formula_common`/`tml_common`).

### Both runtimes

- **CLI:** SKILL emit step → `ts databricks build-mv`.
- **Genie:** SKILL → `%run databricks_mv_lib` → call vendored public functions
  (same names as the pure module entry points). Genie fetches TML via
  `%run ts_client`, passes the dict to the vendored functions.

---

## Data flow

1. **Fetch** Model TML → dict. CLI: `ts tml export --fqn --associated`;
   Genie: `ts_client` export.
2. **Emit** `mv_emit(model_dict, …)` → MV YAML doc + `skipped[]` + `warnings[]`.
3. **Build** `mv_build_view(yaml_doc)` → DDL string.
4. **Present** — write `.sql` / print DDL + Unmapped Report.
5. *(SKILL, separate)* optionally execute the DDL on the Databricks warehouse
   (Preview-channel check first).

Steps 2–4 are identical across runtimes by construction (same pure functions).

---

## Error handling

- **Per-formula** `UntranslatableError` → omit that measure/dimension, record in
  `skipped[]` with a reason → surfaced in the **Unmapped Report** at the review
  checkpoint. Never silently dropped; never aborts the whole conversion.
- **Structural** failures (no source table, unknown top-level construct,
  duplicate display names) → **fail loud** with a clear message.
- **DDL invariants codified**, not left to the LLM: `WITH METRICS LANGUAGE YAML
  AS $$` (not `WITH METRICS AS $$`), Preview-channel note, no-duplicate-display-
  name — lifted from the current SKILL's checklist. Optionally run the emitted
  DDL through the existing `lint-ddl` gate.

---

## Testing

### 1. Unit (`tools/ts-cli/tests/`, no live instance)

Per-construct golden tests for each new module: parse (`mv_emit_expr`), emit-SQL
(`mv_emit_sql`), model→YAML (`mv_emit`), YAML→DDL (`mv_build_view`). Plus a cheap
**round-trip oracle** where feasible — TS → new to-translator → SQL → existing
from-translator → TS — to catch regressions for free even though the merge gate
is live.

### 2. Vendor (`agents/databricks/tests/test_vendor_mv_lib.py`)

New modules compile self-contained in the concatenated namespace
(`test_source_is_self_contained`) + an end-to-end emit through the vendored lib.

### 3. Live numeric fidelity — **the merge gate**

Reuse the from-direction harness:
- Databricks: catalog `agent_skills`, fixtures `window_fixture` / `ratio_fixture`,
  profile `ts-production`, warehouse `c6ed539a60038b93`.
- ThoughtSpot: profile `se-thoughtspot`.

Procedure: seed fixtures → point a TS Model at them → `ts databricks build-mv` →
create the MV on Databricks → run a battery of equivalent queries (grains,
filters, windows) against **both** the TS Model (SpotQL) and the Databricks MV
(SQL) → assert equal numbers. Recorded in
`docs/audit/2026-07-16-dbx-to-fidelity-matrix.md` following the
`2026-07-09-dbx-semantic-claim-matrix.md` template (statement ledger + teardown
discipline).

Built as a **repeatable harness** so it doubles as the skill's smoke test
(`tools/smoke-tests/smoke_ts-convert-to-databricks-mv.py`) and begins
un-parking audit angle #15 (conversion fidelity) for the to-direction.

### Stays agentic (deliberately not codified)

Review checkpoints, ambiguous naming/synonym judgment, and user choices
(file-only vs. execute, Preview-channel confirmation). The codified path is
parse → translate → emit → DDL only.

---

## Deliverables & repo-consistency (change-impact map)

- **ts-cli:** 4 new modules + `build-mv` command + `README.md` entry + version
  bump (`ts_cli/__init__.py` **and** `pyproject.toml`) + unit tests.
- **Vendor:** `build_mv_lib.py` `CLOSURE` + docstring; `test_vendor_mv_lib.py`.
- **SKILLs:** `agents/cli/ts-convert-to-databricks-mv/SKILL.md` and
  `agents/databricks/skills/ts-convert-to-databricks-mv/SKILL.md` rewired to the
  codified path; version bump + changelog each.
- **Coverage matrix:** `references/coverage-matrix.md` updated (enforced by
  `check_coverage_matrix.py`).
- **Open items:** live-fidelity items tracked until VERIFIED.
- **Repo:** `CHANGELOG.md` entry; refresh
  `worked-examples/databricks/ts-to-databricks.md` if output shifts; currency
  anchor on any edited mapping.
- **CoCo:** no change (existing `EXPECTED_DIVERGENCES` entry).

## Merge criteria

1. All `references/open-items.md` items VERIFIED (or explicitly deferred).
2. All validators pass (`python3 tools/validate/check_*.py --root .`).
3. Smoke test exists and passes.
4. Live numeric fidelity matrix passes end-to-end.
5. `pytest tools/ts-cli/tests/` + vendor tests green;
   `check_version_sync.py` clean.

## Open questions

- None blocking. The exact query battery for the fidelity matrix (which
  grains/filters/windows) will be enumerated in the implementation plan against
  the fixture data.
