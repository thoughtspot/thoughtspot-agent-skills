---
name: ts-convert-from-databricks-mv
description: Convert or import a Databricks Metric View into ThoughtSpot as a Model. Use when Databricks is the source and the goal is a ThoughtSpot Model — whether migrating Databricks metrics and semantic definitions into ThoughtSpot or making a Metric View available for Spotter and search-based analytics. Direction is always Databricks → ThoughtSpot. Not for ThoughtSpot → Databricks, standalone DDL generation, or adding AI context to existing ThoughtSpot models.
---

# Databricks Metric View → ThoughtSpot Model

Converts a Databricks Unity Catalog Metric View into a ThoughtSpot Model. Reads the
Metric View YAML definition via `DESCRIBE TABLE EXTENDED`, maps dimensions and measures
to ThoughtSpot columns and formulas, translates SQL expressions, and imports the result
via `ts tml import`.

Two scenarios are supported:
- **Scenario A (existing tables):** ThoughtSpot Table objects already exist for the
  Databricks source table(s) the Metric View references. Reuses those existing Table objects.
- **Scenario B (new tables):** No ThoughtSpot Table objects exist yet for the Databricks
  source table(s). Creates new Table objects pointing to those objects.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md) | Databricks MV YAML parsing, type mapping, formula translation, column classification |
| [../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md) | SQL → ThoughtSpot formula translation rules (bidirectional reference) |
| [../../shared/mappings/ts-databricks/ts-databricks-properties.md](../../shared/mappings/ts-databricks/ts-databricks-properties.md) | Property coverage — what maps, what doesn't, what is partially migrated |
| [../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md) | Databricks Metric View YAML schema (v0.1 single-source, v1.1 multi-source) |
| [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) | TML export parsing (PyYAML pitfalls, type detection) |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure, connection reference, data types, import patterns, common errors |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure, join scenarios, formula visibility, self-validation checklist |
| [../../shared/schemas/thoughtspot-formula-patterns.md](../../shared/schemas/thoughtspot-formula-patterns.md) | ThoughtSpot formula syntax, all function categories, LOD/window patterns, YAML encoding rules |
| [../ts-profile-databricks/SKILL.md](../ts-profile-databricks/SKILL.md) | Databricks auth methods, profile config, CLI usage |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |

---

## Concept Mapping

| Databricks Metric View (v0.1 YAML) | ThoughtSpot Model |
|---|---|
| `source:` (fully qualified table name) | Single Table TML — `db_table`, `db`, `schema` decomposed from the FQN |
| `dimensions[].expr` (direct column reference) | `columns[]` with `column_type: ATTRIBUTE` |
| `dimensions[].expr` (computed expression) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `measures[].expr` (simple `AGG(col)`) | `columns[]` with `column_type: MEASURE` + extracted `aggregation` |
| `measures[].expr` (complex — ratios, nested aggregates) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `filter:` (global WHERE clause) | Noted in model `description` — not enforced as a ThoughtSpot filter |
| `version:` | Drives parsing path (v0.1 vs v1.1) — not stored in ThoughtSpot |

**Key structural rules:**
- `column_id` must use the **column name from the ThoughtSpot Table TML**. Export
  Table TMLs to confirm — do not assume they match the Metric View column names.
- Simple measures (`AGG(col)` — one column, one aggregate) → `MEASURE` column.
  Complex expressions → `formulas[]` entry.
- In Scenario A, the Table TML already exists — reuse its GUID and column names.
- In Scenario B, create a new Table TML from the Databricks schema introspection.
- MV v0.1 has no synonyms, descriptions, or join definitions — these features are
  only available in v1.1 (not yet observed in production environments).

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege — **only required for import**
- Authentication configured — run `/ts-profile-thoughtspot` if you haven't already
- The `ts` CLI installed (`pip install -e /path/to/tools/ts-cli`)

**No ThoughtSpot import access?** You can still run this skill in **file-only mode** —
it generates the Table and Model TML files for you to import manually. Select **FILE**
at the Step 10 checkpoint or say "file only" at any point before Step 11.

### Databricks

- Databricks workspace with **Unity Catalog** enabled
- SQL warehouse on the **Preview channel** — Metric Views are a Preview feature;
  Current channel warehouses return `PARSE_SYNTAX_ERROR`
- Databricks CLI installed and profile configured — run `/ts-profile-databricks` if
  you haven't already
- A Databricks connection configured in ThoughtSpot (required for Scenario B table creation)

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-from-databricks-mv** — convert a Databricks Metric View into a ThoughtSpot Model, translating dimensions, measures, and SQL expressions.

Steps:
  1.   Authenticate (ThoughtSpot + Databricks) .............. auto
  2.   List Metric Views in the catalog ..................... auto
  3.   Select a Metric View ................................. you choose
  4.   Fetch the Metric View definition ..................... auto
  5.   Parse the YAML (dimensions, measures, filter) ........ auto
  6.   Map to ThoughtSpot columns + translate expressions .... auto
  7.   Table registration question (reuse or create) ........ you choose
  8.   Discover / create ThoughtSpot Table objects ........... auto (may ask for clarification)
  9.   Build Table TML (if needed) and Model TML ............ auto
  9.5. Confirm Spotter enablement (default: enabled) ........ you choose
 10.   Review checkpoint — inspect TML before import ......... you confirm
 11.   Import Table TML(s) + Model TML via ts tml import ..... auto
 12.   Verify import and produce summary report .............. auto

File-only mode: at Step 10, choose FILE to write TML files for manual import.

Confirmation required: Steps 3, 7, 9.5, 10
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If profiles were already confirmed earlier in this conversation
(e.g. for a previous Metric View), skip this step and reuse them.

**ThoughtSpot profile:**
1. Run `ts profiles list` to show configured profiles.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and confirm before proceeding.
4. Verify: `ts auth whoami --profile {name}` — print display_name and base URL.

**Databricks profile:**

Load the profile from `~/.claude/databricks-profiles.json`:

```python
import json, os

profiles_path = os.path.expanduser("~/.claude/databricks-profiles.json")
with open(profiles_path) as f:
    profiles = json.load(f)

# Display profiles for selection
for i, p in enumerate(profiles, 1):
    print(f"  {i}. {p['name']}  ({p.get('host', '')})")

profile = next(p for p in profiles if p["name"] == "{profile_name}")
dbx_profile = profile["dbx_profile"]
catalog = profile.get("default_catalog", "")
warehouse_path = profile.get("sql_warehouse_http_path", "")
warehouse_id = warehouse_path.rstrip("/").split("/")[-1] if warehouse_path else ""
```

Verify connectivity:

```bash
source ~/.zshenv && databricks auth describe --profile {dbx_profile}
```

Store `dbx_profile`, `catalog`, and `warehouse_id` for use in subsequent steps.

---

### SQL execution pattern

All Databricks SQL in this skill uses the Statement Execution API:

```bash
source ~/.zshenv && databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{"warehouse_id": "{warehouse_id}", "statement": "{sql}", "wait_timeout": "50s"}'
```

The response contains:
```json
{
  "status": {"state": "SUCCEEDED"},
  "manifest": {"schema": {"columns": [...]}},
  "result": {"data_array": [[...], ...]}
}
```

If `status.state` is `PENDING`, poll the statement ID:
```bash
source ~/.zshenv && databricks api get /api/2.0/sql/statements/{statement_id} --profile {dbx_profile}
```

---

### Step 2: List Metric Views

Query the catalog for available Metric Views:

```sql
SELECT table_catalog, table_schema, table_name
FROM system.information_schema.tables
WHERE table_type = 'METRIC_VIEW'
  AND table_catalog = '{catalog}'
```

Execute via the SQL execution pattern above. Display results as a numbered list:

```
Metric Views in {catalog}:
  1. {schema}.{view_name_1}
  2. {schema}.{view_name_2}
  ...
```

If no Metric Views are found, check:
- The catalog name is correct
- The SQL warehouse is on the Preview channel
- The user's role has `USE CATALOG` and `USE SCHEMA` grants

---

### Step 3: Select a Metric View

If the user has already named a Metric View, skip this step.

Otherwise, ask the user to select from the list displayed in Step 2 (enter a number
or type a fully qualified `catalog.schema.view_name` directly).

Store the selected `{catalog}`, `{schema}`, and `{view_name}` for subsequent steps.

---

### Step 4: Fetch the Metric View definition

Retrieve the YAML definition via `DESCRIBE TABLE EXTENDED`:

```sql
DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}
```

Execute via the SQL execution pattern. Parse the response `result.data_array` — each
row is `[col_name, data_type, comment, metadata]`.

Extract the definition:
1. Find the row where `col_name == 'View Text'` — the `data_type` column contains
   the full YAML string.
2. Find the row where `col_name == 'Type'` — confirm `data_type == 'METRIC_VIEW'`.
3. Store the YAML string for parsing in Step 5.

If the query fails with "table or view not found", verify the fully-qualified name
and confirm the user's role has `SELECT` on the view.

---

### Step 5: Parse the YAML

Parse the YAML string extracted in Step 4. The Metric View YAML follows the schema
documented in [../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md).

```python
import yaml

mv_yaml = yaml.safe_load(yaml_string)

version = mv_yaml.get("version", "0.1")
source_fqn = mv_yaml.get("source", "")          # v0.1: "catalog.schema.table"
entities = mv_yaml.get("entities", [])            # v1.1: list of entity defs
dimensions = mv_yaml.get("dimensions", [])
measures = mv_yaml.get("measures", [])
mv_filter = mv_yaml.get("filter", "")
```

**Version routing:**
- `version: 0.1` → single-source parsing path (all observed production MVs)
- `version: 1.1` → multi-source parsing path (from documentation, not yet observed live)

**v0.1 — single source:**

1. Decompose `source` FQN into `catalog`, `schema`, `table_name`:
   ```python
   parts = source_fqn.split(".")
   src_catalog, src_schema, src_table = parts[0], parts[1], parts[2]
   ```

2. For each dimension, classify:
   - **Direct column reference** (single identifier, no functions): `expr` is a physical
     column name → maps to `ATTRIBUTE` column with `column_id` pointing to the physical column.
   - **Computed expression** (contains functions, operators, CASE): → maps to a `formulas[]`
     entry with a translated ThoughtSpot formula + a `columns[]` entry with `formula_id`.

3. For each measure, classify:
   - **Simple aggregate** (`AGG(column_name)` or `AGG(DISTINCT column_name)`): extract the
     aggregate function → `aggregation` field, extract inner column → `column_id`.
   - **Complex expression** (ratios, nested aggregates, arithmetic inside aggregate): → maps
     to a `formulas[]` entry + `columns[]` with `formula_id`.

4. Record the global `filter` (if present) for inclusion in the model description.

Build an internal map:
- `source_table`: catalog, schema, table_name
- `dimensions_parsed`: list of `{name, expr, is_direct, physical_col_or_formula}`
- `measures_parsed`: list of `{name, expr, is_simple, agg_function, physical_col_or_formula}`
- `filter_expr`: the global filter string (or empty)

**v1.1 — multi-source (when encountered):**

Follow the entity-based parsing documented in
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md)
(v1.1 Parsing section). Map entities to Table TMLs, extract primary/foreign key
relationships for join definitions.

---

### Step 6: Map to ThoughtSpot columns and translate expressions

Apply the classification from Step 5 to build ThoughtSpot column and formula entries.
Use the translation rules in
[../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md).

**Dimensions:**

For each dimension:

| Dimension type | ThoughtSpot mapping |
|---|---|
| Direct column (`expr: region`) | `columns[]` entry: `column_id: {table}::{region}`, `column_type: ATTRIBUTE` |
| Computed (`expr: date_trunc('day', col)`) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` |

**Measures:**

For each measure:

| Measure type | ThoughtSpot mapping |
|---|---|
| Simple `SUM(col)` | `columns[]` entry: `column_id: {table}::{col}`, `column_type: MEASURE`, `aggregation: SUM` |
| Simple `COUNT(DISTINCT col)` | `columns[]` entry: `column_id: {table}::{col}`, `column_type: MEASURE`, `aggregation: COUNT_DISTINCT` |
| Simple `AVG(col)` | `columns[]` entry: `column_id: {table}::{col}`, `column_type: MEASURE`, `aggregation: AVERAGE` |
| Complex expression | `formulas[]` entry with translated expression + `columns[]` with `formula_id` |

**Aggregate extraction mapping:**

| Databricks aggregate | ThoughtSpot `aggregation` |
|---|---|
| `SUM` | `SUM` |
| `COUNT` | `COUNT` |
| `COUNT(DISTINCT ...)` | `COUNT_DISTINCT` |
| `AVG` | `AVERAGE` |
| `MIN` | `MIN` |
| `MAX` | `MAX` |

> **MANDATORY — read the reference before assessing any expression:**
> Open [../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md)
> and use its **Databricks → TS** sections for each SQL pattern. Do **not** classify
> an expression as untranslatable based on SQL syntax recognition alone.

**Formula translation examples:**

| Databricks `expr` | ThoughtSpot formula |
|---|---|
| `date_trunc('day', transaction_date)` | `date ( [TABLE::transaction_date] )` |
| `date_trunc('month', col)` | `start_of_month ( [TABLE::col] )` |
| `CASE WHEN x > 10 THEN 'High' ELSE 'Low' END` | `if ( [TABLE::x] > 10 , 'High' , 'Low' )` |
| `SUM(price * quantity * (1 - discount))` | `sum ( [TABLE::price] * [TABLE::quantity] * ( 1 - [TABLE::discount] ) )` |
| `SUM(x) / COUNT(DISTINCT y)` | `sum ( [TABLE::x] ) / unique count ( [TABLE::y] )` |

**Column references in translated formulas:**

Use the `name:` from the corresponding `model_tables[]` entry. Column name is the
column name from the ThoughtSpot Table TML.

Example:
- MV EXPR: `SUM(product_price * quantity * (1 - discount_percent))`
- ThoughtSpot formula: `sum ( [ECOMMERCE_TRANSACTIONS::product_price] * [ECOMMERCE_TRANSACTIONS::quantity] * ( 1 - [ECOMMERCE_TRANSACTIONS::discount_percent] ) )`

**`last_value` / curly brace formulas — YAML block scalar required:**

When the translated formula contains `{ [col] }` (curly braces), use a `>-` block scalar
for the `expr` field. Inline YAML string assignment fails because `{` is a flow mapping
start character:

```yaml
formulas:
- name: "Running Balance"
  expr: >-
    last_value ( sum ( [TABLE::balance] ) , query_groups ( ) , { [TABLE::date_col] } )
  properties:
    column_type: MEASURE
```

In Python, set the formula string in the dict as a plain string — `yaml.dump` will emit
it as a block scalar automatically when the string contains `{`. If it doesn't, force it:

```python
from yaml.representer import SafeRepresenter

def literal_representer(dumper, data):
    if '{' in data or '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='>')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, literal_representer)
```

---

### Step 7: Table registration question

After mapping, display the source table(s) and ask:

**v0.1 (single source):**

```
The Metric View references 1 source table:
  {catalog}.{schema}.{table_name}

Is this table already registered in ThoughtSpot?
  Y  Yes — use existing ThoughtSpot Table object
  N  No  — create a new Table object from scratch
  ?  Not sure — search ThoughtSpot first

Enter Y / N / ?:
```

**v1.1 (multi-source):**

List all entities and ask the same question.

- **Y** → skip search, go to Step 8A (column verification only)
- **N** → skip search, go to Step 8B (create)
- **?** → go to Step 8A (search + verify)

---

### Step 8A: Discover and verify existing ThoughtSpot Table objects (Y and ? paths)

Skip this step if the user answered **N** in Step 7 — go directly to Step 8B.

**Search ThoughtSpot for table objects:**

```bash
source ~/.zshenv && ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile {profile}
```

Filter the JSON to match the MV source table by database + schema + table name
(`metadata_header.database_stripes`, `metadata_header.schema_stripes`, `metadata_name`).
Build a map: `physical_table_name -> {metadata_id, metadata_name}`.

**Export TMLs for found tables to verify columns:**

```bash
source ~/.zshenv && ts tml export {guid1} {guid2} ... --profile {profile} --parse
```

`--parse` returns structured JSON — access columns via `item["tml"]["table"]["columns"]`
directly. Parse `table.columns[].name` from each returned item. Build a column map:
`table_name -> [col_name, ...]`. Compare against the columns referenced in the MV
dimensions and measures to identify any column gaps.

> The `column_id` in the model TML must use the column names from the ThoughtSpot
> Table TML — export the TMLs to confirm them.

**Confirm the plan before making any changes:**

```
Table Plan:
  ✓  {TABLE_NAME}  — found (GUID: {guid}) — all {n} columns present → use as-is
  ⚠  {TABLE_NAME}  — found (GUID: {guid}) — missing {n} columns: {COL_A}, {COL_B} → update
  ✗  {TABLE_NAME}  — not found in ThoughtSpot → create new

Actions to be taken:
  • Update {TABLE_NAME}: add {n} missing columns
  • Create {TABLE_NAME}: {n} columns from Databricks schema

No changes have been made yet. Proceed? (yes/no):
```

Do not proceed until the user confirms. If any table is **not found**, follow Step 8B
for those tables. If any table has **missing columns**, follow Step 8C before building
the model.

---

### Step 8B: Create ThoughtSpot Table objects (Scenario B)

**Get all column names and types for the source table:**

```sql
DESCRIBE TABLE {catalog}.{schema}.{table_name}
```

Execute via the SQL execution pattern. The response `data_array` contains rows
`[col_name, data_type, comment]`. Map Databricks types to ThoughtSpot types using
the data type mapping in
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md).

Ask the user to confirm which ThoughtSpot connection to use (or auto-select if only
one Databricks connection exists):

```bash
source ~/.zshenv && ts connections list --profile {profile}
```

`ts connections list` auto-paginates and returns all connections. Filter for Databricks
connections. Display matching connections and ask the user to confirm. Once confirmed,
use the exact `name` value from the API response.

Create the ThoughtSpot Table object:

```bash
cat tables-spec.json | source ~/.zshenv && ts tables create --profile {profile}
```

Where `tables-spec.json` is a JSON array built from the column data. See
`ts tables create --help` for the spec format. This command handles JDBC retry and
GUID resolution automatically, and outputs `{name: guid}`.

Record the created GUID for use in the model TML.

---

### Step 8C: Update existing tables with missing columns

For each table from Step 8A with a column gap, introspect the Databricks schema
for the missing columns:

```sql
DESCRIBE TABLE {catalog}.{schema}.{table_name}
```

Filter the result to the missing column names. Map Databricks types to ThoughtSpot
types using [../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md).

Find the ThoughtSpot connection for the table:
```bash
source ~/.zshenv && ts connections list --profile {profile}
```

Add the missing columns to the connection, then re-import the updated Table TML
(batch all imports in one call):
```bash
source ~/.zshenv && ts tml import --policy ALL_OR_NONE --profile {profile}
```

After import, re-export the updated TMLs to refresh the column map before Step 9.

---

### Step 9: Build the Model TML

Construct the model TML as a YAML string. Use the templates in
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md).

**Model name:** `TEST_MV_{view_name_title_case}` — prefix indicates this is a
test/converted model. Ask the user if they want a different name.

**Model description:** Include the MV filter (if present) and source metadata:

```python
desc_parts = [f"Imported from Databricks Metric View: {catalog}.{schema}.{view_name}"]
if mv_filter:
    desc_parts.append(f"Filter: {mv_filter}")
model_description = " | ".join(desc_parts)
```

**Critical `id` rules (applies to all scenarios):**
- **`id` must equal `name` exactly** (same case, same characters). ThoughtSpot resolves
  `with` and `on` join references against the table's actual `name` — if `id` differs
  in case, joins fail with "{table_name} does not exist in schema". Use the exact
  ThoughtSpot table object name for both `id` and `name`.
- `id` values must be **unique** across all `model_tables` entries
- `name` values must also be **unique** — ThoughtSpot rejects models where two tables
  share the same `name` value ("Multiple tables have same alias")

**Model TML skeleton (v0.1 — single source, Scenario A):**

```yaml
model:
  name: "TEST_MV_{view_name}"
  description: "Imported from Databricks Metric View: {catalog}.{schema}.{view_name} | Filter: {filter}"
  model_tables:
  - id: SOURCE_TABLE          # MUST equal name exactly
    name: SOURCE_TABLE        # exact ThoughtSpot table object name
    fqn: "{table_guid}"       # GUID from Step 8A
  columns:
  - name: "{dimension_display_name}"
    column_id: SOURCE_TABLE::{physical_col}
    properties:
      column_type: ATTRIBUTE
  - name: "{measure_display_name}"
    column_id: SOURCE_TABLE::{physical_col}
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - id: "formula_{formula_name}"
    name: "{formula_name}"
    expr: "{translated_ts_formula}"
    properties:
      column_type: MEASURE
```

**Model TML skeleton (v1.1 — multi-source, inline joins):**

```yaml
model:
  name: "TEST_MV_{view_name}"
  description: "Imported from Databricks Metric View: {catalog}.{schema}.{view_name}"
  model_tables:
  - id: PRIMARY_TABLE
    name: PRIMARY_TABLE
    fqn: "{primary_guid}"
    joins:
    - name: "{join_name}"
      with: DIM_TABLE       # REQUIRED — must equal `id` (= `name`) of the target entry
      on: "[PRIMARY_TABLE::{fk_col}] = [DIM_TABLE::{pk_col}]"
      type: INNER
      cardinality: MANY_TO_ONE
  - id: DIM_TABLE
    name: DIM_TABLE
    fqn: "{dim_guid}"
  columns:
  # ... same pattern as single source ...
```

**Every formula must have a `columns[]` entry.** Add a `columns[]` entry with
`formula_id:` for every entry in `formulas[]`:

```yaml
formulas:
- id: formula_Total Sales
  name: "Total Sales"
  expr: >-
    sum ( [ECOMMERCE_TRANSACTIONS::product_price] * [ECOMMERCE_TRANSACTIONS::quantity] * ( 1 - [ECOMMERCE_TRANSACTIONS::discount_percent] ) )
  properties:
    column_type: MEASURE

columns:
# ... physical columns ...
- name: "Total Sales"
  formula_id: formula_Total Sales   # must match the formula's `id` exactly
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX   # recommended for computed numeric measures
```

`aggregation:` on a `columns[]` formula entry is allowed (unlike in `formulas[]` entries
where it causes an import error).

- **Never add `aggregation:` to a `formulas[]` entry** — formulas are self-contained
  via their `expr`. ThoughtSpot rejects TML with `FORMULA is not a valid aggregation type`.

---

### Step 9.5: Spotter enablement

Before assembling the final TML, ask whether Spotter (AI search) should be enabled
for this model. Default is **yes** — Spotter is the primary natural-language
interface for Models, and a converted MV usually exists to be queried this way.

```
Enable Spotter (AI search) for this model? [Y / n] (default: Y)
```

Apply the answer to the model TML's properties block:

```yaml
model:
  name: TEST_MV_{view_name}
  # ... model_tables, columns, formulas, etc.
  properties:
    spotter_config:
      is_spotter_enabled: true   # or false based on answer
```

If the user answers `n` or `no`, set `is_spotter_enabled: false`.

---

### Step 10: Review checkpoint

Before importing, show the user a summary:

```
Model to import: TEST_MV_{view_name}
Source: {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
Filter: {filter_expr or "none"}

Tables:
  ✓ {TABLE_NAME} (GUID: {guid}) — source table

Columns ({n} total):
  ATTRIBUTE: {list of display names}
  MEASURE:   {list of display names}
  Formulas:  {list of display names}

Formula translations:
  ✓ {name}: {dbx_expr} → {ts_formula}
  ⚠ {name}: OMITTED — {reason}

Spotter (AI search): enabled / disabled

Proceed with import?
  yes  — import to ThoughtSpot
  no   — cancel
  file — write TML files without importing (for environments where you lack
          DATAMANAGEMENT access, or to review the TML before committing)
```

Wait for user confirmation before proceeding.

If the user selects **file**, skip to [Step 10-FILE](#step-10-file-output-tml-files-file-only-mode).

---

### Step 10-FILE: Output TML files (file-only mode)

This path is used when the user selected **file** at the Step 10 checkpoint, explicitly
said "file only", or has no ThoughtSpot `DATAMANAGEMENT` access.

**1. Determine output filenames:**

- Model TML: `{model_name}.model.tml`
- Any new Table TMLs created in Step 8B (Scenario B): `{table_name}.table.tml`

**2. Write the files:**

```python
from pathlib import Path
import yaml

# Model TML
model_tml_str = yaml.dump(
    {"model": model_dict}, default_flow_style=False, allow_unicode=True
)
Path(f"{model_name}.model.tml").write_text(model_tml_str, encoding="utf-8")

# Table TMLs (Scenario B only)
for tbl_name, tbl_dict in new_table_tmls.items():
    tbl_str = yaml.dump(
        {"table": tbl_dict}, default_flow_style=False, allow_unicode=True
    )
    Path(f"{tbl_name}.table.tml").write_text(tbl_str, encoding="utf-8")
```

**3. Report:**

```
TML files written:
  {model_name}.model.tml    — ThoughtSpot Model TML
  {table_name}.table.tml   — ThoughtSpot Table TML (if new tables were needed)

To import to ThoughtSpot when you have access:

  1. Package all .tml files into a zip:
       zip {model_name}_tml.zip *.tml

  2. In ThoughtSpot: Data → TML Import → upload the zip
     (table TMLs will import first, then the model)

  3. Or import via CLI:
       ts tml import --file {model_name}.model.tml --policy ALL_OR_NONE --profile {profile}

  Note: On first import, omit `guid` from the TML (already omitted here). ThoughtSpot
  will assign a GUID — save it from the import response if you need to update the model later.
```

**4. Proceed to Step 12** (Produce summary report) — include the formula translation log
and column summary so the user has the full picture before importing.

---

### Step 11: Import the model

**IMPORTANT — Updating vs creating:** Without a `guid` field in the TML, ThoughtSpot
always creates a **new** object, even if a model with the same name already exists.
To update an existing model in-place, add `guid` at the **document root** — as a
top-level key alongside `model:`, NOT nested inside `model:`:

```python
# CORRECT — guid at document root
top_level = {"guid": "{existing_model_guid}", "model": model_dict}

# WRONG — guid nested under model (silently ignored by ThoughtSpot)
# model_dict["guid"] = "..."   <- do NOT do this
```

On the first import (new model), omit `guid`. After import, record the GUID from the
response — you will need it if you reimport to fix any errors.

Serialize the top-level dict to a YAML string, then import:

```python
import yaml, json, subprocess

# First import (new model):
top_level = {"model": model_dict}
# Update existing model:
top_level = {"guid": existing_guid, "model": model_dict}

model_tml = yaml.dump(top_level, default_flow_style=False, allow_unicode=True)
payload = json.dumps([model_tml])

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml import --policy ALL_OR_NONE --profile '{profile_name}'"],
    input=payload,
    capture_output=True, text=True,
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
```

On success, parse the response JSON to extract the created model's GUID. **Save it** —
required for any future reimports to update the model without creating a duplicate.

**Common import errors:**

| Error | Likely cause | Fix |
|---|---|---|
| `column_id not found` | Column name is wrong — MV dimension name used instead of ThoughtSpot Table TML column name | Export Table TML and verify column names |
| `Compulsory Field ... joins(N)->with is not populated` | Missing `with` field on an inline join | Add `with: {target_id}` to every inline join entry |
| `{table_name} does not exist in schema` (on `with` field) | `with` value doesn't match any `id` in model_tables | Ensure `with` matches the target's `id` exactly — same case as `name` |
| `Invalid srcTable or destTable in join expression` | `on` clause references a table name that doesn't match any `id` | Check that both `[table::col]` refs in `on` use `id` values |
| `Multiple tables have same alias {name}` | Two model_tables entries have the same `name` value | Deduplicate — keep only one entry |
| `fqn resolution failed` | GUID is stale or from a different ThoughtSpot instance | Re-run Step 8A to get fresh GUIDs |
| `formula syntax error` | ThoughtSpot formula has invalid syntax | Fix the formula expression |
| YAML mapping error on formula with `{` | Formula with `{ [col] }` emitted as inline YAML string | Use `>-` block scalar for `expr` — see Step 6 |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars from all string values before serialising |

---

### Step 11b: Verify Import

After a successful import response, confirm the model was indexed and has the expected
shape — not just that the API returned 200.

**1. Search for the model by GUID:**

```bash
source ~/.zshenv && ts metadata search --subtype WORKSHEET --name "%TEST_MV_{view_name}%" --profile {profile}
```

The GUID returned by the import response must appear in the results. If it is absent,
the import succeeded at the API level but indexing is delayed — wait 5 seconds and
retry once.

**2. Export the imported model and count columns:**

```bash
source ~/.zshenv && ts tml export {created_guid} --fqn --profile {profile}
```

Parse the returned TML and count `model.columns[]` entries. This count must be >= the
number of translatable fields from the MV (total dimensions + measures, minus any
omitted from the untranslatable list in Step 6).

If the column count is lower than expected: compare the exported TML against the TML
sent in Step 11 to identify which columns ThoughtSpot silently dropped, and investigate.

**3. Report the model URL:**

```
Model imported successfully.

  Name:    TEST_MV_{view_name}
  GUID:    {created_guid}
  URL:     {base_url}/#/model/{created_guid}

Open the URL in a browser to verify the model appears in the ThoughtSpot Data panel.
```

---

### Step 12: Produce summary report

After a successful import (or file output), generate:

```
## Model Import Complete

**Model:** TEST_MV_{view_name}
**GUID:** {created_guid}
**ThoughtSpot URL:** {base_url}/#/model/{created_guid}
**Source:** {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
**Filter:** {filter_expr or "none"}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE ({agg}) | {TABLE}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |
| ... | ... | ... |

### Formula Translation Log
| Column | Original Databricks SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{expr}` | ✓ Translated | `{ts_formula}` |
| {name} | `{expr}` | ⚠ Omitted | {reason} |

### Not Mapped
- Global filter: "{filter_expr}" — noted in model description, not enforced as a ThoughtSpot filter
- MV `version` field — metadata only, not stored in ThoughtSpot
```

**Test questions:** Suggest 3-5 natural language questions the user can try in Spotter
to verify the model works. Base them on the dimensions and measures present:

```
### Suggested test questions for Spotter
1. "What is the total {measure_1} by {dimension_1}?"
2. "Show me {measure_2} for each {dimension_2}"
3. "What are the top 10 {dimension_1} by {measure_1}?"
```

---

### Step 13: Cleanup

Remove any temporary files written during the workflow:

```bash
rm -f /tmp/ts_model_build_*.yaml /tmp/ts_model_build_*.json
```

The `ts` CLI manages its own token cache — do not remove `/tmp/ts_token_*.txt`
unless the user explicitly requests a logout.

---

## Multiple Metric View conversion

After completing Step 12 for one view, ask:
"Convert another Metric View?" If yes: return to Step 2. Reuse the already-confirmed
ThoughtSpot and Databricks profiles. Do not re-authenticate between views.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-05-22 | Initial release — single conversion mode (Mode A) |
