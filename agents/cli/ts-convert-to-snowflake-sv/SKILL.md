---
name: ts-convert-to-snowflake-sv
description: Convert or export a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Use when ThoughtSpot is the source and the goal is a Snowflake Semantic View — whether converting metrics and formulas for Cortex Analyst access, generating CREATE SEMANTIC VIEW DDL, writing a .sql file for later execution, or updating an existing Snowflake SV from a changed model. Direction is always ThoughtSpot → Snowflake. Not for Snowflake → ThoughtSpot, standalone TML exports, or adding synonyms/AI context to ThoughtSpot models.
---

# ThoughtSpot → Snowflake Semantic View

Convert a ThoughtSpot Worksheet or Model into a Snowflake Semantic View. Searches
ThoughtSpot for available models, exports the TML definition, maps it to the Snowflake
Semantic View DDL format, and creates it via `CREATE OR REPLACE SEMANTIC VIEW`.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md) | Column classification, aggregation, join type, data type, and name generation lookup tables |
| [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | ThoughtSpot formula ↔ SQL translation rules (bidirectional) and untranslatable pattern handling |
| [../../shared/mappings/ts-snowflake/ts-snowflake-properties.md](../../shared/mappings/ts-snowflake/ts-snowflake-properties.md) | Full property coverage matrix, limitations, and Unmapped Report format |
| [../../shared/schemas/snowflake-schema.md](../../shared/schemas/snowflake-schema.md) | Snowflake Semantic View DDL syntax, validation rules, and known limitations |
| [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) | TML export parsing — non-printable chars, PyYAML pitfalls, object type identification |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML field reference — column types, data types, joins_with structure |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML field reference — model_tables, columns, formulas, join scenarios |
| [../../shared/worked-examples/snowflake/ts-to-snowflake.md](../../shared/worked-examples/snowflake/ts-to-snowflake.md) | End-to-end mapping example: Worksheet TML → Semantic View DDL |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| `/ts-profile-snowflake` | Snowflake connection profile setup — used with `ts snowflake exec` for SQL execution, and SHOW / INFORMATION_SCHEMA commands for case-sensitivity |

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
| Formula column — `last_value(sum(m), query_groups(), {date})` | `metrics()` with `non additive by (DATE_TABLE.COL asc nulls last)` modifier |
| Formula column — `first_value(sum(m), query_groups(), {date})` | `metrics()` with `non additive by (DATE_TABLE.COL desc nulls last)` modifier |
| Column / formula `properties.synonyms` (NOT top-level `synonyms`) | First synonym → `with synonyms=('First',...)`, all others appended. Top-level `synonyms:` is silently dropped on TS import; always read from `properties.synonyms`. |
| Column / formula `description` | `comment='...'` on the dimension or metric entry |
| Table-level `description` (Table TML) | `comment='...'` on the table entry in the `tables()` block |
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
[../../shared/mappings/ts-snowflake/ts-snowflake-properties.md](../../shared/mappings/ts-snowflake/ts-snowflake-properties.md).

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

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-to-snowflake-sv** — export a ThoughtSpot Worksheet or Model and create a matching Snowflake Semantic View.

Steps:
  1.    Authenticate (ThoughtSpot) ......................... auto
  1.5.  Choose session mode (A: single / B: split / C: update) . you choose
  2.    Find and select the model / worksheet .............. you choose
  3.    Export and parse the TML ........................... auto
  4–6.  Resolve physical tables + case sensitivity ......... auto
  7.    (Mode B only) Multi-domain analysis ................ you choose
  8.    Translate formulas ................................. auto
  9.    Build DDL via `ts snowflake build-sv` .............. auto
  9.5C. (Mode C only) Diff against existing SV + confirm changes . you confirm
 10.    Checkpoint — review DDL before Snowflake execution .. you confirm
 11.    Validate the generated DDL ......................... auto
 12.    CREATE OR REPLACE SEMANTIC VIEW in Snowflake ........ auto
 12b.   Verify creation .................................... auto
 13.    Generate example test questions ..................... auto

File-only mode: at Step 10, choose FILE instead of executing — generates a .sql file
for manual import in Snowsight.

Confirmation required: Step 10 (DDL review); Step 9.5C for Mode C
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If a ThoughtSpot profile was already confirmed earlier in
this conversation (e.g. for a previous model in a batch), skip profile selection
and reuse it.

**Profile selection (first model only):**

1. Run `ts profiles list` to show configured profiles.
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
ts auth whoami --profile {profile_name}
```

The CLI handles token caching, Keychain access, and expiry automatically.
No temp files or manual token management needed in this skill.

If `ts auth whoami` returns 401, the token is expired. Direct the user to
`/ts-profile-thoughtspot` (U3 — Refresh Credential) — that section is the canonical,
cross-platform refresh procedure. Then clear the stale cache and retry:

```bash
ts auth logout --profile {profile_name}
ts auth whoami --profile {profile_name}
```

---

### Step 1.5: Session Mode

```
Choose a conversion mode:
  A — Convert ThoughtSpot Model → new Snowflake Semantic View    (default)
  B — Split ThoughtSpot Model → MULTIPLE Snowflake Semantic Views
  C — Update an EXISTING Snowflake Semantic View from a changed Model
```

**Mode A** (or press Enter): set `session_mode = "single"`. Step 7 is skipped —
the skill produces one SV regardless of how many domains are detected.

**Mode B**: set `session_mode = "split"`. Step 7 runs automatically in SPLIT mode —
the SPLIT/SINGLE/CUSTOM choice prompt is suppressed since the user already chose here.

**Mode C**: set `session_mode = "update"`. After confirming the model in Step 2, also
ask for the existing SV to update:

```
Existing Snowflake Semantic View to update:
  Enter database.schema.view_name or press Enter to browse: _______
```

Store `{existing_sv_name}`. The skill runs Steps 2–9 as a DDL dry run, then
diverges at Step 9.5C (diff + review) before executing.

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
ts metadata search --profile {profile_name} \
  --subtype WORKSHEET \
  --name "%{name_keyword}%" \
  --all
```

Omit `--name` if no keyword was supplied. The `--all` flag auto-paginates.
`--subtype WORKSHEET` restricts results to worksheets and models only.

**Zero results fallback:** If the search returns zero results, retry without `--name`
and apply case-insensitive substring filtering against `metadata_name` client-side.

**Tags** are supported via `--tag <name-or-guid>` (repeatable). If the user
supplies tags, add `--tag "<tag_name>"` for each one.

---

#### Option B — Browse All

```bash
ts metadata search --profile {profile_name} --subtype WORKSHEET --all
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

**Mode C only:** run the following in parallel with the TML export to fetch the
existing SV DDL:

```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{existing_sv_name}');
```

Store the result as `{existing_sv_ddl}` — used in Step 9.5C.

```bash
ts tml export {selected_model_id} --profile {profile_name} --fqn --associated
```

**Batch mode — export all models in one call:**

When the user has selected multiple models for conversion (e.g. "convert all BIRD_
models"), pass all GUIDs to a single export call:

```bash
ts tml export {guid_1} {guid_2} --profile {profile_name} --fqn --associated --parse
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

**`to_snake(name)` — naming convention used by `ts snowflake build-sv`:**
Lowercase, replace non-alphanumeric chars with `_`, strip leading/trailing `_`.
Examples: `"eye colour"` → `eye_colour`, `"# of Products"` → `of_products`,
`"1st Quarter"` → `field_1st_quarter`. The wrapper view naming in this step
follows the same convention.

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
```bash
ts tml export {fqn_guid} --profile {profile_name} --fqn
```

Use `TODO_DATABASE` / `TODO_SCHEMA` placeholders for unresolved tables and flag them.

**SQL view resolution:** For every `sql_view` object referenced in `model_tables[]`
(or `table_paths[]` for Worksheet format), classify its `sql_query` using the logic
in [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md):

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

**Case-sensitivity detection — connect to Snowflake now, before building the DDL:**

This step requires a live Snowflake connection. Select the Snowflake profile and
establish the connection now using the profile selection and auth logic described in
Step 12 — do not wait until Step 12 to do this. The quoting decisions made here
affect every column reference and every `{DB}.{SCHEMA}.{TABLE}` entry in the
generated DDL.
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

**Note:** `INFORMATION_SCHEMA` predicates are literal string comparisons — they do NOT
normalise case. Query with the exact stored case. If the first probe returns zero rows,
retry with `UPPER(table_schema) = UPPER('{schema}')` to handle case-insensitive schemas
(stored uppercase) vs case-sensitive schemas (stored in original case).

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
DDL.** Do not proceed to Step 6 without resolving this:

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
4. All identifiers used in the DDL will then be bare uppercase — no quoting needed anywhere

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

See `/ts-profile-snowflake` for connection setup, and `ts snowflake exec` for
running SQL from a file without hand-rolling the connector/CLI calls above.

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

### Step 7: Multi-Domain Analysis

**Mode gate:**
- **Mode A** (`session_mode = "single"`) — skip this step entirely. Proceed to Step 8.
- **Mode C** (`session_mode = "update"`) — skip this step entirely. Proceed to Step 8.
- **Mode B** (`session_mode = "split"`) — run this step and enter SPLIT mode automatically.
  Set `split_mode = True` immediately; suppress the SPLIT/SINGLE/CUSTOM choice prompt
  since the user already chose Mode B at Step 1.5.

**Trigger (Mode B only):** Run whenever `model_tables[]` contains ≥2 tables and at
least one join exists. Skip (proceed to Step 8) if the model has 0 or 1 fact tables.

**Algorithm:**

**1. Build a directed join graph** from `model_tables[].joins[]`:
- Nodes: every table in `model_tables[]`
- Directed edges: one edge per join, pointing from the FK table (source —
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

### Step 8: Translate Formulas

> **MANDATORY — read the reference before assessing any formula:**
> Open [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
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

For each formula column (`formula_id` is set in `model.columns[]`):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format (Worksheet uses
   `[path_id::col]`, Model uses `[TABLE::col]`)
3. Classify using the Decision Flowchart in the formula translation reference, then
   translate using the rules in that file
4. Handle nested references up to 3 levels deep

Write the translated formulas to a JSON file for `ts snowflake build-sv`:

```json
{
  "formula_id_1": {"expr": "SUM(table.col)", "kind": "metric"},
  "formula_id_2": {"expr": "CONCAT(t.first, ' ', t.last)", "kind": "dimension"}
}
```

Each entry: `formula_id` (matching the `formulas[].id` in the TML) → `{expr, kind}`.
`kind` is `"metric"` or `"dimension"` based on the column's `properties.column_type`.
Untranslatable formulas are omitted from this file — `build-sv` skips any formula
column whose `formula_id` is not in the translated map and reports it as skipped.

**Confirmed untranslatable patterns:** do not maintain a static list here — the set of
untranslatable patterns evolves independently of this skill. Consult the "Untranslatable
Patterns", "Untranslatable LOD Patterns", and "Untranslatable Semi-Additive Patterns"
sections of
[ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
for the current, authoritative list before omitting any column.

---

### Step 9: Build Semantic View DDL (`ts snowflake build-sv`)

**Split mode:** If `split_mode = True` (set in Step 7), run this step once per domain.
For each domain, filter the exported Model TML to include only the domain's tables
in `model_tables[]` and only columns whose `column_id` prefix is in `domain.tables`.
Write the filtered TML to a separate JSON file before running `build-sv`.

**Model format — use `ts snowflake build-sv`:**

```bash
ts snowflake build-sv \
  --model {export_dir}/model.json \
  --tables-dir {export_dir}/ \
  --sv-name {target_database}.{target_schema}.{sv_name} \
  --output {sv_name}.sql \
  --formulas {formulas.json}
```

Omit `--formulas` if the model has no formula columns (or all formulas are
untranslatable).

**What `build-sv` handles** (codified in `sv_build_sv.py`):
- `column_id` resolution → physical column names via Table TML
- Column classification (dimension / time_dimension / metric) using data type and
  column_type properties
- Relationship parsing (`on` expressions) and naming with collision avoidance
- Aggregation mapping (SUM, COUNT, COUNT_DISTINCT, AVG, MIN, MAX, etc.)
- Metric topological ordering (derived metrics after their dependencies)
- Alias deduplication across the entire view
- Synonym and comment emission
- CA extension JSON generation (dimensions, time_dimensions, metrics per table)
- Full DDL assembly (`CREATE OR REPLACE SEMANTIC VIEW`)

The command writes the DDL to `--output` and prints a JSON summary to stdout:

```json
{
  "sv_name": "DB.SCHEMA.MY_SV",
  "ddl_file": "my_sv.sql",
  "dimensions": 12,
  "time_dimensions": 3,
  "metrics": 8,
  "relationship_count": 4,
  "skipped_formulas": 1,
  "dropped_join_attrs": 2,
  "unmapped_properties": 5
}
```

Capture this summary for the Step 10 conversion summary. Skipped formulas and
dropped join attributes are also reported on stderr.

**Worksheet format — `build-sv` does not yet support worksheet TML:**

If the exported TML is worksheet format (top-level key `worksheet`), `build-sv`
cannot process it. Follow the manual procedure:

1. Build a `path_id → table_alias` map from `worksheet.table_paths[]`
2. Resolve joins from Table TML `joins_with[]` entries
3. For each `worksheet_columns[]` entry, resolve `column_id` via the path map,
   classify as dimension/time_dimension/metric using
   [../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-to-snowflake-rules.md)
4. Assemble the DDL manually following the DDL Format Reference at the top of this file

**`connections.yaml` — do not consult proactively.** Only if Snowflake returns a
column-not-found error after execution should you check `connections.yaml`, where
`external_column` may override `db_column_name` for a given column.

**TML temp file cleanup — do this after build-sv completes:**

```bash
rm -f /tmp/ts_tml_*.json {formulas.json}
```

---

### Step 9.5C: Diff Against Existing SV — Mode C Only

**Skip this step for Modes A and B.** Run only when `session_mode = "update"`.

Parse the existing SV DDL (fetched in Step 3C) using the same logic as
[../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md)
to extract its current column set, expressions, and descriptions.

#### Compute the change set (`ts snowflake diff`)

The comparison itself (SQL-expression normalisation, new/removed/modified
detection) is now computed by **`ts snowflake diff`** (ts-cli v0.30.0+) — a
parser-based check, same rationale as the `ts tml lint` pre-import gate. Write
both column maps to temp JSON files shaped `{"expr": ..., "description": ...}`
per column (synonyms aren't tracked on the to-side, so omit that key):

```python
import json

def _cols_for_diff(cols: dict) -> dict:
    return {
        name: {"expr": data["expr"], "description": data.get("description", "")}
        for name, data in cols.items()
    }

with open("/tmp/ts_sv_diff_existing.json", "w") as f:
    json.dump(_cols_for_diff(existing_sv_parse["columns"]), f)
with open("/tmp/ts_sv_diff_generated.json", "w") as f:
    json.dump(_cols_for_diff(generated_sv["columns"]), f)
```

```bash
ts snowflake diff --current /tmp/ts_sv_diff_existing.json --new /tmp/ts_sv_diff_generated.json
rm -f /tmp/ts_sv_diff_*.json
```

Parse the printed `change_set` JSON from stdout:

```json
{
  "new_columns":           ["..."],
  "removed_columns":       ["..."],
  "modified_expressions":  [{"column": "...", "current": "...", "new": "..."}],
  "modified_descriptions": [{"column": "...", "current": "...", "new": "..."}],
  "modified_synonyms":     []
}
```

`modified_synonyms` will always be empty here since neither side supplies synonym
data — ignore that key. `removed_columns` still needs per-column user confirmation
(below); everything else is display-only input to the next section.

#### Present the diff and collect decisions

```
=== Change set for "{existing_sv_name}" ===

  ✚ New columns:              {N}   (will be added)
  ✖ Removed columns:          {M}   (confirm each — unchecked = keep in new SV)
  ~ Modified expressions:     {R}   (will be updated — review before confirming)
  ✏ Modified descriptions:    {P}   (will be updated automatically)
  = Unchanged columns:        {T}   (no change)
```

**Removed columns** — require per-column confirmation. Pre-fill all as unchecked (keep):

```
These columns are in the current SV but not in the updated Model.
Confirm removal from the SV? (unchecked = keep in the new SV DDL)

  [ ] {col_name}  — currently: {existing_expr}
  ...
```

Unchecked columns are re-added verbatim from the existing SV DDL — they are preserved
even if the Model no longer includes them.

**Modified expressions** — show old and new side-by-side. Require `YES / SKIP` per
column; do not bulk-apply.

Descriptions are applied automatically — no per-column confirmation needed.

Require the user to type `done` after reviewing before proceeding.

#### Build the final DDL

Assemble from the reviewed changes:
- All new columns (from generated DDL)
- All unchanged columns (from generated DDL)
- Confirmed-removed columns: omit
- Unchecked (kept) removed columns: carry forward from existing SV DDL verbatim
- Modified expressions confirmed `YES`: use generated DDL value
- Modified descriptions: use generated DDL value

Replace the `generated_sv_ddl` variable with this assembled DDL before Step 10.

---

### ⚑ Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

**Mode C:** show the assembled (diff-reviewed) DDL and a diff summary instead of the
full conversion summary. The prompt becomes:

```
Shall I apply these changes to {existing_sv_name} in Snowflake?
  ✚ {N} columns added, ✖ {M} removed, ~ {R} expressions updated, ✏ {P} descriptions updated

  YES  — proceed (CREATE OR REPLACE)
  NO   — cancel
  FILE — write the final DDL to a file without executing
```

---

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
[../../shared/mappings/ts-snowflake/ts-snowflake-properties.md](../../shared/mappings/ts-snowflake/ts-snowflake-properties.md).
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
  EDIT — followed by changes to the DDL
  FILE — write the DDL to a file without creating it in Snowflake
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

Run all checks from [../../shared/schemas/snowflake-schema.md](../../shared/schemas/snowflake-schema.md).

**Automated — `ts snowflake lint-ddl`:**

Six of this step's checks are deterministic structural checks with no semantic
judgment involved — **`ts snowflake lint-ddl`** (ts-cli v0.30.0+) codifies them
(BL-063 codification quick win), same rationale as the `ts tml lint` pre-import gate:

```bash
ts snowflake lint-ddl {file.sql}
```

Exit code is non-zero if any `error`-severity finding is present. Fix every
finding and re-lint before proceeding — do not create the view from a DDL that
fails this gate.

| Covered by `ts snowflake lint-ddl` | `check` slug |
|---|---|
| Every table referenced in `relationships()`, `dimensions()`, or `metrics()` appears in `tables()` | `undeclared-table` |
| Dimension/metric aliases are globally unique across the entire view (no two tables share an alias name) | `duplicate-alias` |
| Metrics that reference other metric aliases appear **after** those aliases in the `metrics()` clause | `metric-forward-reference` |
| Valid Snowflake identifiers for view name and all aliases: `^[A-Za-z_][A-Za-z0-9_]*$` | `identifier-format` |
| No `-- TODO` / `CAST(NULL AS TEXT)` placeholders anywhere in the DDL | `untranslatable-placeholder` |
| `comment=` value likely has an unescaped embedded single quote (warning — moderate-confidence heuristic) | `unescaped-comment-quote` |

**Still manual — semantic judgment, not codified:**

These require understanding aggregation intent, join cardinality, or a
reserved-word list broad enough to risk false positives on legitimate column
names — `ts snowflake lint-ddl` deliberately does not attempt them. Report all
failures together before retrying:

- [ ] Every table that is a relationship right-side has `primary key (COL)` in its `tables()` entry
- [ ] Every FK column used in a relationship left-side appears as a dimension alias in its table
- [ ] Metric expressions reference **metric aliases** for derived/ratio metrics — not nested `SUM()` calls: `DIV0(tbl.amount, tbl.quantity)` not `DIV0(SUM(tbl.LINE_TOTAL), SUM(tbl.QUANTITY))`
- [ ] LOD/window metrics (`group_sum` → `SUM(...) OVER (PARTITION BY ...)`): the windowed aggregate references a **defined base metric alias**, not a raw column — `SUM(tbl.total_quantity) OVER (...)` not `SUM(tbl.QUANTITY) OVER (...)` (the raw-column form is rejected with error 010256). PARTITION BY may use a dimension on a joined coarser entity; no denormalization needed
- [ ] `non additive by` metrics: modifier is `{TABLE}.{COL} {asc|desc} nulls last`, expression is `SUM(...)`, the TABLE is a joined date dimension
- [ ] Formula dimension expressions use `table_lower.ALIAS` references, not physical column names if those differ
- [ ] Reserved SQL words used as column names are double-quoted in expressions: `table."date"`, `table."schema"`
- [ ] CA extension JSON: every alias defined in `dimensions()` and `metrics()` appears in the correct category (`dimensions`, `time_dimensions`, or `metrics`) under its table; date columns go in `time_dimensions`
- [ ] CA extension JSON: every relationship name defined in `relationships()` appears in the `relationships[]` array
- [ ] No `NULL AS` placeholder anywhere in the DDL — not covered by the automated `untranslatable-placeholder` check (too prone to false-positives on legitimate `COALESCE(x, NULL) AS y`-style expressions to automate reliably)
- [ ] `comment=` value is a single-quoted SQL string — escape any embedded single quotes by doubling them (the automated check above is a moderate-confidence heuristic, not a guarantee — re-check by eye on anything it doesn't flag)

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

**Snowflake connection** (skip if already connected in Step 5):
Use the Snowflake profile configured via `/ts-profile-snowflake`. Execute SQL
via `ts snowflake exec --sf-profile {profile_name}`.

**Role:** Use the profile's default role; ask the user if they need a different one.

**Warehouse:** Use the profile's default warehouse.

**Execute the CREATE via `ts snowflake exec`:**

Write the context statements and the DDL to a file, then run it in one call.
Set the appropriate database and schema context first:

```sql
USE ROLE {role};
USE DATABASE {target_database};
USE SCHEMA {target_schema};
```

Then execute the `CREATE OR REPLACE SEMANTIC VIEW` DDL statement — via
`ts snowflake exec -f {file}.sql --sf-profile {profile_name} --role {role} --warehouse {warehouse}`.

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

Replace `{first_metric_name}` with the first entry in the `metrics (...)` clause in the
generated DDL. If this returns an error, report it verbatim and do not silently skip.

Common errors at this stage and their causes:

| Error | Cause | Fix |
|---|---|---|
| `error 392700 "unknown field data_type"` | Only reachable via the alternate `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` path — a metric has `data_type:` set. Not reachable from DDL, whose `metrics()` clause has no `data_type` field. | If using the YAML path, remove `data_type` from all `metrics:` entries |
| `invalid column name "id"` | Lowercase case-sensitive column not wrapped in a view | Create uppercase wrapper view (Step 5 / Step 6) |
| `semantic view not found` | SHOW result name has different casing | Check exact view name used in the DDL (`CREATE OR REPLACE SEMANTIC VIEW {name}`) |
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
| 1.4.0 | 2026-07-22 | Steps 7–9 rewired onto `ts snowflake build-sv`: relationship building, column classification, DDL assembly now deterministic CLI (model format). Formula translation (Step 8) reordered before build-sv. Inline `to_snake()` code block removed. Worksheet format retains manual DDL assembly path. (BL-063 phase 1b) |
| 1.3.2 | 2026-07-11 | Remove the dead `direct-api-auth.md` reference-table row (retired repo-wide — curl + `/tmp/ts_token.txt` fallback now prohibited by `ts-cli.md`/`security.md`, no step logic used it) (BL-109). |
| 1.3.1 | 2026-07-11 | Document `sql_view` → `base_table.definition:` (D-Direct) auto-map option; emission deferred to BL-031 (audit 13.4). |
| 1.3.0 | 2026-07-03 | Step 9.5C diff + Step 11 mechanical DDL checks now delegate to `ts snowflake diff` / `ts snowflake lint-ddl` (BL-063 quick wins); semantic checks remain manual. Prereq ts-cli v0.30.0. |
| 1.2.4 | 2026-07-03 | Replace the inline macOS-only Keychain token-refresh procedure with a pointer to `/ts-profile-thoughtspot` (U3 — Refresh Credential), the canonical cross-platform procedure (audit finding 11.4). |
| 1.2.3 | 2026-06-13 | Fix INFORMATION_SCHEMA case comparison (F12); add join-type drop reporting table to T-RULES. |
| 1.2.2 | 2026-06-02 | Add Step 11 checklist rule: LOD/window metrics must window over a defined base metric alias (not a raw column — rejected with error 010256); PARTITION BY may use a joined coarser dimension, no denormalization |
| 1.2.1 | 2026-05-11 | Add `source ~/.zshenv &&` prefix to bare `ts auth logout` in the error-recovery bash block |
| 1.2.0 | 2026-05-05 | Add A/B/C mode menu (Step 1.5): A=single new SV, B=split (now first-class), C=update existing SV; add Step 9.5C diff workflow for Mode C |
| 1.1.0 | 2026-04-24 | Add Step 0 session plan with confirmation gate |
| 1.0.0 | 2026-04-24 | Initial versioned release |
