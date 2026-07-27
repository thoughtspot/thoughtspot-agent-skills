<!-- coverage-matrix last-reviewed: 2026-07-18 -->
# Coverage matrix — Sisense → ThoughtSpot

Every Sisense construct and its conversion status. Cite in the migration report. Within
Mapped: **Mapped** (deterministic) · **Approximated** (mapped with a caveat). Source of
truth for the formula rows is `tools/ts-cli/ts_cli/sisense/functions.py`
(`AGG_MAP` / `FUNCTION_MAP` / `UNSUPPORTED`).

## Mapped Constructs

### JAQL aggregations (simple measures, no formula)

| Construct | Status | Notes |
|---|---|---|
| `sum` / `avg` / `min` / `max` | Mapped | → `SUM` / `AVERAGE` / `MIN` / `MAX` aggregation |
| `count` (Sisense = **unique/distinct**) | Mapped | → `COUNT_DISTINCT` — Sisense `count` counts distinct values, not rows |
| `countduplicates` / `dupCount` (Sisense = **total**) | Mapped | → `COUNT` — exact total incl. duplicates (NOT approximate) |
| `stdev` / `var` | Mapped | → `STD_DEVIATION` / `VARIANCE` |

### JAQL formula functions (calculated columns / measures)

| Construct | Status | Notes |
|---|---|---|
| `sum` / `avg`(`average`) / `min` / `max` | Mapped | direct aggregation functions |
| `count` / `dupCount` | Mapped | `count`→`unique count` (distinct); `dupCount`→`count` (total) |
| `abs` / `round` / `ceiling` / `floor` / `power` / `sqrt` / `exp` / `mod` / `sign` | Mapped | `ceiling`→`ceil`, `power`→`pow` |
| `log` / `ln` / `log10` | Mapped | Sisense `Log` is the **natural** log → `ln`; `log10`→`log10` |
| `ddiff(d1, d2)` | Mapped | → `diff_days(d1, d2)` (day grain) |
| `stdev` / `var` / `median` | Mapped | → `stddev` / `variance` / `median` (sample variants) |
| `if(cond, a, b)` | Mapped | → ThoughtSpot `if (cond) then a else b` (nested for chained `if`) |
| `isnull` / `ifnull` | Mapped | `isnull` (not `is_null`) |
| `round(x, n)` (2-arg) | Approximated | TS 2nd arg is a rounding **increment**, not a decimal-place count |
| Context placeholders (`[key]` → `{dim, agg}` / nested `formula`) | Mapped | resolved to `[Column]` or `agg([Column])`; nested calcs recurse |

### Data model

| Construct | Status | Notes |
|---|---|---|
| `datasets[].schema.tables[]` → Tables | Mapped | one Table TML per source table; `db_column_name` on every column |
| Sisense column type codes → data types | Mapped | int/bool/string/datetime/double/date/… (`_SISENSE_TYPE_CODES`) |
| `relations[]` → joins | Mapped | oid-resolved endpoints; most-connected table = fact; ON clause references columns by display **name** (matches the model `column_id`) |
| Composite-key relations (multi-column) | Mapped | ALL column pairs conjoined in the ON clause (`[F::a]=[D::a] AND [F::b]=[D::b]`) — no dropped pair / fan-out |
| Join cardinality | Approximated | Sisense v2 exports none → defaults `MANY_TO_ONE` and **flags the join NEEDS REVIEW** (a many-to-many bridge would fan out) |
| Custom-SQL table (`type: custom`) | Mapped | `sql_expression` carried onto the table |
| Duplicate column names | Mapped | deduped to the fact table |
| Calc column colliding with a physical column name | Mapped | formula renamed `<name> (Calc)` so the base column + its reference survive; flagged |
| Numeric column classification | Approximated | `Year`/`Age`/low-card codes kept as ATTRIBUTE; an ambiguous numeric stays a SUM measure but is **flagged NEEDS REVIEW** |

### Widgets & dashboard

| Sisense widget | Status | ThoughtSpot target |
|---|---|---|
| `chart/column` / `chart/bar` | Mapped | `COLUMN` / `BAR` (`STACKED_*` on a stacked subtype) |
| `chart/line` / `chart/area` / `chart/pie` | Mapped | `LINE` / `AREA` / `PIE` |
| `chart/scatter` | Mapped | `SCATTER` |
| `chart/bubble` | Approximated | `SCATTER` (bubble size dropped) |
| `chart/polar` / `sunburst` / `treemap` / `chart/boxplot` | Approximated | nearest chart (`COLUMN` / `GRID_TABLE` / `TREEMAP`) |
| `indicator` | Mapped | `KPI` |
| `pivot` / `pivot2` | Mapped | `PIVOT_TABLE` (role-aware Rows/Columns) |
| `tablewidget` | Mapped | `GRID_TABLE` |
| JAQL panels → roles | Mapped | Categories/x-axis→Category, Break-by→Series(color), Values/y-axis→Values, Rows/Columns→pivot axes |
| Date `level` → date bucket | Mapped | `hours/days/weeks/months/quarters/years` → `HOURLY…YEARLY` (worked example) |
| Per-attribute top/bottom N | Mapped | baked into the widget answer as `top N` |
| Dashboard filter bar → Liveboard chips | Mapped | member→`IN`, exclude→`NOT_IN` |
| Numeric-range dashboard filter → chip preset | Mapped | single-sided from/to→`GE`/`LE`, fromNotEqual/toNotEqual→`GT`/`LT`; two-sided keeps BOTH bounds→`BW_INC`/`BW` (incl. mixed inclusive/exclusive — never collapses to one bound); equals→`EQ` (worked example) |
| Dashboard → tabbed Liveboard | Mapped | one Liveboard; widgets become Answers |

## Unmapped Constructs (Limitations)

Flagged (needs a human; never faked) or Dropped (no ThoughtSpot equivalent). Formula rows are
the `UNSUPPORTED` set in `functions.py` — presence makes the whole formula NEEDS REVIEW with
the original Sisense expression preserved.

| Construct | Status | Notes |
|---|---|---|
| Window / ranking (`rank`, `ordering`, `rsum`, `rpsum`, `rpavg`, `prev`, `next`, `all`, `now`) | Flagged | no safe deterministic port |
| Time-intelligence period-to-date (`ytdsum`, `ytdavg`, `mtdsum`, `qtdsum`, `wtdsum`, …) | Flagged | rebuild manually (reference-date / cumulative pattern) |
| Time-intelligence prior-period (`pastday`, `pastweek`, `pastmonth`, `pastquarter`, `pastyear`) | Flagged | genuine manual rebuild |
| Growth / diff (`growth`, `growthrate`, `diffpastyear`, `ydiff`, `qdiff`, `mdiff`, …) | Flagged | `ddiff` is the one exception → `diff_days` |
| Population / advanced statistics (`stdevp`, `varp`, `mode`, `largest`, `smallest`, `percentile`, `quartile`, `correl`, `covar`, `slope`) | Flagged | no confident TML 1:1 (sample `stdev`/`var`/`median` DO map) |
| R integration (`rdouble`, `rint`) | Flagged | no equivalent |
| Unknown function / unresolvable `[key]` placeholder | Flagged | NEEDS REVIEW, original expression kept |
| `case(...)` | Flagged | multi-branch conditional has no safe 1:1 — NEEDS REVIEW, rebuild as nested `if` manually (never emitted as invalid syntax) |
| `if(...)` with ≠ 3 args | Flagged | ThoughtSpot `if/then/else` needs exactly `(cond, then, else)` |
| `round(x, n)` 2-arg | Partial | increment-vs-decimal-place semantics diverge |
| Two-sided range with mixed inclusive/exclusive bounds | Partial | both bounds retained via `BW_INC`/`BW`; exact boundary inclusivity is approximate (verify live — open-item #5) |
| Measure-range dashboard filter (filter on a formula/measure not exposed as a column) | Dropped | dropped when the column is not on the model |
| Cyclic date parts (day-of-week, month-of-year as a `level`) | Dropped | no clean date-bucket equivalent |
| `richtexteditor` / text widget | Dropped | not a data visual — no Answer emitted |
| Live Sisense REST fetch | Not implemented | offline bundle only (open-item #3) |
