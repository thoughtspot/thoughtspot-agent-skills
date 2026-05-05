# Update Mode (Mode C) — Design Spec

**Skill:** `ts-convert-from-snowflake-sv`  
**Date:** 2026-05-05  
**Status:** Approved spec — pending implementation in SKILL.md  
**Version impact:** MINOR bump (new capability, no breaking change to existing modes A/B)

---

## What this adds

A new Mode C ("Update existing") that takes a changed Snowflake Semantic View and an
existing ThoughtSpot Model and produces a targeted change set — adding new columns,
surfacing changed descriptions and synonyms for per-column review, and flagging removed
columns without auto-deleting them. `ai_context` and Data Model Instructions are never
touched; the skill hands off to `/ts-object-model-coach` after import.

---

## Step 1.5 — Updated mode menu

Replace the existing two-option menu with:

```
Choose a conversion mode:
  A — Convert ONE Semantic View → new ThoughtSpot Model       (default)
  B — Merge MULTIPLE Semantic Views → new ThoughtSpot Model
  C — Update an EXISTING ThoughtSpot Model from a changed Semantic View
```

Modes A and B are unchanged. Mode C triggers the workflow below.

---

## Mode C workflow

### Step 1.5C — Identify both objects

```
Semantic View (source — the updated version):
  Enter database.schema.view_name or press Enter to browse: _______

ThoughtSpot Model (target — the existing model to update):
  G — I have a GUID
  S — Search by name

Enter G / S:
```

Store `{sv_name}` and `{model_guid}`.

The user always selects both objects explicitly. The skill does not attempt to
auto-match by name — model and SV names often diverge after the initial creation.

---

### Step 2C — Fetch both in parallel

Run simultaneously:

```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{sv_name}');
```

```bash
ts tml export {model_guid} --profile {profile} --fqn --associated --parse
```

Parse the SV DDL using the existing Step 4 logic. Extract from the Model bundle:

```python
existing = {
    col["name"]: {
        "description":  col.get("description", ""),
        "synonyms":     col.get("properties", {}).get("synonyms", []),
        "ai_context":   col.get("properties", {}).get("ai_context"),  # read-only reference
        "formula_id":   col.get("formula_id"),
        "column_id":    col.get("column_id"),
    }
    for col in model_tml["model"]["columns"]
}
existing_formulas = {f["id"]: f["expr"] for f in model_tml["model"].get("formulas", [])}
```

---

### Step 3C — Compute the change set

```python
sv_cols    = set(sv_parse["columns"].keys())   # keyed by (table_alias, view_col)
model_cols = set(existing.keys())

change_set = {
    "new_columns":            sv_cols - model_cols,        # add fully
    "removed_columns":        model_cols - sv_cols,        # flag only — never auto-remove
    "modified_descriptions":  [],   # SV comment ≠ model description
    "modified_synonyms":      [],   # SV aliases ≠ model synonyms
    "modified_expressions":   [],   # formula expression changed in SV
    "join_changes":           [],   # relationships in SV differ from model joins
    "no_change":              [],
}

for col_key in sv_cols & model_cols:
    sv_col = sv_parse["columns"][col_key]
    ts_col = existing[col_key]

    if sv_col["description"] and sv_col["description"] != ts_col["description"]:
        change_set["modified_descriptions"].append(...)

    sv_synonyms = set(sv_col.get("synonyms", []))
    ts_synonyms = set(ts_col["synonyms"])
    if sv_synonyms != ts_synonyms:
        change_set["modified_synonyms"].append(...)

    if col_key in sv_formulas and ts_col["formula_id"]:
        sv_expr  = sv_formulas[col_key]
        ts_expr  = existing_formulas.get(ts_col["formula_id"], "")
        if _expressions_differ(sv_expr, ts_expr):
            change_set["modified_expressions"].append(...)
```

#### Formula expression normalisation (`_expressions_differ`)

Before comparing, normalise both expressions:

1. Strip leading/trailing whitespace
2. Collapse internal whitespace (tabs, multiple spaces → single space)
3. Case-fold SQL keywords and function names (`SUM`, `CASE WHEN`, `YEAR_NUMBER` → lowercase)
4. Normalise string literal quote style (`"value"` → `'value'` for comparison only)
5. **Do NOT fold column/table identifiers** — extract content inside `[]` and `{}` refs,
   compare them verbatim (case changes in identifiers are real diffs)

```python
import re

def _normalise_expr(expr: str) -> str:
    # Extract and stash bracket/brace refs so they survive lowercasing
    refs, i = {}, 0
    def _stash(m):
        nonlocal i
        key = f"__REF{i}__"
        refs[key] = m.group(0)
        i += 1
        return key
    out = re.sub(r'\[[^\]]+\]|\{[^}]+\}', _stash, expr)
    out = re.sub(r'\s+', ' ', out.strip()).lower()
    for key, val in refs.items():
        out = out.replace(key, val)
    return out

def _expressions_differ(a: str, b: str) -> bool:
    return _normalise_expr(a) != _normalise_expr(b)
```

---

### Step 4C — Present the diff and collect decisions

Display the summary, then per-section review tables. Require the user to edit and
type `done` before proceeding.

#### Summary header

```
=== Change set for "{model_name}" ===

  ✚ New columns:              {N}   (will be added with generated synonyms + descriptions)
  ✖ Removed columns:          {M}   (flagged only — must be removed manually if intended)
  ✏ Modified descriptions:    {P}   (UPDATE / KEEP per column)
  ✏ Modified synonyms:        {Q}   (UPDATE / KEEP / MERGE per column)
  ~ Modified expressions:     {R}   (flagged for re-translation — confirm each)
  ~ Join changes:             {S}   (flagged for review — confirm each)
  = Unchanged columns:        {T}   (no action)
```

#### Modified descriptions — per-column table

| Column | Current (TS Model) | New (from SV) | Action |
|---|---|---|---|
| Amount | Total sales amount in USD | Total revenue in local currency | UPDATE / **KEEP** |

Default: `KEEP`. User changes to `UPDATE` for any column where the SV value is preferred.

#### Modified synonyms — per-column table

| Column | Current synonyms | New synonyms (from SV) | Action |
|---|---|---|---|
| Product Category | category, product group | category, dept | **MERGE** / UPDATE / KEEP |

Three options:
- `MERGE` *(default)* — union of existing and SV synonyms; additive, preserves any
  synonyms added via coaching that are absent from the SV
- `UPDATE` — replace existing synonyms entirely with the SV set
- `KEEP` — ignore the SV change, leave existing synonyms untouched

The default is `MERGE`. The user can change any row to `UPDATE` or `KEEP` in the review
table before typing `done`.

#### Removed columns — list with warning

```
⚠ The following columns exist in the ThoughtSpot Model but are no longer in the SV.
  They are NOT removed automatically — removal may break dependent Answers and Liveboards.
  To remove them safely: run /ts-dependency-manager first, then edit the Model TML manually.

  - Discount Percentage
  - Legacy Region Code
```

No action column for removed columns — they are informational only.

#### Modified expressions — per-column confirmation

Show old and new formula side-by-side and require explicit `YES / SKIP` per column
before re-translating. Do not bulk-apply expression changes.

---

### Step 5C — Build the updated Model TML

Deep-copy the existing Model TML. Apply only the confirmed changes:

| Change type | Action |
|---|---|
| New column | Generate using existing Step 8 + Step 9 logic (same as create mode) |
| Modified description with `UPDATE` | Write to `column.description` |
| Modified description with `KEEP` | Leave untouched |
| Modified synonyms with `MERGE` | Union existing and SV synonym sets |
| Modified synonyms with `UPDATE` | Replace `properties.synonyms[]` with SV set |
| Modified synonyms with `KEEP` | Leave untouched |
| Modified expression, confirmed `YES` | Re-translate using Step 9 logic; update `formulas[].expr` |
| Modified expression, `SKIP` | Leave untouched |
| Join change, confirmed | Update `model.joins[]` or `referencing_join` |
| `ai_context` on any column | **Never touch** |
| Data Model Instructions | **Never touch** |
| Removed columns | **Never touch** |

Import with `--no-create-new` to update in place. The import will fail if the model
GUID is not found — surface the error clearly and stop.

---

### Step 6C — Post-import coaching handoff

After a successful import, always surface:

```
✓ Model "{model_name}" updated.

⚠ Coaching surfaces that may need review:

  Column AI Context
    {N_new} new columns added — no ai_context yet
    {M_updated} existing columns had descriptions or synonyms changed
    → Run /ts-object-model-coach → surface 1 to review and update ai_context

  Data Model Instructions
    Schema changes (new columns, expression changes, join changes) may affect
    Spotter's default behaviours — particularly time_defaults and aggregation_defaults.
    → Run /ts-object-model-coach → surface 5 to review Instructions

  Removed columns flagged above
    If you intend to remove any of the flagged columns, run /ts-dependency-manager
    first to assess downstream impact before editing the Model TML manually.
```

---

## What this spec does NOT change

- Modes A and B are unchanged
- `ai_context` is never written or modified by Mode C
- Data Model Instructions are never written or modified — handoff only
- Removed columns in the TS Model are never auto-deleted
