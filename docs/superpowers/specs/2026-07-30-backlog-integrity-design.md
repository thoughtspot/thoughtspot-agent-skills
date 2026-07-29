# Design: backlog + changelog merge integrity

**Date:** 2026-07-30
**Status:** Approved, not yet implemented.
**Owner:** Damian Waldron

## Background

`CHANGELOG.md` and `docs/backlog.md` are the two files in this repo that reliably
conflict when more than one person is committing. The cause is structural, not
procedural: both are append-only lists with a single fixed insertion point. New
changelog entries go at the top of the file under the current date heading; new
backlog items go at the end. So "where my entry goes" is the same lines for every
contributor, on every branch, every time.

PR #356 made the cost concrete. Two branches forked from a base where `BL-170` was
the highest number, and each independently claimed `BL-171`:

| | main | PR #356 |
|---|---|---|
| BL-171 | Five ts-cli emitters still emit the six non-existent string functions `Tier 1` | Bound `ts tml verify-render` per-tile probing `Tier 3` |
| BL-172 | `check_formula_catalog.py` header detection | – |

This is the second occurrence. The first was `BL-150`, resolved on 2026-07-28 by
renumbering the `ts-security-columns` item to `BL-151`.

Two properties of the PR #356 conflict are what motivate this design:

1. **The naive resolution looked correct and passed everything.** Stripping the
   conflict markers ("accept both") yields a file with two `## BL-171` sections.
   All 23 pre-commit checks and all 5 CI jobs pass on it. Nothing in the repo
   validates that a BL number is unique.
2. **Part of the damage was invisible in the conflict view.** The PR side of the
   hunk opened with a stale `**Target:** next live-instance pass on se-thoughtspot`
   line belonging to `BL-170` from when `BL-170` was still open; main has since
   marked it `RESOLVED` with an `**Outcome:**` block and no Target. Because git
   auto-merged main's `BL-171` body immediately *above* the conflict region, that
   line would have attached to the Tier 1 emitter item and pointed it at the wrong
   follow-up pass.

## The constraint that rules out restructuring

`BL-NNN` is a load-bearing identifier outside the backlog. Measured on `2831ce0`,
excluding `backlog.md` and `backlog-archive.md` themselves: **1,029 citations across
231 files** (SKILL.mds, coverage matrices, code comments, test docstrings, specs,
audit reports), broken down as `tools/` 399, `docs/` 325, `agents/` 300,
`.github/` 5. Nothing *parses* `backlog.md` (the
validators that mention it do so only in comments and message strings), so the
coupling is documentary rather than programmatic. But it means any scheme that
reassigns numbers is expensive, which is exactly why resolving PR #356 required
choosing which item keeps `BL-171` rather than bumping one.

The fix therefore belongs in **detection at commit time**, not in storage format.

## Scope

One validator plus a written resolution recipe. Nothing moves, nothing migrates,
no authoring habits change.

### `tools/validate/check_backlog_integrity.py`

Wired into the existing pre-commit suite and `.github/workflows/validate.yml`,
with three rules:

Baseline measured on `2831ce0`: 137 headings in `backlog.md`, 173 total resolvable
ids (headings plus archive-index and priority-index rows), 80 distinct ids cited in
rule 2's scope, 0 dead, no duplicate headings. All three rules pass on main as it
stands.

| Rule | Catches | Baseline |
|---|---|---|
| No duplicate `## BL-NNN` heading; no number defined in both `backlog.md` and `backlog-archive.md` | The BL-150 / BL-171 collision class | clean; 137 headings, 173 resolvable ids |
| Every `BL-NNN` cited under `agents/`, `tools/`, `.github/` resolves to a defined item | A renumber that misses citations | clean; 80 distinct cited, 0 dead |
| No git conflict markers (`<<<<<<<`, `>>>>>>>`, bare `=======`) in any tracked text file | A half-resolved merge shipping | currently ungated |

Rule 2 is adoptable immediately precisely because the baseline is already clean;
that will not stay true indefinitely, so it is worth landing while it holds.

**Rule 2 deliberately excludes `docs/`,** despite 325 citations there. `docs/`
holds specs and audit reports, which are point-in-time records: a 2026-07-25 spec
citing the numbers as they stood then is correct as history, and forcing it to
track later renumbering would be wrong. The gate therefore covers the live,
load-bearing surfaces (skills, CLI, tests, workflows) where a stale number
misdirects current work. If this proves too narrow, widening it is a one-line
change to the scope list.

Rule 3 needs care on one point: a bare `=======` is legal Markdown (setext `<h1>`
underline) and appears in legitimate documents. Gate it on co-occurrence with a
`<<<<<<<` or `>>>>>>>` marker in the same file rather than flagging it alone.

### `CLAUDE.md` addition

Three lines recording the correct resolution for `docs/backlog.md`: take main's
side, then renumber the incoming item to the next free number, and never "accept
both". This is the mitigation for the stale-line class described below, and it is
aimed at whoever resolves next, including an agent.

## Non-goals, and why

**The per-entry file split** (one file per changelog entry / backlog item,
assembled by a script; the towncrier or changesets pattern). It would drive
add-time conflict frequency to near zero, but frequency is not the problem: over
90 days this repo saw 376 commits from the owner against 7 from the one
collaborator. It also costs the single-file grep the owner relies on daily, needs
an assembly tool and a generated priority index, and does not solve number
allocation anyway. Revisit if a third regular contributor appears; the changelog
is the half to do first. This validator does not block that change.

**Moving the backlog to GitHub Issues or Jira.** GitHub would allocate numbers, so
collisions become impossible, and tiers map onto labels. Against it: the 1,029
documentary citations all go stale unless `BL-NNN` survives as a title prefix plus
a mapping table; three ID spaces (`BL-NNN`, issue `#N`, PR `#N`) invite confusion;
the long rationale entries read worse as issue bodies; and agents lose offline
access to a file that is part of how work in this repo gets briefed. Deferred, not
rejected.

**Detecting the misattached-`Target:`-line class.** Tested and abandoned as not
cheaply detectable. After a naive accept-both, `BL-171` appears twice and *each* of
the two sections carries exactly one `Target:` line, so a per-section count rule
never fires. Renumbering to fix rule 1 leaves the misattachment in place. The mitigation
is the `CLAUDE.md` recipe, not a check. This limitation should be stated in the
validator's module docstring so nobody later assumes the check covers it.

## Testing

`tools/validate/tests/` is the established pattern. Use the PR #356 merge as the
fixture, since it is a real specimen rather than a constructed one:

- The reconstructed accept-both file must **fail** rule 1 with `BL-171` named in
  the error. Reproduce it with `git merge-file` against merge base
  `cde7f018`, PR head `7837775` and `origin/main`, stripping the marker lines.
- The resolution actually shipped (`a85ba49`, merged as `2831ce0`) must **pass**
  all three rules.
- A fixture with `BL-999` cited in a `SKILL.md` but absent from the backlog must
  fail rule 2.
- A Markdown fixture using setext `=======` underlines with no other markers must
  **pass** rule 3, guarding the false positive.

Both scans are single-pass; they must stay within the existing 15s pre-commit
timing budget.

## Success criteria

- A naive accept-both resolution of a BL-number collision fails pre-commit locally
  and `validate` in CI, naming the duplicated number.
- A renumber that leaves a dangling citation fails, naming the file and number.
- Committing a file containing conflict markers fails.
- No false positive on the repo as it stands: the full suite is green on
  `origin/main` at implementation time.
- `docs/backlog.md` and `CHANGELOG.md` keep their current format, so no existing
  cross-reference, workflow or reading habit changes.
