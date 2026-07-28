# Step 10 — Liveboard Generation Detail

Reference detail for **Step 10 — Convert LookML dashboard → ThoughtSpot Liveboard**: the
dashboard/element field-extraction list (10a), the chart-type mapping table (10b), the
search-query value-syntax table and worked filter examples (10c), the 24→12-column layout
worked example (10d), the full Liveboard TML template (10e), the dashboard-filter mapping
table and worked example (10f), and the migration-details table format + heredoc (10h). The
step's spine (which mode gates Step 10, the layout conversion formula, the obj_id and
chart-block-completeness gotchas, and the import commands) stays in `SKILL.md` — this file
is what the spine links out to for the full rule/template detail.

---

## 10a. Parse LookML dashboard file — full field list

LookML dashboards are plain-text YAML (`.dashboard.lookml`). Extract:

**Dashboard-level:**
- `dashboard: name` → Liveboard name (convert underscores to spaces, title-case)
- `layout:` → grid style (`newspaper` = 24-column grid; `tile_size` = fixed size)
- `filters:` block → dashboard filter definitions (see Step 10f)

**Per element (`elements:` — not `tiles:`):**
- `title:` → viz name (use `title:` if present, else `name:`)
- `type:` → chart type (see Step 10b for mapping)
- `explore:` → which explore name (= which model) to bind to
- `fields: [view.field, view.field, ...]` → all columns for the viz (dimensions and measures in one flat list)
- `sorts:` → sort order (record in summary; no direct TML equivalent — omit from TML)
- `limit:` → row limit (record in summary; no direct TML equivalent — omit from TML)
- `listen:` → map of `{FilterName: view.field}` — which dashboard filters this tile responds to
- `filters:` → tile-level hard filters `{view.field: "value"}` — embed into `search_query` (see Step 10c)
- `row:`, `col:`, `width:`, `height:` → grid position in 24-column grid (convert in Step 10d)

**Assign viz IDs sequentially:** `Viz_1`, `Viz_2`, ... in the order elements appear.

---

## 10b. LookML chart type → ThoughtSpot chart type

| LookML tile type | ThoughtSpot `display_mode` | ThoughtSpot chart `type` |
|---|---|---|
| `single_value` | `CHART_MODE` | `KPI` |
| `looker_column` | `CHART_MODE` | `COLUMN` |
| `looker_bar` | `CHART_MODE` | `BAR` |
| `looker_line` | `CHART_MODE` | `LINE` |
| `looker_pie` | `CHART_MODE` | `PIE` |
| `looker_scatter` | `CHART_MODE` | `SCATTER` |
| `looker_area` | `CHART_MODE` | `AREA` |
| `looker_waterfall` | `CHART_MODE` | `WATERFALL` |
| `looker_grid` / `table` | `TABLE_MODE` | *(omit `chart:` block — there is no `chart.type: TABLE`)* |
| `looker_donut_multiples` | `CHART_MODE` | `PIE` | No small-multiples chart in ThoughtSpot. Use PIE; document as migration gap — the per-pivot-value breakdown is lost. |
| `looker_funnel` | `TABLE_MODE` | *(unsupported → TABLE_MODE placeholder; log in summary)* |
| `looker_map` / `looker_geo_choropleth` | — | *(unsupported → omit tile entirely; log in summary)* |

---

## 10c. Resolve field references and build search query — full detail

**Resolve `view.field` → ThoughtSpot column display name:**

Each entry in `fields:` uses `view_name.field_name` format. Map each to the ThoughtSpot
column display name using the model built in Steps 3–6:

- Formula columns (measures translated to model formulas): use the formula's `name:` from the Model TML **as-is** — no "Total" prefix is added to formula columns.
  Example: `order_fact.total_net_revenue` → formula name `Total Net Revenue`
- Physical attribute columns: use the column's `name:` from the Model TML.
  Example: `customer_dim.region` → column name `Region`

**Build `search_query`:** Join all resolved column names in square brackets:
```
search_query: '[Region] [Total Net Revenue]'
```

**Handle tile-level `filters:` (hard filters):** Embed as filter conditions appended to the
`search_query`. Do NOT translate these to liveboard-level filters — they are tile-specific.

ThoughtSpot `search_query` uses **dot notation** for value filters — NOT SQL syntax:

| Value type | Syntax | Example |
|---|---|---|
| Single-word value | `[Column].Value` | `[Order Status].Complete` |
| Multi-word value | `[Column].'Value With Spaces'` | `[Customer Segment].'Home Office'` |

Rule: first include the column reference `[Column]`, then one token per filtered value.

```
# LookML tile-level filter:
filters:
  order_fact.order_status: "Complete,Returned"

# Resolve field → column display name, then split comma-separated values into tokens:
search_query: '[Order Channel] [Order Count] [Total Net Revenue] [Average Order Value] [Order Status] [Order Status].Complete [Order Status].Returned'
```

**Translating LookML filter values to search tokens:**
1. Resolve `view.field` → ThoughtSpot column display name (e.g. `order_fact.order_status` → `Order Status`)
2. Split the LookML filter string on commas: `"Complete,Returned"` → `["Complete", "Returned"]`
3. For each value: if it contains spaces wrap in single quotes — `[Order Status].Complete`, `[Customer Segment].'Home Office'`
4. Prepend the bare column reference once: `[Order Status]`
5. Append all value tokens after the column reference

**Build `answer_columns[]`:** One entry per resolved column display name, in field order.

---

## 10d. Layout coordinate conversion — worked example

Example from `skilltest_orders.dashboard.lookml`:
```
LookML (24-col):               ThoughtSpot (12-col):
  row:0,  col:0,  w:8,  h:4   →   x:0,  y:0,  width:4,  height:4
  row:0,  col:8,  w:8,  h:4   →   x:4,  y:0,  width:4,  height:4
  row:0,  col:16, w:8,  h:4   →   x:8,  y:0,  width:4,  height:4
  row:4,  col:0,  w:12, h:8   →   x:0,  y:4,  width:6,  height:8
  row:4,  col:12, w:12, h:8   →   x:6,  y:4,  width:6,  height:8
  row:12, col:0,  w:24, h:8   →   x:0,  y:12, width:12, height:8
```

Odd-width example: `col:1, width:11 → x:0, width:6`; `col:12, width:11 → x:6, width:6` (two 6-wide tiles fill the 12-col grid perfectly).

---

## 10e. Full Liveboard TML template

```yaml
liveboard:
  name: {Dashboard Title}
  visualizations:

  # ── CHART tile (COLUMN / BAR / LINE / PIE / SCATTER / AREA / WATERFALL) ──
  - id: Viz_{n}
    answer:
      name: {tile title}
      display_mode: CHART_MODE
      tables:
      - id: {Model Name}
        name: {Model Name}
        obj_id: "{ModelNameNoSpaces}-{guid8}"   # from Step 9 — NOT fqn
      search_query: '[{DimColumn}] [{MeasureColumn}]'
      answer_columns:
      - name: {DimColumn}
      - name: {MeasureColumn}
      chart:
        type: {COLUMN|BAR|LINE|PIE|SCATTER|AREA|WATERFALL}
        chart_columns:
        - column_id: {DimColumn}              # resolved display name
        - column_id: {MeasureColumn}          # resolved display name
        axis_configs:
        - x:
          - {DimColumn}
          y:
          - {MeasureColumn}

  # ── KPI tile (single_value) ──
  - id: Viz_{n}
    display_headline_column: {MeasureColumn}  # resolved measure display name
    answer:
      name: {tile title}
      display_mode: CHART_MODE
      tables:
      - id: {Model Name}
        name: {Model Name}
        obj_id: "{ModelNameNoSpaces}-{guid8}"
      search_query: '[{MeasureColumn}]'
      answer_columns:
      - name: {MeasureColumn}
      chart:
        type: KPI
        chart_columns:
        - column_id: {MeasureColumn}
        axis_configs:
        - y:
          - {MeasureColumn}

  # ── TABLE tile (table / looker_grid / looker_funnel) ──
  - id: Viz_{n}
    answer:
      name: {tile title}
      display_mode: TABLE_MODE              # TABLE_MODE — no chart: block
      tables:
      - id: {Model Name}
        name: {Model Name}
        obj_id: "{ModelNameNoSpaces}-{guid8}"
      search_query: '[{Col1}] [{Col2}] [{Col3}]'
      answer_columns:
      - name: {Col1}
      - name: {Col2}
      - name: {Col3}

  filters:
  # (populated in Step 10f)

  layout:
    tiles:
    - visualization_id: Viz_1
      x: {col/2}
      y: {row}
      width: {lookml_width/2}
      height: {lookml_height}
    # one entry per viz, in Viz_1…Viz_N order
```

---

## 10f. Dashboard filters → Liveboard filters — full detail

**Collect all unique filters** from the dashboard-level `filters:` block. Build one
ThoughtSpot liveboard filter per dashboard filter.

```yaml
# LookML dashboard filter:
- name: Region
  type: field_filter
  field: customer_dim.region
  allow_multiple_values: true

# ThoughtSpot liveboard filter:
- column:
  - Region                        # resolved ThoughtSpot column display name (from model)
  is_mandatory: false
  is_single_value: false          # allow_multiple_values: true  → is_single_value: false
                                  # allow_multiple_values: false → is_single_value: true
  oper: in                        # default for multi-value string filters (see operator table)
  excluded_visualizations:        # viz IDs whose listen: map does NOT include this filter
  - Viz_{n}
```

**Operator mapping:**

| LookML `allow_multiple_values` | LookML field type | ThoughtSpot `oper` |
|---|---|---|
| `true` | string | `in` |
| `false` | string | `EQ` |
| — | date | use `date_filter:` block instead of `oper` |
| `false` | number | `EQ` |

**`excluded_visualizations` rule:**
For each liveboard filter, find all viz IDs whose `listen:` block does **not** include that
filter name. Add those viz IDs to `excluded_visualizations`. This ensures the filter only
applies to tiles that explicitly opted in via `listen:`.

Example — "Region" filter applies to Viz_1/2/3/5/6 but NOT Viz_4 ("Net Revenue by Region"
only listens to "Order Channel"):
```yaml
- column:
  - Region
  is_single_value: false
  oper: in
  excluded_visualizations:
  - Viz_4
```

---

## 10h. Migration details table format + heredoc

One row per Looker tile — four columns: **Dashboard**, **Answer**, **Migration Status**,
**Reason**. Leave `Reason` blank for a clean 1:1 migration; fill it in only when the row
is approximated or skipped, and keep it to one short sentence:

```
| Dashboard | Answer | Migration Status | Reason |
|---|---|---|---|
| Business Pulse | Revenue by Channel | ✅ Migrated | |
| Business Pulse | Orders Over Time | ✅ Migrated | |
| Business Pulse | Funnel by Stage | ⚠️ Migrated (approximated) | No funnel chart type — rendered as a TABLE placeholder. |
| Business Pulse | Segment Split | ⚠️ Migrated (approximated) | No small-multiples chart — split into 2 PIE tiles, shared-legend comparison lost. |
| Business Pulse | Store Locations | ❌ Skipped | No map/geo chart type in ThoughtSpot Liveboard TML. |
```

`Migration Status` values:
- **✅ Migrated** — same chart type, same fields, no behavioural difference
- **⚠️ Migrated (approximated)** — migrated but not 1:1 (chart type substitution,
  split into multiple tiles, sort/limit dropped, etc.) — always fill `Reason`
- **❌ Skipped** — no ThoughtSpot equivalent; tile omitted entirely — always fill `Reason`

**Dashboard-level notes.** If the dashboard has a gap that applies across tiles rather
than to one answer (e.g. a filter's `listens_to_filters:` cascading behaviour, which has
no ThoughtSpot equivalent, or a filter's default-value handling), add a `## Notes`
section below the table — one bullet per gap. Omit the section entirely if there are none.

**Liveboard URL.** Include the URL from Step 10g exactly **once**, as its own line after
the table (and Notes section, if present) — never repeat it per row. If more than one
dashboard was converted in this run, add one `Liveboard URL:` line per dashboard, each
labelled with the dashboard name.

Write to `{reports_dir}` (defined in Step 7.5 — same folder as the gaps file and the
migration summary), as a single fixed filename regardless of dashboard name or explore:

```bash
cat > "{reports_dir}/migration_details.md" << 'EOF'
# Migration Details
# Generated by ts-convert-from-looker
# Source project: {project_path}
# Date: {date}

| Dashboard | Answer | Migration Status | Reason |
|---|---|---|---|
...

---
## Notes
- {dashboard-level gap, one bullet per gap}
# omit the "## Notes" section entirely if there are none

Liveboard URL: {liveboard_url}
# one "Liveboard URL: {name} — {url}" line per dashboard if more than one was converted

For field/formula-level detail and the full migration writeup, see:
- Migration summary: {reports_dir}/{project_name}_migration_summary.md
- Migration gaps:    {reports_dir}/{explore_name}_migration_gaps.md
EOF
```

This file only exists when Step 10 runs (scope 1 or 3). If the project has more than
one dashboard, add all dashboards' tiles as additional rows in the same table rather
than writing a separate file per dashboard — `migration_details.md` is one file per
migration run.
