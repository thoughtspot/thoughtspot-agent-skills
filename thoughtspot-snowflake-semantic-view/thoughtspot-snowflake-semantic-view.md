---
name: thoughtspot-snowflake-semantic-view
description: Convert a ThoughtSpot Worksheet or Model into a Snowflake Semantic View by exporting TML, mapping columns and joins, translating formulas, and creating the view via SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML.
---

# ThoughtSpot → Snowflake Semantic View

Convert a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Searches
ThoughtSpot for available models, exports the TML definition, maps it to the Snowflake
Semantic View YAML format, and creates it via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`.

---

## References

| File | Purpose |
|---|---|
| [references/mapping-rules.md](references/mapping-rules.md) | Column classification, aggregation, join type, data type, and name generation lookup tables |
| [references/formula-translation.md](references/formula-translation.md) | ThoughtSpot formula → SQL translation rules and untranslatable pattern handling |
| [references/property-coverage.md](references/property-coverage.md) | Full property coverage matrix, limitations, and Unmapped Report format |
| [references/snowflake-schema.md](references/snowflake-schema.md) | Snowflake Semantic View YAML schema and validation rules |
| [references/environment-setup.md](references/environment-setup.md) | Runtime environment detection and Snowflake connectivity options |

---

## Concept Mapping

| ThoughtSpot | Snowflake Semantic View |
|---|---|
| Worksheet / Model | Semantic View |
| `ATTRIBUTE` column (non-date) | `dimensions[]` |
| `ATTRIBUTE` column (date/timestamp) | `time_dimensions[]` |
| `MEASURE` column | `measures[]` |
| Formula column (`formula_id`) | `measures[]` — expression translated to SQL |
| `joins[]` / `referencing_join` | `relationships[]` — conditions from Table TML |
| `synonyms[]` | `synonyms[]` |
| `ai_context` | `description` — merged with `[TS AI Context]` prefix |

For the full coverage matrix including unmapped properties, see
[references/property-coverage.md](references/property-coverage.md).

---

## Prerequisites

**ThoughtSpot:**
- Instance v8.4 or later, REST API v2 enabled
- User with `DATAMANAGEMENT` or `DEVELOPER` privilege, or trusted auth secret key

**Snowflake:**
- Role with `CREATE SEMANTIC VIEW` on the target schema
- A connection method available (see [references/environment-setup.md](references/environment-setup.md))

**Environment variables** — confirm all are set before Step 1:
```
THOUGHTSPOT_BASE_URL     # e.g. https://myorg.thoughtspot.cloud  (no trailing slash)
THOUGHTSPOT_USERNAME     # e.g. analyst@company.com
THOUGHTSPOT_SECRET_KEY   # trusted auth key  (preferred)
THOUGHTSPOT_PASSWORD     # password auth     (alternative)
```

---

## Worked Example

### Input — ThoughtSpot Worksheet TML

```yaml
guid: 2ea7add9-0ccb-4ac1-90bb-231794ebb377
worksheet:
  name: Retail Sales
  tables:
  - name: fact_sales
  - name: dim_product
  joins:
  - name: sales_to_product
    source: fact_sales
    destination: dim_product
    type: INNER
    is_one_to_one: false
  table_paths:
  - id: fact_sales_1
    table: fact_sales
    join_path:
    - {}
  - id: dim_product_1
    table: dim_product
    join_path:
    - join:
      - sales_to_product
  formulas:
  - name: '# of Products'
    expr: "count ( [dim_product_1::product_id] )"
  worksheet_columns:
  - name: Product
    column_id: dim_product_1::product_name
    properties:
      column_type: ATTRIBUTE
      synonyms: [Item]
  - name: Revenue
    column_id: fact_sales_1::sales_amount
    properties:
      column_type: MEASURE
      aggregation: SUM
      synonyms: [Sales]
      ai_context: Total transaction value for financial analysis.
  - name: Sale Date
    column_id: fact_sales_1::sale_date
    properties:
      column_type: ATTRIBUTE
  - name: Product Count
    formula_id: '# of Products'
    properties:
      column_type: MEASURE
      aggregation: COUNT
```

Associated Table TML for `fact_sales` provides `db: ANALYTICS, schema: PUBLIC,
db_table: FACT_SALES` and the join condition
`"[fact_sales::product_id] = [dim_product::product_id]"`.

### Output — Snowflake Semantic View YAML

```yaml
name: retail_sales
description: "Migrated from ThoughtSpot: Retail Sales"
tables:
- name: fact_sales
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: FACT_SALES
- name: dim_product
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: DIM_PRODUCT
relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: product_id
    right_column: product_id
  relationship_type: many_to_one
  join_type: inner
dimensions:
- name: product
  synonyms: ["Product", "Item"]
  description: ""
  expr: dim_product.PRODUCT_NAME
  data_type: TEXT
  sample_values: []
time_dimensions:
- name: sale_date
  synonyms: ["Sale Date"]
  description: ""
  expr: fact_sales.SALE_DATE
  data_type: DATE
measures:
- name: revenue
  synonyms: ["Revenue", "Sales"]
  description: "[TS AI Context] Total transaction value for financial analysis."
  expr: SUM(fact_sales.SALES_AMOUNT)
  data_type: NUMBER
  default_aggregation: sum
- name: product_count
  synonyms: ["Product Count", "# of Products"]
  description: ""
  expr: COUNT(dim_product.PRODUCT_ID)
  data_type: NUMBER
  default_aggregation: count
```

---

## Workflow

### Step 1: Authenticate

Confirm all environment variables are set. Obtain a bearer token:

```
POST {THOUGHTSPOT_BASE_URL}/api/rest/2.0/auth/token/full
{
  "username": "{THOUGHTSPOT_USERNAME}",
  "secret_key": "{THOUGHTSPOT_SECRET_KEY}",   // or "password": "..."
  "validity_time_in_sec": 3600
}
```

Store `token` from the response. Use `Authorization: Bearer {token}` on all subsequent
ThoughtSpot API calls. On 401/403 — stop and ask the user to verify credentials.

---

### Step 2: Search and Select a Model

Ask the user whether to browse all models or search by keyword.

```
POST {THOUGHTSPOT_BASE_URL}/api/rest/2.0/metadata/search
{
  "metadata": [{"type": "LOGICAL_TABLE"}],
  "record_size": 50,
  "record_offset": 0
}
```

Add `"query_string": "{keyword}"` to filter by name. Show only subtypes `WORKSHEET`
or `MODEL` (filter on `metadata_detail.type`).

Display a numbered list and wait for the user to select one. Store `metadata_id` as
`{selected_model_id}` and `metadata_name` as `{original_model_name}`.

---

### Step 3: Export the TML

```
POST {THOUGHTSPOT_BASE_URL}/api/rest/2.0/metadata/tml/export
{
  "metadata": [{"identifier": "{selected_model_id}"}],
  "export_fqn": true,
  "export_associated": true
}
```

Parse every `edoc` string as YAML. Separate into:
- **Primary object:** parsed YAML has top-level key `worksheet` or `model`
- **Table objects:** parsed YAML has top-level key `table`

---

### Step 4: Identify TML Format

| Top-level key | Format | Key difference |
|---|---|---|
| `worksheet` | Worksheet | Join conditions in Table TML; columns explicit in `worksheet_columns[]` |
| `model` | Model | Joins use `referencing_join` or inline `on`; columns derived from Table TML |

---

### Step 5: Resolve Physical Table Names

Build a map: `logical_table_name → { database, schema, physical_table }`.

From each Table TML object extract:
```yaml
table:
  name: fact_sales       # map key
  db: ANALYTICS
  schema: PUBLIC
  db_table: FACT_SALES
```

If `db` or `schema` is absent, ask the user to provide them before continuing.
If a table has no associated TML, fetch it separately using its FQN GUID:
```
POST /api/rest/2.0/metadata/tml/export  { "metadata": [{"identifier": "{fqn}"}] }
```

Use `TODO_DATABASE` / `TODO_SCHEMA` placeholders for unresolved tables and flag them.

---

### Step 6: Build Path → Table Map (Worksheet format only)

Skip for Model format.

From `worksheet.table_paths[]`, build: `path_id → table_alias`.

```yaml
table_paths:
- id: fact_sales_1    # path_id used in column_id references
  table: fact_sales   # resolves to this table alias
```

---

### Step 7: Build Relationships

For each join, obtain the `on` condition and produce a Snowflake relationship.

**Worksheet format:** Join `on` conditions are in Table TML `joins_with[]`. Match
by `name` field across all Table TML objects.

**Model format — two join patterns:**

*Inline `on`:*
```yaml
joins:
- with: DM_LOCALE_COUNTRY
  "on": "[DM_CUSTOMER::COUNTRY] = [DM_LOCALE_COUNTRY::COUNTRY_KEY]"
  type: INNER
  cardinality: ONE_TO_ONE
```

*`referencing_join` (most common in real models):*
```yaml
joins:
- with: DM_CUSTOMER
  referencing_join: DM_ORDER_to_DM_CUSTOMER
```
Search all Table TML `joins_with[]` for `name: DM_ORDER_to_DM_CUSTOMER`.
Note: `destination` in Table TML may be an object (`destination.name`) — handle both.

**Parse `on` condition:** regex `\[([^\]:]+)::([^\]]+)\]\s*=\s*\[([^\]:]+)::([^\]]+)\]`
→ left_table, left_column, right_table, right_column.

For join type and cardinality mappings, see
[references/mapping-rules.md](references/mapping-rules.md).

---

### Step 8: Map Columns

Iterate `worksheet.worksheet_columns[]` (Worksheet) or Table TML `columns[]` (Model).

**For each column:**

1. Resolve physical column name from Table TML: `column_id: path_id::logical_name`
   → look up path_id (Step 6) → table alias → look up logical_name → `db_column_name`
2. Classify as dimension / time_dimension / measure using the decision tree in
   [references/mapping-rules.md](references/mapping-rules.md)
3. Merge `ai_context` into `description` with prefix `[TS AI Context]` if present
4. Record any unmapped properties (format_pattern, default_date_bucket, custom_order,
   column_groups, geo_config) for the Unmapped Properties Report
5. Build the Snowflake field entry using the templates in
   [references/mapping-rules.md](references/mapping-rules.md)

---

### Step 9: Translate Formulas

For each formula column (`formula_id` is set):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format (Worksheet uses
   `[path_id::col]`, Model uses `[TABLE::col]`)
3. Replace function names using
   [references/formula-translation.md](references/formula-translation.md)
4. For untranslatable patterns (parameters, `sql_string_op`, time intelligence),
   emit a `-- TODO` comment and add to the Formula Translation Log
5. Handle nested references up to 3 levels deep

---

### ⚑ Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

Present the following three sections:

**1. Generated YAML** — full content in a code block.

**2. Conversion Summary:**
```
- Tables:          {n}
- Relationships:   {n}
- Dimensions:      {n}
- Time dimensions: {n}
- Measures:        {n}  ({n} translated formulas, {n} with -- TODO)
```

**3. Unmapped Properties Report** — use the format defined in
[references/property-coverage.md](references/property-coverage.md).
Include only sections that have entries. Common sections:
- Parameters not migrated
- Column groups not migrated
- AI Context merged into description
- Format patterns not migrated
- Default date buckets not migrated
- Formula Translation Log (all formulas, translated and untranslated)
- Other dropped properties

Then ask:
```
Shall I create this Semantic View in Snowflake?
  YES  — proceed
  NO   — cancel
  EDIT — followed by changes to the YAML
```

---

### Step 11: Validate

Run all checks from [references/snowflake-schema.md](references/snowflake-schema.md).
Report all failures together before retrying. Key checks:

- [ ] Field names unique across dimensions, time_dimensions, measures
- [ ] All `expr` table prefixes match a `tables[]` entry
- [ ] All relationship table references match a `tables[]` entry
- [ ] No `-- TODO` placeholders (or user has acknowledged)
- [ ] Valid Snowflake identifiers, `data_type`, `default_aggregation`, `join_type`, `relationship_type`

---

### Step 12: Check for Existing View

```sql
SELECT COUNT(*) AS existing_count
FROM INFORMATION_SCHEMA.SEMANTIC_VIEWS
WHERE SEMANTIC_VIEW_NAME = UPPER('{semantic_view_name}')
  AND TABLE_SCHEMA = UPPER('{target_schema}');
```

If exists, ask the user: DROP and recreate / use a different name / cancel.

---

### Step 13: Execute

Ask for Snowflake target if not already provided:
`semantic_view_name`, `target_database`, `target_schema`, `role`.

Use the appropriate connection method from
[references/environment-setup.md](references/environment-setup.md).

```sql
USE ROLE {role};
USE DATABASE {target_database};
USE SCHEMA {target_schema};

SELECT SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML($$
{yaml}
$$);
```

On success: report the created view name and location.
On failure: show the full Snowflake error. Do not retry automatically — ask the user.
