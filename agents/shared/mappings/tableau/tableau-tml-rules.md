# Tableau → ThoughtSpot TML Generation Rules

Critical invariants for producing valid ThoughtSpot TML from a Tableau TWB. Every rule here has been verified against a live ThoughtSpot import.

---

## Table TML Rules

### Required fields on every column

```yaml
- name: COLUMN_NAME
  db_column_name: COLUMN_NAME
  data_type: VARCHAR          # see data type table below
  properties:
    column_type: ATTRIBUTE    # or MEASURE
  db_column_properties:
    data_type: VARCHAR        # MUST match data_type above — omitting causes import failure
```

**Omitting `db_column_properties` causes:** `Compulsory Field table->columns->db_column_properties is not populated`

### MEASURE columns must include `aggregation`

```yaml
- name: SALES
  db_column_name: SALES
  data_type: DOUBLE
  properties:
    column_type: MEASURE
    aggregation: SUM          # SUM | AVERAGE | COUNT | MIN | MAX | COUNT_DISTINCT
  db_column_properties:
    data_type: DOUBLE
```

### Forbidden fields

- **No `guid`, `fqn`, or `connection` sections** — ThoughtSpot assigns these on import.

### Placeholder db/schema

When the connection is not yet known, use placeholders — they produce a warning, not an error:

```yaml
table:
  name: ORDERS
  db: YOUR_DATABASE
  schema: YOUR_SCHEMA
  db_table: ORDERS
```

---

## Model TML Rules

### One model per Tableau datasource — strict separation

Each Tableau `<datasource>` element produces exactly one model TML. **Never collapse
multiple datasources into a single model**, even when they share tables or point at the
same database. Each datasource has its own join topology, calculated fields, and column
aliases — merging them produces wrong joins and broken formula references.

Exception: COLLECTION datasources get one model per underlying table.

### model_tables entries

```yaml
model_tables:
- name: TABLE_A          # must match the table TML's `name` field exactly
```

- `obj_id` is **optional** on fresh import — ThoughtSpot resolves tables by `name`. Include
  `obj_id` only when repointing an existing model to a different table (see
  `thoughtspot-model-tml.md` lines 98-99 for the authoritative rule).
- **No `fqn` in `model_tables` entries** — causes import failures.

### Joins — inline syntax only

```yaml
model_tables:
- name: TABLE_A
  obj_id: TABLE_A
  joins:
  - with: TABLE_B
    on: "[TABLE_A::JOIN_COL] = [TABLE_B::JOIN_COL]"
    type: LEFT_OUTER      # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER (not FULL_OUTER)
    cardinality: ONE_TO_MANY
- name: TABLE_B
  obj_id: TABLE_B
```

**Never use `referencing_join`** — it references named join objects that don't exist on fresh import.

**Every join MUST have a non-empty `on` field.** ThoughtSpot rejects any join where `on` is absent or empty.

**`FULL_OUTER` is invalid** — use `OUTER` instead.

### Formula ordering — dependency order required

Write formulas in dependency order: Level 0 (no formula references) first, then formulas that depend on Level 0, etc.

```yaml
formulas:
- id: formula_Base Metric      # Level 0 — references only physical columns
  name: Base Metric
  expr: "[TABLE_A::sales_amount] * [TABLE_A::quantity]"
- id: formula_Adjusted Metric  # Level 1 — references formula_Base Metric
  name: Adjusted Metric
  expr: "[formula_Base Metric] * 1.1"
```

### Formula ID convention

`id: formula_<display_name>` — spaces allowed in formula IDs.

### Column references in formulas

- Physical columns: `[table_name::column_name]`
- Other formulas: `[formula_<display_name>]` (by their `id`)
- Parameters: `[Parameter Name]` (no table prefix, no `::` separator)

### Parameter migration (Tableau `Parameters` datasource → `model.parameters[]`)

Tableau parameters from the `Parameters` datasource are created as ThoughtSpot model
parameters. Omit `id` on first import — ThoughtSpot assigns it.

```yaml
parameters:
- name: Currency
  data_type: VARCHAR
  default_value: "USD"
  list_config:
    list_choice:
    - value: USD
    - value: CAD
    - value: GBP
```

**Formula references:** Tableau `[Parameters].[Currency]` → ThoughtSpot `[Currency]`.

See `tableau-formula-translation.md` "Parameter References" for the full type mapping
and value cleanup rules (quote stripping, date format conversion).

### Formula fallback — omit and log untranslatable formulas

When a Tableau calculated field cannot be translated to a native ThoughtSpot function
or a pass-through fallback (LOOKUP, INDEX, SIZE, PREVIOUS_VALUE, or any pattern listed
in `tableau-formula-translation.md` "Untranslatable Patterns"):

1. **Omit the formula** from the model TML `formulas[]` section entirely
2. **Omit the corresponding `columns[]` entry** that would reference the formula via `formula_id`
3. **Log the omission** — add a row to the `MIGRATION_LIMITATIONS.md` report with the
   formula name, datasource, reason, and Tableau expression excerpt

Never generate a placeholder or stub formula — a formula with incorrect syntax causes
the entire model import to fail. A missing formula produces a functional model with
reduced coverage, which the user can then address manually.

---

## SQL View TML Rules (Custom SQL Datasources)

When a Tableau `<relation>` has `type="custom-sql"`, the SQL text is the datasource's
query — it does NOT map to a physical table. Generate a `sql_view:` TML instead of a
`table:` TML.

### When to generate a SQL View

- The `<relation>` element has `type="text"` (custom SQL indicator in TWB XML)
- The element contains a raw SQL query in its text content

### Required structure

```yaml
sql_view:
  name: "Datasource Custom SQL"
  connection:
    name: "Connection Display Name"      # exact name from ts connections list — case-sensitive
  sql_query: |
    SELECT col1, col2, col3
    FROM catalog.schema.table_name
    WHERE condition = 'value'
  sql_view_columns:
  - name: COL1
    sql_output_column: col1              # must match a column/alias in the SQL output
    data_type: VARCHAR
    properties:
      column_type: ATTRIBUTE
  - name: COL2
    sql_output_column: col2
    data_type: DOUBLE
    properties:
      column_type: MEASURE
      aggregation: SUM
```

### Key differences from table TML

- **No `db`, `schema`, or `db_table`** — the SQL query defines the data source
- **`connection.name` is required** — SQL Views must reference a named connection
- **`sql_output_column`** replaces `db_column_name` — must match a column/alias in the SQL
- **`db_column_properties` is NOT used** — `data_type` goes at the column level
- **File extension**: `*.sql_view.tml` (not `*.table.tml`)

See `thoughtspot-sql-view-tml.md` for the full schema reference.

### Model references to SQL Views

A SQL View is referenced in `model_tables[]` by name, just like a regular table:

```yaml
model_tables:
- name: "Datasource Custom SQL"
```

Column references use the same `[sql_view_name::column]` syntax.

### Formula fallback — omit and log untranslatable formulas

When a Tableau calculated field cannot be translated to a native ThoughtSpot function
or a pass-through fallback (LOOKUP, INDEX, SIZE, PREVIOUS_VALUE, or any pattern listed
in `tableau-formula-translation.md` "Untranslatable Patterns"):

1. **Omit the formula** from the model TML `formulas[]` section entirely
2. **Omit the corresponding `columns[]` entry** that would reference the formula via `formula_id`
3. **Log the omission** — add a row to the `MIGRATION_LIMITATIONS.md` report with the
   formula name, datasource, reason, and Tableau expression excerpt

Never generate a placeholder or stub formula — a formula with incorrect syntax causes
the entire model import to fail. A missing formula produces a functional model with
reduced coverage, which the user can then address manually.

---

## SQL View TML Rules (Custom SQL Datasources)

When a Tableau `<relation>` has `type="custom-sql"`, the SQL text is the datasource's
query — it does NOT map to a physical table. Generate a `sql_view:` TML instead of a
`table:` TML.

### When to generate a SQL View

- The `<relation>` element has `type="text"` (custom SQL indicator in TWB XML)
- The element contains a raw SQL query in its text content

### Required structure

```yaml
sql_view:
  name: "Datasource Custom SQL"
  connection:
    name: "Connection Display Name"      # exact name from ts connections list — case-sensitive
  sql_query: |
    SELECT col1, col2, col3
    FROM catalog.schema.table_name
    WHERE condition = 'value'
  sql_view_columns:
  - name: COL1
    sql_output_column: col1              # must match a column/alias in the SQL output
    data_type: VARCHAR
    properties:
      column_type: ATTRIBUTE
  - name: COL2
    sql_output_column: col2
    data_type: DOUBLE
    properties:
      column_type: MEASURE
      aggregation: SUM
```

### Key differences from table TML

- **No `db`, `schema`, or `db_table`** — the SQL query defines the data source
- **`connection.name` is required** — SQL Views must reference a named connection
- **`sql_output_column`** replaces `db_column_name` — must match a column/alias in the SQL
- **`db_column_properties` is NOT used** — `data_type` goes at the column level
- **File extension**: `*.sql_view.tml` (not `*.table.tml`)

See `thoughtspot-sql-view-tml.md` for the full schema reference.

### Model references to SQL Views

A SQL View is referenced in `model_tables[]` by name, just like a regular table:

```yaml
model_tables:
- name: "Datasource Custom SQL"
```

Column references use the same `[sql_view_name::column]` syntax.

---

## Join Type Mapping (Tableau → ThoughtSpot)

| Tableau join type | ThoughtSpot `type` |
|---|---|
| `inner` | `INNER` |
| `left` | `LEFT_OUTER` |
| `right` | `RIGHT_OUTER` |
| `full` | `OUTER` — **not `FULL_OUTER`** |

---

## Validation Error Quick Reference

| Error Message | Cause | Fix |
|---|---|---|
| `Data type INT is not valid for column` | Used `INT` instead of `INT64` | Change to `data_type: INT64` |
| `Compulsory Field table->columns->db_column_properties is not populated` | Missing `db_column_properties` | Add `db_column_properties: { data_type: <type> }` to every column |
| `Tables do not exist` | Table TMLs failed to import | Fix table TML errors first |
| `Table with id null not found` | Placeholder db/schema | Expected warning — not a blocker |
| `referencing_join` errors | Used `referencing_join` syntax | Switch to inline `on`/`type`/`cardinality` |
| `Invalid value FULL_OUTER` | Used `FULL_OUTER` join type | Change to `OUTER` |
