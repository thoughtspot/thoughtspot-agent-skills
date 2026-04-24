---
name: ts-object-answer-promote
description: Promote formulas and parameters from a saved ThoughtSpot Answer into a Model — makes them available to all users who search against it.
---

# ThoughtSpot: Promote Answer Objects to Model

Move one or more formulas and parameters from a saved ThoughtSpot Answer into a Model definition.
Formulas and parameters defined in an Answer are private to that Answer. Once promoted to the
Model, they appear in the search bar for everyone who has access to the Model.

**When to use this skill:** A Data Analyst created a useful formula (and optionally a parameter)
in a saved Answer — a calculated ratio, a conditional flag, a YoY comparison — and now wants it
available to the whole team via the Model.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/open-items.md](references/open-items.md) | Verified and unverified API behaviors — read before implementing each step |
| [~/.claude/skills/ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config, token persistence |
| [~/.claude/shared/schemas/thoughtspot-answer-tml.md](~/.claude/shared/schemas/thoughtspot-answer-tml.md) | Answer TML structure — verified field reference for formulas, parameters, sets, data source lookup |
| [~/.claude/shared/schemas/thoughtspot-liveboard-tml.md](~/.claude/shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure — needed for Liveboard fallback path in Step 2 |
| [~/.claude/shared/schemas/thoughtspot-sets-tml.md](~/.claude/shared/schemas/thoughtspot-sets-tml.md) | Set TML structure — bin sets, group sets, query sets; answer-level vs reusable |
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | Model TML structure — formula and column placement rules, self-validation checklist |
| [~/.claude/shared/schemas/thoughtspot-formula-patterns.md](~/.claude/shared/schemas/thoughtspot-formula-patterns.md) | Formula syntax, column reference syntax, YAML encoding rules |
| [~/.claude/shared/schemas/thoughtspot-tml.md](~/.claude/shared/schemas/thoughtspot-tml.md) | TML parsing: non-printable char cleanup, PyYAML field name quirks |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Python package: `pyyaml` (`pip install pyyaml`)
- ThoughtSpot user must have **MODIFY** or **FULL** access on the target Model

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-object-answer-promote** — promote formulas and parameters from a saved ThoughtSpot Answer into a Model, making them available to all users who search against it.

Steps:
  1.  Authenticate ..................................... auto
  2.  Find the Answer .................................. you choose
  3.  Export and parse the Answer TML .................. auto
  4.  Select formulas (and parameters) to promote ...... you choose
  5.  Find the target Model ............................ you choose
  6.  Check edit permissions on the Model .............. auto
  7.  Export and parse the Model TML ................... auto
  8.  Detect duplicate formula and parameter names ..... auto
  9.  Map formula column references to the Model ........ auto (may ask for clarification)
 10.  Build the updated Model TML ...................... auto
 11.  Checkpoint — review changes before import ......... you confirm
 12.  Import the updated Model TML ..................... auto
 13.  Verify and report ............................... auto

Confirmation required: Steps 4, 5, 11
Auto-executed: Steps 1, 3, 6, 7, 8, 9, 10, 12, 13

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
[ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) for the token
refresh procedure.

Save `{base_url}` (strip trailing slash) and `{profile_name}` for all subsequent steps.

---

## Step 2 — Find the Answer

Ask:

```
Which saved Answer contains the formula(s) you want to promote?

  Enter a name or partial name to search, or paste the Answer GUID directly:
```

**If the user enters a search term:**

```bash
source ~/.zshenv && ts metadata search \
  --type ANSWER \
  --name "%{search_term}%" \
  --profile "{profile_name}" \
  --all
```

Show results as a numbered list:

```
Matching Answers:

  1  Q4 Sales Analysis
  2  Q4 Sales by Region
  3  Sales Forecast Check

Enter number, or type a different search term:
```

**If the user pastes a GUID:**

```bash
source ~/.zshenv && ts metadata search \
  --type ANSWER \
  --guid "{guid}" \
  --profile "{profile_name}"
```

Save `{answer_guid}` and `{answer_name}` from the selected result.

Also save the current user's ID from the `ts auth whoami` response (`id` field) as
`{current_user_id}` — used in Step 6 to check ownership.

Note: the metadata search response for an Answer does not include the data source GUID.
The data source GUID is extracted from the Answer TML in Step 3 (`answer.tables[0]["fqn"]`).

---

## Step 3 — Export and Parse Answer TML

Export the Answer TML:

```bash
source ~/.zshenv && ts tml export {answer_guid} \
  --profile "{profile_name}" \
  --fqn \
  --parse
```

`--parse` returns structured JSON directly — no YAML string, no non-printable char
stripping required. Extract the parsed TML from the first result:

```python
import json, subprocess

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml export {answer_guid} --profile '{profile_name}' --fqn --parse"],
    capture_output=True, text=True,
)
export_json = json.loads(result.stdout)
tml = export_json[0]["tml"]   # fully parsed dict — no further parsing needed
```

Extract formulas, sets, parameters, and the data source GUID. The structure is verified —
see [thoughtspot-answer-tml.md](~/.claude/shared/schemas/thoughtspot-answer-tml.md).

```python
answer = tml.get("answer", {})
formulas       = answer.get("formulas", [])
parameters     = answer.get("parameters", [])
cohorts        = answer.get("cohorts", [])     # sets — not formulas
tables_section = answer.get("tables", [])

# Data source GUID is confirmed at tables[0]["fqn"]
data_source_guid = tables_section[0]["fqn"] if tables_section else None
data_source_name = tables_section[0]["name"] if tables_section else None
```

**If `formulas` is empty or absent**, tell the user:

```
"{answer_name}" does not contain any custom formula definitions in its TML.

This can happen when:
  - The Answer uses only columns from the underlying Model with no custom formulas added
  - Formulas were added via search query syntax and are not persisted as named formulas

Would you like to search a different Answer? (Y / N):
```

If Y, return to Step 2. If N, stop.

---

## Step 4 — Select Formulas to Promote

**Separate formulas from sets.** Answer TML has two types of custom columns that both
appear in `answer_columns[]`: formulas (in `formulas[]`) and sets (in `cohorts[]`).
This skill promotes formulas only. Identify both so you can show a clear selection list
and explain to the user what is and isn't in scope.

```python
formula_names = {f["name"] for f in formulas}
set_names     = {c["name"] for c in cohorts}
param_names   = {p["name"] for p in parameters}
```

Display formulas for selection. Answer formulas do **not** carry `column_type` or
`aggregation` — these will be inferred or asked for in Step 10. Show the `expr` so the
user can see what they are promoting. Flag auto-generated formulas.

```
Formulas in "{answer_name}":

  1  Profit Margin            →  [Revenue] - [Cost]
  2  YoY Growth %             →  ( [Revenue] - [Prior Year Revenue] ) / [Prior Year Revenue]
  3  High Value Flag          →  if ( [Revenue] > 10000 ) then 'High' else 'Low'
  4  Auto Derived  [auto]     →  ( [Vivun Deliverables Count] )

Enter numbers to promote (comma-separated), or A for all:
```

`[auto]` marks formulas where `was_auto_generated: true`. These are often wrapper
formulas created by ThoughtSpot during a search — confirm with the user before
including them.

If sets are present, list them separately so the user knows they exist but are out of scope:

```
Also found in this Answer (sets — not promotable as formulas):

  -  Revenue Bins      (column set — bin-based grouping)
  -  Top 10 Products   (query set — embedded search)

Sets require separate promotion to standalone set objects. This skill handles formulas only.
```

After formula selection, **check for parameter references.** A formula that references
`[Param Name]` where `Param Name` matches a `parameters[].name` entry needs its parameter
promoted to the Model as well — Model formulas can reference `model.parameters[]` entries
using the same `[Param Name]` bracket syntax.

```python
import re

def extract_refs(expr):
    return re.findall(r'\[([^\]]+)\]', expr)

# Build a lookup of Answer parameters by name for quick access
params_by_name = {p["name"]: p for p in parameters}

# Collect all parameters referenced by selected formulas
params_needed = {}   # name → parameter dict
for f in selected_formulas:
    for ref in extract_refs(f["expr"]):
        if ref in params_by_name:
            params_needed[ref] = params_by_name[ref]
```

If any selected formula references a parameter, for each such parameter:

```
Parameter reference in "{formula_name}":

  The expression references [today], which is an Answer-level parameter.
  To promote this formula, the parameter must also exist in the target Model.

  Options:
    P  Promote the parameter to the Model along with the formula (recommended)
    M  The Model already has a parameter named "today" — promote formula as-is and it will resolve
    E  Edit the expression now — replace [today] with a fixed value or column
    S  Skip this formula

Enter P / M / E / S:
```

For **P — Promote the parameter:** Add the parameter to `params_to_promote` (a list
collected across all formula checks). Each entry is the Answer parameter dict — the
Answer-level UUID is dropped on import; ThoughtSpot assigns a new one.

Build the parameter entry for the Model, handling both `default_value` and
`dynamic_default_date` (some DATE parameters use the latter instead of a static string):

```python
params_to_promote = []   # populated across all formula checks

def build_model_param_entry(answer_param):
    entry = {
        "name": answer_param["name"],
        "data_type": answer_param["data_type"],
        "description": answer_param.get("description", ""),
    }
    if "default_value" in answer_param:
        entry["default_value"] = answer_param["default_value"]
    elif "dynamic_default_date" in answer_param:
        # Keep dynamic default (e.g. TODAY) — ThoughtSpot supports this at model level
        entry["dynamic_default_date"] = answer_param["dynamic_default_date"]
    return entry
```

For **M — already in Model:** leave `params_to_promote` unchanged; the formula expression
needs no rewriting since the existing Model parameter will resolve it.

For **E — edit expression:** prompt for the replacement expression inline; remove the
parameter reference from `params_needed` for this formula.

For **S — skip formula:** remove the formula from the promotion list entirely.

After parameter handling, **check for formula inter-dependencies**: scan each selected
formula's `expr` for `[token]` references that match other Answer formulas not yet selected.
Note: formula inter-references use the formula `id` (e.g. `[formula_Count(all)]`), not
the display name.

```python
answer_formula_ids   = {f["id"]   for f in formulas}
answer_formula_names = {f["name"] for f in formulas}
selected_ids         = {f["id"]   for f in selected_formulas}

for f in selected_formulas:
    refs = extract_refs(f["expr"])
    # An unselected formula dependency looks like [formula_Name] matching a known id
    unselected_deps = [
        r for r in refs
        if r in answer_formula_ids and r not in selected_ids
    ]
```

If there are unselected dependencies:

```
Dependency notice:

  "YoY Growth %" references [formula_Prior Year Revenue], which is also a custom formula
  in this Answer but was not selected for promotion.

  Options:
    A  Also promote "Prior Year Revenue"
    S  Skip — promote only what I selected (I will add dependencies manually)

Enter A or S:
```

---

## Step 5 — Find the Target Model

**Attempt auto-detect first.** The data source GUID is confirmed at
`answer.tables[0]["fqn"]` (extracted in Step 3 as `{data_source_guid}`).

Use `ts metadata get` for a targeted single-object lookup — no pagination, no `--all`:

```bash
source ~/.zshenv && ts metadata get {data_source_guid} \
  --profile "{profile_name}" 2>/dev/null || echo "NOT_FOUND"
```

If a match is found, determine whether it is a Model or legacy Worksheet by checking
`metadata_header.contentUpgradeId`:

```python
header = match.get("metadata_header", {})
is_model = header.get("contentUpgradeId") in (
    "WORKSHEET_TO_MODEL_UPGRADE", "MODEL_UPGRADE"
) or header.get("worksheetVersion") == "V2"
label = "[MODEL]" if is_model else "[WORKSHEET]"
```

Confirm with the user:

```
The Answer is based on this data source:

  {label}  "{model_name}"

Promote the formula(s) to this data source? (Y / N):
```

If N, or if the data source cannot be found, ask the user to search:

```
Search for the target Model by name:
```

```bash
source ~/.zshenv && ts metadata search \
  --subtype WORKSHEET \
  --name "%{search_term}%" \
  --profile "{profile_name}"
```

Show results as a numbered list, labelled `[MODEL]` or `[WORKSHEET]` using the
`contentUpgradeId` / `worksheetVersion` markers. Let the user select.

**Worksheets:** This skill only promotes formulas to Models. If the selected data source
is a legacy Worksheet (not upgraded), inform the user:

```
"{name}" is a legacy Worksheet. This skill promotes formulas to Models only.
Consider migrating the Worksheet to a Model first using /ts-object-model-builder,
then re-run this skill.
```

Save `{model_guid}` and `{model_name}`.

---

## Step 6 — Check Edit Permissions

The metadata search response does not include an explicit permission field (verified —
see open-items.md #2). Use ownership as a proxy: if the Model's `metadata_header.author`
matches `{current_user_id}` (saved from `ts auth whoami` in Step 1), the user owns
the Model and has edit access.

```python
model_author = match.get("metadata_header", {}).get("author", "")
is_owner = (model_author == current_user_id)
```

If the user is **not** the owner, warn — but do not stop:

```
Note: you are not the owner of "{model_name}" (owned by {authorDisplayName}).
If you do not have MODIFY or FULL sharing access, the import in Step 12 will fail
with a permission error.

Continue anyway? (Y / N):
```

If N, stop. If Y, proceed — a 403 at import time will surface a clear error message.

A full permission pre-flight check requires a separate API endpoint not yet verified
on all instance versions — see open-items.md #2.

---

## Step 7 — Export and Parse Model TML

Export the Model TML with its associated Table objects:

```bash
source ~/.zshenv && ts tml export {model_guid} \
  --profile "{profile_name}" \
  --fqn \
  --associated \
  --parse
```

`--parse` returns structured JSON directly. Separate by `type` field:

```python
import json, subprocess

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml export {model_guid} --profile '{profile_name}' --fqn --associated --parse"],
    capture_output=True, text=True,
)
export_json = json.loads(result.stdout)

model_tml = None
model_guid_from_export = None
table_tmls = {}

for item in export_json:
    if item["type"] == "model":
        model_tml = item["tml"]
        model_guid_from_export = item["guid"]   # required for in-place update
    elif item["type"] == "table":
        model_tml_obj = item["tml"]
        table_tmls[model_tml_obj["table"]["name"]] = model_tml_obj
```

The `guid` at the document root of the model TML is required to update the Model
in-place. If it is absent, search for it:

```bash
source ~/.zshenv && ts metadata search \
  --subtype MODEL \
  --name "%{model_name}%" \
  --profile "{profile_name}"
```

Extract from the Model TML:

```python
model = model_tml["model"]
existing_formulas = model.get("formulas", [])
existing_columns  = model.get("columns", [])
model_tables      = model.get("model_tables", [])

# Build column lookups for Step 9
col_by_name = {c["name"]: c for c in existing_columns}
col_by_id   = {c["column_id"]: c for c in existing_columns if "column_id" in c}
formula_names_in_model = {f["name"] for f in existing_formulas}
formula_ids_in_model   = {f["id"]   for f in existing_formulas}
```

Also build a lookup of valid table names for formula column reference validation:

```python
valid_table_names = {t["name"] for t in model_tables}
if any(t.get("alias") for t in model_tables):
    valid_table_names.update(t["alias"] for t in model_tables if t.get("alias"))
```

---

## Step 8 — Detect Duplicate Formula and Parameter Names

**Formulas:** Check whether any selected formula name already exists in the Model:

```python
duplicates = [f for f in selected_formulas if f["name"] in formula_names_in_model]
```

If duplicates exist:

```
The following formula names already exist in "{model_name}":

  - "Profit Margin"

For each duplicate, choose:
  R  Rename — keep both; enter a new name for the promoted formula
  O  Overwrite — replace the existing Model formula with the Answer version
  S  Skip — leave the existing Model formula unchanged

"Profit Margin":
```

For **Rename**: prompt for the new name, then check it does not also conflict with existing
names or other formulas being promoted. Use the new name in the `formulas[]` `name:` field,
the `columns[]` `name:` field, and the `columns[]` `formula_id:` field. The `id` in
`formulas[]` is derived from the (new) name.

Remove skipped formulas from the promotion list. Mark overwrite formulas — their existing
`formulas[]` and `columns[]` entries will be removed before the new entries are added in
Step 10.

**Parameters:** Check whether any parameter in `params_to_promote` already exists in the Model:

```python
param_names_in_model = {p["name"] for p in model.get("parameters", [])}
param_duplicates = [p for p in params_to_promote if p["name"] in param_names_in_model]
```

If parameter duplicates exist:

```
The following parameters already exist in "{model_name}":

  - "today"

For each duplicate, choose:
  K  Keep existing — the Model parameter is already there; formula will resolve against it
  O  Overwrite — replace the existing Model parameter with the Answer version

"today":
```

For **K — Keep existing:** remove the parameter from `params_to_promote` (it's already
in the Model; no change needed).
For **O — Overwrite:** mark it; the existing `parameters[]` entry will be removed before
the new one is added in Step 10.

---

## Step 9 — Map Formula Column References

For each formula to promote, parse its column references and validate them against the
target Model. Column references are the `[...]` tokens in the expression.

```python
import re

def extract_refs(expr):
    """Return all [token] references from a formula expression."""
    return re.findall(r'\[([^\]]+)\]', expr)
```

For each `[token]` reference in the expression, classify it:

**Class A — References another formula (no `::` separator):**
The token matches the name of another formula being promoted, OR the name of an existing
formula already in the Model. No rewriting needed — keep `[token]` as-is.

**Class B — Explicit `TABLE::column` format (token contains `::`):**
Split on `::` to get `table_part` and `col_part`.
- If `table_part` is in `valid_table_names` AND `col_part` exists in the table's column
  list (cross-check against the exported Table TML) → keep as-is.
- If `table_part` is not in `valid_table_names` → flag for user review (the table name
  may have been aliased differently in this Model).

**Class C — Bare name, no `::`:**
Search for the column by display name across all Model columns:

```python
match = col_by_name.get(token)
```

If found: translate to the table-qualified form using the column's `column_id`:

```python
match = col_by_name.get(token)
if match and "column_id" in match:
    rewrites[f"[{token}]"] = f"[{match['column_id']}]"
```

This replaces `[Amount]` with `[DM_ORDER_DETAIL::LINE_TOTAL]`, matching the convention
used by all existing Model formulas. [OPEN ITEMS #3 — bare display-name refs untested;
`TABLE::COLUMN_ID` translation is confirmed working]

If not found and not a known formula name: the reference is ambiguous. Show the user the
Model's columns and ask for a mapping:

```
Column reference [Prior Year Revenue] in formula "{formula_name}" was not found in
"{model_name}".

  Is it:
    F  Another formula — enter the formula or column name as it appears in the Model: ___
    C  Map to a Model column — here are the available columns:

  Model columns (first 20 shown — enter a search term to filter):
    1  Revenue           MEASURE   (FACT_ORDERS::AMOUNT)
    2  Cost              MEASURE   (FACT_ORDERS::COST)
    3  Order Count       MEASURE   (formula_Order Count)
    ...

  Enter F or the column number:
```

After mapping, record the substitution:

```python
rewrites[f"[{token}]"] = f"[{resolved_name}]"
```

Apply all rewrites to produce `{rewritten_expr}` for each formula.

---

## Step 10 — Build Updated Model TML

**Generate formula IDs** following the convention from
[thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md):
`"formula_"` + name (spaces preserved).

```python
def make_formula_id(name):
    return f"formula_{name}"

for f in formulas_to_add:
    fid = make_formula_id(f["name"])
    # Disambiguate if the id already exists (should not happen after Step 8, but be safe)
    if fid in formula_ids_in_model:
        fid = f"formula_{f['name']}_promoted"
    f["_generated_id"] = fid
```

**Build `formulas[]` entries** (no `aggregation:` — that belongs in `columns[]` only):

```python
new_formula_entries = []
for f in formulas_to_add:
    entry = {"id": f["_generated_id"], "name": f["name"], "expr": f["rewritten_expr"]}
    # Include column_type in formulas[] only if present in source Answer TML
    if f.get("column_type"):
        entry.setdefault("properties", {})["column_type"] = f["column_type"]
    new_formula_entries.append(entry)
```

**Infer `column_type` and `aggregation`.** Answer formula entries do not carry these
fields — they live on the Model column. Infer from the expression:

```python
import re

AGGREGATE_FUNCS = re.compile(
    r'\b(sum|count|count_distinct|unique\s+count|average|min|max|median|stddev|'
    r'variance|sum_if|unique_count_if|cumulative_\w+|moving_\w+|group_aggregate|'
    r'group_\w+|rank|rank_percentile|last_value|first_value)\s*\(',
    re.IGNORECASE,
)

def infer_column_type(expr):
    """Return MEASURE if any aggregate function found, else ATTRIBUTE."""
    return "MEASURE" if AGGREGATE_FUNCS.search(expr) else "ATTRIBUTE"

def infer_aggregation(expr, column_type):
    """Return aggregation for MEASURE formula columns.
    ThoughtSpot ignores the aggregation value on formula columns at query time —
    the formula expr is self-contained. SUM is the convention for all MEASURE formulas."""
    if column_type != "MEASURE":
        return None
    return "SUM"

for f in formulas_to_add:
    f["_column_type"] = infer_column_type(f["expr"])
    f["_aggregation"] = infer_aggregation(f["expr"], f["_column_type"])
```

**Build `columns[]` entries:**

```python
new_column_entries = []
for f in formulas_to_add:
    props = {"column_type": f["_column_type"]}
    if f["_aggregation"]:
        props["aggregation"] = f["_aggregation"]  # MEASURE → SUM; ATTRIBUTE → omitted
    entry = {"name": f["name"], "formula_id": f["_generated_id"], "properties": props}
    new_column_entries.append(entry)
```

**Merge into a deep copy of the Model TML:**

```python
import copy

updated = copy.deepcopy(model_tml)
m = updated["model"]

# Remove overwrite targets first
overwrite_names = {f["name"] for f in formulas_to_overwrite}
if overwrite_names:
    m["formulas"] = [x for x in m.get("formulas", []) if x.get("name") not in overwrite_names]
    m["columns"]  = [x for x in m.get("columns",  []) if x.get("name") not in overwrite_names]

# Append new formulas and columns
m.setdefault("formulas", []).extend(new_formula_entries)
m["columns"].extend(new_column_entries)

# Merge parameters
if params_to_promote:
    overwrite_param_names = {p["name"] for p in params_to_overwrite}
    if overwrite_param_names:
        m["parameters"] = [
            x for x in m.get("parameters", [])
            if x.get("name") not in overwrite_param_names
        ]
    new_param_entries = [build_model_param_entry(p) for p in params_to_promote]
    m.setdefault("parameters", []).extend(new_param_entries)
```

**Run the self-validation checklist** from
[thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) — all 12
checks, silently, before showing the user. The checks most critical for formula promotion:

- **#7** — No `aggregation:` in any `formulas[]` entry
- **#8** — No duplicate display names across all `columns[]` entries
- **#10** — Every `formulas[].id` has a matching `formula_id:` in `columns[]`
- **#11** — Any `expr` containing `{ }` curly braces uses `>-` block scalar encoding
- **#12** — `guid:` is at the document root (not nested inside `model:`)

Fix any issues silently before continuing.

**Serialize to YAML:**

```python
import yaml

def _str_representer(dumper, data):
    if '\n' in data or ('{' in data and '}' in data):
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='>')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, _str_representer)
updated_yaml = yaml.dump(updated, allow_unicode=True, default_flow_style=False)
```

Verify that the GUID is the first key in the serialized YAML (required for in-place
update). If it is not, prepend it:

```python
if not updated_yaml.strip().startswith("guid:"):
    updated_yaml = f"guid: {model_guid_from_export}\n" + updated_yaml
```

---

## Step 11 — Checkpoint

Before importing, show a summary:

```
Ready to update "{model_name}":

  Formulas to add:
    + Profit Margin    MEASURE    →  [Revenue] - [Cost]
    + YoY Growth %     MEASURE    →  ( [Revenue] - [Prior Year Revenue] ) / ...

  Formulas to overwrite:
    ~ High Value Flag  ATTRIBUTE  →  if ( [Revenue] > 10000 ) then 'High' else 'Low'

  Parameters to add:       (shown only when params_to_promote is non-empty)
    + today    DATE    dynamic default: TODAY

  Parameters to overwrite: (shown only when any param is marked overwrite)
    ~ rate     INT64   default: 40

  Source Answer:   "{answer_name}"
  Target Model:    "{model_name}"
  Import policy:   ALL_OR_NONE

Proceed? (Y / N):
```

If N, ask what the user would like to change and loop back to the relevant step.

---

## Step 12 — Import Updated Model TML

Write the YAML to a temp file and pipe it to the `ts` CLI:

```python
import subprocess, json

temp_path = "/tmp/ts_promote_formula_model.yaml"
with open(temp_path, "w") as f:
    f.write(updated_yaml)

payload = json.dumps([updated_yaml])

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml import --profile '{profile_name}' --policy ALL_OR_NONE --no-create-new"],
    input=payload,
    capture_output=True,
    text=True,
)
import_response = json.loads(result.stdout) if result.stdout.strip() else {}
```

Parse the response:
- `status_code: "OK"` → success, continue to Step 13
- Any other status → extract the error message and show the user (see Error Handling)

**Permission error (403 / `UNAUTHORIZED`):**

```
Import failed: you do not have edit access to "{model_name}".

Contact the Model owner or a ThoughtSpot admin to request MODIFY or FULL access.
```

Stop here.

**Validation error:** Show the exact error, diagnose using the self-validation checklist,
fix the TML, and ask the user if they would like to retry.

---

## Step 13 — Verify and Report

Extract the updated Model GUID from the import response (should match `{model_guid}`).

```
Formula(s) successfully promoted to "{model_name}".

  Added:       {comma-separated names of added formulas}
  Overwritten: {comma-separated names of overwritten formulas}  (if any)

  Model:  {base_url}/#/data/tables/{model_guid}

The formulas are now available to anyone who searches against "{model_name}".
To verify, open the Model URL above and check the Columns section for the new formulas.
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts auth whoami` returns 401 | Token expired — follow the refresh steps in `/ts-profile-thoughtspot` |
| Answer TML has no `formulas[]` | Answer may not have custom formulas — see Step 3 |
| Data source is a Worksheet | Worksheets are legacy — inform user, suggest `/ts-object-model-builder` to migrate first |
| Import returns 403 / UNAUTHORIZED | User lacks edit access on the Model — see Step 6 |
| Import: `FORMULA is not a valid aggregation type` | `aggregation:` is in a `formulas[]` entry — move it to the matching `columns[]` entry |
| Import: `duplicate column name` | A promoted formula name conflicts with an existing column — rename or skip it in Step 8 |
| Import: `column_id not found` | A column reference in the formula expression doesn't resolve — revisit Step 9 mapping |
| Import: model already exists with same name | `guid:` may be missing or mis-placed — check Step 10 GUID placement |
| Import creates a duplicate model instead of updating | `--no-create-new` flag is missing from the import command — add it and delete the duplicate |
| Import: `Found multiple data sources with same name` | Model TML was exported without `--fqn` — `model_tables[]` entries lack `fqn:` GUIDs. Re-export with `--fqn` (Step 7 already specifies this) |
| `pyyaml` not installed | `pip install pyyaml` |
| Import: `parameter not found` or formula resolves to NULL after import | Parameter name in the formula expression does not match a `model.parameters[].name` — verify the promoted parameter name matches exactly (case-sensitive) |
| `dynamic_default_date` rejected on import | Older ThoughtSpot instances may not support `dynamic_default_date` at the model level. Fall back to a static `default_value` — ask the user for a sensible default (e.g. today's date as a string `"2026-04-22"` for a DATE parameter). |

---

## Cleanup

```bash
rm -f /tmp/ts_promote_formula_model.yaml
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.2.0 | 2026-04-24 | Add Step 0 session plan with confirmation gate |
| 1.1.0 | 2026-04-22 | Add parameter promotion (option P in Step 4, duplicate detection, merging) |
| 1.0.0 | 2026-04-24 | Initial versioned release |
