# Coverage Matrix: ThoughtSpot Model → Databricks Metric View

What the `ts-convert-to-databricks-mv` skill maps and what it does not.
Use this as the canonical limitations reference.

**Implemented by `ts databricks build-mv`** (`tools/ts-cli/ts_cli/databricks/mv_emit.py`,
`mv_emit_sql.py`, `mv_emit_window.py`, `mv_build_view.py`). This is a deterministic
CLI emitter, not an agentic pipeline — every row below is a rule the code applies,
not a step the model works through by hand. Cross-check against
[ts-databricks-formula-translation.md](../../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md)
for the full bidirectional translation reference.

---

## Mapped Constructs

### Structure, Joins, and Multi-Fact Splitting

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 1 | Model `description` | Top-level `comment:` | |
| 2 | `model_tables[]` fact + dimension structure | Nested `joins:` (v1.1 star schema) | `build_joins` walks breadth-first from the source table |
| 3 | Join `on:` (inline equality, `AND`-joined conjuncts) | Dot-path equality in the nested join's `on:` | Only simple `a.COL = b.COL [AND ...]` — no `<`/`>`/`!=` conjuncts |
| 4 | Join `using:` (column list) | Dot-path equality generated from the shared column names | |
| 5 | `referencing_join` | Resolved via the source table's `joins_with[]` `on:` clause | Falls back to `joins[]` defensively; raises if not found |
| 6 | Join `cardinality: MANY_TO_ONE` | `cardinality: many_to_one` on the MV join node | `ONE_TO_MANY` and unset both fall through with no `cardinality:` key |
| 7 | Multi-fact models | One independent MV per detected fact table | `detect_fact_tables` — join-root tables carrying ≥1 MEASURE column |

### Columns and Column Metadata

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 8 | `ATTRIBUTE` column, physical (non-date) | `dimensions[]` — bare dot-path `expr` | |
| 9 | `ATTRIBUTE` column, physical (date/timestamp) | `dimensions[]` — same as non-date | No separate `time_dimensions` in the MV schema |
| 10 | `MEASURE` column with `properties.aggregation` | `measures[]` — `expr: AGG(dot-path)` | Default aggregation `SUM` when unset |
| 11 | `MEASURE` column, `aggregation: COUNT_DISTINCT` | `measures[]` — `expr: COUNT(DISTINCT dot-path)` | |
| 12 | `properties.description` | `comment:` | |
| 13 | `properties.synonyms[]` | `synonyms:` list | |
| 14 | `properties.currency_type.iso_code` | `format: {type: currency, currency_code: ...}` | |
| 15 | `ai_context` | **NOT MAPPED** | See Unmapped L2 |
| 16 | Data type `VARCHAR` | `string` | `ts_type_to_dbx` (`mv_tml.py`) |
| 17 | Data type `INT64` | `bigint` | |
| 18 | Data type `DOUBLE` | `double` | |
| 19 | Data type `BOOL` | `boolean` | |
| 20 | Data type `DATE` | `date` | |
| 21 | Data type `DATETIME` | `timestamp` | |

### Aggregate Functions

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 22 | `sum(x)` | `SUM(x)` | |
| 23 | `count(x)` | `COUNT(x)` | |
| 24 | `count(1)` | `COUNT(*)` | Recognized as the `count(1)`-shaped call, not a generic literal count |
| 25 | `unique count(x)` | `COUNT(DISTINCT x)` | Tokenized as a two-word identifier (space, not underscore) |
| 26 | `average(x)` / `avg(x)` | `AVG(x)` | |
| 27 | `min(x)` / `max(x)` | `MIN(x)` / `MAX(x)` | |
| 28 | `stddev(x)` | `STDDEV(x)` | |
| 29 | `variance(x)` | `VARIANCE(x)` | |

### Conditional Aggregates (`*_if` family)

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 30 | `sum_if(cond, x)` / `count_if` / `average_if` / `min_if` / `max_if` / `stddev_if` / `variance_if` | `AGG(x) FILTER (WHERE cond)` | |
| 31 | `unique_count_if(cond, x)` | `COUNT(DISTINCT x) FILTER (WHERE cond)` | |

### Scalar and Logic Functions

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 32 | `safe_divide(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` | Numerator re-parenthesized when it is itself a binop |
| 33 | `if_null(x, d)` / `ifnull(x, d)` | `COALESCE(x, d)` | |
| 34 | `zero_if_null(x)` | `COALESCE(x, 0)` | |
| 35 | `null_if_zero(x)` | `NULLIF(x, 0)` | |
| 36 | `isnull(x)` | `x IS NULL` | |
| 37 | `[x] = null` / `[x] != null` | `x IS NULL` / `x IS NOT NULL` | Binop null-comparison special case, not the `isnull()` call form |
| 38 | `if (cond) then a else b` | `CASE WHEN cond THEN a ELSE b END` | |
| 39 | `if(cond, a, b)` (function form) | `CASE WHEN cond THEN a ELSE b END` | |
| 40 | `in(x, a, b, c)` | `x IN (a, b, c)` | |
| 41 | `between(x, lo, hi)` | `x BETWEEN lo AND hi` | |
| 42 | `concat` / `greatest` / `least` / `upper` / `lower` / `abs` / `round` / `length` / `strlen` / `trim` | `CONCAT` / `GREATEST` / `LEAST` / `UPPER` / `LOWER` / `ABS` / `ROUND` / `LENGTH` / `LENGTH` / `TRIM` | Direct rename, same arg order |

### Level of Detail (LOD)

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 43 | `group_aggregate(agg(x), {dims}, query_filters())` | Dimension — `expr: AGG(x) OVER (PARTITION BY dims)` | LOD results are always dimensions, never measures |
| 44 | `group_sum` / `group_count` / `group_average` / `group_max` / `group_min` `(x, dim)` | Dimension — `expr: AGG(x) OVER (PARTITION BY dim)` | Two-arg shorthand forms |
| 45 | `group_unique_count(x, dim)` | Dimension — `expr: COUNT(DISTINCT x) OVER (PARTITION BY dim)` | |
| 46 | `group_aggregate(..., query_groups())` (query-group modifier) | **Unmapped** — raises | See Unmapped L6 |

### Window Measures — Moving / Rolling

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 47 | `moving_sum`/`moving_average(m, N, -1, d)` | `window: [{order: d, range: trailing N day, semiadditive: last}]` | Default/exclusive anchor |
| 48 | `moving_sum`/`moving_average(m, N-1, 0, d)` | `window: [{order: d, range: trailing N day inclusive, semiadditive: last}]` | Anchor row included |
| 49 | `moving_sum`/`moving_average(m, -1, N, d)` | `window: [{order: d, range: leading N day, semiadditive: last}]` | Default/exclusive anchor |
| 50 | `moving_sum`/`moving_average(m, 0, N-1, d)` | `window: [{order: d, range: leading N day inclusive, semiadditive: last}]` | Anchor row included |
| 51 | Any other `(start, end)` pair | **Unmapped — manual review** | `_moving_range` raises `UntranslatableError` rather than guess; a non-positive derived N is also rejected |

### Window Measures — Cumulative and Semi-Additive

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 52 | `cumulative_sum`/`cumulative_average(m, d)` | `window: [{order: d, range: cumulative, semiadditive: last}]` | |
| 53 | `last_value(agg(m), query_groups(), {d})` | `window: [{order: d, semiadditive: last, range: current}]` | True semi-additive (snapshot metric) |
| 54 | `first_value(agg(m), query_groups(), {d})` | `window: [{order: d, semiadditive: first, range: current}]` | |
| 55 | `sum_if`/other `*_if(diff_months([d], today()) = N, [m])` | `window: [{order: month_dim, range: current, offset: N month, semiadditive: last}]` | **Lossy approximation** — see Unmapped L3 |
| 56 | `*_if(diff_quarters([d], today()) = N, [m])` | Same, offset in 3-month units | Same lossy-approximation caveat |
| 57 | `*_if(diff_years(...) = N, [m])` | **Unmapped** — raises | `diff_years` is not in `_PERIOD_OFFSET_GRAIN`; only `diff_months`/`diff_quarters` are recognized |

### Cross-Measure / Cross-Dimension References

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 58 | `[measure_name]` referenced inside another measure's formula | `MEASURE(measure_name)` | Resolved from this MV's own column classification (`make_ref_resolver`) |
| 59 | `[lod_dimension]` referenced inside a measure's formula | `ANY_VALUE(lod_dimension)` | |
| 60 | A sibling formula's `MEASURE()`/`ANY_VALUE()` ref where the referenced column itself failed emission | Cascade-removed from `dimensions[]`/`measures[]`, logged in `skipped[]` | Runs to a fixed point (transitive chain); does **not** scan the top-level `filter:` string — see Unmapped L4 |

### Row Filters

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 61 | Boolean-shaped formula (`ATTRIBUTE`, top-level comparison/`and`/`or`/`not`/`in`/`between`) | MV top-level `filter:` (multiple filters `AND`-joined, each parenthesized) | Emits a warning asking the user to confirm the routing |
| 62 | `ATTRIBUTE` formula whose *name* contains "filter" but is not boolean-shaped | Routed to `dimensions[]` instead of `filter:` | Never silently dropped — always logged as a warning |

### SQL Pass-Through

| # | ThoughtSpot Construct | Databricks Metric View Equivalent | Notes |
|---|---|---|---|
| 63 | `sql_int_op`/`sql_bool_op`/`sql_str_op`/`sql_string_op`/`sql_number_op`/`sql_date_op`/`sql_datetime_op` — single string-literal argument | Unwrapped — the inner SQL text is emitted raw | Raises if the wrapper has more than one argument or a non-literal argument |
| 64 | 2-argument `{0}`-template pass-through form (e.g. `sql_string_op("LOWER({0})", [col])`) | **Not implemented** — raises | See Unmapped L5 |

---

## Unmapped Constructs (Limitations)

| # | ThoughtSpot / Input Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | `sql_view`-backed table referenced by the model | `ts databricks build-mv` reads raw Table TML only — a `sql_view` entry in `--tables` crashes with a `KeyError`-shaped failure | Classify the `sql_view` at Step 4 (Simple/Complex) and choose **S (Skip)** for the deterministic path; omit it from `tables_export.json` before Step 5 |
| L2 | `ai_context` | No Metric View field carries free-text AI context | Fold relevant context into the MV's top-level `comment:` manually if needed |
| L3 | Period-offset `*_if(diff_months/diff_quarters(...) = N, [m])` | Mapped to Databricks window `offset:`, which is **row-relative** (LAG-style, shifts by N rows in the `order:` dimension), not wall-clock `today()`-anchored like the ThoughtSpot source. Exact only for a query returning one row per period at a single current-period snapshot; diverges on a multi-period trend query (e.g. a MoM/YoY growth-% column spanning several months) | None at the automated layer — review any period-over-period measure manually against a multi-period query before relying on it; the "moving_sum LAG idiom" is the closer-fidelity from-direction reference form |
| L4 | A dangling `MEASURE()`/`ANY_VALUE()` reference inside the MV's `filter:` string | The dangling-reference cascade (row 60 above) only scans `dimensions[]`/`measures[]` expressions, not the combined `filter:` string | Rare in practice — an MV `filter:` is a row-level `WHERE`, where `MEASURE()`/`ANY_VALUE()` are not valid anyway, so a boolean filter formula referencing a cross-measure/LOD ref would already be a modeling error upstream |
| L5 | 2-argument `{0}`-template SQL pass-through (`sql_string_op("FN({0})", [col])`) | Only the single-argument (already-complete SQL string) pass-through form is implemented; the 2-arg template form raises `UntranslatableError` | Rewrite the formula as the single-argument form, inlining the column reference directly into the SQL string, before conversion |
| L6 | `group_aggregate(...)` with a `query_groups()` third argument | Cannot be expressed as a dimension window function — no Databricks analogue for the query-group-aware LOD variant | Omit or rewrite as `query_filters()`-based `group_aggregate` if the query-group semantics aren't load-bearing |
| L7 | Worksheet input | `ts databricks build-mv` reads Model TML (`model_tables[]`/`columns[]`) only — a Worksheet's `worksheet_columns[]` shape is not understood | Convert/promote the Worksheet to a Model in ThoughtSpot first, then re-run against the Model GUID |
| L8 | A fact table whose *only* measures are condition-first formulas (e.g. a lone `sum_if(diff_months(...), [FACT::v])` with no physical `MEASURE` column) | `detect_fact_tables`'s attribution walk can resolve such a formula to the *condition's* table rather than the fact, under-detecting the fact | Pass `--source-table` explicitly to `build-mv` rather than relying on auto-detection |
| L9 | Complex `group_aggregate`/window shapes: ordered-set aggregates, running/frame windows (`ORDER BY`/`ROWS`/`RANGE`/`GROUPS` inside the window), or a formula spanning multiple `OVER (...)` clauses | No dimension-window-function analogue on the ThoughtSpot side | Not translatable — log in the Unmapped Report and handle manually |

### Notes on limitations

**L1, L2, L6, L9** are structural — no automated fallback exists today. They are
logged in `skipped[]`/the Unmapped Report at build time rather than silently
dropped.

**L3** is the most consequential limitation in the codified emit path — it produces
a plausible-looking but numerically wrong Metric View for any period-over-period
measure queried across more than one period. See
`references/open-items.md` #3 for the full write-up and the Task 18 live-fidelity
gate that exercises it.

**L5 and L7** are scope boundaries, not defects — the skill's frontmatter and Step 0
plan both document that Model TML (not Worksheet TML, and not the 2-arg pass-through
form) is the supported input shape.

**L4 and L8** are edge cases with a documented, fail-loud workaround (`--source-table`
for L8; L4 is benign because a `filter:` string can never validly contain a
`MEASURE()`/`ANY_VALUE()` reference in the first place).
