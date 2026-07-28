# Step 3 — LookML Parse Field Extraction Detail

Reference detail for **Step 3 — Parse LookML project**: the full field-by-field
extraction lists for the model file (§3a) and each view file (§3b). The step's spine
(the connection-name confirmation flow §3c and the field dependency graph resolution
§3d) stays in `SKILL.md` — this file is what the spine links out to for the exact
per-element field list.

---

## 3a. Parse the model file — full field list

From `.model.lkml` extract:
- `connection:` → ThoughtSpot connection name (must match exactly, by name not GUID — Invariant I6)
- `include:` → file globs to expand; locate all referenced view files
- Each `explore { ... }` block:
  - `explore` name and optional `label:`
  - `sql_table_name:` override if present on the explore itself
  - Each `join { ... }` inside the explore:
    - join name (= the view being joined)
    - `type:` → join type (`left_outer`, `full_outer`, `inner`, `cross`)
    - `relationship:` → cardinality (`many_to_one`, `one_to_many`, `many_to_many`, `one_to_one`)
    - `sql_on:` → join condition (contains `${view.field}` references — resolve at Step 3d)

## 3b. Parse each view file — full field list

From each `.view.lkml` extract:
- `view: name` → ThoughtSpot table name
- `sql_table_name:` → physical table (format: `DATABASE.SCHEMA.TABLE`)
- `derived_table:` → if present, flag as SQL View (special handling — see Step 5b)
- Each `dimension { ... }` block:
  - `type:` → string / number / yesno / date / time / tier / duration / location
  - `sql:` → physical column reference (usually `${TABLE}.COL`)
  - `label:` → ThoughtSpot display name (prefer this over field name when present)
  - `hidden: yes` → note but do NOT skip — hidden fields may be required by measures
  - `primary_key: yes` → `column_type: ATTRIBUTE`
  - `value_format_name:` → informational only (no ThoughtSpot equivalent; record in summary)
- Each `measure { ... }` block:
  - `type:` → sum / count / count_distinct / average / max / min / number
  - `sql:` → expression (may contain `${TABLE}.COL`, `${field}`, or `${view.field}`)
  - `label:` → ThoughtSpot display name
  - `filters:` → conditional measure (translate to `count_if` / `sum_if` / `average_if`)
  - `value_format_name:` → informational only
