# Agentic → Deterministic Codification Review — 2026-07-03

Deep-dive on repo-audit angle #11: which skills would benefit from moving LLM-executed
steps into deterministic Python (ts-cli commands), following the pattern proven by
`ts tableau build-model` / `translate-formulas` (ts-cli v0.17.0) and the `ts audit`
command family. Survey executed by a dedicated agent across all `agents/cli/` skills +
`agents/claude/ts-profile-snowflake`; load-bearing claims spot-verified against source.

**Why this matters (quantified precedent):** ts-convert-from-tableau v1.18.0's changelog
records the codification of formula translation as "root cause of 1,389 tool calls in
the Ads migration" — the single largest token/latency win shipped in this repo.

## Headline verdicts

- **Fully clean already:** `ts-audit` (all analysis in `checks_*.py`), `ts-object-model-erd`
  (gold standard — shared parser/renderer modules + unit tests), `ts-object-model-spotql-query`
  (NL→SpotQL correctly judgment; SQL/data fetch deterministic).
- **Furthest behind the precedent:** the two Snowflake and two Databricks conversion skills —
  parse, translate, and emit are all LLM-executed against 500–1,000-line mapping docs.
  These are the exact analogue of what `ts_cli/tableau/` replaced.
- **Clearest single-skill violator:** `ts-object-answer-promote` Steps 8–10 re-derive
  `ts tml lint`'s checks in prose instead of calling it, plus fully-specified
  ref-rewriting/merge logic that belongs in a `ts tml merge-formulas` command.
- **Safety-critical gap:** `ts-dependency-manager`'s headline promises (backup, mutation,
  rollback) are ~900 lines of inline pseudocode with documented known gaps; its walk +
  impact-report steps are already deterministic (`ts metadata report`), so the skill is
  half-migrated.

## Confirmed bugs found during the survey (fixed in the 2026-07-03 audit PRs)

1. `ts-dependency-manager` Step 4 column-scope filter matched on `risk.reason` strings that
   never contain column names (`classifier.py` reasons are fixed literals) — filter could
   never work. Fixed: classifier now emits matched-column data; SKILL.md filters on it.
2. Two skills documented a nonexistent `ts tml import --file` flag — capability added
   (v0.27.0) instead of doc rollback, deleting the 10+ hand-rolled stdin shims over time.
3. `ts-profile-tableau`'s slug-derivation rule had already drifted from its 3 siblings
   (missing "collapse multiples, strip ends") — the drift the profiles substrate item
   (BL-084) exists to kill.

## Ranked candidates (benefit ÷ effort)

| # | Skill | What moves to Python | Proposed command | Effort | Routed to |
|---|---|---|---|---|---|
| 1 | ts-convert-from-tableau | Phase-1 base-model TML is hand-assembled although `model_builder.py:build_model_tml()` + `split_for_phased_import()` already implement it — wire the existing generate mode | `ts tableau build-model` (generate mode) | S–M | BL-085 |
| 2 | ts-object-answer-promote | Ref classification/rewrite, type/agg inference, TML merge, 12-check self-validation | `ts tml merge-formulas` | M | BL-066 (extended) |
| 3 | both Snowflake converters | Mode-C diff helpers (`_normalise_expr`/`_exprs_differ`) copy-pasted as literal Python in both SKILL.mds | `ts snowflake diff` | S | BL-063 (extended) |
| 4 | ts-convert-to-snowflake-sv | 17-item manual DDL validation checklist (from-direction already gates on `ts tml lint`) | `ts snowflake lint-ddl` | S | BL-063 (extended) |
| 5–7 | Snowflake converters | DDL parse → Model TML build → SV DDL emit (the full `ts_cli/tableau/`-shaped subpackage) | `ts snowflake parse-ddl / build-model / build-sv` | L | BL-063 (extended) |
| 8–9 | Databricks converters | Same shape, zero codification today (`ts_cli/databricks/` doesn't exist); both SKILL.mds embed inline Python contradicting their own CLI-first rules | `ts databricks build-model / build-mv` | L | BL-063 (extended) |
| 10 | all four SF/DBX converters | Formula translation walked from 566–1,000-line mapping docs per formula — direct peer of `ts tableau translate-formulas` | `ts snowflake/databricks translate-formulas --direction` | L | BL-063 (core) |
| 11–13 | ts-dependency-manager | Backup manifest, TML mutation engine (remove/repoint across 5 object types), import/verify/drift, rollback — safety-critical inline pseudocode | `ts dependency backup / apply-change / rollback` | L | BL-083 |
| 14 | ts-recipe-formula-* | UDF SQL exists only as markdown fences the LLM transcribes each run (a `-1` vs `-2` DATEDIFF slip is silent); connect/execute boilerplate cloned between both recipes and already drifted from `load.py` | `references/*.sql` + `ts snowflake exec -f` | M | BL-079 |
| 15 | ts-convert-from-tableau | TWB XML parse (blend graph, table-calc addressing, orphan calcs) feeds the deterministic pipeline agentically | `ts tableau parse --json` | M | BL-085 |
| 16–17 | ts-object-model-coach | Prose-mining arithmetic (regex NP extraction, Jaccard-stem scoring), corpus scan, synonym-conflict validation, TML patch/merge — judgment layer stays agentic, the arithmetic beneath it should not | `ts model mine-language / validate-synonyms / patch-model` | M–L | BL-086 |
| 18 | all four ts-profile-* | Slug/env-var derivation, keychain templating, profile-JSON CRUD duplicated 4× with one demonstrated drift bug | `ts profiles add/update/remove` | M | BL-084 |
| 19 | spotql-query + answer-promote | Column classification duplicated with different keyword lists (live drift) | shared `ts spotql classify-columns` | S | BL-087 |
| 20 | ts-convert-from-tableau | Dashboard 12-col grid math (already live-verified, open-items #6) | `ts tableau layout` | S | BL-068 (extended) |

Guardrail candidate (validator, not command): widen the inline-code detection so
Template-driven TML/DDL emission via the Write tool is caught, not just `python3 <<`
heredocs — the drift class that produced most of the gaps above.

## Suggested sequencing

1. **Quick wins** (S, high leverage): wire Tableau build-model generate mode (BL-085),
   extract `ts snowflake diff` + `lint-ddl` (BL-063), spotql classify-columns dedup (BL-087).
2. **Highest-value single command:** `ts tml merge-formulas` (BL-066).
3. **The two subpackages:** `ts_cli/snowflake/` then `ts_cli/databricks/` (BL-063) — each
   comparable to the original `ts_cli/tableau/` investment, each removes an entire class
   of per-run transcription risk and the bulk of conversion token spend.
4. **Safety-critical:** dependency-manager backup/mutate/rollback (BL-083) — the skill's
   headline guarantees currently rest on prose transcription.
5. **Substrate:** profiles CRUD (BL-084), recipe SQL files + `ts snowflake exec` (BL-079),
   coach mining/patch commands (BL-086).
