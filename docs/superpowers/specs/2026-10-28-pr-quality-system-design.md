# PR quality system: design

**Status:** draft for approval, revised after an independent refute review · **Date:** 2026-10-28

## 1. Why

On 2026-10-28 a contributor asked, about PR #671, "how do I make sure to test all these
aspects before opening the PR?" The honest answer was that they couldn't. The review
used tools and knowledge only the maintainer has: `check-pr.sh` with the private
denylist, a refute-briefed `/code-review`, the history of earlier review threads, and
knowledge of which gates are blind to what.

A cross-PR analysis followed. It covered all 29 external-contributor PRs and a sample of
about 50 maintainer fix PRs, and an independent refute pass then checked it against the
raw data. These findings survived and are the basis for this design:

| # | Finding | Evidence |
|---|---|---|
| F1 | **Maintainer PRs get no second reader.** 0 of 628 merged maintainer PRs has a GitHub review; 95% merge the same day. Defects surface later in audits (median about 47 days) or in live use, including customer SCAL tickets. | Branch protection: the sole code owner is also the sole bypasser |
| F2 | **The full audits attribute more behavioural findings to maintainer PRs than to external ones.** About 29 against 6–7. 2 of 5 checked external attributions were wrong (#471, #128), and all checked maintainer ones held. | Refute pass, claim 2 |
| F3 | **Silent wrong output is the largest *behavioural* defect class.** It imports clean, lints clean, and returns the wrong number (36 of 149 high/medium audit findings). Doc drift is the largest overall (52). Fail-open gates are the same class inside the tooling (16). | Refute pass, claim 5 |
| F4 | **Gates are a defect source, and PRs can edit the gates that judge them.** 26 fix PRs touched only gates, hooks or CI. Ratchets were raised in #311, #506 and #662. In `tools/validate/`, CODEOWNERS covers only the customer-reference gate and `_git.py`. Pre-commit prints PASS for a check that SKIPped. | `.github/CODEOWNERS`, `scripts/pre-commit.sh` `run_check` |
| F5 | **No single local command runs what CI runs.** That caused the false "validators pass" claims in #440 and #505. | Refute pass, claim 7 |
| F6 | **Version, BL-id and CHANGELOG collisions occurred in 9 external PRs.** The cause is structural: PRs claim numbers in append-only registries while main moves at a median of 5 merges per active day, and external PRs wait a median of 3 days. | Refute pass, claim 8 |
| F7 | **Smoke tests don't run in CI for most skills.** CI runs a hardcoded list of 7 of the roughly 13 credential-free smokes (`validate.yml:251-254`). `check_smoke_tests.py` checks only that the file exists. | Spec review S3 |
| F8 | **Two named semantic blind spots in lint.** `[TABLE::COL]` references inside `formulas[].expr` are not checked (`tml_lint.py:633`). No join-operator check exists anywhere. | `tml_lint.py` |
| F9 | **External review is multi-round, and fixes aim at the listed repro rather than the class.** #440 went 5+ rounds and #517 had 17/25 adversarial inputs still wrong. Resubmissions drop earlier review points (#671, #662). Design decisions surface only at review. Reimplementation instead of reuse recurs across four authors. | Three batch reports |
| F10 | **External PRs are large.** Median 1,329 changed lines; 17 of 29 exceed 1,000. Two died open after 43 and 57 days. | `prs.tsv` |

**Claims explicitly not relied on:**
- per-PR escape rates, and any maintainer/external ratio (95% range about 0.9–5×)
- the #583→#586 chain
- the October in-PR-review inference

## 2. Intent

Make the review the maintainer does on a PR **runnable by whoever opens it, before
opening it, including on the maintainer's own PRs**. Review time then goes on decisions
and spot checks, not on finding validator failures or building the first repro.

## 3. Goals, non-goals, anti-goals

**Goals**
- **G1:** Every PR, the maintainer's included, runs the same pre-merge checks and
  review, and attaches the evidence.
- **G2:** One local command runs **a superset of what CI checks** and prints explicitly
  what differs from CI and why. (Identical results are not achievable: the pytest
  matrix, local-only denylist, opt-in upstream checkouts and time-varying pip-audit
  results all differ.)
- **G3:** Review-only knowledge (failure classes, earlier review points, reuse
  expectations) is written down where the author's own Claude session reads it.
- **G4:** Gates are proven to fire, and **external** PRs cannot weaken them unnoticed.
  For maintainer PRs this is stated as a known limit (§8.2), not claimed.
- **G5:** Merge overhead that is not about quality (number collisions) is removed
  structurally where that is possible without breaking consumers.
- **G6:** The effect is measured against a baseline, with the window and method stated
  in advance.

**Non-goals**
- Replacing human review of external PRs.
- General proof of converter semantic equivalence. Angle 15 and the fidelity harness
  remain the deep tools.
- Rewriting git history. The confidentiality scrub is handled separately: PR bodies were
  edited on 2026-10-28, the tree is cleaned in #678, and history is not rewritten.
- CoCo runtime changes.
- **An AI review running in CI.** Deferred by maintainer decision (§8.3). §5 C2 records
  the security constraints a future CI job must meet, so they aren't lost.
- **An agent review of someone else's branch, locally or in CI.** Deferred to a
  dedicated design (§5 C2), which records the requirements it must meet.

**Anti-goals** (failure even if it works)
- A gate people learn to ignore: noisy review output, or a blocking check with a high
  false-positive rate.
- A checklist ticked without being done (#281–#283 merged with every box unchecked).
- Raising the barrier so far that colleagues stop contributing (see the threshold
  numbers in C7).
- Any automation that executes untrusted PR content with secrets, or publishes
  AI-derived text about PR diffs where the private denylist cannot run.
- New gates that are themselves fail-open (F4).

## 4. Constraints

- **21 of 29 external PRs come from forks.** In a fork clone, `origin` is the fork, so
  any `--base origin/main` logic must resolve the upstream remote by URL instead.
- **Branch protection:**
  - `enforce_admins` on, `strict` on
  - required context: `validate` only
  - `require_code_owner_reviews: true`
  - bypass list: the maintainer only; no rulesets
- The private customer denylist never enters CI (`security.md`).
- `generate_quality_gates.py` regex-parses `scripts/pre-commit.sh` `run_check` lines and
  `validate.yml`. Any change to where checks are listed must update it in the same PR,
  or the catalog and its own `--check` gate break.
- Existing smoke infrastructure: `tools/validate/run_smoke_tests.py`,
  `scripts/pre-push.sh`, `REQUIRED_EXTRA_ARGS`, a local `smoke-config.local.json`, and
  `check_smoke_tests.py`'s `ALLOWLIST` (meaning "this skill needs no smoke"; the runner
  imports it, and a test pins that).
- `tools/validate/tests/test_known_bad_fixtures.py` already proves 18 of the 51 gates
  fire on known-bad input.
- `check_pr_size.py` already exists (warn-only in CI).
- A root-level `CONTRIBUTING.md` would fail `check_repo_hygiene`, because it is not in
  `ALLOWED_TOP_LEVEL_FILES`.
- System `python3` on the maintainer's machine is 3.9. CI runs 3.10–3.14.

## 5. Design

### C1. `scripts/pr-ready.sh`: one command, superset of CI

- **Structured list.** A single structured list of checks (`tools/validate/checks.toml`
  or a Python module) records, per check:
  - its arguments per context (pre-commit staged / pr-ready / CI full / CI PR-only)
  - whether it is soft or hard
  - which tools it needs
- `pre-commit.sh`, `pr-ready.sh` and `validate.yml` read from that list.
  `generate_quality_gates.py` is rewritten **in the same PR** to read the list instead of
  regex-parsing the scripts.
- **The 24 checks with context-dependent arguments are modelled explicitly**, not
  flattened.
- **Upstream resolution.** `pr-ready` resolves the upstream remote by URL
  (`thoughtspot/thoughtspot-agent-skills`), fetches its `main`, and runs base-relative
  gates against that. It refuses to print "ready" when the branch is behind upstream
  main.
- **Missing tools.** A missing tool is a **FAIL** when the check is required for every
  PR (e.g. radon). It is an explicit, listed **NOT RUN** when the check is opt-in by
  design (e.g. `check_ossie_mapping_sync` without an apache/ossie checkout).
  `pre-commit.sh` shows SKIP and NOT RUN lines instead of hiding them under PASS.
- **Output.** An evidence block containing:
  - checks run
  - NOT RUN list with reasons
  - CI-vs-local differences
  - upstream base SHA and head SHA
  - smoke results

  It is written to a file, for pasting into the PR template.
- **Ownership.** The runner and the list go under CODEOWNERS.

### C2. Adversarial review: repo reviewer agent, run locally

- **The brief lives in a repo reviewer agent**, `.claude/agents/pr-reviewer.md`.
  `/code-review` takes no brief argument, so an agent file is the single source. It is
  tiered per `model-routing.md`: a review gate, **`effort: max`**, no model pin.
- **What the brief covers:**
  - silent wrong output: build the output and check values, not just lint (local-only
    instruction; see the CI constraints below)
  - fix the class, not the instance: search for siblings of every fixed bug
  - claims vs diff: every statement in the PR body, CHANGELOG, `--help` and docs must be
    true of the diff
  - reuse: `formula_common`, the existing pipelines, ts-cli rather than raw REST
  - earlier review points: if the PR supersedes another, check the author's own
    mapping of every earlier point (C7's "Supersedes #N" section) against the diff;
    the reviewer reads no PR threads (see the deferred design below)
  - destructive paths need a backup, re-check and rollback
  - security basics: TLS, path traversal, secrets in argv
  - gate edits: flag any change to `tools/validate/`, baselines, the C1 list or CI
- **Reuse, don't re-brief.** For changes under `agents/cli/ts-convert-*` or converter
  code, the skill also invokes the existing `conversion-consistency-auditor` agent and
  `check_converter_parity`, as CLAUDE.md already requires before merging converter
  changes.
- **The brief demands refutation.** It must report what was tried, and default to "this
  is a problem" when uncertain.
- **Local skill.** `.claude/skills/pr-ready/` runs C1, then the reviewer agent on the
  diff against upstream main, and appends the findings to the evidence block. The
  evidence block records the head SHA reviewed, so a stale block is visible.
- **Only on your own branch (revised 2026-10-28 after review).** The skill's checks
  (`pr-ready.sh`, its first step after the confirmation below) run the branch's own
  code (the runner, every validator, the smokes and the test suite) with the
  runner's full environment, and from a PR checkout the PR also controls the skill,
  the reviewer brief, `pr-ready.sh` and `.claude/settings.json` hooks. So before
  anything runs, the skill says that it executes the branch's code with the user's
  credentials, and asks the user, every run, to confirm the branch is their own: they
  wrote it, or have read all of it. Only on that confirmation does it run, and it
  passes the reviewer `trusted: yes`; without exactly that value the reviewer refuses,
  reading nothing from the branch (decided 2026-10-28; there is no read-only mode).
  Without the confirmation, or for anyone else's PR, the skill stops and points to
  what is done today: main's `scripts/check-pr.sh` (main's copy, run as its header
  says, never the PR's) and a human review. The review text is scanned for secrets
  and customer references before it is appended, and the finished block again
  before it is shared.
- **Agent review of someone else's branch: deferred to a dedicated design (decided
  2026-10-28).** Three review rounds tried a read-only reviewer over pre-fetched copies
  of a PR's diff, text, threads and files, and each place the copies were moved to
  opened a new channel. This spec's intent (§2) does not need it: whoever opens a PR
  runs the review on their own branch, before opening it, the maintainer included. So
  it gets its own design. What those rounds established, as that design's
  requirements:
  - **No Bash for the reviewer.** The repo's settings pre-approve `Bash(git:*)`,
    `python3`, `pip`, `pytest` and `ts`, so a reviewer with Bash that followed one
    injected instruction would run it unprompted; a brief that says "read only" is
    not a control. This is the local counterpart of the CI constraint below.
  - **Inputs outside any git repository and outside the session's primary working
    directory.** Claude Code's loading of nested `CLAUDE.md` and `.claude/rules`
    files applies to paths under the primary working directory (review round 3), so
    a PR's own copies there become harness instructions. A worktree's git directory
    lies outside its working directory, so "inside the git dir" is not a fixed place
    either.
  - **None of the PR's own control files honoured:** `CLAUDE.md`, `CLAUDE.local.md`
    and `.claude/**` (instructions, agents, settings, hooks); `.gitignore`, `.ignore`
    and `.rgignore` (they hide files from Grep and Glob); `.gitattributes` (filters,
    smudging and re-encoding on archive or checkout).
  - **No secrets beside the inputs.** `tempfile.gettempdir()` holds the `ts` token
    cache (`ts_token_<slug>.txt`), so `$TMPDIR` is not a home for them.
  - **Path-scoped Read deny rules for credential files** (profiles, key files, the
    token cache, `settings.local.json`, which holds approved commands verbatim):
    reads confined by the brief's wording are not confined.
  - **The head pinned** to the SHA `check-pr.sh` scanned, refusing if it moved.
  - **Scanning the output is not a complete control.** `check_secrets.py` and
    `check_customer_references.py` match line by line, so an encoded or split value
    passes.
  - **PR threads are untrusted input, even on the author's own branch.** Anyone can
    comment on a PR, so this PR's and earlier PRs' comments and reviews are text a
    stranger may have written, and `check-pr.sh` does not scan an earlier PR's
    threads. Reading them belongs to this design. Until it lands, the reviewer reads
    no PR threads at all, and "earlier review points" checks the author's own
    mapping (C7's "Supersedes #N" section) against the diff instead (decided
    2026-10-28).

  Until that design lands, other people's PRs are verified as they were before this
  spec: main's `check-pr.sh` and a human review. The C7 backtest depends on it.
- **Maintainer PRs (§8.2).** The maintainer runs the same skill before every self-merge
  and reads the output. This is **advisory**. It is not a required check and not a
  GitHub review, so F1's metric (PRs with a GitHub review) does not move. Success for
  maintainer PRs is measured by post-merge escapes in C7, not by review counts.
- **Constraints for any future CI job** (not built now; §8.3). From the spec review,
  verified against claude-code-action's source and the CVE-2026-47751 advisory:
  - **Agent mode only** (a `prompt:` input). Trigger/tag mode checks out the PR head
    itself, even under `pull_request_target`.
  - **Execution boundary.** `actions/checkout` with no `ref`. A CI-only settings file.
    `--disallowedTools Bash,WebFetch,WebSearch,Edit,Write`, because the repo's committed
    `.claude/settings.json` pre-approves `Bash(python3:*)`, `pip`, `git`, `pytest` and
    `ts`, and has a SessionStart hook.
  - **Token scope.** `permissions: {contents: read, pull-requests: write}` with
    `GITHUB_TOKEN`, not the App token.
  - **Head pinning.** Pre-fetch the diff for the labelled head SHA, and abort if the head
    has moved. Trigger on `labeled` only; strip the label on `synchronize`.
  - **Label required for every non-maintainer PR, including same-repo ones.** Posting
    AI-derived text about a diff publicly is a publication channel, and the denylist
    can't run in CI (8 of the 29 external PRs are same-repo, including SCAL fixes).
  - **Enforcement.** It can't be a required check without blocking every fork PR (no
    secrets means skipped, and `validate` treats skipped as failed). A "review ran on
    this head" presence check is the only blocking shape, and it needs verifying first.
  - **The deferred design comes first.** A CI job that reviews a contributor's PR is
    an agent review of someone else's branch, so it waits for that design and meets
    its requirements (above) as well as these.

### C3. Gate integrity

- **Prove gates fire.** Extend `test_known_bad_fixtures.py`, which already covers 18 of
  51 gates, to every gate CI runs, including non-`check_*` gates: at minimum
  `generate_agentql_offline`, `generate_parity` and `suggest_dependency_types`.
  - A meta-check asserts every gate in the C1 list has a known-bad fixture there.
  - Gates without one go into one dated BL item with the list. They are not fixed in a
    single sweep.
- **Ratchets compare complexity, not keys.**
  - `check_module_health`: compare per-function complexity *values* against base,
    matching by function name across moves, so refactors that rename baseline keys
    (e.g. the Tableau split, b2b5bd1b: 9 keys moved, 0 raised) pass.
  - `check_file_size`: a raise relative to base fails, except a raise on a file whose
    split is already backlogged when the same PR shrinks it.
  - A raise otherwise needs a `ratchet-raise` label plus a cited dated BL item. This is
    a visible control for external PRs. For maintainer PRs it is only a speed bump,
    because the maintainer applies the label (stated limit).
- **CODEOWNERS.** Extend to:
  - `tools/validate/**`
  - `tools/ts-cli/ts_cli/tml_lint.py`
  - the C1 list and runner
  - `.claude/agents/pr-reviewer.md` and `.claude/skills/pr-ready/**`
  - `.github/pull_request_template.md` and issue templates

  This binds external PRs. It does not bind the maintainer (sole owner and sole
  bypasser); stated, not hidden.
- **Gate plus product code in one PR** gets a `pr-ready` warning asking for a split.
  It's a warning, because some changes are legitimately coupled (the CLAUDE.md verify.py
  row).

### C4. Smoke tests that actually run (extend the existing runner)

- Add a CI-run classification **next to** `ALLOWLIST`, under a different name (e.g.
  `CI_RUNNABLE`), in `check_smoke_tests.py`.
  - Today about 13 smokes are credential-free and about 14 need a cluster.
  - No browser category for now: none needs Playwright, and the quest smoke already
    uses the CI runner's headless Chrome.
- CI calls `run_smoke_tests.py --ci` for every `CI_RUNNABLE` smoke, replacing the
  hardcoded list at `validate.yml:251-254`. Fix the stale comment at
  `validate.yml:56` in the same PR.
- `check_smoke_tests.py` fails when a new smoke is neither `CI_RUNNABLE` nor listed as
  needing a cluster with a reason.
- **Cache isolation, scoped.** Credential-free smokes run with an isolated cache
  directory, set via the env var the skill reads (e.g. the chart builders'
  `~/.cache/ts-charts`), not a blanket clean `HOME`. Cluster smokes read profiles from
  `~/.claude`.

### C5. Remove number collisions without breaking consumers (revised)

The spec review showed that the approved "assign at merge or release" approach breaks
real consumers. §8.1 records the revised choice:

- **CHANGELOG fragments: kept.**
  - A PR adds `changes/<pr-or-slug>.md`. A maintainer PR folds the fragments into
    `CHANGELOG.md`, with `scripts/fold-changelog.py`.
  - `suggest_repo_changelog.py` and its CI `--base` gate learn to accept a fragment.
- **BL ids unique from the moment a PR opens.**
  - New items take an id derived from the PR, e.g. `BL-678.1`, `BL-678.2`, so nothing
    is rewritten later. Existing `BL-NNN` ids are untouched.
  - `check_backlog_integrity` (and its Rule 2 regex) accepts both forms, and rejects a
    `BL-<pr>.<n>` whose `<pr>` is not the PR it was introduced in.
  - Rule 2's scan scope is widened to `docs/`, `CHANGELOG.md`, `CLAUDE.md` and
    `.claude/`, because today 2,866 of 6,052 citations are invisible to it.
- **ts-cli version stays bumped in the PR**, because:
  - 18 SKILL.md files cite "Requires ts-cli vX"
  - installs are editable from main, so the version must identify the code at every
    commit
  - the audit snapshot records `ts_cli_version`

  The collision cost is cut, not removed:
  - `pr-ready` warns early when the branch is behind
  - a `scripts/rebump.sh` updates the branch from upstream main and re-applies the bump
    in one step, so the maintainer can fix a contributor branch at merge ("allow edits
    by maintainers"). That work tree belongs to someone else, so it is held to a
    requirement, not a procedure: **every git operation on someone else's branch —
    merge, commit, push — runs with hooks disabled**
    (`git -c core.hooksPath=<an empty directory> ...`), because the installed hook
    dispatchers run the branch's own scripts (`commit-msg` fires on a merge commit too,
    reproduced 2026-10-28; `pre-push` on a push); and **nothing from that work tree is
    executed or sourced**: main's copy of the script runs
    (`git show <upstream>/main:scripts/rebump.sh`), and `rebump.sh` must not `source`
    helpers from the work tree (as house-style scripts do with `scripts/lib/`) —
    anything it needs comes from main too. CI re-validates the pushed result
- **Rule files to update in the C5 PR:**
  - `versioning.md`
  - root `CLAUDE.md` (change-impact map; conflict-resolution section)
  - `tools/ts-cli/CLAUDE.md` (version sync, "Adding a command")
  - `.claude/rules/ts-cli.md`

### C6. Close the named semantic blind spots

- **Lint: `[TABLE::COL]` refs in `formulas[].expr`.** Reuse `on_clause_refs`. Skip refs
  without `::` (parameters, formula ids) and string literals. This is the class behind
  #529, #532 and #484's dangling refs.
- **Join operators: per converter, per emitted shape, declared in code.**
  - Each `ts_cli/<converter>/` declares the join operator shapes it may emit.
  - `check_coverage_matrix` asserts the converter's `coverage-matrix.md` agrees.
  - A converter test asserts that the emitted TML contains only declared shapes.

  This doesn't live in `ts tml lint`, which has no provenance for the TML it reads. And
  it is **not** an exemption list: Snowflake's ASOF `>=` is a documented wrong-number
  case (coverage matrix row 9, BL-240), so its declaration must be "declined loudly",
  not "allowed".
- **Review repros become a corpus.** `tools/ts-cli/tests/corpus/<converter>/` holds
  adversarial inputs with expected output. A review finding that needed a repro ships
  with the repro added there. #517's 25 inputs are the seed. Corpus inputs must be
  synthetic (security.md).
- **Live evidence checks stored values.** The `open-items.md` live-verification entry
  gains a required "post-import read-back" line: export after import and compare the
  fields that matter. #499 and #429 were "import OK, lint clean" and wrong.

### C7. Front-load decisions; measure

- **`.github/CONTRIBUTING.md`.** GitHub shows it, and it avoids the root-file hygiene
  gate. One page: merge criteria, `pr-ready`, what needs a design issue first, size
  guidance, and the resubmission rule. It links to rules rather than restating them.
- **Design-issue template.** A design issue is required before building when a PR would:
  - add a skill
  - add a third-party runtime dependency (with provenance)
  - need a repo-rule exception

  Size alone **warns** through the existing `check_pr_size.py` (threshold about 1,500
  changed lines) instead of requiring an issue. 14 of 29 past external PRs exceeded
  that, and requiring pre-approval for half of all contributions would hit the
  "raising the barrier" anti-goal.
- **PR template additions:**
  - the evidence block (C1/C2)
  - live-evidence pointer (`open-items.md` entries, or N/A with a reason)
  - new runtime dependencies
  - "Supersedes #N: every earlier review point mapped (link)"
- **Measurement (G6), stated up front:**
  - **Window:** the next 90 days, or 15 external PRs merged or closed, whichever comes
    later. External PRs arrive at about 5 a month, so "30 PRs" was not a meaningful
    window.
  - **Metrics:**
    - review rounds per external PR
    - days open
    - blocker findings per first-round review
    - post-merge defects, each attributed to an **introduction PR and date** (the method
      from the refute pass, so defects are counted by when they entered, not when they
      were found)
    - maintainer and external PRs reported separately
  - **Detectable effect:** with n of about 15, only large changes are detectable (e.g.
    median rounds 2 → 1). Results are reported as direction plus the raw counts, not as
    rates with false precision.
  - **Publication:** tables are keyed by PR number, never by author (security.md
    forbids employee identifiers). The script goes in `tools/`; numbers go in
    `docs/reviews/`.
- **Backtest: the acceptance test for C2, kept private.**
  - **n is about 16, not 29.** 13 of the 29 PRs were force-pushed and their first heads
    can't be recovered from GitHub.
  - **Run: waits for the deferred untrusted-branch design (§5 C2).** Every first head
    in the backtest is a contributor's, so reviewing it is an agent review of someone
    else's branch; the backtest runs once that design exists, and under it. Whatever
    it settles, never C1 / `pr-ready.sh` on a contributor's head: it executes that
    head's code. The one exception is a disposable environment with no credentials of
    any kind (e.g. environment exports, Keychain, token caches, SSH keys and agents,
    `.p8` key files, `~/.databrickscfg`, git credential helpers, `gh` auth),
    discarded after the run.
  - **Judge** today's rules separately from rules that existed at the time.
  - **Compare** against the real review findings.
  - **Adjudicate** every finding only the AI raised: the maintainer decides real vs false
    positive before anything counts as a false positive, because the human oracle was
    itself incomplete (F1, F2).
  - **Location.** Fixtures and outputs live in a **private** repository, as with
    ts-model-parity. Several of these PRs carried customer data, and AI restatements of
    their diffs would re-publish it. Only aggregate numbers come into this repo, after a
    `check-pr.sh`-style pass.
  - **Targets.** None are set in advance. The first run sets the bar.

## 6. Sequencing

Each step is its own PR, run through as much of the new process as exists by then.
Gate-changing PRs get an independent refute-briefed review at max effort before merge.
Because each step that adds or changes a gate regenerates `docs/quality-gates.md`, the
gate steps merge **one at a time**, not in parallel.

| Step | PR | Depends on |
|---|---|---|
| 0 | Baseline metrics script + numbers (C7) | — |
| 1 | C1 list + `pr-ready.sh` + catalog generator rewrite; pre-commit shows SKIP / NOT RUN | 0 |
| 2 | C2 reviewer agent + `pr-ready` skill | 1 |
| 3 | C7 private backtest; maintainer adjudication | 2, and the untrusted-branch review design (§5 C2) |
| 4 | C3 known-bad meta-check + ratchet-by-value + CODEOWNERS | 1 |
| 5 | C4 `CI_RUNNABLE` + CI runner call | 4 |
| 6 | C7 CONTRIBUTING, issue and PR templates | 2 |
| 7 | C5 changelog fragments + `BL-<pr>.<n>` + Rule 2 scope + `rebump.sh` | 4 |
| 8 | C6 formula-expr lint; per-converter join declaration; corpus convention; read-back rule | 4 |
| 9 | Re-measure at the end of the window; decide on a CI review job | 3, window end |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Review output is noisy and gets ignored | The backtest measures precision first (once the untrusted-branch design it waits for exists); the brief requires evidence per finding |
| The C1 list becomes a new hand-kept list | It replaces three lists and the catalog parser; a check asserts every gate is listed or allowlisted with a reason |
| `pr-ready` is too slow (CI's suite job takes about 10 minutes) | Run the ts-cli suite once on the local interpreter; the evidence block states that the CI matrix is not reproduced |
| Contributors see more process | Design issue only for new skills, new dependencies and rule exceptions; size only warns |
| Maintainer controls are advisory | Stated in §8.2; measured through post-merge escapes in C7, not assumed |
| Confidentiality via new artefacts (backtest, corpus, metrics) | Private repo for the backtest; synthetic corpus; tables keyed by PR number |

## 8. Maintainer decisions

1. **Numbering collisions (approved 2026-10-28; revised after review; needs
   re-confirmation).** The approved intent was "PRs stop claiming numbers". The spec
   review found that release-time numbering breaks:
   - 18 SKILL.md "Requires ts-cli vX" lines
   - editable installs, where the version must identify the code
   - Rule 2's ability to see rewritten citations

   The revised C5 keeps the intent for BL ids (unique at PR open, never rewritten) and
   CHANGELOG (fragments), and keeps ts-cli version bumps in the PR, with `rebump.sh` to
   make collisions a one-command fix.
2. **Maintainer PRs: advisory review (decided 2026-10-28).** The maintainer runs
   `pr-ready` and reads it before self-merging; it doesn't block. **Known limit:** F1 is
   not closed in GitHub terms, and C3's controls don't bind the maintainer.
3. **Review stays local for now (decided 2026-10-28).** No CI job and no credentials.
   **Consequence:** a contributor's evidence block can't be verified to have run. The
   head SHA in it makes a stale block visible. The maintainer does **not** re-run the
   skill on a contributor's PR head (that would execute the PR's code, and the PR's own
   copy of the skill, with the maintainer's credentials in the environment), and does
   not point the reviewer agent at it: agent review of someone else's branch is
   deferred to a dedicated design (§5 C2). Instead, as before this spec: main's
   `scripts/check-pr.sh` (run as its header says) and a human review.

## 9. Left to the builder

- the format of the C1 list
- the layout of the evidence block
- exact CODEOWNERS globs within C3's list
- the fragment file naming
- the backtest fixture format
- the brief's wording, within C2's content list
