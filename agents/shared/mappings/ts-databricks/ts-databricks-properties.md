<!-- currency: databricks — 2026-07 (external sweep: confirmed accurate — fields:/dimensions: synonym, window Experimental status, materialization Public Preview, offset 18.1 gate, no SHOW METRIC VIEWS all still hold; no content changes needed) -->

# ThoughtSpot ↔ Databricks Metric View Property Coverage

Full reference for what ThoughtSpot TML properties map to Databricks Metric View
fields, what is partially migrated, and what cannot be migrated at all.

**Use v1.1 for all conversions** — v1.1 supports `display_name`, `comment`, and
`synonyms` per column, plus `comment` at the view level. v0.1 only supports
`name`, `expr`, and `window`.

---

## Properties That Map

### TS → Databricks MV (v1.1)

| ThoughtSpot property | Databricks MV field | Notes |
|---|---|---|
| Model / Worksheet `name` | View name in `CREATE VIEW` | Used as-is (spaces allowed in MV names) |
| Model `description` | Top-level `comment:` | View-level description |
| `model_tables[]` source table | `source:` (fact table) + `joins[].source` (dimension tables) | Fully qualified table names |
| `ATTRIBUTE` column | `dimensions[].name` + `dimensions[].expr` | `expr` is the physical column name or SQL expression |
| `MEASURE` column with `aggregation` | `measures[].name` + `measures[].expr` | Aggregate function embedded in `expr`: `SUM(col)` |
| Formula column (translatable MEASURE) | `measures[].expr` | Translated SQL expression with aggregate |
| Formula column (translatable ATTRIBUTE) | `dimensions[].expr` | Translated SQL expression |
| LOD formula (`group_aggregate`) | `dimensions[].expr` with window | `AGG() OVER (PARTITION BY ...)` — becomes a dimension |
| Semi-additive (`last_value(sum(...))` — snapshot metrics) | `measures[].window` | `range: current`, `order:` raw date, `semiadditive: last` or `first` |
| Period filter (`sum_if(diff_months/quarters/years(...))` — flow metrics) | `measures[].window` | `range: current`, `order:` truncated period, `semiadditive: last` + optional `offset` |
| Column `name` (display name) | `display_name:` | Human-readable label |
| Column `description` | `comment:` | Per-column description |
| `properties.synonyms[]` | `synonyms:` | YAML list: `['alias1', 'alias2']`. Read from `properties.synonyms` in TML, NOT column root |
| `safe_divide(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` | No `DIV0` in Databricks |
| Rolling window (`moving_sum(m, N, 0, d)`) | `measures[].window` | `range: trailing N day`, `order:` date dim, `semiadditive: last` |
| Conditional aggregate (`*_if(cond, x)` — `sum_if`, `unique_count_if`, etc.) | `AGG(x) FILTER (WHERE cond)` | Native `*_if` functions; fallback: `agg(if (cond) then x else null)` |
| Boolean filter formula (ATTRIBUTE) | `filter:` field | Translatable boolean expressions → MV global filter; formula removed from dimensions |
| Cross-formula reference `[measure]` | `MEASURE(measure_name)` | Cross-measure reference |
| Cross-formula reference `[lod_dim]` | `ANY_VALUE(dimension_name)` | Dimension ref from measure |

### Databricks MV → TS (v1.1)

| Databricks MV field | ThoughtSpot property | Notes |
|---|---|---|
| Top-level `comment:` | Model `description` | |
| `dimensions[].display_name` | Column `name` (display name) | Falls back to `name:` if no `display_name` |
| `dimensions[].comment` | Column `description` | |
| `dimensions[].synonyms` | `properties.synonyms[]` + `synonym_type: USER_DEFINED` | Must be inside `properties:`, not column root |
| `dimensions[].expr` (direct column ref) | `column_id` pointing to physical column | `column_type: ATTRIBUTE` |
| `dimensions[].expr` (computed) | `formulas[]` entry | Translated to TS formula syntax |
| `dimensions[].expr` (window function) | LOD `formulas[]` entry | `AGG() OVER (PARTITION BY)` → `group_aggregate(...)` |
| `measures[].display_name` | Column `name` (display name) | |
| `measures[].comment` | Column `description` | |
| `measures[].synonyms` | `properties.synonyms[]` + `synonym_type: USER_DEFINED` | Must be inside `properties:`, not column root |
| `measures[].expr` (simple `AGG(col)`) | Column with `column_type: MEASURE` + `aggregation` | Aggregate extracted from expr |
| `measures[].expr` (complex) | `formulas[]` entry | Translated to TS formula syntax |
| `measures[].expr` with `MEASURE()` | Cross-measure formula reference | `MEASURE(name)` → `[name]` |
| `measures[].expr` with `ANY_VALUE()` | Cross-dimension formula reference | `ANY_VALUE(dim)` → `[dim]` |
| `measures[].window`, `order:` is raw date | Semi-additive formula | `last_value(sum([m]), query_groups(), {[date]})` (snapshot metrics) |
| `measures[].window`, `order:` is truncated period | Period-filter formula | `sum_if(diff_months/quarters/years([date], today()) = N, [m])` (flow metrics) |
| `measures[].window`, `range: trailing N day` | Rolling window formula | `moving_sum([m], N, 0, [TABLE::date_col])` — sort arg must be physical column, not formula |
| `AGG(x) FILTER (WHERE cond)` | Conditional aggregate formula | `agg_if(cond, [x])` — native `*_if` function |
| `COUNT(*)` | MEASURE column | `aggregation: COUNT` on any non-null column, or formula `count(1)` |
| `filter:` | Boolean formula column `[MV Filter]` | Always create formula — never description-only. Users apply `[MV Filter] = true` |
| `source:` | Table TML `db_table` + `db` + `schema` | Decomposed into catalog/schema/table |
| `version:` | — | Used for parsing path selection, not stored |

---

## Properties That Do NOT Map

### TS properties with no MV equivalent

| ThoughtSpot property | Status | Future path |
|---|---|---|
| `ai_context` | **Unmapped** | No equivalent; include in view-level `comment` if relevant |
| `properties.calendar_type` | **Unmapped** | No calendar concept in MV |
| `properties.index_type` | **Unmapped** | Databricks handles indexing internally |
| `properties.index_priority` | **Unmapped** | No equivalent |
| `properties.currency_type` | `format: { type: currency }` | v1.1 supports `format:` on measures |
| `properties.geo_config` | **Unmapped** | No geo support in MV |
| `column_type: UNKNOWN` | **Omit** | Cannot classify |
| Complex LOD with `query_groups()` modifier | **Untranslatable** | Cannot express in MV dimension window |
| `last_value(...)` / `last_value_in_period(...)` | **Mapped** | True semi-additive (snapshot metrics) → `window: [{semiadditive: last}]` with raw date `order:` dimension |

### MV fields with no TS equivalent

| Databricks MV field | Status | Notes |
|---|---|---|
| `filter:` (global) | **Mapped** | Always → boolean `[MV Filter]` formula column. Never description-only — users won't apply column filters manually |
| `version:` | **Metadata only** | Drives parsing logic, not stored in TS |
| `rely: { at_most_one_match }` | **Metadata only** | Cardinality hint; TS uses `cardinality: MANY_TO_ONE` in joins |
| `format:` (currency/percentage) | **Partial** | `currency_type` maps; percentage formatting has no TS equivalent |
| `window[].range: current` (no offset) | **Mapped** | `range: current` → `sum_if ( diff_months ( [date] , today ( ) ) = 0 , [m] )` (month grain); quarter grain uses `diff_quarters` |
| `window[].range: current` + `offset: -1 month` | **Mapped** | → `sum_if ( diff_months ( [date] , today ( ) ) = -1 , [m] )` |
| `window[].range: current` + `offset: -1 year` (month grain) | **Mapped** | → `sum_if ( diff_months ( [date] , today ( ) ) = -12 , [m] )` |
| `window[].range: current` + `offset: -1 year` (quarter grain) | **Mapped** | → `sum_if ( diff_quarters ( [date] , today ( ) ) = -4 , [m] )` |
| `window[].range: trailing N day` | **Mapped** | → `moving_sum([m], N, 0, [date])` |
| `window[].range: cumulative` | **Mapped** | `range: cumulative` → `cumulative_sum(m, d)` |
| `AGG(x) FILTER (WHERE cond)` | **Mapped** | → `agg_if(cond, [x])` native conditional aggregate |
| `COUNT(*)` | **Mapped** | → formula `count(1)` |
| Subquery in `expr` | **Untranslatable** | ThoughtSpot formulas cannot contain SQL subqueries |
| `source:` as SELECT subquery | **Mapped (with user choice)** | Prompt: (D) create Databricks VIEW, (T) create ThoughtSpot SQL View, (M) map to existing |

---

## Unmapped Report Format

When generating a conversion report, list unmapped properties in this format:

```
## Unmapped Properties Report

### ThoughtSpot → Databricks MV

| Property | Column/Field | Value | Reason |
|---|---|---|---|
| synonyms | Revenue | ["Total Revenue", "Sales"] | MV does not support synonyms |
| description | Order Date | "Date the order was placed" | MV v0.1 has no description field |
| ai_context | (model-level) | "This model tracks..." | No MV equivalent |

### Formula Translation Log

| Column | ThoughtSpot Formula | Reason |
|---|---|---|
| YoY Growth | `group_aggregate(...)` | LOD function not translatable to MV expr |
| Param Filter | `[Date Parameter]` | Runtime parameter — no MV equivalent |
```

---

## Comparison with Snowflake SV Property Coverage

| Property | Snowflake SV | Databricks MV (v1.1) |
|---|---|---|
| Column name | `name` (snake_cased) | `name` (identifier) + `display_name` (human-readable) |
| Synonyms | `synonyms[]` | `synonyms:` list |
| Description (column) | `description` | `comment:` |
| Description (model/view) | `description` (top-level) | `comment:` (top-level) |
| Aggregation | Embedded in `expr` | Embedded in `expr` |
| Data type | `data_type` on dims/time_dims | Inferred from source table |
| Time dimensions | Separate `time_dimensions[]` | No distinction — all in `dimensions[]` |
| LOD | Via SQL expressions | Dimension window: `AGG() OVER (PARTITION BY ...)` |
| Semi-additive | Via SQL expressions | `window: [{semiadditive: last/first}]` |
| Cross-measure refs | Via SQL expressions | `MEASURE(name)` + `ANY_VALUE(dim)` |
| Joins | `relationships[]` | Nested `joins:` with `rely: { at_most_one_match }` — star schema support |
| Global filter | Not a concept | `filter:` |
| CA extension | `with extension (CA='...')` | Not applicable |
| Currency formatting | Not a concept | `format: { type: currency, currency_code: ... }` |
| Period comparisons | Not a concept | `window[].range: current` + `offset` → `sum_if(diff_months/diff_quarters(...))` / `range: cumulative` → `cumulative_sum` |
