# GitHub Actions CI — design notes

This branch (`wip/github-actions-ci`) exists to add server-side CI for this repo.
It's a placeholder — pick it up when ready to build out the workflow.

## Goal

Re-run the full pre-commit validator suite (currently only enforced via the local
[scripts/pre-commit.sh](../scripts/pre-commit.sh) hook, which a contributor must opt into
by symlinking `.git/hooks/pre-commit`) on every pull request — so checks can't be
bypassed by `git commit --no-verify` or by contributors who never installed the hook.

## Open design questions (from the discussion that produced this branch)

### 1. Should the CI run match local pre-commit exactly, or be a stricter superset?

The local hook detects "staged files" via `git diff --cached`. In CI, "staged" doesn't
quite mean the same thing — there's no staging area, just the PR diff vs the base
branch.

Options:

- **(a) Match local exactly.** Add a small adapter at the start of `scripts/pre-commit.sh`
  that, when `CI=true`, simulates staging from the PR diff (`git diff --name-only ${{ github.base_ref }}...HEAD`). One script, identical behaviour locally and on CI.
  Risk: the adapter is one more thing to keep in sync.
- **(b) Stricter superset.** CI runs every validator unconditionally against the entire
  repo, not just changed files. Catches issues that the local hook would skip because
  no relevant files were staged.
  Risk: slower CI runs; potentially flags pre-existing issues that aren't part of the PR.
- **(c) Two scripts.** Keep `scripts/pre-commit.sh` as-is for local; add a new
  `scripts/ci-checks.sh` that calls each validator with `--root .` and no staged-file
  filtering. Clean separation, but two scripts to maintain.

**Recommendation (deferred):** Option (a). The adapter is small, and divergence between
local and CI behaviour is a real source of frustration. But this is a judgement call —
revisit when implementing.

### 2. Branch protection scope

Once the workflow exists, [GitHub branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
needs to require it as a passing status check. Otherwise the workflow runs but isn't
enforced — PRs can still merge with red checks.

Options:

- **(a) Require on `main` only.** PRs targeting `main` must pass; PRs targeting
  `wip/*` can merge freely. Matches the existing "no direct push to main" rule.
- **(b) Require on `main` AND `wip/*`.** Stricter. Catches issues earlier in long-lived
  wip branches (e.g. wip/databricks, wip/model-builder). Risk: noisy on early-stage
  experiments.

**Recommendation (deferred):** Option (a). Match the existing convention — wip branches
are explicitly "in-progress, not for merge", and their `references/open-items.md`
already tracks unresolved items.

## Draft workflow (not yet active)

Once the design questions are answered, drop this into
`.github/workflows/pre-commit.yml`:

```yaml
name: Pre-commit checks
on:
  pull_request:
    branches: [main]   # or [main, "wip/**"] per design Q2

jobs:
  validators:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # need full history for `git diff base...HEAD`

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pyyaml pytest
          pip install -e tools/ts-cli

      - name: Run pre-commit checks
        env:
          CI: "true"
        run: bash scripts/pre-commit.sh
```

Notes:
- `fetch-depth: 0` is needed if the script computes diffs against the base ref.
- `pip install -e tools/ts-cli` is required because `check_version_sync.py` and the unit
  tests under `tools/ts-cli/tests/` import the package.
- The `CI=true` env var is set automatically by GitHub Actions but explicit is better —
  the adapter logic in pre-commit.sh (option 1a above) keys off this.

## Branch protection setup (manual, after workflow lands)

Once `pre-commit.yml` is on `main`, configure branch protection in the repo settings:

1. Settings → Branches → Branch protection rules → "Add rule"
2. Branch name pattern: `main`
3. Tick: "Require status checks to pass before merging"
4. Tick: "Require branches to be up to date before merging"
5. Status checks → search for and add: `validators`
6. Tick: "Do not allow bypassing the above settings" (closes the `--no-verify` loophole
   for repo admins on PRs)
7. Save

Optionally also enable "Require linear history" and "Restrict who can push to matching
branches" if not already on.

## What this branch contains right now

- This file (`.github/CI_DESIGN_NOTES.md`)
- Nothing else. The workflow file is intentionally not yet present — that's the
  next step when picking this up.

## When you come back

1. Re-read the open questions above and pick answers
2. If option 1a: add the staged-files-from-PR-diff adapter to `scripts/pre-commit.sh`
3. Create `.github/workflows/pre-commit.yml` from the draft above
4. Push the branch and open a PR against `main`
5. After the PR merges: configure branch protection per the section above
6. Delete this design-notes file (or move its content into the PR description)
