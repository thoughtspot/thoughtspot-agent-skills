---
name: ts-convert-from-tableau
description: Convert or import a Tableau workbook (.twb or .twbx) into ThoughtSpot — parses TWB XML, generates table + model TMLs, validates and imports. Optionally migrates dashboards to liveboards with layout approximation. Direction is always Tableau → ThoughtSpot. Not for ThoughtSpot → Tableau or standalone TML exports.
---

# Tableau Workbook → ThoughtSpot

Converts a Tableau workbook into ThoughtSpot objects. Parses the TWB XML to extract
tables, columns, joins, and calculated fields, then generates Table TMLs and a Model
TML per datasource. Optionally converts Tableau dashboards into ThoughtSpot Liveboards
with approximate layout mapping.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/tableau/tableau-formula-translation.md](../../shared/mappings/tableau/tableau-formula-translation.md) | Tableau → ThoughtSpot formula and function mapping |
| [../../shared/mappings/tableau/tableau-tml-rules.md](../../shared/mappings/tableau/tableau-tml-rules.md) | TML generation rules — critical invariants for valid import |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure reference |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure reference |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure reference |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/open-items.md](references/open-items.md) | Known validation quirks and workarounds |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Tableau workbook file (`.twb` or `.twbx`) accessible on disk

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-from-tableau** — convert a Tableau workbook into ThoughtSpot TML objects,
with optional dashboard-to-liveboard migration.

### Steps

  1.  Authenticate to ThoughtSpot .......................... auto
  2.  Locate and extract the TWB file ...................... you provide path
  3.  Parse TWB XML — extract tables, columns, joins,
      calculated fields .................................. auto
  4.  Fetch ThoughtSpot connection schema (optional) ...... you provide Connection ID (or skip)
  5.  Generate TML files (table + model) .................. auto
  6.  Validate against ThoughtSpot (up to 10 fix cycles) .. auto
  7.  Import to ThoughtSpot ................................ you confirm
  8.  Migrate dashboards to liveboards? .................... you choose (skip → Step 12)
  9.  Parse dashboard layout and map to grid ............... auto
 10.  Generate liveboard TML ............................... auto
 11.  Import liveboard ..................................... you confirm
 12.  Summary + limitations report ......................... auto

Confirmation required: Steps 7, 8, 11
Auto-executed: Steps 1, 3, 5, 6, 9, 10, 12

---

Ask: "Ready to start? Please provide the path to your `.twb` or `.twbx` file."

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If multiple profiles exist, display a
numbered menu and ask the user to choose. If only one profile, use it automatically.

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

Save `{base_url}` and `{profile_name}` for all subsequent steps.

---

## Step 2 — Extract TWB File

Ask for the file path if not yet provided.

If the file ends in `.twbx` (a ZIP archive), extract it:

```bash
mkdir -p /tmp/ts_tableau_mig && unzip -o "{twbx_path}" -d /tmp/ts_tableau_mig/
```

Then find the `.twb` inside:

```bash
find /tmp/ts_tableau_mig -name "*.twb" | head -1
```

Save the resolved `.twb` path as `{twb_path}`.

---

## Step 3 — Parse TWB XML

Read `{twb_path}` in full. The TWB is XML. Extract the following elements:

### 3a. Workbook name

Take from the filename (strip `.twb`). Save as `{workbook_name}`.

### 3b. For each `<datasource>` element (skip those named `Parameters`)

For each datasource, extract:

**Physical tables** — `<relation>` elements of `type="table"` or `type="text"`:
- `name` attribute = table alias used in joins
- `table` attribute = physical table name (use this for `db_table`)
- If `type="custom-sql"`: extract the physical table name from the SQL string
  (the table after `FROM`)

**Joins** — `<relation>` elements of `type="join"`:
- `join` attribute = join type (`inner` | `left` | `right` | `full`)
- `<clause>` child = join condition (decode HTML entities: `&quot;`→`"`,
  `&amp;`→`&`, `&lt;`→`<`, `&gt;`→`>`)
- Extract left and right table references from the clause

**Physical columns** — `<column>` elements WITHOUT a `<calculation>` child:
- `name` attribute = `[ColumnName]` — strip brackets
- `datatype` attribute = Tableau data type
- `role` attribute = `dimension` or `measure`
- `caption` attribute = display name

**Calculated fields** — `<column>` elements WITH a `<calculation class="tableau">` child:
- `caption` or `name` = display name
- `calculation formula` attribute = Tableau expression (decode HTML entities)
- `datatype` attribute

**Parameters** — `<datasource name="Parameters">` children:
- `name`, `caption`, `datatype`, default value

Save the parsed structure internally. Announce a summary:
> Parsed `{workbook_name}`: {N} datasource(s), {N} physical table(s),
> {N} calculated field(s), {N} join(s), {N} dashboard(s)

### 3c. Topological sort of calculated fields

Some calculated fields reference other calculated fields. Sort them so that fields
with no formula-dependencies come first (Level 0), then Level 1, etc. This determines
the order they must appear in the model TML `formulas` section.

### 3d. Dashboard metadata (for Step 8 decision)

Count `<dashboard>` elements in the TWB. Save the count and names — this is shown
in Step 8 when asking whether to migrate dashboards.

---

## Step 4 — Fetch Connection Schema (Optional)

Ask: "Do you have a ThoughtSpot Connection ID to map physical tables to the warehouse?
(Enter the GUID or type 'skip')"

If skipped, use `YOUR_DATABASE` and `YOUR_SCHEMA` as placeholders in table TMLs —
these produce a warning on validation, not an error.

If a Connection ID is provided (`{connection_id}`):

```bash
ts connections get {connection_id} --profile {profile_name}
```

Parse the response to extract available databases, schemas, and table names. For each
physical table from Step 3, find the best match (case-insensitive) in the connection
schema. Save the resolved `{db}`, `{schema}`, and `{db_table}` for each table.

If the connection response has no tables (empty `externalDatabases`), ask:
"The connection returned no tables. Please enter the database name to search
(e.g., FRANCOIS):"

---

## Step 5 — Generate TML Files

Create output directory:

```bash
mkdir -p /tmp/ts_tableau_mig/output/{workbook_name}
```

### 5a. Table TML — one per physical table

For each physical table identified in Step 3, generate a `.table.tml` file. Follow
all rules in `tableau-tml-rules.md`.

**Template:**

```yaml
table:
  name: TABLE_NAME
  db: YOUR_DATABASE
  schema: YOUR_SCHEMA
  db_table: physical_table_name
  columns:
  - name: COLUMN_NAME
    db_column_name: COLUMN_NAME
    data_type: VARCHAR              # VARCHAR | INT64 | DOUBLE | FLOAT | BOOL | DATE | DATETIME
    properties:
      column_type: ATTRIBUTE        # or MEASURE
      aggregation: SUM              # only if MEASURE — SUM | AVERAGE | COUNT
    db_column_properties:
      data_type: VARCHAR            # must match data_type above
```

Key rules:
- Use `INT64` for Tableau `integer` — **never `INT`**
- `db_column_properties` is **required** on every column
- No `guid`, `fqn`, or `connection` sections

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{TABLE_NAME}.table.tml`.

### 5b. Model TML — one per datasource

For each datasource, generate a `.model.tml` file.

**Template:**

```yaml
model:
  name: "Datasource Display Name"
  model_tables:
  - name: TABLE_NAME
    obj_id: TABLE_NAME
    joins:                      # only if this table has joins to others
    - with: OTHER_TABLE
      on: "[TABLE_NAME::JOIN_COL] = [OTHER_TABLE::JOIN_COL]"
      type: LEFT_OUTER          # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER
      cardinality: ONE_TO_MANY
  - name: OTHER_TABLE
    obj_id: OTHER_TABLE
  formulas:                     # omit section entirely if no calculated fields
  - id: formula_Formula Name
    name: Formula Name
    expr: "ThoughtSpot expression"
  columns:
  - name: display_name
    column_id: TABLE_NAME::COLUMN_NAME
    properties:
      column_type: ATTRIBUTE    # or MEASURE
```

Formula translation rules: use `tableau-formula-translation.md`.
- Convert Tableau join types: `full` → `OUTER`, `left` → `LEFT_OUTER`,
  `right` → `RIGHT_OUTER`, `inner` → `INNER`
- Write formulas in topological dependency order (Level 0 first)
- Every join MUST have a non-empty `on` field
- No `fqn` in `model_tables`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{DatasourceName}.model.tml`.

---

## Step 6 — Validate Against ThoughtSpot

Create a zip of all generated TML files:

```bash
cd /tmp/ts_tableau_mig/output/{workbook_name} && \
  zip -r /tmp/ts_tableau_mig/{workbook_name}_TMLs.zip *.tml
```

Validate (up to 10 fix cycles):

```bash
ts tml import --policy VALIDATE_ONLY --profile {profile_name} \
  < /tmp/ts_tableau_mig/{workbook_name}_TMLs.zip
```

For each cycle:

1. Parse the validation response.
2. **Ignore** warnings about `Table with id null not found` (placeholder db/schema — expected).
3. For any **errors**, identify the affected TML file and the specific issue. Apply
   the fix from the error table in `tableau-tml-rules.md`.
4. Rewrite the affected TML file and rebuild the zip.
5. Re-validate.

After 10 cycles with remaining errors, stop and report to the user:
- Errors that persist after all retries
- Which fix was attempted for each
- Ask whether to proceed with import anyway or make manual corrections

---

## Step 7 — Import to ThoughtSpot

Display a summary:
```
Ready to import {N} TML files to {base_url}:
  - {N} table TMLs
  - {N} model TMLs
```

Ask: "Import now? (yes/no)"

On confirmation:

```bash
ts tml import --policy ALL_OR_NONE --profile {profile_name} \
  < /tmp/ts_tableau_mig/{workbook_name}_TMLs.zip
```

Parse the response. Extract the GUID for each imported object. On failure, show the
error and stop.

Save the imported GUIDs internally as `{datasource_guids}` and `{table_guids}` — these
are used by Step 10 if the user proceeds with dashboard migration. Also save
`{formula_column_map}` (Tableau calc field caption → ThoughtSpot formula display name)
and `{parameter_map}` from the TWB parse.

---

## Step 8 — Migrate Dashboards?

If Step 3d found zero `<dashboard>` elements, skip to Step 12.

Otherwise, present the decision:

```
The workbook contains {N} dashboard(s):
  - {dashboard_name_1}
  - {dashboard_name_2}
  ...

Would you like to migrate these to ThoughtSpot Liveboards?
This maps Tableau dashboard layout to a 12-column grid with chart and note tiles.

  Y  Yes — migrate dashboards to liveboards
  N  No  — skip to summary

Enter Y / N:
```

If **N**, skip to Step 12.

---

## Step 9 — Parse Dashboard Layout and Map to Grid

### 9a. Zone extraction

For each `<dashboard>` element in the TWB, walk `<zones>` → `<zone>` elements
recursively. For each leaf zone, extract:

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
- **Skip**: `type="bitmap"` (images), `type="web"`, `type="extension"`,
  `type="metric"` (not supported in v1)

### 9b. Worksheet shelf data

For each chart zone's `worksheet_name`, find the corresponding `<worksheet>` element
in the TWB. Extract:
- Columns shelf (`<datasource-dependencies>` → `<column>` with shelf `column`)
- Rows shelf → shelf `row`
- Mark type: `<mark class="{type}">` (bar, line, circle/scatter, square, text, pie)
- Color encoding: column on `color` shelf
- Size encoding: column on `size` shelf
- Aggregation: from column `caption` prefix (`SUM(...)`, `AVG(...)`, etc.)

### 9c. Map coordinates to ThoughtSpot 12-column grid

ThoughtSpot liveboards use a **12-column responsive grid**. Tableau dashboards use
absolute pixel coordinates (0–100,000 range).

Use a band-based approach:

1. **Group zones by y-band** — zones within 2,000 units of each other vertically are
   in the same row band.
2. **Sort bands** from smallest y to largest y (top to bottom).
3. **Within each band**, sort zones by x (left to right).
4. **Assign columns**: divide 12 columns proportionally by each zone's `w` relative to
   the total dashboard width. Round to nearest integer; ensure columns sum to 12.
5. **Assign height**: convert Tableau `h` to ThoughtSpot height units (1 unit ≈ 1/20th
   of the dashboard height; minimum 4 units).
6. **Assign y position**: start from 0; each new row band starts at the bottom of the
   previous band.

Save the grid layout as a list of tiles with `zone_id`, `zone_type`, `worksheet_name`,
`col`, `col_span`, `row_span`, `y`.

---

## Step 10 — Generate Liveboard TML

### 10a. Resolve chart types

| Tableau mark class | ThoughtSpot chart type |
|---|---|
| `bar` | `BAR` |
| `line` | `LINE` |
| `circle` / `point` | `SCATTER` |
| `square` | `BAR` |
| `text` | `TABLE` |
| `pie` | `PIE` |
| `area` | `AREA` |

### 10b. Build search queries

For each chart zone, construct a search query from the worksheet's shelves:

- Rows/Columns shelf columns → include as dimensions or measures
- Apply aggregation prefix from the shelf caption (`SUM(Sales)` → `sum sales`)
- If a date column is on a shelf, add a time bucket (`monthly`, `yearly`) based on the
  `datetrunc` or `datepart` in the TWB
- Resolve calculated field names: use `{formula_column_map}` to translate Tableau
  caption → ThoughtSpot formula name

### 10c. Build liveboard TML

For each dashboard, generate a `.liveboard.tml`:

```yaml
liveboard:
  name: Dashboard Name
  description: "Migrated from Tableau workbook"
  visualizations:
  - id: Viz_1
    answer:
      name: Worksheet Name
      tables:
      - id: DatasourceName
        fqn: "model-guid-here"
      search_query: "sum sales category"
      chart:
        type: BAR
  - id: Note_2                   # for text/title zones
    viz_type: NOTE_TILE
    note_tile:
      content: "Note text here"
      background_color: "#FFFFFF"
  layout:
    tiles:
    - visualization_id: Viz_1
      x: 0
      y: 0
      height: 6
      width: 8
    - visualization_id: Note_2
      x: 8
      y: 0
      height: 6
      width: 4
```

### 10d. Beautify layout

Apply layout optimization to each liveboard TML:

1. **Sort tiles** by y, then x.
2. **Pack rows from y=0** — reset y values so tiles start at 0 with no gaps.
3. **Fill 12 columns per row** — if a row's tiles don't span all 12 columns, expand
   the rightmost tile's width to fill.
4. **Minimum tile height** — enforce minimum height of 4 units.
5. **Remove empty rows** — if a row has no tiles, remove it.

Rewrite the `layout.tiles` section with corrected coordinates.

Write each liveboard to
`/tmp/ts_tableau_mig/output/{workbook_name}/{dashboard_name}.liveboard.tml`.

---

## Step 11 — Import Liveboard

Display a summary:
```
Ready to import {N} liveboard(s) to {base_url}:
  - {dashboard_name_1}
  - {dashboard_name_2}
  ...
```

Ask: "Import now? (yes/no)"

On confirmation, zip all liveboard TMLs:

```bash
cd /tmp/ts_tableau_mig/output/{workbook_name} && \
  zip -r /tmp/ts_tableau_mig/{workbook_name}_LB_TMLs.zip *.liveboard.tml
```

```bash
ts tml import --policy PARTIAL --profile {profile_name} \
  < /tmp/ts_tableau_mig/{workbook_name}_LB_TMLs.zip
```

Use `--policy PARTIAL` so successfully imported liveboards are kept even if some fail.

Parse the response for import errors. Show any failures with detail.

For each successfully imported liveboard, display the URL:

```
{base_url}/#/pinboard/{liveboard_guid}
```

---

## Step 12 — Summary

Display the final summary:

```
Migration complete: {workbook_name}

  Tables imported:     {N}
  Models imported:     {N}
  Liveboards imported: {N} (or "skipped")

  TML files: /tmp/ts_tableau_mig/output/{workbook_name}/
```

If any calculated fields were untranslatable (WINDOW_*, LOD expressions, table
calculations, etc.), write a limitations file and display it:

`/tmp/ts_tableau_mig/output/{workbook_name}/MIGRATION_LIMITATIONS.md`

```markdown
# Migration Limitations: {workbook_name}

## Untranslatable Formulas

| Formula Name | Datasource | Reason | Tableau Expression (excerpt) |
|---|---|---|---|
| {name} | {datasource} | {reason} | `{expression snippet}` |
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-09 | Initial release — merged from ts-model-from-tableau + ts-liveboard-from-tableau |
