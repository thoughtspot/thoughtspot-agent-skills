---
name: conversion-consistency-auditor
description: Audit the five ThoughtSpot conversion skills (from/to Tableau, Snowflake SV, Databricks MV) for SEMANTIC consistency against agents/shared/schemas/ts-model-conversion-invariants.md. Run when editing any conversion skill or its shared mappings/schemas, and before merging conversion-skill changes. Reports per-invariant PASS/FAIL with file:line. Read-only.
---

# Conversion Consistency Auditor

Read `agents/shared/schemas/ts-model-conversion-invariants.md` first — it defines the
invariant IDs (I1–I7, N1) and intentional exceptions (EXC1). Then audit each
Model-producing skill against every invariant. Do NOT flag EXC1 differences — they
are deliberate.

## Skills in scope

**Primary (Model-producing — full I1–I7 + N1 audit):**
- `agents/cli/ts-convert-from-tableau/SKILL.md`
- `agents/cli/ts-convert-from-snowflake-sv/SKILL.md`
- `agents/cli/ts-convert-from-databricks-mv/SKILL.md`

**Reference (formula parity only — I7 gate + I5 parity check):**
- `agents/cli/ts-convert-to-snowflake-sv/SKILL.md`
- `agents/cli/ts-convert-to-databricks-mv/SKILL.md`

**Shared (consulted for cross-skill formula consistency):**
- `agents/shared/mappings/tableau/tableau-formula-translation.md`
- `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`
- `agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md`
- `agents/shared/schemas/thoughtspot-model-tml.md`

**Mirrors (must carry the same invariant guidance — see "Mirror parity" below):**
- `agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md`

## Checks (per from-skill)

For each invariant I1–I7 and N1: confirm the skill states the rule (or cites the
invariants doc at `../../shared/schemas/ts-model-conversion-invariants.md`) AND that
its worked TML examples obey it. Report `file:line` of the first violation.

### I1 — Every formulas[] example has a paired columns[] entry with formula_id

Look for any `formulas:` YAML block in the skill. For each `id:` entry under `formulas:`,
confirm there is a `formula_id:` entry in a `columns:` block below it that matches the
same value. If any formula in a code example has no paired `columns[]` entry, report FAIL.

### I2 — No `aggregation:` under any `formulas[]` example

Scan `formulas:` blocks in code examples. Any `aggregation:` field inside a `formulas:`
YAML block is a FAIL — unless the line is clearly labelled as a "WRONG" counter-example
(e.g. followed by a comment `# WRONG`).

### I3 — Computed numeric measures carry `index_type: DONT_INDEX`

For every `columns[]` entry that has a `formula_id:` AND `column_type: MEASURE`, confirm
`index_type: DONT_INDEX` is present in the same entry. This invariant is **advisory** — the
canonical doc and the skills phrase it as *should* / *recommended* (it affects search
behaviour, not import success). Report absence as a `[WARN]`, not a FAIL.

### I4 — Join examples use id == name (exact case) or with: matches name exactly

- If any `model_tables` entry in a code example has both `id:` and `name:` fields,
  confirm they are identical strings.
- If a `with:` join reference is shown, confirm there is a `model_tables` entry whose
  `name:` equals the `with:` value exactly.

### I5 — Distinct-count uses `unique count(...)`, never `aggregation: COUNT_DISTINCT`

Scan the skill for any `aggregation: COUNT_DISTINCT` — its presence on a `columns[]`
entry backed by `column_id:` (not `formula_id:`) is a FAIL. Also check formula
translation tables: the source-language distinct-count function (COUNTD, COUNT(DISTINCT))
must map to `unique count(...)`.

### I6 — Connection references use name, not a GUID

Scan any `connection:` blocks in code examples. `fqn:` inside a `connection:` block is
a FAIL. `name:` is required.

### I7 — A mandatory "consult the reference" gate precedes any untranslatable classification

Look for the word "MANDATORY" (case-sensitive) or "mandatory" within 5 lines before any
step or section that sorts/classifies formulas into tiers or declares them "untranslatable".
If no such gate exists in either the formula-translation step or the audit-mode
classification step, report FAIL with the first "untranslatable" mention.

### N1 — Model name uses bare source name, no TEST_* prefix

Scan the model name instruction in the skill. If `TEST_SV_`, `TEST_MV_`, or any
`TEST_` prefix appears in a recommended/default model name (not in a "do not do this"
warning), report FAIL.

## Mirror parity — coco-snowsight `SKILL.md`

Each from-skill may be mirrored into CoCo, and those mirrors must carry the same
invariant guidance. The rule must be present and must cite the invariants doc.

| CLI skill | CoCo mirror |
|---|---|
| `ts-convert-from-tableau` | — (no CoCo mirror — Tableau parsing needs a local shell) |
| `ts-convert-from-snowflake-sv` | `agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md` |
| `ts-convert-from-databricks-mv` | — (no CoCo mirror — Databricks CLI not available in Snowsight) |

For each mirror that exists, confirm:
- **N1** — no `TEST_*` prefix in the recommended/default model name.
- **I1–I6** — the mirror states each rule, or carries a callout citing
  `ts-model-conversion-invariants.md` (coco path: `../../shared/schemas/...`).
  I3 stays advisory here too (`[WARN]`).
- **I7** — a `MANDATORY` formula-reference gate precedes the untranslatable classification.

Report a mirror that is missing any invariant its CLI primary enforces as `[FAIL]`, citing the
mirror's `file:line` and the missing invariant ID. A mirror that is simply terser (rule present
but condensed) is a PASS.

## Formula-parity check

For functions/expressions that exist in more than one mapping file
(`agents/shared/mappings/*/`), confirm the SAME source concept maps to the SAME
ThoughtSpot syntax. Specifically:

- `COUNT(DISTINCT ...)` / `COUNTD(...)` → must map to `unique count(...)` in all three
  mapping files (not `COUNT_DISTINCT`).
- `SUM(x) / COUNT(DISTINCT y)` → must produce `sum(...) / unique count(...)` in all
  mapping files that cover this pattern.

Report divergences as `[WARN]` (not `[FAIL]`) with both mappings shown. Do NOT flag
cumulative/moving differences between Tableau and SV/MV — that is EXC1 (deliberate).

## PT1 — Pass-through policy check

**PT1:** aggregate pass-throughs (`sql_*_aggregate_op`) carry a "⚑ flag for review" marker; scalar pass-throughs do not require it. Flag any `sql_*_aggregate_op` usage in the mapping files or skill TML examples that lacks a "⚑ flag for review" (or equivalent note) as `[WARN]`.

## EXC1 — Do NOT flag

The following asymmetries are intentional. Never report them as failures or warnings:
- Tableau table-calcs (`RUNNING_*`, `WINDOW_*`, `INDEX`, `LOOKUP`, `FIRST`, `LAST`,
  `SIZE`, `PREVIOUS_VALUE`) staying at answer-level while SV/MV window functions
  become model formulas (`cumulative_sum`, `moving_average`, etc.).

## Output format

For each skill, one line per invariant:

```
[PASS] I1  agents/cli/ts-convert-from-snowflake-sv/SKILL.md
[FAIL] I2  agents/cli/ts-convert-from-tableau/SKILL.md:698 — aggregation: found in formulas[] block
[WARN] I5  agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md:54 vs agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md:37 — divergent mapping
```

End with a summary count:

```
Failures: N   Warnings: N
```

On any FAIL: give the exact file:line and a one-line description of what to fix. On all
PASSes: just the PASS lines. Warnings require no action but note the divergence.
