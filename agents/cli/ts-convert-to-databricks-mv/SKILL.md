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

**Implemented by `ts databricks build-mv` (Step 5)** — this table documents the
translation rules the CLI applies, useful for interpreting its `skipped[]`/`warnings[]`
output and the generated `.sql`, not a checklist the model works through by hand.

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

**This section documents what `ts databricks build-mv` (Step 5) implements** — it is
reference material for reading the generated `.sql` output and troubleshooting, not a
manual procedure. The CLI, not the model, assembles the YAML and DDL below.

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
- SQL warehouse with `CAN USE` permission, running at or above the **minimum Databricks
  Runtime** the generated Metric View needs (see the tiered table below) — Unity Catalog
  Business Semantics (Metric Views) went **GA on 2026-04-02**; there is no Preview-channel
  requirement anymore
- Databricks CLI installed (`pip install databricks-cli` or `brew install databricks`)
- Profile configured — run `/ts-profile-databricks` if you haven't already

**Minimum Databricks Runtime (tiered, not a single floor).** Per
[../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md),
there is no blanket Runtime requirement — different features unlock at different tiers:

| Runtime | Unlocks | Applies to this skill's output |
|---|---|---|
| 16.4 | Baseline — Metric Views run at all | Never sufficient on its own — this skill always emits richer metadata |
| **17.3+** | Agent metadata (`display_name` / `comment` / `synonyms`) | **Always required** — every MV `ts databricks build-mv` emits uses v1.1 rich metadata |
| **18.1+** | Join `cardinality:` and window `offset:` | Required only if the model has an explicit `MANY_TO_ONE` join (emits `cardinality:`) or a period-over-period measure — prior month/quarter/year (emits window `offset:`) |
| 18.2+ | The `parameters:` block | Not applicable — this skill does not yet emit `parameters:` (logged in the Unmapped Report instead) |

A `PARSE_SYNTAX_ERROR` on a GA-era warehouse is **not** a channel problem — it means the
warehouse's Runtime is below the tier the failing field needs. See the error table in
Step 13.

**No Databricks access?** You can still run this skill in **file-only mode** — it generates
the DDL and writes it to a `.sql` file you can run manually in a Databricks SQL editor
later. Select **FILE** at the Step 10 checkpoint or say "file only" at any point before
Step 12.

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
  5.    Build the Metric View (ts databricks build-mv) ..... auto
 10.    Checkpoint — review generated DDL before execution .. you confirm
 12.    Execute DDL in Databricks .......................... auto
 13.    Verify creation and generate summary ................ auto

Step 5 is a single deterministic CLI call. `ts databricks build-mv` replaces the
previous agentic pipeline (map dimensions → map measures → translate formulas →
generate MV YAML → build DDL) — one command emits the finished `.sql` file(s);
nothing here is hand-assembled column-by-column anymore. The step numbers above
skip 6-9 and 11 deliberately — those steps no longer exist as separate work.

File-only mode: at Step 10, choose FILE instead of executing — reports the location
of the `.sql` file(s) `ts databricks build-mv` already wrote in Step 5, for manual
import in a Databricks SQL editor.

Confirmation required: Step 10 (DDL review)
Auto-executed: all others

Note: `ts databricks build-mv` requires a **Model** TML export — a Worksheet cannot
be routed through it yet. If the selected object exports as `worksheet`, Step 3 will
flag this before Step 5 runs.

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
databricks auth describe --profile {dbx_profile}
```

If authentication fails, direct the user to run `/ts-profile-databricks` to configure
their credentials.

**Warehouse selection:**

The user must provide a SQL warehouse ID. If not already known:

```bash
databricks api get /api/2.0/sql/warehouses \
  --profile {dbx_profile} | python3 -c "
import sys, json
whs = json.load(sys.stdin).get('warehouses', [])
for i, w in enumerate(whs, 1):
    state = w.get('state', 'UNKNOWN')
    print(f'  {i}. {w[\"name\"]}  id: {w[\"id\"]}  state: {state}')
"
```

```
Available SQL warehouses:
  1. dev-warehouse    id: abc123  state: RUNNING
  2. prod-warehouse   id: def456  state: STOPPED

Select a warehouse (or press Enter to use #1):
```

**Runtime floor check (replaces the old Preview-channel check — Metric Views are GA):**
Databricks does not expose a single "Runtime version" field on the SQL warehouse API the
way classic clusters expose one, so this is a confirmation, not an automated probe.
Show the tiered table from Prerequisites and ask:

```
This conversion emits agent metadata (display_name/comment/synonyms), which needs
Databricks Runtime 17.3+. If the model has period-over-period measures (prior
month/quarter/year) or an explicit MANY_TO_ONE join, 18.1+ is needed instead.

Confirm warehouse "{name}" meets that floor?
  Y — confirmed, proceed
  N — I'll upgrade the warehouse first
  ? — not sure, proceed anyway (a PARSE_SYNTAX_ERROR naming display_name/synonyms/
      offset/cardinality at Step 12 or 13 means the Runtime is below the tier that
      field needs — see the error table in Step 13)
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

```bash
ts tml export {selected_model_id} --profile {profile_name} --fqn --associated
```

**Batch mode — export all models in one call:**

When the user has selected multiple models for conversion, pass all GUIDs to a single
export call:

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
- **SQL view objects:** parsed YAML has top-level key `sql_view` — collect separately for handling in Step 4

**Model-only gate:** `ts databricks build-mv` (Step 5) reads Model TML (`model_tables[]`,
`columns[]`) — it does not understand Worksheet TML's `worksheet_columns[]` shape. If the
primary object's top-level key is `worksheet`, stop before Step 5 and tell the user this
deterministic path does not support Worksheets yet: either convert/promote the Worksheet
to a Model in ThoughtSpot first and re-run against the Model GUID, or treat this as a
manual conversion outside this skill. Do not attempt to hand-translate a Worksheet through
`build-mv` — it will misread the TML shape.

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

**`ts databricks build-mv` does not accept a `sql_view` object in `--tables`** — it reads
raw Table TML only. If the user chose **C** or **M** above, the resulting Databricks view
cannot be passed straight through Step 5's `build-mv` call; recommend **S (Skip)** instead
for the deterministic path and log it in the Unmapped Report as a manual follow-up. Leave
any `sql_view` object out of the `tables_export.json` file built in Step 5.

**Multi-table handling:**

If the model references multiple physical tables, `ts databricks build-mv` (Step 5)
handles this automatically — it is not something this skill assembles by hand anymore:

1. **Single fact + dimension joins:** `build-mv` expresses the star schema directly as
   nested `joins:` in v1.1 — the fact table is `source:`, dimension tables are nested
   `joins:`, and column references use dot-path (`dim_alias.COL`, `dim_alias.sub_dim.COL`).
2. **Multiple fact tables:** omit `--source-table` in Step 5 and `build-mv` emits one
   independent MV per detected fact table automatically (`metric_views[]` in its summary).
   **Caveat:** all facts in one invocation share the same `--catalog`/`--schema` (see
   Step 5) — if facts genuinely live in different catalogs/schemas, run `build-mv` once
   per fact with `--source-table` and the correct `--catalog`/`--schema` for that fact.
3. **Flattened SQL VIEW (fallback only):** for join structures `build-mv` cannot express
   as nested joins (e.g., many-to-many, cross-fact joins) — this is the sql_view case
   above, and is not automated; it needs manual handling outside `build-mv`.

See [../../shared/mappings/ts-databricks/ts-to-databricks-rules.md](../../shared/mappings/ts-databricks/ts-to-databricks-rules.md)
for the multi-table mapping rules `build-mv` implements.

See the [Dunder Mifflin worked example](../../shared/worked-examples/databricks/ts-to-databricks.md)
for a complete multi-fact split.

---

### Step 5: Build the Metric View (`ts databricks build-mv`)

This single deterministic CLI call replaces the previous agentic pipeline (map
ATTRIBUTE columns → map MEASURE columns → translate formulas → generate MV YAML →
build DDL — formerly Steps 5-9). Column classification, formula translation, join
assembly, window/semi-additive emission, and DDL generation are all handled inside
`ts databricks build-mv` — see the Concept Mapping and DDL Format Reference sections
above for what it implements. Nothing in this step is hand-assembled.

**1. Write the two JSON input files from the Step 3 export.**

`ts tml export {guid} --profile {profile_name} --fqn --associated --parse` returns a
list of `{"type": ..., "guid": ..., "tml": {...}, "info": {...}}` entries (Step 3).
Build:

- `/tmp/ts_tml_model_{guid}.json` — the `tml` value of the entry whose `type == "model"`,
  written verbatim (it is already shaped `{"model": {...}}`, optionally with a sibling
  `guid` key — `build-mv` ignores the sibling key).
- `/tmp/ts_tml_tables_{guid}.json` — a JSON **list** of the `tml` value of every entry
  whose `type == "table"` (each already shaped `{"table": {...}}`), written verbatim.
  **Omit every `sql_view` entry** — `build-mv` does not accept them (see the Step 4
  caveat); a `sql_view` in this list will crash the command with a `KeyError`-shaped
  failure, not a clean skip.

If the primary object's `type` is `worksheet`, do not proceed — see the Model-only
gate in Step 3.

**2. Determine `--catalog` / `--schema`.**

`build-mv` uses ONE `catalog`/`schema` pair for both (a) the FQN of the fact/source
table in the emitted `source:` field, and (b) the location where the `CREATE OR
REPLACE VIEW` will register the Metric View — it does not read the fact table's own
`db`/`schema` from Table TML the way it does for joined dimension tables. Default to
the fact table's own `db`/`schema` from the Step 4 table map (this is also where the
view will be created); offer to override if the user wants the MV registered
elsewhere, but note that overriding **also changes the `source:` FQN** — there is no
way to decouple "where the view lives" from "where its source table is" in this
command.

```
Metric View will be built against:
  Catalog: {catalog}   (source table location)
  Schema:  {schema}

Use this, or enter a different catalog/schema? Note: this also changes the
source: FQN in the generated DDL, not just where the view is created.
```

For a **multi-fact model** where facts live in different catalogs/schemas, run
`build-mv` once per fact with `--source-table` and that fact's own catalog/schema
(see Step 4's multi-table handling) rather than one call covering all facts.

**3. Run the command:**

```bash
ts databricks build-mv \
  --model /tmp/ts_tml_model_{guid}.json \
  --tables /tmp/ts_tml_tables_{guid}.json \
  --catalog {catalog} --schema {schema} \
  --output-dir {output_dir} \
  [--source-table {fact_table_name}] [--view-name {override_name}]
```

- Omit `--source-table` to let `build-mv` split a multi-fact model into one MV per
  detected fact table automatically.
- **`--view-name` is silently ignored on a multi-fact split** — it only applies when
  exactly one fact table is being emitted (either `--source-table` was given, or the
  model has just one detected fact). On a multi-fact split, every MV keeps its
  `default_view_name(model_name, fact)` name; there is no per-fact override flag today.
  If a custom name is needed for one MV in a multi-fact model, rename it manually after
  Step 5 (in the `.sql` file and its `CREATE OR REPLACE VIEW` line) or re-run with
  `--source-table` scoped to that one fact.
- `--output-dir`: use the same location Step 12-FILE would otherwise pick — a
  `metric-views/` or `output/` subdirectory of the current working directory if one
  exists, else the current directory. The `.sql` file(s) are written here now, at
  Step 5, not later — Steps 10/12/12-FILE/13 read this file, they do not write it.
  This command has **no `--profile` flag** — it is emit-only (no ThoughtSpot or
  Databricks connection is used or needed) and never executes DDL itself.

**4. Read the summary JSON from stdout** — `{model_name, metric_views: [{view_name,
source, dimensions, measures, filter_applied, file}], skipped: [], warnings: []}`.

For each entry in `metric_views[]`, read `file` to get the generated DDL text for
the Step 10 review. `skipped[]` and `warnings[]` are shared across the whole model
(not per-view) — carry them into Step 10 as:

- **`skipped[]` → Unmapped Report.** Each entry is `{role, name, reason}` — an
  untranslatable formula, a dangling cross-reference, or a column whose joined
  table was missing from `--tables`. Present these as the Formula Translation Log /
  "Other dropped properties" sections Step 10 already documents.
- **`warnings[]` → filter-classification confirmations.** Genuine advisories (e.g. a
  boolean formula routed to the MV's `filter:` field, or a sparse-data risk on a
  trailing/leading window) that are not simply duplicates of a `skipped[]` reason —
  the CLI itself de-dupes these on stderr; treat the stdout summary's `warnings[]`
  the same way when presenting to the user.

**5. Handle a non-zero exit.** `build-mv` exits 1 (with a message on stderr) when:
- no fact table can be detected — ask the user to supply `--source-table` explicitly
- a produced MV would have zero measures
- a structural error occurs (e.g. a joined table referenced by the model is missing
  from `--tables`, or two columns would emit the same `name`)

Show the stderr message verbatim and ask the user how to proceed (re-export with the
missing table, fix the model in ThoughtSpot, or supply `--source-table`) — do not
retry automatically and do not attempt to patch the JSON inputs by hand to work
around a structural error; fix the root cause (see `.claude/rules/ts-cli.md`).

**6. Clean up the input JSON files** (they contain sensitive schema metadata —
table names, column descriptions, join conditions, AI context — and are not needed
after `build-mv` has read them). **Do not delete the `.sql` output files** — Steps
10, 12, 12-FILE, and 13 all read them.

```bash
rm -f /tmp/ts_tml_model_*.json /tmp/ts_tml_tables_*.json
```

---

### Step 10: CHECKPOINT — Review with User

**Do not proceed without explicit user confirmation.**

Present the following sections. If `build-mv` produced more than one entry in
`metric_views[]` (a multi-fact model), repeat sections 1-2 per entry.

**1. Generated DDL** — the contents of each `metric_views[].file`, in a SQL code block.

**2. Conversion Summary** (from the `metric_views[]` entry — `source`, `dimensions`,
`measures`, `filter_applied` are read directly off the summary JSON, not recomputed):
```
- View name:        {view_name}
- Source:           {source}
- Dimensions:       {dimensions}
- Measures:         {measures}
- Global filter:    {filter_applied}
- Omitted columns:  {n}  (from summary.skipped — see Unmapped Report below)
```

**3. Unmapped Properties Report** — built from `summary.skipped[]` and
`summary.warnings[]` (Step 5), in the format defined in
[../../shared/mappings/ts-databricks/ts-databricks-properties.md](../../shared/mappings/ts-databricks/ts-databricks-properties.md).
Include only sections that have entries. Common sections:
- AI Context not migrated (no MV equivalent)
- Parameters not yet migrated (MV `parameters:` GA at Runtime 18.2+; emission deferred — audit 13.2)
- Column groups not migrated
- Format patterns not migrated
- Formula Translation Log (from `skipped[]` — role, name, reason per omitted column)
- SQL Views resolved or skipped (from Step 4's manual classification — `build-mv` does
  not see these; they were excluded from `tables_export.json` before Step 5 ran)
- Filter-classification / sparse-data-risk confirmations (from `warnings[]`)
- Other dropped properties

---

**Prompt:**
```
Shall I create this Metric View in Databricks?
  YES  — proceed
  NO   — cancel
  EDIT — followed by changes to the generated .sql file
  FILE — leave the .sql file(s) as-is, without executing
```

If the user selects **EDIT**, apply the requested change directly to the `.sql` file(s)
`build-mv` wrote in Step 5 (e.g. rename the view, add a synonym, adjust a comment) —
there is no YAML to regenerate; edit the text in place. After any manual edit, re-check
that the YAML body between the `$$ ... $$` markers still parses as valid YAML and
contains no literal `$$` substring — `build-mv`'s own `$$`-collision guard
(`mv_build_view.build_view_ddl`) only runs at generation time, so a hand-edit that
introduces a stray `$$` or breaks YAML indentation/quoting would silently corrupt or
truncate the dollar-quoted DDL at execution time and isn't caught automatically.

If the user selects **NO**, stop. No cleanup needed — the CLI manages its own token
cache, and the `.sql` file(s) remain on disk for later use.

If the user selects **FILE**, skip to [Step 12-FILE](#step-12-file-output-ddl-file-only-mode).

---

### Step 12-FILE: Output DDL file (file-only mode)

This path is used when the user selected **FILE** at the Step 10 checkpoint, explicitly
said "file only", or has no Databricks access.

**The `.sql` file(s) already exist** — `ts databricks build-mv` wrote them in Step 5
(one per `metric_views[]` entry, at the path in `metric_views[].file`). This path does
not write anything new; it only reports what is already on disk.

**1. Report the location(s):**

```
Metric View DDL written to: {metric_views[0].file}
{...one line per entry, if the model split into multiple MVs...}

To create it in Databricks when you have access, repeat the following once per
`metric_views[]` entry, using that entry's own `file` path — not a guessed
`{view_name}.sql` in the current directory (a multi-fact split, or a non-default
`--output-dir`, means the real path may differ):

  1. In Databricks SQL editor, set the catalog and schema context,
     and paste + run the contents of {metric_views[i].file}.

  2. Or via Databricks CLI:
       databricks api post /api/2.0/sql/statements \
         --profile {dbx_profile} \
         --json "$(python3 -c "
import json
ddl = open('{metric_views[i].file}').read()
print(json.dumps({'warehouse_id': '{warehouse_id}', 'statement': ddl, 'wait_timeout': '50s'}))
")"
```

The target catalog/schema is whatever was passed to `--catalog`/`--schema` in Step 5
(already baked into the file's `CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}`
line and its `source:` value) — there is no separate location choice at this stage.

**2. Proceed to Step 13** (Verify and Generate Summary) — the summary helps the user
know what to verify once they create the view.

---

### Step 12: Execute

**No target-location prompt here** — the catalog/schema were already fixed when
`build-mv` wrote the `.sql` file(s) in Step 5 (see Step 5's "Determine `--catalog` /
`--schema`" note). This step only executes the DDL that is already on disk.

**Execute the DDL via the Statement Execution API, once per `metric_views[]` entry:**

```bash
databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json "$(python3 -c "
import json
ddl = open('{metric_views[i].file}').read()
print(json.dumps({'warehouse_id': '{warehouse_id}', 'statement': ddl, 'wait_timeout': '50s'}))
")"
```

Reading the file's exact bytes and JSON-encoding it via `json.dumps` (rather than
hand-escaping quotes/newlines in a shell string) avoids escaping mistakes — `$$` and
embedded newlines round-trip correctly this way.

**Response handling:**

Check the `status.state` field in the response:
- `SUCCEEDED` → proceed to the next `metric_views[]` entry, then Step 13 once all are done
- `FAILED` → show `status.error.message` verbatim; ask the user what to do. A message
  naming `display_name`, `synonyms`, `offset`, or `cardinality` as unrecognized is a
  Runtime-tier gap (see the Prerequisites tiered table), not a DDL bug — do not edit the
  `.sql` file to work around it, direct the user to upgrade the warehouse's Runtime instead.
- `PENDING` / `RUNNING` → poll with:
  ```bash
  databricks api get /api/2.0/sql/statements/{statement_id} \
    --profile {dbx_profile}
  ```

On success: report the created view name and location.
On failure: show the full Databricks error. Do not retry automatically — ask the user.

**Cleanup:**

No ThoughtSpot token cleanup needed — the CLI manages its own cache automatically.
The `.sql` file(s) are the user's record of what was created — leave them in place
(the Step 5 cleanup already removed the sensitive intermediate TML JSON).

---

### Step 13: Verify Creation and Generate Summary

After a successful execution, confirm the view exists and generate a summary. Repeat
this whole step once per `metric_views[]` entry created in Step 12.

**1. Verify the view exists:**

```bash
databricks api post /api/2.0/sql/statements \
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
databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "SELECT {first_measure_name} FROM {catalog}.{schema}.{view_name} LIMIT 1",
    "wait_timeout": "50s"
  }'
```

Replace `{first_measure_name}` with the first entry in the `measures:` list of the
generated `.sql` file. If this returns an error, report it verbatim and do not silently skip.

Common errors at this stage and their causes:

| Error | Cause | Fix |
|---|---|---|
| `PARSE_SYNTAX_ERROR` naming `display_name`, `synonyms`, `comment`, `offset`, or `cardinality` | Warehouse's Databricks Runtime is below the tier that field needs (see the tiered table in Prerequisites) | Upgrade the warehouse's Runtime to at least 17.3 (metadata) / 18.1 (offset or cardinality) |
| Syntax error near `WITH METRICS` for another reason | Malformed DDL — unexpected on `build-mv` output; treat as a CLI bug, not a manual fix | Fix `tools/ts-cli/` and re-run `build-mv` (see `.claude/rules/ts-cli.md`) — do not hand-patch the `.sql` file |
| Table or view not found | Source table FQN is incorrect | Verify the `source:` value against Unity Catalog — was the wrong `--catalog`/`--schema` passed in Step 5? |
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
| 1.3.0 | 2026-07-23 | Role-playing (aliased) dimension support (ts-cli v0.91.0): a Model that joins one physical table under multiple aliases (role-play) now emits distinct MV join nodes with correct dot-paths, and each role-play's dimensions/measures survive (the column index is mirrored under the alias key, so `[ON_BEHALF_ACCOUNT::NAME]` resolves instead of being dropped). Previously `build-mv` errored ("no table definition for <alias>") or silently dropped role-play dimensions. Verified on SUPPORT_CASE (ACCOUNT×2, SUPPORT_PRODUCT__C×2 → distinct join nodes + all role-play dims emitted). |
| 1.2.0 | 2026-07-18 | Codify MV emission via `ts databricks build-mv` (deterministic tokenizer→AST→Databricks-SQL translator; LOD/window/cross-measure/filter); reconcile Preview→tiered Databricks Runtime; live numeric-fidelity verified. |
| 1.1.1 | 2026-07-11 | Correct MV `parameters:` GA (Runtime 18.2+, mutually exclusive with materialization) + tiered runtime; TS→MV parameter emission deferred (audit 13.1/13.10/13.2). Minor cleanup: dedup duplicate "AI Context not migrated" bullet in the Unmapped Properties Report list. |
| 1.1.0 | 2026-07-09 | Dimension/metric semantic deep-dive (BL-063 PR1.5, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`). **New capability (A3, the MINOR):** `group_aggregate`'s `{}` filter argument, paired with a model-level `filters:` block mirroring the target MV's `filter:`, reproduces BOTH halves of the A1/A2 DBX composite (MV-`filter:`-aware AND query-time-`WHERE`-blind) in a single ThoughtSpot construct — corrects A1/A2's "no TS analogue" conclusion. `query_filters()` remains the default LOD mapping; `{}` + a mirrored model filter is the new option for reproducing a DBX consumer's ad hoc query-time-`WHERE`-blind LOD. Subtraction form `query_filters() - {col}` tested and found not to exclude a filter pinned on a derived boolean formula — recorded, not adopted. **Corrections/caveats:** LOD `query_filters()` dimension confirmed filter-aware on TS under both filter kinds, with the caveat that the equivalence holds for a Databricks MV's own global `filter:` only, not for a consumer's ad hoc query-time `WHERE` (A1/A2, refined by A3 above); cross-measure ratio inlining confirmed grain-safe at every grain, no caveat needed (B1); global `filter:` × window ordering confirmed filter-before-window on both platforms, with a new frame-semantics caveat — Databricks `trailing`/`leading` windows are date-interval framed while `moving_sum` is row-positional, so results diverge on sparse/gapped data (C1, same root cause as E1); semi-additive `last`/`first_value` under a date-range filter confirmed cross-platform (D1). |
| 1.0.3 | 2026-07-09 | Correct window translation tables to live-verified forms (claim matrix C1/C3/C6); see docs/audit/2026-07-08-dbx-window-claim-matrix.md. Fixes the Concept Mapping table (rolling window rows: `moving_sum(m,7,0,d)` was wrong — resolves to `trailing (N+1) day inclusive`, not `trailing N day`; the `leading N unit` PENDING row is now resolved to `moving_sum([m], -1, N, [d])`/inclusive `moving_sum([m], 0, N-1, [d])`, both live-verified) and the Step 7 period-filter decision tree/examples (adds the row-relative-vs-wall-clock lossy-approximation caveat for `offset`, corrected by matrix C6/C6a; quarter/year rows marked Deferred per C8). |
| 1.0.2 | 2026-07-03 | Product-currency fix (audit 2026-07-03, finding 13.7): flag ThoughtSpot `moving_sum`/`moving_average` with a non-zero look-ahead argument as PENDING LIVE VERIFICATION (candidate `range: leading N unit` emission) instead of silently falling through the `range: trailing N day` mapping. |
| 1.0.1 | 2026-07-03 | Replace the inline macOS-only Keychain token-refresh procedure with a pointer to `/ts-profile-thoughtspot` (U3 — Refresh Credential), the canonical cross-platform procedure (audit finding 11.4). |
| 1.0.0 | 2026-05-22 | Initial release — single conversion mode (Mode A) |
