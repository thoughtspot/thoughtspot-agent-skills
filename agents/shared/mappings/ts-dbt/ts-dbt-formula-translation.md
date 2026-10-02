<!-- currency: dbt — 2026-10 (MetricFlow nested spec, dbt Core 1.12+ / dbt Fusion; manifest dialects of dbt Cloud 2026.9.1 and Fusion local parse seen live 2026-09-08; written 2026-10-02 to give ts-convert-{from,to}-dbt the I7 reference — rows follow ts_cli/dbt_metricflow.py and ts_cli/dbt_build_export.py, which are authoritative) -->
# Formula Translation Reference — dbt

What `ts-convert-from-dbt` and `ts-convert-to-dbt` do with formulas, in both directions.
dbt is unlike the other converters' sources: it has **no formula language of its own**
to translate. Its models are SQL that ThoughtSpot never sees (Tables are generated from
the warehouse relation), so only two things carry calculations across:

1. **`ts_formula`** — ThoughtSpot formula text stored in a column's `config.meta`.
   Carried **verbatim** in both directions; nothing is parsed or rewritten.
2. **MetricFlow metrics** (dbt Semantic Layer) — translated **by metric type and
   aggregation**, not by function name. ThoughtSpot cannot query the Semantic Layer,
   so what carries over is the metric *definition*.

Use **dbt → ThoughtSpot** when running `ts-convert-from-dbt` and **ThoughtSpot → dbt**
when running `ts-convert-to-dbt`. Do not consult the other direction's tables: they
describe a different code path and will mislead.

Every ThoughtSpot function named below is in
[`../../schemas/thoughtspot-formula-patterns.md`](../../schemas/thoughtspot-formula-patterns.md).

---

## dbt → ThoughtSpot (`ts-convert-from-dbt`)

Source: `tools/ts-cli/ts_cli/dbt_metricflow.py` (`_AGG_TO_TS`, `_UNSUPPORTED_AGG`,
`translate_metrics`). Run by `ts dbt build-model` only — `generate-tml` does not
translate metrics.

### `ts_formula` columns

The expression is copied into the Model's `formulas[]` exactly as written, with the
formula id `formula_` + the display name. No translation, so nothing here can be
"untranslatable" — an expression ThoughtSpot rejects was wrong in the dbt project and
is fixed there.

### Simple metrics — aggregation map (`_AGG_TO_TS`)

A simple metric's `agg` on a **bare column name** becomes one aggregate formula over
`[TABLE::COL]`, where `TABLE` is the materialised relation (`alias` or `name`).

| MetricFlow `agg` | ThoughtSpot formula | Status |
|---|---|---|
| `sum` | `sum ( [TABLE::COL] )` | Translated |
| `average` / `avg` | `average ( [TABLE::COL] )` | Translated |
| `min` | `min ( [TABLE::COL] )` | Translated |
| `max` | `max ( [TABLE::COL] )` | Translated |
| `count` | `count ( [TABLE::COL] )` | Translated |
| `count_distinct` | `unique count ( [TABLE::COL] )` | Translated — note the space; `count_distinct` is not a ThoughtSpot function |

### Metric types

| MetricFlow type | ThoughtSpot formula | Status |
|---|---|---|
| `simple` | per the table above | Translated |
| `ratio` | `safe_divide ( [formula_<numerator>] , [formula_<denominator>] )` | Translated when both inputs translated |
| `derived` | the `expr`, each input-metric name or alias replaced by `[formula_<input>]` | Translated when every input translated and no identifier is left over |

Metrics translate simple-first; ratio and derived metrics then resolve against them,
repeating until nothing more resolves, so a derived metric over a ratio works.

### Reported as unmapped — and what to offer instead

`build-model` never guesses and never drops: each of these appears on stderr as
`MetricFlow: metric '<name>' (<type>) NOT translated — <reason>`. **Several have a manual
ThoughtSpot equivalent.** Offer it to the user as a `ts_formula` they can add (and
check it against the catalog) rather than telling them the metric cannot exist in
ThoughtSpot.

| Construct (reason in the report) | Manual ThoughtSpot equivalent | Notes |
|---|---|---|
| `agg: median` ("ThoughtSpot has no median aggregate") | `median ( [TABLE::COL] )` | The *column* aggregation keyword has no median, but the formula function exists. Not yet emitted automatically. |
| `agg: percentile` | — | No percentile aggregate or formula function. Genuinely untranslatable. |
| `agg: sum_boolean` | `sum ( if ( [TABLE::COL] ) then 1 else 0 )` | Counts true rows. `if` needs its parentheses for TML import. |
| metric-level `filter` on a simple metric | `sum_if ( <condition> , [TABLE::COL] )` (or `count_if`, `average_if`, `unique_count_if`) | The MetricFlow filter is Jinja (`{{ Dimension('entity__dim') }} = 'x'`); rewrite the condition with `[TABLE::COL]` refs by hand. |
| `filter` on a ratio/derived input metric | translate the input as a filtered simple metric (row above), then reference it | |
| SQL-expression `expr` (not a bare column) | rewrite the SQL as a ThoughtSpot formula by hand | `CASE WHEN` → `if ( … ) then … else …`; check every function in the catalog — several common SQL string functions do not exist in ThoughtSpot. |
| `cumulative` | `cumulative_sum ( <measure> , [TABLE::DATE_COL] )` (or `cumulative_average` / `_min` / `_max`) | Unbounded running total only. A `window` or `grain_to_date` has no exact equivalent — `moving_sum` is a fixed-row window, not a time window. |
| `offset_window` / `offset_to_grain` on an input | — | No period-offset input in ThoughtSpot formulas. Untranslatable as a metric; ThoughtSpot search keywords (`last year`, `growth of`) answer the question at query time. |
| `conversion` | — | No funnel/conversion construct. Untranslatable. |

---

## ThoughtSpot → dbt (`ts-convert-to-dbt`)

Source: `tools/ts-cli/ts_cli/dbt_build_export.py` (`_classify_model_columns`,
`_build_legacy_measures_and_metrics`) and `tools/ts-cli/ts_cli/dbt/tags.py` (`_AGG_MAP`).

### Formula columns → `ts_formula`

Nothing is translated to SQL. Each Model formula is written **verbatim** as
`ts_formula` on the dbt column under the **first `[TABLE::COL]` reference** in its
expression, and restored verbatim by `ts-convert-from-dbt`. So a ThoughtSpot formula
never fails to "translate" here — the only skip is structural:

| Formula | Result |
|---|---|
| has a `[TABLE::COL]` reference | written as `ts_formula` on that table's model — round-trips exactly |
| references only other formulas or parameters (no `[TABLE::COL]`) | reported in `skipped_formulas`; nowhere to attach it in `schema.yml`. Tell the user — never drop it silently. |

### Column aggregation → `ts_aggregation` (schema.yml)

The Model column's `aggregation` is written lowercased as `ts_aggregation` and read back
through `_AGG_MAP`: `sum`, `count`, `count_distinct`, `min`, `max`, `average`,
`std_deviation`, `variance`, `none`. Round-trips exactly — these are ThoughtSpot tag
values, not MetricFlow syntax.

### Column aggregation → MetricFlow `agg` (`--semantic-models` only)

The opt-in `semantic_models.yml` lowercases the same aggregation into a MetricFlow
measure `agg`:

| ThoughtSpot aggregation | MetricFlow `agg` | Valid MetricFlow? |
|---|---|---|
| `SUM` / `COUNT` / `MIN` / `MAX` / `AVERAGE` / `COUNT_DISTINCT` | `sum` / `count` / `min` / `max` / `average` / `count_distinct` | Yes — each parses under dbt-core 1.12.5 (tested 2026-10-02) |
| (none set) | `sum` | Yes (default) |
| `STD_DEVIATION` / `VARIANCE` / `NONE` | `std_deviation` / `variance` / `none` | **No** — dbt-core 1.12.5 `dbt parse` rejects each with `Invalid enum value … in enum AggregationType`, exactly as it rejects a nonsense control value (tested 2026-10-02). dbt Fusion 2.0.6 accepts them, but it accepts the nonsense value too — it does not validate the legacy spec. Known gap, see ts-convert-to-dbt open-items #2. Remove those measures by hand or omit `--semantic-models`. |

Formula columns are **not** written to `semantic_models.yml` as metrics — they live
only as `ts_formula` in `schema.yml`.
