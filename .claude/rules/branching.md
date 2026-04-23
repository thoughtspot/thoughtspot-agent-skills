# Branching Protocol

## Session-start check — do this before any file edits

At the start of every session, run:

```bash
git branch && git status
```

Then apply these rules before touching any file:

| Current branch | Intended work | Action |
|---|---|---|
| `main` | New skill, new feature, or any change needing live-instance testing | `git checkout -b wip/<skill-name>` from main first |
| `main` | Hotfix to an existing, shipped skill | Acceptable to work directly on main |
| `main` | Docs-only change (README, SETUP.md, CLAUDE.md) | Acceptable to work directly on main |
| `wip/*` (correct branch for the work) | Continuing in-progress work | Proceed |
| `wip/*` (wrong branch) | Work belongs on a different branch | Switch branches before making changes |

**Default: if in doubt, create a wip branch.** It costs nothing and keeps main clean.

## Never commit directly to main for

- New skills or skill extensions under active development
- Any change that requires live ThoughtSpot or Snowflake testing before shipping
- Multi-step changes that span more than one session

## Branch naming

```
wip/<skill-name>       e.g. wip/model-builder, wip/databricks
wip/<feature-slug>     e.g. wip/sv-split-merge, wip/snowflake-osi
```

## Merging to main

Merge criteria (all must be true):
1. All `references/open-items.md` items in changed skills are **VERIFIED**
2. All validators pass: `python3 tools/validate/check_*.py --root .`
3. Changes have been tested against a live instance where required

Merge steps:
```bash
git checkout main
git merge wip/<branch> --ff-only   # fast-forward keeps history clean
git push origin main
git branch -d wip/<branch>
git push origin --delete wip/<branch>
```

## Active wip branches (update this list when branches are created or merged)

| Branch | Contents | Status |
|---|---|---|
| `wip/model-builder` | `ts-object-model-builder` — TS-native split/merge modes | In progress |
| `wip/databricks` | Databricks profile + conversion skills | In progress |
