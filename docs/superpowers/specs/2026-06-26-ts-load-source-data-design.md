# ts-load-source-data Design Spec

> **Backlog:** BL-010
> **Status:** Approved
> **Date:** 2026-06-26

## Goal

Build a generic warehouse data loader that takes source data (CSV files, Tableau
Cloud download output, manifest JSON, or schema-only definitions) and provisions
warehouse tables + loads data. Snowflake first; Databricks later. Motivated by the
gap found during the DunderMifflin Tableau migration: textscan datasources have data
only in Tableau Cloud with no warehouse copy.

## Architecture

Two deliverables:

1. **`ts load` CLI command group** (`tools/ts-cli/ts_cli/commands/load.py`) — four
   subcommands: `infer`, `generate`, `snowflake`, and future `databricks`. Testable,
   scriptable, reusable outside Claude Code.
2. **`ts-load-source-data` SKILL.md** (`agents/cli/ts-load-source-data/SKILL.md`) —
   interactive wrapper that orchestrates the CLI commands with schema review,
   type override, and guided target selection.

Design inspired by [cs_tools syncer](https://thoughtspot.github.io/cs_tools/syncer/what-is/)
adapter pattern (load strategies, auto table creation, per-warehouse plugins) but
built as a self-contained ts-cli module with no external dependency on cs_tools.

## Tech Stack

- Python 3.9+ (ts-cli runtime)
- `snowflake-connector-python` — **not** a ts-cli dependency; imported at runtime only
  when `method:python` is used. The SKILL.md prerequisite tells the user to
  `pip install snowflake-connector-python` if their profile uses the python method.
  `method:cli` profiles need only the `snow` CLI (no extra pip install).
- Snowflake CLI (`snow`) — for `method:cli` profiles
- `csv` stdlib module — CSV parsing and validation
- `json` stdlib module — manifest handling

---

## CLI Commands

### `ts load infer`

Schema inference from source data. Pure function — no warehouse connection needed.

```
ts load infer --source <path>
```

**Source auto-detection:**

| Path shape | Detected as |
|---|---|
| Directory containing `.csv` files | `csv_dir` |
| `.json` with `data_files` key | `tableau_download` (output of `ts tableau download`) |
| `.json` with `tables[].columns` + `tables[].data_file` | `manifest` (full manifest with data) |
| `.json` with `tables[].columns` but no `data_file` | `schema_only` (no data — use `generate`) |

**Type inference rules** (scan first 1000 rows per CSV):

| Pattern | Inferred type |
|---|---|
| All values parse as integer | `INTEGER` |
| All values parse as number with decimals | `FLOAT` |
| Matches `YYYY-MM-DD` | `DATE` |
| Matches `YYYY-MM-DD HH:MM:SS` (with variants) | `TIMESTAMP` |
| All values are `true`/`false`/`0`/`1` | `BOOLEAN` |
| Everything else | `VARCHAR(N)` where N = `max(max_observed_len * 1.5, 256)` |

Nulls and blanks are skipped during inference. A column that is 100% blank defaults
to `VARCHAR(256)`.

**Output (JSON to stdout):**

```json
{
  "source_type": "csv_dir",
  "tables": [
    {
      "file": "DunderMifflinSalesTable.csv",
      "table_name": "DUNDERMIFFLINSALESTABLE",
      "row_count": 42,
      "columns": [
        {"name": "Row ID", "db_column_name": "ROW_ID", "inferred_type": "INTEGER"},
        {"name": "Order Date", "db_column_name": "ORDER_DATE", "inferred_type": "DATE"},
        {"name": "Sales", "db_column_name": "SALES", "inferred_type": "FLOAT"},
        {"name": "Customer Name", "db_column_name": "CUSTOMER_NAME", "inferred_type": "VARCHAR(384)"}
      ]
    }
  ]
}
```

`db_column_name` is the warehouse-safe name (uppercase, spaces to underscores, special
characters stripped). `name` preserves the original for human review.

---

### `ts load generate`

Synthetic sample data generation from schema definitions.

```
ts load generate --source <schema.json> --rows <N> --output <dir>
```

Takes a schema-only manifest (or `ts load infer` output) and generates CSV files
with realistic synthetic data.

**Column name pattern matching:**

| Column name contains | Generator | Example |
|---|---|---|
| `id`, `key` (+ integer type) | Sequential integer | `1, 2, 3...` |
| `email` | Fake email | `user_42@example.com` |
| `name`, `customer` | Name from word pool | `Alice Chen` |
| `date`, `_at`, `_on` | Random date 2023–2025 | `2024-06-15` |
| `price`, `amount`, `cost`, `sales`, `revenue` | Random decimal 1–10000, 2dp | `459.32` |
| `quantity`, `count`, `qty` | Random integer 1–100 | `17` |
| `status`, `state`, `type`, `category` | Categorical from small pool | `Active` |
| `city`, `region` | City/region from pool | `Seattle` |
| `phone` | Phone pattern | `555-0142` |
| `percent`, `ratio`, `rate` | Random 0.0–1.0, 4dp | `0.4523` |
| No match + `INTEGER` | Random integer 1–1000 | `847` |
| No match + `FLOAT` | Random float 0–1000, 2dp | `234.56` |
| No match + `VARCHAR` | Random alphanumeric | `val_00042` |
| No match + `DATE` | Random date 2023–2025 | `2024-03-22` |
| No match + `BOOLEAN` | Random true/false | `true` |

Default: 100 rows. Output: one CSV per table in `--output` directory.

Generated CSVs can be fed directly to `ts load snowflake --source <output-dir>`.

---

### `ts load snowflake`

Load CSV data into Snowflake tables.

```
ts load snowflake --source <path> --profile <name> \
    --database <db> --schema <schema> \
    [--if-exists skip|replace|error] \
    [--warehouse <wh>] [--role <role>] \
    [--generate-sample --rows <N>]
```

**Auth:** reads `~/.claude/snowflake-profiles.json` (managed by `/ts-profile-snowflake`).
The profile's `method` field determines the execution path:

**method: python (snowflake.connector)**

```
1. Connect using profile credentials (key_pair or password)
2. CREATE DATABASE IF NOT EXISTS <db>
3. CREATE SCHEMA IF NOT EXISTS <db>.<schema>
4. Per table:
   a. CREATE TABLE (or handle --if-exists)
   b. PUT file://<csv_path> @%<table_name>
   c. COPY INTO <table> FROM @%<table_name>
      FILE_FORMAT=(TYPE=CSV FIELD_OPTIONALLY_ENCLOSED_BY='"' SKIP_HEADER=1)
   d. REMOVE @%<table_name>
5. Return JSON summary
```

**method: cli (snow)**

```
1. snow sql -c <cli_connection> -q "CREATE DATABASE IF NOT EXISTS ..."
2. snow sql -c <cli_connection> -q "CREATE SCHEMA IF NOT EXISTS ..."
3. Per table:
   a. snow sql for CREATE TABLE
   b. snow stage copy <csv_path> @<db>.<schema>.%<table_name>
   c. snow sql for COPY INTO
   d. snow sql for REMOVE
4. Return JSON summary
```

**`--if-exists` behaviour:**

| Value | Table exists | Action |
|---|---|---|
| `error` (default) | Yes | Exit with error, no data loaded |
| `skip` | Yes | Skip this table, continue with others |
| `replace` | Yes | DROP + CREATE + load |

**`--warehouse` / `--role`:** default to the profile's `default_warehouse` /
`default_role` but can be overridden per-invocation.

**`--generate-sample --rows N`:** when source is schema-only (no CSVs), generate
synthetic data inline before loading. Equivalent to piping through `ts load generate`
but in a single command.

**Output (JSON to stdout):**

```json
{
  "database": "AGENT_SKILLS",
  "schema": "DUNDERMIFFLIN",
  "profile": "Production",
  "tables": [
    {
      "table_name": "DUNDERMIFFLINSALESTABLE",
      "status": "created",
      "rows_loaded": 42,
      "columns": 12,
      "source_file": "DunderMifflinSalesTable.csv"
    }
  ]
}
```

---

### `ts load databricks` (future — v2)

Same interface pattern as `snowflake`. Uses Databricks SQL connector or REST API.
Load strategy: `INSERT INTO ... VALUES` in batches (low-volume use case).
Auth: reads from a future Databricks profiles file managed by `/ts-profile-databricks`.

---

## Manifest JSON Format

The universal input contract. All other input modes are normalised to this shape
internally.

```json
{
  "source": "tableau-download | csv-dir | manual",
  "tables": [
    {
      "table_name": "DUNDERMIFFLINSALESTABLE",
      "data_file": "./csvs/DunderMifflinSalesTable.csv",
      "columns": [
        {"name": "Row ID", "db_column_name": "ROW_ID", "type": "INTEGER"},
        {"name": "Order Date", "db_column_name": "ORDER_DATE", "type": "DATE"},
        {"name": "Sales", "db_column_name": "SALES", "type": "FLOAT"}
      ]
    }
  ]
}
```

- `data_file` — optional; omit for schema-only mode (pair with `--generate-sample`)
- `type` — overrides inference when present
- `db_column_name` — warehouse-safe column name
- `name` — human-readable original

---

## SKILL.md Flow

**Skill name:** `ts-load-source-data`
**Family:** New `ts-load-*` family (added to `skill-naming.md`)
**Location:** `agents/cli/ts-load-source-data/SKILL.md`

```
Step 0 — Overview
         Show plan and input modes

Step 1 — Identify source data
         Ask: path to CSV directory, download output JSON, or manifest JSON
         Auto-detect input mode

Step 2 — Select target warehouse
         Ask: Snowflake (v1) or Databricks (future)

Step 3 — Select warehouse profile
         Read ~/.claude/snowflake-profiles.json
         Show profiles list, user picks one

Step 4 — Specify target location
         Ask: database name, schema name
         Offer defaults from profile or from source metadata

Step 5 — Schema review
         Run `ts load infer`, display inferred schema as table
         User confirms or overrides individual column types
         If schema-only (no data): offer --generate-sample with row count

Step 6 — Load data
         Run `ts load snowflake` with confirmed schema
         Show per-table progress and status

Step 7 — Summary
         Display loaded tables, row counts, warehouse location
         Suggest next step:
           - "Run /ts-convert-from-tableau to build ThoughtSpot objects
              over these tables"
           - "Create a ThoughtSpot connection with
              /ts-object-connection-create (BL-011)"
```

---

## Repo Convention Updates

| Area | Change |
|---|---|
| `tools/ts-cli/ts_cli/commands/load.py` | New module with `infer`, `generate`, `snowflake` subcommands |
| `tools/ts-cli/ts_cli/cli.py` | Register `load` command group |
| `tools/ts-cli/README.md` | Add `ts load infer/generate/snowflake` sections |
| `tools/ts-cli/__init__.py` + `pyproject.toml` | Version bump |
| `agents/cli/ts-load-source-data/SKILL.md` | New skill |
| `agents/cli/ts-load-source-data/references/open-items.md` | Track verification items |
| `.claude/rules/skill-naming.md` | Add family 9: `ts-load-*` |
| `tools/validate/check_skill_naming.py` | Add `ts-load-*` pattern |
| `tools/validate/check_runtime_coverage.py` | Add `ts-load-source-data` to `EXPECTED_DIVERGENCES` (CoCo: warehouse loading not supported in Snowsight runtime) |
| `tools/smoke-tests/smoke_ts_load_source_data.py` | New smoke test |
| `README.md` | Add skill to skills table |
| `agents/cli/SETUP.md` | Add symlink step |
| `CHANGELOG.md` | Entry for new skill + ts-cli bump |
| `docs/backlog.md` | Update BL-010 status |

---

## Scope Boundaries

**In scope (v1):**
- Snowflake loading (both python and cli methods)
- CSV directory, Tableau download output, manifest JSON, schema-only inputs
- Type inference with interactive review
- Synthetic sample data generation
- `--if-exists` table conflict handling

**Out of scope (deferred):**
- Databricks loading (v2 — BL-010 extension)
- ThoughtSpot connection creation (BL-011 — separate skill)
- .hyper file extraction (Tableau proprietary format)
- Incremental/delta loads (append to existing data with dedup)
- Data transformation during load (type casting, column renaming beyond db_column_name)

---

## Relationship to Other Skills

```
ts-convert-from-tableau (Step 3.5)
  → identifies textscan sources needing data load
  → calls ts tableau download to extract CSVs
  → hands off to ts-load-source-data for warehouse loading

ts-load-source-data
  → loads CSVs into Snowflake (or generates sample data)
  → hands off to ts-object-connection-create (BL-011) for ThoughtSpot connection

ts-object-connection-create (BL-011)
  → creates ThoughtSpot connection to the loaded warehouse tables
  → hands back to ts-convert-from-tableau for model/liveboard creation
```
