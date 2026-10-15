# Step 10 — Liveboard Generation Detail

Reference detail for **Step 9 — Parse Dashboard Layout** and **Step 10 — Generate Liveboard
TML**: the zone-extraction field table, the full KPI viz template, the per-encoding
`search_query`-building rule set (10b), and the liveboard TML template (10c). The steps'
spine (which command to run, the decision points, and the critical gotchas) stays in
`SKILL.md` — this file is what the spine links out to for the full rule/template detail.

---

## Zone extraction field reference (Step 9a)

For each leaf zone found by walking `<dashboard>` → `<zones>` → `<zone>` recursively,
extract:

| Field | Source |
|---|---|
| `zone_id` | `id` attribute |
| `zone_type` | `type` attribute (`text`, `title`, `viz`, `bitmap`, `web`, `extension`, `metric`) |
| `worksheet_name` | `name` attribute (for `viz` zones) |
| `x`, `y`, `w`, `h` | `x`, `y`, `w`, `h` attributes (Tableau uses 0–100,000 coordinate space) |
| `text_content` | `<formatted-text>` child text (for `text` / `title` zones) |
| `parent_zone` + `param` | the enclosing `<zone>`'s `id` and its `param` (`vert` = vertical container / stacks children top-to-bottom; `horz` = horizontal container / places children left-to-right). **Keep the nesting** — don't flatten to a coordinate list; the container tree is the layout's real structure (9c). |
| `floating` | `floating="true"` on the zone — a free-positioned overlay, not part of a container. Handle separately in 9c. |

### Title/subtitle zones that signal a dropped dashboard action (Step 9a)

If a `title`/`text` zone's `text_content` displays **per-record identifying attributes**
(e.g. `"08-Jul-2026 | Flight Number: GE0299 | Tail: GE-5361 | SID: RNG2B | STAR: SNT7U"`)
rather than a generic dashboard label, that's the visible signature of a Tableau
**dashboard action** — click a mark on one sheet to filter another to that one record.
This pipeline doesn't parse `<actions>` elements, so the action itself is silently
dropped. Without it, the tiles that were meant to be scoped by the click instead query
the full unfiltered dataset and render a meaningless slice — live-verified on a GE
Aerospace workbook: a per-waypoint chart rendered ~20 arbitrary rows out of 1.5M instead
of one flight's ~30-80 waypoints in sequence.

**Fix:** proactively add a ThoughtSpot liveboard `filters[]` chip (see
`../../../shared/schemas/thoughtspot-liveboard-tml.md`) for each attribute the subtitle
displays (date, ID, name fields) as the substitute for the missing click-through — don't
wait to be asked why a tile looks sparse or wrong.

## Container-tree grid mapping algorithm (Step 9c)

Map the **container tree**, not raw coordinates — a flat y-band scan misgroups zones
whenever two containers share a y range.

1. **Walk the `<zones>` tree** from 9a. A **`vert`** container stacks its children into
   successive **rows**; a **`horz`** container lays its children **side-by-side within one
   row**. Recurse: a `horz` inside a `vert` is one row split into columns; a `vert` inside a
   `horz` is a column split into stacked rows.
2. **Columns within a horizontal container** — split 12 columns **proportionally to each
   child's `w` relative to its siblings' total `w`** (not the whole dashboard). Normalize with
   **largest-remainder** so `col_span`s sum to **exactly 12** with no slivers: floor each
   share, then hand the leftover columns to the zones with the largest fractional remainders.
   Enforce a **minimum `col_span` of 2** (merge or bump anything smaller) so no tile is an
   unreadable sliver.
3. **Rows / height** — give each row a `row_span` from the zone's **aspect ratio**, so charts
   keep roughly their source shape: `row_span ≈ round(col_span × (h/w) × 0.5)`, clamped to a
   per-type floor — **KPI/number ≥ 3, note/text ≥ 2, chart ≥ 6, table ≥ 8**. Stack rows top to
   bottom, each starting at the previous row's bottom (`y += prev row_span`).
4. **Fallback to the band method** only when the tree is unavailable (rare — e.g. a
   hand-edited TWB with flat zones): group zones within ~2,000 y-units into a band, sort bands
   top-to-bottom and zones left-to-right within a band, then apply the same proportional
   column split + aspect-ratio height as above.

**Floating zones** (`floating="true"`) overlap the tiled layout and have no grid equivalent.
Don't try to reproduce the overlap: place each floating zone as its **own full-or-partial-width
tile** in reading order (by y then x) after the tiled zones, and **note in the Migration
Summary** that it was a floating overlay flattened into the flow.

## Mark class → chart type (Step 10a)

| Tableau mark class / zone | ThoughtSpot `chart.type` |
|---|---|
| `bar` | `BAR` |
| `line` | `LINE` |
| `circle` / `point` | `SCATTER` |
| `square` | `BAR` |
| `pie` | `PIE` |
| `area` | `AREA` |
| `text` (crosstab) | `TABLE` (display_mode `TABLE_MODE`) |
| Map (lat/long generated + geo role) | `GEO_BUBBLE` (or `GEO_AREA` for a filled/choropleth map) |
| "Measure Names / Measure Values" KPI block | `KPI` — **one tile per measure** (see KPI rule in SKILL.md Step 10a) |
| **dual-axis combo** (two mark classes, e.g. `Bar` + `Line`, on a synchronized/secondary axis) | `ADVANCED_LINE_COLUMN` (Muze) — see the combo rule in SKILL.md Step 10a |

**Map row, confirmed live:** a Tableau worksheet with Latitude/Longitude on Rows/Cols
(any mark class) must land on `GEO_BUBBLE`, not a generic `LINE`/`SCATTER` of the two
coordinates — the latter loses the geographic context and reads as a confusing scatter of
degree values. Live-verified on a GE Aerospace "Ground Track" (flight path) worksheet:
first built as `LINE`, reviewed as wrong, rebuilt as `GEO_BUBBLE`.

**`GEO_BUBBLE` needs the lat/long columns tagged on the *model*, not just the chart type
set, AND a measure on the chart — lat/long alone is not the full verified shelf shape.**
`thoughtspot-chart-types.md`'s own verified-to-bind table lists `GEO_BUBBLE` as
"geo-dim **+ measure**", not geo-dim alone, and separately notes `GEO_AREA`/`GEO_BUBBLE`
"import structurally but render empty" unless the anchor column is geo-tagged — **both
conditions are required, not just the one you happen to check first.** Tag the Latitude/
Longitude columns' `properties.geo_config` (`{latitude: true}` / `{longitude: true}` — see
`thoughtspot-model-tml.md` "Geo Config") and pair with `spotiq_preference: "EXCLUDE"`, AND
add a measure to `chart_columns` (e.g. a row/event count) alongside the two geo dimensions.
The auto-builder does neither — add both as a patch when a map tile's lat/long columns
aren't already tagged or carry no measure. Live-verified, GE Aerospace C-FOQA "Category
Map"/"Event Map" tiles: adding the `geo_config` tags alone was NOT sufficient, and adding a
count measure to `chart_columns` alone was STILL not sufficient — the tiles only rendered
once an explicit `chart.axis_configs` block was also added: `{x: [<lat column>, <long
column>], y: [<measure column>]}`. Every other chart type in this skill tolerates a bare
`chart_columns` list with no `axis_configs` (the column order alone implies the shelf
assignment); `GEO_BUBBLE` does not — found by diffing against a confirmed-working `GEO_BUBBLE`
tile from an earlier liveboard on the same engagement ("Map Ground Track"), which carried
this block and ours didn't. **Don't assume a chart type "works" from one prior live-verified
case without diffing the FULL answer TML against it field-by-field** — "lat/long + measure"
alone was still missing the one block that actually renders the chart. Also check — before
re-investigating from scratch — whether a *later* `build-model --existing-guid` re-run wiped
the `geo_config` tags again; its column-cleanup regenerates `properties` from scratch and has
no concept of this property (see "Hand-patching formulas directly via TML" in
`step-5-tml-generation.md` for the general pattern).

**Per-entity dot/strip plot (mark `circle`, one measure + a grouping dimension + a
size/color dimension, many points — e.g. "each dot is a flight"):** prefer
**`ADVANCED_BUBBLE`** (Muze) over collapsing to a `BAR` of the measure aggregated by the
grouping dimension, which destroys the per-entity detail the chart exists to show. Keep
the finest-grain identifier available (e.g. a flight/record ID) as a field, sized by the
magnitude dimension (`ABS(difference)`, not the aggregate). Fall back to `BAR`-of-aggregate
only when no per-entity identifier exists in the model.

**A detail/row-level table (every column a dimension, or no real aggregation shelf) that
the auto-builder defaults to `SCATTER`** — because the chart-type-requirement floor sees
≥2 "measure-shaped" columns and stops there — **should be `TABLE` instead.** `TABLE` is not
a real `chart.type` enum value: omit the `chart:` block entirely and set
`display_mode: TABLE_MODE`. Don't trust the floor check's chart-type pick for a tile whose
columns are all per-row detail (flight/event ID, dates, names) rather than true aggregates
— compare against the source screenshot. Live-verified, GE Aerospace C-FOQA "Flights
Table"/"Events Table" tiles, both auto-picked `SCATTER` and were plain detail grids.

**A Tableau date field with a dynamic, parameter-driven grain
(`DATETRUNC([Grain Parameter], [date])`, e.g. a Month/Quarter/Year toggle) has no
ThoughtSpot formula equivalent** (see `tableau-formula-translation.md`'s `DATETRUNC` row) —
ThoughtSpot's date bucketing is a chart-level `Month(...)/Quarter(...)/Year(...)` wrapper on
a plain date column, not a value you can pass into a formula. Rather than drop every chart
that used the dynamic field, substitute the **default-selected grain shown in the source
dashboard screenshot** via the wrapper syntax directly in `chart_columns`/`axis_configs`
(e.g. `Quarter(Flight Date)`), and note the lost toggle interactivity in the Migration
Summary. If the underlying formula later gets hand-reconstructed (see
`tableau-formula-translation.md`'s dispatch technique), rewire the tile back to the real
field to restore the toggle.

## Post-build column-resolution correction pass (Step 10c/10d)

**`ts tableau build-liveboard` never cross-checks its output against the live model** — it
builds TML purely from the parsed TWB spec, using Tableau's raw field captions verbatim as
`column_id`/`answer_columns[].name`. This causes real, frequent import failures that have
nothing to do with chart-type choices:

1. **Casing/whitespace drift** between the Tableau caption and the model's actual column
   name. The model-building step applies its own casing convention (e.g. `"ICAO"` →
   `"Icao"`, `"at Start of Event"` → `"At Start Of Event"`) that doesn't match Tableau's raw
   caption. A duplicate-pill field can also show up suffixed (`"Event Type1"`) where the
   model only has the base name (`"Event Type"`).
2. **The dashboard still references formulas that were skipped or filtered during model
   enrichment.** The liveboard builder has no visibility into which formulas actually
   survived translation — it emits whatever the TWB says the worksheet used, whether or not
   that formula made it into the model.

**Always run a correction pass after `build-liveboard`, before import:**
1. Export the live model (`ts tml export <guid> --parse`) and collect every
   `columns[]`/`formulas[]`/`parameters[]` name into a canonical set.
2. Walk the generated liveboard TML's `answer_columns[].name`, `chart.chart_columns[].column_id`,
   `chart.axis_configs[].{x,y,color}[]`, and `table.{ordered_column_ids,table_columns[].column_id}`.
   For each name: try exact match, then case-insensitive, then strip a trailing digit
   (duplicate-pill suffix), then unwrap a `Month(...)/Quarter(...)/Year(...)/Week(...)`
   bucket wrapper and resolve the inner name recursively.
3. **Also fix `search_query` string literals** (`"[Old Name]"` substrings) — they are not
   just cosmetic; the import's internal answer-resolution step parses and validates them
   too, so a stale/wrong token there alone fails the whole viz even when every structured
   field already resolves correctly.
4. Anything that still doesn't resolve is genuinely dropped/untranslatable, not a typo —
   before deleting that visualization, check the raw Tableau formula for whether it's just
   a *fixed-grain approximation* away from working (the `DATETRUNC` case above) rather than
   truly unrecoverable.
5. `VALIDATE_ONLY`-import the corrected TML before the real create/update — it catches
   anything the correction pass missed in one clean error report rather than a live partial
   import.

Live-verified, GE Aerospace C-FOQA: 18 of 26 generated visualizations initially failed to
import for these reasons; the correction pass fixed 14 mechanically, 6 trend charts needed
the dynamic-grain substitution above, and the remaining 4 were genuinely dropped formulas.

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

## SpotterViz MCP — preferred build path, gotchas found live (2026-10-15)

Per Step 10-pre2 in SKILL.md, prefer `create_dashboard`/`modify_dashboard`
(`mcp__claude_ai_ThoughtSpot_Spotter__*`) over hand-building TML when connected. Pass the
TWB dashboard's tab/worksheet/chart-type/field structure as `instructions` — the designer
asks a clarifying question (`needs_input`) if anything is ambiguous; answer it, don't guess
on the user's behalf. Gotchas found migrating the GE Aerospace C-FOQA workbook this way:

- **Authorizing it when not connected — "restart" differs by runtime, not just VSCode.**
  The common steps are the same everywhere (confirm `.mcp.json` has the `ThoughtSpot` entry,
  restart so the MCP config reloads, run `/mcp`, complete the browser OAuth login), but how
  to restart depends on where Claude Code is running:
  - **CLI (terminal):** exit and re-run `claude`.
  - **VSCode extension:** reload the window (Cmd/Ctrl+Shift+P → "Developer: Reload Window")
    or fully quit/reopen VSCode — starting a new chat inside the same running extension does
    **not** reload `.mcp.json`.
  - **JetBrains plugin:** restart the IDE, or use the plugin's own restart action on the
    Claude Code tool window if it has one.
  - **Desktop or web app:** close and reopen the app/tab, or start a genuinely new session.
  Ask the user which runtime they're in if it isn't already evident, rather than assuming
  VSCode — the wrong restart instructions just waste their time.
- **`is_spotter_enabled` gate.** `create_dashboard` fails outright if the target model's
  `spotter_config.is_spotter_enabled` is `false` — a different gate from general query
  access (the model answered `ts agentql fetch-data` queries fine with it off). Step 5.5
  defaults this to `true` for fresh builds but **skips scope 3** (existing model) — always
  re-check it before a scope-3 liveboard rebuild.
- **`TABLE_MODE` chart-block omission doesn't survive reimport.** The general chart-types
  guidance ("omit `chart`, set `display_mode: TABLE_MODE`") does not hold when the tile's
  *existing* chart type is a grouping type (`ADVANCED_SCATTER` observed) — re-exporting after
  omitting `chart` silently re-adds the same grouping config every time. If a true flat list
  is wanted, the fix is usually not the chart type at all — check whether a column feeding
  the table is model-typed `MEASURE` (it'll auto-aggregate instead of showing per-row values
  when dropped bare into a table; retype to `ATTRIBUTE` if every formula using it already
  wraps it in an explicit aggregate). If a **pivoted/nested-row** look is actually wanted,
  `chart.type: ADVANCED_PIVOT_TABLE` auto-resolves rows/columns from `chart_columns` +
  `search_query` order and sticks cleanly on reimport — use that instead of fighting
  `TABLE_MODE`.
- **Answer-local formula reference syntax differs from Model formula syntax.** A Liveboard
  viz's own `answer.formulas[]` (ad-hoc formulas Spotter creates per-tile) must reference a
  shared **Model**-level formula by its **bare display name** (`[OP Event Count Grand
  Total]`) — the `[formula_<name>]` ID-ref convention that works for Model-to-Model formula
  references gets parsed as a literal, nonexistent search token here and fails at import
  with a misleading `Search did not find "formula_..."` error. (Local-to-local references,
  i.e. one tile-local formula referencing a sibling in the same `formulas[]` list, *do* use
  `[formula_<name>]` normally.) Inlining a nontrivial expression (an `if/else`, or even a
  bare `group_aggregate(...)` call) directly as a new local formula is also fragile and can
  fail the same way even when the identical expression works fine as a Model formula — push
  anything nontrivial into a permanent Model formula and reference it by name instead.
- **Verify filter casing against the actual formula output.** When instructions describe a
  filter in plain English (e.g. "Takeoff and Landing"), the designer can silently lowercase
  it when writing the `search_query` literal. If the underlying formula only emits Title
  Case, the filter matches nothing and the tile falls back to an unfiltered value with no
  error — same failure shape as a Tableau parameter's display-name-vs-internal-value bug.
  Spot-check at least one generated filter's exact casing against the formula's `if/else`
  branch literals before calling a tile done.
- **Verification queries need an explicit `GROUP BY`.** `ts agentql fetch-data` with a bare
  dimension + measure and no `GROUP BY` clause returns a misleading
  `"All non-constant columns should be grouped by or aggregated"` error that looks like a
  platform limitation but is just incomplete SQL — always add the `GROUP BY` when verifying
  a tile's grouped behavior this way.
