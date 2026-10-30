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
| **A** | AI Readiness | Description/synonym coverage, AI context; the report also scores each Model's Spotter readiness |
| **D** | Data Modeling | Complexity, join quality/types and keys, progressive joins, duplicates, SQL pass-through, zero-column tables |
| **H** | Human Readiness | Name quality, hidden columns, orphans, direct table connections, formula promotion candidates |
| **P** | Performance | SQL Views, row-level formulas, join keys, filter/join progressiveness, RLS functions, column sprawl |
| **S** | Security | PII detection, indexing without RLS, RLS bypass, RLS join loops, credentials in analytics |
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
  3.  Confirm scope (Models to audit) ...................... you confirm  (~10-60s)
  4.  Run the audit (fetch + analyse, snapshot saved) ...... auto
  5.  Generate audit report ............................... auto
  6.  Review findings and recommendations ................. you review

Confirmation required: Steps 0, 2, 3, 6
Auto-executed: Steps 1, 4, 5

### B. Available angles

<!-- BEGIN GENERATED: angles-overview -->
  A  AI Readiness ...... Description/synonym coverage, AI context; the report also scores each Model's Spotter readiness
  D  Data Modeling ..... Complexity, join quality/types and keys, progressive joins, duplicates, SQL pass-through, zero-column tables
  H  Human Readiness ... Name quality, hidden columns, orphans, direct table connections, formula promotion candidates
  P  Performance ....... SQL Views, row-level formulas, join keys, filter/join progressiveness, RLS functions, column sprawl
  S  Security .......... PII detection, indexing without RLS, RLS bypass, RLS join loops, credentials in analytics

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

Store the selected angles; Step 4 passes them as `--angles`.

### 2b. Assessment profile

<!-- BEGIN GENERATED: profiles -->
<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by `python -m ts_cli.audit.generate`; do not edit by hand. -->

```
Assessment profile — sets pass/fail thresholds:

  1. Spotter-ready      — aggressive, the bar for a Model Spotter will answer from (AI context required)
  2. General (default)  — lighter, the bar for Search and Liveboards (AI context recommended)

Enter 1 or 2:
```

Pass the choice to `ts audit run` as `--assessment spotter` (1) or `--assessment general` (2) in Step 4. What the profile changes:

- **A1 — Description coverage below threshold:** Spotter-ready: HIGH < 47.5%, MEDIUM < 95% · General: HIGH < 25%, MEDIUM < 50%
- **A2 — Synonym coverage below threshold:** Spotter-ready: HIGH < 40%, MEDIUM < 80% · General: HIGH < 12.5%, MEDIUM < 25%
- **A3 — No AI instructions configured:** Spotter-ready: HIGH · General: MEDIUM
- **A4 — Model has no description:** Spotter-ready: HIGH · General: MEDIUM
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

Display as a numbered list and let the user pick. Each chosen connection becomes one
`--connection "{name}"` flag in Steps 3 and 4 (display name; matched case-insensitively).

---

## Step 3 — Confirm Scope

`ts audit run` resolves the scope itself; this step only shows it and asks to proceed.
Do **not** search for Models, filter them or export TML by hand.

```bash
ts audit run --all-models [--connection "{name}" ...] --dry-run \
  --profile "{profile_name}"
```

It prints the inventory as JSON and fetches nothing else:

```json
{"models": [{"guid": "…", "name": "…"}], "model_count": 12,
 "legacy_worksheets_skipped": 3, "connections": ["Snowflake_Prod"],
 "tables_by_connection": {"Snowflake_Prod": 87}, "views_not_followed": 0}
```

How the scope is decided (`tools/ts-cli/ts_cli/audit/scope.py`):

- **Models only.** Legacy Worksheets are skipped and counted, never audited. Hidden and
  incomplete Models are not audited either (hidden Tables are still searched, since a
  hidden Table can feed a visible Model).
- **A connection scope goes through the Tables.** A Model's own search result rarely
  names a connection, so the audit finds the Tables on the chosen connections and the
  Models that use them, directly or through a View. A Model is in scope when **any** of
  its Tables is on a chosen connection, so a Model spanning connections is included.
- **A connection name that matches no Table is an error** (exit 1, naming it): usually a
  typo. Check the name against `ts connections list` and ask the user again.
- **An empty scope is an error** (exit 1, with the reason), never an empty report.
- `views_not_followed` above 0 means Views stacked deeper than the audit follows; Models
  built on them are not in scope. Tell the user.

Show the user the inventory and confirm:

```
Audit scope:

  Models:     12 (on: Snowflake_Prod; 87 Tables on that connection)
  Skipped:    3 legacy Worksheets

Proceed with the audit? [Y / N]
```

To audit specific Models instead, pass their GUIDs as `--models` in Step 4 and skip this
step.

---

## Step 4 — Run the Audit

Run the audit over the scope confirmed in Step 3 (the same `--all-models` /
`--connection` flags, without `--dry-run`). The scope is resolved again here; on a
cluster that is changing it can differ slightly from the confirmed inventory, and the
report lists the Models actually audited. Use a run folder of its own, with the time in
its name, so a second audit on the same day does not overwrite the first:

```bash
ts audit run \
  --all-models [--connection "{name}" ...] \
  --angles "{A,D,H,P,S}" \
  --assessment "{spotter|general}" \
  --profile "{profile_name}" \
  --snapshot-out ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/snapshot \
  --output ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/audit.json
```

`--snapshot-out` saves everything the audit fetched. A follow-up audit of the same scope
(other angles, or the other assessment profile) replays it with no API calls and no
`--profile`:

```bash
ts audit run --snapshot-in ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/snapshot \
  --angles "{…}" --assessment "{…}" \
  --output ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/audit-{variant}.json
```

A replay can only run rules whose data was captured, so capture with every angle the
user may want (the default, all angles, captures everything). Re-run without
`--snapshot-in` when the cluster has changed.

**What it fetches.** Each rule in the rule
catalog (`tools/ts-cli/ts_cli/audit/catalog/`) declares the data it reads, as `requires`
or `uses` (see [references/rule-authoring.md](references/rule-authoring.md)). The audit
fetches the union of what the selected rules declare, whichever category selected
them:

| Data | Fetched |
|---|---|
| Model TML with its associated Table TML, metadata headers, dependents | Every audit |
| AI instructions (`ai/instructions/get`, one call per Model) | When a selected rule declares `ai_instructions` (A3); the report's Spotter readiness score reads them too |
| Answer TML (the Answers among the Models' dependents) | When a selected rule declares `answers` (H7, H8, H9) |
| Sets and each Set's consumers | When a selected rule declares `sets` (H4, H5) |

So narrowing `--angles` also narrows the fetch. On the AI-instructions lookup, a final 401
(after re-authentication), a 429, or any `requests` exception raised by the request or
its re-authentication aborts the run once, because every later call would fail the same
way. Any other non-2xx (403, 404, a 5xx after the client's retries, …) or a non-JSON
2xx skips that Model's AI-instruction rules with a warning, and the report shows "Could
not be read".

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


The checks are **rules in a catalog**, not code: YAML under
`tools/ts-cli/ts_cli/audit/catalog/` (`categories.yaml`, `profiles.yaml`,
`rules/{ai,data,human,perf,security}.yaml`), run by a small deterministic rule engine
(`ts_cli/audit/engine/`). `--angles` selects categories, and a rule runs when any of its
categories is selected. Each rule declares the data it reads (`requires`/`uses`), and
the audit fetches exactly the union for the selected rules (see above). The rule's
thresholds, severities and wording, and the `--assessment` profile's overrides of them,
are in its catalog entry.

<!-- BEGIN GENERATED: rules-files -->
<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by `python -m ts_cli.audit.generate`; do not edit by hand. -->

| Catalog file | Category | Rules |
|---|---|---|
| `rules/ai.yaml` | A — AI Readiness | A1–A4, A6 (A5 retired) |
| `rules/data.yaml` | D — Data Modeling | D1, D3, D5, D7–D12 (D2, D4, D6 retired) |
| `rules/human.yaml` | H — Human Readiness | H1–H5, H7–H10 (H6 retired) |
| `rules/perf.yaml` | P — Performance | P1–P4, P6–P8, P11, P13–P18 (P5, P9–P10, P12 retired) |
| `rules/security.yaml` | S — Security | S1–S2, S4–S5, S10–S11 (S3, S6–S9 retired) |
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

## Step 5 — Generate Report

Generate the unified HTML report from the JSON output:

```bash
ts audit report ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/audit.json \
  --output ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/report.html
```

Or piped directly from Step 4 (no snapshot, so a follow-up audit fetches again):

```bash
ts audit run \
  --all-models [--connection "{name}" ...] \
  --angles "{A,D,H,P,S}" \
  --assessment "{spotter|general}" \
  --profile "{profile_name}" \
  | ts audit report -o ~/Dev/audit-runs/{profile_name}-{date}-{HHMM}/report.html
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

## Step 6 — Review & Act

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
| 3.7.0 | 2026-10-30 | **Grading into data (roadmap PR 2.4).** A new catalog key, `parameters`, holds a code rule's tuning numbers, profile-overridable and gated: H2's length limits and issues listed, H10's quote length. D1 grades by its catalog bands and H10 by a catalog severity map. P2 now counts a formula as row-level from its expression (no aggregate call, no reference to an aggregate formula) instead of the column's `aggregation:` key, which the model schema says never told the two apart: on the SE demo sample, 6 → 8 findings. H1 and the Spotter readiness score share one name test. The report no longer crashes on a null column name. P6's two severities stay in code, accepted. Design: `docs/superpowers/specs/2026-10-30-audit-grading-data.md`. |
| 3.6.0 | 2026-10-30 | **Noise fixes (roadmap PR 2.3), with BL-112.** D3 reports each full outer join HIGH as before, but rolls a Model's LEFT/RIGHT outer joins into one INFO listing them (was one INFO per join). H2 no longer flags a description opening "The " or "A ". A1 and A2 count visible columns only. D10, D11, H3, D5 and P7 find a model table by its alias as well as its name and resolve a join's target as the join graph does (an aliased table read as zero-column, unknown, unjoined or one hop deep), and H3 credits a formula referenced by id and a column referenced as `[TABLE::COL]`. S1's PII patterns match display names ("First Name", "Zip Code") and keep short tokens to whole words ("Hotel" is not a phone, "SSNLast4" still is a national id); S5 matches a spaced "API Key"; P18 ignores function names inside references and literals and says which kind of distinct count it found. The audit smoke test runs `ts audit run` and `report` (BL-112). On the 148-Model SE demo sample: findings 1,616 → 1,167 (General); D3 490 → 84, D10 62 → 17 (every MEDIUM was the alias bug), H2 79 → 22, H3 88 → 82, S1 51 → 89 and S2 23 → 50 (display names now read). Design: `docs/superpowers/specs/2026-10-30-audit-noise.md`. |
| 3.5.0 | 2026-10-30 | **The BL-406 contradictions resolved (roadmap PR 2.2), with BL-461 and BL-462.** A4 is retitled "Model has no description" (it never checked Spotter config). D7 reports a partial overlap (Jaccard above 0.5) only when a table both Models contain is a fact table in either, found by alias as well as name; identical Models stay HIGH. D11 words an INFO finding by the join's own cardinality (a MANY_TO_MANY join read "ONE_TO_MANY") and reads a referencing join's cardinality from its Table when the model gives none. H10 is MEDIUM for a stale-looking Model name on a Model nothing uses (H4's test), LOW otherwise. D9 matches every `sql_<type>_aggregate_op`, not only int, string and bool, and no longer a name that merely contains the spelling. P18 also reports columns surfacing `unique count`, `unique_count_if` or `group_unique_count` formulas, worded "Distinct count on …". D1, D5, H1, H2, S1, S2 and S5 were already right. On the 148-Model SE demo sample: D7 3 MEDIUM → 2, H10 21 LOW → 18 LOW + 3 MEDIUM, P18 0 → 56 INFO; every other finding unchanged. Design: `docs/superpowers/specs/2026-10-30-audit-contradictions.md`. |
| 3.4.0 | 2026-10-30 | **Rules retired, merged and reworded (roadmap PR 2.1, BL-406).** Retired: S3 (said "no CLS" but never read column security), P9 (search indexing is not query performance), S8 (a text RLS column is not a security gap), P5 (a date limit on fact tables is a design choice) and D6 (grain is keys and dates). Merged: D2 into P6 (string-typed join keys LOW, a multi-key join INFO; P6 now in Performance and Data Modeling), D4 into P4 (P4 in both categories), S9 into P14 (performance, not security). P2 reworded: row-level formulas the warehouse recomputes on every query, LOW above 5 and MEDIUM above 10 (was MEDIUM / HIGH). **A5 is no longer a finding:** the Spotter readiness score shows in each Model's header and as a heatmap column (Ready at 80, Needs work at 50); the report's corpus carries it as `models[].spotter_readiness` (`score`, `level`). On a 148-Model sample of the SE demo cluster, findings fall from 2,072 to 1,561 and HIGH findings from 531 to 148. Design: `docs/superpowers/specs/2026-10-29-audit-retire-merge-reword.md`. |
| 3.3.0 | 2026-10-28 | **`ts audit run` owns scope; the export step is gone (BL-407).** Step 3 runs `ts audit run --all-models [--connection …] --dry-run` and shows the inventory it prints, instead of the LLM searching for Models, telling them from legacy Worksheets and filtering them to connections by hand. A connection scope goes through the Tables (directly or through a View); a Model with any Table on a chosen connection is in scope. A connection name matching no Table stops the run, naming it. A Model the user may not export is now a warning in the report rather than a crash of the whole audit. The old Step 4 (a 1–5 minute TML export into a cache nothing read) is dropped, so the steps are now 0–6; the audit step always saves a snapshot (`--snapshot-out`) so a follow-up audit with other angles or the other assessment replays from disk. Design: `docs/superpowers/specs/2026-10-28-audit-run-scope.md`. |
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
