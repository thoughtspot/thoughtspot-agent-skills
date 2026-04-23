# ThoughtSpot → Unity Catalog Property Coverage

Full reference for what ThoughtSpot TML properties map to Unity Catalog Metric View,
what is partially migrated, and what cannot be migrated at all.

---

## Properties That Map

| ThoughtSpot | UC Metric View | Notes |
|---|---|---|
| Model / Worksheet `name` | View name in DDL | snake_cased; used in `CREATE VIEW` statement |
| Model / Worksheet `description` | `comment:` at top level | Passed through unchanged |
| `model_tables[]` / `tables[]` | `source:` + `joins:` | Physical names from Table TML |
| `sql_view` (simple `SELECT *`) | `source:` or join `source:` | Resolved to physical table |
| `joins[]` (inline `on`) | `joins:` array | Translated to hierarchical join tree |
| `joins[]` (`referencing_join`) | `joins:` array | Resolved from Table TML `joins_with` |
| `ATTRIBUTE` column (non-date) | `dimensions[]` | |
| `ATTRIBUTE` column (date/timestamp) | `dimensions[]` | UC has no `time_dimensions`; all dates → `dimensions` |
| `MEASURE` column | `measures[]` | Aggregation embedded in `expr` |
| Formula column — translatable aggregate | `measures[]` | Expression translated per formula translation reference |
| Formula column — translatable non-aggregate | `dimensions[]` | Rare; dimension formulas go here |
| `synonyms[]` | `synonyms[]` | Passed through |
| `column.description` | `comment:` on field | Passed through |
| `ai_context` | `comment:` on field | **Partial** — see below |
| `column.display_name` / display name | `display_name:` on field | Passed through |

---

## Partial Migrations

### AI Context (`ai_context`)

**Status: Partial — directive semantics lost**

ThoughtSpot `ai_context` is a per-column AI directive for Spotter. Unity Catalog `comment`
is human-facing and also read by Genie for context, but is not an instruction.

Action: Merge into `comment:` with the prefix `[TS AI Context]`:
```
comment: "[TS AI Context] {ai_context text}"
```

If both `description` and `ai_context` are present:
```
comment: "{description}\n[TS AI Context] {ai_context text}"
```

**User review action:** Examine AI context entries in the Unmapped Report and decide
whether to rewrite them as plain UC `comment` values for Genie.

---

### `format_pattern`

**Status: Partial — UC has limited format support**

ThoughtSpot format strings (`#,##0.00`, `dd/MMM/yyyy`) do not map directly. UC Metric
View `format:` supports coarser options:

| ThoughtSpot format | Best UC mapping |
|---|---|
| Currency formats (`$#,##0.00`) | `format: {type: currency, currency_code: USD}` |
| Percentage formats (`#0.00%`) | `format: {type: percentage}` |
| Number formats (`#,##0.00`) | `format: {type: number, decimal_places: {type: exact, places: 2}}` |
| Date formats (`dd/MMM/yyyy`) | No direct UC equivalent — log in Unmapped Report |
| Custom string formats | No UC equivalent — log in Unmapped Report |

---

### Multi-Column Join Conditions (AND)

**Status: Partial — AND supported, OR not**

`AND`-separated join conditions map to multi-condition `on:` clauses:
`on: source.k1 = dim.k1 AND source.k2 = dim.k2`

`OR` conditions have no UC equivalent. Log in Unmapped Report as requiring manual SQL.

---

### Chained / Multi-Hop Join Paths

**Status: Partial — unrolled into nested UC join tree**

Multi-hop chains in Worksheet `table_paths` (e.g. `fact → dim_a → dim_b`) map to
nested `joins:` entries in UC. The join tree is built from the source table outward.
Flag at the checkpoint when the join tree is more than 2 levels deep for user review.

---

### `sql_view` (complex SQL)

**Status: Partial — requires user decision**

Simple `SELECT * FROM single_table` views are resolved to the physical table automatically.
Complex views require one of three options presented at the Step 10 checkpoint:

| Option | Action |
|---|---|
| C (Create) | Create a Databricks VIEW from the sql_query, use it as source or join source |
| M (Map) | User provides an existing catalog.schema.table to use instead |
| S (Skip) | Omit all columns sourced from this view; log in Unmapped Report |

---

## Hard Blockers — No Migration Possible

### Parameters (`parameters[]`)

**Status: Hard blocker**

ThoughtSpot runtime parameters (date ranges, metric selectors) have no UC Metric View
equivalent. All parameter-referencing formulas are omitted. Parameters are listed in
the Unmapped Report.

---

### `sql_string_op` Formulas with Snowflake-Specific Syntax

**Status: Hard blocker — requires manual rewrite**

ThoughtSpot `sql_string_op` formulas containing Snowflake-specific functions that have
no Databricks equivalent must be rewritten manually. See the formula translation reference
for a substitution list. Flag for user review.

---

### Window / LOD Functions — Complex Groupings

**Status: Partially translatable**

`moving_*`, `cumulative_*` → UC `window:` config (translatable — see formula reference)
`last_value`, `first_value` → UC `window: semiadditive` (translatable — see formula reference)
`group_aggregate(sum(m), query_groups(), query_filters())` → `SUM(m)` (translatable)

Untranslatable:
- `first_value(...)` as a scalar (non-semi-additive) formula
- `last_value_in_period(...)`, `first_value_in_period(...)`
- `group_aggregate` with fixed grouping sets or non-simplifiable outer aggregates
- `rank()` / `rank_percentile()` in aggregate measure context

---

### Column Groups / Data Panel Groups

**Status: Hard blocker**

ThoughtSpot `column_groups` and `data_panel_column_groups` have no UC equivalent.
Membership is documented in the Unmapped Report. Re-create in Genie or dashboard layer.

---

### Default Date Buckets (`default_date_bucket`)

**Status: Hard blocker**

Time grain defaults (DAILY, WEEKLY, MONTHLY) are not supported in UC Metric Views.
Log in Unmapped Report.

---

### Many-to-Many / Bridge Table Patterns

**Status: Hard blocker**

UC Metric Views support star and snowflake schemas with many-to-one relationships only.
If the ThoughtSpot model contains a bridge/junction table creating a many-to-many
relationship, document it in the Unmapped Report. Options for users:
- Create a pre-aggregated view that flattens the bridge table
- Restructure the model to expose one side of the relationship
- Use direct SQL queries for cross-bridge analysis

---

### Model-Level Filters (`filters[]`)

**Status: Partially supported**

ThoughtSpot model filters can be mapped to UC's `filter:` top-level key:
```yaml
filter: "o_orderdate >= '2020-01-01'"
```
Simple single-condition filters translate directly. Complex filters with multiple
conditions, OR logic, or parameter references require manual review.

---

### Custom Sort Order (`custom_order`)

**Status: Hard blocker**

Explicit value sort order for dimension values. Apply in Genie configuration or
dashboard layer. Log in Unmapped Report.

---

### Row-Level Security (`is_bypass_rls`)

**Status: Hard blocker**

ThoughtSpot RLS rules are not exported in TML. Must be re-implemented using Databricks
Unity Catalog table permissions, column masks, or row filters.

---

### Geo Configuration (`geo_config`)

**Status: Hard blocker**

Geospatial column configuration has no UC Metric View equivalent. Affected columns are
migrated as regular `dimensions` with a note in the Unmapped Report.

---

## Silently Dropped (No Action Needed)

| ThoughtSpot Property | Reason |
|---|---|
| `spotter_config.is_spotter_enabled` | ThoughtSpot-specific; no UC equivalent |
| `join_progressive` | ThoughtSpot execution hint |
| `index_type` (DONT_INDEX / INDEX) | ThoughtSpot search hint |
| `synonym_type` (USER_DEFINED / SYSTEM) | Metadata about synonyms, not the synonyms themselves |
| `obj_id` | ThoughtSpot internal content ID |
| `was_auto_generated` (formulas) | ThoughtSpot metadata flag |
| `db_column_properties.data_type` | UC infers types from SQL; not declared in YAML |

---

## Unmapped Properties Report Format

Generate this report at Step 10 (Checkpoint) for every model conversion. Omit any
section that has no entries for the current model.

```
### Unmapped Properties Report

#### Parameters (not migrated)
| Parameter Name | Data Type | Default Value | Used In Formula |
|---|---|---|---|
| {name} | {type} | {default} | {column list} |

#### Column Groups (not migrated)
| Group Name | Columns |
|---|---|
| {group} | {comma-separated column names} |

#### AI Context (merged into comment with [TS AI Context] prefix)
| Column | Original ai_context |
|---|---|
| {name} | {ai_context text} |

#### Format Patterns (partial mapping)
| Column | format_pattern | UC format mapping | Review needed? |
|---|---|---|---|
| {name} | {pattern} | {type: currency/number/percentage or NONE} | yes/no |

#### Default Date Buckets (not migrated)
| Column | default_date_bucket |
|---|---|
| {name} | {bucket} |

#### Model-Level Filters (mapped to UC filter: or requires review)
| Condition | Mapped? | UC filter expression |
|---|---|---|
| {condition} | yes/no | {filter expr or MANUAL REVIEW} |

#### Many-to-Many Patterns (not migrated)
| Bridge Table | Left Table | Right Table | Suggested Approach |
|---|---|---|---|
| {bridge} | {left} | {right} | Pre-aggregate / Restructure |

#### SQL Views Resolved Automatically
| sql_view Name | sql_query | Resolved To |
|---|---|---|
| {name} | {sql_query} | {catalog}.{schema}.{db_table} |

#### SQL Views Requiring User Decision (complex SQL)
| sql_view Name | sql_query | Decision | Outcome |
|---|---|---|---|
| {name} | {sql_query} | C / M / S | Created view / Mapped to {name} / Skipped |

#### SQL View Columns Skipped (if user chose S)
| sql_view Name | Column | Reason |
|---|---|---|
| {name} | {column} | sql_view skipped by user |

#### Formula Translation Log
| Column | Original Expression | Status | Notes |
|---|---|---|---|
| {name} | {expr} | Translated / OMITTED | {translated SQL or omit reason} |

#### Other Dropped Properties
| Property | Applies To | Action Taken |
|---|---|---|
| geo_config | {n} columns | Columns migrated as plain dimensions |
| is_bypass_rls | Model | Dropped — RLS must be re-implemented in Databricks UC |
| custom_order | {n} columns | Dropped — apply in Genie or dashboard layer |
```

---

## Future Improvements

| Area | Potential improvement |
|---|---|
| AI context | If UC adds a dedicated per-field AI instruction property, map `ai_context` to it directly |
| Format patterns | Expand `format:` mapping as UC adds finer-grained options |
| Many-to-many | A companion step could generate a pre-aggregation VIEW DDL for bridge table patterns |
| Parameters | Parameter → UC Dynamic View or filter widget mapping when UC adds parameterization |
| Window measures | Additional `range` unit support and multi-window measures as UC matures |
