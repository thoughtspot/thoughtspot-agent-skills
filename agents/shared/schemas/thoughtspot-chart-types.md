# ThoughtSpot Chart Types — verified enum + intent mapping

_Verified live on se-thoughtspot 2026-06-16 against model `P1-UK-Bank-Customers`
(liveboard `5db36c15-00a5-45bb-b764-2fffd2fcb269`). The enum was read from the import
validator's own error message (the authoritative source), and 24 types were imported +
round-tripped to confirm they bind._

## The authoritative `answer.chart.type` enum (44 values)

```
ADVANCED_AREA, ADVANCED_BAR, ADVANCED_COLUMN, ADVANCED_LINE, ADVANCED_LINE_COLUMN,
ADVANCED_LINE_STACKED_COLUMN, ADVANCED_PIVOT_TABLE, ADVANCED_STACKED_AREA,
ADVANCED_STACKED_BAR, ADVANCED_STACKED_COLUMN, AREA, BAR, BUBBLE, CANDLESTICK, COLUMN,
CUSTOM_CHART, FUNNEL, GEO_AREA, GEO_BUBBLE, GEO_EARTH_AREA, GEO_EARTH_BAR,
GEO_EARTH_BUBBLE, GEO_EARTH_GRAPH, GEO_EARTH_HEATMAP, GEO_HEATMAP, GRID_TABLE, HEATMAP,
KPI, LINE, LINE_COLUMN, LINE_STACKED_COLUMN, MUZE_STUDIO, PARETO, PIE, PIVOT_TABLE,
SANKEY, SCATTER, SPIDER_WEB, STACKED_AREA, STACKED_BAR, STACKED_COLUMN, TREEMAP,
WATERFALL, WHISKER_SCATTER
```

- **`GAUGE` is NOT a valid type** — it was rejected, and one bad enum value fails the
  whole import (even under `--policy PARTIAL`). Validate the type before import.
- `TABLE` is not in the enum. For a tabular tile, **omit the `chart` block and set
  `display_mode: TABLE_MODE`** (the export then shows a default `chart.type` but renders as
  a table). `GRID_TABLE` / `PIVOT_TABLE` are the chart-engine table types.
- `ADVANCED_*` are the **new charting library** (early access — see the dedicated section
  below). They use a different encoding block (`custom_chart_config`, not `axis_configs`).
  The classic names are the portable default; emit `ADVANCED_*` only when targeting a cluster
  with the new library enabled.
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

## New charting library (`ADVANCED_*`) — early access

ThoughtSpot is rolling out a new charting library, the **`ADVANCED_*`** chart family
(`ADVANCED_COLUMN`, `ADVANCED_BAR`, `ADVANCED_LINE`, `ADVANCED_AREA`, `ADVANCED_STACKED_*`,
`ADVANCED_LINE_COLUMN`, `ADVANCED_LINE_STACKED_COLUMN`, `ADVANCED_PIVOT_TABLE`). It is
**early access** — enabled on the SE cluster (`se-thoughtspot`), not yet GA. _All findings
below verified live on se-thoughtspot 2026-06-17._

### Scope — which types the advanced library covers

The `ADVANCED_*` family is currently **only the cartesian + pivot types** (10 of them):

```
ADVANCED_COLUMN  ADVANCED_BAR  ADVANCED_LINE  ADVANCED_AREA
ADVANCED_STACKED_COLUMN  ADVANCED_STACKED_BAR  ADVANCED_STACKED_AREA
ADVANCED_LINE_COLUMN  ADVANCED_LINE_STACKED_COLUMN  ADVANCED_PIVOT_TABLE
```

There is **no** `ADVANCED_SCATTER`, `ADVANCED_PIE`, `ADVANCED_HEATMAP`, `ADVANCED_SANKEY`,
etc. So advanced charting applies to bar/line/area/column/combo/pivot migrations; every other
intent (composition, correlation, flow, geo, distribution, funnel, …) stays on the standard
types.

The classic and advanced types map 1:1 by intent (`COLUMN` ↔ `ADVANCED_COLUMN`, etc.). The
important difference is **how the encoding (which column goes on which shelf) is expressed**:

| | Standard chart (`COLUMN`, `BAR`, …) | Advanced chart (`ADVANCED_*`) |
|---|---|---|
| Encoding block | `chart.axis_configs` (`x: […]`, `y: […]`) | `chart.custom_chart_config` (shelf model) |
| Series / color | a second column in `chart_columns` | the **`slice-with-color`** shelf |
| Small multiples / faceting | not expressible | the **`trellis-by`** shelf |

### `custom_chart_config` — the advanced encoding shelf model

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

### Tableau alignment — why advanced is a closer migration target

The shelf model maps almost 1:1 onto Tableau's encoding shelves, so a Tableau viz that uses
Color or small-multiples migrates more faithfully to one advanced chart than to a standard
chart (where a second dimension is an implicit extra column):

| Tableau shelf | Advanced shelf | Standard-chart equivalent |
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
  and **auto-resolve** which measure is the line vs the column; no `custom_chart_config`
  required. Fine-grained line/column + secondary-axis control lives in `client_state_v2`
  `axisProperties` (`axisType: Y`, `isOpposite: true` for the secondary axis).
- **The shelf vocabulary is permissive, not strictly validated.** An unknown shelf key (e.g.
  `size`) on a cartesian type is *accepted and retained* but ignored at render — so don't rely
  on rejection to validate; only the four cartesian shelves above actually render.

### Verified rules (live on se-thoughtspot)

- **Don't put `custom_chart_config` on a standard type.** A standard type (`COLUMN`) with a
  `custom_chart_config` is rejected: *"Switching from advanced charts to standard charts
  through TML is not supported."* One such viz **fails the whole import**.
- **Advanced type + `axis_configs`** is accepted, but on export ThoughtSpot drops it and
  stores neither block (it auto-resolves a simple x/y advanced chart from `chart_columns`).
- **Advanced type + `custom_chart_config`** round-trips faithfully — including the
  `slice-with-color` and `trellis-by` shelves. This is the canonical form for any advanced
  chart that needs an explicit series or facet.
- So: **standard type → `axis_configs`; advanced type → `custom_chart_config`** (or omit both
  for a trivial x/y advanced chart). Never mix a standard type with `custom_chart_config`.

### Guidance for generators (Tableau skill, liveboard-builder)

- **Default to standard chart types, but PROMPT the user to choose** standard vs the advanced
  library before generating chart TML. Standard is the portable default (works on every
  cluster); advanced is early access (the target cluster must have it enabled — e.g. SE).
- When the user picks **advanced**: emit `ADVANCED_*` + `custom_chart_config` for the
  cartesian/pivot intents (bar/column/line/area/stacked/combo/pivot), and **fall back to the
  standard type** for any intent with no advanced equivalent (pie, scatter/bubble, heatmap,
  treemap, sankey, funnel, waterfall, pareto, spider, geo, candlestick, KPI). Map Tableau's
  Color shelf → `slice-with-color` and small multiples → `trellis-by` for a closer migration.
- The shelf model is also a cleaner fit for the liveboard-builder's intent → encoding step
  (series and small-multiples become first-class shelves rather than implicit extra columns).
- `client_state_v2` differs slightly between the two (the advanced export omits
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
