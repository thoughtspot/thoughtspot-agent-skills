# ThoughtSpot → Snowflake Property Coverage

Full reference for what ThoughtSpot TML properties map to Snowflake Semantic View,
what is partially migrated, and what cannot be migrated at all.

Each limitation has a **status tag** and a **future path** note to guide improvement
of this skill over time.

---

## Properties That Map

| ThoughtSpot | Snowflake Semantic View | Notes |
|---|---|---|
| Model / Worksheet `name` | `name` | snake_cased |
| Model / Worksheet `description` | `description` | Passed through unchanged |
| `model_tables[]` / `tables[]` | `tables[]` + `base_table` | Physical names from Table TML |
| `sql_view` (simple `SELECT *`) | `tables[]` + `base_table` | Resolved to physical table — see thoughtspot-tml.md |
| `joins[]` (inline `on`) | `relationships[]` | Direct parse |
| `joins[]` (`referencing_join`) | `relationships[]` | Resolved from Table TML `joins_with` |
| `ATTRIBUTE` column (non-date) | `dimensions[]` | |
| `ATTRIBUTE` column (date/timestamp) | `time_dimensions[]` | Type from `db_column_properties.data_type` |
| `MEASURE` column | `metrics[]` | Aggregation mapped via mapping-rules.md |
| Formula column (`formula_id`) | `metrics[]` | Expression translated; see formula-translation.md |
| `synonyms[]` | `synonyms[]` | Passed through |
| `column.description` | `description` | Passed through |
| `ai_context` | `description` | **Partial** — see below |
| `db_column_properties.data_type` | `data_type` | Preferred over `db_column_type` |

---

## Partial Migrations

### AI Context (`ai_context`)

**Status: Partial — semantic specificity lost**

ThoughtSpot `ai_context` is a per-column AI directive for Spotter
(e.g. "Exclude null values from this column when calculating averages.").
It is an AI instruction, not a human-facing description.

Snowflake `description` is human-facing and also read by Cortex Analyst, but it is
not a directive. The `ai_context` text is merged into `description` with the prefix
`[TS AI Context]`.

**Action for users:** Review all AI context entries in the Unmapped Report and decide
whether to rewrite them in Snowflake's documentation style.

**Future path:** If Snowflake introduces a dedicated per-field AI instruction property,
map `ai_context` directly to it.

---

### Multi-Column Joins (AND conditions)

**Status: Partial — AND supported, OR not**

`AND`-separated join conditions are parsed into multiple `relationship_columns` entries.
`OR` conditions have no Snowflake equivalent — require a wrapping view.

---

### Chained / Multi-Hop Join Paths

**Status: Partial — unrolled into pair-wise relationships**

Worksheet `table_paths` with multi-hop chains (`fact → dim_a → bridge → dim_b`) are
unrolled into direct pair-wise relationships. Flag at the checkpoint for user review.

---

## Partial Migrations — SQL Views

### `sql_view` (complex SQL)

**Status: Partial — requires user decision**

ThoughtSpot `sql_view` objects are virtual tables backed by an arbitrary SQL query.
Simple `SELECT *` views are resolved automatically to the underlying physical table.
Complex views (WHERE clauses, column aliases, JOINs, aggregations, subqueries) cannot
be auto-mapped and require one of three user-directed options at the checkpoint:

- **C (Create):** A Snowflake VIEW is created in the target schema using the
  ThoughtSpot `sql_query` verbatim. Requires the Snowflake role to have `CREATE VIEW`
  on the target schema.
- **M (Map):** User provides an existing Snowflake table or view name to use as
  `base_table`. Requires the named object to already exist and be accessible.
- **S (Skip):** All model columns sourced from the sql_view are omitted and logged
  in the Unmapped Report.

**Future path:** Add SQL dialect translation for ThoughtSpot-specific syntax to
improve portability of complex `sql_query` strings to Snowflake.

---

## Hard Blockers — No Migration Possible

### Parameters (`parameters[]`)

**Status: Hard blocker**

ThoughtSpot parameters are runtime variables (date ranges, metric selectors, locale).
No equivalent in Snowflake Semantic View.

Impact: formulas referencing parameters emit `-- TODO` comments. All parameters are
listed in the Unmapped Properties Report.

**Future path:** Re-implement parameter logic as multiple concrete columns, or as
Snowflake dynamic tables. Monitor Snowflake for parameterised expression support.

---

### `sql_string_op` Formulas

**Status: Hard blocker — requires manual translation**

ThoughtSpot-specific function for embedding SQL templates. Must be rewritten manually.
See [formula-translation.md](formula-translation.md) for guidance.

---

### Time Intelligence Functions

**Status: Hard blocker — requires manual translation**

`growth_rate`, `period_ago`, `moving_average`, `cumulative_sum`, `rank`, etc.
Rewrite as Snowflake window functions. See [formula-translation.md](formula-translation.md).

**Future path:** A companion formula translation skill could assist interactively.

---

### Column Groups / Data Panel Groups

**Status: Hard blocker**

ThoughtSpot `column_groups` and `data_panel_column_groups` organise columns into UI
panels. Snowflake Semantic View has no grouping concept.

**Action:** Group membership is documented in the Unmapped Report. Re-create in BI tool.

---

### Format Patterns (`format_pattern`)

**Status: Hard blocker**

Display format strings (`dd/MMM/yyyy`, `#,##0.00000`) have no Snowflake equivalent.
Apply in the BI tool or via `TO_CHAR()` in a Snowflake view wrapper.

---

### Default Date Buckets (`default_date_bucket`)

**Status: Hard blocker**

Default time grain (DAILY, WEEKLY, MONTHLY, QUARTERLY, YEARLY). Snowflake
`time_dimensions` have no default grain property. Document in Unmapped Report.

---

### Model-Level Filters (`filters[]`)

**Status: Hard blocker**

Default query filters applied to all queries. Options for users:
- Snowflake row access policy on the underlying table
- Wrap the physical table in a view with the filter built in
- Document and enforce in the BI tool

---

### Custom Sort Order (`custom_order`)

**Status: Hard blocker**

Explicit value sort order for dimension values. Apply in BI tool or Snowflake `ORDER BY`.

---

### Row-Level Security (`is_bypass_rls`)

**Status: Hard blocker**

ThoughtSpot RLS rules are not exported in TML. Must be re-implemented using Snowflake
row access policies or column masking policies.

---

### Locale-Specific Column Aliases (`column_alias_udf.tml`)

**Status: Hard blocker**

Per-locale column alias overrides for multilingual display. Snowflake Semantic View has
no locale support. English names and synonyms are migrated. Document in Unmapped Report.

---

### Geo Configuration (`geo_config`)

**Status: Hard blocker**

Latitude, longitude, region, and zip geospatial configuration. No Snowflake equivalent.
Affected columns are migrated as regular `dimensions` with a note in the Unmapped Report.

---

## Silently Dropped (No Action Needed)

| ThoughtSpot Property | Reason |
|---|---|
| `spotter_config.is_spotter_enabled` | ThoughtSpot-specific, no Snowflake equivalent |
| `join_progressive` | ThoughtSpot execution hint, no Snowflake equivalent |
| `index_type` (DONT_INDEX / INDEX) | ThoughtSpot search hint, no Snowflake equivalent |
| `synonym_type` (USER_DEFINED / SYSTEM) | Metadata about synonyms, not the synonyms themselves |
| `obj_id` | ThoughtSpot internal content ID |
| `was_auto_generated` (formulas) | ThoughtSpot metadata flag |

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

#### AI Context (merged into description with [TS AI Context] prefix)
| Column | Original ai_context |
|---|---|
| {name} | {ai_context text} |

#### Format Patterns (not migrated)
| Column | format_pattern | Suggested handling |
|---|---|---|
| {name} | {pattern} | Apply in BI layer or TO_CHAR() in view |

#### Default Date Buckets (not migrated)
| Column | default_date_bucket |
|---|---|
| {name} | {bucket} |

#### Model-Level Filters (not migrated)
| Column | Operator | Value |
|---|---|---|
| {col} | {op} | {val} |

#### SQL Views Resolved Automatically
| sql_view Name | sql_query | Resolved To |
|---|---|---|
| {name} | {sql_query} | {db}.{schema}.{db_table} |

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
| {name} | {expr} | Translated / ⚠ TODO | {translated SQL or TODO reason} |

#### Other Dropped Properties
| Property | Applies To | Action Taken |
|---|---|---|
| spotter_config | Model/Tables | Dropped silently |
| is_bypass_rls | Model | Dropped — RLS must be re-implemented in Snowflake |
| column_alias_udf.tml | Separate file | Not migrated — multilingual aliases require manual handling |
| geo_config | {n} columns | Columns migrated as plain dimensions |
```
