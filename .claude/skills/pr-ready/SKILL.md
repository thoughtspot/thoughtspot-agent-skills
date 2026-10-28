---
name: pr-ready
description: Run before opening a PR, and before self-merging one. Runs everything CI checks locally against upstream main (`scripts/pr-ready.sh`), then an adversarial review of the branch's diff by the `pr-reviewer` agent (plus the conversion-consistency auditor when converters change), and writes both into one evidence block for the PR description. Advisory, not a required check.
---

# pr-ready

One local run of the review a PR would otherwise get only after it is opened: the
CI-superset checks first, then a reviewer briefed to refute the diff. The output is
an evidence block naming the head and base SHAs it describes, so a stale block is
visible.

**Who runs it, and when.**

- A contributor runs it before opening a PR, and again on the final head.
- The maintainer runs it **before every self-merge** and reads the output. For
  maintainer PRs it is **advisory**: it is not a required check and not a GitHub
  review, and it does not block a merge (spec §8.2,
  `docs/superpowers/specs/2026-10-28-pr-quality-system-design.md`).

Run the steps in order. Do not skip ahead: the review is only worth reading on a
branch whose checks pass.

## Step 1: run the checks

Commit first. A dirty tree makes the evidence DIRTY, and a DIRTY block cannot carry
a review (the reviewer reads committed history).

```bash
bash scripts/pr-ready.sh --no-review
echo "pr-ready exit: $?"
EVIDENCE="$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md"
```

It takes several minutes. `--no-review` only silences the script's reminder that
the review is this skill's job.

## Step 2: stop if it failed

If `pr-ready.sh` exits non-zero, **stop here** and do not dispatch the reviewer.
Report to the user:

- the evidence path, `$EVIDENCE`;
- exit 2: the run could not start (no upstream remote, a failed fetch, an unreadable
  workflow) — quote the script's stderr;
- exit 1: every FAIL row and the behind count, read from the evidence:

```bash
grep -E '^\| [a-z]+ \| .* \| FAIL \|' "$EVIDENCE"
grep -E '^Behind upstream main:' "$EVIDENCE"
```

Also stop, and ask the user to commit and re-run, if the first line of the evidence
contains `DIRTY` even though the exit was 0.

## Step 3: dispatch the reviewer

Read the diff range from the evidence — never re-derive the base. It is
`<base_sha>...<head_sha>`, the exact commits the checks ran against:

```bash
RANGE="$(python3 tools/validate/evidence.py range)"
git diff --stat "$RANGE"
```

Dispatch the `pr-reviewer` agent (`.claude/agents/pr-reviewer.md`) with:

- the range `$RANGE`, and the base ref named in the evidence's first line;
- the evidence path `$EVIDENCE`;
- the PR number, if a PR already exists, so it can read the description.

Pass the inputs, not your own reading of the change: a reviewer handed a conclusion
tends to confirm it.

## Step 4: converters also get the converter audit

If the diff touches a conversion skill or converter code, also dispatch the existing
`conversion-consistency-auditor` agent and run `check_converter_parity.py`, as
`CLAUDE.md` requires before merging converter changes. Find out with:

```bash
PLATFORMS="$(ls -d agents/cli/ts-convert-*/ | sed -E 's#.*/ts-convert-(from|to)-([a-z]+).*#\2#' | sort -u | paste -sd'|' -)"
git diff --name-only "$RANGE" | grep -E \
  "^agents/cli/ts-convert-|^agents/shared/mappings/|^agents/shared/schemas/ts-model-conversion-invariants\.md$|^tools/ts-cli/ts_cli/(formula_common|model_builder|sv_[a-z_]+)\.py$|^tools/ts-cli/ts_cli/($PLATFORMS)"
```

Platforms are discovered from the skill directories, never listed here, so a new
converter is covered from its first commit. When unsure whether a file is converter
code, run the audit: it is read-only.

If anything matched:

```bash
python3 tools/validate/check_converter_parity.py --root .
```

and dispatch `conversion-consistency-auditor` on the same range. Steps 3 and 4 are
independent; dispatch the agents together.

## Step 5: append the findings to the evidence

Put the reviewer's report — and, when Step 4 ran, the auditor's report and the
parity check's output under their own `###` headings — in one markdown file in a
scratch directory (never the work tree), then:

```bash
python3 tools/validate/evidence.py append-review --file "$REVIEW_FILE"
```

It replaces the Review section's "Not run" placeholder with a provenance line (the
range and base reviewed, marked advisory) and the text, and scrubs home-directory
paths. Re-running replaces the review rather than stacking a second one. It refuses
(exit 1) if HEAD has moved since Step 1 or the block is DIRTY or unfinished: start
again from Step 1 on the final head.

Do not edit the evidence file by hand, and do not soften or drop findings when
copying them in: the block is evidence of what the reviewer said.

## Step 6: tell the user

Report:

- the evidence path, `$EVIDENCE`;
- the findings by rank (blocker / should-fix / nit), with any blocker first;
- that the whole block goes in the **Evidence** section of the PR template
  (`.github/pull_request_template.md`), pasted as it is.

## Posting

**Never post on your own.** Posting the block to a PR is the user's explicit choice,
made by running the script's post option themselves. Mention that it exists only if
they ask. Note for them that the post option re-runs the checks and posts a fresh
block, whose Review section says "Not run": to share the review, paste the block
written here.
