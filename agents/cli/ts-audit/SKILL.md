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

| Code | Angle | What it finds |
|---|---|---|
| **A** | AI Readiness | Description/synonym coverage, AI context, Spotter readiness score |
| **D** | Data Modeling | Complexity, join quality/types, progressive joins, duplicates, grain consistency, SQL pass-through, zero-column tables |
| **H** | Human Readiness | Name quality, hidden columns, orphans, direct table connections, formula promotion candidates |
| **P** | Performance | SQL Views, scalar formulas, filter/join progressiveness, date constraints, column sprawl |
| **S** | Security | PII detection, indexing without RLS, CLS gaps, RLS bypass, credentials in analytics |

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

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/check-catalog.md](references/check-catalog.md) | All audit checks: what they detect, severity logic, and how to add/modify/remove checks |
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

  A  AI Readiness ........ descriptions, synonyms, AI context, Spotter readiness score
  D  Data Modeling ....... complexity, joins, duplicates, grain, SQL pass-through, zero-column tables
  H  Human Readiness ..... names, hidden columns, orphans, formulas, direct connections
  P  Performance ......... SQL Views, scalar formulas, progressive joins/filters, sprawl
  S  Security ............ PII, indexing, RLS, CLS, credentials

  X  All angles (A, D, H, P, S)

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

Store the selected angles for Step 5 branching.

### 2b. Assessment profile

```
Assessment profile — sets pass/fail thresholds:

  1. Spotter-ready  — aggressive (descriptions >= 95%, synonyms >= 80%, AI context required)
  2. General        — lighter (descriptions >= 50%, synonyms >= 25%, AI context recommended)

Enter 1 or 2:
```

Store the profile. Thresholds are defined in each check function
(see [references/check-catalog.md](references/check-catalog.md)).

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

Run parallel metadata searches to build the object inventory. Only fetch object
types needed by the selected angles.

**Always needed (any angle):**

```bash
ts metadata search --subtype WORKSHEET --all --profile "{profile_name}"
```

Filter to actual Models (not legacy Worksheets) using `metadata_header.type` or
the presence of `worksheetVersion` in the response.

**For D angle — also enumerate tables:**

```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile "{profile_name}"
```

**For D or H angle — query dependents for each model:**

```bash
ts metadata dependents "{model_guid}" --profile "{profile_name}"
```

Store the full response in `corpus.dependents[model_guid]`. D angle uses
dependents to discover Sets (COHORT bucket — not searchable via
`ts metadata search`). H angle uses dependents for H4 (orphan model
detection) and H8 (formula promotion candidates).

**For H angle (formula checks) — also enumerate answers:**

```bash
ts metadata search --type ANSWER --all --profile "{profile_name}"
```

**If connection scope was set in Step 2c**, filter each result set to only include
objects whose `metadata_header.dataSourceName` matches a selected connection.

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

**For models when D, P, or S angles are selected**, also export associated tables
to get `db_column_properties.data_type` for join quality and `rls_rules` for
security checks:

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

Store all exported TML in memory for Step 5 analysis.

---

## Step 5 — Analysis Engine

Run the audit via the `ts` CLI:

```bash
ts audit run \
  --models "{guid1}" --models "{guid2}" \
  --angles "{A,D,H,P,S}" \
  --profile "{profile_name}" \
  --output ~/Dev/audit-runs/{profile_name}-{date}/audit.json
```

The engine runs each selected angle's checks as deterministic Python functions.
Check definitions, thresholds, and severity logic are implemented in:

| Module | Angle | Checks |
|---|---|---|
| `checks_ai.py` | AI Readiness | A1–A5 |
| `checks_data.py` | Data Modeling | D1–D12 |
| `checks_human.py` | Human Readiness | H1–H5, H7–H10 |
| `checks_perf.py` | Performance | P1–P9, P11, P13–P18 |
| `checks_security.py` | Security | S1–S5, S8–S10 |

See [references/check-catalog.md](references/check-catalog.md) for the full catalog
with severity logic per check, and instructions for adding, modifying, or
removing checks.

### Phase 2 — Usage Analysis (future)

*Requires a `ts data search` CLI command to query the TS: BI Server system model.
Will add dead-column detection, unused-object identification, and low-usage flagging.
See open items OI-6 through OI-9 in the reference file.*

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
| 2.4.0 | 2026-07-03 | Fix 3 audit bugs: (1) scorecard missing 77% of findings — child-object findings (columns, joins, formulas) now match by GUID, not lookup index; (2) false orphan models from pagination — `record_size: -1` in dependent payload; (3) false orphan models from associated export — dependent fetch now covers all model GUIDs from TML, not just input list. Batch size reduced 25→15 for reliability. |
| 2.3.2 | 2026-07-02 | Cluster heatmap: findings whose object is not a model (cross-answer/formula/table findings, or empty-guid) are no longer rolled up onto the first model in multi-model audits — this was inflating the first model's row (e.g. GTM Campaigns showing HIGH across angles it had no such findings for). Inherits the ERD fact/dimension classifier refinement |
| 2.3.1 | 2026-07-02 | ERD embed now shares one parser with the ts-object-model-erd skill (single source of definition); inherits the dimension/fact classifier fix so hidden RLS/parameter helper formulas no longer mislabel a dimension as a fact |
| 2.3.0 | 2026-07-02 | ERD: AI domain summary, multi-select filter chips, RLS red colour scheme, grouped controls bar, join-tree double-click, layered layout fixes |
| 2.2.0 | 2026-07-01 | Report UI: accessible heatmap labels, clickable breadcrumbs/KPIs, severity filters on Dashboard, check metadata in Cross-Model groups, show-all-checks toggle, model description + AI analysis panel |
| 2.1.0 | 2026-07-01 | Add `ts audit report` command: unified HTML report with Dashboard, Scorecard, Cross-Model, Object Map, Cleanup views. Delete superseded `efficiency_report.py`. |
| 1.0.0 | 2026-06-18 | Initial release — five audit angles: AI Readiness (A), Data Modeling (D), Human Readiness (H), Performance (P), Security (S) |
