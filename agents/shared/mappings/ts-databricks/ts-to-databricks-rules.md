<!-- currency: databricks — 2026-07 (PR1 window deep-analysis 2026-07-09: TS→MV window emission tables corrected to live-verified forms (C1/C3/C6/C6a), leading PENDING resolved, strict (start,end) reverse-map added; see BL-032 + docs/audit/2026-07-08-dbx-window-claim-matrix.md; PR1.5 semantic deep-dive 2026-07-09: LOD dimension × filter (A1) CONFIRMED filter-aware on TS under both filter kinds, cross-platform DIVERGENCE for a DBX consumer's ad hoc query-time WHERE (A2, DBX-internal asymmetry); cross-measure ratio × grain (B1) CONFIRMED ratio-of-sums cross-platform at every grain; global filter: × window ordering (C1) CONFIRMED filter-before-window cross-platform, frame semantics DIVERGENCE (date-interval vs row-positional); semi-additive × date-range filter (D1) CONFIRMED last/first-in-filtered-range cross-platform; trailing-window frame (E1) DIVERGENCE — DBX date-interval vs TS row-positional on gapped data, density caveat added; A3 follow-up (user-suggested) 2026-07-09: group_aggregate's `{}` filter argument CORRECTS the A1/A2 "no TS analogue" conclusion — `{}` is search-filter-blind but model-filter-aware, reproducing DBX's MV-filter-aware + query-WHERE-blind composite when paired with a mirrored model-level filters: block; subtraction form query_filters() - {col} import-accepted but does not exclude a derived-formula filter — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md; see BL-032) -->

# Mapping Rules Reference

ThoughtSpot → Databricks Metric View conversion tables. Consult during Steps 4–9.

**Always use v1.1** — even for single-source MVs. v1.1 supports `source:` (same as
v0.1) but adds `display_name`, `comment`, and `synonyms` per column.

---

## Column Type Classification

Apply this decision tree to every column:

```
Is formula_id set?
  YES → Is it a LOD formula (group_aggregate with partition)?
          YES → dimensions (with window function in expr — see LOD section)
        Is it last_value/first_value (semi-additive)?
          YES → measures with window: [{semiadditive: last/first}] — see Semi-Additive section
        Is it sum_if(diff_months/quarters/years(...))?
          YES → measures with window: [{range: current, offset: ...}] — see Period-Filter section
        Is it moving_sum/moving_average?
          YES → measures with window: [{range: trailing N day}] — see Rolling Window section
        Is it cumulative_sum?
          YES → measures with window: [{range: cumulative}] — see Cumulative section
        Is it *_if(cond, x) (sum_if, count_if, unique_count_if, etc.)?
          YES → measures with FILTER (WHERE ...) — see Conditional Aggregates section
        Is it agg(if (cond) then x else null) (fallback pattern)?
          YES → measures with FILTER (WHERE ...) — see Conditional Aggregates section
          NO  → measures (if translatable) or OMIT (if untranslatable — see Step 9)
  NO  → Is column_type MEASURE?
          YES → measures
          NO  → dimensions
```

Unlike Snowflake SVs, Databricks Metric Views have no separate `time_dimensions`
category — date/timestamp columns go into `dimensions` alongside all other attributes.

---

## Aggregation Functions

Databricks MV embeds the aggregation in the measure `expr` — same pattern as
Snowflake SVs but with Databricks SQL syntax.

| ThoughtSpot `aggregation` | Databricks MV `expr` wrapper |
|---|---|
| `SUM` | `SUM(expr)` |
| `COUNT` | `COUNT(expr)` |
| `COUNT_DISTINCT` | `COUNT(DISTINCT expr)` |
| `AVG` / `AVERAGE` | `AVG(expr)` |
| `MIN` | `MIN(expr)` |
| `MAX` | `MAX(expr)` |
| `STD_DEVIATION` | `STDDEV(expr)` |
| `VARIANCE` | `VARIANCE(expr)` |
| *(not set on MEASURE)* | `SUM(expr)` *(default)* |

---

## Data Types

Databricks Metric Views do not have an explicit `data_type` field on dimensions
or measures. The data type is inferred from the source table column and the `expr`.

For reference when determining column classification from ThoughtSpot TML:

| Source field value | Databricks type | Classification |
|---|---|---|
| `VARCHAR`, `CHAR`, `TEXT`, `STRING` | `STRING` | dimension |
| `INT`, `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT`, `INT64` | `BIGINT`/`INT` | dimension or measure |
| `FLOAT`, `DOUBLE`, `DECIMAL`, `NUMERIC`, `REAL`, `NUMBER` | `DOUBLE`/`DECIMAL` | dimension or measure |
| `BOOLEAN`, `BOOL` | `BOOLEAN` | dimension |
| `DATE` | `DATE` | dimension |
| `DATETIME`, `DATE_TIME`, `TIMESTAMP`, `TIMESTAMP_NTZ` | `TIMESTAMP` | dimension |

---

## Name Generation Rules

Databricks MV dimension and measure names support spaces and mixed case —
no snake_case conversion needed. Use the ThoughtSpot display name directly:

```yaml
dimensions:
  - name: Sale Date          # Keep as-is from ThoughtSpot display name
    expr: sale_date
measures:
  - name: Total Revenue      # Keep as-is
    expr: SUM(revenue)
```

If the ThoughtSpot name contains characters that break YAML parsing (colons,
quotes, `#` at start of line), wrap the name in quotes:

```yaml
  - name: "Revenue: YoY Growth (%)"
    expr: ...
```

---

## v1.1 Column Metadata Mapping

v1.1 columns support rich metadata. Map ThoughtSpot properties as follows:

| ThoughtSpot property | v1.1 MV field | Notes |
|---|---|---|
| Column `name` (display name) | `display_name:` | Wrap in quotes for YAML safety |
| Column `description` | `comment:` | |
| `properties.synonyms[]` | `synonyms:` | Read from `properties.synonyms`, NOT column root. YAML list: `['alias1', 'alias2']` |
| Model-level `description` | Top-level `comment:` | |
| `ai_context` | **Unmapped** | No equivalent — log in Unmapped Report |
| `properties.calendar_type` | **Unmapped** | No equivalent |

The `name:` field in MV YAML is a machine-readable identifier (snake_case recommended).
The `display_name:` is the human-readable label.

---

## Expression Rules

### Single Source (v0.1 or v1.1 with `source:`)

Column references in `expr` use the source table's physical column names directly
(no table alias prefix):

```yaml
source: catalog.schema.fact_sales

dimensions:
  - name: store_id
    expr: store_id
    display_name: 'Store ID'

  - name: sale_year
    expr: YEAR(sale_date)
    display_name: 'Sale Year'

measures:
  - name: total_sales
    expr: SUM(sales_amount)
    display_name: 'Total Sales'
```

### Multi-Source (v1.1 with `joins:`)

Column references use `alias.column` dot-path prefix. Multi-source uses the
top-level `source:` for the fact table and `joins:` for dimension tables
(see the Multi-Table Model Mapping section below and the schema reference
in `agents/shared/schemas/databricks-metric-view.md`):

```yaml
source: catalog.schema.fact_sales
joins:
  - name: stores
    source: catalog.schema.dim_stores
    "on": source.store_id = stores.store_id
    rely: { at_most_one_match: true }

dimensions:
  - name: store_name
    expr: stores.store_name
    display_name: 'Store Name'

measures:
  - name: total_sales
    expr: SUM(source.sales_amount)
    display_name: 'Total Sales'
```

---

## Filter Generation

ThoughtSpot models may contain boolean ATTRIBUTE formulas intended as filters
(e.g., `[MV Filter]`, `[Is Active]`). Detect these and translate to the MV
`filter:` field when possible.

### Detection

Look for formula columns that match these patterns:
- `column_type: ATTRIBUTE` with a boolean expression (comparisons, AND/OR, NOT)
- Column name contains "filter" (case-insensitive) — e.g., "MV Filter"
- Formula expr produces a boolean result (equality checks, `in()`, `between()`, etc.)

### Classification and translation

```
Is the formula a simple boolean expression?
  (Only AND-joined conditions, each being col = val, col != val, NOT col,
   col > val, col >= val, col < val, col <= val)
  YES → Translate to MV filter: field
        Each condition maps to SQL:
          [TABLE::col] = 'val'     → col = 'val'
          [TABLE::col] = false     → NOT col
          [TABLE::col] > N         → col > N
  NO  → Does it contain OR, in(), between(), or complex logic?
        YES → Still translatable — convert to SQL filter expression:
              [TABLE::col] = 'a' or [TABLE::col] = 'b'  → col IN ('a', 'b')
              [TABLE::col] >= N and [TABLE::col] <= M    → col BETWEEN N AND M
              Use parentheses for OR groups within AND
  NO  → Contains parameters, LOD, or untranslatable functions?
        YES → Omit — log in Unmapped Report
```

### ThoughtSpot → MV filter translation

| ThoughtSpot formula | MV `filter:` |
|---|---|
| `[TABLE::status] = 'Active'` | `status = 'Active'` |
| `[TABLE::is_deleted] = false` | `NOT is_deleted` |
| `[TABLE::status] = 'Active' and [TABLE::is_deleted] = false` | `status = 'Active' AND NOT is_deleted` |
| `[TABLE::status] = 'a' or [TABLE::status] = 'b'` | `status IN ('a', 'b')` |
| `[TABLE::amount] >= 100 and [TABLE::amount] <= 500` | `amount BETWEEN 100 AND 500` |

### Placement in YAML

```yaml
version: 1.1
source: catalog.schema.table
filter: status = 'Active' AND NOT is_deleted
dimensions:
  # ...
measures:
  # ...
```

The filter formula column is consumed by the `filter:` field — do **not** also
emit it as a dimension or measure. Remove it from the column list after converting.

**Live-verified 2026-07-09** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`,
C1) — **filter ordering is CONFIRMED cross-platform**: a ThoughtSpot model-level
`filters:` block and a Databricks MV's global `filter:` both filter rows *before* a
windowed measure (e.g. `moving_sum`) computes over them, so emitting the ThoughtSpot
filter as the MV's `filter:` field (as above) correctly preserves that ordering.
**Frame semantics DIVERGE on filtered/gapped data** (same root cause as E1 below):
Databricks' `trailing N day` spans a date *interval*, while ThoughtSpot's
`moving_sum` counts surviving *rows* — on data with gaps (including gaps created by
this filter itself), the two platforms can compute different numbers for a
trailing/leading window even though both filter before windowing. See the density
caveat in the Rolling Window Measures section below.

### Non-filter boolean formulas

Not every boolean ATTRIBUTE is a filter. If the formula is used for grouping or
display (e.g., "Is High Value" used as a dimension in searches), keep it as a
dimension and do not move it to `filter:`. Only convert when the formula's
purpose is clearly row-level filtering.

---

## LOD Formulas → Dimension Window Functions

ThoughtSpot LOD formulas (`group_aggregate`, `group_sum`, etc.) map to **dimension**
entries with window functions — NOT measures with `AGGREGATE OVER`.

| ThoughtSpot formula | MV YAML (dimension) |
|---|---|
| `group_aggregate(sum(quantity), {product_category}, query_filters())` | `expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)` |
| `group_aggregate(count(order_id), {customer_id}, query_filters())` | `expr: COUNT(ORDER_ID) OVER (PARTITION BY CUSTOMER_ID)` |
| `group_aggregate(average(price), {region, year}, query_filters())` | `expr: AVG(PRICE) OVER (PARTITION BY REGION, YEAR)` |

**Key rules:**
- LOD results go in `dimensions[]`, not `measures[]`
- Use `AGG(col) OVER (PARTITION BY dim1, dim2)` in `expr`
- Do NOT use `AGGREGATE OVER` — it causes `PARSE_SYNTAX_ERROR`
- Do NOT use `window:` for LOD — `window` requires `semiadditive`

**Filter asymmetry caveat (A1/A2, live-verified 2026-07-09 — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** On the ThoughtSpot side,
`query_filters()` makes this LOD respect user-applied filters under both a
query-level pin and a model-level `filters:` block — **CONFIRMED**, no formula
change. The emitted Databricks `AGG(col) OVER (PARTITION BY ...)` dimension
reproduces that behavior only for a Databricks consumer who applies the equivalent
filter as the MV's own global `filter:` block. It does **not** reproduce for a
consumer who instead layers an ad hoc query-time `WHERE` on the MV — Databricks'
`OVER (PARTITION BY ...)` is filter-**blind** to a query-time `WHERE` when the MV
has no global `filter:` baked in (the `WHERE` prunes output rows only, not the
window's computed value). This is a DBX-side asymmetry, not a translation defect —
document it for the consuming team rather than trying to "fix" it with a different
formula shape. The same caveat applies to the `range: all` window-measure mapping
below, which uses this identical LOD mechanism.

**A3 follow-up, live-verified 2026-07-09** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A3) — the asymmetry above **is
reproducible** from the ThoughtSpot side. `group_aggregate`'s filter argument also
accepts the documented empty-set literal `{}`: live-tested, `group_aggregate(sum(x),
{dim}, {})` is **blind to a search-level/query-time filter** (matches DBX's ad hoc
query-time `WHERE`-blind condition) but **still respects a model-level `filters:`
block** (matches DBX's own MV-global-`filter:`-aware condition) — exactly DBX's
composite. **When converting a TS Model whose LOD formula uses `{}` + a model-level
`filters:` block** (rather than `query_filters()`), emit the equivalent Databricks
shape as the MV's global `filter:` block (as above) — the `{}` + model-filter pair is
ThoughtSpot's way of expressing "this LOD should see only rows the MV's own filter
lets through, not ad hoc query-time filters," which is precisely what a DBX global
`filter:` does. Keep `query_filters()` as the default read for LOD formulas with no
model-level filter present. A candidate subtraction form,
`query_filters() - { [TABLE::col] }`, was import-accepted on the TS side but did not
exclude a filter pinned on a derived boolean formula built from that column — not a
construct expected to appear in a TS→DBX conversion, recorded for completeness.

---

## Cross-Measure References

When a measure references another measure or an LOD dimension:

| Pattern | MV `expr` syntax |
|---|---|
| Reference another measure | `MEASURE(measure_name)` |
| Reference a dimension from a measure | `ANY_VALUE(dimension_name)` |
| Ratio: measure / LOD dimension | `MEASURE(quantity) / ANY_VALUE(category_quantity)` |

Example — contribution ratio:
```yaml
dimensions:
  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)

measures:
  - name: quantity
    expr: SUM(QUANTITY)
  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
```

**Live-verified 2026-07-09 across query grain** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — **CONFIRMED**: this
`MEASURE()`/`ANY_VALUE()` inlining computes true ratio-of-sums, cross-platform, at
every grain tested (fine/coarse/total) — no sum-of-ratios or average-of-ratios
divergence found. No formula change or grain caveat is needed.

---

## Window Measures — Classification

Several ThoughtSpot patterns map to Databricks `window:` constructs:

```
Is the ThoughtSpot formula last_value() or first_value()?
  YES → True semi-additive (snapshot metric)
        order: raw date dimension, semiadditive: last/first
        range: current — Live-verified 2026-07-09, matrix C7
  NO  → Is it sum(m) or moving_sum(m, N, -N, d) at a period grain?
          YES → Period filter (flow/additive metric)
                order: truncated period dimension, semiadditive: last
                no offset (plain sum) or offset: -N <unit> (moving_sum LAG idiom)
                — Live-verified 2026-07-09, matrix C6/C6a
  NO  → Is it moving_sum/moving_average with start/end offsets?
          YES → Rolling window or rolling look-ahead — see Rolling Window
                Measures below — Live-verified 2026-07-09, matrix C1/C2/C3
```

**Corrected 2026-07-09** (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`,
C6/C6a): the pre-2026-07-09 classification routed `sum_if(diff_months/quarters/
years(...), today())` to the period-filter pattern. Live testing showed
Databricks' `range: current` + `offset` is **row-relative**, not wall-clock — a
true `sum_if(..., today())` wall-clock filter has **no exact Databricks
equivalent**; `window: [{range: current, offset: -N <unit>}]` is the closest
available construct, exact only for a single-current-period snapshot query. See
the Period-Filter Measures section below for the full caveat.

---

## True Semi-Additive Measures

ThoughtSpot `last_value`/`first_value` formulas (snapshot metrics like inventory
balances, account balances) where summing across time is not meaningful:

| ThoughtSpot formula | MV `window` |
|---|---|
| `last_value(sum(m), query_groups(), {date})` | `window: [{order: raw_date_dim, semiadditive: last, range: current}]` |
| `first_value(sum(m), query_groups(), {date})` | `window: [{order: raw_date_dim, semiadditive: first, range: current}]` |

The `order:` dimension must reference a **raw date** dimension (not a truncated
period like month or quarter).

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C7).

**Live-verified 2026-07-09 under a query-time date-range filter** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — **CONFIRMED
cross-platform**: `last_value`/`first_value` under a query-level date-range pin and
the equivalent Databricks `window:` measure both collapse to the last/first
observation *within the filtered range*, identical values at every row including
the single-surviving-row edge case. No formula change needed.

---

## Period-Filter Measures (`range: current` + truncated dimension)

**Corrected 2026-07-09 — approximation caveat (matrix C6/C6a).** Live testing
established that Databricks `window: [{range: current, offset: ...}]` is
**row-relative** (a `LAG`-style shift relative to each output row's own period),
not anchored to wall-clock `today()`. A ThoughtSpot `sum_if(diff_months/quarters/
years([date], today())=N, [m])` formula has **no exact Databricks equivalent** —
`window: [{range: current, offset: ...}]` is the closest available construct, but
it is a **lossy approximation**: exact only when the query returns a single row
for the current period, not for a multi-period trend. Flag this caveat when
converting a model that will be queried as a trend.

> **Runtime gate:** Measures with `offset` require **Runtime 18.1+**. On Runtime 17.3,
> `offset` causes `PARSE_SYNTAX_ERROR`. The base current-period measure (no `offset`)
> works on 17.3+.

| ThoughtSpot formula | MV `window` |
|---|---|
| `sum_if(diff_months([date], today()) = 0, [m])` (or `sum([m])` at the query grain) | `window: [{order: month_dim, semiadditive: last, range: current}]` |
| `sum_if(diff_months([date], today()) = -1, [m])` | `window: [{order: month_dim, semiadditive: last, range: current, offset: -1 month}]` — caveat above applies |
| `sum_if(diff_months([date], today()) = -12, [m])` | `window: [{order: month_dim, semiadditive: last, range: current, offset: -1 year}]` — caveat above applies |
| `sum_if(diff_quarters([date], today()) = 0, [m])` (or `sum([m])` at the query grain) | `window: [{order: quarter_dim, semiadditive: last, range: current}]` |
| `sum_if(diff_quarters([date], today()) = -1, [m])` | `window: [{order: quarter_dim, semiadditive: last, range: current, offset: -3 month}]` — caveat above applies |
| `sum_if(diff_years([date], today()) = 0, [m])` (or `sum([m])` at the query grain) | `window: [{order: year_dim, semiadditive: last, range: current}]` |
| `sum_if(diff_years([date], today()) = -1, [m])` | `window: [{order: year_dim, semiadditive: last, range: current, offset: -1 year}]` — caveat above applies |
| `sum_if(diff_years([date], today()) = -2, [m])` | `window: [{order: year_dim, semiadditive: last, range: current, offset: -2 year}]` — caveat above applies |

**`semiadditive` is required** when `window` is present. Valid values: `last`, `first`.

The `order:` dimension must reference a **truncated period** dimension (e.g., one
whose `expr` uses `DATE_TRUNC('MONTH', ...)`, `DATE_TRUNC('QUARTER', ...)`, etc.).

**Growth % formulas** inline `sum_if` (or the row-relative equivalent) for both
periods — no cross-formula references:
```
( sum_if(diff_months([date], today()) = 0, [m])
- sum_if(diff_months([date], today()) = -1, [m]) )
/ sum_if(diff_months([date], today()) = -1, [m]) * 100
```

**Live-verified 2026-07-09 at month grain, N=1** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C6, C6a). The quarter/year-grain
and N>1 rows above are Deferred (C8) extrapolations of the same verified mechanism,
not separately live-tested.

---

## Rolling Window Measures (`moving_sum` / `moving_average`)

**Corrected 2026-07-09 (matrix C1/C2/C3).** `moving_sum(m, N, 0, d)` always
includes the anchor row (spans N+1 rows), so it maps to `range: trailing (N+1)
day inclusive`, **not** `range: trailing N day` (Databricks' default/exclusive
form) as previously documented. `moving_sum`'s argument order is
`moving_sum(measure, start, end, sort_column)` — see
[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md#moving-functions)
for the `start`/`end` opposite-sign convention.

| ThoughtSpot formula | MV `window` |
|---|---|
| `moving_sum([m], 7, -1, [d])` (default/exclusive, 7-day trailing) | `window: [{order: date_dim, range: trailing 7 day, semiadditive: last}]` |
| `moving_sum([m], 6, 0, [d])` (anchor-inclusive, 7 rows total) | `window: [{order: date_dim, range: trailing 7 day inclusive, semiadditive: last}]` |
| `moving_sum([m], 30, -1, [d])` (default/exclusive, 30-day trailing) | `window: [{order: date_dim, range: trailing 30 day, semiadditive: last}]` |
| `moving_average([m], 7, -1, [d])` (default/exclusive) | `window: [{order: date_dim, range: trailing 7 day, semiadditive: last}]` (with `AVG` in `expr`) |
| `moving_sum([m], -1, 7, [d])` (default/exclusive, 7-day leading) | `window: [{order: date_dim, range: leading 7 day, semiadditive: last}]` |
| `moving_sum([m], 0, 6, [d])` (anchor-inclusive leading, 7 rows total) | `window: [{order: date_dim, range: leading 7 day inclusive, semiadditive: last}]` |

The `order:` dimension should be a date-granularity dimension (daily). Reverse-map
a TS `moving_sum([m], start, end, [d])` **strictly** — only the four live-verified
(start, end) shapes have a Databricks `range:` equivalent:

| (start, end) shape | Databricks `range:` |
|---|---|
| `start = N > 0`, `end = -1` | `trailing N day` (default/exclusive) |
| `start = N ≥ 0`, `end = 0` | `trailing (N+1) day inclusive` (window spans N+1 rows) |
| `start = -1`, `end = N > 0` | `leading N day` (default/exclusive) |
| `start = 0`, `end = N ≥ 0` | `leading (N+1) day inclusive` (window spans N+1 rows) |

**ANY other (start, end) pair is unmapped — route to manual review / the Unmapped
Report rather than guessing.** The Task-5 live grid explicitly tested detached
windows such as `moving_sum([m], -2, 3, [d])` and `moving_sum([m], -3, 3, [d])`
and recorded **FAIL — matches nothing** against every Databricks `range:` form
(see the candidate PASS/FAIL table under `### C1/C3 — TS-side number-match` in
`docs/audit/2026-07-08-dbx-window-claim-matrix.md`); do not classify them as
`leading`/`trailing` by sign alone.

**Live-verified 2026-07-09** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C1, C2, C3). Boundary
behavior matches on both platforms: a partial sum when 1..N-1 rows are
available, `NULL` only when zero rows are available.

**Density caveat (E1, live-verified 2026-07-09 on gapped data — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** All mappings in this
section (including the strict (start, end) reverse-map table above) were
re-verified against a fixture with date gaps and found to **diverge from
Databricks on that data**: Databricks' `trailing`/`leading N day` is a genuine
date-interval window; `moving_sum` counts rows. On dense daily data the two
framings are identical, which is why the C1/C2/C3 verification above didn't
surface this.

Row-positional: matches Databricks' date-interval trailing/leading windows only when the order column is dense at the window's unit grain (one row per unit, no gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1). Treat this mapping as an approximation requiring a density check before emitting it for any source with possible gaps.

---

## Conditional Aggregates (TS `*_if` → Databricks `FILTER (WHERE ...)`)

ThoughtSpot native `*_if` conditional aggregate functions map to Databricks
`FILTER (WHERE ...)` syntax:

| ThoughtSpot formula | MV `expr` |
|---|---|
| `sum_if ( cond , [x] )` | `SUM(x) FILTER (WHERE cond)` |
| `count_if ( cond , [x] )` | `COUNT(x) FILTER (WHERE cond)` |
| `unique_count_if ( cond , [x] )` | `COUNT(DISTINCT x) FILTER (WHERE cond)` |
| `average_if ( cond , [x] )` | `AVG(x) FILTER (WHERE cond)` |
| `min_if ( cond , [x] )` | `MIN(x) FILTER (WHERE cond)` |
| `max_if ( cond , [x] )` | `MAX(x) FILTER (WHERE cond)` |
| `stddev_if ( cond , [x] )` | `STDDEV(x) FILTER (WHERE cond)` |
| `variance_if ( cond , [x] )` | `VARIANCE(x) FILTER (WHERE cond)` |

Also detect the fallback pattern: an aggregate wrapping `if()` where the else
branch is `null` (or `0` for SUM) → extract the condition into `FILTER (WHERE ...)`.

---

## Cumulative Measures

ThoughtSpot `cumulative_sum(m, d)` maps to `window` with `range: cumulative`:

```yaml
measures:
  - name: cumulative_revenue
    expr: SUM(LINE_TOTAL)
    display_name: 'Cumulative Revenue'
    window:
      - order: order_date
        semiadditive: last
        range: cumulative
```

---

## safe_divide → COALESCE/NULLIF

ThoughtSpot `safe_divide(a, b)` maps to `COALESCE(a / NULLIF(b, 0), 0)`:

```yaml
measures:
  - name: answer_formula
    expr: COALESCE(SUM(LINE_TOTAL) / NULLIF(SUM(QUANTITY), 0), 0)
```

---

## Multi-Table Model Mapping

### Single-fact with dimension joins (primary approach)

Use v1.1 nested `joins:` to express the star schema directly. Map ThoughtSpot
`joins[]` / `referencing_join` to nested join entries:

```yaml
source: catalog.schema.fact_table
joins:
  - name: dim_alias                           # from TS join target table name
    source: catalog.schema.dim_table
    "on": source.FK_COL = dim_alias.PK_COL    # from TS join condition
    rely: { at_most_one_match: true }          # many-to-one cardinality
    joins:                                     # nested for dimension-of-dimension
      - name: sub_dim_alias
        source: catalog.schema.sub_dim
        "on": dim_alias.FK = sub_dim_alias.PK
        rely: { at_most_one_match: true }
```

**Column references** use dot-path through the join hierarchy:
- Fact table: `source.COL`
- First-level dim: `dim_alias.COL`
- Nested dim: `dim_alias.sub_dim_alias.COL`

**Mapping from ThoughtSpot joins:**

| ThoughtSpot | Databricks MV |
|---|---|
| `model_tables[0]` (primary fact) | `source:` |
| `model_tables[].joins[].with` | Nested `joins[].name` |
| `joins[].on: "[A::fk] = [B::pk]"` | `"on": source.fk = alias.pk` or nested equivalent |
| `joins[].type: INNER` | Default join type (no explicit type field in MV) |
| `joins[].cardinality: MANY_TO_ONE` | `rely: { at_most_one_match: true }` |

### Multi-fact models (split required)

Models with multiple fact tables must be split into independent MVs because each MV
has a single `source:`. Each fact table becomes its own MV with its dimension tables
joined via nested `joins:`.

**Split pattern:**
1. Identify fact tables (tables with MEASURE columns)
2. Create one MV per fact table as `source:`, with dimension tables as nested `joins:`
3. Deduplicate shared dimension columns across MVs

### Flattened SQL VIEW (fallback only)

Only use flattened views when the join structure cannot be expressed as nested joins
(e.g., many-to-many, cross-fact). The user must confirm this approach at the Step 10
checkpoint.

See the [Dunder Mifflin worked example](../../worked-examples/databricks/ts-to-databricks.md)
for a complete multi-fact split.

---

## Metric View YAML Templates

### v1.1 — Single Source

```yaml
version: 1.1
comment: >-
  Description of what this Metric View covers.
source: catalog.schema.table_or_view
dimensions:
  - name: identifier_name
    expr: PHYSICAL_COLUMN
    display_name: 'Human Label'
    comment: 'Column description.'
    synonyms: ['alias1', 'alias2']
measures:
  - name: identifier_name
    expr: AGG(PHYSICAL_COLUMN)
    display_name: 'Human Label'
    comment: 'Measure description.'
    synonyms: ['alias1']
```

### v1.1 — Star Schema with Joins (recommended for multi-table)

```yaml
version: 1.1
comment: >-
  Description.
source: catalog.schema.fact_table
joins:
  - name: dim_alias
    source: catalog.schema.dim_table
    "on": source.FK = dim_alias.PK
    rely: { at_most_one_match: true }
    joins:
      - name: sub_dim
        source: catalog.schema.sub_dim_table
        "on": dim_alias.FK2 = sub_dim.PK2
        rely: { at_most_one_match: true }
dimensions:
  - name: dim_col
    expr: dim_alias.COLUMN_NAME
    display_name: 'Human Label'
  - name: nested_dim_col
    expr: dim_alias.sub_dim.COLUMN_NAME     # dot-path through hierarchy
    display_name: 'Nested Dim Label'
measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: 'Revenue'
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }
```

### Untranslatable Formula — OMIT ENTIRELY

Do not include columns whose ThoughtSpot formula cannot be translated to
Databricks SQL. Instead:

1. Omit the column from the generated YAML
2. Log it in the Unmapped Properties Report

---

## Unmapped ThoughtSpot Properties

These ThoughtSpot properties have no Databricks MV equivalent:

| ThoughtSpot property | Status | Notes |
|---|---|---|
| `ai_context` | **Unmapped** | No equivalent — include in view-level `comment` if relevant |
| `properties.calendar_type` | **Unmapped** | No equivalent |
| `properties.index_type` | **Unmapped** | Databricks handles indexing internally |
| `properties.index_priority` | **Unmapped** | No equivalent |
| `properties.currency_type` | `format: { type: currency, currency_code: ... }` | v1.1 supports `format:` on measures |
| `properties.geo_config` | **Unmapped** | No geo support in MV |
| `column_type: UNKNOWN` | **Omit** | Cannot classify — log in report |
