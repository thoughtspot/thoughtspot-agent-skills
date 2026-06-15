---
name: ts-convert-from-databricks-mv
description: Convert a Databricks Metric View into ThoughtSpot Table and Model TML. Genie Code runtime — uses ThoughtSpotClient via %run instead of ts CLI.
---

# Databricks Metric View → ThoughtSpot (Genie Code)

Convert a Databricks Metric View into ThoughtSpot Table and Model TML.

This is the Genie Code version of the CLI skill at `agents/cli/ts-convert-from-databricks-mv/`.
The conversion logic is identical — only the I/O layer differs.

---

## Setup

```python
%run ../notebooks/ts_client
client = ThoughtSpotClient("my-profile")
```

---

## References

Same shared references as the CLI version:

| File | Purpose |
|---|---|
| shared/mappings/ts-databricks/ts-from-databricks-rules.md | Column classification and type mapping rules |
| shared/mappings/ts-databricks/ts-databricks-formula-translation.md | Formula translation rules |
| shared/schemas/thoughtspot-table-tml.md | Table TML field reference |
| shared/schemas/thoughtspot-model-tml.md | Model TML field reference |

---

## Steps

### Step 1: Read the Metric View definition

```python
mv_def = spark.sql("DESCRIBE EXTENDED catalog.schema.my_metric_view")
```

### Step 2: Map to ThoughtSpot TML

Follow the mapping rules in the shared references. The conversion logic is
identical to the CLI skill — parse the MV YAML, classify columns, map data
types, generate Table and Model TML.

### Step 3: Import TML to ThoughtSpot

```python
result = client.tml_import([table_tml, model_tml], policy="ALL_OR_NONE", create_new=True)
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-15 | Initial release — Genie Code runtime |
