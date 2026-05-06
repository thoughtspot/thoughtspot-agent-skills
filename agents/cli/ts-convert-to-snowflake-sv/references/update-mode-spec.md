# Update Mode (Mode C) — Design Spec

**Skill:** `ts-convert-to-snowflake-sv`  
**Date:** 2026-05-05  
**Status:** Approved spec — pending implementation in SKILL.md  
**Version impact:** MINOR bump (new capability, no breaking change to existing modes A/B)

---

## What this adds

Two changes:

1. **Mode B (Split) is surfaced explicitly** in the mode menu. Split was previously
   a sub-flow within Mode A (triggered by Step 7.5 domain detection). It is now a
   first-class mode so the menu is consistent with `ts-convert-from-snowflake-sv`
   (A=single, B=multi, C=update).

2. **Mode C (Update existing)** takes a changed ThoughtSpot Model and an existing
   Snowflake Semantic View, shows the user a diff, and runs `CREATE OR REPLACE` only
   after the user confirms which additions and removals to apply.

---

## Step 1.5 — New mode menu (inserted after Step 1)

```
Choose a conversion mode:
  A — Convert ThoughtSpot Model → new Snowflake Semantic View    (default)
  B — Split ThoughtSpot Model → MULTIPLE Snowflake Semantic Views
  C — Update an EXISTING Snowflake Semantic View from a changed Model
```

**Mode A** — unchanged from the current skill. The split detection in Step 7.5
is suppressed; the skill produces one SV regardless of how many domains are detected.

**Mode B** — the current split flow (Step 7.5 `split_mode = True`) is now explicitly
triggered by selecting B. Step 7.5 runs unconditionally; the single/split prompt is
removed from Step 7.5 since the user already chose at Step 1.5.

**Mode C** — triggers the workflow below.

---

## Mode C workflow

### Step 1.5C — Identify both objects

```
ThoughtSpot Model (source):
  G — I have a GUID
  S — Search by name

Enter G / S: _______

Snowflake Semantic View to update (target):
  Enter database.schema.view_name or press Enter to browse: _______
```

Store `{model_guid}` and `{sv_name}`.

The user always selects both objects explicitly. The skill does not attempt to
auto-match by name — model and SV names often diverge after the initial creation.

---

### Step 2C — Fetch both in parallel

Run simultaneously:

```bash
ts tml export {model_guid} --profile {profile} --fqn --associated --parse
```

```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{sv_name}');
```

Generate the full new SV DDL using the existing Steps 3–9 logic (same as Mode A,
but do not execute in Snowflake yet — treat it as a dry run).

Parse the existing SV DDL to extract its current column set.

---

### Step 3C — Compute the change set

```python
sv_cols_existing = parse_sv_ddl(existing_sv_ddl)   # keyed by column name
sv_cols_new      = generated_sv["columns"]

change_set = {
    "new_columns":            set(sv_cols_new) - set(sv_cols_existing),
    "removed_columns":        set(sv_cols_existing) - set(sv_cols_new),   # user confirms
    "modified_expressions":   [],   # expression changed for an existing column
    "modified_descriptions":  [],   # comment= changed for an existing column
    "no_change":              [],
}

for col in set(sv_cols_new) & set(sv_cols_existing):
    if _expressions_differ(sv_cols_new[col]["expr"], sv_cols_existing[col]["expr"]):
        change_set["modified_expressions"].append(...)
    if sv_cols_new[col]["description"] != sv_cols_existing[col]["description"]:
        change_set["modified_descriptions"].append(...)
```

#### Formula expression normalisation (`_expressions_differ`)

Before comparing, normalise both expressions:

1. Strip leading/trailing whitespace
2. Collapse internal whitespace (tabs, multiple spaces → single space)
3. Case-fold SQL keywords and function names (→ lowercase)
4. Normalise string literal quote style (`"value"` → `'value'` for comparison only)
5. **Do NOT fold column/table identifiers** — case changes in identifiers are real diffs

```python
import re

def _normalise_expr(expr: str) -> str:
    refs, i = {}, 0
    def _stash(m):
        nonlocal i
        key = f"__REF{i}__"
        refs[key] = m.group(0)
        i += 1
        return key
    # Stash quoted identifiers before lowercasing
    out = re.sub(r'"[^"]*"', _stash, expr)
    out = re.sub(r'\s+', ' ', out.strip()).lower()
    for key, val in refs.items():
        out = out.replace(key, val)
    return out

def _expressions_differ(a: str, b: str) -> bool:
    return _normalise_expr(a) != _normalise_expr(b)
```

---

### Step 4C — Present the diff and collect decisions

```
=== Change set for "{sv_name}" ===

  ✚ New columns:              {N}   (will be added)
  ✖ Removed columns:          {M}   (you confirm each — see below)
  ~ Modified expressions:     {R}   (will be updated — review before confirming)
  ✏ Modified descriptions:    {P}   (will be updated automatically)
  = Unchanged columns:        {T}   (no change)
```

#### Removed columns — per-column confirmation

Require explicit confirmation for each removed column rather than a blanket accept.
Pre-fill all as unchecked (KEEP):

```
These columns are in the current SV but not in the updated Model.
Confirm removal from the SV? (unchecked = keep in the new SV)

  [ ] Discount Percentage     — currently: SUM(ORDER_DETAIL.DISCOUNT_AMOUNT)
  [ ] Legacy Region Code      — currently: DIM_REGION.REGION_CODE

Check each to remove it. Leave unchecked to carry it forward from the existing SV.
```

Unchecked columns are re-added to the generated DDL verbatim from the existing SV DDL —
they are preserved even though the Model no longer includes them. This avoids
silently breaking any Cortex Analyst queries or dashboards that reference the SV directly.

#### Modified expressions — side-by-side review

Show old and new DDL expression for each changed column. User confirms before applying.

---

### Step 5C — Build the final DDL and execute

Assemble the final DDL from:
- All new columns (from generated DDL)
- All unchanged columns (from generated DDL)
- All confirmed-removed columns: omit
- All unchecked (kept) removed columns: carry forward from existing SV DDL verbatim
- All confirmed modified expressions: use generated DDL value
- All modified descriptions: use generated DDL value (auto-applied, no confirmation needed)

Run `CREATE OR REPLACE SEMANTIC VIEW {sv_name} ...` with the assembled DDL.

The existing Steps 11–12b (checkpoint + verify) apply unchanged.

---

## What this spec does NOT change

- Modes A and B conversion logic is unchanged
- Mode B split detection (Step 7.5) moves under the Mode B branch — no logic change,
  only the trigger point changes (explicit menu selection vs. domain detection prompt)
- No ThoughtSpot Model TML is modified in Mode C — this skill only writes to Snowflake
