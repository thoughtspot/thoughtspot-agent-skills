---
name: ts-audit
description: Scan a ThoughtSpot environment across five angles — AI Readiness, Data Modeling, Human Readiness, Performance, Security — and generate a prioritised audit report with actionable recommendations linking to existing skills.
metadata:
  category: "Platform & Governance"
  summary: "Scan an environment across five angles — AI Readiness, Data Modeling, Human Readiness, Performance, Security — with per-model scorecards and prioritised findings"
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
| **H** | Human Readiness | Name quality, hidden columns, orphans, Models nobody has queried, direct table connections, formula promotion candidates |
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
  H  Human Readiness ... Name quality, hidden columns, orphans, Models nobody has queried, direct table connections, formula promotion candidates
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
| Model TML with its associated Table TML, metadata headers (the Models', and every source's they use, SQL Views included), dependents | Every audit |
| AI instructions (`ai/instructions/get`, one call per Model) | When a selected rule declares `ai_instructions` (A3); the report's Spotter readiness score reads them too |
| Answer TML (the Answers among the Models' dependents) | When a selected rule declares `answers` (H7, H8, H9) |
| Sets and each Set's consumers | When a selected rule declares `sets` (H4, H5) |
| The custom calendars registered on the cluster's connections (`calendars/search`, paged) | When a selected rule declares `calendars` (P22; P19 also uses them, for a code-based calendar name that a custom calendar also has); the report's Data Cache view reads them too |
| Each connection's settings, reduced to its id, name, type and whether it uses OAuth, PrivateLink or a template variable (`connection/search` with details, paged; no configuration value is kept), and whether its metadata header says it is parameterized (a paged `metadata/search` of CONNECTION headers) | When a selected rule declares `connections` (P24; P23 also uses them, for each connection's type); the report's Data Cache view reads them too |
| Each Model's usage, from ThoughtSpot's system Model TS: AI and BI Stats (`searchdata`): its last query time over all the history kept, and its queries and distinct users over the last 180 days; the Org it was read in (`auth/session/user`); and which used Model IDs match no object the user can see now (a paged `metadata/search`). GUIDs and counts only | When a selected rule declares `usage` (H17); the report's scorecards, Dashboard, Cleanup and Usage views read it too |

So narrowing `--angles` also narrows the fetch. On the AI-instructions lookup, a final 401
(after re-authentication), a 429, or any `requests` exception raised by the request or
its re-authentication aborts the run once, because every later call would fail the same
way. Any other non-2xx (403, 404, a 5xx after the client's retries, …) or a non-JSON
2xx skips that Model's AI-instruction rules with a warning, and the report shows "Could
not be read". The calendar and connection searches are handled the same way, per page;
any other failure leaves the calendars or the connection settings unknown, with a
warning, and P22 or P24 then judges no Model. Separately, the dashboard's "Could not be read" box lists every Model whose
TML, or a Table it uses, holds the wrong shape where the audit reads one — a list or a
single value where a mapping belongs (`properties`, `spotter_config`,
`db_column_properties`, `model_instructions`, `rls_rules`, the document body itself), a
mapping or single value where a list of mappings belongs (`columns`, `formulas`,
`filters`, `model_tables`, their `joins`, `joins_with`, `rls_rules.rules`, an Answer's
`tables` and `formulas`), or a list entry that is not a mapping; an empty-looking value
(null, `0`, `""`) reads as empty — every such Table, and every Answer that holds one or is built on an
excluded Model or Table. None of them is judged
(the excluded Model's Sets and metadata header go with it, and cross-Model rules such as
D7, D8 and D12 do not see it, so a duplicate it is part of goes unreported) until the TML
is fixed; the run warns on stderr. Its formulas and Tables still count where a rule asks
whether something is on no Model (H7, H8, H9). A requested Model ThoughtSpot did not
export (deleted, no access, a refused batch) is listed in a "Not exported" box, in the
run's JSON (`corpus.not_exported`) and in the closing "Audit complete" line, which also
counts what could not be read.

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
| `rules/ai.yaml` | A — AI Readiness | A1–A4, A6–A9 (A5 retired) |
| `rules/data.yaml` | D — Data Modeling | D1, D3, D5, D7–D18 (D2, D4, D6 retired) |
| `rules/human.yaml` | H — Human Readiness | H1–H5, H7–H14, H16–H17 (H6 retired) |
| `rules/perf.yaml` | P — Performance | P1–P4, P6–P8, P11, P13–P28 (P5, P9–P10, P12 retired) |
| `rules/security.yaml` | S — Security | S1–S2, S4–S5, S10–S17 (S3, S6–S9 retired) |
<!-- END GENERATED: rules-files -->

See [references/check-catalog.md](references/check-catalog.md) for every rule — what it
detects, its severity per profile, its finding text and remediation (generated from the
catalog). To add, change or retire a rule, follow
[references/rule-authoring.md](references/rule-authoring.md); never add a Python check
function.

### Usage

When a selected rule declares `usage` (H17, in Human Readiness), the audit reads how much
each Model was queried from ThoughtSpot's own system Model, **TS: AI and BI Stats**,
found by its exact name. It reads, with `searchdata`:

- each Model's last query time, over all the history the system Model keeps;
- each Model's queries and distinct users over the last 180 days;
- the Org (id and name) each Model was queried in, with its last query there;
- where the history starts and ends.

What it keeps is GUIDs, counts and Org names and ids, plus the Org it was read in and
when. Its limits:

- **180-day counts.** Query and user counts cover the last 180 days; the last-used date
  covers all the history kept (on the SE demo cluster, from 2023-10-01). When the history covers fewer than 180
  days before the read, the report labels the counts with the history's own span ("since <date>") instead, and when it covers fewer
  days than H17's 90, H17's Cleanup section and Cross-Model group say it was partly
  judged (Models with no query in that history were not judged) rather than "No findings".
- **About a day's lag.** The history ends the day before it is read, so a Model created
  or first queried since then reads as never queried.
- **Whose usage.** Read from a non-primary Org, it is that Org's usage only, and the
  report says so. Read from the Primary Org it holds every Org's (live, 2026-11-25), and
  when it names more than one Org the header says "Usage of all Orgs (N in the usage
  history), read from the Primary Org". When the data names more Orgs than the session
  suggests, the header gives the count the data shows.
- **No names for Models not found.** The system Model keeps Model IDs, not names, so a used
  Model ID that matches no object the user can see in this Org now is listed by its ID,
  queries, users and last query date. The Cleanup view splits these by the Org each was
  queried in: **this Org's** (deleted, or not shared with the audit's user), **other
  Orgs'** (one collapsed group per Org; the audit does not judge whether they exist) and
  **Org not recorded**. A Model ID queried in several Orgs is listed under each, with its
  last query there; its counts are the Model's across every Org. When the Orgs cannot be
  read (a build that refuses `[Org ID]`/`[Org]`), the run warns and keeps one list,
  marked "Org not read".

The report's **Usage** view (Step 5) lists every audited Model with its status, dependents, owner and creation date, and exports a selection as the candidates file below; it adds no API call. Its dependents are those ThoughtSpot's dependents lookup returns to the audit's user in the Org the audit ran in. A Model whose dependents were not read in full (its Sets not fetched or its Set lookup failed, or dependents hidden from the audit's user, an answer that was not a list, or the Model missing from its batch's answer; the run warns for the last three) shows its visible count as a lower bound ("5+"): never counted as none. Active, it stays Active; idle with a dependent visible, it is "check first"; idle with none visible, it is undecidable and sits in the grey Not judged band, never among the retire candidates.

H17 (LOW) reports a Model with no query in 90 days or more (the catalog parameter
`idle_days`), or none in the history when that history starts at least 90 days before
the read (a shorter history judges no Model it does not hold, and a never-queried Model
created less than 90 days before the read does not qualify), saying whose usage it judged
by: all Orgs when read from the Primary Org and the data names more than one, else the Org
read (or that which Orgs it covers was not read). When the usage cannot be read (the system Model missing or refused, a call
failing, or a history with no first query), the run warns, naming the status and path; H17 judges no Model, and every place the report shows
usage says **Not read**: a failed read never reads as unused. A final 401, a 429 or a
`requests` exception aborts the run once, as for the other fetches. The live probe behind
this is [references/open-items.md](references/open-items.md) #9.

### Candidates file

The Usage view exports the Models a reviewer selects as `ts-audit-candidates.json`, the
input a later ts-dependency-manager and `ts share` list mode is to read (BL-645). Its
shape is fixed within a `format` version: a later release may add fields (a reader
ignores one it does not know), but renaming or removing one, or changing its meaning,
needs a new version.

```json
{
  "format": "ts-audit-candidates/1",
  "generated": "2026-11-26T09:15:00Z",
  "cluster": "https://{your-instance}.thoughtspot.cloud",
  "dependents_scope": "visible to the audit's user in this Org",
  "usage": {"scope": "usage of all Orgs, read from the Primary Org",
            "org": {"id": 0, "name": "Primary"}, "read_at": "2026-11-26T03:40:09Z",
            "idle_days": 90, "window_days": 180},
  "objects": [
    {"guid": "…", "name": "Sales (old)", "type": "MODEL", "status": "idle",
     "last_used": "2026-05-02", "days_since_last_use": 208, "queries_180d": 0,
     "users_180d": 0, "dependents_total": 0, "dependents_visible": 0,
     "dependents_complete": true, "liveboards": 0, "answers": 0, "sets": 0, "other": 0,
     "owner": "Ann Example", "created": "2024-03-11"}
  ]
}
```

The top level:

- `format` names the shape; `generated` is when the file was exported (UTC, to the
  second); `cluster` is the audited cluster's URL ("" when the run did not record one).
- `dependents_scope` says what the dependent counts cover: the dependents the audit's
  user can see in the Org the audit ran in, as ThoughtSpot's dependents lookup returns
  them to that user. The file makes no claim about any other dependents.
- `usage.scope` is the report's "whose usage" wording; `usage.org` is the Org the usage
  was read from (`id` and `name`, either null when not read); `usage.read_at` is when it
  was read; `usage.idle_days` is the idle days the statuses used (H17's); and
  `usage.window_days` is the span `queries_180d` and `users_180d` cover.

Each object:

- `status` is `active`, `idle`, `never`, `too_new` or `not_judged` (the Usage view's
  statuses); `type` is `MODEL`.
- `last_used` and `days_since_last_use` are null for a Model the history holds no query
  of; `owner` and `created` are null when the metadata header does not record them.
- `liveboards`, `answers`, `sets` and `other` (anything else that depends on the Model,
  such as a View or Spotter feedback) split its dependents, and `dependents_visible` is
  their sum (`sets` left out when null).
- `dependents_complete` is true when the dependents were read in full, and then
  `dependents_total` equals `liveboards + answers + sets + other`. It is false when they
  were not: the Model's Sets were not read (the run did not fetch them, or its Set lookup
  failed; `sets` is then null), or its own dependents reading was incomplete (dependents
  hidden from the audit's user and not returned, an answer that was not a list, or the
  Model missing from its batch's answer; the run warns, naming the Model). Then
  `dependents_total` is null and `dependents_visible` is a lower bound: such a Model is
  never counted as having no dependents. It is null when the run could not say (a
  snapshot written before ts-cli 0.225.0, which did not record the check; the total is
  then counted as read).
- Every count is what the audit saw when it read the usage, not now: re-read dependents
  before acting on the file.

The CSV export has the same per-object columns plus `usage_scope`, `dependents_scope`,
`cluster_url` and `audit_read_date` on every row; a null is an empty cell, and a boolean
reads `true` or `false`. Read its columns by header name, not position: from 3.28.0 on, a
new column is added at the end of the row. A cell
starting `=`, `+`, `-` or `@` is prefixed with a single quote, so a spreadsheet does not
run it as a formula.

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

The report is a single self-contained HTML file with eight views. Its size grows with the
estate: about 4MB for a 148-Model sample, measured before 3.19.0 added each formula's definition to the Formulas view, which added 7.5% on a synthetic estate of 20 Models with 40 short formulas each (25 to 70 characters); long expressions, a many-armed CASE say, cost more. Since 3.22.0 a report in which some Model has a formula built on another (since 3.25.0, any formula) also carries the graph's libraries, about 500KB (Cytoscape.js, dagre and cytoscape-dagre, `ts_cli/audit/vendor/`); a report with none does not.

| View | What it shows |
|---|---|
| **Dashboard** | Severity heatmap (models × angles), summary cards, stats. The heatmap has a Spotter readiness column (when the A angle ran) and a Data Cache column (when the Performance angle ran): each listed Model's Data Cache readiness as the Data Cache view labels it, with its reasons on hover, linking to that Model's Data Cache page (absent for JSON written before 3.23.0). When the run fetched usage (H17 ran), the header names whose usage the report shows (all Orgs, when it was read from the Primary Org and names more than one) and the date it was read, with a note when it is one non-primary Org's only, and the heatmap has a Last used column: days since each listed Model's last query, "No query" when the history holds none, its queries and users on hover, or "Not read" in every cell when the usage could not be read |
| **Model Scorecard** | Per-model findings grouped by angle, recommendations, downstream consumers, the Model's usage in its header when the run fetched it (Last used, and queries and distinct users over 180 days; "Not read" when the usage could not be read), and the Model's ERD drawn inline in a section that opens on demand (with a button to open it in a new tab). The ERD's filter bar is the report's: switching a table-kind chip (Fact, Dim, SQL View, Alias, RLS) off hides those tables and their joins and lays the diagram out again, and RLS subgraph and Noted only are Focus toggles beside it. Every page about one Model starts with the same tabs: **Scorecard** (`#model/<guid>`), **ERD** (`#model/<guid>/erd`, the scorecard with its ERD open and scrolled to), **Formulas** (`#formulas/<guid>`; disabled, with the reason, on a Model with no formula tree) and **Data Cache** (`#datacache/<guid>`; only when the report carries Data Cache readiness). The breadcrumb reads Audit / Model / page on each, the Model linking to its scorecard. A heatmap cell's route, `#model/<guid>/<category>`, still opens the scorecard at that category |
| **Cross-Model** | Sortable/filterable table of all findings across models |
| **Object Map** | Table reuse (Sankey), model overlaps, dependencies (bar charts) |
| **Cleanup** | Orphan models, stale objects, and Models not queried in 90 days or more, or never (H17; its section reads "Not read" when the usage could not be read, and says it was not collected when no selected rule fetched it, never "No findings"), with checkbox selection + clipboard copy. When the run fetched usage, the used Model IDs that match no Model, Table or View the user can see now, with their queries and users over 180 days and last query date, by ID only, since the system Model keeps no names, split by the Org each was queried in: "Used in this Org, but not found" (deleted, or not shared with the audit's user), "Used in other Orgs" (one collapsed group per Org, opened to its IDs; no claim they are deleted) and "Org not recorded". One list marked "Org not read" when the Orgs could not be read; "Not read" when the usage, or the objects the user can see, could not be read |
| **Usage** | Shown, with a sidebar link, only when the run fetched usage; it reads **Not read** when the usage could not be read, never an empty table. One row per audited Model with its status: **Active** (queried within H17's idle days, 90), **Idle** (no query in 90 days or more), **Never queried** (none in a history that covers 90 days), **Too new** (never queried, created less than 90 days before the read: H17 skips it) or **Not judged** (a history too short to say, or no query time recorded); the statuses come from H17's own reading, so the view and H17 agree. A quadrant plots each Model by days since its last query (log scale; never-queried, and too-new or not-judged Models, in bands of their own at the right) against its dependents, with a line at 90 days and the quadrants named "Idle, no dependents — retire candidates", "Idle, has dependents — check first" and "Active"; hovering a dot names the Model, its last use, queries and dependents, and clicking it selects its row. The table below is the source of truth: checkbox, Model (linking to its scorecard), Status, Last used, Queries and Users over the window, Dependents (those the audit's user can see in this Org; Liveboards, Answers, Sets and other on hover; a Set counts, since removing the Model removes it; a lower bound such as "5+ (Sets not read)" when they were not read in full, drawn as a hollow dot at its visible count; such a Model is out of the "No dependents" filter, and an idle one with none visible sits in the grey Not judged band), Owner (the metadata header's author), Created and the worst finding's severity, each column sortable; by default retire candidates come first, the most idle first. The shared filter bar's status chips and a "No dependents" chip narrow the table and the chart together. Select all shown, Clear, and **Export CSV** / **Export JSON** write the selected Models, in the browser, as the candidates file (see "Candidates file") |
| **Formulas** | Each Model's formula dependency tree: every tree starts at a formula nothing else uses (or where a circular chain is entered) and opens down to the table columns and parameters, marking each formula MEASURE or ATTRIBUTE, a hidden helper (hidden, and used by other formulas), used once and hidden (a formula H16 reported: a candidate to paste into the one formula that uses it; a report built without H16 tags none) or hidden and unused (a cleanup candidate), and how many formulas use it. An open formula shows its definition beneath it. Clicking a formula, column or parameter opens a panel beside the tree (on a narrow screen, a sheet at the foot of the page) with its definition (every reference a link, a formula named as the tree names it, by its column's name; when that differs from the TML, the definition as the TML writes it follows, to copy) and, when it uses a formula H16 reported, the definition again with each such helper pasted in, in parentheses, all the way down; what it uses, what uses it and everything that depends on it; following a link opens the tree down to that formula. A search box finds columns and parameters by name, then formulas by name, then formulas by definition, showing the first 50 and counting the rest. The tree is one tab stop: the arrow keys move through it, and Escape closes the definition. Roots open one level; Expand all opens about 2,000 more rows per press. A Graph button, on every Model with formulas (since 3.25.0; before, only on one with a formula built on another), draws the same lineage left to right (columns and parameters, then the formulas built on them); clicking a node opens the same panel and lights everything upstream and downstream of it, a link in the panel moves the graph, and the selection carries between the tree and the graph (and is kept when you come back to the Formulas view). A Model of more than 300 formulas, columns and parameters is drawn one lineage at a time. The tree stays the keyboard-reachable form. The filter bar shared with the Data Cache view and the ERD (Show, All, a toggle chip per kind with its count, the search box, the shown count) has type chips (Columns, Parameters, Measure formulas, Attribute formulas; a formula no column surfaces has no stated kind and counts as an attribute) that filter both modes for the session: the graph hides a switched-off type's nodes and edges and lays the rest out again, each connected part on its own, a rank too tall for the canvas (many measures over one amount column) wrapped into several columns, and the parts (lone nodes last) packed in rows about the canvas's shape, and the 300-node cap counts only what is shown; the graph always opens with every drawn node in view, at whatever zoom that takes (the layout keeps common shapes legible: 40 or 80 formulas on one column, or 150 on five, open at 0.35 or more at 1280×720; a very long chain opens smaller); past the cap it opens on the lineage of a root of a type switched on; the tree hides those rows, keeping a switched-off formula, faded, only as the way to a formula of a shown type under it (a shown column or parameter does not keep it, so switching Measure formulas off hides the measures); search leaves them out and counts them. The shown count counts what the mode shows: the graph, the nodes drawn (past the cap, only the lineage drawn); the tree reaches a column or parameter only through a formula, so with both formula types off it is empty, counts 0 and says why. A link to something switched off still opens its definition, with a note and a button to show its type; a column whose formulas are all switched off gets a note naming them and a button to show them. A legend gives each type one mark, a shape in its colour, used in the tree's rows and the graph's nodes. Reached from the sidebar (a Model picker) or a Model's Formulas tab |
| **Data Cache** | Which audited Models ThoughtSpot's Data Cache can serve, one row per Model. Its readiness is Can use, Can't use, To confirm, Warning or Not assessed. To confirm means its only reasons are readings the product team is to review, and every check read the whole Model. Not assessed means a check that decides it did not run or could not read part of the Model: what the audit could not read never reads Can use. The reasons that block are a custom calendar (P19), a SQL pass-through formula (P20), a semantic query Model (P21), a source other than Snowflake or Databricks (P23), a connection using OAuth, PrivateLink or a template variable (P24), a parameterized Table (P25), a parameter in a formula (P26), a SQL View (P27) and an RLS rule beyond its Table's own columns (P28). A connection that defines custom calendars (P22) is a warning. The row also lists the checks it could not make and the calendars its columns use, code-based or custom, with the custom calendars registered on its connections. A source whose TML was not read is named there (Not read), since its Table columns may set a calendar the audit did not see. The shared filter bar narrows the list: a toggle chip per readiness (Can use, Can't use, To confirm, Warning, Not assessed) with its count, multi-select, all on at first, switching one off hiding its Models and All switching every chip back on, and a search box over names, reasons and calendars. Each Model links to its scorecard. `#datacache/<guid>` shows one Model's row under its tabs, without the filters, with a link back to every Model. The readiness is read off the same fields those rules judge by, so the view and the findings agree. A report from JSON written before 3.23.0 shows every Model as Not assessed |

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
| 3.28.0 | 2026-11-26 | **A Usage view.** A new report view, `#usage` (a sidebar link beside Cleanup, only when the run fetched usage; "Not read" when it could not read it, never an empty table): a quadrant of every audited Model by days since its last query and its dependents, with a line at H17's 90 idle days and the quadrants named, a sortable triage table (status, last used, queries, users, dependents by type, owner, created, worst finding) with status and "No dependents" filters, and an export of the selected Models as CSV or as the `ts-audit-candidates/1` JSON file ("Candidates file"), built in the browser; the dependent counts are those the audit's user can see in this Org, and a Model whose dependents were not read in full (Sets not read, or its own reading incomplete: dependents hidden, an answer that was not a list, or the Model missing from it) has a null total, its visible count as a lower bound (`dependents_visible`, `dependents_complete`), never 0. The run records such Models (`sets_incomplete`, `dependents_incomplete`); a snapshot from before reads failed Set lookups from its warnings and cannot say which dependents were hidden. H4 is unchanged. Each Model's status is Active, Idle, Never queried, Too new (never queried, created less than 90 days before the read, the 3.27.1 rule) or Not judged, read through H17's own logic. The audit JSON's `corpus.models[].usage` gains `status`, `dependents` (`total`, `visible`, `complete`, `not_read`, `liveboards`, `answers`, `sets`, `other`), `owner` (the metadata header's author display name, else author name) and `created`, and `corpus.usage` gains `status_idle_days` and `dependents_checked`, all from data the audit already fetches. Absorbs BL-625 (Dashboard usage sort and filters). On the SE demo cluster's 150-Model sample: 117 Active, 12 Idle, 13 Never queried, 8 Too new; 14 retire candidates and 11 idle with dependents. |
| 3.27.1 | 2026-11-26 | **H17 skips young never-queried Models.** A Model never queried and created less than `idle_days` (90) days before the usage was read, by its metadata header's creation time, is no longer reported as "not queried in 90 days or more"; one with no creation time recorded is judged as before. On the SE demo cluster's 150-Model sample this removed 8 of 33 H17 findings, Models 8 to 49 days old. |
| 3.27.0 | 2026-11-25 | **Usage by Org.** The usage read gains the Org each used Model was queried in (`[Org ID]` and `[Org]`, from a query of their own: a build that refuses them, or answers without them, leaves the rest of the usage readable, with a warning, and the Cleanup list reads "Org not read"). Read from the Primary Org, the usage holds every Org's (live, 2026-11-25), so when it names more than one Org the Dashboard header says "Usage of all Orgs (N in the usage history), read from the Primary Org on DATE"; read from another Org and naming more than one, it gives the count the data shows and drops the "that Org's only" note. The Cleanup view's "Used, but not found in this Org" list is split into this Org's IDs (deleted, or not shared with the audit's user), "Used in other Orgs" (one collapsed group per Org with its IDs, queries, users and last query there; no claim they are deleted) and "Org not recorded". A Model ID queried in several Orgs (7 of 3,015 on the SE demo cluster) is listed under each, its counts the Model's across all of them, never summed per Org. The audit JSON's `corpus.usage` gains `org_read`, `orgs` and each not-found ID's `orgs`. A snapshot or JSON from 3.26.0 has no Orgs: it replays and renders, every not-found ID under "Org not recorded". H17's message, the Last used tooltips and the scorecard titles use the same "whose usage" wording as the header; H17's description and remediation say what the usage counts by where it was read. Open-items #9 records the probe. |
| 3.26.0 | 2026-11-25 | **Usage per Model, and H17.** A new conditional data kind, `usage`, fetched only when a selected rule declares it: from the system Model TS: AI and BI Stats, found by its exact name, `searchdata` reads each Model's last query time over all the history kept and its queries and distinct users over the last 180 days (the filter `[TS Query Start Time].'last 180 days'`), every value by its column name, since `searchdata` answers columns in an order of its own. The audit keeps GUIDs and counts, the Org it was read in (`auth/session/user`) and when; a row with no Model ID is dropped and counted. H17 (Human Readiness, LOW, evidence fact; product owner, 2026-11-25): a Model with no query in 90 days or more (the catalog parameter `idle_days`), or none in a history that starts at least 90 days before the read, naming the days since its last query, or where the history starts, and the Org whose usage was read. When the usage cannot be read (the system Model missing or refused, a call failing, or a history with no first query), the run warns with the status and path only, H17 judges no Model, and the report says "Not read" wherever usage would show, H17's Cleanup section and its Cross-Model group included, never "unused" or "No findings"; a final 401, a 429 or a `requests` exception aborts the run once. The report: each scorecard's header shows Last used and the 180-day queries and users; the Dashboard header names the Org and the date the usage was read, with a note when the run was outside the Primary Org, and the heatmap gains a Last used column; the Cleanup view lists H17's Models and a "Used, but not found in this Org" list of the used Model IDs that match no object the user can see now (a paged `metadata/search`), by ID, queries and last query date, since the system Model keeps no names. Limits: the counts cover 180 days; the history lags about a day, so a Model created or first queried since then reads as never queried; the usage is that Org's only. A snapshot written before this release holds no usage, so replaying H from it is refused: capture it again. Live-probed read-only on the SE demo cluster, 2026-11-25; the REST spec was not consulted (open-items #9). |
| 3.25.0 | 2026-11-19 | **One set of tabs on every page about a Model; one filter bar across the Formulas, Data Cache and ERD views.** The scorecard, its ERD, the Formulas view (tree and graph) and the Data Cache view filtered to one Model now share a tab bar (Scorecard, ERD, Formulas, Data Cache) with the current page marked, and one breadcrumb, Audit / Model / page. New routes: `#model/<guid>/erd` opens the scorecard with the Model's ERD drawn inline and scrolled to (the ERD Diagram button opened it in a new tab; the section keeps a button for that), and `#datacache/<guid>` shows one Model's Data Cache row with a link back to all; every older route still works. The Formulas tab is disabled, with the reason, on a Model with no formula tree; the Data Cache tab appears only when the report carries Data Cache readiness. The tabs replace the scorecard's ERD Diagram and Formula tree buttons and the Formulas view's Model scorecard button. The Dashboard heatmap's Data Cache cell links to that Model's Data Cache page. The Formulas view gains type chips (Columns, Parameters, Measure formulas, Attribute formulas, a formula of no stated kind counted as an attribute) shared by the tree and the graph for the session: the graph hides a switched-off type's nodes and edges and lays the rest out again, with the 300-node cap counting only what is shown; the tree hides those rows, keeping a switched-off formula, faded, only as the way to a formula of a shown type under it (a shown column or parameter does not keep it, so switching Measure formulas off hides the measures); search leaves them out and counts them. A link to something switched off still opens its definition, with a note and a button to show its type. A legend gives each type one mark, a shape filled and outlined in its colour, in the tree's rows and the graph's nodes, keeping the dashed (hidden) and amber (H16) borders (product owner, 2026-11-19). In the graph, dagre lays out each connected part on its own, a rank too tall for the canvas is wrapped into several columns, and the parts are packed in rows about the canvas's shape, lone nodes last, instead of dagre stacking every unconnected part, and every node of a rank, in one tall column mostly off screen (on the SE demo sample's Retail Sales Model with Columns off, 34 nodes: 11 off screen before, none after; 80 formulas on one column: 43 of 81 before). The graph now opens with every drawn node in view at whatever zoom that takes (it stopped at 0.7): 40 or 80 formulas on one column and 150 on five open at 0.35 or more at 1280×720 and 1400×900, and only a very long chain opens smaller. Past the cap it opens on a root of a type switched on. Each shown count counts what the mode shows: in the tree, the items the chips leave shown under a shown formula row (treeShownCount); the graph's nodes (past the cap, the lineage drawn, where it counted every node of a type switched on), the Data Cache list's rows and the ERD's tables (a join-tree or compare focus included). An empty tree says why. One filter bar now serves the Formulas view, the Data Cache view and the ERD (product owner, 2026-11-19): Show, an All chip, a toggle chip per kind with its count (multi-select, all on at first; switching one off hides what it covers; All switches every chip back on; a chip covering nothing is disabled), then the search box and the shown count. The Data Cache view's single-select readiness pills become those chips. The ERD runs in its own page, so it keeps the same spec rather than the same script: identical markup, classes and behaviour, and CSS byte-identical between markers, which a test checks; its chips now hide tables and their joins and lay the diagram out again instead of fading them, and RLS subgraph and Notes become Focus toggles (ts-object-model-erd 1.11.0). The tabs show only for a Model the report lists, on every page about it (a Model with no formulas kept none on its Formulas page), and the Data Cache tab only when the Performance angle ran, as the Dashboard's column. The inline ERD escapes every `<` and `>` in its data, so a name holding script markup no longer blanks it; its Share HTML works (the data script lacked the id it reads); and its tab reopens a closed ERD on its own route. **P24:** a client ID or secret key set alone (the other blank or absent), on any warehouse, now reads as OAuth to confirm, as the pair does: it read as no OAuth, so its Model could read Can use, while an open question never reads Can use (product owner, 2026-11-19; open-items #18 point 1). A client key is any set key whose name, ignoring case and punctuation, contains `clientid` or `clientsecret` (`clientId`, `Client Secret`, `client.id`, `clientSecretKey`, `clientIdentifier`), which read as no OAuth before, the same Can use; the match errs toward To confirm. A key names OAuth only with a word starting `oauth` (`oauth_pvt_key`, `OAuth2Secret`, `azureOAuthKey`; not `no_auth`, `noAuth` or `sso_auth`), and one other than the Databricks pair stays firm OAuth. A host or account name key is matched ignoring case and punctuation too, so `account_name` holding `privatelink` now reads PrivateLink to confirm where it read nothing. The finding names such a reading "OAuth client credentials (to confirm)" (it said "OAuth client ID and secret", untrue for one key), and P24's description and the README name every reading to confirm. The derived connection facts change, so `FACTS_VERSION` is 3 and a snapshot recording 2 is refused for the P angle: capture it again. Those are the only finding changes. Every Model with formulas now gets the Graph button, and the report carries the graph's libraries whenever any Model has a formula: on the 150-Model sample of the SE demo cluster, only 6 of the 31 Models with formulas had a formula built on another, so 25 had no graph (product owner, 2026-11-19). |
| 3.24.0 | 2026-11-19 | **A Data Cache column on the Dashboard; P24: Databricks OAuth from a client ID and secret reads To confirm; P23 names Analyst Studio.** The Dashboard heatmap gains a Data Cache column beside Spotter readiness: each listed Model's readiness (Can use, Can't use, To confirm, Warning, Not assessed), as the Data Cache view labels it, with its reasons on hover and a link to that view (product owner, 2026-11-19). The heatmap lists the Models with findings, as before. The column shows only when the Performance angle ran, as Spotter readiness shows only when AI Readiness ran, and not for JSON written before 3.23.0, which carries no readiness. The Formulas view's definition panel names a formula reference as the tree does, by the name of the column that shows it: `[formula_Date]` reads `[Transaction Date]`, as ThoughtSpot's formula editor shows it, with the expression as the TML writes it beneath, to copy, when the two differ (product owner, 2026-11-19). On the SE demo cluster, 12 of the 14 Databricks connections use OAuth, and every one holds `OAuth2ClientId` and `OAuth2Secret` and no other setting naming OAuth; per-user OAuth and a service principal (M2M) both hold that pair, so the names cannot tell which. P24 read it as firm OAuth, so every such Model read Can't use, while its M2M reading looked only for `client_id` and `client_secret`, which no connection there holds. On a Databricks connection that pair alone now reads "OAuth client ID and secret (to confirm)", as `client_id` with `client_secret` does on any connection, and a Model blocked only by it reads To confirm, or Not assessed when another check could not read it (product owner, 2026-11-19; open-items #18 point 1). The same pair on another warehouse stays firm OAuth. P23 names an `RDBMS_MODE` source "Analyst Studio"; Data Cache does not serve one, so it still blocks (product owner, 2026-11-19). Open-items #17's note that called the `OAuth2ClientId` pair Snowflake OAuth and `client_id` with `client_secret` the Databricks form is corrected. On the 150-Model sample of the SE demo cluster run that day, all 7 Models P24 blocked rested on that pair. A snapshot keeps the derived connection facts, not the settings, so it now records the version of that derivation; one recording an older version, or none (every snapshot written before this release, which holds the old reading), has its connection facts counted as not captured, and replaying the P angle from it, or `ts audit fire-rates` on it, is refused with a note saying why (capture it again). The Formulas search finds a definition by the panel's form too. The pasted-in definition (H16) is also shown as the TML writes it, to copy. P23 and P24 compare warehouse types through one normalisation, so a Databricks type with an `RDBMS_` prefix reads as Databricks for P24 as it did for P23. |
| 3.23.0 | 2026-11-18 | **Data Cache readiness: P19 to P28, and a Data Cache view.** ThoughtSpot's Data Cache cannot serve some Models. Ten Performance rules say which, per the product owner's rules (2026-11-18); all are evidence fact except P24. P19, MEDIUM: a column on a table-based custom calendar. A column's calendar is its own `properties.calendar`, else its Table column's; `calendar`, `fiscal` and `default`, any case, are code-based. A formula that passes a custom calendar to a date function, and a code-based value that a custom calendar on the connection is also named, are readings to confirm. P20, MEDIUM: a formula that calls a SQL pass-through function, scalar or aggregate, outside quoted literals and references. P21, MEDIUM: a semantic query Model, with a measure aggregated AGGREGATE (on the Model column or its Table column) or a Table column flagged `is_pre_aggregated_measure: true`; the flag alone is a reading to confirm. It is uncached by design, so the advice is no change. P22, LOW: a connection of the Model's Tables defines custom calendars, so a query that picks one at run time is not cached. P23, MEDIUM: a source on neither Snowflake nor Databricks (its connection's type from the connection search, else its metadata header's `dataSourceType`), or a Table with no connection; a source with neither type leaves P23 not assessed for the Model. P24, MEDIUM, evidence heuristic: a connection using OAuth, PrivateLink or a template variable, read from its setting names and host, since the connection search declares no auth type. A connection missing from the search, or whose settings cannot be read, leaves P24 not assessed for the Model. A parameterized connection is read from its metadata header, since the search shows its settings without their tokens. P25, MEDIUM: a Table whose database, schema or table name is a template variable. P26, MEDIUM: a formula that reads a Model parameter (A9's reading). P27, MEDIUM: a SQL View among the Model's sources. P28, MEDIUM: an RLS rule reaching another table's column or a join, calling a formula function (any call but `ts_var`) or a SQL pass-through. It names a null test (`isnull`, `is_null`) apart, as the trade-off S12 advises, and skips a Model that bypasses RLS. Two new conditional data kinds are fetched only when a selected rule declares them: `calendars` (P22: every connection's registered calendars, one paged search) and `connections` (P24: one paged `connection/search` with details, each connection reduced in the fetch to its id, name, type and four flags from its settings, plus a fifth, whether it is parameterized, from a paged search of CONNECTION headers; no configuration value is kept, logged or reported). A failed search is a warning; P22 or P24 then leaves each Model it could not judge Not assessed. So does any rule that could not read a source: a Table whose export failed, a SQL View, a `model_tables` entry with no fqn, or a connection nothing names. The audit now fetches the metadata header of every Model source, since it keeps no SQL View TML: P27 reads it, and P1, which already read SQL View headers, now sees the SQL Views a Model uses, so it may report more. D8 no longer counts SQL Views, which have no physical table: two SQL Views sharing a name are not duplicates. A header request refused as a bad request is retried one object at a time, and an object still refused is skipped with a warning, so one unreadable source does not end the audit. A source Table whose TML could not be exported leaves P19, P21, P25 and P28 not assessed for the Model. Each Model in the audit JSON gains `data_cache`: its readiness (ready; blocked; confirm when its only reasons are readings to confirm; warning; or unknown when any check, P22's warning included, did not run or could not judge it), the reasons, the calendars its columns use and the custom calendars on its connections. The same rules decide it, so it agrees with the findings. A new Data Cache view lists every Model with filter pills and a search. A snapshot captured before this release holds neither calendars nor connection settings, so replaying the P angle from it is refused: capture it again. `ts calendar search` now lists every calendar; it listed only the first 10 (open-items #16, #17). On the 20 most formula-heavy Models of the SE demo cluster (19 exported), with all ten rules as this release ships them (re-measured 2026-11-19): 5 can use Data Cache, 11 can't, 1 is warned, and 2 are not assessed (each has a View among its sources, which names no connection, so P23 cannot read a warehouse type; open-items #18). P26 (a parameter in a formula) fired on 9 Models, P20 (SQL pass-through) on 3, P22 on 1; P19, P21, P23, P24, P25, P27 and P28 found none (one calendar in use, code-based; every source P23 could read on Snowflake; no OAuth or PrivateLink reading, SQL View or RLS rule beyond its own columns). D8 and P1 counts unchanged by the wider metadata fetch on this sample. Flagged for the product team to review (open-items #18): OAuth read from a Databricks client_id/client_secret pair, and PrivateLink read from the host. Each finding says "to confirm". So do P21 for a measure only flagged pre-aggregated, P28 for an RLS rule's `= null` test, and P19 for a calendar named in a formula or a code-based name a custom calendar also has. A P19, P21, P24 or P28 finding resting only on such readings says the Model may not be able to use Data Cache, and the Model reads To confirm, not Can't use, unless a check could not read part of it: Not assessed outranks To confirm. Also flagged: the meeting of S12 and P28, a null test that keeps an outer join's rows but stops Data Cache, which both remediations describe. Whether S12's `= null` form stops Data Cache is open too, so P28 lists it marked to confirm. |
| 3.22.0 | 2026-11-18 | **A graph of each Model's formula lineage in the Formulas view.** A Graph button beside the tree draws the Model's formulas, columns and parameters left to right with Cytoscape.js and dagre; clicking a node opens the same definition panel and lights its upstream and downstream, a link in the panel moves the graph, and the selection carries between the tree and the graph. Past 300 nodes the graph shows one lineage at a time (the selected node, what it uses and what depends on it), starting at the root whose lineage is the largest that fits under the cap (else the smallest). The libraries (about 500KB in the report; MIT, with graphlib's BSD-3-Clause notice inside dagre; pinned by SHA-256 in `vendor/MANIFEST`) are embedded only in a report where some Model has a formula built on another, and run when a graph is first opened; no report loads anything from the network. No finding changes. |
| 3.21.1 | 2026-11-16 | **S17 fixes from the review of its last commit.** Evidence `heuristic`, with an approved `severity_exception` keeping it HIGH. The message says query generation *can* plan the table as a second fact. A table with no column in the Model now gets the check-the-query-plan advice even when it has a rule of its own, which may not apply without a Model column (not measured); before, that rule chose the reverse-the-join or review advice, and the remediation now says the same. The decision that a rule path reaches every table it passes through is recorded in the description and pinned by a two-hop test. The report's tag for a heuristic finding reads "inferred" (it was "name match"), since S14, S15 and S17 match no name. A test pins the formula-measure guard with a hidden formula measure, direct and chained. Each formula expression is parsed once, so a long formula chain no longer slows the S angle. |
| 3.21.0 | 2026-11-16 | **H16, hidden formula used by only one formula, LOW.** A hidden formula (no visible column shows it) that exactly one other formula uses, once, adds a level a reader must open to follow that formula, and nothing else reuses it. One finding per helper, naming the formula that uses it and the formula it ends up in once every such helper is pasted in, all the way down, with that result's length. Skipped when a Model filter, a column's currency setting, a Model-level join or a date-range constraint names its column; when the two form a cycle; when the Model has two formulas of one name; when no visible formula sits above its user (remove the chain instead); when a column shows it with an aggregation other than SUM, or it is a bare window or group call, brackets around it included (its column aggregation does real work there); when the Model spells a formula ambiguously: a formula with no name, two formulas or a formula and a physical column or parameter sharing an id, a name or a column name (case and edge spaces aside), or a reference read as a column matching one (BL-578); when the paste is not one of the plain cases (an aggregating helper only where no aggregate, group, window or rank call encloses it; a row-level helper only where nothing but plain aggregates such as sum or average does, and inside one when the formula using it aggregates; anything else is left alone, fail safe); or when the result would make more than 3 if() calls (P16's line) or pass 250 characters, in which case none of that formula's helpers is reported (the limit counts them together, per the product owner, 2026-11-14). LOW, not INFO, per the product owner (2026-11-13): each one makes the Model slower to understand. The id is H16 because H15 is held for slot-named columns (BL-514). The Formulas view tags the helpers H16 reported "used once, hidden", and a formula using any of them shows its definition a second time with each pasted in, in parentheses. A formula a visible column shows no longer reads as hidden in the view when a hidden column also shows it. On the 20 most formula-heavy Models of the SE demo cluster (32 to 118 formulas each), 1 finding: of 71 hidden formulas, 53 were used by no formula (BL-577), 9 by two or more, and 9 by exactly one (measured on the rule as shipped). New findings only; none change. |
| 3.20.0 | 2026-11-14 | **S17, access-control table planned as a second fact table, HIGH.** A measure-less table at the root of the Model's joins (nothing joins to it many-to-one; direction from cardinality, so a ONE_TO_MANY join from the dimension counts the same) beside another root, that reads as access-control by the product owner's two signals: it carries RLS rules and every column it surfaces in the Model is hidden, or another table's RLS rule reaches it through a rule path and none of its columns is in the Model. Live-verified 2026-11-12 on an internal dev cluster (the first signal's shape): planned as a second fact, two CTEs stitched by an outer join, roughly double the SQL; the dimension joined many-to-one to it gave one flat query with the same results. HIGH whatever the rule (product owner: an access-control list's RLS filter should leave one row per key per user). Advice: reverse the join for one `ts_username = [column]` rule on the table itself; otherwise review that the filter leaves one row per key, then reverse, keeping the join if it can leave two (ts_groups, a multi-value ts_var, `or`, a second rule, or a user column on another table can). Signal 1 needs at least one hidden column; a formula column over the table counts as one of its columns; only a rule path a rule references and that can be walked reaches a table. Never fires on a table holding measures or read by a formula measure, an event table exposing its columns, a Model with is_bypass_rls, or a table on an RLS join loop (S11's, CRITICAL). The classifier's blindness to formula measures elsewhere (D7, D11, the ERD) is BL-573. Either signal is enough; the second shape is not live-measured, so its finding says to check the query plan first. No fire-rate replay on real data yet. |
| 3.19.0 | 2026-11-12 | **Formula definitions in the Formulas view.** The view showed that a formula was used but not what it was. Clicking a formula, column or parameter now opens a panel with its definition as written, each reference a link that opens the tree down to it, what it uses, what uses it (by name, not a count) and everything that depends on it; an open formula shows its definition beneath it, by label; a search box finds columns and parameters by name, then formulas by name, then formulas by definition, and says when it shows only the first 50. On a narrow screen the definition is a sheet at the foot of the page. The tree is one tab stop, moved through with the arrow keys. The tree's uses and the definition's links are read by one scanner, `tml.expr_parts`, which `expr_refs` is now built on; a list where an expression belongs no longer reads as a column. The audit JSON's `formula_tree` nodes gain `expr`; a report from older JSON says to re-run the audit for definitions. No finding changes. |
| 3.18.0 | 2026-11-05 | **S16, RLS Tables scoping users through different columns, LOW "review" (BL-521).** G5e's keys half: a Model with two or more Tables whose RLS rules scope users through different sets of column names: the columns in a rule's clauses that name a session variable (case aside; columns only compared with a literal, null-tested guards and quoted literals not read). Any difference counts, per the product owner (2026-11-05); often intended, so LOW: review that the columns hold the same tenant values. 0 findings on the SE demo sample. |
| 3.17.0 | 2026-11-04 | **Two RLS checks worded "review", LOW (BL-512).** S14: a Model with two or more Tables whose RLS rules scope users by different sets of session variables (ts_groups, ts_username, ts_org, ts_email_domain, a custom `ts_var`), so one search can scope a user differently per Table. S15: an RLS rule that null-tests the column it scopes users by — the owner key — which keeps an outer join's unmatched rows but also shows the Table's ownerless rows to every user; S12 and S15 now advise testing the never-null join key instead. G5e's "different keys" half is BL-521. Both read rule expressions outside quoted literals. Neither fires on the SE demo sample (8 Tables with RLS, one variable each, no null tests). |
| 3.16.1 | 2026-11-04 | **References and join keys are read one way.** P17, P2 and H3 read formula references as the report's formula tree does — outside quoted literals, stripped, a formula resolved by its surfacing column's display name too — and H3 no longer counts a formula's reference to itself; the RLS reads skip literals too (BL-504). P6 reads join keys as D16 does, so a server-escaped name (`dim\.csv`) is typed, and P6 and D16 type a key of an aliased table, which read as unknown (BL-507). On the SE demo sample P6 gains 10 LOW findings and 7 others name more keys; nothing else changes. |
| 3.16.0 | 2026-11-04 | **D13 reads every bare window; the `*_in_period` spellings are aggregate.** D13 now also reads the `group_*` shorthands (`group_average`, …) and `last_value_in_period` / `first_value_in_period`, which the Model TML schema calls the same functions; an unset aggregation is still not read, since which one ThoughtSpot then applies is unverified. `AGGREGATE_FUNCS` now matches the two `*_in_period` spellings, so P2 and D14 no longer read such a formula as per-row (BL-509). No change on the SE demo sample. |
| 3.15.0 | 2026-11-04 | **Malformed TML never ends the run; what was not checked is shown.** Every list or mapping the audit reads now has its shape checked, as item 10 checked `properties`: a mapping where a list belongs (`model_tables`, `columns`, `joins_with`, `rls_rules.rules`), a single value where either belongs (`rls_rules`, `model_instructions`), a list entry that is not a mapping (a column, formula, filter, join, Table column, RLS rule, Answer formula or table), or a document body that is null or not a mapping. Each ended `ts audit run`; now the object is not judged and is listed under "Could not be read" (BL-501). A null, `0` or `""` list reads as empty, and no longer ends the run in the ERD; shapes no rule reads (`parameters`, `rls_rules.table_paths`) are left alone. `rls_rules` as a flat list of rules is malformed too: no schema doc or census Table has that shape, and reading it as absent would call a protected Table unprotected. A requested Model that was not exported is listed in a new "Not exported" box and `corpus.not_exported`, and the closing line counts it and the unreadable items (BL-516). The Answer export retries a refused batch one Answer at a time, as the Model export does, and records every skipped Answer in the run's warnings (BL-517). No change on the SE demo sample. |
| 3.14.0 | 2026-11-04 | **S12 raised to MEDIUM; the audit keeps healthy Models when one is gone.** S12 (an RLS Table on the optional side of an outer join with no null branch) is MEDIUM: per the docs' "Respect join definitions" such a rule can turn the outer join into an inner one, and whether it does depends on cluster settings the audit cannot read, so it is flagged for review (product owner, 2026-11-04). S12 now recognises the docs' `is_null ( … )` and `= null` as null branches as well as `isnull`, and its advice names no spelling (the formula language and the RLS docs disagree). `ts audit run` retries a Model export batch refused as a bad request (400 or 404) one Model at a time, so one deleted Model no longer drops up to 49 others; a server or auth failure still skips the batch, and stops a retry part-way (BL-510). The sample's findings are unchanged (S12 has none there). |
| 3.13.0 | 2026-11-04 | **New rules, set 2 (roadmap PR 4.4).** Eight rules, each with its evidence class: **S12** an RLS Table on the optional side of an outer join with no `isnull` clause (fact, LOW until probed, BL-511); **S13** an RLS rule search cannot index — no `ts_groups` / `ts_username`, or a `!=` (fact, LOW); **D13** a bare `group_aggregate` / `last_value` / `first_value` summed under a rate, price or ratio name — not a balance, which SUM rightly totals (heuristic, MEDIUM); **D17** an identifier, zip code, coordinate or date part summed, read as the name's last word so a qualifier ("Prior Year Sales") is not (heuristic, MEDIUM); **D18** a copy of a fact or factless table in one Model (fact, LOW, in rollout); **H13** date-part columns beside a date column (heuristic, LOW hint); **H14** flags shown as true/false or 0/1 (heuristic, LOW); **A9** parameters in formulas on a Spotter-enabled Model (fact, LOW, in rollout). On the 144-Model SE demo sample: D17 79 columns in 28 Models, H14 43 Models, H13 22, A9 6, S13 1 rule, S12 / D13 / D18 none; no existing finding changes and no rule warns in `ts audit fire-rates`. Deferred: an RLS path through a one-to-many join (BL-410), G5e/G5f (BL-512), slot-named columns (BL-514). |
| 3.12.0 | 2026-11-02 | **D14 reads per-row formulas.** A MEASURE column surfacing a per-row formula (no aggregate call, none reached through the formulas it references) is rolled up by its `aggregation`, like a physical column, so D14 now checks it too. Aggregate formulas stay out: their aggregation is ignored, except a bare `group_aggregate` / `last_value` / `first_value`, whose aggregation is applied and which D13 is to cover (BL-506). Product owner's ruling on formula aggregation, 2026-11-02. On the 148-Model SE demo sample: one more finding (a per-row ratio formula set to SUM), 133 columns in 53 Models; nothing else changes. |
| 3.11.0 | 2026-11-02 | **New rules, set 1 (roadmap PR 4.3).** Seven rules from the Model and Table TML alone, each with its evidence class: **A7** visible measures without a description (measure; LOW, MEDIUM above 75%); **A8** one search term naming two columns (fact; MEDIUM when a column's name is another's synonym, LOW when only synonyms are shared); **H11** many hidden ordinary columns no formula uses that are not join keys (measure; LOW above 25%, MEDIUM above 50%); **H12** pipeline columns visible — etl/dw/stg, row hashes, load stamps, a leading underscore (heuristic, LOW); **D14** a price-, rate- or ratio-like column summed (heuristic, MEDIUM); **D15** duplicate Table-level joins (fact; MEDIUM when type or cardinality differ, LOW for identical copies); **D16** join keys of different type families (fact, MEDIUM). On the 148-Model SE demo sample: A7 91 Models (65 MEDIUM), A8 47 (20 MEDIUM), D14 132 columns in 52 Models; H11, H12, D15 and D16 none (the independent review read H12's first word list as matching business columns only, and H11's findings as hidden join keys, so both were narrowed); no existing finding changes and no rule warns in `ts audit fire-rates`. A summed semi-additive formula (G1's other half) waits for a live check (backlog). |
| 3.10.0 | 2026-11-02 | **Severity rubric (roadmap PR 4.2).** Every rule declares its evidence: a **fact** the TML states, a **measure** graded against a pass mark, or a **heuristic** inference (a name or wording pattern). A heuristic rule grades at most MEDIUM, enforced by the catalog gate, unless it carries an approved `severity_exception`; S5 (a credential-named column) does, so it stays CRITICAL. **S2 and S4 drop HIGH → MEDIUM** (PII is a name match); on the 148-Model SE demo sample S2's 45 HIGH findings move to MEDIUM and nothing else changes. Findings carry `evidence` in the JSON, and the report tags heuristic ones "name match". The catalog doc gains an Evidence column. New: `ts audit fire-rates --snapshot-in <dir>` reports how many of its objects each rule fires on and warns at MEDIUM+ on more than half, unless a dated `fire_rate_reviewed` explains why; reviews recorded for A3, A6, A1, A2 under Spotter and A3 under General. |
| 3.9.0 | 2026-11-01 | **Table roles from join direction (roadmap PR 4.1).** A table's role now comes from where it sits in the joins, refined by its measures, through one classifier shared with the ERD (`agents/shared/erd/roles.py`): a **fact** is a root of the joins (no table joins to it) holding a measure; **factless** a root holding none (a bridge or a factless fact); a **dimension** is joined to; a **dimension with measures** is joined to yet holds measures (an order header's freight). Flags: outrigger, attribute-heavy fact, unjoined. Replaces "more than 3 MEASURE columns". **D11** is MEDIUM when both ends of a one-to-many join hold measures, its message saying so; **D7**'s shared fact is the fact role, so two Models sharing only a header are not duplicates. On the 148-Model SE demo sample: 4 D11 joins INFO → MEDIUM, 1 new D7 MEDIUM, no other finding moves. The audit JSON records each table's role (`corpus.models[].model_tables[].role`). ts-audit now stops with an error if the shared classifier cannot be loaded. |
| 3.8.0 | 2026-10-31 | **Formula dependency tree (roadmap PR 3.2).** A new report view, Formulas: one tree per Model, from each formula nothing else uses down through the formulas it builds on to the table columns and parameters, each marked MEASURE or ATTRIBUTE, hidden helper or hidden and unused, and used-by count, under the name people search it by. Roots open one level, with Expand all (about 2,000 rows per press) and Collapse all; a circular reference is shown, not walked. Reached from a Formulas sidebar link (a Model picker) and a Formula tree link on each Model's scorecard. The audit JSON gains `corpus.models[].formula_tree`; a report rendered from older JSON says to re-run the audit. The first view built on the 3.1 registry: a new view file and registry entry, plus its styles and the scorecard link. No finding changes. |
| 3.7.1 | 2026-10-30 | **Malformed TML is not judged, and is shown (BL-406 item 10).** A Model whose TML, or a Table it uses, holds a list or single value where a mapping belongs (`properties`, `spotter_config`, `db_column_properties`) gets no findings and no readiness score, and neither do such a Table, the Answers built on either, nor the Model's Sets; cross-Model rules (D7, D8, D12) do not see it, while its formulas and Tables still count for "on no Model" (H7, H8, H9). The dashboard's "Could not be read" box and the run's JSON (`corpus.unreadable`) name each object once, with every path, e.g. `columns[Amount].properties`, and the run warns on stderr. Before, such a value was mapped over (`properties: [...]` read as hidden, so H3 reported the column and A1/A2 left it out) or ended `ts audit run` (report corpus, ERD, table roles, column types, RLS column reads, D12). No change on the SE demo sample. Other non-mapping shapes (a flat-list `rls_rules`, a list `model_instructions`, a scalar list entry) still end the run: BL-501. |
| 3.7.0 | 2026-10-30 | **Grading into data (roadmap PR 2.4).** A new catalog key, `parameters`, holds a code rule's tuning numbers, profile-overridable and gated: H2's length limits and issues listed, H10's quote length. D1 grades by its catalog bands and H10 by a catalog severity map. P2 now counts a formula as row-level from its expression (no aggregate call, no reference to an aggregate formula) instead of the column's `aggregation:` key, which the model schema says never told the two apart: on the SE demo sample, 6 → 8 findings. H1 and the Spotter readiness score share one name test. `ts audit run` no longer ends on a null or numeric Model, table or column name. The grading text names a rule's parameters ("LOW (tuned by min chars 20, …)"). P6's two severities stay in code. Design: `docs/superpowers/specs/2026-10-30-audit-grading-data.md`. |
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
