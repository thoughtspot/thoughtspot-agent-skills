---
name: ts-convert-from-snowflake-sv
description: Convert or import a Snowflake Semantic View into ThoughtSpot as a Model. Use when Snowflake is the source and the goal is a ThoughtSpot Model — whether migrating Snowflake metrics and semantic definitions into ThoughtSpot or making a Semantic View available for Spotter and search-based analytics. Direction is always Snowflake → ThoughtSpot. Not for ThoughtSpot → Snowflake, standalone DDL generation, or adding AI context to existing ThoughtSpot models.
---

# Snowflake Semantic View → ThoughtSpot Model

Converts a Snowflake Semantic View into a ThoughtSpot Model. Reads the semantic
view DDL via `GET_DDL`, maps tables, relationships, dimensions, and metrics to
ThoughtSpot TML, translates SQL expressions to ThoughtSpot formulas, and imports
the result via `ts tml import`.

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
| [../../claude/references/direct-api-auth.md](../../claude/references/direct-api-auth.md) | Direct API authentication fallback when stored procedures are unavailable |
| Cortex Code connection (configured via `cortex connections set`) | Snowflake connection code, SQL execution patterns |

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
  4.   Parse the DDL (incl. synonyms, descriptions) ....... auto
  5.   Table registration question (reuse or create) ...... you choose
  6.   Discover / create ThoughtSpot Table objects ........ auto (may ask for clarification)
  6D.  Apply SV table descriptions to TS Table TMLs ....... auto (when SV has table comments)
  7.   Find join names (Scenario A) ...................... auto
  8.   Build the model TML (incl. column synonyms/desc) ... auto
  9.   Translate SQL expressions → ThoughtSpot formulas ... auto
  9.5. Confirm Spotter enablement (default: enabled) ...... you choose
 10.   Review checkpoint — inspect TML before import ...... you confirm
 11.   Import the model into ThoughtSpot .................. auto
 12.   Verify import and produce summary report ........... auto

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

```sql
SELECT GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.{sv_name}');
```

```bash
source ~/.zshenv && ts tml export {model_guid} --profile {profile} --fqn --associated --parse
```

Parse the SV DDL using the existing Step 4 logic. Extract from the Model bundle:

```python
model_tml   = next(i["tml"]["model"] for i in bundle if i["type"] == "model")
existing = {}
for col in model_tml.get("columns", []):
    existing[col["name"]] = {
        "description":  col.get("description", ""),
        "synonyms":     col.get("properties", {}).get("synonyms", []),
        "ai_context":   col.get("properties", {}).get("ai_context"),   # read-only
        "formula_id":   col.get("formula_id"),
        "column_id":    col.get("column_id"),
    }
existing_formulas = {
    f["id"]: f.get("expr", "")
    for f in model_tml.get("formulas", [])
}
```

---

### Step C3: Compute the change set

```python
import re

def _normalise_expr(expr: str) -> str:
    """Normalise for comparison only — never use the output as actual SQL."""
    refs, i = {}, 0
    def _stash(m):
        nonlocal i
        key = f"__REF{i}__"; refs[key] = m.group(0); i += 1; return key
    # Stash bracket/brace refs so they survive lowercasing
    out = re.sub(r'\[[^\]]+\]|\{[^}]+\}', _stash, expr)
    out = re.sub(r'\s+', ' ', out.strip()).lower()
    for key, val in refs.items():
        out = out.replace(key, val)
    return out

def _exprs_differ(a: str, b: str) -> bool:
    return _normalise_expr(a) != _normalise_expr(b)

sv_cols    = set(sv_parse["columns"].keys())   # keyed by column display name
model_cols = set(existing.keys())

change_set = {
    "new_columns":           list(sv_cols - model_cols),
    "removed_columns":       list(model_cols - sv_cols),   # flag only
    "modified_descriptions": [],
    "modified_synonyms":     [],
    "modified_expressions":  [],
    "join_changes":          [],
}

for col_name in sv_cols & model_cols:
    sv_col = sv_parse["columns"][col_name]
    ts_col = existing[col_name]

    if sv_col.get("description") and sv_col["description"] != ts_col["description"]:
        change_set["modified_descriptions"].append({
            "column": col_name,
            "current": ts_col["description"],
            "new":     sv_col["description"],
        })

    sv_syns = set(sv_col.get("synonyms", []))
    ts_syns = set(ts_col["synonyms"])
    if sv_syns != ts_syns:
        change_set["modified_synonyms"].append({
            "column":   col_name,
            "current":  sorted(ts_syns),
            "new":      sorted(sv_syns),
            "added":    sorted(sv_syns - ts_syns),
            "removed":  sorted(ts_syns - sv_syns),
        })

    if col_name in sv_formulas and ts_col["formula_id"]:
        sv_expr = sv_formulas[col_name]
        ts_expr = existing_formulas.get(ts_col["formula_id"], "")
        if _exprs_differ(sv_expr, ts_expr):
            change_set["modified_expressions"].append({
                "column":  col_name,
                "current": ts_expr,
                "new":     sv_expr,
            })

# Join changes: compare sv_parse["relationships"] vs model join graph
# Flag any relationship not present in the existing model (name or endpoint differs)
```

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

Place `guid` at the document root (not nested under `model:`) and import with
`--no-create-new` to update the existing model in place. The import will fail if
the GUID is not found — surface the error clearly and stop.

```python
top_level = {"guid": model_guid, "model": model_dict}
model_tml_str = yaml.dump(top_level, default_flow_style=False, allow_unicode=True)

result = subprocess.run(
    ["bash", "-c",
     f"source ~/.zshenv && ts tml import --policy ALL_OR_NONE "
     f"--no-create-new --profile '{profile_name}'"],
    input=json.dumps([model_tml_str]),
    capture_output=True, text=True,
)
```

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

**Converting multiple views from the same schema?** Get all DDLs in one query:
```sql
SELECT view_name,
       GET_DDL('SEMANTIC_VIEW', '{database}.{schema}.' || view_name) AS ddl
FROM {database}.information_schema.views
WHERE table_schema = '{schema}'
  AND table_type = 'SEMANTIC VIEW';   -- Snowflake filter for semantic views only
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

**4. Dimensions / time_dimensions / facts** — union across all tables, deduplicated
by (table_name, column_name).

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

Read and parse the DDL returned in Step 3. The DDL is a SQL `CREATE OR REPLACE
SEMANTIC VIEW` statement. See [../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md)
for the full format — it is NOT the hypothetical nested format; the real format has flat
`dimensions` and `metrics` sections at the view level.

Extract the following:

1. **View identity:** database, schema, view name.
   - Top-level `comment='...'` (after the metrics block, before `with extension`) → Model description.
2. **Tables block:** for each table entry, record:
   - Fully-qualified table reference (`DB.SCHEMA.TABLE`) — this is the Snowflake view/table
   - Table alias (explicit `ALIAS as DB.SCHEMA.TABLE`, or defaults to last segment of the name)
   - Primary key column(s) (if present — marks this as a join target)
   - **Table-level `comment='...'`** if present → maps to TS Table TML `table.description`.
3. **Relationships block:** for each relationship (`REL_NAME as FROM(COL) references TO(COL)`), record:
   - Relationship name, from table alias, from column, to table alias, to column
4. **Dimensions block** (flat, all tables): for each entry (`TABLE.COL as view_alias.NAME [with synonyms=(...)] [comment='...']`), record:
   - Source: TABLE alias + VIEW column name (column in the Snowflake view layer)
   - Semantic alias: `view_alias.NAME`
   - **Synonyms** list from `with synonyms=(...)` — first → display name, rest → `properties.synonyms`
   - **Description** from `comment='...'` → column `description`
   - If no synonyms: title-cased NAME → display name
5. **Metrics block** (flat): for each entry, record:
   - Simple: `TABLE.COL as AGG(view_alias.NAME)` — extract source column + aggregation
   - **Semi-additive**: `TABLE.COL non additive by (DATE.col asc|desc nulls last) as SUM(view_alias.col)`
     — translates to a `last_value` (asc) or `first_value` (desc) formula. See the
     formula reference's Semi-additive section for the full DDL → TS mapping.
   - **Window function**: `... OVER (PARTITION BY ...)` — translates to `group_sum`,
     `safe_divide(..., group_sum(...))` for contribution ratios, etc.
   - **Synonyms** + **description** mapping: same rule as dimensions.
6. **Extension JSON** (`with extension (CA='...')`): parse for column type confirmation
   (dimensions / time_dimensions / metrics per table). Do not map to ThoughtSpot.

Build an internal map:
- `tables`: alias → fully-qualified ref, primary key, **table description**
- `relationships`: list of (name, from_alias, from_col, to_alias, to_col)
- `columns` (flat): all dimensions and metrics, keyed by (table_alias, view_col), with
  display name, synonyms[], and description fields populated.
- `model_description`: from the top-level `comment='...'` clause

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

**Search ThoughtSpot for all table objects:**

```bash
source ~/.zshenv && ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile {profile}
```

Filter the JSON to match each semantic view base table by database + schema + table name
(`metadata_header.database_stripes`, `metadata_header.schema_stripes`, `metadata_name`).
Build a map: `physical_table_name → {metadata_id, metadata_name}`.

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

### Step 6B: Create ThoughtSpot Table objects for views (Scenario B)

**Do all Snowflake introspection in a batch query — not per-table calls.**

1. **Batch: get all column names and types for the entire schema in one query:**
   ```sql
   SELECT table_name, column_name, data_type
   FROM {database}.information_schema.columns
   WHERE table_schema = '{SCHEMA}'
   ORDER BY table_name, ordinal_position;
   ```
   This returns every column for every table/view in the schema in one round-trip.

2. Ask the user to confirm which ThoughtSpot connection to use (or auto-select if
   only one matches the semantic view's database). Use the connection **name** directly
   in table TML — no GUID lookup is needed or possible from available procedures.

   `ts connections list` auto-paginates and returns all connections. Filter the
   output by the user's connection name to confirm it exists.

   Display matching connections and ask the user to confirm. Once confirmed, use the
   exact `name` value from the API response.

3. Create ThoughtSpot Table objects for all tables in one command:
   ```bash
   cat tables-spec.json | ts tables create --profile {profile}
   ```
   Where `tables-spec.json` is a JSON array built from the column data above.
   See `ts tables create --help` for the spec format. This command handles
   JDBC retry and GUID resolution automatically, and outputs `{name: guid}`.

4. Inline joins will be defined directly in the model TML (no `referencing_join`).

---

### Step 7: Find join names (Scenario A only)

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

### Step 8: Build the model TML

Construct the model TML as a YAML string. Use the templates in
[../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md](../../shared/mappings/ts-snowflake/ts-from-snowflake-rules.md).

**Model name:** `TEST_SV_{view_name_title_case}` — prefix indicates this is a
test/converted model. Ask the user if they want a different name.

**Identify the fact table** (the table that is never on the "TO" side of any relationship)
— it gets no `referencing_join` and no `joins[]`.

**Critical `id` rules (applies to all scenarios):**
- **`id` must equal `name` exactly** (same case, same characters). ThoughtSpot resolves
  `with` and `on` join references against the table's actual `name` — if `id` differs
  in case (e.g. `id: dm_order` with `name: DM_ORDER`), joins fail with
  "{table_name} does not exist in schema". Use the exact ThoughtSpot table object name
  for both `id` and `name` (often uppercase for newly-created tables).
- `id` values must be **unique** across all `model_tables` entries
- `name` values must also be **unique** — ThoughtSpot rejects models where two tables
  share the same `name` value ("Multiple tables have same alias")
- If two semantic view tables map to the same ThoughtSpot table (same GUID), include
  it only ONCE and use ONE `id`/`name`

**Model TML skeleton (Scenario A — pre-defined joins exist in table TML):**

```yaml
model:
  name: "TEST_SV_{view_name}"
  model_tables:
  - id: FACT_TABLE          # MUST equal name exactly (copy verbatim — often uppercase)
    name: FACT_TABLE        # exact ThoughtSpot table object name — FK side, joins go here
    fqn: "{fact_guid}"      # GUID from Step 6A
    joins:
    - with: DIM_TABLE       # must equal the target entry's name exactly
      referencing_join: "{join_name}"   # from Step 7
  - id: DIM_TABLE           # MUST equal name exactly — PK side, no joins
    name: DIM_TABLE         # exact ThoughtSpot table object name
    fqn: "{dim_guid}"       # GUID from Step 6A
  columns:
  - name: "{display_name}"
    column_id: fact_table::{col_name}  # col_name from ThoughtSpot Table TML
    properties:
      column_type: ATTRIBUTE
  - name: "{display_name}"
    column_id: fact_table::{col_name}
    properties:
      column_type: MEASURE
      aggregation: SUM
  formulas:
  - name: "{display_name}"
    expr: "{thoughtspot_formula}"
    properties:
      column_type: MEASURE
```

**Model TML skeleton (Scenario B / Hybrid — inline joins, or no pre-defined table joins):**

Use this when ThoughtSpot Table objects have no `joins_with` entries, or when creating
new Table objects for views. Inline joins live on the **source (FROM) table** entry.

```yaml
model:
  name: "TEST_SV_{view_name}"
  model_tables:
  - id: FROM_TABLE          # MUST equal name exactly (copy verbatim from import response)
    name: FROM_TABLE        # exact ThoughtSpot table object name — never lowercase or transform
    fqn: "{from_guid}"
    joins:
    - name: "{join_name}"
      with: TO_TABLE        # REQUIRED — must equal `id` (= `name`) of the target entry exactly
      on: "[FROM_TABLE::{fk_col}] = [TO_TABLE::{pk_col}]"  # uses id values (= name values)
      type: INNER
      cardinality: MANY_TO_ONE
  - id: TO_TABLE            # matches `with` value above — same case
    name: TO_TABLE
    fqn: "{to_guid}"
  columns:
  # ... same pattern as Scenario A ...
```

**Column entries — display name, synonyms, description:**

For each dimension or metric in the semantic view, populate metadata as follows:

| SV DDL field | TS column field |
|---|---|
| `with synonyms=('Display Name','Alt 1','Alt 2',...)` (1st value) | `name` |
| `with synonyms=(...)` (remaining values) | `properties.synonyms` (with `properties.synonym_type: USER_DEFINED`) |
| `comment='...'` | `description` (at column root) |
| (no synonyms clause) | `name` = title-cased SV alias (LHS) |

**Critical placement:** synonyms live under `properties.synonyms`, NOT at column root.
A top-level `synonyms:` field is silently dropped on import. Always pair with
`properties.synonym_type: USER_DEFINED`.

For each dimension:
- `column_id`: `{id}::{col_name}` — where `id` is the model_tables `id` for that
  table, and `col_name` is from the ThoughtSpot Table TML
- `properties.column_type: ATTRIBUTE`

For each simple metric (`AGG(view_alias.metric_name)`):
- `column_id`: `{id}::{col_name}`
- `properties.column_type: MEASURE`
- `aggregation`: mapped from the SQL aggregate function (see ts-from-snowflake-rules.md)

For each complex metric (formula expression):
- See Step 9 for translation. Results go into `formulas[]`.
- **Never add `aggregation:` to a `formulas[]` entry** — formulas are self-contained
  via their `expr`. ThoughtSpot rejects TML with `FORMULA is not a valid aggregation type`.

**Every formula must have a `columns[]` entry.** Add a `columns[]` entry with
`formula_id:` for every entry in `formulas[]`:

```yaml
formulas:
- id: formula_Inventory Balance   # id: "formula_" + name (spaces preserved)
  name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
  properties:
    column_type: MEASURE

columns:
# ... physical columns ...
- name: "Inventory Balance"
  formula_id: formula_Inventory Balance   # must match the formula's `id` exactly
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX   # recommended for computed numeric measures
```

`aggregation:` on a `columns[]` formula entry is allowed (unlike in `formulas[]` entries
where it causes an import error).

---

### Step 9: Translate SQL expressions → ThoughtSpot formulas

> **MANDATORY — read the reference before assessing any expression:**
> Open [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
> and use its **Reverse translation** sections for each SQL pattern. Do **not** classify
> an expression as untranslatable based on SQL syntax recognition alone. Patterns that
> appear Snowflake-specific have documented ThoughtSpot equivalents — for example:
>
> | Looks untranslatable | Actually translatable as |
> |---|---|
> | `SUM(col)` + `NON ADDITIVE BY (date ASC NULLS LAST)` | `last_value ( sum ( [col] ) , query_groups ( ) , { [date_col] } )` |
> | `SUM(m) OVER (PARTITION BY dim1, dim2)` | `group_sum ( measure, dim1, dim2 )` |
> | `SUM(m) OVER (PARTITION BY EXCLUDING dim1)` | `group_aggregate ( sum(m), query_groups()-{dim1}, query_filters() )` |
> | `DIV0(tbl.metric, SUM(tbl.metric) OVER (PARTITION BY dim.COL))` | `safe_divide ( sum(m), group_sum(m, dim) )` — contribution ratio |
> | `SUM(m) OVER (PARTITION BY EXCLUDING dim ORDER BY dim ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` | `cumulative_sum ( measure, dim )` |
>
> Consult the reference. Never reason from first principles about SQL window functions.

For each metric whose `EXPR` is not a simple `AGG(table.col)`:

1. Apply the SQL → ThoughtSpot formula translation rules in
   [../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
   (bidirectional reference — use the **Snowflake → ThoughtSpot** direction).
2. Replace column references: `table.COLUMN` → `[TABLE_ALIAS::COLUMN]`
3. If the expression translates successfully → add a `formulas[]` entry.
4. If the expression is confirmed untranslatable after consulting the reference →
   omit the column and log it in the Formula Translation Log (for the summary report in Step 12).

**Column references in translated formulas:**

Use the `name:` from the corresponding `model_tables[]` entry (which matches the semantic
view table alias). Column name is the column name from the ThoughtSpot Table TML.

Example:
- Semantic view EXPR: `SUM(DM_ORDERDETAILS.UNIT_PRICE * DM_ORDERDETAILS.QUANTITY)`
- ThoughtSpot formula: `sum ( [DM_ORDERDETAILS::UNIT_PRICE] * [DM_ORDERDETAILS::QUANTITY] )`
- Add as `formulas[]` entry with `column_type: MEASURE`

**`last_value` / curly brace formulas — YAML block scalar required:**

When the translated formula contains `{ [col] }` (curly braces), use a `>-` block scalar
for the `expr` field. Inline YAML string assignment fails because `{` is a flow mapping
start character:

```yaml
formulas:
- name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )
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

### Step 9.5: Spotter enablement

Before assembling the final TML, ask whether Spotter (AI search) should be enabled
for this model. Default is **yes** — Spotter is the primary natural-language
interface for Models, and a converted SV usually exists to be queried this way.

```
Enable Spotter (AI search) for this model? [Y / n] (default: Y)
```

Apply the answer to the model TML's properties block:

```yaml
model:
  name: TEST_SV_{view_name}
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
Model to import: TEST_SV_{view_name}
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
  ⚠ {name}: OMITTED — {reason}

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
- Any new Table TMLs created in Step 6B (Scenario B): `{table_name}.table.tml`

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

### Step 11: Import the model

**IMPORTANT — Updating vs creating:** Without a `guid` field in the TML, ThoughtSpot
always creates a **new** object, even if a model with the same name already exists.
To update an existing model in-place, add `guid` at the **document root** — as a
top-level key alongside `model:`, NOT nested inside `model:`:

```python
# CORRECT — guid at document root
top_level = {"guid": "{existing_model_guid}", "model": model_dict}

# WRONG — guid nested under model (silently ignored by ThoughtSpot)
# model_dict["guid"] = "..."   ← do NOT do this
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
| `referencing_join not found` | Join name is wrong or join doesn't exist at table level | Export table TML again and verify join name |
| `column_id not found` | Column name is wrong — left-hand side of semantic view dimension used instead of ThoughtSpot Table TML column name | Check Table TML for the correct column name |
| `Compulsory Field … joins(N)->with is not populated` | Missing `with` field on an inline join | Add `with: {target_id}` to every inline join entry |
| `{table_name} does not exist in schema` (on `with` field) | `with` value is wrong case or doesn't match any `id` | Ensure `with` matches the target's `id` exactly — same case as `name` |
| `Invalid srcTable or destTable in join expression` | `on` clause references a table name that doesn't match any `id` in model_tables | Check that both `[table1::col]` refs in `on` use `id` values, not Snowflake table names |
| `Multiple tables have same alias {name}` | Two model_tables entries have the same `name` value | Deduplicate — if two aliases map to the same Snowflake object, keep only one entry |
| `fqn resolution failed` | GUID is stale or from a different ThoughtSpot instance | Re-run Step 6A to get fresh GUIDs |
| `formula syntax error` | ThoughtSpot formula has invalid syntax | Fix the formula expression |
| YAML mapping error on formula with `{` | `last_value` or similar formula with `{ [col] }` emitted as inline YAML string | Use `>-` block scalar for `expr` — see Step 9 for pattern |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars from all string values before serialising |

---

### Step 11b: Verify Import

After a successful import response, confirm the model was indexed and has the expected
shape — not just that the API returned 200.

**1. Search for the model by GUID:**

```bash
source ~/.zshenv && ts metadata search --subtype WORKSHEET --name "%TEST_SV_{view_name}%" --profile {profile}
```

The GUID returned by the import response must appear in the results. If it is absent,
the import succeeded at the API level but indexing is delayed — wait 5 seconds and
retry once.

**2. Export the imported model and count columns:**

```bash
source ~/.zshenv && ts tml export {created_guid} --fqn --profile {profile}
```

Parse the returned TML and count `model.columns[]` entries. This count must be ≥ the
number of translatable fields from the semantic view (i.e. total dimensions + metrics,
minus any omitted from the untranslatable list in Step 9).

If the column count is lower than expected: compare the exported TML against the TML
sent in Step 11 to identify which columns ThoughtSpot silently dropped, and investigate.

**3. Report the model URL:**

```
Model imported successfully.

  Name:    TEST_SV_{view_name}
  GUID:    {created_guid}
  URL:     {base_url}/#/model/{created_guid}

Open the URL in a browser to verify the model appears in the ThoughtSpot Data panel.
```

---

### Step 12: Produce summary report

After a successful import, output:

```
## Model Import Complete

**Model:** TEST_SV_{view_name}
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
| {name} | `{sql}` | ⚠ Omitted | {reason} |

### Not Mapped
- Extension JSON (Cortex Analyst context): not translated to ThoughtSpot
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
| 1.4.1 | 2026-05-11 | Add `source ~/.zshenv &&` prefix to all bash blocks and convert subprocess.run calls from `["ts", ...]` to `["bash", "-c", "source ~/.zshenv && ts ..."]` for consistent env var loading |
| 1.4.0 | 2026-05-05 | Add Mode C (update existing): Steps C1–C6. Identifies a changed SV and an existing TS Model, diffs columns/descriptions/synonyms/expressions, applies per-column reviewed changes with `--no-create-new`, and surfaces /ts-object-model-coach handoff. `ai_context` and Instructions are never touched. Step 1.5 menu updated to A/B/C. |
| 1.3.0 | 2026-04-28 | Add Step 9.5 — confirm Spotter (AI search) enablement before import. Default Y; preserves existing setting on in-place updates. |
| 1.2.0 | 2026-04-28 | Map SV synonyms/descriptions to TS Model + Table TMLs. Add Step 6D for table-description updates. Document `non additive by ... desc` → `first_value`. Fix synonyms placement (`properties.synonyms` not column root). |
| 1.1.0 | 2026-04-24 | Add Step 0 session plan with confirmation gate |
| 1.0.0 | 2026-04-24 | Initial versioned release |
