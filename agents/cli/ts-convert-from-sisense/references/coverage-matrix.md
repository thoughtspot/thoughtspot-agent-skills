<!-- coverage-matrix last-reviewed: 2026-10-27 -->
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
| `round(x, n)` (2-arg) | Mapped | → `round(x, 10^-n)` for a literal `n` (`2` → `0.01`, `0` → `1`, `-2` → `100`): TS's 2nd arg is a rounding **increment**, not a decimal-place count (BL-331, live-probed 2026-10-06). A non-literal `n` or a 3rd argument → NEEDS REVIEW |
| A string literal holding a quote (`O'Brien`) | Mapped | `"O'Brien"` — ThoughtSpot's double-quoted literal; a backslash is doubled; both quote kinds → `concat` of the two forms. **Fixed ts-cli 0.165.0 (BL-365):** the literal was copied as `'O''Brien'`, which ThoughtSpot reads as two quotes — a silent wrong answer (live 2026-10-07, probe record §7). `formula_text.ts_string_literal`; a Sisense literal is read SQL-standard (`''` is one quote) |
| `a * b / c` | Mapped | → `( a * b ) / c`. **Fixed ts-cli 0.165.0 (BL-365):** ThoughtSpot reads `a * b / c` as `a * ( b / c )`, and a division of two integers is fixed-point at scale 6 in Snowflake (`[n] * 4 / 3` = 3.999999). Every product under a division is bracketed (`formula_text.ts_finalize_formula`) |
| Context placeholders (`[key]` → `{dim, agg}` / nested `formula`) | Mapped | resolved to `[Column]` or `agg([Column])`; nested calcs recurse |

### Data model

| Construct | Status | Notes |
|---|---|---|
| `datasets[].schema.tables[]` → Tables | Mapped | one Table TML per source table; `db_column_name` on every column |
| Sisense column type codes → data types | Mapped | int/bool/string/datetime/double/date/… (`_SISENSE_TYPE_CODES`) |
| `relations[]` → joins | Mapped | oid-resolved endpoints; each join runs fact (MANY) → dimension (ONE), the fact being the table with more distinct join keys (then fewer shared keys, more measures, more relations, name) — deterministic, so two facts sharing dimensions never trips I17 (BL-398); ON clause references columns by display **name** (matches the model `column_id`) |
| Composite-key relations (multi-column) | Mapped | ALL column pairs conjoined in the ON clause (`[F::a]=[D::a] AND [F::b]=[D::b]`) — no dropped pair / fan-out |
| Join cardinality | Approximated | Sisense v2 exports none → defaults `MANY_TO_ONE` and **flags the join NEEDS REVIEW** (a many-to-many bridge would fan out). An explicit `many_to_many` is **left out** and flagged NEEDS REVIEW: a Model join cannot be `MANY_TO_MANY` (14528, lint I20) |
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
| `chart/polar` / `sunburst` / `treemap` | Approximated | nearest chart (`COLUMN` / `GRID_TABLE` / `TREEMAP`), same values |
| `chart/boxplot`, any unmapped widget type, a 100% stack | Flagged | NEEDS REVIEW: what it computes (quartiles, an unknown plugin, shares) is not what the emitted chart shows |
| `indicator` | Mapped | `KPI` |
| `pivot` / `pivot2` | Mapped | `PIVOT_TABLE` (role-aware Rows/Columns) |
| `tablewidget` | Mapped | `GRID_TABLE` |
| JAQL panels → roles | Mapped | Categories/x-axis→Category, Break-by→Series(color), Values/y-axis→Values, Rows/Columns→pivot axes |
| Date `level` → date bucket | Mapped | `hours/days/weeks/months/quarters/years` → `HOURLY…YEARLY` (worked example) |
| Per-attribute top N | Mapped | baked into the widget answer as `top N` (default path); a bottom N, or an N that is not a whole number, is NEEDS REVIEW rather than turned into `top N` |
| Dashboard filter bar → Liveboard chips | Mapped | member→`oper: in`, exclude→`oper: not in`, top-level `values` (the exported-Liveboard shape, verified to filter — open-item #5) |
| Cascading dashboard filter group (`levels[]`, e.g. Client > Program > Drug) | Mapped | one chip per level, each keeping its own preset. Until this release the group carried no `jaql` of its own and was dropped without a warning |
| Numeric-range dashboard filter → chip preset | Mapped | single-sided from/to→`GE`/`LE`, fromNotEqual/toNotEqual→`GT`/`LT`; two-sided keeps BOTH bounds→`BW_INC`/`BW` (incl. mixed inclusive/exclusive — never collapses to one bound); equals→`EQ` (worked example) |
| Dashboard → tabbed Liveboard | Mapped | one Liveboard; widgets become Answers |

### Binding to an existing Model (`build-liveboard --target-model`)

Verified tile-for-tile on a live cluster (open-item #6).

| Sisense construct | Status | ThoughtSpot target |
|---|---|---|
| `[Table.column]` on a role-playing copy | Mapped | the Model instance named like the table, else the one joined on the FK column the Sisense relation uses; ambiguous, unreachable from the widget's facts, or a name match the relation's join key disagrees with → NEEDS REVIEW |
| `[Table.column]` where the Table renamed the warehouse column | Mapped | through the Table TML's `db_column_name` when the export carries the Tables (`ts tml export --associated`), else a unique case/underscore-insensitive match; none → NEEDS REVIEW |
| `count` on a key the Model hides | Mapped | the Model formula `unique count ( [inst::col] )`; none → NEEDS REVIEW naming the measure to add |
| `count` / `countduplicates` / `sum` / `avg` / `min` / `max` on a column | Mapped | `unique count` / `count` / `sum` / `average` / `min` / `max` keyword with ThoughtSpot's output name |
| Widget-level member / exclude / range filter | Mapped | `[X] = 'a' [X] = 'b'` (OR) / `[X] != 'a'` (AND) / `>= > <= <` in the search; `'` escaped as `\'` (verified live with a member containing an apostrophe) |
| Widget filter or chip on a date value | Flagged | NEEDS REVIEW: no search form for a date value is verified — live, `[D] = '2026-02-01'` and `'2026-02-01T00:00:00'` are rejected ("Date value token doesn't have a valid date filter") and bare dates are invalid tokens. A coarser level (period starts) says so too |
| Relative-date widget filter, or any filter / JAQL / panel-item setting the parser does not read | Flagged | NEEDS REVIEW naming the settings (the parser lists every key it does not read, so a new Sisense setting is flagged, never ignored) |
| Filter on a key the Model hides, table the Model lacks | Flagged | NEEDS REVIEW → `filter_map` / `field_map` in overrides.json |
| `field_map` / `filter_map` naming a column the Model lacks | Flagged | NEEDS REVIEW (not an import failure) |
| Two aggregations, or two date levels, of one column in one widget | Flagged | NEEDS REVIEW: one answer carries one use per column, so the second is reported, not dropped |
| `WidgetsTabber` (time-grain tabs) | Mapped | the active tab's widget only; a hidden tab plotting the same fields at another date level is `Merged` (grain is the chart's date-bucket control) |
| `WidgetsTabber` whose tabs are different charts | Mapped | every tab is a tile of its own, noted in the report |
| Value / axis title | Mapped | `custom_name` |
| `richtexteditor`, tab-set title | Mapped | section-header note tile |
| Columnar layout | Mapped | tile grid, rows filling 12 columns |
| Jump-to-dashboard drill | Approximated | details table from the drill dashboard's first widget with fields (`--drill`), keeping that widget's own filters plus the source widgets' shared filters; narrowed by right-click → Filter, not a pop-up. Further widgets, or none with fields → NEEDS REVIEW |
| Dashboard filter on a column a tile also filters | Mapped | `excluded_visualizations` on the chip: in Sisense a widget filter takes priority over a dashboard filter on the same dimension, and a ThoughtSpot chip would replace the tile's own filter |
| Dashboard filter on a dimension with several role copies | Mapped | copy reaching the most tiles, then the shortest join path; still tied → flagged |
| Chip whose copy differs from a tile's own Sisense path to the table | Flagged | NEEDS REVIEW naming each tile and the copy it reaches (Sisense resolves per widget, a chip binds one copy for the board) |
| Chip that cannot reach a tile's facts | Flagged | NEEDS REVIEW naming the tiles |
| Dashboard range filter | Flagged | chip `generic_filter` (same operators as the default path), NEEDS REVIEW on the chip and its tiles until a range chip is verified on a live Liveboard (open-item #5) |
| Dashboard relative-date or unrecognised filter | Flagged | NEEDS REVIEW on the chip and on every tile it applies to: the chip is emitted without a condition, so it is unfiltered until set by hand |
| Dashboard mixed inclusive/exclusive range | Flagged | `BW_INC` chip (both bounds kept), NEEDS REVIEW on the chip and its tiles because the exclusive end is included |
| Disabled widget / dashboard filter (`disabled: true`) | Mapped | not applied, as in Sisense; reported (a dashboard filter as `Skipped`) |
| Widget ignoring a dashboard filter (`metadata.ignore`: all, dimension, instance id) | Mapped | the tile is in that chip's `excluded_visualizations`; reported |
| Widget in Highlight mode (`dashboardFiltersMode: select`) with a chip on a column it plots | Flagged | NEEDS REVIEW: Sisense highlights rather than filters, which a chip cannot do. A chip on a column the widget does not plot filters it, as in Sisense |
| Chip on a tile whose facts or path to the table cannot be determined | Flagged | NEEDS REVIEW on the chip and the tile |
| Dashboard-level top / bottom N | Flagged | no chip form; NEEDS REVIEW on every tile |
| Top / bottom N on a widget | Mapped | `top N` / `bottom N` when it ranks the widget's ONLY dimension, at its plotted date level, by its ONLY measure (ThoughtSpot ranks the answer's rows; both live-verified); any other ranking, a non-numeric or non-positive N is NEEDS REVIEW. The ranked column is the widget's own, so a chip on it excludes the tile |
| Quick function (e.g. Contribution), disabled plotted field, secondary value | Flagged | NEEDS REVIEW; the field is not carried |
| Percent display (`format.mask.percent`) on a Model column with no format | Flagged | NEEDS REVIEW (the value would show as a plain number) |
| Weekly, quarterly or yearly bucket; any bucket on a column with a custom `calendar` | Flagged | NEEDS REVIEW, on the tile and on a merged grain: ThoughtSpot follows the cluster's week start and fiscal-year start, or the column's calendar |
| Measure bound to a Model formula whose aggregation differs (`avg` of a `sum ( ... )` formula) | Flagged | NEEDS REVIEW unless mapped by `field_map` |
| Sisense calculated column (`tupleTransformations` add-column) | Flagged until mapped | a Model formula of the same name and role (attribute for a dimension, measure for a measure) on the same instance is reported "bound by name only", NEEDS REVIEW until confirmed with `field_map`; never a plain column of that name |
| Search value containing a backslash | Flagged | NEEDS REVIEW (quoting not verified for it; `'` is) |
| Role-played table (one Sisense table, several Model copies) | Mapped when decided | the copy a widget table joins on a column a Sisense relation uses; for a widget naming no fact, the copy every Sisense-related fact linking its tables joins. Two such copies, a copy Sisense would not use, or no decidable path → NEEDS REVIEW (the binding and every chip check) |
| Model join declared `ONE_TO_MANY` on the dimension side | Mapped | read as many → one, so the fact stays the root its relations are resolved from |
| Column renamed in the Table TML (`--associated` export) | Mapped | only the Table's `db_column_name` mapping decides; no name fallback that could bind another warehouse column |
| Two widget filters on one column | Flagged | NEEDS REVIEW: Sisense applies all of them, one search would OR repeated `=` |
| Two dashboard filters on one column | Flagged | NEEDS REVIEW on both chips' tiles: how two chips on one column combine is not verified |
| Drill dashboard's own dashboard filters | Flagged | NEEDS REVIEW, not applied: how a jump-to-dashboard combines them with what the source passes is not verified |
| Source widget filter not carried to its drill, or not shared by every source | Flagged | NEEDS REVIEW on the details table, naming the filters |
| Hidden tab differing in any setting (quick function, ignore, Highlight, disabled, unread settings, filters) | Mapped | a tile of its own, never `Merged`; a grain of a tab that produced no tile is NEEDS REVIEW |
| Date level with no ThoughtSpot bucket (`minutes`, `dayofweek`, …) | Flagged | NEEDS REVIEW: the grain is not carried |
| Null member, or a range with both `equals` and a bound | Flagged | NEEDS REVIEW |
| Widget or dashboard filter the parser cannot read | Flagged | NEEDS REVIEW on the widget (partly parsed) or on every tile (dashboard filter), never dropped with only a warning |
| Sisense relation from a widget fact that the Model does not join | Flagged | NEEDS REVIEW: the Model would reach the table another way |
| Widget whose columns span facts no single fact reaches | Flagged | NEEDS REVIEW (a multi-fact query is not verified to return Sisense's numbers) |
| Count formula on a role-played table | Mapped | `unique count ( [inst::col] )` on that exact copy (through the Table TML mapping); the base name stands in only when the table has one copy |
| Hidden grain merged into a tile that is NEEDS REVIEW | Flagged | the merged row is NEEDS REVIEW too |
| Widget filter replaced by `filter_map` | Mapped | the widget still owns its Sisense column (a chip on it excludes the tile), and the fragment counts toward "two filters on one column" |
| Filter on an aggregate (`agg` on a filter item) | Flagged | NEEDS REVIEW: measure-filter semantics are not verified |
| Dashboard filter carrying an unread JAQL key | Flagged | NEEDS REVIEW, as on a widget item |
| `dashboardFiltersMode` other than `filter` / `select` | Flagged | NEEDS REVIEW on each tile a chip applies to |
| Jump-to-dashboard filter settings off their defaults (`includeFilterDims`, `excludeFilterDims`, `includeDashFilterDims`, `excludeDashFilterDims`, `resetDashFiltersAfterJTD`, `mergeTargetDashboardFilters`) | Flagged | NEEDS REVIEW on the details table |
| 100% stacked chart (`…100` subtype) | Flagged | NEEDS REVIEW on both paths: Sisense shows shares of each total, carried as absolute values |
| Boolean or decimal member value | Flagged | NEEDS REVIEW: its written form is not verified |
| Model join with `MANY_TO_MANY` cardinality | Flagged | not followed; a widget that needs it reports its table unreachable |
| Sisense dimension bound to a Model MEASURE column | Flagged | NEEDS REVIEW: Sisense groups by it, ThoughtSpot would aggregate it |
| Widget naming no fact table, alone or under a chip | Mapped when decided | carried when the tables Sisense relates directly are joined directly between the bound copies in the Model, or one fact Sisense relates to all of them is the path; otherwise NEEDS REVIEW |
| Sisense relation that is not one column to one column (3+ endpoints, composite) | Flagged | NEEDS REVIEW on any field or filter on its tables |
| Filters a drill source passes | Mapped | the filters every source shares, bound in the DRILL widget's own context (its facts and copies); a ranking or a non-shared filter is NEEDS REVIEW |
| Ranked tab, or a hidden tab with its own drill | Mapped | a tile of its own, never `Merged` (a ranking re-ranks at whatever bucket the chart shows) |
| Model Table TMLs not supplied | Flagged | every tile NEEDS REVIEW, plus one board-level row: warehouse columns were matched by Table column name, not `db_column_name` |
| `field_map` / `filter_map` entries | Mapped | they choose the column (or the search fragment); every path check still runs on what they choose: role copy, a widget naming no fact, a chip's copy per tile, relations not one column to one column |
| Formula built from other formulas | Mapped | read as reading every instance its referenced formulas read (to a fixed point), so the multi-fact and chip checks see it |
| Widget naming no fact, linked in Sisense by two facts | Flagged | NEEDS REVIEW: a tie in Sisense's own path choice (linking facts are counted from Sisense's relations, not the Model's facts) |
| Row-level filter or chip on a Model MEASURE column | Flagged | NEEDS REVIEW: ThoughtSpot filters a measure after aggregating, Sisense filters rows |
| Sum / average / count of a non-fact table's column in a widget joining other tables | Flagged | NEEDS REVIEW: whether both repeat its rows the same way across the join is not verified |
| Chip and widget filter on different Sisense dims bound to one Model column | Flagged | NEEDS REVIEW: Sisense applies both, a chip would replace the widget's |
| Widget reading another data source than the dashboard | Flagged | NEEDS REVIEW |
| Parse warnings (a skipped relation, an unreadable widget) | Flagged | each one a NEEDS REVIEW row in the report, not only stderr |
| Join path from a widget's fact to each table it reads (fields, filters, chips) | Mapped when equal | carried only when the Model's many → one path is the same as Sisense's shortest relation path, hop for hop on the same columns; a different path (a shortcut, another foreign key), a tie among Sisense's shortest paths, or no unique Model path is NEEDS REVIEW |
| Chip adding a join to a measure on a non-fact table | Flagged | NEEDS REVIEW, as for the same filter on the widget |
| Dashboard `filterRelations` / `filterToDatasourceMapping` set | Flagged | NEEDS REVIEW on every tile: the filters are not combined by AND |
| Sisense column renamed from its source column | Flagged | NEEDS REVIEW until mapped: which one the Model column reads is not verified |
| Date field with no level | Flagged | NEEDS REVIEW: the grain ThoughtSpot shows it at is not decided |
| Measure number format (Sisense shows full values) | Mapped | every measure column gets a NUMBER format with unit NONE, thousands separators, 2 decimals with trailing zeroes removed — ThoughtSpot's default abbreviates (`32.16K`); `%` columns and Model columns with their own `format_pattern` / `currency_type` keep theirs. Verified live: imports and exports unchanged, and a count renders as `22,652` (no abbreviation, no `.00`) |

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
| `round(x, n)` 2-arg, non-literal `n` | Flagged | NEEDS REVIEW — a field-driven digit count has no ThoughtSpot increment form (BL-331). Until 2026-10-06 every 2-arg `round` was emitted verbatim as Approximated, which imported cleanly and returned nearest-`n` (`round(x, 0)` = NULL) |
| Two-sided range with mixed inclusive/exclusive bounds | Partial | both bounds retained via `BW_INC`/`BW`; exact boundary inclusivity is approximate (verify live — open-item #5) |
| Measure-range dashboard filter (filter on a formula/measure not exposed as a column) | Dropped | dropped when the column is not on the model |
| Cyclic date parts (day-of-week, month-of-year as a `level`) | Dropped | no clean date-bucket equivalent |
| `richtexteditor` / text widget | Dropped | not a data visual — no Answer emitted (the `--target-model` path emits a note tile) |
| Live Sisense REST fetch | Not implemented | offline bundle only (open-item #3) |
| Locked dashboard filter (`locked: true`) | Dropped | becomes an ordinary editable chip; ThoughtSpot has no locked-chip equivalent in TML that this converter emits |
