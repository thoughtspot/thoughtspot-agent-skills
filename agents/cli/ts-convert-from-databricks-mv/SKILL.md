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
| `dimensions[].expr` (window function — LOD) | LOD `formulas[]` entry: `group_aggregate(agg([col]), {[dim]}, query_filters())` — 3 args required |
| `dimensions[].display_name` (v1.1) | Column `name` (display name) |
| `dimensions[].comment` (v1.1) | Column `description` |
| `dimensions[].synonyms` (v1.1) | `properties.synonyms[]` + `properties.synonym_type: USER_DEFINED` |
| `measures[].expr` (simple `AGG(col)` — SUM, AVG, MIN, MAX, COUNT) | `columns[]` with `column_type: MEASURE` + extracted `aggregation` |
| `measures[].expr` (`COUNT(DISTINCT col)`) | `formulas[]` entry: `unique count ( [TABLE::col] )` — NOT `aggregation: COUNT_DISTINCT` on a `column_id` (TS silently overrides to ATTRIBUTE) |
| `measures[].expr` (complex — ratios, nested aggregates) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` reference |
| `measures[].expr` with `MEASURE()`/`ANY_VALUE()` | Cross-measure formula — **inline** the referenced expressions (cross-refs fail during TML import) |
| `measures[].window`, `order:` raw date (semi-additive) | `last_value ( sum ( [m] ) , query_groups ( ) , { [date] } )` — snapshot metrics (inventory, balance) |
| `measures[].window`, `order:` truncated month (period filter) | `sum_if ( diff_months ( [date] , today ( ) ) = 0 , [m] )` — flow metrics (revenue, qty) |
| `measures[].window` + `offset: -1 month` | `sum_if ( diff_months ( [date] , today ( ) ) = -1 , [m] )` |
| `measures[].window` + `offset: -1 year` (month grain) | `sum_if ( diff_months ( [date] , today ( ) ) = -12 , [m] )` |
| `measures[].window`, `order:` truncated quarter | `sum_if ( diff_quarters ( [date] , today ( ) ) = 0 , [m] )` |
| `measures[].window` + `offset: -3 month` (quarter) | `sum_if ( diff_quarters ( [date] , today ( ) ) = -1 , [m] )` |
| `measures[].window`, `order:` truncated year | `sum_if ( diff_years ( [date] , today ( ) ) = 0 , [m] )` |
| `measures[].window` + `offset: -1 year` (year grain) | `sum_if ( diff_years ( [date] , today ( ) ) = -1 , [m] )` |
| `measures[].window` with `range: trailing N day` | `moving_sum([m], N, 0, [date])` — rolling look-back window |
| `measures[].window` with `range: cumulative` | `cumulative_sum([m], [date])` |
| `measures[].window` with `range: leading N day` | **PENDING LIVE VERIFICATION** — rolling look-ahead window; candidate `moving_sum([m], 0, N, [date])`. Flag for manual review — see BL-032. |
| `measures[].window` with `range: all` | **PENDING LIVE VERIFICATION** — unbounded partition window; no verified equivalent. Flag for manual review — see BL-032. |
| `measures[].window` with `inclusive`/`exclusive` anchor modifier | **PENDING RE-VERIFICATION** — default is `exclusive`; the `trailing`↔`moving_sum` equivalence above predates this confirmation — see BL-032. |
| `measures[].expr` with `FILTER (WHERE cond)` | `agg_if ( cond , [x] )` — native `*_if` conditional aggregate (e.g., `sum_if`, `unique_count_if`) |
| `COUNT(*)` | Formula: `count ( 1 )` |
| `fields[]` (GA alias for `dimensions[]`) | Same mapping as `dimensions[]` above — `fields:` is checked first, `dimensions:` is the fallback |
| Growth % (MoM, QoQ, YoY) | Inline `sum_if` expressions for both periods — cross-formula refs not supported during TML import |
| `joins:` (nested hierarchy) | One Table TML per source; model `joins[]` from parent→child hierarchy |
| `joins[]."on"` or `joins[].using` (exactly one present) | `on` → join expression as-is; `using: [COL, ...]` → `[A::COL] = [B::COL]` (AND-joined for multiple columns) |
| `filter:` (any) | Boolean formula column `[MV Filter]` — users apply `[MV Filter] = true`. Always create, never description-only. |
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
  9.   Build Table TML (if needed) and Model TML ............ auto
  9.5. Confirm Spotter enablement (default: enabled) ........ you choose
 10.   Review checkpoint — inspect TML before import ......... you confirm
 11.   Import Table TML(s) + Model TML via ts tml import ..... auto
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

### Step 5: Parse the YAML

Parse the YAML string extracted in Step 4. The Metric View YAML follows the schema
documented in [../../shared/schemas/databricks-metric-view.md](../../shared/schemas/databricks-metric-view.md).

```python
import yaml

mv_yaml = yaml.safe_load(yaml_string)

version = mv_yaml.get("version", "0.1")
source_fqn = mv_yaml.get("source", "")          # fact table FQN
joins = mv_yaml.get("joins", [])                  # v1.1: nested dimension joins
dimensions = mv_yaml.get("fields", mv_yaml.get("dimensions", []))  # GA uses fields:; dimensions: is backward compat
measures = mv_yaml.get("measures", [])
mv_filter = mv_yaml.get("filter", "")
```

**Subquery source detection (before version routing):**

`source:` accepts four forms — table FQN, parenthesized SQL, bare SQL, or another
metric view (see [Source Forms](../../shared/schemas/databricks-metric-view.md)).
Check for a SQL query in **either** the parenthesized or bare form — do not assume
parentheses are present:

```python
_stripped = source_fqn.strip()
is_subquery = _stripped.lower().startswith(("(select", "(with")) or \
              _stripped.lower().startswith(("select ", "with "))
```

If `is_subquery` is true, the MV source cannot be mapped directly to a ThoughtSpot
Table object. Present these options to the user:

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

1. Construct the SQL query by combining `source` and `filter`:
   ```python
   sql_query = source_fqn  # the SELECT statement
   if mv_filter:
       sql_query = f"SELECT * FROM ({source_fqn}) _mv WHERE {mv_filter}"
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

**MV-on-MV detection (when `is_subquery` is false):** an FQN-shaped `source:`
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

**Version routing:**
- `version: 0.1` → single-source parsing path (basic column metadata only)
- `version: 1.1` → rich metadata + optional multi-source with joins (verified 2026-05-26)

**v0.1 — single source:**

1. Decompose `source` FQN into `catalog`, `schema`, `table_name`:
   ```python
   parts = source_fqn.split(".")
   src_catalog, src_schema, src_table = parts[0], parts[1], parts[2]
   ```

2. For each dimension, classify:
   - **Direct column reference** (single identifier, no functions): `expr` is a physical
     column name → maps to `ATTRIBUTE` column with `column_id` pointing to the physical column.
   - **Computed expression** (contains functions, operators, CASE): → maps to a `formulas[]`
     entry with a translated ThoughtSpot formula + a `columns[]` entry with `formula_id`.

3. For each measure, classify:
   - **Simple aggregate** (`AGG(column_name)` or `AGG(DISTINCT column_name)`): extract the
     aggregate function → `aggregation` field, extract inner column → `column_id`.
   - **Complex expression** (ratios, nested aggregates, arithmetic inside aggregate): → maps
     to a `formulas[]` entry + `columns[]` with `formula_id`.

4. Record the global `filter` (if present) for inclusion in the model description.

Build an internal map:
- `source_table`: catalog, schema, table_name
- `dimensions_parsed`: list of `{name, expr, is_direct, physical_col_or_formula}`
- `measures_parsed`: list of `{name, expr, is_simple, agg_function, physical_col_or_formula}`
- `filter_expr`: the global filter string (or empty)

**v1.1 — multi-source with joins (when encountered):**

Parse the `joins:` hierarchy to identify all source tables and their relationships:

```python
joins = mv_yaml.get("joins", [])

def walk_joins(join_list, parent_alias="source"):
    tables = []
    for j in join_list:
        alias = j["name"]
        source_fqn = j["source"]
        # A join has exactly one of "on" or "using" — never assume "on" is present.
        if "on" in j:
            on_clause = j["on"]
        else:
            shared_cols = j["using"]                        # array of shared column names
            on_clause = " AND ".join(
                f"{parent_alias}.{col} = {alias}.{col}" for col in shared_cols
            )
        cardinality_field = j.get("cardinality", "")       # Runtime 18.1+: "many_to_one" or "one_to_many"
        rely = j.get("rely", {})
        if cardinality_field:
            many_to_one = cardinality_field == "many_to_one"
        elif rely:
            many_to_one = rely.get("at_most_one_match", False)
        else:
            many_to_one = True   # spec default when neither rely: nor cardinality: is present
        tables.append({
            "alias": alias,
            "source": source_fqn,
            "on": on_clause,
            "parent": parent_alias,
            "many_to_one": many_to_one,
        })
        # Recurse into nested sub-joins
        sub_joins = j.get("joins", [])
        tables.extend(walk_joins(sub_joins, parent_alias=alias))
    return tables

all_dim_tables = walk_joins(joins)
```

This produces one entry per dimension table. Each entry records the alias, source FQN,
join condition, parent alias, and cardinality hint. Map each entry to a ThoughtSpot
Table TML and build model joins from the parent→child relationships.

Column references in `expr` use dot-path notation through the join hierarchy:
- `source.COL` → fact table column
- `alias.COL` → first-level dimension column
- `alias.sub_alias.COL` → nested dimension column

Parse dot-paths to determine which Table TML each column belongs to. The last segment
is the column name; preceding segments trace the join path.

Follow [../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md)
(v1.1 Multi-Source Parsing section) for the full mapping reference.

---

### Step 6: Map to ThoughtSpot columns and translate expressions

Apply the classification from Step 5 to build ThoughtSpot column and formula entries.
Use the translation rules in
[../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md).

**Dimensions:**

For each dimension:

| Dimension type | ThoughtSpot mapping |
|---|---|
| Direct column (`expr: region`) | `columns[]` entry: `column_id: {table}::{region}`, `column_type: ATTRIBUTE` |
| Computed (`expr: date_trunc('day', col)`) | `formulas[]` entry with translated expression + `columns[]` with `formula_id` |

**Measures:**

For each measure:

| Measure type | ThoughtSpot mapping |
|---|---|
| Simple `SUM(col)` | `columns[]` entry: `column_id: {table}::{col}`, `column_type: MEASURE`, `aggregation: SUM` |
| Simple `AVG(col)` | `columns[]` entry: `column_id: {table}::{col}`, `column_type: MEASURE`, `aggregation: AVERAGE` |
| Simple `COUNT(DISTINCT col)` | `formulas[]` entry: `unique count ( [TABLE::col] )` + `columns[]` with `formula_id`, `column_type: MEASURE` |
| Complex expression | `formulas[]` entry with translated expression + `columns[]` with `formula_id` |
| Any measure with `window:` | See **Window measures** below — translated to `moving_sum`/`moving_average`/`cumulative_sum`/`sum_if`/`last_value` depending on window type. Always flagged for review. |

**Window measures — `window:` handling:**

When a measure has a `window:` section, the `expr` and `window` are translated **together**
into a single ThoughtSpot formula. The `expr` alone is not sufficient — the `window:`
changes the semantic meaning of the measure. Follow the decision tree in
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md)
(Window Function Translation section).

| MV window pattern | ThoughtSpot formula |
|---|---|
| `range: trailing N day`, `order: date_dim` | `moving_sum ( expr , N , 0 , [TABLE::date_col] )` or `moving_average` if `AVG` |
| `range: cumulative`, `order: date_dim` | `cumulative_sum ( expr , [TABLE::date_col] )` |
| `range: current`, `order:` raw date, `semiadditive: last` | `last_value ( sum ( [m] ) , query_groups ( ) , { [TABLE::date_col] } )` |
| `range: current`, `order:` truncated period | `sum_if ( diff_months/quarters/years ( [TABLE::date_col] , today ( ) ) = N , [m] )` |
| `range: leading N day` / `range: all` | **PENDING LIVE VERIFICATION** — recognised but not yet translated; flag for manual review rather than guessing (see BL-032) |

`range` also accepts an `inclusive|exclusive` anchor-row modifier (default `exclusive`,
**PENDING RE-VERIFICATION** against the `trailing`↔`moving_sum` equivalence above — see
BL-032).

For `moving_sum` / `moving_average`, the inner `expr` is translated **without** the outer
aggregate wrapper — `SUM(a * b)` with `range: trailing 7 day` becomes
`moving_sum ( [TABLE::a] * [TABLE::b] , 7 , 0 , [TABLE::date_col] )`, not
`moving_sum ( sum ( [TABLE::a] * [TABLE::b] ) , 7 , 0 , [TABLE::date_col] )`.

**The sort/date argument must be a physical column reference** (`[TABLE::transaction_date]`),
not a formula dimension name. Look up the `order:` dimension's `expr` to resolve the
underlying physical column. Formula references in `moving_sum`'s sort position fail with
"Search did not find" errors.

**All measures with `window:` definitions must be flagged in the Step 10 review checkpoint**
with a `⚠ WINDOW` marker so the user can verify the translation is correct. Window
semantics (daily grain assumption, offset direction, period boundaries) vary between
platforms and are the most likely source of subtle data mismatches.

**Runtime note:** If the source MV uses `offset` in any `window:` entry, the MV was
authored on a Runtime 18.1+ warehouse. This has no impact on the `from-databricks`
parser (it reads what exists), but note it in the review checkpoint for the user's
awareness.

**Why COUNT_DISTINCT is a formula, not a simple aggregate:** Using `aggregation: COUNT_DISTINCT`
on a direct `column_id` causes ThoughtSpot to silently override `column_type: MEASURE` to
`ATTRIBUTE` on the physical column reference. Always create a `formulas[]` entry with
`unique count ( [TABLE::col] )` instead.

**Aggregate extraction mapping:**

| Databricks aggregate | ThoughtSpot `aggregation` |
|---|---|
| `SUM` | `SUM` |
| `COUNT` | `COUNT` |
| `AVG` | `AVERAGE` |
| `MIN` | `MIN` |
| `MAX` | `MAX` |

> **MANDATORY — read the reference before assessing any expression:**
> Open [../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md](../../shared/mappings/ts-databricks/ts-databricks-formula-translation.md)
> and use its **Databricks → TS** sections for each SQL pattern. Do **not** classify
> an expression as untranslatable based on SQL syntax recognition alone.

**Formula translation examples:**

| Databricks `expr` | ThoughtSpot formula |
|---|---|
| `date_trunc('day', transaction_date)` | `date ( [TABLE::transaction_date] )` |
| `date_trunc('month', col)` | `start_of_month ( [TABLE::col] )` |
| `CASE WHEN x > 10 THEN 'High' ELSE 'Low' END` | `if ( [TABLE::x] > 10 ) then 'High' else 'Low'` |
| `SUM(price * quantity * (1 - discount))` | `sum ( [TABLE::price] * [TABLE::quantity] * ( 1 - [TABLE::discount] ) )` |
| `SUM(x) / COUNT(DISTINCT y)` | `sum ( [TABLE::x] ) / unique count ( [TABLE::y] )` |

**Column references in translated formulas:**

Use the `name:` from the corresponding `model_tables[]` entry. Column name is the
column name from the ThoughtSpot Table TML.

Example:
- MV EXPR: `SUM(product_price * quantity * (1 - discount_percent))`
- ThoughtSpot formula: `sum ( [ECOMMERCE_TRANSACTIONS::product_price] * [ECOMMERCE_TRANSACTIONS::quantity] * ( 1 - [ECOMMERCE_TRANSACTIONS::discount_percent] ) )`

**Curly brace formulas — YAML block scalar required:**

When the translated formula contains `{ [col] }` (curly braces — e.g. in
`group_aggregate` LOD formulas or `last_value` semi-additive formulas), use a `>-`
block scalar for the `expr` field. Inline YAML string assignment fails because `{`
is a flow mapping start character:

```yaml
formulas:
- name: "Category Total Revenue"
  expr: >-
    group_aggregate ( sum ( [TABLE::LINE_TOTAL] ) , { [TABLE::CATEGORY_NAME] } , query_filters ( ) )
  properties:
    column_type: MEASURE
- name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [TABLE::FILLED_INVENTORY] ) , query_groups ( ) , { [TABLE::BALANCE_DATE] } )
  properties:
    column_type: MEASURE
```

In Python, set the formula string in the dict as a plain string — `yaml.dump` will emit
it as a block scalar automatically when the string contains `{`. If it doesn't, force it:

```python
from yaml.representer import SafeRepresenter

def literal_representer(dumper, data):
    if '{' in data or '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='>')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, literal_representer)
```

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

### Step 9: Build the Model TML

Construct the model TML as a YAML string. Use the templates in
[../../shared/mappings/ts-databricks/ts-from-databricks-rules.md](../../shared/mappings/ts-databricks/ts-from-databricks-rules.md).

**Model name:** `{view_name_title_case}` — derived from the Databricks Metric View name.
Ask the user if they want a different name. Do not add a `TEST_MV_` or other prefix —
see `../../shared/schemas/ts-model-conversion-invariants.md` (N1).

**Model description:** Include source metadata only — filters are enforced via the
model-level `filters:` section, not documented in the description:

```python
model_description = f"Imported from Databricks Metric View: {catalog}.{schema}.{view_name}"
```

**Filter handling:** If the MV has a `filter:` field, **always create a boolean formula
column** — never rely on description-only documentation. Users won't remember to apply
column filters manually; a formula makes the filter discoverable and pinnable.

```
If the MV has a filter:
  1. Translate the SQL filter to a ThoughtSpot boolean formula
  2. Create a formula column:
       name: "MV Filter"
       id: "formula_MV Filter"
       expr: <translated SQL filter → ThoughtSpot formula>
       column_type: ATTRIBUTE
  3. Add a columns[] entry with formula_id: "formula_MV Filter"
  4. Add a model-level filters: section to apply the filter automatically:
       filters:
       - column:
         - MV Filter
         oper: in
         values:
         - 'true'
  5. Note in description: "MV Filter applied automatically via model filter."
```

The `filters:` section is a model-level filter — it applies to ALL queries against
the model without users needing to do anything. This is the correct way to enforce
the MV's global filter in ThoughtSpot. Without it, the formula column exists but
is never applied unless users manually pin it.

**SQL → ThoughtSpot filter translation:**

| SQL pattern | ThoughtSpot formula |
|---|---|
| `col = 'val'` | `[TABLE::col] = 'val'` |
| `NOT col` (boolean) | `[TABLE::col] = false` |
| `col IN ('a', 'b')` | `[TABLE::col] = 'a' or [TABLE::col] = 'b'` |
| `col BETWEEN a AND b` | `[TABLE::col] >= a and [TABLE::col] <= b` |
| `col >= 'date'` | `[TABLE::col] >= 'date'` |

**Example — complex filter formula:**
```yaml
formulas:
- id: "formula_MV Filter"
  name: "MV Filter"
  expr: >-
    [TABLE::is_return] = false and ( [TABLE::transaction_status] = 'Completed' or [TABLE::transaction_status] = 'Shipped' )
  properties:
    column_type: ATTRIBUTE

columns:
# ... other columns ...
- name: "MV Filter"
  formula_id: "formula_MV Filter"
  properties:
    column_type: ATTRIBUTE

filters:
- column:
  - MV Filter
  oper: in
  values:
  - 'true'
```

**Critical `id` rules (applies to all scenarios):**
- **`id` must equal `name` exactly** (same case, same characters). ThoughtSpot resolves
  `with` and `on` join references against the table's actual `name` — if `id` differs
  in case, joins fail with "{table_name} does not exist in schema". Use the exact
  ThoughtSpot table object name for both `id` and `name`.
- `id` values must be **unique** across all `model_tables` entries
- `name` values must also be **unique** — ThoughtSpot rejects models where two tables
  share the same `name` value ("Multiple tables have same alias")

**Model TML skeleton (v0.1 — single source, Scenario A):**

```yaml
model:
  name: "{view_name}"
  description: "Imported from Databricks Metric View: {catalog}.{schema}.{view_name} | Filter: {filter}"
  model_tables:
  - id: SOURCE_TABLE          # MUST equal name exactly
    name: SOURCE_TABLE        # exact ThoughtSpot table object name
    fqn: "{table_guid}"       # GUID from Step 8A
  columns:
  - name: "{dimension_display_name}"
    description: "{comment}"             # from MV comment field (v1.1)
    column_id: SOURCE_TABLE::{physical_col}
    properties:
      column_type: ATTRIBUTE
      synonyms:                          # from MV synonyms field (v1.1)
      - "{synonym_1}"
      synonym_type: USER_DEFINED
  - name: "{measure_display_name}"
    description: "{comment}"
    column_id: SOURCE_TABLE::{physical_col}
    properties:
      column_type: MEASURE
      aggregation: SUM
      synonyms:
      - "{synonym_1}"
      synonym_type: USER_DEFINED
  formulas:
  - id: "formula_{formula_name}"
    name: "{formula_name}"
    expr: "{translated_ts_formula}"
    properties:
      column_type: MEASURE
```

**Synonym placement:** synonyms MUST be inside `properties:` alongside `column_type`,
with `synonym_type: USER_DEFINED`. Top-level `synonyms:` at the column root is silently
dropped on import — see open-items #5.

**Model TML skeleton (v1.1 — multi-source, inline joins):**

```yaml
model:
  name: "{view_name}"
  description: "Imported from Databricks Metric View: {catalog}.{schema}.{view_name}"
  model_tables:
  - id: PRIMARY_TABLE
    name: PRIMARY_TABLE
    fqn: "{primary_guid}"
    joins:
    - name: "{join_name}"
      with: DIM_TABLE       # REQUIRED — must equal `id` (= `name`) of the target entry
      on: "[PRIMARY_TABLE::{fk_col}] = [DIM_TABLE::{pk_col}]"
      type: INNER
      cardinality: MANY_TO_ONE
  - id: DIM_TABLE
    name: DIM_TABLE
    fqn: "{dim_guid}"
  columns:
  # ... same pattern as single source ...
```

**Every formula must have a `columns[]` entry.** Add a `columns[]` entry with
`formula_id:` for every entry in `formulas[]`:

```yaml
formulas:
- id: formula_Total Sales
  name: "Total Sales"
  expr: >-
    sum ( [ECOMMERCE_TRANSACTIONS::product_price] * [ECOMMERCE_TRANSACTIONS::quantity] * ( 1 - [ECOMMERCE_TRANSACTIONS::discount_percent] ) )
  properties:
    column_type: MEASURE

columns:
# ... physical columns ...
- name: "Total Sales"
  formula_id: formula_Total Sales   # must match the formula's `id` exactly
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX   # recommended for computed numeric measures
```

`aggregation:` on a `columns[]` formula entry is allowed (unlike in `formulas[]` entries
where it causes an import error).

- **Never add `aggregation:` to a `formulas[]` entry** — formulas are self-contained
  via their `expr`. ThoughtSpot rejects TML with `FORMULA is not a valid aggregation type`.

---

### Step 9.5: Spotter enablement

Before assembling the final TML, ask whether Spotter (AI search) should be enabled
for this model. Default is **yes** — Spotter is the primary natural-language
interface for Models, and a converted MV usually exists to be queried this way.

```
Enable Spotter (AI search) for this model? [Y / n] (default: Y)
```

Apply the answer to the model TML's properties block:

```yaml
model:
  name: {view_name}
  # ... model_tables, columns, formulas, etc.
  properties:
    spotter_config:
      is_spotter_enabled: true   # or false based on answer
```

If the user answers `n` or `no`, set `is_spotter_enabled: false`. Pre-existing
models being updated in place (Step 11): if the user does not explicitly answer,
preserve the existing setting from the previously-exported model TML rather than
overwriting it with a default.

---

### Step 10: Review checkpoint

Before importing, show the user a summary:

```
Model to import: {view_name}
Source: {catalog}.{schema}.{view_name} (Databricks Metric View v{version})
Filter: {filter_expr or "none"}

Tables:
  ✓ {TABLE_NAME} (GUID: {guid}) — source table

Columns ({n} total):
  ATTRIBUTE: {list of display names}
  MEASURE:   {list of display names}
  Formulas:  {list of display names}

Formula translations:
  ✓ {name}: {dbx_expr} → {ts_formula}
  ⚠ {name}: OMITTED — {reason}

Window measures (review required):
  ⚠ WINDOW {name}: {window_type} → {ts_formula}
    Assumption: {grain assumption, e.g. "daily grain — one row per day"}

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

**1. Determine output filenames:**

- Model TML: `{model_name}.model.tml`
- Any new Table TMLs created in Step 8B (Scenario B): `{table_name}.table.tml`

**2. Write the files:**

```python
from pathlib import Path
import yaml

# Model TML
model_tml_str = yaml.dump(
    {"model": model_dict}, default_flow_style=False, allow_unicode=True
)
Path(f"{model_name}.model.tml").write_text(model_tml_str, encoding="utf-8")

# Table TMLs (Scenario B only)
for tbl_name, tbl_dict in new_table_tmls.items():
    tbl_str = yaml.dump(
        {"table": tbl_dict}, default_flow_style=False, allow_unicode=True
    )
    Path(f"{tbl_name}.table.tml").write_text(tbl_str, encoding="utf-8")
```

**3. Report:**

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

**4. Proceed to Step 12** (Produce summary report) — include the formula translation log
and column summary so the user has the full picture before importing.

---

#### Pre-import validation gate (`ts tml lint` — I1 / I2 / I4 / I5 / I8)

Before running `ts tml import`, lint the generated **Model** TML with **`ts tml lint`** — a
parser-based check of the hard invariants in
[`../../shared/schemas/ts-model-conversion-invariants.md`](../../shared/schemas/ts-model-conversion-invariants.md)
that `--policy VALIDATE_ONLY` does **not** catch (ThoughtSpot accepts the TML and then
behaves wrong, or rejects it on import):

- **I1** — every `formulas[]` entry has a paired `columns[]` entry (`formula_id:` == `id:`). *(Unpaired formula silently dropped.)*
- **I2** — no `aggregation:` inside any `formulas[]` entry. *(Raises "FORMULA is not a valid aggregation type".)*
- **I4** — every `model_tables[]` `id:` (when present) equals its `name:`. *(Mismatch makes joins silently fail.)*
- **I5** — no physical-column `aggregation: COUNT_DISTINCT`; use a `unique count ( [TABLE::col] )` formula. *(Silently flips MEASURE → ATTRIBUTE.)*
- **I8** — no duplicate `column_id` across `columns[]`. *(Hard import rejection: "columns should have unique column_id values".)*

`ts tml lint` reads the same stdin shape as `ts tml import` and exits non-zero on any
finding, so it gates the import (replace `<file>`):

```bash
python3 -c "import json,pathlib; print(json.dumps([pathlib.Path('<file>').read_text()]))" | ts tml lint
```

Do not import until it reports `"clean": true`. Fix any finding and re-lint.

---

### Step 11: Import the model

**IMPORTANT — Updating vs creating:** Without a `guid` field in the TML, ThoughtSpot
always creates a **new** object, even if a model with the same name already exists.
To update an existing model in-place, add `guid` at the **document root** — as a
top-level key alongside `model:`, NOT nested inside `model:`:

```python
# CORRECT — guid at document root
top_level = {"guid": "{existing_model_guid}", "model": model_dict}

# WRONG — guid nested under model (silently ignored by ThoughtSpot)
# model_dict["guid"] = "..."   <- do NOT do this
```

On the first import (new model), omit `guid`. After import, record the GUID from the
response — you will need it if you reimport to fix any errors.

Serialize the top-level dict to a YAML string, then import:

```python
import yaml, json, subprocess

# First import (new model):
top_level = {"model": model_dict}
# Update existing model:
top_level = {"guid": existing_guid, "model": model_dict}

model_tml = yaml.dump(top_level, default_flow_style=False, allow_unicode=True)
payload = json.dumps([model_tml])

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml import --policy PARTIAL --profile '{profile_name}'"],
    input=payload,
    capture_output=True, text=True,
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
```

**Import policy:** Use `--policy PARTIAL` when importing multiple models in a batch.
`ALL_OR_NONE` rolls back the **entire** batch if any single TML fails — including
models that parsed and imported successfully. The response still returns success GUIDs
for the rolled-back models, making the failure silent. Use `ALL_OR_NONE` only for
atomic pairs (one table + one model that references it).

On success, parse the response JSON to extract the created model's GUID. **Save it** —
required for any future reimports to update the model without creating a duplicate.

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
| YAML mapping error on formula with `{` | Formula with `{ [col] }` emitted as inline YAML string | Use `>-` block scalar for `expr` — see Step 6 |
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
omitted from the untranslatable list in Step 6).

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
