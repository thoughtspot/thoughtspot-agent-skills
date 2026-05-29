---
name: ts-model-from-tableau
description: Migrate a Tableau workbook (.twb or .twbx) to ThoughtSpot table and model TMLs — parses the TWB XML, generates TML, validates against a live ThoughtSpot instance, and imports. Produces a migration_manifest.json for use by ts-liveboard-from-tableau (Stage 2).
---

# ThoughtSpot: Model from Tableau (Stage 1)

Convert a Tableau workbook's data model into ThoughtSpot TML objects: one `.table.tml` per
physical table and one `.model.tml` per Tableau datasource. Validates the TML against a live
ThoughtSpot cluster before importing.

**Run this skill first** — it produces a `migration_manifest.json` that the liveboard skill (Stage 2) requires.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [../../shared/mappings/tableau/tableau-formula-translation.md](../../shared/mappings/tableau/tableau-formula-translation.md) | Tableau → ThoughtSpot formula and function mapping |
| [../../shared/mappings/tableau/tableau-tml-rules.md](../../shared/mappings/tableau/tableau-tml-rules.md) | TML generation rules — critical invariants for valid import |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure reference |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure reference |
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
**ts-model-from-tableau** — migrate a Tableau workbook's data model to ThoughtSpot TML.

### Steps

  1.  Authenticate to ThoughtSpot .......................... auto
  2.  Locate and extract the TWB file ...................... you provide path
  3.  Parse TWB XML — extract tables, columns, joins,
      calculated fields, parameters ....................... auto
  4.  Fetch ThoughtSpot connection schema (optional) ...... you provide Connection ID (or skip)
  5.  Generate TML files (table + model) .................. auto
  6.  Validate against ThoughtSpot (up to 10 fix cycles) .. auto
  7.  Import to ThoughtSpot ................................ you confirm
  8.  Save migration_manifest.json ......................... auto
  9.  Write MIGRATION_LIMITATIONS.md ....................... auto

Confirmation required: Steps 7 (import)
Auto-executed: Steps 1, 3, 5, 6, 8, 9

---

Ask: "Ready to start? Please provide the path to your `.twb` or `.twbx` file."

---

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`. If multiple profiles exist, display a numbered menu and ask the user to choose. If only one profile, use it automatically.

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
- If `type="custom-sql"`: extract the physical table name from the SQL string (the table after `FROM`)

**Joins** — `<relation>` elements of `type="join"`:
- `join` attribute = join type (`inner` | `left` | `right` | `full`)
- `<clause>` child = join condition (decode HTML entities: `&quot;`→`"`, `&amp;`→`&`, `&lt;`→`<`, `&gt;`→`>`)
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
> Parsed `{workbook_name}`: {N} datasource(s), {N} physical table(s), {N} calculated field(s), {N} join(s)

### 3c. Topological sort of calculated fields

Some calculated fields reference other calculated fields. Sort them so that fields with no formula-dependencies come first (Level 0), then Level 1, etc. This determines the order they must appear in the model TML `formulas` section.

---

## Step 4 — Fetch Connection Schema (Optional)

Ask: "Do you have a ThoughtSpot Connection ID to map physical tables to the warehouse? (Enter the GUID or type 'skip')"

If skipped, use `YOUR_DATABASE` and `YOUR_SCHEMA` as placeholders in table TMLs — these produce a warning on validation, not an error.

If a Connection ID is provided (`{connection_id}`):

```bash
ts connections get {connection_id} --profile {profile_name}
```

Parse the response to extract available databases, schemas, and table names. For each physical table from Step 3, find the best match (case-insensitive) in the connection schema. Save the resolved `{db}`, `{schema}`, and `{db_table}` for each table.

If the connection response has no tables (empty `externalDatabases`), ask: "The connection returned no tables. Please enter the database name to search (e.g., FRANCOIS):"

---

## Step 5 — Generate TML Files

Create output directory:

```bash
mkdir -p /tmp/ts_tableau_mig/output/{workbook_name}
```

### 5a. Table TML — one per physical table

For each physical table identified in Step 3, generate a `.table.tml` file. Follow all rules in `tableau-tml-rules.md`.

**Template:**

```yaml
table:
  name: {TABLE_NAME}
  db: {db_or_YOUR_DATABASE}
  schema: {schema_or_YOUR_SCHEMA}
  db_table: {physical_table_name}
  columns:
  - name: {COLUMN_NAME}
    db_column_name: {COLUMN_NAME}
    data_type: {VARCHAR|INT64|DOUBLE|FLOAT|BOOL|DATE|DATETIME}
    properties:
      column_type: {ATTRIBUTE|MEASURE}
      aggregation: {SUM|AVERAGE|COUNT}   # only if MEASURE
    db_column_properties:
      data_type: {VARCHAR|INT64|DOUBLE|FLOAT|BOOL|DATE|DATETIME}
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
  name: {Datasource Display Name}
  model_tables:
  - name: {TABLE_NAME}
    obj_id: {TABLE_NAME}
    joins:                      # only if this table has joins to others
    - with: {OTHER_TABLE}
      on: "[{TABLE_NAME}::{JOIN_COL}] = [{OTHER_TABLE}::{JOIN_COL}]"
      type: LEFT_OUTER          # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER
      cardinality: ONE_TO_MANY
  - name: {OTHER_TABLE}
    obj_id: {OTHER_TABLE}
  formulas:                     # omit section entirely if no calculated fields
  - id: formula_{Formula Name}
    name: {Formula Name}
    expr: "{ThoughtSpot expression}"
  columns:
  - name: {display_name}
    column_id: {TABLE_NAME}::{COLUMN_NAME}
    properties:
      column_type: {ATTRIBUTE|MEASURE}
```

Formula translation rules: use `tableau-formula-translation.md`.
- Convert Tableau join types: `full` → `OUTER`, `left` → `LEFT_OUTER`, `right` → `RIGHT_OUTER`, `inner` → `INNER`
- Write formulas in topological dependency order (Level 0 first)
- Every join MUST have a non-empty `on` field
- No `fqn` in `model_tables`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{DatasourceName}.model.tml`.

---

## Step 6 — Validate Against ThoughtSpot

Create a zip of all generated TML files:

```bash
cd /tmp/ts_tableau_mig/output/{workbook_name} && zip -r /tmp/ts_tableau_mig/{workbook_name}_TMLs.zip *.tml
```

Validate (up to 10 fix cycles):

```bash
ts tml import --policy VALIDATE_ONLY --profile {profile_name} < /tmp/ts_tableau_mig/{workbook_name}_TMLs.zip
```

For each cycle:

1. Parse the validation response.
2. **Ignore** warnings about `Table with id null not found` (placeholder db/schema — expected).
3. For any **errors**, identify the affected TML file and the specific issue. Apply the fix from the error table in `tableau-tml-rules.md`.
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
  • {N} table TMLs
  • {N} model TMLs
```

Ask: "Import now? (yes/no)"

On confirmation:

```bash
ts tml import --policy ALL_OR_NONE --profile {profile_name} < /tmp/ts_tableau_mig/{workbook_name}_TMLs.zip
```

Parse the response. Extract the GUID for each imported object. On failure, show the error and stop.

---

## Step 8 — Save Migration Manifest

Write `/tmp/ts_tableau_mig/output/{workbook_name}/migration_manifest.json`:

```json
{
  "workbook_name": "{workbook_name}",
  "twb_path": "{twb_path}",
  "base_url": "{base_url}",
  "profile_name": "{profile_name}",
  "datasource_guids": {
    "{DatasourceName}": "{guid}"
  },
  "table_guids": {
    "{TABLE_NAME}": "{guid}"
  },
  "formula_column_map": {
    "{Tableau calc field caption}": "{ThoughtSpot formula display name}"
  },
  "parameter_map": {
    "{Tableau parameter name}": "{caption}"
  }
}
```

Tell the user: "Manifest saved to `/tmp/ts_tableau_mig/output/{workbook_name}/migration_manifest.json` — you'll need this path for Stage 2 (ts-liveboard-from-tableau)."

---

## Step 9 — Write MIGRATION_LIMITATIONS.md

If any calculated fields were untranslatable (WINDOW_*, LOD expressions, etc.), write:

`/tmp/ts_tableau_mig/output/{workbook_name}/MIGRATION_LIMITATIONS.md`

```markdown
# Migration Limitations: {workbook_name}

## Untranslatable Formulas

| Formula Name | Datasource | Reason | Tableau Expression (excerpt) |
|---|---|---|---|
| {name} | {datasource} | {reason} | `{expression snippet}` |
```

Display the final summary to the user:
- TML files location
- Manifest location
- Number of limitations (if any)
- Instructions to run Stage 2: "Run `/ts-liveboard-from-tableau` with the manifest path above to migrate dashboards."

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-05-28 | Initial release |
