---
name: ts-convert-to-databricks-mv
description: Convert or export a ThoughtSpot Worksheet or Model into a Databricks Metric View. Use when ThoughtSpot is the source and the goal is a Databricks Metric View — whether converting metrics and formulas for Databricks AI/BI access, generating CREATE VIEW WITH METRICS DDL, writing a .sql file for later execution, or publishing ThoughtSpot semantics to Unity Catalog. Direction is always ThoughtSpot → Databricks. Not for Databricks → ThoughtSpot, standalone TML exports, or adding synonyms/AI context to ThoughtSpot models.
---

# ThoughtSpot → Databricks Metric View

Convert a ThoughtSpot Worksheet or Model into a Databricks Metric View. Searches
ThoughtSpot for available models, exports the TML definition, maps it to Databricks
Metric View YAML format, and creates it via `CREATE OR REPLACE VIEW ... WITH METRICS`.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-databricks/ts-to-databricks-rules.md](../../shared/mappings/ts-databricks/ts-to-databricks-rules.md) | Column classification, aggregation, data type, and name generation lookup tables |
| [../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md) | ThoughtSpot formula → Databricks SQL translation rules and untranslatable pattern handling |
| [../../shared/mappings/ts-databricks/ts-databricks-properties.md](../../shared/mappings/ts-databricks/ts-databricks-properties.md) | Full property coverage matrix, limitations, and Unmapped Report format |
| [../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md) | Databricks Metric View DDL syntax, YAML schema (v0.1/v1.1), validation rules |
| [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) | TML export parsing — non-printable chars, PyYAML pitfalls, object type identification |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML field reference — column types, data types, joins_with structure |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML field reference — model_tables, columns, formulas, join scenarios |
| [../../shared/schemas/thoughtspot-formula-patterns.md](../../shared/schemas/thoughtspot-formula-patterns.md) | Common ThoughtSpot formula patterns and their classification |
| [../ts-profile-databricks/SKILL.md](../ts-profile-databricks/SKILL.md) | Databricks auth methods, profile config, CLI usage |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| [../../shared/worked-examples/databricks/ts-to-databricks.md](../../shared/worked-examples/databricks/ts-to-databricks.md) | End-to-end Dunder Mifflin conversion: multi-fact split, flattened views, LOD, semi-additive, cross-measure ratios |

---

## Concept Mapping

| ThoughtSpot | Databricks Metric View (v1.1) |
|---|---|
| Worksheet / Model | Metric View (VIEW ... WITH METRICS) |
| Model `description` | Top-level `comment:` |
| `ATTRIBUTE` column (non-date) | `dimensions[]` — `name:`, `expr:`, `display_name:`, `comment:`, `synonyms:` |
| `ATTRIBUTE` column (date/timestamp) | `dimensions[]` — same as non-date (no separate time_dimensions in MV) |
| `MEASURE` column with `aggregation` | `measures[]` — `expr: AGG(column_name)`, with `display_name:`, `comment:`, `synonyms:` |
| `MEASURE` COUNT_DISTINCT column | `measures[]` — `expr: COUNT(DISTINCT column_name)` |
| Formula column — translatable MEASURE | `measures[]` — expression translated to Databricks SQL aggregation |
| Formula column — translatable ATTRIBUTE | `dimensions[]` — expression translated to Databricks SQL |
| Formula column — LOD (`group_aggregate`) | `dimensions[]` — `expr: AGG() OVER (PARTITION BY ...)`. **Live-verified 2026-07-09** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A1/A2): TS `query_filters()` is CONFIRMED filter-aware under both filter kinds and matches a DBX MV's own global `filter:` — it does NOT reproduce a DBX consumer's ad hoc query-time `WHERE` on an MV with no global filter (DBX-side asymmetry, not fixable by formula) unless the source formula uses `{}` + a model-level `filters:` block instead, which reproduces both DBX conditions at once (A3 follow-up, same matrix, live-verified 2026-07-09) |
| Semi-additive (`last_value(sum(m), query_groups(), {d})`) | `measures[]` with `window: [{order: raw_date_dim, semiadditive: last, range: current}]` — snapshot metrics. **Live-verified 2026-07-09**, matrix C7. **Also live-verified 2026-07-09 under a query-time date-range filter** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — CONFIRMED cross-platform, collapses to last/first-in-filtered-range on both platforms |
| Period filter — current month (`sum([m])` at query grain, or `sum_if(diff_months(...)=0,[m])`) | `measures[]` with `window: [{order: month_dim, semiadditive: last, range: current}]` — flow metrics. **Live-verified 2026-07-09**, matrix C6/C6a |
| Period filter — prior month (`moving_sum([m], 1, -1, [date])` row-relative LAG idiom, or `sum_if(diff_months(...)=-1,[m])` wall-clock) | `measures[]` with `window: [{..., range: current, offset: -1 month}]` — **lossy approximation**: Databricks `offset` is row-relative (LAG-style shift per output row's own period), not wall-clock — exact only for a single-current-period snapshot query, not a multi-period trend. **Live-verified 2026-07-09 at month grain N=1**, matrix C6/C6a |
| Period filter — same month last year (`sum_if(diff_months(...)=-12,[m])`) | `measures[]` with `window: [{..., range: current, offset: -1 year}]` — same lossy-approximation caveat; **Deferred (C8)**, extrapolated from the verified month-grain mechanism, not separately live-tested |
| Period filter — current quarter (`sum_if(diff_quarters(...)=0,[m])`) | `measures[]` with `window: [{order: quarter_dim, semiadditive: last, range: current}]` |
| Period filter — prior quarter (`sum_if(diff_quarters(...)=-1,[m])`) | `measures[]` with `window: [{..., range: current, offset: -3 month}]` — same caveat; **Deferred (C8)** |
| Period filter — current year (`sum_if(diff_years(...)=0,[m])`) | `measures[]` with `window: [{order: year_dim, semiadditive: last, range: current}]` |
| Period filter — prior year (`sum_if(diff_years(...)=-1,[m])`) | `measures[]` with `window: [{..., range: current, offset: -1 year}]` — same caveat; **Deferred (C8)** |
| Rolling window, trailing default/exclusive (`moving_sum([m], N, -1, [d])`) | `measures[]` with `window: [{order: date_dim, range: trailing N day, semiadditive: last}]`. **Live-verified 2026-07-09**, matrix C1/C2. **Density caveat (E1):** row-positional — matches only when the order column is dense at the window's unit grain (one row per unit, no gaps); see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` (E1) |
| Rolling window, trailing inclusive (`moving_sum([m], N-1, 0, [d])`, spans N rows incl. anchor) | `measures[]` with `window: [{order: date_dim, range: trailing N day inclusive, semiadditive: last}]`. **Live-verified 2026-07-09**, matrix C1. Same E1 density caveat as above |
| Rolling window, leading default/exclusive (`moving_sum([m], -1, N, [d])`) | `measures[]` with `window: [{order: date_dim, range: leading N day, semiadditive: last}]`. **Live-verified 2026-07-09**, matrix C3. Same E1 density caveat as above |
| Rolling window, leading inclusive (`moving_sum([m], 0, N-1, [d])`, spans N rows incl. anchor) | `measures[]` with `window: [{order: date_dim, range: leading N day inclusive, semiadditive: last}]`. **Live-verified 2026-07-09**, matrix C3. Same E1 density caveat as above |
| Rolling window, any other `(start, end)` pair (e.g. `moving_sum([m], -2, 3, [d])`) | **Unmapped — route to manual review / Unmapped Properties Report.** No Databricks `range:` reproduces a detached window; do not classify by sign alone (matrix C1/C3 TS-side grid) |
| Cumulative (`cumulative_sum(m, d)`) | `measures[]` with `window: [{..., range: cumulative}]`. **Live-verified 2026-07-09**, matrix C5 |
| Conditional aggregate (`sum_if(cond, x)`) | `measures[]` — `expr: SUM(x) FILTER (WHERE cond)` |
| Conditional aggregate (`unique_count_if(cond, x)`) | `measures[]` — `expr: COUNT(DISTINCT x) FILTER (WHERE cond)` |
| Conditional aggregate (all `*_if` variants) | `measures[]` — `expr: AGG(x) FILTER (WHERE cond)` |
| `safe_divide(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` |
| Cross-formula ref to measure | `MEASURE(measure_name)` in measure `expr`. **Live-verified 2026-07-09 across query grain** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — CONFIRMED true ratio-of-sums, cross-platform, at every grain; no grain caveat needed |
| Cross-formula ref to LOD dimension | `ANY_VALUE(dimension_name)` in measure `expr` |
| Formula column — untranslatable | **Omitted** — logged in Unmapped Report |
| Column `name` (display name) | `display_name:` |
| Column `description` | `comment:` |
| `properties.synonyms[]` | `synonyms:` list (read from `properties.synonyms`, NOT column root) |
| `ai_context` | **NOT MAPPED** — no equivalent; include in view-level `comment` if relevant |
| `joins[]` / `referencing_join` | **Primary:** nested `joins:` in v1.1 star schema. **Fallback:** flattened SQL VIEWs (user-confirmed) |
| `properties.currency_type` | `format: { type: currency, currency_code: ... }` |

## DDL Format Reference

The output is a `CREATE OR REPLACE VIEW ... WITH METRICS` statement wrapping a YAML
body. **Always use v1.1** for rich column metadata. Full structure:

**Single-source (no joins):**

```sql
CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: >-
  Description of what this Metric View covers.
source: {catalog}.{schema}.{source_table}
dimensions:
  - name: {identifier}
    expr: {column_or_expression}
    display_name: '{Human Label}'
    comment: '{Column description.}'
    synonyms: ['{alias1}', '{alias2}']
measures:
  - name: {identifier}
    expr: {AGG(column_or_expression)}
    display_name: '{Human Label}'
    comment: '{Measure description.}'
    synonyms: ['{alias1}']
$$
```

**Multi-table with joins (primary approach for star schemas):**

```sql
CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: >-
  Description.
source: {catalog}.{schema}.{fact_table}
joins:
  - name: {dim_alias}
    source: {catalog}.{schema}.{dim_table}
    "on": source.{fk} = {dim_alias}.{pk}
    rely: { at_most_one_match: true }
    joins:
      - name: {sub_dim_alias}
        source: {catalog}.{schema}.{sub_dim_table}
        "on": {dim_alias}.{fk2} = {sub_dim_alias}.{pk2}
        rely: { at_most_one_match: true }
dimensions:
  - name: {identifier}
    expr: {dim_alias}.{column}
    display_name: '{Human Label}'
measures:
  - name: {identifier}
    expr: SUM(source.{column})
    display_name: '{Human Label}'
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }
$$
```

**DDL rules:**
- **Always use `LANGUAGE YAML`** in the DDL — `WITH METRICS AS $$` without it fails with `MISSING_CLAUSES_FOR_OPERATION`.
- **Always use v1.1** — even for single-source MVs. v1.1 supports `source:` (same as v0.1) but adds `display_name`, `comment`, `synonyms`.
- All non-metric columns (including dates) go in `dimensions[]`. There is no separate `time_dimensions` in the Metric View schema.
- Aggregation is embedded in each measure's `expr` — e.g. `expr: SUM(revenue)`, `expr: COUNT(DISTINCT customer_id)`.
- LOD calculations go in `dimensions[]` with `AGG() OVER (PARTITION BY ...)` — NOT in measures.
- Cross-measure references use `MEASURE(name)` and `ANY_VALUE(dim_name)`.
- Semi-additive measures use `window: [{order: dim, range: current, semiadditive: last}]` — `semiadditive` is REQUIRED.
- **Single-source:** column references in `expr` use physical column names directly (no prefix).
- **Multi-table (primary):** use nested `joins:` with `rely: { at_most_one_match: true }`. Column refs use dot-path: `orders.customers.COMPANY_NAME`.
- **Multi-table (fallback):** flattened SQL VIEWs as sources — only when joins are too complex. User must confirm this approach.
- **Multi-fact models** must be split into independent MVs (one per fact table).
- The YAML body is delimited by `$$` — do not use `$$` inside any expression or string value.

For the full schema reference, see
[../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md).

For the full coverage matrix including unmapped properties, see
[../../shared/mappings/ts-databricks/ts-databricks-properties.md](../../shared/mappings/ts-databricks/ts-databricks-properties.md).

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege
- `ts` CLI installed (`pip install -e tools/ts-cli`)
- Authentication configured — run `/ts-profile-thoughtspot` if you haven't already

**Quick auth decision:**
```
Can you log into ThoughtSpot in a browser (even via SSO)?
  YES → token_env   — get a token from Developer Playground (no admin needed)
  NO  → password_env or secret_key_env — see ts-profile-thoughtspot.md
```

### Databricks

- Databricks workspace with Unity Catalog enabled
- SQL warehouse on **Preview channel** — the Current channel will reject Metric View syntax
- Databricks CLI installed (`pip install databricks-cli` or `brew install databricks`)
- Profile configured — run `/ts-profile-databricks` if you haven't already

**Preview channel warning:** Metric Views require a SQL warehouse running on the
**Preview channel**. If the warehouse is on the Current channel, the `CREATE VIEW ...
WITH METRICS` statement will fail with a syntax error. To check:
```bash
source ~/.zshenv && databricks api get /api/2.0/sql/warehouses/{warehouse_id} \
  --profile {dbx_profile} | python3 -c "import sys,json; w=json.load(sys.stdin); print(f'Channel: {w.get(\"channel\",{}).get(\"name\",\"UNKNOWN\")}')"
```

**No Databricks access?** You can still run this skill in **file-only mode** — it generates
the DDL and writes it to a `.sql` file you can run manually in a Databricks SQL editor
later. Select **FILE** at the Step 10 checkpoint or say "file only" at any point before
Step 12.

---

## CLI-first rule — no inline Python for TML operations

**Every** ThoughtSpot API call, TML generation, and model import in this skill **must** go
through a `ts` CLI command. Do not write inline Python scripts to export/merge/import TML,
iterate over formula failures, or assemble model JSON. If a CLI command fails or produces
wrong results, **fix the CLI** (`tools/ts-cli/`) and re-run — do not work around it with
manual scripting.

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-to-databricks-mv** — export a ThoughtSpot Worksheet or Model and create a matching Databricks Metric View.

Steps:
  1.    Authenticate (ThoughtSpot) ......................... auto
  1.5.  Authenticate (Databricks) .......................... auto
  2.    Find and select the model / worksheet .............. you choose
  3.    Export and parse the TML ........................... auto
  4.    Identify source tables from TML .................... auto
  5.    Map ATTRIBUTE columns → dimensions .................. auto
  6.    Map MEASURE columns → measures ...................... auto
  7.    Translate formula columns TS → Databricks SQL ....... auto
  8.    Generate MV YAML body .............................. auto
  9.    Build full DDL (CREATE OR REPLACE VIEW ... WITH METRICS) . auto
 10.    Checkpoint — review DDL before execution ............ you confirm
 11.    Validate the DDL structure ......................... auto
 12.    Execute DDL in Databricks .......................... auto
 13.    Verify creation and generate summary ................ auto

File-only mode: at Step 10, choose FILE instead of executing — generates a .sql file
for manual import in a Databricks SQL editor.

Confirmation required: Step 10 (DDL review)
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Workflow

### Step 1: Authenticate to ThoughtSpot

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
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

The CLI handles token caching, Keychain access, and expiry automatically.
No temp files or manual token management needed in this skill.

If `ts auth whoami` returns 401, the token is expired. Direct the user to
`/ts-profile-thoughtspot` (U3 — Refresh Credential) — that section is the canonical,
cross-platform refresh procedure. Then clear the stale cache and retry:

```bash
source ~/.zshenv && ts auth logout --profile {profile_name}
source ~/.zshenv && ts auth whoami --profile {profile_name}
```

---

### Step 1.5: Authenticate to Databricks

**Session continuity:** If a Databricks profile was already confirmed earlier in
this conversation, skip profile selection and reuse it.

**Profile selection (first model only):**

1. Run `databricks auth describe --profile {dbx_profile}` to verify connectivity.
2. If no profile name was provided, check `~/.databrickscfg` for configured profiles
   and present a numbered list.

```
Available Databricks profiles:
  1. dev-workspace  — https://dbc-abc123.cloud.databricks.com
  2. prod-workspace — https://dbc-def456.cloud.databricks.com

Select a profile (or press Enter to use #1):
```

After the profile is confirmed, verify the connection:

```bash
source ~/.zshenv && databricks auth describe --profile {dbx_profile}
```

If authentication fails, direct the user to run `/ts-profile-databricks` to configure
their credentials.

**Warehouse selection:**

The user must provide a SQL warehouse ID. If not already known:

```bash
source ~/.zshenv && databricks api get /api/2.0/sql/warehouses \
  --profile {dbx_profile} | python3 -c "
import sys, json
whs = json.load(sys.stdin).get('warehouses', [])
for i, w in enumerate(whs, 1):
    ch = w.get('channel', {}).get('name', 'UNKNOWN')
    state = w.get('state', 'UNKNOWN')
    print(f'  {i}. {w[\"name\"]}  id: {w[\"id\"]}  channel: {ch}  state: {state}')
"
```

```
Available SQL warehouses:
  1. dev-warehouse    id: abc123  channel: CHANNEL_NAME_PREVIEW  state: RUNNING
  2. prod-warehouse   id: def456  channel: CHANNEL_NAME_CURRENT  state: STOPPED

Select a warehouse (or press Enter to use #1):
```

**Preview channel check:** If the selected warehouse is on the Current channel, warn:

```
⚠ Warehouse "{name}" is on the Current channel.
  Metric Views require the Preview channel.
  The DDL will likely fail with a syntax error.

  Continue anyway? [Y / N / FILE (generate .sql only)]
```

Store `{warehouse_id}` and `{dbx_profile}` for use in Step 12.

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

When the user has selected multiple models for conversion, pass all GUIDs to a single
export call:

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
- **SQL view objects:** parsed YAML has top-level key `sql_view` — collect separately for handling in Step 4

---

### Step 4: Identify Source Tables

| Top-level key | Format | Key difference |
|---|---|---|
| `worksheet` | Worksheet | Join conditions in Table TML; columns explicit in `worksheet_columns[]` |
| `model` | Model | Joins use `referencing_join` or inline `on`; columns derived from Table TML |

Build a map: `logical_table_name → { catalog, schema, physical_table }`.

From each Table TML object extract:
```yaml
table:
  name: fact_sales       # map key
  db: analytics_catalog
  schema: sales          # accessed as tbl.get("schema") — NOT tbl.get("schema_")
  db_table: fact_sales
```

**PyYAML field name:** The schema field is `"schema"` in Python dicts after parsing —
never `"schema_"`. See [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) for details.

**Schema is reliably exported:** With `export_fqn: true` and `export_associated: true`,
the schema value is present in Table TML whenever it is set in ThoughtSpot. If it
appears missing, first verify with `tbl.keys()` — do not prompt the user until confirmed
genuinely absent.

If `db` or `schema` is confirmed absent after inspection, ask the user to provide them.

Use `TODO_CATALOG` / `TODO_SCHEMA` placeholders for unresolved tables and flag them.

**SQL view resolution:** For every `sql_view` object referenced in `model_tables[]`
(or `table_paths[]` for Worksheet format), classify its `sql_query`:

*Simple* — `SELECT * FROM single_table [AS alias]`:
- Extract the physical FQN from the FROM clause
- Resolve `catalog`, `schema`, `db_table` from the FQN
- Treat the sql_view as a regular table for all subsequent steps
- Note it in the Unmapped Properties Report under "SQL Views resolved automatically"

*Complex* — anything else (WHERE, column list, JOIN, aggregation, subquery, UNION):
- Do not attempt auto-resolution
- At the **Step 10 checkpoint**, present the sql_query to the user and ask:

  ```
  sql_view "{name}" uses SQL that cannot be auto-mapped to a single physical table:
    {sql_query}

  How should this be handled?
    C — Create a Databricks VIEW from this SQL, then reference it as the MV source
    M — Map to an existing Unity Catalog table or view (you provide the name)
    S — Skip — omit all columns sourced from this view
  ```

  - **C (Create view):** Before executing the Metric View CREATE, run:
    ```sql
    CREATE OR REPLACE VIEW {target_catalog}.{target_schema}.{view_name} AS
    {sql_query};
    ```
    Then reference the new view as the MV `source`.

  - **M (Map to existing):** Ask for the fully-qualified Unity Catalog object name.
    Use as the MV `source`.

  - **S (Skip):** Omit all model columns whose `column_id` references this sql_view.
    Log each omitted column in the Unmapped Properties Report under "SQL Views skipped".

**Multi-table handling:**

If the model references multiple physical tables:

1. **Single fact + dimension joins (primary):** Use v1.1 with nested `joins:` to express the
   star schema directly. The fact table is `source:`, dimension tables are nested `joins:`.
   Column references use dot-path: `dim_alias.COL`, `dim_alias.sub_dim.COL`.
2. **Multiple fact tables:** Split into independent MVs — one per fact table as `source:`,
   each with its own dimension joins via nested `joins:`.
3. **Flattened SQL VIEW (fallback only):** Only when the join structure cannot be expressed
   as nested joins (e.g., many-to-many, cross-fact joins). The user must confirm this
   approach at the Step 10 checkpoint.

See [../../shared/mappings/ts-databricks/ts-to-databricks-rules.md](../../shared/mappings/ts-databricks/ts-to-databricks-rules.md)
for the multi-table mapping rules and YAML templates.

See the [Dunder Mifflin worked example](../../shared/worked-examples/databricks/ts-to-databricks.md)
for a complete multi-fact split.

---

### Step 5: Map ATTRIBUTE Columns → Dimensions

For each model column classified as ATTRIBUTE (including date/timestamp columns):

1. Resolve `column_id` → physical column name via Table TML (see Step 4)
2. Build the dimension entry with v1.1 metadata:
   ```yaml
   - name: {snake_case_identifier}
     expr: {physical_column_name}
     display_name: '{ThoughtSpot display name}'
     comment: '{column description}'
     synonyms: ['{synonym1}', '{synonym2}']
   ```
3. If the column has a formula (`formula_id` is set), defer to Step 7 for translation
4. If the formula is an LOD pattern (`group_aggregate`), defer to Step 7 — it maps
   to a dimension with `AGG() OVER (PARTITION BY ...)`, not a measure

**Name generation:** Use a snake_case version of the display name for the `name:` field
(machine identifier). Use the ThoughtSpot display name as `display_name:`.

**All ATTRIBUTE types go in dimensions** — there is no separate `time_dimensions`
section in the Metric View schema. Date columns, timestamp columns, and regular
string/numeric attributes all use the same `dimensions[]` list.

See [../../shared/mappings/ts-databricks/ts-to-databricks-rules.md](../../shared/mappings/ts-databricks/ts-to-databricks-rules.md)
for the column classification decision tree.

---

### Step 6: Map MEASURE Columns → Measures

For each model column classified as MEASURE with an `aggregation` value:

1. Resolve `column_id` → physical column name via Table TML
2. Map the ThoughtSpot aggregation to its SQL equivalent:

   | ThoughtSpot `aggregation` | Measure `expr` |
   |---|---|
   | `SUM` | `SUM({column})` |
   | `AVERAGE` | `AVG({column})` |
   | `MIN` | `MIN({column})` |
   | `MAX` | `MAX({column})` |
   | `COUNT` | `COUNT({column})` |
   | `COUNT_DISTINCT` | `COUNT(DISTINCT {column})` |
   | `STD_DEVIATION` | `STDDEV({column})` |
   | `VARIANCE` | `VARIANCE({column})` |
   | (none — no aggregation) | Treat as ATTRIBUTE → `dimensions[]` |

3. Build the measure entry with v1.1 metadata:
   ```yaml
   - name: {snake_case_identifier}
     expr: {AGG}({physical_column_name})
     display_name: '{ThoughtSpot display name}'
     comment: '{column description}'
     synonyms: ['{synonym1}']
   ```

4. If the column has a formula (`formula_id` is set), defer to Step 7 for translation
5. For period-filter measures (`sum_if(diff_months/quarters/years(...))`) and
   cumulative measures (`cumulative_sum`), add `window:` — see Step 7

**Aggregation is embedded in expr:** Unlike some formats that separate the aggregation
type from the column reference, Metric View measures embed the full aggregate call in
the `expr` field.

See [../../shared/mappings/ts-databricks/ts-to-databricks-rules.md](../../shared/mappings/ts-databricks/ts-to-databricks-rules.md)
for the aggregation mapping rules.

---

### Step 7: Translate Formula Columns

> **MANDATORY — read the reference before assessing any formula:**
> Open [../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md)
> and use its **Decision Flowchart** to classify every formula. Do **not** classify
> a formula as untranslatable based on function name recognition alone. Patterns
> that appear ThoughtSpot-specific may have documented Databricks SQL equivalents.

For each formula column (`formula_id` is set):

1. Look up formula expression from `formulas[]` by `id` or `name`
2. Resolve column references using the syntax rules for the TML format (Worksheet uses
   `[path_id::col]`, Model uses `[TABLE::col]`)
3. Classify using the Decision Flowchart in the formula translation reference, then
   translate using the rules in that file
4. Handle nested references up to 3 levels deep
5. Classify the translated formula:
   - If the original column is a MEASURE → add to `measures[]`
   - If the original column is an ATTRIBUTE → add to `dimensions[]`

**Untranslatable formulas — omit entirely:**

For formulas confirmed untranslatable after consulting the reference, **do not emit
the column** in the YAML. Do NOT use `-- TODO`, `CAST(NULL AS TEXT)`, or any placeholder
`expr` — these cause parse errors or silent failures.

Instead:
- Skip the column in the output YAML
- Add an entry to the Formula Translation Log in the Unmapped Properties Report:
  ```
  | {display_name} | OMITTED | {reason} | {original_expr} |
  ```

**LOD formulas → dimension window functions:**

ThoughtSpot `group_aggregate(sum(x), {dim}, query_filters())` maps to a **dimension** (not a measure):
```yaml
dimensions:
  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)
    display_name: 'Category Quantity'
    comment: 'Total units at category grain.'
```

Do NOT use `AGGREGATE OVER` — it causes `PARSE_SYNTAX_ERROR`.
Do NOT use `window:` for LOD — `window` requires `semiadditive`.

**Filter asymmetry caveat (A1/A2, live-verified 2026-07-09 — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** The source
`query_filters()` is CONFIRMED filter-aware on ThoughtSpot under both a
query-level pin and a model-level `filters:` block. The emitted
`SUM(x) OVER (PARTITION BY ...)` dimension reproduces that behavior only for a
Databricks consumer whose filter is baked into this MV's own global `filter:`
block — a consumer applying an ad hoc query-time `WHERE` on the MV instead gets a
filter-**blind** dimension (the `WHERE` prunes output rows only, not the window's
computed value). Flag this as a DBX-side asymmetry for the consuming team, not a
translation defect — **unless** the source ThoughtSpot formula uses `{}` (not
`query_filters()`) paired with a model-level `filters:` block mirroring what will
become this MV's `filter:`; live-tested 2026-07-09 (A3, same matrix), that
combination is filter-blind to a search-level pin and filter-aware of the model
filter, reproducing both DBX conditions in a single emitted `filter:` block plus
this dimension.

**Window formulas — classify by `order:` dimension type:**

Two ThoughtSpot patterns map to MV `window: [{range: current}]`. The `order:`
dimension determines which:

```
Is the formula last_value() or first_value()?
  YES → Semi-additive (snapshot metric)
        order: raw date dimension
        range: current — Live-verified 2026-07-09, matrix C7
  NO  → Is it sum(m), or moving_sum(m, N, -N, d) at a period grain?
          YES → Period filter (flow/additive metric)
                order: truncated period dimension
                no offset (plain sum) or offset: -N <unit> (moving_sum LAG idiom)
                — Live-verified 2026-07-09, matrix C6/C6a
```

A ThoughtSpot `sum_if(diff_months/quarters/years([date], today())=N, [m])`
wall-clock filter also routes here as the **source** formula being converted —
but see the lossy-approximation caveat below the `offset` examples: Databricks
`window: [{range: current, offset: ...}]` is row-relative, not wall-clock, so it
only reproduces the wall-clock formula's output for a single-current-period
snapshot query, not a multi-period trend (matrix C6/C6a, corrected 2026-07-09).

**Semi-additive (snapshot metrics) → `order:` raw date:**

```yaml
# last_value(sum([FILLED_INVENTORY]), query_groups(), {[balance_date]})
measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    window:
      - order: balance_date
        semiadditive: last
        range: current
```

**Live-verified 2026-07-09 under a query-time date-range filter** (see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — **CONFIRMED
cross-platform**: `last_value`/`first_value` and the equivalent Databricks
`window:` measure both collapse to the last/first observation *within the
filtered range* under a query-level date-range pin, identical values on both
platforms including the single-surviving-row edge case. No formula change needed.

**Period filter (flow metrics) → `order:` truncated period (requires Runtime 18.1+ for `offset`):**

> **Runtime gate:** Measures with `offset` require **Runtime 18.1+**. If the target
> warehouse runs Runtime 17.3, warn the user that period-over-period measures will cause
> `PARSE_SYNTAX_ERROR` and offer to omit `offset` (the base current-period measure without
> `offset` still works on 17.3).

```yaml
# sum_if(diff_months([date], today()) = 0, [m]) → current month
measures:
  - name: monthly_revenue
    expr: SUM(LINE_TOTAL)
    display_name: 'Monthly Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current

# sum_if(diff_months([date], today()) = -1, [m]) → previous month
  - name: prior_month_revenue
    expr: SUM(LINE_TOTAL)
    display_name: 'Prior Month Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 month

# sum_if(diff_months([date], today()) = -12, [m]) → same month last year
  - name: prior_year_revenue
    expr: SUM(LINE_TOTAL)
    display_name: 'Prior Year Revenue'
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 year
```

Quarter grain uses `diff_quarters` → `offset: -3 month`; year grain uses
`diff_years` → `offset: -1 year` / `-2 year`. **Deferred (C8):** the quarter/year
rows are extrapolated from the month-grain mechanism verified below, not
separately live-tested.

**Live-verified 2026-07-09 at month grain, N=1** — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C6, C6a). The corrected
finding: Databricks `window: [{range: current, offset: -N <unit>}]` is a
**row-relative** shift (a `LAG(N)`-style offset relative to each output row's own
period), **not** anchored to wall-clock `today()`. This makes it a **lossy
approximation** of a ThoughtSpot `sum_if(diff_months/quarters/years([date],
today())=N, [m])` formula — exact only when the MV is queried for a single
current-period snapshot, not a multi-period trend. Flag this caveat at the Step
10 checkpoint whenever converting a period-filter measure. The pre-2026-07-09
version of this section presented the mapping as an unqualified equivalence —
it is not.

**Growth % formulas** inline `sum_if` for both periods directly, so no cross-formula
references are needed in the MV — express as a ratio of two `MEASURE()` references.

**Cumulative formulas → window with range cumulative:**

ThoughtSpot `cumulative_sum(m, d)` maps to:
```yaml
measures:
  - name: cumulative_revenue
    expr: SUM(LINE_TOTAL)
    display_name: 'Cumulative Revenue'
    window:
      - order: order_date
        semiadditive: last
        range: cumulative
```

**Cross-measure references:**

When a formula references other measures or LOD dimensions:
- Reference another measure: `MEASURE(measure_name)`
- Reference an LOD dimension from a measure: `ANY_VALUE(dimension_name)`

```yaml
measures:
  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
    display_name: 'Product to Category Contribution Ratio'
```

**safe_divide → COALESCE/NULLIF:**
```yaml
measures:
  - name: answer_formula
    expr: COALESCE(SUM(LINE_TOTAL) / NULLIF(SUM(QUANTITY), 0), 0)
```

**Boolean filter formulas → MV `filter:` field:**

Detect formula columns that are boolean ATTRIBUTE filters (e.g., named "MV Filter",
"Is Active", or containing only boolean comparison logic). If found:

1. Check if the expression is translatable to SQL (see filter translation table below)
2. If translatable → add as `filter:` field in the MV YAML, remove from dimensions list
3. If untranslatable (parameters, LOD-based) → log in Unmapped Report

| ThoughtSpot formula | MV `filter:` |
|---|---|
| `[TABLE::col] = 'val'` | `col = 'val'` |
| `[TABLE::col] = false` | `NOT col` |
| `[TABLE::col] = 'a' or [TABLE::col] = 'b'` | `col IN ('a', 'b')` |
| `[TABLE::col] >= N and [TABLE::col] <= M` | `col BETWEEN N AND M` |

Not every boolean ATTRIBUTE is a filter — only convert when the formula's purpose
is clearly row-level filtering (named "Filter", "MV Filter", or confirmed by user).
If uncertain, present the formula at the Step 10 checkpoint and ask.

**Live-verified 2026-07-09** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`,
C1) — emitting the ThoughtSpot filter as the MV's `filter:` field is **CONFIRMED**
the correct ordering choice: both a ThoughtSpot model-level `filters:` block and a
Databricks MV's global `filter:` filter rows *before* a windowed measure (e.g.
`moving_sum`) computes over them. **Frame semantics on windowed measures still
DIVERGE on gapped data** (same root cause as E1): Databricks' `trailing N day` spans
a date *interval*, `moving_sum` counts surviving *rows* — see the density caveat on
the rolling-window rows in the Concept Mapping table above.

Confirmed untranslatable patterns (after checking the reference):
- `[parameter_name]` — ThoughtSpot runtime parameter (no SQL equivalent)
- `ts_first_day_of_week(...)`, `last_n_days(...)` — period-scoped time intelligence with no Databricks equivalent
- `group_aggregate(...)` with `query_groups()` modifier — hardcoded/selective filters unsupported
- Hyperlink markup: `concat("{caption}", ..., "{/caption}", ...)` — ThoughtSpot display hint
- Any reference to a formula that is itself confirmed untranslatable (transitive)

---

### Step 8: Generate Metric View YAML

Assemble the YAML body from the dimensions and measures collected in Steps 5–7.
**Always use v1.1** for rich column metadata.

```yaml
version: 1.1
comment: >-
  Description of the Metric View.
source: catalog.schema.source_table_or_view

dimensions:
  - name: identifier
    expr: PHYSICAL_COLUMN
    display_name: 'Human Label'
    comment: 'Description.'
    synonyms: ['alias1', 'alias2']

measures:
  - name: identifier
    expr: AGG(PHYSICAL_COLUMN)
    display_name: 'Human Label'
    comment: 'Description.'
    synonyms: ['alias1']
```

**YAML formatting rules:**
- Indent with 2 spaces (YAML standard)
- Quote `display_name`, `comment`, and `synonyms` values in single quotes
- Quote `name` values that contain special YAML characters (`:`, `#`, `{`, `}`, `[`, `]`)
- Do not include trailing whitespace
- Ensure the YAML is valid — test-parse it before embedding in the DDL

---

### Step 9: Build Full DDL

Wrap the YAML body in the `CREATE OR REPLACE VIEW ... WITH METRICS` DDL:

```sql
CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}
WITH METRICS LANGUAGE YAML AS $$
{yaml_body}
$$
```

**View name generation:**
- Default: `{to_snake(original_model_name)}_mv`
- Example: model "Retail Sales" → `retail_sales_mv`
- The user may rename at the Step 10 checkpoint

**`to_snake(name)` — name sanitisation:**
```python
import re
def to_snake(name):
    s = re.sub(r'_+', '_', re.sub(r'[^a-z0-9]', '_', name.lower())).strip('_')
    if not s:
        s = 'field'
    elif s[0].isdigit():
        s = 'field_' + s
    return s
# Examples: "Retail Sales" → "retail_sales", "# of Products" → "of_products"
```

---

**TML temp file cleanup — do this now, before Step 10:**

The exported TML files contain sensitive schema metadata (table names, column
descriptions, join conditions, AI context). Delete them as soon as mapping
is complete — they are not needed after this point:

```bash
rm -f /tmp/ts_tml_*.json
```

---

### Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

Present the following sections:

**1. Generated DDL** — full `CREATE OR REPLACE VIEW ... WITH METRICS` statement in a SQL
code block.

**2. Conversion Summary:**
```
- Source table:     {catalog}.{schema}.{table}
- Dimensions:      {n}
- Measures:        {n}  ({n} translated formulas, {n} physical columns)
- Omitted columns: {n}  (untranslatable formulas — see Formula Translation Log)
```

**3. Unmapped Properties Report** — use the format defined in
[../../shared/mappings/ts-databricks/ts-databricks-properties.md](../../shared/mappings/ts-databricks/ts-databricks-properties.md).
Include only sections that have entries. Common sections:
- AI Context not migrated (no MV equivalent)
- Parameters not migrated
- Column groups not migrated
- AI Context not migrated
- Format patterns not migrated
- Formula Translation Log (all formulas, translated and untranslated)
- SQL Views resolved or skipped
- Other dropped properties

---

**Prompt:**
```
Shall I create this Metric View in Databricks?
  YES  — proceed
  NO   — cancel
  EDIT — followed by changes to the YAML
  FILE — write the DDL to a .sql file without executing
```

If the user selects **NO**, stop. No cleanup needed — the CLI manages its own token cache.

If the user selects **FILE**, skip to [Step 12-FILE](#step-12-file-output-ddl-file-only-mode).

---

### Step 11: Validate

Run all checks before execution. Report all failures together before retrying.
Key checks:

- [ ] `version` is `1.1` (always — v0.1 lacks rich metadata)
- [ ] `source` is a fully-qualified Unity Catalog reference (`catalog.schema.table`)
- [ ] DDL uses `WITH METRICS LANGUAGE YAML AS $$` (not `WITH METRICS AS $$`)
- [ ] Every `dimensions[]` entry has both `name` and `expr`
- [ ] Every `measures[]` entry has both `name` and `expr`
- [ ] Dimension and measure `name` values are unique across the entire view
- [ ] Measure `expr` values contain an aggregate function (SUM, AVG, MIN, MAX, COUNT, etc.) — except cross-measure refs using `MEASURE()`
- [ ] LOD dimensions use `AGG() OVER (PARTITION BY ...)` — NOT `AGGREGATE OVER`
- [ ] Semi-additive measures with `window:` include `semiadditive:` property
- [ ] Cross-measure refs use `MEASURE(name)` and `ANY_VALUE(dim)` — not direct column names
- [ ] No untranslatable formula placeholders anywhere in the YAML (`-- TODO`, `CAST(NULL AS TEXT)`, `NULL AS`)
- [ ] YAML is valid — parse it to confirm no syntax errors
- [ ] `$$` delimiter does not appear inside any `expr` value
- [ ] `name` values do not contain characters that break YAML parsing (unescaped `:`, `#`)
- [ ] Source table exists in Unity Catalog (if Databricks connection is active)

---

### Step 12-FILE: Output DDL file (file-only mode)

This path is used when the user selected **FILE** at the Step 10 checkpoint, explicitly
said "file only", or has no Databricks access.

**1. Determine the output filename:**

Use `{view_name}.sql`. If the current working directory contains a
`metric-views/` or `output/` subdirectory, write there; otherwise write to the
current directory.

**2. Write the file:**

```python
from pathlib import Path
out_path = Path(f"{view_name}.sql")
out_path.write_text(ddl_str, encoding="utf-8")
```

**3. Report:**

```
Metric View DDL written to: {view_name}.sql

To create it in Databricks when you have access:
  1. In Databricks SQL editor, set the catalog and schema context,
     and paste + run the contents of {view_name}.sql.

  2. Or via Databricks CLI:
       databricks api post /api/2.0/sql/statements \
         --profile {dbx_profile} \
         --json '{"warehouse_id": "{warehouse_id}", "statement": "$(cat {view_name}.sql)", "wait_timeout": "50s"}'
```

Use the catalog and schema from the table map built in Step 4 as the suggested target
(or `YOUR_CATALOG.YOUR_SCHEMA` if ambiguous).

**4. Proceed to Step 13** (Verify and Generate Summary) — the summary helps the user
know what to verify once they create the view.

---

### Step 12: Execute

**Target location** (skip if already confirmed by the user — e.g. they named a catalog
earlier in the conversation):

Present the unique `(catalog, schema)` pairs from the table map as numbered options:

```
Where should the Metric View be created?

  1. analytics_catalog.sales   (source table location)
  E. Enter a different catalog and schema

Select (or press Enter for #1):
```

If the user selects E, ask for `target_catalog` and `target_schema` explicitly.

**Execute the DDL via the Statement Execution API:**

```bash
source ~/.zshenv && databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "{escaped_ddl}",
    "wait_timeout": "50s"
  }'
```

**SQL escaping:** The DDL string must be JSON-escaped before embedding in the
`--json` payload. Escape `"` as `\"`, newlines as `\n`, and `$$` must remain literal.

**Alternative — multi-statement execution:**
If the DDL is too long for a single JSON string, write it to a temp file and execute:

```bash
source ~/.zshenv && cat /tmp/mv_ddl.sql | databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json "$(python3 -c "
import json, sys
ddl = sys.stdin.read()
print(json.dumps({'warehouse_id': '{warehouse_id}', 'statement': ddl, 'wait_timeout': '50s'}))
" < /tmp/mv_ddl.sql)"
```

**Response handling:**

Check the `status.state` field in the response:
- `SUCCEEDED` → proceed to Step 13
- `FAILED` → show `status.error.message` verbatim; ask the user what to do
- `PENDING` / `RUNNING` → poll with:
  ```bash
  source ~/.zshenv && databricks api get /api/2.0/sql/statements/{statement_id} \
    --profile {dbx_profile}
  ```

On success: report the created view name and location.
On failure: show the full Databricks error. Do not retry automatically — ask the user.

**Cleanup:**

No ThoughtSpot token cleanup needed — the CLI manages its own cache automatically.
Remove any temp files:
```bash
rm -f /tmp/mv_ddl.sql /tmp/ts_tml_*.json
```

---

### Step 13: Verify Creation and Generate Summary

After a successful execution, confirm the view exists and generate a summary.

**1. Verify the view exists:**

```bash
source ~/.zshenv && databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}",
    "wait_timeout": "50s"
  }'
```

Expected: result includes the view's column definitions. If the statement fails,
report the error verbatim — do not proceed to test questions.

**2. Spot-check — SELECT the first measure:**

```bash
source ~/.zshenv && databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "SELECT {first_measure_name} FROM {catalog}.{schema}.{view_name} LIMIT 1",
    "wait_timeout": "50s"
  }'
```

Replace `{first_measure_name}` with the first entry in the `measures:` list in the
generated YAML. If this returns an error, report it verbatim and do not silently skip.

Common errors at this stage and their causes:

| Error | Cause | Fix |
|---|---|---|
| Syntax error near `WITH METRICS` | Warehouse is on Current channel, not Preview | Switch warehouse to Preview channel |
| Table or view not found | Source table FQN is incorrect | Verify the `source:` value against Unity Catalog |
| Column not found | Physical column name mismatch | Check `db_column_name` vs actual column in source table |

**3. Report location:**

```
Metric View created successfully.

  Name:    {view_name}
  Catalog: {catalog}
  Schema:  {schema}
  Source:  {source_table}
  Dims:    {n} dimension(s)
  Metrics: {n} measure(s)
```

**4. Generate test questions:**

Generate 5 natural language questions derived from the Metric View. Use the actual
measures, dimensions, and their names from the DDL.

**Question design — aim for variety:**

| Type | Example pattern |
|---|---|
| Simple aggregation | "What is the total {measure} ?" |
| Breakdown | "What is {measure} by {dimension} ?" |
| Time trend | "How has {measure} changed over {date_dimension} ?" |
| Ranking | "Which {dimension} has the highest {measure} ?" |
| Filtered | "What is {measure} for {dimension value} ?" |

Present the questions as:

```
Test questions for {view_name}

1. {question}
2. {question}
3. {question}
4. {question}
5. {question}

───────────────────────────────────────────────
Databricks AI/BI
  In Databricks SQL editor: query the Metric View directly, or use AI/BI
  Genie with the view as a data source.

ThoughtSpot Spotter
  In your ThoughtSpot instance: open Spotter, select the original
  worksheet/model, and ask each question.
───────────────────────────────────────────────
```

**After completing a model — batch continuation:**

If the user originally requested multiple models and more remain, immediately offer
the next one without waiting to be asked:

```
{view_name} created in {catalog}.{schema}

Next up: {next_model_name}
  Ready to convert? (Y / N):
```

If yes: go directly to Step 2 (model selection is already known — skip straight to
Step 3: Export TML). Reuse the ThoughtSpot profile, Databricks profile, warehouse,
and target location from this session. Do **not** re-run Step 1 or Step 1.5 profile
prompts.

If no (or no more models remain): the session is complete. No token cleanup needed.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-07-09 | Dimension/metric semantic deep-dive (BL-063 PR1.5, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`). **New capability (A3, the MINOR):** `group_aggregate`'s `{}` filter argument, paired with a model-level `filters:` block mirroring the target MV's `filter:`, reproduces BOTH halves of the A1/A2 DBX composite (MV-`filter:`-aware AND query-time-`WHERE`-blind) in a single ThoughtSpot construct — corrects A1/A2's "no TS analogue" conclusion. `query_filters()` remains the default LOD mapping; `{}` + a mirrored model filter is the new option for reproducing a DBX consumer's ad hoc query-time-`WHERE`-blind LOD. Subtraction form `query_filters() - {col}` tested and found not to exclude a filter pinned on a derived boolean formula — recorded, not adopted. **Corrections/caveats:** LOD `query_filters()` dimension confirmed filter-aware on TS under both filter kinds, with the caveat that the equivalence holds for a Databricks MV's own global `filter:` only, not for a consumer's ad hoc query-time `WHERE` (A1/A2, refined by A3 above); cross-measure ratio inlining confirmed grain-safe at every grain, no caveat needed (B1); global `filter:` × window ordering confirmed filter-before-window on both platforms, with a new frame-semantics caveat — Databricks `trailing`/`leading` windows are date-interval framed while `moving_sum` is row-positional, so results diverge on sparse/gapped data (C1, same root cause as E1); semi-additive `last`/`first_value` under a date-range filter confirmed cross-platform (D1). |
| 1.0.3 | 2026-07-09 | Correct window translation tables to live-verified forms (claim matrix C1/C3/C6); see docs/audit/2026-07-08-dbx-window-claim-matrix.md. Fixes the Concept Mapping table (rolling window rows: `moving_sum(m,7,0,d)` was wrong — resolves to `trailing (N+1) day inclusive`, not `trailing N day`; the `leading N unit` PENDING row is now resolved to `moving_sum([m], -1, N, [d])`/inclusive `moving_sum([m], 0, N-1, [d])`, both live-verified) and the Step 7 period-filter decision tree/examples (adds the row-relative-vs-wall-clock lossy-approximation caveat for `offset`, corrected by matrix C6/C6a; quarter/year rows marked Deferred per C8). |
| 1.0.2 | 2026-07-03 | Product-currency fix (audit 2026-07-03, finding 13.7): flag ThoughtSpot `moving_sum`/`moving_average` with a non-zero look-ahead argument as PENDING LIVE VERIFICATION (candidate `range: leading N unit` emission) instead of silently falling through the `range: trailing N day` mapping. |
| 1.0.1 | 2026-07-03 | Replace the inline macOS-only Keychain token-refresh procedure with a pointer to `/ts-profile-thoughtspot` (U3 — Refresh Credential), the canonical cross-platform procedure (audit finding 11.4). |
| 1.0.0 | 2026-05-22 | Initial release — single conversion mode (Mode A) |
