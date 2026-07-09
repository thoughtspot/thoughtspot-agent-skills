# ThoughtSpot SQL View TML — Structure Reference

How a ThoughtSpot SQL View is represented in TML. A SQL View is a query-backed
logical table — it runs raw SQL against a database connection and exposes the
result columns to Answers, Liveboards, and Models.

**This is NOT a View (AGGR_WORKSHEET).** For the `view:` TML type
(search-query-based logical tables built on existing ThoughtSpot Tables), see
[thoughtspot-view-tml.md](thoughtspot-view-tml.md).

**Metadata search identifiers:**
- `type`: `LOGICAL_TABLE`
- `subtype`: `SQL_VIEW`

```bash
# Find a SQL View by name
ts metadata search --subtype SQL_VIEW --name '%view_name%' --profile {profile}
```

---

## `sql_view:` vs `view:` (AGGR_WORKSHEET)

| Aspect | `sql_view:` | `view:` (AGGR_WORKSHEET) |
|---|---|---|
| TML root key | `sql_view:` | `view:` |
| Data source | `sql_query:` (raw SQL) | `search_query:` (ThoughtSpot search syntax) |
| Column definition | `sql_view_columns:` with `sql_output_column:` | `view_columns:` with `column_id:` |
| Connection | Required — `connection.name:` | Not needed — references Tables |
| Formula syntax | Standard ThoughtSpot formulas | `if/then/else` keywords, row-level only |
| Aggregation | In the SQL query or formulas | In `search_query` keywords |
| File extension (export) | `*.sql_view.tml` | `*.view.tml` |

---

## Full Annotated SQL View TML Structure

```yaml
guid: "<sql_view_guid>"               # document root — omit on first import; required to update in-place
sql_view:
  name: "SQL View Display Name"
  description: |
    Multi-line description.
  connection:
    name: "Connection Display Name"    # exact ThoughtSpot connection name — case-sensitive
  sql_query: |
    SELECT col1, col2, col3
    FROM catalog.schema.table
    WHERE condition = 'value'
  sql_view_columns:
  - name: "Display Name"
    description: "Column description"
    sql_output_column: "col1"          # must match a column name or alias from the SQL query output
    data_type: VARCHAR                 # optional — ThoughtSpot infers from query; specify to override
    properties:
      column_type: ATTRIBUTE
      index_type: DEFAULT              # DEFAULT | DONT_INDEX
      index_priority: 1               # optional — integer for search indexing priority
      synonyms:                        # optional — alternative names for search
      - "alt_name"
      is_hidden: false                 # optional — hides column from search bar
      geo_config:                      # optional — geographic role
        region_name:
        - country: "United States"
          region_name: "state"
  - name: "Amount"
    sql_output_column: "col2"
    data_type: DOUBLE
    properties:
      column_type: MEASURE
      aggregation: SUM                 # SUM, COUNT, AVERAGE, MIN, MAX, COUNT_DISTINCT
      is_additive: true                # optional — marks column as additive
      format_pattern: "#,##0.00"       # optional — display format
      currency_type:
        iso_code: USD                  # optional — adds currency symbol
      spotiq_preference: "EXCLUDE"     # optional — excludes from SpotIQ auto-analysis
  - name: "Date Column"
    sql_output_column: "col3"
    data_type: DATE
    properties:
      column_type: ATTRIBUTE
      index_type: DONT_INDEX
      calendar: CALENDAR_TYPE_GREGORIAN  # optional — date columns
      is_attribution_dimension: false    # optional
  formulas:                            # optional — calculated columns on top of the SQL output
  - id: "formula_Metric Name"
    name: "Metric Name"
    expr: "sum ( [SQL View Display Name::col2] ) / count ( 1 )"
    properties:
      column_type: MEASURE
  joins_with:                          # optional — join this SQL View to other objects
  - name: "ViewName_to_TargetTable"
    destination:
      name: "TARGET_TABLE"
      fqn: "<table_guid>"             # optional — GUID of the destination object
    'on': "[SQL View Display Name::col1] = [TARGET_TABLE::pk_col]"
    type: LEFT_OUTER                   # INNER | LEFT_OUTER | RIGHT_OUTER | FULL_OUTER
    is_one_to_one: false               # optional — boolean
```

---

## Field Reference

### Top-level fields

| Field | Required | Notes |
|---|---|---|
| `guid` | On update only | Document root — NOT inside `sql_view:`. Omit on first import. |
| `sql_view.name` | Yes | Display name in ThoughtSpot |
| `sql_view.description` | No | Optional description |
| `sql_view.connection.name` | Yes | ThoughtSpot connection name (case-sensitive) — NOT a GUID |
| `sql_view.connection.fqn` | No | Connection GUID — populated by `--fqn` export; not required on import |
| `sql_view.sql_query` | Yes | Raw SQL query string executed against the connection |
| `sql_view.sql_view_columns` | Yes | At least one column required |
| `sql_view.formulas` | No | Calculated columns — same syntax as Table/Model formulas |
| `sql_view.joins_with` | No | Only include when the SQL View joins to other objects |

### `sql_view_columns[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Display name in ThoughtSpot — used in join expressions and model column references |
| `description` | No | Optional column description |
| `sql_output_column` | Yes | Must match a column name or alias from the SQL query output. Case-sensitive. |
| `data_type` | No | ThoughtSpot data type (`VARCHAR`, `INT64`, `DOUBLE`, `DATE`, `DATE_TIME`, `BOOL`). Inferred from the query if omitted. |
| `properties.column_type` | Yes | `ATTRIBUTE` or `MEASURE` |
| `properties.aggregation` | No | For MEASURE columns: `SUM`, `COUNT`, `AVERAGE`, `MIN`, `MAX`, `COUNT_DISTINCT` |
| `properties.index_type` | No | `DONT_INDEX` suppresses text search indexing. Omit for default (indexed). |
| `properties.index_priority` | No | Integer — controls search indexing priority |
| `properties.synonyms` | No | Array of alternative names for search. Must be under `properties:`. |
| `properties.is_attribution_dimension` | No | Boolean — marks column as an attribution dimension |
| `properties.is_additive` | No | Boolean — marks column as additive |
| `properties.calendar` | No | Calendar type for date columns (e.g. `CALENDAR_TYPE_GREGORIAN`) |
| `properties.format_pattern` | No | Number/date display format string |
| `properties.currency_type.iso_code` | No | ISO currency code (e.g. `USD`, `EUR`) |
| `properties.is_hidden` | No | `true` hides the column from the search bar |
| `properties.geo_config` | No | Geographic role — same structure as Table/Model TML |
| `properties.spotiq_preference` | No | `"EXCLUDE"` removes column from SpotIQ auto-analysis |

### `formulas[]` fields

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Formula identifier — convention: `"formula_"` + name |
| `name` | Yes | Display name — must match the `id` suffix |
| `expr` | Yes | ThoughtSpot formula expression. Column refs use `[SQLViewName::column]` syntax. |
| `properties.column_type` | No | `ATTRIBUTE` or `MEASURE` — defaults to `MEASURE` if omitted |

### `joins_with[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Join identifier — used as `referencing_join` when a Model references this join |
| `destination.name` | Yes | Exact name of the target ThoughtSpot object (table, view, or SQL view) |
| `destination.fqn` | No | GUID of the destination object — optional but recommended for disambiguation |
| `on` | Yes | Join condition — uses `[ObjectName::col]` references. Quote as `'on':` in YAML (reserved word). |
| `type` | Yes | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `FULL_OUTER` |
| `is_one_to_one` | No | Boolean — `true` for 1:1 joins, `false` or absent for many-to-one/many-to-many |

---

## How Models Reference SQL Views

A Model can reference a SQL View in its `model_tables[]` — the SQL View acts as a
table source alongside regular Tables. The same `model_tables[]` patterns (inline
joins, `referencing_join`, column references) apply.

```yaml
model:
  name: "Sales Model"
  model_tables:
  - name: "Working_Day_Index_Dim"      # SQL View name — exact match
    fqn: "{sql_view_guid}"
  - name: "Orders_Fact"
    fqn: "{table_guid}"
    joins:
    - with: "Working_Day_Index_Dim"
      'on': '[Orders_Fact::date] = [Working_Day_Index_Dim::date]'
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  columns:
  - name: "Working Day Index"
    column_id: Working_Day_Index_Dim::workingDayIndex
    properties:
      column_type: MEASURE
      aggregation: SUM
```

Column references use `[SQL_VIEW_NAME::column]` syntax — the same pattern as
regular table column references. The Model's `model_tables:` section includes
the SQL View by name.

When exported with `--associated`, SQL View objects appear alongside Model TML
in the export bundle.

---

## Key Differences from Table TML

| Aspect | Table TML (`table:`) | SQL View TML (`sql_view:`) |
|---|---|---|
| Data source | Physical table/view via `db`, `schema`, `db_table` | Raw SQL query via `sql_query` |
| Column list | `columns:` with `db_column_name:` | `sql_view_columns:` with `sql_output_column:` |
| Column type mapping | `db_column_properties.data_type` (required) | `data_type` at column level (optional — inferred from query) |
| Connection reference | `connection.name` only | `connection.name` (required) + optional `connection.fqn` |
| Formulas | Not supported at table level | `formulas:` section supported |

---

## GUID and Updates

**`guid` at document root — never inside `sql_view:`:**

```yaml
guid: "{existing_sql_view_guid}"   # MUST be first key in the document
sql_view:
  name: "<view_name>"
  # ...
```

`guid` nested under `sql_view:` is silently ignored — ThoughtSpot creates a new
duplicate object. Always place it as the first key in the document.

**First import:** omit `guid`. After import, record the assigned GUID for future
updates.

**Finding an existing GUID:**
```bash
ts metadata search --subtype SQL_VIEW --name '%{view_name}%' --profile {profile}
```

---

## Connection Reference

Same rules as Table TML. Use the connection `name` directly:

```yaml
connection:
  name: "APJ_BIRD"   # exact name as it appears in ThoughtSpot Connections
```

Connection names are case-sensitive. To list available connections:

```bash
ts connections list --profile {profile}
```

---

## SQL Query Conventions

The `sql_query` field contains raw SQL that ThoughtSpot executes against the
database connection. Conventions:

- The SQL dialect must match the connection's database type (Snowflake SQL for
  Snowflake connections, Databricks SQL for Databricks connections, etc.)
- Every column alias in the SQL query that you want to expose must have a
  matching `sql_output_column` entry in `sql_view_columns[]`
- Columns in the SQL output that have no `sql_view_columns[]` entry are ignored
- Use explicit column aliases in the SQL query to control the `sql_output_column`
  mapping — implicit names from `SELECT *` are fragile

**Multi-line SQL in YAML:** use a block scalar (`|`) for readability:

```yaml
sql_query: |
  SELECT DISTINCT
    d.date_value AS date,
    ROW_NUMBER() OVER (ORDER BY d.date_value) AS workingDayIndex
  FROM calendar_dim d
  WHERE d.is_business_day = TRUE
```

### Snowflake note — unquoted identifiers are UPPERCASE

Snowflake folds unquoted identifiers (table names, column names, and `AS` aliases) to
UPPERCASE at parse time, regardless of how they're cased in the SQL you write. This means
`sql_output_column` must match the *folded* name, not the literal casing typed in the
`sql_query` alias — and both should simply be written in uppercase from the start to avoid
the mismatch entirely.

**Wrong (fails on import, even though the SQL runs fine standalone):**
```yaml
sql_query: |
  SELECT session_id, MIN(created_at) AS session_start FROM events GROUP BY 1
sql_view_columns:
- name: Session Id
  sql_output_column: session_id       # lowercase — does not match Snowflake's folded SESSION_ID
```
Import error: `"Column name [session_id, session_start] is not present in SQL query."`

**Correct:**
```yaml
sql_query: |
  SELECT session_id AS SESSION_ID, MIN(created_at) AS SESSION_START FROM events GROUP BY 1
sql_view_columns:
- name: Session Id
  sql_output_column: SESSION_ID
```

This only applies to warehouses with case-folding on unquoted identifiers (Snowflake,
and similarly Oracle/DB2 fold to uppercase). Databricks and Postgres preserve the alias
case as written — check the target connection's warehouse type (`ts connections list`)
before assuming which rule applies.

---

## Self-Validation Checklist

Before importing a SQL View TML:

- [ ] `guid:` is at the document root, not nested inside `sql_view:`
- [ ] `connection.name:` is present (required for SQL Views)
- [ ] `sql_query:` is non-empty and contains valid SQL for the target connection's dialect
- [ ] Every `sql_view_columns[].sql_output_column` matches a column name or alias in the SQL query output
- [ ] No `search_query:` field present (that belongs to `view:`, not `sql_view:`)
- [ ] Every `column_type` is nested under `properties:` — not bare at the column level
- [ ] No duplicate `name` values across `sql_view_columns[]`
- [ ] If `formulas[]` are present, every `id` follows `"formula_"` + name convention
- [ ] If `joins_with[]` is present, every `destination.name` matches a real ThoughtSpot object
- [ ] Join `on` expressions are quoted as `'on':` in YAML (reserved word)

---

## Common Import Errors

| Error | Cause | Fix |
|---|---|---|
| `connection not found` | Wrong connection name or wrong case | Run `ts connections list` and copy the exact name |
| Using `view:` instead of `sql_view:` | Completely different object types — `view:` creates an AGGR_WORKSHEET | Change the top-level key to `sql_view:` |
| Missing `connection.name:` | SQL Views require a connection reference | Add `connection.name:` with the exact connection name |
| `sql_output_column` mismatch | Column name in `sql_output_column` does not match the SQL query output | Run the SQL query manually and verify column names/aliases |
| Using `search_output_column` | Wrong field name — that does not exist for SQL Views | Use `sql_output_column` |
| `duplicate column name` | Two `sql_view_columns[]` entries share the same `name` | Rename one of the columns |
| `JDBC driver encountered a communication error` | Transient connectivity issue | Retry up to 3 times with a 5-second delay |
| `fqn resolution failed` | GUID is stale | Re-search for the current GUID |
| SQL syntax error | Query is invalid for the connection's database dialect | Test the SQL query directly against the database before importing |
| YAML parse error | Non-printable characters or unquoted special characters | Strip non-printable chars; ensure `'on':` is quoted |

---

## Import Command

```bash
ts tml import --profile {p} --policy PARTIAL --create-new < sql_view.tml.yaml
```

Use `--policy PARTIAL` to allow partial success when importing alongside other objects.
Use `--create-new` on first import (when `guid` is omitted). Omit `--create-new` when
updating an existing SQL View (when `guid` is present at the document root).
