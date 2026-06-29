# Codification Sweep — Agentic → Deterministic Code

**Date:** 2026-06-29
**Scope:** Angle #11b — classify every skill step as judgment-required vs mechanical;
identify mechanical steps that should become deterministic Python (ts-cli commands or
shared modules).
**Method:** Four parallel agents, one per skill group. Each read the full SKILL.md and
cross-referenced existing ts-cli commands.

---

## Verdict

The repo has one fully-codified conversion pipeline (Tableau formula translation +
model builder, ts-cli v0.17.0) and four skill families where the LLM re-derives
mechanical logic from prompt text on every invocation. The three highest-value
targets — ts-audit engine, Snowflake SV pipeline, Databricks MV pipeline — would
each eliminate thousands of prompt tokens per run and produce deterministic,
unit-testable results.

---

## Severity bands

### RED — Entire skill is mechanical; LLM adds zero analytical value

| Skill | Finding | Recommended command | Complexity |
|---|---|---|---|
| **ts-audit** | All 42 checks (A1–A5, D1–D12, H1–H10, P1–P11, S1–S5) are threshold comparisons against TML fields. The LLM re-implements the full analysis engine every run. | `ts audit run --angles A,D,H,P,S` | L |

### ORANGE — Large mechanical pipelines with no codification

| Skill | Finding | Recommended commands | Complexity |
|---|---|---|---|
| **ts-convert-from-snowflake-sv** | Steps 4 (DDL parse), 9 (formula translate), 8 (model build) are ~550 lines of prompt + ~2000 lines of reference files loaded every run. Zero codified commands. | `ts snowflake parse-sv`, `ts snowflake translate-formulas`, `ts snowflake build-model` | L + L + M |
| **ts-convert-from-databricks-mv** | Steps 5 (YAML parse + classify), 6 (formula translate), 9 (model build) — same pattern as Snowflake, zero codified commands. | `ts databricks parse-mv`, `ts databricks translate-formulas`, `ts databricks build-model` | L + L + M |

### YELLOW — Significant mechanical blocks in otherwise-agentic skills

| Skill | Step(s) | What's mechanical | Recommended | Complexity | Token savings |
|---|---|---|---|---|---|
| **ts-convert-from-tableau** | 5b (sets) | Set/cohort detection + TML generation (~400 lines). Every set type fully specified. | Extend `model_builder.py`: `extract_sets()` + `build_cohort_tml()` | L | HIGH |
| **ts-convert-from-tableau** | 5a | Table TML generation — template fill + type mapping | `ts tableau build-tables` or extend `build-model` | M | HIGH |
| **ts-convert-from-tableau** | 9a–9c, 10c | Dashboard zone parsing + liveboard TML assembly | `ts tableau build-liveboard` | L | HIGH |
| **ts-convert-from-tableau** | 3b,3e,3f,3g | Blend graph, table-calc addressing, datasource type, orphan calcs — not in `parse_twb()` | Extend `parse_twb()` return value | M | MED |
| **ts-object-answer-promote** | 8–10 | Duplicate detection, ref mapping, column_type inference, TML merge — entirely mechanical | `ts model promote-formula` | M | HIGH |
| **ts-dependency-manager** | 9b–9c | TML column stripping + repoint (~250 lines) | `ts tml strip-columns`, `ts tml repoint` | M | HIGH |
| **ts-object-model-coach** | 4.5 | Cross-model column collision scan — parallel export + set comparison | `ts model scan-collisions` | L | HIGH |
| **ts-object-model-coach** | 8b | AI context validation (closed-key, enum, ref resolution, char limit) | Extend `ts tml lint --ai-context` | S | MED |

### GREEN — Already codified or judgment-dominated (no action needed)

| Skill | Notes |
|---|---|
| **ts-convert-from-tableau** (formula pipeline) | `tableau_translate.py` (2543 lines) + `model_builder.py` (1025 lines) — the reference pattern |
| **ts-profile-\*** | All interaction — nothing to codify |
| **ts-object-model-coach** (Steps 4, 6.1–6.5) | Coaching, synonym generation, question generation — genuine LLM value |
| **ts-convert-\*** (user interaction steps) | Mode selection, scope choice, confirmation — judgment |

---

## Shared infrastructure opportunities

| Pattern | Used by | What it does | Suggested |
|---|---|---|---|
| Parallel cached TML export | ts-audit, ts-object-model-coach | Batch export with local cache, parallel HTTP | `ts tml export-corpus --cache-dir` |
| Type mapping lookup | all converters | Platform type → TS type (Snowflake, Databricks, Tableau) | Shared `type_mapping.py` module |
| TML backup + manifest | ts-dependency-manager, model-coach rollback | Export batch to directory with manifest JSON | `ts tml backup --guids` |
| Model builder adapter | Snowflake, Databricks (new), Tableau (exists) | Generic `build_model_tml()` with per-platform adapter | Refactor `model_builder.py` to accept adapter input |

---

## Priority order for implementation

Ranked by (token savings per invocation) × (invocation frequency) × (codification tractability):

| # | Target | Skill | Why first |
|---|---|---|---|
| 1 | `ts audit run` | ts-audit | Entire engine is mechanical; highest token cost; most frequently run |
| 2 | Snowflake SV pipeline (parse + translate + build) | ts-convert-from-snowflake-sv | Largest single-skill gap; Tableau precedent proves the pattern |
| 3 | Databricks MV pipeline (parse + translate + build) | ts-convert-from-databricks-mv | Same pattern as #2; zero codification today |
| 4 | `ts model promote-formula` | ts-object-answer-promote | Self-contained; Steps 8–10 are one pure function |
| 5 | Tableau set/cohort generation | ts-convert-from-tableau | ~400 lines of mechanical logic; extends existing `model_builder.py` |
| 6 | `ts tml strip-columns` + `ts tml repoint` | ts-dependency-manager | Reusable TML manipulation primitives |
| 7 | Tableau `build-liveboard` | ts-convert-from-tableau | Dashboard→liveboard is the last major agentic block |
| 8 | `ts tml export-corpus` | ts-audit, ts-object-model-coach | Shared pattern; enables #1 |

---

## Relationship to existing backlog

| This finding | Existing BL item | Action |
|---|---|---|
| Snowflake SV formula translator | BL-063 (extract CLI-based formula translation for SF/DBX) | BL-063 already covers this; update scope to include parser + model builder |
| Databricks MV formula translator | BL-063 | Same — BL-063 covers both platforms |
| ts-audit engine | — | **New BL item needed** |
| Tableau set/cohort codification | — | **New BL item needed** (or fold into existing build-model scope) |
| Formula promotion | — | **New BL item needed** |
| TML strip/repoint | BL-034 (tools quality polish) | Could fold into BL-034 |

---

## Actions taken

- Angle #11 in `.claude/rules/repo-audit.md` expanded with "agentic → deterministic" sub-dimension
- This report filed as `docs/audit/2026-06-29-codification-sweep.md`

## Next steps

Route each finding per the two-bucket rule:
1. File new BL items for ts-audit engine, Tableau set codification, formula promotion
2. Update BL-063 scope to include parse + build commands (not just translate)
3. Implementation order: #1 (ts-audit) is highest value and self-contained
