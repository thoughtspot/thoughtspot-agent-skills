# Worked Example — Tableau KPI Worksheet → ThoughtSpot KPI Viz with Sparkline

End-to-end conversion of a Tableau "KPI's" worksheet (Measure Names / Measure Values
scorecard) into ThoughtSpot KPI liveboard tiles with sparkline trend lines. Verified
against a live ThoughtSpot instance (2026-06-11).

This example documents the `client_state_v2` requirement that is easy to miss: a KPI
viz imported without it renders as a plain number — no sparkline, no comparison, no
change indicator.

---

## Input — Tableau Worksheet (from TWB XML)

Workbook: `Analyzing Amazon Sales data.twb`
Worksheet: `KPI's`

```xml
<worksheet name="KPI's">
  <table>
    <view>
      <datasource caption="Amazon Sales data"
                  name="federated.0fe1kgi0xnq78p17wifi41j35mvm" />
    </view>
    <!-- Cols: Measure Names -->
    <!-- Measure filter: Units Sold, Total Revenue, Total Profit -->
    <!-- Dashboard filter zones: Ship Date (year), Region (top 5), Item Type (top 5) -->
  </table>
</worksheet>
```

**Shelf analysis:**
- Cols: `[:Measure Names]` — three measures filtered via categorical filter
- Measures: `[sum:Units Sold:qk]`, `[sum:Total Revenue:qk]`, `[sum:Total Profit:qk]`
- Mark class: `Automatic`
- No Rows dimension — this is a scorecard, not a chart
- Dashboard filter: `[yr:Ship Date:ok]` — year-level date filter

**Translation decision:** One KPI tile per measure. Include `[Ship Date].yearly` for the
sparkline trend (the dashboard has a year-level date filter, and the data is annual).

---

## ThoughtSpot Model

```yaml
model:
  name: Amazon Sales Data
  # guid: 838eac1d-8734-4fd3-8ace-6021bc01fb28
  model_tables:
  - name: AMAZON_SALES_DATA
  columns:
  - name: Ship Date
    column_id: AMAZON_SALES_DATA::SHIP_DATE
    properties:
      column_type: ATTRIBUTE
  - name: Units Sold
    column_id: AMAZON_SALES_DATA::UNITS_SOLD
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Total Revenue
    column_id: AMAZON_SALES_DATA::TOTAL_REVENUE
    properties:
      column_type: MEASURE
      aggregation: SUM
  - name: Total Profit
    column_id: AMAZON_SALES_DATA::TOTAL_PROFIT
    properties:
      column_type: MEASURE
      aggregation: SUM
  # (other columns omitted for brevity)
```

`obj_id`: `AmazonSalesData-838eac1d`

---

## Output — What FAILS (no sparkline)

A KPI viz with only the structural `chart:` block — no `client_state_v2`, no `table:`
block. This imports successfully (status OK) but renders as a **plain number** with no
sparkline trend line, no period-over-period comparison, and no change indicator.

```yaml
- id: Viz_KPI_UnitsSold
  answer:
    name: "Units Sold"
    tables:
    - id: "Amazon Sales Data"
      name: "Amazon Sales Data"
      obj_id: AmazonSalesData-838eac1d
    search_query: "[Units Sold] [Ship Date].yearly"
    answer_columns:
    - name: "Total Units Sold"
    - name: "Year(Ship Date)"
    display_mode: CHART_MODE
    chart:
      type: KPI
      chart_columns:
      - column_id: "Total Units Sold"
      - column_id: "Year(Ship Date)"
      axis_configs:
      - x:
        - "Year(Ship Date)"
        y:
        - "Total Units Sold"
```

**Result:** KPI headline number only. No sparkline. No "vs previous period" comparison.

---

## Output — What WORKS (sparkline renders)

The same KPI viz with `client_state_v2` on the `chart:` block (containing
`showSparkline: true`) and a `table:` block. Exported from ThoughtSpot after manual
correction and re-import — this is the verified, working TML.

```yaml
- id: Viz_1
  answer:
    name: Units Sold
    description: "KPI — total units sold. Source worksheet: KPI's"
    tables:
    - id: Amazon Sales Data
      name: Amazon Sales Data
      obj_id: AmazonSalesData-838eac1d
    search_query: "[Units Sold] [Ship Date].yearly"
    answer_columns:
    - name: Total Units Sold
    - name: Year(Ship Date)
    table:
      table_columns:
      - column_id: Total Units Sold
        headline_aggregation: SUM
      - column_id: Year(Ship Date)
        headline_aggregation: MIN-MAX
      ordered_column_ids:
      - Year(Ship Date)
      - Total Units Sold
      client_state: ""
      client_state_v2: >-
        {"tableVizPropVersion": "V1",
         "columnProperties": [
           {"columnId": "Year(Ship Date)", "columnProperty": {}},
           {"columnId": "Total Units Sold", "columnProperty": {}}]}
    chart:
      type: KPI
      chart_columns:
      - column_id: Total Units Sold
      - column_id: Year(Ship Date)
      axis_configs:
      - x:
        - Year(Ship Date)
        y:
        - Total Units Sold
      client_state: ""
      client_state_v2: >-
        {"version": "V4DOT2",
         "chartProperties": {
           "gridLines": {},
           "responsiveLayoutPreference": "USER_PREFERRED_ON",
           "chartSpecific": {"dataFieldArea": "column"},
           "kpiDisplayProperties": {
             "showChange": true,
             "showChangeAs": "PERCENT",
             "changeInterpretation": "UPWARD_IS_GOOD",
             "linkChangeColorsWithAnomaly": true}},
         "columnProperties": [
           {"columnId": "Year(Ship Date)",
            "columnProperty": {
              "kpiColumnProperties": {
                "showAbbreviatedPreviousDate": false,
                "showSparkline": true,
                "showComparisonDate": true,
                "showCurrentDateLabel": true,
                "showPreviousDateLabel": true,
                "showPreviousValue": true}}},
           {"columnId": "Total Units Sold",
            "columnProperty": {
              "kpiColumnProperties": {
                "showAbbreviatedPreviousDate": false,
                "showSparkline": true,
                "showComparisonDate": true,
                "showCurrentDateLabel": true,
                "showPreviousDateLabel": true,
                "showPreviousValue": true}}}],
         "axisProperties": [
           {"id": "e3cfd9cc-14cb-4696-a015-ff76723fed22",
            "properties": {"axisType": "Y", "linkedColumns": ["Total Units Sold"], "isOpposite": false}},
           {"id": "b0e1f339-8453-47d0-afd4-2f4f4e657a47",
            "properties": {"axisType": "X", "linkedColumns": ["Year(Ship Date)"]}}],
         "seriesColors": [
           {"serieName": "Total Units Sold", "color": "#9b59b6"}]}
      viz_style: >-
        {"overrides": {"column_properties": [
          {"column_id": "Total Units Sold", "properties": {"color": "#9b59b6"}}]}}
    display_mode: CHART_MODE
  viz_guid: 86330351-6235-48e1-90eb-5f4fcb910550
```

**Result:** KPI headline number + sparkline trend line + "vs previous year" comparison
with percentage change. Purple sparkline color from the High Contrast KPIs theme.

---

## What makes the sparkline render

| Element | Required? | What happens without it |
|---|---|---|
| `chart.client_state_v2` with `showSparkline: true` | **Yes** | Plain number, no trend line |
| `kpiDisplayProperties.showChange` | No (but recommended) | No period-over-period change indicator |
| `table:` block with `table_columns` | **Yes** | Import may succeed but viz renders incorrectly |
| `table.client_state_v2` | Recommended | ThoughtSpot may auto-generate, but explicit is safer |
| `axisProperties[].id` (UUIDs) | **Yes** | Generate fresh UUIDs — not references to other objects |
| `viz_style` | No | Sparkline renders in default color; supply to match theme |
| `display_headline_column` | No | ThoughtSpot auto-selects from the measure |

---

## Applying to other measures

The same pattern applies to every KPI tile. Substitute the column names:

| KPI Tile | `{MeasureColumn}` | `{DateColumn}` |
|---|---|---|
| Units Sold | `Total Units Sold` | `Year(Ship Date)` |
| Total Revenue | `Total Total Revenue` | `Year(Ship Date)` |
| Total Profit | `Total Total Profit` | `Year(Ship Date)` |

The `client_state_v2` structure is identical — only `columnId`, `linkedColumns`,
`serieName`, and `axisProperties[].id` UUIDs change.

---

## Style context

This example uses the **High Contrast KPIs** theme:
- KPI tile override: `tile_brand_color: TBC_I`, `tile_kpi_color: TKS_A`, `is_highlighted: 'true'`
- KPI sparkline color: `#9b59b6` (purple — intentional accent against dark tile)
- Board-level: `lb_brand_color: LBC_A`, `lb_border_type: CURVED`, `kpi_hero_font_size: XL`
