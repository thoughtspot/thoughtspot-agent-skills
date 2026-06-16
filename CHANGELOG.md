# Changelog

All notable changes to this repo are documented here.
Skill-level changes are tracked in each skill's own `## Changelog` section.

---

## 2026-06-16
- chore: migrate the last v1 API (`/tspublic/v1/connection/fetchConnection`, removed/404 on newer builds) to v2 `connection/search`; ts-cli v0.9.0 (`_fetch_connection_v2`/`_adapt_v2_databases`) + databricks `ts_client.py`; no v1 endpoints remain in the repo
- feat: ts-convert-from-tableau v1.11.0 — reorder so the source-table question (exist/create/search) comes before any connection selection or search; add connection-scoped vs instance-wide search (`--name` pattern, `metadata_header.dataSourceName` filter)
- feat: add the same connection-scoped vs instance-wide table search to ts-convert-from-snowflake-sv (v1.10.0) and ts-convert-from-databricks-mv (v1.4.0)
- feat: add a how-to-identify-the-connection prompt (name it / filter by partial string / list all) to the connection-selection step of all three CLI from-* conversion skills — ts-convert-from-tableau (v1.12.0), ts-convert-from-snowflake-sv (v1.11.0), ts-convert-from-databricks-mv (v1.5.0)
- feat: ts-convert-from-tableau v1.13.0 — add a migration-scope choice (Models+Liveboards / Tables+Models only / Liveboards-only with an existing-model picker: GUID/name/filter/list-all, models found via `--subtype WORKSHEET` + `worksheetVersion == "V2"`); fix the model `obj_id` reuse bug (a fresh model's requested obj_id is reassigned by ThoughtSpot — read the real one back before referencing it in liveboard viz/cohort bindings); add an efficiency section (batch independent prompts, single-pass parse, one model export for obj_id + param UUIDs + resolved names)

## 2026-06-14
- feat: BL-024 — row-offset table calcs (INDEX/LOOKUP/FIRST/LAST/SIZE) translate via native TS window functions (`moving_sum`, `first_value`, `last_value`, `rank`) instead of SQL pass-through (which fails for DATE/numeric ORDER BY columns); ts-convert-from-tableau v1.10.0; live-verified 2026-06-15
- chore: retire Cursor runtime — delete `agents/cursor/` (14 .mdc rules, SETUP.md, install scripts), remove all Cursor references from validators, pre-commit hook, rules, README, backlog, and auditor; closes BL-017
- docs: add data-blend-to-model shared reference — two-datasource Tableau blend → single ThoughtSpot model with LEFT_OUTER join worked example

## 2026-06-13
- docs(BL-018): map four previously-unmapped SV features to ThoughtSpot — range joins (GAP-08), filter labels (GAP-10), view-backed sources (GAP-04), verified queries → NLS Feedback TML (GAP-05); update `ts-from-snowflake-rules.md` DDL format + mapping sections, `sv-to-ts-gap-analysis.md`, `thoughtspot-model-tml.md` (remove `is_mandatory`, correct `apply_on_tables` semantics), and `backlog.md` (BL-019/BL-020 for Databricks/Tableau parity)
- feat(from-snowflake-sv): v1.9.0 — identifier resolution engine: facts parsing (BL-003b), metric→fact resolution (BL-003c), double aggregation via group_aggregate (BL-003), window metrics referencing metrics (GAP-13), joinless SV handling (GAP-03/BL-004)
- fix(from-snowflake-sv): fact references use `[formula_<id>]` syntax, not display name — live-verified; add `if()` parenthesization fix; add identifier resolution worked example
- docs: add `ts-from-snowflake-identifier-resolution.md` worked example — facts, metric-on-fact, double aggregation, verified end-to-end
- fix(coco): mirror parity — port PT1 pass-through policy and error-010256 rule to CoCo skills; reverse-port name-normalisation rule to CLI; fix count_distinct example (audit C8/F2/F11)
- fix(snowflake-sv): Phase 1 audit — fail-loud SV DDL parsing (C5), LEFT_OUTER join default (F5), authority fix (F4), discovery SQL fix (F8), Mode C comparison fix (F7), INFORMATION_SCHEMA case fix (F12)

## 2026-06-12
- feat(from-tableau): v1.8.0 — static sets → column sets (BL-009 Phase 2a); detect+log Top-N/set-ops/set-actions as deferred; refresh thoughtspot-sets-tml.md with column-set/query-set vocabulary
- fix(mappings): trig unit bug — SIN/COS/TAN now convert radians→degrees (Tableau trig is radians, ThoughtSpot is degrees); UPPER/LOWER fixed to sql_string_op pass-through (no native in TS 26.6.0); REGEXP_MATCH fixed to sql_bool_op (returns boolean, not 1/0)
- feat(convert-from): PT1 cross-skill pass-through policy — scalar pass-throughs reliable; aggregate pass-throughs (sql_*_aggregate_op) must be flagged for review; policy in ts-model-conversion-invariants.md, applied across Tableau/SV/Databricks formula-translation files
- feat(from-tableau): v1.7.0 — Phase-1 Tableau function mappings: DATEPARSE, EXP, trig, STARTSWITH/ENDSWITH, PI/RADIANS/DEGREES composites, PROPER/ASCII/CHAR/REGEXP/FINDNTH pass-through, WINDOW_*/RUNNING_COUNT table-calc notes (BL-009 Phase 1)
- feat(validate): `check_tml.py` now enforces I4 (join id==name exact case) and I5 (no `aggregation: COUNT_DISTINCT` on physical columns); added `tools/validate/tests/test_check_tml.py` (BL-001)
- feat(convert-from): add an inline pre-import validation gate (I1/I2/I4/I5) to ts-convert-from-tableau, -snowflake-sv, and -databricks-mv before model TML import (BL-001)
- fix(mappings): Snowflake `BOOLEAN` maps to `BOOL` for ThoughtSpot — `ts tables create` rejects `BOOLEAN` on Snowflake connections (BL-006)
- chore(mirrors): mirror conversion invariants into the tableau + databricks-mv cursor rules, completing BL-012 parity

## 2026-06-11
- docs: add `ts-model-conversion-invariants.md` shared reference — canonical hard-rule checklist (I1–I7 + EXC1 + N1) for all Model-producing conversion skills; cross-linked from `thoughtspot-model-tml.md`
- feat: add `conversion-consistency-auditor` subagent — semantic auditor for I1–I7 and N1 across the five conversion skills plus their cursor + coco-snowsight mirrors (Mirror parity section); I3 is advisory (WARN); run before merging any conversion-skill PR
- fix(agents): update `consistency-checker` to current layout — scans `agents/cli/`, `agents/claude/`, and `agents/coco-snowsight/` (keeps `agents/claude/`-only skills like `ts-profile-snowflake` in coverage)
- feat(from-snowflake-sv): v1.5.0 — drop TEST_SV_ prefix, I5 explicit note, open-items.md
- feat(from-databricks-mv): v1.1.0 — preserve Spotter setting on in-place update, drop TEST_MV_ prefix
- fix(from-tableau): v1.5.39 — add I1–I6 hard rules to Step 5b, I7 formula-reference gate
- fix(mirrors): mirror the conversion invariants into the snowflake-sv cursor rule (v1.3.1) and coco-snowsight skill (v1.3.1) — I1–I6 + N1 callout and I7 gate, matching the CLI skill
- fix(validators): complete the `agents/claude/`→`agents/cli/` + `agents/coco/`→`agents/coco-snowsight/` rename left incomplete by PR #18. The validators (`check_references`, `check_skill_versions`, `check_skill_naming`, `check_yaml`, `check_patterns`, `check_smoke_tests`, `check_consistency`, `check_open_items`, `suggest_*`) globbed the old paths and were silently checking only 1 of 20 skills; they now scan `agents/cli/`, `agents/claude/`, and `agents/coco-snowsight/`. `check_references` now skips `{template}` placeholder link targets.
- docs(layout): fix stale `agents/claude/` / `agents/coco/` references across `.claude/rules/*`, `CLAUDE.md`, `agents/PARITY.md`, `agents/cursor/*`, `agents/coco-snowsight/CLAUDE.md`, `tools/` docs, and two cursor rule mirrors to the canonical `agents/cli/` + `agents/coco-snowsight/` layout (`agents/claude/` retained for the Claude-only `ts-profile-snowflake` annex)

## 2026-06-10
- feat: `ts-convert-from-tableau` v1.2.0 → v1.5.37 — major dashboard→liveboard migration upgrade, hardened against 6 real workbook migrations on a live ThoughtSpot. Adds Step 4.5 (confirm tables exist before searching; connection required, no placeholders), Step 5.5 (Spotter on every model), Step 7/7.5 (formula-review checkpoint + model confirmation), Step 9d (orphan-worksheet prompt), full liveboard generation (obj_id binding, complete chart blocks with resolved names, note tiles, KPI-per-measure, parameter header chips, Migration Summary tab, curated style themes), Step 11.5 (formula-coverage answers — every formula gets a testable answer), and Step 12 (written `MIGRATION_REPORT.md` with outcomes table, hyperlinks, and a full formula-mapping status table)
- docs: expand Tableau shared reference library — `tableau-formula-translation.md` (rank direction arg; `cumulative_*`/`moving_*` are query-time only and take the shelf attribute as sort arg; `concat()` not `+`; dynamic year-comparison; drop redundant pass-through formulas), `tableau-tml-rules.md` (in-place re-import requires top-level `guid`/`obj_id`), and schema docs (`thoughtspot-answer-tml.md` PERCENTAGE format; `thoughtspot-liveboard-tml.md` TABLE_MODE tiles omit the chart block)

## 2026-06-09
- feat: add `ts-convert-from-tableau` skill — convert Tableau workbooks (.twb/.twbx) into ThoughtSpot table + model TMLs with optional dashboard-to-liveboard migration; available in CLI, Cortex Code CLI, and Cursor
- docs: add Tableau shared reference library — formula translation (`tableau-formula-translation.md`) and TML generation rules (`tableau-tml-rules.md`) in `agents/shared/mappings/tableau/`
- chore: bump ts-cli to v0.8.0 — adds `--include-obj-id`, `--include-obj-id-ref`, `--no-guid` flags to `ts tml export` for export_options support

## 2026-06-01
- feat: add `ts metadata report` command — dependency walk + TML probes + risk classifier + formatters
- feat: rewrite ts-dependency-manager Steps 4/5 to delegate to `ts metadata report` CLI

## 2026-05-22
- feat: add `ts-convert-to-databricks-mv` and `ts-convert-from-databricks-mv` skills — convert between ThoughtSpot Models and Databricks Metric Views (v0.1 single-source and v1.1 multi-source); available in CLI, Cortex Code CLI, and Cursor
- feat: add `ts-profile-databricks` skill — manage Databricks connection profiles with Service Principal (OAuth M2M), PAT, or existing CLI profile auth; available in CLI, Cortex Code CLI, and Cursor
- docs: add Databricks Metric View shared reference library — MV YAML schema (`databricks-metric-view.md`), bidirectional mapping rules, formula translation reference, and property coverage matrix in `agents/shared/mappings/ts-databricks/`

## 2026-05-13
- feat: add `ts-recipe-formula-hms-display-snowflake` (v1.0.0) — deploys four Snowflake scalar UDFs (`format_seconds_to_hms`, `format_seconds_to_dhms`, `format_minutes_to_hm`, `format_minutes_to_dhm`) for formatting integer durations as `HH:MM:SS` / `DD:HH:MM:SS` / `HH:MM` / `DD:HH:MM` strings; shows ThoughtSpot `sql_string_op` formula syntax and TML pattern; available in CLI, Cortex Code CLI, Snowsight Workspaces, and Cursor
- refactor: introduce `ts-recipe-*` naming family for analytical capability skills — rename `ts-setup-snowflake-udfs-business-days` → `ts-recipe-formula-business-days-snowflake` (v2.0.0 MAJOR); update validator, skill-naming doc, smoke tests, README, and all SETUP.md files
- feat: split README "Setup" section into "Connection Profiles" (`ts-profile-*`) and "Recipes" (`ts-recipe-*`) for clearer category separation

## 2026-05-12
- feat: add `ts-setup-snowflake-udfs-business-days` (v1.0.0) — deploys three Snowflake scalar UDFs for weekday-only date arithmetic (`get_business_days_clamped`, `get_business_minutes_clamped`, `get_business_duration_str`) and shows ThoughtSpot `sql_int_op` / `sql_string_op` formula syntax; available in CLI, Cortex Code CLI, Snowsight Workspaces, and Cursor

## 2026-05-11
- chore: bump ts-cli to v0.6.0
- fix: `ts tml import` default changed from `--create-new` to `--no-create-new` — prevents silent duplicate creation when importing TML with an existing GUID; updated help text and docstring with explicit warning about the `--create-new` + existing-GUID pitfall
- fix: `ts tml export --type FEEDBACK` now exits immediately with a clear error explaining that feedback TML must be exported via the feedback object's own GUID (the API returns HTTP 400 for model GUID + type=FEEDBACK); directs user to `ts metadata dependents` to locate feedback GUIDs
- feat: `ts profiles list --snowflake` — lists Snowflake profiles from `~/.claude/snowflake-profiles.json` (name, method, account, warehouse); previously there was no CLI path to list Snowflake profiles
- fix: `ts-object-model-coach` Step 2b — replaced broken `--type FEEDBACK` export with the correct two-step approach: find feedback object GUIDs via `ts metadata dependents`, then export each GUID directly; handles zero-feedback models gracefully (proceeds with empty list)
- chore: bump ts-cli to v0.5.0 — adds `--type` flag to `ts tml export` for FEEDBACK TML export
- fix: migrate all direct urllib API calls in `ts-object-model-coach` to ts CLI (`ts tml export --type FEEDBACK`, `ts metadata dependents --raw`, `ts metadata dependents`); Cursor mirror updated to match (v1.2.0)

## 2026-05-05
- feat: add Mode C (update existing) to `ts-convert-from-snowflake-sv` (v1.4.0) and `ts-convert-to-snowflake-sv` (v1.2.0) — diff-and-confirm workflow for applying a changed SV/Model to an existing counterpart; per-column KEEP/UPDATE/MERGE decisions; `ai_context` and Data Model Instructions never touched; coaching handoff to `/ts-object-model-coach` after import. Mirrored in Cursor `.mdc` (v1.3.0 / v1.2.0) and CoCo runtimes (v1.3.0 / v1.2.0).
- feat: Mode B (split/merge) is now first-class in both conversion skill mode menus — previously a sub-flow triggered by domain detection, now an explicit choice at session start.
- docs: rename "reverse-engineer" → "convert" in all descriptions for `ts-convert-from-snowflake-sv` across Claude, Cursor, CoCo, README, and SETUP.md files.
- test: add `--mode-c` flag to `smoke_ts_from_snowflake.py` (verifies `--no-create-new` updates in-place, not duplicate) and `smoke_ts_to_snowflake.py` (verifies `CREATE OR REPLACE` on an existing SV).

## 2026-04-28
- feat: `ts-convert-from-snowflake-sv` adds Step 9.5 — confirm Spotter (AI search) enablement before import (default Y). Preserves the existing setting on in-place updates rather than silently overwriting. Mirrored in Cursor `.mdc` and CoCo runtimes.
- feat: SV ↔ TS metadata mapping — `with synonyms=(...)` now maps to display name + `properties.synonyms` (top-level `synonyms:` is silently dropped on TS import); per-dimension/metric `comment='...'` → column `description`; per-table `comment='...'` in the SV `tables(...)` block → TS Table TML `table.description`. Affects `ts-convert-from-snowflake-sv` and `ts-convert-to-snowflake-sv` across Claude/Cursor/CoCo runtimes.
- feat: semi-additive direction handling — `non additive by (col desc nulls last)` now translates to `first_value(...)` (previously documented as untranslatable); `asc nulls last` continues to translate to `last_value(...)`.
- fix: `count_distinct(...)` is rejected by the TS formula parser — `unique count` (with a space, not underscore) is the only valid form. Updated all references in `thoughtspot-formula-patterns.md`, `ts-snowflake-formula-translation.md`, and reverse-flow rules.
- fix: `+` does not concatenate strings in TS formulas — must use `concat(...)`. Documented in `thoughtspot-formula-patterns.md`.
- docs: add `ts-from-snowflake-dunder.md` worked example exercising multi-value synonyms, descriptions, table comments, semi-additive (closing/opening), `unique count`, and `concat()`. BIRD example unchanged.
- chore: add skill-naming convention rule + validator (`.claude/rules/skill-naming.md`, `tools/validate/check_skill_naming.py`) — six families documented (`ts-object-*`, `ts-profile-*`, `ts-convert-*`, `ts-dependency-*`, `ts-variable-*`, `ts-setup-*`); pre-commit fails if a skill name doesn't match a family or sit on the (currently empty) allowlist
- feat: rename `ts-coach-model` → `ts-object-model-coach` (skill bumped to v2.0.0) — aligns with the `ts-object-{type}-{verb}` family pattern; slash command, smoke-test filename, and cache directory all change
- chore: add runtime-coverage convention rule + validator (`.claude/rules/runtime-coverage.md`, `tools/validate/check_runtime_coverage.py`) — Cursor mirrors Claude; CoCo divergences documented in `EXPECTED_DIVERGENCES` map with per-entry justification; pre-commit fails on undocumented gaps
- feat: add Cursor mirrors for `ts-dependency-manager` and `ts-object-model-coach` (closes the previously-undetected gap where Claude had skills with no Cursor `.mdc`); both marked "Untested in Cursor" pending validation by a Cursor user

## 2026-04-27
- feat: add `ts-dependency-manager` skill (v1.0.0) — Audit / Remove / Repoint modes for safely changing columns across Models, Views, Answers, Liveboards, and Sets, with alias-aware dep walk, STOP-condition handling, TML backup, post-import verification, drift detection, and rollback
- feat: add `ts metadata dependents <guid>` to ts-cli (v0.4.0) — wraps v2 metadata/search with `include_dependent_objects=true`; default flat output (one row per dep) or `--raw` for the full v2 response
- feat: add `ts-variable-timezone` skill — manage `ts_user_timezone` variable at org and user level (Beta in 26.5, EA in 26.6)

## 2026-04-24
- feat: add skill versioning — every SKILL.md now has a `## Changelog` section with semver tracking
- feat: add interactive changelog prompt to pre-commit hook (`suggest_skill_version.py`)
- chore: move `semantic-layer-compare` skill to `semantic-layer-research` repo

## 2026-04-23
- feat: add cross-platform credential support (Windows/Linux) and Cursor agent runtime
- feat: add multi-domain split and multi-SV merge to conversion skills
- feat: redesign `ts-convert-to-snowflake-sv` to use native DDL creation (DROP YAML output)
- refactor: rename project from `thoughtspot-skills` to `thoughtspot-agent-skills`
- chore: add branching protocol rule (session-start check)

## 2026-04-22
- feat(ts-object-answer-promote): add parameter promotion — promote Answer parameters to Model alongside formulas (Abhijit Das)

## 2026-04-21
- refactor: add `ts-` brand prefix to all skill names
- refactor: rename `ts-object-model-promote` → `ts-object-answer-promote`
- refactor: restructure profile setup skills — profile before platform
