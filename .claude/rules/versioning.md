# Versioning

Every skill must have a `## Changelog` section at the bottom of its `SKILL.md`. The
`check_skill_versions.py` validator runs in the pre-commit hook and enforces the format.

## When to bump

**Version bumps happen at PR time — not during wip development.** Open a PR to main with
the version bump and changelog entry as part of that PR. A wip branch may accumulate
weeks of work without touching the version; the version reflects what is on main, not
what is in progress.

The mechanics:

| Lifecycle stage | Version field | Changelog |
|---|---|---|
| New skill, on a wip branch | `1.0.0` (no changelog needed yet) | None — the skill hasn't shipped |
| New skill, opening PR to main | `1.0.0`, date = PR creation date | One entry: initial release summary |
| Existing skill on wip, work in progress | Unchanged from main | Unchanged |
| Existing skill, opening PR to main | Bumped per semver below | New entry at top, dated PR creation date |
| Hotfix on main directly (rare — see branching.md) | Bumped on the commit | New entry on the same commit |

**Rationale:** the changelog is for shipped history. Bumping during wip churns the
diff, creates conflicts when two wip branches both bump, and makes the version
meaningless until merge. Bumping at PR time keeps the changelog tied to actual releases.

## Semver rules

| Change type | Version bump | Example |
|---|---|---|
| Breaking change — removed step, changed command interface, incompatible output format | MAJOR | Rename a required `ts` subcommand |
| New capability — new option, new step, new output field | MINOR | Add a new conversion mode |
| Fix or clarification — corrected instructions, typo, updated example | PATCH | Fix wrong flag name in example |

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
- Dates are ISO 8601: `YYYY-MM-DD`, the date of the merge commit (or PR creation if
  merging the same day)
- Newest entry at the top
- One row per shipped change — not per commit, not per wip iteration

## When NOT to bump

- Reformatting or reordering content with no semantic change
- Updating a cross-reference path that was broken (fix the path, PATCH bump on next merge)
- Updating shared reference files (schemas, mappings) — those don't have their own version; bump the skill(s) that reference them if the change affects skill behaviour
- Mid-wip refinements that the user will see as one shipped change

## Validator

```bash
python3 tools/validate/check_skill_versions.py --root .
```

Runs automatically in the pre-commit hook when any `SKILL.md` is staged. New wip
skills without a changelog yet are exempt; the validator only flags skills that have
shipped at least one version and are missing the section.

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
