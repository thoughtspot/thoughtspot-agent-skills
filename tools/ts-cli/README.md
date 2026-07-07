# ThoughtSpot CLI (`ts`)

A lightweight Python CLI wrapping the ThoughtSpot REST API. Used at runtime by
Claude Code and Cortex Code CLI skills to authenticate, search metadata, and
export/import TML.

---

## Installation

```bash
pip install -e /path/to/thoughtspot-agent-skills/tools/ts-cli
```

After install, the `ts` command is available on your PATH.

---

## Authentication & profiles

The CLI resolves which profile to use in this order:

1. `--profile <name>` flag on the command
2. `TS_PROFILE` environment variable
3. First profile in `~/.claude/thoughtspot-profiles.json`

Profiles are created and managed by the `ts-profile-thoughtspot` skill (available
in both Claude Code and Cortex Code CLI). Credentials are stored in the OS
credential store (macOS Keychain, Windows Credential Manager, Linux Secret Service)
— never in the profile file itself.

Tokens are cached in `/tmp/ts_token_<slug>.txt` (permissions: `0600`) and reused
until they expire or `ts auth logout` is called.

---

## Commands

### `ts profiles list`

List all configured ThoughtSpot profiles. Credentials are never shown.

```bash
ts profiles list
```

**Output:**

```
  champ-staging         token         https://champagne-master-aws.thoughtspotstaging.cloud
```

---

### `ts auth whoami`

Verify authentication and print the current user's details.

```bash
ts auth whoami
ts auth whoami --profile champ-staging
```

**Output:** JSON from `GET /api/rest/2.0/auth/session/user`

```json
{
  "id": "f6336c00-1b9f-4119-a2be-79747234e19d",
  "name": "damian.waldron@thoughtspot.com",
  "display_name": "damian.waldron",
  "account_status": "ACTIVE",
  "privileges": ["ADMINISTRATION", "AUTHORING", "DEVELOPER", ...],
  ...
}
```

---

### `ts auth token`

Print the current bearer token. Useful for debugging or passing to other tools.

```bash
ts auth token
ts auth token --profile champ-staging
```

**Output:** The raw bearer token string (base64-encoded).

---

### `ts auth logout`

Clear the cached token so the next command triggers a fresh authentication.

```bash
ts auth logout
ts auth logout --profile champ-staging
```

**Output:**

```
Token cache cleared for profile 'champ-staging'.
```

---

### `ts metadata search`

Search ThoughtSpot metadata objects (auto-paginated by default).

```bash
ts metadata search [OPTIONS]
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | `LOGICAL_TABLE` | Object type: `LOGICAL_TABLE`, `LIVEBOARD`, `ANSWER` |
| `--subtype`, `-s` | (none) | Subtype filter within `LOGICAL_TABLE` (repeatable): `WORKSHEET`, `MODEL`, `ONE_TO_ONE_LOGICAL`, `USER_DEFINED`, `AGGR_WORKSHEET` |
| `--name`, `-n` | (none) | Name filter using SQL LIKE syntax: `%` = any chars, `_` = one char |
| `--guid`, `-g` | (none) | Filter by GUID (exact match) |
| `--tag` | (none) | Filter by tag name or GUID (repeatable) |
| `--include-hidden` | false | Include hidden objects |
| `--include-incomplete` | false | Include incomplete objects |
| `--limit`, `-l` | (none — auto-paginate) | When set, returns a single page of at most this many results starting at `--offset` (legacy behavior). Omit to fetch the full result set. |
| `--offset` | 0 | Pagination offset (only meaningful together with `--limit`) |
| `--all` | false | Deprecated no-op — auto-pagination to the full result set is now the default whenever `--limit` is omitted. Kept only so existing callers don't break. |

**Examples:**

```bash
# All tables/worksheets/models (default type = LOGICAL_TABLE), full result set
ts metadata search

# Worksheets and models only
ts metadata search --subtype WORKSHEET

# Search by name
ts metadata search --subtype WORKSHEET --name "%sales%"

# Search liveboards, full result set (--all is accepted but no longer needed)
ts metadata search --type LIVEBOARD --all

# Find by GUID
ts metadata search --guid e61c7c4c-68a4-4174-b393-a0104ae3bd00

# Single page only (legacy behavior)
ts metadata search --type LIVEBOARD --limit 10
```

**Output:** JSON array from `POST /api/rest/2.0/metadata/search` — the full result set
unless `--limit` is given.

```json
[
  {
    "metadata_id": "e61c7c4c-68a4-4174-b393-a0104ae3bd00",
    "metadata_name": "Retail Sales WS",
    "metadata_type": "LOGICAL_TABLE",
    "metadata_header": {
      "id": "e61c7c4c-68a4-4174-b393-a0104ae3bd00",
      "name": "Retail Sales WS",
      "type": "WORKSHEET",
      "author": "64a0ea53-097d-4682-a34e-e7ad39c35506",
      "authorName": "nicolas.rentz@thoughtspot.com",
      "created": 1717202157272,
      "modified": 1717202210581,
      ...
    }
  }
]
```

---

### `ts metadata get <guid>`

Get details of a single metadata object by GUID.

```bash
ts metadata get e61c7c4c-68a4-4174-b393-a0104ae3bd00
ts metadata get e61c7c4c-68a4-4174-b393-a0104ae3bd00 --profile champ-staging
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | `LOGICAL_TABLE` | Object type to search within |

**Output:** Single metadata object (same structure as one element of `metadata search`).

---

### `ts metadata dependents <guid> [<guid> ...]`

List all objects that depend on the given source GUID(s). Wraps the v2
`metadata/search` endpoint with `include_dependent_objects=true,
dependent_object_version=V2`.

```bash
# Models / Liveboards / Answers / Sets / Feedback that reference this table
ts metadata dependents 32c062cb-9586-43ff-bc66-bceed7529caf

# Same shape, but for a Set/Cohort GUID — must use --type LOGICAL_COLUMN
ts metadata dependents 7f9179af-0a13-4d6f-9a87-2c8099a5c73d --type LOGICAL_COLUMN

# Get the unmodified v2 response (e.g. to read hasInaccessibleDependents)
ts metadata dependents abc-123 --raw
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | `LOGICAL_TABLE` | Source type: `LOGICAL_TABLE` (table/model/view) or `LOGICAL_COLUMN` (column or set/cohort GUID) |
| `--raw` | off | Emit the v2 response untouched instead of the flat normalized list |

**Output (default — flat, one row per dependent):**

```json
[
  {
    "source_guid": "32c062cb-9586-43ff-bc66-bceed7529caf",
    "guid": "e5c84be6-ebbc-4ef0-9522-e124f0d29827",
    "name": "TEST_DEPENDENCY_MANAGEMENT",
    "type": "LOGICAL_TABLE",
    "raw_bucket": "LOGICAL_TABLE",
    "author_id": "f6336c00-1b9f-4119-a2be-79747234e19d",
    "author_display_name": "damian.waldron"
  },
  {
    "source_guid": "32c062cb-...",
    "guid": "62d8c5ef-9c92-4755-a691-9741322d8e2c",
    "name": "ADDRESS set, ZIPCODE, COMPANY_NAME, CITY",
    "type": "ANSWER",
    "raw_bucket": "QUESTION_ANSWER_BOOK",
    ...
  }
]
```

**Type mapping:**

| v2 bucket | Output type |
|---|---|
| `QUESTION_ANSWER_BOOK` | `ANSWER` |
| `PINBOARD_ANSWER_BOOK` | `LIVEBOARD` |
| `LOGICAL_TABLE` | `LOGICAL_TABLE` (caller distinguishes Model/View/Table via subtype) |
| `COHORT` | `SET` |
| `FEEDBACK` | `FEEDBACK` |

**Not covered by v2 dependents:** RLS rules (in source table TML), Alerts (via
Liveboard `--associated`), column aliases, column security TML. See the
`ts-dependency-manager` skill's `references/open-items.md` for the workarounds.

---

### `ts metadata report`

Audit one or more sources: walks dependents, probes TML for RLS rules, alerts, joins, column aliases, and Spotter AI surface area, classifies risk, and renders the result as JSON / text / markdown.

```bash
ts metadata report <source>... --profile <name> [--format json|text|md] [--fast] [--out FILE] [--depth N]
```

`<source>` accepts a 36-char GUID, `DB.SCHEMA.TABLE`, or `DB.SCHEMA.TABLE.COLUMN`. `--fast` skips TML probes (dependents walk only). Default format is `json`.

Output schema: defined in code at `tools/ts-cli/ts_cli/report/schema.py` (the `DependentEntry` / `RiskTag` dataclasses).

---

### `ts metadata delete <guid> [<guid> ...]`

Delete one or more ThoughtSpot objects by GUID.

```bash
ts metadata delete abc-123
ts metadata delete abc-123 def-456 --type LIVEBOARD
ts metadata delete abc-123 --profile se-thoughtspot
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | `LOGICAL_TABLE` | Object type: `LOGICAL_TABLE`, `LIVEBOARD`, `ANSWER` |

**Output:** `{"deleted": ["guid1", "guid2", ...]}` on success.

---

### `ts tml export <guid> [<guid> ...]`

Export TML for one or more objects.

```bash
# Export a single object
ts tml export e61c7c4c-68a4-4174-b393-a0104ae3bd00

# Export with fully-qualified names (required for Snowflake Semantic View conversion)
ts tml export e61c7c4c-68a4-4174-b393-a0104ae3bd00 --fqn

# Export with associated objects (e.g. tables referenced by a worksheet)
ts tml export e61c7c4c-68a4-4174-b393-a0104ae3bd00 --fqn --associated

# Export multiple objects
ts tml export abc-123 def-456 --format JSON

# Export coaching feedback TML (nls_feedback) for a Model
ts tml export abc-123 --type FEEDBACK --parse

# Export with obj_id references (for repoint operations)
ts tml export abc-123 --include-obj-id --include-obj-id-ref --no-guid --parse
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--fqn` | false | Include fully-qualified names in output |
| `--associated` | false | Export associated objects (e.g. tables for a model) |
| `--format`, `-f` | `YAML` | Output format: `YAML` or `JSON` |
| `--parse` | false | Parse each `edoc` string into a structured JSON object (see below) |
| `--type` | (none) | Metadata type for each export entry. Use `FEEDBACK` to export a Model's coaching feedback TML (nls_feedback). |
| `--include-obj-id` | false | Include `obj_id` on the exported object itself. |
| `--include-obj-id-ref` | false | Include `obj_id` on referenced objects (e.g. `model_tables` entries). |
| `--include-guid` / `--no-guid` | true | Include `guid` at document root. Use `--no-guid` to omit. |

**Output (default):** JSON array from `POST /api/rest/2.0/metadata/tml/export`. Each element
contains `info` (metadata) and `edoc` (the raw TML string).

```json
[
  {
    "info": {
      "name": "Retail Sales WS",
      "id": "e61c7c4c-68a4-4174-b393-a0104ae3bd00",
      "type": "worksheet"
    },
    "edoc": "worksheet:\n  name: Retail Sales WS\n  ..."
  }
]
```

**Output (with `--parse`):** Each `edoc` is parsed from YAML into a structured object.
Non-printable characters are stripped automatically. The `edoc` field is replaced by
`type`, `guid`, and `tml`.

```json
[
  {
    "type": "model",
    "guid": "3b0de9da-8753-4def-b5a4-1be6b7f66991",
    "tml": {
      "guid": "3b0de9da-8753-4def-b5a4-1be6b7f66991",
      "model": {
        "name": "Retail Sales WS",
        "formulas": [...],
        "columns": [...]
      }
    },
    "info": {
      "name": "Retail Sales WS",
      "id": "3b0de9da-8753-4def-b5a4-1be6b7f66991",
      "type": "model"
    }
  }
]
```

Skills that use `--parse` replace the standard three-step parse boilerplate
(`json.loads` → strip non-printable → `yaml.safe_load`) with a single `json.loads`
on the CLI output.

**Note:** Using `--associated` on a model exports the model plus all referenced tables.
For example, `--fqn --associated` on a model with 3 tables returns 4 objects total.

---

### `ts tml import`

Import TML objects. Two input modes — mutually exclusive:

1. **`--file`/`--dir`** — reads raw TML text directly from one or more files.
   `--file` is repeatable; `--dir` imports every `.tml`/`.yaml`/`.yml`/`.json`
   file in a directory (non-recursive), in sorted-name order, after any
   explicit `--file` entries.
2. **stdin** (default when neither `--file` nor `--dir` is given) — a JSON
   array of TML strings (or a single JSON string). Unchanged from prior
   versions.

```bash
# Import a model from a file (ALL_OR_NONE — atomic, all succeed or nothing is created)
ts tml import --file model.tml --policy ALL_OR_NONE --profile champ-staging

# Import multiple files
ts tml import --file table1.tml --file table2.tml --policy PARTIAL

# Import every TML file in a directory
ts tml import --dir ./tml_out --policy PARTIAL

# Tableau-order directory import, base model only, then filtered by pattern
ts tml import --dir ./tml_out --order tableau --model-phase base --policy ALL_OR_NONE
ts tml import --dir ./tml_out --pattern '*.liveboard.tml' --policy PARTIAL --create-new

# Original stdin interface (unchanged)
echo '["table:\n  name: ..."]' | ts tml import --policy PARTIAL
cat tmls.json | ts tml import --policy ALL_OR_NONE --profile champ-staging
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--policy` | `PARTIAL` | Import policy, passed through to the API: `PARTIAL`, `ALL_OR_NONE`, `PARTIAL_OBJECT`, or `VALIDATE_ONLY` (dry-run server-side validation) |
| `--create-new / --no-create-new` | `--no-create-new` | Create new objects. Default updates existing objects only; pass `--create-new` for brand-new TML with no existing GUID |
| `--file` | none | Path to a raw TML file (repeatable). Mutually exclusive with piped stdin content |
| `--dir` | none | Import every `.tml`/`.yaml`/`.yml`/`.json` file in this directory (non-recursive). Mutually exclusive with piped stdin content |
| `--order` | `name` | File order for `--dir` (and `--file`) input: `name` (sorted-name order, unchanged) or `tableau` (type order table → sql_view → model → cohort → liveboard, by filename suffix; ties broken by name) |
| `--model-phase` | `all` | `all` (unchanged) or `base` — drops phased model files `*.phaseN.model.tml` for N ≥ 1, keeping bare `*.model.tml` and `*.phase0.model.tml` |
| `--pattern` | none | Glob(s) to filter `--dir` matches (repeatable), e.g. `--pattern '*.liveboard.tml'`. Only restricts files picked up by `--dir` — has no effect on explicit `--file` entries |

`--order`/`--model-phase`/`--pattern` apply only to the `--file`/`--dir` input mode — they have no effect on the stdin JSON-array interface.

**Input:** either `--file`/`--dir` (raw TML text per file) or, when neither is given, stdin as a JSON array of TML strings, e.g.:

```json
["table:\n  name: MY_TABLE\n  db: MY_DB\n  ..."]
```

Combining `--file`/`--dir` with piped stdin content is rejected as an ambiguous invocation — pick one input mode.

**Output:** JSON from `POST /api/rest/2.0/metadata/tml/import` containing
per-object status and GUIDs of created/updated objects.

---

### `ts tml lint`

Lint TML **locally** for the model invariants that ThoughtSpot's `VALIDATE_ONLY`
import policy does **not** catch — the ones it accepts silently and then mis-behaves on
(drops a formula, flips a measure to an attribute, breaks a join at query time). No
ThoughtSpot connection needed; pure structural check. Run it before `ts tml import` to
fail loud.

Checks (mirrors `agents/shared/schemas/ts-model-conversion-invariants.md`):

| Rule | What it catches |
|---|---|
| guid placement | `guid:` nested inside `table:`/`model:` instead of at the document root |
| I1 | a `formulas[]` entry with no paired `columns[]` entry (`formula_id` == `id`) — silently dropped |
| I2 | an `aggregation:` under a `formulas[]` entry (only `columns[]` may carry it) |
| I4 | `model_tables[].id` != `name` — joins silently fail at query time |
| I5 | a physical column using `aggregation: COUNT_DISTINCT` — silently flips MEASURE → ATTRIBUTE |
| I8 | a duplicate `column_id` across `columns[]` — hard import rejection ("columns should have unique column_id values") |

```bash
# Lint a single file
ts tml lint --file model.tml

# Lint every TML file in a directory
ts tml lint --dir ./tml_out

# Tableau-order directory lint, base model only
ts tml lint --dir ./tml_out --order tableau --model-phase base

# Lint the same payload you would import (original stdin interface)
cat tmls.json | ts tml lint

# Gate an import on a clean lint
ts tml lint --file model.tml && ts tml import --file model.tml --policy ALL_OR_NONE
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--file` | none | Path to a raw TML file (repeatable). Mutually exclusive with piped stdin content |
| `--dir` | none | Lint every `.tml`/`.yaml`/`.yml`/`.json` file in this directory (non-recursive). Mutually exclusive with piped stdin content |
| `--order` | `name` | Same as `ts tml import --order`: `name` (default) or `tableau` (table → sql_view → model → cohort → liveboard) |
| `--model-phase` | `all` | Same as `ts tml import --model-phase`: `all` (default) or `base` (drop `*.phaseN.model.tml` for N ≥ 1) |
| `--pattern` | none | Same as `ts tml import --pattern`: glob(s) to filter `--dir` matches (repeatable) |

`--order`/`--model-phase`/`--pattern` apply only to the `--file`/`--dir` input mode, matching `ts tml import`.

**Input:** the SAME input as `ts tml import` — either `--file`/`--dir` (raw TML text per file) or, when neither is given, stdin as a JSON string or array of TML strings.

**Output:** JSON `{"clean": bool, "results": [{index, type, name, findings: [...]}]}`.
**Exit code** is `1` if any document has findings, else `0` — so it composes with `&&`.

---

### `ts connections list`

List all available data connections. Results are auto-paginated — all connections
are returned regardless of how many exist on the instance.

```bash
ts connections list
ts connections list --type BIGQUERY
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | `SNOWFLAKE` | Data warehouse type filter |

**Output:** JSON array of connection objects.

```json
[
  {
    "id": "1f428ed0-c672-435d-a7e1-b4781e5f492c",
    "name": "thoughtspot_partner",
    "description": "",
    "data_warehouse_type": "SNOWFLAKE"
  }
]
```

---

### `ts connections create`

Create a Snowflake data connection using **key-pair** authentication (no tables).
Register tables afterwards with `ts tables create`, referencing the connection by name.

```bash
ts connections create \
  --name APJ_SKILLS \
  --account myorg-myaccount \
  --user SVC_USER \
  --role SE_ROLE \
  --warehouse DEMO_WH \
  --database AGENT_SKILLS \
  --private-key-path ~/.ssh/snowflake_private_key.p8
```

**Options:**

| Flag | Required | Description |
|---|---|---|
| `--name` | yes | Unique name for the new connection |
| `--account` | yes | Snowflake account identifier (e.g. `myorg-myaccount` or `account.region`) |
| `--user` | yes | Snowflake username |
| `--role` | yes | Snowflake role (must see the target database/schema) |
| `--warehouse` | yes | Snowflake warehouse |
| `--private-key-path` | yes | Path to the unencrypted PKCS#8 private key (`.p8`) |
| `--database` | no | Default database |
| `--description` | no | Connection description |
| `--profile`, `-p` | no | Profile to use |

Sends `POST /api/rest/2.0/connection/create` with `authenticationType=KEY_PAIR`,
`validate=false`, and an empty `externalDatabases`. The private key is read from
the file path and placed under the `private_key` configuration attribute — its
value is never printed or logged. The matching public key must be registered on
the Snowflake user (`DESC USER` shows `RSA_PUBLIC_KEY`). Requires `DATAMANAGEMENT`
or `ADMINISTRATION` (`CAN_CREATE_OR_EDIT_CONNECTIONS` under RBAC).

**Output:** JSON `{id, name, data_warehouse_type}` of the created connection.

> **Key-pair only.** This command creates Snowflake connections via key-pair auth.
> Password/OAuth and other warehouse types (e.g. Databricks) are not supported here.

---

### `ts connections get <connection-id>`

Fetch full connection details including the database/schema/table/column hierarchy.

```bash
ts connections get 1f428ed0-c672-435d-a7e1-b4781e5f492c
```

**Output:** JSON in the legacy `dataWarehouseInfo.databases` shape, adapted from
`POST /api/rest/2.0/connection/search` (the v2 endpoint).

> **Note:** This command now uses the v2 `connection/search` endpoint — the v1
> `/tspublic/v1/connection/fetchConnection` endpoint was removed on newer
> ThoughtSpot Cloud builds (returns 404). Requires the
> `CAN_CREATE_OR_EDIT_CONNECTIONS` privilege. The database/table/column hierarchy
> is only populated for connections that authenticate with a stored
> `SERVICE_ACCOUNT`; OAuth/PKCE/per-user connections return an empty hierarchy
> (use `ts metadata search` to find already-registered tables instead).

---

### `ts connections add-tables <connection-id>`

Add or update tables in a connection without removing existing tables.

```bash
echo '[{"db":"MY_DB","schema":"MY_SCHEMA","table":"MY_TABLE","type":"TABLE","columns":[{"name":"ID","type":"NUMBER"},{"name":"NAME","type":"VARCHAR"}]}]' \
  | ts connections add-tables 1f428ed0-c672-435d-a7e1-b4781e5f492c
```

**Input (stdin):** JSON array of table descriptors:

```json
[
  {
    "db": "MY_DATABASE",
    "schema": "MY_SCHEMA",
    "table": "MY_TABLE",
    "type": "TABLE",
    "columns": [
      {"name": "COL1", "type": "VARCHAR"},
      {"name": "COL2", "type": "NUMBER"}
    ]
  }
]
```

**How it works:**

1. Fetches the current connection state via `fetchConnection` (v1)
2. Merges the new tables in — existing tables and columns are preserved
3. New columns are appended to existing tables; existing columns are left unchanged
4. Posts the merged result to `POST /api/rest/2.0/connections/{id}/update`

**Output:** JSON response from the update call.

> **Note:** Inherits the same v1 fetch limitation as `ts connections get` — may
> fail with a 500 on some instances. Requires `CAN_CREATE_OR_EDIT_CONNECTIONS`
> privilege.

---

### `ts tables create`

Create ThoughtSpot logical table objects from a JSON spec.

```bash
cat tables.json | ts tables create --profile my-profile
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--retries`, `-r` | 3 | Max retries per table on transient JDBC errors |
| `--retry-delay` | 5.0 | Seconds between retries |

**Input (stdin):** JSON array of table descriptors:

```json
[
  {
    "name": "FACT_SALES",
    "db": "ANALYTICS",
    "schema": "PUBLIC",
    "db_table": "FACT_SALES",
    "connection_name": "APJ_BIRD",
    "columns": [
      {"name": "SALE_ID",   "data_type": "INT64",   "column_type": "ATTRIBUTE"},
      {"name": "AMOUNT",    "data_type": "DOUBLE",  "column_type": "MEASURE"},
      {"name": "SALE_DATE", "data_type": "DATE",    "column_type": "ATTRIBUTE"},
      {"name": "REGION",    "data_type": "VARCHAR", "column_type": "ATTRIBUTE"}
    ]
  }
]
```

**Field notes:**
- `connection_name` — the ThoughtSpot connection display name (string), not a GUID
- `data_type` — one of: `INT64`, `DOUBLE`, `VARCHAR`, `DATE`, `DATE_TIME`, `BOOLEAN`
- `column_type` — `ATTRIBUTE` (default) or `MEASURE` (adds `aggregation: SUM`)

**Output:** JSON object mapping table name → GUID for all successfully created tables.
Tables that failed after all retries are included with `null` as the GUID.

```json
{"FACT_SALES": "b1e360c4-d571-490f-bae2-e8dc7443c9fa"}
```

Auto-retries transient JDBC errors and resolves GUIDs via metadata search after import.

---

### `ts spotql generate-sql` / `ts spotql fetch-data`

Run SpotQL (Semantic SQL) against a ThoughtSpot Model. The caller supplies the SpotQL
statement and the Model's GUID — these commands do **not** do natural-language → SpotQL.

- `generate-sql` validates the statement and returns the warehouse SQL it compiles to
  (does not execute).
- `fetch-data` executes the statement and returns result rows.

```bash
ts spotql generate-sql '<SpotQL>' --model <model-guid> --profile <name>
ts spotql fetch-data   '<SpotQL>' --model <model-guid> --profile <name>
```

**Example:**

```bash
ts spotql fetch-data \
  'SELECT "Product Category", SUM("Amount") AS total_amount
   FROM "Dunder Mifflin Sales & Inventory" AS "t1" GROUP BY "Product Category"' \
  --model 4da3a07f-fe29-4d20-8758-260eb1315071 --profile champ-staging
```

**Output (JSON to stdout):**

- `generate-sql` → `{status, executable_sql, errors}`
- `fetch-data` → `{status, columns, rows, errors}`

`columns` are `{index, type}` — SpotQL returns per-query column GUIDs (not stable names),
so the SELECT ordinal is the usable identifier. A query that is rejected or fails to
execute returns a non-`SUCCESS` `status` with a populated `errors[]` (and exit code 0) —
these are structured query errors, not transport failures.

> **SpotQL requires an external cloud data warehouse.** The endpoints only support Models
> backed by an external CDW (Snowflake, Databricks, BigQuery, …). A Model over Falcon /
> imported / system data (`DEFAULT` datasource) returns
> `"This API only supports external cloud data warehouses"`.

---

### `ts spotql classify-columns`

Classify ThoughtSpot columns/formula expressions as attribute vs. measure vs.
aggregate-formula-measure — the decision that drives `SUM`-vs-`AGG` in SpotQL and the
MEASURE/ATTRIBUTE + aggregation inference when promoting Answer formulas to a Model.
Codifies BL-087: this was previously two DIFFERENT, drifted keyword lists duplicated
between `ts-object-model-spotql-query` and `ts-object-answer-promote`; both skills now
call through this one command.

Two mutually-exclusive input modes:

| Mode | Flag | What it does | ThoughtSpot connection |
|---|---|---|---|
| Model | `--model <guid>` | Exports the Model's TML and classifies every `model.columns[]` entry | Yes — uses `--profile` |
| Expressions | `--exprs-file <path>` (or stdin) | Classifies a bare JSON array of `{"name", "expr"}` objects not yet attached to a Model column (e.g. Answer formulas being promoted) | No |

```bash
ts spotql classify-columns --model <model-guid> --profile <name>
ts spotql classify-columns --exprs-file formulas_to_add.json
echo '[{"name": "Profit Margin", "expr": "[Revenue] - [Cost]"}]' | ts spotql classify-columns
```

**Output (JSON to stdout):**

- `--model` mode → array of `{name, column_type, kind, needs_agg, aggregation}` — one
  entry per `model.columns[]` entry. `kind` is `"attribute"`, `"raw_measure"`, or
  `"aggregate_measure"`. `kind == "aggregate_measure"` (equivalently `needs_agg: true`)
  means SpotQL must wrap the column in `AGG(...)` — never a real aggregate, or
  ThoughtSpot rejects the query with `NESTED_AGGREGATE_NOT_SUPPORTED`. `"raw_measure"`
  means a real aggregate (`aggregation` names which — `SUM`/`AVG`/…). `"attribute"`
  means group by it.
- `--exprs-file`/stdin mode → array of `{name, column_type, aggregation, is_aggregate}` —
  `column_type` is `MEASURE` iff the expression contains a call to an aggregate function
  (`sum`, `count`, `group_aggregate`, `last_value`, …), else `ATTRIBUTE`; `aggregation` is
  `SUM` for every MEASURE (ThoughtSpot ignores the `aggregation` property on formula
  columns at query time — the expr is self-contained), `null` for an ATTRIBUTE.

Diagnostic counts go to stderr. The canonical aggregate-function list lives in
`ts_cli.spotql_ops.AGGREGATE_FUNCS` — a single source of truth, not duplicated in either
skill's SKILL.md.

---

### `ts orgs search`

List/search orgs (auto-paginated by default).

```bash
ts orgs search --profile <name> [--status ACTIVE] [--name "%pattern%"] [--limit <n>]
```

Omit `--limit` to fetch the full result set (default). Pass `--limit` for the legacy
single-page behavior (starting at offset 0).

---

### `ts users search`

List/search users (by name or email; auto-paginated by default).

```bash
ts users search --profile <name> [--name "%pattern%"] [--org <org> ...] [--status ACTIVE] [--limit <n>]
```

Omit `--limit` to fetch the full result set (default). Pass `--limit` for the legacy
single-page behavior.

---

### `ts users groups`

List/search user groups (auto-paginated by default).

```bash
ts users groups --profile <name> [--name "%pattern%"] [--org <org> ...] [--include-users] [--limit <n>]
```

Omit `--limit` to fetch the full result set (default). Pass `--limit` for the legacy
single-page behavior.

---

### `ts variables search`

Show template variables and their assigned values (e.g. `ts_user_timezone`; auto-paginated).

```bash
ts variables search [<variable>] --profile <name>      # omit <variable> for all
```

Always returns the full result set across all pages (same pattern as `ts connections list`).

---

### `ts variables set`

Assign a variable value at org and/or user scope (used by `ts-variable-timezone`).

```bash
ts variables set <variable> <value> --profile <name> --org <org> [--org ...] [--user <username> ...]
# e.g. ts variables set ts_user_timezone "Australia/Sydney" --profile prod --org Primary
```

Uses the per-identifier endpoint `POST /api/rest/2.0/template/variables/{identifier}/update-values`
(`<variable>` — name or GUID — goes directly in the URL path). This replaced the deprecated
batch endpoint `POST /api/rest/2.0/template/variables/update-values` (2026-07 audit finding
13.1) — semantics (REPLACE/ADD/REMOVE/RESET) are unchanged.

---

### `ts variables remove`

Remove a variable value at org and/or user scope (value must match the current assignment).

```bash
ts variables remove <variable> <value> --profile <name> --org <org> [--org ...] [--user <username> ...]
```

Uses the same per-identifier endpoint as `ts variables set` (see above).

---

### `ts tableau signin`

Sign in to Tableau Server/Cloud and verify credentials.

```bash
ts tableau signin
ts tableau signin --profile "Tableau Cloud Prod"
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Tableau profile name (default: first profile in `~/.claude/tableau-profiles.json`) |

**Output:** JSON `{site_id, api_version, user_id}` on success.

---

### `ts tableau datasources`

List published datasources on the Tableau site.

```bash
ts tableau datasources
ts tableau datasources --name "Sales Data"
ts tableau datasources --profile "Tableau Cloud Prod"
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Tableau profile name |
| `--name`, `-n` | (none) | Exact datasource name filter |

**Output:** JSON array of datasource objects from the Tableau REST API. Auto-paginates — all
results are returned. When `--name` is given, uses a server-side exact-match filter.

---

### `ts tableau datasource <ID>`

Get details of a single datasource by UUID, optionally with field metadata.

```bash
ts tableau datasource abc-123-def
ts tableau datasource abc-123-def --fields
ts tableau datasource abc-123-def --profile "Tableau Cloud Prod"
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Tableau profile name |
| `--fields`, `-f` | false | Include VizQL field metadata via `POST /api/v1/vizql-data-service/read-metadata` |

**Output:** JSON datasource object. When `--fields` is given, a `fields` key is added to the
response containing the VizQL field list.

---

### `ts tableau download <ID>`

Download a published datasource's content (TDSX archive) and extract data files.
Validates CSV files for row integrity (column count consistency, corrupt lines).

```bash
ts tableau download abc-123-def
ts tableau download abc-123-def --output-dir ./data
ts tableau download abc-123-def --profile "Tableau Cloud Prod"
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Tableau profile name |
| `--output-dir`, `-o` | `.` | Directory to save downloaded content |

**Output:** JSON object with keys:

| Key | Description |
|---|---|
| `tdsx_path` | Path to the downloaded TDSX file |
| `extracted_dir` | Path to the extracted archive directory |
| `files` | List of all files in the archive |
| `data_files` | List of data files (CSV, Hyper) with validation results |

Each CSV in `data_files` includes a `validation` object:

```json
{
  "total_lines": 201,
  "data_rows": 200,
  "header_columns": 10,
  "corrupt_lines": [{"line": 40, "expected_columns": 10, "actual_columns": 1, "content": "1tou"}],
  "is_valid": false
}
```

---

### `ts tableau parse`

Parse a `.twb`/`.twbx` file into structured JSON — tables, columns, joins,
calculated fields, parameters, the data-blend graph, a derived blend model-grouping
plan, table-calc addressing, and per-datasource orphan-calc detection. This is the
Step 3 entry point for the `ts-convert-from-tableau` skill: read this JSON instead
of hand-parsing the TWB XML.

```bash
ts tableau parse "workbook.twbx" --output parsed.json
```

**Options:**

| Flag | Required | Description |
|---|---|---|
| `twb_file` (arg) | yes | Path to `.twb` or `.twbx` file |
| `--output`, `-o` | yes | Output path for the parsed JSON |

**Output file:**

```json
{
  "datasources": [
    {
      "name": "...", "tables": [...], "columns": [...], "joins": [...],
      "calculated_fields": [...], "calc_map": {...}, "col_table_map": {...},
      "orphan_calcs": ["Caption1", "..."]
    }
  ],
  "parameters": [...],
  "param_map": {...},
  "blends": {"source_ds_caption": [{"target_ds": "...", "column_mappings": [...]}]},
  "blend_plan": {
    "components": [{"primary": "...", "members": ["...", "..."]}],
    "ds_table_map": {"datasource_caption": "TABLE_NAME"},
    "joins": [{"with": "...", "table": "...", "on": "...", "type": "LEFT_OUTER",
               "cardinality": "MANY_TO_ONE"}]
  },
  "table_calc_addressing": {"column_level": {...}, "ws_overrides": {...}}
}
```

`orphan_calcs` (captions of calculated fields that reference a table missing from
their own datasource, direct + transitive), `blends` (the data-blend graph keyed by
datasource caption), and `table_calc_addressing` (column-level + worksheet-override
`<table-calc>` sort context) are computed by the pure extractors in
`ts_cli/tableau/twb.py` (`detect_orphan_calcs`, `extract_blends`,
`extract_table_calc_addressing`). `blend_plan` is derived from `blends` +
`datasources` by `build_blend_plan` (`ts_cli/tableau/build_model.py`) — connected
components, a datasource→table map, and the flattened join list for every blend
edge, ready for SKILL.md Step 5b to consume directly instead of re-deriving them by
hand. An all-empty shape (`{"components": [], "ds_table_map": {}, "joins": []}`) is
emitted when the workbook has no blends. Stdout is silent; a one-line summary goes
to stderr.

---

### `ts tableau translate-formulas`

Translate Tableau calculated fields to ThoughtSpot formula syntax. Reads the
classification JSON from the TWB parse, applies an ordered translation pipeline,
resolves cross-references via dependency DAG, and outputs formulas ready for TML
generation.

```bash
ts tableau translate-formulas \
  --input classification.json \
  --output formulas_translated.json \
  --datasource cpg_merch_promotion_prod \
  --table-columns table_columns.json \
  --parameters parameters.json \
  --param-map param_map.json \
  --calc-map calc_map.json \
  --csq-map csq_to_table.json \
  --date-columns START_DATE,END_DATE,SHIP_DATE
```

**Options:**

| Flag | Required | Description |
|---|---|---|
| `--input`, `-i` | yes | classification.json from TWB parse (Step 3 output) |
| `--output`, `-o` | yes | Output file for translated formulas JSON |
| `--datasource`, `-d` | no | Filter to a single datasource name |
| `--tables`, `-t` | no | Comma-separated table names for this model |
| `--table-columns` | no | JSON file mapping column name → table name (for scoping) |
| `--parameters` | no | JSON file with parameter definitions |
| `--param-map` | no | JSON file mapping internal param names → captions |
| `--calc-map` | no | JSON file mapping `[Calculation_NNN]` → caption |
| `--csq-map` | no | JSON file mapping Custom SQL Query aliases → table names |
| `--date-columns` | no | Comma-separated date column names for arithmetic rewrite |

**Input file formats:**

- `classification.json`: `[{caption, formula, datatype, role, datasource, tier, detail}]`
- `table_columns.json`: `{"COLUMN_NAME": "TABLE_NAME", ...}`
- `parameters.json`: `[{caption, name, ...}]`
- `param_map.json`: `{"Parameter 3 1": "Metric", ...}`
- `calc_map.json`: `{"[Calculation_123]": "Sales Total", ...}`
- `csq_to_table.json`: `{"Custom SQL Query8": "FORECAST", ...}`

**Output:** JSON file with:

```json
{
  "translated": [{"name": "...", "expr": "...", "column_type": "MEASURE", "level": 0}],
  "skipped": [{"name": "...", "reason": "...", "level": 1}],
  "stats": {"total": 163, "translated": 107, "skipped": 56, "levels": {"0": 107, "1": 56}}
}
```

**Translation pipeline (5 pre-transforms + 14 ordered steps):**

Pre-transforms (run first, in order):
- P0. Strip `//` line comments (preserve `//` inside string literals)
- P1. Rewrite Custom SQL Query aliases → `[TABLE::COL]`
- P2. No-keyword LOD `{AGG([col])}` → `group_aggregate(..., {}, query_filters())`
- P3. Scalar `MAX(a,b)` / `MIN(a,b)` → `if(a > b) then a else b`
- P4. Date arithmetic `DATE([col])+N` → `add_days(date([col]), N)`

Main pipeline:
1. Strip `[Parameters].[X]` → `[X]`
2. Map internal parameter names to captions
3. Resolve `[Calculation_*]` cross-references (dependency DAG, topological sort)
4. LOD expressions → `group_aggregate()`
5. `TOTAL()` → `group_aggregate(..., {}, query_filters())`
6. `CASE/WHEN` → `if/else if` chain
7. `IIF(test,a,b)` → `if(test) then a else b`
8. `IF/THEN/END` → `if()/then/else` (strip END, wrap conditions)
9. `INT()` → floor/ceil composite
10. Function mapping (ZN→ifnull, COUNTD→unique count, etc.)
11. Date functions (DATETRUNC→start_of_*, DATEDIFF→diff_*, etc.)
12. String concatenation (`+` → `concat()`)
13. Column scoping (`[COL]` → `[TABLE::COL]`)
14. Mandatory else clause (type-matched)

Stdout prints the stats summary JSON; the full result goes to `--output`.

---

### `ts tableau classify-formulas`

Classify Tableau calculated fields into translation tiers for the `ts-convert-from-tableau`
audit mode. The translatable/untranslatable verdict is delegated internally to
`translate_formulas` (the same pipeline `ts tableau translate-formulas` runs), so audit-mode
tier counts and migrate-mode translation results can never diverge — a formula tagged
translatable is guaranteed to appear in a `translate-formulas` run's `translated[]`, and vice
versa.

```bash
ts tableau classify-formulas --input parsed.json --output classification.json
ts tableau classify-formulas --input parsed.json --output classification.json --datasource "Orders"
```

**Options:**

| Flag | Required | Description |
|---|---|---|
| `--input`, `-i` | yes | `parsed.json` from `ts tableau parse`, or a bare JSON list of calc-field dicts |
| `--output`, `-o` | yes | Output path for the classification JSON |
| `--datasource`, `-d` | no | Limit to one datasource name (only applies when `--input` is a `parsed.json`) |

**Input:** when given a `parsed.json` (a dict with a `datasources` key), classifies **per
datasource** — each datasource becomes its own model in migration, and a calc *name* shared
across datasources can carry a *different* expression, so it is tiered against its own (no
cross-datasource name dedup). When given a bare JSON list, classifies it directly.

**Output** — per-datasource for a `parsed.json` input:

```json
{
  "datasources": [
    {
      "name": "Orders",
      "formulas": [
        {"name": "Revenue Growth %", "tier": "native", "reason": "", "level": 0, "complexity": 3}
      ],
      "tier_counts": {"native": 42, "lod": 5, "untranslatable": 2},
      "translate_stats": {"total": 49, "translated": 47, "skipped": 2, "levels": {"0": 47}}
    }
  ],
  "tier_counts": {"native": 42, "lod": 5, "untranslatable": 2}
}
```

Each datasource's `translate_stats` reconciles (`total == translated + skipped`); the
top-level `tier_counts` sums per-datasource counts (a shared name is counted once per
model). A **bare-list** input instead yields a flat `{formulas, tier_counts, translate_stats}`.

Translatable tiers: `native`, `lod`, `cumulative`, `moving`, `pass_through`,
`row_offset_native`, `parameter_ref`. Untranslatable tiers: `untranslatable`,
`row_offset_ambiguous`, `geospatial`, `circular`, `orphan`, `parameter_query`. Stdout prints
the `tier_counts` summary JSON; the full result goes to `--output`.

---

### `ts tableau build-model`

Parse a Tableau workbook and build import-ready ThoughtSpot model TML. Combines
TWB parsing, formula translation, name collision resolution, formula-prefix
application, double-aggregation detection, and phased import splitting into a
single deterministic pipeline.

```bash
ts tableau build-model "workbook.twbx" \
  --connection "MY_CONNECTION" \
  --output-dir ./output \
  --model-name "My Model" \
  --datasource "DS Name"
```

**Options:**

| Flag | Required | Description |
|---|---|---|
| `twb_file` (arg) | yes | Path to `.twb` or `.twbx` file |
| `--connection`, `-c` | yes | ThoughtSpot connection name |
| `--output-dir`, `-o` | no | Output directory (default: `.`) |
| `--model-name`, `-m` | no | Model name (default: derived from datasource name) |
| `--datasource`, `-d` | no | Filter to a single datasource |
| `--dry-run` | no | Report stats only — don't write files |
| `--table-name-map` | no | GENERATE mode only (no `--existing-guid`). Path to a JSON file mapping TWB physical table name → ThoughtSpot table TML `name`, for when they differ (warehouse-normalized names, sqlproxy/published-datasource scoping). Ignored (with a stderr note) when `--existing-guid` is set. |
| `--reconcile-table` | no | GUID of an existing ThoughtSpot table to reconcile emitted columns against (consultant/stand-in-view case). Requires `--profile`. |
| `--reconcile-plan` | no | With `--reconcile-table`: print the reconcile plan (suggested mappings + drops) as JSON and exit without writing TML. |
| `--column-name-map` | no | JSON file mapping datasource column → target column name (from the confirmed reconcile plan). Applies in GENERATE mode (with `--reconcile-table`, apply mode) and in MERGE mode (`--existing-guid`), where it rewrites re-derived formula refs so renamed columns resolve against the existing model. |

Column-id qualification and suffix/junk stripping (Tier-1 cleanup) run automatically on
every `build-model` call — the three flags above only add opt-in Tier-2 reconciliation
against a real target schema.

**Pipeline steps:**

1. Parse TWB XML — extract tables, columns, joins, calculated fields, parameters, **and Custom SQL relations** (`<relation type='text'>`)
2. Build dependency levels from raw calculated fields (before reference resolution)
3. Resolve all internal references (`[Calculation_NNN]` and copy-style `[Field (copy)_NNN]`)
4. Translate formulas to ThoughtSpot syntax (via `tableau_translate.py`, an orchestrator facade over the `ts_cli/tableau/` package — entry point unchanged)
5. Resolve name collisions (formula/param clashes → rename; column/formula clashes → drop column)
6. Build model TML with `formula_` prefix for cross-references and double-aggregation fix; **emit a `.sql_view.tml` per Custom SQL relation and reference it by name in `model_tables[]`** (physical/SQL-View column dedup applied)
7. Split into phased import files — **SQL Views first** (they must exist before the model), then phase 0 = base, then per dependency level

**Merge mode** (`--existing-guid`): merge translated formulas into an already-imported
model. This is the Phase 2 flow used by the Tableau migration skill:

```bash
ts tableau build-model "workbook.twbx" \
  --connection "MY_CONNECTION" \
  --existing-guid "d561cee7-ed26-4f79-b353-6a2dc26879d6" \
  --datasource "DS Name" \
  --profile se-thoughtspot \
  --max-retries 25
```

| Flag | Description |
|---|---|
| `--existing-guid`, `-g` | GUID of an already-imported model — exports it, merges formulas in, and re-imports |
| `--max-retries` | Max import retry iterations for formula errors (default: 25) |
| `--profile`, `-p` | ThoughtSpot profile for API calls |

**Sqlproxy remapping:** when the TWB uses published datasources (Tableau Server
`sqlproxy` tables), the parser sees synthetic table names like `"Custom SQL Query"`.
`build-model` automatically remaps these columns to the target ThoughtSpot table:

- **Single-table models**: all sqlproxy columns are force-mapped to the one table
- **Multi-table models**: columns are matched by name against all model tables

Unresolvable sqlproxy references and `Custom SQL Query` aliases are stripped from
formulas before import via `filter_unresolvable_formulas()`.

**Bare-reference resolution:** after sqlproxy remapping, a post-pass (`fix_bare_refs`)
table-qualifies bare `[Column]` references and prefixes `[FormulaName]` cross-references
with `formula_` to match ThoughtSpot's naming convention.

**Table name remapping (GENERATE mode only):** when generating a model from scratch
(no `--existing-guid`), there is no existing model to introspect for the real table
names — unlike the merge-flow sqlproxy remapping above. If the ThoughtSpot table was
created under a different name than the TWB relation (warehouse-normalized names, or a
published-datasource TWB where the relation is literally named `sqlproxy`), pass
`--table-name-map` with a JSON file `{"twb_table_name": "THOUGHTSPOT_TABLE_NAME"}`:

```bash
ts tableau build-model "workbook.twbx" \
  --connection "MY_CONNECTION" \
  --output-dir ./output \
  --datasource "DS Name" \
  --table-name-map ./table-name-map.json
```

```json
{"sqlproxy": "ORDERS_FACT_TS"}
```

The mapped name replaces the TWB table name everywhere it feeds the generated model
TML: `model.tables[].name` and `.fqn`, `model_tables[].name` and join `with`/`on`
endpoints, `columns[].column_id` table prefixes, and any `[TABLE::COL]` refs formula
translation embeds via column scoping. Tables absent from the map pass through
unchanged. Implemented by `apply_table_name_map()` in `ts_cli/tableau/build_model.py`.

**Output:** One set of phased TML files per datasource:

```
output/
  my_model.phase_0.model.tml    # Base: tables, columns, joins, params — no formulas
  my_model.phase_1.model.tml    # Level 0 formulas (no cross-refs)
  my_model.phase_2.model.tml    # + Level 1 formulas (reference level 0)
  ...
```

Stdout: JSON array with per-datasource stats (tables, columns, translated/skipped
formulas, rename map, phase count).

---

## Piping and scripting

All commands write JSON to stdout, making them easy to pipe into `jq` or Python:

```bash
# Get the GUID of a specific worksheet
ts metadata search --subtype WORKSHEET --name "%Retail%" \
  | jq -r '.[0].metadata_id'

# Export TML and extract the edoc string
ts tml export e61c7c4c-68a4-4174-b393-a0104ae3bd00 \
  | jq -r '.[0].edoc'

# Export and parse — get the model's formula list directly
ts tml export e61c7c4c-68a4-4174-b393-a0104ae3bd00 --fqn --parse \
  | jq '.[0].tml.model.formulas'

# Get all worksheet names
ts metadata search --subtype WORKSHEET --all \
  | jq -r '.[].metadata_name'
```

---

## `ts load` — Source data loading

### `ts load infer`

Infer table schemas from source data (CSV directory, Tableau download JSON, or manifest).

```
ts load infer --source <path>
```

**Options:**

| Flag | Description |
|---|---|
| `--source`, `-s` | Path to CSV directory, Tableau download JSON, or manifest JSON (required) |

**Output:** JSON with `source_type` and `tables[]` array containing `table_name`, `row_count`, and `columns[]` with `name`, `db_column_name`, `inferred_type`.

### `ts load generate`

Generate synthetic sample data from a schema definition.

```
ts load generate --source schema.json --rows 500 --output ./generated/
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--source`, `-s` | — | Path to schema JSON or `ts load infer` output (required) |
| `--rows`, `-r` | `100` | Number of rows per table |
| `--output`, `-o` | `.` | Directory to write generated CSV files |

**Output:** JSON array of `{table_name, rows, file}` per generated table.

### `ts load snowflake`

Load CSV data into Snowflake tables. Auth via Snowflake profile (`~/.claude/snowflake-profiles.json`).

```
ts load snowflake --source ./csvs/ --profile Production \
    --database AGENT_SKILLS --schema SALES
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--source`, `-s` | — | Path to CSV directory, download JSON, or manifest (required) |
| `--profile`, `-p` | — | Snowflake profile name (required) |
| `--database`, `-d` | — | Target database (required) |
| `--schema` | — | Target schema (required) |
| `--if-exists` | `error` | Action when table exists: `error`, `skip`, `replace` |
| `--warehouse`, `-w` | from profile | Snowflake warehouse override |
| `--role`, `-r` | from profile | Snowflake role override |
| `--generate-sample` | `false` | Generate synthetic data for schema-only sources |
| `--rows` | `100` | Rows to generate (with `--generate-sample`) |

**Output:** JSON with `database`, `schema`, `profile`, and `tables[]` array containing `table_name`, `status`, `rows_loaded`, `columns`, `source_file`.

### `ts snowflake diff`

Diff two Semantic-View-adjacent column maps and print a change set. Codifies the
Mode-C diff helper that both `ts-convert-to-snowflake-sv` and
`ts-convert-from-snowflake-sv` previously duplicated as inline Python (BL-063
codification quick win). No Snowflake or ThoughtSpot connection needed — pure local
comparison.

```bash
ts snowflake diff --current existing_sv_cols.json --new generated_sv_cols.json
```

`--current`/`--new` are JSON files shaped:

```json
{
  "COLUMN_NAME": {
    "expr": "SQL or ThoughtSpot formula text",
    "description": "optional",
    "synonyms": ["optional", "list"]
  }
}
```

`expr` is compared with a stash-then-normalise algorithm (`normalise_expr` /
`exprs_differ` in `ts_cli/snowflake_ops.py`) that survives whitespace/case
differences while preserving double-quoted SQL identifiers and ThoughtSpot
`[bracket]`/`{brace}` references verbatim — the same function works whether both
sides are SQL (to-side) or already-translated ThoughtSpot formula text (from-side).
Any SV-SQL-to-ThoughtSpot-formula translation must happen in the skill **before**
the column maps are written to these files — this command only compares whatever
expression text it is given, it never translates.

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--current` | — | Path to a JSON file describing the CURRENT column map (required) |
| `--new` | — | Path to a JSON file describing the NEW column map (required) |
| `--ignore-empty-new-description` | `false` | Only flag a description change when the NEW description is non-empty (from-side behaviour). Default flags any difference, including the new description going blank (to-side behaviour) |

**Output:** the change_set JSON to stdout —
`{new_columns, removed_columns, modified_expressions, modified_descriptions, modified_synonyms}`.
`modified_synonyms` is only populated for a column when BOTH sides supply a
`"synonyms"` key — a column map that never tracks synonyms naturally produces an
empty list. Diagnostic counts go to stderr.

```bash
ts snowflake diff --current model_cols.json --new sv_cols_translated.json \
  --ignore-empty-new-description
```

---

### `ts snowflake lint-ddl`

Lint a `CREATE SEMANTIC VIEW` DDL string for the deterministic subset of the
`ts-convert-to-snowflake-sv` Step 11 checklist — the structural checks with no
semantic judgment involved. No Snowflake or ThoughtSpot connection needed; pure
local structural check (parses `tables()`/`relationships()`/`dimensions()`/`metrics()`
via balanced-parenthesis scanning).

```bash
ts snowflake lint-ddl generated_sv.sql
cat generated_sv.sql | ts snowflake lint-ddl
```

Checks (see `agents/cli/ts-convert-to-snowflake-sv/SKILL.md` Step 11 for the full
15-item checklist — everything not in this table is intentionally left as a manual
review step, since it requires semantic judgment or a reserved-word list broad
enough to risk false positives):

| Check | Severity | What it catches |
|---|---|---|
| `identifier-format` | error | View name or a dimension/metric/table alias doesn't match `^[A-Za-z_][A-Za-z0-9_]*$` |
| `duplicate-alias` | error | The same dimension/metric alias declared more than once (aliases must be globally unique across the view) |
| `undeclared-table` | error | A table referenced in `relationships()`, `dimensions()`, or `metrics()` isn't declared in `tables()` |
| `metric-forward-reference` | error | A metric expression references another metric alias that isn't defined *earlier* in the `metrics()` clause |
| `untranslatable-placeholder` | error | Leftover `-- TODO` or `CAST(NULL AS TEXT)` placeholder text |
| `unescaped-comment-quote` | warning | A `comment='...'` value that looks like it has an unescaped embedded apostrophe (moderate-confidence heuristic) |

**Options:**

| Argument | Default | Description |
|---|---|---|
| `FILE` | stdin | Path to a `.sql` file containing the DDL. Reads stdin if omitted |

**Output:** a JSON array of findings to stdout —
`[{"severity": "error"|"warning", "check": "<slug>", "message": str, "detail": str}, ...]`.
A human-readable summary goes to stderr.

**Exit code** is `1` if any `error`-severity finding is present, else `0` — so it
composes with `&&` to gate on a clean lint before creating the view:

```bash
ts snowflake lint-ddl generated_sv.sql && echo "clean, proceeding"
```
