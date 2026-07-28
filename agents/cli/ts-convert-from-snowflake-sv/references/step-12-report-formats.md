This file serves **Step 10: Review checkpoint**, **Step 12: Produce summary report**,
and **Step 12.5: Import verified queries as NLS Feedback TML** in
`agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — the pre-import review console
template, the post-import summary report console template, and the NLS Feedback TML
template.

---

## Step 10 — Review checkpoint console template

```
Model to import: {view_name}
Tables:
  ✓ {FACT_TABLE} (GUID: {guid}) — fact table
  ✓ {DIM_TABLE}  (GUID: {guid}) — referencing_join: {join_name}
  ...

Columns ({n} total):
  ATTRIBUTE: {list of display names}
  MEASURE:   {list of display names}
  Formulas:  {list of display names}

Formula translations:
  ✓ {name}: {sql_expr} → {ts_formula}
  🔄 {name}: DOUBLE AGGREGATION — {outer_agg}(group_{inner_agg}(...))
  📐 {name}: FACT REFERENCE — inlines fact expression (from {fact_name})
  ⚠ {name}: OMITTED — {reason}

Filter labels ({n}):
  {name}: boolean formula (column only / also add as model filter?)

Verified queries ({n}):
  {name}: "{question}" → will import as NLS Feedback after Model import

Spotter (AI search): enabled / disabled

Proceed with import?
  yes  — import to ThoughtSpot
  no   — cancel
  file — write TML files without importing (for environments where you lack
          DATAMANAGEMENT access, or to review the TML before committing)
```

---

## Step 12 — Summary report console template

```
## Model Import Complete

**Model:** {view_name}
**GUID:** {created_guid}
**ThoughtSpot URL:** {base_url}/#/model/{created_guid}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE ({agg}) | {TABLE}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |
| ... | ... | ... |

### Formula Translation Log
| Column | Original SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{sql}` | ✓ Translated | `{ts_formula}` |
| {name} | `{sql}` | 🔄 Double aggregation | `{ts_formula}` |
| {name} | `{sql}` | 📐 Fact formula | `{ts_formula}` |
| {name} | `{sql}` | ⚠ Omitted | {reason} |

### Not Mapped
- Extension JSON (Cortex Analyst context): not translated to ThoughtSpot

### Facts Mapped ({n})
| Fact Name | Source Table | Expression | ThoughtSpot Formula |
|---|---|---|---|
| {name} | {table} | `{sql_expr}` | `{ts_formula}` |

### Identifier Resolution Summary
- Physical columns resolved: {n}
- Fact references resolved: {n}
- Double aggregation patterns: {n}
- Unresolvable references: {n} (see OMITTED above)

### Filter Labels ({n})
| Column | Source Expression | Type |
|---|---|---|
| {name} | `{boolean_expr}` | Boolean formula (ATTRIBUTE) |

### Verified Queries ({n})
| Query Name | Question | Status |
|---|---|---|
| {name} | {question} | ✓ Imported as NLS Feedback / ⚠ Manual review needed |
```

---

## Step 12.5 — NLS Feedback TML template

```yaml
guid: "{model_guid}"
nls_feedback:
  feedback:
  - id: "{index}"
    type: REFERENCE_QUESTION
    access: GLOBAL
    feedback_phrase: "{question_text}"
    search_tokens: "{translated_search_tokens}"
    rating: UPVOTE
    display_mode: UNDEFINED
    chart_type: KPI
```
