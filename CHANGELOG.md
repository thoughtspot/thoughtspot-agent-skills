# Changelog

All notable changes to this repo are documented here.
Skill-level changes are tracked in each skill's own `## Changelog` section.

---

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
