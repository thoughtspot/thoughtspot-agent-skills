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
| [../../shared/schemas/thoughtspot-sql-view-tml.md](../../shared/schemas/thoughtspot-sql-view-tml.md) | SQL View TML structure — for custom SQL datasources |
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

### Modes

  **A  Audit** — analyse a TWB file (or multiple files) and report migration coverage.
     No ThoughtSpot auth required. No TMLs generated. Use this to assess feasibility
     before committing to a migration.

  **M  Migrate** — full conversion: parse, generate TMLs, validate, and import.

Enter A / M:

### Steps (Migrate mode)

  1.  Authenticate to ThoughtSpot .......................... auto
  2.  Locate and extract the TWB file ...................... you provide path
  3.  Parse TWB XML — extract tables, columns, joins,
      calculated fields .................................. auto
  4.  Select ThoughtSpot connection ....................... you choose (or skip)
  5.  Generate TML files (table + sql_view + model) ...... auto
  6.  Validate against ThoughtSpot (up to 10 fix cycles) .. auto
  7.  Import to ThoughtSpot ................................ you confirm
  8.  Migrate dashboards to liveboards? .................... you choose (skip → Step 12)
  9.  Parse dashboard layout and map to grid ............... auto
 10.  Generate liveboard TML ............................... auto
 11.  Import liveboard ..................................... you confirm
 12.  Summary + limitations report ......................... auto

Confirmation required: Steps 7, 8, 11
Auto-executed: Steps 1, 3, 5, 6, 9, 10, 12

### Steps (Audit mode)

  A1.  Locate and extract TWB file(s) ...................... you provide path(s)
  A2.  Parse TWB XML — same extraction as Step 3 .......... auto
  A3.  Classify formulas into translation tiers ............ auto
  A4.  Migration coverage report ........................... auto

No auth, no TML generation, no import. Supports multiple files in one run.

---

If Audit mode, proceed to Step A1. If Migrate mode, proceed to Step 1.

---

## Step A1 — Locate TWB File(s) (Audit Mode)

Ask: "Provide the path to a `.twb` or `.twbx` file, or a directory containing multiple
workbooks."

If a directory is provided, find all `.twb` and `.twbx` files recursively. For each
`.twbx`, extract to a temp directory to access the inner `.twb`.

Save the list of TWB paths. Process each file through Steps A2–A4 independently.

---

## Step A2 — Parse TWB XML (Audit Mode)

Run the same extraction as Step 3 (3a through 3d) on each TWB file. Do NOT skip any
datasource type — include Extract datasources in the audit count (marked as "Extract —
skipped in migration").

---

## Step A3 — Classify Formulas (Audit Mode)

For each calculated field extracted in Step A2, classify it into one of these tiers
based on the patterns in `tableau-formula-translation.md`:

| Tier | Description | Examples |
|---|---|---|
| **Native** | Direct ThoughtSpot function mapping exists | IF/THEN, IFNULL, DATEDIFF, LEFT, ABS, ROUND, IIF |
| **LOD** | LOD expression → `group_aggregate()` | `{FIXED dim : SUM(col)}` |
| **Cumulative** | Running calculation → `cumulative_*()` | RUNNING_SUM, RUNNING_AVG |
| **Moving** | Window table calc → `moving_*()` | WINDOW_SUM, WINDOW_AVG (when sort attr determinable) |
| **Pass-through** | Valid SQL but no native function → `sql_*_aggregate_op()` | Partitioned RANK, DENSE_RANK, WINDOW_* without sort context, TOTAL() |
| **Untranslatable** | No ThoughtSpot equivalent — will be omitted | LOOKUP, INDEX, SIZE(), PREVIOUS_VALUE |
| **Parameter ref** | References a Tableau parameter — requires manual mapping | `[Parameters].[Parameter Name]` |

### Classifier implementation notes

**Function detection — require parentheses.** Match `FUNCTION_NAME(` (with optional
whitespace before the paren), not bare word boundaries. Bare `\bSIZE\b` false-positives
on dimension values like `'Size'` or column names like `[Size]`. Correct patterns:

```
LOOKUP\s*\(   INDEX\s*\(   SIZE\s*\(   PREVIOUS_VALUE\s*\(   RAWSQL_
RUNNING_(SUM|AVG|MAX|MIN|COUNT)\s*\(
WINDOW_(SUM|AVG|MAX|MIN|COUNT|STDEV|VAR|MEDIAN|PERCENTILE)\s*\(
RANK(_UNIQUE|_MODIFIED|_DENSE|_PERCENTILE)?\s*\(
TOTAL\s*\(
```

**Parameter references.** Detect `[Parameters].[...]` pattern — this is Tableau's
cross-datasource parameter reference syntax. These formulas use translatable syntax
(IF/CASE/WHEN) but depend on Tableau parameter values that have no automatic
ThoughtSpot equivalent. Classify as **Parameter ref**, not Untranslatable.

**LOD first.** Check `{FIXED|INCLUDE|EXCLUDE}` before other tiers — LOD expressions
may also contain functions like SUM that would match Native.

For each formula, also check:
- Does it reference other calculated fields? (cross-reference depth)
- Does it use functions from the untranslatable list?
- Does it mix translatable and untranslatable patterns?

---

## Step A4 — Migration Coverage Report (Audit Mode)

For each TWB file, produce a coverage report. If multiple files were audited, also
produce a combined summary at the end.

**Per-file report:**

```
Audit: {workbook_name}
══════════════════════════════════════════════════════

  Datasources:          {N} total
    Live:               {N}
    Extract:            {N} (skipped in migration)
    Published (sqlproxy): {N}

  Physical tables:      {N}
  Custom SQL relations: {N} → will generate sql_view TMLs
  Joins:                {N}

  Calculated fields:    {N} total
  ┌─────────────────────────────────────────────────┐
  │ Tier                Count    %     Examples     │
  ├─────────────────────────────────────────────────┤
  │ Native              {N}     {%}   IF, DATEDIFF │
  │ LOD → group_agg     {N}     {%}   {FIXED ...}  │
  │ Cumulative          {N}     {%}   RUNNING_SUM  │
  │ Moving              {N}     {%}   WINDOW_SUM   │
  │ Pass-through        {N}     {%}   DENSE_RANK   │
  │ Untranslatable      {N}     {%}   LOOKUP       │
  │ Parameter ref       {N}     {%}                │
  └─────────────────────────────────────────────────┘

  Parameters:           {N} (require manual recreation in ThoughtSpot)
  Dashboards:           {N} (optional liveboard migration)

  ──────────────────────────────────────────────────
  Function coverage:    {(native+lod+cum+mov+pt+rank) / total}%
                        (formula syntax is auto-translatable)
  Fully automatic:      {(native+lod+cum+mov+pt+rank) / total}%
                        (excludes parameter refs that need manual mapping)
  Pass-through formulas require SQL Passthrough Functions enabled.
  ──────────────────────────────────────────────────
```

**Function coverage** counts everything except Untranslatable — including parameter
refs, whose IF/CASE/WHEN syntax IS translatable even though the parameter value
needs manual mapping. **Fully automatic** excludes both Untranslatable AND Parameter
ref formulas.

If any formulas are classified as Untranslatable, list them:

```
  Untranslatable formulas (will be omitted):
    - {formula_name}: {reason} — {expression excerpt}
    - ...
```

If any formulas are classified as Parameter ref, list them with guidance:

```
  Parameter-referencing formulas ({count}):
    - {formula_name}: references [Parameters].[{param_name}]
    - ...

  These formulas use translatable syntax (IF/CASE/WHEN) but depend on
  Tableau parameter values. To migrate:
  1. Identify the parameter's purpose (dimension selector, threshold, toggle)
  2. Replace with a ThoughtSpot runtime filter, or hardcode the value
  3. Re-add the formula manually after import
```

If any formulas are classified as Pass-through, list them with the generated expression:

```
  Pass-through formulas (require SQL Passthrough Functions enabled):
    - {formula_name}: sql_{type}_aggregate_op("...", ...)
    - ...
```

Write the report to `/tmp/ts_tableau_mig/audit/{workbook_name}_audit.md` and display
it inline.

**Combined summary (multiple files):**

```
Audit Summary: {N} workbook(s)
══════════════════════════════════════════════════════

  Workbook                          Tables  Calcs  Coverage
  ─────────────────────────────────────────────────────────
  {workbook_1}                      {N}     {N}    {%}%
  {workbook_2}                      {N}     {N}    {%}%
  ...
  ─────────────────────────────────────────────────────────
  Total                             {N}     {N}    {%}%
```

After the audit, exit cleanly. Do NOT proceed to Migrate mode steps.

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

Each datasource is processed independently — **never merge datasources**. Even when
datasources share tables or point at the same database, each has its own join topology,
calculated fields, and column aliases. See `tableau-tml-rules.md` "One model per
Tableau datasource" for the full rule.

**Datasource type detection:**
- If the datasource contains `<connection class="sqlproxy">`, it is a **Published
  Datasource** (hosted on Tableau Server). The table name resolves to
  `connection.get('dbname')`, not the literal `[sqlproxy]`.
- If the datasource contains `<extract>`, it is an **Extract** — skip it (extracts
  are Tableau-local snapshots, not live connections to the warehouse).
- Otherwise, it is a **Live** datasource — proceed with extraction.

**Relation wrapper handling:** TWB XML wraps `<relation>` elements in one of three
structures. Check in order:
1. `_.fcp.ObjectModelEncapsulateLegacy.false...relation` tag
2. `_.fcp.ObjectModelEncapsulateLegacy.true...relation` tag
3. `<relation>` directly under `<connection class='federated'>` (fallback)

All three contain the same child elements — the wrapper determines where to look.

For each datasource, extract:

**Physical tables** — `<relation>` elements of `type="table"`:
- `name` attribute = table alias used in joins
- `table` attribute = fully-qualified physical table name — may be `[DB].[SCHEMA].[TABLE]`
  format; strip brackets and split on `.` to extract db, schema, and table components
- For Published Datasources (sqlproxy): if table name is `[sqlproxy]`, use
  `connection.get('dbname')` instead

**Custom SQL relations** — `<relation>` elements of `type="text"`:
- These contain raw SQL in the element text content — do NOT try to extract a table name
- Flag the relation as `source_type: "custom-sql"` and save the full SQL text
- Refactor the SQL: replace `<<` with `<`, `>>` with `>`, `==` with `=` (XML encoding
  artifacts from the TWB)
- These will generate a `sql_view:` TML instead of a `table:` TML (see Step 5c)
- Extract column names from the SQL `SELECT` clause aliases for column mapping

**Joins** — `<relation>` elements of `type="join"`:
- `join` attribute = join type (`inner` | `left` | `right` | `full`)
- `<clause>` child = join condition (decode HTML entities: `&quot;`→`"`,
  `&amp;`→`&`, `&lt;`→`<`, `&gt;`→`>`)
- Extract left and right table references from the clause

**Physical columns** — from `<metadata-records>` → `<metadata-record class="column">`:
- `local-name` = column identifier
- `remote-name` = physical column name in the database (use for `db_column_name`)
- `local-type` = Tableau data type
- `parent-name` = which table this column belongs to
- Also extract from `<column>` elements WITHOUT a `<calculation>` child:
  `name` (strip brackets), `datatype`, `role` (dimension/measure), `caption` (display name)

**Calculated fields** — `<column>` elements WITH a `<calculation class="tableau">` child:
- Skip columns where `param-domain-type` is `list` or `range` — these are Tableau
  parameters, not calculated fields
- `caption` or `name` = display name
- `calculation formula` attribute = Tableau expression (decode HTML entities)
- `datatype` attribute
- Build a cross-reference map: Tableau internal names (`[Calculation_1234567890]`) →
  display names. Calculated fields reference each other by internal ID in the TWB XML,
  not by display name — resolve these references before translating formulas.

**Parameters** — `<datasource name="Parameters">` children:
- `name`, `caption`, `datatype`, default value
- Log parameters for the limitations report — ThoughtSpot has its own parameter system
  and Tableau parameters cannot be auto-migrated

Save the parsed structure internally. Announce a summary:
> Parsed `{workbook_name}`: {N} datasource(s), {N} physical table(s),
> {N} calculated field(s), {N} join(s), {N} dashboard(s)

### 3c. Topological sort of calculated fields

Some calculated fields reference other calculated fields. Sort them so that fields
with no formula-dependencies come first (Level 0), then Level 1, etc. This determines
the order they must appear in the model TML `formulas` section.

Resolve all internal Tableau cross-references (`[Calculation_\d+]` → display name)
before sorting. The topological sort must use display names, not internal IDs.

### 3d. Dashboard metadata (for Step 8 decision)

Count `<dashboard>` elements in the TWB. Save the count and names — this is shown
in Step 8 when asking whether to migrate dashboards.

---

## Step 4 — Select ThoughtSpot Connection

List available connections and let the user select:

```bash
source ~/.zshenv && ts connections list --profile {profile_name}
```

`ts connections list` auto-paginates and returns all connections. Display the results
as a numbered list showing connection name, type, and database. If only one connection
exists, auto-select it and confirm with the user.

```
Available ThoughtSpot connections:

  1. SNOWFLAKE_PROD    (RDBMS_SNOWFLAKE)   — PROD_DB
  2. ANALYTICS_DW      (RDBMS_SNOWFLAKE)   — ANALYTICS_DB

Which connection should the generated tables use? (Enter number, or 'skip'):
```

Save the selected connection's exact `name` value as `{connection_name}`. This name is
used in SQL View TMLs (where `connection.name` is required) and for schema resolution.

If the user selects a connection, fetch the schema to resolve db/schema/table names:

```bash
source ~/.zshenv && ts connections get {connection_id} --profile {profile_name}
```

Parse the response to extract available databases, schemas, and table names. For each
physical table from Step 3, find the best match (case-insensitive) in the connection
schema. Save the resolved `{db}`, `{schema}`, and `{db_table}` for each table.

If the connection response has no tables (empty `externalDatabases`), ask the user for
the database and schema names directly.

If the user types **skip**: use `YOUR_DATABASE` and `YOUR_SCHEMA` as placeholders in
table TMLs — these produce a warning on validation, not an error. **Custom SQL relations
(Step 5c) still require a connection name** — if skipped, prompt for the connection name
string before generating SQL View TMLs.

---

## Step 5 — Generate TML Files

Create output directory:

```bash
mkdir -p /tmp/ts_tableau_mig/output/{workbook_name}
```

### 5a. Table TML — one per physical table (skip custom SQL relations)

For each physical table identified in Step 3 with `type="table"`, generate a
`.table.tml` file. **Skip custom SQL relations** — those are handled in Step 5c.

Follow all rules in `tableau-tml-rules.md`.

**Template:**

```yaml
table:
  name: TABLE_NAME
  db: RESOLVED_DATABASE
  schema: RESOLVED_SCHEMA
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
- Use `db`, `schema` values resolved from Step 4 — fall back to `YOUR_DATABASE` /
  `YOUR_SCHEMA` only when the connection was skipped
- Use `INT64` for Tableau `integer` — **never `INT`**
- `db_column_properties` is **required** on every column
- No `guid`, `fqn`, or `connection` sections

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{TABLE_NAME}.table.tml`.

### 5b. Model TML — one per datasource (strict separation)

For each datasource, generate exactly one `.model.tml` file. **Never merge multiple
datasources into a single model** — see `tableau-tml-rules.md` for the rationale.

The `model_tables[]` section references both regular tables (from Step 5a) and SQL
Views (from Step 5c) — both are referenced by `name` in the same way.

**Template:**

```yaml
model:
  name: "Datasource Display Name"
  model_tables:
  - name: TABLE_NAME
    joins:                      # only if this table has joins to others
    - with: OTHER_TABLE
      on: "[TABLE_NAME::JOIN_COL] = [OTHER_TABLE::JOIN_COL]"
      type: LEFT_OUTER          # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER
      cardinality: ONE_TO_MANY
  - name: OTHER_TABLE
  formulas:                     # omit section entirely if no translatable calculated fields
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
- Resolve Tableau internal IDs (`[Calculation_\d+]`) to display names before translating
- **LOD expressions** (`{FIXED}`, `{INCLUDE}`, `{EXCLUDE}`) → `group_aggregate()` — see
  the LOD section in `tableau-formula-translation.md`
- **Running calculations** (`RUNNING_SUM`, etc.) → `cumulative_sum()`, etc.
- **Rank functions** → `rank()`
- **Window functions** (WINDOW_SUM, WINDOW_AVG, etc.) → `moving_sum()`, `moving_average()`,
  etc. — requires identifying the sort dimension from the worksheet shelf. See "Window /
  Moving Functions" in `tableau-formula-translation.md`.
- **Pass-through fallback** for formulas with valid Snowflake SQL but no native ThoughtSpot
  function (partitioned RANK, DENSE_RANK, WINDOW_* when sort dimension is unknown): use
  `sql_*_aggregate_op()` pass-through functions — see "Pass-Through Fallback" in
  `tableau-formula-translation.md`. Always prefer native functions first.
- **Truly untranslatable formulas** (LOOKUP, INDEX, SIZE, PREVIOUS_VALUE, etc.): omit
  from `formulas[]` entirely, omit the corresponding `columns[]` entry, and log the
  omission for the Step 12 limitations report. Never generate a placeholder — incorrect
  syntax fails the entire model import.
- Every join MUST have a non-empty `on` field
- No `fqn` in `model_tables`
- `obj_id` is optional on fresh import — omit it unless repointing an existing model

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{DatasourceName}.model.tml`.

### 5c. SQL View TML — one per custom SQL relation

For each custom SQL relation identified in Step 3b (those with `source_type: "custom-sql"`),
generate a `.sql_view.tml` file. Follow the rules in `tableau-tml-rules.md` "SQL View
TML Rules" and the full schema in `thoughtspot-sql-view-tml.md`.

**Template:**

```yaml
sql_view:
  name: "Datasource Custom SQL"
  connection:
    name: "Connection Display Name"
  sql_query: |
    SELECT col1, col2, col3
    FROM catalog.schema.table_name
    WHERE condition = 'value'
  sql_view_columns:
  - name: COL1
    sql_output_column: col1
    data_type: VARCHAR
    properties:
      column_type: ATTRIBUTE
  - name: COL2
    sql_output_column: col2
    data_type: DOUBLE
    properties:
      column_type: MEASURE
      aggregation: SUM
```

Key rules:
- `connection.name` is **required** — use `{connection_name}` from Step 4
- `sql_query` contains the full SQL text from the Tableau `<relation>` element (decode
  HTML entities)
- `sql_output_column` must match a column name or alias from the SQL query output
- Map Tableau column datatypes to ThoughtSpot types using the same mapping as table TMLs
- No `db`, `schema`, `db_table`, or `db_column_properties` fields
- File extension: `*.sql_view.tml`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{Name}.sql_view.tml`.

The model TML (Step 5b) references these SQL Views by name in `model_tables[]`, just
like regular tables.

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
  - {N} SQL view TMLs (if any custom SQL relations)
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
  SQL Views imported:  {N} (or "none" if no custom SQL relations)
  Models imported:     {N}
  Liveboards imported: {N} (or "skipped")

  TML files: /tmp/ts_tableau_mig/output/{workbook_name}/
```

If any calculated fields were untranslatable (LOOKUP, INDEX, SIZE, PREVIOUS_VALUE, etc.),
any formulas used pass-through functions, or any formulas were omitted during Step 5b,
write a limitations file and display it. Include pass-through formulas in the report
(they work but require SQL Passthrough Functions to be enabled in ThoughtSpot admin):

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
| 1.1.0 | 2026-06-09 | Custom SQL → sql_view TML, connection listing, formula fallback, obj_id fix, datasource separation |
| 1.0.0 | 2026-06-09 | Initial release — merged from ts-model-from-tableau + ts-liveboard-from-tableau |
