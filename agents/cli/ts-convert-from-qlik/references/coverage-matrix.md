<!-- currency: qlik — 2026-07 (initial ts qlik release; offline .qvf + engine-artifacts) -->

# Coverage Matrix: Qlik Sense App → ThoughtSpot Model + Liveboard

What the `ts-convert-from-qlik` skill (`ts qlik`) maps and what it does not.
Use this as the canonical limitations reference.

---

## Mapped Constructs

### Structure and Schema

| # | Qlik Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | Data-model tables (IR `tables`) | Table TML (one per table) | |
| 2 | Table fields / columns | Table TML `columns[]` with `db_column_name` on every column | Invariant I1 honoured even when name == db_column_name |
| 3 | Qlik field types → TS types | `integer`→INT64, `num`/`double`/`real`/`money`→DOUBLE, `text`/`string`→VARCHAR, `date`→DATE, `timestamp`→DATE_TIME, `time`→TIME, `bool`→BOOL | Falls back to VARCHAR for unknown types |
| 4 | Warehouse type map (`--types wh_types.json`) | Real column types override Qlik-inferred types | Prefer this over Qlik type inference when available |
| 5 | Data connection (`lib://`) | `connection: { name: }` on every table | Name only, never GUID/fqn (invariant I6) |
| 6 | Master measures | Model `formulas[]` + MEASURE `columns[]` with `formula_id` linkage | Single-pass import via `[formula_<name>]` id-refs |
| 7 | Master/table columns | Model `columns[]` ATTRIBUTE entries; duplicate display names auto-qualified with table name | Keeps model column names unique |

### Formula Translation (Qlik expression → ThoughtSpot formula)

| # | Qlik Function(s) | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 8 | `Sum` / `Avg` / `Min` / `Max` | `sum` / `average` / `min` / `max` | Aggregation on MEASURE columns |
| 9 | `Count` | `count` | |
| 10 | `Count(distinct x)` | `unique count ( x )` | Never a COUNT_DISTINCT aggregation (invariant I5) |
| 11 | `If(cond, a, b)` | `if ( cond ) then a else b` | |
| 12 | Arithmetic / comparison operators | Pass-through | |
| 13 | Set Analysis — set-literal membership (`{1}` total, `=`/`-` include/exclude of literal values) | Filter predicates on the formula | Only literal/static selection sets; see U1 for `$`-context |
| 14 | 199-row Qlik→ThoughtSpot function map (`ts_cli/qlik/data/`) | Mapped per row; unmapped functions flagged (see below) | Loaded by `ts qlik build-model`. Every ThoughtSpot name in the map was audited end-to-end and live-probed on se-thoughtspot 2026-07-30 (BL-171) |
| 14a | `Upper` / `Lower` / `Trim` / `LTrim` / `RTrim` / `Replace` | `sql_string_op ( "UPPER({0})" , col )` … `sql_string_op ( "REPLACE({0}, {1}, {2})" , col, old, new )` | **No ThoughtSpot equivalent for any of the six** (BL-170/BL-171). `Trim`/`LTrim`/`RTrim`/`Replace` emitted the bare, non-existent names until ts-cli v0.126.1; emitted forms live-verified 2026-07-30 |
| 14b | `Len` / `Mid` | `strlen(col)` / `substr(col, start, n)` | `len` and `mid` are **not ThoughtSpot functions at all** — they were identity-mapped until ts-cli v0.126.1 (BL-171), so every affected formula failed at import |
| 14c | `MonthStart` / `QuarterStart` / `YearStart` / `WeekStart` / `Day` | `start_of_month` / `start_of_quarter` / `start_of_year` / `start_of_week` / `day` | Previously emitted fabricated `date_trunc_month`/`_quarter`/`_year`/`_week` and `day_of_month`, none of which exists (BL-171, live-disproved 2026-07-30) |
| 14d | `Ceil` / `Pow` / `Log` | `ceil` / `pow` / `ln` | Previously emitted `ceiling`/`power`/`log`, all three rejected by the parser (BL-171, live-disproved 2026-07-30) |
| 14f | `Index(str, sub)` / `Index(str, sub, n)` | `strpos(col, sub)` / *flagged NEEDS REVIEW* | The 2-arg form is exact (`strpos` is the first-occurrence position). A **third argument** (nth occurrence, incl. negative n) has no equivalent: a bare rename passed it through as a wrong-arity `strpos(col, sub, 2)` — a real function, so the conversion reported success and the import failed later. Now flagged at translate time (BL-171) |
| 14e | `Mid` / `Weekday` / `Month` | `substr(col, start - 1, n)` / `(day_number_of_week(col) - 1)` / `month_number(col)` | **Wrong-meaning class, not a missing name.** All three previously name-mapped to a function that exists, so they imported and returned the wrong answer — the failure mode an existence check cannot see. Qlik `Mid` is 1-indexed and `substr` is 0-indexed; Qlik `Weekday` is a number from 0=Mon while `day_of_week` returns the day NAME and `day_number_of_week` starts at 1; `month` returns the month NAME, not 1-12 (BL-171). `Weekday` carries a caveat: a non-default Qlik `FirstWeekDay` shifts the origin again, and that is app configuration the converter cannot see |
### Sheets, Charts, Liveboard

| # | Qlik Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 15 | Sheets | Liveboard tabs (one tab per sheet) | |
| 16 | Charts (`barchart`, `linechart`, `combochart`, `piechart`, `kpi`, `gauge`, `scatterplot`, `treemap`, `map`, tables) | Embedded Answer with `search_query` from the chart's dimensions + measures, and a mapped chart type | Chart-type enum validity per `thoughtspot-chart-types.md` |
| 17 | Chart dimensions + measures | Search-query tokens on the Answer | Complex per-chart expressions are not re-derived |

---

## Unmapped Constructs (Limitations)

These are flagged `NEEDS REVIEW` (or skipped) in `mapping.json` — never silently downgraded to a
wrong-but-valid substitute. The original Qlik expression is retained for the reviewer.

| # | Qlik Construct | Reason | Workaround |
|---|---|---|---|
| U1 | Set Analysis with current-selection (`$`) context or `$`-expansion | Selection state is not representable in a static ThoughtSpot model | Flag + recreate intent as a Model formula, parameter, or RLS |
| U2 | Qlik variables (`Variable.definition`) | No 1:1 target; semantics vary (constant vs expression vs macro) | Always flagged; recreate as a Model formula or parameter if needed |
| U3 | Functions with no ThoughtSpot equivalent (`subfield`, `networkdays`, `rangesum`, `mode`, `Minute`, `Second`, …) | No native function; not in the translation map | Flagged unmapped; author a manual formula (for `Minute`/`Second`, a `sql_int_op` pass-through — see D09/D10 in the mapping reference) |
| U7 | `Concat(expr, delimiter)` — Qlik's **aggregating** string join | Qlik `Concat()` joins values ACROSS rows (like `GROUP_CONCAT`); ThoughtSpot `concat()` joins within one row (mapping row S14). It was name-mapped to `concat` until ts-cli v0.126.1, producing a valid-but-wrong formula — now flagged (BL-171) | Rebuild by hand; there is no ThoughtSpot string-aggregation function |
| U4 | Table joins / associations | The offline `.qvf` IR carries no reliable join graph, so `model_tables[].joins` is emitted empty | Add joins by hand, or supply them via `--overrides`; engine-artifacts mode records associations as info notes |
| U5 | Chart types with no ThoughtSpot equivalent | Defaulted to a grid table | Flagged; pick a chart type after import |
| U6 | Alternate dimensions, calculated dimensions, and complex in-chart expressions | Only the primary dimensions/measures drive the Answer's search query | Flag + rebuild the visualization in ThoughtSpot |

### Notes on limitations

**U1–U2** are the two structural gaps most likely in a real app — Qlik's selection-state model
(Set Analysis) and variables have no static equivalent in a ThoughtSpot model. Both are surfaced
in the migration report rather than approximated.

**U4** (joins) is the main data-model gap on the offline path: a `.qvf` does not expose a
dependable association graph, so the generated Model binds the tables but leaves joins for the
author to confirm. Promoting a shared `agents/shared/mappings/qlik/` translation reference and
recovering associations from engine-artifacts mode are tracked in `open-items.md`.
