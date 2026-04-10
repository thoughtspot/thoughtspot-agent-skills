# Snowflake Semantic View YAML Schema

Full schema reference for `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`. Use during
Step 11 (Validate) to verify the generated YAML is structurally correct.

---

## Complete Schema

```yaml
name: string                      # Required. Valid Snowflake identifier. No spaces.
                                  # Pattern: ^[A-Za-z_][A-Za-z0-9_]*$
description: string               # Optional. Human-facing description.

tables:                           # Required. At least one entry.
- name: string                    # Alias used in expr fields and relationships.
                                  # Must be unique within this semantic view.
  base_table:
    database: string              # Snowflake database name. Uppercase recommended.
    schema: string                # Snowflake schema name. Uppercase recommended.
    table: string                 # Physical table or view name.

relationships:                    # Optional.
- name: string                    # Unique relationship name.
  left_table: string              # Must match a name in tables[].
  right_table: string             # Must match a name in tables[].
  relationship_columns:           # At least one entry.
  - left_column: string           # Physical column name on left_table.
    right_column: string          # Physical column name on right_table.
  relationship_type: string       # many_to_one | one_to_one | one_to_many | many_to_many
  join_type: string               # inner | left | right | full

dimensions:                       # Optional.
- name: string                    # Unique across dimensions, time_dimensions, measures.
  synonyms:                       # Optional. Alternate names for natural language queries.
  - string
  description: string             # Optional. Human-facing or AI-facing description.
  expr: string                    # SQL expression. e.g. table_alias.COLUMN_NAME
  data_type: string               # TEXT | NUMBER | DATE | TIMESTAMP | BOOLEAN
  sample_values:                  # Optional. Representative values for AI context.
  - string

time_dimensions:                  # Optional.
- name: string                    # Unique across dimensions, time_dimensions, measures.
  synonyms:
  - string
  description: string
  expr: string                    # e.g. table_alias.DATE_COLUMN
  data_type: string               # DATE | TIMESTAMP

measures:                         # Optional.
- name: string                    # Unique across dimensions, time_dimensions, measures.
  synonyms:
  - string
  description: string
  expr: string                    # e.g. SUM(table_alias.COLUMN_NAME)
  data_type: string               # NUMBER
  default_aggregation: string     # sum | count | avg | min | max | count_distinct
```

---

## Validation Rules

The following must all pass before calling `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`:

| Rule | Check |
|---|---|
| Unique field names | No two entries across `dimensions`, `time_dimensions`, `measures` share a `name` |
| Valid identifiers | `name` (view + all fields) matches `^[A-Za-z_][A-Za-z0-9_]*$` |
| Table refs in `expr` | Every `table_alias.column` prefix matches a `name` in `tables[]` |
| Table refs in relationships | Every `left_table` and `right_table` matches a `name` in `tables[]` |
| Valid `data_type` | One of: `TEXT`, `NUMBER`, `DATE`, `TIMESTAMP`, `BOOLEAN` |
| Valid `default_aggregation` | One of: `sum`, `count`, `avg`, `min`, `max`, `count_distinct` |
| Valid `relationship_type` | One of: `many_to_one`, `one_to_one`, `one_to_many`, `many_to_many` |
| Valid `join_type` | One of: `inner`, `left`, `right`, `full` |
| No TODO placeholders | No field `expr` contains `-- TODO` unless user has acknowledged |

---

## Execution

```sql
USE ROLE {role};
USE DATABASE {target_database};
USE SCHEMA {target_schema};

SELECT SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML($$
{full yaml content here}
$$);
```

To drop an existing view before recreating:
```sql
DROP SEMANTIC VIEW IF EXISTS {database}.{schema}.{name};
```

To check if a view already exists:
```sql
SELECT COUNT(*) AS existing_count
FROM INFORMATION_SCHEMA.SEMANTIC_VIEWS
WHERE SEMANTIC_VIEW_NAME = UPPER('{name}')
  AND TABLE_SCHEMA = UPPER('{schema}');
```
