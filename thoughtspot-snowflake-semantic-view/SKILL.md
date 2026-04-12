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
| [references/thoughtspot-auth.md](references/thoughtspot-auth.md) | ThoughtSpot profile configuration, token persistence, and API call patterns |
| [references/thoughtspot-tml.md](references/thoughtspot-tml.md) | TML export parsing — non-printable chars, PyYAML pitfalls, object type identification |
| [references/snowflake-setup.md](references/snowflake-setup.md) | Snowflake connection profiles, auth methods, execution options, and detection order |

---

## Concept Mapping

| ThoughtSpot | Snowflake Semantic View |
|---|---|
| Worksheet / Model | Semantic View |
| `ATTRIBUTE` column (non-date) | `dimensions[]` — nested under owning table |
| `ATTRIBUTE` column (date/timestamp) | `time_dimensions[]` — nested under owning table |
| `MEASURE` column | `metrics[]` — nested under owning table |
| Formula column (`formula_id`) — translatable | `metrics[]` — expression translated to SQL |
| Formula column (`formula_id`) — untranslatable | **Omitted** — logged in Unmapped Report |
| `joins[]` / `referencing_join` | `relationships[]` — top-level, no join/cardinality type |
| Right-side join table | `primary_key` section on that table entry |
| `synonyms[]` | `synonyms[]` |
| `ai_context` | `description` — merged with `[TS AI Context]` prefix |

**Key structural rule:** `dimensions`, `time_dimensions`, and `metrics` are nested
under each `tables[]` entry — they are **not** top-level keys in the semantic view.

**Key keyword:** Use `metrics`, not `measures`. `measures` is not a valid key and
will cause a parse error.

For the full coverage matrix including unmapped properties, see
[references/property-coverage.md](references/property-coverage.md).

---

## Prerequisites

**ThoughtSpot:**
- Instance v8.4 or later, REST API v2 enabled
- User with `DATAMANAGEMENT` or `DEVELOPER` privilege, or trusted auth secret key

**Snowflake:**
- Role with `CREATE SEMANTIC VIEW` on the target schema
- A connection method available (see [references/snowflake-setup.md](references/snowflake-setup.md))

**Profile configuration** — preferred method:

Named profiles are stored in `~/.claude/thoughtspot-profiles.json`. Non-sensitive
values (URL, username) live in the file; secret keys are referenced by env var name
and must be exported in `~/.zshrc`:

```json
{
  "profiles": [
    {
      "name": "Production",
      "base_url": "https://myorg.thoughtspot.cloud",
      "username": "analyst@company.com",
      "secret_key_env": "THOUGHTSPOT_SECRET_KEY_PROD"
    }
  ]
}
```

```bash
# ~/.zshrc
export THOUGHTSPOT_SECRET_KEY_PROD=your-secret-key
```

**Fallback** — if no profiles file exists, read from environment variables directly:
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
  time_dimensions:
  - name: sale_date
    synonyms:
    - "Sale Date"
    description: ""
    expr: fact_sales.SALE_DATE
    data_type: DATE
  metrics:
  - name: revenue
    synonyms:
    - "Revenue"
    - "Sales"
    description: "[TS AI Context] Total transaction value for financial analysis."
    expr: SUM(fact_sales.SALES_AMOUNT)
    data_type: NUMBER

- name: dim_product
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: DIM_PRODUCT
  primary_key:
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
    data_type: NUMBER

relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

Key differences from wrong patterns:
- `dimensions`, `time_dimensions`, `metrics` are **nested under their table**, not top-level
- Keyword is `metrics`, not `measures`
- `primary_key` is present on `dim_product` (the right-side join table)
- No `relationship_type`, `join_type`, `sample_values`, or `default_aggregation`

---

## Workflow

### Step 1: Authenticate

**Profile selection:**

1. Read `~/.claude/thoughtspot-profiles.json` if it exists.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and ask the user to confirm before proceeding.
4. If no profiles file: fall back to `THOUGHTSPOT_BASE_URL` / `THOUGHTSPOT_USERNAME` / `THOUGHTSPOT_SECRET_KEY` env vars.

```
Available ThoughtSpot profiles:
  1. Production — analyst@company.com @ myorg.thoughtspot.cloud
  2. Staging    — analyst@company.com @ myorg-staging.thoughtspot.cloud

Select a profile (or press Enter to use #1):
```

After profile is confirmed, resolve the secret key:
- Read the `secret_key_env` field from the profile (e.g. `THOUGHTSPOT_SECRET_KEY_CHAMPAGNE`)
- Read that env var's value at runtime
- If the env var is unset or empty, **ask the user to paste the key directly** before proceeding:
  `Secret key for {profile_name} is not set (expected env var: {secret_key_env}). Please paste your secret key:`
  Then use the pasted value for this session only — do not write it to any file.

Strip any trailing slash from `base_url` before constructing URLs.

**Obtain a bearer token:**

```
POST {base_url}/api/rest/2.0/auth/token/full
{
  "username": "{username}",
  "secret_key": "{secret_key}",   // or "password": "..."
  "validity_time_in_sec": 3600
}
```

On 401/403 — stop and ask the user to verify credentials.

**Claude Code shell context — token persistence:**
Bash tool calls do not share shell state between separate invocations. Never store
the token in a shell variable across calls — it will be empty in the next call.
Instead, use one of these strategies for every subsequent API call:

- **Inline fetch (preferred for single calls):** Fetch the token and make the API
  call within the **same** `Bash` invocation using `$()` substitution.
- **Temp file (preferred for multi-call scripts):** Write the token to
  `/tmp/ts_token.txt` immediately after authenticating:
  ```bash
  TOKEN=$(curl -s ... | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
  echo "$TOKEN" > /tmp/ts_token.txt
  ```
  Read it back in subsequent calls with `TOKEN=$(cat /tmp/ts_token.txt)`.
- **Single pipeline:** Combine all API calls into one `python3` or `bash` script
  within a single Bash invocation.

The temp file approach is most reliable for the multi-step workflow in this skill.
Delete `/tmp/ts_token.txt` at the end of the session.

---

### Step 2: Find and Select a Model

**Present the following options to the user:**
```
How would you like to find your model?
  G — I have a GUID
  S — Search (by name, author, tags, or a combination)
  B — Browse all
```

---

#### Option G — Direct GUID

If the user provides a GUID, skip search entirely. Store it as `{selected_model_id}`.
The model name will be confirmed from the TML export in Step 3.

---

#### Option S — Search

Ask the user which filters to apply (they may provide any combination):

```
Enter search criteria (leave blank to skip):
  Name keyword:
  Author (username or email):
  Tags (comma-separated):
```

Build the request body from whichever fields are provided. All supplied filters
combine with AND semantics — results must satisfy every condition:

```
POST {base_url}/api/rest/2.0/metadata/search
{
  "metadata": [{"type": "LOGICAL_TABLE"}],
  "query_string": "{name_keyword}",           // omit if blank
  "created_by_user_identifiers": ["{author}"], // omit if blank; accepts username or GUID
  "tag_identifiers": ["{tag1}", "{tag2}"],     // omit if blank; accepts tag name or GUID
  "record_size": 50,
  "record_offset": 0
}
```

Paginate in increments of 50 until an empty page is returned before displaying results.

**Zero results fallback:** If a name-only search returns zero results, re-run with
no `query_string`, collect all results, and apply case-insensitive substring matching
against `metadata_name` client-side. Present matches or offer to browse all.

---

#### Option B — Browse All

Fetch all pages (`record_offset` 0, 50, 100, …) until an empty page is returned.
Filter to `metadata_header.type == 'WORKSHEET'` and display the full numbered list.

---

#### Displaying Results

```
1. [WORKSHEET] Retail Sales WS            id: e61c7c4c-...
2. [WORKSHEET] TS: BI Server              id: eaab6de7-...
```

**API subtype note:** Both Worksheets and Models appear as `type: WORKSHEET` in the
search response — there is no separate `MODEL` subtype. `metadata_detail` is
frequently `null` and must not be relied on for subtype filtering. The actual TML
format (`worksheet` vs `model` top-level key) is only determined after export in
Step 3.

Store `metadata_id` as `{selected_model_id}` and `metadata_name` as
`{original_model_name}`.

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

**Non-printable characters:** Some TML contains special characters (e.g. `#x0095`)
that cause `yaml.safe_load` to raise a `ReaderError`. Strip them before parsing:
```python
import re
cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\x85\xA0-\uD7FF\uE000-\uFFFD]', '', edoc)
parsed = yaml.safe_load(cleaned)
```

Parse every `edoc` string as YAML (with cleaning). Separate into:
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
  schema: PUBLIC         # accessed as tbl.get("schema") — NOT tbl.get("schema_")
  db_table: FACT_SALES
```

**PyYAML field name:** The schema field is `"schema"` in Python dicts after parsing —
never `"schema_"`. See [references/thoughtspot-tml.md](references/thoughtspot-tml.md) for details.

**Schema is reliably exported:** With `export_fqn: true` and `export_associated: true`,
the schema value is present in Table TML whenever it is set in ThoughtSpot. If it
appears missing, first verify with `tbl.keys()` — do not prompt the user until confirmed
genuinely absent.

If `db` or `schema` is confirmed absent after inspection, ask the user to provide them.
If a table has no associated TML, fetch it separately using its FQN GUID:
```
POST /api/rest/2.0/metadata/tml/export  { "metadata": [{"identifier": "{fqn}"}] }
```

Use `TODO_DATABASE` / `TODO_SCHEMA` placeholders for unresolved tables and flag them.

**Case-sensitivity detection:** After resolving physical table locations, run
`SHOW SCHEMAS IN DATABASE {db}` and `SHOW COLUMNS IN TABLE {db}.{schema}.{table}`
to determine which identifiers are case-sensitive (returned in lowercase by SHOW).
Record a `case_sensitive` flag per schema, table, and column. This drives identifier
quoting in all subsequent steps. See [references/snowflake-schema.md](references/snowflake-schema.md)
for the `'"value"'` encoding pattern.

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

**Scope filter — Model format only:** A model's `model_tables[]` is the authoritative
list of tables in scope. Table TML `joins_with[]` entries may reference tables that
are **not** in `model_tables` (e.g. a supplier or status lookup table that exists
in Snowflake but was excluded from the model). Skip any join where either
`left_table` or `right_table` is not in `model_tables`. Only emit relationships
for joins where **both** tables are present in `model_tables`.

**Table aliases in Model format:** `model_tables[]` entries can have an `alias` field:
```yaml
model_tables:
- name: colour
  alias: eye colour      # ← this is the identifier used in column_id references
- name: colour
  alias: hair colour
- name: colour
  alias: skin colour
```
When `alias` is present:
- Use `to_snake(alias)` as the Snowflake table `name` (e.g. `eye_colour`)
- Use the physical `db_table` as `base_table.table` (e.g. `colour`)
- Build an `alias_to_sf_name` map for column_id resolution
- Column references in `model.columns` use the alias: `column_id: eye colour::colour`
- Relationship `with:` field also uses the alias: `with: eye colour`

Deduplicate Snowflake table names if the same alias appears twice (append `_2`, `_3`).

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

**Source of truth — hierarchy:**

| Layer | Used for |
|---|---|
| `model.columns[]` | All Semantic View field definitions — name, description, type, aggregation, synonyms, ai_context, formula_id, column_id |
| Table TML `columns[]` | Resolving `column_id` → `db_column_name` and `db_column_properties.data_type` |
| Table TML root (`db`, `schema`, `db_table`) | Physical table location for `base_table` entries |
| `connections.yaml` | Fallback only — if Snowflake reports column not found, `external_column` overrides `db_column_name` |

The model is the semantic layer and the single source of truth for what appears in
the Semantic View. Never derive the column list from Table TML.

**Column ID resolution:**

`column_id` format: `TABLE_NAME::LOGICAL_COLUMN_NAME`

1. Split on `::` → `table_name`, `logical_col_name`
2. Find the Table TML for `table_name`
3. Find the column in Table TML `columns[]` where `name == logical_col_name`
4. That column's `db_column_name` is the physical Snowflake column name (in the
   vast majority of cases — it is the actual DB column name)
5. Build `expr` as `table_name.DB_COLUMN_NAME`
   - If `DB_COLUMN_NAME` is a SQL reserved word (e.g. `date`, `time`, `schema`),
     double-quote it: `table_name."date"`
6. Use `db_column_properties.data_type` for date/time classification

**`connections.yaml` — do not consult proactively.** Only if Snowflake returns a
column-not-found error after execution should you check `connections.yaml`, where
`external_column` may override `db_column_name` for a given column:
```yaml
column:
- name: CATEGORY_ID           # = db_column_name in Table TML
  external_column: CATEGORY_ID  # = actual physical column in Snowflake (may differ)
```

**Output structure — fields are table-scoped:**

Each field must be placed under the `tables[]` entry for its owning table. Accumulate
fields per table as you iterate columns, then emit the full table entry with nested
`dimensions`, `time_dimensions`, and `metrics` sections.

**`primary_key` — required for join target tables:**

After building all relationships, identify every table that appears as `right_table`
in a relationship. Each such table entry must include a `primary_key` section listing
the physical column(s) used as the join key:
```yaml
primary_key:
- {PHYSICAL_COLUMN_NAME}
```

**For each model column:**

1. If `formula_id` set → translate formula in Step 9; if untranslatable, omit the
   column and log it; do not include placeholder `expr` values
2. If `column_id` set → resolve physical column name as above
3. Classify as dimension / time_dimension / metric using the decision tree in
   [references/mapping-rules.md](references/mapping-rules.md)
4. Merge `ai_context` into `description` with prefix `[TS AI Context]` if present
5. Record unmapped properties (format_pattern, default_date_bucket, custom_order,
   data_panel_column_groups, geo_config) for the Unmapped Properties Report
6. Build the Snowflake field entry using the templates in
   [references/mapping-rules.md](references/mapping-rules.md)
7. Append the field to the field list for its owning table

---

### Step 9: Translate Formulas

For each formula column (`formula_id` is set):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format (Worksheet uses
   `[path_id::col]`, Model uses `[TABLE::col]`)
3. Replace function names using
   [references/formula-translation.md](references/formula-translation.md)
4. Handle nested references up to 3 levels deep

**Untranslatable formulas — omit entirely:**

For formulas containing untranslatable patterns (ThoughtSpot parameters, `sql_string_op`,
time intelligence functions, `runtime_filter`), **do not emit the column** in the YAML.
Do NOT use `-- TODO`, `CAST(NULL AS TEXT)`, or any placeholder `expr` — these cause
Snowflake parse errors or silent failures.

Instead:
- Skip the column in the output YAML
- Add an entry to the Formula Translation Log in the Unmapped Properties Report:
  ```
  | {display_name} | OMITTED | {reason} | {original_expr} |
  ```

Untranslatable patterns to recognise:
- `[parameter_name]` — ThoughtSpot runtime parameter (no SQL equivalent)
- `sql_string_op(...)` — raw SQL injection pattern
- `ts_first_day_of_week(...)`, `last_n_days(...)` — ThoughtSpot time intelligence
- Any reference to a formula that is itself untranslatable (transitive)

---

### ⚑ Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

Present the following three sections:

**1. Generated YAML** — full content in a code block.

**2. Conversion Summary:**
```
- Tables:          {n}
- Relationships:   {n}
- Dimensions:      {n}  (across all tables)
- Time dimensions: {n}  (across all tables)
- Metrics:         {n}  ({n} translated formulas, {n} physical columns)
- Omitted columns: {n}  (untranslatable formulas — see Formula Translation Log)
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

- [ ] `dimensions`, `time_dimensions`, `metrics` are nested under `tables[]` entries — NOT top-level
- [ ] Keyword is `metrics` not `measures` anywhere in the YAML
- [ ] Field names unique globally across all tables' dimensions, time_dimensions, metrics
- [ ] All `expr` table prefixes match a `name` in `tables[]`
- [ ] All relationship `left_table`/`right_table` values match a `name` in `tables[]`
- [ ] Every `right_table` in a relationship has a `primary_key` section
- [ ] Reserved words in column names are double-quoted in `expr`
- [ ] No `relationship_type`, `join_type`, `sample_values`, or `default_aggregation` fields
- [ ] No untranslatable formula placeholders (`-- TODO`, `CAST(NULL AS TEXT)`, `NULL`)
- [ ] Valid Snowflake identifiers (view name, all field names): `^[A-Za-z_][A-Za-z0-9_]*$`
- [ ] Valid `data_type` values: `TEXT`, `NUMBER`, `DATE`, `TIMESTAMP`, `BOOLEAN`

---

### Step 12: Check for Existing View

**Skip the INFORMATION_SCHEMA check** — `INFORMATION_SCHEMA.SEMANTIC_VIEWS` and its
column names vary by Snowflake version and may not exist. Instead, proceed directly
to Step 13. If the view already exists, `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` will
return an error indicating it exists — at that point offer the user:
- DROP and recreate: `DROP SEMANTIC VIEW IF EXISTS {database}.{schema}.{name};`
- Use a different name
- Cancel

---

### Step 13: Execute

Ask for Snowflake target if not already provided:
`target_database`, `target_schema`, `role`.

**Snowflake profile selection:**
1. Read `~/.claude/snowflake-profiles.json`
2. If multiple profiles: display numbered list and ask user to select
3. If one profile: show it and confirm
4. If no file: ask for account, username, auth method; offer to save profile for future use
5. If `private_key_passphrase_env` is set, read passphrase from that env var at runtime

**Warehouse:** If not specified in the profile, run `SHOW WAREHOUSES` after connecting
and use the first available warehouse (preferring running over suspended).

Use the connection method from [references/snowflake-setup.md](references/snowflake-setup.md).

**Always run a dry-run first:**

```sql
USE ROLE {role};
USE DATABASE {target_database};
USE SCHEMA {target_schema};

-- Step 1: Dry-run validation (third arg TRUE = validate only, do not create)
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{yaml}
$$, TRUE);
```

If dry-run succeeds, proceed to create:

```sql
-- Step 2: Create
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{yaml}
$$);
```

**Notes:**
- Use `CALL`, not `SELECT`
- First argument: fully-qualified target schema `'DATABASE.SCHEMA'`
- Second argument: YAML content in `$$` dollar-quotes (safe for YAML with single quotes)
- Third argument `TRUE`: dry-run mode — validates without creating

On success: report the created view name and location.
On failure: show the full Snowflake error. Do not retry automatically — ask the user.

**If the view already exists:**
```sql
DROP SEMANTIC VIEW IF EXISTS {target_database}.{target_schema}.{semantic_view_name};
```
Then re-run the CREATE call.
