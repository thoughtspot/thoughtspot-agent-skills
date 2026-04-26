# Branching Protocol

## Session-start check — do this before any file edits

At the start of every session, run:

```bash
git branch && git status
```

Then apply these rules before touching any file:

| Current branch | Intended work | Action |
|---|---|---|
| `main` | Any change | Create a branch first — **never commit or push directly to main** |
| `wip/*` (correct branch for the work) | Continuing in-progress work | Proceed |
| `wip/*` (wrong branch) | Work belongs on a different branch | Switch branches before making changes |

**All changes to `main` go through a pull request — no exceptions.**
This includes hotfixes, docs-only edits, and single-line changes. `main` has branch
protection; direct pushes bypass review and bypass the PR-gated pre-commit checks.

## Branch naming

Use `feat/<slug>` for changes ready to PR immediately, `wip/<skill>` for in-progress work:

```
feat/<slug>            e.g. feat/skill-intros, feat/step0-convention
wip/<skill-name>       e.g. wip/model-builder, wip/databricks
```

## Merging wip to main

Criteria (all must be true before opening a PR):
1. All `references/open-items.md` items in changed skills are **VERIFIED**
2. All validators pass: `python3 tools/validate/check_*.py --root .`
3. Changes have been tested against a live instance where required

Steps:
```bash
git push -u origin wip/<branch>
# Open a PR on GitHub — do not merge locally
# After the PR is merged on GitHub:
git branch -d wip/<branch>
git push origin --delete wip/<branch>
```

## Active wip branches (update this list when branches are created or merged)

| Branch | Contents | Status |
|---|---|---|
| `wip/model-builder` | `ts-object-model-builder` — TS-native split/merge modes | In progress |
| `wip/databricks` | Databricks profile + conversion skills | In progress |
| `wip/ts-dependency-manager` | `ts-dependency-manager` — column removal, rename, repoint with impact report and rollback | In progress |
| `wip/github-actions-ci` | GitHub Actions workflow to run pre-commit checks on PRs (placeholder — see `.github/CI_DESIGN_NOTES.md`) | Placeholder |
