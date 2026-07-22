---
name: ts-convert-from-snowflake-sv
description: Convert or import a Snowflake Semantic View into ThoughtSpot as a Model. Use when Snowflake is the source and the goal is a ThoughtSpot Model — whether migrating Snowflake metrics and semantic definitions into ThoughtSpot or making a Semantic View available for Spotter and search-based analytics. Direction is always Snowflake → ThoughtSpot. Not for ThoughtSpot → Snowflake, standalone DDL generation, or adding AI context to existing ThoughtSpot models.
---

# Snowflake Semantic View → ThoughtSpot Model

Converts a Snowflake Semantic View into a ThoughtSpot Model. Reads the semantic
view DDL via `GET_DDL`, then uses three deterministic CLI commands —
`ts snowflake parse-sv` (DDL → structured JSON), `ts snowflake translate-formulas`
(SQL → ThoughtSpot formulas), and `ts snowflake build-model` (JSON → Model TML +
import) — to map tables, relationships, dimensions, and metrics to ThoughtSpot TML.

Two scenarios are supported:
- **Scenario A (existing tables):** ThoughtSpot Table objects already exist for the
  Snowflake objects the semantic view references. Reuses those existing Table objects.
- **Scenario B (new tables):** No ThoughtSpot Table objects exist yet for the Snowflake
  objects the semantic view references. Creates new Table objects pointing to those objects.

---

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md) | Snowflake Semantic View DDL parsing, type mapping, formula translation, column classification |
| [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | SQL → ThoughtSpot formula translation rules (bidirectional reference) |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure, connection reference, data types, import patterns, common errors |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure, join scenarios, formula visibility, self-validation checklist |
| [../../shared/schemas/thoughtspot-formula-patterns.md](../../shared/schemas/thoughtspot-formula-patterns.md) | ThoughtSpot formula syntax, all function categories, LOD/window/semi-additive patterns, YAML encoding rules |
| [../../shared/worked-examples/snowflake/ts-from-snowflake.md](../../shared/worked-examples/snowflake/ts-from-snowflake.md) | End-to-end example: BIRD_SUPERHEROS_SV → ThoughtSpot Model (se-thoughtspot, inline joins, verified against live DDL) |
| [../../shared/worked-examples/snowflake/ts-from-snowflake-dunder.md](../../shared/worked-examples/snowflake/ts-from-snowflake-dunder.md) | End-to-end example: DUNDER_MIFFLIN_SALES_INVENTORY → TS Model. Exercises multi-value synonyms, per-column descriptions, table comments, semi-additive metrics (closing/opening), `unique count` formula, and `concat()` for strings. |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth methods, profile config, CLI usage |
| Cortex Code connection (configured via `cortex connections set`) | Snowflake connection code, SQL execution patterns |
| [references/open-items.md](references/open-items.md) | Known gaps and deferred capabilities for this skill |

---

## Concept Mapping

| Snowflake Semantic View (real DDL format) | ThoughtSpot Model |
|---|---|
| `tables ( DB.SCHEMA.TABLE [primary key (col)] )` | `model_tables[]` — one entry per **physical ThoughtSpot table** |
| `primary key (col)` on a table | Identifies join target — not written into model TML directly |
| `tables ( DB.SCHEMA.TABLE ... comment='...' )` | TS **Table** TML `table.description` — applied as a separate Table-TML update |
| `dimensions ( TABLE.COL as view.NAME [comment='...'] )` | `columns[]` with `column_type: ATTRIBUTE` |
| Dimension with date/timestamp physical column | `columns[]` with `column_type: ATTRIBUTE` (ThoughtSpot infers date type) |
| `metrics ( TABLE.COL as SUM(view.NAME) )` | `columns[]` with `column_type: MEASURE` + aggregation |
| `metrics ( TABLE.COL as complex_sql_expr )` | `formulas[]` with translated ThoughtSpot formula |
| `metrics ( TABLE.COL non additive by (D.col asc nulls last) as SUM(...) )` | `formulas[]` with `last_value(sum(...), query_groups(), {date})` |
| `metrics ( TABLE.COL non additive by (D.col desc nulls last) as SUM(...) )` | `formulas[]` with `first_value(sum(...), query_groups(), {date})` |
| `metrics ( ... OVER (ORDER BY col ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) )` — cumulative/running sum, no `PARTITION BY EXCLUDING` | `formulas[]` with `moving_sum(group_aggregate(agg(...), {[T::PK]}, query_filters()), -1, 0, [T::order_col])` — cannot nest aggregates directly in `moving_sum`; must wrap in `group_aggregate` first. **This is a lossy summary row, not exhaustive:** when the SQL has `PARTITION BY EXCLUDING`, the correct mapping is `cumulative_sum`/`cumulative_average`/etc. instead — see the full PARTITION BY EXCLUDING routing decision table in ts-snowflake-formula-translation.md (Translatable Window Function Patterns) |
| `COUNT_IF(boolean_col)` in metrics | `count_if([T::BOOL_COL], [T::PK])` or `sum ( if ( [T::BOOL_COL] ) then 1 else 0 )` — note parentheses required around BOOL in `if()`. `sum_if([T::BOOL], [T::MEASURE])` also works (L6). |
| `relationships ( REL as FROM(FK) references TO(PK) )` | `referencing_join` in model_tables (Scenario A, pre-defined joins) OR `joins[]` inline (Scenario B) |
| `with synonyms=('Display Name','Alt 1','Alt 2',...)` on a dimension/metric | First → column `name`. Rest → `properties.synonyms` (with `properties.synonym_type: USER_DEFINED`). |
| `comment='...'` on a dimension/metric | column `description` |
| Top-level `comment='...'` (after metrics block) | Model TML `model.description` |
| `with extension (CA='...')` | Not mapped to ThoughtSpot — logged in report |

**Key structural rules:**
- `column_id` must use the **column name from the ThoughtSpot Table TML**. Export
  Table TMLs to confirm — do not assume they match the semantic view left-hand side.
- Simple metrics (`AGG(view.col)` — one column, one aggregate) → `MEASURE` column.
  Complex expressions → `formulas[]` entry.
- In Scenario A, `referencing_join` points to a join pre-defined at the ThoughtSpot
  Table object level (found by exporting the FROM table's TML).
- In Scenario B / hybrid, inline `joins[]` on the FROM table entry (requires `with` field).

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

### Snowflake

- Role with `USAGE` on the database and schema containing the semantic view
- Connection configured — run `/ts-profile-snowflake` if you haven't already
- For Scenario B: role with `CREATE TABLE` or connection modification rights

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-convert-from-snowflake-sv** — convert a Snowflake Semantic View into a ThoughtSpot Model, translating tables, joins, and SQL expressions.

Steps:
  1.   Authenticate (ThoughtSpot + Snowflake) ............. auto
  1.5. Choose session mode (A: single / B: merge / C: update) . you choose
  2.   Identify the semantic view ......................... you choose
  3.   Get the semantic view DDL .......................... auto
  4.   Parse the DDL ..................................... auto (ts snowflake parse-sv)
  5.   Table registration question (reuse or create) ...... you choose
  6.   Discover / create ThoughtSpot Table objects ........ auto (may ask for clarification)
  6D.  Apply SV table descriptions to TS Table TMLs ....... auto (when SV has table comments)
  7.   Find join names (Scenario A) ...................... auto
  8.   Assemble tables map ............................... auto
  9.   Translate SQL expressions → ThoughtSpot formulas ... auto (ts snowflake translate-formulas)
  9.5. Confirm Spotter enablement (default: enabled) ...... you choose
 10.   Review checkpoint — inspect TML before import ...... you confirm
 11.   Import the model into ThoughtSpot .................. auto (ts snowflake build-model)
 12.   Verify import and produce summary report ........... auto
 12.5. Import verified queries as NLS Feedback ............ auto (when SV has verified queries)

File-only mode: at Step 10, choose FILE to write TML files for manual import.

Confirmation required: Steps 1.5, 5, 9.5, 10 (Modes A/B); Steps 1.5, C4 (Mode C)
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Workflow

### Step 1: Authenticate

**Session continuity:** If profiles were already confirmed earlier in this conversation
(e.g. for a previous view in a batch), skip this step and reuse them.

**ThoughtSpot profile:**
1. Run `ts profiles list` to show configured profiles.
2. If multiple profiles: display a numbered list and ask the user to select one.
3. If exactly one profile: display it and confirm before proceeding.
4. Verify: `ts auth whoami --profile {name}` — print display_name and base URL.

**Snowflake connection:**
Uses the active Cortex Code connection (configured via `cortex connections set`).
Verify with a `SELECT CURRENT_USER(), CURRENT_ROLE()` query.

---

### Step 1.5: Session Mode

```
Choose a conversion mode:
  A — Convert ONE Semantic View → new ThoughtSpot Model   (default)
  B — Merge MULTIPLE Semantic Views → new ThoughtSpot Model
  C — Update an EXISTING ThoughtSpot Model from a changed Semantic View
```

If the user selects **A** (or presses Enter): set `session_mode = "single"`. Continue
with the workflow unchanged — Steps 2 through 13 run exactly as documented.

If the user selects **B**: set `session_mode = "merge"`. The modified Steps 2, 3, and
new Step 3.5 below apply; Steps 4–13 then run on the merged result exactly once.

If the user selects **C**: set `session_mode = "update"`. Skip Steps 2–13 entirely.
Run the **Mode C workflow** documented in the section below, then stop.

---

---

## Mode C: Update an Existing ThoughtSpot Model

**Run these steps when `session_mode = "update"` (Mode C selected at Step 1.5).
Skip Steps 2–13 entirely. When Step C6 completes, the session ends.**

---

### Step C1: Identify both objects

```
Semantic View (source — the updated version):
  Enter database.schema.view_name or press Enter to browse: _______

ThoughtSpot Model (target — the existing model to update):
  G — I have a GUID
  S — Search by name

Enter G / S:
```

Store `{sv_name}` and `{model_guid}`. Always require both to be explicitly selected —
do not attempt to auto-match by name.

---

### Step C2: Fetch both in parallel

Run simultaneously:

**SV side** — fetch and parse the DDL:
```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{sv_name}');
```
```bash
printf '%s' "$DDL" > sv_ddl.sql
source ~/.zshenv && ts snowflake parse-sv sv_ddl.sql --output parsed.json
source ~/.zshenv && ts snowflake translate-formulas --input parsed.json --output translated.json
```

**ThoughtSpot side** — export the existing model:
```bash
source ~/.zshenv && ts tml export {model_guid} --profile {profile} --fqn --associated --parse
```

Extract from the Model bundle: the `model` TML dict, its `columns[]` (with description,
synonyms, ai_context, formula_id, column_id per column), and its `formulas[]` (keyed
by `id` → `expr`). These are used by `ts snowflake diff` in Step C3.

---

### Step C3: Compute the change set (`ts snowflake diff`)

The column-level comparison (expression normalisation, new/removed/modified
detection) is now computed by **`ts snowflake diff`** (ts-cli v0.30.0+) — a
parser-based check, same rationale as the `ts tml lint` pre-import gate. Join-graph
comparison stays a separate, skill-local step (below) since it needs the model's
join shape, not just column text — `ts snowflake diff` only compares columns.

**IMPORTANT:** the SV side was already translated via `ts snowflake translate-formulas`
in Step C2 — the comparison is TS-formula-to-TS-formula, not raw SQL to TS formula.

Build the two column maps and write them to temp JSON files. The "current" map comes
from the exported Model TML (description, synonyms, formula expr per column). The "new"
map comes from `translated.json` (description, synonyms, `ts_expr` per translated entry).

```bash
ts snowflake diff --current /tmp/ts_sv_diff_model.json --new /tmp/ts_sv_diff_sv.json \
  --ignore-empty-new-description
rm -f /tmp/ts_sv_diff_*.json
```

`--ignore-empty-new-description` reproduces this skill's description-comparison
rule: only flag a description change when the SV supplies a non-empty new value —
a blank SV description means "no opinion," not "clear the ThoughtSpot description."

Parse the printed `change_set` JSON from stdout — `new_columns`, `removed_columns`
(flag only), `modified_descriptions`, `modified_synonyms` (each with `added`/
`removed`), `modified_expressions` — then add the join comparison, which is not
part of `ts snowflake diff`'s output:

Add the join comparison (not part of `ts snowflake diff`'s column-only output):
compare `parsed.json`'s `relationships[]` vs the existing model's join graph.
Flag any relationship not present in the existing model (name or endpoint differs).

---

### Step C4: Present the diff and collect decisions

Display the summary, then per-section review tables. Wait for the user to edit and
type `done` before proceeding.

**Summary**

```
=== Change set for "{model_name}" ===

  ✚ New columns:              {N}   (will be added with generated synonyms + descriptions)
  ✖ Removed columns:          {M}   (flagged only — see note below)
  ✏ Modified descriptions:    {P}   (UPDATE / KEEP per column — default: KEEP)
  ✏ Modified synonyms:        {Q}   (MERGE / UPDATE / KEEP per column — default: MERGE)
  ~ Modified expressions:     {R}   (YES / SKIP per column — confirm before re-translating)
  ~ Join changes:             {S}   (flagged for review)
  = Unchanged columns:        {T}   (no action)
```

**Modified descriptions** — per-column table, default `KEEP`:

| Column | Current (TS Model) | New (from SV) | Action |
|---|---|---|---|
| Amount | Total sales amount in USD | Total revenue in local currency | KEEP |

**Modified synonyms** — per-column table, default `MERGE`:

| Column | Current synonyms | Added by SV | Removed by SV | Action |
|---|---|---|---|---|
| Product Category | category, product group | dept | product group | MERGE |

Options:
- `MERGE` *(default)* — add new SV synonyms, keep existing; never remove coached synonyms
- `UPDATE` — replace existing synonyms entirely with the SV set
- `KEEP` — ignore the SV change; leave existing synonyms untouched

**Modified expressions** — show old and new formula side-by-side. Require `YES / SKIP`
per column — never bulk-apply expression changes.

**Removed columns** — informational list only, no action column:

```
⚠ The following columns exist in the ThoughtSpot Model but are no longer in the SV.
  They are NOT removed automatically — removal may break dependent Answers and Liveboards.
  To remove them safely: run /ts-dependency-manager first, then edit the Model TML manually.
```

Require the user to type `done` after reviewing before proceeding.

---

### Step C5: Build the updated Model TML and import

Deep-copy the existing Model TML. Apply only the confirmed changes:

| Change type | Action |
|---|---|
| New column | Generate using Step 8 + Step 9 logic — same as create mode |
| Modified description, `UPDATE` | Write to `column.description` |
| Modified description, `KEEP` | Leave untouched |
| Modified synonyms, `MERGE` | Union: add new SV synonyms, keep all existing ones |
| Modified synonyms, `UPDATE` | Replace `properties.synonyms[]` with SV set |
| Modified synonyms, `KEEP` | Leave untouched |
| Modified expression, `YES` | Re-translate using Step 9 logic; update `formulas[].expr` |
| Modified expression, `SKIP` | Leave untouched |
| `ai_context` on any column | **Never touch** |
| Data Model Instructions | **Never touch** |
| Removed columns | **Never touch** |

Build `tables.json` from the existing model's table GUIDs (same format as Step 8), then
import with `build-model --existing-guid`:

```bash
source ~/.zshenv && ts snowflake build-model \
  --parsed parsed.json --translated translated.json --tables tables.json \
  --model-name "{model_name}" --output-dir ./tml_out \
  --existing-guid {model_guid} \
  --profile {profile}
```

The `--existing-guid` flag stamps `guid` at the document root and skips the two-pass
phase 1 (update-in-place). The import will fail if the GUID is not found — surface the
error from the summary JSON's `import_error` field.

---

### Step C6: Post-import coaching handoff

After a successful import, always surface:

```
✓ Model "{model_name}" updated.

⚠ Coaching surfaces that may need review:

  Column AI Context
    {N_new} new columns added — no ai_context yet
    {M_updated} existing columns had descriptions or synonyms changed
    → Run /ts-object-model-coach → surface 1 to review and update ai_context

  Data Model Instructions
    Schema changes (new columns, expression changes, join changes) may affect
    Spotter's default behaviours — particularly time_defaults and aggregation_defaults.
    → Run /ts-object-model-coach → surface 5 to review Instructions

  Removed columns flagged above
    If you intend to remove any of the flagged columns, run /ts-dependency-manager
    first to assess downstream impact before editing the Model TML manually.
```

---

### Step 2: Identify the semantic view

**Single mode (`merge_mode = False`):** proceed as documented below.

**Merge mode (`merge_mode = True`):**

1. Also ask for the output ThoughtSpot Model name now:
   ```
   Output ThoughtSpot Model name: _______
   ```
2. Ask the user to list the Semantic Views to merge. Accept either:
   - A comma-separated list of names: `SALES_SV, INVENTORY_SV`
   - A wildcard/prefix — Claude will run:
     ```sql
     SHOW SEMANTIC VIEWS LIKE '{prefix}%' IN SCHEMA {database}.{schema};
     ```
     and display matches for user confirmation before proceeding
3. Confirm the final list before proceeding to Step 3.

**Single mode:** If the user has named the semantic view, proceed directly to Step 3.

Otherwise, list available semantic views so the user can choose:

```sql
SHOW SEMANTIC VIEWS IN SCHEMA {database}.{schema};
```

If the database and schema are unknown, ask the user or run `SHOW DATABASES` /
`SHOW SCHEMAS IN DATABASE {db}` first.

Display results as a numbered list. Ask the user to select one (or enter a full
`database.schema.view_name` directly).

---

### Step 3: Get the semantic view DDL

**Single mode:** run as documented below.

**Merge mode:** execute `GET_DDL` for each SV in the confirmed list. Parse each DDL
independently using the Step 4 logic and store as a separate parse result object before
proceeding to Step 3.5.

```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{view_name}');
```

Store the returned DDL string in full — it will be parsed in the next step.

If the call fails with "object does not exist", verify the fully-qualified name and
the user's role has `USAGE` on the schema.

**Converting multiple views from the same schema?** List then fetch each DDL:
```sql
SHOW SEMANTIC VIEWS IN SCHEMA {database}.{schema};
SELECT "name" FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
-- then per name:
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}."' || name || '"') AS ddl;
```
Parse each DDL in Step 4 before switching Snowflake queries.

---

### Step 3.5: Merge and Deduplication (merge mode only)

**Skip this step if `merge_mode = False`.**

Combine all parse results from Step 3 into a single merged result that Steps 4–13
will treat as if it came from one Semantic View.

**1. Tables** — union of all `tables[]` entries across all SVs.
- Deduplicate by **physical identity**: two entries with the same
  `base_table.database + schema + table` represent the same Snowflake table. Keep one.
- If their column definitions differ (different dimensions, different data types for
  the same column name), flag as a **column conflict** — list each conflicting column
  and ask the user which definition wins before continuing.

**2. Relationships** — union of all `relationships[]`.
- Deduplicate by (left_table, right_table, left_column, right_column) — exact match
  on all four fields. Keep one entry.
- If the same table pair has conflicting relationship definitions (different column
  pairs), flag as a **relationship conflict** for user resolution.

**3. Metrics** — union of all `metrics[]`.
- Deduplicate by (name, expr) — exact match on both. Keep one entry.
- If same name but different expr: flag as a **metric conflict**. User must choose
  which definition wins or rename one before the merge can proceed. Do not silently
  prefer either definition.

**4. Dimensions / time_dimensions / metrics / facts (if present)** — union across all
views, deduplicated by (table_name, column_name). DDL `facts ()` entries (row-level named
expressions) are also merged and available for identifier resolution in Step 9.

**5. Fact table identification in merged context** — re-run the fact-table detection
algorithm (tables with no incoming relationships in the merged relationship set = fact
tables). If a table was a fact in one SV but gains an incoming relationship from
another SV in the merged graph, present it to the user:
```
{TABLE} had no incoming joins in {SV1} but gains one from {SV2} in the merged model.
Treat as:  F — Fact table   D — Dimension table
```

**6. Present merge summary and require confirmation before continuing:**
```
Merging {M} Semantic Views:

  {SV1}:  {n} tables, {n} relationships, {n} metrics
  {SV2}:  {n} tables, {n} relationships, {n} metrics
  ...

Merged result:  {n} tables ({x} deduplicated), {n} relationships, {n} metrics
Conflicts:      {None / list of conflicts to resolve}

Output model name: {name from Step 2}
Proceed? YES / NO
```

If there are unresolved conflicts, require all to be resolved before accepting YES.
After confirmation, continue with Step 4 using the merged result.

---

### Step 4: Parse the DDL

Write the DDL from Step 3 to a file and parse it with `ts snowflake parse-sv`:

```bash
printf '%s' "$DDL" > sv_ddl.sql
source ~/.zshenv && ts snowflake parse-sv sv_ddl.sql --output parsed.json
```

The command extracts all SV constructs deterministically: tables (with aliases, primary
keys, range constraints, table comments), relationships (equi/range/ASOF/composite),
dimensions, metrics (simple, semi-additive, window), facts (with filter labels and
private visibility), verified queries, extension JSON, custom instructions, synonyms,
and descriptions. See [ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md)
for the underlying rules (codified in `sv_parse.py`).

Exit code 1 means unsupported constructs were found — the JSON is still written.

**Review the output:**

1. **`warnings[]`** — informational notes (logged in the report).
2. **`unsupported[]`** — constructs the parser could not handle. Display each to the
   user and stop if any are critical (unknown grammar, stray range tokens).
3. **`custom_instructions`** — if `ai_sql_generation` or `ai_question_categorization`
   are present, log as "Custom instructions present — review for ThoughtSpot
   data_model_instructions equivalent (GAP-06)" in the report.
4. **`verified_queries[]`** — stored for Step 12.5 (NLS Feedback TML import).

The parsed output contains: `tables[]`, `relationships[]`, `dimensions[]`, `metrics[]`,
`facts[]`, `verified_queries[]`, `extension`, `custom_instructions`, `comment` (model
description), and `view_name`/`database`/`schema` identity fields.

---

### Step 5: Table registration question

After parsing, display the tables found and ask a single question:

```
The semantic view references {n} tables:
  {database}.{schema}.{TABLE_1}
  {database}.{schema}.{TABLE_2}
  ...

Are these tables already registered in ThoughtSpot?
  Y  Yes — use existing ThoughtSpot Table objects
  N  No  — create new Table objects from scratch
  ?  Not sure — search ThoughtSpot first

Enter Y / N / ?:
```

- **Y** → skip search, go to Step 6A (column verification only)
- **N** → skip search, go to Step 6B (create)
- **?** → go to Step 6A (search + verify)

---

### Step 6A: Discover and verify existing ThoughtSpot Table objects (Y and ? paths)

Skip this step if the user answered **N** in Step 5 — go directly to Step 6B.

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
  N (name it) / F (filter by substring) / L (list all) prompt in Step 6B — present that
  prompt and let the user choose; do NOT run `ts connections list` and dump every
  connection by default.** Then keep only results whose `metadata_header.dataSourceName`
  equals the chosen connection name (each result carries its connection there, e.g.
  `"APJ_SNOW"`). Fastest, and unambiguous when the same table name exists on several
  connections.
- **I (entire instance)** → run the name search above with no connection filter.

Filter the JSON to match each semantic view base table by table name (`metadata_name`)
and, for the connection scope, `metadata_header.dataSourceName`; use
`metadata_header.database_stripes` / `metadata_header.schema_stripes` to disambiguate
same-named tables. Build a map: `physical_table_name → {metadata_id, metadata_name}`.

> Only fall back to `--all` (fetch every table) when no usable name pattern can be
> formed (e.g. the name is too generic). Tell the user that cost before running it.

**Export TMLs for all found tables in one call to verify columns:**

```bash
source ~/.zshenv && ts tml export {guid1} {guid2} ... --profile {profile} --parse
```

`--parse` returns structured JSON — access columns via `item["tml"]["table"]["columns"]`
directly. Parse `table.columns[].name` from each returned item. Build a column map per table:
`table_name → [col_name, ...]`. Compare against the columns referenced in
the semantic view dimensions and metrics to identify any column gaps.

> The `column_id` in the model TML must use the column names from the ThoughtSpot
> Table TML — export the TMLs to confirm them.

**Confirm the plan before making any changes:**

Show the user a full status table and wait for confirmation:

```
Table Plan:
  ✓  {TABLE_1}  — found (GUID: {guid}) — all {n} columns present → use as-is
  ⚠  {TABLE_2}  — found (GUID: {guid}) — missing {n} columns: {COL_A}, {COL_B} → update
  ✗  {TABLE_3}  — not found in ThoughtSpot → create new

Actions to be taken:
  • Update {TABLE_2}: add {n} missing columns
  • Create {TABLE_3}: {n} columns from Snowflake schema

No changes have been made yet. Proceed? (yes/no):
```

Do not proceed until the user confirms. If any table is **not found**, follow Step 6B
for those tables. If any table has **missing columns**, follow Step 6C before building
the model.

---

### Step 6D: Apply SV table-level metadata to ThoughtSpot Table TMLs

If the SV `tables (...)` block has `comment='...'` on any base table, push those
descriptions onto the corresponding ThoughtSpot Table objects before building the
model. This is a separate Table TML import, run with `--no-create-new` so existing
tables are updated in place.

**Per table that has an SV table-comment:**
1. Take the parsed Table TML from Step 6A.
2. Set `table.description` to the SV table comment.
3. Verify `table.schema` matches the actual Snowflake schema — older Table objects
   sometimes claim a different schema than the live object, which breaks import
   validation. If there's a mismatch, also fix `table.schema` here.
4. Wrap with `{guid: ..., table: ...}` at top level so `--no-create-new` updates the
   existing object.

Batch all updates into one `ts tml import --policy ALL_OR_NONE --no-create-new` call.

If the SV does not put `comment='...'` on any table, skip this step.

---

### Step 6C: Update existing tables with missing columns

For each table from Step 6A with a column gap, introspect the Snowflake schema
for the missing columns only:

```sql
SELECT table_name, column_name, data_type
FROM {database}.information_schema.columns
WHERE table_schema = '{SCHEMA}'
  AND table_name IN ({comma_quoted_table_names})
  AND column_name IN ({comma_quoted_missing_col_names})
ORDER BY table_name, ordinal_position;
```

Map Snowflake types to ThoughtSpot types using `../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md`.

Find the ThoughtSpot connection for those tables:
```bash
source ~/.zshenv && ts connections list --profile {profile}
```
**Note:** `ts connections list` auto-paginates and returns all connections.

Add the missing columns to the connection, then re-import the updated Table TML
for each affected table (batch all imports in one call):
```bash
source ~/.zshenv && ts tml import --policy ALL_OR_NONE --profile {profile}
```

After import, re-export the updated TMLs to refresh the column map before Step 8.

---

### Step 6B: Create ThoughtSpot Table objects for views (Scenario B) — also the connection picker for the Step 6A connection-scoped search

**Use `ts snowflake introspect` to query Snowflake and build the table spec:**

1. First, choose the ThoughtSpot connection (step 2 below), then run:

   ```bash
   source ~/.zshenv && ts snowflake introspect \
     --parsed parsed.json --sf-profile {sf_profile} \
     --connection-name "{connection_name}" --output-dir ./introspect_out
   ```

   This queries `INFORMATION_SCHEMA.COLUMNS` for all SV source tables in one batch,
   maps Snowflake types to ThoughtSpot types, and produces:
   - `introspect_out/tables-spec.json` — input for `ts tables create`
   - `introspect_out/tables.json` — input for `ts snowflake build-model --tables`

   The summary JSON on stdout includes `{tables, total_columns, warnings}`.

   If `ts snowflake introspect` is not available or the Snowflake profile is not set up,
   fall back to the manual batch query:
   ```sql
   SELECT table_name, column_name, data_type
   FROM {database}.information_schema.columns
   WHERE table_schema = '{SCHEMA}'
   ORDER BY table_name, ordinal_position;
   ```

2. Choose which ThoughtSpot connection to use — **use an existing one or create a new
   one**. Use the connection **name** directly in table TML — no GUID lookup is needed
   or possible from available procedures.

   Ask first:

   ```
   The new Table objects need a ThoughtSpot connection that can reach {database}.
     E  Use an existing connection
     C  Create a new connection   (Snowflake, key-pair auth)

   Enter E / C:
   ```

   > **When to create:** a ThoughtSpot connection only sees databases its Snowflake
   > **role** is granted. If no existing connection's role can see `{database}`, table
   > creation fails with *"Database {db} does not exist in connection"* — that is the
   > signal to create one (do **not** trial-and-error existing connections to find out).

   **E — use an existing connection.** Don't dump the full list by default — a long
   connection list is noise when the user already knows the one they want. Ask:

   ```
   How would you like to identify the connection?
     N  Name it     — type the exact connection name; I'll use it directly
     F  Filter      — give a partial string; I'll list only connections that match
     L  List all    — show every connection and pick by number

   Enter N / F / L:
   ```

   Then fetch the connections once (auto-paginated, returns all):

   ```bash
   source ~/.zshenv && ts connections list --profile {profile}
   ```

   Resolve the user's choice against that result:

   - **N (name it)** — match the typed name against the returned `name` values
     (case-sensitive). Exactly one match → use it. No match → show the closest names and
     re-ask. Don't fabricate a name the list doesn't contain — the table TML needs the
     exact, case-sensitive connection name.
   - **F (filter)** — keep connections whose `name` contains the string (case-insensitive),
     show them as a short numbered list (name, type, database), and pick from that. One
     match → auto-select and confirm; none → widen the string or switch to **L**.
   - **L (list all)** — show the full numbered list and pick by number.

   If only one connection exists in total (or only one matches the semantic view's
   database), auto-select it and confirm regardless of the choice. Use the exact `name`
   value from the API response.

   **C — create a new connection (Snowflake, key-pair auth).** Collect the connection
   name, Snowflake account identifier, user, role, warehouse, and the path to the
   **unencrypted PKCS#8 private key** (`.p8`), then run:

   ```bash
   source ~/.zshenv && ts connections create \
     --name "{connection_name}" \
     --account "{account}" --user "{user}" --role "{role}" --warehouse "{warehouse}" \
     --database "{database}" \
     --private-key-path "{key_path}" \
     --profile {profile}
   ```

   The role must have `USAGE` on `{database}` and its schema (and `SELECT` on the
   tables) — otherwise the tables won't resolve. The matching **public** key must already
   be registered on the Snowflake user (`DESC USER {user}` shows `RSA_PUBLIC_KEY`).

   **Credential handling (required):** never ask the user to paste a private key,
   password, or secret into the conversation. The key is passed **by file path only** —
   `ts connections create` reads it and never echoes it. Key-pair is the only auth this
   path supports; for password/OAuth, direct the user to create the connection in the
   ThoughtSpot UI and return on the **E** path. The command prints
   `{id, name, data_warehouse_type}` — use the returned `name` for the table spec.

3. Create ThoughtSpot Table objects for all tables in one command:
   ```bash
   cat introspect_out/tables-spec.json | ts tables create --profile {profile}
   ```
   The `tables-spec.json` from `ts snowflake introspect` is ready to use. This command
   handles JDBC retry and GUID resolution automatically, and outputs `{name: guid}`.
   The `introspect_out/tables.json` is the tables map for `ts snowflake build-model`
   in Step 8 — use it directly.

4. Inline joins will be defined directly in the model TML (no `referencing_join`).

---

### Step 7: Find join names (Scenario A only)

If there is only ONE table in the semantic view, there are no joins by definition.
Skip this step and proceed to Step 8 with a single `model_tables` entry.

**Joinless semantic views (GAP-03) — multi-table SVs with no relationships:**

If the SV has multiple tables but no `relationships(...)` block (or the block is empty),
ThoughtSpot still requires joins for cross-table queries. Present the user with join
discovery options:

```
No relationships defined in the Semantic View ({n} tables found).
ThoughtSpot requires joins for cross-table queries.

How should we discover joins?

  1 — Auto-discover from database constraints (PK/FK)
  2 — Analyse column overlap and suggest joins (deeper dive)
  3 — I'll specify the joins manually
  4 — Skip — create model with no joins (single-table queries only)
```

**Option 1 — Database constraint discovery:**

Query Snowflake for foreign key relationships between the SV's tables:

```sql
-- For each table in the SV:
SHOW IMPORTED KEYS IN TABLE {db}.{schema}.{table};
```

The result contains `pk_table_name`, `pk_column_name`, `fk_table_name`, `fk_column_name`,
and `key_sequence` (for composite FKs with the same constraint name). Build relationships
from these — each FK→PK pair becomes a join. Composite FKs (multiple rows with the same
constraint name) become composite equi-joins.

If FK constraints are found, present them for confirmation:

```
Found {n} foreign key relationships:

  1. {FK_TABLE}.{FK_COL} → {PK_TABLE}.{PK_COL}  (MANY_TO_ONE)
  2. {FK_TABLE}.({COL1},{COL2}) → {PK_TABLE}.({COL1},{COL2})  (composite, MANY_TO_ONE)

Accept these joins? [Y / edit / skip]
```

If no FK constraints are found, offer to fall back to Option 2 (column overlap analysis).

**Option 2 — Column overlap analysis (deeper dive):**

For each pair of tables in the SV:

1. **Scan column name overlap** — find columns with identical names (case-insensitive)
   across the two tables:
   ```sql
   SELECT a.COLUMN_NAME
   FROM INFORMATION_SCHEMA.COLUMNS a
   JOIN INFORMATION_SCHEMA.COLUMNS b
     ON UPPER(a.COLUMN_NAME) = UPPER(b.COLUMN_NAME)
   WHERE a.TABLE_SCHEMA = '{schema}' AND a.TABLE_NAME = '{table_a}'
     AND b.TABLE_SCHEMA = '{schema}' AND b.TABLE_NAME = '{table_b}'
     AND a.TABLE_CATALOG = '{db}' AND b.TABLE_CATALOG = '{db}';
   ```

2. **Check composite key uniqueness** — for each candidate set of join columns,
   verify uniqueness on the target table:
   ```sql
   SELECT COUNT(*) AS total_rows,
          COUNT(DISTINCT ({col1}, {col2})) AS distinct_keys
   FROM {db}.{schema}.{table};
   ```
   If `total_rows == distinct_keys`, the column set is a valid unique key.

3. **Validate cardinality** — confirm the join direction:
   ```sql
   SELECT MAX(cnt) FROM (
     SELECT {join_cols}, COUNT(*) AS cnt
     FROM {db}.{schema}.{from_table}
     GROUP BY {join_cols}
   );
   ```
   `max(cnt) == 1` → ONE_TO_ONE; `max(cnt) > 1` → MANY_TO_ONE from the source table.

4. **Present suggestions with evidence:**
   ```
   Suggested joins (based on column overlap analysis):

     1. EMPLOYEES.(COMPANY_ID, DEPARTMENT) → EMPLOYEE_SUMMARY_VW.(COMPANY_ID, DEPARTMENT)
        Uniqueness: 15 rows, 15 distinct keys ✓
        Cardinality: MANY_TO_ONE (max 12 employees per group)
        Type: LEFT_OUTER

   Accept / Modify / Skip each:
   ```

**Option 3 — User-specified joins:**

Prompt the user to define each join:

```
Specify joins between the {n} tables.

For each join, provide:
  From table: ______
  From column(s): ______  (comma-separated for composite)
  To table: ______
  To column(s): ______
  Cardinality: MANY_TO_ONE / ONE_TO_ONE / MANY_TO_MANY
  Type: LEFT_OUTER (default) / INNER / RIGHT_OUTER / FULL_OUTER

Add another join? [Y / done]
```

**Option 4 — Skip (separate model per table):**

Since ThoughtSpot cannot query across unjoined tables in a single model, create a
separate model for each table:

```
⚠ No joins defined. Creating {n} separate models — one per table.
  Cross-table queries will not be possible.

  Model 1: {TABLE_A} ({m} columns)
  Model 2: {TABLE_B} ({p} columns)

  You can combine them later by editing Model TML and adding joins.

Proceed? [Y / n]
```

Each model gets its own `model_tables` entry (single table), its own columns
(only those from that table), and its own formulas (only those referencing that
table's columns). Import each model separately.

All discovered/specified joins (Options 1–3) are added to the `relationships` map
and treated identically to SV-declared relationships in Step 8 (inline joins on the
FROM table).

---

For each relationship in the semantic view, find the name of the pre-defined join
in the ThoughtSpot Table objects.

**Re-use the TMLs already exported in Step 6A** — do not make another export call.
The `--parse` output gives `item["tml"]["table"]` directly for each FROM table.

For a relationship `FROM {from_table} KEY {from_col} TO {to_table} KEY {to_col}`:

1. In the FROM table's parsed TML (`item["tml"]["table"]`), find the `joins_with` section.
2. Match the entry where `destination.name` (or `destination`) equals the TO table name.
3. Record the join `name` — this is the `referencing_join` value for the `to_table`
   entry in the model TML.

If no matching join is found:
- Warn the user: "No pre-defined join from `{from_table}` to `{to_table}`."
- Options: (1) use an inline join instead (Scenario B for this relationship),
  (2) abort and define the join at the ThoughtSpot Table level first.

---

### Step 8: Assemble the tables map

Build `tables.json` — a JSON object mapping each SV table alias to its ThoughtSpot
table identity. `ts snowflake build-model` uses this to resolve column references,
build joins, and assemble the model TML.

**Model name:** `{view_name_title_case}` — derived from the Snowflake Semantic View name.
Ask the user if they want a different name. Do not add a `TEST_SV_` or other prefix —
see `../../shared/schemas/ts-model-conversion-invariants.md` (N1).

**CRITICAL — Never normalise names from API responses.** Names that came from
`ts tml export` (join names, column names, table names) or from import response GUIDs
must be used **exactly as returned** — no `.lower()`, no `.upper()`, no title-casing,
no whitespace trimming. The `name` value in `tables.json` must match the ThoughtSpot
Table object name character-for-character.

**Format:**

```json
{
  "ALIAS_1": {"name": "TS_TABLE_NAME", "fqn": "guid_from_step_6"},
  "ALIAS_2": {"name": "TS_TABLE_NAME", "fqn": "guid_from_step_6"}
}
```

- `ALIAS` is the SV table alias from `parsed.json` (the `alias` field in each
  `tables[]` entry).
- `name` is the exact ThoughtSpot Table object name (from `ts tml export` in Step 6A,
  or from `ts tables create` response in Step 6B).
- `fqn` is the ThoughtSpot Table GUID.

**Scenario B** (new tables created via `ts snowflake introspect` in Step 6B):
the `introspect` command produces `tables.json` directly — use it as-is.

**Scenario A** (existing tables from Step 6A): build the map manually from the
Step 6A discovery results.

**Joinless models (user chose Option 4 in Step 7):** create a separate `tables.json`
per table. Each will produce a separate model via `build-model`.
Name each model `{view_name} — {TABLE_NAME}` (or let the user choose).

Write the result to `tables.json`.

**What `build-model` handles from here:**

`ts snowflake build-model` (Steps 10-FILE / 11) takes `parsed.json`, `translated.json`,
and `tables.json` and deterministically assembles the model TML. It handles:
- Fact table detection (tables never on the TO side of a relationship)
- Inline join assembly (equi, range, ASOF, composite) with `LEFT_OUTER` / `MANY_TO_ONE` defaults
- Column classification (ATTRIBUTE / MEASURE), `column_id` resolution
- Formula entries with `formula_id` pairing, `id`-based cross-references
- Synonym mapping (first → display name, rest → `properties.synonyms`)
- Description mapping, filter labels, private columns (`index_type: DONT_INDEX`)
- Duplicate `column_id` detection (I8) — promotes duplicates to formulas
- `COUNT(DISTINCT)` → `unique count(...)` formula (I5)
- Name collision resolution, `formula_` prefix for cross-references
- YAML block scalar encoding for `{ }` formulas

---

### Step 9: Translate SQL expressions → ThoughtSpot formulas

Run the deterministic formula translator:

```bash
source ~/.zshenv && ts snowflake translate-formulas --input parsed.json --output translated.json
```

The command translates all dimension, fact, and metric SQL expressions from Snowflake
SQL into ThoughtSpot formula syntax. It handles:
- Identifier resolution (physical columns → `[TABLE::col]`, facts → `[formula_<id>]`,
  metrics → double aggregation via `group_aggregate`)
- Window functions (`PARTITION BY` → `group_sum`/`group_aggregate`;
  `ORDER BY ROWS BETWEEN` → `moving_sum`/`cumulative_sum`)
- Semi-additive patterns (`NON ADDITIVE BY` → `last_value`/`first_value`)
- LOD expressions, contribution ratios, `COUNT_IF`, `COALESCE`/`NULLIF`
- YAML block scalar encoding for `{ }` formulas

All translation rules come from
[ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
(codified in `sv_sql.py` + `sv_translate.py`).

**Review the output stats** (printed to stdout):

```json
{"total": N, "translated": M, "skipped": K}
```

**Surface `skipped[]` entries to the user** — each has a `name`, `block`, and `reason`.
These are formulas the translator could not handle (unsupported SQL constructs, triple
aggregation, etc.). Ask whether to proceed without them or address manually.

---

### Step 9.5: Spotter enablement

Ask whether Spotter (AI search) should be enabled. Default is **yes**.

```
Enable Spotter (AI search) for this model? [Y / n] (default: Y)
```

Store the answer as a flag for `ts snowflake build-model`:
- **Y** → pass `--spotter-enabled`
- **n** → pass `--no-spotter-enabled`
- Omit the flag entirely to leave the spotter_config block absent (pre-existing
  models being updated in place: if the user does not explicitly answer, omit the
  flag to preserve the existing setting).

---

### Step 10: Review checkpoint

Before importing, show the user a summary assembled from `parsed.json`,
`translated.json`, and `tables.json`:

```
Model to import: {view_name}
Tables:
  ✓ {FACT_TABLE} (GUID: {guid}) — fact table
  ✓ {DIM_TABLE}  (GUID: {guid}) — referencing_join: {join_name}
  ...

Columns ({n} total):
  ATTRIBUTE: {list of display names}
  MEASURE:   {list of display names}
  Formulas:  {list of display names}

Formula translations:
  ✓ {name}: {sql_expr} → {ts_formula}
  🔄 {name}: DOUBLE AGGREGATION — {outer_agg}(group_{inner_agg}(...))
  📐 {name}: FACT REFERENCE — inlines fact expression (from {fact_name})
  ⚠ {name}: OMITTED — {reason}

Filter labels ({n}):
  {name}: boolean formula (column only / also add as model filter?)

Verified queries ({n}):
  {name}: "{question}" → will import as NLS Feedback after Model import

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

Run `ts snowflake build-model` without `--profile` — it generates the TML files to
`--output-dir` without importing:

```bash
source ~/.zshenv && ts snowflake build-model \
  --parsed parsed.json --translated translated.json --tables tables.json \
  --model-name "{model_name}" --output-dir ./tml_out \
  --sv-fqn "{database}.{schema}.{view_name}" \
  {--spotter-enabled|--no-spotter-enabled}
```

The command writes `{model_name}.model.tml` to the output directory, validates TML
invariants, and prints a summary JSON to stdout. Exit code 1 on lint findings.

**Report to the user:**

```
TML files written to ./tml_out/:
  {model_name}.model.tml    — ThoughtSpot Model TML

To import to ThoughtSpot when you have access:
  ts tml import --file ./tml_out/{model_name}.model.tml --policy ALL_OR_NONE --profile {profile}

  Note: On first import, omit `guid` from the TML (already omitted here). ThoughtSpot
  will assign a GUID — save it from the import response if you need to update the model later.
```

**Proceed to Step 12** — include the formula translation log and column summary from
the `build-model` summary JSON.

---

#### Pre-import validation gate

`ts snowflake build-model` runs `ts tml lint` internally before any import — the
command exits 1 on lint findings. See
[`../../shared/schemas/ts-tml-import-gate.md`](../../shared/schemas/ts-tml-import-gate.md)
for the invariant list (I1/I2/I4/I5/I8) and import-policy rules. No separate lint
step is needed.

---

### Step 11: Import the model

Re-run `ts snowflake build-model` with `--profile` to import:

```bash
source ~/.zshenv && ts snowflake build-model \
  --parsed parsed.json --translated translated.json --tables tables.json \
  --model-name "{model_name}" --output-dir ./tml_out \
  --sv-fqn "{database}.{schema}.{view_name}" \
  {--spotter-enabled|--no-spotter-enabled} \
  --profile {profile}
```

For updating an existing model, add `--existing-guid {guid}`.

The command handles:
- **Two-pass import (L7):** phase 1 imports structure only (no formulas) to capture
  the GUID; phase 2 imports the full model with formulas using the captured GUID.
  With `--existing-guid`, phase 1 is skipped (update-in-place).
- **GUID placement:** always at the document root, never nested under `model:`.
- **Pre-import lint:** `ts tml lint` runs internally — the command exits 1 on findings.
- **YAML serialization:** block scalars for `{ }` formulas, Unicode support.

Parse the **summary JSON from stdout** — it includes `import_status` and `model_guid`.
On `import_status: "failed"`, `import_error` gives the error details.

**Common import errors:** see
[`ts-tml-import-gate.md` § 4](../../shared/schemas/ts-tml-import-gate.md#4-common-import-errors).

---

### Step 11b: Verify Import

Follow [`ts-tml-import-gate.md` § 5](../../shared/schemas/ts-tml-import-gate.md#5-post-import-verification).

---

### Step 12: Produce summary report

After a successful import, output:

```
## Model Import Complete

**Model:** {view_name}
**GUID:** {created_guid}
**ThoughtSpot URL:** {base_url}/#/model/{created_guid}

### Columns Imported ({n})
| Display Name | Type | Source |
|---|---|---|
| {name} | ATTRIBUTE | {TABLE}::{COL} |
| {name} | MEASURE ({agg}) | {TABLE}::{COL} |
| {name} | MEASURE (formula) | translated from SQL |
| ... | ... | ... |

### Formula Translation Log
| Column | Original SQL | Status | ThoughtSpot Formula |
|---|---|---|---|
| {name} | `{sql}` | ✓ Translated | `{ts_formula}` |
| {name} | `{sql}` | 🔄 Double aggregation | `{ts_formula}` |
| {name} | `{sql}` | 📐 Fact formula | `{ts_formula}` |
| {name} | `{sql}` | ⚠ Omitted | {reason} |

### Not Mapped
- Extension JSON (Cortex Analyst context): not translated to ThoughtSpot

### Facts Mapped ({n})
| Fact Name | Source Table | Expression | ThoughtSpot Formula |
|---|---|---|---|
| {name} | {table} | `{sql_expr}` | `{ts_formula}` |

### Identifier Resolution Summary
- Physical columns resolved: {n}
- Fact references resolved: {n}
- Double aggregation patterns: {n}
- Unresolvable references: {n} (see OMITTED above)

### Filter Labels ({n})
| Column | Source Expression | Type |
|---|---|---|
| {name} | `{boolean_expr}` | Boolean formula (ATTRIBUTE) |

### Verified Queries ({n})
| Query Name | Question | Status |
|---|---|---|
| {name} | {question} | ✓ Imported as NLS Feedback / ⚠ Manual review needed |
```

---

### Step 12.5: Import verified queries as NLS Feedback TML

**Skip this step if `verified_queries` is empty.**

After a successful Model import (Step 11), translate each verified query from the
SV into NLS Feedback TML and import it against the newly-created Model.

**SQL-to-search-token translation:**
1. Map SV column names to TS Model display names (from the column mapping in Steps 8/9)
2. `COUNT(col)` → `count [Col Display Name]`; `SUM(col)` → `sum [Col]`; `AVG(col)` → `avg [Col]`
3. Non-aggregate SELECT columns → dimension tokens: `[Col Display Name]`
4. `WHERE col = 'val'` → `[Col] = 'val'`

**For each verified query with translatable SQL:**

```yaml
guid: "{model_guid}"
nls_feedback:
  feedback:
  - id: "{index}"
    type: REFERENCE_QUESTION
    access: GLOBAL
    feedback_phrase: "{question_text}"
    search_tokens: "{translated_search_tokens}"
    rating: UPVOTE
    display_mode: UNDEFINED
    chart_type: KPI
```

Import with: `source ~/.zshenv && ts tml import --policy ALL_OR_NONE --profile {profile}`

**Complex SQL** (subqueries, CTEs, CASE, window functions) cannot be faithfully
converted to search tokens. Log these in the report as "manual review needed" — do
not attempt a partial translation.

---

### Step 13: Cleanup

Remove any temporary files written during the workflow:

```bash
rm -f /tmp/ts_model_build_*.yaml /tmp/ts_model_build_*.json
```

The `ts` CLI manages its own token cache — do not remove `/tmp/ts_token_*.txt`
unless the user explicitly requests a logout.

---

## Multiple semantic view conversion

**Sequential (separate models):** After completing Step 12 for one view, ask:
"Convert another semantic view?" If yes: return to Step 2. Reuse the already-confirmed
ThoughtSpot and Snowflake profiles. Do not re-authenticate between views.

**Merge into one model:** Use `merge_mode = True` (Step 1.5 → B). All Semantic Views
are ingested in Step 3, merged in Step 3.5, and converted into a single ThoughtSpot
Model in one pass through Steps 4–13.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.17.1 | 2026-07-22 | Import error table + post-import verification extracted to shared `ts-tml-import-gate.md` §4/§5 (BL-063 phase 1c) |
| 1.17.0 | 2026-07-22 | Rewire onto deterministic CLI commands: Step 4 → `ts snowflake parse-sv`, Step 9 → `ts snowflake translate-formulas`, Steps 8/10-FILE/11 → `ts snowflake build-model`. Removes 8 inline Python code blocks — DDL parsing, formula translation, model TML assembly, YAML serialization, and import are all deterministic. Step 6B adds `ts snowflake introspect` for Scenario B table creation. Mode C updated to use CLI commands. Step 8 becomes "Assemble tables map". (BL-063 phase 1a) |
| 1.16.2 | 2026-07-15 | JSON/VARIANT path access: emit `['key']['subkey']` bracket notation in `sql_*_op` pass-throughs — ThoughtSpot's formula parser rejects Snowflake colon-and-dot path syntax (`PARSE_JSON(x):a.b`) even though it is valid Snowflake SQL. Verified 2026-07-15. |
| 1.16.1 | 2026-07-11 | Remove the dead `direct-api-auth.md` reference-table row (the doc taught a curl + `/tmp/ts_token.txt` fallback now prohibited by `ts-cli.md`/`security.md`, with no step logic using it); doc retired repo-wide (BL-109). |
| 1.16.0 | 2026-07-11 | Recognize SQL-query logical tables (`base_table.definition:` → SQL View TML), `is_enum`/`sample_values` dimension clauses, and free-text `ai_sql_generation`/`ai_question_categorization` instructions (audit 13.5/13.6/13.7). |
| 1.15.0 | 2026-07-11 | Formula function-composition rules (group_* = group_aggregate shorthand; no nesting group functions; raw aggregates must wrap in group_aggregate before window functions; if() conditions require parentheses) + refined cumulative/moving_sum mapping rows. Companion shared-reference additions: Function Composition Rules + if() parens (thoughtspot-formula-patterns.md), cumulative reverse-translation decision table + COUNT_IF table (ts-snowflake-formula-translation.md), TML Import Behaviours (ts-from-snowflake-rules.md). Verified on SE cluster via TML import (Payroll Test Model). |
| 1.14.1 | 2026-07-10 | Pre-import lint gate + import-policy text extracted to shared `ts-tml-import-gate.md` (BL-063 PR5) — content unchanged, now linked. |
| 1.14.0 | 2026-07-10 | Cumulative window metrics: row 25 corrected to `moving_sum(group_aggregate(...))` (aggregates cannot nest directly in `moving_sum`); new `COUNT_IF` mapping; new limitations L6 (BOOL in `if` requires parentheses — prefer `count_if`/`sum_if`) and L7 (formulas referencing `[TABLE::COL]` fail on initial CREATE — documented mandatory two-pass import in Step 11). Verified on SE cluster. |
| 1.13.0 | 2026-07-03 | Step C3 change-set computation delegates to `ts snowflake diff` (BL-063 quick win). Prereq ts-cli v0.30.0. |
| 1.12.0 | 2026-06-17 | Step 6B connection step now offers **E — use existing / C — create a new connection** (Snowflake, key-pair auth via `ts connections create`) instead of only selecting an existing one. Adds the "Database does not exist in connection → role can't see it → create one" guidance and a credential-handling guardrail (private key by file path only; never pasted into chat; password/OAuth → UI + E path). Mirrors the connection-step change in ts-convert-from-tableau; ts-convert-from-databricks-mv gets the explicit stop-and-instruct fallback. |
| 1.11.2 | 2026-06-17 | Replace the hand-written pre-import grep gate with `ts tml lint` (parser-based; now also catches **I8** duplicate `column_id`). From the full audit sweep (codification, angle 11). |
| 1.11.1 | 2026-06-16 | **Extend the N/F/L connection prompt into the Step 6A connection-scoped search path.** The 6A "C — within a connection" path now explicitly presents the Step 6B N (name it) / F (filter by substring) / L (list all) prompt to identify the connection — it must NOT run `ts connections list` and dump every connection by default. Mirrors the same fix in ts-convert-from-tableau and ts-convert-from-databricks-mv. |
| 1.11.0 | 2026-06-16 | Connection selection (Step 6B): add a **how-to-identify-the-connection prompt** (N name it / F filter by partial string / L list all) before dumping the full connection list. Fetch once via `ts connections list`, then use the typed name directly, show a filtered subset, or show the full numbered list. Single/database-matched connection still auto-selects. Mirrors the same prompt added to ts-convert-from-tableau and ts-convert-from-databricks-mv. |
| 1.10.0 | 2026-06-16 | Step 6A table discovery: add a **connection-scoped vs instance-wide search choice** and search by `--name "%table%"` pattern instead of `--all`-then-filter. Connection scope filters results on `metadata_header.dataSourceName` (verified field). Avoids slow whole-instance scans on large instances. Mirrors the ts-convert-from-tableau Step 4c change. |
| 1.9.0 | 2026-06-13 | Identifier resolution engine: facts parsing (BL-003b), metric→fact resolution (BL-003c), double aggregation via group_aggregate (BL-003), window metrics referencing metrics (GAP-13), joinless SV handling (GAP-03/BL-004). |
| 1.8.0 | 2026-06-13 | Fail-loud parsing (C5): Step 4x scans for facts, AI clauses, cortex search, private, unknown grammar. LEFT_OUTER join default (F5). Fix SV discovery SQL (F8). Fix Mode C comparison to translate before diff (F7). |
| 1.7.1 | 2026-06-13 | Add "never normalise API response names" rule (reverse-port from CoCo). |
| 1.7.0 | 2026-06-12 | Adopt PT1 pass-through policy (scalar reliable; flag aggregate pass-through for review). |
| 1.6.0 | 2026-06-12 | Add pre-import validation gate (I1/I2/I4/I5) before model TML import (BL-001). |
| 1.5.0 | 2026-06-11 | Drop `TEST_SV_` prefix — model name now uses the bare SV name (N1); cite canonical conversion invariants doc. Add I5 explicit note: `COUNT(DISTINCT)` → `unique count(...)` formula, never `aggregation: COUNT_DISTINCT`. Add `references/open-items.md` tracking sql_view generation gap. |
| 1.4.1 | 2026-05-11 | Add `source ~/.zshenv &&` prefix to all bash blocks and convert subprocess.run calls from `["ts", ...]` to `["bash", "-c", "source ~/.zshenv && ts ..."]` for consistent env var loading |
| 1.4.0 | 2026-05-05 | Add Mode C (update existing): Steps C1–C6. Identifies a changed SV and an existing TS Model, diffs columns/descriptions/synonyms/expressions, applies per-column reviewed changes with `--no-create-new`, and surfaces /ts-object-model-coach handoff. `ai_context` and Instructions are never touched. Step 1.5 menu updated to A/B/C. |
| 1.3.0 | 2026-04-28 | Add Step 9.5 — confirm Spotter (AI search) enablement before import. Default Y; preserves existing setting on in-place updates. |
| 1.2.0 | 2026-04-28 | Map SV synonyms/descriptions to TS Model + Table TMLs. Add Step 6D for table-description updates. Document `non additive by ... desc` → `first_value`. Fix synonyms placement (`properties.synonyms` not column root). |
| 1.1.0 | 2026-04-24 | Add Step 0 session plan with confirmation gate |
| 1.0.0 | 2026-04-24 | Initial versioned release |
