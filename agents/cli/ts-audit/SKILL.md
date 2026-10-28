---
name: ts-audit
description: Scan a ThoughtSpot environment across five angles — AI Readiness, Data Modeling, Human Readiness, Performance, Security — and generate a prioritised audit report with actionable recommendations linking to existing skills.
---

# ThoughtSpot: Environment Audit

Scan your ThoughtSpot environment and surface structural issues, duplicates,
anti-patterns, security gaps, and Spotter readiness across all models, tables,
answers, and sets. The audit is read-only — it produces a report with prioritised
findings and actionable recommendations, but makes no changes.

**Audit angles (user selects which to run):**

<!-- BEGIN GENERATED: categories-table -->
<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by `python -m ts_cli.audit.generate`; do not edit by hand. -->

| Code | Angle | What it finds |
|---|---|---|
| **A** | AI Readiness | Description/synonym coverage, AI context, Spotter readiness score |
| **D** | Data Modeling | Complexity, join quality/types, progressive joins, duplicates, grain consistency, SQL pass-through, zero-column tables |
| **H** | Human Readiness | Name quality, hidden columns, orphans, direct table connections, formula promotion candidates |
| **P** | Performance | SQL Views, scalar formulas, filter/join progressiveness, date constraints, column sprawl |
| **S** | Security | PII detection, indexing without RLS, CLS gaps, RLS bypass, RLS join loops, credentials in analytics |
<!-- END GENERATED: categories-table -->

**When to use this skill:**

- You want to understand the state of a ThoughtSpot environment before making changes
- You need to find duplicate or overlapping models to consolidate
- You want to identify formulas that should be promoted from answers to models
- You need a Spotter readiness assessment across all models
- You want to find PII columns that lack appropriate security controls
- You need to prioritise which models to coach with `/ts-object-model-coach`

**Relationship to other skills:**

| Finding | Follow-up skill |
|---|---|
| Consolidate models / remove columns | `/ts-dependency-manager` (Repoint or Remove mode) |
| Promote formulas to model | `/ts-object-answer-promote` |
| Coach model for Spotter | `/ts-object-model-coach` |
| Fix PII indexing / security | Manual via ThoughtSpot UI or TML reimport |

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [references/check-catalog.md](references/check-catalog.md) | Every audit rule: what it detects, its severity per assessment profile, finding text and remediation — generated from the rule catalog |
| [references/rule-authoring.md](references/rule-authoring.md) | How to add, change or retire a rule (and add a category or derived field): the rule syntax, the gates, and the step-by-step procedures |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config |
| [../ts-dependency-manager/SKILL.md](../ts-dependency-manager/SKILL.md) | Action skill for audit findings (remove/repoint) |
| [../ts-object-answer-promote/SKILL.md](../ts-object-answer-promote/SKILL.md) | Formula promotion from answer to model |
| [../ts-object-model-coach/SKILL.md](../ts-object-model-coach/SKILL.md) | Per-model Spotter coaching |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure — columns, formulas, joins, properties |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer TML structure — formulas, search_query, data source |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure — db_column_properties, rls_rules |
| [../../shared/schemas/thoughtspot-sets-tml.md](../../shared/schemas/thoughtspot-sets-tml.md) | Set (cohort) TML structure |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Python package: `pyyaml` (`pip install pyyaml`)
- ThoughtSpot user must have **VIEW** access on objects to audit (no MODIFY required — this is read-only)

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-audit** — scan your ThoughtSpot environment across five angles.
Read-only — produces a prioritised report with actionable recommendations.

### A. Steps

  1.  Authenticate ......................................... auto
  2.  Choose scope (angles + profile + connections) ....... you choose
  3.  Enumerate objects .................................... auto  (~10-30s)
  4.  Export TML in parallel (cached) ...................... auto  (~1-5 min)
  5.  Analyse per selected angle .......................... auto
  6.  Generate audit report ............................... auto
  7.  Review findings and recommendations ................. you review

Confirmation required: Steps 0, 2, 3 (before export), 7
Auto-executed: Steps 1, 4, 5, 6

### B. Available angles

<!-- BEGIN GENERATED: angles-overview -->
  A  AI Readiness ...... Description/synonym coverage, AI context, Spotter readiness score
  D  Data Modeling ..... Complexity, join quality/types, progressive joins, duplicates, grain consistency, SQL pass-through, zero-column tables
  H  Human Readiness ... Name quality, hidden columns, orphans, direct table connections, formula promotion candidates
  P  Performance ....... SQL Views, scalar formulas, filter/join progressiveness, date constraints, column sprawl
  S  Security .......... PII detection, indexing without RLS, CLS gaps, RLS bypass, RLS join loops, credentials in analytics

  X  All angles (A, D, H, P, S)
<!-- END GENERATED: angles-overview -->

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If the file is missing or empty, prompt the
user to run `/ts-profile-thoughtspot` first.

If multiple profiles exist, ask:

```
Which ThoughtSpot profile?

  1. prod-cluster
  2. staging

Enter number or profile name:
```

Verify the profile:
```bash
ts auth whoami --profile "{profile_name}"
```

If verification fails, display the error and ask the user to re-run
`/ts-profile-thoughtspot` to fix the profile.

---

## Step 2 — Choose Scope

Three sub-decisions, asked sequentially.

### 2a. Angle selection

<!-- BEGIN GENERATED: angles-select -->
```
Which angles would you like to audit?

  A  AI Readiness
  D  Data Modeling
  H  Human Readiness
  P  Performance
  S  Security

  X  All angles (A, D, H, P, S)

Enter letters (e.g. "A,D,S" or "X"):
```
<!-- END GENERATED: angles-select -->

Store the selected angles for Step 5 branching.

### 2b. Assessment profile

<!-- BEGIN GENERATED: profiles -->
<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by `python -m ts_cli.audit.generate`; do not edit by hand. -->

```
Assessment profile — sets pass/fail thresholds:

  1. Spotter-ready      — aggressive, the bar for a Model Spotter will answer from (AI context required)
  2. General (default)  — lighter, the bar for Search and Liveboards (AI context recommended)

Enter 1 or 2:
```

Pass the choice to `ts audit run` as `--assessment spotter` (1) or `--assessment general` (2) in Step 5. What the profile changes:

- **A1 — Description coverage below threshold:** Spotter-ready: HIGH < 47.5%, MEDIUM < 95% · General: HIGH < 25%, MEDIUM < 50%
- **A2 — Synonym coverage below threshold:** Spotter-ready: HIGH < 40%, MEDIUM < 80% · General: HIGH < 12.5%, MEDIUM < 25%
- **A3 — No AI instructions configured:** Spotter-ready: HIGH · General: MEDIUM
- **A4 — Missing Spotter config:** Spotter-ready: HIGH · General: MEDIUM
- **A6 — Measure AI context coverage below threshold:** Spotter-ready: HIGH < 40%, MEDIUM < 80% · General: LOW < 80%
- **P8 — Column sprawl:** Spotter-ready: HIGH > 500, MEDIUM > 250 (provisional) · General: HIGH > 1500, MEDIUM > 500
<!-- END GENERATED: profiles -->

A profile is a named override layer in the rule catalog
(`tools/ts-cli/ts_cli/audit/catalog/profiles.yaml`, and a rule's `profiles:` block): it
may change a rule's bands, severity, wording, remediation or on/off status, never what
the rule checks. The rules that differ by profile show each
profile's grading in [references/check-catalog.md](references/check-catalog.md).
Omitted, it defaults to `general`, and the report header names the assessment used.

### 2c. Connection scope

```
Scope the audit to specific connections, or scan everything?

  A  All connections (full environment scan)
  C  Choose specific connections

Enter A or C:
```

If **C**, list connections:
```bash
ts connections list --profile "{profile_name}"
```

Display as a numbered list and let the user pick.

Store the selected connection names. In Steps 3-4, filter objects by
`metadata_header.dataSourceName` or `table.connection.name`.

---

## Step 3 — Enumerate Objects

This step picks the Models to audit and shows the user an inventory. It does **not**
collect the audit's data: `ts audit run` (Step 5) fetches that itself.

**The Models (always):**

```bash
ts metadata search --subtype WORKSHEET --all --profile "{profile_name}"
```

Filter to actual Models (not legacy Worksheets) using `metadata_header.type` or
the presence of `worksheetVersion` in the response. Their GUIDs are what Step 5 passes
as `--models`.

**What `ts audit run` fetches, and why it is not chosen here.** Each rule in the rule
catalog (`tools/ts-cli/ts_cli/audit/catalog/`) declares the data it reads, as `requires`
or `uses` (see [references/rule-authoring.md](references/rule-authoring.md)). The audit
fetches the union of what the selected rules declare, whichever category selected
them:

| Data | Fetched |
|---|---|
| Model TML with its associated Table TML, metadata headers, dependents | Every audit |
| AI instructions (`ai/instructions/get`, one call per Model) | When a selected rule declares `ai_instructions` (A3, A5) |
| Answer TML (the Answers among the Models' dependents) | When a selected rule declares `answers` (H7, H8, H9) |
| Sets and each Set's consumers | When a selected rule declares `sets` (H4, H5) |

So narrowing `--angles` also narrows the fetch. On the AI-instructions lookup, a final 401
(after re-authentication), a 429, or any `requests` exception raised by the request or
its re-authentication aborts the run once, because every later call would fail the same
way. Any other non-2xx (403, 404, a 5xx after the client's retries, …) or a non-JSON
2xx skips that Model's AI-instruction rules with a warning, and the report shows "Could
not be read".

**Optional, for the inventory summary only** (the audit does not read these results):

```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile "{profile_name}"
ts metadata search --type ANSWER --all --profile "{profile_name}"
```

Sets are **not** in a Model's dependents (BL-324); `ts audit run` discovers them
directly when a selected rule declares `sets` (one cohort listing per Model), adds each
Set to its Model's dependents, and looks up each Set's own consumers for H5. A Set whose
consumer lookup fails, hides dependents from this user, or is consumed only by
another Set is **not** reported as an orphan — the audit records a warning instead.
A Model whose Set listing is incomplete contributes no Set rows, only a warning.
H4 ignores Set rows: a Model whose only dependents are Sets is still an orphan.
The Set discovery and the consumer lookup are the shared `tools/ts-cli/ts_cli/sets/`
modules (`discover.py`, `consumers.py`), the same code behind `/ts-object-set-manager` and
the `/ts-migrate-orgs` Set gate. That skill's "How it works" section describes the API steps.

**If connection scope was set in Step 2c**, filter each result set to only include
objects whose `metadata_header.dataSourceName` matches a selected connection.

> **Why this step does NOT use `ts metadata search --connection`** (finding 11.1,
> 2026-08-26 — an earlier attempt at this change did, and was wrong). Two reasons, both
> verified against `filter_by_connection` (`commands/metadata.py:35`):
>
> 1. **The flag drops models and answers.** It keeps only rows with a matching
>   `metadata_header.dataSourceName`, and worksheets/models/answers do not carry that
>   field — so a connection-scoped audit would enumerate **zero** of them, while the
>   inventory summary below still prints `Models: N (scoped to: …)`. Step 2c is right to
>   scope models via `table.connection.name` instead.
> 2. **The flag takes one connection.** It is `Optional[str]` and not repeatable, whereas
>   Step 2c explicitly offers *"Choose specific connections"* (plural).
>
> Where a search really is table-only and single-connection — as in the `ts-convert-*`
> skills — prefer the flag: it **casefolds** both sides, which a hand comparison does not.
> Here, do the filtering yourself and **compare case-insensitively**.

**Display inventory summary and confirm:**

```
Object inventory:

  Models:     12 (scoped to: Snowflake_Prod)
  Tables:     87
  Sets:       8 (across 12 models)
  Answers:    34

Estimated export time: ~1 min (4-way parallel, cached)
Proceed with TML export? [Y / N]
```

---

## Step 4 — Export TML (parallel, cached)

Export TML for all enumerated objects. Use the same caching pattern as
`ts-object-model-coach` Step 4.5.

### Cache directory

```
~/.cache/ts-audit/tml-corpus/
```

### Cache key

`{guid}-{modified_epoch}.json` — where `modified_epoch` is the
`metadata_header.modified` timestamp from the search response. If the file
already exists, skip the export.

### Export strategy

Run 4-way parallel exports. For each object:

```bash
ts tml export "{guid}" --fqn --profile "{profile_name}"
```

**For models**, also export the associated tables:

```bash
ts tml export "{model_guid}" --fqn --associated --profile "{profile_name}"
```

### FORBIDDEN handling

If an export returns FORBIDDEN (403), cache the failure for 24 hours:
write `{guid}-FORBIDDEN.json` with timestamp. Do not retry within 24h.

### Progress reporting

```
Exporting TML: [=====>          ] 34/87  (12 cached, 2 FORBIDDEN)
```

`ts audit run` (Step 5) exports the TML it audits itself, and does not read this
cache: this step currently costs time without feeding the audit (BL-407). Skip it when
the user only wants the audit report.

---

## Step 5 — Analysis Engine

Run the audit via the `ts` CLI:

```bash
ts audit run \
  --models "{guid1}" --models "{guid2}" \
  --angles "{A,D,H,P,S}" \
  --assessment "{spotter|general}" \
  --profile "{profile_name}" \
  --output ~/Dev/audit-runs/{profile_name}-{date}/audit.json
```

The checks are **rules in a catalog**, not code: YAML under
`tools/ts-cli/ts_cli/audit/catalog/` (`categories.yaml`, `profiles.yaml`,
`rules/{ai,data,human,perf,security}.yaml`), run by a small deterministic rule engine
(`ts_cli/audit/engine/`). `--angles` selects categories, and a rule runs when any of its
categories is selected. Each rule declares the data it reads (`requires`/`uses`), and
the audit fetches exactly the union for the selected rules (see Step 3). The rule's
thresholds, severities and wording, and the `--assessment` profile's overrides of them,
are in its catalog entry.

<!-- BEGIN GENERATED: rules-files -->
<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by `python -m ts_cli.audit.generate`; do not edit by hand. -->

| Catalog file | Category | Rules |
|---|---|---|
| `rules/ai.yaml` | A — AI Readiness | A1–A6 |
| `rules/data.yaml` | D — Data Modeling | D1–D12 |
| `rules/human.yaml` | H — Human Readiness | H1–H5, H7–H10 (H6 retired) |
| `rules/perf.yaml` | P — Performance | P1–P9, P11, P13–P18 (P10, P12 retired) |
| `rules/security.yaml` | S — Security | S1–S5, S8–S11 (S6–S7 retired) |
<!-- END GENERATED: rules-files -->

See [references/check-catalog.md](references/check-catalog.md) for every rule — what it
detects, its severity per profile, its finding text and remediation (generated from the
catalog). To add, change or retire a rule, follow
[references/rule-authoring.md](references/rule-authoring.md); never add a Python check
function.

### Phase 2 — Usage Analysis (future)

*Requires a `ts data search` CLI command to query the TS: BI Server system model.
Will add dead-column detection, unused-object identification, and low-usage flagging.
See open items #9 through #12 in the reference file.*

---

## Step 6 — Generate Report

Generate the unified HTML report from the JSON output:

```bash
ts audit report ~/Dev/audit-runs/{profile_name}-{date}/audit.json \
  --output ~/Dev/audit-runs/{profile_name}-{date}/report.html
```

Or piped directly from Step 5:

```bash
ts audit run \
  --models "{guid1}" --models "{guid2}" \
  --angles "{A,D,H,P,S}" \
  --assessment "{spotter|general}" \
  --profile "{profile_name}" \
  | ts audit report -o ~/Dev/audit-runs/{profile_name}-{date}/report.html
```

The report is a single self-contained HTML file (~100–200KB) with five views:

| View | What it shows |
|---|---|
| **Dashboard** | Severity heatmap (models × angles), summary cards, stats |
| **Model Scorecard** | Per-model findings grouped by angle, recommendations, ERD placeholder |
| **Cross-Model** | Sortable/filterable table of all findings across models |
| **Object Map** | Table reuse (Sankey), model overlaps, dependencies (bar charts) |
| **Cleanup** | Orphan models, stale objects with checkbox selection + clipboard copy |

Open the HTML file in the user's default browser. It has no external dependencies
and can be shared directly via email or Slack.

---

## Step 7 — Review & Act

Display the summary:

```
Audit complete. {N} findings across {L} angles.

  CRITICAL: {n}    HIGH: {n}    MEDIUM: {n}    LOW: {n}    INFO: {n}

Report: ~/Dev/audit-runs/{profile_name}-{date}/report.html
```

Actionable findings link to existing skills:

| Finding | Follow-up skill |
|---|---|
| Consolidate models | `/ts-dependency-manager` (Repoint mode) |
| Remove dead columns | `/ts-dependency-manager` (Remove mode) |
| Promote formulas | `/ts-object-answer-promote` |
| Coach model for Spotter | `/ts-object-model-coach` |
| Fix PII / security | Manual via ThoughtSpot UI or TML reimport |

Ask the user: **review / act on a finding / done**

If **act**: ask the user to pick a finding. Provide the specific follow-up skill
command with pre-filled context from the finding.

If **done**: end the skill.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 3.2.2 | 2026-10-28 | **The report's join count and join depth are real.** Both read a Model-level `joins` key that Model TML does not have (joins sit under each `model_tables[]` entry), so every Model showed 0 joins and depth 0. They now use the same helpers as D1 and P7, so the report and those rules cannot disagree. No finding changes. |
| 3.2.1 | 2026-10-23 | **The catalog-derived sections are generated.** The category table, the Step 0 and Step 2a category lists, the Step 2b profile prompt with what each profile changes, and the catalog-file table of rule ids are now generated from the rule catalog (`python -m ts_cli.audit.generate`) and checked by the catalog gate, so a rule change can no longer leave them stale. |
| 3.2.0 | 2026-10-23 | **Model size lines from production data; S11 is CRITICAL.** The size lines flagged a quarter of production Models (2026-10 call-home data, 268k Models: 21% over the old 75-column HIGH line). P8 now owns column count: General MEDIUM above 500 (Search Data gets hard to use) and HIGH above 1,500 (queries slow down); Spotter-ready 250 / 500, provisional. Its "wider GROUP BY" rationale was wrong — a query groups only by the columns it selects — and is gone. D1 grades tables and joins at 30 / 50 (formulas unchanged at 30 / 50) and no longer reports columns (P8's) or join depth (P7's, same lines). S11 (an RLS join that closes a loop with the Model's joins) is CRITICAL: the Model is broken for every user under the rule, not merely at risk. On the SE demo snapshot D1 goes 204 → 6 findings and P8 15 → 0; nothing else changes. |
| 3.1.0 | 2026-10-23 | **S11 — RLS join cycles.** A Model whose joins plus the joins its Tables' RLS rules use form a directed cycle imports cleanly, then fails every query the rule applies to with "Guid Mismatch". S11 (Security, HIGH) reports each RLS join that closes such a loop, with the joins that lead back (a path it cannot walk is a warning, not a finding); `ts tml lint` I22 catches the same shape before import. Second routes through an RLS join are not flagged (BL-410). |
| 3.0.0 | 2026-10-23 | **Rules are data.** The Python check modules (`checks_*.py`) are gone: every check is a rule in a YAML catalog (`tools/ts-cli/ts_cli/audit/catalog/`) run by a small rule engine, and categories and assessment profiles are catalog data too. `check-catalog.md`, the report's labels and recommendations and the audit JSON's `check_meta` are generated from it, and a catalog gate checks every rule in pre-commit and CI. New [references/rule-authoring.md](references/rule-authoring.md) is the procedure for adding, changing or retiring a rule. **Findings are unchanged**: on every committed test input under both profiles, and on a local 351-Model snapshot, the catalog reports exactly what the old checks did (H6, a stub that never ran, is recorded as retired). **Deliberate behaviour changes:** (a) on one Model's AI-instructions lookup, any non-2xx other than 401 or 429 (403, 404, a 5xx after the client's retries, a final 1xx or 3xx, …) skips that Model with a warning instead of aborting the run (a non-JSON 2xx skipped it before and still does), while a final 401 (after re-authentication), a 429, or any `requests` exception raised by the request or its re-authentication aborts the run once; (b) `--angles ""` or `","` is a usage error (omit the flag for all), so is an unknown letter (`--angles A,X` silently ran only A before), and a repeated letter counts once; (c) `check_meta.thresholds` and the ERD's recommendation text are generated from the catalog, in words (the ERD's "Fix." line is the rule's remediation where it has one); (d) additive JSON: `categories` and `bands` on each finding, `summary.by_category`, `corpus.fetched_needs`, `instructions_read` per Model, and the report shows "Not collected" or "Could not be read" where AI instructions were not fetched or failed; (e) H8 and H9 are fast on large estates; (f) a `requests` exception on the AI-instructions lookup now aborts the run, and any other exception there propagates (both were skipped per Model before); (g) the report's per-finding metric bar reads the finding's bands and their direction, labelled "limit" or "target" in the measure's unit: a lower-is-better measure over its limit (P8's 90 columns against 75) now shows as over it, where it drew as a green "ok" bar against a default 80. Which data is fetched is now decided by the selected rules' `requires`/`uses` rather than by category letter — for every selection today, exactly what was fetched before. `ts audit run --snapshot-out` / `--snapshot-in` capture an audit's data and replay it offline (`--snapshot-out` refuses a directory inside a git work tree, or a non-empty one that is not an earlier snapshot). The pre-catalog ids P10, P12, S6 and S7 are recorded as retired, never reused. |
| 2.6.0 | 2026-10-22 | **The assessment profile now does something (BL-399).** Step 2b has always asked for Spotter-ready or General and promised different thresholds, but nothing passed the choice on: every check ran one fixed bar, so a Spotter-ready audit passed descriptions at 80% against a promised 95%. `ts audit run --assessment spotter|general` now carries it: A1 95% / 50%, A2 80% / 25%, A6 required (graded) / recommended (LOW), A3-A4 HIGH / MEDIUM; coverage is HIGH below half the pass mark. Both run commands pass it, and the report header shows it. Default `general`. |
| 2.5.0 | 2026-10-21 | **A6 — measure AI context coverage**: the share of visible measures carrying `properties.ai_context`, which the Spotter-ready profile has promised ("AI context required") with no check behind it; the finding names the uncovered measures. **A2 fix:** synonyms are read from `properties.synonyms`, where Model TML keeps them. A2 read the column root, so it reported 0% synonym coverage for every Model and A5's readiness score always lost its synonym weight — on 599 Models from the SE demo cluster, A2 flagged all 599 before the fix and 278 after. |
| 2.4.3 | 2026-10-02 | H5 orphan-Set check now fires: Sets discovered directly rather than from Model dependents (BL-302, BL-324). A Set whose consumer lookup fails, hides dependents, or is consumed only by another Set stays unreported with a warning. H4 ignores Set rows, so a Model with only Sets is still an orphan. |
| 2.4.2 | 2026-08-26 | Record why Step 3-4 connection scoping does **not** use `ts metadata search --connection`: the flag keeps only rows with a matching `dataSourceName`, which worksheets/models/answers do not carry, so it would enumerate zero of them — and it takes a single connection where Step 2c offers several. Keep the hand filter, but compare case-insensitively (finding 11.1). |
| 2.4.1 | 2026-07-03 | Fix stale Phase 2 cross-reference — "OI-6 through OI-9" corrected to "#9 through #12", matching the actual numbering in `references/open-items.md` (audit finding 5.4). |
| 2.4.0 | 2026-07-03 | Fix 3 audit bugs: (1) scorecard missing 77% of findings — child-object findings (columns, joins, formulas) now match by GUID, not lookup index; (2) false orphan models from pagination — `record_size: -1` in dependent payload; (3) false orphan models from associated export — dependent fetch now covers all model GUIDs from TML, not just input list. Batch size reduced 25→15 for reliability. |
| 2.3.2 | 2026-07-02 | Cluster heatmap: findings whose object is not a model (cross-answer/formula/table findings, or empty-guid) are no longer rolled up onto the first model in multi-model audits — this was inflating the first model's row (e.g. GTM Campaigns showing HIGH across angles it had no such findings for). Inherits the ERD fact/dimension classifier refinement |
| 2.3.1 | 2026-07-02 | ERD embed now shares one parser with the ts-object-model-erd skill (single source of definition); inherits the dimension/fact classifier fix so hidden RLS/parameter helper formulas no longer mislabel a dimension as a fact |
| 2.3.0 | 2026-07-02 | ERD: AI domain summary, multi-select filter chips, RLS red colour scheme, grouped controls bar, join-tree double-click, layered layout fixes |
| 2.2.1 | 2026-07-22 | Relax prompt-batching: allow independent questions in a single prompt (BL-074) |
| 2.2.0 | 2026-07-01 | Report UI: accessible heatmap labels, clickable breadcrumbs/KPIs, severity filters on Dashboard, check metadata in Cross-Model groups, show-all-checks toggle, model description + AI analysis panel |
| 2.1.0 | 2026-07-01 | Add `ts audit report` command: unified HTML report with Dashboard, Scorecard, Cross-Model, Object Map, Cleanup views. Delete superseded `efficiency_report.py`. |
| 1.0.0 | 2026-06-18 | Initial release — five audit angles: AI Readiness (A), Data Modeling (D), Human Readiness (H), Performance (P), Security (S) |
