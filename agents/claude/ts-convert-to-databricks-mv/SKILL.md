---
name: ts-convert-to-databricks-mv
description: Convert a ThoughtSpot Worksheet or Model into a Databricks Unity Catalog Metric View by exporting TML, mapping columns and joins, translating formulas, and creating the view via CREATE VIEW WITH METRICS LANGUAGE YAML.
---

# ThoughtSpot → Unity Catalog Metric View

Convert a ThoughtSpot Worksheet or Model into a Databricks Unity Catalog Metric View.
Searches ThoughtSpot for available models, exports the TML definition, maps columns
and join relationships to the UC Metric View YAML format, translates ThoughtSpot
formulas to Databricks SQL, and creates the view via
`CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML`.

---

## References

| File | Purpose |
|---|---|
| [~/.claude/mappings/ts-databricks/ts-to-databricks-mv-rules.md](~/.claude/mappings/ts-databricks/ts-to-databricks-mv-rules.md) | Column classification, source table identification, join tree construction, data type, name generation lookup tables |
| [~/.claude/mappings/ts-databricks/ts-databricks-formula-translation.md](~/.claude/mappings/ts-databricks/ts-databricks-formula-translation.md) | ThoughtSpot formula → Databricks SQL translation rules (and untranslatable pattern handling) |
| [~/.claude/mappings/ts-databricks/ts-databricks-properties.md](~/.claude/mappings/ts-databricks/ts-databricks-properties.md) | Full property coverage matrix, limitations, and Unmapped Report format |
| [~/.claude/shared/schemas/databricks-schema.md](~/.claude/shared/schemas/databricks-schema.md) | Unity Catalog Metric View YAML schema, validation rules, and known limitations |
| [~/.claude/shared/schemas/thoughtspot-tml.md](~/.claude/shared/schemas/thoughtspot-tml.md) | TML export parsing — non-printable chars, PyYAML pitfalls, object type identification |
| [~/.claude/shared/schemas/thoughtspot-table-tml.md](~/.claude/shared/schemas/thoughtspot-table-tml.md) | Table TML field reference — column types, data types, joins_with structure |
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | Model TML field reference — model_tables, columns, formulas, join scenarios |
| [~/.claude/skills/ts-setup-profile/SKILL.md](~/.claude/skills/ts-setup-profile/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| [~/.claude/skills/ts-setup-databricks-profile/SKILL.md](~/.claude/skills/ts-setup-databricks-profile/SKILL.md) | Databricks connection code, SQL execution patterns, token refresh |
| [./references/open-items.md](./references/open-items.md) | Unverified UC API behaviors with test scripts |

---

## Concept Mapping

| ThoughtSpot | Unity Catalog Metric View |
|---|---|
| Worksheet / Model | Metric View (`CREATE VIEW ... WITH METRICS LANGUAGE YAML`) |
| `ATTRIBUTE` column (non-date) | `dimensions[]` entry |
| `ATTRIBUTE` column (date/timestamp) | `dimensions[]` entry — UC has no separate `time_dimensions` |
| `MEASURE` column | `measures[]` entry with aggregate `expr` |
| Formula column (translatable aggregate) | `measures[]` entry with SQL `expr` |
| Formula column (translatable non-aggregate) | `dimensions[]` entry with SQL `expr` |
| Formula column (untranslatable) | **Omitted** — logged in Formula Translation Log |
| Fact/primary table | `source:` — fully-qualified `catalog.schema.table` |
| Dimension tables | `joins:[]` — nested hierarchy rooted at source |
| Join `on` condition | `on:` in join entry; `source.col = join_name.col` syntax |
| `synonyms[]` | `synonyms[]` |
| `description` / `ai_context` | `comment:` — merged with `[TS AI Context]` prefix |
| Display name | `display_name:` |

**Key structural difference from Snowflake:** UC Metric Views have one top-level `source:`
table and flat `dimensions:` / `measures:` arrays. There are no `tables[]` or
`relationships[]` — everything hangs off the join tree. All date columns go into
`dimensions:` (no `time_dimensions:` section). The keyword is `measures:`, not `metrics:`.

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege
- Authentication configured — run `/ts-setup-profile` if you haven't already

**Quick auth decision:**
```
Can you log into ThoughtSpot in a browser (even via SSO)?
  YES → token_env — get a token from Developer Playground (no admin needed)
  NO  → password_env or secret_key_env — see ts-setup-profile
```

### Databricks

- Databricks workspace with Unity Catalog enabled
- SQL warehouse running and accessible
- Personal Access Token (PAT) with `CREATE TABLE` privilege on the target schema
  (Unity Catalog `CREATE TABLE` covers metric views in UC-enabled workspaces)
- Connection configured — run `/ts-setup-databricks-profile` if you haven't already

**No Databricks access?** You can still run this skill in **file-only mode** — it generates
the Metric View YAML and writes it to a file you can create manually later. Select **FILE**
at the Step 10 checkpoint or say "file only" at any point before Step 12.

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If ThoughtSpot and Databricks profiles were already confirmed
earlier in this conversation (e.g. for a previous model in a batch), skip profile
selection and reuse them.

**ThoughtSpot profile (first model only):**

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

**Databricks profile (first model only):**

Read `~/.claude/databricks-profiles.json` and follow the same select-or-confirm pattern.
The Databricks profile is needed in Step 5 (to resolve physical table metadata) and Step 12
(to create the view). Select it now so the connection is confirmed before the long
translation steps.

Connect and confirm:

```python
import os, json
from pathlib import Path
from databricks import sql as dbsql

# Load selected profile
profile = {selected_databricks_profile}
token = os.environ.get(profile['token_env'], '')

conn = dbsql.connect(
    server_hostname=profile['hostname'],
    http_path=profile['http_path'],
    access_token=token
)
cursor = conn.cursor()
cursor.execute("SELECT current_user(), current_catalog()")
row = cursor.fetchone()
print(f"Databricks: {row[0]} @ {profile['hostname']}")
```

If the connection fails, see the error handling table in
[~/.claude/skills/ts-setup-databricks-profile/SKILL.md](~/.claude/skills/ts-setup-databricks-profile/SKILL.md).

---

### Step 2: Find and Select a Model or Worksheet

**Present the following options to the user:**
```
How would you like to find your model?
  G — I have a GUID
  S — Search (by name, author, tags, or a combination)
  B — Browse all
```

#### Option G — Direct GUID

If the user provides a GUID, skip search entirely. Store it as `{selected_model_id}`.
The model name will be confirmed from the TML export in Step 3.

#### Option S — Search

Ask the user which filters to apply:

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

**Zero results fallback:** If the search returns zero results, retry without `--name`
and apply case-insensitive substring filtering against `metadata_name` client-side.

**Tags** are not directly supported as a CLI filter — run without `--name`, collect all
results, and filter client-side by tag name in each result's `metadata_header.tags[]`.

#### Option B — Browse All

```bash
source ~/.zshenv && ts metadata search --profile {profile_name} --subtype WORKSHEET --all
```

#### Displaying Results

```
1. [WORKSHEET] Retail Sales WS            id: e61c7c4c-...
2. [WORKSHEET] TS: BI Server              id: eaab6de7-...
```

**API subtype note:** Both Worksheets and Models appear as `type: WORKSHEET` — there is
no separate `MODEL` subtype. The actual TML format (`worksheet` vs `model` top-level key)
is determined after export in Step 3.

Store `metadata_id` as `{selected_model_id}` and `metadata_name` as `{original_model_name}`.

---

### Step 3: Export the TML

```bash
source ~/.zshenv && ts tml export {selected_model_id} --profile {profile_name} --fqn --associated
```

**Batch mode — export all models in one call:**

When the user has selected multiple models, pass all GUIDs to a single export call:

```bash
source ~/.zshenv && ts tml export {guid_1} {guid_2} --profile {profile_name} --fqn --associated --parse
```

`--parse` returns structured JSON directly — non-printable character stripping and
YAML parsing are handled by the CLI. Cache associated table TMLs by GUID.

Separate into:
- **Primary object:** parsed YAML has top-level key `worksheet` or `model`
- **Table objects:** parsed YAML has top-level key `table`
- **SQL view objects:** parsed YAML has top-level key `sql_view` — collect separately

---

### Step 4: Identify TML Format

| Top-level key | Format | Key difference |
|---|---|---|
| `worksheet` | Worksheet | Joins in Table TML `joins_with[]`; columns explicit in `worksheet_columns[]` |
| `model` | Model | Joins use `referencing_join` or inline `on`; columns derived from Table TML |

---

### Step 5: Resolve Physical Table Names and Column Metadata

**`to_snake(name)` — used throughout:**
```python
import re
def to_snake(name):
    s = re.sub(r'_+', '_', re.sub(r'[^a-z0-9]', '_', name.lower())).strip('_')
    if not s:            s = 'field'
    elif s[0].isdigit(): s = 'field_' + s
    return s
```

Build a map: `logical_table_name → { catalog, schema, physical_table }`.

From each Table TML object:
```yaml
table:
  name: fact_sales       # map key (logical name)
  db: ANALYTICS          # → catalog in Databricks
  schema: PUBLIC
  db_table: FACT_SALES
```

**Note:** In ThoughtSpot's `db` field maps to the Databricks `catalog`. The `schema`
maps to the Databricks schema.

**PyYAML field name:** The schema field is `"schema"` in Python dicts after parsing.

If `db` or `schema` is absent after inspection, ask the user to provide them.
Use `TODO_CATALOG` / `TODO_SCHEMA` placeholders for unresolved tables and flag them.

**SQL view resolution:** For `sql_view` objects, classify the `sql_query`:

*Simple* — `SELECT * FROM single_table [AS alias]`:
- Extract the physical FQN from the FROM clause
- Resolve `catalog`, `schema`, `db_table`
- Treat the sql_view as a regular table for all subsequent steps
- Note it in the Unmapped Properties Report under "SQL Views resolved automatically"

*Complex* — anything else (WHERE, column list, JOIN, aggregation, subquery, UNION):
- At the **Step 10 checkpoint**, present the sql_query to the user and ask:

  ```
  sql_view "{name}" uses SQL that cannot be auto-mapped to a single physical table:
    {sql_query}

  How should this be handled?
    C — Create a Databricks VIEW from this SQL in the target schema, then reference it
    M — Map to an existing table or view (you provide the fully-qualified name)
    S — Skip — omit all columns sourced from this view
  ```

**Column metadata — connect to Databricks and run DESCRIBE TABLE:**

The Databricks connection was established in Step 1. Use it now to fetch column types
for all physical tables in one batch.

```python
col_types = {}   # (catalog, schema, table_name, col_name) → data_type

for table_name, phys in phys_map.items():
    cat, sch, tbl = phys['catalog'], phys['schema'], phys['db_table']
    cursor.execute(f"DESCRIBE TABLE `{cat}`.`{sch}`.`{tbl}`")
    rows = cursor.fetchall()
    for row in rows:
        col_name = row['col_name']
        if col_name.startswith('#') or col_name == '':
            continue   # skip partition info rows
        col_types[(cat, sch, tbl, col_name)] = row['data_type']
```

If a table is not found (does not exist in the catalog), note it in the Unmapped Report
and flag for user review. Do not halt — use data types from the Table TML as fallback.

**Databricks identifier quoting:** Databricks SQL is case-insensitive and identifiers
do not require quoting unless they:
- Contain reserved words (`date`, `order`, `name`, etc.)
- Contain spaces or special characters

Use backtick quoting for those cases. No wrapper views are needed (unlike Snowflake).

---

### Step 6: Build Path → Table Map (Worksheet format only)

Skip for Model format.

From `worksheet.table_paths[]`, build: `path_id → table_alias`.

```yaml
table_paths:
- id: fact_sales_1    # path_id used in column_id references
  table: fact_sales   # resolves to this logical table name
```

---

### Step 7: Identify Source Table and Build Join Tree

This step is unique to UC's `source:` + nested `joins:` structure.

**Identify the source (fact) table:**

Follow the source table identification algorithm in
[~/.claude/mappings/ts-databricks/ts-to-databricks-mv-rules.md](~/.claude/mappings/ts-databricks/ts-to-databricks-mv-rules.md).

If the model has no joins (single table), that table is trivially the source.

**Build the join tree:**

Follow the join tree construction algorithm in the rules reference. The output is a
nested list of join entries matching the UC `joins:` YAML structure.

**Join `on` clause construction:**

For each join condition `[LEFT_TABLE::LEFT_COL] = [RIGHT_TABLE::RIGHT_COL]`:

1. Resolve `LEFT_TABLE` → physical column name (`left_phys_col`)
2. Resolve `RIGHT_TABLE` → physical column name (`right_phys_col`)
3. Determine parent context:
   - If `LEFT_TABLE` is the source table: parent ref = `source`
   - If `LEFT_TABLE` is a joined table: parent ref = `to_snake(LEFT_TABLE)`
4. Emit: `on: {parent_ref}.{left_phys_col} = {to_snake(RIGHT_TABLE)}.{right_phys_col}`

**Model format — two join patterns:**

*Inline `on`:*
```yaml
joins:
- with: DM_LOCALE_COUNTRY
  "on": "[DM_CUSTOMER::COUNTRY] = [DM_LOCALE_COUNTRY::COUNTRY_KEY]"
```

*`referencing_join`:*
```yaml
joins:
- with: DM_CUSTOMER
  referencing_join: DM_ORDER_to_DM_CUSTOMER
```
Search all Table TML `joins_with[]` for `name: DM_ORDER_to_DM_CUSTOMER`.

**Parse `on` condition:** regex `\[([^\]:]+)::([^\]]+)\]\s*=\s*\[([^\]:]+)::([^\]]+)\]`
→ left_table, left_column, right_table, right_column.

**Scope filter — Model format only:** Only emit joins where both `left_table` and
`right_table` are in `model_tables[]`. Skip joins that reference tables outside the model.

**Multi-column join conditions** (`AND`): emit all conditions on one `on:` line:
`on: source.k1 = dim.k1 AND source.k2 = dim.k2`

**Model format — table aliases:**
```yaml
model_tables:
- name: colour
  alias: eye colour      # ← identifier used in column_id references
- name: colour
  alias: hair colour
```
When `alias` is present:
- Use `to_snake(alias)` as the UC join `name` (e.g. `eye_colour`)
- Use the physical `db_table` as the join `source:` table
- Build `alias_to_join_name` map for column_id resolution

---

### Step 8: Map Columns

**Source of truth — hierarchy:**

| Layer | Used for |
|---|---|
| `model.columns[]` | All field definitions — name, description, type, aggregation, synonyms, ai_context, formula_id, column_id |
| Table TML `columns[]` | Resolving `column_id` → `db_column_name` and `db_column_properties.data_type` |
| Table TML root (`db`, `schema`, `db_table`) | Physical table location |
| `col_types` from Step 5 | Authoritative Databricks data type (preferred over Table TML) |

**Column ID resolution:**

`column_id` format: `TABLE_NAME::LOGICAL_COLUMN_NAME`

1. Split on `::` → `table_name`, `logical_col_name`
2. Find the Table TML for `table_name`
3. Find the column in Table TML `columns[]` where `name == logical_col_name`
4. That column's `db_column_name` is the physical column name
5. Determine if `table_name` is the source table or a joined table:
   - Source table: `expr` = `{db_column_name}` (bare)
   - Joined table: `expr` = `{join_alias}.{db_column_name}`
6. If column name is a Databricks SQL reserved word, backtick-quote it:
   - Source: `` expr = f"`{db_column_name}`" ``
   - Joined: `` expr = f"{join_alias}.`{db_column_name}`" ``

**Classify each column as `dimensions` or `measures`:**

Follow the classification decision tree in the rules reference:
- `formula_id` set → Step 9 (formula translation)
- `column_type == MEASURE` → `measures`
- All others → `dimensions` (including date/timestamp columns)

**Build dimension entry:**
```python
entry = {
    'name': to_snake(column['name']),
    'expr': expr,
    'display_name': column['name'],   # original display name
}
if column.get('synonyms'):
    entry['synonyms'] = column['synonyms']
if column.get('description') or column.get('ai_context'):
    parts = []
    if column.get('description'):   parts.append(column['description'])
    if column.get('ai_context'):    parts.append(f"[TS AI Context] {column['ai_context']}")
    entry['comment'] = '\n'.join(parts)
```

**Build measure entry:**
```python
agg_map = {'SUM': 'SUM', 'COUNT': 'COUNT', 'COUNT_DISTINCT': 'COUNT(DISTINCT',
           'AVG': 'AVG', 'AVERAGE': 'AVG', 'MIN': 'MIN', 'MAX': 'MAX',
           'STD_DEVIATION': 'STDDEV', 'VARIANCE': 'VARIANCE'}

agg = column.get('aggregation', 'SUM')
if agg == 'COUNT_DISTINCT':
    measure_expr = f"COUNT(DISTINCT {base_expr})"
else:
    func = agg_map.get(agg, 'SUM')
    measure_expr = f"{func}({base_expr})"

entry = {'name': to_snake(column['name']), 'expr': measure_expr, 'display_name': column['name']}
```

**Record unmapped properties** (format_pattern, default_date_bucket, custom_order,
data_panel_column_groups, geo_config) for the Unmapped Properties Report.

**TML temp file cleanup — do this now, before Step 9:**

```bash
rm -f /tmp/ts_tml_*.json
```

---

### Step 9: Translate Formulas

> **MANDATORY — read the reference before assessing any formula:**
> Open [~/.claude/mappings/ts-databricks/ts-databricks-formula-translation.md](~/.claude/mappings/ts-databricks/ts-databricks-formula-translation.md)
> and use its **Translation Decision Flowchart** to classify every formula. Do **not**
> classify a formula as untranslatable based on function name recognition alone.
>
> | Looks untranslatable | Actually translatable as |
> |---|---|
> | `sum(group_aggregate(sum(m), query_groups(), query_filters()))` | Plain `SUM(m)` — simplifies |
> | `safe_divide(sum(a), sum(b))` | `try_divide(SUM(a), SUM(b))` |
> | `last_value(agg, query_groups(), {date_col})` | Window measure with `semiadditive: last` |
> | `moving_sum([m], 3, 1)` | Window measure with `range: trailing 3 month` |
> | `cumulative_sum([m])` | Window measure with `range: cumulative` |
> | `sum(if([status]='x', [m], 0))` | `SUM(m) FILTER (WHERE status = 'x')` |

For each formula column (`formula_id` is set):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format
   (Worksheet: `[path_id::col]`, Model: `[TABLE::col]`)
3. Classify using the Decision Flowchart in the formula translation reference
4. Handle nested references up to 3 levels deep

**Window measures — special handling:**

When a formula translates to a UC window measure (moving, cumulative, semi-additive),
the output is NOT just an `expr` string but a measure entry with a `window:` config block.
Record which dimension name to use as the `order:` field:
- Identify the time column referenced in the formula (e.g. the `{date_col}` in `last_value`)
- Map it to the dimension `name` generated in Step 8 for that column
- Use that name as `window.order`

```yaml
- name: balance_end_of_month
  expr: SUM(balance_amount)
  display_name: "Balance End of Month"
  window:
    - order: snapshot_month    # name of the date dimension in this view
      range: current
      semiadditive: last
```

**Composed measures — prefer `MEASURE()` when referencing other defined measures:**

If the formula references another model column that translates to a measure already in
the output YAML, use `MEASURE(measure_name)` rather than inlining the SQL:

```yaml
# Better: composed
- name: revenue_per_order
  expr: "try_divide(MEASURE(total_revenue), MEASURE(order_count))"

# Acceptable: inline (when constituent measures are not separately exposed)
- name: revenue_per_order
  expr: "try_divide(SUM(revenue_col), COUNT(order_id))"
```

**Untranslatable formulas — omit entirely:**

For formulas confirmed untranslatable after consulting the reference, **do not emit
the column**. Do NOT use `-- TODO`, placeholder `expr`, or `NULL`.

Instead:
- Skip the column in the output YAML
- Add to the Formula Translation Log in the Unmapped Report:
  ```
  | {display_name} | OMITTED | {reason} | {original_expr} |
  ```

---

### ⚑ Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

Present the following three sections:

**1. Generated YAML** — full content in a code block.

**2. Conversion Summary:**
```
- Source table:    {catalog}.{schema}.{fact_table}
- Joins:           {n}  (across {depth} levels)
- Dimensions:      {n}  (including {n_date} date/timestamp columns)
- Measures:        {n}  ({n_formula} translated formulas, {n_physical} physical columns, {n_window} window measures)
- Omitted columns: {n}  (untranslatable formulas — see Formula Translation Log)
```

**3. Unmapped Properties Report** — use the format defined in
[~/.claude/mappings/ts-databricks/ts-databricks-properties.md](~/.claude/mappings/ts-databricks/ts-databricks-properties.md).
Include only sections that have entries.

Then ask:
```
Shall I create this Metric View in Databricks?
  YES  — proceed
  NO   — cancel
  EDIT — followed by changes to the YAML
  FILE — write the YAML to a file without creating it in Databricks
```

If the user selects **NO**, stop. No cleanup needed — the CLI manages its own token cache.

If the user selects **FILE**, skip to [Step 12-FILE](#step-12-file-output-yaml-file-only-mode).

---

### Step 11: Validate

Run all checks from [~/.claude/shared/schemas/databricks-schema.md](~/.claude/shared/schemas/databricks-schema.md).
Report all failures together before retrying. Key checks:

- [ ] `version: "1.1"` is present at the top level
- [ ] `source:` is present and fully-qualified (`catalog.schema.table`)
- [ ] At least one of `dimensions:` or `measures:` is present
- [ ] Field names unique across all `dimensions` and `measures`
- [ ] Keyword is `measures` not `metrics` anywhere in the YAML
- [ ] All join `name` values are unique within the metric view
- [ ] Top-level join `on:` values use `source.col = join_name.col` (not bare table name)
- [ ] Nested join `on:` values use `parent_join_name.col = nested_join_name.col`
- [ ] All `join_alias.col` references in `expr` match a join `name` in the `joins:` array
- [ ] All `MEASURE(name)` references match a `measures:` entry in the same view
- [ ] All `window.order` values match a `dimensions:` entry `name`
- [ ] Reserved word column names are backtick-quoted in `expr`
- [ ] No `data_type:` on `measures:` entries — UC infers types
- [ ] No `tables:`, `relationships:`, `time_dimensions:`, `primary_key:` fields (Snowflake-only)
- [ ] No untranslatable formula placeholders in `expr`

---

### Step 12-FILE: Output YAML file (file-only mode)

This path is used when the user selected **FILE** at the Step 10 checkpoint, explicitly
said "file only", or has no Databricks access or `CREATE TABLE` permission.

**1. Determine the output filename:**

Use `{view_name}.yaml` (the `to_snake()` of the model name). If the current working
directory contains a `metric-views/` or `output/` subdirectory, write there; otherwise
write to the current directory.

**2. Write the file:**

```python
from pathlib import Path
out_path = Path(f"{view_name}.yaml")
out_path.write_text(yaml_content, encoding="utf-8")
```

**3. Report:**

```
Metric View YAML written to: {view_name}.yaml

To create it in Databricks when you have access, run in a Notebook or SQL editor:

  CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`{view_name}`
  WITH METRICS
  LANGUAGE YAML
  AS $$
  <paste YAML content here>
  $$;

Or pass the file to the Databricks CLI:
  databricks sql execute --warehouse-id {warehouse_id} \
    --statement "$(cat {view_name}.yaml | python3 -c '
      import sys
      yaml = sys.stdin.read()
      print(f\"CREATE OR REPLACE VIEW \`{catalog}\`.\`{schema}\`.\`{view_name}\` WITH METRICS LANGUAGE YAML AS \$\${yaml}\$\$\")
    ')"
```

**4. Proceed to Step 13** — test questions help the user verify once they create the view.

---

### Step 12: Execute

**Target location — suggest from source tables:**

Collect the unique `(catalog, schema)` pairs from the table map built in Step 5.
Present as numbered options:

```
Where should the Metric View be created?

  1. analytics.public       (all 3 tables)
  E. Enter a different catalog and schema

Select (or press Enter for #1):
```

If the source tables span multiple catalogs or schemas, list each unique pair with
the tables that belong to it.

**Databricks connection** was established in Step 1. Use the same connection now.
Set the default catalog and schema if needed:

```python
cursor.execute(f"USE CATALOG `{target_catalog}`")
cursor.execute(f"USE SCHEMA `{target_schema}`")
```

**Build and execute the CREATE VIEW DDL:**

```python
view_ddl = f"""CREATE OR REPLACE VIEW `{target_catalog}`.`{target_schema}`.`{view_name}`
WITH METRICS
LANGUAGE YAML
AS $$
{yaml_content}
$$"""

try:
    cursor.execute(view_ddl)
    print("View created.")
except Exception as e:
    print(f"ERROR: {e}")
```

**No dry-run mode exists in UC.** The CREATE VIEW either succeeds or raises an exception
with an error message. If the DDL fails, the Step 11 validation checklist should have
caught structural errors. If a runtime error occurs, show the full error message and
do not retry automatically — ask the user how to proceed.

**If the view already exists:** `CREATE OR REPLACE VIEW` overwrites it — no explicit
DROP needed. If the user wants to check before overwriting:

```python
cursor.execute(f"SHOW TABLES IN `{target_catalog}`.`{target_schema}` LIKE '{view_name}'")
rows = cursor.fetchall()
if rows:
    print(f"View '{view_name}' already exists — CREATE OR REPLACE will overwrite it.")
    input("Press Enter to continue or Ctrl+C to cancel...")
```

---

### Step 12b: Verify Creation

After a successful DDL response, confirm the view exists and is queryable.

**1. Confirm the view exists:**

```python
cursor.execute(f"SHOW CREATE TABLE `{target_catalog}`.`{target_schema}`.`{view_name}`")
row = cursor.fetchone()
if row:
    print(f"View '{view_name}' exists in {target_catalog}.{target_schema}.")
else:
    print("WARNING: DDL succeeded but view not found in SHOW CREATE TABLE.")
```

**2. Spot-check — query the first measure:**

```python
first_measure = measures[0]['name']   # first entry in the generated measures list
# Backtick-quote if name contains spaces or reserved words
mname = f"`{first_measure}`" if ' ' in first_measure or first_measure in reserved_words else first_measure

cursor.execute(f"""
  SELECT MEASURE({mname})
  FROM `{target_catalog}`.`{target_schema}`.`{view_name}`
""")
row = cursor.fetchone()
print(f"Spot-check result for MEASURE({first_measure}): {row[0]}")
```

If the spot-check returns an error, report it verbatim. Common errors at this stage:

| Error | Likely Cause | Fix |
|---|---|---|
| `Table or view not found` | View creation silently failed | Retry CREATE VIEW |
| `MEASURE() can only be used with metric views` | DDL succeeded but `WITH METRICS` was lost | Verify DDL includes `WITH METRICS LANGUAGE YAML` |
| `Reference to undefined measure` | `MEASURE(name)` references a misspelled measure | Fix measure name spelling in YAML |
| `Ambiguous column reference` | Column name conflict between source and join | Qualify the column in `expr` with the join alias |
| `[DATABRICKS_TOKEN_*] is empty` | Token expired | See token refresh instructions in ts-setup-databricks-profile |

**3. Report location:**

```
Metric View created successfully.

  Name:       {view_name}
  Catalog:    {target_catalog}
  Schema:     {target_schema}
  Source:     {source_table}
  Joins:      {n}
  Dimensions: {n}
  Measures:   {n}
```

Close the Databricks connection:
```python
conn.close()
```

---

### Step 13: Generate Test Questions

After the view is successfully created (or file written in file-only mode), generate
5 natural language questions derived from the metric view.

**Question design — aim for variety:**

| Type | Example pattern |
|---|---|
| Simple aggregation | "What is the total {measure} ?" |
| Breakdown | "What is {measure} by {dimension} ?" |
| Time trend | "How has {measure} changed over {date_dimension} ?" |
| Ranking | "Which {dimension} has the highest {measure} ?" |
| Multi-table / filtered | "What is {measure} for {joined_dimension} broken down by {another_dimension} ?" |

Span multiple tables (source + joined) where possible to exercise the join tree.
Use `display_name` values where available — these are more natural than snake_case names.

Present the questions as:

```
Test questions for {view_name}

1. {question}
2. {question}
3. {question}
4. {question}
5. {question}

───────────────────────────────────────────────
Databricks Genie
  In your Databricks workspace: create or open a Genie space, add the metric view as
  a data source, and ask each question. Genie uses the display_name, synonyms, and
  comment fields to understand your questions.

Databricks SQL
  In a Notebook or SQL editor, query the metric view directly:
    SELECT {dimension}, MEASURE(`{measure}`)
    FROM `{catalog}`.`{schema}`.`{view_name}`
    GROUP BY {dimension};

ThoughtSpot Spotter
  In your ThoughtSpot instance: open Spotter, select the original worksheet/model,
  and ask each question to compare results.
───────────────────────────────────────────────
```

**After completing a model — batch continuation:**

If the user originally requested multiple models and more remain, immediately offer
the next one without waiting to be asked:

```
✓ {view_name} created in {target_catalog}.{target_schema}

Next up: {next_model_name}
  Ready to convert? (Y / N):
```

If yes: go directly to Step 2 (model selection is already known — skip to Step 3:
Export TML). Reuse the ThoughtSpot profile and Databricks connection from this session.
Do **not** re-run Step 1 profile prompts.

If no (or no more models remain): the session is complete. Close the Databricks
connection if it is still open.
