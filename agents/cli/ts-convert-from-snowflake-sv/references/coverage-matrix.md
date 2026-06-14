# Coverage Matrix: Snowflake Semantic View → ThoughtSpot Model

What the `ts-convert-from-snowflake-sv` skill maps and what it does not.
Use this as the canonical limitations reference.

Last verified: 2026-06-14 (BL018_TEST_SV end-to-end on se-thoughtspot)

---

## Mapped Constructs

| # | Semantic View Construct | ThoughtSpot Equivalent | Verified Against |
|---|---|---|---|
| 1 | `tables (DB.SCHEMA.TABLE)` block | `model_tables[]` entries | All test SVs |
| 2 | `tables (DB.SCHEMA.VIEW)` — view-backed sources | Same as physical tables (TS tables can point to views) | BL018_TEST_SV (EMPLOYEE_SUMMARY_VW) |
| 3 | Table aliases (explicit + implicit) | `model_tables[].name` | BIRD_SUPERHEROS_SV |
| 4 | `primary key (col)` on table entries | Join target identification (not written to TML) | All test SVs |
| 5 | Table-level `comment='...'` | TS Table TML `table.description` (separate update) | DUNDER_MIFFLIN_SV |
| 6 | Top-level `comment='...'` (after metrics) | `model.description` | All test SVs |
| 7 | `relationships (REL as FROM(FK) references TO(PK))` — equi joins | `joins[]` inline on the FROM table entry | All test SVs |
| 8 | `references TABLE(between START and END exclusive)` — range joins | `joins[].on` with `>=` / `<` expression | BL018_TEST_SV (EMP_TO_PERIOD) |
| 9 | `references TABLE(COL1, ASOF COL2)` — ASOF joins | `joins[].on` with `=` on COL1, `>=` on ASOF col | BL018_TEST_SV (EMP_TO_RATE: DEPARTMENT + asof EFFECTIVE_DATE) |
| 10 | Composite equi-joins (`FROM(C1,C2) references TO(C1,C2)`) | `joins[].on` with multiple `=` pairs | BL018_TEST_SV (EMP_TO_SUMMARY) |
| 11 | Joinless SVs (no `relationships` block) | 4-option join discovery workflow: PK/FK, column overlap, manual, separate models | BL018_TEST_SV (EMPLOYEE_SUMMARY_VW) |
| 12 | `dimensions (TABLE.COL as NAME)` | `columns[]` with `column_type: ATTRIBUTE` | All test SVs |
| 13 | Computed dimensions (`DATEDIFF`, `CONCAT`, `CASE/WHEN`) | `formulas[]` with `column_type: ATTRIBUTE` | COMPANY_WORKFORCE_SV (SALARY_BAND) |
| 14 | `with synonyms=('...',...)` on dimensions/metrics | First → column `name`; rest → `properties.synonyms` | DUNDER_MIFFLIN_SV, BL018_TEST_SV |
| 15 | `comment='...'` on dimensions/metrics | column `description` | DUNDER_MIFFLIN_SV, COMPANY_WORKFORCE_SV |
| 16 | `facts (TABLE.NAME as EXPR)` — row-level expressions | `formulas[]` entries (MEASURE or ATTRIBUTE) | COMPANY_WORKFORCE_SV, BL018_TEST_SV |
| 17 | `labels = (filter)` on facts/dimensions — filter labels | Boolean formula column (`column_type: ATTRIBUTE`) | BL018_TEST_SV (IS_SENIOR) |
| 18 | Simple metrics: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` | `columns[]` with `column_type: MEASURE` + `aggregation` | All test SVs |
| 19 | `COUNT(DISTINCT col)` | `unique count([T::col])` formula (never `COUNT_DISTINCT` aggregation — I5) | DUNDER_MIFFLIN_SV |
| 20 | Complex metric expressions (multi-column, arithmetic) | `formulas[]` with translated ThoughtSpot formula | BIRD_SUPERHEROS_SV |
| 21 | `non additive by (col asc nulls last) as AGG(...)` — semi-additive | `last_value(agg(...), query_groups(), {date})` formula | DUNDER_MIFFLIN_SV |
| 22 | `non additive by (col desc nulls last) as AGG(...)` | `first_value(agg(...), query_groups(), {date})` formula | DUNDER_MIFFLIN_SV |
| 23 | Window functions: `OVER (PARTITION BY ... ORDER BY ...)` | `group_sum` / `group_aggregate` formula | BIRD_SUPERHEROS_SV |
| 24 | `PARTITION BY EXCLUDING` | `group_aggregate(... query_groups()-{dim})` | Mapped; verified in formula reference |
| 25 | Cumulative: `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` | `cumulative_sum` / `cumulative_avg` formula | Mapped; verified in formula reference |
| 26 | Metric-on-fact resolution (`AVG(table.fact_name)`) | `average([formula_<id>])` — references fact by formula `id` | COMPANY_WORKFORCE_SV, BL018_TEST_SV |
| 27 | Double aggregation / metric-on-metric (`AVG(table.count_metric)`) | `average(group_count([T::col], [DIM::pk]))` — `group_*` shorthands | COMPANY_WORKFORCE_SV |
| 28 | Window metrics referencing other metrics | Combined window + double-agg translation | Mapped in SKILL.md |
| 29 | Duplicate `column_id` detection (I8) | Second metric on same column → formula | BL018_TEST_SV (TOTAL_SALARY / AVG_SALARY) |
| 30 | `ai_verified_queries (QUERY_NAME AS (...))` | NLS Feedback TML (`REFERENCE_QUESTION` entries) | BL018_TEST_SV (3 queries) |
| 31 | `with extension (CA='...')` | Parsed for type confirmation; not mapped to TML | BIRD_SUPERHEROS_SV |
| 32 | `constraint ... distinct range between START and END` on table entries | Parsed; used to identify range join endpoints | BL018_TEST_SV (FISCAL_PERIODS) |
| 33 | Spotter enablement | `model.properties.spotter_config.is_spotter_enabled` (user confirms) | All test SVs |
| 34 | Mode A (single SV → new model) | Full workflow Steps 1–12.5 | All test SVs |
| 35 | Mode B (merge multiple SVs → one model) | Multi-SV DDL fetch + dedup + merge | Mapped in SKILL.md |
| 36 | Mode C (update existing model from changed SV) | Structural + metadata diff with per-column MERGE/UPDATE/KEEP | Mapped in SKILL.md |

---

## Unmapped Constructs (Limitations)

| # | Semantic View Construct | ThoughtSpot Equivalent | Severity | Workaround |
|---|---|---|---|---|
| L1 | `CUSTOM_INSTRUCTIONS` (`AI_QUESTION_CATEGORIZATION`, `AI_SQL_GENERATION`) | `data_model_instructions` on the model | LOW | Run `/ts-object-model-coach` after conversion to add Spotter instructions manually |
| L2 | Table-level `with synonyms=('...')` on `tables()` entries | No ThoughtSpot table-level synonym concept | LOW | Add table synonyms to `model.description` or `data_model_instructions` for Spotter context |
| L3 | `ACCESS_MODIFIER: PRIVATE` on facts/metrics | No "private column" concept in ThoughtSpot models | LOW | Omit private facts/metrics from the model; or include with `index_type: DONT_INDEX` so Spotter ignores them |
| L4 | `unique_keys` declarations on table entries | No key declarations in ThoughtSpot models | LOW | Not needed — ThoughtSpot does not use key metadata |
| L5 | Subquery-backed sources (`FROM (<subquery>)` in tables block) | SQL View TML (`sql_view:` type) | N/A | Snowflake `tables()` does not support subquery sources (verified 2026-06-13) — this scenario cannot occur. If a future SV version adds subquery support, implement using the pattern from `ts-convert-from-databricks-mv` (Step 2c) |

### Notes on limitations

**L1–L4** are LOW severity because ThoughtSpot has no direct equivalent or the
equivalent is easily achieved via post-conversion coaching (`/ts-object-model-coach`).
These are cosmetic/metadata features that do not affect the structural correctness of
the converted model.

**L5** was originally MEDIUM severity but has been reclassified as N/A — Snowflake's
`tables()` block does not support subquery sources (verified 2026-06-13). Only named
database objects (tables and views) are valid. If a future SV version adds subquery
support, this limitation would need to be reopened.

**ASOF joins** (row 9) verified end-to-end on BL018_TEST_SV (2026-06-14) with the
`EMP_TO_RATE` relationship: `EMPLOYEES(DEPARTMENT, HIRE_DATE) references
SALARY_RATES(DEPARTMENT, asof EFFECTIVE_DATE)`. ThoughtSpot model import and
round-trip confirmed.

---

## Test Semantic Views

| SV Name | Database.Schema | Features Exercised |
|---|---|---|
| BIRD_SUPERHEROS_SV | DEMO.SEMANTIC_TESTING | Basic tables, equi joins, dimensions, simple + complex metrics, window functions, synonyms |
| DUNDER_MIFFLIN_SALES_INVENTORY | DEMO.SEMANTIC_TESTING | Multi-value synonyms, per-column descriptions, table comments, semi-additive (closing/opening), `unique count`, `concat()` |
| COMPANY_WORKFORCE_SV | AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST | Facts, metric-on-fact (`[formula_<id>]`), double aggregation (`group_count`/`group_sum`), duplicate `column_id`, `if()` parenthesization |
| BL018_TEST_SV | AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST | Range joins, ASOF joins, composite equi-joins, filter labels, I8 detection, verified queries → NLS Feedback, view-backed sources, joinless table discovery |
