# Console and Report Templates — Steps 8A, 10, 10-FILE, 12

Reference detail for the console/report text emitted by **Step 8A — Discover
and verify existing ThoughtSpot Table objects**, **Step 10 — Review
checkpoint**, **Step 10-FILE — Output TML files (file-only mode)**, and
**Step 12 — Produce summary report** in SKILL.md. The spine (what data feeds
each field, when to show it, what happens on each user response) stays in
SKILL.md — this file is what gets printed.

---

## Step 8A — Table plan confirmation console template

```
Table Plan:
  ✓  {TABLE_NAME}  — found (GUID: {guid}) — all {n} columns present → use as-is
  ⚠  {TABLE_NAME}  — found (GUID: {guid}) — missing {n} columns: {COL_A}, {COL_B} → update
  ✗  {TABLE_NAME}  — not found in ThoughtSpot → create new

Actions to be taken:
  • Update {TABLE_NAME}: add {n} missing columns
  • Create {TABLE_NAME}: {n} columns from Databricks schema

No changes have been made yet. Proceed? (yes/no):
```

---

## Step 10 — Review checkpoint console template

```
Model to import: {view_name}
Source: {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
Filter: {parsed.json "filter" expr if summary filter_applied else "none"}

Tables:
  ✓ {tables[].name} (fqn: {tables[].fqn}) — alias: {tables[].alias}

Columns ({n} total):
  ATTRIBUTE: {columns.attributes}
  MEASURE:   {columns.measures}
  Formulas:  {formula_count} formula(s)

Formula translations:
  ✓ {name}: {mv expr from parsed.json} → {ts_expr}     # translated[]
  ⚠ {name}: OMITTED — {reason}                          # skipped[]

Window measures (review required):
  ⚠ WINDOW {name}: {ts_expr}
    Assumption: {annotation.detail}

If any window measures exist, display this warning:

  ⚠ Window measures assume daily grain (one row per day for trailing/rolling).
    Verify that the source data matches this assumption — if the table has
    multiple rows per day, moving_sum/moving_average will over-count.

Spotter (AI search): enabled / disabled

Proceed with import?
  yes  — import to ThoughtSpot
  no   — cancel
  file — write TML files without importing (for environments where you lack
          DATAMANAGEMENT access, or to review the TML before committing)
```

---

## Step 10-FILE — File-only mode report template

```
TML files written:
  {model_name}.model.tml    — ThoughtSpot Model TML
  {table_name}.table.tml   — ThoughtSpot Table TML (if new tables were needed)

To import to ThoughtSpot when you have access:

  1. Package all .tml files into a zip:
       zip {model_name}_tml.zip *.tml

  2. In ThoughtSpot: Data → TML Import → upload the zip
     (table TMLs will import first, then the model)

  3. Or import via CLI:
       ts tml import --file {model_name}.model.tml --policy ALL_OR_NONE --profile {profile}

  Note: On first import, omit `guid` from the TML (already omitted here). ThoughtSpot
  will assign a GUID — save it from the import response if you need to update the model later.
```

---

## Step 12 — Summary report template

```
## Model Import Complete

**Model:** {view_name}
**GUID:** {created_guid}
**ThoughtSpot URL:** {base_url}/#/model/{created_guid}
**Source:** {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
**Filter:** {filter_expr or "none"}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE ({agg}) | {TABLE}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |
| ... | ... | ... |

### Formula Translation Log
| Column | Original Databricks SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{expr}` | ✓ Translated | `{ts_formula}` |
| {name} | `{expr}` | ⚠ Omitted | {reason} |

### Not Mapped
- Global filter: "{filter_expr}" — noted in model description, not enforced as a ThoughtSpot filter
- MV `version` field — metadata only, not stored in ThoughtSpot
```

### Suggested test questions template

```
### Suggested test questions for Spotter
1. "What is the total {measure_1} by {dimension_1}?"
2. "Show me {measure_2} for each {dimension_2}"
3. "What are the top 10 {dimension_1} by {measure_1}?"
```
