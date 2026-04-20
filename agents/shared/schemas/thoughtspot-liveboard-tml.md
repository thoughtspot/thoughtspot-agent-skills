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
    - name: hide_group_title
      value: 'false'
    - name: hide_tile_description
      value: 'false'
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

Two layouts are mutually exclusive:

| Layout style | Structure | Notes |
|---|---|---|
| Flat (no tabs) | `layout.tiles[]` | Each tile: `visualization_id`, `x`, `y`, `height`, `width` OR `size` |
| Tabbed | `layout.tabs[]` | Each tab: `name`, `description`, `tiles[]` (same tile structure) |

Predefined `size` values: `EXTRA_SMALL`, `SMALL`, `MEDIUM`, `LARGE`, `LARGE_SMALL`,
`MEDIUM_SMALL`, `EXTRA_LARGE`. Use `size` OR `height`/`width`, not both.

### `parameter_overrides[]` fields

| Field | Notes |
|---|---|
| `key` | UUID of the parameter |
| `value.name` | `"ModelName::ParameterName"` — scope-qualified parameter name |
| `value.id` | Same UUID as `key` |
| `value.override_value` | Present only if the default was changed. String regardless of data type. |

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
  Liveboard TML, find the viz, extract `answer.formulas[]`, and use `/object-ts-model-promote`.
