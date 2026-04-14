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

  primary_key:                    # Required on tables that appear as right_table
    columns:                      # in any relationship. List of physical column names.
    - string

  dimensions:                     # Optional. Nested under the owning table.
  - name: string                  # Unique across ALL dimensions, time_dimensions,
                                  # metrics in the entire semantic view.
    synonyms:                     # Optional. Alternate names for natural language queries.
    - string
    description: string           # Optional. Human-facing or AI-facing description.
    expr: string                  # SQL expression. e.g. table_alias.COLUMN_NAME
                                  # Quote reserved words: table_alias."date"
    data_type: string             # TEXT | NUMBER | DATE | TIMESTAMP | BOOLEAN

  time_dimensions:                # Optional. Nested under the owning table.
  - name: string                  # Unique across all dimensions, time_dimensions, metrics.
    synonyms:
    - string
    description: string
    expr: string                  # e.g. table_alias.DATE_COLUMN
    data_type: string             # DATE | TIMESTAMP

  metrics:                        # Optional. Nested under the owning table.
                                  # NOTE: The keyword is "metrics", NOT "measures".
  - name: string                  # Unique across all dimensions, time_dimensions, metrics.
    synonyms:
    - string
    description: string
    expr: string                  # e.g. SUM(table_alias.COLUMN_NAME)
                                  # WARNING: Do NOT include data_type on metrics.
                                  # SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML stores it in the
                                  # Cortex Analyst (CA) extension JSON, which Cortex then
                                  # rejects at query time with error 392700 "unknown field
                                  # data_type". Omit data_type from metrics entirely.

relationships:                    # Optional. Defined at the top level (not under tables).
- name: string                    # Unique relationship name.
  left_table: string              # Must match a name in tables[].
  right_table: string             # Must match a name in tables[]. Must have primary_key.
  relationship_columns:           # At least one entry.
  - left_column: string           # Physical column name on left_table.
    right_column: string          # Physical column name on right_table.
```

### What is NOT supported

The following fields are **not** part of the schema. Including them causes a parse error:

| Field | Notes |
|---|---|
| `relationship_type` | Not supported — omit entirely |
| `join_type` | Not supported — omit entirely |
| `default_aggregation` | Not supported in `metrics` — omit entirely |
| `sample_values` | Not supported in `dimensions` — omit entirely |

---

## Key Structural Rules

1. **Table-scoped fields:** `dimensions`, `time_dimensions`, and `metrics` are nested
   **under each `tables[]` entry**, not at the top level of the semantic view.

2. **`metrics` not `measures`:** The correct keyword is `metrics`. Using `measures`
   causes a parse error.

3. **`primary_key` is required** on every table that appears as `right_table` in a
   `relationships[]` entry. Missing `primary_key` causes validation failure.

4. **Reserved words in column names** must be double-quoted in `expr`:
   ```yaml
   expr: DM_DATE_DIM."date"
   ```
   In YAML, the `expr` value string should be: `DM_DATE_DIM."date"`

5. **`relationships[]` is top-level**, not nested under tables.

6. **`name` uniqueness** applies globally: no two entries across all
   `dimensions`, `time_dimensions`, and `metrics` in the entire semantic view
   may share a `name`.

---

## Reserved Keywords and Case-Sensitive Identifiers

### SQL reserved words in `expr`

Column names that are SQL reserved words must be double-quoted in `expr`:
```yaml
expr: table_alias."date"
```

Common reserved words: `date`, `time`, `schema`, `table`, `value`, `name`, `type`, `key`, `id`, `order`, `group`

### Case-sensitive (lowercase) identifiers

When a Snowflake schema, table, or column was created with double-quoted lowercase
identifiers (e.g. `CREATE SCHEMA "superhero"`), it is case-sensitive and must be
referenced with double quotes. In `SHOW SCHEMAS` / `SHOW TABLES` / `SHOW COLUMNS`,
case-sensitive objects appear in lowercase; case-insensitive objects appear in UPPERCASE.

**Rule:** If `SHOW` output returns a name in lowercase → it requires quoting.

**YAML encoding for Snowflake-quoted identifiers:**

In the Semantic View YAML, Snowflake-quoted identifiers must be wrapped in single
quotes containing the double-quoted value — but **only in `base_table` fields and
`expr` SQL expressions**. See the critical exception for `primary_key` and
`relationship_columns` below.

```yaml
# Schema (case-sensitive lowercase)
base_table:
  schema: '"superhero"'    # ← single-quoted YAML string containing "superhero"
  table: '"colour"'        # ← same pattern for table names

# expr fields — embed quotes directly in the SQL expression string
expr: eye_colour."colour"  # ← table alias unquoted, column double-quoted inline
```

**Detection:** Before generating YAML, run `SHOW SCHEMAS`, `SHOW TABLES`, and
`SHOW COLUMNS` to identify which identifiers are lowercase/case-sensitive, then
apply quoting accordingly.

| Location | Case-insensitive (UPPERCASE) | Case-sensitive (lowercase) |
|---|---|---|
| `base_table.schema` | `schema: PUBLIC` | `schema: '"superhero"'` |
| `base_table.table` | `table: FACT_SALES` | `table: '"colour"'` |
| `expr` column ref | `expr: t.COLUMN_NAME` | `expr: t."column_name"` |
| `primary_key.columns` | `- COLUMN_NAME` | `- column_name` (bare — wrapper views normalize to uppercase) |
| `relationship_columns` | `left_column: COL` | `left_column: col` (bare — wrapper views normalize to uppercase) |

**`primary_key.columns` and `relationship_columns`** always use bare unquoted identifiers.
Lowercase case-sensitive join key columns trigger wrapper view creation in Step 5, which
normalizes all column names to uppercase before the YAML is generated. See
*Known Snowflake Semantic View Limitations — Lowercase case-sensitive base table columns*
at the bottom of this file.

---

## Validation Checklist

Run all checks before calling `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`:

| Rule | Check |
|---|---|
| Unique field names | No two entries across all `dimensions`, `time_dimensions`, `metrics` share a `name` |
| Valid identifiers | `name` (view + all fields) matches `^[A-Za-z_][A-Za-z0-9_]*$` |
| Table-scoped fields | `dimensions`, `time_dimensions`, `metrics` are nested under `tables[]` entries, NOT top-level |
| Keyword: `metrics` | No `measures` key anywhere in the YAML |
| Table refs in `expr` | Every `table_alias.column` prefix matches a `name` in `tables[]` |
| Table refs in relationships | Every `left_table` and `right_table` matches a `name` in `tables[]` |
| `primary_key` present | Every `right_table` in a relationship has `primary_key.columns` defined |
| `primary_key` format | `primary_key:` with nested `columns:` list — NOT a bare list under `primary_key:` |
| Case-sensitive identifiers | Lowercase schemas/tables detected via SHOW and wrapped in `'"value"'` in `base_table`; lowercase columns double-quoted inline in `expr` |
| Reserved words quoted | Column names that are SQL reserved words are double-quoted in `expr` |
| Join key identifiers | `primary_key.columns` and `relationship_columns` use bare identifiers — wrapper views (Step 5) ensure all are uppercase before this point |
| Unsupported fields absent | No `relationship_type`, `join_type`, `default_aggregation`, `sample_values` |
| Valid `data_type` | Dimensions/time_dimensions only: one of `TEXT`, `NUMBER`, `DATE`, `TIMESTAMP`, `BOOLEAN`. **Never on metrics** — causes Cortex error 392700. |
| No untranslatable formulas | Columns with untranslatable ThoughtSpot formulas are **omitted** entirely |

---

## Example Structure

```yaml
name: retail_sales
description: "Migrated from ThoughtSpot: Retail Sales"

tables:
- name: fact_sales
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: FACT_SALES
  metrics:
  - name: revenue
    synonyms:
    - "Revenue"
    - "Sales"
    description: "[TS AI Context] Total transaction value for financial analysis."
    expr: SUM(fact_sales.SALES_AMOUNT)
  time_dimensions:
  - name: sale_date
    synonyms:
    - "Sale Date"
    description: ""
    expr: fact_sales.SALE_DATE
    data_type: DATE

- name: dim_product
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: DIM_PRODUCT
  primary_key:
    columns:
    - PRODUCT_ID
  dimensions:
  - name: product
    synonyms:
    - "Product"
    - "Item"
    description: ""
    expr: dim_product.PRODUCT_NAME
    data_type: TEXT
  metrics:
  - name: product_count
    synonyms:
    - "Product Count"
    - "# of Products"
    description: ""
    expr: COUNT(dim_product.PRODUCT_ID)

relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

---

## Execution

```sql
USE ROLE {role};
USE DATABASE {target_database};
USE SCHEMA {target_schema};

-- Dry-run validation (recommended first):
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{full yaml content here}
$$, TRUE);

-- Create (remove TRUE flag):
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{full yaml content here}
$$);
```

**Notes:**
- `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` is a **stored procedure** — use `CALL`, not `SELECT`.
- First argument is the fully-qualified target schema: `'DATABASE.SCHEMA'`
- Third argument `TRUE` enables dry-run validation without creating the view
- The `$$` dollar-quoting allows the YAML to contain single quotes safely

To drop an existing view before recreating:
```sql
DROP SEMANTIC VIEW IF EXISTS {database}.{schema}.{name};
```

Do NOT use `INFORMATION_SCHEMA.SEMANTIC_VIEWS` — the column names vary by Snowflake
version. Instead, proceed with the CREATE call and handle the "already exists"
error if returned.

---

## Known Snowflake Semantic View Limitations

### Lowercase case-sensitive base table columns (Cortex Analyst blocker)

Cortex Analyst validates the semantic model YAML against a strict identifier pattern:
`^[A-Za-z_][A-Za-z0-9_$]*$`. Any column name containing `"` characters is rejected
with error 392700:

```
invalid column name "id": name must start with an underscore or a letter,
and only contain letters, underscores, decimal digits (0-9), and dollar signs ($).
```

This surfaces when the underlying Snowflake tables were created with lowercase quoted
identifiers (e.g. `"id"`, `"race_id"`). `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`
requires `'"id"'` quoting to resolve these columns; Cortex Analyst then rejects that
same encoding at query time. There is no YAML format that satisfies both tools.

**Diagnosis:** Run `SHOW COLUMNS IN TABLE {db}.{schema}.{table}`. If any column name
is returned in lowercase, those columns are case-sensitive and will trigger this issue.

**Fix — create uppercase wrapper views (preferred):**

Before generating the YAML in Step 10, create a new uppercase schema and views:

```sql
CREATE SCHEMA IF NOT EXISTS {db}.{UPPERCASE_SCHEMA_NAME};

CREATE OR REPLACE VIEW {db}.{UPPERCASE_SCHEMA_NAME}.{TABLE_NAME} AS
SELECT "id" AS ID, "column_name" AS COLUMN_NAME, ...
FROM {db}."{lowercase_schema}"."{table}";
```

Point the semantic view's `base_table` entries at the new schema and views. All
identifiers become bare uppercase — no quoting needed anywhere in the YAML, and
both `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` and Cortex Analyst accept the result.

**Alternative fix — rename source columns:**

```sql
ALTER TABLE {db}."{schema}"."{table}" RENAME COLUMN "id" TO ID;
```

This is cleaner long-term but modifies the source schema and may break other
queries or integrations that reference the lowercase column names. Use only if you
control the source tables and have verified no downstream dependencies.

---

### Bridge / junction tables and multi-hop traversal

Snowflake Semantic Views cannot traverse a two-hop path through a bridge table at
query time. If the model contains a many-to-many pattern like:

```
superhero ← hero_power → superpower
```

Queries that request dimensions from both ends (e.g. `superhero_name` + `power_name`)
fail with:

```
Invalid fact specified: The fact entity 'SUPERPOWER' must be related to and have
an equal or lower level of granularity compared to the base metric or fact entity.
```

**What still works:** Queries anchored at one end of the bridge:
- `superhero_name` + any lookup dimension (race, alignment, gender, publisher, colour)
- `superhero_name` + `attribute_name` + `attribute_value` (via `hero_attribute`)

**What doesn't work:** Any query that tries to reach a table on the far side of a
bridge via the bridge table (e.g. `superhero_name` + `power_name`).

**Workaround:** Use direct SQL against the physical tables with explicit JOINs and
properly quoted case-sensitive identifiers (see case-sensitivity rules in Step 5).

### Symmetric join keys (same column name on both FK and PK sides)

Cortex Analyst requires every join key column to be exposed as a **named dimension**,
and resolves join keys **by dimension name** (snake_case of the physical column name).
Dimension names must be globally unique across the entire semantic view.

When FK and PK columns share the same name (e.g. `TRANS.ACCOUNT_ID → ACCOUNT.ACCOUNT_ID`),
you cannot expose both as `account_id` — Snowflake enforces global uniqueness.

**Error:** `Join relationship X using join key 'account_id' which is not defined in
logical table trans.` (error 392700)

**Fix — rename FK columns in wrapper views before generating YAML:**

In the wrapper view for each fact/bridge table, rename every FK column to include the
source table prefix:

```sql
-- Before: "account_id" AS ACCOUNT_ID
-- After:
CREATE OR REPLACE VIEW TRANS AS
SELECT "trans_id" AS TRANS_ID,
       "account_id" AS TRANS_ACCOUNT_ID,   -- renamed FK
       ...
FROM source_schema.trans;
```

Then expose each renamed column as a dimension and update relationships:

```yaml
# TRANS table — dimension for the FK
- name: trans_account_id
  expr: trans.TRANS_ACCOUNT_ID
  data_type: NUMBER

# Relationship uses the renamed column
relationships:
- name: trans_to_account
  left_table: trans
  right_table: account
  relationship_columns:
  - left_column: TRANS_ACCOUNT_ID   # renamed FK in wrapper view
    right_column: ACCOUNT_ID        # PK stays unchanged
```

When a physical table is aliased multiple times (e.g. `DISTRICT` used as both
`client_district` and `account_district`), create **two separate wrapper views** with
distinct PK column names (`CLIENT_DISTRICT_ID` and `ACCOUNT_DISTRICT_ID`) so each alias
can satisfy Cortex's unique-name requirement independently.

**Note:** This also applies to `primary_key` columns — the PK column must also be
exposed as a dimension with a name matching snake_case(pk_column). For example, if
the PK column is `DISP_ID`, the dimension must be named `disp_id`.

---

### `SELECT *` on a multi-fact semantic view

`SELECT *` across a semantic view that contains multiple fact/bridge tables at
different granularities will always fail with the granularity conflict above.
Always select specific fields from a single granularity path.
