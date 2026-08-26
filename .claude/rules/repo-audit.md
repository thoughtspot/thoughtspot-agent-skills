# Repo Audit Rubric

How this repo stays healthy over time. The audit is **not** a per-PR checklist —
manual checklists get rubber-stamped. Instead it is a durable rubric + a rerunnable
sweep, and every finding it produces must exit to one of exactly two places.

## The two-bucket rule (the whole strategy)

Every audit finding resolves into **one** of:

1. **A permanent automated check** — a `tools/validate/check_*.py` validator wired into
   `scripts/pre-commit.sh` and `.github/workflows/validate.yml`, so the issue *can never
   recur*. This is always preferred. (Examples: `check_no_v1_endpoints.py`,
   the secrets-marker anchoring, `check_coverage_matrix.py` date-enforcement — all from
   the 2026-06 audit.)
2. **A dated backlog item** — a `BL-NNN` entry in `docs/backlog.md` with a target date or
   reference, for findings that need real work. The coverage-matrix validator already
   enforces that backlog exemptions carry a date; backlog items should too.

Nothing stays as "we noticed this, we'll remember." A finding that is neither codified
nor backlogged is not done.

**The management goal:** keep migrating angles from the *manual* column into the *automated*
column. Each sweep should end with "which finding can become a validator?" Over time the
manual surface shrinks.

---

## Angle taxonomy

The angles split along one axis: **is the question answerable from the repo itself
(internal/static), or does it depend on something outside the repo that moves
(external/dynamic)?**

### Internal / static — "is the repo good against its own rules?"

These are mostly automated already. The deep sweep re-examines the *manual* ones and looks
for new codification opportunities.

| # | Angle | What it checks | Enforcement today |
|---|---|---|---|
| 1 | Legacy / dead files | Untracked build artifacts, orphaned dirs, stale references, dead code | `check_references` (broken links) + `vulture` (dead-code report, sweep) + MANUAL |
| 2 | README / SETUP accuracy | Skills table, symlink/stage steps match repo reality | `check_consistency` |
| 3 | open-items truthfulness | No shipped-unverified assumptions hiding in open-items; cross-skill index current | `check_open_items` + `generate_open_items_index --check` |
| 4 | Tools quality | `tools/` code health, error handling, dead code, function/module complexity | `check_module_health` (complexity ratchet — blocks new/worsening god-functions vs a baseline) + `check_file_size` (line-count gate on ts_cli modules — warn 500 / fail 1000) + MANUAL (error handling, dead code) |
| 5 | ts-cli gaps | Operations skills need but the CLI lacks; inline `requests` anti-pattern | MANUAL (+ `check_patterns`) |
| 6 | Testing-framework value | Tests assert behaviour, not just presence; smoke tests are real | `check_smoke_tests` (presence) + MANUAL (value) |
| 7 | PR-validation effectiveness | CI is not a strict subset of pre-commit; gates actually fire; gate effectiveness review (see `docs/quality-gates.md` audit checklist) | `generate_quality_gates --check` (catalog freshness) + MANUAL (effectiveness review) |
| 8 | Cross-runtime skill drift | CLI / CoCo / Databricks mirrors in sync; parity matrix current | `check_mirror_sync`, `check_runtime_coverage`, `generate_parity --check`, `check_skill_naming` |
| 9 | Conversion consistency **+ implementation drift** | Two halves. (a) *Semantic*: every converter agrees with the invariants. (b) *Implementation*: converters agree on **how** they are built — shared helpers in `formula_common` imported rather than re-implemented or skipped, one spelling per emitted construct, nothing hand-instructed in prose that a sibling codified. Scope is **discovered, never listed** — a new `ts-convert-*` is audited from its first commit. | `conversion-consistency-auditor` agent (**now invoked by the sweep** — see the note below), `check_coverage_matrix`, `check_formula_catalog`, `check_converter_parity` *(planned, BL-217)* |
| 10 | Security | No secrets, no v1 endpoints, credential-handling rules honoured | `check_secrets`, `check_no_v1_endpoints` |
| 11 | Codification | (a) Repeated skill logic that should become `ts` CLI / shared reference / validator; (b) *agentic → deterministic*: skill steps that are mechanical transformations (parsing, type mapping, TML emission, formula rewriting) currently executed by the LLM but codifiable as deterministic Python — yielding faster, cheaper, more reproducible results. The Tableau `translate-formulas` pipeline (ts-cli v0.17.0) is the reference pattern. | `jscpd` (code-duplication report, sweep) + MANUAL |
| 17 | Change correctness (delta bug-hunt) | Correctness bugs and `.claude/rules`/CLAUDE.md violations in the code that landed **since the last full audit** — the backstop for what slipped past per-PR review. Distinct from angle 4 (which is code *health*: complexity, dead code, duplication) — this hunts for *behavioural bugs*. | **full sweep only:** a `max`-level `/code-review` agent over the `<last-full-audit-sha>..HEAD` diff (see below) + **per-PR `/code-review` (recommended, primary net)** |
| 12 | Synthesis / advise | Prioritise findings, route each to a bucket | MANUAL (the sweep's final step) |

#### Angle 9's judgment half ran nowhere until 2026-08-26

Worth recording, because it is the failure mode an enforcement column invites. Angle 9's
enforcement listed an *agent* alongside two validators. The validators run per-PR; the
agent ran neither per-PR nor in the sweep — the workflow never invoked it. So the half of
angle 9 that needs judgment (semantic invariants, and implementation drift, which no
validator covers at all) was enforced by nothing while the rubric read as covered.

Two compounding staleness bugs made it worse: the agent scoped itself to a hardcoded
"five conversion skills" when nine existed, and to invariants "I1–I7, N1" when the doc
had grown to I1–I14 + PT1. Invoked as written, it would have audited 5 of 9 converters
against 8 of 15 invariants.

The fix has three parts, all landed together: the sweep now invokes the agent; the agent
discovers converters and invariants at run time instead of listing them; and angle 9's
remit explicitly covers implementation drift. **The lesson generalises — when an angle's
enforcement names an agent rather than a validator, check that something actually
invokes it.** Angle 12 (synthesis) is the only other angle in that shape, and it runs by
construction.

**How a new converter gets picked up.** Nothing is edited. The agent globs
`agents/cli/ts-convert-*`, classifies by the `from`/`to` direction token the naming rule
guarantees, and enumerates invariants from the schema file's headings. Same principle as
`tools/validate/_dirs.py`, which exists because ~18 validators each hardcoded the runtime
dir list (BL-110) — a missed edit there reported PASS, exactly as a missed edit here
reported "consistent".

#### Code-health tooling (the sweep runs these; not per-PR gates)

Complexity is gated per-PR by `check_module_health` (deterministic, low false-positive).
Dead code and duplication are **judgment-heavy and noisy per-commit** (dynamic usage reads
as "dead"; sibling-skill SKILL.md prose reads as "duplicate"), so they are **run during the
sweep** — an agent/reviewer interprets and filters the output — rather than blocking every PR:

| Tool | Angle | Command | Read the output as |
|---|---|---|---|
| `radon` | 4 | `radon cc <paths> -n C -s` / `radon mi <paths> -s` | Complexity hotspots (gated by `check_module_health`; this is the descriptive view) |
| `vulture` | 1 | `vulture tools/ts-cli/ts_cli agents --min-confidence 80` | Candidate dead code — verify each isn't dynamically referenced before removing |
| `jscpd` | 11 | `npx jscpd tools/ts-cli/ts_cli agents --min-lines 25 --ignore "**/tests/**"` | Code duplication to codify — **ignore SKILL.md prose clones** (expected across sibling skills) |
| `agentlinter` | 2 | `npx agentlinter --local .` | **Optional advisory** on CLAUDE.md / SKILL.md instruction hygiene (context bloat, dead refs, cross-file overlap). Run **local-only** — the default mode uploads. Filter false positives (it flags file-path refs as "missing sections" and deliberate hard rules as "no escape hatch"). Not a gate; a candidate to formalise if it proves reliable. |

`radon`/`vulture` are Python dev deps (`pip install radon vulture`); `jscpd`/`agentlinter`
run via `npx`. None are required to commit — they inform the sweep.

#### Angle 17 — Change correctness (the `max` `/code-review` backstop)

Per-PR review is the *primary* net for behavioural bugs — cheapest to fix when the author
still has context. The recommended flow is `/code-review` (bug-focused; `low`/`medium` for
small diffs, `high`+ for risky ones) on the working diff before opening a PR, alongside CI.
This angle does **not** replace that; it is the **deep-sweep backstop** for what slipped
through, and it runs **only in the `full` sweep** (never the weekly `external` one, never
per-PR — a `max` review is a heavy fan-out and only the on-demand/nudged full cadence
justifies the cost).

Three rules keep it tractable and honest:

1. **Delta-scoped, not whole-repo.** The review target is the diff since the last full audit —
   `<sha>..HEAD` where `<sha>` is the commit of the most recent `docs/audit/*-full.md`
   (the same range the activity trigger already measures). This mirrors the currency-anchor
   principle for external angles: review only what changed since the last deep look, never
   re-flag settled code.
2. **`max` level + confidence filter.** The `/code-review` agent runs at `max` effort and
   adversarially verifies each candidate, reporting only high-confidence findings. It ignores
   the standard false-positive classes (nitpicks, style, lint/typecheck-catchable issues,
   pre-existing issues, findings on unmodified lines) — same discipline as a standalone
   `/code-review`.
3. **Two-bucket exit, same as every angle.** A one-off bug → a dated `BL-NNN` (or a fix PR);
   a *recurring class* of bug → promote to a `check_*.py` validator (preferred — that is the
   management goal, and it stops the sweep re-finding it next time).

It emits the standard findings schema, so synthesis (angle 12) dedups and routes it with
everything else. A future refinement is to fan it out into per-lens finders (bugs / rules
adherence / git-history context) with an explicit verify stage, mirroring a full
`/code-review`; the initial wiring is a single `max` finder to keep the change small.

### External / dynamic — "are our assumptions still true as the products move?"

A validator can never catch these — they live in the gap between our code and a moving
product. This is the **weekly specialist sweep**. Kept tractable by *currency anchors*
(below) so each run only checks the delta since last time.

| # | Angle | What it checks | Enforcement |
|---|---|---|---|
| 13 | **Product currency** | Per-platform: are our mappings, schemas, and "untranslatable" verdicts still accurate against the product's *current* capabilities? Newly-possible translations, deprecated constructs, new artifact types (chart libraries, semantic-view / metric-view features), API & version drift. | Weekly specialist sweep (per platform) + `check_mapping_currency` (per-PR staleness nudge) |
| 14 | **Performance** | (a) *skill runtime* — redundant API round-trips, un-batched prompts, the obj_id read-back pattern; (b) *generated-artifact efficiency* — do emitted formulas use performant TS constructs (`group_aggregate` vs `sql_*_aggregate_op`, join cardinality) or slow ones; (c) *ts-cli* — pagination, token-cache reuse. | Weekly sweep + MANUAL |
| 16 | **Dependency / supply-chain currency** | Python deps (`typer`, `requests`, `PyYAML`, `keyring`) — pinned ranges, known CVEs, EOL Python versions. | Weekly sweep + `pip-audit` gate (per-PR CI step over core + `[snowflake,qlik]` extras, plus weekly cron — see `.github/workflows/validate.yml`) |
| 18 | **Harness / framework currency** | The Claude setup itself, checked against the current Claude Code + model lineup: `.claude/settings.json` (stale model pins, unused new settings), `.claude/agents/*.md` frontmatter (model/effort tiers vs `.claude/rules/model-routing.md` and the current model tiers), `.claude/workflows/` (capabilities the runner has gained), and the `.claude/rules/*.md` files' own currency anchors. Same pattern as angle 13, pointed inward — the quality framework goes stale exactly the way product mappings do (a pinned `claude-opus-4-6` sat in settings.json after the Claude 5 family shipped; found manually 2026-07-28). **Repo-scoped only — see the boundary note below.** | Weekly sweep |

#### Angle 18's boundary with the machine-level review

Angle 18 and the `claude-practice:setup-review` skill both read
`.claude/agents/*.md` model/effort frontmatter, so the overlap needs an owner or
each will assume the other covered it:

| Surface | Owner |
|---|---|
| **This repo's** routing vs [model-routing.md](model-routing.md); `.claude/workflows/` capabilities; `.claude/rules/*.md` currency anchors | **Angle 18** (this rubric, `check_audit_freshness.py` nudge) |
| `~/.claude/` — user settings, machine-wide agents, installed-vs-used plugins/skills/MCP, the auto-memory folders and their `MEMORY.md` indexes; Claude Code features shipped since last review; routing *across* repos | **`setup-review`** (own `~/.claude/audit/` reports, own backlog, own 30-day SessionStart nudge) |

The split is "does the answer live in this repo?" Angle 18 checks whether this
repo's harness is internally coherent and current; `setup-review` checks the
machine the harness runs on and compares repos to each other. A finding on
`~/.claude/` state routes to `setup-review`'s backlog, not to `docs/backlog.md` —
otherwise a machine-level fix gets tracked where no machine-level review will read
it. Neither is a substitute for the other: `setup-review` cannot know this repo's
rules, and angle 18 cannot see the machine.

Worth knowing: the two nudges are independent, so a quiet angle-18 sweep says
nothing about machine drift. `setup-review` had never run on this machine as of
2026-08-26 despite being installed and armed.

> **Angle 15 — Conversion fidelity** (does converted output produce *semantically
> equivalent* results — the same numbers — not just valid-importing TML?) is **PARKED**
> as of 2026-06-17. It is the highest-value external angle but needs live data on both
> sides to test properly. Revisit once 13/14/16 are embedded.

Why these are external, not just "more angles": #13 already bit us twice — the **Muze
charting library** (we'd have emitted legacy charts forever) and the **v1 endpoint
removal** (started 404ing on newer builds). Both were correct decisions when made, made
obsolete by the product moving.

---

## Currency anchors — the artifact that makes the weekly sweep tractable

Every mapping and platform schema file carries a header anchor recording what product
state it was last validated against:

```markdown
<!-- currency: <platform> — <YYYY-MM> (<context, e.g. "Cortex Analyst GA">) -->
```

The specialist reads the anchor, checks only what changed in that platform since that
date, updates the mappings if needed, and bumps the anchor. Without anchors, every sweep
re-reviews everything; with them, each run is incremental.

`check_mapping_currency.py` (per-PR, soft-warn) nudges when a changed mapping/schema file
has a missing anchor, or one older than ~6 months. It never blocks — external knowledge
can't gate a PR — but it keeps anchors from rotting.

---

## Platforms in scope (expand here)

One specialist lens per platform. **Adding a platform = add a row here + a currency
anchor to its mapping/schema files.** That is the entire expansion cost.

| Platform | Specialist source of truth | Mapping/schema home |
|---|---|---|
| ThoughtSpot | SpotterCode MCP (`get-rest-api-reference`, `get-developer-docs-reference`) | `agents/shared/schemas/thoughtspot-*.md` |
| Snowflake | Snowflake docs (web) | `agents/shared/mappings/ts-snowflake/`, `schemas/snowflake-schema.md` |
| Databricks | Databricks docs (web) | `agents/shared/mappings/ts-databricks/`, `schemas/databricks-metric-view.md` |
| Tableau | Tableau docs (web) | `agents/shared/mappings/tableau/` |

---

## Cadence

| Scope | When | How |
|---|---|---|
| Internal validators (1–10 where automated) | Every PR | pre-commit + CI |
| **External sweep (13, 14, 16, 18)** | On demand, **when nudged** (~weekly threshold) | `Workflow({name: "repo-audit", args: {scope: "external"}})` |
| Full deep audit (all angles) | On demand, **when nudged** (time or activity) + before a release / new runtime | `Workflow({name: "repo-audit", args: {scope: "full"}})` |

**No scheduled cron.** Execution is nudge-driven and on-demand, not automated — see
the rationale under Freshness triggers.

Weekly is deliberately the *external* scope only — the internal angles are already
per-PR validators, so re-running them weekly adds nothing. The weekly cadence is a
starting point chosen to embed the habit; move to a slower or release-triggered cadence
once it is routine.

### Freshness triggers (nudge, never auto-run)

`check_audit_freshness.py` surfaces *both* cadences when they come due, and is silent
otherwise — safe to run on every commit and at session start. It nudges; it never runs
an audit. (A full audit spawns many agents and produces human-routed findings — it must
be a deliberate `Workflow` call, not unattended automation.)

| Nudge | Trigger |
|---|---|
| External sweep due | the more recent of the latest `docs/audit/*-external.md` **and** `docs/audit/*-full.md` older than `EXTERNAL_MAX_AGE_DAYS` (7) — a full audit runs all angles (external included), so it satisfies the external cadence too |
| Full audit worth considering | **time:** latest `*-full.md` older than `FULL_MAX_AGE_DAYS` (90), **OR activity:** a new skill / new runtime / 2+ new shared refs / 40+ commits since the last full audit (measured from the report's commit, `git log <report-sha>..HEAD`). A ts-cli version bump is deliberately not an activity trigger — not audit surface, and redundant with the commit count |

The activity trigger is the important half: it fires the full audit when *substantial
work* has landed, not just when the calendar says so.

**Why nudge-on-demand and not a scheduled cron.** A sweep produces findings that a human
must route to a validator-PR or a dated `BL-NNN`; a cron can't do that, so it would only
generate a report that still waits on your attention — the expensive part is unchanged.
The nudge is also *activity-aware*, so it stays silent when nothing has changed (a weekly
cron would burn tokens regardless), and it lets you run the sweep when you have attention
ready to act on the results. The nudge catches "it's been a week" the next time you touch
the repo (≈daily on an active repo), and `check_mapping_currency` catches the activity
case the instant a mapping is edited — together they cover external drift without a
scheduled job. If a genuinely hands-off report is ever wanted, a cron can be layered on
*top* of the same runner, but it is deliberately not part of this design.

---

## Portability — reusing this in another repo

The framework is two layers. Keep them separate so extraction is cheap, but **do not
build a cross-repo plugin until a second repo actually needs it** (speculative
abstraction is the same anti-pattern as adding CLI commands no skill uses).

| Layer | What it is | Where it lives |
|---|---|---|
| **Generic** (lift as-is) | two-bucket rule, internal/external taxonomy, currency-anchor concept, freshness-trigger logic (`check_audit_freshness.py` date/age/activity code), the workflow runner pattern | this rule + the validator's logic |
| **Repo-specific** (swap) | the angle list, the platform table, validator names, and the `CONFIG`/`ACTIVITY` constants at the top of `check_audit_freshness.py` | the tables in this rule + the CONFIG block |

To reuse: copy `check_audit_freshness.py` and this rubric into the target repo, edit the
`CONFIG`/`ACTIVITY` constants and the angle/platform tables, and point the workflow at
that repo's validators. The date/age/activity machinery is unchanged.

---

## Running a sweep

1. `Workflow({name: "repo-audit", args: {scope: "external" | "full"}})` — fans out one
   agent per angle (and per platform for #13), synthesises a prioritised report.
2. The report lands in `docs/audit/<YYYY-MM-DD>.md` (see that directory for prior runs —
   diff against the last to see what changed).
3. Route every finding: open a validator PR (preferred) or a dated `BL-NNN`. Update the
   report's status column as findings are closed.

## History

| Date | Scope | Outcome |
|---|---|---|
| 2026-06-17 | Rubric established | 12 internal angles + external 13/14/16; 15 parked; weekly external cadence |
| 2026-06 | Full (inaugural, 12-angle) | PRs #90–#100; BL-026/027/028/029. See `docs/audit/`. |
| 2026-06-29 | Angle #11 expanded | Added "agentic → deterministic" sub-dimension: classify skill steps as judgment-required vs mechanical, codify mechanical steps as ts-cli commands |
| 2026-07-24 | Angle 17 added | `max` `/code-review` backstop over the `<last-full-audit-sha>..HEAD` delta, full sweep only; per-PR `/code-review` remains the primary bug net |
| 2026-07-28 | Angle 18 added | Harness/framework currency — the Claude setup (settings, agent tiers, workflows, rules anchors) checked against the current Claude Code + model lineup; joins the external sweep. Motivated by the stale `claude-opus-4-6` pin found in the 2026-07-28 framework review |
| 2026-07-29 | Full (all angles incl. 17/18) | 63 raw → 58 findings (5 high / 23 med / 30 low). Headline: 4 high-severity correctness bugs in the rebuilt `ts migrate` engine (angle 17's first catch) + stale repo-publisher push-to-main flow. 6 validator promotions proposed. See `docs/audit/2026-07-29-full.md` |
| 2026-08-26 | Angle 18 boundary + 18.3 closed | `consistency-checker` moved from `model: haiku` to session model at `effort: low` (the rule's own "effort over model" principle, and the SDD policy's no-Haiku rule); added the corollary that a `model:` pin needs a reason the effort dial cannot serve. Documented the angle-18 / `claude-practice:setup-review` ownership split after finding both read agent frontmatter |
| 2026-08-26 | Angle 9 made real + self-scaling | The `conversion-consistency-auditor` was invoked by nothing (not per-PR, not the sweep) and hardcoded 5 of 9 converters / 8 of 15 invariants. Wired into the sweep, scope now discovered at run time, remit broadened to implementation drift, and PT2 added for the no-native-function class that shipped as `Migrated` in PR #440 |
