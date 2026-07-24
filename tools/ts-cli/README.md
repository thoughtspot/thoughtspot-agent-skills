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
ts profiles list --snowflake
ts profiles list --tableau
ts profiles list --databricks
ts profiles list --json
ts profiles list --snowflake --json
```

**Output (table):**

```
  champ-staging         token         https://champagne-master-aws.thoughtspotstaging.cloud
```

**Output (`--json`):** JSON array with credential fields stripped.

---

### `ts profiles add`

Add or replace a profile. Derives slug, env var name, and keychain commands.
The credential value is NEVER passed through this command.

```bash
ts profiles add \
  --platform thoughtspot \
  --name "My Staging" \
  --auth-type token \
  --field base_url=https://my.thoughtspot.cloud \
  --field username=admin@example.com
```

**Output:** JSON with `profile`, `slug`, `env_var`, `keychain_store_commands`, `zshenv_line`.

---

### `ts profiles update`

Update fields on an existing profile.

```bash
ts profiles update \
  --platform thoughtspot \
  --name "My Staging" \
  --field base_url=https://new.thoughtspot.cloud
```

---

### `ts profiles remove`

Remove a profile and report cleanup info.

```bash
ts profiles remove --platform snowflake --name "Partner AP"
```

**Output:** JSON with `removed` profile, `keychain_service`, `env_var_to_remove`.

---

### `ts profiles sync-env`

Regenerate ~/.zshenv export lines from all configured profiles.

```bash
ts profiles sync-env
ts profiles sync-env --platform snowflake
```

**Output:** JSON with `lines` array — each entry has `platform`, `name`, `env_var`, `line`.

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
| `--connection`, `-c` | (none) | Scope results to one connection by display name (client-side, case-insensitive match on `metadata_header.dataSourceName`). Objects not scoped to a connection (worksheets/models) are excluded when set. |
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

# Scope to a single connection (client-side dataSourceName filter)
ts metadata search --connection "Snowflake Prod"
ts metadata search --connection "Snowflake Prod" --name "%DIM%"

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
ts metadata delete abc-123 stale-guid --ignore-missing
ts metadata delete abc-123 --profile se-thoughtspot
```

A batch delete is atomic — if any one GUID is already gone the whole call
fails and nothing is deleted. This command tries the batch first (one fast
call when every GUID is present) and, on failure, falls back to per-GUID
deletes so present objects are still removed, reporting a per-object outcome
map. Useful for teardown/cleanup where some GUIDs may already be gone.

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | `LOGICAL_TABLE` | Object type: `LOGICAL_TABLE`, `LIVEBOARD`, `ANSWER` |
| `--ignore-missing` | off | Treat already-gone GUIDs (`not_found`) as success instead of exiting non-zero. Genuine errors still exit non-zero. |

**Output:** `{"deleted": [...], "not_found": [...], "errors": {guid: msg}, "outcomes": {guid: "deleted"|"not_found"|"error: ..."}}`.
Exits non-zero if any GUID could not be deleted, unless the only failures are
`not_found` and `--ignore-missing` is set.

---

### `ts model promote-formula`

Promote formulas from an Answer into a Model. Exports both TMLs, detects
duplicate formula names, maps column references, infers column_type
(MEASURE/ATTRIBUTE), and emits the merged Model TML ready for import.

```bash
ts model promote-formula --answer <answer-guid> --model <model-guid> --profile <name>

# Promote specific formulas only
ts model promote-formula -a <answer-guid> -m <model-guid> --formula "Profit Margin" --formula "YoY Growth"

# Overwrite duplicates instead of skipping
ts model promote-formula -a <answer-guid> -m <model-guid> --duplicates overwrite

# Include auto-generated formulas (excluded by default)
ts model promote-formula -a <answer-guid> -m <model-guid> --all --include-auto
```

**Output:** JSON with `added`, `skipped`, `overwritten`, `unresolved_refs`, `params_added`,
`deps_added`, and `merged_tml_yaml` (the full merged Model TML string ready for `ts tml import`).

| Flag | Default | Description |
|---|---|---|
| `--answer`, `-a` | required | Answer GUID — source of the formulas |
| `--model`, `-m` | required | Model GUID — target to merge formulas into |
| `--profile`, `-p` | first profile | Profile to use |
| `--formula` | all non-auto | Formula names to promote (repeatable). Omit for all. |
| `--all` | false | Promote all formulas (equivalent to omitting `--formula`) |
| `--duplicates`, `-d` | `skip` | `skip` or `overwrite` — what to do when a formula name already exists |
| `--include-auto` | false | Include auto-generated formulas (`was_auto_generated=true`) |
| `--include-params/--no-params` | true | Auto-include referenced parameters |
| `--include-deps/--no-deps` | true | Auto-include unselected formula dependencies |

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
| XREF | a model `model_tables`/`column_id`/join reference to a table or column that no batch TML generates — surfaces only when a table/sql_view TML is linted **alongside** the model (e.g. `--dir`); a lone model file skips it (no ground truth for what tables exist) |

```bash
# Lint a single file (model invariants only)
ts tml lint --file model.tml

# Lint every TML file in a directory — also runs the XREF cross-reference
# check, since tables + model are present together
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

### `ts dependency mutate` / `backup` / `rollback` / `apply-change`

BL-083: codifies the `ts-dependency-manager` skill's safety-critical REMOVE/REPOINT
engine — TML backup (Step 7), the mutation transforms (Step 9), rollback (Step 11),
and the destructive drift→delete→fix→source→set orchestrator (Step 9,
`apply-change`) — out of inline SKILL.md pseudocode into deterministic, tested Python.
Pure logic lives in `ts_cli/dependency/mutate.py` (`apply_remove`/`apply_repoint` +
`remove_columns_from_*`/`repoint_*`), `ts_cli/dependency/backup.py`
(filename/ordering/manifest), and `ts_cli/dependency/apply.py`
(drift/obj_id/outcome-matrix/verify/ordering/set-guard/chart-role decisions); this
command group is the I/O shell.

#### `ts dependency mutate`

PURE transform — no network. Applies a REMOVE or REPOINT mutation to one parsed TML
document.

```bash
ts dependency mutate --operation remove --file answer.json --remove-columns "Revenue,Cost"

ts tml export abc-123 --fqn --parse | jq '.[0]' \
  | ts dependency mutate --operation repoint \
      --source-guid abc-123 --target-guid def-456 --target-name "New Model" \
      --column-gap "Legacy Col"
```

**Input:** one TML doc from `--file` or stdin — either a bare TML body (`{"answer":
{...}}`, `{"model": {...}}`, ...) or a `ts tml export --parse` item
(`{"type": ..., "guid": ..., "tml": {...}, "info": {...}}`, auto-unwrapped).

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--operation` | — | `remove` or `repoint` (required) |
| `--file` | stdin | Path to a JSON TML doc |
| `--remove-columns` | — | Comma-separated column names (required for `remove`) |
| `--source-guid` | — | Source object GUID (fqn match / liveboard viz scoping) |
| `--target-guid` | — | Target object GUID (required for `repoint`) |
| `--target-name` | — | Target object display name (required for `repoint`) |
| `--column-gap` | — | Comma-separated columns present on the source but absent on the target — stripped from the repointed object same as `remove` |
| `--source-obj-id` / `--target-obj-id` | — | obj_id references, preferred over guid/fqn matching when present (avoids VERSION_CONFLICT / error 14009) |
| `--viz-decision` | — | Repeatable `viz_id=convert\|remove` — per-visualization decision for a liveboard `remove` where the viz's chart uses the removed column. Default for any viz not listed: `convert` |

**Output:** the mutated TML doc as JSON to stdout; brief diagnostics to stderr. The
result still needs to be serialized to YAML and imported via `ts tml import` — that
wiring is the calling skill's job.

#### `ts dependency backup`

Back up TML for a source object and its fix/delete dependents before a mutation run
(SKILL.md Step 7). Reads a plan JSON on stdin:

```bash
echo '{
  "operation": "REMOVE",
  "source": {"guid": "abc-123", "type": "MODEL", "name": "Orders Model"},
  "fix":    [{"guid": "def-456", "type": "ANSWER", "name": "Revenue by Region"}],
  "delete": [{"guid": "ghi-789", "type": "LIVEBOARD", "name": "Old LB"}],
  "out_dir": "/tmp"
}' | ts dependency backup --profile prod
```

Exports every object's TML the same way `ts tml export --parse` does. **All exports
are collected in memory first** — files are written only if every export succeeds.
If ANY export fails, the command aborts non-zero with a clear message and writes
NOTHING (no partial backup directory).

**Output:** the `manifest.json` contents as JSON to stdout (also written to
`{out_dir}/ts_dep_backup_<timestamp>/manifest.json`, alongside one
`{type}_{guid}_{name}.json` file per backed-up object). Backup dir path + counts go
to stderr.

#### `ts dependency rollback`

Restore from a `ts dependency backup` directory (SKILL.md Step 11).

```bash
ts dependency rollback --backup-dir /tmp/ts_dep_backup_20260704_120000 --profile prod
ts dependency rollback --backup-dir /tmp/ts_dep_backup_20260704_120000 --only deletes
```

Restores entries in dependency-safe order (dependents before source). An entry with
`intent == "DELETE"` is re-imported with `create_new=True` and its `guid:` stripped
(the object no longer exists at that GUID, so ThoughtSpot assigns a new one); every
other entry is updated in place at its original GUID.

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--backup-dir` | — | Backup directory containing `manifest.json` (required) |
| `--guid` | all | Restrict rollback to these GUID(s) (repeatable) |
| `--only` | `all` | `updates` \| `deletes` \| `all` |

**Output:** `{"succeeded": [...], "failed": [...], "new_guids": {old_guid: new_guid}}`
to stdout. `new_guids` lets the caller surface a GUID-remap table for any restored
delete — other objects that referenced the ORIGINAL guid remain broken and need
manual reattachment. Per-object progress goes to stderr.

#### `ts dependency apply-change`

The destructive orchestrator (SKILL.md Step 9). Reads a plan JSON on stdin and runs
the whole change end-to-end: **deletes → dependent fixes → source → set deletes**,
with a per-object drift check, obj_id-first repointing, and post-import verification
(open-item #15: TS can return `ERROR` while the change actually applied). A prior
`ts dependency backup` is **required** — pass its directory as `backup_dir`.

```bash
echo '{
  "operation": "REMOVE",
  "backup_dir": "/tmp/ts_dep_backup_20260708_120000",
  "source": {"guid": "abc-123", "type": "MODEL", "name": "Orders Model", "modified_at": 1714123456000},
  "columns_to_remove": ["Legacy Region"],
  "fix":    [{"guid": "def-456", "type": "ANSWER", "name": "Rev by Region", "modified_at": 1714100000000}],
  "delete": [{"guid": "ghi-789", "type": "ANSWER", "name": "Old Answer", "modified_at": 1714000000000}],
  "sets":   []
}' | ts dependency apply-change --profile prod
```

**Execution order — source LAST.** TS error 14544 ("Deleted columns have dependents")
rejects the source column removal while any dependent still references it, so
dependents are fixed first and the source last (SKILL.md overview). This corrects the
order the SKILL's Step 9 *section bodies* previously used (source-first).

**Per-object drift check.** Each object's `metadata_header.modified` is re-queried and
compared to the plan's `modified_at` snapshot; a moved (or unqueryable) object is
skipped — except the **source**, whose drift is a hard stop that aborts the whole run
(exit 1) before anything is changed.

**Plan fields:** `operation` (`REMOVE`/`REPOINT`), `backup_dir` (required),
`source`, `columns_to_remove` (REMOVE), `target`+`column_gap`+`source_obj_id`
(REPOINT), `fix[]` (each may carry `action`=`REMOVE_CHART`, per-viz `viz_decisions`,
or inline `tml` — required for FEEDBACK, which can't be exported standalone), `delete[]`,
`sets[]` (deleted only if every consumer fix succeeded).

**Output:** a results JSON to stdout
(`{"operation","source","succeeded","failed","deleted","skipped"}` — the data behind
the Step 10 Change Report). Per-object progress goes to stderr. Exits non-zero only on
source drift.

---

### `ts connections list`

List all available data connections. Results are auto-paginated — all connections
are returned regardless of how many exist on the instance. **Lists every warehouse type
by default** (Snowflake, Databricks, BigQuery, …); pass `--type` to filter to one.

```bash
ts connections list                      # ALL types
ts connections list --type DATABRICKS    # filter to one type
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--profile`, `-p` | first profile | Profile to use |
| `--type`, `-t` | _(none — all types)_ | Optional data warehouse type filter (e.g. `SNOWFLAKE`, `DATABRICKS`) |

> **Org scope:** connections (and metadata) are org-scoped. To operate in a non-default
> org, set `TS_ORG=<org_id>` (integer org id) — the CLI mints an org-scoped token
> (`org_id` on `auth/token/full`) with an org-keyed token cache. Without it, calls run in
> your default org.

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

**Options:**

| Flag | Description |
|---|---|
| `--auth-type` | Connection authentication type (e.g. `SERVICE_ACCOUNT`, `KEY_PAIR`, `OAUTH`). Auto-detected from the connection when possible; use this flag to override or when auto-detection fails. |

**How it works:**

1. Fetches the current connection state via v2 `connection/search`
2. Merges the new tables in — existing tables and columns are preserved
3. New columns are appended to existing tables; existing columns are left unchanged
4. Includes `authenticationType` in the update payload (auto-detected or via `--auth-type`)
5. Posts the merged result to `POST /api/rest/2.0/connections/{id}/update`

**Output:** JSON response from the update call.

> **Note:** The v2 update endpoint defaults to `SERVICE_ACCOUNT` if
> `authenticationType` is omitted — silently breaking non-SERVICE_ACCOUNT
> connections (e.g. KEY_PAIR, OAUTH). Pass `--auth-type` explicitly if
> auto-detection does not work for your connection. Requires
> `CAN_CREATE_OR_EDIT_CONNECTIONS` privilege.

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
- `data_type` — one of: `INT64`, `DOUBLE`, `VARCHAR`, `DATE`, `DATE_TIME`, `BOOL`.
  `BOOLEAN` is accepted too and normalized to `BOOL` — the live import API rejects
  `BOOLEAN` with `"Data type BOOLEAN is not valid for column ..."` (verified 2026-07-10)
- `column_type` — `ATTRIBUTE` (default) or `MEASURE` (adds `aggregation: SUM`)

**Output:** JSON object mapping table name → GUID for all successfully created tables.
Tables that failed after all retries are included with `null` as the GUID.

```json
{"FACT_SALES": "b1e360c4-d571-490f-bae2-e8dc7443c9fa"}
```

**How it works:**
1. Tables are imported in batches of up to 50 per API call (`PARTIAL` policy)
2. Tables that fail with transient JDBC errors are retried individually
3. GUIDs are resolved from the import response, falling back to a connection-scoped
   metadata search (`metadata_header.dataSourceName == connection_name`) when absent
4. Specs with `rls_rules` are handled in two passes: pass 1 creates the table without
   RLS; pass 2 re-imports with RLS rules + GUID (self-referencing rules can't resolve
   before the table exists)

---

### `ts spotql generate-sql` / `ts spotql fetch-data`

Run AgentQL (Semantic SQL) against a ThoughtSpot Model. The caller supplies the AgentQL
statement and the Model's GUID — these commands do **not** do natural-language → AgentQL.

- `generate-sql` validates the statement and returns the warehouse SQL it compiles to
  (does not execute).
- `fetch-data` executes the statement and returns result rows.

```bash
ts spotql generate-sql '<AgentQL>' --model <model-guid> --profile <name>
ts spotql fetch-data   '<AgentQL>' --model <model-guid> --profile <name>
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

`columns` are `{index, type}` — AgentQL returns per-query column GUIDs (not stable names),
so the SELECT ordinal is the usable identifier. A query that is rejected or fails to
execute returns a non-`SUCCESS` `status` with a populated `errors[]` (and exit code 0) —
these are structured query errors, not transport failures.

> **AgentQL requires an external cloud data warehouse.** The endpoints only support Models
> backed by an external CDW (Snowflake, Databricks, BigQuery, …). A Model over Falcon /
> imported / system data (`DEFAULT` datasource) returns
> `"This API only supports external cloud data warehouses"`.

---

### `ts spotql classify-columns`

Classify ThoughtSpot columns/formula expressions as attribute vs. measure vs.
aggregate-formula-measure — the decision that drives `SUM`-vs-`AGG` in AgentQL and the
MEASURE/ATTRIBUTE + aggregation inference when promoting Answer formulas to a Model.
Codifies BL-087: this was previously two DIFFERENT, drifted keyword lists duplicated
between `ts-object-model-agentql-query` and `ts-object-answer-promote`; both skills now
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

- `--model` mode → array of `{name, column_type, kind, needs_agg, aggregation, wrapper}`
  — one entry per `model.columns[]` entry. `wrapper` is the directly-actionable output —
  the AgentQL function to wrap the column reference in (`None` for attributes). `kind` is
  `"attribute"`, `"raw_measure"`, `"aggregate_measure"`, or `"semiadditive_measure"`:
  - `"aggregate_measure"` (equivalently `needs_agg: true`, `wrapper: "AGG"`) — wrap in
    `AGG(...)`; a real aggregate errors `NESTED_AGGREGATE_NOT_SUPPORTED`.
  - `"semiadditive_measure"` (`wrapper: "SUM"`) — an aggregate-formula whose **outermost**
    call is `last_value`/`first_value` (the `last_value(sum(col), query_groups(), {date})`
    snapshot form). Inverts the rule: wrap in `SUM(...)`; `AGG(...)` errors
    `NON_CONVERTIBLE_FUNCTION`. `sum(last_value(...))` (additive outer op) is NOT this — it
    stays `aggregate_measure`.
  - `"raw_measure"` (`wrapper: "SUM"`) — a real aggregate (`aggregation` names which —
    `SUM`/`AVG`/…).
  - `"attribute"` — group by it.
- `--exprs-file`/stdin mode → array of `{name, column_type, aggregation, is_aggregate}` —
  `column_type` is `MEASURE` iff the expression contains a call to an aggregate function
  (`sum`, `count`, `group_aggregate`, `last_value`, …), else `ATTRIBUTE`; `aggregation` is
  `SUM` for every MEASURE (ThoughtSpot ignores the `aggregation` property on formula
  columns at query time — the expr is self-contained), `null` for an ATTRIBUTE.

Diagnostic counts go to stderr. The canonical aggregate-function list lives in
`ts_cli.spotql_ops.AGGREGATE_FUNCS` — a single source of truth, not duplicated in either
skill's SKILL.md.

---

### `ts spotter answer`

Ask Spotter (ThoughtSpot AI) a single natural-language question over a Model and return
its answer — crucially the **search tokens** Spotter chose. Wraps the V2 endpoint
`POST /api/rest/2.0/ai/answer/create` (`singleAnswer`, Beta / 10.4.0.cl+). This is the
"Spotter last-mile" the conversion skills use: after a model is built, a measure that
could not be translated deterministically is phrased in plain English, handed to Spotter,
and the returned tokens are shown to a human to verify against the source numbers before
being flagged or adopted.

```bash
ts spotter answer "total sales by region last quarter" --model <model-guid> --profile <name>
ts spotter answer "count of distinct customers this year" -m <model-guid>
```

**Output (JSON to stdout):** `{status, message_type, visualization_type,
session_identifier, generation_number, tokens, display_tokens, errors}`.

- `tokens` / `display_tokens` — the ThoughtSpot Search expression Spotter produced (the
  field the last-mile workflow inspects). `display_tokens` is the human-friendly form.
- `status` is `SUCCESS` when an answer was returned, else an error code with a populated
  `errors[]`: `FORBIDDEN` (missing `CAN_USE_SPOTTER` privilege or no view access to the
  Model), `UNAUTHORIZED` (bad/expired token), or `SPOTTER_ERROR` (Spotter could not answer,
  or is not enabled on the cluster).

Requires `CAN_USE_SPOTTER` and view access to the target Model, and Spotter enabled on the
cluster. Diagnostics go to stderr; the JSON goes to stdout.

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
| `--database`, `-D` | no | GENERATE mode only. Warehouse database for the emitted Table TML(s) `db` field. Empty is fine for offline emission + local `ts tml lint`. (Short flag is `-D`, not `-d` — `-d` is already `--datasource`.) |
| `--schema`, `-s` | no | GENERATE mode only. Warehouse schema for the emitted Table TML(s) `schema` field. Empty is fine for offline emission + local `ts tml lint`. |
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
8. **GENERATE mode only** — emit one `.table.tml` per physical table (see "Table TML emission" below)

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

**Table TML emission (GENERATE mode only):** alongside the phased model TML,
`build-model` also writes a `.table.tml` per physical table, so the output directory
is import-ready and `ts tml lint --dir` can check model↔table cross-references — no
hand-assembly needed. `--database`/`-D` and `--schema`/`-s` set the emitted table(s)'
`db`/`schema` fields (empty is fine for offline emission + local lint; a later live
import supplies the real values).

- **Single-table datasources** (the common case): one `.table.tml` carrying every
  physical column.
- **Multi-table datasources**: one `.table.tml` per table, with columns assigned to
  their owning table. A column whose table ownership can't be resolved from the parse
  is left off every table and reported in the result JSON's `table_columns_unassigned`
  (plus a stderr warning) rather than guessed onto an arbitrary table — reconcile these
  manually before import.

Not emitted in `--dry-run` (stats only, no files written) or `--existing-guid` merge mode.

**Output:** One set of phased TML files per datasource, plus one `.table.tml` per
physical table (GENERATE mode):

```
output/
  my_model.phase_0.model.tml    # Base: tables, columns, joins, params — no formulas
  my_model.phase_1.model.tml    # Level 0 formulas (no cross-refs)
  my_model.phase_2.model.tml    # + Level 1 formulas (reference level 0)
  ...
  orders.table.tml              # GENERATE mode: one per physical table
  customers.table.tml
```

Stdout: JSON array with per-datasource stats (tables, columns, translated/skipped
formulas, rename map, phase count) plus, in GENERATE mode, `table_files` (paths
written), `tables_written` (count), and — for multi-table datasources only —
`table_columns_unassigned` (columns whose owning table couldn't be resolved).

---

### `ts aggregate signatures` / `recommend` / `profile` / `history` / `generate`

The aggregate-model advisor for the `ts-object-model-aggregates` skill (planned):
mines a Model's dependent Answers/Liveboards into query "signatures", generates and
ranks candidate aggregate grains, optionally profiles/reweights them against a live
Snowflake warehouse, and emits the DDL + TML to create one approved aggregate. Each
step writes to a shared working directory so the pipeline can be resumed or re-run
independently. Pure logic lives in `ts_cli/aggregate/` (`signatures.py`,
`measures.py`, `lattice.py`, `scoring.py`, `sqlgen.py`, `generate.py`, `history.py`);
this command group is the I/O shell.

#### `ts aggregate signatures`

Export the primary Model and its Answer/Liveboard dependents, and extract query
signatures (grouping columns, filters, date bucket) from each.

```bash
ts aggregate signatures --model abc-123 --out /tmp/agg --profile prod
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--model` | — | Primary Model GUID (required) |
| `--profile` / `-p` | `TS_PROFILE` env var | ThoughtSpot profile |
| `--out` | — | Output directory (required) |

**Output:** writes `<out>/model.tml.yaml` and `<out>/signatures.jsonl`. Stdout JSON:
`{"model_guid", "signatures", "full", "partial", "dependents", "export_failures"}` —
`partial` counts signatures whose source query couldn't be fully parsed;
`export_failures` counts dependents that failed to export (skipped, not fatal).

#### `ts aggregate recommend`

Generate candidate aggregate grains from the signatures and rank them with a
greedy marginal-gain selection.

```bash
ts aggregate recommend --dir /tmp/agg --max-select 10
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--dir` | — | Directory from `signatures` (required) |
| `--weights` | — | `weights.json` produced by `history`, to reweight signatures by observed query volume |
| `--base-rows` | — | Base (unaggregated) row count, enables cost-mode selection once at least one candidate is profiled |
| `--max-select` | `10` | Maximum number of candidates to select |
| `--tables-dir` | `<dir>/tables` | Directory of exported Table TMLs (Step 3's `<NAME>.tml.yaml` per `model_tables` entry) — read to detect base-table row-level security and surface per-candidate conflicts. A missing/empty directory is a no-op. |

**Output:** writes/updates `<dir>/candidates.json`. Stdout JSON: `{"mode",
"selected", "curve", "candidates", "excluded_unprofiled", "rls_conflicts"}` — `mode` is
`"cost"` once profiling data exists, else `"coverage"`; `excluded_unprofiled` lists
candidate ids skipped from cost-mode ranking because they have no `agg_rows` yet;
`rls_conflicts` (Task 23) lists candidate ids whose grain omits a base-table RLS filter
column — each also carries `rls: {required, missing}` + `rls_conflict: true` in
`candidates.json`; empty when no base table carries RLS at all.

#### `ts aggregate profile`

Measure base and per-candidate row counts, in connected or manual mode.

```bash
ts aggregate profile --dir /tmp/agg --tables-dir /tmp/agg/tables \
  --snowflake-profile my-sf --top-k 10

ts aggregate profile --dir /tmp/agg --tables-dir /tmp/agg/tables \
  --emit-sql /tmp/agg/profile.sql
ts aggregate profile --dir /tmp/agg --tables-dir /tmp/agg/tables \
  --results /tmp/agg/manual_counts.json
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--dir` | — | Directory from `signatures`/`recommend` (required) |
| `--tables-dir` | — | Directory of exported Table TMLs, one `<NAME>.tml.yaml` per `model_tables` entry (required) |
| `--snowflake-profile` | — | Connected mode: profile directly via a `ts-profile-snowflake` profile |
| `--emit-sql` | — | Manual mode: write a numbered profiling SQL script here instead of connecting |
| `--results` | — | Manual mode: ingest `{"base_rows": N, "candidates": {"cand_1": rows, ...}}` from a manual profiling run |
| `--top-k` | `10` | Profile only the top-K candidates by coverage |
| `--dialect` | `snowflake` | SQL dialect for generated statements |
| `--warehouse` | profile's `default_warehouse` | Connected mode: Snowflake warehouse |
| `--role` | profile's `default_role` | Connected mode: Snowflake role |
| `--model-guid` | — | Primary Model GUID — enables AgentQL-based profiling SQL per candidate (ThoughtSpot resolves joins correctly on role-playing/ambiguous-path dimensions; the built-in join walker can be wrong there). Omit to always use the built-in walker (pre-Task-18 default; no ThoughtSpot connection needed). |
| `--profile` / `-p` | `TS_PROFILE` env var | ThoughtSpot profile — used with `--model-guid` to call `ts spotql generate-sql`. Ignored if `--model-guid` is omitted. |
| `--no-spotql` | `false` | Even with `--model-guid`, use the built-in join walker directly |

The three modes are mutually exclusive: `--results` ingests, `--emit-sql` writes a
script (no connection), otherwise `--snowflake-profile` connects and profiles
directly. Each candidate's profiling SQL prefers AgentQL when `--model-guid` is
given (falling back to the built-in join walker on any failure); the base-row
count is always a plain single-table count either way. Candidates whose SELECT
can't be built deterministically by either path are skipped (reported, not
fatal) — the skill falls back to manual SQL for those.

**Output:** writes `agg_rows`/`base_rows` back into `<dir>/candidates.json`. Stdout
JSON varies by mode (`emitted`/`skipped`, `ingested`, or `base_rows`/`profiled`/`skipped`).

#### `ts aggregate history`

Mine Snowflake `QUERY_HISTORY` for the physical tables behind a Model into
signature weights, reflecting actual query volume rather than assuming every
dependent is queried equally.

```bash
ts aggregate history --dir /tmp/agg --snowflake-profile my-sf \
  --tables "SALES_FACT,DIM_CUSTOMER" --days 30
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--dir` | — | Directory from `signatures` (required) |
| `--snowflake-profile` | — | `ts-profile-snowflake` profile (required) |
| `--tables` | — | Comma-separated physical table names to match in query history (required) |
| `--days` | `30` | Lookback window in days |
| `--warehouse` | profile's `default_warehouse` | Snowflake warehouse |
| `--role` | profile's `default_role` | Snowflake role |

**Output:** writes `<dir>/weights.json`. Stdout: `{"history_rows",
"weighted_signatures"}`.

#### `ts aggregate generate`

Emit the DDL and TML for one approved candidate — never imports; the calling skill
gates each import separately.

**DDL SELECT source (default: AgentQL):** builds an AgentQL statement for the
candidate's grain and asks ThoughtSpot to compile it against the primary Model
(`--model-guid`/`--profile`) — this resolves joins against the full semantic
model, so it's correct on role-playing/ambiguous-path dimensions where the
built-in join walker (`sqlgen.build_select`) can silently be wrong. Falls back
to that walker automatically if AgentQL generation is unavailable or errors, or
always with `--no-spotql`; a fallback prints a stderr note that the result may
be wrong on such dimensions.

**RLS propagation (Task 23):** before anything is written, extracts row-level
security from the `--tables-dir` Table TMLs. It **fails closed** (`exit 1`, nothing
written) in two cases: (1) the `--tables-dir` didn't load a Table TML for every
`model_tables` entry, so RLS can't even be assessed (an empty/incomplete dir would
otherwise read as "no RLS" and emit an unsecured aggregate — a fail-open); or (2) any
base table carries `rls_rules` and the candidate's grain still omits a required filter
column. Otherwise the base rule(s) are remapped onto the aggregate's own grain columns
and attached to `table.tml.yaml`'s `table.rls_rules` (and `table_spec.json`'s
`rls_rules` key); a no-op only when the tables-dir fully covers the model and no covered
base table carries RLS. No dedicated flag for the force-add path — the calling skill
applies `ts_cli.aggregate.rls.add_rls_columns_to_candidate` directly to
`candidates.json` before calling `generate`, so `generate` just reads the
already-widened candidate.

```bash
ts aggregate generate --dir /tmp/agg --candidate cand_3 \
  --model-guid abc-123 --tables-dir /tmp/agg/tables \
  --db ANALYTICS --schema PUBLIC --connection-name "Snowflake Prod" \
  --profile prod --materialization auto
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--dir` | — | Directory from `recommend`/`profile` (required) |
| `--candidate` | — | Candidate id, e.g. `cand_3` (required) |
| `--model-guid` | — | Primary Model GUID, re-exported fresh to patch `aggregated_models` (required) |
| `--tables-dir` | — | Directory of exported Table TMLs (required) |
| `--db` | — | Target database for the aggregate table (required) |
| `--schema` | — | Target schema for the aggregate table (required) |
| `--connection-name` | — | ThoughtSpot connection display name (required) |
| `--profile` / `-p` | `TS_PROFILE` env var | ThoughtSpot profile (used to re-export the primary Model) |
| `--dialect` | `snowflake` | SQL dialect |
| `--materialization` | `auto` | `auto` \| `ctas` \| `dynamic` — a Snowflake dynamic table requires `--warehouse` |
| `--warehouse` | — | Warehouse for a dynamic table materialization |
| `--agg-name` | derived from root table + grain | Override the aggregate table/model base name |
| `--out-dir` | `<dir>/<candidate>` | Output directory |
| `--agg-model-guid` | — | Aggregate Model's GUID, once known (import `agg_model.tml.yaml` first, then pass its returned GUID here). Used as the `aggregated_models` association `id` — the aggregate Model and its backing Table share a name, so a name-based id is ambiguous (`DUPLICATE_OBJECT_FOUND` on a live cluster). Omit on the first, pre-import pass; a stderr warning flags the name-based fallback. |
| `--no-spotql` | `false` | Skip AgentQL SQL generation and use the built-in join walker directly — see the DDL SELECT source note above |

**Output:** writes `ddl.sql`, `table_spec.json`, `table.tml.yaml`,
`agg_model.tml.yaml`, and `primary_patched.tml.yaml` (the primary Model TML with the
new `aggregated_models` entry patched in) to `--out-dir`. Stdout: `{"candidate",
"aggregate_name", "files"}`.
### `ts tableau build-liveboard`

Emit Answer + tabbed-Liveboard TML deterministically from a parsed Tableau dashboard
spec — the codified replacement for the LLM-executed chart/liveboard prose templates
(SKILL.md Step 10). Role-aware axis layout (Columns→x, Color→series/color, Rows→pivot
rows, measures→y), a chart-type requirement floor (flags a chart that lacks the measures
it needs — never silently downgrades it), and overrides capture-and-replay (per-column
`format`, `client_state_v2`, the authoritative `custom_chart_config` for combos, and
`viz_style`). The ThoughtSpot-side emission is ported from the verified standalone Power BI
converter (`_answer_tml`/`_answer_tml_explicit`/`_liveboard_tml`).

```bash
ts tableau build-liveboard --input dashboard_spec.json --output-dir ./out
```

**Input** (`--input`): a JSON dashboard spec — see `build_from_spec` in
`ts_cli/tableau/liveboard.py` for the full shape:

```json
{
  "report_name": "Sales Report", "model_name": "Sales Model", "model_fqn": null,
  "measure_names": ["Total Sales"],
  "dashboards": [
    {"name": "Overview", "visuals": [
      {"title": "Sales by Region", "mark": "bar",
       "fields": [{"name": "Region", "shelf": "columns", "measure": false},
                  {"name": "Total Sales", "measure": true},
                  {"name": "Segment", "role": "Series"}],
       "tile": {"x": 0, "y": 0, "width": 6, "height": 8}}
    ]}
  ]
}
```

- Each field carries a Tableau `shelf` (`columns`/`rows`/`color`) — mapped to a
  canonical role — or an explicit `role` that wins over the shelf. `measure: true`
  columns always land on y.
- A visual may carry an `override` (verbatim answer spec) for anything the auto-builder
  can't express. `tile` is the Step 9c grid placement; omit it for a two-per-row layout.
- `extra_visuals[]` (top level) adds tiles that have no Tableau source visual.

**Two live-verified emission rules (v0.55.0):**
- **Bucketed dates** — a `bucket_tokens` entry like `{"Order Date": "[Order Date].monthly"}`
  puts the token in `search_query` but references the **resolved** output column
  (`Month(Order Date)`) in chart/axis/table — the raw name won't match the search output and
  errors `Invalid GUID string` on import. Bare (unbucketed) dates are fine by their raw name.
- **Combos** — emit `ADVANCED_LINE_COLUMN` + both measures on `axis`; ThoughtSpot auto-resolves
  line vs column. **Do not hand-author `custom_chart_config`** — its column refs are GUIDs
  (assigned after an answer exists), so a display-name config fails a fresh import. The command
  **drops** a display-name `custom_chart_config` and replays only a genuine captured
  (GUID-based) one. To pin an exact split: import → tune in UI → export → replay the exported
  config via the visual's `override`.

**Output:** writes `{report}.liveboard.tml` (with every answer embedded) to `--output-dir`.
Stdout: JSON `{report_name, n_answers, n_tabs, liveboard_file, visual_rows, page_rows}` —
`visual_rows`/`page_rows` feed the Step 12 migration report.

### `ts tableau verify`

Source↔output migration-fidelity gate: diffs the *parsed* Tableau workbook against the
*generated* Model TML to catch silent drops (a table/join/translatable formula the
workbook had but the TML doesn't) and mistranslations (a TML formula that barely
resembles its Tableau source) — the two failure classes a coverage count computed from
the TWB alone, or a server-side `VALIDATE_ONLY` import, cannot see (an import gate only
sees what was emitted; it has no idea what the source contained).

```bash
ts tableau verify --parse parsed.json --model out/orders.model.tml
```

| Flag | Required | Notes |
|---|---|---|
| `--parse`, `--input`, `-i` | yes | `ts tableau parse` output JSON (`--input` accepted as an alias, matching `build-liveboard`'s convention) |
| `--model`, `-m` | yes | The generated `*.model.tml` file to verify |

Runs four checks (implemented in `ts_cli/tableau/verify.py::verify_conversion`, pure —
no Tableau/ThoughtSpot connection):

1. **structural** — datasources→model, physical tables/custom-SQL→`model_tables`, join
   counts, and a translatable/untranslatable formula split via
   `ts_cli/tableau/classify.py::classify_formulas` (so this can never disagree with
   `classify-formulas`/`build-model`). ERROR when a translatable formula, physical
   table, or custom-SQL relation is missing from the generated TML.
2. **formula_equivalence** — for each translatable formula, token-normalizes both the
   raw Tableau expression and its TML translation and scores an LCS-based similarity
   (MATCH ≥85%, PARTIAL 50–84%, LOW <50%, MISSING). PARTIAL/LOW are candidate
   mistranslations flagged for manual review.
3. **validity** — reuses `ts_cli/tml_lint.py::lint_tml` (I1/I2/I4/I5/I8) — no invariant
   logic is re-implemented here. Model↔table-TML dangling-reference checking (a
   `columns[].column_id` that no longer resolves on its table TML) is a separate concern,
   covered by `ts tml lint --dir`.
4. **limitation_coverage** — reports how many untranslatable formulas were detected.
   Advisory only (`ts tableau verify` has no `--limitations`/report-list input today).

A formula tiered `UNTRANSLATABLE` by `classify_formulas` (geospatial, circular, orphan,
parameter-query, or genuinely untranslatable) is *expected* to be absent from
`model.formulas` and is never counted as a drop.

**Output:** the full report as JSON to stdout (`{"ok", "checks": [{"name", "severity",
"findings"}], "summary"}`); a human-readable summary to stderr. Exit code is non-zero if
any check carries an ERROR-severity finding.

---

## `ts qlik` — Qlik Sense → ThoughtSpot converter

Converts a Qlik Sense app into ThoughtSpot Table + Model TML and a tabbed
Liveboard. Mirrors the `ts tableau` converter's conventions: structured JSON to
stdout, diagnostics to stderr, pure conversion logic in `ts_cli.qlik`. Four
extraction modes, all producing the same IR that `build-model` / `build-liveboard`
consume:

| `--mode` | `<source>` | Live? | Options |
|---|---|---|---|
| `offline` (default) | a `.qvf` file (SQLite layout when present, else best-effort byte-scan) | no | — |
| `engine-artifacts` | a directory of JSON dumped by the headless-engine extractor | no | — |
| `qlik-cloud` | *(omit)* | yes | `--tenant <url>` + `--app-id <guid|name>` + `--api-key` (or `QLIK_API_KEY`) |
| `engine` | *(omit)* | yes | `--engine <ws-url>` + `--app-id <guid>` + optional repeatable `--header k=v` |

Offline extraction degrades gracefully — an opaque `.qvf` yields warnings,
never a crash. The two **live** modes (`qlik-cloud` REST + QIX, `engine`
JSON-RPC over websocket) require the optional extra:

```bash
pip install 'thoughtspot-cli[qlik]'    # adds websocket-client
```

Invoking a live mode without it fails with that exact remediation message. The
Qlik Cloud API key is read from `--api-key` or `QLIK_API_KEY` only — it is never
printed, echoed, or written to a file. For the live modes the positional
`<source>` is omitted; `qlik-cloud` requires `--tenant` + `--app-id`, `engine`
requires `--engine` + `--app-id`.

### `ts qlik parse`

Parse a Qlik app into a structured inventory JSON.

```bash
ts qlik parse App.qvf -o app.inventory.json
ts qlik parse ./engine-output -o app.inventory.json --mode engine-artifacts
ts qlik parse -o app.inventory.json --mode qlik-cloud \
  --tenant https://acme.us.qlikcloud.com --app-id <guid>   # QLIK_API_KEY in env
ts qlik parse -o app.inventory.json --mode engine \
  --engine wss://host/app --app-id <guid> --header "Authorization=Bearer <t>"
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--output`, `-o` | — | Output inventory JSON path (required) |
| `--mode` | `offline` | `offline` \| `engine-artifacts` \| `qlik-cloud` \| `engine` |
| `--tenant` | — | Qlik Cloud tenant URL (`qlik-cloud` mode) |
| `--app-id` | — | Qlik app GUID (`qlik-cloud`/`engine`); `qlik-cloud` also accepts an app name |
| `--api-key` | env `QLIK_API_KEY` | Qlik Cloud API key (`qlik-cloud` mode); never printed |
| `--engine` | — | Qlik Engine websocket URL, e.g. `wss://host/app` (`engine` mode) |
| `--header` | — | Extra websocket header `k=v` (`engine` mode); repeatable |

The `--mode` / `--tenant` / `--app-id` / `--api-key` / `--engine` / `--header`
flags apply identically to `build-model` and `build-liveboard` below.

**Output:** writes `{app_name, extraction_mode, connections, tables, columns,
measures, dimensions, variables, sheets, charts, counts, warnings}` to the
output file; prints the `counts` object to stdout, warnings to stderr.

### `ts qlik build-model`

Build import-ready Table TML(s) + Model TML + `mapping.json` from a Qlik app.
Translates Qlik master-measure expressions to ThoughtSpot formulas
(`[formula_<name>]` id-refs), honours the TML invariants (`db_column_name` on
every column, connection `name:` only, `formula_id` linkage, `aggregation:` in
`columns[]` only). Anything not faithfully translatable is flagged
`NEEDS REVIEW` in `mapping.json` with the original Qlik expression retained —
never silently downgraded.

```bash
ts qlik build-model App.qvf -c "Snowflake_Sales" --db SALES_DB --schema PUBLIC -o ./tml_out
ts qlik build-model App.qvf -c "Snowflake_Sales" --db DB --schema SCH -o ./tml_out \
  --model-name "Sales" --types wh_types.json
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--connection`, `-c` | — | ThoughtSpot connection display NAME, never a GUID (required) |
| `--db` | — | Warehouse database for the table TML(s) (required) |
| `--schema` | — | Warehouse schema for the table TML(s) (required) |
| `--output`, `-o` | — | Output directory for TML + `mapping.json` (required) |
| `--model-name` | Qlik app name | Model name |
| `--overrides` | — | JSON file whose top-level keys replace parsed IR values (hand-edited IR) |
| `--types` | — | JSON `{TABLE:{COLUMN:ts_type}}` of real warehouse types to avoid type guessing |
| `--mode` | `offline` | `offline` \| `engine-artifacts` \| `qlik-cloud` \| `engine` (+ the live-mode flags above) |

**Output:** writes `table.<name>.tml` (one per table), `model.<name>.tml`, and
`mapping.json` to the output directory; prints a counts summary JSON to stdout.

### `ts qlik build-liveboard`

Build an Answer + tabbed Liveboard from a Qlik app's sheets/charts — one tab per
Qlik sheet, each chart an embedded Answer whose search query is assembled from
its dimensions + measures. A Qlik viz type with no ThoughtSpot equivalent
defaults to a table and is flagged `NEEDS REVIEW`.

```bash
ts qlik build-liveboard App.qvf -o ./tml_out --model-name "Sales"
ts qlik build-liveboard App.qvf -o ./tml_out --model-name "Sales" \
  --model-fqn <model-guid> --report-name "Exec Dashboard"
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--output`, `-o` | — | Output directory for the Liveboard TML + `liveboard_mapping.json` (required) |
| `--model-name` | — | Name of the ThoughtSpot model the Answers query (required) |
| `--model-fqn` | — | GUID of the model (added as `fqn` on the Answer table refs) |
| `--report-name` | model name | Liveboard name |
| `--overrides` | — | JSON file whose top-level keys replace parsed IR values (hand-edited IR) |
| `--mode` | `offline` | `offline` \| `engine-artifacts` \| `qlik-cloud` \| `engine` (+ the live-mode flags above) |

**Output:** writes `liveboard.<name>.tml` and `liveboard_mapping.json` to the
output directory; prints a counts summary JSON to stdout.

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

### `ts load databricks`

Provision table(s) + synthetic data into a Databricks `catalog.schema` (Unity Catalog), so a
ThoughtSpot Databricks connection can bind a model over them. Auth via a Databricks profile in
`~/.claude/databricks-profiles.json` (`dbx_profile`, `sql_warehouse_http_path`, `catalog`,
`schema`); the token lives in `~/.databrickscfg` (`databricks auth login`), never in the
profile file. Execution goes through the `databricks` CLI's SQL Statement Execution API.

```
ts load databricks --source ./orders_demo_schema.json --profile sisense-dbx --rows 200
```

Infers the schema from `--source` (manifest / schema JSON / CSV dir), generates deterministic
synthetic rows, then `CREATE TABLE` (Delta **column mapping** enabled — preserves column names
with spaces/special chars like `Order Date` 1:1) + batched `INSERT`.

| Flag | Default | Description |
|---|---|---|
| `--source`, `-s` | — | Schema/manifest JSON or CSV dir (required) |
| `--profile`, `-p` | — | Databricks profile name (required) |
| `--catalog` / `--schema` | from profile | Override target catalog/schema |
| `--rows`, `-r` | `100` | Synthetic rows per table |
| `--batch` | `200` | Rows per `INSERT` statement |

> **Connection caveat (live-verified):** for a ThoughtSpot model to bind to the new table, the
> connection must expose it. A **SERVICE_ACCOUNT** Databricks connection introspects it
> automatically; an **OAuth/PKCE** connection returns an empty API hierarchy (a ThoughtSpot
> limitation), so the new table must be **selected in the ThoughtSpot connection editor (UI)**
> before `ts tables create` / model build can reference it.

### `ts powerbi parse` / `build-model` / `build-liveboard`

The Power BI (`.pbip`) to ThoughtSpot converter for the `ts-convert-from-powerbi` skill.
Mirrors the Tableau converter: `parse` reads the project into structured JSON, `build-model`
emits import-ready Table + Model TML (DAX translated to ThoughtSpot formulas), and
`build-liveboard` emits Answer + tabbed-Liveboard TML from the report pages. The
ThoughtSpot-side emission reuses the shared `dump_tml_yaml` and `tableau.liveboard.build_from_spec`,
so both BI converters produce identical TML shapes. Pure conversion logic lives in
`ts_cli/powerbi/*`; only I/O and typer wiring live in `commands/powerbi.py`.

#### `ts powerbi parse`

Parse a `.pbip` project (TMDL semantic model + PBIR report) into structured JSON:
tables/columns/measures/relationships and pages/visuals. Anything the parser cannot
confidently read is listed under `warnings` rather than guessed.

```bash
ts powerbi parse ./MyReport.pbip --output parsed.json
```

| Flag | Required | Description |
|---|---|---|
| `pbip_dir` (arg) | yes | Path to the `.pbip` project folder |
| `--output`, `-o` | yes | Output parsed JSON path |

Stdout: JSON `counts` object (pipeable). Warnings go to stderr.

#### `ts powerbi build-model`

Build Table + Model TML (and `mapping.json`) from a `.pbip`. Parses the project, translates
DAX to ThoughtSpot formulas (`[formula_<name>]` id-refs, topo-sorted), emits joins with the
real relationship cardinality, honours `summarizeBy` for AVG-vs-SUM, and enables Spotter.
The connection block carries `name:` only (never `fqn:`).

```bash
ts powerbi build-model ./MyReport.pbip \
  --connection "MY_CONNECTION" \
  --db WAREHOUSE_DB --schema WAREHOUSE_SCHEMA \
  --output ./tml_out \
  --model-name "My Model"
```

| Flag | Required | Description |
|---|---|---|
| `pbip_dir` (arg) | yes | Path to the `.pbip` project folder |
| `--connection`, `-c` | yes | ThoughtSpot connection display name the tables bind to |
| `--db` | yes | Warehouse database |
| `--schema` | yes | Warehouse schema |
| `--output`, `-o` | yes | Output dir for `.tml` + `mapping.json` |
| `--model-name` | no | Name for the generated Model (default: derived) |
| `--join-type` | no | Join type for relationships (default: `LEFT_OUTER`, keeps fact rows) |
| `--overrides` | no | `overrides.json` (hand-authored `ts_formula` / connection / `table_map` / parameters) |
| `--lower-db-table` | no | Lowercase `db_table` (Databricks folds unquoted names) |

Stdout: JSON counts (`tables`, `model`, `measures`, `migrated`, `approximated`,
`needs_review`). A measure whose DAX cannot be translated is flagged `NEEDS REVIEW`
(never silently downgraded). `mapping.json` records per-object status + notes.

#### `ts powerbi build-liveboard`

Emit Answer + tabbed-Liveboard TML from a `.pbip`'s report pages, reusing the shared
`build_from_spec` (role-aware axes: Category to x, Series to color, Rows/Columns to pivot,
measures to y; chart-needs floor; override capture-and-replay). Report pages become tabs in
PBI `pageOrder`; a Tooltip page is dropped, not a tab.

```bash
ts powerbi build-liveboard ./MyReport.pbip \
  --output ./tml_out \
  --model-name "My Model" \
  --model-fqn <model-guid>
```

| Flag | Required | Description |
|---|---|---|
| `pbip_dir` (arg) | yes | Path to the `.pbip` project folder |
| `--output`, `-o` | yes | Directory for the emitted `.liveboard.tml` |
| `--model-name` | yes | Model name the answers bind to (must match `build-model`) |
| `--model-fqn` | no | Model GUID to bind to (optional; more robust than name) |
| `--report-name` | no | Liveboard name (default: derived from model) |
| `--connection`, `-c` | no | Connection name (for the in-memory model build) |
| `--db` / `--schema` | no | Warehouse db/schema (for the in-memory model build) |
| `--overrides` | no | `overrides.json` (explicit answers / extra_visuals) |

Stdout: JSON counts (`report_name`, `answers`, `tabs`, `visuals_migrated`,
`approximated`, `needs_review`, `liveboard`). A chart type with no faithful ThoughtSpot
equivalent is emitted as its nearest approximation and flagged `Approximated` or
`NEEDS REVIEW`, matching the Tableau path's "flag, never downgrade" contract.

---

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

### `ts snowflake exec`

Execute a `.sql` template (or inline query) against a Snowflake profile. Backs
the `ts-recipe-formula-*-snowflake` skills, which keep their UDF DDL in
`references/*.sql` files instead of markdown fences the agent retypes each run.
Works with both `python` and `cli` profile methods and reuses the same connector
as `ts load` (so credentials never drift).

```bash
ts snowflake exec -f references/business-day-udfs.sql --sf-profile PROD \
  --var target_db=ANALYTICS --var target_schema=PUBLIC
ts snowflake exec -q "SELECT ANALYTICS.PUBLIC.get_business_days_clamped(
  '2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, FALSE)" --sf-profile PROD
```

| Option | Default | Description |
|---|---|---|
| `--file` / `-f` | — | Path to a `.sql` file to execute |
| `--query` / `-q` | — | Inline SQL (mutually exclusive with `--file`); reads stdin if neither is given |
| `--sf-profile` | *(required)* | Snowflake profile name from `~/.claude/snowflake-profiles.json` |
| `--var` | — | Placeholder substitution as `name=value` (repeatable); fills `{name}` tokens in the SQL |
| `--warehouse` / `-w` | profile `default_warehouse` | Warehouse override |
| `--role` / `-r` | profile `default_role` | Role override |

`{name}` placeholders are filled from `--var` before execution; any placeholder
left without a value aborts the run rather than shipping a literal
`{target_schema}` to Snowflake. Statements run in file order and stop at the
first error (so a dependent UDF is not created after the function it references
failed).

**Output:** JSON to stdout — `{"profile", "method", "statement_count",
"results": [{"rows": [...]}, ...], "rows": <last result set's rows>}`. The
top-level `rows` is a convenience for single-query verifies. Diagnostics go to
stderr.

### `ts snowflake parse-sv`

Parse a Snowflake Semantic View DDL string (from `GET_DDL('SEMANTIC_VIEW', ...)`)
into structured JSON for the `ts-convert-from-snowflake-sv` skill. Codifies
Step 4: tables (aliases, PKs, range constraints, subquery sources), relationships
(equi/range/asof), dimensions, metrics (semi-additive, window, USING), facts,
custom instructions, verified queries, and extension JSON.

```bash
ts snowflake parse-sv sv.sql --output parsed.json
cat sv.sql | ts snowflake parse-sv - --output parsed.json
```

| Option | Default | Description |
|---|---|---|
| `ddl_file` | *(required)* | Path to a DDL file, or `-` for stdin |
| `--output` / `-o` | *(required)* | Output JSON path |

Exits 1 when `unsupported[]` is non-empty (list on stderr; JSON still written).
Emits BL-100 prerequisite warnings for `sample_values`/`is_enum` (DDL clause
shape unverified against live `GET_DDL`).

**Output:** JSON to the `--output` file — `{"view_name", "database", "schema",
"name", "comment", "tables", "relationships", "dimensions", "metrics", "facts",
"custom_instructions", "verified_queries", "extension", "warnings",
"unsupported"}`. Summary line to stderr.

---

### `ts snowflake translate-formulas`

Translate Snowflake SQL formulas from a parsed Semantic View (output of
`ts snowflake parse-sv`) into ThoughtSpot formula syntax. Codifies
ts-convert-from-snowflake-sv SKILL.md Step 9: identifier resolution,
function mapping (DATEDIFF/DATEADD/CASE/CAST/DIV0/COUNT_IF/window functions),
column classification (ATTRIBUTE/MEASURE, column/formula), semi-additive
wrapping (last_value/first_value), and USING relationship group_aggregate.

```bash
ts snowflake translate-formulas --input parsed.json --output translated.json
```

| Option | Default | Description |
|---|---|---|
| `--input` / `-i` | *(required)* | Path to parsed SV JSON from `parse-sv` |
| `--output` / `-o` | *(required)* | Output translated JSON path |

**Output:** JSON to the `--output` file — `{"translated": [...],
"skipped": [...], "stats": {"total", "translated", "skipped"}}`.
Each translated entry: `{name, role, output_kind, column_type, table,
column, ts_expr, aggregation, comment, synonyms, is_private, annotations}`.
Stats JSON to stdout; skipped entries and diagnostics to stderr.

---

### `ts snowflake introspect`

Query Snowflake INFORMATION_SCHEMA for the source tables referenced by a parsed
Semantic View and build the artifacts the downstream pipeline needs. Codifies
ts-convert-from-snowflake-sv Steps 6A–6C: Snowflake type → ThoughtSpot type
mapping, tables-spec assembly for `ts tables create`, and a tables map for
`ts snowflake build-model`.

```bash
ts snowflake introspect --parsed parsed.json --sf-profile PROD \
  --connection-name "My Snowflake" --output-dir ./output
cat output/tables-spec.json | ts tables create --profile my-ts
ts snowflake build-model --tables output/tables.json ...
```

| Option | Default | Description |
|---|---|---|
| `--parsed` | *(required)* | Path to parsed SV JSON from `parse-sv` |
| `--sf-profile` | *(required)* | Snowflake profile name |
| `--connection-name` | *(required)* | ThoughtSpot connection display name (stamped on every table spec) |
| `--output-dir` | *(required)* | Directory for `tables-spec.json` and `tables.json` |
| `--warehouse` | profile default | Warehouse override |
| `--role` | profile default | Role override |

**Outputs:**
- `tables-spec.json` — JSON array for `ts tables create` stdin
- `tables.json` — `{alias: {name}}` map for `ts snowflake build-model --tables`
  (enrich with GUIDs from `ts tables create` output before calling build-model)

**Output (stdout):** JSON summary — `{tables, total_columns, warnings,
tables_spec_file, tables_map_file, connection_name}`.

---

### `ts snowflake build-model`

Assemble a ThoughtSpot Model TML from the outputs of `ts snowflake parse-sv` and
`ts snowflake translate-formulas`, then import it via two-pass import. Codifies
ts-convert-from-snowflake-sv SKILL.md Steps 10–11: inline Scenario B joins
(equi/range/ASOF), SV synonym→display name, private column handling, fact table
detection, and the two-pass import flow (structure-only → GUID capture → full
model with formulas + `--no-create-new`).

```bash
ts snowflake build-model \
  --parsed parsed.json --translated translated.json \
  --tables tables.json --model-name "Sales Model" \
  --sv-fqn DB.SCHEMA.SALES_SV --profile my-ts \
  --output-dir ./output
```

| Option | Default | Description |
|---|---|---|
| `--parsed` | *(required)* | Path to parsed SV JSON from `parse-sv` |
| `--translated` | *(required)* | Path to translated JSON from `translate-formulas` |
| `--tables` | *(required)* | Path to tables JSON map (`{alias: {name, fqn}}` or `{alias: name}`) |
| `--model-name` | *(required)* | Display name for the ThoughtSpot model |
| `--output-dir` | *(required)* | Directory to write the model TML YAML file |
| `--sv-fqn` | — | Fully-qualified SV name for the model description |
| `--spotter-enabled` / `--no-spotter-enabled` | enabled | Enable/disable Spotter (AI search) on the model |
| `--existing-guid` | — | GUID of an existing model to update (skips phase 1 create) |
| `--profile` | — | ThoughtSpot profile for import |
| `--dry-run` | `false` | Write TML files only, skip import |

**Output:** JSON summary to stdout — `{model_name, model_guid, formula_count,
attribute_count, measure_count, phase1, phase2, tml_path, build_info}`.
Phase 1 is skipped when `--existing-guid` is supplied or when the model has no
formulas.

---

### `ts snowflake build-sv`

Build a Snowflake Semantic View DDL from exported ThoughtSpot Model + Table TMLs.
Codifies ts-convert-to-snowflake-sv Steps 5–8: column_id resolution to physical
column names, classification (dimension/metric/time_dimension), `to_snake`
aliasing, relationship naming with collision avoidance, metric topological
ordering, DDL assembly with tables/relationships/dimensions/metrics clauses, and
Cortex Analyst extension JSON.

```bash
ts tml export {model_guid} --parse --associated --output-dir ./export
ts snowflake build-sv --model export/model.json \
  --tables-dir export/ --sv-name DB.SCHEMA.MY_SV \
  --output my_sv.sql
```

| Option | Default | Description |
|---|---|---|
| `--model` | *(required)* | Path to Model TML JSON (from `ts tml export --parse`) |
| `--tables-dir` | *(required)* | Directory with Table TML JSON files |
| `--sv-name` | *(required)* | Fully-qualified SV name (e.g. `DB.SCHEMA.MY_SV`) |
| `--output` | *(required)* | Output `.sql` file path |
| `--formulas` | — | Pre-translated formulas JSON (`{formula_id: {expr, kind}}`) |

Formulas without a matching entry in `--formulas` are omitted from the DDL
and logged as skipped. Join type/cardinality attributes are dropped (logged as
unmapped). Pipe the output to `ts snowflake lint-ddl` for validation, then
`ts snowflake exec` to create the view.

**Output (stdout):** JSON summary — `{sv_name, ddl_file, dimensions,
time_dimensions, metrics, relationship_count, skipped_formulas,
dropped_join_attrs, unmapped_properties}`.

---

### `ts databricks parse-mv`

Parse a Databricks Metric View YAML definition (v0.1 or v1.1) into structured
JSON for the `ts-convert-from-databricks-mv` skill. Offline — the YAML is
fetched beforehand via the external `databricks` CLI (`DESCRIBE TABLE
EXTENDED`, `View Text` row).

```bash
ts databricks parse-mv mv.yaml --output parsed.json
cat mv.yaml | ts databricks parse-mv - --output parsed.json
```

Covers: version routing (`0.1`/`1.1` normalized to one shape), source-form
classification (table FQN / parenthesized SQL / bare SQL — FQNs carry
`needs_live_check: true` because MV-on-MV cannot be ruled out offline),
`fields:`/`dimensions:` alias, dimension classification
(direct/computed/LOD-window), measure classification (simple / COUNT
DISTINCT / COUNT(*) / conditional FILTER / cross-measure / complex /
windowed with all five `range` values + `inclusive|exclusive` anchor +
`offset`), nested `joins:` walk (`on`/`using` XOR, `cardinality:`/`rely:`
precedence), `materialization:` pass-through, global `filter:`.

Exit codes: `0` = parsed clean (warnings, if any, on stderr); `1` = one or
more `unsupported[]` constructs (listed on stderr; JSON still written), or
the input file is missing or unreadable (no JSON written).
Every `trailing`/`leading` window measure gets `density_check_required:
true` plus a stderr WARNING — Databricks date-interval frames vs
ThoughtSpot row-positional `moving_sum` diverge on gapped data (BL-098).

### `ts databricks translate-formulas`

Translate a `parse-mv` result into ThoughtSpot formula text for the
`ts-convert-from-databricks-mv` skill. Deterministic — no LLM in the loop:
dot-path column resolution, the `ts-databricks-formula-translation.md`
function map, conditional (`FILTER (WHERE …)`) aggregates, LOD `group_aggregate`
windows, the full window decision tree (trailing/leading/cumulative/current,
post-PR-1 corrected forms), cross-measure (`MEASURE()`/`ANY_VALUE()`)
inlining in dependency order (Databricks needs no phased import), and
JSON colon-path access (`col:a.b`, `parse_json(col):a.b`) rewritten to a
`get_json_object` pass-through (ThoughtSpot rejects the colon syntax).

```bash
ts databricks translate-formulas \
  --input parsed.json \
  --output translated.json \
  --tables '{"source": "TRANSACTIONS", "orders": "DM_ORDER"}'
```

| Option | Required | Meaning |
|---|---|---|
| `--input` / `-i` | yes | `parsed.json` produced by `ts databricks parse-mv` |
| `--output` / `-o` | yes | Output path for the translated formulas JSON |
| `--tables` / `-t` | yes | JSON object mapping MV alias paths to ThoughtSpot table names — a `"source"` key is required (the MV's base table alias); nested join aliases (e.g. `"orders.customers"`) map to their joined ThoughtSpot table |

**Output:** `{"translated": [...], "skipped": [...], "filter": {...}|null,
"dependency_dag": {...}, "window_measures": [...], "stats": {"total":
n, "translated": n, "skipped": n}}`. Every dimension/measure lands in
`translated[]` (with `ts_expr`/`table`+`column`, `aggregation`, and any
`annotations`) or `skipped[]` (with a `reason` string) — nothing is silently
dropped.

Exit codes: `0` — every dimension/measure was processed, whether translated
or skipped (skips are a reported outcome via `skipped[]`, not a failure);
`1` — the `--input`/`--tables` file is missing or unreadable, or `--tables`
is not a valid JSON object with a `"source"` key.

Every `trailing`/`leading` window translation emits a `sparse_data_risk`
annotation plus a stderr WARNING (BL-098): a Databricks date-interval frame
maps to ThoughtSpot's row-positional `moving_sum`/`moving_average`/etc., so
the numbers only match when the order column is dense at the window's grain
(no gaps) — verify density before trusting the translation.

### `ts databricks build-model`

Assemble ThoughtSpot Model (+ Table) TML from a `parse-mv` + `translate-formulas`
pair for the `ts-convert-from-databricks-mv` skill, validate it, and optionally
import it. Deterministic assembly only — no LLM in the loop.

```bash
ts databricks build-model \
  --parsed parsed.json --translated translated.json --tables tables.json \
  --connection "Databricks Analytics" --model-name "Transactions_MV_Model" \
  --output-dir out/
```

| Option | Required | Meaning |
|---|---|---|
| `--parsed` / `-p` | yes | `parsed.json` from `ts databricks parse-mv` |
| `--translated` / `-t` | yes | `translated.json` from `ts databricks translate-formulas` |
| `--tables` | yes | Same `tables.json` used for `translate-formulas` — values may be plain strings or v2 objects (`{"name", "fqn", "create", "db", "schema", "db_table", "columns"}`) |
| `--connection` / `-c` | yes | ThoughtSpot connection display name (used only for `create: true` table TML) |
| `--model-name` / `-n` | yes | Model TML `name:` |
| `--output-dir` / `-o` | yes | Directory for the generated `.model.tml` / `.table.tml` files |
| `--mv-fqn` | no | Source MV FQN, appended to the model description |
| `--spotter-enabled` / `--no-spotter-enabled` | no | Tri-state; omitted means no `spotter_config` block at all |
| `--existing-guid` | no | Stamps `guid:` at the document root (update-in-place, not a MERGE) |
| `--profile` | no | Import the model TML after a clean lint (`ts tml import --policy PARTIAL`) |
| `--dry-run` | no | With `--profile`: assemble + lint but skip the import |

A `create: true` table whose columns[] end up empty after Databricks-type
omissions (e.g. every column is `binary`/`array`/`map`/`struct`) is a hard
error naming the table and the omitted columns — this is caught before any
file is written.

**Output:** a summary JSON on stdout (the only stdout output — diagnostics are
on stderr): `model_name`, `model_file`, `table_files`, `connection`, `tables[]`,
`columns` (`attributes`/`measures`), `formula_count`, `window_measures[]`,
`skipped[]`, `name_renames`, `filter_applied`, `spotter_enabled`,
`existing_guid`, `invariant_findings[]`, `lint_findings[]`, `import_status`
(`not_requested`|`dry_run`|`imported`|`failed`), `model_guid`, and
`import_error` (only when `import_status` is `failed`).

TML files are always written to `--output-dir` even when invariant/lint
findings are non-empty, so the user can inspect what was generated.

Exit codes: `0` — clean lint (and, if `--profile` was given, a successful or
skipped import); `1` — a builder `ValueError` (bad alias, duplicate formula
title, unsupported join), the zero-column-table guard, non-empty
`invariant_findings`/`lint_findings`, an unreadable/invalid input file, or an
import failure.

### `ts databricks build-mv`

Emit Databricks Metric View `.sql` file(s) (`CREATE OR REPLACE VIEW ... WITH
METRICS`) from an exported ThoughtSpot Model, for the `ts-convert-to-databricks-mv`
skill. Emit-only — no ThoughtSpot or Databricks profile is used or needed, and
no DDL is ever executed; it reads local Model/Table TML JSON and writes local
`.sql` files.

```bash
ts databricks build-mv \
  --model model.json --tables tables.json \
  --catalog analytics --schema sales \
  --output-dir out/
```

| Option | Required | Meaning |
|---|---|---|
| `--model` / `-m` | yes | Exported Model TML JSON (`{"model": {...}}`, or a bare model dict) |
| `--tables` | yes | Associated Table TML JSON list (`[{"table": {...}}, ...]`) |
| `--catalog` | yes | Databricks catalog for the MV's source table and the view itself |
| `--schema` | yes | Databricks schema for the MV's source table and the view itself |
| `--output-dir` / `-o` | yes | Directory for the generated `.sql` file(s) |
| `--source-table` | no | Fact table to build the MV for; omit to emit one MV per fact table `mv_emit.detect_fact_tables` finds (a table carrying ≥1 MEASURE column that is not itself the join target of another table) |
| `--view-name` | no | Override the generated view name — only honoured when exactly one MV is being emitted (a single `--source-table`, or a model with exactly one detected fact) |

Each fact produces one `{view_name}.sql` file in `--output-dir` (default name
`{model}_{fact}_mv`, via `mv_build_view.default_view_name`). A fact table this
model has no MEASURE column for, or that a formula fails to translate for,
naturally lands in that MV's `skipped[]` rather than aborting the whole run.

**Output:** a summary JSON on stdout (the only stdout output — diagnostics are
on stderr): `model_name`, `metric_views[]` (`view_name`, `source`, `dimensions`,
`measures`, `filter_applied`, `file`), `skipped[]`, `warnings[]` — the
`mv_build_view.build_summary` shape.

Exit codes: `0` — every produced MV has at least one measure; `1` — no fact
table could be found (no `--source-table` and no MEASURE column anywhere in
the model), an unreadable/invalid `--model`/`--tables` file, a structural
`ValueError` while building an MV (e.g. a duplicate emitted column name, or
the `build_view_ddl` `$$`-collision guard), or any produced MV ends up with
zero measures.
