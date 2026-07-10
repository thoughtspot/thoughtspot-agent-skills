---
name: ts-convert-from-databricks-mv
description: Convert or import a Databricks Metric View into ThoughtSpot as a Model. Use when Databricks is the source and the goal is a ThoughtSpot Model — whether migrating Databricks metrics and semantic definitions into ThoughtSpot or making a Metric View available for Spotter and search-based analytics. Direction is always Databricks → ThoughtSpot. Not for ThoughtSpot → Databricks, standalone DDL generation, or adding AI context to existing ThoughtSpot models.
---

# Databricks Metric View → ThoughtSpot Model

Converts a Databricks Unity Catalog Metric View into a ThoughtSpot Model. Reads the
Metric View YAML definition via `DESCRIBE TABLE EXTENDED`, maps dimensions and measures
to ThoughtSpot columns and formulas, translates SQL expressions, and imports the result
via `ts tml import`.

Two scenarios are supported:
- **Scenario A (existing tables):** ThoughtSpot Table objects already exist for the
  Databricks source table(s) the Metric View references. Reuses those existing Table objects.
- **Scenario B (new tables):** No ThoughtSpot Table objects exist yet for the Databricks
  source table(s). Creates new Table objects pointing to those objects.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md) | Databricks MV YAML parsing, type mapping, formula translation, column classification |
| [../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md) | SQL → ThoughtSpot formula translation rules (bidirectional reference) |
| [../../shared/mappings/ts-databricks/ts-databricks-properties.md](../../shared/mappings/ts-databricks/ts-databricks-properties.md) | Property coverage — what maps, what doesn't, what is partially migrated |
| [../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md) | Databricks Metric View YAML schema (v0.1 single-source, v1.1 multi-source) |
| [../../shared/schemas/thoughtspot-tml.md](../../shared/schemas/thoughtspot-tml.md) | TML export parsing (PyYAML pitfalls, type detection) |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure, connection reference, data types, import patterns, common errors |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure, join scenarios, formula visibility, self-validation checklist |
| [../../shared/schemas/thoughtspot-sql-view-tml.md](../../shared/schemas/thoughtspot-sql-view-tml.md) | SQL View TML structure — `sql_view:` type for subquery sources |
| [../../shared/schemas/thoughtspot-formula-patterns.md](../../shared/schemas/thoughtspot-formula-patterns.md) | ThoughtSpot formula syntax, all function categories, LOD/window patterns, YAML encoding rules |
| [../ts-profile-databricks/SKILL.md](../ts-profile-databricks/SKILL.md) | Databricks auth methods, profile config, CLI usage |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| [../../shared/worked-examples/databricks/ts-to-databricks.md](../../shared/worked-examples/databricks/ts-to-databricks.md) | End-to-end Dunder Mifflin conversion: LOD dimensions, semi-additive, cross-measure ratios, multi-fact split |
| [../../shared/worked-examples/databricks/ts-from-databricks.md](../../shared/worked-examples/databricks/ts-from-databricks.md) | End-to-end MV → Model conversion: direct + computed dimensions, simple + ratio + window + conditional measures |
| [../../shared/worked-examples/databricks/ts-from-databricks-sql-view.md](../../shared/worked-examples/databricks/ts-from-databricks-sql-view.md) | Subquery source path: SQL View TML + Model on top |

---

## Concept Mapping

| Databricks Metric View YAML | ThoughtSpot Model |
|---|---|
| `source:` (table FQN, SQL query, or another metric view — 4 forms, see schema) | Table FQN → Single Table TML (`db_table`, `db`, `schema` decomposed from the FQN); SQL query → see `source:` as SELECT subquery row below; another metric view → **fail loud** (MV-on-MV chaining is not supported) |
| Top-level `comment:` (v1.1) | Model `description` |
| `dimensions[].expr` (direct column reference) | `columns[]` with `column_type: ATTRIBUTE` |
| `dimensions[].expr` (computed expression) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `dimensions[].expr` (window function — LOD) | LOD `formulas[]` entry: `group_aggregate(agg([col]), {[dim]}, query_filters())` — 3 args required. **Live-verified 2026-07-09** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, A1/A2): this is filter-aware on TS under both filter kinds, and reproduces a Databricks MV's own global `filter:` — but NOT an ad hoc query-time `WHERE` on an MV with no global filter (DBX-side asymmetry, not fixable by formula), **unless** the emitted formula uses `{}` instead of `query_filters()` paired with a model-level `filters:` block mirroring the MV's `filter:` — that combination reproduces both DBX conditions (A3 follow-up, same matrix, live-verified 2026-07-09) |
| `dimensions[].display_name` (v1.1) | Column `name` (display name) |
| `dimensions[].comment` (v1.1) | Column `description` |
| `dimensions[].synonyms` (v1.1) | `properties.synonyms[]` + `properties.synonym_type: USER_DEFINED` |
| `measures[].expr` (simple `AGG(col)` — SUM, AVG, MIN, MAX, COUNT) | `columns[]` with `column_type: MEASURE` + extracted `aggregation` |
| `measures[].expr` (`COUNT(DISTINCT col)`) | `formulas[]` entry: `unique count ( [TABLE::col] )` — NOT `aggregation: COUNT_DISTINCT` on a `column_id` (TS silently overrides to ATTRIBUTE) |
| `measures[].expr` (complex — ratios, nested aggregates) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `measures[].expr` with `MEASURE()`/`ANY_VALUE()` | Cross-measure formula — **inline** the referenced expressions (cross-refs fail during TML import). **Live-verified 2026-07-09 across query grain** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, B1) — CONFIRMED true ratio-of-sums, cross-platform, at every grain; no grain caveat needed |
| `measures[].window`, `order:` raw date (semi-additive) | `last_value ( sum ( [m] ) , query_groups ( ) , { [date] } )` / `first_value ( ... )` — snapshot metrics (inventory, balance). **Live-verified 2026-07-09**, `docs/audit/2026-07-08-dbx-window-claim-matrix.md` C7. **Also live-verified 2026-07-09 under a query-time date-range filter** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, D1) — CONFIRMED cross-platform, collapses to last/first-in-filtered-range on both platforms |
| `measures[].window`, `order:` truncated period (period filter), no `offset` | `sum ( [m] )` at the query grain — flow metrics (revenue, qty). **Live-verified 2026-07-09**, matrix C6 |
| `measures[].window`, `order:` truncated period, `offset: -N <unit>` | `moving_sum ( [m] , N , -N , [date] )` — row-relative `LAG(N)` idiom, **NOT** a wall-clock filter; valid only when the query returns exactly one row per period. **Live-verified 2026-07-09 at month grain, N=1** (matrix C6/C6a); quarter/year grains and N>1 are Deferred (C8) extrapolations of the same idiom. Corrects the pre-2026-07-09 `sum_if(diff_months/quarters/years([date], today())=N, [m])` mapping, which was WRONG for any multi-period query |
| `measures[].window` with `range: trailing N day` (default/exclusive) | `moving_sum([m], N, -1, [date])` — rolling look-back window, anchor excluded. **Live-verified 2026-07-09**, matrix C1/C2. **Density caveat (E1):** row-positional — matches only when the order column is dense at the window's unit grain (one row per unit, no gaps); see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` (E1) |
| `measures[].window` with `range: trailing N day inclusive` | `moving_sum([m], N-1, 0, [date])` — anchor included. **Live-verified 2026-07-09**, matrix C1. Same E1 density caveat as above |
| `measures[].window` with `range: leading N day` (default/exclusive) | `moving_sum([m], -1, N, [date])` — rolling look-ahead window, anchor excluded. **Live-verified 2026-07-09**, matrix C3. Same E1 density caveat as above |
| `measures[].window` with `range: leading N day inclusive` | `moving_sum([m], 0, N-1, [date])` — anchor included. **Live-verified 2026-07-09**, matrix C3. Same E1 density caveat as above |
| `measures[].window` with `range: cumulative` | `cumulative_sum([m], [date])`. **Live-verified 2026-07-09**, matrix C5 |
| `measures[].window` with `range: all` | `group_aggregate(sum([m]), {partition dims}, query_filters())`, `column_type: ATTRIBUTE` — unbounded partition window, scoped per query partition. **Live-verified 2026-07-09**, matrix C4. Inherits the same A1/A2 filter asymmetry as the LOD row above (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`), including its A3 `{}` + model-filter refinement |
| `measures[].window` with `inclusive`/`exclusive` anchor modifier | Default is `exclusive`, confirmed. Applies only to `trailing`/`leading`. **Live-verified 2026-07-09**, matrix C1/C2/C3 |
| `measures[].expr` with `FILTER (WHERE cond)` | `agg_if ( cond , [x] )` — native `*_if` conditional aggregate (e.g., `sum_if`, `unique_count_if`) |
| `COUNT(*)` | Formula: `count ( 1 )` |
| `fields[]` (GA alias for `dimensions[]`) | Same mapping as `dimensions[]` above — `fields:` is checked first, `dimensions:` is the fallback |
| Growth % (MoM, QoQ, YoY) | Inline `sum([m])` and `moving_sum([m], N, -N, [date])` expressions for both periods — cross-formula refs not supported during TML import |
| `joins:` (nested hierarchy) | One Table TML per source; model `joins[]` from parent→child hierarchy |
| `joins[]."on"` or `joins[].using` (exactly one present) | `on` → join expression as-is; `using: [COL, ...]` → `[A::COL] = [B::COL]` (AND-joined for multiple columns) |
| `filter:` (any) | Boolean formula column `[MV Filter]` — users apply `[MV Filter] = true`. Always create, never description-only. **Live-verified 2026-07-09** (`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`, C1): filter ordering is CONFIRMED cross-platform — a model-level `filters:` block filters rows before a windowed measure computes, matching a Databricks MV's own global `filter:`. Frame semantics on windowed measures still DIVERGE on gapped data — see the density caveat on the trailing/leading rows above (E1) |
| Subquery in `expr` | **Untranslatable** — log in Unmapped Report |
| `source:` as SELECT subquery (parenthesized `(SELECT ...)` or bare `SELECT ...`/`WITH ...`) | Prompt user: (D) create Databricks VIEW, (T) create ThoughtSpot SQL View, (M) map to existing, (S) skip |
| `source:` as another metric view (MV-on-MV) | **Fail loud** — not supported; ask the user to convert the upstream MV first or flatten the chain in Databricks |
| `version:` | Drives parsing path (v0.1 vs v1.1) — not stored in ThoughtSpot |

**Key structural rules:**
- `column_id` must use the **column name from the ThoughtSpot Table TML**. Export
  Table TMLs to confirm — do not assume they match the Metric View column names.
- Simple measures (`AGG(col)` — one column, one aggregate) → `MEASURE` column.
  Complex expressions → `formulas[]` entry.
- In Scenario A, the Table TML already exists — reuse its GUID and column names.
- In Scenario B, create a new Table TML from the Databricks schema introspection.
- v1.1 MVs provide `display_name`, `comment`, and `synonyms` — map `display_name` to
  column `name`, `comment` to `description`, and `synonyms` to `properties.synonyms`
  (with `properties.synonym_type: USER_DEFINED`). Synonyms at the column root level
  are silently dropped on import. v0.1 MVs only have `name` and `expr`.
- LOD dimensions (with `AGG() OVER (PARTITION BY ...)`) map to ThoughtSpot
  `group_aggregate()` formulas — always 3 arguments: `group_aggregate(expr, {query}, query_filters())`.
- Cross-measure references (`MEASURE(name)`, `ANY_VALUE(dim)`) must be **inlined** as
  full expressions during TML import — `[name]` cross-references fail during import
  (open-items #4). After import, users can simplify formulas in the ThoughtSpot UI.
- **Duplicate column_id:** when the same physical column appears as both an ATTRIBUTE
  dimension and a MEASURE (e.g., `COUNT(col)`), convert the measure to a formula to
  avoid the "unique column_id" import error (open-items #2).

---

## Prerequisites

### ThoughtSpot

- ThoughtSpot Cloud instance, REST API v2 enabled
- User account with `DATAMANAGEMENT` or `DEVELOPER` privilege — **only required for import**
- Authentication configured — run `/ts-profile-thoughtspot` if you haven't already
- The `ts` CLI installed (`pip install -e /path/to/tools/ts-cli`)

**No ThoughtSpot import access?** You can still run this skill in **file-only mode** —
it generates the Table and Model TML files for you to import manually. Select **FILE**
at the Step 10 checkpoint or say "file only" at any point before Step 11.

### Databricks

- Databricks workspace with **Unity Catalog** enabled
- SQL warehouse on the **Preview channel** — Metric Views are a Preview feature;
  Current channel warehouses return `PARSE_SYNTAX_ERROR`
- Databricks CLI installed and profile configured — run `/ts-profile-databricks` if
  you haven't already
- A Databricks connection configured in ThoughtSpot (required for Scenario B table creation)

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
**ts-convert-from-databricks-mv** — convert a Databricks Metric View into a ThoughtSpot Model, translating dimensions, measures, and SQL expressions.

Steps:
  1.   Authenticate (ThoughtSpot + Databricks) .............. auto
  2.   List Metric Views in the catalog ..................... auto
  3.   Select a Metric View ................................. you choose
  4.   Fetch the Metric View definition ..................... auto
  5.   Parse the YAML (dimensions, measures, filter) ........ auto
  6.   Map to ThoughtSpot columns + translate expressions .... auto
  7.   Table registration question (reuse or create) ........ you choose
  8.   Discover / create ThoughtSpot Table objects ........... auto (may ask for clarification)
  9.   Build Table + Model TML — ts databricks build-model .... auto
  9.5. Confirm Spotter enablement (re-run build-model + flag) . you choose
 10.   Review checkpoint — inspect TML before import ......... you confirm
 11.   Import Model TML — ts databricks build-model --profile . auto
 12.   Verify import and produce summary report .............. auto

File-only mode: at Step 10, choose FILE to write TML files for manual import.

Confirmation required: Steps 3, 7, 9.5, 10
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If profiles were already confirmed earlier in this conversation
(e.g. for a previous Metric View), skip this step and reuse them.

**ThoughtSpot profile:**
1. Run `ts profiles list` to show configured profiles.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and confirm before proceeding.
4. Verify: `ts auth whoami --profile {name}` — print display_name and base URL.

**Databricks profile:**

Load the profile from `~/.claude/databricks-profiles.json`:

```python
import json, os

profiles_path = os.path.expanduser("~/.claude/databricks-profiles.json")
with open(profiles_path) as f:
    profiles = json.load(f)

# Display profiles for selection
for i, p in enumerate(profiles, 1):
    print(f"  {i}. {p['name']}  ({p.get('host', '')})")

profile = next(p for p in profiles if p["name"] == "{profile_name}")
dbx_profile = profile["dbx_profile"]
catalog = profile.get("default_catalog", "")
warehouse_path = profile.get("sql_warehouse_http_path", "")
warehouse_id = warehouse_path.rstrip("/").split("/")[-1] if warehouse_path else ""
```

Verify connectivity:

```bash
source ~/.zshenv && databricks auth describe --profile {dbx_profile}
```

Store `dbx_profile`, `catalog`, and `warehouse_id` for use in subsequent steps.

---

### SQL execution pattern

All Databricks SQL in this skill uses the Statement Execution API:

```bash
source ~/.zshenv && databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{"warehouse_id": "{warehouse_id}", "statement": "{sql}", "wait_timeout": "50s"}'
```

The response contains:
```json
{
  "status": {"state": "SUCCEEDED"},
  "manifest": {"schema": {"columns": [...]}},
  "result": {"data_array": [[...], ...]}
}
```

If `status.state` is `PENDING`, poll the statement ID:
```bash
source ~/.zshenv && databricks api get /api/2.0/sql/statements/{statement_id} --profile {dbx_profile}
```

---

### Step 2: List Metric Views

Query the catalog for available Metric Views:

```sql
SELECT table_catalog, table_schema, table_name
FROM system.information_schema.tables
WHERE table_type = 'METRIC_VIEW'
  AND table_catalog = '{catalog}'
```

Execute via the SQL execution pattern above. Display results as a numbered list:

```
Metric Views in {catalog}:
  1. {schema}.{view_name_1}
  2. {schema}.{view_name_2}
  ...
```

If no Metric Views are found, check:
- The catalog name is correct
- The SQL warehouse is on the Preview channel
- The user's role has `USE CATALOG` and `USE SCHEMA` grants

---

### Step 3: Select a Metric View

If the user has already named a Metric View, skip this step.

Otherwise, ask the user to select from the list displayed in Step 2 (enter a number
or type a fully qualified `catalog.schema.view_name` directly).

Store the selected `{catalog}`, `{schema}`, and `{view_name}` for subsequent steps.

---

### Step 4: Fetch the Metric View definition

Retrieve the YAML definition via `DESCRIBE TABLE EXTENDED`:

```sql
DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}
```

Execute via the SQL execution pattern. Parse the response `result.data_array` — each
row is `[col_name, data_type, comment, metadata]`.

Extract the definition:
1. Find the row where `col_name == 'View Text'` — the `data_type` column contains
   the full YAML string.
2. Find the row where `col_name == 'Type'` — confirm `data_type == 'METRIC_VIEW'`.
3. Store the YAML string for parsing in Step 5.

If the query fails with "table or view not found", verify the fully-qualified name
and confirm the user's role has `SELECT` on the view.

---

### Step 5: Parse the YAML — `ts databricks parse-mv`

Parse the YAML string extracted in Step 4 with the deterministic parser (schema:
[../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md)):

```bash
printf '%s' "$MV_YAML" > mv.yaml
source ~/.zshenv && ts databricks parse-mv mv.yaml --output parsed.json
```

The command handles version routing (0.1 / 1.1), `fields:`/`dimensions:` aliasing,
dimension/measure classification (including `window:` and its 5 `range` values),
the nested `joins:` walk (`on`/`using`, `cardinality`/`rely` precedence), the
`materialization:` block, and metadata pass-through. It prints `WARNING:` lines
(e.g. BL-098 density checks) on stderr.

**Exit 1 with `unsupported[]`:** the JSON is still written; each entry names the
construct and why. Show the list to the user and ask whether to skip this MV
(log to the Unmapped Report) or handle the construct manually. Never continue
silently past a non-empty `unsupported[]`.

Read `parsed.json` and branch on `source.kind`:

- **`sql_query`** — the source is a SELECT subquery. Present the (D / T / M / S)
  options below.
- **`table_fqn` with `needs_live_check: true`** — run the MV-on-MV live check
  below before treating it as a physical table. The same check applies to every
  `joins[].source`.

Present these options to the user:

| Option | Action |
|---|---|
| **(D)** Create Databricks VIEW | Execute `CREATE VIEW catalog.schema.view_name AS {source}` in Databricks, then use the new view as a regular table FQN. Re-enter Step 5 with the new FQN. |
| **(T)** Create ThoughtSpot SQL View | Build a `sql_view:` TML that runs the source SQL against the Databricks connection, import it, then build a Model on top. See **Step 5T** below. |
| **(M)** Map to existing | User provides an existing ThoughtSpot Table/View name — skip table creation, proceed to Model. |
| **(S)** Skip | Log the MV to the Unmapped Report and continue to the next MV. |

If the user selects **(T)**, proceed to **Step 5T**. Otherwise continue with the
selected option. For **(D)**, **(M)**, and **(S)**, the rest of Step 5 proceeds as normal
(or skips).

**Step 5T — Build a ThoughtSpot SQL View from a subquery source:**

See [../../shared/schemas/thoughtspot-sql-view-tml.md](../../shared/schemas/thoughtspot-sql-view-tml.md)
for the full TML reference.

1. Read `source.raw` and `filter` from `parsed.json`, then construct the SQL query:
   ```python
   sql_query = parsed["source"]["raw"]  # the SELECT statement
   if parsed.get("filter"):
       sql_query = f"SELECT * FROM ({parsed['source']['raw']}) _mv WHERE {parsed['filter']}"
   ```

2. Introspect the query columns. Execute the query with `LIMIT 0` via the Statement
   Execution API to retrieve the column schema without returning data:
   ```sql
   SELECT * FROM ({sql_query}) _cols LIMIT 0
   ```
   Parse `manifest.schema.columns` from the response — each entry has `name` and
   `type_name`.

3. Build the `sql_view:` TML:
   ```yaml
   sql_view:
     name: "{model_name}"
     description: "SQL View for Databricks MV {mv_fqn}. Source: {source_fqn}"
     connection:
       name: "{databricks_connection_name}"
     sql_query: "{sql_query}"
     sql_view_columns:
     - name: "{col_name}"
       sql_output_column: "{col_name}"
       properties:
         column_type: ATTRIBUTE   # or MEASURE for numeric columns used in aggregation
   ```

4. Import via `ts tml import --profile {profile} --policy PARTIAL --create-new`.
   Record the returned GUID.

5. Continue to Step 6 (mapping) — treat the SQL View as the source table. Column
   references in the Model TML use `[SQL_VIEW_NAME::column]` syntax. The Model's
   `model_tables` entry references the SQL View name and GUID.

See [../../shared/worked-examples/databricks/ts-from-databricks-sql-view.md](../../shared/worked-examples/databricks/ts-from-databricks-sql-view.md)
for a complete worked example.

---

**MV-on-MV detection (when `source.kind` is `table_fqn`):** an FQN-shaped `source:`
cannot be assumed to be a physical table — it may be another metric view. Query:

```sql
SELECT table_type FROM system.information_schema.tables
WHERE table_catalog = '{src_catalog}' AND table_schema = '{src_schema}'
  AND table_name = '{src_table}'
```

If `table_type = 'METRIC_VIEW'`, **fail loud** — do not build a Table TML against it.
Report to the user:

```
The Metric View's source ('{source_fqn}') is itself a Metric View, not a physical
table. Chained (MV-on-MV) sources are not supported by this skill yet. Convert
'{source_fqn}' on its own first, or flatten the source chain in Databricks before
retrying.
```

Log the MV to the Unmapped Report and stop processing it. This same check applies
to `joins[].source` values.

---

Version routing and classification are handled by `parse-mv` — both versions
normalize into one `parsed.json` shape.

See [../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md)
(v1.1 Multi-Source Parsing section) for background reading on the join-walk
semantics `parse-mv` implements.

---

### Step 6: Translate expressions — `ts databricks translate-formulas`

**1. Author `tables.json`** — the alias-path → ThoughtSpot-table-name map:

- Key `"source"` (required) plus one key per join alias; nested joins use
  dot-joined paths from the root (`"orders.customers"`).
- Value: the ThoughtSpot Table object name. Derive the initial name from the
  FQN's table part upper-cased (`analytics.ecommerce.transactions` →
  `TRANSACTIONS`); Step 8 confirms it against the real objects and enriches
  these values with GUIDs.

```json
{"source": "TRANSACTIONS", "orders": "DM_ORDER", "orders.customers": "DM_CUSTOMER"}
```

**2. Translate:**

```bash
source ~/.zshenv && ts databricks translate-formulas \
  --input parsed.json --tables tables.json --output translated.json
```

The command encodes the full mapping surface — the function map from
[../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md),
the window decision tree from
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md),
conditional aggregates, LOD `group_aggregate` (3-arg with `query_filters()`),
`COUNT(DISTINCT)` → `unique count`, and cross-measure inlining. Every
dimension/measure lands in `translated[]` or `skipped[]` with a reason —
review both.

**3. Review the output with the user:**

- **`skipped[]`** — each entry needs a decision: accept the omission, or build
  the formula manually per the reason text (e.g. `range: all` needs a
  partition-dimension judgment call — the reason names the manual recipe).
- **`annotations[]`** — surface every `sparse_data_risk` (BL-098: Databricks
  date-interval windows vs ThoughtSpot row-positional `moving_sum`; numbers
  match only on data dense at the window grain), `pending_verification` (C8
  grain/offset extrapolations), `one_row_per_period`, and
  `lod_filter_asymmetry` note. These feed the Step 10 `⚠ WINDOW` markers.
- The `filter` entry (when present) becomes the model-level filter in Step 9.

**Semantic caveats (live-verified):**

**Density caveat (E1, live-verified 2026-07-09 on gapped data — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`).** Databricks'
`trailing`/`leading N day` windows are genuine date-interval windows;
ThoughtSpot's `moving_sum`/`moving_average` are row-positional — the two are
indistinguishable on dense daily data, but diverge on data with date gaps.
Treat any `translated[]` entry carrying a `sparse_data_risk` annotation as an
approximation that matches Databricks only when the order column is dense at
the window's unit grain (one row per unit, no gaps); run a density check on
any source with possible gaps before accepting the translation.

**Filter-asymmetry caveat (A1/A2/A3, live-verified 2026-07-09 — same matrix).**
The `range: all` / LOD `group_aggregate(..., query_filters())` mapping is
filter-aware for a Databricks MV's own global `filter:`, but filter-blind to
an ad hoc query-time `WHERE` on an MV with no global filter — **unless** the
third argument is `{}` instead of `query_filters()`, paired with a
model-level `filters:` block mirroring the MV's `filter:` (live-tested
2026-07-09, A3 follow-up): that combination is filter-blind to a
search-level pin and filter-aware of the model filter, reproducing both
Databricks conditions in one formula. Every entry carrying a
`lod_filter_asymmetry` annotation needs this judgment call made explicitly
with the user.

**Deferred grains note (C8).** The `range: current` + `offset: -N <unit>`
row-relative `LAG(N)` mapping is live-verified at month grain (`N=1`) only;
quarter/year grain offsets remain Deferred (C8 — see
`docs/audit/2026-07-08-dbx-window-claim-matrix.md`). Entries carrying a
`pending_verification` annotation at those grains need this caveat surfaced
to the user before the translation is treated as final.

---

### Step 7: Table registration question

After mapping, display the source table(s) and ask:

**v0.1 (single source):**

```
The Metric View references 1 source table:
  {catalog}.{schema}.{table_name}

Is this table already registered in ThoughtSpot?
  Y  Yes — use existing ThoughtSpot Table object
  N  No  — create a new Table object from scratch
  ?  Not sure — search ThoughtSpot first

Enter Y / N / ?:
```

**v1.1 (multi-source with joins):**

List all source tables (fact table from `source:` + all dimension tables from `joins:`)
and ask the same question for each.

- **Y** → skip search, go to Step 8A (column verification only)
- **N** → skip search, go to Step 8B (create)
- **?** → go to Step 8A (search + verify)

---

### Step 8A: Discover and verify existing ThoughtSpot Table objects (Y and ? paths)

Skip this step if the user answered **N** in Step 7 — go directly to Step 8B.

**Choose the search scope first.** A whole-instance scan is the slow path — on a
large instance `--all` pulls every table. Offer the narrower option and search by
**table-name pattern** (`--name`), never `--all`-then-filter:

```
How should I search for these tables?
  C  Within a specific connection — fastest; search that one connection's tables
  I  Entire ThoughtSpot instance  — broader, slower

Enter C / I :
```

**Search by name (both scopes start here):**

```bash
source ~/.zshenv && ts metadata search --subtype ONE_TO_ONE_LOGICAL --name "%{table_name}%" --profile {profile}
```

- **C (within a connection)** → **first identify the connection using the
  N (name it) / F (filter by substring) / L (list all) prompt in Step 8B — present that
  prompt and let the user choose; do NOT run `ts connections list` and dump every
  connection by default.** Then keep only results whose `metadata_header.dataSourceName`
  equals the chosen connection name (each result carries its connection there, e.g.
  `"APJ_DBX"`). Fastest, and unambiguous when the same table name exists on several
  connections.
- **I (entire instance)** → run the name search above with no connection filter.

Filter the JSON to match the MV source table by table name (`metadata_name`) and, for
the connection scope, `metadata_header.dataSourceName`; use
`metadata_header.database_stripes` / `metadata_header.schema_stripes` to disambiguate
same-named tables. Build a map: `physical_table_name -> {metadata_id, metadata_name}`.

> Only fall back to `--all` (fetch every table) when no usable name pattern can be
> formed (e.g. the name is too generic). Tell the user that cost before running it.

**Export TMLs for found tables to verify columns:**

```bash
source ~/.zshenv && ts tml export {guid1} {guid2} ... --profile {profile} --parse
```

`--parse` returns structured JSON — access columns via `item["tml"]["table"]["columns"]`
directly. Parse `table.columns[].name` from each returned item. Build a column map:
`table_name -> [col_name, ...]`. Compare against the columns referenced in the MV
dimensions and measures to identify any column gaps.

> The `column_id` in the model TML must use the column names from the ThoughtSpot
> Table TML — export the TMLs to confirm them.

**Confirm the plan before making any changes:**

```
Table Plan:
  ✓  {TABLE_NAME}  — found (GUID: {guid}) — all {n} columns present → use as-is
  ⚠  {TABLE_NAME}  — found (GUID: {guid}) — missing {n} columns: {COL_A}, {COL_B} → update
  ✗  {TABLE_NAME}  — not found in ThoughtSpot → create new

Actions to be taken:
  • Update {TABLE_NAME}: add {n} missing columns
  • Create {TABLE_NAME}: {n} columns from Databricks schema

No changes have been made yet. Proceed? (yes/no):
```

Do not proceed until the user confirms. If any table is **not found**, follow Step 8B
for those tables. If any table has **missing columns**, follow Step 8C before building
the model.

**Enrich `tables.json`:** upgrade each value from a name string to an object
carrying the ThoughtSpot GUID, e.g.
`{"source": {"name": "TRANSACTIONS", "fqn": "<guid>"}}`. Step 9's
`build-model` stamps these GUIDs as `model_tables[].fqn`. For **file-only**
runs (Step 10-FILE) where new tables were needed but NOT created, instead set
`"create": true` with `db`/`schema`/`db_table` and a `columns` list of
`{"name", "dbx_type"}` from the `DESCRIBE TABLE` output — `build-model` then
writes a `{name}.table.tml` alongside the model.

---

### Step 8B: Create ThoughtSpot Table objects (Scenario B) — also the connection picker for the Step 8A connection-scoped search

**Get all column names and types for the source table:**

```sql
DESCRIBE TABLE {catalog}.{schema}.{table_name}
```

Execute via the SQL execution pattern. The response `data_array` contains rows
`[col_name, data_type, comment]`. Map Databricks types to ThoughtSpot types using
the data type mapping in
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md).

**Choose how to identify the connection — don't dump the full list by default.** A long
connection list is noise when the user already knows the one they want. Ask first:

```
How would you like to choose the ThoughtSpot connection?
  N  Name it     — type the exact connection name; I'll use it directly
  F  Filter      — give a partial string; I'll list only connections that match
  L  List all    — show every connection and pick by number

Enter N / F / L:
```

Then fetch the connections once (auto-paginated, returns all of the specified type):

```bash
source ~/.zshenv && ts connections list --type DATABRICKS --profile {profile}
```

Resolve the user's choice against that result:

- **N (name it)** — match the typed name against the returned `name` values
  (case-sensitive). Exactly one match → use it. No match → show the closest names and
  re-ask. Don't fabricate a name the list doesn't contain — the table TML needs the exact,
  case-sensitive connection name.
- **F (filter)** — keep connections whose `name` contains the string (case-insensitive),
  show them as a short numbered list (name, type, database), and pick from that. One match
  → auto-select and confirm; none → widen the string or switch to **L**.
- **L (list all)** — show the full numbered list and pick by number.

If only one connection exists in total, auto-select it and confirm regardless of the choice.
Use the exact `name` value from the API response in the table TML.

> **No suitable connection?** A ThoughtSpot connection only sees catalogs its Databricks
> credentials are granted. If no existing connection can see the source catalog, table
> creation fails with *"Database … does not exist in connection"*. **Creating a Databricks
> connection is out of this skill's scope** — Databricks connections authenticate with a
> Personal Access Token or OAuth (M2M), not key-pair, so there is no `ts connections create`
> path for them (that is `BL-036`). Stop and direct the user to create the connection in the
> ThoughtSpot UI (credentials per `/ts-profile-databricks`), then resume on this step and
> select it. Do **not** trial-and-error existing connections.

Create the ThoughtSpot Table object:

```bash
cat tables-spec.json | source ~/.zshenv && ts tables create --profile {profile}
```

Where `tables-spec.json` is a JSON array built from the column data. See
`ts tables create --help` for the spec format. This command handles JDBC retry and
GUID resolution automatically, and outputs `{name: guid}`.

> **Both `db` and `schema` must be non-empty** in every table spec entry. ThoughtSpot
> requires the fully qualified three-part path (`catalog.schema.table`) even if the
> connection has a default catalog configured. Passing an empty `db` or `schema` causes
> "Fully qualified table mapping missing".

Record the created GUID for use in the model TML.

**Enrich `tables.json`:** upgrade each value from a name string to an object
carrying the ThoughtSpot GUID, e.g.
`{"source": {"name": "TRANSACTIONS", "fqn": "<guid>"}}`. Step 9's
`build-model` stamps these GUIDs as `model_tables[].fqn`. For **file-only**
runs (Step 10-FILE) where new tables were needed but NOT created, instead set
`"create": true` with `db`/`schema`/`db_table` and a `columns` list of
`{"name", "dbx_type"}` from the `DESCRIBE TABLE` output — `build-model` then
writes a `{name}.table.tml` alongside the model.

---

### Step 8C: Update existing tables with missing columns

For each table from Step 8A with a column gap, introspect the Databricks schema
for the missing columns:

```sql
DESCRIBE TABLE {catalog}.{schema}.{table_name}
```

Filter the result to the missing column names. Map Databricks types to ThoughtSpot
types using [../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md).

Find the ThoughtSpot connection for the table:
```bash
source ~/.zshenv && ts connections list --type DATABRICKS --profile {profile}
```

Add the missing columns to the connection, then re-import the updated Table TML
(batch all imports in one call):
```bash
source ~/.zshenv && ts tml import --policy ALL_OR_NONE --profile {profile}
```

After import, re-export the updated TMLs to refresh the column map before Step 9.

---

### Step 9: Build the Model TML — `ts databricks build-model`

**Model name:** `{view_name_title_case}` — derived from the Metric View name.
Ask the user if they want a different name. Do not add a `TEST_MV_` or other
prefix — see [../../shared/schemas/ts-model-conversion-invariants.md](../../shared/schemas/ts-model-conversion-invariants.md) (N1).

```bash
source ~/.zshenv && ts databricks build-model \
  --parsed parsed.json --translated translated.json --tables tables.json \
  --connection "{connection_name}" --model-name "{model_name}" \
  --mv-fqn "{catalog}.{schema}.{view_name}" --output-dir ./tml_out
```

The command assembles the Model TML (columns, formulas, joins, the model-level
`filters:` block when the MV has a `filter:`, `properties:`), assembles Table
TML for any `create: true` entries, validates the hard TML invariants
(`db_column_name` on every table column, `name:`-only connection blocks,
`guid:` at document root, formula/column `formula_id` pairing, no
`aggregation:` in `formulas[]`) and runs the `ts tml lint` checks (I1/I2/I4/
I5/I8) — exit 1 names the specific field on any finding. It prints a summary
JSON on stdout; keep it for Step 10.

**Filter handling** is automatic: the MV `filter:` becomes an `MV Filter`
ATTRIBUTE formula plus a model-level `filters:` block (`oper: in`,
`values: ['true']`) — the live-verified emulation of the MV's global filter
(A1, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`). If the filter was
skipped at translate time it appears in `skipped[]` — resolve it with the user
before importing (an unfiltered model silently changes every number).

**Live-verified 2026-07-09** (see `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`,
A1) — this model-level `filters:` approach is the **CONFIRMED** correct emulation of
the MV's own global `filter:`: on ThoughtSpot, a model-level `filters:` block makes
LOD/window formulas (e.g. `group_aggregate(..., query_filters())`) filter-aware
identically to a query-level pin, matching the DBX MV's global-`filter:` condition
exactly. It does not, and cannot, reproduce a DBX consumer's ad hoc query-time
`WHERE` on an MV with no global filter — that DBX condition is filter-blind for
LOD/window dimensions, a source-side asymmetry, not a ThoughtSpot gap.

`build-model` emits these correctly; they matter when you hand-edit TML:
- **`id` must equal `name` exactly** (same case, same characters). ThoughtSpot resolves
  `with` and `on` join references against the table's actual `name` — if `id` differs
  in case, joins fail with "{table_name} does not exist in schema". Use the exact
  ThoughtSpot table object name for both `id` and `name`.
- `id` values must be **unique** across all `model_tables` entries
- `name` values must also be **unique** — ThoughtSpot rejects models where two tables
  share the same `name` value ("Multiple tables have same alias")

---

### Step 9.5: Spotter enablement

Ask whether Spotter (AI search) should be enabled. Default is **yes**.

```
Enable Spotter (AI search) for this model? [Y / n] (default: Y)
```

Re-run the Step 9 `build-model` command appending `--spotter-enabled` (or
`--no-spotter-enabled`) — assembly is deterministic and cheap; the flag adds
`properties.spotter_config.is_spotter_enabled` to the model TML. When
**updating** an existing model (`--existing-guid`) and the user does not
explicitly answer: export the existing model first (`ts tml export {guid}
--profile {profile} --parse`), read its current
`properties.spotter_config.is_spotter_enabled`, and pass the matching flag —
never overwrite a live setting with a default.

---

### Step 10: Review checkpoint

Before importing, show the user a summary built from the Step 9 `build-model` summary
JSON (and `translated.json`/`parsed.json` for the formula log): tables from `tables[]`
(`alias`/`name`/`fqn`), column lists from `columns.attributes`/`columns.measures`,
formula translations from `translated.json`'s `translated[]`/`skipped[]` entries,
window markers from `window_measures[]` (`name`, `ts_expr`, each annotation's `detail`
as the assumption line), and Spotter from `spotter_enabled`:

```
Model to import: {view_name}
Source: {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
Filter: {parsed.json "filter" expr if summary filter_applied else "none"}

Tables:
  ✓ {tables[].name} (fqn: {tables[].fqn}) — alias: {tables[].alias}

Columns ({n} total):
  ATTRIBUTE: {columns.attributes}
  MEASURE:   {columns.measures}
  Formulas:  {formula_count} formula(s)

Formula translations:
  ✓ {name}: {mv expr from parsed.json} → {ts_expr}     # translated[]
  ⚠ {name}: OMITTED — {reason}                          # skipped[]

Window measures (review required):
  ⚠ WINDOW {name}: {ts_expr}
    Assumption: {annotation.detail}

If any window measures exist, display this warning:

  ⚠ Window measures assume daily grain (one row per day for trailing/rolling).
    Verify that the source data matches this assumption — if the table has
    multiple rows per day, moving_sum/moving_average will over-count.

Spotter (AI search): enabled / disabled

Proceed with import?
  yes  — import to ThoughtSpot
  no   — cancel
  file — write TML files without importing (for environments where you lack
          DATAMANAGEMENT access, or to review the TML before committing)
```

Wait for user confirmation before proceeding.

If the user selects **file**, skip to [Step 10-FILE](#step-10-file-output-tml-files-file-only-mode).

---

### Step 10-FILE: Output TML files (file-only mode)

This path is used when the user selected **file** at the Step 10 checkpoint, explicitly
said "file only", or has no ThoughtSpot `DATAMANAGEMENT` access.

**1. Files are already on disk** — Step 9's `build-model --output-dir` wrote
`{model_name}.model.tml` (and `{table_name}.table.tml` for every
`create: true` table). Nothing to generate here.

**2. Report:**

```
TML files written:
  {model_name}.model.tml    — ThoughtSpot Model TML
  {table_name}.table.tml   — ThoughtSpot Table TML (if new tables were needed)

To import to ThoughtSpot when you have access:

  1. Package all .tml files into a zip:
       zip {model_name}_tml.zip *.tml

  2. In ThoughtSpot: Data → TML Import → upload the zip
     (table TMLs will import first, then the model)

  3. Or import via CLI:
       ts tml import --file {model_name}.model.tml --policy ALL_OR_NONE --profile {profile}

  Note: On first import, omit `guid` from the TML (already omitted here). ThoughtSpot
  will assign a GUID — save it from the import response if you need to update the model later.
```

**3. Proceed to Step 12** (Produce summary report) — include the formula translation log
and column summary so the user has the full picture before importing.

---

#### Pre-import validation gate

Before any `ts tml import`, run the mandatory lint gate — see
[`../../shared/schemas/ts-tml-import-gate.md`](../../shared/schemas/ts-tml-import-gate.md)
for the invariant list (I1/I2/I4/I5/I8), the stdin command, and the
update-vs-create `guid` and import-policy rules. Do not import until
`ts tml lint` reports `"clean": true`.

---

### Step 11: Import the model

**IMPORTANT — Updating vs creating:** without `--existing-guid`, ThoughtSpot
always creates a **new** object, even when a model with the same name exists.
To update in place, pass the existing model's GUID — `build-model` stamps it
as a top-level `guid:` alongside `model:` (a `guid:` nested inside `model:` is
silently ignored). On first import omit it; record the returned GUID.

```bash
# First import (new model):
source ~/.zshenv && ts databricks build-model \
  --parsed parsed.json --translated translated.json --tables tables.json \
  --connection "{connection_name}" --model-name "{model_name}" \
  --mv-fqn "{catalog}.{schema}.{view_name}" --output-dir ./tml_out \
  {--spotter-enabled|--no-spotter-enabled} --profile {profile}

# Update an existing model in place:
#   ... same command plus: --existing-guid {existing_model_guid}
```

With `--profile`, the command imports the model TML via
`ts tml import --policy PARTIAL` after a clean lint, and reports
`import_status` and `model_guid` in the summary JSON. **Save the GUID** —
required for any future update import. On `import_status: "failed"` read
`import_error` and consult the table below.

**Common import errors:**

| Error | Likely cause | Fix |
|---|---|---|
| `column_id not found` | Column name is wrong — MV dimension name used instead of ThoughtSpot Table TML column name | Export Table TML and verify column names |
| `Compulsory Field ... joins(N)->with is not populated` | Missing `with` field on an inline join | Add `with: {target_id}` to every inline join entry |
| `{table_name} does not exist in schema` (on `with` field) | `with` value doesn't match any `id` in model_tables | Ensure `with` matches the target's `id` exactly — same case as `name` |
| `Invalid srcTable or destTable in join expression` | `on` clause references a table name that doesn't match any `id` | Check that both `[table::col]` refs in `on` use `id` values |
| `Multiple tables have same alias {name}` | Two model_tables entries have the same `name` value | Deduplicate — keep only one entry |
| `fqn resolution failed` | GUID is stale or from a different ThoughtSpot instance | Re-run Step 8A to get fresh GUIDs |
| `formula syntax error` | ThoughtSpot formula has invalid syntax | Fix the formula expression |
| YAML mapping error on formula with `{` | Formula with `{ [col] }` emitted as inline YAML string | The CLI's YAML emitter quotes `{` correctly; this arises only in hand-edited TML |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars from all string values before serialising |

---

### Step 11b: Verify Import

After a successful import response, confirm the model was indexed and has the expected
shape — not just that the API returned 200.

**1. Search for the model by GUID:**

```bash
source ~/.zshenv && ts metadata search --subtype WORKSHEET --name "%{view_name}%" --profile {profile}
```

The GUID returned by the import response must appear in the results. If it is absent,
the import succeeded at the API level but indexing is delayed — wait 5 seconds and
retry once.

**2. Export the imported model and count columns:**

```bash
source ~/.zshenv && ts tml export {created_guid} --fqn --profile {profile}
```

Parse the returned TML and count `model.columns[]` entries. This count must be >= the
number of translatable fields from the MV (total dimensions + measures, minus any
entries in translated.json's `skipped[]`).

If the column count is lower than expected: compare the exported TML against the TML
sent in Step 11 to identify which columns ThoughtSpot silently dropped, and investigate.

**3. Report the model URL:**

```
Model imported successfully.

  Name:    {view_name}
  GUID:    {created_guid}
  URL:     {base_url}/#/model/{created_guid}

Open the URL in a browser to verify the model appears in the ThoughtSpot Data panel.
```

---

### Step 12: Produce summary report

After a successful import (or file output), generate:

```
## Model Import Complete

**Model:** {view_name}
**GUID:** {created_guid}
**ThoughtSpot URL:** {base_url}/#/model/{created_guid}
**Source:** {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
**Filter:** {filter_expr or "none"}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE ({agg}) | {TABLE}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |
| ... | ... | ... |

### Formula Translation Log
| Column | Original Databricks SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{expr}` | ✓ Translated | `{ts_formula}` |
| {name} | `{expr}` | ⚠ Omitted | {reason} |

### Not Mapped
- Global filter: "{filter_expr}" — noted in model description, not enforced as a ThoughtSpot filter
- MV `version` field — metadata only, not stored in ThoughtSpot
```

**Test questions:** Suggest 3-5 natural language questions the user can try in Spotter
to verify the model works. Base them on the dimensions and measures present:

```
### Suggested test questions for Spotter
1. "What is the total {measure_1} by {dimension_1}?"
2. "Show me {measure_2} for each {dimension_2}"
3. "What are the top 10 {dimension_1} by {measure_1}?"
```

---

### Step 13: Cleanup

Remove any temporary files written during the workflow:

```bash
rm -f /tmp/ts_model_build_*.yaml /tmp/ts_model_build_*.json
```

The `ts` CLI manages its own token cache — do not remove `/tmp/ts_token_*.txt`
unless the user explicitly requests a logout.

---

## Multiple Metric View conversion

After completing Step 12 for one view, ask:
"Convert another Metric View?" If yes: return to Step 2. Reuse the already-confirmed
ThoughtSpot and Databricks profiles. Do not re-authenticate between views.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.8.1 | 2026-07-10 | Pre-import lint gate extracted to shared `ts-tml-import-gate.md` (BL-063 PR5) — content unchanged, now linked. |
| 1.8.0 | 2026-07-10 | Steps 5/6/9/9.5/10/11 rewired onto ts databricks parse-mv / translate-formulas / build-model; tables.json v2 |
| 1.7.0 | 2026-07-09 | Dimension/metric semantic deep-dive (BL-063 PR1.5, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`). **New capability (A3, the MINOR):** `group_aggregate`'s `{}` filter argument, paired with a model-level `filters:` block mirroring the source MV's `filter:`, reproduces BOTH halves of the A1/A2 DBX composite (MV-`filter:`-aware AND query-time-`WHERE`-blind) in a single ThoughtSpot construct — corrects A1/A2's "no TS analogue" conclusion. `query_filters()` remains the default LOD mapping; `{}` + a mirrored model filter is the new option for reproducing a DBX consumer's ad hoc query-time-`WHERE`-blind LOD. Subtraction form `query_filters() - {col}` tested and found not to exclude a filter pinned on a derived boolean formula — recorded, not adopted. **Corrections/caveats:** LOD `query_filters()` dimension confirmed filter-aware on TS under both filter kinds, with the caveat that the equivalence holds for a Databricks MV's own global `filter:` only, not for a consumer's ad hoc query-time `WHERE` (A1/A2, refined by A3 above); cross-measure ratio inlining confirmed grain-safe at every grain, no caveat needed (B1); global `filter:` × window ordering confirmed filter-before-window on both platforms, with a new frame-semantics caveat — Databricks `trailing`/`leading` windows are date-interval framed while `moving_sum` is row-positional, so results diverge on sparse/gapped data (C1, same root cause as E1); semi-additive `last`/`first_value` under a date-range filter confirmed cross-platform (D1). |
| 1.6.0 | 2026-07-09 | Window semantics live-verified against a Databricks fixture + ThoughtSpot number-match (`docs/audit/2026-07-08-dbx-window-claim-matrix.md`, C1–C7/C6a); resolves the previously-PENDING `leading`/`all` cases — new capability, not just a correction. **CORRECTED:** `range: trailing N day` (default/exclusive) — was `moving_sum([m], N, 0, [date])` (actually reproduces `trailing (N+1) day inclusive`), now `moving_sum([m], N, -1, [date])` (C1); `range: current` + `offset: -N <unit>` — was wall-clock `sum_if(diff_months/quarters/years([date], today())=N, [m])`, now row-relative `moving_sum([m], N, -N, [date])` LAG idiom, valid only with one row per period (C6/C6a; quarter/year grains and N>1 Deferred per C8). **RESOLVED (was PENDING):** `range: leading N day` (default/exclusive) → `moving_sum([m], -1, N, [date])` (C3); `range: all` → `group_aggregate(sum([m]), {partition dims}, query_filters())` (C4); `inclusive`/`exclusive` anchor modifier default confirmed `exclusive` (C2). **CONFIRMED unchanged:** `range: cumulative` → `cumulative_sum([m], [date])` (C5); `semiadditive: last`/`first` → `last_value`/`first_value(...)` (C7). Adds `trailing`/`leading` `inclusive` variants (`moving_sum([m], N-1, 0, [date])` / `moving_sum([m], 0, N-1, [date])`). |
| 1.5.4 | 2026-07-03 | Product-currency fixes (audit 2026-07-03, findings 13.5/13.6/13.7): widen `source:` detection to catch the bare (unparenthesized) SQL form, not just `(SELECT ...)`; add MV-on-MV fail-loud detection for `source:`/`joins[].source`; fix the join-walk snippet to handle `using: [COL, ...]` (previously assumed every join had `"on"`, which would `KeyError`) and the spec's `many_to_one` default when neither `rely:` nor `cardinality:` is present; recognise (but flag PENDING LIVE VERIFICATION) the `range: leading`/`range: all` window values and the `inclusive`/`exclusive` anchor modifier. |
| 1.5.3 | 2026-06-17 | Connection step: add explicit **"no suitable connection → stop & instruct"** guidance — a connection only sees catalogs its credentials are granted; if none fits, table creation fails with *"Database does not exist in connection"*. Creating a Databricks connection is out of scope (PAT/OAuth, not key-pair — no `ts connections create` path; tracked as BL-036): direct the user to the ThoughtSpot UI, then resume and select it. Don't trial-and-error connections. (Sibling to the Snowflake/Tableau create-connection change.) |
| 1.5.2 | 2026-06-17 | Replace the hand-written pre-import grep gate with `ts tml lint` (parser-based; now also catches **I8** duplicate `column_id`). From the full audit sweep (codification, angle 11). |
| 1.5.1 | 2026-06-16 | **Extend the N/F/L connection prompt into the Step 8A connection-scoped search path.** The 8A "C — within a connection" path now explicitly presents the Step 8B N (name it) / F (filter by substring) / L (list all) prompt to identify the connection — it must NOT run `ts connections list` and dump every connection by default. Mirrors the same fix in ts-convert-from-tableau and ts-convert-from-snowflake-sv. |
| 1.5.0 | 2026-06-16 | Connection selection (Step 8B): add a **how-to-identify-the-connection prompt** (N name it / F filter by partial string / L list all) before dumping the full connection list. Fetch once via `ts connections list --type DATABRICKS`, then use the typed name directly, show a filtered subset, or show the full numbered list. Single connection still auto-selects. Mirrors the same prompt added to ts-convert-from-tableau and ts-convert-from-snowflake-sv. |
| 1.4.0 | 2026-06-16 | Step 8A table discovery: add a **connection-scoped vs instance-wide search choice** and search by `--name "%table%"` pattern instead of `--all`-then-filter. Connection scope filters results on `metadata_header.dataSourceName` (verified field). Avoids slow whole-instance scans on large instances. Mirrors the ts-convert-from-tableau Step 4c change. |
| 1.3.0 | 2026-06-12 | Adopt PT1 pass-through policy (scalar reliable; flag aggregate pass-through for review). |
| 1.2.0 | 2026-06-12 | Add pre-import validation gate (I1/I2/I4/I5) before model TML import (BL-001). |
| 1.1.0 | 2026-06-11 | Preserve existing Spotter setting on in-place model updates (don't reset to default). Drop `TEST_MV_` prefix — model name uses the bare MV name (N1); cite canonical conversion invariants doc. |
| 1.0.0 | 2026-05-22 | Initial release — single conversion mode (Mode A) |
