---
name: pr-ready
description: Run on your OWN branch before opening a PR, and before self-merging one. Runs everything CI checks locally against upstream main (`scripts/pr-ready.sh`), then an adversarial review of the branch's diff by the `pr-reviewer` agent (plus the conversion-consistency auditor when converters change), and writes both into one evidence block for the PR description. Advisory, not a required check. For someone else's PR it does not run the branch: it gives the read-only procedure instead.
---

# pr-ready

One local run of the review a PR would otherwise get only after it is opened: the
CI-superset checks first, then a reviewer briefed to refute the diff. The output is
an evidence block naming the head and base SHAs it describes, so a stale block is
visible.

**Who runs it, and when.**

- A contributor runs it on their branch before opening a PR, and again on the final
  head.
- The maintainer runs it on their own branch **before every self-merge** and reads
  the output. For maintainer PRs it is **advisory**: it is not a required check and
  not a GitHub review, and it does not block a merge (spec §8.2,
  `docs/superpowers/specs/2026-10-28-pr-quality-system-design.md`).

## Whose branch is this? Decide first

Steps 1–6 **execute the branch's own code** — the runner, every validator, the
smokes and the test suite — with your full environment: credential variables, the
Keychain, the `ts` token cache. And from a PR checkout the PR also controls this
skill, the reviewer brief, `scripts/pr-ready.sh` and the `.claude/settings.json`
hooks, so its copy of these instructions is not evidence of anything.

- **You wrote the branch** (or have read every line of it, its `.claude/` and
  `scripts/` changes included): continue at Step 1. The reviewer gets
  `trusted: yes`.
- **Anyone else's branch — the default.** Do not run this skill, or
  `scripts/pr-ready.sh`, from that checkout. Use "Someone else's branch" below.

## Someone else's branch

Work from a checkout of **main**, never the PR's: start the session there, so the
`pr-reviewer` agent definition loaded is main's, not the PR's.

1. Run main's `scripts/check-pr.sh` first — main's copy, never a PR checkout's
   (`.claude/rules/security.md`). The invocation is the script header's own; in a
   fork clone, use the remote that points at the canonical repo in place of
   `origin`:

```bash
( set -e; git fetch origin main; f="$(mktemp)"; trap 'rm -f "$f"' EXIT
  git show origin/main:scripts/check-pr.sh >| "$f"; bash "$f" <pr-number> )
```

   No `check-pr: PR #N ...` verdict line means it did not run. Stop on findings
   (exit 1) and tell the user; exit 3 means binary files need a manual look first.

2. Fetch the PR head as data — no checkout, no new ref — and confirm it is the head
   GitHub shows:

```bash
set -eo pipefail
N=<pr-number>
UP="$(git remote -v | awk '$2 ~ /github\.com[:\/]thoughtspot\/thoughtspot-agent-skills(\.git)?$/ && $3 == "(fetch)" {print $1; exit}')"
test -n "$UP" || { echo "no remote points at thoughtspot/thoughtspot-agent-skills"; exit 1; }
git fetch --no-tags --quiet "$UP" main
BASE_SHA="$(git rev-parse FETCH_HEAD)"
git fetch --no-tags --quiet "$UP" "refs/pull/$N/head"
HEAD_SHA="$(git rev-parse FETCH_HEAD)"
PR_HEAD="$(gh pr view "$N" --repo thoughtspot/thoughtspot-agent-skills --json headRefOid --jq .headRefOid)"
test "$HEAD_SHA" = "$PR_HEAD" || { echo "fetched $HEAD_SHA but the PR head is $PR_HEAD"; exit 1; }
echo "range: $BASE_SHA...$HEAD_SHA"
```

3. Dispatch main's `pr-reviewer` **read-only** with `trusted: no`, the printed range,
   and the PR number. There is no evidence block: nothing ran. With `trusted: no`
   the reviewer executes none of the branch's code. If the diff touches converter
   paths (the Step 4 pattern), also dispatch `conversion-consistency-auditor` on the
   same range, telling it the code is untrusted and must be read, not run.

4. Give the findings to the user. Do not post them; posting is the user's decision.

## Step 1: run the checks

Commit first. A dirty tree makes the evidence DIRTY, and a DIRTY block cannot carry
a review (the reviewer reads committed history).

The run takes about five minutes: give the Bash call a 600000 ms timeout, or run it
in the background and wait for it to finish.

```bash
set -o pipefail
bash scripts/pr-ready.sh --no-review
echo "pr-ready exit: $?"
echo "evidence: $(git rev-parse --absolute-git-dir)/pr-ready/evidence.md"
```

`--no-review` only silences the script's reminder that the review is this skill's
job.

## Step 2: stop if it failed

If `pr-ready.sh` exits non-zero, **stop here** and do not dispatch the reviewer.
Report to the user:

- the evidence path;
- exit 2: the run could not start (no upstream remote, a failed fetch, an unreadable
  workflow) — quote the script's stderr;
- exit 1: every FAIL row and the behind count, read from the evidence:

```bash
EVIDENCE="$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md"
head -1 "$EVIDENCE"
grep -E '^\| [a-z]+ \| .* \| FAIL \|' "$EVIDENCE"
grep -E '^Behind upstream main:' "$EVIDENCE"
```

Also stop, and ask the user to commit and re-run, if the first line of the evidence
contains `DIRTY` even though the exit was 0.

## Step 3: dispatch the reviewer

Read the diff range from the evidence — never re-derive the base. It is
`<base_sha>...<head_sha>`, the exact commits the checks ran against:

```bash
set -o pipefail
RANGE="$(python3 tools/validate/evidence.py range)" || exit 1
EVIDENCE="$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md"
echo "range: $RANGE"
echo "evidence: $EVIDENCE"
git diff --stat "$RANGE"
```

Dispatch the `pr-reviewer` agent (`.claude/agents/pr-reviewer.md`) with, written out
literally in the prompt (an agent does not share your shell):

- `trusted: yes` — always stated explicitly; this step is reached only on your own
  branch;
- the printed range, and the base ref named in the evidence's first line;
- the printed evidence path;
- the PR number, if a PR already exists, so it can read the description.

Pass the inputs, not your own reading of the change: a reviewer handed a conclusion
tends to confirm it.

## Step 4: converters also get the converter audit

If the diff touches a conversion skill (any runtime), the shared mappings or schemas,
or anything under `tools/ts-cli/ts_cli/`, also dispatch the existing
`conversion-consistency-auditor` agent, as `CLAUDE.md` requires before merging
converter changes. The pattern is deliberately broad: converter code is spread across
shared modules, and the audit is read-only, so a false trigger costs one agent run
and a miss costs an unaudited converter.

```bash
set -o pipefail
RANGE="$(python3 tools/validate/evidence.py range)" || exit 1
EVIDENCE="$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md"
CONVERTER_RE='^agents/(cli|coco-snowsight|databricks/skills)/ts-convert-|^agents/shared/(mappings|schemas)/|^tools/ts-cli/ts_cli/'
git diff --name-only "$RANGE" | grep -E "$CONVERTER_RE"
echo "match exit: $? (0 = converter change, 1 = none, anything else = error: stop)"
grep -F '`converter-parity`' "$EVIDENCE"
```

`check_converter_parity.py` already ran in Step 1 (it is in the check list); the
last line shows its row, which goes in the review alongside the auditor's report.

If anything matched, dispatch `conversion-consistency-auditor` on the same range.
Steps 3 and 4 are independent; dispatch the agents together.

## Step 5: append the findings to the evidence

Make a scratch file outside the work tree:

```bash
REVIEW_FILE="$(mktemp -d)/review.md"
echo "$REVIEW_FILE"
```

Write into it the reviewer's report — and, when Step 4 matched, the auditor's report
and the parity row under their own `###` headings. The reviewer's report must end
with its "What I checked and found nothing" section; the append refuses a review
without it, and refuses an empty one. Then, with the path printed above:

```bash
REVIEW_FILE=<the path printed above>
python3 tools/validate/evidence.py append-review --file "$REVIEW_FILE"
```

It replaces the Review section's "Not run" placeholder with a provenance line (the
range and base reviewed, marked advisory) and the text, and scrubs home-directory
paths. Re-running replaces the review rather than stacking a second one. It refuses
(exit 1) if HEAD has moved since Step 1, or the block is DIRTY, NOT READY or
unfinished: start again from Step 1 on the final head.

Do not edit the evidence file by hand, and do not soften or drop findings when
copying them in: the block is evidence of what the reviewer said.

## Step 6: scan it, then tell the user

The block is meant for a public PR, and the review text has not been through any
gate. Scan it with the customer-reference checker (with your private name list, if
you keep one):

```bash
EVIDENCE="$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md"
python3 tools/validate/check_customer_references.py --message-file "$EVIDENCE"
echo "scan exit: $?"
```

Exit 1 (a FAIL line): **stop** — tell the user the block must not be shared until
the finding is removed from the review text and the append is re-run. WARN lines
(personal details such as a home path or an email) get the same fix before sharing.

Then report:

- the evidence path;
- the findings by rank (blocker / should-fix / nit), with any blocker first;
- that the whole block goes in the **Evidence** section of the PR template
  (`.github/pull_request_template.md`), pasted as it is.

## Posting

**Never post on your own.** Posting the block to a PR is the user's explicit choice,
made by running the script's post option themselves. Mention that it exists only if
they ask. Note for them that the post option re-runs the checks and posts a fresh
block, whose Review section says "Not run": to share the review, paste the block
written here.
