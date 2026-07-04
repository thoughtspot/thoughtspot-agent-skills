# Design — Codify highest-value/risk inline logic in `ts-convert-from-tableau`

_Date: 2026-07-04 · Skill: `agents/cli/ts-convert-from-tableau` · CLI: `tools/ts-cli`_

## Problem

`ts-convert-from-tableau/SKILL.md` is 4,297 lines. A full review found that
substantial **deterministic** work is still performed by the LLM at runtime —
inline Python parsing/graph blocks and a duplicated audit-vs-migrate formula
classifier — even though the repo's convention (`.claude/rules/ts-cli.md`,
CLAUDE.md "CLI-first rule", repo-audit Angle 11 "agentic → deterministic") is to
codify mechanical transformations into the `ts` CLI.

The most damaging instance is a **correctness divergence**: audit mode
(Step A3) classifies calculated fields into translation tiers using one
implementation (a markdown tier table + regex list, L254–321), while migrate
mode (Step 5b) uses a different one (`ts tableau translate-formulas`). The two
can disagree — an audit can report a formula as translatable that the migration
then silently skips, or vice versa. This is repo-audit **Angle 9 (conversion
consistency)**, not cosmetic cleanup.

## Goal

1. Make audit and migrate **provably agree** on formula translatability (single
   shared classifier, guarded by a parity test).
2. Remove the inline Python the model executes at runtime, moving it into tested
   `ts_cli/tableau` functions behind thin CLI commands.

Non-goals (deferred follow-ups): TML-template emission (category B), relocating
spec tables to `agents/shared/` (category C), and the skill-split decision.

## Scope — what is codified now

Catalogued inline items addressed by this effort:

| ID | SKILL.md loc | What | Disposition |
|----|--------------|------|-------------|
| D  | A3 L254–321 | Audit tier table + classifier regexes (duplicate of translate) | Shared classifier (Component 2) |
| A1 | 3e L876 | Blend-graph extraction | `extract_blends()` (Component 1) |
| A2 | 3f L962/997 | Table-calc addressing + worksheet overrides | `extract_table_calc_addressing()` (Component 1) |
| A3 | 3g L1039 | Orphan-calc detection (direct + transitive) | `detect_orphan_calcs()` (Component 1) |
| A4 | 5b L1696 | Blend connected-components (BFS) | `build_blend_components()` (Component 3) |
| A5 | 5b L1733 | ds→table mapping | `map_ds_to_tables()` (Component 3) |
| A6 | 5b L1755 | Blend-join derivation (+ cardinality L1779, renames L1787) | `derive_blend_joins()` (Component 3) |
| A7 | 6 L2802 | Payload builder (phase-0 glob) | `--dir` on `ts tml import` (Component 4) |
| A8 | 7 L2981 | Same payload builder, duplicated verbatim | `--dir` (Component 4) |
| A9 | 11 L3951 | Liveboard payload builder | `--dir --pattern` (Component 4) |

Explicitly **out of scope** (follow-ups): category B TML-template emission (table
5a, blend-merge model 5b, sql_view 5c, three cohort/set templates, liveboard 10c,
KPI `client_state_v2` blob 10a); category C spec-table relocation; the
three-component skill split (revisit once this lands and the file has shrunk).

## Already codified (context — not changed here)

- Formula translation → `ts tableau translate-formulas` (`functions.py`,
  `conditionals.py`, `lod.py`, `dag.py`, …)
- Model build/merge + Phase-2 formula import → `ts tableau build-model`
- Core TWB parse → `parse_twb()` (params, tables, columns, joins, calcs,
  column→table map, type mapping)
- Pre-import invariant lint → `ts tml lint`

Verified 2026-07-04: no `parse` or `classify` command exists yet (both net-new);
`check_skill_cli_usage.py` only matches heredocs near *formula* assembly, which is
why the payload-builder heredocs (A7–A9) currently pass.

## Architecture

New CLI spine the skill orchestrates:

```
ts tableau parse  →  ts tableau classify-formulas  →  ts tableau build-model (existing)
```

### Component 1 — `ts tableau parse` (foundation; absorbs A1–A3)

`parse_twb()` already exists and is proven (translate/build-model call it
internally). Expose it as `ts tableau parse {twb} --output parsed.json`, and add
three pure extractors whose results become fields in the parse JSON:

- `extract_blends(root) -> blend_graph` — `{source_ds: [{target_ds, column_mappings}]}` (A1)
- `extract_table_calc_addressing(root) -> {column_level, ws_overrides}` (A2)
- `detect_orphan_calcs(datasource) -> set[str]` (direct + transitive) (A3)

**SKILL.md effect:** Step 3 collapses to "run `ts tableau parse`"; Steps 3e/3f/3g
delete their inline Python and read the corresponding fields.

### Component 2 — shared classifier + `ts tableau classify-formulas` (fixes D)

Extract one pure `classify_formulas(parsed) -> list[FormulaClass]` in a new
`ts_cli/tableau/classify.py`, returning per formula: **tier, reason, dependency
level, complexity score, orphan flag**. It reuses the *same* detection
(`functions.py` / `validate.py` / `dag.py`) that `translate-formulas` uses;
`translate-formulas` is refactored to call it internally so there is exactly one
detector. Expose `ts tableau classify-formulas --input parsed.json --output
classification.json` (accepts a `.twb` directly too, running parse first).

The regex/detection list currently at SKILL.md L268–321 moves *into* `classify.py`.
The human-readable tier table stays in SKILL.md as reference (relocation to shared
is deferred category C) but is no longer *executed*.

**SKILL.md effect:** Step A3 → run the command; Step A4 report built from the
JSON; Step 7 review reuses the same tiers.

**Correctness guarantee (the teeth on D):** a unit test asserts every formula's
`classify-formulas` tier is consistent with its `translate-formulas` outcome
(translatable tiers ⇒ translated; untranslatable tier ⇒ skipped). A divergence is
a failing test, not a silent audit lie.

**Orphan carve-out:** orphan calcs (Step 3g) are excluded from the `translate-formulas`
verdict entirely and always tiered `orphan`, matching migrate's own exclusion of
orphans from `translate-formulas`/`build-model` — so a syntactically-valid orphan
never gets counted as translatable by audit while migrate silently drops it.

### Component 3 — blend graph helpers, computation only (A4–A6)

Pure functions in `build_model.py`:

- `build_blend_components(blend_graph) -> list[model_group]` (BFS connected components)
- `map_ds_to_tables(datasources) -> (ds_id_to_table, ds_id_to_caption)`
- `derive_blend_joins(model_group, blend_graph, ds_id_to_table) -> list[join]`
  including the cardinality heuristic (SKILL.md L1779) and column-conflict rename
  detection (L1787)

These are folded into the parse output as a `blend_plan` block (components,
ds→table map, joins with suggested cardinality, renames).

**SKILL.md effect:** Step 5b deletes the inline Python (L1696/1733/1755); the
hand-assembly TML template (deferred category B) stays but is populated *from*
`blend_plan`. TML file emission for blends is explicitly NOT codified here.

### Component 4 — payload builder de-dup (A7–A9)

Add `--dir {dir}` to `ts tml import` and `ts tml lint`: read a directory, order
files (tables → sql_views → base models → cohorts), apply phase-0 base-model
selection internally (keep bare `*.model.tml` + `*.phase0.model.tml`, drop
`*.phase1+`), with `--pattern` for the liveboard-only case.

**SKILL.md effect:** Steps 6, 7-phase1, and 11 replace their `python3` heredocs
with the flag (removes 3 blocks, 2 of them identical).

Extend `check_skill_cli_usage.py` to also flag payload-assembly heredocs
(`json.dumps([open(f).read() ...])` over globbed TML files), so this cannot drift
back.

## Testing & compliance

- Unit tests (no live instance, per `.claude/rules/ts-cli.md`) for every new
  function. **The classify↔translate parity test is the keystone.**
- Blend helpers: components/joins for star (A→B, A→C) and transitive (A→B, B→C)
  topologies.
- `--dir`: ordering + phase-0 selection + `--pattern`.
- One end-to-end smoke on a sample `.twb` through parse → classify → build-model.
- Version bumps: `ts-cli` (`__init__.py` + `pyproject.toml`), skill version +
  `## Changelog` entry (at PR time, per `.claude/rules/versioning.md`),
  `tools/ts-cli/README.md` (new commands), `references/coverage-matrix.md` if any
  construct's status changes, repo `CHANGELOG.md` (ts-cli bump). Branch
  `feat/tableau-codify-parse-classify`; PR to main — no direct push.

## Sequencing (phases, each independently shippable)

1. `ts tableau parse` command + A1–A3 extractors + tests.
2. Classifier core + `ts tableau classify-formulas` + **parity test**; rewire
   Step A3/A4/Step 7. ← the D fix.
3. `blend_plan` helpers folded into parse; rewire Step 5b Python.
4. `--dir` on import/lint; rewire Steps 6/7/11; extend validator.
5. Version/changelog/docs/coverage-matrix + smoke.

## Risks

- **Classifier extraction changes translate behaviour.** Mitigation: refactor is
  behaviour-preserving; the parity test + existing translate unit tests gate it.
- **`parse` command scope.** It only *exposes* the already-proven `parse_twb`
  plus three additive extractors — low risk, and it is the natural home for A1–A3
  and the input contract for classify.
- **Blend `blend_plan` shape churn** while B is deferred: the skill still
  hand-assembles blend TML from `blend_plan`, so the block's shape is a contract
  the deferred B work will also consume. Keep it explicit and versioned.
