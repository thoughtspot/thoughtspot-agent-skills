---
name: ts-liveboard-from-tableau
description: Migrate Tableau dashboards to ThoughtSpot liveboards — reads the migration_manifest.json from ts-model-from-tableau (Stage 1), parses dashboard layout, generates liveboard TML with visualizations and note tiles, and imports to ThoughtSpot.
---

# ThoughtSpot: Liveboard from Tableau (Stage 2)

Convert Tableau dashboard sheets into ThoughtSpot liveboards. Each Tableau dashboard
becomes one liveboard with visualizations, note tiles for text/title zones, and a
layout that approximates the original Tableau positioning.

**Prerequisite: run `ts-model-from-tableau` (Stage 1) first** to generate the
`migration_manifest.json` that this skill requires.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [../ts-model-from-tableau/SKILL.md](../ts-model-from-tableau/SKILL.md) | Stage 1 — run this first |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure reference |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [references/open-items.md](references/open-items.md) | Known coordinate mapping quirks and liveboard import behavior |

---

## Prerequisites

- Stage 1 (`ts-model-from-tableau`) completed — `migration_manifest.json` on disk
- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-liveboard-from-tableau** — migrate Tableau dashboards to ThoughtSpot liveboards.

### Steps

  1.  Authenticate to ThoughtSpot .......................... auto
  2.  Load manifest and TWB file ........................... you provide manifest path
  3.  Parse TWB dashboard sheets (zones, layout) ........... auto
  4.  Map Tableau coordinates to TS 12-column grid ......... auto
  5.  Generate Answer TMLs for chart zones ................. auto (one per worksheet)
  6.  Build liveboard TML (layout + tiles + note tiles) .... auto
  7.  Beautify layout (fill columns, pack rows) ............ auto
  8.  Import liveboard to ThoughtSpot ...................... you confirm
  9.  Display liveboard URL ................................ auto

Confirmation required: Step 8 (import)
Auto-executed: Steps 1, 3, 4, 5, 6, 7, 9

---

Ask: "Ready to start? Please provide the path to your `migration_manifest.json` from Stage 1."

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If multiple profiles, show a numbered menu. Otherwise use the single profile automatically.

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

If the manifest specifies a `profile_name`, prefer it unless it fails.

Save `{base_url}` and `{profile_name}`.

---

## Step 2 — Load Manifest and TWB File

Read the `migration_manifest.json` at the provided path. Extract:
- `{workbook_name}`, `{twb_path}`, `{base_url}`, `{datasource_guids}`, `{formula_column_map}`, `{parameter_map}`

If the TWB file no longer exists at `{twb_path}`, ask: "The TWB file was not found at `{twb_path}`. Please provide the current path."

Read the TWB XML file in full.

---

## Step 3 — Parse Dashboard Sheets

In the TWB XML, identify `<dashboard>` elements (these are the Tableau dashboard sheets). For each dashboard:

### 3a. Dashboard metadata
- `name` attribute = dashboard sheet name → becomes liveboard name
- `<size>` element (if present) — original pixel dimensions

### 3b. Zone extraction

Walk `<zones>` → `<zone>` elements recursively. For each leaf zone, extract:

| Field | Source |
|---|---|
| `zone_id` | `id` attribute |
| `zone_type` | `type` attribute (`text`, `title`, `viz`, `bitmap`, `web`, `extension`, `metric`) |
| `worksheet_name` | `name` attribute (for `viz` zones) |
| `x`, `y`, `w`, `h` | `x`, `y`, `w`, `h` attributes (Tableau uses 0–100,000 coordinate space) |
| `text_content` | `<formatted-text>` child text (for `text` / `title` zones) |

Classify each zone:
- **Chart zones**: `type="viz"` with a worksheet name → becomes a visualization tile
- **Text/title zones**: `type="text"` or `type="title"` → becomes a note tile
- **Skip**: `type="bitmap"` (images), `type="web"`, `type="extension"`, `type="metric"` (not supported in v1)

### 3c. Worksheet shelf data

For each chart zone's `worksheet_name`, find the corresponding `<worksheet>` element in the TWB. Extract:
- Columns shelf (`<datasource-dependencies>` → `<column>` with shelf `column`)
- Rows shelf → shelf `row`
- Mark type: `<mark class="{type}">` (bar, line, circle/scatter, square, text, pie)
- Color encoding: column on `color` shelf
- Size encoding: column on `size` shelf
- Aggregation: from column `caption` prefix (`SUM(...)`, `AVG(...)`, etc.)

---

## Step 4 — Map Coordinates to ThoughtSpot Grid

ThoughtSpot liveboards use a **12-column responsive grid**. Tableau dashboards use absolute pixel coordinates (0–100,000 range).

Use a band-based approach:

1. **Group zones by y-band** — zones within 2,000 units of each other vertically are in the same row band.
2. **Sort bands** from smallest y to largest y (top to bottom).
3. **Within each band**, sort zones by x (left to right).
4. **Assign columns**: divide 12 columns proportionally by each zone's `w` relative to the total dashboard width. Round to nearest integer; ensure columns sum to 12.
5. **Assign height**: convert Tableau `h` to ThoughtSpot height units (1 unit ≈ 1/20th of the dashboard height; minimum 4 units).
6. **Assign y position**: start from 0; each new row band starts at the bottom of the previous band.

Save the grid layout as a list of tiles:

```
[
  { zone_id, zone_type, worksheet_name, col, col_span, row_span, y }
]
```

---

## Step 5 — Generate Answer TMLs for Chart Zones

For each chart zone, generate a ThoughtSpot Answer TML that approximates the Tableau visualization.

### 5a. Look up the datasource model

Find the datasource used by the worksheet from the TWB. Look up its GUID from `{datasource_guids}` in the manifest.

```bash
ts metadata search --subtype MODEL --name "{DatasourceName}" --profile {profile_name}
```

Save the model GUID as `{model_guid}`.

### 5b. Build a natural-language query

Construct a search query from the worksheet's shelves:

- Rows/Columns shelf columns → include as dimensions or measures
- Apply aggregation prefix from the shelf caption (`SUM(Sales)` → `sum sales`)
- If a date column is on a shelf, add a time bucket (`monthly`, `yearly`) based on the `datetrunc` or `datepart` in the TWB
- Resolve calculated field names: use `{formula_column_map}` from the manifest to translate Tableau caption → ThoughtSpot formula name

Example query for a bar chart with SUM(Sales) by Category:
```
sum sales category
```

### 5c. Resolve chart type

| Tableau mark class | ThoughtSpot chart type |
|---|---|
| `bar` | `BAR` |
| `line` | `LINE` |
| `circle` / `point` | `SCATTER` |
| `square` | `BAR` |
| `text` | `TABLE` |
| `pie` | `PIE` |
| `area` | `AREA` |

### 5d. Write Answer TML

Generate a `.answer.tml` for each worksheet and write to `/tmp/ts_tableau_mig/output/{workbook_name}/answers/{worksheet_name}.answer.tml`:

```yaml
answer:
  name: {worksheet_name}
  description: Migrated from Tableau worksheet "{worksheet_name}"
  tables:
  - id: {DatasourceName}
    fqn: {model_guid}
  search_query: "{nl_query}"
  answer_columns:
  - name: {column_name}
  chart:
    type: {BAR|LINE|TABLE|PIE|SCATTER|AREA}
    chart_columns:
    - column_id: {column_name}
      type: X_AXIS
    - column_id: {column_name}
      type: Y_AXIS
```

---

## Step 6 — Build Liveboard TML

For each dashboard, generate a `.liveboard.tml`:

```yaml
liveboard:
  name: {dashboard_name}
  description: Migrated from Tableau workbook "{workbook_name}"
  visualizations:
  - id: Viz_{zone_id}
    answer:
      name: {worksheet_name}
      tables:
      - id: {DatasourceName}
        fqn: {model_guid}
      search_query: "{nl_query}"
      chart:
        type: {CHART_TYPE}
  - id: Note_{zone_id}      # for text/title zones
    viz_type: NOTE_TILE
    note_tile:
      content: "{text_content}"
      background_color: "#FFFFFF"
  layout:
    tiles:
    - visualization_id: Viz_{zone_id}
      x: {col}
      y: {y}
      height: {row_span}
      width: {col_span}
    - visualization_id: Note_{zone_id}
      x: {col}
      y: {y}
      height: {row_span}
      width: {col_span}
```

Write to `/tmp/ts_tableau_mig/output/{workbook_name}/{dashboard_name}.liveboard.tml`.

---

## Step 7 — Beautify Layout

Apply layout optimization to each liveboard TML:

1. **Sort tiles** by y, then x.
2. **Pack rows from y=0** — reset y values so tiles start at 0 with no gaps.
3. **Fill 12 columns per row** — if a row's tiles don't span all 12 columns, expand the rightmost tile's width to fill.
4. **Minimum tile height** — enforce minimum height of 4 units.
5. **Remove empty rows** — if a row has no tiles, remove it.

Rewrite the `layout.tiles` section of each liveboard TML with the corrected coordinates.

---

## Step 8 — Import Liveboard

Display a summary:
```
Ready to import {N} liveboard(s) to {base_url}:
  {dashboard_name_1}
  {dashboard_name_2}
  ...
```

Ask: "Import now? (yes/no)"

On confirmation, zip all liveboard TMLs and any answer TMLs:

```bash
cd /tmp/ts_tableau_mig/output/{workbook_name} && zip -r /tmp/ts_tableau_mig/{workbook_name}_LB_TMLs.zip *.liveboard.tml answers/*.answer.tml
```

```bash
ts tml import --policy PARTIAL --profile {profile_name} < /tmp/ts_tableau_mig/{workbook_name}_LB_TMLs.zip
```

Use `--policy PARTIAL` so that successfully imported liveboards are kept even if some answer TMLs fail.

Parse the response for import errors. Show any failures with detail.

---

## Step 9 — Display Liveboard URL

For each successfully imported liveboard, construct and display the URL:

```
{base_url}/#/pinboard/{liveboard_guid}
```

Show a summary:
- Liveboards imported: {N}
- Visualizations per liveboard: {N}
- Any failed tiles or warnings

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-05-28 | Initial release |
