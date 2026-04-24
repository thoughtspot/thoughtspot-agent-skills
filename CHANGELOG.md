# Changelog

All notable changes to this repo are documented here.
Skill-level changes are tracked in each skill's own `## Changelog` section.

---

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
