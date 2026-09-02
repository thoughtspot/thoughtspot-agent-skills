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

Ask one question at a time for **dependent** decisions (each answer narrows the next —
target database, then schema, then table). Batch **independent** questions when possible
— e.g. connection name + target database + schema can be collected together (BL-074).

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
| [references/concept-mapping.md](references/concept-mapping.md) | SV DDL construct → ThoughtSpot Model mapping table |
| [references/step-3.5-merge-dedup.md](references/step-3.5-merge-dedup.md) | Step 3.5 merge-mode dedup rules and merge-summary template |
| [references/step-6-table-registration.md](references/step-6-table-registration.md) | Step 6A table-plan template; Step 6B introspect/connection/create command sequence |
| [references/step-7-join-discovery.md](references/step-7-join-discovery.md) | Step 7 joinless-SV (GAP-03) join-discovery options |
| [references/step-7.5-roleplay-aliases.md](references/step-7.5-roleplay-aliases.md) | Step 7.5 role-played dimension aliases — I14, the alias shape, column trim |
| [references/step-8.5-display-name-collisions.md](references/step-8.5-display-name-collisions.md) | Step 8.5 flat-namespace collisions — characterise, choose, disambiguate |
| [references/step-c-update-mode.md](references/step-c-update-mode.md) | Mode C diff-review, change-action mapping, and handoff templates (C4–C6) |
| [references/step-12-report-formats.md](references/step-12-report-formats.md) | Step 10/12/12.5 console + TML report templates |
| [references/open-items.md](references/open-items.md) | Known gaps and deferred capabilities for this skill |

---

## Concept Mapping

Full DDL-construct → ThoughtSpot-Model mapping table — tables, dimensions, metrics,
non-additive/window-function formulas, relationships, synonyms, comments, and the
unmapped `extension` clause: [references/concept-mapping.md](references/concept-mapping.md).

**Key structural rules:**
- `column_id` must use the **column name from the ThoughtSpot Table TML**. Export
  Table TMLs to confirm — do not assume they match the semantic view left-hand side.
- Simple metrics (`AGG(view.col)` — one column, one aggregate) → `MEASURE` column.
  Complex expressions → `formulas[]` entry.
- **Unqualified derived metrics** (`NAME as m1 / m2`, no table prefix on the left) →
  `formulas[]` MEASURE. This is the only SV construct that can combine metrics from two
  *unrelated* facts, so cross-fact ratios — attainment, period-over-period growth — arrive
  this way.
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
- `ts snowflake introspect` needs the Snowflake connector in the `ts` environment. If it
  reports `snowflake-connector-python is required`, install it into the tool env:
  `uv tool install thoughtspot-cli --with snowflake-connector-python`

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
  7.5. Role-played dimension aliases (if any) ............ you choose
  8.   Assemble tables map ............................... auto
  8.5. Display-name collisions (if any) .................. you choose
  9.   Translate SQL expressions → ThoughtSpot formulas ... auto (ts snowflake translate-formulas)
  9.5. Confirm Spotter enablement (default: enabled) ...... you choose
 10.   Review checkpoint — inspect TML before import ...... you confirm
 11.   Import the model into ThoughtSpot .................. auto (ts snowflake build-model)
 11c.  Reconcile the Model against the SV ................. auto
 12.   Verify import and produce summary report ........... auto
 12.5. Import verified queries as NLS Feedback ............ auto (when SV has verified queries)

File-only mode: at Step 10, choose FILE to write TML files for manual import.

Confirmation required: Steps 1.5, 5, 7.5 + 8.5 (if applicable), 9.5, 10 (Modes A/B); Steps 1.5, C4 (Mode C)
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
ts snowflake parse-sv sv_ddl.sql --output parsed.json
ts snowflake translate-formulas --input parsed.json --output translated.json
```

**ThoughtSpot side** — export the existing model:
```bash
ts tml export {model_guid} --profile {profile} --fqn --associated --parse
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
type `done` before proceeding. Full console templates (summary block, descriptions/
synonyms/expressions tables, removed-columns warning):
[references/step-c-update-mode.md](references/step-c-update-mode.md) "Step C4 templates".

Require the user to type `done` after reviewing before proceeding.

---

### Step C5: Build the updated Model TML and import

Deep-copy the existing Model TML. Apply only the confirmed changes — full change-type
→ action mapping table (incl. `ai_context`/Instructions never-touch rules):
[references/step-c-update-mode.md](references/step-c-update-mode.md) "Step C5 change-action mapping".

Build `tables.json` from the existing model's table GUIDs (same format as Step 8), then
import with `build-model --existing-guid`:

```bash
ts snowflake build-model \
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

After a successful import, always surface the coaching-handoff message (`/ts-object-model-coach`
and `/ts-dependency-manager` pointers). Exact template:
[references/step-c-update-mode.md](references/step-c-update-mode.md) "Step C6 handoff message".

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
will treat as if it came from one Semantic View. Full dedup rule set (tables,
relationships, metrics, dimensions/facts, fact re-detection, merge-summary template):
[references/step-3.5-merge-dedup.md](references/step-3.5-merge-dedup.md).

If there are unresolved conflicts, require all to be resolved before accepting the
merge summary's `YES`. After confirmation, continue with Step 4 using the merged result.

---

### Step 4: Parse the DDL

Write the DDL from Step 3 to a file and parse it with `ts snowflake parse-sv`:

```bash
printf '%s' "$DDL" > sv_ddl.sql
ts snowflake parse-sv sv_ddl.sql --output parsed.json
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
ts metadata search --subtype ONE_TO_ONE_LOGICAL --name "%{table_name}%" --profile {profile}
```

- **C (within a connection)** → **first identify the connection using the
  N (name it) / F (filter by substring) / L (list all) prompt in Step 6B — present that
  prompt and let the user choose; do NOT run `ts connections list` and dump every
  connection by default.**
  Then **pass `--connection "{connection_name}"` to `ts metadata search`** rather than
  hand-filtering: the CLI scopes it in `filter_by_connection`
  (`commands/metadata.py:35`), which **casefolds** both sides. This step previously said
  to keep results whose `dataSourceName` **equals** the connection name — an executor
  following that literally drops rows the CLI keeps (`APJ_SNOW` vs `apj_snow`).
  Corrected 2026-08-26, finding 11.1. Fastest, and unambiguous when the same table name
  exists on several connections.
- **I (entire instance)** → run the name search above with no connection filter.

Filter the JSON to match each semantic view base table by table name (`metadata_name`).
**Connection scoping is already done** by the `--connection` flag above — do NOT re-filter on
`metadata_header.dataSourceName` here: the flag casefolds and a hand comparison does not, so
re-applying it drops every row the flag kept (finding 11.1, 2026-08-26). Use
`metadata_header.database_stripes` / `metadata_header.schema_stripes` to disambiguate
same-named tables. Build a map: `physical_table_name → {metadata_id, metadata_name}`.

> Only fall back to `--all` (fetch every table) when no usable name pattern can be
> formed (e.g. the name is too generic). Tell the user that cost before running it.

**Export TMLs for all found tables in one call to verify columns:**

```bash
ts tml export {guid1} {guid2} ... --profile {profile} --parse
```

`--parse` returns structured JSON — access columns via `item["tml"]["table"]["columns"]`
directly. Parse `table.columns[].name` from each returned item. Build a column map per table:
`table_name → [col_name, ...]`. Compare against the columns referenced in
the semantic view dimensions and metrics to identify any column gaps.

> The `column_id` in the model TML must use the column names from the ThoughtSpot
> Table TML — export the TMLs to confirm them.

**Confirm the plan before making any changes:**

Show the user a full status table and wait for confirmation. Exact template:
[references/step-6-table-registration.md](references/step-6-table-registration.md)
"Step 6A — Table Plan confirmation template".

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
ts connections list --profile {profile}
```
**Note:** `ts connections list` auto-paginates and returns all connections.

Add the missing columns to the connection, then re-import the updated Table TML
for each affected table (batch all imports in one call):
```bash
ts tml import --policy ALL_OR_NONE --profile {profile}
```

After import, re-export the updated TMLs to refresh the column map before Step 8.

---

### Step 6B: Create ThoughtSpot Table objects for views (Scenario B) — also the connection picker for the Step 6A connection-scoped search

**Use `ts snowflake introspect` to query Snowflake and build the table spec**, choose
or create the ThoughtSpot connection, then create the Table objects in one batch. The
full command sequence — the `introspect` call and its manual-query fallback, the E/C
connection-selection flow, the `ts connections create` invocation with role/key
requirements, the required credential-handling guardrail (private key by file path
only, never pasted into chat), and the batch `ts tables create` call — is in
[references/step-6-table-registration.md](references/step-6-table-registration.md) "Step 6B — command sequence".

> **Table objects are created with `ts tables create`. Do NOT use
> `ts connections add-tables`.** That command rewrites the *connection's* registered-object
> list, which is a different operation and is not what this step needs — a connection that
> can already reach the database needs no change. Run against a shared connection it can
> fail with a 500 (`NullPointerException` in `validateConfigSourceConnectionId`) and, if it
> succeeded, would risk the connection's `authenticationType`.
>
> The tell: `introspect` writes `tables-spec.json` shaped to pipe into `ts tables create`
> **unmodified**. If a command rejects those keys (it wants `table` where the spec has
> `db_table`), that is the signal you have the wrong command — do not transform the keys to
> force it through.

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

Full detail for each option — the auto-discovery SQL, confirmation console templates,
the column-overlap-analysis queries and evidence display, the manual-join prompt, and
the separate-model-per-table fallback — is in
[references/step-7-join-discovery.md](references/step-7-join-discovery.md).

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

### Step 7.5: Role-played dimension aliases (I14)

A Semantic View may join one table to the same target several times (a date
dimension on order/ship/booked date; an employee dimension on several account-team
roles). That is legal in an SV, which scopes names per table, and **fatal in
ThoughtSpot**, which has one flat join graph: the join path is ambiguous and the
Model will not load. `ts tml lint` invariant I14 rejects it, so `build-model`
refuses rather than emitting an unloadable Model.

Detect it from `parsed.json` before building:

```python
from collections import Counter
pairs = Counter((r["from_table"], r["to_table"]) for r in parsed["relationships"])
roleplay = {k: v for k, v in pairs.items() if v > 1}
```

If `roleplay` is non-empty, follow
[references/step-7.5-roleplay-aliases.md](references/step-7.5-roleplay-aliases.md) —
it covers picking the primary role, synthesizing the alias entries, the column
trim (**ask the user**; the naive full-copy adds hundreds of near-duplicate
columns and degrades NL search), and the `tables.json` entries the aliases need.

Otherwise skip to Step 8.

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

### Step 8.5: Display-name collisions

A Semantic View scopes construct names per table; a ThoughtSpot Model has one flat
column namespace. On a wide multi-fact SV the two collide by construction and
`build-model` refuses with `duplicate display title(s): ...`. Detect it before
building:

```python
import re
from collections import defaultdict
def title(n): return " ".join(w.capitalize() for w in re.split(r"[_\s]+", n))
groups = defaultdict(list)
for block in ("dimensions", "facts", "metrics"):
    for e in parsed[block]:
        groups[title(e["source_column"])].append(e)
dups = {k: v for k, v in groups.items() if len(v) > 1}
```

If `dups` is non-empty, follow
[references/step-8.5-display-name-collisions.md](references/step-8.5-display-name-collisions.md) —
characterise the collisions, **ask the user** which resolution they want (it changes
the model's whole search surface), then apply it to the parsed doc.

Otherwise skip to Step 9.

---

### Step 9: Translate SQL expressions → ThoughtSpot formulas

Run the deterministic formula translator:

```bash
ts snowflake translate-formulas --input parsed.json --output translated.json
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

**Surface `annotations[]` too** — each translated entry may carry review markers (🔄
double aggregation, ⚑ ambiguous reference or skipped double aggregation). Carry them into
the Step 12 Review Flags section; they are the only signal for translations that succeeded
but need a human check.

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
`translated.json`, and `tables.json` — tables with fact/join annotations, columns by
type, the formula translation log, filter labels, verified queries, and the Spotter
setting. Exact console template:
[references/step-12-report-formats.md](references/step-12-report-formats.md) "Step 10
— Review checkpoint console template".

Wait for user confirmation before proceeding.

If the user selects **file**, skip to [Step 10-FILE](#step-10-file-output-tml-files-file-only-mode).

---

### Step 10-FILE: Output TML files (file-only mode)

This path is used when the user selected **file** at the Step 10 checkpoint, explicitly
said "file only", or has no ThoughtSpot `DATAMANAGEMENT` access.

Run `ts snowflake build-model` without `--profile` — it generates the TML files to
`--output-dir` without importing:

```bash
ts snowflake build-model \
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
for the invariant list (I1/I2/I4/I5/I8/I12/I13) and import-policy rules. No separate lint
step is needed.

---

### Step 11: Import the model

Re-run `ts snowflake build-model` with `--profile` to import:

```bash
ts snowflake build-model \
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

### Step 11c: Reconcile the Model against the Semantic View

**A successful import is not a correct conversion.** Step 11b confirms the object exists
and re-exports; it does not confirm a single number. Query the Model and compare it to the
SV — this is the only check that catches a join wired to the wrong key, a role-played alias
that resolved to the wrong node, or rows lost to an unmatched join.

**Check 1 — grand totals, every additive measure.** For each simple `SUM` metric, compare
the Model's grand total to the SV's:

```bash
# ThoughtSpot
ts agentql fetch-data 'SELECT SUM("{measure}") FROM "{model_name}" AS "t1"' \
  -m {model_guid} --profile {profile}
```
```sql
-- Snowflake, same measure
SELECT * FROM SEMANTIC_VIEW({sv_fqn} METRICS {table}.{metric});
```

They must be **identical**. A difference is a wiring fault, not a rounding one.

**Check 2 — one grouped query per fact.** Grand totals can agree while a join is wrong, so
group by a dimension each fact reaches and compare a few rows. Pick a dimension in the
middle of the data, not the first or last period.

**Check 3 — aliased facts must reconcile to their base.** If the SV role-plays a table
(the same physical table under several aliases), each alias's additive measure sums to the
**same grand total** as the base measure — it is the same rows read through a different
key. A mismatch means rows fell out of the aliased join.

Report each comparison in Step 12 with both numbers. If any fails, do not describe the
conversion as verified — say which check failed and what the two numbers were.

---

### Step 12: Produce summary report

After a successful import, output the summary report — model header, columns
imported, formula translation log, **review flags**, not-mapped items, facts mapped,
identifier resolution summary, filter labels, and verified queries. Exact console template:
[references/step-12-report-formats.md](references/step-12-report-formats.md) "Step 12
— Summary report console template".

**Surface every `translated[].annotations` entry** from `translated.json` in the Review
Flags section — the 🔄 double-aggregation markers and the ⚑ ambiguity/skip warnings. These
are conversions the translator completed but **cannot verify**: a double aggregation whose
grouping key needs a human check, or a renamed construct referenced by a name that may also
be a physical column. Nothing downstream re-raises them, so dropping them here is the
difference between a flagged risk and a silent one.

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

**For each verified query with translatable SQL:** build an NLS Feedback TML entry.
Exact template: [references/step-12-report-formats.md](references/step-12-report-formats.md)
"Step 12.5 — NLS Feedback TML template".

Import with: `ts tml import --policy ALL_OR_NONE --profile {profile}`

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
| 1.22.0 | 2026-09-02 | **BL-232 — column descriptions reached the TML at the wrong nesting level and were silently discarded on import (ts-cli v0.136.0).** `sv_build_model.py` wrote a Semantic View column's `comment:` to `columns[].properties.description`, but ThoughtSpot expects `description` as a **sibling of `name`** and a Model import **silently ignores unknown keys inside `properties`** — so the TML linted clean, imported with `status_code OK`, and every column description was lost. Same root cause and fix as the Databricks converter, where it was live-caught on 2026-09-02 (19 of 19 descriptions dropped, then all 19 restored after relocation). Synonyms were unaffected. Worked example `ts-from-snowflake-identifier-resolution.md` corrected. |
| 1.21.2 | 2026-08-26 | Use `ts metadata search --connection` instead of hand-filtering `dataSourceName`; the old instruction said **equals** where the CLI casefolds (finding 11.1). |
| 1.21.1 | 2026-08-26 | Carry BL-074's prompt-batching rule — ask one question at a time for **dependent** decisions, batch **independent** ones. The rule reached 13 skills but omitted the four conversion skills, which are the most interactive in the repo by ask-count (finding 14.6). A `check_patterns` rule now enforces it above a question-count threshold. |
| 1.21.0 | 2026-08-06 | **Two translator gaps closed, derived metrics supported, and two workflow fixes — all from converting a live SV end to end into a ThoughtSpot Model (ts-cli v0.130.0).** **BL-213:** an unqualified derived metric (`NAME as m1 / m2`, no table prefix) is valid SV grammar and the **only** way to express a ratio spanning two *unrelated* facts — a qualified metric may reference only metrics on directly related entities (`010211`) — so attainment and period-over-period growth arrive exclusively this way. All four on the fixture had landed in `unsupported[]` as "could not parse metric entry" and were silently absent from the Model. Now parsed, translated to a MEASURE formula, and emitted by `build-model`. The resolver needed its own path: the generic metric branch emits `[formula_<id>]`, which **dangles** against a simple-`AGG(col)` metric (emitted as a plain column) — the BL-178 shape I13 rejects, previously unreachable because Snowflake refuses the qualified equivalent. **BL-212:** the translator rejected `DATEDIFF('day', …)` (Snowflake accepts the unit bare *or* quoted) and any double-quoted identifier (`dm_date_dim."DATE"` raised "unrecognized character '.'"), each silently costing a construct — 3 of 44 on the fixture, now 44/44. **New Step 11c — reconcile the Model against the SV:** a successful import is not a correct conversion; Step 11b confirms the object exists but not one number. Three checks (grand totals per additive measure, one grouped query per fact, and aliased facts reconciling to their base) — the only thing that catches a join wired to the wrong key or a role-played alias resolved to the wrong node. **Step 6B** now warns off `ts connections add-tables` (it rewrites the connection's registered-object list, is not what the step needs, and 500s on a shared connection) and names the tell: `tables-spec.json` is shaped to pipe into `ts tables create` unmodified. **Prerequisites** note the `snowflake-connector-python` extra `introspect` requires. |
| 1.20.0 | 2026-07-31 | **Two new steps and three parser/translator fixes, from converting a real 1,100-line customer Semantic View (ts-cli v0.128.0).** New **Step 7.5 — role-played dimension aliases**: an SV scopes names per table and freely joins one fact to one date dimension eight times; ThoughtSpot has one flat join graph, so that is ambiguous and **the Model will not load**. New lint invariant **I14** (BL-202) rejects any duplicate `(from_node, joins[].with)` pair, so `build-model` now refuses rather than emitting an unloadable Model — it previously emitted 21 such joins across 7 pairs with `lint_findings: []` and I1–I13 all clean. The reference covers picking the primary role (one must keep the base node or it becomes a disconnected table), synthesizing the alias entries, the `tables.json` entries they need, and the **column trim** — which is a user decision, because the naive full copy adds 784 near-duplicate columns to a 1,015-column model and degrades NL search more than the ambiguity it fixed. New **Step 8.5 — display-name collisions**: an SV's per-table name scoping collides with ThoughtSpot's flat column namespace by construction on a wide multi-fact SV (129 colliding titles over 322 of 1,010 columns on the fixture); the reference characterises them, offers three resolutions, and applies the qualify-and-de-index pattern. `build-model`'s error message no longer says "set distinct display_name values in the SV", which is not actionable when you do not own the SV. Parser fixes: **BL-200** the entry splitter is now quote aware, so a comma inside `comment='...'` no longer shatters the entry (15 tables had parsed as 32, with 169 fragments in `unsupported[]`); **BL-201** live `GET_DDL`'s `sample_values (...)` spelling is now matched, so the clause is no longer read as part of the expression (had skipped all 46 `is_enum` dimensions). Translator fixes: **BL-179** first-synonym promotion is now opt-in (`--promote-first-synonym`, default off) and the decision is recorded in `translated.json` for `build-model` to read — on a foreign SV it had renamed 9 constructs, destroying the logical identifier; **BL-181** facts now classify MEASURE or ATTRIBUTE from the expression instead of hardcoding ATTRIBUTE, so quantities and profit aggregate (182 of 182 facts on the fixture were previously categorical). |
| 1.19.5 | 2026-07-30 | **BL-171 — `sv_sql.py` stops emitting six non-existent string functions (ts-cli v0.126.1).** BL-170 corrected the *documentation* on 2026-07-29 and left the code: `sv_sql.py`'s `_RENAME` still translated Snowflake `TRIM`/`LTRIM`/`RTRIM`/`REPLACE`/`STARTSWITH`/`ENDSWITH` to the bare ThoughtSpot names `trim`/`ltrim`/`rtrim`/`replace`/`starts_with`/`ends_with`, **none of which exists**, so every affected metric or computed dimension failed at import with `error_code 14516`. `TRIM`/`LTRIM`/`RTRIM` now go through `_PASS_THROUGH_HINT` (the same path as `UPPER`/`LOWER`), and `REPLACE`/`STARTSWITH`/`ENDSWITH` through new composed handlers, matching `ts-snowflake-formula-translation.md`'s String Functions rows character for character. `test_sv_sql.py`'s `test_starts_with` had asserted the *wrong* expectation (`starts_with ( … )`) — corrected, and 7 new tests cover the family plus a sweep asserting no bare name is ever emitted. Coverage matrix rows 20a/20b added. **The emitted forms were live-verified on se-thoughtspot 2026-07-30** (`--policy VALIDATE_ONLY`, nothing persisted). |
| 1.19.4 | 2026-07-30 | **BL-178 — formula reference integrity restored (three defects; ts-cli v0.126.0).** Every metric-on-fact and metric-on-metric reference in the emitted Model TML matched no declared `formulas[].id` between 2026-07-22 (v1.17.0's rewire) and today, so **every measure was unimportable** while `ts tml lint`, `check_tml.py` and `build-model`'s own `lint_findings` all reported clean. Live-confirmed on se-thoughtspot 2026-07-30 as a **hard import failure** (`error_code 14516`, *Search did not find "formula_tenure_months )"*), settling the question the fidelity review left open. Three fixes: (1) the documented resolution order is restored — a **passthrough** fact (right-hand side is a bare physical column, the shape a Cortex-Analyst model emits for every field) resolves to `[TABLE::col]`, which is what `build-model` emits for it, so all 5 of 5 TPC-DS metrics now resolve; (2) `display_title` is now a single function shared by the resolver and the builder, so an emitted `[formula_X]` is by construction the id the builder mints — and metric-on-metric gained the documented `group_*` double aggregation (grouping on the parent-side PK of the connecting relationship) it never implemented; (3) `parse-sv` keys the facts/metrics maps on **declared** names rather than the first qualified token of the expression, which had been indexing a computed fact under a physical column of its own table and letting a metric resolve its inner reference to itself. **New gate:** `ts tml lint` invariant **I13** rejects any `[formula_*]` reference or `columns[].formula_id` matching no declared id (BL-183), so this class cannot recur silently. The `ts-from-snowflake-identifier-resolution.md` worked example was re-verified live and its recorded output updated; three of its four divergences from the 2026-06-13 baseline are later documented features (BL-179 first-synonym promotion, duplicate-`column_id` promotion, BL-181 fact typing), not regressions. **PR review additions:** a *renamed* passthrough (`STORE_SALES.revenue as store_sales.ss_ext_sales_price`) is now indexed under its declared name as well as its physical column — referenced by the declared name it previously emitted `column_id: STORE_SALES::revenue`, a column that does not exist and that I13 cannot see because it is a `TABLE::col` reference; every double aggregation now carries the 🔄 review marker the rules file has always mandated; a degenerate grouping (`group_count([X],[X])`, one row per group) is skipped and flagged instead of emitted; and a passthrough *metric* is a reasoned skip rather than a raw `AttributeError`. **Known limitation, newly documented:** same-table metric-on-metric (e.g. a ratio of two simple-aggregate metrics) has no resolvable reference and now fails at `build-model` via I13 rather than emitting a broken Model — coverage row 27 and **BL-194**. **Re-review addition — renamed DIMENSIONS had the same defect:** `DM_CATEGORY.CATEGORY as dm_category.CATEGORY_NAME` referenced as `PARTITION BY dm_category.category` emitted `[DM_CATEGORY::category]` where the real column is `CATEGORY_NAME`, a second worked-example regression (`ts-from-snowflake-dunder.md:207` documents the correct form). Dimensions now resolve through the same index with a three-way split — passthrough, bare-column rename, computed — and the emitted output matches that worked example character for character. Step 9 and Step 12 now **surface `translated[].annotations`** (🔄 double-aggregation markers and ⚑ ambiguity warnings) in a Review Flags section: these are conversions the translator completed but cannot verify, and nothing downstream re-raises them. A wrong `TABLE::col` reference remains invisible to `build-model`'s lint — see **BL-195**. |
| 1.19.3 | 2026-07-29 | **TPC-DS conversion-fidelity cross-validation — eleven coverage-matrix corrections (docs only; the behaviour fixes are BL-178 through BL-182).** Converting upstream's TPC-DS Cortex-Analyst model through this converter and back (`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` §3) found that only 10 of 47 constructs survive unchanged. Rows **#26/#27/#28** caveated — metric-on-fact, metric-on-metric and window-on-metric resolution all emit a `[formula_X]` reference matching no declared `formulas[].id`, so **every measure in the emitted Model TML is unresolvable** while `ts tml lint` and `check_tml.py` both report clean; a regression against a live-verified worked example, likely introduced by v1.17.0's rewire on 2026-07-22 (BL-178, three defects). Row **#14** corrected — promoting the first synonym to `column.name` is right only for a Semantic View our own to-direction authored; on a foreign SV `with synonyms=(...)` means alternate NL names and the promotion **destroys the logical identifier** (29 of 36 named constructs renamed on this fixture — BL-179). Row **#16** corrected — facts are `ATTRIBUTE`-**only** (`sv_translate.py:454-468` has no `MEASURE` branch), so every fact returns inside `dimensions()` rather than `facts()`, not "MEASURE or ATTRIBUTE" (BL-181). Row **#5** — the table-level `comment=` mapping runs in Step 6D and is **unreachable on the file-only path**, which emits no Table TML (BL-176). Row **#4** — a round trip can only restore a PK some relationship implies, so a fact table's composite PK is lost (BL-166). New row **#38** — `time_dimensions:` map to `ATTRIBUTE` and the temporal role survives only for date-typed columns (BL-166). New row **#39** — a `NULLIF(y,0)` ratio guard becomes `safe_divide`/`DIV0`, silently turning NULL into 0 with `annotations: []` (BL-180). New limitation **L10** — `||` concatenation is rejected and the whole construct dropped, though the `CONCAT` mapping it names as the fix is already bidirectional (BL-180). New limitation **L11** — `data_type` has no DDL representation. No behaviour change in this release. |
| 1.19.2 | 2026-07-29 | **BL-170 — six string functions and the `in` delimiter corrected (docs only; CLI fix is BL-171).** Live verification on se-thoughtspot 2026-07-29 proved `trim`, `ltrim`, `rtrim`, `replace`, `starts_with` and `ends_with` are **all** absent from the ThoughtSpot formula parser. `ts-snowflake-formula-translation.md`'s String Functions table now maps `TRIM`/`LTRIM`/`RTRIM`/`REPLACE` to `sql_string_op` pass-throughs and `STARTSWITH`/`ENDSWITH` to native compositions; the `IN` / `NOT IN` rows were also corrected from the rejected `in ( 'a' , 'b' )` to `in { 'a' , 'b' }` (curly braces, requiring `>-` YAML) and `not ( [x] in { } )` — there is no `not in` keyword. **Caveat: `ts_cli/sv_sql.py` still emits the bare names, so affected formulas fail at import until BL-171 lands.** |
| 1.19.1 | 2026-07-28 | Extract reference-heavy detail into references/ step files (BL-128) — no logic change; SKILL.md context cost ~15.0k → ~11.5k est. tokens. |
| 1.19.0 | 2026-07-24 | Duplicate `column_id` → formula promotion (ts-cli v0.92.0, BL-132): an SV that references one physical column both as a raw fact and as a simple-aggregate metric (e.g. a raw measure + `AVG(col)` on the same column) previously emitted two `columns[]` entries with an identical `TABLE::col`, failing `ts tml lint` I8 on import. `ts snowflake build-model` now keeps the first occurrence as a `column_id` entry and re-expresses the rest as `fn ( [TABLE::col] )` aggregation formulas (shared `formula_common.promote_duplicate_column_ids` helper, so from-Databricks behaves identically). A duplicate that is not a re-expressible aggregate is left in place for `ts tml lint` I8 to surface. |
| 1.18.0 | 2026-07-23 | Role-playing (aliased) dimension support (ts-cli v0.89.0): a physical table reused under multiple SV aliases now maps to distinct alias nodes — `model_tables` emit `alias:`, joins carry the alias in `with:` while the `on` clause uses physical names, and column refs use the alias prefix. Bare-column renames emit direct columns, not formulas. Live-verified against se-thoughtspot (SUPPORT_CASE_SV with ACCOUNT/USER/SUPPORT_PRODUCT__C role-plays). |
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
