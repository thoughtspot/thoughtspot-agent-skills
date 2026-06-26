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

Search ThoughtSpot metadata objects.

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
| `--limit`, `-l` | 50 | Max results per page |
| `--offset` | 0 | Pagination offset |
| `--all` | false | Fetch all pages automatically |

**Examples:**

```bash
# All tables/worksheets/models (default type = LOGICAL_TABLE)
ts metadata search

# Worksheets and models only
ts metadata search --subtype WORKSHEET

# Search by name
ts metadata search --subtype WORKSHEET --name "%sales%"

# Search liveboards, all pages
ts metadata search --type LIVEBOARD --all

# Find by GUID
ts metadata search --guid e61c7c4c-68a4-4174-b393-a0104ae3bd00
```

**Output:** JSON array from `POST /api/rest/2.0/metadata/search`

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

Import TML objects. Reads a JSON array of TML strings from stdin.

```bash
# Import tables (PARTIAL — best-effort, tolerates partial failures)
echo '["table:\n  name: ..."]' | ts tml import --policy PARTIAL

# Import a model (ALL_OR_NONE — atomic, all succeed or nothing is created)
cat tmls.json | ts tml import --policy ALL_OR_NONE --profile champ-staging
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--policy` | `PARTIAL` | Import policy, passed through to the API: `PARTIAL`, `ALL_OR_NONE`, `PARTIAL_OBJECT`, or `VALIDATE_ONLY` (dry-run server-side validation) |
| `--create-new / --no-create-new` | `--no-create-new` | Create new objects. Default updates existing objects only; pass `--create-new` for brand-new TML with no existing GUID |

**Input (stdin):** JSON array of TML strings, e.g.:

```json
["table:\n  name: MY_TABLE\n  db: MY_DB\n  ..."]
```

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
# Lint the same payload you would import
cat tmls.json | ts tml lint

# Gate an import on a clean lint
cat tmls.json | ts tml lint && cat tmls.json | ts tml import --policy ALL_OR_NONE
```

**Input (stdin):** JSON string or array of TML strings — the same shape `ts tml import` reads.

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

### `ts orgs search`

List/search orgs.

```bash
ts orgs search --profile <name> [--status ACTIVE] [--name "%pattern%"] [--limit 200]
```

---

### `ts users search`

List/search users (by name or email).

```bash
ts users search --profile <name> [--name "%pattern%"] [--org <org> ...] [--status ACTIVE] [--limit 20]
```

---

### `ts users groups`

List/search user groups.

```bash
ts users groups --profile <name> [--name "%pattern%"] [--org <org> ...] [--include-users] [--limit 20]
```

---

### `ts variables search`

Show template variables and their assigned values (e.g. `ts_user_timezone`).

```bash
ts variables search [<variable>] --profile <name>      # omit <variable> for all
```

---

### `ts variables set`

Assign a variable value at org and/or user scope (used by `ts-variable-timezone`).

```bash
ts variables set <variable> <value> --profile <name> --org <org> [--org ...] [--user <username> ...]
# e.g. ts variables set ts_user_timezone "Australia/Sydney" --profile prod --org Primary
```

---

### `ts variables remove`

Remove a variable value at org and/or user scope (value must match the current assignment).

```bash
ts variables remove <variable> <value> --profile <name> --org <org> [--org ...] [--user <username> ...]
```

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
