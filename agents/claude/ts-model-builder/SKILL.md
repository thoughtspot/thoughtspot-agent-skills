---
name: ts-model-builder
description: Build a ThoughtSpot Model from a Snowflake schema or ERD image. Browses Snowflake databases and tables (or reads a diagram), ensures tables exist in a ThoughtSpot connection, creates logical Table objects, and generates a Model with inferred or user-defined joins.
---

# ThoughtSpot Model Builder

Build a ThoughtSpot Model (not a Worksheet — Worksheets are legacy and will not be created)
from a Snowflake schema or an ERD image. The skill:

1. Browses Snowflake to select tables/views/semantic views — or reads a diagram image
2. Checks whether those tables exist in a ThoughtSpot connection; adds any that are missing
3. Creates logical Table objects in ThoughtSpot via TML import
4. Infers or accepts user-defined joins (table-level or model-level)
5. Generates and imports the final Model TML

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/open-items.md](references/open-items.md) | Unknowns that must be tested before this skill is complete — check before implementing each step |
| [~/.claude/skills/ts-profile-setup/SKILL.md](~/.claude/skills/ts-profile-setup/SKILL.md) | ThoughtSpot auth, profile config, token persistence (Pattern A), API call patterns |
| [~/.claude/skills/snowflake-profile-setup/SKILL.md](~/.claude/skills/snowflake-profile-setup/SKILL.md) | Snowflake connection patterns, SQL execution, SHOW commands |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-setup` if not
- Snowflake profile configured — run `/snowflake-profile-setup` if not (required for Snowflake source; not needed for image source)
- Python packages: `requests`, `pyyaml`, `snowflake-connector-python`
- ThoughtSpot user must have `DATAMANAGEMENT` or `DEVELOPER` privilege and `CAN_CREATE_OR_EDIT_CONNECTIONS` if adding tables to a connection

---

## Entry Point

### 1. Load profiles

Read both profile files:
- `~/.claude/thoughtspot-profiles.json`
- `~/.claude/snowflake-profiles.json`

If either file is missing or empty where required, prompt the user to run the relevant setup skill first.

If multiple ThoughtSpot profiles exist, ask:
```
Which ThoughtSpot profile would you like to use?

  1. {name}  —  {base_url}
  2. {name}  —  {base_url}

Enter number:
```

If multiple Snowflake profiles exist (and Snowflake source is chosen), ask the same for Snowflake.

Authenticate ThoughtSpot using Pattern A from `ts-profile-setup/SKILL.md`. Token written to `/tmp/ts_token.txt`.

### 2. Choose source

```
How would you like to define the model tables?

  1  Browse Snowflake  (select database → schema → tables or semantic view)
  2  Load from image   (ERD diagram, hand-drawn sketch, or database screenshot)

Enter 1 or 2:
```

---

## Step 1A — Browse Snowflake Schema

Run each query using the selected Snowflake profile. Show results as a numbered list.

```sql
-- Navigate down the hierarchy one level at a time
SHOW DATABASES;
SHOW SCHEMAS IN DATABASE {db};
SHOW TABLES IN SCHEMA {db}.{schema};
SHOW VIEWS IN SCHEMA {db}.{schema};
```

Present tables and views together, labelled `[TABLE]` or `[VIEW]`. Allow multi-select.

```
Tables and views in {db}.{schema}:

  1  [TABLE]  FACT_ORDERS
  2  [TABLE]  FACT_RETURNS
  3  [VIEW]   V_CUSTOMER_SUMMARY
  4  ...

  S  Also show Snowflake Semantic Views

Enter numbers to include (comma-separated), or S:
```

If the user chooses **S**, run:

```sql
-- [TEST REQUIRED — see open-items.md #2]
-- Try in order until one succeeds:
SHOW SEMANTIC VIEWS IN SCHEMA {db}.{schema};
-- fallback:
SELECT semantic_view_name FROM {db}.INFORMATION_SCHEMA.SEMANTIC_VIEWS;
```

For each selected regular table or view, fetch column metadata:

```sql
DESCRIBE TABLE {db}.{schema}.{table};
-- Returns: name, type, null?, default, primary key, unique key, check, expression, comment
```

For each selected semantic view, fetch its full definition:

```sql
-- [TEST REQUIRED — see open-items.md #2]
SELECT SYSTEM$GET_SEMANTIC_VIEW('{db}.{schema}.{view_name}');
```

Parse the semantic view YAML — dimensions, time_dimensions, and metrics are already classified.
Use that classification directly rather than re-inferring from column names.

After collecting all table/column metadata, proceed to [Step 2](#step-2--check-thoughtspot-connection).

---

## Step 1B — Load from Image

```
Path to your diagram image (PNG, JPG, PDF screenshot, etc.):
```

Read the image using the Read tool. Extract:

| What to look for | Maps to |
|---|---|
| Box header / entity name | Table name |
| Rows inside box | Column names |
| Type annotations (`INT`, `VARCHAR`, `DATE`, etc.) | Data type |
| `PK` marker or bold/underline | Primary key column |
| `FK` marker | Foreign key / join column |
| Lines between entities | Join relationship |
| Crow's foot / `1:N` / `N:1` notation | Join cardinality |
| `[M]` or circled column / shading | Measure hint |

Present the extracted structure for confirmation before proceeding:

```
Extracted from image:

  Tables:
    FACT_ORDERS       — 8 columns (ORDER_ID PK, CUSTOMER_ID FK, ORDER_DATE DATE, ...)
    DIM_CUSTOMER      — 5 columns (CUSTOMER_ID PK, CUSTOMER_NAME, REGION, ...)

  Inferred joins:
    FACT_ORDERS → DIM_CUSTOMER  on  CUSTOMER_ID  (LEFT OUTER, many-to-one)

  Does this look right? Any corrections before we continue?
  (Enter Y to continue, or describe what to fix):
```

After confirmation, proceed to [Step 2](#step-2--check-thoughtspot-connection).

**Note:** For image source, Step 2 connection check compares against what was extracted
from the image. The Snowflake profile is not used.

---

## Step 2 — Check ThoughtSpot Connection

### Find the right connection

List available ThoughtSpot connections and ask the user to select the Snowflake connection
that should own these tables:

```python
# Write to /tmp/ts_connections.py, run, remove
import requests, json

with open("/tmp/ts_token.txt") as f:
    token = f.read().strip()

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

resp = requests.post(
    "{base_url}/api/rest/2.0/connection/search",
    json={"data_warehouse_types": ["SNOWFLAKE"]},
    headers=headers,
)
resp.raise_for_status()
print(json.dumps(resp.json(), indent=2))
```

Show only Snowflake connections. If exactly one exists, confirm and use it automatically.

Save the selected connection's `id` (GUID) as `{ts_connection_id}` and `name` as `{ts_connection_name}`.

### Fetch current connection state

```python
# [TEST REQUIRED — see open-items.md #1: does this v1 endpoint work with a Bearer token?]
resp = requests.post(
    "{base_url}/tspublic/v1/connection/fetchConnection",
    json={"connection_id": "{ts_connection_id}", "includeColumns": True},
    headers=headers,
)
```

Parse the response into a lookup: `{db}.{schema}.{table}` → set of column names already linked.

### Compare

For each user-selected table, determine its status:

| Condition | Status | Action needed |
|---|---|---|
| Table present, all columns present | `OK` | None |
| Table present, some columns missing | `UPDATE` | Add missing columns |
| Table not present | `ADD` | Add table + all columns |

If all tables are `OK`, print:
```
All tables already exist in the ThoughtSpot connection — no connection changes needed.
```
Skip to [Step 4](#step-4--create--verify-table-tml-objects).

Otherwise show a summary and proceed to Step 3:
```
Connection changes required:

  ADD     FACT_ORDERS      (8 columns)
  ADD     DIM_CUSTOMER     (5 columns)
  UPDATE  FACT_PRODUCTS    (add 2 columns: CATEGORY, BRAND)

Proceed? Y / N:
```

---

## Step 3 — Add / Update Tables in Connection

**[TEST REQUIRED — see open-items.md #1 and #3 before implementing this step]**

Construct the update payload by merging the existing connection state (from Step 2's
`fetchConnection` response) with the new/updated tables. Never send only the new tables —
the full set must be included or existing tables will be delinked.

```python
# Write to /tmp/ts_connection_update.py, run, remove
import requests, json, os

with open("/tmp/ts_token.txt") as f:
    token = f.read().strip()

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Merge existing tables with new/updated tables
# existing_state = full response from fetchConnection (Step 2)
# new_tables = tables to add/update

merged_databases = _merge(existing_state, new_tables)  # see merge logic below

payload = {
    "connection_id": "{ts_connection_id}",
    "metadata": {
        # [TEST REQUIRED #1] — try without 'configuration' first
        # If the API rejects it, add configuration block using Snowflake credentials
        "externalDatabases": merged_databases,
    },
}

resp = requests.post(
    "{base_url}/tspublic/v1/connection/update",
    json=payload,
    headers=headers,
)
print(resp.status_code, resp.text[:500])
```

### Merge logic

```python
def _merge(existing_state, new_tables):
    """
    existing_state: fetchConnection response (full database/schema/table hierarchy)
    new_tables: list of {db, schema, table, type, columns: [{name, type}]}

    Returns the merged externalDatabases list where:
    - Existing tables are preserved unchanged (selected=True, linked=True for all their columns)
    - New tables are added with selected=True, linked=True
    - Updated tables have new columns appended with selected=True, isLinkedActive=True
    """
    # Build index of existing tables
    # For each new table: find it in existing or create it
    # For updated tables: find missing columns and append them
    # Return the full merged structure
    pass  # implement after open-item #1 and #3 are resolved
```

After the update call succeeds, check whether ThoughtSpot automatically created Table
metadata objects — see open-item #3. If yes, skip to Step 5. If no, proceed to Step 4.

---

## Step 4 — Create / Verify Table TML Objects

For each selected table, check whether a ThoughtSpot Table metadata object already exists:

```python
resp = requests.post(
    "{base_url}/api/rest/2.0/metadata/search",
    json={
        "metadata": [{"type": "LOGICAL_TABLE"}],
        "record_size": 50,
    },
    headers=headers,
)
# Filter results by name matching the table name
# A match is only valid if the object's connection matches {ts_connection_id}
```

For each table that does not have an existing object, generate its Table TML:

```yaml
table:
  name: {TABLE_DISPLAY_NAME}       # e.g. "FACT_ORDERS" or a cleaned display name
  db: {SNOWFLAKE_DATABASE}
  schema: {SNOWFLAKE_SCHEMA}
  db_table: {SNOWFLAKE_TABLE_NAME}
  connection:
    name: {ts_connection_name}
    fqn: {ts_connection_id}
  columns:
  - name: {DISPLAY_NAME}
    db_column_name: {PHYSICAL_COLUMN_NAME}
    properties:
      column_type: {ATTRIBUTE|MEASURE}
      aggregation: {SUM|COUNT|...}        # MEASURE columns only
    db_column_properties:
      data_type: {INT64|VARCHAR|DOUBLE|DATE|DATE_TIME|BOOL}
  joins_with: []                          # populated in Step 5 if table-level joins chosen
```

### Column classification

| Snowflake type | ThoughtSpot `data_type` | `column_type` default |
|---|---|---|
| `NUMBER`, `INT`, `INTEGER`, `BIGINT`, `FLOAT`, `DOUBLE`, `DECIMAL`, `REAL` | `DOUBLE` or `INT64` | `MEASURE` (aggregation: `SUM`) |
| `VARCHAR`, `TEXT`, `STRING`, `CHAR`, `NVARCHAR` | `VARCHAR` | `ATTRIBUTE` |
| `BOOLEAN` | `BOOL` | `ATTRIBUTE` |
| `DATE` | `DATE` | `ATTRIBUTE` |
| `TIMESTAMP*`, `DATETIME` | `DATE_TIME` | `ATTRIBUTE` |

**ID/key heuristic:** If a numeric column name ends with `_id`, `_key`, or `_code`, override
`column_type` to `ATTRIBUTE` (it is a foreign key, not a measure).

Import all Table TMLs in a single call:

```python
resp = requests.post(
    "{base_url}/api/rest/2.0/metadata/tml/import",
    json={
        "metadata_tmls": [yaml1_str, yaml2_str, ...],
        "import_policy": "PARTIAL",
        "create_new": True,
    },
    headers=headers,
)
```

Parse the import response — each object has its own status. Report any failures before
continuing. Do not proceed to Step 5 if any table failed to import.

**[TEST REQUIRED — see open-items.md #4]:** If a Table object already exists with the same
name and connection, determine whether re-importing updates it or creates a duplicate.

---

## Step 5 — Joins and Model Creation

### 5A — Join strategy

```
Where would you like to define joins?

  1  Table level  — joins stored on Table objects, reusable across any model
  2  Model level  — joins scoped to this model only
  3  No joins     — create model without joins (add them later)

Enter 1, 2, or 3:
```

### 5B — Infer join candidates

Scan all selected tables for column name matches across table pairs.
Score each candidate:

| Signal | Confidence |
|---|---|
| Exact name match (`customer_id` = `customer_id`) | High |
| One is PK (from image or Snowflake metadata) | High |
| Name match with `_id` / `_key` suffix | Medium |
| Similar names (`cust_id` / `customer_id`) | Low — flag for user review |

Present candidates:

```
Inferred joins:

  1  FACT_ORDERS.CUSTOMER_ID → DIM_CUSTOMER.CUSTOMER_ID   [HIGH confidence]
  2  FACT_ORDERS.PRODUCT_ID  → DIM_PRODUCT.PRODUCT_ID     [HIGH confidence]
  3  FACT_ORDERS.STORE_CODE  → DIM_STORE.STORE_CD         [LOW — review recommended]

  A  Add a join manually
  R  Remove a join
  C  Change join type (default: LEFT OUTER)

Confirm joins (Y to accept, or edit):
```

Default join type: `LEFT_OUTER`. Ask if the user wants to change any.

For each confirmed join, determine left (fact) vs right (dimension) table:
- The table with the FK column is left
- The table with the PK column is right (gets `primary_key` in its Table TML if table-level joins)

### 5C — Apply table-level joins (if chosen)

If strategy is table-level (option 1), update each source Table TML to add `joins_with`:

```yaml
joins_with:
- name: {left_table}_to_{right_table}
  destination: {right_table_name}
  type: LEFT_OUTER
  on: "[{left_table}::{left_col}] = [{right_table}::{right_col}]"
  is_one_to_one: false
```

Re-import the updated Table TMLs.

**[TEST REQUIRED — see open-items.md #5]:** Confirm whether table-level joins mean the
`model` TML can omit the `joins` section entirely, or whether `table_paths` must still
reference them.

### 5D — Generate Model TML

```yaml
model:
  name: {MODEL_NAME}
  description: ""
  model_tables:
  - name: {TABLE_1_NAME}
    id: {TABLE_1_NAME}_1
  - name: {TABLE_2_NAME}
    id: {TABLE_2_NAME}_1
  # ... one entry per table

  joins:                              # OMIT if using table-level joins (see open-item #5)
  - name: {left}_to_{right}
    source: {LEFT_TABLE}_1
    destination: {RIGHT_TABLE}_1
    type: LEFT_OUTER
    on: "[{LEFT_TABLE}_1::{left_col}] = [{RIGHT_TABLE}_1::{right_col}]"
    is_one_to_one: false

  table_paths:
  - id: {FACT_TABLE}_1
    table: {FACT_TABLE}
    join_path:
    - {}                              # fact table has empty join_path
  - id: {DIM_TABLE}_1
    table: {DIM_TABLE}
    join_path:
    - join:
      - {fact}_to_{dim}              # join name from joins section above

  columns:
  - name: {DISPLAY_NAME}
    column_id: {TABLE_PATH_ID}::{PHYSICAL_COLUMN_NAME}
    properties:
      column_type: {ATTRIBUTE|MEASURE}
      aggregation: {SUM|COUNT|...}   # MEASURE only
```

### 5E — Review checkpoint

Before importing, show the user a summary:

```
Model to be created: "{MODEL_NAME}"

  Tables:    3  (FACT_ORDERS, DIM_CUSTOMER, DIM_PRODUCT)
  Joins:     2  (table-level)
  Columns:   24  (18 attributes, 4 measures, 2 time dimensions)

  Columns flagged for review:
    FACT_ORDERS.DISCOUNT_RATE  — numeric but name suggests ratio, not a sum measure
    FACT_ORDERS.STATUS_CODE    — numeric, classified as ATTRIBUTE (ID heuristic)

Proceed with import? Y / N:
```

### 5F — Import model

```python
resp = requests.post(
    "{base_url}/api/rest/2.0/metadata/tml/import",
    json={
        "metadata_tmls": [model_yaml_str],
        "import_policy": "ALL_OR_NONE",
        "create_new": True,
    },
    headers=headers,
)
```

Use `ALL_OR_NONE` for the model (either the whole model works or it doesn't).

Parse the response for the created model's GUID. Report success with a link:

```
Model created successfully.

  Name:  {MODEL_NAME}
  GUID:  {guid}
  URL:   {base_url}/#/data/tables/{guid}

To search against this model in ThoughtSpot, open the URL above and verify the column
classifications look correct.
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `fetchConnection` returns 401/403 | Token expired or insufficient privilege — re-auth or check `CAN_CREATE_OR_EDIT_CONNECTIONS` |
| `connection/update` requires credentials | Read Snowflake password/key from Keychain for the selected Snowflake profile and include in `configuration` block |
| TML import partial failure | Show per-object errors. Fix the failing TML and retry just those objects |
| Model import: "table not found" | Table TML import in Step 4 may have failed silently — re-check Step 4 response |
| Duplicate table object created | See open-item #4 — may need to delete the duplicate and update instead |
| `requests` or `yaml` not found | `pip install requests pyyaml` |

---

## Cleanup

```bash
rm -f /tmp/ts_token.txt /tmp/ts_connections.py /tmp/ts_connection_update.py
```
