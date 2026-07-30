<!-- currency: thoughtspot — 2026-07 (2026-07-30: corrected joins_with[].type — FULL_OUTER is invalid and OUTER was missing, live-verified on se-thoughtspot. Also 2026-07-30, from a 500-document TML property census on se-thoughtspot covering 275 Tables: rls_rules.table_paths[].column corrected to a list of bare names; joins_with[].cardinality de-required (0 of 165 exported joins carry it); four column properties added (format_pattern, is_hidden, currency_type, calendar); dataset_id documented; connection block noted as absent on Falcon tables; 2026-07-23: added rls_rules structure; prior: validated in 2026-07-11 external sweep) -->

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
    db_column_name: COL_NAME  # physical column name — always include even when equal to name
    description: "Optional description or source column alias"
    properties:
      column_type: ATTRIBUTE  # ATTRIBUTE or MEASURE
      index_type: DONT_INDEX  # optional — omit for default (indexed)
      value_casing: UNKNOWN   # optional — VARCHAR columns: UPPER | LOWER | MIXED | UNKNOWN
      format_pattern: "MM/dd/yyyy"  # optional — display format (date or number)
      is_hidden: false        # optional — hides the column from the search bar
      calendar: calendar      # optional — DATE columns only; a custom-calendar NAME
      currency_type:          # optional — MEASURE columns
        column: TARGET_CURRENCY     # per-row ISO code read from another column
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
    type: INNER                # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER (OUTER = full outer; FULL_OUTER is invalid)
    cardinality: MANY_TO_ONE   # MANY_TO_ONE | ONE_TO_ONE | ONE_TO_MANY | MANY_TO_MANY
                               # required on IMPORT; never present on EXPORT — see the note below
  # rls_rules: omit entirely when this table has no row-level security rules
  rls_rules:
    tables:
      - name: TABLE_NAME           # self-reference to the owning table
    table_paths:
      - id: T_1                    # alias used in rule expressions
        table: TABLE_NAME
        column:                    # a LIST of BARE column names — not "[COL_NAME]"
          - COL_NAME
    rules:
      - name: RULE_NAME
        expr: "[T_1::COL_NAME] = ts_groups_int"  # bracket refs use table_paths aliases
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
| `table.connection.name` | Yes, for warehouse-backed tables | ThoughtSpot connection name (case-sensitive) — NOT a GUID. `name` is the **only** key ever seen in a connection block (313 of 313 in the 2026-07-30 census, across Tables and SQL Views) — never `fqn:`. **But the block is not universally present:** 2 of 275 census Tables have no `connection` block at all — `MetricsMonitoring` (`db: thoughtspot_internal_stats`) and `sav_dim_unit` (`db: falcon_default_schema`), both Falcon / in-memory tables. A reader that assumes a connection block exists will crash on those; a *generator* still always emits it. |
| `table.columns` | Yes | At least one column required |
| `table.joins_with` | No | Only include on tables that have FK relationships to other tables |
| `table.rls_rules` | No | Row-level security rules. Contains `tables` (self-reference), `table_paths` (aliases for bracket refs), and `rules` (name + expr). Import all related Table TMLs together when `rls_rules` reference other tables. |
| `table.dataset_id` | No | A 12-hex-character identifier (`28ede9b627ab`) observed at the Table root on uploaded/derived tables — 4 of 275 in the 2026-07-30 census (`cbre_fact_revenue`, `doordash_report_by_data_usage`, `silvia___test_1`, `gerdau_procurement`). **Instance-local: never carry it into a portable document** and never re-emit a value copied from another instance. Pass through only on a same-instance round trip. Undocumented by ThoughtSpot; recorded here because a converter that carries it unknowingly makes its output non-portable |

### `columns[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Display name — also used as `column_id` suffix in model TML (`TABLE::name`) |
| `db_column_name` | Yes | Physical column name in the warehouse. **Always include**, even when it equals `name` — some ThoughtSpot instances reject import if absent. |
| `description` | No | Optional description. Sometimes used to record the original db column name when `name` is a friendly alias (e.g. `"description": "RECVDATE"` on a column named `"Received Date"`). |
| `properties.column_type` | Yes | `ATTRIBUTE` or `MEASURE` |
| `db_column_properties.data_type` | Yes | ThoughtSpot type value — see type mapping below |
| `properties.aggregation` | No | For MEASURE columns: `SUM`, `COUNT`, `AVERAGE`, `MIN`, `MAX`, `COUNT_DISTINCT` |
| `properties.index_type` | No | `DONT_INDEX` suppresses text search indexing — recommended for measures and date/FK columns. Omit for default (indexed). |
| `properties.value_casing` | No | For VARCHAR columns: `UPPER`, `LOWER`, `MIXED`, or `UNKNOWN`. Only present when ThoughtSpot has detected or assigned a casing convention. |
| `properties.synonyms` | No | Array of alternative names for natural-language search. **Must live under `properties:`** — top-level `synonyms:` at the column root is silently dropped on import. |
| `properties.synonym_type` | No | Set to `USER_DEFINED` whenever you populate `properties.synonyms`. |
| `properties.format_pattern` | No | Display format string — date or number. **Added 2026-07-30:** documented on Model and SQL-View columns but missing from this reference; the census found it on 13 of 275 Tables (37 columns) with values `MM/dd/yyyy`, `yyyy-MM-dd HH:mm:ss`, `#,###`, `dd MMM YYYY`. |
| `properties.is_hidden` | No | `true` hides the column from the search bar. **Added 2026-07-30** (11 sightings, 4 Tables). Same caution as the Model reference: do not set during conversion — hidden columns cause locked visualizations. |
| `properties.currency_type` | No | Currency symbol and formatting for a MEASURE. Same three mutually-exclusive forms as the Model reference (`iso_code`, `column`, `is_browser`). **Added 2026-07-30** — and the single live sighting anywhere of the `column` form is on a Table column: `{"column": "TARGET_CURRENCY"}` on `TARGET_CURRENCY_RATES`. Note it is a **bare column name**, not a `TABLE::Column` reference. |
| `properties.calendar` | No | **DATE columns only** — the name of a Connection-scoped custom calendar. **Added 2026-07-30, and this settles an open question:** `calendar:` **is** honoured on a Table column, not only on a Model column — `FACT_RETAPP_SALES.RECORDDATE: SeanTSCROOTS`, 1 of 275 Tables. Same portability caveat as the Model reference (see [thoughtspot-model-tml.md](thoughtspot-model-tml.md) `properties.calendar`): the calendar object lives outside TML, so **do not emit when generating a table** — pass through on round-trips only. |
| `table.description` | No | Table-level description (top-level under `table:`). Maps from Snowflake Semantic View `tables (...)` table-comment clauses. |

### `joins_with[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Join identifier — used as `referencing_join` in model TML (Scenario A) |
| `destination.name` | Yes | Exact `name` of the target ThoughtSpot table object |
| `on` | Yes | Join condition — uses `[TABLE::col]` references. Multiple conditions joined with `AND` are supported. Supports range/inequality operators (`>=`, `<`, `>`, `<=`) for range joins, ASOF joins, and SCD lookups — see Range Joins in [thoughtspot-model-tml.md](thoughtspot-model-tml.md). |
| `type` | Yes | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `OUTER` — and nothing else. **`OUTER` *is* the full outer join** (per ThoughtSpot domain review, 2026-07-30); `FULL_OUTER` is **not** a ThoughtSpot value and is rejected here exactly as it is in Model TML: `Invalid value FULL_OUTER of field table->joins_with(1st)->type. Allowed values are INNER, LEFT_OUTER, OUTER, RIGHT_OUTER` (error 14528, live-verified 2026-07-30 on `se-thoughtspot`; the other four passed as controls in the same document). This reference previously listed `FULL_OUTER` and omitted `OUTER` — that was wrong. See [thoughtspot-model-tml.md](thoughtspot-model-tml.md) *`joins[]` fields* for the full probe record. |
| `cardinality` | On import | `MANY_TO_ONE`, `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY`. **Required on import, but never emitted on export** — a 2026-07-30 census found it absent from **all 165** `joins_with[]` entries across 275 real Tables, while the Model document's *inline* joins carry it freely (`MANY_TO_ONE` ×223, `ONE_TO_MANY` ×11, `ONE_TO_ONE` ×3). Practical consequence for a round trip: **re-importing an exported Table TML verbatim submits a document with no `cardinality`**, so a generator must supply one, and a validator must not treat its absence in an *exported* document as a defect. Which of the two readings is right — import-required/export-dropped, or the requirement being wrong — is not settled by export evidence alone; the safe behaviour is to emit it and to tolerate its absence |
| `is_one_to_one` | No | Boolean — seen on data augmentation joins and SQL view joins |

### `rls_rules` fields

| Field | Required | Notes |
|---|---|---|
| `rls_rules.tables[].name` | Yes | Self-reference to the owning table (and any other table the rules reach) |
| `rls_rules.table_paths[].id` | Yes | Alias used in rule expressions — `[T_1::COL]` |
| `rls_rules.table_paths[].table` | Yes | The table this path starts from |
| `rls_rules.table_paths[].column` | Yes | **A list of bare column names** — `column: ["COUNTRY"]`. **Corrected 2026-07-30:** this reference previously documented it as a *string with the brackets inside the value* (`column: "[COL_NAME]"`). The single live sighting (`BANK_EMPLOYEES`, in a 275-Table census) is a list of bare names, so a generator following the old shape emitted the wrong YAML type. The brackets belong in the **rule `expr`**, not in this value. |
| `rls_rules.rules[].name` | Yes | Rule display name |
| `rls_rules.rules[].expr` | Yes | Bracket refs use the `table_paths` aliases. Live examples: `ts_groups = [BANK_EMPLOYEES_1::COUNTRY]`, `ts_groups != "katrina's group"` |

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
  # ...
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
