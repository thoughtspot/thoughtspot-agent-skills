# Branching Protocol

## Session-start check — now automated

A `SessionStart` hook in `.claude/settings.json` prints the current branch every session
and, on `main`, says so explicitly. Added 2026-08-26 (audit finding 18.8): this protocol
was prose the human had to remember, and the only thing that ran
`check_audit_freshness.py` was `pre-commit.sh` — i.e. *after* the edits the branch check
exists to gate. The hook makes both deterministic rather than advisory.

Note for anyone editing that hook: a **newly added** `settings.json` key is inert until
`/hooks` is opened or the session restarts, so a fresh clone gets it on the next session,
not the current one.

You can still run it by hand:

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
1. All `references/open-items.md` items in changed skills are **VERIFIED** (or explicitly deferred to a follow-up open item)
2. All validators pass: `python3 tools/validate/check_*.py --root .`
3. **A smoke test exists for every new or modified Claude skill** in `tools/smoke-tests/smoke_<skill>.py` — or the skill is on the `ALLOWLIST` in `tools/validate/check_smoke_tests.py` with a justification comment. The validator (`check_smoke_tests.py`) runs in the pre-commit hook
4. Changes have been tested against a live instance where required (use the smoke test from #3 as the entry point)

Steps:
```bash
git push -u origin wip/<branch>
# Open a PR on GitHub — do not merge locally
# After the PR is merged on GitHub:
git branch -d wip/<branch>
git push origin --delete wip/<branch>
```

## Active wip branches

Derive the list — do not maintain it by hand. (A hand-kept table stood here until
2026-08-27: mutable status inside a rules file, which concurrent sessions had to
race to update and which was stale whenever they lost.)

```bash
git fetch --prune && git branch -r | grep 'origin/wip/' || echo "no active wip branches"
```
