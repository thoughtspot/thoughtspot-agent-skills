---
name: ts-load-source-data
description: Load source data (CSV, Tableau download, manifest) into a warehouse. Infers schema, generates synthetic data for schema-only sources, and provisions tables. Snowflake supported; Databricks planned.
---

# Load Source Data

Load CSV data into a warehouse for ThoughtSpot to connect to. Supports four input
modes: CSV directory, Tableau Cloud download output, manifest JSON, and schema-only
with synthetic data generation.

Ask one question at a time for **dependent** decisions. Batch independent questions.

---

## References

| File | Purpose |
|---|---|
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure — for understanding the downstream ThoughtSpot objects |
| [references/open-items.md](references/open-items.md) | Known issues and verification items |

---

## Prerequisites

- Snowflake profile configured — run `/ts-profile-snowflake` if not
- `ts` CLI installed: `pip install -e tools/ts-cli` (v0.15.0+)
- For `method:python` profiles: `pip install snowflake-connector-python`
- For `method:cli` profiles: `snow` CLI installed and configured
- Source data accessible on disk (CSV files, download output, or manifest JSON)

---

## Step 0 — Overview

On skill invocation, display this plan:

---
**ts-load-source-data** — load source data into a warehouse for ThoughtSpot.

### Input modes

  **1  CSV directory** — a folder of `.csv` files, one table per file
  **2  Tableau download** — output JSON from `ts tableau download`
  **3  Manifest JSON** — explicit schema + data file paths
  **4  Schema only** — column definitions without data → generate synthetic sample data

### Steps

  1.  Identify source data (path + auto-detect mode) ........ you provide
  2.  Select target warehouse (Snowflake) ................... auto (v1)
  3.  Select Snowflake profile .............................. you choose
  4.  Specify target location (database, schema) ............ you provide
  5.  Schema review (inferred types, confirm/override) ...... you confirm
  6.  Load data ............................................. auto
  7.  Summary + next steps .................................. auto

---

## Step 1 — Identify Source Data

Ask: "Provide the path to your source data — a directory of CSV files, a JSON file
from `ts tableau download`, or a manifest JSON."

Run `ts load infer --source <path>` to auto-detect and display:

```
Source type: {csv_dir | tableau_download | manifest | schema_only}
Tables found: {N}
```

If `schema_only`:
```
No data files found — this is a schema-only source.
Would you like to generate synthetic sample data? (Y/n)
If yes, how many rows per table? [100]:
```

---

## Step 2 — Select Target Warehouse

v1 supports Snowflake only. Display:

```
Target warehouse: Snowflake
```

When Databricks support is added, prompt: `Load into Snowflake or Databricks?`

---

## Step 3 — Select Snowflake Profile

Read `~/.claude/snowflake-profiles.json`. Show:

```
Snowflake profiles:

  1. {name}  —  {method_label}  —  {account_or_connection}
  2. {name}  —  {method_label}  —  {account_or_connection}

Select a profile (enter number or name):
```

For `method_label`: `method: python` + `auth: key_pair` → `python / key pair`,
`method: python` + `auth: password` → `python / password`, `method: cli` → `Snowflake CLI`.

---

## Step 4 — Specify Target Location

Ask: "Target database name:" and "Target schema name:"

Offer defaults if available from source metadata (e.g., Tableau download may have
the datasource name as a schema hint).

---

## Step 5 — Schema Review

Display the inferred schema from Step 1 as a table:

```
Table: {TABLE_NAME}  ({row_count} rows from {file})

  #   Column Name         DB Column Name      Inferred Type
  1   Row ID              ROW_ID              INTEGER
  2   Order Date          ORDER_DATE          DATE
  3   Sales               SALES               FLOAT
  4   Customer Name       CUSTOMER_NAME       VARCHAR(384)

Type overrides? Enter column # and new type (e.g. "1 VARCHAR(20)"), or confirm (Y):
```

Repeat for each table. Save the confirmed schema as a manifest JSON for reproducibility.

If schema-only + user accepted synthetic data in Step 1, run `ts load generate` here
with the confirmed schema.

---

## Step 6 — Load Data

Run `ts load snowflake` with the confirmed schema:

```bash
ts load snowflake --source <path> --profile <name> \
    --database <DB> --schema <SCH> --if-exists error
```

Show progress per table:

```
Loading into {DB}.{SCH}...
  DUNDERMIFFLINSALESTABLE    42 rows    ✓ created
  CUSTOMERSTABLE            150 rows    ✓ created
```

---

## Step 7 — Summary

Display the load result:

```
Load complete.

  Database: {DB}
  Schema:   {SCH}
  Profile:  {profile_name}

  Tables loaded:
    {TABLE_NAME}   {rows} rows   {columns} columns

Next steps:
  • Create a ThoughtSpot connection to {DB}.{SCH}
    → /ts-object-connection-create (when available)
  • Build ThoughtSpot objects over these tables
    → /ts-convert-from-tableau (if migrating from Tableau)
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-06-26 | Initial release — Snowflake loading with schema inference and synthetic data generation |
