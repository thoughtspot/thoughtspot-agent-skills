---
name: ts-to-snowflake-sv
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
| [../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md) | Column classification, aggregation, join type, data type, and name generation lookup tables |
| [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | ThoughtSpot formula ↔ SQL translation rules (bidirectional) and untranslatable pattern handling |
| [../../shared/mappings/ts-snowflake/ts-snowflake-properties.md](../../shared/mappings/ts-snowflake/ts-snowflake-properties.md) | Full property coverage matrix, limitations, and Unmapped Report format |
| [../../shared/schemas/snowflake-schema.md](../../shared/schemas/snowflake-schema.md) | Snowflake Semantic View YAML schema, validation rules, and known limitations |
| [../../shared/worked-examples/snowflake/ts-to-snowflake.md](../../shared/worked-examples/snowflake/ts-to-snowflake.md) | End-to-end mapping example: Worksheet TML → Semantic View YAML |
| [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) | TML export parsing — non-printable chars, PyYAML pitfalls, object type identification |

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
[../../shared/mappings/ts-snowflake/ts-snowflake-properties.md](../../shared/mappings/ts-snowflake/ts-snowflake-properties.md).

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege
- Authentication configured — run `/ts-profile-setup` if you haven't already

**Quick auth decision:**
```
Can you log into ThoughtSpot in a browser (even via SSO)?
  YES → token_env   — get a token from Developer Playground (no admin needed)
  NO  → password_env or secret_key_env — see ts-profile-setup.md
```

### Snowflake

- Role with `CREATE SEMANTIC VIEW` on the target schema
- Connection configured — run `/snowflake-setup` if you haven't already
- Not sure where to start? → Python connector + password auth has the fewest setup steps

---

## Workflow

### SQL Call Batching (Minimise UI Confirmations)

**CRITICAL for Snowsight Workspaces:** Every `snowflake_sql_execute` call triggers a
UI confirmation prompt that the user must click. Minimise the number of separate SQL
calls by batching related statements together.

**Rules:**

1. **Combine independent queries into one call.** Use semicolons to separate multiple
   statements in a single `snowflake_sql_execute` invocation. For example, instead of
   12 separate `CREATE VIEW` calls, combine all into one multi-statement call:
   ```sql
   CREATE OR REPLACE VIEW A AS SELECT ...;
   CREATE OR REPLACE VIEW B AS SELECT ...;
   CREATE OR REPLACE VIEW C AS SELECT ...;
   ```

2. **Combine independent reads.** When you need to check stored procedures, get
   profiles, and detect schemas — batch them:
   ```sql
   SELECT PROCEDURE_NAME FROM SKILLS.INFORMATION_SCHEMA.PROCEDURES
   WHERE PROCEDURE_SCHEMA = 'PUBLIC'
     AND PROCEDURE_NAME IN ('TS_SEARCH_MODELS', 'TS_EXPORT_TML', 'TS_IMPORT_TML');

   SELECT NAME, BASE_URL, USERNAME, TOKEN_EXPIRES_AT FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES;
   ```

3. **Combine TML metadata extraction.** After storing TML in a temp table, extract
   model_tables, joins, columns, and table physical details in a single query using
   CTEs or UNION ALL rather than one query per aspect:
   ```sql
   -- All model metadata in one query
   SELECT 'model_tables' AS section, ... FROM ... 
   UNION ALL
   SELECT 'joins' AS section, ... FROM ...
   UNION ALL
   SELECT 'columns' AS section, ... FROM ...;
   ```

4. **Batch wrapper view DDL.** All `CREATE OR REPLACE VIEW` statements for wrapper
   views MUST be combined into a single multi-statement SQL call — never one call per
   view.

5. **Batch schema + column inspection.** Combine `SHOW SCHEMAS` and
   `INFORMATION_SCHEMA.COLUMNS` queries where possible.

6. **Combine dry-run with prerequisite DDL.** When dropping an existing semantic view
   before re-creating, combine the DROP + dry-run CALL in one statement.

**Target call budget per model:** Aim for **5–8 total SQL calls** per model conversion:

| Call | Purpose |
|---|---|
| 1 | Setup: check stored procedures + get profile |
| 2 | Search for models |
| 3 | Export TML + store in temp table |
| 4 | Extract all metadata (tables, joins, columns, table details) |
| 5 | Check Snowflake schemas + column case (INFORMATION_SCHEMA) |
| 6 | Create all wrapper views (one batched call) |
| 7 | Dry-run validation |
| 8 | Create semantic view |

For batch conversions of N models that share the same schema, calls 1, 2, and 5 are
only needed once — not per model.

---

**API method selection:**

The workflow calls the ThoughtSpot API in two places: Step 2 (search) and Step 3
(TML export). There are two ways to make these calls:

| Method | When to use |
|---|---|
| **Stored procedures** (preferred) | When `SKILLS.PUBLIC.TS_SEARCH_MODELS` and `SKILLS.PUBLIC.TS_EXPORT_TML` exist — installed via `/ts-sv-setup` |
| **Direct API** (fallback) | When the stored procedures do not exist (e.g. setup was not completed) — uses inline Python with `/tmp/ts_token.txt`. **Not available in Snowsight Workspaces** — requires CLI environment. |

**Auto-detect at the start of the workflow (batch with profile query):**

```sql
SELECT PROCEDURE_NAME FROM SKILLS.INFORMATION_SCHEMA.PROCEDURES
WHERE PROCEDURE_SCHEMA = 'PUBLIC'
  AND PROCEDURE_NAME IN ('TS_SEARCH_MODELS', 'TS_EXPORT_TML', 'TS_IMPORT_TML');

SELECT NAME, BASE_URL, USERNAME, TOKEN_EXPIRES_AT FROM SKILLS.PUBLIC.THOUGHTSPOT_PROFILES;
```

Run both in a **single** `snowflake_sql_execute` call to minimise UI prompts.
Parse the combined result to determine both `{api_method}` and `{profile_name}`.

**Check token expiry immediately:** if `TOKEN_EXPIRES_AT <= CURRENT_TIMESTAMP()` or is NULL,
stop and tell the user:
> "Your ThoughtSpot token has expired. Run `/ts-profile-setup` → U → Refresh token, then retry."
Do not proceed to Step 1 until the token is valid.

If `TS_SEARCH_MODELS` and `TS_EXPORT_TML` both appear in the result, set `{api_method}` = `stored_procedure`.
If either is missing, set `{api_method}` = `direct_api` and inform the user:

```
Stored procedures not found in SKILLS.PUBLIC. Run /ts-sv-setup to install them.
```

> **Snowsight Workspace:** If running in a Snowsight Workspace, STOP here and tell
> the user: "The stored procedures are required in Snowsight Workspaces. Please run
> `/ts-sv-setup` to install them." The direct API fallback uses `python3`
> and `curl` which are not available in this environment.

The `{api_method}` selection applies to both Step 2 and Step 3.

---

### Step 1: Authenticate

**When `{api_method}` = `stored_procedure`:**

Authentication is handled by the stored procedures themselves via the Snowflake
`EXTERNAL_ACCESS_INTEGRATIONS` and `SECRETS` configured during `/ts-profile-setup`.
Skip the token file workflow below — only profile selection is needed (to determine
which profile name to pass to the procedures).

**Profile name discovery (mandatory before any CALL):**

Use the profile rows already fetched in the auto-detect query above — do not query
the profiles table again. The `NAME` column is the exact profile name.

If one profile: use it directly (confirm with user).
If multiple: display a numbered list and ask the user to select.
Store the exact `NAME` value as `{profile_name}` for all subsequent
`CALL` statements — do not modify it.

**When `{api_method}` = `direct_api`:**

> **Snowsight Workspace limitation:** The direct API fallback uses `python3` and
> `curl` via the Bash tool, which are **not available** in Snowsight Workspaces.
> If the stored procedures are missing and you are in a Snowsight Workspace, inform
> the user they must run `/ts-profile-setup` first to create the stored procedures.
> Do not attempt direct API calls.

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
  Author (username or email):
  Tags (comma-separated):
```

**If `{api_method}` = `stored_procedure`:**

Use the `TS_SEARCH_MODELS` stored procedure:

```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS('{profile_name}', ARRAY_CONSTRUCT('{name_keyword}'), {owner_only});
```

Parameters:
- `profile_name`: the ThoughtSpot profile name selected in Step 1
- `ARRAY_CONSTRUCT('{name_keyword}')`: single-element array with the name keyword; pass `ARRAY_CONSTRUCT()` for browse-all
- `owner_only`: `TRUE` to filter to models owned by the profile's user, `FALSE` for all

When a single keyword is supplied the procedure applies `name_pattern` substring
matching server-side; results are already filtered to names containing the keyword.

Display the results as described in "Displaying Results" below.
If no results are returned, inform the user and offer to browse all or refine the search.

Note: The stored procedure supports name keyword and `owner_only` filtering. If the
user also wants to filter by tags, fall back to the direct API approach for that search
or apply tag filtering client-side on the stored procedure results.

**If `{api_method}` = `direct_api`:** *(CLI only — not available in Snowsight Workspaces)*

Build the request body from whichever fields are provided. All supplied filters
combine with AND semantics — results must satisfy every condition:

```
POST {base_url}/api/rest/2.0/metadata/search
{
  "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": "%{name_keyword}%"}],  // omit name_pattern if blank
  "created_by_user_identifiers": ["{author}"], // omit if blank; accepts username or GUID
  "tag_identifiers": ["{tag1}", "{tag2}"],     // omit if blank; accepts tag name or GUID
  "record_size": 50,
  "record_offset": 0
}
```

Paginate in increments of 50 until an empty page is returned before displaying results.

**Client-side filtering (mandatory — same as stored procedure method):** After
collecting all pages, apply case-insensitive substring filtering on model names
using the user's search keyword. Display only matching results.

**Zero results fallback (both methods):** If a name-only search returns zero results,
re-run with no name filter (or empty string for stored procedure), collect all
results, and apply case-insensitive substring matching against `metadata_name`
client-side. Present matches or offer to browse all.

---

#### Option B — Browse All

**If `{api_method}` = `stored_procedure`:**

```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS('{profile_name}', ARRAY_CONSTRUCT(), FALSE);
```

Filter the results to `type == 'WORKSHEET'` and display the full numbered list.

**If `{api_method}` = `direct_api`:** *(CLI only — not available in Snowsight Workspaces)*

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

**If `{api_method}` = `stored_procedure`:**

```sql
CALL SKILLS.PUBLIC.TS_EXPORT_TML('{profile_name}', ARRAY_CONSTRUCT('{selected_model_id}'));
```

For batch mode (multiple models):
```sql
CALL SKILLS.PUBLIC.TS_EXPORT_TML('{profile_name}', ARRAY_CONSTRUCT('{model_guid_1}', '{model_guid_2}'));
```

The procedure returns a VARIANT containing the exported TML data. Parse the result
and proceed to the separation logic below.

**If `{api_method}` = `direct_api`:** *(CLI only — not available in Snowsight Workspaces)*

```
POST {THOUGHTSPOT_BASE_URL}/api/rest/2.0/metadata/tml/export
{
  "metadata": [{"identifier": "{selected_model_id}"}],
  "export_fqn": true,
  "export_associated": true
}
```

**Batch mode — export all models in one call:**

When the user has selected multiple models for conversion (e.g. "convert all BIRD_
models"), export all their TMLs in a single request rather than one per model:

```json
{
  "metadata": [
    {"identifier": "{model_guid_1}"},
    {"identifier": "{model_guid_2}"}
  ],
  "export_fqn": true,
  "export_associated": true
}
```

**Processing (both methods):**

Separate the combined response by top-level key (`worksheet`/`model` = primary objects;
`table`/`sql_view` = associated objects). Cache associated table TMLs by GUID — if
two models share a physical table, the TML is returned once and should not be
re-fetched for the second model.

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
never `"schema_"`. See [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) for details.

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

**SQL view resolution:** For every `sql_view` object referenced in `model_tables[]`
(or `table_paths[]` for Worksheet format), classify its `sql_query` using the logic
in [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md):

*Simple* — `SELECT * FROM single_table [AS alias]`:
- Extract the physical FQN from the FROM clause
- Resolve `db`, `schema`, `db_table` from the FQN
- Borrow column types from the matching physical table TML or from the `col_types`
  map already built via `INFORMATION_SCHEMA.COLUMNS` — no additional query needed
  unless the physical table was genuinely absent from both
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

  - **C (Create view):** Collect all "C" views before executing any DDL. Batch the
    CREATE statements into a single SQL call (same pattern as wrapper views):
    ```sql
    CREATE OR REPLACE VIEW {target_db}.{target_schema}.{to_snake(sv_name_1)} AS {sql_query_1};
    CREATE OR REPLACE VIEW {target_db}.{target_schema}.{to_snake(sv_name_2)} AS {sql_query_2};
    ```
    After all views are created, resolve column types for all of them in **one** query:
    ```sql
    SELECT table_name, column_name, data_type
    FROM {target_db}.INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema = '{target_schema}'
      AND table_name IN ('{view_name_1}', '{view_name_2}', ...)
    ORDER BY table_name, ordinal_position;
    ```
    Reference each new view as `base_table.table`.

  - **M (Map to existing):** Collect all "M" mappings before querying. Resolve column
    types for all mapped objects in **one** `INFORMATION_SCHEMA.COLUMNS` query using
    the same pattern as above (filter by schema and `table_name IN (...)`). Use each
    as `base_table`.

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

**IMPORTANT — batch all wrapper DDL into one call:** Combine the `CREATE SCHEMA` and
all `CREATE OR REPLACE VIEW` statements into a **single** multi-statement SQL call.
This reduces N+1 UI confirmations to just 1:
```sql
CREATE SCHEMA IF NOT EXISTS {db}.{TARGET_SCHEMA}_SV;
CREATE OR REPLACE VIEW {db}.{TARGET_SCHEMA}_SV.TABLE_A AS SELECT ...;
CREATE OR REPLACE VIEW {db}.{TARGET_SCHEMA}_SV.TABLE_B AS SELECT ...;
CREATE OR REPLACE VIEW {db}.{TARGET_SCHEMA}_SV.TABLE_C AS SELECT ...;
```

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

See [../../shared/schemas/snowflake-schema.md](../../shared/schemas/snowflake-schema.md) — Known Snowflake Semantic View Limitations for full details.

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
[../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md).

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
  columns:
  - {PHYSICAL_COLUMN_NAME}
```

**Join key columns must be exposed as dimensions (Cortex Analyst requirement):**

Cortex Analyst validates that every column used in a relationship is exposed as a
**named dimension** in its table. It resolves join keys by dimension name using
`snake_case(physical_column)`. Dimension names must be globally unique.

This creates a conflict when FK and PK columns share the same name (e.g.
`TRANS.ACCOUNT_ID → ACCOUNT.ACCOUNT_ID`) — you cannot expose both as `account_id`.

**Fix: rename FK columns in wrapper views with a table-specific prefix**, then expose
them as uniquely-named dimensions:

```sql
-- Instead of: "account_id" AS ACCOUNT_ID
CREATE OR REPLACE VIEW TRANS AS
SELECT "account_id" AS TRANS_ACCOUNT_ID, ...  -- prefixed FK
FROM source.trans;
```

```yaml
# In the trans table entry — FK dimension
- name: trans_account_id       # unique name; snake_case(TRANS_ACCOUNT_ID)
  expr: trans.TRANS_ACCOUNT_ID
  data_type: NUMBER

# In the account table entry — PK dimension (unchanged)
- name: account_id
  expr: account.ACCOUNT_ID
  data_type: NUMBER

# Relationship uses the renamed physical column
- name: trans_to_account
  relationship_columns:
  - left_column: TRANS_ACCOUNT_ID   # renamed in wrapper view
    right_column: ACCOUNT_ID
```

When a physical table is aliased multiple times (e.g. a shared DISTRICT table used
as both `client_district` and `account_district`), create **separate wrapper views**
for each alias with a distinct PK column name (e.g. `CLIENT_DISTRICT_ID` vs
`ACCOUNT_DISTRICT_ID`) so each satisfies the unique-name requirement independently.

Also expose PK columns as dimensions — `primary_key` alone is not sufficient for
Cortex. The PK dimension name must equal `snake_case(pk_column)`. For example, if
the PK is `DISP_ID`, there must be a dimension named `disp_id`.

**For each model column:**

1. If `formula_id` set → translate formula in Step 9; if untranslatable, omit the
   column and log it; do not include placeholder `expr` values
2. If `column_id` set → resolve physical column name as above
3. Classify as dimension / time_dimension / metric using the decision tree in
   [../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md)
4. Merge `ai_context` into `description` with prefix `[TS AI Context]` if present
5. Record unmapped properties (format_pattern, default_date_bucket, custom_order,
   data_panel_column_groups, geo_config) for the Unmapped Properties Report
6. Build the Snowflake field entry using the templates in
   [../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md)
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

For each formula column (`formula_id` is set):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format (Worksheet uses
   `[path_id::col]`, Model uses `[TABLE::col]`)
3. Replace function names using
   [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
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
[../../shared/mappings/ts-snowflake/ts-snowflake-properties.md](../../shared/mappings/ts-snowflake/ts-snowflake-properties.md).
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

If the user selects **NO**, clean up and stop:
```bash
rm -f /tmp/ts_token.txt
```

---

### Step 11: Validate

Run all checks from [../../shared/schemas/snowflake-schema.md](../../shared/schemas/snowflake-schema.md).
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
- [ ] Valid `data_type` values on dimensions/time_dimensions: `TEXT`, `NUMBER`, `DATE`, `TIMESTAMP`, `BOOLEAN`. **Never on metrics** — causes Cortex error 392700.
- [ ] Every join key column (FK and PK) is exposed as a named dimension in its table, with name = `snake_case(physical_column)`
- [ ] No two tables in a relationship share a join column name — if they do, rename FK columns in wrapper views with a table-specific prefix

---

### Step 12: Execute

**Target location — suggest from source tables:**

Collect the unique `(database, schema)` pairs from the table map built in Step 5.
Present them as numbered options so the user can pick with a single keypress:

```
Where should the Semantic View be created?

  1. ANALYTICS.PUBLIC       (all 3 tables)
  E. Enter a different database and schema

Select (or press Enter for #1):
```

If the source tables span multiple databases or schemas, list each unique pair with
the tables that belong to it:

```
Where should the Semantic View be created?

  1. ANALYTICS.PUBLIC       (fact_sales, dim_product)
  2. ANALYTICS.STAGING      (dim_customer)
  E. Enter a different database and schema

Select (or press Enter for #1):
```

If the user selects E, ask for `target_database` and `target_schema` explicitly.

**Snowflake profile selection** (skip if already connected in Step 5):
1. Read `~/.claude/snowflake-profiles.json`
2. If multiple profiles: display a numbered list including each profile's `method`
   (`cli` / `python`) so the user can distinguish them at a glance; ask user to select
3. If one profile: show it (including method) and confirm
4. If no file: ask for connection details and whether to use the CLI or Python
   connector; offer to save profile for future use
5. If `method: python` and `private_key_passphrase_env` is set, read passphrase
   from that env var at runtime

**Role:** Use `default_role` from the profile if set; otherwise ask the user.

**Warehouse:** If not specified in the profile:
- Python: run `SHOW WAREHOUSES` via `cur.execute()` and pick the first non-suspended
- CLI: run `snow sql -c {cli_connection} --format json -q "SHOW WAREHOUSES"` and
  pick the first non-suspended warehouse from the JSON results

**Always run a dry-run first:**

```sql
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{yaml}
$$, TRUE);
```

If dry-run succeeds, combine the DROP (if needed) and CREATE into a **single** call:

```sql
DROP SEMANTIC VIEW IF EXISTS {target_database}.{target_schema}.{semantic_view_name};
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{yaml}
$$);
```

**Notes:**
- Use `CALL`, not `SELECT`
- First argument: fully-qualified target schema `'DATABASE.SCHEMA'`
  - If the target schema is case-sensitive (lowercase in `SHOW SCHEMAS` output),
    quote it: `'DATABASE."schema"'` — e.g. `'BIRD."superhero"'`
- Second argument: YAML content in `$$` dollar-quotes (safe for YAML with single quotes)
- Third argument `TRUE`: dry-run mode — validates without creating

On success: report the created view name and location.
On failure: show the full Snowflake error. Do not retry automatically — ask the user.

**If the view already exists:**
```sql
DROP SEMANTIC VIEW IF EXISTS {target_database}.{target_schema}.{semantic_view_name};
```
Then re-run the CREATE call.

**Cleanup (direct_api mode only — skip if using stored procedures):**
*(CLI only — not applicable in Snowsight Workspaces)*

- If **more models remain** in the current batch, preserve `/tmp/ts_token.txt` for
  the next iteration — do not delete it.
- Delete it only after the **last model** in the session is done (or if the user
  cancels the batch), whether the view was created successfully or not:
```bash
rm -f /tmp/ts_token.txt
```

---

### Step 13: Generate Test Questions

After the view is successfully created, generate 5 natural language questions derived
from the semantic view. Use the actual metrics, dimensions, and time dimensions that
were mapped — not column names, but the `name` or `label` values from the YAML.

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

If no (or no more models remain) and `{api_method}` = `direct_api` (CLI only):
```bash
rm -f /tmp/ts_token.txt
```
