# Versioning

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

---

## Repo changelog (CHANGELOG.md)

`CHANGELOG.md` at the repo root tracks **repo-level** changes — things that affect
users of the whole collection, not just one skill.

### What belongs in CHANGELOG.md

| Event | Example entry |
|---|---|
| New skill ships to main | `feat: add ts-dependency-manager skill` |
| ts-cli version bump | `chore: bump ts-cli to v0.4.0` |
| New shared schema/mapping | `docs: add thoughtspot-view-tml shared reference` |
| Significant infrastructure change | `feat: add interactive changelog prompt to pre-commit hook` |

### What does NOT belong in CHANGELOG.md

- Individual skill fixes or minor updates — those go in the skill's own `## Changelog`
- Refactoring with no user-visible change
- Internal tooling that doesn't affect skill consumers

### Format

```markdown
## YYYY-MM-DD
- feat: add ts-dependency-manager skill
- chore: bump ts-cli to v0.4.0
```

Entries are dated, not versioned — this repo ships continuously, not in releases.
Newest date at the top. Multiple entries per date are fine.

### Automation

The pre-commit hook runs `suggest_repo_changelog.py` on every commit. It detects
new SKILL.md files, ts-cli version bumps, and new shared files, then prompts
accept/edit/skip. If you've already updated CHANGELOG.md today, it exits silently.
