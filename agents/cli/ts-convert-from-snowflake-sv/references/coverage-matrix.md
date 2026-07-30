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
| 4 | `primary key (col)` on table entries | Join target identification | Not written to TML (Model TML has no key concept). Consequence on a round trip: the reverse leg can only restore a PK that some relationship implies, so a fact table's own — often composite — PK is lost, and any of its columns the SV references nowhere else disappear with it. Lossless preservation needs a stash — see BL-166. |
| 5 | Table-level `comment='...'` | `table.description` | Separate Table TML update (Step 6D, which needs Table TMLs fetched from a live instance). **Unreachable on the documented file-only path**, which emits `{model_name}.model.tml` only — table comments are silently dropped there. See BL-176. |
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
| 14 | `with synonyms=('...',...)` on dimensions/metrics | `column.name` + `properties.synonyms` | First synonym → name; rest → synonyms. **Correct only for a Semantic View our own to-direction authored** — `build-sv` emits the ThoughtSpot column name as the first synonym, so the pair round-trips. For a Semantic View authored anywhere else, `with synonyms=(...)` means what Snowflake says it means (alternate names for NL matching), and promoting the first one **destroys the logical identifier** any verified query or downstream SQL cites. See BL-179. |
| 15 | `comment='...'` on dimensions/metrics | column `description` | |
| 38 | `time_dimensions:` members (YAML form — the DDL has no `time_dimensions` clause; the role survives only inside `with extension (CA='…')`) | `columns[]` with `column_type: ATTRIBUTE` | ThoughtSpot infers the date role from the column's data type, so the temporal role survives **only for date-typed columns**. A `NUMBER` year or a `VARCHAR` month/quarter name is demoted to a plain dimension on the reverse leg. Model TML has no independent temporal-role flag, so lossless preservation needs a stash — see BL-166. |

### Facts and Metrics

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 16 | `facts (TABLE.NAME as EXPR)` — row-level expressions | `formulas[]` entries (**ATTRIBUTE only**) | `sv_translate.py:454-468` hardcodes `ATTRIBUTE` on both branches — there is no `MEASURE` branch, despite the function's own docstring describing the choice. Consequence: every fact returns from the reverse leg inside `dimensions()`, never `facts()`, so quantities/prices/profits are declared to Cortex Analyst as categorical dimensions. See BL-181. |
| 17 | `labels = (filter)` on facts/dimensions — filter labels | Boolean formula column (`column_type: ATTRIBUTE`) | |
| 18 | Simple metrics: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` | `columns[]` with `column_type: MEASURE` + `aggregation` | |
| 19 | `COUNT(DISTINCT col)` | `unique count([T::col])` formula | Never COUNT_DISTINCT aggregation (I5) |
| 20 | Complex metric expressions (multi-column, arithmetic) | `formulas[]` with translated ThoughtSpot formula | |
| 20a | `TRIM` / `LTRIM` / `RTRIM` / `REPLACE` | `sql_string_op ( "TRIM({0})" , … )` / `sql_string_op ( "REPLACE({0}, {1}, {2})" , … )` pass-through | **None of the four ThoughtSpot names exists** — live-verified 2026-07-29 (BL-170) and re-verified 2026-07-30 (BL-171). `sv_sql.py` emitted the bare names until ts-cli v0.126.1; the pass-through forms were live-verified on se-thoughtspot 2026-07-30 |
| 20b | `STARTSWITH` / `ENDSWITH` | `( strpos ( s , p ) = 1 )` / `( substr ( s , strlen ( s ) - strlen ( x ) , strlen ( x ) ) = x )` | No native `starts_with`/`ends_with` (BL-170) — composed from native functions since ts-cli v0.126.1 (BL-171); both emitted forms live-verified 2026-07-30 |
| 21 | `non additive by (col asc nulls last) as AGG(...)` — semi-additive | `last_value(agg(...), query_groups(), {date})` formula | |
| 22 | `non additive by (col desc nulls last) as AGG(...)` | `first_value(agg(...), query_groups(), {date})` formula | |
| 23 | Window functions: `OVER (PARTITION BY ... ORDER BY ...)` | `group_sum([T::col], [T::dim])` for PARTITION BY; `group_aggregate(agg(...), query_groups()-{dim}, query_filters())` for EXCLUDING | Group functions take columns only, cannot nest in each other. Window functions (`cumulative_*`, `moving_*`) accept `group_aggregate(...)` as input but not raw aggregates. |
| 24 | `PARTITION BY EXCLUDING` | `group_aggregate(... query_groups()-{dim})` | |
| 25 | Cumulative: `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` | `moving_sum(group_aggregate(agg(...), {[T::PK]}, query_filters()), -1, 0, [T::order_col])` | Cannot nest aggregates directly in `moving_sum`; must wrap in `group_aggregate` first |
| 26 | Metric-on-fact resolution (`AVG(table.fact_name)`) | `average([formula_<id>])` | References the fact by formula `id`, derived from the fact's display name by the same function `build-model` mints ids with. A **passthrough** fact (right-hand side is a bare physical column, the shape a Cortex-Analyst model emits) is a `columns[]` entry, not a formula, so a reference to it resolves to `[TABLE::col]` instead — resolution step 1. Broken 2026-07-22 → 2026-07-30 (BL-178, three defects); **fixed and live-re-verified 2026-07-30**, and `ts tml lint` I13 now gates the dangling-reference class (BL-183). |
| 27 | Double aggregation / metric-on-metric (`AVG(table.count_metric)`) | `average(group_count([T::col], [DIM::pk]))` | **CROSS-TABLE only.** `group_*` shorthands, grouping on the PK of the parent (TO) side of the relationship connecting the two metrics' tables; full `group_aggregate(..., {key}, query_filters())` when the inner aggregation has no shorthand or the inner expression is not a simple aggregate. Every double aggregation carries a 🔄 review annotation — the grouping key and relationship direction are not machine-verifiable. Two cases are **skipped and flagged** instead: the inner metric aggregating the grouping column itself (`group_count([X],[X])` = 1 per group), and an SV cycle. Fixed and live-re-verified 2026-07-30 (BL-178). **SAME-TABLE metric-on-metric is NOT supported** — the `[formula_<id>]` fallback resolves only when the inner metric becomes a `formulas[]` entry, so a same-table reference to a simple-aggregate metric dangles, I13 fires and `build-model` **exits 1**. The common shape is a same-table ratio (`ORDERS.aov as orders.total_rev / orders.order_count`). Fails loudly rather than emitting a broken Model; the fix is to inline the inner aggregation — **BL-194**. |
| 28 | Window metrics referencing other metrics | Combined window + double-agg translation | Shares row #26/#27's resolver, so the BL-178 fix covers it; **not exercised on a live fixture** — the TPC-DS fixture contains no window-on-metric construct, so this row's evidence is unit-level only. |
| 29 | Duplicate `column_id` detection (I8) | Formula with unique `column_id` | Second metric on same column gets formula |
| 39 | Ratio metrics with a `NULLIF(y, 0)` zero-divisor guard | `safe_divide ( ... )` formula | **Changes semantics silently: `x / NULLIF(y,0)` returns NULL when `y = 0`; `safe_divide` returns 0** (and the reverse leg completes the substitution by emitting Snowflake's `DIV0`). 0 participates in `AVG`/`MIN`/ranking where NULL does not. Emitted with `annotations: []` — no flag. `nullif` is mapped in both directions (`ts-snowflake-formula-translation.md:154`), so a NULL-preserving translation was available throughout. See BL-180. |

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

### SQL-Query Logical Tables (GA 2026-06-26)

| # | Semantic View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 37 | `ALIAS as (SELECT ...)` in `tables()` — SQL-query logical table (YAML: `base_table.definition:`) | ThoughtSpot SQL View TML (`sql_view:`), referenced from `model_tables[]` | Parser now recognizes this form. Distinct from row 2 (named Snowflake views) — this is an inline SQL query with no named database object. To-direction emission of `definition:` from a ThoughtSpot `sql_view` is a separate, deferred concern tracked in BL-031 and does not affect this from-direction parse. |

---

## Unmapped Constructs (Limitations)

| # | Semantic View Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | `CUSTOM_INSTRUCTIONS` / `AI_SQL_GENERATION` / `AI_QUESTION_CATEGORIZATION` — free-text instruction strings, not ON/OFF toggles (corrected 2026-07) | No ThoughtSpot Model TML field yet for Data Model Instructions (location TBD — see `ts-object-model-coach` references/open-items.md #4) | Parse the free text (`module_custom_instructions.sql_generation` / `.question_categorization` per snowflake-schema.md) and surface as candidate Data Model Instructions content; run `/ts-object-model-coach` after conversion to place it |
| L2 | Table-level `with synonyms=('...')` on `tables()` entries | No ThoughtSpot table-level synonym concept | Add table synonyms to `model.description` or `data_model_instructions` for Spotter context |
| L3 | `ACCESS_MODIFIER: PRIVATE` on facts/metrics | No "private column" concept in ThoughtSpot models | Omit private facts/metrics; or include with `index_type: DONT_INDEX` so Spotter ignores them |
| L4 | `unique_keys` declarations on table entries | No key declarations in ThoughtSpot models | Not needed — ThoughtSpot does not use key metadata |
| L6 | BOOL columns in `if` expressions require parentheses | `if [TABLE::BOOL_COL] then...` fails. Must use `if ( [TABLE::BOOL_COL] ) then...` with parentheses around the condition. `count_if` and `sum_if` also work without this issue. | Use `if ( [T::BOOL] ) then 1 else 0` (parens required) or prefer `count_if([T::BOOL], [T::PK])` / `sum_if([T::BOOL], [T::MEASURE])` which don't need the workaround. |
| L7 | Formula import on initial model CREATE | Formulas referencing `[TABLE::COL]` fail during initial `ts tml import` (CREATE) but succeed on UPDATE (`--no-create-new`) | Always import model structure first (no formulas), then update with formulas in a second pass |
| L8 | `is_enum` dimension property (GA 2026-06-25) | No ThoughtSpot enum/categorical-dimension concept | Informational Cortex-Analyst-only aid — parsed but not carried to TML; no action needed |
| L9 | `with sample values (...)` on a dimension (Snowflake best-practice NL-parsing aid) | No ThoughtSpot sample-values concept | Informational Cortex-Analyst-only aid — parsed but not carried to TML; no action needed |
| L10 | `\|\|` string concatenation anywhere in a dimension / fact / metric expression | `ts snowflake translate-formulas` rejects the operator and **drops the whole construct** — it lands in `skipped[]` and never reaches the Model TML. `\|\|` is the ANSI standard concatenation operator, and the skip message itself names the fix ("use CONCAT() instead"), whose mapping is already bidirectional (`ts-snowflake-formula-translation.md:197-198`) | Rewrite as `CONCAT(a, ' ', b)` in the Semantic View before converting. The `\|\|` → `concat` rewrite is a mechanical N-ary fold with no judgment involved — fix tracked in BL-180. |
| L11 | `data_type` on dimensions / time_dimensions / facts (Cortex-Analyst YAML form) | No `CREATE SEMANTIC VIEW` DDL representation, so the skill's `GET_DDL` input never carries it; ThoughtSpot derives the column type from the physical column | None needed on the DDL path. When starting from the YAML form instead, the value is exactly what a Table TML's `db_column_properties.data_type` needs — map it per `ts-from-snowflake-rules.md` rather than discarding it. |

### Notes on limitations

**L10** is a converter defect rather than a platform limitation: the target mapping exists,
is bidirectional, and is cited in the very message that declines to apply it. It is recorded
here so the drop is declared while BL-180 is open, and should move to Mapped when it lands.

**L11** is informational — the property is absent from the skill's actual (DDL) input, and
is only relevant if a future path consumes the Cortex-Analyst YAML form directly.

**L1–L4, L8, L9** are low severity — ThoughtSpot has no direct equivalent or the
equivalent is easily achieved via post-conversion coaching (`/ts-object-model-coach`).
These are cosmetic/metadata features that do not affect the structural correctness of
the converted model.

**L6** is LOW severity — purely a syntax quirk. BOOL columns work in all formula contexts;
the `if` construct just requires parentheses around BOOL conditions: `if ( [T::BOOL] ) then`.
The `count_if` and `sum_if` functions work without any workaround. Verified on ThoughtSpot
Cloud (SE cluster).

**L7** is a runtime behaviour — not a fundamental limitation. The skill's Step 11 workflow
already uses two-pass import (create model without formulas → update with formulas).
This note documents WHY that pattern is required.
