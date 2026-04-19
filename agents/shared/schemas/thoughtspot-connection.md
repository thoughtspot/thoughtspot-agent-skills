# ThoughtSpot Connection — Reference

How to discover, reference, and update ThoughtSpot connections when building
Table and Model TML. Platform-agnostic — applies to Snowflake, Databricks,
BigQuery, etc.

For creating Table objects that use a connection, see
[thoughtspot-table-tml.md](thoughtspot-table-tml.md).

---

## What a Connection Is

A ThoughtSpot connection represents a live link to a cloud data warehouse (Snowflake,
BigQuery, Databricks, Redshift, etc.). It holds the warehouse credentials, account
details, and the list of tables/columns that ThoughtSpot can query.

Connections are referenced by **name** in Table TML — you never need a connection GUID
when building TML. The connection name is case-sensitive.

---

## Discovering Connections

### List all connections

```bash
ts connections list --profile {profile}
```

Returns a JSON array. Each entry includes:

```json
{
  "id": "1f428ed0-c672-435d-a7e1-b4781e5f492c",
  "name": "APJ_BIRD",
  "description": "",
  "data_warehouse_type": "SNOWFLAKE",
  "data_warehouse_objects": null,
  "details": null
}
```

`data_warehouse_objects` and `details` are always `null` in the list response — they
are not populated even if the connection has registered tables. Use
`ts connections get {id}` to retrieve the full connection object including registered
table/column hierarchy.

`name` is what goes into `connection.name` in Table TML. Copy it verbatim —
ThoughtSpot will return "connection not found" if the case is wrong.

### Filter by warehouse type

```bash
ts connections list --type SNOWFLAKE --profile {profile}
ts connections list --type BIGQUERY --profile {profile}
ts connections list --type DATABRICKS --profile {profile}
```

### CoCo / stored procedure workflow

```sql
CALL SKILLS.PUBLIC.TS_LIST_CONNECTIONS('{profile_name}');
```

Returns the same connection list as the CLI. If the connection name used in Table
TML returns "connection not found", call this to see the available names.

---

## Using a Connection in Table TML

Reference the connection by name in every Table TML object. No GUID or `fqn` lookup
is needed or possible for connections — name is the only identifier used at import time:

```yaml
table:
  name: MY_TABLE
  db: MY_DATABASE
  schema: MY_SCHEMA
  db_table: MY_TABLE
  connection:
    name: "APJ_BIRD"   # exact name from ts connections list — case-sensitive
  columns:
  # ...
```

---

## Adding Tables to an Existing Connection

When Table objects are created via `ts tml import`, ThoughtSpot validates that the
physical columns exist in the connection. If a table is not yet registered in the
connection, the import fails with a column-not-found or table-not-found error.

**Add tables to the connection before importing their Table TML:**

```bash
# Input: JSON array of table descriptors (from stdin)
echo '[
  {
    "db": "MY_DATABASE",
    "schema": "MY_SCHEMA",
    "table": "MY_TABLE",
    "type": "TABLE",
    "columns": [
      {"name": "COL1", "type": "VARCHAR"},
      {"name": "COL2", "type": "NUMBER"}
    ]
  }
]' | ts connections add-tables {connection_id} --profile {profile}
```

`add-tables` merges new tables into the connection without removing existing ones.
Existing tables and columns are preserved; new columns are appended to existing tables.

Get the `connection_id` from `ts connections list`:

```bash
ts connections list --profile {profile} | jq -r '.[] | select(.name == "APJ_BIRD") | .id'
```

**Column type values for `add-tables`:** Use warehouse SQL types here (not ThoughtSpot
data_type values). These are passed to the ThoughtSpot connection API which handles
type normalisation:

| Warehouse | Column type string |
|---|---|
| Snowflake | `VARCHAR`, `NUMBER`, `FLOAT`, `BOOLEAN`, `DATE`, `TIMESTAMP_NTZ`, etc. |
| BigQuery | `STRING`, `INT64`, `FLOAT64`, `BOOL`, `DATE`, `DATETIME`, `TIMESTAMP` |
| Databricks | `STRING`, `BIGINT`, `DOUBLE`, `BOOLEAN`, `DATE`, `TIMESTAMP` |

---

## Connection Errors

| Error | Cause | Fix |
|---|---|---|
| `connection not found` | Wrong name or wrong case in Table TML | Run `ts connections list` and copy the exact name |
| `column not found in connection` | Table not registered in the connection | Run `ts connections add-tables` before importing Table TML |
| `table not found in connection` | Table not registered in the connection | Run `ts connections add-tables` |
| `JDBC driver encountered a communication error` | Transient connectivity to the warehouse | Retry up to 3 times with a 5-second delay |
| `Connection metadata fetch error` | Warehouse credentials have expired or the warehouse is suspended | Ask the user to verify the connection in the ThoughtSpot UI |

---

## Connection Object Structure (from API)

The full connection object returned by `ts connections get {id}` includes the
credential config and the registered table/column hierarchy. Useful for:

- Checking whether a table is already registered before calling `add-tables`
- Reading the `data_warehouse_type` to know which SQL types to use

```bash
ts connections get {connection_id} --profile {profile}
```

> **Note:** `ts connections get` uses the v1 API. It requires
> `CAN_CREATE_OR_EDIT_CONNECTIONS` privilege and may return a 500 on some instances.
> If it fails, fall back to checking the connection in the ThoughtSpot UI.

---

## Workflow: New Source → ThoughtSpot

The typical sequence when a new data source needs to be modelled in ThoughtSpot:

```
1. Identify connection          ts connections list → confirm name + id
2. Register tables              ts connections add-tables {id} ← warehouse column info
3. Create Table TML objects     ts tml import ← Table TMLs referencing connection name
4. Build Model TML              see thoughtspot-model-tml.md
5. Import Model                 ts tml import ← Model TML referencing table GUIDs
```

Steps 2 and 3 can be batched — `add-tables` and Table TML import can use the same
column introspection data. Step 2 is required before step 3 when tables are not yet
registered in the connection.
