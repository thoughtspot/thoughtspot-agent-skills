<!-- currency: tableau — 2026-07 (matrix refresh) -->

# Coverage Matrix: Tableau Workbook → ThoughtSpot Model + Liveboard

What the `ts-convert-from-tableau` skill maps and what it does not.
Use this as the canonical limitations reference.

---

## Mapped Constructs

### Structure and Schema

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | Physical tables (`<relation type="table">`) | Table TML | |
| 2 | Custom SQL relations (`<relation type="text">`) | SQL View TML | Full SQL preserved in `sql_query` |
| 3 | Joins (`<relation type="join">` — inner/left/right/full) | Model `joins[]` | `full`→`OUTER`, `left`→`LEFT_OUTER`, etc. |
| 4 | Data blending (`<datasource-relationships>`) | Merged single model with `LEFT_OUTER` joins | Same connection only — blended tables must exist in the same database connection |
| 5 | Cross-datasource formula references (blend) | Resolved within merged model | Federated ID/caption prefix stripped, re-prefixed with `TABLE::` |
| 6 | Column data types (string, integer, real, boolean, date, datetime) | VARCHAR, INT64, DOUBLE, BOOL, DATE, DATETIME | |
| 7 | `db_column_name` from `remote-name` metadata | Physical column name in table TML | |
| 8 | Connection binding by name | `connection.name` on every table/sql_view TML | Never GUID (invariant I6) |
| 9 | Published datasource (`sqlproxy` connection) | Resolved to `dbname` from connection | |
| 10 | Extract datasources | Resolved to underlying live source | Skipped if no source resolves |
| 11 | `.twbx` archive extraction | Unzip to access inner `.twb` | |
| 12 | Topological sort of calculated fields | Formulas emitted in dependency order | Level 0 first; `ts tableau translate-formulas` resolves cross-references via DAG + inlining |

### Formula Translation — Scalar Functions

| # | Tableau Function(s) | ThoughtSpot Function | Notes |
|---|---|---|---|
| 13 | `IF/THEN/ELSE/ELSEIF/END` | `if ( cond ) then a else b` / `else if` | |
| 14 | `CASE/WHEN` | `if/else if` chain | No native CASE in TS |
| 15 | `IIF(test, a, b)` | `if ( test ) then a else b` | |
| 16 | `IFNULL(a, b)`, `ZN(a)` | `ifnull ( a , b )` | |
| 17 | `ISNULL(a)` | `isnull ( a )` | |
| 18 | `CONTAINS`, `TRIM`, `REPLACE`, `FIND` | `contains`, `trim`, `replace`, `strpos` | |
| 19 | `LEFT/MID/RIGHT/LEN` | `substr()` / `strlen()` | CLI-translated (v0.26.0); index adjustment (Tableau is 1-based) |
| 20 | `UPPER/LOWER` | `sql_string_op("UPPER/LOWER({0})")` | CLI-translated (v0.26.0) |
| 21 | `STARTSWITH/ENDSWITH` | `strpos(s,sub) = 1` / `substr` idiom | CLI-translated (v0.26.0) |
| 24 | `DATEDIFF` (all units) | `diff_days`/`diff_months`/`diff_years`/`diff_time` | Args reversed vs Tableau. `day/month/year/hour/minute/week` supported; any other unit (e.g. `quarter`) rejected with reason at translate time (v0.26.0) |
| 25 | `DATETRUNC` | `start_of_month/quarter/week/year`; `day` → `date()` | `hour`/`minute`/`second` (and any other unit not in the map) rejected with reason at translate time (v0.26.0) |
| 26 | `DATEADD` | `add_days/add_months/add_years` | Only `day/month/year` supported; other units (e.g. `week`) rejected with reason at translate time (v0.26.0) |
| 27 | `DATEPART` (all units) | Per-unit functions | `month`→`month_number`, `year`→`year`, `day`→`day`, `quarter`→`quarter_number`, `week`→`week_number_of_year`, `dayofyear`→`day_number_of_year`, `weekday`→`day_of_week`, `hour`→`hour_of_day`. Units outside this map rejected with reason at translate time (v0.26.0) |
| 28 | `DATENAME('month', d)` | `month ( [date] )` | Returns name, not number. Only `month` supported — other units rejected with reason at translate time (v0.26.0) |
| 29 | `DATEPARSE(format, s)` | `to_date ( s , format )` | CLI-translated (v0.26.0); args flipped vs Tableau |
| 30 | `TODAY`/`NOW`/`DATE`/`YEAR`/`MONTH`/`DAY` | `today`/`now`/`date`/`year`/`month_number`/`day` | |
| 31 | `ABS`/`ROUND`/`CEILING`/`FLOOR`/`SQRT`/`POWER`/`LOG`/`LN`/`EXP` | `abs`/`round`/`ceil`/`floor`/`sqrt`/`pow`/`log10`/`ln`/`exp` | |
| 32 | `SIN/COS/TAN` | Radians-to-degrees conversion applied | CLI-translated (v0.26.0). Inverse trig (`ACOS`/`ASIN`/`ATAN`) and `COT` are NOT implemented as of v0.26.0 — all four pass through untranslated and are not caught by the fail-loud validator (a silent gap distinct from the `_UNMAPPED_FUNCTIONS` reject-at-translate-time list below). `ACOS`/`ASIN`/`ATAN` are translatable in principle: ThoughtSpot's inverse trig functions return degrees where Tableau's return radians, so a `* pi/180` composite applies — the same conversion family as the shipped SIN/COS/TAN handling. `COT` has no direct ThoughtSpot function and would need a `1/tan(...)` composite. Tracked in BL-072 |
| 33 | `PI()/RADIANS()/DEGREES()` | Literal composites | CLI-translated (v0.26.0); no native equivalent |
| 34 | `INT(x)` | `if ( x >= 0 ) then floor ( x ) else ceil ( x )` | Partial; truncate-toward-zero |
| 35 | `FLOAT(x)/STR(x)` | `to_double(x)/to_string(x)` | |
| 36 | `DATETIME(expr)` cast | `sql_date_time_op ( "TO_TIMESTAMP({0})" , [col] )` | Pass-through |
| 37 | String concat (`+` on strings) | `concat ( a , b )` | TS `+` is numeric-only |
| 38 | `SIGN(x)/SQUARE(x)` | `if/then` composite / `pow(x,2)` | CLI-translated (v0.26.0) |
| 39 | `MIN/MAX` (scalar, 2-arg) | `least ( a , b )` / `greatest ( a , b )` | CLI-translated (since v0.17.0; scan-abort bug fixed v0.26.0); 2-arg form only — 1-arg is the aggregate `min()`/`max()` |
| 40 | Division by zero | `safe_divide()` or `if ( b = 0 ) then null else a/b` | |
| 108 | `ISMEMBEROF("group")` | `ts_groups = 'group'` | Multi-value list membership handled natively with `=`. Documented skill-level mapping only — the CLI does NOT translate it as of v0.26.0: `ISMEMBEROF(...)` passes through untranslated and is not caught by the fail-loud validator (not in `_UNMAPPED_FUNCTIONS`), the same silent-gap class as the inverse trig note on #32. CLI implementation tracked in BL-071 |

### Formula Translation — Aggregates

| # | Tableau Function(s) | ThoughtSpot Function | Notes |
|---|---|---|---|
| 43 | `SUM/COUNT/AVG/MIN/MAX` (aggregate) | `aggregation:` on MEASURE columns | |
| 44 | `COUNTD(x)` | `unique count ( x )` formula | Never COUNT_DISTINCT aggregation (invariant I5) |
| 45 | `STDEV/MEDIAN` | `stddev/median` | |
| 46 | `ATTR(x)` | Reference `x` directly | |
| 47 | Conditional aggregates (`SUM/COUNT/AVG(IF c THEN x END)`) | `sum_if/count_if/average_if/unique_count_if` | |
| 48 | `Number of Records` / row count (`= 1`) | `count([column])` | User-prompted column selection |
| 49 | Redundant pass-through formulas (`SUM([col])` / `[col]`) | Detected and dropped | Use physical column directly |

### Formula Translation — LOD Expressions

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 50 | `{FIXED [dim] : AGG([col])}` | `group_aggregate ( agg ( [t::col] ) , { dim } , {} )` | |
| 51 | `{INCLUDE [dim] : AGG([col])}` | `group_aggregate ( ... , query_groups() + { dim } , query_filters() )` | |
| 52 | `{EXCLUDE [dim] : AGG([col])}` | `group_aggregate ( ... , query_groups() - { dim } , query_filters() )` | |
| 53 | `TOTAL(SUM([col]))` / percent-of-total | `group_aggregate ( ... , {} , query_filters() )` | |
| 54 | `max([date])` in formula filters | `group_aggregate ( max ( [date] ) , {} , {} )` | Global max date, dynamic |
| 110 | `{FIXED [d], [boolFlag] : AGG}` where `[boolFlag]` is pinned `=true` on the Filters shelf | `group_aggregate ( agg ( [t::col] ) , { [d] } , { [boolFlag] = true } )` | Boolean predicate inside FIXED is a **filter, not a grain** — move to the filter arg; hard `{...}`, not `query_filters()`. Check the filter shelf before treating a FIXED dim as a grouping key. See formula-translation LOD section. |
| 111 | Weighted average — **pre-weighted source column** (e.g. `WEIGHTED_USAGE`) | `sum ( [t::col] )` / `group_aggregate ( sum ( [t::col] ) , { grain } , … )` | Weight already applied upstream — just sum. Do NOT apply a weighted-average formula on top (double-counts). Read the expression, not the field name. |
| 112 | Weighted average — **computed** `SUM([v]*[w]) / SUM([w])` | `sum ( group_aggregate ( sum ( [v] ) * sum ( [w] ) , { grain } , query_filters () ) ) / sum ( [w] )` | Grain choice + outer-sum re-aggregation are the hard parts. See `thoughtspot-formula-patterns.md` → "Weighted average". |

### Formula Translation — Running / Cumulative

| # | Tableau Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 55 | `RUNNING_SUM/AVG/MAX/MIN` | `cumulative_sum/average/max/min ( [t::col] , [sort_attr] )` | |
| 56 | `RUNNING_COUNT` | `cumulative_sum ( 1 , [sort_attr] )` | Answer-level only; approximate; Not verified as of 2026-07-03 |

### Formula Translation — Moving / Window

| # | Tableau Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 57 | `WINDOW_SUM/AVG/MAX/MIN` | `moving_sum/average/max/min ( [t::col] , start , end , [sort_attr] )` | |
| 58 | `WINDOW_STDEV/WINDOW_COUNT` (sliding window) | `sql_*_aggregate_op("STDDEV_POP/COUNT(...) OVER (...)")` | Pass-through — no native `moving_stdev`/`moving_count` (`moving_*` is sum/average/max/min only, per `tableau-formula-translation.md`). If used as a plain aggregate over the whole partition (not a sliding window), use `stddev()`/`count()` instead |
| 59 | `WINDOW_PERCENTILE/WINDOW_MEDIAN` (sliding window) | `sql_*_aggregate_op("PERCENTILE_CONT/MEDIAN(...) OVER (...)")` | Pass-through |

### Formula Translation — Rank

| # | Tableau Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 60 | `RANK(SUM([col]))` | `rank ( sum ( [t::col] ) , 'desc' )` | Direction arg required |
| 61 | `RANK_UNIQUE` | `rank()` | Ties possible; use #109 for guaranteed uniqueness |
| 62 | Partitioned `RANK` | `group_aggregate ( sql_int_aggregate_op("rank() over (...)") , query_groups() + {dim} , query_filters() )` | Always wrapped in group_aggregate |
| 63 | `RANK_DENSE` / `RANK_MODIFIED` | `sql_int_aggregate_op("dense_rank() over (...)")` | Pass-through |
| 109 | `RANK_UNIQUE` (unique ranks, no ties) | `sql_int_aggregate_op("ROW_NUMBER() OVER (ORDER BY ...)")` | Pass-through |

### Formula Translation — Row-Offset Table Calculations

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 64 | `INDEX() <= N` (Top-N filter intent) | `rank ( [m] , 'desc' )` + query set | |
| 65 | `INDEX()` (display row numbering, sort recoverable) | `rank ( sum ( [m] ) , 'asc' )` | |
| 66 | `LOOKUP(agg, N)` where N < 0 (LAG) | `moving_sum ( [m] , abs(N) , -abs(N) , [sort] )` | |
| 67 | `LOOKUP(agg, N)` where N > 0 (LEAD) | `moving_sum ( [m] , -N , N , [sort] )` | |
| 68 | `LOOKUP(agg, FIRST())` — "get value at first row" | `first_value ( sum ( [m] ) , query_groups() , { [sort] } )` | |
| 69 | `LOOKUP(agg, LAST())` — "get value at last row" | `last_value ( sum ( [m] ) , query_groups() , { [sort] } )` | |
| 70 | `SIZE()` (unpartitioned) | `sql_int_aggregate_op ( "COUNT(*) OVER ()" )` | Pass-through |
| 71 | String-aggregation CSV technique | `sql_string_aggregate_op("LISTAGG(...)")` | |
| 72 | `<table-calc>` addressing extraction (Step 3f) | Sort/partition context recovery from TWB XML | `ordering-type`, `ordering-field`, `<order>` |

### Sets

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 73 | Static sets (`<group>` with union/member) | `GROUP_BASED` column set (`cohort_type: SIMPLE`) | |
| 74 | Static sets with `%null%` member | `{Null}` grouping value in column set | |
| 75 | `except` member-list sets | `operator: NE` conditions with `combine_type: ALL` | |
| 76 | Sets anchored on formula columns | Column set with `anchor_column_id` = formula display name | |
| 77 | Top-N / Bottom-N sets (literal count) | Query set (`ADVANCED/COLUMN_BASED`) with `top N`/`bottom N` keyword | |
| 78 | Top-N / Bottom-N sets (parameter-driven count) | Query set with rank formula + parameter-filter formula | |
| 79 | All-except-Top-N (`except` with `end` child) | Query set with inverted rank filter (`[rank] > N`) | |
| 80 | Condition-based sets (`function='filter'`) | Query set with boolean condition formula | |
| 81 | Member-list intersect | `GROUP_BASED` column set of computed common members | |
| 82 | Mixed computed set operations (intersect/except of mixed types) | Multi-formula query set combining filters in `search_query` | |
| 83 | Set IN/OUT consumption (`IF [Set] THEN x END`) | `sum_if ( [Set] = 'in' , x )` / group by cohort | |

### Parameters

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 84 | Static list parameters (`param-domain-type="list"`) | `model.parameters[]` with `list_config.list_choice[]` | |
| 85 | Range parameters (`param-domain-type="range"`) | `range_config` | Numeric; values as strings in TML |
| 86 | Stepped range parameters (granularity attribute) | `list_config` (enumerate min→max by step) | NOT `range_config` |
| 87 | Free-form parameters (`param-domain-type="any"`) | Free-form parameter (no config) | |
| 88 | `[Parameters].[Name]` formula references | Strip prefix to `[Name]` | |
| 89 | Parameter on liveboard header | `ordered_chips[]` + `parameter_overrides[]` with UUID | |

### Bins and Manual Groups

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 90 | Dynamic/parameter-driven bins (`class='bin'`) | `floor([x]/[param])*[param]` formula | |
| 91 | Fixed-size bins (`class='bin'`) | `BIN_BASED` cohort TML object | |
| 92 | Manual groups (`class='categorical-bin'`) | `GROUP_BASED` cohort or `if/then/else if` formula | |

### Dashboard / Liveboard

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 93 | Dashboard zones → layout | 12-column responsive grid | Band-based coordinate mapping |
| 94 | Chart zones → visualization tiles | Answer TML with `search_query`, chart type, axis configs | |
| 95 | Text/title zones | Note tiles (`note_tile.html_parsed_string`) | |
| 96 | Mark types (bar/line/circle/pie/area/text) | BAR/LINE/SCATTER/PIE/AREA/TABLE | |
| 97 | Measure Names/Values KPI blocks | One KPI tile per measure with sparkline | `client_state_v2` rendering |
| 98 | Filter zones | Liveboard `filters[]` | |
| 99 | Parameter control zones | Model `parameters[]` + header chips | |
| 100 | Orphan worksheets (not on any dashboard) | Prompted to user; added as tiles or excluded | |
| 101 | Styling/themes | 6 curated themes with brand tokens + `viz_style` palettes | |
| 102 | Sections/groups | Inferred `groups[]` + `group_layouts[]` | From viz relationships |
| 103 | Formula coverage answers | Every uncovered formula gets a testable answer | |
| 104 | Migration Summary tab | Note tile tab | Documents items migrated, decisions, partial/omitted |
| 117 | Multiple dashboards → single liveboard with tabs (Step 8 option **T**) | `layout.tabs[]` — one tab per dashboard + the Migration Summary tab | Implemented v1.5.20–v1.5.24; verified against `thoughtspot-liveboard-tml.md` schema (`layout.tabs[]`: `name`, `description`, `tiles[]`) |

### Operational Modes

| # | Capability | Notes |
|---|---|---|
| 105 | Audit mode (A) — parse-only, no auth | Coverage report with per-tier formula classification |
| 106 | Migrate mode (M) — full conversion + import | Full pipeline Steps 1–11 |
| 107 | Multi-file audit | Directory scanning, per-file + combined summary |
| 113 | CLI formula translation pipeline (`ts tableau translate-formulas`) | 14-step deterministic transform; cross-reference resolution via dependency DAG |
| 114 | Two-phase model import | Phase 1: base model (no formulas) → guaranteed success; Phase 2: add formulas with iterative error recovery |
| 115 | Join confirmation flow (Step 3.6) | Detected joins presented for confirmation; missing joins (sqlproxy) suggested from shared column names |
| 116 | Cross-reference depth reporting (audit) | Level 0/1/2+/circular counts; effective migration coverage vs syntax-level coverage |

---

## Unmapped Constructs (Limitations)

### Rejected at Translate Time (ts-cli v0.26.0)

These functions have no CLI implementation. `ts tableau translate-formulas` detects them
(`validate.py::_UNMAPPED_FUNCTIONS`) and skips the formula with an `unmapped Tableau
function: X` reason instead of emitting broken TML or silently passing the Tableau syntax
through untranslated.

| # | Tableau Function(s) | Notes |
|---|---|---|
| U1 | `SPLIT(s, delim, n)` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |
| U2 | `FINDNTH(s, sub, n)` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |
| U3 | `PROPER(s)` / `ASCII(s)` / `CHAR(n)` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |
| U4 | `REGEXP_MATCH(s, pat)` / `REGEXP_EXTRACT(s, pat)` / `REGEXP_EXTRACT_NTH(s, pat, n)` / `REGEXP_REPLACE(s, pat, r)` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |
| U5 | `MAKEDATE(y, m, d)` / `MAKETIME(h, m, s)` / `MAKEDATETIME(date, time)` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |
| U6 | `ISDATE(s)` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |
| U7 | `USERNAME()` / `FULLNAME()` / `ISUSERNAME(s)` / `ISFULLNAME(s)` / `USERDOMAIN()` | Rejected with reason at translate time (ts-cli v0.26.0) — manual translation required |

### HIGH — Functionality loss, no workaround

| # | Tableau Construct | Reason | Workaround |
|---|---|---|---|
| L1 | `PREVIOUS_VALUE()` (true recursion) | Recursive table calc; no SQL equivalent | Omit + log. String-aggregation CSV technique IS handled separately (#71) |
| L2 | True statistical clustering (k-means — analytics-engine "Clusters" calc) | No ThoughtSpot equivalent | Omit + log. Note: `categorical-bin` (manual groups) IS translatable (#92) |
| L3 | `RAWSQL_*()` functions | Direct SQL passthrough; not portable | Omit + log |
| L4 | COLLECTION datasources (multiple primary data sources combined) | Not implemented | Deferred (open-items #3) |
| L5 | Row-offset table calcs with ambiguous addressing (`CellInPane`, multi-dim `Table`) | Sort/partition context unrecoverable | Omit + log |
| L6 | Bare `FIRST()` as filter (e.g. `IF FIRST() == 0`) | Row-position test; no TS equivalent. `FIRST()` returns offset, not value | Omit + log |
| L7 | Bare `LAST()` standalone | Returns offset-to-end; no TS equivalent | Omit + log |

### MEDIUM — Partial translation or admin enablement required

| # | Tableau Construct | Limitation | Workaround |
|---|---|---|---|
| L8 | Set actions (`<action>` on a set) | No interactive set membership changes in TS | Omit + log. See L26 for the other `<action>` types (filter/URL/parameter) |
| L9 | SQL pass-through functions the CLI emits (RANK partitioned, DENSE_RANK, SIZE, UPPER, LOWER) | Enabled by default — admin would only need to check if explicitly turned off in Admin > Search & SpotIQ | Flagged with PT1 marker for review. `PROPER`/`ASCII`/`CHAR`/`REGEXP_*`/`FINDNTH` are a distinct case — the CLI does not emit a pass-through for them at all; see "Rejected at Translate Time" above |
| L10 | Geospatial formulas (`MAKEPOINT`, `MAKELINE`, `DISTANCE`, `BUFFER`, `AREA`) | No spatial data types or constructors | Decompose `MAKEPOINT` lat/lon to individual ATTRIBUTE columns; omit spatial formula + log |
| L11 | Non-warehouse sources (`google-sheets`, `ogrdirect`, `webdata-direct`, `CustomMapbox`) | No ThoughtSpot connection possible | Skip datasource; data must be loaded into a warehouse first |
| L24 | Tableau hierarchies (`<drill-paths>` in TWB XML) | No TML construct exists to encode a curated drill order (e.g. Region → State → City). Near-universal in production workbooks | Omit + log in the migration report's Limitations section. ThoughtSpot's own ad-hoc drill-down still works without a declared hierarchy, but the authored order/structure from `<drill-paths>` is not preserved. See BL-072 |
| L25 | Dimension value aliases (`<aliases>` in TWB XML) | No TML construct for display-value remapping (e.g. source value `"US"` displayed as `"United States"`) | Omit + log. A `CASE`-style `if/else if` formula reproducing the alias mapping is conceivable but not auto-generated by the CLI today. See BL-072 |
| L26 | Dashboard filter actions / URL actions / parameter actions (`<action>`, non-set) | No interactive cross-viz filter triggering, URL navigation, or parameter-set-on-click in TS Liveboards. Only set actions were previously documented (L8) — filter/URL/parameter actions were undocumented until now | Omit + log |
| L27 | Fiscal-year start setting (`fiscal_year_start` datasource attribute) | No TML construct on the Model carries a non-calendar fiscal year start. ThoughtSpot date functions accept an optional `fiscal` parameter, but nothing populates it from this attribute today | Omit + log. `ts-object-model-coach`'s `time_defaults.fiscal_year_start` field (`model-instructions-schema.md`) is a plausible landing spot for a future coaching-pass integration, but this skill does not wire it up. See BL-072 |

### LOW — Cosmetic or edge-case

| # | Tableau Construct | Limitation | Workaround |
|---|---|---|---|
| L16 | SQL-lookup parameter values | ThoughtSpot `list_config` is static; no live-query capability | Point-in-time snapshot; document staleness |
| L17 | `RUNNING_COUNT` | No `cumulative_count` function | Approximate with `cumulative_sum(1, [sort_attr])` at answer level |
| L18 | Bitmap/image zones | Images not migratable to liveboard tiles | Skipped |
| L19 | Web/extension zones | No equivalent | Skipped |
| L20 | Flipboard/Story interaction | Flip navigation lost | Content salvaged; interaction dropped |
| L21 | Legend/color zones | TS draws its own legends | Skipped |
| L22 | `DATEDIFF('week', ...)` boundary semantics | Week-start semantics differ between Tableau and TS | Flag per workbook for manual verification |
| L23 | Manual group value snapshot | `categorical-bin` values from TWB authoring time may not exist in current data | Flag as data-fidelity limitation |

### Notes on limitations

**L1–L3** are truly untranslatable — the functions have no SQL or ThoughtSpot equivalent.
The skill detects them, omits them cleanly, and logs them in the audit report.

**L4** (COLLECTION datasources) is the only HIGH-severity structural gap. Data blending
(#4) handles the common multi-datasource case; COLLECTION is a separate, rarer construct.

**L6–L7** (bare FIRST/LAST) are distinct from LOOKUP(agg, FIRST/LAST) (#68–69) — see
the decision tree in `tableau-formula-translation.md` tiers 5a–6c.

**L9** (pass-through functions) — SQL Passthrough Functions are **enabled by default** in
ThoughtSpot. This is only a limitation if an admin has explicitly turned it off in
Admin > Search & SpotIQ. All pass-through formulas are flagged with `PT1` in the audit
report for visibility. Native alternatives are used wherever possible — SQL pass-through
is the last resort (see the translation priority order in `tableau-formula-translation.md`).
`PROPER`/`ASCII`/`CHAR`/`REGEXP_*`/`FINDNTH` are documented in `tableau-formula-translation.md`
as pass-through candidates but the CLI does not implement them (v0.26.0) — it rejects the
formula with a reason instead of emitting the pass-through, so a manual `sql_string_op`/
`sql_bool_op`/`sql_int_op` formula (per that reference) is required.

**L24–L27** are structural/metadata gaps documented here for the first time — hierarchies,
value aliases, non-set dashboard actions, and fiscal-year start were previously absent
from this matrix entirely despite being common in production Tableau workbooks. None of
them break an import; all are logged in the migration report's Limitations section and
left for manual follow-up. See BL-072.
