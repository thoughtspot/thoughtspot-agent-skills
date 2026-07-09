# ThoughtSpot Liveboard TML — Structure Reference

How a ThoughtSpot Liveboard is represented in TML. Verified against a live instance
(`champ-staging`) by exporting real Liveboards with filters, parameters, and multi-viz layouts.

For the embedded Answer structure inside each visualization, see
[thoughtspot-answer-tml.md](thoughtspot-answer-tml.md).

---

## Full Liveboard TML Structure

```yaml
guid: "{liveboard_guid}"        # document root
liveboard:
  name: "Liveboard Display Name"
  description: "Optional description"

  visualizations:               # one entry per chart/table/KPI tile
  - id: "Viz_1"                 # stable local ID used by layout.tiles
    viz_guid: "{viz_guid}"      # ThoughtSpot-assigned GUID for this viz
    answer:                     # full embedded Answer — same structure as standalone Answer TML
      name: "Viz Title"
      description: ""
      display_mode: TABLE_MODE | CHART_MODE
      # TABLE_MODE → render as a table: OMIT the `chart` block entirely (there is no
      # `chart.type: TABLE` — that value is rejected). CHART_MODE → include a `chart` block
      # with a verified type (BAR / LINE / PIE / KPI / AREA / SCATTER). Good for "coverage"
      # tiles that just surface one formula as a simple table.
      tables:
      - id: "Model Name"
        name: "Model Name"
        fqn: "{model_guid}"
      search_query: "[Revenue] [Region]"
      answer_columns:
      - name: Revenue
      - name: Region
      formulas:                 # viz-level custom formulas (same structure as Answer TML)
      - id: "formula_My Formula"
        name: "My Formula"
        expr: "[Revenue] / [Cost]"
        was_auto_generated: false
      parameters: []            # viz-level parameters (rare)
      cohorts: []               # viz-level sets (rare)
      table:
        client_state: ''
        ordered_column_ids: [Revenue, Region]
        table_columns:
        - column_id: Revenue
          headline_aggregation: SUM
      chart:
        type: COLUMN
        chart_columns:
        - column_id: Revenue
        axis_configs:
        - y: [Revenue]
        client_state: ''
    display_headline_column: "Revenue"   # optional — KPI headline column

  filters:                      # liveboard-level filters applied to all (or some) vizzes
  - column:
    - Created Date              # primary filter column
    - Order Date                # linked column (optional additional entries)
    display_name: ''
    is_mandatory: false
    is_single_value: false
    date_filter:                # for date columns only
      type: LAST_N_PERIOD
      date_period: MONTH
      number: 6
      oper: '='
    excluded_visualizations:    # viz IDs excluded from this filter
    - Viz_3

  - column:
    - Status
    display_name: ''
    is_mandatory: false
    is_single_value: false
    oper: in
    values:
    - Open
    - Closed

  layout:
    tiles:                      # one entry per viz — controls position and size
    - visualization_id: "Viz_1"
      x: 0                      # horizontal grid position
      y: 0                      # vertical grid position
      height: 4                 # grid units tall
      width: 6                  # grid units wide
    - visualization_id: "Viz_2"
      x: 6
      y: 0
      size: MEDIUM              # alternative to explicit height/width

    tabs:                       # optional — tabs group tiles into pages
    - name: "Overview"
      description: ""
      tiles:
      - visualization_id: "Viz_1"
        x: 0
        y: 0
        height: 4
        width: 6
    - name: "Details"
      tiles: [...]

  parameter_overrides:          # liveboard-level parameter defaults
  - key: "{parameter_uuid}"
    value:
      name: "Model Name::Param Name"   # format: model_name::param_name
      id: "{parameter_uuid}"
      override_value: "42"             # present only if overridden from default

  ordered_chips:                # display order of filter/parameter chips in the UI
  - name: "Model Name::Param Name"
    type: PARAMETER
  - name: Created Date
    type: FILTER

  style:                        # visual styling
    style_properties:
    - name: lb_border_type
      value: CURVED | SQUARE
    - name: lb_brand_color
      value: LBC_A | LBC_B | ...
    - name: hide_group_title          # section header title
      value: 'false'
    - name: hide_group_description     # section header description
      value: 'true'
    - name: hide_group_tile_description
      value: 'false'
    - name: hide_tile_description      # per-viz tile description
      value: 'false'
    - name: kpi_hero_font_size         # KPI headline size: S | M | L | XL
      value: M
```

---

## Field Reference

### Top-level

| Field | Required | Notes |
|---|---|---|
| `guid` | On update only | Document root — NOT inside `liveboard:`. Omit for new liveboards. |
| `liveboard.name` | Yes | Display name |
| `liveboard.description` | No | Multi-line text supported |
| `liveboard.visualizations` | Yes | One entry per tile. Each embeds a full Answer TML. |
| `liveboard.filters` | No | Liveboard-level filters applied across vizzes |
| `liveboard.layout` | No | Tile positions. Can use `tiles[]` (flat) or `tabs[]` (tabbed). |
| `liveboard.parameter_overrides` | No | Default parameter values at liveboard level |
| `liveboard.ordered_chips` | No | UI order of filter/parameter chips |
| `liveboard.style` | No | Visual styling settings |

### `visualizations[]` fields

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Stable local ID (e.g. `Viz_1`) — referenced by `layout.tiles[].visualization_id` |
| `viz_guid` | No | ThoughtSpot-assigned GUID for this viz. Omit on first import. |
| `answer` | Yes | Full embedded Answer TML — same structure as a standalone Answer |
| `display_headline_column` | No | Column name shown as KPI headline below a tile |

**Viz-level formulas:** If a visualization has custom formulas, they appear inside
`answer.formulas[]` with the same structure as standalone Answer formulas. The
`was_auto_generated` flag is present. Formulas are scoped to that viz only — they are
not shared between vizzes on the same Liveboard.

### `filters[]` fields

| Field | Notes |
|---|---|
| `column[]` | First entry is the primary filter column. Additional entries are linked columns that receive the same filter value. Display names only (no TABLE:: prefix). |
| `display_name` | Label shown on the filter chip in the UI |
| `is_mandatory` | If true, a value must be selected before the liveboard loads |
| `is_single_value` | If true, only one filter value can be selected at a time |
| `oper` | Filter operator: `in`, `not_in`, `between`, `eq`, `ne`, `lt`, `le`, `gt`, `ge` |
| `values[]` | Pre-set filter values |
| `date_filter` | For date columns: `type` (`LAST_N_PERIOD`, `BETWEEN`, etc.), `date_period` (`MONTH`, `WEEK`, `QUARTER`, etc.), `number`, `oper` |
| `excluded_visualizations[]` | Viz IDs that this filter does NOT apply to |

### `layout` fields

There are four layout styles:

| Layout style | Structure | Notes |
|---|---|---|
| Flat (no tabs) | `layout.tiles[]` | Each tile: `visualization_id`, `x`, `y`, `height`, `width` OR `size` |
| Tabbed | `layout.tabs[]` | Each tab: `name`, `description`, `tiles[]` (same tile structure) |
| Flat + Groups | `layout.tiles[]` + `layout.group_layouts[]` | Groups in a flat (non-tabbed) layout. See "Sections (groups)" below. |
| **Tabbed + Groups** | `layout.tabs[]` with `group_layouts[]` **inside each tab** | Tabs and groups coexist. Tab `tiles[]` reference **group IDs** (not individual viz IDs); `group_layouts[]` nests inside each tab entry. See "Tabbed + Groups" below. |

Predefined `size` values: `EXTRA_SMALL`, `SMALL`, `MEDIUM`, `LARGE`, `LARGE_SMALL`,
`MEDIUM_SMALL`, `EXTRA_LARGE`. Use `size` OR `height`/`width`, not both.

---

## Visualization data-source binding — use `obj_id`, not `fqn`

Inside a viz, the `answer.tables[]` entry binds the viz to its Model. **Use `obj_id`,
not a bare `fqn` GUID** — a viz-level `fqn` is dropped on import, leaving the viz with no
data source, which renders as an error (the chart shows but has nothing to query).

```yaml
tables:
- id: "Model Name"
  name: "Model Name"
  obj_id: ModelNameNoSpaces-{guid8}   # e.g. AmazonSalesdata-fdea93b4
```

`obj_id` format = the model's display name with spaces removed, `-`, then the first
segment of its GUID (`fdea93b4` from `fdea93b4-a80f-...`). The liveboard document itself
also carries a root `obj_id` (`{LiveboardNameNoSpaces}-{guid8}`) alongside the root
`guid`.

## Chart block must be complete

A partial `chart:` block (just `type`) is **not** auto-completed on import — the viz
renders broken. Either omit `chart:` entirely (ThoughtSpot generates a full default,
usually a table/KPI) **or** supply a complete block: `type`, `chart_columns[]`, and
`axis_configs[]` (`x`/`y`). All column references must use the **resolved** answer-column
names, not the raw model column names:

- An aggregated measure gains its aggregation word: `SUM([Total Revenue])` resolves to
  `Total Total Revenue`; a non-default agg follows the same pattern.
- **Model formula columns** with embedded aggregation (e.g. `sum([A] * [B])`) resolve to
  their **formula name as-is** — no "Total" prefix. Example: a formula named
  "Commission Earned" with `sum(...)` in its expression resolves to `Commission Earned`,
  NOT `Total Commission Earned`.
- A bucketed date resolves to `{Bucket}(col)` — `[Ship Date].yearly` → `Year(Ship Date)`,
  `[Order Date].monthly` → `Month(Order Date)`.
- **KPI date auto-bucketing:** a bare date column in a KPI `search_query`
  (e.g. `[Date]`) is auto-bucketed to **monthly** by ThoughtSpot. The resolved column
  name becomes `Month(Date)` and the search_query gains `.monthly`. To get a different
  bucket, specify it explicitly (e.g. `[Date].daily` → `Day(Date)`).
- Attributes keep their name.
- Date bucketing in `search_query` uses the **dotted** form (`[Order Date].monthly`); a
  bare `monthly` token is rejected with `Invalid value token: monthly`.

ThoughtSpot re-resolves `answer_columns` from `search_query` on import, but it does **not**
fix `chart_columns`/`axis_configs`/`table_columns` — those must already use the resolved
names or the chart fails. The reliable workflow: import once, export, copy the resolved
names into `chart_columns`/`axis_configs`, re-import.

### "Complete" means the right axis keys for the chart type, not just a non-empty block

`axis_configs[]` having *some* content is not the same as being complete — which keys are
required depends on the chart type:

| Chart type | Required `axis_configs` keys | Why |
|---|---|---|
| `KPI` | `y` only | No category to slice by — a single measure value |
| `COLUMN`, `BAR`, `LINE`, `AREA`, `SCATTER`, `PIE` | **both** `x` (category) **and** `y` (measure) | The chart needs an explicit dimension to group/slice by, not just the value to plot |

A `PIE` (or `COLUMN`/`BAR`/`LINE`/`AREA`) chart with only `y` set — no `x` — is a subtler
version of the "partial chart block" problem above: it **does not** produce an import
error, and it **does not** obviously render broken (no blank tile, no error banner). It
imports successfully and then the tile takes an extremely long time to load or never
finishes — verified 2026-07-02 on a PIE tile (`type: PIE`, `chart_columns: [Department,
Users Count]`, `axis_configs: [{y: [Users Count]}]`) that hung indefinitely while every
other tile in the same liveboard (AREA/COLUMN with both `x` and `y` set) loaded normally.
Fix: add the missing `x` key with the categorical column — `axis_configs: [{x:
[Department], y: [Users Count]}]` — re-import as an update (see below), confirmed the
tile then loads fast. Treat "imports fine but one specific tile is slow to the point of
hanging, while structurally similar tiles are fast" as a signal to diff that tile's
`axis_configs` against a working tile of a **similar categorical chart type** (not just
any working tile) before assuming it's a data-volume problem.

### Patching a tile after import — preserve `guid` and `viz_guid`

To fix one tile without recreating the whole liveboard (which would lose sharing,
permissions, and any manual UI edits to other tiles):

1. `ts tml export {liveboard_guid} --parse --profile {p}` and inspect the broken/slow
   viz's `answer.chart` block against a working viz of the same chart type in the same
   export — the diff is usually the fastest way to spot a missing key.
2. In your source TML, add `guid: "{liveboard_guid}"` at the document root (this makes it
   an update, not a new object) and `viz_guid: "{...}"` on **every** `visualizations[]`
   entry (from the export) so ThoughtSpot patches each tile in place instead of
   regenerating new viz identities.
3. Fix only the broken block, re-validate (`--policy VALIDATE_ONLY`), then re-import
   **without** `--create-new` (guid present = update).
4. Re-export and diff again to confirm the fix landed (e.g. `axis_configs` now present)
   before asking the user to check the UI.

---

## Note tiles (text tiles)

A note tile is a `visualizations[]` entry with a `note_tile` block and **no `answer`**.
It holds rich text (migrate a Tableau dashboard text/title zone here). It is placed in
`layout.tiles[]` like any other tile.

```yaml
- id: Viz_6
  viz_guid: "{viz_guid}"          # omit on first import
  note_tile:
    html_parsed_string: |-
      <p><strong>Sales Performance Overview</strong></p>
      <p><em>Your complete view of Amazon sales health.</em></p>
      <p>Narrative text, with <strong>bold</strong> and <em>italic</em> HTML.</p>
```

## Sections (groups)

Groups (a.k.a. sections) bundle vizzes into a labelled container with its own inner grid.

```yaml
liveboard:
  groups:
  - id: Group_1
    name: "Sales Channel Performance"
    description: "Revenue and profit breakdown by sales channel"
    group_guid: "{group_guid}"     # omit on first import
    visualizations:                # member viz IDs
    - Viz_2
    - Viz_3
  layout:
    tiles:                         # the GROUP is positioned here, as a tile
    - visualization_id: Group_1
      x: 0
      y: 6
      height: 6
      width: 6
    group_layouts:                 # members are arranged INSIDE the group (fresh 12-col grid)
    - id: Group_1
      tiles:
      - visualization_id: Viz_2
        x: 0
        y: 0
        height: 6
        width: 6
      - visualization_id: Viz_3
        x: 6
        y: 0
        height: 6
        width: 6
```

| Field | Notes |
|---|---|
| `groups[].id` | Local group ID (`Group_1`); referenced from `layout.tiles[]` and `layout.group_layouts[]` |
| `groups[].name` / `description` | Section header text |
| `groups[].visualizations[]` | Member viz IDs |
| `groups[].group_guid` | TS-assigned; omit on first import |
| `layout.group_layouts[]` | Per-group inner layout — one entry per group, each with its own `tiles[]` |

## Tabbed + Groups

Groups work inside tabs. The key difference from flat+groups: `group_layouts[]` nests
inside each **tab** entry, and the tab's `tiles[]` reference **group IDs** — individual
vizzes only appear inside `group_layouts[].tiles[]`. Verified against a live instance
(`se-thoughtspot`) on 2026-06-12.

```yaml
liveboard:
  groups:
  - id: Group_1
    name: "Key Metrics"
    description: "High-level KPIs"
    visualizations:              # member viz IDs
    - Viz_1
    - Viz_2
  - id: Group_2
    name: "Sales Analysis"
    description: "Breakdown charts"
    visualizations:
    - Viz_3
    - Viz_4
  layout:
    tabs:
    - name: "Overview"
      tiles:                     # tab tiles reference GROUPS, not individual vizzes
      - visualization_id: Group_1
        x: 0
        y: 0
        height: 4
        width: 12
      - visualization_id: Group_2
        x: 0
        y: 4
        height: 6
        width: 12
      group_layouts:             # nested INSIDE the tab — not at layout root
      - id: Group_1              # matches groups[].id — NOT "group_id"
        tiles:
        - visualization_id: Viz_1
          x: 0
          y: 0
          height: 4
          width: 6
        - visualization_id: Viz_2
          x: 6
          y: 0
          height: 4
          width: 6
      - id: Group_2
        tiles:
        - visualization_id: Viz_3
          x: 0
          y: 0
          height: 6
          width: 6
        - visualization_id: Viz_4
          x: 6
          y: 0
          height: 6
          width: 6
    - name: "Notes"
      tiles:                     # ungrouped vizzes go directly in tabs[].tiles[]
      - visualization_id: Viz_5
        x: 0
        y: 0
        height: 14
        width: 12
```

**Common mistakes that cause "Group was dropped because it has no valid visualizations":**
- Putting individual viz IDs in `tabs[].tiles[]` instead of group IDs
- Putting `group_layouts` at the top-level `layout` instead of inside each tab
- Using `group_id` instead of `id` in `group_layouts[]` entries
- Using `visualization_ids` instead of `visualizations` in `groups[]`

## `client_state` / `client_state_v2`

Both `answer.table` and `answer.chart` carry `client_state` (legacy, usually `''`) and
`client_state_v2` — an opaque JSON blob holding frontend presentation state. For most chart
types it is **not** required — ThoughtSpot applies sensible defaults when it is empty. See the
`client_state_v2` section in [thoughtspot-answer-tml.md](thoughtspot-answer-tml.md) for the
observed structure (series colors, axis properties incl. dual-axis `isOpposite`, per-column
KPI display options, responsive layout).

**Exception — KPI sparklines.** A KPI viz imported without `client_state_v2` renders as a
plain number — no sparkline, no comparison, no change indicator. The sparkline requires
`kpiColumnProperties.showSparkline: true` on the date column inside `client_state_v2`. See
"KPI sparkline `client_state_v2`" below for the verified template.

For all other chart types, do not hand-author `client_state_v2` — supply the structural chart
block and leave styling to defaults.

### KPI sparkline `client_state_v2`

A KPI viz with a date dimension (e.g. `[Ship Date].yearly`) needs this `client_state_v2` on
the `chart:` block to render the sparkline trend line. Verified against a live instance
(2026-06-11).

```jsonc
{
  "version": "V4DOT2",
  "chartProperties": {
    "gridLines": {},
    "responsiveLayoutPreference": "USER_PREFERRED_ON",
    "chartSpecific": { "dataFieldArea": "column" },
    "kpiDisplayProperties": {
      "showChange": true,              // show % change vs prior period
      "showChangeAs": "PERCENT",       // PERCENT | ABSOLUTE
      "changeInterpretation": "UPWARD_IS_GOOD",
      "linkChangeColorsWithAnomaly": true
    }
  },
  "columnProperties": [
    {
      "columnId": "{DateColumn}",      // e.g. "Year(Ship Date)"
      "columnProperty": {
        "kpiColumnProperties": {
          "showAbbreviatedPreviousDate": false,
          "showSparkline": true,       // ← THIS enables the sparkline
          "showComparisonDate": true,
          "showCurrentDateLabel": true,
          "showPreviousDateLabel": true,
          "showPreviousValue": true
        }
      }
    },
    {
      "columnId": "{MeasureColumn}",   // e.g. "Total Units Sold"
      "columnProperty": {
        "kpiColumnProperties": {
          "showAbbreviatedPreviousDate": false,
          "showSparkline": true,
          "showComparisonDate": true,
          "showCurrentDateLabel": true,
          "showPreviousDateLabel": true,
          "showPreviousValue": true
        }
      }
    }
  ],
  "axisProperties": [
    { "id": "{uuid}", "properties": { "axisType": "Y", "linkedColumns": ["{MeasureColumn}"], "isOpposite": false } },
    { "id": "{uuid}", "properties": { "axisType": "X", "linkedColumns": ["{DateColumn}"] } }
  ],
  "seriesColors": [
    { "serieName": "{MeasureColumn}", "color": "{hex}" }  // optional — matches viz_style
  ]
}
```

The `table:` block also needs a corresponding `client_state_v2` (simpler — just
`tableVizPropVersion` and column stubs) and `table_columns` with `headline_aggregation`.
Both `table:` and `chart:` blocks are required for the KPI to render correctly with
sparkline.

Generate fresh UUIDs for `axisProperties[].id` — these are opaque identifiers, not
references to other objects.

### `parameter_overrides[]` fields

| Field | Notes |
|---|---|
| `key` | UUID of the parameter |
| `value.name` | `"ModelName::ParameterName"` — scope-qualified parameter name |
| `value.id` | Same UUID as `key` |
| `value.override_value` | Present only if the default was changed. String regardless of data type. |

---

## Liveboard styling — `style_properties`, `overrides`, color tokens

Liveboard styling lives **in the TML** under `liveboard.style` and uses semantic **color
tokens**, not hex codes. (This is distinct from embed-time theming via the Visual Embed
SDK `customizations.style` / `--ts-var-*` CSS variables, which is a runtime layer and does
**not** appear in TML.)

```yaml
style:
  style_properties:            # global — whole liveboard
  - name: lb_brand_color
    value: LBC_A
  - name: lb_border_type
    value: CURVED              # CURVED | SHARP
  - name: hide_group_title
    value: 'false'
  - name: hide_group_description
    value: 'true'
  - name: kpi_hero_font_size
    value: M                   # S | M | L
  overrides:                   # per-object — keyed by group or viz id
  - object_id: Group_2
    style_properties:
    - name: group_brand_color
      value: GBC_C
  - object_id: Viz_7
    style_properties:
    - name: tile_brand_color
      value: TBC_I             # dark — KPI tiles only
```

### Property scopes

| Scope | Property | Values |
|---|---|---|
| Liveboard | `lb_brand_color` | `LBC_A`…`LBC_H` |
| Liveboard | `lb_border_type` | `CURVED` / `SHARP` |
| Group | `group_brand_color` | `GBC_A`…`GBC_H` |
| Group | `hide_group_title` / `hide_group_description` / `hide_group_tile_description` | `'true'`/`'false'` |
| Tile | `tile_brand_color` | `TBC_A`…`TBC_H` (light, any viz); `TBC_I`…`TBC_P` (dark, **KPI only**) |
| Tile | `hide_tile_title` / `hide_tile_description` | `'true'`/`'false'` |
| KPI | `is_highlighted` | emphasis styling |
| KPI | `tile_kpi_color` | `TKS_A`…`TKS_P` (KPI number color) |
| KPI | `kpi_hero_font_size` | `S` / `M` / `L` / `XL` |

`overrides[].object_id` accepts a group id (`Group_N`) or viz id (`Viz_N`). Per-object
`style_properties` override the global ones for that object only.

### Background color tokens (hex reference)

`LBC_*` = liveboard background, `GBC_*` = group background (lighter), `TBC_A`–`TBC_H` =
light tile backgrounds. Suffix → hue:

| Suffix | Hue | `LBC_*` hex |
|---|---|---|
| A | light gray | `#F6F8FA` |
| B | light purple | `#E3D9FC` |
| C | light blue | `#CEDCF5` |
| D | light cyan | `#C9F0F5` |
| E | light green | `#C7F2E3` |
| F | light yellow | `#FCF1D1` |
| G | light orange | `#FFDDCC` |
| H | light pink | `#FCD4D7` |

`TBC_I`–`TBC_P` are dark tile backgrounds valid **only on KPI tiles** (pair with light
`tile_kpi_color`). `TKS_A`–`TKS_P` set the KPI hero-number color.

### Curated themes

A pick-one set that maps cleanly onto the tokens (used by the skill's style step). The
**base brand colors** are below; border type, per-tile colors, KPI emphasis
(`tile_kpi_color`/`is_highlighted`), and matching `chart.viz_style` palettes vary per theme
— the verified, complete recipes live in the tableau skill's
`references/liveboard-style-themes.md`.

| Theme | `lb_brand_color` | `group_brand_color` | `tile_brand_color` | `lb_border_type` |
|---|---|---|---|---|
| Clean & Minimal | `LBC_A` | `GBC_A` | `TBC_A` | `SHARP` |
| Warm Tones | `LBC_G` | `GBC_G` | `TBC_G` | `CURVED` |
| Cool Professional | `LBC_C` | `GBC_C` | `TBC_C` | `CURVED` |
| Fresh & Modern | `LBC_D` | `GBC_D` | `TBC_D` | `CURVED` |
| Soft Lavender | `LBC_B` | `GBC_B` | `TBC_B` | `CURVED` |
| High Contrast KPIs | `LBC_A` | — | KPI tiles `TBC_I`–`TBC_P` (dark) | `CURVED` |

---

## Key Differences from Answer TML

| Aspect | Liveboard TML | Standalone Answer TML |
|---|---|---|
| Top-level key | `liveboard:` | `answer:` |
| Vizzes | `visualizations[]` — each embeds an `answer:` | N/A — the whole file is one answer |
| Formulas | Inside `visualizations[n].answer.formulas[]` | `answer.formulas[]` |
| Filters | Liveboard-level `filters[]` (cross-viz) | `answer.search_query` only |
| Layout | `layout.tiles[]` or `layout.tabs[]` | N/A |
| Parameter scope | `parameter_overrides[]` for liveboard defaults | `parameters[]` per answer |

---

## Finding Formulas in a Liveboard

When searching for a formula that lives in a Liveboard visualization:

```python
import re, yaml

lb = tml.get("liveboard", {})
for viz in lb.get("visualizations", []):
    a = viz.get("answer", {})
    formulas = a.get("formulas", [])
    if formulas:
        print(f"Viz {viz['id']} ({a.get('name')}) has {len(formulas)} formula(s):")
        for f in formulas:
            flag = " [auto]" if f.get("was_auto_generated") else ""
            print(f"  {f['name']}{flag}: {f['expr']}")
```

---

## Limitations

- R and Python-powered visualizations cannot be exported or imported via TML.
- Changing a viz's `name` and `expr` in the same TML import requires two separate imports.
- Liveboard-embedded viz formulas cannot be directly promoted to a Model — export the
  Liveboard TML, find the viz, extract `answer.formulas[]`, and use `/ts-object-answer-promote`.
