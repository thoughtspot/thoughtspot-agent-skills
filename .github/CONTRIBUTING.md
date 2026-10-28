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
3. **Meet the criteria for opening a PR,** listed under "Merging wip to main" in
   [`.claude/rules/branching.md`](../.claude/rules/branching.md): open items verified or
   deferred, validators passing, a smoke test for every new or modified Claude skill (or
   the skill on the smoke-test allowlist, with a reason), and live testing where needed.
4. **Commit, bring the branch up to date with `main`, and run `pr-ready`** on your own
   branch (below). Fix whatever it reports and run it again until it says READY.
5. **Open the PR** and fill in the template
   ([`.github/pull_request_template.md`](pull_request_template.md)). Paste the evidence
   block into the **Evidence** section. If the PR replaces an earlier one, fill in
   **Supersedes #N** with every earlier review point mapped to the diff.

**Size.** Keep a PR to one change. A large PR is not refused, but it is slower to review
and more likely to need several rounds. Today the PR-size gate warns only on very many
added files or large binary assets; a warning on changed lines is planned (BL-420 in
[`docs/backlog.md`](../docs/backlog.md)).

## What `pr-ready` is

`scripts/pr-ready.sh` runs, on your machine, the checks CI runs on a pull request: the
validators, the PR-only gates, the credential-free smoke suites and the test suites, on
one Python version. It compares your branch with the current upstream `main` (it finds the
upstream by URL, so a fork clone works; it adds a remote named `upstream` if it has to).

It reports **READY** when nothing FAILs and the branch is not behind upstream `main`. A
required check skipped for a missing tool, and a test skipped for a missing module, count
as FAIL. **WARN** and **NOT RUN** rows do not block READY: they are listed in the block with
their reasons, so read them. Some CI checks cannot be reproduced locally (the other
Python versions in CI's test matrix, and `pip-audit`, which is a warning here and a hard
gate in CI); the block lists them under "Not reproduced locally".

It writes an **evidence block** recording the base and head commits, every result, and
what it could not reproduce, to:

```text
$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md
```

Run it on a clean tree: uncommitted changes mark the block DIRTY.

## One-time setup: an environment with CI's packages

`pr-ready` uses the newest `python3.1x` on your `PATH` that has pytest, and that
interpreter needs exactly what CI installs. The install lines are quoted, and kept in step
with CI by a test, under "Before your first run" in
[`.claude/skills/pr-ready/SKILL.md`](../.claude/skills/pr-ready/SKILL.md). Copy them from
there rather than from anywhere else.

If your Python accepts `pip install`, run those lines with it. If it refuses
("externally-managed-environment": a Python managed by uv or Homebrew), use a dedicated
virtual environment:

1. Create it: `uv venv ~/.venvs/tas-ci --python 3.12` (or
   `python3.12 -m venv ~/.venvs/tas-ci` without uv).
2. From the repo root, run each line quoted in the skill with
   `uv pip install --python ~/.venvs/tas-ci/bin/python` (or `~/.venvs/tas-ci/bin/pip install`)
   in place of `pip install`.
3. Check which interpreter `pr-ready` will pick. Because it takes the newest Python with
   pytest, a newer Python elsewhere on your `PATH` wins over the environment even when the
   environment comes first (an override is planned: BL-436). This should print the
   environment's `python3.12`:

   ```bash
   PATH=~/.venvs/tas-ci/bin:$PATH bash -c 'source scripts/lib/python-bin.sh; command -v "$PYTHON_BIN"'
   ```

   If it prints another interpreter, build the environment from that newer Python instead.

Optionally, add an alias to `~/.zshrc` (or `~/.bashrc`) that works from any directory in
the checkout:

```bash
alias pr-ready='PATH=~/.venvs/tas-ci/bin:$PATH bash "$(git rev-parse --show-toplevel)/scripts/pr-ready.sh"'
```

Open a new terminal, or run `source ~/.zshrc`, for it to take effect. The alias runs the
`scripts/pr-ready.sh` of whatever checkout you are in, so use it only in your own.

## Running it

### In a terminal: the checks

In your own branch's checkout:

```bash
pr-ready                                                    # with the alias
PATH=~/.venvs/tas-ci/bin:$PATH bash scripts/pr-ready.sh     # without it, from the checkout's root
```

It takes a few minutes. It ends with `pr-ready: READY` or `pr-ready: NOT READY` (the
failing rows are printed above), the path of the evidence file, and a reminder that the
Claude Code skill adds the review (`--no-review` drops the reminder). A run that cannot
start (no upstream remote reachable, a failed fetch) exits with status 2 and neither
verdict.

`--post N` comments the block on PR N for you, but only when the run is READY, the tree
is clean, PR N's head is your HEAD, and the block passes the secrets and
customer-reference scans. It re-runs the checks, and the block it posts has no review in
it.

### In Claude Code: the checks plus a review

Run the `pr-ready` skill (type `/pr-ready`, or ask Claude to run pr-ready). It:

1. asks you to confirm the branch is your own;
2. runs `scripts/pr-ready.sh`, and stops unless the result is READY and the tree was clean;
3. asks whether the PR supersedes an earlier one, and for your mapping of that PR's
   review points if it does;
4. runs the `pr-reviewer` agent on your diff. The agent tries to refute the change:
   output that is wrong but still lints and imports cleanly, a fix aimed at one instance
   instead of the class, PR text that claims more than the diff does, reimplementing
   something that exists, dropped earlier review points, destructive paths without a
   backup, security basics, and edits to the gates that judge the PR. For converter
   changes it also runs the conversion-consistency auditor;
5. adds the review to the evidence block and scans the result for secrets and customer
   references.

Paste that block into the PR. Any later `pr-ready.sh` run (including `--post`) replaces
the file, review included, so paste it first.

The review is advisory: it is not a required check. The maintainer runs the same skill
before merging their own PRs.

## Reviewing someone else's pull request

**Never run `pr-ready`, the skill, the alias, or the PR's tests in a checkout of someone
else's branch.** They execute that branch's code with your credentials. The skill's
own-branch question is not a safeguard there: in such a checkout the skill, the reviewer
agent's instructions and `scripts/pr-ready.sh` are that branch's copies, so they can be
changed not to ask.

For another person's PR, maintainers use `main`'s copy of `scripts/check-pr.sh`, which
scans the PR for customer data without executing any of its code, and then review it by
reading. Run it from a clone whose `origin` is `thoughtspot/thoughtspot-agent-skills`
(in a fork clone, `origin/main` is the fork's copy), with the invocation in the header of
`scripts/check-pr.sh`; it needs the maintainer's private name list unless run with
`--links-only`. An automated reviewer for other people's PRs is a separate design that is
not built yet (BL-416 in [`docs/backlog.md`](../docs/backlog.md)).

## Why it works this way

The design, and the analysis of past PRs it came from, is in
[`docs/superpowers/specs/2026-10-28-pr-quality-system-design.md`](../docs/superpowers/specs/2026-10-28-pr-quality-system-design.md).
