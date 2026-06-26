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
| [references/modeling-best-practices.md](references/modeling-best-practices.md) | Authoritative audit framework: all 42 checks, thresholds, PII patterns, scoring conventions, TML field references, open items |
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

Store the profile. Thresholds are defined in
[references/modeling-best-practices.md](references/modeling-best-practices.md).

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

Run each selected angle's checks independently. Read
[references/modeling-best-practices.md](references/modeling-best-practices.md) — it is the
authoritative source for all check definitions, thresholds, TML fields, and scoring.

Each check produces findings with: `angle`, `check_id`, `severity`, `title`,
`detail`, `score` (0.0–1.0 fraction where applicable), and `recommendation`.

---

### 5-A. AI Readiness

**A1–A4** — per-model checks against the thresholds for the selected profile
(Spotter-ready or General). See reference file for exact fields and thresholds.

**A5** — Spotter readiness composite score per model. Weighted formula in the
reference file. Sort models by score ascending (worst first) to help prioritise
coaching.

---

### 5-D. Data Modeling

**D1. Model complexity** — count tables, joins, columns, formulas, join depth per
model. Score against GREEN/YELLOW/RED thresholds in the reference file.

**D2. Join key quality** — extract `joins[].on` column names, look up `data_type`
in associated table TMLs. Flag VARCHAR-to-VARCHAR and multi-column joins.

**D3. Join type analysis** — count `joins[].type` values across each model. Flag
FULL OUTER as HIGH. Flag LEFT/RIGHT OUTER as INFO (for review — may indicate
data discrepancies, but not always).

**D4. Progressive joins** — check `model.properties.join_progressive`. Flag as
HIGH if false on models with > 5 tables.

**D5. Orphan tables in model** — cross-reference `model_tables[].name` against
all `joins[].with` targets. Any unreferenced table is an orphan (Cartesian risk).

**D6. Grain consistency** — classify tables as likely-fact or likely-dimension
based on MEASURE/ATTRIBUTE ratio. Flag fact tables with > 40% attributes.

**D7. Model overlap & duplication** — compare `model_tables[].fqn` sets across all
models. **Not all overlap is bad** — conformed dimension reuse across focused domain
models is good design (e.g. Product shared by Sales and Purchasing). The anti-pattern
is two models with near-identical table sets, or mega-models that should be split.
Classify shared tables as dimension or fact (using D6 heuristic) to distinguish
healthy reuse from wasteful duplication. See D7 classification rules in the
reference file for severity mapping.

**D8. Duplicate tables** — group table TMLs by `(connection.name, db, schema,
db_table)`. Any group with 2+ entries = duplicate.

**D9. SQL pass-through function usage** — count `sql_*_aggregate_op` formulas
(`sql_int_aggregate_op`, `sql_string_aggregate_op`, `sql_bool_aggregate_op`).
Legitimate for timezone conversions; flag if > 20% of formulas use pass-through.

**D10. Zero-column tables** — tables in `model_tables[]` with no columns
referencing them via `columns[].column_id` (split on `::` to extract table name).
Two sub-categories:
- **Bridge table** (participates in joins) — INFO. May cause query generation
  issues if the optimizer cannot determine the join path without selected columns.
- **Leaf table** (no joins in either direction) — MEDIUM. No columns selected and
  no join purpose — why include it?

Note: bridge tables with zero columns but hidden columns are a legitimate pattern —
the hidden column exists to ensure query plan correctness without cluttering the UI.
See H3 exception (b).

**D11. Fan-out join risk** — joins that risk row multiplication: reversed direction
relative to table roles, fact-to-fact joins, ONE_TO_MANY cardinality, or
conversion/rate table naming patterns. Severity reduced if mitigated by a parameter,
model filter, or conditional formula.

**D12. Conformed dimension divergence** — same physical column (`db_column_name`)
classified differently across models (e.g. ATTRIBUTE in one, MEASURE in another).
Causes inconsistent aggregation and search behaviour for the same underlying data.

---

### 5-H. Human Readiness

**H1. Column name quality** — apply anti-pattern regexes from the reference file.

**H2. Description quality** — check too-short, too-long, boilerplate patterns.

**H3. Unnecessary hidden columns** — `is_hidden: true` columns not referenced by
any formula. Hidden columns cause locked visualizations. Unused columns should be
removed from the model, not hidden. Exceptions: (a) hidden formulas referenced by
other formulas (legitimate intermediaries); (b) hidden columns on zero-column bridge
tables needed for join-path correctness — the column ensures the query plan is
correct but is not needed in the UI (see D10).

**H4. Orphan models** — models with zero dependents across all buckets.

**H5. Orphan sets** — sets with zero consuming answers or liveboards.

**H6. Duplicate sets** — sets across models with equivalent filter definitions.

**H7. Direct table connections** — answers connected directly to Tables rather
than through a Model (bypasses the semantic layer).

**H8. Formula promotion candidates** — formulas duplicated in 2+ answers against
the same model but NOT in the model. Severity HIGH — link to
`/ts-object-answer-promote`.

**H9. Redundant answer formulas** — answer formulas duplicating a model formula.

**H10. Stale / temporary objects** — scan at two levels:
- **Object-level:** models, tables, answers, liveboards, and sets from the metadata
  inventory whose name or description matches stale patterns (`[DO NOT USE]`,
  `Copy of`, `zDEL`, `backup`, `deprecated`, etc.). Severity escalates to MEDIUM
  if the object is also an orphan (H4/H5).
- **Column-level:** columns within each model matching the same patterns (e.g. 56
  `zDEL`-prefixed columns in a single model).

Phase 1 (now): name and description regex — severity LOW (heuristic, false positives
expected). Phase 2 (with usage data): cross-reference with BI Server — zero queries
in 90 days plus a stale-name match is a strong HIGH removal candidate. See pattern
table in the reference file for full regex list and false-positive exclusions.

For H8/H9, normalise expressions before comparison: collapse whitespace, trim,
lowercase, remove trailing semicolons. Group by (normalised expression, data
source FQN).

---

### 5-P. Performance

**P1. SQL View detection** — objects with `subtype: SQL_VIEW`. Block filter pushdown.

**P2. Scalar formula density** — formulas without aggregation using scalar functions.
Score against thresholds in the reference file.

**P3. Model filter progressiveness** — filters lacking `apply_on_tables` run on every
query. With `apply_on_tables`, the filter only activates when those tables are searched.

**P4. Apply-all-joins anti-pattern** — `join_progressive: false`. Same data as D4,
framed as performance impact.

**P5. Date constraint coverage** — large fact tables without `constraints[]` risk full
table scans. Date constraints ensure a date filter is applied when certain tables are
in the search.

**P6. VARCHAR join keys** — same data as D2, framed as performance (2–5x slower).

**P7. Join depth** — same data as D1 join depth metric, framed as query plan degradation.

**P8. Column sprawl** — > 75 columns: wider GROUP BY, more complex query plans.

**P9. High-cardinality attribute indexing** — GUIDs, transaction IDs indexed as
ATTRIBUTEs. Wastes storage, pollutes Spotter suggestions. Note: ID columns stored
as numbers should be ATTRIBUTEs (not MEASUREs) — the issue is the indexing, not the
column type.

**P11. Secure suggestions overhead** — many indexed columns on a Spotter-enabled model.
Informational only — helps identify where selective de-indexing improves response time.

---

### 5-S. Security

**S1. PII column detection** — heuristic regex matching against column names. See PII
patterns table in the reference file. False positives expected.

**S2. PII indexing without RLS** — PII columns that are indexed expose values in Spotter
autocomplete. **The index can ONLY be secured if the backing table has RLS rules.**
Check Table TML for `table.rls_rules`. No table RLS + indexed PII = HIGH.

**S3. Column Level Security gaps** — PII columns without CLS or masking formulas.
CLS not in standard TML export (open item OI-10). Heuristic fallback: flag PII where
no masking formula exists (e.g. `if(is_group_member(...))` referencing the PII column).

**S4. RLS bypass + PII** — `is_bypass_rls: true` AND model contains PII columns = HIGH.

**S5. Credentials in analytics** — columns matching credential patterns. Severity
CRITICAL — should never be in an analytics model.

**S10. RLS bypass as exception** — `is_bypass_rls: true` disables Row-Level Security,
meaning all users see all rows regardless of RLS rules. Legitimate for aggregate-only
models but should be the exception.

---

### Phase 2 — Usage Analysis (future)

*Requires a `ts data search` CLI command to query the TS: BI Server system model.
Will add dead-column detection, unused-object identification, and low-usage flagging.
See open items OI-6 through OI-9 in the reference file.*

---

## Step 6 — Generate Report

Create a run directory:

```python
import pathlib, time
run_dir = pathlib.Path.home() / "Dev" / "audit-runs" / f"{profile_name}-{int(time.time())}"
run_dir.mkdir(parents=True, exist_ok=True)
```

### Output files

| File | Content |
|---|---|
| `audit_report.html` | Interactive HTML report — single self-contained file (all CSS/JS inline). Shareable via email, Slack, or browser. |
| `audit_findings.json` | Machine-readable JSON array of all findings — for downstream processing or custom reports |

### HTML report (`audit_report.html`)

Single self-contained HTML file — no external dependencies, opens in any browser.
All CSS and JavaScript embedded inline.

#### Report header

```
ThoughtSpot Environment Audit Report

Profile:    {profile_name}
Date:       {YYYY-MM-DD}
Profile:    {Spotter-ready | General}
Scope:      {All connections | list of connections}
Angles:     {A, D, H, P, S}
Models:     {count}    Findings: {count}    CRITICAL: {n}  HIGH: {n}
```

#### View 1 — Cluster heatmap (landing page)

Colour-coded grid: rows = models, columns = angles. Each cell shows worst severity
for that model × angle (GREEN / YELLOW / RED). Sorted by priority (most RED first).

- Click a cell → jump to that model's scorecard (View 2)
- Click an angle column header → jump to by-check detail (View 3)
- Severity filter bar at top — toggle CRITICAL / HIGH / MEDIUM / LOW / INFO visibility
- Search/filter box for model names

```
Model                    │  A   │  D   │  H   │  P   │  S   │ Findings
─────────────────────────┼──────┼──────┼──────┼──────┼──────┼──────────
GTM Pipeline             │ RED  │ RED  │ RED  │ RED  │ RED  │ 47
Customer 360             │ YEL  │ RED  │ YEL  │ YEL  │ YEL  │ 18
Sales Analytics          │ GRN  │ GRN  │ YEL  │ GRN  │ GRN  │  3
```

#### View 2 — Model scorecard (per-model drill-down)

All checks and scores for one model. Grouped by angle with expandable sections.

- CRITICAL / HIGH findings expanded by default
- MEDIUM / LOW / INFO collapsed by default — click to expand
- Each finding shows: check ID, title, score, severity, detail, recommendation
- "Back to cluster" link returns to View 1

```
GTM Pipeline  (79 tables, 1452 columns, 156 formulas)

▼ A — AI Readiness                                          RED
  A1  Description coverage    12%            RED
  A2  Synonym coverage         0%            RED
  A3  AI context              Missing        HIGH
  A5  Spotter readiness       8/100          NOT READY → /ts-object-model-coach

▼ D — Data Modeling                                          RED
  D1  Complexity              79 tables      RED   depth 9   RED
  D2  Join key quality        3 VARCHAR      HIGH
  D7  Model overlap           subset of...   INFO  (conformed dim reuse)
  D10 Zero-column tables      5 bridge       INFO
▸ P — Performance                                            RED
▸ S — Security                                               RED
```

#### View 3 — By-check detail (cross-model)

One section per check listing every finding across all models. Accessible by
clicking an angle column header in View 1, or via the sidebar navigation.

- Sortable columns (model, severity, score)
- Filter by model name
- Each row links to the model scorecard

```
D2 — Join Key Quality (14 findings across 5 models, HIGH)

Model              │ Join              │ Type    │ Issue
───────────────────┼───────────────────┼─────────┼────────────────
GTM Pipeline       │ ACCOUNT.ID        │ VARCHAR │ VARCHAR-to-VARCHAR
GTM Pipeline       │ OPP.ACCOUNT_ID    │ VARCHAR │ VARCHAR-to-VARCHAR
Customer 360       │ PERSON.EMAIL      │ VARCHAR │ VARCHAR-to-VARCHAR
```

#### Sidebar navigation

Always-visible sidebar with:
- Cluster heatmap (View 1)
- Severity summary counts
- Angle sections (click to View 3)
- Model list (click to View 2)

#### HTML generation approach

Generate the HTML by:
1. Building the `audit_findings.json` data structure first (same as below)
2. Embedding the JSON as a `<script>` data block in the HTML
3. Using vanilla JavaScript to render the three views — no framework dependencies
4. Inlining all CSS (colour coding, grid layout, collapsible sections)

The HTML file should be under 200KB for a typical cluster audit (20 models).
For large audits (100+ models), paginate the heatmap.

### Findings JSON format (`audit_findings.json`)

```json
[
  {
    "angle": "D",
    "check_id": "D7",
    "check_name": "DUPLICATE_MODEL",
    "severity": "HIGH",
    "score": 1.0,
    "title": "Duplicate models: Sales Model, Revenue Model",
    "detail": "Both models reference identical table set: DM_ORDERS, DM_CUSTOMERS, DM_PRODUCTS",
    "objects": [
      {"guid": "abc-123", "name": "Sales Model", "dependents": 15},
      {"guid": "def-456", "name": "Revenue Model", "dependents": 2}
    ],
    "recommendation": "Consolidate into Sales Model via /ts-dependency-manager (Repoint mode)",
    "profile": "Spotter-ready",
    "accepted": false
  }
]
```

---

## Step 7 — Review & Recommendations

Display the summary:

```
Audit complete. {N} findings across {L} angles.

  CRITICAL: {n} (immediate action)
  HIGH:     {n} (action recommended)
  MEDIUM:   {n} (review recommended)
  LOW:      {n} (informational)
  INFO:     {n}

Report saved to: {run_dir}/

Actionable findings link to existing skills:
  - "Consolidate models"     → /ts-dependency-manager (Repoint mode)
  - "Promote formulas"       → /ts-object-answer-promote
  - "Remove dead columns"    → /ts-dependency-manager (Remove mode)
  - "Coach model for Spotter"→ /ts-object-model-coach
  - "Fix PII/security"       → manual TML reimport or ThoughtSpot UI

Would you like to review the full report, or act on a specific finding?
(review / act / done)
```

If **review**: display `audit_report.md` contents.

If **act**: ask the user to pick a finding by number. Provide the specific
follow-up skill command with pre-filled context:

```
Finding #3: Promote "Profit Margin" formula to "Sales Model"

To act on this, run:
  /ts-object-answer-promote

When prompted, select model "Sales Model" and the answers listed in the finding.
```

If **done**: end the skill.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-18 | Initial release — five audit angles: AI Readiness (A), Data Modeling (D), Human Readiness (H), Performance (P), Security (S) |
