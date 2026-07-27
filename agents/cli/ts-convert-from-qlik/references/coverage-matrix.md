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
| 14 | 199-row Qlik→ThoughtSpot function map (`ts_cli/qlik/data/`) | Mapped per row; unmapped functions flagged (see below) | Loaded by `ts qlik build-model` |

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
| U3 | Functions with no ThoughtSpot equivalent (`subfield`, `networkdays`, `rangesum`, `mode`, …) | No native function; not in the translation map | Flagged unmapped; author a manual formula |
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
