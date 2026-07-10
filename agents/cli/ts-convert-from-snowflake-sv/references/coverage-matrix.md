# Coverage Matrix: Snowflake Semantic View → ThoughtSpot Model

What the `ts-convert-from-snowflake-sv` skill maps and what it does not.
Use this as the canonical limitations reference.

---

## Mapped Constructs

### Structure and Schema

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | `tables (DB.SCHEMA.TABLE)` block | `model_tables[]` entries | |
| 2 | `tables (DB.SCHEMA.VIEW)` — view-backed sources | `model_tables[]` entries | TS tables can point to views |
| 3 | Table aliases (explicit + implicit) | `model_tables[].name` | |
| 4 | `primary key (col)` on table entries | Join target identification | Not written to TML |
| 5 | Table-level `comment='...'` | `table.description` | Separate Table TML update |
| 6 | Top-level `comment='...'` (after metrics) | `model.description` | |

### Joins and Relationships

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 7 | `relationships (REL as FROM(FK) references TO(PK))` — equi joins | `joins[]` inline on the FROM table entry | |
| 8 | `references TABLE(between START and END exclusive)` — range joins | `joins[].on` with `>=` / `<` expression | |
| 9 | `references TABLE(COL1, ASOF COL2)` — ASOF joins | `joins[].on` with `=` on COL1, `>=` on ASOF col | |
| 10 | Composite equi-joins (`FROM(C1,C2) references TO(C1,C2)`) | `joins[].on` with multiple `=` pairs | |
| 11 | Joinless SVs (no `relationships` block) | 4-option join discovery workflow: PK/FK, column overlap, manual, separate models | |

### Dimensions

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 12 | `dimensions (TABLE.COL as NAME)` | `columns[]` with `column_type: ATTRIBUTE` | |
| 13 | Computed dimensions (`DATEDIFF`, `CONCAT`, `CASE/WHEN`) | `formulas[]` with `column_type: ATTRIBUTE` | |
| 14 | `with synonyms=('...',...)` on dimensions/metrics | `column.name` + `properties.synonyms` | First synonym → name; rest → synonyms |
| 15 | `comment='...'` on dimensions/metrics | column `description` | |

### Facts and Metrics

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 16 | `facts (TABLE.NAME as EXPR)` — row-level expressions | `formulas[]` entries (MEASURE or ATTRIBUTE) | |
| 17 | `labels = (filter)` on facts/dimensions — filter labels | Boolean formula column (`column_type: ATTRIBUTE`) | |
| 18 | Simple metrics: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` | `columns[]` with `column_type: MEASURE` + `aggregation` | |
| 19 | `COUNT(DISTINCT col)` | `unique count([T::col])` formula | Never COUNT_DISTINCT aggregation (I5) |
| 20 | Complex metric expressions (multi-column, arithmetic) | `formulas[]` with translated ThoughtSpot formula | |
| 21 | `non additive by (col asc nulls last) as AGG(...)` — semi-additive | `last_value(agg(...), query_groups(), {date})` formula | |
| 22 | `non additive by (col desc nulls last) as AGG(...)` | `first_value(agg(...), query_groups(), {date})` formula | |
| 23 | Window functions: `OVER (PARTITION BY ... ORDER BY ...)` | `group_sum([T::col], [T::dim])` for PARTITION BY; `group_aggregate(agg(...), query_groups()-{dim}, query_filters())` for EXCLUDING | Group functions take columns only, cannot nest in each other. Window functions (`cumulative_*`, `moving_*`) accept `group_aggregate(...)` as input but not raw aggregates. |
| 24 | `PARTITION BY EXCLUDING` | `group_aggregate(... query_groups()-{dim})` | |
| 25 | Cumulative: `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` | `moving_sum(group_aggregate(agg(...), {[T::PK]}, query_filters()), -1, 0, [T::order_col])` | Cannot nest aggregates directly in `moving_sum`; must wrap in `group_aggregate` first |
| 26 | Metric-on-fact resolution (`AVG(table.fact_name)`) | `average([formula_<id>])` | References fact by formula `id` |
| 27 | Double aggregation / metric-on-metric (`AVG(table.count_metric)`) | `average(group_count([T::col], [DIM::pk]))` | `group_*` shorthands |
| 28 | Window metrics referencing other metrics | Combined window + double-agg translation | |
| 29 | Duplicate `column_id` detection (I8) | Formula with unique `column_id` | Second metric on same column gets formula |

### Verified Queries and Metadata

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 30 | `ai_verified_queries (QUERY_NAME AS (...))` | NLS Feedback TML (`REFERENCE_QUESTION` entries) | |
| 31 | `with extension (CA='...')` | Parsed only | Type confirmation; not mapped to TML |
| 32 | `constraint ... distinct range between START and END` on table entries | Parsed only | Identifies range join endpoints |

### Operational Modes

| # | Capability | Notes |
|---|---|---|
| 33 | Spotter enablement | `model.properties.spotter_config.is_spotter_enabled` (user confirms) |
| 34 | Mode A (single SV → new model) | Full workflow Steps 1–12.5 |
| 35 | Mode B (merge multiple SVs → one model) | Multi-SV DDL fetch + dedup + merge |
| 36 | Mode C (update existing model from changed SV) | Structural + metadata diff with per-column MERGE/UPDATE/KEEP |

---

## Unmapped Constructs (Limitations)

| # | Semantic View Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | `CUSTOM_INSTRUCTIONS` (`AI_QUESTION_CATEGORIZATION`, `AI_SQL_GENERATION`) | No `data_model_instructions` mapping | Run `/ts-object-model-coach` after conversion to add Spotter instructions |
| L2 | Table-level `with synonyms=('...')` on `tables()` entries | No ThoughtSpot table-level synonym concept | Add table synonyms to `model.description` or `data_model_instructions` for Spotter context |
| L3 | `ACCESS_MODIFIER: PRIVATE` on facts/metrics | No "private column" concept in ThoughtSpot models | Omit private facts/metrics; or include with `index_type: DONT_INDEX` so Spotter ignores them |
| L4 | `unique_keys` declarations on table entries | No key declarations in ThoughtSpot models | Not needed — ThoughtSpot does not use key metadata |
| L5 | Subquery-backed sources (`FROM (<subquery>)` in tables block) | N/A — Snowflake `tables()` does not support subquery sources | If a future SV version adds subquery support, implement using the pattern from `ts-convert-from-databricks-mv` (Step 2c) |
| L6 | BOOL columns in `if` expressions require parentheses | `if [TABLE::BOOL_COL] then...` fails. Must use `if ( [TABLE::BOOL_COL] ) then...` with parentheses around the condition. `count_if` and `sum_if` also work without this issue. | Use `if ( [T::BOOL] ) then 1 else 0` (parens required) or prefer `count_if([T::BOOL], [T::PK])` / `sum_if([T::BOOL], [T::MEASURE])` which don't need the workaround. |
| L7 | Formula import on initial model CREATE | Formulas referencing `[TABLE::COL]` fail during initial `ts tml import` (CREATE) but succeed on UPDATE (`--no-create-new`) | Always import model structure first (no formulas), then update with formulas in a second pass |

### Notes on limitations

**L1–L4** are low severity — ThoughtSpot has no direct equivalent or the equivalent is
easily achieved via post-conversion coaching (`/ts-object-model-coach`). These are
cosmetic/metadata features that do not affect the structural correctness of the converted model.

**L5** is N/A — Snowflake's `tables()` block does not support subquery sources. Only named
database objects (tables and views) are valid. If a future SV version adds subquery support,
this limitation would need to be reopened.

**L6** is LOW severity — purely a syntax quirk. BOOL columns work in all formula contexts;
the `if` construct just requires parentheses around BOOL conditions: `if ( [T::BOOL] ) then`.
The `count_if` and `sum_if` functions work without any workaround. Verified on ThoughtSpot
Cloud (SE cluster).

**L7** is a runtime behaviour — not a fundamental limitation. The skill's Step 11 workflow
already uses two-pass import (create model without formulas → update with formulas).
This note documents WHY that pattern is required.
