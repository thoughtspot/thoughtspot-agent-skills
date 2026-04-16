---
name: ts-from-snowflake-sv
description: Convert a Snowflake Semantic View into a ThoughtSpot Model by reading the view DDL, mapping tables and joins, translating SQL expressions to ThoughtSpot formulas, and importing the model via the ThoughtSpot REST API.
---

# Snowflake Semantic View → ThoughtSpot Model

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the
semantic view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics
back to ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and
imports the result via `ts tml import`.

Two scenarios are supported:
- **Scenario A (existing tables):** ThoughtSpot Table objects already exist for the
  Snowflake objects the semantic view references. Reuses those existing Table objects.
- **Scenario B (new tables):** No ThoughtSpot Table objects exist yet for the Snowflake
  objects the semantic view references. Creates new Table objects pointing to those objects.

---

## References

| File | Purpose |
|---|---|
| [~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md) | Semantic View DDL parsing, model TML templates, type and aggregation mapping |
| [~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md](~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | SQL → ThoughtSpot formula translation rules (bidirectional reference) |
| [~/.claude/shared/worked-examples/snowflake/ts-from-snowflake.md](~/.claude/shared/worked-examples/snowflake/ts-from-snowflake.md) | End-to-end example: BIRD_SUPERHEROS_SV → ThoughtSpot Model (se-thoughtspot, inline joins, verified against live DDL) |
| [~/.claude/skills/thoughtspot-setup/SKILL.md](~/.claude/skills/thoughtspot-setup/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| [../references/direct-api-auth.md](../references/direct-api-auth.md) | Direct API authentication fallback when stored procedures are unavailable |
| [~/.claude/skills/snowflake-setup/SKILL.md](~/.claude/skills/snowflake-setup/SKILL.md) | Snowflake connection code, SQL execution patterns |

---

## Concept Mapping

| Snowflake Semantic View (real DDL format) | ThoughtSpot Model |
|---|---|
| `tables ( DB.SCHEMA.TABLE [primary key (col)] )` | `model_tables[]` — one entry per **physical ThoughtSpot table** |
| `primary key (col)` on a table | Identifies join target — not written into model TML directly |
| `dimensions ( TABLE.COL as view.NAME [comment='...'] )` | `columns[]` with `column_type: ATTRIBUTE` |
| Dimension with date/timestamp physical column | `columns[]` with `column_type: ATTRIBUTE` (ThoughtSpot infers date type) |
| `metrics ( TABLE.COL as SUM(view.NAME) )` | `columns[]` with `column_type: MEASURE` + aggregation |
| `metrics ( TABLE.COL as complex_sql_expr )` | `formulas[]` with translated ThoughtSpot formula |
| `relationships ( REL as FROM(FK) references TO(PK) )` | `referencing_join` in model_tables (Scenario A, pre-defined joins) OR `joins[]` inline (Scenario B) |
| `comment='...'` on a dimension/metric | ThoughtSpot column `name` (display name) |
| `with extension (CA='...')` | Not mapped to ThoughtSpot — logged in report |

**Key structural rules:**
- `column_id` must use the **column name from the ThoughtSpot Table TML**. Export
  Table TMLs to confirm — do not assume they match the semantic view left-hand side.
- Simple metrics (`AGG(view.col)` — one column, one aggregate) → `MEASURE` column.
  Complex expressions → `formulas[]` entry.
- In Scenario A, `referencing_join` points to a join pre-defined at the ThoughtSpot
  Table object level (found by exporting the FROM table's TML).
- In Scenario B / hybrid, inline `joins[]` on the FROM table entry (requires `with` field).

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege
- Authentication configured — run `/thoughtspot-setup` if you haven't already
- The `ts` CLI installed (`pip install -e /path/to/tools/ts-cli`)

### Snowflake

- Role with `USAGE` on the database and schema containing the semantic view
- Connection configured — run `/snowflake-setup` if you haven't already
- For Scenario B: role with `CREATE TABLE` or connection modification rights

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If profiles were already confirmed earlier in this conversation
(e.g. for a previous view in a batch), skip this step and reuse them.

**ThoughtSpot profile:**
1. Run `ts profiles list` to show configured profiles.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and confirm before proceeding.
4. Verify: `ts auth whoami --profile {name}` — print display_name and base URL.

**Snowflake profile:**
1. Read `~/.claude/snowflake-profiles.json` to list profiles.
2. If multiple: list and ask; if one: confirm.
3. Verify with a `SELECT CURRENT_USER(), CURRENT_ROLE()` query.

---

### Step 2: Identify the semantic view

If the user has named the semantic view, proceed directly to Step 3.

Otherwise, list available semantic views so the user can choose:

```sql
SHOW SEMANTIC VIEWS IN SCHEMA {database}.{schema};
```

If the database and schema are unknown, ask the user or run `SHOW DATABASES` /
`SHOW SCHEMAS IN DATABASE {db}` first.

Display results as a numbered list. Ask the user to select one (or enter a full
`database.schema.view_name` directly).

---

### Step 3: Get the semantic view DDL

```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{view_name}');
```

Store the returned DDL string in full — it will be parsed in the next step.

If the call fails with "object does not exist", verify the fully-qualified name and
the user's role has `USAGE` on the schema.

**Converting multiple views from the same schema?** Get all DDLs in one query:
```sql
SELECT view_name,
       GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.' || view_name) AS ddl
FROM {database}.information_schema.views
WHERE table_schema = '{schema}'
  AND table_type = 'SEMANTIC VIEW';   -- Snowflake filter for semantic views only
```
Parse each DDL in Step 4 before switching Snowflake queries.

---

### Step 4: Parse the DDL

Read and parse the DDL returned in Step 3. The DDL is a SQL `CREATE OR REPLACE
SEMANTIC VIEW` statement. See [~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md)
for the full format — it is NOT the hypothetical nested format; the real format has flat
`dimensions` and `metrics` sections at the view level.

Extract the following:

1. **View identity:** database, schema, view name.
2. **Tables block:** for each table entry, record:
   - Fully-qualified table reference (`DB.SCHEMA.TABLE`) — this is the Snowflake view/table
   - Table alias (explicit `ALIAS as DB.SCHEMA.TABLE`, or defaults to last segment of the name)
   - Primary key column(s) (if present — marks this as a join target)
3. **Relationships block:** for each relationship (`REL_NAME as FROM(COL) references TO(COL)`), record:
   - Relationship name, from table alias, from column, to table alias, to column
4. **Dimensions block** (flat, all tables): for each entry (`TABLE.COL as view_alias.NAME [comment='...']`), record:
   - Source: TABLE alias + VIEW column name (column in the Snowflake view layer)
   - Semantic alias: `view_alias.NAME`
   - Display name: value of `comment='...'`, or title-cased NAME
5. **Metrics block** (flat): for each entry (`TABLE.COL as AGG(view_alias.NAME)`), record:
   - Source: TABLE alias + VIEW column name
   - Aggregation: extracted from `AGG(...)`
   - Display name: from `comment='...'` or title-cased NAME
6. **Extension JSON** (`with extension (CA='...')`): parse for column type confirmation
   (dimensions / time_dimensions / metrics per table). Do not map to ThoughtSpot.

Build an internal map:
- `tables`: list of parsed table entries (alias → fully-qualified ref, primary key)
- `relationships`: list of (name, from_alias, from_col, to_alias, to_col)
- `columns` (flat): all dimensions and metrics, keyed by (table_alias, view_col)

---

### Step 5: Table registration question

After parsing, display the tables found and ask a single question:

```
The semantic view references {n} tables:
  {database}.{schema}.{TABLE_1}
  {database}.{schema}.{TABLE_2}
  ...

Are these tables already registered in ThoughtSpot?
  Y  Yes — use existing ThoughtSpot Table objects
  N  No  — create new Table objects from scratch
  ?  Not sure — search ThoughtSpot first

Enter Y / N / ?:
```

- **Y** → skip search, go to Step 6A (column verification only)
- **N** → skip search, go to Step 6B (create)
- **?** → go to Step 6A (search + verify)

---

### Step 6A: Discover and verify existing ThoughtSpot Table objects (Y and ? paths)

Skip this step if the user answered **N** in Step 5 — go directly to Step 6B.

**Search ThoughtSpot for all table objects:**

```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile {profile}
```

Filter the JSON to match each semantic view base table by database + schema + table name
(`metadata_header.database_stripes`, `metadata_header.schema_stripes`, `metadata_name`).
Build a map: `physical_table_name → {metadata_id, metadata_name}`.

**Export TMLs for all found tables in one call to verify columns:**

```bash
ts tml export {guid1} {guid2} ... --profile {profile}
```

Parse `table.columns[].name` from each returned TML. Build a column map per table:
`table_name → [col_name, ...]`. Compare against the columns referenced in
the semantic view dimensions and metrics to identify any column gaps.

> The `column_id` in the model TML must use the column names from the ThoughtSpot
> Table TML — export the TMLs to confirm them.

**Confirm the plan before making any changes:**

Show the user a full status table and wait for confirmation:

```
Table Plan:
  ✓  {TABLE_1}  — found (GUID: {guid}) — all {n} columns present → use as-is
  ⚠  {TABLE_2}  — found (GUID: {guid}) — missing {n} columns: {COL_A}, {COL_B} → update
  ✗  {TABLE_3}  — not found in ThoughtSpot → create new

Actions to be taken:
  • Update {TABLE_2}: add {n} missing columns
  • Create {TABLE_3}: {n} columns from Snowflake schema

No changes have been made yet. Proceed? (yes/no):
```

Do not proceed until the user confirms. If any table is **not found**, follow Step 6B
for those tables. If any table has **missing columns**, follow Step 6C before building
the model.

---

### Step 6C: Update existing tables with missing columns

For each table from Step 6A with a column gap, introspect the Snowflake schema
for the missing columns only:

```sql
SELECT table_name, column_name, data_type
FROM {database}.information_schema.columns
WHERE table_schema = '{SCHEMA}'
  AND table_name IN ({comma_quoted_table_names})
  AND column_name IN ({comma_quoted_missing_col_names})
ORDER BY table_name, ordinal_position;
```

Map Snowflake types to ThoughtSpot types using `~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md`.

Find the ThoughtSpot connection for those tables:
```bash
ts connections list --profile {profile}
```

Add the missing columns to the connection, then re-import the updated Table TML
for each affected table (batch all imports in one call):
```bash
ts tml import --policy ALL_OR_NONE --profile {profile}
```

After import, re-export the updated TMLs to refresh the column map before Step 8.

---

### Step 6B: Create ThoughtSpot Table objects for views (Scenario B)

**Do all Snowflake introspection in a batch query — not per-table calls.**

1. **Batch: get all column names and types for the entire schema in one query:**
   ```sql
   SELECT table_name, column_name, data_type
   FROM {database}.information_schema.columns
   WHERE table_schema = '{SCHEMA}'
   ORDER BY table_name, ordinal_position;
   ```
   This returns every column for every table/view in the schema in one round-trip.

2. Find the ThoughtSpot connection to use:
   ```bash
   ts connections list --profile {profile}
   ```
   Note the connection GUID (not just name) — use `fqn` in table TML for reliability.
   Ask the user to confirm which connection to use (or auto-select if only one matches
   the semantic view's database).

3. Create ThoughtSpot Table objects for all tables in one command:
   ```bash
   cat tables-spec.json | ts tables create --profile {profile}
   ```
   Where `tables-spec.json` is a JSON array built from the column data above.
   See `ts tables create --help` for the spec format. This command handles
   JDBC retry and GUID resolution automatically, and outputs `{name: guid}`.

4. Inline joins will be defined directly in the model TML (no `referencing_join`).

---

### Step 7: Find join names (Scenario A only)

For each relationship in the semantic view, find the name of the pre-defined join
in the ThoughtSpot Table objects.

**Re-use the TMLs already exported in Step 6A** — do not make another export call.
Parse the `edoc` YAML for each FROM table.

For a relationship `FROM {from_table} KEY {from_col} TO {to_table} KEY {to_col}`:

1. In the FROM table's `edoc` YAML, find the `joins` section.
2. Match the entry where `destination` equals the TO table name.
3. Record the join `name` — this is the `referencing_join` value for the `to_table`
   entry in the model TML.

If no matching join is found:
- Warn the user: "No pre-defined join from `{from_table}` to `{to_table}`."
- Options: (1) use an inline join instead (Scenario B for this relationship),
  (2) abort and define the join at the ThoughtSpot Table level first.

---

### Step 8: Build the model TML

Construct the model TML as a YAML string. Use the templates in
[~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md).

**Model name:** `TEST_SV_{view_name_title_case}` — prefix indicates this is a
test/converted model. Ask the user if they want a different name.

**Identify the fact table** (the table that is never on the "TO" side of any relationship)
— it gets no `referencing_join` and no `joins[]`.

**Critical `id` rules (applies to all scenarios):**
- All `id` values must be **lowercase**
- `id` values must be **unique** across all `model_tables` entries
- `name` values must also be **unique** — ThoughtSpot rejects models where two tables
  share the same `name` value ("Multiple tables have same alias")
- `name` must match the ThoughtSpot table object's name exactly (usually lowercase)
- If two semantic view tables map to the same ThoughtSpot table (same GUID), include
  it only ONCE and use ONE `id`/`name`

**Model TML skeleton (Scenario A — pre-defined joins exist in table TML):**

```yaml
model:
  name: "TEST_SV_{view_name}"
  model_tables:
  - id: fact_table          # lowercase
    name: fact_table        # ThoughtSpot table object name (lowercase)
    fqn: "{fact_guid}"      # GUID from Step 6A
  - id: dim_table           # lowercase
    name: dim_table         # ThoughtSpot table object name (lowercase)
    fqn: "{dim_guid}"       # GUID from Step 6A
    referencing_join: "{join_name}"   # from Step 7
  columns:
  - name: "{display_name}"
    column_id: fact_table::{col_name}  # col_name from ThoughtSpot Table TML
    properties:
      column_type: ATTRIBUTE
  - name: "{display_name}"
    column_id: fact_table::{col_name}
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - name: "{display_name}"
    expr: "{thoughtspot_formula}"
    properties:
      column_type: MEASURE
```

**Model TML skeleton (Scenario B / Hybrid — inline joins, or no pre-defined table joins):**

Use this when ThoughtSpot Table objects have no `joins_with` entries, or when creating
new Table objects for views. Inline joins live on the **source (FROM) table** entry.

```yaml
model:
  name: "TEST_SV_{view_name}"
  model_tables:
  - id: from_table          # lowercase, unique
    name: from_table        # ThoughtSpot table object name
    fqn: "{from_guid}"
    joins:
    - name: "{join_name}"
      with: to_table        # REQUIRED — must equal `id` of the target entry
      on: "[from_table::{fk_col}] = [to_table::{pk_col}]"  # uses id values, col names from ThoughtSpot Table TML
      type: INNER
      cardinality: MANY_TO_ONE
  - id: to_table            # matches `with` value above
    name: to_table
    fqn: "{to_guid}"
  columns:
  # ... same pattern as Scenario A ...
```

**Column entries:**

For each dimension in the semantic view:
- `name`: value of `comment='...'` on the dimension, or title-cased dimension name
- `column_id`: `{id}::{col_name}` — where `id` is the model_tables `id` for that
  table, and `col_name` is from the ThoughtSpot Table TML
- `column_type: ATTRIBUTE`

For each simple metric (`AGG(view_alias.metric_name)`):
- `name`: value of `comment='...'` on the metric, or title-cased metric name
- `column_id`: `{id}::{col_name}`
- `column_type: MEASURE`
- `aggregation`: mapped from the SQL aggregate function (see ts-from-snowflake-rules.md)

For each complex metric (formula expression):
- See Step 9 for translation. Results go into `formulas[]`.

---

### Step 9: Translate SQL expressions → ThoughtSpot formulas

For each metric whose `EXPR` is not a simple `AGG(table.col)`:

1. Apply the SQL → ThoughtSpot formula translation rules in
   [~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-from-snowflake-rules.md).
2. Replace column references: `table.COLUMN` → `[TABLE_ALIAS::COLUMN]`
3. If the expression translates successfully → add a `formulas[]` entry.
4. If the expression cannot be translated → omit the column and log it in the
   Formula Translation Log (for the summary report in Step 12).

**Column references in translated formulas:**

Use the TABLE_ALIAS from `model_tables` (the `id` field, which matches the semantic
view table alias). Column name is the column name from the EXPR (from the ThoughtSpot Table TML).

Example:
- Semantic view EXPR: `SUM(DM_ORDERDETAILS.UNIT_PRICE * DM_ORDERDETAILS.QUANTITY)`
- ThoughtSpot formula: `sum ( [DM_ORDERDETAILS::UNIT_PRICE] * [DM_ORDERDETAILS::QUANTITY] )`
- Add as `formulas[]` entry with `column_type: MEASURE`

---

### Step 10: Review checkpoint

Before importing, show the user a summary:

```
Model to import: TEST_SV_{view_name}
Tables:
  ✓ {FACT_TABLE} (GUID: {guid}) — fact table
  ✓ {DIM_TABLE}  (GUID: {guid}) — referencing_join: {join_name}
  ...

Columns ({n} total):
  ATTRIBUTE: {list of display names}
  MEASURE:   {list of display names}
  Formulas:  {list of display names}

Formula translations:
  ✓ {name}: {sql_expr} → {ts_formula}
  ⚠ {name}: OMITTED — {reason}

Proceed with import? (yes/no):
```

Wait for user confirmation before proceeding.

---

### Step 11: Import the model

**IMPORTANT — Updating vs creating:** Without a `guid` field in the TML, ThoughtSpot
always creates a **new** object, even if a model with the same name already exists.
To update an existing model in-place, add `guid` to the model dict:

```python
model_dict["guid"] = "{existing_model_guid}"   # omit on first import; required for all subsequent fixes
```

On the first import (new model), omit `guid`. After import, record the GUID from the
response — you will need it if you reimport to fix any errors.

Serialize the model TML dict to a YAML string, then import:

```python
import yaml, json, subprocess

model_tml = yaml.dump({"model": model_dict}, default_flow_style=False, allow_unicode=True)
payload = json.dumps([model_tml])

result = subprocess.run(
    ["ts", "tml", "import", "--policy", "ALL_OR_NONE", "--profile", profile_name],
    input=payload,
    capture_output=True,
    text=True,
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
| `referencing_join not found` | Join name is wrong or join doesn't exist at table level | Export table TML again and verify join name |
| `column_id not found` | Column name is wrong — left-hand side of semantic view dimension used instead of ThoughtSpot Table TML column name | Check Table TML for the correct column name |
| `Compulsory Field … joins(N)->with is not populated` | Missing `with` field on an inline join | Add `with: {target_id}` to every inline join entry |
| `{table_name} does not exist in schema` (on `with` field) | `with` value is wrong case or doesn't match any `id` | Ensure `with` matches the target's `id` exactly (lowercase) |
| `Invalid srcTable or destTable in join expression` | `on` clause references a table name that doesn't match any `id` in model_tables | Check that both `[table1::col]` refs in `on` use `id` values, not Snowflake table names |
| `Multiple tables have same alias {name}` | Two model_tables entries have the same `name` value | Deduplicate — if two aliases map to the same Snowflake object, keep only one entry |
| `fqn resolution failed` | GUID is stale or from a different ThoughtSpot instance | Re-run Step 6A to get fresh GUIDs |
| `formula syntax error` | ThoughtSpot formula has invalid syntax | Fix the formula expression |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars from all string values before serialising |

---

### Step 12: Produce summary report

After a successful import, output:

```
## Model Import Complete

**Model:** TEST_SV_{view_name}
**GUID:** {created_guid}
**ThoughtSpot URL:** {base_url}/#/model/{created_guid}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE ({agg}) | {TABLE}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |
| ... | ... | ... |

### Formula Translation Log
| Column | Original SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{sql}` | ✓ Translated | `{ts_formula}` |
| {name} | `{sql}` | ⚠ Omitted | {reason} |

### Not Mapped
- Extension JSON (Cortex Analyst context): not translated to ThoughtSpot
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

## Multiple semantic view conversion

If the user wants to convert more than one semantic view in the same session:

1. After completing Step 12 for the first view, ask: "Convert another semantic view?"
2. If yes: return to Step 2. Reuse the already-confirmed ThoughtSpot and Snowflake profiles.
3. Do not re-authenticate between views.
