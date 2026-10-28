# Contributing

This repository is public: every commit, PR description and comment is world-readable.
Before anything else, read the confidentiality rule in
[`.claude/rules/security.md`](../.claude/rules/security.md) (section "Customer data and
confidentiality"). No customer names, tenant links, employee names or customer data,
anywhere.

## The routine for every pull request

1. **Open an issue first** if the change adds a skill, adds a third-party runtime
   dependency, or needs an exception to a repo rule. Agree the approach before building.
2. **Work on a branch,** never on `main` (see
   [`.claude/rules/branching.md`](../.claude/rules/branching.md)). Install the git hooks
   once per clone with `bash scripts/install-hooks.sh`.
3. **Commit, bring the branch up to date with `main`, and run `pr-ready`** on your own
   branch (below). Fix whatever it reports and run it again until it says READY.
4. **Open the PR** and fill in the template
   ([`.github/pull_request_template.md`](pull_request_template.md)). Paste the evidence
   block into the **Evidence** section. If the PR replaces an earlier one, fill in
   **Supersedes #N** with every earlier review point mapped to the diff.

Merge criteria (open items verified, validators passing, a smoke test per changed skill,
live testing where needed) are in
[`.claude/rules/branching.md`](../.claude/rules/branching.md), "Merging wip to main".

## What `pr-ready` is

`scripts/pr-ready.sh` runs, on your machine, everything CI checks on a pull request: the
validators, the PR-only gates, the credential-free smoke suites and the test suites. It
compares your branch with the current upstream `main` (it finds the upstream by URL, so a
fork clone works; it adds a remote named `upstream` if it has to).

It reports **READY** only when every check passes and the branch is not behind `main`. A
check that skipped, or a test skipped because a module CI installs is missing, counts as
a failure. It writes an **evidence block** recording the base and head commits, every
result, and what it could not reproduce locally, to:

```text
$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md
```

Run it on a clean tree: uncommitted changes mark the block DIRTY.

## One-time setup: an environment with CI's packages

`pr-ready` uses the newest Python 3.10+ on your `PATH` that has pytest, and that
interpreter needs exactly what CI installs. The lines are quoted, and kept in step with
CI, under "Before your first run" in
[`.claude/skills/pr-ready/SKILL.md`](../.claude/skills/pr-ready/SKILL.md).

The simplest way is a dedicated virtual environment, which also works when your Python is
managed by uv or Homebrew and refuses `pip install` ("externally-managed-environment").
From the repo root:

```bash
uv venv ~/.venvs/tas-ci --python 3.12
uv pip install --python ~/.venvs/tas-ci/bin/python pytest pyyaml radon pip-audit jsonschema==4.25.1
uv pip install --python ~/.venvs/tas-ci/bin/python -e "tools/ts-cli[snowflake,qlik,xlsx]"
```

Without uv, `python3.12 -m venv ~/.venvs/tas-ci` and then
`~/.venvs/tas-ci/bin/pip install ...` with the same packages does the same.

Then, optionally, an alias in `~/.zshrc` (or `~/.bashrc`):

```bash
alias pr-ready='PATH=~/.venvs/tas-ci/bin:$PATH bash scripts/pr-ready.sh'
```

Open a new terminal, or run `source ~/.zshrc`, for the alias to take effect.

## Running it

### In a terminal: the checks

From your branch's checkout:

```bash
pr-ready                                                    # with the alias
PATH=~/.venvs/tas-ci/bin:$PATH bash scripts/pr-ready.sh     # without it
```

It takes a few minutes and ends with `pr-ready: READY` or `pr-ready: NOT READY` (the
failing rows are printed above it), and the path of the evidence file.

`--post N` comments the block on PR N for you, but only when the run is READY, the tree
is clean, PR N's head is your HEAD, and the block passes the secrets and
customer-reference scans. It re-runs the checks, and the block it posts has no review in
it.

### In Claude Code: the checks plus a review

Run the `pr-ready` skill (type `/pr-ready`, or ask Claude to run pr-ready). It:

1. asks you to confirm the branch is your own;
2. runs `scripts/pr-ready.sh`, and stops if the result is not READY;
3. runs the `pr-reviewer` agent on your diff. The agent tries to refute the change:
   output that is wrong but still lints and imports cleanly, a fix aimed at one instance
   instead of the class, PR text that claims more than the diff does, reimplementing
   something that exists, dropped earlier review points, destructive paths without a
   backup, security basics, and edits to the gates that judge the PR. For converter
   changes it also runs the conversion-consistency auditor;
4. adds the review to the evidence block and scans the result for secrets and customer
   references.

Paste that block into the PR. Any `pr-ready.sh` run afterwards (including `--post`)
replaces the file, review included, so paste it first.

The review is advisory: it is not a required check. The maintainer runs the same skill
before merging their own PRs.

## Reviewing someone else's pull request

**Never run `pr-ready`, the skill, or the PR's tests on someone else's branch.** They
execute that branch's code with your credentials. The skill and the reviewer agent refuse
to run unless you confirm the branch is your own.

For another person's PR, maintainers use `main`'s copy of `scripts/check-pr.sh`, which
scans the PR for customer data without executing any of its code, and then review it by
reading. The exact safe invocation is in the header of `scripts/check-pr.sh`; it needs the
maintainer's private name list. An automated reviewer for other people's PRs is a separate
design that is not built yet (BL-416 in [`docs/backlog.md`](../docs/backlog.md)).

## Why it works this way

The design, and the analysis of past PRs it came from, is in
[`docs/superpowers/specs/2026-10-28-pr-quality-system-design.md`](../docs/superpowers/specs/2026-10-28-pr-quality-system-design.md).
