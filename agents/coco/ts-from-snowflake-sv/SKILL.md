---
name: ts-from-snowflake-sv
description: Convert a Snowflake Semantic View into a ThoughtSpot Model by reading the view DDL, mapping tables and joins, translating SQL expressions to ThoughtSpot formulas, and importing the model via the ThoughtSpot REST API.
---

# Snowflake Semantic View → ThoughtSpot Model

Reverse-engineers a Snowflake Semantic View into a ThoughtSpot Model. Reads the
semantic view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics
back to ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and
imports the result via the ThoughtSpot REST API.

Two scenarios are supported:
- **Scenario A (existing tables):** ThoughtSpot Table objects already exist for the
  Snowflake objects the semantic view references. Reuses those existing Table objects.
- **Scenario B (new tables):** No ThoughtSpot Table objects exist yet for the Snowflake
  objects the semantic view references. Creates new Table objects pointing to those objects.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md) | Semantic View DDL parsing, model TML templates, type and aggregation mapping |
| [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | SQL → ThoughtSpot formula translation rules (bidirectional reference) |
| [../../shared/worked-examples/snowflake/ts-from-snowflake.md](../../shared/worked-examples/snowflake/ts-from-snowflake.md) | End-to-end example: BIRD_SUPERHEROS_SV → ThoughtSpot Model (se-thoughtspot, inline joins, verified against live DDL) |

---

## Concept Mapping

| Snowflake Semantic View | ThoughtSpot Model |
|---|---|
| `TABLES ( ... BASE TABLE db.schema.tbl )` | `model_tables[]` — one entry per table |
| `PRIMARY KEY ( col )` | Identifies join target tables — not directly in model TML |
| `DIMENSIONS ( col DATA_TYPE = TEXT )` | `columns[]` with `column_type: ATTRIBUTE` |
| `DIMENSIONS ( col DATA_TYPE = DATE )` | `columns[]` with `column_type: ATTRIBUTE` (date) |
| `METRICS ( name EXPR = AGG(tbl.col) )` | `columns[]` with `column_type: MEASURE` + aggregation |
| `METRICS ( name EXPR = complex_sql )` | `formulas[]` with translated ThoughtSpot formula |
| `RELATIONSHIPS ( ... FROM tbl KEY col TO tbl KEY col )` | `referencing_join` (Scenario A) or inline joins (Scenario B) |
| `ALIASES = ( alias1, alias2 )` | First alias → display name; additional aliases → synonyms |

---

## SQL Call Batching (Minimise UI Confirmations)

**CRITICAL for Snowsight Workspaces:** Every `snowflake_sql_execute` call triggers a
UI confirmation prompt. Minimise calls by batching related statements.

**Target call budget:** Aim for **4–5 total SQL calls** per model:

| Call | Purpose |
|---|---|
| 1 | Get DDL + check profile |
| 2 | Search ThoughtSpot for **all** base tables in one batched call |
| 3 | Export Table TMLs to find join names (one batched call) |
| 4 | (Scenario B only) Introspect Snowflake columns for missing tables |
| 5 | Import model TML |

---

## Prerequisites

- A Snowflake role with `USAGE` on the database/schema containing the semantic view
- ThoughtSpot setup completed via `/ts-profile-setup` — `SKILLS.PUBLIC.THOUGHTSPOT_PROFILES` table must exist with at least one profile
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege in ThoughtSpot

---

## Workflow

### Step 1: Select profile and get DDL

**Check procedures and select the ThoughtSpot profile in one call:**

```sql
SELECT PROCEDURE_NAME FROM SKILLS.INFORMATION_SCHEMA.PROCEDURES
WHERE PROCEDURE_SCHEMA = 'PUBLIC'
  AND PROCEDURE_NAME IN ('TS_SEARCH_MODELS', 'TS_EXPORT_TML', 'TS_IMPORT_TML');

SELECT NAME, BASE_URL, USERNAME, AUTH_TYPE, SECRET_NAME, TOKEN_EXPIRES_AT
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
ORDER BY NAME;
```

**Procedure check:** if any of the three procedures are missing from the first result,
stop and tell the user:
> "Required stored procedures are not installed. Run `/ts-sv-setup` to install them,
> then retry."

**Profile selection:** using the rows from the second result:
- If multiple rows: display a numbered list (`#. name — auth_type — base_url`) and ask
  the user to select one. Store the selected `NAME` as `{profile_name}`.
- If exactly one row: display it and confirm before proceeding. Store as `{profile_name}`.

**Validate the selected profile — branch by auth_type:**

*Token auth:* check the `TOKEN_EXPIRES_AT` value already returned above (no second query):
- `TOKEN_EXPIRES_AT > CURRENT_TIMESTAMP()` → proceed
- Otherwise → stop:
  > "The token for profile '{profile_name}' has expired. Run `/ts-profile-setup` →
  > U → Refresh token, then retry."

*Password auth:* no expiry check needed — proceed directly to credential retrieval.

**Batch: retrieve credential + get DDL:**

If the user has not named the semantic view, first list available views:

```sql
SHOW SEMANTIC VIEWS IN SCHEMA {database}.{schema};
```

Display results as a numbered list and ask the user to select one.

Then fetch credential and store the full DDL. The DDL can be very long and is
truncated when read inline — always store it via `CREATE TABLE AS SELECT`:

```sql
-- Batch call: credential + DDL stored in temp table (two statements, one confirmation)
SELECT SYSTEM$GET_SECRET_STRING('SKILLS.PUBLIC.' || SECRET_NAME) AS secret_value
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE name = '{profile_name}';

CREATE OR REPLACE TEMPORARY TABLE SKILLS.TEMP.SV_DDL AS
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{view_name}') AS ddl_text;
```

Read the full DDL from the temp table in the next step:
```sql
SELECT ddl_text FROM SKILLS.TEMP.SV_DDL;
```

**Do not** use `SELECT GET_DDL(...)` directly — the result will be truncated.
Do not use `SUBSTR` chunking — that requires multiple extra SQL calls.
`GET_DDL` is a function (not a stored procedure), so `CREATE TABLE AS SELECT` works
and stores the complete result in one call.

Store `secret_value` for use in subsequent API calls via stored procedures. Never print it.

---

### Step 2: Parse the DDL

Parse the DDL string returned in Step 1. The DDL is a SQL `CREATE OR REPLACE
SEMANTIC VIEW` statement. See [../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md)
for the full format.

> **Important:** The real DDL format has **flat** `dimensions` and `metrics` blocks at the
> view level — NOT nested per-table. Relationships use `REL_NAME as FROM(COL) references TO(COL)` syntax.

Extract:
1. **Tables block:** for each entry, record:
   - Fully-qualified table reference (`DB.SCHEMA.TABLE`)
   - Table alias (explicit `ALIAS as DB.SCHEMA.TABLE`, or last segment of the name)
   - Primary key column(s) — marks this as a join target
2. **Relationships block:** for each entry, record:
   - Relationship name, from table alias, from column, to table alias, to column
3. **Dimensions block** (flat, all tables): for each entry (`TABLE.COL as view_alias.NAME [comment='...']`), record:
   - Source: table alias + column name
   - Display name: value of `comment='...'`, or title-cased NAME if no comment
4. **Metrics block** (flat): for each entry, record:
   - Source: table alias + column name
   - Aggregation (from `AGG(...)`) or full expression
   - Display name: from `comment='...'` or title-cased NAME
5. **Extension JSON** (`with extension (CA='...')`): log but do not map to ThoughtSpot

Build an internal map:
- `tables`: list of `{alias, fqn, primary_key}`
- `relationships`: list of `{name, from_alias, from_col, to_alias, to_col}`
- `columns`: all dimensions and metrics keyed by `(table_alias, col_name)`

Identify the **fact table**: the table that never appears on the `TO` side of any relationship.

---

### Step 3: Table registration question

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

- **Y** → go to Step 4A (verify existing tables, skip the search)
- **N** → go to Step 4B (create new Table objects)
- **?** → go to Step 4A (search + verify)

---

### Step 4A: Discover and verify existing ThoughtSpot Table objects (Y and ? paths)

Skip this step if the user answered **N** in Step 3 — go directly to Step 4B.

**Search ThoughtSpot for matching table objects:**

Search for all base tables in a **single** call by passing their names as an array:

```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS(
    '{profile_name}',
    ARRAY_CONSTRUCT('{table_name_1}', '{table_name_2}', ...),
    FALSE
);
```

The procedure fetches all ThoughtSpot objects and filters client-side to names
containing any of the supplied keywords. Filter the returned results further to
match by database + schema + table name (case-insensitive).
Build map: `physical_table_name → {guid, metadata_name}`.

Always use `owner_only=FALSE`. Token-authenticated users may not appear as the
owner of objects they created, so `owner_only=TRUE` can return 0 results even for
objects that exist.

**Export TMLs for all found tables in one call to verify columns:**

The CALL result can be truncated when read inline. Always store via RESULT_SCAN.
These must be **two separate SQL calls** — RESULT_SCAN depends on LAST_QUERY_ID().

```sql
-- Call 1: export
CALL SKILLS.PUBLIC.TS_EXPORT_TML('{profile_name}', ARRAY_CONSTRUCT('{guid1}', '{guid2}'));
```

```sql
-- Call 2: store full result (column is always named after the procedure, uppercase)
CREATE OR REPLACE TEMPORARY TABLE SKILLS.TEMP.TML_RAW (tml_data VARIANT);
INSERT INTO SKILLS.TEMP.TML_RAW
SELECT PARSE_JSON("TS_EXPORT_TML") FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
```

**Do not** use the procedure in a FROM clause or as a UDF — it is a stored procedure,
not a function. FLATTEN and direct SELECT from the CALL result will not work.

Parse `table.columns[].name` from each returned TML. Build a column map per table:
`table_name → [col_name, ...]`. Column names in the ThoughtSpot TML are what you use in
`column_id` — always use the TML as the authoritative source.

**Confirm the plan before making any changes:**

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

Do not proceed until the user confirms. For any table **not found**, follow Step 4B.
For any table with **missing columns**, add them before building the model.

---

### Step 4B: Create ThoughtSpot Table objects (Scenario B)

**When tables don't exist in ThoughtSpot, create them first before the model.**

Ask which ThoughtSpot connection to register them under:

```
Which ThoughtSpot connection should these tables be added to?

Connection name:
```

Store as `{connection_name}`.

**Do NOT search for the connection using `TS_SEARCH_MODELS`** — that procedure only
finds `LOGICAL_TABLE` objects (worksheets, models, tables). Connections are a different
object type and are not returned. The connection is referenced by **name** directly in
the Table TML — no GUID or lookup is needed.

For each base table reference, introspect columns:

```sql
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
FROM {database}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{schema}'
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

Build a table TML for each table and import them all in one batch:

```yaml
table:
  name: TABLE_NAME
  db: DATABASE
  schema: SCHEMA
  db_table: TABLE_NAME
  connection:
    name: {connection_name}
  columns:
  - name: COL_NAME
    db_column_name: COL_NAME
    data_type: INT64        # or VARCHAR, DOUBLE, etc.
    properties:
      column_type: ATTRIBUTE
  joins:                     # Only on tables that have FK relationships
  - name: JOIN_NAME
    destination: TARGET_TABLE
    on: "[SOURCE::FK_COL] = [TARGET::PK_COL]"
    type: INNER
```

Validate all table TMLs first, then import:

```sql
-- Validate (dry run)
CALL SKILLS.PUBLIC.TS_IMPORT_TML('{profile_name}', ARRAY_CONSTRUCT($$...$$, $$...$$), TRUE);
```

**If validation fails with a connection-related error** (e.g. "connection not found",
"invalid connection name") — do NOT proceed to import. Call `TS_LIST_CONNECTIONS` to
fetch available connections and ask the user to correct the name:

```sql
CALL SKILLS.PUBLIC.TS_LIST_CONNECTIONS('{profile_name}');
```

Display results as a numbered list and ask the user to select:

```
Available ThoughtSpot connections:
  1. APJ_BIRD       (SNOWFLAKE)
  2. PROD_SF        (SNOWFLAKE)

Enter the connection name to use:
```

Update `{connection_name}` and **rebuild all table TMLs** with the corrected name
(the connection field appears in every table TML), then re-validate before importing.

**If validation passes**, proceed to the actual import.

**Critical distinction:**
- `validate_only=TRUE` — dry run only. No objects are created. Any GUIDs in the
  response are temporary and must NOT be used. Discard this response entirely.
- `validate_only=FALSE` — objects are created. GUIDs in this response are the real
  persistent IDs. This is the only response to extract GUIDs from.

```sql
-- Actual import (creates objects)
CALL SKILLS.PUBLIC.TS_IMPORT_TML('{profile_name}', ARRAY_CONSTRUCT($$...$$, $$...$$), FALSE);
```

```sql
-- Store full response (column is always named after the procedure, uppercase)
CREATE OR REPLACE TEMPORARY TABLE SKILLS.TEMP.TABLE_IMPORT_RESULT (result_data VARIANT);
INSERT INTO SKILLS.TEMP.TABLE_IMPORT_RESULT
SELECT PARSE_JSON("TS_IMPORT_TML") FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
```

Extract GUIDs directly from the import response — **do not** call `TS_SEARCH_MODELS`
to find them. The response contains `response.header.id_guid` and `response.header.name`
for each imported object:

```sql
SELECT
    value:response:header:name::STRING    AS table_name,
    value:response:header:id_guid::STRING AS guid,
    value:response:status:status_code::STRING AS status
FROM SKILLS.TEMP.TABLE_IMPORT_RESULT,
LATERAL FLATTEN(input => result_data);
```

Build a map `table_name → guid` from this result for use in Step 5 (join name resolution)
and Step 6 (model TML referencing_join lookup).

**Only available procedures are:** `TS_SEARCH_MODELS`, `TS_EXPORT_TML`, `TS_IMPORT_TML`,
`TS_LIST_CONNECTIONS`. Do not attempt to call any other procedure — none others exist.

**IMPORTANT:** Use `$$` dollar-quoting for each TML string to preserve YAML formatting.
Do NOT use `\n` escape sequences — they are passed literally and break YAML parsing.

Snowflake → ThoughtSpot type mapping:

| Snowflake | ThoughtSpot |
|---|---|
| NUMBER, INT, INTEGER, BIGINT, SMALLINT, TINYINT | INT64 |
| FLOAT, DOUBLE, REAL, DECIMAL, NUMERIC | DOUBLE |
| VARCHAR, TEXT, STRING, CHAR | VARCHAR |
| BOOLEAN | BOOL |
| DATE | DATE |
| TIMESTAMP, TIMESTAMP_NTZ, TIMESTAMP_LTZ, TIMESTAMP_TZ | DATE_TIME |

---

### Step 5: Find join names (Scenario A only)

For each relationship, find the pre-defined join name in the ThoughtSpot Table TML
of the `FROM` table. Export TMLs for all FROM tables in one call:

```
POST {base_url}/api/rest/2.0/metadata/tml/export
{
  "metadata": [
    {"type": "LOGICAL_TABLE", "identifier": "{from_table_guid_1}"},
    {"type": "LOGICAL_TABLE", "identifier": "{from_table_guid_2}"}
  ],
  "export_fqn": false
}
```

Parse each returned `edoc` YAML string. Find in the `joins` section the entry whose
`destination` matches the TO table name. Record the join `name`.

---

### Step 6: Build and translate the model TML

**IMPORTANT — TML format rules learned from production use:**

1. **Table TML `column_type`** must be nested under `properties:`:
   ```yaml
   columns:
   - name: COL_NAME
     db_column_name: COL_NAME
     data_type: INT64
     properties:
       column_type: ATTRIBUTE
   ```
   Bare `column_type: ATTRIBUTE` (without `properties:`) causes "No enum constant ColumnTypeEnum." error.

2. **Model TML joins** use `with:` (not `destination:`), require `cardinality:`, and
   `'on'` must be quoted in YAML:
   ```yaml
   joins:
   - name: join_name
     with: TARGET_TABLE
     'on': '[SOURCE::FK_COL] = [TARGET::PK_COL]'
     type: INNER
     cardinality: MANY_TO_ONE
   ```

3. **Join type is `INNER`** for all dimension lookups. ThoughtSpot models work correctly
   with INNER joins for standard fact-to-dimension relationships.

4. **Column `column_id`** format is `TABLE_NAME::COLUMN_NAME` (not `db_column_name`).

5. **Display names** should be title-cased (e.g. "Superhero Name" not "SUPERHERO_NAME").

6. **Model `properties`** should include:
   ```yaml
   properties:
     is_bypass_rls: false
     join_progressive: true
   ```

7. **Formula columns must NOT have `aggregation:`** — only `columns[]` entries support
   `aggregation`. Formulas are self-aggregating through their expression. Adding any
   `aggregation:` value to a `formulas[]` entry causes a TML import error. Correct format:
   ```yaml
   formulas:
   - name: "Num Orders"
     expr: "count_distinct ( [dm_order::ORDER_ID] )"
     id: num_orders
     properties:
       column_type: MEASURE
   ```
   No `aggregation:` field — not even `aggregation: FORMULA`.

8. **`table.name` in `model_tables[]` must exactly match the ThoughtSpot Table object
   name (case-sensitive).** ThoughtSpot Table names are stored as-is; if tables were
   imported with uppercase names (`DM_ORDER`, `DM_CUSTOMER`) then `model_tables` must
   reference them as `DM_ORDER`, `DM_CUSTOMER` — not `dm_order`, `dm_customer`. Use the
   exact names from the import response (Step 4B GUID extraction query) — never
   lowercase or transform them.

Apply all column, formula, and join mappings from
[../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md) to build
the model TML dict. Serialise to a YAML string.

For each metric in the semantic view:
- Simple `SUM/COUNT/AVG/MIN/MAX(table.col)` → `MEASURE` column in `columns[]`
- `COUNT(DISTINCT table.col)` → **always** a formula in `formulas[]`, never a MEASURE column:
  ```
  unique count ( [TABLE_ID::col_name] )
  ```
  ThoughtSpot rejects models where the same `column_id` appears more than once.
  A COUNT_DISTINCT MEASURE on a column that is also an ATTRIBUTE dimension will
  cause a **duplicate column_id** error — even though the `column_type` values differ.
  Using a formula avoids this entirely since formulas don't carry a `column_id`.
- Complex expression → translate SQL to ThoughtSpot formula, add to `formulas[]`
- Untranslatable → omit and log in report

**Model name:** `TEST_SV_{semantic_view_name}` (or user-specified).

---

### Step 7: Review checkpoint

Show the user a summary of the model before importing:

```
Model to import: TEST_SV_{view_name}

Tables ({n}):
  ✓ {FACT_TABLE}    — fact table
  ✓ {DIM_TABLE}     — referencing_join: {join_name}
  ...

Columns: {n} ATTRIBUTE, {n} MEASURE, {n} formulas

Formula translations:
  ✓ {name}: {sql} → {ts_formula}
  ⚠ {name}: OMITTED — {reason}

Proceed? (yes/no):
```

---

### Step 8: Import the model TML

**IMPORTANT — Updating vs creating:** Without a `guid` field in the TML, ThoughtSpot
always creates a **new** object, even if a model with the same name already exists.
To update an existing model, add `guid: {existing_model_guid}` directly under `name`:

```yaml
model:
  name: "TEST_SV_{view_name}"
  guid: "{existing_model_guid}"   # omit on first import; required for all subsequent fixes
  model_tables:
  ...
```

On the first import (new model), omit `guid` — it doesn't exist yet. After import,
record the GUID from the response for all future updates.

Import via the stored procedure:

```sql
CALL SKILLS.PUBLIC.TS_IMPORT_TML('{profile_name}', ARRAY_CONSTRUCT($$
{model_tml_yaml}
$$), TRUE);
```

**IMPORTANT:** Use `$$` dollar-quoting to preserve YAML formatting.

On success, extract and display the created model GUID. **Save it** — you will need it
if you reimport to fix any errors.

**Common errors:**

| Error | Likely cause | Fix |
|---|---|---|
| `duplicate column_id` | Same physical column used as both ATTRIBUTE and COUNT_DISTINCT MEASURE | Convert the COUNT_DISTINCT metric to a formula: `unique count ( [TABLE::col] )` |
| `referencing_join not found` | Join name wrong or join doesn't exist at table level | Re-export table TML and verify join name |
| `column_id not found` | Semantic view left-side alias used instead of ThoughtSpot Table TML column name | Check ThoughtSpot Table TML for correct `db_column_name` |
| `Compulsory Field … joins(N)->with is not populated` | Missing `with` field on inline join | Add `with: {target_id}` to every inline join entry |
| `{table_name} does not exist in schema` (on `with`) | `with` value doesn't match any `id` | Ensure `with` matches target `id` exactly (lowercase) |
| `Invalid srcTable or destTable in join expression` | `on` clause uses table names instead of `id` values | Check both `[table::col]` refs use `id` values |
| `Multiple tables have same alias {name}` | Two `model_tables` entries share the same `name` | Deduplicate — same Snowflake object must appear only once |
| `aggregation type FORMULA is not valid` | `aggregation:` field set on a `formulas[]` entry | Remove `aggregation:` from all formula entries — formulas must not have this field |
| `table not found` or model references unresolved table | `table.name` in `model_tables[]` doesn't match ThoughtSpot Table name exactly | Use exact names from Step 4B import response — often uppercase; never lowercase or transform |
| `formula syntax error` | ThoughtSpot formula has invalid syntax | Review translated formula against ts-snowflake-formula-translation.md |
| `fqn resolution failed` | Stale GUID | Re-run Step 4 to get fresh GUIDs |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars before serialising |

---

### Step 9: Summary report

```
## Model Import Complete

**Model:** TEST_SV_{view_name}
**GUID:** {guid}
**ThoughtSpot URL:** {base_url}/#/model/{guid}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {table_id}::{COL} |
| {name} | MEASURE ({agg}) | {table_id}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |

### Formula Translation Log
| Column | Original SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{sql}` | ✓ Translated | `{ts_formula}` |
| {name} | `{sql}` | ⚠ Omitted | {reason} |

### Not Mapped
- Extension JSON (Cortex Analyst context): not translated to ThoughtSpot
```

---

## Multiple semantic view conversion

After completing one conversion, offer to convert additional views.

- **Session continuity:** If the ThoughtSpot profile was already selected and validated
  earlier in this conversation, skip the profile selection and validation. For token
  auth, reuse the stored `secret_value` (tokens are valid for the session). For
  password auth, re-retrieve the credential only if the stored value is no longer
  available.
- Do not re-authenticate between views.
- Return to Step 1 (DDL fetch only) for the next view, skipping the profile SQL call.
