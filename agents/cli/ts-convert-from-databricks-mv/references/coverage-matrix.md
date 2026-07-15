# Coverage Matrix: Databricks Metric View → ThoughtSpot Model

What the `ts-convert-from-databricks-mv` skill maps and what it does not.
Use this as the canonical limitations reference.

---

## Mapped Constructs

### Source Types

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | `source: catalog.schema.table` (table FQN) | Table TML (`db_table`, `db`, `schema` decomposed from FQN) | |
| 2 | `source: (SELECT ...)` (subquery) | SQL View TML (`sql_view:`) + Model on top | User chooses: create DBX VIEW, create TS SQL View, map to existing, or skip |
| 3 | `source: catalog.schema.another_mv` (MV-on-MV) | **Fail loud** | User must convert the upstream MV first or flatten in Databricks |

### Version and Metadata

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 4 | `version: 0.1` / `version: 1.1` | Drives parsing path | Not stored in ThoughtSpot |
| 5 | Top-level `comment:` (v1.1) | `model.description` | |
| 6 | `display_name` on dimensions/measures (v1.1) | Column `name` | |
| 7 | `comment` on dimensions/measures (v1.1) | Column `description` | |
| 8 | `synonyms` on dimensions/measures (v1.1) | `properties.synonyms` + `synonym_type: USER_DEFINED` | |
| 9 | `fields:` (GA alias for `dimensions:`) | Same mapping as `dimensions:` | `fields:` checked first, `dimensions:` fallback |

### Joins and Multi-Source

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 10 | `joins:` (nested hierarchy) | One Table TML per source; `model.joins[]` from parent→child | |
| 11 | `joins[].on` (join expression) | `joins[].on` expression as-is | |
| 12 | `joins[].using: [COL, ...]` | `[A::COL] = [B::COL]` (AND-joined for multiple columns) | |
| 13 | `joins[].cardinality` / `joins[].rely` | Parsed, precedence applied | Informational — not written to TML |

### Dimensions

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 14 | Direct column reference (`expr: col_name`) | `columns[]` with `column_type: ATTRIBUTE` | |
| 15 | Computed expression (`expr: DATE_TRUNC(...)`) | `formulas[]` entry + `columns[]` with `formula_id` | |
| 16 | Window function / LOD (`AGG() OVER (PARTITION BY ...)`) | `group_aggregate(agg([col]), {[dim]}, query_filters())` | Always 3 args; live-verified 2026-07-09 |

### Measures — Simple Aggregates

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 17 | `SUM(col)` | `columns[]` with `column_type: MEASURE`, `aggregation: SUM` | |
| 18 | `AVG(col)` / `MIN(col)` / `MAX(col)` | `columns[]` with matching `aggregation` | |
| 19 | `COUNT(col)` | `columns[]` with `aggregation: COUNT` | |
| 20 | `COUNT(*)` | Formula: `count ( 1 )` | |
| 21 | `COUNT(DISTINCT col)` | Formula: `unique count ( [T::col] )` | Never `COUNT_DISTINCT` aggregation (silently overridden to ATTRIBUTE) |
| 22 | `STDDEV(col)` / `VARIANCE(col)` | `columns[]` with matching `aggregation` | |

### Measures — Complex Expressions

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 23 | Ratio expressions (`SUM(x) / NULLIF(SUM(y), 0)`) | `safe_divide ( sum([x]) , sum([y]) )` formula | NULLIF(x,0) collapsed to safe_divide |
| 24 | Nested NULLIF in ratios (e.g. eCPC vs budget) | Nested `safe_divide` calls | |
| 25 | `COALESCE(x, 0)` | `ifnull ( [x] , 0 )` | 2-arg only; 3+ args raises |
| 26 | Cross-measure references (`MEASURE(name)` / `ANY_VALUE(dim)`) | **Inlined** — full expression substituted via dependency DAG | Cross-formula refs fail during TML import |
| 27 | Duplicate `column_id` (same column as ATTRIBUTE + MEASURE) | Measure converted to formula | Avoids unique column_id import error |

### Measures — Conditional Aggregates

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 28 | `AGG(expr) FILTER (WHERE cond)` | `sum_if(cond, [col])` / `count_if` / `average_if` etc. | Native `*_if` conditional aggregate |
| 29 | `COUNT(DISTINCT col) FILTER (WHERE cond)` | `unique_count_if(cond, [col])` | |

### Measures — Windowed

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 30 | `window:` with `range: trailing N day` (exclusive, default) | `moving_sum([m], N, -1, [date])` | Anchor excluded; live-verified 2026-07-09 |
| 31 | `window:` with `range: trailing N day inclusive` | `moving_sum([m], N-1, 0, [date])` | Anchor included; live-verified 2026-07-09 |
| 32 | `window:` with `range: leading N day` (exclusive, default) | `moving_sum([m], -1, N, [date])` | Live-verified 2026-07-09 |
| 33 | `window:` with `range: leading N day inclusive` | `moving_sum([m], 0, N-1, [date])` | Live-verified 2026-07-09 |
| 34 | `window:` with `range: cumulative` | `cumulative_sum([m], [date])` | Also `cumulative_average`, `_min`, `_max`; live-verified 2026-07-09 |
| 35 | `window:` with `range: all` | `group_aggregate(sum([m]), {partition dims}, query_filters())` | Unbounded partition window; `column_type: ATTRIBUTE`; live-verified 2026-07-09 |
| 36 | `window:` with `range: current` (period filter, no offset) | `sum([m])` at the query grain | Flow metrics; live-verified 2026-07-09 |
| 37 | `window:` with `range: current` + `offset: -N` | `moving_sum([m], N, -N, [date])` | Row-relative LAG(N) idiom; live-verified at month grain N=1 |
| 38 | Semi-additive (`window:` with raw date order, no range) | `last_value(sum([m]), query_groups(), {[date]})` / `first_value(...)` | Live-verified 2026-07-09 |

### Global Filter

| # | Metric View Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 39 | `filter:` (any boolean expression) | Boolean formula column `[MV Filter]` — users apply `[MV Filter] = true` | Always created when present; live-verified 2026-07-09 |

### SQL Expression Translation — Functions

| # | Databricks SQL | ThoughtSpot Formula | Notes |
|---|---|---|---|
| 40 | `CONCAT`, `LENGTH`, `SUBSTRING`, `TRIM`, `LTRIM`, `RTRIM` | `concat`, `strlen`, `substr`, `trim`, `ltrim`, `rtrim` | Direct rename |
| 41 | `REPLACE`, `CONTAINS`, `STARTSWITH`, `LEFT`, `RIGHT` | `replace`, `contains`, `starts_with`, `left`, `right` | |
| 42 | `LPAD`, `RPAD`, `REVERSE`, `REPEAT` | `lpad`, `rpad`, `reverse`, `repeat` | |
| 43 | `LOWER(s)` / `UPPER(s)` | `sql_string_op("LOWER({0})", [col])` / `sql_string_op("UPPER({0})", [col])` | Auto-translated pass-through (v0.50.0) |
| 44 | `ABS`, `CEIL`, `FLOOR`, `ROUND`, `MOD`, `POWER`, `SQRT` | `abs`, `ceil`, `floor`, `round`, `mod`, `pow`, `sqrt` | |
| 45 | `LN`, `LOG2`, `LOG10` | `ln`, `log2`, `log10` | |
| 46 | `GREATEST`, `LEAST` | `greatest`, `least` | |
| 47 | `YEAR`, `MONTH`, `DAY`, `HOUR`, `QUARTER` | `year`, `month_number`, `day`, `hour_of_day`, `quarter_number` | |
| 48 | `WEEKOFYEAR`, `DAYOFWEEK`, `DAYOFYEAR` | `week_number_of_year`, `day_number_of_week`, `day_number_of_year` | |
| 49 | `MINUTE(ts)` / `SECOND(ts)` | `sql_int_op("MINUTE({0})", [col])` / `sql_int_op("SECOND({0})", [col])` | Auto-translated pass-through (v0.50.0) |
| 50 | `DATE_FORMAT(d, 'fmt')` | `sql_string_op("DATE_FORMAT({0}, 'fmt')", [col])` | Format literal baked into SQL template (v0.50.0) |
| 51 | `DATE_ADD(d, n)` / `ADD_MONTHS(d, n)` | `add_days`, `add_months` | |
| 52 | `DATE_TRUNC('day'/'week'/'month'/'quarter'/'year', d)` | `date`, `start_of_week`, `start_of_month`, `start_of_quarter`, `start_of_year` | |
| 53 | `DATE_TRUNC('hour'/'minute'/'second', ts)` | `sql_date_time_op("DATE_TRUNC('UNIT', {0})", [col])` | Sub-day pass-through (v0.49.0) |
| 54 | `EXTRACT(YEAR/MONTH/DAY/HOUR FROM d)` | `year`, `month_number`, `day`, `hour_of_day` | |
| 55 | `DATEDIFF(end, start)` / `DATEDIFF(DAY, s, e)` | `diff_days(start, end)` | Arg order reversed; 2-arg and 3-arg forms |
| 56 | `DATEDIFF(MONTH, s, e)` | `diff_months(s, e)` | |
| 57 | `MONTHS_BETWEEN(a, b)` | `diff_months(b, a)` | Arg order reversed |
| 58 | `LOCATE(sub, s)` | `strpos(s, sub)` | Arg order reversed |
| 59 | `TO_DATE('literal', 'format')` | `to_date('literal', 'format')` | Raw string args — no date-literal wrapping |

### SQL Expression Translation — Constructs

| # | Databricks SQL | ThoughtSpot Formula | Notes |
|---|---|---|---|
| 60 | `CASE WHEN cond THEN val ELSE val END` | `if (cond) then val else val` | Multi-branch → nested `if` (v0.49.0) |
| 61 | `IF(cond, then_val, else_val)` | `if (cond) then then_val else else_val` | (v0.49.0) |
| 62 | `CAST(expr AS type)` | Unwrapped — target type dropped (implicit in TS) | Precision specs `DECIMAL(10,2)` skipped |
| 63 | `x IS NULL` / `x IS NOT NULL` | `isnull([x])` / `not ( isnull([x]) )` | |
| 64 | `x IN (a, b, c)` | `( [x] = a or [x] = b or [x] = c )` | |
| 65 | `x BETWEEN lo AND hi` | `[x] >= lo and [x] <= hi` | |
| 66 | `NOT expr` | `not ( expr )` or `[col] = false` for boolean columns | |
| 67 | `NULLIF(x, 0)` in denominator | Collapsed to `safe_divide` on the enclosing division | |
| 68 | `COALESCE(x, default)` | `ifnull(x, default)` | 2-arg only |

### Operational Capabilities

| # | Capability | Notes |
|---|---|---|
| 69 | Scenario A — existing ThoughtSpot Table objects | Reuses GUIDs and column names from exported Table TML |
| 70 | Scenario B — new Table objects from Databricks schema | Creates Table TML from connection introspection |
| 71 | Spotter enablement | `model.properties.spotter_config.is_spotter_enabled` (user confirms) |
| 72 | File-only mode | Generates TML files without importing — for manual import |
| 73 | MV version routing (v0.1 / v1.1) | Automatic — `fields:` aliasing, `display_name`/`comment`/`synonyms` extraction |
| 74 | `materialization:` block | Parsed and passed through; not mapped to TML |

---

## Unmapped Constructs (Limitations)

| # | Metric View Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | `source:` as another metric view (MV-on-MV chaining) | Not supported — cannot resolve the upstream MV's schema | Convert the upstream MV first, or flatten the chain in Databricks |
| L2 | Multi-MV merge into single model | Deferred (open-items #1) — when a multi-table TS model was split into multiple MVs during to-direction conversion, the from-direction does not yet support merging them back | Convert each MV individually; manually combine models in ThoughtSpot |
| L3 | `parameters:` block (GA 18.2+) | Parsed but not translated — auto-translation deferred | Manually add parameters to the ThoughtSpot model after conversion |
| L4 | Subquery in a dimension/measure `expr` (not the `source:`) | Untranslatable — logged in Unmapped Report | Rewrite as a Databricks VIEW or pre-compute in the source table |
| L5 | `NOT IN` / `NOT BETWEEN` / `NOT LIKE` | No documented ThoughtSpot mapping | Rewrite using positive logic (`IN` with inverted condition, manual range check) |
| L6 | `DISTINCT` under non-COUNT aggregates (`SUM(DISTINCT x)`) | No ThoughtSpot mapping | Pre-deduplicate in the source table or use a Databricks VIEW |
| L7 | `COALESCE` with 3+ arguments | Only 2-arg COALESCE maps to `ifnull` | Nest: `ifnull(a, ifnull(b, c))` |
| L8 | Window measures with non-daily order dimension | Emitted with a sparse-data-risk warning (BL-098) | Valid but may diverge from Databricks on gapped data — TS uses row-positional frames, Databricks uses date-interval frames |
| L9 | `window:` `offset` with quarter/year grain or N>1 | Deferred extrapolation of the month-grain N=1 live-verified pattern (C8) | Use month grain where possible; for other grains, verify results manually |
| L10 | `AGG(DISTINCT col) FILTER (WHERE cond)` for non-COUNT aggregates | No ThoughtSpot mapping for `sum_distinct_if` etc. | Pre-aggregate in the source or split into filtered view + distinct aggregate |

### Notes on limitations

**L1–L2** are structural — they reflect the single-source constraint of Metric Views
and the deferred merge capability. Not a translation gap.

**L3** is deferred automation — MV `parameters:` is a GA construct but the converter
doesn't yet generate ThoughtSpot parameters from it. Manual post-conversion step.

**L4–L7, L10** are SQL expression edge cases. Most real-world MVs don't hit these;
the two E2E exercises (B2C Outbound Fulfillment — 83 dims, 21 measures, 3 joins,
subquery source, global filter; E2E Reporting Daily — 10 dims, 82 measures, 37
ratio formulas) translated fully without hitting any of these limitations.

**L8–L9** are window-measure precision caveats — the translation is emitted but with
a warning about potential divergence on sparse or non-daily data.
