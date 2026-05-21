# ThoughtSpot ↔ Databricks Metric View Property Coverage

Full reference for what ThoughtSpot TML properties map to Databricks Metric View
fields, what is partially migrated, and what cannot be migrated at all.

---

## Properties That Map

### TS → Databricks MV

| ThoughtSpot property | Databricks MV field | Notes |
|---|---|---|
| Model / Worksheet `name` | View name in `CREATE VIEW` | Used as-is (spaces allowed in MV names) |
| `model_tables[]` source table | `source:` (v0.1) or `entities[].db_connection` (v1.1) | Fully qualified table name |
| `ATTRIBUTE` column | `dimensions[].name` + `dimensions[].expr` | `expr` is the physical column name or SQL expression |
| `MEASURE` column with `aggregation` | `measures[].name` + `measures[].expr` | Aggregate function embedded in `expr`: `SUM(col)` |
| Formula column (translatable MEASURE) | `measures[].expr` | Translated SQL expression with aggregate |
| Formula column (translatable ATTRIBUTE) | `dimensions[].expr` | Translated SQL expression |

### Databricks MV → TS

| Databricks MV field | ThoughtSpot property | Notes |
|---|---|---|
| `dimensions[].name` | Column `name` (display name) | |
| `dimensions[].expr` (direct column ref) | `column_id` pointing to physical column | `column_type: ATTRIBUTE` |
| `dimensions[].expr` (computed) | `formulas[]` entry | Translated to TS formula syntax |
| `measures[].name` | Column `name` (display name) | |
| `measures[].expr` (simple `AGG(col)`) | Column with `column_type: MEASURE` + `aggregation` | Aggregate extracted from expr |
| `measures[].expr` (complex) | `formulas[]` entry | Translated to TS formula syntax |
| `filter:` | Model `description` | Advisory — noted in description, not enforced |
| `source:` | Table TML `db_table` + `db` + `schema` | Decomposed into catalog/schema/table |
| `version:` | — | Used for parsing path selection, not stored |

---

## Properties That Do NOT Map

### TS properties with no MV equivalent (v0.1)

| ThoughtSpot property | Status | Future path |
|---|---|---|
| `synonyms[]` (column-level) | **Unmapped** | MV has no synonym concept; log in Unmapped Report |
| `properties.synonyms` (property-level) | **Unmapped** | Same as above |
| `column.description` | **Unmapped in v0.1** | v1.1 adds `description:` per dimension/measure |
| `ai_context` | **Unmapped** | No equivalent in MV; include in model `description` if present |
| `properties.calendar_type` | **Unmapped** | No calendar concept in MV |
| `properties.index_type` | **Unmapped** | Databricks handles indexing internally |
| `properties.index_priority` | **Unmapped** | No equivalent |
| `properties.currency_type` | **Unmapped** | No currency formatting in MV |
| `joins[]` / `referencing_join` | **Unmapped in v0.1** | v1.1 supports `entities` with `primary_key`/`foreign_key` |
| `column_type: UNKNOWN` | **Omit** | Cannot classify |
| `properties.geo_config` | **Unmapped** | No geo support in MV |

### MV fields with no TS equivalent

| Databricks MV field | Status | Notes |
|---|---|---|
| `filter:` (global) | **Partial** | Noted in model description; not enforced as a TS filter |
| `version:` | **Metadata only** | Drives parsing logic, not stored in TS |
| `entities[].type` (v1.1) | **Metadata only** | Used during join mapping |

---

## Unmapped Report Format

When generating a conversion report, list unmapped properties in this format:

```
## Unmapped Properties Report

### ThoughtSpot → Databricks MV

| Property | Column/Field | Value | Reason |
|---|---|---|---|
| synonyms | Revenue | ["Total Revenue", "Sales"] | MV does not support synonyms |
| description | Order Date | "Date the order was placed" | MV v0.1 has no description field |
| ai_context | (model-level) | "This model tracks..." | No MV equivalent |

### Formula Translation Log

| Column | ThoughtSpot Formula | Reason |
|---|---|---|
| YoY Growth | `group_aggregate(...)` | LOD function not translatable to MV expr |
| Param Filter | `[Date Parameter]` | Runtime parameter — no MV equivalent |
```

---

## Comparison with Snowflake SV Property Coverage

| Property | Snowflake SV | Databricks MV (v0.1) |
|---|---|---|
| Column name | `name` (snake_cased) | `name` (display name as-is) |
| Synonyms | `synonyms[]` | **Not supported** |
| Description (column) | `description` | **Not supported** |
| Description (model/view) | `description` (top-level) | **Not supported** |
| Aggregation | Embedded in `expr` | Embedded in `expr` |
| Data type | `data_type` on dims/time_dims | Inferred from source table |
| Time dimensions | Separate `time_dimensions[]` | No distinction — all in `dimensions[]` |
| Joins | `relationships[]` | **Not supported** (v0.1) |
| Global filter | Not a concept | `filter:` |
| CA extension | `with extension (CA='...')` | Not applicable |
| Primary key | `primary_key.columns` | **Not supported** (v0.1) |
