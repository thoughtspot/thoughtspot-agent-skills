---
name: ts-convert-to-databricks-mv
description: Convert a ThoughtSpot Worksheet or Model into a Databricks Metric View. Genie Code runtime — uses ThoughtSpotClient via %run instead of ts CLI.
---

# ThoughtSpot → Databricks Metric View (Genie Code)

Convert a ThoughtSpot Worksheet or Model into a Databricks Metric View.

This is the Genie Code version of the CLI skill at `agents/cli/ts-convert-to-databricks-mv/`.
The conversion logic is identical — only the I/O layer differs.

---

## Setup

```python
%run ../notebooks/ts_client
client = ThoughtSpotClient("my-profile")
```

---

## References

Same shared references as the CLI version — deployed to the workspace by the Asset Bundle:

| File | Purpose |
|---|---|
| shared/mappings/ts-databricks/ts-to-databricks-rules.md | Column classification, aggregation, data type rules |
| shared/mappings/ts-databricks/ts-databricks-formula-translation.md | Formula translation rules |
| shared/mappings/ts-databricks/ts-databricks-properties.md | Property coverage matrix |
| shared/schemas/databricks-metric-view.md | Metric View DDL syntax and YAML schema |
| shared/schemas/thoughtspot-table-tml.md | Table TML field reference |
| shared/schemas/thoughtspot-model-tml.md | Model TML field reference |

---

## Steps

### Step 1: Search for the ThoughtSpot object

```python
models = client.metadata_search(type="LOGICAL_TABLE", name="%revenue%")
```

### Step 2: Export TML

```python
tml = client.tml_export(["<guid>"], fqn=True, associated=True, parse=True)
```

### Step 3: Map to Metric View

Follow the mapping rules in the shared references. The conversion logic is
identical to the CLI skill — classify columns, map data types, translate
formulas, generate the CREATE VIEW WITH METRICS DDL.

### Step 4: Execute in Databricks

```python
spark.sql(ddl_statement)
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-15 | Initial release — Genie Code runtime |
