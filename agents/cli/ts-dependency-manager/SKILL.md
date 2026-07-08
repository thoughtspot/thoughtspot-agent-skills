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

Then parse the JSON. Key fields:

- `source` — `{ "input", "guid", "type", "name", "parent" }`
- `dependents[]` — flat list, each with `guid / name / type / hops / owner / modified_at / risk{tag,reason} / matched_columns[]`
- `coverage[]` — `[{ "type", "checked", "found", "reason?" }, ...]`
- `classification` — `{ "per_dependent", "aggregate{tag,reason}", "recommendation" }`

Where the skill needs to filter by audit-scope (specific columns vs whole-object), it does so over the dependents list after parsing — the CLI returns everything the source touches.

### Filtering by scope

`matched_columns[]` is the column name(s) the deep TML probes (RLS/join/alias/AI-surface/
alert) actually matched for that specific dependent — populated by
`ts_cli.report.classifier.build_matched_columns_map`. Filter on this field, not
`risk.reason`: every `reason` string is a fixed literal (e.g. "referenced in a join
condition") that never names a column, so a text match against it can never succeed
(2026-07 audit finding — dependency-manager column-scope filter bug).

| Scope | Filter applied after parse |
|---|---|
| Specific column(s) | Keep dependents whose `matched_columns` contains the column name; drop others. |
| Column set | As above, but check `matched_columns` for membership against the set's columns. |
| Whole object | Keep all dependents. |

Note: `matched_columns` is only populated when the report was walked with a
column-scoped source (`ts metadata report {table}.{COLUMN}` or a column GUID) — deep
probes activate only for `LOGICAL_COLUMN` sources (see Step 4's `ts metadata report`
command). For a Column(s) or Column-set scope, run one `ts metadata report` per target
column (or pass all of them as separate arguments to get the `{"reports": [...]}`
multi-source form) rather than a single whole-object report, so each dependent's
`matched_columns` is actually populated for the column(s) in scope.

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
    • Call `ts metadata delete <guid> --type <type>` for each object marked for
      delete in Step 9 (verified 2026-05-11 to genuinely delete)
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
referenced in that object, which causes ThoughtSpot to reject the source change (applied last in Step 9)
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
- **Source object** (always — the column-modifying change to the source happens in Step 9)
- Every dependent in `objects_to_fix` (column references stripped in Step 9)
- Every dependent in `objects_to_delete` (object removed in Step 9)
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

### Run the backup — `ts dependency backup`

Build a plan JSON (source object + every dependent in `objects_to_fix` and
`objects_to_delete`) and pass it to `ts dependency backup`. The command exports each
object's TML the same way `ts tml export --parse` does, writes one file per object
plus a `manifest.json`, and returns the manifest. It **collects all exports first and
writes nothing if any export fails** — so a partial backup directory can never be
mistaken for a complete one (backup failure is fatal for both fix- and delete-targets:
the skill guarantees rollback, and rollback needs the backup).

```python
import os, json, subprocess

plan = {
    "operation": operation,                              # "REMOVE" | "REPOINT"
    "source": {"guid": source_guid, "type": source_type, "name": source_name},
    "fix":    [{"guid": d["guid"], "type": d["type"], "name": d["name"]} for d in objects_to_fix],
    "delete": [{"guid": d["guid"], "type": d["type"], "name": d["name"]} for d in objects_to_delete],
    "out_dir": custom_backup_path or "/tmp",             # from the location prompt above
}

result = subprocess.run(
    ["bash", "-c", f"source ~/.zshenv && ts dependency backup --profile '{profile_name}'"],
    input=json.dumps(plan), capture_output=True, text=True,
)
if result.returncode != 0:
    raise SystemExit(
        "Backup failed — no changes have been applied and no backup files were written. "
        f"Investigate the export error (token, permissions, object validity) and re-run.\n{result.stderr}"
    )

manifest    = json.loads(result.stdout)
backup_dir  = os.path.dirname(manifest["objects"][0]["backup_file"])
print(f"TML backup saved to: {backup_dir}")
print(f"  {len(manifest['objects'])} object(s) backed up. Keep this path handy — it is required for rollback.")
```

Save `{backup_dir}` for use in Steps 10 and 11.

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
Policy: ALL_OR_NONE per object update; `ts metadata delete` (with explicit type) for deletions

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

The entire destructive change is executed by one codified command —
**`ts dependency apply-change`** (ts-cli ≥ 0.41.0, BL-083 PR2). It reads a plan JSON
on stdin and orchestrates the whole flow deterministically: drift check → deletes →
dependent fixes → source → set deletes, with obj_id-first repointing and post-import
verification. Do **not** re-implement this loop inline — the command encodes edge-case
fixes (the error-14544 ordering, open-item #15 verify-despite-ERROR, obj_id
VERSION_CONFLICT avoidance, the set-delete consumer guard) that a hand-rolled script
will miss. If the command misbehaves, fix `ts_cli/dependency/` and re-run.

**Order — source LAST.** apply-change applies changes as:

1. **Deletes** (`delete[]`) — leaf-most types first (Liveboards, Answers), then
   Models/Views. Removes what the user explicitly asked to delete.
2. **Dependent fixes** (`fix[]`) — strip column references (REMOVE) or repoint
   (REPOINT) from each remaining dependent. Terminal types first (Answers/Liveboards),
   then Sets, Views, Feedback, Models last.
3. **Source** — modify the source object. Runs **LAST**: TS error 14544 ("Deleted
   columns have dependents") rejects the source column removal while ANY dependent
   still references the column.
4. **Reusable Sets** (`sets[]`) — delete sets that operated on the removed column,
   but only if every consumer fix succeeded (deleting a Set whose consumer fix failed
   would dangle that consumer).

> This corrects the order the earlier inline Step 9 used (source-first). See the
> command's module docstring and open-items #23.

Each import is atomic (ALL_OR_NONE per object); a failure on one item does not roll
back others — every outcome is tracked in the results JSON for the Step 10 report.

### Build the plan JSON

Assemble the plan from the Step 4 scan + Step 6 selection. `modified_at` is the
`metadata_header.modified` snapshotted per object in Step 4 (`modified_at_scan[guid]`)
— apply-change uses it for the drift check. `backup_dir` is the directory Step 7
created (required — rollback safety).

```json
{
  "operation": "REMOVE",
  "backup_dir": "{backup_dir}",
  "source": {"guid": "{source_guid}", "type": "{source_type}", "name": "{source_name}",
             "modified_at": {source_modified_at}},
  "columns_to_remove": ["Legacy Region", "Old Segment"],
  "fix": [
    {"guid": "...", "type": "ANSWER",    "name": "...", "modified_at": ...},
    {"guid": "...", "type": "LIVEBOARD", "name": "...", "modified_at": ...,
     "viz_decisions": {"viz-id-1": "convert", "viz-id-2": "remove"}},
    {"guid": "...", "type": "MODEL",     "name": "...", "modified_at": ...}
  ],
  "delete": [
    {"guid": "...", "type": "ANSWER", "name": "...", "modified_at": ...}
  ],
  "sets": [
    {"guid": "...", "name": "...", "action": "DELETE_SAFE", "in_use_by": ["consumer-guid", ...]}
  ]
}
```

For **REPOINT**, replace `columns_to_remove` with the target and (optional) gap:

```json
{
  "operation": "REPOINT",
  "backup_dir": "{backup_dir}",
  "source": {"guid": "{source_guid}", "type": "{source_type}", "name": "{source_name}",
             "modified_at": {source_modified_at}},
  "target": {"guid": "{target_guid}", "name": "{target_name}"},
  "column_gap": ["Column present on source but absent on target"],
  "fix":  [ ... ],
  "delete": [],
  "sets": []
}
```

Plan field notes:

- **`fix[].action`** — set to `"REMOVE_CHART"` for a standalone Answer whose removed
  column sits on a chart x/y axis; apply-change converts it to TABLE_MODE before
  stripping. If omitted, apply-change auto-detects the chart role (`chart_role_for_answer`).
- **`fix[].viz_decisions`** — per-liveboard-viz map `{viz_id: "convert" | "remove"}`
  from the Step 6c decisions. Any viz not listed defaults to `convert` (CONVERT_TO_TABLE),
  which is always safe. Use `classify_liveboard_viz_roles` output from Step 6 to know
  which vizzes use the column on x/y and therefore need a decision surfaced.
- **`fix[].tml`** — optional inline TML body. Required only for `FEEDBACK` objects,
  which cannot be exported standalone (open-item #18) — pass the model's
  `nls_feedback` doc from the Step 4 `--associated` export. For every other type,
  omit it and apply-change exports the object fresh (after the drift check confirms it
  is unchanged since Step 4).
- **`source.source_obj_id`** (REPOINT, optional) — apply-change auto-probes the source
  for obj_id support; provide it only to skip the probe.

### Run apply-change

```bash
source ~/.zshenv
echo "$PLAN_JSON" | ts dependency apply-change --profile "{profile_name}"
```

**Source-drift hard stop.** If the source object drifted since Step 4, apply-change
aborts the ENTIRE run before touching anything (exit code 1, `"aborted": true` in the
output) — the Step 6 plan was computed against the old source and applying it could
remove columns that were re-purposed. Re-run the skill from Step 1 to rebuild the plan.

**Dependent drift** skips only that object (recorded under `skipped` with reason
`DRIFT_DETECTED`); the rest of the run proceeds.

### Read the results

apply-change prints a results JSON to stdout — this is the data for the Step 10 Change
Report. Per-object progress goes to stderr.

```json
{
  "operation": "REMOVE",
  "source": {"guid": "...", "name": "...", "type": "..."},
  "backup_dir": "...",
  "succeeded": [{"guid": "...", "name": "...", "type": "...", "phase": "fix|source",
                 "outcome": "SUCCESS|SUCCESS_WITH_WARNING", ...}],
  "failed":    [{"guid": "...", "name": "...", "phase": "...", "outcome": "FAIL_SILENT|FAIL_VERIFIED",
                 "error": "..."}],
  "deleted":   [{"guid": "...", "name": "...", "type": "..."}],
  "skipped":   [{"guid": "...", "name": "...", "reason": "DRIFT_DETECTED ..." | "set consumer ..."}]
}
```

Outcome meanings (from the import/verify matrix — open-item #15):

| `outcome` | Meaning |
|---|---|
| `SUCCESS` | API returned OK and re-export verified the change applied |
| `SUCCESS_WITH_WARNING` | API returned ERROR but the change actually applied — TS misreported (open-item #15). Treated as success. |
| `FAIL_SILENT` | API returned OK but the change did NOT apply — silent rejection |
| `FAIL_VERIFIED` | API returned ERROR and the change did not apply — genuine failure |

Carry `succeeded` / `failed` / `deleted` / `skipped` straight into the Step 10 Change
Report.

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

**Rollback — `ts dependency rollback`:**

Map the menu choice to the command flags and run it against `{backup_dir}`. The command
reads the manifest, restores objects in dependency-safe order (dependents before source),
re-imports DELETE-intent objects as NEW objects (new GUIDs, `guid:` stripped), and updates
every other object in place at its original GUID.

```python
import subprocess, json

# Map the Step 11 menu choice to rollback flags:
#   A → (no --only)      restore everything (updates AND deletes)
#   U → --only updates   in-place updates only
#   D → --only deletes   re-import deleted objects only
#   S → --guid <g> per selected object (repeatable)
flags = ""
if   choice == "U": flags = "--only updates"
elif choice == "D": flags = "--only deletes"
elif choice == "S": flags = " ".join(f"--guid {g}" for g in selected_rollback_guids)

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts dependency rollback --backup-dir '{backup_dir}' "
     f"{flags} --profile '{profile_name}'"],
    capture_output=True, text=True,
)
rollback_results = (json.loads(result.stdout) if result.stdout.strip()
                    else {"succeeded": [], "failed": [], "new_guids": {}})
```

Show rollback results. If `new_guids` is non-empty, surface the `old_guid → new_guid`
mapping table so the user can manually reattach any external references (restored deletes
always receive new GUIDs). If any entries are in `failed`, give the user the backup file
path (from the manifest) for manual restoration via the ThoughtSpot UI TML editor.

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts auth whoami` returns 401 | Token expired — follow the refresh steps in `/ts-profile-thoughtspot` |
| Import returns 403 / UNAUTHORIZED | User lacks edit access on the object — skip it, note in report; backup available |
| Import: `column_id not found` in dependent | Column reference format may differ from display name — see open-items.md #2 |
| Import: `search_query` validation error | The `search_query` still references a removed column — `sanitize_search_query()` may have missed a token. Check for bracket-format variants like `[TABLE::col]` and strip manually |
| Import: join condition references removed column | `source_affected_joins` detection in Step 4 may have missed a join — check `model_tables[].joins_with[].on` for the column name and remove the join entry manually |
| Liveboard import fails after REMOVE_CHART decision | A viz ID in the plan's `viz_decisions` may not match `visualizations[].id` — export the liveboard TML and compare the `viz_decisions` keys to each `visualizations[].id` |
| Import: model already exists with same name | The source export's `guid:` line may be missing — re-run `ts tml export {guid}` and confirm the top-level `guid:` is present before retrying |
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
| 1.4.0 | 2026-07-08 | **Step 9 apply is now the codified `ts dependency apply-change` command** (BL-083 PR2). The ~1,060 lines of inline drift/delete/mutate/import/verify/set-delete pseudocode are replaced by a single plan-JSON-driven command; Step 9 now builds the plan and reads back a results JSON. Deterministic decisions (drift, obj_id derivation, the import/verify outcome matrix, post-import verification, 9c ordering, the set-delete consumer guard, and REMOVE_CHART-vs-REMOVE_COLUMN chart-axis-role classification) are extracted to tested `ts_cli/dependency/apply.py`. **Latent-bug fix:** the corrected execution order is deletes → dependents → source → sets (source LAST) — the old section bodies ran source-first, which error 14544 (“Deleted columns have dependents”) would reject whenever a dependent still referenced the column. Live-verified on se-thoughtspot; the test surfaced and fixed a mutation gap — **rollback now restores ROOT-first** (source table before dependents — one-pass, was two, open-item #25); the model-fix now strips **aliased** base columns matched by `column_id`/formula-expr, not just `name` (open-item #24). Chart-role surfacing in `ts metadata report` (open-item #22) and the mandatory live test of the corrected ordering (open-item #23) are follow-ups. Requires ts-cli v0.41.0. |
| 1.3.0 | 2026-07-08 | **Step 7 backup and Step 11 rollback now call codified CLI commands** (BL-083 PR1). Step 7's inline export loop is replaced by `ts dependency backup` (builds a plan JSON → exports source + fix/delete dependents → writes per-object files + `manifest.json`; collects all exports first and writes nothing on any failure). Step 11's inline `rollback_objects` is replaced by `ts dependency rollback --backup-dir` (restores dependents-before-source; re-imports DELETE-intent objects as new GUIDs). The pure REMOVE/REPOINT TML transforms are now available as `ts dependency mutate` (extracted to `ts_cli/dependency/mutate.py` with full unit tests; fixes two latent bugs — an always-empty formula-name scrub set, and an Answer duplicate-`guid:` YAML break). Requires ts-cli v0.39.0. Step 9's drift/import/verify/delete orchestration stays inline pending the `ts dependency apply-change` follow-up (BL-083 PR2). |
| 1.2.0 | 2026-07-03 | **Step 4 scope filter now uses `matched_columns[]`.** `ts metadata report`'s dependents now carry a `matched_columns` field (populated by `ts_cli.report.classifier.build_matched_columns_map` from the deep RLS/join/alias/AI-surface/alert probes) — the Step 4 "Filtering by scope" table was filtering on `risk.reason` text, which is always a fixed literal and never names a column, so the filter could never match (2026-07 audit finding). **Step 6b / delete policy line corrected** — both no longer claim `ts metadata delete` "is currently broken" and call raw v2; they now name `ts metadata delete` directly, matching Step 9a (verified 2026-05-11) and removing a stale instruction that could have led an executor to hand-roll a `requests` call. |
| 1.1.0 | 2026-06-09 | **Repoint: obj_id-based references with fqn fallback.** Step 9 now detects `obj_id` support via `export_options` flags and prefers obj_id-based model_table references over fqn to avoid VERSION_CONFLICT (error 14009) on some TS builds (open-item #23). New `repoint_model()` function handles model_tables obj_id/name/joins/column_id/formula swaps. `repoint_answer()` and `repoint_view()` also support obj_id-first matching. **Backup location prompt** — Step 7 now asks the user where to save backups (current directory, /tmp, or custom path) instead of hardcoding /tmp. Requires ts-cli v0.8.0 (`--include-obj-id`, `--include-obj-id-ref`, `--no-guid` flags). |
| 1.0.0 | 2026-04-27 | Initial release. Three modes: **Audit** (read-only blast-radius report), **Remove** (drop one or more columns and clean up dependents), **Repoint** (redirect Answers/Liveboards to a different Model/View/Table with column-gap detection). Step 4 dep walk uses the v2 metadata/search dependents API (`ts metadata dependents`) with **alias propagation** — per-Model/View aliases for the target column are extracted at scan time so Answers/Liveboards/Sets that reference renamed columns (e.g. `ZIPCODE` → `Customer Zipcode`) are caught. **STOP-condition** handling for inaccessible dependents (v2 `hasInaccessibleDependents` flag), source-table RLS rules, model-level join conditions referencing the column (open-items.md #4), model-level filters (#12), and chart-axis conflicts. Step 5 impact report drives the Scan Coverage block from the canonical `references/dependency-types.md` status table via `references/build_coverage.py`. Steps 7 / 8 require typed "DELETE" / "ACCEPT INCOMPLETE IMPACT" confirmations and take a TML backup before any change is applied. Step 9 wraps every import with **post-import verification** (`import_and_verify`) — re-exports the TML and confirms the change actually applied, since TS sometimes returns status_code=ERROR while applying the change anyway (open-item #15). **Object-version drift detection** captures `metadata_header.modified` at scan time and aborts the per-object change (or the entire run, if the source drifted) when the timestamp moves between scan and apply. Step 11 supports rollback for both updates and deletes. RENAME mode is intentionally not supported on this build — see the rationale at the top of SKILL.md. |
