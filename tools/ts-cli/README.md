# ThoughtSpot CLI (`ts`)

A lightweight Python CLI wrapping the ThoughtSpot REST API. Used at runtime by
Claude Code skills to authenticate, search metadata, and export/import TML.

---

## Installation

```bash
pip install -e /path/to/thoughtspot-skills/tools/ts-cli
```

After install, the `ts` command is available on your PATH.

---

## Authentication & profiles

The CLI resolves which profile to use in this order:

1. `--profile <name>` flag on the command
2. `TS_PROFILE` environment variable
3. First profile in `~/.claude/thoughtspot-profiles.json`

Profiles are created and managed by the `thoughtspot-setup` Claude Code skill.
Credentials are stored in the macOS Keychain — never in the profile file itself.

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
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--fqn` | false | Include fully-qualified names in output |
| `--associated` | false | Export associated objects (e.g. tables for a worksheet) |
| `--format`, `-f` | `YAML` | Output format: `YAML` or `JSON` |

**Output:** JSON array from `POST /api/rest/2.0/metadata/tml/export`. Each element
contains `info` (metadata) and `edoc` (the TML string).

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

**Note:** Using `--associated` on a worksheet exports the worksheet plus all
referenced tables. For example, `--fqn --associated` on `Retail Sales WS`
returned 4 objects: 1 worksheet + 3 tables (`DIM_RETAPP_STORES`,
`FACT_RETAPP_SALES`, `DIM_RETAPP_PRODUCTS`).

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
| `--policy` | `PARTIAL` | Import policy: `PARTIAL` or `ALL_OR_NONE` |
| `--create-new / --no-create-new` | `--create-new` | Create new objects if they don't exist |

**Input (stdin):** JSON array of TML strings, e.g.:

```json
["table:\n  name: MY_TABLE\n  db: MY_DB\n  ..."]
```

**Output:** JSON from `POST /api/rest/2.0/metadata/tml/import` containing
per-object status and GUIDs of created/updated objects.

---

### `ts connections list`

List available data connections.

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

### `ts connections get <connection-id>`

Fetch full connection details including the database/schema/table/column hierarchy.

```bash
ts connections get 1f428ed0-c672-435d-a7e1-b4781e5f492c
```

**Output:** Raw JSON from `POST /tspublic/v1/connection/fetchConnection`.

> **Note:** This command uses the v1 API endpoint as no v2 equivalent that returns
> the full table/column hierarchy has been confirmed yet. It requires the
> `CAN_CREATE_OR_EDIT_CONNECTIONS` privilege and may return a 500 error on some
> ThoughtSpot instances. Update this command once a v2 fetch endpoint is confirmed
> in the REST Playground.

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

## Piping and scripting

All commands write JSON to stdout, making them easy to pipe into `jq` or Python:

```bash
# Get the GUID of a specific worksheet
ts metadata search --subtype WORKSHEET --name "%Retail%" \
  | jq -r '.[0].metadata_id'

# Export TML and extract the edoc string
ts tml export e61c7c4c-68a4-4174-b393-a0104ae3bd00 \
  | jq -r '.[0].edoc'

# Get all worksheet names
ts metadata search --subtype WORKSHEET --all \
  | jq -r '.[].metadata_name'
```
