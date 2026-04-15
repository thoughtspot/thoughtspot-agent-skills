---
name: thoughtspot-model-from-semantic-view
description: Convert a Snowflake Semantic View into a ThoughtSpot Model by reading the view DDL, mapping tables and joins, translating SQL expressions to ThoughtSpot formulas, and importing the model via the ThoughtSpot REST API.
---

# Snowflake Semantic View → ThoughtSpot Model

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the
semantic view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics
back to ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and
imports the result via `ts tml import`.

Two scenarios are supported:
- **Scenario A (underlying tables):** Build the model on top of the physical tables
  already registered in a ThoughtSpot connection. Reuses existing ThoughtSpot Table
  objects and their pre-defined joins.
- **Scenario B (views):** Build the model on top of the Snowflake views that the
  semantic view's `base_table` references. Creates new ThoughtSpot Table objects
  and registers the views in the connection.

---

## References

| File | Purpose |
|---|---|
| [references/reverse-mapping-rules.md](references/reverse-mapping-rules.md) | Semantic View DDL parsing, SQL → ThoughtSpot formula translation, model TML templates |
| [references/worked-example.md](references/worked-example.md) | End-to-end example: DUNDER_MIFFLIN_SALES → ThoughtSpot Model |
| [~/.claude/skills/thoughtspot-setup/SKILL.md](~/.claude/skills/thoughtspot-setup/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| [~/.claude/skills/snowflake-setup/SKILL.md](~/.claude/skills/snowflake-setup/SKILL.md) | Snowflake connection code, SQL execution patterns |

---

## Concept Mapping

| Snowflake Semantic View | ThoughtSpot Model |
|---|---|
| `TABLES ( ... BASE TABLE db.schema.tbl )` | `model_tables[]` — one entry per table |
| `PRIMARY KEY ( col )` | Identifies join target tables — not directly in model TML |
| `DIMENSIONS ( col DATA_TYPE = TEXT )` | `columns[]` with `column_type: ATTRIBUTE` |
| `DIMENSIONS ( col DATA_TYPE = DATE )` | `columns[]` with `column_type: ATTRIBUTE` (date type inferred) |
| `DIMENSIONS ( col DATA_TYPE = TIMESTAMP )` | `columns[]` with `column_type: ATTRIBUTE` (datetime type) |
| `METRICS ( name EXPR = AGG(tbl.col) )` | `columns[]` with `column_type: MEASURE` + aggregation |
| `METRICS ( name EXPR = complex_sql )` | `formulas[]` with translated ThoughtSpot formula |
| `RELATIONSHIPS ( ... FROM tbl KEY col TO tbl KEY col )` | `referencing_join` in model_tables (Scenario A) or inline joins (Scenario B) |
| `ALIASES = ( alias1, alias2 )` | Display name override via `name:` in columns — first alias used as display name |
| `EXTENSION = '{"cortex_analyst_context": ...}'` | Not mapped to ThoughtSpot — logged in report |

**Key structural rules:**
- The first alias in `ALIASES = (...)` becomes the model column `name` (display name).
  The physical column name becomes the `column_id` pointer.
- Simple metrics (`AGG(table.col)` — single column, single aggregation function) →
  `MEASURE` column. Complex expressions → `formulas[]` entry.
- In Scenario A, `referencing_join` in a model_table entry points to a join that was
  pre-defined at the ThoughtSpot Table object level. Find it by exporting TML for the
  "from" table in the relationship.

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege
- Authentication configured — run `/thoughtspot-setup` if you haven't already
- The `ts` CLI installed (`pip install -e /path/to/cli`)

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

---

### Step 4: Parse the DDL

Read and parse the DDL returned in Step 3. The DDL is a SQL `CREATE OR REPLACE
SEMANTIC VIEW` statement. See [references/reverse-mapping-rules.md](references/reverse-mapping-rules.md)
for the full DDL format and parsing rules.

Extract the following:

1. **View identity:** database, schema, view name.
2. **Tables block:** for each table entry, record:
   - Table alias (the name used inside the semantic view)
   - Base table: `database.schema.physical_table` (or `database.schema.view_name` for Scenario B)
   - Primary key column(s) (if present — marks this table as a join target)
   - Dimensions: name, aliases, data_type, expr
   - Time dimensions (if any): name, aliases, data_type (DATE / TIMESTAMP), expr
   - Per-table metrics: name, aliases, expr
3. **Relationships block:** for each relationship, record:
   - Relationship name
   - From table alias, from key column(s)
   - To table alias, to key column(s)
4. **Global metrics block** (metrics not nested under a table): name, aliases, expr
5. **Extension JSON** (Cortex Analyst context): record as-is for the report; do not map to ThoughtSpot.

Build an internal map:
- `tables`: list of parsed table entries
- `relationships`: list of parsed relationship entries
- `columns` (flat): all dimensions, time_dimensions, and metrics across all tables and global

---

### Step 5: Choose scenario

Present the user with a clear choice:

```
The semantic view references these base tables:
  DUNDERMIFFLIN.PUBLIC.DM_ORDERS
  DUNDERMIFFLIN.PUBLIC.DM_CUSTOMER
  DUNDERMIFFLIN.PUBLIC.DM_PRODUCTS
  ...

How should the ThoughtSpot Model be built?

  A) On the underlying physical tables (recommended if these tables are already
     registered in ThoughtSpot). Reuses existing ThoughtSpot Table objects and
     their pre-defined joins.

  B) On these tables as-is (creates new ThoughtSpot Table objects pointing
     to the base table references above, adds them to the ThoughtSpot connection).

Select A or B:
```

---

### Step 6A: Find existing ThoughtSpot Table objects (Scenario A)

For each base table reference parsed in Step 4, find the matching ThoughtSpot Table
object (subtype `ONE_TO_ONE_LOGICAL`).

**Search by database + schema + table name:**

```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile {profile}
```

This returns all table objects. Filter the JSON to find entries where:
- `metadata_header.database_stripes` matches the database name
- `metadata_header.schema_stripes` matches the schema name
- `metadata_name` matches the physical table name

Alternatively, if a table name is distinctive, search directly:

```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --name "%{table_name}%" --profile {profile}
```

Build a map: `physical_table_name → {metadata_id, metadata_name}`.

**If a table is not found:**
- Warn the user: "Table `{db}.{schema}.{tbl}` has no matching ThoughtSpot object."
- Options: (1) skip the table from the model, (2) switch to Scenario B for that table,
  (3) abort and run the ThoughtSpot model-builder skill first to register the tables.
- Do not proceed to import until all required tables are resolved.

---

### Step 6B: Create ThoughtSpot Table objects for views (Scenario B)

For each base table reference (which may be a Snowflake view):

1. Introspect columns from Snowflake:
   ```sql
   SHOW COLUMNS IN TABLE {database}.{schema}.{table_or_view};
   ```
   For each column record: name, data type.

2. Find the ThoughtSpot connection to use:
   ```bash
   ts connections list --profile {profile}
   ```
   Ask the user to confirm which connection to use (or auto-select if only one matches
   the semantic view's database).

3. Register the views/tables in the connection:
   ```bash
   echo '[{
     "db": "{database}",
     "schema": "{schema}",
     "table": "{view_name}",
     "type": "VIEW",
     "columns": [{"name": "COL1", "type": "VARCHAR"}, ...]
   }, ...]' | ts connections add-tables {connection_id} --profile {profile}
   ```
   Map Snowflake types to ThoughtSpot types using the table in
   [references/reverse-mapping-rules.md](references/reverse-mapping-rules.md).

4. Create ThoughtSpot Table TML objects for each view/table and import them:
   - Use `ts tml import --policy PARTIAL` for tables (allows partial success).
   - Collect the assigned GUIDs for use in the model TML.

5. Inline joins will be defined directly in the model TML (no `referencing_join`).

---

### Step 7: Find join names (Scenario A only)

For each relationship in the semantic view, find the name of the pre-defined join
in the ThoughtSpot Table objects.

For a relationship `FROM {from_table} KEY {from_col} TO {to_table} KEY {to_col}`:

1. Identify the `from_table`'s ThoughtSpot GUID (from Step 6A).
2. Export its TML:
   ```bash
   ts tml export {from_table_guid} --profile {profile}
   ```
3. Parse the returned `edoc` (YAML string). Find the `joins` section.
4. Match the join where `destination` equals the `to_table` name.
5. Record the join `name` — this is the `referencing_join` value for the `to_table`
   entry in the model TML.

If no matching join is found, the tables may not have a pre-defined join. Options:
- Use an inline join instead (switch this relationship to Scenario B behaviour).
- Abort and define the join at the ThoughtSpot Table level first.

**Export multiple table TMLs in one call to reduce API calls:**
```bash
ts tml export {guid1} {guid2} {guid3} --profile {profile}
```

---

### Step 8: Build the model TML

Construct the model TML as a YAML string. Use the templates in
[references/reverse-mapping-rules.md](references/reverse-mapping-rules.md).

**Model name:** `TEST_SV_{view_name_title_case}` — prefix indicates this is a
test/converted model. Ask the user if they want a different name.

**Identify the fact table** (the table that is never on the "TO" side of any relationship)
— it gets no `referencing_join`.

**Model TML skeleton (Scenario A):**

```yaml
model:
  name: "TEST_SV_{view_name}"
  model_tables:
  - id: {FACT_TABLE_ALIAS}
    name: {PHYSICAL_TABLE_NAME}
    fqn: {fact_table_guid}           # GUID from Step 6A
  - id: {DIM_TABLE_ALIAS}
    name: {PHYSICAL_TABLE_NAME}
    fqn: {dim_table_guid}            # GUID from Step 6A
    referencing_join: {join_name}    # from Step 7
  # ... one entry per table ...
  columns:
  - name: "{display_name}"
    column_id: {TABLE_ALIAS}::{PHYSICAL_COLUMN}
    properties:
      column_type: ATTRIBUTE
  # ... one entry per dimension/time_dimension ...
  # ... MEASURE columns for simple metrics ...
  formulas:
  - name: "{display_name}"
    expr: "{thoughtspot_formula}"
    properties:
      column_type: MEASURE
  # ... formula entries for complex metrics ...
```

**Column entries:**

For each dimension in the semantic view:
- `name`: first ALIAS if present, otherwise the snake_case dimension name
- `column_id`: `{TABLE_ALIAS}::{expr_column}` — extract the column name from the
  EXPR (e.g. `DM_CUSTOMER.CUSTOMER_NAME` → `DM_CUSTOMER::CUSTOMER_NAME`)
- `column_type: ATTRIBUTE`

For each time_dimension (DATE / TIMESTAMP):
- Same as dimension above.

For each simple metric (`AGG(table.col)`):
- `name`: first ALIAS if present, otherwise the metric name
- `column_id`: `{TABLE_ALIAS}::{col}`
- `column_type: MEASURE`
- `aggregation`: mapped from the SQL aggregate function (see reverse-mapping-rules.md)

For each complex metric (formula expression):
- See Step 9 for translation. Results go into `formulas[]`.

---

### Step 9: Translate SQL expressions → ThoughtSpot formulas

For each metric whose `EXPR` is not a simple `AGG(table.col)`:

1. Apply the SQL → ThoughtSpot formula translation rules in
   [references/reverse-mapping-rules.md](references/reverse-mapping-rules.md).
2. Replace column references: `table.COLUMN` → `[TABLE_ALIAS::COLUMN]`
3. If the expression translates successfully → add a `formulas[]` entry.
4. If the expression cannot be translated → omit the column and log it in the
   Formula Translation Log (for the summary report in Step 12).

**Column references in translated formulas:**

Use the TABLE_ALIAS from `model_tables` (the `id` field, which matches the semantic
view table alias). Column name is the physical column from the EXPR.

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

On success, parse the response JSON to extract the created model's GUID.

**Common import errors:**

| Error | Likely cause | Fix |
|---|---|---|
| `referencing_join not found` | Join name is wrong or join doesn't exist at table level | Export table TML again and verify join name |
| `column_id not found` | Physical column name is wrong or table GUID is wrong | Check Table TML for the correct column name |
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
