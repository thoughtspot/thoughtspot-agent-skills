# ThoughtSpot Table TML — Construction Reference

How to construct a valid ThoughtSpot Table TML for import via the REST API or
stored procedures. Platform-agnostic — applies to any source (Snowflake, Databricks,
Redshift, etc.).

For parsing TML that was **exported** from ThoughtSpot (PyYAML pitfalls,
non-printable characters, object type detection), see
[thoughtspot-tml.md](thoughtspot-tml.md).

---

## Full Table TML Structure

```yaml
guid: "{existing_guid}"   # document root — omit on first import; required to update in-place
table:
  name: TABLE_NAME            # exact name as it will appear in ThoughtSpot
  db: DATABASE_NAME
  schema: SCHEMA_NAME
  db_table: TABLE_NAME        # physical table/view name in the warehouse
  connection:
    name: "{connection_name}" # exact ThoughtSpot connection name — case-sensitive
  columns:
  - name: COL_NAME             # display name in ThoughtSpot
    db_column_name: COL_NAME  # physical column name — omit when it equals name
    description: "Optional description or source column alias"
    properties:
      column_type: ATTRIBUTE  # ATTRIBUTE or MEASURE
      index_type: DONT_INDEX  # optional — omit for default (indexed)
      value_casing: UNKNOWN   # optional — VARCHAR columns: UPPER | LOWER | MIXED | UNKNOWN
    db_column_properties:
      data_type: VARCHAR       # ThoughtSpot data type — see type mapping below
  # joins_with: omit entirely when this table has no FK relationships
  # (do NOT write joins_with: [] — absent key is different from empty array)
  joins_with:
  - name: JOIN_NAME
    destination:
      name: TARGET_TABLE_NAME
    'on': "[SOURCE_TABLE::FK_COL] = [TARGET_TABLE::PK_COL]"
    # on expressions may optionally be wrapped in parens — both styles are valid:
    # 'on': "([SOURCE_TABLE::FK_COL] = [TARGET_TABLE::PK_COL])"
    type: INNER                # INNER | LEFT_OUTER | RIGHT_OUTER | FULL_OUTER
    cardinality: MANY_TO_ONE   # MANY_TO_ONE | ONE_TO_ONE | ONE_TO_MANY | MANY_TO_MANY
  properties:
    spotter_config:
      is_spotter_enabled: false  # optional — controls Spotter (AI search) for this table
```

---

## Field Reference

### Top-level fields

| Field | Required | Notes |
|---|---|---|
| `guid` | On update only | Document root — NOT inside `table:`. Omit on first import. |
| `table.name` | Yes | Display name in ThoughtSpot — used to reference this table in Models |
| `table.db` | Yes | Warehouse database name |
| `table.schema` | Yes | Warehouse schema name |
| `table.db_table` | Yes | Physical table or view name in the warehouse |
| `table.connection.name` | Yes | ThoughtSpot connection name (case-sensitive) — NOT a GUID |
| `table.columns` | Yes | At least one column required |
| `table.joins_with` | No | Only include on tables that have FK relationships to other tables |

### `columns[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Display name — also used as `column_id` suffix in model TML (`TABLE::name`) |
| `db_column_name` | No | Physical column name in the warehouse. Omit when it equals `name`. Required when the display name differs from the physical column name. |
| `description` | No | Optional description. Sometimes used to record the original db column name when `name` is a friendly alias (e.g. `"description": "RECVDATE"` on a column named `"Received Date"`). |
| `properties.column_type` | Yes | `ATTRIBUTE` or `MEASURE` |
| `db_column_properties.data_type` | Yes | ThoughtSpot type value — see type mapping below |
| `properties.aggregation` | No | For MEASURE columns: `SUM`, `COUNT`, `AVERAGE`, `MIN`, `MAX`, `COUNT_DISTINCT` |
| `properties.index_type` | No | `DONT_INDEX` suppresses text search indexing — recommended for measures and date/FK columns. Omit for default (indexed). |
| `properties.value_casing` | No | For VARCHAR columns: `UPPER`, `LOWER`, `MIXED`, or `UNKNOWN`. Only present when ThoughtSpot has detected or assigned a casing convention. |

### `joins_with[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Join identifier — used as `referencing_join` in model TML (Scenario A) |
| `destination.name` | Yes | Exact `name` of the target ThoughtSpot table object |
| `on` | Yes | Join condition — uses `[TABLE::col]` references. Multiple conditions joined with `AND` are supported. |
| `type` | Yes | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `FULL_OUTER` |
| `cardinality` | Yes | `MANY_TO_ONE`, `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY` |
| `is_one_to_one` | No | Boolean — seen on data augmentation joins and SQL view joins |

---

## Data Type Mapping

Use ThoughtSpot data type values in `db_column_properties.data_type`. The API rejects
SQL type names — `BIGINT`, `INTEGER`, `TIMESTAMP` etc. will cause a type mismatch error.

| Warehouse type (generic) | ThoughtSpot `data_type` |
|---|---|
| Integer / whole number | `INT64` |
| Float / decimal / numeric (Snowflake) | `DOUBLE` |
| Float / decimal / numeric (BigQuery) | `FLOAT` |
| Text / varchar / string / char | `VARCHAR` |
| Boolean (Snowflake) | `BOOL` |
| Boolean (general / may vary) | `BOOLEAN` |
| Date | `DATE` |
| Datetime / timestamp | `DATE_TIME` |

**Source-specific mappings** are in the relevant mappings file (e.g.
`mappings/ts-snowflake/ts-from-snowflake-rules.md` for Snowflake types).

**`INT64` not `BIGINT`:** ThoughtSpot returns `DataType BIGINT does not match CDW DataType`
if you use SQL type names. When uncertain between `INT64` and `DOUBLE` (e.g. a
`NUMBER` column), use `INT64` — ThoughtSpot will report a mismatch if wrong, giving
you a clear signal to switch.

---

## Connection Reference

**Use the connection `name` directly — never look up a GUID:**

```yaml
connection:
  name: "APJ_BIRD"   # exact name as it appears in ThoughtSpot Connections
```

Connection names are case-sensitive. To list available connections:

```bash
ts connections list --profile {profile}
```

If import fails with a connection-related error (e.g. "connection not found"), the
name is wrong — list connections and correct it. Do not try to look up a connection
by GUID; the ThoughtSpot REST API v2 does not expose a connection-search-by-name
endpoint.

---

## GUID and Updates

**`guid` at document root for updates:**

```yaml
guid: "{existing_table_guid}"   # TOP of document
table:
  name: TABLE_NAME
  ...
```

`guid` nested inside `table:` is silently ignored — ThoughtSpot creates a new
duplicate object. Always place it as the first key in the document.

**First import:** omit `guid` entirely. After import, record the assigned GUID for
future updates.

---

## Import Patterns

### Retrieving the GUID after import

**CLI workflow:** `ts tml import` often returns an empty `object` list even on success.
Retrieve the GUID by searching immediately after import:

```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --name '{table_name}' --profile {profile}
```

**CoCo / stored procedure workflow:** Use `RESULT_SCAN` of the import call — do NOT
search by name. `TS_SEARCH_MODELS` returns tables from ALL connections; you cannot
distinguish newly-created tables from pre-existing ones with the same name. See the
CoCo SKILL.md for the `OBJECT_AGG` extraction pattern.

### Transient JDBC errors

ThoughtSpot occasionally returns `CONNECTION_METADATA_FETCH_ERROR / JDBC driver
encountered a communication error` during table TML import. This is transient — retry
up to 3 times with a 5-second delay before treating it as a real failure.

### Importing multiple tables

Batch all table TMLs into a single import call. ThoughtSpot processes them as a unit
and is more efficient than one call per table. Use `PARTIAL` policy so one bad table
doesn't block the others:

```bash
# CLI
echo '["{table1_tml}", "{table2_tml}"]' | ts tml import --policy PARTIAL --profile {profile}
```

---

## SQL View TML (`sql_view`)

A `sql_view` is a ThoughtSpot object backed by a SQL query rather than a physical table.
It exports as a `sql_view` TML object (not `table`) with filename `*.sql_view.tml`.

```yaml
guid: "{existing_guid}"
sql_view:
  name: Working_Day_Index_Dim
  connection:
    name: "{connection_name}"
    fqn: "{connection_guid}"
  sql_query: "SELECT DISTINCT date, ROW_NUMBER() OVER (ORDER BY date) AS workingDayIndex FROM ..."
  sql_view_columns:
  - name: date
    sql_output_column: date         # matches the column alias in sql_query
    properties:
      column_type: ATTRIBUTE
      index_type: DONT_INDEX
  - name: workingDayIndex
    sql_output_column: workingDayIndex
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  joins_with:                       # optional — sql_views can define joins to other tables
  - name: "ViewName_to_TargetTable"
    destination:
      name: TARGET_TABLE
      fqn: "{table_guid}"
    'on': "[ViewName::col] = [TARGET_TABLE::col]"
    type: LEFT_OUTER
    is_one_to_one: true
```

**Key differences from `table` TML:**
- Top-level key is `sql_view:` not `table:`
- Has `sql_query:` instead of `db`, `schema`, `db_table`
- Columns defined in `sql_view_columns:` (not `columns:`) with `sql_output_column:` mapping
- When exported with `--associated`, sql_view objects appear alongside model TML

---

## Common Import Errors

| Error | Cause | Fix |
|---|---|---|
| `DataType BIGINT does not match CDW DataType` | SQL type name used in `data_type` | Use `INT64`, `VARCHAR`, `DOUBLE`, etc. — not SQL names |
| `connection not found` | Wrong connection name or wrong case | Run `ts connections list` and copy the exact name |
| `column not found in connection` | `db_column_name` doesn't match the physical column | Check the warehouse schema for the correct column name |
| `JDBC driver encountered a communication error` | Transient connectivity issue | Retry up to 3 times with a 5-second delay |
| `Multiple tables have same name` | Two imports created duplicate table objects | Delete the duplicate with `ts metadata delete {guid}` |
| `fqn resolution failed` | GUID is stale | Re-search for the current GUID |
| YAML parse error | Non-printable characters in column names or descriptions | Strip non-printable chars before serialising |
