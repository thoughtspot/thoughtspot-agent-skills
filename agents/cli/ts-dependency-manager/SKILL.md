---
name: ts-dependency-manager
description: Safely audit, remove, or repoint columns and objects across a ThoughtSpot environment — generates a risk-rated impact report, backs up TML before any change, and supports full rollback.
---

# ThoughtSpot: Dependency Manager

Safely make changes that affect dependent objects in ThoughtSpot. Before any modification,
this skill generates a full impact report with hyperlinks and risk ratings, lets you choose
exactly what to change, takes TML backups, and provides rollback capability.

**Supported operations:**

- **Remove columns** — remove one or more columns from a connection table or Model, then
  clean up all dependent Answers, Liveboards, and Models that reference them
- **Repoint objects** — redirect Answers or Liveboards to a different table or Model,
  with column-gap detection and mapping

> **Note: RENAME mode is intentionally not supported by this skill.** Smoke testing
> on champ-staging (2026-04-27) demonstrated that ThoughtSpot's TML import API
> sometimes applies a column rename despite returning `status_code: ERROR` —
> leaving source and dependents out of sync with no atomicity guarantee. Until
> TS resolves the misleading-error issue (open-item #15) and the skill has a
> reliable post-import verification path (added v0.2.0), RENAME is excluded.
> Use the ThoughtSpot UI to rename columns; this skill stays focused on the
> safe-to-automate operations.

**When to use this skill:**

- A database column has been deprecated and needs to be removed from ThoughtSpot cleanly
- A column has been renamed in the data warehouse and ThoughtSpot objects need updating
- Answers or Liveboards need to be moved to a new or restructured Model
- You want to audit what would be affected before making a structural change
- You want a dependency report on a column/table/Model **without** committing to a change — Audit mode, or run `ts metadata report` directly for a non-interactive shell version.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/dependency-types.md](references/dependency-types.md) | Status of every dependency type (Implementable / Partial / Manual / GUID-stable / Informational), the dependency hierarchy the skill walks in Step 4, and a worked sample of the Step 5 impact report — read before adding new dep handling or changing how Step 4 walks the graph |
| [references/open-items.md](references/open-items.md) | Dependency API, search_query and join constraints, Alert scan, RLS/security/aliasing open items — read before implementing Steps 4 and 9 |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure — column and formula placement rules, self-validation checklist |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer TML structure — answer_columns, cohorts (sets), chart, table, search_query layout |
| [../../shared/schemas/thoughtspot-sets-tml.md](../../shared/schemas/thoughtspot-sets-tml.md) | Set (cohort) TML structure — reusable vs answer-level, anchor_column_id, bin/group/query types |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure — visualizations, filters, layout |
| [../../shared/schemas/thoughtspot-view-tml.md](../../shared/schemas/thoughtspot-view-tml.md) | View TML structure — view_columns, joins, table_paths, search_query |
| [../../shared/schemas/thoughtspot-alert-tml.md](../../shared/schemas/thoughtspot-alert-tml.md) | Alert TML structure — metric_id references, personalised_view_info filters |
| [../../shared/schemas/thoughtspot-feedback-tml.md](../../shared/schemas/thoughtspot-feedback-tml.md) | Feedback/coaching TML structure — search_tokens and formula_info column references |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Connection table TML structure — column definitions |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Python package: `pyyaml` (`pip install pyyaml`)
- ThoughtSpot user must have **MODIFY** or **FULL** access on all objects being changed

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-dependency-manager** — safely audit, remove, or repoint columns and objects across a ThoughtSpot environment, with a full impact report and TML backup before any change is made.

### A. Steps

  1.  Authenticate ......................................... auto
  2.  Choose mode (Audit | Remove | Repoint) ............... you choose
       Audit produces a dependency report only — no changes applied.
       Useful before any change to plan blast radius.
  3.  Identify source object and column scope .............. you provide
  4.  Walk dependents via v2 dependents API and classify
      impact (alias-aware) ................................. auto  (~3 s — single API call + per-dep TML check)
  5.  Impact report — review, confirm, re-scan, or exit .... you confirm
  6.  Per-object action — fix (update) or delete entirely .. you choose; chart decisions apply only to "fix"
  7.  Back up all TML (source + every selected dependent) to /tmp/ts_dep_backup_<ts>/ ... auto
  8.  Pre-change confirmation; deletes require typed "DELETE" confirmation ... you confirm
  9.  Apply changes (deletes first, then updates, then source) ... auto
 10.  Rollback on any failure ............................... auto

Confirmation required: Steps 5, 6, 8 (extra typed confirm if any deletes are queued)
Auto-executed: Steps 1, 3 (model lookup), 4, 7, 9, 10

### B. Dependency hierarchy

What the skill walks during Step 4. Solid arrows = standard dependencies via v2 dependents API; dotted arrows = TML-attached objects that come through `--associated` exports; dashed arrows = TMLs that exist but are not retrievable on this build.

```
                  [CONNECTION]
                       │
                       ▼
                   [TABLE]──────────────────┐
                  /  │  \                   │
                 /   │   \              (inline)
                /    │    \                 │
               /     │     \                ▼
              /      │      ╲       [table.rls_rules]
             /       │       ╲              (#7 RLS — verified)
            /        │        ╲
           ▼         ▼         ╲- - -→ [<TABLE>_CSR.column_security_rules]
       [MODEL]    [VIEW]                   (#9 — retrieval unverified)
        / │ \      │ │
       /  │  \     │ │  ............→ [<MODEL>.column_alias]
      /   │   ╲    │ │       (#10 — retrieval unverified)
     /    │    ╲   │ │
    ▼     ▼     ▼  ▼ ▼
 [ANSWER] │  [SET]   ┊
     │    │     │    ┊  (model-attached)
     │    │     ▼    ┊
     │    │  [ANSWER consumers via Set]
     │    │
     ▼    ▼
 [LIVEBOARD]
     │   │
     │   └ ............→ [nls_feedback]   (#18 partial via --associated)
     │
     ├ ............→ [monitor_alert]   (#6 verified via --associated)
     ▼
[SCHEDULE]   (informational only — column-agnostic)
```

### C. Coverage at a glance

Before showing the prompt, run the coverage helper and display its output verbatim
so the user can see what the skill auto-detects vs. what needs manual review:

```bash
python3 references/build_coverage.py --summary
```

Sample output (regenerates from `references/dependency-types.md`):

```
Coverage:  auto-detected (8): Model / Worksheet, View, Answer, Liveboard, Set / Cohort, Monitor alert, RLS rule, Inline alias
           partial (3): Spotter feedback, Column security rule (CSR), Column alias TML
           informational (2): Schedule, Connection | no skill action (1): Column-level ACLs
           Full breakdown in references/dependency-types.md
```

If a status changes (e.g. open-item #9 CSR retrieval verified), update
`references/dependency-types.md` only — this block re-renders. Do **not** hardcode
the list anywhere in SKILL.md.

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If the file is missing or empty, prompt the
user to run `/ts-profile-thoughtspot` first.

If multiple profiles exist, ask:

```
Which ThoughtSpot profile would you like to use?

  1. {name}  —  {base_url}
  2. {name}  —  {base_url}

Enter number:
```

If exactly one profile exists, show it and ask the user to confirm.

Authenticate:

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

If the command fails, the token may be expired. Refer to
[../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) for the
token refresh procedure.

Save `{base_url}` (strip trailing slash) and `{profile_name}` for all subsequent steps.

---

## Step 2 — Choose Mode

Ask:

```
What would you like to do?

  Plan:
    A  Audit — generate a dependency report; no changes applied.
       Use this to understand blast radius BEFORE deciding on a column change.

  Apply changes:
    R  Remove column(s)  — remove one or more columns and clean up all dependents
    P  Repoint objects   — redirect Answers / Liveboards to a different
                           Model, View, or connection Table

Enter A / R / P:
```

Save `{operation}` (`AUDIT` / `REMOVE` / `REPOINT`) and branch to the appropriate
Step 3 sub-section.

> **RENAME mode is not supported** — see the rationale at the top of this file. If
> the user types `N`, respond with the warning explaining why and prompt them to
> pick A/R/P or use the ThoughtSpot UI for renames.

**Audit (A) is read-only.** No backups taken, no objects modified. The audit produces
the same report files as R/N/P (impact_plan.json, impact_report.csv, dependency_tree.txt,
dependency.mmd) and exits cleanly after Step 5. The user can re-run with R/N/P later
once they've planned their change.

> For a quick non-interactive audit, you can also run `ts metadata report <source>` directly — same coverage, no skill conversation. The CLI emits the same impact report data in JSON, text, or markdown.

---

## Step 3-A — Audit scope (operation = AUDIT)

Search for the source object exactly like Step 3-R (search both `WORKSHEET` and
`ONE_TO_ONE_LOGICAL` and `AGGR_WORKSHEET` subtypes). Save `{source_guid}`,
`{source_name}`, `{source_type}`.

Then ask which scope to report on:

```
What scope?

  1  One column          — pick a single column from the source
  2  Several columns     — pick multiple columns by number

  Deferred to a future commit (currently routed to scope 1 with a warning):
  3  Whole object        — section-per-column breakdown of every column on the source
  4  Repoint pre-flight  — pick a target object; show column-gap from source → target

Enter 1 / 2 / 3 / 4:
```

Then pick the column(s) using the same numbered-list flow as Step 3-R. Save:

- `{audit_columns}` — list of column names to scan against
- `{audit_scope}`   — `"ONE"` / `"MANY"` / `"WHOLE"` / `"REPOINT_PREFLIGHT"`

Branch directly to **Step 4 — Dependency Discovery** with these inputs. Step 4 runs
the same recursive walk regardless of operation. After Step 5 renders the report,
audit mode **exits cleanly** at Step 5.5 (defined below) — it does NOT proceed to
Step 6 / 7 / 8 / 9.

**Scope 3 and 4** are deferred — see open-items.md #19 (whole-object section-per-column
report) and #20 (repoint pre-flight column-gap analysis). For now, if the user picks
3 or 4, print a notice and route them to scope 1 ("treat this as one-column for now").

```python
if audit_scope in ("WHOLE", "REPOINT_PREFLIGHT"):
    print("\n⚠  Scope 3 (Whole object) and Scope 4 (Repoint pre-flight) are not yet")
    print("   implemented. Falling back to scope 1 — pick a single column.\n")
    audit_scope = "ONE"
    # Re-prompt for a single column
```

---

## Step 3-R — Identify Columns to Remove

Ask:

```
Which object contains the column(s) you want to remove?

  Enter a name or partial name to search (searches Models and connection tables):
```

Search for the object — run both queries and combine results:

```bash
# Models and Worksheets
source ~/.zshenv && ts metadata search \
  --subtype WORKSHEET \
  --name "%{search_term}%" \
  --profile "{profile_name}" \
  --all

# Connection tables
source ~/.zshenv && ts metadata search \
  --subtype ONE_TO_ONE_LOGICAL \
  --name "%{search_term}%" \
  --profile "{profile_name}" \
  --all
```

Show results as a numbered list, labelled `[MODEL]`, `[WORKSHEET]`, or `[TABLE]`. Let the
user pick one.

Save `{source_guid}`, `{source_name}`, `{source_type}` (`MODEL` / `WORKSHEET` / `TABLE`).

Export the source TML to get the column list:

```bash
source ~/.zshenv && ts tml export {source_guid} \
  --profile "{profile_name}" \
  --fqn \
  --parse
```

```python
import json, subprocess

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml export {source_guid} "
     f"--profile '{profile_name}' --fqn --parse"],
    capture_output=True, text=True,
)
export_json = json.loads(result.stdout)
source_export_item = export_json[0]  # save for Step 9
tml = source_export_item["tml"]

if source_type in ("MODEL", "WORKSHEET"):
    section = tml.get("model") or tml.get("worksheet", {})
    columns = [
        {"name": c["name"], "type": c.get("properties", {}).get("column_type", "ATTRIBUTE")}
        for c in section.get("columns", [])
    ]
else:  # TABLE
    table_section = tml.get("table", {})
    columns = [{"name": c["name"], "type": "ATTRIBUTE"} for c in table_section.get("columns", [])]
```

Show columns as a numbered list:

```
Columns in "{source_name}":

  1  Customer ID     ATTRIBUTE
  2  Revenue         MEASURE
  3  Order Date      ATTRIBUTE
  4  Legacy Region   ATTRIBUTE
  5  Old Segment     ATTRIBUTE
  ...

Enter numbers to remove (comma-separated), or a search term to filter:
```

Save `{columns_to_remove}` (list of column names).

Confirm the selection:

```
Columns selected for removal from "{source_name}":

  - Legacy Region
  - Old Segment

Correct? (Y / N):
```

---

## Step 3-P — Identify Objects and Target for Repoint

Ask:

```
What would you like to repoint?

  A  Specific Answers or Liveboards — search by name
  M  All objects pointing at a specific Model — search for the source Model

Enter A or M:
```

**M — All objects pointing at a source Model:**

Search for the source Model, let the user pick. Save `{source_guid}`, `{source_name}`.

Then ask:

```
What is the new target Model or table?

  Enter a name or partial name to search:
```

Search and let user pick. Save `{target_guid}`, `{target_name}`, `{target_type}`.

Export both source and target TMLs to identify the column gap:

```python
def export_columns(guid, profile_name):
    result = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml export {guid} "
         f"--profile '{profile_name}' --fqn --parse"],
        capture_output=True, text=True,
    )
    item = json.loads(result.stdout)[0]
    tml = item["tml"]
    section = tml.get("model") or tml.get("worksheet") or tml.get("table", {})
    return {c["name"] for c in section.get("columns", [])}

source_cols = export_columns(source_guid, profile_name)
target_cols = export_columns(target_guid, profile_name)
column_gap  = source_cols - target_cols   # columns not available in target
```

If `column_gap` is non-empty, show it to the user:

```
Column gap — these columns exist in "{source_name}" but NOT in "{target_name}":

  - Legacy Region
  - Old Segment Code

  Any objects that use these columns will have them removed during the repoint.

Continue? (Y / N):
```

**A — Specific Answers or Liveboards:** Search by name, let the user select multiple.

For each selected object, export its TML and check which of its data source references
will be repointed. Then ask for the target using the same search as above.

Save `{source_guid}`, `{target_guid}`, `{target_name}`, `{column_gap}`.

---

## Step 4 — Walk dependents

Call the `ts metadata report` command to do the walk. It returns the same data the skill previously assembled inline, plus richer coverage (RLS, alerts, joins, Spotter AI surface area, column aliases).

```bash
ts metadata report <source-guid> --profile {profile_name} --format json --depth 3 > /tmp/{slug}_report.json
```

Then parse the JSON. The shape is documented in [ts-metadata-report design spec](../../../docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md). Key fields:

- `source` — `{ "input", "guid", "type", "name", "parent" }`
- `dependents[]` — flat list, each with `guid / name / type / hops / owner / modified_at / risk{tag,reason}`
- `coverage[]` — `[{ "type", "checked", "found", "reason?" }, ...]`
- `classification` — `{ "per_dependent", "aggregate{tag,reason}", "recommendation" }`

Where the skill needs to filter by audit-scope (specific columns vs whole-object), it does so over the dependents list after parsing — the CLI returns everything the source touches.

### Filtering by scope

| Scope | Filter applied after parse |
|---|---|
| Specific column(s) | Keep dependents whose `risk.reason` references the column name; drop others. |
| Column set | As above, but check membership against the set's columns. |
| Whole object | Keep all dependents. |

---

## Step 5 — Render the impact report

The CLI already does the rendering. Run:

```bash
ts metadata report <source-guid> --profile {profile_name} --format md --out /tmp/{slug}_impact_report.md
```

Present the markdown content to the user. Apply scope filtering (Step 4) to the dependents table before display when the audit scope is column-specific.

The CLI's coverage matrix is the canonical Scan Coverage block — `build_coverage.py` is now retired in favor of the live API-driven coverage list.

### Stop conditions

When `classification.aggregate.tag == "STOP"`, surface to the user:

> ⛔ STOP CONDITION — `{recommendation}`
>
> {reason}
>
> Resolve via the ThoughtSpot UI (remove or rewrite the RLS rule) before re-running this skill.

For Audit mode, stop after this step. For Remove / Repoint, proceed to Step 6 only if the user explicitly accepts the STOP impact.

---

## Step 6 — Object Selection and Per-Object Action

This step has three parts run in order:

- **6a — Selection:** which dependents to act on (existing A / N / S menu)
- **6b — Action per object:** for each selected dependent, choose to **fix** it (strip column
  references — the historical default) or **delete** it entirely. Delete is opt-in and gated
  by a typed-confirmation prompt at Step 8
- **6c — Chart-removal decisions:** only asked for objects marked **fix** that have
  `action == "REMOVE_CHART"`. Objects marked for delete skip these decisions — the entire
  Liveboard or Answer is going away, so per-viz choices are moot

### 6a — Select objects

**If any dependent has `action == "REMOVE_CHART"`**, present per-chart decisions later in 6c
(only for objects the user marks **fix** in 6b). Liveboards with `REMOVE_CHART` vizzes can have
those specific charts removed from the liveboard; standalone Answers with `REMOVE_CHART` cannot
be auto-fixed and are excluded from the **fix** list (you can still mark them **delete**).

```
CHART REMOVAL DECISIONS REQUIRED

The following chart visualizations use the removed column as a primary axis (X or Y).
Each requires a decision before the main operation proceeds:

─── LIVEBOARD: Q4 Sales Overview ──────────────────────────────────
  Viz: Revenue Trend  (Y axis: Legacy Region)
    A  Remove this chart from the liveboard
    S  Skip — leave this visualization unchanged (may appear broken after column removal)

─── LIVEBOARD: Monthly Report ──────────────────────────────────────
  Viz: Monthly Revenue by Region  (X axis: Legacy Region)
    A  Remove this chart from the liveboard
    S  Skip — leave this visualization unchanged

─── ANSWERS (skip only — cannot partially fix a standalone Answer) ─
  → Sales by Region Q4  (Y axis: Legacy Region)
     Automatically excluded from update list. Will appear in Change Report as
     "Requires manual intervention".

Enter decisions (e.g. "1A 2S"):
```

Ask:

```
Which of the {N} dependent objects would you like to act on?

  A  All {N} objects
  N  None — make the source change only; dependent objects will need manual updates
  S  Select specific objects

Enter A / N / S:
```

If S, show the numbered list from the impact report and let the user enter numbers
(comma-separated). Confirm the selection before proceeding.

The **source object itself** is always updated — the column must be removed, renamed,
or the source must be updated regardless of which dependents are selected. The source
cannot be marked for delete from this step (deleting the source would be a different
operation entirely; refuse and re-prompt if the user attempts it).

Save `{selected_objects}` (list of dependent object dicts including guid, type, name, tml).

### 6b — Choose action per selected object: fix or delete

Default action for every selected object is **fix** (= strip the column references — the
behaviour applied prior to this skill version). The user can opt to **delete** specific
objects instead. Deletes are **destructive and not eligible for clean rollback** (see the
warning below) — keep this option opt-in.

Ask:

```
For the {M} selected dependent(s), choose an action:

  F  Fix all       — strip the affected column references from every selected object
                     (default; preserves objects)

  D  Delete all    — DELETE every selected dependent object entirely
                     ⚠  IRREVERSIBLE without manual TML re-import; new GUIDs on restore;
                     references from any object NOT in the selected list will break.

  M  Mixed         — choose F or D for each selected object individually

Enter F / D / M:
```

If **D** or **M**, show this warning block before continuing:

```
⚠  DELETE WARNING

  Deleting a ThoughtSpot object is permanent. The skill will:
    • Take a TML backup before any delete (Step 7 — non-negotiable, always runs)
    • Call POST /api/rest/2.0/metadata/delete (with explicit type) for each object marked
      for delete in Step 9. Note: the ts CLI's `metadata delete` command is currently broken
      — it reports success without actually deleting — so the skill calls v2 directly
    • Offer rollback by re-importing the backup at Step 11

  Important rollback caveats:
    • Re-imported objects receive a NEW GUID. Any object that referenced the deleted
      object by its original GUID — including objects NOT in the selected list, or
      objects you cannot see (cross-org, RLS-restricted, Spotter feedback) — will
      remain broken even after rollback.
    • Sets / Cohorts / Spotter feedback / Alerts that depend on the deleted object
      cannot be auto-restored.
    • Re-imported Liveboards lose their saved layout if the backup TML doesn't include it.

  Do not proceed unless you accept these caveats.
```

If **M**, present a numbered list and ask for one F/D per row:

```
Set action for each object (e.g. "1F 2D 3D 4F"):

  1  Q4 Sales Overview        (LIVEBOARD)  default: F
  2  Sales by Region Q4       (ANSWER)     default: F
  3  Customer 360 Model       (MODEL)      default: F
  4  Historical Comparison    (ANSWER)     default: F
```

Validate input — every selected object must have an explicit F or D. Reject ambiguous input
and re-prompt rather than guessing.

Save the action on each dict: `dep["user_action"] = "FIX" | "DELETE"`.

Split the list:
- `objects_to_fix`    — dependents with `user_action == "FIX"`
- `objects_to_delete` — dependents with `user_action == "DELETE"`

### 6b.1 — Set-cascade enforcement

If any Set is marked `DELETE` in `objects_to_delete`, every consumer of that Set (Answers
and Liveboards listed in the Set's `consumers[]` from Step 4) MUST also be in either
`objects_to_fix` or `objects_to_delete`. Deleting a Set out from under its consumers
silently breaks them — the consumers continue to reference the (now-missing) Set GUID.

Walk the selection and check; if any consumer is missing, **block the run** with a stop-
condition prompt and require the user to either select the consumer for action or revert
the Set to FIX.

```python
deletes_blocked_by = []   # list of (set_dep, missing_consumer_guid)

for set_dep in [d for d in objects_to_delete if d["type"] == "SET"]:
    selected_guids = {d["guid"] for d in objects_to_fix} | {d["guid"] for d in objects_to_delete}
    for consumer_guid in set_dep.get("in_use_by", []):
        if consumer_guid not in selected_guids:
            deletes_blocked_by.append((set_dep, consumer_guid))

if deletes_blocked_by:
    print("\n⛔  SET-CASCADE BLOCK")
    print("  The following Sets are marked DELETE but have consumers that aren't in the action list.")
    print("  Deleting the Set will silently break these consumers. Resolve before continuing.\n")
    for set_dep, consumer_guid in deletes_blocked_by:
        consumer = next((d for d in dependents if d["guid"] == consumer_guid), None)
        consumer_name = (consumer or {}).get("name", "(unknown)")
        print(f"    Set: {set_dep['name']} ({set_dep['guid']})")
        print(f"      missing consumer: {consumer_name} ({consumer_guid})")
    print("\n  Options:")
    print("    A  Add the missing consumers to the action list (you'll be prompted F/D each)")
    print("    R  Revert the Set(s) to FIX action")
    print("    X  Exit")
    # Re-prompt — do not proceed to Step 6c until resolved
```

### 6c — Chart-on-axis decisions (only for objects to fix)

Run this flow ONLY for entries in `objects_to_fix` with `action == "REMOVE_CHART"`. Skip
entirely for objects in `objects_to_delete` — the whole object is being removed, so per-viz
decisions are irrelevant.

**Two valid choices per viz/answer — SKIP is not offered.** Skipping would leave the column
referenced in that object, which causes ThoughtSpot to reject the source change at Step 9b
with error 14544 ("Deleted columns have dependents") naming the skipped object. The user
must pick a real fix or delete the whole object via Step 6b.

```
CHART AXIS DECISIONS REQUIRED

The following visualizations use the removed column as a primary X or Y axis.
For each, choose how to fix it:

  T  Convert to table view  (default — preserves the viz, switches display_mode to TABLE_MODE,
                             strips the column from search_query/answer_columns/chart bindings)
  A  Remove the chart       (Liveboard only — drops the entire viz from the liveboard;
                             for standalone Answers this is unavailable — delete via Step 6b
                             if you want the Answer gone)

─── LIVEBOARD: Q4 Sales Overview ──────────────────────────────────
  1  Viz: Revenue Trend            (Y axis: Legacy Region)   [T / A]
  2  Viz: Monthly Revenue by Region (X axis: Legacy Region)  [T / A]

─── ANSWERS (auto-fixed to TABLE_MODE — no decision needed) ────────
   - Sales by Region Q4  (Y axis: Legacy Region)  → CONVERT_TO_TABLE

Enter decisions (e.g. "1T 2A"), or press Enter to accept defaults (all T):
```

Save per-viz decisions as `dep["viz_remove_decisions"] = {viz_id: "CONVERT_TO_TABLE" | "REMOVE"}`
for each liveboard. Standalone Answers with `action == "REMOVE_CHART"` are auto-marked
`CONVERT_TO_TABLE` (they remain in `objects_to_fix`).

Final state passed to Step 7:
- `objects_to_fix`    — dependents to update (column references stripped)
- `objects_to_delete` — dependents to delete entirely

Inform the user about backup location before continuing:

```
Next: Step 7 will back up the source object PLUS every selected dependent.

  Backup directory: /tmp/ts_dep_backup_<YYYYMMDD_HHMMSS>/
  This includes the source — even if you selected "None" above, the source TML is still
  backed up because the column change itself is a change. Backup runs automatically
  before any modification and is required for rollback.
```

---

## Step 7 — TML Backup

**Non-negotiable: this step always runs and must complete successfully before Step 9.**
A successful TML export is taken for **every object that will change** — including the
source itself, even if no dependents were selected. The source change (column removed,
renamed, or repointed) is itself a change and is always backed up.

Scope of the backup:
- **Source object** (always — the column-modifying change happens here at Step 9b)
- Every dependent in `objects_to_fix` (column references stripped at Step 9c)
- Every dependent in `objects_to_delete` (object removed at Step 9a)
- A `manifest.json` index linking each backup file to its GUID, name, type, and intent

If any backup export fails, abort the run and ask the user how to proceed — never skip,
never proceed with partial backup.

### Choose backup location

Before generating the backup path, ask the user:

```
Where should the TML backup be saved?

  1  /tmp/   (default — ephemeral, cleared on reboot)
  2  Custom path

Enter 1 or a path [default: 1]:
```

If the user enters a custom path, use it as the base directory. The skill appends
`ts_dep_backup_<YYYYMMDD_HHMMSS>/` for uniqueness in both cases. If the directory
doesn't exist, create it with `os.makedirs(path, exist_ok=True)`.

### Announce backup location BEFORE running

Before exporting anything, tell the user where the backup will be written and what it will
contain. The path is generated once and reused for the rest of this run.

```
TML BACKUP — about to run

  Location:  {backup_dir}/
  Contents:  manifest.json
             {source_type}_{source_guid}_{source_name}.json   ← source
             {type}_{guid}_{name}.json   × {F + D} dependent(s)

  This backup is required for rollback (Step 11). Keep the directory until you are
  confident the change is correct.
```

Replace the placeholders with the actual path (computed below) and counts before printing.
Then begin the export loop.

Export and save the current TML for every object that will be modified or deleted. Do this
even if the user selected "None" in Step 6 (the source still changes).

```python
import os, json, datetime

timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup_base = custom_backup_path or "/tmp"
backup_dir  = os.path.join(backup_base, f"ts_dep_backup_{timestamp}")
os.makedirs(backup_dir, exist_ok=True)

# Source + everything we touch (fix + delete) — non-negotiable: always back up before Step 9
all_to_backup = (
    [{"guid": source_guid, "name": source_name, "type": source_type, "intent": "FIX_SOURCE"}]
    + [{**d, "intent": "FIX"}    for d in objects_to_fix]
    + [{**d, "intent": "DELETE"} for d in objects_to_delete]
)

# Announce the backup destination BEFORE exporting so the user can see where files will land.
print(f"TML backup will be written to: {backup_dir}/")
print(f"  {len(all_to_backup)} object(s) will be exported "
      f"(1 source + {len(objects_to_fix)} fix + {len(objects_to_delete)} delete)")

manifest = {
    "created":       timestamp,
    "profile":       profile_name,
    "base_url":      base_url,
    "operation":     operation,
    "source_object": {"guid": source_guid, "name": source_name, "type": source_type},
    "fix_count":     len(objects_to_fix),
    "delete_count":  len(objects_to_delete),
    "objects":       [],
}

print(f"Backing up {len(all_to_backup)} object(s) to {backup_dir}...")

for obj in all_to_backup:
    result = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml export {obj['guid']} "
         f"--profile '{profile_name}' --fqn --parse"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Backup failure on a delete-target is fatal — TML is the only restore source.
        # Backup failure on a fix-target is also treated as fatal: the skill guarantees
        # rollback, and rollback requires the backup. Abort and surface to the user.
        print(f"  ✗ Backup FAILED for '{obj['name']}' ({obj['guid']}) — intent={obj.get('intent')}")
        raise SystemExit(
            "Backup failed for at least one object. No changes have been applied. "
            "Investigate the export error (token, permissions, object validity) and re-run."
        )

    for item in json.loads(result.stdout):
        safe_name   = obj["name"].replace("/", "_").replace("\\", "_")[:60]
        backup_file = os.path.join(backup_dir,
                                   f"{item['type']}_{item['guid']}_{safe_name}.json")
        with open(backup_file, "w") as f:
            json.dump(item, f, indent=2)
        manifest["objects"].append({
            "guid":        item["guid"],
            "name":        obj["name"],
            "type":        item["type"],
            "intent":      obj.get("intent", "FIX"),
            "backup_file": backup_file,
        })

with open(os.path.join(backup_dir, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)

print(f"  Backed up {len(manifest['objects'])} file(s) — manifest at {backup_dir}/manifest.json")
```

Save `{backup_dir}` for use in Steps 10 and 11.

Tell the user:

```
TML backup saved to: {backup_dir}
  {N} object(s) backed up. Keep this path handy — it is required for rollback.
```

---

## Step 8 — Pre-change Confirmation

Show a concise summary of all changes that will be made. No changes have been made yet.
Sections only appear when non-empty: skip "Dependent objects to delete" if `objects_to_delete`
is empty, etc.

**REMOVE example with mixed fix + delete:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 PENDING CHANGES — ready to apply
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Source:
  {source_name} ({source_type}):
    Remove columns: Legacy Region, Old Segment

Dependent objects to FIX ({F}):
  Q4 Sales Overview     (LIVEBOARD) — remove column references
  Customer 360 Model    (MODEL)     — remove formula referencing Legacy Region

Dependent objects to DELETE ({D}):  ⚠  IRREVERSIBLE without manual intervention
  Sales by Region Q4    (ANSWER)    — entire object will be deleted
  Historical Comparison (ANSWER)    — entire object will be deleted

Skipped ({K} not selected):
  Old Trend Liveboard   (LIVEBOARD)

Backup: {backup_dir}
Order:  deletes first → updates → source
Policy: ALL_OR_NONE per object update; v2 /metadata/delete (with explicit type) for deletions

IMPORTANT: This will modify {F + 1} and DELETE {D} live ThoughtSpot objects.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Proceed? (Y / N):
```

If `objects_to_delete` is non-empty AND user answers Y, **require a typed confirmation**
before proceeding to Step 9:

```
You have {D} object(s) marked for DELETE. This is irreversible without manual TML re-import.

Type DELETE (in capitals, exactly) to confirm:
```

If the input is anything other than the exact string `DELETE`, treat it as a no and ask:

```
  A  Adjust selection (go back to Step 6)
  X  Exit without making any changes

Enter A / X:
```

If N at the first prompt (no deletes pending), ask the same A / X choice without the typed
confirmation step.

---

## Step 9 — Apply Changes

Apply changes in this order:

1. **9a — Deletes** (`objects_to_delete`) — runs first; leaf-most types first (Liveboards,
   Answers), then Models/Views in reverse-dependency order. Removes the objects the user
   explicitly asked to delete before any updates so the dependency graph reflects the final
   intent.
2. **9b — Fixes on dependents** (`objects_to_fix`) — strip column references from each
   remaining dependent. Order: Liveboards/Answers first (no recursion); Sets next; Views;
   Models last (so a Model's dependent Views/Answers/Sets reflect the fix before the Model
   itself is rewritten).
3. **9c — Source** — modify the source object (column removed / renamed / repointed). Runs
   LAST because TS error 14544 will reject the source change while ANY visible dependent
   still references the column. Source must be the final step.
4. **9d — Reusable Sets** — only used for sets where action is `DELETE` and `9b` didn't already
   handle them; for FIX-mode sets, the body update happens in `9b` alongside other dependents.

Each import is atomic (ALL_OR_NONE per object). A failure on one item does not roll back
previously successful operations — track all results in a single `results` dict for the
Step 10 Change Report.

### Drift check helper (Fix #3, 2026-04-26)

Before applying any change to a specific object, re-query its `metadata_header.modified`
and compare against the value snapshotted in Step 4 (`modified_at_scan[guid]`). If the
timestamp moved, someone else edited the object between scan and apply — the dep walk's
analysis (chart roles, alias chain, removed-column references) is now stale. Skip the
import and report DRIFT_DETECTED.

```python
def check_drift(guid, type_str, profile_name, snapshot):
    """Returns (has_drift: bool, current_modified: int, error: Optional[str]).

    `snapshot` is the int from `modified_at_scan[guid]`. If we cannot re-query
    (network failure, deleted object), return has_drift=True with the error so
    the caller skips the import — better to fail safe than to clobber.
    """
    r = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts metadata get {guid} --type {type_str} --profile '{profile_name}'"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return True, 0, (r.stderr.strip() or "metadata get returned no output")
    try:
        meta = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return True, 0, f"JSON decode error: {e}"
    current = int((meta.get("metadata_header") or {}).get("modified", 0))
    if not snapshot:
        # No snapshot to compare against — be conservative and allow the import.
        # Source-not-found cases will surface naturally as the import proceeds.
        return False, current, None
    return (current != snapshot), current, None


def v2_type_for(skill_type):
    """Map skill type label to v2 metadata type."""
    return {
        "ANSWER": "ANSWER", "LIVEBOARD": "LIVEBOARD",
        "SET": "LOGICAL_COLUMN", "COHORT": "LOGICAL_COLUMN",
    }.get(skill_type.upper(), "LOGICAL_TABLE")


def assert_no_drift_or_skip(guid, skill_type, profile_name, snapshot, results,
                            phase, name=None):
    """Returns True if safe to proceed; False if drift detected (caller must skip).
    Logs the skip into `results['skipped']` with reason DRIFT_DETECTED."""
    has_drift, current, err = check_drift(guid, v2_type_for(skill_type), profile_name, snapshot)
    if has_drift:
        reason = (f"DRIFT_DETECTED — modified at scan was {snapshot}, "
                  f"now {current}" + (f"; query error: {err}" if err else ""))
        results.setdefault("skipped", []).append({
            "guid": guid, "name": name or guid, "type": skill_type,
            "phase": phase, "reason": reason,
        })
        print(f"  ⚠ Skip {skill_type} {name or guid} — {reason}")
        return False
    return True
```

**Detect obj_id support (REPOINT only).** Before any modifications, probe whether the
instance supports obj_id references by exporting the source with the obj_id flags.
When obj_id is available, the repoint helpers use it instead of fqn — avoiding
VERSION_CONFLICT (error 14009) on builds that track content versions via obj_id.

```python
source_obj_id = None
target_obj_id = None

if operation == "REPOINT":
    probe = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml export {source_guid} "
         f"--profile '{profile_name}' --include-obj-id --include-obj-id-ref "
         f"--no-guid --parse"],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        probe_items = json.loads(probe.stdout)
        probe_tml = probe_items[0]["tml"] if probe_items else {}
        probe_section = probe_tml.get("model") or probe_tml.get("worksheet") or probe_tml.get("table", {})
        for tbl in probe_section.get("model_tables", probe_section.get("tables", [])):
            if tbl.get("obj_id"):
                source_obj_id = tbl.get("obj_id")
                break
        if not source_obj_id and probe_tml.get("obj_id"):
            source_obj_id = probe_tml["obj_id"]

    if source_obj_id:
        # Derive target obj_id: {target_name}-{first 8 chars of target_guid}
        target_obj_id = f"{target_name}-{target_guid[:8]}"
        print(f"  obj_id detected — using obj_id-based repoint (avoids VERSION_CONFLICT)")
        print(f"    source: {source_obj_id}")
        print(f"    target: {target_obj_id}")
    else:
        print(f"  obj_id not available — using fqn-based repoint")
```

**Source drift is a hard stop.** If the source object has drifted between Step 4 and
Step 9, abort the entire run before touching any dependent — the Step 6 plan was
computed against the old source, and applying it could remove columns that were
re-purposed in the meantime.

```python
# Run this BEFORE 9a/9b/9c
if not assert_no_drift_or_skip(source_guid, source_type, profile_name,
                               modified_at_scan.get(source_guid, 0),
                               results, phase="drift_pre_check",
                               name=source_name):
    raise SystemExit(
        "Source object has drifted since Step 4 — aborting the entire run. "
        "No changes applied. Re-run /ts-dependency-manager from Step 1 to "
        "rebuild the impact plan against the current source state."
    )
```

For dependent objects, drift detection skips that one object and continues with
the rest. The user sees DRIFT_DETECTED entries in the Change Report and can re-run
the skill on the affected dependents.

### 9a — Delete objects marked for deletion

Skip this section entirely if `objects_to_delete` is empty.

**Verified 2026-05-11 on se-thoughtspot:** `ts metadata delete <guid> --type <type>`
genuinely deletes objects. The CLI passes `type` in the v2 request body and the API
performs the deletion (confirmed by post-delete `ts metadata get` returning "No … object
found"). See open-items.md #17 for the history of the earlier CLI bug (now fixed).

```python
results = {"succeeded": [], "failed": [], "deleted": [], "skipped": []}

# Delete order: terminal types first, then non-terminal (Sets, Models/Views, source last)
# Sets are intentionally placed before Models/Views — a Set's parent Model still needs to
# exist so the Set's TML can be backed up earlier in Step 7. Sets delete cleanly even
# while their Model is still present, since the cascade is one-directional.
delete_order = {
    "LIVEBOARD": 0, "ANSWER": 1,
    "SET": 2, "COHORT": 2,
    "VIEW": 3,
    "MODEL": 4, "WORKSHEET": 4,
    "TABLE": 5,
}
sorted_deletes = sorted(objects_to_delete, key=lambda d: delete_order.get(d["type"].upper(), 9))

# v2 type values expected by --type flag
v2_type_map = {
    "ANSWER":    "ANSWER",
    "LIVEBOARD": "LIVEBOARD",
    "MODEL":     "LOGICAL_TABLE",
    "WORKSHEET": "LOGICAL_TABLE",
    "VIEW":      "LOGICAL_TABLE",
    "TABLE":     "LOGICAL_TABLE",
    "SET":       "LOGICAL_COLUMN",
    "COHORT":    "LOGICAL_COLUMN",
}

for dep in sorted_deletes:
    v2_type = v2_type_map.get(dep["type"].upper())
    if not v2_type:
        results["failed"].append({**dep, "error": f"no v2 type mapping for {dep['type']}",
                                  "phase": "delete"})
        continue

    # Drift check before deleting (Fix #3). If the object has been modified since
    # Step 4, the user's selection at Step 6 may have been based on stale state —
    # skip the delete and let the user re-scan.
    if not assert_no_drift_or_skip(dep["guid"], dep["type"], profile_name,
                                   modified_at_scan.get(dep["guid"], 0),
                                   results, phase="delete", name=dep["name"]):
        continue

    print(f"  Deleting {dep['type']}: {dep['name']} ({dep['guid']})...")
    r = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts metadata delete {dep['guid']} --type {v2_type} "
         f"--profile '{profile_name}'"],
        capture_output=True, text=True,
    )

    if r.returncode == 0:
        print(f"  ✓ Deleted: {dep['name']}")
        results["deleted"].append(dep)
    else:
        # Verify by re-querying — if the object is gone, treat as success
        check = subprocess.run(
            ["bash", "-c",
             f"source ~/.zshenv && ts metadata get {dep['guid']} --type {v2_type} "
             f"--profile '{profile_name}'"],
            capture_output=True, text=True,
        )
        if check.returncode != 0 or not check.stdout.strip():
            print(f"  ✓ Deleted: {dep['name']}  (verified by post-query)")
            results["deleted"].append(dep)
        else:
            err = f"CLI exit {r.returncode}: {r.stderr[:200]}"
            print(f"  ✗ Delete failed: {dep['name']} — {err}")
            results["failed"].append({**dep, "error": err, "phase": "delete"})
```

If a delete fails (permissions, dependent of an inaccessible object, etc.), continue with the
remaining deletes — the user will see the failures in the Change Report and can decide whether
to retry or roll back.

### 9b — Modify and import the source object

Read [references/open-items.md](references/open-items.md) #2 before modifying Answer or
Liveboard TML — some fields use opaque column IDs that differ from display names.

**Helper: serialize TML dict to YAML and import**

```python
import copy, yaml, re, json, subprocess

def _str_representer(dumper, data):
    if '\n' in data or ('{' in data and '}' in data):
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='>')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, _str_representer)

def import_tml(tml_dict, guid, profile_name, policy="ALL_OR_NONE", create_new=False):
    """
    Import a TML dict.

    create_new=False (default) — update an existing object at `guid`. Adds `--no-create-new`
        so an unknown GUID errors out instead of silently creating a duplicate.
    create_new=True  — used by Step 11 rollback after a delete: the original GUID no longer
        exists, so we want TS to assign a new one. Strips `guid:` from the YAML and drops
        the `--no-create-new` flag.
    """
    tml_yaml = yaml.dump(tml_dict, allow_unicode=True, default_flow_style=False)
    if create_new:
        tml_yaml = re.sub(r"^guid:\s*\S+\s*\n", "", tml_yaml, count=1, flags=re.MULTILINE)
    elif not tml_yaml.strip().startswith("guid:"):
        tml_yaml = f"guid: {guid}\n" + tml_yaml
    payload = json.dumps([tml_yaml])
    cmd = (f"source ~/.zshenv && ts tml import "
           f"--profile '{profile_name}' --policy {policy}")
    if not create_new:
        cmd += " --no-create-new"
    result = subprocess.run(["bash", "-c", cmd], input=payload, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}

def import_status(resp):
    """Extract (ok: bool, error_msg: str) from an import response.

    NOTE: do not trust this in isolation. TS sometimes returns status_code=ERROR
    while still applying the change (open-item #15 + 2026-04-27 smoke test on
    TEST_DEPENDENCY_MANAGEMENT). Always pair with `verify_change_applied()`
    before reporting a per-object outcome.
    """
    try:
        status = resp["object"][0]["response"]["status"]
        ok     = status.get("status_code") == "OK"
        return ok, status.get("error_message", "Unknown error")
    except (KeyError, IndexError):
        return False, str(resp)


def verify_change_applied(guid, skill_type, profile_name, *,
                          operation, columns_to_remove=None,
                          target_guid=None, column_gap=None,
                          target_obj_id=None):
    """Re-export the object's TML and confirm the expected change was applied.

    Returns (verified_applied: bool, detail: str). The skill calls this AFTER
    every Step 9 import (regardless of import_status) and decides what to do
    based on the matrix:

      api=OK + verified=True    → SUCCESS
      api=OK + verified=False   → FAIL (silent rejection — rare)
      api=ERROR + verified=True → SUCCESS_WITH_WARNING (open-item #15: TS
                                  applied the change despite returning ERROR;
                                  log the warning, treat as succeeded, continue)
      api=ERROR + verified=False → FAIL (genuine rejection — current behaviour)

    Why this matters: smoke-test 2026-04-27 had TS return error_message
    "Invalid YAML/JSON syntax in file" while applying the rename. Without
    post-import verification the skill thought the import failed and aborted —
    leaving source and dependents out of sync.

    Per-operation verification:
      REMOVE  — none of the columns_to_remove may appear in the exported TML
      REPOINT — target_guid or target_obj_id must appear in the exported TML;
                columns in column_gap (if any) must be absent
    """
    cmd = (f"source ~/.zshenv && ts tml export {guid} "
           f"--profile '{profile_name}' --fqn "
           f"--include-obj-id --include-obj-id-ref --parse")
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return False, f"verification re-export failed: {r.stderr[:200]}"
    try:
        items = json.loads(r.stdout)
        if not items:
            return False, "verification re-export returned no items"
        body = json.dumps(items[0]["tml"])
    except (json.JSONDecodeError, KeyError) as e:
        return False, f"verification parse error: {e}"

    if operation == "REMOVE":
        cols = list(columns_to_remove or [])
        # Check both the bracketed token form ("[col]") and TABLE::col form
        leftover = [
            c for c in cols
            if (f'"{c}"' in body) or (f"[{c}]" in body) or (f"::{c}" in body)
        ]
        if leftover:
            return False, f"REMOVE not applied — still references: {leftover}"
        return True, f"REMOVE verified — none of {cols} appear in TML"

    if operation == "REPOINT":
        # Verify target is referenced — check both fqn and obj_id
        target_found = False
        if target_guid and target_guid in body:
            target_found = True
        if target_obj_id and target_obj_id in body:
            target_found = True
        if not target_found and (target_guid or target_obj_id):
            ref = target_obj_id or target_guid[:8]
            return False, f"REPOINT not applied — target {ref} not in TML"
        if column_gap:
            still_present = [c for c in column_gap if (f"[{c}]" in body) or (f"::{c}" in body)]
            if still_present:
                return False, f"REPOINT partial — gap columns still present: {still_present}"
        return True, "REPOINT verified — target referenced; gap columns absent"

    # Unknown operation: treat as not-verifiable (return True so we don't block)
    return True, f"verification skipped for operation={operation}"


def import_and_verify(tml_dict, guid, skill_type, profile_name,
                      operation, results, phase, name=None,
                      columns_to_remove=None, target_guid=None, column_gap=None,
                      target_obj_id=None):
    """Single entry point that wraps import_tml + import_status + verify_change_applied
    and writes the right entry to `results`. Use this at every Step 9 call site.

    Returns one of: "SUCCESS", "SUCCESS_WITH_WARNING", "FAIL_VERIFIED",
    "FAIL_SILENT" (api=OK but change didn't apply).
    """
    resp = import_tml(tml_dict, guid, profile_name)
    api_ok, api_err = import_status(resp)
    verified, verify_detail = verify_change_applied(
        guid, skill_type, profile_name,
        operation=operation,
        columns_to_remove=columns_to_remove,
        target_guid=target_guid, column_gap=column_gap,
        target_obj_id=target_obj_id,
    )

    label = name or guid
    record = {"guid": guid, "name": label, "type": skill_type, "phase": phase,
              "api_status": "OK" if api_ok else "ERROR",
              "api_error": None if api_ok else api_err,
              "verified": verified, "verify_detail": verify_detail}

    if api_ok and verified:
        results["succeeded"].append(record)
        return "SUCCESS"
    if (not api_ok) and verified:
        # TS lied — change was applied despite the error. Log + treat as success.
        record["warning"] = ("api returned ERROR but verification confirms the "
                             "change applied (open-item #15)")
        results["succeeded"].append(record)
        print(f"  ⚠ {skill_type} {label} — api=ERROR, verified=True. "
              f"Treating as success per open-item #15. err={api_err[:120]}")
        return "SUCCESS_WITH_WARNING"
    if api_ok and (not verified):
        record["error"] = f"api=OK but change not applied — {verify_detail}"
        results["failed"].append(record)
        print(f"  ✗ {skill_type} {label} — silent rejection. {verify_detail}")
        return "FAIL_SILENT"
    # Both ERROR and not verified — true failure
    record["error"] = f"{api_err}  ({verify_detail})"
    results["failed"].append(record)
    return "FAIL_VERIFIED"
```

**REMOVE — source is a Model or Worksheet:**

Join conditions that reference removed columns MUST also be updated — ThoughtSpot
will reject the import otherwise (see open-items.md #4). Use `source_affected_joins`
identified in Step 4 to know which joins to remove.

```python
updated_source = copy.deepcopy(source_export_item["tml"])
section = updated_source.get("model") or updated_source.get("worksheet")

# Collect formula IDs of any formula columns being removed
formula_ids_to_remove = {
    col.get("formula_id")
    for col in section.get("columns", [])
    if col.get("name") in columns_to_remove and col.get("formula_id")
}

section["columns"] = [
    c for c in section.get("columns", [])
    if c.get("name") not in columns_to_remove
]
section["formulas"] = [
    f for f in section.get("formulas", [])
    if f.get("id") not in formula_ids_to_remove
]

# Remove join conditions that reference the removed column(s)
# (must be done — cannot save a model with an orphaned join condition)
for tbl in section.get("model_tables", []):
    tbl["joins_with"] = [
        j for j in tbl.get("joins_with", [])
        if not any(col in j.get("on", "") for col in columns_to_remove)
    ]

# Remove model-level filters that reference the removed column(s)
# Required by open-items.md #12 — TS rejects the import with error_code 14518
# ("Invalid filter column") if a filter still references a deleted column.
section["filters"] = [
    f for f in section.get("filters", [])
    if not any(c in columns_to_remove for c in f.get("column", []))
]
```

**REMOVE — source is a connection Table:**

```python
updated_source = copy.deepcopy(source_export_item["tml"])
table_section  = updated_source.get("table", {})
table_section["columns"] = [
    c for c in table_section.get("columns", [])
    if c.get("name") not in columns_to_remove
]
```

Import the source object — but only after the source-drift hard-stop check above
has passed. The pre-check uses `assert_no_drift_or_skip` and aborts the entire run
on drift; if we get here, the source is still at the timestamp we scanned.

```python
print(f"  Updating source: {source_name}...")
outcome = import_and_verify(
    updated_source, source_guid, source_type, profile_name,
    operation=operation, results=results, phase="source",
    name=source_name,
    columns_to_remove=columns_to_remove if operation == "REMOVE" else None,
    target_guid=target_guid if operation == "REPOINT" else None,
    column_gap=column_gap if operation == "REPOINT" else None,
    target_obj_id=target_obj_id if operation == "REPOINT" else None,
)
if outcome in ("FAIL_VERIFIED", "FAIL_SILENT"):
    print(f"  ✗ Source update failed ({outcome}). "
          f"No dependent objects will be updated. Backup is at {backup_dir}.")
    return
# SUCCESS or SUCCESS_WITH_WARNING — proceed to dependents
print(f"  ✓ {source_name} ({outcome})")
```

### 9c — Modify and import dependent objects

**Search query helpers — mandatory for Answers and Views:**

ThoughtSpot rejects the import of any object where `search_query` references a column
that no longer exists. These sanitizers are not optional (see open-items.md #3).

```python
import re

def sanitize_search_query(query_str, cols_to_remove):
    """Strip [col_name] tokens from a ThoughtSpot search_query string."""
    if not query_str:
        return query_str
    for col in cols_to_remove:
        query_str = re.sub(r'\s*\[' + re.escape(col) + r'\]\s*', ' ', query_str)
    return query_str.strip()

def rename_in_search_query(query_str, old_name, new_name):
    """Rename a [col_name] token in a ThoughtSpot search_query string."""
    if not query_str:
        return query_str
    return re.sub(r'\[' + re.escape(old_name) + r'\]', f'[{new_name}]', query_str)
```

**For REMOVE — strip a column from an Answer or Liveboard viz:**

```python
def convert_answer_to_table(answer_dict):
    """
    Switch an answer to TABLE_MODE so it remains valid after a chart-axis column is stripped.
    Sets `display_mode = "TABLE_MODE"`. Used for REMOVE_CHART → CONVERT_TO_TABLE fixes.
    Skipping the conversion is not an option for column-removal cleanup: TS will reject the
    source change at error 14544 if the column is still referenced anywhere.
    """
    answer_dict["display_mode"] = "TABLE_MODE"
    return answer_dict

def remove_columns_from_answer(answer_dict, cols_to_remove):
    """Remove column references from an answer dict (the answer: section, not full TML)."""
    a = answer_dict

    # search_query — MUST be sanitized or ThoughtSpot will reject the import (open-items.md #3)
    if a.get("search_query"):
        a["search_query"] = sanitize_search_query(a["search_query"], cols_to_remove)

    # answer_columns[]
    a["answer_columns"] = [
        c for c in a.get("answer_columns", [])
        if c.get("name") not in cols_to_remove
    ]

    # table view: ordered_column_ids and table_columns
    tbl = a.get("table", {})
    if tbl.get("ordered_column_ids"):
        tbl["ordered_column_ids"] = [
            c for c in tbl["ordered_column_ids"] if c not in cols_to_remove
        ]
    tbl["table_columns"] = [
        c for c in tbl.get("table_columns", [])
        if c.get("column_id") not in cols_to_remove
    ]

    # chart view: chart_columns and axis_configs
    # Only strip color/size/shape bindings — x/y axis removal requires removing the
    # entire chart visualization. classify_chart_role() identifies those as REMOVE_CHART
    # and they are handled separately in Step 6 decisions and the liveboard loop below.
    chart = a.get("chart", {})
    chart["chart_columns"] = [
        c for c in chart.get("chart_columns", [])
        if c.get("column_id") not in cols_to_remove
    ]
    for axis in chart.get("axis_configs", []):
        for key in ("color", "size", "shape"):  # x/y excluded — see REMOVE_CHART path
            if key in axis and isinstance(axis[key], list):
                axis[key] = [v for v in axis[key] if v not in cols_to_remove]

    # formulas that reference the removed column
    formula_ids_to_remove = {
        f["id"] for f in a.get("formulas", [])
        if any(col in f.get("expr", "") for col in cols_to_remove)
    }
    if formula_ids_to_remove:
        a["formulas"]       = [f for f in a.get("formulas", [])
                                if f["id"] not in formula_ids_to_remove]
        a["answer_columns"] = [c for c in a.get("answer_columns", [])
                                if c.get("formula_id") not in formula_ids_to_remove
                                and c.get("name") not in
                                    {f["name"] for f in a.get("formulas", [])
                                     if f["id"] in formula_ids_to_remove}]

    # answer-level cohorts (sets) whose anchor_column_id is being removed
    # The set's display name also appears in answer_columns[] and may be in search_query
    set_names_to_remove = {
        c["name"] for c in a.get("cohorts", [])
        if c.get("config", {}).get("anchor_column_id") in cols_to_remove
    }
    if set_names_to_remove:
        a["cohorts"] = [
            c for c in a.get("cohorts", [])
            if c["name"] not in set_names_to_remove
        ]
        a["answer_columns"] = [
            c for c in a.get("answer_columns", [])
            if c.get("name") not in set_names_to_remove
        ]
        if a.get("search_query"):
            a["search_query"] = sanitize_search_query(
                a["search_query"], list(set_names_to_remove)
            )

    return a
```

**For REPOINT — change the data source reference and remove gap columns:**

The repoint helpers use **obj_id-first matching with fqn fallback**. When the TML was
exported with `--include-obj-id --include-obj-id-ref`, obj_id fields are present and the
helpers match on those. This avoids VERSION_CONFLICT (error 14009) on builds that track
content versions via obj_id. When obj_id is absent (older builds), the helpers fall back
to fqn matching.

```python
def repoint_answer(answer_dict, source_guid, target_guid, target_name, column_gap,
                   *, source_obj_id=None, target_obj_id=None):
    a = answer_dict

    for tbl in a.get("tables", []):
        matched = False
        if source_obj_id and tbl.get("obj_id") == source_obj_id:
            matched = True
        elif tbl.get("fqn") == source_guid:
            matched = True

        if matched:
            if target_obj_id:
                tbl["obj_id"] = target_obj_id
                tbl.pop("fqn", None)
            else:
                tbl["fqn"] = target_guid
                tbl.pop("obj_id", None)
            tbl["name"] = target_name
            tbl["id"]   = target_name

    if column_gap:
        a = remove_columns_from_answer(a, column_gap)

    return a
```

```python
def repoint_view(view_dict, source_guid, target_guid, target_name, column_gap,
                 *, source_obj_id=None, target_obj_id=None):
    """Update a View TML body to point at target_guid instead of source_guid.

    Prefers obj_id matching when available (avoids VERSION_CONFLICT / error 14009).
    Falls back to fqn when obj_id is absent.
    """
    v = view_dict
    old_name = None

    for tbl in v.get("tables", []):
        matched = False
        if source_obj_id and tbl.get("obj_id") == source_obj_id:
            matched = True
        elif tbl.get("fqn") == source_guid:
            matched = True

        if matched:
            old_name = tbl.get("name")
            if tbl.get("id") == old_name:
                tbl["id"] = target_name
            if target_obj_id:
                tbl["obj_id"] = target_obj_id
                tbl.pop("fqn", None)
            else:
                tbl["fqn"] = target_guid
                tbl.pop("obj_id", None)
            tbl["name"] = target_name

    if old_name and old_name != target_name:
        for tp in v.get("table_paths", []):
            if tp.get("table") == old_name:
                tp["table"] = target_name
        for j in v.get("joins", []):
            if j.get("source") == old_name:
                j["source"] = target_name
            if j.get("destination") == old_name:
                j["destination"] = target_name

    if column_gap:
        v = remove_columns_from_view(v, column_gap)

    return v
```

```python
def repoint_model(model_dict, source_name, target_name, column_gap,
                  *, source_obj_id=None, target_obj_id=None,
                  source_guid=None, target_guid=None):
    """Repoint a Model's model_tables entry from source to target.

    Updates model_tables obj_id/fqn/name, joins with/on clauses,
    column_id prefixes, formula expressions, and description.
    Prefers obj_id when available; falls back to fqn.
    """
    m = model_dict

    for tbl in m.get("model_tables", []):
        matched = False
        if source_obj_id and tbl.get("obj_id") == source_obj_id:
            matched = True
        elif source_guid and tbl.get("fqn") == source_guid:
            matched = True
        elif tbl.get("name") == source_name:
            matched = True

        if matched:
            tbl["name"] = target_name
            if target_obj_id:
                tbl["obj_id"] = target_obj_id
                tbl.pop("fqn", None)
            elif target_guid:
                tbl["fqn"] = target_guid
                tbl.pop("obj_id", None)

        for join_key in ("joins", "joins_with"):
            for j in tbl.get(join_key, []):
                if j.get("with") == source_name:
                    j["with"] = target_name
                on_clause = j.get("on", "")
                if f"[{source_name}::" in on_clause:
                    j["on"] = on_clause.replace(
                        f"[{source_name}::", f"[{target_name}::")

    for col in m.get("columns", []):
        cid = col.get("column_id", "")
        if cid.startswith(f"{source_name}::"):
            col["column_id"] = cid.replace(
                f"{source_name}::", f"{target_name}::", 1)

    for formula in m.get("formulas", []):
        expr = formula.get("expr", "")
        if f"[{source_name}::" in expr:
            formula["expr"] = expr.replace(
                f"[{source_name}::", f"[{target_name}::")

    desc = m.get("description", "")
    if source_name in desc:
        m["description"] = desc.replace(source_name, target_name)

    if column_gap:
        m = fix_model(m, column_gap)

    return m
```

**Apply to Answers:**

```python
for dep in [d for d in objects_to_fix if d["type"] == "ANSWER"]:
    # Drift check — skip this Answer if it's been edited since the Step-4 scan
    if not assert_no_drift_or_skip(dep["guid"], dep["type"], profile_name,
                                   modified_at_scan.get(dep["guid"], 0),
                                   results, phase="fix", name=dep["name"]):
        continue

    updated = copy.deepcopy(dep["tml"])
    answer  = updated.get("answer", {})

    if operation == "REMOVE":
        # Standalone Answers with action == "REMOVE_CHART" are auto-converted to TABLE_MODE
        # before stripping the column. This preserves the Answer (no longer "manual only").
        if dep.get("action") == "REMOVE_CHART":
            answer = convert_answer_to_table(answer)
        answer = remove_columns_from_answer(answer, columns_to_remove)
    elif operation == "REPOINT":
        answer = repoint_answer(answer, source_guid, target_guid, target_name, column_gap,
                                source_obj_id=source_obj_id, target_obj_id=target_obj_id)

    updated["answer"] = answer
    import_and_verify(
        updated, dep["guid"], dep["type"], profile_name,
        operation=operation, results=results, phase="fix", name=dep["name"],
        columns_to_remove=columns_to_remove if operation == "REMOVE" else None,
        target_guid=target_guid if operation == "REPOINT" else None,
        column_gap=column_gap if operation == "REPOINT" else None,
        target_obj_id=target_obj_id if operation == "REPOINT" else None,
    )
```

**Apply to Liveboards:**

Liveboards embed full answer definitions in `visualizations[].answer`. Apply the same
helper functions to each visualization's answer section that references `{source_guid}`.
Check against `[../../shared/schemas/thoughtspot-liveboard-tml.md]` for the exact
field layout before modifying.

```python
for dep in [d for d in objects_to_fix if d["type"] == "LIVEBOARD"]:
    # Drift check (Fix #3)
    if not assert_no_drift_or_skip(dep["guid"], dep["type"], profile_name,
                                   modified_at_scan.get(dep["guid"], 0),
                                   results, phase="fix", name=dep["name"]):
        continue

    updated   = copy.deepcopy(dep["tml"])
    liveboard = updated.get("liveboard", {})

    # Collect vizzes the user chose to remove entirely (REMOVE_CHART + "A" decision)
    vizes_to_remove = set()

    for viz in liveboard.get("visualizations", []):
        viz_id = viz.get("id", "")
        answer = viz.get("answer", {})
        tables = answer.get("tables", [])
        if not any(t.get("fqn") == source_guid for t in tables):
            continue  # this viz doesn't use the source — skip

        if operation == "REMOVE":
            viz_action = dep.get("viz_actions", {}).get(viz_id, "REMOVE_COLUMN")
            if viz_action == "REMOVE_CHART":
                # Two valid decisions: CONVERT_TO_TABLE (default) or REMOVE.
                # SKIP is not offered — leaving the column referenced causes TS to reject
                # the source change at error 14544.
                decision = dep.get("viz_remove_decisions", {}).get(viz_id, "CONVERT_TO_TABLE")
                if decision == "REMOVE":
                    vizes_to_remove.add(viz_id)
                    continue
                # CONVERT_TO_TABLE: switch this viz's display_mode and strip the column
                answer = convert_answer_to_table(answer)
            answer = remove_columns_from_answer(answer, columns_to_remove)
        elif operation == "REPOINT":
            answer = repoint_answer(answer, source_guid, target_guid, target_name, column_gap)

        viz["answer"] = answer

    # Remove entire chart visualizations the user chose to delete
    if vizes_to_remove:
        liveboard["visualizations"] = [
            v for v in liveboard.get("visualizations", [])
            if v.get("id") not in vizes_to_remove
        ]

    # Liveboard-level filter updates (REMOVE only)
    if operation == "REMOVE":
        # Remove filter entries for removed columns (Rule 1)
        # A filter whose column list is fully emptied is dropped entirely
        updated_filters = []
        for filt in liveboard.get("filters", []):
            new_cols = [c for c in filt.get("column", []) if c not in columns_to_remove]
            if new_cols:
                filt["column"] = new_cols
                updated_filters.append(filt)
        liveboard["filters"] = updated_filters

    import_and_verify(
        updated, dep["guid"], dep["type"], profile_name,
        operation=operation, results=results, phase="fix", name=dep["name"],
        columns_to_remove=columns_to_remove if operation == "REMOVE" else None,
        target_guid=target_guid if operation == "REPOINT" else None,
        column_gap=column_gap if operation == "REPOINT" else None,
        target_obj_id=target_obj_id if operation == "REPOINT" else None,
    )
```

**Apply to Views:**

Views have `view_columns[]`, `formulas[]`, `joins[]`, and `search_query` — all need
updating when a referenced column is removed or renamed. See
[../../shared/schemas/thoughtspot-view-tml.md](../../shared/schemas/thoughtspot-view-tml.md)
for the full field layout.

```python
def remove_columns_from_view(view_dict, cols_to_remove):
    """Remove column references from a View TML dict (the view: section)."""
    v = view_dict

    # search_query — MUST be sanitized (same rule as Answers — open-items.md #3)
    if v.get("search_query"):
        v["search_query"] = sanitize_search_query(v["search_query"], cols_to_remove)

    # view_columns[] — remove entries whose column_id references the removed column
    v["view_columns"] = [
        c for c in v.get("view_columns", [])
        if not any(col in c.get("column_id", "") for col in cols_to_remove)
        and c.get("name") not in cols_to_remove
    ]

    # formulas[] — remove formulas whose expr references the removed column
    formula_ids_to_remove = {
        f["id"] for f in v.get("formulas", [])
        if any(col in f.get("expr", "") for col in cols_to_remove)
    }
    if formula_ids_to_remove:
        v["formulas"]     = [f for f in v.get("formulas", []) if f["id"] not in formula_ids_to_remove]
        v["view_columns"] = [c for c in v.get("view_columns", []) if c.get("column_id") not in formula_ids_to_remove]

    # joins[] — remove join conditions that reference the column in the ON expression
    v["joins"] = [
        j for j in v.get("joins", [])
        if not any(col in j.get("on", "") for col in cols_to_remove)
    ]

    return v
```

Apply to Views in the update loop:

```python
for dep in [d for d in objects_to_fix if d["type"] == "VIEW"]:
    # Drift check (Fix #3)
    if not assert_no_drift_or_skip(dep["guid"], dep["type"], profile_name,
                                   modified_at_scan.get(dep["guid"], 0),
                                   results, phase="fix", name=dep["name"]):
        continue

    updated = copy.deepcopy(dep["tml"])
    view    = updated.get("view", {})

    if   operation == "REMOVE":  view = remove_columns_from_view(view, columns_to_remove)
    elif operation == "REPOINT": view = repoint_view(view, source_guid, target_guid, target_name, column_gap,
                                                       source_obj_id=source_obj_id, target_obj_id=target_obj_id)

    updated["view"] = view
    import_and_verify(
        updated, dep["guid"], dep["type"], profile_name,
        operation=operation, results=results, phase="fix", name=dep["name"],
        columns_to_remove=columns_to_remove if operation == "REMOVE" else None,
        target_guid=target_guid if operation == "REPOINT" else None,
        column_gap=column_gap if operation == "REPOINT" else None,
        target_obj_id=target_obj_id if operation == "REPOINT" else None,
    )
```

**Apply to Feedback:**

Feedback items share the Model's GUID. Export the updated Model's `--associated` TML
to get the current feedback state, then strip stale entries:

```python
for dep in [d for d in objects_to_fix if d["type"] == "FEEDBACK"]:
    # Drift check (Fix #3) — feedback shares the Model GUID, so we re-check
    # the Model's timestamp; a moved Model invalidates the feedback we exported
    if not assert_no_drift_or_skip(dep["guid"], "MODEL", profile_name,
                                   modified_at_scan.get(dep["guid"], 0),
                                   results, phase="fix", name=dep["name"]):
        continue

    updated   = copy.deepcopy(dep["tml"])
    feedback  = updated.get("nls_feedback", {})
    target    = columns_to_remove

    entries = feedback.get("feedback", [])
    if operation == "REMOVE":
        entries = [
            e for e in entries
            if not any(col in json.dumps(e) for col in target)
        ]
    feedback["feedback"] = entries
    updated["nls_feedback"] = feedback
    import_and_verify(
        updated, dep["guid"], "MODEL", profile_name,
        operation=operation, results=results, phase="fix", name=dep["name"],
        columns_to_remove=columns_to_remove if operation == "REMOVE" else None,
    )
```

**Apply to dependent Models:**

Dependent Models may join on the renamed/removed column. Apply the same removal/rename
logic as Step 9b (source) — including **join condition removal AND model-level filter
removal** — to each dependent Model's TML. Both are required to avoid TS rejection
(open-items.md #4 and #12).

```python
def fix_model(m, cols_to_remove):
    """Strip a column from a model TML body. Returns the same dict mutated."""
    # Strip from columns[]
    formula_ids_to_remove = {
        c.get("formula_id") for c in m.get("columns", [])
        if c.get("name") in cols_to_remove and c.get("formula_id")
    }
    m["columns"] = [c for c in m.get("columns", []) if c.get("name") not in cols_to_remove]
    m["formulas"] = [f for f in m.get("formulas", []) if f.get("id") not in formula_ids_to_remove]

    # Strip join conditions referencing the column (open-items.md #4)
    for tbl in m.get("model_tables", []):
        tbl["joins_with"] = [
            j for j in tbl.get("joins_with", [])
            if not any(c in j.get("on", "") for c in cols_to_remove)
        ]

    # Strip model-level filters referencing the column (open-items.md #12)
    # TS rejects the import with error_code 14518 if a filter references a missing column.
    m["filters"] = [
        f for f in m.get("filters", [])
        if not any(c in cols_to_remove for c in f.get("column", []))
    ]

    return m
```

**Track all results:**

```python
results = {"succeeded": [], "failed": [], "skipped": []}
# Add source to succeeded (already confirmed above)
results["succeeded"].append({"name": source_name, "type": source_type, "guid": source_guid})

for dep in objects_to_fix:
    # ... apply change, call import_tml, call import_status ...
    if ok:
        results["succeeded"].append(dep)
    else:
        results["failed"].append({**dep, "error": err})
        print(f"  ✗ {dep['name']} — {err}")
```

### 9d — Process reusable Sets

After all dependent objects have been updated, process the `affected_sets` list.

Read [references/open-items.md](references/open-items.md) #11 before implementing the
delete step — the `ts metadata delete` command for Sets is unverified.

**For REMOVE — delete sets that operated on the removed column:**

Sets with `action == "DELETE_SAFE"` have no consumers and can be deleted immediately.
Sets with `action == "DELETE_AFTER_DEPENDENTS"` had consumers that should have been
updated in 9c — but only delete the Set if every consumer fix actually succeeded.
Deleting a Set whose consumer fixes failed leaves the consumers pointing at a missing
Set GUID (silent breakage). Skip the Set delete in that case and surface in the
Change Report so the user can investigate.

```python
# Index 9c results by guid for O(1) lookup
fix_results_by_guid = {r.get("guid"): r for r in results["succeeded"]
                       if r.get("phase") in ("fix", None)}
fix_failed_guids = {r["guid"] for r in results["failed"]
                    if r.get("phase") in ("fix", None) and r.get("guid")}

for s in affected_sets:
    if s["action"] not in ("DELETE_SAFE", "DELETE_AFTER_DEPENDENTS"):
        continue

    # GUARD (Fix #2, 2026-04-26): if any consumer fix failed in 9c, do NOT delete the
    # Set. Deleting it would silently break the failed consumer (now points at a
    # missing GUID with no chance for the skill to detect or restore).
    consumer_guids = set(s.get("in_use_by", []))
    failed_consumers = consumer_guids & fix_failed_guids
    if failed_consumers:
        msg = (f"skipped — {len(failed_consumers)} consumer fix(es) failed in 9c; "
               f"deleting the Set would dangle those consumers. "
               f"Failed consumer GUIDs: {sorted(failed_consumers)}")
        print(f"  ⚠ Skip delete '{s['name']}' ({s['guid']}): {msg}")
        results["skipped"].append({"name": s["name"], "type": "SET", "guid": s["guid"],
                                   "phase": "set_delete", "reason": msg})
        continue

    print(f"  Deleting set '{s['name']}' ({s['guid']})...")
    result = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts metadata delete {s['guid']} "
         f"--profile '{profile_name}'"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  ✓ Deleted set: {s['name']}")
        results["succeeded"].append({"name": s["name"], "type": "SET", "guid": s["guid"],
                                     "phase": "set_delete", "action": "deleted"})
    else:
        err = result.stderr.strip() or result.stdout.strip()
        print(f"  ✗ Failed to delete set '{s['name']}': {err}")
        results["failed"].append({"name": s["name"], "type": "SET", "guid": s["guid"],
                                  "phase": "set_delete", "error": err})
```

---

## Step 10 — Change Report

Show a full summary of what succeeded, what failed, and what was skipped:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CHANGE REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Operation:  {operation_description}
Source:     {source_name} ({source_type})

 ✓ Updated ({N}):
   - {source_name} (source — {source_type})
   - Q4 Sales Overview        (LIVEBOARD)
   - Customer 360 Model       (MODEL)

 ✗ Deleted ({D}):  ⚠  rollback re-imports as NEW GUIDs — see warning below
   - Sales by Region Q4       (ANSWER)
   - Historical Comparison    (ANSWER)

 ✗ Failed ({M}):
   - Outbound Trends Model    (MODEL)
     Error: column 'Legacy Region' appears in a join condition —
            join conditions cannot be modified by TML import on this instance.
     Backup: {backup_dir}/model_{guid}_Outbound_Trends_Model.json

 ─ Skipped ({K}):
   - Old Trend Liveboard      (LIVEBOARD) — not selected
   - Q3 Sales Liveboard       (LIVEBOARD) — DRIFT_DETECTED: modified at scan was
                              1714123456000, now 1714234567890. Re-run the skill
                              to refresh the impact plan against the current state.
   - Customer Segment Set     (SET) — set_cascade: 1 consumer fix(es) failed in 9c;
                              deleting the Set would dangle those consumers.

Backup location: {backup_dir}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If any objects were deleted, append:

  ⚠  Deleted objects can be re-imported from {backup_dir} but will receive NEW GUIDs.
     Other objects (visible or not) that referenced the original GUIDs will not be
     automatically reconnected. Plan manual reattachment if needed.
```

For each failed object, provide an actionable next step (manual UI edit, different approach,
or a note that the backup is ready to restore if needed).

---

## Step 11 — Rollback Option

After the change report, ask:

```
Would you like to roll back any changes? (Y / N):
```

If N, proceed to Cleanup.

If Y:

```
Which objects would you like to roll back?

  A  Roll back ALL successfully changed objects (updates AND deletes)
  U  Updated objects only — restore original TML for in-place updates
  D  Deleted objects only — re-import deleted objects from backup (NEW GUIDs)
  S  Select specific objects

Enter A / U / D / S:
```

If S, show a numbered list of all changed objects (both updated and deleted) and let the user
pick.

For any deleted object the user chose to roll back, show this caveat once and require
acknowledgment before proceeding:

```
⚠  Restoring deleted objects:

  Deleted objects will be re-imported from the TML backup. The new objects will receive
  NEW GUIDs assigned by ThoughtSpot. Any other object that referenced the deleted object's
  ORIGINAL GUID will remain broken — including objects you cannot see.

  Continue? (Y / N):
```

**Rollback implementation:**

```python
import json

def rollback_objects(backup_dir, guids_to_rollback, profile_name):
    manifest_path = os.path.join(backup_dir, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    restore_policy = {
        "table":    "PARTIAL",
        "model":    "ALL_OR_NONE",
        "answer":   "ALL_OR_NONE",
        "liveboard": "ALL_OR_NONE",
    }

    rollback_results = {"succeeded": [], "failed": [], "new_guids": {}}

    # Restore dependents before source (reverse dependency order)
    entries = [e for e in manifest["objects"] if e["guid"] in guids_to_rollback]
    entries.sort(key=lambda e: 0 if e["type"] == "table" else 1)

    for entry in reversed(entries):
        with open(entry["backup_file"]) as f:
            backup_item = json.load(f)

        policy = restore_policy.get(backup_item["type"], "ALL_OR_NONE")
        was_deleted = entry.get("intent") == "DELETE"

        if was_deleted:
            # Re-import as NEW object — strip guid from TML so TS assigns a new one
            tml_dict = dict(backup_item["tml"])
            tml_dict.pop("guid", None)
            # Use create-new policy: object no longer exists at original GUID
            resp = import_tml(tml_dict, None, profile_name, policy=policy, create_new=True)
        else:
            resp = import_tml(backup_item["tml"], entry["guid"], profile_name, policy=policy)

        ok, err = import_status(resp)

        if ok:
            new_guid = (resp.get("object", [{}])[0]
                            .get("response", {}).get("header", {}).get("id_guid"))
            label = entry["name"] + (f" (new GUID: {new_guid})" if was_deleted and new_guid else "")
            rollback_results["succeeded"].append(label)
            if was_deleted and new_guid:
                rollback_results["new_guids"][entry["guid"]] = new_guid
            print(f"  ✓ Rolled back: {label}")
        else:
            rollback_results["failed"].append({"name": entry["name"], "error": err})
            print(f"  ✗ Rollback failed: {entry['name']} — {err}")

    return rollback_results
```

Note: `import_tml` here is assumed to support a `create_new=True` flag that removes
`--no-create-new` from the underlying `ts tml import` call when restoring a deleted object.
Update the helper in §9b accordingly: when `create_new=True`, drop the `--no-create-new` flag.

Show rollback results. If any deletes were restored, surface the GUID mapping table
(`old_guid → new_guid`) so the user can update any external references manually.

If any rollbacks failed, tell the user the backup file path for manual restoration.

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts auth whoami` returns 401 | Token expired — follow the refresh steps in `/ts-profile-thoughtspot` |
| Import returns 403 / UNAUTHORIZED | User lacks edit access on the object — skip it, note in report; backup available |
| Import: `column_id not found` in dependent | Column reference format may differ from display name — see open-items.md #2 |
| Import: `search_query` validation error | The `search_query` still references a removed column — `sanitize_search_query()` may have missed a token. Check for bracket-format variants like `[TABLE::col]` and strip manually |
| Import: join condition references removed column | `source_affected_joins` detection in Step 4 may have missed a join — check `model_tables[].joins_with[].on` for the column name and remove the join entry manually |
| Liveboard import fails after REMOVE_CHART decision | Viz ID in `viz_remove_decisions` may not match `visualizations[].id` — print `dep["viz_actions"]` keys and compare to `viz.get("id")` in the liveboard TML |
| Import: model already exists with same name | `guid:` may be missing or mis-placed — check the YAML serialization in `import_tml()` |
| Import creates a new object instead of updating | `--no-create-new` flag missing — add it; delete the duplicate via `ts metadata delete` |
| Dependency scan returns 0 results unexpectedly | Batch export may have timed out — reduce `batch_size` to 5 and re-run Step 4 |
| View TML import fails after column removal | `view_columns[].column_id` may use `TABLE_PATH::col` format — check that column path ID prefix is retained in the update |
| Feedback TML import fails | Feedback shares the Model GUID — ensure `guid:` at document root matches the Model's GUID, not a separate feedback GUID |
| Liveboard TML import fails validation | Chart column IDs may differ from display names — see open-items.md #2 |
| Rollback import fails | Open the backup JSON manually; the `tml` field contains the original YAML — import via the ThoughtSpot UI TML editor |
| `pyyaml` not installed | `pip install pyyaml` |

---

## Cleanup

The backup directory at `{backup_dir}` is kept after the skill completes to enable rollback.
Remind the user:

```
Backup retained at: {backup_dir}
Remove when you are confident the changes are correct: rm -rf {backup_dir}
```

Remove any temp import files created during the session:

```bash
rm -f /tmp/ts_dep_*.yaml
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-06-09 | **Repoint: obj_id-based references with fqn fallback.** Step 9 now detects `obj_id` support via `export_options` flags and prefers obj_id-based model_table references over fqn to avoid VERSION_CONFLICT (error 14009) on some TS builds (open-item #23). New `repoint_model()` function handles model_tables obj_id/name/joins/column_id/formula swaps. `repoint_answer()` and `repoint_view()` also support obj_id-first matching. **Backup location prompt** — Step 7 now asks the user where to save backups (current directory, /tmp, or custom path) instead of hardcoding /tmp. Requires ts-cli v0.8.0 (`--include-obj-id`, `--include-obj-id-ref`, `--no-guid` flags). |
| 1.0.0 | 2026-04-27 | Initial release. Three modes: **Audit** (read-only blast-radius report), **Remove** (drop one or more columns and clean up dependents), **Repoint** (redirect Answers/Liveboards to a different Model/View/Table with column-gap detection). Step 4 dep walk uses the v2 metadata/search dependents API (`ts metadata dependents`) with **alias propagation** — per-Model/View aliases for the target column are extracted at scan time so Answers/Liveboards/Sets that reference renamed columns (e.g. `ZIPCODE` → `Customer Zipcode`) are caught. **STOP-condition** handling for inaccessible dependents (v2 `hasInaccessibleDependents` flag), source-table RLS rules, model-level join conditions referencing the column (open-items.md #4), model-level filters (#12), and chart-axis conflicts. Step 5 impact report drives the Scan Coverage block from the canonical `references/dependency-types.md` status table via `references/build_coverage.py`. Steps 7 / 8 require typed "DELETE" / "ACCEPT INCOMPLETE IMPACT" confirmations and take a TML backup before any change is applied. Step 9 wraps every import with **post-import verification** (`import_and_verify`) — re-exports the TML and confirms the change actually applied, since TS sometimes returns status_code=ERROR while applying the change anyway (open-item #15). **Object-version drift detection** captures `metadata_header.modified` at scan time and aborts the per-object change (or the entire run, if the source drifted) when the timestamp moves between scan and apply. Step 11 supports rollback for both updates and deletes. RENAME mode is intentionally not supported on this build — see the rationale at the top of SKILL.md. |
