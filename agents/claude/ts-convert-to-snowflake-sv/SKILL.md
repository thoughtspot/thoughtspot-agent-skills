---
name: ts-convert-to-snowflake-sv
description: Convert a ThoughtSpot Worksheet or Model into a Snowflake Semantic View by exporting TML, mapping columns and joins, translating formulas, and creating the view via CREATE OR REPLACE SEMANTIC VIEW DDL.
---

# ThoughtSpot → Snowflake Semantic View

Convert a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Searches
ThoughtSpot for available models, exports the TML definition, maps it to the Snowflake
Semantic View DDL format, and creates it via `CREATE OR REPLACE SEMANTIC VIEW`.

---

## References

| File | Purpose |
|---|---|
| [~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md) | Column classification, aggregation, join type, data type, and name generation lookup tables |
| [~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md](~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | ThoughtSpot formula ↔ SQL translation rules (bidirectional) and untranslatable pattern handling |
| [~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md](~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md) | Full property coverage matrix, limitations, and Unmapped Report format |
| [~/.claude/shared/schemas/snowflake-schema.md](~/.claude/shared/schemas/snowflake-schema.md) | Snowflake Semantic View DDL syntax, validation rules, and known limitations |
| [~/.claude/shared/schemas/thoughtspot-tml.md](~/.claude/shared/schemas/thoughtspot-tml.md) | TML export parsing — non-printable chars, PyYAML pitfalls, object type identification |
| [~/.claude/shared/schemas/thoughtspot-table-tml.md](~/.claude/shared/schemas/thoughtspot-table-tml.md) | Table TML field reference — column types, data types, joins_with structure |
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | Model TML field reference — model_tables, columns, formulas, join scenarios |
| [~/.claude/shared/worked-examples/snowflake/ts-to-snowflake.md](~/.claude/shared/worked-examples/snowflake/ts-to-snowflake.md) | End-to-end mapping example: Worksheet TML → Semantic View DDL |
| [~/.claude/skills/ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| [~/.claude/skills/ts-profile-snowflake/SKILL.md](~/.claude/skills/ts-profile-snowflake/SKILL.md) | Snowflake connection code, SQL execution patterns, SHOW commands for case-sensitivity |
| [../references/direct-api-auth.md](../references/direct-api-auth.md) | Direct API authentication fallback when stored procedures are unavailable |

---

## Concept Mapping

| ThoughtSpot | Snowflake Semantic View DDL |
|---|---|
| Worksheet / Model | Semantic View |
| `ATTRIBUTE` column (non-date) | `dimensions()` clause — `TABLE.ALIAS as table.COL with synonyms=(...)` |
| `ATTRIBUTE` column (date/timestamp) | `dimensions()` clause — same as above; flagged as `time_dimensions` in CA extension JSON only |
| `MEASURE` column (SUM/AVG/MIN/MAX) | `metrics()` clause — `TABLE.ALIAS as AGG(table.COL) with synonyms=(...)` |
| `MEASURE` COUNT_DISTINCT column | `metrics()` clause — `TABLE.ALIAS as COUNT(DISTINCT table.COL)` |
| Formula column — translatable MEASURE | `metrics()` clause — expression translated to SQL aggregation |
| Formula column — translatable ATTRIBUTE | `dimensions()` clause — expression as computed column alias |
| Formula column — `last_value(sum(m), query_groups(), {date})` | `metrics()` with `non additive by (DATE_TABLE.COL direction nulls last)` modifier |
| Formula column — untranslatable | **Omitted** — logged in Unmapped Report |
| `joins[]` / `referencing_join` | `relationships()` clause — `rel_name as LEFT(col) references RIGHT(col)` |
| Right-side join table | `primary key (COL)` in the `tables()` declaration for that table |
| `synonyms[]` | `with synonyms=('...', '...')` on the dimension or metric entry |
| `ai_context` / model `description` | `comment='...'` on the semantic view |
| Semantic layer structure | `with extension (CA='...')` — JSON mapping each table's columns to dimension/time_dimension/metric |

## DDL Format Reference

The output is a `CREATE OR REPLACE SEMANTIC VIEW` statement. Full structure:

```sql
CREATE OR REPLACE SEMANTIC VIEW {sv_name}
  tables (
    {DB}.{SCHEMA}.{TABLE} [primary key ({PK_COL})],
    ...
  )
  relationships (
    {left_table}_to_{right_table} as {LEFT_TABLE}({fk_col}) references {RIGHT_TABLE}({pk_col}),
    ...
  )
  dimensions (
    {TABLE}.{ALIAS} as {table_lower}.{PHYSICAL_COL} [with synonyms=('{display_name}')],
    {TABLE}.{ALIAS} as {SQL_EXPRESSION} [with synonyms=('{display_name}')],  -- formula dim
    ...
  )
  metrics (
    {TABLE}.{ALIAS} as {AGG}({table_lower}.{COL}) [with synonyms=('{display_name}')],
    {TABLE}.{ALIAS} non additive by ({TIME_TABLE}.{TIME_COL} {asc|desc} nulls last) as SUM({table_lower}.{COL}) [with synonyms=(...)],
    {TABLE}.{ALIAS} as DIV0({table_lower}.{metric_alias}, {table_lower}.{other_metric_alias}) [...],  -- ratio: reference metric aliases not raw aggregates
    ...
  )
  comment='{description}'
  with extension (CA='{ca_json}')
```

**DDL rules:**
- All non-metric columns (including dates, FK columns) go in `dimensions()`. There is no `time_dimensions` clause in the DDL — date classification lives only in the CA extension JSON.
- Metric expressions reference **column aliases** (lowercase, as defined in `dimensions()` or earlier `metrics()` entries), not raw physical column names. For ratio metrics, reference the previously-defined aggregated metric alias: `DIV0(tbl.amount, tbl.quantity)` — do not nest `SUM()` calls directly.
- Relationship names: `{left_table}_to_{right_table}` (lowercase). Disambiguate duplicates by appending the FK column: `{left_table}_{fk_col}_to_{right_table}`.
- Column alias format: `TABLE_NAME.DESCRIPTIVE_ALIAS` (uppercase, e.g. `DM_ORDER.ORDER_ID`). Reference the alias with lowercase table and alias: `dm_order.ORDER_ID` or `dm_order.order_id`.
- `with extension (CA='...')` is a JSON string that maps each table's columns into `dimensions[]`, `time_dimensions[]`, and `metrics[]` by alias name (lowercase). Required for Cortex Analyst to understand the semantic structure. Relationship names are also listed here.

**CA extension JSON structure:**
```json
{
  "tables": [
    {
      "name": "dm_order",
      "dimensions": [{"name": "order_id"}, {"name": "fk_col"}],
      "time_dimensions": [{"name": "order_date"}],
      "metrics": [{"name": "employees"}]
    }
  ],
  "relationships": [
    {"name": "dm_order_to_dm_customer"}
  ]
}
```

For the full coverage matrix including unmapped properties, see
[~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md](~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md).

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege
- Authentication configured — run `/ts-profile-thoughtspot` if you haven't already

**Quick auth decision:**
```
Can you log into ThoughtSpot in a browser (even via SSO)?
  YES → token_env   — get a token from Developer Playground (no admin needed)
  NO  → password_env or secret_key_env — see ts-profile-thoughtspot.md
```

### Snowflake

- Role with `CREATE SEMANTIC VIEW` on the target schema — **only required if creating live**
- Connection configured — run `/ts-profile-snowflake` if you haven't already
- Not sure where to start? → Python connector + password auth has the fewest setup steps

**No Snowflake access?** You can still run this skill in **file-only mode** — it generates
the `CREATE OR REPLACE SEMANTIC VIEW` DDL and writes it to a `.sql` file you can run
manually in Snowsight later. Select **FILE** at the Step 10 checkpoint or say "file only"
at any point before Step 12.

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If a ThoughtSpot profile was already confirmed earlier in
this conversation (e.g. for a previous model in a batch), skip profile selection
and reuse it.

**Profile selection (first model only):**

1. Read `~/.claude/thoughtspot-profiles.json`.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and confirm before proceeding.

```
Available ThoughtSpot profiles:
  1. Production — analyst@company.com @ myorg.thoughtspot.cloud
  2. Staging    — analyst@company.com @ myorg-staging.thoughtspot.cloud

Select a profile (or press Enter to use #1):
```

After the profile is confirmed, verify the connection:

```bash
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

The CLI handles token caching, Keychain access, and expiry automatically.
No temp files or manual token management needed in this skill.

If `ts auth whoami` returns 401, the token is expired. Ask the user to refresh it:

```
Your ThoughtSpot token has expired. To refresh:
  1. Log into ThoughtSpot in your browser
  2. Go to Develop → REST Playground 2.0 → Authentication → Get Current User Token
  3. Click Try it out → Execute, then copy the token value
  4. Run in your terminal:
       security delete-generic-password -s "thoughtspot-{slug}" -a "{username}"
       security add-generic-password -s "thoughtspot-{slug}" -a "{username}" -w "YOUR_TOKEN"
  5. Let me know when done.
```

Then clear the stale cache and retry:

```bash
ts auth logout --profile {profile_name}
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

---

### Step 2: Find and Select a Model or Worksheet

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
  Tags (comma-separated):
```

Run the search using the CLI:

```bash
source ~/.zshenv && ts metadata search --profile {profile_name} \
  --subtype WORKSHEET \
  --name "%{name_keyword}%" \
  --all
```

Omit `--name` if no keyword was supplied. The `--all` flag auto-paginates.
`--subtype WORKSHEET` restricts results to worksheets and models only.

**Zero results fallback:** If the search returns zero results, retry without `--name`
and apply case-insensitive substring filtering against `metadata_name` client-side.

**Tags** are not directly supported as a CLI filter — if the user supplies tags,
run without `--name`, collect all results, and filter client-side by tag name
in each result's `metadata_header.tags[]`.

---

#### Option B — Browse All

```bash
source ~/.zshenv && ts metadata search --profile {profile_name} --subtype WORKSHEET --all
```

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

```bash
source ~/.zshenv && ts tml export {selected_model_id} --profile {profile_name} --fqn --associated
```

**Batch mode — export all models in one call:**

When the user has selected multiple models for conversion (e.g. "convert all BIRD_
models"), pass all GUIDs to a single export call:

```bash
source ~/.zshenv && ts tml export {guid_1} {guid_2} --profile {profile_name} --fqn --associated --parse
```

`--parse` returns structured JSON directly — non-printable character stripping and
YAML parsing are handled by the CLI. Separate by `type` field. Cache associated table
TMLs by GUID — if two models share a physical table, the TML is returned once and
should not be re-fetched for the second model.

Separate into:
- **Primary object:** parsed YAML has top-level key `worksheet` or `model`
- **Table objects:** parsed YAML has top-level key `table`
- **SQL view objects:** parsed YAML has top-level key `sql_view` — collect separately for handling in Step 5

---

### Step 4: Identify TML Format

| Top-level key | Format | Key difference |
|---|---|---|
| `worksheet` | Worksheet | Join conditions in Table TML; columns explicit in `worksheet_columns[]` |
| `model` | Model | Joins use `referencing_join` or inline `on`; columns derived from Table TML |

---

### Step 5: Resolve Physical Table Names

**`to_snake(name)` — used throughout this step and Step 7:**
Convert a display name to a valid Snowflake identifier:
1. Lowercase the string
2. Replace any run of non-alphanumeric characters with `_`
3. Strip leading/trailing underscores

```python
import re
def to_snake(name):
    s = re.sub(r'_+', '_', re.sub(r'[^a-z0-9]', '_', name.lower())).strip('_')
    if not s:
        s = 'field'
    elif s[0].isdigit():
        s = 'field_' + s
    return s
# Examples: "eye colour" → "eye_colour", "# of Products" → "of_products"
#           "1st Quarter" → "field_1st_quarter", "$" → "field"
```

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
never `"schema_"`. See [~/.claude/shared/schemas/thoughtspot-tml.md](~/.claude/shared/schemas/thoughtspot-tml.md) for details.

**Schema is reliably exported:** With `export_fqn: true` and `export_associated: true`,
the schema value is present in Table TML whenever it is set in ThoughtSpot. If it
appears missing, first verify with `tbl.keys()` — do not prompt the user until confirmed
genuinely absent.

If `db` or `schema` is confirmed absent after inspection, ask the user to provide them.
If a table has no associated TML, fetch it separately using its FQN GUID:
```bash
source ~/.zshenv && ts tml export {fqn_guid} --profile {profile_name} --fqn
```

Use `TODO_DATABASE` / `TODO_SCHEMA` placeholders for unresolved tables and flag them.

**SQL view resolution:** For every `sql_view` object referenced in `model_tables[]`
(or `table_paths[]` for Worksheet format), classify its `sql_query` using the logic
in [~/.claude/shared/schemas/thoughtspot-tml.md](~/.claude/shared/schemas/thoughtspot-tml.md):

*Simple* — `SELECT * FROM single_table [AS alias]`:
- Extract the physical FQN from the FROM clause
- Resolve `db`, `schema`, `db_table` from the FQN
- Borrow column types from the matching physical table TML (run `SHOW COLUMNS` if
  no matching table TML exists)
- Treat the sql_view as a regular table for all subsequent steps
- Note it in the Unmapped Properties Report under "SQL Views resolved automatically"

*Complex* — anything else (WHERE, column list, JOIN, aggregation, subquery, UNION):
- Do not attempt auto-resolution
- At the **Step 10 checkpoint**, present the sql_query to the user and ask:

  ```
  sql_view "{name}" uses SQL that cannot be auto-mapped to a single physical table:
    {sql_query}

  How should this be handled?
    C — Create a Snowflake VIEW from this SQL in the target schema, then reference it
    M — Map to an existing Snowflake table or view (you provide the name)
    S — Skip — omit all columns sourced from this view
  ```

  - **C (Create view):** Before executing the semantic view CREATE, run:
    ```sql
    CREATE OR REPLACE VIEW {target_db}.{target_schema}.{to_snake(sv_name)} AS
    {sql_query};
    ```
    Then run `SHOW COLUMNS IN VIEW {target_db}.{target_schema}.{view_name}` to get
    column types. Reference the new view as `base_table.table`.

  - **M (Map to existing):** Ask for the fully-qualified Snowflake object name.
    Run `SHOW COLUMNS` on it to get column types. Use as `base_table`.

  - **S (Skip):** Omit all model columns whose `column_id` references this sql_view.
    Log each omitted column in the Unmapped Properties Report under "SQL Views skipped".

**Case-sensitivity detection — connect to Snowflake now, before building the YAML:**

This step requires a live Snowflake connection. Select the Snowflake profile and
establish the connection now using the profile selection and auth logic described in
Step 12 — do not wait until Step 12 to do this. The quoting decisions made here
affect every `expr`, `base_table.schema`, and `base_table.table` value in the YAML.
When Step 12 is reached, skip profile selection (already done) and proceed directly
to target location selection.

**Schema case — infer directly from the TML, no Snowflake query needed:**

The `schema` field value exported by ThoughtSpot with `export_fqn: true` reflects
exactly how the identifier was stored. If it is lowercase, it is case-sensitive and
must be quoted:

```python
def is_cs(identifier):
    return identifier != identifier.upper()

# Example: "financial" → case-sensitive (quoted); "PUBLIC" → case-insensitive (bare)
cs_schema = is_cs(tbl.get("schema", ""))
schema_ref = f'"{schema}"' if cs_schema else schema
```

No `SHOW SCHEMAS` call is needed.

**Column case — use a single `INFORMATION_SCHEMA.COLUMNS` query per schema:**

Instead of running one `SHOW COLUMNS` per table (N round-trips), run a single
`INFORMATION_SCHEMA.COLUMNS` query that returns all columns for all tables at once.
`INFORMATION_SCHEMA` stores names as they were created, so lowercase = case-sensitive.

**Python connector (`method: python`):**
```python
table_names_sql = ", ".join(f"'{t.upper()}'" for t in all_physical_tables)
cur.execute(f"""
    SELECT table_name, column_name, data_type
    FROM {db}.INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema = '{schema.upper()}'
      AND table_name IN ({table_names_sql})
    ORDER BY table_name, ordinal_position
""")
cs_columns = {}   # phys_table → set of case-sensitive column names
col_types = {}    # (phys_table, col_name) → data_type

for table_name, col_name, data_type in cur.fetchall():
    cs_columns.setdefault(table_name, set())
    if col_name != col_name.upper():          # lowercase → case-sensitive
        cs_columns[table_name].add(col_name)
    col_types[(table_name, col_name)] = data_type
```

**Snowflake CLI (`method: cli`):**
```python
import subprocess, json

def snow_json(snow_cmd, cli_connection, query):
    r = subprocess.run(
        [snow_cmd, 'sql', '-c', cli_connection, '--format', 'json', '-q', query],
        capture_output=True, text=True
    )
    return json.loads(r.stdout)

table_names_sql = ", ".join(f"'{t.upper()}'" for t in all_physical_tables)
rows = snow_json(snow_cmd, cli_connection, f"""
    SELECT table_name, column_name, data_type
    FROM {db}.INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema = '{schema.upper()}'
      AND table_name IN ({table_names_sql})
    ORDER BY table_name, ordinal_position
""")

cs_columns = {}
col_types = {}
for r in rows:
    tbl_name = r['TABLE_NAME']
    col_name = r['COLUMN_NAME']
    cs_columns.setdefault(tbl_name, set())
    if col_name != col_name.upper():
        cs_columns[tbl_name].add(col_name)
    col_types[(tbl_name, col_name)] = r['DATA_TYPE']
```

**Note:** `INFORMATION_SCHEMA` stores schema names in uppercase for case-insensitive
schemas and lowercase for case-sensitive ones — use `schema.upper()` in the WHERE
clause when querying a case-insensitive schema; use the literal value when case-sensitive.
In practice, the `schema.upper()` form works for both because Snowflake normalises the
comparison.

**Rule:** lowercase column name in `INFORMATION_SCHEMA.COLUMNS` → the column is
case-sensitive (created with a quoted identifier).

Apply quoting as follows:

| Location | Case-insensitive (UPPERCASE) | Case-sensitive (lowercase) |
|---|---|---|
| `base_table.schema` | `schema: PUBLIC` | `schema: '"superhero"'` |
| `base_table.table` | `table: FACT_SALES` | `table: '"colour"'` |
| `expr` column | `expr: t.HEIGHT_CM` | `expr: t."height_cm"` |
| `primary_key.columns` | `- ID` | ⚠ see below |
| `relationship_columns` | `left_column: PRODUCT_ID` | ⚠ see below |

**`primary_key` and `relationship_columns` — Cortex Analyst conflict:**

There is no single YAML format that satisfies both tools for case-sensitive columns
in these two fields. `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` requires `'"id"'`;
Cortex Analyst rejects `'"id"'` with error 392700.

**If any `SHOW COLUMNS` result returns lowercase column names that are used as join
keys or primary keys, you MUST create uppercase wrapper views before generating the
YAML.** Do not proceed to Step 6 without resolving this:

```python
# Detect whether wrapper views are needed
needs_wrapper = any(
    cs_cols_map.get(phys['db_table'], set())   # any cs columns in join-key tables
    for phys in phys_map.values()
)
```

If `needs_wrapper` is True:
1. Create a new uppercase schema: `CREATE SCHEMA IF NOT EXISTS {db}.{TARGET_SCHEMA}_SV`
2. For each physical table, create a view that uppercases all column names:
   ```sql
   CREATE OR REPLACE VIEW {db}.{TARGET_SCHEMA}_SV.{TABLE_NAME} AS
   SELECT "col1" AS COL1, "col2" AS COL2, ...
   FROM {db}."{schema}"."{table}";
   ```
3. Update `phys_map` to point at the new schema and uppercase table/column names
4. All YAML identifiers will then be bare uppercase — no quoting needed anywhere

Execute these DDL statements using the same method as the column queries above.

**Python connector — run wrapper view DDL in parallel:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def exec_ddl(connection_factory, ddl):
    conn = connection_factory()
    conn.cursor().execute(ddl)
    conn.close()
    return ddl.split('\n')[0][:60]  # first line for progress output

ddl_list = [
    f"CREATE OR REPLACE VIEW {db}.{TARGET_SCHEMA}_SV.{VIEW_NAME} AS SELECT ...",
    # one entry per physical table
]

with ThreadPoolExecutor(max_workers=min(len(ddl_list), 8)) as pool:
    futures = {pool.submit(exec_ddl, connection_factory, d): d for d in ddl_list}
    for f in as_completed(futures):
        print(f"  Created: {f.result()}")
```

**Snowflake CLI — write all DDL to one file, execute in a single call:**
```python
with open("/tmp/sv_wrappers.sql", "w") as f:
    f.write(";\n".join(ddl_list) + ";")
subprocess.run([snow_cmd, 'sql', '-c', cli_connection, '-f', '/tmp/sv_wrappers.sql'],
               capture_output=True, text=True)
import os; os.remove("/tmp/sv_wrappers.sql")
```

See [~/.claude/skills/ts-profile-snowflake/SKILL.md](~/.claude/skills/ts-profile-snowflake/SKILL.md) for the
connection factory pattern and CLI file-based execution details.

See [~/.claude/shared/schemas/snowflake-schema.md](~/.claude/shared/schemas/snowflake-schema.md) — Known Snowflake Semantic View Limitations for full details.

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

**Relationship naming — collision avoidance:**

Generate the base name as `{left_table}_to_{right_table}`. If that name is already
taken by a previously emitted relationship (two different join paths between the same
table pair), append the left join column to disambiguate:

```python
base_name = f"{left_tbl}_to_{right_tbl}"
if base_name in used_rel_names:
    base_name = f"{left_tbl}_{to_snake(left_col)}_to_{right_tbl}"
used_rel_names.add(base_name)
```

Initialise `used_rel_names = set()` before the relationship loop.

For join type and cardinality mappings, see
[~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md).

---

### Step 7.5: Multi-Domain Analysis

**Trigger:** Run this step whenever `model_tables[]` contains ≥2 tables and Step 7 produced
at least one join. Skip (proceed to Step 8) if the model has 0 or 1 fact tables.

**Algorithm:**

**1. Build a directed join graph** from the joins resolved in Step 7:
- Nodes: every table in `model_tables[]`
- Directed edges: one edge per resolved join, pointing from the FK table (source —
  the table whose `joins[]` array declared the join) to the PK table (target)

**2. Identify fact tables and dimension tables:**
- **Fact table**: any table with ≥1 outbound edge (it appears as the source of at
  least one join)
- **Dimension table**: any table with zero outbound edges (only ever a join target)

**3. Check the fact-table count:**
- 0 or 1 fact table → skip this step. Proceed to Step 8 as normal.
- ≥2 fact tables → continue.

**4. For each fact table, traverse its reachable dimension set** via BFS through its
outbound joins. A dimension table is "reachable from fact F" if you can reach it by
following directed edges from F.

**5. Identify shared dimensions:** any dimension table reachable from 2+ distinct fact
roots. Dimensions reachable from only one fact belong exclusively to that domain.

**6. Present the domain map to the user:**

```
I detected {N} logical domains in this model:

  Domain 1 — {FACT_TABLE_ROOT}
    Fact tables:  {list}
    Dimensions:   {list; flag shared dims with "(shared)"}

  Domain 2 — {FACT_TABLE_ROOT}
    Fact tables:  {list}
    Dimensions:   {list; flag shared dims with "(shared)"}

  Shared dimensions (included in each view if you split): {list}

How would you like to proceed?
  SPLIT   — Create {N} separate Semantic Views (one per domain)
  SINGLE  — Create one combined Semantic View (current behaviour)
  CUSTOM  — I'll assign tables to groups manually
```

**7a. SINGLE:** Set `split_mode = False`. Proceed to Step 8 with no change in scope.

**7b. SPLIT:** Set `split_mode = True`. For each domain:
- `domain.tables` = fact table(s) + all reachable dimensions (including shared ones,
  duplicated into every domain that reaches them)
- `domain.joins` = all relationships where **both** left_table and right_table are in
  `domain.tables`
- Default `domain.sv_name` = `{model_name}_{snake_case(primary_fact_table)}`
  (e.g. model `sales_inventory`, fact `DM_ORDER` → `sales_inventory_dm_order`).
  User may rename at the Step 10 checkpoint.
- Proceed to Step 8 and run it **once per domain** in sequence.

**7c. CUSTOM:** Display a numbered list of all tables. User types group assignments,
for example: `1,2,3 → Group A; 4,5,6 → Group B`. Validate that each group forms a
connected subgraph (every table reachable from at least one other table in its group).
If a group is disconnected, ask the user to revise. Treat each group as a domain and
proceed as SPLIT.

**Cross-domain formula columns (split mode only):**

A formula whose expression references column IDs from tables in multiple domains cannot
be cleanly split. Assign it to the domain containing the **most** of its referenced
tables. Log it in the Unmapped Properties Report under a new section:

```
#### Cross-Domain Formulas (assigned to primary domain)
| Formula | Assigned To | References tables in |
|---|---|---|
| {name} | {domain_name} | {other_domain_name} |
```

---

### Step 8: Map Columns

**Split mode:** If `split_mode = True` (set in Step 7.5), run this entire step once per
domain. On each pass, restrict scope to the current domain:
- Only include columns whose `column_id` prefix (the `TABLE_NAME::` part) is a table
  in `domain.tables`
- Only use `domain.joins` as the relationship set (already scoped in Step 7.5)
- Use `domain.sv_name` as the output view name

If `split_mode = False`, run once with the full scope as normal.

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
   - If `DB_COLUMN_NAME` is case-sensitive (lowercase in `SHOW COLUMNS` output from
     Step 5), double-quote it: `table_name."column_name"`
   - Both rules may apply simultaneously: `table_name."date"` (reserved + lowercase)
6. Use `db_column_properties.data_type` for date/time classification. If the
   `col_types` map built in Step 5 (from `INFORMATION_SCHEMA.COLUMNS`) already
   has the data type for this column, prefer it — it comes directly from Snowflake
   and is authoritative. Fall back to `db_column_properties.data_type` from the
   Table TML only when `col_types` doesn't have an entry (e.g. a sql_view column).

**`connections.yaml` — do not consult proactively.** Only if Snowflake returns a
column-not-found error after execution should you check `connections.yaml`, where
`external_column` may override `db_column_name` for a given column:
```yaml
column:
- name: CATEGORY_ID           # = db_column_name in Table TML
  external_column: CATEGORY_ID  # = actual physical column in Snowflake (may differ)
```

**Output structure — DDL clauses:**

Accumulate four lists as you iterate columns: `tables_clause`, `relationships_clause`,
`dimensions_clause`, `metrics_clause`. Then emit them in order as the final DDL.

**`tables()` clause — primary key for join target tables:**

After building all relationships, identify every table that appears on the right side
of a relationship. That table's entry in `tables()` must declare its PK:
```sql
DB.SCHEMA.DM_ORDER primary key (ORDER_ID),
DB.SCHEMA.DM_ORDER_DETAIL,   -- no PK: left-side only, nothing joins to it
```

**`dimensions()` clause — all non-metric columns including dates and FK columns:**

Every column that is not a metric goes here — including date/timestamp columns (which
are distinguished as time_dimensions only in the CA extension JSON, not in the DDL).
Format: `TABLE.ALIAS as table_lower.PHYSICAL_COL [with synonyms=('display_name')]`

FK columns (join keys) must also appear in `dimensions()` so Cortex Analyst can
resolve relationships. Alias names must be globally unique across the entire view.

When FK and PK columns share the same physical name (e.g. `TRANS.ACCOUNT_ID →
ACCOUNT.ACCOUNT_ID`), they would collide as dimension aliases. Fix by renaming FK
columns in wrapper views with a table-specific prefix:

```sql
-- Wrapper view renames the FK to avoid alias collision
CREATE OR REPLACE VIEW DB.SCHEMA_SV.TRANS AS
SELECT "account_id" AS TRANS_ACCOUNT_ID, ...
FROM DB.SCHEMA.TRANS;

-- dimensions() entries — now globally unique
TRANS.TRANS_ACCOUNT_ID as trans.TRANS_ACCOUNT_ID,  -- FK dim
ACCOUNT.ACCOUNT_ID as account.ACCOUNT_ID,           -- PK dim

-- relationships() entry uses the renamed physical column
trans_to_account as TRANS(TRANS_ACCOUNT_ID) references ACCOUNT(ACCOUNT_ID)
```

When a physical table is aliased multiple times, create separate wrapper views for
each alias with distinct PK column names so each satisfies the unique-name requirement.

**`metrics()` clause — ordering matters:**

Metrics are evaluated in order. A metric that references another metric's alias (e.g.
a ratio `DIV0(tbl.amount, tbl.quantity)`) must appear **after** the metrics it
references. Always emit base aggregate metrics before derived/ratio metrics for the
same table.

**For each model column:**

1. If `formula_id` set → translate formula in Step 9; if untranslatable, omit the
   column and log it; do not include placeholder `expr` values
2. If `column_id` set → resolve physical column name as above
3. Classify as dimension / time_dimension / metric using the decision tree in
   [~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md)
4. Merge `ai_context` into `description` with prefix `[TS AI Context]` if present
5. Record unmapped properties (format_pattern, default_date_bucket, custom_order,
   data_panel_column_groups, geo_config) for the Unmapped Properties Report
6. Build the Snowflake field entry using the templates in
   [~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md](~/.claude/mappings/ts-snowflake/ts-to-snowflake-rules.md)
7. Append the field to the field list for its owning table

---

**TML temp file cleanup — do this now, before Step 9:**

The exported TML files contain sensitive schema metadata (table names, column
descriptions, join conditions, AI context). Delete them as soon as column mapping
is complete — they are not needed after this point:

```bash
rm -f /tmp/ts_tml_*.json
```

---

### Step 9: Translate Formulas

> **MANDATORY — read the reference before assessing any formula:**
> Open [~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md](~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
> and use its **Decision Flowchart** to classify every formula. Do **not** classify
> a formula as untranslatable based on function name recognition alone. Patterns
> that appear ThoughtSpot-specific have documented Snowflake equivalents — for example:
>
> | Looks untranslatable | Actually translatable as |
> |---|---|
> | `last_value(agg, query_groups(), {date_col})` | `SUM(col)` + `non_additive_dimensions` on the date table |
> | `sum(group_aggregate(sum(m), {attr}, query_filters()))` | Plain `SUM(m)` — outer sum + query_filters() simplifies |
> | `sum(group_aggregate(sum(m), query_groups(), query_filters()))` | Plain `SUM(m)` |
> | `safe_divide(sum(m), [NamedMetric])` where NamedMetric is same measure at coarser grain | `DIV0(tbl.metric, SUM(tbl.metric) OVER (PARTITION BY dim.COL))` — contribution ratio pattern |
>
> Consult the reference. Never reason from first principles about ThoughtSpot functions.

For each formula column (`formula_id` is set):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format (Worksheet uses
   `[path_id::col]`, Model uses `[TABLE::col]`)
3. Classify using the Decision Flowchart in the formula translation reference, then
   translate using the rules in that file
4. Handle nested references up to 3 levels deep

**Untranslatable formulas — omit entirely:**

For formulas confirmed untranslatable after consulting the reference, **do not emit
the column** in the YAML. Do NOT use `-- TODO`, `CAST(NULL AS TEXT)`, or any placeholder
`expr` — these cause Snowflake parse errors or silent failures.

Instead:
- Skip the column in the output YAML
- Add an entry to the Formula Translation Log in the Unmapped Properties Report:
  ```
  | {display_name} | OMITTED | {reason} | {original_expr} |
  ```

Confirmed untranslatable patterns (after checking the reference):
- `[parameter_name]` — ThoughtSpot runtime parameter (no SQL equivalent)
- `ts_first_day_of_week(...)`, `last_n_days(...)`, `last_value_in_period(...)` — period-scoped time intelligence with no Snowflake equivalent
- `first_value(...)` — `NON ADDITIVE BY` only supports last-value semantics
- `group_aggregate(...)` with any filter argument other than `query_filters()` — hardcoded/selective filters unsupported
- `group_aggregate(...)` with `query_groups() + {attr}` or `query_groups(attr1, attr2)` grouping
- `max/min/avg/count(group_aggregate(...))` — outer non-sum aggregate prevents simplification
- Hyperlink markup: `concat("{caption}", ..., "{/caption}", ...)` — ThoughtSpot display hint
- Any reference to a formula that is itself confirmed untranslatable (transitive)

---

### ⚑ Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

**Single mode (`split_mode = False`):** present the following three sections.

**Split mode (`split_mode = True`):** present one labelled block per domain (Domain 1,
Domain 2, …). Each block contains the three sections below for that domain. At the end,
show the combined prompt once covering all domains.

---

**1. Generated DDL** — full `CREATE OR REPLACE SEMANTIC VIEW` statement in a SQL code block.

*Split mode:* label each block — e.g. `### Domain 1 — sales_inventory_dm_order`.
Include the `domain.sv_name` as the view name; remind the user they may rename it before creating.

**2. Conversion Summary:**
```
- Tables:          {n}
- Relationships:   {n}
- Dimensions:      {n}  (across all tables)
- Time dimensions: {n}  (across all tables)
- Metrics:         {n}  ({n} translated formulas, {n} physical columns)
- Omitted columns: {n}  (untranslatable formulas — see Formula Translation Log)
```
*Split mode:* show per-domain counts, then a totals row.
If shared dimensions were duplicated, note: `Shared dimensions duplicated into each view:
{list} — updates to these must be applied to all {N} views.`

**3. Unmapped Properties Report** — use the format defined in
[~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md](~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md).
Include only sections that have entries. Common sections:
- Parameters not migrated
- Column groups not migrated
- AI Context merged into description
- Format patterns not migrated
- Default date buckets not migrated
- Formula Translation Log (all formulas, translated and untranslated)
- Cross-Domain Formulas (split mode only — if any exist)
- Other dropped properties

---

**Single mode prompt:**
```
Shall I create this Semantic View in Snowflake?
  YES  — proceed
  NO   — cancel
  EDIT — followed by changes to the YAML
  FILE — write the YAML to a file without creating it in Snowflake
```

**Split mode prompt:**
```
Shall I create all {N} Semantic Views in Snowflake?
  YES       — create all {N} views
  NO        — cancel
  EDIT {n}  — edit domain n's DDL before creating (e.g. EDIT 1)
  FILE      — write all {N} DDL files without creating them
```

If the user selects **NO**, stop. No cleanup needed — the CLI manages its own token cache.

If the user selects **FILE**, skip to [Step 12-FILE](#step-12-file-output-ddl-file-only-mode).

---

### Step 11: Validate

Run all checks from [~/.claude/shared/schemas/snowflake-schema.md](~/.claude/shared/schemas/snowflake-schema.md).
Report all failures together before retrying. Key checks:

- [ ] Every table referenced in `relationships()`, `dimensions()`, or `metrics()` appears in `tables()`
- [ ] Every table that is a relationship right-side has `primary key (COL)` in its `tables()` entry
- [ ] Every FK column used in a relationship left-side appears as a dimension alias in its table
- [ ] Dimension aliases are globally unique across the entire view (no two tables share an alias name)
- [ ] Metric expressions reference **metric aliases** for derived/ratio metrics — not nested `SUM()` calls: `DIV0(tbl.amount, tbl.quantity)` not `DIV0(SUM(tbl.LINE_TOTAL), SUM(tbl.QUANTITY))`
- [ ] Metrics that reference other metric aliases appear **after** those aliases in the `metrics()` clause
- [ ] `non additive by` metrics: modifier is `{TABLE}.{COL} {asc|desc} nulls last`, expression is `SUM(...)`, the TABLE is a joined date dimension
- [ ] Formula dimension expressions use `table_lower.ALIAS` references, not physical column names if those differ
- [ ] Reserved SQL words used as column names are double-quoted in expressions: `table."date"`, `table."schema"`
- [ ] CA extension JSON: every alias defined in `dimensions()` and `metrics()` appears in the correct category (`dimensions`, `time_dimensions`, or `metrics`) under its table; date columns go in `time_dimensions`
- [ ] CA extension JSON: every relationship name defined in `relationships()` appears in the `relationships[]` array
- [ ] Valid Snowflake identifiers for view name and all aliases: `^[A-Za-z_][A-Za-z0-9_]*$`
- [ ] No untranslatable formula placeholders anywhere in the DDL (`-- TODO`, `CAST(NULL AS TEXT)`, `NULL AS`)
- [ ] `comment=` value is a single-quoted SQL string — escape any embedded single quotes by doubling them

---

### Step 12-FILE: Output DDL file (file-only mode)

This path is used when the user selected **FILE** at the Step 10 checkpoint, explicitly
said "file only", or has no Snowflake access or `CREATE SEMANTIC VIEW` permission.

**Split mode:** repeat steps 1–3 for each domain in sequence, using `domain.sv_name` as
the filename. Report each file written before moving to the next domain.

**1. Determine the output filename:**

Use `{semantic_view_name}.sql`. If the current working directory contains a
`semantic-views/` or `output/` subdirectory, write there; otherwise write to the
current directory.

**2. Write the file:**

```python
from pathlib import Path
out_path = Path(f"{semantic_view_name}.sql")
out_path.write_text(sv_ddl_str, encoding="utf-8")
```

**3. Report:**

```
Semantic View DDL written to: {semantic_view_name}.sql

To create it in Snowflake when you have access:
  1. In Snowsight, open a worksheet, set context to {suggested_db}.{suggested_schema},
     and paste + run the contents of {semantic_view_name}.sql.

  2. Or via Snowflake CLI:
       snow sql -c {cli_connection} -f {semantic_view_name}.sql
```

Use the database and schema from the table map built in Step 5 as the suggested target
(or `YOUR_DATABASE.YOUR_SCHEMA` if ambiguous).

**4. Proceed to Step 13** (Generate Test Questions) — the test questions help the user
know what to verify once they create the view.

---

### Step 12: Execute

**Split mode:** run this entire step once per domain in sequence. Use `domain.sv_name`
as the view name for each iteration. If one domain fails, report the error and ask:
`Retry / Skip and continue with the remaining domains / Cancel all?` before proceeding.

**Target location** (skip if already confirmed by the user — e.g. they named a schema
earlier in the conversation):

Present the unique `(database, schema)` pairs from the table map as numbered options:

```
Where should the Semantic View be created?

  1. ANALYTICS.PUBLIC       (all 3 tables)
  E. Enter a different database and schema

Select (or press Enter for #1):
```

If the user selects E, ask for `target_database` and `target_schema` explicitly.

**Snowflake profile selection** (skip if already connected in Step 5):
1. Read `~/.claude/snowflake-profiles.json`
2. If multiple profiles: display a numbered list including each profile's `method`
   (`cli` / `python`) so the user can distinguish them; ask user to select
3. If one profile: show it (including method) and confirm
4. If no file: ask for connection details; offer to save profile for future use
5. If `method: python` and `private_key_passphrase_env` is set, read passphrase from that env var

**Role:** Use `default_role` from the profile if set; otherwise ask the user.

**Warehouse:** If not specified in the profile:
- Python: `SHOW WAREHOUSES` via `cur.execute()` — pick first non-suspended
- CLI: `snow sql -c {cli_connection} --format json -q "SHOW WAREHOUSES"` — pick first non-suspended

Use the connection method and patterns from
[~/.claude/skills/ts-profile-snowflake/SKILL.md](~/.claude/skills/ts-profile-snowflake/SKILL.md).

**Execute the CREATE — branch on `profile.method`:**

**`method: python`** — re-establish the connector (the Step 5 connection is closed by
this point) and execute the DDL:

```python
import snowflake.connector
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key, Encoding, PrivateFormat, NoEncryption)
from cryptography.hazmat.backends import default_backend
import os

# Rebuild connection from profile (same auth as Step 5)
pk_path = os.path.expanduser(profile["private_key_path"])
with open(pk_path, "rb") as f:
    pk_data = f.read()
passphrase = None
if profile.get("private_key_passphrase_env"):
    passphrase = os.environ.get(profile["private_key_passphrase_env"], "").encode() or None
private_key = load_pem_private_key(pk_data, password=passphrase, backend=default_backend())
pk_der = private_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())

conn = snowflake.connector.connect(
    account=profile["account"],
    user=profile["username"],
    private_key=pk_der,
    warehouse=warehouse,
    role=role,
    database=target_database,
    schema=target_schema
)
cur = conn.cursor()
try:
    cur.execute(sv_ddl)  # CREATE OR REPLACE SEMANTIC VIEW ... (USE statements not needed — set in connect())
    result = cur.fetchone()
    print(result[0] if result else "Created successfully")
except Exception as e:
    print(f"ERROR: {e}")
    raise
finally:
    cur.close()
    conn.close()
```

**`method: cli`** — write the DDL to a temp file and execute with `snow sql -f`:

```python
import subprocess, os

sql_script = (
    f"USE ROLE {role};\n"
    f"USE DATABASE {target_database};\n"
    f"USE SCHEMA {target_schema};\n"
    f"{sv_ddl};"
)
with open("/tmp/sv_create.sql", "w") as f:
    f.write(sql_script)

result = subprocess.run(
    [snow_cmd, "sql", "-c", cli_connection, "-f", "/tmp/sv_create.sql"],
    capture_output=True, text=True
)
os.remove("/tmp/sv_create.sql")

if result.returncode != 0:
    print(f"ERROR: {result.stderr or result.stdout}")
    raise RuntimeError(result.stderr)
print(result.stdout or "Created successfully")
```

**Notes:**
- `CREATE OR REPLACE SEMANTIC VIEW` is idempotent — no need to `DROP` first
- The `comment=` value is a single-quoted SQL string; escape embedded single quotes by doubling: `''`
- The `with extension (CA='...')` JSON uses double quotes internally — no escaping needed

On success: report the created view name and location.
On failure: show the full Snowflake error. Do not retry automatically — ask the user.

**Cleanup:**

No ThoughtSpot token cleanup needed — the CLI manages its own cache automatically.
If Snowflake temp files were written (e.g. `/tmp/sv_wrappers.sql`), remove them now.

---

### Step 12b: Verify Creation

After a successful `CREATE OR REPLACE SEMANTIC VIEW` execution, confirm the view
exists and is queryable before reporting success.

**Split mode:** run this step after each domain's CREATE call. After all domains are
verified, report a combined summary listing every view created.

**1. Confirm the view exists:**

```sql
SHOW SEMANTIC VIEWS LIKE '{semantic_view_name}' IN SCHEMA {target_database}.{target_schema};
```

Expected: exactly one row returned with `name = '{semantic_view_name}'`.

If zero rows returned: the stored procedure reported success but the view was not
created. Report this discrepancy verbatim — do not proceed to test questions.

**2. Spot-check — SELECT the first metric:**

```sql
SELECT {first_metric_name}
FROM {target_database}.{target_schema}.{semantic_view_name}
LIMIT 1;
```

Replace `{first_metric_name}` with the first entry in the `metrics:` list in the
generated YAML. If this returns an error, report it verbatim and do not silently skip.

Common errors at this stage and their causes:

| Error | Cause | Fix |
|---|---|---|
| `error 392700 "unknown field data_type"` | A metric has `data_type:` set | Remove `data_type` from all `metrics:` entries |
| `invalid column name "id"` | Lowercase case-sensitive column not wrapped in a view | Create uppercase wrapper view (Step 5 / Step 6) |
| `semantic view not found` | SHOW result name has different casing | Check exact `name:` value used in the YAML |
| `The fact entity … must be … lower granularity` | Bridge/junction table traversal hit | Use direct SQL instead; see Known Limitations in snowflake-schema.md |

**3. Report location:**

```
Semantic View created successfully.

  Name:    {semantic_view_name}
  Schema:  {target_database}.{target_schema}
  Tables:  {n} table(s), {m} metric(s)
```

After the spot-check passes, proceed to Step 13 (Generate Test Questions).

---

### Step 13: Generate Test Questions

After the view is successfully created, generate 5 natural language questions derived
from the semantic view. Use the actual metrics, dimensions, and time dimensions that
were mapped — not column names, but the synonym or alias values from the DDL.

**Split mode:** generate 5 questions per domain view, each labelled with the view name.
Include at least one question per domain that could NOT be answered by querying the
other domain's view alone — to demonstrate the value of the split and its scope.

**Question design — aim for variety:**

| Type | Example pattern |
|---|---|
| Simple aggregation | "What is the total {metric} ?" |
| Breakdown | "What is {metric} by {dimension} ?" |
| Time trend | "How has {metric} changed over {time_dimension} ?" |
| Ranking | "Which {dimension} has the highest {metric} ?" |
| Multi-table / filtered | "What is {metric} for {dimension value} broken down by {dimension from joined table} ?" |

Span multiple tables where possible to exercise the relationships. Keep phrasing
conversational — these are for testing, not production reports.

Present the questions as:

```
Test questions for {semantic_view_name}

1. {question}
2. {question}
3. {question}
4. {question}
5. {question}

───────────────────────────────────────────────
Snowflake Cortex Analyst
  In Snowsight: open Cortex Analyst, select the semantic view, and ask each question.

ThoughtSpot Spotter
  In your ThoughtSpot instance: open Spotter, select the original worksheet/model,
  and ask each question.

Claude Code
  Ask Claude directly — for example:
    "Using the {semantic_view_name} semantic view in {target_database}.{target_schema},
     {question}"
───────────────────────────────────────────────
```

**After completing a model — batch continuation:**

If the user originally requested multiple models and more remain, immediately offer
the next one without waiting to be asked:

```
✓ {semantic_view_name} created in {target_database}.{target_schema}

Next up: {next_model_name}
  Ready to convert? (Y / N):
```

If yes: go directly to Step 2 (model selection is already known — skip straight to
Step 3: Export TML). Reuse the ThoughtSpot profile, Snowflake profile, warehouse,
and role from this session. Do **not** re-run Step 1 profile prompts.

If no (or no more models remain): the session is complete. No ThoughtSpot token
cleanup needed — the CLI manages its own cache.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-04-24 | Initial versioned release |
