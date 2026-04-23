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
| `joins[]` (inline `on`) | `relationships[]` | Sub-fields: `left_table`, `right_table`, `relationship_columns[].left_column/.right_column` |
| `joins[]` (`referencing_join`) | `relationships[]` | Resolved from Table TML `joins_with`; same sub-field names |
| `ATTRIBUTE` column (non-date) | `dimensions[]` | Expression in `dimensions[].expr` |
| `ATTRIBUTE` column (date/timestamp) | `time_dimensions[]` | Type from `db_column_properties.data_type`; expression in `time_dimensions[].expr` |
| `MEASURE` column | `metrics[]` | Aggregation in `metrics[].expr`; see `facts[]` note in Field Reference section below |
| Formula column (`formula_id`) | `metrics[]` | Expression in `metrics[].expr`; see ts-snowflake-formula-translation.md |
| `synonyms[]` | `synonyms[]` | Column/metric-level; table-level synonyms also supported by SV but not populated — see Field Reference section |
| `column.description` | `description` | Passed through |
| `ai_context` | `description` | **Partial** — see below |
| `db_column_properties.data_type` | `data_type` | Preferred over `db_column_type` |

---

## Snowflake SV YAML Field Reference

Field names confirmed against the OSI → Snowflake converter (`tgao-snowflake-converter`, commit `1e36581`).

### Expression field: `expr`

SQL expressions use `expr` at every level — not `expression`, `formula`, or `sql`:

```yaml
tables:
  - name: orders
    dimensions:
      - name: status
        expr: "status"                      # dimensions[].expr
    time_dimensions:
      - name: created_at
        expr: "created_at"                  # time_dimensions[].expr
    facts:
      - name: amount
        expr: "amount"                      # facts[].expr (see facts[] note below)
metrics:
  - name: total_revenue
    expr: "SUM(orders.amount)"              # metrics[].expr
```

Cross-table references in `metrics[].expr` use `table_name.column_name` dot notation:
`SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)`

---

### `base_table` sub-structure

`base_table` is a nested dict, not a flat string:

```yaml
tables:
  - name: orders
    base_table:
      database: MY_DB    # uppercased if the identifier was unquoted in the source
      schema: PUBLIC
      table: ORDERS
```

For subquery sources (`sql_view` complex SQL):
```yaml
    base_table:
      definition: "SELECT * FROM ..."
```

---

### `relationships[]` sub-structure

Snowflake SV uses `left_table`/`right_table`, not `from`/`to` (OSI naming):

```yaml
relationships:
  - name: orders_to_customers
    left_table: orders
    right_table: customers
    relationship_columns:
      - left_column: customer_id
        right_column: id
```

`AND`-conditions on a single join produce multiple `relationship_columns` entries.

---

### `facts[]` — raw numeric columns vs. `metrics[]`

Snowflake SV supports a `facts[]` array on each table for raw numeric columns that carry
no pre-defined aggregation. This is distinct from the top-level `metrics[]` array.

```yaml
tables:
  - name: orders
    facts:
      - name: amount
        expr: "amount"     # raw column — Cortex Analyst can aggregate ad-hoc
metrics:
  - name: total_revenue
    expr: "SUM(orders.amount)"   # pre-defined aggregation
```

**Our converter's choice:** All TS `MEASURE` columns are mapped to top-level `metrics[]`
with an explicit aggregation wrapper (e.g. `SUM(table.col)`). This is valid Snowflake SV
and works with Cortex Analyst, but it pre-determines the aggregation. Using `facts[]`
instead would let Cortex Analyst compose aggregations freely at query time.

This is a deliberate trade-off, not an error. See Future Improvements below.

---

### `synonyms[]` — table-level and column-level

`synonyms[]` is valid at both table scope and column/metric scope:

```yaml
tables:
  - name: orders
    synonyms:
      - "sales transactions"    # table-level — not populated from TS (TS has no table synonym concept)
    dimensions:
      - name: status
        synonyms:
          - "order status"      # column-level — populated from TS column synonyms[]
```

Table-level synonyms are left absent in TS→SV conversions. See Future Improvements.

---

### `primary_key` and `unique_keys`

Snowflake SV supports key declarations; ThoughtSpot TML has no equivalent:

```yaml
tables:
  - name: customers
    primary_key:
      columns:
        - customer_id
    unique_keys:
      - columns:
          - email
```

These fields are never populated in a TS→SV conversion and are silently absent from
the output. They are not logged in the Unmapped Report — TS has no source data for them.

---

## Partial Migrations

### AI Context (`ai_context`)

**Status: Partial — semantic specificity lost**

ThoughtSpot `ai_context` is a per-column AI directive for Spotter
(e.g. "Exclude null values from this column when calculating averages.").
It is an AI instruction, not a human-facing description.

Snowflake `description` is human-facing and also read by Cortex Analyst, but it is
not a directive. The `ai_context` text is merged into `description` with the prefix
`[TS AI Context]` followed by a newline.

Note: the OSI Snowflake converter appends `ai_context` with a bare `\n` separator and
no prefix label. Our `[TS AI Context]` prefix is more legible in the Snowflake UI and
makes the merged section easy to identify and remove later if Snowflake adds a dedicated
AI instruction field.

**Action for users:** Review all AI context entries in the Unmapped Report and decide
whether to rewrite them in Snowflake's documentation style.

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

---

## Hard Blockers — No Migration Possible

### Parameters (`parameters[]`)

**Status: Hard blocker**

ThoughtSpot parameters are runtime variables (date ranges, metric selectors, locale).
No equivalent in Snowflake Semantic View.

Impact: formulas referencing parameters are **omitted** from the YAML. All parameters are
listed in the Unmapped Properties Report.

---

### `sql_string_op` Formulas

**Status: Hard blocker — requires manual translation**

ThoughtSpot-specific function for embedding SQL templates. Must be rewritten manually.
See [ts-snowflake-formula-translation.md](ts-snowflake-formula-translation.md) for guidance.

---

### Window, LOD, and Semi-Additive Functions

**Status: Partially translatable — review each formula against ts-snowflake-formula-translation.md**

`moving_average`, `cumulative_sum`, `rank`, `group_aggregate`, `first_value`, `last_value`, etc.
Many of these translate directly to SQL window functions (`OVER (PARTITION BY)`) supported in
Snowflake Semantic View `metrics` `expr`. See [ts-snowflake-formula-translation.md](ts-snowflake-formula-translation.md)
for the complete pattern library.

Untranslatable patterns (omit and log in Unmapped Report):
- `first_value` and `agg(first_value(...))` — no direct Snowflake equivalent
- `last_value_in_period` — period-scoped variants have no SV equivalent
- Window functions with complex multi-dimension grouping not expressible as `PARTITION BY`

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

---

## Future Improvements

| Area | Potential improvement |
|---|---|
| AI context | If Snowflake introduces a dedicated per-field AI instruction property, map `ai_context` directly to it instead of merging into `description`. |
| `facts[]` vs `metrics[]` | Emit raw TS MEASURE columns (no formula) as `facts[]` rather than `metrics[]` to preserve Cortex Analyst's ad-hoc aggregation flexibility. Pre-defined formula MEASUREs would still go to `metrics[]`. |
| Table-level synonyms | Populate `tables[].synonyms[]` from the model's table description or TML table name variants; currently left absent. |
| `primary_key` / `unique_keys` | If ThoughtSpot ever exposes PK declarations in TML (or if they can be inferred from connection metadata), populate these for better Cortex Analyst query planning. |
| Complex SQL views | Add SQL dialect translation for ThoughtSpot-specific syntax to improve portability of complex `sql_query` strings to Snowflake. |
| Parameters | Re-implement parameter logic as multiple concrete columns, or as Snowflake dynamic tables. Monitor Snowflake for parameterised expression support. |
| Window / LOD / semi-additive functions | A companion skill could assist interactively with window function rewrites, CTE generation, and semi-additive view creation. |
