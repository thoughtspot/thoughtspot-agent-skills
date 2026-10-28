## Summary

<!-- What changes and why. -->

## Test plan

<!-- What you ran, and against what (no hostnames: name the cluster by profile or role). -->

## Evidence

<!--
On your own branch, paste the whole evidence block from `bash scripts/pr-ready.sh` (or
the `pr-ready` skill, which adds its review) as it is, from
`$(git rev-parse --absolute-git-dir)/pr-ready/evidence.md`. Run it on the final head, once
the branch is current with main: the block records the upstream base SHA, the head SHA
and whether the tree was dirty, so a block from an earlier head does not describe this PR.
Both execute the branch's code with your credentials: for someone else's PR, use main's
`scripts/check-pr.sh` and a human review instead.

`bash scripts/pr-ready.sh --post N` comments a block on PR N for you (only when it is
READY, the tree is clean and the PR's head is your HEAD), but it re-runs the checks and
posts a fresh block whose Review section reads "Not run": to share a reviewed block,
paste the file before any `--post` run, which replaces it.
-->

## Live evidence

<!-- For behaviour only a live instance can confirm: the `references/open-items.md` entries
that record it (skill and item number). Otherwise "N/A" and why (e.g. "docs only",
"offline tooling, covered by unit tests"). -->

## New runtime dependencies

<!-- Each new third-party package a skill or `ts-cli` needs at run time, with its
provenance: where it comes from, who maintains it, its licence, and why an existing
dependency does not cover it. Otherwise "None". -->

## Supersedes #N — every earlier review point mapped

<!-- If this PR supersedes, continues or reworks an earlier PR: link it, then map every
point raised in that PR's review to this diff — addressed (with `file:line`) or declined
(with the reason, and where that is recorded). The `pr-ready` skill's review checks this
mapping against the diff. Otherwise "None". -->

## Checklist

- [ ] **Public-repo content is synthetic.** No customer names, tenant URLs (Jira, SharePoint/OneDrive, Slack, Google Docs, ThoughtSpot clusters), employee names or customer data in code, examples, fixtures, screenshots, commit messages or this description. AI-assistant output pasted from a customer tenant has had its citation links removed. See `.claude/rules/security.md` → "Customer data and confidentiality".
- [ ] Ran `bash scripts/pr-ready.sh` (or the `pr-ready` skill) on my own branch's final head, and pasted its evidence block above. For someone else's PR: main's `scripts/check-pr.sh` and a human review instead.
- [ ] Skill version bumped and `## Changelog` updated for any changed `SKILL.md`; `CHANGELOG.md` updated for repo-level changes (`.claude/rules/versioning.md`).
