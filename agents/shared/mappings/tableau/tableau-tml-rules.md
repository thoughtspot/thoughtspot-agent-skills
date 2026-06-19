<!-- currency: tableau — 2026-06 (inaugural anchor; verify in first external sweep) -->

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

### Required `connection` section

- **`connection.name` is required** — a ThoughtSpot logical table sits on a connection that
  already exposes the physical table and its columns. Use the exact ThoughtSpot connection
  **name** (case-sensitive), never a GUID; the v2 API cannot search connections by name, so
  the name string is both necessary and sufficient.

```yaml
table:
  name: ORDERS
  db: AGENT_SKILLS
  schema: SALES
  db_table: ORDERS
  connection:
    name: "APJ_TAB"        # exact connection name as it appears in ts connections list
```

If import returns `connection not found`, the name/case is wrong; if it returns
`column not found in connection`, the connection doesn't expose the `db_table`/column
named — both fail loudly at validation rather than silently producing an empty table.

### Forbidden fields

- **No `guid` or `fqn` sections on a *fresh* import** — ThoughtSpot assigns the `guid` on first
  import (use `--create-new`). (For a *re-import in place*, you DO pin `guid` — see below.)
- **No placeholder `db`/`schema`** (e.g. `YOUR_DATABASE`) — a ThoughtSpot table is a logical
  object over a live connection. The physical table must exist in the database and the
  connection must exist, or the table cannot be created. Always emit the real `db`, `schema`,
  `db_table`, and `connection.name`; if they aren't known, stop rather than emit a stub.

### Updating an existing object in place (re-import)

To update an object you already imported (a styling/formula/coverage pass) instead of forking a
duplicate, pin its identity and import with **`--no-create-new`**. **The `guid` and `obj_id` must
be TOP-LEVEL keys of the TML document — siblings of `table:`/`model:`/`liveboard:`, never nested
inside that object:**

```json
{ "guid": "<existing>", "obj_id": "<existing>", "liveboard": { "name": ..., "visualizations": ... } }
```

- Nesting them *inside* the object (e.g. `liveboard.guid`) means the import never matches the
  existing object and **silently forks a new guid — every time, regardless of `--policy`**.
  (Tables/models often "just work" because their `guid` is naturally written at the top level;
  liveboards forked repeatedly until the guid was moved out of the `liveboard` block.)
- `--create-new` with a TML that already has a `guid` also forks a duplicate — use it only for
  brand-new objects.
- Read the existing `obj_id` from a search (`metadata_obj_id`) or a prior export. **After import,
  verify the returned `id_guid` is unchanged** — a new guid means you forked; delete the stale copy.

---

## Model TML Rules

### One model per Tableau datasource — strict separation

Each Tableau `<datasource>` element produces exactly one model TML. **Never *blindly*
collapse multiple datasources into a single model** just because they share tables or point
at the same database — each has its own join topology, calculated fields, and column aliases,
and merging them indiscriminately produces wrong joins and broken formula references.

**Three deliberate exceptions:**
- **COLLECTION datasources** → one model per underlying table.
- **Blend-connected datasources** → datasources linked by `<datasource-relationships>` in the
  workbook XML produce a single merged model. The primary datasource's tables and columns
  form the base; secondary datasources' tables join in via `LEFT_OUTER` inline joins derived
  from the blend's `<column-mapping>` link fields. **Join placement:** the join is declared on
  the **secondary** table's `model_tables[]` entry, with `with:` pointing to the primary.
  This is the standard blend-to-model mapping; see SKILL.md Step 3e (extraction) and Step 5b
  (model generation).
  - A datasource with no worksheet of its own (e.g. a targets source that exists only to feed
    a blend) folds into the model that uses it rather than becoming a standalone, unused model.
- **A cross-datasource formula** that references another datasource resolves within the
  merged model — no separate SQL view is needed when both datasources are already in the
  same model via blending.

**Build only the models the workbook actually uses.** Map models to what the worksheets and
dashboards reference — don't materialize a model for every datasource speculatively.

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
  expr: "[Base Metric] * 1.1"
```

### Formula cross-references during import — inline the expression

**Formula-to-formula bracket references (`[Other Formula Name]`) fail during TML
import** with "Search did not find 'other formula name'". ThoughtSpot resolves formula
references by display name at import time, but the referenced formula may not yet exist
in the object when the referencing formula is being validated.

**Workaround:** inline the referenced formula's expression directly into the referencing
formula. For example, if formula B references formula A:

```yaml
# WRONG — fails with "Search did not find 'Total Sales'"
- id: formula_Total Sales
  name: Total Sales
  expr: "group_aggregate ( sum ( [TABLE::AMOUNT] ) , { [TABLE::REGION] } , {} )"
- id: formula_Above Threshold
  name: Above Threshold
  expr: "if ( [Total Sales] >= [Min Amount] ) then true else false"

# CORRECT — inline the group_aggregate expression
- id: formula_Total Sales
  name: Total Sales
  expr: "group_aggregate ( sum ( [TABLE::AMOUNT] ) , { [TABLE::REGION] } , {} )"
- id: formula_Above Threshold
  name: Above Threshold
  expr: >-
    if ( group_aggregate ( sum ( [TABLE::AMOUNT] ) , { [TABLE::REGION] } , {} ) >= [Min Amount] ) then true else false
```

**Alternative:** import base formulas first, export the model to get GUIDs assigned,
then add dependent formulas via a second import with the exported JSON format. This is
slower but avoids expression duplication.

### Formula ID convention

`id: formula_<display_name>` — spaces allowed in formula IDs.

### Column references in formulas

- Physical columns: `[table_name::column_name]`
- Formula columns (post-import): `[Formula Display Name]` (by display name, no table prefix)
- Parameters: `[Parameter Name]` (no table prefix, no `::` separator)

### Parameter migration (Tableau `Parameters` datasource → `model.parameters[]`)

Tableau parameters from the `Parameters` datasource are created as ThoughtSpot model
parameters. Omit `id` on first import — ThoughtSpot assigns it.

**`data_type` for list parameters must be `CHAR`** — `VARCHAR` is listed in the schema
but fails on import for list parameters. Use `CHAR` for all string-typed list parameters.
(`INT64`, `DOUBLE`, `DATE`, `BOOL` are valid for non-string types.)

**`list_choice` entries require `value:` and `display_name:` sub-keys** — bare string
values are rejected. Every entry must be an object with at least `value:`.

```yaml
parameters:
- name: Currency
  data_type: CHAR
  default_value: "USD"
  list_config:
    list_choice:
    - value: USD
      display_name: USD
    - value: CAD
      display_name: CAD
    - value: GBP
      display_name: GBP

- name: Threshold
  data_type: DOUBLE
  default_value: "500"
  range_config:
    range_min: "0"
    range_max: "10000"
    include_min: true
    include_max: true
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

---

## Date Column Rules — full date required

Any column intended as a DATE in ThoughtSpot must resolve to a full `YYYY-MM-DD` date,
never a bare year or partial string. ThoughtSpot requires a complete date for:

- **Date bucketing** — `.yearly`, `.monthly`, `.quarterly` in search queries
- **KPI sparklines** — period-over-period comparison needs actual date arithmetic
- **Filters** — date-range filters expect a real date type

### The rule

When converting a string that represents a year (e.g. `_2016_17`, `FY2016`, `2016`) to
a date column, always produce a full date by appending a month and day:

```sql
-- Correct: full date — ThoughtSpot can bucket, compare, and sparkline
TO_DATE(SUBSTRING(YEAR_PERIOD, 2, 4) || '-01-01', 'YYYY-MM-DD')

-- Wrong: bare year — renders as a number, not a date; sparklines fail
TO_DATE(SUBSTRING(YEAR_PERIOD, 2, 4), 'YYYY')
```

The same applies in ThoughtSpot formulas:

```
// Correct
to_date ( concat ( substr ( [YEAR_PERIOD] , 1 , 4 ) , '-01-01' ) , 'yyyy-MM-dd' )

// Wrong — produces an ambiguous value ThoughtSpot can't reliably bucket
to_date ( substr ( [YEAR_PERIOD] , 1 , 4 ) , 'yyyy' )
```

### Where to apply the conversion

**If the datasource already uses a SQL View** (custom SQL or UNPIVOT), apply the
conversion in the SQL query itself — this produces a native DATE column at the source.
The model then references it directly via `column_id` instead of needing a formula.

**If the datasource uses a regular table**, apply the conversion as a model formula —
a formula like `to_date ( concat ( substr ( [col] , 1 , 4 ) , '-01-01' ) , 'yyyy-MM-dd' )` works correctly
and keeps the date logic visible in the model. Either approach is fine as long as the
result is a full `YYYY-MM-DD` date.

### Common patterns

| Source pattern | SQL (in SQL View) | ThoughtSpot formula (in model) | Result |
|---|---|---|---|
| `_2016_17` (UNPIVOT) | `TO_DATE(SUBSTRING(col, 2, 4) \|\| '-01-01', 'YYYY-MM-DD')` | `to_date ( concat ( substr ( [col] , 1 , 4 ) , '-01-01' ) , 'yyyy-MM-dd' )` | `2016-01-01` |
| `FY2016` | `TO_DATE(SUBSTRING(col, 3, 4) \|\| '-01-01', 'YYYY-MM-DD')` | `to_date ( concat ( substr ( [col] , 2 , 4 ) , '-01-01' ) , 'yyyy-MM-dd' )` | `2016-01-01` |
| `2016` (bare year) | `TO_DATE(col \|\| '-01-01', 'YYYY-MM-DD')` | `to_date ( concat ( [col] , '-01-01' ) , 'yyyy-MM-dd' )` | `2016-01-01` |
| `2016-03` (year-month) | `TO_DATE(col \|\| '-01', 'YYYY-MM-DD')` | `to_date ( concat ( [col] , '-01' ) , 'yyyy-MM-dd' )` | `2016-03-01` |

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
| `connection not found` | Wrong `connection.name` or wrong case | Run `ts connections list` and copy the exact name |
| `column not found in connection` | `db_table`/`db_column_name` doesn't match what the connection exposes | Check the warehouse schema for the real names |
| `referencing_join` errors | Used `referencing_join` syntax | Switch to inline `on`/`type`/`cardinality` |
| `Invalid value FULL_OUTER` | Used `FULL_OUTER` join type | Change to `OUTER` |
