# Skill Versioning

Every skill must have a `## Changelog` section at the bottom of its `SKILL.md`.
The pre-commit hook validates this — commits touching a SKILL.md will fail if the
changelog is missing or has no valid entries.

## Format

```markdown
---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-04-22 | Add parameter promotion support |
| 1.0.0 | 2026-01-15 | Initial release |
```

- Versions follow semver: `MAJOR.MINOR.PATCH`
- Dates are ISO 8601: `YYYY-MM-DD`
- Newest entry at the top
- One row per meaningful change — not per commit

## When to bump

| Change type | Version bump | Example |
|---|---|---|
| Breaking change — removed step, changed command interface, incompatible output format | MAJOR | Rename a required `ts` subcommand |
| New capability — new option, new step, new output field | MINOR | Add a new conversion mode |
| Fix or clarification — corrected instructions, typo, updated example | PATCH | Fix wrong flag name in example |

## When NOT to bump

- Reformatting or reordering content with no semantic change
- Updating a cross-reference path that was broken (fix the path, PATCH bump)
- Updating shared reference files (schemas, mappings) — those don't have their own version; bump the skill(s) that reference them if the change affects skill behaviour

## New skills

Start at `1.0.0` when the skill first ships to `main`. Work-in-progress skills on
`wip/*` branches do not need a changelog until they merge.

## Validator

```bash
python3 tools/validate/check_skill_versions.py --root .
```

Runs automatically in the pre-commit hook when any `SKILL.md` is staged.
