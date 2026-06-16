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
- `ADVANCED_*` are the newer chart-engine variants of the classic types; the classic names
  still import and are the safer default.
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
