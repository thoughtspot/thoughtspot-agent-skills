# Coverage Matrix: Tableau Workbook → ThoughtSpot Model + Liveboard

What the `ts-convert-from-tableau` skill maps and what it does not.
Use this as the canonical limitations reference.

Last verified: 2026-06-15 (BL-024 row-offset table calcs on se-thoughtspot)

---

## Mapped Constructs

### Structure and Schema

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 1 | Physical tables (`<relation type="table">`) | Table TML (one per physical table) | Yes |
| 2 | Custom SQL relations (`<relation type="text">`) | SQL View TML — full SQL preserved in `sql_query` | Yes (open-items #4) |
| 3 | Joins (`<relation type="join">` — inner/left/right/full) | Model `joins[]` with type mapping (`full`→`OUTER`, `left`→`LEFT_OUTER`, etc.) | Yes |
| 4 | Data blending (`<datasource-relationships>`) | Merged single model with `LEFT_OUTER` joins from blend column mappings; connected-component grouping | Yes (open-items #8, 64% of audited workbooks) |
| 5 | Cross-datasource formula references (blend) | Resolved within merged model — federated ID/caption prefix stripped, re-prefixed with `TABLE::` | Yes |
| 6 | Column data types (string, integer, real, boolean, date, datetime) | VARCHAR, INT64, DOUBLE, BOOL, DATE, DATETIME | Yes |
| 7 | `db_column_name` from `remote-name` metadata | Physical column name in table TML | Yes |
| 8 | Connection binding by name | `connection.name` on every table/sql_view TML (never GUID — invariant I6) | Yes |
| 9 | Published datasource (`sqlproxy` connection) | Resolved to `dbname` from connection | Yes |
| 10 | Extract datasources | Resolved to underlying live source; skipped if no source resolves | Yes |
| 11 | `.twbx` archive extraction | Unzip to access inner `.twb` | Yes |
| 12 | Topological sort of calculated fields | Formulas emitted in dependency order (level 0 first) | Yes |

### Formula Translation — Scalar Functions

| # | Tableau Function(s) | ThoughtSpot Function | Verified |
|---|---|---|---|
| 13 | `IF/THEN/ELSE/ELSEIF/END` | `if ( cond ) then a else b` / `else if` | Yes |
| 14 | `CASE/WHEN` | Expanded to `if/else if` chain (no native CASE in TS) | Yes |
| 15 | `IIF(test, a, b)` | `if ( test ) then a else b` | Yes |
| 16 | `IFNULL(a, b)`, `ZN(a)` | `ifnull ( a , b )` | Yes |
| 17 | `ISNULL(a)` | `isnull ( a )` | Yes |
| 18 | `CONTAINS`, `TRIM`, `REPLACE`, `FIND` | `contains`, `trim`, `replace`, `strpos` | Yes |
| 19 | `LEFT/MID/RIGHT/LEN` | `substr()` with index adjustment / `strlen()` | Yes |
| 20 | `UPPER/LOWER` | `sql_string_op("UPPER/LOWER({0})")` pass-through | Yes |
| 21 | `STARTSWITH/ENDSWITH` | `strpos(s,sub) = 1` / `substr` idiom | Yes |
| 22 | `PROPER/ASCII/CHAR` | `sql_string_op("INITCAP/ASCII/CHR({0})")` pass-through | Yes |
| 23 | `SPLIT(s, delim, n)` | `substr`/`strpos` chain | Documented |
| 24 | `DATEDIFF` (day/month/year/hour/minute/week) | `diff_days/diff_months/diff_years/diff_time` (reversed arg order) | Yes |
| 25 | `DATETRUNC` | `start_of_month/quarter/week/year` | Yes |
| 26 | `DATEADD` | `add_days/add_months/add_years` | Yes |
| 27 | `DATEPART` (month/day/year/hour/quarter/week/dayofyear/weekday) | `month_number/day/year/hour_of_day/quarter_number/week_number_of_year/day_number_of_year/day_of_week` | Yes |
| 28 | `DATEPARSE(format, s)` | `to_date ( s , format )` (args flipped) | Yes |
| 29 | `TODAY()/NOW()/DATE()/YEAR()/MONTH()/DAY()` | `today()/now()/date()/year()/month_number()/day()` | Yes |
| 30 | `ABS/ROUND/CEILING/FLOOR/SQRT/POWER/LOG/LN/EXP` | `abs/round/ceil/floor/sqrt/pow/log10/ln/exp` | Yes |
| 31 | `SIN/COS/TAN` (and inverse trig) | Radians-to-degrees conversion applied | Yes |
| 32 | `PI()/RADIANS()/DEGREES()` | Literal composites (no native) | Yes |
| 33 | `INT(x)` | `if ( x >= 0 ) then floor ( x ) else ceil ( x )` (truncate-toward-zero) | Partial |
| 34 | `FLOAT(x)/STR(x)` | `to_double(x)/to_string(x)` | Yes |
| 35 | String concat (`+` on strings) | `concat ( a , b )` (TS `+` is numeric-only) | Yes |
| 36 | `SIGN(x)/SQUARE(x)` | Composite `if/then` / `pow(x,2)` | Yes |
| 37 | `MIN/MAX` (scalar, 2-arg) | `if ( a < b ) then a else b` / vice versa | Yes |
| 38 | Division by zero | `safe_divide()` or `if ( b = 0 ) then null else a/b` | Yes |
| 39 | `REGEXP_EXTRACT/MATCH/REPLACE` | `sql_string_op/sql_bool_op` pass-through (Snowflake REGEXP_*) | Documented |
| 40 | `FINDNTH(s, sub, n)` | `sql_int_op("REGEXP_INSTR({0},{1},1,{2})")` pass-through | Documented |

### Formula Translation — Aggregates

| # | Tableau Function(s) | ThoughtSpot Function | Verified |
|---|---|---|---|
| 41 | `SUM/COUNT/AVG/MIN/MAX` (aggregate) | Direct mappings with `aggregation:` on MEASURE columns | Yes |
| 42 | `COUNTD(x)` | `unique count ( x )` formula (never `COUNT_DISTINCT` aggregation — invariant I5) | Yes |
| 43 | `STDEV/MEDIAN` | `stddev/median` | Yes |
| 44 | `ATTR(x)` | Reference `x` directly | Yes |
| 45 | Conditional aggregates (`SUM/COUNT/AVG(IF c THEN x END)`) | `sum_if/count_if/average_if/unique_count_if` family | Yes |
| 46 | `Number of Records` / row count (`= 1`) | `count([column])` with user-prompted column | Yes |
| 47 | Redundant pass-through formulas (`SUM([col])` / `[col]`) | Detected and dropped; use physical column directly | Yes |

### Formula Translation — LOD Expressions

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 48 | `{FIXED [dim] : AGG([col])}` | `group_aggregate ( agg ( [t::col] ) , { dim } , {} )` | Yes |
| 49 | `{INCLUDE [dim] : AGG([col])}` | `group_aggregate ( ... , query_groups() + { dim } , query_filters() )` | Yes |
| 50 | `{EXCLUDE [dim] : AGG([col])}` | `group_aggregate ( ... , query_groups() - { dim } , query_filters() )` | Yes |
| 51 | `TOTAL(SUM([col]))` / percent-of-total | `group_aggregate ( ... , {} , query_filters() )` | Yes |

### Formula Translation — Running / Cumulative

| # | Tableau Function(s) | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 52 | `RUNNING_SUM/AVG/MAX/MIN` | `cumulative_sum/average/max/min ( [t::col] , [sort_attr] )` | Yes |
| 53 | `RUNNING_COUNT` | `cumulative_sum ( 1 , [sort_attr] )` at answer level (approx) | Documented |

### Formula Translation — Moving / Window

| # | Tableau Function(s) | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 54 | `WINDOW_SUM/AVG/MAX/MIN` | `moving_sum/average/max/min ( [t::col] , start , end , [sort_attr] )` | Yes |
| 55 | `WINDOW_STDEV/PERCENTILE/COUNT/MEDIAN` | Answer-level only; plain aggregate fallback when non-sliding | Documented |

### Formula Translation — Rank

| # | Tableau Function(s) | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 56 | `RANK(SUM([col]))` | `rank ( sum ( [t::col] ) , 'desc' )` (direction arg required) | Yes |
| 57 | `RANK_UNIQUE` | `rank()` (competition ranking; tie-handling difference documented) | Yes |
| 58 | Partitioned `RANK` | `group_aggregate ( sql_int_aggregate_op("rank() over (...)") , query_groups() + {dim} , query_filters() )` — always wrapped | Yes (2026-06-15) |
| 59 | `RANK_DENSE` / `RANK_MODIFIED` | `sql_int_aggregate_op("dense_rank() over (...)")` pass-through | Yes |

### Formula Translation — Row-Offset Table Calculations

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 60 | `INDEX() <= N` (Top-N filter intent) | `rank ( [m] , 'desc' )` + query set | Yes (2026-06-15) |
| 61 | `INDEX()` (display row numbering, sort recoverable) | `rank ( sum ( [m] ) , 'asc' )` | Yes (2026-06-15) |
| 62 | `LOOKUP(agg, N)` where N < 0 (LAG) | `moving_sum ( [m] , abs(N) , -abs(N) , [sort] )` | Yes (DATE + VARCHAR, 2026-06-15) |
| 63 | `LOOKUP(agg, N)` where N > 0 (LEAD) | `moving_sum ( [m] , -N , N , [sort] )` | Yes (2026-06-15) |
| 64 | `LOOKUP(agg, FIRST())` — "get value at first row" | `first_value ( sum ( [m] ) , query_groups() , { [sort] } )` | Yes (2026-06-15) |
| 65 | `LOOKUP(agg, LAST())` — "get value at last row" | `last_value ( sum ( [m] ) , query_groups() , { [sort] } )` | Yes (2026-06-15) |
| 66 | `SIZE()` (unpartitioned) | `sql_int_aggregate_op ( "COUNT(*) OVER ()" )` pass-through | Yes (2026-06-15) |
| 67 | String-aggregation CSV technique (FIRST/LAST/LOOKUP/PREVIOUS_VALUE building delimited string) | `sql_string_aggregate_op("LISTAGG(...)")` | Yes (2026-06-12) |
| 68 | `<table-calc>` addressing extraction (Step 3f) | Sort/partition context recovery from TWB XML `ordering-type`, `ordering-field`, `<order>` | Yes |

### Sets

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 69 | Static sets (`<group>` with union/member) | `GROUP_BASED` column set (`cohort_type: SIMPLE`) | Yes (2026-06-12) |
| 70 | Static sets with `%null%` member | `{Null}` grouping value in column set | Yes (2026-06-12) |
| 71 | `except` member-list sets | `operator: NE` conditions with `combine_type: ALL` | Yes (2026-06-12) |
| 72 | Sets anchored on formula columns | Column set with `anchor_column_id` = formula display name | Yes (2026-06-12) |
| 73 | Top-N / Bottom-N sets (literal count) | Query set (`ADVANCED/COLUMN_BASED`) with `top N`/`bottom N` keyword | Yes (2026-06-12) |
| 74 | Top-N / Bottom-N sets (parameter-driven count) | Query set with rank formula + parameter-filter formula | Yes (2026-06-12) |
| 75 | All-except-Top-N (`except` with `end` child) | Query set with inverted rank filter (`[rank] > N`) | Yes (2026-06-14) |
| 76 | Condition-based sets (`function='filter'`) | Query set with boolean condition formula | Yes (2026-06-14) |
| 77 | Member-list intersect | `GROUP_BASED` column set of computed common members | Yes (2026-06-14) |
| 78 | Mixed computed set operations (intersect/except of mixed types) | Multi-formula query set combining filters in `search_query` | Yes (2026-06-14) |
| 79 | Set IN/OUT consumption (`IF [Set] THEN x END`) | `sum_if ( [Set] = 'in' , x )` / group by cohort | Yes (2026-06-12) |

### Parameters

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 80 | Static list parameters (`param-domain-type="list"`) | `model.parameters[]` with `list_config.list_choice[]` | Yes |
| 81 | Range parameters (`param-domain-type="range"`) | `range_config` (numeric; values as strings in TML) | Yes |
| 82 | Stepped range parameters (granularity attribute) | `list_config` (enumerate min→max by step), NOT `range_config` | Yes (2026-06-12) |
| 83 | Free-form parameters (`param-domain-type="any"`) | Free-form parameter (no config) | Yes |
| 84 | `[Parameters].[Name]` formula references | Strip prefix to `[Name]` | Yes |
| 85 | Parameter on liveboard header | `ordered_chips[]` + `parameter_overrides[]` with UUID | Yes |

### Bins and Manual Groups

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 86 | Dynamic/parameter-driven bins (`class='bin'`) | `floor([x]/[param])*[param]` formula | Yes |
| 87 | Fixed-size bins (`class='bin'`) | `BIN_BASED` cohort TML object | Yes |
| 88 | Manual groups (`class='categorical-bin'`) | `GROUP_BASED` cohort or `if/then/else if` formula | Yes |

### Dashboard / Liveboard

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 89 | Dashboard zones → layout | 12-column responsive grid (band-based coordinate mapping) | Needs verification (#6) |
| 90 | Chart zones → visualization tiles | Answer TML with `search_query`, chart type, axis configs | Partial (#5) |
| 91 | Text/title zones | Note tiles (`note_tile.html_parsed_string`) | Needs verification (#7) |
| 92 | Mark types (bar/line/circle/pie/area/text) | BAR/LINE/SCATTER/PIE/AREA/TABLE | Yes |
| 93 | Measure Names/Values KPI blocks | One KPI tile per measure with date + sparkline (`client_state_v2`) | Yes |
| 94 | Filter zones | Liveboard `filters[]` | Yes |
| 95 | Parameter control zones | Model `parameters[]` + header chips | Yes |
| 96 | Orphan worksheets (not on any dashboard) | Prompted to user; added as tiles or excluded | Yes |
| 97 | Styling/themes | 6 curated themes with brand tokens + `viz_style` palettes | Yes |
| 98 | Sections/groups | Inferred `groups[]` + `group_layouts[]` from viz relationships | Yes |
| 99 | Formula coverage answers | Every uncovered formula gets a testable answer | Yes |
| 100 | Migration Summary tab | Note tile tab documenting items migrated, decisions, partial/omitted | Yes |

### Operational Modes

| # | Capability | Notes | Verified |
|---|---|---|---|
| 101 | Audit mode (A) — parse-only, no auth | Coverage report with per-tier formula classification | Yes |
| 102 | Migrate mode (M) — full conversion + import | Full pipeline Steps 1–11 | Yes |
| 103 | Multi-file audit | Directory scanning, per-file + combined summary | Yes |
| 104 | Dialect support: Snowflake (primary) | All pass-through SQL uses Snowflake syntax | Yes |
| 105 | Dialect support: Redshift | Dialect notes for `LISTAGG`/type casting | Yes (#15) |
| 106 | Dialect support: Postgres | Dialect notes for `string_agg`/type casting | Yes (#15) |

### Corrections from Review (formerly listed as limitations)

| # | Tableau Construct | ThoughtSpot Equivalent | Verified |
|---|---|---|---|
| 107 | `DATENAME('month', d)` | `month ( [date] )` — returns month name natively (e.g. "january") | Yes (se-thoughtspot, 2026-06-15) |
| 108 | `WINDOW_STDEV/WINDOW_COUNT` (sliding window) | `moving_*` family — same as WINDOW_SUM/AVG (#54) | Documented |
| 109 | `WINDOW_PERCENTILE/WINDOW_MEDIAN` (sliding window) | `sql_*_aggregate_op` pass-through: `PERCENTILE_CONT/MEDIAN(...) OVER (...)` | Documented |
| 110 | `max([date])` in formula filters — "latest year in data" | `group_aggregate ( max ( [date] ) , {} , {} )` — global max date, dynamic | Yes (se-thoughtspot, 2026-06-15) |
| 111 | `DATETIME(expr)` cast | `sql_date_time_op ( "TO_TIMESTAMP({0})" , [col] )` pass-through | Yes (se-thoughtspot, 2026-06-15) |

---

## Unmapped Constructs (Limitations)

### HIGH — Functionality loss, no workaround

| # | Tableau Construct | Reason | Workaround |
|---|---|---|---|
| L1 | `PREVIOUS_VALUE()` (true recursion) | Recursive table calc; no SQL equivalent | Omit + log. String-aggregation CSV technique IS handled separately (#67) |
| L2 | True statistical clustering (k-means — analytics-engine "Clusters" calc) | No ThoughtSpot equivalent | Omit + log. Note: `categorical-bin` (manual groups) IS translatable (#88) |
| L3 | `RAWSQL_*()` functions | Direct SQL passthrough; not portable | Omit + log |
| L4 | `ISMEMBEROF()` | User-specific function; no equivalent | Omit + log |
| L5 | COLLECTION datasources (multiple primary data sources combined) | Not implemented | Deferred (open-items #3) |
| L6 | Row-offset table calcs with ambiguous addressing (`CellInPane`, multi-dim `Table`) | Sort/partition context unrecoverable | Omit + log |
| L7 | Bare `FIRST()` as filter (e.g. `IF FIRST() == 0`) | Row-position test; no TS equivalent. `FIRST()` returns offset, not value | Omit + log |
| L8 | Bare `LAST()` standalone | Returns offset-to-end; no TS equivalent | Omit + log |

### MEDIUM — Partial translation or admin enablement required

| # | Tableau Construct | Limitation | Workaround |
|---|---|---|---|
| L9 | Set actions (`<action>` on a set) | No interactive set membership changes in TS | Omit + log |
| ~~L10~~ | ~~`DATETIME(expr)` cast~~ | ~~No native `to_datetime`~~ | Moved to Mapped (#111): `sql_date_time_op ( "TO_TIMESTAMP({0})" , [col] )` — verified on se-thoughtspot |
| L11 | All SQL pass-through functions (RANK partitioned, DENSE_RANK, SIZE, REGEXP, UPPER/LOWER, PROPER, ASCII, CHAR) | Enabled by default — admin would only need to check if explicitly turned off in Admin > Search & SpotIQ | Flagged with PT1 marker for review |
| L12 | `rank()` tie handling | TS `rank()` is competition ranking (1,1,3) — no `ROW_NUMBER()` equivalent for unique ranks | Document the difference |
| L13 | Geospatial formulas (`MAKEPOINT`, `MAKELINE`, `DISTANCE`, `BUFFER`, `AREA`) | No spatial data types or constructors | Decompose `MAKEPOINT` lat/lon to individual ATTRIBUTE columns; omit spatial formula + log |
| L14 | Non-warehouse sources (`google-sheets`, `ogrdirect`, `webdata-direct`, `CustomMapbox`) | No ThoughtSpot connection possible | Skip datasource; data must be loaded into a warehouse first |
| L15 | Liveboard layout coordinate system | Exact ThoughtSpot grid units not fully verified | Open-items #6 |
| L16 | Inline answer TML in liveboard | Nested `answer:` blocks inside `visualizations[]` not confirmed | Open-items #5 |
| L17 | NOTE_TILE structure | Exact TML structure not fully verified | Open-items #7 |
| L18 | Multi-dashboard → tabs | Liveboard tabs TML structure not implemented | Open-items #9 — deferred to v1.1.0; creates separate liveboards |

### LOW — Cosmetic or edge-case

| # | Tableau Construct | Limitation | Workaround |
|---|---|---|---|
| L19 | SQL-lookup parameter values | ThoughtSpot `list_config` is static; no live-query capability | Point-in-time snapshot; document staleness |
| L20 | `RUNNING_COUNT` | No `cumulative_count` function | Approximate with `cumulative_sum(1, [sort_attr])` at answer level |
| ~~L21~~ | ~~`DATENAME('month', d)`~~ | ~~No month-name function~~ | Moved to Mapped (#107): `month([date])` returns month name natively |
| L22 | Bitmap/image zones | Images not migratable to liveboard tiles | Skipped |
| L23 | Web/extension zones | No equivalent | Skipped |
| L24 | Flipboard/Story interaction | Flip navigation lost | Content salvaged; interaction dropped |
| L25 | Legend/color zones | TS draws its own legends | Skipped |
| ~~L26~~ | ~~`WINDOW_STDEV/PERCENTILE/COUNT/MEDIAN`~~ | ~~No windowed model-formula equivalent~~ | Moved to Mapped (#108–109): `moving_*` for sliding windows, `sql_*_aggregate_op` pass-through for others |
| L27 | `DATEDIFF('week', ...)` boundary semantics | Week-start semantics differ between Tableau and TS | Flag per workbook for manual verification |
| L28 | Manual group value snapshot | `categorical-bin` values from TWB authoring time may not exist in current data | Flag as data-fidelity limitation |
| ~~L29~~ | ~~`max([date])` in formula filters~~ | ~~Cannot compute dynamically~~ | Moved to Mapped (#110): `group_aggregate ( max ( [date] ) , {} , {} )` returns global max date; or query set for "rows where date = max" |

### Notes on limitations

**L1–L4** are truly untranslatable — the functions have no SQL or ThoughtSpot equivalent.
The skill detects them, omits them cleanly, and logs them in the audit report.

**L5** (COLLECTION datasources) is the only HIGH-severity structural gap. Data blending
(#4) handles the common multi-datasource case; COLLECTION is a separate, rarer construct.

**L7–L8** (bare FIRST/LAST) are distinct from LOOKUP(agg, FIRST/LAST) (#64–65) — see
the decision tree in `tableau-formula-translation.md` tiers 5a–6c.

**L11** (pass-through functions) — SQL Passthrough Functions are **enabled by default** in
ThoughtSpot. This is only a limitation if an admin has explicitly turned it off in
Admin > Search & SpotIQ. All pass-through formulas are flagged with `PT1` in the audit
report for visibility. Native alternatives are used wherever possible — SQL pass-through
is the last resort (see the translation priority order in `tableau-formula-translation.md`).

---

## Test Workbooks

| Source | Features Exercised |
|---|---|
| 140-workbook TWB corpus | Audit-mode coverage statistics: INDEX (39), LOOKUP (21), FIRST/LAST/SIZE (18), sets (42), parameters, blends (90/140), all formula tiers |
| BL-024 test liveboard (`2c33a13e-...`) on se-thoughtspot | LAG/LEAD (`moving_sum` offsets), FIRST/LAST (`first_value`/`last_value`), SQL pass-through with date matching, `group_aggregate` wrapping for partitioned rank, SIZE | 
| BL-024 test liveboard v1 (`4253d395-...`) on se-thoughtspot | Original offset testing (superseded by v2) |
| Static set test (se-thoughtspot, `TEST_SV_DMSI_AI_CONTEXT`) | Column set creation, IN/OUT semantics, formula-anchor, NE/except sets |
| Top-N set test (se-thoughtspot, `TEST_SV_DMSI_AI_CONTEXT`) | Dynamic (rank + parameter-filter) and static (`top N`) query sets |
| KPI sparkline test (se-thoughtspot) | `client_state_v2` rendering, sparkline date + measure binding |
| Data blend test (se-thoughtspot) | Two-datasource blend → merged model with LEFT_OUTER join |
