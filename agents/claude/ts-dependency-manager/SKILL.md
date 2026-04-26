---
name: ts-dependency-manager
description: Safely remove or rename columns and repoint objects across a ThoughtSpot environment — generates a risk-rated impact report, backs up TML before any change, and supports full rollback.
---

# ThoughtSpot: Dependency Manager

Safely make changes that affect dependent objects in ThoughtSpot. Before any modification,
this skill generates a full impact report with hyperlinks and risk ratings, lets you choose
exactly what to change, takes TML backups, and provides rollback capability.

**Supported operations:**

- **Remove columns** — remove one or more columns from a connection table or Model, then
  clean up all dependent Answers, Liveboards, and Models that reference them
- **Rename a column** — rename a column in a connection table or Model and propagate the
  rename to all dependent objects
- **Repoint objects** — redirect Answers or Liveboards to a different table or Model,
  with column-gap detection and mapping

**When to use this skill:**

- A database column has been deprecated and needs to be removed from ThoughtSpot cleanly
- A column has been renamed in the data warehouse and ThoughtSpot objects need updating
- Answers or Liveboards need to be moved to a new or restructured Model
- You want to audit what would be affected before making a structural change

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/dependency-types.md](references/dependency-types.md) | Status of every dependency type (Implementable / Partial / Manual / GUID-stable / Informational), the dependency hierarchy the skill walks in Step 4, and a worked sample of the Step 5 impact report — read before adding new dep handling or changing how Step 4 walks the graph |
| [references/open-items.md](references/open-items.md) | Dependency API, search_query and join constraints, Alert scan, RLS/security/aliasing open items — read before implementing Steps 4 and 9 |
| [~/.claude/skills/ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | Model TML structure — column and formula placement rules, self-validation checklist |
| [~/.claude/shared/schemas/thoughtspot-answer-tml.md](~/.claude/shared/schemas/thoughtspot-answer-tml.md) | Answer TML structure — answer_columns, cohorts (sets), chart, table, search_query layout |
| [~/.claude/shared/schemas/thoughtspot-sets-tml.md](~/.claude/shared/schemas/thoughtspot-sets-tml.md) | Set (cohort) TML structure — reusable vs answer-level, anchor_column_id, bin/group/query types |
| [~/.claude/shared/schemas/thoughtspot-liveboard-tml.md](~/.claude/shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure — visualizations, filters, layout |
| [~/.claude/shared/schemas/thoughtspot-view-tml.md](~/.claude/shared/schemas/thoughtspot-view-tml.md) | View TML structure — view_columns, joins, table_paths, search_query |
| [~/.claude/shared/schemas/thoughtspot-alert-tml.md](~/.claude/shared/schemas/thoughtspot-alert-tml.md) | Alert TML structure — metric_id references, personalised_view_info filters |
| [~/.claude/shared/schemas/thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md) | Feedback/coaching TML structure — search_tokens and formula_info column references |
| [~/.claude/shared/schemas/thoughtspot-table-tml.md](~/.claude/shared/schemas/thoughtspot-table-tml.md) | Connection table TML structure — column definitions |

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
**ts-dependency-manager** — safely remove, rename, or repoint columns across a ThoughtSpot environment, with a full impact report and TML backup before any change is made.

### A. Steps

  1.  Authenticate ......................................... auto
  2.  Choose mode (Audit | Remove | Rename | Repoint) ...... you choose
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
       /  │  \     │ │
      /   │   ╲    │ │
     /    │    ╲   │ │
    ▼     ▼     ▼  ▼ ▼
 [ANSWER] │  [SET]   ┊
     │    │     │    ┊  (model-attached)
     │    │     ▼    ┊
     │    │  [ANSWER consumers via Set]
     │    │
     ▼    ▼
 [LIVEBOARD]
     │   │  ............→ [<MODEL>.column_alias]
     │   │       (#10 — retrieval unverified)
     │   │
     │   └ ............→ [nls_feedback]   (#18 partial via --associated)
     │
     ├ ............→ [monitor_alert]   (#6 verified via --associated)
     ▼
[SCHEDULE]   (informational only — column-agnostic)
```

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
[ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) for the
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
    N  Rename a column   — rename and propagate the new name to every dependent
    P  Repoint objects   — redirect Answers / Liveboards to a different
                           Model, View, or connection Table

Enter A / R / N / P:
```

Save `{operation}` (`AUDIT` / `REMOVE` / `RENAME` / `REPOINT`) and branch to the
appropriate Step 3 sub-section.

**Audit (A) is read-only.** No backups taken, no objects modified. The audit produces
the same report files as R/N/P (impact_plan.json, impact_report.csv, dependency_tree.txt,
dependency.mmd) and exits cleanly after Step 5. The user can re-run with R/N/P later
once they've planned their change.

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

## Step 3-N — Identify Column to Rename

Use the same object search and TML export as Step 3-R. After showing the column list, ask:

```
Which column would you like to rename? Enter a number:
```

Then ask:

```
New name for "{current_col_name}":
```

Validate that the new name does not already exist in the object's column list. If it does:

```
A column named "{new_col_name}" already exists in "{source_name}".
Please enter a different name:
```

Save `{current_col_name}`, `{new_col_name}`, `{source_guid}`, `{source_name}`, `{source_type}`.

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

## Step 4 — Dependency Discovery (v2 API + alias propagation)

Walk only the dependents — do **not** enumerate every Answer/Liveboard/Model/View in
the instance. The v2 dependents API returns just what references the source.

**Performance budget — strict.** A bulk scan over 10k+ objects takes 30+ minutes and
fails on large instances. The v2 dependents call returns the full transitive list in
one HTTP request (~2-3s on Cloud). The skill MUST follow this path; the legacy bulk-scan
approach is removed. Verified working on Cloud and Software 7.1.1+ (open item #1).

The discovery has three logical phases:

1. **Direct dependents** — single v2 dependents call on `source_guid` returns Models,
   Views, Answers, Liveboards, Sets, and Feedback that reference the source
2. **Alias chain** — for each Model/View dependent, extract what alias the target
   column is exposed as (e.g. `ZIPCODE` → `Customer Zipcode`). Downstream objects
   reference the alias, never the base name, so this step is mandatory for correctness
3. **Alias-aware filtering** — for each Answer/Liveboard/Set candidate, match against
   the alias of the Model it queries (resolved via `tables[].fqn` for Answers/vizzes;
   `cohort.worksheet.fqn` for Sets), not against the base name

This catches references that would be invisible to a naive base-name scan (~30% miss
rate in test environments where Models commonly rename columns).

```python
import json, subprocess

def v2_dependents(guid, type_str, profile_name):
    """Returns the dependents bucket dict {LOGICAL_TABLE: [...], QUESTION_ANSWER_BOOK: [...],
    PINBOARD_ANSWER_BOOK: [...], COHORT: [...], FEEDBACK: [...]}.

    Wraps `ts metadata dependents <guid> --type <type> --raw --profile <name>`
    (ts-cli >= 0.4.0). The CLI handles auth/token caching; we ask for `--raw`
    here because we want the bucket structure for the alias-aware classification
    below. See `tools/ts-cli/README.md` for the flat output shape used elsewhere.
    """
    r = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts metadata dependents {guid} "
         f"--type {type_str} --raw --profile '{profile_name}'"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    arr = json.loads(r.stdout)
    if not arr:
        return {}
    item = arr[0]
    return ((item.get("dependent_objects") or {}).get("dependents") or {}).get(guid) or {}

def tml_export_one(guid, profile_name):
    """Export a single object's TML. Returns the parsed item dict, or None on failure."""
    r = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml export {guid} --profile '{profile_name}' --fqn --parse"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        items = json.loads(r.stdout)
        return items[0] if items else None
    except json.JSONDecodeError:
        return None

# === Phase 1: direct dependents ===========================================
src_buckets = v2_dependents(source_guid, "LOGICAL_TABLE", profile_name)
print(f"Source dependent buckets: {[(k, len(v)) for k, v in src_buckets.items()]}")

candidate_models   = src_buckets.get("LOGICAL_TABLE",         []) or []
candidate_answers  = src_buckets.get("QUESTION_ANSWER_BOOK",  []) or []
candidate_lbs      = src_buckets.get("PINBOARD_ANSWER_BOOK",  []) or []
candidate_cohorts  = src_buckets.get("COHORT",                []) or []
direct_feedback    = src_buckets.get("FEEDBACK",              []) or []

# Track totals for the Scan Coverage section in the impact report
scan_totals = {
    "method":            "v2 metadata/search include_dependent_objects",
    "endpoint_calls":    1,                            # incremented as we walk
    "candidate_models":  len(candidate_models),
    "candidate_answers": len(candidate_answers),
    "candidate_lbs":     len(candidate_lbs),
    "candidate_cohorts": len(candidate_cohorts),
}

# === Phase 2: alias chain — extract aliases per Model/View ================
# alias_map[model_or_view_guid] = {
#     "name": str, "type": "MODEL"|"VIEW"|"TABLE", "owner": str,
#     "exposed_as": set[str],     # the alias names the target column is known by
#     "tml": dict,                # the parsed TML
# }
def extract_aliases(section, target_cols):
    """Find what each target column is renamed to in this Model/View.
    Returns set of alias names (display names used downstream)."""
    aliases = set()
    # Models/Worksheets: columns[].column_id like "TABLE::COL"
    for col in section.get("columns", []) or []:
        cid = col.get("column_id", "") or ""
        for tc in target_cols:
            if cid.endswith(f"::{tc}") or cid == tc:
                aliases.add(col.get("name", tc))
    # Views: view_columns[] reference base by name or via search_output_column
    for vc in section.get("view_columns", []) or []:
        for tc in target_cols:
            if vc.get("name") == tc or vc.get("search_output_column") == tc:
                aliases.add(vc.get("name", tc))
    # Views: search_query may reference [TC] tokens directly
    sq = section.get("search_query", "") or ""
    for tc in target_cols:
        if f"[{tc}]" in sq:
            aliases.add(tc)
    # Formulas referencing target columns expose the formula column's name as an alias
    for f in section.get("formulas", []) or []:
        expr = f.get("expr", "") or ""
        if any(f"[{tc}]" in expr for tc in target_cols):
            for col in section.get("columns", []) or []:
                if col.get("formula_id") == f.get("id"):
                    aliases.add(col.get("name"))
    return aliases

target_cols = (set(columns_to_remove) if operation == "REMOVE"
               else {current_col_name} if operation == "RENAME"
               else set(column_gap or []))   # REPOINT
alias_map = {
    source_guid: {
        "name": source_name, "type": source_type, "owner": "?",
        "exposed_as": set(target_cols), "tml": None,
    },
}

for cm in candidate_models:
    item = tml_export_one(cm["id"], profile_name)
    if not item:
        continue
    tml = item["tml"]
    # Determine real type from the TML body
    if   "model"   in tml or "worksheet" in tml: real_type = "MODEL"
    elif "view"    in tml:                       real_type = "VIEW"
    elif "table"   in tml:                       real_type = "TABLE"
    else:                                        real_type = item.get("type", "MODEL").upper()
    section = (tml.get("model") or tml.get("worksheet")
               or tml.get("view") or tml.get("table") or {})
    aliases = extract_aliases(section, target_cols)
    if not aliases:
        # The Model joins to the source but doesn't expose the target column
        # (e.g. only uses CUSTOMER_ID from this table). Skip — nothing to do.
        continue
    alias_map[cm["id"]] = {
        "name": cm.get("name", "?"),
        "type": real_type,
        "owner": cm.get("authorDisplayName", "?"),
        "exposed_as": aliases,
        "tml": tml,
    }
    print(f"  [{real_type:5}] {cm.get('name','?')[:50]:50}  "
          f"exposes {sorted(target_cols)} as: {sorted(aliases)}")

all_aliases = set()
for v in alias_map.values():
    all_aliases |= v["exposed_as"]

# === Phase 3: alias-aware filtering of Answers, Liveboards, Sets ==========
def find_parent_model(tml, alias_map):
    """Identify which Model/View this Answer/Liveboard queries.
    Returns the GUID (matches alias_map keys), or None if not in our chain.
    """
    a = tml.get("answer") or {}
    for t in a.get("tables", []) or []:
        if t.get("fqn") in alias_map:
            return t.get("fqn")
    lb = tml.get("liveboard") or {}
    for v in lb.get("visualizations", []) or []:
        for t in (v.get("answer", {}).get("tables") or []):
            if t.get("fqn") in alias_map:
                return t.get("fqn")
    return None

dependents = []   # final list with parent_guid set correctly

# 3a — Answers
for ca in candidate_answers:
    item = tml_export_one(ca["id"], profile_name)
    if not item:
        continue
    tml = item["tml"]
    parent_guid = find_parent_model(tml, alias_map) or source_guid
    applicable = (alias_map[parent_guid]["exposed_as"]
                  if parent_guid in alias_map else all_aliases)
    body = json.dumps(tml)
    affected = sorted({a for a in applicable if a in body})
    if not affected:
        continue
    dependents.append({
        "guid":        ca["id"],
        "name":        ca.get("name", "?"),
        "type":        "ANSWER",
        "owner":       ca.get("authorDisplayName", "?"),
        "parent_guid": parent_guid,                 # the Model it queries
        "affected":    affected,
        "tml":         tml,
    })

# 3b — Liveboards (per-viz scoping)
for cl in candidate_lbs:
    item = tml_export_one(cl["id"], profile_name)
    if not item:
        continue
    tml = item["tml"]
    parent_guid = find_parent_model(tml, alias_map) or source_guid
    body = json.dumps(tml)
    # Use the union of aliases across vizzes (a liveboard may use multiple Models)
    applicable = set()
    lb = tml.get("liveboard") or {}
    for v in lb.get("visualizations", []) or []:
        for t in (v.get("answer", {}).get("tables") or []):
            if t.get("fqn") in alias_map:
                applicable |= alias_map[t.get("fqn")]["exposed_as"]
    if not applicable:
        applicable = all_aliases
    affected = sorted({a for a in applicable if a in body})
    if not affected:
        continue
    dependents.append({
        "guid":        cl["id"],
        "name":        cl.get("name", "?"),
        "type":        "LIVEBOARD",
        "owner":       cl.get("authorDisplayName", "?"),
        "parent_guid": parent_guid,
        "affected":    affected,
        "tml":         tml,
    })

# 3c — Promote Models/Views from alias_map (excluding source) into dependents
for guid, info in alias_map.items():
    if guid == source_guid:
        continue
    dependents.append({
        "guid":        guid,
        "name":        info["name"],
        "type":        info["type"],            # MODEL or VIEW
        "owner":       info["owner"],
        "parent_guid": source_guid,             # Models/Views attach to source
        "affected":    sorted(info["exposed_as"]),
        "tml":         info["tml"],
    })

**Feedback (coaching):** Export the source Model's associated TML to check for
`nls_feedback` items that reference the affected columns. These are appended to the
dependents list with type `"FEEDBACK"` and shown as LOW-risk informational items.

```python
# For REMOVE/RENAME on a Model: also check feedback items in --associated export
if source_type in ("MODEL", "WORKSHEET") and operation in ("REMOVE", "RENAME"):
    assoc_result = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml export {source_guid} "
         f"--profile '{profile_name}' --fqn --associated --parse"],
        capture_output=True, text=True,
    )
    if assoc_result.returncode == 0:
        for item in json.loads(assoc_result.stdout):
            if item["type"] == "nls_feedback":
                # Check if any feedback entry references the target columns
                target = columns_to_remove if operation == "REMOVE" else [current_col_name]
                if any(col in json.dumps(item["tml"]) for col in target):
                    dependents.append({
                        "guid":    source_guid,   # feedback shares the model GUID
                        "name":    f"Coaching for {source_name}",
                        "type":    "FEEDBACK",
                        "owner":   "N/A",
                        "tml":     item["tml"],
                    })
```

**Alert scan:** See [references/open-items.md](references/open-items.md) #6. Until
that item is verified, note in the impact report that Alerts referencing affected
Answers or Liveboards cannot be automatically detected and should be reviewed manually.

For **REMOVE** and **RENAME** operations, also identify which specific columns within each
dependent are affected (so the impact report can show them):

```python
def find_affected_columns(tml_dict, target_columns):
    """Find which of target_columns appear in the TML object."""
    tml_str = json.dumps(tml_dict)
    return [col for col in target_columns if col in tml_str]

for dep in dependents:
    if operation == "REMOVE":
        dep["affected"] = find_affected_columns(dep["tml"], columns_to_remove)
    elif operation == "RENAME":
        dep["affected"] = [current_col_name] if current_col_name in json.dumps(dep["tml"]) else []
    else:  # REPOINT
        dep["affected"] = list(column_gap) if column_gap else []
```

**Classify chart roles for each affected column (REMOVE operation — Rules 3–5):**

Chart columns have three action types depending on how they are used:
- `REMOVE_CHART` — column is on X or Y axis (removing it breaks the chart; requires per-viz user decision in Step 6)
- `REMOVE_COLOR_BINDING` — column is a color/size/shape binding (safe to strip the binding; chart remains intact)
- `REMOVE_COLUMN` — column is not visualised on any axis, or only in the table view (safe to remove)

Liveboard-level filters that reference the column can always be removed safely.

```python
def classify_chart_role(answer_section, col_name):
    """
    Returns: 'X_AXIS' | 'Y_AXIS' | 'COLOR_BINDING' | 'NOT_VISUALISED' | 'NOT_IN_CHART'
    - X_AXIS / Y_AXIS   → REMOVE_CHART required (cannot auto-fix; Step 6 per-viz decision)
    - COLOR_BINDING     → REMOVE_COLOR_BINDING (strip binding; chart stays intact)
    - NOT_VISUALISED    → REMOVE_COLUMN (in chart_columns[] but not mapped to any axis)
    - NOT_IN_CHART      → REMOVE_COLUMN (only in answer_columns/table, or not present)
    """
    chart = answer_section.get("chart", {})
    in_chart = any(
        c.get("column_id") == col_name for c in chart.get("chart_columns", [])
    )
    if not in_chart:
        return "NOT_IN_CHART"
    for axis in chart.get("axis_configs", []):
        if col_name in axis.get("x", []):
            return "X_AXIS"
        if col_name in axis.get("y", []):
            return "Y_AXIS"
        for role in ("color", "size", "shape"):
            if col_name in axis.get(role, []):
                return "COLOR_BINDING"
    return "NOT_VISUALISED"

if operation == "REMOVE":
    for dep in dependents:
        if dep["type"] == "ANSWER" and dep.get("affected"):
            answer_section = dep["tml"].get("answer", {})
            roles = [classify_chart_role(answer_section, col) for col in dep["affected"]]
            if "X_AXIS" in roles or "Y_AXIS" in roles:
                dep["action"] = "REMOVE_CHART"   # cannot auto-fix standalone answer
            elif "COLOR_BINDING" in roles:
                dep["action"] = "REMOVE_COLOR_BINDING"
            else:
                dep["action"] = "REMOVE_COLUMN"

        elif dep["type"] == "LIVEBOARD" and dep.get("affected"):
            liveboard = dep["tml"].get("liveboard", {})
            dep["viz_actions"] = {}  # viz_id → "REMOVE_COLUMN" | "REMOVE_COLOR_BINDING" | "REMOVE_CHART"

            # Liveboard-level filters (Rule 1): safe to remove filter entries for removed columns
            dep["filter_cols"] = list({
                col for col in dep["affected"]
                for filt in liveboard.get("filters", [])
                if col in filt.get("column", [])
            })

            # Per-viz classification (Rules 3–5)
            for viz in liveboard.get("visualizations", []):
                answer = viz.get("answer", {})
                # Vizzes can query the source table OR any Model/View in alias_map.
                # We act on a viz only if its tables[].fqn is in our alias chain.
                viz_table_fqns = {t.get("fqn") for t in answer.get("tables", []) or []}
                if not (viz_table_fqns & set(alias_map.keys())):
                    continue
                viz_id = viz.get("id", "")
                # Use the alias set of the Model/View this viz actually queries
                viz_aliases = set()
                for fqn in viz_table_fqns:
                    if fqn in alias_map:
                        viz_aliases |= alias_map[fqn]["exposed_as"]
                roles = [classify_chart_role(answer, col) for col in viz_aliases & set(dep["affected"])]
                if "X_AXIS" in roles or "Y_AXIS" in roles:
                    dep["viz_actions"][viz_id] = "REMOVE_CHART"
                elif "COLOR_BINDING" in roles:
                    dep["viz_actions"][viz_id] = "REMOVE_COLOR_BINDING"
                else:
                    dep["viz_actions"][viz_id] = "REMOVE_COLUMN"

            all_viz_actions = list(dep["viz_actions"].values())
            if "REMOVE_CHART" in all_viz_actions:
                dep["action"] = "REMOVE_CHART"
            elif "REMOVE_COLOR_BINDING" in all_viz_actions:
                dep["action"] = "REMOVE_COLOR_BINDING"
            else:
                dep["action"] = "REMOVE_COLUMN"
        else:
            dep["action"] = "UPDATE"  # RENAME, REPOINT, VIEW, MODEL, FEEDBACK
```

**Check for join conditions in the source object that reference the removed column**
(REMOVE operation only). A join condition referencing a removed column causes a fatal
import error. This is a **STOP condition** — detect the joins here and require explicit
user acknowledgment in Step 5 before proceeding.

```python
source_affected_joins = []
if operation == "REMOVE" and source_type in ("MODEL", "WORKSHEET"):
    source_section = source_export_item["tml"].get("model") or \
                     source_export_item["tml"].get("worksheet", {})
    for tbl in source_section.get("model_tables", []):
        for join in tbl.get("joins_with", []):
            if any(col in join.get("on", "") for col in columns_to_remove):
                source_affected_joins.append({
                    "table": tbl.get("name", "?"),
                    "join":  join.get("name", "unnamed"),
                    "on":    join.get("on", ""),
                })
```

**Scan for reusable Sets (cohorts) that reference the affected column(s):**

Reusable sets have `config.anchor_column_id` pointing to the column they operate on.
When that column is removed, the set must be deleted. When renamed, it must be updated.
Answer-level sets (inline `answer.cohorts[]`) are handled inside `remove_columns_from_answer()`
later; this scan only finds standalone reusable sets.

"Pinned Answers" are Answers embedded in Liveboard visualizations (`visualizations[].answer`).
They are already covered by the Liveboard dependency scan above — no separate scan needed.

Read [references/open-items.md](references/open-items.md) #11 before implementing this scan.
**Important — verified 2026-04-26 on champ-staging:** `COHORT` is NOT a valid
`SearchMetadataType` enum value (the v2 API returns 400). Sets are returned in v2 dependents
responses under their own **`COHORT` bucket** in the source's response, and Sets are queryable
by GUID with `type: LOGICAL_COLUMN`.

The correct discovery for sets is:

1. **Read the `COHORT` bucket** from the source's v2 dependents response (alongside
   `LOGICAL_TABLE`, `QUESTION_ANSWER_BOOK`, `PINBOARD_ANSWER_BOOK`, `FEEDBACK`)
2. **For each Set found**, query its own dependents:
   `metadata/search` with `{type: LOGICAL_COLUMN, identifier: set_guid, include_dependent_objects: true}`
3. **Merge the Set's QUESTION_ANSWER_BOOK and PINBOARD_ANSWER_BOOK consumers** into the
   global dependent list — these consumers reference the column transitively through the Set
   and would be missed by a table-level + recursive-Model walk

Both the Set itself AND its consumers are hard blockers for source removal — TS error 14544
will list them all if any still reference the column at the time of source change.

```python
affected_sets = []

# Read sets from the v2 dependents response's COHORT bucket (already populated as
# `candidate_cohorts` in Phase 1 above). Apply alias-aware filtering: a set "matches"
# if any alias of the target column (the alias exposed by the set's parent Model) is
# found in the cohort body.

if operation in ("REMOVE", "RENAME"):
    for set_meta in candidate_cohorts:
        set_guid = set_meta["id"]
        item = tml_export_one(set_guid, profile_name)
        if not item:
            continue
        set_tml = item["tml"]
        cohort = set_tml.get("cohort", {}) or {}
        config = cohort.get("config", {}) or {}

        # The aliases applicable to this set are the ones exposed by its parent Model
        parent_fqn = (cohort.get("worksheet", {}) or {}).get("fqn")
        applicable_aliases = (alias_map[parent_fqn]["exposed_as"]
                              if parent_fqn in alias_map else all_aliases)

        # Match: anchor matches an alias  → DELETE
        #        alias appears in body    → FIX
        anchor       = config.get("anchor_column_id", "")
        anchor_match = anchor in applicable_aliases
        body_str     = json.dumps(cohort)
        col_in_body  = any(a in body_str for a in applicable_aliases)
        if not (anchor_match or col_in_body):
            continue

        # Find this Set's consumers (Answers/Liveboards). Each consumer references the
        # column transitively through the Set; we re-parent any matching Answer/Liveboard
        # already in `dependents` to make the Set its parent in the tree.
        consumers = []
        try:
            cohort_buckets = v2_dependents(set_guid, "LOGICAL_COLUMN", profile_name)
            scan_totals["endpoint_calls"] += 1
            for type_key in ("QUESTION_ANSWER_BOOK", "PINBOARD_ANSWER_BOOK"):
                for it in (cohort_buckets.get(type_key) or []):
                    consumers.append({
                        "guid":    it["id"],
                        "name":    it.get("name", ""),
                        "type":    "ANSWER" if type_key == "QUESTION_ANSWER_BOOK" else "LIVEBOARD",
                        "owner":   it.get("authorDisplayName", "?"),
                        "via_set": set_guid,
                    })
        except Exception as e:
            print(f"  Note: Could not query consumers of set {set_guid}: {e}")

        if operation == "REMOVE":
            default_action = "DELETE" if anchor_match else "FIX"
        else:  # RENAME
            default_action = "UPDATE_SET"

        affected_sets.append({
            "guid":           set_guid,
            "name":           set_meta.get("name") or cohort.get("name", "Unknown"),
            "type":           "SET",
            "owner":          set_meta.get("authorDisplayName", "Unknown"),
            "parent_guid":    parent_fqn or source_guid,   # set attaches under its Model
            "anchor_column":  anchor,
            "anchor_match":   anchor_match,
            "col_in_body":    col_in_body,
            "affected":       sorted({a for a in applicable_aliases if a in body_str}),
            "tml":            set_tml,
            "consumers":      consumers,
            "in_use_by":      [c["guid"] for c in consumers],
            "default_action": default_action,
        })

        # Re-parent any consumer already in `dependents` so the tree shows
        # ANSWER/LIVEBOARD under the SET, not under the source table or Model
        consumer_guids = {c["guid"] for c in consumers}
        for d in dependents:
            if d["guid"] in consumer_guids:
                d["parent_guid"] = set_guid

        # Add brand-new consumers (not already in `dependents`) — these are transitive
        # deps that didn't show up under the source's direct dependents
        existing_guids = {d["guid"] for d in dependents}
        for c in consumers:
            if c["guid"] in existing_guids:
                continue
            item = tml_export_one(c["guid"], profile_name)
            c["tml"]      = item["tml"] if item else {}
            c["affected"] = sorted(applicable_aliases)
            c["parent_guid"] = set_guid
            dependents.append(c)
```

**Open-item #11 outcome:** the `COHORT` enum value is not valid for v2 search; replace with
the `LOGICAL_COLUMN`-typed direct dependents query above. Update the open-item to VERIFIED.

If no dependents are found, inform the user:

```
No dependent objects found that reference "{source_name}".

  The change can be made to the source object only — no other ThoughtSpot objects
  will be affected.

Proceed with the change? (Y / N):
```

If Y, skip to Step 7 (backup the source, then apply changes at Step 9a only). If N, stop.

---

## Step 5 — Impact Report

Assign risk ratings:

```python
def risk_rating(dep):
    if dep["type"] in ("LIVEBOARD", "MODEL"):
        return "HIGH"    # Liveboards are shared/published; broken Models cascade to all dependents
    if dep["type"] == "VIEW":
        return "HIGH"    # Views are data sources — a broken View breaks all Answers built on it
    if dep["type"] == "SET":
        return "MEDIUM" if dep.get("in_use_by") else "LOW"  # in-use sets affect consumers
    if dep["type"] == "FEEDBACK":
        return "LOW"     # Stale coaching entries don't break functionality
    return "MEDIUM"      # Answers affect individual users or specific consumers
```

Display the impact report. The report has four parts (in order):

1. **Header + STOP CONDITIONS block** — fixed-width plaintext for the banner; the STOP
   CONDITIONS callout uses a bullet list
2. **Dependent object tables** — render as **markdown tables** (one per object category) so
   names are clickable links in any markdown viewer (Claude Code IDE, GitHub, VSCode preview,
   stakeholder docs). Every row has `Type | Name (link) | GUID | Owner | Action`. The full
   GUID goes in the row (not truncated) so it's copy-pasteable
3. **Dependency tree (text)** — indented hierarchy with 4-line labels per node:
   `[TYPE]` / `Name: ...` / `GUID: ...` / `Owner: ...`. Connection (parent of source) is at
   the root. Sets/Cohorts MUST attach under the Model they're anchored on (read
   `cohort.worksheet.fqn` from the cohort TML to find the parent), not under the source table
4. **Dependency DAG (mermaid)** — a separate `dependency.mmd` file written to the report
   directory; reference it in the report rather than inlining the source. Sets attach to
   their Model in the DAG too. Each node carries the same 4-field label

If `source_affected_joins` is non-empty, show them as a STOP condition block (join removal
requires explicit user confirmation — it cannot be undone). If any dependents have
`action == "REMOVE_CHART"`, show them in the STOP CONDITIONS block too. Include an
ACTION column in every dependent table so the user can see what will happen to each object.

Before rendering, compute per-type found counts for the Scan Coverage section:

```python
found_counts = {
    "ANSWER":    sum(1 for d in dependents if d["type"] == "ANSWER"),
    "LIVEBOARD": sum(1 for d in dependents if d["type"] == "LIVEBOARD"),
    "VIEW":      sum(1 for d in dependents if d["type"] == "VIEW"),
    "MODEL":     sum(1 for d in dependents if d["type"] == "MODEL"),
    "SET":       len(affected_sets),
    "FEEDBACK":  sum(1 for d in dependents if d["type"] == "FEEDBACK"),
}
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 IMPACT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Source:   {source_name} ({source_type})
Change:   {change_description}

⛔  STOP CONDITIONS — REQUIRES CONFIRMATION   (only shown when non-empty)

   JOIN CONDITIONS IN SOURCE MODEL ({len(source_affected_joins)} join(s)):
   These joins in "{source_name}" reference the removed column and MUST be deleted
   for the model import to succeed. Removing joins permanently changes query behavior
   for all objects using these join paths.
     - Table: Orders_Fact  Join: Customer_to_Orders  ON: [FACT::Legacy_Region] = [...]

   CHART AXIS CONFLICTS ({count} visualization(s)):
   These chart visualizations use the removed column as a primary X or Y axis.
   Removing the column without removing the chart would break the visualization.
   You will choose an action for each in Step 6.
     - Q4 Sales Overview / Revenue Trend  (Y axis: Legacy Region)  [LIVEBOARD]
     - Sales by Region Q4                 (Y axis: Legacy Region)  [ANSWER — skip only]

{N} dependent object(s) found:
  {HIGH_count} HIGH   {MEDIUM_count} MEDIUM   {LOW_count} LOW
```

(Then close the plain-text banner block and switch to markdown for the tables. The IDE
renders the names below as clickable links.)

### Models / Views

| Risk | Type | Name | GUID | Owner | Action |
|---|---|---|---|---|---|
| HIGH | MODEL | [Customer 360 Model](https://yourcluster.thoughtspot.cloud/#/data/tables/{guid}) | `{guid}` | admin@co.com | UPDATE (join removed) |
| HIGH | VIEW  | [Regional Sales View](https://yourcluster.thoughtspot.cloud/#/data/tables/{guid}) | `{guid}` | jane@co.com | REMOVE_COLUMN |

### Answers / Liveboards

| Risk | Type | Name | GUID | Owner | Action |
|---|---|---|---|---|---|
| HIGH   | LIVEBOARD | [Q4 Sales Overview](https://yourcluster.thoughtspot.cloud/#/pinboard/{guid})    | `{guid}` | john@co.com | REMOVE_CHART (1 viz) |
| MEDIUM | ANSWER    | [Sales by Region Q4](https://yourcluster.thoughtspot.cloud/#/saved-answer/{guid}) | `{guid}` | john@co.com | REMOVE_CHART (manual) |
| MEDIUM | ANSWER    | [Revenue by Store](https://yourcluster.thoughtspot.cloud/#/saved-answer/{guid})   | `{guid}` | john@co.com | REMOVE_COLOR_BINDING |

### Sets (Cohorts)

| Risk | Name | GUID | Owner | Anchor column | Parent model | Action |
|---|---|---|---|---|---|---|
| MEDIUM | [Revenue Bins](https://yourcluster.thoughtspot.cloud/#/cohort/{guid})       | `{guid}` | john@co.com | Legacy Region | Customer 360 Model | DELETE (in use by 2 objects) |
| LOW    | [Old Region Groups](https://yourcluster.thoughtspot.cloud/#/cohort/{guid})  | `{guid}` | jane@co.com | Legacy Region | Customer 360 Model | DELETE (not in use — safe) |

Sets are always children of a Model (anchored via `cohort.worksheet.fqn`). Read that field
from the cohort TML and resolve the parent Model name + GUID before rendering the row.
Never link a Set directly under the source table — even if the v2 dependents API lists it
as a column-level dependent, its parent in the structural graph is its Model.

### Spotter feedback

| Risk | Name | GUID | Owner | Parent model |
|---|---|---|---|---|
| LOW | by customer zipcode                  | `{guid}` | damian.waldron | TEST_DEPENDENCY_MANAGEMENT |
| LOW | sum of quantity by customer zipcode  | `{guid}` | damian.waldron | TEST_DEPENDENCY_MANAGEMENT |

### Alerts (manual review required)

Alerts referencing affected Answers or Liveboards cannot be automatically detected via v2
dependents. After applying changes, manually review Alerts on the following:
  - [Q4 Sales Overview](https://yourcluster.thoughtspot.cloud/#/pinboard/{guid})
  - [Sales by Region Q4](https://yourcluster.thoughtspot.cloud/#/saved-answer/{guid})

### Dependency tree

```
[CONNECTION]
  Name:  {connection_name}
  GUID:  {connection_guid}
  Owner: {connection_owner}
│
└─ [TABLE] (source)
     Name:  {source_name}
     GUID:  {source_guid}
     Owner: {source_owner}
   │   └─ [RLS] {rls_rule_name} — internal reference to {column} (must be updated)
   │
   ├─ [MODEL]
   │    Name:  TEST_DEPENDENCY_MANAGEMENT
   │    GUID:  e5c84be6-ebbc-4ef0-9522-e124f0d29827
   │    Owner: damian.waldron
   │  ├─ [VIEW]
   │  │    Name:  TEST_DEPENDENCY_VIEW
   │  │    GUID:  91dd9901-9fb3-40d0-b127-cdca2eb0e400
   │  │    Owner: damian.waldron
   │  ├─ [ANSWER]                          ⚠ X-axis (manual)
   │  │    Name:  TEST_DEPENDENCY_ANSWER
   │  │    GUID:  f16015e6-...
   │  │    Owner: damian.waldron
   │  └─ [FEEDBACK]
   │       Name:  by customer zipcode
   │       GUID:  ce706506-...
   │       Owner: damian.waldron
   │
   └─ [MODEL]
        Name:  Dependency_View_Test_2ndary_Model
        GUID:  3dfa8673-...
        Owner: damian.waldron
      └─ [SET]                              (anchored on ADDRESS — filter refs ZIPCODE)
           Name:  ADDRESS set
           GUID:  7f9179af-...
           Owner: damian.waldron
```

### Dependency DAG (mermaid)

A `dependency.mmd` file is written alongside the report at `{report_dir}/dependency.mmd`.
The diagram uses the same 4-field labels per node and links Sets to their parent Model.

To render: paste the file contents into https://mermaid.live/ — it expects pure mermaid
source without the markdown ` ```mermaid ` fence.

─── SCAN COVERAGE ──────────────────────────────────────────────

  Method: v2 metadata/search include_dependent_objects (single API call per source +
  per-Set consumer lookup). NO bulk environment scan. Calls = 1 + N_sets.

  CHECKED                 FOUND   NOTES
  ──────────────────────  ──────  ────────────────────────────────────────────
  Models / Worksheets     {found_counts["MODEL"]}      direct from LOGICAL_TABLE bucket
  Views                   {found_counts["VIEW"]}       direct from LOGICAL_TABLE bucket
  Answers                 {found_counts["ANSWER"]}     direct from QUESTION_ANSWER_BOOK bucket
  Liveboards              {found_counts["LIVEBOARD"]}  direct from PINBOARD_ANSWER_BOOK bucket
  Sets / Cohorts          {found_counts["SET"]}        direct from COHORT bucket
  Coaching / Feedback     {found_counts["FEEDBACK"]}   direct from FEEDBACK bucket (verified item #1)
  Alias chain layers      {len(alias_map) - 1}         per-Model/View aliases for target column
  RLS rules               {len(rls_hits)}              from source table TML (verified item #7)

  NOT CHECKED — manual review recommended
  ──────────────────────  ──────  ────────────────────────────────────────────
  Alerts (Monitors)       —       open item #6: VERIFIED via Liveboard --associated;
                                  not yet wired into Step 4
  Column-level ACLs       —       open item #8: VERIFIED — GUID-stable, no skill action
  Column security TML     —       open item #9: STRUCTURE KNOWN; retrieval unverified
  Per-locale alias TML    —       open item #10: STRUCTURE KNOWN; retrieval unverified

  Total endpoint calls:   {scan_totals["endpoint_calls"]}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Action types:
  REMOVE_COLUMN       — column stripped from table/search_query (chart unaffected)
  REMOVE_COLOR_BINDING — color/size/shape axis binding removed (chart remains intact)
  REMOVE_CHART        — column is on X or Y axis; requires per-viz decision (Step 6)
  UPDATE              — column renamed/repointed in all references

Risk ratings:
  HIGH   — Cascading or shared (Models, Views, Liveboards). A break here propagates
           downstream; treat as P0 in any rollout.
  MEDIUM — Individual user-saved object (saved Answers; Sets that have consumers).
           Affects whoever owns/views the object.
  LOW    — Informational / non-breaking (orphan Sets with no consumers, Spotter
           feedback entries).
```

**If any STOP CONDITIONS are present**, require explicit acknowledgment before proceeding:

```
Review the STOP CONDITIONS above.

  {J} join condition(s) in "{source_name}" will be permanently removed.
  {C} visualization(s) require a per-chart decision in Step 6.

  Y  Acknowledge and continue to Step 6
  N  Stop — exit without making any changes

Enter Y / N:
```

If N, stop immediately. No changes have been made.

**URL patterns by object type:**

| Type | URL pattern |
|---|---|
| LIVEBOARD | `https://yourcluster.thoughtspot.cloud/#/pinboard/{guid}` |
| ANSWER | `https://yourcluster.thoughtspot.cloud/#/saved-answer/{guid}` |
| MODEL / WORKSHEET / VIEW | `https://yourcluster.thoughtspot.cloud/#/data/tables/{guid}` |
| TABLE | `https://yourcluster.thoughtspot.cloud/#/data/tables/{guid}` |

**After displaying the report (and handling any STOP CONDITIONS acknowledgment), always
write the report to persistent files.** This happens whether the user continues, exits,
or re-scans. The files are the sharable artifact and the re-run source of truth.

```python
import csv, json, datetime, os

def object_url(guid, obj_type, base_url):
    if obj_type == "LIVEBOARD":
        return f"https://yourcluster.thoughtspot.cloud/#/pinboard/{guid}"
    elif obj_type == "ANSWER":
        return f"https://yourcluster.thoughtspot.cloud/#/saved-answer/{guid}"
    elif obj_type in ("SET", "COHORT"):
        return f"https://yourcluster.thoughtspot.cloud/#/cohort/{guid}"
    else:
        return f"https://yourcluster.thoughtspot.cloud/#/data/tables/{guid}"

timestamp  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
report_dir = f"/tmp/ts_dep_report_{timestamp}"
os.makedirs(report_dir, exist_ok=True)

# JSON plan — includes setup metadata so the scan can be resumed or re-run
plan = {
    "created":   datetime.datetime.now().isoformat(),
    "profile":   profile_name,
    "base_url":  base_url,
    "operation": operation,
    "source":    {"guid": source_guid, "name": source_name, "type": source_type},
    "columns":   (columns_to_remove          if operation == "REMOVE"
                  else {"from": current_col_name, "to": new_col_name}),
    "summary": {
        "total":  len(dependents),
        "HIGH":   sum(1 for d in dependents if risk_rating(d) == "HIGH"),
        "MEDIUM": sum(1 for d in dependents if risk_rating(d) == "MEDIUM"),
        "LOW":    sum(1 for d in dependents if risk_rating(d) == "LOW"),
        "stop_conditions": {
            "affected_joins":     len(source_affected_joins),
            "remove_chart_items": sum(1 for d in dependents
                                      if d.get("action") == "REMOVE_CHART"),
        },
    },
    "dependents": [
        {
            "guid":     d["guid"],
            "name":     d["name"],
            "type":     d["type"],
            "owner":    d.get("owner", ""),
            "risk":     risk_rating(d),
            "action":   d.get("action", "UPDATE"),
            "affected": d.get("affected", []),
            "url":      object_url(d["guid"], d["type"], base_url),
        }
        for d in dependents
    ],
    "sets": [
        {
            "guid":          s["guid"],
            "name":          s["name"],
            "anchor_column": s["anchor_column"],
            "action":        s["action"],
            "in_use_by":     s["in_use_by"],
            "url":           object_url(s["guid"], "SET", base_url),
        }
        for s in affected_sets
    ],
    "stop_conditions": {"affected_joins": source_affected_joins},
}

plan_file = os.path.join(report_dir, "impact_plan.json")
with open(plan_file, "w") as f:
    json.dump(plan, f, indent=2)

# CSV — for human sharing (stakeholders, tickets, email)
csv_file = os.path.join(report_dir, "impact_report.csv")
with open(csv_file, "w", newline="", encoding="utf-8") as f:
    cols = ["Type", "Name", "Owner", "URL", "Affected Columns", "Action", "Risk"]
    writer = csv.DictWriter(f, fieldnames=cols)
    writer.writeheader()
    for d in dependents:
        writer.writerow({
            "Type":             d["type"],
            "Name":             d["name"],
            "Owner":            d.get("owner", ""),
            "URL":              object_url(d["guid"], d["type"], base_url),
            "Affected Columns": ", ".join(d.get("affected", [])),
            "Action":           d.get("action", "UPDATE"),
            "Risk":             risk_rating(d),
        })
    for s in affected_sets:
        writer.writerow({
            "Type":             "SET (COHORT)",
            "Name":             s["name"],
            "Owner":            s.get("owner", ""),
            "URL":              object_url(s["guid"], "SET", base_url),
            "Affected Columns": s["anchor_column"],
            "Action":           s["action"],
            "Risk":             "MEDIUM" if s["in_use_by"] else "LOW",
        })

print(f"\nReport saved to: {report_dir}/")
print(f"  impact_plan.json  — machine-readable plan (use for re-scan or resume)")
print(f"  impact_report.csv — human-readable summary (share with stakeholders)")
```

### Emit the tree and DAG files

Build a parent-keyed graph from `dependents` + `affected_sets` + `feedback_relevant`. Sets
attach to their parent Model (read from cohort TML's `worksheet.fqn`); feedback attaches
to its `parent_model`. Then render two views:

```python
def _label(node, indent_step="     "):
    """4-line label block for a node — Type/Name/GUID/Owner."""
    return (
        f"[{node['type']}]\n"
        f"{indent_step}Name:  {node['name']}\n"
        f"{indent_step}GUID:  {node['guid']}\n"
        f"{indent_step}Owner: {node.get('owner','?')}"
    )

def write_tree_text(report_dir, connection, source, graph):
    """
    graph: {parent_guid: [child_node_dict, ...]}
    Writes report_dir/dependency_tree.txt
    """
    lines = []
    lines.append(f"[CONNECTION]\n  Name:  {connection['name']}\n"
                 f"  GUID:  {connection['guid']}\n  Owner: {connection.get('owner','?')}")
    lines.append("│")
    lines.append(f"└─ [TABLE] (source)\n     Name:  {source['name']}\n"
                 f"     GUID:  {source['guid']}\n     Owner: {source.get('owner','?')}")

    def recurse(parent_guid, prefix="   "):
        children = graph.get(parent_guid, [])
        for i, child in enumerate(children):
            is_last = (i == len(children) - 1)
            branch  = "└─" if is_last else "├─"
            cont    = "   " if is_last else "│  "
            lines.append(f"{prefix}{branch} {_label(child, prefix + cont + '   ')}")
            recurse(child["guid"], prefix + cont)

    recurse(source["guid"])

    with open(os.path.join(report_dir, "dependency_tree.txt"), "w") as f:
        f.write("\n".join(lines))

def _mmd_label(s):
    """Escape characters that break mermaid label parsing.

    Without this, names containing & (e.g. "Sales & Inventory"), [, ], <, >, |, or
    embedded quotes will silently break the diagram — the file looks fine to humans
    but mermaid.live/the renderer rejects it. Apply to every label string before
    embedding into a node definition.
    """
    return (s.replace("&", "and")
             .replace('"', "'")
             .replace("<", "")
             .replace(">", "")
             .replace("[", "(")
             .replace("]", ")")
             .replace("|", "/")
             .replace("\n", " "))


def write_mermaid(report_dir, connection, source, graph):
    """Writes report_dir/dependency.mmd as pure mermaid source (no markdown fence)."""
    lines = ["graph TD"]
    style_for = {
        "CONNECTION": "conn",  "TABLE": "source",   "ANSWER": "stop",
        "LIVEBOARD":  "stop",  "FEEDBACK": "feedback", "SET": "set",
        "RLS":        "rls",
    }
    def node_id(guid):  # mermaid IDs cannot start with a digit or contain hyphens
        # Use underscore prefix + alnum-only suffix so IDs are always valid
        safe = "".join(ch for ch in guid if ch.isalnum())
        return "n_" + safe[:16]
    def emit(node):
        nid = node_id(node["guid"])
        label = (f'{node["type"]}<br/>{_mmd_label(node["name"])}<br/>'
                 f'{node["guid"][:8]}<br/>{_mmd_label(node.get("owner","?"))}')
        cls = style_for.get(node["type"], "")
        suffix = f":::{cls}" if cls else ""
        lines.append(f'    {nid}["{label}"]{suffix}')

    emit({**connection, "type": "CONNECTION"})
    emit({**source, "type": "TABLE"})
    lines.append(f'    {node_id(connection["guid"])} --> {node_id(source["guid"])}')

    seen = {connection["guid"], source["guid"]}
    def recurse(parent_guid):
        for child in graph.get(parent_guid, []):
            if child["guid"] not in seen:
                emit(child); seen.add(child["guid"])
            edge = "-.feedback.->" if child["type"] == "FEEDBACK" else \
                   "-.contains.->" if child["type"] == "RLS"      else "-->"
            lines.append(f'    {node_id(parent_guid)} {edge} {node_id(child["guid"])}')
            recurse(child["guid"])
    recurse(source["guid"])

    lines += [
        "",
        "    classDef conn     fill:#003366,color:#fff,stroke:#000,stroke-width:2px",
        "    classDef source   fill:#0066cc,color:#fff,stroke:#003366,stroke-width:2px",
        "    classDef stop     fill:#cc6600,color:#fff,stroke:#663300",
        "    classDef feedback fill:#999,color:#fff,stroke:#333,stroke-dasharray: 4 2",
        "    classDef set      fill:#9933cc,color:#fff,stroke:#330066",
        "    classDef rls      fill:#cc3333,color:#fff,stroke:#660000",
    ]
    with open(os.path.join(report_dir, "dependency.mmd"), "w") as f:
        f.write("\n".join(lines))

write_tree_text(report_dir, connection_info, source_info, parent_keyed_graph)
write_mermaid(report_dir,    connection_info, source_info, parent_keyed_graph)
print(f"  dependency_tree.txt — indented hierarchy")
print(f"  dependency.mmd      — mermaid DAG (paste into https://mermaid.live/ to render)")
```

`connection_info` and `source_info` are dicts with `guid`, `name`, `owner`. Build
`parent_keyed_graph` so that:
- Models, Views, Answers, Liveboards listed under `dependents` attach to whatever Model
  surfaces the column (or the source if no intermediary)
- Sets in `affected_sets` attach to the Model named in their cohort TML's `worksheet.fqn`
- Feedback in `feedback_relevant` attaches to its `parent_model`
- An RLS rule found in the source table TML attaches to the source as a special `RLS` node

### Audit-mode exit (operation = AUDIT)

If `operation == "AUDIT"`, **do not** show the C/E/R menu below. Instead jump to the
audit exit handler:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 AUDIT COMPLETE — no changes applied
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Report files saved to: {report_dir}/
  - impact_plan.json     — machine-readable plan (use as input for R/N/P)
  - impact_report.csv    — flat list, one row per dependent
  - dependency_tree.txt  — indented hierarchy
  - dependency.mmd       — mermaid DAG

Recommendation engine (Step 5.5) is deferred — see open-items.md #21.
For now, run /ts-dependency-manager again with the appropriate mode (R/N/P)
to apply changes based on this report.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

End the skill. No backups taken, no objects modified.

---

**Action menu (operation in REMOVE / RENAME / REPOINT)** — shown after the report is written:

```
What would you like to do?

  C  Continue — proceed to select and apply changes
  E  Exit     — save the report and stop here; re-run the skill when ready to apply
  R  Re-scan  — re-run discovery with the same inputs to reflect manual corrections

Enter C / E / R:
```

If **E**, tell the user:

```
Stopped — no changes made.

Report:   {report_dir}/impact_report.csv
Plan:     {report_dir}/impact_plan.json

To resume: run /ts-dependency-manager with the same model and column inputs.
The plan file records the inputs — load it to skip the setup questions.
```

If **R — Re-scan**, re-run the Step 4 discovery loop with the same `source_guid`,
`columns_to_remove` / `current_col_name`, `profile_name`. Then compute and display a diff:

```python
def diff_scan(previous_plan, new_dependents):
    """Compare a fresh scan against a saved plan. Returns (resolved, added)."""
    prev_guids = {d["guid"] for d in previous_plan["dependents"]}
    curr_guids = {d["guid"] for d in new_dependents}
    resolved = [d for d in previous_plan["dependents"] if d["guid"] not in curr_guids]
    added    = [d for d in new_dependents              if d["guid"] not in prev_guids]
    return resolved, added
```

Display the diff before the full refreshed report:

```
Re-scan complete.

  Previously: {prev_count} dependent(s)
  Now:        {curr_count} dependent(s)

  ✓ Resolved ({len(resolved)}):
    - Sales by Region Q4  (ANSWER) — no longer references the column
    - Revenue Summary     (ANSWER)

  + New ({len(added)}):
    - Monthly Dashboard   (LIVEBOARD) — newly detected

  = Unchanged ({unchanged_count}): still present as dependents
```

After the diff, re-display the full updated impact report (same format as above) and
present the action menu again. Overwrite the plan file and CSV with the refreshed results.

If **C**, proceed to Step 6.

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

### Announce backup location BEFORE running

Before exporting anything, tell the user where the backup will be written and what it will
contain. The path is generated once and reused for the rest of this run.

```
TML BACKUP — about to run

  Location:  /tmp/ts_dep_backup_<YYYYMMDD_HHMMSS>/
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
backup_dir  = f"/tmp/ts_dep_backup_{timestamp}"
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

### 9a — Delete objects marked for deletion

Skip this section entirely if `objects_to_delete` is empty.

**Important — verified 2026-04-26 on champ-staging:** the `ts metadata delete <guid>` CLI
command is **broken**. It returns success (`{"deleted": [guid]}`) but the object is not
actually deleted; querying it afterward still returns the object with `isDeleted: False`.
The root cause is that the CLI doesn't pass an explicit `type` field in the v2
`/api/rest/2.0/metadata/delete` body, which the API silently ignores. Until the CLI is
fixed, call the v2 endpoint directly with `type` populated per object.

```python
import requests

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

# v2 expects an explicit type per object. Map skill types to the v2 enum.
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

    # IMPLEMENTATION NOTE: The `ts metadata delete` CLI command is broken (open-items.md
    # #17) — it doesn't pass the required `type` field to v2 /metadata/delete. Until the
    # CLI is fixed, the implementation must call the v2 endpoint directly with explicit
    # type. The exact call shape is documented in open-items.md #17 (verified 2026-04-26
    # against champ-staging). Once the CLI is fixed, replace this whole block with a
    # subprocess call to `ts metadata delete --type {v2_type} {guid}`.

    print(f"  Deleting {dep['type']}: {dep['name']} ({dep['guid']})...")
    status, body = ts_metadata_delete(dep["guid"], v2_type, profile_name)  # see open-items.md #17

    # 204 No Content = success. 200 with body is the broken path; treat as inconclusive
    # and verify by re-querying the object's metadata.
    if status == 204:
        print(f"  ✓ Deleted: {dep['name']}")
        results["deleted"].append(dep)
    else:
        # Verify by re-querying — the API sometimes returns 200 with a deleted-list payload
        # even when the object remains. Trust only the post-state.
        gone = ts_metadata_object_is_gone(dep["guid"], v2_type, profile_name)  # search returns empty
        if gone:
            print(f"  ✓ Deleted: {dep['name']}  (verified by post-query)")
            results["deleted"].append(dep)
        else:
            err = f"status={status} body={body[:200]}; post-query still returns object"
            print(f"  ✗ Delete failed: {dep['name']} — {err}")
            results["failed"].append({**dep, "error": err, "phase": "delete"})
```

The `ts_metadata_dependents`, `ts_metadata_delete`, and `ts_metadata_object_is_gone`
helpers are temporary stubs that wrap the verified v2 calls documented in
[references/open-items.md](references/open-items.md) #1 and #17. They live in a
small `_v2_helpers.py` shim alongside the skill, and will be deleted once `ts metadata
dependents` and `ts metadata delete --type` ship in ts-cli.

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
    """Extract (ok: bool, error_msg: str) from an import response."""
    try:
        status = resp["object"][0]["response"]["status"]
        ok     = status.get("status_code") == "OK"
        return ok, status.get("error_message", "Unknown error")
    except (KeyError, IndexError):
        return False, str(resp)
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

**RENAME — Model, Worksheet, or Table:**

```python
updated_source = copy.deepcopy(source_export_item["tml"])
section = (updated_source.get("model") or updated_source.get("worksheet")
           or updated_source.get("table", {}))

# Rename in columns[]
for col in section.get("columns", []):
    if col.get("name") == current_col_name:
        col["name"] = new_col_name
    # column_id format may be TABLE::COL_NAME — update the column name part
    if col.get("column_id", "").endswith(f"::{current_col_name}"):
        col["column_id"] = col["column_id"].rsplit("::", 1)[0] + f"::{new_col_name}"

# For Models/Worksheets: update formula expressions referencing the old name
for formula in section.get("formulas", []):
    formula["expr"] = re.sub(
        r'\[' + re.escape(current_col_name) + r'\]',
        f'[{new_col_name}]',
        formula.get("expr", ""),
    )
```

Import the source object:

```python
print(f"  Updating source: {source_name}...")
resp = import_tml(updated_source, source_guid, profile_name)
ok, err = import_status(resp)
if not ok:
    print(f"  ✗ Source update failed: {err}")
    print("  No dependent objects will be updated. Backup is at {backup_dir}.")
    # Stop — do not proceed to dependent updates
    return
print(f"  ✓ {source_name}")
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

**For RENAME — update column references in an Answer or Liveboard viz:**

```python
def rename_column_in_answer(answer_dict, old_name, new_name):
    a = answer_dict

    # search_query — MUST be updated or stale reference will fail on import (open-items.md #3)
    if a.get("search_query"):
        a["search_query"] = rename_in_search_query(a["search_query"], old_name, new_name)

    # answer_columns[].name
    for col in a.get("answer_columns", []):
        if col.get("name") == old_name:
            col["name"] = new_name

    # table.ordered_column_ids
    tbl = a.get("table", {})
    tbl["ordered_column_ids"] = [
        new_name if c == old_name else c
        for c in tbl.get("ordered_column_ids", [])
    ]
    for tc in tbl.get("table_columns", []):
        if tc.get("column_id") == old_name:
            tc["column_id"] = new_name

    # chart
    chart = a.get("chart", {})
    for cc in chart.get("chart_columns", []):
        if cc.get("column_id") == old_name:
            cc["column_id"] = new_name
    for axis in chart.get("axis_configs", []):
        for key in ("x", "y", "color", "size", "shape"):
            if key in axis and isinstance(axis[key], list):
                axis[key] = [new_name if v == old_name else v for v in axis[key]]

    # formulas: update expr references
    for formula in a.get("formulas", []):
        formula["expr"] = re.sub(
            r'\[' + re.escape(old_name) + r'\]',
            f'[{new_name}]',
            formula.get("expr", ""),
        )

    # display_headline_column (KPI tiles)
    if a.get("display_headline_column") == old_name:
        a["display_headline_column"] = new_name

    return a
```

**For REPOINT — change the data source reference and remove gap columns:**

```python
def repoint_answer(answer_dict, source_guid, target_guid, target_name, column_gap):
    a = answer_dict

    for tbl in a.get("tables", []):
        if tbl.get("fqn") == source_guid:
            tbl["fqn"]  = target_guid
            tbl["name"] = target_name
            tbl["id"]   = target_name  # id mirrors name in answer tables

    if column_gap:
        a = remove_columns_from_answer(a, column_gap)

    return a
```

**For RENAME — update column references in a reusable Set (cohort) TML:**

See [~/.claude/shared/schemas/thoughtspot-sets-tml.md](~/.claude/shared/schemas/thoughtspot-sets-tml.md)
for the full field layout. The column name appears in `anchor_column_id`, group condition
`column_name` fields, `return_column_id` (COLUMN_BASED sets), pass-through filter column
lists, and the embedded answer section.

```python
def rename_column_in_set(set_tml, old_name, new_name):
    """Update all column references in a reusable set (cohort) TML dict."""
    s = copy.deepcopy(set_tml)
    cohort = s.get("cohort", {})
    config = cohort.get("config", {})

    # anchor_column_id — the primary column reference
    if config.get("anchor_column_id") == old_name:
        config["anchor_column_id"] = new_name

    # return_column_id (COLUMN_BASED query sets)
    if config.get("return_column_id") == old_name:
        config["return_column_id"] = new_name

    # group conditions (GROUP_BASED sets)
    for group in config.get("groups", []):
        for cond in group.get("conditions", []):
            if cond.get("column_name") == old_name:
                cond["column_name"] = new_name

    # pass_thru_filter column lists (COLUMN_BASED sets)
    ptf = config.get("pass_thru_filter", {})
    ptf["include_column_ids"] = [
        new_name if c == old_name else c for c in ptf.get("include_column_ids", [])
    ]
    ptf["exclude_column_ids"] = [
        new_name if c == old_name else c for c in ptf.get("exclude_column_ids", [])
    ]

    # embedded answer (COLUMN_BASED query sets only)
    if "answer" in cohort:
        cohort["answer"] = rename_column_in_answer(cohort["answer"], old_name, new_name)

    return s
```

**Apply to Answers:**

```python
for dep in [d for d in objects_to_fix if d["type"] == "ANSWER"]:
    updated = copy.deepcopy(dep["tml"])
    answer  = updated.get("answer", {})

    if operation == "REMOVE":
        # Standalone Answers with action == "REMOVE_CHART" are auto-converted to TABLE_MODE
        # before stripping the column. This preserves the Answer (no longer "manual only").
        if dep.get("action") == "REMOVE_CHART":
            answer = convert_answer_to_table(answer)
        answer = remove_columns_from_answer(answer, columns_to_remove)
    elif operation == "RENAME":
        answer = rename_column_in_answer(answer, current_col_name, new_col_name)
    elif operation == "REPOINT":
        answer = repoint_answer(answer, source_guid, target_guid, target_name, column_gap)

    updated["answer"] = answer
    resp = import_tml(updated, dep["guid"], profile_name)
    ok, err = import_status(resp)
    ...
```

**Apply to Liveboards:**

Liveboards embed full answer definitions in `visualizations[].answer`. Apply the same
helper functions to each visualization's answer section that references `{source_guid}`.
Check against `[~/.claude/shared/schemas/thoughtspot-liveboard-tml.md]` for the exact
field layout before modifying.

```python
for dep in [d for d in objects_to_fix if d["type"] == "LIVEBOARD"]:
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
        elif operation == "RENAME":
            answer = rename_column_in_answer(answer, current_col_name, new_col_name)
        elif operation == "REPOINT":
            answer = repoint_answer(answer, source_guid, target_guid, target_name, column_gap)

        viz["answer"] = answer

    # Remove entire chart visualizations the user chose to delete
    if vizes_to_remove:
        liveboard["visualizations"] = [
            v for v in liveboard.get("visualizations", [])
            if v.get("id") not in vizes_to_remove
        ]

    # Liveboard-level filter updates
    if operation == "RENAME":
        # Update column names in liveboard filters
        for f in liveboard.get("filters", []):
            f["column"] = [new_col_name if c == current_col_name else c
                           for c in f.get("column", [])]
    elif operation == "REMOVE":
        # Remove filter entries for removed columns (Rule 1)
        # A filter whose column list is fully emptied is dropped entirely
        updated_filters = []
        for filt in liveboard.get("filters", []):
            new_cols = [c for c in filt.get("column", []) if c not in columns_to_remove]
            if new_cols:
                filt["column"] = new_cols
                updated_filters.append(filt)
        liveboard["filters"] = updated_filters

    resp = import_tml(updated, dep["guid"], profile_name)
    ok, err = import_status(resp)
    ...
```

**Apply to Views:**

Views have `view_columns[]`, `formulas[]`, `joins[]`, and `search_query` — all need
updating when a referenced column is removed or renamed. See
[~/.claude/shared/schemas/thoughtspot-view-tml.md](~/.claude/shared/schemas/thoughtspot-view-tml.md)
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

def rename_column_in_view(view_dict, old_name, new_name):
    """Rename a column reference in a View TML dict (the view: section)."""
    v = view_dict

    if v.get("search_query"):
        v["search_query"] = rename_in_search_query(v["search_query"], old_name, new_name)

    # view_columns[].column_id — update the column name part after ::
    for col in v.get("view_columns", []):
        if col.get("name") == old_name:
            col["name"] = new_name
        if col.get("column_id", "").endswith(f"::{old_name}"):
            col["column_id"] = col["column_id"].rsplit("::", 1)[0] + f"::{new_name}"

    # formulas[].expr
    for formula in v.get("formulas", []):
        formula["expr"] = re.sub(
            r'\[' + re.escape(old_name) + r'\]',
            f'[{new_name}]',
            formula.get("expr", ""),
        )

    # joins[].on — replace column name in join expressions
    for join in v.get("joins", []):
        join["on"] = join.get("on", "").replace(f"::{old_name}]", f"::{new_name}]")

    return v
```

Apply to Views in the update loop:

```python
for dep in [d for d in objects_to_fix if d["type"] == "VIEW"]:
    updated = copy.deepcopy(dep["tml"])
    view    = updated.get("view", {})

    if   operation == "REMOVE":  view = remove_columns_from_view(view, columns_to_remove)
    elif operation == "RENAME":  view = rename_column_in_view(view, current_col_name, new_col_name)
    elif operation == "REPOINT": view = repoint_view(view, source_guid, target_guid, target_name, column_gap)

    updated["view"] = view
    resp = import_tml(updated, dep["guid"], profile_name)
    ok, err = import_status(resp)
    ...
```

**Apply to Feedback:**

Feedback items share the Model's GUID. Export the updated Model's `--associated` TML
to get the current feedback state, then strip stale entries:

```python
for dep in [d for d in objects_to_fix if d["type"] == "FEEDBACK"]:
    updated   = copy.deepcopy(dep["tml"])
    feedback  = updated.get("nls_feedback", {})
    target    = columns_to_remove if operation == "REMOVE" else [current_col_name]

    entries = feedback.get("feedback", [])
    if operation == "REMOVE":
        entries = [
            e for e in entries
            if not any(col in json.dumps(e) for col in target)
        ]
    elif operation == "RENAME":
        for e in entries:
            e["search_tokens"] = rename_in_search_query(e.get("search_tokens", ""), current_col_name, new_col_name)
    feedback["feedback"] = entries
    updated["nls_feedback"] = feedback
    resp = import_tml(updated, dep["guid"], profile_name)
    ok, err = import_status(resp)
    ...
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
Sets with `action == "DELETE_AFTER_DEPENDENTS"` had consumers that have now been updated
(or skipped) — proceed with deletion.

```python
for s in affected_sets:
    if s["action"] not in ("DELETE_SAFE", "DELETE_AFTER_DEPENDENTS"):
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
                                     "action": "deleted"})
    else:
        err = result.stderr.strip() or result.stdout.strip()
        print(f"  ✗ Failed to delete set '{s['name']}': {err}")
        results["failed"].append({"name": s["name"], "type": "SET", "guid": s["guid"],
                                  "error": err})
```

**For RENAME — update sets that referenced the renamed column:**

```python
for s in affected_sets:
    if s["action"] != "UPDATE_SET":
        continue

    updated_set = rename_column_in_set(s["tml"], current_col_name, new_col_name)
    resp = import_tml(updated_set, s["guid"], profile_name)
    ok, err = import_status(resp)
    if ok:
        print(f"  ✓ Updated set: {s['name']}")
        results["succeeded"].append({"name": s["name"], "type": "SET", "guid": s["guid"]})
    else:
        print(f"  ✗ Failed to update set '{s['name']}': {err}")
        results["failed"].append({"name": s["name"], "type": "SET", "guid": s["guid"],
                                  "error": err})
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
| 0.1.2 | 2026-04-26 | Step 4 rewrite — replace bulk environment scan (10k+ TML exports, ~30 min) with v2 dependents API (~3s, single call). Add alias propagation: for each Model/View dependent, extract what alias the target column is exposed as (e.g. ZIPCODE → "Customer Zipcode"), then match Answers/Liveboards/Sets against the alias of the Model they query — caught ~30% more dependents in test environments. Fix tree hierarchy: Answers/Liveboards now attach to the Model they query (via tables[].fqn); Set consumers re-parent under the Set; Views handled correctly via view_columns + search_query. Mermaid DAG escapes & and special chars. Add Step 0 dependency hierarchy diagram. Add risk-rating legend inline in impact report |
| 0.1.1 | 2026-04-26 | Add references/dependency-types.md (status table, hierarchy diagram, sample impact report); update open-items.md #6 (alerts VERIFIED via Liveboard --associated), #7 (RLS VERIFIED inline in table TML), #9 (CSR structure documented; retrieval unverified), #10 (column_alias TML structure documented; retrieval unverified); add suggest_dependency_types.py soft pre-commit nudge |
| 0.1.0 | 2026-04-26 | Initial WIP — Audit/Remove/Rename/Repoint modes; v2 dependents discovery with recursive walk through Models, Views, and Sets; FIX/DELETE per dependent with typed-DELETE confirmation; markdown-table impact report with text tree + mermaid DAG; TML backup with manifest; rollback for updates and deletes |
