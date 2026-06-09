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

### One model per Tableau datasource

Exception: COLLECTION datasources get one model per underlying table.

### model_tables entries

```yaml
model_tables:
- name: TABLE_A          # must match the table TML's `name` field exactly
  obj_id: TABLE_A        # MUST be present and match `name`
```

- **No `fqn` in `model_tables` entries** — causes import failures.
- `obj_id` must match the table's own `obj_id`.

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
