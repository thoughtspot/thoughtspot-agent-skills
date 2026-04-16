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
- **Scenario A (underlying tables):** Build the model on top of the physical tables
  already registered in a ThoughtSpot connection. Reuses existing ThoughtSpot Table
  objects and their pre-defined joins.
- **Scenario B (views):** Build the model on top of the Snowflake views or tables
  the semantic view's `base_table` references. Creates new ThoughtSpot Table objects.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-snowflake/reverse-mapping-rules.md](../../shared/mappings/ts-snowflake/reverse-mapping-rules.md) | Semantic View DDL parsing, model TML templates, type and aggregation mapping |
| [../../shared/mappings/ts-snowflake/formula-translation.md](../../shared/mappings/ts-snowflake/formula-translation.md) | SQL → ThoughtSpot formula translation rules (bidirectional reference) |
| [references/worked-example.md](references/worked-example.md) | End-to-end example: DUNDER_MIFFLIN_SALES → ThoughtSpot Model |

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

**Target call budget:** Aim for **4–6 total SQL calls** per model:

| Call | Purpose |
|---|---|
| 1 | Get DDL + check profile |
| 2 | Search ThoughtSpot for table objects (via stored procedure or API) |
| 3 | Export Table TMLs to find join names (via stored procedure or API) |
| 4 | Import model TML (via stored procedure or API) |

---

## Prerequisites

- A Snowflake role with `USAGE` on the database/schema containing the semantic view
- ThoughtSpot setup completed via `/thoughtspot-setup` — `SKILLS.PUBLIC.THOUGHTSPOT_PROFILES` table must exist with at least one profile
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege in ThoughtSpot

---

## Workflow

### Step 1: Get profile and DDL

Batch profile retrieval and DDL fetch in a single call:

```sql
-- Batch: profile + DDL
SELECT NAME, BASE_URL, USERNAME, SECRET_NAME, TOKEN_EXPIRES_AT
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
LIMIT 1;

SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{view_name}');
```

If the user has not named the semantic view, first list available views:

```sql
SHOW SEMANTIC VIEWS IN SCHEMA {database}.{schema};
```

Display results as a numbered list and ask the user to select one.

**Authenticate with ThoughtSpot** using the profile:

First check token expiry:
```sql
SELECT TOKEN_EXPIRES_AT > CURRENT_TIMESTAMP() AS is_valid
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE NAME = '{profile_name}';
```

If `is_valid = FALSE` or `TOKEN_EXPIRES_AT IS NULL`: stop and tell the user:
> "Your ThoughtSpot token has expired. Run `/thoughtspot-setup` → U → Refresh token, then retry."

If valid, retrieve the bearer token:
```sql
SELECT SYSTEM$GET_SECRET_STRING('SKILLS.PUBLIC.' || SECRET_NAME) AS token
FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES
WHERE NAME = '{profile_name}';
```

Store the token value for use in subsequent API calls. Never print it.

---

### Step 2: Parse the DDL

Parse the DDL string returned in Step 1. The DDL is a SQL `CREATE OR REPLACE
SEMANTIC VIEW` statement. See [../../shared/mappings/ts-snowflake/reverse-mapping-rules.md](../../shared/mappings/ts-snowflake/reverse-mapping-rules.md)
for the full DDL format.

Extract:
1. **Tables block:** alias, base table reference, primary key, dimensions, time_dimensions, per-table metrics
2. **Relationships block:** name, from table/key, to table/key
3. **Global metrics block:** name, aliases, expr
4. **Extension JSON:** log but do not map to ThoughtSpot

Identify the **fact table**: the table that never appears on the `TO` side of any relationship.

---

### Step 3: Choose scenario

Present the user with a clear choice:

```
The semantic view references these base tables:
  {database}.{schema}.{TABLE_1}
  {database}.{schema}.{TABLE_2}
  ...

How should the ThoughtSpot Model be built?

  A) On the underlying physical tables (recommended if already in ThoughtSpot)
  B) On these tables/views as-is (creates new ThoughtSpot Table objects)

Select A or B:
```

---

### Step 4A: Find ThoughtSpot Table objects (Scenario A)

**First, ask the user before searching:**

```
Do the base tables already exist as Table objects in ThoughtSpot?

  Y) Yes — search ThoughtSpot to find them
  N) No — I'll provide the connection name to use

Enter Y or N:
```

**If Y:** Search ThoughtSpot for existing table objects:

```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS('{profile_name}', '{table_name}', FALSE);
```

Filter results to match by database + schema + table name against the semantic
view's `BASE TABLE` refs.

Build map: `physical_table_name → {guid, metadata_name}`.

**If N:** Ask for the connection name:

```
Which ThoughtSpot connection should be used for these tables?

Connection name:
```

Store as `{connection_name}`. The tables will be added to this connection and
Table TML objects will be created automatically (follow Step 4B for table creation,
but use the named connection instead of creating a new one).

---

### Step 4B: Create ThoughtSpot Table objects (Scenario B)

**When tables don't exist in ThoughtSpot, create them first before the model.**

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
    type: LEFT_OUTER
```

Import all table TMLs in one call:
```sql
CALL SKILLS.PUBLIC.TS_IMPORT_TML('{profile_name}', ARRAY_CONSTRUCT($$...$$, $$...$$), TRUE);
```

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

3. **Join type should default to `INNER`** (not `LEFT_OUTER`). Snowflake semantic views
   don't specify join type, but ThoughtSpot models work best with INNER joins for
   lookup/dimension tables. At the review checkpoint (Step 7), ask the user:
   ```
   Join type for all relationships:
     1) INNER (recommended for dimension lookups)
     2) LEFT_OUTER
   ```

4. **Column `column_id`** format is `TABLE_NAME::COLUMN_NAME` (not `db_column_name`).

5. **Display names** should be title-cased (e.g. "Superhero Name" not "SUPERHERO_NAME").

6. **Model `properties`** should include:
   ```yaml
   properties:
     is_bypass_rls: false
     join_progressive: true
   ```

Apply all column, formula, and join mappings from
[../../shared/mappings/ts-snowflake/reverse-mapping-rules.md](../../shared/mappings/ts-snowflake/reverse-mapping-rules.md) to build
the model TML dict. Serialise to a YAML string.

For each metric in the semantic view:
- Simple `AGG(table.col)` → `MEASURE` column in `columns[]`
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

Import via the stored procedure:

```sql
CALL SKILLS.PUBLIC.TS_IMPORT_TML('{profile_name}', ARRAY_CONSTRUCT($$
{model_tml_yaml}
$$), TRUE);
```

**IMPORTANT:** Use `$$` dollar-quoting to preserve YAML formatting.

On success, extract and display the created model GUID.

**Common errors:**

| Error | Likely cause | Fix |
|---|---|---|
| `referencing_join not found` | Join name is wrong | Re-export table TML and check join name |
| `column_id not found` | Column name mismatch | Verify physical column name in table TML |
| `fqn resolution failed` | Stale GUID | Re-run Step 4A |
| YAML parse error | Non-printable characters | Strip before serialising |

---

### Step 9: Summary report

```
## Model Import Complete

**Model:** TEST_SV_{view_name}
**GUID:** {guid}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE (SUM) | {TABLE}::{COL} |
| {name} | formula | translated from SQL |

### Formula Translation Log
| Column | Original SQL | Status |
|---|---|---|
| {name} | `{sql}` | ✓ Translated |
| {name} | `{sql}` | ⚠ Omitted — {reason} |

### Not Mapped
- Extension JSON (Cortex Analyst context)
```

---

## Multiple semantic view conversion

After completing one conversion, offer to convert additional views. Reuse the
authenticated ThoughtSpot session (don't re-authenticate between views).
