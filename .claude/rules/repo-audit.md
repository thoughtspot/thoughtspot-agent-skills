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
| 1 | Legacy / dead files | Untracked build artifacts, orphaned dirs, stale references | `check_references` (broken links) + MANUAL |
| 2 | README / SETUP accuracy | Skills table, symlink/stage steps match repo reality | `check_consistency` |
| 3 | open-items truthfulness | No shipped-unverified assumptions hiding in open-items | `check_open_items` |
| 4 | Tools quality | `tools/` code health, error handling, dead code, function/module complexity | `check_module_health` (complexity ratchet — blocks new/worsening god-functions vs a baseline) + MANUAL (error handling, dead code) |
| 5 | ts-cli gaps | Operations skills need but the CLI lacks; inline `requests` anti-pattern | MANUAL (+ `check_patterns`) |
| 6 | Testing-framework value | Tests assert behaviour, not just presence; smoke tests are real | `check_smoke_tests` (presence) + MANUAL (value) |
| 7 | PR-validation effectiveness | CI is not a strict subset of pre-commit; gates actually fire | MANUAL (meta) |
| 8 | Cross-runtime skill drift | CLI / CoCo / Databricks mirrors in sync; parity matrix current | `check_mirror_sync`, `check_runtime_coverage`, `generate_parity --check`, `check_skill_naming` |
| 9 | Conversion consistency | The conversion skills agree with each other against the invariants | `conversion-consistency-auditor` agent, `check_coverage_matrix`, `check_formula_catalog` |
| 10 | Security | No secrets, no v1 endpoints, credential-handling rules honoured | `check_secrets`, `check_no_v1_endpoints` |
| 11 | Codification | (a) Repeated skill logic that should become `ts` CLI / shared reference / validator; (b) *agentic → deterministic*: skill steps that are mechanical transformations (parsing, type mapping, TML emission, formula rewriting) currently executed by the LLM but codifiable as deterministic Python — yielding faster, cheaper, more reproducible results. The Tableau `translate-formulas` pipeline (ts-cli v0.17.0) is the reference pattern. | MANUAL |
| 12 | Synthesis / advise | Prioritise findings, route each to a bucket | MANUAL (the sweep's final step) |

### External / dynamic — "are our assumptions still true as the products move?"

A validator can never catch these — they live in the gap between our code and a moving
product. This is the **weekly specialist sweep**. Kept tractable by *currency anchors*
(below) so each run only checks the delta since last time.

| # | Angle | What it checks | Enforcement |
|---|---|---|---|
| 13 | **Product currency** | Per-platform: are our mappings, schemas, and "untranslatable" verdicts still accurate against the product's *current* capabilities? Newly-possible translations, deprecated constructs, new artifact types (chart libraries, semantic-view / metric-view features), API & version drift. | Weekly specialist sweep (per platform) + `check_mapping_currency` (per-PR staleness nudge) |
| 14 | **Performance** | (a) *skill runtime* — redundant API round-trips, un-batched prompts, the obj_id read-back pattern; (b) *generated-artifact efficiency* — do emitted formulas use performant TS constructs (`group_aggregate` vs `sql_*_aggregate_op`, join cardinality) or slow ones; (c) *ts-cli* — pagination, token-cache reuse. | Weekly sweep + MANUAL |
| 16 | **Dependency / supply-chain currency** | Python deps (`typer`, `requests`, `PyYAML`, `keyring`) — pinned ranges, known CVEs, EOL Python versions. | Weekly sweep (candidate for a future `pip-audit` gate) |

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
| **External sweep (13, 14, 16)** | On demand, **when nudged** (~weekly threshold) | `Workflow({name: "repo-audit", args: {scope: "external"}})` |
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
| External sweep due | latest `docs/audit/*-external.md` older than `EXTERNAL_MAX_AGE_DAYS` (7) |
| Full audit worth considering | **time:** latest `*-full.md` older than `FULL_MAX_AGE_DAYS` (90), **OR activity:** a new skill / new runtime / 2+ new shared refs / a ts-cli bump / 40+ commits since the last full audit |

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
