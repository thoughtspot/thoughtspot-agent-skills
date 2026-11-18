<!-- currency: thoughtspot — 2026-11 (enum re-read live 2026-11-08 from the import validator on a dev build; library status, limits and 26.9–26.11 features from release notes only, BL-449) -->

# ThoughtSpot Chart Types — verified enum + intent mapping

_First verified live on se-thoughtspot 2026-06-16 against model `P1-UK-Bank-Customers`
(liveboard `5db36c15-00a5-45bb-b764-2fffd2fcb269`): the enum was read from the import
validator's own error message (the authoritative source), and 24 types were imported +
round-tripped to confirm they bind. **Re-read 2026-11-08** (BL-449) the same way on
internal dev builds that report no release version; see "Provenance" below for what that
does and does not prove._

## The authoritative `answer.chart.type` enum (52 values)

```
ADVANCED_AREA, ADVANCED_BAR, ADVANCED_BUBBLE, ADVANCED_CANDLESTICK, ADVANCED_COLUMN,
ADVANCED_DONUT, ADVANCED_FUNNEL, ADVANCED_HEATMAP, ADVANCED_LINE, ADVANCED_LINE_COLUMN,
ADVANCED_LINE_STACKED_COLUMN, ADVANCED_PARETO, ADVANCED_PIVOT_TABLE, ADVANCED_SCATTER,
ADVANCED_STACKED_AREA, ADVANCED_STACKED_BAR, ADVANCED_STACKED_COLUMN, ADVANCED_WATERFALL,
AREA, BAR, BUBBLE, CANDLESTICK, COLUMN, CUSTOM_CHART, FUNNEL, GEO_AREA, GEO_BUBBLE,
GEO_EARTH_AREA, GEO_EARTH_BAR, GEO_EARTH_BUBBLE, GEO_EARTH_GRAPH, GEO_EARTH_HEATMAP,
GEO_HEATMAP, GRID_TABLE, HEATMAP, KPI, LINE, LINE_COLUMN, LINE_STACKED_COLUMN,
MUZE_STUDIO, PARETO, PIE, PIVOT_TABLE, SANKEY, SCATTER, SPIDER_WEB, STACKED_AREA,
STACKED_BAR, STACKED_COLUMN, TREEMAP, WATERFALL, WHISKER_SCATTER
```

`tools/ts-cli/ts_cli/chart_types.py` carries this list as `CHART_TYPE_ENUM`, split into
`RELEASE_BUILD_CHART_TYPES` (the 44 read on a release build) and `DEV_BUILD_CHART_TYPES`
(the 8 added since). `tools/ts-cli/tests/test_chart_types.py` fails when the code and this
block disagree, and when a converter's chart map emits a value outside the release-build
44. Change the code and this block together.

**Provenance.** Method: `ts tml import --policy VALIDATE_ONLY` of an Answer whose
`chart.type` is not a real value; the error (code 14528) lists every allowed value.
VALIDATE_ONLY creates nothing. The builds report no release version, so this is the
enum in **current product code, not in a named release**. A value can be here and still
be rejected by your cluster, and one rejected value fails the whole import. The 44 values
read on 2026-06-16 from the SE demo cluster (a release build) are all still present. The 8
added since are `ADVANCED_*` types (see "Which types the new library covers" below).

- **`GAUGE` is NOT a valid type** — it was rejected, and one bad enum value fails the
  whole import (even under `--policy PARTIAL`). Validate the type before import.
- `TABLE` is not in the enum. For a tabular tile, **omit the `chart` block and set
  `display_mode: TABLE_MODE`** (the export then shows a default `chart.type` but renders as
  a table). `GRID_TABLE` / `PIVOT_TABLE` are the chart-engine table types.
- `ADVANCED_*` are the **new charts library** (Muze). It is GA and the product default
  since 26.7 (release notes). See the dedicated section below. These types use a different
  encoding block (`custom_chart_config`, not `axis_configs`). The plain names are the Legacy
  library. They still import everywhere, but they are no longer what the product draws by
  default.
- `CUSTOM_CHART` / `MUZE_STUDIO` are extension/custom-viz hooks — not general-purpose.
- `GEO_EARTH_*` are the 3-D globe variants of the geo charts.

## Verified-to-bind (24 imported + round-tripped)

| chart.type | columns used | shelf shape | notes |
|---|---|---|---|
| COLUMN | dim + measure | x=dim, y=measure | |
| BAR | dim + measure | x=dim, y=measure | |
| STACKED_COLUMN | 2 dim + measure | x=dim1, series=dim2, y=measure | |
| STACKED_BAR | 2 dim + measure | | |
| LINE | ordered dim + measure | x=date/ordinal, y=measure | |
| AREA | ordered dim + measure | | |
| STACKED_AREA | 2 dim + measure | | |
| LINE_COLUMN | dim + 2 measure | combo (line + column) | |
| PIE | dim + measure | composition | |
| SCATTER | dim + 2 measure | x=meas1, y=meas2 | correlation |
| BUBBLE | dim + 3 measure | x, y, size | correlation + magnitude |
| PARETO | dim + measure | ranked bars + cumulative % | |
| FUNNEL | dim + measure | stage drop-off | |
| WATERFALL | dim + measure | running contribution | |
| HEATMAP | 2 dim + measure | x=dim1, y=dim2, color=measure | |
| TREEMAP | dim + measure | nested rectangles | composition |
| SANKEY | 2 dim + measure | flow dim1→dim2 | |
| SPIDER_WEB | dim + measure | radar | |
| PIVOT_TABLE | 2 dim + measure | rows × cols × measure | |
| GEO_AREA | geo-dim + measure | filled map | needs the dim **geo-tagged**; else empty |
| GEO_BUBBLE | geo-dim + measure | bubble map | needs lat/long or geo config |
| CANDLESTICK | dim + 4 measure | OHLC | needs open/high/low/close-shaped measures |
| TABLE (TABLE_MODE) | columns | — | omit `chart`; `display_mode: TABLE_MODE` |
| KPI | measure (+ date) | headline + sparkline | date drives the trend; see liveboard schema KPI template |

**Caveats observed:** `GEO_AREA`/`GEO_BUBBLE` import structurally but render empty unless the
anchor column is geo-tagged in ThoughtSpot. `CANDLESTICK`/`WHISKER_SCATTER` import but only
render meaningfully with OHLC / distribution-shaped inputs.

**`GEO_BUBBLE` also requires an explicit `chart.axis_configs` block — unlike every other
chart type in this table, a bare `chart_columns` list with no `axis_configs` is not
sufficient and the tile renders empty with no error anywhere.** Live-verified on a Tableau
migration, 2026-10-14: a `GEO_BUBBLE` tile with geo-tagged lat/long columns and a measure, but no
`axis_configs`, imported clean and stayed blank; diffing against a confirmed-working
`GEO_BUBBLE` tile on a different liveboard showed the only structural difference was this
block:
```yaml
chart:
  type: GEO_BUBBLE
  chart_columns:
  - column_id: "{Latitude column}"
  - column_id: "{Longitude column}"
  - column_id: "{Measure column}"
  axis_configs:
  - x:
    - "{Latitude column}"
    - "{Longitude column}"
    y:
    - "{Measure column}"
```
Adding it fixed the render. Treat `GEO_BUBBLE`'s full requirement as three things together,
not any one in isolation: (1) the geo dimension(s) geo-tagged on the model
(`properties.geo_config`), (2) a measure present in `chart_columns`, and (3) this explicit
`axis_configs` block — each was independently verified necessary and none was sufficient
alone.

**The `TABLE` guidance above ("omit `chart`, set `display_mode: TABLE_MODE`") does not
survive a reimport if the tile's existing chart type was a grouping type.** Live-verified on
a Tableau migration, 2026-10-15: a tile whose `chart.type` was `ADVANCED_SCATTER` (with x/y/slice axis grouping) kept
reverting to that exact same `ADVANCED_SCATTER` block on every reimport, even submitted
with `chart` fully omitted each time. If a flat per-row list looks pivoted/grouped and this
doesn't fix it, check first whether a column feeding the table is model-typed `MEASURE` —
it auto-aggregates (per its `aggregation` property) when dropped bare into a table instead
of showing the literal per-row value, which can look identical to a chart-type problem.
Retype to `ATTRIBUTE` if every formula using that column already wraps it in an explicit
aggregate function (so aggregation stays formula-specified, not column-type-driven). If a
genuinely **pivoted/nested-row** table is wanted (a Tableau-style repeat-suppressed grouped
row display), use `ADVANCED_PIVOT_TABLE` instead of fighting `TABLE_MODE` — it auto-resolves
its row/column grouping from `chart_columns` + `search_query` (no `custom_chart_config`
needed) and stuck cleanly on reimport in the same test.

## The new charts library (Muze, `ADVANCED_*` types) — GA, the product default since 26.7

ThoughtSpot has two charting libraries:

- **Legacy** — the original charts. In TML these are the plain type names (`COLUMN`, `BAR`,
  `LINE`, …) with `chart.axis_configs`.
- **New charts library (Muze)** — ThoughtSpot's newer charting engine. In TML these are the
  **`ADVANCED_*`** type names with `chart.custom_chart_config`. _(Note: the TML enum and
  ThoughtSpot's own internal error messages call these "advanced" / the Legacy ones
  "standard". The release notes say "new charts library". **Muze** is the engine's name,
  as in the `MUZE_STUDIO` type. The literal `ADVANCED_*` enum values are unchanged.)_

### Status

| When | What | Source |
|---|---|---|
| 26.6.0.cl | Phase 1 GA: the cartesian + pivot types | release not sourced; the types were verified live on the SE demo cluster, 2026-06-17 |
| 26.7 | GA, and the **product default**; the admin default is instance-wide | release notes only |
| 26.10 | Adds waterfall, pareto, funnel and heatmap | release notes only |
| (not stated) | Also covers donut, scatter and bubble | release notes only |

**Limits** (release notes only): at most **2 axes** and **one slice-by-color attribute**
per chart. A Tableau viz with a third axis, or with two dimensions on Color, does not fit
one new-library chart.

The `newChartsLibrary` property on `SearchViewConfig` / `LiveboardViewConfig` (Visual
Embed SDK) controls enablement in an embed. _The shelf-model findings below were verified
live on se-thoughtspot 2026-06-17 unless dated otherwise._

### Which types the new library covers

18 `ADVANCED_*` types (enum read 2026-11-08). Each has a Legacy twin, which is its name
without the prefix, except `ADVANCED_DONUT`, whose twin is `PIE`. Only DONUT↔PIE comes
from the release notes; the other pairings are inferred from the names:

| `ADVANCED_` + | Legacy twin | Release (per release notes) | Verified live |
|---|---|---|---|
| `COLUMN`, `BAR`, `LINE`, `AREA`, `STACKED_COLUMN`, `STACKED_BAR`, `STACKED_AREA`, `LINE_COLUMN`, `LINE_STACKED_COLUMN`, `PIVOT_TABLE` | same name (inferred) | 26.6.0.cl (phase 1) | enum + import round trip, SE demo cluster (release build), 2026-06 |
| `WATERFALL`, `PARETO`, `FUNNEL`, `HEATMAP` | same name (inferred) | 26.10 | enum, plus a VALIDATE_ONLY import with and without `axis_configs` (both accepted), dev build, 2026-11-08. Not imported or rendered |
| `SCATTER`, `BUBBLE` | same name (inferred) | not stated | as above. Three existing `ADVANCED_SCATTER` Answers on the dev build export a `custom_chart_config` (shelves below) |
| `DONUT` | `PIE` (release notes) | not stated | as above |
| `CANDLESTICK` | `CANDLESTICK` (inferred) | **no release note** | in the enum on a dev build; no release note — do not emit |

These have **no** `ADVANCED_*` twin and stay on Legacy: `TREEMAP`, `SANKEY`, `SPIDER_WEB`,
`WHISKER_SCATTER`, every `GEO_*`, `KPI`, `GRID_TABLE`. (`CUSTOM_CHART` and `MUZE_STUDIO`
are the custom-visual hooks.)

`tools/ts-cli/ts_cli/chart_types.py` holds the twin rule (`legacy_twin()`). The Tableau
generator's cartesian layout and measure floor derive their `ADVANCED_*` members from it.
The axis-encoding lint (`tml_lint.CHART_NEEDS_AXIS`, shared with `ts tml verify-render`)
does **not**. It flags a bare tile of the phase-1 cartesian `ADVANCED_*` types only. The
types added since have not been rendered, and an `ADVANCED_*` tile with neither block
auto-resolves (see "Verified rules" below), so whether a bare one draws blank is unknown.
The same question stands for the phase-1 types the lint already flags.

### Added since 26.9 — release notes only, TML shape not captured

| Release | Feature |
|---|---|
| 26.9 | Gradient legends (Column, Bar, Line-column, Scatter, Bubble, Donut); outline encoding; chart caching |
| 26.10 | Trellis and faceting modes (the `trellis-by` shelf below predates this; how the new modes appear in TML is unverified) |
| 26.11 | Dashed / dotted line styling for future dates; `rules_UNSTABLE` CSS for embedded charts |

None of these were exported or imported here. Capture a real export before emitting any of
them. Until then, a generator should leave them at product defaults.

### Legacy ↔ new library: how the encoding differs

The Legacy and new-library types map 1:1 by intent (`COLUMN` ↔ `ADVANCED_COLUMN`, `PIE` ↔
`ADVANCED_DONUT`, …). The important difference is **how the encoding (which column goes on
which shelf) is expressed**:

| | Legacy chart (`COLUMN`, `BAR`, …) | Muze chart (`ADVANCED_*`) |
|---|---|---|
| Encoding block | `chart.axis_configs` (`x: […]`, `y: […]`) | `chart.custom_chart_config` (shelf model) |
| Series / color | a second column in `chart_columns` | the **`slice-with-color`** shelf |
| Small multiples / faceting | not expressible | the **`trellis-by`** shelf |

### `custom_chart_config` — the Muze encoding shelf model

```yaml
chart:
  type: ADVANCED_STACKED_COLUMN
  chart_columns:
  - column_id: Number of Records
  - column_id: Region
  - column_id: Gender
  custom_chart_config:
  - key: basic
    dimensions:
    - key: x-axis
      axes: [{ type: FLAT, column: Region }]
      mode: AXIS_DRIVEN
    - key: y-axis
      axes: [{ type: FLAT, column: Number of Records }]
      mode: AXIS_DRIVEN
    - key: slice-with-color          # series / color split (empty = no series)
      axes: [{ type: FLAT, column: Gender }]
      mode: AXIS_DRIVEN
    - key: trellis-by                # small-multiples facet (empty = none)
      mode: AXIS_DRIVEN
  display_mode: CHART_MODE
```

Shelf keys (cartesian types): **`x-axis`**, **`y-axis`**, **`slice-with-color`**
(series/color), **`trellis-by`** (facets / small multiples). Each populated shelf carries
`axes: [{type: FLAT, column: <display name>}]` + `mode: AXIS_DRIVEN`; an empty shelf carries
just `mode: AXIS_DRIVEN`. (`type: FLAT` and `mode: AXIS_DRIVEN` are the only values observed.)

`ADVANCED_SCATTER` (read-only export of three existing Answers, dev build, 2026-11-08) uses
**`x-axis`**, **`y-axis`**, **`slice`** and **`slice-with-color`**, and has no `trellis-by`.
Those exports reference columns by display name, not GUID. That differs from the combo
finding below, and nothing here establishes which form a fresh import accepts, so the
capture-and-replay rule stands. A display-name export like these also cannot be replayed
through the converters: `build_answer_explicit` (`tools/ts-cli/ts_cli/tableau/liveboard.py`)
drops any `custom_chart_config` whose column references are not all GUIDs. The shelves of
the other added types have not been read.

### Tableau alignment — why Muze is a closer migration target

The shelf model maps almost 1:1 onto Tableau's encoding shelves, so a Tableau viz that uses
Color or small-multiples migrates more faithfully to one Muze chart than to a Legacy chart
(where a second dimension is an implicit extra column):

| Tableau shelf | Muze shelf | Legacy-chart equivalent |
|---|---|---|
| Columns | `x-axis` | `axis_configs.x` |
| Rows | `y-axis` | `axis_configs.y` |
| Color | `slice-with-color` | a 2nd column in `chart_columns` (implicit) |
| small multiples (row/col trellis) | `trellis-by` | **not expressible** |

Example: a Tableau bar of customers by Region, colored by Gender → one
`ADVANCED_STACKED_COLUMN` with `x-axis: Region`, `y-axis: Number of Records`,
`slice-with-color: Gender`.

### Per-type behavior (verified live)

- **Cartesian shelves** (`x-axis`/`y-axis`/`slice-with-color`/`trellis-by`) apply to COLUMN,
  BAR, LINE, AREA and their STACKED forms. `trellis-by` round-trips faithfully.
- **`ADVANCED_PIVOT_TABLE`** does **not** use `custom_chart_config` — it auto-resolves
  rows/columns/values from `chart_columns` + `search_query` (the block is dropped on export).
- **Combos** (`ADVANCED_LINE_COLUMN`, `ADVANCED_LINE_STACKED_COLUMN`) accept two+ measures
  and **auto-resolve** which measure is the line vs the column — emit the type + measures +
  `axis_configs` (by display name) and it renders as a combo. This is the fresh-import path.

  > **`custom_chart_config` is capture-and-replay only — do NOT hand-author it.** Its
  > `axes[].column`/`axes[].columns` reference columns by **GUID** (assigned when an answer is
  > created), so a fresh import with display names errors `Invalid GUID string: <name>`
  > (live-verified on ps-internal 2026-07-15; `ts tml lint` does NOT catch it — only a real /
  > VALIDATE_ONLY import does). To pin an exact line-vs-column split + dual axis: import the
  > auto-resolved combo, set it in the UI, **export** (the exported `custom_chart_config` now
  > has real GUIDs in `y-axis-column`/`y-axis-line`, `type: MERGED`), and replay that exported
  > config. `client_state_v2` is not durable for the split (re-derived on render); the
  > exported GUID-based `custom_chart_config` is. Per-column format lives on
  > `answer_columns[].format`. Worked example:
  > `worked-examples/tableau/combo-dual-axis-custom-chart-config.md`.
- **The shelf vocabulary is permissive, not strictly validated.** An unknown shelf key (e.g.
  `size`) on a cartesian type is *accepted and retained* but ignored at render — so don't rely
  on rejection to validate; only the four cartesian shelves above actually render.

### Verified rules (live on se-thoughtspot)

- **Don't put `custom_chart_config` on a Legacy type.** A Legacy type (`COLUMN`) with a
  `custom_chart_config` is rejected — ThoughtSpot's verbatim error: *"Switching from advanced
  charts to standard charts through TML is not supported."* One such viz **fails the whole
  import**.
- **Muze type (`ADVANCED_*`) + `axis_configs`** is accepted, but on export ThoughtSpot drops
  it and stores neither block (it auto-resolves a simple x/y Muze chart from `chart_columns`).
- **Muze type + `custom_chart_config`** round-trips faithfully — including the
  `slice-with-color` and `trellis-by` shelves. This is the canonical form for any Muze chart
  that needs an explicit series or facet.
- So: **Legacy type → `axis_configs`; Muze type → `custom_chart_config`** (or omit both for a
  trivial x/y Muze chart). Never mix a Legacy type with `custom_chart_config`.

### Guidance for generators (Tableau skill, liveboard-builder)

- **The new library is the product default (26.7+), so a Legacy tile is now an opt-out,
  not a neutral default.** The repo's generators still emit Legacy names by default (the
  Tableau skill asks, Legacy first). Two things hold the switch back (BL-449):
  1. The added types are verified only in a dev build's enum, whose release cannot be
     read. Emitting one into a cluster on an earlier release fails the **whole** import.
  2. `ADVANCED_*` + `axis_configs` loses the encoding on export (below), so a Tableau Color
     split survives only through a captured `custom_chart_config`. Render fidelity of the
     default path has not been checked.

  Read the enum on a release build that reports its version, then flip the default.
- When the user picks the **new library**: emit `ADVANCED_*` for the phase-1
  cartesian/pivot intents (bar/column/line/area/stacked/combo/pivot), and **keep the Legacy
  type** for everything else: pie, scatter/bubble, heatmap, treemap, sankey, funnel,
  waterfall, pareto, spider, geo, candlestick, KPI. Waterfall, pareto, funnel, heatmap,
  donut, scatter and bubble now have `ADVANCED_*` twins, but those stay unused until
  verified on a named release. Map Tableau's Color shelf → `slice-with-color` and small
  multiples → `trellis-by` for a closer migration. Respect the limits: at most 2 axes and
  one slice-by-color attribute.
- The shelf model is also a cleaner fit for the liveboard-builder's intent → encoding step
  (series and small-multiples become first-class shelves rather than implicit extra columns).
- `client_state_v2` differs slightly between the two (the Muze export omits
  `responsiveLayoutPreference` and trims some `kpiColumnProperties`/`systemSeriesColors`
  defaults) — these are cosmetic defaults, not required for a valid import.

## Analytical intent → chart type (recommendation mapping)

Used by the liveboard-builder recommendation engine and the Tableau skill's Step 10a.

| Analytical intent | First choice | Alternatives |
|---|---|---|
| Headline metric / single number | KPI | — |
| Trend over time | LINE | AREA, LINE_COLUMN (2 measures) |
| Composition / part-to-whole | PIE (≤6 parts) | TREEMAP, STACKED_COLUMN, WATERFALL |
| Ranking (top/bottom N) | BAR | PARETO (with cumulative %) |
| Distribution across bands | COLUMN | HEATMAP (2-D) |
| Comparison across categories | COLUMN / BAR | STACKED_* (with a second dim) |
| Correlation between measures | SCATTER | BUBBLE (3rd measure = size) |
| Two dimensions × one measure | HEATMAP | PIVOT_TABLE, STACKED_* |
| Flow / transition between entities | SANKEY | — |
| Multi-metric profile of one entity | SPIDER_WEB | — |
| Stage conversion / drop-off | FUNNEL | — |
| Geographic distribution | GEO_AREA (regions) | GEO_BUBBLE (points); needs geo-tagged column |
| Detailed records / cross-tab | TABLE_MODE | PIVOT_TABLE |
