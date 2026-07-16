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

**Two deliberate exceptions:**
- **COLLECTION datasources** → one model per underlying table.
- **A genuine cross-datasource blend** (a calculated field that references *another*
  datasource, e.g. `SUM([Sales]) - SUM([Targets].[Target])`) is *meant* to combine the two.
  Realize it as **one model** by co-locating the blend's link keys into a single relation
  (a SQL view spanning the needed tables) and joining the other datasource in — see
  "Join keys must be physical" / "Cross-datasource formulas" in `tableau-formula-translation.md`.
  This is an intentional, key-aligned merge, not the accidental collapse the rule guards against.

**Build only the models the workbook actually uses.** Map models to what the worksheets and
dashboards reference — don't materialize a model for every datasource speculatively. A
datasource with no worksheet of its own (e.g. a targets source that exists only to feed a
blend) folds into the model that uses it rather than becoming a standalone, unused model.

### Formula scoping — each model gets ONLY its own datasource's formulas

When populating `model.formulas[]`, pull calculated fields **only** from the
datasource that corresponds to this model — `parsed.datasources[i].calculated_fields`.
Never search across datasources by formula name.

**Why this matters:** Multiple Tableau datasources can have calculated fields with
the same caption (e.g. "Graph Metric", "Membership Status", "Max Fiscal Year")
but completely different expressions. A Customer Segments datasource might have
`Graph Metric = IF [Segment Metric] = 'Customer Count' THEN COUNTD([CUSTOMER_ID]) ...`
while an Insights Campaign datasource has
`Graph Metric = IF [Insight Graph Metric] = 'Engagement' THEN [Unique Clicks / Delivered] ...`.
Using the wrong body produces a model that references columns that don't exist in
its tables — silent breakage at query time.

**Rules:**

1. **Scope by datasource index** — for each model, iterate only over
   `parsed.datasources[N].calculated_fields` where `N` is the datasource that
   produced this model. Do not search other datasources.
2. **Never use a flat formula-name dict** — if an intermediate structure keys
   formulas by `caption` alone (no datasource qualifier), the last datasource
   processed wins and earlier entries are silently overwritten. Key by
   `(datasource_name, caption)` or process one datasource at a time.
3. **`formula_column_map` (Calculation_ID → caption) is safe to share globally**
   because Tableau Calculation IDs are unique per workbook. But the formula
   **body** (the `formula` / `expr` field) must come from the datasource-specific
   `calculated_fields` list, never from a cross-datasource lookup.
4. **Same-name formulas get independent `formula_` IDs per model** — each model's
   `formula_Graph Metric` contains its own datasource's expression. They don't
   collide because they live in separate TML files.

### model_tables entries

```yaml
model_tables:
- name: TABLE_A          # must match the table TML's `name` field exactly
```

- `obj_id` is **optional** on fresh import — ThoughtSpot resolves tables by `name`. Include
  `obj_id` only when repointing an existing model to a different table (see
  `thoughtspot-model-tml.md` lines 98-99 for the authoritative rule).
- **No `fqn` in `model_tables` entries** — causes import failures.

### Column references use display `name`, not physical `db_column_name`

All model TML references — `model_tables[].name`, `column_id`, join `on` clauses,
and `joins[].with` — use the **display `name`** field from the table/sql_view TML,
never the physical `db_table` or `db_column_name`.

```yaml
# Table TML (fragment — {db}/{schema}/{connection_name} as in the full template)
table:
  name: CHOCOLATE_SALES_2
  db: "{db}"
  schema: "{schema}"
  db_table: CHOCOLATE_SALES_2
  connection:
    name: "{connection_name}"
  columns:
  - name: Sales Person          # ← display name
    db_column_name: SALES_PERSON # ← physical warehouse column

# Model TML — references display name
columns:
- column_id: CHOCOLATE_SALES_2::Sales Person    # ✓ correct — uses `name`
- column_id: CHOCOLATE_SALES_2::SALES_PERSON    # ✗ wrong — uses `db_column_name`
```

When `name` and `db_column_name` happen to be identical (common when tables are
auto-created), the distinction is invisible. It matters when the table was created
with display-friendly names (spaces, mixed case) that differ from the physical
column. Always export the Table TML and use its `name` values — never assume they
match the warehouse schema. See `thoughtspot-model-tml.md` lines 631-640 for the
authoritative rule.

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

**All tables must be connected — no islands.** Every table in `model_tables` must be
reachable from every other table through the join graph. A table with no `joins:` entry
that isn't the target of another table's `with:` is a disconnected island — ThoughtSpot
rejects the model with `Schema validation failed` (error 13122). If a model has three
tables A, B, C where B→C is joined but A is unconnected, add a join from A to B (or C)
to complete the graph. Verified against live instance 2026-07-01.

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
  data_type: CHAR              # CHAR for strings — not VARCHAR (parameters only)
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
| `connection not found` | Wrong `connection.name` or wrong case | Run `ts connections list` and copy the exact name |
| `column not found in connection` | `db_table`/`db_column_name` doesn't match what the connection exposes | Check the warehouse schema for the real names |
| `referencing_join` errors | Used `referencing_join` syntax | Switch to inline `on`/`type`/`cardinality` |
| `Invalid value FULL_OUTER` | Used `FULL_OUTER` join type | Change to `OUTER` |
