# Step 10 — Liveboard Generation Detail

Reference detail for **Step 10 — Generate Liveboard TML**: the full KPI viz template, the
per-encoding `search_query`-building rule set (10b), and the liveboard TML template (10c).
The step's spine (which command to run, the decision points, and the critical gotchas) stays
in `SKILL.md` — this file is what the spine links out to for the full rule/template detail.

---

## KPI viz template (Step 10a)

Full KPI viz template (substitute column names, UUIDs, and colors). Requires
`kpiDisplayProperties` at the chart level (`showChange`, `showChangeAs: "PERCENT"`),
per-column `kpiColumnProperties` with `showSparkline: true` on **both** the date and measure
columns, `axisProperties` with fresh UUIDs (`python3 -c "import uuid; print(uuid.uuid4())"`),
and optional `seriesColors` to match the chosen theme palette. See
`thoughtspot-liveboard-tml.md` "KPI sparkline `client_state_v2`" for the verified template
this mirrors.

```yaml
chart:
  type: KPI
  chart_columns:
  - column_id: "{ResolvedMeasure}"
  - column_id: "{ResolvedDate}"
  axis_configs:
  - x:
    - "{ResolvedDate}"
    y:
    - "{ResolvedMeasure}"
  client_state: ""
  client_state_v2: >-
    {"version": "V4DOT2",
     "chartProperties": {"gridLines": {}, "responsiveLayoutPreference": "USER_PREFERRED_ON",
       "chartSpecific": {"dataFieldArea": "column"},
       "kpiDisplayProperties": {"showChange": true, "showChangeAs": "PERCENT",
         "changeInterpretation": "UPWARD_IS_GOOD", "linkChangeColorsWithAnomaly": true}},
     "columnProperties": [
       {"columnId": "{ResolvedDate}", "columnProperty": {"kpiColumnProperties":
         {"showAbbreviatedPreviousDate": false, "showSparkline": true,
          "showComparisonDate": true, "showCurrentDateLabel": true,
          "showPreviousDateLabel": true, "showPreviousValue": true}}},
       {"columnId": "{ResolvedMeasure}", "columnProperty": {"kpiColumnProperties":
         {"showAbbreviatedPreviousDate": false, "showSparkline": true,
          "showComparisonDate": true, "showCurrentDateLabel": true,
          "showPreviousDateLabel": true, "showPreviousValue": true}}}],
     "axisProperties": [
       {"id": "{uuid1}", "properties": {"axisType": "Y", "linkedColumns": ["{ResolvedMeasure}"], "isOpposite": false}},
       {"id": "{uuid2}", "properties": {"axisType": "X", "linkedColumns": ["{ResolvedDate}"]}}],
     "seriesColors": [{"serieName": "{ResolvedMeasure}", "color": "{hex}"}]}
  viz_style: '{"overrides": {"column_properties": [{"column_id": "{ResolvedMeasure}", "properties": {"color": "{hex}"}}]}}'
table:
  table_columns:
  - column_id: "{ResolvedMeasure}"
    headline_aggregation: SUM
  - column_id: "{ResolvedDate}"
    headline_aggregation: MIN-MAX
  ordered_column_ids:
  - "{ResolvedDate}"
  - "{ResolvedMeasure}"
  client_state: ""
  client_state_v2: >-
    {"tableVizPropVersion": "V1",
     "columnProperties": [
       {"columnId": "{ResolvedDate}", "columnProperty": {}},
       {"columnId": "{ResolvedMeasure}", "columnProperty": {}}]}
```

---

## Build search queries — per-encoding rule set (Step 10b)

`search_query` is a ThoughtSpot search string of **bracketed column display names**, not
a "sum sales" phrase. Build it from the worksheet shelves:

- Reference each measure by its model column name: `[Total Revenue]` — the column's own
  default aggregation applies; do **not** prepend `sum`.
- Reference each dimension/attribute by name: `[Sales Channel]`.
- Date on a shelf → **dotted** bucket from the TWB `datetrunc`/`datepart`:
  `[Ship Date].yearly`, `[Order Date].monthly`. A bare `monthly` token is rejected.
- Top-N (Tableau Top filter) → append `top N`, e.g. `[Item Type] [Total Revenue] top 5`.
- **Sort fidelity.** Carry the worksheet's sort. A Tableau **Top/Bottom-N** sort → the `top N`
  / `bottom N` keyword above. A plain **descending/ascending sort on a measure** → append
  `sorted by [Measure] descending` / `ascending` to the `search_query` (`top N` already
  implies a descending sort, so don't stack both; confirm the token renders as expected on
  your build — see open item #19). A manual (hand-ordered) sort has no search equivalent —
  note it as a minor migration gap.
- **Column display format (currency / number / percent).** Carry the Tableau column's number
  format so a tile reads like the source — `$1,240`, `12.3%`, `1.2K` — not a raw `1240` /
  `0.123`. Set `format` on the measure's `answer_columns[]` entry:
  - **Percent** — a contribution / percent-of-total / growth-rate measure (detect from the
    formula: `/ TOTAL(...)`, `/ {FIXED ...}`, `growth of`, `pcdf`, or the Tableau column's own
    `%` format) → `category: PERCENTAGE`, `percentageFormatConfig.decimals`. **Verified** —
    see `../../../shared/schemas/thoughtspot-answer-tml.md` "answer_columns[] fields".
  - **Currency** — Tableau format is a currency (`$`, `€`, custom currency string) →
    `category: CURRENCY` with the parallel `currencyFormatConfig` (currency code + decimals).
  - **Plain number** — thousands separator, fixed decimals, or a K/M/B unit →
    `category: NUMBER` with the parallel `numberFormatConfig` (decimals, thousands separator,
    negative-value form).
  Map the Tableau `<format>`'s decimal count and separators across. **Caveat:** only the
  PERCENTAGE shape is live-verified in the schema; confirm the exact `currencyFormatConfig` /
  `numberFormatConfig` field names against a live export before relying on them (tracked as an
  open item) — when unsure, ship the numeric measure unformatted rather than an invalid
  `format` block that could fail the import.
- **Color / series fidelity.** Carry the worksheet's Color shelf (9b) into the chart encoding,
  don't drop it:
  - **Muze path** — a dimension on the Color shelf → the **`slice-with-color`** shelf of
    `custom_chart_config` (series/color split); a **row/column small-multiples** (trellis)
    encoding → the **`trellis-by`** shelf. This is the faithful mapping (see
    `../../../shared/schemas/thoughtspot-chart-types.md` "Tableau alignment").
  - **Legacy path** — a color dimension becomes a **second column in `chart_columns`**
    (implicit series); small multiples are **not expressible** on Legacy — note the gap.
  - **Specific series colors** — when the Tableau color palette is meaningful (brand hues,
    a fixed category→color map), carry it into the tile's `viz_style` per-series palette
    (same mechanism Step 10.5 themes use), rather than letting ThoughtSpot auto-assign.
- **Cumulative / moving measures** → reference the **measure column** by name with the
  worksheet's shelf attribute as the trailing sort arg: `cumulative_sum ( [Sales] , [Month] )`,
  `moving_average ( [Sales] , 2 , 0 , [Order Date] )` — these are **answer-level** formulas (not
  model columns). See `tableau-formula-translation.md` Running/Moving sections.
- **Growth / decline.** Two cases — read the worksheet's actual filters/table-calc to choose:
  - **A trend of growth over time** (`pcdf` with no Top-N, every period shown) → the
    `growth of` keyword: supply the bare date *and* its bucket, `growth of [Measure] by [Date]
    [Date].yearly [dim]` (default is **monthly**, so set `.yearly` for annual; dotted-only
    `by [Date].yearly` fails to tokenize). Resolved columns: `Growth of Total {Measure}` +
    `{Bucket}(Date)` — bind chart columns to those (export-patch).
  - **"Top/bottom N by growth over a window"** (`pcdf` **plus a Top-N filter + a recent-N-years
    filter** — e.g. "highest growth in past 5 years") → a **period-comparison**, best built as
    **answer-level formulas** on that one viz (it's viz-specific):
    ```yaml
    formulas:
    - id: formula_Val Start   # FDI in the start year
      expr: "group_aggregate ( sum ( [Measure] ) , query_groups () , query_filters () + { year_name ( [Date] ) = '2012' } )"
    - id: formula_Val End     # FDI in the end year
      expr: "group_aggregate ( sum ( [Measure] ) , query_groups () , query_filters () + { year_name ( [Date] ) = '2016' } )"
    - id: formula_Growth
      expr: "( [formula_Val End] - [formula_Val Start] ) / [formula_Val Start]"
    # search_query: "[Sector] [formula_Growth] top 5 by [formula_Growth]"   (bottom 5 = decline)
    ```
    Anchor years: **dynamic vs the actual data range matters.** `max([Date])` is **not allowed
    inside a formula filter** (`"Search did not find max("`), so you can't compute the data's
    latest year in-formula. Options: (a) **dynamic** via `currentdate()` —
    `year ([Date]) = year ( currentdate () )` and `… - 5` — correct for **live/refreshing**
    data, but returns **nothing** if the data is historical (e.g. ends 2016 while "today" is
    2026); (b) **anchor to the data's real bounds** (latest year and latest−5) when the
    dataset is static — functional, matches the "past 5 years" intent. Choose by whether the
    source refreshes; if unsure, **ask the user**. Format `Growth` as a percentage. This is the
    faithful translation of the `pcdf` + Top-N + window pattern — not a raw `growth of` line.
- A formula used by only this one viz can be an **answer-level formula** (`answer.formulas[]`
  + an `answer_columns[]` entry) rather than a model formula — see Step 5b.
- Calculated fields: translate the Tableau caption to the ThoughtSpot formula name via
  `{formula_column_map}`.

---

## Liveboard TML template (Step 10c)

The YAML below is the **reference for what the `ts tableau build-liveboard` command emits**
(and the shape to match when hand-tuning an `override`). Follow
`../../../shared/schemas/thoughtspot-liveboard-tml.md` exactly — the structure below is what
actually imports and renders (an earlier `fqn`-based, minimal-chart form did not).

```yaml
liveboard:
  name: Dashboard Name
  description: "Migrated from Tableau workbook"
  visualizations:
  - id: Viz_1
    answer:
      name: Worksheet Name
      tables:
      - id: "Model Name"
        name: "Model Name"
        obj_id: "{model_obj_id}"            # the model's REAL obj_id from Step 10-pre (NOT the one you wrote into the model TML, NOT fqn — a viz-level fqn is dropped on import)
      search_query: "[Sales Channel] [Total Revenue]"
      answer_columns:                         # RESOLVED names (see below)
      - name: Sales Channel
      - name: Total Total Revenue
      chart:                                  # complete block, or omit entirely
        type: PIE
        chart_columns:
        - column_id: Sales Channel
        - column_id: Total Total Revenue
        axis_configs:
        - x: [Sales Channel]
          y: [Total Total Revenue]
      display_mode: CHART_MODE
  - id: Note_1                                # Tableau text / title zone → note tile
    note_tile:
      html_parsed_string: |-
        <p><strong>Title text</strong></p>
        <p>Body text from the Tableau text zone.</p>
  layout:
    tiles:
    - visualization_id: Viz_1
      x: 0
      y: 0
      height: 6
      width: 8
    - visualization_id: Note_1
      x: 8
      y: 0
      height: 6
      width: 4
```
