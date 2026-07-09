<!-- currency: databricks — 2026-07 (PR1 window deep-analysis 2026-07-09: property-coverage window rows corrected to live-verified forms (C1/C3/C6/C6a) and materialization: added as a documented (metadata-only) property (C9); fields:/dimensions: synonym and offset 18.1 gate re-checked, still hold; see BL-032; PR1.5 semantic deep-dive 2026-07-09: LOD dimension × filter (A1) CONFIRMED filter-aware on TS under both filter kinds, cross-platform DIVERGENCE for a DBX consumer's ad hoc query-time WHERE (A2, DBX-internal asymmetry); cross-measure ratio × grain (B1) CONFIRMED ratio-of-sums cross-platform at every grain; global filter: × window ordering (C1) CONFIRMED filter-before-window cross-platform, frame semantics DIVERGENCE (date-interval vs row-positional); semi-additive × date-range filter (D1) CONFIRMED last/first-in-filtered-range cross-platform; trailing-window frame (E1) DIVERGENCE — DBX date-interval vs TS row-positional on gapped data, density caveat added; A3 follow-up (user-suggested) 2026-07-09: group_aggregate's `{}` filter argument CORRECTS the A1/A2 "no TS analogue" conclusion — `{}` is search-filter-blind but model-filter-aware, reproducing DBX's MV-filter-aware + query-WHERE-blind composite when paired with a mirrored model-level filters: block; subtraction form query_filters() - {col} import-accepted but does not exclude a derived-formula filter — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md; see BL-032) -->

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
| Semi-additive (`last_value(sum(...))`/`first_value(sum(...))` — snapshot metrics) | `measures[].window` | `range: current`, `order:` raw date, `semiadditive: last` or `first` — **Live-verified 2026-07-09**, `docs/audit/2026-07-08-dbx-window-claim-matrix.md` C7 |
| Period filter, no offset (`sum(m)` at the query grain — flow metrics) | `measures[].window` | `range: current`, `order:` truncated period, no `offset` — **Live-verified 2026-07-09**, matrix C6 |
| Period filter with offset (`moving_sum(m, N, -N, d)` LAG idiom — flow metrics) | `measures[].window` | `range: current`, `order:` truncated period, `semiadditive: last` + `offset: -N <unit>` — **row-relative, not wall-clock**; caveat: exactly one row per period at the query grain — **Live-verified 2026-07-09**, matrix C6/C6a (corrects the pre-2026-07-09 `sum_if(diff_months/quarters/years(...))` mapping) |
| Column `name` (display name) | `display_name:` | Human-readable label |
| Column `description` | `comment:` | Per-column description |
| `properties.synonyms[]` | `synonyms:` | YAML list: `['alias1', 'alias2']`. Read from `properties.synonyms` in TML, NOT column root |
| `safe_divide(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` | No `DIV0` in Databricks |
| Rolling window, default/exclusive (`moving_sum(m, N, -1, d)`) | `measures[].window` | `range: trailing N day` (default) / `trailing N day exclusive`, `order:` date dim, `semiadditive: last` — **Live-verified 2026-07-09**, matrix C1/C2 |
| Rolling window, inclusive (`moving_sum(m, N-1, 0, d)`) | `measures[].window` | `range: trailing N day inclusive`, `order:` date dim, `semiadditive: last` — **Live-verified 2026-07-09**, matrix C1 |
| Rolling look-ahead, default/exclusive (`moving_sum(m, -1, N, d)`) | `measures[].window` | `range: leading N day` (default) / `leading N day exclusive`, `order:` date dim, `semiadditive: last` — **Live-verified 2026-07-09**, matrix C3 |
| Rolling look-ahead, inclusive (`moving_sum(m, 0, N-1, d)`) | `measures[].window` | `range: leading N day inclusive`, `order:` date dim, `semiadditive: last` — **Live-verified 2026-07-09**, matrix C3 |
| Partition-wide LOD (`group_aggregate(sum(m), {dim}, query_filters())`) | `measures[].window` | `range: all`, scoped per query partition — **Live-verified 2026-07-09**, matrix C4. Inherits the LOD row's A1/A2 filter asymmetry below (and its A3 refinement) |
| Conditional aggregate (`*_if(cond, x)` — `sum_if`, `unique_count_if`, etc.) | `AGG(x) FILTER (WHERE cond)` | Native `*_if` functions; fallback: `agg(if (cond) then x else null)` |
| Boolean filter formula (ATTRIBUTE) | `filter:` field | Translatable boolean expressions → MV global filter; formula removed from dimensions |
| Cross-formula reference `[measure]` | `MEASURE(measure_name)` | Cross-measure reference |
| Cross-formula reference `[lod_dim]` | `ANY_VALUE(dimension_name)` | Dimension ref from measure |

**Density caveat (E1, live-verified 2026-07-09 on gapped data —
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** The four rolling
window/look-ahead rows above are row-positional: matches Databricks' date-interval
trailing/leading windows only when the order column is dense at the window's unit
grain (one row per unit, no gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md
(E1). **Filter asymmetry caveat (A1/A2, same date):** the LOD row above (and the
partition-wide LOD row) is filter-aware on ThoughtSpot under both filter kinds and
matches a Databricks MV's own global `filter:` — it does NOT reproduce a DBX
consumer's ad hoc query-time `WHERE` on an MV with no global filter, **unless the
filter argument is `{}` instead of `query_filters()`, paired with a model-level
`filters:` block mirroring the MV's `filter:`** — that combination reproduces the
DBX consumer's query-time-`WHERE`-blind reading too (A3 follow-up, live-verified
2026-07-09, same matrix).

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
| `measures[].window`, `order:` is raw date | Semi-additive formula | `last_value(sum([m]), query_groups(), {[date]})` / `first_value(...)` (snapshot metrics) — **Live-verified 2026-07-09**, matrix C7 |
| `measures[].window`, `order:` is truncated period, no `offset` | Period-filter formula | `sum([m])` at the query grain (flow metrics) — **Live-verified 2026-07-09**, matrix C6 |
| `measures[].window`, `order:` is truncated period, `offset: -N <unit>` | Period-filter formula | `moving_sum([m], N, -N, [date])` — row-relative LAG idiom, NOT wall-clock; one-row-per-period caveat — **Live-verified 2026-07-09**, matrix C6/C6a |
| `measures[].window`, `range: trailing N day` (default/exclusive) | Rolling window formula | `moving_sum([m], N, -1, [TABLE::date_col])` — sort arg must be physical column, not formula — **Live-verified 2026-07-09**, matrix C1/C2 |
| `measures[].window`, `range: trailing N day inclusive` | Rolling window formula | `moving_sum([m], N-1, 0, [TABLE::date_col])` — **Live-verified 2026-07-09**, matrix C1 |
| `measures[].window`, `range: leading N day` (default/exclusive) | Rolling look-ahead formula | `moving_sum([m], -1, N, [TABLE::date_col])` — **Live-verified 2026-07-09**, matrix C3 |
| `measures[].window`, `range: leading N day inclusive` | Rolling look-ahead formula | `moving_sum([m], 0, N-1, [TABLE::date_col])` — **Live-verified 2026-07-09**, matrix C3 |
| `measures[].window`, `range: all` | Partition-wide LOD formula | `group_aggregate(sum([m]), {[partition_dim]}, query_filters())`, `column_type: ATTRIBUTE` — **Live-verified 2026-07-09**, matrix C4. Inherits the LOD row's A1/A2 filter asymmetry above (and its A3 refinement) |
| `AGG(x) FILTER (WHERE cond)` | Conditional aggregate formula | `agg_if(cond, [x])` — native `*_if` function |
| `COUNT(*)` | MEASURE column | `aggregation: COUNT` on any non-null column, or formula `count(1)` |
| `filter:` | Boolean formula column `[MV Filter]` | Always create formula — never description-only. Users apply `[MV Filter] = true` |
| `source:` | Table TML `db_table` + `db` + `schema` | Decomposed into catalog/schema/table |
| `version:` | — | Used for parsing path selection, not stored |

**Density caveat (E1)** — same as the TS → Databricks MV table above: the four
`range: trailing`/`leading` rows are row-positional: matches Databricks'
date-interval trailing/leading windows only when the order column is dense at the
window's unit grain (one row per unit, no gaps) — see
docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

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
| `window[].range: current` (no offset) | **Mapped** | `range: current` → `sum(m)` at the query grain (month/quarter/year) — **corrected 2026-07-09** (was `sum_if(diff_months(...)=0, [m])`; row-relative, not wall-clock) — Live-verified, matrix C6 |
| `window[].range: current` + `offset: -1 month` | **Mapped** | → `moving_sum(m, 1, -1, d)` — **corrected 2026-07-09** (was `sum_if(diff_months(...)=-1, [m])`) — Live-verified, matrix C6; one-row-per-period caveat applies (see the TS→MV table above) |
| `window[].range: current` + `offset: -1 year` (month grain) | **Mapped** | → `moving_sum(m, 12, -12, d)` — **corrected 2026-07-09** (was `sum_if(diff_months(...)=-12, [m])`) — Deferred (C8), not separately live-tested; one-row-per-period caveat applies |
| `window[].range: current` + `offset: -1 year` (quarter grain) | **Mapped** | → `moving_sum(m, 4, -4, d)` — **corrected 2026-07-09** (was `sum_if(diff_quarters(...)=-4, [m])`) — Deferred (C8), not separately live-tested; one-row-per-period caveat applies |
| `window[].range: trailing N day` (default/exclusive) | **Mapped** | → `moving_sum([m], N, -1, [date])` — **corrected 2026-07-09** (was `moving_sum([m], N, 0, [date])`, which reproduces `trailing (N+1) day inclusive`, not `trailing N day`) — Live-verified, matrix C1/C2 |
| `window[].range: trailing N day inclusive` | **Mapped** | → `moving_sum([m], N-1, 0, [date])` — Live-verified 2026-07-09, matrix C1 |
| `window[].range: leading N day` (default/exclusive) | **Mapped** | → `moving_sum([m], -1, N, [date])` — Live-verified 2026-07-09, matrix C3 |
| `window[].range: leading N day inclusive` | **Mapped** | → `moving_sum([m], 0, N-1, [date])` — Live-verified 2026-07-09, matrix C3 |
| `window[].range: all` | **Mapped** | → `group_aggregate(sum(m), {partition dims}, query_filters())`, scoped per query partition — Live-verified 2026-07-09, matrix C4. Filter-aware for the MV's own global `filter:` only — not for an ad hoc query-time `WHERE` on an MV with no global filter (A1/A2, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`), **unless emitted as `{}` + a mirrored model-level `filters:` block, which reproduces both halves (A3, same matrix)** |
| `window[].range: cumulative` | **Mapped** | `range: cumulative` → `cumulative_sum(m, d)` — Live-verified 2026-07-09, matrix C5 |
| `AGG(x) FILTER (WHERE cond)` | **Mapped** | → `agg_if(cond, [x])` native conditional aggregate |
| `COUNT(*)` | **Mapped** | → formula `count(1)` |
| Subquery in `expr` | **Untranslatable** | ThoughtSpot formulas cannot contain SQL subqueries |
| `source:` as SELECT subquery | **Mapped (with user choice)** | Prompt: (D) create Databricks VIEW, (T) create ThoughtSpot SQL View, (M) map to existing |
| `materialization:` (top-level block: `schedule`, `mode`, `materialized_views[]`) | **Metadata only** | Databricks-side query-acceleration hint (Public Preview) — no ThoughtSpot analog; not stored on import. See [databricks-metric-view.md](../../schemas/databricks-metric-view.md#materialization-block-public-preview). Docs-research finding (Task 1, `docs/audit/2026-07-08-dbx-window-docs-findings.md`), 2026-07-08 |

**Density caveat (E1)** — the four `window[].range: trailing`/`leading` rows above
are row-positional: matches Databricks' date-interval trailing/leading windows only
when the order column is dense at the window's unit grain (one row per unit, no
gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

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
| Period comparisons | Not a concept | `window[].range: current` + `offset` → `moving_sum(m, N, -N, d)` (row-relative LAG idiom; one-row-per-period caveat applies) / `range: cumulative` → `cumulative_sum` |
