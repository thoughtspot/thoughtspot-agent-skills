<!-- coverage-matrix last-reviewed: 2026-07-16 -->
# Coverage matrix — Power BI → ThoughtSpot

Every Power BI construct and its conversion status. Cite in the migration report. Within
Mapped: **Mapped** (deterministic) · **Approximated** (mapped with a caveat).

## Mapped Constructs

### DAX measures / calculated columns

| Construct | Status | Notes |
|---|---|---|
| `SUM/AVERAGE/MIN/MAX/COUNT/DISTINCTCOUNT` | Mapped | direct aggregation (`DISTINCTCOUNT` → `unique_count`) |
| Arithmetic, operators, `DIVIDE` | Mapped | `DIVIDE` → `safe_divide` |
| `IF` / nested `IF` | Mapped | → conditional expressions |
| `CALCULATE(<agg>, FILTER/cond)` | Approximated | → `sum_if`; verify vs Power BI |
| `CALCULATE(m, ALL(Table[Col]))` / `REMOVEFILTERS` / `ALLSELECTED` | Approximated | → `group_aggregate(m, query_groups()-{cols}, query_filters()-{cols})` (worked example) |
| Measure / calc-column cross-references | Mapped | `[formula_<name>]` id-refs, topo-sorted (resolve on first import — open-item #2) |
| `CEILING/FLOOR(x[, significance])` | Mapped | 1-arg → `ceil/floor`; 2-arg → `ceil(x/sig)*sig` |
| `ROUND(x, n)` | Mapped | TS 2nd arg is an increment: `round(x, 10^-n)` |
| Date subtraction / `DATEDIFF` | Approximated | → `diff_days` (day grain) |
| `SAMEPERIODLASTYEAR` / YoY / SPLY / `TOTALYTD` | Approximated | rebuilt via a Reference Date **parameter** (worked example); not a 1:1 formula |

### Data model

| Construct | Status | Notes |
|---|---|---|
| Tables / columns / data types | Mapped | Table TML bound to an existing connection; `db_column_name` on every column |
| Relationships → joins | Mapped | real cardinality from `fromCardinality`/`toCardinality`; `MANY_TO_ONE` default |
| `summarizeBy` (Sum/Average/…) | Mapped | drives MEASURE aggregation (AVG vs SUM) |
| Calc column used as a join key | Mapped | materialized as a physical column (joins are physical) |

### Visuals & report

| Power BI visual | Status | ThoughtSpot target |
|---|---|---|
| Clustered/stacked column & bar | Mapped | `COLUMN`/`STACKED_COLUMN` / `BAR`/`STACKED_BAR` (PBI naming inverted) |
| Line / area | Mapped | `LINE` / `AREA` |
| Line + clustered column combo | Approximated | `LINE_COLUMN`; needs 2 measures (flagged if 1 survives) |
| Pie / donut | Mapped | `PIE` |
| Matrix | Mapped | `PIVOT_TABLE` (role-aware `axis_configs`) |
| Card / KPI | Mapped | `KPI` |
| Table | Mapped | `GRID_TABLE` |
| Month text column on an axis | Mapped | monthly date bucket (`Month(Date)`) so it sorts chronologically |
| Pages → tabs | Mapped | one Liveboard, PBI `pageOrder` preserved |

## Unmapped Constructs (Limitations)

Flagged (needs a human; never faked) or Dropped (no ThoughtSpot equivalent).

| Construct | Status | Notes |
|---|---|---|
| Point-in-time (`CALCULATE`+`ALL`+`MAX`, headcount-as-of-date) | Flagged | genuine manual rebuild |
| Iterators (`SUMX`/`RANKX`/`EARLIER`), row-context, `VAR/RETURN`, `SWITCH` | Flagged | no safe deterministic port |
| Map / gauge / custom AppSource visual | Flagged/Approximated | needs a geo column / no map equivalent |
| Tooltip page | Dropped | hover overlay, not a navigable tab |
| Slicer / `basicShape` / buttons / text boxes | Dropped | filters / decorations, not data visuals |
| Conditional formatting / bookmarks / drill-through | Dropped | not parsed |
