# Coverage Matrix: Tableau Workbook → ThoughtSpot Model + Liveboard

What the `ts-convert-from-tableau` skill maps and what it does not.
Use this as the canonical limitations reference.

---

## Mapped Constructs

### Structure and Schema

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | Physical tables (`<relation type="table">`) | Table TML (one per physical table) | |
| 2 | Custom SQL relations (`<relation type="text">`) | SQL View TML — full SQL preserved in `sql_query` | |
| 3 | Joins (`<relation type="join">` — inner/left/right/full) | Model `joins[]` with type mapping (`full`→`OUTER`, `left`→`LEFT_OUTER`, etc.) | |
| 4 | Data blending (`<datasource-relationships>`) | Merged single model with `LEFT_OUTER` joins from blend column mappings; connected-component grouping | 64% of audited workbooks |
| 5 | Cross-datasource formula references (blend) | Resolved within merged model — federated ID/caption prefix stripped, re-prefixed with `TABLE::` | |
| 6 | Column data types (string, integer, real, boolean, date, datetime) | VARCHAR, INT64, DOUBLE, BOOL, DATE, DATETIME | |
| 7 | `db_column_name` from `remote-name` metadata | Physical column name in table TML | |
| 8 | Connection binding by name | `connection.name` on every table/sql_view TML (never GUID — invariant I6) | |
| 9 | Published datasource (`sqlproxy` connection) | Resolved to `dbname` from connection | |
| 10 | Extract datasources | Resolved to underlying live source; skipped if no source resolves | |
| 11 | `.twbx` archive extraction | Unzip to access inner `.twb` | |
| 12 | Topological sort of calculated fields | Formulas emitted in dependency order (level 0 first) | |

### Formula Translation — Scalar Functions

| # | Tableau Function(s) | ThoughtSpot Function | Notes |
|---|---|---|---|
| 13 | `IF/THEN/ELSE/ELSEIF/END` | `if ( cond ) then a else b` / `else if` | |
| 14 | `CASE/WHEN` | Expanded to `if/else if` chain (no native CASE in TS) | |
| 15 | `IIF(test, a, b)` | `if ( test ) then a else b` | |
| 16 | `IFNULL(a, b)`, `ZN(a)` | `ifnull ( a , b )` | |
| 17 | `ISNULL(a)` | `isnull ( a )` | |
| 18 | `CONTAINS`, `TRIM`, `REPLACE`, `FIND` | `contains`, `trim`, `replace`, `strpos` | |
| 19 | `LEFT/MID/RIGHT/LEN` | `substr()` with index adjustment / `strlen()` | |
| 20 | `UPPER/LOWER` | `sql_string_op("UPPER/LOWER({0})")` pass-through | |
| 21 | `STARTSWITH/ENDSWITH` | `strpos(s,sub) = 1` / `substr` idiom | |
| 22 | `PROPER/ASCII/CHAR` | `sql_string_op("INITCAP/ASCII/CHR({0})")` pass-through | |
| 23 | `SPLIT(s, delim, n)` | `substr`/`strpos` chain | Documented |
| 24 | `DATEDIFF` (day/month/year/hour/minute/week) | `diff_days/diff_months/diff_years/diff_time` (reversed arg order) | |
| 25 | `DATETRUNC` | `start_of_month/quarter/week/year` | |
| 26 | `DATEADD` | `add_days/add_months/add_years` | |
| 27 | `DATEPART` (month/day/year/hour/quarter/week/dayofyear/weekday) | `month_number/day/year/hour_of_day/quarter_number/week_number_of_year/day_number_of_year/day_of_week` | |
| 28 | `DATENAME('month', d)` | `month ( [date] )` — returns month name natively (e.g. "january") | |
| 29 | `DATEPARSE(format, s)` | `to_date ( s , format )` (args flipped) | |
| 30 | `TODAY()/NOW()/DATE()/YEAR()/MONTH()/DAY()` | `today()/now()/date()/year()/month_number()/day()` | |
| 31 | `ABS/ROUND/CEILING/FLOOR/SQRT/POWER/LOG/LN/EXP` | `abs/round/ceil/floor/sqrt/pow/log10/ln/exp` | |
| 32 | `SIN/COS/TAN` (and inverse trig) | Radians-to-degrees conversion applied | |
| 33 | `PI()/RADIANS()/DEGREES()` | Literal composites (no native) | |
| 34 | `INT(x)` | `if ( x >= 0 ) then floor ( x ) else ceil ( x )` (truncate-toward-zero) | Partial |
| 35 | `FLOAT(x)/STR(x)` | `to_double(x)/to_string(x)` | |
| 36 | `DATETIME(expr)` cast | `sql_date_time_op ( "TO_TIMESTAMP({0})" , [col] )` pass-through | |
| 37 | String concat (`+` on strings) | `concat ( a , b )` (TS `+` is numeric-only) | |
| 38 | `SIGN(x)/SQUARE(x)` | Composite `if/then` / `pow(x,2)` | |
| 39 | `MIN/MAX` (scalar, 2-arg) | `if ( a < b ) then a else b` / vice versa | |
| 40 | Division by zero | `safe_divide()` or `if ( b = 0 ) then null else a/b` | |
| 41 | `REGEXP_EXTRACT/MATCH/REPLACE` | `sql_string_op/sql_bool_op` pass-through (Snowflake REGEXP_*) | Documented |
| 42 | `FINDNTH(s, sub, n)` | `sql_int_op("REGEXP_INSTR({0},{1},1,{2})")` pass-through | Documented |

### Formula Translation — Aggregates

| # | Tableau Function(s) | ThoughtSpot Function | Notes |
|---|---|---|---|
| 43 | `SUM/COUNT/AVG/MIN/MAX` (aggregate) | Direct mappings with `aggregation:` on MEASURE columns | |
| 44 | `COUNTD(x)` | `unique count ( x )` formula (never `COUNT_DISTINCT` aggregation — invariant I5) | |
| 45 | `STDEV/MEDIAN` | `stddev/median` | |
| 46 | `ATTR(x)` | Reference `x` directly | |
| 47 | Conditional aggregates (`SUM/COUNT/AVG(IF c THEN x END)`) | `sum_if/count_if/average_if/unique_count_if` family | |
| 48 | `Number of Records` / row count (`= 1`) | `count([column])` with user-prompted column | |
| 49 | Redundant pass-through formulas (`SUM([col])` / `[col]`) | Detected and dropped; use physical column directly | |

### Formula Translation — LOD Expressions

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 50 | `{FIXED [dim] : AGG([col])}` | `group_aggregate ( agg ( [t::col] ) , { dim } , {} )` | |
| 51 | `{INCLUDE [dim] : AGG([col])}` | `group_aggregate ( ... , query_groups() + { dim } , query_filters() )` | |
| 52 | `{EXCLUDE [dim] : AGG([col])}` | `group_aggregate ( ... , query_groups() - { dim } , query_filters() )` | |
| 53 | `TOTAL(SUM([col]))` / percent-of-total | `group_aggregate ( ... , {} , query_filters() )` | |
| 54 | `max([date])` in formula filters — "latest year in data" | `group_aggregate ( max ( [date] ) , {} , {} )` — global max date, dynamic | |

### Formula Translation — Running / Cumulative

| # | Tableau Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 55 | `RUNNING_SUM/AVG/MAX/MIN` | `cumulative_sum/average/max/min ( [t::col] , [sort_attr] )` | |
| 56 | `RUNNING_COUNT` | `cumulative_sum ( 1 , [sort_attr] )` at answer level (approx) | Documented |

### Formula Translation — Moving / Window

| # | Tableau Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 57 | `WINDOW_SUM/AVG/MAX/MIN` | `moving_sum/average/max/min ( [t::col] , start , end , [sort_attr] )` | |
| 58 | `WINDOW_STDEV/WINDOW_COUNT` (sliding window) | `moving_stdev/moving_count` — same pattern as WINDOW_SUM/AVG (#57) | |
| 59 | `WINDOW_PERCENTILE/WINDOW_MEDIAN` (sliding window) | `sql_*_aggregate_op` pass-through: `PERCENTILE_CONT/MEDIAN(...) OVER (...)` | |

### Formula Translation — Rank

| # | Tableau Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 60 | `RANK(SUM([col]))` | `rank ( sum ( [t::col] ) , 'desc' )` (direction arg required) | |
| 61 | `RANK_UNIQUE` | `rank()` (competition ranking; tie-handling difference documented) | |
| 62 | Partitioned `RANK` | `group_aggregate ( sql_int_aggregate_op("rank() over (...)") , query_groups() + {dim} , query_filters() )` — always wrapped | |
| 63 | `RANK_DENSE` / `RANK_MODIFIED` | `sql_int_aggregate_op("dense_rank() over (...)")` pass-through | |

### Formula Translation — Row-Offset Table Calculations

| # | Tableau Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 64 | `INDEX() <= N` (Top-N filter intent) | `rank ( [m] , 'desc' )` + query set | |
| 65 | `INDEX()` (display row numbering, sort recoverable) | `rank ( sum ( [m] ) , 'asc' )` | |
| 66 | `LOOKUP(agg, N)` where N < 0 (LAG) | `moving_sum ( [m] , abs(N) , -abs(N) , [sort] )` | |
| 67 | `LOOKUP(agg, N)` where N > 0 (LEAD) | `moving_sum ( [m] , -N , N , [sort] )` | |
| 68 | `LOOKUP(agg, FIRST())` — "get value at first row" | `first_value ( sum ( [m] ) , query_groups() , { [sort] } )` | |
| 69 | `LOOKUP(agg, LAST())` — "get value at last row" | `last_value ( sum ( [m] ) , query_groups() , { [sort] } )` | |
| 70 | `SIZE()` (unpartitioned) | `sql_int_aggregate_op ( "COUNT(*) OVER ()" )` pass-through | |
| 71 | String-aggregation CSV technique (FIRST/LAST/LOOKUP/PREVIOUS_VALUE building delimited string) | `sql_string_aggregate_op("LISTAGG(...)")` | |
| 72 | `<table-calc>` addressing extraction (Step 3f) | Sort/partition context recovery from TWB XML `ordering-type`, `ordering-field`, `<order>` | |

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
| 85 | Range parameters (`param-domain-type="range"`) | `range_config` (numeric; values as strings in TML) | |
| 86 | Stepped range parameters (granularity attribute) | `list_config` (enumerate min→max by step), NOT `range_config` | |
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
| 93 | Dashboard zones → layout | 12-column responsive grid (band-based coordinate mapping) | Needs verification (#6) |
| 94 | Chart zones → visualization tiles | Answer TML with `search_query`, chart type, axis configs | Partial (#5) |
| 95 | Text/title zones | Note tiles (`note_tile.html_parsed_string`) | Needs verification (#7) |
| 96 | Mark types (bar/line/circle/pie/area/text) | BAR/LINE/SCATTER/PIE/AREA/TABLE | |
| 97 | Measure Names/Values KPI blocks | One KPI tile per measure with date + sparkline (`client_state_v2`) | |
| 98 | Filter zones | Liveboard `filters[]` | |
| 99 | Parameter control zones | Model `parameters[]` + header chips | |
| 100 | Orphan worksheets (not on any dashboard) | Prompted to user; added as tiles or excluded | |
| 101 | Styling/themes | 6 curated themes with brand tokens + `viz_style` palettes | |
| 102 | Sections/groups | Inferred `groups[]` + `group_layouts[]` from viz relationships | |
| 103 | Formula coverage answers | Every uncovered formula gets a testable answer | |
| 104 | Migration Summary tab | Note tile tab documenting items migrated, decisions, partial/omitted | |

### Operational Modes

| # | Capability | Notes |
|---|---|---|
| 105 | Audit mode (A) — parse-only, no auth | Coverage report with per-tier formula classification |
| 106 | Migrate mode (M) — full conversion + import | Full pipeline Steps 1–11 |
| 107 | Multi-file audit | Directory scanning, per-file + combined summary |
| 108 | Dialect support: Snowflake (primary) | All pass-through SQL uses Snowflake syntax; skill confirms dialect with user if unknown |
| 109 | Dialect support: Redshift | Dialect notes for `LISTAGG`/type casting; skill confirms dialect with user if unknown |
| 110 | Dialect support: Postgres | Dialect notes for `string_agg`/type casting; skill confirms dialect with user if unknown |

---

## Unmapped Constructs (Limitations)

### HIGH — Functionality loss, no workaround

| # | Tableau Construct | Reason | Workaround |
|---|---|---|---|
| L1 | `PREVIOUS_VALUE()` (true recursion) | Recursive table calc; no SQL equivalent | Omit + log. String-aggregation CSV technique IS handled separately (#71) |
| L2 | True statistical clustering (k-means — analytics-engine "Clusters" calc) | No ThoughtSpot equivalent | Omit + log. Note: `categorical-bin` (manual groups) IS translatable (#92) |
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
| L10 | All SQL pass-through functions (RANK partitioned, DENSE_RANK, SIZE, REGEXP, UPPER/LOWER, PROPER, ASCII, CHAR) | Enabled by default — admin would only need to check if explicitly turned off in Admin > Search & SpotIQ | Flagged with PT1 marker for review |
| L11 | `rank()` tie handling | TS `rank()` is competition ranking (1,1,3) — no `ROW_NUMBER()` equivalent for unique ranks | Document the difference |
| L12 | Geospatial formulas (`MAKEPOINT`, `MAKELINE`, `DISTANCE`, `BUFFER`, `AREA`) | No spatial data types or constructors | Decompose `MAKEPOINT` lat/lon to individual ATTRIBUTE columns; omit spatial formula + log |
| L13 | Non-warehouse sources (`google-sheets`, `ogrdirect`, `webdata-direct`, `CustomMapbox`) | No ThoughtSpot connection possible | Skip datasource; data must be loaded into a warehouse first |
| L14 | Liveboard layout coordinate system | Exact ThoughtSpot grid units not fully verified | Open-items #6 |
| L15 | Inline answer TML in liveboard | Nested `answer:` blocks inside `visualizations[]` not confirmed | Open-items #5 |
| L16 | NOTE_TILE structure | Exact TML structure not fully verified | Open-items #7 |
| L17 | Multi-dashboard → tabs | Liveboard tabs TML structure not implemented | Open-items #9 — deferred to v1.1.0; creates separate liveboards |

### LOW — Cosmetic or edge-case

| # | Tableau Construct | Limitation | Workaround |
|---|---|---|---|
| L18 | SQL-lookup parameter values | ThoughtSpot `list_config` is static; no live-query capability | Point-in-time snapshot; document staleness |
| L19 | `RUNNING_COUNT` | No `cumulative_count` function | Approximate with `cumulative_sum(1, [sort_attr])` at answer level |
| L20 | Bitmap/image zones | Images not migratable to liveboard tiles | Skipped |
| L21 | Web/extension zones | No equivalent | Skipped |
| L22 | Flipboard/Story interaction | Flip navigation lost | Content salvaged; interaction dropped |
| L23 | Legend/color zones | TS draws its own legends | Skipped |
| L24 | `DATEDIFF('week', ...)` boundary semantics | Week-start semantics differ between Tableau and TS | Flag per workbook for manual verification |
| L25 | Manual group value snapshot | `categorical-bin` values from TWB authoring time may not exist in current data | Flag as data-fidelity limitation |

### Notes on limitations

**L1–L4** are truly untranslatable — the functions have no SQL or ThoughtSpot equivalent.
The skill detects them, omits them cleanly, and logs them in the audit report.

**L5** (COLLECTION datasources) is the only HIGH-severity structural gap. Data blending
(#4) handles the common multi-datasource case; COLLECTION is a separate, rarer construct.

**L7–L8** (bare FIRST/LAST) are distinct from LOOKUP(agg, FIRST/LAST) (#68–69) — see
the decision tree in `tableau-formula-translation.md` tiers 5a–6c.

**L10** (pass-through functions) — SQL Passthrough Functions are **enabled by default** in
ThoughtSpot. This is only a limitation if an admin has explicitly turned it off in
Admin > Search & SpotIQ. All pass-through formulas are flagged with `PT1` in the audit
report for visibility. Native alternatives are used wherever possible — SQL pass-through
is the last resort (see the translation priority order in `tableau-formula-translation.md`).
